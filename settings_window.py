"""各種設定の管理画面(左のタブで切り替え)。保存すると settings.json に書き込み、即時反映する。
専門用語には必ず（）で分かりやすい言い換えを付ける。"""
import os
import threading

import customtkinter as ctk

import config
import icons
import models
import services
import shortcut
import theme as T
import voicevox
from version import VERSION

# 項目: (キー, 表示名, 種類, 補足説明[, 選択肢])
#   種類: str / int / float / bool / list / choice / model
#   choice の選択肢は (保存する値, 表示名) の組
# (項目の説明のもと。画面のタブの並びは下の LAYOUT で決める)
_SOURCE = [
    ("一般", [
        ("—", "名前と呼びかけ"),
        ("AI_NAME", "AI名", "str", "画面の表示と、呼びかけに使う名前"),
        ("HOME_PLACE", "住んでいる地域", "str", "都道府県や市の名前（例: 大阪、札幌）。場所を言わずに天気を聞いたときに使います"),
        ("USER_CALL", "あなたの呼び方", "str", "AIがあなたを呼ぶときの名前（例: たろうさん、マスター）。空なら名前では呼びません"),
        ("AI_NAME_ALIASES", "AI名の別表記", "list", "聞き間違えやすい呼び方をカンマ（,）区切りで"),
        ("WAKE_WORDS", "ウェイク語（呼びかけの合図の言葉）", "list", "例: 「ウェイク、Zealous、〜して」の「ウェイク」"),
        ("WAKE_ENABLED", "ウェイクワード（合図の言葉）で起動", "bool",
         "ONにすると、マイクを押さなくても常に聞き取り、合図の言葉で始まる命令だけ実行"
         "（マイクボタンで話すときは合図の言葉は不要）"),
        ("—", "マイク"),
        ("INPUT_MODE", "マイクの入力方式", "choice", "マイクボタンと話すキーの使い方",
         [("トランシーバー", "トランシーバー（押している間だけ録音）"),
          ("トグル", "トグル（1回押して開始・もう1回で終了）")]),
        ("PTT_ENABLED", "話すキー（押している間だけ聞き取るキー）を使う", "bool",
         "どの画面を開いていても、キーを押しながら話すだけで聞き取ります"),
        ("PTT_KEY", "話すキー", "choice",
         "普段の操作で使わないキーがおすすめ。スペースは長押しで話し、短く押すと普通のスペースになります",
         [("right ctrl", "右Ctrl"), ("space", "スペース（長押しで話す）"), ("right alt", "右Alt"),
          ("right shift", "右Shift"), ("f8", "F8"),
          ("f9", "F9"), ("f10", "F10"), ("scroll lock", "Scroll Lock"), ("pause", "Pause")]),
        ("—", "起動"),
        ("AUTOSTART", "PC起動時に自動で起動", "bool", "Windows にサインインしたら Zealous を立ち上げる"),
        ("—", "表示"),
        ("PILL_STYLE", "待機中のウィジェットの形", "choice",
         "画面の隅に待機しているときの形。正方形と円は、ロゴを押すとチャット、右クリックで音声会話などを選べます",
         [("standard", "標準（横長・マイクとチャットのボタンつき）"), ("square", "角の丸い正方形"), ("circle", "円（いちばん小さい）")]),
        ("UI_THEME", "カラー（画面の配色）", "choice", "画面全体の色合い（保存後、再起動で反映）",
         [(k, v["LABEL"]) for k, v in T.THEMES.items()]),
        ("UI_FONT", "フォント（画面の文字の書体）", "font", "このPCに入っているフォントから選べます（保存後、再起動で反映）"),
        ("UI_FONT_SCALE", "文字の大きさ", "choice", "画面全体の文字の大きさ（保存後、再起動で反映）",
         [(90, "小さめ（90%）"), (100, "標準（100%）"), (115, "大きめ（115%）"), (130, "特大（130%）")]),
        ("IME_INLINE", "日本語入力を入力欄の中に表示", "bool",
         "変換中の文字を入力欄の中に表示します。文字入力で調子が悪いときはOFFに（再起動後に反映）"),
        ("SMOOTH_FRAME", "なめらかな外枠と影", "bool",
         "ウィジェット（常駐する小さな窓）の縁を滑らかにし、影を付けます。表示が乱れる場合はOFFに（再起動後に反映）"),
    ]),
    ("権限", [
        ("—", "AIに任せる操作"),
        ("—", "画面の直接操作"),
        ("SCREEN_CONTROL_ENABLED", "画面を直接操作する", "bool",
         "直前まで使っていたウィンドウで、ボタンを押す・文字を入れる・キーを押す・スクロールするなどを許可します。"
         "できるだけマウスを動かさずに操作し、あなたの操作を邪魔しません"),
        ("SCREEN_ALLOW_CLICK", "　ボタンや項目を押す", "bool", "「保存を押して」「OKをクリックして」など"),
        ("SCREEN_ALLOW_TYPE", "　文字を入力する", "bool", "「〇〇と入力して」など"),
        ("SCREEN_ALLOW_KEYS", "　キー・ショートカットを押す", "bool", "「Ctrl+Sを押して」「エンターを押して」など"),
        ("SCREEN_ALLOW_SCROLL", "　スクロールする", "bool", "「下にスクロールして」など"),
        ("SCREEN_ALLOW_WINDOWS", "　ウィンドウを操作する", "bool",
         "「メモ帳に切り替えて」「最小化して」「閉じて」など（声で「閉じて」は確認してから）"),
        ("SCREEN_WAIT_IDLE", "　あなたの操作を優先する", "bool",
         "マウスやキーボードを借りる必要があるときは、あなたの手が止まるまで待ち、終わったらマウスの位置と使っていた窓を元に戻します"),
        ("—", "Webページの操作"),
        ("WEB_CONTROL_ENABLED", "Webページの中を操作する", "bool",
         "サイトはゼラス用のブラウザ（Chrome か Edge。普段のものとは別のプロフィール）で開き、"
         "「ログインを押して」「検索欄に〇〇と入力して」「前のページに戻って」「動画を止めて」"
         "「このページを要約して」などをページの中へ直接行います。マウスやキーボードは使いません。"
         "パスワードの入力はしません"),
        ("WEB_CONFIRM_RISKY", "　購入・送信・削除などは確認する", "bool",
         "「購入」「注文」「送信」「削除」などのボタンは、声でも文字でも、押す前に「はい/いいえ」で確かめます"),
        ("—", "ファイル・フォルダ"),
        ("FOLDER_OPS_ENABLED", "ファイル・フォルダ操作を許可", "bool", "作成・名前変更・移動・コピー・一覧"),
        ("FOLDER_DELETE_ENABLED", "削除を許可", "bool", "削除はごみ箱へ移動するだけで、完全には消しません"),
        ("CONFIRM_VOICE_DANGER", "声での危険な操作は確認する", "bool",
         "声で頼まれた削除・移動・名前変更・シャットダウンは、実行する前に「はい/いいえ」で確かめます"
         "（近くの人やテレビの音声で勝手に実行されないように）"),
        ("DRY_RUN", "お試しモード", "bool", "実際には操作せず、何をするつもりかだけ表示"),
        ("—", "ブラウザ"),
        ("BROWSER", "使うブラウザ", "choice", "Webページを開くときのブラウザ（Firefox と既定のブラウザでは、ページの中の操作はできません）",
         [("chrome", "Chrome"), ("edge", "Edge"), ("firefox", "Firefox"), ("default", "既定のブラウザ")]),
        ("SEARCH_URL", "検索URL（検索サイトのアドレス）", "str", "{} の部分に検索する言葉が入ります"),
        ("—", "検索結果"),
        ("SAFE_SITES_ONLY", "安全なサイトだけを案内する", "bool",
         "危険（ウイルス・詐欺）と判定されたサイトは、検索結果・画像・リンクに出しません"),
        ("SOURCE_COUNT", "返事に添えるリンクの数", "int", "調べものの返事の下に出す参考ページの数（例: 3）"),
        ("SEARCH_IMAGE_COUNT", "返事に添える画像の枚数", "int", "調べものの返事に添える関連画像の数（0で出さない）"),
        ("IMAGE_COUNT", "画像を探したときの枚数", "int", "「〜の画像を探して」で一覧に出す枚数（例: 30）"),
    ]),
    ("声・音声", [
        ("—", "読み上げ"),
        ("TTS_ENABLED", "返事を声で読み上げる", "bool", "VOICEVOX（無料の読み上げソフト）を使います"),
        ("＊", "voice_picker"),  # 「声を選ぶ」ボタン(キャラ一覧・試聴・ダウンロード)
        ("TTS_SPEED", "話す速さ（1.0 が標準）", "float", "大きいほど速く話します（例: 1.2）"),
        ("READINGS", "読み方の辞書（読み上げの読み方を決める）", "list",
         "「表記=よみ」の形でカンマ（,）区切り。例: 生物=なまもの, 才=さい。"
         "「行っている」など、文の流れで読み方が変わる言葉は自動で読み分けます"),
        ("VOICEVOX_URL", "VOICEVOX の URL（読み上げソフトの接続先）", "str", "通常は変更不要"),
        ("TTS_ENGINE", "読み上げのソフト", "catalog",
         "Kokoro はとても軽く、別のソフトを起動しません。AivisSpeech は声がより自然です（初めて使うときに自動で準備）"),
        ("KOKORO_VOICE", "Kokoro の声", "choice", "読み上げのソフトが Kokoro のときに使う声",
         [("jf_alpha", "女性・はっきり（おすすめ）"), ("jf_gongitsune", "女性・やわらか"), ("jf_nezumi", "女性・かわいい"),
          ("jf_tebukuro", "女性・おちついた"), ("jm_kumo", "男性")]),
        ("AIVIS_URL", "AivisSpeech の URL", "str", "通常は変更不要"),
        ("AIVIS_SPEAKER", "AivisSpeech の声の番号", "int", "0 なら入っている最初の声"),
        ("VISION_MODEL", "画像を理解するAI", "catalog",
         "添付した画像や、「画面に何が出てる？」と聞いたときに使います（初めて使うときにダウンロード）"),
        ("EMBED_MODEL", "意味で探すAI（埋め込みAI）", "catalog",
         "「先月の見積もりの資料どこ？」のように、PCの中の文書を内容で探すときに使います"),
        ("SEMANTIC_FOLDERS", "意味で探すフォルダ", "list", "カンマ（,）区切り。空ならドキュメントとデスクトップ"),
        ("SEARXNG_URL", "SearXNG の URL（自分で動かす検索エンジン）", "str",
         "例: http://localhost:8080 。設定すると調べものに最初に使います（JSON の出力を有効にしてください）。空ならいつもの検索"),
        ("—", "聞き取り"),
        ("VOICE_SPELL_CHECK", "名前の書き方を選んでから付ける", "bool",
         "声でフォルダやファイルを作る・名前を変えるときは、聞き取った名前の書き方（漢字・カタカナ・英語など）の"
         "候補を出して、正しいものを選んでもらいます"),
        ("MIC_DEVICE", "マイク", "mic", "聞き取れないことが多いときは、使っているマイクを選んでください"),
        ("COMMAND_WHISPER_MODEL", "命令の聞き取りに使うAI（声を文字にするAI）", "catalog",
         "話しかけた命令を文字にします。大きいほど正確ですが、返事までが少し遅くなります"),
        ("WHISPER_MODEL", "待機中の聞き取りに使うAI", "catalog", "合図の言葉を待つ間に使うので、軽いものがおすすめ"),
        ("WAKE_ENGINE", "合図の言葉の見つけ方", "catalog",
         "openWakeWord は待機中のCPUがほぼゼロですが、合図の言葉は英語（Hey Jarvis など）か、自分で作ったものになります"),
        ("OWW_MODEL", "openWakeWord の合図の言葉", "str",
         "hey_jarvis / alexa / hey_mycroft のどれか、または自分で作ったモデル（.onnx）のファイルの場所"),
        ("OWW_THRESHOLD", "openWakeWord の感度", "float", "小さいほど反応しやすく、大きいほど聞き間違いが減ります"),
        ("VAD_ENGINE", "声かどうかの判定", "catalog", "Silero VAD は物音や音楽では聞き取りAIを動かさないので、CPUの無駄が減ります"),
        ("VOICE_WORDS", "ユーザー辞書（正しく聞き取ってほしい言葉）", "list",
         "人や会社の名前、よく使う専門用語などをカンマ（,）区切りで。例: 株式会社才, Zealous"),
        ("VOICE_REPLACE", "置き換え（よく間違う言葉の直し方）", "list",
         "「まちがい=正しい」の形でカンマ（,）区切り。例: ゼラス=Zealous, 才コンサル=才コンサルティング"),
        ("WHISPER_DEVICE", "計算に使う装置", "choice", "分からなければ CPU（PCの標準の計算装置）のまま",
         [("cpu", "CPU（どのPCでも動く）"), ("cuda", "CUDA（NVIDIA製GPU：速いが対応GPUが必要）")]),
        ("WHISPER_COMPUTE", "計算の細かさ", "choice", "分からなければ int8（軽い標準の設定）のまま",
         [("int8", "int8（軽い・標準）"), ("float16", "float16（GPU向け）"),
          ("float32", "float32（最も細かい・重い）")]),
        ("LANGUAGE", "言語コード（話す言語・AIが答える言語）", "str",
         "ja = 日本語、en = 英語 など。声の聞き取りと、AIの返事の言葉の両方に使います"),
        ("—", "常時待ち受けの感度"),
        ("VAD_THRESHOLD", "音量しきい値（声とみなす音の大きさ）", "float", "雑音を拾うなら大きく、声を拾わないなら小さく"),
        ("VAD_SILENCE_SEC", "話し終わりの判定（無音の秒数）", "float", "この秒数だけ静かになったら1回の発言として区切る"),
        ("VAD_MAX_SEC", "1回の発言の最大秒数", "float", ""),
        ("VAD_MIN_SEC", "1回の発言の最小秒数", "float", "これより短い音は無視（咳や物音対策）"),
    ]),
    ("AI", [
        ("—", "AIの性格・話し方"),
        ("PERSONA", "AIの性格・話し方", "persona",
         "例:「兄弟のようにタメ口で」「関西弁で明るく」「結論から短く答える」。下の型から選んで書き足すこともできます。"
         "会話の中で「関西弁で話して」「話し方を元に戻して」と言っても変えられます"),
        ("—", "記憶"),
        ("MEMORY", "AIが覚えていること", "lines",
         "1行に1つ。会話で「〜を覚えておいて」と言うと増え、「〜を忘れて」で消えます。ここで直接書き直すこともできます"),
        ("—", "AIの頭脳"),
        ("OLLAMA_MODEL", "会話のAI（ふだん使う頭脳）", "catalog",
         "一覧から選ぶか、Ollama のモデル名を入力。変えるときはサイズを確認してから、保存でダウンロードします"),
        ("OLLAMA_URL", "Ollama の URL（AIを動かすソフトの接続先）", "str", "通常は変更不要"),
        ("OLLAMA_TIMEOUT", "タイムアウト（返事を待つ最大秒数）", "int", ""),
        ("AI_CPU", "AIが使うCPU", "choice",
         "「控えめ」はAIが考えている間もCPUに余裕を残し、ほかのアプリやPC全体が重くなりにくくします"
         "（返事は少しだけ遅くなります）。「すべて」は速さ優先で、考えている間はCPUがほぼ100%になります",
         [("save", "控えめ（おすすめ・PCが重くならない）"), ("full", "すべて使う（速さ優先）")]),
        ("USE_GPU", "GPU（NVIDIA製の画像処理チップ）でAIを速くする", "bool",
         "NVIDIA製GPUがあるPCのみ。ONだと追加で約0.6〜0.9GBをダウンロード。"
         "変更後は「更新・情報」の「部品を準備」で反映"),
        ("—", "動き方"),
        ("MAX_TOOL_STEPS", "1回の命令で行う操作の上限回数", "int", "暴走を防ぐための上限"),
        ("SUMMARIZE_AFTER_TOOL", "操作のあとにAIが返事を考える", "bool", "ONで自然な返事になりますが、少し遅くなります"),
        ("—", "会話の記憶"),
        ("CONTEXT_TURNS", "覚えておくやりとりの数（往復）", "int",
         "同じチャット（スレッド）の中で、「それをもっと詳しく」のように前の話を受けて答えます。"
         "話題を変えるときは「新しいチャット」を押してください。0で記憶しない"),
        ("—", "テクニカルモード（コード・サーバー・IT の相談）"),
        ("TECH_AUTO", "技術的な質問では自動で切り替える", "bool",
         "コードの添削・作成、サーバーやネットワークの設定などを聞かれたら、テクニカルモードにして、コードや手順を添えて"
         "くわしく答えます。チャットの上の「</>」ボタンや「通常モードに戻して」でも切り替えられます"),
        ("TECH_MODEL", "テクニカルモード（コード・IT の相談）で使うAI", "catalog",
         "テクニカルモードのときだけ読み込み、通常モードに戻すとメモリから外します（初めて使うときに自動でダウンロード）"),
        ("—", "会話をすべて参照"),
        ("FULL_CONTEXT", "会話をすべて参照して答える", "bool",
         "同じチャットの最初からのやりとりを、省略せずに参照して答えます（上の「やりとりの数」は使いません）。"
         "長い会話ほど返事が遅くなり、メモリも多く使います"),
        ("FULL_CONTEXT_LIMIT", "　参照する会話の上限（文字数）", "int",
         "会話がこれより長くなったら、古い部分を圧縮します。小さいほど速く、大きいほど細かく覚えています"),
        ("FULL_CONTEXT_COMPRESS", "　上限を超えたら古い部分を要約して使う", "bool",
         "ONなら古いやりとりを要約（圧縮）して参照し続けます。OFFなら上限を超えた古い部分は参照しません"),
    ]),
    ("資料づくり", [
        ("OFFICE_FONT", "書体（フォント）", "choice",
         "資料の文字の書体。「明朝体で」「ポップ体で」のように頼んだときは、そちらを使います。"
         "PCに入っていない書体は使わず、代わりにゴシック体にします（ポップ体・丸ゴシック体は Microsoft Office に付いてくる書体）",
         [("gothic", "ゴシック体（游ゴシック）"), ("mincho", "明朝体（本文は游明朝・見出しはゴシック）"),
          ("kyokasho", "教科書体（UDデジタル教科書体）"), ("pop", "ポップ体（HG創英角ポップ体）"),
          ("maru", "丸ゴシック体（HG丸ゴシックM-PRO）"), ("ud", "UDゴシック（BIZ UDPゴシック・読みやすさ重視）")]),
        ("OFFICE_RESEARCH", "事実を調べてから書き、出典を付ける", "bool",
         "数字・制度・会社名などは、ネットで調べた内容だけを根拠にして書き、参考にしたページを最後に「出典」として載せます。"
         "「今の内容をWordにして」のように会話の内容から作るときは調べません"),
        ("OFFICE_REVIEW", "書いた中身を見直す", "bool",
         "誤字脱字・表記ゆれ・同じ内容の重複・不自然な言い回しを、AIがもう一度読んで直します（少し時間がかかります）"),
        ("OFFICE_IMAGES", "写真を入れる", "bool",
         "使ってよい許可（CC0・パブリックドメイン・CC BY など）が明記された Wikimedia Commons の写真だけを使い、"
         "作者とライセンスを資料に書き添えます"),
    ]),
    ("メール", [
        ("—", "メールの操作（メールアプリを開かずに裏側で行います）"),
        ("MAIL_SERVICE", "使うメール", "choice",
         "「迷惑メールを全部既読にして」「仕事フォルダの名前を〇〇に変えて」などに使います",
         [("auto", "自動（登録したアカウント → 無ければ Outlook）"), ("imap", "IMAP（Gmail・Outlook.com・Yahoo など）"),
          ("outlook", "Outlook（PCに入っている従来版）"),
          ("thunderbird", "Thunderbird の画面を目立たないように操作（設定不要・既読にするだけ）")]),
        ("MAIL_IMAP_HOST", "IMAP サーバー", "str",
         "Gmail: imap.gmail.com / Outlook.com: outlook.office365.com / Yahoo: imap.mail.yahoo.co.jp / "
         "iCloud: imap.mail.me.com。Thunderbird で使っているアカウントなら、その受信サーバーと同じ"),
        ("MAIL_IMAP_PORT", "ポート", "int", "通常は 993"),
        ("MAIL_IMAP_USER", "アカウント（メールアドレス）", "str", ""),
        ("MAIL_IMAP_PASSWORD", "アプリパスワード", "secret",
         "Gmail などは、普段のパスワードではなく「アプリパスワード」を作って入れてください。"
         "このPCのこのユーザーだけが読める形（暗号化）で保存します"),
    ]),
    ("更新・情報", [
        ("—", "アップデート（新しい版への更新）"),
        ("AUTO_UPDATE", "起動時に新しい版を確認", "bool", "見つかると会話ボタンに印が付きます"),
    ]),
]
_ALL = {f[0]: f for _, fs in _SOURCE for f in fs if f[0] not in ("—", "＊")}
# 画面のタブ: 1つのタブに詰め込みすぎないよう、目的ごとに分ける。
#   "—見出し" / "＊部品" / キー。「+」付きのキーは、ふだんは隠す「詳細設定」(押すと開く)
LAYOUT = [
    ("基本", ["—名前と呼びかけ", "AI_NAME", "USER_CALL", "HOME_PLACE", "—起動", "AUTOSTART"]),
    ("見た目", ["—待機中の表示", "PILL_STYLE", "—画面", "UI_THEME", "UI_FONT", "UI_FONT_SCALE",
             "+IME_INLINE", "+SMOOTH_FRAME"]),
    ("マイク", ["＊mic_test", "—マイク", "MIC_DEVICE", "INPUT_MODE", "PTT_ENABLED", "PTT_KEY",
             "—呼びかけ（合図の言葉）", "WAKE_ENABLED", "WAKE_WORDS",
             "—聞き取りの正確さ", "VOICE_WORDS", "VOICE_REPLACE", "VOICE_SPELL_CHECK",
             "+AI_NAME_ALIASES", "+LANGUAGE", "+VAD_THRESHOLD", "+VAD_SILENCE_SEC", "+VAD_MIN_SEC",
             "+VAD_MAX_SEC", "+WHISPER_DEVICE", "+WHISPER_COMPUTE"]),
    ("読み上げ", ["—声", "TTS_ENABLED", "＊voice_picker", "TTS_SPEED", "—読み方", "READINGS", "+VOICEVOX_URL"]),
    ("モデル", ["＊model_presets", "—会話・資料づくり", "OLLAMA_MODEL", "TECH_MODEL",
              "—画像・検索", "VISION_MODEL", "EMBED_MODEL", "SEMANTIC_FOLDERS",
              "—声の聞き取り", "COMMAND_WHISPER_MODEL", "WHISPER_MODEL", "VAD_ENGINE", "WAKE_ENGINE",
              "—読み上げ", "TTS_ENGINE", "KOKORO_VOICE",
              "+OWW_MODEL", "+OWW_THRESHOLD", "+AIVIS_URL", "+AIVIS_SPEAKER"]),
    ("AI", ["—性格・話し方", "PERSONA", "—覚えていること", "MEMORY", "—AIの動かし方", "AI_CPU", "USE_GPU",
            "+OLLAMA_URL", "+OLLAMA_TIMEOUT", "+MAX_TOOL_STEPS", "+SUMMARIZE_AFTER_TOOL"]),
    ("会話", ["—会話の記憶", "CONTEXT_TURNS", "FULL_CONTEXT", "FULL_CONTEXT_LIMIT", "FULL_CONTEXT_COMPRESS",
            "—テクニカルモード（コード・サーバー・IT）", "TECH_AUTO"]),
    ("権限", ["—画面の直接操作", "SCREEN_CONTROL_ENABLED", "SCREEN_ALLOW_CLICK", "SCREEN_ALLOW_TYPE", "SCREEN_ALLOW_KEYS",
            "SCREEN_ALLOW_SCROLL", "SCREEN_ALLOW_WINDOWS", "SCREEN_WAIT_IDLE",
            "—ファイル・フォルダ", "FOLDER_OPS_ENABLED", "FOLDER_DELETE_ENABLED", "—確認", "CONFIRM_VOICE_DANGER",
            "+DRY_RUN"]),
    ("資料づくり", ["—Word・PowerPoint・Excel", "OFFICE_FONT", "OFFICE_RESEARCH", "OFFICE_REVIEW", "OFFICE_IMAGES"]),
    ("ブラウザ・検索", ["—Webページの操作", "WEB_CONTROL_ENABLED", "WEB_CONFIRM_RISKY", "BROWSER",
                 "—調べものの返事", "SAFE_SITES_ONLY", "SOURCE_COUNT", "SEARCH_IMAGE_COUNT", "IMAGE_COUNT",
                 "+SEARCH_URL", "+SEARXNG_URL"]),
    ("メール", ["—メールの操作（メールアプリを開かずに行います）", "MAIL_SERVICE", "MAIL_IMAP_HOST", "MAIL_IMAP_USER",
             "MAIL_IMAP_PASSWORD", "+MAIL_IMAP_PORT"]),
    ("更新・情報", ["—アップデート（新しい版への更新）", "AUTO_UPDATE"]),
]
ADVANCED = {k[1:] for _, keys in LAYOUT for k in keys if k.startswith("+")}
TABS = [(name, [("—", k[1:]) if k.startswith("—") else ("＊", k[1:]) if k.startswith("＊") else _ALL[k.lstrip("+")]
                for k in keys]) for name, keys in LAYOUT]
assert {f[0] for _, fs in TABS for f in fs if f[0] not in ("—", "＊")} == set(_ALL), "設定の項目に漏れ・重複がある"

# 数を「つまみ」で選べる項目: (最小, 最大, 刻み)
SLIDERS = {
    "TTS_SPEED": (0.5, 2.0, 0.05),
    "OWW_THRESHOLD": (0.2, 0.9, 0.05),
    "VAD_THRESHOLD": (0.002, 0.06, 0.001),
    "VAD_SILENCE_SEC": (0.3, 3.0, 0.1),
    "VAD_MIN_SEC": (0.1, 2.0, 0.1),
    "VAD_MAX_SEC": (5, 60, 1),
    "CONTEXT_TURNS": (0, 12, 1),
    "FULL_CONTEXT_LIMIT": (2000, 40000, 1000),
    "SOURCE_COUNT": (0, 8, 1),
    "SEARCH_IMAGE_COUNT": (0, 16, 1),
    "IMAGE_COUNT": (8, 60, 1),
}


def _digits(step):
    text = f"{step:g}"
    return len(text.split(".")[1]) if "." in text else 0


FIELDS = [f for _, fields in TABS for f in fields if f[0] not in ("—", "＊")]
_INFO_TAB = "更新・情報"


def _secret_value(key, raw):
    """パスワード欄: 変わっていなければ保存済みのまま、変わったら暗号化して保存する。"""
    import secret
    raw = raw.strip()
    old = getattr(config, key, "")
    return old if raw == secret.reveal(old) else secret.protect(raw)


def parse(kind, raw):
    """入力値を設定値へ変換する。不正なら ValueError。"""
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "list":
        return [w.strip() for w in raw.replace("、", ",").split(",") if w.strip()]
    if kind == "lines":
        return [w.strip() for w in raw.splitlines() if w.strip()]
    return raw.strip() if isinstance(raw, str) else raw


DEFAULT_LABEL = f"標準（{T.DEFAULT_FONT}）"
_FIRST = ["Yu Gothic UI", "Meiryo UI", "BIZ UDPGothic", "BIZ UDゴシック", "游ゴシック", "メイリオ",
          "Noto Sans JP", "UD デジタル 教科書体 NK-R", "MS UI Gothic"]


def font_choices(widget):
    """このPCのフォント一覧(日本語でよく使うものを先頭に。縦書き用の @ 付きは除く)。"""
    import tkinter.font as tkfont
    names = sorted({n for n in tkfont.families(widget) if not n.startswith("@")}, key=str.lower)
    first = [n for n in _FIRST if n in names]
    return first + [n for n in names if n not in first]


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, on_saved, on_quit, on_check_update, on_pick_voice, on_update, on_clear_history=None):
        super().__init__(master, fg_color=T.BG)
        self._on_saved, self._on_quit, self._on_check_update = on_saved, on_quit, on_check_update
        self._on_pick_voice = on_pick_voice
        self._on_update = on_update
        self._on_clear_history = on_clear_history
        self._vars = {}
        self._choices = {}  # キー -> {表示名: 値}
        self._items = {}  # ページ -> [(部品, 置き方, 検索用の文字 または None(見出し))]
        self._rows = {}   # キー -> 項目のカード
        self.title(f"{config.AI_NAME} 設定")
        self.geometry("680x600")
        self.minsize(580, 540)
        self._adv_open = {}  # ページ -> 詳細設定を開いているか
        self._tag = None     # いま作っている項目の種類(None / "adv" 詳細設定 / "toggle" 詳細設定の開閉)
        self.attributes("-topmost", True)
        if os.name == "nt":  # CTkToplevel は起動直後に既定アイコンへ戻すため少し待って設定
            self.after(250, lambda: self.iconbitmap(shortcut.ICON))
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---- 左: タブ ----
        side = ctk.CTkFrame(self, fg_color=T.SURFACE, corner_radius=0, width=150)
        side.grid(row=0, column=0, rowspan=2, sticky="ns")
        side.grid_propagate(False)
        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(pady=(16, 12), padx=14, anchor="w")
        ctk.CTkLabel(brand, text="", image=icons.emblem(26)).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(brand, text="設定", font=T.font(15, "bold"), text_color=T.TEXT).pack(side="left")
        # 設定の検索(項目名・説明に含まれる言葉で絞り込む)
        self.search = ctk.CTkEntry(side, placeholder_text="設定を検索", height=30, corner_radius=15,
                                   fg_color=T.BG, border_color=T.BORDER, text_color=T.TEXT, font=T.font(11))
        self.search.pack(fill="x", padx=10, pady=(0, 10))
        self.search.bind("<KeyRelease>", lambda e: self._filter(self.search.get()))
        self._tab_btns, self._pages = {}, {}
        for name, _ in TABS:
            b = ctk.CTkButton(side, text=name, anchor="w", height=32, corner_radius=10, font=T.font(12),
                              fg_color="transparent", hover_color=T.BORDER, text_color=T.SUB,
                              command=lambda n=name: self._select(n))
            b.pack(fill="x", padx=10, pady=1)
            self._tab_btns[name] = b
        ctk.CTkLabel(side, text=f"バージョン {VERSION}", font=T.font(10), text_color=T.SUB).pack(
            side="bottom", pady=12)

        # ---- 右: 各タブの中身(開いたタブだけを作る。全部を一度に作ると、開くのが遅く、メモリも多く使う) ----
        self._built, self._fill_source = set(), config.current()
        for name, fields in TABS:
            page = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=T.BORDER)
            page.grid_columnconfigure(0, weight=1)
            self._pages[name] = page

        # ---- 下: 保存 ----
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=1, column=1, sticky="ew", padx=16, pady=(4, 14))
        self._foot = foot
        foot.grid_columnconfigure(0, weight=1)
        self.msg = ctk.CTkLabel(foot, text="", font=T.font(11), text_color=T.DANGER, anchor="w")
        self.msg.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(foot, text="既定に戻す", width=96, height=34, corner_radius=17, fg_color="transparent",
                      border_width=1, border_color=T.BORDER, text_color=T.SUB, hover_color=T.SURFACE,
                      font=T.font(12), command=self._reset).grid(row=0, column=1, padx=6)
        ctk.CTkButton(foot, text="保存", width=96, height=34, corner_radius=17, fg_color=T.ACCENT,
                      hover_color=T.ACCENT_HOVER, font=T.font(12, "bold"),
                      command=self._save).grid(row=0, column=2)

        # 変更した項目を目立たせ、保存していない変更の数を出す
        self._save_btn = self._foot.winfo_children()[-1]
        self._select(TABS[0][0])
        self._refresh_dirty()
        self.protocol("WM_DELETE_WINDOW", self._close)
        # この窓を動かしている間は、常駐の画面の見た目の更新を休ませて、動きを軽くする
        self._where = None
        quiet = getattr(master, "quiet", None)

        def moved(e):
            if e.widget is self and quiet:
                where = (self.winfo_x(), self.winfo_y())
                if where != self._where:
                    self._where = where
                    quiet()
        self.bind("<Configure>", moved, add="+")
        # 日本語入力の変換中の文字を、チャット欄と同じように入力欄の中に表示する
        import ime
        ime.attach_all(self, T.FONT, 15)
        self._ime_ready = True

        # 保存したときのお知らせ(少しだけ出して消える)
        self.toast = ctk.CTkLabel(self, text="✓  保存しました", font=T.font(12, "bold"), text_color="white",
                                  fg_color=T.OK, corner_radius=16, height=34, width=150)

    # ---------------- 画面づくり ----------------
    def _section(self, page, title):
        w = ctk.CTkLabel(page, text=title, font=T.font(12, "bold"), text_color=T.ACCENT, anchor="w")
        kw = dict(fill="x", padx=8, pady=(14, 4))
        w.pack(**kw)
        self._items.setdefault(page, []).append((w, kw, None, self._tag))  # 見出し(検索で、中身が無ければ隠す)

    def _card_row(self, page, search=""):
        row = ctk.CTkFrame(page, fg_color=T.SURFACE, corner_radius=12, border_width=1, border_color=T.SURFACE)
        kw = dict(fill="x", padx=4, pady=3)
        row.pack(**kw)
        row.grid_columnconfigure(0, weight=1)
        self._items.setdefault(page, []).append((row, kw, search.lower(), self._tag))
        return row

    def _build_fields(self, page, fields):
        basic = [f for f in fields if f[0] not in ADVANCED]
        adv = [f for f in fields if f[0] in ADVANCED]
        self._tag = None
        self._add_fields(page, basic)
        if adv:  # ふだんは使わない項目は「詳細設定」にまとめて隠す
            self._tag = "toggle"
            row = self._card_row(page, "")
            row.configure(fg_color="transparent", border_width=0)
            btn = ctk.CTkButton(row, text="", height=30, corner_radius=15, font=T.font(11), fg_color="transparent",
                                border_width=1, border_color=T.BORDER, text_color=T.SUB, hover_color=T.SURFACE,
                                command=lambda p=page: self._toggle_adv(p))
            btn.grid(row=0, column=0, sticky="w", padx=4, pady=(10, 4))
            page._adv_btn, page._adv_count = btn, len(adv)
            self._tag = "adv"
            self._section(page, "詳細設定")
            self._add_fields(page, adv)
            self._tag = None
            self._paint_adv(page)

    def _toggle_adv(self, page):
        self._adv_open[page] = not self._adv_open.get(page, False)
        self._paint_adv(page)
        self._filter(self.search.get())

    def _paint_adv(self, page):
        is_open = self._adv_open.get(page, False)
        page._adv_btn.configure(text="▴  詳細設定を隠す" if is_open else f"▾  詳細設定を表示（{page._adv_count}項目）")

    def _add_fields(self, page, fields):
        for f in fields:
            if f[0] == "—":
                self._section(page, f[1])
                continue
            if f[0] == "＊":
                if f[1] == "mic_test":
                    self._mic_test_card(page)
                elif f[1] == "model_presets":
                    self._preset_card(page)
                else:
                    self._voice_card(page)
                continue
            if f[2] == "mic":  # マイクはこのPCにつながっているものから選ぶ
                import voice
                f = (*f[:2], "choice", f[3],
                     [("", "既定のマイク（Windows の設定）")] + [(n, n) for n in voice.input_devices()])
            key, label, kind, hint = f[:4]
            # スイッチは右端、それ以外の入力欄は説明の下に横幅いっぱいで置く(長い項目名でも切れない)
            switch = kind == "bool"
            wrap = 330 if switch else 400
            row = self._card_row(page, f"{label} {hint} {key}")
            self._rows[key] = row
            ctk.CTkLabel(row, text=label, font=T.font(12), text_color=T.TEXT, anchor="w", justify="left",
                         wraplength=wrap).grid(row=0, column=0, sticky="w", padx=12, pady=(9, 0))
            if hint:
                ctk.CTkLabel(row, text=hint, font=T.font(10), text_color=T.SUB, anchor="w", justify="left",
                             wraplength=wrap).grid(row=1, column=0, sticky="w", padx=12)
            if switch:
                ctl = dict(row=0, column=1, rowspan=2, padx=12, pady=8, sticky="e")
                ctk.CTkFrame(row, height=9, fg_color="transparent").grid(row=2, column=0)
            else:
                ctl = dict(row=2, column=0, columnspan=2, padx=12, pady=(6, 10), sticky="ew")
            if kind == "bool":
                var = ctk.BooleanVar()
                ctk.CTkSwitch(row, text="", variable=var, width=46, progress_color=T.ACCENT).grid(**ctl)
                # スイッチだけでなく、項目のどこを押しても切り替わる
                for w in [row] + [c for c in row.winfo_children() if isinstance(c, ctk.CTkLabel)]:
                    w.bind("<Button-1>", lambda e, v=var: v.set(not v.get()), add="+")
                    w.configure(cursor="hand2")
            elif kind in ("float", "int") and key in SLIDERS:
                var = ctk.StringVar()
                lo, hi, step = SLIDERS[key]
                box = ctk.CTkFrame(row, fg_color="transparent")
                box.grid(**ctl)
                box.grid_columnconfigure(0, weight=1)
                value = ctk.CTkLabel(box, text="", font=T.font(11, "bold"), text_color=T.TEXT, width=48, anchor="e")
                value.grid(row=0, column=1, padx=(8, 0))
                fmt = (lambda x: str(int(round(x)))) if kind == "int" else (lambda x, st=step: f"{round(x / st) * st:.{_digits(st)}f}")
                slider = ctk.CTkSlider(box, from_=lo, to=hi, number_of_steps=int(round((hi - lo) / step)),
                                       progress_color=T.ACCENT, button_color=T.ACCENT_LIGHT,
                                       button_hover_color=T.ACCENT, command=lambda x, v=var, f=fmt: v.set(f(x)))
                slider.grid(row=0, column=0, sticky="ew")

                def show(*_, v=var, s_=slider, lab=value, lo=lo, hi=hi):  # 値が変わったら、つまみと数字も合わせる
                    try:
                        x = float(v.get())
                    except ValueError:
                        return
                    lab.configure(text=v.get())
                    s_.set(min(hi, max(lo, x)))
                var.trace_add("write", show)
            elif kind == "catalog":
                var = self._catalog_field(row, key, ctl)
            elif kind == "model":
                var = ctk.StringVar()
                ctk.CTkComboBox(row, values=[models.label(k[0]) for k in models.KNOWN], variable=var,
                                fg_color=T.BG, border_color=T.BORDER, button_color=T.BG,
                                button_hover_color=T.BORDER, dropdown_fg_color=T.SURFACE, dropdown_text_color=T.TEXT, text_color=T.TEXT,
                                  font=T.font(11)).grid(**ctl)
                # 選んだモデルの特徴と注意点
                info = ctk.CTkFrame(row, fg_color=T.BG, corner_radius=10)
                info.grid(row=3, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
                info.grid_columnconfigure(1, weight=1)
                labels = {}
                for r, (name, color) in enumerate((("特徴", T.OK), ("注意", T.WARN))):
                    ctk.CTkLabel(info, text=name, font=T.font(10, "bold"), text_color=color, width=34,
                                 anchor="nw").grid(row=r, column=0, sticky="nw", padx=(10, 4), pady=(8 if r == 0 else 2, 2))
                    labels[name] = ctk.CTkLabel(info, text="", font=T.font(10), text_color=T.TEXT, anchor="w",
                                                justify="left", wraplength=300)
                    labels[name].grid(row=r, column=1, sticky="ew", padx=(0, 10), pady=(8 if r == 0 else 2, 2))
                ctk.CTkFrame(info, height=6, width=1, fg_color="transparent").grid(row=2, column=0)
                # 枠の幅に合わせて折り返す(長い説明でも切れない)
                info.bind("<Configure>", lambda e, lab=labels, i=info: [
                    l.configure(wraplength=max(160, int(e.width / i._get_widget_scaling()) - 70)) for l in lab.values()],
                    add="+")

                def describe(*_, v=var, lab=labels):
                    d = models.details(models.name_of(v.get()))
                    good, warn = d if d else ("一覧にないモデルです。Ollama の名前（例: gemma3:4b）を入力できます。",
                                              "保存のときに大きさを調べてお知らせします。日本語やPC操作に対応していないモデルもあります。")
                    lab["特徴"].configure(text=good)
                    lab["注意"].configure(text=warn)
                var.trace_add("write", describe)
            elif kind == "lines":
                var = ctk.StringVar()
                box = ctk.CTkTextbox(row, height=86, fg_color=T.BG, border_color=T.BORDER, border_width=1,
                                     font=T.font(11), text_color=T.TEXT, wrap="char")
                box.grid(**ctl)

                def sync_lines(*_, b=box, v=var):
                    if b.get("1.0", "end-1c") != v.get():
                        b.delete("1.0", "end")
                        b.insert("1.0", v.get())
                var.trace_add("write", sync_lines)
                box.bind("<KeyRelease>", lambda e, b=box, v=var: v.set(b.get("1.0", "end-1c")), add="+")
            elif kind == "persona":
                import persona
                var = ctk.StringVar()
                box = ctk.CTkTextbox(row, height=74, fg_color=T.BG, border_color=T.BORDER, border_width=1,
                                     font=T.font(11), text_color=T.TEXT, wrap="char")
                box.grid(**ctl)
                # 入力欄の中身を、ほかの欄と同じように var で読み書きできるようにする
                def sync(*_, b=box, v=var):
                    if b.get("1.0", "end-1c") != v.get():
                        b.delete("1.0", "end")
                        b.insert("1.0", v.get())
                var.trace_add("write", sync)
                box.bind("<KeyRelease>", lambda e, b=box, v=var: v.set(b.get("1.0", "end-1c")), add="+")
                chips = ctk.CTkFrame(row, fg_color="transparent")
                chips.grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10))
                for i, (name, text) in enumerate(persona.PRESETS):
                    ctk.CTkButton(chips, text=name, height=26, width=10, corner_radius=13, font=T.font(10),
                                  fg_color="transparent", border_width=1, border_color=T.BORDER,
                                  hover_color=T.SURFACE, text_color=T.TEXT,
                                  command=lambda t=text, v=var: v.set(t)).grid(row=i // 3, column=i % 3,
                                                                                padx=2, pady=2, sticky="w")
            elif kind == "font":
                var = ctk.StringVar()
                fonts = font_choices(self)
                self._choices[key] = {DEFAULT_LABEL: "", **{n: n for n in fonts}}
                box = ctk.CTkComboBox(row, values=[DEFAULT_LABEL] + fonts, variable=var, fg_color=T.BG,
                                      border_color=T.BORDER, button_color=T.BG, button_hover_color=T.BORDER,
                                      dropdown_fg_color=T.SURFACE, font=T.font(11), text_color=T.TEXT)
                box.grid(**ctl)
                preview = ctk.CTkLabel(row, text="", text_color=T.TEXT, anchor="w")
                preview.grid(row=3, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 10))

                def show(*_, v=var, p=preview):  # 選んだフォントの見本
                    name = self._choices["UI_FONT"].get(v.get(), v.get()) or T.DEFAULT_FONT
                    p.configure(text="見本: こんにちは、Zealous です。Aa 123", font=(name, 13))
                var.trace_add("write", show)
            elif kind == "choice":
                var = ctk.StringVar()
                options = [lbl for _, lbl in f[4]]
                self._choices[key] = {lbl: val for val, lbl in f[4]}
                ctk.CTkOptionMenu(row, values=options, variable=var, dynamic_resizing=False,
                                  fg_color=T.BG, button_color=T.BG, button_hover_color=T.BORDER,
                                  dropdown_fg_color=T.SURFACE, dropdown_text_color=T.TEXT, text_color=T.TEXT,
                                  font=T.font(11)).grid(**ctl)
            else:
                var = ctk.StringVar()
                ctk.CTkEntry(row, textvariable=var, fg_color=T.BG, border_color=T.BORDER, show="•" if kind == "secret" else "",
                             font=T.font(11), text_color=T.TEXT).grid(**ctl)
            self._vars[key] = (kind, var)

    def _action(self, page, title, hint, text, command, danger=False):
        row = self._card_row(page, f"{title} {hint}")
        ctk.CTkLabel(row, text=title, font=T.font(12), text_color=T.TEXT, anchor="w").grid(
            row=0, column=0, sticky="w", padx=12, pady=(8, 0))
        ctk.CTkLabel(row, text=hint, font=T.font(10), text_color=T.SUB, anchor="w", justify="left",
                     wraplength=250).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))
        ctk.CTkButton(row, text=text, width=120, height=30, corner_radius=15, font=T.font(11),
                      fg_color="transparent", border_width=1, border_color=T.DANGER if danger else T.ACCENT,
                      text_color=T.DANGER if danger else T.TEXT, hover_color=T.BORDER,
                      command=command).grid(row=0, column=1, rowspan=2, padx=12)
        return row

    def _build_info(self, page):
        # ---- アップデート: 確認して、新しい版があればここから更新できる ----
        row = self._card_row(page, "アップデート 更新 バージョン")
        ctk.CTkLabel(row, text="アップデート", font=T.font(12), text_color=T.TEXT, anchor="w").grid(
            row=0, column=0, sticky="w", padx=12, pady=(9, 0))
        self.upd_status = ctk.CTkLabel(row, text=f"現在のバージョン: {VERSION}", font=T.font(10),
                                       text_color=T.SUB, anchor="w", justify="left", wraplength=300)
        # 結果の文が長くても途切れないよう、文はカードの幅いっぱいに折り返し、ボタンはその下に置く
        self.upd_status.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 6))
        row.grid_columnconfigure(0, weight=1)
        row.bind("<Configure>", lambda e: self.upd_status.configure(
            wraplength=max(200, int(e.width / self.upd_status._get_widget_scaling()) - 30)), add="+")
        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 10))
        self.upd_check = ctk.CTkButton(btns, text="今すぐ確認", width=100, height=30, corner_radius=15,
                                       font=T.font(11), fg_color="transparent", border_width=1,
                                       border_color=T.ACCENT, text_color=T.TEXT, hover_color=T.BORDER,
                                       command=self._check_update)
        self.upd_check.pack(side="left")
        self.upd_go = ctk.CTkButton(btns, text="アップデート", width=110, height=30, corner_radius=15,
                                    font=T.font(11, "bold"), fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER)
        self._section(page, "部品（AI・音声のソフト）")
        self._action(page, "動作確認", "AIを動かすソフト（Ollama）と読み上げソフト（VOICEVOX）が動いているか",
                     "確認する", self._check)
        self._action(page, "部品を準備", "AIモデルを変えたときや、部品が壊れたときに再ダウンロード",
                     "準備画面を開く", self._open_setup)
        self.svc = ctk.CTkLabel(page, text="", font=T.font(11), text_color=T.CYAN, anchor="w", justify="left",
                                wraplength=380)
        self.svc.pack(fill="x", padx=12, pady=(6, 0))
        self._section(page, "その他")
        self._action(page, f"{config.AI_NAME} を終了", "常駐をやめます（次回はアイコンから起動）", "終了する",
                     self._on_quit)
        self._action(page, "会話の履歴を消す", "これまでのチャット・音声会話の記録と、動きの記録をすべて消します",
                     "すべて消す", self._clear_history, danger=True)
        self._action(page, "アンインストール（削除）", "Zealous をこのPCから取り除きます", "アンインストール",
                     self._uninstall, danger=True)

    # ---------------- モデル(種類ごとの選択と、おすすめ構成) ----------------
    TIER_COLORS = {"ok": T.OK, "warn": T.WARN, "danger": T.DANGER}

    def _catalog_field(self, row, key, ctl):
        """モデルのプルダウン: 1行で「メモリの低・中・高｜名前｜大きさ｜使うメモリ｜得意なこと」。
        左に低・中・高の札、下に得意なことと主な用途。Ollama のモデルは名前を入力してもよい。"""
        var = ctk.StringVar()
        items = models.CATALOG[key]
        self._choices[key] = {models.catalog_label(e): e[0] for e in items}
        box = ctk.CTkFrame(row, fg_color="transparent")
        box.grid(**ctl)
        box.grid_columnconfigure(1, weight=1)
        badge = ctk.CTkLabel(box, text="", width=34, height=26, corner_radius=8, font=T.font(11, "bold"),
                             text_color="white", fg_color=T.OK)
        badge.grid(row=0, column=0, padx=(0, 8))
        common = dict(values=list(self._choices[key]), variable=var, fg_color=T.BG, button_color=T.BG,
                      button_hover_color=T.BORDER, dropdown_fg_color=T.SURFACE, dropdown_text_color=T.TEXT,
                      text_color=T.TEXT, font=T.font(11), dropdown_font=T.font(11))
        if key in models.FREE_INPUT:
            ctk.CTkComboBox(box, border_color=T.BORDER, **common).grid(row=0, column=1, sticky="ew")
        else:
            ctk.CTkOptionMenu(box, dynamic_resizing=False, **common).grid(row=0, column=1, sticky="ew")
        info = ctk.CTkLabel(row, text="", font=T.font(10), text_color=T.SUB, anchor="w", justify="left", wraplength=420)
        info.grid(row=3, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 10))

        def show(*_):
            e = self._choices[key].get(var.get())
            e = models.entry(key, e) if e is not None else None
            if e:
                t, color = models.tier(e[3])
                badge.configure(text=t, fg_color=self.TIER_COLORS[color])
                info.configure(text=f"得意なこと: {e[4]}　／　主な用途: {e[5]}　／　ダウンロード: {e[2]}")
            else:
                badge.configure(text="？", fg_color=T.BORDER)
                info.configure(text="一覧にないモデルです。保存のときに大きさを調べてお知らせします")
            self._update_meter()
        var.trace_add("write", show)
        return var

    def _preset_card(self, page):
        """おすすめ構成のボタン(このPCに合うものに★)と、使うメモリの目安のメーター。"""
        total = models.memory_gb()[0]
        rec = models.recommended_preset(total) if total else "standard"
        card = ctk.CTkFrame(page, fg_color=T.SURFACE, corner_radius=12)
        kw = dict(fill="x", padx=4, pady=(6, 3))
        card.pack(**kw)
        self._items.setdefault(page, []).append((card, kw, "おすすめ構成 プリセット メモリ", None))
        ctk.CTkLabel(card, text="おすすめ構成", font=T.font(13, "bold"), text_color=T.TEXT, anchor="w").pack(
            anchor="w", padx=14, pady=(12, 0))
        ctk.CTkLabel(card, text=(f"このPCのメモリ: {total:.0f}GB。" if total else "") +
                     "押すと下の欄にまとめて入ります。そこから1つずつ変えて、保存で決まります。",
                     font=T.font(10), text_color=T.SUB, anchor="w", justify="left", wraplength=440).pack(
            anchor="w", padx=14, pady=(2, 8))
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=10)
        for i, (pid, name, desc, _, values) in enumerate(models.PRESETS):
            grid.grid_columnconfigure(i % 2, weight=1)
            mine = pid == rec
            btn = ctk.CTkButton(grid, text=f"{'★ ' if mine else ''}{name}\n{desc}・約{models.estimate(values):g}GB",
                                height=52, corner_radius=12, font=T.font(11, "bold" if mine else "normal"),
                                fg_color=T.ACCENT if mine else T.BG, hover_color=T.ACCENT_HOVER if mine else T.BORDER,
                                text_color="white" if mine else T.TEXT, border_width=0 if mine else 1,
                                border_color=T.BORDER, command=lambda v=values: self._apply_preset(v))
            btn.grid(row=i // 2, column=i % 2, sticky="ew", padx=4, pady=4)
        # 使うメモリの目安(選んでいる構成の合計)
        meter = ctk.CTkFrame(card, fg_color="transparent")
        meter.pack(fill="x", padx=14, pady=(8, 4))
        meter.grid_columnconfigure(0, weight=1)
        self._meter_text = ctk.CTkLabel(meter, text="", font=T.font(11, "bold"), text_color=T.TEXT, anchor="w")
        self._meter_text.grid(row=0, column=0, sticky="w")
        self._meter_bar = ctk.CTkProgressBar(meter, height=10, corner_radius=5, progress_color=T.OK, fg_color=T.BG)
        self._meter_bar.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        legend = ctk.CTkFrame(card, fg_color="transparent")
        legend.pack(anchor="w", padx=12, pady=(4, 12))
        for t, color, text in (("低", T.OK, "メモリ2GBまで"), ("中", T.WARN, "6GBまで"), ("高", T.DANGER, "6GBより多い")):
            ctk.CTkLabel(legend, text=t, width=26, height=20, corner_radius=6, fg_color=color, text_color="white",
                         font=T.font(10, "bold")).pack(side="left", padx=(2, 4))
            ctk.CTkLabel(legend, text=text, font=T.font(10), text_color=T.SUB).pack(side="left", padx=(0, 10))
        self._pc_total = total

    def _apply_preset(self, values):
        """おすすめ構成を欄に入れる(保存はまだ。ここから好きに変えられる)。"""
        for key, value in values.items():
            if key in self._vars:
                e = models.entry(key, value)
                self._vars[key][1].set(models.catalog_label(e) if e else value)
        self.msg.configure(text="おすすめ構成を入れました。必要なら変えてから「保存」を押してください", text_color=T.SUB)

    def _update_meter(self):
        """選んでいる構成で使うメモリの目安を、このPCのメモリと比べて見せる。"""
        if not getattr(self, "_meter_bar", None) or not self._meter_bar.winfo_exists():
            return
        values = {}
        for key in models.CATALOG:
            if key in self._vars:
                try:
                    values[key] = self._value(key)
                except (ValueError, KeyError):
                    pass
            else:
                values[key] = getattr(config, key, "")
        need = models.estimate(values)
        total = self._pc_total or 16
        share = need / total
        t, color = ("低", "ok") if share <= 0.4 else ("中", "warn") if share <= 0.7 else ("高", "danger")
        self._meter_bar.configure(progress_color=self.TIER_COLORS[color])
        self._meter_bar.set(min(1.0, share))
        self._meter_text.configure(
            text=f"使うメモリの目安: 約{need:g}GB（このPCの{share * 100:.0f}%・負担 {t}）" +
                 ("　メモリが足りない可能性があります" if share > 0.85 else ""))

    def _build_page(self, name):
        """タブの中身を、初めて開いたときに作る。作ったら、今の値を入れ、変更の見張りを付ける。"""
        if name in self._built:
            return False
        self._built.add(name)
        page = self._pages[name]
        before = set(self._vars)
        self._build_fields(page, dict(TABS)[name])
        if name == _INFO_TAB:
            self._build_info(page)
        new = {k: v for k, v in self._vars.items() if k not in before}
        self._fill_vars(new, self._fill_source)
        for _, var in new.values():
            var.trace_add("write", lambda *_: self._dirty_later())
        if getattr(self, "_ime_ready", False):
            import ime
            ime.attach_all(page, T.FONT, 15)
        return True

    def _select(self, name):
        if self._build_page(name):
            self._filter(self.search.get())  # 詳細設定は閉じた状態で見せる(検索中なら絞り込む)
        for n, page in self._pages.items():
            page.grid_forget()
            active = n == name
            self._tab_btns[n].configure(fg_color=T.ACCENT if active else "transparent",
                                        text_color="white" if active else T.SUB,
                                        hover_color=T.ACCENT_HOVER if active else T.BORDER)
        self._pages[name].grid(row=0, column=1, sticky="nsew", padx=(12, 8), pady=(12, 0))

    # ---------------- 部品・更新(別スレッドで実行し画面を止めない) ----------------
    def _bg(self, job):
        def run():
            try:
                job()
            except Exception as e:
                self._show(f"エラー: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _check_update(self):
        self.upd_go.pack_forget()
        self._upd_text("確認中…", T.SUB)

        def report(msg, info):  # 裏のスレッドから届く
            self.after(0, lambda: self._update_result(msg, info))
        self._on_check_update(report)

    def _update_result(self, msg, info):
        if not self.winfo_exists():
            return
        self._upd_text(msg, T.WARN if msg.startswith("確認できません") else T.CYAN if info else T.OK)
        if info:
            self.upd_go.configure(text=f"v{info['version']} に更新", state="normal",
                                  command=lambda: self._run_update(info))
            self.upd_go.pack(side="left", padx=(6, 0))

    def _run_update(self, info):
        self.upd_go.configure(state="disabled", text="更新中…")
        self.upd_check.configure(state="disabled")

        def progress(text, failed=False):
            self._upd_text(text, T.DANGER if failed else T.CYAN)
            if failed:
                self.upd_go.configure(state="normal", text="もう一度")
                self.upd_check.configure(state="normal")
        self._on_update(info, progress)

    def _upd_text(self, text, color):
        if self.winfo_exists():
            self.upd_status.configure(text=text, text_color=color)

    def _show(self, text):
        self.after(0, lambda: self.winfo_exists() and self.svc.configure(text=text))

    def _check(self):
        self._select(_INFO_TAB)
        self._show("確認中…")
        self._bg(lambda: self._show(services.check_ollama()[2] + "\n" + services.check_voicevox()[1]))

    def _open_setup(self):
        """セットアップ画面を開き、終わったら本体を再起動する。"""
        import subprocess
        subprocess.Popen(shortcut.command("--setup"), cwd=shortcut.HERE)
        self._on_quit()

    # ---------------- 変更の管理 ----------------
    def _catalog_value(self, key, text):
        """プルダウンの表示 → 保存する値(一覧にない名前は、入力されたまま)。"""
        if text in self._choices[key]:
            return self._choices[key][text]
        if key in models.FREE_INPUT:
            return text.strip()
        raise ValueError

    def _value(self, key):
        """入力欄の値を設定値にする(不正なら ValueError / KeyError)。"""
        kind, var = self._vars[key]
        if kind == "catalog":
            return self._catalog_value(key, var.get())
        if kind == "model":
            name = models.name_of(var.get())
            if not name:
                raise ValueError
            return name
        if kind == "choice":
            return self._choices[key][var.get()]
        if kind == "font":
            return self._choices[key].get(var.get(), var.get().strip())
        if kind == "secret":
            return _secret_value(key, var.get())
        return parse(kind, var.get())

    def _dirty(self):
        out = []
        for key in self._vars:
            try:
                if self._value(key) != getattr(config, key):
                    out.append(key)
            except (ValueError, KeyError):
                out.append(key)
        return out

    def _dirty_later(self):
        if not getattr(self, "_dirty_job", None):
            self._dirty_job = self.after(80, self._refresh_dirty)

    def _refresh_dirty(self):
        self._dirty_job = None
        if not self.winfo_exists():
            return
        dirty = set(self._dirty())
        for key, row in self._rows.items():
            row.configure(border_color=T.ACCENT if key in dirty else T.SURFACE)
        for name, fields in TABS:
            n = sum(1 for f in fields if f[0] in dirty)
            base = self._tab_btns[name].cget("text").split("  ")[0]
            self._tab_btns[name].configure(text=f"{base}  ●" if n else base)
        self._save_btn.configure(text=f"保存（{len(dirty)}）" if dirty else "保存")
        if dirty:
            self.msg.configure(text=f"● 保存していない変更が {len(dirty)} 件あります", text_color=T.WARN)
        elif self.msg.cget("text").startswith("●"):
            self.msg.configure(text="")

    def _close(self):
        """保存していない変更があれば、閉じる前に確かめる。"""
        if self._dirty():
            import tkinter.messagebox as mb
            answer = mb.askyesnocancel("設定", "保存していない変更があります。保存してから閉じますか？", parent=self)
            if answer is None:
                return
            if answer:
                self._save()
                if self._dirty():  # 入力に誤りがあって保存できなかった
                    return
        self.destroy()

    # ---------------- 検索 ----------------
    def _filter(self, query):
        """項目名・説明に query を含む項目だけを見せる。空なら元に戻す。"""
        q = query.strip().lower()
        if q:  # 検索はすべてのタブが対象
            for n in self._pages:
                self._build_page(n)
        first = None
        for name, page in self._pages.items():
            items = self._items.get(page, [])
            is_open = self._adv_open.get(page, False)
            # 項目: 検索に合うもの。詳細設定は、開いているときか検索中だけ。開閉のボタンは検索中は隠す
            visible = [None if text is None else (not q) if tag == "toggle" else
                       (not q or q in text) and (bool(q) or tag != "adv" or is_open)
                       for w, kw, text, tag in items]
            for i, (w, kw, text, tag) in enumerate(items):
                if text is None:  # 見出し: 次の見出しまでに見える項目があれば見せる
                    rest = []
                    for j in range(i + 1, len(items)):
                        if items[j][2] is None or items[j][3] == "toggle":
                            break
                        rest.append(visible[j])
                    visible[i] = any(rest)
            for w, kw, _, _ in items:
                w.pack_forget()
            for (w, kw, _, _), show in zip(items, visible):
                if show:
                    w.pack(**kw)
            hits = sum(1 for (w, kw, t, tag), show in zip(items, visible) if show and t is not None and tag != "toggle")
            base = self._tab_btns[name].cget("text").split("（")[0].split("  ")[0]
            self._tab_btns[name].configure(text=f"{base}（{hits}）" if q else base,
                                           state="normal" if (hits or not q) else "disabled")
            if q and hits and first is None:
                first = name
        if q and first:
            self._select(first)
        elif not q:
            self._refresh_dirty()

    def _show_toast(self):
        if not self.winfo_exists():
            return
        self.toast.place(in_=self._foot, relx=0.5, y=-12, anchor="s")  # 設定の中身の真ん中、保存ボタンの上
        self.toast.lift()
        if getattr(self, "_toast_job", None):
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(1800, lambda: self.winfo_exists() and self.toast.place_forget())

    def _clear_history(self):
        import tkinter.messagebox as mb
        if not mb.askyesno("会話の履歴を消す", "これまでの会話の記録をすべて消します。元には戻せません。よろしいですか？",
                           parent=self):
            return
        import threads
        threads.delete_all()
        for name in ("trace.log", "trace.log.old"):  # 動きの記録も消す
            try:
                os.remove(os.path.join(config.APP_DIR, name))
            except OSError:
                pass
        if self._on_clear_history:
            self._on_clear_history()
        self._show("会話の履歴を消しました")

    def _uninstall(self):
        import subprocess
        exe = shortcut.uninstaller()
        if not exe:
            self._show("ソース版はアンインストール不要です（フォルダを削除してください）")
            return
        subprocess.Popen([exe], cwd=shortcut.HERE)
        self._on_quit()

    def _mic_test_card(self, page):
        """マイクテスト: 5秒録音して、音の大きさ・雑音・聞き取れた言葉を見せ、録音した声を再生する。"""
        row = self._card_row(page, "マイクテスト ボイスチェック 録音 再生 音量 感度 聞き取り")
        ctk.CTkLabel(row, text="マイクテスト（ボイスチェック）", font=T.font(12), text_color=T.TEXT, anchor="w").grid(
            row=0, column=0, sticky="w", padx=12, pady=(9, 0))
        ctk.CTkLabel(row, text="「テスト開始」を押して、5秒ほど普段どおりに話してください。声の大きさと雑音を確かめ、"
                               "聞き取れた言葉を表示して、録音した声を再生します（下で選んでいるマイクを使います）",
                     font=T.font(10), text_color=T.SUB, anchor="w", justify="left", wraplength=440).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=12)
        self.mic_btn = ctk.CTkButton(row, text="テスト開始", width=110, height=32, corner_radius=16, fg_color=T.ACCENT,
                                     hover_color=T.ACCENT_HOVER, font=T.font(12, "bold"), command=self._mic_test)
        self.mic_btn.grid(row=0, column=1, padx=12, pady=(8, 2))
        self.mic_bar = ctk.CTkProgressBar(row, height=10, corner_radius=5, progress_color=T.OK, fg_color=T.BG)
        self.mic_bar.set(0)
        self.mic_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(8, 2))
        self.mic_msg = ctk.CTkLabel(row, text="", font=T.font(11), text_color=T.TEXT, anchor="w", justify="left",
                                    wraplength=440)
        self.mic_msg.grid(row=3, column=0, columnspan=2, sticky="w", padx=12, pady=(2, 4))
        self.mic_fix = ctk.CTkButton(row, text="", height=28, corner_radius=14, font=T.font(10), fg_color="transparent",
                                     border_width=1, border_color=T.ACCENT, text_color=T.TEXT, hover_color=T.BORDER)
        self._mic_level, self._mic_busy = 0.0, False

    def _mic_test(self):
        if self._mic_busy:
            return
        import mictest
        try:
            device = self._value("MIC_DEVICE")
        except (KeyError, ValueError):
            device = config.MIC_DEVICE
        self._mic_busy = True
        self.mic_btn.configure(state="disabled", text="録音中…")
        self.mic_fix.grid_forget()
        self.mic_msg.configure(text="話してください（5秒）", text_color=T.TEXT)
        voice = getattr(self.master, "voice", None)
        listen = voice.should_listen if voice else None
        if voice:
            voice.should_listen = lambda: False  # テスト中は、ふだんの聞き取りを休む(命令として扱わない)

        def level(v):
            self._mic_level = max(v, self._mic_level * 0.8)

        import queue
        self._mic_q = queue.Queue()

        def meter():  # 画面のスレッドで: 音の大きさの表示と、録音側から届いた画面の変更
            if not self.winfo_exists():
                return
            while not self._mic_q.empty():
                self._mic_q.get()()
            if self._mic_busy:
                self.mic_bar.set(self._mic_level)
                self._mic_level *= 0.85
                self.after(50, meter)
        meter()

        def run():
            try:
                audio = mictest.record(device, 5.0, level)
                result = mictest.analyze(audio)
                self._ui(lambda: self.mic_msg.configure(text=f"{result['advice']}。録音した声を再生しています…"))
                self._ui(lambda: self.mic_btn.configure(text="再生中…"))
                mictest.play(audio)
                self._ui(lambda: self.mic_msg.configure(text=f"{result['advice']}。聞き取りを確かめています…"))
                self._ui(lambda: self.mic_btn.configure(text="確認中…"))
                text = mictest.transcribe(audio) if result["peak"] >= 0.01 else ""
                self._ui(lambda: self._mic_done(result, text))
            except Exception as e:
                err = str(e)
                self._ui(lambda: self._mic_done(None, f"マイクを使えませんでした（{err[:80]}）"))
            finally:
                if voice:
                    voice.should_listen = listen
        threading.Thread(target=run, daemon=True).start()

    def _ui(self, fn):
        """別のスレッドから、画面の部品を変える(画面のスレッドで、順に行う)。"""
        self._mic_q.put(fn)

    def _mic_done(self, result, text):
        import mictest
        self._mic_busy = False
        self.mic_bar.set(0)
        self.mic_btn.configure(state="normal", text="もう一度テスト")
        if result is None:
            self.mic_msg.configure(text=text, text_color=T.DANGER)
            return
        good = result["advice"] == "よく聞こえています"
        heard = f"聞き取れた言葉:「{text}」" if text else "言葉は聞き取れませんでした"
        self.mic_msg.configure(
            text=f"{'✓ ' if good else '⚠ '}{result['advice']}\n{heard}\n"
                 f"声の大きさ {result['voice'] * 100:.1f} ／ 雑音 {result['noise'] * 100:.1f}",
            text_color=T.TEXT if good else T.DANGER)
        t = result["threshold"]
        if t and result["peak"] >= 0.01 and not mictest.threshold_ok(result) and "VAD_THRESHOLD" in self._vars:
            def apply():
                self._vars["VAD_THRESHOLD"][1].set(str(t))
                self.mic_fix.grid_forget()
                self.mic_msg.configure(text=self.mic_msg.cget("text") + f"\n感度を {t} にしました（保存で確定）")
            self.mic_fix.configure(text=f"待ち受けの感度を、このマイクに合わせる（{t}）", command=apply)
            self.mic_fix.grid(row=4, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 10))

    def _voice_card(self, page):
        """現在の声と「声を選ぶ」ボタン。キャラ一覧の画面で試聴・ダウンロードする。"""
        row = self._card_row(page, "声 キャラクター VOICEVOX 読み上げ 選ぶ")
        ctk.CTkLabel(row, text="声", font=T.font(12), text_color=T.TEXT, anchor="w").grid(
            row=0, column=0, sticky="w", padx=12, pady=(9, 0))
        self.voice_now = ctk.CTkLabel(row, text="", font=T.font(11), text_color=T.CYAN, anchor="w")
        self.voice_now.grid(row=1, column=0, sticky="w", padx=12)
        ctk.CTkLabel(row, text="キャラクターの一覧から試聴して選べます。選んだ声のモデル（約55MB）だけを"
                               "ダウンロードし、使わなくなった声は削除します。",
                     font=T.font(10), text_color=T.SUB, anchor="w", justify="left", wraplength=330).grid(
            row=2, column=0, sticky="w", padx=12, pady=(2, 10))
        ctk.CTkButton(row, text="声を選ぶ", width=110, height=34, corner_radius=17, fg_color=T.ACCENT,
                      hover_color=T.ACCENT_HOVER, font=T.font(12, "bold"),
                      command=lambda: self._on_pick_voice(self.refresh_voice)).grid(
            row=0, column=1, rowspan=3, padx=12)
        self.refresh_voice()

    def refresh_voice(self):
        if not hasattr(self, "voice_now"):
            return
        cur = next((v for v in voicevox.cached_catalog() if v["id"] == config.VOICEVOX_SPEAKER), None)
        if self.winfo_exists():
            self.voice_now.configure(text=f"現在の声: {voicevox.label(cur) if cur else config.VOICEVOX_SPEAKER}")

    # ---------------- 値の読み書き ----------------
    def _fill(self, values):
        self._fill_source = values  # まだ作っていないタブも、作るときにこの値を入れる
        self._fill_vars(self._vars, values)

    def _fill_vars(self, vars_, values):
        for key, (kind, var) in vars_.items():
            v = values[key]
            if kind == "model":
                var.set(models.label(v))
            elif kind == "catalog":
                e = models.entry(key, v)
                var.set(models.catalog_label(e) if e else v)
            elif kind == "font":
                var.set(v or DEFAULT_LABEL)
            elif kind == "choice":
                # 選択肢に無い値(外したマイクなど)は先頭の選択肢にする
                var.set(next((lbl for lbl, val in self._choices[key].items() if val == v),
                             next(iter(self._choices[key]))))
            elif kind == "bool":
                var.set(v)
            elif kind == "lines":
                var.set("\n".join(v))
            elif kind == "secret":
                import secret
                var.set(secret.reveal(v))
            else:
                var.set(", ".join(v) if kind == "list" else str(v))

    def _reset(self):
        self._fill(config.DEFAULTS)
        self.msg.configure(text="既定値を表示しています（保存で確定）", text_color=T.SUB)

    def _save(self):
        # まだ開いていないタブの項目は、表示している値(今の設定、または「既定に戻す」の値)のまま
        changes = {f[0]: self._fill_source[f[0]] for f in FIELDS if f[0] in self._fill_source}
        for key, (kind, var) in self._vars.items():
            try:
                if kind == "catalog":
                    changes[key] = self._catalog_value(key, var.get())
                elif kind == "model":
                    changes[key] = models.name_of(var.get())
                    if not changes[key]:
                        raise ValueError
                elif kind == "choice":
                    changes[key] = self._choices[key][var.get()]
                elif kind == "font":
                    changes[key] = self._choices[key].get(var.get(), var.get().strip())
                elif kind == "secret":
                    changes[key] = _secret_value(key, var.get())
                else:
                    changes[key] = parse(kind, var.get())
            except (ValueError, KeyError):
                name = next(f[1] for f in FIELDS if f[0] == key)
                self._select(next(t for t, fs in TABS if any(f[0] == key for f in fs)))
                self.msg.configure(text=f"入力値を確認してください: {name}", text_color=T.DANGER)
                return
        if not changes["AI_NAME"] or not changes["WAKE_WORDS"]:
            self._select("一般")
            self.msg.configure(text="AI名とウェイク語は必須です", text_color=T.DANGER)
            return
        if changes["OLLAMA_MODEL"] != config.OLLAMA_MODEL:
            # AIモデルの変更は、必ずサイズと注意を伝えて確認してから
            self.msg.configure(text="モデルのサイズを確認中…", text_color=T.SUB)
            name = changes["OLLAMA_MODEL"]
            threading.Thread(target=lambda: self.after(0, lambda w=models.warning(name): self._confirm(w, changes)),
                             daemon=True).start()
            return
        self._commit(changes)

    def _confirm(self, text, changes):
        """モデル変更の確認ダイアログ。"""
        self.msg.configure(text="")
        dlg = ctk.CTkToplevel(self, fg_color=T.BG)
        dlg.title("AIモデルの変更")
        dlg.attributes("-topmost", True)
        dlg.resizable(False, False)
        ctk.CTkLabel(dlg, text="⚠ 確認してください", font=T.font(14, "bold"), text_color=T.WARN).pack(
            anchor="w", padx=20, pady=(18, 6))
        ctk.CTkLabel(dlg, text=text, font=T.font(12), text_color=T.TEXT, justify="left", wraplength=400).pack(
            anchor="w", padx=20)
        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(anchor="e", padx=20, pady=18)
        ctk.CTkButton(btns, text="やめる", width=96, height=34, corner_radius=17, fg_color="transparent",
                      border_width=1, border_color=T.BORDER, text_color=T.SUB, hover_color=T.SURFACE,
                      command=dlg.destroy).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="変更してダウンロード", width=160, height=34, corner_radius=17,
                      fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER, font=T.font(12, "bold"),
                      command=lambda: (dlg.destroy(), self._commit(changes))).pack(side="left")
        dlg.grab_set()

    def _commit(self, changes):
        try:
            shortcut.set_autostart(changes["AUTOSTART"])
        except Exception as e:
            self.msg.configure(text=f"自動起動の設定に失敗: {e}", text_color=T.DANGER)
            return
        restart = any(changes.get(k) != getattr(config, k) for k in ("UI_FONT", "UI_FONT_SCALE", "UI_THEME"))
        config.save(changes)
        self._on_saved()
        self.msg.configure(text="")
        self._show_toast()  # 画面は閉じずに、保存したことだけを知らせる
        self._refresh_dirty()
        if restart:
            import tkinter.messagebox as mb
            if mb.askyesno("表示の変更", "カラー・フォント・文字の大きさは、再起動すると反映されます。\n今すぐ再起動しますか？"):
                self.master.restart_app()
