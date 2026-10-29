import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import llm  # noqa: E402
import tools  # noqa: E402
from wakeword import strip_wake_word  # noqa: E402


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
