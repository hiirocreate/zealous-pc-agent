"""マイク録音(手動/常時待ち受け)と Faster-Whisper による文字起こし。
聞き取りの取りこぼしを減らすため、
- 押す直前の音(0.4秒)と、離した直後の音(0.3秒)も含めて文字にする
- マイクが 16kHz で開けない場合は、そのマイクの標準の速さで録って 16kHz に変換する
- 小さい声は音量をそろえてから文字にする
- 何も聞き取れなかったときは、そのことを知らせる"""
import collections
import os
import queue
import re
import threading

import numpy as np

import config

SR = config.SAMPLE_RATE            # 文字起こしに渡す速さ(16kHz)
PRE_SEC, POST_SEC = 0.4, 0.3       # 押す前・離した後に含める秒数
# 無音のときに Whisper が出しがちな決まり文句(実際には話していない)
_HALLUCINATIONS = re.compile(r"^(ご視聴ありがとうございました|ご視聴ありがとうございます|チャンネル登録|"
                             r"ありがとうございました|字幕|お疲れ様でした)[。.!！]*$")


def input_devices():
    """選べるマイクの名前の一覧(重複は除く)。"""
    try:
        import sounddevice as sd
        names = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
    except Exception:
        return []
    return list(dict.fromkeys(names))


def prompt_text():
    """聞き取りの手がかり(Whisper に「この言葉が出てきやすい」と伝える文)。長すぎると逆効果なので短く。"""
    words = [config.AI_NAME] + [w for w in getattr(config, "VOICE_WORDS", []) if w]
    text = "、".join(dict.fromkeys(words)) + "。"
    context = getattr(config, "VOICE_CONTEXT", "")
    if context:
        text += context[-120:]
    return text


def fix_words(text):
    """設定の置き換え(「まちがい=正しい」)を当てる。"""
    for rule in getattr(config, "VOICE_REPLACE", []):
        wrong, sep, right = str(rule).partition("=")
        if sep and wrong.strip():
            text = text.replace(wrong.strip(), right.strip())
    return text


def load_model(name, device, compute, light=False):
    from faster_whisper import WhisperModel
    import runtime
    # CPU の半分だけを使う(全部使うと、常時聞き取りの間 PC 全体が重くなる)。
    # 待機中の聞き取り(light)は、さらに4分の1まで(合図の言葉を見つけるだけなので十分速い)
    cores = os.cpu_count() or 4
    return WhisperModel(name, device=device, compute_type=compute, download_root=runtime.WHISPER_DIR,
                        cpu_threads=max(2, cores // 4 if light else cores // 2))


def _repetitive(text):
    """同じ言い回しを繰り返しているか(雑音を聞き取ろうとしたときによく出る、意味のない文)。"""
    import zlib
    if len(text) < 30:
        return False
    return len(text.encode()) / len(zlib.compress(text.encode())) > 2.4


class VoiceInput:
    def __init__(self, on_text, on_status):
        self._on_text = on_text        # (text, from_button) 認識結果と、マイクボタンで録った音声か
        self._on_status = on_status    # (msg) 状態・エラー表示
        self._jobs = queue.Queue()
        self._gen = 0
        self._stream = None
        self._rate = SR
        self._manual = False
        self._buf = []
        self._ring = collections.deque()  # 直前の音(押す前の分を含めるため)
        self._wake = False
        self._pre = collections.deque(maxlen=3)
        self._seg = None
        self._lock = threading.Lock()
        self.should_listen = lambda: True  # 待機中の聞き取りをしてよいか(考え中・読み上げ中は休む)
        self.command_mode = lambda: False  # 待機中に拾った声を、命令として正確に聞き取るべきか
        self.context = ""  # 直前の会話(聞き取りの手がかりにする)
        self.on_nothing = lambda: None  # ボタンで話したのに、文字にするものが無かったとき
        self.on_wake = lambda: None  # 合図の言葉のAI(openWakeWord)が合図の言葉を見つけたとき
        self._conversation = False  # 音声会話画面: 合図の言葉なしで、話すたびに聞き取る
        self._rest = False  # 待機中の聞き取りを休む(チャット画面を開いている間など。マイクを閉じてPCの負担を減らす)
        self.level = 0.0  # いまのマイクの音の大きさ(0〜1。音声会話画面の球の動きに使う)
        threading.Thread(target=self._transcriber, daemon=True).start()

    # ---- 操作 ----
    @property
    def conversation(self):
        return self._conversation

    @conversation.setter
    def conversation(self, on):
        self._conversation = on
        self._apply_stream()

    def rest(self, on):
        """待機中の聞き取り(合図の言葉)を休むか。休む間はマイクを閉じる(ボタンで話すときは、その場で開く)。"""
        if on != self._rest:
            self._rest = on
            self._apply_stream()

    def _apply_stream(self):
        """いま聞き取りが要るときだけマイクを開いておく(要らなければ閉じて、CPU と電力を使わない)。"""
        if self._manual or self._conversation or (self._wake and not self._rest):
            self._ensure_stream()
        else:
            self._close_stream()

    def _close_stream(self):
        stream, self._stream = self._stream, None
        self._seg = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def start_manual(self):
        if not self._ensure_stream():
            return
        self.preload()  # 話している間に、命令用の聞き取りAIを読み込んでおく(休んでいて外していた場合)
        with self._lock:
            self._buf, self._manual = list(self._ring), True  # 押す直前の音から始める

    def stop_manual(self):
        """離した直後の音も少しだけ録ってから文字起こしへ回す。"""
        if not self._manual:
            self.on_nothing()  # 録音が始まっていなかった(マイクを開けなかったなど)
            return
        threading.Timer(POST_SEC, self._finish_manual, args=(self._gen,)).start()

    def _finish_manual(self, gen):
        with self._lock:
            if not self._manual or gen != self._gen:
                return
            self._manual = False
            buf, self._buf = self._buf, []
        if buf:
            self._jobs.put((gen, self._to_16k(np.concatenate(buf)), True))
        else:
            self.on_nothing()
        self._apply_stream()  # 待機中の聞き取りを休んでいるなら、マイクを閉じる

    def set_wake(self, enabled):
        self._seg = None
        # マイクを開けなかったときは、合図の言葉での聞き取りを止める(休んでいる間は、開くのを後に回す)
        self._wake = enabled and (self._rest or self._ensure_stream())
        self._apply_stream()

    def reset_device(self):
        """マイクの設定が変わったときに開き直す。"""
        self._close_stream()
        self._apply_stream()

    def cancel(self):
        self._gen += 1
        with self._lock:
            self._manual, self._buf, self._seg = False, [], None
        while not self._jobs.empty():
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                break

    # ---- 録音 ----
    def _device(self):
        name = config.MIC_DEVICE
        if not name:
            return None
        import sounddevice as sd
        for i, d in enumerate(sd.query_devices()):
            if d["name"] == name and d["max_input_channels"] > 0:
                return i
        return None  # 見つからなければ既定のマイク

    def _ensure_stream(self):
        if self._stream:
            return True
        try:
            import sounddevice as sd
            device = self._device()
            try:
                rate = SR
                stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32", device=device,
                                        blocksize=rate // 10, callback=self._callback)
            except Exception:  # 16kHz に対応していないマイクは、標準の速さで録って後で変換
                rate = int(sd.query_devices(device, "input")["default_samplerate"])
                stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32", device=device,
                                        blocksize=rate // 10, callback=self._callback)
            self._rate = rate
            self._ring = collections.deque(maxlen=max(1, int(PRE_SEC * 10)))
            stream.start()
            self._stream = stream
            return True
        except Exception as e:
            self._stream = None
            self._on_status(f"マイクを開けませんでした（{e}）。設定の「声・音声」でマイクを選び直してください")
            return False

    def _to_16k(self, audio):
        if self._rate == SR or len(audio) == 0:
            return audio
        n = int(len(audio) * SR / self._rate)
        return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)

    def _callback(self, indata, frames, time_info, status):
        mono = indata[:, 0].copy()
        self._ring.append(mono)
        rms = float(np.sqrt(np.mean(mono ** 2)))
        self.level = max(min(1.0, rms / max(config.VAD_THRESHOLD * 6, 1e-4)), self.level * 0.85)
        with self._lock:
            if self._manual:
                self._buf.append(mono)
                return
        if (self._wake and not self._rest) or self._conversation:
            try:
                listen = self.should_listen()
            except Exception:
                listen = True
            if listen:
                self._vad(mono)
            else:
                self._seg = None

    def _gate(self):
        """合図の言葉のAI(openWakeWord)で待っているか。見つけるまでは、声を文字にするAIを動かさない。"""
        if getattr(config, "WAKE_ENGINE", "whisper") != "openwakeword" or self._conversation:
            return None
        try:
            if self.command_mode():  # 合図の後の会話: ふつうに聞き取る
                return None
        except Exception:
            pass
        import audiogate
        return audiogate.wakenet(getattr(config, "OWW_MODEL", "hey_jarvis"))

    def _is_voice(self, mono, rms):
        """人の声か。音の大きさで大まかに見て、Silero VAD(使えるとき)で声かどうかを確かめる。"""
        if rms <= config.VAD_THRESHOLD:
            return False
        if getattr(config, "VAD_ENGINE", "silero") != "silero":
            return True
        import audiogate
        model = audiogate.vad()
        return model is None or model.prob(self._to_16k(mono)) >= 0.5

    def _vad(self, mono):
        net = self._gate()
        if net is not None:  # 合図の言葉だけを、小さなAIで待つ(物音で聞き取りAIを動かさない)
            self._seg = None
            if net.push(self._to_16k(mono)) >= float(getattr(config, "OWW_THRESHOLD", 0.5)):
                net.fired()
                self.on_wake()
            return
        rms = float(np.sqrt(np.mean(mono ** 2)))
        # 話し始めは声かどうかを確かめる。話している途中は、音の大きさだけで切れ目を見る(軽く、言葉の間で切れない)
        loud = self._is_voice(mono, rms) if self._seg is None else rms > config.VAD_THRESHOLD
        if self._seg is None:
            self._pre.append(mono)
            if loud:
                self._seg, self._silence = list(self._pre), 0
            return
        self._seg.append(mono)
        self._silence = 0 if loud else self._silence + len(mono)
        total = sum(len(s) for s in self._seg)
        sr = self._rate
        # 音声会話画面では、話し終わりを早めに判定して、テンポよく返事をする
        silence = min(config.VAD_SILENCE_SEC, 0.7) if self.conversation else config.VAD_SILENCE_SEC
        if self._silence >= silence * sr or total >= config.VAD_MAX_SEC * sr:
            seg, self._seg = self._seg, None
            # 文字起こしが追いつかないときは捨てる(たまり続けると重くなり、最後は落ちてしまう)
            if (total - self._silence) >= config.VAD_MIN_SEC * sr and self._jobs.empty():
                self._jobs.put((self._gen, self._to_16k(np.concatenate(seg)), False))

    # ---- 文字起こし ----
    def _load(self, name):
        return load_model(name, config.WHISPER_DEVICE, config.WHISPER_COMPUTE)

    def _transcriber(self):
        # 文字起こしは別プロセスで行う(音声認識の部品が異常終了しても、本体は落ちない)
        from whisper_worker import WhisperWorker
        from wakeword import strip_wake_word
        worker = WhisperWorker(self._on_status)
        while True:
            gen, audio, from_button = self._jobs.get()
            if gen != self._gen:
                continue
            if audio is None:  # 命令用のモデルを前もって読み込む(初回はダウンロード)
                worker.transcribe(np.zeros(SR, np.float32), True, command=True)
                continue
            # 命令(ボタン・話すキー・合図の後の会話)は正確なモデルで、待機中は軽いモデルで文字にする
            command = from_button or self.command_mode()
            text = worker.transcribe(audio, from_button, command=command)
            if not command and text and strip_wake_word(text):
                # 「ウェイク、ゼラス、〜して」と続けて言った: 命令の部分を正確なモデルで聞き直す
                text = worker.transcribe(audio, from_button, command=True) or text
            if gen != self._gen:
                continue
            text = fix_words(text)
            if text:
                self._on_text(text, from_button)
            elif from_button:
                self.on_nothing()
                self._on_status("聞き取れませんでした。マイクに近づいて、もう一度話してください")

    def preload(self):
        """命令用のモデルを裏で準備しておく(最初の命令で待たされないように)。"""
        self._jobs.put((self._gen, None, True))

    @staticmethod
    def transcribe(model, audio, from_button):
        if len(audio) < SR * 0.3:
            return ""
        peak = float(np.max(np.abs(audio)))
        if peak < 0.003:  # ほぼ無音(マイクが拾っていない)
            return ""
        audio = audio * min(0.9 / peak, 20.0)  # 小さい声は音量をそろえる
        segs, _ = model.transcribe(
            # 待機中の聞き取りは軽く(合図の言葉を見つけるだけなので)、ボタンで話したときは正確に
            audio, language=config.LANGUAGE, beam_size=5 if from_button else 1, temperature=0.0,
            condition_on_previous_text=False,
            # 無音の切り落とし(vad_filter)は使わない。声の区切りはこちらで判定済みで、
            # 使うと別のAI部品(onnxruntime)が読み込まれ、Whisper の部品とぶつかって強制終了することがある
            vad_filter=False,
            initial_prompt=prompt_text(),  # AI名・ユーザー辞書・直前の会話を手がかりにする
        )
        # 声らしくない部分(雑音から作られた文)は捨てる
        text = "".join(s.text for s in segs
                       if getattr(s, "no_speech_prob", 0) < 0.6 and getattr(s, "avg_logprob", 0) > -1.0).strip()
        if _HALLUCINATIONS.match(text) or _repetitive(text):
            return ""
        if len(text) > 3 and text.strip("。、 ") in prompt_text():  # 手がかりの文をそのまま返しただけ
            return ""
        return text
