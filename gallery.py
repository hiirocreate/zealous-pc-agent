"""画像一覧ウィンドウ。サムネイルを並べ、クリックで大きく表示(元のページを開く・保存もできる)。"""
import io
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import customtkinter as ctk
from PIL import Image, ImageOps

import theme as T
import tools
import websearch

THUMB = 150
COLS = 4
_pool = ThreadPoolExecutor(6)  # 画像の取得は同時に数枚ずつ


def load_async(widget, urls, size, on_image, fit=False):
    """画像を裏で取得し、取得できたら画面の処理として on_image(表示用CTkImage, 元の画像) を呼ぶ。"""
    def job():
        try:
            orig = Image.open(io.BytesIO(websearch.fetch_image(urls))).convert("RGB")
        except Exception:
            return
        img = ImageOps.contain(orig, size) if fit else ImageOps.fit(orig, size)
        widget.after(0, lambda: widget.winfo_exists() and on_image(ctk.CTkImage(img, size=img.size), orig))
    _pool.submit(job)


class Gallery(ctk.CTkToplevel):
    def __init__(self, master, query, items):
        super().__init__(master, fg_color=T.BG)
        self.title(f"画像: {query}")
        self.geometry(f"{COLS * (THUMB + 12) + 48}x620")
        self.attributes("-topmost", True)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(head, text=f"「{query}」の画像", font=T.font(15, "bold"), text_color=T.TEXT).pack(side="left")
        ctk.CTkLabel(head, text=f"{len(items)}枚 ・ クリックで拡大", font=T.font(11), text_color=T.SUB).pack(
            side="left", padx=10)
        grid = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=T.BORDER)
        grid.pack(fill="both", expand=True, padx=8, pady=(0, 12))
        for i, item in enumerate(items):
            cell = ctk.CTkFrame(grid, fg_color=T.SURFACE, corner_radius=12, width=THUMB + 4, height=THUMB + 30)
            cell.grid(row=i // COLS, column=i % COLS, padx=4, pady=4)
            cell.grid_propagate(False)
            pic = ctk.CTkLabel(cell, text="…", width=THUMB, height=THUMB, text_color=T.SUB, cursor="hand2")
            pic.place(x=2, y=2)
            cap = ctk.CTkLabel(cell, text=_short(item.get("title", ""), 12), font=T.font(9), text_color=T.SUB)
            cap.place(relx=0.5, y=THUMB + 14, anchor="center")
            for w in (pic, cell):
                w.bind("<Button-1>", lambda e, it=item: Preview(self, it))
            load_async(pic, [item["thumb"], item.get("mid", "")], (THUMB, THUMB),
                       lambda im, _, p=pic: p.configure(image=im, text=""))


class Preview(ctk.CTkToplevel):
    """1枚を大きく表示する。"""

    def __init__(self, master, item):
        super().__init__(master, fg_color=T.BG)
        self.item = item
        self.title(item.get("title", "画像"))
        self.geometry("720x620")
        self.attributes("-topmost", True)
        self.pic = ctk.CTkLabel(self, text="読み込み中…", text_color=T.SUB)
        self.pic.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        ctk.CTkLabel(self, text=item.get("title", ""), font=T.font(11), text_color=T.TEXT, wraplength=680).pack(
            padx=12)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(pady=12)
        self.status = ctk.CTkLabel(bar, text="", font=T.font(10), text_color=T.CYAN)
        self.status.pack(side="left", padx=8)
        for text, cmd, primary in (("元のページを開く", self._open, False), ("画像を保存", self._save, True)):
            ctk.CTkButton(bar, text=text, width=130, height=32, corner_radius=16, font=T.font(11),
                          fg_color=T.ACCENT if primary else "transparent", border_width=0 if primary else 1,
                          border_color=T.BORDER, hover_color=T.ACCENT_HOVER if primary else T.SURFACE,
                          command=cmd).pack(side="left", padx=4)
        self.full = None
        load_async(self.pic, [item.get("full", ""), item.get("mid", ""), item["thumb"]], (696, 500),
                   self._shown, fit=True)

    def _shown(self, image, raw):
        self.full = raw
        self.pic.configure(image=image, text="")

    def _open(self):
        tools.open_in_browser(self.item.get("page") or self.item.get("full"))

    def _save(self):
        """ピクチャフォルダの Zealous フォルダに保存する。"""
        if self.full is None:
            return
        folder = os.path.join(os.path.expanduser("~"), "Pictures", "Zealous")
        os.makedirs(folder, exist_ok=True)
        name = re.sub(r'[\\/:*?"<>|]', "_", self.item.get("title") or "image")[:40] or "image"
        path, n = os.path.join(folder, f"{name}.jpg"), 1
        while os.path.exists(path):
            n += 1
            path = os.path.join(folder, f"{name} ({n}).jpg")
        threading.Thread(target=lambda: self.full.save(path, quality=92), daemon=True).start()
        self.status.configure(text=f"保存しました: ピクチャ\\Zealous\\{os.path.basename(path)}")


def _short(text, n):
    return text if len(text) <= n else text[:n] + "…"
