"""日本語入力(IME)を、チャット欄の中でそのまま行えるようにする(Windows)。

Tk は変換中の文字を Windows 標準の白い枠で表示してしまうため、
- 標準の枠を出さないよう Windows に伝え、変換中の文字は入力欄の中に下線付きで直接描く
- 変換候補の一覧はカーソルのすぐ下に出す
確定した文字は、これまで通り Tk が入力欄に入れる。"""
import ctypes
import os

WM_IME_SETCONTEXT = 0x0281
WM_IME_STARTCOMPOSITION = 0x010D
WM_IME_ENDCOMPOSITION = 0x010E
WM_IME_COMPOSITION = 0x010F
GCS_COMPSTR, GCS_CURSORPOS, GCS_RESULTSTR = 0x0008, 0x0080, 0x0800
ISC_SHOWUICOMPOSITIONWINDOW = 0x80000000
CFS_CANDIDATEPOS = 0x0040
GWLP_WNDPROC = -4
TAG = "ime_preedit"

_keep = []  # Windows に渡した関数を、消されないよう持っておく


def attach(text, font_family, font_px):
    """text(tk.Text) で日本語入力するとき、変換中の文字を入力欄の中に描く。"""
    if os.name != "nt":
        return
    from ctypes import wintypes
    user32, imm = ctypes.WinDLL("user32"), ctypes.WinDLL("imm32")
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class CANDIDATEFORM(ctypes.Structure):
        _fields_ = [("dwIndex", wintypes.DWORD), ("dwStyle", wintypes.DWORD),
                    ("ptCurrentPos", wintypes.POINT), ("rcArea", wintypes.RECT)]

    user32.GetFocus.restype = wintypes.HWND
    user32.SendMessageW.restype = LRESULT
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.GetWindowLongPtrW.restype = ctypes.c_void_p
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.CallWindowProcW.restype = LRESULT
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                       wintypes.LPARAM]
    imm.ImmGetContext.restype = wintypes.HANDLE
    imm.ImmGetContext.argtypes = [wintypes.HWND]
    imm.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
    imm.ImmGetCompositionStringW.restype = ctypes.c_long
    imm.ImmGetCompositionStringW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    imm.ImmSetCandidateWindow.argtypes = [wintypes.HANDLE, ctypes.POINTER(CANDIDATEFORM)]

    text.tag_configure(TAG, underline=True)
    state = {"focused": False, "hooked": set()}

    def composition(hwnd, kind):
        himc = imm.ImmGetContext(hwnd)
        if not himc:
            return "", 0
        try:
            size = imm.ImmGetCompositionStringW(himc, kind, None, 0)
            buf = ctypes.create_unicode_buffer(size // 2 + 1)
            if size > 0:
                imm.ImmGetCompositionStringW(himc, kind, buf, size)
            cursor = imm.ImmGetCompositionStringW(himc, GCS_CURSORPOS, None, 0)
            return buf.value, max(0, cursor)
        finally:
            imm.ImmReleaseContext(hwnd, himc)

    def clear_preedit():
        ranges = text.tag_ranges(TAG)
        if ranges:
            text.delete(ranges[0], ranges[-1])

    def show_preedit(s, cursor):
        clear_preedit()
        start = text.index("insert")
        if s:
            text.insert(start, s, TAG)
            text.mark_set("insert", f"{start}+{min(cursor, len(s))}c")
        text.see("insert")
        text.event_generate("<<ImePreedit>>")  # 入力欄の高さの調整などに使う

    def place_candidates(hwnd):
        box = text.bbox("insert")
        himc = imm.ImmGetContext(hwnd)
        if not box or not himc:
            return
        try:
            pt = wintypes.POINT(text.winfo_rootx() + box[0], text.winfo_rooty() + box[1] + box[3] + 4)
            user32.ScreenToClient(hwnd, ctypes.byref(pt))
            imm.ImmSetCandidateWindow(himc, ctypes.byref(CANDIDATEFORM(0, CFS_CANDIDATEPOS, pt)))
        finally:
            imm.ImmReleaseContext(hwnd, himc)

    def hook(hwnd):
        """入力を受け取る窓の処理に割り込む(日本語入力の知らせだけを横取りする)。"""
        old = user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC)

        def proc(h, msg, wparam, lparam):
            try:
                if state["focused"]:
                    if msg == WM_IME_SETCONTEXT and wparam:
                        lparam &= ~ISC_SHOWUICOMPOSITIONWINDOW  # 標準の白い枠を出さない
                    elif msg == WM_IME_STARTCOMPOSITION:
                        place_candidates(h)
                        return 0
                    elif msg == WM_IME_COMPOSITION:
                        if lparam & GCS_RESULTSTR:  # 確定: 下書きを消し、確定文字は Tk に入れてもらう
                            clear_preedit()
                        elif lparam & GCS_COMPSTR:
                            show_preedit(*composition(h, GCS_COMPSTR))
                            place_candidates(h)
                            return 0
                    elif msg == WM_IME_ENDCOMPOSITION:
                        clear_preedit()
            except Exception:
                pass  # うまくいかなくても、通常の入力はできるようにする
            return user32.CallWindowProcW(old, h, msg, wparam, lparam)

        cb = WNDPROC(proc)
        _keep.append(cb)
        user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(cb, ctypes.c_void_p))
        state["hooked"].add(hwnd)

    def focus_in(_=None):
        state["focused"] = True
        hwnd = user32.GetFocus()
        if hwnd and hwnd not in state["hooked"]:
            try:
                hook(hwnd)
                # 初めて入力欄に来たときは、標準の枠を出さない設定をもう一度伝える
                user32.SendMessageW(hwnd, WM_IME_SETCONTEXT, 1, 0xC000000F)
            except Exception:
                pass

    def focus_out(_=None):
        state["focused"] = False
        clear_preedit()

    text.bind("<FocusIn>", focus_in, add="+")
    text.bind("<FocusOut>", focus_out, add="+")
