"""配色・フォント。"""
import os

FONT = "Yu Gothic UI" if os.name == "nt" else "IPAPGothic"
KEY = "#010203"          # 角丸の外側を透過させる色(Windows)

BG = "#14161c"           # カード背景
SURFACE = "#1d2029"      # 入力欄・吹き出し
SIDEBAR = "#101218"      # スレッド一覧(チャットより一段暗く)
BORDER = "#2b303c"
TEXT = "#e8eaf0"
SUB = "#8a91a5"
ACCENT = "#7c5cff"       # ゼラスのテーマ色
ACCENT_HOVER = "#6a4cf0"
CYAN = "#22d3ee"
OK = "#34d399"
WARN = "#fbbf24"
DANGER = "#ef4444"
DANGER_HOVER = "#c53030"


def font(size=12, weight="normal"):
    return (FONT, size, weight)
