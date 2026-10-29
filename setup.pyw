"""初回セットアップ(ダブルクリックで起動)。コマンドプロンプトを使わずに
部品のインストール・AIモデルの取得・ショートカット作成を行う。標準ライブラリのみで動く。"""
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext

import config
import services
import shortcut

HERE = os.path.dirname(os.path.abspath(__file__))
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Setup(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Zealous セットアップ")
        self.geometry("520x420")
        self.desktop = tk.BooleanVar(value=True)
        self.autostart = tk.BooleanVar(value=config.AUTOSTART)
        tk.Label(self, text="Zealous のセットアップ", font=("", 13, "bold")).pack(pady=(10, 2))
        tk.Label(self, text="事前に Ollama と VOICEVOX をインストールして起動しておいてください").pack()
        tk.Checkbutton(self, text="デスクトップにショートカットを作る", variable=self.desktop).pack(anchor="w", padx=12)
        tk.Checkbutton(self, text="PC起動時に自動で起動する", variable=self.autostart).pack(anchor="w", padx=12)
        self.log = scrolledtext.ScrolledText(self, height=14, state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=6)
        row = tk.Frame(self)
        row.pack(pady=(0, 10))
        self.btn = tk.Button(row, text="セットアップ開始", width=16, command=self.start)
        self.btn.pack(side="left", padx=4)
        self.run_btn = tk.Button(row, text="Zealous を起動", width=16, state="disabled", command=self.launch)
        self.run_btn.pack(side="left", padx=4)

    def write(self, text):
        def f():
            self.log.configure(state="normal")
            self.log.insert("end", text + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(0, f)

    def start(self):
        self.btn.configure(state="disabled")
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        ok = True
        try:
            self.write("① 部品をインストール中…(数分かかります)")
            python = os.path.join(os.path.dirname(sys.executable), "python.exe")
            p = subprocess.Popen([python if os.path.exists(python) else sys.executable, "-m", "pip", "install",
                                  "-r", os.path.join(HERE, "requirements.txt")],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 creationflags=_NO_WINDOW)
            for line in p.stdout:
                if line.startswith(("Collecting", "Successfully", "ERROR")):
                    self.write("   " + line.strip())
            if p.wait() != 0:
                raise RuntimeError("部品のインストールに失敗しました")

            self.write("② AIモデルを確認中…")
            running, has, msg = services.check_ollama()
            self.write("   " + msg)
            if running and not has:
                last = [""]

                def prog(s):
                    if s.split(" ")[0] != last[0]:  # 同じ段階の進捗は間引く
                        last[0] = s.split(" ")[0]
                        self.write("   " + s)
                services.pull_model(prog)
            elif not running:
                ok = False
                self.write("   → Ollama を起動後、Zealous の⚙設定画面から「モデル取得」を押してください")

            self.write("③ VOICEVOX を確認中…")
            self.write("   " + services.check_voicevox()[1] + "(未起動でも読み上げ以外は動きます)")

            self.write("④ ショートカットを作成中…")
            if self.desktop.get():
                shortcut.create(config.DESKTOP)
            shortcut.set_autostart(self.autostart.get())
            config.save({"AUTOSTART": self.autostart.get()})
            self.write("完了しました。" if ok else "一部未完了ですが起動できます。")
            self.after(0, lambda: self.run_btn.configure(state="normal"))
        except Exception as e:
            self.write(f"エラー: {e}")
            self.after(0, lambda: self.btn.configure(state="normal"))

    def launch(self):
        subprocess.Popen([shortcut.pythonw(), shortcut.LAUNCHER], cwd=HERE)
        self.destroy()


if __name__ == "__main__":
    Setup().mainloop()
