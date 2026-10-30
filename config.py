"""設定。settings.json に保存され、管理画面(⚙)から変更できる。
他モジュールは config.AI_NAME のように参照する(load() で更新される)。"""
import json
import os

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Zealous")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")

DEFAULTS = {
    # ---- AI名・ウェイクワード「ウェイク、<AI名>」 ----
    "AI_NAME": "Zealous",
    "HOME_PLACE": "東京",            # 住んでいる地域(「天気は？」と場所を言わなかったときに使う)
    "USER_CALL": "",                 # AIがユーザーを呼ぶときの呼び方(例: 「たろうさん」「マスター」。空なら呼ばない)
    "AI_NAME_ALIASES": ["ゼラス", "ぜらす", "ジーラス", "ゼーラス", "セラス", "ゼラズ", "Zelas", "Zeras"],  # 音声認識での表記ゆれ
    "WAKE_WORDS": ["ウェイク", "ウエイク", "ウェーク", "ウエーク", "うぇいく", "Wake"],
    "WAKE_ENABLED": True,             # 待機中も「ウェイク、<AI名>」を聞き取る
    "INPUT_MODE": "トランシーバー",
    "PTT_ENABLED": True,             # 話すキー(押している間だけ聞き取る)を使う
    "PTT_KEY": "right ctrl",         # 話すキー
    "AUTOSTART": False,              # PC起動時に自動起動
    "WINDOW_POS": None,              # 常駐位置 [x, y](ドラッグで更新)
    "PANEL_SIZE": [340, 500],        # 会話パネルの大きさ [幅, 高さ](端のドラッグで更新)
    "SIDEBAR_OPEN": True,            # パネルが広いとき、スレッド一覧を左に出しておくか
    "PANEL_OFFSET": None,            # 待機表示から見た会話パネルの位置 [x, y](大きさを変えると更新)
    "SMOOTH_FRAME": True,            # Windows: なめらかな外枠と影を重ねて表示(再起動後に反映)
    "SETUP_DONE": False,             # 初回セットアップ画面を表示済みか
    # ---- アップデート ----
    "AUTO_UPDATE": True,             # 起動時(と1日ごと)に新しい版を確認
    "UPDATE_REPO": "hiirocreate/zealous-releases",  # 配布元(GitHub の owner/repo、公開リポジトリ)
    "IMAGE_COUNT": 30,               # 画像を探したときの枚数
    "SEARCH_IMAGE_COUNT": 8,         # 調べものの返事に添える画像の枚数
    "SOURCE_COUNT": 3,               # 調べものの返事に添える参考リンクの数
    "SAFE_SITES_ONLY": True,         # 危険と判定されたサイトは表示・案内しない
    "PERSONA": "",
    "MEMORY": [],                    # AIがユーザーについてずっと覚えておくこと(「〜を覚えておいて」で増える)                   # AIの性格・話し方(空なら標準の丁寧な話し方)
    "PILL_STYLE": "standard",        # 待機中のウィジェットの形(standard 横長 / square 角の丸い正方形 / circle 円)
    "UI_THEME": "midnight",          # 画面の配色(midnight / ocean / sakura / light)
    "UI_FONT": "",                   # 画面の文字のフォント(空なら標準: Yu Gothic UI)
    "UI_FONT_SCALE": 100,            # 画面の文字の大きさ(%)
    "IME_INLINE": True,              # 日本語の変換中の文字を入力欄の中に表示する(OFF で Windows 標準の表示)
    "SETTINGS_VERSION": 2,           # 設定ファイルの形式(古い設定を読み込むときの移し替え用)
    # ---- フォルダ操作の権限 ----
    "FOLDER_OPS_ENABLED": True,      # 作成・移動・コピー・名前変更などを許可
    "FOLDER_DELETE_ENABLED": True,
    "SCREEN_CONTROL_ENABLED": False, # マウス・キーボードで画面を直接操作する(ボタンを押す・文字を入力する など)
    "SCREEN_ALLOW_CLICK": True,      #   ボタン・項目を押す
    "SCREEN_ALLOW_TYPE": True,       #   文字を入力する
    "SCREEN_ALLOW_KEYS": True,       #   キー・ショートカットを押す
    "SCREEN_ALLOW_SCROLL": True,     #   スクロールする
    "SCREEN_ALLOW_WINDOWS": True,    #   ウィンドウの切り替え・最小化・最大化・閉じる
    "SCREEN_WAIT_IDLE": True,        #   マウス・キーボードを借りるときは、あなたの手が止まるまで待つ
    "CONFIRM_VOICE_DANGER": True,    # 声で頼まれた削除・移動・名前変更・シャットダウンは、実行前に確認する   # 削除(ごみ箱へ移動)を許可
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
    "CONTEXT_TURNS": 6,              # 会話の記憶: 直前の何往復を覚えるか(0で記憶しない)
    "FULL_CONTEXT": False,           # このスレッドの会話をすべて参照して答える(長くなったら古い部分を圧縮)
    "FULL_CONTEXT_LIMIT": 12000,     #   参照する会話の上限(文字数)。超えたら古い部分を圧縮する
    "FULL_CONTEXT_COMPRESS": True,   #   上限を超えたら古い部分を要約して使う(OFF なら古い部分は参照しない)
    "WEB_CONTROL_ENABLED": True,     # サイトはゼラス用ブラウザで開き、ページの中の操作(押す・入力・スクロールなど)もする
    "WEB_CONFIRM_RISKY": True,       #   購入・送信・削除などのボタンは、押す前に確かめる
    "CONTEXT_RESET_MIN": 10,         # スレッドを使わない呼び出しで、この分数話しかけなければ記憶を消す
    "SUMMARIZE_AFTER_TOOL": False,   # True: 関数実行後にLLMで返答文を作る(遅くなる)
    "DRY_RUN": False,                # True: 関数を実行せず呼び出し内容だけ返す(モック)
    # ---- 音声合成 (VOICEVOX) ----
    "TTS_ENABLED": True,
    "TTS_SPEED": 1.1,                # 話す速さ(1.0 が標準)
    "VOICEVOX_URL": "http://localhost:50021",
    "VOICEVOX_SPEAKER": 3,
    # ---- 音声認識 (Faster-Whisper) ----
    "WHISPER_MODEL": "base",         # 待機中(合図の言葉を待つ間)の聞き取り用。軽さ優先
    "COMMAND_WHISPER_MODEL": "small",  # 話しかけた命令を文字にする用。正確さ優先(初回に約0.5GBを取得)
    "VOICE_WORDS": [],               # ユーザー辞書: 正しく聞き取ってほしい言葉(固有名詞など)
    "VOICE_REPLACE": [],
    "READINGS": [],                  # 読み方の辞書: 「表記=よみ」の形で、読み上げの読み方を決める(例: 生物=なまもの)             # 置き換え: 「まちがい=正しい」の形で、よく間違う言葉を直す
    "WHISPER_DEVICE": "cpu",
    "WHISPER_COMPUTE": "int8",
    "LANGUAGE": "ja",
    "MIC_DEVICE": "",                # 使うマイクの名前(空なら Windows の既定のマイク)
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
_FOLDER_IDS = {  # Windows が覚えている、本当のフォルダの場所(OneDrive に移したデスクトップなども正しく分かる)
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}


def known_folder(kind):
    """デスクトップ・ドキュメントなどの本当の場所。"""
    if os.name == "nt":
        try:
            import ctypes
            import uuid
            from ctypes import wintypes
            guid = uuid.UUID(_FOLDER_IDS[kind])
            buf = ctypes.c_wchar_p()
            gid = (ctypes.c_byte * 16).from_buffer_copy(guid.bytes_le)
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(gid), 0, None, ctypes.byref(buf)) == 0:
                path = buf.value
                ctypes.windll.ole32.CoTaskMemFree(buf)
                if path and os.path.isdir(path):
                    return path
        except Exception:
            pass
    home = os.path.expanduser("~")
    name = kind.capitalize()
    for p in (os.path.join(home, "OneDrive", name), os.path.join(home, "OneDrive", "デスクトップ")
              if kind == "desktop" else "", os.path.join(home, name)):
        if p and os.path.isdir(p):
            return p
    return os.path.join(home, name)


DESKTOP = known_folder("desktop")


def current():
    return {k: globals()[k] for k in DEFAULTS}


def load():
    values = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        values.update({k: v for k, v in saved.items() if k in DEFAULTS})
        if saved.get("SETTINGS_VERSION", 1) < 2:  # 以前の版は合図の言葉での起動が既定で OFF だった
            values["WAKE_ENABLED"] = True
            for key, new in (("WAKE_WORDS", DEFAULTS["WAKE_WORDS"]), ("AI_NAME_ALIASES", DEFAULTS["AI_NAME_ALIASES"])):
                values[key] = list(dict.fromkeys(list(values[key]) + new))
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
