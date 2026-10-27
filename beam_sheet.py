"""Beam design sheet (Singly & Doubly) — port of the "Beam-Singly" and "Beam-Doubly"
calculation forms, one section per sheet, units as in the forms: kg, kg-m, cm, ksc.

Singly ("Beam-Singly"):
  1.) Assume  rho_b, 0.5rho_b, rho_max = 0.75rho_b, rho_min, Ru, suggested d
  2.) Use     Rn = Mu/(phi b d^2), rho required, As = rho b d
  3.) Design  bars used
  4.) Check   rho <= rho_max, phi Mn = phi As fy (d - a/2), phi from eps_t 0.70..0.90
Doubly ("Beam-Doubly"):
  rho1 = 0.5 rho_b, Mu1 = phi Ru b d^2, Mu2 = Mu - Mu1,
  fs' from the bars used (c from equilibrium), As' = Mu2/(phi fs'(d - d')),
  As = rho1 b d + As' fs'/fy; check rho - rho' fs'/fy <= 0.75 rho_b and
  phi Mn = phi[(As - As'fs'/fy) fy (d - a/2) + As' fs'(d - d')], phi = 0.9
Mode: "auto" (singly when rho required <= rho_max), "singly" or "doubly".

Bars are a free list of rows (side, layer, count, diameter).  Layer k of a side
sits at cover + stirrup + sum(previous layers: largest bar + gap) + largest bar/2
from that face; d and d' are the area-weighted centroids.  Extra checks asked by
the user: tension steel ratio As/(b h) <= rho_limit (2 %), and the clear distance
between main bars of each layer
    (B - 2 cover - stirrup x legs - sum(n x db)) / (n - 1) >= clear_min.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

BAR_SIZES = [12, 16, 20, 25, 28, 32]
STIRRUP_SIZES = [6, 9, 12]
MODES = {"auto": "อัตโนมัติ", "singly": "Singly", "doubly": "Doubly"}


def bar_area(d_mm: float) -> float:
    return math.pi * (d_mm / 10) ** 2 / 4          # cm^2


def bar_name(d_mm: float) -> str:
    return ("DB" if d_mm > 9 else "RB") + f"{d_mm:g}"


def bars_text(layers: list[dict]) -> str:
    """Total bars of a side, e.g. "4-DB20 + 2-DB16" (from layer_table rows)."""
    cnt: dict = {}
    for l in layers:
        for part in l["txt"].split(" + "):
            n, name = part.split("-", 1)
            cnt[name] = cnt.get(name, 0) + int(n)
    return " + ".join(f"{n}-{name}" for name, n in cnt.items()) or "-"


@dataclass
class Bar:
    side: str = "t"          # "t" tension / "c" compression
    layer: int = 1           # 1 = closest to the face
    n: int = 2
    db: float = 16.0         # mm


@dataclass
class SheetInput:
    fc: float = 280.0               # ksc
    fy: float = 4000.0              # main bars (DB), ksc
    fy_rb: float = 2400.0           # round bars (RB), ksc
    Es: float = 2.04e6              # ksc
    phi_b: float = 0.9
    phi_v: float = 0.85
    Mu: float = 0.0                 # kg-m
    Vu: float = 0.0                 # kg, zone 2H from support
    Vu_mid: float = 0.0             # kg, midspan zone
    span: float = 4.0               # m
    B: float = 20.0                 # cm
    H: float = 50.0                 # cm
    cover: float = 4.0              # cm, to stirrup
    gap: float = 3.0                # cm, clear distance between layers
    db: float = 16.0                # mm, default main bar for suggestions
    bars: list = field(default_factory=lambda: [Bar("t", 1, 2, 16.0), Bar("c", 1, 2, 16.0)])
    ds: float = 9.0                 # mm, stirrup
    legs: int = 2
    eq: bool = True                 # seismic spacing in the 2H zone
    mode: str = "auto"              # auto / singly / doubly
    rho_limit: float = 0.02         # As(tension)/(b h)
    clear_min: float = 6.0          # cm, clear distance between main bars

    @property
    def fy_st(self) -> float:
        return self.fy if self.ds > 9 else self.fy_rb

    def side(self, s: str) -> list[Bar]:
        return [b for b in self.bars if b.side == s and b.n > 0]

    def fy_main(self) -> float:
        t = self.side("t")
        return self.fy if (max((b.db for b in t), default=self.db) > 9) else self.fy_rb


def beta1(fc: float) -> float:
    if fc <= 280:
        return 0.85
    if fc <= 560:
        return 0.85 - 0.05 * (fc - 280) / 70
    return 0.65


def phi_eps(eps_t: float, fy: float, Es: float) -> float:
    """Form V39: 0.70 (compression controlled) .. 0.90 (tension controlled)."""
    ety = fy / Es
    if eps_t <= ety:
        return 0.7
    if eps_t < ety + 0.003:
        return 0.7 + 0.25 * (eps_t - ety) / 0.003
    return 0.9


def _count(bars) -> dict:
    cnt: dict = {}
    for b in sorted(bars, key=lambda b: -b.db):
        cnt[b.db] = cnt.get(b.db, 0) + b.n
    return cnt


def layer_table(inp: SheetInput, side: str) -> list[dict]:
    """Layers of one side: n, As, largest bar, depth of the centre from that face, clear distance."""
    bars = inp.side(side)
    out = []
    y0 = inp.cover + inp.ds / 10
    for k in sorted({b.layer for b in bars}):
        lb = [b for b in bars if b.layer == k]
        dmax = max(b.db for b in lb)
        n = sum(b.n for b in lb)
        As = sum(b.n * bar_area(b.db) for b in lb)
        width = sum(b.n * b.db / 10 for b in lb)
        clear = (inp.B - 2 * inp.cover - inp.ds / 10 * inp.legs - width) / (n - 1) if n > 1 else math.inf
        out.append(dict(layer=k, n=n, As=As, dmax=dmax, y=y0 + dmax / 20, clear=clear,
                        txt=" + ".join(f"{n}-{bar_name(d)}" for d, n in _count(lb).items())))
        y0 += dmax / 10 + inp.gap
    return out


def depth(inp: SheetInput, side: str) -> float:
    """Centroid of a side's bars from its own face (d' for compression)."""
    lt = layer_table(inp, side)
    if not lt:
        return inp.cover + inp.ds / 10 + inp.db / 20
    return sum(l["As"] * l["y"] for l in lt) / sum(l["As"] for l in lt)


def compute(inp: SheetInput) -> dict:
    fc, Es, b = inp.fc, inp.Es, inp.B
    fy = inp.fy_main()
    b1 = beta1(fc)
    lt_t, lt_c = layer_table(inp, "t"), layer_table(inp, "c")
    d = inp.H - depth(inp, "t")
    dp = depth(inp, "c")
    As = sum(l["As"] for l in lt_t)
    Asc = sum(l["As"] for l in lt_c)
    r = dict(inp=inp, beta1=b1, d=d, dp=dp, fy=fy, layers_t=lt_t, layers_c=lt_c, As=As, Asc=Asc,
             rho=As / (b * d), rho_c=Asc / (b * d), pct=As / (b * inp.H))

    # 1.) Assume
    rho_b = 0.85 * b1 * fc / fy * 0.003 / (0.003 + fy / Es)
    rho_half, rho_max = 0.5 * rho_b, 0.75 * rho_b
    Ru = rho_half * fy * (1 - 0.59 * rho_half * fy / fc)
    d_sugg = math.sqrt(inp.Mu * 100 / (inp.phi_b * Ru * b)) if inp.Mu > 0 else 0.0
    r.update(rho_b=rho_b, rho_half=rho_half, rho_max=rho_max, Ru=Ru, d_sugg=d_sugg,
             As_sugg=rho_half * b * d_sugg)

    # 2.) Use
    Rn = inp.Mu * 100 / (inp.phi_b * b * d ** 2)
    disc = 1 - 2 * Rn / (0.85 * fc)
    rho_req = 0.85 * fc / fy * (1 - math.sqrt(disc)) if disc >= 0 else math.inf
    rho_min = min(max(14 / fy, 0.8 * math.sqrt(fc) / fy), 1.33 * rho_req)
    auto_kind = "Singly" if rho_req <= rho_max else "Doubly"
    kind = {"singly": "Singly", "doubly": "Doubly"}.get(inp.mode, auto_kind)
    r.update(Rn=Rn, rho_req=rho_req, rho_min=rho_min, kind=kind, auto_kind=auto_kind,
             chosen=inp.mode != "auto" and kind != auto_kind)

    if kind == "Singly":
        rho_use = max(rho_req, rho_min)
        As_req, Asc_req = rho_use * b * d, rho_min * b * d          # form K30: hanger bars >= rho_min bd
        a = As * fy / (0.85 * fc * b)
        c = a / b1
        Mn = As * fy * (d - a / 2) / 100
        eps_t = 0.003 * (d - c) / c if c > 0 else math.inf
        phi = phi_eps(eps_t, fy, Es)
        duct_val, duct = r["rho"], r["rho"] < rho_max
        r.update(rho_use=rho_use, fs_c=None, c=c, eps_t=eps_t)
    else:
        rho1 = rho_half
        Ru1 = rho1 * fy * (1 - 0.59 * rho1 * fy / fc)
        Mu1 = inp.phi_b * Ru1 * b * d * d / 100
        Mu2 = inp.Mu - Mu1
        E = 0.003 * Es                                      # 6120 ksc
        P = (E * Asc - As * fy) / (1.7 * fc * b * b1)       # form M13..M16
        Q = E * dp * Asc / (0.85 * fc * b * b1)
        c = -P + math.sqrt(P * P + Q) if P * P + Q >= 0 else 0.0
        fs_c = min(fy, (c - dp) / c * E) if c > 0 else 0.0
        rho_cy = 0.85 * b1 * fc / fy * dp / d * E / (E - fy)
        if fs_c > 0:
            Asc_req = max(Mu2, 0.0) * 100 / (inp.phi_b * fs_c * (d - dp))
            As_req = rho1 * b * d + Asc_req * fs_c / fy
        else:
            Asc_req = As_req = math.inf
        As_eff = As - Asc * max(fs_c, 0) / fy
        a = As_eff * fy / (0.85 * b * fc)
        Mn = (As_eff * fy * (d - a / 2) + Asc * max(fs_c, 0) * (d - dp)) / 100
        phi = inp.phi_b
        eps_t = 0.003 * (d - c) / c if c > 0 else math.inf
        duct_val = As_eff / (b * d)
        duct = duct_val <= rho_max
        r.update(rho1=rho1, Ru1=Ru1, Mu1=Mu1, Mu2=Mu2, P=P, Q=Q, c=c, fs_c=fs_c, rho_cy=rho_cy,
                 eps_t=eps_t, rho_use=rho1)
    phiMn = phi * Mn
    clear_ok = all(l["clear"] >= inp.clear_min - 1e-9 for l in lt_t + lt_c)
    r.update(As_req=As_req, Asc_req=Asc_req, As_ok=As >= As_req - 1e-9, Asc_ok=Asc >= Asc_req - 1e-9,
             a=a, ety=fy / Es, phi=phi, Mn=Mn, phiMn=phiMn, duct_val=duct_val, duct_ok=duct,
             Mn_ok=phiMn >= inp.Mu - 1e-6, pct_ok=r["pct"] <= inp.rho_limit + 1e-12, clear_ok=clear_ok)

    # Shear reinforcement
    Av = inp.legs * bar_area(inp.ds)
    r.update(Av=Av, fy_st=inp.fy_st)
    db_t = max((l["dmax"] for l in lt_t), default=inp.db)
    r["sh_2h"] = shear_zone(inp, d, Av, inp.Vu, eq=inp.eq,
                            eq_limit=min(d / 4, 8 * db_t / 10, 24 * inp.ds / 10, 30))
    r["sh_mid"] = shear_zone(inp, d, Av, inp.Vu_mid, eq=inp.eq, eq_limit=d / 2)
    r["flex_ok"] = (r["As_ok"] and r["Asc_ok"] and r["duct_ok"] and r["Mn_ok"]
                    and math.isfinite(r["Asc_req"]) and math.isfinite(r["As_req"]))
    r["ok"] = (r["flex_ok"] and r["pct_ok"] and r["clear_ok"] and r["sh_2h"]["ok"] and r["sh_mid"]["ok"])
    return r


def shear_zone(inp: SheetInput, d: float, Av: float, Vu: float, eq: bool, eq_limit: float) -> dict:
    b, fc, phi = inp.B, inp.fc, inp.phi_v
    sfc = math.sqrt(fc)
    phiVc = phi * 0.53 * sfc * b * d
    phiVs = Vu - phiVc                               # "Shear Resistance" (form Q37)
    lim11 = 1.1 * phi * b * d * sfc
    lim21 = 2.1 * phi * b * d * sfc
    fy = inp.fy_st
    s1 = min(0.5 * d, 60)
    s2 = min(Av * fy / (3.5 * b), 0.5 * d, 60)
    s3 = min(phi * Av * fy * d / phiVs, 0.5 * d, 60) if phiVs > 0 else math.inf
    s4 = min(0.25 * d, 30)
    if Vu <= phiVc / 2:
        case, cands = 1, [s1]
    elif Vu < phiVc:
        case, cands = 2, [s2]
    elif phiVs <= lim11:
        case, cands = 3, [s1, s2, s3]
    elif phiVs <= lim21:
        case, cands = 4, [s1, s2, s3, s4]
    else:
        case, cands = 5, []                         # "Revised": enlarge the section
    if eq and cands:
        cands.append(eq_limit)
    s_ctrl = min(cands) if cands else None
    s_use = math.floor(s_ctrl / 2.5 + 1e-9) * 2.5 if s_ctrl else None
    return dict(Vu=Vu, phiVc=phiVc, half=phiVc / 2, phiVs=phiVs, lim11=lim11, lim21=lim21,
                s1=s1, s2=s2, s3=s3, s4=s4, eq_limit=eq_limit, eq=eq, case=case, s_ctrl=s_ctrl,
                s=s_use, ok=case <= 4 and bool(s_use) and s_use >= 2.5)


# ---------------------------------------------------------------------------
# Suggestion
# ---------------------------------------------------------------------------
def per_layer(inp: SheetInput, db: float) -> int:
    """Most bars of one size in a layer with clear distance >= clear_min (at least 2)."""
    free = inp.B - 2 * inp.cover - inp.ds / 10 * inp.legs
    n = 2
    while (free - (n + 1) * db / 10) / n >= inp.clear_min - 1e-9 and n < 20:
        n += 1
    return n


MAX_LT, MAX_LC = 4, 3          # layers a suggestion may use (as in the forms)


def _layers(side: str, n_tot: int, cap: int, db: float) -> list[Bar]:
    rows, k = [], 1
    while n_tot > 0:
        m = min(cap, n_tot)
        rows.append(Bar(side, k, m, db))
        n_tot -= m
        k += 1
    if len(rows) > 1 and rows[-1].n == 1 and rows[-2].n >= 3:  # no single bar alone in a layer
        rows[-2].n -= 1
        rows[-1].n += 1
    return rows


def _suggest_bars(inp: SheetInput) -> SheetInput:
    db = inp.db
    cap = per_layer(inp, db)
    cur = replace(inp, bars=_layers("t", 2, cap, db) + _layers("c", 2, cap, db))
    r0 = compute(cur)
    if r0["kind"] == "Doubly":                       # start from the steel a singly section would need
        rho0 = r0["rho_req"] if math.isfinite(r0["rho_req"]) else r0["rho_max"]
        n0 = max(2, math.ceil(max(rho0, r0["rho_half"]) * cur.B * r0["d"] / bar_area(db)))
        cur = replace(cur, bars=_layers("t", n0, cap, db) + _layers("c", 2, cap, db))
    nt = lambda c: sum(b.n for b in c.side("t"))
    nc = lambda c: sum(b.n for b in c.side("c"))
    for _ in range(25):
        r = compute(cur)
        if not (math.isfinite(r["As_req"]) and math.isfinite(r["Asc_req"])):
            if nt(cur) >= MAX_LT * cap:
                break
            cur = replace(cur, bars=_layers("t", nt(cur) + 1, cap, db) + _layers("c", nc(cur), cap, db))
            continue
        n_t = max(2, math.ceil(r["As_req"] / bar_area(db) - 1e-9))
        n_c = max(2, math.ceil(r["Asc_req"] / bar_area(db) - 1e-9))
        if (n_t, n_c) == (nt(cur), nc(cur)):
            break
        cur = replace(cur, bars=_layers("t", min(n_t, MAX_LT * cap), cap, db) + _layers("c", min(n_c, MAX_LC * cap), cap, db))
    for _ in range(10):                              # rounding / extra layers: top up until it checks
        r = compute(cur)
        if r["As_ok"] and r["Asc_ok"] and r["Mn_ok"] and (r["kind"] == "Singly" or r["duct_ok"]):
            break
        t, c = nt(cur), nc(cur)
        if not (r["Mn_ok"] and r["As_ok"]):
            t += 1
        if not r["Asc_ok"] or (r["kind"] == "Doubly" and not r["duct_ok"]):
            c += 1
        cur = replace(cur, bars=_layers("t", t, cap, db) + _layers("c", c, cap, db))
    return cur


def _bars_for(inp: SheetInput) -> SheetInput:
    best = _suggest_bars(inp)
    r = compute(best)
    if inp.mode == "auto" and r["kind"] == "Singly" and not (r["flex_ok"] and r["duct_ok"]):
        dbl = _suggest_bars(replace(inp, mode="doubly"))
        if compute(dbl)["flex_ok"]:
            best = dbl
    return best


def _pick_size(inp: SheetInput) -> SheetInput:
    """Main bar size from the chosen one upwards: the first that passes flexure, the % steel limit
    and the clear distance within the allowed layers; else the first that passes flexure."""
    tried = [_bars_for(replace(inp, db=float(d))) for d in [inp.db] + [d for d in BAR_SIZES if d > inp.db]]
    rs = [compute(t) for t in tried]
    for want in (lambda r: r["flex_ok"] and r["pct_ok"] and r["clear_ok"], lambda r: r["flex_ok"]):
        for t, r in zip(tried, rs):
            if want(r):
                return t
    return tried[0]


def suggest(inp: SheetInput) -> SheetInput:
    """Bars and stirrups for the section.  In "auto" mode the section is designed as doubly when
    the bars a singly section needs cannot pass the singly check (mode is then set to "doubly").
    A larger main bar is used when the chosen one needs more than 4 tension / 3 compression layers.
    Stirrups: a larger size, then more legs, when the spacing would be below 7.5 cm."""
    best = _pick_size(inp)
    trial = best
    for ds, legs in [(best.ds, best.legs), (12.0, best.legs), (12.0, max(3, best.legs)), (12.0, max(4, best.legs))]:
        if ds < best.ds:
            continue
        trial = replace(best, ds=ds, legs=legs)
        if (ds, legs) != (best.ds, best.legs):
            trial = _bars_for(trial)                # d and the bars per layer change with the stirrup
        rt = compute(trial)
        if min(z["s"] or 0 for z in (rt["sh_2h"], rt["sh_mid"])) >= 7.5:
            return trial
    return trial
