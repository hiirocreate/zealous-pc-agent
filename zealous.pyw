"""Zealous の起動口(ダブルクリック / Zealous.exe)。コンソール画面は出さない。
  (引数なし)    : 初回は部品のセットアップ画面 → 本体
  --setup       : セットアップ画面を表示してから本体
  --uninstall   : アンインストール時の後片付け(インストーラーから呼ばれる)
  --selftest F  : 部品がすべて読み込めるか確認し、結果をファイル F に書く(ビルド確認用)"""
import multiprocessing as mp
import os
import sys


def _here():
    return os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))


def uninstall():
    import shutil
    import tkinter.messagebox as mb

    import config
    import runtime
    runtime.kill_all(also=_here())
    if mb.askyesno("Zealous アンインストール",
                   "ダウンロードしたAI・音声の部品(数GB)と設定も削除しますか？\n"
                   "「いいえ」を選ぶと、再インストール時にそのまま使えます。"):
        for d in (runtime.DATA_DIR, config.APP_DIR):
            shutil.rmtree(d, ignore_errors=True)


def selftest(out):
    import importlib
    import traceback
    mods = ["app", "setup_wizard", "llm", "tools", "voice", "tts", "stopper", "runtime", "updater",
            "faster_whisper", "ctranslate2", "sounddevice", "keyboard", "pyautogui", "customtkinter"]
    errors = []
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception:
            errors.append(f"{m}: {traceback.format_exc(limit=1)}")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(errors) or "OK")
    sys.exit(1 if errors else 0)


def main():
    os.chdir(_here())
    sys.path.insert(0, os.getcwd())
    import config
    import runtime
    if "--selftest" in sys.argv:
        return selftest(sys.argv[sys.argv.index("--selftest") + 1])
    if "--uninstall" in sys.argv:
        return uninstall()
    if "--setup" in sys.argv or (not config.SETUP_DONE and not runtime.ready()):
        import setup_wizard
        if not setup_wizard.run():
            return
    from app import App
    App().mainloop()


if __name__ == "__main__":
    mp.freeze_support()
    main()
