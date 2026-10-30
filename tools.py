"""AIが呼び出せるPC操作関数(Tool Call)。重いライブラリは関数内で読み込む。"""
import os
import re
import time
import subprocess
import urllib.parse
import urllib.request
import webbrowser

import config

TOOLS = {}  # name -> (func, schema)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def tool(description, **params):
    """params: 引数名=(型, 説明, 必須か)"""
    def deco(func):
        TOOLS[func.__name__] = (func, {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {k: {"type": t, "description": d} for k, (t, d, _) in params.items()},
                    "required": [k for k, (_, _, r) in params.items() if r],
                },
            },
        })
        return func
    return deco


SCREEN_TOOLS = set()  # 画面を直接操作する関数(設定で許可したときだけ AI に見せる)
WEB_TOOLS = set()     # ゼラス用ブラウザのページの中を操作する関数(ブラウザを開いている間だけ AI に見せる)


def schemas(only=None):
    if only is not None:  # テクニカルモードなど: 決まった関数だけ
        return [s for name, (_, s) in TOOLS.items() if name in only]
    hide = set() if getattr(config, "SCREEN_CONTROL_ENABLED", False) else set(SCREEN_TOOLS)
    import browser
    if not (browser.enabled() and browser.running()):
        hide |= WEB_TOOLS
    return [s for name, (_, s) in TOOLS.items() if name not in hide]


# 取り返しがつきにくい操作。声で頼まれたときは、実行する前に「はい/いいえ」で確かめる
# (近くの人の声や、テレビ・動画の音声で勝手に実行されないように)
DANGEROUS = {
    "delete_item": "「{name}」をごみ箱へ移動",
    "move_item": "「{name}」を「{dest}」へ移動",
    "rename_item": "「{name}」の名前を「{new_name}」に変更",
    "shutdown_pc": "PCをシャットダウン",
    "click_on": "「{label}」をクリック",
    "press_keys": "「{keys}」キーを押",
    "window_action": "「{name}」のウィンドウを終了",
    "web_click": "ページの「{target}」を押",
}
REQUIRE_CONFIRM = False  # いまの依頼が声によるものか(作業プロセスが依頼ごとに設定する)
CONFIRM = "\n\n確認:\n"  # 返事のうち、これより後ろは「確認待ちの操作」(画面用。読み上げない)


CHOICE = "\n\n選択:\n"
FILES = "\n\nファイル:\n"  # 返事のうち、これより後ろは作ったファイルの一覧(JSON)。チャットに「開く・保存」の札を出す  # 返事のうち、これより後ろは「どれにするか選んでもらう」候補(画面用。読み上げない)


def ask_choice(question, tool_name, arg, options, labels=None, args=None):
    """操作する相手の候補が複数あるとき、どれにするかを聞く返事。次の発言(番号か名前)で選ばれたものを実行する。"""
    import json
    labels = labels or options
    lines = "\n".join(f"{i}. {label}" for i, label in enumerate(labels, 1))
    return (f"{question}\n{lines}\n番号か名前で教えてください。" + CHOICE
            + json.dumps({"tool": tool_name, "arg": arg, "options": options, "labels": labels, "args": args or {}},
                         ensure_ascii=False))


# 声で名前を付ける操作: 聞き取った名前の書き方(漢字・カタカナ・英語など)を選んでもらう
SPELL_ARGS = {"create_folder": "name", "create_text_file": "name", "rename_item": "new_name",
              "mail_rename_folder": "new_name"}
_SPELLED = set()  # 選んでもらった書き方(もう一度聞かない)


def spell_options(text):
    """聞き取った名前の、考えられる書き方(最初は聞き取ったまま)。"""
    import re
    stem, ext = os.path.splitext(text) if re.search(r"\.[A-Za-z0-9]{1,5}$", text) else (text, "")
    hira = stem.translate({c: c - 0x60 for c in range(0x30A1, 0x30F7)})
    kata = stem.translate({c: c + 0x60 for c in range(0x3041, 0x3097)})
    out = [stem, kata, hira]
    try:  # 漢字や英語の書き方は、AIに考えてもらう
        import llm
        msg = llm._chat([{"role": "user", "content": (
            f"「{stem}」は、音声から聞き取ったファイルやフォルダの名前です。考えられる書き方(漢字・カタカナ・ひらがな・英語など)を"
            "よく使われる順に最大4つ、1行に1つずつ、名前だけを書いてください。")}], use_tools=False)
        for line in (msg.get("content") or "").splitlines():
            line = re.sub(r"^\s*(?:[-・*]|\d+[.)、．])\s*", "", line).strip().strip("「」『』\"'")
            if line and len(line) <= 40 and not re.search(r'[\\/:*?"<>|]', line):
                out.append(line)
    except Exception:
        pass
    seen = []
    for o in out:
        if o and o not in seen:
            seen.append(o)
    return [o + ext for o in seen[:6]]


def needs_spelling(name, args):
    arg = SPELL_ARGS.get(name)
    value = str(args.get(arg, "")) if arg else ""
    return bool(value) and REQUIRE_CONFIRM and getattr(config, "VOICE_SPELL_CHECK", True) and value not in _SPELLED


def needs_confirm(name, args):
    if name == "web_click" and getattr(config, "WEB_CONFIRM_RISKY", True):
        # 購入・送信・削除などのボタンは、声でも文字でも、押す前に確かめる
        import browser
        try:
            hit = browser.peek(str(args.get("target", "")))
        except Exception:
            hit = None
        if hit and hit.get("risky"):
            args["target"] = hit["label"] or args.get("target", "")
            return True
    if not (REQUIRE_CONFIRM and getattr(config, "CONFIRM_VOICE_DANGER", True)) or name not in DANGEROUS:
        return False
    if name == "window_action":  # ウィンドウは「閉じる」ときだけ確かめる
        return str(args.get("action", "")) in ("close", "閉じる")
    return not (name == "shutdown_pc" and str(args.get("cancel", "")).lower() in ("true", "1"))


def run_tool(name, args, confirmed=False):
    if name not in TOOLS:
        return "すみません、その操作にはまだ対応していません。"
    func, schema = TOOLS[name]
    props = schema["function"]["parameters"]["properties"]
    args = {k: v for k, v in (args or {}).items() if k in props}
    if config.DRY_RUN:
        return f"[DRY] {name}({args})"
    if not confirmed and needs_spelling(name, args):
        arg = SPELL_ARGS[name]
        options = spell_options(str(args[arg]))
        _SPELLED.update(options)
        if len(options) > 1:
            return ask_choice(f"「{args[arg]}」は、どの書き方にしますか？", name, arg, options, args=args)
    if not confirmed and needs_confirm(name, args):
        import json
        what = DANGEROUS[name].format_map({k: args.get(k, "") for k in ("name", "dest", "new_name", "label", "keys", "target")})
        if name == "window_action" and not args.get("name"):
            what = "いま使っているウィンドウを終了"
        return (f"{what}してよいですか？「はい」か「いいえ」で答えてください。"
                + CONFIRM + json.dumps({"tool": name, "args": args, "what": what}, ensure_ascii=False))
    try:
        return func(**args)
    except Exception as e:  # 関数の失敗は、自然な言い方で返す(中身は記録へ)
        import zlog
        zlog.error(f"{name}: {e!r}")
        if isinstance(e, PermissionError):
            return f"ごめんなさい、それは設定で許可されていないのでできませんでした（{e}）。"
        if isinstance(e, (OSError, ConnectionError)) and "http" in str(e).lower():
            return "インターネットにうまくつながらなかったようです。少し時間をおいて、もう一度お願いできますか？"
        return "すみません、うまくいきませんでした。もう一度お願いできますか？"


def _powershell(script, timeout=30):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW,
    )
    return (r.stdout + r.stderr).strip()


# ---------------- ブラウザ ----------------
_BROWSER_EXE = {"chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe"}


def _browser_path():
    return app_path(_BROWSER_EXE.get(config.BROWSER))


def app_path(exe):
    """Windows に登録されたアプリの場所(App Paths)。"""
    if not exe or os.name != "nt":
        return None
    import winreg
    key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + exe
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key) as k:
                return winreg.QueryValue(k, None)
        except OSError:
            pass
    return None


def open_in_browser(url):
    """設定で選んだブラウザで開く(検索結果のリンクや画像の元ページもこれで開く)。
    危険と判定されたサイトや、http(s) 以外のアドレスは開かない。"""
    import websearch
    url = str(url).strip()
    host = websearch._host(url)
    if websearch._looks_bad(url, host) or (getattr(config, "SAFE_SITES_ONLY", True)
                                           and not websearch.host_is_safe(host)):
        raise PermissionError(f"安全でない可能性があるため開きませんでした: {host or url[:40]}")
    import browser
    if browser.enabled():  # ゼラス用ブラウザ: 開いたページの中も、あとから操作できる
        browser.launch(url)
        return
    path = _browser_path()
    if path:
        subprocess.Popen([path, url])
    else:
        webbrowser.open(url)


# よく使うサイト: 呼び名 → (トップページ, サイト内検索のアドレス)
SITES = {
    "youtube": ("https://www.youtube.com/", "https://www.youtube.com/results?search_query={}"),
    "google": ("https://www.google.com/", "https://www.google.com/search?q={}"),
    "yahoo": ("https://www.yahoo.co.jp/", "https://search.yahoo.co.jp/search?p={}"),
    "amazon": ("https://www.amazon.co.jp/", "https://www.amazon.co.jp/s?k={}"),
    "楽天": ("https://www.rakuten.co.jp/", "https://search.rakuten.co.jp/search/mall/{}/"),
    "wikipedia": ("https://ja.wikipedia.org/", "https://ja.wikipedia.org/w/index.php?search={}"),
    "x": ("https://x.com/", "https://x.com/search?q={}"),
    "instagram": ("https://www.instagram.com/", "https://www.instagram.com/explore/search/keyword/?q={}"),
    "github": ("https://github.com/", "https://github.com/search?q={}"),
    "googlemap": ("https://www.google.com/maps/", "https://www.google.com/maps/search/{}"),
    "niconico": ("https://www.nicovideo.jp/", "https://www.nicovideo.jp/search/{}"),
    "netflix": ("https://www.netflix.com/", "https://www.netflix.com/search?q={}"),
    "spotify": ("https://open.spotify.com/", "https://open.spotify.com/search/{}"),
    "mercari": ("https://jp.mercari.com/", "https://jp.mercari.com/search?keyword={}"),
}
SITE_NAMES = {  # 呼び方のゆれ → 上の呼び名
    "youtube": "youtube", "ユーチューブ": "youtube", "ようつべ": "youtube",
    "google": "google", "グーグル": "google", "ぐーぐる": "google",
    "yahoo": "yahoo", "ヤフー": "yahoo", "amazon": "amazon", "アマゾン": "amazon",
    "楽天": "楽天", "rakuten": "楽天", "wikipedia": "wikipedia", "ウィキペディア": "wikipedia", "ウィキ": "wikipedia",
    "x": "x", "twitter": "x", "ツイッター": "x", "エックス": "x", "instagram": "instagram", "インスタ": "instagram",
    "インスタグラム": "instagram", "github": "github", "ギットハブ": "github",
    "googleマップ": "googlemap", "グーグルマップ": "googlemap", "地図": "googlemap", "マップ": "googlemap",
    "ニコニコ": "niconico", "ニコニコ動画": "niconico", "niconico": "niconico", "netflix": "netflix",
    "ネットフリックス": "netflix", "spotify": "spotify", "スポティファイ": "spotify", "メルカリ": "mercari",
}


def site_key(name):
    return SITE_NAMES.get(str(name).strip().lower().replace(" ", ""))


@tool("よく使うサイト(YouTube・Google・Amazon・楽天・Wikipedia・X・地図など)をブラウザで開く。"
      "query を渡すと、そのサイトの中で検索した結果を開く。URLを推測で作らずに、これを使う",
      site=("string", "サイトの名前(例: YouTube、Amazon、Googleマップ)", True),
      query=("string", "サイトの中で検索する言葉(無ければトップページ)", False))
def open_site(site, query=""):
    key = site_key(site)
    if not key:
        # 知らないサイト: 名前で検索して、そのサイトを見つけてもらう
        open_in_browser(config.SEARCH_URL.format(urllib.parse.quote_plus(f"{site} {query}".strip())))
        return f"「{site}」を検索して開きました"
    top, search = SITES[key]
    open_in_browser(search.format(urllib.parse.quote_plus(query)) if query else top)
    return f"{site}で「{query}」を検索しました" if query else f"{site}を開きました"


_YT_ORDER = {"relevance": "EgIQAQ%253D%253D", "views": "CAMSAhAB", "newest": "CAISAhAB"}  # 関連順・再生回数順・新しい順


def youtube_search(query, order="relevance", limit=10):
    """YouTube の検索結果 [(動画の番号, 題名)](動画だけ。並び順を選べる)。"""
    import re
    sp = _YT_ORDER.get(order, _YT_ORDER["relevance"])
    req = urllib.request.Request(
        "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query) + f"&sp={sp}&hl=ja&gl=JP",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
                 "Accept-Language": "ja"})
    with urllib.request.urlopen(req, timeout=10) as r:
        page = r.read(3_000_000).decode("utf-8", "replace")
    out, seen = [], set()
    for m in re.finditer(r'"videoRenderer":\{"videoId":"([\w-]{11})".*?"title":\{"runs":\[\{"text":"(.*?)"', page):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append((m.group(1), m.group(2)))
        if len(out) >= limit:
            break
    return out


@tool("YouTube で動画を探して再生する(「〇〇の動画を流して」)。count を2以上にすると、上から順に続けて再生する"
      "(「〇〇の歌を上から順に流して」)。order で並び順(relevance=関連順、views=再生回数順、newest=新しい順)を選べる",
      query=("string", "探す動画の内容", True),
      order=("string", "relevance / views / newest(既定は relevance)", False),
      count=("integer", "続けて流す本数(1〜20。既定1)", False))
def play_video(query, order="relevance", count=1):
    order = {"再生回数順": "views", "人気順": "views", "新しい順": "newest", "新着順": "newest"}.get(order, order or "relevance")
    count = max(1, min(20, int(count or 1)))
    found = youtube_search(query, order, count)
    if not found:
        open_in_browser(SITES["youtube"][1].format(urllib.parse.quote_plus(query)))
        return f"「{query}」の動画をすぐには選べなかったので、YouTube の検索結果を開きました"
    how = {"views": "再生回数の多い順に", "newest": "新しい順に"}.get(order, "")
    if count == 1 or len(found) == 1:
        open_in_browser(f"https://www.youtube.com/watch?v={found[0][0]}")
        return f"YouTube で「{found[0][1]}」を再生します"
    # 何本かを続けて再生する(YouTube の一時的な再生リスト)
    open_in_browser("https://www.youtube.com/watch_videos?video_ids=" + ",".join(v for v, _ in found))
    titles = "、".join(f"「{t[:20]}」" for _, t in found[:3])
    return f"YouTube で「{query}」を{how}{len(found)}本続けて再生します。最初は{titles}などです"


@tool("ブラウザで指定URLを開く(本当にあるURLが分かっているときだけ。推測で作らない)", url=("string", "開くURL", True))
def open_url(url):
    import re
    # 説明用の決まった名前(example.com など)や、「video_id」「xxxx」のような穴埋めの文字が入った URL は作り話
    if re.search(r"//(?:www\.)?example\.(?:com|org|net)\b|example_|your[_-]|video[_-]?id|xxxx|<[^>]+>", url, re.I):
        return "そのURLは推測で作ったもののようなので開きませんでした。サイト名と探したいものを教えてください"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    open_in_browser(url)
    return f"{url} を開きました"


@tool("ブラウザで検索結果のページを開く(「ブラウザで検索して」など画面で見たいとき)",
      query=("string", "検索キーワード", True))
def web_search(query):
    open_in_browser(config.SEARCH_URL.format(urllib.parse.quote_plus(query)))
    return f"「{query}」を検索しました"


@tool("天気予報を答える(「明日の東京の天気は？」「今日は雨降る？」など)。場所が無ければ設定の地域",
      place=("string", "場所(都道府県や市の名前)", False), day=("string", "今日 / 明日 / 明後日", False))
def get_weather(place="", day="今日"):
    import weather
    name, d = weather.parse(f"{day} {place}")
    if not name and place:  # 知らない地名: 調べて答える
        return search_summary(f"{place} {day}の天気")
    name = name or weather.parse(config.HOME_PLACE)[0] or "東京"
    return weather.report(name, d)


@tool("Webで調べて結果を要約して答える(「〜について調べて」「〜を教えて」など)",
      query=("string", "調べる内容", True))
def search_summary(query):
    import llm
    import websearch
    results = websearch.search(query, max(5, config.SOURCE_COUNT))
    if not results:
        return (f"「{query}」について調べてみましたが、はっきりした情報が見つかりませんでした。"
                "言い方を変えて、もう一度聞いてもらえますか？")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(1) as ex:
        pics = ex.submit(lambda: _safe(websearch.images, query, config.SEARCH_IMAGE_COUNT))  # 関連画像も同時に探す
        # AIに渡す量が多いほど遅くなるため、検索結果の説明文5件 + 上位2ページの冒頭だけにする
        docs = websearch.read_pages(results, count=2, limit=600)
        material = "\n".join(f"・{r['title']}: {r['snippet']}" for r in results[:5])
        material += "\n\n" + "\n\n".join(f"[{r['title']}]\n{d}" for r, d in zip(results, docs))
        summary = llm.summarize(query, material) or results[0]["snippet"]
    links = "\n".join(f"[{i}] {r['title']}\n{r['url']}"
                      for i, r in enumerate(results[:config.SOURCE_COUNT], 1))
    return summary + llm.SOURCES + links + _images_part(query, pics.result())


def _safe(func, *args):
    try:
        return func(*args)
    except Exception:
        return []


def _images_part(query, found, open_gallery=False):
    """画面に渡す画像一覧。open_gallery=True なら一覧ウィンドウを自動で開く。"""
    import json
    import llm
    data = {"query": query, "items": found, "open": open_gallery}
    return llm.IMAGES + json.dumps(data, ensure_ascii=False) if found else ""


@tool("Webで画像・写真を探して一覧で表示する(「〜の写真を探して」「〜の画像を見せて」など)",
      query=("string", "探す画像の内容", True))
def image_search(query):
    import websearch
    found = websearch.images(query)
    if not found:
        return f"「{query}」の画像はうまく見つかりませんでした。別の言い方で探してみましょうか？"
    return f"「{query}」の画像を{len(found)}枚見つけました。一覧を表示します。" + _images_part(query, found, True)


# ---------------- アプリ ----------------
@tool("PCにインストールされたアプリやソフトを名前で起動する(例: Excel、メモ帳、Spotify)",
      name=("string", "アプリの名前", True))
def launch_app(name):
    import apps
    return apps.launch(name)


# ---------------- ファイル・フォルダ ----------------
_HOME = os.path.expanduser("~")
_KNOWN = {  # よく使うフォルダの呼び名 → 本当の場所
    "デスクトップ": config.DESKTOP, "desktop": config.DESKTOP,
    "ドキュメント": config.known_folder("documents"), "documents": config.known_folder("documents"),
    "ダウンロード": config.known_folder("downloads"), "downloads": config.known_folder("downloads"),
    "ピクチャ": config.known_folder("pictures"), "pictures": config.known_folder("pictures"),
    "画像": config.known_folder("pictures"),
    "ミュージック": config.known_folder("music"), "music": config.known_folder("music"),
    "ビデオ": config.known_folder("videos"), "videos": config.known_folder("videos"),
}


def _base(path):
    if not path:
        return config.DESKTOP
    p = path.strip().strip('"')
    if p.lower() in _KNOWN:
        return _KNOWN[p.lower()]
    full = os.path.expandvars(os.path.expanduser(p))
    # AIが「C:\\Desktop」のように、ありそうな場所を思い込みで書いたとき: 名前が分かるなら本当の場所にする
    last = os.path.basename(full.rstrip("\\/")).lower()
    if not os.path.isdir(full) and last in _KNOWN:
        return _KNOWN[last]
    return full


def _resolve(name, path=""):
    if not path and name.strip().lower() in _KNOWN:
        return _KNOWN[name.strip().lower()]
    return os.path.abspath(os.path.join(_base(path), name))


def _guard(p, delete=False):
    """OS・アプリ本体・ドライブ直下など、壊すと危険な場所への操作を拒否する。"""
    if not config.FOLDER_OPS_ENABLED:
        raise PermissionError("フォルダ操作は設定で無効になっています")
    if delete and not config.FOLDER_DELETE_ENABLED:
        raise PermissionError("削除は設定で無効になっています")
    original = os.path.abspath(p)
    p = os.path.normcase(original)  # 比較用(Windows では小文字化される)
    here = os.path.normcase(os.path.dirname(os.path.abspath(__file__)))
    blocked = [os.environ.get(k, "") for k in ("WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")]
    if p == os.path.normcase(os.path.splitdrive(p)[0] + os.sep) or p == os.path.normcase(_HOME):
        raise PermissionError(f"{original} は操作できません")
    for b in [here] + [x for x in blocked if x]:
        b = os.path.normcase(os.path.abspath(b))
        if p == b or p.startswith(b + os.sep):
            raise PermissionError(f"{original} は保護されているため操作できません")
    if delete and os.path.normcase(os.path.abspath(p)) in {os.path.normcase(v) for v in _KNOWN.values()}:
        raise PermissionError(f"{original} は削除できません")
    return original


@tool("フォルダを作成する(場所の指定が無ければデスクトップ)",
      name=("string", "フォルダ名", True), path=("string", "作成場所のパス", False))
def create_folder(name, path=""):
    p = _guard(_resolve(name, path))
    os.makedirs(p, exist_ok=True)
    return f"フォルダ {p} を作成しました"


@tool("新しいテキストファイル(.txt)を作る(場所の指定が無ければデスクトップ)。"
      "ファイルを探す・開くときには使わない(探すのは find_files、開くのは open_file)",
      name=("string", "ファイル名", True), content=("string", "書き込む内容", False),
      path=("string", "保存場所のパス", False))
def create_text_file(name, content="", path=""):
    if not name.lower().endswith(".txt"):
        name += ".txt"
    p = _guard(_resolve(name, path))
    if os.path.exists(p) and not content:
        return f"{os.path.basename(p)} はすでにあります（{os.path.dirname(p)}）。中身はそのままにしました"
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return f"{os.path.basename(p)} を作成しました（{os.path.dirname(p)}）"


@tool("既存のテキストファイルの末尾に追記する",
      name=("string", "ファイル名", True), content=("string", "追記する内容", True),
      path=("string", "ファイルの場所のパス", False))
def append_text_file(name, content, path=""):
    if not name.lower().endswith(".txt"):
        name += ".txt"
    p = _resolve(name, path)
    with open(p, "a", encoding="utf-8") as f:
        f.write(content + "\n")
    return f"{p} に追記しました"


@tool("フォルダをエクスプローラーで開く(デスクトップ・ドキュメント・ダウンロード等の名前も可)",
      path=("string", "フォルダのパスまたは名前", True))
def open_folder(path):
    p = _resolve(path)
    if not os.path.isdir(p):
        return f"フォルダ {p} が見つかりません"
    os.startfile(p)
    return f"{p} を開きました"


@tool("フォルダの中身を一覧する", path=("string", "フォルダのパスまたは名前", False))
def list_folder(path=""):
    p = _resolve(path) if path else config.DESKTOP
    items = sorted(os.listdir(p), key=str.lower)
    dirs = [f"[{n}]" for n in items if os.path.isdir(os.path.join(p, n))]
    files = [n for n in items if not os.path.isdir(os.path.join(p, n))]
    shown = (dirs + files)[:30]
    more = f" ほか{len(items) - 30}件" if len(items) > 30 else ""
    return f"{p}: " + (", ".join(shown) + more if shown else "空です")


def _locate(name, path, tool_name, args):
    """名前からファイル・フォルダを1つに決める。(パス, None) または 決まらないとき (None, 返事)。
    その場所に無ければ、よく使う場所から探す(聞き取りの書き方の違いも考える)。"""
    p = _resolve(name, path)
    if os.path.exists(p):
        return p, None
    found = []
    for spelling in [name] + spell_options(name)[1:]:
        key = os.path.splitext(spelling.lower())[0]
        found += [f for f in find_paths(spelling, path) if f not in found and
                  os.path.splitext(os.path.basename(f).lower())[0] == key]
        if found:
            break
    if not found:
        return None, f"「{name}」が見つかりませんでした"
    if len(found) > 1:
        return None, ask_choice(f"「{name}」が{len(found)}件あります。どれにしますか？", tool_name, "name", found[:6],
                                [f"{os.path.basename(f)}（{os.path.dirname(f)}）" for f in found[:6]], args=args)
    return found[0], None


@tool("ファイルまたはフォルダの名前を変更する",
      name=("string", "今の名前", True), new_name=("string", "新しい名前", True),
      path=("string", "ある場所のパス", False))
def rename_item(name, new_name, path=""):
    src, reply = _locate(name, path, "rename_item", {"new_name": new_name})
    if reply:
        return reply
    src = _guard(src)
    dst = _guard(os.path.join(os.path.dirname(src), new_name))
    if os.path.exists(dst):
        return f"{new_name} はすでに存在します"
    os.rename(src, dst)
    return f"{os.path.basename(src)} を {new_name} に変更しました"


@tool("ファイルまたはフォルダを別のフォルダへ移動する",
      name=("string", "移動するもの", True), dest=("string", "移動先フォルダのパスまたは名前", True),
      path=("string", "今ある場所のパス", False))
def move_item(name, dest, path=""):
    import shutil
    src, reply = _locate(name, path, "move_item", {"dest": dest})
    if reply:
        return reply
    src = _guard(src)
    dst_dir = _guard(_resolve(dest))
    os.makedirs(dst_dir, exist_ok=True)
    shutil.move(src, os.path.join(dst_dir, os.path.basename(src)))
    return f"{name} を {dst_dir} へ移動しました"


@tool("ファイルまたはフォルダを別のフォルダへコピーする",
      name=("string", "コピーするもの", True), dest=("string", "コピー先フォルダのパスまたは名前", True),
      path=("string", "今ある場所のパス", False))
def copy_item(name, dest, path=""):
    import shutil
    src, reply = _locate(name, path, "copy_item", {"dest": dest})
    if reply:
        return reply
    dst_dir = _guard(_resolve(dest))
    dst = os.path.join(dst_dir, os.path.basename(src))
    os.makedirs(dst_dir, exist_ok=True)
    (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, dst)
    return f"{name} を {dst_dir} へコピーしました"


@tool("ファイルまたはフォルダをごみ箱へ移動する(完全には消さない)",
      name=("string", "削除するもの", True), path=("string", "ある場所のパス", False))
def delete_item(name, path=""):
    p, reply = _locate(name, path, "delete_item", {})
    if reply:
        return reply
    p = _guard(p, delete=True)
    kind = "Directory" if os.path.isdir(p) else "File"
    out = _powershell("Add-Type -AssemblyName Microsoft.VisualBasic;"
                      f"[Microsoft.VisualBasic.FileIO.FileSystem]::Delete{kind}('{p.replace(chr(39), chr(39) * 2)}',"
                      "'OnlyErrorDialogs','SendToRecycleBin')")
    return f"エラー: {out}" if os.path.exists(p) else f"{os.path.basename(p)} をごみ箱へ移動しました"


# ---------------- PC基本制御 ----------------
@tool("システム音量を0〜100に設定する", level=("integer", "音量(0〜100)", True))
def set_volume(level):
    import pyautogui
    level = max(0, min(100, int(level)))
    pyautogui.press("volumedown", presses=50)   # 一旦0へ(1回=2%)
    pyautogui.press("volumeup", presses=level // 2)
    return f"音量を{level}にしました"


@tool("システム音量のミュートを切り替える")
def toggle_mute():
    import pyautogui
    pyautogui.press("volumemute")
    return "ミュートを切り替えました"


@tool("画面をロックする")
def lock_screen():
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    return "画面をロックしました"


@tool("PCをシャットダウンする(30秒後)。cancel=trueで予約を取り消す",
      cancel=("boolean", "取り消す場合true", False))
def shutdown_pc(cancel=False):
    if cancel:
        subprocess.run(["shutdown", "/a"], creationflags=_NO_WINDOW)
        return "シャットダウンを取り消しました"
    subprocess.run(["shutdown", "/s", "/t", "30"], creationflags=_NO_WINDOW)
    return "30秒後にシャットダウンします(取り消し可)"


# ---------------- Bluetooth ----------------
@tool("Bluetooth機器を接続(connect=true)または切断(connect=false)する",
      device=("string", "機器名の一部", True), connect=("boolean", "接続ならtrue", True))
def bluetooth_connect(device, connect=True):
    name = str(device).replace("'", "''")
    verb = "Enable" if str(connect).lower() not in ("false", "0") else "Disable"
    script = (
        f"$d = Get-PnpDevice -Class Bluetooth -FriendlyName '*{name}*' -ErrorAction SilentlyContinue"
        " | Where-Object { $_.FriendlyName -notmatch 'Enumerator|Radio|Adapter|Transport' };"
        " if (-not $d) { 'NOTFOUND'; exit };"
        f" $d | {verb}-PnpDevice -Confirm:$false -ErrorAction Stop;"
        " 'OK:' + ($d.FriendlyName -join ', ')"
    )
    out = _powershell(script)
    if "NOTFOUND" in out:
        return f"Bluetooth機器「{device}」が見つかりません"
    if out.startswith("OK:"):
        return f"{out[3:]} を{'接続' if verb == 'Enable' else '切断'}しました"
    return f"エラー: {out}(管理者権限で起動してください)"


# ---------------- 画面の直接操作(マウス・キーボード) ----------------
# まずはマウスを動かさずに(ボタンや入力欄へ直接伝えて)操作し、あなたの操作を邪魔しない。
# それができないアプリのときだけ、あなたの手が止まるのを待ってから本物のマウス・キーボードを少し借り、
# 終わったらマウスの位置と使っていた窓を元に戻す。
_SCREEN_KINDS = {"click": "クリック", "type": "文字の入力", "keys": "キー操作", "scroll": "スクロール",
                 "windows": "ウィンドウの操作"}


def screen_tool(kind, description, **params):
    """画面を直接操作する関数。全体のスイッチと、操作の種類ごとのスイッチの両方が ON のときだけ実行する。"""
    def deco(func):
        def run(**kw):
            if not getattr(config, "SCREEN_CONTROL_ENABLED", False):
                raise PermissionError("画面の直接操作は設定で許可されていません（設定の「権限」タブ）")
            if not getattr(config, f"SCREEN_ALLOW_{kind.upper()}", True):
                raise PermissionError(f"画面の{_SCREEN_KINDS[kind]}は設定で許可されていません（設定の「権限」タブ）")
            return func(**kw)
        run.__name__ = func.__name__
        SCREEN_TOOLS.add(func.__name__)
        return tool(description, **params)(run)
    return deco


def _is_browser(hwnd):
    import screen
    return screen.class_name(hwnd).startswith(("Chrome_WidgetWin", "MozillaWindowClass"))


def _ours(hwnd, title):
    """ゼラス用ブラウザの窓か(それならページの中へ直接伝える)。"""
    import browser
    try:
        return browser.enabled() and browser.running() and browser.owns(hwnd, title)
    except Exception:
        return False


def browser_click(label):
    """ページの中で押す。購入・送信などは確かめてから(run_tool 経由)。"""
    return run_tool("web_click", {"target": label})


def _target():
    import screen
    hwnd, title = screen.target_window()
    if not hwnd:
        raise RuntimeError("操作するウィンドウが見つかりません")
    return hwnd, title


@screen_tool("click", "直前まで使っていたウィンドウの中の、ボタンや項目を名前で探して押す(例: 「保存」「OK」「次へ」)",
             label=("string", "押すボタンや項目の名前(画面に表示されている文字)", True))
def click_on(label):
    import pyautogui
    import screen
    hwnd, title = _target()
    if _ours(hwnd, title):  # ゼラス用ブラウザ: ページの中へ直接
        return browser_click(label)
    name = screen.press_button(hwnd, label)  # 1. 昔ながらのボタン: マウスを使わずに押す
    if name:
        return f"「{title}」の「{name}」を押しました(マウスは動かしていません)"
    hit = screen.uia_act(hwnd, label)  # 2. 新しいアプリ: マウスを使わずに押す・選ぶ・開く
    if not hit and screen.class_name(hwnd).startswith("Chrome_WidgetWin"):
        # ブラウザ(Chrome・Edge)は、最初に問い合わせたときにページの中身の情報を作り始めるので、少し待ってもう一度
        time.sleep(1.5)
        hit = screen.uia_act(hwnd, label)
    if hit and hit[0] == "done":
        return f"「{title}」の「{hit[1]}」を押しました(マウスは動かしていません)"
    if not hit and _is_browser(hwnd):
        # 4. ブラウザのページの中: ページ内検索で文字を探し、検索を閉じるとそのリンクやボタンが選ばれるので Enter で押す
        with screen.Borrow():
            screen.focus(hwnd)
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.4)
            screen.paste_text(label)
            pyautogui.press("enter")
            time.sleep(0.4)
            pyautogui.press("esc")
            time.sleep(0.3)
            pyautogui.press("enter")
        return f"「{title}」のページで「{label}」を探して押しました"
    if not hit:
        return f"「{title}」の中に「{label}」が見つかりませんでした"
    with screen.Borrow():  # 3. マウスでしか押せない: 手が止まるのを待ってから、少しだけ借りる
        pyautogui.click(hit[1], hit[2])
    return f"「{title}」の「{hit[3]}」をクリックしました"


@screen_tool("type", "直前まで使っていたウィンドウに、文字を入力する(日本語も可)", text=("string", "入力する文字", True))
def type_text(text):
    import screen
    hwnd, title = _target()
    if _ours(hwnd, title):
        import browser
        return browser.type_text(text, "", replace=False)
    if screen.insert_text(hwnd, text):  # 入力欄へ直接(キーボードを使わない)
        return f"「{title}」に入力しました(キーボードは使っていません)"
    with screen.Borrow():
        screen.focus(hwnd)
        screen.paste_text(text)
    return f"「{title}」に入力しました"


@screen_tool("keys", "直前まで使っていたウィンドウで、キーやショートカットを押す(例: enter, ctrl+s, ctrl+c, alt+f, f5)",
             keys=("string", "押すキー。同時に押すものは + でつなぐ", True))
def press_keys(keys):
    import pyautogui
    import screen
    names = [k.strip().lower() for k in str(keys).replace("＋", "+").split("+") if k.strip()]
    alias = {"control": "ctrl", "コントロール": "ctrl", "エンター": "enter", "改行": "enter", "シフト": "shift",
             "オルト": "alt", "タブ": "tab", "エスケープ": "esc", "削除": "delete", "スペース": "space",
             "上": "up", "下": "down", "左": "left", "右": "right", "ウィンドウズ": "win", "windows": "win"}
    names = [alias.get(k, k) for k in names]
    bad = [k for k in names if k not in pyautogui.KEYBOARD_KEYS]
    if not names or bad:
        return f"「{keys}」というキーは押せません"
    hwnd, title = _target()
    if _ours(hwnd, title):
        import browser
        return browser.keys(keys)
    with screen.Borrow():  # キーは手前の窓にしか届かないので、手が止まるのを待ってから少しだけ借りる
        screen.focus(hwnd)
        pyautogui.hotkey(*names)
    return f"「{title}」で {'+'.join(names)} を押しました"


@screen_tool("scroll", "直前まで使っていたウィンドウを上下にスクロールする",
             direction=("string", "up(上) または down(下)", True), amount=("integer", "量(1〜20。既定5)", False))
def scroll(direction, amount=5):
    import pyautogui
    import screen
    hwnd, title = _target()
    down = not (str(direction).lower().startswith("u") or "上" in str(direction))
    n = max(1, min(20, int(amount or 5)))
    if _ours(hwnd, title):
        import browser
        return browser.scroll(down, n)
    if screen.scroll_window(hwnd, down, n):
        return f"「{title}」をスクロールしました(マウスは動かしていません)"
    with screen.Borrow():
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
        pyautogui.moveTo((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        pyautogui.scroll((-n if down else n) * 120)
    return f"「{title}」をスクロールしました"


@screen_tool("click", "画面の位置(ピクセル)を指定してクリックする。ボタン名で探せないときだけ使う",
             x=("integer", "横の位置", True), y=("integer", "縦の位置", True),
             double=("boolean", "ダブルクリックならtrue", False))
def click_position(x, y, double=False):
    import pyautogui
    import screen
    w, h = pyautogui.size()
    x, y = int(x), int(y)
    if not (0 <= x < w and 0 <= y < h):
        return "画面の外の位置はクリックできません"
    with screen.Borrow():
        pyautogui.click(x, y, clicks=2 if str(double).lower() in ("true", "1") else 1)
    return f"({x}, {y}) をクリックしました"


@screen_tool("windows", "ウィンドウを手前に出す(切り替える)。例:「メモ帳に切り替えて」",
             name=("string", "ウィンドウの題名やアプリ名の一部", True))
def switch_window(name):
    import screen
    hwnd, title = screen.find_window(name)
    if not hwnd:
        return f"「{name}」のウィンドウは見つかりませんでした"
    screen.bring_front(hwnd)
    return f"「{title}」に切り替えました"


@screen_tool("windows", "ウィンドウを最小化・最大化・元の大きさに戻す・閉じる",
             action=("string", "minimize(最小化) / maximize(最大化) / restore(元に戻す) / close(閉じる)", True),
             name=("string", "ウィンドウの題名の一部(省略すると直前まで使っていたウィンドウ)", False))
def window_action(action, name=""):
    import screen
    act = {"最小化": "minimize", "最大化": "maximize", "元に戻す": "restore", "閉じる": "close"}.get(action, action)
    if act not in ("minimize", "maximize", "restore", "close"):
        return f"「{action}」という操作はできません"
    hwnd, title = screen.find_window(name) if name else _target()
    if not hwnd:
        return f"「{name}」のウィンドウは見つかりませんでした"
    screen.window_command(hwnd, act)
    return f"「{title}」を{ {'minimize': '最小化', 'maximize': '最大化', 'restore': '元の大きさに', 'close': '閉じ'}[act] }しました"


# ---------------- Webページの中の操作(ゼラス用ブラウザ) ----------------
# ページの中へ直接伝えるので、あなたのマウスやキーボードは使わない(画面の直接操作の許可は要らない)。
def web_tool(description, **params):
    def deco(func):
        def run(**kw):
            import browser
            if not getattr(config, "WEB_CONTROL_ENABLED", True):
                raise PermissionError("Webページの操作は設定で許可されていません（設定の「権限」タブ）")
            if not browser.running():
                return "操作できるブラウザが開いていません。先にサイトを開いてください（例:「YouTubeを開いて」）"
            return func(**kw)
        run.__name__ = func.__name__
        WEB_TOOLS.add(func.__name__)
        return tool(description, **params)(run)
    return deco


@web_tool("開いているWebページの中のリンク・ボタン・タブ・チェックボックスなどを、画面に出ている名前で探して押す"
          "(例:「ログイン」「次へ」「2番目の動画」は題名の一部で)",
          target=("string", "押すものの名前(ページに表示されている文字の一部でよい)", True))
def web_click(target):
    import browser
    text, hit = browser.click(target)
    if hit and hit.get("alts"):  # 同じくらい当てはまるものが複数: どれを押すか確かめる
        return ask_choice(f"ページの中に「{target}」に当てはまるものが{len(hit['alts'])}つあります。どれを押しますか？",
                          "web_click", "target", hit["alts"])
    return text


@web_tool("開いているWebページの入力欄に文字を入れる。submit=true なら入れたあと Enter で決定(検索など)",
          text=("string", "入れる文字", True),
          field=("string", "入力欄の名前(例: 検索、メールアドレス)。省略すると選ばれている欄か検索欄", False),
          submit=("boolean", "入れたあと Enter を押すなら true", False))
def web_type(text, field="", submit=False):
    import browser
    return browser.type_text(text, field, str(submit).lower() in ("true", "1"))


@web_tool("開いているWebページの選択の一覧(プルダウン)から項目を選ぶ",
          option=("string", "選ぶ項目の文字", True), field=("string", "一覧の名前(省略可)", False))
def web_select(option, field=""):
    import browser
    return browser.choose(option, field)


@web_tool("開いているWebページでキーを押す(例: enter, tab, esc, space, pagedown, ctrl+a)",
          keys=("string", "押すキー。同時に押すものは + でつなぐ", True))
def web_key(keys):
    import browser
    return browser.keys(keys)


@web_tool("開いているWebページを上下にスクロールする",
          direction=("string", "up(上) または down(下)", True), amount=("integer", "量(1〜20。既定5)", False))
def web_scroll(direction, amount=5):
    import browser
    down = not (str(direction).lower().startswith("u") or "上" in str(direction))
    return browser.scroll(down, max(1, min(20, int(amount or 5))))


@web_tool("開いているWebページで、前のページに戻る・次へ進む・読み込み直す・いちばん上/下へ移動する",
          action=("string", "back(戻る) / forward(進む) / reload(更新) / top(いちばん上) / bottom(いちばん下)", True))
def web_page(action):
    import browser
    act = {"戻る": "back", "進む": "forward", "更新": "reload", "再読み込み": "reload",
           "上": "top", "一番上": "top", "下": "bottom", "一番下": "bottom"}.get(action, action)
    return browser.navigate(act)


@web_tool("開いているWebページの内容を読んで、要約したり質問に答えたりする(「このページを要約して」「この記事の結論は？」)",
          question=("string", "ページについての質問(省略すると要約)", False))
def web_read(question=""):
    import browser
    import llm
    title, url, text = browser.read()
    if not text.strip():
        return "このページからは文章を読み取れませんでした"
    return llm.page_answer(question, title, text) + llm.SOURCES + f"[1] {title or url}\n{url}"


@web_tool("開いているWebページの動画・音声を操作する(再生・一時停止・消音・全画面・早送り・巻き戻し・次の動画・速さ)",
          action=("string", "play / pause / toggle / mute / unmute / fullscreen / exit_fullscreen / forward / rewind /"
                            " restart / next / faster / slower / normal", True),
          seconds=("integer", "forward / rewind で動かす秒数(既定10)", False))
def web_video(action, seconds=10):
    import browser
    return browser.media(action, seconds)


@web_tool("ゼラス用ブラウザのタブを操作する(新しいタブ・閉じる・切り替え)",
          action=("string", "new(新しいタブ) / close(閉じる) / switch(名前で切り替え) / previous(ひとつ前のタブ)", True),
          name=("string", "タブの題名の一部(switch・close のとき)", False))
def web_tab(action, name=""):
    import browser
    return browser.tab(action, name)


# ---------------- メール(画面を使わずに裏側で) ----------------
@tool("メールのフォルダの未読メールを、すべて既読にする(メールアプリの画面は使わずに裏側で行う)。"
      "例:「迷惑メールを全部既読にして」",
      folder=("string", "フォルダの名前(例: 迷惑メール、受信トレイ、仕事)", True))
def mail_mark_read(folder):
    import mail
    return mail.mark_read(folder) if mail.backend() else mail.NOT_READY


@tool("メールのフォルダの未読メールの数を答える", folder=("string", "フォルダの名前(省略すると受信トレイ)", False))
def mail_unread(folder=""):
    import mail
    return mail.unread(folder) if mail.backend() else mail.NOT_READY


@tool("メールのフォルダの名前を変える", folder=("string", "今のフォルダの名前", True),
      new_name=("string", "新しい名前", True))
def mail_rename_folder(folder, new_name):
    import mail
    return mail.rename(folder, new_name) if mail.backend() else mail.NOT_READY


@tool("メールのフォルダの一覧を答える")
def mail_folders():
    import mail
    return mail.listing() if mail.backend() else mail.NOT_READY


# ---------------- ファイルを読む(テクニカルモードのコードの添削など) ----------------
@tool("テキストファイル(プログラムのコード・設定ファイル・ログなど)の中身を読む",
      name=("string", "ファイル名またはパス", True), path=("string", "ある場所(分かれば)", False))
def read_text_file(name, path=""):
    p, reply = _locate(name, path, "read_text_file", {})
    if reply:
        return reply
    if os.path.isdir(p):
        return f"{p} はフォルダです"
    text = file_text(p, limit=400_000)
    limit = 16000
    note = f"\n…（長いので最初の{limit}文字だけ読みました）" if len(text) > limit else ""
    return f"{p} の中身:\n{text[:limit]}{note}"


# ---------------- Word・PowerPoint・Excel を作る ----------------
_OFFICE_UNIT = {"pptx": "スライド{n}枚", "docx": "{n}章", "xlsx": "{n}シート"}


@tool("Word(.docx)・PowerPoint(.pptx)・Excel(.xlsx)のファイルを、頼まれた内容で作って開く(作ったファイルは自由に編集できる)。"
      "PDF は、はっきり「PDFで」と頼まれたときだけ kind=pdf にする。"
      "例:「新サービスの提案資料をパワポで作って」「今の内容をWordにまとめて」「月別の売上表をExcelで作って」",
      kind=("string", "pptx(PowerPoint) / docx(Word) / xlsx(Excel) / pdf(頼まれたときだけ)", True),
      request=("string", "どんな資料にするか(頼まれた文をそのまま)", True),
      name=("string", "ファイル名(省略すると資料の題名)", False),
      path=("string", "保存する場所(省略するとデスクトップ)", False),
      font=("string", "書体: ゴシック体 / 明朝体 / 教科書体 / ポップ体 / 丸ゴシック体 / UDゴシック(省略すると設定のもの)", False),
      source=("string", "中身の材料: web(ネットで調べる) / attach(添付) / user(伝えられた内容) / chat(会話の内容)", False),
      design=("string", "デザインの希望(色・書体・枚数・雰囲気など)", False))
def make_office_file(kind, request, name="", path="", font="", source="", design=""):
    import fonts
    import llm
    import officedoc
    kind = llm.OFFICE_KINDS.get(str(kind).lower().lstrip("."), str(kind).lower().lstrip("."))
    pdf = kind == "pdf"
    if pdf:  # PDF は、編集できる元のファイル(スライドなら PowerPoint、ほかは Word)を作ってから変換する
        kind = "pptx" if re.search(r"スライド|プレゼン|パワポ|パワーポイント|発表", request) else "docx"
    if kind not in officedoc.MAKERS:
        return "作れるのは Word・PowerPoint・Excel(と PDF)のファイルです"
    llm._status("@office")  # 画面に「作成中」の表示を出す
    wish = f"{font} {design} {request}"
    style = fonts.style_of(wish, "") or ("pop" if re.search(r"ポップ|かわいい|楽しい", design or "") else "") \
        or getattr(config, "OFFICE_FONT", "gothic")
    head, body, font_note = fonts.pick(style)  # このPCに入っている書体だけを使う
    officedoc.use_fonts(head, body)
    officedoc.use_theme(officedoc.theme_of(design))  # 「青系で」「緑で」など(無ければ標準の紺と青)
    doc = officedoc.parse(llm.write_document(kind, request, source))
    if not doc["sections"]:
        return "資料の中身をうまく作れませんでした。何についての資料か、もう少し詳しく教えてください"
    if getattr(config, "OFFICE_IMAGES", True) and kind != "xlsx":
        # 写真は、使ってよい許可が明記されたもの(Wikimedia Commons)だけ。作者とライセンスを資料に書き添える
        officedoc.attach_images(doc, os.path.join(config.APP_DIR, "office_images"))
    else:
        for sec in doc["sections"]:
            sec["blocks"] = [(k, b) for k, b in sec["blocks"] if k != "image"]
    if officedoc.generic_title(doc["title"]):  # 「資料」のような題名なら、頼まれた内容(「株式会社才」など)を題名にする
        topic = re.match(r"^(.+?)の(?:" + "|".join(map(re.escape, llm.KIND_NAMES.values())) + ")", request or "")
        topic = topic.group(1).strip() if topic else llm.office_topic(request)
        if topic and len(topic) <= 40:
            doc["title"] = topic
    folder = _guard(_base(path))
    p = officedoc.save_path(folder, os.path.splitext(name)[0] if name else doc["title"], "." + kind)
    count = officedoc.MAKERS[kind](doc, p)
    made = f"「{os.path.basename(p)}」"
    if pdf:
        out = officedoc.to_pdf(p)
        if out:
            made = f"「{os.path.basename(out)}」(編集用に{made}も保存)"
            p = out
        else:
            made += "（PDF にするには Microsoft Office か LibreOffice が必要なため、編集できる形で保存しました）"
    opened = "作って開きました"
    if os.name == "nt":
        try:
            os.startfile(p)
        except OSError:  # Office などの開くアプリが無い
            opened = "作りました"
    note = f"。{font_note}" if font_note else ""
    import json
    files = [p] + ([os.path.splitext(p)[0] + "." + kind] if pdf and p.endswith(".pdf") else [])
    return (f"{made}を{opened}（{folder}・{_OFFICE_UNIT[kind].format(n=count)}・書体: {head}）{note}。"
            "自由に編集できます。直したいところがあれば言ってください" + FILES + json.dumps(files, ensure_ascii=False))


@tool("Word・PowerPoint・Excel のファイルを PDF にする(PDF にしてと頼まれたときだけ)",
      name=("string", "ファイル名またはパス", True), path=("string", "ある場所(分かれば)", False))
def convert_to_pdf(name, path=""):
    import officedoc
    p, reply = _locate(name, path, "convert_to_pdf", {})
    if reply:
        return reply
    if os.path.splitext(p)[1].lower() not in (".docx", ".pptx", ".xlsx"):
        return "PDF にできるのは Word・PowerPoint・Excel のファイルです"
    out = officedoc.to_pdf(_guard(p))
    if not out:
        return "PDF にするには、このPCに Microsoft Office か LibreOffice が必要です"
    import json
    return (f"「{os.path.basename(out)}」を作りました（{os.path.dirname(out)}）。元のファイルもそのまま残しています"
            + FILES + json.dumps([out], ensure_ascii=False))


# ---------------- ファイルの中身で探す ----------------
_KINDS = {  # 呼び方 → 探すファイルの種類
    "text": (".txt", ".md", ".log", ".csv", ".tsv", ".json", ".ini", ".xml", ".html", ".htm", ".yaml", ".yml"),
    "word": (".docx",), "excel": (".xlsx",), "powerpoint": (".pptx",),
}
_KIND_WORDS = {"メモ帳": "text", "テキスト": "text", "txt": "text", "メモ": "text", "ワード": "word", "word": "word",
               "エクセル": "excel", "excel": "excel", "パワーポイント": "powerpoint", "パワポ": "powerpoint",
               "powerpoint": "powerpoint"}


def file_text(path, limit=2_000_000):
    """ファイルの中の文字(テキスト・Word・Excel・PowerPoint)。読めなければ ""。"""
    import re
    import zipfile
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".docx", ".xlsx", ".pptx"):
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if re.match(
                    r"word/document\.xml|xl/sharedStrings\.xml|xl/worksheets/sheet\d+\.xml|ppt/slides/slide\d+\.xml", n)]
                xml = " ".join(z.read(n)[:limit].decode("utf-8", "replace") for n in names)
            return re.sub(r"<[^>]+>", " ", xml)
        with open(path, "rb") as f:
            data = f.read(limit)
        for enc in ("utf-8-sig", "utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp932"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                pass
        return data.decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile, KeyError):
        return ""


def _fold(s):
    import unicodedata
    s = unicodedata.normalize("NFKC", s).lower()
    return s.translate({c: c - 0x60 for c in range(0x30A1, 0x30F7)})  # カタカナはひらがなにそろえる


def search_contents(text, path="", kind="", limit=30):
    """中に text が書かれたファイル [(パス, 見つかった回数, 前後の文)](多い順)。"""
    import re
    exts = _KINDS.get(_KIND_WORDS.get(str(kind).lower(), str(kind).lower()), sum(_KINDS.values(), ()))
    words = [_fold(w) for w in re.split(r"[\s　、,]+|(?<=.)(?:と|や|および)(?=.)", str(text).strip()) if w]
    words = words or [_fold(text)]
    hits = []
    for root in _search_roots(path):
        base_depth = root.rstrip(os.sep).count(os.sep)
        for cur, dirs, files in os.walk(root):
            if cur.count(os.sep) - base_depth >= 4:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and d.lower() not in ("node_modules", "appdata")]
            for n in files:
                full = os.path.join(cur, n)
                if not n.lower().endswith(exts) or n.startswith("~$"):
                    continue
                try:
                    if os.path.getsize(full) > 20_000_000:
                        continue
                except OSError:
                    continue
                body = _fold(file_text(full))
                if all(w in body for w in words):
                    i = body.find(words[0])
                    around = re.sub(r"\s+", " ", body[max(0, i - 20):i + 40]).strip()
                    hits.append((full, sum(body.count(w) for w in words), around))
            if len(hits) > 200:
                break
    return sorted(hits, key=lambda h: -h[1])[:limit]


@tool("ファイルの中身を読んで、ある言葉や話題が書かれているファイルを探す(open=true なら開く)。"
      "例:「デスクトップのメモ帳のファイルから、旅行について書いてあるものを開いて」",
      text=("string", "中に書かれている言葉・話題", True),
      path=("string", "探す場所(デスクトップ・ドキュメントなど。省略するとよく使う場所すべて)", False),
      kind=("string", "ファイルの種類: メモ帳(テキスト) / ワード / エクセル / パワーポイント(省略するとすべて)", False),
      open=("boolean", "見つけたファイルを開くなら true", False))
def find_in_files(text, path="", kind="", open=False):
    hits = search_contents(text, path, kind)
    where = f"{path}の" if path else ""
    if not hits:
        return f"{where}ファイルの中に「{text}」が書かれたものは見つかりませんでした"
    if str(open).lower() not in ("true", "1"):
        lines = "\n".join(f"・{os.path.basename(p)}（{n}か所）… {a}" for p, n, a in hits[:5])
        return f"「{text}」が書かれたファイルが{len(hits)}件見つかりました。\n{lines}"
    if len(hits) > 1:  # 複数: どれを開くか確かめる
        return ask_choice(f"「{text}」が書かれたファイルが{len(hits)}件あります。どれを開きますか？", "open_file", "name",
                          [p for p, _, _ in hits[:6]], [f"{os.path.basename(p)}（{n}か所）" for p, n, _ in hits[:6]])
    return open_file(hits[0][0])


# ---------------- ファイルを探す・開く ----------------
def _search_roots(path=""):
    if path:
        return [_base(path)]
    public = os.path.join(os.environ.get("PUBLIC", r"C:\\Users\\Public"), "Desktop")  # 全員に見えるデスクトップ
    roots = [config.DESKTOP, public] + [_KNOWN[k] for k in ("documents", "downloads", "pictures", "music", "videos")]
    return [r for i, r in enumerate(roots) if r not in roots[:i] and os.path.isdir(r)]


def find_paths(name, path="", limit=10):
    """名前に name を含むファイル・フォルダを、デスクトップ・ドキュメントなどから探す(深さ4まで)。"""
    key = name.strip().lower()
    stem = os.path.splitext(key)[0] or key
    hits = []
    for root in _search_roots(path):
        base_depth = root.rstrip(os.sep).count(os.sep)
        for cur, dirs, files in os.walk(root):
            if cur.count(os.sep) - base_depth >= 4:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and d.lower() not in ("node_modules", "appdata")]
            for n in dirs + files:
                low = n.lower()
                if key in low or stem in os.path.splitext(low)[0]:
                    full = os.path.join(cur, n)
                    exact = os.path.splitext(low)[0] == stem or low == key
                    hits.append((not exact, len(n), full))
            if len(hits) > 200:
                break
    return [h[2] for h in sorted(hits)[:limit]]


@tool("PCの中のファイルやフォルダを名前で探す(デスクトップ・ドキュメント・ダウンロードなど)。見つかった場所を答える",
      name=("string", "探す名前(一部でよい)", True), path=("string", "探す場所(指定が無ければ、よく使う場所すべて)", False))
def find_files(name, path=""):
    found = find_paths(name, path)
    if not found:
        return f"「{name}」という名前のファイルは見つかりませんでした"
    lines = "\n".join(f"・{p}" for p in found[:5])
    return f"「{name}」が {len(found)} 件見つかりました。\n{lines}"


@tool("ファイルやフォルダを開く(名前だけでもよい。見つからなければ探してから開く)",
      name=("string", "開くファイル名またはパス", True), path=("string", "ある場所(分かれば)", False))
def open_file(name, path=""):
    p = _resolve(name, path)
    if not os.path.exists(p):
        found = find_paths(name, path)
        if not found:
            return f"「{name}」が見つからないため、開けませんでした"
        key = os.path.splitext(name.strip().lower())[0]
        exact = [f for f in found if os.path.splitext(os.path.basename(f).lower())[0] == key or
                 os.path.basename(f).lower() == name.strip().lower()]
        same = exact if exact else found
        if len(same) > 1:  # 同じような名前が複数: どれを開くか確かめる
            return ask_choice(f"「{name}」に当てはまるものが{len(same)}件あります。どれを開きますか？", "open_file", "name",
                              same[:6], [f"{os.path.basename(f)}（{os.path.dirname(f)}）" for f in same[:6]])
        p = same[0]
    _guard(p)
    if os.name == "nt":
        os.startfile(p)  # いつものアプリで開く(テキストならメモ帳など)
    else:
        subprocess.Popen(["xdg-open", p])
    return f"{os.path.basename(p)} を開きました（{os.path.dirname(p)}）"
