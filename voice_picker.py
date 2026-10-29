"""声を選ぶ画面。キャラクターの一覧から試聴して選ぶと、その声のモデルだけをダウンロードする。"""
import io
import threading

import customtkinter as ctk
from PIL import Image

import config
import runtime
import services
import theme as T
import voicevox
from gallery import _pool

ICON = 44


class VoicePicker(ctk.CTkToplevel):
    def __init__(self, master, play_wav, say, on_changed=None):
        """play_wav(bytes): 試聴音を鳴らす / say(text): 選んだ声で話す / on_changed(): 声が変わったとき"""
        super().__init__(master, fg_color=T.BG)
        self._play_wav, self._say, self._on_changed = play_wav, say, on_changed
        self.title("声を選ぶ")
        self.geometry("600x660")
        self.attributes("-topmost", True)
        self._busy = False
        self._cards = []

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(18, 4))
        ctk.CTkLabel(head, text="声を選ぶ", font=T.font(17, "bold"), text_color=T.TEXT).pack(anchor="w")
        ctk.CTkLabel(head, text="「試聴」で聞き比べて、「この声にする」を押すと、その声のモデル（約55MB）だけを"
                                "ダウンロードします。使わなくなった声のモデルは自動で削除します。",
                     font=T.font(11), text_color=T.SUB, justify="left", wraplength=550).pack(anchor="w", pady=(4, 0))

        self.search = ctk.CTkEntry(self, placeholder_text="キャラクター名で探す", fg_color=T.SURFACE,
                                   border_color=T.BORDER, font=T.font(12), height=34)
        self.search.pack(fill="x", padx=20, pady=(10, 6))
        self.search.bind("<KeyRelease>", lambda e: self._filter())

        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=T.BORDER)
        self.list.pack(fill="both", expand=True, padx=12)

        foot = ctk.CTkFrame(self, fg_color=T.SURFACE, corner_radius=0)
        foot.pack(fill="x", side="bottom")
        self.status = ctk.CTkLabel(foot, text="", font=T.font(11), text_color=T.SUB, anchor="w")
        self.status.pack(fill="x", padx=20, pady=(10, 4))
        self.bar = ctk.CTkProgressBar(foot, height=6, progress_color=T.ACCENT, fg_color=T.BG)
        self.bar.set(0)

        if not voicevox.cached_catalog():
            self.status.configure(text="声の一覧を取得中…")
            threading.Thread(target=self._load_catalog, daemon=True).start()
        else:
            self._build()

    # ---------------- 一覧 ----------------
    def _load_catalog(self):
        try:
            voicevox.catalog()
            self.after(0, self._build)
        except Exception as e:
            err = f"声の一覧を取得できませんでした: {e}"
            self.after(0, lambda: self.status.configure(text=err))

    def _build(self):
        have = voicevox.installed_models()
        current = config.VOICEVOX_SPEAKER
        for sp in voicevox.speakers():
            self._cards.append(self._card(sp, have, current))
        self._update_status()

    def _card(self, sp, have, current):
        card = ctk.CTkFrame(self.list, fg_color=T.SURFACE, corner_radius=14)
        card.pack(fill="x", padx=4, pady=4)
        card.grid_columnconfigure(1, weight=1)
        icon = ctk.CTkLabel(card, text="", width=ICON, height=ICON, fg_color=T.BG, corner_radius=0)
        icon.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=10)
        self._load_icon(icon, sp)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.grid(row=0, column=1, sticky="w", pady=(10, 0))
        ctk.CTkLabel(top, text=sp["name"], font=T.font(13, "bold"), text_color=T.TEXT).pack(side="left")
        badge = ctk.CTkLabel(top, text="", font=T.font(10), corner_radius=8, height=18, padx=8)
        badge.pack(side="left", padx=8)

        names = [s["style"] for s in sp["styles"]]
        style = ctk.StringVar(value=next((s["style"] for s in sp["styles"] if s["id"] == current), names[0]))
        if len(names) > 1:
            menu = ctk.CTkSegmentedButton(card, values=names[:6], variable=style, font=T.font(10), height=24,
                                          selected_color=T.ACCENT, selected_hover_color=T.ACCENT_HOVER,
                                          unselected_color=T.BG, fg_color=T.BG) if len(names) <= 6 else \
                ctk.CTkOptionMenu(card, values=names, variable=style, width=160, height=24, font=T.font(10),
                                  fg_color=T.BG, button_color=T.BG, button_hover_color=T.BORDER)
            menu.grid(row=1, column=1, sticky="w", pady=(4, 10))
        else:
            ctk.CTkLabel(card, text=names[0], font=T.font(10), text_color=T.SUB).grid(
                row=1, column=1, sticky="w", pady=(0, 10))

        sid = lambda: next(s["id"] for s in sp["styles"] if s["style"] == style.get())  # noqa: E731
        ctk.CTkButton(card, text="▶ 試聴", width=72, height=30, corner_radius=15, font=T.font(11),
                      fg_color="transparent", border_width=1, border_color=T.BORDER, hover_color=T.BG,
                      text_color=T.TEXT, command=lambda: self._preview(sp, sid())).grid(
            row=0, column=2, rowspan=2, padx=4)
        choose = ctk.CTkButton(card, text="この声にする", width=104, height=30, corner_radius=15,
                               font=T.font(11, "bold"), fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER,
                               command=lambda: self._choose(sp, sid()))
        choose.grid(row=0, column=3, rowspan=2, padx=(4, 12))
        entry = {"sp": sp, "frame": card, "badge": badge, "choose": choose, "style": style}
        self._paint(entry, have, current)
        return entry

    def _paint(self, c, have, current):
        """使用中 / ダウンロード済み / サイズ の印を付ける。"""
        sp = c["sp"]
        if any(s["id"] == current for s in sp["styles"]):
            c["badge"].configure(text="使用中", fg_color=T.ACCENT, text_color="white")
        elif sp["vvm"] in have:
            c["badge"].configure(text="ダウンロード済み", fg_color=T.BG, text_color=T.OK)
        else:
            c["badge"].configure(text=f"⬇ {sp['mb']}MB", fg_color=T.BG, text_color=T.SUB)

    def _load_icon(self, label, sp):
        def job():
            try:
                img = Image.open(io.BytesIO(voicevox.icon_bytes(sp["uuid"], sp["styles"][0]["id"]))).convert("RGBA")
            except Exception:
                return
            img = img.resize((ICON, ICON), Image.LANCZOS)
            self.after(0, lambda: label.winfo_exists() and label.configure(
                image=ctk.CTkImage(img, size=(ICON, ICON))))
        _pool.submit(job)

    def _filter(self):
        q = self.search.get().strip()
        for c in self._cards:
            c["frame"].pack_forget()
        for c in self._cards:
            if not q or q in c["sp"]["name"]:
                c["frame"].pack(fill="x", padx=4, pady=4)

    def _update_status(self):
        cur = next((v for v in voicevox.cached_catalog() if v["id"] == config.VOICEVOX_SPEAKER), None)
        self.status.configure(text=f"いまの声: {voicevox.label(cur) if cur else config.VOICEVOX_SPEAKER}")

    # ---------------- 試聴・決定 ----------------
    def _preview(self, sp, style_id):
        self.status.configure(text=f"{sp['name']} の試聴音を取得中…")

        def job():
            try:
                wav = voicevox.sample_wav(sp["uuid"], style_id)
            except Exception as e:
                err = f"試聴音を取得できませんでした: {e}"
                self.after(0, lambda: self.status.configure(text=err))
                return
            self.after(0, lambda: self.status.configure(text=f"▶ {sp['name']} を再生中"))
            self._play_wav(wav)
        threading.Thread(target=job, daemon=True).start()

    def _choose(self, sp, style_id):
        if self._busy:
            return
        if not runtime.voicevox_exe() and not services.check_voicevox()[0]:
            self.status.configure(text="先に「更新・情報」タブの「部品を準備」で VOICEVOX を準備してください")
            return
        self._busy = True
        config.save({"VOICEVOX_SPEAKER": style_id})
        self.bar.pack(fill="x", padx=20, pady=(0, 12))
        self.bar.set(0)
        name = sp["name"]

        def progress(ratio, text):
            self.after(0, lambda: (self.winfo_exists() and self.status.configure(text=f"{name}: {text}"),
                                   ratio is not None and self.winfo_exists() and self.bar.set(ratio)))

        def job():
            try:
                if runtime.voicevox_exe():  # Zealous が管理している VOICEVOX のときだけモデルを入れ替える
                    voicevox.install_voice(style_id, progress)
                    progress(None, "読み込み中…")
                    runtime.restart_voicevox()
                    runtime.wait_voicevox()
                progress(1, "この声になりました")
                self._say(f"{name}です。よろしくお願いします。")
            except Exception as e:
                err = f"失敗しました（{e}）"
                progress(0, err)
            self.after(0, self._done)
        threading.Thread(target=job, daemon=True).start()

    def _done(self):
        self._busy = False
        if not self.winfo_exists():
            return
        have = voicevox.installed_models()
        for c in self._cards:
            self._paint(c, have, config.VOICEVOX_SPEAKER)
        if self._on_changed:
            self._on_changed()
