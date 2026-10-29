"""PC のアプリを名前で探して起動する。スタートメニューに載っているアプリ(ストアアプリ含む)が対象。"""
import difflib
import json
import os
import subprocess
import unicodedata

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# スタートメニューに無い / 呼び方が違う定番のもの: 呼び名 -> 起動するもの
BUILTIN = {
    "メモ帳": "notepad.exe", "notepad": "notepad.exe",
    "電卓": "calc.exe", "計算機": "calc.exe", "calculator": "calc.exe",
    "エクスプローラー": "explorer.exe", "エクスプローラ": "explorer.exe", "explorer": "explorer.exe",
    "設定": "ms-settings:", "windowsの設定": "ms-settings:",
    "タスクマネージャー": "taskmgr.exe", "タスクマネージャ": "taskmgr.exe",
    "コントロールパネル": "control.exe", "ペイント": "mspaint.exe", "paint": "mspaint.exe",
    "コマンドプロンプト": "cmd.exe", "パワーシェル": "powershell.exe", "powershell": "powershell.exe",
}
# よく使う英語名の日本語の呼び方(スタートメニュー上の名前に合わせる)
ALIASES = {
    "エクセル": "excel", "ワード": "word", "パワーポイント": "powerpoint", "パワポ": "powerpoint",
    "アウトルック": "outlook", "チームズ": "teams", "クローム": "chrome", "エッジ": "edge",
    "ファイアフォックス": "firefox", "スポティファイ": "spotify", "ディスコード": "discord",
    "ライン": "line", "ズーム": "zoom", "スラック": "slack", "ブイエスコード": "visual studio code",
    "スチーム": "steam", "vscode": "visual studio code", "フォト": "フォト", "カメラ": "カメラ", "時計": "時計",
}

_cache = None


def _norm(s):
    return unicodedata.normalize("NFKC", s).lower().replace(" ", "").replace("　", "")


def start_apps():
    """スタートメニューのアプリ一覧 [{"Name", "AppID"}](1回だけ取得して使い回す)。"""
    global _cache
    if _cache is None:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                            "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"],
                           capture_output=True, text=True, encoding="utf-8", creationflags=_NO_WINDOW, timeout=30)
        data = json.loads(r.stdout or "[]")
        _cache = data if isinstance(data, list) else [data]
    return _cache


def find(name, apps):
    """呼び名に最も近いアプリを返す(見つからなければ None)。"""
    key = _norm(ALIASES.get(_norm(name), name))
    names = [(_norm(a["Name"]), a) for a in apps]
    for test in (lambda n: n == key, lambda n: n.startswith(key), lambda n: key in n):
        hits = [a for n, a in names if test(n)]
        if hits:
            return min(hits, key=lambda a: len(a["Name"]))  # 余計な語の少ない名前を優先
    close = difflib.get_close_matches(key, [n for n, _ in names], n=1, cutoff=0.6)
    return next(a for n, a in names if n == close[0]) if close else None


def launch(name):
    builtin = BUILTIN.get(_norm(name))
    if builtin:
        os.startfile(builtin)
        return f"{name} を起動しました"
    app = find(name, start_apps())
    if not app:
        return f"「{name}」というアプリが見つかりませんでした"
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app['AppID']}"], creationflags=_NO_WINDOW)
    return f"{app['Name']} を起動しました"
