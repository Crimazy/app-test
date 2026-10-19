"""Reinforced concrete column design engine per ACI 318-19 (SI units).

Internal units : N, mm, MPa (N/mm^2).  Axial force: compression positive.
Moment signs   : Mx = sum(F * y)  -> positive Mx compresses the +y face
                 My = sum(F * x)  -> positive My compresses the +x face

Main references (ACI 318-19)
  10.6.1.1   longitudinal reinforcement limits 0.01Ag - 0.08Ag
  10.7.3.1   minimum number of longitudinal bars
  19.2.2.1   Ec = 4700 sqrt(fc')
  21.2.2     strength reduction factor phi (Table 21.2.2)
  22.2       flexure + axial: strain compatibility, eps_cu = 0.003, beta1
  22.4.2     maximum axial strength Pn,max = 0.80Po (ties) / 0.85Po (spirals)
  22.5       one-way shear strength
  6.2.5      slenderness limits,  6.6.4  moment magnification
  25.2.3     minimum clear spacing of longitudinal bars
  25.7.2     ties,  25.7.3 spirals
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

EPS_CU = 0.003
ES_DEFAULT = 200_000.0  # MPa

# Thai standard (TIS 24 / TIS 20) bar designations -> nominal diameter (mm)
BAR_SIZES = {
    "DB12": 12, "DB16": 16, "DB20": 20, "DB25": 25, "DB28": 28,
    "DB32": 32, "DB36": 36, "DB40": 40,
}
TIE_SIZES = {"RB6": 6, "RB9": 9, "DB10": 10, "DB12": 12, "DB16": 16}

KSC_TO_MPA = 0.0980665
TONF_TO_KN = 9.80665


def bar_area(d: float) -> float:
    return math.pi * d * d / 4.0


def beta1(fc: float) -> float:
    """Table 22.2.2.4.3."""
    if fc <= 28.0:
        return 0.85
    if fc >= 55.0:
        return 0.65
    return 0.85 - 0.05 * (fc - 28.0) / 7.0


def concrete_modulus(fc: float) -> float:
    """19.2.2.1(b), normal-weight concrete."""
    return 4700.0 * math.sqrt(fc)


def phi_factor(eps_t: float | np.ndarray, fy: float, Es: float, spiral: bool):
    """Table 21.2.2 - phi for moment, axial force, or combined."""
    ety = fy / Es
    phi_c = 0.75 if spiral else 0.65
    eps_t = np.asarray(eps_t, dtype=float)
    phi = phi_c + (0.90 - phi_c) * (eps_t - ety) / 0.003
    return np.clip(phi, phi_c, 0.90)


# --------------------------------------------------------------------------
# Input data
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ColumnInput:
    shape: str = "rect"          # "rect" | "circular"
    b: float = 400.0             # rect: width along x (mm)
    h: float = 400.0             # rect: depth along y (mm)
    D: float = 500.0             # circular diameter (mm)
    cover: float = 40.0          # clear cover to transverse reinforcement (mm)
    fc: float = 28.0             # MPa
    fy: float = 420.0            # longitudinal bars, MPa
    fyt: float = 420.0           # transverse bars, MPa
    Es: float = ES_DEFAULT
    bar_d: float = 20.0          # longitudinal bar diameter (mm)
    nx: int = 3                  # rect: bars per face parallel to x (incl. corners)
    ny: int = 3                  # rect: bars per face parallel to y (incl. corners)
    n_circ: int = 8              # circular: total number of bars
    transverse: str = "tied"     # "tied" | "spiral"
    tie_d: float = 10.0          # tie / spiral diameter (mm)
    s: float = 200.0             # tie spacing / spiral pitch (mm)
    legs_x: int = 2              # tie legs parallel to x (resist Vx)
    legs_y: int = 2              # tie legs parallel to y (resist Vy)
    agg: float = 20.0            # nominal max. aggregate size (mm)
    lam: float = 1.0             # lightweight factor lambda

    @property
    def is_circular(self) -> bool:
        return self.shape == "circular"

    @property
    def is_spiral(self) -> bool:
        return self.is_circular and self.transverse == "spiral"

    @property
    def edge(self) -> float:
        """Distance from concrete face to centre of longitudinal bar."""
        return self.cover + self.tie_d + self.bar_d / 2.0


@dataclass(frozen=True)
class SlendernessInput:
    sway: bool = False            # False = braced (nonsway) frame
    lu_x: float = 3000.0          # unsupported length for bending about x (mm)
    lu_y: float = 3000.0          # unsupported length for bending about y (mm)
    k_x: float = 1.0
    k_y: float = 1.0
    m1m2_x: float = -0.5          # M1/M2 (ACI 318-19: negative = single curvature)
    m1m2_y: float = -0.5
    beta_dns: float = 0.6
    delta_s_x: float = 1.0        # sway magnifier from frame analysis (sway frames)
    delta_s_y: float = 1.0
    transverse_load: bool = False  # transverse loads between supports -> Cm = 1.0


@dataclass
class LoadCase:
    name: str
    Pu: float   # N  (compression +)
    Mux: float  # N*mm
    Muy: float  # N*mm
    Vux: float = 0.0  # N, shear acting along x
    Vuy: float = 0.0  # N, shear acting along y


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------
def _clip_halfplane(poly: np.ndarray, u: np.ndarray, k: float) -> np.ndarray:
    """Sutherland-Hodgman: keep the part of a polygon with p.u >= k."""
    out = []
    n = len(poly)
    for i in range(n):
        P, Q = poly[i], poly[(i + 1) % n]
        dp, dq = P @ u - k, Q @ u - k
        if dp >= 0:
            out.append(P)
        if dp * dq < 0:
            t = dp / (dp - dq)
            out.append(P + t * (Q - P))
    return np.array(out) if out else np.zeros((0, 2))


def _poly_area_centroid(poly: np.ndarray):
    if len(poly) < 3:
        return 0.0, 0.0, 0.0
    x, y = poly[:, 0], poly[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y1 - x1 * y
    A = cross.sum() / 2.0
    if abs(A) < 1e-9:
        return 0.0, 0.0, 0.0
    cx = ((x + x1) * cross).sum() / (6.0 * A)
    cy = ((y + y1) * cross).sum() / (6.0 * A)
    return abs(A), cx, cy


# --------------------------------------------------------------------------
# Section
# --------------------------------------------------------------------------
class ColumnSection:
    def __init__(self, inp: ColumnInput):
        self.inp = inp
        self.Ab = bar_area(inp.bar_d)
        self.bars = self._bar_layout()
        self.n_bars = len(self.bars)
        self.Ast = self.n_bars * self.Ab
        if inp.is_circular:
            self.R = inp.D / 2.0
            self.Ag = math.pi * inp.D ** 2 / 4.0
            self.poly = None
        else:
            b2, h2 = inp.b / 2.0, inp.h / 2.0
            self.Ag = inp.b * inp.h
            self.poly = np.array([[-b2, -h2], [b2, -h2], [b2, h2], [-b2, h2]])
        self.rho = self.Ast / self.Ag
        self.beta1 = beta1(inp.fc)
        self.Ec = concrete_modulus(inp.fc)
        # 22.4.2
        self.Po = 0.85 * inp.fc * (self.Ag - self.Ast) + inp.fy * self.Ast
        self.alpha_max = 0.85 if inp.is_spiral else 0.80
        self.Pn_max = self.alpha_max * self.Po
        self.phi_c = 0.75 if inp.is_spiral else 0.65
        self.phiPn_max = self.phi_c * self.Pn_max
        self.Pnt = -inp.fy * self.Ast
        self.phiPnt = 0.90 * self.Pnt

    # ---- layout --------------------------------------------------------
    def _bar_layout(self) -> np.ndarray:
        inp = self.inp
        e = inp.edge
        if inp.is_circular:
            rb = inp.D / 2.0 - e
            ang = math.pi / 2 + 2 * math.pi * np.arange(inp.n_circ) / inp.n_circ
            return np.column_stack([rb * np.cos(ang), rb * np.sin(ang)])
        xs = np.linspace(-inp.b / 2 + e, inp.b / 2 - e, inp.nx)
        ys = np.linspace(-inp.h / 2 + e, inp.h / 2 - e, inp.ny)
        pts = [(x, ys[0]) for x in xs] + [(x, ys[-1]) for x in xs]
        pts += [(xs[0], y) for y in ys[1:-1]] + [(xs[-1], y) for y in ys[1:-1]]
        return np.array(pts, dtype=float)

    def clear_spacing(self) -> float:
        """Smallest clear distance between adjacent longitudinal bars (mm)."""
        inp = self.inp
        if inp.is_circular:
            rb = inp.D / 2.0 - inp.edge
            return 2 * rb * math.sin(math.pi / inp.n_circ) - inp.bar_d
        sx = (inp.b - 2 * inp.edge) / (inp.nx - 1) - inp.bar_d
        sy = (inp.h - 2 * inp.edge) / (inp.ny - 1) - inp.bar_d
        return min(sx, sy)

    def face_clear_spacing(self) -> tuple[float, float]:
        inp = self.inp
        sx = (inp.b - 2 * inp.edge) / (inp.nx - 1) - inp.bar_d
        sy = (inp.h - 2 * inp.edge) / (inp.ny - 1) - inp.bar_d
        return sx, sy

    # ---- strain compatibility -----------------------------------------
    def _extreme(self, u: np.ndarray):
        if self.inp.is_circular:
            return self.R, -self.R
        d = self.poly @ u
        return d.max(), d.min()

    def _concrete_block(self, u: np.ndarray, dmax: float, a: float):
        """Resultant of 0.85fc' Whitney block of depth a measured from extreme fibre."""
        fc = self.inp.fc
        if a <= 0:
            return 0.0, 0.0, 0.0
        if self.inp.is_circular:
            R = self.R
            a = min(a, 2 * R)
            alpha = math.acos((R - a) / R)
            area = R * R * (alpha - math.sin(alpha) * math.cos(alpha))
            if area <= 0:
                return 0.0, 0.0, 0.0
            dist = 2 * R * math.sin(alpha) ** 3 / (3 * (alpha - math.sin(alpha) * math.cos(alpha)))
            F = 0.85 * fc * area
            return F, F * dist * u[1], F * dist * u[0]
        comp = _clip_halfplane(self.poly, u, dmax - a)
        area, cx, cy = _poly_area_centroid(comp)
        F = 0.85 * fc * area
        return F, F * cy, F * cx

    def point(self, theta: float, c: float) -> dict:
        """Nominal strength for a neutral axis at angle theta (compression direction)
        and depth c measured from the extreme compression fibre."""
        inp = self.inp
        u = np.array([math.cos(theta), math.sin(theta)])
        dmax, dmin = self._extreme(u)
        H = dmax - dmin
        a = min(self.beta1 * c, H)
        Fc, Mcx, Mcy = self._concrete_block(u, dmax, a)
        yb = dmax - self.bars @ u
        eps = EPS_CU * (c - yb) / c
        fs = np.clip(inp.Es * eps, -inp.fy, inp.fy)
        fs = fs - np.where(yb <= a, 0.85 * inp.fc, 0.0)  # displaced concrete
        F = fs * self.Ab
        P = Fc + F.sum()
        Mx = Mcx + (F * self.bars[:, 1]).sum()
        My = Mcy + (F * self.bars[:, 0]).sum()
        dt = yb.max()
        eps_t = EPS_CU * (dt - c) / c
        phi = float(phi_factor(eps_t, inp.fy, inp.Es, inp.is_spiral))
        return dict(P=P, Mx=Mx, My=My, eps_t=eps_t, phi=phi, c=c)

    def curve(self, theta: float, n_c: int = 60) -> dict:
        """Interaction curve for one neutral-axis direction, from pure tension to Po."""
        inp = self.inp
        u = np.array([math.cos(theta), math.sin(theta)])
        dmax, dmin = self._extreme(u)
        H = dmax - dmin
        cs = np.geomspace(0.02 * H, 4.0 * H, n_c)
        rows = [dict(P=self.Pnt, Mx=0.0, My=0.0, eps_t=np.inf, phi=0.90, c=0.0)]
        rows += [self.point(theta, c) for c in cs]
        rows.append(dict(P=self.Po, Mx=0.0, My=0.0, eps_t=-EPS_CU, phi=self.phi_c, c=np.inf))
        out = {k: np.array([r[k] for r in rows], dtype=float) for k in rows[0]}
        out["phiP"] = np.minimum(out["phi"] * out["P"], self.phiPn_max)
        out["phiMx"] = out["phi"] * out["Mx"]
        out["phiMy"] = out["phi"] * out["My"]
        return out

    def surface(self, n_angles: int = 72, n_c: int = 60) -> dict:
        thetas = np.linspace(0, 2 * math.pi, n_angles, endpoint=False)
        curves = [self.curve(t, n_c) for t in thetas]
        return {k: np.vstack([cv[k] for cv in curves]) for k in curves[0]} | {"theta": thetas}


# --------------------------------------------------------------------------
# Capacity at a given axial load
# --------------------------------------------------------------------------
def moment_contour(surf: dict, Pu: float) -> np.ndarray:
    """phi*Mn contour (Mx, My) at phi*Pn = Pu; empty if Pu outside the diagram."""
    pts = []
    phiP, mx, my = surf["phiP"], surf["phiMx"], surf["phiMy"]
    for i in range(phiP.shape[0]):
        d = phiP[i] - Pu
        cand = []
        for j in range(len(d) - 1):
            if d[j] == 0:
                cand.append((mx[i, j], my[i, j]))
            elif d[j] * d[j + 1] < 0:
                t = d[j] / (d[j] - d[j + 1])
                cand.append((mx[i, j] + t * (mx[i, j + 1] - mx[i, j]),
                             my[i, j] + t * (my[i, j + 1] - my[i, j])))
        if cand:
            # several crossings are possible where phi varies; keep the smallest (conservative)
            pts.append(min(cand, key=lambda p: math.hypot(*p)))
    return np.array(pts) if pts else np.zeros((0, 2))


def ray_capacity(contour: np.ndarray, mx: float, my: float) -> float:
    """Magnitude of the capacity contour in the direction of (mx, my)."""
    if len(contour) < 3:
        return 0.0
    norm = math.hypot(mx, my)
    if norm == 0:
        return 0.0
    dx, dy = mx / norm, my / norm
    order = np.argsort(np.arctan2(contour[:, 1], contour[:, 0]))
    poly = contour[order]
    best = 0.0
    for i in range(len(poly)):
        p1, p2 = poly[i], poly[(i + 1) % len(poly)]
        ex, ey = p2 - p1
        det = -dx * ey + ex * dy
        if abs(det) < 1e-12:
            continue
        t = (-p1[0] * ey + ex * p1[1]) / det
        s = (dx * p1[1] - dy * p1[0]) / det
        if -1e-9 <= s <= 1 + 1e-9 and t > best:
            best = t
    return best


# --------------------------------------------------------------------------
# Slenderness (6.2.5, 6.6.4)
# --------------------------------------------------------------------------
def slenderness_axis(sec: ColumnSection, sl: SlendernessInput, axis: str, Pu: float, Mu: float) -> dict:
    inp = sec.inp
    if axis == "x":
        lu, k, m1m2, ds = sl.lu_x, sl.k_x, sl.m1m2_x, sl.delta_s_x
        depth = inp.D if inp.is_circular else inp.h
        width = inp.D if inp.is_circular else inp.b
    else:
        lu, k, m1m2, ds = sl.lu_y, sl.k_y, sl.m1m2_y, sl.delta_s_y
        depth = inp.D if inp.is_circular else inp.b
        width = inp.D if inp.is_circular else inp.h
    if inp.is_circular:
        r = 0.25 * inp.D
        Ig = math.pi * inp.D ** 4 / 64.0
    else:
        r = 0.30 * depth
        Ig = width * depth ** 3 / 12.0
    klu_r = k * lu / r
    if sl.sway:
        limit = 22.0
    else:
        limit = min(34.0 + 12.0 * m1m2, 40.0)
    slender = klu_r > limit
    out = dict(axis=axis, lu=lu, k=k, r=r, klu_r=klu_r, limit=limit, slender=slender,
               Mu=abs(Mu), Mc=abs(Mu), delta=1.0, Pc=None, Cm=None, M2min=None,
               EI=None, ok=True, note="ไม่ชะลูด - ไม่ต้องขยายโมเมนต์ (short column)")
    if not slender:
        return out
    EI = 0.4 * sec.Ec * Ig / (1.0 + sl.beta_dns)          # 6.6.4.4.4(a)
    Pc = math.pi ** 2 * EI / (k * lu) ** 2                # 6.6.4.4.2
    out.update(EI=EI, Pc=Pc)
    if sl.sway:
        Mc = ds * abs(Mu)
        out.update(delta=ds, Mc=Mc,
                   note="Sway frame: ใช้ δs จากการวิเคราะห์โครงข้อแข็ง (6.6.4.6) คูณโมเมนต์ทั้งหมด (อนุรักษ์)")
    else:
        M2min = max(Pu, 0.0) * (15.0 + 0.03 * depth)       # 6.6.4.5.4
        M2 = abs(Mu)
        Cm = 1.0 if (sl.transverse_load or M2 < M2min) else 0.6 - 0.4 * m1m2  # 6.6.4.5.3
        M2 = max(M2, M2min)
        if Pu >= 0.75 * Pc:
            out.update(Cm=Cm, M2min=M2min, delta=math.inf, Mc=math.inf, ok=False,
                       note="Pu ≥ 0.75Pc : เสาไม่มีเสถียรภาพ - ต้องขยายหน้าตัด")
            return out
        delta = max(Cm / (1.0 - Pu / (0.75 * Pc)), 1.0)    # 6.6.4.5.2
        out.update(Cm=Cm, M2min=M2min, delta=delta, Mc=delta * M2,
                   note="Nonsway frame: ขยายโมเมนต์ตาม 6.6.4.5")
    if abs(Mu) > 0 and out["Mc"] / abs(Mu) > 1.4 and not (out["M2min"] and out["M2min"] > abs(Mu)):
        out["ok"] = False
        out["note"] += " | โมเมนต์ลำดับที่สอง > 1.4 เท่าของลำดับที่หนึ่ง (6.2.5.3) - ต้องขยายหน้าตัด"
    return out


# --------------------------------------------------------------------------
# Shear (22.5)
# --------------------------------------------------------------------------
def shear_check(sec: ColumnSection, Nu: float, Vu: float, direction: str) -> dict:
    inp = sec.inp
    lam = inp.lam
    sqrt_fc = min(math.sqrt(inp.fc), 8.3)                  # 22.5.3.1
    fyt = min(inp.fyt, 420.0)                              # 20.2.2.4
    At = bar_area(inp.tie_d)
    if inp.is_circular:
        bw, d = inp.D, 0.8 * inp.D                         # 22.5.2.2
        Av = 2 * At
        As_t = sec.Ast / 2.0
    else:
        if direction == "x":
            bw, d, legs = inp.h, inp.b - inp.edge, inp.legs_x
            As_t = inp.ny * sec.Ab
        else:
            bw, d, legs = inp.b, inp.h - inp.edge, inp.legs_y
            As_t = inp.nx * sec.Ab
        Av = legs * At
    Ag = sec.Ag
    s = inp.s
    Av_min = max(0.062 * sqrt_fc, 0.35) * bw * s / fyt     # 10.6.2.2
    axial = min(Nu / (6.0 * Ag), 0.05 * inp.fc)            # 22.5.5.1 (Nu/6Ag <= 0.05fc')
    if Av >= Av_min:
        Vc = (0.17 * lam * sqrt_fc + axial) * bw * d        # Table 22.5.5.1 (a)
        eq = "22.5.5.1(a)"
    else:
        lam_s = min(math.sqrt(2.0 / (1.0 + 0.004 * d)), 1.0)
        rho_w = As_t / (bw * d)
        Vc = (0.66 * lam_s * lam * rho_w ** (1 / 3) * sqrt_fc + axial) * bw * d  # (c)
        eq = "22.5.5.1(c)"
    Vc = max(min(Vc, 0.42 * lam * sqrt_fc * bw * d), 0.0)
    Vs = Av * fyt * d / s                                  # 22.5.8.5.3
    Vs_max = 0.66 * sqrt_fc * bw * d                       # 22.5.1.2
    phi = 0.75
    phiVn = phi * (Vc + min(Vs, Vs_max))
    s_max = d / 2.0 if Vs <= 0.33 * sqrt_fc * bw * d else d / 4.0  # 10.7.6.5.2
    need_min = abs(Vu) > 0.5 * phi * Vc
    ok = abs(Vu) <= phiVn and Vs <= Vs_max and (not need_min or (Av >= Av_min and s <= s_max))
    return dict(direction=direction, bw=bw, d=d, Av=Av, Av_min=Av_min, Vc=Vc, Vs=Vs,
                Vs_max=Vs_max, phiVn=phiVn, Vu=abs(Vu), s_max=s_max, need_min=need_min,
                eq=eq, ok=ok, dcr=abs(Vu) / phiVn if phiVn > 0 else math.inf)


# --------------------------------------------------------------------------
# Detailing checks
# --------------------------------------------------------------------------
def _required_supported_bars(n: int, clear: float) -> int:
    """25.7.2.3: corners + alternate bars, none farther than 150 mm clear from a supported bar."""
    if clear > 150.0:
        return n
    return n // 2 + 1 if n % 2 == 0 else (n + 1) // 2


def detailing_checks(sec: ColumnSection) -> list[dict]:
    inp = sec.inp
    rows = []

    def add(clause, item, req, prov, ok):
        rows.append(dict(clause=clause, item=item, required=req, provided=prov, ok=bool(ok)))

    add("19.2.1.1", "กำลังอัดคอนกรีต fc'", "≥ 17 MPa", f"{inp.fc:.1f} MPa", inp.fc >= 17.0)
    add("20.2.2.4", "กำลังครากเหล็กยืน fy", "≤ 550 MPa", f"{inp.fy:.0f} MPa", inp.fy <= 550.0)
    add("10.6.1.1", "อัตราส่วนเหล็กยืน ρg", "0.01 – 0.08", f"{sec.rho:.4f}", 0.01 <= sec.rho <= 0.08)
    n_min = 6 if inp.is_spiral else 4
    add("10.7.3.1", "จำนวนเหล็กยืนขั้นต่ำ", f"≥ {n_min} เส้น", f"{sec.n_bars} เส้น", sec.n_bars >= n_min)
    s_cl_min = max(40.0, 1.5 * inp.bar_d, 4.0 / 3.0 * inp.agg)
    s_cl = sec.clear_spacing()
    add("25.2.3", "ระยะช่องว่างระหว่างเหล็กยืน", f"≥ {s_cl_min:.0f} mm", f"{s_cl:.0f} mm", s_cl >= s_cl_min)

    if inp.is_spiral:
        Dch = inp.D - 2 * inp.cover
        Ach = math.pi * Dch ** 2 / 4.0
        rho_s = 4 * bar_area(inp.tie_d) / (Dch * inp.s)
        rho_s_min = 0.45 * (sec.Ag / Ach - 1.0) * inp.fc / inp.fyt
        add("25.7.3.2", "ขนาดเหล็กปลอกเกลียว", "≥ 10 mm", f"{inp.tie_d:.0f} mm", inp.tie_d >= 9.5)
        clear_pitch = inp.s - inp.tie_d
        add("25.7.3.1", "ระยะช่องว่างปลอกเกลียว", "25 – 75 mm", f"{clear_pitch:.0f} mm",
            25.0 <= clear_pitch <= 75.0)
        add("25.7.3.3", "อัตราส่วนเหล็กปลอกเกลียว ρs", f"≥ {rho_s_min:.4f}", f"{rho_s:.4f}", rho_s >= rho_s_min)
        add("20.2.2.4", "กำลังครากเหล็กเกลียว fyt", "≤ 690 MPa", f"{inp.fyt:.0f} MPa", inp.fyt <= 690.0)
    else:
        tie_req = 10.0 if inp.bar_d <= 32 else 12.0
        add("25.7.2.2", "ขนาดเหล็กปลอก", f"≥ {tie_req:.0f} mm (No.{10 if tie_req == 10 else 13})",
            f"{inp.tie_d:.0f} mm", inp.tie_d >= tie_req)
        s_max = min(16 * inp.bar_d, 48 * inp.tie_d, inp.D if inp.is_circular else min(inp.b, inp.h))
        add("25.7.2.1", "ระยะเรียงเหล็กปลอก", f"≤ {s_max:.0f} mm", f"{inp.s:.0f} mm", inp.s <= s_max)
        if not inp.is_circular:
            sx, sy = sec.face_clear_spacing()
            req_y = _required_supported_bars(inp.nx, sx)  # legs parallel to y support bars along x-face
            req_x = _required_supported_bars(inp.ny, sy)
            add("25.7.2.3", "จำนวนขาปลอกขนานแกน y (ค้ำเหล็กด้าน b)", f"≥ {req_y} ขา",
                f"{inp.legs_y} ขา", inp.legs_y >= req_y)
            add("25.7.2.3", "จำนวนขาปลอกขนานแกน x (ค้ำเหล็กด้าน h)", f"≥ {req_x} ขา",
                f"{inp.legs_x} ขา", inp.legs_x >= req_x)
    return rows


# --------------------------------------------------------------------------
# Full design
# --------------------------------------------------------------------------
@dataclass
class CaseResult:
    case: LoadCase
    slx: dict
    sly: dict
    Mcx: float
    Mcy: float
    phiMn_dir: float
    phiMnx: float
    phiMny: float
    dcr_axial: float
    dcr_moment: float
    shear_x: dict
    shear_y: dict
    contour: np.ndarray = field(repr=False)

    @property
    def dcr(self) -> float:
        return max(self.dcr_axial, self.dcr_moment, self.shear_x["dcr"], self.shear_y["dcr"])

    @property
    def ok(self) -> bool:
        return (self.dcr <= 1.0 and self.slx["ok"] and self.sly["ok"]
                and self.shear_x["ok"] and self.shear_y["ok"])


def check_case(sec: ColumnSection, surf: dict, sl: SlendernessInput, lc: LoadCase) -> CaseResult:
    slx = slenderness_axis(sec, sl, "x", lc.Pu, lc.Mux)
    sly = slenderness_axis(sec, sl, "y", lc.Pu, lc.Muy)
    Mcx = math.copysign(slx["Mc"], lc.Mux if lc.Mux else 1.0)
    Mcy = math.copysign(sly["Mc"], lc.Muy if lc.Muy else 1.0)
    if not slx["slender"]:
        Mcx = lc.Mux
    if not sly["slender"]:
        Mcy = lc.Muy
    contour = moment_contour(surf, lc.Pu)
    dcr_axial = lc.Pu / sec.phiPn_max if lc.Pu >= 0 else lc.Pu / sec.phiPnt
    finite = math.isfinite(Mcx) and math.isfinite(Mcy)
    mag = math.hypot(Mcx, Mcy) if finite else math.inf
    phiMn_dir = ray_capacity(contour, Mcx, Mcy) if finite and mag > 0 else 0.0
    phiMnx = ray_capacity(contour, 1.0 if Mcx >= 0 else -1.0, 0.0)
    phiMny = ray_capacity(contour, 0.0, 1.0 if Mcy >= 0 else -1.0)
    if not finite:
        dcr_m = math.inf
    elif mag == 0:
        dcr_m = 0.0
    elif phiMn_dir <= 0:
        dcr_m = math.inf
    else:
        dcr_m = mag / phiMn_dir
    shx = shear_check(sec, lc.Pu, lc.Vux, "x")
    shy = shear_check(sec, lc.Pu, lc.Vuy, "y")
    return CaseResult(lc, slx, sly, Mcx, Mcy, phiMn_dir, phiMnx, phiMny,
                      dcr_axial, dcr_m, shx, shy, contour)


def design(inp: ColumnInput, sl: SlendernessInput, loads: list[LoadCase],
           n_angles: int = 72, n_c: int = 60, surf: dict | None = None):
    sec = ColumnSection(inp)
    if surf is None:
        surf = sec.surface(n_angles, n_c)
    cases = [check_case(sec, surf, sl, lc) for lc in loads]
    detail = detailing_checks(sec)
    return sec, surf, cases, detail


def auto_select(base: ColumnInput, sl: SlendernessInput, loads: list[LoadCase],
                bar_names=("DB16", "DB20", "DB25", "DB28", "DB32"), max_per_face: int = 8):
    """Search the lightest longitudinal layout that passes all strength and detailing checks."""
    cands = []
    for name in bar_names:
        d = BAR_SIZES[name]
        if base.is_circular:
            for n in range(6 if base.is_spiral else 4, 25):
                cands.append(ColumnInput(**{**base.__dict__, "bar_d": d, "n_circ": n}))
        else:
            for nx in range(2, max_per_face + 1):
                for ny in range(2, max_per_face + 1):
                    cands.append(ColumnInput(**{**base.__dict__, "bar_d": d, "nx": nx, "ny": ny}))

    def screen(c: ColumnInput):
        sec = ColumnSection(c)
        if not 0.01 <= sec.rho <= 0.08:
            return None
        if sec.clear_spacing() < max(40.0, 1.5 * c.bar_d, 4.0 / 3.0 * c.agg):
            return None
        return sec

    screened = [(c, s) for c in cands if (s := screen(c)) is not None]
    screened.sort(key=lambda cs: (cs[1].Ast, cs[1].n_bars))
    for c, sec in screened:
        # keep tie legs adequate for the candidate layout
        if not c.is_circular:
            sx, sy = sec.face_clear_spacing()
            c = ColumnInput(**{**c.__dict__,
                               "legs_y": max(c.legs_y, _required_supported_bars(c.nx, sx)),
                               "legs_x": max(c.legs_x, _required_supported_bars(c.ny, sy))})
            sec = ColumnSection(c)
        surf = sec.surface(24, 36)
        results = (check_case(sec, surf, sl, lc) for lc in loads)
        if all(r.dcr_axial <= 1.0 and r.dcr_moment <= 0.97 for r in results):
            return c
    return None
