"""ファイル・フォルダを窓へドラッグ＆ドロップしたり、エクスプローラーでコピーして貼り付けたりして添付する(Windows)。"""
import ctypes
import os
import queue

WM_DROPFILES = 0x0233
_keep = []


def _api():
    from ctypes import wintypes
    user32, shell32 = ctypes.WinDLL("user32"), ctypes.WinDLL("shell32")
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell32.DragFinish.argtypes = [wintypes.HANDLE]
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.GetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetWindowLongPtrW.restype = ctypes.c_void_p
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetClipboardData.restype = wintypes.HANDLE
    return user32, shell32


def _paths(shell32, hdrop):
    n = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
    out = []
    for i in range(n):
        size = shell32.DragQueryFileW(hdrop, i, None, 0) + 1
        buf = ctypes.create_unicode_buffer(size)
        shell32.DragQueryFileW(hdrop, i, buf, size)
        out.append(buf.value)
    return out


def enable(widget, on_files):
    """widget の窓へのドロップを受け取る。on_files(パスの一覧) は Tk の側で呼ぶ。"""
    if os.name != "nt":
        return
    from ctypes import wintypes
    user32, shell32 = _api()
    hwnd = user32.GetParent(widget.winfo_id()) or widget.winfo_id()
    got = queue.Queue()
    old = user32.GetWindowLongPtrW(hwnd, -4)
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    def proc(h, msg, wparam, lparam):
        # Windows から直接呼ばれるので、ここでは Tk に触らず、受け取ったパスを積むだけにする
        if msg == WM_DROPFILES:
            try:
                got.put(_paths(shell32, wparam))
                shell32.DragFinish(wparam)
            except Exception:
                pass
            return 0
        return user32.CallWindowProcW(old, h, msg, wparam, lparam)

    cb = WNDPROC(proc)
    _keep.append(cb)
    user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(cb, ctypes.c_void_p))
    shell32.DragAcceptFiles(hwnd, True)

    def pump():
        while not got.empty():
            on_files(got.get())
        widget.after(120, pump)
    pump()


def clipboard_files():
    """エクスプローラーでコピーしたファイル・フォルダのパス(無ければ空)。"""
    if os.name != "nt":
        return []
    user32, shell32 = _api()
    if not user32.IsClipboardFormatAvailable(15):  # CF_HDROP
        return []
    if not user32.OpenClipboard(None):
        return []
    try:
        h = user32.GetClipboardData(15)
        return _paths(shell32, h) if h else []
    finally:
        user32.CloseClipboard()
