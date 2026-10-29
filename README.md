# Zealous（ゼラス）— デスクトップ常駐型 AI PCエージェント

| 待機 | 応答待ち（停止ボタン表示） | 会話パネル（応答待ち） |
|---|---|---|
| ![待機](docs/standby.png) | ![応答待ち](docs/busy.png) | ![パネル](docs/panel.png) |

## インストール（Windows 11）
1. [Releases](../../releases) または [Actions](../../actions) の成果物から **`ZealousSetup.exe`** をダウンロードして実行
2. 初回起動時のセットアップ画面で「準備を開始」を押す
   - AIエンジン（Ollama）・AIモデル・音声合成（VOICEVOX エンジン）・音声認識（Whisper）を自動でダウンロードして準備します（合計 約4〜5GB、初回のみ）
   - Python・Ollama・VOICEVOX を別途インストールする必要はありません（Python は Zealous.exe に同梱）
   - すでに Ollama / VOICEVOX を起動している場合はそれを使います
3. 以後はデスクトップ・スタートメニューの **Zealous** から起動。Ollama と VOICEVOX は Zealous が裏で自動起動・終了します
4. 設定は本体の **⚙** から（AIモデルを変えたら「部品を準備」で再取得）
   - Bluetooth操作を使う場合は「管理者として実行」

## アンインストール
Windows の「設定 > アプリ > インストールされているアプリ」→ Zealous →「アンインストール」（⚙ の「アンインストール」からも可）。
ダウンロードした部品と設定も消すかは確認画面で選べます。

## 保存場所
| 内容 | 場所 |
|---|---|
| 本体 | `%LOCALAPPDATA%\Programs\Zealous` |
| Ollama・AIモデル・VOICEVOX・Whisper | `%LOCALAPPDATA%\Zealous` |
| 設定 | `%APPDATA%\Zealous\settings.json` |

## 開発者向け
- ソースから実行: `pip install -r requirements.txt` → `python zealous.pyw`
- インストーラーは GitHub Actions（`.github/workflows/build.yml`）が PyInstaller + Inno Setup で自動作成。`v1.0.0` のようなタグを push すると Releases に公開

## 構成
| ファイル | 役割 |
|---|---|
| `app.py` | 常駐UI（待機は横長楕円: マイク / ロゴ・状態 / 会話ボタン。右下最前面・ドラッグ移動可） |
| `theme.py` / `icons.py` | 配色・フォント / ロゴ・アイコン描画 |
| `stopper.py` | 緊急停止ショートカット Ctrl+Shift+E+S |
| `agent_worker.py` | 推論・PC操作を別プロセスで実行。緊急停止でKill→再起動 |
| `llm.py` | Ollama Tool Call 判定（上限 `MAX_TOOL_STEPS`） |
| `tools.py` | ブラウザ / ファイル・フォルダ（開く・一覧・作成・名前変更・移動・コピー・ごみ箱へ削除） / 音量・ロック・シャットダウン / Bluetooth |
| `voice.py` | 録音（トランシーバー/トグル/常時待ち受け）＋Faster-Whisper |
| `tts.py` | VOICEVOX 非同期再生 |
| `wakeword.py` | 「ウェイク、<AI名>」検出 |
| `settings_window.py` | 設定の管理画面（⚙ボタン） |
| `zealous.pyw` | 起動口（初回セットアップ → 本体、`--uninstall` で後片付け） |
| `setup_wizard.py` | 初回セットアップ画面 |
| `runtime.py` | Ollama・VOICEVOX・Whisper の自動ダウンロードと裏での起動/停止 |
| `packaging/installer.iss` | インストーラー（Inno Setup）定義 |
| `services.py` | Ollama/VOICEVOX 接続確認・モデル取得 |
| `shortcut.py` | 自動起動・起動コマンド |
| `config.py` | 設定の既定値と `%APPDATA%\Zealous\settings.json` への保存 |

## 動作
- トリガー: 「ウェイク、Zealous（ゼラス）、〜して」。AI名・別表記・ウェイク語は⚙設定画面で変更可。
- 設定は保存時に即反映（推論プロセスを再起動）。Whisper関連のみアプリ再起動後に反映。
- ウェイクON: 常時待ち受けを開始し、先頭にウェイクワードがある音声のみ実行（ボタン録音にも適用）。
- 待機表示はドラッグで移動可（位置は保存）。会話パネルは常駐位置から画面の内側へ展開。
- チャット欄: Enter で送信 / Shift+Enter で改行。
- フォルダ操作は ⚙ の「権限」で許可/禁止を切替。Windows・Program Files・ドライブ直下・ホーム直下・アプリ本体は常に保護。削除はごみ箱へ移動。
- 応答待ちの間はドットが波打つローディング表示。
- 緊急停止ボタンは操作中のみ表示。Ctrl+Shift+E+S は常に有効。
- 緊急停止: 推論/操作プロセスを強制終了、音声再生・録音・認識待ちも破棄。
- ⚙「お試しモード」ONで関数を実行せず呼び出し内容のみ表示（判定確認用）。
- シャットダウンは30秒猶予（「シャットダウンを取り消して」で中止）。

## テスト
`python -m pytest tests`
