"""各種設定の管理画面(左のタブで切り替え)。保存すると settings.json に書き込み、即時反映する。
専門用語には必ず（）で分かりやすい言い換えを付ける。"""
import os
import threading

import customtkinter as ctk

import config
import icons
import models
import services
import shortcut
import theme as T
import voicevox
from version import VERSION

# 項目: (キー, 表示名, 種類, 補足説明[, 選択肢])
#   種類: str / int / float / bool / list / choice / model
#   choice の選択肢は (保存する値, 表示名) の組
TABS = [
    ("一般", [
        ("—", "名前と呼びかけ"),
        ("AI_NAME", "AI名", "str", "画面の表示と、呼びかけに使う名前"),
        ("USER_CALL", "あなたの呼び方", "str", "AIがあなたを呼ぶときの名前（例: たろうさん、マスター）。空なら名前では呼びません"),
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
        ("PTT_KEY", "話すキー", "choice",
         "普段の操作で使わないキーがおすすめ。スペースは長押しで話し、短く押すと普通のスペースになります",
         [("right ctrl", "右Ctrl"), ("space", "スペース（長押しで話す）"), ("right alt", "右Alt"),
          ("right shift", "右Shift"), ("f8", "F8"),
          ("f9", "F9"), ("f10", "F10"), ("scroll lock", "Scroll Lock"), ("pause", "Pause")]),
        ("—", "起動"),
        ("AUTOSTART", "PC起動時に自動で起動", "bool", "Windows にサインインしたら Zealous を立ち上げる"),
        ("—", "表示"),
        ("UI_THEME", "カラー（画面の配色）", "choice", "画面全体の色合い（保存後、再起動で反映）",
         [(k, v["LABEL"]) for k, v in T.THEMES.items()]),
        ("UI_FONT", "フォント（画面の文字の書体）", "font", "このPCに入っているフォントから選べます（保存後、再起動で反映）"),
        ("UI_FONT_SCALE", "文字の大きさ", "choice", "画面全体の文字の大きさ（保存後、再起動で反映）",
         [(90, "小さめ（90%）"), (100, "標準（100%）"), (115, "大きめ（115%）"), (130, "特大（130%）")]),
        ("IME_INLINE", "日本語入力を入力欄の中に表示", "bool",
         "変換中の文字を入力欄の中に表示します。文字入力で調子が悪いときはOFFに（再起動後に反映）"),
        ("SMOOTH_FRAME", "なめらかな外枠と影", "bool",
         "ウィジェット（常駐する小さな窓）の縁を滑らかにし、影を付けます。表示が乱れる場合はOFFに（再起動後に反映）"),
    ]),
    ("権限", [
        ("—", "AIに任せる操作"),
        ("SCREEN_CONTROL_ENABLED", "画面を直接操作する（マウス・キーボード）", "bool",
         "直前まで使っていたウィンドウで、ボタンを名前で探して押す・文字を入力する・キーを押す・スクロールするなどを許可します。"
         "止めたいときは緊急停止キーで止まります"),
        ("FOLDER_OPS_ENABLED", "ファイル・フォルダ操作を許可", "bool", "作成・名前変更・移動・コピー・一覧"),
        ("FOLDER_DELETE_ENABLED", "削除を許可", "bool", "削除はごみ箱へ移動するだけで、完全には消しません"),
        ("CONFIRM_VOICE_DANGER", "声での危険な操作は確認する", "bool",
         "声で頼まれた削除・移動・名前変更・シャットダウンは、実行する前に「はい/いいえ」で確かめます"
         "（近くの人やテレビの音声で勝手に実行されないように）"),
        ("DRY_RUN", "お試しモード", "bool", "実際には操作せず、何をするつもりかだけ表示"),
        ("—", "ブラウザ"),
        ("BROWSER", "使うブラウザ", "choice", "Webページを開くときのブラウザ",
         [("chrome", "Chrome"), ("edge", "Edge"), ("firefox", "Firefox"), ("default", "既定のブラウザ")]),
        ("SEARCH_URL", "検索URL（検索サイトのアドレス）", "str", "{} の部分に検索する言葉が入ります"),
        ("—", "検索結果"),
        ("SAFE_SITES_ONLY", "安全なサイトだけを案内する", "bool",
         "危険（ウイルス・詐欺）と判定されたサイトは、検索結果・画像・リンクに出しません"),
        ("SOURCE_COUNT", "返事に添えるリンクの数", "int", "調べものの返事の下に出す参考ページの数（例: 3）"),
        ("SEARCH_IMAGE_COUNT", "返事に添える画像の枚数", "int", "調べものの返事に添える関連画像の数（0で出さない）"),
        ("IMAGE_COUNT", "画像を探したときの枚数", "int", "「〜の画像を探して」で一覧に出す枚数（例: 30）"),
    ]),
    ("声・音声", [
        ("—", "読み上げ"),
        ("TTS_ENABLED", "返事を声で読み上げる", "bool", "VOICEVOX（無料の読み上げソフト）を使います"),
        ("＊", "voice_picker"),  # 「声を選ぶ」ボタン(キャラ一覧・試聴・ダウンロード)
        ("TTS_SPEED", "話す速さ（1.0 が標準）", "float", "大きいほど速く話します（例: 1.2）"),
        ("READINGS", "読み方の辞書（読み上げの読み方を決める）", "list",
         "「表記=よみ」の形でカンマ（,）区切り。例: 生物=なまもの, 才=さい。"
         "「行っている」など、文の流れで読み方が変わる言葉は自動で読み分けます"),
        ("VOICEVOX_URL", "VOICEVOX の URL（読み上げソフトの接続先）", "str", "通常は変更不要"),
        ("—", "聞き取り"),
        ("MIC_DEVICE", "マイク", "mic", "聞き取れないことが多いときは、使っているマイクを選んでください"),
        ("COMMAND_WHISPER_MODEL", "命令の聞き取りに使うAI（Whisper：声を文字にするAI）", "choice",
         "話しかけた命令を文字にするときに使います。大きいほど正確ですが、返事までが少し遅くなります",
         [("base", "base（軽い・約0.15GB）"), ("small", "small（おすすめ・約0.5GB）"),
          ("medium", "medium（高精度・約1.5GB・重い）"), ("large-v3-turbo", "large-v3-turbo（最も正確・約1.6GB・重い）")]),
        ("WHISPER_MODEL", "待機中の聞き取りに使うAI", "choice",
         "合図の言葉を待つ間ずっと使うので、軽いものがおすすめ",
         [("tiny", "tiny（いちばん軽い）"), ("base", "base（標準）"), ("small", "small（正確・PCが重くなりやすい）")]),
        ("VOICE_WORDS", "ユーザー辞書（正しく聞き取ってほしい言葉）", "list",
         "人や会社の名前、よく使う専門用語などをカンマ（,）区切りで。例: 株式会社才, Zealous"),
        ("VOICE_REPLACE", "置き換え（よく間違う言葉の直し方）", "list",
         "「まちがい=正しい」の形でカンマ（,）区切り。例: ゼラス=Zealous, 才コンサル=才コンサルティング"),
        ("WHISPER_DEVICE", "計算に使う装置", "choice", "分からなければ CPU（PCの標準の計算装置）のまま",
         [("cpu", "CPU（どのPCでも動く）"), ("cuda", "CUDA（NVIDIA製GPU：速いが対応GPUが必要）")]),
        ("WHISPER_COMPUTE", "計算の細かさ", "choice", "分からなければ int8（軽い標準の設定）のまま",
         [("int8", "int8（軽い・標準）"), ("float16", "float16（GPU向け）"),
          ("float32", "float32（最も細かい・重い）")]),
        ("LANGUAGE", "言語コード（話す言語・AIが答える言語）", "str",
         "ja = 日本語、en = 英語 など。声の聞き取りと、AIの返事の言葉の両方に使います"),
        ("—", "常時待ち受けの感度"),
        ("VAD_THRESHOLD", "音量しきい値（声とみなす音の大きさ）", "float", "雑音を拾うなら大きく、声を拾わないなら小さく"),
        ("VAD_SILENCE_SEC", "話し終わりの判定（無音の秒数）", "float", "この秒数だけ静かになったら1回の発言として区切る"),
        ("VAD_MAX_SEC", "1回の発言の最大秒数", "float", ""),
        ("VAD_MIN_SEC", "1回の発言の最小秒数", "float", "これより短い音は無視（咳や物音対策）"),
    ]),
    ("AI", [
        ("—", "AIの性格・話し方"),
        ("PERSONA", "AIの性格・話し方", "persona",
         "例:「兄弟のようにタメ口で」「関西弁で明るく」「結論から短く答える」。下の型から選んで書き足すこともできます。"
         "会話の中で「関西弁で話して」「話し方を元に戻して」と言っても変えられます"),
        ("—", "記憶"),
        ("MEMORY", "AIが覚えていること", "lines",
         "1行に1つ。会話で「〜を覚えておいて」と言うと増え、「〜を忘れて」で消えます。ここで直接書き直すこともできます"),
        ("—", "AIの頭脳"),
        ("OLLAMA_MODEL", "AIモデル（使う頭脳の種類）", "model",
         "一覧から選ぶか名前を入力。変えるときはサイズを確認してから、保存でダウンロードします"),
        ("OLLAMA_URL", "Ollama の URL（AIを動かすソフトの接続先）", "str", "通常は変更不要"),
        ("OLLAMA_TIMEOUT", "タイムアウト（返事を待つ最大秒数）", "int", ""),
        ("USE_GPU", "GPU（NVIDIA製の画像処理チップ）でAIを速くする", "bool",
         "NVIDIA製GPUがあるPCのみ。ONだと追加で約0.6〜0.9GBをダウンロード。"
         "変更後は「更新・情報」の「部品を準備」で反映"),
        ("—", "動き方"),
        ("MAX_TOOL_STEPS", "1回の命令で行う操作の上限回数", "int", "暴走を防ぐための上限"),
        ("SUMMARIZE_AFTER_TOOL", "操作のあとにAIが返事を考える", "bool", "ONで自然な返事になりますが、少し遅くなります"),
        ("—", "会話の記憶"),
        ("CONTEXT_TURNS", "覚えておくやりとりの数（往復）", "int",
         "同じチャット（スレッド）の中で、「それをもっと詳しく」のように前の話を受けて答えます。"
         "話題を変えるときは「新しいチャット」を押してください。0で記憶しない"),
    ]),
    ("更新・情報", [
        ("—", "アップデート（新しい版への更新）"),
        ("AUTO_UPDATE", "起動時に新しい版を確認", "bool", "見つかると会話ボタンに印が付きます"),
    ]),
]
# 数を「つまみ」で選べる項目: (最小, 最大, 刻み)
SLIDERS = {
    "TTS_SPEED": (0.5, 2.0, 0.05),
    "VAD_THRESHOLD": (0.002, 0.06, 0.001),
    "VAD_SILENCE_SEC": (0.3, 3.0, 0.1),
    "VAD_MIN_SEC": (0.1, 2.0, 0.1),
    "VAD_MAX_SEC": (5, 60, 1),
    "CONTEXT_TURNS": (0, 12, 1),
    "SOURCE_COUNT": (0, 8, 1),
    "SEARCH_IMAGE_COUNT": (0, 16, 1),
    "IMAGE_COUNT": (8, 60, 1),
}


def _digits(step):
    text = f"{step:g}"
    return len(text.split(".")[1]) if "." in text else 0


FIELDS = [f for _, fields in TABS for f in fields if f[0] not in ("—", "＊")]
_INFO_TAB = "更新・情報"


def parse(kind, raw):
    """入力値を設定値へ変換する。不正なら ValueError。"""
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "list":
        return [w.strip() for w in raw.replace("、", ",").split(",") if w.strip()]
    if kind == "lines":
        return [w.strip() for w in raw.splitlines() if w.strip()]
    return raw.strip() if isinstance(raw, str) else raw


DEFAULT_LABEL = f"標準（{T.DEFAULT_FONT}）"
_FIRST = ["Yu Gothic UI", "Meiryo UI", "BIZ UDPGothic", "BIZ UDゴシック", "游ゴシック", "メイリオ",
          "Noto Sans JP", "UD デジタル 教科書体 NK-R", "MS UI Gothic"]


def font_choices(widget):
    """このPCのフォント一覧(日本語でよく使うものを先頭に。縦書き用の @ 付きは除く)。"""
    import tkinter.font as tkfont
    names = sorted({n for n in tkfont.families(widget) if not n.startswith("@")}, key=str.lower)
    first = [n for n in _FIRST if n in names]
    return first + [n for n in names if n not in first]


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, on_saved, on_quit, on_check_update, on_pick_voice, on_update, on_clear_history=None):
        super().__init__(master, fg_color=T.BG)
        self._on_saved, self._on_quit, self._on_check_update = on_saved, on_quit, on_check_update
        self._on_pick_voice = on_pick_voice
        self._on_update = on_update
        self._on_clear_history = on_clear_history
        self._vars = {}
        self._choices = {}  # キー -> {表示名: 値}
        self._items = {}  # ページ -> [(部品, 置き方, 検索用の文字 または None(見出し))]
        self._rows = {}   # キー -> 項目のカード
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
        # 設定の検索(項目名・説明に含まれる言葉で絞り込む)
        self.search = ctk.CTkEntry(side, placeholder_text="設定を検索", height=30, corner_radius=15,
                                   fg_color=T.BG, border_color=T.BORDER, text_color=T.TEXT, font=T.font(11))
        self.search.pack(fill="x", padx=10, pady=(0, 10))
        self.search.bind("<KeyRelease>", lambda e: self._filter(self.search.get()))
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
        self._foot = foot
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
        # 変更した項目を目立たせ、保存していない変更の数を出す
        self._save_btn = self._foot.winfo_children()[-1]
        for _, var in self._vars.values():
            var.trace_add("write", lambda *_: self._dirty_later())
        self._refresh_dirty()
        self.protocol("WM_DELETE_WINDOW", self._close)
        # 日本語入力の変換中の文字を、チャット欄と同じように入力欄の中に表示する
        import ime
        ime.attach_all(self, T.FONT, 15)

        # 保存したときのお知らせ(少しだけ出して消える)
        self.toast = ctk.CTkLabel(self, text="✓  保存しました", font=T.font(12, "bold"), text_color="white",
                                  fg_color=T.OK, corner_radius=16, height=34, width=150)

    # ---------------- 画面づくり ----------------
    def _section(self, page, title):
        w = ctk.CTkLabel(page, text=title, font=T.font(12, "bold"), text_color=T.ACCENT, anchor="w")
        kw = dict(fill="x", padx=8, pady=(14, 4))
        w.pack(**kw)
        self._items.setdefault(page, []).append((w, kw, None))  # 見出し(検索で、中身が無ければ隠す)

    def _card_row(self, page, search=""):
        row = ctk.CTkFrame(page, fg_color=T.SURFACE, corner_radius=12, border_width=1, border_color=T.SURFACE)
        kw = dict(fill="x", padx=4, pady=3)
        row.pack(**kw)
        row.grid_columnconfigure(0, weight=1)
        self._items.setdefault(page, []).append((row, kw, search.lower()))
        return row

    def _build_fields(self, page, fields):
        for f in fields:
            if f[0] == "—":
                self._section(page, f[1])
                continue
            if f[0] == "＊":
                self._voice_card(page)
                continue
            if f[2] == "mic":  # マイクはこのPCにつながっているものから選ぶ
                import voice
                f = (*f[:2], "choice", f[3],
                     [("", "既定のマイク（Windows の設定）")] + [(n, n) for n in voice.input_devices()])
            key, label, kind, hint = f[:4]
            # スイッチは右端、それ以外の入力欄は説明の下に横幅いっぱいで置く(長い項目名でも切れない)
            switch = kind == "bool"
            wrap = 330 if switch else 400
            row = self._card_row(page, f"{label} {hint} {key}")
            self._rows[key] = row
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
                # スイッチだけでなく、項目のどこを押しても切り替わる
                for w in [row] + [c for c in row.winfo_children() if isinstance(c, ctk.CTkLabel)]:
                    w.bind("<Button-1>", lambda e, v=var: v.set(not v.get()), add="+")
                    w.configure(cursor="hand2")
            elif kind in ("float", "int") and key in SLIDERS:
                var = ctk.StringVar()
                lo, hi, step = SLIDERS[key]
                box = ctk.CTkFrame(row, fg_color="transparent")
                box.grid(**ctl)
                box.grid_columnconfigure(0, weight=1)
                value = ctk.CTkLabel(box, text="", font=T.font(11, "bold"), text_color=T.TEXT, width=48, anchor="e")
                value.grid(row=0, column=1, padx=(8, 0))
                fmt = (lambda x: str(int(round(x)))) if kind == "int" else (lambda x, st=step: f"{round(x / st) * st:.{_digits(st)}f}")
                slider = ctk.CTkSlider(box, from_=lo, to=hi, number_of_steps=int(round((hi - lo) / step)),
                                       progress_color=T.ACCENT, button_color=T.ACCENT_LIGHT,
                                       button_hover_color=T.ACCENT, command=lambda x, v=var, f=fmt: v.set(f(x)))
                slider.grid(row=0, column=0, sticky="ew")

                def show(*_, v=var, s_=slider, lab=value, lo=lo, hi=hi):  # 値が変わったら、つまみと数字も合わせる
                    try:
                        x = float(v.get())
                    except ValueError:
                        return
                    lab.configure(text=v.get())
                    s_.set(min(hi, max(lo, x)))
                var.trace_add("write", show)
            elif kind == "model":
                var = ctk.StringVar()
                ctk.CTkComboBox(row, values=[models.label(k[0]) for k in models.KNOWN], variable=var,
                                fg_color=T.BG, border_color=T.BORDER, button_color=T.BG,
                                button_hover_color=T.BORDER, dropdown_fg_color=T.SURFACE, dropdown_text_color=T.TEXT, text_color=T.TEXT,
                                  font=T.font(11)).grid(**ctl)
                # 選んだモデルの特徴と注意点
                info = ctk.CTkFrame(row, fg_color=T.BG, corner_radius=10)
                info.grid(row=3, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
                info.grid_columnconfigure(1, weight=1)
                labels = {}
                for r, (name, color) in enumerate((("特徴", T.OK), ("注意", T.WARN))):
                    ctk.CTkLabel(info, text=name, font=T.font(10, "bold"), text_color=color, width=34,
                                 anchor="nw").grid(row=r, column=0, sticky="nw", padx=(10, 4), pady=(8 if r == 0 else 2, 2))
                    labels[name] = ctk.CTkLabel(info, text="", font=T.font(10), text_color=T.TEXT, anchor="w",
                                                justify="left", wraplength=300)
                    labels[name].grid(row=r, column=1, sticky="ew", padx=(0, 10), pady=(8 if r == 0 else 2, 2))
                ctk.CTkFrame(info, height=6, width=1, fg_color="transparent").grid(row=2, column=0)
                # 枠の幅に合わせて折り返す(長い説明でも切れない)
                info.bind("<Configure>", lambda e, lab=labels, i=info: [
                    l.configure(wraplength=max(160, int(e.width / i._get_widget_scaling()) - 70)) for l in lab.values()],
                    add="+")

                def describe(*_, v=var, lab=labels):
                    d = models.details(models.name_of(v.get()))
                    good, warn = d if d else ("一覧にないモデルです。Ollama の名前（例: gemma3:4b）を入力できます。",
                                              "保存のときに大きさを調べてお知らせします。日本語やPC操作に対応していないモデルもあります。")
                    lab["特徴"].configure(text=good)
                    lab["注意"].configure(text=warn)
                var.trace_add("write", describe)
            elif kind == "lines":
                var = ctk.StringVar()
                box = ctk.CTkTextbox(row, height=86, fg_color=T.BG, border_color=T.BORDER, border_width=1,
                                     font=T.font(11), text_color=T.TEXT, wrap="char")
                box.grid(**ctl)

                def sync_lines(*_, b=box, v=var):
                    if b.get("1.0", "end-1c") != v.get():
                        b.delete("1.0", "end")
                        b.insert("1.0", v.get())
                var.trace_add("write", sync_lines)
                box.bind("<KeyRelease>", lambda e, b=box, v=var: v.set(b.get("1.0", "end-1c")), add="+")
            elif kind == "persona":
                import persona
                var = ctk.StringVar()
                box = ctk.CTkTextbox(row, height=74, fg_color=T.BG, border_color=T.BORDER, border_width=1,
                                     font=T.font(11), text_color=T.TEXT, wrap="char")
                box.grid(**ctl)
                # 入力欄の中身を、ほかの欄と同じように var で読み書きできるようにする
                def sync(*_, b=box, v=var):
                    if b.get("1.0", "end-1c") != v.get():
                        b.delete("1.0", "end")
                        b.insert("1.0", v.get())
                var.trace_add("write", sync)
                box.bind("<KeyRelease>", lambda e, b=box, v=var: v.set(b.get("1.0", "end-1c")), add="+")
                chips = ctk.CTkFrame(row, fg_color="transparent")
                chips.grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10))
                for i, (name, text) in enumerate(persona.PRESETS):
                    ctk.CTkButton(chips, text=name, height=26, width=10, corner_radius=13, font=T.font(10),
                                  fg_color="transparent", border_width=1, border_color=T.BORDER,
                                  hover_color=T.SURFACE, text_color=T.TEXT,
                                  command=lambda t=text, v=var: v.set(t)).grid(row=i // 3, column=i % 3,
                                                                                padx=2, pady=2, sticky="w")
            elif kind == "font":
                var = ctk.StringVar()
                fonts = font_choices(self)
                self._choices[key] = {DEFAULT_LABEL: "", **{n: n for n in fonts}}
                box = ctk.CTkComboBox(row, values=[DEFAULT_LABEL] + fonts, variable=var, fg_color=T.BG,
                                      border_color=T.BORDER, button_color=T.BG, button_hover_color=T.BORDER,
                                      dropdown_fg_color=T.SURFACE, font=T.font(11), text_color=T.TEXT)
                box.grid(**ctl)
                preview = ctk.CTkLabel(row, text="", text_color=T.TEXT, anchor="w")
                preview.grid(row=3, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 10))

                def show(*_, v=var, p=preview):  # 選んだフォントの見本
                    name = self._choices["UI_FONT"].get(v.get(), v.get()) or T.DEFAULT_FONT
                    p.configure(text="見本: こんにちは、Zealous です。Aa 123", font=(name, 13))
                var.trace_add("write", show)
            elif kind == "choice":
                var = ctk.StringVar()
                options = [lbl for _, lbl in f[4]]
                self._choices[key] = {lbl: val for val, lbl in f[4]}
                ctk.CTkOptionMenu(row, values=options, variable=var, dynamic_resizing=False,
                                  fg_color=T.BG, button_color=T.BG, button_hover_color=T.BORDER,
                                  dropdown_fg_color=T.SURFACE, dropdown_text_color=T.TEXT, text_color=T.TEXT,
                                  font=T.font(11)).grid(**ctl)
            else:
                var = ctk.StringVar()
                ctk.CTkEntry(row, textvariable=var, fg_color=T.BG, border_color=T.BORDER,
                             font=T.font(11), text_color=T.TEXT).grid(**ctl)
            self._vars[key] = (kind, var)

    def _action(self, page, title, hint, text, command, danger=False):
        row = self._card_row(page, f"{title} {hint}")
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
        # ---- アップデート: 確認して、新しい版があればここから更新できる ----
        row = self._card_row(page, "アップデート 更新 バージョン")
        ctk.CTkLabel(row, text="アップデート", font=T.font(12), text_color=T.TEXT, anchor="w").grid(
            row=0, column=0, sticky="w", padx=12, pady=(9, 0))
        self.upd_status = ctk.CTkLabel(row, text=f"現在のバージョン: {VERSION}", font=T.font(10),
                                       text_color=T.SUB, anchor="w", justify="left", wraplength=300)
        # 結果の文が長くても途切れないよう、文はカードの幅いっぱいに折り返し、ボタンはその下に置く
        self.upd_status.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 6))
        row.grid_columnconfigure(0, weight=1)
        row.bind("<Configure>", lambda e: self.upd_status.configure(
            wraplength=max(200, int(e.width / self.upd_status._get_widget_scaling()) - 30)), add="+")
        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 10))
        self.upd_check = ctk.CTkButton(btns, text="今すぐ確認", width=100, height=30, corner_radius=15,
                                       font=T.font(11), fg_color="transparent", border_width=1,
                                       border_color=T.ACCENT, text_color=T.TEXT, hover_color=T.BORDER,
                                       command=self._check_update)
        self.upd_check.pack(side="left")
        self.upd_go = ctk.CTkButton(btns, text="アップデート", width=110, height=30, corner_radius=15,
                                    font=T.font(11, "bold"), fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER)
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
        self._action(page, "会話の履歴を消す", "これまでのチャット・音声会話の記録と、動きの記録をすべて消します",
                     "すべて消す", self._clear_history, danger=True)
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

    def _check_update(self):
        self.upd_go.pack_forget()
        self._upd_text("確認中…", T.SUB)

        def report(msg, info):  # 裏のスレッドから届く
            self.after(0, lambda: self._update_result(msg, info))
        self._on_check_update(report)

    def _update_result(self, msg, info):
        if not self.winfo_exists():
            return
        self._upd_text(msg, T.WARN if msg.startswith("確認できません") else T.CYAN if info else T.OK)
        if info:
            self.upd_go.configure(text=f"v{info['version']} に更新", state="normal",
                                  command=lambda: self._run_update(info))
            self.upd_go.pack(side="left", padx=(6, 0))

    def _run_update(self, info):
        self.upd_go.configure(state="disabled", text="更新中…")
        self.upd_check.configure(state="disabled")

        def progress(text, failed=False):
            self._upd_text(text, T.DANGER if failed else T.CYAN)
            if failed:
                self.upd_go.configure(state="normal", text="もう一度")
                self.upd_check.configure(state="normal")
        self._on_update(info, progress)

    def _upd_text(self, text, color):
        if self.winfo_exists():
            self.upd_status.configure(text=text, text_color=color)

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

    # ---------------- 変更の管理 ----------------
    def _value(self, key):
        """入力欄の値を設定値にする(不正なら ValueError / KeyError)。"""
        kind, var = self._vars[key]
        if kind == "model":
            name = models.name_of(var.get())
            if not name:
                raise ValueError
            return name
        if kind == "choice":
            return self._choices[key][var.get()]
        if kind == "font":
            return self._choices[key].get(var.get(), var.get().strip())
        return parse(kind, var.get())

    def _dirty(self):
        out = []
        for key in self._vars:
            try:
                if self._value(key) != getattr(config, key):
                    out.append(key)
            except (ValueError, KeyError):
                out.append(key)
        return out

    def _dirty_later(self):
        if not getattr(self, "_dirty_job", None):
            self._dirty_job = self.after(80, self._refresh_dirty)

    def _refresh_dirty(self):
        self._dirty_job = None
        if not self.winfo_exists():
            return
        dirty = set(self._dirty())
        for key, row in self._rows.items():
            row.configure(border_color=T.ACCENT if key in dirty else T.SURFACE)
        for name, fields in TABS:
            n = sum(1 for f in fields if f[0] in dirty)
            base = self._tab_btns[name].cget("text").split("  ")[0]
            self._tab_btns[name].configure(text=f"{base}  ●" if n else base)
        self._save_btn.configure(text=f"保存（{len(dirty)}）" if dirty else "保存")
        if dirty:
            self.msg.configure(text=f"● 保存していない変更が {len(dirty)} 件あります", text_color=T.WARN)
        elif self.msg.cget("text").startswith("●"):
            self.msg.configure(text="")

    def _close(self):
        """保存していない変更があれば、閉じる前に確かめる。"""
        if self._dirty():
            import tkinter.messagebox as mb
            answer = mb.askyesnocancel("設定", "保存していない変更があります。保存してから閉じますか？", parent=self)
            if answer is None:
                return
            if answer:
                self._save()
                if self._dirty():  # 入力に誤りがあって保存できなかった
                    return
        self.destroy()

    # ---------------- 検索 ----------------
    def _filter(self, query):
        """項目名・説明に query を含む項目だけを見せる。空なら元に戻す。"""
        q = query.strip().lower()
        first = None
        for name, page in self._pages.items():
            items = self._items.get(page, [])
            visible = []
            for i, (w, kw, text) in enumerate(items):
                if text is None:  # 見出し: 次の見出しまでに見える項目があれば見せる
                    rest = []
                    for w2, _, t2 in items[i + 1:]:
                        if t2 is None:
                            break
                        rest.append(t2)
                    visible.append(not q or any(q in t for t in rest))
                else:
                    visible.append(not q or q in text)
            for w, kw, _ in items:
                w.pack_forget()
            for (w, kw, _), show in zip(items, visible):
                if show:
                    w.pack(**kw)
            hits = sum(1 for (w, kw, t), show in zip(items, visible) if show and t is not None)
            base = self._tab_btns[name].cget("text").split("（")[0].split("  ")[0]
            self._tab_btns[name].configure(text=f"{base}（{hits}）" if q else base,
                                           state="normal" if (hits or not q) else "disabled")
            if q and hits and first is None:
                first = name
        if q and first:
            self._select(first)
        elif not q:
            self._refresh_dirty()

    def _show_toast(self):
        if not self.winfo_exists():
            return
        self.toast.place(in_=self._foot, relx=0.5, y=-12, anchor="s")  # 設定の中身の真ん中、保存ボタンの上
        self.toast.lift()
        if getattr(self, "_toast_job", None):
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(1800, lambda: self.winfo_exists() and self.toast.place_forget())

    def _clear_history(self):
        import tkinter.messagebox as mb
        if not mb.askyesno("会話の履歴を消す", "これまでの会話の記録をすべて消します。元には戻せません。よろしいですか？",
                           parent=self):
            return
        import threads
        threads.delete_all()
        for name in ("trace.log", "trace.log.old"):  # 動きの記録も消す
            try:
                os.remove(os.path.join(config.APP_DIR, name))
            except OSError:
                pass
        if self._on_clear_history:
            self._on_clear_history()
        self._show("会話の履歴を消しました")

    def _uninstall(self):
        import subprocess
        exe = shortcut.uninstaller()
        if not exe:
            self._show("ソース版はアンインストール不要です（フォルダを削除してください）")
            return
        subprocess.Popen([exe], cwd=shortcut.HERE)
        self._on_quit()

    def _voice_card(self, page):
        """現在の声と「声を選ぶ」ボタン。キャラ一覧の画面で試聴・ダウンロードする。"""
        row = self._card_row(page, "声 キャラクター VOICEVOX 読み上げ 選ぶ")
        ctk.CTkLabel(row, text="声", font=T.font(12), text_color=T.TEXT, anchor="w").grid(
            row=0, column=0, sticky="w", padx=12, pady=(9, 0))
        self.voice_now = ctk.CTkLabel(row, text="", font=T.font(11), text_color=T.CYAN, anchor="w")
        self.voice_now.grid(row=1, column=0, sticky="w", padx=12)
        ctk.CTkLabel(row, text="キャラクターの一覧から試聴して選べます。選んだ声のモデル（約55MB）だけを"
                               "ダウンロードし、使わなくなった声は削除します。",
                     font=T.font(10), text_color=T.SUB, anchor="w", justify="left", wraplength=330).grid(
            row=2, column=0, sticky="w", padx=12, pady=(2, 10))
        ctk.CTkButton(row, text="声を選ぶ", width=110, height=34, corner_radius=17, fg_color=T.ACCENT,
                      hover_color=T.ACCENT_HOVER, font=T.font(12, "bold"),
                      command=lambda: self._on_pick_voice(self.refresh_voice)).grid(
            row=0, column=1, rowspan=3, padx=12)
        self.refresh_voice()

    def refresh_voice(self):
        cur = next((v for v in voicevox.cached_catalog() if v["id"] == config.VOICEVOX_SPEAKER), None)
        if self.winfo_exists():
            self.voice_now.configure(text=f"現在の声: {voicevox.label(cur) if cur else config.VOICEVOX_SPEAKER}")

    # ---------------- 値の読み書き ----------------
    def _fill(self, values):
        for key, (kind, var) in self._vars.items():
            v = values[key]
            if kind == "model":
                var.set(models.label(v))
            elif kind == "font":
                var.set(v or DEFAULT_LABEL)
            elif kind == "choice":
                # 選択肢に無い値(外したマイクなど)は先頭の選択肢にする
                var.set(next((lbl for lbl, val in self._choices[key].items() if val == v),
                             next(iter(self._choices[key]))))
            elif kind == "bool":
                var.set(v)
            elif kind == "lines":
                var.set("\n".join(v))
            else:
                var.set(", ".join(v) if kind == "list" else str(v))

    def _reset(self):
        self._fill(config.DEFAULTS)
        self.msg.configure(text="既定値を表示しています（保存で確定）", text_color=T.SUB)

    def _save(self):
        changes = {}
        for key, (kind, var) in self._vars.items():
            try:
                if kind == "model":
                    changes[key] = models.name_of(var.get())
                    if not changes[key]:
                        raise ValueError
                elif kind == "choice":
                    changes[key] = self._choices[key][var.get()]
                elif kind == "font":
                    changes[key] = self._choices[key].get(var.get(), var.get().strip())
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
        if changes["OLLAMA_MODEL"] != config.OLLAMA_MODEL:
            # AIモデルの変更は、必ずサイズと注意を伝えて確認してから
            self.msg.configure(text="モデルのサイズを確認中…", text_color=T.SUB)
            name = changes["OLLAMA_MODEL"]
            threading.Thread(target=lambda: self.after(0, lambda w=models.warning(name): self._confirm(w, changes)),
                             daemon=True).start()
            return
        self._commit(changes)

    def _confirm(self, text, changes):
        """モデル変更の確認ダイアログ。"""
        self.msg.configure(text="")
        dlg = ctk.CTkToplevel(self, fg_color=T.BG)
        dlg.title("AIモデルの変更")
        dlg.attributes("-topmost", True)
        dlg.resizable(False, False)
        ctk.CTkLabel(dlg, text="⚠ 確認してください", font=T.font(14, "bold"), text_color=T.WARN).pack(
            anchor="w", padx=20, pady=(18, 6))
        ctk.CTkLabel(dlg, text=text, font=T.font(12), text_color=T.TEXT, justify="left", wraplength=400).pack(
            anchor="w", padx=20)
        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(anchor="e", padx=20, pady=18)
        ctk.CTkButton(btns, text="やめる", width=96, height=34, corner_radius=17, fg_color="transparent",
                      border_width=1, border_color=T.BORDER, text_color=T.SUB, hover_color=T.SURFACE,
                      command=dlg.destroy).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="変更してダウンロード", width=160, height=34, corner_radius=17,
                      fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER, font=T.font(12, "bold"),
                      command=lambda: (dlg.destroy(), self._commit(changes))).pack(side="left")
        dlg.grab_set()

    def _commit(self, changes):
        try:
            shortcut.set_autostart(changes["AUTOSTART"])
        except Exception as e:
            self.msg.configure(text=f"自動起動の設定に失敗: {e}", text_color=T.DANGER)
            return
        restart = any(changes.get(k) != getattr(config, k) for k in ("UI_FONT", "UI_FONT_SCALE", "UI_THEME"))
        config.save(changes)
        self._on_saved()
        self.msg.configure(text="")
        self._show_toast()  # 画面は閉じずに、保存したことだけを知らせる
        self._refresh_dirty()
        if restart:
            import tkinter.messagebox as mb
            if mb.askyesno("表示の変更", "カラー・フォント・文字の大きさは、再起動すると反映されます。\n今すぐ再起動しますか？"):
                self.master.restart_app()
