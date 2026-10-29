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
CFS_POINT, CFS_CANDIDATEPOS, CFS_EXCLUDE = 0x0002, 0x0040, 0x0080
WM_IME_NOTIFY, WM_IME_REQUEST = 0x0282, 0x0288
IMN_OPENCANDIDATE, IMN_CHANGECANDIDATE = 0x0005, 0x0003
IMR_COMPOSITIONWINDOW, IMR_CANDIDATEWINDOW, IMR_QUERYCHARPOSITION = 0x0001, 0x0002, 0x0006
GWLP_WNDPROC = -4
TAG = "ime_preedit"

_keep = []  # Windows に渡した関数を、消されないよう持っておく


def attach(text, font_family, font_px):
    """text(tk.Text) で日本語入力するとき、変換中の文字を入力欄の中に描く。"""
    import config
    if os.name != "nt" or not getattr(config, "IME_INLINE", True):
        return
    from ctypes import wintypes
    user32, imm = ctypes.WinDLL("user32"), ctypes.WinDLL("imm32")
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class CANDIDATEFORM(ctypes.Structure):
        _fields_ = [("dwIndex", wintypes.DWORD), ("dwStyle", wintypes.DWORD),
                    ("ptCurrentPos", wintypes.POINT), ("rcArea", wintypes.RECT)]

    class COMPOSITIONFORM(ctypes.Structure):
        _fields_ = [("dwStyle", wintypes.DWORD), ("ptCurrentPos", wintypes.POINT), ("rcArea", wintypes.RECT)]

    class IMECHARPOSITION(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("dwCharPos", wintypes.DWORD), ("pt", wintypes.POINT),
                    ("cLineHeight", wintypes.UINT), ("rcDocument", wintypes.RECT)]

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
    imm.ImmSetCompositionWindow.argtypes = [wintypes.HANDLE, ctypes.POINTER(COMPOSITIONFORM)]

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

    # 日本語入力からの「文字はどこ？」という問い合わせは、Tk が入力欄を描いている最中にも届く。
    # その最中に入力欄を調べると Tk が壊れて強制終了するので、位置は普段のうちに調べて覚えておき、
    # 問い合わせには覚えた値だけで答える。
    cache = {"caret": None, "chars": [], "doc": None}

    def remember(_=None):
        try:
            box = text.bbox("insert")
            x0, y0 = text.winfo_rootx(), text.winfo_rooty()
            cache["doc"] = (x0, y0, x0 + text.winfo_width(), y0 + text.winfo_height())
            cache["caret"] = (x0 + box[0], y0 + box[1], box[3]) if box else None
            chars = []
            ranges = text.tag_ranges(TAG)
            if ranges:
                n = len(text.get(ranges[0], ranges[-1]))
                for i in range(n + 1):
                    b = text.bbox(f"{ranges[0]}+{i}c")
                    if b:
                        chars.append((x0 + b[0], y0 + b[1], b[3]))
            cache["chars"] = chars
        except Exception:
            pass

    def remember_later(_=None):
        text.after_idle(remember)

    def client_rect(hwnd, x, y, h):
        """画面上の位置を、窓の中の位置に直す。行の上下を (左, 上, 右, 下) で返す。"""
        pt = wintypes.POINT(x, y)
        user32.ScreenToClient(hwnd, ctypes.byref(pt))
        return pt.x, pt.y, pt.x + 2, pt.y + h

    def candidate_form(hwnd):
        """変換候補・予測候補の一覧が、入力中の行に重ならないようにする指定(行の下、入らなければ上)。"""
        cb = cache["caret"]
        if not cb:
            return None
        l, t, r, b = client_rect(hwnd, *cb)
        return CANDIDATEFORM(0, CFS_EXCLUDE, wintypes.POINT(l, b), wintypes.RECT(l, t, r, b))

    def place_candidates(hwnd):
        form = candidate_form(hwnd)
        if not form:
            return
        himc = imm.ImmGetContext(hwnd)
        if not himc:
            return
        try:
            # 変換中の文字の場所(入力欄の中)を伝える。予測候補はこの位置を基準に、文字を避けて出る
            l, t = form.rcArea.left, form.rcArea.top
            imm.ImmSetCompositionWindow(himc, ctypes.byref(COMPOSITIONFORM(CFS_POINT, wintypes.POINT(l, t))))
            for i in range(4):
                form.dwIndex = i
                imm.ImmSetCandidateWindow(himc, ctypes.byref(form))
        finally:
            imm.ImmReleaseContext(hwnd, himc)

    def answer_request(hwnd, kind, lparam):
        """新しい日本語入力(Windows 10/11 の Microsoft IME など)からの「文字はどこ？」に答える
        (答えないと、予測候補が入力欄の上に重なる)。入力欄には触らず、覚えた位置だけを使う。"""
        if not lparam:
            return 0
        if kind == IMR_QUERYCHARPOSITION:
            info = IMECHARPOSITION.from_address(lparam)
            if info.dwSize < ctypes.sizeof(IMECHARPOSITION):
                return 0
            chars = cache["chars"]
            cb = chars[min(info.dwCharPos, len(chars) - 1)] if chars else cache["caret"]
            if not cb or not cache["doc"]:
                return 0
            info.pt = wintypes.POINT(cb[0], cb[1])
            info.cLineHeight = cb[2]
            info.rcDocument = wintypes.RECT(*cache["doc"])
            return 1
        if kind == IMR_CANDIDATEWINDOW:
            form = candidate_form(hwnd)
            if not form:
                return 0
            ctypes.memmove(lparam, ctypes.byref(form), ctypes.sizeof(form))
            return 1
        return 0

    def hook(hwnd):
        """入力を受け取る窓の処理に割り込む(日本語入力の知らせだけを横取りする)。"""
        old = user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC)

        def proc(h, msg, wparam, lparam):
            try:
                if state["focused"]:
                    if msg == WM_IME_SETCONTEXT and wparam:
                        lparam &= ~ISC_SHOWUICOMPOSITIONWINDOW  # 標準の白い枠を出さない
                    elif msg == WM_IME_STARTCOMPOSITION:
                        place_candidates(h)  # 覚えた位置を使うだけ(入力欄には触らない)
                        return 0
                    elif msg == WM_IME_COMPOSITION:
                        if lparam & GCS_RESULTSTR:  # 確定: 下書きを消し、確定文字は Tk に入れてもらう
                            clear_preedit()
                        elif lparam & GCS_COMPSTR:
                            show_preedit(*composition(h, GCS_COMPSTR))
                            # 位置は描き終わってから調べ、候補の一覧をその下(入らなければ上)へ
                            text.after_idle(lambda: (remember(), place_candidates(h)))
                            return 0
                    elif msg == WM_IME_ENDCOMPOSITION:
                        clear_preedit()
                    elif msg == WM_IME_REQUEST:
                        res = answer_request(h, wparam, lparam)
                        if res:
                            return res
                    elif msg == WM_IME_NOTIFY and wparam in (IMN_OPENCANDIDATE, IMN_CHANGECANDIDATE):
                        place_candidates(h)
            except Exception:
                pass  # うまくいかなくても、通常の入力はできるようにする
            return user32.CallWindowProcW(old, h, msg, wparam, lparam)

        cb = WNDPROC(proc)
        _keep.append(cb)
        user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(cb, ctypes.c_void_p))
        state["hooked"].add(hwnd)

    def focus_in(_=None):
        state["focused"] = True
        remember_later()
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

    for event in ("<KeyRelease>", "<ButtonRelease-1>", "<Configure>"):
        text.bind(event, remember_later, add="+")
    text.bind("<FocusIn>", focus_in, add="+")
    text.bind("<FocusOut>", focus_out, add="+")
