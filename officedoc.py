"""Word(.docx)・PowerPoint(.pptx)・Excel(.xlsx)を作る。AIが書いた中身(見出し・箇条書き・表の簡単な書式)を、
整ったデザインのファイルにする。すべてPCの中で行う(ネットは使わない)。

中身の書式(AIに書かせる形):
  # 題名            … 文書・発表の題名(1行目)
  ## 見出し          … Word: 見出し / PowerPoint: 1枚のスライド / Excel: シート
  ### 小見出し
  - 箇条書き(字下げで階層) / 1. 番号付き
  | 表 | の | 行 |   … 2行目は |---|---|
  > メモ             … PowerPoint: 話す人のメモ(ノート)
  **太字**
"""
import os
import re

FONT = "Yu Gothic UI"   # 日本語も英語も読みやすい Windows 標準の書体
FONT_DOC = "Yu Gothic"  # 文書の本文
NAVY, ACCENT, GRAY, LIGHT = (0x1F, 0x2A, 0x44), (0x2F, 0x6F, 0xEB), (0x5B, 0x64, 0x72), (0xF2, 0xF5, 0xFA)


# ---------------- 中身の読み取り ----------------
def parse(text):
    """書式つきの文 → {"title", "subtitle", "sections": [{"title", "blocks": [(種類, 中身)], "notes"}]}"""
    text = re.sub(r"^```\w*\n|\n```\s*$", "", text.strip())
    doc = {"title": "", "subtitle": "", "sections": []}
    cur = None
    table = None

    def section(title):
        nonlocal cur
        cur = {"title": title, "blocks": [], "notes": []}
        doc["sections"].append(cur)

    for raw in text.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if table is not None and not s.startswith("|"):
            cur["blocks"].append(("table", table))
            table = None
        if not s:
            continue
        if s.startswith("# ") and not doc["title"]:
            doc["title"] = s[2:].strip()
            continue
        if s.startswith("## "):
            section(s[3:].strip())
            continue
        if cur is None:
            if doc["title"] and not doc["subtitle"] and not s.startswith(("-", "*", "|", "#")):
                doc["subtitle"] = _plain(s)
                continue
            section("")
        if s.startswith("### "):
            cur["blocks"].append(("h3", s[4:].strip()))
        elif s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            table = (table or []) + [cells]
        elif s.startswith(">"):
            cur["notes"].append(_plain(s.lstrip("> ")))
        elif re.match(r"^[-*・]\s+", s):
            level = min(2, (len(line) - len(line.lstrip(" "))) // 2)
            cur["blocks"].append(("bullet", (level, re.sub(r"^[-*・]\s+", "", s))))
        elif re.match(r"^\d+[.)．]\s+", s):
            level = min(2, (len(line) - len(line.lstrip(" "))) // 2)
            cur["blocks"].append(("number", (level, re.sub(r"^\d+[.)．]\s+", "", s))))
        else:
            cur["blocks"].append(("text", s))
    if table is not None:
        cur["blocks"].append(("table", table))
    if not doc["title"]:
        doc["title"] = doc["sections"][0]["title"] if doc["sections"] else "資料"
    return doc


def _plain(s):
    return re.sub(r"\*\*(.+?)\*\*", r"\1", s).strip()


def _runs(s):
    """「**太字**」を分けて [(文字, 太字か)]"""
    out = []
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", s)):
        if part:
            out.append((part, i % 2 == 1))
    return out


def save_path(folder, name, ext):
    """同じ名前のファイルがあれば「(2)」などを付けて、上書きしない。"""
    name = re.sub(r'[\\/:*?"<>|]', "", name).strip() or "資料"
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name + ext)
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{name} ({n}){ext}")
        n += 1
    return path


# ---------------- PowerPoint ----------------
def _ea_font(run, name=FONT):
    """日本語の文字にも書体を指定する(指定しないと、日本語だけ別の書体になる)。"""
    from pptx.oxml.ns import qn
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea"):
        el = rpr.find(qn(tag))
        if el is None:
            el = rpr.makeelement(qn(tag), {})
            rpr.append(el)
        el.set("typeface", name)


def _text(frame, s, size, color=NAVY, bold=False, first=True, level=0, align=None):
    from pptx.dml.color import RGBColor
    from pptx.util import Pt
    p = frame.paragraphs[0] if first else frame.add_paragraph()
    p.level = level
    if align is not None:
        p.alignment = align
    for part, b in _runs(s):
        r = p.add_run()
        r.text = part
        r.font.size = Pt(size)
        r.font.bold = bold or b
        r.font.color.rgb = RGBColor(*color)
        _ea_font(r)
    return p


def _rect(slide, x, y, w, h, color):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(*color)
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def make_pptx(doc, path):
    from pptx import Presentation
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Inches, Pt
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)  # 16:9
    W, H = prs.slide_width, prs.slide_height
    blank = prs.slide_layouts[6]

    # 表紙: 濃い紺の背景に、題名と副題、細いアクセントの線
    s = prs.slides.add_slide(blank)
    _rect(s, 0, 0, W, H, NAVY)
    _rect(s, Inches(0.9), Inches(3.55), Inches(1.2), Emu(54000), ACCENT)
    box = s.shapes.add_textbox(Inches(0.9), Inches(1.6), W - Inches(1.8), Inches(1.9))
    box.text_frame.word_wrap = True
    box.text_frame.vertical_anchor = MSO_ANCHOR.BOTTOM
    _text(box.text_frame, doc["title"], 40, (0xFF, 0xFF, 0xFF), bold=True)
    if doc["subtitle"]:
        sub = s.shapes.add_textbox(Inches(0.9), Inches(3.8), W - Inches(1.8), Inches(1.2))
        sub.text_frame.word_wrap = True
        _text(sub.text_frame, doc["subtitle"], 18, (0xC9, 0xD3, 0xE6))

    total = len(doc["sections"])
    for i, sec in enumerate(doc["sections"], 1):
        s = prs.slides.add_slide(blank)
        _rect(s, 0, 0, Inches(0.18), H, ACCENT)  # 左の細い帯
        title = s.shapes.add_textbox(Inches(0.7), Inches(0.45), W - Inches(1.4), Inches(0.9))
        title.text_frame.word_wrap = True
        _text(title.text_frame, sec["title"] or doc["title"], 30, NAVY, bold=True)
        _rect(s, Inches(0.7), Inches(1.32), Inches(0.8), Emu(36000), ACCENT)
        # 下: ページ番号と題名
        foot = s.shapes.add_textbox(Inches(0.7), H - Inches(0.55), W - Inches(1.4), Inches(0.35))
        _text(foot.text_frame, f"{doc['title']}", 10, GRAY)
        num = s.shapes.add_textbox(W - Inches(1.6), H - Inches(0.55), Inches(0.9), Inches(0.35))
        _text(num.text_frame, f"{i} / {total}", 10, GRAY, align=PP_ALIGN.RIGHT)

        tables = [b for k, b in sec["blocks"] if k == "table"]
        lines = [(k, b) for k, b in sec["blocks"] if k != "table"]
        top, left, width = Inches(1.65), Inches(0.7), W - Inches(1.4)
        body_h = H - top - Inches(0.9)
        # 短い項目が数個だけなら、文の羅列ではなく図にする(手順は番号つきの流れ、要点はカード)
        items = [b for k, b in lines if k in ("bullet", "number") and b[0] == 0]
        rest = [(k, b) for k, b in lines if not (k in ("bullet", "number") and b[0] == 0)]
        if not tables and 2 <= len(items) <= 6 and not any(k in ("bullet", "number") for k, _ in rest) \
                and all(len(_plain(t)) <= 60 for _, t in items):
            steps = all(k == "number" for k, b in lines if k in ("bullet", "number"))
            used = (_steps if steps else _cards)(s, [t for _, t in items], left, top, W - Inches(1.4))
            top += used + Inches(0.3)
            body_h = H - top - Inches(0.9)
            lines = rest
        if lines and tables:  # 文と表: 左に文、右に表
            width = (W - Inches(1.6)) / 2
        if lines:
            box = s.shapes.add_textbox(left, top, width, body_h)
            tf = box.text_frame
            tf.word_wrap = True
            n = sum(1 for _ in lines)
            size = 22 if n <= 5 else 19 if n <= 8 else 16
            first, numbers = True, {}
            for k, b in lines:
                if k in ("bullet", "number"):
                    level, s_ = b
                    if k == "number":
                        numbers[level] = numbers.get(level, 0) + 1
                    mark = "•" if k == "bullet" else f"{numbers.get(level, 1)}."
                    p = _text(tf, (f"{mark}  " if mark and level == 0 else "– " if level else "") + s_,
                              size - 2 * level, NAVY if level == 0 else GRAY, first=first, level=level)
                elif k == "h3":
                    p = _text(tf, b, size + 1, ACCENT, bold=True, first=first)
                else:
                    p = _text(tf, b, size, NAVY, first=first)
                p.space_after = Pt(10 if size >= 18 else 6)
                first = False
        for t_index, rows in enumerate(tables[:1]):
            x = left + (width + Inches(0.2) if lines else 0)
            tw = (W - Inches(1.4)) - (width + Inches(0.2) if lines else 0)
            _pptx_table(s, rows, x, top, tw, min(body_h, Inches(0.6) * len(rows)))
        if sec["notes"]:
            s.notes_slide.notes_text_frame.text = "\n".join(sec["notes"])
    prs.save(path)
    return len(prs.slides._sldIdLst)


def _cards(slide, texts, x, y, w):
    """要点をカードにして並べる(3つまでは横1列、4〜6は2段)。返り値は使った高さ。"""
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR
    from pptx.util import Emu, Inches
    per_row = len(texts) if len(texts) <= 3 else (len(texts) + 1) // 2
    rows = (len(texts) + per_row - 1) // per_row
    gap = Inches(0.3)
    cw = (w - gap * (per_row - 1)) / per_row
    ch = Inches(3.3) if rows == 1 else Inches(2.15)
    for i, t in enumerate(texts):
        cx, cy = x + (cw + gap) * (i % per_row), y + (ch + gap) * (i // per_row)
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, int(cx), int(cy), int(cw), int(ch))
        card.adjustments[0] = 0.08
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor(*LIGHT)
        card.line.fill.background()
        card.shadow.inherit = False
        _rect(slide, int(cx), int(cy), int(cw), Emu(60000), ACCENT)
        num = slide.shapes.add_textbox(int(cx + Inches(0.3)), int(cy + Inches(0.25)), Inches(1), Inches(0.5))
        _text(num.text_frame, f"{i + 1:02d}", 16, ACCENT, bold=True)
        body = slide.shapes.add_textbox(int(cx + Inches(0.3)), int(cy + Inches(0.75)), int(cw - Inches(0.6)),
                                        int(ch - Inches(0.9)))
        body.text_frame.word_wrap = True
        body.text_frame.vertical_anchor = MSO_ANCHOR.TOP
        _text(body.text_frame, t, 22 if len(texts) <= 3 else 18, NAVY)
    return ch * rows + gap * (rows - 1)


def _steps(slide, texts, x, y, w):
    """手順: 番号の丸を線でつなぎ、下に説明を置く。返り値は使った高さ。"""
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Inches
    n = len(texts)
    step = w / n
    d = Inches(0.9)
    _rect(slide, int(x + step / 2), int(y + d / 2 - Emu(19000)), int(step * (n - 1)), Emu(38000), (0xC9, 0xD3, 0xE6))
    for i, t in enumerate(texts):
        cx = x + step * i + step / 2
        dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, int(cx - d / 2), int(y), int(d), int(d))
        dot.fill.solid()
        dot.fill.fore_color.rgb = RGBColor(*(ACCENT if i == 0 else NAVY))
        dot.line.fill.background()
        dot.shadow.inherit = False
        dot.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        _text(dot.text_frame, str(i + 1), 24, (0xFF, 0xFF, 0xFF), bold=True, align=PP_ALIGN.CENTER)
        body = slide.shapes.add_textbox(int(cx - step / 2 + Inches(0.1)), int(y + d + Inches(0.25)),
                                        int(step - Inches(0.2)), Inches(1.6))
        body.text_frame.word_wrap = True
        _text(body.text_frame, t, 17 if n <= 4 else 15, NAVY, align=PP_ALIGN.CENTER)
    return d + Inches(1.9)


def _pptx_table(slide, rows, x, y, w, h):
    from pptx.dml.color import RGBColor
    from pptx.util import Pt
    cols = max(len(r) for r in rows)
    shape = slide.shapes.add_table(len(rows), cols, x, y, w, h)
    table = shape.table
    for r, row in enumerate(rows):
        for c in range(cols):
            cell = table.cell(r, c)
            cell.text = ""
            p = cell.text_frame.paragraphs[0]
            run = p.add_run()
            run.text = _plain(row[c]) if c < len(row) else ""
            run.font.size = Pt(18 if len(rows) <= 6 else 14 if len(rows) <= 12 else 11)
            run.font.bold = r == 0
            run.font.color.rgb = RGBColor(*((0xFF, 0xFF, 0xFF) if r == 0 else NAVY))
            _ea_font(run)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(*(NAVY if r == 0 else LIGHT if r % 2 else (0xFF, 0xFF, 0xFF)))


# ---------------- Word ----------------
def _doc_font(style_or_run, name=FONT_DOC):
    from docx.oxml.ns import qn
    el = style_or_run.element
    rpr = el.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(fonts)
    for k in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(k), name)


def _add_runs(p, s, size=None, color=None):
    from docx.shared import Pt, RGBColor
    for part, b in _runs(s):
        r = p.add_run(part)
        r.bold = b or None
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = RGBColor(*color)
        _doc_font(r)
    return p


def make_docx(doc, path):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor
    d = Document()
    for sec in d.sections:
        sec.top_margin = sec.bottom_margin = Mm(22)
        sec.left_margin = sec.right_margin = Mm(24)
    normal = d.styles["Normal"]
    normal.font.size = Pt(10.5)
    _doc_font(normal)
    normal.paragraph_format.line_spacing = 1.35
    normal.paragraph_format.space_after = Pt(4)
    for name, size, color in (("Title", 22, NAVY), ("Heading 1", 15, NAVY), ("Heading 2", 12.5, ACCENT)):
        st = d.styles[name]
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = RGBColor(*color)
        _doc_font(st)
    d.styles["Heading 1"].paragraph_format.space_before = Pt(16)
    d.styles["Heading 2"].paragraph_format.space_before = Pt(10)

    t = d.add_paragraph(style="Title")
    _add_runs(t, doc["title"])
    _border(t, ACCENT)  # 題名の下に線
    if doc["subtitle"]:
        _add_runs(d.add_paragraph(), doc["subtitle"], 11, GRAY)

    for sec in doc["sections"]:
        if sec["title"]:
            _add_runs(d.add_paragraph(style="Heading 1"), sec["title"])
        for k, b in sec["blocks"]:
            if k == "h3":
                _add_runs(d.add_paragraph(style="Heading 2"), b)
            elif k in ("bullet", "number"):
                level, s = b
                style = ("List Bullet" if k == "bullet" else "List Number") + (f" {level + 1}" if level else "")
                _add_runs(d.add_paragraph(style=style), s)
            elif k == "table":
                _docx_table(d, b)
            else:
                _add_runs(d.add_paragraph(), b)
        for note in sec["notes"]:
            p = d.add_paragraph()
            _add_runs(p, note, 9.5, GRAY)
    # 下: ページ番号
    footer = d.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run()
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.text = text
        run._r.append(el)
    d.save(path)
    return sum(1 for _ in doc["sections"])


def _border(p, color):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    ppr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "12"), ("w:space", "4"), ("w:color", "%02X%02X%02X" % color)):
        bottom.set(qn(k), v)
    bdr.append(bottom)
    ppr.append(bdr)


def _shade(cell, color):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), "%02X%02X%02X" % color)
    tcpr.append(shd)


def _docx_table(d, rows):
    from docx.shared import Pt
    cols = max(len(r) for r in rows)
    table = d.add_table(rows=len(rows), cols=cols)
    table.style = "Table Grid"
    for r, row in enumerate(rows):
        for c in range(cols):
            cell = table.cell(r, c)
            cell.text = ""
            _add_runs(cell.paragraphs[0], _plain(row[c]) if c < len(row) else "", 10,
                      (0xFF, 0xFF, 0xFF) if r == 0 else None)
            if r == 0:
                for run in cell.paragraphs[0].runs:
                    run.bold = True
                _shade(cell, NAVY)
            elif r % 2 == 0:
                _shade(cell, LIGHT)
    d.add_paragraph().paragraph_format.space_after = Pt(2)


# ---------------- Excel ----------------
def _number(s):
    """「1,200」「¥3,000」「12.5%」→ 数(と表示の形)。数でなければ None。"""
    t = str(s).strip().replace(",", "").replace("，", "")
    m = re.fullmatch(r"([¥￥$])?(-?\d+(?:\.\d+)?)(%|％|円)?", t)
    if not m:
        return None
    value = float(m.group(2))
    if m.group(3) in ("%", "％"):
        return value / 100, "0.0%"
    if m.group(1) or m.group(3) == "円":
        return value, "¥#,##0"
    return (int(value) if value.is_integer() else value), ("#,##0" if value.is_integer() else "#,##0.00")


def _width(s):
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def make_xlsx(doc, path):
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    hex_ = lambda c: "%02X%02X%02X" % c  # noqa: E731
    thin = Side(style="thin", color="D5DBE5")
    sheets = [sec for sec in doc["sections"] if any(k == "table" for k, _ in sec["blocks"])] or doc["sections"]
    for n, sec in enumerate(sheets, 1):
        ws = wb.create_sheet(re.sub(r"[\\/*?:\[\]]", "", sec["title"] or doc["title"])[:31] or f"Sheet{n}")
        ws.sheet_view.showGridLines = False
        ws["A1"] = sec["title"] or doc["title"]
        ws["A1"].font = Font(name=FONT, size=15, bold=True, color=hex_(NAVY))
        row = 3
        widths = {}
        for k, b in sec["blocks"]:
            if k != "table":
                text = b[1] if isinstance(b, tuple) else b
                ws.cell(row=row, column=1, value=_plain(text)).font = Font(name=FONT, size=10, color=hex_(GRAY))
                row += 1
                continue
            cols = max(len(r) for r in b)
            head = row
            for r, values in enumerate(b):
                for c in range(cols):
                    raw = _plain(values[c]) if c < len(values) else ""
                    cell = ws.cell(row=row, column=c + 1)
                    num = _number(raw) if r else None
                    header = str(b[0][c]) if c < len(b[0]) else ""
                    if num and isinstance(num[0], int) and (c == 0 or re.search(r"年|year|id|番号|コード|no", header, re.I)):
                        num = (num[0], "0")  # 年・番号は「2,026」のように区切らない
                    if raw.startswith("="):
                        cell.value = raw  # 計算式はそのまま
                    elif num:
                        cell.value, cell.number_format = num
                    else:
                        cell.value = raw
                    cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
                    cell.alignment = Alignment(vertical="center", wrap_text=r == 0,
                                               horizontal="right" if num else "center" if r == 0 else "left")
                    if r == 0:
                        cell.font = Font(name=FONT, size=10, bold=True, color="FFFFFF")
                        cell.fill = PatternFill("solid", fgColor=hex_(NAVY))
                    else:
                        cell.font = Font(name=FONT, size=10, color=hex_(NAVY))
                        if r % 2 == 0:
                            cell.fill = PatternFill("solid", fgColor=hex_(LIGHT))
                    widths[c] = max(widths.get(c, 0), _width(raw))
                row += 1
            ws.row_dimensions[head].height = 22
            if ws.freeze_panes is None or ws.freeze_panes == "A1":
                ws.freeze_panes = ws.cell(row=head + 1, column=1)
            ws.auto_filter.ref = f"A{head}:{get_column_letter(cols)}{row - 1}"
            # 1列目が名前、ほかが数の表は、棒グラフを右に添える
            numeric = [c for c in range(2, cols + 1)
                       if all(isinstance(ws.cell(row=r, column=c).value, (int, float)) for r in range(head + 1, row))]
            # 単位の違う列(金額と%など)は同じグラフにしない: 最初の数の列と同じ表示の形の列だけ
            if numeric:
                fmt = ws.cell(row=head + 1, column=numeric[0]).number_format
                numeric = [c for c in numeric if ws.cell(row=head + 1, column=c).number_format == fmt and "%" not in fmt]
            if numeric and 2 <= row - head - 1 <= 30:
                chart = BarChart()
                chart.title = sec["title"] or doc["title"]
                chart.style = 10
                chart.height, chart.width = 7.5, 15
                for c in numeric[:4]:
                    chart.add_data(Reference(ws, min_col=c, min_row=head, max_row=row - 1), titles_from_data=True)
                chart.set_categories(Reference(ws, min_col=1, min_row=head + 1, max_row=row - 1))
                chart.legend.position = "b"
                ws.add_chart(chart, f"{get_column_letter(cols + 2)}{head}")
            row += 2
        for c, w in widths.items():
            ws.column_dimensions[get_column_letter(c + 1)].width = min(60, max(10, w + 4))
    wb.save(path)
    return len(wb.sheetnames)


MAKERS = {"pptx": make_pptx, "docx": make_docx, "xlsx": make_xlsx}
