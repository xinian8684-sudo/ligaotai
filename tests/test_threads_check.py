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
