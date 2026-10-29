"""常駐型UI。起動: zealous.pyw をダブルクリック
待機中は右下に小さなピル型で常駐し、▲で会話パネルを展開する。"""
import multiprocessing as mp
import queue

import customtkinter as ctk

import config
import icons
import theme as T
from agent_worker import AgentWorker
from settings_window import SettingsWindow
from tts import Speaker
from voice import VoiceInput
from wakeword import strip_wake_word

MODE_HOLD, MODE_TOGGLE = "トランシーバー", "トグル"
HOTKEY = "+".join(k.capitalize() for k in config.EMERGENCY_KEYS)
PILL_W, PILL_H = 320, 64
PANEL_W, PANEL_H = 380, 460
MAX_BUBBLES = 40

# 状態 -> (表示, 色, 点滅するか)
STATES = {
    "idle": ("待機中", T.OK, False),
    "listen": ("聞き取り中…", T.DANGER, True),
    "recog": ("認識中…", T.CYAN, True),
    "think": ("考え中…", T.ACCENT, True),
    "stop": ("停止しました", T.WARN, False),
}


class RoundButton(ctk.CTkButton):
    """真円ボタン(CTkButton は角丸半径ぶん横幅が広がるため、その余白を消す)。"""

    def _create_grid(self):
        super()._create_grid()
        for c in (0, 4):
            self.grid_columnconfigure(c, minsize=0)


class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=T.KEY)
        self._events = queue.Queue()  # 他スレッド -> UIスレッドへの処理依頼
        self._recording = False
        self._expanded = False
        self._state = "idle"
        self._blink = 0

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-transparentcolor", T.KEY)  # Windows: 角丸の外側を透過
        except Exception:
            pass
        self._build()
        self._show_pill()

        self.worker = AgentWorker()
        self.speaker = Speaker(on_error=self._post_log)
        self.voice = VoiceInput(on_text=lambda t: self._events.put(lambda: self._on_voice(t)),
                                on_status=self._post_log)
        try:
            import stopper
            stopper.register(self.emergency_stop)
        except Exception as e:
            self._log(f"ショートカット登録エラー: {e}", "sys")
        self._refresh_title()
        if config.WAKE_ENABLED:
            self.wake.select()
            self.voice.set_wake(True)
        self._set_state("idle")
        self.after(50, self._pump)

    # ================= 画面 =================
    def _card(self):
        return ctk.CTkFrame(self, fg_color=T.BG, bg_color=T.KEY, corner_radius=18,
                            border_width=1, border_color=T.BORDER)

    def _icon_btn(self, master, text, cmd=None, size=32, fg="transparent", hover=T.SURFACE, color=T.SUB):
        return RoundButton(master, text=text, width=size, height=size, corner_radius=size // 2,
                             fg_color=fg, hover_color=hover, text_color=color, font=T.font(14), command=cmd)

    def _stop_btn(self, master, compact):
        text = f"■ 停止\n{HOTKEY}" if compact else f"■  緊急停止　{HOTKEY}"
        return ctk.CTkButton(master, text=text, height=40 if compact else 38, width=96 if compact else 0,
                             corner_radius=12, fg_color=T.DANGER, hover_color=T.DANGER_HOVER,
                             text_color="white", font=T.font(10 if compact else 12, "bold"),
                             command=self.emergency_stop)

    def _mic_btn(self, master, size):
        b = RoundButton(master, text="", image=icons.mic(size // 2), width=size, height=size,
                          corner_radius=size // 2, fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER)
        b.bind("<ButtonPress-1>", self._mic_press)
        b.bind("<ButtonRelease-1>", self._mic_release)
        return b

    def _orb(self, master):
        return ctk.CTkLabel(master, text="●", width=18, font=T.font(16), text_color=T.OK)

    def _build(self):
        # ---- 待機スタイル(ピル型) ----
        self.pill = self._card()
        self.pill.grid_columnconfigure(1, weight=1)
        self.pill_orb = self._orb(self.pill)
        self.pill_orb.grid(row=0, column=0, rowspan=2, padx=(16, 8), pady=10)
        self.pill_name = ctk.CTkLabel(self.pill, text="", font=T.font(14, "bold"), text_color=T.TEXT,
                                      anchor="w", height=20)
        self.pill_name.grid(row=0, column=1, sticky="sw", pady=(10, 0))
        self.pill_status = ctk.CTkLabel(self.pill, text="", font=T.font(11), text_color=T.SUB,
                                        anchor="w", height=16)
        self.pill_status.grid(row=1, column=1, sticky="nw", pady=(0, 10))
        self.pill_mic = self._mic_btn(self.pill, 40)
        self.pill_mic.grid(row=0, column=2, rowspan=2, padx=4)
        self._stop_btn(self.pill, True).grid(row=0, column=3, rowspan=2, padx=4)
        self._icon_btn(self.pill, "▴", self._show_panel, size=28).grid(row=0, column=4, rowspan=2, padx=(0, 10))
        for w in (self.pill, self.pill_name, self.pill_status, self.pill_orb):
            self._draggable(w)
        self.pill_name.bind("<Double-Button-1>", lambda e: self._show_panel())

        # ---- 会話パネル ----
        self.panel = self._card()
        p = self.panel
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(p, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        head.grid_columnconfigure(1, weight=1)
        self.orb = self._orb(head)
        self.orb.grid(row=0, column=0, rowspan=2, padx=(0, 8))
        self.title_label = ctk.CTkLabel(head, text="", font=T.font(15, "bold"), text_color=T.TEXT,
                                        anchor="w", height=20)
        self.title_label.grid(row=0, column=1, sticky="w")
        self.status = ctk.CTkLabel(head, text="", font=T.font(11), text_color=T.SUB, anchor="w", height=16)
        self.status.grid(row=1, column=1, sticky="w")
        self._icon_btn(head, "⚙", self.open_settings, size=30).grid(row=0, column=2, rowspan=2)
        self._icon_btn(head, "▾", self._show_pill, size=30).grid(row=0, column=3, rowspan=2)
        self._icon_btn(head, "✕", self.quit_app, size=30).grid(row=0, column=4, rowspan=2)
        for w in (head, self.title_label, self.status):
            self._draggable(w)

        self.chat = ctk.CTkScrollableFrame(p, fg_color="transparent", scrollbar_button_color=T.BORDER)
        self.chat.grid(row=1, column=0, sticky="nsew", padx=8)
        self.chat.grid_columnconfigure(0, weight=1)
        self._bubbles = []

        box = ctk.CTkFrame(p, fg_color=T.SURFACE, corner_radius=14)
        box.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 8))
        box.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(box, placeholder_text=f"{config.AI_NAME}に話しかける…", border_width=0,
                                  fg_color="transparent", font=T.font(12), text_color=T.TEXT, height=36)
        self.entry.grid(row=0, column=0, sticky="ew", padx=(10, 0))
        self.entry.bind("<Return>", lambda e: self._send_entry())
        send = self._icon_btn(box, "", self._send_entry, size=32, fg=T.ACCENT, hover=T.ACCENT_HOVER)
        send.configure(image=icons.send())
        send.grid(row=0, column=1, padx=4, pady=4)

        ctl = ctk.CTkFrame(p, fg_color="transparent")
        ctl.grid(row=3, column=0, sticky="ew", padx=12)
        ctl.grid_columnconfigure(1, weight=1)
        self.mic = self._mic_btn(ctl, 44)
        self.mic.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        self.mode = ctk.CTkSegmentedButton(ctl, values=[MODE_HOLD, MODE_TOGGLE], command=self._mode_changed,
                                           font=T.font(11), height=26, selected_color=T.ACCENT,
                                           selected_hover_color=T.ACCENT_HOVER, unselected_color=T.SURFACE,
                                           fg_color=T.SURFACE)
        self.mode.set(config.INPUT_MODE if config.INPUT_MODE in (MODE_HOLD, MODE_TOGGLE) else MODE_HOLD)
        self.mode.grid(row=0, column=1, sticky="w")
        self.wake = ctk.CTkSwitch(ctl, text="ウェイクワードで起動", font=T.font(11), text_color=T.SUB,
                                  progress_color=T.ACCENT, switch_width=34, switch_height=18,
                                  command=self._wake_changed)
        self.wake.grid(row=1, column=1, sticky="w", pady=(4, 0))

        self._stop_btn(p, False).grid(row=4, column=0, sticky="ew", padx=12, pady=(10, 14))

    def _draggable(self, w):
        w.bind("<ButtonPress-1>", self._drag_start, add="+")
        w.bind("<B1-Motion>", self._drag_move, add="+")

    def _scaling(self):
        try:
            return ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            return 1.0

    def _place(self, w, h):
        """右下を基準に配置(サイズが変わっても右下の位置を保つ)。"""
        s = self._scaling()
        if getattr(self, "_anchor", None) is None:
            self._anchor = (int(self.winfo_screenwidth() / s) - config.MARGIN_X,
                            int(self.winfo_screenheight() / s) - config.MARGIN_Y)
        ax, ay = self._anchor
        self.geometry(f"{w}x{h}+{ax - w}+{ay - h}")

    def _show_pill(self):
        self._expanded = False
        self.panel.pack_forget()
        self.pill.pack(fill="both", expand=True)
        self._place(PILL_W, PILL_H)

    def _show_panel(self):
        self._expanded = True
        self.pill.pack_forget()
        self.panel.pack(fill="both", expand=True)
        self._place(PANEL_W, PANEL_H)
        self.entry.focus_set()

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _drag_move(self, e):
        x, y = e.x_root - self._dx, e.y_root - self._dy
        self.geometry(f"+{x}+{y}")
        s = self._scaling()
        self._anchor = (int((x + self.winfo_width()) / s), int((y + self.winfo_height()) / s))

    # ---- 会話表示: kind = user / ai / sys ----
    def _log(self, text, kind="sys"):
        row = len(self._bubbles)
        if kind == "sys":
            w = ctk.CTkLabel(self.chat, text=text, font=T.font(10), text_color=T.SUB, wraplength=300)
            w.grid(row=row, column=0, pady=2)
        else:
            user = kind == "user"
            w = ctk.CTkLabel(self.chat, text=text, font=T.font(12), wraplength=240, justify="left",
                             fg_color=T.ACCENT if user else T.SURFACE, text_color="white" if user else T.TEXT,
                             corner_radius=14, padx=12, pady=7)
            w.grid(row=row, column=0, sticky="e" if user else "w", padx=4, pady=3)
            if not user:
                self.pill_status.configure(text=_short(text))
        self._bubbles.append(w)
        if len(self._bubbles) > MAX_BUBBLES:
            self._bubbles.pop(0).destroy()
        self.after(20, lambda: self.chat._parent_canvas.yview_moveto(1.0))

    def _post_log(self, text):  # 任意のスレッドから呼べる
        self._events.put(lambda: self._log(text, "sys"))

    def _set_state(self, state):
        self._state = state
        label, color, _ = STATES[state]
        for orb in (self.orb, self.pill_orb):
            orb.configure(text_color=color)
        self.status.configure(text=label)
        if state != "idle" or self.pill_status.cget("text") in ("", *(v[0] for v in STATES.values())):
            self.pill_status.configure(text=label)

    def _animate(self):
        _, color, blink = STATES[self._state]
        self._blink = (self._blink + 1) % 16
        c = T.BORDER if blink and self._blink >= 8 else color
        for orb in (self.orb, self.pill_orb):
            orb.configure(text_color=c)

    # ================= 入力 =================
    def _send_entry(self):
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, "end")
            self._submit(text)

    def _submit(self, text):
        self._log(text, "user")
        self.worker.submit(text)
        self._set_state("think")

    def _on_voice(self, text):
        if self.wake.get():
            cmd = strip_wake_word(text)
            if not cmd:
                self._log(f"(無視) {text}", "sys")
                self._set_state("idle")
                return
            text = cmd
        self._submit(text)

    def _mic_press(self, _):
        if self.mode.get() == MODE_HOLD or not self._recording:
            self._start_rec()
        else:
            self._stop_rec()

    def _mic_release(self, _):
        if self.mode.get() == MODE_HOLD and self._recording:
            self._stop_rec()

    def _paint_mic(self, active):
        for b in (self.mic, self.pill_mic):
            b.configure(fg_color=T.DANGER if active else T.ACCENT)

    def _start_rec(self):
        self.speaker.stop()
        self.voice.start_manual()
        self._recording = True
        self._paint_mic(True)
        self._set_state("listen")

    def _stop_rec(self):
        self.voice.stop_manual()
        self._recording = False
        self._paint_mic(False)
        self._set_state("recog")

    def _mode_changed(self, value):
        if self._recording:
            self._stop_rec()
        config.save({"INPUT_MODE": value})

    def _wake_changed(self):
        on = bool(self.wake.get())
        self.voice.set_wake(on)
        config.save({"WAKE_ENABLED": on})
        self._log(f"ウェイクワード ON ─「{config.WAKE_WORDS[0]}、{config.AI_NAME}、〜」" if on
                  else "ウェイクワード OFF", "sys")

    # ================= 設定 =================
    def open_settings(self):
        if getattr(self, "_settings", None) and self._settings.winfo_exists():
            self._settings.focus()
            return
        self._settings = SettingsWindow(self, on_saved=self._settings_saved)

    def _settings_saved(self):
        self.worker.restart()  # 推論プロセスに新しい設定を読ませる
        self._refresh_title()
        self._log("設定を保存しました", "sys")
        self._set_state("idle")

    def _refresh_title(self):
        for w in (self.title_label, self.pill_name):
            w.configure(text=config.AI_NAME)
        self.entry.configure(placeholder_text=f"{config.AI_NAME}に話しかける…")

    # ================= 緊急停止 =================
    def emergency_stop(self):
        """どのスレッドからでも呼べる。推論・PC操作プロセスを強制終了する。"""
        self.voice.cancel()
        self.speaker.stop()
        self.worker.kill()
        self._events.put(self._after_stop)

    def _after_stop(self):
        self._recording = False
        self._paint_mic(False)
        self._log("⚠ 緊急停止しました", "sys")
        self._set_state("stop")

    # ================= ループ =================
    def _pump(self):
        while True:
            try:
                self._events.get_nowait()()
            except queue.Empty:
                break
        for kind, text in self.worker.poll():
            if kind == "reply":
                self._log(text, "ai")
                self.speaker.say(text)
            else:
                self._log(f"エラー: {text}", "sys")
        if self._state == "think" and not self.worker.pending:
            self._set_state("idle")
        self._animate()
        self.after(50, self._pump)

    def quit_app(self):
        self.worker.close()
        self.destroy()


def _short(text, n=22):
    text = text.replace("\n", " ")
    return text if len(text) <= n else text[:n] + "…"


if __name__ == "__main__":
    mp.freeze_support()
    App().mainloop()
