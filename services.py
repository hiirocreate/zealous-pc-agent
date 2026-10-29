"""Ollama / VOICEVOX の接続確認とモデル取得。標準ライブラリのみ(セットアップ画面からも使う)。"""
import json
import urllib.request

import config


def ollama_base():
    return config.OLLAMA_URL.split("/api/")[0]


def _get(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def check_ollama():
    """(起動しているか, モデル取得済みか, メッセージ)"""
    try:
        names = [m["name"] for m in _get(ollama_base() + "/api/tags")["models"]]
    except Exception:
        return False, False, "Ollama が起動していません"
    has = any(n == config.OLLAMA_MODEL or n.split(":")[0] == config.OLLAMA_MODEL for n in names)
    return True, has, f"Ollama OK / モデル {config.OLLAMA_MODEL}: {'取得済み' if has else '未取得'}"


def check_voicevox():
    try:
        return True, f"VOICEVOX OK (v{_get(config.VOICEVOX_URL + '/version')})"
    except Exception:
        return False, "VOICEVOX が起動していません"


def pull_model(on_progress):
    """モデルをダウンロードする。on_progress(文字列) で進捗を通知。"""
    body = json.dumps({"model": config.OLLAMA_MODEL, "stream": True}).encode()
    req = urllib.request.Request(ollama_base() + "/api/pull", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        for line in r:
            d = json.loads(line)
            if "error" in d:
                raise RuntimeError(d["error"])
            pct = f" {d['completed'] * 100 // d['total']}%" if d.get("total") and d.get("completed") else ""
            on_progress(d.get("status", "") + pct)
    on_progress("モデル取得完了")
