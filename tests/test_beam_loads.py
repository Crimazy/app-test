"""Load items under each span: formulas, slab load transfer, factored (Wu) loads."""
import pytest

from beam_loads import (
    AREA, LINE, POINT, SLAB, TRI, ExprError, evaluate, items_to_loads, loads_to_items, scale_item,
    slab_tributary,
)
from continuous_beam import (
    EXAMPLE_LOADS, EXAMPLE_NODES, EXAMPLE_SPANS, BeamModel, Load, Node, Settings, Span,
)


def test_formula_evaluation():
    assert evaluate("=(1.4*(2400*30/100+150)+1.7*400)*3.45/3/1000") == pytest.approx(2.1827)
    assert evaluate("2^3") == 8 and evaluate(" 1.5 ") == 1.5 and evaluate("") is None
    for bad in ["__import__('os')", "x+1", "2**99", "1/0", "open('f')"]:
        with pytest.raises(ExprError):
            evaluate(bad)


def test_slab_classification_and_tributary():
    one = slab_tributary(3.0, 7.0, beam_L=7.0)                 # L/S >= 2, beam on long side
    assert one["type"] == "One-way" and one["k"] == pytest.approx(1.5)
    assert slab_tributary(3.0, 7.0, beam_L=3.0)["k"] == 0.0   # one-way: short-side beam carries nothing
    short = slab_tributary(4.0, 5.0, beam_L=4.0)
    assert short["type"] == "Two-way" and short["side"] == "ด้านสั้น" and short["k"] == pytest.approx(4 / 3)
    long_ = slab_tributary(2.3, 3.8, beam_L=3.8)
    assert long_["k"] == pytest.approx(2.3 / 3 * (3 - (2.3 / 3.8) ** 2) / 2)
    assert slab_tributary(3.0, 4.0, beam_L=3.0, slab_type="One-way", side="ด้านยาว")["k"] == pytest.approx(1.5)


def test_slab_item_matches_excel_formula():
    """B_FL.2_A.6-7.xls, span 2: slab 15 cm one side (one-way S = 3.45) + slab 20 cm (two-way S = 5)."""
    items = [dict(span=1, kind=SLAB, S="3.45", L="7", t="15", DL="150", LL="400", side="ด้านยาว"),
             dict(span=1, kind=SLAB, S="5", L="5", t="20", DL="150", LL="200")]
    loads, res, err = items_to_loads(items, [Span(5, 30, 45)])
    assert not err
    wu = sum((1.4 if l.case == "DL" else 1.7) * l.w1 for l in loads)
    excel = (0.5 * (1.4 * (2400 * 15 / 100 + 150) + 1.7 * 400) * 3.45
             + (1.4 * (2400 * 20 / 100 + 150) + 1.7 * 200) * 5 / 3) / 1000
    assert wu == pytest.approx(excel)


def test_wall_point_triangle_and_multiple_items():
    items = [dict(span=1, kind=AREA, name="ผนัง 1", S="3.2", DL="200"),
             dict(span=1, kind=AREA, name="ผนัง 2", S="1.0", DL="100"),
             dict(span=1, kind=POINT, DL="2", LL="1", a="1.5"),
             dict(span=1, kind=POINT, DL="3", a="3"),
             dict(span=1, kind=TRI, DL="0;0.5", a="0", b="2"),
             dict(span=1, kind=LINE, WU="=1.4*0.2*3.2")]
    loads, res, err = items_to_loads(items, [Span(4, 25, 50)])
    assert not err
    walls = [l for l in loads if l.kind == "UDL" and l.case == "DL" and l.w1 == l.w2]
    assert sorted(l.w1 for l in walls) == pytest.approx([0.1, 0.64])
    assert len([l for l in loads if l.kind == "Point"]) == 3
    assert any(l.case == "U" and l.w1 == pytest.approx(0.896) for l in loads)


def test_bad_entries_are_reported():
    _, res, err = items_to_loads([dict(span=1, kind=SLAB, S="", DL="150"),
                                  dict(span=1, kind=POINT, DL="2", a="9"),
                                  dict(span=3, kind=LINE, DL="1")], [Span(4, 25, 50)])
    assert len(err) == 3 and all("error" in r for r in res)


def test_factored_items_equal_service_items_factored():
    """Wu = 1.4·DL + 1.7·LL entered directly gives the same result as DL / LL on a single span.
    (On continuous beams DL / LL also gets pattern LL and the 1.4D check, which Wu cannot.)"""
    st = Settings(self_weight=False, pattern=False)
    sp, nd = [Span(5, 25, 50)], [Node("Fixed"), Node("Pin")]
    a = BeamModel(st, sp, nd, [Load(1, "DL", "UDL", 2.0), Load(1, "LL", "UDL", 1.0),
                               Load(1, "DL", "Point", 3.0, a=2.0)]).summary()
    b = BeamModel(st, sp, nd, [Load(1, "U", "UDL", 1.4 * 2 + 1.7),
                               Load(1, "U", "Point", 1.4 * 3, a=2.0)]).summary()
    for x, y in zip(a, b):
        for k in ("Mpos_max", "MR_min", "Vu_left"):
            assert x[k] == pytest.approx(y[k])


def test_example_loads_round_trip_through_items():
    items = loads_to_items(EXAMPLE_LOADS, EXAMPLE_SPANS)
    loads, _, err = items_to_loads(items, EXAMPLE_SPANS)
    assert not err
    a = BeamModel(Settings(), EXAMPLE_SPANS, EXAMPLE_NODES, EXAMPLE_LOADS).summary()
    b = BeamModel(Settings(), EXAMPLE_SPANS, EXAMPLE_NODES, loads).summary()
    for x, y in zip(a, b):
        assert x["Mpos_max"] == pytest.approx(y["Mpos_max"]) and x["Vu_right"] == pytest.approx(y["Vu_right"])


def test_unit_scaling_keeps_formulas():
    it = scale_item(dict(kind=LINE, DL="0.65", LL="=0.1+0.05"), 9.80665)
    assert evaluate(it["DL"]) == pytest.approx(0.65 * 9.80665)
    assert evaluate(it["LL"]) == pytest.approx(0.15 * 9.80665)
    assert scale_item(dict(kind=SLAB, DL="150"), 9.8)["DL"] == "150"      # kg/m² unchanged
