from tools.eval_archives import check_refs, sentences


def test_按句切分带编号的正文():
    text = "他救了人 [S-0003]。后来去了青州 [S-0004]。天气很好。"
    assert len(sentences(text)) == 3


def test_标题行不算结论句():
    text = "# L-001 林清线\n## 来龙去脉\n他救了人 [S-0003]。"
    assert len(sentences(text)) == 1


def test_编号不存在算编造():
    res = check_refs({"L-001": "他救了人 [S-9999]。"}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003"})
    assert res["bad"] == 1 and res["total"] == 1
    assert res["fabricated_rate"] == 1.0


def test_编号存在但不属于这条线也算不合格():
    res = check_refs({"L-001": "他救了人 [S-0007]。"}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003", "S-0007"})
    assert res["bad"] == 1
    assert res["details"][0]["why"] == "不属于这份档案"


def test_无引用句率():
    res = check_refs({"L-001": "他救了人 [S-0003]。天气很好。"},
                     allowed={"L-001": {"S-0003"}}, existing={"S-0003"})
    assert res["sentences"] == 2 and res["no_ref"] == 1
    assert res["no_ref_rate"] == 0.5


def test_全部合格时两个率都是0():
    res = check_refs({"L-001": "他救了人 [S-0003]。"}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003"})
    assert res["fabricated_rate"] == 0.0 and res["no_ref_rate"] == 0.0
