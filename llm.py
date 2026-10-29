"""Ollama API へ問い合わせ、Tool Call を判定・実行する。"""
import json
import re
import time
from collections import deque

import requests

import config
import tools


SOURCES = "\n\n出典:\n"  # 返答のうち、これより後ろは画面表示用(読み上げない)
IMAGES = "\n\n画像:\n"   # この後ろは画像一覧(JSON)。画面に表示し、読み上げない


def friendly(error):
    """うまく答えられなかったときの、自然な言い方(技術的な中身は記録だけに残す)。"""
    e = str(error)
    if any(k in e for k in ("11434", "Connection refused", "Max retries", "ConnectionError", "10061")):
        return "ごめんなさい、いま考える準備（AI）が整っていないみたいです。少し待ってから、もう一度話しかけてもらえますか？"
    if "timed out" in e.lower() or "timeout" in e.lower():
        return "考えるのに時間がかかりすぎてしまいました。すみませんが、もう一度お願いできますか？"
    if "not found" in e and "model" in e:
        return "使うAIモデルがまだ準備できていないようです。設定の「更新・情報」にある「部品を準備」から準備してください。"
    return "すみません、うまくお答えできませんでした。少し言い方を変えて、もう一度お願いできますか？"


def split_reply(reply):
    """返答を (本文, 出典の行, 画像 {"query", "items"} または None) に分ける。"""
    reply, _, images = reply.partition(IMAGES)
    body, _, sources = reply.partition(SOURCES)
    return body, sources, json.loads(images) if images else None

_history = deque()  # 直前のやりとり [(ユーザーの発言, 返答)]
_last = 0.0
on_delta = None      # 返事を少しずつ受け取る関数(作業プロセスが設定)。届いた分から表示・読み上げする


def system_prompt():
    return (f"あなたはWindows PCを操作するアシスタント「{config.AI_NAME}」です。"
            "PC操作が必要な命令には必ず用意された関数を呼び出してください。"
            "調べものや質問には search_summary、画像や写真を探すときは image_search 関数を使ってください。"
            "関数が不要な会話には日本語で一文だけ短く答えてください。")


def _remember(text, reply):
    """会話の記憶。設定の往復数だけ覚え、しばらく話しかけなければ忘れる。"""
    global _last
    _history.append((text, split_reply(reply)[0][:300]))
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


def summarize(query, material):
    """検索結果を、質問に答える形で短くまとめる(書いた分から順に画面と読み上げへ流す)。"""
    prompt = (f"次の検索結果をもとに、「{query}」そのものについて日本語で2〜3文で簡潔に答えてください。"
              f"「{query}」に関係ない一般的な説明はしないでください。"
              "検索結果に書かれていないことは書かず、情報が見つからなければそう伝えてください。\n\n" + material)
    msg = _chat([{"role": "user", "content": prompt}], use_tools=False, stream_out=True)
    return (msg.get("content") or "").strip()


def _chat(messages, use_tools=True, stream_out=False):
    """Ollama に問い合わせる。返事は少しずつ受け取り、stream_out なら届いた分を on_delta へ渡す。
    関数呼び出し(JSON)らしい返事は画面に出さない。"""
    body = {"model": config.OLLAMA_MODEL, "messages": messages, "stream": True,
            "options": {"temperature": 0, "num_ctx": 4096}, "keep_alive": "30m"}
    if use_tools:
        body["tools"] = tools.schemas()
    content, calls, shown = "", [], 0
    with requests.post(config.OLLAMA_URL, json=body, timeout=config.OLLAMA_TIMEOUT, stream=True) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            msg = json.loads(line).get("message") or {}
            calls += msg.get("tool_calls") or []
            content += msg.get("content") or ""
            if stream_out and on_delta and not calls and not content.lstrip().startswith(("{", "`")):
                if len(content) > shown:
                    on_delta(content[shown:])
                    shown = len(content)
    return {"role": "assistant", "content": content, "tool_calls": calls}


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


def ask(text, history=None):
    """history を渡すとその会話の続きとして答える(チャットのスレッドごとの記憶)。"""
    global _last
    if history is not None:
        _history.clear()
        _history.extend(history)
        _last = time.monotonic()  # スレッドの会話は時間が空いても忘れない
    reply = _ask(text)
    _remember(text, reply)
    return reply


# はっきりした言い方は AI に判断させずに直接実行する(速く、小さいモデルでも確実)
_ROUTES = [
    (re.compile(r"^(?P<q>.+?)の?(?:写真|画像|イラスト|絵)を?(?:探して|さがして|見せて|検索して|表示して|出して|調べて|しらべて|見つけて|ちょうだい|ください|ほしい|欲しい)"),
     "image_search"),
    (re.compile(r"^(?P<q>.+?)を?(?:起動して|立ち上げて)"), "launch_app"),
    (re.compile(r"^(?P<q>.+?)(?:について|を|って)?(?:調べて|しらべて|検索して|教えて)"), "search_summary"),
]
_NOT_SEARCH = re.compile(r"ブラウザ|あなた|きみ|君|お前|自分|さっき|それ|これ|あれ")  # 会話の続き・ブラウザ指定は AI に任せる


def quick_route(text):
    """(関数名, 引数) を返す。当てはまらなければ None。"""
    t = text.strip().rstrip("。.!！?？")
    if not config.QUICK_ROUTE or _NOT_SEARCH.search(t):
        return None
    for pattern, name in _ROUTES:
        m = pattern.match(t)
        if m and m.group("q").strip(" 、,をのは"):
            key = "name" if name == "launch_app" else "query"
            return name, {key: m.group("q").strip(" 、,をのは")}
    return None


# PC操作や調べものが要りそうな言い方(当てはまらない普通の会話では、関数を渡さずにすぐ答え始める)
_NEEDS_TOOLS = re.compile(
    r"開い|ひらい|起動|立ち上げ|閉じ|検索|調べ|探し|さがし|見つけ|ファイル|フォルダ|作成|作って|保存|削除|消して|"
    r"移動|コピー|名前を変え|リネーム|一覧|ブラウザ|サイト|ページ|URL|画像|写真|ロック|音量|ニュース|天気|最新|"
    r"今日|明日|昨日|いま何|今何|何時|価格|値段|株価|スクリーンショット|デスクトップ|ドキュメント|ダウンロード")


def needs_tools(text):
    return bool(_NEEDS_TOOLS.search(text))


def _ask(text):
    route = quick_route(text)
    if route:
        return tools.run_tool(*route)
    messages = [{"role": "system", "content": system_prompt()}, *_context(), {"role": "user", "content": text}]
    if not needs_tools(text):
        # ふつうの会話: 関数の一覧を渡すと、返事を最後まで書き終えるまで届かないことがある(読み上げが遅れる)ので、
        # 渡さずに、書けた分からすぐ画面と読み上げへ流す
        reply = (_chat(messages, use_tools=False, stream_out=True).get("content") or "").strip()
        return reply or "うまく答えをまとめられませんでした。もう少し詳しく聞いてもらえますか？"
    results = []
    for _ in range(config.MAX_TOOL_STEPS):
        msg = _chat(messages, stream_out=True)
        calls = parse_tool_calls(msg)
        if not calls:
            reply = (msg.get("content") or "").strip() if not results else " ".join(results)
            return reply or "うまく答えをまとめられませんでした。もう少し詳しく聞いてもらえますか？"
        messages.append(msg)
        for name, args in calls:
            res = tools.run_tool(name, args)
            results.append(res)
            messages.append({"role": "tool", "content": res})
        if not config.SUMMARIZE_AFTER_TOOL:
            return " ".join(results)
    return _chat(messages, use_tools=False, stream_out=True).get("content", "").strip() or " ".join(results)
