"""ざっくりした頼み方から、したいことを読み取る。
- 「PCが重い」→ 原因を調べて、一時ファイルを消し、重いアプリの終了を勧める
- 「落ち込んでるから曲かけて」→ ひとこと寄り添ってから、気分に合う曲(前向きな曲 / 寄り添うバラード)を流す
決まった言い回しはすぐに判断し(速く・確実に)、それ以外はAIが関数の説明から判断する。"""
import random
import re
import threading
import urllib.parse

import config

# ---------------- 「PCが重い」 ----------------
_SLOW = re.compile(r"(?:PC|ピーシー|パソコン|パソ|動き|動作|画面|このPC)?(?:が|の動きが|、)?\s*"
                   r"(?:重い|重たい|遅い|おそい|もっさり|カクカク|かくかく|固まる|フリーズ|サクサク動かない|動かない|重くなっ|遅くなっ)"
                   r"|(?:PC|パソコン)を?(?:軽く|速く|サクサクに)", re.I)
_NOT_SLOW = re.compile(r"ページ|サイト|ネット|回線|wifi|wi-fi|通信|読み込み|ダウンロード|荷物|体|頭|気分|肩|腰", re.I)

# ---------------- 気分と曲 ----------------
_MUSIC = re.compile(r"曲|音楽|歌|ソング|BGM|ミュージック|かけて|流して|聴きたい|聞きたい|プレイリスト|spotify|スポティファイ", re.I)
MOODS = {
    "down": (re.compile(r"落ち込|へこ|凹|悲し|かなし|つら|辛い|しんど|泣き|泣い|失恋|元気(?:が)?(?:ない|出ない)|憂鬱|ゆううつ|"
                        r"ブルー|さみし|寂し|へこむ|へこん|しょんぼり|やる気(?:が)?(?:出ない|ない)|励まし|元気出"),
             ["それはつらかったですね。少しでも気持ちが軽くなるといいな。",
              "話してくれてありがとうございます。無理しなくて大丈夫ですよ。",
              "大変でしたね。今日は自分をいたわって、ゆっくりしてくださいね。"],
             {"uplift": ["元気が出る 前向き 応援ソング J-POP", "背中を押してくれる 前向きな曲"],
              "ballad": ["心に寄り添う バラード 邦楽", "そっと寄り添う 癒し バラード"]}),
    "tired": (re.compile(r"疲れ|つかれ|ヘトヘト|へとへと|くたくた|クタクタ|ぐったり|しんどい"),
              ["お疲れさまです。今日もよく頑張りましたね。ゆっくり休めるように、落ち着く曲をかけますね。",
               "お疲れさまでした。肩の力を抜いて、少し休憩しましょう。"],
              {"": ["癒し 音楽 リラックス ゆったり", "落ち着く 夜 チル 曲"]}),
    "sleep": (re.compile(r"眠れ|寝つけ|寝付け|ねむれ|寝れない|眠りたい|寝たい|寝る前"),
              ["眠れないのはつらいですね。目を閉じて、ゆっくり呼吸してみてください。眠りやすい音楽をかけますね。"],
              {"": ["睡眠用BGM 眠れる 音楽", "ぐっすり眠れる ピアノ 音楽"]}),
    "focus": (re.compile(r"集中|作業|勉強|仕事中|はかど|捗"),
              ["集中できるように、作業用のBGMをかけますね。頑張ってください。"],
              {"": ["作業用BGM 集中 lofi", "勉強用 集中 BGM ピアノ"]}),
    "happy": (re.compile(r"嬉しい|うれしい|楽しい|たのしい|テンション|アゲ|あげ(?:たい|て)|ノリノリ|盛り上が|ハッピー|最高"),
              ["いいですね！その気分にぴったりの、明るい曲をかけますね。"],
              {"": ["テンションが上がる 曲 J-POP", "ノリノリ 明るい 曲"]}),
    "calm": (re.compile(r"イライラ|いらいら|ムカ|むか|腹立|落ち着きたい|リラックスしたい|ストレス|不安"),
             ["それは大変でしたね。深呼吸して、少し気持ちを落ち着けましょう。穏やかな曲をかけますね。"],
             {"": ["心が落ち着く 音楽 リラックス", "ストレス解消 癒し 音楽"]}),
}
_UPLIFT = re.compile(r"明る|元気|前向き|アップテンポ|励ま|テンション|ポジティブ")
_BALLAD = re.compile(r"バラード|しっとり|寄り添|泣け|泣きたい|静か|ゆっくり")


def mood_of(text):
    for name, (pattern, _, _) in MOODS.items():
        if pattern.search(text):
            return name
    return None


def route(text):
    """ざっくりした頼み方なら (関数名, 引数)。当てはまらなければ None。"""
    t = text.strip()
    if _SLOW.search(t) and not _NOT_SLOW.search(t) and len(t) <= 40:
        return "speed_up_pc", {}
    mood = mood_of(t)
    if mood and (_MUSIC.search(t) or mood in ("sleep", "focus") and re.search(r"何か|なにか|かけ|流し", t)):
        style = "uplift" if _UPLIFT.search(t) else "ballad" if _BALLAD.search(t) else ""
        service = "spotify" if re.search(r"spotify|スポティファイ|スポティ", t, re.I) else ""
        return "play_mood_music", {"mood": mood, "style": style, "service": service}
    return None


def play_music(mood, style="", service=""):
    """ひとこと添えてから、気分に合う曲を流す(声で読み上げ終わるころに再生が始まるよう、少し待つ)。"""
    import tools
    mood = mood if mood in MOODS else "down"
    _, lines, queries = MOODS[mood]
    if mood == "down":
        style = style if style in ("uplift", "ballad") else random.choice(("uplift", "ballad"))
        kind = "前向きになれる曲" if style == "uplift" else "気持ちに寄り添うバラード"
        query = random.choice(queries[style])
    else:
        kind, query = "", random.choice(queries[""])
    line = random.choice(lines)
    service = (service or getattr(config, "MUSIC_SERVICE", "youtube") or "youtube").lower()
    wait = min(6.0, 1.0 + len(line) * 0.12)  # 先にひとこと伝えてから流す

    def play():
        if service == "spotify":
            path = tools.app_path("Spotify.exe")
            if path:  # Spotify のアプリがあれば、アプリで探す
                import os
                os.startfile("spotify:search:" + urllib.parse.quote(query))
            else:
                tools.open_in_browser("https://open.spotify.com/search/" + urllib.parse.quote(query))
        else:
            tools.play_video(query, "relevance", 5)
    threading.Timer(wait, play).start()
    where = "Spotify で" if service == "spotify" else ""
    return line + (f"{where}{kind}を流しますね。" if kind else (f"{where}流しますね。" if where else ""))
