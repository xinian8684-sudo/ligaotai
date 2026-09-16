import pytest

from ligaotai.facts import (
    ATTRS,
    OTHER,
    VALUE_LIMIT,
    FactRow,
    collect_facts,
    group_facts,
    norm_attr,
    to_simplified,
)


def test_attrs_是24项加兜底():
    assert len(ATTRS) == 24
    assert OTHER == "其他"
    assert OTHER not in ATTRS
    for a in ["年龄", "外貌", "籍贯", "身份", "官职", "兵器", "亲属", "居所", "生死", "位置"]:
        assert a in ATTRS


def test_繁体属性名转简体后对上表():
    assert norm_attr("年齡") == "年龄"
    assert norm_attr("官職") == "官职"
    assert norm_attr("兵器") == "兵器"


def test_表外的属性一律落其他():
    for a in ["行動", "言語", "心事", "反應", "戰況", ""]:
        assert norm_attr(a) == OTHER


def test_属性名两边的空白和标点不影响():
    assert norm_attr(" 年龄 ") == "年龄"
    assert norm_attr("年龄：") == "年龄"


def test_to_simplified处理常见繁体():
    assert to_simplified("變化") == "变化"
    assert to_simplified("法術") == "法术"
    assert to_simplified("金箍棒") == "金箍棒"


def test_value_limit是15():
    assert VALUE_LIMIT == 15


@pytest.mark.parametrize("繁,简", [
    ("年齡", "年龄"), ("官職", "官职"), ("稱號", "称号"), ("別名", "别名"),
    ("所屬", "所属"), ("本領", "本领"), ("坐騎", "坐骑"), ("傷病", "伤病"),
    ("來歷", "来历"), ("形製", "形制"), ("規模", "规模"), ("師承", "师承"),
    ("親屬", "亲属"), ("籍貫", "籍贯"),
])
def test_受控表每一项的繁体写法都能归一(繁, 简):
    assert norm_attr(繁) == 简


def test_主语走实体表归一():
    cmap = {("人物", "行者"): "孙悟空", ("人物", "孫大聖"): "孙悟空"}
    cards = {
        "S-0001": {"facts": [{"subject": "行者", "attribute": "兵器", "value": "金箍棒", "quote": "行者取出金箍棒"}]},
        "S-0002": {"facts": [{"subject": "孫大聖", "attribute": "兵器", "value": "降妖宝杖", "quote": "大圣使降妖宝杖"}]},
    }
    rows = collect_facts(cards, cmap)
    assert [r.subject for r in rows] == ["孙悟空", "孙悟空"]
    assert [r.scene for r in rows] == ["S-0001", "S-0002"]


def test_映不上的主语保持原样不硬凑():
    rows = collect_facts({"S-0001": {"facts": [
        {"subject": "某不知名小妖", "attribute": "兵器", "value": "钢叉", "quote": "小妖持钢叉"}]}}, {})
    assert rows[0].subject == "某不知名小妖"


def test_分组按规范主语和受控属性():
    cmap = {("人物", "行者"): "孙悟空", ("人物", "孫大聖"): "孙悟空"}
    cards = {
        "S-0001": {"facts": [{"subject": "行者", "attribute": "兵器", "value": "金箍棒", "quote": "甲"}]},
        "S-0002": {"facts": [{"subject": "孫大聖", "attribute": "兵器", "value": "降妖宝杖", "quote": "乙"}]},
        "S-0003": {"facts": [{"subject": "行者", "attribute": "行動", "value": "打妖怪", "quote": "丙"}]},
    }
    groups = group_facts(collect_facts(cards, cmap))
    assert ("孙悟空", "兵器") in groups
    assert ("孙悟空", "其他") not in groups, "落「其他」的不参与分组"
    assert len(groups[("孙悟空", "兵器")]) == 2
