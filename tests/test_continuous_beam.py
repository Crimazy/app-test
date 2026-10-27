"""Checks against the original workbook Beam_Design_Singly_Doubly.xlsm.

Reference values: ANALYSIS sheet written by the VBA macro, and DESIGN sheet
recalculated in LibreOffice, for the example shipped with the workbook.
"""
import math

import pytest

from continuous_beam import (
    CODE19, EXAMPLE_LOADS, EXAMPLE_NODES, EXAMPLE_OVERRIDES, EXAMPLE_SPANS, BeamModel, InputError,
    Load, Node, Settings, Span, design_all, helper_load, min_depth,
)


@pytest.fixture(scope="module")
def example():
    st = Settings()
    m = BeamModel(st, EXAMPLE_SPANS, EXAMPLE_NODES, EXAMPLE_LOADS)
    return st, m, m.summary()


# ANALYSIS!H6:Q9  (M left max/min, M+ max, x, M mid min, M right max/min, Vu left/mid/right)
REF_SUMMARY = [
    [0.0, 0.0, 0.0, 0, -0.949851562499995, -1.22107999999999, -1.47097999999999, 0.0, 1.688625, 1.424449],
    [-0.567866641241658, -1.08456726624625, 0.319874769574687, 1, -9.13934853124154, -10.5792782513257,
     -15.5869654450604, 1.36776313431145, 6.78224784818912, 7.96096784818912],
    [-12.9545579966308, -19.092673078038, 17.3391303451636, 3, 3.28762848670398, -12.9976192592366,
     -18.9763285330634, 19.7835765808053, 13.0497525808053, 19.7612367393979],
    [-10.7240952189546, -15.45644540197, 0.519103485116271, 3.2, -9.19747507879975, 0.125140435639524,
     -0.0347297248488947, 7.42658929854602, 6.57149153854602, 1.17138409015547],
]
KEYS = ["ML_max", "ML_min", "Mpos_max", "Mpos_x", "Mmid_min", "MR_max", "MR_min", "Vu_left", "Vu_mid", "Vu_right"]

# ANALYSIS!D19:I23 (R DL, R LL, Ru max, Ru min, Mu to column max, min)
REF_REACT = [
    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    [2.44940481417191, 0.274965925252006, 5.15104313431145, 2.17473241829831, -0.288255291201065, -0.85355824605005],
    [16.0968713094564, 5.77189982328534, 32.4760004289944, 22.4074689370687, 5.47774370399128, 3.13630873320174],
    [16.0049778660163, 5.18212840112253, 31.3054042779439, 22.31815202881, -3.22213978770456, -5.44169748805417],
    [0.623746010355363, -0.403994149659884, 1.32941268972869, -0.269713915155472, 0.0, 0.0],
]


def test_analysis_summary_matches_macro(example):
    _, _, summary = example
    for sm, ref in zip(summary, REF_SUMMARY):
        for k, v in zip(KEYS, ref):
            assert sm[k] == pytest.approx(v, abs=1e-9), (sm["span"], k)
    assert [s["type"] for s in summary] == ["Cantilever", "Continuous", "Continuous", "Continuous"]


def test_reactions_match_macro(example):
    _, m, _ = example
    for r, ref in zip(m.reactions(), REF_REACT):
        got = [r["RD"], r["RL"], r["Ru_max"], r["Ru_min"], r["Mu_max"], r["Mu_min"]]
        assert got == pytest.approx(ref, abs=1e-9)


def test_simple_span_udl_closed_form():
    """Pin-pin span, UDL: M = wL²/8, R = wL/2 (no pattern effect)."""
    st = Settings(self_weight=False)
    m = BeamModel(st, [Span(6, 25, 50)], [Node("Pin"), Node("Pin")], [Load(1, "DL", "UDL", 2.0),
                                                                       Load(1, "LL", "UDL", 1.0)])
    wu = 1.4 * 2 + 1.7 * 1
    assert m.env_M(1, 3.0)[0] == pytest.approx(wu * 36 / 8, rel=1e-9)
    assert m.reactions()[0]["Ru_max"] == pytest.approx(wu * 3, rel=1e-9)


def test_fixed_fixed_point_load():
    """Fixed-fixed span with central point load: end moments -PL/8 (DL only)."""
    st = Settings(self_weight=False)
    m = BeamModel(st, [Span(4, 25, 50)], [Node("Fixed"), Node("Fixed")], [Load(1, "DL", "Point", 10.0, a=2.0)])
    assert m.M(0, 1, 0.0) == pytest.approx(-10 * 4 / 8, rel=1e-9)
    assert m.M(0, 1, 2.0) == pytest.approx(10 * 4 / 8, rel=1e-9)


def test_unstable_structure_is_reported():
    st = Settings(all_simple=True)
    with pytest.raises(InputError):
        BeamModel(st, EXAMPLE_SPANS, EXAMPLE_NODES, EXAMPLE_LOADS)


@pytest.mark.parametrize("code", [None, CODE19])
def test_design_matches_workbook(example, code):
    st, _, summary = example
    if code:
        st = Settings(code=code)
    rows = {(r["span"], r["pos"]): r for r in design_all(st, summary, EXAMPLE_OVERRIDES)}
    left3, mid3, right3 = rows[3, "ซ้าย"], rows[3, "กลาง"], rows[3, "ขวา"]
    # DESIGN!Q13, V13, W13, AL13, AY13 (ACI 318-99) — identical bars for 318-19 in this example
    assert left3["flex"]["neg"]["type"] == "Doubly"
    assert left3["flex"]["top_txt"] == "7-DB20" and left3["flex"]["bot_txt"] == "2-DB20"
    assert mid3["flex"]["bot_txt"] == "6-DB20"
    assert right3["shear"]["label"] == "DB12 @ 0.075 m"
    assert mid3["shear"]["label"] == ("RB9 @ 0.100 m" if code is None else "RB9 @ 0.075 m")
    if code is not None:   # φ from εt (DESIGN!AX13, AY13 recalculated for ACI 318-19)
        assert left3["flex"]["cap_neg"]["phi"] == pytest.approx(0.867437243301781, rel=1e-9)
        assert left3["flex"]["cap_neg"]["phiMn"] == pytest.approx(20.9812031413898, rel=1e-9)
    else:
        assert left3["flex"]["neg"]["As"] == pytest.approx(19.9403527840986, rel=1e-9)
        assert left3["flex"]["neg"]["Asp"] == pytest.approx(1.17169312351495, rel=1e-9)
        assert left3["flex"]["cap_neg"]["phiMn"] == pytest.approx(21.7688172522717, rel=1e-9)
        assert left3["flex"]["cap_neg"]["fsp"] == pytest.approx(3806.11951884224, rel=1e-9)
        assert mid3["flex"]["pos_"]["As"] == pytest.approx(17.9638785943322, rel=1e-9)
        assert mid3["flex"]["cap_pos"]["phiMn"] == pytest.approx(19.0810019268653, rel=1e-9)
        assert left3["shear"]["s_str"] == pytest.approx(11.1516937398058, rel=1e-9)
        assert mid3["shear"]["s_ctrl"] == pytest.approx(12.4312505815671, rel=1e-9)
    assert all(r["ok"] for r in rows.values())


def test_minimum_depth_and_helper(example):
    st, _, _ = example
    got = [round(min_depth(st, EXAMPLE_NODES, i, 4, s)["hmin"]) for i, s in enumerate(EXAMPLE_SPANS, 1)]
    assert got == [18, 19, 28, 21]   # INPUT!H30:H33
    assert helper_load("สองทาง-ด้านสั้น (wS/3)", 4, 5, 438) == pytest.approx(0.584)
    assert helper_load("สองทาง-ด้านยาว", 4, 5, 438) == pytest.approx(0.68912)
    assert helper_load("ผนัง (w×สูง)", 2.8, None, 180) == pytest.approx(0.504)
    assert math.isclose(st.rhomax, 0.0229386610671937, rel_tol=1e-12)
