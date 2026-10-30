"""AIモデルの選択肢と、ダウンロードサイズの確認(モデルを変えるときに必ずユーザーへ伝える)。"""
import json
import urllib.request

# (名前, サイズ, 必要メモリの目安, 一言の特徴)  サイズは Ollama 公式の値
KNOWN = [
    ("qwen2.5:1.5b", "986MB", "約2GB", "軽い・初期設定"),
    ("qwen3.5:0.8b-q8_0", "1.0GB", "約2GB", "軽い・新しい世代"),
    ("qwen3.5:2b-q4_K_M", "1.9GB", "約3GB", "新しい世代・賢さと軽さのバランス"),
    ("qwen3.5:4b-q4_K_M", "3.3GB", "約5GB", "新しい世代・かなり賢い"),
    ("qwen2.5:0.5b", "398MB", "約1GB", "とても軽い・精度は低め"),
    ("qwen2.5:3b", "1.9GB", "約3〜4GB", "速さと精度のバランスが良い"),
    ("qwen2.5:7b", "4.7GB", "約6〜8GB", "高精度・GPUが無いと遅い"),
    ("qwen2.5:14b", "9.0GB", "約12GB以上", "とても高精度・GPU推奨"),
    ("maternion/lfm2:8b-a1b", "5.0GB", "約6〜8GB", "必要な部分だけ動かす仕組み(MoE)・速くて賢い・テクニカルモードにおすすめ"),
    ("granite4:tiny-h", "4.2GB", "約6GB", "IBM・MoE(動くのは約10億)・指示と関数の扱いが正確"),
    ("granite4:micro-h", "1.9GB", "約3GB", "IBM・軽い"),
    ("sam860/olmoe-1b-7b-0924", "3.0GB", "約4〜5GB", "AllenAI・MoE(動くのは約10億)・英語向け"),
    # ---- 低負担でコスパの良いモデル(1〜2GB・メモリ2〜4GB) ----
    ("lfm3:1.7b-q4_K_M", "1.1GB", "約2GB", "Liquid AI・とても軽いのに賢い・コスパ重視におすすめ"),
    ("lfm3:1.7b-q8_0", "1.8GB", "約3GB", "Liquid AI・上の高精度版"),
    ("granite4.2:3b-q4_K_M", "2.2GB", "約3〜4GB", "IBM・指示と関数の扱いが正確・コードも得意"),
    # ---- コーディングが得意なモデル ----
    ("qwen2.5-coder:1.5b", "986MB", "約2GB", "コード向け・軽い"),
    ("qwen2.5-coder:3b", "1.9GB", "約3〜4GB", "コード向け・軽さと精度のバランス"),
    ("nemotron-3.5-bolt:e4b-q4_K_M", "7.9GB", "約10GB", "NVIDIA・コード・関数の扱いが得意"),
    ("laguna-xs-2.1:q4_K_M", "20.3GB", "約24GB以上", "コード専用の上位モデル・MoE(動くのは約30億)"),
    ("qwen3.6:35b-a3b-coding-mtp-q4_K_M", "22.6GB", "約26GB以上", "コード専用の最上位・MoE(動くのは約30億)"),
    # ---- ハイエンド(高性能なPC向け) ----
    ("qwen3.5:9b-q4_K_M", "6.6GB", "約8〜10GB", "上位モデル・かなり賢い・GPU推奨"),
    ("gemma4:12b-it-q4_K_M", "8.0GB", "約10〜12GB", "Google・上位モデル・GPU推奨"),
    ("qwen3.6:35b-a3b-q4_K_M", "23.9GB", "約28GB以上", "最上位クラス・MoEで大きさの割に速い"),
    ("qwen3.8:27b-q4_K_M", "17.7GB", "約22GB以上", "最上位クラス・GPU(24GB)推奨"),
    ("llama3.2:1b", "1.3GB", "約2GB", "軽い・英語が得意"),
    ("llama3.2:3b", "2.0GB", "約3〜4GB", "英語が得意"),
]

# 選んだモデルの「特徴」と「注意点」(設定画面で、選んだモデルの下に表示する)
DETAILS = {
    "qwen2.5:1.5b": ("2024年の世代の小さなモデル。どのPCでも軽く動き、返事も速い。",
                     "日本語の言い回しがやや不自然なことがある。長い指示や、いくつもの操作を一度に頼むと取り違えやすい。"),
    "qwen3.5:0.8b-q8_0": ("2026年の新しい世代。いまの標準とほぼ同じ軽さで、日本語の自然さと関数(PC操作)の使い方がやや上。"
                          "画像の理解にも対応。",
                          "とても小さいモデルなので、複雑な指示や長い会話は苦手。考える過程は切って使う(返事を速くするため)。"
                          "新しめの Ollama(0.17.5以降)が必要。"),
    "qwen3.5:2b-q4_K_M": ("新しい世代の中くらいのモデル。日本語の自然さ、指示の理解、PC操作の正確さがはっきり良くなる。"
                          "迷ったらこれがおすすめ。",
                          "いまの標準の約2倍の大きさ。メモリ8GBのPCでは、ほかのアプリを多く開いていると重くなることがある。"
                          "新しめの Ollama(0.17.5以降)が必要。"),
    "qwen3.5:4b-q4_K_M": ("新しい世代でかなり賢い。複数の操作を組み合わせた依頼や、詳しい説明も得意。",
                          "メモリ16GB以上のPC向け。GPUが無いと返事が遅く感じることがある。新しめの Ollama(0.17.5以降)が必要。"),
    "qwen2.5:0.5b": ("とても小さく、古いPCでも動く。",
                     "精度は低め。言い間違いや、指示とずれた返事が増える。"),
    "qwen2.5:3b": ("2024年の世代。速さと賢さのバランスが良い。",
                   "新しい世代(qwen3.5:2b)の方が、同じくらいの大きさで賢い。"),
    "qwen2.5:7b": ("賢く、詳しい説明も得意。",
                   "メモリ8GB以上が必要。GPU(NVIDIA製)が無いと返事が遅い。"),
    "qwen2.5:14b": ("とても賢い。",
                    "メモリ16GB以上とGPU(NVIDIA製)を推奨。GPUが無いとかなり遅い。"),
    "maternion/lfm2:8b-a1b": ("Liquid AI の LFM2-8B-A1B。全体は83億パラメータだが、1回に動くのは約15億だけ(MoE)なので、"
                              "30〜40億クラスの賢さで、17億クラスより速い。コードも多く学んでいる。日本語に対応。",
                              "ダウンロードとメモリは全体の大きさ分が必要(約5GB・メモリ8GB以上推奨)。"
                              "有志が Ollama 用に変換したもの(公式の一覧ではない)。"),
    "granite4:tiny-h": ("IBM の Granite 4.0 Tiny。全体70億・動くのは約10億(MoE)。指示どおりに動くことと、"
                        "関数(PC操作)の呼び出しが正確。日本語に対応。",
                        "メモリ8GB以上推奨。会話の自然さは LFM2 や qwen の方が上のことがある。"),
    "granite4:micro-h": ("IBM の Granite 4.0 Micro。30億の軽いモデル。", "込み入ったコードの相談は苦手。"),
    "sam860/olmoe-1b-7b-0924": ("AllenAI の OLMoE。全体70億・動くのは約10億(MoE)。学習データまで公開された完全なオープンソース。",
                                "英語向けで、日本語は苦手。関数(PC操作)の呼び出しに対応していないので、"
                                "テクニカルモードでの相談・コードの説明向け。有志が Ollama 用に変換したもの。"),
    "lfm3:1.7b-q4_K_M": ("Liquid AI の LFM3-1.7B(2026年10月)。メモリ約1GBで動くほど軽いのに、関数(PC操作)の扱いや指示の理解が得意。"
                         "日本語に対応。軽さと賢さのつり合いが最も良い選択肢のひとつ。",
                         "とても新しいモデルなので、最新の Ollama が必要。長い文章をていねいに書くのは、大きいモデルの方が上。"),
    "lfm3:1.7b-q8_0": ("LFM3-1.7B の、圧縮を控えめにした版。言い回しの正確さが少し上がる。",
                       "4bit 版より大きく、少し遅い。最新の Ollama が必要。"),
    "granite4.2:3b-q4_K_M": ("IBM の Granite 4.2(30億)。指示どおりに動くこと・関数(PC操作)の呼び出し・決まった形(JSON)で書くことが正確で、"
                             "コードも得意。日本語に対応。",
                             "会話の自然さは qwen 系の方が上のことがある。"),
    "qwen2.5-coder:1.5b": ("コード用に学習した小さなモデル。コードの説明・修正・短いコードの作成が軽く動く。",
                           "ふだんの会話や日本語の文章は苦手。テクニカルモード用に向く。"),
    "qwen2.5-coder:3b": ("コード用に学習したモデル。軽さと正確さのバランスが良い。",
                         "ふだんの会話は qwen 系の通常モデルの方が自然。テクニカルモード用に向く。"),
    "nemotron-3.5-bolt:e4b-q4_K_M": ("NVIDIA の Nemotron 3.5 Bolt。PCの中でのコード・考える力・関数の扱い向けに調整されたモデル。",
                                     "メモリ12GB以上推奨。画像を読む部品も含むため、ダウンロードが大きめ。"),
    "laguna-xs-2.1:q4_K_M": ("コード専用の上位モデル。全体330億・動くのは約30億(MoE)なので、大きさの割に速い。",
                             "メモリ32GB以上のPC向け。日本語の会話は通常モデルの方が自然。"),
    "qwen3.6:35b-a3b-coding-mtp-q4_K_M": ("Qwen3.6 のコード向け版。全体350億・動くのは約30億(MoE)。最上位クラスのコードの力。",
                                          "メモリ32GB以上のPC向け(GPUがあるとさらに速い)。ダウンロードがとても大きい。"),
    "qwen3.5:9b-q4_K_M": ("新しい世代の上位モデル。複雑な依頼・詳しい説明・資料づくりがはっきり良くなる。",
                          "メモリ16GB以上推奨。GPU(NVIDIA製・8GB以上)があると快適。"),
    "gemma4:12b-it-q4_K_M": ("Google の Gemma 4(120億)。文章・考える力・コードのバランスが良い上位モデル。日本語も自然。",
                             "メモリ16GB以上推奨。GPU(NVIDIA製・12GB以上)があると快適。"),
    "qwen3.6:35b-a3b-q4_K_M": ("Qwen3.6。全体350億・動くのは約30億(MoE)なので、最上位クラスの賢さで動きは速い。",
                               "メモリ32GB以上のPC向け。ダウンロードがとても大きい。"),
    "qwen3.8:27b-q4_K_M": ("Qwen3.8(270億)。いま選べる中で最も賢いクラス。コード・資料づくり・長い作業も得意。",
                           "GPU(NVIDIA製・24GB)か、メモリ32GB以上が必要。GPUが無いととても遅い。"),
    "llama3.2:1b": ("軽い。英語での会話が得意。", "日本語は苦手で、不自然な返事が多い。"),
    "llama3.2:3b": ("英語での会話が得意。", "日本語は苦手。日本語で使うなら qwen 系がおすすめ。"),
}


def details(name):
    """(特徴, 注意点)。一覧にないモデルは None。"""
    return DETAILS.get(name)


def thinks(name):
    """返事の前に「考える過程」を書くモデルか(書かせると遅くなるので、切って使う)。"""
    return name.startswith(("qwen3", "lfm3", "lfm2.5", "granite4.2", "gemma4", "nemotron-3", "laguna"))


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


# ---------------- PCのメモリに合わせたモデル選び ----------------
def memory_gb():
    """(搭載メモリ, いま空いているメモリ) を GB で。分からなければ (0, 0)。"""
    import os
    try:
        if os.name == "nt":
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MEM()
            m.dwLength = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 2 ** 30, m.ullAvailPhys / 2 ** 30
        info = dict(line.split(":", 1) for line in open("/proc/meminfo"))
        kb = lambda k: int(info[k].split()[0]) / 2 ** 20  # noqa: E731
        return kb("MemTotal"), kb("MemAvailable")
    except Exception:
        return 0.0, 0.0


def need_gb(name):
    """そのモデルを動かすのに要るメモリの目安(GB)。一覧にないものは 4GB とみなす。"""
    k = next((k for k in KNOWN if k[0] == name), None)
    if not k:
        return 4.0
    size, unit = float(k[1][:-2]), k[1][-2:]
    return (size if unit == "GB" else size / 1000) * 1.2 + 0.8  # 本体 + 会話の記憶(KVキャッシュ)などの分


# テクニカルモードの「自動」: 搭載メモリが多い順に、入るものを選ぶ(GPU が無くても動く大きさ)
TECH_AUTO = [(24, "maternion/lfm2:8b-a1b"), (12, "granite4.2:3b-q4_K_M")]


def auto_tech(total_gb):
    """搭載メモリに合うテクニカルモード用のモデル(少なければ "" = いつものAIをそのまま使う)。"""
    return next((name for gb, name in TECH_AUTO if total_gb >= gb), "")

