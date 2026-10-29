"""会話の中で AI の性格・話し方を変える(「関西弁で話して」「話し方を元に戻して」など)。"""
import re

# 話し方を変えてほしいという言い方
_STYLE = re.compile(r"(?:みたいに|のように|ように|風に|ふうに|っぽく|口調で|調で|弁で|話し方で|キャラで|感じで|"
                    r"敬語で|タメ口で|ため口で|丁寧に|短く|簡潔に|詳しく|やさしく|優しく|明るく|元気に|落ち着いて)")
_VERB = re.compile(r"(?:話して|喋って|しゃべって|答えて|返事して|返して|接して|振る舞って|なって|話すように|答えるように)"
                   r"(?:ください|くれる|くれ|ね|よ|ほしい|欲しい)?$")
_RESET = re.compile(r"(?:話し方|口調|性格|キャラ|設定)を?(?:元に戻して|もとに戻して|戻して|リセットして|リセット|"
                    r"普通にして|ふつうにして|標準にして|やめて)")
_LEAD = re.compile(r"^(?:これから(?:は)?|今後(?:は)?|以後|今から|これからずっと|ずっと|次から(?:は)?)[、,\s]*")

PRESETS = [
    ("標準", ""),
    ("友だち・兄弟", "兄弟のように気さくなタメ口で、親しみをこめて話す。"),
    ("丁寧な執事", "落ち着いた丁寧な敬語で、執事のように控えめに話す。"),
    ("元気", "明るく元気に、楽しそうに話す。"),
    ("簡潔なプロ", "結論から先に、短く要点だけを答える。"),
    ("関西弁", "関西弁で、明るく親しみやすく話す。"),
]


def parse(text):
    """話し方を変える言い方なら ("set", 新しい話し方) / ("add", 足す話し方) / ("reset", "") を、違えば None を返す。"""
    t = text.strip().rstrip("。.!！")
    if _RESET.search(t):
        return ("reset", "")
    if len(t) > 60 or not _VERB.search(t) or not _STYLE.search(t):
        return None
    style = _LEAD.sub("", t)
    if style.startswith(("もっと", "もう少し", "もうちょっと", "さらに")):
        return ("add", style)
    return ("set", style)


def apply(current, change):
    """いまの話し方に、変更を当てた結果。"""
    kind, style = change
    if kind == "reset":
        return ""
    if kind == "add" and current:
        return (current.rstrip("。") + "。" + style).strip()
    return style
