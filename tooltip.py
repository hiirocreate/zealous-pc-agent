"""ボタンにマウスを乗せたとき、少しして「何のボタンか」を小さく表示する。"""
import tkinter as tk

import theme as T

DELAY = 450  # 表示するまでの時間(ミリ秒)


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self._job = self._win = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def set(self, text):
        self.text = text

    def _schedule(self, _=None):
        self._cancel()
        self._job = self.widget.after(DELAY, self._show)

    def _cancel(self):
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None

    def _show(self):
        self._job = None
        if self._win or not self.widget.winfo_exists() or not self.widget.winfo_ismapped():
            return
        win = tk.Toplevel(self.widget)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        label = tk.Label(win, text=self.text, bg=T.SURFACE, fg=T.TEXT, bd=0, padx=8, pady=4,
                         font=(T.FONT, max(8, round(9 * T.SCALE))), highlightthickness=1,
                         highlightbackground=T.BORDER)
        label.pack()
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2 - w // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        sw, sh = self.widget.winfo_screenwidth(), self.widget.winfo_screenheight()
        if y + h > sh:  # 画面の下にはみ出すなら、ボタンの上に出す
            y = self.widget.winfo_rooty() - h - 6
        x = max(0, min(x, sw - w))
        win.geometry(f"+{x}+{y}")
        self._win = win

    def _hide(self, _=None):
        self._cancel()
        if self._win:
            self._win.destroy()
            self._win = None


def tip(widget, text):
    """widget に説明を付ける(あとで文を変えるときは、戻り値の set() を使う)。"""
    return Tooltip(widget, text)
