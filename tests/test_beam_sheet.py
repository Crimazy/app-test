"""Design sheet (Singly & Doubly) against the user's Excel forms.

Beam-Singly : B_FL.2_A.6-7.xlsx  (HB4: Mu 5,200 kg-m, Vu 6,000 kg, 20x50, fc' 320, 2-DB16)
Beam-Doubly : B_FL.2_J.1-2_db.xlsx (Mu 17,600 kg-m, Vu 11,800 kg, 20x45, fc' 280, 6-DB20 / 4-DB20)
"""
import pytest

from beam_sheet import SheetInput, compute, suggest
from beam_sheet_report import render_document, render_sheet


def singly():
    return SheetInput(fc=320, fy=4000, Mu=5200, Vu=6000, Vu_mid=2550, span=3.45, B=20, H=50, cover=4,
                      db=16, n_t=[2, 0, 0, 0], n_c=[2, 0, 0], ds=9, legs=2)


def doubly():
    return SheetInput(fc=280, fy=4000, Mu=17600, Vu=11800, Vu_mid=7615, span=6, B=20, H=45, cover=4,
                      db=20, n_t=[2, 2, 2, 0], n_c=[2, 2, 0], ds=9, legs=2)


@pytest.mark.parametrize("key,ref", [
    ("d", 44.3), ("beta1", 0.8214285714285714), ("rho_b", 0.033779220779220784),
    ("rho_max", 0.025334415584415588), ("rho_min", 0.003577708763999664), ("Ru", 59.14330285461293),
    ("d_sugg", 22.10103601353327), ("As_sugg", 7.4655577495065), ("Rn", 14.720527946073041),
    ("rho_req", 0.003785499691786775), ("As_req", 3.3539527269230827), ("rho", 0.004538644014215503),
    ("a", 2.9567930857315705), ("phiMn", 6199.051845236805),
])
def test_singly_form(key, ref):
    r = compute(singly())
    assert r["kind"] == "Singly"
    assert r[key] == pytest.approx(ref, rel=1e-9)


def test_singly_form_shear():
    r = compute(singly())
    z, m = r["sh_2h"], r["sh_mid"]
    assert z["phiVc"] == pytest.approx(7140.087045945589) and z["lim11"] == pytest.approx(14819.048585924811)
    assert z["lim21"] == pytest.approx(28290.91093676554)
    assert (z["case"], z["s"]) == (2, 10.0)          # EQ: min(d/4, 8db, 24ds, 30) = 11.075 -> 10
    assert (m["case"], m["s"]) == (1, 20.0)
    assert r["ok"]


@pytest.mark.parametrize("key,ref", [
    ("d", 34.1), ("dp", 5.9), ("rho_b", 0.030584881422924905), ("rho1", 0.015292440711462452),
    ("rho_max", 0.02293866106719368), ("rho_cy", 0.025260915453992144), ("P", 0.18635250540325002),
    ("c", 10.405232126177903), ("fs_c", 2649.822731281695), ("Ru1", 53.2853823704772),
    ("Mu1", 11152.939585358628), ("Mu2", 6447.060414641372), ("Asc_req", 9.586350435230976),
    ("As_req", 16.779976888544194), ("duct_val", 0.015432393395350361), ("a", 8.844447307251215),
    ("phiMn", 19695.992899320416),
])
def test_doubly_form(key, ref):
    r = compute(doubly())
    assert r["kind"] == "Doubly"
    assert r[key] == pytest.approx(ref, rel=1e-9)


def test_doubly_form_shear():
    r = compute(doubly())
    z, m = r["sh_2h"], r["sh_mid"]
    assert z["phiVc"] == pytest.approx(5141.125264247119) and z["case"] == 3
    assert z["s_ctrl"] == pytest.approx(8.525)        # EQ limit d/4
    assert m["case"] == 3 and m["s_ctrl"] == pytest.approx(17.05)
    assert r["ok"]


@pytest.mark.parametrize("Mu", [500, 3000, 8000, 15000, 22000, 30000])
def test_suggestion_passes(Mu):
    r = compute(suggest(SheetInput(fc=240, fy=4000, Mu=Mu, Vu=9000, Vu_mid=6000, B=25, H=50, db=20)))
    assert r["ok"], r["kind"]


def test_forced_doubly_when_rounded_singly_fails():
    """rho required just below rho_max: the bars needed fail the singly check -> designed as doubly."""
    s = suggest(SheetInput(fc=280, fy=4000, fy_rb=2400, Mu=17339, Vu=19784, Vu_mid=15000, span=6, B=25,
                           H=40, cover=3, db=20, ds=12, legs=2))
    r = compute(s)
    assert r["kind"] == "Doubly" and r["forced"] and r["ok"]


def test_render_page():
    page = render_sheet(compute(doubly()), dict(project="P", member="B1", page="1/1"))
    doc = render_document([page, render_sheet(compute(singly()), {})])
    assert doc.count('class="sheet"') == 2 and "Doubly" in doc and "Singly" in doc and "19,696" in doc
