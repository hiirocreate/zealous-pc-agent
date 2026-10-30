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


def take_files(reply):
    """返事から「作ったファイルの一覧」を取り出す。(残りの返事, [パス])"""
    body, sep, data = reply.partition(tools.FILES)
    if not sep:
        return reply, []
    try:
        return body, [p for p in json.loads(data) if isinstance(p, str)]
    except ValueError:
        return body, []


def split_reply(reply):
    """返答を (本文, 出典の行, 画像 {"query", "items"} または None) に分ける。"""
    reply = take_files(reply)[0]
    reply, _, images = reply.partition(IMAGES)
    body, _, sources = reply.partition(SOURCES)
    return body, sources, json.loads(images) if images else None

_history = deque()  # 直前のやりとり [(ユーザーの発言, 返答)]
_last = 0.0
on_delta = None      # 返事を少しずつ受け取る関数(作業プロセスが設定)。届いた分から表示・読み上げする
on_summary = None    # 長い会話の古い部分を圧縮したときに知らせる関数(スレッド番号, 要約, 要約した往復数)
on_status = None     # 時間のかかる作業の途中経過を、画面の状態の表示へ出す関数(「調べています」など)
_full = False        # このスレッドの会話をすべて参照するモード
on_retract = None    # 書き始めた返事を取り消す関数(返事の途中で操作を始めたとき。「開きます」などを話さないように)
_streamed = False    # 直前の問い合わせで、返事を画面と読み上げへ流したか
_tech = False        # テクニカルモード(コード・サーバーなど技術的な作業の補助)
TECH_TOOLS = ("read_text_file", "find_files", "find_in_files", "search_summary", "create_text_file", "open_file",
              "make_office_file", "search_by_meaning", "look_at_screen")
_attached = ""       # チャットに添付されたファイル・フォルダの中身(読み取って要約したもの)
_attach_key = ()
_office = None       # 資料づくりの前の聞き取り中 {"kind", "request", "topic", "step", "source", "content", "design"}
_office_ready = False  # 聞き取りが済んだ(本当に作ってよい)
_current_text = ""   # いま答えている、ユーザーの発言
_choice = None       # どれにするか聞いている候補 {"tool", "arg", "options", "labels", "args"}


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
            "・天気は get_weather、最新の情報・ニュース・今日のことは search_summary で、必ず調べてから答える。"
            "「最新の情報は提供できない」とは言わない。\n"
            "・URLを推測で作らない。サイトを開く・サイト内で探すときは open_site、動画を流すときは play_video を使う。\n"
            "・開いているWebページの中の操作(リンクやボタンを押す・入力する・選ぶ・スクロール・戻る・動画の操作・"
            "ページの内容を読む)は、web_ で始まる関数を使う。押す名前が見つからなければ、返ってきた項目の名前から選び直す。\n"
            "・メールの操作(既読にする・未読の数・フォルダの名前を変える)は mail_ で始まる関数で、"
            "メールアプリを開かずに行う。\n"
            "・ファイルの中身(書かれている言葉や話題)で探すときは find_in_files を使う。\n"
            "・Word・PowerPoint・Excel のファイル(資料・文書・表)を作るときは make_office_file を使う。\n"
            "・アプリを開く・起動するときは launch_app を使う(click_on は、開いているウィンドウの中のボタンを押すときだけ)。\n"
            "・PCの操作(ファイルを作る・探す・開く・消すなど)は、必ず関数を呼び出して行う。"
            "関数を呼んでいないのに「作成しました」「開きます」などと言わない。できないときは、できないと正直に言う。\n"
            "・これまでの会話の流れを踏まえて、いまの質問そのものに答える。"
            "「それ」「さっきの」などは、直前の会話を指していると考える。"
            + user_rule() + memory_rule() + persona_rule())


def tech_prompt():
    return (f"あなたは、経験豊富なソフトウェアエンジニア兼インフラエンジニアとして働くアシスタント「{config.AI_NAME}」です。"
            "いまはテクニカルモードです。プログラミング・コードの添削・Web制作・サーバー・ネットワーク・クラウド・"
            "データベース・セキュリティなど、IT の技術的な作業を手伝います。\n"
            "【必ず守ること】\n"
            f"・{answer_language()}で答える(コード・コマンド・エラーメッセージはそのまま)。\n"
            "・コード・コマンド・設定ファイルは、必ず ``` で囲み、言語名を付ける(例: ```python、```bash、```nginx)。\n"
            "・まず結論、次に理由と手順。長くなるときは見出しや箇条書きで整理する。\n"
            "・コードの添削は「問題点 → 直したコード → 変えた理由」の順。直した箇所が分かるようにする。\n"
            "・存在しない関数・オプション・コマンドを推測で作らない。確かでないことは、確かでないと書く。\n"
            "・削除・上書き・本番環境の変更・ポートの開放など、危ない操作には注意点と元に戻す方法を書く。\n"
            "・パスワード・APIキー・秘密鍵は、会話に貼らずに伏せるよう伝える。\n"
            "・PCのファイルの中身が必要なら read_text_file で読み、最新の情報や公式ドキュメントは search_summary で調べる。"
            "書いたコードを保存するよう頼まれたら create_text_file、Word・PowerPoint・Excel のファイルにするなら"
            " make_office_file を使う。"
            + user_rule() + memory_rule())


# 技術的な話題(この言葉と、頼み方・たずね方の両方があればテクニカルモードへ)
_TECH_TOPIC = re.compile(
    r"コード|プログラム|スクリプト|関数|クラス|変数|配列|バグ|デバッグ|例外|コンパイル|ビルド|デプロイ|リファクタ|"
    r"サーバー|サーバ|nginx|apache|docker|コンテナ|kubernetes|k8s|linux|ubuntu|centos|ssh|dns|ssl|tls|証明書|"
    r"ファイアウォール|ポート|データベース|sql|mysql|postgres|mongodb|redis|api|rest|graphql|git|github|"
    r"python|パイソン|javascript|ジャバスクリプト|typescript|java\b|ジャバ|c\+\+|c#|php|ruby|rust|golang|go言語|"
    r"html|css|react|vue|next\.js|node|npm|pip|aws|gcp|azure|lambda|正規表現|json|yaml|wordpress|"
    r"ドメイン|インフラ|ネットワーク|ip ?アドレス|vpn|ルーター|cron|シェル|bash|powershell|コマンド|ターミナル|"
    r"vscode|エンジニア|プログラミング|アルゴリズム|フレームワーク|ライブラリ|traceback|stack ?trace|"
    r"エラー(?:コード|メッセージ|が出|になる)", re.I)
_TECH_ASK = re.compile(r"書いて|作って|直して|添削|レビュー|教えて|どう|方法|設定|原因|なぜ|使い方|違い|手順|"
                       r"解決|意味|説明|おすすめ|できる|したい|[?？]")
_CODE_LIKE = re.compile(r"```|Traceback \(most recent|^\s*(?:def |class |import |from \S+ import|function |const |"
                        r"let |var |public |#include|<\?php|<html|SELECT |server \{)|[;{}]\s*$", re.M)


def looks_technical(text):
    """コード・サーバーなど、技術的な作業の話か。"""
    if _CODE_LIKE.search(text) and text.count("\n") >= 1:
        return True
    return bool(_TECH_TOPIC.search(text) and _TECH_ASK.search(text))


def _remember(text, reply):
    """会話の記憶。設定の往復数だけ覚え、しばらく話しかけなければ忘れる。"""
    global _last
    body = split_reply(reply)[0]
    _history.append((text, body if _full else body[:300]))
    while not _full and len(_history) > config.CONTEXT_TURNS:
        _history.popleft()
    _last = time.monotonic()


def _context():
    if time.monotonic() - _last > config.CONTEXT_RESET_MIN * 60:
        _history.clear()
    msgs = []
    if _attached:  # 添付されたファイル・フォルダ(この中身をもとに答える)
        msgs.append({"role": "system", "content": "【添付されたファイル・フォルダの内容】\n" + _attached +
                     "\n\n添付についての質問には、この内容だけを根拠に、具体的に答えてください。"
                     "書かれていないことは推測せず、分からないと伝えてください。"})
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


def page_answer(question, title, text):
    """開いているWebページの文章をもとに、質問に答える(質問が無ければ要約する)。"""
    ask_for = (f"「{question}」に日本語で簡潔に答えてください。" if (question or "").strip()
               else "内容の要点を日本語で3〜4文にまとめてください。")
    prompt = (f"次のWebページ「{title}」の文章をもとに、{ask_for}"
              "ページに書かれていないことは書かず、見つからなければそう伝えてください。"
              + persona_rule() + "\n\n" + text)
    msg = _chat([{"role": "user", "content": prompt}], use_tools=False, stream_out=True)
    return (msg.get("content") or "").strip() or "ページの内容をうまくまとめられませんでした"


def ai_options(**extra):
    """AIへの指定(読む量・温度など)に、使うCPUの数を足す。
    「控えめ」なら、論理コアの半分から1つ引いた数まで(少なくとも2)。CPUだけで動かすときに、
    PC全体がほぼ100%に張り付いて重くなるのを防ぐ(返事は少し遅くなるが、操作は軽いまま)。"""
    import os
    if getattr(config, "AI_CPU", "save") == "save":
        extra["num_thread"] = max(2, (os.cpu_count() or 4) // 2 - 1)
    return extra


def num_ctx(messages):
    """AIが一度に読む量(トークン)。渡す文が長いときだけ広げる。
    広げ方を4段階に限るのは、変えるたびに Ollama がモデルを読み込み直して遅くなるため。"""
    chars = sum(len(m.get("content") or "") for m in messages) + 2500  # 関数の説明などの分
    import models
    total = models.memory_gb()[0]
    # メモリの少ないPCでは上限を下げる(読む量が倍になると、会話の記憶に使うメモリも倍になるため)
    top = 8192 if 0 < total < 12 else 16384 if 0 < total < 24 else 32768
    for size in (4096, 8192, 16384, 32768):
        if chars <= size * 0.9 or size >= top:
            return size
    return 32768


def _fit(history, summary, tid, base):
    """全部を参照するモード: 会話が上限を超えたら、古い部分を要約に圧縮する(または参照しない)。"""
    limit = max(2000, int(getattr(config, "FULL_CONTEXT_LIMIT", 12000) or 12000))
    size = lambda pairs: sum(len(u) + len(a) for u, a in pairs)  # noqa: E731
    if size(history) + len(summary) <= limit:
        return history, summary
    keep = []  # 新しいやりとりから、上限の6割まで(毎回圧縮が起きないよう、余裕を残す)
    for pair in reversed(history):
        if keep and size(keep) + len(pair[0]) + len(pair[1]) > limit * 0.6:
            break
        keep.insert(0, pair)
    old = history[:len(history) - len(keep)]
    if not getattr(config, "FULL_CONTEXT_COMPRESS", True):
        return keep, ""
    import zlog
    zlog.note(f"会話が上限を超えたため、古い{len(old)}往復を圧縮")
    convo = "\n".join(f"ユーザー: {u}\nAI: {a}" for u, a in old)
    words = max(400, min(2000, limit // 6))
    prompt = (f"次の会話を、あとで話の続きができるように日本語で{words}字以内に要約してください。"
              "ユーザーの名前・好み・決めたこと・頼まれたこと・出てきた固有名詞や数字・話題の流れを優先し、"
              "あいさつなどは省いてください。要約だけを書いてください。\n\n"
              + (f"【これまでの要約】\n{summary}\n\n" if summary else "") + f"【会話】\n{convo}")
    try:
        new = (_chat([{"role": "user", "content": prompt}], use_tools=False).get("content") or "").strip()[:words + 200]
    except Exception as e:
        zlog.error(f"会話の圧縮: {e!r}")
        return keep, summary  # 圧縮できなくても、新しい分だけで答える
    if not new:
        return keep, summary
    if on_summary and tid:
        on_summary(tid, new, base + len(old))
    return keep, new


_DOC_GUIDE = {
    "pptx": ("PowerPoint の発表資料です。1行目に「# 題名」、2行目に副題を1行。続けて「## スライドの題名」で1枚ずつ、"
             "全部で5〜10枚。各スライドには「- 要点」を3〜5個(1つ40字以内で簡潔に)。手順は「1. 」の番号付きで。"
             "数字の比較や一覧は表(| 見出し | 見出し |、2行目は |---|---|)で。話す人向けの補足は「> 」で始める。"
             "最後のスライドは「## まとめ」。"),
    "docx": ("Word の文書です。1行目に「# 題名」、2行目に1行の概要。「## 見出し」で章を分け、本文は段落でていねいに書く。"
             "必要に応じて「### 小見出し」「- 箇条書き」「1. 番号」と表(| 見出し | 見出し |、2行目は |---|---|)を使う。"),
    "xlsx": ("Excel の表です。1行目に「# 題名」。「## シート名」ごとに、表(| 列名 | 列名 |、2行目は |---|---|)を1つ書く。"
             "数は数字だけを書き、単位は列名に入れる(例: 売上(円))。1列目は項目名にする。"
             "合計などの計算は =SUM(B3:B6) のような式で書いてもよい。"),
}


_DOC_QUALITY = (
    "【品質の決まり】"
    "・誤字脱字のない自然な{lang}で書く。同じ内容を別の場所で繰り返さない。"
    "・1つのページ(スライド・章)では1つのことを伝え、見出しは内容が分かる具体的な言葉にする。"
    "・数字・統計・日付・会社名・制度名などの事実は、【調べた情報】か、これまでの会話に書かれているものだけを使う。"
    "根拠の無い数字や事実は作らない(分からないところは、数字を使わずに書く)。"
    "・写真が理解を助けるページにだけ「!画像: 英語の検索語(例: !画像: solar panels on roof)」を1行入れる(全体で2つまで)。"
    "・前置き・あいさつ・説明・```は書かず、資料の中身だけを書く。")
_REVIEW = ("次の資料を校正してください。誤字脱字・表記ゆれ・同じ内容の重複・不自然な言い回し・根拠の無い断定を直し、"
           "見出しや箇条書きの書式(# / ## / ### / - / 1. / **太字**： / 表 / > / !画像: / !リード: / !要点:)はそのまま残してください。"
           "内容を勝手に増やさず、校正後の資料だけを書いてください。")
_ABOUT_CHAT = re.compile(r"今の|この(?:内容|会話|話|回答|返事)|さっき|上の|これまで|会話|回答|返事")


def doc_topic(request):
    """「〇〇についての提案資料をパワポで作って」→「〇〇についての提案資料」(調べる言葉)"""
    t = _OFFICE.split(request)[0] if _OFFICE.search(request) else request
    t = re.sub(r"(?:明朝|ゴシック|教科書|ポップ|丸ゴシック|UD)体?(?:の書体)?で[、\s]*", "", t)
    return re.sub(r"(?:を|の|で|に)$", "", t.strip(" 、,。（(")).strip()


def _status(text):
    if on_status:
        on_status(text)


def _doc_chat(messages, model, temperature, fmt=None):
    try:
        return _chat(messages, use_tools=False, model=model, temperature=temperature, fmt=fmt).get("content") or ""
    except requests.HTTPError as e:
        if model == config.OLLAMA_MODEL or "404" not in str(e):
            raise
        _start_pull(model)  # 資料づくり向けのモデルがまだ無い: 裏で準備し、今回はいつものモデルで
        return _chat(messages, use_tools=False, model=config.OLLAMA_MODEL, temperature=temperature,
                     fmt=fmt).get("content") or ""


# 資料の設計図(JSON の形)。題名・各ページの「伝えたいこと」・見せ方まで先に決めてから、ページを組み立てる
_STR = {"type": "string"}
_ITEM = {"type": "object", "properties": {"head": _STR, "text": _STR}, "required": ["head", "text"]}
_PLAN = {
    "pptx": {"type": "object", "required": ["title", "subtitle", "slides", "closing"], "properties": {
        "title": _STR, "subtitle": _STR,
        "slides": {"type": "array", "minItems": 4, "maxItems": 9, "items": {
            "type": "object", "required": ["layout", "title", "message", "items"], "properties": {
                "layout": {"type": "string", "enum": ["cards", "steps", "stats", "compare", "table", "points"]},
                "title": _STR, "message": _STR,
                "items": {"type": "array", "minItems": 2, "maxItems": 6, "items": _ITEM},
                "table": {"type": "array", "items": {"type": "array", "items": _STR}},
                "notes": _STR}}},
        "closing": {"type": "object", "required": ["title", "points"], "properties": {
            "title": _STR, "points": {"type": "array", "minItems": 2, "maxItems": 4, "items": _STR}}}}},
    "docx": {"type": "object", "required": ["title", "summary", "sections"], "properties": {
        "title": _STR, "summary": _STR,
        "key_points": {"type": "array", "maxItems": 4, "items": _STR},
        "sections": {"type": "array", "minItems": 3, "maxItems": 8, "items": {
            "type": "object", "required": ["heading", "paragraphs"], "properties": {
                "heading": _STR,
                "paragraphs": {"type": "array", "minItems": 1, "maxItems": 4, "items": _STR},
                "points": {"type": "array", "maxItems": 6, "items": _ITEM},
                "table": {"type": "array", "items": {"type": "array", "items": _STR}}}}}}},
}
_PLAN_GUIDE = {
    "pptx": ("JSON で PowerPoint の設計図を書いてください。"
             "title: 聞き手を引きつけ、中身が一言で分かる題名(25字以内。「〇〇について」「資料」「プレゼン」とだけ書くのは禁止)。"
             "subtitle: 誰に何を伝えるかが分かる副題(35字以内)。"
             "slides: 4〜8枚。流れは「背景・課題 → 中身(特徴・方法・事例・数字) → 次の一歩」のように、話の筋が通る順にする。"
             "各スライドの title は内容が分かる具体的な見出し(20字以内)、message はそのスライドで一番伝えたい結論を1文(45字以内)。"
             "items は 2〜4個(手順なら最大6個)。head は12字以内の要点、text はその説明を1〜2文(60字以内)。"
             "layout は中身に合わせて選ぶ: 特徴・理由・強みは cards、手順・流れ・歴史は steps、"
             "数字が主役なら stats(head に「30%」のような数字、text に説明)、2つ以上の比べ合いは compare(head に比べるものの名前)、"
             "細かい比較の一覧は table(table に1行目を見出しにした表)、それ以外は points。同じ layout を3枚続けない。"
             "notes は話す人向けの補足(任意)。closing はまとめのスライド(title とpoints 2〜4個の要点)。"),
    "docx": ("JSON で Word 文書の設計図を書いてください。"
             "title: 中身が一言で分かる題名(30字以内。「〇〇について」「資料」とだけ書くのは禁止)。"
             "summary: 文書全体の要旨を2〜3文。key_points: 読み手に覚えてほしい要点を3つ(各30字以内)。"
             "sections: 3〜7章。heading は内容が分かる具体的な見出し、paragraphs はていねいな段落(1段落 80〜200字)、"
             "points は箇条書きにしたい項目(head と text)、table は比べると分かりやすいときだけ(1行目が見出し)。"
             "最後の章は「まとめ」や「今後の進め方」にする。"),
}


def _plan_md(kind, plan):
    """設計図(JSON)→ いつもの書式つきの文(# / ## / - / 1. / 表 / >)。"""
    clean = lambda s: re.sub(r"\s+", " ", str(s or "")).strip()  # noqa: E731
    out = [f"# {clean(plan.get('title'))}", clean(plan.get("subtitle") or plan.get("summary")), ""]

    def table(rows):
        rows = [[clean(c).replace("|", "／") for c in r] for r in rows or [] if r]
        if len(rows) < 2:
            return []
        n = max(len(r) for r in rows)
        rows = [r + [""] * (n - len(r)) for r in rows]
        return ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * n] + ["| " + " | ".join(r) + " |" for r in rows[1:]]

    if kind == "pptx":
        for sl in plan.get("slides") or []:
            items = [i for i in sl.get("items") or [] if clean(i.get("head")) or clean(i.get("text"))]
            layout = sl.get("layout")
            out.append(f"## {clean(sl.get('title'))}")
            if clean(sl.get("message")):
                out.append(f"!リード: {clean(sl.get('message'))}")
            rows = table(sl.get("table")) if layout == "table" else []
            if rows:
                out += rows
            elif layout == "compare" and len(items) >= 2:
                for i in items:
                    out += [f"### {clean(i.get('head'))}"] + [f"- {p}" for p in re.split(r"[／/。]\s*", clean(i.get("text"))) if p]
            else:
                mark = (lambda n: f"{n}. ") if layout == "steps" else (lambda n: "- ")
                out += [f"{mark(n)}**{clean(i.get('head'))}**：{clean(i.get('text'))}"
                        if clean(i.get("head")) else f"{mark(n)}{clean(i.get('text'))}" for n, i in enumerate(items, 1)]
            if clean(sl.get("notes")):
                out.append(f"> {clean(sl.get('notes'))}")
            out.append("")
        close = plan.get("closing") or {}
        if close.get("points"):
            out.append(f"## まとめ：{clean(close.get('title'))}" if clean(close.get("title")) and
                       "まとめ" not in clean(close.get("title")) else f"## {clean(close.get('title')) or 'まとめ'}")
            out += [f"- {clean(p)}" for p in close["points"] if clean(p)]
    else:
        if plan.get("key_points"):
            out += [f"!要点: {clean(p)}" for p in plan["key_points"] if clean(p)] + [""]
        for sec in plan.get("sections") or []:
            out.append(f"## {clean(sec.get('heading'))}")
            out += [clean(p) for p in sec.get("paragraphs") or [] if clean(p)]
            out += [f"- **{clean(i.get('head'))}**：{clean(i.get('text'))}" for i in sec.get("points") or []
                    if clean(i.get("head"))]
            out += table(sec.get("table"))
            out.append("")
    return "\n".join(out).strip()


def _plan(kind, rule, request, model):
    """設計図を JSON で書かせて、書式つきの文にする。うまくいかなければ None(ふつうの書き方に戻す)。"""
    if kind not in _PLAN:
        return None
    messages = [{"role": "system", "content": rule + "\n\n" + _PLAN_GUIDE[kind]}, *_context(),
                {"role": "user", "content": request}]
    try:
        plan = json.loads(_doc_chat(messages, model, 0.5, fmt=_PLAN[kind]))
    except Exception:
        return None
    body = plan.get("slides") if kind == "pptx" else plan.get("sections")
    if not isinstance(body, list) or len(body) < 2:
        return None
    return _plan_md(kind, plan)


def write_document(kind, request, source=""):
    """Word・PowerPoint・Excel の中身を書く。事実が要る資料は先に調べ、その情報だけを根拠にして、最後に校正する。
    (調べたページは「## 出典」として最後に付ける)
    source: web(ネットで調べる) / attach(添付をもとに) / user(ユーザーが伝えた内容で) / chat(会話の内容で) / ""(自動)"""
    material, sources = "", []
    research = source == "web" or (not source and not _ABOUT_CHAT.search(request))
    if getattr(config, "OFFICE_RESEARCH", True) and research:
        _status("資料のために調べています…")
        try:
            import websearch
            results = websearch.search(doc_topic(request) or request, 6)
            pages = websearch.read_pages(results, count=3, limit=1500)
            material = "\n".join(f"・{r['title']}: {r['snippet']}" for r in results[:6])
            material += "\n\n" + "\n\n".join(f"[{r['title']}]\n{p}" for r, p in zip(results, pages) if p)
            sources = [f"{r['title']} {r['url']}" for r in results[:5]]
        except Exception:
            material = ""
    rule = ("あなたは資料作成のプロです。" + _DOC_GUIDE[kind] + _DOC_QUALITY.format(lang=answer_language())
            + (f"\n\n【調べた情報】\n{material[:6000]}" if material else
               "\n\n(調べた情報はありません。数字や事実は、これまでの会話にあるものだけを使ってください)"))
    messages = [{"role": "system", "content": rule}, *_context(), {"role": "user", "content": request}]
    # テクニカルモード用のAIは、テクニカルモードのときだけ使う(ふだんはいつものAIで書く)
    model = tech_model() if _tech else config.OLLAMA_MODEL
    _status("構成を考えています…")
    draft = _plan(kind, rule, request, model)
    planned = draft is not None
    if not planned:
        _status("資料の中身を書いています…")
        draft = _doc_chat(messages, model, 0.4)
    text = draft
    # 設計図から作ったときは形が整っているので、見直しで崩さない(見直しは自由に書いたときだけ)
    if getattr(config, "OFFICE_REVIEW", True) and draft.strip() and not planned:
        _status("誤字や重複がないか見直しています…")
        import officedoc
        checked = _doc_chat([{"role": "system", "content": _REVIEW}, {"role": "user", "content": draft}], model, 0.1)
        before, after = officedoc.parse(draft), officedoc.parse(checked)
        # 見直しで章が大きく減った(書き損じた)ときは、元の文を使う
        if len(after["sections"]) >= max(1, int(len(before["sections"]) * 0.8)):
            text = checked
    if sources:
        text += "\n\n## 出典\n" + "\n".join(f"- {s}" for s in sources)
    _status("ファイルを作っています…")
    return text


KEEP = "15m"  # 使い終わってからAIをメモリに置いておく時間(過ぎたら外す。チャットを開くと前もって読み込み直す)
_warmed = 0.0


def warm():
    """チャットを開いたときなどに、AIを裏で読み込んでおく(外していても、打ち終わるまでに準備ができる)。"""
    global _warmed
    import threading
    import time
    if time.monotonic() - _warmed < 120:
        return
    _warmed = time.monotonic()
    model = tech_model() if _tech else config.OLLAMA_MODEL

    def run():
        try:
            requests.post(config.OLLAMA_URL.replace("/api/chat", "/api/generate"),
                          json={"model": model, "keep_alive": KEEP, "options": ai_options(num_ctx=4096)}, timeout=120)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


_tech_note = ""  # テクニカルモードで、メモリが足りずにいつものAIで答えたときの知らせ(1回だけ出す)


def tech_model():
    """テクニカルモードで実際に使うモデル。
    「自動」なら搭載メモリに合うものを選び、いま空いているメモリで動かせないときは、いつものAIのまま答える
    (メモリが足りないモデルを読み込むと、PC全体が固まったように遅くなるため)。"""
    global _tech_note
    import models
    want = getattr(config, "TECH_MODEL", "") or ""
    total, free = models.memory_gb()
    if want == "auto":
        want = models.auto_tech(total) if total else ""
    if not want or want == config.OLLAMA_MODEL:
        return config.OLLAMA_MODEL
    if total:
        # いつものAIは入れ替わりで外れる(同時に読み込むのは1つだけ)ので、その分も空きに数える
        room = free + models.need_gb(config.OLLAMA_MODEL) * 0.8
        if room < models.need_gb(want):
            if not _tech_note:
                _tech_note = (f"（いま空いているメモリが少ないため、コード向けのAI「{want}」ではなく、いつものAIで答えます。"
                              "ほかのアプリを閉じると使えるようになります）")
            return config.OLLAMA_MODEL
    return want


def release_tech_model():
    """テクニカルモード用のAIを、メモリから外す(いつものAIはそのまま)。"""
    model = tech_model() if _tech else (getattr(config, "TECH_MODEL", "") or "")
    if model == "auto":
        import models
        model = models.auto_tech(models.memory_gb()[0])
    if not model or model == config.OLLAMA_MODEL:
        return
    import threading

    def run():
        try:
            requests.post(config.OLLAMA_URL.replace("/api/chat", "/api/generate"),
                          json={"model": model, "keep_alive": 0}, timeout=10)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def _start_pull(model):
    import threading
    import services
    threading.Thread(target=lambda: services.pull_model(lambda s: None, model), daemon=True).start()


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


def _chat(messages, use_tools=True, stream_out=False, guard=None, model=None, temperature=None, fmt=None):
    """Ollama に問い合わせる。返事は少しずつ受け取り、stream_out なら届いた分を on_delta へ渡す。
    関数呼び出し(JSON)らしい返事は画面に出さない。
    guard(ユーザーの質問)を渡すと、書き出しを少しだけ見てから流し、質問とかみ合わなければ OffTrack を出す。"""
    model = model or (tech_model() if _tech else config.OLLAMA_MODEL)
    temp = temperature if temperature is not None else 0.2 if _tech else 0
    body = {"model": model, "messages": messages, "stream": True,
            "options": ai_options(temperature=temp, num_ctx=num_ctx(messages)),
            # テクニカルモード用のAIは大きいので、使い終わって10分たったらメモリから外す
            "keep_alive": "10m" if model != config.OLLAMA_MODEL else KEEP}
    if use_tools:
        body["tools"] = tools.schemas(TECH_TOOLS if _tech else None)
    if fmt:
        body["format"] = fmt  # 決めた形(JSON)のとおりにだけ書かせる(小さなモデルでも形が崩れない)
    import models
    if models.thinks(model):
        body["think"] = False  # 考える過程を書かせない(書かせると、話し始めるまでが遅くなる)
    global _streamed
    content, calls, shown = "", [], 0
    _streamed = False
    with requests.post(config.OLLAMA_URL, json=body, timeout=config.OLLAMA_TIMEOUT, stream=True) as r:
        if getattr(r, "status_code", 200) == 400 and use_tools and "tools" in r.text:
            # 関数(PC操作)の呼び出しに対応していないモデル(OLMoE など): 関数なしで聞き直す
            return _chat(messages, False, stream_out, guard, model, temperature)
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
            if stream_out and on_delta and not calls and not content.lstrip().startswith(("{",) if _tech else ("{", "`")):
                ok = visible(content)
                if len(ok) > shown:
                    on_delta(ok[shown:])
                    shown = len(ok)
                    _streamed = True
    if guard is not None and not calls and off_track(guard, content):
        raise OffTrack(content[:40])
    if stream_out and on_delta and not calls and not content.lstrip().startswith(("{",) if _tech else ("{", "`")):
        ok = visible(content)
        if len(ok) > shown:
            on_delta(ok[shown:])  # 短い返事(待っている間に書き終わった分)
            _streamed = True
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


_TOOL_TEXT_TECH = re.compile(r"\[Tools?\]|<tool_call>|^\s*\{\s*\"(?:name|function)\"\s*:")  # コードの ``` は出してよい


def visible(content):
    """画面と読み上げに出してよい部分(関数の呼び出しらしい書き出しより前)。"""
    m = (_TOOL_TEXT_TECH if _tech else _TOOL_TEXT).search(content)
    return content[:m.start()].rstrip() if m else content


def attach(paths):
    """添付されたファイル・フォルダを読み取る(同じ添付なら読み直さない)。"""
    global _attached, _attach_key
    key = tuple(paths or ())
    if key != _attach_key:
        _attach_key = key
        if key:
            _status("添付されたファイルを読んでいます…")
            import attachments
            _attached = attachments.material(list(key))
        else:
            _attached = ""


def ask(text, history=None, summary="", memory=None, full=False, tid=None, base=0, mode="", attachments=None):
    """history を渡すとその会話の続きとして答える(チャットのスレッドごとの記憶)。
    summary: 古いやりとりの要約 / memory: ユーザーについてずっと覚えておくこと
    full: スレッドの会話をすべて参照する(長すぎれば古い部分を圧縮。tid・base はその保存用)"""
    global _last, _summary, _memory, _full, _tech, _current_text
    _current_text = text
    attach(attachments)
    _full = bool(full)
    was_tech, _tech = _tech, mode == "tech"
    if was_tech and not _tech:
        release_tech_model()  # テクニカルモードを抜けた: 大きなAIをすぐメモリから外す
    if _full and history is not None:
        history, summary = _fit(list(history), summary or "", tid, base)
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
    # 「明日の東京の天気は？」「今日の天気どう」「明日雨降る？」
    (re.compile(r"^(?P<q>.*?(?:天気|気温|降水確率|天気予報|雨降る|雨が降る|晴れる|傘(?:いる|が?要る)).*?)"
                r"(?:は|を|って|どう|どんな感じ)?(?:教えて|調べて|かな|ですか)?$"), "get_weather"),
    (re.compile(r"^(?P<q>.+?ニュース.*?)(?:を|について)?(?:いくつか|少し|ちょっと)?"
                r"(?:教えて|紹介して|しょうかいして|知りたい|調べて|見せて|まとめて)"), "search_summary"),
    (re.compile(r"^(?P<q>.+?)(?:について|を|って)?(?:調べて|しらべて|検索して|教えて|紹介して|しょうかいして)"),
     "search_summary"),
]
# 開いているWebページの中の操作(ゼラス用ブラウザが手前にあるときだけ)
_TYPE = r"(?:と|って)(?:入力|にゅうりょく|打って|うって|入れて|いれて|書いて|かいて)(?:して)?"
_GO = r"(?P<go>[、,\s]*(?:て|して)?[、,\s]*(?:検索|決定|送信|エンター|enter)(?:して|を押して)?)?(?:ください)?"
_PAGE_ROUTES = [
    (re.compile(r"^(?P<f>.+?)(?:の欄|欄|ボックス|のところ)?(?:に|へ)(?P<q>.+?)" + _TYPE + _GO + "$", re.I), "type_in"),
    (re.compile(r"^(?P<q>.+?)" + _TYPE + _GO + "$", re.I), "type"),
    (re.compile(r"^(?:ページを?|前のページに?|ひとつ前のページに?|1つ前のページに?)(?:戻って|もどって|戻る)(?:ください)?$"), "back"),
    (re.compile(r"^(?:次のページに?|ページを?)(?:進んで|すすんで|進む)(?:ください)?$"), "forward"),
    (re.compile(r"^(?:ページを?|画面を?)?(?:更新|再読み込み|リロード|読み込み直)(?:して|し)?(?:ください)?$"), "reload"),
    (re.compile(r"^(?:ページの)?(?:一番|いちばん)(?P<q>上|下)(?:まで|に|へ)?(?:戻って|行って|いって|移動して|スクロールして)?(?:ください)?$"), "edge"),
    (re.compile(r"^(?:この|今の|いまの)(?:ページ|記事|サイト)(?P<q>.*)$"), "read"),
    (re.compile(r"^(?:次の(?:動画|曲)|次へ)(?:に|へ)?(?:して|行って|いって|流して|飛ばして|スキップして)?$"), "video:next"),
    (re.compile(r"^(?:動画|曲|音楽|再生)?を?(?:止めて|とめて|一時停止(?:して)?|ストップ(?:して)?|ポーズ(?:して)?)$"), "video:pause"),
    (re.compile(r"^(?:動画|曲|音楽)?を?(?:再生して|再開して|続きを?(?:流して|再生して))$"), "video:play"),
    (re.compile(r"^(?:動画を?)?(?:全画面|フルスクリーン)(?:にして|で(?:見せて|再生して)|表示(?:して)?)?$"), "video:fullscreen"),
    (re.compile(r"^(?:全画面|フルスクリーン)を?(?:やめて|解除して|戻して|終わって)$"), "video:exit_fullscreen"),
    (re.compile(r"^(?:動画を?)?(?P<n>\d+)秒(?:進めて|すすめて|飛ばして|とばして|早送りして|先へ)$"), "video:forward"),
    (re.compile(r"^(?:動画を?)?(?P<n>\d+)秒(?:戻して|もどして|巻き戻して|前へ)$"), "video:rewind"),
    (re.compile(r"^(?:動画を?|音を?)?(?:ミュート|消音)(?:にして|して)?$"), "video:mute"),
    (re.compile(r"^(?:ミュートを?(?:解除|やめ)て|音を出して)$"), "video:unmute"),
    (re.compile(r"^(?P<q>.+?)(?:を|って)?(?:クリック|くりっく|タップ)(?:して)?(?:ください)?$"), "click"),
    (re.compile(r"^(?P<q>.+?)(?:の(?:ボタン|リンク))?を?(?:押して|おして)(?:ください)?$"), "click"),
]


def page_route(t):
    """開いているWebページの中の操作なら (関数名, 引数)。ゼラス用ブラウザが手前に無ければ None。"""
    for pattern, kind in _PAGE_ROUTES:
        m = pattern.match(t)
        if not m:
            continue
        import browser
        try:
            if not (browser.enabled() and browser.active()):
                return None
        except Exception:
            return None
        g = m.groupdict()
        q = (g.get("q") or "").strip(" 、,「」『』\"'")
        if kind in ("type", "type_in"):
            if not q:
                return None
            args = {"text": q, "submit": bool(g.get("go"))}
            if kind == "type_in":
                args["field"] = g["f"].strip(" 、,「」")
            return "web_type", args
        if kind in ("back", "forward", "reload"):
            return "web_page", {"action": kind}
        if kind == "edge":
            return "web_page", {"action": "top" if q == "上" else "bottom"}
        if kind == "read":
            if not re.search(r"要約|まとめ|何|なに|内容|教えて|結論|ポイント|書いて|読んで|説明|[？?]", q):
                return None
            return "web_read", {"question": t if re.search(r"[？?]|何|なに|どう|いつ|誰|どこ|教えて|結論|ポイント", q) else ""}
        if kind.startswith("video:"):
            args = {"action": kind[6:]}
            if g.get("n"):
                args["seconds"] = int(g["n"])
            return "web_video", args
        if kind == "click" and q and len(q) <= 40:
            key = re.sub(r"キー$", "", q).strip().lower()
            import browser as b
            if b.KEY_ALIAS.get(key, key) in b._KEYS or "+" in key or "＋" in key:  # 「エンターを押して」はキー
                return "web_key", {"keys": key}
            return "web_click", {"target": q}
    return None


_NOT_SEARCH = re.compile(r"ブラウザ|あなた|きみ|君|お前|自分|さっき|それ|これ|あれ")  # 会話の続き・ブラウザ指定は AI に任せる


# メール: 「(メールアプリを開いて)迷惑メールフォルダのメールを全部既読にして」など
_MAIL_PREFIX = r"(?:(?:メール|めーる)(?:の)?(?:アプリ|ソフト)?(?:を)?(?:開いて|ひらいて|起動して)?[、,\s]*)?"
_MAIL_ROUTES = [
    (re.compile(r"^" + _MAIL_PREFIX + r"(?P<f>.+?)(?:フォルダー?|ボックス)?(?:の|にある|に入っている|内の)?(?:中の)?"
                r"(?:未読の?)?(?:メール)?(?:を)?(?:全部|ぜんぶ|すべて|全て|まとめて)?(?:を)?既読(?:に)?(?:して|する|にする)?"
                r"(?:ください|おいて|といて)?$"), "read"),
    (re.compile(r"^" + _MAIL_PREFIX + r"(?:メールの)?(?P<f>.+?)(?:フォルダー?|ボックス)?の?(?:名前|なまえ|名称)を?[、\s]*"
                r"[「『]?(?P<n>.+?)[」』]?(?:に|へ)(?:変えて|変更して|かえて|リネームして)(?:ください)?$"), "rename_maybe"),
    (re.compile(r"^" + _MAIL_PREFIX + r"(?P<f>.*?)(?:フォルダー?|ボックス)?(?:の|に)?未読(?:メール)?(?:は|が)?"
                r"(?:何通|なんつう|いくつ|何件|ある|どれくらい)"), "unread"),
]
# ファイルの中身: 「デスクトップにあるメモ帳のファイルから、旅行についての記載があるものを開いて」
_CONTENT = re.compile(
    r"^(?:(?P<where>デスクトップ|ドキュメント|ダウンロード|ピクチャ)(?:に(?:ある)?|の)?)?[、\s]*"
    r"(?:(?P<kind>メモ帳|テキスト|ワード|エクセル|パワーポイント|パワポ)の?)?(?:ファイル)?(?:の?中)?(?:から|で)?[、,\s]*"
    r"(?P<q>.+?)(?:(?:について|に関して|に関する)(?:の)?(?:記載|記述|内容|こと|話|事)?|の(?:記載|記述|内容|こと|話|事))(?:が|を)?"
    r"(?:ある|あるもの|書いてある|書かれた|書かれている|含む|載っている)?(?:もの|ファイル|やつ|の)?(?:を|は)?[、\s]*"
    r"(?P<act>開いて|ひらいて|探して|さがして|見つけて|教えて|どれ)")


# 「会議の内容が書いてあるワードのファイルを開いて」(書いてあること → 種類 → 操作 の順)
_CONTENT2 = re.compile(
    r"^(?:(?P<where>デスクトップ|ドキュメント|ダウンロード|ピクチャ)(?:に(?:ある)?|の)?(?:中の)?)?[、\s]*"
    r"(?P<q>.+?)(?:について|に関して|の(?:記載|記述|内容|こと|話|事))?(?:が|の)?"
    r"(?:書いてある|書かれた|書かれている|載っている|含まれる|入っている)"
    r"(?:(?P<kind>メモ帳|テキスト|ワード|エクセル|パワーポイント|パワポ)の?)?(?:ファイル|もの|やつ)を?[、\s]*"
    r"(?P<act>開いて|ひらいて|探して|さがして|見つけて|教えて)")


def content_route(t):
    m = _CONTENT.match(t) or _CONTENT2.match(t)
    if not m or not m.group("q").strip(" 、,「」"):
        return None
    args = {"text": m.group("q").strip(" 、,「」『』"), "open": m.group("act") in ("開いて", "ひらいて")}
    if m.group("where"):
        args["path"] = m.group("where")
    if m.group("kind"):
        args["kind"] = m.group("kind")
    return "find_in_files", args


# 「〇〇についてのプレゼン資料をパワポで作って」「今の内容をWordにして」「売上表をExcelで作って」
_OFFICE = re.compile(
    r"(?P<kind>パワポ|パワーポイント|powerpoint|pptx|スライド|プレゼン(?:資料)?|ワード|word|docx|エクセル|excel|xlsx|pdf|ＰＤＦ)"
    r"(?:の?ファイル|形式|資料)?(?:で|に|として|へ)?[、\s]*(?:(?:資料|文書|書類|表|ファイル|スライド)を?[、\s]*)?"
    r"(?:作って|作成して|まとめて|出力して|保存して|書き出して|して|にして|"
    r"作ってください|ください)", re.I)
OFFICE_KINDS = {"パワポ": "pptx", "パワーポイント": "pptx", "powerpoint": "pptx", "pptx": "pptx", "スライド": "pptx",
                "プレゼン": "pptx", "プレゼン資料": "pptx", "ワード": "docx", "word": "docx", "docx": "docx",
                "エクセル": "xlsx", "excel": "xlsx", "xlsx": "xlsx", "pdf": "pdf", "ｐｄｆ": "pdf"}
# 「報告書.docx をPDFにして」: いまあるファイルを PDF にする
_TO_PDF = re.compile(r"^(?P<q>.+?\.(?:docx|pptx|xlsx))\s*を?\s*(?:pdf|ＰＤＦ)(?:に|へ)(?:変換して|して|保存して)", re.I)


def office_route(t):
    m = _TO_PDF.match(t)
    if m:
        return "convert_to_pdf", {"name": m.group("q").strip(" 、「」")}
    m = _OFFICE.search(t)
    if not m:
        if _GENERIC_DOC.search(t):  # 「資料つくって」: 形式は聞き取りで決める
            return "make_office_file", {"kind": "", "request": t}
        return None
    return "make_office_file", {"kind": OFFICE_KINDS[m.group("kind").lower()], "request": t}


def mail_route(t):
    for pattern, kind in _MAIL_ROUTES:
        m = pattern.match(t)
        if not m:
            continue
        f = (m.groupdict().get("f") or "").strip(" 、,「」").removesuffix("の")
        if kind == "read" and f:
            return "mail_mark_read", {"folder": f}
        if kind == "unread":
            return "mail_unread", {"folder": f}
        if kind == "rename_maybe" and ("メール" in t or re.search(r"迷惑|受信|送信|下書き|ゴミ箱|アーカイブ", f)):
            return "mail_rename_folder", {"folder": f, "new_name": m.group("n").strip()}
    return None


_OPEN_APP = re.compile(r"^(?P<q>[^、。,\s]{1,30}?)(?:を)?(?:開いて|ひらいて|起動して|立ち上げて|つけて)(?:ください)?$")
_NOT_APP = re.compile(r"ファイル|フォルダ|サイト|ページ|ブラウザ|\.|それ|これ|あれ|デスクトップ|ドキュメント|ダウンロード|ピクチャ")

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


_FILLER = re.compile(r"^(?:じゃあ|では|なら|じゃ|それじゃ|だから|もう一回|もう一度)?[、\s]*(?:それ|これ|そのこと|その件)?"
                     r"[、\s]*(?:ネットで|ネット|ウェブで|インターネットで|グーグルで|googleで|検索で)?[、\s]*$", re.I)


def _topic(q):
    """調べる言葉から「ネットで」「じゃあ」などを除く。何も残らなければ ""。"""
    q = (q or "").strip(" 、,をのは")
    return "" if _FILLER.fullmatch(q) else re.sub(r"^(?:ネットで|ウェブで|インターネットで|グーグルで)[、\s]*", "", q, flags=re.I)


def _prev_topic():
    """直前の質問から、調べる言葉を取り出す(「〜を教えて」などは除く)。"""
    if not _history:
        return ""
    prev = _history[-1][0].strip().rstrip("。.!！?？")
    for pattern, name in _ROUTES:
        m = pattern.match(prev)
        if m and name == "search_summary" and _topic(m.group("q")):
            return _topic(m.group("q"))[:80]
    return prev[:80]


def quick_route(text):
    """(関数名, 引数) を返す。当てはまらなければ None。"""
    t = text.strip().rstrip("。.!！?？")
    if not config.QUICK_ROUTE:
        return None
    follow = follow_up(t)
    if follow:
        return follow
    # 「じゃあそれ調べて」「ネットで調べてよ」: 直前の質問を調べる
    if re.fullmatch(r"(?:じゃあ|では|なら|じゃ|それじゃ|だから)?[、\s]*(?:それ|これ|そのこと|その件)?(?:を|について)?[、\s]*"
                    r"(?:ネットで|ウェブで|インターネットで|グーグルで|googleで|検索で)?[、\s]*"
                    r"(?:調べて|しらべて|検索して|調べてみて|調べてきて|ググって)(?:ください|よ|ね|くれる|みて)?", t, re.I):
        import weather
        if _history and weather.is_weather(_history[-1][0]):  # 直前が天気の質問なら、天気予報で答える
            return quick_route(_history[-1][0])
        q = _prev_topic()
        if q:
            return "search_summary", {"query": q}
    page = page_route(t)
    if page:
        return page
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
    for route in (office_route(t), mail_route(t), content_route(t)):
        if route:
            return route
    m = _OPEN_APP.match(t)  # 「サンダーバード開いて」: このPCのアプリの名前なら、そのアプリを起動する
    if m and not _NOT_APP.search(m.group("q")):
        import apps
        if apps.is_app(m.group("q")):
            return "launch_app", {"name": m.group("q")}
    if _NOT_SEARCH.search(t):
        return None
    for pattern, name in _ROUTES:
        m = pattern.match(t)
        if m and name == "get_weather":
            import weather
            place, day = weather.parse(m.group("q"))
            other = re.sub(r"(?:今日|明日|明後日|あさって|あした|きょう|の|は|天気|予報|気温|降水確率|雨|降る|晴れる|傘|いる|要る|が|って|どう|\s)",
                           "", m.group("q"))
            if place is None and other:  # 表にない地名(例: 軽井沢): 天気予報の関数に、その地名で調べてもらう
                return name, {"place": other, "day": ["今日", "明日", "明後日"][day]}
            return name, {"place": place or "", "day": ["今日", "明日", "明後日"][day]}
        if m and name == "search_summary":
            q = _topic(m.group("q"))
            if not q:  # 「ネットで調べてよ」「じゃあ検索して」: 何を調べるかは直前の質問から
                q = _prev_topic()
                if not q:
                    continue
            return name, {"query": q}
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
    r"切り替え|最小化|最大化|ウィンドウ|閉じて|動画|再生|流して|サイト|youtube|ユーチューブ|アマゾン|amazon|"
    r"戻って|進んで|更新して|要約|このページ|この記事|止めて|一時停止|全画面|タブ|選んで|ログイン|入れて|書いて|"
    r"メール|既読|未読|記載|書いてある|名前を変|パワポ|パワーポイント|スライド|プレゼン|ワード|word|エクセル|excel")


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


_NUMS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6}


def _pick(text, choice):
    """候補を聞いたあとの返事から、選ばれた番号(0から)。やめるなら "cancel"、関係ない話なら None。"""
    import unicodedata
    t = unicodedata.normalize("NFKC", text).strip().rstrip("。.!！?？").lower()
    n = len(choice["options"])
    if re.fullmatch(r"(?:やっぱり)?(?:やめて|やめる|キャンセル|いいえ|いらない|どれでもない|なし)(?:ておく|とく)?", t):
        return "cancel"
    m = re.fullmatch(r"(?:じゃあ|では)?[、\s]*(?:(\d)|([一二三四五六]))\s*(?:番目?|つ目|個目|こめ|の方|のほう)?(?:で|を|に)?"
                     r"(?:お願い|おねがい|開いて|押して|して|ください)?", t)
    if m:
        k = int(m.group(1)) if m.group(1) else _NUMS[m.group(2)]
        return k - 1 if 1 <= k <= n else None
    if re.fullmatch(r"(?:最初|いちばん上|一番上|上)の?(?:方|ほう|やつ)?(?:で|を)?(?:お願い|開いて|押して)?", t):
        return 0
    if re.fullmatch(r"(?:最後|いちばん下|一番下|下)の?(?:方|ほう|やつ)?(?:で|を)?(?:お願い|開いて|押して)?", t):
        return n - 1
    core = re.sub(r"(?:の方|のほう|のやつ)?(?:で|を)?(?:お願い|おねがい|開いて|押して|ください)?$", "", t).strip()
    if len(core) >= 2:
        hits = [i for i, label in enumerate(choice["labels"])
                if core in unicodedata.normalize("NFKC", str(label)).lower()]
        if len(hits) == 1:
            return hits[0]
    return None


# ---------------- 資料づくりの前の聞き取り(形式・内容・材料・デザイン) ----------------
KIND_NAMES = {"pptx": "PowerPoint の資料", "docx": "Word の文書", "xlsx": "Excel の表", "pdf": "PDF の資料"}
_SKIP = re.compile(r"おまかせ|お任せ|任せ|omakase|makase|(?i:^(?:none|no|nothing|any)$)|特に(?:ない|なし|無い)|^なし|^ない|いらない|大丈夫|そのまま|どれでも|^特には")
_CANCEL = re.compile(r"^(?:やっぱり)?[、\s]*(?:やめ|キャンセル|中止|作らなくて|いいや|やっぱいい)")
_NUM = {"1": 1, "一": 1, "いち": 1, "2": 2, "二": 2, "に": 2, "3": 3, "三": 3, "さん": 3}
_PLAIN_TOPIC = re.compile(r"^(?:資料|文書|書類|表|ファイル|スライド|プレゼン(?:資料)?|報告書|企画書|提案書|何か|なにか|"
                          r"これ|それ|まとめ)?$")
_PICK = re.compile(r"^(?:じゃあ|では)?[、\s]*(1|2|3|一|二|三|いち|に|さん)(?:番|つ目|ばん|で|、|。|\s|$)")
# 形式を言わない「資料つくって」「プレゼン資料を作成して」
_GENERIC_DOC = re.compile(r"(?:資料|プレゼン(?:資料)?|スライド|報告書|企画書|提案書|書類|ドキュメント|まとめ)を?[、\s]*"
                          r"(?:つくって|作って|作成して|用意して|まとめて|ちょうだい|ください)")
_KIND_WORD = re.compile(r"パワポ|パワーポイント|powerpoint|pptx|スライド|プレゼン|ワード|word|docx|エクセル|excel|xlsx|pdf",
                        re.I)
_WEB_WORD = re.compile(r"インターネット|ネット|ウェブ|web|検索|調べ", re.I)
_ATTACH_WORD = re.compile(r"添付|アップロード|送った|渡した")
# 内容(題名)を取り出すときに除く言葉
_NOT_TOPIC = re.compile(
    r"(?:インターネット|ネット|ウェブ|web)(?:で|から)(?:調べて)?|調べて|検索して|添付(?:した)?(?:ファイル|もの)?(?:で|から|をもとに)?|"
    r"(?:パワポ|パワーポイント|powerpoint|pptx|スライド|プレゼン(?:資料)?|ワード|word|docx|エクセル|excel|xlsx|pdf)"
    r"(?:の?ファイル|形式|資料)?(?:で|に|として|へ)?|"
    r"(?:の|を)?(?:資料|文書|書類|表)?(?:を)?(?:つくって|作って|作成して|まとめて|用意して|にして|して)(?:ください|ほしい)?$|"
    r"(?:について|に関して|に関する)(?:の)?(?:資料|内容)?|(?:を)?まとめ(?:て|た|る)?(?=\s|$|パ|ワ|エ|p|w|e|P|W|E)|"
    r"(?:お願い|おねがい)(?:します)?$", re.I)


def office_topic(text):
    """頼まれた文から、資料の内容(題名)だけを取り出す。何も残らなければ ""。"""
    t = _NOT_TOPIC.sub(" ", text or "")
    t = re.sub(r"[、。,\s]+", " ", t).strip(" をのでにはがと")
    return "" if _PLAIN_TOPIC.match(_key(t)) else t


def _kind_of(text):
    m = _KIND_WORD.search(text or "")
    if not m:
        return None
    w = m.group(0).lower()
    return OFFICE_KINDS.get(w) or ("pptx" if w in ("スライド", "プレゼン") else None)


def _absorb(st, text):
    """答えの中に、形式・材料・内容が含まれていれば取り込む(順番どおりでなくてもよい)。"""
    kind = _kind_of(text)
    if kind:
        st["kind"] = kind
    if not st["source"]:
        if _WEB_WORD.search(text):
            st["source"] = "web"
        elif _ATTACH_WORD.search(text):
            st["source"] = "attach"
    topic = office_topic(text)
    if topic and (not st["topic"] or re.search(r"について|に関して|に関する|の資料|まとめ", text)):
        st["topic"] = topic


def start_office(kind, request, args=None):
    """資料を作る前に、形式・内容・材料(ネット/添付/自分で伝える)・デザインを聞く。最初の質問を返す。"""
    global _office
    _office = st = {"kind": kind if kind in KIND_NAMES else None, "topic": "", "source": "", "content": "",
                    "design": "", "args": dict(args or {}), "request": request}
    if _ABOUT_CHAT.search(request):
        st["source"] = "chat"  # 「今の内容を Word に」: 材料は会話の内容
    _absorb(st, request)
    if st["source"] == "chat" and not st["topic"]:
        st["topic"] = "これまでの会話の内容"
    return _next_question()


def _key(s):
    return re.sub(r"[\s、。・「」]", "", s or "")


def _next_question(lead=""):
    st = _office
    if not st["kind"] and not st["topic"]:
        st["step"] = "kind_topic"
        return (f"{lead}資料を作ります。どんな内容を、どの形式で作りますか？\n"
                "形式: PowerPoint（発表用のスライド）／Word（報告書などの文書）／Excel（表・データ）\n"
                "例:「株式会社〇〇の紹介をパワポで」「月別の売上表をエクセルで」")
    if not st["kind"]:
        st["step"] = "kind"
        return (f"{lead}「{st['topic']}」の資料を、どの形式で作りますか？\n1. PowerPoint（発表・説明用のスライド）\n"
                "2. Word（報告書などの文書）\n3. Excel（表・データ）\n番号か言葉で答えてください。")
    if not st["topic"]:
        st["step"] = "topic"
        return f"{lead}{KIND_NAMES[st['kind']]}を作ります。どんな内容にしますか？（テーマ・目的・誰に見せるか など）"
    if not st["source"]:
        st["step"] = "source"
        have = f"（いま添付: {len(_attach_key)}件）" if _attach_key else "（＋ボタンかドラッグ＆ドロップで添付）"
        return (f"{lead}「{st['topic']}」の{KIND_NAMES[st['kind']]}を作ります。中身はどうしますか？\n"
                f"1. インターネットで調べて作る\n2. 添付したファイル・フォルダをもとに作る{have}\n"
                "3. 入れたい内容を自分で伝える\n番号か言葉で答えてください。")
    if st["source"] == "user" and not st["content"]:
        st["step"] = "content"
        return f"{lead}入れたい内容を教えてください。箇条書きでも、話し言葉でも大丈夫です。"
    if st["source"] == "attach" and not _attach_key:
        st["step"] = "attach"
        return (f"{lead}チャットの「＋」ボタンかドラッグ＆ドロップで、ファイルやフォルダを添付してから、"
                "「添付した」と答えてください。")
    if not st.get("asked_design"):
        st["step"], st["asked_design"] = "design", True
        return (f"{lead}「{st['topic']}」の{KIND_NAMES[st['kind']]}のデザインの希望はありますか？"
                "（例: 青系・明朝体・10枚くらい・シンプル／ポップ）なければ「おまかせ」と答えてください。")
    return None


def continue_office(text):
    """聞き取りの答えを受け取り、次の質問か、そろったら資料づくりへ。"""
    global _office, _office_ready
    import unicodedata
    text = unicodedata.normalize("NFKC", text)  # 全角の「１」や「ｏｍａｋａｓｅ」も、ふつうの字として読む
    st, t = _office, text.strip().rstrip("。.!！?？")
    if _CANCEL.match(t):
        _office = None
        return "わかりました。資料づくりはやめておきます。"
    step = st["step"]
    m = _PICK.match(t)
    if step == "design":
        st["design"] = "" if _SKIP.search(t) else text.strip()
    elif step == "content":
        st["content"] = text.strip()
    elif step == "kind" and m:
        st["kind"] = {1: "pptx", 2: "docx", 3: "xlsx"}[_NUM[m.group(1)]]
    elif step == "source" and m:
        st["source"] = {1: "web", 2: "attach", 3: "user"}[_NUM[m.group(1)]]
        rest = t[m.end():].strip(" 、。")
        if st["source"] == "user" and len(rest) > 10:  # 「3、〜と〜を入れて」: その場で内容も言った
            st["content"] = rest
    else:
        before = (st["kind"], st["topic"], st["source"])
        _absorb(st, t)
        if step in ("topic", "kind_topic") and not st["topic"]:
            st["topic"] = office_topic(t) or (t if not _kind_of(t) else "")
        if step == "source" and not st["source"] and re.search(r"自分|伝える|言う|話す|考え", t):
            st["source"] = "user"
        if step == "attach" and not _attach_key:
            return "まだ添付が見つかりません。「＋」ボタンかドラッグ＆ドロップで添付してから、もう一度答えてください。"
        if (st["kind"], st["topic"], st["source"]) == before and step in ("kind", "source", "kind_topic"):
            return _next_question("すみません、うまく聞き取れませんでした。")
    question = _next_question()
    if question:
        return question
    _office = None
    args = dict(st["args"], kind=st["kind"], source=st["source"], design=st["design"],
                request=f"{st['topic']}の{KIND_NAMES[st['kind']]}を作る"
                + (f"\n【入れる内容】{st['content']}" if st["content"] else "")
                + (f"\n【デザインの希望】{st['design']}" if st["design"] else ""))
    _office_ready = True
    try:
        return tools.run_tool("make_office_file", args)
    finally:
        _office_ready = False


def _run(name, args):
    if name == "make_office_file" and not _office_ready:
        # 資料づくりは、作る前に必ず形式・内容・材料・デザインを聞く。AIが考えた依頼文ではなく、ユーザーの言葉で始める
        kind = OFFICE_KINDS.get(str(args.get("kind", "")).lower().lstrip("."), str(args.get("kind", "")).lower())
        return start_office(kind, _current_text or str(args.get("request") or ""),
                            {k: v for k, v in args.items() if k in ("name", "path", "font")})
    if name == "scroll":  # ゼラス用ブラウザが手前なら、ページの中を直接スクロールする(画面の操作の許可は要らない)
        import browser
        try:
            if browser.enabled() and browser.active():
                name = "web_scroll"
        except Exception:
            pass
    global _choice
    res = tools.run_tool(name, args)
    if tools.CHOICE in res:  # 当てはまるものが複数: 次の発言で選んでもらう
        res, _, data = res.partition(tools.CHOICE)
        _choice = json.loads(data)
        return res
    if name in ("scroll", "web_scroll") and "スクロールしました" in res:  # 「もっと下に」などのために覚えておく
        down = not (str(args.get("direction", "")).lower().startswith("u") or "上" in str(args.get("direction", "")))
        _last_scroll.update(direction="down" if down else "up", amount=int(args.get("amount") or 5))
    return res


def _ask_tech(text):
    """テクニカルモード: 技術的な質問に、コードや手順を添えてくわしく答える(関数はファイルを読む・調べるなどだけ)。"""
    route = office_route(text.strip())
    if route:  # 「Wordにまとめて」などは、すぐに資料を作る
        return _run(*route)
    messages = [{"role": "system", "content": tech_prompt()}, *_context(), {"role": "user", "content": text}]
    global _tech_note
    tech_model()  # メモリが足りるか、ここで確かめる
    if _tech_note not in ("", "shown") and on_delta:  # メモリが足りずに、いつものAIで答えることを一度だけ伝える
        on_delta(_tech_note + "\n\n")
        _tech_note = "shown"
    for step in range(max(2, config.MAX_TOOL_STEPS)):
        try:
            msg = _chat(messages, use_tools=True, stream_out=True)
        except requests.HTTPError as e:
            model = tech_model()
            if not (model and model != config.OLLAMA_MODEL and "404" in str(e)):
                raise
            # コード向けのモデルがまだ無い: 裏でダウンロードを始め、今回はいつものモデルで答える
            import threading
            import services
            threading.Thread(target=lambda: services.pull_model(lambda s: None, model), daemon=True).start()
            config.TECH_MODEL = ""
            if on_delta:
                on_delta(f"（コード向けのAI「{model}」を準備し始めました。準備ができるまでは、いつものAIで答えます）\n\n")
            msg = _chat(messages, use_tools=True, stream_out=True)
        calls = [(n, a) for n, a in parse_tool_calls(msg) if n in TECH_TOOLS]
        if not calls:
            return visible(msg.get("content") or "").strip() or "うまく答えをまとめられませんでした。もう少し詳しく教えてください。"
        if _streamed and on_retract:
            on_retract()
        messages.append(msg)
        for name, args in calls:
            res = _run(name, args)
            if tools.CONFIRM in res or _choice or _office:
                return res
            messages.append({"role": "tool", "content": res.partition(SOURCES)[0][:16000]})
    return (_chat(messages, use_tools=False, stream_out=True).get("content") or "").strip()


def _ask(text):
    global _choice
    if _office:  # 資料づくりの前の聞き取りへの答え
        return continue_office(text)
    if _choice:  # 「どれにしますか？」への答え
        choice, _choice = _choice, None
        k = _pick(text, choice)
        if k == "cancel":
            return "わかりました。やめておきます。"
        if k is not None:
            args = dict(choice["args"], **{choice["arg"]: choice["options"][k]})
            return _run(choice["tool"], args)
    if _tech:
        return _ask_tech(text)
    if _attached:  # 添付があるとき: 資料づくり以外は、添付の内容をもとに答える(サイトを開くなどの決まった操作はしない)
        route = office_route(text.strip())
        if route:
            return _run(*route)
        messages = [{"role": "system", "content": system_prompt()}, *_context(), {"role": "user", "content": text}]
        return (_chat_on_track(messages, text).get("content") or "").strip() or \
            "うまく答えをまとめられませんでした。もう少し詳しく聞いてもらえますか？"
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
        if calls and _streamed and on_retract:
            on_retract()  # 「〇〇を開きます」と書き始めてから操作した: 書いた分は取り消し、操作の結果だけを伝える
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
            if tools.CONFIRM in res or _choice or _office:  # 確認・選択・聞き取りが要る操作: 実行せずに聞き返す
                return res
            results.append(res)
            messages.append({"role": "tool", "content": res})
        if not config.SUMMARIZE_AFTER_TOOL:
            return " ".join(results)
    return _chat(messages, use_tools=False, stream_out=True).get("content", "").strip() or " ".join(results)
