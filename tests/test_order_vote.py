from ligaotai.order_vote import agreement, consensus


def test_一份就原样返回():
    assert consensus([["a", "b", "c"]]) == ["a", "b", "c"]


def test_三份里两份一致_少数那份的错被投掉():
    good = ["a", "b", "c", "d", "e"]
    bad = ["d", "a", "b", "c", "e"]  # 一块被排到了最前面
    assert consensus([good, bad, good]) == good
    assert consensus([bad, good, good]) == good


def test_三份各错一处_错的地方不同_都能投回来():
    """9-28 实测雪月梅 L-005：三遍 τ 0.994 / 0.897 / 0.641，多数票之后 0.994～1.0。"""
    truth = list("abcdefgh")
    r1 = list("bacdefgh")
    r2 = list("abcdfegh")
    r3 = list("abcdefhg")
    assert consensus([r1, r2, r3]) == truth


def test_块不全的那份只在它有的块对上投票():
    """某一遍漏了块（missing）：没有的块不算它的票。"""
    full = ["a", "b", "c", "d"]
    part = ["b", "a", "d"]  # 漏了 c，还把 a/b 排反
    got = consensus([full, part, full])
    assert got == full
    assert consensus([part, full]) is not None


def test_结果包含所有份里出现过的块_不丢不重():
    got = consensus([["a", "b"], ["b", "c"], ["c", "a", "d"]])
    assert sorted(got) == ["a", "b", "c", "d"] and len(got) == 4


def test_平票不动_保持第一份的先后():
    assert consensus([["a", "b"], ["b", "a"]]) == ["a", "b"]


def test_agreement_是两份顺序里同向的块对比例():
    assert agreement(["a", "b", "c"], ["a", "b", "c"]) == 1.0
    assert agreement(["a", "b", "c"], ["c", "b", "a"]) == 0.0
    assert agreement(["a", "b", "c"], ["b", "a", "c"]) == 2 / 3
    assert agreement(["a"], ["a"]) == 1.0
