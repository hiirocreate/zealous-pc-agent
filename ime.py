"""日本語入力(IME)を、チャット欄の中でそのまま行えるようにする(Windows)。

Tk は変換中の文字を Windows 標準の白い枠で表示してしまうため、
- 標準の枠を出さないよう Windows に伝え、変換中の文字は入力欄の中に下線付きで直接描く
- 変換候補の一覧はカーソルのすぐ下に出す
確定した文字は、これまで通り Tk が入力欄に入れる。"""
import ctypes
import os
import queue

import zlog

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
IMR_RECONVERTSTRING, IMR_CONFIRMRECONVERTSTRING = 0x0004, 0x0005
GWLP_WNDPROC = -4
TAG = "ime_preedit"

_keep = []  # Windows に渡した関数を、消されないよう持っておく


class EntryShim:
    """1行の入力欄(tk.Entry)を、複数行の入力欄(tk.Text)と同じ書き方で扱えるようにする。
    (日本語入力の処理を、設定画面などの1行の欄でもそのまま使うため)"""

    def __init__(self, entry):
        self.e = entry
        self.pre = None  # 変換中の文字の (始まり, 長さ)

    def __getattr__(self, name):  # winfo_*, after, bind などはそのまま渡す
        return getattr(self.e, name)

    def _i(self, idx):
        """"1.5" "insert" "end" "1.end" "1.3+2c" などを、文字の位置(数)にする。"""
        idx, plus = str(idx), 0
        if "+" in idx:
            idx, extra = idx.split("+", 1)
            plus = int(extra.rstrip("c") or 0)
        if idx == "insert":
            n = self.e.index("insert")
        elif idx in ("end", "end-1c") or idx.endswith(".end"):
            n = len(self.e.get())
        elif "." in idx:
            n = int(idx.split(".", 1)[1])
        else:
            n = int(idx)
        return max(0, min(len(self.e.get()), n + plus))

    def index(self, idx):
        return f"1.{self._i(idx)}"

    def tag_configure(self, *a, **k):
        pass  # 1行の欄は下線を引けない(変換中の文字はそのまま表示する)

    def tag_ranges(self, tag):
        if tag == TAG and self.pre:
            return (f"1.{self.pre[0]}", f"1.{self.pre[0] + self.pre[1]}")
        if tag == "sel" and self.e.selection_present():
            return (f"1.{self.e.index('sel.first')}", f"1.{self.e.index('sel.last')}")
        return ()

    def tag_remove(self, tag, *a):
        if tag == "sel":
            self.e.selection_clear()

    def delete(self, a, b=None):
        ia = self._i(a)
        ib = self._i(b) if b is not None else ia + 1
        self.e.delete(ia, ib)
        if self.pre and ia <= self.pre[0] < ib:
            self.pre = None

    def insert(self, idx, s, tag=None):
        i = self._i(idx)
        self.e.insert(i, s)
        if tag == TAG:
            self.pre = (i, len(s))

    def mark_set(self, mark, idx):
        if mark == "insert":
            self.e.icursor(self._i(idx))

    def see(self, idx):
        self.e.xview(max(0, self._i(idx) - 20))

    def bbox(self, idx):
        return self.e.bbox(self._i(idx))

    def get(self, a, b=None):
        text = self.e.get()
        return text[self._i(a):self._i(b) if b is not None else self._i(a) + 1]


def attach_all(root, font_family, font_px):
    """root の中の入力欄すべてで、日本語入力を欄の中に表示する(設定画面など)。"""
    import tkinter as tk
    for w in root.winfo_children():
        if isinstance(w, (tk.Entry, tk.Text)):
            attach(w, font_family, font_px)
        attach_all(w, font_family, font_px)


def attach(text, font_family, font_px):
    """text(tk.Text / tk.Entry) で日本語入力するとき、変換中の文字を入力欄の中に描く。"""
    import config
    import tkinter as tk
    if os.name != "nt" or not getattr(config, "IME_INLINE", True):
        return
    if isinstance(text, tk.Entry):
        text = EntryShim(text)
    from ctypes import wintypes
    user32, imm = ctypes.WinDLL("user32"), ctypes.WinDLL("imm32")
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class CANDIDATEFORM(ctypes.Structure):
        _fields_ = [("dwIndex", wintypes.DWORD), ("dwStyle", wintypes.DWORD),
                    ("ptCurrentPos", wintypes.POINT), ("rcArea", wintypes.RECT)]

    class COMPOSITIONFORM(ctypes.Structure):
        _fields_ = [("dwStyle", wintypes.DWORD), ("ptCurrentPos", wintypes.POINT), ("rcArea", wintypes.RECT)]

    class RECONVERTSTRING(ctypes.Structure):  # 再変換: 対象の行と、変換し直す範囲を伝える
        _fields_ = [("dwSize", wintypes.DWORD), ("dwVersion", wintypes.DWORD),
                    ("dwStrLen", wintypes.DWORD), ("dwStrOffset", wintypes.DWORD),
                    ("dwCompStrLen", wintypes.DWORD), ("dwCompStrOffset", wintypes.DWORD),
                    ("dwTargetStrLen", wintypes.DWORD), ("dwTargetStrOffset", wintypes.DWORD)]

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

    # 日本語入力からの「文字はどこ？」という問い合わせは、Tk が入力欄を描いている最中にも届く。
    # その最中に入力欄を調べると Tk が壊れて強制終了するので、位置は普段のうちに調べて覚えておき、
    # 問い合わせには覚えた値だけで答える。
    cache = {"caret": None, "chars": [], "doc": None, "line": None}

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
            # 再変換用: いまの行の文字と、選択範囲(なければカーソルの位置)
            if not ranges:
                line, col = map(int, text.index("insert").split("."))
                sel = text.tag_ranges("sel")
                start = end = col
                if sel:
                    (l1, c1), (l2, c2) = (map(int, str(i).split(".")) for i in sel[:2])
                    if l1 == l2 == line:
                        start, end = c1, c2
                cache["line"] = (line, text.get(f"{line}.0", f"{line}.end"), start, end)
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

    def u16(t):
        return len(t.encode("utf-16-le")) // 2

    def from_u16(t, n):
        """UTF-16 での位置 n を、文字の位置に直す。"""
        count = 0
        for i, ch in enumerate(t):
            if count >= n:
                return i
            count += 2 if ord(ch) > 0xFFFF else 1
        return len(t)

    def reconvert(kind, lparam):
        """確定した文字の再変換(変換キーなど)。日本語入力に、いまの行の文字と変換し直す範囲を渡す。
        入れ替えは Tk の側(pump)で、変換中の文字が届いたときに行う。"""
        if not cache["line"]:
            return 0
        line, s, start, end = cache["line"]
        head = ctypes.sizeof(RECONVERTSTRING)
        size = head + (u16(s) + 1) * 2
        if kind == IMR_RECONVERTSTRING:
            if not lparam:
                return size  # 1回目は必要な大きさだけを答える
            info = RECONVERTSTRING.from_address(lparam)
            if info.dwSize < size:
                return 0
            a, b = u16(s[:start]), u16(s[:end])
            info.dwVersion, info.dwStrLen, info.dwStrOffset = 0, u16(s), head
            info.dwCompStrOffset = info.dwTargetStrOffset = a * 2
            info.dwCompStrLen = info.dwTargetStrLen = b - a
            buf = ctypes.create_unicode_buffer(s, u16(s) + 1)
            ctypes.memmove(lparam + head, buf, (u16(s) + 1) * 2)
            ops.put(("reconv", line, start, end, False))
            return size
        if kind == IMR_CONFIRMRECONVERTSTRING and lparam:
            info = RECONVERTSTRING.from_address(lparam)
            a = from_u16(s, info.dwCompStrOffset // 2)
            b = from_u16(s, info.dwCompStrOffset // 2 + info.dwCompStrLen)
            ops.put(("reconv", line, a, b, True))  # 日本語入力が選び直した範囲
            return 1
        return 0

    def answer_request(hwnd, kind, lparam):
        """新しい日本語入力(Windows 10/11 の Microsoft IME など)からの「文字はどこ？」に答える
        (答えないと、予測候補が入力欄の上に重なる)。入力欄には触らず、覚えた位置だけを使う。"""
        if kind in (IMR_RECONVERTSTRING, IMR_CONFIRMRECONVERTSTRING):
            return reconvert(kind, lparam)
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
            # ここは Windows から直接呼ばれる。ここで Tk(入力欄)に触ると、Tk の処理の途中に割り込む形になり、
            # 強制終了することがある。ここでは日本語入力の文字を受け取って順番に積むだけにし、
            # 入力欄への反映は Tk の側(pump)で行う。
            try:
                if state["focused"]:
                    if msg == WM_IME_SETCONTEXT and wparam:
                        lparam &= ~ISC_SHOWUICOMPOSITIONWINDOW  # 標準の白い枠を出さない
                    elif msg == WM_IME_STARTCOMPOSITION:
                        state["hwnd"] = h
                        place_candidates(h)  # 覚えた位置を使うだけ(入力欄には触らない)
                        return 0
                    elif msg == WM_IME_COMPOSITION:
                        state["hwnd"] = h
                        handled = False
                        if lparam & GCS_RESULTSTR:  # 確定した文字
                            ops.put(("result", composition(h, GCS_RESULTSTR)[0]))
                            handled = True
                        if lparam & GCS_COMPSTR:  # 変換中の文字
                            ops.put(("pre", *composition(h, GCS_COMPSTR)))
                            handled = True
                        if handled:
                            return 0  # Tk には渡さない(確定文字もこちらで入れる)
                    elif msg == WM_IME_ENDCOMPOSITION:
                        ops.put(("end",))
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

    ops = queue.Queue()  # Windows から受け取った日本語入力の知らせ(Tk の側で順に反映する)

    def pump():
        """積まれた日本語入力の知らせを、入力欄に反映する(Tk の中で安全に行う)。"""
        changed = False
        while True:
            try:
                op = ops.get_nowait()
            except queue.Empty:
                break
            changed = True
            try:
                if op[0] == "reconv":  # 再変換する範囲(変換中の文字が届いたら入れ替える)
                    state["reconv"] = op[1:]
                    continue
                target = state.pop("reconv", None) if op[0] in ("pre", "result") else None
                if target:
                    # 再変換が始まった: 元の文字を消し、そこに変換中の文字を出す(取り消したら戻す)。
                    # 日本語入力が周りの文字を確かめただけのときは消さないよう、日本語入力が範囲を
                    # 確定したとき(confirmed)か、変換中の文字が元の文字と同じときだけ入れ替える
                    line, a, b, confirmed = target
                    original = text.get(f"{line}.{a}", f"{line}.{b}")
                    if original and (confirmed or original == op[1]):
                        state["restore"] = (f"{line}.{a}", original)
                        text.tag_remove("sel", "1.0", "end")
                        text.delete(f"{line}.{a}", f"{line}.{b}")
                        text.mark_set("insert", f"{line}.{a}")
                if op[0] == "pre":
                    show_preedit(op[1], op[2])
                elif op[0] == "result":
                    clear_preedit()
                    text.insert("insert", op[1])
                    text.see("insert")
                    state["restore"] = None
                    zlog.note(f"日本語入力 確定 {len(op[1])}文字")
                else:  # 変換の終わり
                    clear_preedit()
                    state["reconv"] = None
                    if state.get("restore"):  # 再変換を取り消した: 元の文字に戻す
                        index, original = state.pop("restore")
                        text.insert(index, original)
                        text.mark_set("insert", f"{index}+{len(original)}c")
            except Exception:
                pass
        if changed:
            remember()
            if state.get("hwnd"):
                place_candidates(state["hwnd"])
            text.event_generate("<<ImePreedit>>")  # 入力欄の高さの調整などに使う
        if state["focused"]:
            state["pump"] = text.after(15, pump)
        else:
            state["pump"] = None

    def focus_in(_=None):
        state["focused"] = True
        remember_later()
        if not state.get("pump"):
            state["pump"] = text.after(15, pump)
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
        pump()  # 残っている確定文字などを反映してから
        clear_preedit()

    for event in ("<KeyRelease>", "<ButtonRelease-1>", "<Configure>"):
        text.bind(event, remember_later, add="+")
    text.bind("<FocusIn>", focus_in, add="+")
    text.bind("<FocusOut>", focus_out, add="+")
    state["ops"] = ops  # 動作確認(smoketest)から日本語入力の知らせを模擬するため
    return state
