from ligaotai.archive import SCENE_REF, check_archive, refs_in


def test_抓得出引用():
    assert refs_in("他救了人 [S-0003]，后来去了青州 [S-0004,S-0120]。") == \
        ["S-0003", "S-0004", "S-0120"]


def test_编造的编号要报问题():
    md = "# L-001 林清线\n\n## 来龙去脉\n他救了人 [S-9999]。\n"
    assert check_archive(md, allowed={"S-0003"}, required_headings=["来龙去脉"]) != []


def test_缺小节要报问题():
    md = "# L-001 林清线\n\n## 来龙去脉\n他救了人 [S-0003]。\n"
    problems = check_archive(md, allowed={"S-0003"}, required_headings=["来龙去脉", "写到哪"])
    assert any("写到哪" in p for p in problems)


def test_一个引用都没有要报问题():
    md = "# L-001 林清线\n\n## 来龙去脉\n他救了人。\n"
    assert check_archive(md, allowed={"S-0003"}, required_headings=["来龙去脉"]) != []


def test_正常档案没问题():
    md = "# L-001 林清线\n\n## 来龙去脉\n他救了人 [S-0003]。\n\n## 写到哪\n状态：待定 [S-0003]\n"
    assert check_archive(md, allowed={"S-0003"}, required_headings=["来龙去脉", "写到哪"]) == []
