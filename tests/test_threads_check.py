import asyncio
import json

from helpers import FakeBackend

from ligaotai.config import AppConfig
from ligaotai.llm import LLMClient
from ligaotai.threads_check import check_worlds, clean_worlds, coverage_problems, score_worlds


def fullwidth(s):
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in s)


def test_coverage_problems():
    assert coverage_problems(["S-0001", "S-0002"], {"S-0001", "S-0002"}) == []
    p = coverage_problems(["S-0001", "S-0001", "S-0009"], {"S-0001", "S-0002"})
    assert len(p) == 3
    assert "S-0009" in p[0] and "S-0001" in p[1] and "S-0002" in p[2]


def test_coverage_lists_at_most_20():
    p = coverage_problems([], {f"S-{i:04d}" for i in range(1, 31)})
    assert p[0].count("S-") == 20
    assert "共 30 个" in p[0]


def test_check_worlds():
    ok = {"time_unit": "年", "worlds": [{"name": "人间", "reason": "r", "scenes": ["S-0001"]}, {"id": "W-01", "scenes": ["S-0002"]}]}
    assert check_worlds(ok, {"S-0001", "S-0002"}, {"W-01"}, need_unit=True) == []
    assert check_worlds({"worlds": ok["worlds"]}, {"S-0001", "S-0002"}, {"W-01"}, need_unit=True) != []
    assert check_worlds({"worlds": ok["worlds"]}, {"S-0001", "S-0002"}, {"W-01"}, need_unit=False) == []
    assert check_worlds({"worlds": [{"id": "W-09", "scenes": ["S-0001"]}]}, {"S-0001"}, set(), False) != []
    assert check_worlds({"worlds": [{"scenes": ["S-0001"]}]}, {"S-0001"}, set(), False) != []
    assert check_worlds({"worlds": "乱写"}, {"S-0001"}, set(), False) == ["缺少 worlds 列表"]
    assert check_worlds({"worlds": [1, None]}, set(), set(), False) != []


def test_clean_worlds():
    data = {"time_unit": " 年 ", "worlds": [
        {"name": "人间", "reason": "r", "scenes": ["S-0001", "S-0009", "S-0001"]},
        {"id": "W-01", "scenes": ["S-0002"]},
        {"id": "W-01", "scenes": ["S-0003", "S-0001"]},
        {"scenes": ["S-0004"]},
        {"name": "空的", "scenes": ["S-0009"]},
        "乱写",
    ]}
    worlds, missing, unit = clean_worlds(data, {"S-0001", "S-0002", "S-0003", "S-0004", "S-0005"}, {"W-01"})
    assert unit == "年"
    assert worlds == [
        {"key": None, "name": "人间", "reason": "r", "scenes": ["S-0001"]},
        {"key": "W-01", "name": "", "reason": "", "scenes": ["S-0002", "S-0003"]},
        {"key": None, "name": "未命名世界", "reason": "", "scenes": ["S-0004"]},
    ]
    assert missing == ["S-0005"]


def test_worlds_weird_shapes_never_raise():
    exp = {"S-0001"}
    cases = [
        {"worlds": 5}, {"worlds": True}, {"worlds": None}, {"time_unit": ["年"], "worlds": 5},
        {"worlds": [{"id": ["W-01"], "scenes": ["S-0001"]}]},
        {"worlds": [{"id": {"a": 1}, "scenes": ["S-0001"]}]},
        {"worlds": [{"id": 3, "scenes": "S-0001"}]},
        {"worlds": [{"name": ["人间"], "scenes": [["S-0001"], {"a": 1}, None]}]},
        [], 5,
    ]
    for data in cases:
        assert check_worlds(data, exp, {"W-01"}, True) != []
        assert score_worlds(data, exp, {"W-01"}, True) > 0
        worlds, missing, unit = clean_worlds(data, exp, {"W-01"})
        assert sorted([s for w in worlds for s in w["scenes"]] + missing) == ["S-0001"] and isinstance(unit, str)
    p = check_worlds({"worlds": [{"id": ["W-01"], "scenes": ["S-0001"]}]}, exp, {"W-01"}, False)
    assert len(p) == 1 and "字符串" in p[0]


def test_check_worlds_same_scene_in_two_worlds():
    data = {"worlds": [{"name": "人间", "scenes": ["S-0001", "S-0002"]}, {"id": "W-01", "scenes": ["S-0002"]}]}
    p = check_worlds(data, {"S-0001", "S-0002"}, {"W-01"}, False)
    assert len(p) == 1 and "不止一次" in p[0] and "S-0002" in p[0]
    worlds, missing, _ = clean_worlds(data, {"S-0001", "S-0002"}, {"W-01"})
    assert [(w["key"], w["scenes"]) for w in worlds] == [(None, ["S-0001", "S-0002"]), ("W-01", [])]
    assert missing == []


def test_known_world_id_variants_map_to_the_real_id():
    exp = {"S-0001", "S-0002", "S-0003", "S-0004", "S-0005"}
    data = {"worlds": [
        {"id": "w-01", "scenes": ["S-0001"]},
        {"id": "W-1", "scenes": ["S-0002"]},
        {"id": " W-01 ", "scenes": ["s-0003"]},
        {"id": fullwidth("W-01"), "scenes": ["S-4"]},
        {"id": "W01", "scenes": [" S-0005 "]},
    ]}
    assert check_worlds(data, exp, {"W-01"}, False) == []
    worlds, missing, _ = clean_worlds(data, exp, {"W-01"})
    assert worlds == [{"key": "W-01", "name": "", "reason": "", "scenes": ["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"]}]
    assert missing == []


def test_id_key_accepts_variants_but_never_glues_two_numbers():
    """rereview_batch1 M-1：数字去前导 0 可以；数字跟数字之间的分隔符不能去，否则两段数字粘成一个编号，
    对上另一个真编号，检查就不报了。"""
    from ligaotai.threads_check import _Ids

    ids = _Ids([f"S-{i:04d}" for i in range(1, 30)], ["W-01", "W-01#1", "W-01#10", "L-002"])
    ok = {
        "W-1": "W-01", "w-01": "W-01", "W01": "W-01", fullwidth("W-01"): "W-01", "S-4": "S-0004", "l-2": "L-002",
        "W-01#01": "W-01#1", "S-00019": "S-0019", " s_0013 ": "S-0013", "S 13": "S-0013", "W-01# 1": "W-01#1",
    }
    for raw, real in ok.items():
        assert ids.one(raw) == real, raw
    for raw in ("S-0001-3", "S-0001 3", "S-1-3", "S-00-13", "W-01#1-0", "W-01#1 0"):
        assert ids.one(raw) == raw, raw  # 对不上任何真编号，原样留着
    exp = {"S-0001", "S-0013", "S-0019"}
    p = check_worlds({"worlds": [{"name": "A", "scenes": ["S-0001", "S-0001-3", "S-00019"]}]}, exp, set(), False)
    assert len(p) == 2 and "S-0001-3" in p[0] and "编造" in p[0] and "S-0013" in p[1] and "漏掉" in p[1]


def test_worlds_with_the_same_name():
    exp = {"S-0001", "S-0002", "S-0003"}
    names = {"W-01": "天界"}
    data = {"worlds": [{"name": "人间", "scenes": ["S-0001"]}, {"name": "人间 ", "scenes": ["S-0002"]}, {"name": "天界", "scenes": ["S-0003"]}]}
    p = check_worlds(data, exp, {"W-01"}, False, names=names)
    assert len(p) == 2 and "第 1 个世界同名" in p[0] and "W-01" in p[1]
    worlds, missing, _ = clean_worlds(data, exp, {"W-01"}, names=names)
    assert [(w["key"], w["name"], w["scenes"]) for w in worlds] == [(None, "人间", ["S-0001", "S-0002"]), ("W-01", "", ["S-0003"])]
    assert missing == []


def test_worlds_score_counts_broken_blocks_not_problem_lines():
    """几乎全对（1 重复 + 1 编造，2 条问题）要比「只补交差额」「空列表」（1 条问题）分数低。"""
    exp = {f"S-{i:04d}" for i in range(1, 101)}
    near = {"worlds": [{"name": "人间", "scenes": sorted(exp) + ["S-0001", "S-0999"]}]}
    lazy = {"worlds": [{"name": "人间", "scenes": ["S-0001"]}]}
    empty = {"worlds": []}
    assert len(check_worlds(near, exp, set(), False)) > len(check_worlds(empty, exp, set(), False))
    assert score_worlds(near, exp, set(), False) < score_worlds(lazy, exp, set(), False)
    assert score_worlds(lazy, exp, set(), False) < score_worlds(empty, exp, set(), False)
    assert score_worlds(empty, exp, set(), False) < score_worlds({"worlds": 5}, exp, set(), False)


from ligaotai.threads_check import check_lines, clean_lines

ORD = {"S-0001", "S-0002", "S-0003"}
OUT = {"S-0009"}


def line_reply(*threads, world_outlines=()):
    return {"threads": list(threads), "world_outlines": list(world_outlines)}


def test_check_lines_ok():
    data = line_reply(
        {"name": "甲", "about": "a", "main": True, "scenes": ["S-0001", "S-0002"], "outlines": ["S-0009"]},
        {"id": "L-003", "scenes": ["S-0003"]},
    )
    assert check_lines(data, ORD, OUT, {"L-003"}) == []


def test_check_lines_problems():
    base = {"name": "甲", "main": True, "scenes": ["S-0001", "S-0002", "S-0003"], "outlines": []}
    p = check_lines(line_reply(base), ORD, OUT, set())  # 提纲漏了
    assert len(p) == 1 and "提纲块漏掉" in p[0] and "S-0009" in p[0]
    assert check_lines(line_reply(base, world_outlines=["S-0009"]), ORD, OUT, set()) == []
    no_main = {**base, "main": False}
    p = check_lines(line_reply(no_main, world_outlines=["S-0009"]), ORD, OUT, set())
    assert len(p) == 1 and "main" in p[0] and "0 条" in p[0]
    two_main = [{**base, "scenes": ["S-0001", "S-0002"]}, {"name": "乙", "main": True, "scenes": ["S-0003"]}]
    p = check_lines(line_reply(*two_main, world_outlines=["S-0009"]), ORD, OUT, set())
    assert len(p) == 1 and "main" in p[0] and "2 条" in p[0]
    bad_id = {**base, "id": "L-099"}
    p = check_lines(line_reply(bad_id, world_outlines=["S-0009"]), ORD, OUT, set())
    assert len(p) == 1 and "L-099" in p[0] and "不是已有的线" in p[0]
    assert check_lines({"threads": None}, ORD, OUT, set()) == ["缺少 threads 列表"]
    p = check_lines(line_reply(), set(), OUT, set())  # 只有提纲、没线：提纲要放 world_outlines
    assert len(p) == 1 and "S-0009" in p[0]
    assert check_lines(line_reply(world_outlines=["S-0009"]), set(), OUT, set()) == []


def test_clean_lines():
    data = line_reply(
        {"name": "甲", "about": "a", "main": False, "scenes": ["S-0001", "S-0001", "S-0077"], "outlines": []},
        {"id": "L-003", "scenes": ["S-0002"]},
        {"id": "L-003", "scenes": ["S-0003"], "outlines": ["S-0009"]},
        {"name": "", "main": True, "scenes": [], "outlines": []},
    )
    got = clean_lines(data, ORD | {"S-0004"}, OUT | {"S-0008"}, {"L-003"})
    assert got["threads"] == [
        {"key": None, "name": "甲", "about": "a", "main": False, "scenes": ["S-0001"], "outlines": []},
        {"key": "L-003", "name": "", "about": "", "main": True, "scenes": ["S-0002", "S-0003"], "outlines": ["S-0009"]},
    ]
    assert got["world_outlines"] == ["S-0008"]
    assert got["missing"] == ["S-0004"]


def test_clean_lines_keeps_first_main_and_moves_orphan_outlines():
    data = line_reply(
        {"name": "甲", "main": True, "scenes": ["S-0001"]},
        {"name": "乙", "main": True, "scenes": ["S-0002", "S-0003"]},
        {"name": "丙", "scenes": [], "outlines": ["S-0009"]},
    )
    got = clean_lines(data, ORD, OUT, set())
    assert [t["main"] for t in got["threads"]] == [True, False]
    assert got["threads"][1]["name"] == "乙"
    assert got["world_outlines"] == ["S-0009"]


def test_check_lines_temp_keys():
    known = {"W-01#1"}
    ok = line_reply({"id": "W-01#1", "main": True, "scenes": sorted(ORD)}, world_outlines=["S-0009"])
    assert check_lines(ok, ORD, OUT, known) == []
    for bad in ("W-01#2", "W-02#1", "L-001"):  # 不存在的临时键、别的世界的临时键、不在 known 里的正式编号
        data = line_reply({"id": bad, "main": True, "scenes": sorted(ORD)}, world_outlines=["S-0009"])
        p = check_lines(data, ORD, OUT, known)
        assert len(p) == 1 and bad in p[0] and "不是已有的线" in p[0]
    got = clean_lines(line_reply({"id": "W-01#2", "main": True, "scenes": sorted(ORD)}), ORD, OUT, known)
    assert got["threads"][0]["key"] is None and got["threads"][0]["name"] == "未命名支线"
    got = clean_lines(ok, ORD, OUT, known)
    assert got["threads"][0]["key"] == "W-01#1"


def test_check_lines_id_that_is_not_a_string():
    for bad in (["L-003"], {"k": 1}, True):
        data = line_reply({"id": bad, "main": True, "scenes": sorted(ORD)}, world_outlines=["S-0009"])
        p = check_lines(data, ORD, OUT, {"L-003"})
        assert len(p) == 1 and "字符串" in p[0]
        got = clean_lines(data, ORD, OUT, {"L-003"})
        assert got["threads"][0]["key"] is None and got["threads"][0]["scenes"] == sorted(ORD)
    assert check_lines({"threads": [{"id": "L-003", "scenes": 5, "outlines": True}]}, ORD, OUT, {"L-003"}) != []


def test_check_lines_new_thread_named_like_an_existing_one():
    names = {"L-003": "旧线"}
    data = line_reply({"name": "旧线", "main": True, "scenes": sorted(ORD)}, world_outlines=["S-0009"])
    p = check_lines(data, ORD, OUT, {"L-003"}, names)
    assert len(p) == 1 and "旧线" in p[0] and "L-003" in p[0]
    got = clean_lines(data, ORD, OUT, {"L-003"}, names)
    assert [(t["key"], t["scenes"]) for t in got["threads"]] == [("L-003", sorted(ORD))]
    same = line_reply(
        {"name": "甲", "main": True, "scenes": ["S-0001"]}, {"name": "甲", "scenes": ["S-0002", "S-0003"]},
        world_outlines=["S-0009"],
    )
    p = check_lines(same, ORD, OUT, set())
    assert len(p) == 1 and "第 1 条线同名" in p[0]
    got = clean_lines(same, ORD, OUT, set())
    assert [(t["name"], t["scenes"], t["main"]) for t in got["threads"]] == [("甲", ["S-0001", "S-0002", "S-0003"], True)]


def test_check_lines_new_thread_without_ordered_blocks():
    data = line_reply({"name": "甲", "main": True, "scenes": sorted(ORD)}, {"name": "乙", "about": "b", "scenes": [], "outlines": ["S-0009"]})
    p = check_lines(data, ORD, OUT, set())
    assert len(p) == 1 and "第 2 条线是新线" in p[0]
    data = line_reply({"name": "甲", "scenes": sorted(ORD)}, {"name": "乙", "main": True, "scenes": []}, world_outlines=["S-0009"])
    p = check_lines(data, ORD, OUT, set())
    assert len(p) == 1 and "第 2 条线是新线" in p[0] and "main" in p[0]


def test_check_lines_block_in_the_wrong_field():
    data = line_reply({"name": "甲", "main": True, "scenes": ["S-0001", "S-0002", "S-0009"], "outlines": ["S-0003"]})
    p = check_lines(data, ORD, OUT, set())
    assert len(p) == 2 and "是正文/碎片" in p[0] and "S-0003" in p[0] and "是提纲" in p[1] and "S-0009" in p[1]
    assert all("编造" not in x and "漏掉" not in x for x in p)
    got = clean_lines(data, ORD, OUT, set())
    assert got["threads"][0]["scenes"] == ["S-0001", "S-0002", "S-0003"] and got["threads"][0]["outlines"] == ["S-0009"]
    assert got["missing"] == [] and got["world_outlines"] == []
    data = line_reply({"name": "甲", "main": True, "scenes": ["S-0001", "S-0002"], "outlines": ["S-0009"]}, world_outlines=["S-0003"])
    p = check_lines(data, ORD, OUT, set())
    assert len(p) == 1 and "world_outlines" in p[0] and "S-0003" in p[0]
    assert clean_lines(data, ORD, OUT, set())["missing"] == ["S-0003"]


def test_check_lines_block_of_an_existing_thread_written_back():
    data = line_reply({"name": "甲", "main": True, "scenes": sorted(ORD) + ["S-0404"]}, world_outlines=["S-0009"])
    p = check_lines(data, ORD, OUT, {"L-003"}, held={"S-0404": "L-003"})
    assert len(p) == 1 and "S-0404（L-003）" in p[0] and "编造" not in p[0]
    got = clean_lines(data, ORD, OUT, {"L-003"})
    assert got["threads"][0]["scenes"] == sorted(ORD)
    p = check_lines(data, ORD, OUT, {"L-003"})  # 不传 held：按编造报
    assert len(p) == 1 and "编造" in p[0]


def test_check_lines_require_main():
    """require_main=False（这个世界的主线已经定了）：标几条 main 都不查（清理只留一条，重试只花钱）；
    main 标在空的新线上照样报（报的是新线没有正文/碎片块）。"""
    from ligaotai.threads_check import score_lines

    none = line_reply({"name": "甲", "scenes": sorted(ORD)}, world_outlines=["S-0009"])
    p = check_lines(none, ORD, OUT, set())
    assert len(p) == 1 and "0 条" in p[0]
    assert check_lines(none, ORD, OUT, set(), require_main=False) == []
    assert score_lines(none, ORD, OUT, set(), require_main=False) == 0
    one = line_reply({"name": "甲", "main": True, "scenes": sorted(ORD)}, world_outlines=["S-0009"])
    assert check_lines(one, ORD, OUT, set(), require_main=False) == []
    two = line_reply(
        {"name": "甲", "main": True, "scenes": ["S-0001"]}, {"name": "乙", "main": True, "scenes": ["S-0002", "S-0003"]},
        world_outlines=["S-0009"],
    )
    p = check_lines(two, ORD, OUT, set(), require_main=True)
    assert len(p) == 1 and "main" in p[0] and "2 条" in p[0]
    assert score_lines(two, ORD, OUT, set(), require_main=True) > 0
    assert check_lines(two, ORD, OUT, set(), require_main=False) == []
    assert score_lines(two, ORD, OUT, set(), require_main=False) == 0
    assert [t["main"] for t in clean_lines(two, ORD, OUT, set())["threads"]] == [True, False]
    empty_main = line_reply(
        {"name": "甲", "scenes": sorted(ORD)}, {"name": "乙", "main": True, "scenes": []}, world_outlines=["S-0009"]
    )
    p = check_lines(empty_main, ORD, OUT, set(), require_main=False)
    assert len(p) == 1 and "第 2 条线是新线" in p[0] and "main" in p[0]


def test_check_lines_known_main_without_new_blocks():
    """review_t08 第 2 条：本世界的主线是已有的 L-001，这次的块都归了新支线，把 L-001 列出来、scenes 写空。"""
    data = line_reply(
        {"id": "L-001", "main": True, "scenes": []}, {"name": "赵五寻亲", "scenes": sorted(ORD)},
        world_outlines=["S-0009"],
    )
    assert check_lines(data, ORD, OUT, {"L-001"}, {"L-001": "林清入京"}) == []
    got = clean_lines(data, ORD, OUT, {"L-001"})
    assert [(t["key"], t["main"]) for t in got["threads"]] == [("L-001", True), (None, False)]


from ligaotai.threads_check import check_order, clean_order, parse_time, score_order

SEGS = {"P-001": ["S-0001", "S-0002"]}
EXP = {"S-0001", "S-0002", "S-0003"}


def order_reply(order, times=None, state="待定"):
    times = {s: [i, "高"] for i, s in enumerate(sorted(EXP))} if times is None else times
    return {"order": order, "times": times, "end": {"state": state, "note": "n"}}


def test_parse_time():
    assert parse_time([1, "高"]) == {"t": 1, "conf": "高"}
    assert parse_time(["2.5", "中"]) == {"t": 2.5, "conf": "中"}
    assert parse_time([None, "很有把握"]) == {"t": None, "conf": "低"}
    assert parse_time({"t": 3, "conf": "低"}) == {"t": 3, "conf": "低"}
    assert parse_time([True, "高"]) is None
    assert parse_time(["不知道", "高"]) is None
    assert parse_time([float("nan"), "高"]) is None
    assert parse_time(5) is None


def test_parse_time_edge_cases():
    assert parse_time({"time": 5, "conf": "高"}) is None  # 字典缺 t 键
    assert parse_time({}) is None
    assert parse_time({"t": 5}) == {"t": 5, "conf": "低"}
    assert parse_time([10 ** 400, "高"]) is None  # 超大整数
    assert parse_time([-(10 ** 400), "高"]) is None
    for s in ("inf", "-inf", "nan", "1e400"):
        assert parse_time([s, "高"]) is None
    assert parse_time([1, " 高 "]) == {"t": 1, "conf": "高"}  # 把握先去空白
    assert parse_time([1, "high"]) == {"t": 1, "conf": "低"}
    assert parse_time([1, "high"], strict=True) is None
    assert parse_time([[1], "高"]) is None and parse_time([{"a": 1}, "高"]) is None


def test_check_order():
    assert check_order(order_reply(["S-0003", "P-001"]), SEGS, EXP) == []
    assert check_order(order_reply(["S-0003", "S-0002", "S-0001"]), SEGS, EXP) == []  # 片段可以拆
    assert check_order(order_reply(["P-001", "S-0001", "S-0003"]), SEGS, EXP) != []  # 重复
    assert check_order(order_reply(["P-001"]), SEGS, EXP) != []  # 漏
    assert check_order(order_reply(["P-001", "S-0003", "P-009"]), SEGS, EXP) != []  # 编造
    assert check_order(order_reply(["P-001", "S-0003"], times={}), SEGS, EXP) != []
    assert check_order(order_reply(["P-001", "S-0003"], state="写完了"), SEGS, EXP) != []
    assert check_order({"order": "乱写"}, SEGS, EXP) == ["缺少 order 列表"]


def test_check_order_partial_segment_reports_missing():
    p = check_order(order_reply(["S-0001", "S-0003"]), SEGS, EXP)
    assert len(p) == 1 and "漏掉" in p[0] and "S-0002" in p[0]


def test_check_order_bad_times():
    times = {"S-0001": [10 ** 400, "高"], "S-0002": {"time": 5, "conf": "高"}, "S-0003": [1, "很有把握"]}
    data = order_reply(["P-001", "S-0003"], times=times)
    p = check_order(data, SEGS, EXP)
    assert len(p) == 2
    assert "格式不对" in p[0] and "S-0001、S-0002" in p[0]
    assert "把握" in p[1] and "S-0003" in p[1]
    got = clean_order(data, SEGS, EXP, sorted(EXP))
    assert got["times"] == {"S-0003": {"t": 1, "conf": "低"}}


def test_clean_order():
    data = order_reply(["S-0003", "P-001", "S-0003", "S-0099"], times={"S-0003": [5, "中"], "S-0001": "乱写"}, state="?")
    got = clean_order(data, SEGS, EXP | {"S-0004"}, ["S-0001", "S-0002", "S-0003", "S-0004"])
    assert got["scenes"] == ["S-0003", "S-0001", "S-0002"]
    assert got["times"] == {"S-0003": {"t": 5, "conf": "中"}}
    assert got["end"] == {"state": "待定", "note": "n"}
    assert got["missing"] == ["S-0004"]
    assert got["failed"] is False


def test_clean_order_unusable_reply_falls_back_to_file_order():
    """order 不是列表、或者一块都没对上：按原稿位置排，标 failed，块一个不丢（调用方当成调用失败）。"""
    fb = ["S-0003", "S-0001", "S-0002"]
    for data in ({"order": "乱写"}, {"order": 5}, {}, {"order": []}, {"order": ["S-0099", "P-009"]}):
        got = clean_order(data, SEGS, EXP, fb)
        assert got == {"scenes": fb, "times": {}, "end": {"state": "待定", "note": ""}, "missing": [], "failed": True}
    got = clean_order(order_reply(["S-0003"]), SEGS, EXP, fb)
    assert got["failed"] is False and got["missing"] == ["S-0001", "S-0002"]


def test_garbage_replies_do_not_wipe_the_line_after_three_tries():
    """review_t06 的现场：「差一点」和「乱写」都只有 1 条问题。传了 score 就留差一点的那次；
    三次全是乱写，清理也不会把整条线清空。"""
    near = json.dumps(order_reply(["S-0003", "P-001"], times={"S-0001": [0, "高"], "S-0002": [1, "高"]}), ensure_ascii=False)
    junk = json.dumps({"order": "乱写"}, ensure_ascii=False)
    fb = sorted(EXP)

    def ask(replies):
        client = LLMClient(AppConfig(), FakeBackend(replies))
        return asyncio.run(client.chat_json(
            "synth", "s", "u", lambda d: check_order(d, SEGS, EXP), tag="t", score=lambda d: score_order(d, SEGS, EXP)
        ))

    for replies in ([near, junk, near], [junk, near, junk], [near, junk, junk]):
        data, problems = ask(replies)
        assert len(problems) == 1 and data["order"] == ["S-0003", "P-001"]
        got = clean_order(data, SEGS, EXP, fb)
        assert got["scenes"] == ["S-0003", "S-0001", "S-0002"] and got["missing"] == [] and got["failed"] is False
    data, _ = ask([junk, junk, junk])
    got = clean_order(data, SEGS, EXP, fb)
    assert got["failed"] is True and got["scenes"] == fb and got["missing"] == []


from ligaotai.threads_check import check_align, check_gaps, clean_align, clean_gaps, score_align, score_gaps

MEMBERS = {"L-001": {"S-0001", "S-0002"}, "L-002": {"S-0003"}, "L-003": {"S-0004"}}


def test_check_align():
    ok = {"threads": [{"id": "L-001", "offset": 0}, {"id": "L-002", "offset": 1.5}, {"id": "L-003", "offset": None}],
          "intersections": [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "r", "same_time": True}]}
    assert check_align(ok, set(MEMBERS), "L-001", MEMBERS) == []
    # 9-26：交汇点必须写 same_time（程序拿 true 的校准时间），没写或写成字符串都让模型改
    for bad in ({}, {"same_time": "true"}):
        c = {k: v for k, v in ok["intersections"][0].items() if k != "same_time"} | bad
        p = check_align({**ok, "intersections": [c]}, set(MEMBERS), "L-001", MEMBERS)
        assert len(p) == 1 and "same_time" in p[0]
    assert check_align({"threads": ok["threads"][:2]}, set(MEMBERS), "L-001", MEMBERS) != []
    bad_offset = {"threads": [{**t, "offset": "很久"} for t in ok["threads"]]}
    assert check_align(bad_offset, set(MEMBERS), "L-001", MEMBERS) != []
    bad_cross = {**ok, "intersections": [{"thread": "L-001", "scene": "S-0001", "main_scene": "S-0002"}]}
    assert check_align(bad_cross, set(MEMBERS), "L-001", MEMBERS) != []
    assert check_align({"threads": 3}, set(MEMBERS), "L-001", MEMBERS) == ["缺少 threads 列表"]


def test_clean_align():
    data = {"threads": [{"id": "L-001", "offset": 9}, {"id": "L-002", "offset": "2"}, {"id": "L-003", "offset": "?"}],
            "intersections": [
                {"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "r", "same_time": True},
                {"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "重复"},
                {"thread": "L-003", "scene": "S-0003", "main_scene": "S-0002"},
            ]}
    offsets, cross = clean_align(data, set(MEMBERS), "L-001", MEMBERS)
    # 主线写了 9：其他线都减 9，保持相对关系（L-002 比主线早 7）
    assert offsets == {"L-001": 0, "L-002": -7.0, "L-003": None}
    assert cross == [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "r", "same_time": True}]
    # 没写 / 写成非布尔值一律当 false：拿不准的交汇点不能拿去校准时间
    for v in (None, "true", 1):
        c = {"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "r", "same_time": v}
        assert clean_align({**data, "intersections": [c]}, set(MEMBERS), "L-001", MEMBERS)[1][0]["same_time"] is False


def test_check_align_main_offset_must_be_zero():
    data = {"threads": [{"id": "L-001", "offset": 9}, {"id": "L-002", "offset": 11}, {"id": "L-003", "offset": None}]}
    p = check_align(data, set(MEMBERS), "L-001", MEMBERS)
    assert len(p) == 1 and "L-001" in p[0] and "offset" in p[0]
    offsets, _ = clean_align(data, set(MEMBERS), "L-001", MEMBERS)
    assert offsets == {"L-001": 0, "L-002": 2, "L-003": None}
    data = {"threads": [{"id": "L-001", "offset": None}, {"id": "L-002", "offset": 11}, {"id": "L-003", "offset": None}]}
    assert check_align(data, set(MEMBERS), "L-001", MEMBERS) == []  # 主线写 null 不算错，清理固定成 0
    assert clean_align(data, set(MEMBERS), "L-001", MEMBERS)[0] == {"L-001": 0, "L-002": 11, "L-003": None}


def test_align_weird_shapes_never_raise():
    ids = set(MEMBERS)
    cases = [
        {"threads": 5}, {"threads": True}, {"threads": [{"id": ["L-001"], "offset": 0}]},
        {"threads": [{"id": "L-001", "offset": 10 ** 400}, {"id": "L-002", "offset": 0}, {"id": "L-003", "offset": 0}]},
        {"threads": [], "intersections": 5},
        {"threads": [], "intersections": [{"thread": ["L-002"], "scene": {"a": 1}, "main_scene": ["S-0001"]}]},
        {"threads": [], "intersections": [{"thread": "L-002", "scene": ["S-0003"], "main_scene": "S-0001"}]},
        {"threads": [], "intersections": [None, 3, "x"]},
    ]
    for data in cases:
        assert check_align(data, ids, "L-001", MEMBERS) != []
        assert score_align(data, ids, "L-001", MEMBERS) > 0
        offsets, cross = clean_align(data, ids, "L-001", MEMBERS)
        assert set(offsets) == ids and offsets["L-001"] == 0 and cross == []


def test_align_huge_integer_offsets_never_raise():
    """rereview_batch1 I-1：偏移写成 309 位的整数（合法 JSON，float 装得下），check 只报「主线要写 0」，
    三次都这样时 chat_json 把它当最好的一次返回；平移时不能因为 int 减 int 超出 float 范围而抛 OverflowError。"""
    ids = {"L-001", "L-002"}
    members = {"L-001": {"S-0001"}, "L-002": {"S-0002"}}
    big = "1" + "0" * 308
    reply = '{"threads": [{"id": "L-001", "offset": ' + big + '}, {"id": "L-002", "offset": -' + big + '}], "intersections": []}'
    client = LLMClient(AppConfig(), FakeBackend([reply] * 3))
    data, problems = asyncio.run(client.chat_json(
        "synth", "s", "u", lambda d: check_align(d, ids, "L-001", members), tag="t",
        score=lambda d: score_align(d, ids, "L-001", members),
    ))
    assert data["threads"][0]["offset"] == 10 ** 308  # 模型给的就是整数
    assert len(problems) == 1 and "L-001" in problems[0] and "offset" in problems[0]
    offsets, cross = clean_align(data, ids, "L-001", members)
    assert offsets == {"L-001": 0, "L-002": None} and cross == []  # -1e308 - 1e308 溢出成 inf，置 null
    data = {"threads": [{"id": "L-001", "offset": 10 ** 308}, {"id": "L-002", "offset": 3}]}
    assert clean_align(data, ids, "L-001", members)[0] == {"L-001": 0, "L-002": -1e308}  # 没溢出的照常平移


def test_clean_align_same_thread_twice_keeps_the_first():
    data = {"threads": [{"id": "L-001", "offset": 0}, {"id": "L-002", "offset": 2}, {"id": "L-002", "offset": 7},
                        {"id": "L-003", "offset": None}]}
    p = check_align(data, set(MEMBERS), "L-001", MEMBERS)
    assert len(p) == 1 and "不止一次" in p[0] and "L-002" in p[0]
    assert clean_align(data, set(MEMBERS), "L-001", MEMBERS)[0]["L-002"] == 2


def test_align_intersections():
    ids = set(MEMBERS)
    base = {"threads": [{"id": "L-001", "offset": 0}, {"id": "L-002", "offset": 1}, {"id": "L-003", "offset": None}]}

    def one(c):
        d = {**base, "intersections": [{**c, "same_time": False}]}  # same_time 另有测试，这里都写上
        return check_align(d, ids, "L-001", MEMBERS), clean_align(d, ids, "L-001", MEMBERS)[1]

    p, cross = one({"thread": "L-002", "scene": "S-0002", "main_scene": "S-0003", "reason": "r"})  # 写反了
    assert len(p) == 1 and "写反" in p[0]
    assert cross == [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "r", "same_time": False}]
    p, cross = one({"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002"})  # 只有 scene 不对
    assert len(p) == 1 and "scene「S-0004」不在 L-002 里" in p[0] and "main_scene" not in p[0] and cross == []
    p, cross = one({"thread": "L-002", "scene": "S-0003", "main_scene": "S-0004"})  # 只有 main_scene 不对
    assert len(p) == 1 and "main_scene「S-0004」不在主线 L-001 里" in p[0] and cross == []
    p, cross = one({"thread": "L-001", "scene": "S-0001", "main_scene": "S-0002"})  # 跟主线自己对齐
    assert len(p) == 1 and "thread" in p[0] and cross == []
    p, cross = one({"thread": "l-2", "scene": "s-0003", "main_scene": "S-2"})  # 编号变体
    assert p == [] and cross == [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "",
                                  "same_time": False}]


def test_align_score_prefers_the_mostly_right_reply():
    """review_t07 场景 A：第 1 次 offset 全对、3 个交汇点写反（3 条问题）；第 2 次只交了交汇点（1 条问题）。"""
    ids = set(MEMBERS)
    swapped = {"threads": [{"id": "L-001", "offset": 0}, {"id": "L-002", "offset": 1}, {"id": "L-003", "offset": 2}],
               "intersections": [{"thread": "L-002", "scene": "S-0002", "main_scene": "S-0003"}] * 3}
    only_crosses = {"intersections": [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002"}]}
    assert len(check_align(swapped, ids, "L-001", MEMBERS)) > len(check_align(only_crosses, ids, "L-001", MEMBERS))
    assert score_align(swapped, ids, "L-001", MEMBERS) < score_align(only_crosses, ids, "L-001", MEMBERS)


LINES = {"L-001": ["S-0001", "S-0002", "S-0003"]}


def test_check_gaps():
    ok = {"gaps": [{"event": "城破", "mentioned_in": ["S-0002"], "thread": "L-001", "after": "S-0001", "before": None}]}
    assert check_gaps(ok, {"S-0002"}, LINES) == []
    assert check_gaps({"gaps": []}, {"S-0002"}, LINES) == []
    assert check_gaps({"gaps": [{**ok["gaps"][0], "event": ""}]}, {"S-0002"}, LINES) != []
    assert check_gaps({"gaps": [{**ok["gaps"][0], "mentioned_in": ["S-0003"]}]}, {"S-0002"}, LINES) != []
    assert check_gaps({"gaps": [{**ok["gaps"][0], "thread": "L-009"}]}, {"S-0002"}, LINES) != []
    assert check_gaps({"gaps": [{**ok["gaps"][0], "after": "S-0099"}]}, {"S-0002"}, LINES) != []
    assert check_gaps({}, {"S-0002"}, LINES) == ["缺少 gaps 列表"]


def test_clean_gaps():
    data = {"gaps": [
        {"event": "城破", "mentioned_in": ["S-0002", "S-0099"], "thread": "L-001", "after": "S-0001", "before": "S-0099"},
        {"event": "婚宴", "mentioned_in": ["S-0002"], "thread": "L-009", "after": "S-0001"},
        {"event": "", "mentioned_in": ["S-0002"]},
        {"event": "没出处", "mentioned_in": ["S-0099"]},
    ]}
    assert clean_gaps(data, {"S-0002"}, LINES) == [
        {"event": "城破", "mentioned_in": ["S-0002"], "thread": "L-001", "after": "S-0001", "before": None},
        {"event": "婚宴", "mentioned_in": ["S-0002"], "thread": None, "after": None, "before": None},
    ]


def test_gaps_weird_shapes_never_raise():
    cases = [
        {"gaps": 5}, {"gaps": True}, {"gap": []},
        {"gaps": [{"event": "e", "mentioned_in": ["S-0002"], "thread": ["L-001"]}]},
        {"gaps": [{"event": "e", "mentioned_in": ["S-0002"], "thread": {"a": 1}}]},
        {"gaps": [{"event": "e", "mentioned_in": ["S-0002"], "thread": "L-001", "after": ["S-0001"], "before": {"a": 1}}]},
        {"gaps": [{"event": ["e"], "mentioned_in": 5}]},
        {"gaps": [None, 3, "x"]},
    ]
    for data in cases:
        assert check_gaps(data, {"S-0002"}, LINES) != []
        assert score_gaps(data, {"S-0002"}, LINES) > 0
        assert isinstance(clean_gaps(data, {"S-0002"}, LINES), list)
    got = clean_gaps(cases[3], {"S-0002"}, LINES)
    assert got == [{"event": "e", "mentioned_in": ["S-0002"], "thread": None, "after": None, "before": None}]
    got = clean_gaps(cases[5], {"S-0002"}, LINES)
    assert got == [{"event": "e", "mentioned_in": ["S-0002"], "thread": "L-001", "after": None, "before": None}]


def test_gaps_place_and_duplicates():
    g = {"event": "城破", "mentioned_in": ["S-0002"], "thread": "L-001"}

    def one(**kw):
        d = {"gaps": [{**g, **kw}]}
        return check_gaps(d, {"S-0002"}, LINES), clean_gaps(d, {"S-0002"}, LINES)

    p, got = one(after="S-0003", before="S-0001")  # 前后颠倒
    assert len(p) == 1 and "after" in p[0] and "before" in p[0]
    assert (got[0]["after"], got[0]["before"]) == (None, None)
    p, got = one(after="S-0002", before="S-0002")  # after 等于 before
    assert len(p) == 1 and (got[0]["after"], got[0]["before"]) == (None, None)
    p, got = one(after="S-0001", before="S-0099")  # before 不在线里
    assert len(p) == 1 and "before 不在 L-001 里" in p[0]
    assert (got[0]["after"], got[0]["before"]) == ("S-0001", None)
    p, got = one(after="S-0099", before="S-0002")  # after 不在线里
    assert len(p) == 1 and "after 不在 L-001 里" in p[0]
    assert (got[0]["after"], got[0]["before"]) == (None, "S-0002")
    p, got = one(thread="")  # 空串当 null
    assert p == [] and got[0]["thread"] is None
    p, got = one(thread=None, after="S-0001", before="S-0003")  # 判断不了属于哪条线：thread 写 null 合格
    assert p == [] and (got[0]["thread"], got[0]["after"], got[0]["before"]) == (None, None, None)
    p, got = one(mentioned_in="S-0002")  # 单个字符串当成只有一项的列表
    assert p == [] and got[0]["mentioned_in"] == ["S-0002"]
    dup = {"gaps": [{**g, "mentioned_in": ["S-0002"]}, {**g, "event": "城破 ", "mentioned_in": ["S-0003", "S-0002"]}]}
    p = check_gaps(dup, {"S-0002", "S-0003"}, LINES)
    assert len(p) == 1 and "同一件事" in p[0]
    assert clean_gaps(dup, {"S-0002", "S-0003"}, LINES) == [
        {"event": "城破", "mentioned_in": ["S-0002", "S-0003"], "thread": "L-001", "after": None, "before": None},
    ]


def test_gaps_score_prefers_the_mostly_right_reply():
    """review_t07 场景 D：4 个缺口里 2 个的 after 写错（清理能修）vs 键名写错整个没有 gaps。"""
    gaps = {"gaps": [{"event": f"e{i}", "mentioned_in": ["S-0002"], "thread": "L-001", "after": "S-0099" if i < 2 else None}
                     for i in range(4)]}
    assert len(check_gaps(gaps, {"S-0002"}, LINES)) == 2
    assert score_gaps(gaps, {"S-0002"}, LINES) < score_gaps({"gap": []}, {"S-0002"}, LINES)
