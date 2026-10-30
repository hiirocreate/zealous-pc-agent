"""小さな画像対応AI(Ollama)で、画像や画面に何が写っているかを文章にする。
初めて使うときにモデルをダウンロードする(設定の「モデル」で選んだもの。空なら使わない)。"""
import base64
import io
import os

import requests

import config
import zlog


def enabled():
    return bool(getattr(config, "VISION_MODEL", ""))


def _image_b64(path_or_image, max_side=1280):
    """大きな画像は縮めてから渡す(読む量とメモリを減らす)。"""
    from PIL import Image
    im = path_or_image if hasattr(path_or_image, "size") else Image.open(path_or_image)
    im = im.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def describe(image, question="この画像に何が写っているか、文字が書かれていればその内容も含めて、日本語でくわしく説明してください。",
             status=lambda text: None):
    """画像(ファイルのパス か PIL の画像)を説明する文。使えなければ ""。"""
    if not enabled():
        return ""
    import llm
    import services
    model = config.VISION_MODEL
    body = {"model": model, "stream": False, "keep_alive": "5m",
            "messages": [{"role": "user", "content": question, "images": [_image_b64(image)]}],
            "options": llm.ai_options(temperature=0.1, num_ctx=4096)}
    for attempt in range(2):
        try:
            r = requests.post(config.OLLAMA_URL, json=body, timeout=max(120, config.OLLAMA_TIMEOUT))
            if r.status_code == 404 and attempt == 0:  # まだ無い: ダウンロードしてからもう一度
                status(f"画像を理解するAI（{model}）を準備しています…")
                services.pull_model(lambda t: None, model)
                continue
            r.raise_for_status()
            return (r.json().get("message") or {}).get("content", "").strip()
        except Exception as e:
            zlog.error(f"画像の説明に失敗: {e!r}")
            return ""
    return ""


def name_of(path):
    return os.path.basename(path)
