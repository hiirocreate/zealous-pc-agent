"""Ollama API へ問い合わせ、Tool Call を判定・実行する。"""
import json
import re
import time
from collections import deque

import requests

import config
import tools


SOURCES = "\n\n出典:\n"  # 返答のうち、これより後ろは画面表示用(読み上げない)

_history = deque()  # 直前のやりとり [(ユーザーの発言, 返答)]
_last = 0.0


def system_prompt():
    return (f"あなたはWindows PCを操作するアシスタント「{config.AI_NAME}」です。"
            "PC操作が必要な命令には必ず用意された関数を呼び出してください。"
            "調べものや質問には search_summary 関数を使ってください。"
            "関数が不要な会話には日本語で一文だけ短く答えてください。")


def _remember(text, reply):
    """会話の記憶。設定の往復数だけ覚え、しばらく話しかけなければ忘れる。"""
    global _last
    _history.append((text, reply.split(SOURCES)[0][:300]))
    while len(_history) > config.CONTEXT_TURNS:
        _history.popleft()
    _last = time.monotonic()


def _context():
    if time.monotonic() - _last > config.CONTEXT_RESET_MIN * 60:
        _history.clear()
    msgs = []
    for user, reply in _history:
        msgs += [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
    return msgs


def summarize(query, results, docs):
    """検索結果の本文を、質問に答える形で短くまとめる。"""
    material = "\n\n".join(f"[{i}] {r['title']}\n{d}" for i, (r, d) in enumerate(zip(results, docs), 1))
    prompt = (f"次の検索結果を読んで「{query}」について日本語で3〜4文に要点をまとめてください。"
              "検索結果に書かれていないことは書かないでください。\n\n" + material)
    msg = _chat([{"role": "user", "content": prompt}], use_tools=False)
    return (msg.get("content") or "").strip()


def _chat(messages, use_tools=True):
    body = {"model": config.OLLAMA_MODEL, "messages": messages, "stream": False,
            "options": {"temperature": 0}, "keep_alive": "30m"}
    if use_tools:
        body["tools"] = tools.schemas()
    r = requests.post(config.OLLAMA_URL, json=body, timeout=config.OLLAMA_TIMEOUT)
    r.raise_for_status()
    return r.json()["message"]


def parse_tool_calls(message):
    """正式な tool_calls と、本文にJSONで書かれた呼び出し(小型モデルの癖)の両方を拾う。"""
    calls = []
    for c in message.get("tool_calls") or []:
        fn = c.get("function", {})
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        calls.append((fn.get("name"), args))
    if calls:
        return calls
    m = re.search(r"\{.*\}", message.get("content") or "", re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
        except ValueError:
            return []
        name = obj.get("name") or obj.get("function")
        if name in tools.TOOLS:
            return [(name, obj.get("arguments") or obj.get("parameters") or {})]
    return []


def ask(text):
    reply = _ask(text)
    _remember(text, reply)
    return reply


def _ask(text):
    messages = [{"role": "system", "content": system_prompt()}, *_context(), {"role": "user", "content": text}]
    results = []
    for _ in range(config.MAX_TOOL_STEPS):
        msg = _chat(messages)
        calls = parse_tool_calls(msg)
        if not calls:
            return (msg.get("content") or "").strip() if not results else " ".join(results)
        messages.append(msg)
        for name, args in calls:
            res = tools.run_tool(name, args)
            results.append(res)
            messages.append({"role": "tool", "content": res})
        if not config.SUMMARIZE_AFTER_TOOL:
            return " ".join(results)
    return _chat(messages, use_tools=False).get("content", "").strip() or " ".join(results)
