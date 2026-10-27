"""HTML calculation report for the beam design page."""
from __future__ import annotations

import html
import math

from beam_design import ACI


def _f(x, nd=1):
    return f"{x:,.{nd}f}" if x is not None and math.isfinite(x) else "∞"


def _status(ok: bool) -> str:
    return '<span class="ok">OK</span>' if ok else '<span class="ng">NG</span>'


def build_beam_report(project, beam_id, inp, results, code_name, fu, mu, wu_u, F, all_ok, extra,
                      bars_txt, unit_txt) -> str:
    kN = lambda n: n / 1e3 / F
    kNm = lambda m: m / 1e6 / F
    esc = html.escape
    size = f"{inp.bw:.0f} × {inp.h:.0f} mm"
    if inp.flange:
        size += f" (ตัว T: bf = {inp.bf:.0f}, hf = {inp.hf:.0f} mm)"

    load_html = ""
    if extra["analysis"]:
        frc = extra["frc"]
        load_html = f"""
<h2>2. น้ำหนักบรรทุกและแรงออกแบบ</h2>
<table class="meta">
<tr><td>สภาพจุดรองรับ</td><td>{esc(extra['support'])}</td><td>ช่วง L</td><td>{extra['span'] / 1000:.2f} m</td></tr>
<tr><td>DL (รวมน้ำหนักคาน)</td><td>{_f(kN(extra['wD'] * 1e3), 2)} {wu_u}</td>
    <td>LL</td><td>{_f(kN(extra['wL'] * 1e3), 2)} {wu_u}</td></tr>
<tr><td>wu ({esc(extra['combo'])})</td><td>{_f(kN(extra['wu'] * 1e3), 2)} {wu_u}</td>
    <td>h,min (ไม่ต้องคำนวณการโก่งตัว)</td><td>{extra['hmin']:.0f} mm</td></tr>
<tr><td>Mu+</td><td>{_f(kNm(frc['Mpos']))} {mu}</td><td>Mu−</td><td>{_f(kNm(frc['Mneg']))} {mu}</td></tr>
<tr><td>Vu ที่ระยะ d</td><td>{_f(kN(frc['Vu_d']))} {fu}</td><td>Vu ที่ L/4</td><td>{_f(kN(frc['Vu_mid']))} {fu}</td></tr>
</table>"""

    sections = []
    for r in results.values():
        f_ = r.flex
        flex_html = "<p>ไม่มีโมเมนต์ดัดที่ตำแหน่งนี้</p>"
        if f_ is not None:
            req = r.req["As"]
            flex_html = f"""
<table class="meta">
<tr><td>d / dt</td><td>{f_['d']:.0f} / {f_['dt']:.0f} mm</td><td>As / As′</td><td>{f_['As']:,.0f} / {f_['As_comp']:,.0f} mm²</td></tr>
<tr><td>As ต้องการ</td><td>{_f(req, 0) if req is not None else 'เกินขีดจำกัด'} mm²</td>
    <td>As,min / As,max</td><td>{f_['As_min']:,.0f} / {f_['As_max']:,.0f} mm²</td></tr>
<tr><td>c / a</td><td>{f_['c']:.1f} / {f_['a']:.1f} mm</td><td>εt / φ</td><td>{f_['eps_t']:.4f} / {f_['phi']:.3f}</td></tr>
<tr><td>Mn</td><td>{_f(kNm(f_['Mn']))} {mu}</td><td>φMn vs Mu</td>
    <td>{_f(kNm(f_['phiMn']))} vs {_f(kNm(abs(r.loc.Mu)))} {mu}</td></tr>
</table>"""
        sh = r.shear
        rows = "".join(
            f"<tr><td>{c['clause']}</td><td>{esc(c['item'])}</td><td>{esc(unit_txt(c['required']))}</td>"
            f"<td>{esc(unit_txt(c['provided']))}</td><td>{_status(c['ok'])}</td></tr>"
            for c in r.checks + r.detail
        )
        sections.append(f"""
<h3>{esc(r.loc.name)} — {_status(r.ok)}</h3>
<table class="meta">
<tr><td>เหล็กบน</td><td>{bars_txt(r.loc.reinf, 'top')}</td><td>เหล็กล่าง</td><td>{bars_txt(r.loc.reinf, 'bot')}</td></tr>
<tr><td>เหล็กปลอก</td><td>{esc(extra['stir'])} {inp.legs} ขา @ {r.loc.reinf.s:.0f} mm</td>
    <td>Mu / Vu</td><td>{_f(kNm(r.loc.Mu))} {mu} / {_f(kN(r.loc.Vu))} {fu}</td></tr>
</table>
<h4>แรงดัด</h4>{flex_html}
<h4>แรงเฉือน</h4>
<table class="meta">
<tr><td>{esc(sh['eq'])}</td><td>Vc = {_f(kN(sh['Vc']))} {fu}</td><td>Vs = Av·fyt·d/s</td><td>{_f(kN(sh['Vs']))} {fu}</td></tr>
<tr><td>φ</td><td>{sh['phi']}</td><td>φVn vs Vu</td><td>{_f(kN(sh['phiVn']))} vs {_f(kN(sh['Vu']))} {fu}</td></tr>
<tr><td>s,max</td><td>{sh['s_max']:.0f} mm</td><td>s แนะนำ</td><td>{sh['s_rec']:.0f} mm</td></tr>
</table>
<h4>รายการตรวจสอบ</h4>
<table><tr><th>ข้อ</th><th>รายการ</th><th>ต้องการ</th><th>ที่ใช้</th><th>สถานะ</th></tr>{rows}</table>""")

    defl_html = ""
    d_ = extra.get("defl")
    if d_:
        lim_L = d_["eff_L"] / 360
        lim_T = d_["eff_L"] / (240 if extra["dlim"] == "L/240" else 480)
        ie = "Bischoff (ACI 318-19 Table 24.2.3.5)" if inp.code == ACI else "Branson (ACI 318-99 Eq. 9-7)"
        defl_html = f"""
<h2>4. การโก่งตัว</h2>
<table class="meta">
<tr><td>Ig / Icr</td><td>{d_['Ig'] / 1e6:,.0f} / {d_['Icr'] / 1e6:,.0f} ×10⁶ mm⁴</td>
    <td>Mcr</td><td>{_f(kNm(d_['Mcr']))} {mu}</td></tr>
<tr><td>Ie (D+L), {ie}</td><td>{d_['IeDL'] / 1e6:,.0f} ×10⁶ mm⁴</td><td>λΔ</td><td>{d_['lam_d']:.2f}</td></tr>
<tr><td>Δ ทันที LL</td><td>{d_['dL']:.2f} mm (≤ {lim_L:.1f}) {_status(d_['dL'] <= lim_L)}</td>
    <td>Δ หลังติดตั้ง</td><td>{d_['d_after']:.2f} mm (≤ {lim_T:.1f}) {_status(d_['d_after'] <= lim_T)}</td></tr>
</table>"""

    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<title>{esc(beam_id)} – Beam Design</title>
<style>
 body {{font-family: 'Sarabun','Segoe UI',sans-serif; margin: 32px; color:#202124; background:#fff;}}
 h1 {{font-size: 22px; margin-bottom: 4px;}} h2 {{font-size: 17px; border-bottom: 2px solid #1a73e8; padding-bottom: 4px; margin-top: 28px;}}
 h3 {{font-size: 16px; margin-top: 22px;}} h4 {{font-size: 14px; margin: 14px 0 4px;}}
 table {{border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 8px;}}
 th, td {{border: 1px solid #dadce0; padding: 5px 8px; text-align: center;}}
 th {{background: #f1f3f4;}}
 .ok {{color:#137333; font-weight:700;}} .ng {{color:#c5221f; font-weight:700;}}
 .meta td {{text-align:left;}}
 small {{color:#5f6368;}}
</style></head><body>
<h1>รายการคำนวณออกแบบคาน {esc(beam_id)}</h1>
<small>โครงการ: {esc(project)} • มาตรฐาน: {esc(code_name)} • วันที่: {extra['today']}</small>
<h2>1. ข้อมูลออกแบบ</h2>
<table class="meta">
<tr><td>หน้าตัด</td><td>{size}</td><td>ระยะหุ้มถึงเหล็กปลอก</td><td>{inp.cover:.0f} mm</td></tr>
<tr><td>fc′</td><td>{inp.fc:.1f} MPa ({inp.fc / 0.0980665:.0f} ksc)</td><td>fy / fyt</td>
    <td>{inp.fy:.0f} / {inp.fyt:.0f} MPa</td></tr>
<tr><td>Ec = 4700√fc′</td><td>{4700 * math.sqrt(inp.fc):,.0f} MPa</td><td>มวลรวมโตสุด</td><td>{inp.agg:.0f} mm</td></tr>
</table>
{load_html}
<h2>3. ผลการออกแบบแต่ละตำแหน่ง</h2>
{''.join(sections)}
{defl_html}
<h2>สรุป: {_status(all_ok)}</h2>
<small>คำนวณด้วย strain compatibility (εcu = 0.003, Whitney stress block 0.85fc′).
ผลลัพธ์ต้องได้รับการตรวจสอบโดยวิศวกรผู้มีใบอนุญาต</small>
</body></html>"""
