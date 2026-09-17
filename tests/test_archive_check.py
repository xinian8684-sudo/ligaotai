from ligaotai.archive import SCENE_REF, backfill_refs, check_archive, refs_in


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


def test_多个说法回填成矛盾编号():
    md = "## 兵器\n- 孙悟空：如意金箍棒 / 降妖宝杖（多个说法）[S-0014,S-0207]\n"
    groups = [{"id": "C-007", "subject": "孙悟空", "attribute": "兵器"}]
    got = backfill_refs(md, groups)
    assert "（多个说法，见矛盾 C-007）" in got


def test_对不上矛盾组的保持原样():
    md = "## 外貌\n- 林清：清瘦（多个说法）[S-0003]\n"
    assert backfill_refs(md, [{"id": "C-007", "subject": "孙悟空", "attribute": "兵器"}]) == md


def test_同一节里多条各自回填():
    md = ("## 兵器\n- 孙悟空：金箍棒 / 宝杖（多个说法）[S-0014]\n"
          "- 猪八戒：钉耙 / 宝杖（多个说法）[S-0020]\n")
    groups = [{"id": "C-007", "subject": "孙悟空", "attribute": "兵器"},
              {"id": "C-008", "subject": "猪八戒", "attribute": "兵器"}]
    got = backfill_refs(md, groups)
    assert "C-007" in got and "C-008" in got


def test_回填不花钱也不改别的字():
    md = "## 兵器\n- 孙悟空：金箍棒（多个说法）[S-0014]\n\n## 年龄\n- 林清：十六 [S-0003]\n"
    got = backfill_refs(md, [{"id": "C-007", "subject": "孙悟空", "attribute": "兵器"}])
    assert "## 年龄\n- 林清：十六 [S-0003]" in got
