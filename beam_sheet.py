"""Beam design sheet (Singly & Doubly) — port of the "Beam-Singly" and "Beam-Doubly"
calculation forms, one section per sheet, units as in the forms: kg, kg-m, cm, ksc.

Singly (rho required <= rho_max = 0.75 rho_b), "Beam-Singly":
  1.) Assume  rho_b, 0.5rho_b, rho_max, rho_min, Ru, suggested d
  2.) Use     Rn = Mu/(phi b d^2), rho required, As = rho b d
  3.) Design  tension bars (rows / layers), compression (hanger) bars >= rho_min b d
  4.) Check   rho <= rho_max, phi Mn = phi As fy (d - a/2), phi from eps_t 0.70..0.90
Doubly (rho required > rho_max), "Beam-Doubly":
  rho1 = 0.5 rho_b, Mu1 = phi Ru b d^2, Mu2 = Mu - Mu1,
  fs' from the bars used (c from equilibrium), As' = Mu2/(phi fs'(d - d')),
  As = rho1 b d + As' fs'/fy; check rho - rho' fs'/fy <= 0.75 rho_b and
  phi Mn = phi[(As - As'fs'/fy) fy (d - a/2) + As' fs'(d - d')], phi = 0.9
  Shear       zone 2H from the support face and midspan; 4 cases of Vu
              (<= phiVc/2, < phiVc, phiVs <= 1.1phi sqrt(fc') bd, <= 2.1...),
              optional seismic spacing in the 2H zone: min(d/4, 8db, 24ds, 30 cm)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

BAR_SIZES = [6, 9, 12, 16, 20, 25, 28, 32]


def bar_area(d_mm: float) -> float:
    return math.pi * (d_mm / 10) ** 2 / 4          # cm^2


def bar_name(d_mm: float) -> str:
    return ("DB" if d_mm > 9 else "RB") + f"{d_mm:g}"


@dataclass
class SheetInput:
    fc: float = 280.0               # ksc
    fy: float = 4000.0              # main bars (DB), ksc
    fy_rb: float = 2400.0           # round bars (RB), ksc
    Es: float = 2.04e6              # ksc
    phi_b: float = 0.9              # used for Rn and the suggested depth (form J8)
    phi_v: float = 0.85             # shear (form J9)
    Mu: float = 0.0                 # kg-m
    Vu: float = 0.0                 # kg, zone 2H from support
    Vu_mid: float = 0.0             # kg, midspan zone
    span: float = 4.0               # m
    B: float = 20.0                 # cm
    H: float = 50.0                 # cm
    cover: float = 4.0              # cm, to stirrup
    gap: float = 3.0                # cm, clear distance between layers
    db: float = 16.0                # mm, main bars
    n_t: list = field(default_factory=lambda: [2, 0, 0, 0])   # tension rows (layers)
    n_c: list = field(default_factory=lambda: [2, 0, 0])      # compression rows
    ds: float = 9.0                 # mm, stirrup
    legs: int = 2
    eq: bool = True                 # seismic spacing in the 2H zone
    force_doubly: bool = False      # design as doubly although rho required <= rho_max

    @property
    def fy_main(self) -> float:
        return self.fy if self.db > 9 else self.fy_rb

    @property
    def fy_st(self) -> float:
        return self.fy if self.ds > 9 else self.fy_rb


def beta1(fc: float) -> float:
    if fc <= 280:
        return 0.85
    if fc <= 560:
        return 0.85 - 0.05 * (fc - 280) / 70
    return 0.65


def eff_depth(inp: SheetInput, layers: int | None = None) -> float:
    """d from the number of tension layers (form T21)."""
    if layers is None:
        layers = max(1, sum(1 for n in inp.n_t if n > 0))
    base = inp.H - inp.cover - inp.ds / 10
    if layers >= 4:
        return base - 2 * inp.db / 10 - inp.gap - inp.gap / 2
    if layers == 3:
        return base - inp.db / 10 - inp.gap - inp.db / 20
    if layers == 2:
        return base - inp.db / 10 - inp.gap / 2
    return base - inp.db / 20


def phi_eps(eps_t: float, fy: float, Es: float) -> float:
    """Form V39: 0.70 (compression controlled) .. 0.90 (tension controlled)."""
    ety = fy / Es
    if eps_t <= ety:
        return 0.7
    if eps_t < ety + 0.003:
        return 0.7 + 0.25 * (eps_t - ety) / 0.003
    return 0.9


def per_layer(inp: SheetInput) -> int:
    s = max(2.5, inp.db / 10)
    return max(1, int((inp.B - 2 * inp.cover - 2 * inp.ds / 10 + s) // (inp.db / 10 + s)))


def compute(inp: SheetInput) -> dict:
    fc, fy, Es, b = inp.fc, inp.fy_main, inp.Es, inp.B
    b1 = beta1(fc)
    d = eff_depth(inp)
    dp = inp.cover + inp.ds / 10 + inp.db / 20
    r = dict(inp=inp, beta1=b1, d=d, dp=dp, fy=fy)

    # 1.) Assume
    rho_b = 0.85 * b1 * fc / fy * 0.003 / (0.003 + fy / Es)
    rho_half, rho_max = 0.5 * rho_b, 0.75 * rho_b
    Ru = rho_half * fy * (1 - 0.59 * rho_half * fy / fc)
    d_sugg = math.sqrt(max(inp.Mu, 0) * 100 / (inp.phi_b * Ru * b)) if inp.Mu > 0 else 0.0
    r.update(rho_b=rho_b, rho_half=rho_half, rho_max=rho_max, Ru=Ru, d_sugg=d_sugg,
             As_sugg=rho_half * b * d_sugg)

    # 2.) Use
    Rn = inp.Mu * 100 / (inp.phi_b * b * d ** 2)
    disc = 1 - 2 * Rn / (0.85 * fc)
    rho_req = 0.85 * fc / fy * (1 - math.sqrt(disc)) if disc >= 0 else math.inf
    rho_min = min(max(14 / fy, 0.8 * math.sqrt(fc) / fy), 1.33 * rho_req)
    kind = "Singly" if rho_req <= rho_max and not inp.force_doubly else "Doubly"
    r.update(Rn=Rn, rho_req=rho_req, rho_min=rho_min, kind=kind,
             forced=inp.force_doubly and rho_req <= rho_max)

    # 3.) Design — bars used
    Ab = bar_area(inp.db)
    As_rows = [n * Ab for n in inp.n_t]
    Asc_rows = [n * Ab for n in inp.n_c]
    As, Asc = sum(As_rows), sum(Asc_rows)
    r.update(Ab=Ab, As_rows=As_rows, Asc_rows=Asc_rows, As=As, Asc=Asc, per_layer=per_layer(inp),
             fit_ok=all(n <= per_layer(inp) for n in inp.n_t), rho=As / (b * d), rho_c=Asc / (b * d))

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
        # c from equilibrium with the bars used (form M13..M16)
        P = (E * Asc - As * fy) / (1.7 * fc * b * b1)
        Q = E * dp * Asc / (0.85 * fc * b * b1)
        c = -P + math.sqrt(P * P + Q) if P * P + Q >= 0 else 0.0
        fs_c = min(fy, (c - dp) / c * E) if c > 0 else 0.0
        rho_cy = 0.85 * b1 * fc / fy * dp / d * E / (E - fy)
        if fs_c > 0:
            Asc_req = Mu2 * 100 / (inp.phi_b * fs_c * (d - dp))
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
    r.update(As_req=As_req, Asc_req=Asc_req, As_ok=As >= As_req - 1e-9, Asc_ok=Asc >= Asc_req - 1e-9,
             a=a, ety=fy / Es, phi=phi, Mn=Mn, phiMn=phiMn, duct_val=duct_val, duct_ok=duct,
             Mn_ok=phiMn >= inp.Mu - 1e-6)

    # Shear reinforcement
    Av = inp.legs * bar_area(inp.ds)
    r.update(Av=Av, fy_st=inp.fy_st)
    r["sh_2h"] = shear_zone(inp, d, Av, inp.Vu, eq=inp.eq, eq_limit=min(d / 4, 8 * inp.db / 10,
                                                                          24 * inp.ds / 10, 30))
    r["sh_mid"] = shear_zone(inp, d, Av, inp.Vu_mid, eq=inp.eq, eq_limit=d / 2)
    r["ok"] = (r["As_ok"] and r["Asc_ok"] and r["duct_ok"] and r["Mn_ok"] and r["fit_ok"]
               and r["sh_2h"]["ok"] and r["sh_mid"]["ok"] and math.isfinite(r["Asc_req"]))
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


def _rows(n_tot: int, cap: int, max_rows: int) -> list[int] | None:
    rows = []
    while n_tot > 0 and len(rows) < max_rows:
        k = min(cap, n_tot)
        rows.append(k)
        n_tot -= k
    if n_tot > 0:
        return None
    if len(rows) > 1 and rows[-1] == 1 and rows[-2] >= 3:    # no single bar alone in a layer
        rows[-2] -= 1
        rows[-1] += 1
    return rows + [0] * (max_rows - len(rows))


def suggest(inp: SheetInput) -> SheetInput:
    """Bars for the section: singly first; when the bars needed cannot pass the singly check
    (rho > rho_max or phi Mn < Mu after rounding up / extra layers) design it as doubly.
    The stirrup size is increased when the spacing would be below 7.5 cm."""
    best = _suggest_bars(SheetInput(**{**inp.__dict__, "force_doubly": False}))
    r = compute(best)
    if not (r["As_ok"] and r["duct_ok"] and r["Mn_ok"]):
        dbl = _suggest_bars(SheetInput(**{**inp.__dict__, "force_doubly": True}))
        rd = compute(dbl)
        if rd["As_ok"] and rd["Asc_ok"] and rd["duct_ok"] and rd["Mn_ok"]:
            best, r = dbl, rd
    for ds in sorted({best.ds, 12.0}):
        if ds < best.ds:
            continue
        trial = SheetInput(**{**best.__dict__, "ds": ds})
        rt = compute(trial)
        s_min = min(x["s"] or 0 for x in (rt["sh_2h"], rt["sh_mid"]))
        if s_min >= 7.5 or ds == 12.0:
            if ds != best.ds:
                trial = _suggest_bars(trial)           # d changes with the stirrup size
            best = trial
            break
    return best


def _suggest_bars(inp: SheetInput) -> SheetInput:
    """Tension rows (up to 4 layers) and compression rows; iterate because d and fs'
    depend on the bars chosen."""
    cap = per_layer(inp)
    cur = SheetInput(**{**inp.__dict__, "n_t": [2, 0, 0, 0], "n_c": [2, 0, 0]})
    r0 = compute(cur)
    if r0["kind"] == "Doubly":                       # start from the steel a singly section would need
        As0 = max(r0["rho_req"] if math.isfinite(r0["rho_req"]) else r0["rho_max"], r0["rho_half"]) * cur.B * r0["d"]
        cur.n_t = _rows(max(2, math.ceil(As0 / r0["Ab"])), cap, 4) or [cap] * 4
    for _ in range(20):
        r = compute(cur)
        if not (math.isfinite(r["As_req"]) and math.isfinite(r["Asc_req"])):
            # f's <= 0: the neutral axis is above the compression bars -> more tension steel
            more = _rows(sum(cur.n_t) + 1, cap, 4)
            if more is None:
                break
            cur.n_t = more
            continue
        n_t = max(2, math.ceil(r["As_req"] / r["Ab"] - 1e-9))
        n_c = max(2, math.ceil(r["Asc_req"] / r["Ab"] - 1e-9))
        rt, rc = _rows(n_t, cap, 4), _rows(n_c, cap, 3)
        if rt is None or rc is None:
            break
        if rt == cur.n_t and rc == cur.n_c:
            break
        cur.n_t, cur.n_c = rt, rc
    r = compute(cur)
    for _ in range(8):                               # rounding / extra layers: top up until it checks
        if r["As_ok"] and r["Asc_ok"] and r["Mn_ok"]:
            break
        if not r["Mn_ok"] or not r["As_ok"]:
            more = _rows(sum(cur.n_t) + 1, cap, 4)
            if more is None:
                break
            cur.n_t = more
        if not r["Asc_ok"] or (r["kind"] == "Doubly" and not r["duct_ok"]):
            more = _rows(sum(cur.n_c) + 1, cap, 3)
            if more is None:
                break
            cur.n_c = more
        r = compute(cur)
    return cur
