"""待機中の聞き取りを軽くする2つの小さなAI(どちらも onnxruntime で動き、CPUをほとんど使わない)。
- Silero VAD: 音が「人の声」かどうかを見分ける(物音・テレビの音楽などで、聞き取りAIを動かさない)
- openWakeWord: 合図の言葉だけを見つける(見つけるまで、声を文字にするAIは動かさない)
どちらも使えないとき(部品やモデルが無いなど)は None を返し、これまでの方法(音の大きさ・Whisper)で聞き取る。"""
import os
import threading

import numpy as np

import zlog

SR = 16000
OWW_URL = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/{}"
# 用意されている合図の言葉(英語)。日本語の合図の言葉は、自分で学習したモデル(.onnx)を指定する
OWW_BUILTIN = {"hey_jarvis": "hey_jarvis_v0.1.onnx", "alexa": "alexa_v0.1.onnx", "hey_mycroft": "hey_mycroft_v0.1.onnx"}


def _session(path):
    import onnxruntime
    opts = onnxruntime.SessionOptions()
    opts.inter_op_num_threads = opts.intra_op_num_threads = 1  # 1つのCPUだけで十分
    opts.log_severity_level = 4
    return onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"], sess_options=opts)


# ---------------- Silero VAD ----------------
class SileroVAD:
    """16kHz の音から「人の声らしさ」(0〜1)を返す。モデルは faster-whisper に同梱のものを使う(追加のダウンロード不要)。"""

    def __init__(self):
        import faster_whisper
        folder = os.path.join(os.path.dirname(faster_whisper.__file__), "assets")
        path = next(os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.startswith("silero_vad"))
        self.s = _session(path)

    def prob(self, audio16k):
        x = np.asarray(audio16k, np.float32)
        n = 512
        if len(x) < n:
            x = np.pad(x, (0, n - len(x)))
        x = x[: len(x) // n * n].reshape(-1, n)
        ctx = np.concatenate([np.zeros((1, 64), np.float32), x[:-1, -64:]], 0)  # 前の区切りの終わりを手がかりに
        batch = np.concatenate([ctx, x], 1)
        h = np.zeros((1, 1, 128), np.float32)
        c = np.zeros((1, 1, 128), np.float32)
        out = self.s.run(None, {"input": batch, "h": h, "c": c})[0]
        return float(np.max(out))


_vad = None
_vad_failed = False


def vad():
    """Silero VAD(使えなければ None)。"""
    global _vad, _vad_failed
    if _vad is None and not _vad_failed:
        try:
            _vad = SileroVAD()
        except Exception as e:
            _vad_failed = True
            zlog.note(f"声の判定AI(Silero VAD)を使えません: {e!r}")
    return _vad


# ---------------- openWakeWord ----------------
class WakeNet:
    """openWakeWord と同じ手順(音 → メルスペクトル → 特徴 → 判定)を、少しずつ届く音に対して行う。"""
    CHUNK = 1280  # 80ミリ秒ごとに判定する

    def __init__(self, folder, model_path):
        self.mel = _session(os.path.join(folder, "melspectrogram.onnx"))
        self.emb = _session(os.path.join(folder, "embedding_model.onnx"))
        self.ww = _session(model_path)
        self.ww_in = self.ww.get_inputs()[0].name
        self.frames = int(self.ww.get_inputs()[0].shape[1] or 16)
        self.raw = np.zeros(0, np.float32)
        self.pending = np.zeros(0, np.float32)
        self.spec = np.ones((76, 32), np.float32)
        self.feat = np.zeros((self.frames, 96), np.float32)
        self.cool = 0

    def push(self, audio16k):
        """届いた音(-1〜1)を足し、合図の言葉らしさの最大値(0〜1)を返す。"""
        self.pending = np.concatenate([self.pending, np.asarray(audio16k, np.float32) * 32767])
        best = 0.0
        while len(self.pending) >= self.CHUNK:
            chunk, self.pending = self.pending[:self.CHUNK], self.pending[self.CHUNK:]
            self.raw = np.concatenate([self.raw, chunk])[-(self.CHUNK + 480):]
            if len(self.raw) < self.CHUNK + 480:
                continue
            spec = np.squeeze(self.mel.run(None, {"input": self.raw[None, :]})[0]) / 10 + 2
            self.spec = np.vstack([self.spec, spec.reshape(-1, 32)])[-120:]
            emb = self.emb.run(None, {"input_1": self.spec[-76:][None, :, :, None]})[0].reshape(-1)
            self.feat = np.vstack([self.feat, emb[None, :]])[-self.frames:]
            score = float(self.ww.run(None, {self.ww_in: self.feat[None, :, :]})[0].reshape(-1)[0])
            if self.cool > 0:  # 一度見つけたら、しばらくは同じ声で何度も反応しない
                self.cool -= 1
                score = 0.0
            best = max(best, score)
        return best

    def fired(self):
        self.cool = 25  # 約2秒


def _download(url, dest):
    import urllib.request
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, dest)


_net, _net_key, _net_lock = None, None, threading.Lock()


def wakenet(model):
    """合図の言葉を見つけるAI。model は用意されている名前か、.onnx のファイル名。使えなければ None。
    初めて使うときに、必要なファイル(合わせて約4MB)をダウンロードする。"""
    global _net, _net_key
    import runtime
    with _net_lock:
        if _net_key == model:
            return _net
        _net_key, _net = model, None
        folder = os.path.join(runtime.DATA_DIR, "wakeword")
        try:
            names = ["melspectrogram.onnx", "embedding_model.onnx"]
            if model in OWW_BUILTIN:
                names.append(OWW_BUILTIN[model])
                path = os.path.join(folder, OWW_BUILTIN[model])
            else:
                path = model
                if not os.path.exists(path):
                    raise FileNotFoundError(path)
            for n in names:
                if not os.path.exists(os.path.join(folder, n)):
                    _download(OWW_URL.format(n), os.path.join(folder, n))
            _net = WakeNet(folder, path)
        except Exception as e:
            zlog.note(f"合図の言葉のAI(openWakeWord)を使えません: {e!r}")
        return _net
