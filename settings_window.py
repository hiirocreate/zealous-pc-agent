"""各種設定の管理画面(左のタブで切り替え)。保存すると settings.json に書き込み、即時反映する。
専門用語には必ず（）で分かりやすい言い換えを付ける。"""
import os
import threading

import customtkinter as ctk

import config
import icons
import services
import shortcut
import theme as T
import voicevox
from version import VERSION

# 項目: (キー, 表示名, 種類, 補足説明[, 選択肢])
#   種類: str / int / float / bool / list / choice / voice
#   choice の選択肢は (保存する値, 表示名) の組
TABS = [
    ("一般", [
        ("—", "名前と呼びかけ"),
        ("AI_NAME", "AI名", "str", "画面の表示と、呼びかけに使う名前"),
        ("AI_NAME_ALIASES", "AI名の別表記", "list", "聞き間違えやすい呼び方をカンマ（,）区切りで"),
        ("WAKE_WORDS", "ウェイク語（呼びかけの合図の言葉）", "list", "例: 「ウェイク、Zealous、〜して」の「ウェイク」"),
        ("WAKE_ENABLED", "ウェイクワード（合図の言葉）で起動", "bool",
         "ONにすると、マイクを押さなくても常に聞き取り、合図の言葉で始まる命令だけ実行"
         "（マイクボタンで話すときは合図の言葉は不要）"),
        ("—", "マイク"),
        ("INPUT_MODE", "マイクの入力方式", "choice", "マイクボタンと話すキーの使い方",
         [("トランシーバー", "トランシーバー（押している間だけ録音）"),
          ("トグル", "トグル（1回押して開始・もう1回で終了）")]),
        ("PTT_ENABLED", "話すキー（押している間だけ聞き取るキー）を使う", "bool",
         "どの画面を開いていても、キーを押しながら話すだけで聞き取ります"),
        ("PTT_KEY", "話すキー", "choice", "普段の操作で使わないキーがおすすめ",
         [("right ctrl", "右Ctrl"), ("right alt", "右Alt"), ("right shift", "右Shift"), ("f8", "F8"),
          ("f9", "F9"), ("f10", "F10"), ("scroll lock", "Scroll Lock"), ("pause", "Pause")]),
        ("—", "起動"),
        ("AUTOSTART", "PC起動時に自動で起動", "bool", "Windows にサインインしたら Zealous を立ち上げる"),
    ]),
    ("権限", [
        ("—", "AIに任せる操作"),
        ("FOLDER_OPS_ENABLED", "ファイル・フォルダ操作を許可", "bool", "作成・名前変更・移動・コピー・一覧"),
        ("FOLDER_DELETE_ENABLED", "削除を許可", "bool", "削除はごみ箱へ移動するだけで、完全には消しません"),
        ("DRY_RUN", "お試しモード", "bool", "実際には操作せず、何をするつもりかだけ表示"),
        ("—", "ブラウザ"),
        ("BROWSER", "使うブラウザ", "choice", "Webページを開くときのブラウザ",
         [("chrome", "Chrome"), ("edge", "Edge"), ("firefox", "Firefox"), ("default", "既定のブラウザ")]),
        ("SEARCH_URL", "検索URL（検索サイトのアドレス）", "str", "{} の部分に検索する言葉が入ります"),
    ]),
    ("声・音声", [
        ("—", "読み上げ"),
        ("TTS_ENABLED", "返事を声で読み上げる", "bool", "VOICEVOX（無料の読み上げソフト）を使います"),
        ("VOICEVOX_SPEAKER", "声", "voice", "⬇ の付いた声は、保存するとその声だけダウンロード（使わない声は削除）"),
        ("VOICEVOX_URL", "VOICEVOX の URL（読み上げソフトの接続先）", "str", "通常は変更不要"),
        ("—", "聞き取り（再起動後に反映）"),
        ("WHISPER_MODEL", "Whisper（声を文字にするAI）の種類", "choice", "大きいほど正確ですが重くなります",
         [("tiny", "tiny（軽い・速い）"), ("base", "base（標準・より正確）")]),
        ("WHISPER_DEVICE", "計算に使う装置", "choice", "分からなければ CPU のまま",
         [("cpu", "CPU（どのPCでも動く）"), ("cuda", "CUDA（NVIDIA製GPU：速いが対応GPUが必要）")]),
        ("WHISPER_COMPUTE", "計算の細かさ", "choice", "分からなければ int8 のまま",
         [("int8", "int8（軽い・標準）"), ("float16", "float16（GPU向け）"),
          ("float32", "float32（最も細かい・重い）")]),
        ("LANGUAGE", "言語コード（話す言語）", "str", "ja = 日本語、en = 英語"),
        ("—", "常時待ち受けの感度"),
        ("VAD_THRESHOLD", "音量しきい値（声とみなす音の大きさ）", "float", "雑音を拾うなら大きく、声を拾わないなら小さく"),
        ("VAD_SILENCE_SEC", "話し終わりの判定（無音の秒数）", "float", "この秒数だけ静かになったら1回の発言として区切る"),
        ("VAD_MAX_SEC", "1回の発言の最大秒数", "float", ""),
        ("VAD_MIN_SEC", "1回の発言の最小秒数", "float", "これより短い音は無視（咳や物音対策）"),
    ]),
    ("AI", [
        ("—", "AIの頭脳"),
        ("OLLAMA_MODEL", "AIモデル（使う頭脳の種類）", "str", "変えたら「更新・情報」の「部品を準備」で取得"),
        ("OLLAMA_URL", "Ollama の URL（AIを動かすソフトの接続先）", "str", "通常は変更不要"),
        ("OLLAMA_TIMEOUT", "タイムアウト（返事を待つ最大秒数）", "int", ""),
        ("—", "動き方"),
        ("MAX_TOOL_STEPS", "1回の命令で行う操作の上限回数", "int", "暴走を防ぐための上限"),
        ("SUMMARIZE_AFTER_TOOL", "操作のあとにAIが返事を考える", "bool", "ONで自然な返事になりますが、少し遅くなります"),
        ("—", "会話の記憶"),
        ("CONTEXT_TURNS", "覚えておくやりとりの数（往復）", "int", "「それをもっと詳しく」のように前の話を受けて答えられます。0で記憶しない"),
        ("CONTEXT_RESET_MIN", "記憶を消すまでの時間（分）", "int", "この時間だけ話しかけなければ、新しい会話として始めます"),
    ]),
    ("更新・情報", [
        ("—", "アップデート（新しい版への更新）"),
        ("AUTO_UPDATE", "起動時に新しい版を確認", "bool", "見つかると会話ボタンに印が付きます"),
        ("UPDATE_REPO", "配布元（更新ファイルの置き場所）", "str", "GitHub のリポジトリ名（owner/repo の形）"),
    ]),
]
FIELDS = [f for _, fields in TABS for f in fields if f[0] != "—"]
_INFO_TAB = "更新・情報"


def parse(kind, raw):
    """入力値を設定値へ変換する。不正なら ValueError。"""
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "list":
        return [w.strip() for w in raw.replace("、", ",").split(",") if w.strip()]
    return raw.strip() if isinstance(raw, str) else raw


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, on_saved, on_quit, on_check_update):
        super().__init__(master, fg_color=T.BG)
        self._on_saved, self._on_quit, self._on_check_update = on_saved, on_quit, on_check_update
        self._vars = {}
        self._choices = {}  # キー -> {表示名: 値}
        self.title(f"{config.AI_NAME} 設定")
        self.geometry("640x560")
        self.minsize(560, 440)
        self.attributes("-topmost", True)
        if os.name == "nt":  # CTkToplevel は起動直後に既定アイコンへ戻すため少し待って設定
            self.after(250, lambda: self.iconbitmap(shortcut.ICON))
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---- 左: タブ ----
        side = ctk.CTkFrame(self, fg_color=T.SURFACE, corner_radius=0, width=150)
        side.grid(row=0, column=0, rowspan=2, sticky="ns")
        side.grid_propagate(False)
        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(pady=(18, 16), padx=14, anchor="w")
        ctk.CTkLabel(brand, text="", image=icons.emblem(26)).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(brand, text="設定", font=T.font(15, "bold"), text_color=T.TEXT).pack(side="left")
        self._tab_btns, self._pages = {}, {}
        for name, _ in TABS:
            b = ctk.CTkButton(side, text=name, anchor="w", height=36, corner_radius=10, font=T.font(12),
                              fg_color="transparent", hover_color=T.BORDER, text_color=T.SUB,
                              command=lambda n=name: self._select(n))
            b.pack(fill="x", padx=10, pady=2)
            self._tab_btns[name] = b
        ctk.CTkLabel(side, text=f"バージョン {VERSION}", font=T.font(10), text_color=T.SUB).pack(
            side="bottom", pady=12)

        # ---- 右: 各タブの中身 ----
        for name, fields in TABS:
            page = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=T.BORDER)
            page.grid_columnconfigure(0, weight=1)
            self._pages[name] = page
            self._build_fields(page, fields)
        self._build_info(self._pages[_INFO_TAB])

        # ---- 下: 保存 ----
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=1, column=1, sticky="ew", padx=16, pady=(4, 14))
        foot.grid_columnconfigure(0, weight=1)
        self.msg = ctk.CTkLabel(foot, text="", font=T.font(11), text_color=T.DANGER, anchor="w")
        self.msg.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(foot, text="既定に戻す", width=96, height=34, corner_radius=17, fg_color="transparent",
                      border_width=1, border_color=T.BORDER, text_color=T.SUB, hover_color=T.SURFACE,
                      font=T.font(12), command=self._reset).grid(row=0, column=1, padx=6)
        ctk.CTkButton(foot, text="保存", width=96, height=34, corner_radius=17, fg_color=T.ACCENT,
                      hover_color=T.ACCENT_HOVER, font=T.font(12, "bold"),
                      command=self._save).grid(row=0, column=2)

        self._fill(config.current())
        self._select(TABS[0][0])

    # ---------------- 画面づくり ----------------
    def _section(self, page, title):
        ctk.CTkLabel(page, text=title, font=T.font(12, "bold"), text_color=T.ACCENT, anchor="w").pack(
            fill="x", padx=8, pady=(14, 4))

    def _card_row(self, page):
        row = ctk.CTkFrame(page, fg_color=T.SURFACE, corner_radius=12)
        row.pack(fill="x", padx=4, pady=3)
        row.grid_columnconfigure(0, weight=1)
        return row

    def _build_fields(self, page, fields):
        for f in fields:
            if f[0] == "—":
                self._section(page, f[1])
                continue
            key, label, kind, hint = f[:4]
            if kind == "voice" and not voicevox.cached_catalog():
                kind = "int"  # 声の一覧が無いときは話者ID(声の番号)を直接入力
            # スイッチは右端、それ以外の入力欄は説明の下に横幅いっぱいで置く(長い項目名でも切れない)
            switch = kind == "bool"
            wrap = 330 if switch else 400
            row = self._card_row(page)
            ctk.CTkLabel(row, text=label, font=T.font(12), text_color=T.TEXT, anchor="w", justify="left",
                         wraplength=wrap).grid(row=0, column=0, sticky="w", padx=12, pady=(9, 0))
            if hint:
                ctk.CTkLabel(row, text=hint, font=T.font(10), text_color=T.SUB, anchor="w", justify="left",
                             wraplength=wrap).grid(row=1, column=0, sticky="w", padx=12)
            if switch:
                ctl = dict(row=0, column=1, rowspan=2, padx=12, pady=8, sticky="e")
                ctk.CTkFrame(row, height=9, fg_color="transparent").grid(row=2, column=0)
            else:
                ctl = dict(row=2, column=0, columnspan=2, padx=12, pady=(6, 10), sticky="ew")
            if kind == "bool":
                var = ctk.BooleanVar()
                ctk.CTkSwitch(row, text="", variable=var, width=46, progress_color=T.ACCENT).grid(**ctl)
            elif kind in ("choice", "voice"):
                var = ctk.StringVar()
                options = self._voice_choices() if kind == "voice" else [lbl for _, lbl in f[4]]
                if kind == "choice":
                    self._choices[key] = {lbl: val for val, lbl in f[4]}
                ctk.CTkOptionMenu(row, values=options, variable=var, dynamic_resizing=False,
                                  fg_color=T.BG, button_color=T.BG, button_hover_color=T.BORDER,
                                  dropdown_fg_color=T.SURFACE, font=T.font(11)).grid(**ctl)
            else:
                var = ctk.StringVar()
                ctk.CTkEntry(row, textvariable=var, fg_color=T.BG, border_color=T.BORDER,
                             font=T.font(11)).grid(**ctl)
            self._vars[key] = (kind, var)

    def _action(self, page, title, hint, text, command, danger=False):
        row = self._card_row(page)
        ctk.CTkLabel(row, text=title, font=T.font(12), text_color=T.TEXT, anchor="w").grid(
            row=0, column=0, sticky="w", padx=12, pady=(8, 0))
        ctk.CTkLabel(row, text=hint, font=T.font(10), text_color=T.SUB, anchor="w", justify="left",
                     wraplength=250).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))
        ctk.CTkButton(row, text=text, width=120, height=30, corner_radius=15, font=T.font(11),
                      fg_color="transparent", border_width=1, border_color=T.DANGER if danger else T.ACCENT,
                      text_color=T.DANGER if danger else T.TEXT, hover_color=T.BORDER,
                      command=command).grid(row=0, column=1, rowspan=2, padx=12)
        return row

    def _build_info(self, page):
        self._action(page, "更新を確認", f"いまのバージョン: {VERSION}", "今すぐ確認",
                     lambda: (self._show("確認中…"), self._on_check_update(self._show)))
        self._section(page, "部品（AI・音声のソフト）")
        self._action(page, "動作確認", "AIを動かすソフト（Ollama）と読み上げソフト（VOICEVOX）が動いているか",
                     "確認する", self._check)
        self._action(page, "部品を準備", "AIモデルを変えたときや、部品が壊れたときに再ダウンロード",
                     "準備画面を開く", self._open_setup)
        self.svc = ctk.CTkLabel(page, text="", font=T.font(11), text_color=T.CYAN, anchor="w", justify="left",
                                wraplength=380)
        self.svc.pack(fill="x", padx=12, pady=(6, 0))
        self._section(page, "その他")
        self._action(page, f"{config.AI_NAME} を終了", "常駐をやめます（次回はアイコンから起動）", "終了する",
                     self._on_quit)
        self._action(page, "アンインストール（削除）", "Zealous をこのPCから取り除きます", "アンインストール",
                     self._uninstall, danger=True)

    def _select(self, name):
        for n, page in self._pages.items():
            page.grid_forget()
            active = n == name
            self._tab_btns[n].configure(fg_color=T.ACCENT if active else "transparent",
                                        text_color="white" if active else T.SUB,
                                        hover_color=T.ACCENT_HOVER if active else T.BORDER)
        self._pages[name].grid(row=0, column=1, sticky="nsew", padx=(12, 8), pady=(12, 0))

    # ---------------- 部品・更新(別スレッドで実行し画面を止めない) ----------------
    def _bg(self, job):
        def run():
            try:
                job()
            except Exception as e:
                self._show(f"エラー: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _show(self, text):
        self.after(0, lambda: self.winfo_exists() and self.svc.configure(text=text))

    def _check(self):
        self._select(_INFO_TAB)
        self._show("確認中…")
        self._bg(lambda: self._show(services.check_ollama()[2] + "\n" + services.check_voicevox()[1]))

    def _open_setup(self):
        """セットアップ画面を開き、終わったら本体を再起動する。"""
        import subprocess
        subprocess.Popen(shortcut.command("--setup"), cwd=shortcut.HERE)
        self._on_quit()

    def _uninstall(self):
        import subprocess
        exe = shortcut.uninstaller()
        if not exe:
            self._show("ソース版はアンインストール不要です（フォルダを削除してください）")
            return
        subprocess.Popen([exe], cwd=shortcut.HERE)
        self._on_quit()

    def _voice_choices(self):
        """声の選択肢。未ダウンロードのものにはサイズを付ける。"""
        have = voicevox.installed_models()
        self._voice_ids, self._voice_labels = {}, {}
        for v in voicevox.cached_catalog():
            text = voicevox.label(v) + ("" if v["vvm"] in have else f"  ⬇{v['mb']}MB")
            self._voice_ids[text], self._voice_labels[v["id"]] = v["id"], text
        return list(self._voice_ids)

    # ---------------- 値の読み書き ----------------
    def _fill(self, values):
        for key, (kind, var) in self._vars.items():
            v = values[key]
            if kind == "voice":
                var.set(self._voice_labels.get(v, ""))
            elif kind == "choice":
                var.set(next((lbl for lbl, val in self._choices[key].items() if val == v), v))
            elif kind == "bool":
                var.set(v)
            else:
                var.set(", ".join(v) if kind == "list" else str(v))

    def _reset(self):
        self._fill(config.DEFAULTS)
        self.msg.configure(text="既定値を表示しています（保存で確定）", text_color=T.SUB)

    def _save(self):
        changes = {}
        for key, (kind, var) in self._vars.items():
            try:
                if kind == "voice":
                    changes[key] = self._voice_ids[var.get()]
                elif kind == "choice":
                    changes[key] = self._choices[key][var.get()]
                else:
                    changes[key] = parse(kind, var.get())
            except (ValueError, KeyError):
                name = next(f[1] for f in FIELDS if f[0] == key)
                self._select(next(t for t, fs in TABS if any(f[0] == key for f in fs)))
                self.msg.configure(text=f"入力値を確認してください: {name}", text_color=T.DANGER)
                return
        if not changes["AI_NAME"] or not changes["WAKE_WORDS"]:
            self._select("一般")
            self.msg.configure(text="AI名とウェイク語は必須です", text_color=T.DANGER)
            return
        try:
            shortcut.set_autostart(changes["AUTOSTART"])
        except Exception as e:
            self.msg.configure(text=f"自動起動の設定に失敗: {e}", text_color=T.DANGER)
            return
        config.save(changes)
        self._on_saved()
        self.destroy()
