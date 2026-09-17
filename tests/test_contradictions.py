from ligaotai.contradictions import batches, group_text, scene_times


def test_场景的全局故事时间是线的offset加线内时间():
    threads = [
        {"id": "L-001", "offset": 0, "scenes": ["S-0001"], "times": {"S-0001": {"t": 3.0, "conf": "高"}}},
        {"id": "L-002", "offset": 10, "scenes": ["S-0100"], "times": {"S-0100": {"t": 2.0, "conf": "低"}}},
    ]
    t = scene_times(threads)
    assert t["S-0001"] == {"t": 3.0, "conf": "高", "thread": "L-001"}
    assert t["S-0100"] == {"t": 12.0, "conf": "低", "thread": "L-002"}


def test_没有时间估计的场景不报错():
    threads = [{"id": "L-001", "offset": 0, "scenes": ["S-0001"], "times": {}}]
    assert scene_times(threads)["S-0001"]["t"] is None


def test_渲染的组带引用编号和时间():
    cand = {"subject": "孙悟空", "attribute": "兵器", "values": [
        {"value": "金箍棒", "scenes": [{"id": "S-0014", "quote": "取出金箍棒"}]},
        {"value": "降妖宝杖", "scenes": [{"id": "S-0207", "quote": "使降妖宝杖"}]},
    ]}
    times = {"S-0014": {"t": 3.0, "conf": "高", "thread": "L-001"},
             "S-0207": {"t": 5.0, "conf": "低", "thread": "L-001"}}
    text = group_text("C-001", cand, times, unit="年")
    assert "C-001" in text and "孙悟空" in text and "兵器" in text
    assert "S-0014" in text and "取出金箍棒" in text
    assert "低" in text, "置信度低的要标出来给模型"
    assert "年" in text


def test_按token上限切批():
    cands = [{"subject": f"人{i}", "attribute": "兵器", "values": [
        {"value": "甲", "scenes": [{"id": "S-0001", "quote": "x" * 100}]},
        {"value": "乙", "scenes": [{"id": "S-0002", "quote": "y" * 100}]}]} for i in range(10)]
    got = batches(cands, {}, unit="年", budget=600)
    assert len(got) > 1
    assert sum(len(b) for b in got) == 10, "一个组都不能丢"


def test_单个组超预算也自成一批():
    cands = [{"subject": "甲", "attribute": "兵器", "values": [
        {"value": "v", "scenes": [{"id": "S-0001", "quote": "x" * 5000}]},
        {"value": "w", "scenes": [{"id": "S-0002", "quote": "y" * 5000}]}]}]
    got = batches(cands, {}, unit="年", budget=100)
    assert len(got) == 1 and len(got[0]) == 1


import pytest

from ligaotai.contradictions import check_output, clean_output


def _out(**kw):
    base = {"id": "C-001", "status": "真矛盾", "level": "严重",
            "category": "人物", "reason": "两处写的不是一件兵器 [S-0014][S-0207]"}
    base.update(kw)
    return {"groups": [base]}


def test_输出覆盖不全要报问题():
    assert check_output(_out(), {"C-001", "C-002"}) != []


def test_多出来的编号要报问题():
    assert check_output(_out(), set()) != []


def test_status不在三值里要报问题():
    assert check_output(_out(status="也许"), {"C-001"}) != []


def test_真矛盾没给严重度要报问题():
    assert check_output(_out(level=""), {"C-001"}) != []


def test_合理变化的严重度留空是对的():
    assert check_output(_out(status="合理变化", level=""), {"C-001"}) == []


def test_reason不带场景编号要报问题():
    assert check_output(_out(reason="就是不一样"), {"C-001"}) != []


def test_正常输出没问题():
    assert check_output(_out(), {"C-001"}) == []


def test_clean丢掉编造的编号并给漏掉的兜底():
    data = {"groups": [
        {"id": "C-001", "status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0014]"},
        {"id": "C-999", "status": "真矛盾", "level": "严重", "category": "人物", "reason": "y [S-0001]"},
    ]}
    got = clean_output(data, {"C-001", "C-002"})
    assert set(got) == {"C-001", "C-002"}
    assert got["C-002"]["status"] == "无法判断", "模型没答的按宁可多报兜底"
    assert got["C-002"]["reason"]


from ligaotai.contradictions import build_result


def _cand(subject, attribute, values):
    return {"subject": subject, "attribute": attribute, "merged": 0,
            "values": [{"value": v, "scenes": [{"id": s, "quote": "q"}]} for v, s in values]}


def test_编号取next_id只增不减():
    old = {"next_id": 5, "groups": []}
    res = build_result([_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
                       {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
                       {}, old, stats={})
    assert res["groups"][0]["id"] == "C-005"
    assert res["next_id"] == 6


def test_同一主语属性重跑沿用原编号():
    old = {"next_id": 9, "groups": [{"id": "C-003", "subject": "甲", "attribute": "兵器", "verdict": None}]}
    res = build_result([_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
                       {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
                       {}, old, stats={})
    assert res["groups"][0]["id"] == "C-003"
    assert res["next_id"] == 9, "沿用了就不该消耗新号"


def test_verdict按主语属性迁移():
    old = {"next_id": 9, "groups": [
        {"id": "C-003", "subject": "甲", "attribute": "兵器", "verdict": {"choice": "v"}},
        {"id": "C-004", "subject": "乙", "attribute": "外貌", "verdict": {"choice": "x"}},
    ]}
    res = build_result([_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
                       {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
                       {}, old, stats={})
    assert res["groups"][0]["verdict"] == {"choice": "v"}
    assert res["orphan_verdicts"] == [{"subject": "乙", "attribute": "外貌", "verdict": {"choice": "x"}}]


def test_场景里带上故事时间和所属线():
    times = {"S-0001": {"t": 3.0, "conf": "高", "thread": "L-001"}}
    res = build_result([_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
                       {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
                       times, {"next_id": 1, "groups": []}, stats={})
    s = res["groups"][0]["values"][0]["scenes"][0]
    assert s["t"] == 3.0 and s["conf"] == "高" and s["thread"] == "L-001"
