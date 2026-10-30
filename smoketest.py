"""実際の Windows で本体を動かして確かめる(ビルド時に GitHub Actions の Windows で実行)。
本物のマウス・キーボード操作で、表示・文字入力・端のドラッグ・音声認識・送信を試し、
結果を results.txt に、画面写真を PNG に書き出す。強制終了した場合は results.txt が残らない。"""
import json
import os
import queue
import sys
import threading
import time
import traceback


def _walk(w):
    yield w
    for c in w.winfo_children():
        yield from _walk(c)


def run(out):
    os.makedirs(out, exist_ok=True)
    import numpy as np
    import pyautogui
    from PIL import ImageGrab

    import config
    from app import App

    pyautogui.FAILSAFE = False
    app = App()
    log, calls = [], queue.Queue()

    def note(text):
        log.append(text)
        print(text, flush=True)

    def on_main(fn):
        """画面の部品は Tk のスレッドでしか触れないので、そちらで実行して結果を受け取る。"""
        box = queue.Queue()
        calls.put((fn, box))
        return box.get(timeout=20)

    def pump():
        while not calls.empty():
            fn, box = calls.get()
            try:
                box.put(fn())
            except Exception as e:
                box.put(e)
        app.after(30, pump)

    def rect():
        return on_main(lambda: (app.winfo_rootx(), app.winfo_rooty(), app.winfo_width(), app.winfo_height()))

    def shot(name):
        x, y, w, h = rect()
        img = ImageGrab.grab(bbox=(x - 20, y - 20, x + w + 20, y + h + 20), all_screens=True)
        img.save(os.path.join(out, f"{name}.png"))
        arr = np.asarray(img.convert("RGB"), dtype=np.float32)
        inner = arr[20:-20, 20:-20]
        note(f"{name}: rect={x},{y},{w}x{h} 明るさ={inner.mean():.1f} 色の幅={inner.std():.1f}")
        return inner

    def drive():
        try:
            time.sleep(3)
            inner = shot("1_start")
            note("起動直後の表示: " + ("OK" if inner.std() > 12 else "NG(真っ黒/一色)"))

            on_main(lambda: app._show_panel())
            time.sleep(2)
            shot("2_panel")

            # 入力欄をクリックして文字を打つ
            ex, ey = on_main(lambda: (app.entry.winfo_rootx() + app.entry.winfo_width() // 2,
                                      app.entry.winfo_rooty() + app.entry.winfo_height() // 2))
            pyautogui.click(ex, ey)
            time.sleep(0.8)
            pyautogui.write("hello zealous", interval=0.05)
            time.sleep(0.8)
            typed = on_main(lambda: app.entry.get("1.0", "end").strip())
            note(f"文字入力: {'OK' if typed == 'hello zealous' else 'NG'} ({typed!r})")
            shot("3_typed")

            # 日本語入力(変換中 → 確定)を模擬して、入力欄への反映で落ちないか
            if app._ime:
                ops = app._ime["ops"]
                for op in (("pre", "あいう", 3), ("pre", "あいうえお", 5), ("result", "愛上尾"), ("end",)):
                    ops.put(op)
                    time.sleep(0.1)
                time.sleep(0.5)
                typed = on_main(lambda: app.entry.get("1.0", "end").strip())
                note(f"日本語入力(模擬): {'OK' if typed == 'hello zealous愛上尾' else 'NG'} ({typed!r})")
                # 再変換(「愛上尾」を選んで変換し直し →「藍上緒」で確定)
                for op in (("reconv", 1, 13, 16, True), ("pre", "愛上尾", 3), ("pre", "藍上緒", 3),
                           ("result", "藍上緒"), ("end",)):
                    ops.put(op)
                    time.sleep(0.1)
                time.sleep(0.5)
                typed = on_main(lambda: app.entry.get("1.0", "end").strip())
                note(f"再変換(模擬): {'OK' if typed == 'hello zealous藍上緒' else 'NG'} ({typed!r})")
                # 再変換を取り消したら元に戻る
                for op in (("reconv", 1, 13, 16, True), ("pre", "藍上緒", 3), ("end",)):
                    ops.put(op)
                    time.sleep(0.1)
                time.sleep(0.5)
                typed = on_main(lambda: app.entry.get("1.0", "end").strip())
                note(f"再変換の取り消し(模擬): {'OK' if typed == 'hello zealous藍上緒' else 'NG'} ({typed!r})")

            # 左辺をつかんで左へ広げる: 右辺は動かないこと
            x, y, w, h = rect()
            pyautogui.moveTo(x + 2, y + h // 2)
            pyautogui.mouseDown()
            right_during = []
            for i in range(1, 9):
                pyautogui.moveTo(x + 2 - i * 12, y + h // 2)
                time.sleep(0.08)
                nx, ny, nw, nh = rect()
                right_during.append(nx + nw)
            pyautogui.mouseUp()
            time.sleep(0.8)
            nx, ny, nw, nh = rect()
            moved = max(abs(r - (x + w)) for r in right_during)
            note(f"左辺のドラッグ: 幅 {w}→{nw}、右辺のずれ(ドラッグ中の最大) {moved}px "
                 + ("OK" if nw > w and moved <= 3 else "NG"))
            shot("4_resized")

            # 右下の角をつかんで斜めに広げる: 幅と高さが同時に変わること
            x, y, w, h = rect()
            g = app._grips["s"]  # 下の辺の右端(角)
            gx, gy = on_main(lambda: (g.winfo_rootx() + g.winfo_width() - 20, g.winfo_rooty() + 3))
            pyautogui.moveTo(gx, gy)
            pyautogui.mouseDown()
            for i in range(1, 7):
                pyautogui.moveTo(gx - i * 10, gy - i * 8)
                time.sleep(0.08)
            pyautogui.mouseUp()
            time.sleep(0.8)
            nx, ny, nw, nh = rect()
            img = ImageGrab.grab(bbox=(nx, ny, nx + 40, ny + 40), all_screens=True)  # 角に黒い四角が無いこと
            img.save(os.path.join(out, "4b_corner.png"))
            note(f"角のドラッグ(斜め): {w}x{h} → {nw}x{nh} " + ("OK" if nw < w and nh < h and (nx, ny) == (x, y) else "NG"))

            # 全画面にして戻す
            on_main(lambda: app._toggle_max())
            time.sleep(1.2)
            on_main(lambda: app._toggle_max())
            time.sleep(1.2)
            inner = shot("5_restored")
            note("全画面から戻した後の表示: " + ("OK" if inner.std() > 12 else "NG(真っ黒/一色)"))

            # 音声認識(待機中の聞き取りと同じ条件)を、雑音と無音で試す
            from voice import SR, VoiceInput
            m = app.voice._load("tiny")  # 本番と同じく、画面とは別のスレッドで読み込んで使う
            rng = np.random.default_rng(0)
            for name, audio in (("雑音", rng.normal(0, 0.05, SR * 2).astype(np.float32)),
                                ("無音", np.zeros(SR * 2, np.float32))):
                for button in (False, True):
                    text = VoiceInput.transcribe(m, audio, button)
                    note(f"音声認識({name}, {'ボタン' if button else '待機中'}): OK {text!r}")

            # 本番と同じく、別プロセスの音声認識で試す
            from whisper_worker import WhisperWorker
            config.WHISPER_MODEL = config.COMMAND_WHISPER_MODEL = "tiny"
            w = WhisperWorker(note)
            for button in (False, True):
                text = w.transcribe(rng.normal(0, 0.05, SR * 2).astype(np.float32), button)
                note(f"音声認識(別プロセス, {'ボタン' if button else '待機中'}): OK {text!r}")
            w.close()

            # 送信する(AI が動いていなくても、落ちずにエラーを表示できること)
            on_main(lambda: app._send_entry())
            time.sleep(6)
            shot("6_sent")
            note("送信: OK")

            # テクニカルモード: ボタンの色が変わり、コードは等幅の枠(コピーのボタン付き)で表示されること
            on_main(lambda: app._set_tech(True))
            box = on_main(lambda: app._log("括弧が閉じていません。\n```python\nprint('hi')\n```\n以上です。", "ai"))
            time.sleep(1)
            shot("6b_code")
            has_code = on_main(lambda: any(w.__class__.__name__ == "CTkTextbox" for w in _walk(box)))
            color = on_main(lambda: app.tech_btn.cget("fg_color"))
            note(f"テクニカルモード: {'OK' if has_code and color != 'transparent' else 'NG'} (コード枠={has_code}, ボタン={color})")
            badge = on_main(lambda: app.tech_badge.winfo_ismapped())
            border = on_main(lambda: app._input_box.cget("border_width"))
            on_main(lambda: app._set_tech(False))
            note(f"テクニカルモードの見た目: {'OK' if badge and border == 2 else 'NG'} (札={badge}, 縁={border})")
            # 資料づくりの札 → できたファイルの札(開く・保存)、複数選択コピー
            import tools
            on_main(lambda: setattr(app, "_pending_tid", app.thread["id"]))
            on_main(lambda: app._office_start())
            time.sleep(0.8)
            shot("6d_office_loading")
            loading = on_main(lambda: app.office_card.winfo_ismapped())
            sample_file = os.path.join(out, "office_test_card.docx")
            with open(sample_file, "wb") as f:
                f.write(b"x")
            on_main(lambda: app._on_reply("作りました" + tools.FILES + json.dumps([sample_file])))
            time.sleep(0.8)
            shot("6e_file_card")
            gone = on_main(lambda: not app.office_card.winfo_ismapped())
            saved = on_main(lambda: app.thread["messages"][-1].get("files"))
            note(f"資料づくりの表示とファイルの札: {'OK' if loading and gone and saved == [sample_file] else 'NG'}")
            on_main(lambda: app._log("一つ目", "user"))
            b2 = on_main(lambda: app._log("二つ目", "ai"))
            on_main(lambda: app._start_select(b2))
            on_main(lambda: app._toggle_select(app._bubbles[-2]))
            on_main(lambda: app._copy_selected())
            clip = on_main(lambda: app.clipboard_get())
            want = "あなた: 一つ目\n\n" + config.AI_NAME + ": 二つ目"
            note(f"複数選択コピー: {'OK' if clip == want else 'NG'} ({clip!r})")

            # Word・PowerPoint・Excel のファイルを作れること(exe の中に部品と雛形が入っているか)
            import officedoc
            sample = ("# 提案書\n概要\n\n## 背景\n- 人手不足\n- 自動化\n\n## 売上\n| 年度 | 売上(円) |\n|---|---|\n"
                      "| 2026 | 1,200 |\n| 2027 | 3,500 |\n\n## 手順\n1. 整理\n2. 導入\n")
            made = []
            for kind, make in officedoc.MAKERS.items():
                p = os.path.join(out, f"office_test.{kind}")
                make(officedoc.parse(sample), p)
                made.append(f"{kind}={os.path.getsize(p)}")
            note(f"Office のファイル作成: OK ({', '.join(made)})")
            import fonts
            picked = {k: fonts.pick(k)[:2] for k in fonts.STYLES}
            note(f"書体(このPCにあるもの): {picked} / 全{len(fonts.installed())}件")
            # 添付: 札が出て、×で外せること。ドラッグ＆ドロップを受け取る準備ができていること
            on_main(lambda: app._add_attachments([os.path.join(out, "office_test.xlsx"), out]))
            time.sleep(0.8)
            chips = on_main(lambda: len(app.attach_bar.winfo_children()))
            shot("6c_attach")
            on_main(lambda: [app._remove_attachment(p) for p in list(app.thread.get("attachments", []))])
            left = on_main(lambda: len(app.thread.get("attachments", [])))
            import dropfiles
            note(f"添付: {'OK' if chips == 2 and left == 0 and dropfiles._keep else 'NG'} (札={chips}, 外した後={left})")
            import attachments
            note("添付の読み取り: " + ("OK" if "シート" in attachments.material([os.path.join(out, "office_test.xlsx")])
                                     else "NG"))

            # 待機表示に戻し、マイクから音声会話画面を開いて閉じる
            on_main(lambda: app._show_pill())
            time.sleep(1.5)
            on_main(lambda: app.pill_mic.invoke())
            time.sleep(2.5)
            ok = on_main(lambda: app._voice_win is not None and app._voice_win.winfo_exists())
            if ok:
                vx, vy, vw, vh = on_main(lambda: (app._voice_win.winfo_rootx(), app._voice_win.winfo_rooty(),
                                                  app._voice_win.winfo_width(), app._voice_win.winfo_height()))
                ImageGrab.grab(bbox=(vx, vy, vx + vw, vy + vh), all_screens=True).save(os.path.join(out, "7_voice.png"))
                on_main(lambda: app._voice_win.close())
            note(f"音声会話画面: {'OK' if ok else 'NG'}")

            # ファイルを探す・開く: 本当のデスクトップに置いたファイルを、名前で探して開く
            import tools
            note(f"デスクトップの場所: {config.DESKTOP!r}")
            test_file = os.path.join(config.DESKTOP, "zealous_テンプレ_確認.txt")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("test")
            r = tools.run_tool("find_files", {"name": "zealous_テンプレ", "path": "デスクトップ"})
            note(f"ファイルを探す: {'OK' if test_file in r else 'NG'} ({r[:80]!r})")
            r = tools.run_tool("open_file", {"name": "zealous_テンプレ_確認"})
            time.sleep(3)
            import screen as _scr
            title = _scr.target_window()[1]
            note(f"ファイルを開く: {'OK' if 'zealous_テンプレ_確認' in title else 'NG'} ({r[:60]!r} / 手前: {title!r})")
            __import__("subprocess").run(["taskkill", "/F", "/IM", "notepad.exe"], capture_output=True)
            os.remove(test_file)

            # ファイルの中身で探して開く(名前ではなく、書かれていることで)
            import llm
            memo = os.path.join(config.DESKTOP, "zealous_中身テスト.txt")
            with open(memo, "w", encoding="cp932") as f:  # Windows のメモ帳の古い形式(Shift_JIS)
                f.write("ゼラスの動作確認。今日の合言葉はぶどう。")
            route = llm.quick_route("デスクトップにあるメモ帳のファイルから、ぶどうについての記載があるものを開いて")
            r = tools.run_tool(*route)
            time.sleep(3)
            title = _scr.target_window()[1]
            note(f"中身で探して開く: {'OK' if 'zealous_中身テスト' in title else 'NG'} ({route} → {r[:50]!r} / 手前: {title!r})")
            __import__("subprocess").run(["taskkill", "/F", "/IM", "notepad.exe"], capture_output=True)
            os.remove(memo)
            # 名前の変更(フォルダ)。メールの裏側の操作は、アカウントが無いので「設定がまだ」と答えること
            folder = os.path.join(config.DESKTOP, "zealous_フォルダ")
            os.makedirs(folder, exist_ok=True)
            r = tools.run_tool("rename_item", {"name": "zealous_フォルダ", "new_name": "zealous_名前変更"})
            renamed = os.path.join(config.DESKTOP, "zealous_名前変更")
            note(f"フォルダの名前を変える: {'OK' if os.path.isdir(renamed) else 'NG'} ({r!r})")
            os.rmdir(renamed) if os.path.isdir(renamed) else os.rmdir(folder)
            r = tools.run_tool("mail_mark_read", {"folder": "迷惑メール"})
            note(f"メール(未設定): {'OK' if '設定' in r else 'NG'} ({r[:40]!r})")
            import secret
            enc = secret.protect("テスト用パスワード")
            note(f"パスワードの暗号化保存: {'OK' if secret.reveal(enc) == 'テスト用パスワード' and 'テスト' not in enc else 'NG'}")

            # 画面の直接操作: メモ帳に日本語を入力し、キー操作で選択・コピーして確かめる
            import subprocess as sp
            import tools
            import screen
            config.SCREEN_CONTROL_ENABLED = True
            pad = sp.Popen(["notepad.exe"])
            time.sleep(3)
            hwnd, title = screen.target_window()
            note(f"操作の相手: {title!r}")
            pyautogui.moveTo(30, 30)
            before = pyautogui.position()
            note("文字入力: " + tools.run_tool("type_text", {"text": "こんにちは Zealous"}))
            note(f"マウスを動かさずに入力: {'OK' if pyautogui.position() == before else 'NG'}")
            note("キー: " + tools.run_tool("press_keys", {"keys": "ctrl+a"}))
            tools.run_tool("press_keys", {"keys": "ctrl+c"})
            time.sleep(0.5)
            got = screen._ps("Get-Clipboard -Raw")
            note(f"画面の直接操作(メモ帳): {'OK' if 'こんにちは Zealous' in got else 'NG'} ({got[:30]!r})")
            # ウィンドウの操作: 最小化して、名前で切り替えて戻す
            note("最小化: " + tools.run_tool("window_action", {"action": "minimize"}))
            time.sleep(1)
            minimized = bool(__import__("ctypes").windll.user32.IsIconic(hwnd))
            note("切り替え: " + tools.run_tool("switch_window", {"name": "Notepad"}))
            time.sleep(1)
            back = not __import__("ctypes").windll.user32.IsIconic(hwnd)
            note(f"ウィンドウの操作: {'OK' if minimized and back else 'NG'}")
            note("部品の一覧(確認用): " + screen.list_controls(hwnd)[:300])
            note("メニュー: " + tools.run_tool("click_on", {"label": "File"}))
            pyautogui.press("esc")
            pad.kill()
            # ふつうのボタン: 「テストボタン」だけの小さな窓を出し、名前で押せるか(押すとファイルができる)
            flag = os.path.join(out, "clicked.txt")
            form = sp.Popen(["powershell", "-NoProfile", "-Command",
                             "Add-Type -AssemblyName System.Windows.Forms;"
                             "$f=New-Object Windows.Forms.Form; $f.Text='Zealous Test'; $f.TopMost=$true;"
                             "$b=New-Object Windows.Forms.Button; $b.Text='テストボタン'; $b.Width=160; $b.Height=40;"
                             f"$b.Add_Click({{ Set-Content -Path '{flag}' -Value ok; $f.Close() }});"
                             "$f.Controls.Add($b); [void]$f.ShowDialog()"])
            time.sleep(4)
            note("ボタンの窓: " + repr(screen.target_window()[1]))
            pyautogui.moveTo(30, 30)
            before = pyautogui.position()
            note("ボタン: " + tools.run_tool("click_on", {"label": "テストボタン"}))
            note(f"マウスを動かさずに押す: {'OK' if pyautogui.position() == before else 'NG'}")
            time.sleep(1.5)
            note(f"名前でボタンを押す: {'OK' if os.path.exists(flag) else 'NG'}")
            form.kill()
            # ゼラス用ブラウザ(Chrome/Edge)のページの中を、名前で操作する(マウス・キーボードは使わない)
            import functools
            import http.server
            import browser
            import llm
            with open(os.path.join(out, "web.html"), "w", encoding="utf-8") as f:
                f.write("<!doctype html><meta charset=utf-8><title>Zealous Web Test</title><body style='height:3000px'>"
                        "<p>ゼラスのテストページです。今日の合言葉は「みかん」。</p>"
                        "<button onclick=\"document.title='clicked ok'\">ウェブのテストボタン</button>"
                        "<input type=search placeholder='サイト内検索' onkeydown=\"if(event.key==='Enter')document.body.dataset.q=this.value\">"
                        "<select><option>りんご</option><option>みかん</option></select>"
                        "<button>購入する</button><a href='#next'>次のページへ</a>")
            class Quiet(http.server.SimpleHTTPRequestHandler):
                def log_message(self, *args):  # 画面だけのアプリには書き出し先(stderr)が無いので、記録しない
                    pass
            handler = functools.partial(Quiet, directory=out)
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8766), handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            note(f"操作できるブラウザ: {browser.exe()!r}")
            browser.launch("http://127.0.0.1:8766/web.html")
            time.sleep(6)
            note(f"ブラウザが手前: {'OK' if browser.active() else 'NG'} ({screen.target_window()[1]!r})")
            pyautogui.moveTo(30, 30)
            before = pyautogui.position()
            route = llm.quick_route("ウェブのテストボタンを押して")
            note(f"ページのボタン: {route} → {tools.run_tool(*route)}")
            time.sleep(1)
            note(f"ページの中のボタンを押す: {'OK' if browser.read()[0] == 'clicked ok' else 'NG'}")
            route = llm.quick_route("サイト内検索にねこと入力して検索して")
            note(f"入力: {route} → {tools.run_tool(*route)}")
            with browser.Page() as p:
                got = p.js("document.body.dataset.q")
            note(f"ページの入力欄に入れて決定: {'OK' if got == 'ねこ' else 'NG'} ({got!r})")
            note("選ぶ: " + tools.run_tool("web_select", {"option": "みかん"}))
            note("スクロール: " + llm._run(*llm.quick_route("下にスクロールして")))
            with browser.Page() as p:
                y = p.js("scrollY")
            note(f"ページのスクロール: {'OK' if y and y > 0 else 'NG'} ({y})")
            res = tools.run_tool("web_click", {"target": "購入する"})
            note(f"購入ボタンは確認する: {'OK' if tools.CONFIRM in res else 'NG'}")
            note(f"マウスを動かさずに操作: {'OK' if pyautogui.position() == before else 'NG'}")
            title, url, text = browser.read()
            note(f"ページを読む: {'OK' if '合言葉' in text else 'NG'}")
            img = ImageGrab.grab(all_screens=True)
            img.save(os.path.join(out, "7_browser.png"))
            srv.shutdown()
            config.SCREEN_CONTROL_ENABLED = False

            # 設定画面を開いて(入力欄すべてに日本語入力の処理が付く)、入力欄に打って保存する(閉じないこと)
            on_main(lambda: app.open_settings())
            time.sleep(2.5)
            win = on_main(lambda: app._settings)
            kind, var = on_main(lambda: win._vars["AI_NAME"])
            entry = on_main(lambda: next(w for w in _walk(win) if w.__class__.__name__ == "Entry"))
            ex, ey = on_main(lambda: (entry.winfo_rootx() + 20, entry.winfo_rooty() + entry.winfo_height() // 2))
            pyautogui.click(ex, ey)
            time.sleep(0.5)
            pyautogui.press("end")
            pyautogui.write("X", interval=0.05)
            time.sleep(0.5)
            on_main(lambda: win._save())
            time.sleep(1.0)
            ImageGrab.grab(bbox=on_main(lambda: (win.winfo_rootx(), win.winfo_rooty(), win.winfo_rootx() + win.winfo_width(),
                                                 win.winfo_rooty() + win.winfo_height())), all_screens=True).save(
                os.path.join(out, "8_settings.png"))
            # 設定のタブ分け・詳細設定の開閉・マイクテスト(このPCにマイクが無くても落ちないこと)
            on_main(lambda: (win.search.delete(0, "end"), win._filter("")))  # 上の入力の確かめで検索欄に入った文字を消す
            on_main(lambda: win._select("マイク"))
            hidden = on_main(lambda: not win._rows["VAD_THRESHOLD"].winfo_ismapped())
            page = on_main(lambda: win._pages["マイク"])
            on_main(lambda: win._toggle_adv(page))
            time.sleep(0.5)
            shown = on_main(lambda: win._rows["VAD_THRESHOLD"].winfo_ismapped())
            note(f"設定の詳細設定の開閉: {'OK' if hidden and shown else 'NG'} (閉={hidden}, 開={shown})")
            on_main(lambda: win._toggle_adv(page))
            on_main(lambda: win._mic_test())
            time.sleep(8)
            msg = on_main(lambda: win.mic_msg.cget("text"))
            busy = on_main(lambda: win._mic_busy)
            note(f"マイクテスト: {'OK' if not busy and msg else 'NG'} ({msg[:60]!r})")
            ImageGrab.grab(bbox=on_main(lambda: (win.winfo_rootx(), win.winfo_rooty(), win.winfo_rootx() + win.winfo_width(),
                                                 win.winfo_rooty() + win.winfo_height())), all_screens=True).save(
                os.path.join(out, "9_settings_mic.png"))
            note(f"設定のタブ: {len(on_main(lambda: win._tab_btns))}")
            still = on_main(lambda: win.winfo_exists())
            note(f"設定の保存(画面は閉じない): {'OK' if still else 'NG'} 名前={config.AI_NAME!r}")
            on_main(lambda: win.destroy())
            note("ALL DONE")
        except Exception:
            note("エラー: " + traceback.format_exc())
        finally:
            with open(os.path.join(out, "results.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(log))
            os._exit(0)

    app.after(100, pump)
    threading.Thread(target=drive, daemon=True).start()
    app.mainloop()


if __name__ == "__main__":
    run(sys.argv[1])
