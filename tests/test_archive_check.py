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


# --- DE 审查必须修3：真数据上模型常见的写法都要对得上（规范名是繁体、属性节用 ###、主语加粗、
# 写的是别名），且同一主语两个属性各自回填自己的编号 ---

_TRAD_GROUPS = [{"id": "C-004", "subject": "孫悟空", "attribute": "兵器"},
                {"id": "C-005", "subject": "孫悟空", "attribute": "称号"},
                {"id": "C-009", "subject": "劉雲", "attribute": "官职"}]


def test_主语写成简体也能对上繁体规范名():
    md = "## 兵器\n- 孙悟空：金箍棒 / 宝杖（多个说法）[S-0014]\n\n## 官职\n- 刘云：知县 / 知府（多个说法）[S-0020]\n"
    got = backfill_refs(md, _TRAD_GROUPS)
    assert "金箍棒 / 宝杖（多个说法，见矛盾 C-004）" in got
    assert "知县 / 知府（多个说法，见矛盾 C-009）" in got


def test_属性节写成三级标题也能对上():
    md = "## 设定\n### 兵器\n- 孫悟空：金箍棒 / 宝杖（多个说法）[S-0014]\n"
    assert "见矛盾 C-004" in backfill_refs(md, _TRAD_GROUPS)


def test_主语加粗也能对上():
    md = "## 兵器\n- **孫悟空**：金箍棒 / 宝杖（多个说法）[S-0014]\n"
    assert "见矛盾 C-004" in backfill_refs(md, _TRAD_GROUPS)


def test_同一主语两个属性各自回填自己的编号():
    md = ("## 兵器\n- 孙悟空：金箍棒 / 宝杖（多个说法）[S-0014]\n\n"
          "## 称号\n- 孙悟空：美猴王 / 齐天大圣（多个说法）[S-0015]\n")
    got = backfill_refs(md, _TRAD_GROUPS)
    assert "宝杖（多个说法，见矛盾 C-004）" in got
    assert "齐天大圣（多个说法，见矛盾 C-005）" in got


def test_不是受控属性的节标题会切断上一节():
    md = "## 兵器\n- 孫悟空：金箍棒\n\n## 其他\n- 孫悟空：金箍棒 / 宝杖（多个说法）[S-0014]\n"
    assert "见矛盾" not in backfill_refs(md, _TRAD_GROUPS), "其他节里的主语不能按上一节的兵器去对"


def test_写的是别名时按规范名映射对上():
    md = "## 兵器\n- 行者：金箍棒 / 宝杖（多个说法）[S-0014]\n"
    got = backfill_refs(md, _TRAD_GROUPS, aliases={"行者": "孫悟空"})
    assert "见矛盾 C-004" in got
