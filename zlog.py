"""動きの記録。落ちたときに「直前に何をしていたか」を後から調べられるようにする。
- trace.log: 直前の動き(新しいものほど下。大きくなったら古い分を捨てる)
- error.log: エラーの内容"""
import os
import threading
import time

import config

_lock = threading.Lock()


def _write(name, text, limit):
    try:
        os.makedirs(config.APP_DIR, exist_ok=True)
        path = os.path.join(config.APP_DIR, name)
        with _lock:
            if os.path.exists(path) and os.path.getsize(path) > limit:
                os.replace(path, path + ".old")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{os.getpid()}] {text}\n")
                f.flush()
    except OSError:
        pass


def note(text):
    _write("trace.log", text, 300_000)


def error(text):
    _write("error.log", text, 1_000_000)
