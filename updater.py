"""アップデート: GitHub Releases の最新版を確認し、インストーラーを裏で実行して入れ替える。
設定・ダウンロード済みの部品(AIモデル等)はそのまま引き継がれる。"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

import config
import runtime
from version import VERSION

FROZEN = getattr(sys, "frozen", False)
ASSET = "ZealousSetup.exe"


def _ver(text):
    nums = []
    for part in text.lstrip("vV").split("."):
        digits = "".join(c for c in part if c.isdigit())
        nums.append(int(digits or 0))
    return tuple(nums + [0] * (3 - len(nums)))


def check():
    """新しい版があれば {"version", "url", "notes"} を、無ければ None を返す。"""
    req = urllib.request.Request(f"https://api.github.com/repos/{config.UPDATE_REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "Zealous"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            rel = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(f"配布元（{config.UPDATE_REPO}）にまだ公開された版がありません") from e
        raise
    latest = rel.get("tag_name", "")
    if _ver(latest) <= _ver(VERSION):
        return None
    url = next((a["browser_download_url"] for a in rel.get("assets", []) if a["name"] == ASSET), None)
    if not url:
        return None
    return {"version": latest.lstrip("vV"), "url": url, "notes": (rel.get("body") or "").strip()}


def install(info, progress):
    """インストーラーを取得して静かに実行する。呼び出し側はこの後すぐ終了すること。"""
    if not FROZEN:
        raise RuntimeError("ソース版は git pull で更新してください")
    dest = os.path.join(tempfile.gettempdir(), f"ZealousSetup-{info['version']}.exe")
    runtime.download(info["url"], dest, progress)
    # Zealous が完全に終わってからインストーラーを動かす(動いたままだとファイルを置き換えられない)。
    # 待つ役は別のプロセス(PowerShell)に任せ、Zealous はこの後すぐ終了する。
    # 終わったら自動で起動し直す(installer.iss の [Run] 参照)。記録は設定フォルダの update.log に残す。
    log = os.path.join(config.APP_DIR, "update.log")
    q = lambda p: "'" + p.replace("'", "''") + "'"
    log_arg = q('/LOG="' + log + '"')
    script = (f"Wait-Process -Id {os.getpid()} -Timeout 30 -ErrorAction SilentlyContinue; "
              "Get-Process -Name Zealous -ErrorAction SilentlyContinue | Stop-Process -Force; "
              "Start-Sleep -Milliseconds 800; "
              f"Start-Process -FilePath {q(dest)} -ArgumentList "
              f"'/SILENT','/NORESTART','/NOCLOSEAPPLICATIONS',{log_arg}")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    import base64  # 引用符の扱いで壊れないよう、命令は符号化して渡す
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                      "-EncodedCommand", encoded],
                     cwd=tempfile.gettempdir(), creationflags=flags)
