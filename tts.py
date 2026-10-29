"""VOICEVOX による音声合成。別スレッドで合成・再生し、UIをブロックしない。"""
import io
import queue
import threading
import wave

import numpy as np
import requests

import config


class Speaker:
    def __init__(self, on_error=None):
        self._q = queue.Queue()
        self._gen = 0
        self._on_error = on_error
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text):
        if config.TTS_ENABLED and text:
            self._q.put((self._gen, text))

    def stop(self):
        self._gen += 1
        import sounddevice as sd
        sd.stop()

    def _synth(self, text):
        p = {"text": text, "speaker": config.VOICEVOX_SPEAKER}
        q = requests.post(f"{config.VOICEVOX_URL}/audio_query", params=p, timeout=10)
        q.raise_for_status()
        w = requests.post(f"{config.VOICEVOX_URL}/synthesis", params={"speaker": config.VOICEVOX_SPEAKER},
                          json=q.json(), timeout=30)
        w.raise_for_status()
        with wave.open(io.BytesIO(w.content)) as f:
            data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
            return data.reshape(-1, f.getnchannels()), f.getframerate()

    def _run(self):
        import sounddevice as sd
        while True:
            gen, text = self._q.get()
            if gen != self._gen:
                continue
            try:
                data, rate = self._synth(text)
                if gen == self._gen:
                    sd.play(data, rate)
                    sd.wait()
            except Exception as e:
                if self._on_error:
                    self._on_error(f"音声合成エラー: {e}")
