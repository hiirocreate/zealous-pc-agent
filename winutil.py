"""Windows 専用の見た目・画面の補助。Windows 以外では何もしない(または控えめな代わりの値を返す)。

- Shell: 常駐ウィンドウの外枠(角丸・縁・影)を、なめらかに描いた半透明の画像として後ろに重ねる。
  Tk の窓は角丸に切り抜けても縁がギザギザになるため、縁と影はこの画像に任せる。
- work_area / virtual_bounds: 複数のモニター(デュアルスクリーン)の範囲を調べる。
"""
import ctypes
import os
import tkinter as tk

WIN = os.name == "nt"

if WIN:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_byte)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]

    user32.GetAncestor.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                           ctypes.POINTER(SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                           wintypes.DWORD, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_uint]
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateDIBSection.restype = wintypes.HANDLE
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), ctypes.c_uint,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
    gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6

    GA_ROOT, GWL_EXSTYLE, GWLP_HWNDPARENT = 2, -20, -8
    WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x80, 0x08000000
    SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
    ULW_ALPHA, AC_SRC_ALPHA = 2, 1


def hwnd_of(win):
    """Tk のウィンドウの、Windows 上の本当の窓の番号。"""
    return user32.GetAncestor(win.winfo_id(), GA_ROOT)


def work_area(x, y, fallback):
    """点(x, y)があるモニターの、タスクバーを除いた範囲 (左, 上, 右, 下)。"""
    if not WIN:
        return fallback
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    mon = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)  # 2 = いちばん近いモニター
    if not mon or not user32.GetMonitorInfoW(mon, ctypes.byref(info)):
        return fallback
    r = info.rcWork
    return r.left, r.top, r.right, r.bottom


def virtual_bounds(fallback):
    """すべてのモニターを合わせた範囲 (左, 上, 右, 下)。"""
    if not WIN:
        return fallback
    gm = user32.GetSystemMetrics
    x, y = gm(76), gm(77)
    return x, y, x + gm(78), y + gm(79)


class Shell:
    """常駐ウィンドウの後ろに置く「なめらかな外枠と影」。本体の窓は少し内側で角丸に切り抜く。"""

    MARGIN = 14   # 影を描く余白
    INSET = 2     # 本体の窓を外枠より内側で切り抜く幅(切り口のギザギザを外枠の内側に隠す)

    def __init__(self, root, fill, border, enabled=True):
        self.ok = WIN and enabled
        self.root, self.fill, self.border = root, fill, border
        self._last = None
        self._ready = False  # Windows 側の準備は、本体の窓が画面に出てから行う

    def _setup(self):
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry("1x1+-100+-100")
        self.win.update_idletasks()
        self.hwnd = hwnd_of(self.win)
        ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE,
                                 ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        self.root_hwnd = hwnd_of(self.root)
        # 本体をこの窓の「持ち主付き」にして、常に外枠より手前に表示させる
        user32.SetWindowLongPtrW(self.root_hwnd, GWLP_HWNDPARENT, self.hwnd)
        self._ready = True

    def update(self, x, y, w, h, radius, fast=False):
        """本体の窓の位置・大きさ(実ピクセル)と角の丸み(実ピクセル)に合わせて描き直す。"""
        if not self.ok:
            return
        try:
            self._update(x, y, w, h, radius, fast)
        except Exception:
            self._give_up()

    def suspend(self):
        """外枠を一旦外し、本体を切り抜かずにそのまま見せる(全画面のとき)。"""
        if self.ok and self._ready:
            try:
                user32.SetWindowRgn(self.root_hwnd, None, True)
                self.win.withdraw()
            except Exception:
                pass
            self._last = None
            self._suspended = True

    def resume(self):
        if self.ok and self._ready and getattr(self, "_suspended", False):
            self._suspended = False
            self.win.deiconify()
            self.win.attributes("-topmost", True)

    def frame(self, x, y, w, h, radius, fast=True):
        """外枠だけを (x, y, w, h) に描く(本体の窓の切り抜きは変えない)。展開・折りたたみの途中用。"""
        if not self.ok:
            return
        try:
            if not self._ready:
                if not self.root.winfo_ismapped():
                    return
                self._setup()
            self._draw(w, h, radius, fast)
            self._last = None  # 次の update() で本体の切り抜きと外枠を必ず描き直す
            self.move(x, y)
        except Exception:
            self._give_up()

    def _give_up(self):
        """うまく描けない環境では外枠をやめ、本体の窓を切り抜かずにそのまま見せる(使えなくはならない)。"""
        self.ok = False
        try:
            user32.SetWindowRgn(self.root_hwnd, None, True)
            self.win.withdraw()
        except Exception:
            pass

    def _update(self, x, y, w, h, radius, fast):
        if getattr(self, "_suspended", False):
            return
        if not self._ready:
            if not self.root.winfo_ismapped():
                return  # まだ画面に出ていない(出た後にもう一度呼ばれる)
            self._setup()
        key = (w, h, radius, fast)
        if key != self._last:
            self._draw(w, h, radius, fast)
            region = gdi32.CreateRoundRectRgn(self.INSET, self.INSET, w - self.INSET + 1, h - self.INSET + 1,
                                              max(0, 2 * (radius - self.INSET)), max(0, 2 * (radius - self.INSET)))
            user32.SetWindowRgn(self.root_hwnd, region, True)  # 渡した領域は Windows が管理する
            self._last = key
        self.move(x, y)

    def move(self, x, y):
        if self.ok and self._ready:
            m = self.MARGIN
            if not user32.SetWindowPos(self.hwnd, None, x - m, y - m, 0, 0,
                                       SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE):
                self._give_up()

    def _draw(self, w, h, r, fast):
        import numpy as np
        img = render_frame(w, h, r, self.fill, self.border, self.MARGIN, fast)
        a = np.asarray(img, dtype=np.float32)
        a[..., :3] *= a[..., 3:4] / 255.0  # Windows は「色×透明度」済みの値を求める
        bgra = a[..., [2, 1, 0, 3]].astype(np.uint8).tobytes()
        self._blit(bgra, img.width, img.height)

    def _blit(self, bgra, W, H):
        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bmi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=W, biHeight=-H, biPlanes=1,
                               biBitCount=32, biCompression=0)
        bits = ctypes.c_void_p()
        bmp = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        try:
            ctypes.memmove(bits, bgra, len(bgra))
            old = gdi32.SelectObject(mem, bmp)
            blend = BLENDFUNCTION(0, 0, 255, AC_SRC_ALPHA)
            size, src = SIZE(W, H), wintypes.POINT(0, 0)
            user32.UpdateLayeredWindow(self.hwnd, screen, None, ctypes.byref(size), mem, ctypes.byref(src), 0,
                                       ctypes.byref(blend), ULW_ALPHA)
            gdi32.SelectObject(mem, old)
        finally:
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(None, screen)


def render_frame(w, h, r, fill, border, m, fast=False):
    """外枠の画像(影つき・角丸・縁取り)。大きめに描いて縮小し、縁をなめらかにする。
    fast=True は動かしている途中用(少し粗く、そのぶん速い)。"""
    from PIL import Image, ImageDraw, ImageFilter
    k = 1 if fast else 3  # 動いている途中は粗くても目に見えないので、速さを優先
    W, H = w + 2 * m, h + 2 * m
    q = 4  # 影はぼかすだけなので 1/4 の大きさで作って拡大する(速い)
    shadow = Image.new("L", (W // q + 1, H // q + 1), 0)
    ImageDraw.Draw(shadow).rounded_rectangle((m / q, (m + 3) / q, (m + w) / q, (m + h + 3) / q), r / q, fill=95)
    shadow = shadow.filter(ImageFilter.GaussianBlur(m / 2.6 / q)).resize((W, H), Image.BILINEAR)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.putalpha(shadow)
    shape = Image.new("RGBA", (W * k, H * k), (0, 0, 0, 0))
    ImageDraw.Draw(shape).rounded_rectangle((m * k, m * k, (m + w) * k - 1, (m + h) * k - 1), r * k,
                                            fill=_rgb(fill) + (255,), outline=_rgb(border) + (255,), width=k)
    img.alpha_composite(shape.resize((W, H), Image.BILINEAR if fast else Image.LANCZOS))
    return img


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
