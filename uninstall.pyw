"""アンインストール(ダブルクリック、または Windows の「設定 > アプリ」から起動)。
ショートカット・自動起動・アプリ一覧の登録・設定を削除する。標準ライブラリのみで動く。"""
import os
import shutil
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


def _requirements():
    with open(os.path.join(HERE, "requirements.txt"), encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


class Uninstall(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Zealous アンインストール")
        self.geometry("480x400")
        if os.name == "nt":
            self.iconbitmap(shortcut.ICON)
        self.opts = {
            "settings": (tk.BooleanVar(value=True), "設定を削除する"),
            "model": (tk.BooleanVar(value=False), f"AIモデル ({config.OLLAMA_MODEL}) を削除する"),
            "packages": (tk.BooleanVar(value=False), "インストールした部品 (Pythonライブラリ) を削除する"),
            "folder": (tk.BooleanVar(value=False), "Zealous のフォルダごと削除する"),
        }
        tk.Label(self, text="Zealous のアンインストール", font=("", 13, "bold")).pack(pady=(10, 2))
        tk.Label(self, text="ショートカット・自動起動・アプリ一覧の登録を削除します。\n"
                            "先に Zealous を終了しておいてください。").pack()
        for var, label in self.opts.values():
            tk.Checkbutton(self, text=label, variable=var).pack(anchor="w", padx=12)
        self.log = scrolledtext.ScrolledText(self, height=9, state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=6)
        self.btn = tk.Button(self, text="アンインストール", width=18, command=self.start)
        self.btn.pack(pady=(0, 10))

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

    def _step(self, label, func):
        try:
            func()
            self.write(f"✓ {label}")
        except Exception as e:
            self.write(f"✗ {label}: {e}")

    def _run(self):
        on = {k: v.get() for k, (v, _) in self.opts.items()}
        if os.name == "nt":
            self._step("ショートカットを削除", lambda: [shortcut.remove(d) for d in
                                                (config.DESKTOP, shortcut.START_MENU_DIR, shortcut.STARTUP_DIR)])
            self._step("アプリ一覧から登録を解除", shortcut.unregister_app)
        if on["model"]:
            self._step("AIモデルを削除", services.delete_model)
        if on["packages"]:
            def pip_uninstall():
                python = os.path.join(os.path.dirname(sys.executable), "python.exe")
                subprocess.run([python if os.path.exists(python) else sys.executable, "-m", "pip", "uninstall",
                                "-y", *_requirements()], capture_output=True, creationflags=_NO_WINDOW, check=True)
            self._step("部品を削除", pip_uninstall)
        if on["settings"]:
            self._step("設定を削除", lambda: shutil.rmtree(config.APP_DIR, ignore_errors=True))
        if on["folder"]:
            # 実行中のこの画面を閉じた後に、見えないところでフォルダを消す
            q = HERE.replace("'", "''")
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                              f"Start-Sleep 2; Remove-Item -LiteralPath '{q}' -Recurse -Force"],
                             creationflags=_NO_WINDOW, cwd=os.path.dirname(HERE))
            self.write("✓ この画面を閉じるとフォルダを削除します")
        self.write("アンインストールが完了しました。")
        self.after(0, lambda: self.btn.configure(text="閉じる", state="normal", command=self.destroy))


if __name__ == "__main__":
    Uninstall().mainloop()
