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
    HELPER_KINDS, MAXS, POSITIONS, STIRRUP_SIZES, SUPPORT_TYPES, BeamModel, InputError, Load,
    Node, Override, Settings, Span, design_all, helper_load, min_depth, read_workbook,
)
from beam_design import LOAD_PRESETS, preset_factors
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
    return pd.DataFrame([{"ชื่อคาน": s.name, "L (m)": s.L, "b (cm)": s.b, "h (cm)": s.h} for s in spans])


def nodes_df(nodes):
    return pd.DataFrame([{
        "ชนิด": n.kind, "c (cm)": n.c or None,
        "เสาล่าง b": n.lower[0] or None, "เสาล่าง h": n.lower[1] or None, "เสาล่าง H (m)": n.lower[2] or None,
        "เสาบน b": n.upper[0] or None, "เสาบน h": n.upper[1] or None, "เสาบน H (m)": n.upper[2] or None,
        "ต่อเนื่อง": n.continuous,
    } for n in nodes]).astype({c: float for c in ["c (cm)", "เสาล่าง b", "เสาล่าง h", "เสาล่าง H (m)",
                                                  "เสาบน b", "เสาบน h", "เสาบน H (m)"]})


def loads_df(loads):
    return pd.DataFrame([{"ช่วงที่": l.span, "กรณี": l.case, "ชนิด": l.kind, "w1 / P": l.w1,
                          "w2": l.w2, "a (m)": l.a, "b (m)": l.b, "หมายเหตุ": ""} for l in loads],
                        columns=["ช่วงที่", "กรณี", "ชนิด", "w1 / P", "w2", "a (m)", "b (m)", "หมายเหตุ"]
                        ).astype({"w1 / P": float, "w2": float, "a (m)": float, "b (m)": float})


def load_state(settings: Settings, spans, nodes, loads, overrides, project=None, helper=None):
    ss.cb_lc, ss.cb_fD, ss.cb_fL = "code", 1.4, 1.7
    for f, k in SET_KEYS.items():
        v = getattr(settings, f)
        ss[k] = int(v) if f in ("stir", "db", "legs") else v   # selectbox options are ints
    ss.cb_spans = spans_df(spans)
    ss.cb_nodes = nodes_df(nodes)
    ss.cb_loads = loads_df(loads)
    ss.cb_ov = dict(overrides)
    ss.cb_helper = pd.DataFrame(helper or [
        dict(item="พื้น DL (หนา 12 cm + SDL 150)", kind="สองทาง-ด้านสั้น (wS/3)", S=4.0, L=5.0, w=438.0),
        dict(item="พื้น LL", kind="สองทาง-ด้านสั้น (wS/3)", S=4.0, L=5.0, w=200.0),
        dict(item="ผนังก่ออิฐครึ่งแผ่น สูง 2.8 m", kind="ผนัง (w×สูง)", S=2.8, L=None, w=180.0),
    ])
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


if "cb_spans" not in ss:
    load_state(Settings(), EXAMPLE_SPANS, EXAMPLE_NODES, EXAMPLE_LOADS, EXAMPLE_OVERRIDES,
               dict(project="ตัวอย่าง: บ้านพักอาศัย 2 ชั้น", member="B1", date=str(date.today().year)))
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
            load_state(d["settings"], d["spans"], d["nodes"], d["loads"], d["overrides"], d["project"],
                       d["helper"])
            ss.cb_loaded_file = (up.name, up.size)
            st.rerun()
        except Exception as exc:   # bad / foreign workbook
            st.error(f"อ่านไฟล์ไม่สำเร็จ: {exc}")
    if st.button("↺ โหลดข้อมูลตัวอย่าง"):
        load_state(Settings(), EXAMPLE_SPANS, EXAMPLE_NODES, EXAMPLE_LOADS, EXAMPLE_OVERRIDES,
                   dict(project="ตัวอย่าง: บ้านพักอาศัย 2 ชั้น", member="B1", date=str(date.today().year)))
        ss.pop("cb_loaded_file", None)
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
                      "• ตรวจ 1.4DL เพิ่มเสมอ")
    if ss.cb_lc == "custom":
        c1, c2 = st.columns(2)
        c1.number_input("ตัวคูณ DL", 1.0, 2.0, step=0.05, key="cb_fD")
        c2.number_input("ตัวคูณ LL", 1.0, 2.5, step=0.05, key="cb_fL")
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

sett = Settings(**{f: ss[k] for f, k in SET_KEYS.items()})
sett = Settings(**{**sett.__dict__, "legs": int(sett.legs), "stir": float(sett.stir), "db": float(sett.db),
                   "load_factors": preset_factors(ss.cb_lc, (ss.cb_fD, ss.cb_fL))})

# --------------------------------------------------------------------------
# Header + INPUT tables
# --------------------------------------------------------------------------
st.title("📐 ออกแบบคานต่อเนื่อง ค.ส.ล. — Singly & Doubly (SDM)")
st.caption("วิเคราะห์ Direct Stiffness (เสาคิด stiffness 4EI/H) • Pattern LL • ออกแบบทุกช่วง 3 ตำแหน่ง "
           "• หน่วย ตัน-เมตร / ksc / cm • จากไฟล์ Beam_Design_Singly_Doubly.xlsm")

tabs = st.tabs(["📥 INPUT", "📊 ANALYSIS", "🔩 DESIGN", "📄 OUTPUT", "❓ HELP"])

with tabs[0]:
    st.markdown("#### 3. รูปแบบคาน : ช่วงคาน (ซ้าย → ขวา) และ จุดรองรับ")
    st.checkbox("คานเดี่ยวทุกช่วง (ไม่ต่อเนื่องที่จุดรองรับ)", key="cb_allsimple")
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
        rows = []
        for i, s in enumerate(spans, 1):
            md = min_depth(sett, nodes, i, nS, s)
            rows.append({"ช่วง": i, "ประเภท": md["kind"],
                         "นน.คาน (t/m)": round(sett.gc * s.b / 100 * s.h / 100, 3) if sett.self_weight else None,
                         "hmin (cm)": round(md["hmin"], 1), "h ≥ hmin": "OK" if md["ok"] else "ตรวจการแอ่นตัว",
                         "b/h": round(s.b / s.h, 2)})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.markdown("#### 4. น้ำหนักบรรทุก (ตัน, เมตร) — น้ำหนักลง = ค่าบวก")
    c1, c2 = st.columns([3, 2])
    with c1:
        ld_ed = table_editor(
            "loads", ss.cb_loads, f"cb_loads_ed_{ver}", num_rows="dynamic", hide_index=True, width="stretch",
            column_config={
                "ช่วงที่": st.column_config.NumberColumn(min_value=1, max_value=MAXS, step=1, required=True),
                "กรณี": st.column_config.SelectboxColumn(options=["DL", "LL"], required=True, default="DL"),
                "ชนิด": st.column_config.SelectboxColumn(options=["UDL", "Point"], required=True, default="UDL"),
                "w1 / P": st.column_config.NumberColumn(help="t/m หรือ P (t)", format="%.3f"),
                "w2": st.column_config.NumberColumn(help="t/m (ว่าง = w1) — w1≠w2 = สามเหลี่ยม/คางหมู",
                                                    format="%.3f"),
                "a (m)": st.column_config.NumberColumn(help="จากปลายซ้ายของช่วง (Point: ตำแหน่งแรง)",
                                                       format="%.2f"),
                "b (m)": st.column_config.NumberColumn(help="ปลายน้ำหนักแผ่ (ว่าง = L)", format="%.2f"),
            })
        st.caption("UDL: เว้น a, b = เต็มช่วง | w1≠w2 = สามเหลี่ยม/คางหมู | Point: a = ตำแหน่งจากปลายซ้าย")
    with c2:
        st.caption("ตัวช่วย: แปลงน้ำหนักพื้น/ผนัง (kg/m²) เป็นน้ำหนักแผ่บนคาน (t/m)")
        hp = table_editor(
            "helper", ss.cb_helper, f"cb_helper_ed_{ver}", num_rows="dynamic", hide_index=True, width="stretch",
            column_config={
                "item": st.column_config.TextColumn("รายการ"),
                "kind": st.column_config.SelectboxColumn("รูปแบบ", options=HELPER_KINDS),
                "S": st.column_config.NumberColumn("S / สูง (m)", format="%.2f"),
                "L": st.column_config.NumberColumn("L ยาว (m)", format="%.2f"),
                "w": st.column_config.NumberColumn("w (kg/m²)", format="%.0f"),
            })
        hp_out = hp.copy()
        hp_out["ลงคาน (t/m)"] = [
            (lambda v: round(v, 3) if v is not None else None)(
                helper_load(r["kind"], nn(r["S"]) or None, nn(r["L"]) or None, nn(r["w"]) or None))
            for _, r in hp.iterrows()]
        st.dataframe(hp_out[["item", "ลงคาน (t/m)"]].rename(columns={"item": "รายการ"}),
                     hide_index=True, width="stretch")
        st.caption("สองทาง-ด้านยาว: w·S/3·(3−m²)/2, m = S/L • สองทาง-ด้านสั้น: w·S/3")

    opt = lambda v: None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
    loads = [Load(int(r["ช่วงที่"]), str(r["กรณี"] or "DL"), str(r["ชนิด"] or "UDL"), float(r["w1 / P"]),
                  opt(r["w2"]), opt(r["a (m)"]), opt(r["b (m)"]))
             for _, r in ld_ed.dropna(subset=["ช่วงที่", "w1 / P"]).iterrows()]

# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


@st.cache_data(show_spinner="กำลังวิเคราะห์โครงสร้าง ...")
def analyse(sett: Settings, spans: tuple, nodes: tuple, loads: tuple):
    m = BeamModel(sett, list(spans), list(nodes), list(loads))
    return m.summary(), m.stations(), m.reactions(), m.X0


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Drop floating-point noise (e.g. -1e-15) so it does not show as -0.00."""
    return df.map(lambda v: 0.0 if isinstance(v, float) and abs(v) < 1e-9 else v)


err = None
try:
    if not spans:
        raise InputError("กรุณาใส่ช่วงคานอย่างน้อย 1 ช่วง")
    summary, stations, reactions, X0 = analyse(sett, tuple(spans), tuple(nodes), tuple(loads))
except InputError as exc:
    err = str(exc)

if err:
    for t in tabs[1:4]:
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
with tabs[1]:
    st.caption(f"Factored envelope = max/min ของ {sett.fD}DL + {sett.fL}LL "
               f"{'(pattern ทีละช่วง)' if sett.pattern else '(LL เต็มทุกช่วง)'} และ 1.4DL • "
               "M บวก = ท้องคานรับแรงดึง • M ที่ผิวเสา (x = c/2) • Vu ที่ระยะ d จากผิวเสา")
    sdf = pd.DataFrame([{
        "ช่วง": s["span"], "L (m)": s["L"], "b×h (cm)": f"{s['b']:g}×{s['h']:g}", "ประเภท": s["type"],
        "M ซ้าย max": s["ML_max"], "M ซ้าย min": s["ML_min"], "M+ max": s["Mpos_max"], "x (m)": s["Mpos_x"],
        "M min กลาง": s["Mmid_min"], "M ขวา max": s["MR_max"], "M ขวา min": s["MR_min"],
        "Vu ซ้าย": s["Vu_left"], "Vu กลาง": s["Vu_mid"], "Vu ขวา": s["Vu_right"], "d (cm)": s["d"],
    } for s in summary])
    st.markdown("##### สรุปแรงภายในแต่ละช่วง (t-m, t)")
    st.dataframe(clean(sdf).style.format(precision=2), hide_index=True, width="stretch")

    stdf = pd.DataFrame(stations)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.09,
                        subplot_titles=("Bending Moment Diagram (Mu envelope, t-m)",
                                        "Shear Force Diagram (Vu envelope, t)"))
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
        "จุด": r["node"], "X (m)": r["X"], "ชนิด": r["kind"], "R จาก DL (t)": r["RD"], "R จาก LL (t)": r["RL"],
        "Ru max (t)": r["Ru_max"], "Ru min (t)": r["Ru_min"], "Mu เข้าเสา max (t-m)": r["Mu_max"],
        "Mu เข้าเสา min (t-m)": r["Mu_min"]} for r in reactions])).style.format(precision=2),
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
# OUTPUT tab (calculation sheet of one location)
# --------------------------------------------------------------------------
with tabs[3]:
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
    html = build_report(sett, spans, nodes, summary, reactions, rows, project)
    st.download_button("⬇️ ดาวน์โหลดรายการคำนวณทุกช่วง (HTML, พิมพ์ A4)", html,
                       file_name=f"{project['member'] or 'beam'}_calc.html", mime="text/html", type="primary")
    with st.expander("ดูตัวอย่างรายการคำนวณ"):
        st.iframe(html, height=800)

# --------------------------------------------------------------------------
# HELP tab
# --------------------------------------------------------------------------
with tabs[4]:
    st.markdown("""
**ขั้นตอน**
1. แถบซ้าย: กรอกวัสดุ เลือกมาตรฐาน (ACI 318-99/วสท. 1.4D+1.7L หรือ ACI 318-19/มยผ. 1.2D+1.6L) และ
   Load combination (ตามมาตรฐาน / 1.4D+1.7L / 1.2D+1.6L / กำหนดเอง), Pattern LL,
   น้ำหนักคานอัตโนมัติ — หรือ **นำเข้าไฟล์ Excel เดิม** (.xlsm) ได้ทันที
2. แท็บ INPUT ข้อ 3: กรอก L, b, h ของแต่ละช่วงจากซ้ายไปขวา และชนิดจุดรองรับ (จุดที่ 1 ถึง N+1)
   - คานเดี่ยว: 1 ช่วง จุด 1 = Pin, จุด 2 = Pin • คานยื่นอย่างเดียว: 1 ช่วง จุด 1 = Fixed (หรือ Column), จุด 2 = Free
   - คานต่อเนื่อง: ≥ 2 ช่วง • คานต่อเนื่อง + คานยื่น: ให้จุดปลายเป็น Free
   - คานเดี่ยวหลายตัวต่อกัน: ติ๊ก "คานเดี่ยวทุกช่วง" หรือเอาติ๊ก "ต่อเนื่อง" ออกเฉพาะจุดที่ต้องการตัด
     (ห้ามตัดที่จุดโคนคานยื่น มิฉะนั้นโครงสร้างไม่เสถียร)
   - Column: คิด stiffness เสาบน/ล่าง (4EI/H, ปลายไกลยึดแน่น) ถ้าไม่ใส่ขนาดเสา จะเท่ากับ Pin
3. แท็บ INPUT ข้อ 4: ใส่น้ำหนัก DL / LL ทีละแถว (ตัน, เมตร) — ใช้ตารางตัวช่วยแปลงน้ำหนักพื้น/ผนังได้
4. **ไม่ต้องกด RUN** — วิเคราะห์ใหม่อัตโนมัติทุกครั้งที่แก้ข้อมูล
5. แท็บ DESIGN: ออกแบบทุกช่วง 3 ตำแหน่ง เลือก Singly/Doubly อัตโนมัติ — แก้ Ø เหล็ก/จำนวนชั้น/จำนวนเส้น/
   เหล็กปลอก ได้ใน "ช่องสีเหลือง"
6. แท็บ OUTPUT: รายการคำนวณรายตำแหน่ง และดาวน์โหลดรายการคำนวณทุกช่วงเป็น HTML (สั่งพิมพ์ A4)

**หลักการคำนวณ**
- วิเคราะห์ด้วย Direct Stiffness Method (2 DOF/จุด) — เท่ากับ Moment Distribution ของ SUTStructor แต่ไม่ต้องวนรอบ
- Pattern LL: วิเคราะห์ LL ทีละช่วง แล้วรวมเฉพาะส่วนที่เพิ่มค่าสูงสุด/ต่ำสุดในแต่ละจุด และตรวจ 1.4DL ด้วย
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
