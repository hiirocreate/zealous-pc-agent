"""AI推論とPC操作を別プロセスで実行する。緊急停止時はプロセスごと強制終了(Kill)する。"""
import multiprocessing as mp
import queue
import threading


def _worker_main(inq, outq):
    import llm
    import tools
    llm.on_delta = lambda piece: outq.put(("delta", piece))  # 返事は書けた分から画面へ送る
    llm.on_retract = lambda: outq.put(("retract", None))  # 書き始めた返事を取り消す
    import os
    if os.name == "nt":  # アプリの一覧を先に読んでおく(「〇〇を開いて」をすぐ判断できるように)
        import apps
        threading.Thread(target=lambda: apps.start_apps(), daemon=True).start()
    llm.on_summary = lambda tid, text, upto: outq.put(("summary", (tid, text, upto)))  # 長い会話を圧縮した
    while True:
        text, history, by_voice, extra = inq.get()
        try:
            if text == "__confirmed__":  # 確認で「はい」と言われた操作を実行する
                name, args = history
                outq.put(("reply", tools.run_tool(name, args, confirmed=True)))
                continue
            tools.REQUIRE_CONFIRM = by_voice
            outq.put(("reply", llm.ask(text, history, **(extra or {}))))
        except Exception as e:
            outq.put(("error", str(e)))


class AgentWorker:
    def __init__(self):
        self._ctx = mp.get_context("spawn")
        self._lock = threading.Lock()
        self.pending = 0
        self._start()

    def _start(self):
        # キューもプロセスごと作り直す(Kill時にキューが壊れる可能性があるため)
        self._inq, self._outq = self._ctx.Queue(), self._ctx.Queue()
        self._proc = self._ctx.Process(target=_worker_main, args=(self._inq, self._outq), daemon=True)
        self._proc.start()

    def submit(self, text, history=None, by_voice=False, extra=None):
        """history: そのスレッドの直前のやりとり [(発言, 返事)]。None なら作業プロセス側の記憶を使う。
        by_voice: 声で頼まれた(危険な操作は実行前に確認する)。"""
        with self._lock:
            self.pending += 1
            self._inq.put((text, history, by_voice, extra))

    def run_confirmed(self, name, args):
        """確認が取れた操作を実行する。"""
        with self._lock:
            self.pending += 1
            self._inq.put(("__confirmed__", (name, args), False, None))

    def poll(self):
        out = []
        with self._lock:
            while True:
                try:
                    out.append(self._outq.get_nowait())
                except (queue.Empty, OSError, EOFError):
                    break
            done = sum(1 for kind, _ in out if kind in ("reply", "error"))  # 途中経過(delta)は数えない
            self.pending = max(0, self.pending - done)
        return out

    def kill(self):
        with self._lock:
            self._proc.kill()
            self._proc.join(2)
            self.pending = 0
            self._start()

    restart = kill  # 設定変更時: 新しいプロセスが設定を読み直す

    def close(self):
        self._proc.kill()
        self._proc.join(2)
