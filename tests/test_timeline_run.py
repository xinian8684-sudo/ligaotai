from ligaotai.timeline_run import check_death, check_refs, clean_death, clean_refs


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
