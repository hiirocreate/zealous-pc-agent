# Zealous（ゼラス）— デスクトップ常駐型 AI PCエージェント

| 待機 | 操作中（停止ボタン表示） | 会話パネル |
|---|---|---|
| ![待機](docs/standby.png) | ![操作中](docs/busy.png) | ![パネル](docs/panel.png) |

## 準備 (Windows 11)・コマンド入力は不要
1. 各インストーラーで以下を入れて起動
   - Python 3.10以上（https://www.python.org/ ／「Add python.exe to PATH」にチェック）
   - Ollama（https://ollama.com/）
   - VOICEVOX（https://voicevox.hiroshiba.jp/）
2. このフォルダの **`setup.pyw` をダブルクリック** →「セットアップ開始」
   - 部品のインストール、AIモデル（`qwen2.5:1.5b`）の取得、デスクトップのショートカット作成、自動起動の設定まで行います
3. 以後はデスクトップの **Zealous** アイコン（または `zealous.pyw`）をダブルクリックで起動
   - Bluetooth操作を使う場合は、アイコンを右クリック →「管理者として実行」
4. 設定はすべて本体の **⚙** から変更（接続確認・モデル取得・自動起動もここで操作可）

## 構成
| ファイル | 役割 |
|---|---|
| `app.py` | 常駐UI（待機は横長楕円: マイク / ロゴ・状態 / 会話ボタン。右下最前面・ドラッグ移動可） |
| `theme.py` / `icons.py` | 配色・フォント / ロゴ・アイコン描画 |
| `stopper.py` | 緊急停止ショートカット Ctrl+Shift+E+S |
| `agent_worker.py` | 推論・PC操作を別プロセスで実行。緊急停止でKill→再起動 |
| `llm.py` | Ollama Tool Call 判定（上限 `MAX_TOOL_STEPS`） |
| `tools.py` | ブラウザ / ファイル / 音量・ロック・シャットダウン / Bluetooth |
| `voice.py` | 録音（トランシーバー/トグル/常時待ち受け）＋Faster-Whisper |
| `tts.py` | VOICEVOX 非同期再生 |
| `wakeword.py` | 「ウェイク、<AI名>」検出 |
| `settings_window.py` | 設定の管理画面（⚙ボタン） |
| `setup.pyw` | 初回セットアップ画面（標準ライブラリのみで動作） |
| `zealous.pyw` | 起動用（コンソール画面なし） |
| `services.py` | Ollama/VOICEVOX 接続確認・モデル取得 |
| `shortcut.py` | ショートカット・自動起動の作成 |
| `config.py` | 設定の既定値と `%APPDATA%\Zealous\settings.json` への保存 |

## 動作
- トリガー: 「ウェイク、Zealous（ゼラス）、〜して」。AI名・別表記・ウェイク語は⚙設定画面で変更可。
- 設定は保存時に即反映（推論プロセスを再起動）。Whisper関連のみアプリ再起動後に反映。
- ウェイクON: 常時待ち受けを開始し、先頭にウェイクワードがある音声のみ実行（ボタン録音にも適用）。
- 緊急停止ボタンは操作中のみ表示。Ctrl+Shift+E+S は常に有効。
- 緊急停止: 推論/操作プロセスを強制終了、音声再生・録音・認識待ちも破棄。
- ⚙「お試しモード」ONで関数を実行せず呼び出し内容のみ表示（判定確認用）。
- シャットダウンは30秒猶予（「シャットダウンを取り消して」で中止）。

## テスト（開発者向け）
`python -m pytest tests`
