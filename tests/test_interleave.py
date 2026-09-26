"""全书穿插：检查 / 清理 / 可用性。期望值手算。"""
from ligaotai.interleave import check_interleave, clean_interleave, score_interleave, usable_order

TH = {"L-001": ["S-0001", "S-0002", "S-0003"], "L-002": ["S-0010", "S-0011"]}


def test_合法的合并一次过():
    d = {"order": ["S-0001", "S-0010", "S-0002", "S-0011", "S-0003"]}
    assert check_interleave(d, TH) == [] and score_interleave(d, TH) == 0
    assert clean_interleave(d, TH) == d["order"]


def test_编号变体认得出():
    d = {"order": ["s-1", "S-10", "S-0002", "S-0011", "S-0003"]}
    assert check_interleave(d, TH) == []
    assert clean_interleave(d, TH) == ["S-0001", "S-0010", "S-0002", "S-0011", "S-0003"]


def test_线内顺序被打乱_清理时占住位置按原顺序填回():
    """模型给 S-0002、S-0010、S-0001、S-0011、S-0003：L-001 占第 1、3、5 位，按线内原顺序填
    S-0001、S-0002、S-0003；L-002 占第 2、4 位 → S-0001、S-0010、S-0002、S-0011、S-0003。"""
    d = {"order": ["S-0002", "S-0010", "S-0001", "S-0011", "S-0003"]}
    p = check_interleave(d, TH)
    assert len(p) == 1 and "L-001" in p[0] and "L-002" not in p[0]
    assert clean_interleave(d, TH) == ["S-0001", "S-0010", "S-0002", "S-0011", "S-0003"]


def test_漏掉_重复_编造都报_清理补回():
    """漏 S-0002（接在同线前一块 S-0001 后面）、漏 S-0010（线首，放在同线下一块 S-0011 前面）；
    S-0003 重复只留第一次；S-0999 编造丢掉。"""
    d = {"order": ["S-0001", "S-0011", "S-0003", "S-0003", "S-0999"]}
    p = "\n".join(check_interleave(d, TH))
    assert "S-0002" in p and "S-0010" in p and "重复" in p and "S-0999" in p
    assert clean_interleave(d, TH) == ["S-0001", "S-0002", "S-0010", "S-0011", "S-0003"]
    assert score_interleave(d, TH) == 1 + 1 + 3 * 2


def test_整条线都漏了_接在最后():
    d = {"order": ["S-0001", "S-0002", "S-0003"]}
    assert clean_interleave(d, TH) == ["S-0001", "S-0002", "S-0003", "S-0010", "S-0011"]


def test_形状不对():
    for d in (None, [], {"order": "S-0001"}, {"order": [None, 3, {"a": 1}]}):
        assert check_interleave(d, TH) != []
        assert clean_interleave(d, TH) == ["S-0001", "S-0002", "S-0003", "S-0010", "S-0011"]


def test_存下来的顺序跟现在的线对不上就不用():
    good = ["S-0001", "S-0010", "S-0002", "S-0011", "S-0003"]
    assert usable_order(good, TH) == good
    assert usable_order(good[:-1], TH) is None  # 线里新加了块
    assert usable_order(good + ["S-0020"], TH) is None  # 块被移出了这些线
    assert usable_order(["S-0002", "S-0010", "S-0001", "S-0011", "S-0003"], TH) is None  # 作者调了线内顺序
    assert usable_order(good + ["S-0001"], {**TH}) is None  # 重复
    assert usable_order(None, TH) is None and usable_order("x", TH) is None


def test_模型只排了一小半就不算():
    from ligaotai.interleave import mostly_there
    assert mostly_there({"order": ["S-0001", "S-0010", "S-0002", "S-0011"]}, TH) is True  # 4/5 = 0.8
    assert mostly_there({"order": ["S-0001", "S-0010", "S-0002"]}, TH) is False  # 3/5
    assert mostly_there({"order": ["S-0001", "S-0001", "S-0001", "S-0001"]}, TH) is False  # 重复不算数
