"""ロゴ・アイコン(Pillowで描画。絵文字フォントに依存しない)。"""
import functools
import math
import os

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

_S = 256  # 高解像度で描いて縮小(なめらかにするため)
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_FONTS = [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\YuGothB.ttc",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf"]
_JP_FONTS = [r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc",
             "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf"]


def _canvas(w=_S, h=_S):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _img(img, w, h):
    return ctk.CTkImage(img, size=(w, h))


def _font(size, text):
    paths = _FONTS if text.isascii() else _JP_FONTS
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


@functools.lru_cache(maxsize=None)
def emblem(size=24):
    return _img(Image.open(os.path.join(ASSETS, "emblem.png")), size, size)


@functools.lru_cache(maxsize=8)
def wordmark(name, height=12):
    """AI名のワードマーク。既定名(Zealous)はロゴ画像、変更後は文字を描画する。"""
    if name.lower() == "zealous":
        img = Image.open(os.path.join(ASSETS, "wordmark.png"))
        return _img(img, round(img.width * height / img.height), height)
    k = 4  # 描画倍率
    h = height * k
    text = name.upper() if name.isascii() else name
    f = _font(h, text)
    track = int(h * 0.12) if text.isascii() else 0
    widths = [f.getbbox(c)[2] - f.getbbox(c)[0] for c in text]
    img, d = _canvas(sum(widths) + track * (len(text) - 1) + 4, int(h * 1.2))
    x = 0
    for c, cw in zip(text, widths):
        d.text((x - f.getbbox(c)[0], img.height / 2), c, font=f, fill=(236, 232, 255, 255), anchor="lm")
        x += cw + track
    return _img(img, img.width // k, img.height // k)


@functools.lru_cache(maxsize=None)
def mic(size=18, color="white"):
    img, d = _canvas()
    w = 18
    d.rounded_rectangle((88, 24, 168, 148), radius=40, fill=color)
    d.arc((56, 64, 200, 184), start=0, end=180, fill=color, width=w)
    d.line((128, 184, 128, 224), fill=color, width=w)
    d.line((84, 226, 172, 226), fill=color, width=w)
    return _img(img, size, size)


@functools.lru_cache(maxsize=None)
def waves(size=18, color="white"):
    """音声会話のボタン: 高さの違う縦の棒(声の波)。"""
    img, d = _canvas()
    for x, h in ((56, 50), (92, 110), (128, 160), (164, 110), (200, 50)):
        d.rounded_rectangle((x - 13, 128 - h / 2, x + 13, 128 + h / 2), radius=13, fill=color)
    return _img(img, size, size)


@functools.lru_cache(maxsize=None)
def mic_live(size=18, color="white"):
    """聞き取り中のマイク: マイクの両側に音の波を描き、「いま聞いている」ことを示す。"""
    img, d = _canvas()
    w = 16
    d.rounded_rectangle((100, 44, 156, 140), radius=28, fill=color)
    d.arc((76, 76, 180, 172), start=0, end=180, fill=color, width=w)
    d.line((128, 172, 128, 206), fill=color, width=w)
    d.line((96, 210, 160, 210), fill=color, width=w)
    for r in (52, 84):  # 音の波
        d.arc((128 - r - 20, 92 - r, 128 + r - 20, 92 + r), start=150, end=210, fill=color, width=12)
        d.arc((128 - r + 20, 92 - r, 128 + r + 20, 92 + r), start=-30, end=30, fill=color, width=12)
    return _img(img, size, size)


@functools.lru_cache(maxsize=None)
def mic_off(size=18, color="white"):
    """マイクを止めている印(マイクに斜線)。"""
    img, d = _canvas()
    w = 18
    d.rounded_rectangle((88, 24, 168, 148), radius=40, fill=color)
    d.arc((56, 64, 200, 184), start=0, end=180, fill=color, width=w)
    d.line((128, 184, 128, 224), fill=color, width=w)
    d.line((84, 226, 172, 226), fill=color, width=w)
    d.line((52, 40, 204, 208), fill=(0, 0, 0, 0), width=40)  # 斜線の周りを抜いて見やすく
    d.line((52, 40, 204, 208), fill=color, width=w)
    return _img(img, size, size)


@functools.lru_cache(maxsize=None)
def chat(size=18, color="white"):
    img, d = _canvas()
    d.rounded_rectangle((28, 40, 228, 180), radius=48, fill=color)
    d.polygon([(70, 170), (120, 170), (60, 228)], fill=color)
    for x in (88, 128, 168):
        d.ellipse((x - 13, 97, x + 13, 123), fill=(0, 0, 0, 0))
    return _img(img, size, size)


@functools.lru_cache(maxsize=None)
def send(size=18, color="white"):
    """紙飛行機(右向き)。尾の切れ込みで飛行機らしく見せる。"""
    img, d = _canvas()
    d.polygon([(30, 36), (232, 128), (30, 220), (30, 150), (150, 128), (30, 106)], fill=color)
    return _img(img, size, size)


@functools.lru_cache(maxsize=None)
def gear(size=18, color=(170, 176, 194)):
    img, d = _canvas()
    c, teeth = _S / 2, 8
    pts = []
    for i in range(teeth * 4):  # 歯の先端と付け根を交互に結ぶ
        a = math.radians(i * 360 / (teeth * 4) - 360 / (teeth * 8))
        r = 118 if i % 4 in (1, 2) else 92
        pts.append((c + r * math.cos(a), c + r * math.sin(a)))
    d.polygon(pts, fill=color)
    d.ellipse((c - 40, c - 40, c + 40, c + 40), fill=(0, 0, 0, 0))
    return _img(img, size, size)


@functools.lru_cache(maxsize=None)
def close(size=14, color=(170, 176, 194)):
    img, d = _canvas()
    d.line((56, 56, 200, 200), fill=color, width=26)
    d.line((200, 56, 56, 200), fill=color, width=26)
    return _img(img, size, size)


TAIL = 16  # 尾の細かさ


@functools.lru_cache(maxsize=None)
def flow_frames_pil(w, h, count=54, scale=2):
    """読み込み中のアニメーション「流れる3つの光」(PIL 画像のリスト。w×h の scale 倍の大きさ)。
    ロゴの3色の光の粒が、∞(無限大)の形の道を尾を引きながら流れ続け、中央で交わるたびに
    液体のように溶け合っては離れる。考えが行き来しながらまとまっていく様子を表す。"""
    import numpy as np
    k = 3  # 細かく計算して縮小し、縁をなめらかにする
    W, H = w * scale * k, h * scale * k
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    colors = np.array([(124, 92, 255), (91, 140, 255), (34, 211, 238)], np.float32)
    rx, ry = W * 0.34, H * 0.26            # ∞ の横幅・縦幅
    base = H * 0.105                       # 光の粒の大きさ
    frames = []
    for f in range(count):
        t = f / count
        field = np.zeros((H, W), np.float32)
        rgb = np.zeros((H, W, 3), np.float32)
        for i, col in enumerate(colors):
            for j in range(TAIL):  # 先頭の粒と、後ろに伸びる尾(細かく重ねて、なめらかな1本にする)
                th = 2 * math.pi * (t + i / 3) - j * 0.06
                cx = W / 2 + rx * math.sin(th)
                cy = H / 2 + ry * math.sin(th) * math.cos(th) * 2
                fade = 1 - j / TAIL
                r = base * (1 + 0.18 * math.sin(2 * math.pi * (2 * t + i / 3))) * (0.45 + 0.55 * fade)
                g = (r * r) / ((xx - cx) ** 2 + (yy - cy) ** 2 + 1.0) * (1.0 if j == 0 else 0.24 * fade ** 1.6)
                field += g
                rgb += g[..., None] * col
        color = rgb / np.maximum(field, 1e-6)[..., None]
        core = np.clip((field - 0.75) / 0.35, 0, 1)        # 光の粒の本体(溶け合う部分)
        glow = np.clip((field - 0.2) / 0.55, 0, 1) * 0.35   # まわりのほのかな光
        alpha = np.maximum(core, glow)
        img = np.dstack([np.clip(color + core[..., None] * 40, 0, 255), alpha * 255]).astype(np.uint8)
        frames.append(Image.fromarray(img, "RGBA").resize((w * scale, h * scale), Image.LANCZOS))
    return tuple(frames)


@functools.lru_cache(maxsize=8)
def dot_frames(dot=6, gap=5, count=54):
    """読み込み中のアニメーションのコマ画像(大きさは以前の3つのドットと同じ)。"""
    w, h = dot * 3 + gap * 2, int(dot * 2.4)
    return [_img(im, w, h) for im in flow_frames_pil(w, h, count)]


@functools.lru_cache(maxsize=None)
def dot(color, size=8):
    """状態を表す小さな丸(文字の「●」より縁がなめらか)。"""
    k = 8
    img = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((0, 0, size * k - 1, size * k - 1), fill=color)
    return _img(img.resize((size * 2, size * 2), Image.LANCZOS), size, size)


@functools.lru_cache(maxsize=None)
def menu(size=16, color=(170, 176, 194)):
    """ハンバーガーメニュー(三本線)。"""
    img, d = _canvas()
    for y in (70, 128, 186):
        d.rounded_rectangle((40, y - 11, 216, y + 11), radius=11, fill=color)
    return _img(img, size, size)


@functools.lru_cache(maxsize=None)
def plus(size=16, color=(170, 176, 194)):
    img, d = _canvas()
    d.rounded_rectangle((116, 36, 140, 220), radius=12, fill=color)
    d.rounded_rectangle((36, 116, 220, 140), radius=12, fill=color)
    return _img(img, size, size)


@functools.lru_cache(maxsize=None)
def maximize(size=16, restore=False, color=(170, 176, 194)):
    """全画面(四角)/元に戻す(重なった四角)。"""
    img, d = _canvas()
    if restore:
        d.rounded_rectangle((84, 40, 216, 172), radius=22, outline=color, width=18)
        d.rounded_rectangle((40, 84, 172, 216), radius=22, outline=color, width=18, fill=(0, 0, 0, 0))
    else:
        d.rounded_rectangle((44, 44, 212, 212), radius=26, outline=color, width=18)
    return _img(img, size, size)


@functools.lru_cache(maxsize=None)
def trash(size=14, color=(138, 145, 165)):
    img, d = _canvas()
    d.rounded_rectangle((52, 70, 204, 90), radius=8, fill=color)
    d.rounded_rectangle((100, 44, 156, 70), radius=8, outline=color, width=16)
    d.rounded_rectangle((68, 96, 188, 220), radius=18, outline=color, width=16)
    return _img(img, size, size)


@functools.lru_cache(maxsize=None)
def threads(size=17, color=(170, 176, 194)):
    """スレッド一覧(重なった2つの吹き出し)。"""
    img, d = _canvas()
    d.rounded_rectangle((70, 30, 236, 140), radius=30, outline=color, width=16)       # 奥の吹き出し
    d.polygon([(196, 136), (226, 136), (226, 170)], fill=color)
    d.rounded_rectangle((20, 92, 186, 202), radius=30, fill=(0, 0, 0, 0))              # 手前と重なる部分を抜く
    d.rounded_rectangle((20, 92, 186, 202), radius=30, fill=color)                     # 手前の吹き出し
    d.polygon([(44, 198), (76, 198), (36, 240)], fill=color)
    for y in (132, 162):
        d.rounded_rectangle((52, y - 7, 154, y + 7), radius=7, fill=(0, 0, 0, 0))     # 文字の線(抜き)
    return _img(img, size, size)
