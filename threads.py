"""チャットのスレッド(会話のまとまり)の保存と読み出し。1スレッド = 1ファイル(JSON)。"""
import json
import os
import time
import uuid

import config

DIR = os.path.join(config.APP_DIR, "threads")


def _path(tid):
    return os.path.join(DIR, f"{tid}.json")


def new():
    now = time.time()
    return {"id": uuid.uuid4().hex[:12], "title": "新しいチャット", "created": now, "updated": now, "messages": []}


def save(thread):
    os.makedirs(DIR, exist_ok=True)
    tmp = _path(thread["id"]) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(thread, f, ensure_ascii=False)
    os.replace(tmp, _path(thread["id"]))


def load(tid):
    try:
        with open(_path(tid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def listing():
    """一覧 [{"id", "title", "updated"}](新しい順)。空のスレッドは出さない。"""
    out = []
    if os.path.isdir(DIR):
        for name in os.listdir(DIR):
            if name.endswith(".json"):
                t = load(name[:-5])
                if t and t["messages"]:
                    out.append({"id": t["id"], "title": t["title"], "updated": t["updated"]})
    return sorted(out, key=lambda t: -t["updated"])


def delete(tid):
    try:
        os.remove(_path(tid))
    except OSError:
        pass


def delete_all():
    """会話の履歴をすべて消す。"""
    import glob
    for f in glob.glob(os.path.join(DIR, "*.json")):
        try:
            os.remove(f)
        except OSError:
            pass


def add(thread, role, text, sources="", images=None, files=None):
    """メッセージを足して保存する。最初の発言をスレッド名にする。files: 作ったファイルのパス"""
    msg = {"role": role, "text": text, "time": time.time()}
    if files:
        msg["files"] = list(files)
    if sources:
        msg["sources"] = sources
    if images:
        msg["images"] = images
    thread["messages"].append(msg)
    if role == "user" and thread["title"] == "新しいチャット":
        line = " ".join(text.split())
        thread["title"] = line[:24] + ("…" if len(line) > 24 else "")
    thread["updated"] = msg["time"]
    save(thread)


def history(thread, turns):
    """AI に渡す直前のやりとり [(ユーザーの発言, 返事)](新しいものから turns 往復まで)。"""
    pairs, user = [], None
    for m in thread["messages"]:
        if m["role"] == "user":
            user = m["text"]
        elif m["role"] == "ai" and user is not None:
            pairs.append((user, m["text"][:300]))
            user = None
    return pairs[-turns:] if turns > 0 else []


def full_history(thread):
    """全部を参照するモードで AI に渡すもの (やりとり [(発言, 返事)], 古い部分の要約, 要約した往復数)。
    長くなって古い部分を圧縮してあれば、その後ろのやりとりだけを省略せずに渡す。"""
    pairs, user = [], None
    for m in thread["messages"]:
        if m["role"] == "user":
            user = m["text"]
        elif m["role"] == "ai" and user is not None:
            pairs.append((user, m["text"]))
            user = None
    if thread.get("summary_full") and thread.get("summary"):
        upto = min(thread.get("summary_upto", 0), len(pairs))
        return pairs[upto:], thread["summary"], upto
    return pairs, "", 0


def when(ts):
    """一覧に出す日時(今日なら時刻、それ以外は日付)。"""
    t, now = time.localtime(ts), time.localtime()
    return time.strftime("%H:%M" if t[:3] == now[:3] else "%m/%d", t)


def pairs(thread):
    """やりとり [(ユーザーの発言, 返事)] をすべて(古い順)。"""
    out, user = [], None
    for m in thread["messages"]:
        if m["role"] == "user":
            user = m["text"]
        elif m["role"] == "ai" and user is not None:
            out.append((user, m["text"][:300]))
            user = None
    return out


def export_text(thread, ai_name="AI"):
    """スレッドを読みやすい文章(Markdown)にする。書き出し・まとめてコピー用。"""
    lines = [f"# {thread['title']}", "", f"作成: {time.strftime('%Y/%m/%d %H:%M', time.localtime(thread['created']))}", ""]
    for m in thread["messages"]:
        who = "あなた" if m["role"] == "user" else ai_name
        at = time.strftime("%m/%d %H:%M", time.localtime(m.get("time", thread["updated"])))
        lines += [f"**{who}**（{at}）", "", m["text"], ""]
        if m.get("sources"):
            lines += ["出典:", m["sources"], ""]
        if m.get("images"):
            lines += [f"画像: {m['images'].get('query', '')}（{len(m['images'].get('items', []))}枚）", ""]
    return "\n".join(lines).rstrip() + "\n"


def safe_name(title):
    import re
    return re.sub(r'[\\/:*?"<>|\s]+', "_", title).strip("_")[:40] or "chat"
