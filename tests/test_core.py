import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import llm  # noqa: E402
import tools  # noqa: E402
from wakeword import strip_wake_word, voice_command  # noqa: E402


def test_wake_word():
    assert strip_wake_word("ウェイク、ゼラス、メモ帳を作って") == "メモ帳を作って"
    assert strip_wake_word("Wake Zealous open youtube") == "open youtube"
    assert strip_wake_word("ゼラス、音量を50に") is None
    assert strip_wake_word("今日の天気は？") is None


def test_rename_ai(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path))
    config.save({"AI_NAME": "アトラス", "AI_NAME_ALIASES": []})
    assert strip_wake_word("ウェイク、アトラス、検索して") == "検索して"
    assert strip_wake_word("ウェイク、ゼラス、検索して") is None
    config.reset()
    config.load()
    assert config.AI_NAME == "Zealous"


def test_parse_tool_calls():
    msg = {"tool_calls": [{"function": {"name": "web_search", "arguments": {"query": "猫"}}}]}
    assert llm.parse_tool_calls(msg) == [("web_search", {"query": "猫"})]
    msg = {"content": '{"name": "lock_screen", "arguments": {}}'}
    assert llm.parse_tool_calls(msg) == [("lock_screen", {})]
    assert llm.parse_tool_calls({"content": "こんにちは"}) == []


def test_run_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DESKTOP", str(tmp_path))
    tools.run_tool("create_text_file", {"name": "memo", "content": "abc", "bogus": 1})
    assert (tmp_path / "memo.txt").read_text(encoding="utf-8") == "abc"
    assert "対応していません" in tools.run_tool("nope", {})
    monkeypatch.setattr(config, "DRY_RUN", True)
    assert tools.run_tool("lock_screen", {}).startswith("[DRY]")


def test_ask_with_mock(monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", True)
    monkeypatch.setattr(llm, "_chat", lambda m, use_tools=True, **kw: {
        "tool_calls": [{"function": {"name": "open_url", "arguments": {"url": "example.com"}}}]})
    assert llm.ask("example.comを開いて").startswith("[DRY] open_url")


def test_folder_ops(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DESKTOP", str(tmp_path))
    tools.run_tool("create_folder", {"name": "A"})
    tools.run_tool("create_text_file", {"name": "m", "content": "x"})
    assert "[A]" in tools.run_tool("list_folder", {"path": str(tmp_path)})
    tools.run_tool("rename_item", {"name": "m.txt", "new_name": "n.txt"})
    tools.run_tool("move_item", {"name": "n.txt", "dest": str(tmp_path / "A")})
    assert (tmp_path / "A" / "n.txt").exists()
    tools.run_tool("copy_item", {"name": "A", "dest": str(tmp_path / "B")})
    assert (tmp_path / "B" / "A" / "n.txt").exists()
    # ホームフォルダそのものや設定で禁止された操作は拒否
    assert "できませんでした" in tools.run_tool("rename_item", {"name": os.path.expanduser("~"), "new_name": "x"})
    monkeypatch.setattr(config, "FOLDER_OPS_ENABLED", False)
    assert "無効" in tools.run_tool("create_folder", {"name": "C"})


def test_version_compare():
    import updater
    assert updater._ver("v1.10.0") > updater._ver("1.9.9")
    assert updater._ver("1.0") == updater._ver("v1.0.0")


def test_voice_models(tmp_path, monkeypatch):
    import json
    import voicevox
    cat = tmp_path / "cat.json"
    cat.write_text(json.dumps([{"id": 3, "speaker": "ずんだもん", "style": "ノーマル", "vvm": "0.vvm", "mb": 56, "uuid": "z"},
                               {"id": 8, "speaker": "春日部つむぎ", "style": "ノーマル", "vvm": "0.vvm", "mb": 56, "uuid": "k"},
                               {"id": 13, "speaker": "青山龍星", "style": "ノーマル", "vvm": "15.vvm", "mb": 63, "uuid": "a"}]),
                   encoding="utf-8")
    monkeypatch.setattr(voicevox, "CATALOG", str(cat))
    monkeypatch.setattr(voicevox, "BUNDLED", str(cat))
    monkeypatch.setattr(voicevox, "MODEL_DIR", str(tmp_path / "model"))
    assert voicevox.needs_change(3)                     # まだ何も入っていない
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "0.vvm").write_bytes(b"")
    assert not voicevox.needs_change(8)                 # 同じモデルに入っている声
    assert voicevox.needs_change(13)                    # 別のモデルが必要
    assert voicevox.install_voice(8, lambda *a: None) is False
    assert [(sp["name"], [st["id"] for st in sp["styles"]]) for sp in voicevox.speakers()] == [
        ("ずんだもん", [3]), ("春日部つむぎ", [8]), ("青山龍星", [13])]


def test_settings_fields():
    import pytest
    sw = pytest.importorskip("settings_window")  # 画面部品(tkinter)が無い環境では飛ばす
    assert {f[0] for f in sw.FIELDS} <= set(config.DEFAULTS)
    assert sw.parse("list", "a、b, ,c") == ["a", "b", "c"]


def test_voice_command():
    assert voice_command("メモ帳を開いて", True) == "メモ帳を開いて"            # ボタン: 合図不要
    assert voice_command("ウェイク、Zealous、メモ帳を開いて", True) == "メモ帳を開いて"
    assert voice_command("メモ帳を開いて", False) is None                      # 常時待ち受け: 合図が必要
    assert voice_command("ウェイク、Zealous、メモ帳を開いて", False) == "メモ帳を開いて"


def test_search_summary(monkeypatch):
    import websearch
    monkeypatch.setattr(websearch, "search", lambda q, limit=5: [{"title": "A", "url": "https://a", "snippet": "a"},
                                                        {"title": "B", "url": "https://b", "snippet": "b"}])
    monkeypatch.setattr(websearch, "read_pages", lambda r, count=3, limit=1500: ["本文A", "本文B"])
    monkeypatch.setattr(websearch, "images", lambda q, limit=30: [{"thumb": "t"}])
    monkeypatch.setattr(llm, "_chat", lambda m, use_tools=True, **kw: {"content": "要約です"})
    body, sources, images = llm.split_reply(tools.run_tool("search_summary", {"query": "猫"}))
    assert body == "要約です" and sources == "[1] A\nhttps://a\n[2] B\nhttps://b"
    assert images == {"query": "猫", "items": [{"thumb": "t"}], "open": False}  # 関連画像は一覧を自動で開かない


def test_parse_bing():
    import base64
    import websearch
    url = "https://example.com/page"
    enc = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    page = (f'<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?!&amp;u=a1{enc}&amp;ntb=1">'
            '<strong>例</strong>のページ</a></h2><p>説明&amp;文</p></li>')
    assert websearch.parse_bing(page) == [{"title": "例のページ", "url": url, "snippet": "説明&文"}]


def test_find_app():
    import apps
    found = [{"Name": "Excel", "AppID": "1"}, {"Name": "Excel 2016 Database Compare", "AppID": "2"},
             {"Name": "Microsoft Edge", "AppID": "3"}]
    assert apps.find("エクセル", found)["AppID"] == "1"
    assert apps.find("edge", found)["AppID"] == "3"
    assert apps.find("存在しないアプリ", found) is None


def test_conversation_memory(monkeypatch):
    seen = []
    monkeypatch.setattr(config, "CONTEXT_TURNS", 1)
    monkeypatch.setattr(llm, "_chat", lambda m, use_tools=True, **kw: (seen.append(m), {"content": "はい"})[1])
    llm._history.clear()
    llm.ask("一つ目")
    llm.ask("二つ目")
    llm.ask("三つ目")
    contents = [m["content"] for m in seen[-1]]
    assert "二つ目" in contents and "一つ目" not in contents   # 直前の1往復だけ覚えている


def test_image_search(monkeypatch):
    import websearch
    items = [{"thumb": "t", "mid": "m", "full": "f", "title": "りんご", "page": "p"}]
    monkeypatch.setattr(websearch, "images", lambda q, limit=30: items)
    body, sources, images = llm.split_reply(tools.run_tool("image_search", {"query": "リンゴ"}))
    assert "1枚" in body and sources == ""
    assert images == {"query": "リンゴ", "items": items, "open": True}


def test_parse_yahoo_images():
    import json
    import websearch
    data = {"props": {"initialProps": {"pageProps": {"algos": [
        {"title": "赤いリンゴ", "refererUrl": "https://ex.jp", "thumbnail": {"url": "https://t"},
         "main": {"url": "https://m"}, "original": {"url": "https://o"}}]}}}}
    page = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    assert websearch.parse_yahoo_images(page) == [
        {"thumb": "https://t", "mid": "https://m", "full": "https://o", "title": "赤いリンゴ", "page": "https://ex.jp"}]


def test_model_labels():
    import models
    text = models.label("qwen2.5:3b")
    assert "1.9GB" in text and models.name_of(text) == "qwen2.5:3b"
    assert models.name_of("gemma2:2b") == "gemma2:2b"          # 手入力の名前はそのまま
    assert "1.9GB" in models.warning("qwen2.5:3b")              # 変更時は必ずサイズを伝える


def test_ollama_members():
    import runtime
    names = ["ollama.exe", "lib/ollama/ggml-cpu.dll", "lib/ollama/cuda_v12/cublas.dll",
             "lib/ollama/cuda_v13/cublas.dll", "lib/ollama/vulkan/ggml-vulkan.dll"]
    assert [n for n in names if runtime.ollama_member(n, None)] == [names[0], names[1], names[4]]
    assert [n for n in names if runtime.ollama_member(n, "cuda_v13")] == [names[0], names[1], names[3], names[4]]


def test_quick_route():
    assert llm.quick_route("リンゴの写真探しておいて") == ("image_search", {"query": "リンゴ"})
    assert llm.quick_route("Excelを起動して") == ("launch_app", {"name": "Excel"})
    assert llm.quick_route("東京タワーについて調べてください") == ("search_summary", {"query": "東京タワー"})
    assert llm.quick_route("あなたの名前を教えて") is None          # 会話はAIに任せる
    assert llm.quick_route("ブラウザで天気を検索して") is None      # ブラウザ指定はAIに任せる


def test_streaming_chat(monkeypatch):
    import json

    class Resp:
        def __init__(self, lines):
            self.lines = lines

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def raise_for_status(self):
            pass

        def iter_lines(self):
            return [json.dumps({"message": {"content": c}}).encode() for c in self.lines]

    got = []
    monkeypatch.setattr(llm, "on_delta", got.append)
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: Resp(["こんに", "ちは。", "元気です"]))
    assert llm._chat([], stream_out=True)["content"] == "こんにちは。元気です"
    assert got == ["こんに", "ちは。", "元気です"]               # 届いた分から順に渡す
    got.clear()
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: Resp(['{"name": "lock_screen"', "}"]))
    llm._chat([], stream_out=True)
    assert got == []                                           # 関数呼び出しのJSONは画面に出さない


def test_split_sentences():
    from tts import split_sentences
    assert split_sentences("はい。わかりました！次は？") == ["はい。", "わかりました！", "次は？"]
    assert split_sentences("短い、文。") == ["短い、文。"]


def test_threads(tmp_path, monkeypatch):
    import threads
    monkeypatch.setattr(threads, "DIR", str(tmp_path))
    t = threads.new()
    assert threads.listing() == []                      # まだ何も話していないスレッドは出さない
    threads.add(t, "user", "ポメラニアンの性格を調べて")
    threads.add(t, "ai", "明るい性格です。", sources="[1] A\nhttps://a")
    threads.add(t, "user", "寿命は？")
    threads.add(t, "ai", "12〜16年ほどです。")
    assert t["title"] == "ポメラニアンの性格を調べて"
    assert threads.history(t, 1) == [("寿命は？", "12〜16年ほどです。")]
    assert threads.load(t["id"])["messages"][1]["sources"] == "[1] A\nhttps://a"
    assert [x["id"] for x in threads.listing()] == [t["id"]]
    threads.delete(t["id"])
    assert threads.listing() == []


def test_space_ptt(monkeypatch):
    """スペースキー: 長押しで話す、短く押せば普通のスペースを入力し直す。"""
    import time
    import types
    import stopper
    events, sent, hooks = [], [], []
    fake = types.SimpleNamespace(KEY_DOWN="down", hook=lambda cb, suppress=False: hooks.append(cb) or (lambda: None),
                                 unhook=lambda h: None, send=lambda k: sent.append(k))
    monkeypatch.setitem(__import__("sys").modules, "keyboard", fake)
    stopper.register_ptt("space", lambda: events.append("start"), lambda: events.append("stop"))
    press = lambda t: hooks[-1](types.SimpleNamespace(name="space", event_type=t))  # noqa: E731
    assert press("down") is False and press("up") is False          # 短く押す: 一旦止めて…
    time.sleep(0.05)
    assert sent == ["space"] and events == []                         # 普通のスペースとして入力し直す
    assert press("down") is True and press("up") is True             # 入力し直した分は通す
    press("down")
    time.sleep(stopper.HOLD_SEC + 0.1)
    press("up")
    assert events == ["start", "stop"]                                # 長押し: 話す
    assert hooks[-1](types.SimpleNamespace(name="a", event_type="down")) is True  # 他のキーは通す


def test_transcribe_tuning():
    import numpy as np
    from voice import VoiceInput, SR
    calls = []

    class FakeModel:
        def __init__(self, text):
            self.text = text

        def transcribe(self, audio, **kw):
            calls.append(kw)
            return [type("S", (), {"text": self.text})()], None

    speech = (np.sin(np.arange(SR) / 5) * 0.05).astype(np.float32)   # 小さめの声 1秒
    assert VoiceInput.transcribe(FakeModel("メモ帳を開いて"), speech, True) == "メモ帳を開いて"
    assert calls[-1]["vad_filter"] is False                              # ボタンで録った音は切り落とさない
    assert VoiceInput.transcribe(FakeModel("ご視聴ありがとうございました"), speech, True) == ""  # 決まり文句は捨てる
    assert VoiceInput.transcribe(FakeModel("x"), np.zeros(SR, np.float32), True) == ""             # 無音
    assert VoiceInput.transcribe(FakeModel("x"), speech[:SR // 10], True) == ""                     # 短すぎる


def test_search_relevance():
    import json
    import websearch
    data = {"props": {"pageProps": {"initialProps": {"pageData": {"algos": [
        {"title": "<b>株式会社 才</b>（さい）", "url": "https://sai.example.jp/", "description": "Web制作の<b>株式会社才</b>"}]}}}}}
    page = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    assert websearch.parse_yahoo_web(page) == [
        {"title": "株式会社 才（さい）", "url": "https://sai.example.jp/", "snippet": "Web制作の株式会社才"}]
    general = {"title": "株式会社とは？仕組みを解説", "url": "https://kaisha.example.jp/", "snippet": "株式会社の基本"}
    exact = {"title": "株式会社 才 会社概要", "url": "https://sai.example.jp/", "snippet": ""}
    assert websearch.is_relevant("株式会社才", exact) and not websearch.is_relevant("株式会社才", general)
    assert websearch.relevance("株式会社才", exact) > websearch.relevance("株式会社才", general)


def test_image_queries():
    import websearch
    assert websearch.image_queries("きれいなりんご") == ["りんご きれい", "りんご 高画質"]
    assert llm.quick_route("きれいなりんごの画像調べて") == ("image_search", {"query": "きれいなりんご"})


def test_wake_only_opens_chat():
    from wakeword import strip_wake_word
    assert strip_wake_word("ウェイク、ゼラス。") == ""
    assert strip_wake_word("ウェーク ゼラス、天気を教えて") == "天気を教えて"
    assert strip_wake_word("今日はいい天気") is None


def test_safe_only_and_chunks(monkeypatch):
    import websearch
    monkeypatch.setattr(websearch, "host_is_safe", lambda h: h != "bad.example")
    items = [{"url": "https://ok.example/a"}, {"url": "https://bad.example/x"}, {"url": "http://1.2.3.4/"}]
    assert websearch.safe_only(items, "url") == [items[0]]
    a = [{"full": f"https://ok.example/a{i}", "page": "https://ok.example"} for i in range(8)]
    b = [{"full": f"https://ok.example/b{i}", "page": "https://ok.example"} for i in range(8)]
    monkeypatch.setattr(websearch, "image_queries", lambda q: ["x", "y"])
    monkeypatch.setattr(websearch, "_images_one", lambda q, n: a if q == "x" else b)
    got = [it["full"].rsplit("/", 1)[1] for it in websearch.images("q", 10)]
    assert got == ["a0", "a1", "a2", "a3", "b0", "b1", "b2", "b3", "a4", "a5"]


def test_persona_parse():
    import persona
    assert persona.parse("関西弁で話して") == ("set", "関西弁で話して")
    assert persona.parse("これからは兄弟みたいに話して") == ("set", "兄弟みたいに話して")
    assert persona.parse("話し方を元に戻して") == ("reset", "")
    assert persona.parse("今日の天気を教えて") is None
    assert persona.apply("関西弁で話す", ("add", "もっと短く答えて")) == "関西弁で話す。もっと短く答えて"
    config.PERSONA = "関西弁で話す"
    assert "関西弁" in llm.system_prompt()
    config.PERSONA = ""


def test_voice_danger_needs_confirm(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DESKTOP", str(tmp_path))
    (tmp_path / "memo.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(tools, "REQUIRE_CONFIRM", True)
    res = tools.run_tool("delete_item", {"name": "memo.txt"})
    body, confirm = llm.take_confirm(res)
    assert confirm["tool"] == "delete_item" and "はい" in body
    assert (tmp_path / "memo.txt").exists()  # 確認前なので消えていない
    assert tools.CONFIRM not in tools.run_tool("create_folder", {"name": "a"})  # 危なくない操作はそのまま
    monkeypatch.setattr(tools, "REQUIRE_CONFIRM", False)
    assert tools.CONFIRM not in tools.run_tool("shutdown_pc", {"cancel": True})


def test_open_url_rejects_bad(monkeypatch):
    import websearch
    monkeypatch.setattr(websearch, "host_is_safe", lambda h: h != "bad.example")
    opened = []
    monkeypatch.setattr(tools, "_browser_path", lambda: None)
    monkeypatch.setattr(tools.webbrowser, "open", lambda u: opened.append(u))
    assert "開きませんでした" in tools.run_tool("open_url", {"url": "https://bad.example/x"})
    assert "開きませんでした" in tools.run_tool("open_url", {"url": "http://1.2.3.4/"})
    tools.run_tool("open_url", {"url": "https://ok.example/"})
    assert opened == ["https://ok.example/"]


def test_reading_fix():
    import reading
    assert reading.fix("確認を行っています") == "確認をおこなっています"
    assert reading.fix("東京へ行っています") == "東京へ行っています"
    assert reading.fix("会議を行います") == "会議をおこないます"
    assert reading.fix("流行っている") == "流行っている"
