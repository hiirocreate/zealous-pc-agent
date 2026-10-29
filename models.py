"""AIモデルの選択肢と、ダウンロードサイズの確認(モデルを変えるときに必ずユーザーへ伝える)。"""
import json
import urllib.request

# (名前, サイズ, 必要メモリの目安, 特徴)  サイズは Ollama 公式の値
KNOWN = [
    ("qwen2.5:0.5b", "398MB", "約1GB", "とても軽い・精度は低め"),
    ("qwen2.5:1.5b", "986MB", "約2GB", "軽い・初期設定"),
    ("qwen2.5:3b", "1.9GB", "約3〜4GB", "速さと精度のバランスが良い"),
    ("qwen2.5:7b", "4.7GB", "約6〜8GB", "高精度・GPUが無いと遅い"),
    ("qwen2.5:14b", "9.0GB", "約12GB以上", "とても高精度・GPU推奨"),
    ("llama3.2:1b", "1.3GB", "約2GB", "軽い・英語が得意"),
    ("llama3.2:3b", "2.0GB", "約3〜4GB", "英語が得意"),
]


def label(name):
    """選択肢の表示名(例: qwen2.5:3b（1.9GB・メモリ約3〜4GB・速さと精度のバランスが良い）)。"""
    k = next((k for k in KNOWN if k[0] == name), None)
    return f"{name}（{k[1]}・メモリ{k[2]}・{k[3]}）" if k else name


def name_of(text):
    """表示名からモデル名だけを取り出す(手入力された名前はそのまま)。"""
    return text.split("（")[0].strip()


def fetch_size(name):
    """Ollama の配布元に問い合わせて、ダウンロードサイズ(バイト)を返す。分からなければ None。"""
    repo, _, tag = name.partition(":")
    if "/" not in repo:
        repo = f"library/{repo}"
    req = urllib.request.Request(f"https://registry.ollama.ai/v2/{repo}/manifests/{tag or 'latest'}",
                                 headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return sum(layer["size"] for layer in json.load(r)["layers"])
    except Exception:
        return None


def size_text(size):
    return f"{size / 1e9:.1f}GB" if size >= 1e9 else f"{size / 1e6:.0f}MB"


def warning(name):
    """モデルを変えるときに必ず表示する注意文(サイズ・メモリ・影響)。"""
    k = next((k for k in KNOWN if k[0] == name), None)
    if k:
        size = k[1]
    else:
        fetched = fetch_size(name)
        if fetched is None:
            return (f"「{name}」のサイズを確認できませんでした（名前の間違い、またはネット未接続）。\n"
                    "このまま保存すると、取得に失敗する可能性があります。")
        size = size_text(fetched)
    mem = f"\n必要なメモリの目安: {k[2]}" if k else ""
    return (f"AIモデルを「{name}」に変更します。\n\n"
            f"ダウンロードサイズ: {size}{mem}\n\n"
            "・保存するとダウンロードを始めます（回線によって数分〜数十分）\n"
            "・大きいモデルほど賢くなりますが、返事が遅くなり、PCのメモリを多く使います\n"
            "・メモリが足りないと、PC全体が重くなったり動かなくなったりします")
