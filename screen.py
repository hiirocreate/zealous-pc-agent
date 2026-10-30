"""画面の直接操作(マウス・キーボード)。設定の「画面を直接操作する」が ON のときだけ使う。
操作の相手は、Zealous の窓ではなく「直前まで使っていた窓」(いちばん手前にある、ほかのアプリの窓)。"""
import ctypes
import os
import subprocess
import time

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _user32():
    from ctypes import wintypes
    u = ctypes.WinDLL("user32")
    u.GetWindow.restype = wintypes.HWND
    u.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    u.GetTopWindow.restype = wintypes.HWND
    u.GetTopWindow.argtypes = [wintypes.HWND]
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsIconic.argtypes = [wintypes.HWND]
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    return u


def target_window():
    """操作する相手の窓 (番号, 題名)。Zealous 自身の窓・見えない窓・最小化した窓は除く。"""
    from ctypes import wintypes
    u = _user32()
    ours = {os.getpid(), os.getppid()}  # この作業プロセスと、Zealous 本体
    hwnd = u.GetTopWindow(None)
    while hwnd:
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        ex = u.GetWindowLongPtrW(hwnd, -20)  # 拡張スタイル
        n = u.GetWindowTextLengthW(hwnd)
        if (pid.value not in ours and u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd) and n > 0
                and not ex & 0x80):  # WS_EX_TOOLWINDOW(小さな補助の窓)は除く
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value not in ("Program Manager",):
                return hwnd, buf.value
        hwnd = u.GetWindow(hwnd, 2)  # GW_HWNDNEXT: 奥へ
    return None, ""


def focus(hwnd):
    """相手の窓を手前に出して、キー入力を受け取れるようにする。"""
    import pyautogui
    u = _user32()
    pyautogui.press("alt")  # (Windows は、別のアプリが勝手に窓を手前に出すのを止めるため、合図を送ってから)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.25)


def _ps(script, timeout=20):
    script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script  # 日本語の名前も正しく受け取る
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=_NO_WINDOW)
    return (r.stdout or "").strip()


# UIAutomationClientsideProviders: 昔ながらの Windows のボタンやメニューを見つけるための部品(これが無いと見えない)
_UIA = ("Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes,UIAutomationClientsideProviders;"
        "$A=[System.Windows.Automation.AutomationElement];"
        "$w=$A::FromHandle([IntPtr]{hwnd});"
        "$all=$w.FindAll([System.Windows.Automation.TreeScope]::Descendants,"
        "[System.Windows.Automation.Condition]::TrueCondition);")


def _child_windows(hwnd):
    """窓の中の小さな窓(昔ながらのボタンや入力欄)を (名前, 中心x, 中心y) で返す。"""
    from ctypes import wintypes
    u = ctypes.WinDLL("user32")
    out = []
    PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def each(h, _):
        n = u.GetWindowTextLengthW(h)
        if n and u.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, buf, n + 1)
            r = wintypes.RECT()
            u.GetWindowRect(h, ctypes.byref(r))
            if r.right > r.left and r.bottom > r.top:
                out.append((buf.value.replace("&", ""), (r.left + r.right) // 2, (r.top + r.bottom) // 2))
        return True
    u.EnumChildWindows(wintypes.HWND(hwnd), PROC(each), 0)
    return out


def find_control(hwnd, label):
    """窓の中から、名前に label を含むボタンなどを探し、その真ん中の位置 (x, y, 名前) を返す。
    名前がぴったり同じものを優先し、無ければ名前に含むもののうち短い名前のものを選ぶ。"""
    # 1. 昔ながらのボタンなど(窓の中の小さな窓)から探す(速い)
    kids = [k for k in _child_windows(hwnd) if label.lower() in k[0].lower()]
    if kids:
        best = min(kids, key=lambda k: (k[0].lower() != label.lower(), len(k[0])))
        return best[1], best[2], best[0]
    # 2. 画面の部品の情報(UI Automation)から探す(新しいアプリのボタンやメニューも見つかる)
    name = label.replace("'", "''")
    script = _UIA.format(hwnd=int(hwnd)) + (
        "$hits=@(); foreach($e in $all){ try { $n=$e.Current.Name; $r=$e.Current.BoundingRectangle;"
        f" if($n -and $n -like '*{name}*' -and $r.Width -gt 0 -and $r.Height -gt 0)"
        " { $hits += ,@($n, [int]($r.X+$r.Width/2), [int]($r.Y+$r.Height/2)) } } catch {} };"
        f"$best = $hits | Sort-Object @{{e={{ if($_[0] -eq '{name}'){{0}}else{{1}} }}}}, @{{e={{ $_[0].Length }}}} "
        "| Select-Object -First 1;"
        "if($best){ '{0},{1},{2}' -f $best[1],$best[2],$best[0] }"
    )
    out = _ps(script, timeout=30)
    if not out or "," not in out:
        return None
    x, y, found = out.splitlines()[-1].split(",", 2)
    return int(x), int(y), found


def list_controls(hwnd, limit=30):
    """(確認用) 窓の中で名前を持つ部品の数と、最初のいくつかの名前。"""
    script = _UIA.format(hwnd=int(hwnd)) + (
        "$names=@(); foreach($e in $all){ try { if($e.Current.Name){ $names += $e.Current.Name } } catch {} };"
        f"'{{0}}|{{1}}' -f $all.Count, (($names | Select-Object -First {limit}) -join ' / ')"
    )
    return _ps(script, timeout=30)


def paste_text(text):
    """文字を入力する(日本語も入るよう、クリップボード経由で貼り付ける。元のクリップボードは戻す)。"""
    import pyautogui
    old = _ps("Get-Clipboard -Raw")
    safe = text.replace("'", "''")
    _ps(f"Set-Clipboard -Value '{safe}'")
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)
    if old:
        _ps("Set-Clipboard -Value '" + old.replace("'", "''") + "'")
