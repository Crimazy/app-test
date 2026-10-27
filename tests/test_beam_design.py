import math

import pytest

from beam_design import (
    ACI, DPT, BeamInput, BeamSection, Layer, Location, Reinforcement, deflection,
    design_location, development_length, factored_load, min_depth, phi_flexure, shear_check,
    span_forces, suggest_reinforcement,
)

SINGLY = Reinforcement(top1=Layer(0, 16), bot1=Layer(4, 20))


def test_load_combinations():
    assert factored_load(DPT, 10, 5) == ("1.4D + 1.7L", pytest.approx(22.5))
    assert factored_load(ACI, 10, 5)[1] == pytest.approx(20.0)
    assert factored_load(ACI, 10, 0)[1] == pytest.approx(14.0)


def test_phi_flexure():
    assert phi_flexure(DPT, 0.001, 400) == 0.90
    assert phi_flexure(ACI, 0.0051, 420) == pytest.approx(0.90)
    assert phi_flexure(ACI, 0.004, 420) == pytest.approx(0.65 + 0.25 * (0.004 - 0.0021) / 0.003)
    assert phi_flexure(ACI, 0.001, 420) == pytest.approx(0.65)


def test_singly_rectangular_hand_calc():
    inp = BeamInput(code=ACI, bw=300, h=600, cover=40, stirrup_d=10, fc=28, fy=420)
    f = BeamSection(inp, SINGLY).flexure(1)
    As = 4 * math.pi * 100
    d = 600 - 40 - 10 - 10
    a = As * 420 / (0.85 * 28 * 300)
    assert f["d"] == pytest.approx(d)
    assert f["a"] == pytest.approx(a, rel=1e-6)
    assert f["Mn"] == pytest.approx(As * 420 * (d - a / 2), rel=1e-6)
    assert f["phi"] == pytest.approx(0.90)


def test_tbeam_flange_and_web_compression():
    """a > hf: Cf = 0.85fc'(bf-bw)hf, Cw = 0.85fc' bw a."""
    inp = BeamInput(code=DPT, bw=300, h=500, tbeam=True, bf=600, hf=80, cover=40, stirrup_d=10,
                    fc=24, fy=400)
    r = Reinforcement(top1=Layer(0, 16), bot1=Layer(4, 25), bot2=Layer(2, 25))
    sec = BeamSection(inp, r)
    f = sec.flexure(1)
    As = 6 * math.pi * 25 ** 2 / 4
    Cf = 0.85 * 24 * (600 - 300) * 80
    a = (As * 400 - Cf) / (0.85 * 24 * 300)
    assert a > 80
    assert f["a"] == pytest.approx(a, rel=1e-6)
    d = f["d"]
    Mn = Cf * (d - 40) + 0.85 * 24 * 300 * a * (d - a / 2)
    assert f["Mn"] == pytest.approx(Mn, rel=1e-6)
    # hogging: flange in tension, compression on the web only (no bottom... tension at top)
    assert not sec.flexure(-1)["compression_flange"]


def test_dpt_balanced_limit_singly():
    inp = BeamInput(code=DPT, bw=300, h=600, fc=24, fy=392, stirrup_d=9)
    sec = BeamSection(inp, Reinforcement(top1=Layer(0, 16), bot1=Layer(3, 20)))
    d = sec.tension_steel(1)[1]
    rho_b = 0.85 * 0.85 * 24 / 392 * 600 / (600 + 392)
    assert sec.as_max(1) == pytest.approx(0.75 * rho_b * 300 * d, rel=1e-9)


def test_as_min():
    inp = BeamInput(code=ACI, bw=300, h=600, fc=28, fy=420, stirrup_d=10)
    sec = BeamSection(inp, SINGLY)
    d = sec.tension_steel(1)[1]
    assert sec.as_min(1) == pytest.approx(max(0.25 * math.sqrt(28), 1.4) / 420 * 300 * d)


def test_required_as_matches_mu():
    inp = BeamInput(code=ACI, bw=300, h=600, fc=28, fy=420, stirrup_d=10)
    sec = BeamSection(inp, SINGLY)
    Mu = 250e6
    req = sec.required_as(Mu, 1)["As"]
    d = sec.tension_steel(1)[1]
    a = req * 420 / (0.85 * 28 * 300)
    assert 0.9 * req * 420 * (d - a / 2) == pytest.approx(Mu, rel=1e-4)


def test_compression_steel_raises_capacity_limit():
    inp = BeamInput(code=DPT, bw=250, h=500, fc=24, fy=392, stirrup_d=9)
    singly = BeamSection(inp, Reinforcement(top1=Layer(0, 16), bot1=Layer(3, 20)))
    doubly = BeamSection(inp, Reinforcement(top1=Layer(3, 20), bot1=Layer(3, 20)))
    assert doubly.as_max(1) > singly.as_max(1)
    # section equilibrium holds with yielded / elastic compression bars
    f = doubly.flexure(1)
    Cs = sum(F for A, y, eps, fs, F in f["steel"] if F > 0)
    T = -sum(F for A, y, eps, fs, F in f["steel"] if F < 0)
    assert f["Cc"] + Cs == pytest.approx(T, rel=1e-6)


def test_shear_dpt():
    inp = BeamInput(code=DPT, bw=300, h=600, fc=24, fy=392, fyt=235, stirrup_d=9, legs=2)
    sec = BeamSection(inp, SINGLY)
    sh = shear_check(sec, 200e3, 150)
    d = sh["d"]
    Vc = math.sqrt(24) / 6 * 300 * d
    Vs = 2 * math.pi * 81 / 4 * 235 * d / 150
    assert sh["Vc"] == pytest.approx(Vc)
    assert sh["phiVn"] == pytest.approx(0.85 * (Vc + Vs))
    assert sh["s_max"] == pytest.approx(min(d / 2, 600))


def test_shear_aci_size_effect_without_min_stirrups():
    inp = BeamInput(code=ACI, bw=300, h=900, fc=28, fy=420, fyt=420, stirrup_d=6, legs=2)
    sec = BeamSection(inp, Reinforcement(top1=Layer(2, 16), bot1=Layer(3, 20)))
    sh = shear_check(sec, 50e3, 600)            # Av < Av,min
    assert sh["Av"] < sh["Av_min"]
    d = sh["d"]
    lam_s = math.sqrt(2 / (1 + d / 254))
    rho = 3 * math.pi * 100 / (300 * d)
    assert sh["Vc"] == pytest.approx(0.66 * lam_s * rho ** (1 / 3) * math.sqrt(28) * 300 * d)


def test_shear_tight_spacing_when_vs_high():
    inp = BeamInput(code=ACI, bw=300, h=600, fc=28, fyt=420, stirrup_d=12, legs=2)
    sec = BeamSection(inp, SINGLY)
    sh = shear_check(sec, 700e3, 100)
    assert sh["tight"]
    assert sh["s_max"] == pytest.approx(min(sh["d"] / 4, 300))


def test_cracked_section_rectangular():
    inp = BeamInput(code=ACI, bw=300, h=600, fc=28, stirrup_d=10)
    sec = BeamSection(inp, SINGLY)
    cr = sec.cracked(1)
    n, As, d = cr["n"], 4 * math.pi * 100, sec.tension_steel(1)[1]
    rho = As / (300 * d)
    k = math.sqrt(2 * rho * n + (rho * n) ** 2) - rho * n
    assert cr["kd"] == pytest.approx(k * d, rel=1e-6)
    Icr = 300 * (k * d) ** 3 / 3 + n * As * (d - k * d) ** 2
    assert cr["Icr"] == pytest.approx(Icr, rel=1e-6)


def test_deflection_uncracked_simple_span():
    inp = BeamInput(code=ACI, bw=300, h=600, fc=28, stirrup_d=10)
    sec = BeamSection(inp, SINGLY)
    w, L = 2.0, 5000.0                     # small load -> Ma < 2/3 Mcr -> Ig
    out = deflection(inp, sec, L, "simple", w, 0.0)
    assert out["IeD"] == pytest.approx(sec.Ig)
    assert out["dD"] == pytest.approx(5 * w * L ** 4 / (384 * sec.Ec * sec.Ig))


def test_min_depth_and_forces():
    inp = BeamInput(fy=420)
    assert min_depth(inp, 6000, "simple") == pytest.approx(6000 / 16 * 1.0)
    f = span_forces(inp, 6000, "end", 30.0, 500)
    assert f["Mpos"] == pytest.approx(30 * 6000 ** 2 / 14)
    assert f["Mneg"] == pytest.approx(30 * 6000 ** 2 / 10)
    assert f["Vu_d"] == pytest.approx(1.15 * 30 * 3000 - 30 * 500)


def test_development_length():
    inp = BeamInput(code=ACI, fc=28, fy=420)
    dl = development_length(inp, 25, top=True, clear_spacing=50, clear_cover=50)
    assert dl["ld"] == pytest.approx(420 * 1.3 / (1.7 * math.sqrt(28)) * 25)
    inp = BeamInput(code=DPT, fc=24, fy=392)
    dl = development_length(inp, 16, top=False, clear_spacing=50, clear_cover=50)
    assert dl["ld"] == pytest.approx(max(12 / 25 * 392 / math.sqrt(24) * 16, 300))


def test_design_location_and_suggestion():
    inp = BeamInput(code=ACI, bw=300, h=600, fc=28, fy=420, fyt=420, stirrup_d=10)
    loc = Location("mid", 400e6, 250e3, SINGLY)
    assert not design_location(inp, loc).ok
    r = suggest_reinforcement(inp, loc, 25, 16)
    assert r is not None
    res = design_location(inp, Location("mid", 400e6, 250e3, r))
    assert res.ok, [c for c in res.checks + res.detail if not c["ok"]]
    # hogging puts tension bars on top
    r2 = suggest_reinforcement(inp, Location("sup", -300e6, 200e3, SINGLY), 20, 16)
    assert r2.top1.n >= 2 and r2.bot1.n >= 2
    assert design_location(inp, Location("sup", -300e6, 200e3, r2)).ok
