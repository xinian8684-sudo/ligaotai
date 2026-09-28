import json

import pytest

from helpers import FakeBackend
from ligaotai.config import AppConfig
from ligaotai.fsutil import read_json, write_json
from ligaotai.llm import LLMClient
from ligaotai.timeline_run import (
    VERDICT_KINDS,
    check_death,
    check_refs,
    clean_death,
    clean_refs,
    load_timeline,
    run_timeline,
    set_timeline_verdict,
)


def test_A输出检查():
    ids = {"A-01", "A-02"}
    ok = {"items": [{"id": "A-01", "status": "在场", "reason": "x[S-0001]"},
                    {"id": "A-02", "status": "提到", "reason": "y[S-0002]"}]}
    assert check_death(ok, ids) == []
    bad = {"items": [{"id": "A-01", "status": "活着", "reason": "x"}, {"id": "A-09", "status": "在场", "reason": "[S-0001]"}]}
    probs = check_death(bad, ids)
    assert any("A-02" in p for p in probs)          # 漏答
    assert any("A-09" in p for p in probs)          # 编造编号
    assert any("status" in p for p in probs)
    assert any("场景编号" in p for p in probs)
    assert check_death([], ids)                      # 形状不对


def test_A清理_没答的按说不准保留():
    got = clean_death({"items": [{"id": "A-01", "status": "提到", "reason": "r"}]}, {"A-01", "A-02"})
    assert got["A-01"]["status"] == "提到"
    assert got["A-02"]["status"] == "说不准"


def test_C输出检查_happens_in只能是这条自己的候选或null():
    cands = {"C-01": ["S-0001", "S-0002"], "C-02": ["S-0003"]}
    ok = {"items": [{"id": "C-01", "happens_in": "S-0002", "reason": "[S-0002]"},
                    {"id": "C-02", "happens_in": None, "reason": "都不是"}]}
    assert check_refs(ok, cands) == []
    bad = {"items": [{"id": "C-01", "happens_in": "S-0003", "reason": "[S-0003]"}]}
    probs = check_refs(bad, cands)
    assert any("C-01" in p and "候选" in p for p in probs)
    assert any("C-02" in p for p in probs)


def test_C清理_不合法的当null():
    got = clean_refs({"items": [{"id": "C-01", "happens_in": "S-0009", "reason": "r"}]}, {"C-01": ["S-0001"], "C-02": ["S-0002"]})
    assert got == {"C-01": {"happens_in": None, "reason": "r"}, "C-02": {"happens_in": None, "reason": ""}}


def _book(book):
    """甲在 S-0002 死了，S-0004 又出现；S-0001 回指「比箭」，比箭在 S-0003（排在后面）。"""
    from helpers import seed_book
    from ligaotai.cards import card_path
    seed_book(book, [
        {"id": "S-0001", "persons": ["乙", "丙"], "refs": ["那日比箭之事"], "text": "乙想起那日比箭之事。"},
        {"id": "S-0002", "persons": ["甲"], "text": "甲已死了。"},
        {"id": "S-0003", "persons": ["乙", "丙"], "text": "乙丙比箭。"},
        {"id": "S-0004", "persons": ["甲"], "text": "甲道：我回來了。"},
    ])
    rec = read_json(card_path(book, "S-0002"))
    rec["card"]["facts"] = [{"subject": "甲", "attribute": "生死", "value": "已死", "quote": "甲已死了"}]
    write_json(card_path(book, "S-0002"), rec)
    write_json(book.threads_path, {"threads": [{"id": "L-001", "offset": 0,
        "scenes": ["S-0001", "S-0002", "S-0003", "S-0004"],
        "times": {s: {"t": i} for i, s in enumerate(["S-0001", "S-0002", "S-0003", "S-0004"])}}],
        "worlds": [], "main_thread": "L-001", "global_order": [], "unassigned": [], "pending": [],
        "gaps": [], "intersections": []})
    return book


def _handler(tier, messages):
    system, user = messages[0]["content"], messages[1]["content"]
    if "死了" in system:
        return json.dumps({"items": [{"id": "A-01", "status": "在场", "reason": "甲在说话[S-0004]"}]}, ensure_ascii=False)
    if "回指" in system:
        return json.dumps({"items": [{"id": "C-01", "happens_in": "S-0003", "reason": "比箭在这[S-0003]"}]}, ensure_ascii=False)
    raise AssertionError(system[:30])


def test_跑一遍_报出A和C_落盘带指纹和统计(book):
    b = _book(book)
    client = LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir)
    summary = run_timeline(b, client)
    data = read_json(b.timeline_path)
    got = [(c["id"], c["kind"], c["scenes"], c.get("who"), c.get("ref")) for c in data["conflicts"]]
    assert got == [("T-001", "A", ["S-0002", "S-0004"], "甲", None),
                   ("T-002", "C", ["S-0001", "S-0003"], None, "那日比箭之事")]
    assert data["conflicts"][0]["pos"] == [1, 3]
    assert data["fingerprint"] and data["stats"]["placed"] == 4
    assert summary == {"ok": True, "conflicts": 2, "failed": 0}


def test_A判成提到的不报_记进dismissed(book):
    b = _book(book)

    def h(tier, messages):
        if "死了" in messages[0]["content"]:
            return json.dumps({"items": [{"id": "A-01", "status": "提到", "reason": "只是回忆[S-0004]"}]}, ensure_ascii=False)
        return json.dumps({"items": [{"id": "C-01", "happens_in": None, "reason": "都不是"}]}, ensure_ascii=False)

    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=h), log_dir=b.logs_dir))
    data = read_json(b.timeline_path)
    assert data["conflicts"] == []
    assert data["dismissed"] == [{"who": "甲", "scenes": ["S-0002", "S-0004"]}]
    assert data["asked_refs"][0]["happens_in"] is None


def test_重跑沿用编号和裁决(book):
    b = _book(book)
    client = LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir)
    run_timeline(b, client)
    data = read_json(b.timeline_path)
    data["conflicts"][1]["verdict"] = {"kind": "order_error", "at": "x"}
    write_json(b.timeline_path, data)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    again = read_json(b.timeline_path)
    assert [(c["id"], c["verdict"]) for c in again["conflicts"]] == [
        ("T-001", None), ("T-002", {"kind": "order_error", "at": "x"})]


def test_一批调用失败_记进failed_不崩(book):
    from ligaotai.llm import LLMError
    b = _book(book)

    def h(tier, messages):
        if "死了" in messages[0]["content"]:
            return LLMError("坏了")
        return _handler(tier, messages)

    s = run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=h), log_dir=b.logs_dir))
    data = read_json(b.timeline_path)
    assert s["failed"] == 1 and len(data["failed"]) == 1
    # 失败批次里的 A 嫌疑按「说不准」报出来（宁可多报），不静默丢
    assert [c["kind"] for c in data["conflicts"]] == ["A", "C"]
    assert data["conflicts"][0]["status"] == "说不准"


def test_读结果_没跑过返回空_跑过带stale(book):
    b = _book(book)
    assert load_timeline(b) == {"conflicts": [], "never_run": True, "stale": False}
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    d = load_timeline(b)
    assert d["stale"] is False and d["never_run"] is False
    # 故事顺序按时间值排，只改 scenes 的排列不会让顺序变；改一张卡的回指，指纹一定变
    from ligaotai.cards import card_path
    rec = read_json(card_path(b, "S-0001"))
    rec["card"]["refs_elsewhere"] = ["另一件事"]
    write_json(card_path(b, "S-0001"), rec)
    assert load_timeline(b)["stale"] is True


def test_裁决_设置_改_撤销_没有这条报KeyError_类型不对报ValueError(book):
    b = _book(book)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    c = set_timeline_verdict(b, "T-001", "author_error")
    assert c["verdict"]["kind"] == "author_error"
    assert set_timeline_verdict(b, "T-001", "ignore")["verdict"]["kind"] == "ignore"
    assert set_timeline_verdict(b, "T-001", None)["verdict"] is None
    assert read_json(b.timeline_path)["conflicts"][0]["verdict"] is None
    with pytest.raises(KeyError):
        set_timeline_verdict(b, "T-099", "ignore")
    with pytest.raises(ValueError):
        set_timeline_verdict(b, "T-001", "随便")
    assert VERDICT_KINDS == ("author_error", "order_error", "ignore")
