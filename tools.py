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


@tool("ブラウザでキーワード検索する", query=("string", "検索キーワード", True))
def web_search(query):
    _open(config.SEARCH_URL.format(urllib.parse.quote_plus(query)))
    return f"「{query}」を検索しました"


# ---------------- ファイル・フォルダ ----------------
def _resolve(name, path):
    base = os.path.expandvars(os.path.expanduser(path)) if path else config.DESKTOP
    return os.path.join(base, name)


@tool("フォルダを作成する(場所の指定が無ければデスクトップ)",
      name=("string", "フォルダ名", True), path=("string", "作成場所のパス", False))
def create_folder(name, path=""):
    p = _resolve(name, path)
    os.makedirs(p, exist_ok=True)
    return f"フォルダ {p} を作成しました"


@tool("テキストファイル(.txt)を作成または上書きする(場所の指定が無ければデスクトップ)",
      name=("string", "ファイル名", True), content=("string", "書き込む内容", False),
      path=("string", "保存場所のパス", False))
def create_text_file(name, content="", path=""):
    if not name.lower().endswith(".txt"):
        name += ".txt"
    p = _resolve(name, path)
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
