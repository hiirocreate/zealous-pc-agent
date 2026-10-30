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

FONT = "Yu Gothic UI"   # 見出しの書体(use_fonts で変える。Windows 8.1 以降に標準で入っている書体が既定)
FONT_DOC = "Yu Gothic"  # 本文の書体
MONO = "Consolas"
NAVY = (0x1F, 0x2A, 0x44)
ACCENT = (0x2F, 0x6F, 0xEB)
ACCENT_SOFT = (0xDC, 0xE7, 0xFD)
GRAY = (0x5B, 0x64, 0x72)
LIGHT = (0xF3, 0xF6, 0xFB)
WHITE = (0xFF, 0xFF, 0xFF)
LINE = (0xC9, 0xD3, 0xE6)
ON_DARK = (0xC9, 0xD3, 0xE6)     # 濃い背景の上の、控えめな文字
ACCENT_ON_DARK = (0x9C, 0xBC, 0xFF)
ACCENT_2 = (0x7F, 0xA7, 0xF5)    # グラフの3つ目の色

# 色の組み合わせ(頼まれた色の名前 → 濃い色, 目立たせる色)。文字と背景の明るさの差が十分にとれる組だけ
THEMES = {
    "blue": ((0x1F, 0x2A, 0x44), (0x2F, 0x6F, 0xEB)), "navy": ((0x14, 0x1E, 0x38), (0x3B, 0x5B, 0xA9)),
    "green": ((0x14, 0x35, 0x2B), (0x0F, 0x8F, 0x6A)), "teal": ((0x0F, 0x34, 0x38), (0x0E, 0x93, 0x93)),
    "red": ((0x3B, 0x15, 0x18), (0xD0, 0x31, 0x3A)), "orange": ((0x3A, 0x24, 0x12), (0xE0, 0x7A, 0x10)),
    "purple": ((0x2A, 0x1F, 0x4A), (0x6D, 0x4D, 0xE6)), "pink": ((0x3D, 0x18, 0x30), (0xD9, 0x46, 0x84)),
    "brown": ((0x3B, 0x2A, 0x1E), (0x9C, 0x62, 0x34)), "mono": ((0x1F, 0x1F, 0x22), (0x4B, 0x55, 0x63)),
}
COLOR_WORDS = [("紺", "navy"), ("ネイビー", "navy"), ("青", "blue"), ("ブルー", "blue"), ("水色", "teal"),
               ("ティール", "teal"), ("緑", "green"), ("グリーン", "green"), ("赤", "red"), ("レッド", "red"),
               ("オレンジ", "orange"), ("橙", "orange"), ("紫", "purple"), ("パープル", "purple"), ("ピンク", "pink"),
               ("桃", "pink"), ("茶", "brown"), ("ブラウン", "brown"), ("黒", "mono"), ("モノクロ", "mono"),
               ("白黒", "mono"), ("グレー", "mono"), ("灰", "mono")]


def theme_of(text):
    """頼まれた文から色の組み合わせの名前(無ければ None)。"""
    return next((name for word, name in COLOR_WORDS if word in str(text)), None)


def _mix(c, other, t):
    return tuple(round(a + (b - a) * t) for a, b in zip(c, other))


def use_theme(name):
    """色の組み合わせを決める(薄い色は、目立たせる色を白に混ぜて作る)。"""
    global NAVY, ACCENT, ACCENT_SOFT, LIGHT, LINE, ON_DARK, ACCENT_ON_DARK, ACCENT_2
    dark, accent = THEMES.get(name or "blue", THEMES["blue"])
    NAVY, ACCENT = dark, accent
    ACCENT_SOFT, LIGHT, LINE = _mix(accent, WHITE, 0.85), _mix(accent, WHITE, 0.95), _mix(accent, WHITE, 0.72)
    ON_DARK, ACCENT_ON_DARK, ACCENT_2 = _mix(dark, WHITE, 0.78), _mix(accent, WHITE, 0.5), _mix(accent, WHITE, 0.45)
_SOURCES = re.compile(r"出典|参考(?:文献|資料|URL|サイト)?$|sources?|references?", re.I)


def use_fonts(head, body):
    """見出しと本文の書体を決める(このPCに入っているものだけを渡すこと。fonts.pick で選ぶ)。"""
    global FONT, FONT_DOC
    FONT, FONT_DOC = head, body


# ---------------- 中身の読み取りと整え ----------------
_GENERIC = re.compile(r"^(?:新しい)?(?:資料|書類|文書|スライド|プレゼン(?:テーション)?|発表資料|報告書|レポート|表|概要|"
                      r"タイトル|無題|untitled|document|presentation|slides?)$", re.I)


_SLIDE_HEAD = re.compile(r"^(?:#{1,3}\s*)?(?:\*\*)?(?:スライド|slide|ページ)\s*\d+\s*(?:枚目)?\s*[:：.．]\s*(.+?)(?:\*\*)?$", re.I)
_PLACEHOLDER = re.compile(r"^(?:スライド|章|節|段落|セクション)?の?(?:題名|タイトル|見出し)\d*(?:[（(]続き[）)])?$")
_BULLET = re.compile(r"^(?:[-*]\s+|[・•■□●○◆◇▪▫▶►✓✔]\s*)")


def generic_title(title):
    """題名が「資料」「プレゼンテーション」のように中身を表していないか。"""
    return not title or bool(_GENERIC.match(re.sub(r"[\s　「」『』]", "", title)))


def parse(text):
    """書式つきの文 → {"title", "subtitle", "sections": [{"title", "blocks", "notes"}], "sources": [...]}"""
    text = re.sub(r"^```\w*\n|\n```\s*$", "", text.strip())
    # 出典の URL から、追跡用の飾り(?srsltid=… など)を取る
    text = re.sub(r"[?&](?:srsltid|utm_\w+|gclid|fbclid|yclid)=[^\s&#)]*", "", text)
    text = re.sub(r"(https?://\S*?)&", lambda m: m.group(1) + ("?" if "?" not in m.group(1) else "&"), text)
    doc = {"title": "", "subtitle": "", "sections": [], "sources": [], "key_points": []}
    cur, table = None, None

    def section(title):
        nonlocal cur
        cur = {"title": title, "blocks": [], "notes": [], "lead": ""}
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
        # 「スライド2: サービスの特徴」のように、AIが枚ごとの題名を本文に書いたときも、1枚(1節)として分ける
        m = _SLIDE_HEAD.match(s)
        if m:
            section(_clean(m.group(1)))
            continue
        if s.startswith("## "):
            title = _clean(s[3:])
            section("" if _PLACEHOLDER.match(title) else title)  # 「スライドの題名」のような書き方の見本は題名にしない
            continue
        m = re.match(r"^!\s*要点\s*[:：]\s*(.+)$", s)
        if m:  # 文書全体の要点(Word では最初に囲みで見せる)
            doc["key_points"].append(_clean(m.group(1)))
            continue
        if cur is None:
            if doc["title"] and not doc["subtitle"] and not s.startswith(("-", "*", "|", "#", "!", ">")):
                doc["subtitle"] = _clean(_plain(s))
                continue
            section("")
        m = re.match(r"^!\s*リード\s*[:：]\s*(.+)$", s)
        if m:  # そのページで一番伝えたいこと(スライドでは題名の下に出す)
            cur["lead"] = _clean(_plain(m.group(1)))
            continue
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
        elif _BULLET.match(s):
            level = min(2, (len(line) - len(line.lstrip(" "))) // 2)
            cur["blocks"].append(("bullet", (level, _clean(_BULLET.sub("", s)))))
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
def _ea_font(run, name=None):
    """日本語の文字にも書体を指定する(指定しないと、日本語だけ別の書体になる)。太字は見出しの書体。"""
    from pptx.oxml.ns import qn
    name = name or (FONT if run.font.bold else FONT_DOC)
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea"):
        el = rpr.find(qn(tag))
        if el is None:
            el = rpr.makeelement(qn(tag), {})
            rpr.append(el)
        el.set("typeface", name)


def _text(frame, s, size, color=None, bold=False, first=True, level=0, align=None, space=None):
    from pptx.dml.color import RGBColor
    from pptx.util import Pt
    color = color or NAVY
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


def _picture(slide, pic, x, y, w, h, credit_color=None):
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
    _text(tf, pic["credit"], 8, credit_color or GRAY)


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
    if sum(1 for sec in doc["sections"] if sec["title"]) >= 4:  # 章が多いときは目次を付ける
        deck.agenda()
    for sec in doc["sections"]:
        deck.section(sec)
    if doc["sources"]:
        deck.sources()
    deck.finish()
    prs.save(path)
    return len(prs.slides._sldIdLst)


def _split_head(t):
    """「**見出し**：説明」→ (見出し, 説明)。見出しが無ければ ("", 文)。"""
    m = re.match(r"^\*\*(.+?)\*\*\s*[:：]?\s*(.*)$", t)
    if m:
        return _clean(m.group(1)), _clean(m.group(2))
    m = re.match(r"^([^:：。、]{1,14})[:：]\s*(.+)$", t)
    return (_clean(m.group(1)), _clean(m.group(2))) if m else ("", t)


def _shape(slide, kind, x, y, w, h, color, line=None):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    s = slide.shapes.add_shape(getattr(MSO_SHAPE, kind), int(x), int(y), int(w), int(h))
    s.fill.solid()
    s.fill.fore_color.rgb = RGBColor(*color)
    if line:
        s.line.color.rgb = RGBColor(*line)
        s.line.width = 12700
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    return s


def _size_for(texts, width_in, height_in, sizes, spacing=1.3):
    """どの文も枠に収まる、いちばん大きい文字の大きさ。"""
    for size in sizes:
        if all(_lines(t, width_in, size) * size * spacing / 72 <= height_in for t in texts if t):
            return size
    return sizes[-1]


class _Deck:
    """16:9 のスライド。どのページも「小さな見出し(何の話か) + 大きな一文(伝えたいこと)」+ 中身の図、の形にそろえる。"""

    def __init__(self, prs, doc):
        from pptx.util import Inches
        self.prs, self.doc = prs, doc
        self.W, self.H = prs.slide_width, prs.slide_height
        self.titled = prs.slide_layouts[5]  # 「タイトルのみ」: 題名を本物のタイトル欄に入れる(アウトラインや一覧に出て、編集しやすい)
        self.margin = Inches(0.7)
        self.pages = []  # ページ番号を最後に入れるため
        self.lead = ""
        self.cover_pic = None

    def finish(self):
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Inches
        total = len(self.pages)
        for i, (s, dark) in enumerate(self.pages, 1):
            col = ON_DARK if dark else GRAY
            _text(_box(s, self.margin, self.H - Inches(0.45), Inches(8), Inches(0.3)), self.doc["title"], 10, col)
            _text(_box(s, self.W - self.margin - Inches(1.2), self.H - Inches(0.45), Inches(1.2), Inches(0.3)),
                  f"{i:02d} / {total:02d}", 10, col, align=PP_ALIGN.RIGHT)

    # ---- 表紙・目次 ----
    def cover(self):
        import datetime
        from pptx.util import Emu, Inches
        s = self.prs.slides.add_slide(self.titled)
        _rect(s, 0, 0, self.W, self.H, NAVY)
        pic = next((b for sec in self.doc["sections"] for k, b in sec["blocks"] if k == "picture"), None)
        self.cover_pic = pic
        text_w = int(self.W * 0.6)
        if pic:  # 写真があれば右に大きく
            pw = int(self.W * 0.4)
            _picture(s, pic, self.W - pw, 0, pw, self.H - Inches(0.3), credit_color=LINE)
        else:  # 写真が無いときは、色の円を重ねた飾り(右上と右下にはみ出させる)
            _shape(s, "OVAL", self.W - Inches(4.6), Inches(-1.6), Inches(6.4), Inches(6.4), _mix(NAVY, ACCENT, 0.35))
            _shape(s, "OVAL", self.W - Inches(2.9), Inches(3.6), Inches(4.4), Inches(4.4), _mix(NAVY, ACCENT, 0.75))
            _shape(s, "OVAL", self.W - Inches(5.3), Inches(4.4), Inches(1.3), Inches(1.3), ACCENT_ON_DARK)
        _rect(s, 0, 0, Inches(0.22), self.H, ACCENT)
        title, tw = self.doc["title"], text_w / 914400
        size = next((z for z in (48, 44, 40, 36) if _lines(title, tw, z) == 1), None) or \
            next((z for z in (44, 40, 36, 32, 28) if _lines(title, tw, z) <= 2), 26)
        _text(_box(s, self.margin + Inches(0.1), Inches(1.5), text_w, Inches(0.4)), "PRESENTATION", 13,
              ACCENT_ON_DARK, bold=True)
        _text(self._title(s, self.margin + Inches(0.1), Inches(1.95), text_w, Inches(2.1)), title, size, WHITE,
              bold=True)
        _rect(s, self.margin + Inches(0.1), Inches(4.3), Inches(1.2), Emu(60000), ACCENT_ON_DARK)
        if self.doc["subtitle"]:
            _text(_box(s, self.margin + Inches(0.1), Inches(4.55), text_w, Inches(1.2)), self.doc["subtitle"], 20,
                  ON_DARK)
        today = datetime.date.today()
        _text(_box(s, self.margin + Inches(0.1), self.H - Inches(1.0), Inches(5), Inches(0.4)),
              f"{today.year}年{today.month}月{today.day}日", 14, ON_DARK)

    def agenda(self):
        """目次: 左に濃い帯、右に番号つきの章の一覧。"""
        from pptx.enum.text import MSO_ANCHOR
        from pptx.util import Inches
        self.lead = ""
        titles = [sec["title"] for sec in self.doc["sections"] if sec["title"]][:8]
        s = self.prs.slides.add_slide(self.titled)
        band = Inches(4.2)
        _rect(s, 0, 0, band, self.H, NAVY)
        _text(_box(s, self.margin, Inches(2.6), band - self.margin, Inches(0.4)), "AGENDA", 14, ACCENT_ON_DARK, bold=True)
        _text(self._title(s, self.margin, Inches(3.0), band - self.margin * 1.5, Inches(0.9)), "目次", 40, WHITE,
              bold=True)
        x, w = band + Inches(0.8), self.W - band - Inches(1.6)
        top, bottom = Inches(0.9), self.H - Inches(0.9)
        row = min(Inches(0.95), (bottom - top) / len(titles))
        y = top + ((bottom - top) - row * len(titles)) / 2
        for i, t in enumerate(titles):
            cy = y + row * i
            _text(_box(s, x, cy, Inches(0.9), row, MSO_ANCHOR.MIDDLE), f"{i + 1:02d}", 26, ACCENT, bold=True)
            _text(_box(s, x + Inches(1.0), cy, w - Inches(1.0), row, MSO_ANCHOR.MIDDLE), t,
                  22 if _units(t) <= 26 else 18, NAVY, bold=True)
            if i < len(titles) - 1:
                _rect(s, x, cy + row - 6350, w, 12700, LINE)
        self.pages.append((s, False))

    # ---- ページの枠 ----
    def page(self, title, dark=False):
        """小さな見出し(このページの話題)と、大きな一文(伝えたいこと。無ければ見出しを大きく)。"""
        from pptx.util import Emu, Inches
        s = self.prs.slides.add_slide(self.titled)
        if dark:
            _rect(s, 0, 0, self.W, self.H, NAVY)
        _rect(s, 0, 0, Inches(0.14), self.H, ACCENT)
        fg = WHITE if dark else NAVY
        w = self.W - self.margin * 2
        head = self.lead or title
        if self.lead:  # 見出しは小さく色で、伝えたいことを大きく
            _text(_box(s, self.margin, Inches(0.45), w, Inches(0.35)), title, 14, ACCENT_ON_DARK if dark else ACCENT,
                  bold=True)
        size = next((z for z in (30, 28, 26, 24) if _lines(head, w / 914400, z) == 1), None) or \
            next((z for z in (26, 24, 22) if _lines(head, w / 914400, z) <= 2), 20)
        _text(self._title(s, self.margin, Inches(0.8), w, Inches(0.95)), head, size, fg, bold=True)
        _rect(s, self.margin, Inches(1.88), Inches(0.8), Emu(45000), ACCENT_ON_DARK if dark else ACCENT)
        self.pages.append((s, dark))
        return s

    @staticmethod
    def _title(s, x, y, w, h):
        """スライドのタイトル欄を、決めた場所・左寄せ・下ぞろえにして、その文字の枠を返す。"""
        from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
        from pptx.util import Emu
        ph = s.shapes.title
        ph.left, ph.top, ph.width, ph.height = int(x), int(y), int(w), int(h)
        sp = ph._element  # 背景の図形より手前に
        tree = sp.getparent()
        tree.remove(sp)
        tree.append(sp)
        tf = ph.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Emu(0)
        tf.vertical_anchor = MSO_ANCHOR.BOTTOM
        tf.paragraphs[0].alignment = PP_ALIGN.LEFT
        return tf

    @property
    def body(self):
        """中身の場所(見出しの下から、ページ番号の上まで)。"""
        from pptx.util import Inches
        top = Inches(2.25)
        return self.margin, top, self.W - self.margin * 2, self.H - top - Inches(0.8)

    # ---- 章ごとに、中身に合う見せ方を選ぶ ----
    def section(self, sec):
        title = sec["title"] or self.doc["title"]
        self.lead = sec.get("lead", "")
        blocks = [(k, b) for k, b in sec["blocks"] if not (k == "picture" and b is self.cover_pic)]
        tables = [b for k, b in blocks if k == "table"]
        pics = [b for k, b in blocks if k == "picture"]
        lines = [(k, b) for k, b in blocks if k in ("bullet", "number", "text", "h3")]
        top_items = [b for k, b in lines if k in ("bullet", "number") and b[0] == 0]
        subs = [b for k, b in lines if k in ("bullet", "number") and b[0] > 0]
        others = [(k, b) for k, b in lines if k == "text"]
        h3s = [b for k, b in lines if k == "h3"]
        closing = re.search(r"まとめ|おわりに|結論|summary|conclusion", title, re.I) and not tables
        for rows in tables:
            self.table(title, rows, lines)
            lines = []
        if not lines:
            if pics and not tables:
                self.photo(title, pics[0], [])
            self._notes(sec)
            return
        texts = [t for _, t in top_items]
        heads = [_split_head(t) for t in texts]
        has_heads = texts and all(h for h, _ in heads)
        short = all(_units(b) <= 70 for _, b in heads)
        nums = [t for t in texts if re.match(r"^(?:\*\*)?[¥$]?\d", t)]
        if closing:
            self.closing(title, texts or [_plain(b if not isinstance(b, tuple) else b[1]) for _, b in lines])
        elif 2 <= len(h3s) <= 3 and not others:
            self.compare(title, lines)
        elif pics:
            self.photo(title, pics[0], lines)
        elif top_items and not subs and 2 <= len(texts) <= 6 and short and all(
                k == "number" for k, _ in lines if k in ("bullet", "number")):
            self.steps(title, heads, others)
        elif top_items and not subs and 2 <= len(texts) <= 4 and len(nums) == len(texts) and short:
            self.stats(title, heads, others)
        elif top_items and not subs and 2 <= len(texts) <= 6 and short and (has_heads or len(texts) <= 4):
            self.cards(title, heads, others)
        elif has_heads and not subs and len(texts) <= 6:
            self.rows(title, heads, others)
        else:
            self.bullets(title, lines)
        self._notes(sec)

    def _notes(self, sec):
        if sec["notes"] and self.pages:
            self.pages[-1][0].notes_slide.notes_text_frame.text = "\n".join(sec["notes"])

    def _footer_text(self, s, others, y, h):
        """図の下に、補足の文を薄い囲みで添える。"""
        from pptx.util import Inches
        if not others or h < Inches(0.6):
            return
        x, _, w, _ = self.body
        text = "  ".join(_plain(b if not isinstance(b, tuple) else b[1]) for _, b in others)
        size = 16 if _lines(text, w / 914400 - 0.6, 16) <= 2 else 14
        lines = _lines(text, w / 914400 - 0.6, size)
        bh = min(h, Inches(0.3) + int(lines * size * 1.3 / 72 * 914400))
        _rect(s, x, y, w, bh, LIGHT, rounded=True)
        _rect(s, x, y, Inches(0.07), bh, ACCENT)
        _text(_box(s, x + Inches(0.3), y + Inches(0.15), w - Inches(0.6), bh - Inches(0.2)), text, size, NAVY)

    def _extra(self, others):
        from pptx.util import Inches
        return Inches(1.05) if others else 0

    # ---- 見せ方 ----
    def cards(self, title, heads, others):
        """要点のカード(3つまでは横1列、4つ以上は2段)。見出しを太く大きく、説明をその下に。"""
        from pptx.enum.text import MSO_ANCHOR
        from pptx.util import Emu, Inches
        s = self.page(title)
        x, y, w, h = self.body
        n = len(heads)
        extra = self._extra(others)
        per_row = n if n <= 3 else (n + 1) // 2
        rows = -(-n // per_row)
        gap = Inches(0.3)
        cw = (w - gap * (per_row - 1)) / per_row
        ch = (h - extra - gap * (rows - 1)) / rows
        tw = cw / 914400 - 0.7
        hs = _size_for([hd for hd, _ in heads], tw, 0.9, (24, 22, 20, 18, 16))
        top = 1.4 if rows == 1 else 0.7
        bs = _size_for([b for _, b in heads], tw, ch / 914400 - top - 1.0, (20, 18, 17, 16, 15, 14))
        # カードの高さは中身に合わせ(大きすぎる空白を作らない)、まとまりをページの中ほどに置く
        need = top + 0.5 + max((_lines(hd, tw, hs) * hs * 1.3 / 72 + 0.2 if hd else 0) +
                               _lines(b, tw, bs if hd else hs) * (bs if hd else hs) * 1.35 / 72 for hd, b in heads)
        ch = min(ch, max(Inches(need), int((h - extra) * (0.62 if rows == 1 else 0.4))))
        y += int((h - extra - ch * rows - gap * (rows - 1)) * 0.4)
        for i, (hd, body) in enumerate(heads):
            cx, cy = x + (cw + gap) * (i % per_row), y + (ch + gap) * (i // per_row)
            _rect(s, cx, cy, cw, ch, LIGHT, rounded=True)
            _rect(s, cx, cy, Emu(60000), ch, ACCENT)
            if rows == 1:
                badge = _shape(s, "OVAL", cx + Inches(0.35), cy + Inches(0.4), Inches(0.75), Inches(0.75), ACCENT)
                badge.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
                from pptx.enum.text import PP_ALIGN
                _text(badge.text_frame, f"{i + 1:02d}", 16, WHITE, bold=True, align=PP_ALIGN.CENTER)
                ty = cy + Inches(1.4)
            else:
                _text(_box(s, cx + Inches(0.35), cy + Inches(0.25), Inches(1), Inches(0.4)), f"{i + 1:02d}", 16, ACCENT,
                      bold=True)
                ty = cy + Inches(0.7)
            if hd:
                _text(_box(s, cx + Inches(0.35), ty, cw - Inches(0.7), Inches(0.8)), hd, hs, NAVY, bold=True)
                hl = _lines(hd, tw, hs) * hs * 1.3 / 72
                ty += Inches(hl + 0.2)
                _rect(s, cx + Inches(0.35), ty - Inches(0.1), Inches(0.5), Emu(25400), LINE)
            _text(_box(s, cx + Inches(0.35), ty, cw - Inches(0.7), cy + ch - ty - Inches(0.2)), body,
                  bs if hd else hs, GRAY if hd else NAVY)
        self._footer_text(s, others, y + ch * rows + gap * (rows - 1) + Inches(0.3), extra - Inches(0.25))

    def rows(self, title, heads, others):
        """見出しつきの要点を、横長の行に(左に見出し、右に説明)。"""
        from pptx.enum.text import MSO_ANCHOR
        from pptx.util import Inches
        s = self.page(title)
        x, y, w, h = self.body
        extra = self._extra(others)
        n = len(heads)
        gap = Inches(0.18)
        rh = min(Inches(1.35), (h - extra - gap * (n - 1)) / n)
        y += int((h - extra - rh * n - gap * (n - 1)) / 2)
        lw = Inches(3.2)
        bs = _size_for([b for _, b in heads], (w - lw - Inches(0.8)) / 914400, rh / 914400 - 0.2, (20, 18, 17, 16, 15, 14))
        for i, (hd, body) in enumerate(heads):
            cy = y + (rh + gap) * i
            _rect(s, x, cy, w, rh, LIGHT, rounded=True)
            _rect(s, x, cy, lw, rh, ACCENT if i % 2 == 0 else NAVY, rounded=True)
            _rect(s, x + lw - Inches(0.2), cy, Inches(0.2), rh, ACCENT if i % 2 == 0 else NAVY)
            _text(_box(s, x + Inches(0.3), cy, lw - Inches(0.5), rh, MSO_ANCHOR.MIDDLE), hd,
                  20 if _units(hd) <= 12 else 17, WHITE, bold=True)
            _text(_box(s, x + lw + Inches(0.35), cy, w - lw - Inches(0.6), rh, MSO_ANCHOR.MIDDLE), body, bs, NAVY)
        self._footer_text(s, others, y + h - extra + Inches(0.25), extra - Inches(0.25))

    def stats(self, title, heads, others):
        """数字が主役: 数字をとても大きく、何の数字かをその下に。"""
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Emu, Inches
        s = self.page(title)
        x, y, w, h = self.body
        n = len(heads)
        extra = self._extra(others)
        gap = Inches(0.35)
        cw = (w - gap * (n - 1)) / n
        ch = min(Inches(3.9), h - extra)
        y += int((h - extra - ch) / 2)
        for i, (hd, body) in enumerate(heads):
            if not hd:  # 見出しが無い: 文の中の数字を取り出す
                plain = _plain(body)
                m = re.search(r"[¥$]?\d[\d,.]*\s*\S{0,4}", plain)
                hd, body = m.group(0).strip(), (plain[:m.start()] + plain[m.end():]).strip(" 、:：") or plain
            cx = x + (cw + gap) * i
            _rect(s, cx, y, cw, ch, LIGHT, rounded=True)
            _rect(s, cx + cw * 0.3, y, cw * 0.4, Emu(60000), ACCENT)
            m = re.match(r"^([¥$]?[\d,.]+)\s*(.*)$", hd)
            num, unit = (m.group(1), m.group(2)) if m else (hd, "")
            big = 66 if _units(num) <= 4 else 54 if _units(num) <= 6 else 40
            p = _text(_box(s, cx + Inches(0.2), y + Inches(0.5), cw - Inches(0.4), Inches(1.4)), num, big, ACCENT,
                      bold=True, align=PP_ALIGN.CENTER)
            if unit:
                from pptx.dml.color import RGBColor
                from pptx.util import Pt
                r = p.add_run()
                r.text = unit
                r.font.size, r.font.bold = Pt(max(20, big // 2.4)), True
                r.font.color.rgb = RGBColor(*ACCENT)
                _ea_font(r)
            _rect(s, cx + cw / 2 - Inches(0.3), y + Inches(2.05), Inches(0.6), Emu(19050), LINE)
            _text(_box(s, cx + Inches(0.35), y + Inches(2.25), cw - Inches(0.7), ch - Inches(2.4)), body,
                  _size_for([body], cw / 914400 - 0.7, ch / 914400 - 2.5, (20, 18, 16, 15, 14)), NAVY,
                  align=PP_ALIGN.CENTER)
        self._footer_text(s, others, y + ch + Inches(0.3), h - ch - Inches(0.3))

    def steps(self, title, heads, others):
        """手順: 矢印の形を横に並べ、その下に説明。"""
        from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
        from pptx.util import Inches
        s = self.page(title)
        x, y, w, h = self.body
        n = len(heads)
        extra = self._extra(others)
        aw = w / n
        ah = Inches(1.05)
        tw = aw / 914400 - 0.4
        hs = _size_for([hd or str(i + 1) for i, (hd, _) in enumerate(heads)], tw - 0.4, 0.75, (22, 20, 18, 16, 14))
        bs = _size_for([b for _, b in heads], tw, 2.4, (22, 20, 18, 17, 16, 15, 14))
        need = Inches(0.7 + max(_lines(b, tw, bs) for _, b in heads) * bs * 1.35 / 72)
        y += int((h - extra - ah - need) * 0.4)
        for i, (hd, body) in enumerate(heads):
            cx = x + aw * i
            col = _mix(ACCENT, NAVY, i / max(1, n - 1) * 0.7)
            arrow = _shape(s, "PENTAGON" if i == 0 else "CHEVRON", cx, y, aw + Inches(0.12), ah, col)
            if i:
                arrow.adjustments[0] = 0.28
            else:
                arrow.adjustments[0] = 0.28
            tf = arrow.text_frame
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf.margin_left = tf.margin_right = Inches(0.35)
            tf.word_wrap = True
            _text(tf, hd or f"STEP {i + 1}", hs, WHITE, bold=True, align=PP_ALIGN.CENTER)
            _text(_box(s, cx + Inches(0.2), y + ah + Inches(0.3), aw - Inches(0.35), Inches(0.4)), f"STEP {i + 1}", 12,
                  ACCENT, bold=True)
            _text(_box(s, cx + Inches(0.2), y + ah + Inches(0.7), aw - Inches(0.35), Inches(2.4)), body, bs, NAVY)
        self._footer_text(s, others, y + ah + need + Inches(0.3), extra)

    def compare(self, title, lines):
        """比べ合い: 小見出しごとに列を作る(最後の列を目立たせる)。"""
        from pptx.enum.text import MSO_ANCHOR
        from pptx.util import Inches
        groups = []
        for k, b in lines:
            if k == "h3":
                groups.append((b, []))
            elif groups:
                groups[-1][1].append(_plain(b[1] if isinstance(b, tuple) else b))
        s = self.page(title)
        x, y, w, h = self.body
        n = len(groups)
        gap = Inches(0.35)
        cw = (w - gap * (n - 1)) / n
        hh = Inches(0.8)
        most = max(1, max(len(i) for _, i in groups))
        size = _size_for([t for _, items in groups for t in items], cw / 914400 - 1.0,
                         ((h - hh) / 914400 - 0.6) / most - 0.15, (22, 20, 18, 17, 16, 15, 14))
        need = max(sum(_lines(t, cw / 914400 - 1.0, size) * size * 1.3 / 72 + size * 0.7 / 72 for t in items)
                   for _, items in groups)
        col_h = min(h, max(hh + Inches(need + 0.8), int(h * 0.6)))
        y += int((h - col_h) * 0.4)
        h = col_h
        for i, (name, items) in enumerate(groups):
            cx = x + (cw + gap) * i
            main = i == n - 1
            _rect(s, cx, y, cw, h, ACCENT_SOFT if main else LIGHT, rounded=True)
            head = _rect(s, cx, y, cw, hh, ACCENT if main else GRAY, rounded=True)
            _rect(s, cx, y + hh - Inches(0.2), cw, Inches(0.2), ACCENT if main else GRAY)
            head.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            from pptx.enum.text import PP_ALIGN
            _text(head.text_frame, name, 20 if _units(name) <= 16 else 17, WHITE, bold=True, align=PP_ALIGN.CENTER)
            tf = _box(s, cx + Inches(0.4), y + hh + Inches(0.35), cw - Inches(0.8), h - hh - Inches(0.5))
            for j, t in enumerate(items):
                p = _text(tf, "", size, NAVY, first=j == 0, space=size * 0.7)
                self._mark(p, "✓" if main else "–", size, ACCENT if main else GRAY)
                for part, b in _runs(t):
                    from pptx.dml.color import RGBColor
                    from pptx.util import Pt
                    r = p.add_run()
                    r.text = part
                    r.font.size, r.font.bold = Pt(size), b or main
                    r.font.color.rgb = RGBColor(*NAVY)
                    _ea_font(r)

    def closing(self, title, texts):
        """まとめ: 濃い背景に、持ち帰ってほしい要点を番号つきで大きく。"""
        from pptx.enum.text import MSO_ANCHOR
        from pptx.util import Inches
        if not self.lead:
            name = re.sub(r"^(?:まとめ|おわりに|結論)\s*[:：]\s*", "", title)
            title, self.lead = ("まとめ", name) if name != title else (title, "")
        s = self.page(title, dark=True)
        x, y, w, h = self.body
        n = len(texts)
        gap = Inches(0.2)
        rh = min(Inches(1.15), (h - gap * (n - 1)) / max(1, n))
        y += int((h - rh * n - gap * (n - 1)) / 2)
        size = _size_for([_plain(t) for t in texts], w / 914400 - 1.8, rh / 914400 - 0.2, (24, 22, 20, 18, 16))
        for i, t in enumerate(texts):
            cy = y + (rh + gap) * i
            _rect(s, x, cy, w, rh, _mix(NAVY, WHITE, 0.08), rounded=True)
            _text(_box(s, x + Inches(0.35), cy, Inches(1), rh, MSO_ANCHOR.MIDDLE), f"{i + 1:02d}", 28, ACCENT_ON_DARK,
                  bold=True)
            _text(_box(s, x + Inches(1.4), cy, w - Inches(1.7), rh, MSO_ANCHOR.MIDDLE), t, size, WHITE)

    def bullets(self, title, lines, dark=False, cont=False):
        """箇条書き: 文字の量から大きさを決める。入りきらなければ2ページに分ける。"""
        from pptx.dml.color import RGBColor
        from pptx.util import Emu, Pt
        x, y, w, h = self.body
        items = []
        for k, b in lines:
            level, text = b if isinstance(b, tuple) else (0, b)
            items.append((k, level, text))
        sizes = (26, 24, 22, 20, 18, 16, 15, 14) if len(items) <= 4 else (22, 20, 18, 16, 15, 14)
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
        y0 = y + max(0, int((h - Emu(int(used * 914400))) * 0.3))
        tf = _box(s, x, y0, w, h)
        numbers, first = {}, True
        fg, sub = (WHITE, ON_DARK) if dark else (NAVY, GRAY)
        for k, lv, t in items:
            sz = size - 2 * lv
            if k == "h3":
                _text(tf, t, sz + 2, ACCENT if not dark else ACCENT_ON_DARK, bold=True, first=first, space=sz * 0.3)
            elif k == "text":
                _text(tf, t, sz, fg, first=first, space=sz * 0.45)
            else:
                if k == "number":
                    numbers[lv] = numbers.get(lv, 0) + 1
                    for deeper in [d for d in numbers if d > lv]:
                        numbers.pop(deeper)
                mark = f"{numbers[lv]}." if k == "number" else ("■" if lv == 0 else "–")
                p = tf.paragraphs[0] if first else tf.add_paragraph()
                p.level, p.line_spacing, p.space_after = lv, 1.15, Pt(sz * 0.6)
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
        size = _fit(items, (w - pw - Inches(0.4)) / 914400, h / 914400, (22, 20, 18, 16, 15, 14)) or 14
        s = self.page(title)
        tf = _box(s, x, y, w - pw - Inches(0.4), h)
        first = True
        for (k, b), (t, lv) in zip(lines, items):
            prefix = "■  " if k == "bullet" and lv == 0 else "–  " if lv else ""
            _text(tf, prefix + t, size - 2 * lv, NAVY if lv == 0 else GRAY, first=first, level=lv,
                  space=(size - 2 * lv) * 0.6)
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
            _pptx_table(s, [head] + chunk, x, y, tw, min(h, Inches(0.75 if len(chunk) <= 5 else 0.55) * (len(chunk) + 1)))
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
                chart.font.name = FONT_DOC
                chart.value_axis.has_major_gridlines = True
                chart.value_axis.major_gridlines.format.line.color.rgb = RGBColor(*LINE)
                chart.value_axis.format.line.fill.background()
                colors = [ACCENT, NAVY, ACCENT_2]
                for i, series in enumerate(chart.plots[0].series):
                    series.format.fill.solid()
                    series.format.fill.fore_color.rgb = RGBColor(*colors[i % 3])
                chart.plots[0].gap_width = 80

    def sources(self):
        """出典のページ(参考にしたページと、写真の作者・ライセンス)。"""
        self.lead = ""
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
    size = 18 if len(rows) <= 6 else 15
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
def _doc_font(style_or_run, name=None):
    from docx.oxml.ns import qn
    name = name or FONT_DOC
    rpr = style_or_run.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(fonts)
    for k in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(k), name)


def _add_runs(p, s, size=None, color=None, bold=None):
    from docx.shared import Pt, RGBColor
    heading = p.style is not None and p.style.name.startswith(("Heading", "Title"))
    for part, b in _runs(s):
        r = p.add_run(part)
        r.bold = True if (b or bold) else None
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = RGBColor(*color)
        _doc_font(r, FONT if heading else None)
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
        _doc_font(st, FONT)
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
    if doc.get("key_points"):  # この文書の要点: 最初に囲みで見せる(忙しい人はここだけ読めば分かるように)
        _key_points(d, doc["key_points"])

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


def _key_points(d, points):
    """「この文書の要点」の囲み(色の帯の見出し + 番号つきの要点)。"""
    from docx.shared import Pt
    table = d.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    _shade(cell, LIGHT)
    p = cell.paragraphs[0]
    _add_runs(p, "この文書の要点", 11, ACCENT, bold=True)
    p.paragraph_format.space_after = Pt(4)
    for i, t in enumerate(points[:4], 1):
        q = cell.add_paragraph()
        q.paragraph_format.space_after = Pt(2)
        _add_runs(q, f"{i}.  ", 10.5, ACCENT, bold=True)
        _add_runs(q, t, 10.5, NAVY)
    _border(p, ACCENT, "left")
    d.add_paragraph().paragraph_format.space_after = Pt(2)


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
                ws.cell(row=row, column=1, value=_plain(text)).font = Font(name=FONT_DOC, size=10, color=hx(GRAY))
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
                        cell.font = Font(name=FONT_DOC, size=10, color=hx(NAVY),
                                         bold=bool(re.match(r"合計|計$|total", raw, re.I)))
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
            ws.cell(row=i + 2, column=1, value=f"[{i}] {src}").font = Font(name=FONT_DOC, size=10, color=hx(GRAY))
        ws.column_dimensions["A"].width = 100
    wb.save(path)
    return len([s for s in wb.sheetnames if s != "出典"])


MAKERS = {"pptx": make_pptx, "docx": make_docx, "xlsx": make_xlsx}


# ---------------- PDF(頼まれたときだけ。元の Word・PowerPoint・Excel も編集用に残す) ----------------
_PDF_PS = {
    ".docx": "$a = New-Object -ComObject Word.Application; $a.Visible = $false; $a.DisplayAlerts = 0;"
             "$d = $a.Documents.Open($src, $false, $true); $d.ExportAsFixedFormat($dst, 17); $d.Close($false); $a.Quit()",
    ".pptx": "$a = New-Object -ComObject PowerPoint.Application;"
             "$d = $a.Presentations.Open($src, $true, $false, $false); $d.SaveAs($dst, 32); $d.Close(); $a.Quit()",
    ".xlsx": "$a = New-Object -ComObject Excel.Application; $a.Visible = $false; $a.DisplayAlerts = $false;"
             "$d = $a.Workbooks.Open($src); $d.ExportAsFixedFormat(0, $dst); $d.Close($false); $a.Quit()",
}


def _soffice():
    import shutil
    for p in (shutil.which("soffice"), os.path.join(os.environ.get("ProgramFiles", ""), "LibreOffice", "program", "soffice.exe"),
              os.path.join(os.environ.get("ProgramFiles(x86)", ""), "LibreOffice", "program", "soffice.exe")):
        if p and os.path.exists(p):
            return p
    return None


def to_pdf(path):
    """Word・PowerPoint・Excel のファイルを PDF にする。PCの Microsoft Office、無ければ LibreOffice を使う。
    できたら PDF のパス、どちらも無ければ None。"""
    import subprocess
    ext = os.path.splitext(path)[1].lower()
    dst = os.path.splitext(path)[0] + ".pdf"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if os.name == "nt" and ext in _PDF_PS:
        q = lambda s: "'" + s.replace("'", "''") + "'"  # noqa: E731
        script = f"$ErrorActionPreference='Stop'; $src={q(path)}; $dst={q(dst)}; " + _PDF_PS[ext]
        try:
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                           timeout=180, creationflags=flags)
        except Exception:
            pass
        if os.path.exists(dst):
            return dst
    office = _soffice()
    if office:
        try:
            subprocess.run([office, "--headless", "--convert-to", "pdf", "--outdir", os.path.dirname(path), path],
                           capture_output=True, timeout=180, creationflags=flags)
        except Exception:
            pass
        if os.path.exists(dst):
            return dst
    return None
