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
