"""メールの設定(IMAP)をしていないときに、PCの Thunderbird を目立たないように操作する。
Thunderbird の窓は画面の外・いちばん奥に置いたまま、フォルダを選んで「フォルダーを既読にする」(Shift+C)を送る。
キーを送る一瞬だけ、あなたの手が止まるのを待ってから借り、終わったら使っていた窓へ戻す。"""
import os
import subprocess
import time

import config

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def exe():
    if os.name != "nt":
        return None
    import tools
    path = tools.app_path("thunderbird.exe")
    for base in (path and os.path.dirname(path), os.path.join(os.environ.get("ProgramFiles", ""), "Mozilla Thunderbird"),
                 os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Mozilla Thunderbird")):
        if base and os.path.exists(os.path.join(base, "thunderbird.exe")):
            return os.path.join(base, "thunderbird.exe")
    return None


def window():
    """Thunderbird のいちばん上の窓(番号) または None。"""
    import ctypes
    from ctypes import wintypes
    import screen
    u = screen._user32()
    h = u.GetTopWindow(None)
    while h:
        n = u.GetWindowTextLengthW(h)
        if n and u.IsWindowVisible(h) and screen.class_name(h) == "MozillaWindowClass":
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, buf, n + 1)
            if "Thunderbird" in buf.value:
                return h
        h = u.GetWindow(h, 2)
    del wintypes
    return None


class Hidden:
    """with Hidden(hwnd): の間、窓を画面の外・いちばん奥に置く(作業が見えないように)。終わったら元の位置へ。"""

    def __init__(self, hwnd):
        self.hwnd = hwnd

    def __enter__(self):
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        self.rect = wintypes.RECT()
        u.GetWindowRect(self.hwnd, ctypes.byref(self.rect))
        self.zoomed = bool(u.IsZoomed(self.hwnd))
        if self.zoomed:
            u.ShowWindow(self.hwnd, 4)  # SW_SHOWNOACTIVATE: 最大化を解かないと動かせない
        u.SetWindowPos(self.hwnd, 1, -32000, -32000, 0, 0, 0x0001 | 0x0010)  # HWND_BOTTOM, NOSIZE|NOACTIVATE
        return self

    def __exit__(self, *exc):
        import ctypes
        u = ctypes.windll.user32
        r = self.rect
        u.SetWindowPos(self.hwnd, 1, r.left, r.top, 0, 0, 0x0001 | 0x0010)
        if self.zoomed:
            u.ShowWindow(self.hwnd, 3)  # SW_MAXIMIZE
            u.SetWindowPos(self.hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # また奥へ
        return False


_TREE = ("$W=[System.Windows.Automation.TreeWalker]::ControlViewWalker;"
         "$TI=[System.Windows.Automation.ControlType]::TreeItem;"
         "$items=@($all | Where-Object { try { $_.Current.ControlType -eq $TI } catch { $false } });")


def folders(hwnd):
    """フォルダ一覧の項目 [(番号, 名前, 上の階層の名前)]。"""
    import screen
    script = screen._UIA.format(hwnd=int(hwnd)) + _TREE + (
        "for($i=0; $i -lt $items.Count; $i++){ $e=$items[$i]; $p=$W.GetParent($e); $up='';"
        " while($p -and $p.Current.ControlType -eq $TI){ $up=$p.Current.Name+'/'+$up; $p=$W.GetParent($p) };"
        " '{0}|{1}|{2}' -f $i, $e.Current.Name, $up }")
    out = []
    for line in screen._ps(script, timeout=60).splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3 and parts[0].isdigit():
            out.append((int(parts[0]), parts[1], parts[2].rstrip("/")))
    return out


def _select(hwnd, index):
    import screen
    script = screen._UIA.format(hwnd=int(hwnd)) + _TREE + (
        f"$e=$items[{int(index)}]; $o=$null;"
        "if($e.TryGetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern,[ref]$o)){ $o.ScrollIntoView() };"
        "if($e.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$o)){ $o.Select(); 'OK' }"
        "elseif($e.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$o)){ $o.Invoke(); 'OK' }")
    return screen._ps(script, timeout=60).strip().endswith("OK")


def mark_read(query):
    """Thunderbird で、フォルダのメールをすべて既読にする。"""
    import mail
    import tools
    path = exe()
    if not path:
        return None
    hwnd, launched = window(), False
    if not hwnd:  # 起動していなければ起動する(終わったら閉じる)
        subprocess.Popen([path], creationflags=_NO_WINDOW)
        launched = True
        for _ in range(60):
            time.sleep(0.5)
            hwnd = window()
            if hwnd:
                break
        if not hwnd:
            return "Thunderbird を起動できませんでした"
        time.sleep(4)  # フォルダの一覧ができるのを待つ
    try:
        with Hidden(hwnd):
            items = folders(hwnd)
            hits = _match(query, items, mail)
            if not hits:
                return f"Thunderbird のフォルダの中に「{query}」が見つかりませんでした"
            if len(hits) > 1:
                return tools.ask_choice(
                    f"「{query}」に当てはまるフォルダが{len(hits)}つあります。どれにしますか？", "mail_mark_read", "folder",
                    [f"{up}/{name}" if up else name for _, name, up in hits[:6]],
                    [f"{name}（{up}）" if up else name for _, name, up in hits[:6]])
            index, name, up = hits[0]
            if not _select(hwnd, index):
                return f"Thunderbird の「{name}」を選べませんでした"
            import pyautogui
            import screen
            with screen.Borrow():  # キーを送る一瞬だけ借りる(窓は画面の外なので見えない)
                screen.focus(hwnd)
                time.sleep(0.3)
                pyautogui.hotkey("shift", "c")  # フォルダーを既読にする
                time.sleep(0.5)
        return f"Thunderbird の「{name}」のメールを、すべて既読にしました（画面の外で操作しました）"
    finally:
        if launched:
            import ctypes
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # 自分で起動したものは閉じる(WM_CLOSE)


def _match(query, items, mail):
    """呼び名に合うフォルダの項目。「迷惑メール」→ 迷惑メール・Junk・スパム など。「仕事/迷惑メール」のような道筋も可。"""
    q = mail._norm(str(query))
    whole = [it for it in items if mail._norm(f"{it[2]}/{it[1]}" if it[2] else it[1]) == q]
    if whole:
        return whole
    q = mail._norm(str(query).split("/")[-1])
    for k, (_, _, words) in mail.SPECIAL.items():
        if any(mail._norm(w) in q for w in words):
            return [it for it in items if any(mail._norm(w) in mail._norm(it[1]) for w in words)]
    exact = [it for it in items if mail._norm(it[1]).split("(")[0] == q]
    return exact or [it for it in items if q and q in mail._norm(it[1])]
