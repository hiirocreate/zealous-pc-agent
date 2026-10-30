"""VOICEVOX による音声合成。返事を短い区切りごとに「合成」と「再生」を並行して行い、
返事が書かれ始めてすぐに話し始める(UIはブロックしない)。
- 最初の区切りは短く(読点や数文字で)切って、とにかく早く話し始める
- 合成は2つ同時に進め、再生している間に次の区切りを用意しておく(切れ目なく話す)"""
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
_SENTENCE = re.compile(r"[。！？!?\n]")
_COMMA = re.compile(r"[、,]")
# 助詞の後で、次が漢字・カタカナ・英数字になるところ(言葉の途中では切らない)
_PARTICLE = re.compile(r"(?<=[\u4e00-\u9fff\u30a0-\u30ffA-Za-z0-9])(?:は|が|を|に|で|も|と|へ|から|まで)(?=[\u4e00-\u9fff\u30a0-\u30ffA-Za-z0-9「])")
FIRST_MIN, NEXT_COMMA, FORCE = 4, 24, 60  # 最初の区切りの最小文字数 / 読点で切る長さ / 強制的に切る長さ


def persona_voice():
    """AIの話し方に合わせた、声の速さ(倍率)と高さ(足す値)。"""
    p = getattr(config, "PERSONA", "") or ""
    if any(w in p for w in ("元気", "明るく", "楽しそう", "ハイテンション", "テンション高")):
        return 1.08, 0.03
    if any(w in p for w in ("落ち着", "ゆっくり", "執事", "穏やか", "おだやか", "低い声", "渋")):
        return 0.92, -0.02
    return 1.0, 0.0


def cut_point(buf, first):
    """届いた途中の文から、読み上げに回せる位置を返す(まだなら None)。
    最初の区切りは短めに切って早く話し始め、2つ目からは自然な文の切れ目で切る。"""
    m = _SENTENCE.search(buf)
    if m:
        return m.end()
    if first:  # 最初は読点でも切って、早く話し始める
        m = _COMMA.search(buf)
        while m and m.end() < FIRST_MIN:
            m = _COMMA.search(buf, m.end())
        if m:
            return m.end()
        if len(buf) >= 10:  # 読点が来ないときは、助詞の後(「〜は」「〜を」など)の切れ目で早めに話し始める
            m = None
            for m in _PARTICLE.finditer(buf, 4):
                pass
            if m:
                return m.end()
    if len(buf) >= NEXT_COMMA:
        commas = list(_COMMA.finditer(buf))
        if commas:
            return commas[-1].end()
    return len(buf) if len(buf) >= FORCE else None


class Speaker:
    def __init__(self, on_error=None):
        from concurrent.futures import ThreadPoolExecutor
        self._texts = queue.Queue()   # 合成待ちの文
        self._audio = queue.Queue()   # 再生待ちの音声(合成中のものは「後で受け取る約束」)
        self._pool = ThreadPoolExecutor(2)  # 2つ同時に合成する
        self._gen = 0                 # stop() のたびに増え、古い文・音声を捨てる目印
        self._on_error = on_error
        self._buf = ""
        self._first = True            # この返事でまだ何も話していないか
        self._last_error = -1e9
        self._playing = False
        self._inflight = 0            # 合成中の数
        self._quiet_since = 0.0
        self.text = ""                # いま読み上げている文(話の調子を見るため)
        self._env, self._t0 = None, 0.0  # いま鳴らしている音の大きさの変化(20ミリ秒ごと)
        threading.Thread(target=self._synth_loop, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()

    # ---------------- 外から使う ----------------
    def say(self, text):
        """まとまった文章を読み上げる(文ごとに区切って順に)。"""
        for sentence in split_sentences(text):
            self._push(sentence)

    def feed(self, piece):
        """返事の途中経過(少しずつ届く文字)を受け取り、区切りができたところから読み上げる。"""
        self._buf += piece
        while True:
            at = cut_point(self._buf, self._first)
            if at is None:
                break
            chunk, self._buf = self._buf[:at], self._buf[at:]
            if re.search(r"\w", chunk):
                self._first = False
            self._push(chunk)

    def flush(self):
        """途中経過の残り(句点で終わっていない最後の部分)を読み上げる。次の返事は最初から。"""
        rest, self._buf = self._buf, ""
        self._first = True
        self._push(rest)

    def play_wav(self, data):
        """WAVデータをそのまま鳴らす(声の試聴用)。読み上げ中なら止めてから。"""
        self.stop()
        self._audio.put((self._gen, _decode(data), ""))

    @property
    def busy(self):
        """読み上げ中(または読み上げ待ち)か。終わった直後の少しの間も含める(マイクが自分の声を拾わないように)。"""
        return (self._playing or self._inflight > 0 or not self._texts.empty() or not self._audio.empty()
                or time.monotonic() - self._quiet_since < 0.6)

    @property
    def level(self):
        """いま鳴らしている声の強さ(0〜1)。音声会話画面の球の動きに使う。"""
        env = self._env
        if not self._playing or env is None:
            return 0.0
        i = int((time.monotonic() - self._t0) / 0.02)
        return float(env[i]) if 0 <= i < len(env) else 0.0

    @property
    def _synthing(self):  # 以前の名前(互換用)
        return self._inflight > 0

    def stop(self):
        self._gen += 1
        self._buf = ""
        self._first = True
        import sounddevice as sd
        sd.stop()

    # ---------------- 内部 ----------------
    def _push(self, text):
        import reading
        text = reading.fix(text.strip())  # 同じ表記で読み方が変わる言葉を、文の流れから読み分ける
        if config.TTS_ENABLED and re.search(r"\w", text):
            self._texts.put((self._gen, text))

    def _synth(self, text):
        p = {"text": text, "speaker": config.VOICEVOX_SPEAKER}
        q = requests.post(f"{config.VOICEVOX_URL}/audio_query", params=p, timeout=10)
        q.raise_for_status()
        query = q.json()
        speed, pitch = persona_voice()
        query["speedScale"] = config.TTS_SPEED * speed
        query["pitchScale"] = query.get("pitchScale", 0.0) + pitch
        # 区切りの前後の無音を短くして、区切りをまたいでも途切れて聞こえないようにする
        query["outputSamplingRate"] = 24000
        query["prePhonemeLength"] = 0.05
        query["postPhonemeLength"] = 0.08
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
        """合成を順に依頼する(2つまで同時)。再生の順番は依頼した順のまま。"""
        while True:
            gen, text = self._texts.get()
            if gen != self._gen:
                continue
            self._inflight += 1
            future = self._pool.submit(self._synth, text)
            future.add_done_callback(lambda _: setattr(self, "_inflight", self._inflight - 1))
            self._audio.put((gen, future, text))

    def _play_loop(self):
        import sounddevice as sd
        while True:
            gen, item, text = self._audio.get()
            if gen != self._gen:
                continue
            if not isinstance(item, tuple):  # 合成中なら、できあがるのを待つ
                try:
                    item = item.result()
                except Exception as e:
                    self._report(e)
                    continue
                if gen != self._gen:
                    continue
            data, rate = item
            self.text, self._env = text, _envelope(data, rate)
            self._playing = True
            try:
                self._t0 = time.monotonic()
                sd.play(data, rate)
                sd.wait()
            finally:
                self._playing = False
                self._quiet_since = time.monotonic()


def _envelope(data, rate):
    """音の大きさを 20 ミリ秒ごとに 0〜1 で表す。"""
    step = max(1, int(rate * 0.02))
    mono = data if data.ndim == 1 else data.mean(axis=1)
    n = len(mono) // step
    if n == 0:
        return np.zeros(1, np.float32)
    rms = np.sqrt((mono[:n * step].astype(np.float32).reshape(n, step) ** 2).mean(axis=1))
    return np.clip(rms / (rms.max() + 1e-6), 0, 1) ** 0.8


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
