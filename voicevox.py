"""VOICEVOX エンジンを「本体 + 使う声のモデルだけ」で入れる(全部入りの約1.9GBを数百MBに)。
声のモデル(.vvm)は配布パッケージ(zip)から必要なものだけを後から取り出す。"""
import json
import os
import threading

import remotezip
import runtime

VERSION = runtime.VOICEVOX_VERSION
PKG = runtime.VOICEVOX_PKG
DIR = runtime.VOICEVOX_DIR
MODEL_DIR = os.path.join(DIR, "model")
CATALOG = os.path.join(runtime.DATA_DIR, f"voicevox_voices_{VERSION}.json")
# 同じ版の一覧はアプリに同梱(ネットに繋がずに声を選べる)
BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", f"voicevox_voices_{VERSION}.json")


def _is_voice_model(name):
    # s*.vvm は歌唱用なので対象外
    base = name.rsplit("/", 1)[-1]
    return name.startswith("model/") and base.endswith(".vvm") and not base.startswith("s")


def _core_member(name):
    # 声のモデルと、サンプル音声(wav)は入れない
    return not name.startswith("model/") and not name.endswith(".wav")


def catalog():
    """全ての声の一覧 [{"id", "speaker", "style", "vvm", "mb"}]。初回だけネットから目次を読み、保存して使い回す。"""
    cached = cached_catalog()
    if cached:
        return cached
    zf, raw = remotezip.open_zip(PKG, block=256 << 10)  # 各モデルの目次(metas.json)だけ読む
    voices = []
    for info in zf.infolist():
        if not _is_voice_model(info.filename):
            continue
        metas = json.loads(remotezip.inner_zip(zf, raw, info).read("metas.json"))
        vvm = info.filename.rsplit("/", 1)[-1]
        for m in metas:
            for st in m["styles"]:
                if "talk" in st.get("type", "talk"):  # 歌唱用のスタイルは除く
                    voices.append({"id": st["id"], "speaker": m["name"], "style": st["name"], "vvm": vvm,
                                   "mb": info.file_size >> 20, "uuid": m["speaker_uuid"]})
    voices.sort(key=lambda v: v["id"])
    os.makedirs(runtime.DATA_DIR, exist_ok=True)
    with open(CATALOG, "w", encoding="utf-8") as f:
        json.dump(voices, f, ensure_ascii=False)
    return voices


def cached_catalog():
    """ネットに繋がずに使える一覧(未取得なら空)。"""
    for path in (CATALOG, BUNDLED):
        try:
            with open(path, encoding="utf-8") as f:
                voices = json.load(f)
            if voices and "uuid" in voices[0]:  # 古い形式(キャラの識別子なし)は作り直す
                return voices
        except (OSError, ValueError):
            pass
    return []


def label(v):
    return f"{v['speaker']}（{v['style']}）"


def installed_models():
    return {n for n in os.listdir(MODEL_DIR) if n.endswith(".vvm")} if os.path.isdir(MODEL_DIR) else set()


def model_for(style_id):
    v = next((v for v in catalog() if v["id"] == int(style_id)), None)
    if not v:
        raise ValueError(f"話者ID {style_id} は見つかりません")
    return v["vvm"]


def needs_change(style_id):
    """選んだ声のモデルが無い、または使わないモデルが残っているか。"""
    v = next((v for v in cached_catalog() if v["id"] == int(style_id)), None)
    return bool(v) and installed_models() != {v["vvm"]}


def install_engine(progress):
    """エンジン本体(声のモデル以外)を入れる。"""
    if os.path.exists(os.path.join(DIR, "run.exe")):
        return
    zf, _ = remotezip.open_zip(PKG)
    remotezip.extract(zf, [m for m in zf.infolist() if _core_member(m.filename)], DIR, progress)
    os.makedirs(MODEL_DIR, exist_ok=True)


def install_voice(style_id, progress):
    """選んだ声のモデルだけを入れ、使わなくなったモデルは消して容量を空ける。戻り値: 変更があったか。"""
    need = model_for(style_id)
    changed = False
    if need not in installed_models():
        zf, _ = remotezip.open_zip(PKG)
        remotezip.extract(zf, [zf.getinfo(f"model/{need}")], DIR, progress)
        changed = True
    for old in installed_models() - {need}:
        os.remove(os.path.join(MODEL_DIR, old))
        changed = True
    return changed


# ---------------- 声選びの画面用 ----------------
def speakers():
    """キャラごとにまとめた一覧 [{"name", "uuid", "vvm", "mb", "styles": [{"id", "style"}]}](一覧の順)。
    同じキャラでもモデルが分かれている場合は、モデルごとに分ける(ダウンロード単位がモデルのため)。"""
    out = {}
    for v in cached_catalog():
        key = (v["uuid"], v["vvm"])
        if key not in out:
            out[key] = {"name": v["speaker"], "uuid": v["uuid"], "vvm": v["vvm"], "mb": v["mb"], "styles": []}
        out[key]["styles"].append({"id": v["id"], "style": v["style"]})
    for sp in out.values():
        sp["styles"].sort(key=lambda s: (s["style"] != "ノーマル", s["id"]))  # ノーマルを先頭に
    return sorted(out.values(), key=lambda sp: (int(sp["vvm"].split(".")[0]), sp["name"]))


_remote = None
_remote_lock = threading.Lock()


def _read_remote(name):
    """配布パッケージの中の小さなファイルを1つ読む(目次は1回だけ読み、以後は使い回す)。"""
    global _remote
    with _remote_lock:  # 読み取り位置を共有するため、同時には読まない
        if _remote is None:
            _remote = remotezip.open_zip(PKG, block=128 << 10)[0]
        return _remote.read(name)


def _resource(uuid, kind, name):
    return f"resources/character_info/{uuid}/{kind}/{name}"


def icon_bytes(uuid, style_id):
    """キャラの顔アイコン(PNG)。エンジン導入済みならPC内から、未導入ならネットから小さく取得。"""
    local = os.path.join(DIR, *_resource(uuid, "icons", f"{style_id}.png").split("/"))
    if os.path.exists(local):
        with open(local, "rb") as f:
            return f.read()
    return _read_remote(_resource(uuid, "icons", f"{style_id}.png"))


def sample_wav(uuid, style_id):
    """試聴用の音声(WAV)。モデルをダウンロードしなくても聞ける。"""
    return _read_remote(_resource(uuid, "voice_samples", f"{style_id}_001.wav"))
