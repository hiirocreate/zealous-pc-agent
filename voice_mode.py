"""音声会話画面。中央の光の球で、聞き取り中・考え中・話し中が分かる。
合図の言葉もボタンも要らず、話しかけるたびに聞き取り、返事を読み上げ、また聞き取る。"""
import time
import tkinter as tk

import customtkinter as ctk
from PIL import ImageTk

import icons
import orb
import theme as T

ORB = 260  # 球を描く大きさ(論理ピクセル)
LABELS = {"listen": "聞いています…", "think": "考えています…", "speak": "話しています", "pause": "マイクは止まっています"}


class VoiceMode(ctk.CTkToplevel):
    def __init__(self, app, x, y):
        super().__init__(app, fg_color=T.BG)
        self.app = app
        self.title(f"{app_name()} と話す")
        self.geometry(f"360x640+{x}+{y}")
        self.minsize(300, 560)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.muted = False
        self.user_text, self.ai_text = "", ""

        scale = ctk.ScalingTracker.get_window_scaling(self)
        size = round(ORB * scale)
        self.orb = orb.Orb(size, _rgb(T.BG))
        self.photo = ImageTk.PhotoImage(self.orb.frame(time.monotonic(), "listen"))
        self.canvas = tk.Label(self, image=self.photo, bg=T.BG, bd=0, highlightthickness=0, cursor="hand2")
        self.canvas.pack(pady=(28, 6))
        self.canvas.bind("<Button-1>", lambda e: self.interrupt())  # 話し中に押すと、話をやめて聞き取りへ

        self.state_label = ctk.CTkLabel(self, text="", font=T.font(14, "bold"), text_color=T.TEXT)
        self.state_label.pack()
        self.user_label = ctk.CTkLabel(self, text="", font=T.font(11), text_color=T.SUB, wraplength=310,
                                       justify="center")
        self.user_label.pack(padx=20, pady=(10, 2))
        self.ai_label = ctk.CTkLabel(self, text="話しかけてください", font=T.font(12), text_color=T.TEXT,
                                     wraplength=310, justify="center")
        self.ai_label.pack(padx=20, pady=(2, 0), fill="x")
        self.pics = ctk.CTkFrame(self, fg_color="transparent")  # 返事に画像があるときの並び

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(side="bottom", pady=22)
        self.mute_btn = ctk.CTkButton(bar, text="", width=58, height=58, corner_radius=29, command=self.toggle_mute)
        self._paint_mute()
        self.mute_btn.pack(side="left", padx=10)
        ctk.CTkButton(bar, text="", image=icons.chat(22), width=58, height=58, corner_radius=29,
                      fg_color=T.SURFACE, hover_color=T.BORDER, command=self.to_chat).pack(side="left", padx=10)
        ctk.CTkButton(bar, text="", image=icons.close(20, (255, 255, 255)), width=58, height=58, corner_radius=29,
                      fg_color=T.DANGER, hover_color=T.DANGER_HOVER, command=self.close).pack(side="left", padx=10)
        self.bind("<Escape>", lambda e: self.close())
        self.bind("<space>", lambda e: self.toggle_mute())
        for ms in (10, 250):  # 開いた直後にも、いちばん手前へ
            self.after(ms, lambda: self.winfo_exists() and (self.lift(), self.focus_force()))
        self._tick()

    # ---- 状態 ----
    def mode(self):
        """いまの状態: 考え中 > 話し中 > マイク停止中 > 聞き取り中。"""
        if self.app._state == "think":
            return "think"
        if self.app.speaker.busy:
            return "speak"
        return "pause" if self.muted else "listen"

    def _tick(self):
        if not self.winfo_exists():
            return
        mode = self.mode()
        if mode == "speak":
            look, level = orb.tone_of(self.app.speaker.text), self.app.speaker.level
        elif mode == "listen":
            look, level = "listen", self.app.voice.level
        else:
            look, level = mode, 0.0
        self.photo.paste(self.orb.frame(time.monotonic(), look, level))
        self.state_label.configure(text=LABELS[mode])
        self.after(33, self._tick)  # 30コマ/秒

    # ---- 会話の表示 ----
    def heard(self, text):
        self.user_text, self.ai_text = text, ""
        self.clear_images()
        self.user_label.configure(text=f"あなた: {_short(text, 80)}")
        self.ai_label.configure(text="")

    def reply_piece(self, piece):
        self.ai_text += piece
        self.ai_label.configure(text=_tail(self.ai_text, 120))

    def reply_done(self, body):
        self.ai_text = body
        self.ai_label.configure(text=_tail(body, 120))

    def show_images(self, images):
        """返事に画像があれば、文の下に4枚まで並べる。押すと一覧(大きく見られる)を開く。"""
        import gallery
        self.clear_images()
        items = images["items"]
        open_all = lambda: gallery.Gallery(self, images["query"], items)  # noqa: E731
        row = ctk.CTkFrame(self.pics, fg_color="transparent")
        row.pack()
        for item in items[:4]:
            pic = ctk.CTkLabel(row, text="", width=72, height=72, fg_color=T.SURFACE, corner_radius=0, cursor="hand2")
            pic.pack(side="left", padx=3)
            pic.bind("<Button-1>", lambda e: open_all())
            gallery.load_async(pic, [item["thumb"]], (72, 72), lambda im, _, p=pic: p.configure(image=im))
        ctk.CTkButton(self.pics, text=f"画像を大きく見る（{len(items)}枚）", height=28, corner_radius=14,
                      font=T.font(10), fg_color="transparent", border_width=1, border_color=T.ACCENT,
                      hover_color=T.SURFACE, command=open_all).pack(pady=(8, 0))
        self.pics.pack(pady=(12, 0))

    def clear_images(self):
        for w in self.pics.winfo_children():
            w.destroy()
        self.pics.pack_forget()

    # ---- 操作 ----
    def toggle_mute(self):
        self.muted = not self.muted
        self.app.voice.conversation = not self.muted
        self._paint_mute()

    def _paint_mute(self):
        """マイクボタン: 聞き取り中=水色(球と同じ色)、止めている=灰色に斜線。乗せたときは少し明るく。"""
        if self.muted:
            self.mute_btn.configure(image=icons.mic_off(22, (203, 213, 225)), fg_color="#3a4150", hover_color="#4b5466")
        else:
            self.mute_btn.configure(image=icons.mic_live(24), fg_color="#0e7490", hover_color="#1597b5")

    def interrupt(self):
        if self.app.speaker.busy:
            self.app.speaker.stop()

    def to_chat(self):
        self.close()
        self.app.open_chat()

    def close(self):
        self.app.voice_mode_closed()
        self.destroy()


def app_name():
    import config
    return config.AI_NAME


def _short(text, n):
    return text if len(text) <= n else text[:n - 1] + "…"


def _tail(text, n):
    return text if len(text) <= n else "…" + text[-(n - 1):]


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
