"""各種設定の管理画面。保存すると settings.json に書き込み、即時反映する。"""
import customtkinter as ctk

import config

# (キー, 表示名, 種類[, 選択肢])  種類: str / int / float / bool / list / choice
FIELDS = [
    ("—", "AI・ウェイクワード"),
    ("AI_NAME", "AI名", "str"),
    ("AI_NAME_ALIASES", "AI名の別表記 (カンマ区切り)", "list"),
    ("WAKE_WORDS", "ウェイク語 (カンマ区切り)", "list"),
    ("—", "ブラウザ"),
    ("BROWSER", "使用ブラウザ", "choice", ["chrome", "edge", "firefox", "default"]),
    ("SEARCH_URL", "検索URL ({} に語句)", "str"),
    ("—", "AI (Ollama)"),
    ("OLLAMA_URL", "API URL", "str"),
    ("OLLAMA_MODEL", "モデル", "str"),
    ("OLLAMA_TIMEOUT", "タイムアウト(秒)", "int"),
    ("MAX_TOOL_STEPS", "関数呼び出し上限", "int"),
    ("SUMMARIZE_AFTER_TOOL", "実行後にAIが返答文を作る", "bool"),
    ("DRY_RUN", "お試しモード (操作しない)", "bool"),
    ("—", "音声合成 (VOICEVOX)"),
    ("TTS_ENABLED", "読み上げ", "bool"),
    ("VOICEVOX_URL", "API URL", "str"),
    ("VOICEVOX_SPEAKER", "話者ID", "int"),
    ("—", "音声認識 (再起動後に反映)"),
    ("WHISPER_MODEL", "Whisperモデル", "choice", ["tiny", "base"]),
    ("WHISPER_DEVICE", "デバイス", "choice", ["cpu", "cuda"]),
    ("WHISPER_COMPUTE", "演算精度", "choice", ["int8", "float16", "float32"]),
    ("LANGUAGE", "言語", "str"),
    ("—", "常時待ち受け"),
    ("VAD_THRESHOLD", "音量しきい値", "float"),
    ("VAD_SILENCE_SEC", "発話終了の無音(秒)", "float"),
    ("VAD_MAX_SEC", "最大発話長(秒)", "float"),
    ("VAD_MIN_SEC", "最小発話長(秒)", "float"),
]


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
    def __init__(self, master, on_saved):
        super().__init__(master)
        self._on_saved = on_saved
        self._vars = {}
        self.title(f"{config.AI_NAME} 設定")
        self.geometry("440x560")
        self.attributes("-topmost", True)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        body = ctk.CTkScrollableFrame(self)
        body.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        body.grid_columnconfigure(1, weight=1)
        for r, f in enumerate(FIELDS):
            if f[0] == "—":
                ctk.CTkLabel(body, text=f[1], font=("", 13, "bold")).grid(
                    row=r, column=0, columnspan=2, sticky="w", pady=(10, 2))
                continue
            key, label, kind = f[:3]
            ctk.CTkLabel(body, text=label).grid(row=r, column=0, sticky="w", padx=(4, 8), pady=2)
            if kind == "bool":
                var = ctk.BooleanVar()
                ctk.CTkSwitch(body, text="", variable=var).grid(row=r, column=1, sticky="w")
            elif kind == "choice":
                var = ctk.StringVar()
                ctk.CTkOptionMenu(body, values=f[3], variable=var).grid(row=r, column=1, sticky="ew")
            else:
                var = ctk.StringVar()
                ctk.CTkEntry(body, textvariable=var).grid(row=r, column=1, sticky="ew")
            self._vars[key] = (kind, var)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        foot.grid_columnconfigure(0, weight=1)
        self.msg = ctk.CTkLabel(foot, text="", text_color="#e76f51")
        self.msg.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(foot, text="既定に戻す", width=90, fg_color="gray40",
                      command=self._reset).grid(row=0, column=1, padx=4)
        ctk.CTkButton(foot, text="保存", width=80, command=self._save).grid(row=0, column=2)
        self._fill(config.current())

    def _fill(self, values):
        for key, (kind, var) in self._vars.items():
            v = values[key]
            var.set(", ".join(v) if kind == "list" else v if kind in ("bool", "choice") else str(v))

    def _reset(self):
        self._fill(config.DEFAULTS)
        self.msg.configure(text="既定値を表示中(保存で確定)", text_color="gray70")

    def _save(self):
        changes = {}
        for key, (kind, var) in self._vars.items():
            try:
                changes[key] = parse(kind, var.get())
            except ValueError:
                self.msg.configure(text=f"入力値が不正です: {key}", text_color="#e76f51")
                return
        if not changes["AI_NAME"] or not changes["WAKE_WORDS"]:
            self.msg.configure(text="AI名とウェイク語は必須です", text_color="#e76f51")
            return
        config.save(changes)
        self._on_saved()
        self.destroy()
