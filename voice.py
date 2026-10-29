"""マイク録音(手動/常時待ち受け)と Faster-Whisper による文字起こし。"""
import collections
import queue
import threading

import numpy as np

import config

_BLOCK = config.SAMPLE_RATE // 10  # 0.1秒


class VoiceInput:
    def __init__(self, on_text, on_status):
        self._on_text = on_text        # (text, from_button) 認識結果と、マイクボタンで録った音声か
        self._on_status = on_status    # (msg) 状態・エラー表示
        self._jobs = queue.Queue()
        self._gen = 0
        self._stream = None
        self._manual = False
        self._buf = []
        self._wake = False
        self._pre = collections.deque(maxlen=3)
        self._seg = None
        threading.Thread(target=self._transcriber, daemon=True).start()

    # ---- 操作 ----
    def start_manual(self):
        if not self._ensure_stream():
            return
        self._buf, self._manual = [], True

    def stop_manual(self):
        if not self._manual:
            return
        self._manual = False
        if self._buf:
            self._jobs.put((self._gen, np.concatenate(self._buf), True))
        self._buf = []

    def set_wake(self, enabled):
        self._seg = None
        self._wake = enabled and self._ensure_stream()

    def cancel(self):
        self._gen += 1
        self._manual, self._buf, self._seg = False, [], None
        while not self._jobs.empty():
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                break

    # ---- 内部 ----
    def _ensure_stream(self):
        if self._stream:
            return True
        try:
            import sounddevice as sd
            self._stream = sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1, dtype="float32",
                                          blocksize=_BLOCK, callback=self._callback)
            self._stream.start()
            return True
        except Exception as e:
            self._stream = None
            self._on_status(f"マイクエラー: {e}")
            return False

    def _callback(self, indata, frames, time_info, status):
        mono = indata[:, 0].copy()
        if self._manual:
            self._buf.append(mono)
        elif self._wake:
            self._vad(mono)

    def _vad(self, mono):
        loud = float(np.sqrt(np.mean(mono ** 2))) > config.VAD_THRESHOLD
        if self._seg is None:
            self._pre.append(mono)
            if loud:
                self._seg, self._silence = list(self._pre), 0
            return
        self._seg.append(mono)
        self._silence = 0 if loud else self._silence + len(mono)
        total = sum(len(s) for s in self._seg)
        sr = config.SAMPLE_RATE
        if self._silence >= config.VAD_SILENCE_SEC * sr or total >= config.VAD_MAX_SEC * sr:
            seg, self._seg = self._seg, None
            if (total - self._silence) >= config.VAD_MIN_SEC * sr:
                self._jobs.put((self._gen, np.concatenate(seg), False))

    def _transcriber(self):
        try:
            from faster_whisper import WhisperModel
            import runtime
            model = WhisperModel(config.WHISPER_MODEL, device=config.WHISPER_DEVICE,
                                 compute_type=config.WHISPER_COMPUTE, download_root=runtime.WHISPER_DIR)
        except Exception as e:
            self._on_status(f"Whisper読み込みエラー: {e}")
            return
        while True:
            gen, audio, from_button = self._jobs.get()
            if gen != self._gen:
                continue
            try:
                segs, _ = model.transcribe(audio, language=config.LANGUAGE, beam_size=1,
                                           vad_filter=True, condition_on_previous_text=False)
                text = "".join(s.text for s in segs).strip()
            except Exception as e:
                self._on_status(f"音声認識エラー: {e}")
                continue
            if text and gen == self._gen:
                self._on_text(text, from_button)
