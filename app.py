"""常駐型UI。起動: zealous.pyw をダブルクリック
待機中は横長の楕円(左:マイク / 中央:ロゴと状態 / 右:会話)で常駐し、ドラッグで移動できる。
会話パネルは常駐位置に応じて、画面の内側へ向かって展開する。
緊急停止ボタンは操作中だけ表示する(Ctrl+Shift+E+S は常に有効)。"""
import math
import multiprocessing as mp
import os
import queue
import threading

import customtkinter as ctk

import config
import icons
import runtime
import updater
import shortcut
import theme as T
from agent_worker import AgentWorker
from settings_window import SettingsWindow
from tts import Speaker
from voice import VoiceInput
from wakeword import strip_wake_word

MODE_HOLD = "トランシーバー"
HOTKEY = "+".join(k.capitalize() for k in config.EMERGENCY_KEYS)
PILL_W, PILL_H = 200, 52
PANEL_W, PANEL_H = 300, 400
INPUT_MAX_LINES = 4
MAX_BUBBLES = 40

# 状態 -> (表示, 色, 点滅するか)
STATES = {
    "idle": ("待機中", T.OK, False),
    "listen": ("聞き取り中", T.DANGER, True),
    "recog": ("認識中", T.CYAN, True),
    "think": ("応答待ち", T.ACCENT, False),
    "stop": ("停止しました", T.WARN, False),
}
BUSY = ("think",)  # 緊急停止ボタンを出す状態


class RoundButton(ctk.CTkButton):
    """真円ボタン(CTkButton は角丸半径ぶん横幅が広がるため、その余白を消す)。"""

    def _create_grid(self):
        super()._create_grid()
        for c in (0, 4):
            self.grid_columnconfigure(c, minsize=0)


class DotSpinner(ctk.CTkCanvas):
    """3つのドットが波打つローディング表示。tick() を一定間隔で呼んで動かす。"""

    def __init__(self, master, bg, dot=5, gap=4):
        self._d, self._g = dot, gap
        super().__init__(master, width=dot * 3 + gap * 2, height=dot * 3, bg=bg, highlightthickness=0)
        self._t = 0

    def tick(self):
        self._t += 1
        self.delete("all")
        d, h = self._d, self._d * 3
        for i, col in enumerate((T.ACCENT, "#5b8cff", T.CYAN)):
            lift = max(0.0, math.sin(self._t * 0.35 - i * 0.9))  # 順番に跳ねる
            y = h - d - lift * d * 1.6
            x = i * (d + self._g)
            self.create_oval(x, y, x + d, y + d, fill=col, outline="")


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

        threading.Thread(target=runtime.start_services, daemon=True).start()  # Ollama / VOICEVOX
        if os.name == "nt":
            config.AUTOSTART = shortcut.is_autostart()
        self.worker = AgentWorker()
        self.speaker = Speaker(on_error=self._post_log)
        self.voice = VoiceInput(on_text=lambda t: self._events.put(lambda: self._on_voice(t)),
                                on_status=self._post_log)
        try:
            import stopper
            stopper.register(self.emergency_stop)
        except Exception as e:
            self._log(f"ショートカット登録エラー: {e}")
        self._apply_settings()
        self._set_state("idle")
        self._update_info = None
        if config.AUTO_UPDATE and updater.FROZEN:
            self.after(5000, self.check_update)
        self.after(50, self._pump)

    # ================= 画面 =================
    def _round(self, master, size, image, cmd=None, fg="transparent", hover=T.SURFACE):
        return RoundButton(master, text="", image=image, width=size, height=size, corner_radius=size // 2,
                           fg_color=fg, hover_color=hover, command=cmd)

    def _mic(self, master, size):
        b = self._round(master, size, icons.mic(size * 9 // 20), fg=T.ACCENT, hover=T.ACCENT_HOVER)
        b.bind("<ButtonPress-1>", self._mic_press)
        b.bind("<ButtonRelease-1>", self._mic_release)
        return b

    def _stop(self, master, **kw):
        return ctk.CTkButton(master, corner_radius=14, fg_color=T.DANGER, hover_color=T.DANGER_HOVER,
                             text_color="white", command=self.emergency_stop, **kw)

    def _status_row(self, master):
        row = ctk.CTkFrame(master, fg_color="transparent")
        dot = ctk.CTkLabel(row, text="●", font=T.font(8), text_color=T.OK, width=8, height=12)
        dot.pack(side="left", padx=(0, 4))
        text = ctk.CTkLabel(row, text="", font=T.font(10), text_color=T.SUB, height=12)
        text.pack(side="left")
        return row, dot, text

    def _build(self):
        # ---- 待機スタイル: 横長の楕円 ----
        self.pill = ctk.CTkFrame(self, fg_color=T.BG, bg_color=T.KEY, corner_radius=PILL_H // 2,
                                 border_width=1, border_color=T.BORDER)
        self.pill.grid_columnconfigure(1, weight=1)
        self.pill.grid_rowconfigure(0, weight=1)
        self.pill_mic = self._mic(self.pill, PILL_H - 12)
        self.pill_mic.grid(row=0, column=0, padx=(6, 0))
        chat_btn = self._round(self.pill, PILL_H - 12, icons.chat(18), self._show_panel, fg=T.SURFACE,
                               hover=T.BORDER)
        chat_btn.grid(row=0, column=2, padx=(0, 6))
        # アップデートがあるときに会話ボタンの右上に出す印
        self.badge = ctk.CTkLabel(self.pill, text="●", font=T.font(10), text_color=T.CYAN,
                                  fg_color="transparent", width=10, height=10)

        self.center = ctk.CTkFrame(self.pill, fg_color="transparent")
        self.center.grid(row=0, column=1)
        emb = ctk.CTkLabel(self.center, text="", image=icons.emblem(26), width=26)
        emb.grid(row=0, column=0, rowspan=2, padx=(0, 5))
        self.pill_logo = ctk.CTkLabel(self.center, text="", height=12)
        self.pill_logo.grid(row=0, column=1, sticky="sw")
        row, self.pill_dot, self.pill_status = self._status_row(self.center)
        row.grid(row=1, column=1, sticky="nw", pady=(2, 0))
        self.pill_busy = ctk.CTkFrame(self.pill, fg_color="transparent")
        self.pill_spin = DotSpinner(self.pill_busy, T.BG, dot=6, gap=5)
        self.pill_spin.pack(pady=(0, 3))
        self.pill_stop = self._stop(self.pill_busy, text=f"■ 停止  {HOTKEY}", width=PILL_W - 2 * PILL_H + 4,
                                    height=18, font=T.font(8, "bold"))
        self.pill_stop.configure(corner_radius=9)
        self.pill_stop.pack()
        for w in (self.pill, self.center, emb, self.pill_logo, row, self.pill_dot, self.pill_status,
                  self.pill_busy, self.pill_spin):
            self._draggable(w)

        # ---- 会話パネル ----
        self.panel = ctk.CTkFrame(self, fg_color=T.BG, bg_color=T.KEY, corner_radius=20,
                                  border_width=1, border_color=T.BORDER)
        p = self.panel
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(p, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        head.grid_columnconfigure(1, weight=1)
        emb2 = ctk.CTkLabel(head, text="", image=icons.emblem(34), width=34)
        emb2.grid(row=0, column=0, rowspan=2, padx=(0, 8))
        self.panel_logo = ctk.CTkLabel(head, text="", height=14)
        self.panel_logo.grid(row=0, column=1, sticky="sw")
        row2, self.dot, self.status = self._status_row(head)
        row2.grid(row=1, column=1, sticky="nw", pady=(3, 0))
        self.head_spin = DotSpinner(row2, T.BG, dot=4, gap=3)
        self._round(head, 30, icons.gear(18), self.open_settings).grid(row=0, column=2, rowspan=2)
        for w in (head, emb2, self.panel_logo, row2, self.dot, self.status):
            self._draggable(w)

        self.chat = ctk.CTkScrollableFrame(p, fg_color="transparent", scrollbar_button_color=T.BORDER)
        self.chat.grid(row=1, column=0, sticky="nsew", padx=6)
        self.chat.grid_columnconfigure(0, weight=1)
        self._bubbles = []
        self.typing = ctk.CTkFrame(self.chat, fg_color=T.SURFACE, corner_radius=14)
        self.typing_spin = DotSpinner(self.typing, T.SURFACE, dot=6, gap=5)
        self.typing_spin.pack(padx=14, pady=10)

        box = ctk.CTkFrame(p, fg_color=T.SURFACE, corner_radius=18)
        box.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 6))
        box.grid_columnconfigure(1, weight=1)
        self.mic = self._mic(box, 32)
        self.mic.grid(row=0, column=0, padx=4, pady=4, sticky="s")
        self.entry = ctk.CTkTextbox(box, border_width=0, fg_color="transparent", font=T.font(12),
                                    text_color=T.TEXT, height=30, wrap="char", activate_scrollbars=False)
        self.entry.grid(row=0, column=1, sticky="ew", padx=2, pady=4)
        self.entry.bind("<Return>", self._on_return)
        self.entry.bind("<KeyRelease>", lambda e: self._fit_input())
        self.entry.bind("<FocusIn>", lambda e: self._fit_input())
        self.entry.bind("<FocusOut>", lambda e: self._fit_input())
        self.hint = ctk.CTkLabel(box, text="", font=T.font(12), text_color=T.SUB, height=20)
        self.hint.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.send_btn = self._round(box, 34, icons.send(18), self._send_entry, fg=T.ACCENT, hover=T.ACCENT_HOVER)
        self.send_btn.grid(row=0, column=2, padx=3, pady=3, sticky="s")
        tip = ctk.CTkLabel(p, text="Enter で送信 ・ Shift+Enter で改行", font=T.font(9), text_color=T.SUB,
                           height=12)
        tip.grid(row=3, column=0, sticky="w", padx=22)

        foot = ctk.CTkFrame(p, fg_color="transparent", height=36)
        foot.grid(row=4, column=0, sticky="ew", padx=10, pady=(4, 10))
        foot.grid_columnconfigure(0, weight=1)
        self.panel_stop = self._stop(foot, text=f"■  緊急停止　{HOTKEY}", height=32, font=T.font(11, "bold"))
        self._round(foot, 32, icons.close(12), self._show_pill, fg=T.SURFACE,
                    hover=T.BORDER).grid(row=0, column=1, padx=(8, 0))

    def _draggable(self, w):
        w.bind("<ButtonPress-1>", self._drag_start, add="+")
        w.bind("<B1-Motion>", self._drag_move, add="+")
        w.bind("<ButtonRelease-1>", self._drag_end, add="+")

    def _scaling(self):
        try:
            return ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            return 1.0

    # 位置は画面の実ピクセル、サイズは CTk の論理ピクセル(×scaling で実ピクセル)で扱う
    def _px(self, v):
        return round(v * self._scaling())

    def _screen(self):
        return self.winfo_screenwidth(), self.winfo_screenheight()

    def _clamp(self, x, y, w, h):
        sw, sh = self._screen()
        return max(0, min(x, sw - w)), max(0, min(y, sh - h))

    def _default_pos(self):
        sw, sh = self._screen()
        return (sw - self._px(PILL_W + config.MARGIN_X), sh - self._px(PILL_H + config.MARGIN_Y))

    def _show_pill(self):
        self._expanded = False
        self.panel.pack_forget()
        self.pill.pack(fill="both", expand=True)
        if getattr(self, "_pos", None) is None:
            pos = config.WINDOW_POS
            self._pos = tuple(pos) if pos else self._default_pos()
        self._pos = self._clamp(*self._pos, self._px(PILL_W), self._px(PILL_H))
        self.geometry(f"{PILL_W}x{PILL_H}+{self._pos[0]}+{self._pos[1]}")

    def _panel_origin(self):
        """常駐位置が画面のどちら側にあるかで、パネルの伸びる向きを決める。"""
        sw, sh = self._screen()
        (x, y), pw, ph = self._pos, self._px(PILL_W), self._px(PILL_H)
        w, h = self._px(PANEL_W), self._px(PANEL_H)
        px = x + pw - w if x + pw / 2 > sw / 2 else x   # 右寄りなら右端を揃えて左へ
        py = y + ph - h if y + ph / 2 > sh / 2 else y   # 下寄りなら下端を揃えて上へ
        return self._clamp(px, py, w, h)

    def _show_panel(self):
        self._expanded = True
        self.badge.place_forget()  # 更新のお知らせはパネル内のカードで確認できる
        self.pill.pack_forget()
        self.panel.pack(fill="both", expand=True)
        x, y = self._panel_origin()
        self.geometry(f"{PANEL_W}x{PANEL_H}+{x}+{y}")
        self.entry.focus_set()

    def _drag_start(self, e):
        self._drag = (e.x_root, e.y_root, self.winfo_x(), self.winfo_y(), self._pos)

    def _drag_move(self, e):
        sx, sy, wx, wy, (px, py) = self._drag
        dx, dy = e.x_root - sx, e.y_root - sy
        x, y = self._clamp(wx + dx, wy + dy, self.winfo_width(), self.winfo_height())
        self.geometry(f"+{x}+{y}")
        # パネル表示中に動かした場合も、閉じたときの待機位置を同じだけ動かす
        self._pos = (px + x - wx, py + y - wy)

    def _drag_end(self, _):
        if getattr(self, "_drag", None):
            self._drag = None
            config.save({"WINDOW_POS": list(self._pos)})

    # ---- 会話表示: kind = user / ai / sys ----
    def _log(self, text, kind="sys"):
        row = len(self._bubbles)
        if kind == "sys":
            w = ctk.CTkLabel(self.chat, text=text, font=T.font(10), text_color=T.SUB, wraplength=240)
            w.grid(row=row, column=0, pady=2)
        else:
            user = kind == "user"
            w = ctk.CTkLabel(self.chat, text=text, font=T.font(12), wraplength=200, justify="left",
                             fg_color=T.ACCENT if user else T.SURFACE, text_color="white" if user else T.TEXT,
                             corner_radius=14, padx=10, pady=6)
            w.grid(row=row, column=0, sticky="e" if user else "w", padx=4, pady=3)
        self._add_widget(w, None)

    def _add_widget(self, w, sticky):
        """チャット欄の末尾に部品を追加する(sticky 指定時はここで配置)。"""
        if sticky:
            w.grid(row=len(self._bubbles), column=0, sticky=sticky, padx=4, pady=3)
        self._bubbles.append(w)
        if len(self._bubbles) > MAX_BUBBLES:  # 古いものを消し、行を詰め直す
            self._bubbles.pop(0).destroy()
            for i, b in enumerate(self._bubbles):
                b.grid_configure(row=i)
        if self.typing.winfo_manager():
            self.typing.grid_configure(row=len(self._bubbles))  # 入力中表示は常に最後尾
        self.after(20, lambda: self.chat._parent_canvas.yview_moveto(1.0))

    def _post_log(self, text):  # 任意のスレッドから呼べる
        self._events.put(lambda: self._log(text, "sys"))

    def _set_state(self, state):
        self._state = state
        label, color, _ = STATES[state]
        for t in (self.status, self.pill_status):
            t.configure(text=label)
        for d in (self.dot, self.pill_dot):
            d.configure(text_color=color)
        busy = state in BUSY
        if busy:  # 操作中だけ緊急停止ボタンとローディング表示を出す
            self.center.grid_remove()
            self.pill_busy.grid(row=0, column=1)
            self.panel_stop.grid(row=0, column=0, sticky="ew")
            self.dot.pack_forget()
            self.head_spin.pack(side="left", padx=(0, 5), before=self.status)
            self.typing.grid(row=len(self._bubbles), column=0, sticky="w", padx=4, pady=3)
            self.after(20, lambda: self.chat._parent_canvas.yview_moveto(1.0))
        else:
            self.pill_busy.grid_remove()
            self.panel_stop.grid_remove()
            self.center.grid()
            self.head_spin.pack_forget()
            self.dot.pack(side="left", padx=(0, 4), before=self.status)
            self.typing.grid_remove()

    def _animate(self):
        if self._state in BUSY:
            for sp in (self.pill_spin, self.head_spin, self.typing_spin):
                sp.tick()
        _, color, blink = STATES[self._state]
        self._blink = (self._blink + 1) % 16
        c = T.BORDER if blink and self._blink >= 8 else color
        for d in (self.dot, self.pill_dot):
            d.configure(text_color=c)

    # ================= 入力 =================
    def _on_return(self, e):
        if e.state & 0x0001:  # Shift+Enter: 改行(既定の動作)
            self.after(1, self._fit_input)
            return None
        self._send_entry()
        return "break"

    def _send_entry(self):
        text = self.entry.get("1.0", "end").strip()
        if text:
            self.entry.delete("1.0", "end")
            self._fit_input()
            self._submit(text)

    def _fit_input(self):
        """入力行数に合わせて高さを変え、空欄ならヒントを表示する。"""
        tb = self.entry._textbox
        lines = tb.count("1.0", "end-1c", "displaylines")
        n = max(1, min(INPUT_MAX_LINES, (lines[0] if lines else 0) + 1))
        self.entry.configure(height=12 + n * 18)
        empty = not self.entry.get("1.0", "end").strip()
        if empty and self.focus_get() is not tb:
            self.hint.grid(row=0, column=1, sticky="w", padx=8)
        else:
            self.hint.grid_remove()

    def _submit(self, text):
        self._log(text, "user")
        self.worker.submit(text)
        self._set_state("think")

    def _on_voice(self, text):
        if config.WAKE_ENABLED:
            cmd = strip_wake_word(text)
            if not cmd:
                self._log(f"(無視) {text}")
                self._set_state("idle")
                return
            text = cmd
        self._submit(text)

    def _mic_press(self, _):
        if config.INPUT_MODE == MODE_HOLD or not self._recording:
            self._start_rec()
        else:
            self._stop_rec()

    def _mic_release(self, _):
        if config.INPUT_MODE == MODE_HOLD and self._recording:
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

    # ================= 設定 =================
    def open_settings(self):
        if getattr(self, "_settings", None) and self._settings.winfo_exists():
            self._settings.focus()
            return
        self._settings = SettingsWindow(self, on_saved=self._settings_saved, on_quit=self.quit_app,
                                        on_check_update=lambda report: self.check_update(True, report))

    def _settings_saved(self):
        self.worker.restart()  # 推論プロセスに新しい設定を読ませる
        self._apply_settings()
        self._log("設定を保存しました")
        self._set_state("idle")

    def _apply_settings(self):
        self.pill_logo.configure(image=icons.wordmark(config.AI_NAME, 9))
        self.panel_logo.configure(image=icons.wordmark(config.AI_NAME, 13))
        self.hint.configure(text=f"{config.AI_NAME} にメッセージ…")
        self._fit_input()
        if self._recording:
            self._stop_rec()
        self.voice.set_wake(config.WAKE_ENABLED)

    # ================= アップデート =================
    def check_update(self, manual=False, report=None):
        """裏で最新版を確認する。自動確認は1日ごとに繰り返す。report(文字列) は設定画面への結果表示。"""
        def run():
            try:
                info = updater.check()
            except Exception as e:
                info, msg = None, f"確認できませんでした: {e}"
            else:
                msg = f"v{info['version']} があります" if info else f"最新版です (v{updater.VERSION})"
            self._events.put(lambda: self._update_found(info, manual))
            if report:
                report(msg)
        threading.Thread(target=run, daemon=True).start()
        if not manual:
            self.after(24 * 3600 * 1000, self.check_update)

    def _update_found(self, info, manual):
        if not info or (self._update_info and self._update_info["version"] == info["version"] and not manual):
            return
        self._update_info = info
        self.badge.place(relx=1.0, x=-12, y=6, anchor="ne")
        card = ctk.CTkFrame(self.chat, fg_color=T.SURFACE, corner_radius=14, border_width=1, border_color=T.ACCENT)
        ctk.CTkLabel(card, text=f"新しいバージョン v{info['version']} があります", font=T.font(11, "bold"),
                     text_color=T.TEXT).pack(anchor="w", padx=12, pady=(8, 0))
        if info["notes"]:
            ctk.CTkLabel(card, text=info["notes"][:160], font=T.font(10), text_color=T.SUB, wraplength=220,
                         justify="left").pack(anchor="w", padx=12)
        self._upd_note = ctk.CTkLabel(card, text="設定とAIモデルはそのまま引き継がれます", font=T.font(9),
                                      text_color=T.SUB)
        self._upd_note.pack(anchor="w", padx=12)
        self._upd_btn = ctk.CTkButton(card, text="今すぐアップデート", height=28, corner_radius=14,
                                      fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER, font=T.font(11, "bold"),
                                      command=self.install_update)
        self._upd_btn.pack(fill="x", padx=12, pady=(6, 10))
        self._add_widget(card, "w")

    def install_update(self):
        info = self._update_info
        if not info:
            return
        self._upd_btn.configure(state="disabled", text="ダウンロード中…")

        def progress(ratio, text):
            self._events.put(lambda: self._upd_note.configure(text=text))

        def run():
            try:
                updater.install(info, progress)
            except Exception as e:
                err = f"失敗: {e}"
                self._events.put(lambda: (self._upd_note.configure(text=err),
                                          self._upd_btn.configure(state="normal", text="もう一度")))
                return
            self._events.put(self.quit_app)  # インストーラーが入れ替えて再起動する
        threading.Thread(target=run, daemon=True).start()

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
        self._log("⚠ 緊急停止しました")
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
                self._log(f"エラー: {text}")
        if self._state == "think" and not self.worker.pending:
            self._set_state("idle")
        self._animate()
        self.after(50, self._pump)

    def quit_app(self):
        self.worker.close()
        runtime.stop_services()
        self.destroy()


if __name__ == "__main__":
    mp.freeze_support()
    App().mainloop()
