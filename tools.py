"""AIが呼び出せるPC操作関数(Tool Call)。重いライブラリは関数内で読み込む。"""
import os
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


def schemas():
    hide = set() if getattr(config, "SCREEN_CONTROL_ENABLED", False) else SCREEN_TOOLS
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
}
REQUIRE_CONFIRM = False  # いまの依頼が声によるものか(作業プロセスが依頼ごとに設定する)
CONFIRM = "\n\n確認:\n"  # 返事のうち、これより後ろは「確認待ちの操作」(画面用。読み上げない)


def needs_confirm(name, args):
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
    if not confirmed and needs_confirm(name, args):
        import json
        what = DANGEROUS[name].format_map({k: args.get(k, "") for k in ("name", "dest", "new_name", "label", "keys")})
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
    exe = _BROWSER_EXE.get(config.BROWSER)
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


@tool("ファイルまたはフォルダの名前を変更する",
      name=("string", "今の名前", True), new_name=("string", "新しい名前", True),
      path=("string", "ある場所のパス", False))
def rename_item(name, new_name, path=""):
    src = _guard(_resolve(name, path))
    dst = _guard(os.path.join(os.path.dirname(src), new_name))
    if os.path.exists(dst):
        return f"{new_name} はすでに存在します"
    os.rename(src, dst)
    return f"{name} を {new_name} に変更しました"


@tool("ファイルまたはフォルダを別のフォルダへ移動する",
      name=("string", "移動するもの", True), dest=("string", "移動先フォルダのパスまたは名前", True),
      path=("string", "今ある場所のパス", False))
def move_item(name, dest, path=""):
    import shutil
    src = _guard(_resolve(name, path))
    dst_dir = _guard(_resolve(dest))
    os.makedirs(dst_dir, exist_ok=True)
    shutil.move(src, os.path.join(dst_dir, os.path.basename(src)))
    return f"{name} を {dst_dir} へ移動しました"


@tool("ファイルまたはフォルダを別のフォルダへコピーする",
      name=("string", "コピーするもの", True), dest=("string", "コピー先フォルダのパスまたは名前", True),
      path=("string", "今ある場所のパス", False))
def copy_item(name, dest, path=""):
    import shutil
    src = _resolve(name, path)
    dst_dir = _guard(_resolve(dest))
    dst = os.path.join(dst_dir, os.path.basename(src))
    os.makedirs(dst_dir, exist_ok=True)
    (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, dst)
    return f"{name} を {dst_dir} へコピーしました"


@tool("ファイルまたはフォルダをごみ箱へ移動する(完全には消さない)",
      name=("string", "削除するもの", True), path=("string", "ある場所のパス", False))
def delete_item(name, path=""):
    p = _guard(_resolve(name, path), delete=True)
    if not os.path.exists(p):
        return f"{p} が見つかりません"
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
    if not hit:
        return f"「{title}」の中に「{label}」が見つかりませんでした"
    with screen.Borrow():  # 3. マウスでしか押せない: 手が止まるのを待ってから、少しだけ借りる
        pyautogui.click(hit[1], hit[2])
    return f"「{title}」の「{hit[3]}」をクリックしました"


@screen_tool("type", "直前まで使っていたウィンドウに、文字を入力する(日本語も可)", text=("string", "入力する文字", True))
def type_text(text):
    import screen
    hwnd, title = _target()
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
        p = found[0]
    _guard(p)
    if os.name == "nt":
        os.startfile(p)  # いつものアプリで開く(テキストならメモ帳など)
    else:
        subprocess.Popen(["xdg-open", p])
    return f"{os.path.basename(p)} を開きました（{os.path.dirname(p)}）"
