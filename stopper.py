"""緊急停止のグローバルショートカット(Ctrl+Shift+E+S)。"""
import threading
import time

import config


def register(callback):
    import keyboard
    lock = threading.Lock()
    last = [0.0]

    def fire():
        with lock:
            if time.monotonic() - last[0] < 1.0:  # 連続発火を抑止
                return
            last[0] = time.monotonic()
        threading.Thread(target=callback, daemon=True).start()

    keyboard.add_hotkey("+".join(config.EMERGENCY_KEYS), fire, suppress=False)

    # 予備: キーを押すたびに全キーの同時押しを確認(押す順番に依存しない)
    def on_press(_):
        if all(keyboard.is_pressed(k) for k in config.EMERGENCY_KEYS):
            fire()
    keyboard.on_press(on_press)
