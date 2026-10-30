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


def _same_app_windows(hwnd):
    """hwnd と同じアプリの、見えている窓すべて(手前の小窓から順に)。"""
    from ctypes import wintypes
    u = _user32()
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    out, h = [], u.GetTopWindow(None)
    while h:
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid.value and u.IsWindowVisible(h):
            out.append(h)
        h = u.GetWindow(h, 2)
    return out or [hwnd]


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
    # 1. 昔ながらのボタンなど(窓の中の小さな窓)から探す(速い)。
    #    同じアプリの小窓(「検索」「保存」などのダイアログ)は別の窓なので、それらの中も探す
    kids = [k for w in _same_app_windows(hwnd) for k in _child_windows(w) if label.lower() in k[0].lower()]
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


# ================= マウスを動かさない操作(見えない2つ目のカーソル) =================
# ボタンや入力欄に直接「押された」「この文字を入れて」と伝えるので、あなたのマウスやキーボードの
# 操作を邪魔しない。直接伝えられないアプリのときだけ、本物のマウス・キーボードを少しだけ借りる。
BM_CLICK, EM_REPLACESEL, WM_VSCROLL, WM_CLOSE = 0x00F5, 0x00C2, 0x0115, 0x0010


def _api():
    from ctypes import wintypes
    u = _user32()
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.SendMessageW.restype = ctypes.c_ssize_t
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetForegroundWindow.restype = wintypes.HWND
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.IsWindowEnabled.argtypes = [wintypes.HWND]
    return u


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(128)
    _api().GetClassNameW(hwnd, buf, 128)
    return buf.value


def children(hwnd):
    """窓の中の小さな窓 [(番号, 名前, 種類)]。"""
    from ctypes import wintypes
    u = _api()
    out = []
    PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def each(h, _):
        if u.IsWindowVisible(h):
            n = u.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, buf, n + 1)
            out.append((h, buf.value.replace("&", ""), class_name(h)))
        return True
    u.EnumChildWindows(wintypes.HWND(hwnd), PROC(each), 0)
    return out


def press_button(hwnd, label):
    """昔ながらのボタンを、マウスを使わずに押す。押せたらボタンの名前を返す。"""
    u = _api()
    key = label.lower()
    cands = [(h, n) for w in _same_app_windows(hwnd) for h, n, c in children(w)
             if key in n.lower() and "button" in c.lower() and u.IsWindowEnabled(h)]
    if not cands:
        return None
    h, name = min(cands, key=lambda c: (c[1].lower() != key, len(c[1])))
    u.PostMessageW(h, BM_CLICK, 0, 0)
    return name


def uia_act(hwnd, label):
    """新しいアプリのボタンなどを、マウスを使わずに押す(UI Automation の「押す」「選ぶ」「開く」)。
    ("done", 名前) / ("pos", x, y, 名前)(マウスでしか押せない) / None(見つからない)"""
    name = label.replace("'", "''")
    script = _UIA.format(hwnd=int(hwnd)) + (
        "$P=[System.Windows.Automation.InvokePattern]::Pattern;"
        "$T=[System.Windows.Automation.TogglePattern]::Pattern;"
        "$S=[System.Windows.Automation.SelectionItemPattern]::Pattern;"
        "$E=[System.Windows.Automation.ExpandCollapsePattern]::Pattern;"
        "$hits=@(); foreach($e in $all){ try { $n=$e.Current.Name;"
        f" if($n -and $n -like '*{name}*'){{ $hits += ,@($n,$e) }} }} catch {{}} }};"
        f"$best = $hits | Sort-Object @{{e={{ if($_[0] -eq '{name}'){{0}}else{{1}} }}}}, @{{e={{ $_[0].Length }}}} "
        "| Select-Object -First 1;"
        "if($best){ $e=$best[1]; $o=$null;"
        " if($e.TryGetCurrentPattern($P,[ref]$o)){ $o.Invoke(); 'DONE|'+$best[0] }"
        " elseif($e.TryGetCurrentPattern($T,[ref]$o)){ $o.Toggle(); 'DONE|'+$best[0] }"
        " elseif($e.TryGetCurrentPattern($S,[ref]$o)){ $o.Select(); 'DONE|'+$best[0] }"
        " elseif($e.TryGetCurrentPattern($E,[ref]$o)){ $o.Expand(); 'DONE|'+$best[0] }"
        " else { $r=$e.Current.BoundingRectangle;"
        "  'POS|{0}|{1}|{2}' -f [int]($r.X+$r.Width/2),[int]($r.Y+$r.Height/2),$best[0] } }"
    )
    out = _ps(script, timeout=30).splitlines()
    line = out[-1] if out else ""
    if line.startswith("DONE|"):
        return ("done", line[5:])
    if line.startswith("POS|"):
        _, x, y, n = line.split("|", 3)
        return ("pos", int(x), int(y), n)
    return None


def _edit_of(hwnd):
    """窓の中の文字入力欄(昔ながらの Edit・RichEdit)。"""
    for w in _same_app_windows(hwnd):
        for h, _, c in children(w):
            if c.lower() == "edit" or c.lower().startswith("richedit"):
                return h
    return None


def insert_text(hwnd, text):
    """入力欄に、マウスもキーボードも使わずに文字を入れる(いまのカーソルの位置に)。できたら True。"""
    edit = _edit_of(hwnd)
    if not edit:
        return False
    _api().SendMessageW(edit, EM_REPLACESEL, 1, ctypes.c_wchar_p(text))
    return True


def scroll_window(hwnd, down, lines):
    """マウスを使わずにスクロールする。できたら True。"""
    target = _edit_of(hwnd) or hwnd
    u = _api()
    for _ in range(lines * 3):
        u.SendMessageW(target, WM_VSCROLL, 1 if down else 0, None)  # SB_LINEDOWN / SB_LINEUP
    return True if _edit_of(hwnd) else False


# ---- 本物のマウス・キーボードを少しだけ借りる(あなたの操作を優先する) ----
def idle_seconds():
    """あなたが最後にマウスやキーボードを触ってからの秒数。"""
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO))
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return max(0, (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


class Borrow:
    """with Borrow(): の間だけマウス・キーボードを借りる。
    あなたが操作している間は待ち(手が止まってから)、終わったらマウスの位置と、使っていた窓を元に戻す。"""

    def __init__(self, idle=1.2, timeout=20):
        self.idle, self.timeout = idle, timeout

    def __enter__(self):
        import config
        import pyautogui
        if getattr(config, "SCREEN_WAIT_IDLE", True):
            start = time.monotonic()
            while idle_seconds() < self.idle:
                if time.monotonic() - start > self.timeout:
                    raise TimeoutError("あなたがマウスやキーボードを操作中のため、待ちきれませんでした。"
                                       "手が空いたら、もう一度頼んでください")
                time.sleep(0.2)
        self.pos = pyautogui.position()
        self.front = _api().GetForegroundWindow()
        return self

    def __exit__(self, *exc):
        import pyautogui
        try:
            pyautogui.moveTo(*self.pos)  # マウスを元の位置へ
            if self.front:
                _user32().SetForegroundWindow(self.front)  # 使っていた窓へ戻す
        except Exception:
            pass
        return False


# ---- 窓の操作 ----
def find_window(name):
    """題名に name を含む、見えている窓 (番号, 題名)。"""
    from ctypes import wintypes
    u = _user32()
    ours = {os.getpid(), os.getppid()}
    key = name.lower()
    best = None
    h = u.GetTopWindow(None)
    while h:
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        n = u.GetWindowTextLengthW(h)
        if pid.value not in ours and u.IsWindowVisible(h) and n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, buf, n + 1)
            if key in buf.value.lower():
                best = best or (h, buf.value)
        h = u.GetWindow(h, 2)
    return best or (None, "")


def window_command(hwnd, action):
    u = _api()
    if action == "close":
        u.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    else:
        u.ShowWindow(hwnd, {"minimize": 6, "maximize": 3, "restore": 9}[action])


def bring_front(hwnd):
    u = _api()
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)
    focus(hwnd)
