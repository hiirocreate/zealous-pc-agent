"""常駐型UI。起動: python app.py"""
import multiprocessing as mp
import queue

import customtkinter as ctk

import config
from agent_worker import AgentWorker
from settings_window import SettingsWindow
from tts import Speaker
from voice import VoiceInput
from wakeword import strip_wake_word

MODE_HOLD, MODE_TOGGLE = "トランシーバー", "トグル"
STOP_LABEL = "■ 緊急停止  (" + "+".join(k.capitalize() for k in config.EMERGENCY_KEYS) + ")"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._events = queue.Queue()  # 他スレッド -> UIスレッドへの処理依頼
        self._recording = False

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self._build()
        self._place_bottom_right()

        self.worker = AgentWorker()
        self.speaker = Speaker(on_error=self._post_log)
        self.voice = VoiceInput(on_text=lambda t: self._events.put(lambda: self._on_voice(t)),
                                on_status=self._post_log)
        try:
            import stopper
            stopper.register(self.emergency_stop)
        except Exception as e:
            self._log(f"ショートカット登録エラー: {e}")
        self._refresh_title()
        if config.WAKE_ENABLED:
            self.wake.select()
            self.voice.set_wake(True)
        self._set_status("待機中")
        self.after(50, self._pump)

    # ---------------- 画面 ----------------
    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(self, height=26, corner_radius=0)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        self.title_label = ctk.CTkLabel(head, text="", font=("", 13, "bold"))
        self.title_label.grid(row=0, column=0, padx=8)
        self.status = ctk.CTkLabel(head, text="", text_color="gray70")
        self.status.grid(row=0, column=1, sticky="w")
        ctk.CTkButton(head, text="⚙", width=26, height=22, fg_color="transparent", text_color=("gray20", "gray85"),
                      command=self.open_settings).grid(row=0, column=2)
        ctk.CTkButton(head, text="✕", width=26, height=22, fg_color="transparent", text_color=("gray20", "gray85"),
                      command=self.quit_app).grid(row=0, column=3, padx=(0, 4))
        for w in (head, self.status, self.title_label):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        self.logbox = ctk.CTkTextbox(self, height=100, wrap="char", state="disabled")
        self.logbox.grid(row=1, column=0, sticky="ew", padx=6, pady=(6, 4))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=6)
        row.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(row, placeholder_text="命令を入力…")
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda e: self._send_entry())
        ctk.CTkButton(row, text="送信", width=50, command=self._send_entry).grid(row=0, column=1, padx=(4, 0))

        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.grid(row=3, column=0, sticky="ew", padx=6, pady=4)
        self.mic = ctk.CTkButton(row2, text="🎤", width=46, height=32, font=("", 18))
        self.mic.grid(row=0, column=0)
        self.mic.bind("<ButtonPress-1>", self._mic_press)
        self.mic.bind("<ButtonRelease-1>", self._mic_release)
        self.mode = ctk.CTkSegmentedButton(row2, values=[MODE_HOLD, MODE_TOGGLE], command=self._mode_changed)
        self.mode.set(config.INPUT_MODE if config.INPUT_MODE in (MODE_HOLD, MODE_TOGGLE) else MODE_HOLD)
        self.mode.grid(row=0, column=1, padx=6)
        self.wake = ctk.CTkSwitch(row2, text="ウェイク", width=40, command=self._wake_changed)
        self.wake.grid(row=0, column=2)

        ctk.CTkButton(self, text=STOP_LABEL, height=34, fg_color="#d62828", hover_color="#a4161a",
                      font=("", 13, "bold"), command=self.emergency_stop
                      ).grid(row=4, column=0, sticky="ew", padx=6, pady=(2, 6))

    def _place_bottom_right(self):
        try:
            s = ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            s = 1.0
        x = int(self.winfo_screenwidth() / s) - config.WINDOW_W - config.MARGIN_X
        y = int(self.winfo_screenheight() / s) - config.WINDOW_H - config.MARGIN_Y
        self.geometry(f"{config.WINDOW_W}x{config.WINDOW_H}+{x}+{y}")

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _log(self, text):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", text + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _post_log(self, text):  # 任意のスレッドから呼べる
        self._events.put(lambda: self._log(text))

    def _set_status(self, text):
        self.status.configure(text=text)

    # ---------------- 入力 ----------------
    def _send_entry(self):
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, "end")
            self._submit(text)

    def _submit(self, text):
        self._log(f"あなた: {text}")
        self.worker.submit(text)
        self._set_status("考え中…")

    def _on_voice(self, text):
        if self.wake.get():
            cmd = strip_wake_word(text)
            if not cmd:
                self._log(f"(無視) {text}")
                self._set_status("待機中")
                return
            text = cmd
        self._submit(text)

    def _mic_press(self, _):
        if self.mode.get() == MODE_HOLD:
            self._start_rec()
        elif self._recording:
            self._stop_rec()
        else:
            self._start_rec()

    def _mic_release(self, _):
        if self.mode.get() == MODE_HOLD and self._recording:
            self._stop_rec()

    def _start_rec(self):
        self.speaker.stop()
        self.voice.start_manual()
        self._recording = True
        self.mic.configure(fg_color="#e63946")
        self._set_status("録音中…")

    def _stop_rec(self):
        self.voice.stop_manual()
        self._recording = False
        self.mic.configure(fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"])
        self._set_status("認識中…")

    def _mode_changed(self, value):
        if self._recording:
            self._stop_rec()
        config.save({"INPUT_MODE": value})

    def _wake_changed(self):
        on = bool(self.wake.get())
        self.voice.set_wake(on)
        config.save({"WAKE_ENABLED": on})
        self._log(f"ウェイクワード: {'ON(常時待ち受け)' if on else 'OFF'}"
                  + (f" ─「{config.WAKE_WORDS[0]}、{config.AI_NAME}、〜」" if on else ""))

    # ---------------- 設定 ----------------
    def open_settings(self):
        if getattr(self, "_settings", None) and self._settings.winfo_exists():
            self._settings.focus()
            return
        self._settings = SettingsWindow(self, on_saved=self._settings_saved)

    def _settings_saved(self):
        self.worker.restart()  # 推論プロセスに新しい設定を読ませる
        self._refresh_title()
        self._log("設定を保存しました")
        self._set_status("待機中")

    def _refresh_title(self):
        self.title_label.configure(text=f"🤖 {config.AI_NAME}")

    # ---------------- 緊急停止 ----------------
    def emergency_stop(self):
        """どのスレッドからでも呼べる。推論・PC操作プロセスを強制終了する。"""
        self.voice.cancel()
        self.speaker.stop()
        self.worker.kill()
        self._events.put(self._after_stop)

    def _after_stop(self):
        self._recording = False
        self.mic.configure(fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"])
        self._log("⚠ 緊急停止しました")
        self._set_status("停止")

    # ---------------- ループ ----------------
    def _pump(self):
        while True:
            try:
                self._events.get_nowait()()
            except queue.Empty:
                break
        for kind, text in self.worker.poll():
            if kind == "reply":
                self._log(f"AI: {text}")
                self.speaker.say(text)
            else:
                self._log(f"エラー: {text}")
        if not self._recording and self.status.cget("text") == "考え中…" and not self.worker.pending:
            self._refresh_title()
        if config.WAKE_ENABLED:
            self.wake.select()
            self.voice.set_wake(True)
        self._set_status("待機中")
        self.after(50, self._pump)

    def quit_app(self):
        self.worker.close()
        self.destroy()


if __name__ == "__main__":
    mp.freeze_support()
    App().mainloop()
