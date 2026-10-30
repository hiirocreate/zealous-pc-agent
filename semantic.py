"""PCの中の文書を「意味」で探す(言葉が一致しなくても、内容の近いものを見つける)。
文書を小さな区切りに分け、埋め込みAI(Ollama の qwen3-embedding など)で「意味の数値」にして保存しておく。
保存には sqlite-vec(SQLite で近いものを速く探す部品)を使い、使えなければ numpy で計算する。
初めて使うときに文書を読み込む(時間がかかる分は裏で続ける)。2回目からは、変わったファイルだけを読み直す。"""
import os
import sqlite3
import threading
import time

import numpy as np
import requests

import config
import zlog

CHUNK, OVERLAP, MAX_CHUNKS, MAX_FILES, MAX_BYTES = 600, 100, 30, 3000, 5_000_000
_lock = threading.Lock()
_bg = None


def _db_path():
    import runtime
    return os.path.join(runtime.DATA_DIR, "semantic.db")


def folders():
    home = os.path.expanduser("~")
    return [f for f in (getattr(config, "SEMANTIC_FOLDERS", []) or
                        [os.path.join(home, "Documents"), os.path.join(home, "Desktop")]) if os.path.isdir(f)]


# ---------------- 埋め込み(意味の数値) ----------------
def embed(texts, query=False):
    """文の一覧 → 長さ1にそろえた数値の配列。初めて使うモデルはダウンロードする。"""
    import llm
    import services
    model = getattr(config, "EMBED_MODEL", "") or "qwen3-embedding:0.6b"
    if query and model.startswith("qwen3-embedding"):  # 検索の言葉には、何を探すかの説明を付けると精度が上がる
        texts = [f"Instruct: Given a search query, retrieve relevant passages\nQuery: {t}" for t in texts]
    url = services.ollama_base() + "/api/embed"
    body = {"model": model, "input": texts, "keep_alive": "5m", "options": llm.ai_options()}
    r = requests.post(url, json=body, timeout=300)
    if r.status_code == 404:
        llm._status(f"意味で探すAI（{model}）を準備しています…")
        services.pull_model(lambda t: None, model)
        r = requests.post(url, json=body, timeout=300)
    r.raise_for_status()
    v = np.asarray(r.json()["embeddings"], np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-6)


# ---------------- 保存先 ----------------
def _open():
    """保存先を開く。(接続, sqlite-vec を使えるか)"""
    os.makedirs(os.path.dirname(_db_path()), exist_ok=True)
    db = sqlite3.connect(_db_path(), check_same_thread=False)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime REAL);
        CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, path TEXT, pos INTEGER, text TEXT, emb BLOB);
        CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
    """)
    vec = False
    try:  # sqlite-vec: 近いものを SQLite の中で速く探す
        import sqlite_vec
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        vec = True
    except Exception:
        pass
    model = getattr(config, "EMBED_MODEL", "") or "qwen3-embedding:0.6b"
    row = db.execute("SELECT v FROM meta WHERE k='model'").fetchone()
    if row and row[0] != model:  # 埋め込みAIを変えた: 数値の意味が変わるので作り直す
        db.executescript("DELETE FROM files; DELETE FROM chunks; DROP TABLE IF EXISTS vec; DELETE FROM meta;")
    db.execute("INSERT OR REPLACE INTO meta VALUES('model', ?)", (model,))
    db.commit()
    return db, vec


def _vec_table(db, vec, dim):
    """数値の長さが分かったら、近いものを探す表(sqlite-vec)を用意する。使えるなら True。"""
    row = db.execute("SELECT v FROM meta WHERE k='dim'").fetchone()
    if not row:
        db.execute("INSERT INTO meta VALUES('dim', ?)", (str(dim),))
    if vec:
        db.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS vec USING vec0(embedding float[{dim}] distance_metric=cosine)")
    return vec


# ---------------- 読み込み ----------------
def _files():
    import attachments
    exts = set(attachments.TEXT) | {".docx", ".pptx", ".pdf"}
    out = []
    for base in folders():
        for cur, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d.lower() not in attachments.SKIP_DIRS and not d.startswith(".")]
            for f in files:
                p = os.path.join(cur, f)
                if os.path.splitext(f)[1].lower() in exts:
                    try:
                        if os.path.getsize(p) <= MAX_BYTES:
                            out.append(p)
                    except OSError:
                        pass
                if len(out) >= MAX_FILES:
                    return out
    return out


def _text(path):
    import attachments
    import tools
    ext = os.path.splitext(path)[1].lower()
    text = attachments.markdown(path) if ext in (".docx", ".pptx", ".pdf") else ""
    return text or tools.file_text(path, limit=400_000)


def _chunks(text):
    text = " ".join(text.split())
    step = CHUNK - OVERLAP
    return [text[i:i + CHUNK] for i in range(0, max(1, len(text)), step)][:MAX_CHUNKS] if text.strip() else []


def index(budget=60.0):
    """変わったファイルだけを読み直す。budget 秒を過ぎたら、続きは裏で行う。読み終えたら True。"""
    global _bg
    with _lock:
        start = time.monotonic()
        db, vec = _open()
        known = dict(db.execute("SELECT path, mtime FROM files"))
        paths = _files()
        gone = set(known) - set(paths)
        for p in gone:
            _remove(db, p)
        todo = []
        for p in paths:
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if known.get(p) != m:
                todo.append((p, m))
        for n, (p, m) in enumerate(todo):
            if time.monotonic() - start > budget:
                db.commit()
                if _bg is None or not _bg.is_alive():
                    _bg = threading.Thread(target=lambda: index(budget=10 ** 9), daemon=True)
                    _bg.start()
                return False
            try:
                parts = _chunks(_text(p))
                vecs = embed(parts) if parts else np.zeros((0, 1), np.float32)
            except Exception as e:
                zlog.note(f"意味の検索: 読めなかったファイル {os.path.basename(p)}: {e!r}")
                continue
            use_vec = _vec_table(db, vec, vecs.shape[1]) if len(vecs) else False
            _remove(db, p)
            for i, (t, v) in enumerate(zip(parts, vecs)):
                cid = db.execute("INSERT INTO chunks(path, pos, text, emb) VALUES(?,?,?,?)",
                                 (p, i, t, v.astype(np.float32).tobytes())).lastrowid
                if use_vec:
                    db.execute("INSERT INTO vec(rowid, embedding) VALUES(?, ?)", (cid, v.astype(np.float32).tobytes()))
            db.execute("INSERT OR REPLACE INTO files VALUES(?, ?)", (p, m))
            if n % 20 == 0:
                db.commit()
        db.commit()
        return True


def _remove(db, path):
    ids = [r[0] for r in db.execute("SELECT id FROM chunks WHERE path=?", (path,))]
    if ids:
        try:
            db.executemany("DELETE FROM vec WHERE rowid=?", [(i,) for i in ids])
        except sqlite3.Error:
            pass
        db.execute("DELETE FROM chunks WHERE path=?", (path,))
    db.execute("DELETE FROM files WHERE path=?", (path,))


# ---------------- 検索 ----------------
def search(query, limit=5):
    """[(パス, 似ている度合い0〜1, その部分の文)] 。同じファイルは1つにまとめる。"""
    q = embed([query], query=True)[0]
    db, vec = _open()
    vec = vec and db.execute("SELECT name FROM sqlite_master WHERE name='vec'").fetchone() is not None
    if vec:
        rows = db.execute("SELECT c.path, v.distance, c.text FROM vec v JOIN chunks c ON c.id = v.rowid "
                          "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
                          (q.astype(np.float32).tobytes(), limit * 6)).fetchall()
        hits = [(p, 1 - d, t) for p, d, t in rows]
    else:
        rows = db.execute("SELECT path, text, emb FROM chunks").fetchall()
        if not rows:
            return []
        m = np.frombuffer(b"".join(r[2] for r in rows), np.float32).reshape(len(rows), -1)
        score = m @ q
        hits = [(rows[i][0], float(score[i]), rows[i][1]) for i in np.argsort(-score)[:limit * 6]]
    out, seen = [], set()
    for p, s, t in hits:
        if p not in seen and os.path.exists(p):
            seen.add(p)
            out.append((p, s, t))
        if len(out) >= limit:
            break
    return out
