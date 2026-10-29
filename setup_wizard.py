"""初回セットアップ画面。AIエンジン・AIモデル・音声合成・音声認識を自動で準備する。"""
import threading

import customtkinter as ctk

import config
import icons
import runtime
import theme as T

ICON = {"wait": "○", "run": "◌", "ok": "✓", "ng": "✕"}
COLOR = {"wait": T.SUB, "run": T.CYAN, "ok": T.OK, "ng": T.DANGER}


class SetupWizard(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=T.BG)
        self.title("Zealous セットアップ")
        self.geometry("460x420")
        self.resizable(False, False)
        self.completed = False
        self.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, pady=(22, 4))
        ctk.CTkLabel(head, text="", image=icons.emblem(44)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(head, text="", image=icons.wordmark("Zealous", 20)).pack(side="left")
        ctk.CTkLabel(self, text="AIと音声の部品を準備します（初回のみ・合計 約4〜5GB）\n"
                                "回線によっては数十分かかります。途中で閉じても続きから再開できます。",
                     font=T.font(11), text_color=T.SUB, justify="center").grid(row=1, column=0, pady=(0, 12))

        box = ctk.CTkFrame(self, fg_color=T.SURFACE, corner_radius=14)
        box.grid(row=2, column=0, sticky="ew", padx=24)
        box.grid_columnconfigure(1, weight=1)
        self.rows = []
        for i, (name, _) in enumerate(runtime.STEPS):
            mark = ctk.CTkLabel(box, text=ICON["wait"], width=20, font=T.font(14, "bold"), text_color=T.SUB)
            mark.grid(row=i, column=0, padx=(14, 6), pady=6)
            ctk.CTkLabel(box, text=name, font=T.font(12), text_color=T.TEXT, anchor="w").grid(
                row=i, column=1, sticky="w")
            note = ctk.CTkLabel(box, text="", font=T.font(10), text_color=T.SUB, anchor="e")
            note.grid(row=i, column=2, sticky="e", padx=(6, 14))
            self.rows.append((mark, note))

        self.bar = ctk.CTkProgressBar(self, progress_color=T.ACCENT, fg_color=T.SURFACE, height=6)
        self.bar.grid(row=3, column=0, sticky="ew", padx=24, pady=(16, 4))
        self.bar.set(0)
        self.detail = ctk.CTkLabel(self, text="", font=T.font(10), text_color=T.SUB, height=14)
        self.detail.grid(row=4, column=0)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=5, column=0, pady=(14, 18))
        self.later = ctk.CTkButton(foot, text="あとで", width=100, fg_color="transparent", border_width=1,
                                   border_color=T.BORDER, command=self._skip)
        self.later.pack(side="left", padx=6)
        self.go = ctk.CTkButton(foot, text="準備を開始", width=140, fg_color=T.ACCENT,
                                hover_color=T.ACCENT_HOVER, command=self._start)
        self.go.pack(side="left", padx=6)

    def _ui(self, f):
        self.after(0, f)

    def _mark(self, i, state, note=""):
        mark, label = self.rows[i]
        self._ui(lambda: (mark.configure(text=ICON[state], text_color=COLOR[state]),
                          label.configure(text=note, text_color=COLOR[state] if state == "ng" else T.SUB)))

    def _progress(self, ratio, text):
        def f():
            if ratio is None:
                if self.bar.cget("mode") != "indeterminate":
                    self.bar.configure(mode="indeterminate")
                    self.bar.start()
            else:
                if self.bar.cget("mode") != "determinate":
                    self.bar.stop()
                    self.bar.configure(mode="determinate")
                self.bar.set(ratio)
            self.detail.configure(text=text)
        self._ui(f)

    def _start(self):
        self.go.configure(state="disabled", text="準備中…")
        self.later.configure(state="disabled")
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        ok = True
        for i, (_, step) in enumerate(runtime.STEPS):
            self._mark(i, "run", "処理中")
            try:
                self._mark(i, "ok", step(self._progress))
            except Exception as e:
                ok = False
                self._mark(i, "ng", "失敗")
                self._progress(0, f"エラー: {e}")
        self._progress(1 if ok else 0, "すべて準備できました" if ok else "失敗した項目は「もう一度」で再試行できます")
        if ok:
            config.save({"SETUP_DONE": True})
        self._ui(lambda: self._finish(ok))

    def _finish(self, ok):
        self.bar.stop()
        self.bar.configure(mode="determinate")
        self.later.configure(state="normal", text="閉じる" if ok else "あとで")
        self.go.configure(state="normal", text="Zealous を起動" if ok else "もう一度",
                          command=self._done if ok else self._start)

    def _done(self):
        self.completed = True
        self.destroy()

    def _skip(self):
        config.save({"SETUP_DONE": True})  # 次回から自動では出さない(設定画面から再実行可)
        self.completed = True
        self.destroy()


def run():
    """セットアップ画面を表示し、閉じたら True(起動してよい)を返す。"""
    w = SetupWizard()
    w.mainloop()
    return w.completed
