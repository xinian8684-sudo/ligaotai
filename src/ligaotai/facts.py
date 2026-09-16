"""步骤 7 用的 facts 归一：受控属性表、属性名 / 主语归一、分组、同义值合并。

为什么要受控表：实测两本验收书的场景卡，1538 / 2893 条 facts 里有 991 / 1612 种
自由填写的属性名，平均每种只出现 1.6 次，按 (主语, 属性) 分组基本分不出可比对的组；
而且繁简各写一份（年齡 / 年龄）、一大半根本不是设定而是流水账（行動 / 言語 / 心事）。
见 docs/superpowers/specs/2026-09-16-ligaotai-plan2c-archives-design.md 第 2 节。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 受控属性表，24 项。改这里必须同步改 prompts/cards.md（tests/test_prompts.py 守着）。
ATTRS: tuple[str, ...] = (
    # 人物·身世
    "年龄", "性别", "外貌", "籍贯", "出身", "亲属", "师承",
    # 人物·社会
    "身份", "官职", "称号", "别名", "所属", "居所",
    # 人物·能力
    "性格", "本领", "兵器", "坐骑",
    # 人物·状态
    "伤病", "生死",
    # 地点 / 组织 / 物件
    "位置", "归属", "规模", "来历", "形制",
)
OTHER = "其他"
VALUE_LIMIT = 15  # value 超过这么多字就是在写流水账，丢掉

# 单字繁转简映射表。不是通用繁转简（没装 opencc 就不引入依赖），只覆盖两类字：
# 1) 受控表 24 项属性繁体写法用得到的字（如 齡/職/騎/來/稱/歸 等）；
# 2) 本模块测试用例里出现的几个常见繁体字（變/術），用来验证 to_simplified 本身的行为。
# 计划里的骨架表把 騎 错映射成了「坐」（坐騎 会被转成「坐坐」），且漏了 稱/來/歸，
# 已逐个核对 24 项属性的繁体写法后改正、补齐。
_T2S = str.maketrans({
    "齡": "龄", "別": "别", "貫": "贯", "親": "亲", "屬": "属",
    "師": "师", "職": "职", "稱": "称", "號": "号", "領": "领",
    "騎": "骑", "傷": "伤", "歸": "归", "規": "规", "來": "来",
    "歷": "历", "製": "制",
    # 测试/示例用到的常见字，不属于受控表 24 项：
    "變": "变", "術": "术",
})

_EDGE = re.compile(r"^[\s\W_]+|[\s\W_]+$")


def to_simplified(s: str) -> str:
    """把字符串里 _T2S 覆盖到的繁体字转成简体（非通用繁转简）。"""
    return (s or "").translate(_T2S)


def norm_attr(attr: str) -> str:
    """属性名归一到受控表；对不上的一律落「其他」（不参与矛盾分组）。"""
    s = _EDGE.sub("", to_simplified(attr or ""))
    return s if s in ATTRS else OTHER


_KINDS = ("人物", "地点", "组织")


@dataclass(frozen=True)
class FactRow:
    scene: str      # S-0001
    subject: str    # 已归一的规范主语
    attribute: str  # 已归一的受控属性（可能是 OTHER）
    value: str
    quote: str


def canon_subject(name: str, cmap: dict[tuple[str, str], str]) -> str:
    """人物 / 地点 / 组织三类都试着映；映不上保持原样。"""
    for kind in _KINDS:
        hit = cmap.get((kind, name))
        if hit:
            return hit
    return name


def collect_facts(cards: dict[str, dict], cmap: dict[tuple[str, str], str]) -> list[FactRow]:
    """把 {场景编号: 场景卡 card 部分} 摊平成归一后的 FactRow 列表，按场景编号排序。"""
    rows: list[FactRow] = []
    for sid in sorted(cards):
        for f in cards[sid].get("facts") or []:
            subject = (f.get("subject") or "").strip()
            if not subject:
                continue
            rows.append(FactRow(
                scene=sid,
                subject=canon_subject(subject, cmap),
                attribute=norm_attr(f.get("attribute") or ""),
                value=(f.get("value") or "").strip(),
                quote=f.get("quote") or "",
            ))
    return rows


def group_facts(rows: list[FactRow]) -> dict[tuple[str, str], list[FactRow]]:
    """按 (规范主语, 受控属性) 分组。落「其他」的不参与——它们本来就是模型没想清楚的东西，
    送去比对只会制造误报（spec 6.1 ②）。"""
    groups: dict[tuple[str, str], list[FactRow]] = {}
    for r in rows:
        if r.attribute == OTHER or not r.value:
            continue
        groups.setdefault((r.subject, r.attribute), []).append(r)
    return groups
