"""音声会話画面の中央の「光の球」。
ローディングの「流れる3つの光」と同じ仲間で、球の中を3色の光が流れ、溶け合う。
- 聞き取り中: 水色系。声の大きさに合わせて、球がふくらみ、表面が波打つ
- 考え中: 紫系。光が ∞ の形を速く流れる(ローディングと同じ動き)
- 話し中: 話の調子(明るい・やさしい・問いかけ・ふつう)で色が変わり、声の強さで内側の流れが速くなる"""
import math

import numpy as np
from PIL import Image

# 状態・話の調子ごとの3色(ロゴの色合いに合わせる)
PALETTES = {
    "listen": [(34, 211, 238), (45, 212, 191), (91, 140, 255)],
    "think": [(124, 92, 255), (99, 102, 241), (168, 85, 247)],
    "speak": [(124, 92, 255), (91, 140, 255), (34, 211, 238)],      # ふつう
    "excited": [(236, 72, 153), (168, 85, 247), (251, 146, 60)],    # 明るい・うれしい
    "gentle": [(167, 139, 250), (147, 197, 253), (129, 140, 248)],  # やさしい・おわび
    "question": [(56, 189, 248), (34, 211, 238), (124, 92, 255)],   # 問いかけ
    "pause": [(71, 85, 105), (100, 116, 139), (91, 100, 130)],      # 一時停止(マイクOFF)
}

_EXCITED = ("！", "!", "うれし", "嬉し", "よかった", "良かった", "すごい", "楽し", "おめでと", "やった", "ワクワク")
_GENTLE = ("申し訳", "すみません", "ごめん", "残念", "大丈夫", "お大事", "無理せず", "ゆっくり", "心配")


def tone_of(text):
    """話している文から、話の調子を決める。"""
    text = text or ""
    if any(w in text for w in _GENTLE):
        return "gentle"
    if any(w in text for w in _EXCITED):
        return "excited"
    if text.rstrip().endswith(("？", "?", "か。", "ですか")):
        return "question"
    return "speak"


class Orb:
    def __init__(self, size, bg):
        self.size = size
        self.bg = np.array(bg, np.float32)
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
        c = size / 2
        self.dx, self.dy = xx - c, yy - c
        self.dist = np.hypot(self.dx, self.dy)
        self.angle = np.arctan2(self.dy, self.dx)
        self.R = size * 0.27
        # 画像の端に近づくほど光を消す(四角い境目が見えないように)
        self.edge_fade = np.clip((size / 2 - self.dist) / (size * 0.14), 0, 1) ** 2
        self.palette = np.array(PALETTES["listen"], np.float32)
        self.energy = 0.0
        self.phase = 0.0
        self._last = None

    def frame(self, now, mode, level=0.0):
        """mode: listen / think / speak / excited / gentle / question / pause。level: 声の強さ(0〜1)。"""
        dt = 0.033 if self._last is None else min(0.1, now - self._last)
        self._last = now
        target = np.array(PALETTES.get(mode, PALETTES["speak"]), np.float32)
        self.palette += (target - self.palette) * min(1.0, dt * 4)  # 色はなめらかに移り変わる
        goal = 0.35 if mode == "think" else (0.0 if mode == "pause" else level)
        self.energy += (goal - self.energy) * min(1.0, dt * (10 if goal > self.energy else 4))
        e = self.energy
        speed = {"think": 1.6, "pause": 0.15}.get(mode, 0.35 + 1.6 * e)
        self.phase += dt * speed
        p, R = self.phase, self.R * (1 + 0.10 * e)

        # 表面: 声に合わせて波打つ
        wobble = 1 + (0.035 + 0.06 * e) * np.sin(3 * self.angle + p * 2.3) + 0.03 * e * np.sin(5 * self.angle - p * 3.1)
        edge = R * wobble
        inside = np.clip((edge - self.dist) / 1.6 + 0.5, 0, 1)  # 縁はなめらかに

        # 内側の3つの光
        field = np.zeros_like(self.dist)
        rgb = np.zeros(self.dist.shape + (3,), np.float32)
        for i in range(3):
            th = 2 * math.pi * (p / 2.2 + i / 3)
            if mode == "think":  # ローディングと同じ ∞ の流れ
                bx = R * 0.55 * math.sin(th)
                by = R * 0.32 * math.sin(th) * math.cos(th) * 2
            else:  # ゆったり回りながら、声が強いほど外へ広がる
                rad = R * (0.30 + 0.22 * e + 0.06 * math.sin(p * 1.7 + i))
                bx, by = rad * math.cos(th), rad * math.sin(th) * 0.85
            br = R * (0.62 + 0.18 * math.sin(p * 1.3 + i * 2))
            g = br * br / ((self.dx - bx) ** 2 + (self.dy - by) ** 2 + br * br * 0.25)
            field += g
            rgb += g[..., None] * self.palette[i]
        color = rgb / np.maximum(field, 1e-6)[..., None]
        deep = self.palette.mean(axis=0) * 0.35 + self.bg * 0.65   # 球の奥の色
        mix = np.clip(field / 2.2, 0, 1)[..., None]
        body = deep + (color - deep) * mix
        # 左上のつや
        shine = np.clip(1 - np.hypot(self.dx + R * 0.35, self.dy + R * 0.45) / (R * 0.55), 0, 1) ** 2
        body += shine[..., None] * 60 * (0.6 + 0.4 * e)
        # 外側のほのかな光(声が強いほど明るく広く)
        out = np.clip(self.dist - edge, 0, None)
        glow = np.exp(-out / (R * (0.16 + 0.18 * e))) * (0.30 + 0.45 * e) * (1 - inside) * self.edge_fade
        glow_col = self.palette.mean(axis=0)
        img = self.bg + (body - self.bg) * inside[..., None]
        img += (glow_col - self.bg) * glow[..., None]
        return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
