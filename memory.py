"""会話の記憶。
- 長い会話: 古いやりとりは短い「要約」にまとめ、新しいやりとりはそのまま AI に渡す(正確さと速さの両立)
- ずっと覚えておくこと: 「〜を覚えておいて」で覚え、「〜を忘れて」で忘れる(設定の「AI」タブでも見直せる)
要約は返事のあと手が空いたときに裏で作り、話しかけられたらすぐやめる(返事を遅らせない)。"""
import json
import re
import threading

import requests

import config

# 「〜を覚えておいて」「〜って記憶して」
_REMEMBER = re.compile(r"^(?P<fact>.+?)(?:ということ|こと)?(?:だ|です)?(?:って|と|を|は)?[、,\s]*"
                       r"(?:覚え(?:ておいて|といて|ててね|てて|てね|て)|記憶して(?:おいて)?|メモして(?:おいて)?)"
                       r"(?:ください|ほしい|欲しい|ね|よ)?[。！!]*$")
_FORGET_ALL = re.compile(r"(?:覚えて(?:いる|る)こと|記憶)?を?(?:全部|すべて|ぜんぶ)忘れて")
_FORGET = re.compile(r"^(?P<what>.+?)(?:のこと)?(?:は|を)?忘れて(?:ください|ほしい|ね)?[。！!]*$")


def parse(text):
    """("remember", 事実) / ("forget", 言葉) / ("forget_all", "") / None"""
    t = text.strip()
    if _FORGET_ALL.search(t):
        return ("forget_all", "")
    m = _REMEMBER.match(t)
    if m and len(m.group("fact")) >= 2:
        return ("remember", m.group("fact").strip("、, "))
    m = _FORGET.match(t)
    if m and len(m.group("what")) >= 2:
        return ("forget", m.group("what").strip("、, "))
    return None


def apply(facts, change):
    kind, value = change
    facts = list(facts)
    if kind == "remember":
        if value not in facts:
            facts.append(value)
    elif kind == "forget":
        facts = [f for f in facts if value not in f and f not in value]
    elif kind == "forget_all":
        facts = []
    return facts


# ---------------- 古いやりとりの要約 ----------------
class Summarizer:
    """返事のあとの空き時間に、古いやりとりを要約する。話しかけられたら cancel() で即やめる。"""

    def __init__(self):
        self._stop = threading.Event()
        self._busy = False

    def cancel(self):
        self._stop.set()

    def start(self, thread, keep, on_done):
        """thread の、新しい keep 往復より古いやりとりを、前の要約と合わせて要約し直す。"""
        import threads
        all_pairs = threads.pairs(thread)
        upto = len(all_pairs) - keep
        if self._busy or upto <= thread.get("summary_upto", 0):
            return
        old = all_pairs[thread.get("summary_upto", 0):upto]
        prev = thread.get("summary", "")
        self._stop.clear()
        self._busy = True
        threading.Thread(target=self._run, args=(prev, old, upto, on_done), daemon=True).start()

    def _run(self, prev, pairs, upto, on_done):
        try:
            convo = "\n".join(f"ユーザー: {u}\nAI: {a}" for u, a in pairs)
            prompt = ("次の会話の要点を、あとで話の続きができるように日本語で200字以内にまとめてください。"
                      "ユーザーの名前・好み・決めたこと・頼まれたこと・話題の流れを優先し、あいさつなどは省いてください。"
                      "要約だけを書いてください。\n\n"
                      + (f"【これまでの要約】\n{prev}\n\n" if prev else "") + f"【新しい会話】\n{convo}")
            import llm
            body = {"model": config.OLLAMA_MODEL, "stream": True, "keep_alive": "15m",
                    "messages": [{"role": "user", "content": prompt}],
                    "options": llm.ai_options(temperature=0, num_ctx=4096)}
            import models
            if models.thinks(config.OLLAMA_MODEL):
                body["think"] = False
            text = ""
            with requests.post(config.OLLAMA_URL, json=body, timeout=120, stream=True) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if self._stop.is_set():  # 話しかけられた: 接続を切ると、AIもすぐ手を止める
                        return
                    if line:
                        text += (json.loads(line).get("message") or {}).get("content") or ""
            text = text.strip()[:400]
            if text and not self._stop.is_set():
                on_done(text, upto)
        except Exception:
            pass  # 要約できなくても、会話はそのまま続けられる
        finally:
            self._busy = False
