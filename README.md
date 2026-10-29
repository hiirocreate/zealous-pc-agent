# ゼラス（Zealous）— デスクトップ常駐型 AI PCエージェント

## 準備 (Windows 11)
1. Ollama を起動し `ollama pull qwen2.5:1.5b`
2. VOICEVOX を起動 (`http://localhost:50021`)
3. `pip install -r requirements.txt`
4. `python app.py`（Bluetooth操作は管理者権限で起動）

## 構成
| ファイル | 役割 |
|---|---|
| `app.py` | 常駐UI（右下・最前面・ドラッグ移動可） |
| `stopper.py` | 緊急停止ショートカット Ctrl+Shift+E+S |
| `agent_worker.py` | 推論・PC操作を別プロセスで実行。緊急停止でKill→再起動 |
| `llm.py` | Ollama Tool Call 判定（上限 `MAX_TOOL_STEPS`） |
| `tools.py` | ブラウザ / ファイル / 音量・ロック・シャットダウン / Bluetooth |
| `voice.py` | 録音（トランシーバー/トグル/常時待ち受け）＋Faster-Whisper |
| `tts.py` | VOICEVOX 非同期再生 |
| `wakeword.py` | 「ウェイク、<AI名>」検出 |
| `settings_window.py` | 設定の管理画面（⚙ボタン） |
| `config.py` | 設定の既定値と `%APPDATA%\Zealous\settings.json` への保存 |

## 動作
- トリガー: 「ウェイク、ゼラス、〜して」。AI名・別表記・ウェイク語は⚙設定画面で変更可。
- 設定は保存時に即反映（推論プロセスを再起動）。Whisper関連のみアプリ再起動後に反映。
- ウェイクON: 常時待ち受けを開始し、先頭にウェイクワードがある音声のみ実行（ボタン録音にも適用）。
- 緊急停止: 推論/操作プロセスを強制終了、音声再生・録音・認識待ちも破棄。
- `DRY_RUN = True` で関数を実行せず呼び出し内容のみ表示（判定確認用）。
- シャットダウンは30秒猶予（「シャットダウンを取り消して」で中止）。

## テスト
`python -m pytest pc_agent/tests`
