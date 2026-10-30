"""Ollama / VOICEVOX / Whisper を Zealous 専用フォルダへ自動で入れ、裏で起動・停止する。
すでに別途起動している Ollama / VOICEVOX があればそれを使う。"""
import os
import shutil
import subprocess
import urllib.request

import config
import remotezip
import services

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Zealous")
OLLAMA_DIR = os.path.join(DATA_DIR, "ollama")
OLLAMA_MODELS = os.path.join(DATA_DIR, "models")
VOICEVOX_DIR = os.path.join(DATA_DIR, "voicevox")
WHISPER_DIR = os.path.join(DATA_DIR, "whisper")
AIVIS_DIR = os.path.join(DATA_DIR, "aivisspeech")
AIVIS_VERSION = "1.2.0"
AIVIS_PKG = ("https://github.com/Aivis-Project/AivisSpeech-Engine/releases/download/"
             f"{AIVIS_VERSION}/AivisSpeech-Engine-Windows-x64-{AIVIS_VERSION}.7z.001")

VOICEVOX_VERSION = "0.26.0"
OLLAMA_ZIP = "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip"
VOICEVOX_PKG = ("https://github.com/VOICEVOX/voicevox_engine/releases/download/"
                f"{VOICEVOX_VERSION}/voicevox_engine-windows-cpu-{VOICEVOX_VERSION}.vvpp")  # 中身は zip


def has_nvidia():
    """NVIDIA の GPU ドライバーがあるか(無ければ GPU 用の大きなライブラリを入れない)。"""
    return os.path.exists(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "nvcuda.dll"))


def cuda_folder():
    """Ollama の GPU 用ライブラリのうち、このPCで使う1種類だけを選ぶ(使わないなら None)。
    CUDA 13 用はドライバー 580 以降が必要。それより古い、または確認できなければ CUDA 12 用。"""
    if not config.USE_GPU or not has_nvidia():
        return None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW).stdout
        major = int(out.strip().split(".")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        major = 0
    return "cuda_v13" if major >= 580 else "cuda_v12"


def ollama_member(name, cuda):
    """取り出す Ollama のファイルか(GPU 用ライブラリは選んだ1種類だけ)。"""
    return "/cuda_" not in name or (cuda is not None and f"/{cuda}/" in name)

_procs = []


def _find(folder, exe):
    for root, _, files in os.walk(folder):
        if exe in files:
            return os.path.join(root, exe)
    return None


def ollama_exe():
    return _find(OLLAMA_DIR, "ollama.exe") if os.path.isdir(OLLAMA_DIR) else None


def voicevox_exe():
    p = os.path.join(VOICEVOX_DIR, "run.exe")
    return p if os.path.exists(p) else None


def ollama_ready():
    return services.check_ollama()[0] or bool(ollama_exe())


def voicevox_ready():
    return services.check_voicevox()[0] or bool(voicevox_exe())


def ready():
    return ollama_ready() and voicevox_ready()


# ---------------- ダウンロード・展開 ----------------
def download(url, dest, progress):
    """途中で止まっても続きから再開できるダウンロード。progress(割合0〜1, 説明)。"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    done = os.path.getsize(part) if os.path.exists(part) else 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={done}-"} if done else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        if done and r.status != 206:  # 再開に未対応なら最初から
            done = 0
        total = done + int(r.headers.get("Content-Length") or 0)
        with open(part, "ab" if done else "wb") as f:
            last = -1
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                pct = int(done * 100 / total) if total else 0
                if pct != last:
                    last = pct
                    progress(done / total if total else 0, f"ダウンロード中 {done >> 20} / {total >> 20} MB")
    os.replace(part, dest)


# ---------------- 起動・停止 ----------------
_LOW = 0x00004000 if os.name == "nt" else 0  # BELOW_NORMAL_PRIORITY_CLASS: ほかのアプリの動きを優先させる


def _spawn(args, env=None):
    p = subprocess.Popen(args, cwd=os.path.dirname(args[0]), env=env, creationflags=_NO_WINDOW | _LOW,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _procs.append(p)


def _wait(check, seconds=90):
    import time
    for _ in range(seconds * 2):
        if check():
            return True
        time.sleep(0.5)
    return False


def _voicevox_args():
    # 読み上げに使うCPUの数を半分までにする(読み上げ中もPCが重くならないように。速さはほぼ変わらない)
    threads = max(2, (os.cpu_count() or 4) // 2)
    return [voicevox_exe(), "--host", "127.0.0.1", "--port", "50021", "--cpu_num_threads", str(threads)]


def start_services():
    """入っていて止まっているものだけ裏で起動する。"""
    if not services.check_ollama()[0] and ollama_exe():
        env = dict(os.environ, OLLAMA_MODELS=OLLAMA_MODELS, OLLAMA_HOST="127.0.0.1:11434",
                   # メモリを節約: 同時に読み込むモデルは1つ・同時の処理は1つ・会話の記憶(KVキャッシュ)を半分の大きさに
                   OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_NUM_PARALLEL="1",
                   OLLAMA_FLASH_ATTENTION="1", OLLAMA_KV_CACHE_TYPE="q8_0")
        _spawn([ollama_exe(), "serve"], env)
    engine = getattr(config, "TTS_ENGINE", "voicevox")
    # 読み上げは、選んでいるソフトだけを起動する(使わないソフトでメモリを使わない)
    if config.TTS_ENABLED and engine == "voicevox" and not services.check_voicevox()[0] and voicevox_exe():
        _spawn(_voicevox_args())
    if config.TTS_ENABLED and engine == "aivis":
        start_aivis()


def restart_voicevox():
    """声を変えたときに読み込み直す(Zealous が起動したエンジンのみ)。"""
    for p in list(_procs):
        if str(p.args[0]).endswith("run.exe") and p.poll() is None:
            p.kill()
            p.wait(10)
            _procs.remove(p)
            _spawn(_voicevox_args())


def warm_up():
    """起動直後に AIモデルと声を読み込んでおき、最初の返事を速くする(裏で実行)。"""
    import requests
    import llm
    if _wait(lambda: services.check_ollama()[0], 60):
        try:  # 空の依頼でモデルをメモリに載せる
            requests.post(services.ollama_base() + "/api/generate",
                          # 返事のときと同じ指定で読み込む(違うと、最初の返事で読み込み直しになる)
                          json={"model": config.OLLAMA_MODEL, "keep_alive": "15m",
                                "options": llm.ai_options(num_ctx=4096)}, timeout=120)
        except requests.RequestException:
            pass
    engine = getattr(config, "TTS_ENGINE", "voicevox")
    if config.TTS_ENABLED and engine == "kokoro":
        try:
            import kokoro_tts
            kokoro_tts.prepare()  # 声のモデルを読み込んでおく(初回はダウンロード)
        except Exception as e:
            import zlog
            zlog.error(f"Kokoro の準備に失敗: {e!r}")
        return
    if config.TTS_ENABLED and engine == "voicevox" and _wait(lambda: services.check_voicevox()[0], 120):
        try:
            requests.post(f"{config.VOICEVOX_URL}/initialize_speaker",
                          params={"speaker": config.VOICEVOX_SPEAKER, "skip_reinit": "true"}, timeout=120)
        except requests.RequestException:
            pass


def aivis_exe():
    return _find(AIVIS_DIR, "run.exe") if os.path.isdir(AIVIS_DIR) else None


def aivis_running():
    try:
        with urllib.request.urlopen(config.AIVIS_URL + "/version", timeout=2):
            return True
    except Exception:
        return False


def install_aivis(progress=lambda share, text: None):
    """AivisSpeech Engine を Zealous 専用フォルダへ入れる(約210MB。声のモデルは初回起動時に取得)。"""
    if aivis_exe():
        return
    import py7zr
    pkg = os.path.join(DATA_DIR, "aivisspeech.7z")
    download(AIVIS_PKG, pkg, progress)
    progress(1.0, "読み上げソフト(AivisSpeech)を展開しています…")
    with py7zr.SevenZipFile(pkg) as z:
        z.extractall(AIVIS_DIR)
    os.remove(pkg)


def start_aivis(progress=lambda share, text: None):
    """AivisSpeech を起動する(入っていなければ入れてから)。"""
    if aivis_running():
        return
    install_aivis(progress)
    exe = aivis_exe()
    if exe:
        port = config.AIVIS_URL.rsplit(":", 1)[-1].strip("/") or "10101"
        threads = max(2, (os.cpu_count() or 4) // 2)
        _spawn([exe, "--host", "127.0.0.1", "--port", port, "--cpu_num_threads", str(threads)])


def wait_voicevox(seconds=120):
    """VOICEVOX が応答するまで待つ(声の読み込み直し後など)。"""
    return _wait(lambda: services.check_voicevox()[0], seconds)


def stop_voicevox():
    """Zealous が起動した VOICEVOX を止める(ほかの読み上げに切り替えたとき、メモリを空けるため)。"""
    for p in list(_procs):
        if str(p.args[0]).endswith("run.exe") and os.path.dirname(p.args[0]) == VOICEVOX_DIR and p.poll() is None:
            p.kill()
            _procs.remove(p)


def stop_services():
    for p in _procs:
        if p.poll() is None:
            p.kill()
    _procs.clear()


def kill_all(also=""):
    """アンインストール用: 専用フォルダ(と also 以下)で動いているプロセスを止める。"""
    if os.name != "nt":
        return
    paths = [DATA_DIR] + ([also] if also else [])
    cond = " -or ".join(f"$_.Path -like '{p.replace(chr(39), chr(39) * 2)}*'" for p in paths)
    subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                    f"Get-Process | Where-Object {{ $_.Path -and $_.Id -ne {os.getpid()} -and ({cond}) }}"
                    " | Stop-Process -Force"], capture_output=True, creationflags=_NO_WINDOW)


# ---------------- セットアップ手順 ----------------
def step_ollama(progress):
    if services.check_ollama()[0]:
        return "起動済みの Ollama を使います"
    cuda = cuda_folder()
    variant = cuda or "cpu"
    marker = os.path.join(OLLAMA_DIR, ".variant")
    installed = open(marker).read() if os.path.exists(marker) else ("cpu" if ollama_exe() else "")
    if installed != variant:
        # GPU 用ライブラリは使う1種類だけ(NVIDIA の GPU が無い、または GPU を使わない設定なら入れない)
        stop_services()
        zf, _ = remotezip.open_zip(OLLAMA_ZIP)
        tmp = OLLAMA_DIR + ".tmp"
        if os.path.isdir(OLLAMA_DIR) and not os.path.isdir(tmp):
            os.replace(OLLAMA_DIR, tmp)  # 入っているファイルは再ダウンロードせずに使う
        remotezip.extract(zf, [m for m in zf.infolist() if ollama_member(m.filename, cuda)], tmp, progress)
        lib = os.path.join(tmp, "lib", "ollama")
        for name in os.listdir(lib) if os.path.isdir(lib) else []:
            if name.startswith("cuda_") and name != cuda:  # 使わなくなった GPU 用ライブラリを消す
                shutil.rmtree(os.path.join(lib, name), ignore_errors=True)
        with open(os.path.join(tmp, ".variant"), "w") as f:
            f.write(variant)
        shutil.rmtree(OLLAMA_DIR, ignore_errors=True)
        os.replace(tmp, OLLAMA_DIR)
    progress(None, "起動中…")
    start_services()
    if not _wait(lambda: services.check_ollama()[0]):
        raise RuntimeError("Ollama（AIを動かすソフト）が起動しませんでした")
    return "準備完了"


def step_model(progress):
    if services.check_ollama()[1]:
        return f"{config.OLLAMA_MODEL} 取得済み"
    import models
    progress(None, f"{models.label(config.OLLAMA_MODEL)} をダウンロードします")

    def on(text):
        parts = text.rsplit(" ", 1)
        pct = parts[1][:-1] if len(parts) == 2 and parts[1].endswith("%") else ""
        progress(int(pct) / 100 if pct.isdigit() else None, text)
    services.pull_model(on)
    return "準備完了"


def step_voicevox(progress):
    if services.check_voicevox()[0]:
        return "起動済みの VOICEVOX を使います"
    import voicevox
    progress(None, "声の一覧を取得中…")
    voicevox.catalog()
    voicevox.install_engine(progress)
    voicevox.install_voice(config.VOICEVOX_SPEAKER, progress)
    progress(None, "起動中…")
    start_services()
    if not _wait(lambda: services.check_voicevox()[0], seconds=180):
        raise RuntimeError("VOICEVOX（読み上げソフト）が起動しませんでした")
    return "準備完了"


def step_whisper(progress):
    progress(None, f"音声認識モデル ({config.WHISPER_MODEL}) を取得中…")
    from faster_whisper import download_model
    download_model(config.WHISPER_MODEL, cache_dir=WHISPER_DIR)
    return "準備完了"


STEPS = [
    ("Ollama（AIを動かすソフト）", step_ollama),
    ("AIモデル（AIの頭脳）", step_model),
    ("VOICEVOX（読み上げソフト）", step_voicevox),
    ("Whisper（声を文字にするAI）", step_whisper),
]
