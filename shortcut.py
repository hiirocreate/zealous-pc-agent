"""ショートカット・自動起動・「アプリ」一覧への登録(コンソール画面を出さずに実行)。"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.join(HERE, "zealous.pyw")
UNINSTALLER = os.path.join(HERE, "uninstall.pyw")
ICON = os.path.join(HERE, "assets", "zealous.ico")
NAME = "Zealous.lnk"
_PROGRAMS = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")
STARTUP_DIR = os.path.join(_PROGRAMS, "Startup")
START_MENU_DIR = _PROGRAMS
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Zealous"
VERSION = "1.0.0"


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


def remove(folder):
    path = os.path.join(folder, NAME)
    if os.path.exists(path):
        os.remove(path)


def set_autostart(enabled):
    if os.name != "nt":
        return
    if enabled:
        create(STARTUP_DIR)
    else:
        remove(STARTUP_DIR)


def register_app():
    """Windows の「設定 > アプリ」に登録し、そこからアンインストールできるようにする。"""
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, value in {
            "DisplayName": "Zealous", "DisplayVersion": VERSION, "Publisher": "Zealous",
            "DisplayIcon": ICON, "InstallLocation": HERE,
            "UninstallString": f'"{pythonw()}" "{UNINSTALLER}"',
        }.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        for name in ("NoModify", "NoRepair"):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 1)


def unregister_app():
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
