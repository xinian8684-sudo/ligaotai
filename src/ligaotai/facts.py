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

# 单字繁转简映射表。不是通用繁转简（没装 opencc 就不引入依赖，真要处理繁体手稿正路是装 opencc），
# 只覆盖受控表 24 项属性繁体写法用得到的字（如 齡/職/騎/來/稱/歸 等），只给 _to_simplified 这一个
# 私有辅助函数用，只服务属性名归一这一个用途——不要拿它转别的文本（比如「騎馬」会被转成「骑馬」，
# 只转对一半，比不转更危险）。
# 计划里的骨架表把 騎 错映射成了「坐」（坐騎 会被转成「坐坐」），且漏了 稱/來/歸，
# 已逐个核对 24 项属性的繁体写法后改正、补齐。
_T2S = str.maketrans({
    "齡": "龄", "別": "别", "貫": "贯", "親": "亲", "屬": "属",
    "師": "师", "職": "职", "稱": "称", "號": "号", "領": "领",
    "騎": "骑", "傷": "伤", "歸": "归", "規": "规", "來": "来",
    "歷": "历", "製": "制",
})

_EDGE = re.compile(r"^[\s\W_]+|[\s\W_]+$")


def _to_simplified(s: str) -> str:
    """把属性名里 _T2S 覆盖到的繁体字转成简体。私有：只给 norm_attr 用，不是通用繁转简，
    别拿它转属性名以外的文本。"""
    return (s or "").translate(_T2S)


def norm_attr(attr: str) -> str:
    """属性名归一到受控表；对不上的一律落「其他」（不参与矛盾分组）。"""
    s = _EDGE.sub("", _to_simplified(attr or ""))
    return s if s in ATTRS else OTHER


# 跟 entities.canonical_map 的真实契约对齐：entities.py 的 TYPES 是英文类型码
# ("person", "location", "organization")，_cmap() 的键就是 (e["type"], 名字)，
# 即英文；中文（entities.TYPE_LABELS）只用来渲染提示词，不是 cmap 的键。
# 之前这里错写成中文「人物/地点/组织」，导致 canon_subject 在真实 cmap 上一条都不命中——
# 因为 ("人物", "行者") 这个键在真实 cmap 里根本不存在，一直查的是不存在的键。
_KINDS = ("person", "location", "organization")


@dataclass(frozen=True)
class FactRow:
    scene: str      # S-0001
    subject: str    # 已归一的规范主语
    attribute: str  # 已归一的受控属性（可能是 OTHER）
    value: str
    quote: str


def canon_subject(name: str, cmap: dict[tuple[str, str], str]) -> str:
    """按 entities.canonical_map 的键形状 (type, 原文名) 归一，type 用英文类型码
    （"person"/"location"/"organization"，跟 entities.TYPES 一致）。三类都试着映；映不上保持原样。"""
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


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_CN_NUM = re.compile(r"[零一二两三四五六七八九十百千万]+")


def _cn_to_int(s: str) -> int | None:
    """「十六」→ 16，「二十四」→ 24，「三千」→ 3000。看不懂就返回 None。

    两类看不懂、必须返回 None（宁可不合并，也不能把不同的值悄悄合成一个，
    合并后只剩一种值的组不进候选，误合并等于静默吞掉一条真矛盾）：
    - 光杆单位：「千年」「万年」「百年」里的「千/万/百」前面没有数字撑着，
      不是数字。「十」除外（「十」本身就是合法数字，等于 10）。
    - 没有任何单位、纯数字连写且长度 > 1：「一九三七」「二零零八」这类年份写法，
      不是「十进制数值」，逐字按最后一位折算（本来的 bug）比不转更危险。
      单字符（如「六」）不受此限——那本来就是明确的个位数。
    """
    total, section, digit = 0, 0, 0
    seen = False
    has_unit = False
    for ch in s:
        if ch in _CN_DIGITS:
            digit = _CN_DIGITS[ch]
            seen = True
        elif ch in _CN_UNITS:
            if ch != "十" and digit == 0 and section == 0 and total == 0:
                return None  # 光杆单位，前面没有数字撑着
            unit = _CN_UNITS[ch]
            if unit == 10000:
                total = (total + section + (digit or 0)) * unit
                section = digit = 0
            else:
                section += (digit if digit or ch != "十" else 1) * unit
                digit = 0
            seen = True
            has_unit = True
        else:
            return None
    if not has_unit and len(s) > 1:
        return None  # 没有单位的连写数字（年份等），不是十进制数值，别折算
    return total + section + digit if seen else None


def norm_number(value: str) -> str:
    """把值里的中文数字换成阿拉伯数字，好让「十六」「16岁」「十六岁」归到一起。"""
    def sub(m: re.Match) -> str:
        n = _cn_to_int(m.group(0))
        return str(n) if n is not None else m.group(0)
    return _CN_NUM.sub(sub, value or "")


def merge_values(rows: list[FactRow]) -> list[dict]:
    """组内把明显同义的值合掉（spec 6.1 ④），返回
    [{"value": 代表值, "scenes": [{"id","quote"}...]}]，按代表值排序。

    三种合并：完全相同、一个是另一个的连续子串（合到长的）、数字规范化后相同。
    """
    buckets: list[dict] = []  # {"value": str, "keys": set[str], "scenes": list}
    for r in sorted(rows, key=lambda r: (-len(r.value), r.value, r.scene)):
        key = norm_number(r.value)
        hit = None
        for b in buckets:
            if key in b["keys"] or any(key in k or k in key for k in b["keys"]):
                hit = b
                break
        if hit is None:
            hit = {"value": r.value, "keys": set(), "scenes": []}
            buckets.append(hit)
        hit["keys"].add(key)
        hit["scenes"].append({"id": r.scene, "quote": r.quote})
    out = [{"value": b["value"], "scenes": sorted(b["scenes"], key=lambda s: s["id"])} for b in buckets]
    return sorted(out, key=lambda b: b["value"])


def candidates(groups: dict[tuple[str, str], list[FactRow]]) -> list[dict]:
    """合并后仍有 ≥2 种值的组才进候选。按 (值种类数 × 涉及场景数) 从大到小排，
    上限截断时先保住信息量大的（spec 6.2）。

    「涉及场景数」是去重后的场景个数，不是 fact 行数——同一个场景里挂了好几条
    fact 不代表牵涉好几个场景，按行数算权重会让同场景多条 fact 的组被高估。
    """
    out = []
    for (subject, attribute), rows in groups.items():
        values = merge_values(rows)
        if len(values) < 2:
            continue
        scenes = len({s["id"] for v in values for s in v["scenes"]})
        out.append({
            "subject": subject,
            "attribute": attribute,
            "values": values,
            "merged": len({r.value for r in rows}) - len(values),
            "weight": len(values) * scenes,
        })
    return sorted(out, key=lambda c: (-c["weight"], c["subject"], c["attribute"]))
