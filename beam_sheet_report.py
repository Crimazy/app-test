"""HTML calculation page laid out like the "Beam-Singly" / "Beam-Doubly" forms (A1:K54)."""
from __future__ import annotations

import html
import math

from beam_sheet import bar_name, bars_text

CSS = """
@page { size: A4; margin: 10mm; }
body { font-family: Arial, 'Sarabun', sans-serif; font-size: 11.5px; color: #111; background: #fff; margin: 0; }
.sheet { width: 186mm; margin: 6mm auto; border: 1.5px solid #000; page-break-after: always; }
.sheet:last-child { page-break-after: auto; }
table { border-collapse: collapse; width: 100%; table-layout: fixed; }
td { padding: 1.5px 4px; vertical-align: middle; overflow: hidden; }
.grid td.eq { text-align: right; white-space: normal; }
.grid td.v { text-align: right; white-space: nowrap; }
.grid td.u { white-space: nowrap; padding-left: 3px; }
.bars { table-layout: auto; margin: 2px 0; }
.bars td { white-space: nowrap; }
.bars td.bl { width: 22%; text-align: right; font-weight: bold; padding-right: 6px; }
.bx { border-top: 1px solid #000; border-bottom: 1px solid #000; text-align: center; }
.bx.l { border-left: 1px solid #000; }
.bx.r { border-right: 1px solid #000; }
.inb { color: #1a3fb5; }
.hdr td { border: 1px solid #000; font-size: 11px; }
.hdr .lbl { font-weight: bold; font-style: italic; width: 16mm; }
.hdr .logo { text-align: center; border-right: 1px solid #000; }
.hdr .logo img { max-width: 34mm; max-height: 14mm; }
.sec { font-weight: bold; text-decoration: underline; display: inline-block; padding-top: 6px; }
.sub { font-weight: bold; text-decoration: underline; display: inline-block; padding-top: 3px; }
.eq { font-family: 'Cambria Math', 'Times New Roman', serif; font-style: italic; }
.v { text-align: right; }
.in { color: #1a3fb5; font-weight: bold; text-align: right; }
.ok { color: #d01818; font-weight: bold; font-style: italic; }
.ng { color: #fff; background: #d01818; font-weight: bold; font-style: italic; padding: 0 4px; }
.box td { border-top: 1px solid #000; border-bottom: 1px solid #000; }
.box td.l { border-left: 1px solid #000; }
.box td.r { border-right: 1px solid #000; }
.arrow { color: #333; }
.foot td { border: 1px solid #000; font-size: 11px; height: 16px; }
.foot .lbl { font-weight: bold; font-style: italic; }
.kind { display: inline-block; padding: 0 6px; border: 1px solid #1a3fb5; color: #1a3fb5; border-radius: 3px;
        font-weight: bold; font-style: normal; margin-left: 6px; }
.note { color: #555; font-size: 10.5px; }
"""


def _n(v, nd=2, comma=True):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    return f"{v:,.{nd}f}" if comma else f"{v:.{nd}f}"


def _ok(flag: bool, ok="O.K.", ng="NOT O.K.") -> str:
    return f'<span class="ok">{ok}</span>' if flag else f'<span class="ng">{ng}</span>'


def _bar_rows(layers, req, label, clear_min, n_show) -> str:
    """One line per layer: Using n DB.. (As = ..) and the clear distance between its bars."""
    out = []
    tot = sum(l["As"] for l in layers)
    rows = layers + [None] * max(0, n_show - len(layers))
    for k, l in enumerate(rows):
        if l is None:
            out.append(f"<tr><td class='bl'>{label if k == 0 else ''}</td><td class='bx l'>Using</td><td class='bx in'>-</td>"
                       "<td class='bx'></td><td class='bx'></td><td class='bx'>mm</td><td class='bx'>( As =</td>"
                       "<td class='bx'>-</td><td class='bx r'>cm² )</td><td></td><td></td></tr>")
            continue
        clr = "" if not math.isfinite(l["clear"]) else (
            f"ช่องว่าง {_n(l['clear'])} cm " + _ok(l["clear"] >= clear_min - 1e-9, "≥ " + _n(clear_min, 1), "&lt; " + _n(clear_min, 1)))
        out.append(
            f"<tr><td class='bl'>{label if k == 0 else ''}</td><td class='bx l'>ชั้น {l['layer']}</td>"
            f"<td class='bx in'>{html.escape(l['txt'])}</td><td class='bx'></td><td class='bx'></td><td class='bx'></td>"
            f"<td class='bx'>( As =</td><td class='bx in'>{_n(l['As'])}</td><td class='bx r'>cm² )</td>"
            f"<td>{_ok(tot >= req - 1e-9) if k == 0 else ''}</td><td class='note'>{clr}</td></tr>")
    return "<tr><td colspan='6' style='padding:0'><table class='bars'>" + "".join(out) + "</table></td></tr>"


def _row(left=None, right=None, cls="") -> str:
    """One line of the form: [formula = value unit] [formula = value unit]."""
    def half(h):
        if not h:
            return "<td></td><td></td><td></td>"
        eq, val, unit = (list(h) + ["", "", ""])[:3]
        return f"<td class='eq'>{eq}</td><td class='v'>{val}</td><td class='u'>{unit}</td>"
    return f"<tr class='{cls}'>{half(left)}{half(right)}</tr>"


def _wide(eq, val, mark) -> str:
    return f"<tr><td class='eq' colspan='4'>{eq}</td><td class='v'>{val}</td><td class='u'>{mark}</td></tr>"


def _title(text, cls="sub") -> str:
    head, _, rest = text.partition("&nbsp;")
    return f"<tr><td colspan='6'><span class='{cls}'>{head}</span>{('&nbsp;' + rest) if rest else ''}</td></tr>"


def _shear(sh, title) -> str:
    case_txt = {1: "Vu ≤ φVc/2 → s ≤ d/2, 60 cm",
                2: "φVc/2 < Vu < φVc → Av,min: s ≤ Av·fy/(3.5b)",
                3: "φVs ≤ 1.1φ√fc′·bd → s = φAv·fy·d/(Vu − φVc) ≤ d/2, 60 cm",
                4: "1.1 < φVs ≤ 2.1φ√fc′·bd → s ≤ d/4, 30 cm",
                5: "φVs > 2.1φ√fc′·bd → Revised (ขยายหน้าตัด)"}[sh["case"]]
    eq = f" • For EQ: s ≤ {_n(sh['eq_limit'])} cm" if sh["eq"] else ""
    calc = f" • s คำนวณ = {_n(sh['s_ctrl'])} cm" if sh["s_ctrl"] else ""
    S = (f"<b class='inb'>{_n(sh['s'])}</b>" if sh["s"] else _ok(False, ng="Revised"))
    return (_title(title)
            + _row(("V<sub>u</sub> =", _n(sh['Vu'], 0), "kg"), ("φV<sub>c</sub> = φ0.53√f′<sub>c</sub>·bd =", _n(sh['phiVc']), "kg"))
            + _row(None, ("φV<sub>c</sub>/2 =", _n(sh['half']), "kg"))
            + _row(("1.1φbd√f′<sub>c</sub> =", _n(sh['lim11']), "kg"), ("2.1φbd√f′<sub>c</sub> =", _n(sh['lim21']), "kg"))
            + f"<tr><td colspan='4' class='note' style='text-align:left'>case {sh['case'] if sh['case'] <= 4 else '-'}: "
              f"{case_txt}{eq}{calc}</td><td class='v'>S = {S}</td><td class='u'>cm</td></tr>")


def render_sheet(r: dict, head: dict) -> str:
    """One page.  head: project, location, member, type, date, job, note, calc, approve, page, logo (data URI)."""
    inp = r["inp"]
    esc = lambda v: html.escape(str(v or ""))
    logo = f'<img src="{head["logo"]}" alt="logo">' if head.get("logo") else ""
    doubly = r["kind"] == "Doubly"
    fc, fy = "f′<sub>c</sub>", "f<sub>y</sub>"
    kind = f"<span class='kind'>{r['kind']}</span>"

    rows = [
        _title("Material Properties", "sec"),
        _row((f"concrete : {fc} =", f"<span class='in'>{_n(inp.fc, 0)}</span>", "ksc"), ("β<sub>1</sub> =", _n(r['beta1']), "")),
        _row((f"steel : {fy} =", f"<span class='in'>{_n(r['fy'], 0)}</span>", "ksc"), ("E<sub>s</sub> =", _n(inp.Es, 0), "ksc")),
        _title("Input", "sec"),
        _row(("M<sub>max</sub> =", _n(inp.Mu, 0), "kg-m"), (f"B = <span class='in'>{_n(inp.B, 0)}</span> cm &nbsp; φ<sub>moment</sub> =", _n(inp.phi_b), "")),
        _row(("V<sub>max</sub> =", _n(inp.Vu, 0), "kg"), (f"H = <span class='in'>{_n(inp.H, 0)}</span> cm &nbsp; φ<sub>shear</sub> =", _n(inp.phi_v), "")),
        _row(("span =", f"<span class='in'>{_n(inp.span)}</span>", "m"),
             ("d =" + (f" &nbsp;(d′ = {_n(r['dp'])} cm)" if doubly else ""), _n(r['d']), "cm")),
    ]
    if not doubly:
        rows += [
            _title(f"Solution &nbsp; <span class='sub'>1.) Assume</span> {kind}"
                   + (f" &nbsp;<span class='note'>เลือกออกแบบเป็น Singly (ρ ต้องการ = {_n(r['rho_req'], 4)}"
                      f" &gt; ρ<sub>max</sub> = {_n(r['rho_max'], 4)})</span>" if r['chosen'] else ""), "sec"),
            _row((f"ρ<sub>b</sub> = 0.85β<sub>1</sub>({fc}/{fy})·0.003/(0.003 + {fy}/E<sub>s</sub>) =", _n(r['rho_b'], 4), ""),
                 ("→ ρ = 0.5ρ<sub>b</sub> =", _n(r['rho_half'], 4), "")),
            _row(None, ("ρ<sub>max</sub> = 0.75ρ<sub>b</sub> =", _n(r['rho_max'], 4), "")),
            _row(None, ("ρ<sub>min</sub> =", _n(r['rho_min'], 4), "")),
            _row((f"R<sub>u</sub> = ρ{fy}(1 − 0.59ρ{fy}/{fc}) =", _n(r['Ru']), "ksc"),
                 ("→ Suggest effective depth =", _n(r['d_sugg']), "cm")),
            _row(None, ("A<sub>s</sub> = ρbd =", _n(r['As_sugg']), "cm²")),
            _title("2.) Use"),
            _row((f"B × H = {_n(inp.B, 0)} × {_n(inp.H, 0)} cm", "", ""), ("d =", _n(r['d']), "cm")),
            _row(("R<sub>n</sub> = M<sub>u</sub>/(φbd²) =", _n(r['Rn']), "ksc"),
                 (f"→ ρ = (0.85{fc}/{fy})(1 − √(1 − 2R<sub>n</sub>/0.85{fc})) =", _n(r['rho_req'], 4), "")),
            _row(("use ρ =", _n(r['rho_use'], 4), ""), ("→ A<sub>s</sub> = ρbd =", _n(r['As_req']), "cm²")),
            _title("3.) Design"),
        ]
        check = [
            _title("4.) Check"),
            _row(None, ("ρ = A<sub>s</sub>/bd =", _n(r['rho'], 4), _ok(r['duct_ok']))),
            _row((f"a = A<sub>s</sub>{fy}/(0.85b{fc}) =", _n(r['a']), "cm"),
                 (f"φM<sub>n</sub> = φA<sub>s</sub>{fy}(d − a/2) =", _n(r['phiMn'], 0), "kg-m " + _ok(r['Mn_ok']))),
            _row((f"<span class='note'>ε<sub>t</sub> = {_n(r['eps_t'], 4)}, ε<sub>ty</sub> = {_n(r['ety'], 5)} → φ = {_n(r['phi'], 3)}"
                  f" • ρ ≤ ρ<sub>max</sub> = {_n(r['rho_max'], 4)}</span>", "", ""), None),
        ]
    else:
        why = (f"ρ ต้องการ = {_n(r['rho_req'], 4)} ≤ ρ<sub>max</sub> — เลือกออกแบบเป็น Doubly"
               if r['rho_req'] <= r['rho_max'] else f"ρ ต้องการ = {_n(r['rho_req'], 4)} &gt; ρ<sub>max</sub> = {_n(r['rho_max'], 4)}")
        rows += [
            _title(f"Solution &nbsp; {kind} &nbsp;<span class='note'>{why}</span>", "sec"),
            _row((f"ρ<sub>b</sub> = 0.85β<sub>1</sub>({fc}/{fy})·0.003/(0.003 + {fy}/E<sub>s</sub>) =", _n(r['rho_b'], 4), ""),
                 ("ρ<sub>1</sub> = 0.50ρ<sub>b</sub> =", _n(r['rho1'], 4), "")),
            _row(None, ("ρ<sub>max</sub> = 0.75ρ<sub>b</sub> =", _n(r['rho_max'], 4), "")),
            _row(None, (f"ρ<sub>cy</sub> = 0.85β<sub>1</sub>({fc}/{fy})(d′/d)·6120/(6120 − {fy}) =", _n(r['rho_cy'], 4), "")),
            _row((f"R<sub>u</sub> = ρ<sub>1</sub>{fy}(1 − 0.59ρ<sub>1</sub>{fy}/{fc}) =", _n(r['Ru1']), "ksc"),
                 ("M<sub>u1</sub> = φR<sub>u</sub>bd² =", _n(r['Mu1']), "kg-m")),
            _row(None, ("M<sub>u2</sub> = M<sub>u</sub> − M<sub>u1</sub> =", _n(r['Mu2']), "kg-m")),
            _row(("c (สมดุลแรงจากเหล็กที่ใช้) =", _n(r['c']), "cm"),
                 (f"f′<sub>s</sub> = 6120(c − d′)/c ≤ {fy} =", _n(r['fs_c'], 0), "ksc")),
            _row(("A′<sub>s</sub> = M<sub>u2</sub>/(φf′<sub>s</sub>(d − d′)) =", _n(r['Asc_req']), "cm²"),
                 (f"A<sub>s</sub> = ρ<sub>1</sub>bd + A′<sub>s</sub>f′<sub>s</sub>/{fy} =", _n(r['As_req']), "cm²")),
        ]
        check = [
            _title("Check", "sec"),
            _row(None, (f"ρ − ρ′f′<sub>s</sub>/{fy} =", _n(r['duct_val'], 4), _ok(r['duct_ok']))),
            _row((f"a = (A<sub>s</sub> − A′<sub>s</sub>f′<sub>s</sub>/{fy}){fy}/(0.85b{fc}) =", _n(r['a']), "cm"),
                 (f"φM<sub>n</sub> = φ[(A<sub>s</sub> − A′<sub>s</sub>f′<sub>s</sub>/{fy}){fy}(d − a/2) + A′<sub>s</sub>f′<sub>s</sub>(d − d′)] =",
                  _n(r['phiMn'], 0), "kg-m " + _ok(r['Mn_ok']))),
            _row((f"<span class='note'>ρ − ρ′f′<sub>s</sub>/{fy} ≤ 0.75ρ<sub>b</sub> = {_n(r['rho_max'], 4)}</span>", "", ""), None),
        ]
    # rows shown as in the forms: Singly 3 + 2, Doubly 4 + 3 (more when used)
    rows += [_bar_rows(r['layers_t'], r['As_req'], 'Tension Steel :', inp.clear_min, 4 if doubly else 3),
             _bar_rows(r['layers_c'], r['Asc_req'], 'Compression Steel :', inp.clear_min, 3 if doubly else 2),
             _wide(f"% เหล็กรับแรงดึง = A<sub>s</sub>/(B·H) = {_n(r['As'])}/({_n(inp.B, 0)}×{_n(inp.H, 0)}) "
                   f"≤ {_n(100 * inp.rho_limit, 1)} % →", _n(100 * r['pct']) + " %", _ok(r['pct_ok'])),
             _wide(f"ช่องว่างเหล็กเมนน้อยสุด = (B − 2·cover − Ø<sub>ปลอก</sub>·ขา − ΣnØ)/(n − 1) "
                   f"≥ {_n(inp.clear_min, 1)} cm →", _n(min((l['clear'] for l in r['layers_t'] + r['layers_c'] if math.isfinite(l['clear'])), default=None)) + " cm", _ok(r['clear_ok']))]
    rows += check
    rows += [
        _title("Shear Reinforcement", "sec"),
        _row((f"use {'DB' if inp.ds > 9 else 'RB'} <span class='in'>{inp.ds:g}</span> mm &nbsp; {fy} =", _n(r['fy_st'], 0), "ksc"),
             ("E<sub>s</sub> =", _n(inp.Es, 0), "ksc")),
        _row(("A<sub>v</sub> =", _n(r['Av'], 3), "cm²"), ("Leg =", f"<span class='in'>{inp.legs}</span>", "")),
        _shear(r['sh_2h'], "Distance of 2H from Support"),
        _shear(r['sh_mid'], "Midspan"),
        f"<tr><td colspan='6' class='note' style='padding-top:6px'>สรุป: เหล็กรับแรงดึง {bars_text(r['layers_t'])} • "
        f"เหล็กรับแรงอัด {bars_text(r['layers_c'])} • ปลอก {inp.legs} ขา {bar_name(inp.ds)} @ "
        f"{_n(r['sh_2h']['s']) if r['sh_2h']['s'] else '-'} cm (ช่วง 2H จากหน้าเสา) / @ "
        f"{_n(r['sh_mid']['s']) if r['sh_mid']['s'] else '-'} cm (กลางคาน) — {_ok(r['ok'], 'ผ่าน', 'ไม่ผ่าน')}</td></tr>",
    ]
    return f"""<div class="sheet">
<table class="hdr">
<colgroup><col style="width:24%"><col style="width:11%"><col style="width:33%"><col style="width:11%"><col style="width:21%"></colgroup>
<tr><td class="logo" rowspan="2">{logo}</td><td class="lbl">Project</td><td>{esc(head.get('project'))}</td>
    <td class="lbl">Date</td><td>{esc(head.get('date'))}</td></tr>
<tr><td class="lbl">Location</td><td>{esc(head.get('location'))}</td><td class="lbl">Job No.</td><td>{esc(head.get('job'))}</td></tr>
<tr><td class="lbl" style="text-align:center">Member</td><td colspan="2">{esc(head.get('member'))} &nbsp;&nbsp;
    <b><i>Type</i></b> &nbsp;{esc(head.get('type') or 'RC - BEAM')}</td><td class="lbl">Note</td><td>{esc(head.get('note'))}</td></tr>
</table>
<table class="grid">
<colgroup><col style="width:33%"><col style="width:10%"><col style="width:7%"><col style="width:31%"><col style="width:10%"><col style="width:9%"></colgroup>
{''.join(rows)}
</table>
<table class="foot">
<colgroup><col style="width:20%"><col style="width:52%"><col style="width:14%"><col style="width:14%"></colgroup>
<tr><td class="lbl">Calculated by :</td><td>{esc(head.get('calc'))}</td><td class="lbl" rowspan="2">Page No.</td>
    <td rowspan="2" style="text-align:center">{esc(head.get('page'))}</td></tr>
<tr><td class="lbl">Approved by :</td><td>{esc(head.get('approve'))}</td></tr>
</table>
</div>"""


def render_document(pages: list[str], title: str = "Beam Design") -> str:
    return (f"<!doctype html><html lang='th'><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{CSS}</style></head><body>{''.join(pages)}</body></html>")
