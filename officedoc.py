"""Word(.docx)・PowerPoint(.pptx)・Excel(.xlsx)を作る。AIが書いた中身を、人が見て自然で読みやすいデザインのファイルにする。

中身の書式(AIに書かせる形):
  # 題名            … 文書・発表の題名(1行目)。2行目の普通の文は副題
  ## 見出し          … Word: 章 / PowerPoint: 1枚のスライド / Excel: シート
  ### 小見出し
  - 箇条書き(字下げで階層) / 1. 番号付き
  | 表 | の | 行 |   … 2行目は |---|---|
  > メモ             … PowerPoint: 話す人のメモ / Word: 補足の囲み
  !画像: 英語の検索語 … そのページに写真を入れる(Wikimedia Commons の、使ってよい許可が明記された画像だけ)
  **太字**
  「## 出典」の章は、参考にしたページの一覧として最後にまとめる

見た目の決まり:
- 書体は Windows に入っている実在のもの(Yu Gothic UI / Yu Gothic / Consolas)だけ
- 配色は紺・青・薄い灰の3系統に限り、文字と背景の明るさの差を十分にとる
- 文字の量から大きさを決め、はみ出し・不自然な空白を作らない。入りきらなければ次のページへ分ける
- 内容に合わせて、カード・手順図・数字の強調・表とグラフ・写真つき などを使い分け、文字だけのページを続けない
"""
import os
import re
import unicodedata

FONT = "Yu Gothic UI"   # Windows 8.1 以降に標準で入っている書体
FONT_DOC = "Yu Gothic"
MONO = "Consolas"
NAVY = (0x1F, 0x2A, 0x44)
ACCENT = (0x2F, 0x6F, 0xEB)
ACCENT_SOFT = (0xDC, 0xE7, 0xFD)
GRAY = (0x5B, 0x64, 0x72)
LIGHT = (0xF3, 0xF6, 0xFB)
WHITE = (0xFF, 0xFF, 0xFF)
LINE = (0xC9, 0xD3, 0xE6)
_SOURCES = re.compile(r"出典|参考(?:文献|資料|URL|サイト)?$|sources?|references?", re.I)


# ---------------- 中身の読み取りと整え ----------------
def parse(text):
    """書式つきの文 → {"title", "subtitle", "sections": [{"title", "blocks", "notes"}], "sources": [...]}"""
    text = re.sub(r"^```\w*\n|\n```\s*$", "", text.strip())
    doc = {"title": "", "subtitle": "", "sections": [], "sources": []}
    cur, table = None, None

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
        if not s or re.fullmatch(r"[-=_*]{3,}", s):
            continue
        if s.startswith("# ") and not doc["title"]:
            doc["title"] = _clean(s[2:])
            continue
        if s.startswith("## "):
            section(_clean(s[3:]))
            continue
        if cur is None:
            if doc["title"] and not doc["subtitle"] and not s.startswith(("-", "*", "|", "#", "!", ">")):
                doc["subtitle"] = _clean(_plain(s))
                continue
            section("")
        m = re.match(r"^!\s*(?:画像|image|写真)\s*[:：]\s*(.+)$", s, re.I)
        if m:
            cur["blocks"].append(("image", m.group(1).strip()))
        elif s.startswith("### "):
            cur["blocks"].append(("h3", _clean(s[4:])))
        elif s.startswith("|"):
            cells = [_clean(c) for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            table = (table or []) + [cells]
        elif s.startswith(">"):
            cur["notes"].append(_clean(_plain(s.lstrip("> "))))
        elif re.match(r"^[-*・•]\s+", s):
            level = min(2, (len(line) - len(line.lstrip(" "))) // 2)
            cur["blocks"].append(("bullet", (level, _clean(re.sub(r"^[-*・•]\s+", "", s)))))
        elif re.match(r"^\d+[.)．]\s+", s):
            level = min(2, (len(line) - len(line.lstrip(" "))) // 2)
            cur["blocks"].append(("number", (level, _clean(re.sub(r"^\d+[.)．]\s+", "", s)))))
        else:
            cur["blocks"].append(("text", _clean(s)))
    if table is not None:
        cur["blocks"].append(("table", table))
    polish(doc)
    if not doc["title"]:
        doc["title"] = doc["sections"][0]["title"] if doc["sections"] else "資料"
    return doc


def _clean(s):
    """全角の英数字を半角に、余分な空白や記号を整える(日本語の句読点はそのまま)。"""
    s = "".join(unicodedata.normalize("NFKC", c) if re.match(r"[０-９Ａ-Ｚａ-ｚ　]", c) else c for c in str(s))
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"^(?:\*\*)?\s*(.*?)\s*(?:\*\*)?$", lambda m: m.group(0) if m.group(0).count("**") % 2 == 0
               else m.group(1), s)
    return re.sub(r"([。、！？])\1+", r"\1", s)


def _plain(s):
    return re.sub(r"\*\*(.+?)\*\*", r"\1", str(s)).strip()


def _key(s):
    return re.sub(r"[\s、。・,.!！?？「」()（）]", "", _plain(s)).lower()


def polish(doc):
    """重複した項目・章を除き、箇条書きの終わり方をそろえ、空の章をなくす。出典の章は一覧にする。"""
    seen, merged = set(), []
    for sec in doc["sections"]:
        if _SOURCES.search(sec["title"] or ""):
            for k, b in sec["blocks"]:
                text = b[1] if isinstance(b, tuple) else b
                if k != "table" and text and text not in doc["sources"]:
                    doc["sources"].append(_plain(text))
            continue
        same = next((m for m in merged if sec["title"] and _key(m["title"]) == _key(sec["title"])), None)
        blocks = []
        for k, b in sec["blocks"]:
            if k in ("bullet", "number", "text"):
                text = b[1] if isinstance(b, tuple) else b
                if k == "bullet":
                    text = text.rstrip("。")  # 箇条書きは体言止め・言い切りにそろえる
                    b = (b[0], text)
                key = _key(text)
                if not key or key in seen:  # 同じことを二度書かない
                    continue
                seen.add(key)
            blocks.append((k, b))
        if same:
            same["blocks"] += blocks
            same["notes"] += sec["notes"]
        else:
            sec["blocks"] = blocks
            if sec["blocks"] or sec["notes"]:
                merged.append(sec)
    doc["sections"] = [s for s in merged if s["blocks"]]
    return doc


def _runs(s):
    """「**太字**」を分けて [(文字, 太字か)]"""
    return [(part, i % 2 == 1) for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", s)) if part]


def save_path(folder, name, ext):
    """同じ名前のファイルがあれば「(2)」などを付けて、上書きしない。"""
    name = re.sub(r'[\\/:*?"<>|\r\n]', "", name).strip()[:60] or "資料"
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name + ext)
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{name} ({n}){ext}")
        n += 1
    return path


def _units(s):
    """文字の幅(全角=1、半角=0.55)。"""
    return sum(1.0 if unicodedata.east_asian_width(c) in "WFA" else 0.55 for c in _plain(s))


def _lines(s, width_in, size_pt):
    """幅 width_in(インチ)・大きさ size_pt の文字が何行になるか。"""
    per_line = max(1.0, width_in * 72 / size_pt * 0.96)
    return max(1, -(-_units(s) // per_line))


def _number(s):
    """「1,200」「¥3,000」「12.5%」→ (数, 表示の形)。数でなければ None。"""
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


def numeric_table(rows):
    """1列目が項目名、ほかの列の一部が数の表か。(数の列の番号の一覧) を返す。"""
    if len(rows) < 3:
        return []
    cols = max(len(r) for r in rows)
    out = []
    for c in range(1, cols):
        vals = [_number(r[c]) if c < len(r) else None for r in rows[1:]]
        if all(vals) and len({v[1] for v in vals}) == 1 and "%" not in vals[0][1]:
            out.append(c)
    return out


# ---------------- 画像(使ってよい許可が明記されたものだけ) ----------------
_OK_LICENSES = re.compile(r"^(?:CC0|Public domain|PD|CC BY(?:-SA)? [0-9.]+|CC BY(?:-SA)?)", re.I)
_UA = "Zealous/1.2 (desktop assistant; https://github.com/hiirocreate/zealous-releases)"


def commons_image(query, folder):
    """Wikimedia Commons から、許可(CC0・パブリックドメイン・CC BY・CC BY-SA)が明記された写真を1枚取る。
    {"path", "credit", "url"} または None。作者とライセンスは、必ず資料に書き添える。"""
    import json
    import urllib.parse
    import urllib.request
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 10,
              "gsrsearch": f"{query} filetype:bitmap", "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
              "iiurlwidth": 1600}
    req = urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=12) as r:
        pages = sorted((json.load(r).get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = re.sub(r"<[^>]+>", "", (meta.get("LicenseShortName") or {}).get("value", "")).strip()
        if info.get("mime") not in ("image/jpeg", "image/png") or info.get("width", 0) < 800 or not _OK_LICENSES.match(lic):
            continue
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip() or "作者不明"
        url = info.get("thumburl") or info.get("url")
        ext = ".png" if info["mime"] == "image/png" else ".jpg"
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"img_{abs(hash(url)) % 10 ** 8}{ext}")
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": _UA}), timeout=20) as r:
            data = r.read(15_000_000)
        with open(path, "wb") as f:
            f.write(data)
        return {"path": path, "credit": f"写真: {artist[:40]} / {lic} / Wikimedia Commons",
                "url": info.get("descriptionurl") or url}
    return None


def attach_images(doc, folder, limit=3):
    """「!画像:」の場所に写真を入れる(取れなければ、その行は使わない)。出典に写真の元のページも足す。"""
    used = 0
    for sec in doc["sections"]:
        blocks = []
        for k, b in sec["blocks"]:
            if k == "image":
                pic = None
                if used < limit:
                    try:
                        pic = commons_image(b, folder)
                    except Exception:
                        pic = None
                if pic:
                    used += 1
                    blocks.append(("picture", pic))
                    if pic["url"] not in doc["sources"]:
                        doc["sources"].append(f"{pic['credit']} {pic['url']}")
                continue
            blocks.append((k, b))
        sec["blocks"] = blocks
    return used


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


def _text(frame, s, size, color=NAVY, bold=False, first=True, level=0, align=None, space=None):
    from pptx.dml.color import RGBColor
    from pptx.util import Pt
    p = frame.paragraphs[0] if first else frame.add_paragraph()
    p.level = level
    if align is not None:
        p.alignment = align
    if space is not None:
        p.space_after = Pt(space)
    p.line_spacing = 1.15
    for part, b in _runs(s):
        r = p.add_run()
        r.text = part
        r.font.size = Pt(size)
        r.font.bold = bold or b
        r.font.color.rgb = RGBColor(*color)
        _ea_font(r)
    return p


def _box(slide, x, y, w, h, anchor=None):
    from pptx.enum.text import MSO_ANCHOR
    from pptx.util import Emu
    tb = slide.shapes.add_textbox(int(x), int(y), int(w), int(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    tf.vertical_anchor = anchor if anchor is not None else MSO_ANCHOR.TOP
    return tf


def _rect(slide, x, y, w, h, color, rounded=False):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
                                   int(x), int(y), int(w), int(h))
    if rounded:
        shape.adjustments[0] = 0.06
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(*color)
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def _picture(slide, pic, x, y, w, h, credit_color=GRAY):
    """写真を枠いっぱいに(縦横比を保って余分を切り取る)入れ、下に作者とライセンスを添える。"""
    from PIL import Image
    from pptx.util import Pt
    with Image.open(pic["path"]) as im:
        iw, ih = im.size
    shape = slide.shapes.add_picture(pic["path"], int(x), int(y), int(w), int(h))
    box, img = w / h, iw / ih
    if img > box:  # 横に長い: 左右を切る
        cut = (1 - box / img) / 2
        shape.crop_left = shape.crop_right = cut
    else:
        cut = (1 - img / box) / 2
        shape.crop_top = shape.crop_bottom = cut
    tf = _box(slide, x, y + h + Pt(4), w, Pt(14))
    _text(tf, pic["credit"], 8, credit_color)


def _fit(items, width_in, height_in, sizes=(24, 22, 20, 18, 16, 15, 14)):
    """[(文, 階層)] が枠に収まる、いちばん大きい文字の大きさ(収まらなければ None)。"""
    for size in sizes:
        total = 0.0
        for text, level in items:
            s = size - 2 * level
            total += _lines(text, width_in - 0.35 * (level + 1), s) * s * 1.2 / 72 + s * 0.45 / 72
        if total <= height_in:
            return size
    return None


def make_pptx(doc, path):
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)  # 16:9
    deck = _Deck(prs, doc)
    deck.cover()
    for sec in doc["sections"]:
        deck.section(sec)
    if doc["sources"]:
        deck.sources()
    deck.finish()
    prs.save(path)
    return len(prs.slides._sldIdLst)


class _Deck:
    def __init__(self, prs, doc):
        from pptx.util import Inches
        self.prs, self.doc = prs, doc
        self.W, self.H = prs.slide_width, prs.slide_height
        self.blank = prs.slide_layouts[6]
        self.margin = Inches(0.75)
        self.pages = []  # ページ番号を最後に入れるため

    def finish(self):
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Inches
        total = len(self.pages)
        for i, s in enumerate(self.pages, 1):
            _text(_box(s, self.margin, self.H - Inches(0.5), Inches(8), Inches(0.3)), self.doc["title"], 10, GRAY)
            _text(_box(s, self.W - self.margin - Inches(1.2), self.H - Inches(0.5), Inches(1.2), Inches(0.3)),
                  f"{i} / {total}", 10, GRAY, align=PP_ALIGN.RIGHT)

    def cover(self):
        from pptx.enum.text import MSO_ANCHOR
        from pptx.util import Emu, Inches
        s = self.prs.slides.add_slide(self.blank)
        _rect(s, 0, 0, self.W, self.H, NAVY)
        # 最初の写真は表紙に使う(同じ写真を二度使わない。Word など、ほかの形で作るときのために中身は変えない)
        pic = next((b for sec in self.doc["sections"] for k, b in sec["blocks"] if k == "picture"), None)
        self.cover_pic = pic
        text_w = self.W - self.margin * 2
        if pic:  # 写真があれば右に大きく
            pw = int(self.W * 0.42)
            _picture(s, pic, self.W - pw, 0, pw, self.H - Inches(0.3), credit_color=LINE)
            text_w = self.W - pw - self.margin * 2
        title, tw = self.doc["title"], text_w / 914400
        # 1行に収まるいちばん大きい大きさ(32以上)。無理なら2行に収まる大きさ
        size = next((z for z in (44, 40, 36, 32) if _lines(title, tw, z) == 1), None) or \
            next((z for z in (40, 36, 32, 28, 24) if _lines(title, tw, z) <= 2), 22)
        _text(_box(s, self.margin, Inches(1.4), text_w, Inches(2.4), MSO_ANCHOR.BOTTOM), self.doc["title"], size, WHITE,
              bold=True)
        _rect(s, self.margin, Inches(4.0), Inches(1.1), Emu(54000), ACCENT)
        if self.doc["subtitle"]:
            _text(_box(s, self.margin, Inches(4.3), text_w, Inches(1.6)), self.doc["subtitle"], 18, (0xC9, 0xD3, 0xE6))

    def page(self, title, dark=False):
        from pptx.enum.text import MSO_ANCHOR
        from pptx.util import Emu, Inches
        s = self.prs.slides.add_slide(self.blank)
        if dark:
            _rect(s, 0, 0, self.W, self.H, NAVY)
        _rect(s, 0, 0, Inches(0.16), self.H, ACCENT)
        size = 30 if _units(title) <= 24 else 26 if _units(title) <= 34 else 22
        _text(_box(s, self.margin, Inches(0.45), self.W - self.margin * 2, Inches(0.85), MSO_ANCHOR.BOTTOM), title,
              size, WHITE if dark else NAVY, bold=True)
        _rect(s, self.margin, Inches(1.42), Inches(0.9), Emu(36000), ACCENT)
        self.pages.append(s)
        return s

    # 本文の場所
    @property
    def body(self):
        from pptx.util import Inches
        top = Inches(1.8)
        return self.margin, top, self.W - self.margin * 2, self.H - top - Inches(0.8)

    def section(self, sec):
        title = sec["title"] or self.doc["title"]
        blocks = [(k, b) for k, b in sec["blocks"] if not (k == "picture" and b is getattr(self, "cover_pic", None))]
        tables = [b for k, b in blocks if k == "table"]
        pics = [b for k, b in blocks if k == "picture"]
        lines = [(k, b) for k, b in blocks if k in ("bullet", "number", "text", "h3")]
        top_items = [b for k, b in lines if k in ("bullet", "number") and b[0] == 0]
        subs = [b for k, b in lines if k in ("bullet", "number") and b[0] > 0]
        others = [(k, b) for k, b in lines if k in ("text", "h3")]
        closing = re.search(r"まとめ|おわりに|結論|summary|conclusion", title, re.I) and not tables
        for rows in tables:
            self.table(title, rows, [(k, b) for k, b in lines])
            lines = []
        if not lines:
            if pics and not tables:
                self.photo(title, pics[0], [])
            self._notes(sec)
            return
        short = all(_units(t) <= 46 for _, t in top_items) and not any(k == "h3" for k, _ in others)
        nums = [t for _, t in top_items if re.search(r"\d", t)]
        if closing:
            self.bullets(title, lines, dark=True)
        elif pics:
            self.photo(title, pics[0], lines)
        elif top_items and not subs and 2 <= len(top_items) <= 6 and short and all(k == "number" for k, _ in lines
                                                                                    if k in ("bullet", "number")):
            self.steps(title, [t for _, t in top_items], others)
        elif top_items and not subs and 2 <= len(top_items) <= 4 and len(nums) == len(top_items) and short:
            self.stats(title, [t for _, t in top_items], others)
        elif top_items and not subs and 2 <= len(top_items) <= 6 and short:
            self.cards(title, [t for _, t in top_items], others)
        else:
            self.bullets(title, lines)
        self._notes(sec)

    def _notes(self, sec):
        if sec["notes"] and self.pages:
            self.pages[-1].notes_slide.notes_text_frame.text = "\n".join(sec["notes"])

    # ---- 種類ごとのページ ----
    def bullets(self, title, lines, dark=False, cont=False):
        """箇条書き: 文字の量から大きさを決める。入りきらなければ2ページに分ける。"""
        from pptx.dml.color import RGBColor
        from pptx.util import Emu, Pt
        x, y, w, h = self.body
        items = []
        for k, b in lines:
            level, text = b if isinstance(b, tuple) else (0, b)
            items.append((k, level, text))
        sizes = (28, 26, 24, 22, 20, 18, 16, 15, 14) if len(items) <= 4 else (24, 22, 20, 18, 16, 15, 14)
        size = _fit([(t, lv) for _, lv, t in items], w / 914400, h / 914400, sizes)
        if size is None and len(items) > 1:  # 多すぎる: 半分ずつ2ページに
            half = (len(items) + 1) // 2
            while half < len(items) and items[half][1] > 0:
                half += 1  # 小項目は親と同じページに
            self.bullets(title, [(k, (lv, t)) for k, lv, t in items[:half]], dark, cont)
            self.bullets(f"{title}（続き）", [(k, (lv, t)) for k, lv, t in items[half:]], dark, True)
            return
        size = size or 14
        s = self.page(title, dark)
        used = sum(_lines(t, w / 914400 - 0.35 * (lv + 1), size - 2 * lv) * (size - 2 * lv) * 1.2 / 72 + (size - 2 * lv)
                   * 0.45 / 72 for _, lv, t in items)
        y0 = y + max(0, int((h - Emu(int(used * 914400))) * 0.35))  # 少ないときは少し下げて、上だけに寄らないように
        tf = _box(s, x, y0, w, h)
        numbers, first = {}, True
        fg, sub = (WHITE, (0xC9, 0xD3, 0xE6)) if dark else (NAVY, GRAY)
        for k, lv, t in items:
            sz = size - 2 * lv
            if k == "h3":
                _text(tf, t, sz + 2, ACCENT if not dark else (0x9C, 0xBC, 0xFF), bold=True, first=first, space=sz * 0.3)
            elif k == "text":
                _text(tf, t, sz, fg, first=first, space=sz * 0.45)
            else:
                if k == "number":
                    numbers[lv] = numbers.get(lv, 0) + 1
                    for deeper in [d for d in numbers if d > lv]:
                        numbers.pop(deeper)
                mark = f"{numbers[lv]}." if k == "number" else ("■" if lv == 0 else "–")
                p = tf.paragraphs[0] if first else tf.add_paragraph()
                p.level, p.line_spacing, p.space_after = lv, 1.15, Pt(sz * 0.45)
                self._mark(p, mark, sz, ACCENT if lv == 0 and not dark else sub)
                for part, b in _runs(t):
                    r = p.add_run()
                    r.text = part
                    r.font.size = Pt(sz)
                    r.font.bold = b
                    r.font.color.rgb = RGBColor(*(fg if lv == 0 else sub))
                    _ea_font(r)
            first = False

    @staticmethod
    def _mark(p, mark, size, color):
        from pptx.dml.color import RGBColor
        from pptx.util import Pt
        r = p.add_run()
        r.text = mark + "  "
        r.font.size = Pt(size * (0.6 if mark == "■" else 1))
        r.font.bold = True
        r.font.color.rgb = RGBColor(*color)
        _ea_font(r)

    def _footer_text(self, s, others, y, h):
        """図の下に、補足の文を薄い囲みで添える。"""
        from pptx.util import Inches
        if not others:
            return
        x, _, w, _ = self.body
        text = "  ".join(_plain(b if not isinstance(b, tuple) else b[1]) for _, b in others)
        size = 16 if _lines(text, w / 914400 - 0.6, 16) <= 2 else 14
        lines = _lines(text, w / 914400 - 0.6, size)
        bh = min(h, Inches(0.3) + int(lines * size * 1.25 / 72 * 914400))
        _rect(s, x, y, w, bh, LIGHT, rounded=True)
        _rect(s, x, y, Inches(0.07), bh, ACCENT)
        _text(_box(s, x + Inches(0.3), y + Inches(0.15), w - Inches(0.6), bh - Inches(0.2)), text, size, NAVY)

    def cards(self, title, texts, others):
        """要点をカードに(3つまでは横1列、4〜6は2段)。"""
        from pptx.util import Emu, Inches
        s = self.page(title)
        x, y, w, h = self.body
        extra = Inches(1.2) if others else 0
        per_row = len(texts) if len(texts) <= 3 else (len(texts) + 1) // 2
        rows = -(-len(texts) // per_row)
        gap = Inches(0.3)
        cw = (w - gap * (per_row - 1)) / per_row
        ch = min(Inches(3.4), (h - extra - gap * (rows - 1)) / rows)
        size = _fit_cards(texts, cw / 914400 - 0.6, ch / 914400 - 1.0)
        need = max(_lines(t, cw / 914400 - 0.6, size) for t in texts) * size * 1.3 / 72
        ch = min(ch, max(Inches(1.2 + need + 0.5), int(h * 0.55) if rows == 1 else 0))  # 文の量に合わせた高さ
        y += int((h - extra - ch * rows - gap * (rows - 1)) * 0.35)
        for i, t in enumerate(texts):
            cx, cy = x + (cw + gap) * (i % per_row), y + (ch + gap) * (i // per_row)
            _rect(s, cx, cy, cw, ch, LIGHT, rounded=True)
            _rect(s, cx, cy, cw, Emu(60000), ACCENT)
            _text(_box(s, cx + Inches(0.3), cy + Inches(0.3), Inches(1), Inches(0.45)), f"{i + 1:02d}", 18, ACCENT,
                  bold=True)
            _text(_box(s, cx + Inches(0.3), cy + Inches(0.85), cw - Inches(0.6), ch - Inches(1.0)), t, size, NAVY)
        self._footer_text(s, others, y + ch * rows + gap * (rows - 1) + Inches(0.3), extra)

    def stats(self, title, texts, others):
        """数字が主役の項目: 数字を大きく、説明を下に。"""
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Inches
        s = self.page(title)
        x, y, w, h = self.body
        gap = Inches(0.3)
        cw = (w - gap * (len(texts) - 1)) / len(texts)
        ch = min(Inches(3.4), h - (Inches(1.3) if others else 0))
        y += int((h - ch - (Inches(1.3) if others else 0)) * 0.35)  # 上だけに寄らないように
        for i, t in enumerate(texts):
            cx = x + (cw + gap) * i
            plain = _plain(t)
            m = re.search(r"[¥$]?\d[\d,.]*\s*(?:%|％|倍|円|万円|億円|件|人|社|時間|分|日|か月|ヶ月|年|個|台|点|位)?", plain)
            big = m.group(0).strip()
            # 数字が文の端にあるときだけ説明から外す(途中なら、文をそのまま説明にする)
            rest = (plain[:m.start()] + plain[m.end():]).strip(" 、:：") if m.start() == 0 or m.end() == len(plain) \
                else plain
            _rect(s, cx, y, cw, ch, LIGHT, rounded=True)
            size = 54 if _units(big) <= 5 else 40 if _units(big) <= 8 else 30
            _text(_box(s, cx + Inches(0.2), y + Inches(0.45), cw - Inches(0.4), Inches(1.2)), big, size, ACCENT,
                  bold=True, align=PP_ALIGN.CENTER)
            _text(_box(s, cx + Inches(0.3), y + Inches(1.8), cw - Inches(0.6), ch - Inches(1.95)), rest or t,
                  20 if _units(rest) <= 16 else 17 if _units(rest) <= 30 else 15, NAVY, align=PP_ALIGN.CENTER)
        self._footer_text(s, others, y + ch + Inches(0.3), h - ch - Inches(0.3))

    def steps(self, title, texts, others):
        """手順: 番号の丸を線でつなぎ、下に説明。"""
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
        from pptx.util import Emu, Inches
        s = self.page(title)
        x, y, w, h = self.body
        n = len(texts)
        step = w / n
        d = Inches(0.95)
        y += int((h - d - Inches(2.3) - (Inches(1.2) if others else 0)) * 0.4)
        _rect(s, x + step / 2, y + d / 2 - Emu(19000), step * (n - 1), Emu(38000), LINE)
        size = 18 if all(_lines(t, step / 914400 - 0.3, 18) <= 3 for t in texts) else 15
        for i, t in enumerate(texts):
            cx = x + step * i + step / 2
            dot = s.shapes.add_shape(MSO_SHAPE.OVAL, int(cx - d / 2), int(y), int(d), int(d))
            dot.fill.solid()
            dot.fill.fore_color.rgb = RGBColor(*(ACCENT if i == 0 else NAVY))
            dot.line.fill.background()
            dot.shadow.inherit = False
            dot.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            _text(dot.text_frame, str(i + 1), 26, WHITE, bold=True, align=PP_ALIGN.CENTER)
            _text(_box(s, cx - step / 2 + Inches(0.15), y + d + Inches(0.3), step - Inches(0.3), Inches(1.8)), t, size,
                  NAVY, align=PP_ALIGN.CENTER)
        self._footer_text(s, others, y + d + Inches(2.3), h - d - Inches(2.5))

    def photo(self, title, pic, lines):
        """写真つき: 左に文、右に写真(文が無ければ写真を大きく)。"""
        from pptx.util import Inches
        if not lines:
            s = self.page(title)
            x, y, w, h = self.body
            _picture(s, pic, x, y, w, h - Inches(0.3))
            return
        x, y, w, h = self.body
        pw = int(w * 0.45)
        items = [(b[1] if isinstance(b, tuple) else b, b[0] if isinstance(b, tuple) else 0) for _, b in lines]
        size = _fit(items, (w - pw - Inches(0.4)) / 914400, h / 914400) or 14
        s = self.page(title)
        tf = _box(s, x, y, w - pw - Inches(0.4), h)
        first = True
        for (k, b), (t, lv) in zip(lines, items):
            prefix = "■  " if k == "bullet" and lv == 0 else "–  " if lv else ""
            _text(tf, prefix + t, size - 2 * lv, NAVY if lv == 0 else GRAY, first=first, level=lv,
                  space=(size - 2 * lv) * 0.45)
            first = False
        _picture(s, pic, x + w - pw, y, pw, h - Inches(0.35))

    def table(self, title, rows, lines):
        """表: 数の表なら右にグラフを添える。行が多ければ複数ページに分ける(見出しの行はどのページにも)。"""
        from pptx.chart.data import CategoryChartData
        from pptx.dml.color import RGBColor
        from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
        from pptx.util import Inches, Pt
        head, body = rows[0], rows[1:]
        per = 9
        chunks = [body[i:i + per] for i in range(0, len(body), per)] or [[]]
        num_cols = numeric_table(rows) if len(body) <= per else []
        for n, chunk in enumerate(chunks):
            s = self.page(title if n == 0 else f"{title}（続き）")
            x, y, w, h = self.body
            if lines and n == 0:
                text = "  ".join(_plain(b[1] if isinstance(b, tuple) else b) for _, b in lines)
                _text(_box(s, x, y, w, Inches(0.6)), text, 16, GRAY)
                y += Inches(0.75)
                h -= Inches(0.75)
            tw = int(w * 0.52) if num_cols else w
            _pptx_table(s, [head] + chunk, x, y, tw, min(h, Inches(0.55) * (len(chunk) + 1)))
            if num_cols:
                data = CategoryChartData()
                data.categories = [_plain(r[0]) for r in chunk]
                for c in num_cols[:3]:
                    data.add_series(_plain(head[c]) if c < len(head) else f"系列{c}",
                                    [_number(r[c])[0] for r in chunk])
                gx = x + tw + Inches(0.4)
                chart = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, int(gx), int(y), int(w - tw - Inches(0.4)),
                                           int(min(h, Inches(4.6))), data).chart
                chart.has_legend = len(num_cols) > 1
                if chart.has_legend:
                    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
                    chart.legend.include_in_layout = False
                chart.font.size = Pt(11)
                chart.font.name = FONT
                chart.value_axis.has_major_gridlines = True
                chart.value_axis.major_gridlines.format.line.color.rgb = RGBColor(*LINE)
                chart.value_axis.format.line.fill.background()
                colors = [ACCENT, NAVY, (0x7F, 0xA7, 0xF5)]
                for i, series in enumerate(chart.plots[0].series):
                    series.format.fill.solid()
                    series.format.fill.fore_color.rgb = RGBColor(*colors[i % 3])
                chart.plots[0].gap_width = 80

    def sources(self):
        """出典のページ(参考にしたページと、写真の作者・ライセンス)。"""
        s = self.page("出典")
        x, y, w, h = self.body
        items = self.doc["sources"][:14]
        size = 14 if len(items) <= 8 else 12
        tf = _box(s, x, y, w, h)
        for i, src in enumerate(items):
            _text(tf, f"[{i + 1}] {src}", size, GRAY, first=i == 0, space=6)


def _fit_cards(texts, width_in, height_in):
    for size in (22, 20, 18, 16, 15, 14):
        if all(_lines(t, width_in, size) * size * 1.25 / 72 <= height_in for t in texts):
            return size
    return 13


def _pptx_table(slide, rows, x, y, w, h):
    from pptx.dml.color import RGBColor
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Pt
    cols = max(len(r) for r in rows)
    shape = slide.shapes.add_table(len(rows), cols, int(x), int(y), int(w), int(h))
    table = shape.table
    # 列の幅: 中身の長さに合わせる(ただし極端にしない)
    lens = [max(4.0, min(24.0, max(_units(r[c]) if c < len(r) else 0 for r in rows))) for c in range(cols)]
    for c in range(cols):
        table.columns[c].width = int(w * lens[c] / sum(lens))
    size = 16 if len(rows) <= 6 else 14
    for r, row in enumerate(rows):
        for c in range(cols):
            cell = table.cell(r, c)
            raw = _plain(row[c]) if c < len(row) else ""
            cell.text = ""
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = cell.margin_right = Emu(91440)
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.RIGHT if r and _number(raw) else PP_ALIGN.LEFT
            run = p.add_run()
            run.text = raw
            run.font.size = Pt(size)
            run.font.bold = r == 0
            run.font.color.rgb = RGBColor(*(WHITE if r == 0 else NAVY))
            _ea_font(run)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(*(NAVY if r == 0 else LIGHT if r % 2 == 0 else WHITE))


# ---------------- Word ----------------
def _doc_font(style_or_run, name=FONT_DOC):
    from docx.oxml.ns import qn
    rpr = style_or_run.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(fonts)
    for k in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(k), name)


def _add_runs(p, s, size=None, color=None, bold=None):
    from docx.shared import Pt, RGBColor
    for part, b in _runs(s):
        r = p.add_run(part)
        r.bold = True if (b or bold) else None
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = RGBColor(*color)
        _doc_font(r)
    return p


def make_docx(doc, path):
    import datetime
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Mm, Pt, RGBColor
    d = Document()
    for sec in d.sections:
        sec.page_height, sec.page_width = Mm(297), Mm(210)  # A4
        sec.top_margin = sec.bottom_margin = Mm(22)
        sec.left_margin = sec.right_margin = Mm(24)
    normal = d.styles["Normal"]
    normal.font.size = Pt(10.5)
    _doc_font(normal)
    pf = normal.paragraph_format
    pf.line_spacing = 1.4
    pf.space_after = Pt(5)
    pf.widow_control = True  # 段落の1行だけが次のページに残らないように
    for name, size, color, before in (("Title", 24, NAVY, 0), ("Heading 1", 15, NAVY, 18), ("Heading 2", 12.5, ACCENT, 10)):
        st = d.styles[name]
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = RGBColor(*color)
        _doc_font(st)
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(6)
        st.paragraph_format.keep_with_next = True  # 見出しだけがページの最後に残らないように
    for name in ("List Bullet", "List Bullet 2", "List Number", "List Number 2"):
        _doc_font(d.styles[name])
        d.styles[name].paragraph_format.space_after = Pt(3)

    t = d.add_paragraph(style="Title")
    _add_runs(t, doc["title"])
    _border(t, ACCENT)
    if doc["subtitle"]:
        _add_runs(d.add_paragraph(), doc["subtitle"], 11.5, GRAY)
    today = datetime.date.today()
    date = d.add_paragraph()
    date.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _add_runs(date, f"{today.year}年{today.month}月{today.day}日", 9.5, GRAY)

    for sec in doc["sections"]:
        if sec["title"]:
            _add_runs(d.add_paragraph(style="Heading 1"), sec["title"])
        numbered = False
        tops = [b[1] for k, b in sec["blocks"] if k in ("bullet", "number")]
        if 2 <= len(tops) <= 4 and len(sec["blocks"]) == len(tops) and all(
                re.match(r"^\D{0,20}?[¥$]?\d", t) and _units(t) <= 30 for t in tops):
            _key_figures(d, tops)  # 数字が主役の項目は、数字を大きく見せる
            continue
        blocks = sec["blocks"]
        for i, (k, b) in enumerate(blocks):
            if k == "h3":
                _add_runs(d.add_paragraph(style="Heading 2"), b)
            elif k in ("bullet", "number"):
                level, s = b
                style = ("List Bullet" if k == "bullet" else "List Number") + (" 2" if level else "")
                p = d.add_paragraph(style=style)
                if k == "number" and not numbered and level == 0:
                    _restart_numbering(d, p)
                    numbered = True
                _add_runs(p, s)
                # 箇条書きは、ページの切れ目で1行だけ離れないように、続きと同じページにまとめる(長い一覧は除く)
                nxt = blocks[i + 1][0] if i + 1 < len(blocks) else None
                if nxt in ("bullet", "number") and len(tops) <= 8:
                    p.paragraph_format.keep_with_next = True
            elif k == "table":
                _docx_table(d, b)
            elif k == "picture":
                p = d.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.keep_with_next = True
                p.add_run().add_picture(b["path"], width=Cm(14))
                cap = d.add_paragraph()
                cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _add_runs(cap, b["credit"], 8.5, GRAY)
            else:
                _add_runs(d.add_paragraph(), b)
        for note in sec["notes"]:
            _callout(d, note)
    if doc["sources"]:
        _add_runs(d.add_paragraph(style="Heading 1"), "出典")
        for i, src in enumerate(doc["sources"], 1):
            _add_runs(d.add_paragraph(), f"[{i}] {src}", 9, GRAY)
    # 下: ページ番号
    footer = d.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run()
    run.font.size = Pt(9)
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        el = OxmlElement("w:fldChar" if kind else "w:instrText")
        if kind:
            el.set(qn("w:fldCharType"), kind)
        else:
            el.text = text
        run._r.append(el)
    d.save(path)
    return len(doc["sections"])


def _key_figures(d, texts):
    """主な数字: 横に並べた枠に、数字を大きく、説明を小さく。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    table = d.add_table(rows=1, cols=len(texts))
    for i, t in enumerate(texts):
        plain = _plain(t)
        m = re.search(r"[¥$]?\d[\d,.]*\s*(?:%|％|倍|円|万円|億円|件|人|社|時間|分|日|か月|ヶ月|年|個|台|点|位)?", plain)
        cell = table.cell(0, i)
        _shade(cell, LIGHT)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(8)
        _add_runs(p, m.group(0).strip(), 20, ACCENT, bold=True)
        q = cell.add_paragraph()
        q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        q.paragraph_format.space_after = Pt(8)
        label = (plain[:m.start()] + plain[m.end():]).strip(" 、:：") if m.start() == 0 or m.end() == len(plain) else plain
        _add_runs(q, label or plain, 9.5, NAVY)
    d.add_paragraph().paragraph_format.space_after = Pt(2)


def _restart_numbering(d, p):
    """番号付きの箇条書きを、章ごとに 1 から数え直す。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    numbering = d.part.numbering_part.numbering_definitions._numbering
    style_num = d.styles["List Number"]._element.pPr.numPr.numId.val
    abstract = numbering.num_having_numId(style_num).abstractNumId.val
    num = numbering.add_num(abstract)
    over = OxmlElement("w:lvlOverride")
    over.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:startOverride")
    start.set(qn("w:val"), "1")
    over.append(start)
    num.append(over)
    ppr = p._p.get_or_add_pPr()
    numpr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    numid = OxmlElement("w:numId")
    numid.set(qn("w:val"), str(num.numId))
    numpr.append(ilvl)
    numpr.append(numid)
    ppr.append(numpr)
    d._zealous_num = num.numId


def _border(p, color, side="bottom"):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    ppr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    el = OxmlElement(f"w:{side}")
    for k, v in (("w:val", "single"), ("w:sz", "12"), ("w:space", "4"), ("w:color", "%02X%02X%02X" % color)):
        el.set(qn(k), v)
    bdr.append(el)
    ppr.append(bdr)


def _shade(cell, color):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), "%02X%02X%02X" % color)
    cell._tc.get_or_add_tcPr().append(shd)


def _callout(d, text):
    """補足: 薄い色の囲み(左に青い線)。"""
    from docx.shared import Pt
    table = d.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    _shade(cell, LIGHT)
    p = cell.paragraphs[0]
    _add_runs(p, text, 10, NAVY)
    _border(p, ACCENT, "left")
    d.add_paragraph().paragraph_format.space_after = Pt(2)


def _docx_table(d, rows):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt
    cols = max(len(r) for r in rows)
    table = d.add_table(rows=len(rows), cols=cols)
    table.style = "Table Grid"
    for r, row in enumerate(rows):
        tr_pr = table.rows[r]._tr.get_or_add_trPr()
        no_split = OxmlElement("w:cantSplit")  # 1つの行が2ページにまたがらないように
        tr_pr.append(no_split)
        if r == 0:
            head = OxmlElement("w:tblHeader")  # 次のページにも見出しの行を出す
            tr_pr.append(head)
        for c in range(cols):
            cell = table.cell(r, c)
            raw = _plain(row[c]) if c < len(row) else ""
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            if r and _number(raw):
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _add_runs(p, raw, 10, WHITE if r == 0 else None, bold=r == 0)
            if r == 0:
                _shade(cell, NAVY)
            elif r % 2 == 0:
                _shade(cell, LIGHT)
        for cell in table.rows[r].cells:  # 枠線は薄い色に
            borders = OxmlElement("w:tcBorders")
            for side in ("top", "left", "bottom", "right"):
                el = OxmlElement(f"w:{side}")
                el.set(qn("w:val"), "single")
                el.set(qn("w:sz"), "4")
                el.set(qn("w:color"), "%02X%02X%02X" % LINE)
                borders.append(el)
            cell._tc.get_or_add_tcPr().append(borders)
    d.add_paragraph().paragraph_format.space_after = Pt(2)


# ---------------- Excel ----------------
def _width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def make_xlsx(doc, path):
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    hx = lambda c: "%02X%02X%02X" % c  # noqa: E731
    thin = Side(style="thin", color=hx(LINE))
    sheets = [sec for sec in doc["sections"] if any(k == "table" for k, _ in sec["blocks"])] or doc["sections"]
    names = set()
    for n, sec in enumerate(sheets, 1):
        name = re.sub(r"[\\/*?:\[\]]", "", sec["title"] or doc["title"])[:28] or f"Sheet{n}"
        while name in names:
            name = f"{name[:26]}{n}"
        names.add(name)
        ws = wb.create_sheet(name)
        ws.sheet_view.showGridLines = False
        ws["A1"] = sec["title"] or doc["title"]
        ws["A1"].font = Font(name=FONT, size=15, bold=True, color=hx(NAVY))
        ws.row_dimensions[1].height = 26
        row = 3
        widths = {}
        for k, b in sec["blocks"]:
            if k != "table":
                if k == "picture":
                    continue
                text = b[1] if isinstance(b, tuple) else b
                ws.cell(row=row, column=1, value=_plain(text)).font = Font(name=FONT, size=10, color=hx(GRAY))
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
                        cell.number_format = "#,##0"
                    elif num:
                        cell.value, cell.number_format = num
                    else:
                        cell.value = raw
                    cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
                    cell.alignment = Alignment(vertical="center", wrap_text=r == 0 or _width(raw) > 40,
                                               horizontal="right" if (num or raw.startswith("=")) else
                                               "center" if r == 0 else "left")
                    if r == 0:
                        cell.font = Font(name=FONT, size=10, bold=True, color="FFFFFF")
                        cell.fill = PatternFill("solid", fgColor=hx(NAVY))
                    else:
                        cell.font = Font(name=FONT, size=10, color=hx(NAVY), bold=bool(re.match(r"合計|計$|total", raw, re.I)))
                        if r % 2 == 0:
                            cell.fill = PatternFill("solid", fgColor=hx(LIGHT))
                    widths[c] = max(widths.get(c, 0), min(_width(raw), 40))
                ws.row_dimensions[row].height = 24 if r == 0 else 20
                row += 1
            if ws.freeze_panes is None:
                ws.freeze_panes = ws.cell(row=head + 1, column=1)
            ws.auto_filter.ref = f"A{head}:{get_column_letter(cols)}{row - 1}"
            ws.print_title_rows = f"{head}:{head}"
            numeric = [c for c in range(2, cols + 1)
                       if all(isinstance(ws.cell(row=r, column=c).value, (int, float)) for r in range(head + 1, row))]
            if numeric:  # 単位の違う列(金額と%など)は同じグラフにしない
                fmt = ws.cell(row=head + 1, column=numeric[0]).number_format
                numeric = [c for c in numeric if ws.cell(row=head + 1, column=c).number_format == fmt and "%" not in fmt]
            if numeric and 2 <= row - head - 1 <= 30:
                chart = BarChart()
                chart.title = sec["title"] or doc["title"]
                chart.style = 10
                chart.height, chart.width = 8, 16
                for c in numeric[:4]:
                    chart.add_data(Reference(ws, min_col=c, min_row=head, max_row=row - 1), titles_from_data=True)
                chart.set_categories(Reference(ws, min_col=1, min_row=head + 1, max_row=row - 1))
                chart.legend.position = "b"
                if len(numeric) == 1:
                    chart.legend = None
                ws.add_chart(chart, f"{get_column_letter(cols + 2)}{head}")
            row += 2
        for c, w in widths.items():
            ws.column_dimensions[get_column_letter(c + 1)].width = min(48, max(10, w + 4))
        ws.page_setup.orientation = "landscape" if len(widths) > 5 else "portrait"
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
    if doc["sources"]:
        ws = wb.create_sheet("出典")
        ws.sheet_view.showGridLines = False
        ws["A1"] = "出典"
        ws["A1"].font = Font(name=FONT, size=15, bold=True, color=hx(NAVY))
        for i, src in enumerate(doc["sources"], 1):
            ws.cell(row=i + 2, column=1, value=f"[{i}] {src}").font = Font(name=FONT, size=10, color=hx(GRAY))
        ws.column_dimensions["A"].width = 100
    wb.save(path)
    return len([s for s in wb.sheetnames if s != "出典"])


MAKERS = {"pptx": make_pptx, "docx": make_docx, "xlsx": make_xlsx}
