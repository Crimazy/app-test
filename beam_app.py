"""Streamlit page: reinforced concrete beam design per มยผ. 1103 / ACI 318-19.

Run the multipage app with:  streamlit run app.py
"""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from beam_design import (
    ACI, CODES, DPT, GAMMA_C, KSC_TO_MPA, LOAD_PRESETS, MAIN_BARS, STIRRUPS, SUPPORTS, TONF_TO_KN,
    BeamInput, BeamSection, Layer, Location, Reinforcement, deflection, design_location,
    development_length, factored_load, load_combinations, min_depth, preset_factors, shear_check,
    span_forces, suggest_reinforcement,
)
from beam_report import build_beam_report

st.set_page_config(page_title="ออกแบบคาน คสล.", page_icon="🏗️", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.6rem;}
      div[data-testid="stMetricValue"] {font-size: 1.45rem;}
      .ok-badge {background:#e6f4ea;color:#137333;padding:4px 12px;border-radius:12px;font-weight:600;}
      .ng-badge {background:#fce8e6;color:#c5221f;padding:4px 12px;border-radius:12px;font-weight:600;}
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Defaults & session state (all keys prefixed "bm_")
# --------------------------------------------------------------------------
DEFAULTS = dict(
    unit_mat="ksc", unit_force="kN", code=DPT,
    bw=300.0, h=600.0, tbeam=False, bf=1000.0, hf=120.0, cover=40.0,
    fc=240.0, fy=4000.0, fyt=2400.0, agg=20.0, stir="RB9", legs=2,
    lc="code", lc_fd=1.4, lc_fl=1.7,
    mode="จากน้ำหนักบรรทุก", support="end", span=6.0, wd=15.0, wl=10.0, selfw=True,
    sus=0.0, dlim="L/240",
    mu_sup=150.0, vu_sup=120.0, mu_mid=100.0, vu_mid=60.0,
    main_bar="DB20", comp_bar="DB16",
    sup_t1n=3, sup_t1d="DB20", sup_t2n=0, sup_t2d="DB20",
    sup_b1n=2, sup_b1d="DB16", sup_b2n=0, sup_b2d="DB16", sup_s=150.0,
    mid_t1n=2, mid_t1d="DB16", mid_t2n=0, mid_t2d="DB16",
    mid_b1n=3, mid_b1d="DB20", mid_b2n=0, mid_b2d="DB20", mid_s=200.0,
)
ss = st.session_state
for k, v in DEFAULTS.items():
    ss.setdefault("bm_" + k, v)


def K(name: str) -> str:
    return "bm_" + name


def V(name: str):
    return ss["bm_" + name]


def bar_name(d: float) -> str:
    return next((k for k, v in MAIN_BARS.items() if v == d), f"DB{d:.0f}")


# --------------------------------------------------------------------------
# Sidebar - inputs
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ ข้อมูลออกแบบ")
    c1, c2 = st.columns(2)
    unit_mat = c1.radio("หน่วยกำลังวัสดุ", ["ksc", "MPa"], key=K("unit_mat"), horizontal=True)
    unit_force = c2.radio("หน่วยแรง", ["kN", "tonf"], key=K("unit_force"), horizontal=True)
    mat_f = 1.0 if unit_mat == "MPa" else KSC_TO_MPA
    F = 1.0 if unit_force == "kN" else TONF_TO_KN       # user force unit -> kN
    fu, mu, wu_u = ("kN", "kN·m", "kN/m") if unit_force == "kN" else ("tonf", "tonf·m", "tonf/m")

    # convert stored values when a unit changes
    prev = ss.get("_bm_unit_mat_prev", "ksc")
    if prev != unit_mat:
        f = 1 / KSC_TO_MPA if unit_mat == "ksc" else KSC_TO_MPA
        for k in ("fc", "fy", "fyt"):
            ss[K(k)] = round(V(k) * f, 1 if k == "fc" else 0)
        ss._bm_unit_mat_prev = unit_mat
    prev = ss.get("_bm_unit_force_prev", "kN")
    if prev != unit_force:
        f = TONF_TO_KN if unit_force == "kN" else 1 / TONF_TO_KN
        for k in ("wd", "wl", "mu_sup", "vu_sup", "mu_mid", "vu_mid"):
            ss[K(k)] = round(V(k) * f, 2)
        ss._bm_unit_force_prev = unit_force

    st.radio("มาตรฐานการออกแบบ", list(CODES), format_func=CODES.get, key=K("code"),
             help="มยผ. 1103: U = 1.4D + 1.7L, φ ดัด 0.90 / เฉือน 0.85, ρ ≤ 0.75ρb\n\n"
                  "ACI 318-19: U = 1.2D + 1.6L, φ ตาม εt, εt ≥ 0.004, Vc รวม size effect")

    with st.expander("🧱 1. หน้าตัดคาน", expanded=True):
        c1, c2 = st.columns(2)
        c1.number_input("กว้าง bw (mm)", 150.0, 2000.0, step=25.0, key=K("bw"))
        c2.number_input("ลึก h (mm)", 200.0, 3000.0, step=50.0, key=K("h"))
        st.checkbox("คานตัว T (หล่อพร้อมพื้น)", key=K("tbeam"),
                    help="ปีกอยู่ด้านบน ช่วยรับแรงอัดเมื่อโมเมนต์บวก (กลางช่วง)")
        if V("tbeam"):
            c1, c2 = st.columns(2)
            c1.number_input("ความกว้างปีก bf (mm)", 150.0, 6000.0, step=50.0, key=K("bf"))
            c2.number_input("ความหนาพื้น hf (mm)", 50.0, 500.0, step=10.0, key=K("hf"))
        st.number_input("ระยะหุ้มถึงผิวเหล็กปลอก (mm)", 20.0, 100.0, step=5.0, key=K("cover"),
                        help="ACI 318-19 Table 20.5.1.3.1: คานภายในอาคาร ≥ 40 mm")

    with st.expander("🧪 2. วัสดุ", expanded=True):
        fy_lo, fy_hi = (200.0, 700.0) if unit_mat == "MPa" else (2000.0, 7000.0)
        st.number_input(f"fc' คอนกรีต ({unit_mat})", 15.0 if unit_mat == "MPa" else 150.0,
                        100.0 if unit_mat == "MPa" else 1000.0, key=K("fc"),
                        help="ทรงกระบอก; ksc: 240 ≈ 23.5 MPa, 280 ≈ 27.5 MPa")
        c1, c2 = st.columns(2)
        c1.number_input(f"fy เหล็กยืน ({unit_mat})", fy_lo, fy_hi, key=K("fy"), help="SD40 = 4000 ksc")
        c2.number_input(f"fyt เหล็กปลอก ({unit_mat})", fy_lo, fy_hi, key=K("fyt"), help="SR24 = 2400 ksc")
        st.number_input("ขนาดมวลรวมโตสุด (mm)", 10.0, 40.0, step=5.0, key=K("agg"))
        c1, c2 = st.columns(2)
        c1.selectbox("เหล็กปลอก", list(STIRRUPS), key=K("stir"))
        c2.number_input("จำนวนขาปลอก", 2, 8, step=1, key=K("legs"))

    with st.expander("⚖️ 3. น้ำหนักบรรทุก / แรงกระทำ", expanded=True):
        st.radio("วิธีกำหนดแรง", ["จากน้ำหนักบรรทุก", "กรอกแรงประลัยเอง"], key=K("mode"), horizontal=True)
        if V("mode") == "จากน้ำหนักบรรทุก":
            st.selectbox("สภาพจุดรองรับ", list(SUPPORTS), format_func=lambda s: SUPPORTS[s]["name"],
                         key=K("support"))
            st.number_input("ความยาวช่วง L (m)", 0.5, 30.0, step=0.5, key=K("span"),
                            help="ใช้ช่วงว่าง ln สำหรับวิธีสัมประสิทธิ์ (คานต่อเนื่อง)")
            c1, c2 = st.columns(2)
            c1.number_input(f"DL เพิ่มเติม ({wu_u})", 0.0, 1000.0, step=1.0, key=K("wd"),
                            help="น้ำหนักบรรทุกคงที่แผ่กระจาย (ไม่รวมน้ำหนักคาน)")
            c2.number_input(f"LL ({wu_u})", 0.0, 1000.0, step=1.0, key=K("wl"))
            st.checkbox(f"รวมน้ำหนักคานเอง ({GAMMA_C:.0f} kN/m³)", key=K("selfw"))
            st.selectbox("Load combination", list(LOAD_PRESETS), format_func=LOAD_PRESETS.get, key=K("lc"),
                         help="ตามมาตรฐาน: มยผ. 1103 = 1.4D + 1.7L, ACI 318-19 = 1.2D + 1.6L • "
                              "ตรวจ 1.4D เพิ่มเสมอเมื่อตัวคูณ DL < 1.4")
            if V("lc") == "custom":
                c1, c2 = st.columns(2)
                c1.number_input("ตัวคูณ DL", 1.0, 2.0, step=0.05, key=K("lc_fd"))
                c2.number_input("ตัวคูณ LL", 1.0, 2.5, step=0.05, key=K("lc_fl"))
            c1, c2 = st.columns(2)
            c1.number_input("สัดส่วน LL ค้างนาน", 0.0, 1.0, step=0.05, key=K("sus"),
                            help="ใช้คำนวณการโก่งตัวระยะยาว")
            c2.selectbox("ขีดจำกัดการโก่งตัวระยะยาว", ["L/240", "L/480"], key=K("dlim"),
                         help="L/480 เมื่อรองรับชิ้นส่วนที่เสียหายได้ง่าย (ผนังก่อ)")
        else:
            st.caption(f"แรงประลัยที่หน้าตัดวิกฤต (Vu ที่ระยะ d จากหน้าจุดรองรับ) — {fu}, {mu}")
            c1, c2 = st.columns(2)
            c1.number_input(f"Mu− ที่รองรับ ({mu})", 0.0, 1e5, step=5.0, key=K("mu_sup"))
            c2.number_input(f"Vu ที่รองรับ ({fu})", 0.0, 1e5, step=5.0, key=K("vu_sup"))
            c1.number_input(f"Mu+ กลางช่วง ({mu})", 0.0, 1e5, step=5.0, key=K("mu_mid"))
            c2.number_input(f"Vu กลางช่วง ({fu})", 0.0, 1e5, step=5.0, key=K("vu_mid"))

code = V("code")
inp = BeamInput(
    code=code, bw=V("bw"), h=V("h"), tbeam=V("tbeam"), bf=V("bf"), hf=V("hf"), cover=V("cover"),
    fc=V("fc") * mat_f, fy=V("fy") * mat_f, fyt=V("fyt") * mat_f, agg=V("agg"),
    stirrup_d=STIRRUPS[V("stir")], legs=int(V("legs")),
)
if inp.flange and inp.hf >= inp.h:
    st.error("ความหนาพื้น hf ต้องน้อยกว่าความลึกคาน h")
    st.stop()


def reinf_of(tag: str) -> Reinforcement:
    g = lambda n: V(f"{tag}_{n}")
    return Reinforcement(
        top1=Layer(int(g("t1n")), MAIN_BARS[g("t1d")]), top2=Layer(int(g("t2n")), MAIN_BARS[g("t2d")]),
        bot1=Layer(int(g("b1n")), MAIN_BARS[g("b1d")]), bot2=Layer(int(g("b2n")), MAIN_BARS[g("b2d")]),
        s=float(g("s")),
    )


kN = lambda n: n / 1e3 / F            # N -> user force unit
kNm = lambda nmm: nmm / 1e6 / F       # N*mm -> user moment unit

# --------------------------------------------------------------------------
# Design forces
# --------------------------------------------------------------------------
analysis = V("mode") == "จากน้ำหนักบรรทุก"
support = V("support")
r_sup, r_mid = reinf_of("sup"), reinf_of("mid")
span = V("span") * 1000.0 if analysis else None
if analysis:
    Ag_m2 = BeamSection(inp, r_mid).Ag / 1e6
    w_self = GAMMA_C * Ag_m2 if V("selfw") else 0.0          # kN/m = N/mm
    wD = V("wd") * F + w_self
    wL = V("wl") * F
    factors = preset_factors(V("lc"), (V("lc_fd"), V("lc_fl")))
    combo, wu = factored_load(code, wD, wL, factors)
    sign_sup = -1 if SUPPORTS[support]["cn"] > 0 else 1
    d_sup = BeamSection(inp, r_sup).tension_steel(sign_sup)[1]
    frc = span_forces(inp, span, support, wu, d_sup)
    loc_defs = [("sup", "ที่รองรับ (Support)", -frc["Mneg"], frc["Vu_d"])]
    if support != "cantilever":
        loc_defs.append(("mid", "กลางช่วง (Midspan)", frc["Mpos"], frc["Vu_mid"]))
else:
    loc_defs = [
        ("sup", "ที่รองรับ (Support)", -V("mu_sup") * F * 1e6, V("vu_sup") * F * 1e3),
        ("mid", "กลางช่วง (Midspan)", V("mu_mid") * F * 1e6, V("vu_mid") * F * 1e3),
    ]

# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
st.title("🏗️ ออกแบบคานคอนกรีตเสริมเหล็ก")
st.caption(f"มาตรฐาน: **{CODES[code]}** • ออกแบบรับแรงดัด (strain compatibility, Whitney stress block), "
           "แรงเฉือน, การโก่งตัว, ระยะฝังยึด และรายละเอียดเหล็กเสริม • หน่วยภายใน SI")

if analysis:
    combos = " , ".join(f"{n} = {kN(w * 1e3):,.2f}" for n, w in load_combinations(code, wD, wL, factors))
    st.info(f"น้ำหนักบรรทุก: DL = {kN(wD * 1e3):,.2f} {wu_u} (น้ำหนักคาน {kN(w_self * 1e3):,.2f}), "
            f"LL = {kN(wL * 1e3):,.2f} {wu_u} → {combos} {wu_u} • ใช้ **wu = {kN(wu * 1e3):,.2f} {wu_u}** "
            f"({combo})", icon="⚖️")

# --------------------------------------------------------------------------
# Reinforcement inputs
# --------------------------------------------------------------------------


def reinf_editor(tag: str, title: str, Mu: float, Vu: float):
    with st.container(border=True):
        st.markdown(f"**{title}** &nbsp; Mu = {kNm(Mu):,.1f} {mu} • Vu = {kN(Vu):,.1f} {fu}")
        for face, label in (("t", "บน"), ("b", "ล่าง")):
            c1, c2, c3, c4 = st.columns(4)
            c1.number_input(f"เหล็ก{label} ชั้น 1", 0, 20, step=1, key=K(f"{tag}_{face}1n"))
            c2.selectbox("ขนาด", list(MAIN_BARS), key=K(f"{tag}_{face}1d"))
            c3.number_input(f"เหล็ก{label} ชั้น 2", 0, 20, step=1, key=K(f"{tag}_{face}2n"))
            c4.selectbox("ขนาด", list(MAIN_BARS), key=K(f"{tag}_{face}2d"))
        st.number_input(f"ระยะเรียงเหล็กปลอก {V('stir')} ({inp.legs} ขา) s (mm)", 25.0, 600.0,
                        step=25.0, key=K(f"{tag}_s"))


def apply_auto(locs_spec, main_d: float, comp_d: float):
    picks = {}
    for tag, title, Mu, Vu in locs_spec:
        loc = Location(title, Mu, Vu, reinf_of(tag))
        if Mu == 0:   # no flexure here: only set stirrup spacing
            sh = shear_check(BeamSection(inp, loc.reinf), Vu, loc.reinf.s)
            picks[tag] = replace(loc.reinf, s=sh["s_rec"])
            continue
        r = suggest_reinforcement(inp, loc, main_d, comp_d, span)
        if r is None:
            ss["_bm_auto_msg"] = f"❌ {title}: หน้าตัดเล็กเกินไป — ขยายหน้าตัดหรือใช้เหล็กเส้นใหญ่ขึ้น"
            return
        picks[tag] = r
    for tag, r in picks.items():
        for face, lay in (("t1", r.top1), ("t2", r.top2), ("b1", r.bot1), ("b2", r.bot2)):
            ss[K(f"{tag}_{face}n")] = lay.n
            ss[K(f"{tag}_{face}d")] = bar_name(lay.d)
        ss[K(f"{tag}_s")] = float(r.s)
    ss["_bm_auto_msg"] = "✅ จัดเหล็กเสริมอัตโนมัติแล้ว — ตรวจสอบผลด้านล่าง"


st.subheader("🔩 เหล็กเสริม")
with st.expander("🪄 ออกแบบเหล็กเสริมอัตโนมัติ", expanded=False):
    st.write("หาจำนวนเหล็กรับแรงดึงน้อยที่สุด (1–2 ชั้น) ที่ผ่านกำลัง/As,min/ความเหนียว "
             "และระยะเรียงเหล็กปลอกที่ต้องการ โดยคงขนาดหน้าตัดเดิม")
    c1, c2, c3 = st.columns([1, 1, 1])
    c1.selectbox("เหล็กรับแรงดึง", list(MAIN_BARS), key=K("main_bar"))
    c2.selectbox("เหล็กรับแรงอัด/เหล็กนั่งร้าน", list(MAIN_BARS), key=K("comp_bar"))
    c3.button("ออกแบบ", type="primary", on_click=apply_auto,
              args=(loc_defs, MAIN_BARS[V("main_bar")], MAIN_BARS[V("comp_bar")]))
    if msg := ss.pop("_bm_auto_msg", None):
        (st.success if msg.startswith("✅") else st.error)(msg)

cols = st.columns(len(loc_defs))
for col, (tag, title, Mu, Vu) in zip(cols, loc_defs):
    with col:
        reinf_editor(tag, title, Mu, Vu)

# --------------------------------------------------------------------------
# Compute
# --------------------------------------------------------------------------
results = {tag: design_location(inp, Location(title, Mu, Vu, reinf_of(tag)), span)
           for tag, title, Mu, Vu in loc_defs}
defl = hmin = None
if analysis:
    dsec = results["sup"].sec if support == "cantilever" else results["mid"].sec
    defl = deflection(inp, dsec, span, support, wD, wL, V("sus"))
    hmin = min_depth(inp, span, support)

all_ok = all(r.ok for r in results.values())
defl_ok = True
if defl:
    defl_ok = (defl["dL"] <= defl["eff_L"] / 360 and
               defl["d_after"] <= defl["eff_L"] / (240 if V("dlim") == "L/240" else 480))
gov = max(results.values(), key=lambda r: r.dcr)

# --------------------------------------------------------------------------
# Summary strip
# --------------------------------------------------------------------------
st.divider()
ok_all = all_ok and defl_ok
badge = ('<span class="ok-badge">✅ ผ่านทุกข้อ (OK)</span>' if ok_all
         else '<span class="ng-badge">❌ ไม่ผ่าน (NG)</span>')
st.markdown(f"### ผลการออกแบบ &nbsp; {badge}", unsafe_allow_html=True)
m = st.columns(5)
for i, (tag, r) in enumerate(results.items()):
    if r.flex is not None:
        m[i].metric(f"φMn {r.loc.name.split(' ')[0]}", f"{kNm(r.flex['phiMn']):,.1f} {mu}",
                    f"Mu = {kNm(abs(r.loc.Mu)):,.1f}", delta_color="off", delta_arrow="off")
    else:
        m[i].metric(f"φMn {r.loc.name.split(' ')[0]}", "-", "ไม่มีโมเมนต์", delta_color="off",
                    delta_arrow="off")
sh_gov = max(results.values(), key=lambda r: r.shear["dcr"]).shear
m[2].metric("φVn (วิกฤต)", f"{kN(sh_gov['phiVn']):,.1f} {fu}", f"Vu = {kN(sh_gov['Vu']):,.1f}",
            delta_color="off", delta_arrow="off")
m[3].metric("D/C สูงสุด", f"{gov.dcr:.2f}" if math.isfinite(gov.dcr) else "∞", gov.loc.name,
            delta_color="inverse" if gov.dcr > 1 else "off", delta_arrow="off")
if defl:
    m[4].metric("การโก่งตัวระยะยาว", f"{defl['d_after']:.1f} mm",
                f"ขีดจำกัด {defl['eff_L'] / (240 if V('dlim') == 'L/240' else 480):.1f} mm",
                delta_color="off" if defl_ok else "inverse", delta_arrow="off")
else:
    m[4].metric("β1 / Ec", f"{gov.sec.beta1:.3f}", f"Ec = {gov.sec.Ec:,.0f} MPa", delta_color="off",
                delta_arrow="off")
if gov.dcr <= 1:
    st.progress(min(gov.dcr, 1.0), text=f"อัตราส่วนการใช้งานสูงสุด {gov.dcr * 100:.0f}%")
else:
    st.error(f"กำลังไม่พอ: D/C = {gov.dcr:.2f} ที่ {gov.loc.name} — เพิ่มเหล็กเสริม/ขนาดหน้าตัด "
             "หรือใช้ 'ออกแบบเหล็กเสริมอัตโนมัติ'")

tabs = st.tabs(["📋 สรุปผล", "📐 แรงดัด", "✂️ แรงเฉือน", "🧱 หน้าตัด",
                "📉 แรงภายใน & การโก่งตัว", "🔗 ระยะฝังยึด", "📝 รายงาน"])


def style_status(df: pd.DataFrame, col: str = "สถานะ"):
    return df.style.format(precision=1).map(
        lambda v: "color:#137333;font-weight:600" if v == "OK" else "color:#c5221f;font-weight:600",
        subset=[col])


def checks_df(items):
    return pd.DataFrame([{"ข้อกำหนด": d["clause"], "รายการ": d["item"], "ต้องการ": d["required"],
                          "ที่ใช้": d["provided"], "สถานะ": "OK" if d["ok"] else "NG"} for d in items])


def unit_txt(txt: str) -> str:
    """Engine messages are in kN; convert labels when tonf is selected."""
    if unit_force == "kN":
        return txt
    import re

    def conv(m_):
        val = float(m_.group(1).replace(",", "")) / F
        return f"{val:,.2f} {m_.group(2).replace('kN', 'tonf')}"
    return re.sub(r"([\d,]+\.?\d*) (kN·m|kN)", conv, txt)


def bars_txt(r: Reinforcement, face: str) -> str:
    l1, l2 = (r.top1, r.top2) if face == "top" else (r.bot1, r.bot2)
    parts = [f"{l.n}-{bar_name(l.d)}" for l in (l1, l2) if l.n]
    return " + ".join(parts) if parts else "-"


# ---- Summary ---------------------------------------------------------------
with tabs[0]:
    rows = []
    for tag, r in results.items():
        f_ = r.flex
        rows.append({
            "ตำแหน่ง": r.loc.name,
            "เหล็กบน": bars_txt(r.loc.reinf, "top"),
            "เหล็กล่าง": bars_txt(r.loc.reinf, "bot"),
            "ปลอก": f"{V('stir')} @ {r.loc.reinf.s:.0f} mm",
            f"Mu ({mu})": round(kNm(abs(r.loc.Mu)), 1),
            f"φMn ({mu})": round(kNm(f_["phiMn"]), 1) if f_ else None,
            f"Vu ({fu})": round(kN(r.shear["Vu"]), 1),
            f"φVn ({fu})": round(kN(r.shear["phiVn"]), 1),
            "D/C": f"{r.dcr:.3f}" if math.isfinite(r.dcr) else "∞",
            "สถานะ": "OK" if r.ok else "NG",
        })
    st.dataframe(style_status(pd.DataFrame(rows)), width="stretch", hide_index=True)
    for tag, r in results.items():
        with st.expander(f"รายการตรวจสอบ — {r.loc.name}", expanded=not r.ok):
            st.dataframe(style_status(checks_df([{**c, "required": unit_txt(c["required"]),
                                                  "provided": unit_txt(c["provided"])}
                                                 for c in r.checks + r.detail])),
                         width="stretch", hide_index=True)
    if hmin is not None:
        msg = (f"ความลึกขั้นต่ำโดยไม่ต้องคำนวณการโก่งตัว (Table 9.3.1.1 / 9.5(a)): "
               f"h,min = L/{SUPPORTS[support]['hdiv']:g} × (0.4 + fy/700) = **{hmin:.0f} mm** — ")
        if inp.h >= hmin:
            st.success(msg + f"h = {inp.h:.0f} mm ✔")
        else:
            st.warning(msg + f"h = {inp.h:.0f} mm น้อยกว่า → ตรวจสอบการโก่งตัวในแท็บ 'แรงภายใน & การโก่งตัว'")


# ---- Flexure ---------------------------------------------------------------
def strain_stress_fig(r):
    f_ = r.flex
    h = inp.h
    c, a = f_["c"], f_["a"]
    # oriented depth -> plot y (compression face at top of the plot)
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.08,
                        subplot_titles=("ความเครียด ε", "แรงภายใน (kN)"))
    eps_bot = 0.003 * (c - h) / c
    fig.add_scatter(x=[0, 0.003, eps_bot, 0], y=[0, 0, h, h], fill="toself", mode="lines",
                    line=dict(color="#1a73e8"), fillcolor="rgba(26,115,232,0.15)", showlegend=False,
                    row=1, col=1)
    for A, y, eps, fs, Fs in f_["steel"]:
        fig.add_scatter(x=[eps], y=[y], mode="markers+text", text=[f"{eps:+.4f}"],
                        textposition="middle right" if eps >= 0 else "middle left",
                        marker=dict(size=9, color="#c5221f" if eps < 0 else "#137333"),
                        showlegend=False, row=1, col=1)
        fig.add_scatter(x=[0, Fs / 1e3], y=[y, y], mode="lines+markers+text",
                        text=["", f"{Fs / 1e3:,.0f}<br>fs={fs:,.0f}"], textposition="middle right"
                        if Fs >= 0 else "middle left", line=dict(color="#e37400", width=4),
                        marker=dict(size=[0, 8]), showlegend=False, row=1, col=2)
    fig.add_shape(type="rect", x0=0, x1=f_["Cc"] / 1e3, y0=0, y1=a, fillcolor="rgba(26,115,232,0.25)",
                  line=dict(color="#1a73e8"), row=1, col=2)
    fig.add_annotation(x=f_["Cc"] / 1e3, y=a / 2, text=f"Cc = {f_['Cc'] / 1e3:,.0f}", showarrow=False,
                       xanchor="left", row=1, col=2)
    fig.add_hline(y=c, line=dict(color="#5f6368", dash="dash"), annotation_text=f"c = {c:.0f} mm",
                  row=1, col=1)
    fig.update_yaxes(autorange="reversed", title_text="ระยะจากผิวรับแรงอัด (mm)", row=1, col=1)
    fig.update_xaxes(zeroline=True, zerolinecolor="#9aa0a6")
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="white")
    return fig


with tabs[1]:
    for tag, r in results.items():
        st.markdown(f"#### {r.loc.name}")
        if r.flex is None:
            st.caption("ไม่มีโมเมนต์ดัดที่ตำแหน่งนี้")
            continue
        f_ = r.flex
        req_txt = (f"{r.req['As']:,.0f}" if r.req["As"] is not None
                   else "เกินขีดจำกัด → เพิ่มเหล็กรับแรงอัด/ขยายหน้าตัด")
        c1, c2 = st.columns([2, 3])
        with c1:
            sign_txt = "บวก (ล่างรับแรงดึง)" if r.sign > 0 else "ลบ (บนรับแรงดึง)"
            st.markdown(f"""
| รายการ | ค่า |
|---|---|
| โมเมนต์ | {sign_txt} |
| หน้าตัดรับแรงอัด | {'ตัว T (ปีกรับแรงอัด)' if f_['compression_flange'] else 'สี่เหลี่ยม bw'} |
| d / dt | {f_['d']:.0f} / {f_['dt']:.0f} mm |
| As (ดึง) / As' (อัด) | {f_['As']:,.0f} / {f_['As_comp']:,.0f} mm² |
| As ต้องการ | {req_txt} mm² |
| As,min | {f_['As_min']:,.0f} mm² |
| As,max ({'εt = 0.004' if code == ACI else '0.75ρb + ρ′fs′/fy'}) | {f_['As_max']:,.0f} mm² |
| ρ = As/(bw·d) | {f_['rho'] * 100:.3f} % |
| c / a (β1 = {r.sec.beta1:.3f}) | {f_['c']:.1f} / {f_['a']:.1f} mm |
| εt | {f_['eps_t']:.4f} |
| φ | {f_['phi']:.3f} |
| Mn | {kNm(f_['Mn']):,.1f} {mu} |
| **φMn** | **{kNm(f_['phiMn']):,.1f} {mu}** |
| Mu | {kNm(abs(r.loc.Mu)):,.1f} {mu} |
""")
        with c2:
            st.plotly_chart(strain_stress_fig(r), width="stretch", key=f"ss_{tag}")
    if code == ACI:
        st.caption("φ ตาม Table 21.2.2: 0.65 เมื่อ εt ≤ εty, 0.90 เมื่อ εt ≥ εty + 0.003 • "
                   "คานต้องมี εt ≥ 0.004 (9.3.3.1) • As,min = max(0.25√fc′, 1.4)·bw·d/fy (9.6.1.2)")
    else:
        st.caption("มยผ. 1103 (ACI 318-99): φ = 0.90 • ρb = 0.85β1(fc′/fy)·600/(600+fy) • "
                   "As ≤ 0.75Asb + As′fs′/fy (10.3.3) • As,min = max(0.25√fc′, 1.4)·bw·d/fy "
                   "(≈ 14/fy ksc) หรือ 4/3 As ต้องการ")


# ---- Shear -----------------------------------------------------------------
with tabs[2]:
    rows = []
    for tag, r in results.items():
        sh = r.shear
        rows.append({
            "ตำแหน่ง": r.loc.name, "d (mm)": round(sh["d"]), "ρw (%)": round(sh["rho_w"] * 100, 3),
            "Av (mm²)": round(sh["Av"], 1), "Av,min (mm²)": round(sh["Av_min"], 1),
            f"Vc ({fu})": round(kN(sh["Vc"]), 1), f"φVc ({fu})": round(kN(sh["phiVc"]), 1),
            f"Vs ({fu})": round(kN(sh["Vs"]), 1), f"Vs ต้องการ ({fu})": round(kN(sh["Vs_req"]), 1),
            f"φVn ({fu})": round(kN(sh["phiVn"]), 1), f"Vu ({fu})": round(kN(sh["Vu"]), 1),
            "s ใช้ (mm)": round(sh["s"]), "s,max (mm)": round(sh["s_max"]),
            "s แนะนำ (mm)": round(sh["s_rec"]),
            "สถานะ": "OK" if all(c["ok"] for c in r.checks[-4:]) else "NG",
        })
    st.dataframe(style_status(pd.DataFrame(rows)), width="stretch", hide_index=True)
    for tag, r in results.items():
        st.caption(f"{r.loc.name}: {r.shear['eq']} • φ = {r.shear['phi']} • fyt ใช้คำนวณ = "
                   f"{r.shear['fyt']:.0f} MPa • ต้องใช้ Av,min เมื่อ {r.shear['av_needed_txt']}")
    if code == ACI:
        st.caption("ACI 318-19: Vs ≤ 0.66√fc′·bw·d (22.5.1.2) • s ≤ d/2 ≤ 600 mm; "
                   "ถ้า Vs > 0.33√fc′·bw·d → s ≤ d/4 ≤ 300 mm (9.7.6.2.2) • λs = √(2/(1+d/254)) ≤ 1")
    else:
        st.caption("มยผ. 1103 (ACI 318-99): Vc = 0.53√fc′·bw·d (ksc) • Vs ≤ 2.1√fc′·bw·d (ksc) • "
                   "s ≤ d/2 ≤ 60 cm; ถ้า Vs > 1.1√fc′·bw·d → s ≤ d/4 ≤ 30 cm • Av,min = 3.5bw·s/fy (ksc)")


# ---- Section drawing -------------------------------------------------------
def section_fig(r):
    sec, rf = r.sec, r.loc.reinf
    h, bw = inp.h, inp.bw
    fig = go.Figure()
    if inp.flange:
        bf, hf = inp.bf, inp.hf
        xs = [-bw / 2, bw / 2, bw / 2, bf / 2, bf / 2, -bf / 2, -bf / 2, -bw / 2, -bw / 2]
        ys = [0, 0, h - hf, h - hf, h, h, h - hf, h - hf, 0]
        W = bf
    else:
        xs, ys, W = [-bw / 2, bw / 2, bw / 2, -bw / 2, -bw / 2], [0, 0, h, h, 0], bw
    fig.add_scatter(x=xs, y=ys, fill="toself", fillcolor="#e8eaed", line=dict(color="#5f6368", width=2),
                    mode="lines", showlegend=False, hoverinfo="skip")
    off = inp.cover + inp.stirrup_d / 2
    fig.add_shape(type="rect", x0=-bw / 2 + off, y0=off, x1=bw / 2 - off, y1=h - off,
                  line=dict(color="#e37400", width=max(inp.stirrup_d / 4, 2)))
    if inp.legs > 2:
        for x in np.linspace(-bw / 2 + off, bw / 2 - off, inp.legs)[1:-1]:
            fig.add_shape(type="line", x0=x, y0=off, x1=x, y1=h - off,
                          line=dict(color="#e37400", width=2, dash="dash"))
    inner = bw / 2 - inp.cover - inp.stirrup_d
    hover_x, hover_y, hover_t = [], [], []
    for A, y, face, layer, n, db in sec.bars:
        xs_ = np.linspace(-inner + db / 2, inner - db / 2, n) if n > 1 else np.array([-inner + db / 2])
        yp = h - y
        for x in xs_:
            fig.add_shape(type="circle", x0=x - db / 2, y0=yp - db / 2, x1=x + db / 2, y1=yp + db / 2,
                          fillcolor="#3c4043", line=dict(color="#202124"))
            hover_x.append(x)
            hover_y.append(yp)
            hover_t.append(f"{'บน' if face == 'top' else 'ล่าง'} ชั้น {layer}: {n}-{bar_name(db)} "
                           f"(ลึก {y:.0f} mm)")
    fig.add_scatter(x=hover_x, y=hover_y, mode="markers", marker=dict(size=1, opacity=0),
                    hovertext=hover_t, hoverinfo="text", showlegend=False)
    pad = 0.15 * max(W, h)
    fig.add_annotation(x=0, y=-pad * 0.4, text=f"bw = {bw:.0f} mm", showarrow=False, font=dict(size=13))
    fig.add_annotation(x=-W / 2 - pad * 0.4, y=h / 2, text=f"h = {h:.0f} mm", textangle=-90,
                       showarrow=False, font=dict(size=13))
    if inp.flange:
        fig.add_annotation(x=0, y=h + pad * 0.35, text=f"bf = {inp.bf:.0f}, hf = {inp.hf:.0f} mm",
                           showarrow=False, font=dict(size=13))
    fig.update_xaxes(range=[-W / 2 - pad, W / 2 + pad], visible=False)
    fig.update_yaxes(range=[-pad, h + pad], visible=False, scaleanchor="x", scaleratio=1)
    fig.update_layout(height=460, plot_bgcolor="white", margin=dict(l=0, r=0, t=30, b=0),
                      title=dict(text=r.loc.name, x=0.5, font=dict(size=15)))
    return fig


with tabs[3]:
    cols = st.columns(len(results))
    for col, (tag, r) in zip(cols, results.items()):
        with col:
            st.plotly_chart(section_fig(r), width="stretch", key=f"sec_{tag}")
            rf = r.loc.reinf
            st.markdown(f"""
| รายการ | ค่า |
|---|---|
| เหล็กบน | {bars_txt(rf, 'top')} |
| เหล็กล่าง | {bars_txt(rf, 'bot')} |
| เหล็กปลอก | {V('stir')} {inp.legs} ขา @ {rf.s:.0f} mm |
| Ag / Ig | {r.sec.Ag:,.0f} mm² / {r.sec.Ig / 1e6:,.0f}×10⁶ mm⁴ |
| fc′ / fy / fyt | {inp.fc:.1f} / {inp.fy:.0f} / {inp.fyt:.0f} MPa |
""")


# ---- Internal forces & deflection -----------------------------------------
with tabs[4]:
    if not analysis:
        st.info("แท็บนี้ใช้ได้เมื่อเลือก 'จากน้ำหนักบรรทุก' (ต้องทราบความยาวช่วงและน้ำหนักบรรทุก)")
    else:
        sp = SUPPORTS[support]
        L = span
        x = np.linspace(0, L, 201)
        w = wu
        if support == "cantilever":
            M = -w * (L - x) ** 2 / 2
            Vx = w * (L - x)
        else:
            M1 = {"simple": 0.0, "end": w * L * L / 16, "interior": w * L * L / 11}[support]
            M2 = {"simple": 0.0, "end": w * L * L / 10, "interior": w * L * L / 11}[support]
            R1 = w * L / 2 - (M1 - M2) / L
            M = -M1 + R1 * x - w * x * x / 2
            Vx = R1 - w * x
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                            subplot_titles=(f"แผนภาพโมเมนต์ ({mu})", f"แผนภาพแรงเฉือน ({fu})"))
        fig.add_scatter(x=x / 1000, y=kNm(M), fill="tozeroy", line=dict(color="#1a73e8"),
                        name="M (สถิตศาสตร์)", row=1, col=1)
        fig.add_scatter(x=x / 1000, y=kN(Vx), fill="tozeroy", line=dict(color="#e37400"),
                        name="V", row=2, col=1)
        if frc["Mpos"] > 0:
            fig.add_hline(y=kNm(frc["Mpos"]), line=dict(color="#137333", dash="dot"), row=1, col=1,
                          annotation_text=f"Mu+ = wL²/{1 / sp['cp']:g}")
        if frc["Mneg"] > 0:
            fig.add_hline(y=-kNm(frc["Mneg"]), line=dict(color="#c5221f", dash="dot"), row=1, col=1,
                          annotation_text=f"Mu− = wL²/{1 / sp['cn']:g}")
        fig.update_yaxes(autorange="reversed", row=1, col=1)
        fig.update_xaxes(title_text="ระยะ (m)", row=2, col=1)
        fig.update_layout(height=560, showlegend=False, margin=dict(l=10, r=10, t=40, b=10))
        c1, c2 = st.columns([3, 2])
        c1.plotly_chart(fig, width="stretch")
        with c2:
            st.markdown(f"""
**แรงออกแบบ (วิธีสัมประสิทธิ์ ACI)**

| รายการ | ค่า |
|---|---|
| wu ({combo}) | {kN(wu * 1e3):,.2f} {wu_u} |
| Mu+ = {('wL²/' + format(1 / sp['cp'], 'g')) if sp['cp'] else '-'} | {kNm(frc['Mpos']):,.1f} {mu} |
| Mu− = {('wL²/' + format(1 / sp['cn'], 'g')) if sp['cn'] else '-'} | {kNm(frc['Mneg']):,.1f} {mu} |
| Vu ที่หน้าจุดรองรับ = {sp['cv']:g}wL | {kN(frc['V_face']):,.1f} {fu} |
| Vu ที่ระยะ d | {kN(frc['Vu_d']):,.1f} {fu} |
| Vu ที่ L/4 (โซนกลางช่วง) | {kN(frc['Vu_mid']):,.1f} {fu} |
""")
            st.caption("แผนภาพแสดงผลจากสถิตศาสตร์ที่โมเมนต์ปลายตามสัมประสิทธิ์ (ประกอบการอ่าน) "
                       "ค่าออกแบบใช้สัมประสิทธิ์ซึ่งครอบคลุมการจัดน้ำหนักจรเป็นรูปแบบ — "
                       "เงื่อนไข: ≥ 2 ช่วง, ช่วงต่างกัน ≤ 20%, LL ≤ 3DL, น้ำหนักแผ่สม่ำเสมอ")

        st.markdown("#### การโก่งตัว (Deflection)")
        d_ = defl
        lim_L = d_["eff_L"] / 360
        lim_T = d_["eff_L"] / (240 if V("dlim") == "L/240" else 480)
        ie_txt = ("Ie = Icr / [1 − ((2/3)Mcr/Ma)²(1 − Icr/Ig)] (Table 24.2.3.5)" if code == ACI
                  else "Ie = (Mcr/Ma)³Ig + [1 − (Mcr/Ma)³]Icr ≤ Ig (Branson, 9.5.2.3)")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"""
| คุณสมบัติหน้าตัด ({'ที่รองรับ' if d_['sign'] < 0 else 'กลางช่วง'}) | ค่า |
|---|---|
| Ec = 4700√fc′ | {d_['Ec']:,.0f} MPa |
| n = Es/Ec | {d_['n']:.2f} |
| Ig | {d_['Ig'] / 1e6:,.0f} ×10⁶ mm⁴ |
| kd / Icr | {d_['kd']:.0f} mm / {d_['Icr'] / 1e6:,.0f} ×10⁶ mm⁴ |
| Mcr = 0.62√fc′·Ig/yt | {kNm(d_['Mcr']):,.1f} {mu} |
| Ma (D) / Ie | {kNm(d_['MaD']):,.1f} {mu} / {d_['IeD'] / 1e6:,.0f} ×10⁶ |
| Ma (D+L) / Ie | {kNm(d_['MaDL']):,.1f} {mu} / {d_['IeDL'] / 1e6:,.0f} ×10⁶ |
""")
            st.caption(ie_txt)
        with c2:
            okL, okT = d_["dL"] <= lim_L, d_["d_after"] <= lim_T
            st.markdown(f"""
| การโก่งตัว | ค่า (mm) | ขีดจำกัด (mm) | สถานะ |
|---|---|---|---|
| Δ ทันที DL | {d_['dD']:.2f} | | |
| Δ ทันที LL | {d_['dL']:.2f} | L/360 = {lim_L:.1f} | {'✅' if okL else '❌'} |
| λΔ = ξ/(1+50ρ′) | {d_['lam_d']:.2f} (ρ′ = {d_['rho_c'] * 100:.2f}%) | | |
| Δ ระยะยาว (ค้างนาน) | {d_['d_long']:.2f} | | |
| Δ หลังติดตั้ง = Δระยะยาว + ΔLL | {d_['d_after']:.2f} | {V('dlim')} = {lim_T:.1f} | {'✅' if okT else '❌'} |
""")
            if support == "cantilever":
                st.caption("คานยื่น: ใช้ความยาวอ้างอิง 2L สำหรับขีดจำกัด")
            st.caption("Δ = K·w·L⁴/(Ec·Ie), K จาก Δ = 5L²/48EI·[Mmid − 0.1(M1+M2)] • ξ = 2.0 (≥ 5 ปี)")


# ---- Development length ---------------------------------------------------
with tabs[5]:
    rows = []
    seen = set()
    for tag, r in results.items():
        sec, rf = r.sec, r.loc.reinf
        for A, y, face, layer, n, db in sec.bars:
            lay = getattr(rf, f"{'top' if face == 'top' else 'bot'}{layer}")
            top = face == "top" and (inp.h - y) > 300
            key = (db, top)
            sc = sec.clear_spacing(lay)
            dl = development_length(inp, db, top, sc if math.isfinite(sc) else 1e9,
                                    inp.cover + inp.stirrup_d, True)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "เหล็ก": bar_name(db), "ตำแหน่ง": "บน (top bar)" if top else ("บน" if face == "top" else "ล่าง"),
                "ψt": dl["psi_t"], "ψg": dl["psi_g"], "เงื่อนไขระยะ/ระยะหุ้มดี": "ใช่" if dl["good"] else "ไม่",
                "ld/db": round(dl["ld_db"], 1), "ld (mm)": int(math.ceil(dl["ld"] / 10) * 10),
                "ทาบต่อ Class B = 1.3ld (mm)": int(math.ceil(1.3 * dl["ld"] / 10) * 10),
            })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    ref = development_length(inp, 20.0, False, 100.0, 50.0)["ref"]
    st.caption(f"ระยะฝังยึดรับแรงดึงแบบตรง ({ref}) เหล็กไม่เคลือบ คอนกรีตน้ำหนักปกติ • ld ≥ 300 mm • "
               "ψt = 1.3 สำหรับเหล็กบนที่มีคอนกรีตเทใต้ > 300 mm • ระยะทาบ Class B = 1.3ld")


# ---- Report ----------------------------------------------------------------
with tabs[6]:
    c1, c2 = st.columns(2)
    project = c1.text_input("ชื่อโครงการ", "Project", key=K("project"))
    beam_id = c2.text_input("รหัสคาน", "B1", key=K("beam_id"))
    extra = dict(stir=V("stir"), analysis=analysis, today=date.today().isoformat())
    if analysis:
        extra.update(support=SUPPORTS[support]["name"], span=span, wD=wD, wL=wL, wu=wu, combo=combo,
                     frc=frc, defl=defl, hmin=hmin, dlim=V("dlim"), defl_ok=defl_ok)
    html = build_beam_report(project, beam_id, inp, results, CODES[code], fu, mu, wu_u, F,
                             ok_all, extra, bars_txt, unit_txt)
    st.download_button("⬇️ ดาวน์โหลดรายการคำนวณ (HTML)", html, file_name=f"{beam_id}_{code}.html",
                       mime="text/html", type="primary")
    csv = pd.DataFrame([{
        "location": r.loc.name, "top": bars_txt(r.loc.reinf, "top"), "bottom": bars_txt(r.loc.reinf, "bot"),
        "stirrup": f"{V('stir')}@{r.loc.reinf.s:.0f}", f"Mu ({mu})": kNm(abs(r.loc.Mu)),
        f"phiMn ({mu})": kNm(r.flex["phiMn"]) if r.flex else None, f"Vu ({fu})": kN(r.shear["Vu"]),
        f"phiVn ({fu})": kN(r.shear["phiVn"]), "DCR": r.dcr, "status": "OK" if r.ok else "NG",
    } for r in results.values()])
    st.download_button("⬇️ ดาวน์โหลดผลการตรวจสอบ (CSV)", csv.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{beam_id}_results.csv", mime="text/csv")
    with st.expander("ดูตัวอย่างรายงาน"):
        st.iframe(html, height=800)

st.divider()
st.caption("⚠️ โปรแกรมนี้เป็นเครื่องมือช่วยออกแบบ ผลลัพธ์ต้องได้รับการตรวจสอบโดยวิศวกรผู้มีใบอนุญาต • "
           "ไม่ครอบคลุมแรงบิด ข้อกำหนดแผ่นดินไหว (มยผ. 1301/1302, ACI Ch. 18) และคานลึก")
