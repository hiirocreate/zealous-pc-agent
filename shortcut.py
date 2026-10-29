"""自動起動(スタートアップのショートカット)と起動コマンド。コンソール画面は出さない。"""
import os
import subprocess
import sys

FROZEN = getattr(sys, "frozen", False)  # Zealous.exe として配布されているか
HERE = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
LAUNCHER = os.path.join(HERE, "zealous.pyw")
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "zealous.ico")
NAME = "Zealous.lnk"
STARTUP_DIR = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")


def pythonw():
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return exe if os.path.exists(exe) else sys.executable


def command(*args):
    """Zealous を起動するコマンド(exe 版 / ソース版)。"""
    return [sys.executable, *args] if FROZEN else [pythonw(), LAUNCHER, *args]


def uninstaller():
    """exe 版はインストーラーが置いたアンインストーラー、ソース版は無し。"""
    p = os.path.join(HERE, "unins000.exe")
    return p if FROZEN and os.path.exists(p) else None


def create(folder):
    cmd = command()
    q = lambda s: s.replace("'", "''")
    args = " ".join(f'"{a}"' for a in cmd[1:])
    script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(os.path.join(folder, NAME))}');"
              f"$s.TargetPath='{q(cmd[0])}';$s.Arguments='{q(args)}';"
              f"$s.WorkingDirectory='{q(HERE)}';$s.IconLocation='{q(ICON)}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                   check=True, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def is_autostart():
    return os.path.exists(os.path.join(STARTUP_DIR, NAME))


def set_autostart(enabled):
    if os.name != "nt":
        return
    path = os.path.join(STARTUP_DIR, NAME)
    if enabled and not os.path.exists(path):
        create(STARTUP_DIR)
    elif not enabled and os.path.exists(path):
        os.remove(path)
