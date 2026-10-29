"""AIが呼び出せるPC操作関数(Tool Call)。重いライブラリは関数内で読み込む。"""
import os
import subprocess
import urllib.parse
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


def schemas():
    return [s for _, s in TOOLS.values()]


def run_tool(name, args):
    if name not in TOOLS:
        return f"エラー: 不明な関数 {name}"
    func, schema = TOOLS[name]
    props = schema["function"]["parameters"]["properties"]
    args = {k: v for k, v in (args or {}).items() if k in props}
    if config.DRY_RUN:
        return f"[DRY] {name}({args})"
    try:
        return func(**args)
    except Exception as e:  # 関数の失敗はAIへの返答として扱う
        return f"エラー: {name}: {e}"


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


def _open(url):
    path = _browser_path()
    if path:
        subprocess.Popen([path, url])
    else:
        webbrowser.open(url)


@tool("ブラウザで指定URLを開く", url=("string", "開くURL", True))
def open_url(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    _open(url)
    return f"{url} を開きました"


@tool("ブラウザで検索結果のページを開く(「ブラウザで検索して」など画面で見たいとき)",
      query=("string", "検索キーワード", True))
def web_search(query):
    _open(config.SEARCH_URL.format(urllib.parse.quote_plus(query)))
    return f"「{query}」を検索しました"


@tool("Webで調べて結果を要約して答える(「〜について調べて」「〜を教えて」など)",
      query=("string", "調べる内容", True))
def search_summary(query):
    import llm
    import websearch
    results = websearch.search(query)
    if not results:
        return f"「{query}」の検索結果を取得できませんでした"
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(1) as ex:
        pics = ex.submit(lambda: _safe(websearch.images, query, 8))  # 関連画像も同時に探す
        docs = websearch.read_pages(results)
        summary = llm.summarize(query, results[:len(docs)], docs) or results[0]["snippet"]
    links = "\n".join(f"[{i}] {r['title']}\n{r['url']}" for i, r in enumerate(results[:len(docs)], 1))
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
        return f"「{query}」の画像が見つかりませんでした"
    return f"「{query}」の画像を{len(found)}枚見つけました。一覧を表示します。" + _images_part(query, found, True)


# ---------------- アプリ ----------------
@tool("PCにインストールされたアプリやソフトを名前で起動する(例: Excel、メモ帳、Spotify)",
      name=("string", "アプリの名前", True))
def launch_app(name):
    import apps
    return apps.launch(name)


# ---------------- ファイル・フォルダ ----------------
_HOME = os.path.expanduser("~")
_KNOWN = {  # よく使うフォルダの呼び名
    "デスクトップ": config.DESKTOP, "desktop": config.DESKTOP,
    "ドキュメント": os.path.join(_HOME, "Documents"), "documents": os.path.join(_HOME, "Documents"),
    "ダウンロード": os.path.join(_HOME, "Downloads"), "downloads": os.path.join(_HOME, "Downloads"),
    "ピクチャ": os.path.join(_HOME, "Pictures"), "画像": os.path.join(_HOME, "Pictures"),
    "ミュージック": os.path.join(_HOME, "Music"), "ビデオ": os.path.join(_HOME, "Videos"),
}


def _base(path):
    if not path:
        return config.DESKTOP
    return _KNOWN.get(path.strip().lower(), os.path.expandvars(os.path.expanduser(path)))


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


@tool("テキストファイル(.txt)を作成または上書きする(場所の指定が無ければデスクトップ)",
      name=("string", "ファイル名", True), content=("string", "書き込む内容", False),
      path=("string", "保存場所のパス", False))
def create_text_file(name, content="", path=""):
    if not name.lower().endswith(".txt"):
        name += ".txt"
    p = _guard(_resolve(name, path))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return f"ファイル {p} を作成しました"


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
