"""VOICEVOX による音声合成。文ごとに「合成」と「再生」を別スレッドで並行して行い、
返事の最初の一文ができた時点で話し始める(UIはブロックしない)。"""
import io
import queue
import re
import threading
import time
import wave

import numpy as np
import requests

import config

# 文の区切り(ここまで来たら合成を始める)
_END = re.compile(r"[。！？!?\n]|[、,](?=.{12,})")


class Speaker:
    def __init__(self, on_error=None):
        self._texts = queue.Queue()   # 合成待ちの文
        self._audio = queue.Queue()   # 再生待ちの音声
        self._gen = 0                 # stop() のたびに増え、古い文・音声を捨てる目印
        self._on_error = on_error
        self._buf = ""
        self._last_error = -1e9
        threading.Thread(target=self._synth_loop, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()

    # ---------------- 外から使う ----------------
    def say(self, text):
        """まとまった文章を読み上げる(文ごとに区切って順に)。"""
        for sentence in split_sentences(text):
            self._push(sentence)

    def feed(self, piece):
        """返事の途中経過(少しずつ届く文字)を受け取り、一文になったものから読み上げる。"""
        self._buf += piece
        while True:
            m = _END.search(self._buf)
            if not m:
                break
            self._push(self._buf[:m.end()])
            self._buf = self._buf[m.end():]

    def flush(self):
        """途中経過の残り(句点で終わっていない最後の部分)を読み上げる。"""
        rest, self._buf = self._buf, ""
        self._push(rest)

    def play_wav(self, data):
        """WAVデータをそのまま鳴らす(声の試聴用)。読み上げ中なら止めてから。"""
        self.stop()
        self._audio.put((self._gen, _decode(data)))

    def stop(self):
        self._gen += 1
        self._buf = ""
        import sounddevice as sd
        sd.stop()

    # ---------------- 内部 ----------------
    def _push(self, text):
        text = text.strip()
        if config.TTS_ENABLED and re.search(r"\w", text):
            self._texts.put((self._gen, text))

    def _synth(self, text):
        p = {"text": text, "speaker": config.VOICEVOX_SPEAKER}
        q = requests.post(f"{config.VOICEVOX_URL}/audio_query", params=p, timeout=10)
        q.raise_for_status()
        query = q.json()
        query["speedScale"] = config.TTS_SPEED
        w = requests.post(f"{config.VOICEVOX_URL}/synthesis", params={"speaker": config.VOICEVOX_SPEAKER},
                          json=query, timeout=30)
        w.raise_for_status()
        return _decode(w.content)

    def _report(self, error):
        """読み上げの失敗は短く、1分に1回だけ知らせる(文ごとに何度も出さない)。"""
        now = time.monotonic()
        if self._on_error and now - self._last_error > 60:
            self._last_error = now
            reason = "接続できません" if isinstance(error, requests.ConnectionError) else str(error)[:80]
            self._on_error(f"読み上げできませんでした（VOICEVOX: {reason}）")

    def _synth_loop(self):
        while True:
            gen, text = self._texts.get()
            if gen != self._gen:
                continue
            try:
                audio = self._synth(text)
            except Exception as e:
                self._report(e)
                continue
            if gen == self._gen:
                self._audio.put((gen, audio))

    def _play_loop(self):
        import sounddevice as sd
        while True:
            gen, (data, rate) = self._audio.get()
            if gen != self._gen:
                continue
            sd.play(data, rate)
            sd.wait()


def _decode(data):
    with wave.open(io.BytesIO(data)) as f:
        pcm = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
        return pcm.reshape(-1, f.getnchannels()), f.getframerate()


def split_sentences(text):
    """文章を読み上げ用の文に分ける。"""
    out, buf = [], text
    while True:
        m = _END.search(buf)
        if not m:
            break
        out.append(buf[:m.end()])
        buf = buf[m.end():]
    out.append(buf)
    return [s for s in (x.strip() for x in out) if s]
