"""配色・フォント。"""
import os

import config

DEFAULT_FONT = "Yu Gothic UI" if os.name == "nt" else "IPAPGothic"
FONT = config.UI_FONT or DEFAULT_FONT  # 設定で変えたフォント(再起動で反映)
SCALE = (config.UI_FONT_SCALE or 100) / 100  # 文字の大きさ
KEY = "#010203"          # 角丸の外側を透過させる色(Windows)

# 画面の配色(設定の「カラー」で選ぶ。再起動で反映)
THEMES = {
    "midnight": dict(LABEL="ミッドナイト（標準・紫）", MODE="dark",
                     BG="#14161c", SURFACE="#1d2029", SIDEBAR="#101218", BORDER="#2b303c", RAISED="#3a4150",
                     TEXT="#e8eaf0", SUB="#8a91a5", MUTED_TEXT="#c3c8d6",
                     ACCENT="#7c5cff", ACCENT_HOVER="#6a4cf0", ACCENT_LIGHT="#9b85ff"),
    "ocean": dict(LABEL="オーシャン（深い青・水色）", MODE="dark",
                  BG="#0f1a24", SURFACE="#162432", SIDEBAR="#0b141c", BORDER="#223647", RAISED="#2c4559",
                  TEXT="#e3f1f8", SUB="#86a3b5", MUTED_TEXT="#b9d0dc",
                  ACCENT="#0ea5c6", ACCENT_HOVER="#0b8fac", ACCENT_LIGHT="#38c5e3"),
    "sakura": dict(LABEL="サクラ（深い赤紫・ピンク）", MODE="dark",
                   BG="#1c1418", SURFACE="#271c22", SIDEBAR="#150f12", BORDER="#3a2a33", RAISED="#4a3641",
                   TEXT="#f6e9ef", SUB="#b393a3", MUTED_TEXT="#dcc4cf",
                   ACCENT="#e5578f", ACCENT_HOVER="#cf4479", ACCENT_LIGHT="#f07fab"),
    "light": dict(LABEL="ライト（明るい白・紫）", MODE="light",
                  BG="#f5f6fa", SURFACE="#e9ebf2", SIDEBAR="#eceef4", BORDER="#d3d7e2", RAISED="#c6cbd8",
                  TEXT="#1d2130", SUB="#6b7286", MUTED_TEXT="#3b4256",
                  ACCENT="#6d4dff", ACCENT_HOVER="#5a3ce8", ACCENT_LIGHT="#8d74ff"),
}
NAME = config.UI_THEME if config.UI_THEME in THEMES else "midnight"
globals().update(THEMES[NAME])

CYAN = "#22d3ee"
OK = "#34d399"
WARN = "#fbbf24"
DANGER = "#ef4444"
DANGER_HOVER = "#c53030"
LIVE = "#ef4444"          # マイクが聞き取り中
LIVE_HOVER = "#f87171"    # 聞き取り中にマウスを乗せたとき(押すと止まる): 明るい赤


def font(size=12, weight="normal"):
    return (FONT, max(7, round(size * SCALE)), weight)
