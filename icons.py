"""ボタン用アイコン(Pillowで描画。絵文字フォントに依存しない)。"""
import functools

import customtkinter as ctk
from PIL import Image, ImageDraw

_S = 256  # 高解像度で描いて縮小(なめらかにするため)


def _canvas():
    img = Image.new("RGBA", (_S, _S), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


@functools.lru_cache(maxsize=None)
def mic(size=20, color="white"):
    img, d = _canvas()
    w = 18
    d.rounded_rectangle((88, 24, 168, 148), radius=40, fill=color)
    d.arc((56, 64, 200, 184), start=0, end=180, fill=color, width=w)
    d.line((128, 184, 128, 224), fill=color, width=w)
    d.line((84, 226, 172, 226), fill=color, width=w)
    return ctk.CTkImage(img, size=(size, size))


@functools.lru_cache(maxsize=None)
def send(size=16, color="white"):
    img, d = _canvas()
    d.polygon([(40, 40), (224, 128), (40, 216), (72, 128)], fill=color)
    return ctk.CTkImage(img, size=(size, size))
