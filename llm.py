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


def take_confirm(reply):
    """返事から「確認待ちの操作」を取り出す。(残りの返事, 操作 または None)"""
    body, sep, data = reply.partition(tools.CONFIRM)
    return (body, json.loads(data)) if sep else (reply, None)


def split_reply(reply):
    """返答を (本文, 出典の行, 画像 {"query", "items"} または None) に分ける。"""
    reply, _, images = reply.partition(IMAGES)
    body, _, sources = reply.partition(SOURCES)
    return body, sources, json.loads(images) if images else None

_history = deque()  # 直前のやりとり [(ユーザーの発言, 返答)]
_last = 0.0
on_delta = None      # 返事を少しずつ受け取る関数(作業プロセスが設定)。届いた分から表示・読み上げする


_LANG_NAMES = {"ja": "日本語", "en": "英語", "zh": "中国語", "ko": "韓国語", "fr": "フランス語", "de": "ドイツ語",
               "es": "スペイン語", "it": "イタリア語", "pt": "ポルトガル語", "ru": "ロシア語"}


def answer_language():
    """返事に使う言葉(設定の「言語コード」に合わせる)。"""
    return _LANG_NAMES.get((getattr(config, "LANGUAGE", "ja") or "ja").lower(), "日本語")


def user_rule():
    """設定の「あなたの呼び方」をAIへの指示にする。"""
    call = (getattr(config, "USER_CALL", "") or "").strip()
    return f"ユーザーのことは「{call}」と呼んでください。" if call else ""


_summary = ""   # このスレッドの古いやりとりの要約(依頼ごとに受け取る)
_memory = []    # ユーザーについて、ずっと覚えておくこと(依頼ごとに受け取る)


def memory_rule():
    facts = [f for f in (_memory or []) if f]
    if not facts:
        return ""
    return "\n\n【ユーザーについて覚えていること】\n" + "\n".join(f"・{f}" for f in facts[:30])


def persona_rule():
    """設定の「AIの性格・話し方」を、AIへの指示にする(空なら何も足さない)。"""
    persona = (getattr(config, "PERSONA", "") or "").strip()
    if not persona:
        return ""
    return (f"\n\n【あなたの性格・話し方】{persona}\n"
            "この性格・話し方を、会話の最後まで必ず守ってください。"
            "実在の人物の名前が出てきても、本人になりすますことはせず、口調や雰囲気をまねるだけにしてください。")


def system_prompt():
    return (f"あなたはWindows PCを操作するアシスタント「{config.AI_NAME}」です。"
            "PC操作が必要な命令には必ず用意された関数を呼び出してください。"
            "調べものや質問には search_summary、画像や写真を探すときは image_search 関数を使ってください。"
            "関数が不要な会話には日本語で一文だけ短く答えてください。\n"
            "【必ず守ること】\n"
            f"・いつも{answer_language()}で答える(ユーザーが別の言葉で話しかけたときだけ、その言葉で答える)。\n"
            "・ユーザーの発言を翻訳したり、言い換えたりしない(翻訳を頼まれたときだけ翻訳する)。\n"
            "・最新の情報・ニュース・今日のことを聞かれたら、必ず search_summary で調べてから答える。"
            "「最新の情報は提供できない」とは言わない。\n"
            "・URLを推測で作らない。サイトを開く・サイト内で探すときは open_site、動画を流すときは play_video を使う。\n"
            "・PCの操作(ファイルを作る・探す・開く・消すなど)は、必ず関数を呼び出して行う。"
            "関数を呼んでいないのに「作成しました」「開きます」などと言わない。できないときは、できないと正直に言う。\n"
            "・これまでの会話の流れを踏まえて、いまの質問そのものに答える。"
            "「それ」「さっきの」などは、直前の会話を指していると考える。"
            + user_rule() + memory_rule() + persona_rule())


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
    if _summary:  # 古いやりとりは要約で(新しいやりとりは下にそのまま)
        msgs.append({"role": "system", "content": f"【この会話のこれまでの要約】\n{_summary}"})
    for user, reply in _history:
        msgs += [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
    return msgs


def summarize(query, material):
    """検索結果を、質問に答える形で短くまとめる(書いた分から順に画面と読み上げへ流す)。"""
    prompt = (f"次の検索結果をもとに、「{query}」そのものについて日本語で2〜3文で簡潔に答えてください。"
              f"「{query}」に関係ない一般的な説明はしないでください。"
              "検索結果に書かれていないことは書かず、情報が見つからなければそう伝えてください。"
              + persona_rule() + "\n\n" + material)
    msg = _chat([{"role": "user", "content": prompt}], use_tools=False, stream_out=True)
    return (msg.get("content") or "").strip()


class OffTrack(Exception):
    """返事が質問とかみ合っていない(日本語の質問に、英語の翻訳を返し始めたなど)。"""


_JA = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def off_track(question, reply):
    """日本語で聞かれたのに、返事の書き出しが英語ばかりになっているか(小さなモデルが「質問の英訳」を始める癖)。"""
    if (getattr(config, "LANGUAGE", "ja") or "ja").lower() != "ja":
        return False  # 日本語以外で使う設定のときは、確かめない
    if not question or not _JA.search(question) or re.search(r"英語|英訳|翻訳|english|translate", question, re.I):
        return False
    head = reply.strip()[:40]
    letters = sum(c.isascii() and c.isalpha() for c in head)
    return len(head) >= 12 and letters >= 8 and len(_JA.findall(head)) <= 2


def _chat(messages, use_tools=True, stream_out=False, guard=None):
    """Ollama に問い合わせる。返事は少しずつ受け取り、stream_out なら届いた分を on_delta へ渡す。
    関数呼び出し(JSON)らしい返事は画面に出さない。
    guard(ユーザーの質問)を渡すと、書き出しを少しだけ見てから流し、質問とかみ合わなければ OffTrack を出す。"""
    body = {"model": config.OLLAMA_MODEL, "messages": messages, "stream": True,
            "options": {"temperature": 0, "num_ctx": 4096}, "keep_alive": "30m"}
    if use_tools:
        body["tools"] = tools.schemas()
    import models
    if models.thinks(config.OLLAMA_MODEL):
        body["think"] = False  # 考える過程を書かせない(書かせると、話し始めるまでが遅くなる)
    content, calls, shown = "", [], 0
    with requests.post(config.OLLAMA_URL, json=body, timeout=config.OLLAMA_TIMEOUT, stream=True) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            msg = json.loads(line).get("message") or {}
            calls += msg.get("tool_calls") or []
            content += msg.get("content") or ""
            if guard is not None and shown == 0 and not calls:
                if len(_JA.findall(content)) >= 2:
                    guard = None  # 日本語で書き始めた: 確かめるまでもないので、すぐ流す
                elif len(content.strip()) < 16:
                    continue  # 書き出しがそろうまで少し待つ(画面や読み上げにはまだ出さない)
                elif off_track(guard, content):
                    raise OffTrack(content[:40])
                else:
                    guard = None
            if stream_out and on_delta and not calls and not content.lstrip().startswith(("{", "`")):
                ok = visible(content)
                if len(ok) > shown:
                    on_delta(ok[shown:])
                    shown = len(ok)
    if guard is not None and not calls and off_track(guard, content):
        raise OffTrack(content[:40])
    if stream_out and on_delta and not calls and not content.lstrip().startswith(("{", "`")):
        ok = visible(content)
        if len(ok) > shown:
            on_delta(ok[shown:])  # 短い返事(待っている間に書き終わった分)
    return {"role": "assistant", "content": content, "tool_calls": calls}


_FIX = ("前の返事は、質問に答えずに翻訳などをしていました。翻訳はせず、日本語で、"
        "これまでの会話の流れに沿って、いまの質問そのものに答えてください。")


def _chat_on_track(messages, question, use_tools=False):
    """質問とかみ合わない返事なら、直すように一言そえて1回だけやり直す。"""
    try:
        return _chat(messages, use_tools=use_tools, stream_out=True, guard=question)
    except OffTrack as e:
        import zlog
        zlog.note(f"返事がかみ合わないため、やり直し({len(str(e))}文字で検出)")
        retry = messages[:-1] + [{"role": "system", "content": _FIX}, messages[-1]]
        try:
            return _chat(retry, use_tools=use_tools, stream_out=True, guard=question)
        except OffTrack:
            return _chat(retry, use_tools=use_tools, stream_out=True)


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
    content = message.get("content") or ""
    m = re.search(r"\{.*\}", content, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            name = obj.get("name") or obj.get("function")
            if isinstance(name, dict):  # {"type":"function","function":{"name":..,"arguments":..}}
                obj, name = name, name.get("name")
            if name in tools.TOOLS:
                return [(name, obj.get("arguments") or obj.get("parameters") or {})]
        except (ValueError, AttributeError):
            pass
    # 小さなモデルが本文に書いてしまう、崩れた形(例: web_search "AIの最新ニュース")
    for name in sorted(tools.TOOLS, key=len, reverse=True):
        m = re.search(rf"\b{name}\b\W{{0,6}}[\"「']([^\"」']{{1,80}})[\"」']", content)
        if m:
            schema = tools.TOOLS[name][1]["function"]["parameters"]
            key = (schema.get("required") or list(schema["properties"]) or ["query"])[0]
            return [(name, {key: m.group(1)})]
    return []


# 本文に紛れ込んだ「関数の呼び出し」の書き出し(ここから先は画面に出さない)
_TOOL_TEXT = re.compile(r"\[Tools?\]|<tool_call>|\{\s*\"(?:type|name|function)\"|```|\b(?:"
                        + "|".join(re.escape(n) for n in tools.TOOLS) + r")\s*[\(\"「]")


def visible(content):
    """画面と読み上げに出してよい部分(関数の呼び出しらしい書き出しより前)。"""
    m = _TOOL_TEXT.search(content)
    return content[:m.start()].rstrip() if m else content


def ask(text, history=None, summary="", memory=None):
    """history を渡すとその会話の続きとして答える(チャットのスレッドごとの記憶)。
    summary: 古いやりとりの要約 / memory: ユーザーについてずっと覚えておくこと"""
    global _last, _summary, _memory
    _summary, _memory = summary or "", list(memory or [])
    if history is not None:
        _history.clear()
        _history.extend(history)
        _last = time.monotonic()  # スレッドの会話は時間が空いても忘れない
    reply = _ask(text)
    _remember(text, reply)
    return reply


# はっきりした言い方は AI に判断させずに直接実行する(速く、小さいモデルでも確実)
_SITE = (r"(?P<site>youtube|ユーチューブ|ようつべ|google|グーグル|yahoo|ヤフー|amazon|アマゾン|楽天|wikipedia|"
         r"ウィキペディア|twitter|ツイッター|instagram|インスタ(?:グラム)?|github|googleマップ|グーグルマップ|"
         r"ニコニコ(?:動画)?|netflix|ネットフリックス|spotify|スポティファイ|メルカリ)")
_BROWSER = r"(?:ブラウザ(?:から|で|を開いて)?[、,\s]*)?"
# サイト・動画の言い方(「ブラウザ」と言っていても、ここはすぐ実行する)
_WEB_ROUTES = [
    # 「YouTubeで〇〇の歌を上から順に流して」「再生回数順に流して」(何本も続けて)
    (re.compile(_BROWSER + r"(?:(?:youtube|ユーチューブ|ようつべ)(?:を)?(?:開いて|ひらいて|で|から)?[、,\s]*)?"
                r"(?P<q>.+?)の?(?:歌|曲|動画|音楽|mv|ＭＶ)?を?[、,\s]*"
                r"(?P<how>上から順に|上から順番に|順番に|順に|全部|続けて|まとめて|再生回数順に|再生回数が多い順に|"
                r"人気順に|新しい順に|新着順に)(?:上から)?(?:順に)?(?:流して|再生して|かけて)", re.I),
     "play_list"),
    # 「ブラウザからYouTube開いて、株式会社才の動画を流して」「YouTubeで〇〇を再生して」
    (re.compile(_BROWSER + r"(?:youtube|ユーチューブ|ようつべ)(?:を)?(?:開いて|ひらいて|で|から)?[、,\s]*"
                r"(?P<q>.+?)の?(?:動画|曲|音楽|mv|ＭＶ|映像|ライブ)?を?(?:流して|再生して|かけて|見せて|見たい)", re.I),
     "play_video"),
    (re.compile(r"(?P<q>.+?)の?(?:動画|曲|音楽|mv|ＭＶ|映像)を?(?:youtube|ユーチューブ)?で?(?:流して|再生して|かけて)", re.I),
     "play_video"),
    # 「Amazonで充電器を検索して」「楽天で〇〇を探して」
    (re.compile(_BROWSER + _SITE + r"(?:を開いて|で|の中で)[、,\s]*(?P<q>.+?)を?(?:検索して|探して|さがして|調べて|見せて)", re.I),
     "open_site"),
    # 「下にスクロールして」「上にスクロール」
    (re.compile(r"(?P<q>下|した|上|うえ)(?:に|へ|の方)?(?:少し|ちょっと)?スクロール(?:して)?"), "scroll"),
    # 「YouTubeを開いて」「ブラウザでAmazon開いて」
    (re.compile(_BROWSER + _SITE + r"(?:を)?(?:開いて|ひらいて|見せて)$", re.I), "open_site"),
]
_PLACE = r"(?:(?P<where>デスクトップ|ドキュメント|ダウンロード|ピクチャ)(?:に|の|にある|から)?)?"
_ROUTES = [
    # 「デスクトップのテンプレっていうテキストファイル探して」
    (re.compile(_PLACE + r"(?P<q>.+?)(?:という|っていう|って)?(?:テキスト|エクセル|ワード)?(?:ファイル|フォルダ)[をは]?"
                r"(?:探して|さがして|見つけて|探してきて|どこ)"), "find_files"),
    # 「デスクトップのテンプレってファイルを開いて」「メモ.txt を開いて」
    (re.compile(_PLACE + r"(?P<q>.+?)(?:という|っていう|って)?(?:テキスト|エクセル|ワード)?(?:ファイル|フォルダ)を?"
                r"(?:開いて|ひらいて)"), "open_file"),
    # 「メモ.txt を開いて」(拡張子つきの名前。example.com のようなサイトの名前は除く)
    (re.compile(_PLACE + r"(?P<q>[^\s/]+\.(?!(?:com|net|org|jp|io|co|dev|app|ai|info|me|tv|us|uk)(?![A-Za-z0-9]))"
                r"[A-Za-z0-9]{1,5})を?(?:開いて|ひらいて)"), "open_file"),
    (re.compile(r"^(?P<q>.+?)の?(?:写真|画像|イラスト|絵)を?(?:探して|さがして|見せて|検索して|表示して|出して|調べて|しらべて|見つけて|ちょうだい|ください|ほしい|欲しい)"),
     "image_search"),
    (re.compile(r"^(?P<q>.+?)を?(?:起動して|立ち上げて)"), "launch_app"),
    (re.compile(r"^(?P<q>.+?ニュース.*?)(?:を|について)?(?:いくつか|少し|ちょっと)?"
                r"(?:教えて|紹介して|しょうかいして|知りたい|調べて|見せて|まとめて)"), "search_summary"),
    (re.compile(r"^(?P<q>.+?)(?:について|を|って)?(?:調べて|しらべて|検索して|教えて|紹介して|しょうかいして)"),
     "search_summary"),
]
_NOT_SEARCH = re.compile(r"ブラウザ|あなた|きみ|君|お前|自分|さっき|それ|これ|あれ")  # 会話の続き・ブラウザ指定は AI に任せる


# 直前の画面操作(「もっと下に」「少し戻って」など、続きの指示に使う)
_last_scroll = {"direction": None, "amount": 5}
_MORE = r"(?:もっと|もう(?:少し|ちょっと|すこし)|さらに|更に|続けて|もう一回|もう1回|もういっかい)"
_FOLLOW = [
    (re.compile(r"(?:" + _MORE[3:-1] + r"|少し|ちょっと|すこし)?[、\s]*(?P<dir>下|した|上|うえ)(?:に|へ|の方|のほう)?"
                r"(?:少し|ちょっと)?(?:スクロール)?(?:して|お願い|ね)?$"), "dir"),
    (re.compile(r"(?:少し|ちょっと|すこし|1つ|ひとつ)?(?:戻って|戻して|もどって|もどして|戻る)(?:ください)?$"), "back"),
    (re.compile(_MORE + r"(?:スクロール)?(?:して|お願い|ね)?$"), "more"),
]


def follow_up(t):
    """「もっと下に」「少し戻って」など、直前のスクロールの続きなら (関数名, 引数)。"""
    last = _last_scroll["direction"]
    for pattern, kind in _FOLLOW:
        m = pattern.match(t)
        if not m:
            continue
        if kind == "dir":
            down = m.group("dir") in ("下", "した")
            if last is None and not re.match(_MORE, t) and "スクロール" not in t:
                return None  # 「下に」だけで、直前にスクロールもしていない: ふつうの会話として扱う
            more = re.match(_MORE, t)  # 「もっと下に」: 同じ向きなら前と同じ量。「下に(スクロール)」: いつもの量
            amount = _last_scroll["amount"] if more and last == ("down" if down else "up") else 5
            if re.search(r"少し|ちょっと|すこし", t) and not more:
                amount = 2
            return "scroll", {"direction": "down" if down else "up", "amount": amount}
        if last is None:
            return None
        if kind == "back":  # 少しだけ逆へ
            return "scroll", {"direction": "up" if last == "down" else "down", "amount": 2}
        return "scroll", {"direction": last, "amount": _last_scroll["amount"]}
    return None


def quick_route(text):
    """(関数名, 引数) を返す。当てはまらなければ None。"""
    t = text.strip().rstrip("。.!！?？")
    if not config.QUICK_ROUTE:
        return None
    follow = follow_up(t)
    if follow:
        return follow
    # 「じゃあそれ調べて」「それについて検索して」: 直前の質問を調べる
    if re.fullmatch(r"(?:じゃあ|では|なら|じゃ|それじゃ)?[、\s]*(?:それ|これ|そのこと|その件)(?:を|について)?[、\s]*"
                    r"(?:調べて|しらべて|検索して|調べてみて|調べてきて)(?:ください|よ|ね)?", t) and _history:
        prev = _history[-1][0].strip().rstrip("。.!！?？")
        for pattern, name in _ROUTES:  # 前の質問から「〜して」などを除いて、調べる言葉だけにする
            m = pattern.match(prev)
            if m and name == "search_summary":
                prev = m.group("q").strip(" 、,をのは")
                break
        return "search_summary", {"query": prev[:80]}
    if not re.search(r"それ|これ|あれ|さっき", t):
        for pattern, name in _WEB_ROUTES:
            m = pattern.match(t)
            if m:
                q = (m.groupdict().get("q") or "").strip(" 、,をのは")
                if name == "play_video" and q:
                    return name, {"query": q}
                if name == "play_list" and q:
                    how = m.group("how")
                    order = "views" if re.search(r"再生回数|人気", how) else "newest" if re.search(r"新", how) else "relevance"
                    return "play_video", {"query": q, "order": order, "count": 10}
                if name == "open_site":
                    return name, {"site": m.group("site"), "query": q}
                if name == "scroll":
                    small = re.search(r"少し|ちょっと", t)
                    return name, {"direction": "down" if q in ("下", "した") else "up", "amount": 2 if small else 5}
    if _NOT_SEARCH.search(t):
        return None
    for pattern, name in _ROUTES:
        m = pattern.match(t)
        if m and m.group("q").strip(" 、,をのは"):
            q = m.group("q").strip(" 、,をのは")
            if name in ("find_files", "open_file"):
                args = {"name": q}
                if m.groupdict().get("where"):
                    args["path"] = m.group("where")
                return name, args
            key = "name" if name == "launch_app" else "query"
            return name, {key: q}
    return None


# PC操作や調べものが要りそうな言い方(当てはまらない普通の会話では、関数を渡さずにすぐ答え始める)
_NEEDS_TOOLS = re.compile(
    r"開い|ひらい|起動|立ち上げ|閉じ|検索|調べ|探し|さがし|見つけ|ファイル|フォルダ|作成|作って|保存|削除|消して|"
    r"移動|コピー|名前を変え|リネーム|一覧|ブラウザ|サイト|ページ|URL|画像|写真|ロック|音量|ニュース|天気|最新|"
    r"今日|明日|昨日|いま何|今何|何時|価格|値段|株価|スクリーンショット|デスクトップ|ドキュメント|ダウンロード|"
    r"クリック|押して|入力して|打って|タイプ|スクロール|キーを|ショートカット|貼り付け|ボタン|"
    r"切り替え|最小化|最大化|ウィンドウ|閉じて|動画|再生|流して|サイト|youtube|ユーチューブ|アマゾン|amazon")


_CLAIM = re.compile(r"(?:作成し|作り|保存し|削除し|移動し|コピーし|開き|開け|起動し|探し|見つけ|変更し|追記し|再生し|流し)"
                    r"(?:ました|ます|ておきます)|https?://")
# 「最新の情報は提供できません」のように、調べもせずに断る返事
_REFUSE = re.compile(r"(?:最新|現在|リアルタイム)の?(?:情報|ニュース)[^。]*(?:できません|ありません|持っていません|わかりません)|"
                     r"(?:能力|機能)は(?:ありません|持っていません)|インターネットに(?:アクセス|接続)でき")
_DO_IT = ("あなたはまだ何も操作していません。操作が必要なら、必ず用意された関数を呼び出してください。"
          "ファイルを探すなら find_files、開くなら open_file、サイトは open_site、動画は play_video を使ってください。"
          "URLを推測で書かないでください。最新の情報やニュースは search_summary で調べてから答えてください。")


def needs_tools(text):
    return bool(_NEEDS_TOOLS.search(text))


def _run(name, args):
    res = tools.run_tool(name, args)
    if name == "scroll" and "スクロールしました" in res:  # 「もっと下に」などのために覚えておく
        down = not (str(args.get("direction", "")).lower().startswith("u") or "上" in str(args.get("direction", "")))
        _last_scroll.update(direction="down" if down else "up", amount=int(args.get("amount") or 5))
    return res


def _ask(text):
    route = quick_route(text)
    if route:
        return _run(*route)
    messages = [{"role": "system", "content": system_prompt()}, *_context(), {"role": "user", "content": text}]
    if not needs_tools(text):
        # ふつうの会話: 関数の一覧を渡すと、返事を最後まで書き終えるまで届かないことがある(読み上げが遅れる)ので、
        # 渡さずに、書けた分からすぐ画面と読み上げへ流す
        reply = (_chat_on_track(messages, text).get("content") or "").strip()
        if _REFUSE.search(reply):  # 「最新情報は提供できません」: 実際に調べて答える
            return _run("search_summary", {"query": text})
        return reply or "うまく答えをまとめられませんでした。もう少し詳しく聞いてもらえますか？"
    results = []
    for step in range(config.MAX_TOOL_STEPS):
        msg = _chat_on_track(messages, text, use_tools=True) if step == 0 else _chat(messages, stream_out=True)
        calls = parse_tool_calls(msg)
        if not calls and not results and step == 0 and _REFUSE.search(msg.get("content") or ""):
            return _run("search_summary", {"query": text})  # 「最新情報は提供できません」: 実際に調べて答える
        if not calls and not results and step == 0 and _CLAIM.search(msg.get("content") or ""):
            # 関数を呼ばずに「〜しました」「開きます」と言った(実際は何もしていない): 関数を使うよう促して1回やり直す
            import zlog
            zlog.note("操作したと言ったのに関数を呼んでいないため、やり直し")
            retry = messages[:-1] + [{"role": "system", "content": _DO_IT}, messages[-1]]
            msg = _chat(retry, stream_out=False)
            calls = parse_tool_calls(msg)
            if not calls:
                return "すみません、その操作はうまくできませんでした。何をどうしたいか、もう少し詳しく教えてもらえますか？"
        if not calls:
            reply = visible(msg.get("content") or "").strip() if not results else " ".join(results)
            return reply or "うまく答えをまとめられませんでした。もう少し詳しく聞いてもらえますか？"
        messages.append(msg)
        if "ブラウザ" not in text:  # 「調べて」なのにブラウザで検索ページを開こうとした: 調べて答える方にする
            calls = [("search_summary", a) if n == "web_search" else (n, a) for n, a in calls]
        for name, args in calls:
            res = _run(name, args)
            if tools.CONFIRM in res:  # 声で頼まれた危険な操作: 実行せずに確認を返す
                return res
            results.append(res)
            messages.append({"role": "tool", "content": res})
        if not config.SUMMARIZE_AFTER_TOOL:
            return " ".join(results)
    return _chat(messages, use_tools=False, stream_out=True).get("content", "").strip() or " ".join(results)
