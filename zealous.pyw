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
    mods = ["app", "setup_wizard", "llm", "tools", "voice", "tts", "stopper", "runtime", "updater", "gallery", "websearch", "apps", "models", "voicevox", "voice_picker", "ime", "winutil", "single_instance", "threads",
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


def _crash_log(folder):
    """強制終了したときの記録を crash.log に残す(原因を調べるため)。"""
    import faulthandler
    try:
        os.makedirs(folder, exist_ok=True)
        f = open(os.path.join(folder, "crash.log"), "a", encoding="utf-8")
        faulthandler.enable(f, all_threads=True)
        _crash_log.file = f  # 閉じられないように持っておく
    except OSError:
        pass


def main():
    # 音声認識などの部品が同じ計算ライブラリ(OpenMP)を別々に持っていても、強制終了しないようにする
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.chdir(_here())
    sys.path.insert(0, os.getcwd())
    import config
    import runtime
    if "--selftest" in sys.argv:
        return selftest(sys.argv[sys.argv.index("--selftest") + 1])
    if "--uninstall" in sys.argv:
        return uninstall()
    if "--smoketest" in sys.argv:  # ビルド確認用: 実際に画面を動かして試す(smoketest.py)
        _crash_log(config.APP_DIR)
        import smoketest
        return smoketest.run(sys.argv[sys.argv.index("--smoketest") + 1])
    import single_instance
    lock = single_instance.acquire()
    if lock is None and ("--setup" in sys.argv or "--restart" in sys.argv):  # 元の Zealous が閉じるのを少し待つ
        import time
        for _ in range(40):
            time.sleep(0.25)
            lock = single_instance.acquire()
            if lock:
                break
    if lock is None:  # すでに起動中: 新しく出さずに、今あるウィジェットを表に出す
        single_instance.notify_running()
        return
    if "--setup" in sys.argv or (not config.SETUP_DONE and not runtime.ready()):
        import setup_wizard
        if not setup_wizard.run():
            return
    _crash_log(config.APP_DIR)
    import zlog
    zlog.note(f"起動 v{__import__('version').VERSION}")
    from app import App
    app = App()
    single_instance.serve(lock, app.bring_to_front)
    app.mainloop()
    # 画面を閉じた後に裏の処理(マイク・キー監視など)が残ると、ファイルが使用中のままになり
    # アップデートのインストールが失敗するので、確実にプロセスを終える
    os._exit(0)


if __name__ == "__main__":
    mp.freeze_support()
    main()
