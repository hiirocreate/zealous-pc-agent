"""設定。settings.json に保存され、管理画面(⚙)から変更できる。
他モジュールは config.AI_NAME のように参照する(load() で更新される)。"""
import json
import os

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Zealous")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")

DEFAULTS = {
    # ---- AI名・ウェイクワード「ウェイク、<AI名>」 ----
    "AI_NAME": "Zealous",
    "AI_NAME_ALIASES": ["ゼラス", "ぜらす", "ジーラス", "ゼーラス"],  # 音声認識での表記ゆれ
    "WAKE_WORDS": ["ウェイク", "ウエイク", "うぇいく", "Wake"],
    "WAKE_ENABLED": False,
    "INPUT_MODE": "トランシーバー",
    "PTT_ENABLED": True,             # 話すキー(押している間だけ聞き取る)を使う
    "PTT_KEY": "right ctrl",         # 話すキー
    "AUTOSTART": False,              # PC起動時に自動起動
    "WINDOW_POS": None,              # 常駐位置 [x, y](ドラッグで更新)
    "PANEL_SIZE": [340, 500],
    "SMOOTH_FRAME": True,            # Windows: なめらかな外枠と影を重ねて表示(再起動後に反映)        # 会話パネルの大きさ [幅, 高さ](端のドラッグで更新)
    "SETUP_DONE": False,             # 初回セットアップ画面を表示済みか
    # ---- アップデート ----
    "AUTO_UPDATE": True,             # 起動時(と1日ごと)に新しい版を確認
    "UPDATE_REPO": "hiirocreate/zealous-releases",  # 配布元(GitHub の owner/repo、公開リポジトリ)             # 初回セットアップ画面を表示済みか              # 常駐位置 [x, y](ドラッグで更新)
    # ---- フォルダ操作の権限 ----
    "FOLDER_OPS_ENABLED": True,      # 作成・移動・コピー・名前変更などを許可
    "FOLDER_DELETE_ENABLED": True,   # 削除(ごみ箱へ移動)を許可
    # ---- ブラウザ: chrome / edge / firefox / default ----
    "BROWSER": "chrome",
    "SEARCH_URL": "https://www.google.com/search?q={}",
    # ---- LLM (Ollama) ----
    "OLLAMA_URL": "http://localhost:11434/api/chat",
    "OLLAMA_MODEL": "qwen2.5:1.5b",
    "OLLAMA_TIMEOUT": 60,
    "USE_GPU": True,                 # NVIDIA の GPU があれば使う(GPU 用ライブラリを追加で取得)
    "MAX_TOOL_STEPS": 3,             # 1命令あたりの関数呼び出し上限(ループ防止)
    "QUICK_ROUTE": True,             # 「〜を調べて」などはAIの判断を待たずに直接実行(速い)
    "CONTEXT_TURNS": 4,              # 会話の記憶: 直前の何往復を覚えるか(0で記憶しない)
    "CONTEXT_RESET_MIN": 10,         # スレッドを使わない呼び出しで、この分数話しかけなければ記憶を消す
    "SUMMARIZE_AFTER_TOOL": False,   # True: 関数実行後にLLMで返答文を作る(遅くなる)
    "DRY_RUN": False,                # True: 関数を実行せず呼び出し内容だけ返す(モック)
    # ---- 音声合成 (VOICEVOX) ----
    "TTS_ENABLED": True,
    "TTS_SPEED": 1.1,                # 話す速さ(1.0 が標準)
    "VOICEVOX_URL": "http://localhost:50021",
    "VOICEVOX_SPEAKER": 3,
    # ---- 音声認識 (Faster-Whisper) ※変更はアプリ再起動後に反映 ----
    "WHISPER_MODEL": "base",
    "WHISPER_DEVICE": "cpu",
    "WHISPER_COMPUTE": "int8",
    "LANGUAGE": "ja",
    # ---- 常時待ち受けの発話区切り ----
    "VAD_THRESHOLD": 0.015,
    "VAD_SILENCE_SEC": 0.8,
    "VAD_MAX_SEC": 15.0,
    "VAD_MIN_SEC": 0.4,
}

# ---- 固定値(管理画面では変更しない) ----
EMERGENCY_KEYS = ["ctrl", "shift", "e", "s"]
SAMPLE_RATE = 16000
WINDOW_W, WINDOW_H = 360, 270
MARGIN_X, MARGIN_Y = 12, 60    # 右下からの余白(MARGIN_Y はタスクバー分)
DESKTOP = next(
    (p for p in (os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"),
                 os.path.join(os.path.expanduser("~"), "Desktop")) if os.path.isdir(p)),
    os.path.join(os.path.expanduser("~"), "Desktop"),
)


def current():
    return {k: globals()[k] for k in DEFAULTS}


def load():
    values = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            values.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    globals().update(values)


def save(changes):
    values = current()
    values.update({k: v for k, v in changes.items() if k in DEFAULTS})
    os.makedirs(APP_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False, indent=2)
    globals().update(values)


def reset():
    save(DEFAULTS)


load()
