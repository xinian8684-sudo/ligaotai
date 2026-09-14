from ligaotai.threads_check import check_worlds, clean_worlds, coverage_problems


def test_coverage_problems():
    assert coverage_problems(["S-0001", "S-0002"], {"S-0001", "S-0002"}) == []
    p = coverage_problems(["S-0001", "S-0001", "S-0009"], {"S-0001", "S-0002"})
    assert len(p) == 3
    assert "S-0009" in p[0] and "S-0001" in p[1] and "S-0002" in p[2]


def test_coverage_lists_at_most_20():
    p = coverage_problems([], {f"S-{i:04d}" for i in range(1, 31)})
    assert p[0].count("S-") == 20


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
    assert check_lines(line_reply(base), ORD, OUT, set()) != []  # 提纲漏了
    assert check_lines(line_reply(base, world_outlines=["S-0009"]), ORD, OUT, set()) == []
    no_main = {**base, "main": False}
    assert check_lines(line_reply(no_main, world_outlines=["S-0009"]), ORD, OUT, set()) != []
    two_main = [base, {"name": "乙", "main": True, "scenes": []}]
    assert check_lines(line_reply(*two_main, world_outlines=["S-0009"]), ORD, OUT, set()) != []
    bad_id = {**base, "id": "L-099"}
    assert check_lines(line_reply(bad_id, world_outlines=["S-0009"]), ORD, OUT, set()) != []
    assert check_lines({"threads": None}, ORD, OUT, set()) == ["缺少 threads 列表"]
    assert check_lines(line_reply(), set(), OUT, set()) != []  # 只有提纲、没线：提纲要放 world_outlines
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


from ligaotai.threads_check import check_order, clean_order, parse_time

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


def test_check_order():
    assert check_order(order_reply(["S-0003", "P-001"]), SEGS, EXP) == []
    assert check_order(order_reply(["S-0003", "S-0002", "S-0001"]), SEGS, EXP) == []  # 片段可以拆
    assert check_order(order_reply(["P-001", "S-0001", "S-0003"]), SEGS, EXP) != []  # 重复
    assert check_order(order_reply(["P-001"]), SEGS, EXP) != []  # 漏
    assert check_order(order_reply(["P-001", "S-0003", "P-009"]), SEGS, EXP) != []  # 编造
    assert check_order(order_reply(["P-001", "S-0003"], times={}), SEGS, EXP) != []
    assert check_order(order_reply(["P-001", "S-0003"], state="写完了"), SEGS, EXP) != []
    assert check_order({"order": "乱写"}, SEGS, EXP) == ["缺少 order 列表"]


def test_clean_order():
    data = order_reply(["S-0003", "P-001", "S-0003", "S-0099"], times={"S-0003": [5, "中"], "S-0001": "乱写"}, state="?")
    got = clean_order(data, SEGS, EXP | {"S-0004"}, ["S-0001", "S-0002", "S-0003", "S-0004"])
    assert got["scenes"] == ["S-0003", "S-0001", "S-0002"]
    assert got["times"] == {"S-0003": {"t": 5, "conf": "中"}}
    assert got["end"] == {"state": "待定", "note": "n"}
    assert got["missing"] == ["S-0004"]


from ligaotai.threads_check import check_align, check_gaps, clean_align, clean_gaps

MEMBERS = {"L-001": {"S-0001", "S-0002"}, "L-002": {"S-0003"}, "L-003": {"S-0004"}}


def test_check_align():
    ok = {"threads": [{"id": "L-001", "offset": 0}, {"id": "L-002", "offset": 1.5}, {"id": "L-003", "offset": None}],
          "intersections": [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "r"}]}
    assert check_align(ok, set(MEMBERS), "L-001", MEMBERS) == []
    assert check_align({"threads": ok["threads"][:2]}, set(MEMBERS), "L-001", MEMBERS) != []
    bad_offset = {"threads": [{**t, "offset": "很久"} for t in ok["threads"]]}
    assert check_align(bad_offset, set(MEMBERS), "L-001", MEMBERS) != []
    bad_cross = {**ok, "intersections": [{"thread": "L-001", "scene": "S-0001", "main_scene": "S-0002"}]}
    assert check_align(bad_cross, set(MEMBERS), "L-001", MEMBERS) != []
    assert check_align({"threads": 3}, set(MEMBERS), "L-001", MEMBERS) == ["缺少 threads 列表"]


def test_clean_align():
    data = {"threads": [{"id": "L-001", "offset": 9}, {"id": "L-002", "offset": "2"}, {"id": "L-003", "offset": "?"}],
            "intersections": [
                {"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "r"},
                {"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "重复"},
                {"thread": "L-003", "scene": "S-0003", "main_scene": "S-0002"},
            ]}
    offsets, cross = clean_align(data, set(MEMBERS), "L-001", MEMBERS)
    assert offsets == {"L-001": 0, "L-002": 2.0, "L-003": None}
    assert cross == [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "r"}]


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
