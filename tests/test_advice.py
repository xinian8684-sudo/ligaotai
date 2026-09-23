import json

from helpers import FakeBackend

from ligaotai.advice import advice_input, advice_status, check_advice, run_advice
from ligaotai.config import AppConfig
from ligaotai.fsutil import atomic_write_text, read_json
from ligaotai.llm import LLMClient
from ligaotai.threads_ops import load_threads

GOOD = {"advice": [
    {"thread": "L-001", "advice": "keep", "merge_into": None, "reason": "主线 [S-0001]"},
    {"thread": "L-002", "advice": "merge", "merge_into": "L-001", "reason": "篇幅短 [S-0004]"},
]}


def test_输入_有档案用档案摘要_没档案用about_列出场景编号(book_with_threads):
    b = book_with_threads
    atomic_write_text(b.thread_archive_dir / "L-001.md",
                      "# L-001 取经\n- 一句话：取经的主线 [S-0001]\n\n## 来龙去脉\n一路西行 [S-0002]\n\n## 主要人物\n- 略\n")
    values, tids, allowed = advice_input(b, load_threads(b))
    assert tids == ["L-001", "L-002"]
    assert allowed == {"S-0001", "S-0002", "S-0003", "S-0004", "S-0005"}
    assert "一路西行 [S-0002]" in values["threads"]
    assert "主要人物" not in values["threads"]          # 只取到「主要人物」之前
    assert "场景：S-0004、S-0005" in values["threads"]
    assert values["map"] == "（还没有全书地图）"


def test_输入_合法编号并上地图和档案里出现的场景_不限于线里的场景(book_with_threads):
    b = book_with_threads
    atomic_write_text(b.thread_archive_dir / "L-001.md",
                      "# L-001 取经\n- 一句话：取经的主线，参见设定笔记 [S-0006]\n\n## 主要人物\n- 略\n")
    values, tids, allowed = advice_input(b, load_threads(b))
    assert "S-0006" in allowed          # S-0006 是设定笔记，不属于任何一条线
    bad = {"advice": [{"thread": "L-001", "advice": "keep", "merge_into": None,
                       "reason": "沿用设定笔记 [S-0006]"},
                      {"thread": "L-002", "advice": "cut", "merge_into": None, "reason": "可删 [S-0004]"}]}
    assert check_advice(bad, tids, allowed) == []


def test_核对_漏线_重复_编号不在范围_合并目标不对(book_with_threads):
    tids, allowed = ["L-001", "L-002"], {"S-0001", "S-0004"}
    assert check_advice(GOOD, tids, allowed) == []
    bad = {"advice": [{"thread": "L-001", "advice": "merge", "merge_into": "L-001", "reason": "x [S-0009]"},
                      {"thread": "L-001", "advice": "drop", "reason": "没编号"}]}
    problems = "\n".join(check_advice(bad, tids, allowed))
    for word in ["L-002", "重复", "S-0009", "merge_into", "drop", "场景编号"]:
        assert word in problems


def test_跑一次_写进建议文件_再跑命中缓存不再调模型(book_with_threads):
    b = book_with_threads
    backend = FakeBackend(handler=lambda tier, messages: json.dumps(GOOD, ensure_ascii=False))
    client = LLMClient(AppConfig(), backend, log_dir=b.logs_dir)
    r = run_advice(b, client)
    assert r["ok"] is True and r["count"] == 2
    saved = read_json(b.advice_path)
    assert [i["advice"] for i in saved["items"]] == ["keep", "merge"]
    assert advice_status(b, load_threads(b))["stale"] is False
    run_advice(b, client)
    assert len(backend.calls) == 1


def test_模型一直不合规_不写文件_报失败(book_with_threads):
    b = book_with_threads
    backend = FakeBackend(handler=lambda tier, messages: json.dumps({"advice": []}))
    client = LLMClient(AppConfig(), backend, log_dir=b.logs_dir)
    r = run_advice(b, client)
    assert r["ok"] is False and r["failed"]
    assert not b.advice_path.exists()


def test_线变了_建议标过期(book_with_threads):
    b = book_with_threads
    backend = FakeBackend(handler=lambda tier, messages: json.dumps(GOOD, ensure_ascii=False))
    run_advice(b, LLMClient(AppConfig(), backend, log_dir=b.logs_dir))
    data = read_json(b.threads_path)
    data["threads"][1]["about"] = "改过的概述"
    from ligaotai.fsutil import write_json
    write_json(b.threads_path, data)
    assert advice_status(b, load_threads(b))["stale"] is True


def test_失败的结果不留缓存_重跑会再调模型(book_with_threads):
    b = book_with_threads
    backend = FakeBackend(handler=lambda tier, messages: json.dumps({"advice": []}))
    client = LLMClient(AppConfig(), backend, log_dir=b.logs_dir)
    run_advice(b, client)
    n = len(backend.calls)
    run_advice(b, client)
    assert len(backend.calls) == 2 * n
