"""日本語入力(IME)で変換中の文字を、チャット欄のカーソル位置に重ねて表示させる(Windows)。
Tk は変換中の文字を画面の端など既定の場所に出してしまうため、位置とフォントを Windows に毎回伝える。"""
import ctypes
import os
from ctypes import wintypes

CFS_FORCE_POSITION = 0x0020   # 変換中の文字を指定位置に出す
CFS_CANDIDATEPOS = 0x0040     # 変換候補の一覧を指定位置に出す
SHIFTJIS_CHARSET = 128


class COMPOSITIONFORM(ctypes.Structure):
    _fields_ = [("dwStyle", wintypes.DWORD), ("ptCurrentPos", wintypes.POINT), ("rcArea", wintypes.RECT)]


class CANDIDATEFORM(ctypes.Structure):
    _fields_ = [("dwIndex", wintypes.DWORD), ("dwStyle", wintypes.DWORD),
                ("ptCurrentPos", wintypes.POINT), ("rcArea", wintypes.RECT)]


class LOGFONTW(ctypes.Structure):
    _fields_ = [("lfHeight", wintypes.LONG), ("lfWidth", wintypes.LONG), ("lfEscapement", wintypes.LONG),
                ("lfOrientation", wintypes.LONG), ("lfWeight", wintypes.LONG), ("lfItalic", wintypes.BYTE),
                ("lfUnderline", wintypes.BYTE), ("lfStrikeOut", wintypes.BYTE), ("lfCharSet", wintypes.BYTE),
                ("lfOutPrecision", wintypes.BYTE), ("lfClipPrecision", wintypes.BYTE),
                ("lfQuality", wintypes.BYTE), ("lfPitchAndFamily", wintypes.BYTE),
                ("lfFaceName", wintypes.WCHAR * 32)]


def attach(text, font_family, font_px):
    """text(tk.Text) で日本語入力するとき、変換中の文字と候補一覧をカーソルの位置に出す。"""
    if os.name != "nt":
        return
    user32, imm = ctypes.WinDLL("user32"), ctypes.WinDLL("imm32")
    user32.GetFocus.restype = wintypes.HWND
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    imm.ImmGetContext.restype = wintypes.HANDLE
    imm.ImmGetContext.argtypes = [wintypes.HWND]
    imm.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
    imm.ImmSetCompositionWindow.argtypes = [wintypes.HANDLE, ctypes.POINTER(COMPOSITIONFORM)]
    imm.ImmSetCandidateWindow.argtypes = [wintypes.HANDLE, ctypes.POINTER(CANDIDATEFORM)]
    imm.ImmSetCompositionFontW.argtypes = [wintypes.HANDLE, ctypes.POINTER(LOGFONTW)]

    font = LOGFONTW()
    font.lfHeight, font.lfCharSet, font.lfFaceName = -font_px, SHIFTJIS_CHARSET, font_family

    def update(_=None):
        try:
            hwnd = user32.GetFocus()
            box = text.bbox("insert")  # カーソルの位置(入力欄の中での座標)
            if not hwnd or not box:
                return
            pt = wintypes.POINT(text.winfo_rootx() + box[0], text.winfo_rooty() + box[1])
            user32.ScreenToClient(hwnd, ctypes.byref(pt))
            himc = imm.ImmGetContext(hwnd)
            if not himc:
                return
            try:
                imm.ImmSetCompositionFontW(himc, ctypes.byref(font))
                imm.ImmSetCompositionWindow(himc, ctypes.byref(COMPOSITIONFORM(CFS_FORCE_POSITION, pt)))
                below = wintypes.POINT(pt.x, pt.y + box[3] + 4)  # 候補一覧はカーソルのすぐ下
                imm.ImmSetCandidateWindow(himc, ctypes.byref(CANDIDATEFORM(0, CFS_CANDIDATEPOS, below)))
            finally:
                imm.ImmReleaseContext(hwnd, himc)
        except Exception:
            pass  # 位置合わせに失敗しても入力自体はできる

    for event in ("<FocusIn>", "<KeyPress>", "<KeyRelease>", "<ButtonRelease-1>"):
        text.bind(event, update, add="+")
