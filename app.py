"""常駐型UI。起動: zealous.pyw をダブルクリック(Zealous は1つだけ起動する)
待機中は横長の楕円(左:マイク / 中央:ロゴと状態 / 右:会話)で常駐し、ドラッグでどのモニターにも移動できる。
会話パネルは常駐位置から画面の内側へ、なめらかに広がる。大きさは端をドラッグして自由に変えられ、全画面にもできる。
チャットはスレッド(話題ごとの会話)で管理し、パネルが広いときは左に一覧、狭いときは ☰ で一覧を開く。
緊急停止ボタンは操作中だけ表示する(Ctrl+Shift+E+S は常に有効)。"""
import multiprocessing as mp
import os
import queue
import re
import threading
import time

import customtkinter as ctk
import tkinter as tk

import config
import icons
import runtime
import services
import shortcut
import theme as T
import threads
import tools
import updater
import voicevox
import winutil
import zlog
from agent_worker import AgentWorker
from llm import split_reply
from settings_window import SettingsWindow
from tts import Speaker
from voice import VoiceInput
from wakeword import strip_wake_word

MODE_HOLD = "トランシーバー"
HOTKEY = "+".join(k.capitalize() for k in config.EMERGENCY_KEYS)
PILL_W, PILL_H = 200, 52
# 待機中のウィジェットの形: (幅, 高さ, 角の丸み)
PILL_STYLES = {"standard": (200, 52, 26), "square": (112, 112, 24), "circle": (76, 76, 38)}


def pill_dims():
    return PILL_STYLES.get(getattr(config, "PILL_STYLE", "standard"), PILL_STYLES["standard"])
PANEL_MIN_W, PANEL_MIN_H = 300, 380
PANEL_R = 18           # パネルの角の丸み
SIDEBAR_W = 210        # スレッド一覧の幅
WIDE = 600             # パネルの幅がこれ以上なら、スレッド一覧を常に左に出す
GRIP = 6               # 端をつかんで大きさを変えられる幅
INPUT_MAX_LINES = 4
MAX_BUBBLES = 60
ANIM_FRAMES, ANIM_MS = 6, 8    # 展開・折りたたみの動き(コマ数・1コマの間隔)。全体で約0.1秒

# 状態 -> (表示, 色, 点滅するか)
STATES = {
    "idle": ("待機中", T.OK, False),
    "listen": ("聞き取り中", T.DANGER, True),
    "recog": ("認識中", T.CYAN, True),
    "think": ("応答待ち", T.ACCENT, False),
    "stop": ("停止しました", T.WARN, False),
}
BUSY = ("think",)  # 緊急停止ボタンを出す状態
# 「待機して」「待機モード」「小さくして」「おやすみ」など(短い言い方だけ。ほかの命令と取り違えない)
# 「会話を全部参照して答えて」「全部参照するのをやめて」: 会話をすべて参照するモードの切り替え
FULL_ON = re.compile(r"(?:会話|チャット|やりとり|やり取り|履歴)(?:の内容)?を?(?:全部|ぜんぶ|すべて|全て)(?:参照|覚えて|踏まえて|ふまえて|見て)"
                     r"(?:して)?(?:答えて|回答して|話して|ね|ください)|全部参照モード(?:に|を)?(?:して|オン|ON)")
FULL_OFF = re.compile(r"(?:全部|ぜんぶ|すべて|全て)(?:参照|覚えて)(?:する|るの|するの)?(?:のを|を)?(?:やめて|止めて|オフ|OFF)|"
                      r"全部参照モード(?:を)?(?:やめて|終わって|オフ|OFF|解除)")
# 「テクニカルモードにして」「通常モードに戻して」
TECH_ON = re.compile(r"(?:テクニカル|技術|開発|エンジニア)モード(?:に|へ)?(?:して|切り替えて|変えて|オン|ON|で)")
TECH_OFF = re.compile(r"(?:通常|普通|ふつう|いつも)の?モード(?:に|へ)?(?:戻して|もどして|して|切り替えて)|"
                      r"(?:テクニカル|技術|開発)モード(?:を)?(?:終わ|おわ|やめ|オフ|OFF|解除)")
STANDBY = re.compile(r"(?:もう|じゃあ|では|ちょっと|いったん|一旦)?(?:"
                     r"(?:待機|たいき|スタンバイ)(?:モード|状態)?(?:に)?(?:して|しといて|しておいて|戻って|入って|"
                     r"なって|して(?:ください|くれる|くれ|ね))?(?:ください)?|"
                     r"(?:小さく|ちいさく|縮小)(?:して)?(?:ください)?|"
                     r"(?:おやすみ|休んで|やすんで|休憩して)(?:ください|なさい)?)")
FOLLOW_SEC = 8    # 合図の言葉の後、続けて話しかけられる秒数(返事の読み上げが終わるたびに延長)


def _autohide_scrollbar(frame):
    """中身が収まっているときはスクロールバーを隠す(CTkScrollableFrame は常に出すため)。"""
    canvas, bar = frame._parent_canvas, frame._scrollbar

    def check(_=None):
        try:
            need = canvas.bbox("all") and canvas.bbox("all")[3] > canvas.winfo_height() + 1
            if need and not bar.winfo_ismapped():
                bar.grid()
            elif not need and bar.winfo_ismapped():
                bar.grid_remove()
                canvas.yview_moveto(0)
        except tk.TclError:
            pass
    frame.bind("<Configure>", lambda e: frame.after_idle(check), add="+")
    canvas.bind("<Configure>", lambda e: frame.after_idle(check), add="+")
    frame.after(200, check)


class RoundButton(ctk.CTkButton):
    """真円ボタン(CTkButton は角丸半径ぶん横幅が広がるため、その余白を消す)。"""

    def _create_grid(self):
        super()._create_grid()
        for c in (0, 4):
            self.grid_columnconfigure(c, minsize=0)


class DotSpinner(ctk.CTkLabel):
    """3つのドットが波打つローディング表示(なめらかに描いたコマ画像を順に切り替える)。
    tick() を一定間隔で呼んで動かす。"""

    PERIOD = 0.9  # 1周の秒数

    def __init__(self, master, dot=5, gap=4):
        self._frames = icons.dot_frames(dot, gap, count=54)
        super().__init__(master, text="", image=self._frames[0], fg_color="transparent")
        self._t = -1

    def tick(self):
        """時刻に合わせたコマを出す(処理が重くて呼ばれるのが遅れても、動きの速さは変わらない)。"""
        t = int((time.monotonic() % self.PERIOD) / self.PERIOD * len(self._frames))
        if t != self._t:
            self._t = t
            self.configure(image=self._frames[t])


class FrameSpinner(ctk.CTkLabel):
    """用意したコマ画像を、時刻に合わせて切り替えるローディング表示(コマは最初に一度だけ作る)。"""

    def __init__(self, master, frames, period, size):
        import loaders
        self._frames, self.PERIOD = frames, period
        super().__init__(master, text="", width=size[0], height=size[1], fg_color="transparent")
        self._t = -1
        loaders.warm()

    def tick(self):
        import loaders
        frames = loaders.ready(self._frames)  # 裏で作り終えるまでは何も出さない(画面を止めない)
        if not frames:
            return
        t = int((time.monotonic() % self.PERIOD) / self.PERIOD * len(frames))
        if t != self._t:
            self._t = t
            self.configure(image=frames[t])


def tech_spinner(master):
    """テクニカルモード: 回る二重のリングと、流れるデータの光。"""
    import loaders
    return FrameSpinner(master, loaders.tech, 1.6, (44, 18))


class App(ctk.CTk):
    # 合図の言葉で始めた音声の会話(起動中の _show_pill からも参照されるので、最初から用意しておく)
    _voice_session = False
    _follow_until = 0
    _voice_win = None  # 音声会話画面(開いているとき)
    _pending_confirm = None  # 実行前の確認を待っている操作 {"tool", "args", "what"}

    def __init__(self):
        ctk.set_appearance_mode(T.MODE)
        # 画面の拡大率の変化を確かめる間隔(既定の 0.1 秒ごとは、窓が多いと負担になる)
        ctk.ScalingTracker.update_loop_interval = 1000
        # 明るさ(ダーク/ライト)の確認も、既定の 0.03 秒ごとから1秒ごとに(1秒に30回起きていたのを減らす)
        ctk.AppearanceModeTracker.update_loop_interval = 1000
        super().__init__(fg_color=T.KEY)
        self._events = queue.Queue()  # 他スレッド -> UIスレッドへの処理依頼
        self._recording = False
        self._expanded = False
        self._maximized = False
        self._animating = False
        self._state = "idle"
        self._blink = 0
        self._stream = None           # 書きかけの返事 [吹き出し, ここまでの文字]
        self._pending_tid = None      # 返事を待っているスレッド
        self._update_info = None
        self.thread = threads.new()   # いま表示しているスレッド(最初の発言で保存される)

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        # Windows: 外枠(角丸・縁・影)はなめらかに描いた画像を後ろに重ね、本体は内側で切り抜く。
        # それ以外: 角の外側を透過色で抜く(縁は少し粗い)
        self.shell = winutil.Shell(self, T.BG, T.BORDER, enabled=config.SMOOTH_FRAME)
        self._bg = T.BG if self.shell.ok else T.KEY
        self.configure(fg_color=self._bg)
        if not self.shell.ok:
            try:
                self.attributes("-transparentcolor", T.KEY)
            except tk.TclError:
                pass
        self._build()
        self._show_pill(animate=False)
        for ms in (200, 600, 1500):  # 画面に出た後に、位置・大きさ・外枠をもう一度合わせる
            self.after(ms, self._settle)
        self.after(300, lambda: self._apply(*self._current_rect()))  # 画面に出た後に外枠(Windows)を整える
        for ms in (450, 1300):  # 画面に出た直後は中身が黒いまま描かれないことがあるので、描き直させる
            self.after(ms, self._repaint)

        # Ollama / VOICEVOX を裏で起動し、AIモデルと声を先に読み込んでおく(最初の返事を速くする)
        threading.Thread(target=lambda: (runtime.start_services(), runtime.warm_up()), daemon=True).start()
        if os.name == "nt":
            config.AUTOSTART = shortcut.is_autostart()
        self.worker = AgentWorker()
        import memory
        self.summarizer = memory.Summarizer()  # 古いやりとりを、空き時間に要約する
        self.speaker = Speaker(on_error=self._post_log)
        self.voice = VoiceInput(on_text=lambda t, b: self._events.put(lambda: self._on_voice(t, b)),
                                on_status=self._post_log)
        # ボタンで話したのに何も聞き取れなかったとき(何も言わずに止めたときなど)は、「認識中」から待機中へ戻す
        self.voice.on_nothing = lambda: self._events.put(
            lambda: self._state == "recog" and self._set_state("idle"))
        # 考え中・読み上げ中は待機中の聞き取りを休む(自分の声を拾わず、PC も重くならない)
        self.voice.should_listen = lambda: self._state != "think" and not self.speaker.busy
        self.voice.command_mode = lambda: self._following() or self._voice_win is not None
        self.voice.on_wake = lambda: self._events.put(self._heard_wake)
        self._tts_engine = config.TTS_ENGINE  # 読み上げのソフトを変えたかを見るため  # 合図の後の会話は命令として正確に聞き取る
        # 合図の言葉で話しかける設定のときだけ、命令用の聞き取りAIを前もって準備(使わない人のメモリを使わない)
        self.after(15000, lambda: config.WAKE_ENABLED and self.voice.preload())  # 命令用の聞き取りAIを前もって準備(初回はダウンロード)
        try:
            import stopper
            stopper.register(self.emergency_stop)
        except Exception as e:
            self._log(f"ショートカット登録エラー: {e}")
        self._apply_settings()
        self._set_state("idle")
        self._refresh_threads()
        if config.AUTO_UPDATE and updater.FROZEN:
            self.after(5000, self.check_update)
        self.after(50, self._pump)

    # ================= 画面の部品 =================
    def _round(self, master, size, image, cmd=None, fg="transparent", hover=T.SURFACE, tip=None):
        b = RoundButton(master, text="", image=image, width=size, height=size, corner_radius=size // 2,
                        fg_color=fg, hover_color=hover, command=cmd)
        if tip:  # マウスを乗せると、何のボタンか表示する
            import tooltip
            b._tip = tooltip.tip(b, tip)
        return b

    def _mic(self, master, size):
        b = self._round(master, size, icons.mic(size * 9 // 20), fg=T.ACCENT, hover=T.ACCENT_LIGHT,
                        tip="押して話す（もう一度押すか、離すと止まる）")
        b.bind("<ButtonPress-1>", self._mic_press)
        b.bind("<ButtonRelease-1>", self._mic_release)
        return b

    def _stop(self, master, **kw):
        return ctk.CTkButton(master, corner_radius=14, fg_color=T.DANGER, hover_color=T.DANGER_HOVER,
                             text_color="white", command=self.emergency_stop, **kw)

    def _status_row(self, master):
        row = ctk.CTkFrame(master, fg_color="transparent")
        dot = ctk.CTkLabel(row, text="", image=icons.dot(T.OK), width=8, height=12)
        dot.pack(side="left", padx=(0, 5))
        text = ctk.CTkLabel(row, text="", font=T.font(10), text_color=T.SUB, height=12)
        text.pack(side="left")
        return row, dot, text

    def _card(self, radius):
        # Windows では外枠(縁・影)を後ろの画像が描くので、こちらは縁なし
        return ctk.CTkFrame(self, fg_color=T.BG, bg_color=self._bg, corner_radius=radius,
                            border_width=0 if self.shell.ok else 1, border_color=T.BORDER)

    def _build(self):
        # ---- 待機表示(形は設定で選ぶ: 標準の横長 / 角の丸い正方形 / 円) ----
        self.pill = self._card(PILL_H // 2)
        # 標準(横長): マイク | ロゴと状態 | チャット
        self.pill_mic = self._round(self.pill, PILL_H - 12, icons.mic((PILL_H - 12) * 9 // 20), self.open_voice_mode,
                                    fg=T.ACCENT, hover=T.ACCENT_LIGHT, tip="音声で会話する")
        self.pill_chat = self._round(self.pill, PILL_H - 12, icons.chat(18, icons.INK), self._show_panel, fg=T.SURFACE,
                                     hover=T.BORDER, tip="チャットを開く")
        # アップデートがあるときに会話ボタンの右上に出す印
        self.badge = ctk.CTkLabel(self.pill, text="", image=icons.dot(T.CYAN, 9), width=9, height=9)

        self.center = ctk.CTkFrame(self.pill, fg_color="transparent")
        emb = ctk.CTkLabel(self.center, text="", image=icons.emblem(26), width=26)
        emb.grid(row=0, column=0, rowspan=2, padx=(0, 5))
        self.pill_logo = ctk.CTkLabel(self.center, text="", height=12)
        self.pill_logo.grid(row=0, column=1, sticky="sw")
        row, self.pill_dot, self.pill_status = self._status_row(self.center)
        row.grid(row=1, column=1, sticky="nw", pady=(2, 0))

        # 正方形・円: 大きなロゴを真ん中に(正方形は下に状態とボタン)
        self.compact = ctk.CTkFrame(self.pill, fg_color="transparent")
        self.cmp_emb = ctk.CTkLabel(self.compact, text="", image=icons.emblem(40), width=40, height=40)
        self.cmp_emb.pack()
        self.cmp_row, self.cmp_dot, self.cmp_status = self._status_row(self.compact)
        self.sq_buttons = ctk.CTkFrame(self.pill, fg_color="transparent")
        self._round(self.sq_buttons, 30, icons.mic(14), self.open_voice_mode, fg=T.ACCENT,
                    hover=T.ACCENT_LIGHT, tip="音声で会話する").pack(side="left", padx=4)
        self._round(self.sq_buttons, 30, icons.chat(14, icons.INK), self._show_panel, fg=T.SURFACE,
                    hover=T.BORDER, tip="チャットを開く").pack(side="left", padx=4)

        self.pill_busy = ctk.CTkFrame(self.pill, fg_color="transparent")
        self.pill_spin = DotSpinner(self.pill_busy, dot=6, gap=5)
        self.pill_spin.pack(pady=(0, 3))
        self.pill_stop = self._stop(self.pill_busy, text=f"■ 停止  {HOTKEY}", width=PILL_W - 2 * PILL_H + 4,
                                    height=18, font=T.font(8, "bold"))
        self.pill_stop.configure(corner_radius=9)
        self.pill_stop.pack()
        for w in (self.pill, self.center, emb, self.pill_logo, row, self.pill_dot, self.pill_status,
                  self.pill_busy, self.pill_spin, self.compact, self.cmp_emb, self.cmp_row, self.cmp_dot,
                  self.cmp_status, self.sq_buttons):
            self._draggable(w, on_click=self._show_panel)  # 動かさずにクリックしたら、チャットを開く
            w.bind("<Button-3>", self._pill_menu, add="+")  # 右クリック: チャット・音声会話・設定
        self._layout_pill()

        # ---- 展開・折りたたみ中に見せる、中身のない下地 ----
        self.morph = self._card(PANEL_R)

        # ---- 会話パネル: 左にスレッド一覧、右にチャット ----
        self.panel = self._card(PANEL_R)
        self.panel.grid_columnconfigure(1, weight=1)
        self.panel.grid_rowconfigure(0, weight=1)
        self.side = self._build_sidebar(self.panel)
        self.main = ctk.CTkFrame(self.panel, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew")
        self._build_chat(self.main)
        self._side_mode = None
        self.panel.bind("<Configure>", self._on_panel_resize, add="+")

        # ---- 端をつかんで大きさを変える(パネル表示中だけ) ----
        cursors = {"n": "sb_v_double_arrow", "s": "sb_v_double_arrow", "e": "sb_h_double_arrow",
                   "w": "sb_h_double_arrow", "nw": "top_left_corner", "ne": "top_right_corner",
                   "sw": "bottom_left_corner", "se": "bottom_right_corner"}
        if os.name == "nt":  # Windows の斜めの矢印
            cursors.update(nw="size_nw_se", se="size_nw_se", ne="size_ne_sw", sw="size_ne_sw",
                           n="size_ns", s="size_ns", e="size_we", w="size_we")
        # 角は専用の部品を置かず(背景と色が合わず四角が見えるため)、辺のつまみの端の方をつかむと斜めに動く
        self._grips, self._cursors = {}, cursors
        for edge in ("n", "s", "w", "e"):
            g = tk.Frame(self, bg=T.BG, cursor=cursors[edge], highlightthickness=0, bd=0)
            g.bind("<Motion>", lambda e, ed=edge: e.widget.configure(cursor=self._cursors[self._grip_edge(e, ed)]))
            g.bind("<ButtonPress-1>", lambda e, ed=edge: self._resize_start(e, self._grip_edge(e, ed)))
            g.bind("<B1-Motion>", self._resize_move)
            g.bind("<ButtonRelease-1>", self._resize_end)
            self._grips[edge] = g

    def _build_sidebar(self, master):
        """左端に沿ったスレッド一覧(Claude のような構成)。右端に区切り線。"""
        side = ctk.CTkFrame(master, fg_color=T.SIDEBAR, corner_radius=0, width=SIDEBAR_W)
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(2, weight=1)
        ctk.CTkFrame(side, fg_color=T.BORDER, width=1, corner_radius=0).grid(row=0, column=1, rowspan=3,
                                                                              sticky="ns")
        top = ctk.CTkFrame(side, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=(10, 8), pady=(12, 4))
        top.grid_columnconfigure(1, weight=1)
        self._round(top, 30, icons.threads(17), self._toggle_drawer, hover=T.SURFACE, tip="チャットの一覧を閉じる").grid(row=0, column=0)
        ctk.CTkLabel(top, text="チャット", font=T.font(13, "bold"), text_color=T.TEXT).grid(
            row=0, column=1, sticky="w", padx=6)
        ctk.CTkButton(side, text="新しいチャット", image=icons.plus(12), compound="left", anchor="w", height=34,
                      corner_radius=10, font=T.font(11), fg_color="transparent", hover_color=T.SURFACE,
                      text_color=T.TEXT, command=self._new_thread).grid(row=1, column=0, sticky="ew",
                                                                        padx=8, pady=(4, 6))
        self.thread_list = ctk.CTkScrollableFrame(side, fg_color="transparent", scrollbar_button_color=T.BORDER)
        self.thread_list.grid(row=2, column=0, sticky="nsew", padx=(4, 2), pady=(0, 10))
        _autohide_scrollbar(self.thread_list)
        self.thread_list.grid_columnconfigure(0, weight=1)
        return side

    def _build_chat(self, p):
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(p, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=(10, 12), pady=(12, 4))
        head.grid_columnconfigure(2, weight=1)
        self.menu_btn = self._round(head, 30, icons.threads(17), self._toggle_drawer, tip="チャットの一覧")  # スレッド一覧の開閉
        self.menu_btn.grid(row=0, column=0, rowspan=2, padx=(0, 4))
        emb2 = ctk.CTkLabel(head, text="", image=icons.emblem(32), width=32)
        emb2.grid(row=0, column=1, rowspan=2, padx=(2, 8))
        self.panel_logo = ctk.CTkLabel(head, text="", height=14)
        self.panel_logo.grid(row=0, column=2, sticky="sw")
        row2, self.dot, self.status = self._status_row(head)
        row2.grid(row=1, column=2, sticky="nw", pady=(3, 0))
        self.head_spin = DotSpinner(row2, dot=5, gap=3)
        self.tech_badge = ctk.CTkLabel(row2, text=" TECH ", font=("Consolas", 9, "bold"), fg_color=T.TECH,
                                       text_color="#04130d", corner_radius=6, height=16)
        buttons = ctk.CTkFrame(head, fg_color="transparent")
        buttons.grid(row=0, column=3, rowspan=2)
        self.tech_btn = ctk.CTkButton(buttons, text="</>", width=30, height=30, corner_radius=15, font=("Consolas", 11, "bold"),
                                      fg_color="transparent", hover_color=T.SURFACE, text_color=T.SUB,
                                      command=lambda: self._set_tech(not self._tech_on(), announce=True))
        self.tech_btn.pack(side="left")
        import tooltip
        tooltip.tip(self.tech_btn, "テクニカルモード（コードの添削・作成、サーバー・IT の相談）")
        self._round(buttons, 30, icons.export(15), lambda: self._export_thread(self.thread), tip="このチャットを書き出す").pack(side="left")
        self._round(buttons, 30, icons.plus(15), self._new_thread, tip="新しいチャット").pack(side="left")
        self.max_btn = self._round(buttons, 30, icons.maximize(14), self._toggle_max, tip="全画面にする")
        self.max_btn.pack(side="left")
        self._round(buttons, 30, icons.gear(18), self.open_settings, tip="設定").pack(side="left")
        for w in (head, emb2, self.panel_logo, row2, self.dot, self.status):
            self._draggable(w)
        for w in (head, self.panel_logo, self.status):
            w.bind("<Double-Button-1>", lambda e: self._toggle_max(), add="+")

        self.chat = ctk.CTkScrollableFrame(p, fg_color="transparent", scrollbar_button_color=T.BORDER)
        self.chat.grid(row=1, column=0, sticky="nsew", padx=6)
        self.chat.grid_columnconfigure(0, weight=1)
        self.chat.bind("<Configure>", self._on_chat_resize, add="+")
        _autohide_scrollbar(self.chat)
        # 一覧を重ねて開いているとき、チャット側を押したら閉じる
        self.chat._parent_canvas.bind("<Button-1>", lambda e: self._close_drawer(), add="+")
        self._bubbles = []
        self._wrap = 220
        self.typing = ctk.CTkFrame(self.chat, fg_color=T.SURFACE, corner_radius=14)
        self.typing_spin = DotSpinner(self.typing, dot=7, gap=5)
        self.typing_spin.pack(padx=14, pady=10)
        self.code_spin = tech_spinner(self.typing)  # テクニカルモードのときは、こちらを出す
        # 資料(ファイル)を作っている間だけ出す札: 行が書き込まれていく書類・途中経過・光が走る帯
        import loaders
        self.office_card = ctk.CTkFrame(self.chat, fg_color=T.SURFACE, corner_radius=14)
        self.office_doc = FrameSpinner(self.office_card, loaders.document, 3.2, (44, 52))
        self.office_doc.grid(row=0, column=0, rowspan=3, padx=(14, 12), pady=12)
        ctk.CTkLabel(self.office_card, text="資料を作成中", font=T.font(12, "bold"), text_color=T.TEXT,
                     anchor="w").grid(row=0, column=1, sticky="sw", padx=(0, 16), pady=(14, 0))
        self.office_text = ctk.CTkLabel(self.office_card, text="", font=T.font(10), text_color=T.SUB, anchor="w")
        self.office_text.grid(row=1, column=1, sticky="w", padx=(0, 16))
        self.office_bar = FrameSpinner(self.office_card, loaders.bar, 1.4, (170, 6))
        self.office_bar.grid(row=2, column=1, sticky="nw", padx=(0, 16), pady=(6, 14))

        # 複数選択してコピーするときの帯
        self.select_bar = ctk.CTkFrame(p, fg_color=T.RAISED, corner_radius=18)
        self.select_text = ctk.CTkLabel(self.select_bar, text="", font=T.font(11, "bold"), text_color=T.TEXT)
        self.select_text.pack(side="left", padx=(14, 8), pady=6)
        ctk.CTkButton(self.select_bar, text="コピー", width=70, height=28, corner_radius=14, font=T.font(11, "bold"),
                      fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER, command=self._copy_selected).pack(side="left", pady=6)
        ctk.CTkButton(self.select_bar, text="やめる", width=64, height=28, corner_radius=14, font=T.font(11),
                      fg_color="transparent", border_width=1, border_color=T.BORDER, text_color=T.TEXT,
                      hover_color=T.BORDER, command=self._end_select).pack(side="left", padx=(6, 8), pady=6)
        self._selected = None  # 複数選択中なら、選んだ吹き出しの集まり

        # 1行のときの高さ(ボタン32 + 上下の余白4×2 = 40)のちょうど半分の丸みにして、両端をきれいな半円にする
        # 入力欄: 高さ 48(ボタン 30 + 上下 9)のちょうど半分の丸みで、両端を半円にする。
        # 縁(テクニカルモードで緑)はいつも描いておき(ふだんは背景と同じ色)、両端のボタンは縁の丸みの内側に収める
        box = ctk.CTkFrame(p, fg_color=T.SURFACE, corner_radius=24, border_width=2, border_color=T.SURFACE)
        box.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 6))
        box.grid_columnconfigure(1, weight=1)
        self._input_box = box
        # 添付したファイル・フォルダ(入力欄の上に、名前の札を並べる。×で外す)
        self.attach_bar = ctk.CTkFrame(box, fg_color="transparent")
        self.mic = self._mic(box, 30)
        self.mic.grid(row=1, column=0, padx=(9, 4), pady=9, sticky="s")
        self.entry = ctk.CTkTextbox(box, border_width=0, fg_color="transparent", font=T.font(12),
                                    text_color=T.TEXT, height=30, wrap="char", activate_scrollbars=False)
        self.entry.grid(row=1, column=1, sticky="ew", padx=2, pady=9)
        self.entry.bind("<Return>", self._on_return)
        import ime  # 日本語の変換中の文字を、この入力欄の中に表示させる
        self._ime = ime.attach(self.entry._textbox, T.FONT, round(12 * 96 / 72 * self._scaling()))
        self.entry.bind("<KeyRelease>", lambda e: self._fit_input())
        self.entry._textbox.bind("<<ImePreedit>>", lambda e: self._fit_input(), add="+")
        self.entry.bind("<FocusIn>", lambda e: self._fit_input())
        self.entry.bind("<FocusOut>", lambda e: self._fit_input())
        self.hint = ctk.CTkLabel(box, text="", font=T.font(12), text_color=T.SUB, height=20)
        self.entry.bind("<Control-v>", self._paste_files, add="+")  # エクスプローラーでコピーしたファイルを貼り付けて添付
        # 入力欄のどこをクリックしても(「〜にメッセージ…」の文字の上や余白でも)、文字を打てる状態にする
        def bind_all(w):
            if isinstance(w, RoundButton):
                return  # マイク・送信ボタンはそれぞれの動作
            w.bind("<ButtonPress-1>", self._focus_entry, add="+")
            for c in w.winfo_children():
                bind_all(c)
        bind_all(box)
        # ファイル・フォルダを添付するボタン
        clip = ctk.CTkButton(box, text="＋", width=30, height=30, corner_radius=15, font=T.font(15, "bold"),
                             fg_color="transparent", hover_color=T.RAISED, text_color=T.SUB,
                             command=lambda: self._attach_menu())
        clip.grid(row=1, column=2, padx=(3, 0), pady=9, sticky="s")
        import tooltip
        tooltip.tip(clip, "ファイル・フォルダを添付（ドラッグ＆ドロップ・貼り付けでも）")
        # 音声会話画面へ切り替えるボタン(声の波の印)
        self._round(box, 30, icons.waves(15, icons.INK), self.open_voice_mode, fg=T.BORDER, hover=T.RAISED,
                    tip="音声で会話する").grid(
            row=1, column=3, padx=(4, 0), pady=9, sticky="s")
        self._round(box, 30, icons.send(16), self._send_entry, fg=T.ACCENT, hover=T.ACCENT_HOVER, tip="送信（Enter）").grid(
            row=1, column=4, padx=(4, 9), pady=9, sticky="s")
        import dropfiles
        self.after(500, lambda: dropfiles.enable(self, self._add_attachments))
        self.tip = ctk.CTkLabel(p, text="", font=T.font(9), text_color=T.SUB, height=12)
        self.tip.grid(row=3, column=0, sticky="w", padx=22)

        foot = ctk.CTkFrame(p, fg_color="transparent", height=36)
        foot.grid(row=4, column=0, sticky="ew", padx=10, pady=(4, 10))
        foot.grid_columnconfigure(0, weight=1)
        self.panel_stop = self._stop(foot, text=f"■  緊急停止　{HOTKEY}", height=32, font=T.font(11, "bold"))
        self._round(foot, 32, icons.close(12), self._show_pill, fg=T.SURFACE,
                    hover=T.BORDER, tip="小さくして待機する").grid(row=0, column=1, padx=(8, 0))

    def _layout_pill(self):
        """設定の形に合わせて、待機表示の中身を並べ直す。"""
        style = getattr(config, "PILL_STYLE", "standard")
        w, h, r = pill_dims()
        self.pill.configure(corner_radius=r)
        for c in self.pill.winfo_children():
            c.grid_forget()
        for i in range(3):
            self.pill.grid_columnconfigure(i, weight=0)
            self.pill.grid_rowconfigure(i, weight=0)
        self.cmp_row.pack_forget()
        self.pill_stop.pack_forget()
        if style == "standard":
            self.pill.grid_columnconfigure(1, weight=1)
            self.pill.grid_rowconfigure(0, weight=1)
            self.pill_mic.grid(row=0, column=0, padx=(6, 0))
            self.pill_chat.grid(row=0, column=2, padx=(0, 6))
            self._pill_main = self.center
            self._pill_main.grid(row=0, column=1)
            self.pill_stop.configure(width=w - 2 * h + 4)
            self.pill_stop.pack()
            self._busy_place = lambda: self.pill_busy.grid(row=0, column=1)
        else:
            self.pill.grid_columnconfigure(0, weight=1)
            self.pill.grid_rowconfigure(0, weight=1)
            size = 40 if style == "square" else 38
            self.cmp_emb.configure(image=icons.emblem(size), width=size, height=size)
            self._pill_main = self.compact
            if style == "square":  # ロゴ、その下に状態、いちばん下にマイクとチャット
                self.cmp_row.pack(pady=(4, 0))
                self._pill_main.grid(row=0, column=0, pady=(12, 0))
                self.sq_buttons.grid(row=1, column=0, pady=(2, 10))
                self.pill_stop.configure(width=w - 20)
                self.pill_stop.pack()
            else:  # 円: ロゴだけ(押すとチャット、右クリックで音声会話など)
                self._pill_main.grid(row=0, column=0)
            self._busy_place = lambda: self.pill_busy.grid(row=0, column=0)
        if getattr(self, "_state", "idle") in BUSY:
            self._pill_main.grid_remove()
            self._busy_place()

    def _pill_menu(self, e):
        self._menu(e, [("チャットを開く", self._show_panel), ("音声で会話する", self.open_voice_mode), None,
                       ("設定", self.open_settings)])

    def _draggable(self, w, on_click=None):
        w.bind("<ButtonPress-1>", lambda e: (setattr(self, "_drag_click", on_click), self._drag_start(e)), add="+")
        w.bind("<B1-Motion>", self._drag_move, add="+")
        w.bind("<ButtonRelease-1>", self._drag_end, add="+")

    # ================= 位置と大きさ =================
    # 位置は画面の実ピクセル、大きさは CTk の論理ピクセル(×scaling で実ピクセル)で扱う
    def _scaling(self):
        try:
            return ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            return 1.0

    def _px(self, v):
        return round(v * self._scaling())

    def _logical(self, v):
        return round(v / self._scaling())

    def _work(self, x, y):
        """点(x, y)があるモニターの、タスクバーを除いた範囲 (左, 上, 右, 下)。"""
        return winutil.work_area(x, y, (0, 0, self.winfo_screenwidth(), self.winfo_screenheight()))

    def _clamp(self, x, y, w, h, area):
        l, t, r, b = area
        return max(l, min(x, r - w)), max(t, min(y, b - h))

    def _apply(self, x, y, w, h, radius, fast=False):
        """窓を (x, y) に 論理サイズ w×h で置き、外枠(Windows)も合わせる。"""
        self.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        if getattr(self, "_shell_hold", False):  # 展開・折りたたみ中は外枠だけを別に動かす
            return
        W, H = self._px(w), self._px(h)
        if not fast:  # 実際に変わった大きさで外枠と切り抜きを合わせる(ずれ防止)
            self.update_idletasks()
            if self.winfo_width() > 1 and self.winfo_height() > 1:  # まだ画面に出ていないときは指定の大きさで
                W, H = self.winfo_width(), self.winfo_height()
        self.shell.update(int(x), int(y), W, H, self._px(radius), fast)

    def _settle(self):
        """待機表示の位置・大きさ・外枠が崩れていたら整え直す。
        (アップデート直後の自動起動などで、画面に出る前の指定が効かず、四角いまま画面の中ほどに
        出ることがあるため、起動直後と、その後も定期的に確かめる)"""
        if self._expanded or self._animating or getattr(self, "_drag", None):
            return
        if not self.winfo_ismapped():
            return
        x, y, w, h, r = self._pill_rect()
        if (abs(self.winfo_x() - x) > 2 or abs(self.winfo_y() - y) > 2
                or abs(self.winfo_width() - self._px(w)) > 2 or abs(self.winfo_height() - self._px(h)) > 2):
            self.shell._last = None  # 外枠と切り抜きも必ず描き直す
            self._apply(x, y, w, h, r)

    def _fit_on_screen(self):
        """ウィジェットがモニターからはみ出していたら(モニターを外した時なども)内側へ戻す。"""
        self._settle()
        if self._animating or getattr(self, "_drag", None) or getattr(self, "_resizing", None):
            return
        x, y, w, h, r = self._current_rect()
        W, H = self._px(w), self._px(h)
        l, t, rr, b = self._work(x + W // 2, y + H // 2)
        nw, nh = min(W, rr - l), min(H, b - t)
        nx, ny = self._clamp(x, y, nw, nh, (l, t, rr, b))
        if (nx, ny, nw, nh) != (x, y, W, H):
            if not self._expanded:
                self._pos = (nx, ny)
                config.save({"WINDOW_POS": list(self._pos)})
            self._apply(nx, ny, self._logical(nw), self._logical(nh), r)

    def _pill_rect(self):
        if getattr(self, "_pos", None) is None:
            pos = config.WINDOW_POS
            if pos:
                self._pos = tuple(pos)
            else:  # 初回はメインモニターの右下(タスクバーの上)
                l, t, r, b = self._work(1, 1)
                pw0, ph0, _ = pill_dims()
                self._pos = (r - self._px(pw0 + 12), b - self._px(ph0 + 12))
        pw, ph, pr = pill_dims()
        w, h = self._px(pw), self._px(ph)
        cx, cy = self._pos[0] + w // 2, self._pos[1] + h // 2
        self._pos = self._clamp(*self._pos, w, h, self._work(cx, cy))  # 外されたモニターに取り残さない
        return (*self._pos, pw, ph, pr)

    def _panel_size(self):
        w, h = config.PANEL_SIZE
        return max(PANEL_MIN_W, w), max(PANEL_MIN_H, h)

    def _panel_rect(self):
        """常駐位置がモニターのどちら側にあるかで、パネルの伸びる向きを決める。"""
        x, y, _, _, _ = self._pill_rect()
        pw, ph = self._px(pill_dims()[0]), self._px(pill_dims()[1])
        area = self._work(x + pw // 2, y + ph // 2)
        l, t, r, b = area
        w, h = self._panel_size()
        w, h = min(w, self._logical(r - l)), min(h, self._logical(b - t))
        W, H = self._px(w), self._px(h)
        off = config.PANEL_OFFSET  # 大きさを変えたときの、待機表示から見たパネルの位置
        if off and l <= x + off[0] and x + off[0] + W <= r and t <= y + off[1] and y + off[1] + H <= b:
            return x + off[0], y + off[1], w, h, PANEL_R
        px = x + pw - W if x + pw / 2 > (l + r) / 2 else x   # 右寄りなら右端を揃えて左へ
        py = y + ph - H if y + ph / 2 > (t + b) / 2 else y   # 下寄りなら下端を揃えて上へ
        return (*self._clamp(px, py, W, H, area), w, h, PANEL_R)

    def _current_rect(self):
        r = PANEL_R if self._expanded else pill_dims()[2]
        return (self.winfo_x(), self.winfo_y(), self._logical(self.winfo_width()),
                self._logical(self.winfo_height()), r)

    # ================= 展開・折りたたみ(なめらかに大きさを変える) =================
    def _morph(self, start, end, done):
        """start から end へ、少しずつ大きさを変える(最初は速く、最後はゆっくり止まる)。
        Windows: 本体は一旦見えなくして最後の大きさに整えておき、なめらかな外枠だけを動かす
        (本体の窓を動かしながら描き直すと、角に黒い四角が出るため)。
        それ以外: 中身のない下地の大きさを変え、最後に中身を出す。"""
        self._animating = True
        self._hide_grips()
        shell = self.shell.ok
        if shell:
            self.attributes("-alpha", 0.0)
            self._shell_hold = True
            done()  # 見えない間に中身を最後の形にしておく
        else:
            for w in (self.pill, self.panel):
                w.pack_forget()
            self.morph.pack(fill="both", expand=True)

        def step(i):
            t = i / ANIM_FRAMES
            e = 1 - (1 - t) ** 3
            rect = [a + (b - a) * e for a, b in zip(start, end)]
            last = i >= ANIM_FRAMES
            if shell:
                x, y, w, h, r = rect
                self.shell.frame(int(x), int(y), self._px(w), self._px(h), self._px(r), fast=not last)
            else:
                self.morph.configure(corner_radius=int(min(rect[4], rect[3] / 2)))
                self._apply(*rect, fast=not last)
            if not last:
                self.after(ANIM_MS, step, i + 1)
                return
            self._animating = False
            if shell:
                self._shell_hold = False
                self._apply(*end)
                self.update_idletasks()
                self.attributes("-alpha", 1.0)
                if self._expanded:
                    self._show_grips()
            else:
                self.morph.pack_forget()
                done()
        step(1)

    def _show_pill(self, animate=True):
        self._end_follow()
        self._close_drawer()
        if self._maximized:  # 全画面のまま折りたたむときは、外枠を戻して元の大きさから縮める
            self._maximized = False
            self.shell.resume()
            self._apply(*self._restore_rect)
        end = self._pill_rect()

        def done():
            self._expanded = self._maximized = False
            self._mic_policy()
            self.max_btn.configure(image=icons.maximize(14))
            self.max_btn._tip.set("全画面にする")
            self.panel.pack_forget()
            self._hide_grips()
            self.pill.pack(fill="both", expand=True)
            self._apply(*end)
        if animate and self._expanded and not self._animating:
            self._morph(self._current_rect(), end, done)
        else:
            done()

    def _show_panel(self, animate=True):
        if self._expanded or self._animating:
            return
        self.badge.place_forget()  # 更新のお知らせはパネル内のカードで確認できる
        end = self._panel_rect()

        def done():
            self._expanded = True
            self._mic_policy()
            import llm
            llm.warm()  # 休んでメモリから外していたAIを、文字を打っている間に読み込み直す
            self.pill.pack_forget()
            self.panel.pack(fill="both", expand=True)
            self._apply(*end)
            self._show_grips()
            self._focus_entry()
        if animate:
            self._morph(self._current_rect(), end, done)
        else:
            done()

    def bring_to_front(self):
        """2つ目の起動から呼ばれる(別スレッド)。ウィジェットを表に出して会話パネルを開く。"""
        def front():
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self._show_panel()
        self._events.put(front)

    def _focus_entry(self, _=None):
        zlog.note("入力欄にフォーカス")
        winutil.activate(self)
        self.focus_force()
        self.entry._textbox.focus_force()
        # 窓が前面に出た直後に Windows がフォーカスを戻すことがあるので、少し後にもう一度
        for ms in (30, 120):
            self.after(ms, lambda: self.entry._textbox.focus_force())
        if _ is not None and _.widget is not self.entry._textbox:  # 文字の外を押したときは、文末から打てるように
            self.entry._textbox.mark_set("insert", "end")

    def _toggle_max(self):
        """会話パネルの全画面(いまのモニターのタスクバーを除いた範囲)と元の大きさを切り替える。"""
        if not self._expanded or self._animating:
            return
        if self._maximized:
            self._maximized = False
            self._apply(*self._restore_rect)
            self._show_grips()
        else:
            self._restore_rect = self._current_rect()
            x, y, w, h, _ = self._restore_rect
            l, t, r, b = self._work(x + self._px(w) // 2, y + self._px(h) // 2)
            self._maximized = True
            self._hide_grips()
            self.shell.suspend()  # 全画面では外枠・影を付けず、画面いっぱいの四角で表示
            self._apply(l, t, self._logical(r - l), self._logical(b - t), 0)
        self.max_btn.configure(image=icons.maximize(14, restore=self._maximized))
        self.max_btn._tip.set("元の大きさに戻す" if self._maximized else "全画面にする")
        # 新しい大きさでの並べ直しと描き直しをその場で済ませる(黒い窓や古い表示を残さない)
        self.update()
        if not self._maximized:
            self.shell.resume()
            self._apply(*self._restore_rect)
        self.after(15, self._repaint)

    def _repaint(self):
        """全画面との切り替え後、中身を確実に描き直す。透明度を一瞬だけ変えると、
        Windows が窓の表示を作り直す(これをしないと黒いまま残ることがある)。"""
        self.lift()  # 外枠の窓より必ず手前に
        winutil.repaint(self)
        self.attributes("-alpha", 0.99)
        self.update_idletasks()
        self.attributes("-alpha", 1.0)
        winutil.repaint(self)

    # ---- 移動(ドラッグ) ----
    def _drag_start(self, e):
        if self._maximized or self._animating:
            self._drag = None
            return
        self._drag = (e.x_root, e.y_root, self.winfo_x(), self.winfo_y(), self._pos)

    def _drag_move(self, e):
        if not getattr(self, "_drag", None):
            return
        sx, sy, wx, wy, (px, py) = self._drag
        w, h = self.winfo_width(), self.winfo_height()
        # 移動中は、すべてのモニターを合わせた範囲で動かせる(デュアルスクリーン対応)
        x, y = self._clamp(wx + e.x_root - sx, wy + e.y_root - sy, w, h,
                           winutil.virtual_bounds((0, 0, self.winfo_screenwidth(), self.winfo_screenheight())))
        self.geometry(f"+{x}+{y}")
        self.shell.move(x, y)
        # パネル表示中に動かした場合も、閉じたときの待機位置を同じだけ動かす
        self._pos = (px + x - wx, py + y - wy)

    def _drag_end(self, e):
        if not getattr(self, "_drag", None):
            return
        sx, sy = self._drag[:2]
        self._drag = None
        click = getattr(self, "_drag_click", None)
        if click and abs(e.x_root - sx) < 5 and abs(e.y_root - sy) < 5:  # ほとんど動かしていない: クリック
            self.after(1, click)
            return
        # 離した場所のモニターからはみ出していれば、内側に収める
        x, y, w, h, r = self._current_rect()
        area = self._work(x + self._px(w) // 2, y + self._px(h) // 2)
        nx, ny = self._clamp(x, y, self._px(w), self._px(h), area)
        self._pos = (self._pos[0] + nx - x, self._pos[1] + ny - y)
        if (nx, ny) != (x, y):
            self._apply(nx, ny, w, h, r)
        config.save({"WINDOW_POS": list(self._pos)})

    # ---- 大きさの変更(端をドラッグ) ----
    def _grip_edge(self, e, edge):
        """辺のつまみのどこをつかんだか: 端から 28 の範囲なら斜め(角)。"""
        k, w = self._px(28), e.widget
        if edge in ("n", "s"):
            return edge + "w" if e.x < k else edge + "e" if e.x > w.winfo_width() - k else edge
        return "n" + edge if e.y < k else "s" + edge if e.y > w.winfo_height() - k else edge

    def _show_grips(self):
        g = GRIP
        place = {"n": dict(x=0, y=0, relwidth=1, height=g), "s": dict(x=0, rely=1, y=-g, relwidth=1, height=g),
                 "w": dict(x=0, y=0, relheight=1, width=g), "e": dict(relx=1, x=-g, y=0, relheight=1, width=g)}
        px = lambda d: {key: (self._px(v) if key in ("x", "y", "width", "height") else v) for key, v in d.items()}
        for edge, grip in self._grips.items():
            grip.place(**px(place[edge]))
            grip.lift()

    def _hide_grips(self):
        for grip in self._grips.values():
            grip.place_forget()

    def _resize_start(self, e, edge):
        x, y, w, h = self.winfo_x(), self.winfo_y(), self.winfo_width(), self.winfo_height()
        self._resizing = (edge, e.x_root, e.y_root, x, y, x + w, y + h, self._work(x + w // 2, y + h // 2))

    def _resize_move(self, e):
        """つかんだ辺だけを動かし、反対側の辺は動かさない。モニターの外には出さない。"""
        if not getattr(self, "_resizing", None):
            return
        edge, sx, sy, left, top, right, bottom, (l, t, r, b) = self._resizing
        dx, dy = e.x_root - sx, e.y_root - sy
        mw, mh = self._px(PANEL_MIN_W), self._px(PANEL_MIN_H)
        if "e" in edge:
            right = min(r, max(left + mw, right + dx))
        if "w" in edge:
            left = max(l, min(right - mw, left + dx))
        if "s" in edge:
            bottom = min(b, max(top + mh, bottom + dy))
        if "n" in edge:
            top = max(t, min(bottom - mh, top + dy))
        self._resize_rect = (left, top, self._logical(right - left), self._logical(bottom - top), PANEL_R)
        # マウスの動きのたびに大きさを変えると描き直しが追いつかず古い表示が残るので、
        # 手が空いたときに最新の大きさだけを反映し、その場で描き直す(ブラウザのように追従)
        if not getattr(self, "_resize_queued", False):
            self._resize_queued = True
            self.after_idle(self._resize_flush)

    def _resize_flush(self):
        self._resize_queued = False
        if not self._resize_rect:
            return
        x, y, w, h, r = self._resize_rect
        # Windows では位置と大きさを一度に変える(Tk 経由だと、ドラッグ中に反対側の辺まで動いて見える)
        if winutil.set_rect(self, x, y, self._px(w), self._px(h)):
            self.shell.update(int(x), int(y), self._px(w), self._px(h), self._px(r), True)
        else:
            self._apply(x, y, w, h, r, fast=True)
        self.update_idletasks()

    def _resize_end(self, _):
        if not getattr(self, "_resizing", None):
            return
        self._resizing = None
        x, y, w, h, r = getattr(self, "_resize_rect", None) or self._current_rect()
        self._resize_rect = None
        self._apply(x, y, w, h, r)  # 最後にきれいに描き直す
        # 次に開くときも同じ場所・大きさになるよう、待機表示から見た位置と大きさを覚える
        config.save({"PANEL_SIZE": [w, h], "PANEL_OFFSET": [x - self._pos[0], y - self._pos[1]]})

    # ---- スレッド一覧: 広いときはチャットの左に並べ、狭いときは左端から重ねて出す ----
    def _on_panel_resize(self, e):
        mode = "wide" if self._logical(e.width) >= WIDE else "narrow"
        if mode == self._side_mode:
            return
        self._side_mode = mode
        self._close_drawer()
        self._layout_side()

    def _layout_side(self):
        if self._side_mode == "wide" and config.SIDEBAR_OPEN:
            self.side.grid(row=0, column=0, sticky="nsew")
            self.menu_btn.grid_remove()  # 一覧の上にある同じボタンで閉じられる
        else:
            self.side.grid_forget()
            self.menu_btn.grid()

    def _toggle_drawer(self):
        if self._side_mode == "wide":  # 広いとき: 一覧の表示・非表示を切り替え(次回も覚えておく)
            config.save({"SIDEBAR_OPEN": not config.SIDEBAR_OPEN})
            self._layout_side()
        elif self.side.winfo_manager() == "place":
            self._close_drawer()
        else:
            # 左端から全体の高さで、すっと出す(CTk の部品は place で大きさを渡せないので高さは先に設定)
            self.side.configure(height=self._logical(self.panel.winfo_height()))
            self.side.place(in_=self.panel, x=-self._px(SIDEBAR_W), y=0)
            self.side.lift()
            self._slide(0)

    def _slide(self, i, frames=5):
        x = -self._px(SIDEBAR_W) * (1 - (1 - (i + 1) / frames) ** 3)
        if self.side.winfo_manager() != "place":
            return
        self.side.place_configure(x=int(x) if i + 1 < frames else 0)
        if i + 1 < frames:
            self.after(10, self._slide, i + 1, frames)

    def _close_drawer(self):
        if self.side.winfo_manager() == "place":
            self.side.place_forget()

    def _on_chat_resize(self, e):
        """チャット欄の幅に合わせて、吹き出しの折り返し幅を変える。"""
        wrap = max(180, int(self._logical(e.width) * 0.74))
        if abs(wrap - self._wrap) < 8:
            return
        self._wrap = wrap
        for w in self._bubbles:
            if getattr(w, "_bubble", False):
                w.configure(wraplength=wrap)
            for lab in getattr(w, "_labels", []):
                lab.configure(wraplength=wrap)

    # ================= スレッド =================
    def _refresh_threads(self):
        for w in self.thread_list.winfo_children():
            w.destroy()
        items = threads.listing()
        if not items:
            ctk.CTkLabel(self.thread_list, text="まだ会話はありません", font=T.font(10), text_color=T.SUB).grid(
                row=0, column=0, pady=12)
        for i, t in enumerate(items):
            active = t["id"] == self.thread["id"]
            base = T.SURFACE if active else T.SIDEBAR
            row = ctk.CTkFrame(self.thread_list, fg_color=base, corner_radius=10, cursor="hand2", height=48)
            row.grid(row=i, column=0, sticky="ew", padx=2, pady=1)
            row.grid_columnconfigure(0, weight=1)
            name = t["title"] if len(t["title"]) <= 13 else t["title"][:12] + "…"
            title = ctk.CTkLabel(row, text=name, font=T.font(11, "bold" if active else "normal"),
                                 text_color=T.TEXT if active else T.MUTED_TEXT, anchor="w", height=18)
            title.grid(row=0, column=0, sticky="ew", padx=(10, 4), pady=(7, 0))
            when = ctk.CTkLabel(row, text=threads.when(t["updated"]), font=T.font(9), text_color=T.SUB, anchor="w",
                                height=12)
            when.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 7))
            trash = self._round(row, 24, icons.trash(12), lambda tid=t["id"]: self._delete_thread(tid),
                                fg=base, hover=T.BORDER)
            for w in (row, title, when):
                w.bind("<Button-1>", lambda e, tid=t["id"]: self._open_thread(tid))
                w.bind("<Button-3>", lambda e, tid=t["id"]: self._thread_menu(e, tid))  # 右クリック: コピー・書き出し
            # マウスを乗せた行だけ明るくし、削除ボタンを出す
            row.bind("<Enter>", lambda e, r=row, b=trash: (r.configure(fg_color=T.SURFACE),
                                                          b.grid(row=0, column=1, rowspan=2, padx=(0, 6))))
            row.bind("<Leave>", lambda e, r=row, b=trash, c=base: self._row_leave(e, r, b, c))

    def _row_leave(self, e, row, trash, color):
        # 行の中の部品へ移っただけなら閉じない
        x, y = row.winfo_pointerxy()
        inside = row.winfo_rootx() <= x < row.winfo_rootx() + row.winfo_width() and \
            row.winfo_rooty() <= y < row.winfo_rooty() + row.winfo_height()
        if not inside:
            row.configure(fg_color=color)
            trash.grid_remove()

    def _new_thread(self):
        self._close_drawer()
        if self.thread["messages"]:
            self.thread = threads.new()
            self._clear_chat()
            self._refresh_threads()
        self._paint_tech()
        self._paint_attachments()
        self.entry.focus_set()

    def _open_thread(self, tid):
        self._close_drawer()
        t = threads.load(tid)
        if not t:
            return
        self.thread = t
        self._clear_chat()
        self._paint_tech()
        self._paint_attachments()
        for m in t["messages"]:
            if m["role"] in ("user", "ai"):
                self._log(m["text"], m["role"])
            if m.get("images"):
                self._log_images(m["images"], auto_open=False)
            if m.get("sources"):
                self._log_sources(m["sources"])
            if m.get("files"):
                self._log_files(m["files"])
        self._refresh_threads()

    def _delete_thread(self, tid):
        threads.delete(tid)
        if tid == self.thread["id"]:
            self.thread = threads.new()
            self._clear_chat()
        self._refresh_threads()

    def _clear_chat(self):
        self._stream = None
        if self._selected is not None:
            self._end_select()
        for w in self._bubbles:
            w.destroy()
        self._bubbles.clear()
        self.typing.grid_remove()

    # ================= 会話表示: kind = user / ai / sys =================
    # ================= 添付(ファイル・フォルダ) =================
    def _attach_menu(self):
        x, y = self.winfo_pointerx(), self.winfo_pointery()

        class E:  # メニューを出す位置
            x_root, y_root = x, y
        self._menu(E, [("ファイルを添付…", self._pick_files), ("フォルダを添付…", self._pick_folder)])

    def _pick_files(self):
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(parent=self, title="添付するファイルを選ぶ")
        if paths:
            self._add_attachments(list(paths))

    def _pick_folder(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(parent=self, title="添付するフォルダを選ぶ")
        if path:
            self._add_attachments([path])

    def _paste_files(self, e=None):
        import dropfiles
        files = dropfiles.clipboard_files()
        if not files:
            return None  # ふつうの文字の貼り付け
        self._add_attachments(files)
        return "break"

    def _add_attachments(self, paths):
        """添付を足す(このチャットに覚えておき、外すまで質問のたびに使う)。"""
        import os as _os
        have = self.thread.setdefault("attachments", [])
        for p in paths:
            p = _os.path.abspath(p)
            if _os.path.exists(p) and p not in have:
                have.append(p)
        del have[12:]  # 多すぎると読み取りに時間がかかるので、12個まで
        if self.thread["messages"]:
            threads.save(self.thread)
        self._paint_attachments()
        if not self._expanded and self._voice_win is None:
            self._show_panel()
        self._toast(f"{len(paths)}件を添付しました。添付について質問できます")
        self._focus_entry()

    def _remove_attachment(self, path):
        have = self.thread.get("attachments", [])
        if path in have:
            have.remove(path)
            if self.thread["messages"]:
                threads.save(self.thread)
        self._paint_attachments()

    def _paint_attachments(self):
        import attachments
        for w in self.attach_bar.winfo_children():
            w.destroy()
        items = self.thread.get("attachments", [])
        if not items:
            self.attach_bar.grid_forget()
            return
        for p in items:
            chip = ctk.CTkButton(self.attach_bar, text=f"{attachments.label(p)}  ✕", height=24, corner_radius=12,
                                 font=T.font(10), fg_color=T.BG, hover_color=T.BORDER, text_color=T.TEXT,
                                 command=lambda p=p: self._remove_attachment(p))
            chip.pack(side="left", padx=(0, 4), pady=(2, 0))
            import tooltip
            tooltip.tip(chip, f"{p}\n押すと添付を外します")
        self.attach_bar.grid(row=0, column=0, columnspan=5, sticky="w", padx=18, pady=(8, 0))

    # ================= テクニカルモード =================
    def _tech_on(self):
        return self.thread.get("mode") == "tech"

    def _set_tech(self, on, announce=False):
        """このチャットをテクニカルモードにする / 戻す(チャットごとに覚える)。"""
        if on:
            self.thread["mode"] = "tech"
        else:
            if self.thread.pop("mode", None):
                import llm
                llm.release_tech_model()  # テクニカルモード用の大きなAIを、すぐメモリから外す
        if self.thread["messages"]:
            threads.save(self.thread)
        self._paint_tech()
        if announce:
            self._toast("テクニカルモードにしました" if on else "通常モードに戻しました")

    def _paint_tech(self):
        """テクニカルモードの見た目: ボタン・見出しの「TECH」の札・入力欄の緑の縁。"""
        if getattr(self, "tech_btn", None) is not None:
            on = self._tech_on()
            self.tech_btn.configure(fg_color=T.TECH if on else "transparent", text_color="white" if on else T.SUB,
                                    hover_color=T.TECH_HOVER if on else T.SURFACE)
            if on:
                self.tech_badge.pack(side="left", padx=(6, 0))
            else:
                self.tech_badge.pack_forget()
            self._input_box.configure(border_color=T.TECH if on else T.SURFACE)

    def _log_code(self, text):
        """コード(``` で囲んだ部分)のある返事: 文はふつうに、コードは等幅の枠に入れ、コピーのボタンを付ける。"""
        row = len(self._bubbles)
        box = ctk.CTkFrame(self.chat, fg_color=T.SURFACE, corner_radius=14)
        box.grid(row=row, column=0, sticky="w", padx=4, pady=3)
        box._labels = []
        parts = re.split(r"```([^\n`]*)\n?(.*?)(?:```|$)", text, flags=re.S)
        for i in range(0, len(parts), 3):
            prose = parts[i].strip()
            if prose:
                lab = ctk.CTkLabel(box, text=prose, font=T.font(12), wraplength=self._wrap, justify="left",
                                   text_color=T.TEXT, anchor="w")
                lab.pack(anchor="w", padx=10, pady=(6, 2))
                lab.bind("<Button-3>", lambda e, b=box: self._bubble_menu(e, b))
                box._labels.append(lab)
            if i + 2 < len(parts):
                lang, code = parts[i + 1].strip() or "code", parts[i + 2].rstrip()
                frame = ctk.CTkFrame(box, fg_color=T.BG, corner_radius=8)
                frame.pack(fill="x", padx=8, pady=4)
                bar = ctk.CTkFrame(frame, fg_color="transparent")
                bar.pack(fill="x", padx=6, pady=(4, 0))
                ctk.CTkLabel(bar, text=lang, font=T.font(9), text_color=T.SUB).pack(side="left")
                ctk.CTkButton(bar, text="コピー", width=52, height=20, corner_radius=10, font=T.font(9),
                              fg_color="transparent", border_width=1, border_color=T.BORDER, hover_color=T.SURFACE,
                              text_color=T.TEXT, command=lambda c=code: self._copy(c)).pack(side="right")
                lines = code.count("\n") + 1
                tb = ctk.CTkTextbox(frame, font=("Consolas", 11), wrap="none", fg_color=T.BG, text_color=T.TEXT,
                                    height=min(22, lines) * 17 + 12, activate_scrollbars=lines > 22)
                tb.insert("1.0", code)
                tb.configure(state="disabled")
                tb.pack(fill="x", padx=4, pady=(0, 4))
        box._bubble_text = text
        box._role = "ai"
        box.bind("<Button-3>", lambda e, b=box: self._bubble_menu(e, b))
        self._add_widget(box, None)
        return box

    def _log(self, text, kind="sys"):
        if kind == "ai" and "```" in text:
            return self._log_code(text)
        row = len(self._bubbles)
        if kind == "sys":
            w = ctk.CTkLabel(self.chat, text=text, font=T.font(10), text_color=T.SUB, wraplength=self._wrap)
            w.grid(row=row, column=0, pady=2)
        else:
            user = kind == "user"
            w = ctk.CTkLabel(self.chat, text=text, font=T.font(12), wraplength=self._wrap, justify="left",
                             fg_color=T.ACCENT if user else T.SURFACE, text_color="white" if user else T.TEXT,
                             corner_radius=14, padx=10, pady=6)
            w.grid(row=row, column=0, sticky="e" if user else "w", padx=4, pady=3)
            w.bind("<Button-3>", lambda e, b=w: self._bubble_menu(e, b))  # 右クリック: コピー・書き出し
            w._role, w._base_color = kind, (T.ACCENT if user else T.SURFACE)
            if self._selected is not None:
                self._bind_select(w)
        w._bubble = True
        self._add_widget(w, None)
        return w

    def _remove_widget(self, w):
        """チャット欄から部品を取り除き、行を詰め直す。"""
        if w in self._bubbles:
            self._bubbles.remove(w)
        w.destroy()
        for i, b in enumerate(self._bubbles):
            b.grid_configure(row=i)

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
        if self.office_card.winfo_manager():
            self.office_card.grid_configure(row=len(self._bubbles))  # 資料づくり中の表示も最後尾
        self.after(20, lambda: self.chat._parent_canvas.yview_moveto(1.0))

    # ---- 返事を書けた分から表示・読み上げ ----
    def _showing_pending(self):
        return self._pending_tid == self.thread["id"]

    def _speakable(self, piece):
        """読み上げる部分(``` で囲んだコードは読まない)。"""
        if self._stream is None:  # 新しい返事の書き始め
            import tts
            self._code_filter = tts.CodeFilter()
        return self._code_filter.feed(piece)

    def _on_delta(self, piece):
        self.speaker.feed(self._speakable(piece))  # 一文になったところから話し始める(コードは読まない)
        if self._voice_win is not None:
            self._voice_win.reply_piece(piece)
        if not self._showing_pending():
            return
        if self._stream is None:
            self.typing.grid_remove()  # 文字が届き始めたら「入力中」のドットは消す
            self._stream = [self._log("", "ai"), ""]
        self._stream[1] += piece
        self._stream[0].configure(text=self._stream[1])
        self.after(20, lambda: self.chat._parent_canvas.yview_moveto(1.0))

    def _on_reply(self, text):
        import llm
        text, confirm = llm.take_confirm(text)
        if confirm:
            self.after(1, lambda: self._ask_confirm(confirm))
        text, files = llm.take_files(text)
        self._office_done()
        body, sources, images = split_reply(text)
        if self._voice_win is not None:
            self._voice_win.reply_done(body)
            if images:
                self._voice_win.show_images(images)
            if files:
                self._voice_win.show_files(files, on_done=self._toast)
        config.VOICE_CONTEXT = (getattr(config, "VOICE_CONTEXT", "") + " " + body)[-200:]
        streamed = self._stream is not None
        if streamed:
            self.speaker.flush()  # 句点で終わっていない最後の部分も読む
        else:
            # 出典(URL)や画像、コードは読み上げない
            self.speaker.say(re.sub(r"```.*?(?:```|$)", "（コードは画面に表示しました）", body, flags=re.S))
        # 返事は、質問したスレッドに保存する(途中で別のスレッドを開いていても)
        target = self.thread if self._showing_pending() else threads.load(self._pending_tid)
        if target is not None:
            threads.add(target, "ai", body, sources, images, files)
        if self._showing_pending():
            if streamed and "```" in body:  # コードのある返事は、最後に見やすい形に作り直す
                self._remove_widget(self._stream[0])
                self._log(body, "ai")
            elif streamed:
                self._stream[0].configure(text=body)
            else:
                self._log(body, "ai")
            if images:  # 音声会話画面では、画像は会話画面に並べる(一覧は押したときだけ開く)
                self._log_images(images, auto_open=self._voice_win is None)
            if sources:
                self._log_sources(sources)
            if files:
                self._log_files(files)
        self._stream = None
        self._refresh_threads()
        if self._voice_session:  # 声で会話しているときは、読み上げが終わったらまた聞き取る
            self.after(300, self._start_follow)
        self.after(2500, self._summarize_later)  # 手が空いたら、古いやりとりを要約しておく

    def _log_files(self, files):
        """作ったファイルの札(開く・保存・場所を開く)を、チャットに並べる。"""
        import filecard
        box = ctk.CTkFrame(self.chat, fg_color="transparent")
        for p in files:
            filecard.card(box, p, wrap=max(260, self._wrap), on_done=self._toast).pack(anchor="w", pady=2, fill="x")
        self._add_widget(box, "w")

    def _office_start(self):
        """資料づくりの間だけ出す札(ほかのローディング表示の代わり)。"""
        if not self._showing_pending():
            return
        self.typing.grid_remove()
        self.office_text.configure(text="準備しています…")
        self.office_card.grid(row=len(self._bubbles), column=0, sticky="w", padx=4, pady=3)
        self.after(20, lambda: self.chat._parent_canvas.yview_moveto(1.0))

    def _office_done(self):
        if self.office_card.winfo_ismapped():
            self.office_card.grid_remove()
        if self._voice_win is not None:
            self._voice_win.office_done()

    # ---- 複数選択してコピー ----
    def _start_select(self, first=None):
        self._selected = []
        self.select_bar.place(in_=self.chat._parent_frame, relx=0.5, rely=1.0, y=-10, anchor="s")
        self.select_bar.lift()
        for w in self._bubbles:
            if getattr(w, "_role", None):
                self._bind_select(w)
        if first is not None:
            self._toggle_select(first)
        self._paint_select()

    def _bind_select(self, w):
        targets = [w] + list(getattr(w, "_labels", []))
        for t in targets:
            t.bind("<Button-1>", lambda e, b=w: self._toggle_select(b) if self._selected is not None else None, add="+")

    def _toggle_select(self, w):
        if self._selected is None:
            return
        if w in self._selected:
            self._selected.remove(w)
            w.configure(border_width=0) if isinstance(w, ctk.CTkFrame) else w.configure(fg_color=w._base_color)
        else:
            self._selected.append(w)
            if isinstance(w, ctk.CTkFrame):
                w.configure(border_width=2, border_color=T.CYAN)
            else:
                w.configure(fg_color=T.CYAN if w._role == "user" else T.RAISED)
        self._paint_select()

    def _paint_select(self):
        n = len(self._selected or [])
        self.select_text.configure(text=f"{n}件を選択中（吹き出しを押して選ぶ）" if n else "コピーする吹き出しを押して選んでください")

    def _copy_selected(self):
        """選んだ発言だけを、会話の順に「名前: 発言」でまとめてコピーする。"""
        chosen = [w for w in self._bubbles if w in (self._selected or [])]
        if not chosen:
            self._toast("吹き出しを選んでください")
            return
        name = config.AI_NAME
        lines = [f"{'あなた' if w._role == 'user' else name}: {getattr(w, '_bubble_text', None) or w.cget('text')}"
                 for w in chosen]
        self._copy("\n\n".join(lines))
        self._end_select()

    def _end_select(self):
        for w in self._selected or []:
            w.configure(border_width=0) if isinstance(w, ctk.CTkFrame) else w.configure(fg_color=w._base_color)
        self._selected = None
        self.select_bar.place_forget()

    def _log_sources(self, sources):
        """検索の出典を、クリックでブラウザが開くリンクとして並べる。"""
        box = ctk.CTkFrame(self.chat, fg_color="transparent")
        lines = sources.strip().split("\n")
        for title, url in zip(lines[0::2], lines[1::2]):
            link = ctk.CTkLabel(box, text=f"↗ {title}", font=T.font(10, "underline"), text_color=T.CYAN,
                                anchor="w", justify="left", wraplength=self._wrap, cursor="hand2")
            link.pack(anchor="w", padx=8, pady=1)
            link.bind("<Button-1>", lambda e, u=url: tools.open_in_browser(u))
        self._add_widget(box, "w")

    def _log_images(self, images, auto_open=True):
        """画像のサムネイルを横に並べ、クリックで一覧ウィンドウを開く。画像検索なら一覧も自動で開く。"""
        import gallery
        items = images["items"]
        open_all = lambda: gallery.show(self, images["query"], items)  # noqa: E731
        box = ctk.CTkFrame(self.chat, fg_color="transparent")
        for i, item in enumerate(items[:4]):
            # 角丸を付けると幅が広がってはみ出すため、角丸なしの正方形で並べる
            pic = ctk.CTkLabel(box, text="", width=52, height=52, fg_color=T.SURFACE, corner_radius=0,
                               cursor="hand2")
            pic.grid(row=0, column=i, padx=2)
            pic.bind("<Button-1>", lambda e: open_all())
            gallery.load_async(pic, [item["thumb"]], (52, 52), lambda im, _, p=pic: p.configure(image=im))
        ctk.CTkButton(box, text=f"画像一覧（{len(items)}枚）", height=26, corner_radius=13, font=T.font(10),
                      fg_color="transparent", border_width=1, border_color=T.ACCENT, hover_color=T.SURFACE,
                      command=open_all).grid(row=1, column=0, columnspan=4, sticky="w", padx=2, pady=(4, 0))
        self._add_widget(box, "w")
        if auto_open and images.get("open"):
            open_all()

    def _post_log(self, text):  # 任意のスレッドから呼べる
        self._events.put(lambda: self._log(text, "sys"))

    def _set_state(self, state):
        self._state = state
        label, color, _ = STATES[state]
        for t in (self.status, self.pill_status, self.cmp_status):
            t.configure(text=label)
        for d in (self.dot, self.pill_dot, self.cmp_dot):
            d.configure(image=icons.dot(color))
        if state in BUSY:  # 操作中だけ緊急停止ボタンとローディング表示を出す
            self._pill_main.grid_remove()
            self._busy_place()
            self.panel_stop.grid(row=0, column=0, sticky="ew")
            self.dot.pack_forget()
            self.head_spin.pack(side="left", padx=(0, 5), before=self.status)
            if self._showing_pending() and not self.office_card.winfo_ismapped():
                tech = self._tech_on()  # テクニカルモードは、ローディングの見た目も変える
                (self.typing_spin if tech else self.code_spin).pack_forget()
                (self.code_spin if tech else self.typing_spin).pack(padx=14, pady=10 if not tech else 6)
                self.typing.grid(row=len(self._bubbles), column=0, sticky="w", padx=4, pady=3)
                self.after(20, lambda: self.chat._parent_canvas.yview_moveto(1.0))
        else:
            self.pill_busy.grid_remove()
            self.panel_stop.grid_remove()
            self._pill_main.grid()
            self.head_spin.pack_forget()
            self.dot.pack(side="left", padx=(0, 5), before=self.status)
            self.typing.grid_remove()
            self._office_done()

    def _spin(self):
        """ローディングのドットを 60 コマ/秒 で動かす(処理中だけ)。"""
        if self._state not in BUSY:
            self._spinning = False
            return
        for sp in (self.pill_spin, self.head_spin, self.typing_spin, self.code_spin, self.office_doc, self.office_bar):
            if sp.winfo_ismapped():
                sp.tick()
        self.after(16, self._spin)

    def _animate(self):
        if self._state in BUSY and not getattr(self, "_spinning", False):
            self._spinning = True
            self._spin()
        _, color, blink = STATES[self._state]
        self._blink = (self._blink + 1) % 16
        if blink and self._blink in (0, 8):  # 色が切り替わるときだけ描き直す
            c = T.BORDER if self._blink >= 8 else color
            for d in (self.dot, self.pill_dot, self.cmp_dot):
                d.configure(image=icons.dot(c))

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
            self._end_follow(idle=False)  # 文字で入力したら、声の会話は終える
            self.entry.delete("1.0", "end")
            self._fit_input()
            self._submit(text)

    def _fit_input(self):
        """入力行数に合わせて高さを変え、空欄ならヒントを表示する。"""
        tb = self.entry._textbox
        lines = tb.count("1.0", "end-1c", "displaylines")
        n = max(1, min(INPUT_MAX_LINES, (lines[0] if lines else 0) + 1))
        # 変わったときだけ描き直す(毎回 configure すると、縁ごと描き直されて入力欄がガタつく)
        if n != getattr(self, "_input_lines", None):
            self._input_lines = n
            self.entry.configure(height=12 + n * 18)
        empty = not self.entry.get("1.0", "end").strip()
        show = empty and self.focus_get() is not tb
        if show != getattr(self, "_hint_shown", None):
            self._hint_shown = show
            if show:
                self.hint.grid(row=1, column=1, sticky="w", padx=8)
            else:
                self.hint.grid_remove()

    def _submit(self, text, by_voice=False):
        if self._pending_confirm is not None and self._answer_confirm(text):
            return  # 「はい」「いいえ」: 確認待ちの操作への答え
        self.summarizer.cancel()  # 要約の途中なら、すぐやめて返事を優先する
        import memory
        change = memory.parse(text)
        if change:  # 「〜を覚えておいて」「〜を忘れて」
            self._change_memory(text, change)
            return
        import persona
        change = persona.parse(text)
        if change:  # 「関西弁で話して」「話し方を元に戻して」など: AIの性格・話し方を変える
            self._change_persona(text, change)
            return
        full = FULL_ON.search(text) and True or (False if FULL_OFF.search(text) else None)
        if full is not None:  # 「会話を全部参照して答えて」「全部参照するのをやめて」
            config.save({"FULL_CONTEXT": full})
            reply = ("わかりました。このチャットの最初からの会話をすべて参照して答えます。"
                     "長くなったら古い部分は要約して覚えておきます。" if full else
                     f"わかりました。直前の{config.CONTEXT_TURNS}往復と要約を参照して答える、ふつうのモードに戻します。")
            self._log(text, "user")
            self._log(reply, "ai")
            threads.add(self.thread, "user", text)
            threads.add(self.thread, "ai", reply)
            self.speaker.say(reply)
            self._refresh_threads()
            return
        tech = True if TECH_ON.search(text) else False if TECH_OFF.search(text) else None
        if tech is not None and len(text) <= 40:  # 「テクニカルモードにして」「通常モードに戻して」
            self._log(text, "user")
            threads.add(self.thread, "user", text)
            self._set_tech(tech)
            reply = ("テクニカルモードにしました。コードの添削・作成、サーバーやネットワークの設定などを、くわしくお手伝いします。"
                     if tech else "通常モードに戻しました。")
            self._log(reply, "ai")
            threads.add(self.thread, "ai", reply)
            self.speaker.say(reply)
            self._refresh_threads()
            return
        import llm
        if not self._tech_on() and getattr(config, "TECH_AUTO", True) and llm.looks_technical(text):
            self._set_tech(True)  # 技術的な話: テクニカルモードに切り替えてから答える
            self._log("技術的な内容なので、テクニカルモードに切り替えました（「通常モードに戻して」で戻ります）", "sys")
        if STANDBY.fullmatch(re.sub(r"[\s。、！!？?…]", "", text)):  # 「待機して」など: 小さくして待機する
            self._standby()
            return
        config.VOICE_CONTEXT = text  # 次の聞き取りの手がかりにする(直前の話題)
        zlog.note(f"送信: {len(text)}文字{'(声)' if by_voice else ''}")  # 記録には中身を残さない
        self._log(text, "user")
        if re.search(r"声を(?:変え|かえ|選|えら)", text):  # 「声を変えたい」は声選びの画面を開く
            self._log("声を選ぶ画面を開きます。試聴して選んでください。", "ai")
            self.open_voice_picker()
            return
        if getattr(config, "FULL_CONTEXT", False) or self._tech_on():
            # 会話をすべて参照する(長すぎる分は圧縮)。テクニカルモードは、コードの話が続くので いつもこちら
            history, summary, base = threads.full_history(self.thread)
            extra = {"summary": summary, "memory": list(config.MEMORY), "full": True,
                     "tid": self.thread["id"], "base": base, "mode": "tech" if self._tech_on() else ""}
        else:
            history = threads.history(self.thread, config.CONTEXT_TURNS)  # このスレッドの直前のやりとり
            extra = {"summary": self.thread.get("summary", ""), "memory": list(config.MEMORY)}
        extra["attachments"] = list(self.thread.get("attachments", []))  # 添付したファイル・フォルダ(外すまで使う)
        threads.add(self.thread, "user", text)
        self._pending_tid = self.thread["id"]
        self.worker.submit(text, history, by_voice=by_voice, extra=extra)
        self._set_state("think")
        self._refresh_threads()

    def _on_voice(self, text, from_button):
        """聞き取った文を処理する。
        - マイクボタン・話すキー: そのまま命令にする(合図の言葉は不要)
        - 待機中の常時聞き取り: 「ウェイク、<AI名>」で始まるときだけ。チャット画面を開き、
          そのまま続けて話しかけられる状態にする(以後は合図の言葉なしで会話を続けられる)"""
        zlog.note(f"聞き取り {'ボタン' if from_button else '待機中'}: {len(text)}文字")  # 中身は残さない
        cmd = strip_wake_word(text)
        if self._voice_win is not None and not from_button:  # 音声会話画面: 話したことはそのまま命令
            cmd = cmd or text
            self._voice_win.heard(cmd)
            self._submit(cmd, by_voice=True)
            return
        if from_button:
            self._end_follow(idle=False)
            self._submit(cmd or text, by_voice=True)
            return
        if self.speaker.busy and cmd is None:
            return  # 読み上げ中は、自分の声を拾っただけなので無視
        if cmd is not None:  # 合図の言葉を聞き取った
            self.speaker.stop()
            self._wake_up()
            if not cmd:
                self._start_follow()
                return
        elif not self._following():
            return  # 合図の言葉がない周りの会話は無視(チャット欄にも出さない)
        else:
            cmd = text
        self._follow_until = 0
        self._submit(cmd, by_voice=True)

    # ================= 音声会話画面 =================
    def open_voice_mode(self):
        """待機表示のマイクから開く。話しかけるたびに聞き取り、返事を読み上げ、また聞き取る。"""
        if self._voice_win is not None and self._voice_win.winfo_exists():
            self._voice_win.lift()
            return
        import voice_mode
        if self._expanded:  # チャットから切り替えたとき: チャットは閉じて、待機表示の近くに会話画面を出す
            self._show_pill(animate=False)
        self._end_follow(idle=False)
        self.speaker.stop()
        x, y, w, h, _ = self._current_rect()
        l, t, r, b = self._work(x + self._px(w) // 2, y + self._px(h) // 2)
        vx = max(l, min(x + self._px(w) - self._px(360), r - self._px(360)))
        vy = max(t, min(y - self._px(650), b - self._px(640)))
        self.voice.conversation = True
        self.voice._ensure_stream()
        self._voice_win = voice_mode.VoiceMode(self, vx, vy)
        zlog.note("音声会話画面を開く")

    def voice_mode_closed(self):
        self._voice_win = None
        self.voice.conversation = False
        self.speaker.stop()
        if self._state == "listen":
            self._set_state("idle")
        zlog.note("音声会話画面を閉じる")

    def open_chat(self):
        self.deiconify()
        self.lift()
        self._show_panel()

    # ================= 危険な操作の確認 =================
    YES = re.compile(r"^(?:はい|うん|ええ|お願い|おねがい|実行|いいよ|いいです|オッケー|ok|どうぞ|やって|大丈夫|そう)", re.I)
    NO = re.compile(r"^(?:いいえ|いや|やめ|だめ|ダメ|キャンセル|中止|ストップ|しないで|やらないで|ノー|no|待って)", re.I)

    def _ask_confirm(self, confirm):
        """声で頼まれた危険な操作を、実行する前に確かめる(画面のボタンでも、声で「はい/いいえ」でも答えられる)。"""
        self._pending_confirm = confirm
        card = ctk.CTkFrame(self.chat, fg_color=T.SURFACE, corner_radius=14, border_width=1, border_color=T.WARN)
        ctk.CTkLabel(card, text=f"{confirm['what']}しますか？", font=T.font(11, "bold"), text_color=T.TEXT,
                     wraplength=240, justify="left").pack(anchor="w", padx=12, pady=(8, 4))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(row, text="実行する", height=28, corner_radius=14, fg_color=T.DANGER,
                      hover_color=T.DANGER_HOVER, font=T.font(11, "bold"),
                      command=lambda: self._answer_confirm("はい")).pack(side="left", padx=(0, 6))
        ctk.CTkButton(row, text="やめる", height=28, corner_radius=14, fg_color="transparent", border_width=1,
                      border_color=T.BORDER, text_color=T.TEXT, hover_color=T.BORDER, font=T.font(11),
                      command=lambda: self._answer_confirm("いいえ")).pack(side="left")
        self._confirm_card = card
        self._add_widget(card, "w")

    def _answer_confirm(self, text):
        """確認への答えなら処理して True。違う話なら確認を取り下げて False(ふつうの依頼として扱う)。"""
        t = text.strip()
        confirm, self._pending_confirm = self._pending_confirm, None
        card = getattr(self, "_confirm_card", None)
        if card is not None and card.winfo_exists():
            self._remove_widget(card)
        if self.YES.match(t):
            self._log(t, "user")
            self.worker.run_confirmed(confirm["tool"], confirm["args"])
            self._set_state("think")
            return True
        if self.NO.match(t):
            self._log(t, "user")
            self._log("わかりました、やめておきますね。", "ai")
            self.speaker.say("わかりました、やめておきますね。")
            return True
        return False

    def _history_cleared(self):
        """会話の履歴を消したあと: 画面の会話も消し、新しいチャットにする。"""
        for b in list(self._bubbles):
            self._remove_widget(b)
        self._new_thread()
        config.VOICE_CONTEXT = ""

    # ================= 記憶 =================
    def _change_memory(self, text, change):
        import memory
        kind, value = change
        if kind == "remember" and value.startswith(("この", "その", "それ", "さっき", "今の", "いまの")):
            # 「これを覚えておいて」: 直前の返事の中身もあわせて覚える
            last = next((m["text"] for m in reversed(self.thread["messages"]) if m["role"] == "ai"), "")
            change = (kind, f"{value}: {last[:120]}" if last else value)
        new = memory.apply(config.MEMORY, change)
        reply = {"remember": f"はい、「{change[1][:40]}」を覚えました。",
                 "forget": (f"わかりました、「{value}」に関することは忘れました。" if len(new) < len(config.MEMORY)
                            else f"「{value}」に関することは、覚えていませんでした。"),
                 "forget_all": "わかりました、覚えていたことをすべて忘れました。"}[kind]
        config.save({"MEMORY": new})
        self._log(text, "user")
        self._log(reply, "ai")
        threads.add(self.thread, "user", text)
        threads.add(self.thread, "ai", reply)
        self.speaker.say(reply)
        self._refresh_threads()
        zlog.note(f"記憶を変更: {kind}(覚えていること {len(new)}件)")

    def _summarize_later(self):
        if self._state == "think" or self.worker.pending or getattr(config, "FULL_CONTEXT", False):
            return  # 全部を参照するモードでは、上限を超えたときだけ圧縮する
        tid = self.thread["id"]
        self.summarizer.start(self.thread, max(2, config.CONTEXT_TURNS),
                              lambda text, upto: self._events.put(lambda: self._save_summary(tid, text, upto)))

    def _save_summary(self, tid, text, upto, full=False):
        t = self.thread if self.thread["id"] == tid else threads.load(tid)
        if t is None:
            return
        t["summary"], t["summary_upto"], t["summary_full"] = text, upto, full
        threads.save(t)
        zlog.note(f"会話を要約({upto}往復分)")

    # ================= コピー・書き出し =================
    def _menu(self, e, items):
        """右クリックのメニュー。items: [(名前, 動作) または None(区切り)]"""
        m = tk.Menu(self, tearoff=0, bg=T.SURFACE, fg=T.TEXT, activebackground=T.ACCENT, activeforeground="white",
                    bd=0, relief="flat", font=(T.FONT, max(9, round(10 * T.SCALE))))
        for it in items:
            if it is None:
                m.add_separator()
            else:
                m.add_command(label=it[0], command=it[1])
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _bubble_menu(self, e, widget):
        self._menu(e, [("この発言をコピー", lambda: self._copy(getattr(widget, "_bubble_text", None) or widget.cget("text"))),
                       ("複数選択してコピー…", lambda: self._start_select(widget)),
                       ("チャット全体をコピー", lambda: self._copy(threads.export_text(self.thread, config.AI_NAME))),
                       None,
                       ("このチャットを書き出す…", lambda: self._export_thread(self.thread))])

    def _thread_menu(self, e, tid):
        t = threads.load(tid)
        if not t:
            return
        self._menu(e, [("開く", lambda: self._open_thread(tid)),
                       ("まとめてコピー", lambda: self._copy(threads.export_text(t, config.AI_NAME))),
                       ("書き出す…", lambda: self._export_thread(t)),
                       None,
                       ("削除", lambda: self._delete_thread(tid))])

    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._toast("コピーしました")

    def _export_thread(self, t):
        """スレッドを Markdown(.md)またはテキスト(.txt)で保存する。"""
        if not t.get("messages"):
            self._toast("まだ会話がありません")
            return
        from tkinter import filedialog
        docs = os.path.join(os.path.expanduser("~"), "Documents")
        path = filedialog.asksaveasfilename(
            parent=self, title="チャットを書き出す", initialdir=docs if os.path.isdir(docs) else None,
            initialfile=f"{threads.safe_name(t['title'])}.md", defaultextension=".md",
            filetypes=[("Markdown（見出しつき）", "*.md"), ("テキスト", "*.txt")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(threads.export_text(t, config.AI_NAME))
        self._toast("書き出しました")

    def _toast(self, text):
        """会話画面の下に、短いお知らせを少しだけ出す。"""
        if not getattr(self, "_toast_label", None):
            self._toast_label = ctk.CTkLabel(self.panel, text="", font=T.font(11, "bold"), text_color="white",
                                             fg_color=T.OK, corner_radius=14, height=30)
        self._toast_label.configure(text=f"✓  {text}")
        self._toast_label.place(relx=0.5, rely=1.0, y=-110, anchor="s")
        self._toast_label.lift()
        if getattr(self, "_toast_job", None):
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(1500, self._toast_label.place_forget)

    def _change_persona(self, text, change):
        import persona
        new = persona.apply(config.PERSONA, change)
        config.save({"PERSONA": new})
        zlog.note(f"話し方を変更: {new!r}")
        self._log(text, "user")
        self._log(f"話し方を変更しました: {new or '標準'}（設定の「AI」タブでも変えられます）")
        self.worker.restart()  # 考える側に新しい話し方を読ませる
        # 新しい話し方で、ひとこと返事をしてもらう
        history = threads.history(self.thread, config.CONTEXT_TURNS)
        threads.add(self.thread, "user", text)
        self._pending_tid = self.thread["id"]
        self.worker.submit("（話し方を変えたので）今の話し方で、了解の返事をひとことだけしてください。", history)
        self._set_state("think")

    def _standby(self):
        """待機を命じられた: 音声会話画面やチャットを閉じ、小さな待機表示に戻る。"""
        zlog.note("待機")
        if self._voice_win is not None:
            self._voice_win.close()  # (閉じると読み上げも止まるので、先に閉じてから話す)
        self.speaker.say("はい、待機しますね。")
        self._end_follow()
        if self._expanded:
            self._show_pill()
        self._set_state("idle")

    def _heard_wake(self):
        """合図の言葉のAI(openWakeWord)が合図の言葉を見つけた: チャットを開き、続けて話す命令を聞き取る。"""
        if self.speaker.busy:
            return  # 読み上げ中は、自分の声を拾っただけ
        self._wake_up()
        self._start_follow()

    def _wake_up(self):
        """合図の言葉で呼ばれたとき: ウィジェットを表に出してチャット画面を開く。"""
        self._voice_session = True
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self._show_panel()

    def _mic_policy(self):
        """チャット画面を開いている間は、合図の言葉の聞き取りを休む(マイクを閉じ、聞き取りAIも動かさない)。
        声で話しかけた続き(続けて話しかけられる間)は聞き取る。マイクボタンはいつでも使える。"""
        voice = getattr(self, "voice", None)
        if voice is not None:
            voice.rest(self._expanded and not getattr(self, "_voice_session", False))

    def _following(self):
        return self._voice_session and time.monotonic() < self._follow_until

    def _start_follow(self):
        """続けて話しかけられる状態にする(マイクボタンを押さなくても聞き取る)。"""
        if not self._voice_session or not config.WAKE_ENABLED:
            return
        if self.speaker.busy:  # 読み上げが終わってから聞き始める
            self.after(300, self._start_follow)
            return
        if self._state == "think":
            return
        self._follow_until = time.monotonic() + FOLLOW_SEC
        self._mic_policy()
        self._paint_mic(True)
        self._set_state("listen")
        self.after(int(FOLLOW_SEC * 1000) + 100, self._follow_timeout)

    def _follow_timeout(self):
        if self._voice_session and self._follow_until and time.monotonic() >= self._follow_until:
            self._end_follow()

    def _end_follow(self, idle=True):
        was = self._voice_session
        self._voice_session, self._follow_until = False, 0
        self._mic_policy()
        if was and not self._recording:
            self._paint_mic(False)
            if idle and self._state == "listen":
                self._set_state("idle")

    def _mic_press(self, _):
        if config.INPUT_MODE == MODE_HOLD or not self._recording:
            self._start_rec()
        else:
            self._stop_rec()

    def _mic_release(self, _):
        if config.INPUT_MODE == MODE_HOLD and self._recording:
            self._stop_rec()

    def _paint_mic(self, active):
        """マイクの見た目(印は変えず、色だけ): 止まっている=紫(乗せると明るい紫)、聞き取り中=赤(乗せると明るい赤)。
        どの状態でも、乗せたときの色がほかの状態の色と重ならないようにする。"""
        for b, size in ((self.mic, 32), (self.pill_mic, PILL_H - 12)):
            b.configure(fg_color=T.LIVE if active else T.ACCENT, hover_color=T.LIVE_HOVER if active else T.ACCENT_LIGHT)

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
                                        on_check_update=lambda report: self.check_update(True, report),
                                        on_update=self.start_update, on_clear_history=self._history_cleared,
                                        on_pick_voice=self.open_voice_picker)

    def open_voice_picker(self, on_changed=None):
        import voice_picker
        if getattr(self, "_picker", None) and self._picker.winfo_exists():
            self._picker.focus()
            return
        self._picker = voice_picker.VoicePicker(self, play_wav=self.speaker.play_wav, say=self.speaker.say,
                                                on_changed=on_changed)

    def _settings_saved(self):
        self.worker.restart()  # 推論プロセスに新しい設定を読ませる
        self.voice.reset_device()  # マイクの選び直しを反映
        self._apply_settings()
        self._log("設定を保存しました")
        self._set_state("idle")
        self._switch_tts()
        if config.TTS_ENGINE == "voicevox" and runtime.voicevox_exe() and voicevox.needs_change(config.VOICEVOX_SPEAKER):
            self._background("声", self._prepare_voice)
        running, has_model, _ = services.check_ollama()
        if running and not has_model:
            self._background(f"AIモデル {config.OLLAMA_MODEL}", lambda p: services.pull_model(lambda t: p(None, t)))

    def _switch_tts(self):
        """読み上げのソフトを変えたとき: 使わなくなったソフトを止めてメモリを空け、選んだものを準備する。"""
        engine = config.TTS_ENGINE
        if engine == getattr(self, "_tts_engine", engine) and engine != "aivis":
            self._tts_engine = engine
            return
        self._tts_engine = engine
        self.speaker.stop()
        if engine != "voicevox":
            runtime.stop_voicevox()
        if engine != "kokoro":
            import kokoro_tts
            kokoro_tts.release()
        if engine == "voicevox":
            threading.Thread(target=runtime.start_services, daemon=True).start()
        elif engine == "aivis" and not runtime.aivis_running():
            self._background("読み上げ(AivisSpeech)", runtime.start_aivis)
        elif engine == "kokoro":
            import kokoro_tts
            self._background("読み上げ(Kokoro)", lambda p: kokoro_tts.prepare(lambda t: p(None, t)))

    def _prepare_voice(self, progress):
        """選んだ声のモデルだけを取得し(使わない声は削除)、VOICEVOX を読み込み直す。"""
        voicevox.install_voice(config.VOICEVOX_SPEAKER, progress)
        runtime.restart_voicevox()

    def _background(self, label, job):
        """時間のかかる準備を裏で行い、進み具合をチャット欄に表示する。job(progress(割合, 説明))。"""
        note = self._log(f"{label}: 準備中…")

        def progress(ratio, text):
            self._events.put(lambda: note.winfo_exists() and note.configure(text=f"{label}: {text}"))

        def run():
            try:
                job(progress)
                progress(1, "準備できました")
            except Exception as e:
                err = f"失敗しました（{e}）"
                progress(0, err)
        threading.Thread(target=run, daemon=True).start()

    def _apply_ptt(self):
        """話すキー: どの画面を開いていても、押している間だけ聞き取る(トグル方式なら押すたびに開始/終了)。"""
        import stopper
        try:
            stopper.register_ptt(config.PTT_KEY if config.PTT_ENABLED else None,
                                 lambda: self._events.put(lambda: self._mic_press(None)),
                                 lambda: self._events.put(lambda: self._mic_release(None)))
        except Exception as e:
            self._log(f"話すキーの登録エラー: {e}")
        key = stopper.KEY_NAMES.get(config.PTT_KEY, config.PTT_KEY)
        self.tip.configure(text=(f"{key} を押しながら話す ・ " if config.PTT_ENABLED else "")
                           + "Enter で送信 ・ Shift+Enter で改行")

    def _apply_settings(self):
        self.pill_logo.configure(image=icons.wordmark(config.AI_NAME, 9))
        self.panel_logo.configure(image=icons.wordmark(config.AI_NAME, 13))
        self.hint.configure(text=f"{config.AI_NAME} にメッセージ…")
        self._fit_input()
        if self._recording:
            self._stop_rec()
        self.voice.set_wake(config.WAKE_ENABLED)
        self._apply_ptt()
        style = getattr(config, "PILL_STYLE", "standard")
        if style != getattr(self, "_pill_style", style):  # 待機表示の形が変わった: 右下の角をそろえて並べ直す
            old_w, old_h, _ = PILL_STYLES.get(self._pill_style, PILL_STYLES["standard"])
            new_w, new_h, _ = pill_dims()
            if getattr(self, "_pos", None):
                self._pos = (self._pos[0] + self._px(old_w - new_w), self._pos[1] + self._px(old_h - new_h))
                config.save({"WINDOW_POS": list(self._pos)})
            self._layout_pill()
            if not self._expanded:
                self._apply(*self._pill_rect())
        self._pill_style = style

    # ================= アップデート =================
    def check_update(self, manual=False, report=None):
        """裏で最新版を確認する。自動確認は1日ごとに繰り返す。
        report(文字列, 新しい版の情報 or None) は設定画面への結果表示(裏のスレッドから呼ぶ)。"""
        def run():
            try:
                info = updater.check()
            except Exception as e:
                info, msg = None, f"確認できませんでした: {e}"
            else:
                msg = (f"新しいバージョン v{info['version']} があります（会話パネルから更新できます）" if info
                       else f"既に最新バージョンです（v{updater.VERSION}）")
            self._events.put(lambda: self._update_found(info, manual))
            if report:
                report(msg, info)
        threading.Thread(target=run, daemon=True).start()
        if not manual:
            self.after(24 * 3600 * 1000, self.check_update)

    def _update_found(self, info, manual):
        if not info or (self._update_info and self._update_info["version"] == info["version"] and not manual):
            return
        self._update_info = info
        if not self._expanded:
            self.badge.place(relx=1.0, x=-12, y=6, anchor="ne")
        # 更新のお知らせはチャット欄に1つだけ(何度確認しても増やさない。新しい版なら差し替える)
        old_card = getattr(self, "_upd_card", None)
        if old_card is not None and old_card.winfo_exists():
            if getattr(old_card, "_version", None) == info["version"]:
                return
            self._remove_widget(old_card)
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
        card._version = info["version"]
        self._upd_card = card
        self._add_widget(card, "w")

    def install_update(self):
        """会話パネルの「今すぐアップデート」から。"""
        if not self._update_info:
            return
        self._upd_btn.configure(state="disabled", text="ダウンロード中…")
        self.start_update(self._update_info, lambda text, failed=False: (
            self._upd_note.configure(text=text),
            failed and self._upd_btn.configure(state="normal", text="もう一度")))

    def start_update(self, info, on_progress):
        """新しい版をダウンロードして入れ替える(終わると自動で起動し直す)。設定画面からも呼ぶ。
        on_progress(説明, failed=False) は画面の処理として呼ばれる。"""
        def progress(ratio, text):
            self._events.put(lambda: on_progress(text))

        def run():
            try:
                updater.install(info, progress)
            except Exception as e:
                err = f"失敗しました: {e}"
                self._events.put(lambda: on_progress(err, True))
                return
            self._events.put(lambda: on_progress("インストールしています。終わると自動で起動し直します"))
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
        self._end_follow()
        self._stream = None
        self._recording = False
        self._paint_mic(False)
        self._log("⚠ 緊急停止しました")
        self._set_state("stop")

    # ================= ループ =================
    def _pump(self):
        busy = False
        while True:
            try:
                self._events.get_nowait()()
                busy = True
            except queue.Empty:
                break
        for kind, text in self.worker.poll():
            busy = True
            if kind == "delta":
                self._on_delta(text)
            elif kind == "reply":
                self._on_reply(text)
            elif kind == "status":  # 時間のかかる作業の途中経過(「調べています…」など)
                if self._voice_win is not None:
                    self._voice_win.status(text)
                if text == "@office":  # 資料づくりの始まり: 作成中の札を出す
                    self._office_start()
                elif self._state == "think":
                    for t in (self.status, self.pill_status, self.cmp_status):
                        t.configure(text=text)
                    if self.office_card.winfo_ismapped():
                        self.office_text.configure(text=text)
            elif kind == "retract":  # 返事の途中で操作を始めた: 書いた分(「開きます」など)を消し、話すのもやめる
                self.speaker.stop()
                if self._stream is not None:
                    self._remove_widget(self._stream[0])
                    self._stream = None
                if self._voice_win is not None:
                    self._voice_win.reply_done("")
            elif kind == "summary":  # 長くなった会話の古い部分を圧縮した(全部を参照するモード)
                tid, summary, upto = text
                self._save_summary(tid, summary, upto, full=True)
                self._toast("会話が長くなったので、古い部分を要約して覚えました")
            else:  # うまく答えられなかった: 自然な言い方で伝え、読み上げる(技術的な中身は記録へ)
                import llm
                zlog.error(f"返事のエラー: {text}")
                if self._stream is not None:
                    self.speaker.flush()
                self._stream = None
                self._on_reply(llm.friendly(text))
        if self._state == "think" and not self.worker.pending:
            self._set_state("idle")
        moving = time.monotonic() < getattr(self, "_quiet_until", 0)
        if not moving:  # 設定画面などを動かしている間は、見た目の更新を休む(動きを軽くする)
            self._animate()
        self._ticks = getattr(self, "_ticks", 0) + 1
        if self._ticks % 20 == 0 and not moving:  # ときどき、モニターからはみ出していないか確かめる
            self._fit_on_screen()
        # 何も起きていないときは間をあけて、PCの負担を減らす(返事の途中・処理中・声の聞き取り中はすぐ反応する)
        self._idle_ticks = 0 if busy or self._state != "idle" or self.worker.pending else \
            getattr(self, "_idle_ticks", 0) + 1
        self.after(50 if self._idle_ticks < 10 else 150, self._pump)

    def quiet(self, sec=0.4):
        """しばらく見た目の更新を休む(ほかの窓を動かしている間に呼ぶ)。"""
        self._quiet_until = time.monotonic() + sec

    def report_callback_exception(self, exc, val, tb):
        """画面の処理で起きたエラーは記録して続ける(1つのエラーで全体が止まらないように)。"""
        import traceback
        _log_error("".join(traceback.format_exception(exc, val, tb)))

    def restart_app(self):
        """Zealous を起動し直す(新しい Zealous は、この Zealous が終わるのを待ってから出る)。"""
        import subprocess
        import sys
        args = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, os.path.abspath("zealous.pyw")]
        subprocess.Popen(args + ["--restart"], cwd=os.getcwd())
        self.quit_app()

    def quit_app(self):
        zlog.note("終了")
        try:
            self.worker.close()  # 裏方のプロセスも確実に止める(残るとアップデートで上書きできない)
        except Exception:
            pass
        runtime.stop_services()
        self.destroy()


def _log_error(text):
    import zlog
    zlog.error(text)


if __name__ == "__main__":
    mp.freeze_support()
    App().mainloop()
