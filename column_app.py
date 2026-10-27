"""Streamlit page: reinforced concrete column design per ACI 318-19.

Run the multipage app with:  streamlit run app.py
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from aci318_column import (
    BAR_SIZES, KSC_TO_MPA, TIE_SIZES, TONF_TO_KN, ColumnInput, ColumnSection,
    LoadCase, SlendernessInput, auto_select, bar_area, design,
)
from report import build_report

st.set_page_config(page_title="ออกแบบเสา ACI 318-19", page_icon="🏛️", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.6rem;}
      div[data-testid="stMetricValue"] {font-size: 1.5rem;}
      .ok-badge {background:#e6f4ea;color:#137333;padding:4px 12px;border-radius:12px;font-weight:600;}
      .ng-badge {background:#fce8e6;color:#c5221f;padding:4px 12px;border-radius:12px;font-weight:600;}
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Defaults & session state
# --------------------------------------------------------------------------
DEFAULTS = dict(
    shape="สี่เหลี่ยม", b=400.0, h=400.0, D=500.0, cover=40.0,
    fc=28.0, fy=420.0, fyt=420.0, agg=20.0,
    bar="DB20", nx=3, ny=3, n_circ=8,
    transverse="ปลอกเดี่ยว (Tied)", tie="DB10", s=200.0, legs_x=2, legs_y=2,
    sway="ค้ำยัน (Nonsway)", lu_x=3.0, lu_y=3.0, k_x=1.0, k_y=1.0,
    m1m2_x=-0.5, m1m2_y=-0.5, beta_dns=0.6, ds_x=1.0, ds_y=1.0, trans_load=False,
    unit_mat="MPa", unit_force="kN",
)
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)


def apply_suggestion(sug: dict):
    for k, v in sug.items():
        st.session_state[k] = v


# --------------------------------------------------------------------------
# Sidebar - inputs
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ ข้อมูลออกแบบ")
    c1, c2 = st.columns(2)
    unit_mat = c1.radio("หน่วยกำลังวัสดุ", ["MPa", "ksc"], key="unit_mat", horizontal=True)
    unit_force = c2.radio("หน่วยแรง", ["kN", "tonf"], key="unit_force", horizontal=True)
    mat_f = 1.0 if unit_mat == "MPa" else KSC_TO_MPA
    F = 1.0 if unit_force == "kN" else TONF_TO_KN       # user unit -> kN
    fu, mu = ("kN", "kN·m") if unit_force == "kN" else ("tonf", "tonf·m")

    with st.expander("🧱 1. หน้าตัดเสา", expanded=True):
        shape = st.radio("รูปทรงหน้าตัด", ["สี่เหลี่ยม", "วงกลม"], key="shape", horizontal=True)
        is_circ = shape == "วงกลม"
        if is_circ:
            st.number_input("เส้นผ่านศูนย์กลาง D (mm)", 200.0, 3000.0, step=50.0, key="D")
        else:
            c1, c2 = st.columns(2)
            c1.number_input("กว้าง b (แกน x, mm)", 150.0, 3000.0, step=50.0, key="b")
            c2.number_input("ลึก h (แกน y, mm)", 150.0, 3000.0, step=50.0, key="h")
        st.number_input("ระยะหุ้มถึงผิวเหล็กปลอก (mm)", 20.0, 100.0, step=5.0, key="cover",
                        help="ACI 318-19 Table 20.5.1.3.1: เสาภายในอาคาร ≥ 40 mm")

    with st.expander("🧪 2. วัสดุ", expanded=True):
        lo_fc, hi_fc = (17.0, 100.0) if unit_mat == "MPa" else (175.0, 1000.0)
        prev = st.session_state.get("_unit_mat_prev", "MPa")
        if prev != unit_mat:  # convert existing values when the unit changes
            f = 1 / KSC_TO_MPA if unit_mat == "ksc" else KSC_TO_MPA
            st.session_state.fc = round(st.session_state.fc * f, 1)
            st.session_state.fy = round(st.session_state.fy * f, 0)
            st.session_state.fyt = round(st.session_state.fyt * f, 0)
            st.session_state._unit_mat_prev = unit_mat
        st.number_input(f"fc' คอนกรีต ({unit_mat})", lo_fc, hi_fc, key="fc")
        c1, c2 = st.columns(2)
        c1.number_input(f"fy เหล็กยืน ({unit_mat})", 200.0 * (1 if unit_mat == "MPa" else 10.2),
                        700.0 * (1 if unit_mat == "MPa" else 10.2), key="fy")
        c2.number_input(f"fyt เหล็กปลอก ({unit_mat})", 200.0 * (1 if unit_mat == "MPa" else 10.2),
                        700.0 * (1 if unit_mat == "MPa" else 10.2), key="fyt")
        st.number_input("ขนาดมวลรวมโตสุด (mm)", 10.0, 40.0, step=5.0, key="agg")

    with st.expander("🔩 3. เหล็กเสริม", expanded=True):
        st.selectbox("เหล็กยืน", list(BAR_SIZES), key="bar")
        if is_circ:
            st.number_input("จำนวนเหล็กยืนทั้งหมด", 4, 60, step=1, key="n_circ")
            st.radio("เหล็กปลอก", ["ปลอกเดี่ยว (Tied)", "ปลอกเกลียว (Spiral)"], key="transverse")
        else:
            c1, c2 = st.columns(2)
            c1.number_input("จำนวนเส้น/ด้าน b", 2, 20, step=1, key="nx", help="นับรวมเหล็กมุม")
            c2.number_input("จำนวนเส้น/ด้าน h", 2, 20, step=1, key="ny", help="นับรวมเหล็กมุม")
        spiral = is_circ and st.session_state.transverse.startswith("ปลอกเกลียว")
        c1, c2 = st.columns(2)
        c1.selectbox("เหล็กปลอก", list(TIE_SIZES), key="tie")
        c2.number_input("ระยะเรียง/ระยะเกลียว s (mm)", 25.0, 600.0, step=25.0 if not spiral else 5.0, key="s")
        if not is_circ:
            c1, c2 = st.columns(2)
            c1.number_input("ขาปลอก // แกน x", 2, 12, step=1, key="legs_x", help="ต้านแรงเฉือน Vux")
            c2.number_input("ขาปลอก // แกน y", 2, 12, step=1, key="legs_y", help="ต้านแรงเฉือน Vuy")

    with st.expander("📏 4. ความชะลูด (Slenderness)"):
        st.radio("ชนิดโครงสร้าง", ["ค้ำยัน (Nonsway)", "เซ (Sway)"], key="sway", horizontal=True)
        c1, c2 = st.columns(2)
        c1.number_input("Lu แกน x (m)", 0.0, 30.0, step=0.1, key="lu_x", help="ความยาวไม่ค้ำยัน ดัดรอบแกน x")
        c2.number_input("Lu แกน y (m)", 0.0, 30.0, step=0.1, key="lu_y")
        c1.number_input("k แกน x", 0.5, 5.0, step=0.05, key="k_x")
        c2.number_input("k แกน y", 0.5, 5.0, step=0.05, key="k_y")
        if st.session_state.sway.startswith("ค้ำยัน"):
            c1.number_input("M1/M2 แกน x", -1.0, 1.0, step=0.1, key="m1m2_x",
                            help="ACI 318-19: ค่าลบ = โค้งทางเดียว (single curvature)")
            c2.number_input("M1/M2 แกน y", -1.0, 1.0, step=0.1, key="m1m2_y")
            st.checkbox("มีแรงกระทำทางข้างระหว่างจุดรองรับ (Cm = 1.0)", key="trans_load")
        else:
            c1.number_input("δs แกน x", 1.0, 3.0, step=0.05, key="ds_x", help="จากการวิเคราะห์ 6.6.4.6")
            c2.number_input("δs แกน y", 1.0, 3.0, step=0.05, key="ds_y")
        st.number_input("βdns (สัดส่วนน้ำหนักคงที่ค้างนาน)", 0.0, 1.0, step=0.05, key="beta_dns")

ss = st.session_state
inp = ColumnInput(
    shape="circular" if is_circ else "rect",
    b=ss.b, h=ss.h, D=ss.D, cover=ss.cover,
    fc=ss.fc * mat_f, fy=ss.fy * mat_f, fyt=ss.fyt * mat_f,
    bar_d=BAR_SIZES[ss.bar], nx=int(ss.nx), ny=int(ss.ny), n_circ=int(ss.n_circ),
    transverse="spiral" if spiral else "tied",
    tie_d=TIE_SIZES[ss.tie], s=ss.s, legs_x=int(ss.legs_x), legs_y=int(ss.legs_y), agg=ss.agg,
)
slend = SlendernessInput(
    sway=ss.sway.startswith("เซ"), lu_x=ss.lu_x * 1000, lu_y=ss.lu_y * 1000,
    k_x=ss.k_x, k_y=ss.k_y, m1m2_x=ss.m1m2_x, m1m2_y=ss.m1m2_y, beta_dns=ss.beta_dns,
    delta_s_x=ss.ds_x, delta_s_y=ss.ds_y, transverse_load=ss.trans_load,
)

# --------------------------------------------------------------------------
# Header & loads
# --------------------------------------------------------------------------
st.title("🏛️ ออกแบบเสาคอนกรีตเสริมเหล็ก — ACI 318-19")
st.caption("ตรวจสอบกำลังรับแรงอัดร่วมแรงดัดสองทาง (strain compatibility), ความชะลูด, แรงเฉือน "
           "และรายละเอียดเหล็กเสริม • หน่วยภายใน SI • แรงอัดเป็นบวก")

st.subheader(f"📥 แรงกระทำประลัย (Factored loads) — หน่วย {fu}, {mu}")
if "loads_df" not in ss or ss.get("loads_unit") != unit_force:
    base = pd.DataFrame({
        "กรณี": ["1.4D", "1.2D+1.6L", "1.2D+1.0L+1.0E"],
        "Pu": [1200.0, 1800.0, 1100.0],
        "Mux": [40.0, 90.0, 130.0],
        "Muy": [20.0, 45.0, 50.0],
        "Vux": [20.0, 40.0, 90.0],
        "Vuy": [15.0, 30.0, 70.0],
    })
    if "loads_df" in ss:  # unit switch: convert the existing table
        base = ss.loads_df.copy()
        f = TONF_TO_KN if unit_force == "kN" else 1 / TONF_TO_KN
        for col in ["Pu", "Mux", "Muy", "Vux", "Vuy"]:
            base[col] = (base[col] * f).round(2)
    ss.loads_df = base
    ss.loads_unit = unit_force

loads_df = st.data_editor(
    ss.loads_df, num_rows="dynamic", width="stretch", key="loads_editor",
    column_config={
        "กรณี": st.column_config.TextColumn("กรณีน้ำหนัก", required=True),
        "Pu": st.column_config.NumberColumn(f"Pu ({fu})", help="แรงอัด +, แรงดึง −", format="%.1f"),
        "Mux": st.column_config.NumberColumn(f"Mux ({mu})", help="โมเมนต์รอบแกน x (ด้าน h)", format="%.1f"),
        "Muy": st.column_config.NumberColumn(f"Muy ({mu})", help="โมเมนต์รอบแกน y (ด้าน b)", format="%.1f"),
        "Vux": st.column_config.NumberColumn(f"Vux ({fu})", help="แรงเฉือนตามแนวแกน x", format="%.1f"),
        "Vuy": st.column_config.NumberColumn(f"Vuy ({fu})", help="แรงเฉือนตามแนวแกน y", format="%.1f"),
    },
)
loads_df = loads_df.dropna(subset=["Pu"]).fillna(0.0)
ss.loads_df = loads_df.reset_index(drop=True)
loads = [
    LoadCase(str(r["กรณี"]), r["Pu"] * F * 1e3, r["Mux"] * F * 1e6, r["Muy"] * F * 1e6,
             r["Vux"] * F * 1e3, r["Vuy"] * F * 1e3)
    for _, r in loads_df.iterrows()
]
if not loads:
    st.warning("กรุณาใส่แรงกระทำอย่างน้อย 1 กรณี")
    st.stop()


# --------------------------------------------------------------------------
# Compute
# --------------------------------------------------------------------------
@st.cache_data(show_spinner="กำลังสร้าง interaction surface ...")
def get_surface(inp: ColumnInput):
    return ColumnSection(inp).surface(72, 60)


try:
    surf = get_surface(inp)
    sec, surf, cases, detail = design(inp, slend, loads, surf=surf)
except (ValueError, ZeroDivisionError) as exc:
    st.error(f"ข้อมูลหน้าตัดไม่ถูกต้อง: {exc}")
    st.stop()

kN = lambda n: n / 1e3 / F           # N -> user force unit
kNm = lambda nmm: nmm / 1e6 / F      # N*mm -> user moment unit

detail_ok = all(d["ok"] for d in detail)
strength_ok = all(c.ok for c in cases)
all_ok = detail_ok and strength_ok
max_dcr = max(c.dcr for c in cases)
gov = max(cases, key=lambda c: c.dcr)

# --------------------------------------------------------------------------
# Summary strip
# --------------------------------------------------------------------------
st.divider()
badge = '<span class="ok-badge">✅ ผ่านทุกข้อ (OK)</span>' if all_ok else '<span class="ng-badge">❌ ไม่ผ่าน (NG)</span>'
st.markdown(f"### ผลการออกแบบ &nbsp; {badge}", unsafe_allow_html=True)
m = st.columns(5)
m[0].metric("เหล็กยืน", f"{sec.n_bars}-{ss.bar}", f"Ast = {sec.Ast:,.0f} mm²", delta_color="off", delta_arrow="off")
m[1].metric("ρg", f"{sec.rho * 100:.2f} %", "ช่วง 1–8 %", delta_color="off", delta_arrow="off")
m[2].metric("φPn,max", f"{kN(sec.phiPn_max):,.0f} {fu}", f"φ = {sec.phi_c}", delta_color="off", delta_arrow="off")
m[3].metric("D/C สูงสุด", f"{max_dcr:.2f}" if math.isfinite(max_dcr) else "∞",
            f"กรณี {gov.case.name}", delta_color="inverse" if max_dcr > 1 else "off", delta_arrow="off")
m[4].metric("β1 / Ec", f"{sec.beta1:.3f}", f"Ec = {sec.Ec:,.0f} MPa", delta_color="off", delta_arrow="off")
if max_dcr <= 1:
    st.progress(min(max_dcr, 1.0), text=f"อัตราส่วนการใช้งาน {max_dcr * 100:.0f}%")
else:
    st.error(f"หน้าตัดรับแรงไม่พอ: D/C = {max_dcr:.2f} ในกรณี {gov.case.name} — "
             "เพิ่มขนาดหน้าตัด/เหล็กเสริม หรือใช้ปุ่ม 'ช่วยเลือกเหล็กเสริม' ด้านล่าง")

tabs = st.tabs(["📋 สรุปผล", "📈 Interaction P–M", "🔄 Biaxial Mx–My", "🧱 หน้าตัด",
                "📏 ความชะลูด", "✂️ แรงเฉือน", "📝 รายงาน"])


def fmt_dcr(x):
    return f"{x:.3f}" if math.isfinite(x) else "∞"


def style_status(df: pd.DataFrame, col: str = "สถานะ"):
    return df.style.format(precision=1).map(lambda v: "color:#137333;font-weight:600" if v == "OK"
                        else "color:#c5221f;font-weight:600", subset=[col])


# ---- Summary -------------------------------------------------------------
with tabs[0]:
    st.markdown("#### กำลังรับแรงอัดร่วมแรงดัด (Axial + Biaxial bending)")
    rows = []
    for c in cases:
        rows.append({
            "กรณี": c.case.name,
            f"Pu ({fu})": round(kN(c.case.Pu), 1),
            f"Mcx ({mu})": round(kNm(c.Mcx), 1) if math.isfinite(c.Mcx) else "∞",
            f"Mcy ({mu})": round(kNm(c.Mcy), 1) if math.isfinite(c.Mcy) else "∞",
            f"φMnx ({mu})": round(kNm(c.phiMnx), 1),
            f"φMny ({mu})": round(kNm(c.phiMny), 1),
            f"φMn ทิศ Mu ({mu})": round(kNm(c.phiMn_dir), 1),
            "D/C แรงอัด": fmt_dcr(c.dcr_axial),
            "D/C โมเมนต์": fmt_dcr(c.dcr_moment),
            "D/C เฉือน": fmt_dcr(max(c.shear_x["dcr"], c.shear_y["dcr"])),
            "สถานะ": "OK" if c.ok else "NG",
        })
    st.dataframe(style_status(pd.DataFrame(rows)), width="stretch", hide_index=True)
    st.caption("Mcx, Mcy = โมเมนต์ออกแบบหลังขยายผลความชะลูด • D/C โมเมนต์ = |Mu| / φMn "
               "ในทิศทางเดียวกันที่ระดับ Pu เดียวกัน (load contour จาก strain compatibility)")

    st.markdown("#### รายละเอียดเหล็กเสริม (Detailing)")
    ddf = pd.DataFrame([{"ข้อกำหนด": d["clause"], "รายการ": d["item"], "ต้องการ": d["required"],
                         "ที่ใช้": d["provided"], "สถานะ": "OK" if d["ok"] else "NG"} for d in detail])
    st.dataframe(style_status(ddf), width="stretch", hide_index=True)

    with st.expander("🔍 ช่วยเลือกเหล็กเสริมอัตโนมัติ (หาเหล็กยืนน้อยที่สุดที่ผ่าน)"):
        st.write("ค้นหาขนาดและจำนวนเหล็กยืนที่มีพื้นที่น้อยที่สุดซึ่งผ่านกำลังรับแรงทุกกรณี "
                 "และข้อกำหนดระยะช่องว่าง/ρg โดยคงขนาดหน้าตัดและเหล็กปลอกเดิม")
        if st.button("เริ่มค้นหา", type="primary"):
            with st.spinner("กำลังค้นหา ..."):
                best = auto_select(inp, slend, loads)
            if best is None:
                st.error("ไม่พบชุดเหล็กเสริมที่ผ่าน — ควรเพิ่มขนาดหน้าตัดหรือกำลังคอนกรีต")
            else:
                bsec = ColumnSection(best)
                bar_name = next(k for k, v in BAR_SIZES.items() if v == best.bar_d)
                sug = {"bar": bar_name}
                if best.is_circular:
                    sug["n_circ"] = best.n_circ
                    txt = f"{best.n_circ}-{bar_name}"
                else:
                    sug.update(nx=best.nx, ny=best.ny, legs_x=best.legs_x, legs_y=best.legs_y)
                    txt = (f"{bsec.n_bars}-{bar_name} (ด้าน b {best.nx} เส้น, ด้าน h {best.ny} เส้น, "
                           f"ขาปลอก {best.legs_x}×{best.legs_y})")
                st.success(f"แนะนำ: **{txt}** — Ast = {bsec.Ast:,.0f} mm², ρg = {bsec.rho * 100:.2f}%")
                st.button("ใช้ค่านี้", on_click=apply_suggestion, args=(sug,))


# ---- Plot helpers ----------------------------------------------------------
def uniaxial(axis: str):
    """Return (M, P, phiM, phiP) for bending about the given axis, both directions."""
    if axis == "x":
        pos, neg, key = sec.curve(math.pi / 2), sec.curve(3 * math.pi / 2), "Mx"
    else:
        pos, neg, key = sec.curve(0.0), sec.curve(math.pi), "My"
    M = np.concatenate([pos[key], neg[key][::-1]])
    P = np.concatenate([pos["P"], neg["P"][::-1]])
    phiM = np.concatenate([pos["phi" + key], neg["phi" + key][::-1]])
    phiP = np.concatenate([pos["phiP"], neg["phiP"][::-1]])
    return M, P, phiM, phiP


def pm_figure(axis: str):
    M, P, phiM, phiP = uniaxial(axis)
    fig = go.Figure()
    fig.add_scatter(x=kNm(M), y=kN(P), name="Pn–Mn (nominal)", mode="lines",
                    line=dict(color="#9aa0a6", dash="dash"))
    fig.add_scatter(x=kNm(phiM), y=kN(phiP), name="φPn–φMn (design)", mode="lines",
                    line=dict(color="#1a73e8", width=3), fill="toself", fillcolor="rgba(26,115,232,0.08)")
    xs = [kNm(c.Mcx if axis == "x" else c.Mcy) for c in cases]
    ys = [kN(c.case.Pu) for c in cases]
    colors = ["#137333" if c.ok else "#c5221f" for c in cases]
    fig.add_scatter(x=xs, y=ys, mode="markers+text", name="แรงกระทำ",
                    text=[c.case.name for c in cases], textposition="top right",
                    marker=dict(size=11, color=colors, symbol="diamond", line=dict(width=1, color="white")))
    fig.add_hline(y=kN(sec.phiPn_max), line=dict(color="#e37400", dash="dot"),
                  annotation_text="φPn,max", annotation_position="top left")
    fig.update_layout(
        title=f"ดัดรอบแกน {axis} ({'M' + axis})", height=520, hovermode="closest",
        xaxis_title=f"M{axis} ({mu})", yaxis_title=f"P ({fu})",
        legend=dict(orientation="h", y=-0.15), margin=dict(l=10, r=10, t=50, b=10),
    )
    fig.add_vline(x=0, line=dict(color="#bdc1c6", width=1))
    fig.add_hline(y=0, line=dict(color="#bdc1c6", width=1))
    return fig


with tabs[1]:
    st.info("แผนภาพปฏิสัมพันธ์แกนเดียว — จุดแรงกระทำแสดงโมเมนต์แต่ละแกนแยกกัน; "
            "การตรวจสอบจริงใช้ biaxial contour ในแท็บถัดไป", icon="ℹ️")
    if is_circ:
        st.plotly_chart(pm_figure("x"), width="stretch")
    else:
        c1, c2 = st.columns(2)
        c1.plotly_chart(pm_figure("x"), width="stretch")
        c2.plotly_chart(pm_figure("y"), width="stretch")
    Mx_, Px_, phiMx_, phiPx_ = uniaxial("x")
    i_bal = int(np.argmax(phiMx_))
    st.markdown(
        f"- Po = **{kN(sec.Po):,.0f} {fu}**, Pn,max = {sec.alpha_max:.2f}Po = **{kN(sec.Pn_max):,.0f} {fu}**, "
        f"φPn,max = **{kN(sec.phiPn_max):,.0f} {fu}**\n"
        f"- แรงดึงล้วน φPnt = **{kN(sec.phiPnt):,.0f} {fu}**\n"
        f"- โมเมนต์สูงสุดบนแผนภาพ (แกน x) φMn = **{kNm(phiMx_[i_bal]):,.1f} {mu}** "
        f"ที่ φPn = {kN(phiPx_[i_bal]):,.0f} {fu}"
    )

with tabs[2]:
    names = [c.case.name for c in cases]
    sel = st.selectbox("เลือกกรณีน้ำหนัก", names, index=names.index(gov.case.name))
    c = cases[names.index(sel)]
    col1, col2 = st.columns([3, 2])
    fig = go.Figure()
    if len(c.contour) >= 3:
        order = np.argsort(np.arctan2(c.contour[:, 1], c.contour[:, 0]))
        ct = c.contour[order]
        ct = np.vstack([ct, ct[:1]])
        fig.add_scatter(x=kNm(ct[:, 0]), y=kNm(ct[:, 1]), mode="lines", name=f"φMn ที่ Pu = {kN(c.case.Pu):,.0f}",
                        line=dict(color="#1a73e8", width=3), fill="toself", fillcolor="rgba(26,115,232,0.08)")
    if math.isfinite(c.Mcx) and math.isfinite(c.Mcy):
        fig.add_scatter(x=[0, kNm(c.Mcx)], y=[0, kNm(c.Mcy)], mode="lines+markers", name="Mu (ออกแบบ)",
                        line=dict(color="#c5221f" if not c.ok else "#137333", width=3),
                        marker=dict(size=[0, 12], symbol="diamond"))
        mag = math.hypot(c.Mcx, c.Mcy)
        if mag > 0 and c.phiMn_dir > 0:
            ux, uy = c.Mcx / mag, c.Mcy / mag
            fig.add_scatter(x=[kNm(ux * c.phiMn_dir)], y=[kNm(uy * c.phiMn_dir)], mode="markers",
                            name="φMn ในทิศ Mu", marker=dict(size=10, color="#e37400"))
    fig.update_layout(height=520, xaxis_title=f"Mx ({mu})", yaxis_title=f"My ({mu})",
                      yaxis=dict(scaleanchor="x", scaleratio=1), legend=dict(orientation="h", y=-0.15),
                      margin=dict(l=10, r=10, t=30, b=10))
    col1.plotly_chart(fig, width="stretch")
    with col2:
        st.markdown(f"**กรณี {c.case.name}**")
        st.markdown(
            f"""
| รายการ | ค่า |
|---|---|
| Pu | {kN(c.case.Pu):,.1f} {fu} |
| Mcx / Mcy | {kNm(c.Mcx):,.1f} / {kNm(c.Mcy):,.1f} {mu} |
| \\|Mu\\| | {kNm(math.hypot(c.Mcx, c.Mcy)):,.1f} {mu} |
| φMn ทิศเดียวกัน | {kNm(c.phiMn_dir):,.1f} {mu} |
| φMnx / φMny (uniaxial) | {kNm(c.phiMnx):,.1f} / {kNm(c.phiMny):,.1f} {mu} |
| D/C โมเมนต์ | **{fmt_dcr(c.dcr_moment)}** |
| D/C แรงอัด (Pu/φPn,max) | **{fmt_dcr(c.dcr_axial)}** |
"""
        )
        if len(c.contour) < 3:
            st.error("Pu อยู่นอกขอบเขตแผนภาพปฏิสัมพันธ์ (เกิน φPn,max หรือแรงดึงเกิน φPnt)")
    with st.expander("🌐 Interaction surface 3 มิติ"):
        f3 = go.Figure()
        for i in range(0, surf["phiP"].shape[0], 3):
            f3.add_scatter3d(x=kNm(surf["phiMx"][i]), y=kNm(surf["phiMy"][i]), z=kN(surf["phiP"][i]),
                             mode="lines", line=dict(color="#1a73e8", width=2), showlegend=False)
        f3.add_scatter3d(x=[kNm(k.Mcx) for k in cases], y=[kNm(k.Mcy) for k in cases],
                         z=[kN(k.case.Pu) for k in cases], mode="markers+text",
                         text=[k.case.name for k in cases], name="แรงกระทำ",
                         marker=dict(size=5, color=["#137333" if k.ok else "#c5221f" for k in cases]))
        f3.update_layout(height=600, scene=dict(xaxis_title=f"φMnx ({mu})", yaxis_title=f"φMny ({mu})",
                                                zaxis_title=f"φPn ({fu})"), margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(f3, width="stretch")

# ---- Section drawing -------------------------------------------------------
with tabs[3]:
    fig = go.Figure()
    tie_off = inp.cover + inp.tie_d / 2
    if is_circ:
        R = inp.D / 2
        fig.add_shape(type="circle", x0=-R, y0=-R, x1=R, y1=R,
                      fillcolor="#e8eaed", line=dict(color="#5f6368", width=2))
        rt = R - tie_off
        fig.add_shape(type="circle", x0=-rt, y0=-rt, x1=rt, y1=rt,
                      line=dict(color="#e37400", width=max(inp.tie_d / 4, 2), dash="dot" if spiral else "solid"))
        W = H = inp.D
    else:
        W, H = inp.b, inp.h
        fig.add_shape(type="rect", x0=-W / 2, y0=-H / 2, x1=W / 2, y1=H / 2,
                      fillcolor="#e8eaed", line=dict(color="#5f6368", width=2))
        fig.add_shape(type="rect", x0=-W / 2 + tie_off, y0=-H / 2 + tie_off, x1=W / 2 - tie_off,
                      y1=H / 2 - tie_off, line=dict(color="#e37400", width=max(inp.tie_d / 4, 2)))
        # cross-ties (interior legs)
        xs = np.unique(np.round(sec.bars[:, 0], 6))
        ys = np.unique(np.round(sec.bars[:, 1], 6))
        for xi in np.linspace(xs[0], xs[-1], inp.legs_y)[1:-1] if inp.legs_y > 2 else []:
            xb = xs[np.argmin(abs(xs - xi))]
            fig.add_shape(type="line", x0=xb, y0=-H / 2 + tie_off, x1=xb, y1=H / 2 - tie_off,
                          line=dict(color="#e37400", width=2, dash="dash"))
        for yi in np.linspace(ys[0], ys[-1], inp.legs_x)[1:-1] if inp.legs_x > 2 else []:
            yb = ys[np.argmin(abs(ys - yi))]
            fig.add_shape(type="line", x0=-W / 2 + tie_off, y0=yb, x1=W / 2 - tie_off, y1=yb,
                          line=dict(color="#e37400", width=2, dash="dash"))
    r = inp.bar_d / 2
    for x, y in sec.bars:
        fig.add_shape(type="circle", x0=x - r, y0=y - r, x1=x + r, y1=y + r,
                      fillcolor="#3c4043", line=dict(color="#202124"))
    fig.add_scatter(x=sec.bars[:, 0], y=sec.bars[:, 1], mode="markers", marker=dict(size=1, opacity=0),
                    hovertext=[f"bar {i + 1}: ({x:.0f}, {y:.0f})" for i, (x, y) in enumerate(sec.bars)],
                    hoverinfo="text", showlegend=False)
    pad = 0.18 * max(W, H)
    fig.add_annotation(x=0, y=-H / 2 - pad * 0.45, text=f"{'D' if is_circ else 'b'} = {W:.0f} mm",
                       showarrow=False, font=dict(size=14))
    if not is_circ:
        fig.add_annotation(x=-W / 2 - pad * 0.45, y=0, text=f"h = {H:.0f} mm", textangle=-90,
                           showarrow=False, font=dict(size=14))
    fig.add_annotation(x=W / 2 + pad * 0.6, y=0, ax=-40, ay=0, text="x", showarrow=True, arrowhead=2)
    fig.add_annotation(x=0, y=H / 2 + pad * 0.6, ax=0, ay=40, text="y", showarrow=True, arrowhead=2)
    fig.update_xaxes(range=[-W / 2 - pad, W / 2 + pad], visible=False)
    fig.update_yaxes(range=[-H / 2 - pad, H / 2 + pad], visible=False, scaleanchor="x", scaleratio=1)
    fig.update_layout(height=520, plot_bgcolor="white", margin=dict(l=0, r=0, t=10, b=0))
    c1, c2 = st.columns([3, 2])
    c1.plotly_chart(fig, width="stretch")
    with c2:
        tie_txt = "ปลอกเกลียว" if spiral else "ปลอก"
        st.markdown(f"""
**สรุปหน้าตัด**

| รายการ | ค่า |
|---|---|
| ขนาด | {'Ø' + f'{inp.D:.0f}' if is_circ else f'{inp.b:.0f} × {inp.h:.0f}'} mm |
| Ag | {sec.Ag:,.0f} mm² |
| เหล็กยืน | {sec.n_bars}-{ss.bar} (Ast = {sec.Ast:,.0f} mm²) |
| ρg | {sec.rho * 100:.2f} % |
| {tie_txt} | {ss.tie} @ {inp.s:.0f} mm |
| ขาปลอก (x × y) | {'-' if is_circ else f'{inp.legs_x} × {inp.legs_y}'} |
| ระยะหุ้ม | {inp.cover:.0f} mm |
| ระยะช่องว่างเหล็กยืนน้อยสุด | {sec.clear_spacing():.0f} mm |
| fc' / fy / fyt | {inp.fc:.1f} / {inp.fy:.0f} / {inp.fyt:.0f} MPa |
""")

# ---- Slenderness -----------------------------------------------------------
with tabs[4]:
    st.markdown(f"**ชนิดโครงสร้าง:** {'เซ (Sway)' if slend.sway else 'ค้ำยัน (Nonsway)'} • "
                f"EI eff = 0.4EcIg/(1+βdns), βdns = {slend.beta_dns}")
    rows = []
    for c in cases:
        for s_ in (c.slx, c.sly):
            rows.append({
                "กรณี": c.case.name, "แกน": s_["axis"],
                "kLu/r": round(s_["klu_r"], 1), "ขีดจำกัด": round(s_["limit"], 1),
                "ชะลูด?": "ใช่" if s_["slender"] else "ไม่",
                f"Pc ({fu})": round(kN(s_["Pc"]), 0) if s_["Pc"] else "-",
                "Cm": round(s_["Cm"], 3) if s_["Cm"] is not None else "-",
                f"M2,min ({mu})": round(kNm(s_["M2min"]), 1) if s_["M2min"] is not None else "-",
                "δ": round(s_["delta"], 3) if math.isfinite(s_["delta"]) else "∞",
                f"Mu ({mu})": round(kNm(s_["Mu"]), 1),
                f"Mc ({mu})": round(kNm(s_["Mc"]), 1) if math.isfinite(s_["Mc"]) else "∞",
                "สถานะ": "OK" if s_["ok"] else "NG",
                "หมายเหตุ": s_["note"],
            })
    st.dataframe(style_status(pd.DataFrame(rows)), width="stretch", hide_index=True)
    st.caption("6.2.5.1: Nonsway kLu/r ≤ 34 + 12(M1/M2) ≤ 40 • Sway kLu/r ≤ 22 • "
               "r = 0.3h (สี่เหลี่ยม), 0.25D (วงกลม) • δ = Cm / (1 − Pu/0.75Pc) ≥ 1.0 • "
               "M2,min = Pu(15 + 0.03h) mm")

# ---- Shear -----------------------------------------------------------------
with tabs[5]:
    rows = []
    for c in cases:
        for sh in (c.shear_x, c.shear_y):
            rows.append({
                "กรณี": c.case.name, "ทิศ": "Vux" if sh["direction"] == "x" else "Vuy",
                "bw (mm)": round(sh["bw"]), "d (mm)": round(sh["d"]),
                "Av (mm²)": round(sh["Av"], 1), "Av,min (mm²)": round(sh["Av_min"], 1),
                f"Vc ({fu})": round(kN(sh["Vc"]), 1), f"Vs ({fu})": round(kN(sh["Vs"]), 1),
                f"φVn ({fu})": round(kN(sh["phiVn"]), 1), f"Vu ({fu})": round(kN(sh["Vu"]), 1),
                "s,max (mm)": round(sh["s_max"]), "สมการ Vc": sh["eq"],
                "D/C": fmt_dcr(sh["dcr"]), "สถานะ": "OK" if sh["ok"] else "NG",
            })
    st.dataframe(style_status(pd.DataFrame(rows)), width="stretch", hide_index=True)
    st.caption("Vc = [0.17λ√fc' + Nu/(6Ag)]·bw·d (Table 22.5.5.1a, Nu/6Ag ≤ 0.05fc') • "
               "Vs = Av·fyt·d/s (fyt ≤ 420 MPa) • φ = 0.75 • วงกลม: bw = D, d = 0.8D • "
               "ต้องใช้ Av,min เมื่อ Vu > 0.5φVc (10.6.2.1)")

# ---- Report ----------------------------------------------------------------
with tabs[6]:
    project = st.text_input("ชื่อโครงการ", "Project")
    col_id = st.text_input("รหัสเสา", "C1")
    html = build_report(project, col_id, ss.bar, ss.tie, inp, slend, sec, cases, detail,
                        fu, mu, F, all_ok, date.today().isoformat())
    st.download_button("⬇️ ดาวน์โหลดรายงาน (HTML)", html, file_name=f"{col_id}_ACI318-19.html",
                       mime="text/html", type="primary")
    csv = pd.DataFrame([{
        "case": c.case.name, f"Pu ({fu})": kN(c.case.Pu), f"Mcx ({mu})": kNm(c.Mcx),
        f"Mcy ({mu})": kNm(c.Mcy), f"phiMn_dir ({mu})": kNm(c.phiMn_dir), "DCR_axial": c.dcr_axial,
        "DCR_moment": c.dcr_moment, "status": "OK" if c.ok else "NG"} for c in cases])
    st.download_button("⬇️ ดาวน์โหลดผลการตรวจสอบ (CSV)", csv.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{col_id}_results.csv", mime="text/csv")
    with st.expander("ดูตัวอย่างรายงาน"):
        st.iframe(html, height=800)

st.divider()
st.caption("⚠️ โปรแกรมนี้เป็นเครื่องมือช่วยออกแบบ ผลลัพธ์ต้องได้รับการตรวจสอบโดยวิศวกรผู้มีใบอนุญาต • "
           "ไม่ครอบคลุมข้อกำหนดแผ่นดินไหวพิเศษ (Chapter 18)")
