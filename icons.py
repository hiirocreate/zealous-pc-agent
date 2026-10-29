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
def chat(size=18, color="white"):
    img, d = _canvas()
    d.rounded_rectangle((28, 40, 228, 180), radius=48, fill=color)
    d.polygon([(70, 170), (120, 170), (60, 228)], fill=color)
    for x in (88, 128, 168):
        d.ellipse((x - 13, 97, x + 13, 123), fill=(0, 0, 0, 0))
    return _img(img, size, size)


@functools.lru_cache(maxsize=None)
def send(size=16, color="white"):
    """紙飛行機。"""
    img, d = _canvas()
    d.polygon([(24, 118), (232, 28), (150, 232), (116, 148)], fill=color)
    d.line((116, 148, 232, 28), fill=(0, 0, 0, 0), width=14)  # 折り目
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
