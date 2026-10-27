"""Excel (.xlsx) export of the design sheet with live formulas, one worksheet per section.

Every value on a sheet is an Excel formula of the blue input cells (materials, Mu/Vu, section,
bars per layer, stirrup, legs, mode, limits), so the file can be edited and recalculated outside
the program.  The formulas are the same as beam_sheet.compute (Singly and Doubly blocks are both
computed; the "Check" block takes the one selected by the mode cell).
"""
from __future__ import annotations

import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from beam_sheet import MODES, SheetInput

BLUE = Font(color="1A3FB5", bold=True)
BOLD = Font(bold=True)
SEC = Font(bold=True, underline="single", size=11)
NOTE = Font(color="666666", italic=True, size=9)
IN_FILL = PatternFill("solid", fgColor="EAF1FF")
THIN = Side(style="thin", color="000000")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
MODE_TXT = {"auto": "Auto", "singly": "Singly", "doubly": "Doubly"}
NROW_T, NROW_C = 4, 3          # bar layer rows shown at least (as in the forms)
NPAIR = 3                      # bar sizes per layer row


class _Sheet:
    """Row writer: label (A:F) | value (G) | unit (H) | note (I:M); named cells for formulas."""

    def __init__(self, ws):
        self.ws, self.r, self.cells = ws, 1, {}

    def f(self, text: str) -> str:
        return re.sub(r"\{(\w+)\}", lambda m: self.cells[m.group(1)], text)

    def title(self, text, font=SEC):
        self.ws.cell(self.r, 1, text).font = font
        self.r += 1

    def note(self, text):
        self.ws.cell(self.r, 1, text).font = NOTE
        self.r += 1

    def put(self, name, label, value, unit="", fmt="#,##0.00", inp=False, note=None, row=None):
        r = row or self.r
        self.ws.cell(r, 1, label)
        c = self.ws.cell(r, 7, self.f(value) if isinstance(value, str) and value.startswith("=") else value)
        c.number_format = fmt
        c.alignment = Alignment(horizontal="right")
        if inp:
            c.font, c.fill, c.border = BLUE, IN_FILL, BOX
        self.ws.cell(r, 8, unit)
        if note:
            n = self.ws.cell(r, 9, self.f(note) if note.startswith("=") else note)
            n.font = Font(color="D01818", bold=True, italic=True) if note.startswith("=") else NOTE
        if name:
            self.cells[name] = f"$G${r}"
        if row is None:
            self.r += 1
        return f"$G${r}"


def _pairs(inp: SheetInput, side: str) -> list[tuple[int, list[tuple[int, float]]]]:
    """Layer rows of a side: (layer number, [(n, db) x NPAIR]) in layer order."""
    bars = inp.side(side)
    out = []
    for k in sorted({b.layer for b in bars}):
        cnt: dict = {}
        for b in bars:
            if b.layer == k:
                cnt[b.db] = cnt.get(b.db, 0) + b.n
        items = sorted(cnt.items(), key=lambda t: -t[0])
        if len(items) > NPAIR:                     # more sizes than columns: extra rows of the same layer
            for j in range(0, len(items), NPAIR):
                out.append((k, [(n, d) for d, n in items[j:j + NPAIR]]))
        else:
            out.append((k, [(n, d) for d, n in items]))
    return out


def _bar_block(S: _Sheet, inp: SheetInput, side: str, title: str, nmin: int) -> dict:
    """Bar table of one side; returns cell ranges of As / y / clear / n and the dmax cells."""
    ws = S.ws
    S.title(title, BOLD)
    heads = ["", "ชั้นที่"] + sum(([f"n{j + 1}", f"Ø{j + 1} (mm)"] for j in range(NPAIR)), []) + \
            ["n รวม", "As (cm²)", "Ømax", "y (cm)", "ช่องว่าง (cm)"]
    for j, h in enumerate(heads, 1):
        c = ws.cell(S.r, j, h)
        c.font, c.alignment = BOLD, Alignment(horizontal="center")
    S.r += 1
    rows = _pairs(inp, side)
    rows += [(rows[-1][0] + 1 + i if rows else 1 + i, []) for i in range(max(0, nmin - len(rows)))]
    first = S.r
    cN, cA, cD, cY, cC = (get_column_letter(2 + 2 * NPAIR + k) for k in range(1, 6))
    for i, (layer, items) in enumerate(rows):
        r = S.r
        ws.cell(r, 2, layer).alignment = Alignment(horizontal="center")
        for j in range(NPAIR):
            n, d = items[j] if j < len(items) else (0, 0)
            for col, v in ((3 + 2 * j, n), (4 + 2 * j, d)):
                c = ws.cell(r, col, v)
                c.font, c.fill, c.border, c.alignment = BLUE, IN_FILL, BOX, Alignment(horizontal="center")
        nl = [f"{get_column_letter(3 + 2 * j)}{r}" for j in range(NPAIR)]
        dl = [f"{get_column_letter(4 + 2 * j)}{r}" for j in range(NPAIR)]
        ws[f"{cN}{r}"] = "=" + "+".join(nl)
        ws[f"{cA}{r}"] = "=" + "+".join(f"{n}*PI()*({d}/10)^2/4" for n, d in zip(nl, dl))
        ws[f"{cD}{r}"] = "=MAX(" + ",".join(f"IF({n}>0,{d},0)" for n, d in zip(nl, dl)) + ")"
        # y0 of this row: cover + stirrup + previous non-empty rows (Ømax + gap); a row that repeats
        # the previous row's layer number (more than NPAIR sizes) shares its position
        if i == 0:
            y0 = S.f("({cover}+{ds}/10)")
        else:
            p = r - 1
            same = rows[i][0] == rows[i - 1][0]
            y0 = (f"({cY}{p}-{cD}{p}/20)" if same else
                  f"IF({cN}{p}>0,{cY}{p}-{cD}{p}/20+{cD}{p}/10+{S.cells['gap']},{cY}{p})")
        ws[f"{cY}{r}"] = f"=IF({cN}{r}>0,{y0}+{cD}{r}/20,{y0})" if i else f"=IF({cN}{r}>0,{y0}+{cD}{r}/20,{y0})"
        ws[f"{cC}{r}"] = S.f(f'=IF({cN}{r}>1,({{B}}-2*{{cover}}-{{ds}}/10*{{legs}}-('
                             + "+".join(f"{n}*{d}" for n, d in zip(nl, dl)) + f')/10)/({cN}{r}-1),"-")')
        for col in (cA, cY, cC):
            ws[f"{col}{r}"].number_format = "0.00"
        ws[f"{cC}{r}"].font = Font(color="D01818", bold=True)
        S.r += 1
    last = S.r - 1
    rng = lambda c: f"${c}${first}:${c}${last}"
    # y of an empty row carries y0 forward: weight by As (0 for empty rows)
    return dict(As=rng(cA), y=rng(cY), clear=rng(cC), n=rng(cN), dmax=rng(cD))


def write_section(ws, inp: SheetInput, head: dict):
    S = _Sheet(ws)
    widths = [30, 7, 6, 8, 6, 8, 12, 9, 7, 9, 8, 8, 12]
    for j, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.sheet_view.showGridLines = False

    S.title(f"Beam Design Sheet — {head.get('member', '')}", Font(bold=True, size=13))
    for k, lbl in (("project", "Project"), ("location", "Location"), ("note", "Note"), ("date", "Date"),
                   ("calc", "Calculated by")):
        if head.get(k):
            ws.cell(S.r, 1, f"{lbl} : {head[k]}")
            S.r += 1
    S.note("ช่องสีฟ้า = ค่าที่กรอก/แก้ได้ • ค่าอื่นเป็นสูตร Excel ทั้งหมด (หน่วย kg, kg-m, cm, ksc)")

    S.title("Material Properties")
    S.put("fc", "concrete : fc' =", inp.fc, "ksc", "0", inp=True)
    S.put("fy", "steel (main) : fy =", inp.fy, "ksc", "0", inp=True)
    S.put("fy_rb", "steel RB (stirrup ≤ 9 mm) : fy =", inp.fy_rb, "ksc", "0", inp=True)
    S.put("Es", "Es =", inp.Es, "ksc", "#,##0", inp=True)
    S.put("b1", "β1 =", "=IF({fc}<=280,0.85,IF({fc}<=560,0.85-0.05*({fc}-280)/70,0.65))", "", "0.000")

    S.title("Input")
    S.put("Mu", "Mmax = Mu =", round(inp.Mu, 2), "kg-m", inp=True)
    S.put("Vu", "Vmax (ที่หน้าเสา, โซน 2H) =", round(inp.Vu, 2), "kg", inp=True)
    S.put("Vum", "Vu กลางคาน (ที่ระยะ 2H) =", round(inp.Vu_mid, 2), "kg", inp=True)
    S.put("span", "span =", inp.span, "m", inp=True)
    S.put("B", "B =", inp.B, "cm", "0.0", inp=True)
    S.put("H", "H =", inp.H, "cm", "0.0", inp=True)
    S.put("cover", "covering (ถึงผิวเหล็กปลอก) =", inp.cover, "cm", "0.0", inp=True)
    S.put("gap", "ระยะห่างระหว่างชั้นเหล็ก =", inp.gap, "cm", "0.0", inp=True)
    S.put("phib", "φ moment =", inp.phi_b, "", "0.00", inp=True)
    S.put("phiv", "φ shear =", inp.phi_v, "", "0.00", inp=True)
    S.put("ds", "เหล็กปลอก Ø =", inp.ds, "mm", "0", inp=True)
    S.put("legs", "จำนวนขาเหล็กปลอก =", inp.legs, "ขา", "0", inp=True)
    S.put("mode", "ออกแบบเป็น (Auto / Singly / Doubly) =", MODE_TXT.get(inp.mode, "Auto"), "", "@", inp=True)
    dv = DataValidation(type="list", formula1='"Auto,Singly,Doubly"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(S.cells["mode"].replace("$", ""))
    S.put("eq", "For EQ (1 = ใช้, 0 = ไม่ใช้) =", 1 if inp.eq else 0, "", "0", inp=True)
    S.put("rlim", "% เหล็กรับแรงดึงไม่เกิน =", inp.rho_limit, "", "0.0%", inp=True)
    S.put("cmin", "ช่องว่างเหล็กเมนไม่น้อยกว่า =", inp.clear_min, "cm", "0.0", inp=True)

    S.title("Main Bars (แต่ละแถว = 1 ชั้น; ชั้น 1 ชิดผิว)")
    T = _bar_block(S, inp, "t", "Tension Steel :", NROW_T)
    C = _bar_block(S, inp, "c", "Compression Steel :", NROW_C)
    S.put("As", "As (ดึง) =", f"=SUM({T['As']})", "cm²")
    S.put("Asc", "A's (อัด) =", f"=SUM({C['As']})", "cm²")
    S.put("dbt", "Ø เหล็กดึงใหญ่สุด =", f"=MAX({T['dmax']})", "mm", "0")
    S.put("fym", "fy เหล็กหลักที่ใช้ =", "=IF({dbt}>9,{fy},{fy_rb})", "ksc", "0")
    S.put("d", "d = H − (Σ As·y / Σ As)ดึง =", f"={{H}}-IF({{As}}>0,SUMPRODUCT({T['As']},{T['y']})/{{As}},"
                                               "{cover}+{ds}/10+{dbt}/20)", "cm")
    S.put("dp", "d' = (Σ As·y / Σ As)อัด =", f"=IF({{Asc}}>0,SUMPRODUCT({C['As']},{C['y']})/{{Asc}},"
                                             "{cover}+{ds}/10+" + f"{inp.db:g}/20)", "cm")
    S.put("pct", "% เหล็กรับแรงดึง = As/(B·H) =", "={As}/({B}*{H})", "", "0.00%",
          note='=IF({pct}<={rlim}+1E-12,"O.K.","NOT O.K.")'.replace("{pct}", f"$G${S.r}"))
    S.put("cl", "ช่องว่างเหล็กเมนน้อยสุด = (B−2cover−Øปลอก·ขา−ΣnØ)/(n−1) =",
          f'=IF(COUNT({T["clear"]},{C["clear"]})>0,MIN({T["clear"]},{C["clear"]}),"-")', "cm",
          note=f'=IF(COUNT({T["clear"]},{C["clear"]})=0,"O.K.",IF($G${S.r}>={{cmin}}-1E-9,"O.K.","NOT O.K."))')

    S.title("Solution")
    S.put("rhob", "ρb = 0.85β1(fc'/fy)·0.003/(0.003+fy/Es) =", "=0.85*{b1}*{fc}/{fym}*0.003/(0.003+{fym}/{Es})", "", "0.0000")
    S.put("rhoh", "ρ = 0.5ρb =", "=0.5*{rhob}", "", "0.0000")
    S.put("rmax", "ρmax = 0.75ρb =", "=0.75*{rhob}", "", "0.0000")
    S.put("Ru", "Ru = ρfy(1 − 0.59ρfy/fc') =", "={rhoh}*{fym}*(1-0.59*{rhoh}*{fym}/{fc})", "ksc")
    S.put("dsug", "Suggest effective depth = √(Mu/(φRu·b)) =", "=IF({Mu}>0,SQRT({Mu}*100/({phib}*{Ru}*{B})),0)", "cm")
    S.put("Rn", "Rn = Mu/(φbd²) =", "={Mu}*100/({phib}*{B}*{d}^2)", "ksc")
    S.put("disc", "1 − 2Rn/(0.85fc') =", "=1-2*{Rn}/(0.85*{fc})", "", "0.0000")
    S.put("rreq", "ρ ต้องการ = (0.85fc'/fy)(1 − √(1 − 2Rn/0.85fc')) =",
          "=IF({disc}>=0,0.85*{fc}/{fym}*(1-SQRT({disc})),9.99)", "", "0.0000",
          note="9.99 = หน้าตัดเล็กเกิน (Singly ไม่ได้)")
    S.put("rmin", "ρmin = min(max(14/fy, 0.8√fc'/fy), 1.33ρ) =",
          "=MIN(MAX(14/{fym},0.8*SQRT({fc})/{fym}),1.33*{rreq})", "", "0.0000")
    S.put("kind", "ใช้แบบ =", '=IF({mode}="Singly","Singly",IF({mode}="Doubly","Doubly",'
                              'IF({rreq}<={rmax},"Singly","Doubly")))', "", "General")

    S.title("Singly")
    S.put("s_ruse", "use ρ = max(ρ, ρmin) =", "=MAX({rreq},{rmin})", "", "0.0000")
    S.put("s_As", "As ต้องการ = ρbd =", "={s_ruse}*{B}*{d}", "cm²")
    S.put("s_Asc", "A's ต้องการ (เหล็กเสริมรับแรงอัด ≥ ρmin·bd) =", "={rmin}*{B}*{d}", "cm²")
    S.put("s_a", "a = As·fy/(0.85b·fc') =", "={As}*{fym}/(0.85*{fc}*{B})", "cm")
    S.put("s_c", "c = a/β1 =", "={s_a}/{b1}", "cm")
    S.put("s_et", "εt = 0.003(d − c)/c =", "=IF({s_c}>0,0.003*({d}-{s_c})/{s_c},1)", "", "0.00000")
    S.put("ety", "εty = fy/Es =", "={fym}/{Es}", "", "0.00000")
    S.put("s_phi", "φ (0.70 – 0.90 ตาม εt) =",
          "=IF({s_et}<={ety},0.7,IF({s_et}<{ety}+0.003,0.7+0.25*({s_et}-{ety})/0.003,0.9))", "", "0.000")
    S.put("s_pMn", "φMn = φAs·fy(d − a/2) =", "={s_phi}*{As}*{fym}*({d}-{s_a}/2)/100", "kg-m")
    S.put("rho", "ρ = As/bd =", "={As}/({B}*{d})", "", "0.0000")

    S.title("Doubly")
    S.put("Ru1", "Ru = ρ1·fy(1 − 0.59ρ1·fy/fc'), ρ1 = 0.5ρb =", "={rhoh}*{fym}*(1-0.59*{rhoh}*{fym}/{fc})", "ksc")
    S.put("Mu1", "Mu1 = φRu·bd² =", "={phib}*{Ru1}*{B}*{d}^2/100", "kg-m")
    S.put("Mu2", "Mu2 = Mu − Mu1 =", "={Mu}-{Mu1}", "kg-m")
    S.put("E6", "0.003Es =", "=0.003*{Es}", "ksc", "#,##0")
    S.put("P", "P = (0.003Es·A's − As·fy)/(1.7fc'·b·β1) =", "=({E6}*{Asc}-{As}*{fym})/(1.7*{fc}*{B}*{b1})", "", "0.0000")
    S.put("Q", "Q = 0.003Es·d'·A's/(0.85fc'·b·β1) =", "={E6}*{dp}*{Asc}/(0.85*{fc}*{B}*{b1})", "", "0.0000")
    S.put("c", "c = −P + √(P² + Q) =", "=IF({P}^2+{Q}>=0,-{P}+SQRT({P}^2+{Q}),0)", "cm", "0.0000")
    S.put("fsc", "f's = 0.003Es(c − d')/c ≤ fy =", "=IF({c}>0,MIN({fym},({c}-{dp})/{c}*{E6}),0)", "ksc")
    S.put("rcy", "ρcy = 0.85β1(fc'/fy)(d'/d)·6120/(6120 − fy) =",
          "=0.85*{b1}*{fc}/{fym}*{dp}/{d}*{E6}/({E6}-{fym})", "", "0.0000")
    S.put("d_Asc", "A's ต้องการ = Mu2/(φf's(d − d')) =",
          "=IF({fsc}>0,MAX({Mu2},0)*100/({phib}*{fsc}*({d}-{dp})),9999)", "cm²")
    S.put("d_As", "As ต้องการ = ρ1·bd + A's·f's/fy =", "=IF({fsc}>0,{rhoh}*{B}*{d}+{d_Asc}*{fsc}/{fym},9999)", "cm²")
    S.put("Aseff", "As − A's·f's/fy =", "={As}-{Asc}*MAX({fsc},0)/{fym}", "cm²")
    S.put("d_a", "a = (As − A's·f's/fy)fy/(0.85b·fc') =", "={Aseff}*{fym}/(0.85*{B}*{fc})", "cm")
    S.put("d_pMn", "φMn = φ[(As − A's f's/fy)fy(d − a/2) + A's f's(d − d')] =",
          "={phib}*({Aseff}*{fym}*({d}-{d_a}/2)+{Asc}*MAX({fsc},0)*({d}-{dp}))/100", "kg-m")
    S.put("d_duct", "ρ − ρ'f's/fy =", "={Aseff}/({B}*{d})", "", "0.0000")

    S.title("Check (ตามแบบที่ใช้)")
    sg = '{kind}="Singly"'
    S.put("Asr", "As ต้องการ =", f"=IF({sg},{{s_As}},{{d_As}})", "cm²",
          note='=IF({As}>={Asr}-1E-9,"O.K.","NOT O.K.")'.replace("{Asr}", f"$G${S.r}"))
    S.put("Ascr", "A's ต้องการ =", f"=IF({sg},{{s_Asc}},{{d_Asc}})", "cm²",
          note='=IF({Asc}>={Ascr}-1E-9,"O.K.","NOT O.K.")'.replace("{Ascr}", f"$G${S.r}"))
    S.put("duct", "ρ (Singly) / ρ − ρ'f's/fy (Doubly) ≤ ρmax =", f"=IF({sg},{{rho}},{{d_duct}})", "", "0.0000",
          note=f'=IF(IF({sg},$G${S.r}<{{rmax}},$G${S.r}<={{rmax}}),"O.K.","NOT O.K.")')
    S.put("pMn", "φMn ≥ Mu =", f"=IF({sg},{{s_pMn}},{{d_pMn}})", "kg-m",
          note=f'=IF($G${S.r}>={{Mu}}-1E-6,"O.K.","NOT O.K.")')
    S.put("flex", "ดัด (1 = ผ่าน) =",
                 '=IF(AND({As}>={Asr}-1E-9,{Asc}>={Ascr}-1E-9,'
                 f'IF({sg},{{rho}}<{{rmax}},{{d_duct}}<={{rmax}}),{{pMn}}>={{Mu}}-1E-6,{{Asr}}<9999,{{Ascr}}<9999),1,0)',
                 "", "0")

    S.title("Shear Reinforcement")
    S.put("fys", "fy เหล็กปลอก =", "=IF({ds}>9,{fy},{fy_rb})", "ksc", "0")
    S.put("Av", "Av = ขา × πØ²/4 =", "={legs}*PI()*({ds}/10)^2/4", "cm²", "0.000")
    S.put("sfc", "√fc' =", "=SQRT({fc})", "", "0.0000")
    S.put("pVc", "φVc = φ0.53√fc'·bd =", "={phiv}*0.53*{sfc}*{B}*{d}", "kg")
    S.put("l11", "1.1φbd√fc' =", "=1.1*{phiv}*{B}*{d}*{sfc}", "kg")
    S.put("l21", "2.1φbd√fc' =", "=2.1*{phiv}*{B}*{d}*{sfc}", "kg")
    S.put("s1", "s1 = min(d/2, 60) =", "=MIN(0.5*{d},60)", "cm")
    S.put("s2", "s2 = min(Av·fy/(3.5b), d/2, 60) =", "=MIN({Av}*{fys}/(3.5*{B}),0.5*{d},60)", "cm")
    S.put("s4", "s4 = min(d/4, 30) =", "=MIN(0.25*{d},30)", "cm")
    zones = (("z", "Distance of 2H from Support", "Vu", "MIN({d}/4,8*{dbt}/10,24*{ds}/10,30)"),
             ("m", "Midspan", "Vum", "{d}/2"))
    for z, title, vu, eql in zones:
        S.title(title, BOLD)
        S.put(f"{z}V", "Vu =", f"={{{vu}}}", "kg")
        S.put(f"{z}pVs", "φVs = Vu − φVc =", f"={{{z}V}}-{{pVc}}", "kg")
        S.put(f"{z}case", "case (1–4; 5 = Revised) =",
              f"=IF({{{z}V}}<={{pVc}}/2,1,IF({{{z}V}}<{{pVc}},2,IF({{{z}pVs}}<={{l11}},3,IF({{{z}pVs}}<={{l21}},4,5))))",
              "", "0")
        S.put(f"{z}s3", "s3 = min(φAv·fy·d/φVs, d/2, 60) =",
              f"=IF({{{z}pVs}}>0,MIN({{phiv}}*{{Av}}*{{fys}}*{{d}}/{{{z}pVs}},0.5*{{d}},60),999)", "cm")
        S.put(f"{z}eq", "For EQ: s ≤", f"={eql}", "cm")
        S.put(f"{z}sc", "s ควบคุม =",
              f"=IF({{{z}case}}>4,0,MIN(CHOOSE({{{z}case}},{{s1}},{{s2}},MIN({{s1}},{{s2}},{{{z}s3}}),"
              f"MIN({{s1}},{{s2}},{{{z}s3}},{{s4}})),IF({{eq}}=1,{{{z}eq}},999)))", "cm")
        S.put(f"{z}s", "S ใช้ (ปัดลงทีละ 2.5) =", f"=INT({{{z}sc}}/2.5+1E-9)*2.5", "cm", "0.0",
              note=f'=IF(AND({{{z}case}}<=4,$G${S.r}>=2.5),"O.K.","Revised")')

    S.title("สรุป")
    S.put("ok", "ผ่านทั้งหมด (1 = ผ่าน) =",
          '=IF(AND({flex}=1,{pct}<={rlim}+1E-12,OR(COUNT(' + T["clear"] + "," + C["clear"] + ')=0,{cl}>={cmin}-1E-9),'
          'AND({zcase}<=4,{zs}>=2.5),AND({mcase}<=4,{ms}>=2.5)),1,0)', "", "0",
          note='=IF({ok}=1,"ผ่าน","ไม่ผ่าน")'.replace("{ok}", f"$G${S.r}"))
    for row in ws.iter_rows(min_row=1, max_row=S.r, max_col=1):
        row[0].alignment = Alignment(horizontal="left")
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0
    return S.cells


def _safe_title(t: str, used: set) -> str:
    t = re.sub(r"[\[\]:*?/\\]", "-", t)[:28] or "Sheet"
    base, k = t, 2
    while t in used:
        t = f"{base[:25]}~{k}"
        k += 1
    used.add(t)
    return t


def build_workbook(sections: list[tuple[str, SheetInput, dict]]) -> bytes:
    """sections: (sheet name, input, header).  First sheet = live summary of all sections."""
    wb = Workbook()
    summ = wb.active
    summ.title = "สรุป"
    heads = ["Sheet", "ชนิด", "Mu (kg-m)", "As (cm²)", "A's (cm²)", "d (cm)", "% ดึง", "ช่องว่างน้อยสุด",
             "φMn (kg-m)", "S 2H (cm)", "S กลาง (cm)", "ผล"]
    for j, h in enumerate(heads, 1):
        summ.cell(1, j, h).font = BOLD
        summ.column_dimensions[get_column_letter(j)].width = 14
    used: set = {"สรุป"}
    for i, (name, inp, head) in enumerate(sections, 2):
        title = _safe_title(name, used)
        ws = wb.create_sheet(title)
        cells = write_section(ws, inp, head)
        q = f"'{title}'!"
        summ.cell(i, 1, title)
        for j, key in enumerate(["kind", "Mu", "As", "Asc", "d", "pct", "cl", "pMn", "zs", "ms"], 2):
            c = summ.cell(i, j, f"={q}{cells[key]}")
            c.number_format = {"pct": "0.00%", "kind": "General"}.get(key, "#,##0.00")
        summ.cell(i, 12, f'=IF({q}{cells["ok"]}=1,"ผ่าน","ไม่ผ่าน")')
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


__all__ = ["build_workbook", "write_section", "MODES"]
