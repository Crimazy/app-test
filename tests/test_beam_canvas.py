import pytest

from beam_canvas import PRESETS, build_preset, input_figure
from continuous_beam import BeamModel, Load, Settings, Span


@pytest.mark.parametrize("kind,n,kinds,simple", [
    ("simple", 3, ["Pin", "Pin"], False),
    ("cantilever", 3, ["Fixed", "Free"], False),
    ("continuous", 1, ["Pin", "Pin", "Pin"], False),            # at least 2 spans
    ("cont_left", 2, ["Free", "Pin", "Pin", "Pin"], False),
    ("cont_right", 2, ["Pin", "Pin", "Pin", "Free"], False),
    ("cont_both", 2, ["Free", "Pin", "Pin", "Pin", "Free"], False),
    ("simple_series", 3, ["Pin", "Pin", "Pin", "Pin"], True),
])
def test_presets(kind, n, kinds, simple):
    spans, nodes, all_simple = build_preset(kind, n)
    assert [nd.kind for nd in nodes] == kinds
    assert len(nodes) == len(spans) + 1 and all_simple is simple
    # every preset is a stable structure
    st = Settings(self_weight=False, all_simple=all_simple)
    BeamModel(st, [Span(r["L"], r["b"], r["h"]) for r in spans], nodes,
              [Load(i, "DL", "UDL", 1.0) for i in range(1, len(spans) + 1)])
    assert kind in PRESETS


def test_input_figure_click_targets():
    spans, nodes, _ = build_preset("cont_right", 2)
    rows = [dict(r, DL=1.0, LL=0.5) for r in spans]
    extra = [dict(span=2, case="DL", kind="Point", w1=2.0, a=1.0), dict(span=2, case="LL", kind="Point", w1=1.0, a=1.0)]
    fig, targets = input_figure(rows, nodes, extra, "t/m", "t", ("span", 2))
    assert len(targets) == len(fig.data)
    assert [t for t in targets if t and t[0] == "span"] == [("span", i) for i in (1, 2, 3)]
    assert [t for t in targets if t and t[0] == "node"] == [("node", j) for j in (1, 2, 3, 4)]
