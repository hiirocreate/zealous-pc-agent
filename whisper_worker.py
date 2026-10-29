"""音声認識(Whisper)を別プロセスで実行する。
音声認識の部品が内部で異常終了しても、Zealous 本体は落ちずに、この作業プロセスだけを起動し直す。"""
import multiprocessing as mp
import queue
import threading

import zlog


def _worker_main(inq, outq):
    import os
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    import config
    from voice import VoiceInput, load_model
    model, loaded = None, None
    parent = mp.parent_process()
    while True:
        try:
            job_id, audio, from_button, settings = inq.get(timeout=2)
        except queue.Empty:
            if parent is not None and not parent.is_alive():
                os._exit(0)  # 本体が終わったら、この作業プロセスも終える(残るとアップデートの邪魔になる)
            continue
        try:
            for k, v in settings.items():  # 本体の今の設定に合わせる
                setattr(config, k, v)
            want = (config.WHISPER_MODEL, config.WHISPER_DEVICE, config.WHISPER_COMPUTE)
            if loaded != want:
                model, loaded = None, None
                model, loaded = load_model(*want), want
            outq.put((job_id, VoiceInput.transcribe(model, audio, from_button), None))
        except Exception as e:
            outq.put((job_id, None, str(e)))


class WhisperWorker:
    SETTINGS = ("WHISPER_MODEL", "WHISPER_DEVICE", "WHISPER_COMPUTE", "LANGUAGE", "AI_NAME")

    def __init__(self, on_status):
        self._ctx = mp.get_context("spawn")
        self._on_status = on_status
        self._lock = threading.Lock()
        self._proc = None
        self._next = 0

    def _ensure(self):
        if self._proc is None or not self._proc.is_alive():
            self._inq, self._outq = self._ctx.Queue(), self._ctx.Queue()
            self._proc = self._ctx.Process(target=_worker_main, args=(self._inq, self._outq), daemon=True)
            self._proc.start()

    def transcribe(self, audio, from_button, timeout=300):
        """文字にした結果を返す。作業プロセスが落ちたら起動し直し、"" を返す。"""
        import config
        with self._lock:
            self._ensure()
            self._next += 1
            job_id = self._next
            self._inq.put((job_id, audio, from_button, {k: getattr(config, k) for k in self.SETTINGS}))
            zlog.note(f"音声認識 開始 #{job_id} {len(audio) / 16000:.1f}秒 {'ボタン' if from_button else '待機中'}")
            waited = 0.0
            while True:
                try:
                    got, text, error = self._outq.get(timeout=0.5)
                except queue.Empty:
                    waited += 0.5
                    if not self._proc.is_alive():
                        code = (self._proc.exitcode or 0) & 0xFFFFFFFF
                        zlog.note(f"音声認識の作業プロセスが止まりました(終了コード {code:#x})")
                        zlog.error(f"音声認識の作業プロセスが異常終了しました: 終了コード {code:#x}")
                        self._on_status("音声認識の部品が止まったため、起動し直しました")
                        self._proc = None
                        return ""
                    if waited >= timeout:
                        zlog.note(f"音声認識 時間切れ #{job_id}")
                        self._proc.kill()
                        self._proc = None
                        return ""
                    continue
                if got != job_id:
                    continue  # 前に時間切れになった分の答え
                zlog.note(f"音声認識 終了 #{job_id} {'エラー: ' + error if error else repr(text)[:60]}")
                if error:
                    self._on_status(f"音声認識でエラーが起きました: {error}")
                    return ""
                return text

    def close(self):
        if self._proc is not None and self._proc.is_alive():
            self._proc.kill()
