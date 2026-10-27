"""Graphical beam input (SUTStructor style) for the continuous-beam page.

* beam presets: simple / continuous / cantilever / continuous with overhangs
* input_figure : plotly drawing of the beam with supports and loads; every span
                 and support is a clickable trace (mode A: click, edit below)
* beam_editor  : bidirectional custom component (mode B: edit in a popup drawn
                 on the beam itself), see components/beam_editor/index.html

Spans / loads here are plain dicts in the *display* force unit
(span: name, L, b, h, DL, LL; extra load: span, case, kind, w1, w2, a, b).
"""
from __future__ import annotations

import math
import os

import plotly.graph_objects as go

from continuous_beam import MAXS, Node

PRESETS = {
    "simple": "คานเดี่ยว (Pin – Pin)",
    "continuous": "คานต่อเนื่อง",
    "cantilever": "คานยื่นอย่างเดียว (Fixed – Free)",
    "cont_left": "คานต่อเนื่อง + ยื่นซ้าย",
    "cont_right": "คานต่อเนื่อง + ยื่นขวา",
    "cont_both": "คานต่อเนื่อง + ยื่นสองข้าง",
    "simple_series": "คานเดี่ยวหลายช่วงต่อกัน",
}
MULTI = {"continuous", "cont_left", "cont_right", "cont_both", "simple_series"}


def build_preset(kind: str, n: int = 2, L: float = 4.0, Lc: float = 1.5, b: float = 25.0, h: float = 50.0,
                 support: str = "Pin"):
    """Return (spans, nodes, all_simple) for a beam layout; n = number of interior spans."""
    n = max(1, int(n)) if kind in MULTI else 1
    if kind == "continuous":
        n = max(2, n)

    def span(Lx):
        return dict(name="B1", L=Lx, b=b, h=h, DL=None, LL=None)

    if kind == "simple":
        return [span(L)], [Node("Pin"), Node("Pin")], False
    if kind == "cantilever":
        return [span(Lc)], [Node("Fixed"), Node("Free")], False
    inner = [span(L) for _ in range(n)]
    inner_nodes = [Node(support) for _ in range(n + 1)]
    if kind == "cont_left":
        spans, nodes = [span(Lc)] + inner, [Node("Free")] + inner_nodes
    elif kind == "cont_right":
        spans, nodes = inner + [span(Lc)], inner_nodes + [Node("Free")]
    elif kind == "cont_both":
        spans, nodes = [span(Lc)] + inner + [span(Lc)], [Node("Free")] + inner_nodes + [Node("Free")]
    else:
        spans, nodes = inner, inner_nodes
    return spans[:MAXS], nodes[: MAXS + 1], kind == "simple_series"


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


DL_C, LL_C, PT_C = "#188038", "#1a73e8", "#e37400"


def input_figure(spans: list[dict], nodes: list[Node], extra: list[dict], wu_u: str, fu: str,
                 selected: tuple | None = None, all_simple: bool = False):
    """Beam drawing for input.  Returns (figure, targets) where targets[curve_number]
    is ("span", i) / ("node", j) for clickable traces (1-based)."""
    fig = go.Figure()
    targets: list = []

    def add(trace, target=None):
        fig.add_trace(trace)
        targets.append(target)

    X0 = [0.0]
    for s in spans:
        X0.append(X0[-1] + s["L"])
    total = X0[-1] or 1.0
    wmax = max([abs(_num(s.get(k)) or 0) for s in spans for k in ("DL", "LL")] +
               [max(abs(_num(e.get("w1")) or 0), abs(_num(e.get("w2")) or 0)) for e in extra
                if e.get("kind") != "Point"] + [1e-9])

    # selection highlight
    if selected and selected[0] == "span" and 1 <= selected[1] <= len(spans):
        i = selected[1]
        fig.add_shape(type="rect", x0=X0[i - 1], x1=X0[i], y0=-0.62, y1=1.22,
                      fillcolor="rgba(251,188,4,0.13)", line=dict(color="#f9ab00", width=1.5, dash="dot"))
    if selected and selected[0] == "node" and 1 <= selected[1] <= len(X0):
        xj = X0[selected[1] - 1]
        fig.add_shape(type="circle", x0=xj - total * 0.025, x1=xj + total * 0.025, y0=-0.35, y1=0.2,
                      line=dict(color="#f9ab00", width=2.5))

    fig.add_shape(type="line", x0=0, x1=total, y0=0, y1=0, line=dict(color="#3c4043", width=6))
    for i, s in enumerate(spans, 1):
        x0, x1 = X0[i - 1], X0[i]
        xm = (x0 + x1) / 2
        fig.add_annotation(x=xm, y=-0.42, text=f"<b>ช่วง {i}</b> {s['L']:.2f} m • {s['b']:g}×{s['h']:g}",
                           showarrow=False, font=dict(size=12, color="#3c4043"))
        top = 0.06
        for key, color in (("DL", DL_C), ("LL", LL_C)):
            w = _num(s.get(key)) or 0.0
            if w == 0:
                continue
            hgt = 0.12 + 0.3 * abs(w) / wmax
            fig.add_shape(type="rect", x0=x0, x1=x1, y0=top, y1=top + hgt, line=dict(color=color, width=1.5),
                          fillcolor="rgba(24,128,56,0.08)" if key == "DL" else "rgba(26,115,232,0.08)")
            fig.add_annotation(x=xm, y=top + hgt / 2, text=f"{key} = {w:.2f} {wu_u}", showarrow=False,
                               font=dict(size=12, color=color))
            top += hgt + 0.02
        stack = {}                            # point loads at the same place: stack the labels
        for e in extra:
            if int(e.get("span") or 0) != i:
                continue
            col = DL_C if e.get("case") == "DL" else LL_C
            if e.get("kind") == "Point":
                a = _num(e.get("a"))
                a = s["L"] / 2 if a is None else a
                xp = x0 + a
                k = stack.get(round(a, 6), 0)
                stack[round(a, 6)] = k + 1
                if k == 0:
                    fig.add_annotation(x=xp, y=0.05, ax=xp, ay=top + 0.32, xref="x", yref="y", axref="x",
                                       ayref="y", showarrow=True, arrowhead=2, arrowwidth=2.5, arrowcolor=PT_C,
                                       text="")
                fig.add_annotation(x=xp, y=top + 0.4 + 0.11 * k,
                                   text=f"P{e.get('case')} {_num(e.get('w1')) or 0:.2f} {fu}",
                                   showarrow=False, font=dict(size=11, color=col))
            else:
                a = _num(e.get("a")) or 0.0
                bb = _num(e.get("b"))
                bb = s["L"] if bb is None else bb
                w1 = _num(e.get("w1")) or 0.0
                w2 = _num(e.get("w2"))
                w2 = w1 if w2 is None else w2
                ya = top + 0.3 * abs(w1) / wmax
                yb = top + 0.3 * abs(w2) / wmax
                k = stack.get(("d", round(a, 6), round(bb, 6)), 0)
                stack[("d", round(a, 6), round(bb, 6))] = k + 1
                add(go.Scatter(x=[x0 + a, x0 + a, x0 + bb, x0 + bb, x0 + a], y=[top, ya, yb, top, top],
                               mode="lines", fill="toself", line=dict(color=col, width=1.2, dash="dot"),
                               hoverinfo="skip", showlegend=False))
                fig.add_annotation(x=x0 + (a + bb) / 2, y=max(ya, yb) + 0.06 + 0.09 * k, showarrow=False,
                                   font=dict(size=10, color=col),
                                   text=f"{e.get('case')} {w1:.2f}→{w2:.2f}")

        # clickable area of the span
        nx, ny = 24, 5
        xs = [x0 + (x1 - x0) * (k + 0.5) / nx for k in range(nx) for _ in range(ny)]
        ys = [-0.3 + 1.3 * (j + 0.5) / ny for _ in range(nx) for j in range(ny)]
        invisible = dict(marker=dict(opacity=0))
        add(go.Scatter(x=xs, y=ys, mode="markers", marker=dict(size=18, color="rgba(0,0,0,0)", opacity=0),
                       selected=invisible, unselected=invisible,
                       hovertemplate=f"ช่วง {i} — คลิกเพื่อแก้ไข<extra></extra>", showlegend=False),
            ("span", i))

    for j, nd in enumerate(nodes[: len(spans) + 1], 1):
        xj = X0[j - 1]
        kind = nd.kind
        brk = (1 < j <= len(spans)) and (all_simple or not nd.continuous)
        if kind == "Column":
            fig.add_shape(type="rect", x0=xj - total * 0.008, x1=xj + total * 0.008, y0=-0.32, y1=-0.04,
                          fillcolor="#bdc1c6", line=dict(color="#5f6368"))
            if nd.upper and nd.upper[0]:
                fig.add_shape(type="rect", x0=xj - total * 0.008, x1=xj + total * 0.008, y0=0.04, y1=0.5,
                              fillcolor="rgba(189,193,198,0.35)", line=dict(color="#9aa0a6", dash="dot"))
        elif kind == "Fixed":
            fig.add_shape(type="rect", x0=xj - total * 0.006, x1=xj + total * 0.006, y0=-0.3, y1=0.3,
                          fillcolor="#5f6368", line=dict(color="#202124"))
        marker = {"Pin": "triangle-up", "Column": "square", "Fixed": "square", "Free": "circle-open"}[kind]
        add(go.Scatter(x=[xj], y=[-0.12], mode="markers+text", text=[f"{j}"], textposition="bottom center",
                       marker=dict(symbol=marker, size=20 if kind != "Free" else 12,
                                   color="#f9ab00" if kind == "Pin" else ("#5f6368" if kind != "Free" else "#9aa0a6"),
                                   line=dict(color="#3c4043", width=1)),
                       selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1)),
                       hovertemplate=f"จุด {j}: {kind}{' (ตัดโมเมนต์)' if brk else ''} — คลิกเพื่อแก้ไข<extra></extra>",
                       showlegend=False), ("node", j))
        if brk:
            fig.add_scatter(x=[xj], y=[0], mode="markers", marker=dict(size=12, color="white",
                                                                   line=dict(color="#3c4043", width=2)),
                            hoverinfo="skip", showlegend=False)
            targets.append(None)
    fig.update_xaxes(visible=False, range=[-total * 0.04, total * 1.04], fixedrange=True)
    fig.update_yaxes(visible=False, range=[-0.7, 1.3], fixedrange=True)
    fig.update_layout(height=330, margin=dict(l=8, r=8, t=8, b=8), plot_bgcolor="white", dragmode=False,
                      clickmode="event+select", hovermode="closest")
    return fig, targets


# --------------------------------------------------------------------------
# Mode B: custom component with popups on the drawing
# --------------------------------------------------------------------------
_COMPONENT = None


def beam_editor(data: dict, key: str):
    """Render the popup editor; returns the last edit {type, index, ..., nonce} or None."""
    global _COMPONENT
    if _COMPONENT is None:
        import streamlit.components.v1 as components
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "components", "beam_editor")
        _COMPONENT = components.declare_component("beam_editor", path=path)
    return _COMPONENT(data=data, key=key, default=None)
