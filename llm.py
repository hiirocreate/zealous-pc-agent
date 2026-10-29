"""Ollama API へ問い合わせ、Tool Call を判定・実行する。"""
import json
import re

import requests

import config
import tools


def system_prompt():
    return (f"あなたはWindows PCを操作するアシスタント「{config.AI_NAME}」です。"
            "PC操作が必要な命令には必ず用意された関数を呼び出してください。"
            "関数が不要な会話には日本語で一文だけ短く答えてください。")


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
    messages = [{"role": "system", "content": system_prompt()}, {"role": "user", "content": text}]
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
