"""HTML calculation report for the column design app."""
from __future__ import annotations

import html
import math


def _f(x, nd=1):
    return f"{x:,.{nd}f}" if x is not None and math.isfinite(x) else "∞"


def _status(ok: bool) -> str:
    return '<span class="ok">OK</span>' if ok else '<span class="ng">NG</span>'


def build_report(project, col_id, bar_name, tie_name, inp, slend, sec, cases, detail,
                 fu, mu, F, all_ok, today) -> str:
    kN = lambda n: n / 1e3 / F
    kNm = lambda m: m / 1e6 / F
    esc = html.escape
    size = f"Ø{inp.D:.0f} mm" if inp.is_circular else f"{inp.b:.0f} × {inp.h:.0f} mm"
    trans = "Spiral" if inp.is_spiral else "Tied"

    case_rows = "".join(
        f"<tr><td>{esc(c.case.name)}</td><td>{_f(kN(c.case.Pu))}</td><td>{_f(kNm(c.Mcx))}</td>"
        f"<td>{_f(kNm(c.Mcy))}</td><td>{_f(kNm(c.phiMn_dir))}</td><td>{_f(c.dcr_axial, 3)}</td>"
        f"<td>{_f(c.dcr_moment, 3)}</td><td>{_f(max(c.shear_x['dcr'], c.shear_y['dcr']), 3)}</td>"
        f"<td>{_status(c.ok)}</td></tr>"
        for c in cases
    )
    det_rows = "".join(
        f"<tr><td>{d['clause']}</td><td>{esc(d['item'])}</td><td>{esc(d['required'])}</td>"
        f"<td>{esc(d['provided'])}</td><td>{_status(d['ok'])}</td></tr>"
        for d in detail
    )
    sl_rows = "".join(
        f"<tr><td>{esc(c.case.name)}</td><td>{s['axis']}</td><td>{_f(s['klu_r'])}</td>"
        f"<td>{_f(s['limit'])}</td><td>{'Yes' if s['slender'] else 'No'}</td>"
        f"<td>{_f(s['delta'], 3)}</td><td>{_f(kNm(s['Mc']))}</td><td>{_status(s['ok'])}</td></tr>"
        for c in cases for s in (c.slx, c.sly)
    )
    sh_rows = "".join(
        f"<tr><td>{esc(c.case.name)}</td><td>V{sh['direction']}</td><td>{_f(kN(sh['Vc']))}</td>"
        f"<td>{_f(kN(sh['Vs']))}</td><td>{_f(kN(sh['phiVn']))}</td><td>{_f(kN(sh['Vu']))}</td>"
        f"<td>{_status(sh['ok'])}</td></tr>"
        for c in cases for sh in (c.shear_x, c.shear_y)
    )
    verdict = _status(all_ok)
    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<title>{esc(col_id)} – ACI 318-19 Column Design</title>
<style>
 body {{font-family: 'Sarabun','Segoe UI',sans-serif; margin: 32px; color:#202124; background:#fff;}}
 h1 {{font-size: 22px; margin-bottom: 4px;}} h2 {{font-size: 17px; border-bottom: 2px solid #1a73e8; padding-bottom: 4px; margin-top: 28px;}}
 table {{border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 8px;}}
 th, td {{border: 1px solid #dadce0; padding: 5px 8px; text-align: center;}}
 th {{background: #f1f3f4;}}
 .ok {{color:#137333; font-weight:700;}} .ng {{color:#c5221f; font-weight:700;}}
 .meta td {{text-align:left;}}
 small {{color:#5f6368;}}
</style></head><body>
<h1>รายการคำนวณออกแบบเสา {esc(col_id)} — ACI 318-19</h1>
<small>โครงการ: {esc(project)} • วันที่: {today}</small>
<h2>1. ข้อมูลออกแบบ</h2>
<table class="meta">
<tr><td>หน้าตัด</td><td>{size} ({trans})</td><td>ระยะหุ้ม</td><td>{inp.cover:.0f} mm</td></tr>
<tr><td>fc'</td><td>{inp.fc:.1f} MPa</td><td>fy / fyt</td><td>{inp.fy:.0f} / {inp.fyt:.0f} MPa</td></tr>
<tr><td>เหล็กยืน</td><td>{sec.n_bars}-{bar_name} (Ast = {sec.Ast:,.0f} mm², ρg = {sec.rho * 100:.2f}%)</td>
    <td>เหล็กปลอก</td><td>{tie_name} @ {inp.s:.0f} mm</td></tr>
<tr><td>β1</td><td>{sec.beta1:.3f}</td><td>Ec</td><td>{sec.Ec:,.0f} MPa</td></tr>
<tr><td>Po</td><td>{_f(kN(sec.Po), 0)} {fu}</td><td>φPn,max = {sec.phi_c}×{sec.alpha_max}Po</td>
    <td>{_f(kN(sec.phiPn_max), 0)} {fu}</td></tr>
<tr><td>ชนิดโครงสร้าง</td><td>{'Sway' if slend.sway else 'Nonsway'}</td>
    <td>Lu (x / y)</td><td>{slend.lu_x / 1000:.2f} / {slend.lu_y / 1000:.2f} m</td></tr>
</table>
<h2>2. กำลังรับแรงอัดร่วมแรงดัด ({fu}, {mu})</h2>
<table><tr><th>กรณี</th><th>Pu</th><th>Mcx</th><th>Mcy</th><th>φMn (ทิศ Mu)</th>
<th>D/C แรงอัด</th><th>D/C โมเมนต์</th><th>D/C เฉือน</th><th>สถานะ</th></tr>{case_rows}</table>
<h2>3. ความชะลูด (6.2.5, 6.6.4)</h2>
<table><tr><th>กรณี</th><th>แกน</th><th>kLu/r</th><th>ขีดจำกัด</th><th>ชะลูด</th><th>δ</th>
<th>Mc ({mu})</th><th>สถานะ</th></tr>{sl_rows}</table>
<h2>4. แรงเฉือน (22.5) ({fu})</h2>
<table><tr><th>กรณี</th><th>ทิศ</th><th>Vc</th><th>Vs</th><th>φVn</th><th>Vu</th><th>สถานะ</th></tr>{sh_rows}</table>
<h2>5. รายละเอียดเหล็กเสริม</h2>
<table><tr><th>ข้อ</th><th>รายการ</th><th>ต้องการ</th><th>ที่ใช้</th><th>สถานะ</th></tr>{det_rows}</table>
<h2>6. สรุป: {verdict}</h2>
<small>คำนวณด้วย strain compatibility (εcu = 0.003, Whitney stress block) และ φ ตาม Table 21.2.2.
ผลลัพธ์ต้องได้รับการตรวจสอบโดยวิศวกรผู้มีใบอนุญาต</small>
</body></html>"""
