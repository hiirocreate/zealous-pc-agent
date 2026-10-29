"""ロゴ・アイコン(Pillowで描画。絵文字フォントに依存しない)。"""
import functools
import math
import os

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

_S = 256  # 高解像度で描いて縮小(なめらかにするため)
PURPLE, CYAN = (124, 92, 255), (34, 211, 238)
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


def _gradient(w, h):
    """左上の紫から右下のシアンへのグラデーション。"""
    g = Image.new("RGBA", (w, h))
    px = g.load()
    for y in range(h):
        for x in range(w):
            t = (x + y) / (w + h - 2)
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(PURPLE, CYAN)) + (255,)
    return g


@functools.lru_cache(maxsize=None)
def _monogram():
    """角を落とした六角形のグラデーションに、斜めに切れ込んだ「Z」。"""
    s = _S
    mask, d = _canvas()
    hexagon = [(s / 2 + s * 0.48 * math.cos(math.radians(a)), s / 2 + s * 0.48 * math.sin(math.radians(a)))
               for a in range(-90, 270, 60)]
    d.polygon(hexagon, fill="white")
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    img.paste(_gradient(s, s), mask=mask)
    d = ImageDraw.Draw(img)
    w = (255, 255, 255, 255)
    d.polygon([(70, 74), (186, 74), (172, 100), (70, 100)], fill=w)            # 上の横線
    d.polygon([(158, 100), (186, 100), (98, 156), (70, 156)], fill=w)          # 斜線
    d.polygon([(84, 156), (186, 156), (186, 182), (70, 182)], fill=w)          # 下の横線
    d.line((150, 126, 196, 98), fill=(255, 255, 255, 140), width=6)            # 切れ込みの光
    return img


@functools.lru_cache(maxsize=8)
def logo(name, height=18):
    """モノグラム + 字間を空けたAI名のワードマーク。"""
    k = 4  # 描画倍率
    h = height * k
    text = name.upper() if name.isascii() else name
    f = _font(int(h * 0.62), text)
    track = int(h * 0.12) if text.isascii() else 0
    widths = [f.getbbox(c)[2] - f.getbbox(c)[0] for c in text]
    tw = sum(widths) + track * (len(text) - 1)
    gap = int(h * 0.35)
    img, d = _canvas(h + gap + tw + 4, h)
    img.paste(_monogram().resize((h, h), Image.LANCZOS), (0, 0))
    x = h + gap
    for c, cw in zip(text, widths):
        d.text((x - f.getbbox(c)[0], h / 2), c, font=f, fill=(236, 238, 245, 255), anchor="lm")
        x += cw + track
    return _img(img, img.width // k, height)


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
    img, d = _canvas()
    d.polygon([(40, 40), (224, 128), (40, 216), (72, 128)], fill=color)
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
