import math

import pytest

from aci318_column import (
    ColumnInput, ColumnSection, LoadCase, SlendernessInput, auto_select, beta1,
    check_case, detailing_checks, phi_factor, shear_check, slenderness_axis,
)


def test_beta1_table():
    assert beta1(28) == 0.85
    assert beta1(55) == 0.65
    assert beta1(35) == pytest.approx(0.80)


def test_phi_transition():
    assert phi_factor(0.001, 420, 200000, False) == pytest.approx(0.65)
    assert phi_factor(0.0051, 420, 200000, False) == pytest.approx(0.90)
    assert phi_factor(0.0036, 420, 200000, False) == pytest.approx(0.775)
    assert phi_factor(0.0036, 420, 200000, True) == pytest.approx(0.825)


def test_po_and_pn_max():
    sec = ColumnSection(ColumnInput(b=400, h=400, nx=3, ny=3, bar_d=20, fc=28, fy=420))
    Ast = 8 * math.pi * 100
    Po = 0.85 * 28 * (160000 - Ast) + 420 * Ast
    assert sec.Po == pytest.approx(Po)
    assert sec.phiPn_max == pytest.approx(0.65 * 0.80 * Po)


def test_strain_compatibility_hand_calc():
    """400x400, 8-DB20, c = 200 mm, bending about x (hand calculation)."""
    sec = ColumnSection(ColumnInput())
    p = sec.point(math.pi / 2, 200.0)
    Ab = math.pi * 100
    Cc = 0.85 * 28 * 170 * 400
    Ft = 3 * Ab * (420 - 0.85 * 28)
    Fb = -3 * Ab * 420
    P = Cc + Ft + Fb
    M = Cc * (200 - 85) + Ft * 140 - Fb * 140
    assert p["P"] == pytest.approx(P, rel=1e-6)
    assert p["Mx"] == pytest.approx(M, rel=1e-6)
    assert abs(p["My"]) < 1e-3


def test_biaxial_symmetry_and_dcr():
    sec = ColumnSection(ColumnInput())
    surf = sec.surface(72, 60)
    r = check_case(sec, surf, SlendernessInput(lu_x=1000, lu_y=1000),
                   LoadCase("t", 1000e3, 100e6, 0.0))
    assert r.phiMnx == pytest.approx(r.phiMny, rel=1e-3)
    assert r.dcr_moment == pytest.approx(100e6 / r.phiMnx, rel=1e-6)
    # biaxial at 45 deg is weaker than uniaxial for a square section
    r45 = check_case(sec, surf, SlendernessInput(lu_x=1000, lu_y=1000),
                     LoadCase("t", 1000e3, 100e6, 100e6))
    assert r45.phiMn_dir < r.phiMnx * math.sqrt(2)


def test_axial_beyond_capacity_fails():
    sec = ColumnSection(ColumnInput())
    surf = sec.surface(24, 30)
    r = check_case(sec, surf, SlendernessInput(), LoadCase("t", 1.1 * sec.phiPn_max, 10e6, 0))
    assert not r.ok


def test_slenderness_nonsway():
    sec = ColumnSection(ColumnInput())
    sl = SlendernessInput(lu_x=6000, m1m2_x=-1.0)  # single curvature -> limit 22
    s = slenderness_axis(sec, sl, "x", 1000e3, 50e6)
    assert s["klu_r"] == pytest.approx(6000 / 120)
    assert s["limit"] == pytest.approx(22)
    assert s["slender"] and s["Cm"] == pytest.approx(1.0)
    assert s["delta"] > 1.0


def test_shear_and_detailing():
    sec = ColumnSection(ColumnInput())
    sh = shear_check(sec, 1000e3, 100e3, "x")
    assert sh["eq"] == "22.5.5.1(a)"
    assert sh["phiVn"] > 0
    assert all(d["ok"] for d in detailing_checks(sec))
    bad = ColumnSection(ColumnInput(nx=2, ny=2, bar_d=12))  # rho < 1 %
    assert not all(d["ok"] for d in detailing_checks(bad))


def test_circular_spiral():
    inp = ColumnInput(shape="circular", D=500, n_circ=8, transverse="spiral", s=60)
    sec = ColumnSection(inp)
    assert sec.phi_c == 0.75 and sec.alpha_max == 0.85
    assert sec.Ag == pytest.approx(math.pi * 250 ** 2)


def test_auto_select_finds_passing_layout():
    best = auto_select(ColumnInput(), SlendernessInput(), [LoadCase("t", 1500e3, 150e6, 60e6)])
    assert best is not None
    sec = ColumnSection(best)
    r = check_case(sec, sec.surface(), SlendernessInput(), LoadCase("t", 1500e3, 150e6, 60e6))
    assert r.dcr_moment <= 1.0
