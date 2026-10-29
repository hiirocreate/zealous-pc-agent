"""AI推論とPC操作を別プロセスで実行する。緊急停止時はプロセスごと強制終了(Kill)する。"""
import multiprocessing as mp
import queue
import threading


def _worker_main(inq, outq):
    import llm
    llm.on_delta = lambda piece: outq.put(("delta", piece))  # 返事は書けた分から画面へ送る
    while True:
        text, history = inq.get()
        try:
            outq.put(("reply", llm.ask(text, history)))
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

    def submit(self, text, history=None):
        """history: そのスレッドの直前のやりとり [(発言, 返事)]。None なら作業プロセス側の記憶を使う。"""
        with self._lock:
            self.pending += 1
            self._inq.put((text, history))

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
