"""マイクテスト: 数秒録音して、音の大きさ・雑音・聞き取れた言葉を確かめ、録音した声を再生する。"""
import numpy as np

import config

SR = 16000


def device_index(name):
    if not name:
        return None
    import sounddevice as sd
    for i, d in enumerate(sd.query_devices()):
        if d["name"] == name and d["max_input_channels"] > 0:
            return i
    return None


def record(device_name="", seconds=5.0, on_level=None, stop=None):
    """録音して 16kHz・1チャンネルの音を返す。on_level(0〜1) に、いまの音の大きさを伝える。"""
    import sounddevice as sd
    dev = device_index(device_name)
    rate = int(sd.query_devices(dev if dev is not None else sd.default.device[0], "input")["default_samplerate"])
    chunks = []

    def callback(indata, frames, time_info, status):
        mono = indata.mean(axis=1) if indata.ndim > 1 else indata
        chunks.append(mono.copy())
        if on_level:
            on_level(min(1.0, float(np.sqrt(np.mean(mono ** 2))) * 8))
    with sd.InputStream(device=dev, channels=1, samplerate=rate, dtype="float32", callback=callback):
        waited = 0.0
        while waited < seconds and not (stop and stop()):
            sd.sleep(100)
            waited += 0.1
    audio = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
    if rate != SR and len(audio):  # 文字起こしに合わせて 16kHz にする
        n = int(len(audio) * SR / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio


def analyze(audio):
    """音の大きさの診断。{"peak", "noise", "voice", "advice"(直し方の一言), "threshold"(おすすめの感度)}"""
    if len(audio) < SR // 2:
        return {"peak": 0.0, "noise": 0.0, "voice": 0.0, "advice": "録音できませんでした。マイクを確かめてください",
                "threshold": None}
    frame = SR // 20  # 0.05秒ずつの音の大きさ
    rms = np.sqrt(np.mean(audio[:len(audio) // frame * frame].reshape(-1, frame) ** 2, axis=1))
    peak = float(np.max(np.abs(audio)))
    noise, voice = float(np.percentile(rms, 15)), float(np.percentile(rms, 92))
    threshold = round(min(0.06, max(0.002, noise * 2.5, (noise + voice) / 4)), 3)
    if peak < 0.01:
        advice = "ほとんど音を拾っていません。マイクがミュートになっていないか、選んでいるマイクが正しいか確かめてください"
    elif peak > 0.98:
        advice = "音が割れています。Windows のサウンド設定で、マイクの音量を少し下げてください"
    elif voice < noise * 2:
        advice = "声と周りの雑音の差が小さいです。マイクに近づくか、静かな場所で話してください"
    elif voice < 0.02:
        advice = "声が小さめです。マイクに近づくか、Windows のサウンド設定でマイクの音量を上げてください"
    else:
        advice = "よく聞こえています"
    return {"peak": peak, "noise": noise, "voice": voice, "advice": advice, "threshold": threshold}


def play(audio):
    import sounddevice as sd
    if len(audio):
        sd.play(audio, SR)
        sd.wait()


def transcribe(audio):
    """命令の聞き取りと同じAIで文字にする(初回はAIの準備に少し時間がかかる)。"""
    from whisper_worker import WhisperWorker
    worker = WhisperWorker(lambda msg: None)
    try:
        return worker.transcribe(audio, True, timeout=600, command=True)
    finally:
        worker.close()


def threshold_ok(result):
    """いまの感度(音量しきい値)で、声を拾えて雑音は拾わないか。"""
    t = config.VAD_THRESHOLD
    return result["noise"] < t < result["voice"]
