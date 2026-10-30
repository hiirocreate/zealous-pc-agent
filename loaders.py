"""ローディングのアニメーション。いつもの「流れる3つの光」(ロゴの色の、尾を引いて溶け合う光の粒)と同じ描き方で、
- テクニカルモード: 緑の光の粒が、回路の道を走り抜ける(角の点が光る)
- 資料づくり: 光の粒がペンになって、書類に1行ずつ光の文字を書いていく(書き終えると書類が光る)
- 進み具合の帯: 光の粒が、尾を引いて左から右へ流れる
コマ画像は最初に一度だけ作り、あとは時刻に合わせて切り替えるだけ(動かす処理は軽い)。"""
import functools
import math

from PIL import Image, ImageDraw, ImageFilter

LOGO = [(124, 92, 255), (91, 140, 255), (34, 211, 238)]   # いつもの光と同じ3色(ロゴの色)
TECH = [(16, 185, 129), (20, 184, 166), (34, 211, 238)]   # テクニカルモード: 緑からシアンへ
K = 3       # 細かく計算して縮小し、縁をなめらかにする
TAIL = 14   # 尾の細かさ


def _light(W, H, drops):
    """光の粒(液体のように溶け合う)を描く。drops: [(x, y, 半径, 色, 強さ)]。いつもの光と同じ式。"""
    import numpy as np
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    field = np.zeros((H, W), np.float32)
    rgb = np.zeros((H, W, 3), np.float32)
    for x, y, r, col, weight in drops:
        g = (r * r) / ((xx - x) ** 2 + (yy - y) ** 2 + 1.0) * weight
        field += g
        rgb += g[..., None] * np.array(col, np.float32)
    color = rgb / np.maximum(field, 1e-6)[..., None]
    core = np.clip((field - 0.75) / 0.35, 0, 1)
    glow = np.clip((field - 0.2) / 0.55, 0, 1) * 0.35
    alpha = np.maximum(core, glow)
    img = np.dstack([np.clip(color + core[..., None] * 40, 0, 255), alpha * 255]).astype(np.uint8)
    return Image.fromarray(img, "RGBA")


def _drop(path, t, r, col, tail_len=0.22):
    """道 path(t→(x, y)) の上を走る、尾を引いた光の粒。"""
    out = []
    for j in range(TAIL):
        fade = 1 - j / TAIL
        x, y = path(t - j * tail_len / TAIL)
        out.append((x, y, r * (0.45 + 0.55 * fade), col, 1.0 if j == 0 else 0.24 * fade ** 1.6))
    return out


def _mix(a, b, f):
    return tuple(round(x + (y - x) * f) for x, y in zip(a, b))


def _loop(W, H, m):
    """角の丸い長方形の道(回路のように、まっすぐ進んで角で曲がる)。t は 0〜1 で一周。"""
    x0, y0, x1, y1 = m, m, W - m, H - m
    w, h = x1 - x0, y1 - y0
    per = 2 * (w + h)

    def at(t):
        d = (t % 1.0) * per
        if d < w:
            return x0 + d, y0
        d -= w
        if d < h:
            return x1, y0 + d
        d -= h
        if d < w:
            return x1 - d, y1
        return x0, y1 - (d - w)
    return at, (x0, y0, x1, y1)


def tech_frames_pil(w, h, count=54, scale=2):
    """テクニカルモード: 緑の光の粒が回路の道を追いかけ合い、角の点が光る。"""
    W, H = w * scale * K, h * scale * K
    m = H * 0.22
    path, (x0, y0, x1, y1) = _loop(W, H, m)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    frames = []
    for f in range(count):
        t = f / count
        drops = []
        heads = []
        for i, col in enumerate(TECH):
            p = t + i / 3
            drops += _drop(path, p, H * 0.105, col, 0.2)
            heads.append(path(p))
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img, "RGBA")
        lw = max(1, int(K * scale * 0.5))
        d.rounded_rectangle((x0, y0, x1, y1), radius=m * 0.2, outline=(*TECH[0], 60), width=lw)  # 回路の道(下に敷く)
        img = Image.alpha_composite(img, _light(W, H, drops))
        d = ImageDraw.Draw(img, "RGBA")
        for cx, cy in corners:  # 角の点: 光の粒が近づくと明るくなる
            near = max(0.0, 1 - min(math.hypot(cx - hx, cy - hy) for hx, hy in heads) / (H * 0.5))
            r = H * (0.045 + 0.045 * near)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*TECH[2], int(80 + 175 * near)))
        frames.append(img.resize((w * scale, h * scale), Image.LANCZOS))
    return frames


def doc_frames_pil(w, h, count=90, scale=2):
    """資料づくり: 光の粒がペンになり、書類に1行ずつ光の文字を書く。書き終えると書類全体が光って、また始めから。"""
    W, H = w * scale * K, h * scale * K
    m = W * 0.1
    px0, py0, px1, py1 = m, m * 0.8, W - m, H - m * 0.8
    fold = (px1 - px0) * 0.26
    page = [(px0, py0), (px1 - fold, py0), (px1, py0 + fold), (px1, py1), (px0, py1)]
    rows = 5
    top = py0 + fold + (py1 - py0) * 0.05
    gap = (py1 - (py1 - py0) * 0.1 - top) / (rows - 1)
    lx0, lx1 = px0 + (px1 - px0) * 0.16, px1 - (px1 - px0) * 0.16
    ends = [lx1, lx1, lx1 - (lx1 - lx0) * 0.12, lx1, lx0 + (lx1 - lx0) * 0.55]  # 最後の行は短く(文章らしく)
    lw = max(2, int(K * scale * 0.9))
    frames = []
    for f in range(count):
        t = f / count
        write = min(1.0, t / 0.78)        # 8割で書き終え、残りで光る
        flash = max(0.0, (t - 0.78) / 0.22)
        shine = math.sin(flash * math.pi)
        base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(base, "RGBA")
        d.polygon(page, fill=(*LOGO[0], int(26 + 70 * shine)))
        edge = (*_mix(LOGO[0], LOGO[2], shine), int(150 + 105 * shine))
        d.line(page + [page[0]], fill=edge, width=lw, joint="curve")
        d.line([(px1 - fold, py0), (px1 - fold, py0 + fold), (px1, py0 + fold)], fill=edge, width=lw)
        pen = None
        for n in range(rows):
            y = top + gap * n
            done = max(0.0, min(1.0, write * rows - n))
            col = LOGO[n % 3]
            d.line((lx0, y, ends[n], y), fill=(*col, 35), width=lw)  # まだ書いていない行(うっすら)
            if done > 0:
                x = lx0 + (ends[n] - lx0) * done
                d.line((lx0, y, x, y), fill=(*_mix(col, (255, 255, 255), 0.15 * shine), 235), width=lw + 1)
                if done < 1:
                    pen = (n, x, y, col, done)
        base = Image.alpha_composite(base.filter(ImageFilter.GaussianBlur(K * scale * (0.6 + 1.6 * shine))), base)
        if pen:  # ペン: いつもの光の粒が、書いている行の先で尾を引く
            n, x, y, col, done = pen
            span = ends[n] - lx0
            path = lambda s, n=n, y=y, span=span: (lx0 + span * max(0.0, s), y)  # noqa: E731
            drops = _drop(path, done, H * 0.045, col, 0.3)
            # 書いた勢いで、小さな光の粒が少し上へ跳ねる
            for k in range(2):
                ph = (t * 7 + k * 0.5) % 1.0
                drops.append((x - W * 0.03 * k, y - H * 0.06 * ph, H * 0.018 * (1 - ph), LOGO[(n + k + 1) % 3], 1.0))
            base = Image.alpha_composite(base, _light(W, H, drops))
        frames.append(base.resize((w * scale, h * scale), Image.LANCZOS))
    return frames


def bar_frames_pil(w, h, count=54, scale=2):
    """進み具合の帯: うっすらした道の上を、ロゴの色の光の粒が尾を引いて流れる。"""
    W, H = w * scale * K, max(h * scale * K, 6)
    frames = []
    for f in range(count):
        t = f / count
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(img, "RGBA").rounded_rectangle((0, H * 0.3, W - 1, H * 0.7), radius=H * 0.2,
                                                     fill=(*LOGO[1], 45))
        drops = []
        for i, col in enumerate(LOGO):
            p = (t + i / 3) % 1.0
            path = lambda s: (-W * 0.15 + W * 1.3 * s, H / 2)  # noqa: E731
            drops += _drop(path, p, H * 0.42, col, 0.12)
        img = Image.alpha_composite(img, _light(W, H, drops))
        frames.append(img.resize((w * scale, h * scale), Image.LANCZOS))
    return frames


def _ctk(frames, w, h):
    import customtkinter as ctk
    return [ctk.CTkImage(im, size=(w, h)) for im in frames]


@functools.lru_cache(maxsize=2)
def tech(w=44, h=18):
    return _ctk(tech_frames_pil(w, h), w, h)


@functools.lru_cache(maxsize=2)
def document(w=44, h=52):
    return _ctk(doc_frames_pil(w, h), w, h)


@functools.lru_cache(maxsize=2)
def bar(w=170, h=6):
    return _ctk(bar_frames_pil(w, h), w, h)


_started = False


def warm():
    """コマ画像を裏で作り始める(起動時に一度。作り終えるまでは、ローディングの絵は出さずに待つ)。"""
    global _started
    if _started:
        return
    _started = True
    import threading
    import time

    def run():
        time.sleep(12)  # 起動の直後は避ける(ほかの準備を先に。起動時のPCの負担を分散する)
        tech(), document(), bar()
    threading.Thread(target=run, daemon=True).start()


def ready(fn):
    """コマ画像ができていれば返す(まだなら None。画面を止めないため、ここでは作らない)。"""
    info = fn.cache_info()
    return fn() if info.currsize else None
