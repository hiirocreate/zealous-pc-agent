"""メールの操作を、メールアプリの画面を使わずに裏側で行う(既読にする・未読を数える・フォルダの名前を変える)。
- IMAP: Gmail・Outlook.com・Yahoo・プロバイダのメールなど(Thunderbird などで使っているアカウントも、
  同じサーバーの状態が変わるので、アプリにもそのまま反映される)。設定でサーバーとアカウントを登録する。
- Outlook(従来版): PCに入っている Outlook を、画面を出さずに操作する(登録不要)。"""
import base64
import json
import re
import unicodedata

import config

# よく使うフォルダの呼び名 → 種類(IMAP の特別なフォルダの印 / Outlook の既定フォルダ)
SPECIAL = {
    "junk": ("\\Junk", 23, ("迷惑", "スパム", "spam", "junk", "bulk")),
    "trash": ("\\Trash", 3, ("ゴミ箱", "ごみ箱", "削除済み", "trash", "deleted", "bin")),
    "sent": ("\\Sent", 5, ("送信済み", "送信", "sent")),
    "drafts": ("\\Drafts", 16, ("下書き", "draft")),
    "inbox": ("", 6, ("受信", "inbox")),
    "archive": ("\\Archive", None, ("アーカイブ", "archive")),
    "all": ("\\All", None, ("すべてのメール", "全てのメール", "all mail")),
    "flagged": ("\\Flagged", None, ("スター", "starred", "flagged")),
}


def _norm(s):
    return unicodedata.normalize("NFKC", str(s)).lower().replace(" ", "").replace("　", "")


def backend():
    """使う仕組み: "imap" / "outlook" / None(使えない)。"""
    kind = getattr(config, "MAIL_SERVICE", "auto")
    if kind in ("imap", "auto") and config.MAIL_IMAP_HOST and config.MAIL_IMAP_USER:
        return "imap"
    if kind in ("outlook", "auto") and _has_outlook():
        return "outlook"
    if kind in ("thunderbird", "auto"):
        import mail_ui
        if mail_ui.exe():
            return "thunderbird"  # 設定なし: Thunderbird の画面を、画面の外で操作する(既読にするだけ)
    return None


def _has_outlook():
    import os
    if os.name != "nt":
        return False
    import winreg
    try:
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID").Close()
        return True
    except OSError:
        return False


NOT_READY = ("メールの設定がまだです（Thunderbird・Outlook も見つかりませんでした）。設定の「メール」タブで、使っているメールのサーバー（例: imap.gmail.com）と"
             "アカウント、アプリパスワードを登録してください（Outlook を使っている場合は登録不要です）。")


# ---------------- IMAP ----------------
def _utf7_decode(name):
    """IMAP のフォルダ名(修正UTF-7)を、ふつうの文字に。"""
    def dec(m):
        body = m.group(1)
        if not body:
            return "&"
        b = body.replace(",", "/")
        return base64.b64decode(b + "=" * (-len(b) % 4)).decode("utf-16-be")
    return re.sub(r"&([A-Za-z0-9+,]*)-", dec, name)


def _utf7_encode(name):
    out, buf = [], []

    def flush():
        if buf:
            b = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            out.append("&" + b + "-")
            buf.clear()
    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def _quote(raw):
    return '"' + raw.replace("\\", "\\\\").replace('"', '\\"') + '"'


class _Imap:
    def __enter__(self):
        import imaplib
        import ssl
        import secret
        port = int(getattr(config, "MAIL_IMAP_PORT", 993) or 993)
        self.m = imaplib.IMAP4_SSL(config.MAIL_IMAP_HOST, port, ssl_context=ssl.create_default_context(), timeout=30)
        try:
            self.m.login(config.MAIL_IMAP_USER, secret.reveal(config.MAIL_IMAP_PASSWORD))
        except imaplib.IMAP4.error:
            raise PermissionError("メールのサーバーにログインできませんでした。設定のアカウントとアプリパスワードを確認してください")
        return self.m

    def __exit__(self, *exc):
        try:
            self.m.logout()
        except Exception:
            pass


_LIST = re.compile(r'\((?P<flags>[^)]*)\)\s+(?P<sep>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.+)$')


def _imap_folders(m):
    typ, data = m.list()
    out = []
    for line in data or []:
        if isinstance(line, tuple):  # 名前が別送り(リテラル)のとき
            line = line[0] + b'"' + line[1] + b'"'
        g = _LIST.match(line.decode("utf-8", "replace"))
        if not g:
            continue
        raw = g.group("name").strip()
        if raw.startswith('"'):
            raw = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        sep = g.group("sep").strip('"') if g.group("sep") != "NIL" else ""
        flags = g.group("flags")
        if "\\Noselect" in flags or "\\NonExistent" in flags:
            continue
        path = _utf7_decode(raw)
        kind = next((k for k, (flag, _, _) in SPECIAL.items() if flag and flag in flags), None)
        if raw.upper() == "INBOX":
            kind = "inbox"
        out.append({"path": path, "raw": raw, "sep": sep, "kind": kind,
                    "name": path.split(sep)[-1] if sep else path})
    return out


# ---------------- Outlook(従来版) ----------------
_OUTLOOK = r"""
$ErrorActionPreference = 'Stop'
$o = New-Object -ComObject Outlook.Application
$ns = $o.GetNamespace('MAPI')
$special = @{}
foreach ($id in 3, 5, 6, 16, 23) { try { $special[$ns.GetDefaultFolder($id).FolderPath] = $id } catch {} }
function Walk($f) { $f; foreach ($c in $f.Folders) { Walk $c } }
$all = foreach ($s in $ns.Folders) { foreach ($c in $s.Folders) { Walk $c } }
function Find($path) { $all | Where-Object { $_.FolderPath -eq $path } | Select-Object -First 1 }
"""


def _outlook(script, **values):
    import subprocess
    head = "".join(f"${k} = '{str(v).replace(chr(39), chr(39) * 2)}'\n" for k, v in values.items())
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + _OUTLOOK + head + script],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        import zlog
        zlog.error(f"Outlook: {r.stderr.strip()[:300]}")
        raise RuntimeError("Outlook を操作できませんでした（新しい Outlook には対応していません）")
    return r.stdout.strip()


def _outlook_folders():
    text = _outlook("$all | ForEach-Object { [pscustomobject]@{path = $_.FolderPath; name = $_.Name; "
                    "id = $special[$_.FolderPath]} } | ConvertTo-Json -Compress")
    data = json.loads(text or "[]")
    data = data if isinstance(data, list) else [data]
    ids = {num: k for k, (_, num, _) in SPECIAL.items() if num}
    return [{"path": d["path"], "name": d["name"], "kind": ids.get(d.get("id")), "raw": d["path"]} for d in data]


# ---------------- フォルダを名前で探す ----------------
def folders():
    kind = backend()
    if kind == "imap":
        with _Imap() as m:
            return _imap_folders(m)
    if kind == "outlook":
        return _outlook_folders()
    raise RuntimeError(NOT_READY)


def match(query, found):
    """呼び名に合うフォルダの候補(合う度合いの高い組だけ)。「迷惑メール」→ 迷惑メールの印のあるフォルダ など。"""
    import apps
    q = _norm(re.sub(r"(?:の)?(?:フォルダー?|ボックス)$", "", str(query).strip()))
    exact = [f for f in found if _norm(f["path"]) == q or _norm(f["name"]) == q]
    if exact:
        return exact
    for k, (_, _, words) in SPECIAL.items():
        if any(_norm(w) in q for w in words):
            hits = [f for f in found if f["kind"] == k] or \
                   [f for f in found if any(_norm(w) in _norm(f["name"]) for w in words)]
            if hits:
                return hits
    for test in (lambda n: n.startswith(q), lambda n: q in n):
        hits = [f for f in found if test(_norm(f["name"]))]
        if hits:
            return hits
    s = apps.sound(query)
    if len(s) >= 3:
        return [f for f in found if s in (apps.sound(f["name"]), apps.sound(f["name"]).removesuffix("s"))]
    return []


def resolve(query, tool, args):
    """フォルダを1つに決める。(フォルダ, None) または 決まらないとき (None, 返事)。"""
    import tools
    found = folders()
    hits = match(query, found)
    if not hits:  # 聞き取りの書き方の違い(しごと → 仕事 など): 考えられる書き方で探し直す
        for spelling in tools.spell_options(str(query))[1:]:
            hits += [f for f in match(spelling, found) if f not in hits]
    if not hits:
        names = "、".join(f["path"] for f in found[:12])
        return None, f"「{query}」というメールのフォルダは見つかりませんでした。あるフォルダ: {names}"
    if len(hits) > 1:
        return None, tools.ask_choice(f"「{query}」に当てはまるメールのフォルダが{len(hits)}つあります。どれにしますか？",
                                      tool, "folder", [f["path"] for f in hits[:6]], args=args)
    return hits[0], None


# ---------------- 操作 ----------------
_UI_ONLY = ("この操作は、メールの設定（設定の「メール」タブで IMAP のアカウントを登録）をすると使えます。"
            "設定なしでできるのは、Thunderbird で「〜を全部既読にして」だけです。")


def mark_read(query):
    if backend() == "thunderbird":
        import mail_ui
        return mail_ui.mark_read(query)
    folder, reply = resolve(query, "mail_mark_read", {})
    if reply:
        return reply
    if backend() == "imap":
        with _Imap() as m:
            m.select(_quote(folder["raw"]))
            typ, data = m.search(None, "UNSEEN")
            ids = (data[0] or b"").split()
            for i in range(0, len(ids), 500):
                m.store(b",".join(ids[i:i + 500]).decode(), "+FLAGS", "\\Seen")
            n = len(ids)
    else:
        n = int(_outlook("$f = Find $p; $list = @($f.Items.Restrict('[UnRead] = True'));"
                         "foreach ($i in $list) { $i.UnRead = $false }; $list.Count", p=folder["path"]) or 0)
    if not n:
        return f"「{folder['name']}」に未読のメールはありませんでした"
    return f"「{folder['name']}」の未読メール{n}通を、すべて既読にしました"


def unread(query=""):
    if backend() == "thunderbird":
        return _UI_ONLY
    folder, reply = resolve(query or "受信", "mail_unread", {})
    if reply:
        return reply
    if backend() == "imap":
        with _Imap() as m:
            typ, data = m.status(_quote(folder["raw"]), "(UNSEEN)")
            got = re.search(rb"UNSEEN (\d+)", data[0] or b"")
            n = int(got.group(1)) if got else 0
    else:
        n = int(_outlook("(Find $p).UnReadItemCount", p=folder["path"]) or 0)
    return f"「{folder['name']}」の未読メールは{n}通です" if n else f"「{folder['name']}」に未読のメールはありません"


def rename(query, new_name):
    new_name = str(new_name).strip().strip("「」『』\"'")
    if not new_name or re.search(r'[\\/"*?<>|]', new_name):
        return "その名前はフォルダの名前に使えません"
    if backend() == "thunderbird":
        return _UI_ONLY
    folder, reply = resolve(query, "mail_rename_folder", {"new_name": new_name})
    if reply:
        return reply
    if folder["kind"] == "inbox":
        return "受信トレイの名前は変えられません"
    old = folder["name"]
    if backend() == "imap":
        sep = folder["sep"]
        parent = folder["raw"].rsplit(sep, 1)[0] + sep if sep and sep in folder["raw"] else ""
        with _Imap() as m:
            typ, data = m.rename(_quote(folder["raw"]), _quote(parent + _utf7_encode(new_name)))
            if typ != "OK":
                return f"「{old}」の名前を変えられませんでした（{(data[0] or b'').decode('utf-8', 'replace')[:60]}）"
    else:
        _outlook("(Find $p).Name = $n", p=folder["path"], n=new_name)
    return f"メールのフォルダ「{old}」の名前を「{new_name}」に変えました"


def listing():
    if backend() == "thunderbird":
        return _UI_ONLY
    found = folders()
    return "メールのフォルダ: " + "、".join(f["path"] for f in found[:40])
