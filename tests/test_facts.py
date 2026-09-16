import pytest

from ligaotai.entities import _cmap as _entities_cmap
from ligaotai.facts import (
    ATTRS,
    OTHER,
    VALUE_LIMIT,
    FactRow,
    _to_simplified,
    candidates,
    collect_facts,
    group_facts,
    merge_values,
    norm_attr,
    norm_number,
)


def _real_cmap(*entities):
    """按 entities.py 的真实契约构造 cmap：entities 是 (type, names, canonical) 的元组列表，
    type 用英文类型码（"person"/"location"/"organization"，见 entities.TYPES）。
    直接复用 entities._cmap 而不是自己拍脑袋拼中文键——这样 entities.py 的 (type, name) 键
    契约一变，这里的测试就会跟着挂，不再只是测我们自己对契约的假设。"""
    return _entities_cmap({"entities": [
        {"type": t, "names": names, "canonical": canonical}
        for t, names, canonical in entities
    ]})


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


def test__to_simplified只转属性名用字():
    assert _to_simplified("年齡") == "年龄"
    assert _to_simplified("坐騎") == "坐骑"
    assert _to_simplified("金箍棒") == "金箍棒"


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
    cmap = _real_cmap(("person", ["行者", "孫大聖"], "孙悟空"))
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
    cmap = _real_cmap(("person", ["行者", "孫大聖"], "孙悟空"))
    cards = {
        "S-0001": {"facts": [{"subject": "行者", "attribute": "兵器", "value": "金箍棒", "quote": "甲"}]},
        "S-0002": {"facts": [{"subject": "孫大聖", "attribute": "兵器", "value": "降妖宝杖", "quote": "乙"}]},
        "S-0003": {"facts": [{"subject": "行者", "attribute": "行動", "value": "打妖怪", "quote": "丙"}]},
    }
    groups = group_facts(collect_facts(cards, cmap))
    assert ("孙悟空", "兵器") in groups
    assert ("孙悟空", "其他") not in groups, "落「其他」的不参与分组"
    assert len(groups[("孙悟空", "兵器")]) == 2


def test_数字规范化():
    assert norm_number("十六") == "16"
    assert norm_number("十六岁") == "16岁"
    assert norm_number("16") == "16"
    assert norm_number("二十四") == "24"
    assert norm_number("三千") == "3000"
    assert norm_number("金箍棒") == "金箍棒"
    # 对照：更大量级、"十X万"这种复合单位不受下面两条新规则影响
    assert norm_number("一万三千五百") == "13500"
    assert norm_number("一百零八") == "108"
    assert norm_number("十万") == "100000"


def test_光杆单位不当数字():
    """「千/万/百」前面没有数字撑着就不是数字，不然「千年」「万年」「百年」这三个
    不同的值会被 merge_values 悄悄合成一组（真实 bug，实测复现过）。"""
    assert norm_number("千年") == "千年"
    assert norm_number("万年") == "万年"
    assert norm_number("百年") == "百年"


def test_无单位连写数字不折叠():
    """没有任何单位的连写数字（年份写法）不是十进制数值，别按最后一位折算，
    否则「一九三七」和「一九四七」会被合并成同一个值（真实 bug，实测复现过）。"""
    assert norm_number("一九三七") == "一九三七"
    assert norm_number("二零零八") == "二零零八"


def test_子串的值合并到长的那个():
    rows = [
        FactRow("S-0001", "孙悟空", "兵器", "金箍棒", "甲"),
        FactRow("S-0002", "孙悟空", "兵器", "如意金箍棒", "乙"),
    ]
    merged = merge_values(rows)
    assert len(merged) == 1
    assert merged[0]["value"] == "如意金箍棒"
    assert sorted(s["id"] for s in merged[0]["scenes"]) == ["S-0001", "S-0002"]


def test_数字相同的值合并():
    rows = [
        FactRow("S-0001", "林清", "年龄", "十六", "甲"),
        FactRow("S-0002", "林清", "年龄", "16岁", "乙"),
        FactRow("S-0003", "林清", "年龄", "十六岁", "丙"),
    ]
    assert len(merge_values(rows)) == 1


def test_合并后只剩一种值的组不进候选():
    groups = {
        ("孙悟空", "兵器"): [
            FactRow("S-0001", "孙悟空", "兵器", "金箍棒", "甲"),
            FactRow("S-0002", "孙悟空", "兵器", "如意金箍棒", "乙"),
        ],
        ("孙悟空", "外貌"): [
            FactRow("S-0003", "孙悟空", "外貌", "毛脸雷公嘴", "丙"),
            FactRow("S-0004", "孙悟空", "外貌", "白面书生", "丁"),
        ],
    }
    cands = candidates(groups)
    assert [c["subject"] + c["attribute"] for c in cands] == ["孙悟空外貌"]
    assert cands[0]["merged"] == 0


def test_候选按值种类数和场景数排序():
    groups = {
        ("甲", "兵器"): [FactRow(f"S-000{i}", "甲", "兵器", f"v{i}", "q") for i in range(1, 4)],
        ("乙", "兵器"): [FactRow(f"S-001{i}", "乙", "兵器", f"w{i}", "q") for i in range(1, 3)],
    }
    cands = candidates(groups)
    assert cands[0]["subject"] == "甲", "值种类多的排前面"


def test_权重按去重场景数不按fact行数():
    """权重是「值种类数 × 涉及场景数」，场景数必须去重。构造两个组让按行数算（旧 bug）
    和按去重场景数算（正确）给出相反的排序，只有算对了才能让「庚」排在「辛」前面：
    - 庚：2 种值，各出现在 3 个不重复场景，共 6 个不重复场景 → 正确权重 2*6=12
    - 辛：3 种值，但都挤在同样的 3 个场景里，共 9 条 fact → 正确权重 3*3=9；
      如果按 fact 行数算（旧 bug），辛会算成 3*9=27，反而排到庚前面——那就是回归。
    """
    rows_geng = (
        [FactRow(f"S-100{i}", "庚", "兵器", "v1", "q") for i in (1, 2, 3)]
        + [FactRow(f"S-100{i}", "庚", "兵器", "v2", "q") for i in (4, 5, 6)]
    )
    rows_xin = [
        FactRow(f"S-200{i}", "辛", "兵器", value, "q")
        for value in ("w1", "w2", "w3")
        for i in (1, 2, 3)
    ]
    groups = {("庚", "兵器"): rows_geng, ("辛", "兵器"): rows_xin}
    cands = candidates(groups)
    assert [c["subject"] for c in cands] == ["庚", "辛"]
    assert cands[0]["weight"] == 12
    assert cands[1]["weight"] == 9
