"""Kokoro(約8,200万パラメータの小さな読み上げAI)で、日本語を読み上げる。
VOICEVOX のような別のソフトを起動しないので、メモリが少なく、CPU だけでも速い。
初めて使うときに、声のモデル(約120MB)をダウンロードする。"""
import os
import threading

import numpy as np

import zlog

URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/{}"
FILES = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
VOICES = [("jf_alpha", "女性・はっきり（おすすめ）"), ("jf_gongitsune", "女性・やわらか"), ("jf_nezumi", "女性・かわいい"),
          ("jf_tebukuro", "女性・おちついた"), ("jm_kumo", "男性")]
RATE = 24000

_model = None
_g2p = None
_lock = threading.Lock()


def folder():
    import runtime
    return os.path.join(runtime.DATA_DIR, "kokoro")


def ready():
    return all(os.path.exists(os.path.join(folder(), f)) for f in FILES)


def prepare(progress=lambda text: None):
    """声のモデルを用意して読み込む(ダウンロード済みなら読み込むだけ)。"""
    global _model, _g2p
    with _lock:
        if _model is not None:
            return
        import urllib.request
        os.makedirs(folder(), exist_ok=True)
        for f in FILES:
            dest = os.path.join(folder(), f)
            if not os.path.exists(dest):
                progress("読み上げの声(Kokoro)をダウンロードしています…")
                urllib.request.urlretrieve(URL.format(f), dest + ".part")
                os.replace(dest + ".part", dest)
        from kokoro_onnx import Kokoro
        from misaki import ja
        _g2p = ja.JAG2P()
        _model = Kokoro(os.path.join(folder(), FILES[0]), os.path.join(folder(), FILES[1]))
        zlog.note("Kokoro の読み込み完了")


def synth(text, voice="jf_alpha", speed=1.0):
    """文 → (音 int16 の [n, 1], 24000)。"""
    prepare()
    phonemes = _g2p(text)
    phonemes = phonemes[0] if isinstance(phonemes, tuple) else phonemes
    with _lock:  # 同時に2つ合成しない(メモリとCPUを使いすぎないように)
        audio, rate = _model.create(phonemes, voice=voice, speed=max(0.5, min(2.0, speed)), lang="ja",
                                    is_phonemes=True)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    return pcm.reshape(-1, 1), rate


def release():
    """使わなくなったらメモリから外す。"""
    global _model, _g2p
    with _lock:
        _model = _g2p = None
