"""Printable HTML calculation sheet for the continuous-beam page (OUTPUT sheet)."""
from __future__ import annotations

import html

from continuous_beam import min_depth


def _f(v, nd=2):
    return "-" if v is None else f"{_z(v):,.{nd}f}"


def _z(v: float) -> float:
    """Drop floating-point noise such as -1e-15 so it does not print as -0.00."""
    return 0.0 if abs(v) < 1e-9 else v


def _ok(flag: bool, yes="OK", no="NG") -> str:
    return f'<span class="ok">{yes}</span>' if flag else f'<span class="ng">{no}</span>'


def _location(st, sm, r, neg: bool) -> str:
    f, s = r["flex"], r["shear"]
    req = f["neg"] if neg else f["pos_"]
    cap = f["cap_neg"] if neg else f["cap_pos"]
    d = f["d_neg"] if neg else f["d_pos"]
    dp = f["dp_bot"] if neg else f["dp_top"]
    Mu = f["Mneg"] if neg else f["Mpos"]
    As_t, As_c = (f["As_top"], f["As_bot"]) if neg else (f["As_bot"], f["As_top"])
    tens = f["top_txt"] if neg else f["bot_txt"]
    comp = f["bot_txt"] if neg else f["top_txt"]
    asp = "เพิ่ม h" if req["need_h"] else _f(req["Asp"])
    return f"""
<tr><td>{r['pos']}</td><td>{'M−' if neg else 'M+'}</td><td>{_f(Mu * 1000, 0)}</td><td>{_f(d)}</td>
<td>{_f(req['phiMn1'] * 1000, 0)}</td><td>{req['type']}</td>
<td>{_f(req['rho'], 5) if req['rho'] is not None else '-'}</td><td>{_f(req['As'])}</td><td>{asp}</td>
<td>{tens} ({_f(As_t)})</td><td>{comp} ({_f(As_c)})</td><td>{_f(cap['c'])}</td><td>{_f(cap['fsp'], 0)}</td>
<td>{cap['eps_t']:.4f}</td><td>{cap['phi']:.3f}</td><td>{_f(cap['phiMn'] * 1000, 0)}</td>
<td>{_ok(cap['phiMn'] >= Mu - 1e-4 and cap['ductile'])}</td></tr>"""


def _items_table(load_items, i, esc) -> str:
    """Load items of span i: input (formulas kept) and the resulting loads."""
    rows = [(it, res) for it, res in (load_items or []) if int(it.get("span") or 0) == i]
    if not rows:
        return ""
    def r3(res, f):
        v = res.get(f)
        if v is None:
            return ""
        return f"{v[0]:.3f}→{v[1]:.3f}" if isinstance(v, tuple) else f"{v:.3f}"
    body = "".join(
        f"<tr><td style='text-align:left'>{esc(it.get('name') or '')}</td><td>{esc(it.get('kind'))}</td>"
        f"<td>{esc(it.get('S'))}{(' × ' + esc(it.get('L'))) if it.get('L') else ''}</td><td>{esc(it.get('t'))}</td>"
        f"<td>{esc(it.get('DL'))}</td><td>{esc(it.get('LL'))}</td><td>{esc(it.get('WU'))}</td>"
        f"<td>{esc(it.get('a'))}{('–' + esc(it.get('b'))) if it.get('b') else ''}</td>"
        f"<td>{r3(res, 'DL')}</td><td>{r3(res, 'LL')}</td><td>{r3(res, 'WU')}</td>"
        f"<td style='text-align:left'>{esc(res.get('error') or res.get('note') or '')}</td></tr>"
        for it, res in rows)
    return f"""<h3>น้ำหนักบรรทุกบนคาน (ไม่รวมน้ำหนักคาน)</h3>
<table><tr><th>รายการ</th><th>ชนิด</th><th>S × L (m)</th><th>t (cm)</th><th>DL</th><th>LL</th><th>Wu</th><th>a–b (m)</th>
<th>→ DL</th><th>→ LL</th><th>→ Wu</th><th>หมายเหตุ</th></tr>{body}</table>"""


def build_report(st, spans, nodes, summary, reactions, rows, project, load_items=None, unit="t") -> str:
    esc = lambda v: html.escape(str(v or ""))
    nS = len(spans)
    span_html = []
    for sm in summary:
        i = sm["span"]
        md = min_depth(st, nodes, i, nS, spans[i - 1])
        locs = [r for r in rows if r["span"] == i]
        flex_rows = "".join(_location(st, sm, r, neg) for r in locs for neg in (True, False)
                            if (r["flex"]["Mneg"] if neg else r["flex"]["Mpos"]) > 0.0001)
        shear_rows = "".join(
            f"<tr><td>{r['pos']}</td><td>{_f(r['shear']['Vu'] * 1000, 0)}</td><td>{_f(r['shear']['phiVc'] * 1000, 0)}</td>"
            f"<td>{_f(r['shear']['phiVs_req'] * 1000, 0)}</td><td>{_f(r['shear']['phiVs_max'] * 1000, 0)}</td>"
            f"<td>{_f(r['shear']['s_str'], 1)}</td><td>{_f(r['shear']['s_max'], 1)}</td>"
            f"<td>{_f(r['shear']['s_avmin'], 1)}</td><td>{esc(r['shear']['label'])}</td>"
            f"<td>{_ok(r['shear']['ok'])}</td></tr>" for r in locs)
        summ = " | ".join(f"{r['pos']}: บน {r['flex']['top_txt']} / ล่าง {r['flex']['bot_txt']} / "
                          f"{r['shear']['label']}" for r in locs)
        ok = all(r["ok"] for r in locs)
        span_html.append(f"""
<section class="page">
<h2>ช่วงที่ {i} — {esc(spans[i - 1].name)} : {sm['b']:g}×{sm['h']:g} cm, L = {sm['L']:g} m ({md['kind']})
 &nbsp; {_ok(ok, 'ผ่าน', 'ไม่ผ่าน')}</h2>
<p class="meta">d = {sm['d']:.1f} cm • b/h = {sm['b'] / sm['h']:.2f} • hmin = L/{md['div']:g}·(0.4 + fy/7000)
 = {md['hmin']:.1f} cm → {_ok(md['ok'], 'OK', 'ตรวจการแอ่นตัว')} •
 M ซ้าย {_f(sm['ML_min'])}/{_f(sm['ML_max'])}, M+ {_f(sm['Mpos_max'])} (x = {sm['Mpos_x']:.2f} m),
 M ขวา {_f(sm['MR_min'])}/{_f(sm['MR_max'])} t-m • Vu {_f(sm['Vu_left'])} / {_f(sm['Vu_mid'])} / {_f(sm['Vu_right'])} t</p>
{_items_table(load_items, i, esc)}
<h3>ดัด (kg-m, cm, cm²)</h3>
<table><tr><th>ตำแหน่ง</th><th>M</th><th>Mu</th><th>d</th><th>φMn1 (ρmax)</th><th>ชนิด</th><th>ρ</th>
<th>As req</th><th>As' req</th><th>เหล็กรับแรงดึง</th><th>เหล็กรับแรงอัด</th><th>c</th><th>fs'</th><th>εt</th>
<th>φ</th><th>φMn</th><th>ตรวจ</th></tr>{flex_rows or '<tr><td colspan=17>ไม่มีโมเมนต์</td></tr>'}</table>
<h3>เฉือน (kg, cm)</h3>
<table><tr><th>โซน</th><th>Vu ที่ d</th><th>φVc</th><th>φVs req</th><th>φVs max</th><th>s กำลัง</th><th>s max</th>
<th>s Av,min</th><th>เหล็กปลอก</th><th>ตรวจ</th></tr>{shear_rows}</table>
<p class="meta"><b>สรุป:</b> {esc(summ)}</p>
</section>""")

    react = "".join(
        f"<tr><td>{r['node']}</td><td>{r['X']:.2f}</td><td>{r['kind']}</td><td>{_f(r['RD'])}</td>"
        f"<td>{_f(r['RL'])}</td><td>{_f(r['Ru_max'])}</td><td>{_f(r['Ru_min'])}</td>"
        f"<td>{_f(r['Mu_max'])}</td><td>{_f(r['Mu_min'])}</td></tr>" for r in reactions)
    tot = []
    for i in range(1, nS + 1):
        L_, M_, R_ = [x for x in rows if x["span"] == i]
        tot.append(f"<tr><td>{i}</td><td>{L_['flex']['b']:g}×{L_['flex']['h']:g}</td><td>{L_['flex']['top_txt']}</td>"
                   f"<td>{M_['flex']['bot_txt']}</td><td>{R_['flex']['top_txt']}</td>"
                   f"<td>{L_['shear']['label']}</td><td>{M_['shear']['label']}</td><td>{R_['shear']['label']}</td>"
                   f"<td>{_ok(all(x['ok'] for x in (L_, M_, R_)), 'ผ่าน', 'ไม่ผ่าน')}</td></tr>")
    p = {k: esc(v) for k, v in project.items()}
    duct = (f"ρ − ρ'fs'/fy ≤ 0.75ρb = {st.rhomax:.5f}" if st.is99 else "εt ≥ 0.004 (ACI 318-19)")
    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8"><title>{p['member'] or 'Beam'} – Beam Design</title>
<style>
 @page {{ size: A4; margin: 12mm; }}
 body {{font-family:'Sarabun','Segoe UI',sans-serif; margin:24px; color:#202124; background:#fff; font-size:12px;}}
 h1 {{font-size:19px; margin:0 0 4px;}} h2 {{font-size:15px; border-bottom:2px solid #1a73e8; padding-bottom:3px; margin-top:22px;}}
 h3 {{font-size:13px; margin:12px 0 4px;}}
 table {{border-collapse:collapse; width:100%; margin-top:4px;}}
 th, td {{border:1px solid #dadce0; padding:3px 5px; text-align:center;}}
 th {{background:#f1f3f4;}} .meta {{color:#3c4043; margin:4px 0;}}
 .head td {{text-align:left; border:none; padding:2px 6px;}}
 .ok {{color:#137333; font-weight:700;}} .ng {{color:#c5221f; font-weight:700;}}
 .page {{page-break-inside: avoid;}}
 .sign td {{border:none; text-align:left; padding:14px 6px 2px;}}
</style></head><body>
<h1>การออกแบบคาน ค.ส.ล. วิธีกำลัง (SDM) – Singly &amp; Doubly Reinforced</h1>
<table class="head">
<tr><td><b>Project</b> {p['project']}</td><td><b>Date</b> {p['date']}</td></tr>
<tr><td><b>Location</b> {p['location']}</td><td><b>Job No.</b> {p['job']}</td></tr>
<tr><td><b>Member</b> {p['member']}</td><td><b>Type</b> {p['type']}</td></tr>
</table>
<h2>Design Parameter</h2>
<table><tr><th>fy (ksc)</th><th>fc' (ksc)</th><th>β1</th><th>φ bending</th><th>φ shear</th><th>fy stirrup (ksc)</th>
<th>Es (ksc)</th><th>ρb</th><th>ρmax</th><th>ρmin</th><th>มาตรฐาน</th></tr>
<tr><td>{st.fy:,.0f}</td><td>{st.fc:,.0f}</td><td>{st.beta1:.3f}</td><td>{st.phib}</td><td>{st.phiv}</td>
<td>{st.fys:,.0f}</td><td>{st.Es:,.0f}</td><td>{st.rhob:.5f}</td><td>{st.rhomax:.5f}</td><td>{st.rhomin:.5f}</td>
<td>{esc(st.code)}</td></tr></table>
<p class="meta">U = {st.fD:g}DL + {st.fL:g}LL (และตรวจ 1.4DL) • ระยะหุ้ม {st.cover:g} cm • เหล็กปลอก Ø{st.stir:g} mm {st.legs} ขา • Pattern LL: {'Yes' if st.pattern else 'No'}
 • น้ำหนักคานอัตโนมัติ: {'Yes' if st.self_weight else 'No'} • ความเหนียว: {duct}</p>
<h2>ช่วงคานทั้งหมด (สรุป)</h2>
<table><tr><th>ช่วง</th><th>b×h</th><th>บน-ซ้าย</th><th>ล่าง-กลาง</th><th>บน-ขวา</th><th>ปลอก ซ้าย</th>
<th>ปลอก กลาง</th><th>ปลอก ขวา</th><th>ผล</th></tr>{''.join(tot)}</table>
<h2>แรงปฏิกิริยาที่จุดรองรับ (t, t-m)</h2>
<table><tr><th>จุด</th><th>X (m)</th><th>ชนิด</th><th>R DL</th><th>R LL</th><th>Ru max</th><th>Ru min</th>
<th>Mu เข้าเสา max</th><th>Mu เข้าเสา min</th></tr>{react}</table>
{''.join(span_html)}
<table class="sign">
<tr><td>Check by: {p['chk']} {p['chk_lic']}</td><td>Signature ____________________</td></tr>
<tr><td>Engineer: {p['eng']} {p['eng_lic']}</td><td>Signature ____________________</td></tr>
</table>
<p class="meta">วิเคราะห์ Direct Stiffness (2 DOF/จุด), Pattern LL envelope และ 1.4DL • เครื่องมือช่วยออกแบบ
ผลลัพธ์ต้องได้รับการตรวจสอบโดยวิศวกรผู้มีใบอนุญาต</p>
</body></html>"""
