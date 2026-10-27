"""Load items entered under each span (SUTStructor / Excel style).

Every span has a list of load items.  Each item has a type (slab, wall, line
load, triangle, point), its geometry (S, L, a, b) and up to three load values.
A slab item only needs the slab size and thickness: its weight (gamma_c x t +
SDL), one-way / two-way type (L/S >= 2 -> one-way, or chosen) and the beam side
(short / long, from the beam span or chosen) give the load on the beam.
Load values:

  DL, LL : service (unfactored) dead / live load -> factored by the program
           (pattern LL, selectable load combination)
  Wu     : already factored load, Excel style (e.g. 1.4*(...)+1.7*(...))

Every value is a text that may be a formula, e.g. "2400*0.3+150" or
"=(1.4*(2400*30/100+150)+1.7*400)*3.45/3/1000".

Units: slab / wall values in kg/m^2 (as on the drawings); line loads in the
display force unit per metre; point loads in the display force unit.
"""
from __future__ import annotations

import ast
import math
import operator

from continuous_beam import Load

# ---------------------------------------------------------------------------
# Safe formula evaluation
# ---------------------------------------------------------------------------
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUN = {"sqrt": math.sqrt, "min": min, "max": max, "abs": abs, "round": round}
_CONST = {"pi": math.pi}


class ExprError(ValueError):
    pass


def evaluate(text) -> float | None:
    """Evaluate a number or a simple formula; blank -> None.

    Accepts + - * / ^ (power) ( ), a leading '=', ',' as decimal separator is NOT
    accepted (use '.'), and sqrt/min/max/abs/round/pi.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return None if isinstance(text, float) and math.isnan(text) else float(text)
    s = str(text).strip()
    if not s:
        return None
    if s.startswith("="):
        s = s[1:]
    s = s.replace("^", "**").replace("×", "*").replace("÷", "/")
    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError:
        raise ExprError(f"สูตรไม่ถูกต้อง: {text}") from None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 10:
                raise ExprError(f"เลขยกกำลังใหญ่เกินไป: {text}")
            return _BIN[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
            return _UN[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Name) and n.id in _CONST:
            return _CONST[n.id]
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUN
                and not n.keywords and len(n.args) <= 4):
            return float(_FUN[n.func.id](*[ev(a) for a in n.args]))
        raise ExprError(f"สูตรไม่ถูกต้อง: {text}")

    try:
        v = ev(tree)
    except ZeroDivisionError:
        raise ExprError(f"หารด้วยศูนย์: {text}") from None
    if not math.isfinite(v):
        raise ExprError(f"ผลลัพธ์ไม่ใช่ตัวเลข: {text}")
    return v


# ---------------------------------------------------------------------------
# Load item types
# ---------------------------------------------------------------------------
SLAB = "พื้น (คิดให้อัตโนมัติ)"
AREA = "ผนัง / กว้างรับ (w×S)"
LINE = "น้ำหนักแผ่ (ต่อเมตร)"
TRI = "สามเหลี่ยม/คางหมู (w1;w2)"
POINT = "แรงจุด P ที่ a"
KINDS = [SLAB, AREA, LINE, TRI, POINT]
AREAL = {SLAB, AREA}
SLAB_TYPES = ["อัตโนมัติ", "One-way", "Two-way"]
SIDES = ["อัตโนมัติ", "ด้านสั้น", "ด้านยาว"]
KIND_HELP = {
    SLAB: ("S × L = ขนาดพื้น (m), t = หนา (cm), DL = SDL เพิ่ม (kg/m², เช่น 150), LL (kg/m²) → "
           "w = 2400·t + SDL; One-way (L/S ≥ 2): คานด้านยาว w·S/2, คานด้านสั้น 0; "
           "Two-way: ด้านสั้น w·S/3, ด้านยาว w·S/3·(3−m²)/2, m = S/L"),
    AREA: "S = ความสูงผนัง หรือความกว้างรับน้ำหนัก (m); DL, LL เป็น kg/m² → w·S",
    LINE: "ค่าเป็นน้ำหนักต่อเมตร (t/m หรือ kN/m ตามหน่วยที่เลือก)",
    TRI: "ใส่ค่าที่ปลาย a และปลาย b คั่นด้วย ; เช่น 0;0.5 (ต่อเมตร)",
    POINT: "ค่าเป็นแรง (t หรือ kN) กระทำที่ระยะ a จากปลายซ้ายของช่วง",
}
ITEM_FIELDS = ["span", "name", "kind", "S", "L", "t", "type", "side", "DL", "LL", "WU", "a", "b"]
CASES = (("DL", "DL"), ("LL", "LL"), ("WU", "U"))


def _txt(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v).strip()


def _pair(text):
    """'w1;w2' -> (w1, w2); single value -> (w, w)."""
    s = _txt(text)
    if not s:
        return None
    parts = [p for p in s.replace("→", ";").split(";")]
    if len(parts) == 1:
        v = evaluate(parts[0])
        return None if v is None else (v, v)
    if len(parts) != 2:
        raise ExprError(f"ใส่ 2 ค่าคั่นด้วย ; : {text}")
    w1, w2 = evaluate(parts[0]), evaluate(parts[1])
    return (w1 or 0.0, w2 or 0.0)


def slab_tributary(S: float | None, L: float | None, beam_L: float, slab_type: str = "อัตโนมัติ",
                   side: str = "อัตโนมัติ") -> dict:
    """Tributary width k (m) of a slab panel S x L on the beam, with the slab type and
    beam side used.  One-way when L/S >= 2 (or chosen)."""
    if not S or S <= 0:
        raise ExprError("ต้องใส่ขนาดพื้น S (m)")
    if not L or L <= 0:
        L = S if slab_type != "One-way" else 2 * S      # square panel unless told otherwise
    S, L = min(S, L), max(S, L)
    m = S / L
    typ = slab_type if slab_type in ("One-way", "Two-way") else ("One-way" if L / S >= 2 else "Two-way")
    if side not in ("ด้านสั้น", "ด้านยาว"):
        side = "ด้านสั้น" if abs(beam_L - S) < abs(beam_L - L) else "ด้านยาว"
    if typ == "One-way":
        k = S / 2 if side == "ด้านยาว" else 0.0
        rule = "w·S/2" if side == "ด้านยาว" else "0 (พื้นทางเดียวไม่ถ่ายลงคานด้านสั้น)"
    elif side == "ด้านสั้น":
        k, rule = S / 3, "w·S/3"
    else:
        k, rule = S / 3 * (3 - m * m) / 2, "w·S/3·(3−m²)/2"
    return dict(k=k, type=typ, side=side, m=m, S=S, L=L, rule=rule)


def areal_factor(kind: str, S: float | None) -> float:
    """Tributary width (m) of a wall / loaded strip."""
    if S is None or S <= 0:
        raise ExprError("ต้องใส่ S (m)")
    return S


def item_loads(item: dict, span_L: float, U: float = 1.0, gc: float = 2.4) -> tuple[list[Load], dict]:
    """Loads (engine units, t / t-m) for one item and the per-case results in the
    display unit {"DL": .., "LL": .., "WU": .., "unit": "/m" | "", "k": tributary m}.
    Raises ExprError for a bad entry."""
    kind = item.get("kind") or LINE
    sp = int(item.get("span") or 0)
    a = evaluate(item.get("a"))
    b = evaluate(item.get("b"))
    out, res = [], {"unit": "" if kind == POINT else "/m"}
    slab_w = 0.0
    if kind == SLAB:
        info = slab_tributary(evaluate(item.get("S")), evaluate(item.get("L")), span_L,
                              _txt(item.get("type")) or "อัตโนมัติ", _txt(item.get("side")) or "อัตโนมัติ")
        t = evaluate(item.get("t")) or 0.0
        slab_w = gc * 1000 * t / 100                     # kg/m^2 of the slab itself
        res.update(info)
        res["slab_w"] = slab_w
        res["note"] = (f"{info['type']} (m = {info['m']:.2f}), คานอยู่{info['side']} → {info['rule']}, "
                       f"k = {info['k']:.3f} m" + (f", นน.พื้น {slab_w:.0f} kg/m²" if t else ""))
    elif kind in AREAL:
        res["k"] = areal_factor(kind, evaluate(item.get("S")))
    a0 = 0.0 if a is None else a
    b0 = span_L if b is None else b
    if kind != POINT and (a0 < 0 or b0 > span_L + 1e-6 or b0 <= a0):
        raise ExprError(f"ช่วง a–b ไม่ถูกต้อง (0 ≤ a < b ≤ {span_L:g} m)")
    for field, case in CASES:
        if kind == TRI:
            pr = _pair(item.get(field))
            if pr is None:
                continue
            w1, w2 = pr[0] / U, pr[1] / U
            out.append(Load(sp, case, "UDL", w1, w2, a0, b0))
            res[field] = (pr[0], pr[1])
            continue
        v = evaluate(item.get(field))
        if field == "DL" and kind == SLAB and slab_w:
            v = (v or 0.0) + slab_w                      # slab weight + SDL
        if v is None:
            continue
        if kind in AREAL:
            w = v * res["k"] / 1000.0                    # kg/m^2 x m -> t/m
            out.append(Load(sp, case, "UDL", w, w, a0, b0))
            res[field] = w * U
        elif kind == POINT:
            pos = span_L / 2 if a is None else a
            if pos < 0 or pos > span_L + 1e-6:
                raise ExprError(f"ตำแหน่ง a ของแรงจุดอยู่นอกช่วง (0–{span_L:g} m)")
            out.append(Load(sp, case, "Point", v / U, a=pos))
            res[field] = v
        else:
            out.append(Load(sp, case, "UDL", v / U, v / U, a0, b0))
            res[field] = v
    return out, res


def items_to_loads(items: list[dict], spans: list, U: float = 1.0, gc: float = 2.4):
    """All items -> (loads, results list, errors list).  results[i] matches items[i]."""
    loads, results, errors = [], [], []
    for n, it in enumerate(items, 1):
        sp = int(it.get("span") or 0)
        if not 1 <= sp <= len(spans):
            results.append({"error": "หมายเลขช่วงไม่ถูกต้อง"})
            errors.append(f"รายการ {n}: หมายเลขช่วงไม่ถูกต้อง")
            continue
        try:
            ld, res = item_loads(it, spans[sp - 1].L, U, gc)
            loads += ld
            results.append(res)
        except ExprError as exc:
            results.append({"error": str(exc)})
            errors.append(f"ช่วง {sp} – {it.get('name') or it.get('kind')}: {exc}")
    return loads, results, errors


def loads_to_items(loads: list[Load], spans: list, U: float = 1.0) -> list[dict]:
    """Convert engine loads (example / imported workbook) into items, merging the
    DL and LL parts that share the same geometry."""
    rows: dict = {}
    for ld in loads:
        L = spans[ld.span - 1].L if 1 <= ld.span <= len(spans) else 0.0
        field = {"DL": "DL", "LL": "LL", "U": "WU"}.get(ld.case.upper(), "DL")
        if ld.kind.upper() == "POINT":
            a = L / 2 if ld.a is None else ld.a
            key = (ld.span, POINT, round(a, 6), None)
            row = rows.setdefault(key, dict(span=ld.span, name="", kind=POINT, a=f"{a:.6g}"))
            row[field] = f"{ld.w1 * U:.6g}"
            continue
        w2 = ld.w1 if ld.w2 is None else ld.w2
        a = 0.0 if ld.a is None else ld.a
        b = L if ld.b is None else ld.b
        full = a <= 1e-9 and abs(b - L) < 1e-9
        kind = LINE if abs(w2 - ld.w1) < 1e-12 else TRI
        key = (ld.span, kind, round(a, 6), round(b, 6))
        row = rows.setdefault(key, dict(span=ld.span, name="", kind=kind,
                                        a="" if full else f"{a:.6g}", b="" if full else f"{b:.6g}"))
        row[field] = (f"{ld.w1 * U:.6g}" if kind == LINE else f"{ld.w1 * U:.6g};{w2 * U:.6g}")
    out = []
    for r in rows.values():
        out.append({f: r.get(f, "") for f in ITEM_FIELDS} | {"span": r["span"]})
    out.sort(key=lambda r: int(r["span"]))
    return out


def scale_item(item: dict, f: float) -> dict:
    """Unit change: scale the force values of line / triangle / point items."""
    if item.get("kind") in AREAL:
        return dict(item)
    new = dict(item)
    for field in ("DL", "LL", "WU"):
        s = _txt(item.get(field))
        if not s:
            continue
        parts = s.replace("→", ";").split(";")
        conv = []
        for p in parts:
            p = p.strip()
            try:
                float(p)
                conv.append(f"{float(p) * f:.6g}")
            except ValueError:
                body = p[1:] if p.startswith("=") else p
                conv.append(f"({body})*{f:.6g}")
        new[field] = ";".join(conv)
    return new
