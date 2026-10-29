"""デスクトップ / スタートアップのショートカット作成(コンソール画面を出さずに実行)。"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.join(HERE, "zealous.pyw")
ICON = os.path.join(HERE, "assets", "zealous.ico")
NAME = "Zealous.lnk"
STARTUP_DIR = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")


def pythonw():
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return exe if os.path.exists(exe) else sys.executable


def create(folder):
    q = lambda s: s.replace("'", "''")
    script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(os.path.join(folder, NAME))}');"
              f"$s.TargetPath='{q(pythonw())}';$s.Arguments='\"{q(LAUNCHER)}\"';"
              f"$s.WorkingDirectory='{q(HERE)}';$s.IconLocation='{q(ICON)}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                   check=True, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def set_autostart(enabled):
    if os.name != "nt":
        return
    path = os.path.join(STARTUP_DIR, NAME)
    if enabled:
        create(STARTUP_DIR)
    elif os.path.exists(path):
        os.remove(path)
