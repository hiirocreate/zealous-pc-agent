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


KEY_NAMES = {"right ctrl": "右Ctrl", "right alt": "右Alt", "right shift": "右Shift", "space": "スペース",
             "f8": "F8", "f9": "F9", "f10": "F10", "scroll lock": "Scroll Lock", "pause": "Pause"}
# キーの呼び名の違い(環境によって keyboard が返す名前が違う)
_ALIASES = {"right ctrl": {"right ctrl", "ctrl right", "right control", "rctrl"},
            "right alt": {"right alt", "alt right", "alt gr", "altgr", "ralt"},
            "right shift": {"right shift", "shift right", "rshift"},
            "space": {"space", "spacebar", " "}}
HOLD_SEC = 0.25    # スペースキーはこの時間以上押し続けたら「話す」、短く押したら普通のスペース
_remove = []       # 登録を解除する関数


def _matches(event, key):
    name = (event.name or "").lower()
    return name in _ALIASES.get(key, {key})


def register_ptt(key, on_down, on_up):
    """話すキーを登録し直す(key=None で解除)。押し続けたときの連続入力は1回として扱う。
    スペースキーは、長押しで話す / 短く押すと普通のスペースを入力する。"""
    import keyboard
    for remove in _remove:
        try:
            remove()
        except Exception:
            pass
    _remove.clear()
    if not key:
        return
    # injected: 自分で入力し直したスペース(押す・離すの2回)を、止めずに通すための残り回数
    state = {"down": False, "talking": False, "timer": None, "injected": 0}
    lock = threading.Lock()

    def start_talking():
        if state["down"] and not state["talking"]:
            state["talking"] = True
            on_down()

    def handle(event):
        if not _matches(event, key):
            return True  # 関係ないキーはそのまま通す
        with lock:
            if state["injected"] > 0:  # 自分で入力し直したスペースは通す
                state["injected"] -= 1
                return True
        if event.event_type == keyboard.KEY_DOWN:
            if not state["down"]:  # 押し続けによる連続入力は無視
                state["down"] = True
                if key == "space":
                    state["timer"] = threading.Timer(HOLD_SEC, start_talking)
                    state["timer"].start()
                else:
                    start_talking()
        else:
            state["down"] = False
            if state["timer"]:
                state["timer"].cancel()
                state["timer"] = None
            if state["talking"]:
                state["talking"] = False
                on_up()
            elif key == "space":  # 短く押しただけ: 普通のスペースとして入力し直す
                with lock:
                    state["injected"] += 2
                threading.Thread(target=keyboard.send, args=("space",), daemon=True).start()
        return key != "space"  # スペースキーはいったん止め、上で入力し直す

    hook = keyboard.hook(handle, suppress=(key == "space"))
    _remove.append(lambda: keyboard.unhook(hook))
