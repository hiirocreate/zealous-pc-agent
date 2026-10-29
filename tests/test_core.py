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
    assert tools.run_tool("nope", {}).startswith("エラー")
    monkeypatch.setattr(config, "DRY_RUN", True)
    assert tools.run_tool("lock_screen", {}).startswith("[DRY]")


def test_ask_with_mock(monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", True)
    monkeypatch.setattr(llm, "_chat", lambda m, use_tools=True: {
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
    assert "エラー" in tools.run_tool("rename_item", {"name": os.path.expanduser("~"), "new_name": "x"})
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
    cat.write_text(json.dumps([{"id": 3, "speaker": "ずんだもん", "style": "ノーマル", "vvm": "0.vvm", "mb": 56},
                               {"id": 8, "speaker": "春日部つむぎ", "style": "ノーマル", "vvm": "0.vvm", "mb": 56},
                               {"id": 13, "speaker": "青山龍星", "style": "ノーマル", "vvm": "15.vvm", "mb": 63}]),
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
    monkeypatch.setattr(websearch, "search", lambda q: [{"title": "A", "url": "https://a", "snippet": "a"},
                                                        {"title": "B", "url": "https://b", "snippet": "b"}])
    monkeypatch.setattr(websearch, "read_pages", lambda r: ["本文A", "本文B"])
    monkeypatch.setattr(websearch, "images", lambda q, limit=30: [{"thumb": "t"}])
    monkeypatch.setattr(llm, "_chat", lambda m, use_tools=True: {"content": "要約です"})
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
    monkeypatch.setattr(llm, "_chat", lambda m, use_tools=True: (seen.append(m), {"content": "はい"})[1])
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
