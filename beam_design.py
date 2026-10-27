"""Reinforced concrete beam design engine (SI units).

Internal units : N, mm, MPa (N/mm^2).
Moment sign    : positive = sagging (bottom face in tension),
                 negative = hogging (top face in tension).

Two design codes are supported:

  "ACI318-19"  ACI 318-19
               U = 1.4D, 1.2D + 1.6L                       (5.3.1)
               phi by net tensile strain eps_t              (Table 21.2.2)
               eps_t >= 0.004 for beams                     (9.3.3.1)
               Vc per Table 22.5.5.1 incl. size effect      (22.5.5.1)
  "DPT1103"    มยผ. 1103 strength design (วิธีกำลัง), whose beam provisions
               follow ACI 318-99:
               U = 1.4D + 1.7L                              (9.2.1)
               phi = 0.90 flexure, 0.85 shear               (9.3.2)
               rho <= 0.75 rho_b (+ rho' fs'/fy)            (10.3.3)
               Vc = (1/6) sqrt(fc') bw d                    (11.3.1.1)

Shared provisions (same intent in both editions)
  As,min = max(0.25 sqrt(fc'), 1.4) bw d / fy, or 4/3 As,req
  Whitney stress block 0.85fc', beta1, eps_cu = 0.003
  minimum depth for deflection (L/16, L/18.5, L/21, L/8) x (0.4 + fy/700)
  clear spacing of bars >= max(25 mm, db, 4/3 d_agg)
  crack-control bar spacing, skin reinforcement for h > 900 mm
  stirrup spacing d/2 <= 600 mm (d/4 <= 300 mm for high shear)
  tension development length (simplified tables)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

EPS_CU = 0.003
ES_DEFAULT = 200_000.0  # MPa
GAMMA_C = 24.0          # unit weight of reinforced concrete, kN/m^3

ACI = "ACI318-19"
DPT = "DPT1103"
CODES = {
    ACI: "ACI 318-19",
    DPT: "มยผ. 1103 วิธีกำลัง (ACI 318-99)",
}

# Thai standard (TIS 24 / TIS 20) bar designations -> nominal diameter (mm)
MAIN_BARS = {"DB12": 12, "DB16": 16, "DB20": 20, "DB25": 25, "DB28": 28, "DB32": 32}
STIRRUPS = {"RB6": 6, "RB9": 9, "DB10": 10, "DB12": 12}

KSC_TO_MPA = 0.0980665
TONF_TO_KN = 9.80665


def bar_area(d: float) -> float:
    return math.pi * d * d / 4.0


def beta1(fc: float) -> float:
    """ACI 318-19 Table 22.2.2.4.3 (identical to ACI 318-99 10.2.7.3)."""
    if fc <= 28.0:
        return 0.85
    if fc >= 55.0:
        return 0.65
    return 0.85 - 0.05 * (fc - 28.0) / 7.0


def concrete_modulus(fc: float) -> float:
    """Ec = 4700 sqrt(fc') MPa, normal-weight concrete (19.2.2.1 / 8.5.1)."""
    return 4700.0 * math.sqrt(fc)


def phi_flexure(code: str, eps_t: float, fy: float, Es: float = ES_DEFAULT) -> float:
    if code == DPT:
        return 0.90
    ety = fy / Es
    phi = 0.65 + 0.25 * (eps_t - ety) / 0.003
    return min(max(phi, 0.65), 0.90)


def phi_shear(code: str) -> float:
    return 0.85 if code == DPT else 0.75


# Load-factor choice shared by the beam pages
LOAD_PRESETS = {
    "code": "ตามมาตรฐานที่เลือก",
    "1.4/1.7": "1.4D + 1.7L (ACI 318-99 / วสท. / มยผ. 1103)",
    "1.2/1.6": "1.2D + 1.6L (ACI 318-19)",
    "custom": "กำหนดเอง",
}


def preset_factors(preset: str, custom: tuple[float, float] | None = None) -> tuple[float, float] | None:
    """(fD, fL) for a LOAD_PRESETS key; None = follow the design code."""
    if preset == "1.4/1.7":
        return 1.4, 1.7
    if preset == "1.2/1.6":
        return 1.2, 1.6
    if preset == "custom" and custom:
        return float(custom[0]), float(custom[1])
    return None


def load_combinations(code: str, D: float, L: float,
                      factors: tuple[float, float] | None = None) -> list[tuple[str, float]]:
    """Gravity load combinations; D and L in any consistent unit.

    factors = (fD, fL) overrides the code combination; 1.4D is always checked as well
    when fD < 1.4 (as in ACI 318-19 5.3.1a).
    """
    if factors is None:
        factors = (1.4, 1.7) if code == DPT else (1.2, 1.6)
    fD, fL = factors
    combos = [(f"{fD:g}D + {fL:g}L", fD * D + fL * L)]
    if fD < 1.4:
        combos.insert(0, ("1.4D", 1.4 * D))
    return combos


def factored_load(code: str, D: float, L: float,
                  factors: tuple[float, float] | None = None) -> tuple[str, float]:
    return max(load_combinations(code, D, L, factors), key=lambda c: abs(c[1]))


# --------------------------------------------------------------------------
# Input data
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Layer:
    n: int = 0
    d: float = 16.0

    @property
    def area(self) -> float:
        return self.n * bar_area(self.d)


@dataclass(frozen=True)
class Reinforcement:
    """Reinforcement at one design location."""
    top1: Layer = Layer(2, 16)
    top2: Layer = Layer(0, 16)
    bot1: Layer = Layer(3, 20)
    bot2: Layer = Layer(0, 20)
    s: float = 150.0             # stirrup spacing (mm)


@dataclass(frozen=True)
class BeamInput:
    code: str = ACI
    bw: float = 300.0            # web width (mm)
    h: float = 600.0             # overall depth (mm)
    tbeam: bool = False          # T-beam with flange at the top
    bf: float = 1000.0           # effective flange width (mm)
    hf: float = 120.0            # flange (slab) thickness (mm)
    cover: float = 40.0          # clear cover to stirrups (mm)
    fc: float = 24.0             # MPa
    fy: float = 392.0            # main bars, MPa
    fyt: float = 235.0           # stirrups, MPa
    Es: float = ES_DEFAULT
    agg: float = 20.0            # nominal max. aggregate size (mm)
    lam: float = 1.0             # lightweight concrete factor lambda
    stirrup_d: float = 9.0       # stirrup diameter (mm)
    legs: int = 2                # stirrup legs

    @property
    def flange(self) -> bool:
        return self.tbeam and self.bf > self.bw and self.hf > 0


@dataclass(frozen=True)
class Location:
    name: str
    Mu: float                    # N*mm, signed (+ sagging, - hogging)
    Vu: float                    # N, at the critical section
    reinf: Reinforcement = field(default_factory=Reinforcement)


# --------------------------------------------------------------------------
# Section
# --------------------------------------------------------------------------
def _block(rects, a: float) -> tuple[float, float]:
    """Area and centroid depth of the part of `rects` within depth a from the face."""
    A = Ay = 0.0
    for y0, y1, w in rects:
        lo, hi = y0, min(y1, a)
        if hi > lo:
            A += w * (hi - lo)
            Ay += w * (hi - lo) * (lo + hi) / 2.0
    return A, (Ay / A if A > 0 else 0.0)


class BeamSection:
    def __init__(self, inp: BeamInput, reinf: Reinforcement):
        self.inp, self.reinf = inp, reinf
        h = inp.h
        if inp.flange:
            self.rects = [(0.0, inp.hf, inp.bf), (inp.hf, h, inp.bw)]
        else:
            self.rects = [(0.0, h, inp.bw)]
        self.beta1 = beta1(inp.fc)
        self.Ec = concrete_modulus(inp.fc)

        edge = inp.cover + inp.stirrup_d
        r = reinf
        # (area, depth from top, face, layer, n, db)
        self.bars = []
        if r.top1.n:
            self.bars.append((r.top1.area, edge + r.top1.d / 2, "top", 1, r.top1.n, r.top1.d))
        if r.top2.n:
            y = edge + r.top1.d + self.layer_gap(r.top1, r.top2) + r.top2.d / 2
            self.bars.append((r.top2.area, y, "top", 2, r.top2.n, r.top2.d))
        if r.bot1.n:
            self.bars.append((r.bot1.area, h - edge - r.bot1.d / 2, "bot", 1, r.bot1.n, r.bot1.d))
        if r.bot2.n:
            y = h - (edge + r.bot1.d + self.layer_gap(r.bot1, r.bot2) + r.bot2.d / 2)
            self.bars.append((r.bot2.area, y, "bot", 2, r.bot2.n, r.bot2.d))

        A = sum(w * (y1 - y0) for y0, y1, w in self.rects)
        self.Ag = A
        self.ybar = sum(w * (y1 - y0) * (y0 + y1) / 2 for y0, y1, w in self.rects) / A
        self.Ig = sum(w * (y1 - y0) ** 3 / 12 + w * (y1 - y0) * ((y0 + y1) / 2 - self.ybar) ** 2
                      for y0, y1, w in self.rects)

    @staticmethod
    def layer_gap(l1: Layer, l2: Layer) -> float:
        """Clear vertical distance between layers >= 25 mm and >= db (25.2.2 / 7.6.2)."""
        return max(25.0, l1.d, l2.d)

    # -- orientation helpers --------------------------------------------
    def oriented(self, sign: int):
        """Concrete rects and bars measured from the compression face."""
        h = self.inp.h
        tface = "bot" if sign > 0 else "top"
        if sign > 0:
            rects = self.rects
            bars = [(A, y, f == tface) for A, y, f, *_ in self.bars]
        else:
            rects = sorted((h - y1, h - y0, w) for y0, y1, w in self.rects)
            bars = [(A, h - y, f == tface) for A, y, f, *_ in self.bars]
        return rects, bars

    def tension_steel(self, sign: int) -> tuple[float, float, float]:
        """(As, d, dt) of the tension-face bars for the moment sign."""
        _, bars = self.oriented(sign)
        t = [(A, y) for A, y, ten in bars if ten]
        if not t:
            edge = self.inp.cover + self.inp.stirrup_d
            d = self.inp.h - edge - 10.0
            return 0.0, d, d
        As = sum(A for A, _ in t)
        return As, sum(A * y for A, y in t) / As, max(y for _, y in t)

    def compression_steel(self, sign: int) -> float:
        _, bars = self.oriented(sign)
        return sum(A for A, _, ten in bars if not ten)

    # -- strain compatibility ------------------------------------------
    def _state(self, rects, bars, c: float):
        inp = self.inp
        a = min(self.beta1 * c, inp.h)
        Ac, yc = _block(rects, a)
        Cc = 0.85 * inp.fc * Ac
        N, M = Cc, -Cc * yc
        steel = []
        for A, y in bars:
            eps = EPS_CU * (c - y) / c
            fs = max(-inp.fy, min(inp.fy, inp.Es * eps))
            F = A * fs
            if y < a and fs > 0:
                F -= A * 0.85 * inp.fc   # concrete displaced by compression bars
            N += F
            M -= F * y
            steel.append((A, y, eps, fs, F))
        return N, M, a, Cc, yc, steel

    def _solve(self, rects, bars):
        """Neutral-axis depth c from force equilibrium (bisection)."""
        lo, hi = 1e-3, 5.0 * self.inp.h
        for _ in range(80):
            c = 0.5 * (lo + hi)
            if self._state(rects, bars, c)[0] > 0:
                hi = c
            else:
                lo = c
        return 0.5 * (lo + hi)

    def _analyze(self, rects, bars, dt: float) -> dict:
        c = self._solve(rects, bars)
        N, Mn, a, Cc, yc, steel = self._state(rects, bars, c)
        eps_t = EPS_CU * (dt - c) / c
        phi = phi_flexure(self.inp.code, eps_t, self.inp.fy, self.inp.Es)
        return dict(c=c, a=a, Cc=Cc, yc=yc, Mn=max(Mn, 0.0), eps_t=eps_t, phi=phi,
                    phiMn=phi * max(Mn, 0.0), steel=steel)

    def flexure(self, sign: int) -> dict:
        """Nominal and design moment strength for sagging (+1) or hogging (-1)."""
        inp = self.inp
        rects, bars = self.oriented(sign)
        As, d, dt = self.tension_steel(sign)
        if As <= 0:
            res = dict(c=0.0, a=0.0, Cc=0.0, yc=0.0, Mn=0.0, eps_t=math.inf,
                       phi=phi_flexure(inp.code, 1.0, inp.fy, inp.Es), phiMn=0.0, steel=[])
        else:
            res = self._analyze(rects, [(A, y) for A, y, _ in bars], dt)
        res.update(As=As, d=d, dt=dt, As_comp=self.compression_steel(sign),
                   As_max=self.as_max(sign), As_min=self.as_min(sign), sign=sign,
                   compression_flange=inp.flange and sign > 0)
        res["rho"] = As / (inp.bw * d)
        return res

    # -- reinforcement limits ------------------------------------------
    def as_min(self, sign: int) -> float:
        """9.6.1.2 (ACI 318-19) / 10.5.1 (ACI 318-99)."""
        inp = self.inp
        _, d, _ = self.tension_steel(sign)
        return max(0.25 * math.sqrt(inp.fc), 1.4) / inp.fy * inp.bw * d

    def as_max(self, sign: int) -> float:
        """Largest tension steel area allowed by the ductility rule of the code.

        DPT1103 : As <= 0.75 Asb(concrete) + As' fs'b / fy   (ACI 318-99 10.3.3)
        ACI     : As giving eps_t = 0.004 at d                (9.3.3.1)
        """
        inp = self.inp
        rects, bars = self.oriented(sign)
        _, d, dt = self.tension_steel(sign)
        comp = [(A, y) for A, y, ten in bars if not ten]
        if inp.code == DPT:
            cb = EPS_CU * d / (EPS_CU + inp.fy / inp.Es)
            Ac, _ = _block(rects, self.beta1 * cb)
            Cs = sum(A * max(0.0, min(inp.fy, inp.Es * EPS_CU * (cb - y) / cb)) for A, y in comp)
            return (0.75 * 0.85 * inp.fc * Ac + Cs) / inp.fy
        c = EPS_CU * d / (EPS_CU + 0.004)
        N_comp, *_ = self._state(rects, comp, c)
        return N_comp / inp.fy

    def required_as(self, Mu: float, sign: int) -> dict:
        """Tension steel (lumped at the provided d) needed for |Mu|, with the provided
        compression bars.  Returns {'As': value | None, 'limit': As_max}."""
        rects, bars = self.oriented(sign)
        _, d, _ = self.tension_steel(sign)
        comp = [(A, y) for A, y, ten in bars if not ten]
        Mu = abs(Mu)
        As_hi = self.as_max(sign)

        def phiMn(As):
            return self._analyze(rects, comp + [(As, d)], d)["phiMn"] if As > 0 else 0.0

        if Mu <= 0:
            return dict(As=0.0, limit=As_hi)
        if As_hi <= 0 or phiMn(As_hi) < Mu:
            return dict(As=None, limit=As_hi)
        n = 40
        prev = 0.0
        for i in range(1, n + 1):
            As = As_hi * i / n
            if phiMn(As) >= Mu:
                lo, hi = prev, As
                for _ in range(40):
                    mid = 0.5 * (lo + hi)
                    if phiMn(mid) >= Mu:
                        hi = mid
                    else:
                        lo = mid
                return dict(As=hi, limit=As_hi)
            prev = As
        return dict(As=As_hi, limit=As_hi)

    # -- service (cracked) properties ----------------------------------
    def cracked(self, sign: int) -> dict:
        """Cracked transformed section: neutral axis kd and Icr (n = Es/Ec)."""
        n = self.inp.Es / self.Ec
        rects, bars = self.oriented(sign)
        tr = [(A * (n if ten else n - 1), y) for A, y, ten in bars]

        def first_moment(x):
            S = 0.0
            for y0, y1, w in rects:
                lo, hi = y0, min(y1, x)
                if hi > lo:
                    S += w * (hi - lo) * (x - (lo + hi) / 2)
            return S - sum(At * (y - x) for At, y in tr)

        lo, hi = 1e-6, self.inp.h
        for _ in range(80):
            x = 0.5 * (lo + hi)
            if first_moment(x) > 0:
                hi = x
            else:
                lo = x
        x = 0.5 * (lo + hi)
        Icr = sum(At * (y - x) ** 2 for At, y in tr)
        for y0, y1, w in rects:
            lo_, hi_ = y0, min(y1, x)
            if hi_ > lo_:
                Icr += w * (hi_ - lo_) ** 3 / 12 + w * (hi_ - lo_) * (x - (lo_ + hi_) / 2) ** 2
        return dict(kd=x, Icr=Icr, n=n)

    def cracking_moment(self, sign: int) -> float:
        """Mcr = fr Ig / yt, fr = 0.62 lambda sqrt(fc') (19.2.3.1)."""
        fr = 0.62 * self.inp.lam * math.sqrt(self.inp.fc)
        yt = self.inp.h - self.ybar if sign > 0 else self.ybar
        return fr * self.Ig / yt

    # -- detailing helpers ---------------------------------------------
    def clear_spacing(self, layer: Layer) -> float:
        inp = self.inp
        if layer.n < 2:
            return math.inf
        inner = inp.bw - 2 * (inp.cover + inp.stirrup_d)
        return (inner - layer.n * layer.d) / (layer.n - 1)

    def center_spacing(self, layer: Layer) -> float:
        inp = self.inp
        if layer.n < 2:
            return math.inf
        inner = inp.bw - 2 * (inp.cover + inp.stirrup_d)
        return (inner - layer.d) / (layer.n - 1)


# --------------------------------------------------------------------------
# Shear
# --------------------------------------------------------------------------
def shear_check(sec: BeamSection, Vu: float, s: float, sign: int = 1) -> dict:
    inp = sec.inp
    code = inp.code
    Vu = abs(Vu)
    bw = inp.bw
    As, d, _ = sec.tension_steel(sign)
    lam = inp.lam
    sfc = min(math.sqrt(inp.fc), 8.3)        # 22.5.3.1 / 11.1.2
    fyt = min(inp.fyt, 420.0)                # 20.2.2.4 / 11.5.2
    phi = phi_shear(code)
    Av = inp.legs * bar_area(inp.stirrup_d)
    Vs = Av * fyt * d / s if s > 0 else 0.0
    rho_w = As / (bw * d)

    if code == DPT:
        Vc = sfc / 6.0 * bw * d
        eq = "Vc = (1/6)√fc'·bw·d"
        av_min_coef = 1.0 / 3.0                  # Av,min = bw s / (3 fyt)
        av_min_ref = "Av,min = bw·s/(3fyt)"
        vs_lim = 2.0 / 3.0 * sfc * bw * d        # 11.5.6.9
        vs_tight = 1.0 / 3.0 * sfc * bw * d      # 11.5.4.3
        av_needed = Vu > 0.5 * phi * Vc         # 11.5.5.1
        av_needed_txt = "Vu > 0.5φVc"
    else:
        av_min_coef = max(0.062 * math.sqrt(inp.fc), 0.35)
        av_min_ref = "Av,min = max(0.062√fc', 0.35)·bw·s/fyt"
        Av_min_s = av_min_coef * bw * s / fyt
        lam_s = min(1.0, math.sqrt(2.0 / (1.0 + d / 254.0)))
        if Av >= Av_min_s:
            Vc_a = 0.17 * lam * sfc * bw * d
            Vc_b = 0.66 * lam * rho_w ** (1 / 3) * sfc * bw * d
            Vc = max(Vc_a, Vc_b)
            eq = ("Vc = 0.17λ√fc'·bw·d (22.5.5.1a)" if Vc_a >= Vc_b
                  else "Vc = 0.66λ(ρw)^⅓√fc'·bw·d (22.5.5.1b)")
        else:
            Vc = 0.66 * lam_s * lam * rho_w ** (1 / 3) * sfc * bw * d
            eq = f"Vc = 0.66λsλ(ρw)^⅓√fc'·bw·d (22.5.5.1c, λs = {lam_s:.3f})"
        Vc = min(Vc, 0.42 * lam * sfc * bw * d)   # 22.5.5.1.1
        vs_lim = 0.66 * sfc * bw * d              # 22.5.1.2
        vs_tight = 0.33 * sfc * bw * d            # 9.7.6.2.2
        if inp.h <= 250:                          # Table 9.6.3.1
            av_needed = Vu > phi * Vc
            av_needed_txt = "Vu > φVc (h ≤ 250 mm)"
        else:                                     # 9.6.3.1
            av_needed = Vu > phi * 0.083 * lam * sfc * bw * d
            av_needed_txt = "Vu > φ0.083λ√fc'·bw·d"

    Av_min = av_min_coef * bw * s / fyt
    Vs_req = max(Vu / phi - Vc, 0.0)
    tight = max(Vs, Vs_req) > vs_tight
    s_max = min(d / 4, 300.0) if tight else min(d / 2, 600.0)

    # recommended spacing for the chosen stirrup (rounded down to 25 mm)
    cands = [s_max]
    if Vs_req > 0:
        cands.append(Av * fyt * d / Vs_req)
    if av_needed or code == ACI:
        cands.append(Av * fyt / (av_min_coef * bw))
    s_rec = max(25.0, math.floor(min(cands) / 25.0) * 25.0)

    phiVn = phi * (Vc + min(Vs, vs_lim))
    section_ok = Vs_req <= vs_lim
    av_ok = (not av_needed) or Av >= Av_min - 1e-9
    s_ok = s <= s_max + 1e-9
    strength_ok = Vu <= phiVn + 1e-6
    return dict(
        Vu=Vu, d=d, bw=bw, phi=phi, Vc=Vc, phiVc=phi * Vc, Vs=Vs, Vs_req=Vs_req, Vs_lim=vs_lim,
        Vs_tight=vs_tight, phiVn=phiVn, Av=Av, Av_min=Av_min, av_needed=av_needed,
        av_needed_txt=av_needed_txt, av_min_ref=av_min_ref, s=s, s_max=s_max, s_rec=s_rec,
        rho_w=rho_w, eq=eq, fyt=fyt, tight=tight,
        section_ok=section_ok, av_ok=av_ok, s_ok=s_ok, strength_ok=strength_ok,
        ok=section_ok and av_ok and s_ok and strength_ok,
        dcr=Vu / phiVn if phiVn > 0 else math.inf,
    )


# --------------------------------------------------------------------------
# Development length (tension, straight bars)
# --------------------------------------------------------------------------
def development_length(inp: BeamInput, db: float, top: bool, clear_spacing: float,
                       clear_cover: float, stirrups_ok: bool = True) -> dict:
    """Simplified tension development length.

    ACI 318-19 Table 25.4.2.3 / ACI 318-99 12.2.2 (uncoated, normal-weight).
    """
    sfc = min(math.sqrt(inp.fc), 8.3)
    good = ((clear_spacing >= db and clear_cover >= db and stirrups_ok)
            or (clear_spacing >= 2 * db and clear_cover >= db))
    psi_t = 1.3 if top else 1.0
    if inp.code == DPT:
        small = db <= 20
        k = (12 / 25 if small else 3 / 5) if good else (18 / 25 if small else 9 / 10)
        psi_g = 1.0
        ld = k * inp.fy * psi_t / (inp.lam * sfc) * db
        ref = "ACI 318-99 12.2.2"
    else:
        small = db < 20          # No. 19 and smaller
        div = (2.1 if small else 1.7) if good else (1.4 if small else 1.1)
        psi_g = 1.0 if inp.fy <= 420 else (1.15 if inp.fy <= 550 else 1.3)
        ld = inp.fy * psi_t * psi_g / (div * inp.lam * sfc) * db
        ref = "ACI 318-19 Table 25.4.2.3"
    ld = max(ld, 300.0)
    return dict(ld=ld, db=db, psi_t=psi_t, psi_g=psi_g, good=good, ref=ref, ld_db=ld / db)


# --------------------------------------------------------------------------
# Span analysis helpers
# --------------------------------------------------------------------------
# support condition -> (M+ coef, M- coef, V coef at face, deflection coef K, h_min divisor)
# Moments: ACI approximate coefficients (6.5 / 8.3.3).  Deflection: Delta = K w L^4 / (Ec Ie),
# from Delta = 5L^2/(48EI) [Mmid - 0.1(M1 + M2)] with the same coefficients.
SUPPORTS = {
    "simple": dict(name="ช่วงเดียว (Simply supported)", cp=1 / 8, cn=0.0, cv=0.5,
                   K=5 / 384, hdiv=16.0),
    "end": dict(name="ปลายต่อเนื่องด้านเดียว (End span)", cp=1 / 14, cn=1 / 10, cv=1.15 / 2,
                K=5 / 48 * (1 / 14 - 0.1 * (1 / 16 + 1 / 10)), hdiv=18.5),
    "interior": dict(name="ต่อเนื่องสองด้าน (Interior span)", cp=1 / 16, cn=1 / 11, cv=0.5,
                     K=5 / 48 * (1 / 16 - 0.1 * (2 / 11)), hdiv=21.0),
    "cantilever": dict(name="คานยื่น (Cantilever)", cp=0.0, cn=1 / 2, cv=1.0,
                       K=1 / 8, hdiv=8.0),
}


def min_depth(inp: BeamInput, L: float, support: str) -> float:
    """Table 9.3.1.1 (ACI 318-19) / Table 9.5(a) (ACI 318-99), normal-weight concrete."""
    return L / SUPPORTS[support]["hdiv"] * (0.4 + inp.fy / 700.0)


def span_forces(inp: BeamInput, L: float, support: str, wu: float, d: float) -> dict:
    """Design forces from the approximate coefficients.  wu in N/mm, L in mm."""
    sp = SUPPORTS[support]
    Mpos = sp["cp"] * wu * L * L
    Mneg = sp["cn"] * wu * L * L
    V_face = sp["cv"] * wu * L
    Vu_d = max(V_face - wu * d, 0.0)
    Vu_mid = 0.0 if support == "cantilever" else max(V_face - wu * L / 4, 0.0)
    return dict(Mpos=Mpos, Mneg=Mneg, V_face=V_face, Vu_d=Vu_d, Vu_mid=Vu_mid)


def deflection(inp: BeamInput, sec: BeamSection, L: float, support: str,
               wD: float, wL: float, sustained_L: float = 0.0, xi: float = 2.0) -> dict:
    """Immediate and long-term deflection (w in N/mm, L in mm).

    Ie: ACI 318-19 Table 24.2.3.5 (Bischoff) / ACI 318-99 Eq. 9-7 (Branson).
    Long-term multiplier lambda_delta = xi / (1 + 50 rho')  (24.2.4.1 / 9.5.2.5).
    """
    sp = SUPPORTS[support]
    sign = -1 if support == "cantilever" else 1
    coefM = sp["cn"] if sign < 0 else sp["cp"]
    cr = sec.cracked(sign)
    Mcr = sec.cracking_moment(sign)
    Ig, Icr, Ec = sec.Ig, cr["Icr"], sec.Ec

    def Ie(Ma):
        if Ma <= 0:
            return Ig
        if inp.code == DPT:
            r = min(Mcr / Ma, 1.0) ** 3
            return min(r * Ig + (1 - r) * Icr, Ig)
        if Ma <= 2 / 3 * Mcr:
            return Ig
        return min(Icr / (1 - (2 / 3 * Mcr / Ma) ** 2 * (1 - Icr / Ig)), Ig)

    def delta(w):
        Ma = coefM * w * L * L
        I = Ie(Ma)
        return sp["K"] * w * L ** 4 / (Ec * I), Ma, I

    dD, MaD, IeD = delta(wD)
    dDL, MaDL, IeDL = delta(wD + wL)
    dL = dDL - dD
    _, d, _ = sec.tension_steel(sign)
    rho_c = sec.compression_steel(sign) / (inp.bw * d)
    lam_d = xi / (1 + 50 * rho_c)
    d_long = lam_d * (dD + sustained_L * dL)
    eff_L = 2 * L if support == "cantilever" else L   # limits use 2L for cantilevers
    return dict(Mcr=Mcr, Ig=Ig, Icr=Icr, kd=cr["kd"], n=cr["n"], Ec=Ec,
                MaD=MaD, MaDL=MaDL, IeD=IeD, IeDL=IeDL,
                dD=dD, dDL=dDL, dL=dL, lam_d=lam_d, rho_c=rho_c, d_long=d_long,
                d_after=d_long + dL, eff_L=eff_L, sign=sign)


# --------------------------------------------------------------------------
# Location design
# --------------------------------------------------------------------------
def detailing_checks(sec: BeamSection, sign: int, flex: dict, shear: dict,
                     span: float | None = None) -> list[dict]:
    inp, r = sec.inp, sec.reinf
    code19 = inp.code == ACI
    out = []

    def add(clause, item, req, prov, ok):
        out.append(dict(clause=clause, item=item, required=req, provided=prov, ok=bool(ok)))

    s_min_req = max(25.0, 4.0 / 3.0 * inp.agg)
    for nm, lay in (("ล่างชั้น 1", r.bot1), ("ล่างชั้น 2", r.bot2), ("บนชั้น 1", r.top1), ("บนชั้น 2", r.top2)):
        if lay.n >= 2:
            sc = sec.clear_spacing(lay)
            need = max(s_min_req, lay.d)
            add("25.2.1" if code19 else "7.6.1", f"ระยะช่องว่างเหล็ก {nm} ({lay.n}-DB{lay.d:.0f})",
                f"≥ {need:.0f} mm", f"{sc:.0f} mm", sc >= need - 1e-9)
    for nm, lay in (("ล่าง", r.bot1), ("บน", r.top1)):
        add("9.7.1" if code19 else "7.10", f"เหล็กมุมยึดปลอก ผิว{nm} (ชั้น 1)", "≥ 2 เส้น",
            f"{lay.n} เส้น", lay.n >= 2)

    # crack control (tension face, first layer)
    tl = r.bot1 if sign > 0 else r.top1
    if tl.n >= 1:
        cc = inp.cover + inp.stirrup_d
        if code19:
            fs = 2 / 3 * inp.fy
            smax = min(380 * 280 / fs - 2.5 * cc, 300 * 280 / fs)
            clause = "24.3.2"
        else:
            fs = 0.6 * inp.fy
            smax = min(95000 / fs - 2.5 * cc, 300 * 252 / fs)
            clause = "10.6.4"
        sc = sec.center_spacing(tl)
        add(clause, "ระยะเรียงเหล็กรับแรงดึง (ควบคุมรอยร้าว)", f"≤ {smax:.0f} mm",
            "-" if not math.isfinite(sc) else f"{sc:.0f} mm", (not math.isfinite(sc)) or sc <= smax)
    if inp.h > 900:
        add("9.7.2.3" if code19 else "10.6.7", "เหล็กเสริมผิวข้าง (Skin reinforcement)",
            "ต้องจัดให้มี (h > 900 mm)", "ตรวจสอบเอง", False)

    # stirrups
    if code19 and inp.legs >= 2:
        sw = (inp.bw - 2 * inp.cover - inp.stirrup_d) / (inp.legs - 1)
        lim = min(shear["d"] / 2, 300.0) if shear["tight"] else min(shear["d"], 600.0)
        add("9.7.6.2.2", "ระยะขาปลอกตามแนวกว้าง", f"≤ {lim:.0f} mm", f"{sw:.0f} mm", sw <= lim + 1e-9)

    # T-beam effective flange width
    if inp.flange:
        ov = (inp.bf - inp.bw) / 2
        lim = 8 * inp.hf
        txt = f"8hf = {lim:.0f}"
        if span:
            if code19:
                lim = min(lim, span / 8)
                txt += f", ln/8 = {span / 8:.0f}"
            else:
                lim = min(lim, (span / 4 - inp.bw) / 2)
                txt += f", (L/4 − bw)/2 = {(span / 4 - inp.bw) / 2:.0f}"
        add("6.3.2.1" if code19 else "8.10.2", "ปีกยื่นแต่ละข้างของคานตัว T",
            f"≤ {lim:.0f} mm ({txt})", f"{ov:.0f} mm", ov <= lim + 1e-9)
    return out


@dataclass
class LocationResult:
    loc: Location
    sec: BeamSection
    sign: int
    flex: dict | None          # None when there is no moment at this location
    req: dict | None
    shear: dict
    checks: list[dict]
    detail: list[dict]

    @property
    def ok(self) -> bool:
        return all(c["ok"] for c in self.checks) and all(d["ok"] for d in self.detail)

    @property
    def dcr(self) -> float:
        vals = [self.shear["dcr"]]
        if self.flex is not None and self.loc.Mu != 0:
            vals.append(abs(self.loc.Mu) / self.flex["phiMn"] if self.flex["phiMn"] > 0 else math.inf)
        return max(vals)


def design_location(inp: BeamInput, loc: Location, span: float | None = None) -> LocationResult:
    sec = BeamSection(inp, loc.reinf)
    sign = -1 if loc.Mu < 0 else 1
    code19 = inp.code == ACI
    checks = []

    def add(clause, item, req, prov, ok):
        checks.append(dict(clause=clause, item=item, required=req, provided=prov, ok=bool(ok)))

    flex = req = None
    if loc.Mu != 0:
        flex = sec.flexure(sign)
        req = sec.required_as(loc.Mu, sign)
        Mu = abs(loc.Mu)
        add("9.5.1.1" if code19 else "9.1.1", "กำลังรับโมเมนต์ φMn ≥ Mu",
            f"≥ {Mu / 1e6:,.1f} kN·m", f"{flex['phiMn'] / 1e6:,.1f} kN·m", flex["phiMn"] >= Mu - 1e-6)
        As_req = req["As"] if req["As"] is not None else math.inf
        need_min = min(flex["As_min"], 4 / 3 * As_req)
        add("9.6.1.2–3" if code19 else "10.5.1–3", "เหล็กรับแรงดึงขั้นต่ำ As,min",
            f"≥ {need_min:,.0f} mm²", f"{flex['As']:,.0f} mm²", flex["As"] >= need_min - 1e-6)
        if code19:
            add("9.3.3.1", "ความเหนียว: εt ≥ 0.004", "≥ 0.0040", f"{flex['eps_t']:.4f}",
                flex["eps_t"] >= 0.004 - 1e-9)
        else:
            add("10.3.3", "เหล็กรับแรงดึงสูงสุด (0.75ρb + ρ'fs'/fy)",
                f"≤ {flex['As_max']:,.0f} mm²", f"{flex['As']:,.0f} mm²",
                flex["As"] <= flex["As_max"] + 1e-6)

    shear = shear_check(sec, loc.Vu, loc.reinf.s, sign)
    sclause = "22.5" if code19 else "11.1"
    add(sclause, "กำลังรับแรงเฉือน φVn ≥ Vu", f"≥ {shear['Vu'] / 1e3:,.1f} kN",
        f"{shear['phiVn'] / 1e3:,.1f} kN", shear["strength_ok"])
    add("22.5.1.2" if code19 else "11.5.6.9", "ขนาดหน้าตัดพอรับแรงเฉือน (Vs ≤ Vs,max)",
        f"≤ {shear['Vs_lim'] / 1e3:,.1f} kN", f"{shear['Vs_req'] / 1e3:,.1f} kN", shear["section_ok"])
    add("9.6.3" if code19 else "11.5.5", f"เหล็กปลอกขั้นต่ำ ({shear['av_min_ref']})",
        f"≥ {shear['Av_min']:,.0f} mm²" if shear["av_needed"] else "ไม่บังคับ",
        f"{shear['Av']:,.0f} mm²", shear["av_ok"])
    add("9.7.6.2.2" if code19 else "11.5.4", "ระยะเรียงเหล็กปลอกสูงสุด",
        f"≤ {shear['s_max']:.0f} mm", f"{loc.reinf.s:.0f} mm", shear["s_ok"])

    detail = detailing_checks(sec, sign, flex, shear, span)
    return LocationResult(loc, sec, sign, flex, req, shear, checks, detail)


def suggest_reinforcement(inp: BeamInput, loc: Location, bar_d: float, comp_d: float,
                          span: float | None = None) -> Reinforcement | None:
    """Pick the number of bars (one or two layers) and stirrup spacing for a location."""
    sign = -1 if loc.Mu < 0 else 1
    base = loc.reinf
    smin = max(25.0, bar_d, 4 / 3 * inp.agg)
    inner = inp.bw - 2 * (inp.cover + inp.stirrup_d)
    per_layer = max(2, int((inner + smin) // (bar_d + smin)))
    comp = Layer(max(2, (base.top1.n if sign > 0 else base.bot1.n)), comp_d)

    for n in range(2, 4 * per_layer + 1):
        n1 = min(n, per_layer)
        n2 = n - n1
        if n2 > per_layer:
            break
        ten1, ten2 = Layer(n1, bar_d), Layer(n2, bar_d)
        if sign > 0:
            r = replace(base, bot1=ten1, bot2=ten2, top1=comp, top2=Layer(0, comp_d))
        else:
            r = replace(base, top1=ten1, top2=ten2, bot1=comp, bot2=Layer(0, comp_d))
        res = design_location(inp, replace(loc, reinf=r), span)
        if res.flex is None or all(c["ok"] for c in res.checks[:3]):
            sh = shear_check(res.sec, loc.Vu, base.s, sign)
            r = replace(r, s=sh["s_rec"])
            return r
    return None
