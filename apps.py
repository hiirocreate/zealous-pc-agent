"""PC のアプリを名前で探して起動する。スタートメニューに載っているアプリ(ストアアプリ含む)が対象。"""
import difflib
import json
import os
import subprocess
import unicodedata

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# スタートメニューに無い / 呼び方が違う定番のもの: 呼び名 -> 起動するもの
BUILTIN = {
    "メモ帳": "notepad.exe", "notepad": "notepad.exe",
    "電卓": "calc.exe", "計算機": "calc.exe", "calculator": "calc.exe",
    "エクスプローラー": "explorer.exe", "エクスプローラ": "explorer.exe", "explorer": "explorer.exe",
    "設定": "ms-settings:", "windowsの設定": "ms-settings:",
    "タスクマネージャー": "taskmgr.exe", "タスクマネージャ": "taskmgr.exe",
    "コントロールパネル": "control.exe", "ペイント": "mspaint.exe", "paint": "mspaint.exe",
    "コマンドプロンプト": "cmd.exe", "パワーシェル": "powershell.exe", "powershell": "powershell.exe",
}
# よく使う英語名の日本語の呼び方(スタートメニュー上の名前に合わせる)
ALIASES = {
    "エクセル": "excel", "ワード": "word", "パワーポイント": "powerpoint", "パワポ": "powerpoint",
    "アウトルック": "outlook", "チームズ": "teams", "クローム": "chrome", "エッジ": "edge",
    "ファイアフォックス": "firefox", "スポティファイ": "spotify", "ディスコード": "discord",
    "ライン": "line", "ズーム": "zoom", "スラック": "slack", "ブイエスコード": "visual studio code",
    "スチーム": "steam", "vscode": "visual studio code", "フォト": "フォト", "カメラ": "カメラ", "時計": "時計",
    "サンダーバード": "thunderbird", "オービーエス": "obs", "ノーション": "notion", "ブレンダー": "blender",
    "ジンプ": "gimp", "ブイエルシー": "vlc", "フォトショップ": "photoshop", "フォトショ": "photoshop",
    "イラストレーター": "illustrator", "イラレ": "illustrator", "プレミア": "premiere", "アクロバット": "acrobat",
    "キャンバ": "canva", "ワンノート": "onenote", "ワンドライブ": "onedrive", "ドロップボックス": "dropbox",
    "スカイプ": "skype", "ウェブエックス": "webex", "マインクラフト": "minecraft", "マイクラ": "minecraft",
    "ブレイブ": "brave", "オペラ": "opera", "ビバルディ": "vivaldi", "アイチューンズ": "itunes", "キンドル": "kindle",
    "リブレオフィス": "libreoffice", "ギットハブ": "github", "ジーメール": "gmail", "グーグルクローム": "chrome",
    "ビジュアルスタジオコード": "visual studio code", "ブイエス": "visual studio", "ティームズ": "teams",
}
# メーカー名など、アプリの名前の前に付いていても無視する言葉
_VENDORS = ("microsoft", "mozilla", "google", "adobe", "apple", "amazon")

_cache = None


def _norm(s):
    return unicodedata.normalize("NFKC", s).lower().replace(" ", "").replace("　", "")


def start_apps():
    """スタートメニューのアプリ一覧 [{"Name", "AppID"}](1回だけ取得して使い回す)。"""
    global _cache
    if _cache is None:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                            "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"],
                           capture_output=True, text=True, encoding="utf-8", creationflags=_NO_WINDOW, timeout=30)
        data = json.loads(r.stdout or "[]")
        _cache = data if isinstance(data, list) else [data]
    return _cache


# ---- 表記ゆれ: カタカナと英語の名前を「子音の並び」にして比べる(サンダーバード = Thunderbird) ----
_KANA = {c: k for k, row in {
    "k": "カキクケコ", "g": "ガギグゲゴ", "s": "サシスセソザジズゼゾ", "t": "タチツテト", "d": "ダヂヅデド",
    "n": "ナニヌネノン", "f": "フ", "b": "バビブベボヴ", "p": "パピプペポ", "m": "マミムメモ", "r": "ラリルレロ"}.items()
    for c in row}
_EN = [(r"tion|sion", "sn"), (r"ght", "t"), (r"th|sh", "s"), (r"ph", "f"), (r"chr", "kr"), (r"ch", "t"),
       (r"ck|qu|q", "k"), (r"x", "ks"), (r"c(?=[eiy])", "s"), (r"c", "k"), (r"v", "b"), (r"[jz]", "s"),
       (r"r(?=e[^aeiou])|r(?![aeiou])", ""), (r"l", "r"), (r"[aeiouyhw]", "")]


def sound(text):
    """名前の読みの手がかり(子音の並び)。例: サンダーバード / Thunderbird → sndbd"""
    import re
    out = []
    for run in re.findall(r"[a-z]+|[\u30a0-\u30ff]+", _norm(text).translate(
            {c: c + 0x60 for c in range(0x3041, 0x3097)})):  # ひらがなはカタカナにそろえる
        if run.isascii():
            for pattern, repl in _EN:
                run = re.sub(pattern, repl, run)
            out.append(run)
        else:
            out.append("".join(_KANA.get(c, "") for c in run))
    return re.sub(r"(.)\1+", r"\1", "".join(out))


def _core(n):
    """「Mozilla Thunderbird」→「thunderbird」(メーカー名を除いた名前)"""
    for v in _VENDORS:
        if n.startswith(v) and len(n) > len(v):
            return n[len(v):]
    return n


def matches(name, apps, fuzzy=True):
    """呼び名に合うアプリの候補(合う度合いの高い組だけ、短い名前から)。fuzzy=False なら似ているだけのものは除く。"""
    key = _norm(ALIASES.get(_norm(name), name))
    names = [(_norm(a["Name"]), a) for a in apps]
    tests = (lambda n: n == key or _core(n) == key, lambda n: n.startswith(key) or _core(n).startswith(key),
             lambda n: key in n)
    for test in tests:
        hits = [a for n, a in names if test(n)]
        if hits:
            return sorted(hits, key=lambda a: len(a["Name"]))
    key_sound = sound(name)
    if len(key_sound) >= 3:  # カタカナで呼んだ英語の名前(またはその逆)
        hits = [a for n, a in names
                if key_sound == sound(a["Name"]) or any(key_sound == sound(w) for w in a["Name"].split())]
        if hits:
            return sorted(hits, key=lambda a: len(a["Name"]))
    if not fuzzy:
        return []
    close = difflib.get_close_matches(key, [n for n, _ in names], n=1, cutoff=0.6)
    return [next(a for n, a in names if n == close[0])] if close else []


def find(name, apps):
    """呼び名に最も近いアプリを返す(見つからなければ None)。"""
    found = matches(name, apps)
    return found[0] if found else None


def is_app(name):
    """その呼び名が、このPCのアプリのことか(「〇〇を開いて」をアプリの起動として扱ってよいか)。"""
    if _norm(name) in BUILTIN:
        return True
    if os.name != "nt" or len(_norm(name)) < 2:
        return False
    try:
        return bool(matches(name, start_apps(), fuzzy=False))
    except Exception:
        return False


def launch(name):
    builtin = BUILTIN.get(_norm(name))
    if builtin:
        os.startfile(builtin)
        return f"{name} を起動しました"
    found = matches(name, start_apps())
    if not found:
        return f"「{name}」というアプリが見つかりませんでした"
    names = list(dict.fromkeys(a["Name"] for a in found))
    if len(names) > 1:  # 当てはまるアプリが複数: どれを開くか確かめる
        import tools
        return tools.ask_choice(f"「{name}」に当てはまるアプリが{len(names)}つあります。どれを開きますか？",
                                "launch_app", "name", names[:6])
    app = found[0]
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app['AppID']}"], creationflags=_NO_WINDOW)
    return f"{app['Name']} を起動しました"
