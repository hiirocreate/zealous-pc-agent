"""ウェイクワード「ウェイク、<AI名>」の検出。AI名・ウェイク語は設定から変更可能。"""
import functools
import re

import config

_SEP = r"[\s、。,.!！?？・～〜\-]*"


@functools.lru_cache(maxsize=4)
def _pattern(wakes, names):
    alt = lambda ws: "(?:" + "|".join(re.escape(w) for w in sorted(ws, key=len, reverse=True) if w) + ")"
    return re.compile(r"^\s*" + alt(wakes) + _SEP + alt(names) + _SEP, re.IGNORECASE)


def strip_wake_word(text):
    """先頭にウェイクワードがあれば残りの命令文を、無ければ None を返す。"""
    names = tuple([config.AI_NAME] + list(config.AI_NAME_ALIASES))
    m = _pattern(tuple(config.WAKE_WORDS), names).match(text)
    return text[m.end():].strip() if m else None


def voice_command(text, from_button):
    """音声から実行する命令を決める。実行しないときは None。
    マイクボタンで話した内容はそのまま(合図の言葉を言った場合は取り除く)。
    常時待ち受けで拾った内容は、合図の言葉で始まるものだけ。"""
    cmd = strip_wake_word(text)
    return (cmd or text) if from_button else cmd
