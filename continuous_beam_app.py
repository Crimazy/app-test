"""Streamlit page: continuous RC beam analysis & design (Singly / Doubly).

Port of the workbook "Beam_Design_Singly_Doubly.xlsm"
(INPUT -> ANALYSIS -> DESIGN -> OUTPUT).  Units: t, m, cm, ksc.
"""
from __future__ import annotations

import math
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from continuous_beam import (
    BAR_SIZES, CODE99, CODES, EXAMPLE_LOADS, EXAMPLE_NODES, EXAMPLE_OVERRIDES, EXAMPLE_SPANS,
    MAXS, POSITIONS, STIRRUP_SIZES, SUPPORT_TYPES, BeamModel, InputError, Node, Override, Settings,
    Span, combination, design_all, min_depth, read_workbook,
)
from beam_loads import (
    AREAL, KIND_HELP, KINDS, LINE, LOAD_FIELDS, POINT, SIDES, SLAB, SLAB_TYPES, TRI, items_to_loads,
    loads_to_items, migrate_item, scale_item,
)
from beam_design import LOAD_PRESETS, TONF_TO_KN, preset_factors
from beam_canvas import MULTI, PRESETS, beam_editor, build_preset, input_figure
from beam_sheet import MODES, Bar, SheetInput, bar_name, bars_text, compute as sheet_compute, suggest as sheet_suggest
from beam_sheet_report import render_document, render_sheet
from beam_sheet_xlsx import build_workbook
from continuous_beam_report import build_report

st.set_page_config(page_title="ออกแบบคานต่อเนื่อง", page_icon="📐", layout="wide")
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.6rem;}
      div[data-testid="stMetricValue"] {font-size: 1.4rem;}
      .ok-badge {background:#e6f4ea;color:#137333;padding:4px 12px;border-radius:12px;font-weight:600;}
      .ng-badge {background:#fce8e6;color:#c5221f;padding:4px 12px;border-radius:12px;font-weight:600;}
    </style>
    """,
    unsafe_allow_html=True,
)
ss = st.session_state

# --------------------------------------------------------------------------
# State: settings are widgets (cb_*); tables are base DataFrames + editors
# --------------------------------------------------------------------------
SET_KEYS = dict(fc="cb_fc", fy="cb_fy", fys="cb_fys", Es="cb_Es", gc="cb_gc", code="cb_code",
                pattern="cb_pattern", self_weight="cb_sw", cover="cb_cover", stir="cb_stir",
                legs="cb_legs", db="cb_db", all_simple="cb_allsimple")
PROJECT_KEYS = ["project", "location", "member", "type", "date", "job", "eng", "eng_lic", "chk", "chk_lic"]


def spans_df(spans):
    return pd.DataFrame([{"ชื่อคาน": s.name, "L (m)": s.L, "b (cm)": s.b, "h (cm)": s.h} for s in spans],
                        columns=["ชื่อคาน", "L (m)", "b (cm)", "h (cm)"])


# load items under each span: table column -> item field (values are text, formulas allowed)
ITEM_COLS = {"ช่วงที่": "span", "รายการ": "name", "ชนิด": "kind", "S (m)": "S", "L (m)": "L",
             "หนา t (cm)": "t", "แบบพื้น": "type", "คานอยู่ด้าน": "side", "DL": "DL", "SDL": "SDL", "LL": "LL",
             "Wu (ประลัย)": "WU", "a (m)": "a", "b (m)": "b"}
ITEM_TEXT = [c for c in ITEM_COLS if c not in ("ช่วงที่",)]


def items_df(items: list[dict]) -> pd.DataFrame:
    items = [migrate_item(it) for it in items]
    df = pd.DataFrame([{col: (it.get(f) if f != "span" else int(it.get("span") or 1)) for col, f in ITEM_COLS.items()}
                       for it in items], columns=list(ITEM_COLS))
    for c in ITEM_TEXT:
        df[c] = df[c].map(lambda v: "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v))
    return df


def df_items(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        if r.get("ช่วงที่") is None or (isinstance(r.get("ช่วงที่"), float) and math.isnan(r.get("ช่วงที่"))):
            continue
        it = {f: r.get(col) for col, f in ITEM_COLS.items()}
        it = {k: ("" if v is None or (isinstance(v, float) and math.isnan(v)) else v) for k, v in it.items()}
        it["span"] = int(float(it["span"]))
        it["kind"] = it["kind"] or LINE
        out.append(it)
    return out


def nodes_df(nodes):
    return pd.DataFrame([{
        "ชนิด": n.kind, "c (cm)": n.c or None,
        "เสาล่าง b": n.lower[0] or None, "เสาล่าง h": n.lower[1] or None, "เสาล่าง H (m)": n.lower[2] or None,
        "เสาบน b": n.upper[0] or None, "เสาบน h": n.upper[1] or None, "เสาบน H (m)": n.upper[2] or None,
        "ต่อเนื่อง": n.continuous,
    } for n in nodes]).astype({c: float for c in ["c (cm)", "เสาล่าง b", "เสาล่าง h", "เสาล่าง H (m)",
                                                  "เสาบน b", "เสาบน h", "เสาบน H (m)"]})


def load_state(settings: Settings, spans, nodes, loads, overrides, project=None, items=None):
    ss.cb_lc, ss.cb_fD, ss.cb_fL = "code", 1.4, 1.7
    ss.cb_sdl_same, ss.cb_fSD = True, 1.4
    for f, k in SET_KEYS.items():
        v = getattr(settings, f)
        ss[k] = int(v) if f in ("stir", "db", "legs") else v   # selectbox options are ints
    u = TONF_TO_KN if ss.get("cb_unit") == "kN" else 1.0
    ss.cb_spans = spans_df(spans)
    ss.cb_nodes = nodes_df(nodes)
    ss.cb_items = items_df(items if items is not None else loads_to_items(loads, spans, u))
    ss.cb_ov = dict(overrides)
    ss.cb_sheet_ov = {}
    for k in PROJECT_KEYS:
        ss[f"cb_pj_{k}"] = str((project or {}).get(k) or "")
    for k in [k for k in ss.keys() if k.endswith("_saved")]:
        del ss[k]
    ss.cb_ver = ss.get("cb_ver", 0) + 1     # reset the table editors


def table_editor(name: str, base, key: str, **kw) -> pd.DataFrame:
    """st.data_editor whose edits survive page switches.

    The edited table is saved after every run; a freshly mounted editor (first run,
    after an import, or after returning from another page) starts from the saved copy.
    """
    if key not in ss:
        ss[f"cb_{name}_base"] = base() if callable(base) else ss.get(f"cb_{name}_saved", base)
    out = st.data_editor(ss[f"cb_{name}_base"], key=key, **kw)
    ss[f"cb_{name}_saved"] = out
    return out


ss.setdefault("cb_unit", "t")
ss.setdefault("cb_preset", "continuous")
ss.setdefault("cb_preset_n", 2)
ss.setdefault("cb_input_mode", "คลิกแล้วกรอกด้านล่าง")
ss.setdefault("cb_sh_eq", True)
ss.setdefault("cb_sheet_ov", {})
ss.setdefault("cb_sh_rev", 0)
ss.setdefault("cb_sdl_same", True)
ss.setdefault("cb_fSD", 1.4)
ss.setdefault("cb_sh_rlim", 2.0)
ss.setdefault("cb_sh_cmin", 6.0)
if "cb_spans" not in ss:
    load_state(Settings(), EXAMPLE_SPANS, EXAMPLE_NODES, EXAMPLE_LOADS, EXAMPLE_OVERRIDES,
               dict(project="ตัวอย่าง: บ้านพักอาศัย 2 ชั้น", member="B1", date=str(date.today().year)))
    ss._cb_unit_prev = ss.cb_unit
ver = ss.cb_ver

# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 ไฟล์ข้อมูล")
    up = st.file_uploader("นำเข้าจากไฟล์ Excel (Beam_Design_Singly_Doubly.xlsm)", type=["xlsm", "xlsx"],
                          help="อ่านแผ่น INPUT (วัสดุ ช่วงคาน จุดรองรับ น้ำหนัก) และช่องสีเหลืองที่แก้ไว้ในแผ่น DESIGN")
    if up is not None and ss.get("cb_loaded_file") != (up.name, up.size):
        try:
            d = read_workbook(up)
            load_state(d["settings"], d["spans"], d["nodes"], d["loads"], d["overrides"], d["project"])
            ss.cb_loaded_file = (up.name, up.size)
            st.rerun()
        except Exception as exc:   # bad / foreign workbook
            st.error(f"อ่านไฟล์ไม่สำเร็จ: {exc}")
    if st.button("↺ โหลดข้อมูลตัวอย่าง"):
        load_state(Settings(), EXAMPLE_SPANS, EXAMPLE_NODES, EXAMPLE_LOADS, EXAMPLE_OVERRIDES,
                   dict(project="ตัวอย่าง: บ้านพักอาศัย 2 ชั้น", member="B1", date=str(date.today().year)))
        ss.pop("cb_loaded_file", None)
        st.rerun()

    st.radio("หน่วยแรง (น้ำหนักบรรทุก / ผลวิเคราะห์)", ["t", "kN"], key="cb_unit", horizontal=True,
             format_func=lambda u: "ตัน (t)" if u == "t" else "กิโลนิวตัน (kN)",
             help="แผ่น DESIGN / OUTPUT ยังแสดงเป็น t-m และ kg-m ตามแบบฟอร์มเดิม")
    if ss.get("_cb_unit_prev", "t") != ss.cb_unit:      # convert the force values of the load items
        f = TONF_TO_KN if ss.cb_unit == "kN" else 1 / TONF_TO_KN
        ss.cb_items = items_df([scale_item(it, f) for it in df_items(ss.get("cb_items_saved", ss.cb_items))])
        ss.pop("cb_items_saved", None)
        ss._cb_unit_prev = ss.cb_unit
        ss.cb_ver += 1
        st.rerun()

    st.header("1. วัสดุ และ มาตรฐาน")
    c1, c2 = st.columns(2)
    c1.number_input("fc' (ksc)", 100.0, 1000.0, step=10.0, key="cb_fc")
    c2.number_input("fy (ksc)", 2000.0, 7000.0, step=100.0, key="cb_fy")
    c1.number_input("fys ปลอก (ksc)", 2000.0, 7000.0, step=100.0, key="cb_fys")
    c2.number_input("Es (ksc)", 1.5e6, 2.5e6, step=10000.0, key="cb_Es", format="%.0f")
    c1.number_input("γc (t/m³)", 1.5, 3.0, step=0.1, key="cb_gc")
    st.selectbox("มาตรฐาน (φ, ρmax)", CODES, key="cb_code")
    st.selectbox("Load combination", list(LOAD_PRESETS), format_func=LOAD_PRESETS.get, key="cb_lc",
                 help="ตามมาตรฐาน = ตามตัวเลือกด้านบน (ACI 318-99 → 1.4D+1.7L, ACI 318-19 → 1.2D+1.6L) "
                      "• ตรวจ 1.4(DL + SDL) เพิ่มเสมอ")
    if ss.cb_lc == "custom":
        c1, c2 = st.columns(2)
        c1.number_input("ตัวคูณ DL", 1.0, 2.0, step=0.05, key="cb_fD")
        c2.number_input("ตัวคูณ LL", 1.0, 2.5, step=0.05, key="cb_fL")
    c1, c2 = st.columns([1.3, 1])
    c1.checkbox("SDL ใช้ตัวคูณเดียวกับ DL", key="cb_sdl_same",
                help="SDL = น้ำหนักบรรทุกคงที่เพิ่มเติม (วัสดุปูผิว ฝ้า งานระบบ ผนัง) แยกจาก DL (น้ำหนักคาน + พื้น) "
                     "— ปกติใช้ตัวคูณเดียวกับ DL; เอาออกเพื่อกำหนดตัวคูณ SDL เอง")
    if not ss.cb_sdl_same:
        c2.number_input("ตัวคูณ SDL", 1.0, 2.5, step=0.05, key="cb_fSD")
    c1, c2 = st.columns(2)
    c1.checkbox("คิด Pattern LL", key="cb_pattern")
    c2.checkbox("รวมน้ำหนักคาน", key="cb_sw")

    st.header("2. ระยะหุ้ม และ ขนาดเหล็ก")
    c1, c2 = st.columns(2)
    c1.number_input("ระยะหุ้มถึงปลอก (cm)", 1.0, 10.0, step=0.5, key="cb_cover")
    c2.selectbox("เหล็กปลอก Ø (mm)", STIRRUP_SIZES, key="cb_stir")
    c1.number_input("จำนวนขาปลอก", 2, 6, step=1, key="cb_legs")
    c2.selectbox("เหล็กหลัก Ø (mm)", BAR_SIZES, key="cb_db")

    with st.expander("ข้อมูลโครงการ (สำหรับรายการคำนวณ)"):
        labels = dict(project="Project", location="Location", member="Member", type="Type", date="Date",
                      job="Job No.", eng="Engineer", eng_lic="เลขใบอนุญาต (Engineer)", chk="Check by",
                      chk_lic="เลขใบอนุญาต (Check)")
        for k in PROJECT_KEYS:
            st.text_input(labels[k], key=f"cb_pj_{k}")
        logo = st.file_uploader("โลโก้บริษัท (หัวกระดาษ DESIGN SHEET)", type=["png", "jpg", "jpeg"],
                                key="cb_logo_up")
        if logo is not None:
            import base64
            ss.cb_logo = f"data:{logo.type};base64,{base64.b64encode(logo.getvalue()).decode()}"
        if ss.get("cb_logo") and st.button("ลบโลโก้"):
            ss.pop("cb_logo", None)

sett = Settings(**{f: ss[k] for f, k in SET_KEYS.items()})
sett = Settings(**{**sett.__dict__, "legs": int(sett.legs), "stir": float(sett.stir), "db": float(sett.db),
                   "load_factors": preset_factors(ss.cb_lc, (ss.cb_fD, ss.cb_fL)),
                   "sdl_factor": None if ss.cb_sdl_same else float(ss.cb_fSD)})

U = TONF_TO_KN if ss.cb_unit == "kN" else 1.0          # t -> display unit
fu, mu, wu_u = ("kN", "kN-m", "kN/m") if ss.cb_unit == "kN" else ("t", "t-m", "t/m")

# --------------------------------------------------------------------------
# Header + INPUT tables
# --------------------------------------------------------------------------
st.title("📐 ออกแบบคานต่อเนื่อง ค.ส.ล. — Singly & Doubly (SDM)")
st.caption("วิเคราะห์ Direct Stiffness (เสาคิด stiffness 4EI/H) • Pattern LL • ออกแบบทุกช่วง 3 ตำแหน่ง "
           "• หน่วย ตัน-เมตร / ksc / cm • จากไฟล์ Beam_Design_Singly_Doubly.xlsm")

# --------------------------------------------------------------------------
# Graphical input (SUTStructor style): presets, click-to-edit, popup editor
# --------------------------------------------------------------------------
NODE_NUM = ["c (cm)", "เสาล่าง b", "เสาล่าง h", "เสาล่าง H (m)", "เสาบน b", "เสาบน h", "เสาบน H (m)"]


def _clean(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def opt(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) or v == "" else float(v)


def cur(name: str) -> pd.DataFrame:
    """Latest version of a table (edits included)."""
    return ss.get(f"cb_{name}_saved", ss[f"cb_{name}"]).copy().reset_index(drop=True)


def commit(spans=None, nodes=None, items=None):
    for name, df in (("spans", spans), ("nodes", nodes), ("items", items)):
        if df is not None:
            ss[f"cb_{name}"] = df.reset_index(drop=True)
            ss.pop(f"cb_{name}_saved", None)
    ss.cb_ver += 1


def cur_nodes(n_nodes: int) -> pd.DataFrame:
    nd = cur("nodes")
    if len(nd) < n_nodes:
        nd = pd.concat([nd, nodes_df([Node("Pin")] * (n_nodes - len(nd)))], ignore_index=True)
    return nd.head(n_nodes)


def apply_preset():
    sp_rows, nodes_, simple = build_preset(ss.cb_preset, ss.cb_preset_n)
    spans_ = spans_df([Span(r["L"], r["b"], r["h"], r["name"]) for r in sp_rows])
    commit(spans=spans_, nodes=nodes_df(nodes_), items=items_df([]))
    ss.cb_allsimple = simple
    ss.cb_ov = {}
    ss.cb_sheet_ov = {}
    ss.cb_sel = ("span", 1)


def add_span():
    sp, it = cur("spans"), df_items(cur("items"))
    nd = cur_nodes(len(sp) + 1)
    right_free = len(nd) and nd.iloc[-1]["ชนิด"] == "Free" and len(sp) >= 2
    k = len(sp) - 1 if right_free else len(sp)          # 0-based position of the new span
    tmpl = sp.iloc[max(0, k - 1)].copy() if len(sp) else pd.Series(
        {"ชื่อคาน": "B1", "L (m)": 4.0, "b (cm)": 25.0, "h (cm)": 50.0})
    if right_free or (len(sp) == 1 and nd.iloc[-1]["ชนิด"] == "Free"):
        tmpl["L (m)"] = 4.0
    sp = pd.concat([sp.iloc[:k], tmpl.to_frame().T, sp.iloc[k:]], ignore_index=True)
    sp = sp.astype({"L (m)": float, "b (cm)": float, "h (cm)": float})
    pos = len(nd) - 1 if right_free else len(nd)
    nd = pd.concat([nd.iloc[:pos], nodes_df([Node("Pin")]), nd.iloc[pos:]], ignore_index=True)
    for x in it:
        if x["span"] > k:
            x["span"] += 1
    commit(spans=sp, nodes=nd, items=items_df(it))


def remove_last_span():
    sp = cur("spans")
    if len(sp) <= 1:
        return
    nd = cur_nodes(len(sp) + 1)
    it = [x for x in df_items(cur("items")) if x["span"] < len(sp)]
    commit(spans=sp.iloc[:-1], nodes=nd.iloc[:-1], items=items_df(it))
    if ss.get("cb_sel") and ss.cb_sel[1] > len(sp) - (0 if ss.cb_sel[0] == "node" else 1):
        ss.cb_sel = ("span", 1)


def update_span(i: int, vals: dict, items: list[dict]):
    """Save the size of span i and replace its load items."""
    sp = cur("spans")
    for col, key in (("ชื่อคาน", "name"), ("L (m)", "L"), ("b (cm)", "b"), ("h (cm)", "h")):
        if vals.get(key) not in (None, ""):
            sp.at[i - 1, col] = vals[key]
    keep = [x for x in df_items(cur("items")) if x["span"] != i]
    new = []
    for x in items:
        x = {f: x.get(f, "") for f in ITEM_COLS.values()} | {"span": i}
        x = {k: ("" if v is None else v) for k, v in x.items()}
        if any(str(x.get(f) or "").strip() for f in LOAD_FIELDS) or x.get("kind") == SLAB:
            new.append(x)
    allitems = sorted(keep + new, key=lambda x: x["span"])
    commit(spans=sp, items=items_df(allitems))


def update_node(j: int, n_nodes: int, v: dict):
    nd = cur_nodes(n_nodes)
    nd.at[j - 1, "ชนิด"] = v["kind"]
    for col, key in zip(NODE_NUM, ("c", "lb", "lh", "lH", "ub", "uh", "uH")):
        nd.at[j - 1, col] = v.get(key) if v.get(key) else None
    nd.at[j - 1, "ต่อเนื่อง"] = bool(v.get("cont", True))
    commit(nodes=nd.astype({c: float for c in NODE_NUM}))


def drawing_loads(spans, loads):
    """Loads in the display unit for the drawings: per span full-span totals (DL, SDL, LL, WU)
    and the other loads (partial / triangle / point)."""
    rows, extra = [], []
    for i, s in enumerate(spans, 1):
        tot = {"DL": 0.0, "SDL": 0.0, "LL": 0.0, "WU": 0.0}
        for ld in loads:
            if ld.span != i:
                continue
            key = {"DL": "DL", "SDL": "SDL", "LL": "LL", "U": "WU"}[ld.case]
            w2 = ld.w1 if ld.w2 is None else ld.w2
            full = (ld.kind == "UDL" and abs(w2 - ld.w1) < 1e-12 and (ld.a or 0) <= 1e-9
                    and (ld.b is None or abs(ld.b - s.L) < 1e-9))
            if full:
                tot[key] += ld.w1 * U
            else:
                extra.append(dict(span=i, case=key, kind="Point" if ld.kind == "Point" else "UDL",
                                  w1=ld.w1 * U, w2=w2 * U, a=ld.a, b=ld.b))
        rows.append(dict(name=s.name, L=s.L, b=s.b, h=s.h,
                         DL=tot["DL"] or None, SDL=tot["SDL"] or None, LL=tot["LL"] or None, WU=tot["WU"] or None))
    return rows, extra


def fmt_res(res: dict, field: str) -> str:
    v = res.get(field)
    if v is None:
        return ""
    if isinstance(v, tuple):
        return f"{v[0]:.3f} → {v[1]:.3f}"
    return f"{v:.3f}"


def items_results_df(items, results) -> pd.DataFrame:
    rows = []
    for it, res in zip(items, results):
        unit = fu if it["kind"] == POINT else wu_u
        rows.append({"ช่วง": it["span"], "รายการ": it.get("name") or it["kind"],
                     f"DL ({unit})": fmt_res(res, "DL"), f"SDL ({unit})": fmt_res(res, "SDL"),
                     f"LL ({unit})": fmt_res(res, "LL"),
                     f"Wu ({unit})": fmt_res(res, "WU"),
                     "หมายเหตุ": res.get("error") or res.get("note") or ""})
    return pd.DataFrame(rows)


ITEM_COLCFG = {
    "ช่วงที่": st.column_config.NumberColumn(min_value=1, max_value=MAXS, step=1, required=True, default=1),
    "รายการ": st.column_config.TextColumn(help="ชื่อรายการ เช่น พื้น S1, ผนังก่ออิฐ, คานซอย B3"),
    "ชนิด": st.column_config.SelectboxColumn(options=KINDS, required=True, default=SLAB, width="medium",
                                             help="\n\n".join(f"**{k}** — {v}" for k, v in KIND_HELP.items())),
    "S (m)": st.column_config.TextColumn(help="พื้น: ด้านสั้นของแผ่นพื้น • ผนัง: ความสูง • กว้างรับน้ำหนัก"),
    "L (m)": st.column_config.TextColumn(help="พื้น: ด้านยาวของแผ่นพื้น (ว่าง = พื้นสี่เหลี่ยมจัตุรัส)"),
    "หนา t (cm)": st.column_config.TextColumn(help="ความหนาพื้น — น้ำหนักพื้น = γc·t"),
    "แบบพื้น": st.column_config.SelectboxColumn(options=SLAB_TYPES, default="อัตโนมัติ",
                                                help="อัตโนมัติ: L/S ≥ 2 → One-way, น้อยกว่า → Two-way"),
    "คานอยู่ด้าน": st.column_config.SelectboxColumn(options=SIDES, default="อัตโนมัติ",
                                                   help="อัตโนมัติ: เทียบความยาวช่วงคานกับด้านของพื้น"),
    "DL": st.column_config.TextColumn(help="น้ำหนักบรรทุกคงที่ • พื้น: น้ำหนักพื้น γc·t คิดให้เอง ช่องนี้ = DL เพิ่ม (kg/m²) "
                                           "• ผนัง: kg/m² • แผ่: ต่อเมตร • จุด: แรง — พิมพ์สูตรได้ เช่น 2400*0.12"),
    "SDL": st.column_config.TextColumn(help="น้ำหนักบรรทุกคงที่เพิ่มเติม (วัสดุปูผิว ฝ้า งานระบบ ผนัง) หน่วยเดียวกับ DL "
                                            "— แยกกรณีจาก DL, ตัวคูณตั้งได้ที่แถบซ้าย • พิมพ์สูตรได้ เช่น 50+30+20"),
    "LL": st.column_config.TextColumn(help="น้ำหนักจร (หน่วยเดียวกับ DL) — พิมพ์สูตรได้"),
    "Wu (ประลัย)": st.column_config.TextColumn(help="น้ำหนักที่คูณตัวคูณแล้ว แบบ Excel เช่น "
                                                    "=(1.4*(2400*0.3+150)+1.7*400)*3.45/3/1000 — ไม่คิด pattern"),
    "a (m)": st.column_config.TextColumn(help="จุด: ตำแหน่งแรงจากปลายซ้าย • แผ่: จุดเริ่ม (ว่าง = 0)"),
    "b (m)": st.column_config.TextColumn(help="แผ่: จุดสิ้นสุด (ว่าง = L)"),
}


def draw_input(spans, nodes, items, results, loads):
    nS_ = len(spans)
    rows, extra = drawing_loads(spans, loads)

    st.markdown("#### 3. รูปแบบคาน และน้ำหนักบรรทุก")
    c1, c2, c3 = st.columns([3, 1.3, 2])
    c1.selectbox("รูปแบบคาน", list(PRESETS), format_func=PRESETS.get, key="cb_preset")
    c2.number_input("จำนวนช่วง", 1, MAXS, step=1, key="cb_preset_n", disabled=ss.cb_preset not in MULTI,
                    help="ไม่นับช่วงคานยื่น")
    c3.button("🏗️ สร้างรูปคานใหม่", on_click=apply_preset, width="stretch",
              help="สร้างช่วงคานและจุดรองรับตามรูปแบบที่เลือก (ล้างน้ำหนักเดิม)")
    c1, c2, c3, c4 = st.columns([1.3, 1.3, 2.2, 3.2])
    c1.button("➕ เพิ่มช่วง", on_click=add_span, width="stretch", disabled=nS_ >= MAXS)
    c2.button("➖ ลบช่วงสุดท้าย", on_click=remove_last_span, width="stretch", disabled=nS_ <= 1)
    c3.checkbox("คานเดี่ยวทุกช่วง", key="cb_allsimple", help="ไม่ต่อเนื่องที่จุดรองรับ (คานเดี่ยวต่อกัน)")
    mode = c4.radio("วิธีกรอก", ["คลิกแล้วกรอกด้านล่าง", "กรอกบนรูป (ป๊อปอัป)"], key="cb_input_mode",
                    horizontal=True, label_visibility="collapsed")
    if not nS_:
        st.info("ยังไม่มีช่วงคาน — เลือกรูปแบบคานแล้วกด 'สร้างรูปคานใหม่'")
        return

    if mode.startswith("กรอกบนรูป"):
        data = dict(spans=rows, nodes=[dict(kind=n.kind, c=n.c or None, lb=n.lower[0] or None, lh=n.lower[1] or None,
                                            lH=n.lower[2] or None, ub=n.upper[0] or None, uh=n.upper[1] or None,
                                            uH=n.upper[2] or None, cont=n.continuous) for n in nodes],
                    extra=extra, wu=wu_u, fu=fu, allSimple=bool(ss.cb_allsimple),
                    items=[dict({k: ("" if v is None else v) for k, v in it.items()},
                                res={f: fmt_res(r, f) for f in LOAD_FIELDS},
                                note=r.get("error") or r.get("note") or "", err=bool(r.get("error")))
                           for it, r in zip(items, results)],
                    kinds=KINDS, slabTypes=SLAB_TYPES, sides=SIDES, kindHelp=KIND_HELP,
                    slab=SLAB, point=POINT)
        val = beam_editor(data, key=f"cb_popup_{ss.cb_ver}")
        if val and val.get("nonce") != ss.get("_cb_nonce"):
            ss._cb_nonce = val["nonce"]
            if val["type"] == "span":
                update_span(int(val["index"]), val["span"], val.get("items") or [])
            else:
                update_node(int(val["index"]), nS_ + 1, val["node"])
            st.rerun()
        return

    sel = ss.get("cb_sel") or ("span", 1)
    if (sel[0] == "span" and sel[1] > nS_) or (sel[0] == "node" and sel[1] > nS_ + 1):
        sel = ("span", 1)
    fig, targets = input_figure(rows, nodes, extra, wu_u, fu, sel, bool(ss.cb_allsimple))
    ev = st.plotly_chart(fig, on_select="rerun", selection_mode="points", key=f"cb_canvas_{ss.cb_ver}",
                         config={"displayModeBar": False}, width="stretch")
    pts = (ev or {}).get("selection", {}).get("points", []) if isinstance(ev, dict) else ev.selection.points
    if pts:
        p = pts[0]
        cn = p.get("curve_number")
        tgt = targets[cn] if cn is not None and cn < len(targets) else None
        tok = (ss.cb_ver, cn, p.get("point_index"))
        if tgt and tok != ss.get("_cb_click"):
            ss._cb_click = tok
            ss.cb_sel = tgt
            st.rerun()
    opts = [("span", i) for i in range(1, nS_ + 1)] + [("node", j) for j in range(1, nS_ + 2)]
    pick = st.selectbox("แก้ไข (คลิกบนรูป หรือเลือกที่นี่)", opts, index=opts.index(sel),
                        format_func=lambda t: f"ช่วงที่ {t[1]}" if t[0] == "span" else f"จุดรองรับที่ {t[1]}")
    if pick != sel:
        ss.cb_sel = pick
        st.rerun()

    if sel[0] == "span":
        i = sel[1]
        r = rows[i - 1]
        mine = [(it, res) for it, res in zip(items, results) if it["span"] == i]
        with st.form(f"cb_span_form_{ss.cb_ver}_{i}", border=True):
            st.markdown(f"**ช่วงที่ {i}** — ขนาดคาน และรายการน้ำหนักใต้คานช่วงนี้")
            c = st.columns(4)
            name = c[0].text_input("ชื่อคาน", r["name"])
            L = c[1].number_input("L (m)", 0.1, 50.0, float(r["L"]), step=0.1)
            b = c[2].number_input("b (cm)", 10.0, 300.0, float(r["b"]), step=5.0)
            h = c[3].number_input("h (cm)", 10.0, 300.0, float(r["h"]), step=5.0)
            ed = st.data_editor(items_df([it for it, _ in mine]).drop(columns=["ช่วงที่"]), num_rows="dynamic",
                                hide_index=True, width="stretch", key=f"cb_span_ex_{ss.cb_ver}_{i}",
                                column_config={k: v for k, v in ITEM_COLCFG.items() if k != "ช่วงที่"})
            st.caption("เพิ่มแถวได้ไม่จำกัด (แถวว่างด้านล่างตาราง) — พื้นหลายแผ่น/สองข้างคาน ผนังหลายรายการ "
                       "แรงจุดหลายตัว ฯลฯ • ทุกช่องพิมพ์สูตรได้ เช่น 2400*0.12+150 • "
                       f"พื้น/ผนัง: kg/m² • แผ่: {wu_u} • จุด: {fu} • น้ำหนักคานคิดให้อัตโนมัติ")
            if st.form_submit_button("💾 บันทึกช่วงนี้", type="primary"):
                ed = ed.copy()
                ed.insert(0, "ช่วงที่", i)
                update_span(i, dict(name=name, L=L, b=b, h=h), df_items(ed))
                st.rerun()
        if mine:
            st.dataframe(items_results_df([m[0] for m in mine], [m[1] for m in mine]),
                         hide_index=True, width="stretch")
        tot = {k: r.get(k) for k in LOAD_FIELDS}
        st.caption(f"รวมน้ำหนักแผ่เต็มช่วง (ไม่รวมน้ำหนักคาน): DL {tot['DL'] or 0:.3f} • SDL {tot['SDL'] or 0:.3f} • "
                   f"LL {tot['LL'] or 0:.3f} • "
                   f"Wu {tot['WU'] or 0:.3f} {wu_u}")
    else:
        j = sel[1]
        n = nodes[j - 1]
        with st.form(f"cb_node_form_{ss.cb_ver}_{j}", border=True):
            st.markdown(f"**จุดรองรับที่ {j}**")
            c = st.columns([1.4, 1, 1, 1, 1, 1, 1, 1])
            kind = c[0].selectbox("ชนิด", SUPPORT_TYPES, index=SUPPORT_TYPES.index(n.kind))
            cc = c[1].number_input("c (cm)", 0.0, 300.0, float(n.c or 0.0), step=5.0, help="กว้างเสาตามแนวคาน")
            lb = c[2].number_input("เสาล่าง b", 0.0, 300.0, float(n.lower[0] or 0.0), step=5.0)
            lh = c[3].number_input("เสาล่าง h", 0.0, 300.0, float(n.lower[1] or 0.0), step=5.0)
            lH = c[4].number_input("เสาล่าง H (m)", 0.0, 20.0, float(n.lower[2] or 0.0), step=0.1)
            ub = c[5].number_input("เสาบน b", 0.0, 300.0, float(n.upper[0] or 0.0), step=5.0)
            uh = c[6].number_input("เสาบน h", 0.0, 300.0, float(n.upper[1] or 0.0), step=5.0)
            uH = c[7].number_input("เสาบน H (m)", 0.0, 20.0, float(n.upper[2] or 0.0), step=0.1)
            cont = st.radio("คานที่จุดนี้", [True, False], index=0 if n.continuous else 1, horizontal=True,
                            format_func=lambda v: "ต่อเนื่อง (คานต่อเนื่อง)" if v else
                            "ตัดโมเมนต์ (คานเดี่ยวต่อกัน)")
            st.caption("Pin อย่างเดียวยังคำนวณเป็นคานต่อเนื่อง — ถ้าต้องการคานเดี่ยวหลายตัวให้เลือก 'ตัดโมเมนต์' "
                       "(หรือติ๊ก 'คานเดี่ยวทุกช่วง' ด้านบน) • Pin = หมุนได้ • Fixed = ยึดแน่น • "
                       "Free = ปลายอิสระ (คานยื่น) • Column = คิด stiffness เสาบน-ล่าง 4EI/H (ไม่ใส่ขนาดเสา = Pin)")
            if st.form_submit_button("💾 บันทึกจุดรองรับ", type="primary"):
                update_node(j, nS_ + 1, dict(kind=kind, c=cc, lb=lb, lh=lh, lH=lH, ub=ub, uh=uh, uH=uH, cont=cont))
                st.rerun()


tabs = st.tabs(["📥 INPUT", "📊 ANALYSIS", "🔩 DESIGN", "🧾 DESIGN SHEET", "📄 OUTPUT", "❓ HELP"])

with tabs[0]:
    draw_area = st.container()        # filled after the tables below are read
    with st.expander("📋 ข้อมูลละเอียดแบบตาราง (แบบ Excel) — ช่วงคาน จุดรองรับ และรายการน้ำหนักทุกช่วง",
                     expanded=False):
        st.markdown("#### ช่วงคาน (ซ้าย → ขวา) และ จุดรองรับ")
        c1, c2 = st.columns([2, 5])
        with c1:
            st.caption("ช่วงคาน — เพิ่ม/ลบแถวได้ (1–10 ช่วง)")
            sp_ed = table_editor(
                "spans", ss.cb_spans, f"cb_spans_ed_{ver}", num_rows="dynamic", hide_index=True, width="stretch",
                column_config={
                    "ชื่อคาน": st.column_config.TextColumn(default="B1"),
                    "L (m)": st.column_config.NumberColumn(help="ศก.เสา – ศก.เสา", min_value=0.1, format="%.2f"),
                    "b (cm)": st.column_config.NumberColumn(min_value=10.0, format="%.0f"),
                    "h (cm)": st.column_config.NumberColumn(min_value=10.0, format="%.0f"),
                })
        sp_ed = sp_ed.dropna(subset=["L (m)", "b (cm)", "h (cm)"]).head(MAXS)
        spans = [Span(float(r["L (m)"]), float(r["b (cm)"]), float(r["h (cm)"]), str(r["ชื่อคาน"] or "B1"))
                 for _, r in sp_ed.iterrows()]
        nS = len(spans)
        with c2:
            st.caption(f"จุดรองรับ — ต้องมี {nS + 1} จุด (จุดที่ 1 ถึง {nS + 1})")
            def nd_base():
                base = ss.get("cb_nodes_saved", ss.cb_nodes).reset_index(drop=True)
                if len(base) < nS + 1:
                    base = pd.concat([base, nodes_df([Node("Pin")] * (nS + 1 - len(base)))], ignore_index=True)
                base = base.head(nS + 1).copy()
                base.index = [f"จุด {i + 1}" for i in range(len(base))]
                return base
            nd_ed = table_editor(
                "nodes", nd_base, f"cb_nodes_ed_{ver}_{nS}", width="stretch",
                column_config={
                    "ชนิด": st.column_config.SelectboxColumn(options=SUPPORT_TYPES, required=True),
                    "c (cm)": st.column_config.NumberColumn(help="ความกว้างเสาตามแนวคาน", format="%.0f"),
                    "ต่อเนื่อง": st.column_config.CheckboxColumn(help="ไม่ติ๊ก = ตัดโมเมนต์ที่จุดนี้ (คานเดี่ยวต่อกัน)"),
                })
        nn = lambda v: 0.0 if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
        nodes = [Node(str(r["ชนิด"] or "Pin"), nn(r["c (cm)"]),
                      (nn(r["เสาล่าง b"]), nn(r["เสาล่าง h"]), nn(r["เสาล่าง H (m)"])),
                      (nn(r["เสาบน b"]), nn(r["เสาบน h"]), nn(r["เสาบน H (m)"])),
                      bool(r["ต่อเนื่อง"]) if r["ต่อเนื่อง"] is not None else True)
                 for _, r in nd_ed.iterrows()]
        st.caption("Pin = รองรับแนวดิ่ง หมุนได้ • Fixed = ยึดแน่น • Free = ปลายอิสระ (คานยื่น) • "
                   "Column = ต่อกับเสา คิด stiffness เสาบน-ล่าง (4EI/H) • c = กว้างเสา ใช้หาโมเมนต์ลบที่ผิวเสา "
                   "และแรงเฉือนที่ระยะ d")

        if spans and len(nodes) == nS + 1:
            rows_ = []
            for i, s_ in enumerate(spans, 1):
                md = min_depth(sett, nodes, i, nS, s_)
                rows_.append({"ช่วง": i, "ประเภท": md["kind"],
                              "นน.คาน (t/m)": round(sett.gc * s_.b / 100 * s_.h / 100, 3) if sett.self_weight else None,
                              "hmin (cm)": round(md["hmin"], 1), "h ≥ hmin": "OK" if md["ok"] else "ตรวจการแอ่นตัว",
                              "b/h": round(s_.b / s_.h, 2)})
            st.dataframe(pd.DataFrame(rows_), hide_index=True, width="stretch")

        st.markdown(f"#### รายการน้ำหนักใต้คาน (ทุกช่วง) — พื้น/ผนัง kg/m², แผ่ {wu_u}, จุด {fu}")
        it_ed = table_editor("items", ss.cb_items, f"cb_items_ed_{ver}", num_rows="dynamic", hide_index=True,
                             width="stretch", column_config=ITEM_COLCFG)
        items = df_items(it_ed)
        loads, results, load_errors = items_to_loads(items, spans, U, sett.gc)
        if items:
            st.dataframe(items_results_df(items, results), hide_index=True, width="stretch")
        st.caption("ทุกช่องพิมพ์สูตรได้ (+ − * / ^ วงเล็บ) • DL, SDL, LL = น้ำหนักใช้งาน (โปรแกรมคูณตัวคูณและคิด Pattern LL; "
                   "SDL = วัสดุปูผิว/ฝ้า/งานระบบ/ผนัง แยกจาก DL) "
                   "• Wu = น้ำหนักประลัยที่คูณแล้ว (บวกเข้าตรง ๆ ไม่คิด pattern) • น้ำหนักคานคิดให้อัตโนมัติ")

    with draw_area:
        for e in load_errors:
            st.warning(e, icon="⚠️")
        draw_input(spans, nodes, items, results, loads)

# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


@st.cache_data(show_spinner="กำลังวิเคราะห์โครงสร้าง ...")
def analyse(sett: Settings, spans: tuple, nodes: tuple, loads: tuple):
    m = BeamModel(sett, list(spans), list(nodes), list(loads))
    return m.summary(), m.stations(), m.reactions(), m.X0, m


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Drop floating-point noise (e.g. -1e-15) so it does not show as -0.00."""
    return df.map(lambda v: 0.0 if isinstance(v, float) and abs(v) < 1e-9 else v)


err = None
try:
    if not spans:
        raise InputError("กรุณาใส่ช่วงคานอย่างน้อย 1 ช่วง")
    summary, stations, reactions, X0, model = analyse(sett, tuple(spans), tuple(nodes), tuple(loads))
except InputError as exc:
    err = str(exc)

if err:
    for t in tabs[1:5]:
        with t:
            st.error(f"ERROR: {err}")
    st.stop()

# --------------------------------------------------------------------------
# Overrides (yellow cells) + design
# --------------------------------------------------------------------------
def ov_df(nS):
    rows = []
    for s in range(1, nS + 1):
        for p in POSITIONS:
            o = ss.cb_ov.get((s, p), Override())
            rows.append({"ช่วง": s, "ตำแหน่ง": p, "Ø บน": o.db_top, "Ø ล่าง": o.db_bot,
                         "ชั้นบน": o.layers_top, "ชั้นล่าง": o.layers_bot,
                         "เส้นบน": o.n_top, "เส้นล่าง": o.n_bot, "Ø ปลอก": o.stir, "s (cm)": o.s})
    return pd.DataFrame(rows)


with tabs[2]:
    with st.expander("✏️ ช่องสีเหลือง — แก้ Ø เหล็ก / จำนวนชั้น / จำนวนเส้น / เหล็กปลอก (ว่าง = ค่าแนะนำ)",
                     expanded=False):
        ov_ed = table_editor(
            "ov", lambda: ov_df(nS), f"cb_ov_ed_{ver}_{nS}", hide_index=True, width="stretch",
            disabled=["ช่วง", "ตำแหน่ง"],
            column_config={
                "Ø บน": st.column_config.SelectboxColumn(options=BAR_SIZES),
                "Ø ล่าง": st.column_config.SelectboxColumn(options=BAR_SIZES),
                "ชั้นบน": st.column_config.SelectboxColumn(options=[1, 2], required=True),
                "ชั้นล่าง": st.column_config.SelectboxColumn(options=[1, 2], required=True),
                "เส้นบน": st.column_config.NumberColumn(min_value=2, max_value=20, step=1),
                "เส้นล่าง": st.column_config.NumberColumn(min_value=2, max_value=20, step=1),
                "Ø ปลอก": st.column_config.SelectboxColumn(options=STIRRUP_SIZES),
                "s (cm)": st.column_config.NumberColumn(min_value=5.0, max_value=60.0, step=2.5),
            })
    ovs = {}
    for _, r in ov_ed.iterrows():
        ovs[(int(r["ช่วง"]), r["ตำแหน่ง"])] = Override(
            opt(r["Ø บน"]), opt(r["Ø ล่าง"]), int(r["ชั้นบน"] or 1), int(r["ชั้นล่าง"] or 1),
            int(r["เส้นบน"]) if opt(r["เส้นบน"]) else None, int(r["เส้นล่าง"]) if opt(r["เส้นล่าง"]) else None,
            opt(r["Ø ปลอก"]), opt(r["s (cm)"]))
ss.cb_ov = {k: v for k, v in ovs.items() if v != Override()}

rows = design_all(sett, summary, ovs)
all_ok = all(r["ok"] for r in rows)

# --------------------------------------------------------------------------
# ANALYSIS tab
# --------------------------------------------------------------------------
def r2(v: float) -> float:
    """Round half away from zero to 2 decimals (12.665 -> 12.67, as in hand calculations)."""
    return math.copysign(math.floor(abs(v) * 100 + 0.5 + 1e-7) / 100, v)


def span_diagram(cmb: dict) -> go.Figure:
    """Loads + reactions, SFD and BMD with values, one load combination."""
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.36, 0.32, 0.32],
                        subplot_titles=("", f"V ({fu})", f"M ({mu})"))
    total = X0[-1]
    green, red, blue = "#188038", "#d93025", "#1a73e8"
    fig.add_shape(type="line", x0=0, x1=total, y0=0, y1=0, line=dict(color="#3c4043", width=5), row=1, col=1)
    wmax = max([abs(sp["udl"]) for sp in cmb["spans"]] +
               [max(abs(o["w1"]), abs(o["w2"])) for sp in cmb["spans"] for o in sp["others"] if o["kind"] == "dist"]
               + [1e-9])
    for sp in cmb["spans"]:
        x0, x1 = sp["X0"], sp["X0"] + sp["L"]
        fig.add_annotation(x=(x0 + x1) / 2, y=-0.28, text=f"{sp['L']:.2f} m", showarrow=False, row=1, col=1)
        if abs(sp["udl"]) > 1e-9:
            hgt = 0.25 + 0.35 * abs(sp["udl"]) / wmax
            fig.add_shape(type="rect", x0=x0, x1=x1, y0=0.08, y1=hgt, line=dict(color=green, width=2),
                          fillcolor="rgba(24,128,56,0.07)", row=1, col=1)
            for xa in [x0 + (x1 - x0) * k / 6 for k in range(7)]:
                fig.add_annotation(x=xa, y=0.08, ax=xa, ay=hgt, xref="x", yref="y", axref="x", ayref="y",
                                   showarrow=True, arrowhead=2, arrowcolor=green, arrowwidth=1.5, text="")
            fig.add_annotation(x=(x0 + x1) / 2, y=hgt + 0.1, showarrow=False, font=dict(color=green, size=13),
                               text=f"W = {r2(sp['udl'] * U):.2f} {wu_u}", row=1, col=1)
        for o in sp["others"]:
            if o["kind"] == "point":
                xp = x0 + o["a"]
                fig.add_annotation(x=xp, y=0.08, ax=xp, ay=0.88, xref="x", yref="y", axref="x", ayref="y",
                                   showarrow=True, arrowhead=2, arrowcolor="#e37400", arrowwidth=2.5, text="")
                fig.add_annotation(x=xp, y=0.98, text=f"P = {r2(o['w1'] * U):.2f} {fu}", showarrow=False,
                                   font=dict(color="#e37400", size=12), row=1, col=1)
            else:
                xa, xb = x0 + o["a"], x0 + o["b"]
                ya = 0.08 + 0.4 * abs(o["w1"]) / wmax
                yb = 0.08 + 0.4 * abs(o["w2"]) / wmax
                fig.add_scatter(x=[xa, xa, xb, xb, xa], y=[0.08, ya, yb, 0.08, 0.08], mode="lines", fill="toself",
                                line=dict(color="#e37400", width=1.5), fillcolor="rgba(227,116,0,0.08)",
                                hoverinfo="skip", showlegend=False, row=1, col=1)
                fig.add_annotation(x=(xa + xb) / 2, y=max(ya, yb) + 0.08, showarrow=False,
                                   font=dict(color="#e37400", size=11),
                                   text=f"{o['w1'] * U:.2f}→{o['w2'] * U:.2f} {wu_u}", row=1, col=1)
    for r in cmb["reactions"]:
        sym = {"PIN": "triangle-up", "COLUMN": "triangle-up", "FIXED": "square", "FREE": None}[r["kind"]]
        if sym:
            fig.add_scatter(x=[r["X"]], y=[-0.07], mode="markers", showlegend=False, hoverinfo="skip",
                            marker=dict(symbol=sym, size=16, color="#f9ab00", line=dict(color="#3c4043", width=1)),
                            row=1, col=1)
            fig.add_annotation(x=r["X"], y=-0.42, ax=r["X"], ay=-0.82, xref="x", yref="y", axref="x", ayref="y",
                               showarrow=True, arrowhead=2, arrowcolor=red, arrowwidth=2, text="")
            fig.add_annotation(x=r["X"], y=-0.95, text=f"Ry = {r2(r['R'] * U):.2f} {fu}", showarrow=False,
                               font=dict(color="#3c4043", size=12), row=1, col=1)
    fig.update_yaxes(range=[-1.1, 1.1], visible=False, row=1, col=1)

    for sp in cmb["spans"]:
        X = [sp["X0"] + x for x in sp["x"]]
        V = [v * U for v in sp["V"]]
        M = [m_ * U for m_ in sp["M"]]
        fig.add_scatter(x=X, y=[max(v, 0) for v in V], mode="lines", line=dict(color=red, width=2), fill="tozeroy",
                        fillcolor="rgba(217,48,37,0.10)", showlegend=False, hovertemplate="%{y:.2f}", row=2, col=1)
        fig.add_scatter(x=X, y=[min(v, 0) for v in V], mode="lines", line=dict(color=blue, width=2), fill="tozeroy",
                        fillcolor="rgba(26,115,232,0.10)", showlegend=False, hovertemplate="%{y:.2f}", row=2, col=1)
        for xv, vv, side in ((X[0], V[0], "right"), (X[-1], V[-1], "left")):
            if abs(vv) < 0.005:              # free end of a cantilever
                continue
            pos = ("top " if vv >= 0 else "bottom ") + side
            fig.add_scatter(x=[xv], y=[vv], mode="markers+text", text=[f"{r2(vv):.2f}"], textposition=pos,
                            marker=dict(size=9, color="rgba(0,0,0,0)", line=dict(color=red, width=1.5)),
                            showlegend=False, hoverinfo="skip", row=2, col=1)
        fig.add_scatter(x=X, y=M, mode="lines", line=dict(color=red, width=2.5), fill="tozeroy",
                        fillcolor="rgba(217,48,37,0.08)", showlegend=False, hovertemplate="%{y:.2f}", row=3, col=1)
        marks = []
        if sp["Mmax"] > 1e-6:
            marks.append((sp["X0"] + sp["x_Mmax"], sp["Mmax"] * U, "top center"))
        for xv, mv, side in ((X[0], M[0], "right"), (X[-1], M[-1], "left")):
            if abs(mv) >= 0.005:             # labels kept on their own span's side of the support
                marks.append((xv, mv, ("bottom " if mv < 0 else "top ") + side))
        if marks:
            fig.add_scatter(x=[m_[0] for m_ in marks], y=[m_[1] for m_ in marks], mode="markers+text",
                            text=[f"{r2(m_[1]):.2f}" for m_ in marks], textposition=[m_[2] for m_ in marks],
                            marker=dict(size=9, color="rgba(0,0,0,0)", line=dict(color=red, width=1.5)),
                            showlegend=False, hoverinfo="skip", row=3, col=1)
    for rr, key in ((2, "V"), (3, "M")):
        fig.add_hline(y=0, line=dict(color="#3c4043", width=1), row=rr, col=1)
        vals = [v * U for sp in cmb["spans"] for v in sp[key]] + [0.0]
        lo, hi = min(vals), max(vals)
        pad = 0.22 * (hi - lo or 1.0)          # room for the value labels
        fig.update_yaxes(range=[lo - pad, hi + pad], row=rr, col=1)
    for x in X0:
        fig.add_vline(x=x, line=dict(color="#e8eaed", width=1))
    fig.update_xaxes(title_text="X (m)", row=3, col=1)
    fig.update_layout(height=820, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="white", hovermode="x")
    return fig


with tabs[1]:
    st.markdown("##### แผนภาพรายช่วง — น้ำหนัก แรงปฏิกิริยา แรงเฉือน และโมเมนต์")
    has_wu = any(ld.case == "U" for ld in loads)
    has_sdl = any(ld.case == "SDL" for ld in loads)
    sdl_txt = f" + {sett.fSD:g}SDL" if has_sdl else ""
    cases = {f"Factored: {sett.fD:g}DL{sdl_txt} + {sett.fL:g}LL" + (" + Wu" if has_wu else ""):
             dict(a=sett.fD, sd=sett.fSD, b=sett.fL, u=1.0),
             "Service: DL" + (" + SDL" if has_sdl else "") + " + LL": dict(a=1.0, sd=1.0, b=1.0, u=0.0),
             "DL": dict(a=1.0, sd=0.0, b=0.0, u=0.0)}
    if has_sdl:
        cases["SDL"] = dict(a=0.0, sd=1.0, b=0.0, u=0.0)
    cases["LL"] = dict(a=0.0, sd=0.0, b=1.0, u=0.0)
    if has_wu:
        cases["Wu (ประลัยที่กรอก)"] = dict(a=0.0, sd=0.0, b=0.0, u=1.0)
    case = st.radio("กรณีน้ำหนัก (LL เต็มทุกช่วง)", list(cases), horizontal=True, key="cb_diag_case")
    cmb = combination(model, **(cases[case] if case in cases else next(iter(cases.values()))))
    st.plotly_chart(span_diagram(cmb), width="stretch")
    st.dataframe(clean(pd.DataFrame([{
        "ช่วง": sp["span"], "L (m)": sp["L"], f"W ({wu_u})": r2(sp["udl"] * U) if sp["udl"] else None,
        f"V ซ้าย ({fu})": r2(sp["V_left"] * U), f"V ขวา ({fu})": r2(sp["V_right"] * U),
        f"M ซ้าย ({mu})": r2(sp["M_left"] * U), f"M+ max ({mu})": r2(sp["Mmax"] * U), "ที่ x (m)": sp["x_Mmax"],
        f"M ขวา ({mu})": r2(sp["M_right"] * U),
    } for sp in cmb["spans"]])).style.format(precision=2, na_rep="-"), hide_index=True, width="stretch")
    st.markdown("**แรงปฏิกิริยา:** " + " • ".join(f"Ry{r['node']} = {r2(r['R'] * U):.2f} {fu}"
                                                 for r in cmb["reactions"] if r["kind"] != "FREE"))
    if has_wu and not case.startswith(("Factored", "Wu")):
        st.caption("กรณีนี้ไม่รวมน้ำหนัก Wu ที่กรอกแบบประลัย (แยก DL/SDL/LL ไม่ได้)")
    st.caption("W = น้ำหนักแผ่เต็มช่วงรวม (รวมน้ำหนักคานเมื่อเลือก) คูณตัวคูณของกรณีที่เลือก • แผนภาพนี้วาง LL ทุกช่วงพร้อมกัน "
               "— ค่าออกแบบใช้ envelope (Pattern LL) ด้านล่าง • M บวก = ท้องคานรับแรงดึง")
    st.divider()
    st.markdown(f"##### Envelope สำหรับออกแบบ ({mu}, {fu})")
    st.caption(f"Factored envelope = max/min ของ {sett.fD:g}DL{sdl_txt} + {sett.fL:g}LL "
               f"{'(pattern ทีละช่วง)' if sett.pattern else '(LL เต็มทุกช่วง)'} และ 1.4(DL{' + SDL' if has_sdl else ''}) • "
               "M บวก = ท้องคานรับแรงดึง • M ที่ผิวเสา (x = c/2) • Vu ที่ระยะ d จากผิวเสา")
    sdf = pd.DataFrame([{
        "ช่วง": s["span"], "L (m)": s["L"], "b×h (cm)": f"{s['b']:g}×{s['h']:g}", "ประเภท": s["type"],
        "M ซ้าย max": s["ML_max"], "M ซ้าย min": s["ML_min"], "M+ max": s["Mpos_max"], "x (m)": s["Mpos_x"],
        "M min กลาง": s["Mmid_min"], "M ขวา max": s["MR_max"], "M ขวา min": s["MR_min"],
        "Vu ซ้าย": s["Vu_left"], "Vu กลาง": s["Vu_mid"], "Vu ขวา": s["Vu_right"], "d (cm)": s["d"],
    } for s in summary])
    force_cols = [c for c in sdf.columns if c.startswith(("M ", "M+", "Vu"))]
    sdf[force_cols] = sdf[force_cols] * U
    st.dataframe(clean(sdf).style.format(precision=2), hide_index=True, width="stretch")

    stdf = pd.DataFrame(stations)
    stdf[["Mmax", "Mmin", "Vmax", "Vmin"]] = stdf[["Mmax", "Mmin", "Vmax", "Vmin"]] * U
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.09,
                        subplot_titles=(f"Bending Moment Diagram (Mu envelope, {mu})",
                                        f"Shear Force Diagram (Vu envelope, {fu})"))
    for s in range(1, nS + 1):
        seg = stdf[stdf.span == s]
        first = s == 1
        fig.add_scatter(x=seg.X, y=seg.Mmax, line=dict(color="#1a73e8"), name="max", legendgroup="max",
                        showlegend=first, row=1, col=1)
        fig.add_scatter(x=seg.X, y=seg.Mmin, line=dict(color="#c5221f"), name="min", legendgroup="min",
                        showlegend=first, row=1, col=1)
        fig.add_scatter(x=seg.X, y=seg.Vmax, line=dict(color="#1a73e8"), showlegend=False, legendgroup="max",
                        row=2, col=1)
        fig.add_scatter(x=seg.X, y=seg.Vmin, line=dict(color="#c5221f"), showlegend=False, legendgroup="min",
                        row=2, col=1)
    for x in X0:
        fig.add_vline(x=x, line=dict(color="#dadce0", width=1))
    fig.add_scatter(x=[r["X"] for r in reactions], y=[0] * len(reactions), mode="markers+text",
                    marker=dict(symbol="triangle-up", size=13, color="#5f6368"),
                    text=[r["kind"][0] for r in reactions], textposition="bottom center",
                    showlegend=False, row=2, col=1)
    fig.update_xaxes(title_text="X (m)", row=2, col=1)
    fig.update_layout(height=640, margin=dict(l=10, r=10, t=40, b=10), hovermode="x unified",
                      legend=dict(orientation="h", y=1.07))
    st.plotly_chart(fig, width="stretch")

    st.markdown("##### แรงปฏิกิริยาที่จุดรองรับ")
    st.dataframe(clean(pd.DataFrame([{
        "จุด": r["node"], "X (m)": r["X"], "ชนิด": r["kind"], f"R จาก DL ({fu})": r["RD"] * U,
        **({f"R จาก SDL ({fu})": r["RSD"] * U} if has_sdl else {}),
        f"R จาก LL ({fu})": r["RL"] * U, f"Ru max ({fu})": r["Ru_max"] * U, f"Ru min ({fu})": r["Ru_min"] * U,
        f"Mu เข้าเสา max ({mu})": r["Mu_max"] * U, f"Mu เข้าเสา min ({mu})": r["Mu_min"] * U}
        for r in reactions])).style.format(precision=2),
        hide_index=True, width="stretch")
    st.download_button("⬇️ ค่าตามตำแหน่ง (CSV)", stdf.to_csv(index=False).encode("utf-8-sig"),
                       file_name="analysis_stations.csv", mime="text/csv")

# --------------------------------------------------------------------------
# DESIGN tab
# --------------------------------------------------------------------------


def okc(v):
    return "color:#137333;font-weight:600" if v in ("OK", "ผ่าน", "Singly") else (
        "color:#b06000;font-weight:600" if v == "Doubly" else (
            "color:#c5221f;font-weight:600" if v in ("NG", "ไม่ผ่าน") or str(v).startswith(("วาง", "ขยาย", "เพิ่ม"))
            else ""))


def num(v, nd=2):
    return None if v is None else round(v, nd)


with tabs[2]:
    badge = ('<span class="ok-badge">✅ ผ่านทุกตำแหน่ง</span>' if all_ok
             else '<span class="ng-badge">❌ มีตำแหน่งไม่ผ่าน</span>')
    st.markdown(f"##### การออกแบบเหล็กเสริม — Singly / Doubly (อัตโนมัติ) &nbsp; {badge}", unsafe_allow_html=True)
    fl = []
    for r in rows:
        f = r["flex"]
        fl.append({
            "ช่วง": r["span"], "ตำแหน่ง": r["pos"], "b×h": f"{f['b']:g}×{f['h']:g}",
            "Mu− (t-m)": num(f["Mneg"]), "Mu+ (t-m)": num(f["Mpos"]),
            "ชนิด (M−)": f["neg"]["type"], "ชนิด (M+)": f["pos_"]["type"],
            "d M− / M+ (cm)": f"{f['d_neg']:.1f} / {f['d_pos']:.1f}",
            "As บน ต้องการ": num(f["As_top_req"]), "As ล่าง ต้องการ": num(f["As_bot_req"]),
            "เหล็กบน": f["top_txt"] + (" (2 ชั้น)" if f["layers_top"] == 2 else ""),
            "เหล็กล่าง": f["bot_txt"] + (" (2 ชั้น)" if f["layers_bot"] == 2 else ""),
            "As ≥ ต้องการ": "OK" if f["as_ok"] else "NG",
            "การจัดเหล็ก": "OK" if f["fit_ok"] else "วางไม่พอ: เพิ่มชั้น/Ø/b",
            "φMn− (t-m)": num(f["cap_neg"]["phiMn"]), "φMn+ (t-m)": num(f["cap_pos"]["phiMn"]),
            "ความเหนียว": "OK" if f["cap_neg"]["ductile"] and f["cap_pos"]["ductile"] else "NG",
            "φMn ≥ Mu": "OK" if f["strength_ok"] else "NG",
            "สรุป": "ผ่าน" if f["flex_ok"] else "ไม่ผ่าน",
        })
    fl_df = pd.DataFrame(fl)
    st.dataframe(fl_df.style.format(precision=2).map(okc), hide_index=True, width="stretch")
    st.caption(f"ρmax = {sett.rhomax:.5f} ({'0.75ρb' if sett.is99 else 'εt = 0.005'}) • ρmin = {sett.rhomin:.5f} • "
               f"β1 = {sett.beta1:.3f} • φ ดัด = {sett.phib} • ถ้า Mu > φMn1(ρmax) → Doubly")

    st.markdown("##### การออกแบบเหล็กปลอก (Shear)")
    sh = []
    for r in rows:
        s = r["shear"]
        sh.append({
            "ช่วง": r["span"], "โซน": r["pos"], "d (cm)": num(s["d"], 1), "Vu (t)": num(s["Vu"]),
            "φVc (t)": num(s["phiVc"]), "φVs ต้องการ": num(s["phiVs_req"]), "φVs max": num(s["phiVs_max"]),
            "ตรวจหน้าตัด": "OK" if s["section_ok"] else "ขยายหน้าตัด",
            "s กำลัง (cm)": num(s["s_str"], 1) if s["s_str"] is not None else "-",
            "s max (cm)": num(s["s_max"], 1), "s Av,min (cm)": num(s["s_avmin"], 1),
            "s ควบคุม": num(s["s_ctrl"], 1), "s ที่ใช้": s["s_use"], "ตรวจ": "OK" if s["ok"] else "NG",
            "เหล็กปลอก": s["label"], "หมายเหตุ": s["note"],
        })
    sh_df = pd.DataFrame(sh).astype({"s กำลัง (cm)": str})
    st.dataframe(sh_df.style.format(precision=2).map(okc), hide_index=True, width="stretch")
    st.caption(f"φVc = φ0.53√fc'·b·d (φ = {sett.phiv}) • s = φAv·fys·d/φVs • s ≤ d/2 (60 cm) หรือ d/4 (30 cm) "
               "เมื่อ φVs > φ1.1√fc'bd • φVs ≤ φ2.1√fc'bd • Av,min: s ≤ Av·fys/(3.5b) • ปัดลงทีละ 2.5 cm")

# --------------------------------------------------------------------------
# DESIGN SHEET tab — "Beam-Singly" / "Beam-Doubly" calculation form per section
# --------------------------------------------------------------------------
SHEET_BARS = [12, 16, 20, 25, 28, 32]
SHEET_STIR = [6, 9, 12]


def sheet_forces() -> dict:
    """Mu (kg-m) and tension face per (span, position); Vu (kg) at the support faces and at 2H."""
    out = {}
    for sm in summary:
        s_, L = sm["span"], sm["L"]
        xl = 0.0 if model.kind[s_ - 1] == "FREE" else min(sm["c_left"] / 200, L / 2)
        xr = L if model.kind[s_] == "FREE" else max(L - sm["c_right"] / 200, L / 2)
        h2 = 2 * sm["h"] / 100
        vmax = lambda x: max(abs(v) for v in model.env_V(s_, x)) * 1000
        v_face = max(vmax(xl), vmax(xr))
        v_mid = max(vmax(min(xl + h2, L / 2)), vmax(max(xr - h2, L / 2)))
        for pos in POSITIONS:
            if pos == "กลาง":
                neg, posm = -sm["Mmid_min"], sm["Mpos_max"]
                top = posm <= 1e-6 and neg > 1e-6
            else:
                neg, posm = (-sm["ML_min"], sm["ML_max"]) if pos == "ซ้าย" else (-sm["MR_min"], sm["MR_max"])
                top = neg > 1e-6 or posm <= 1e-6
            Mu = max(neg if top else posm, 0.0) * 1000
            out[(s_, pos)] = dict(Mu=Mu, top=top, Vu=v_face, Vu_mid=v_mid, L=L, b=sm["b"], h=sm["h"])
    return out


def sheet_input(key, f, ov=None) -> SheetInput:
    base = SheetInput(fc=sett.fc, fy=sett.fy, fy_rb=sett.fys, Es=sett.Es, Mu=f["Mu"], Vu=f["Vu"],
                      Vu_mid=f["Vu_mid"], span=f["L"], B=f["b"], H=f["h"], cover=sett.cover,
                      db=float(sett.db), ds=float(sett.stir), legs=int(sett.legs), eq=bool(ss.cb_sh_eq),
                      rho_limit=float(ss.cb_sh_rlim) / 100, clear_min=float(ss.cb_sh_cmin))
    ov = ov if ov is not None else ss.cb_sheet_ov.get(key)
    if not ov:
        return sheet_suggest(base)
    for k_, v_ in ov.items():
        if k_ != "bars":
            setattr(base, k_, v_)
    if ov.get("bars") is None:                       # mode / Ø / legs only: suggest the bars for them
        return sheet_suggest(base)
    base.bars = [Bar(**b_) for b_ in ov["bars"]]
    return base


def bars_df(inp: SheetInput) -> pd.DataFrame:
    rows = [{"ด้าน": "ดึง" if b_.side == "t" else "อัด", "ชั้นที่": int(b_.layer), "จำนวน": int(b_.n),
             "Ø (mm)": int(b_.db)} for b_ in sorted(inp.bars, key=lambda b_: (b_.side != "t", b_.layer))]
    return pd.DataFrame(rows, columns=["ด้าน", "ชั้นที่", "จำนวน", "Ø (mm)"])


def df_bars(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, row in df.iterrows():
        try:
            n_, d_, k_ = int(row["จำนวน"]), float(row["Ø (mm)"]), int(row["ชั้นที่"])
        except (TypeError, ValueError):
            continue
        if n_ > 0 and d_ > 0 and k_ > 0:
            out.append(dict(side="c" if row["ด้าน"] == "อัด" else "t", layer=k_, n=n_, db=d_))
    return out


def sheet_head(key, f, page) -> dict:
    s_, pos = key
    pj = {k: ss[f"cb_pj_{k}"] for k in PROJECT_KEYS}
    face = "M− บนรับแรงดึง" if f["top"] else "M+ ล่างรับแรงดึง"
    return dict(project=pj["project"], location=pj["location"], date=pj["date"], job=pj["job"],
                member=f"{spans[s_ - 1].name} (ช่วงที่ {s_})", type=pj["type"] or "RC - BEAM",
                note=f"{pos} • {face}", calc=f"{pj['eng']} {pj['eng_lic']}".strip(),
                approve=f"{pj['chk']} {pj['chk_lic']}".strip(), page=page, logo=ss.get("cb_logo"))


with tabs[3]:
    forces = sheet_forces()
    keys = list(forces)
    st.markdown("##### แบบฟอร์มรายการคำนวณคาน — Singly / Doubly ในแผ่นเดียว (ตามฟอร์ม Beam-Singly / Beam-Doubly)")
    c1, c2, c3, c4, c5 = st.columns([0.8, 1, 0.9, 0.9, 2.2])
    sel_s = c1.number_input("ช่วงที่", 1, nS, 1, key="cb_sh_span")
    sel_p = c2.selectbox("ตำแหน่ง", POSITIONS, key="cb_sh_pos")
    c3.number_input("% เหล็กดึงไม่เกิน", 0.5, 4.0, step=0.1, format="%.1f", key="cb_sh_rlim",
                    help="As(ดึง)/(B·H) — ทุกหน้าตัด")
    c4.number_input("ช่องว่างเหล็กเมน ≥ (cm)", 2.0, 15.0, step=0.5, format="%.1f", key="cb_sh_cmin",
                    help="(B − 2·cover − Øปลอก·ขา − ΣnØ)/(n − 1) ของแต่ละชั้น — ใช้ตรวจและใช้แนะนำจำนวนเส้นต่อชั้น")
    c5.toggle("For EQ — ระยะปลอกในโซน 2H จากหน้าเสา ≤ min(d/4, 8db, 24Ø, 30 cm)", key="cb_sh_eq")
    key = (int(sel_s), sel_p)
    f = forces[key]
    inp_ = sheet_input(key, f)
    res = sheet_compute(inp_)
    ov_ = ss.cb_sheet_ov.get(key) or {}

    with st.form(f"cb_sheet_form_{key[0]}_{key[1]}_{ss.cb_ver}_{ss.cb_sh_rev}", border=True):
        st.caption(f"Mu = {f['Mu']:,.0f} kg-m ({'M− บนรับแรงดึง' if f['top'] else 'M+ ล่างรับแรงดึง'}) • "
                   f"Vu ที่หน้าเสา = {f['Vu']:,.0f} kg • Vu ที่ระยะ 2H = {f['Vu_mid']:,.0f} kg — จาก envelope ของผลวิเคราะห์ • "
                   f"{'เหล็กที่กรอกเอง' if ov_.get('bars') is not None else 'เหล็กที่โปรแกรมแนะนำ'}")
        cl, cr = st.columns([1.15, 1])
        with cl:
            m_keys = list(MODES)
            mode_ = st.radio("ออกแบบเป็น", m_keys, index=m_keys.index(inp_.mode if inp_.mode in MODES else "auto"),
                             format_func=lambda m: MODES[m] + (f" (ตอนนี้ {res['auto_kind']})" if m == "auto" else ""),
                             horizontal=True,
                             help="อัตโนมัติ: Singly เมื่อ ρ ต้องการ ≤ 0.75ρb (และเหล็กที่ใช้จริงตรวจผ่าน) ไม่งั้น Doubly • "
                                  "เลือก Singly/Doubly เองได้ — แบบไหนไม่ผ่านจะขึ้น NOT O.K. ในแผ่นคำนวณ")
            k1, k2, k3 = st.columns(3)
            db_ = k1.selectbox("Ø เหล็กเมน (ที่ใช้แนะนำ)", SHEET_BARS,
                               index=SHEET_BARS.index(int(inp_.db)) if int(inp_.db) in SHEET_BARS else 1)
            ds_ = k2.selectbox("Ø ปลอก", SHEET_STIR, index=SHEET_STIR.index(int(inp_.ds)) if int(inp_.ds) in SHEET_STIR else 1)
            legs_ = k3.number_input("ขาปลอก", 2, 8, int(inp_.legs), help="ปลอกหลายขา (2, 3, 4, … ขา) — Av = ขา × πØ²/4")
        with cr:
            st.caption("เหล็กเมน — 1 แถว = 1 กลุ่ม (ด้าน, ชั้นที่, จำนวน, Ø) • ชั้น 1 ชิดผิว • ชั้นเดียวกันใส่หลายขนาดได้ • "
                       "เพิ่ม/ลบแถวได้ไม่จำกัด")
            ed_ = st.data_editor(
                bars_df(inp_), key=f"cb_sh_ed_{key[0]}_{key[1]}_{ss.cb_ver}_{ss.cb_sh_rev}", num_rows="dynamic",
                hide_index=True, width="stretch",
                column_config={"ด้าน": st.column_config.SelectboxColumn(options=["ดึง", "อัด"], required=True, default="ดึง"),
                               "ชั้นที่": st.column_config.NumberColumn(min_value=1, max_value=10, step=1, default=1),
                               "จำนวน": st.column_config.NumberColumn(min_value=0, max_value=30, step=1, default=2),
                               "Ø (mm)": st.column_config.SelectboxColumn(options=SHEET_BARS, default=16)})
        b1_, b2_, b3_ = st.columns(3)
        save = b1_.form_submit_button("💾 ใช้เหล็กตามที่กรอก", type="primary")
        auto = b2_.form_submit_button("🪄 ให้โปรแกรมคำนวณเหล็กเบื้องต้น", help="ตามแบบ (Singly/Doubly), Ø เหล็กเมน, ปลอก, ขา ที่เลือก")
        reset = b3_.form_submit_button("↺ กลับเป็นค่าแนะนำเดิม")
    if save or auto:
        ov_new = dict(mode=mode_, db=float(db_), ds=float(ds_), legs=int(legs_))
        if save:
            ov_new["bars"] = df_bars(ed_)
        else:
            sug = sheet_suggest(sheet_input(key, f, ov=ov_new))
            ov_new.update(mode=sug.mode, ds=sug.ds, legs=sug.legs,
                          bars=[dict(side=b_.side, layer=b_.layer, n=b_.n, db=b_.db) for b_ in sug.bars])
        ss.cb_sheet_ov[key] = ov_new
        ss.cb_sh_rev += 1
        st.rerun()
    if reset:
        ss.cb_sheet_ov.pop(key, None)
        ss.cb_sh_rev += 1
        st.rerun()

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("แบบที่ใช้", res["kind"], None if res["kind"] == res["auto_kind"] else f"ตามเกณฑ์: {res['auto_kind']}",
              delta_color="off")
    m2.metric("% เหล็กรับแรงดึง", f"{100 * res['pct']:.2f} %", f"{'≤' if res['pct_ok'] else '>'} {ss.cb_sh_rlim:.1f} %",
              delta_color="normal" if res["pct_ok"] else "inverse")
    clr_ = [l_["clear"] for l_ in res["layers_t"] + res["layers_c"] if math.isfinite(l_["clear"])]
    m3.metric("ช่องว่างเหล็กเมนน้อยสุด", f"{min(clr_):.2f} cm" if clr_ else "-",
              f"{'≥' if res['clear_ok'] else '<'} {ss.cb_sh_cmin:.1f} cm", delta_color="normal" if res["clear_ok"] else "inverse")
    m4.metric("φMn / Mu", f"{res['phiMn']:,.0f}", f"Mu {inp_.Mu:,.0f} kg-m", delta_color="normal" if res["Mn_ok"] else "inverse")
    m5.metric("ผลรวม", "ผ่าน" if res["ok"] else "ไม่ผ่าน")
    with st.expander("ช่องว่างเหล็กเมนแต่ละชั้น", expanded=not res["clear_ok"]):
        st.dataframe(pd.DataFrame([{"ด้าน": "ดึง" if sd == "t" else "อัด", "ชั้น": l_["layer"], "เหล็ก": l_["txt"],
                                    "As (cm²)": round(l_["As"], 2), "ระยะถึงผิว y (cm)": round(l_["y"], 2),
                                    "ช่องว่าง (cm)": round(l_["clear"], 2) if math.isfinite(l_["clear"]) else None,
                                    "ตรวจ": ("ผ่าน" if l_["clear"] >= inp_.clear_min - 1e-9 else "ไม่ผ่าน")}
                                   for sd in ("t", "c") for l_ in res[f"layers_{sd}"]]),
                     hide_index=True, width="stretch")
        st.caption(f"ช่องว่าง = (B − 2·cover − Øปลอก/10·ขา − ΣnØ/10)/(n − 1) = ({inp_.B:g} − 2×{inp_.cover:g} − "
                   f"{inp_.ds / 10:g}×{inp_.legs} − ΣnØ)/(n − 1)")

    k_idx = keys.index(key) + 1
    page_html = render_document([render_sheet(res, sheet_head(key, f, f"{k_idx}/{len(keys)}"))],
                                f"{spans[key[0] - 1].name} {key[1]}")
    st.iframe(page_html, height=1180)

    # all sections
    all_rows, all_pages, xl_secs = [], [], []
    for n_, k_ in enumerate(keys, 1):
        r_ = sheet_compute(sheet_input(k_, forces[k_]))
        i_ = r_["inp"]
        all_pages.append(render_sheet(r_, sheet_head(k_, forces[k_], f"{n_}/{len(keys)}")))
        xl_secs.append((f"S{k_[0]}-{k_[1]}", i_, sheet_head(k_, forces[k_], f"{n_}/{len(keys)}")))
        clr_ = [l_["clear"] for l_ in r_["layers_t"] + r_["layers_c"] if math.isfinite(l_["clear"])]
        all_rows.append({"ช่วง": k_[0], "ตำแหน่ง": k_[1], "Mu (kg-m)": round(forces[k_]["Mu"]),
                         "ดึง": "บน" if forces[k_]["top"] else "ล่าง", "ชนิด": r_["kind"],
                         "เหล็กรับแรงดึง": bars_text(r_["layers_t"]), "เหล็กรับแรงอัด": bars_text(r_["layers_c"]),
                         "% ดึง": round(100 * r_["pct"], 2), "ช่องว่างน้อยสุด (cm)": round(min(clr_), 2) if clr_ else None,
                         "φMn (kg-m)": round(r_["phiMn"]),
                         "ปลอก 2H": f"{i_.legs}ขา {bar_name(i_.ds)}@{r_['sh_2h']['s']:g}" if r_["sh_2h"]["s"] else "Revised",
                         "ปลอกกลาง": f"{i_.legs}ขา {bar_name(i_.ds)}@{r_['sh_mid']['s']:g}" if r_["sh_mid"]["s"] else "Revised",
                         "ผล": "ผ่าน" if r_["ok"] else "ไม่ผ่าน",
                         "ที่มา": "แก้เอง" if (ss.cb_sheet_ov.get(k_) or {}).get("bars") is not None else "แนะนำ"})
    st.markdown("###### สรุปทุกช่วง")
    st.dataframe(pd.DataFrame(all_rows).style.map(
        lambda v: "color:#137333;font-weight:600" if v == "ผ่าน" else (
            "color:#c5221f;font-weight:600" if v in ("ไม่ผ่าน", "Revised") else "")),
        hide_index=True, width="stretch")
    c1, c2, c3, c4, c5 = st.columns(5)
    member = ss.cb_pj_member or "beam"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    c1.download_button("⬇️ แผ่นนี้ (HTML, พิมพ์ A4)", page_html, file_name=f"{member}_S{key[0]}_{key[1]}.html",
                       mime="text/html")
    c2.download_button("⬇️ ทุกช่วงทุกตำแหน่ง (HTML, พิมพ์ A4)", render_document(all_pages, member),
                       file_name=f"{member}_design_sheets.html", mime="text/html", type="primary")
    c3.download_button("📗 แผ่นนี้ (Excel มีสูตร)", lambda: build_workbook([xl_secs[k_idx - 1]]),
                       file_name=f"{member}_S{key[0]}_{key[1]}.xlsx", mime=XLSX)
    c4.download_button("📗 ทุกช่วง (Excel มีสูตร)", lambda: build_workbook(xl_secs),
                       file_name=f"{member}_design_sheets.xlsx", mime=XLSX, type="primary")
    if ss.cb_sheet_ov and c5.button("↺ ล้างค่าที่แก้เองทั้งหมด"):
        ss.cb_sheet_ov = {}
        st.rerun()
    st.caption("หน่วยตามแบบฟอร์ม: kg, kg-m, cm, ksc • φ ดัด 0.90 (Singly: φ ตาม εt 0.70–0.90), φ เฉือน 0.85 • "
               "Singly เมื่อ ρ ≤ 0.75ρb, Doubly เมื่อ ρ > 0.75ρb (ρ1 = 0.5ρb, f′s จากเหล็กที่ใช้) • "
               "ระยะห่างระหว่างชั้นเหล็ก 3 cm • % เหล็กดึง = As/(B·H) • ไฟล์ Excel: ทุกค่าเป็นสูตร แก้ช่องสีฟ้าแล้วคำนวณใหม่ได้ • ปลอก RB ใช้ fy ของเหล็กปลอก (แถบซ้าย), DB ใช้ fy เหล็กหลัก • "
               "เปิดไฟล์ HTML แล้วสั่งพิมพ์ (Ctrl+P) เป็น PDF ได้")


# --------------------------------------------------------------------------
# OUTPUT tab (calculation sheet of one location)
# --------------------------------------------------------------------------
with tabs[4]:
    c1, c2, c3 = st.columns(3)
    sel_span = c1.number_input("ช่วงที่", 1, nS, 1, key="cb_sel_span")
    sel_pos = c2.selectbox("ตำแหน่ง", POSITIONS, key="cb_sel_pos")
    sel_neg = c3.selectbox("โมเมนต์", ["M− (บนดึง)", "M+ (ล่างดึง)"], key="cb_sel_sign").startswith("M−")
    r = next(x for x in rows if x["span"] == sel_span and x["pos"] == sel_pos)
    f, s = r["flex"], r["shear"]
    req = f["neg"] if sel_neg else f["pos_"]
    cap = f["cap_neg"] if sel_neg else f["cap_pos"]
    d = f["d_neg"] if sel_neg else f["d_pos"]
    dp = f["dp_bot"] if sel_neg else f["dp_top"]
    Mu = f["Mneg"] if sel_neg else f["Mpos"]
    As_t, As_c = (f["As_top"], f["As_bot"]) if sel_neg else (f["As_bot"], f["As_top"])
    sm = summary[sel_span - 1]
    md = min_depth(sett, nodes, sel_span, nS, spans[sel_span - 1])

    def table(d_):
        return pd.DataFrame([{k: ("-" if v is None else v) for k, v in d_.items()}]).astype(str)

    st.markdown(f"**Member:** {spans[sel_span - 1].name} (ช่วงที่ {sel_span}) • **Note:** {sel_pos} / "
                f"{'M− (บนดึง)' if sel_neg else 'M+ (ล่างดึง)'} • **Code:** {sett.code}")
    st.markdown("###### Design Parameter")
    st.dataframe(table({"fy (ksc)": sett.fy, "fc' (ksc)": sett.fc, "β1": round(sett.beta1, 3),
                        "φ bending": sett.phib, "φ shear": sett.phiv, "fy stirrup (ksc)": sett.fys,
                        "Es (ksc)": f"{sett.Es:,.0f}"}), hide_index=True, width="stretch")
    st.markdown("###### Input Data")
    st.dataframe(table({"Span (m)": sm["L"], "ประเภท": md["kind"], "b (cm)": f["b"], "h (cm)": f["h"],
                        "d (cm)": round(d, 2), "d' (cm)": round(dp, 2), "Mu (kg-m)": round(Mu * 1000, 0),
                        "Vu ที่ d (kg)": round(s["Vu"] * 1000, 0)}), hide_index=True, width="stretch")
    bh = f["b"] / f["h"]
    st.caption(f"b/h = {bh:.2f} ({'0.25–0.6 OK' if 0.25 <= bh <= 0.6 else 'นอกช่วง 0.25–0.6'}) • "
               f"h: {'OK' if md['ok'] else 'ตรวจการแอ่นตัว'} (hmin = {md['hmin']:.0f} cm)")
    st.markdown("###### Calculation (ตรวจ Singly)")
    As_max = sett.rhomax * f["b"] * d
    st.dataframe(table({"ρb": f"{sett.rhob:.5f}", "ρmax": f"{sett.rhomax:.5f}", "d (cm)": round(d, 2),
                        "As,max (cm²)": round(As_max, 2), "a (cm)": round(As_max * sett.fy / (0.85 * sett.fc * f["b"]), 2),
                        "φMn1 (kg-m)": round(req["phiMn1"] * 1000, 0),
                        "Check": "Single Ren." if Mu <= req["phiMn1"] else "Double Ren."}),
                 hide_index=True, width="stretch")
    st.markdown("###### Reinforcement")
    nT, dbT = (f["n_top"], f["db_top"]) if sel_neg else (f["n_bot"], f["db_bot"])
    nC, dbC = (f["n_bot"], f["db_bot"]) if sel_neg else (f["n_top"], f["db_top"])
    st.dataframe(table({
        "ρ": f"{req['rho']:.5f}" if req["rho"] is not None else None, "d' (cm)": round(dp, 2),
        "Rn (ksc)": num(req["Rn"]), "M2 (kg-m)": round(req["M2"] * 1000, 0),
        "fs' (ksc)": num(req["fsp"], 0), "As' req (cm²)": "เพิ่ม h" if req["need_h"] else round(req["Asp"], 2),
        "As req (cm²)": round(req["As"], 2),
        "ใช้ (ดึง)": f"{nT}-DB{dbT:g} = {As_t:.2f} cm² ({'Top' if sel_neg else 'Bottom'})",
        "ใช้ (อัด)": f"{nC}-DB{dbC:g} = {As_c:.2f} cm² ({'Bottom' if sel_neg else 'Top'})",
    }), hide_index=True, width="stretch")
    st.caption(f"As บน / ล่าง ต้องการ (รวมทุกกรณี): บน {f['As_top_req']:.2f} / ล่าง {f['As_bot_req']:.2f} cm²")
    st.markdown("###### Check yield compression / capacity")
    E = sett.es_cu
    rho_cy = 0.85 * sett.beta1 * sett.fc / sett.fy * dp / d * E / (E - sett.fy)
    st.dataframe(table({
        "ρ − ρ'": f"{(As_t - As_c) / (f['b'] * d):.5f}", "ρcy (As' คราก)": f"{rho_cy:.5f}",
        "As' yield ?": "Yield" if cap["yield_c"] else "check fs'", "c (cm)": round(cap["c"], 2),
        "fs' (ksc)": round(cap["fsp"], 0), "ρ−ρ'fs'/fy": f"{(As_t - As_c * cap['fsp'] / sett.fy) / (f['b'] * d):.5f}",
        "εt": f"{cap['eps_t']:.4f}", "Ductility": "OK" if cap["ductile"] else "NG", "φ": round(cap["phi"], 3),
        "φMn (kg-m)": round(cap["phiMn"] * 1000, 0), "Mu (kg-m)": round(Mu * 1000, 0),
        "Check": "OK" if cap["phiMn"] >= Mu - 1e-4 and cap["ductile"] else "NG",
    }), hide_index=True, width="stretch")
    st.caption(f"Ductility: ρ − ρ'·fs'/fy ≤ 0.75ρb = {sett.rhomax:.5f}" if sett.is99
               else "Ductility: εt ≥ 0.004 (ACI 318-19)")
    st.markdown(f"###### Shear — โซน: {sel_pos} | {s['note']}")
    st.dataframe(table({
        "Vu at d (kg)": round(s["Vu"] * 1000, 0), "φVc (kg)": round(s["phiVc"] * 1000, 0),
        "φVs req (kg)": round(s["phiVs_req"] * 1000, 0), "φVs max (kg)": round(s["phiVs_max"] * 1000, 0),
        "φ1.1√fc'bd (kg)": round(s["phiVs_tight"] * 1000, 0), "use": s["label"].split(" @")[0],
        "Av (cm²)": round(s["Av"], 3), "s strength (cm)": num(s["s_str"], 1), "s max (cm)": num(s["s_max"], 1),
        "s Av,min (cm)": num(s["s_avmin"], 1), "s use (cm)": s["s_use"],
    }), hide_index=True, width="stretch")
    st.caption(("φVs ≤ φ2.1√fc'bd OK" if s["section_ok"] else "ขยายหน้าตัด") + " • " +
               ("φVs > φ1.1√fc'bd → s ≤ d/4, 30 cm" if s["phiVs_req"] > s["phiVs_tight"]
                else "φVs ≤ φ1.1√fc'bd → s ≤ d/2, 60 cm"))
    st.info(f"**สรุปเหล็กเสริม** — เหล็กบน: {f['top_txt']} • เหล็กล่าง: {f['bot_txt']} • เหล็กปลอก: {s['label']}  \n"
            f"ผลตรวจ: ดัด {'ผ่าน' if f['flex_ok'] else 'ไม่ผ่าน'} | เฉือน {'OK' if s['ok'] else 'NG'}")

    st.markdown("###### ช่วงคานทั้งหมด (สรุป)")
    tot = []
    for i in range(1, nS + 1):
        L_, M_, R_ = [x for x in rows if x["span"] == i]
        tot.append({"ช่วง": i, "b×h": f"{L_['flex']['b']:g}×{L_['flex']['h']:g}",
                    "บน-ซ้าย": L_["flex"]["top_txt"], "ล่าง-กลาง": M_["flex"]["bot_txt"],
                    "บน-ขวา": R_["flex"]["top_txt"], "ปลอก ซ้าย": L_["shear"]["label"].replace(" ", ""),
                    "ปลอก กลาง": M_["shear"]["label"].replace(" ", ""),
                    "ปลอก ขวา": R_["shear"]["label"].replace(" ", ""),
                    "ผล": "ผ่าน" if all(x["ok"] for x in (L_, M_, R_)) else "ไม่ผ่าน"})
    st.dataframe(pd.DataFrame(tot).style.map(okc), hide_index=True, width="stretch")

    project = {k: ss[f"cb_pj_{k}"] for k in PROJECT_KEYS}
    html = build_report(sett, spans, nodes, summary, reactions, rows, project, list(zip(items, results)),
                        ss.cb_unit)
    st.download_button("⬇️ ดาวน์โหลดรายการคำนวณทุกช่วง (HTML, พิมพ์ A4)", html,
                       file_name=f"{project['member'] or 'beam'}_calc.html", mime="text/html", type="primary")
    with st.expander("ดูตัวอย่างรายการคำนวณ"):
        st.iframe(html, height=800)

# --------------------------------------------------------------------------
# HELP tab
# --------------------------------------------------------------------------
with tabs[5]:
    st.markdown("""
**ขั้นตอน**
1. แถบซ้าย: กรอกวัสดุ เลือกมาตรฐาน (ACI 318-99/วสท. 1.4D+1.7L หรือ ACI 318-19/มยผ. 1.2D+1.6L) และ
   Load combination (ตามมาตรฐาน / 1.4D+1.7L / 1.2D+1.6L / กำหนดเอง), Pattern LL,
   น้ำหนักคานอัตโนมัติ — หรือ **นำเข้าไฟล์ Excel เดิม** (.xlsm) ได้ทันที
2. แท็บ INPUT: เลือก **รูปแบบคาน** (คานเดี่ยว / ต่อเนื่อง / คานยื่น / ต่อเนื่อง + ยื่น / คานเดี่ยวต่อกัน)
   แล้วกด "สร้างรูปคานใหม่" — เพิ่ม/ลบช่วงได้ แล้ว **กรอกบนรูปคาน** ได้ 2 แบบ (สลับได้):
   - คลิกแล้วกรอกด้านล่าง: คลิกช่วงหรือจุดรองรับบนรูป แล้วกรอกขนาดคานและรายการน้ำหนักในกล่องใต้รูป
   - จุดรองรับ: คลิกที่จุดบนรูปเพื่อเปลี่ยน Pin / Fixed / Free / Column และเลือก "ต่อเนื่อง" หรือ "ตัดโมเมนต์"
     (Pin อย่างเดียวยังเป็นคานต่อเนื่อง — ต้องเลือกตัดโมเมนต์จึงเป็นคานเดี่ยวต่อกัน)
   - กรอกบนรูป (ป๊อปอัป): คลิกบนรูปแล้วกรอกในกล่องที่เด้งขึ้นบนรูปเลย
   ตารางแบบ Excel ยังเปิดได้ที่ "ข้อมูลละเอียดแบบตาราง" (แก้ข้อมูลชุดเดียวกัน)
   - คานเดี่ยว: 1 ช่วง จุด 1 = Pin, จุด 2 = Pin • คานยื่นอย่างเดียว: 1 ช่วง จุด 1 = Fixed (หรือ Column), จุด 2 = Free
   - คานต่อเนื่อง: ≥ 2 ช่วง • คานต่อเนื่อง + คานยื่น: ให้จุดปลายเป็น Free
   - คานเดี่ยวหลายตัวต่อกัน: ติ๊ก "คานเดี่ยวทุกช่วง" หรือเอาติ๊ก "ต่อเนื่อง" ออกเฉพาะจุดที่ต้องการตัด
     (ห้ามตัดที่จุดโคนคานยื่น มิฉะนั้นโครงสร้างไม่เสถียร)
   - Column: คิด stiffness เสาบน/ล่าง (4EI/H, ปลายไกลยึดแน่น) ถ้าไม่ใส่ขนาดเสา จะเท่ากับ Pin
3. น้ำหนักใต้คาน: คลิกช่วงคานแล้วเพิ่ม **รายการน้ำหนัก** ได้ไม่จำกัด (ทุกช่องพิมพ์สูตรได้ เช่น 2400*0.12+150)
   - **พื้น**: กรอกขนาดพื้น S × L, ความหนา, SDL, LL (kg/m²) → โปรแกรมคิดน้ำหนักพื้น (เป็น DL), เลือก One-way (L/S ≥ 2) /
     Two-way และด้านที่คานรองรับให้อัตโนมัติ (หรือเลือกเอง) แล้วใช้ wS/2, wS/3, wS/3·(3−m²)/2 • พื้นสองข้างคาน = 2 รายการ
   - **ผนัง / กว้างรับ** (kg/m² × สูง) • **น้ำหนักแผ่** (ต่อเมตร, ระบุ a–b ได้) • **สามเหลี่ยม/คางหมู** (w1;w2) • **แรงจุด** ที่ a
   - DL / SDL / LL = น้ำหนักใช้งาน (โปรแกรมคูณตัวคูณและคิด Pattern LL) • Wu = น้ำหนักประลัยที่คูณแล้วแบบ Excel
   - **DL** = น้ำหนักโครงสร้าง (คาน พื้น — คิดให้อัตโนมัติ) • **SDL** = น้ำหนักบรรทุกคงที่เพิ่มเติม (วัสดุปูผิว ฝ้า
     งานระบบ ผนัง) แยกกรณีไว้ แสดงแยกในแผนภาพ/แรงปฏิกิริยา • ตัวคูณ SDL = ตัวคูณ DL (ตั้งเองได้ที่แถบซ้าย)
   - น้ำหนักคานคิดให้อัตโนมัติ • เลือกหน่วยแรง ตัน หรือ kN ที่แถบซ้าย
   • แท็บ ANALYSIS มีแผนภาพรายช่วง (W, Ry, SFD, BMD พร้อมค่า) แบบรายการคำนวณมือ
4. **ไม่ต้องกด RUN** — วิเคราะห์ใหม่อัตโนมัติทุกครั้งที่แก้ข้อมูล
5. แท็บ DESIGN: ออกแบบทุกช่วง 3 ตำแหน่ง เลือก Singly/Doubly อัตโนมัติ — แก้ Ø เหล็ก/จำนวนชั้น/จำนวนเส้น/
   เหล็กปลอก ได้ใน "ช่องสีเหลือง"
6. แท็บ DESIGN SHEET: ออกแบบเหล็กจริงทีละหน้าตัดตามแบบฟอร์ม Beam-Singly / Beam-Doubly (Mu, Vu จากผลวิเคราะห์)
   — เลือก อัตโนมัติ/Singly/Doubly ได้ • กรอกเหล็กเมนเป็นตาราง (ด้าน, ชั้นที่, จำนวน, Ø) ได้ตามต้องการ หรือกด
   "ให้โปรแกรมคำนวณเหล็กเบื้องต้น" • เหล็กปลอกเลือก Ø และจำนวนขาได้ • ตรวจ % เหล็กดึง As/(B·H) ≤ 2 % และ
   ช่องว่างเหล็กเมน (B − 2·cover − Øปลอก·ขา − ΣnØ)/(n − 1) ≥ 6 cm • ดาวน์โหลดแบบฟอร์ม (HTML → พิมพ์ PDF)
   หรือ Excel ที่ทุกค่าเป็นสูตร
   • ใส่ชื่อผู้คำนวณ/ผู้ตรวจ และโลโก้บริษัทได้ที่ "ข้อมูลโครงการ" แถบซ้าย
7. แท็บ OUTPUT: รายการคำนวณรายตำแหน่ง และดาวน์โหลดรายการคำนวณทุกช่วงเป็น HTML (สั่งพิมพ์ A4)

**หลักการคำนวณ**
- วิเคราะห์ด้วย Direct Stiffness Method (2 DOF/จุด) — เท่ากับ Moment Distribution ของ SUTStructor แต่ไม่ต้องวนรอบ
- Pattern LL: วิเคราะห์ LL ทีละช่วง แล้วรวมเฉพาะส่วนที่เพิ่มค่าสูงสุด/ต่ำสุดในแต่ละจุด และตรวจ 1.4(DL + SDL) ด้วย
- โมเมนต์ลบออกแบบที่ผิวเสา (x = c/2), แรงเฉือนออกแบบที่ระยะ d จากผิวเสา, โซนกลาง = Vu สูงสุดในช่วง L/4–3L/4
- ดัด: ρmax = 0.75ρb (ACI 318-99) หรือที่ εt = 0.005 (ACI 318-19). ถ้า Mu > φMn(ρmax) → Doubly:
  As = ρmax·b·d + M2/(fy(d−d')), As' = M2/((fs'−0.85fc')(d−d')), fs' จาก strain compatibility
- ตรวจหน้าตัดจริง: หา c จากสมดุล (As' ครากและไม่คราก), φMn ≥ Mu และความเหนียว (ρ−ρ'fs'/fy ≤ ρmax หรือ εt ≥ 0.004)
- เฉือน: φVc = φ0.53√fc'·b·d, s = φAv·fys·d/(Vu−φVc), s ≤ d/2 (60 cm) หรือ d/4 (30 cm) เมื่อ φVs > φ1.1√fc'bd,
  ไม่เกิน φ2.1√fc'bd, Av,min: s ≤ Av·fys/(3.5b)
- d = h − ระยะหุ้ม − Ø ปลอก − Ø เหล็กหลัก/2 (1 ชั้น) หรือ − (Ø + 1.25 cm) (2 ชั้น) ; d' = ระยะหุ้ม + Ø ปลอก + Ø/2

**ข้อจำกัด:** ไม่คิดแรงลม/แผ่นดินไหว แรงบิด และหน้าตัดตัว T ; ไม่คำนวณการแอ่นตัว (มีตรวจ hmin ตาม ACI ตาราง 9.5a) ;
สูงสุด 10 ช่วง
""")

st.divider()
st.caption("⚠️ เครื่องมือช่วยออกแบบ ผลลัพธ์ต้องได้รับการตรวจสอบโดยวิศวกรผู้มีใบอนุญาต")
