"""資料に使う書体(フォント)。PCに実際に入っているものだけを使う(無い書体の名前をファイルに書かない)。

書体の種類ごとに、Windows や Office に入っている実在の書体を、使いたい順に並べてある。
見出しと本文で書体を分けるものもある(例: 明朝体は、本文を明朝・見出しをゴシックにすると読みやすい)。"""
import os
import subprocess

# 種類 → (表示名, 見出しの候補, 本文の候補)。候補は英語名と日本語名の両方(Windows の言語で名前が変わるため)
STYLES = {
    "gothic": ("ゴシック体", ["Yu Gothic UI", "Yu Gothic UI Semibold", "游ゴシック", "Yu Gothic", "Meiryo UI", "メイリオ", "Meiryo"],
               ["Yu Gothic", "游ゴシック", "Meiryo", "メイリオ"]),
    "mincho": ("明朝体", ["Yu Gothic", "游ゴシック", "Meiryo", "メイリオ"],
               ["Yu Mincho", "游明朝", "BIZ UDPMincho", "BIZ UDP明朝 Medium", "MS PMincho", "ＭＳ Ｐ明朝"]),
    "kyokasho": ("教科書体", ["UD Digi Kyokasho NP-B", "UD デジタル 教科書体 NP-B", "UD Digi Kyokasho NP-R",
                            "UD デジタル 教科書体 NP-R", "UD Digi Kyokasho N-R", "UD デジタル 教科書体 N-R"],
                 ["UD Digi Kyokasho NP-R", "UD デジタル 教科書体 NP-R", "UD Digi Kyokasho N-R", "UD デジタル 教科書体 N-R"]),
    "pop": ("ポップ体", ["HGP創英角ﾎﾟｯﾌﾟ体", "HGP創英角ポップ体", "HGS創英角ﾎﾟｯﾌﾟ体", "HG創英角ﾎﾟｯﾌﾟ体"],
            ["HG丸ｺﾞｼｯｸM-PRO", "HG丸ゴシックM-PRO", "BIZ UDPGothic", "BIZ UDPゴシック", "Yu Gothic", "游ゴシック"]),
    "maru": ("丸ゴシック体", ["HG丸ｺﾞｼｯｸM-PRO", "HG丸ゴシックM-PRO"], ["HG丸ｺﾞｼｯｸM-PRO", "HG丸ゴシックM-PRO"]),
    "ud": ("UDゴシック（読みやすさ重視）", ["BIZ UDPGothic", "BIZ UDPゴシック"], ["BIZ UDPGothic", "BIZ UDPゴシック"]),
}
FALLBACK = ("Yu Gothic UI", "Yu Gothic")  # Windows 8.1 以降なら必ずある
# 頼み方の言葉 → 種類
WORDS = [("教科書", "kyokasho"), ("ポップ", "pop"), ("丸ゴシ", "maru"), ("丸文字", "maru"), ("明朝", "mincho"),
         ("ＵＤ", "ud"), ("UD", "ud"), ("ゴシック", "gothic")]

_installed = None


def installed():
    """このPCに入っている書体の名前(英語名と日本語名)。Windows 以外や、調べられないときは空。"""
    global _installed
    if _installed is not None:
        return _installed
    names = set()
    if os.name == "nt":
        try:
            script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Add-Type -AssemblyName System.Drawing;"
                      "$ja=[Globalization.CultureInfo]::GetCultureInfo('ja-JP');"
                      "$en=[Globalization.CultureInfo]::GetCultureInfo('en-US');"
                      "foreach($f in (New-Object System.Drawing.Text.InstalledFontCollection).Families)"
                      "{ $f.GetName($en.LCID); $f.GetName($ja.LCID) }")
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=40,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            names = {n.strip() for n in r.stdout.splitlines() if n.strip()}
        except Exception:
            names = set()
    _installed = names
    return names


def style_of(text, default="gothic"):
    """頼まれた文から書体の種類を決める(「明朝体で」「ポップな感じで」など)。"""
    for word, style in WORDS:
        if word in str(text):
            return style
    return default


def pick(style):
    """(見出しの書体, 本文の書体, 代わりにした書体があればその説明)。入っていない書体は使わない。"""
    have = installed()
    label, heads, bodies = STYLES.get(style, STYLES["gothic"])
    if not have:  # 調べられない(Windows 以外など): Windows に必ずある書体
        return FALLBACK[0], FALLBACK[1], ""
    head = next((n for n in heads if n in have), None)
    body = next((n for n in bodies if n in have), None)
    note = ""
    if not head:
        note = f"{label}の書体がこのPCに無いため、ゴシック体で作りました"
        if style == "pop":
            note += "（ポップ体は Microsoft Office に付いてくる「HG創英角ポップ体」を使います）"
        head = next((n for n in STYLES["gothic"][1] if n in have), FALLBACK[0])
    if not body and not note:
        note = f"{label}の書体がこのPCに無いため、本文はゴシック体で作りました"
    if not body and style in ("mincho", "kyokasho"):
        note += "（Windows の設定「オプション機能」の「日本語の追加フォント」を入れると使えます）"
    body = body or next((n for n in STYLES["gothic"][2] if n in have), FALLBACK[1])
    return head, body, note


def choices():
    """設定画面の選択肢 [(種類, 表示名)]。"""
    return [(k, v[0]) for k, v in STYLES.items()]
