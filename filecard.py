"""作ったファイルの札(チャットと音声会話画面で共通)。種類の印・名前・大きさと、「開く」「保存」「場所」のボタン。"""
import os
import shutil
import subprocess

import customtkinter as ctk

import theme as T

# 種類 → (印の文字, 色)。Office で見慣れた色に合わせる
KINDS = {".docx": ("W", "#2B579A"), ".pptx": ("P", "#C43E1C"), ".xlsx": ("X", "#217346"), ".pdf": ("PDF", "#D93025")}


def _size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


def open_file(path):
    if os.name == "nt":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])


def show_in_folder(path):
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def save_copy(parent, path, on_done=None):
    """「ダウンロード」: 好きな場所と名前で、ファイルのコピーを保存する(ダウンロードと同じ)。"""
    from tkinter import filedialog
    ext = os.path.splitext(path)[1]
    dest = filedialog.asksaveasfilename(parent=parent, title="ファイルを保存", initialfile=os.path.basename(path),
                                        defaultextension=ext, filetypes=[(f"{ext} ファイル", f"*{ext}"), ("すべて", "*.*")])
    if not dest:
        return
    if os.path.abspath(dest) != os.path.abspath(path):
        shutil.copy2(path, dest)
    if on_done:
        on_done(f"保存しました: {os.path.basename(dest)}")


def card(parent, path, wrap=260, on_done=None, compact=False):
    """ファイル1つ分の札を作って返す(置き方は呼ぶ側で決める)。"""
    exists = os.path.exists(path)
    mark, color = KINDS.get(os.path.splitext(path)[1].lower(), ("FILE", "#6B7286"))
    box = ctk.CTkFrame(parent, fg_color=T.SURFACE, corner_radius=12, border_width=1, border_color=T.BORDER)
    box.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(box, text=mark, width=40, height=40, corner_radius=8, fg_color=color, text_color="white",
                 font=T.font(13 if len(mark) == 1 else 10, "bold")).grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=10)
    ctk.CTkLabel(box, text=os.path.basename(path), font=T.font(11, "bold"), text_color=T.TEXT, anchor="w",
                 justify="left", wraplength=wrap - 70).grid(row=0, column=1, sticky="sw", pady=(9, 0))
    sub = f"{_size(os.path.getsize(path))}・{os.path.dirname(path)}" if exists else "ファイルが見つかりません（移動・削除された可能性）"
    ctk.CTkLabel(box, text=sub, font=T.font(9), text_color=T.SUB, anchor="w", justify="left",
                 wraplength=wrap - 70).grid(row=1, column=1, sticky="nw", pady=(0, 6))
    row = ctk.CTkFrame(box, fg_color="transparent")
    row.grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10))
    buttons = [("開く", lambda: open_file(path), True), ("ダウンロード", lambda: save_copy(box, path, on_done), False)]
    if not compact:
        buttons.append(("場所を開く", lambda: show_in_folder(path), False))
    for text, cmd, main in buttons:
        ctk.CTkButton(row, text=text, width=64 if main else 92, height=28, corner_radius=14, font=T.font(10, "bold" if main else "normal"),
                      fg_color=T.ACCENT if main else "transparent", hover_color=T.ACCENT_HOVER if main else T.BORDER,
                      border_width=0 if main else 1, border_color=T.BORDER, text_color="white" if main else T.TEXT,
                      state="normal" if exists else "disabled", command=cmd).pack(side="left", padx=(0, 6))
    return box
