"""Ollama / VOICEVOX / Whisper を Zealous 専用フォルダへ自動で入れ、裏で起動・停止する。
すでに別途起動している Ollama / VOICEVOX があればそれを使う。"""
import os
import shutil
import subprocess
import urllib.request
import zipfile

import config
import services

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Zealous")
OLLAMA_DIR = os.path.join(DATA_DIR, "ollama")
OLLAMA_MODELS = os.path.join(DATA_DIR, "models")
VOICEVOX_DIR = os.path.join(DATA_DIR, "voicevox")
WHISPER_DIR = os.path.join(DATA_DIR, "whisper")
DL_DIR = os.path.join(DATA_DIR, "downloads")

VOICEVOX_VERSION = "0.26.0"
OLLAMA_ZIP = "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip"
VOICEVOX_PKG = ("https://github.com/VOICEVOX/voicevox_engine/releases/download/"
                f"{VOICEVOX_VERSION}/voicevox_engine-windows-cpu-{VOICEVOX_VERSION}.vvpp")  # 中身は zip

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
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


def extract(archive, folder, progress):
    tmp = folder + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(archive) as z:
        items = z.infolist()
        for i, m in enumerate(items, 1):
            z.extract(m, tmp)
            if i % 50 == 0 or i == len(items):
                progress(i / len(items), f"展開中 {i} / {len(items)}")
    shutil.rmtree(folder, ignore_errors=True)
    os.replace(tmp, folder)
    os.remove(archive)


# ---------------- 起動・停止 ----------------
def _spawn(args, env=None):
    p = subprocess.Popen(args, cwd=os.path.dirname(args[0]), env=env, creationflags=_NO_WINDOW,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _procs.append(p)


def _wait(check, seconds=90):
    import time
    for _ in range(seconds * 2):
        if check():
            return True
        time.sleep(0.5)
    return False


def start_services():
    """入っていて止まっているものだけ裏で起動する。"""
    if not services.check_ollama()[0] and ollama_exe():
        env = dict(os.environ, OLLAMA_MODELS=OLLAMA_MODELS, OLLAMA_HOST="127.0.0.1:11434")
        _spawn([ollama_exe(), "serve"], env)
    if not services.check_voicevox()[0] and voicevox_exe():
        _spawn([voicevox_exe(), "--host", "127.0.0.1", "--port", "50021"])


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
    if not ollama_exe():
        archive = os.path.join(DL_DIR, "ollama.zip")
        download(OLLAMA_ZIP, archive, progress)
        extract(archive, OLLAMA_DIR, progress)
    progress(None, "起動中…")
    start_services()
    if not _wait(lambda: services.check_ollama()[0]):
        raise RuntimeError("Ollama が起動しませんでした")
    return "準備完了"


def step_model(progress):
    if services.check_ollama()[1]:
        return f"{config.OLLAMA_MODEL} 取得済み"

    def on(text):
        parts = text.rsplit(" ", 1)
        pct = parts[1][:-1] if len(parts) == 2 and parts[1].endswith("%") else ""
        progress(int(pct) / 100 if pct.isdigit() else None, text)
    services.pull_model(on)
    return "準備完了"


def step_voicevox(progress):
    if services.check_voicevox()[0]:
        return "起動済みの VOICEVOX を使います"
    if not voicevox_exe():
        archive = os.path.join(DL_DIR, "voicevox.zip")
        download(VOICEVOX_PKG, archive, progress)
        extract(archive, VOICEVOX_DIR, progress)
    progress(None, "起動中…")
    start_services()
    if not _wait(lambda: services.check_voicevox()[0], seconds=180):
        raise RuntimeError("VOICEVOX が起動しませんでした")
    return "準備完了"


def step_whisper(progress):
    progress(None, f"音声認識モデル ({config.WHISPER_MODEL}) を取得中…")
    from faster_whisper import download_model
    download_model(config.WHISPER_MODEL, cache_dir=WHISPER_DIR)
    return "準備完了"


STEPS = [
    ("AIエンジン (Ollama)", step_ollama),
    ("AIモデル", step_model),
    ("音声合成 (VOICEVOX)", step_voicevox),
    ("音声認識 (Whisper)", step_whisper),
]
