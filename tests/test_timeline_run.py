import json

import pytest

from helpers import FakeBackend
from ligaotai.config import AppConfig
from ligaotai.fsutil import read_json, write_json
from ligaotai.llm import LLMClient
from ligaotai.timeline_run import (
    VERDICT_KINDS,
    BrokenTimelineFile,
    _group_batches,
    _line_of,
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


def test_A模型输出畸形_检查和清理都不抛异常():
    ids = {"A-01", "A-02"}
    malformed = {"items": [{"id": "A-01", "status": ["在场"], "reason": 123}, "garbage", None, 42]}
    probs = check_death(malformed, ids)
    assert isinstance(probs, list) and probs
    cleaned = clean_death(malformed, ids)
    assert cleaned["A-01"]["status"] == "说不准"  # status 不是字符串、不在枚举里，退回默认
    assert cleaned["A-02"]["status"] == "说不准"  # 没答的


def test_C模型输出畸形_检查和清理都不抛异常():
    cands = {"C-01": ["S-0001"], "C-02": ["S-0002"]}
    malformed = {"items": [{"id": "C-01", "happens_in": ["S-0001"], "reason": 1}, "garbage", None, 42]}
    probs = check_refs(malformed, cands)
    assert isinstance(probs, list) and probs
    cleaned = clean_refs(malformed, cands)
    assert cleaned["C-01"]["happens_in"] is None
    assert cleaned["C-02"]["happens_in"] is None


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
    # 审 F1 第 8 条改完：dismissed 带上 status（现在有「提到」「记录不成立」两种都不报冲突），
    # 旧断言没有 status 字段（语义变化，见报告）。
    assert data["dismissed"] == [{"who": "甲", "scenes": ["S-0002", "S-0004"], "status": "提到"}]
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


# ---------- 审 F1 修复清单：必须修 1-4 ----------

def test_结果文件坏了重跑_先备份再当空(book):
    b = _book(book)
    b.timeline_path.write_text("{bad json", encoding="utf-8")
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    backups = list(b.root.glob("时间冲突.损坏备份-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{bad json"
    data = read_json(b.timeline_path)
    assert data["conflicts"][0]["id"] == "T-001"  # 当空处理，没有可沿用的旧编号


def test_场景文件缺失_不崩_退回卡片摘要_记进text_missing(book):
    b = _book(book)
    from ligaotai.scenes import scene_path
    scene_path(b, "S-0004").unlink()
    summary = run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    assert summary["ok"] is True
    data = read_json(b.timeline_path)
    assert [c["kind"] for c in data["conflicts"]] == ["A", "C"]  # A 类那条冲突照样报出来了
    assert data["stats"]["text_missing"] >= 1


def test_读结果_归线文件坏了_stale带原因(book):
    b = _book(book)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    b.threads_path.write_text("{bad", encoding="utf-8")
    d = load_timeline(b)
    assert d["stale"] is True
    assert "支线" in d["stale_reason"]


def test_读结果_场景文件坏了_stale带原因(book):
    b = _book(book)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    from ligaotai.scenes import scene_path
    scene_path(b, "S-0001").write_text("坏的场景文件", encoding="utf-8")
    d = load_timeline(b)
    assert d["stale"] is True
    assert "场景" in d["stale_reason"]


def test_读结果_实体文件坏了_stale带原因(book):
    b = _book(book)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    b.entities_path.write_text("{bad", encoding="utf-8")
    d = load_timeline(b)
    assert d["stale"] is True
    assert "实体" in d["stale_reason"]


def test_裁决_时间冲突json坏了报BrokenTimelineFile_不是ValueError(book):
    b = _book(book)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    b.timeline_path.write_text("{bad", encoding="utf-8")
    with pytest.raises(BrokenTimelineFile):
        set_timeline_verdict(b, "T-001", "ignore")


def test_裁决_时间冲突json不是字典报BrokenTimelineFile(book):
    b = _book(book)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    write_json(b.timeline_path, [1])
    with pytest.raises(BrokenTimelineFile):
        set_timeline_verdict(b, "T-001", "ignore")


def test_裁决_conflicts不是列表报BrokenTimelineFile(book):
    b = _book(book)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    write_json(b.timeline_path, {"conflicts": "坏了"})
    with pytest.raises(BrokenTimelineFile):
        set_timeline_verdict(b, "T-001", "ignore")


# ---------- 建议修 7/8/9/10/12/14b ----------

def test_分批不切开同一组_加一条新的只多一批不改老批次():
    who_a = [{"who": "甲", "n": i} for i in range(3)]
    who_b = [{"who": "乙", "n": i} for i in range(3)]
    batches1 = _group_batches(who_a, lambda x: x["who"], 3)
    assert batches1 == [who_a]
    batches2 = _group_batches(who_a + who_b, lambda x: x["who"], 3)
    assert batches2[0] == who_a  # 老批次原封不动，加的人只多出一批（who_a 正好凑满 size=3 才切）
    assert batches2[1] == who_b


def test_分批_单个组超过size也不切开():
    items = [{"who": "甲", "n": i} for i in range(7)]
    assert _group_batches(items, lambda x: x["who"], 5) == [items]


def test_跑成功没失败_清掉这次没用到的旧缓存(book):
    # 提前塞一条这次用不到的缓存条目（模拟上一轮留下的），这次全部真跑成功、没有失败，
    # prune_cache() 该把它清掉。
    b = _book(book)
    write_json(b.timeline_cache_path, {"垃圾键": {"data": {}, "problems": []}})
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    assert "垃圾键" not in read_json(b.timeline_cache_path)


def test_有失败批次不清缓存(book):
    # 这次有批次真的失败了（A 类那批），prune_cache() 不该调用，垃圾条目原样留着。
    from ligaotai.llm import LLMError
    b = _book(book)
    write_json(b.timeline_cache_path, {"垃圾键": {"data": {}, "problems": []}})

    def h(tier, messages):
        if "死了" in messages[0]["content"]:
            return LLMError("坏了")
        return _handler(tier, messages)

    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=h), log_dir=b.logs_dir))
    assert "垃圾键" in read_json(b.timeline_cache_path)


def test_A判成记录不成立_不报冲突_记进dismissed带status(book):
    b = _book(book)

    def h(tier, messages):
        if "死了" in messages[0]["content"]:
            return json.dumps({"items": [{"id": "A-01", "status": "记录不成立", "reason": "只是传闻[S-0002]"}]}, ensure_ascii=False)
        return json.dumps({"items": [{"id": "C-01", "happens_in": None, "reason": "都不是"}]}, ensure_ascii=False)

    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=h), log_dir=b.logs_dir))
    data = read_json(b.timeline_path)
    assert data["conflicts"] == []
    assert data["dismissed"] == [{"who": "甲", "scenes": ["S-0002", "S-0004"], "status": "记录不成立"}]


def test_同场景重复回指原话只生成一条冲突(book):
    b = _book(book)
    from ligaotai.cards import card_path
    rec = read_json(card_path(b, "S-0001"))
    rec["card"]["refs_elsewhere"] = ["那日比箭之事", "那日比箭之事"]  # 重复
    write_json(card_path(b, "S-0001"), rec)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    data = read_json(b.timeline_path)
    assert len([c for c in data["conflicts"] if c["kind"] == "C"]) == 1


def test_C批次失败_asked_refs带failed_没有C类冲突(book):
    from ligaotai.llm import LLMError
    b = _book(book)

    def h(tier, messages):
        if "回指" in messages[0]["content"]:
            return LLMError("坏了")
        return _handler(tier, messages)

    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=h), log_dir=b.logs_dir))
    data = read_json(b.timeline_path)
    assert [c["kind"] for c in data["conflicts"]] == ["A"]
    assert data["asked_refs"][0]["failed"] is True
    assert data["asked_refs"][0]["happens_in"] is None


def test_C批次成功_asked_refs的failed是False(book):
    b = _book(book)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    data = read_json(b.timeline_path)
    assert data["asked_refs"][0]["failed"] is False


def test_C类冲突的quotes是回指原话加发生场摘要(book):
    b = _book(book)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    data = read_json(b.timeline_path)
    c = next(c for c in data["conflicts"] if c["kind"] == "C")
    assert c["quotes"] == ["那日比箭之事", "S-0003 摘要"]


def test_候选摘要带上卡片的events(book):
    b = _book(book)
    from ligaotai.cards import card_path
    rec = read_json(card_path(b, "S-0003"))
    rec["card"]["events"] = ["乙丙约定明日再战"]
    write_json(card_path(b, "S-0003"), rec)
    captured = {}

    def h(tier, messages):
        if "回指" in messages[0]["content"]:
            captured["user"] = messages[1]["content"]
        return _handler(tier, messages)

    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=h), log_dir=b.logs_dir))
    assert "乙丙约定明日再战" in captured["user"]


def test_line_of经过version_map换成当前主版本编号(book):
    from helpers import seed_book
    seed_book(book, [{"id": "S-0001", "text": "a"}, {"id": "S-0002", "text": "b"}],
              groups=[("S-0002", ["S-0001", "S-0002"])])
    write_json(book.threads_path, {"threads": [{"id": "L-001", "offset": 0, "scenes": ["S-0001"],
        "times": {"S-0001": {"t": 0}}}], "worlds": [], "main_thread": "L-001", "global_order": [],
        "unassigned": [], "pending": [], "gaps": [], "intersections": []})
    # 线里存的是旧主版本 S-0001，line_of 的键要换成当前主版本 S-0002，不然跟 seq 里的编号对不上
    assert _line_of(book) == {"S-0002": "L-001"}


# ---------- 补测清单里跟 run 有关的几处 ----------

def test_C类模型答的候选在回指场之前_不报冲突(book):
    from helpers import seed_book
    seed_book(book, [
        {"id": "S-0000", "persons": ["乙", "丙"], "text": "乙丙很早以前的一场。"},
        {"id": "S-0001", "persons": ["乙", "丙"], "refs": ["某事"], "text": "乙想起某事。"},
        {"id": "S-0002", "persons": ["乙", "丙"], "text": "乙丙后来的一场。"},
    ])
    write_json(book.threads_path, {"threads": [{"id": "L-001", "offset": 0,
        "scenes": ["S-0000", "S-0001", "S-0002"],
        "times": {s: {"t": i} for i, s in enumerate(["S-0000", "S-0001", "S-0002"])}}],
        "worlds": [], "main_thread": "L-001", "global_order": [], "unassigned": [], "pending": [],
        "gaps": [], "intersections": []})

    def h(tier, messages):
        if "回指" in messages[0]["content"]:
            return json.dumps({"items": [{"id": "C-01", "happens_in": "S-0000", "reason": "选了前面那场[S-0000]"}]},
                              ensure_ascii=False)
        raise AssertionError(messages[0]["content"][:30])

    run_timeline(book, LLMClient(AppConfig(), FakeBackend(handler=h), log_dir=book.logs_dir))
    data = read_json(book.timeline_path)
    assert data["conflicts"] == []
    assert data["asked_refs"][0]["candidates"] == ["S-0000", "S-0002"]
    assert data["asked_refs"][0]["happens_in"] == "S-0000"


def test_A类摘录按别名也能在原文里找到(book):
    # 别名「劉公道」故意放在 40 字以外——不用别名查、退回「开头 40 字」兜底的话，
    # 巧合也会把它包进去，测不出真的在用别名；这里前面垫够长度，只有真的按别名在
    # 全文里找才能命中。
    from helpers import seed_book
    later_text = "話說" + "。".join(f"閒話{i}" for i in range(20)) + "。劉公道：我回來了。"
    assert len(later_text[:40]) < later_text.index("劉公道")  # 自检：确实排在 40 字之外
    seed_book(book, [
        {"id": "S-0002", "persons": ["劉芳"], "text": "劉芳已死了。"},
        {"id": "S-0004", "persons": ["劉公"], "text": later_text},
    ], entities=[("person", "劉芳", ["劉芳", "劉公"])])
    from ligaotai.cards import card_path
    rec = read_json(card_path(book, "S-0002"))
    rec["card"]["facts"] = [{"subject": "劉芳", "attribute": "生死", "value": "已死", "quote": "劉芳已死了"}]
    write_json(card_path(book, "S-0002"), rec)
    write_json(book.threads_path, {"threads": [{"id": "L-001", "offset": 0,
        "scenes": ["S-0002", "S-0004"], "times": {"S-0002": {"t": 0}, "S-0004": {"t": 1}}}],
        "worlds": [], "main_thread": "L-001", "global_order": [], "unassigned": [], "pending": [],
        "gaps": [], "intersections": []})

    def h(tier, messages):
        if "死了" in messages[0]["content"]:
            return json.dumps({"items": [{"id": "A-01", "status": "在场", "reason": "在说话[S-0004]"}]}, ensure_ascii=False)
        return json.dumps({"items": []}, ensure_ascii=False)

    run_timeline(book, LLMClient(AppConfig(), FakeBackend(handler=h), log_dir=book.logs_dir))
    data = read_json(book.timeline_path)
    assert "劉公道" in data["conflicts"][0]["quotes"][1]


def test_stats的七个字段不是写死的0(book):
    b = _book(book)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    stats = read_json(b.timeline_path)["stats"]
    assert stats["placed"] == 4
    assert stats["unplaced"] == 0
    assert stats["untracked"] == 0
    assert stats["a_suspects"] == 1
    assert stats["a_capped"] == 0
    assert stats["refs_asked"] == 1
    assert stats["refs_no_candidate"] == 0
    assert stats["refs_all_before"] == 0
    assert stats["text_missing"] == 0


def test_stats的unplaced_untracked_a_capped_refs字段真的有非零值(book):
    # 上一条测试的书里这几个字段天然都是 0，硬编码成 0 也照样通过；这里专门造一本
    # unplaced/untracked/a_capped/refs_no_candidate/refs_all_before 都不为 0 的书。
    from helpers import seed_book
    scenes = [{"id": "S-0001", "persons": ["甲"], "text": "甲已死了。"}]
    scenes += [{"id": f"S-{i:04d}", "persons": ["甲"], "text": "甲道：我回来了。"} for i in range(2, 9)]  # 7 次，超 MAX_LATER=5
    scenes += [{"id": "S-0009", "persons": ["乙", "丙"], "text": "乙丙的一场。"}]
    scenes += [{"id": "S-0010", "persons": ["乙", "丙"], "refs": ["某段往事"], "text": "乙丙想起某段往事。"}]  # 候选只有 S-0009，在它之前
    scenes += [{"id": "S-0011", "persons": ["丁"], "refs": ["没人知道的事"], "text": "丁想起没人知道的事。"}]  # 没有共同人物候选
    scenes += [{"id": "S-0012", "persons": [], "text": "没有时间的一场。"}]  # 待会不给它时间 → unplaced
    scenes += [{"id": "S-0013", "persons": [], "text": "压根没被任何线提到的一场。"}]  # → untracked
    seed_book(book, scenes)
    from ligaotai.cards import card_path
    rec = read_json(card_path(book, "S-0001"))
    rec["card"]["facts"] = [{"subject": "甲", "attribute": "生死", "value": "已死", "quote": "甲已死了"}]
    write_json(card_path(book, "S-0001"), rec)
    in_thread = [s["id"] for s in scenes if s["id"] != "S-0013"]
    times = {sid: {"t": i} for i, sid in enumerate(in_thread) if sid != "S-0012"}
    write_json(book.threads_path, {"threads": [{"id": "L-001", "offset": 0, "scenes": in_thread, "times": times}],
        "worlds": [], "main_thread": "L-001", "global_order": [], "unassigned": [], "pending": [],
        "gaps": [], "intersections": []})

    def h(tier, messages):
        if "死了" in messages[0]["content"]:
            items = [{"id": f"A-{i:02d}", "status": "在场", "reason": f"在场[S-{i + 1:04d}]"} for i in range(1, 6)]
            return json.dumps({"items": items}, ensure_ascii=False)
        return json.dumps({"items": []}, ensure_ascii=False)  # 这本书的回指都问不到候选，不会真的调到这支

    run_timeline(book, LLMClient(AppConfig(), FakeBackend(handler=h), log_dir=book.logs_dir))
    stats = read_json(book.timeline_path)["stats"]
    assert stats["placed"] == 11        # S-0001..S-0011，S-0012 unplaced、S-0013 untracked 都不算
    assert stats["unplaced"] == 1
    assert stats["untracked"] == 1
    assert stats["a_suspects"] == 5     # MAX_LATER=5，7 次后来出现只留最近 5 个
    assert stats["a_capped"] == 2       # 超掉的 2 个记在这
    assert stats["refs_asked"] == 0     # 两条回指一条没候选、一条候选全在前面，都没问到模型
    assert stats["refs_no_candidate"] == 1
    assert stats["refs_all_before"] == 1
    assert stats["text_missing"] == 0
