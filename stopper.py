"""どの画面からでも効くキー操作: 緊急停止(Ctrl+Shift+E+S)と、話すキー(押している間だけ聞き取る)。"""
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


KEY_NAMES = {"right ctrl": "右Ctrl", "right alt": "右Alt", "right shift": "右Shift", "f8": "F8", "f9": "F9",
             "f10": "F10", "scroll lock": "Scroll Lock", "pause": "Pause"}
_ptt_hooks = []


def register_ptt(key, on_down, on_up):
    """話すキーを登録し直す(key=None で解除)。キーを押し続けたときの連続入力は1回として扱う。"""
    import keyboard
    for h in _ptt_hooks:
        keyboard.unhook(h)
    _ptt_hooks.clear()
    if not key:
        return
    held = [False]

    def down(_):
        if not held[0]:
            held[0] = True
            on_down()

    def up(_):
        if held[0]:
            held[0] = False
            on_up()
    _ptt_hooks.extend([keyboard.on_press_key(key, down), keyboard.on_release_key(key, up)])
