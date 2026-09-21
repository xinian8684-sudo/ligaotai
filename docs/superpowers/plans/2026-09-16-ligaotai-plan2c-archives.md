# 理稿台 计划②c 实施计划：步骤 7 档案 + 矛盾 + 地图

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把场景卡的 `facts` 改造成可比对的受控属性，然后实现步骤 7 的四件产出——支线档案、世界设定集、矛盾扫描、全书地图——并配套验收工具。

**Architecture:** 新增 `facts.py`（纯函数：属性/主语归一、分组、同义值合并）、`archive.py`（四件产出的编排与落盘）、`archive_input.py`（各次调用的输入准备）、`contradictions.py`（矛盾管线）。模型调用复用 ②b 的 `Caller`（本计划把它从 `threads.py` 抽到 `llm_caller.py` 并参数化缓存路径）。支线档案、世界设定集、矛盾扫描三者并行，完成后程序回填 `C-` 编号，最后跑全书地图。

**Tech Stack:** Python 3.12、uv、pydantic、FastAPI、pytest、asyncio。设计文档：`docs/superpowers/specs/2026-09-16-ligaotai-plan2c-archives-design.md`（下称「spec」）。

**约定（每个任务都适用）：**
- 只在本计划的分支上干活；**禁止 `git stash` / `git checkout --` / `git reset` / `git restore`**，`git add` 只加自己这个任务的文件。
- 跑测试：`uv run pytest tests/xxx.py -v`。全量：`uv run pytest -q`。
- **别在工具参数里敲 `\u` 转义**（会被吃掉，用 `chr(92)` 拼）。
- 中文输出别信终端，要看结果就写文件再读。
- `tools/` 下的脚本必须能 `uv run python tools/xxx.py` 直接跑（`tests/test_tools_scripts.py` 守着）。
- 每个任务最后一步是 commit，commit message 用中文，结尾带 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`。

---

## 文件结构

| 文件 | 职责 | 新建/修改 |
|---|---|---|
| `src/ligaotai/facts.py` | 受控属性表；属性名归一（繁转简 + 对表）、主语归一（走 `实体.json`）、按 (主语,属性) 分组、同义值程序合并 | 新建 |
| `src/ligaotai/llm_caller.py` | 从 `threads.py` 抽出的 `Caller`，缓存路径参数化 | 新建（`threads.py` 改为引用） |
| `src/ligaotai/archive_input.py` | 步骤 7 每次调用的输入准备：支线档案输入、世界设定集输入、地图输入、开放伏笔的程序计算 | 新建 |
| `src/ligaotai/contradictions.py` | 矛盾管线：候选生成、批次切分、模型输出校验、`矛盾.json` 读写与编号沿用 | 新建 |
| `src/ligaotai/archive.py` | 步骤 7 编排：并行调度、`档案/index.json`、`sig` 计算与过期、`C-` 编号回填、summary | 新建 |
| `src/ligaotai/cards.py` | `Fact` 校验接入受控属性表与 15 字上限 | 修改 |
| `src/ligaotai/book.py` | 新增档案相关路径属性 | 修改 |
| `src/ligaotai/api.py` | 挂 `archive` 步骤与单独重跑接口 | 修改 |
| `prompts/cards.md` | 加受控属性表与「只记稳定设定」的硬约束 | 修改 |
| `prompts/archive_thread.md` / `archive_world.md` / `contradictions.md` / `map.md` | 步骤 7 的四个提示词 | 新建 |
| `tools/scramble.py` | 加 `--contradictions N`：植入人造矛盾 | 修改 |
| `tools/eval_archives.py` | 引用核对（编造率、无引用句率）、植入矛盾召回率、人工抽查抽样、`--estimate` | 新建 |

---

## Task 1: 受控属性表与属性名归一

**Files:**
- Create: `src/ligaotai/facts.py`
- Test: `tests/test_facts.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_facts.py
import pytest

from ligaotai.facts import ATTRS, OTHER, VALUE_LIMIT, norm_attr, to_simplified


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_facts.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'ligaotai.facts'`

- [ ] **Step 3: 写实现**

先确认仓库有没有 `opencc`：`uv run python -c "import opencc"`。**有就用它，没有就用内置映射表**（不为这件事加依赖——繁转简只用在属性名这 24 个词上，内置表足够）。

```python
# src/ligaotai/facts.py
"""步骤 7 用的 facts 归一：受控属性表、属性名 / 主语归一、分组、同义值合并。

为什么要受控表：实测两本验收书的场景卡，1538 / 2893 条 facts 里有 991 / 1612 种
自由填写的属性名，平均每种只出现 1.6 次，按 (主语, 属性) 分组基本分不出可比对的组；
而且繁简各写一份（年齡 / 年龄）、一大半根本不是设定而是流水账（行動 / 言語 / 心事）。
见 docs/superpowers/specs/2026-09-16-ligaotai-plan2c-archives-design.md 第 2 节。
"""

from __future__ import annotations

import re

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

# 只覆盖受控表这 24 个词会用到的繁体字，不做通用繁转简。
_T2S = str.maketrans({
    "齡": "龄", "貌": "貌", "籍": "籍", "貫": "贯", "份": "份", "職": "职",
    "號": "号", "別": "别", "屬": "属", "領": "领", "騎": "坐", "馬": "马",
    "傷": "伤", "歷": "历", "製": "制", "規": "规", "模": "模", "師": "师",
    "承": "承", "親": "亲", "縣": "县", "號": "号", "貭": "质",
})

_EDGE = re.compile(r"^[\s\W_]+|[\s\W_]+$")


def to_simplified(s: str) -> str:
    """把字符串里受控表用得到的繁体字转成简体。"""
    return (s or "").translate(_T2S)


def norm_attr(attr: str) -> str:
    """属性名归一到受控表；对不上的一律落「其他」（不参与矛盾分组）。"""
    s = _EDGE.sub("", to_simplified(attr or ""))
    return s if s in ATTRS else OTHER
```

**注意** `_T2S` 只是骨架，写实现时必须逐个核对 24 项属性的繁体写法，确保 `norm_attr("年齡")`、`norm_attr("官職")`、`norm_attr("稱號")`、`norm_attr("別名")`、`norm_attr("所屬")`、`norm_attr("本領")`、`norm_attr("坐騎")`、`norm_attr("傷病")`、`norm_attr("來歷")`、`norm_attr("形製")`、`norm_attr("規模")`、`norm_attr("師承")`、`norm_attr("親屬")` 全部命中。测试里要把这 13 个都断言一遍。

- [ ] **Step 4: 补齐繁体断言并跑测试**

在 `tests/test_facts.py` 加：

```python
@pytest.mark.parametrize("繁,简", [
    ("年齡", "年龄"), ("官職", "官职"), ("稱號", "称号"), ("別名", "别名"),
    ("所屬", "所属"), ("本領", "本领"), ("坐騎", "坐骑"), ("傷病", "伤病"),
    ("來歷", "来历"), ("形製", "形制"), ("規模", "规模"), ("師承", "师承"),
    ("親屬", "亲属"), ("籍貫", "籍贯"),
])
def test_受控表每一项的繁体写法都能归一(繁, 简):
    assert norm_attr(繁) == 简
```

Run: `uv run pytest tests/test_facts.py -v`
Expected: PASS（14 项繁体全部命中；不命中就补 `_T2S`）

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/facts.py tests/test_facts.py
git commit -m "feat: 受控属性表与属性名归一

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: 主语归一与分组

**Files:**
- Modify: `src/ligaotai/facts.py`
- Test: `tests/test_facts.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_facts.py 追加
from ligaotai.facts import FactRow, collect_facts, group_facts


def test_主语走实体表归一():
    # 键是英文类型码，跟 entities._cmap 的真实形状一致——别写成中文
    cmap = {("person", "行者"): "孙悟空", ("person", "孫大聖"): "孙悟空"}
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
    cmap = {("person", "行者"): "孙悟空", ("person", "孫大聖"): "孙悟空"}
    cards = {
        "S-0001": {"facts": [{"subject": "行者", "attribute": "兵器", "value": "金箍棒", "quote": "甲"}]},
        "S-0002": {"facts": [{"subject": "孫大聖", "attribute": "兵器", "value": "降妖宝杖", "quote": "乙"}]},
        "S-0003": {"facts": [{"subject": "行者", "attribute": "行動", "value": "打妖怪", "quote": "丙"}]},
    }
    groups = group_facts(collect_facts(cards, cmap))
    assert ("孙悟空", "兵器") in groups
    assert ("孙悟空", "其他") not in groups, "落「其他」的不参与分组"
    assert len(groups[("孙悟空", "兵器")]) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_facts.py -v`
Expected: FAIL，`ImportError: cannot import name 'FactRow'`

- [ ] **Step 3: 写实现**

`cmap` 的形状跟 `entities.canonical_map(book)` 一致：`dict[tuple[str, str], str]`，键是 `(类型, 原文名)`。

**类型是英文码，不是中文**：`entities.py:34` 是 `TYPES = ("person", "location", "organization")`，`entities.py:575` 的 `_cmap` 直接拿 `e["type"]` 当键；`TYPE_LABELS`（中文）只用来渲染提示词。仓库里另一个消费者 `threads_input.py:71-73` 用的也是 `cmap.get(("person", n))`。**写测试时别自己捏中文键的假 cmap**——那是在测自己的假设，不是测真实契约，测试全绿也挡不住这个 bug。归一时三类都试。

```python
# src/ligaotai/facts.py 追加
from dataclasses import dataclass

_KINDS = ("person", "location", "organization")


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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_facts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/facts.py tests/test_facts.py
git commit -m "feat: facts 主语归一与按(主语,属性)分组

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: 同义值的程序合并（送模型之前降本）

**Files:**
- Modify: `src/ligaotai/facts.py`
- Test: `tests/test_facts.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_facts.py 追加
from ligaotai.facts import candidates, merge_values, norm_number


def test_数字规范化():
    assert norm_number("十六") == "16"
    assert norm_number("十六岁") == "16岁"
    assert norm_number("16") == "16"
    assert norm_number("二十四") == "24"
    assert norm_number("三千") == "3000"
    assert norm_number("金箍棒") == "金箍棒"


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_facts.py -v`
Expected: FAIL，`ImportError: cannot import name 'merge_values'`

- [ ] **Step 3: 写实现**

```python
# src/ligaotai/facts.py 追加
_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_CN_NUM = re.compile(r"[零一二两三四五六七八九十百千万]+")


def _cn_to_int(s: str) -> int | None:
    """「十六」→ 16，「二十四」→ 24，「三千」→ 3000。看不懂就返回 None。"""
    total, section, digit = 0, 0, 0
    seen = False
    for ch in s:
        if ch in _CN_DIGITS:
            digit = _CN_DIGITS[ch]
            seen = True
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if unit == 10000:
                total = (total + section + (digit or 0)) * unit
                section = digit = 0
            else:
                section += (digit if digit or ch != "十" else 1) * unit
                digit = 0
            seen = True
        else:
            return None
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
    上限截断时先保住信息量大的（spec 6.2）。"""
    out = []
    for (subject, attribute), rows in groups.items():
        values = merge_values(rows)
        if len(values) < 2:
            continue
        scenes = sum(len(v["scenes"]) for v in values)
        out.append({
            "subject": subject,
            "attribute": attribute,
            "values": values,
            "merged": len({r.value for r in rows}) - len(values),
            "weight": len(values) * scenes,
        })
    return sorted(out, key=lambda c: (-c["weight"], c["subject"], c["attribute"]))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_facts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/facts.py tests/test_facts.py
git commit -m "feat: 同义值程序合并与候选组排序

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: 场景卡校验接入受控属性表

**Files:**
- Modify: `src/ligaotai/cards.py`（`check_card` 附近 200-240 行、`clean_card` 241-286 行）
- Test: `tests/test_cards.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_cards.py 追加
from ligaotai.cards import Card, check_card, clean_card


def _card(**kw) -> dict:
    base = {"summary": "林清救人", "characters": [{"name": "林清", "role": "主要"}],
            "facts": [], "kind": "正文"}
    base.update(kw)
    return base


def test_表外属性归到其他不当失败():
    text = "林清年方十六，行至青州。"
    data = _card(facts=[{"subject": "林清", "attribute": "行動", "value": "行至青州",
                         "quote": "林清年方十六"}])
    assert check_card(data, text) == [], "属性不对不该触发重试"
    cleaned, dropped = clean_card(Card.model_validate(data), text)
    assert cleaned.facts[0].attribute == "其他"
    assert dropped["attrs"] == 1


def test_value超15字的fact丢掉():
    text = "林清年方十六，行至青州，遇见一个背着竹篓的老人。"
    long_value = "行至青州遇见一个背着竹篓的老人并与之交谈"
    assert len(long_value) > 15
    data = _card(facts=[{"subject": "林清", "attribute": "年龄", "value": long_value,
                         "quote": "林清年方十六"}])
    cleaned, dropped = clean_card(Card.model_validate(data), text)
    assert cleaned.facts == []
    assert dropped["long_values"] == 1


def test_受控属性的短值正常保留():
    text = "林清年方十六，行至青州。"
    data = _card(facts=[{"subject": "林清", "attribute": "年龄", "value": "十六",
                         "quote": "林清年方十六"}])
    cleaned, dropped = clean_card(Card.model_validate(data), text)
    assert len(cleaned.facts) == 1
    assert cleaned.facts[0].attribute == "年龄"
    assert dropped["attrs"] == 0 and dropped["long_values"] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cards.py -v -k "属性 or value超"`
Expected: FAIL，`cleaned.facts[0].attribute` 还是「行動」、`dropped` 里没有 `attrs` 键

- [ ] **Step 3: 写实现**

在 `clean_card` 里，`kept_facts` 算完之后加一段（**放在 `keep_fact` 过滤之后**，这样被 quote / subject 刷掉的不重复计数）：

```python
# src/ligaotai/cards.py，clean_card 内，kept_facts 那一行之后
from .facts import VALUE_LIMIT, norm_attr  # 文件顶部

    kept_facts = [f for f in card.facts if keep_fact(f)]
    dropped_facts = [f.model_dump() for f in card.facts if not keep_fact(f)]

    # 受控属性表（spec 2.4）：属性对不上归「其他」，不当失败也不重试——为这种小事
    # 重试 3 次不划算；value 超长说明模型又在写流水账，这条直接丢。
    n_attrs = 0
    normalized: list[Fact] = []
    long_values: list[dict] = []
    for f in kept_facts:
        a = norm_attr(f.attribute)
        if a != f.attribute:
            n_attrs += 1
        if len(f.value) > VALUE_LIMIT:
            long_values.append(f.model_dump())
            continue
        normalized.append(f.model_copy(update={"attribute": a}))
    kept_facts = normalized
    dropped_facts += long_values
```

然后把 `dropped` 改成：

```python
    dropped = {"facts": dropped_facts, "names": dropped_names,
               "attrs": n_attrs, "long_values": len(long_values)}
```

`check_card` **不改**——受控属性和长值都不触发重试。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_cards.py -v`
Expected: PASS（全部，包括原有用例；原有断言里如果有对 `dropped` 做完整相等比较的，改成只断言关心的键）

- [ ] **Step 5: 把计数写进 book.json 的 cards summary**

在 `cards.py` 里汇总每张卡的 `dropped["attrs"]` / `dropped["long_values"]`，加进步骤 `cards` 的 summary（跟现有 summary 字段并列），字段名 `attrs_normalized`、`long_values_dropped`。跑完能看出模型听话程度。

Run: `uv run pytest tests/test_cards.py tests/test_api_ai.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/ligaotai/cards.py tests/test_cards.py
git commit -m "feat: 场景卡校验接入受控属性表与 15 字上限

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: 改场景卡提示词，加一致性测试

**Files:**
- Modify: `prompts/cards.md`
- Test: `tests/test_prompts.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_prompts.py 追加
from pathlib import Path

from ligaotai.facts import ATTRS, OTHER, VALUE_LIMIT


def test_提示词里的受控属性表和代码一致():
    text = Path("prompts/cards.md").read_text(encoding="utf-8")
    for a in ATTRS:
        assert a in text, f"prompts/cards.md 里缺属性「{a}」"
    assert OTHER in text
    assert str(VALUE_LIMIT) in text


def test_提示词写明只记稳定设定():
    text = Path("prompts/cards.md").read_text(encoding="utf-8")
    assert "稳定" in text and "events" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_prompts.py -v -k 受控`
Expected: FAIL，缺属性

- [ ] **Step 3: 改提示词**

把 `prompts/cards.md` 第 13 条（facts 那条）整条替换成下面四条，其余规则一字不动：

```markdown
4. facts 只记**跨场景稳定的设定**——换个场景还成立的那种（年龄、外貌、籍贯、身份、兵器、亲属关系……）。这一场做的事、这一场说的话、当下的心情、这一仗的战况**一律不许进 facts**，它们写进 events。
5. facts 的 attribute 只能从下面这张表里挑一个，一律写简体；实在挑不出就写「其他」：
   年龄、性别、外貌、籍贯、出身、亲属、师承、身份、官职、称号、别名、所属、居所、性格、本领、兵器、坐骑、伤病、生死、位置、归属、规模、来历、形制、其他
6. facts 的 value 是**短值**，不超过 15 个字，写那个设定本身（「如意金箍棒」「十六」「青州」），不要写成一句叙述。写不下 15 个字说明你在写流水账，那条该进 events。
7. facts 的 quote 必须是从片段中逐字复制的一句话（或一句中连续的一段），用来证明这条事实。不要改字，不要把繁体改成简体。quote 只能是片段里一段连续的原文，不许用省略号、分号或别的符号把几处原文拼接在一起；要证明的内容分散在几处，就拆成几条 facts。quote 去掉标点后至少要有 4 个字，太短（比如「他」「是」）没法核对。facts 的 subject 要照片段原文的写法填一个具体的人名/地名/组织名，最好就是 characters / locations / organizations 里列出的某一个，不要写成「林清的父亲」这种描述性的说法。
```

（原来第 5 条之后的条目序号顺延；`attribute` / `value` 写简体，`subject` / `quote` 照旧照原文抄。）

同时把示例那行改掉：

```json
 "events": ["林清救下受伤的赵五", "林清发现赵五身上的令牌"],
 "facts": [{"subject": "林清", "attribute": "年龄", "value": "十六", "quote": "林清年方十六"},
           {"subject": "林清", "attribute": "籍贯", "value": "青州", "quote": "林清乃青州人氏"}],
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_prompts.py tests/test_cards.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add prompts/cards.md tests/test_prompts.py
git commit -m "feat: 场景卡提示词加受控属性表与只记稳定设定的硬约束

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: 把 Caller 抽成通用组件

**Files:**
- Create: `src/ligaotai/llm_caller.py`
- Modify: `src/ligaotai/threads.py:89-186`（删掉 `Caller` 与 `load_cache`，改为 import）
- Modify: `src/ligaotai/book.py`（加档案相关路径属性）
- Test: `tests/test_llm_caller.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_llm_caller.py
from ligaotai.book import Book
from ligaotai.llm_caller import Caller


def test_caller_用传进来的缓存路径(tmp_path, fake_client):
    book = Book(tmp_path)
    book.root.mkdir(exist_ok=True)
    c = Caller(book, fake_client, lambda *a: None, cache_path=book.archive_cache_path, tag_prefix="archive")
    assert c.cache_path == book.root / "档案缓存.json"


def test_book_档案路径():
    from pathlib import Path
    b = Book(Path("/tmp/x"))
    assert b.archive_dir.name == "档案"
    assert b.thread_archive_dir == b.archive_dir / "支线"
    assert b.world_archive_dir == b.archive_dir / "世界"
    assert b.archive_index_path == b.archive_dir / "index.json"
    assert b.contradictions_path.name == "矛盾.json"
    assert b.map_path.name == "全书地图.md"
    assert b.archive_cache_path.name == "档案缓存.json"
```

`fake_client` 从 `tests/helpers.py` 里已有的假模型 fixture 来；没有就照 `tests/test_threads_run.py` 里现成的假模型写法加一个。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_llm_caller.py -v`
Expected: FAIL，`No module named 'ligaotai.llm_caller'`

- [ ] **Step 3: 写实现**

1. 新建 `src/ligaotai/llm_caller.py`，把 `threads.py` 第 60-186 行的 `_noop`、`load_cache`、`_broken`、`Caller` **原样搬过去**，只改三处：
   - `Caller.__init__` 加两个关键字参数 `cache_path: Path` 和 `tag_prefix: str`，存成 `self.cache_path` / `self.tag_prefix`；
   - `load_cache(book)` 改成 `load_cache(path: Path)`；`__init__` 里 `self.cache = load_cache(cache_path)`；
   - `_save` / `prune_cache` 里的 `self.book.threads_cache_path` 改成 `self.cache_path`；`call` 里的 `tag=f"threads/{tag}"` 改成 `tag=f"{self.tag_prefix}/{tag}"`。

   **其余逻辑一个字不动**（三种失败的处理、`usable`、缓存删除、进度回调都保持原样）。

2. `threads.py` 顶部改成 `from .llm_caller import Caller, load_cache, _noop`，删掉搬走的那一段；`run_threads` 里构造 Caller 的地方补上 `cache_path=book.threads_cache_path, tag_prefix="threads"`。

3. `book.py` 加路径属性：

```python
# src/ligaotai/book.py，threads_cache_path 之后
    @property
    def archive_dir(self) -> Path:
        return self.root / "档案"

    @property
    def thread_archive_dir(self) -> Path:
        return self.archive_dir / "支线"

    @property
    def world_archive_dir(self) -> Path:
        return self.archive_dir / "世界"

    @property
    def archive_index_path(self) -> Path:
        """每份档案对应的编号、输入签名、是否过期。"""
        return self.archive_dir / "index.json"

    @property
    def contradictions_path(self) -> Path:
        return self.root / "矛盾.json"

    @property
    def map_path(self) -> Path:
        return self.root / "全书地图.md"

    @property
    def archive_cache_path(self) -> Path:
        """步骤 7 每次模型调用的缓存。"""
        return self.root / "档案缓存.json"
```

- [ ] **Step 4: 跑测试确认通过（含归线的全部测试，证明抽取没改行为）**

Run: `uv run pytest tests/test_llm_caller.py tests/test_book.py tests/test_threads.py tests/test_threads_run.py tests/test_api_threads.py -q`
Expected: PASS，一个都不能挂

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/llm_caller.py src/ligaotai/threads.py src/ligaotai/book.py tests/test_llm_caller.py
git commit -m "refactor: Caller 抽成通用组件，缓存路径参数化

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: 档案 index 的签名与按编号对账

**Files:**
- Create: `src/ligaotai/archive.py`
- Test: `tests/test_archive_index.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_archive_index.py
from ligaotai.archive import load_index, map_sig, reconcile, thread_sig, world_sig, write_index


def test_线的签名跟着成员和顺序变():
    t = {"id": "L-001", "name": "取经", "scenes": ["S-0001", "S-0002"],
         "end": {"state": "待定", "note": "", "last": "S-0002"}}
    hashes = {"S-0001": "a", "S-0002": "b"}
    gaps = []
    base = thread_sig(t, hashes, gaps)
    assert thread_sig(t, hashes, gaps) == base, "同样的输入要稳定"
    assert thread_sig({**t, "scenes": ["S-0002", "S-0001"]}, hashes, gaps) != base, "顺序变了要变"
    assert thread_sig(t, {"S-0001": "a", "S-0002": "c"}, gaps) != base, "块内容变了要变"
    assert thread_sig(t, hashes, [{"event": "青州城破"}]) != base, "缺口变了要变"


def test_世界的签名跟着成员和规范名映射变():
    w = {"id": "W-01", "name": "人间"}
    base = world_sig(w, ["S-0001"], {"S-0001": "a"}, "cmap-v1")
    assert world_sig(w, ["S-0001"], {"S-0001": "a"}, "cmap-v2") != base


def test_地图签名是全部档案内容的哈希(tmp_path):
    f1, f2 = tmp_path / "a.md", tmp_path / "b.md"
    f1.write_text("甲", encoding="utf-8")
    f2.write_text("乙", encoding="utf-8")
    base = map_sig([f1, f2])
    f2.write_text("丙", encoding="utf-8")
    assert map_sig([f1, f2]) != base


def test_对账把找不到对应线的档案标过期():
    index = {"threads": {"L-001": {"outdated": False}, "L-009": {"outdated": False}},
             "worlds": {"W-01": {"outdated": False}}, "map": {"outdated": False}}
    stale = reconcile(index, thread_ids={"L-001"}, world_ids={"W-01"})
    assert stale == ["L-009"]
    assert index["threads"]["L-009"]["outdated"] is True
    assert index["threads"]["L-001"]["outdated"] is False


def test_index读写往返(tmp_path):
    from ligaotai.book import Book
    book = Book(tmp_path)
    book.root.mkdir(exist_ok=True)
    data = {"threads": {}, "worlds": {}, "map": {}}
    write_index(book, data)
    assert load_index(book) == data


def test_index不存在时给空壳(tmp_path):
    from ligaotai.book import Book
    book = Book(tmp_path)
    book.root.mkdir(exist_ok=True)
    assert load_index(book) == {"threads": {}, "worlds": {}, "map": {}}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_archive_index.py -v`
Expected: FAIL，`No module named 'ligaotai.archive'`

- [ ] **Step 3: 写实现**

```python
# src/ligaotai/archive.py
"""步骤 7：支线档案 + 世界设定集 + 矛盾扫描 + 全书地图。

见 docs/superpowers/specs/2026-09-16-ligaotai-plan2c-archives-design.md。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .book import Book
from .fsutil import read_json, write_json

EMPTY_INDEX = {"threads": {}, "worlds": {}, "map": {}}


def _digest(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(p, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def thread_sig(thread: dict, scene_hashes: dict[str, str], gaps: list[dict]) -> str:
    """一条线的输入签名：线名 + 有序场景编号 + 每块的 scene_hash + 断点 + 这条线的缺口。"""
    scenes = list(thread.get("scenes") or [])
    return _digest(
        thread.get("name", ""),
        scenes,
        [scene_hashes.get(s, "") for s in scenes],
        thread.get("end") or {},
        [g.get("event", "") for g in gaps],
    )


def world_sig(world: dict, scenes: list[str], scene_hashes: dict[str, str], cmap_sig: str) -> str:
    """一个世界的输入签名：世界名 + 该世界所有块的 scene_hash + 规范名映射版本。"""
    ordered = sorted(scenes)
    return _digest(world.get("name", ""), ordered,
                   [scene_hashes.get(s, "") for s in ordered], cmap_sig)


def map_sig(files: list[Path]) -> str:
    """地图的输入签名：全部档案文件内容的哈希。"""
    parts = []
    for p in sorted(files, key=lambda p: p.name):
        try:
            parts.append(p.read_text(encoding="utf-8"))
        except OSError:
            parts.append("")
    return _digest(parts)


def reconcile(index: dict, thread_ids: set[str], world_ids: set[str]) -> list[str]:
    """按编号对账（spec 7.1）：index 里有、但线 / 世界已经不存在的档案标过期。
    不删文件——作者可能还想看。返回被标过期的编号。"""
    stale = []
    for oid, entry in sorted(index.get("threads", {}).items()):
        if oid not in thread_ids:
            entry["outdated"] = True
            stale.append(oid)
    for oid, entry in sorted(index.get("worlds", {}).items()):
        if oid not in world_ids:
            entry["outdated"] = True
            stale.append(oid)
    return stale


def load_index(book: Book) -> dict:
    data = read_json(book.archive_index_path, None)
    if not isinstance(data, dict):
        return json.loads(json.dumps(EMPTY_INDEX))
    for k, empty in (("threads", {}), ("worlds", {}), ("map", {})):
        data.setdefault(k, json.loads(json.dumps(empty)))
    return data


def write_index(book: Book, data: dict) -> None:
    book.archive_dir.mkdir(parents=True, exist_ok=True)
    write_json(book.archive_index_path, data)
```

写之前确认 `fsutil.read_json` 的签名（有没有默认值参数），不一致就按仓库里的实际签名来。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_archive_index.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/archive.py tests/test_archive_index.py
git commit -m "feat: 档案 index 的输入签名与按编号对账

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: 矛盾扫描的输入渲染与批次切分

**Files:**
- Create: `src/ligaotai/contradictions.py`
- Test: `tests/test_contradictions.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_contradictions.py
from ligaotai.contradictions import batches, group_text, scene_times


def test_场景的全局故事时间是线的offset加线内时间():
    threads = [
        {"id": "L-001", "offset": 0, "scenes": ["S-0001"], "times": {"S-0001": {"t": 3.0, "conf": "高"}}},
        {"id": "L-002", "offset": 10, "scenes": ["S-0100"], "times": {"S-0100": {"t": 2.0, "conf": "低"}}},
    ]
    t = scene_times(threads)
    assert t["S-0001"] == {"t": 3.0, "conf": "高", "thread": "L-001"}
    assert t["S-0100"] == {"t": 12.0, "conf": "低", "thread": "L-002"}


def test_没有时间估计的场景不报错():
    threads = [{"id": "L-001", "offset": 0, "scenes": ["S-0001"], "times": {}}]
    assert scene_times(threads)["S-0001"]["t"] is None


def test_渲染的组带引用编号和时间():
    cand = {"subject": "孙悟空", "attribute": "兵器", "values": [
        {"value": "金箍棒", "scenes": [{"id": "S-0014", "quote": "取出金箍棒"}]},
        {"value": "降妖宝杖", "scenes": [{"id": "S-0207", "quote": "使降妖宝杖"}]},
    ]}
    times = {"S-0014": {"t": 3.0, "conf": "高", "thread": "L-001"},
             "S-0207": {"t": 5.0, "conf": "低", "thread": "L-001"}}
    text = group_text("C-001", cand, times, unit="年")
    assert "C-001" in text and "孙悟空" in text and "兵器" in text
    assert "S-0014" in text and "取出金箍棒" in text
    assert "低" in text, "置信度低的要标出来给模型"
    assert "年" in text


def test_按token上限切批():
    cands = [{"subject": f"人{i}", "attribute": "兵器", "values": [
        {"value": "甲", "scenes": [{"id": "S-0001", "quote": "x" * 100}]},
        {"value": "乙", "scenes": [{"id": "S-0002", "quote": "y" * 100}]}]} for i in range(10)]
    got = batches(cands, {}, unit="年", budget=600)
    assert len(got) > 1
    assert sum(len(b) for b in got) == 10, "一个组都不能丢"


def test_单个组超预算也自成一批():
    cands = [{"subject": "甲", "attribute": "兵器", "values": [
        {"value": "v", "scenes": [{"id": "S-0001", "quote": "x" * 5000}]},
        {"value": "w", "scenes": [{"id": "S-0002", "quote": "y" * 5000}]}]}]
    got = batches(cands, {}, unit="年", budget=100)
    assert len(got) == 1 and len(got[0]) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_contradictions.py -v`
Expected: FAIL，`No module named 'ligaotai.contradictions'`

- [ ] **Step 3: 写实现**

```python
# src/ligaotai/contradictions.py
"""矛盾扫描：程序分组 → 按批交模型判断（spec 第 6 节）。

时间只作参考给模型判断「是不是随故事推进的合理变化」，不拿它做硬判断——
②b 验收已证实步骤 6 的故事时间估计不硬（L-003 单线 τ 只有 0.32）。
"""

from __future__ import annotations


def scene_times(threads: list[dict]) -> dict[str, dict]:
    """每个场景的全局故事时间 = 这条线的 offset + 线内时间。没估过的 t 给 None。"""
    out: dict[str, dict] = {}
    for t in threads:
        offset = t.get("offset") or 0
        times = t.get("times") or {}
        for sid in t.get("scenes") or []:
            row = times.get(sid) or {}
            v = row.get("t")
            out[sid] = {
                "t": (offset + v) if isinstance(v, (int, float)) else None,
                "conf": row.get("conf", ""),
                "thread": t.get("id", ""),
            }
    return out


def _scene_line(s: dict, times: dict[str, dict], unit: str) -> str:
    info = times.get(s["id"]) or {}
    bits = [f"[{s['id']}]"]
    if info.get("thread"):
        bits.append(info["thread"])
    if info.get("t") is not None:
        conf = info.get("conf") or ""
        bits.append(f"故事时间约 {info['t']}{unit}" + (f"（把握{conf}）" if conf else ""))
    else:
        bits.append("故事时间未知")
    return "    " + " ".join(bits) + "：" + (s.get("quote") or "")


def group_text(cid: str, cand: dict, times: dict[str, dict], unit: str) -> str:
    """把一个候选组渲染成交给模型的文本。"""
    lines = [f"{cid} 主语：{cand['subject']}　属性：{cand['attribute']}"]
    for v in cand["values"]:
        lines.append(f"  值「{v['value']}」出现在：")
        for s in v["scenes"]:
            lines.append(_scene_line(s, times, unit))
    return "\n".join(lines)


def batches(cands: list[dict], times: dict[str, dict], unit: str, budget: int) -> list[list[dict]]:
    """按输入字符数上限切批（按 1 字符 1 token 估，偏保守，同 ②b 的做法）。
    单个组自己就超预算的，自成一批——不丢任何组。"""
    out: list[list[dict]] = []
    cur: list[dict] = []
    cost = 0
    for i, c in enumerate(cands):
        n = len(group_text(f"C-{i:03d}", c, times, unit))
        if cur and cost + n > budget:
            out.append(cur)
            cur, cost = [], 0
        cur.append(c)
        cost += n
    if cur:
        out.append(cur)
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_contradictions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/contradictions.py tests/test_contradictions.py
git commit -m "feat: 矛盾扫描的输入渲染与批次切分

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: 矛盾扫描的提示词与输出校验

**Files:**
- Create: `prompts/contradictions.md`
- Modify: `src/ligaotai/contradictions.py`
- Test: `tests/test_contradictions.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_contradictions.py 追加
import pytest

from ligaotai.contradictions import check_output, clean_output


def _out(**kw):
    base = {"id": "C-001", "status": "真矛盾", "level": "严重",
            "category": "人物", "reason": "两处写的不是一件兵器 [S-0014][S-0207]"}
    base.update(kw)
    return {"groups": [base]}


def test_输出覆盖不全要报问题():
    assert check_output(_out(), {"C-001", "C-002"}) != []


def test_多出来的编号要报问题():
    assert check_output(_out(), set()) != []


def test_status不在三值里要报问题():
    assert check_output(_out(status="也许"), {"C-001"}) != []


def test_真矛盾没给严重度要报问题():
    assert check_output(_out(level=""), {"C-001"}) != []


def test_合理变化的严重度留空是对的():
    assert check_output(_out(status="合理变化", level=""), {"C-001"}) == []


def test_reason不带场景编号要报问题():
    assert check_output(_out(reason="就是不一样"), {"C-001"}) != []


def test_正常输出没问题():
    assert check_output(_out(), {"C-001"}) == []


def test_clean丢掉编造的编号并给漏掉的兜底():
    data = {"groups": [
        {"id": "C-001", "status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0014]"},
        {"id": "C-999", "status": "真矛盾", "level": "严重", "category": "人物", "reason": "y [S-0001]"},
    ]}
    got = clean_output(data, {"C-001", "C-002"})
    assert set(got) == {"C-001", "C-002"}
    assert got["C-002"]["status"] == "无法判断", "模型没答的按宁可多报兜底"
    assert got["C-002"]["reason"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_contradictions.py -v -k "check_output or clean or status or reason"`
Expected: FAIL，`ImportError: cannot import name 'check_output'`

- [ ] **Step 3: 写实现**

```python
# src/ligaotai/contradictions.py 追加
import re

STATUSES = ("真矛盾", "合理变化", "无法判断")
LEVELS = ("严重", "中等", "轻微")
CATEGORIES = ("人物", "设定", "时间", "称谓")
_SCENE_REF = re.compile(r"\[S-\d{4}(?:,S-\d{4})*\]")


def check_output(data, ids: set[str]) -> list[str]:
    """模型输出的检查，返回要反馈给模型的问题（空列表 = 没问题）。"""
    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        return ["输出要是 {\"groups\": [...]} 的形状"]
    problems = []
    got = [g for g in data["groups"] if isinstance(g, dict)]
    seen = {g.get("id") for g in got}
    missing = sorted(ids - seen)
    extra = sorted(x for x in seen - ids if x)
    if missing:
        problems.append("这些编号没答：" + "、".join(missing[:10]))
    if extra:
        problems.append("这些编号不在我给你的列表里：" + "、".join(extra[:10]))
    for g in got:
        gid = g.get("id", "?")
        if g.get("status") not in STATUSES:
            problems.append(f"{gid} 的 status 只能是：" + " / ".join(STATUSES))
        if g.get("status") == "真矛盾" and g.get("level") not in LEVELS:
            problems.append(f"{gid} 判了真矛盾就要给 level：" + " / ".join(LEVELS))
        if g.get("category") not in CATEGORIES:
            problems.append(f"{gid} 的 category 只能是：" + " / ".join(CATEGORIES))
        if not _SCENE_REF.search(g.get("reason") or ""):
            problems.append(f"{gid} 的 reason 里要带场景编号，写成 [S-0014] 这样")
    return problems[:8]


def clean_output(data, ids: set[str]) -> dict[str, dict]:
    """整理成 {编号: 判断}。编造的编号丢掉；模型没答的按「宁可多报」兜底成「无法判断」。"""
    out: dict[str, dict] = {}
    for g in (data or {}).get("groups") or []:
        gid = g.get("id")
        if not isinstance(g, dict) or gid not in ids or gid in out:
            continue
        status = g.get("status") if g.get("status") in STATUSES else "无法判断"
        level = g.get("level") if g.get("level") in LEVELS else ""
        out[gid] = {
            "status": status,
            "level": level if status == "真矛盾" else "",
            "category": g.get("category") if g.get("category") in CATEGORIES else "设定",
            "reason": (g.get("reason") or "").strip(),
        }
    for gid in sorted(ids - set(out)):
        out[gid] = {"status": "无法判断", "level": "", "category": "设定",
                    "reason": "模型没有给出判断，按宁可多报保留，请人工看一眼"}
    return out
```

- [ ] **Step 4: 写提示词**

```markdown
<!-- prompts/contradictions.md -->
判断一批「同一个主语、同一个属性、前后写了不一样的值」的组，哪些是真矛盾，哪些是随故事推进的合理变化。

## system

你在帮一位作者整理一部长篇小说的乱稿。下面每一组是：同一个主语、同一个属性，在不同场景里写出了不一样的值。你要逐组判断。

规则：
1. 每一组都要答，不许漏，也不许答我没给你的编号。
2. status 三选一：
   - 真矛盾：两个值不可能同时成立，作者写岔了。
   - 合理变化：随故事推进本来就会变（年龄长了、升了官、换了兵器、受了伤），或者只是详略不同、同一件事的不同说法。
   - 无法判断：拿不准。**拿不准就写无法判断，不要硬判成合理变化**——作者宁可多看几条误报，也不想漏掉真矛盾。
3. 判了真矛盾，level 三选一：严重 / 中等 / 轻微。合理变化和无法判断的 level 留空字符串。
4. category 四选一：人物 / 设定 / 时间 / 称谓。
5. reason 一句话说清楚为什么，**必须带场景编号**，写成 [S-0014] 这样；多个写 [S-0014,S-0207]。拿不出编号就别写这句。
6. 每组给的「故事时间」是估出来的，只能当参考，不要拿它当硬证据——把握低的那些尤其不可靠。

只输出 JSON：
{"groups": [{"id": "C-001", "status": "真矛盾", "level": "严重", "category": "人物", "reason": "……[S-0014][S-0207]"}]}

## user

这本书的故事时间单位是「$unit」。

$groups
```

在 `contradictions.py` 里加渲染入口：

```python
def render_values(cands: list[dict], start: int, times: dict[str, dict], unit: str) -> tuple[str, dict[str, dict]]:
    """把一批候选组渲染成提示词的 $groups，同时返回 {本批编号: 候选组}。
    编号在这一批里从 start 开始连号，落盘时再换成 矛盾.json 的正式编号。"""
    numbered = {f"C-{start + i:03d}": c for i, c in enumerate(cands)}
    text = "\n\n".join(group_text(cid, c, times, unit) for cid, c in numbered.items())
    return text, numbered
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_contradictions.py tests/test_prompts.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add prompts/contradictions.md src/ligaotai/contradictions.py tests/test_contradictions.py
git commit -m "feat: 矛盾扫描提示词与输出校验

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 10: 矛盾.json 的落盘、编号沿用与 verdict 迁移

**Files:**
- Modify: `src/ligaotai/contradictions.py`
- Test: `tests/test_contradictions.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_contradictions.py 追加
from ligaotai.contradictions import build_result


def _cand(subject, attribute, values):
    return {"subject": subject, "attribute": attribute, "merged": 0,
            "values": [{"value": v, "scenes": [{"id": s, "quote": "q"}]} for v, s in values]}


def test_编号取next_id只增不减():
    old = {"next_id": 5, "groups": []}
    res = build_result([_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
                       {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
                       {}, old, stats={})
    assert res["groups"][0]["id"] == "C-005"
    assert res["next_id"] == 6


def test_同一主语属性重跑沿用原编号():
    old = {"next_id": 9, "groups": [{"id": "C-003", "subject": "甲", "attribute": "兵器", "verdict": None}]}
    res = build_result([_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
                       {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
                       {}, old, stats={})
    assert res["groups"][0]["id"] == "C-003"
    assert res["next_id"] == 9, "沿用了就不该消耗新号"


def test_verdict按主语属性迁移():
    old = {"next_id": 9, "groups": [
        {"id": "C-003", "subject": "甲", "attribute": "兵器", "verdict": {"choice": "v"}},
        {"id": "C-004", "subject": "乙", "attribute": "外貌", "verdict": {"choice": "x"}},
    ]}
    res = build_result([_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
                       {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
                       {}, old, stats={})
    assert res["groups"][0]["verdict"] == {"choice": "v"}
    assert res["orphan_verdicts"] == [{"subject": "乙", "attribute": "外貌", "verdict": {"choice": "x"}}]


def test_场景里带上故事时间和所属线():
    times = {"S-0001": {"t": 3.0, "conf": "高", "thread": "L-001"}}
    res = build_result([_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
                       {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
                       times, {"next_id": 1, "groups": []}, stats={})
    s = res["groups"][0]["values"][0]["scenes"][0]
    assert s["t"] == 3.0 and s["conf"] == "高" and s["thread"] == "L-001"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_contradictions.py -v -k "编号 or verdict or 故事时间和"`
Expected: FAIL，`ImportError: cannot import name 'build_result'`

- [ ] **Step 3: 写实现**

```python
# src/ligaotai/contradictions.py 追加
from .book import now_iso


def build_result(cands: list[dict], judged: dict[int, dict], times: dict[str, dict],
                 old: dict, stats: dict, skipped: list[dict] | None = None) -> dict:
    """拼出 矛盾.json（spec 7.2）。

    `judged` 的键是 cands 的下标。编号按 (规范主语, 属性) 沿用上一次的，沿用不到的取
    只增不减的 next_id（②a / ②b 撞号踩过的坑）。作者的 verdict 也按 (主语, 属性) 迁移。
    """
    old_by_key = {(g.get("subject"), g.get("attribute")): g for g in old.get("groups") or []}
    next_id = int(old.get("next_id") or 1)
    used_keys = set()
    groups = []
    for i, c in enumerate(cands):
        key = (c["subject"], c["attribute"])
        used_keys.add(key)
        prev = old_by_key.get(key)
        if prev and prev.get("id"):
            gid = prev["id"]
        else:
            gid = f"C-{next_id:03d}"
            next_id += 1
        j = judged.get(i) or {"status": "无法判断", "level": "", "category": "设定",
                              "reason": "这一批调用失败，没拿到判断"}
        values = []
        for v in c["values"]:
            scenes = []
            for s in v["scenes"]:
                info = times.get(s["id"]) or {}
                scenes.append({"id": s["id"], "quote": s.get("quote", ""),
                               "thread": info.get("thread", ""),
                               "t": info.get("t"), "conf": info.get("conf", "")})
            values.append({"value": v["value"], "scenes": scenes})
        groups.append({
            "id": gid, "subject": c["subject"], "attribute": c["attribute"],
            "status": j["status"], "level": j["level"], "category": j["category"],
            "reason": j["reason"], "values": values,
            "verdict": (prev or {}).get("verdict"),
        })
    orphans = [{"subject": k[0], "attribute": k[1], "verdict": g["verdict"]}
               for k, g in sorted(old_by_key.items(), key=lambda kv: (kv[0][0], kv[0][1]))
               if k not in used_keys and g.get("verdict")]
    return {
        "generated": now_iso(),
        "next_id": next_id,
        "groups": groups,
        "skipped": list(skipped or []),
        "orphan_verdicts": orphans,
        "stats": dict(stats),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_contradictions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/contradictions.py tests/test_contradictions.py
git commit -m "feat: 矛盾.json 落盘、编号沿用与 verdict 迁移

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 11: 候选上限保护

**Files:**
- Modify: `src/ligaotai/contradictions.py`、`src/ligaotai/book.py`（`DEFAULT_SETTINGS`）
- Test: `tests/test_contradictions.py`、`tests/test_book.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_contradictions.py 追加
from ligaotai.contradictions import cap


def test_超上限的按权重截断且不静默丢弃():
    cands = [{"subject": f"人{i}", "attribute": "兵器", "weight": i,
              "values": [{"value": "v", "scenes": [{"id": "S-0001", "quote": "q"}]},
                         {"value": "w", "scenes": [{"id": "S-0002", "quote": "q"}]}]}
             for i in range(5)]
    cands.sort(key=lambda c: -c["weight"])
    kept, skipped = cap(cands, 2)
    assert len(kept) == 2
    assert [c["subject"] for c in kept] == ["人4", "人3"]
    assert len(skipped) == 3
    assert skipped[0] == {"subject": "人2", "attribute": "兵器", "reason": "超过上限"}


def test_没超上限就原样返回():
    cands = [{"subject": "甲", "attribute": "兵器", "weight": 1, "values": []}]
    kept, skipped = cap(cands, 10)
    assert kept == cands and skipped == []
```

```python
# tests/test_book.py 追加
def test_默认设置有矛盾扫描的两个上限():
    from ligaotai.book import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["contradictions_batch_tokens"] == 30000
    assert DEFAULT_SETTINGS["contradictions_max_groups"] == 2000
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_contradictions.py tests/test_book.py -v -k "上限 or cap or 默认设置有矛盾"`
Expected: FAIL

- [ ] **Step 3: 写实现**

```python
# src/ligaotai/contradictions.py 追加
def cap(cands: list[dict], limit: int) -> tuple[list[dict], list[dict]]:
    """候选组超上限就截断（cands 已按权重排好序），被砍掉的记进 skipped，
    不静默丢弃（spec 6.2）。"""
    if len(cands) <= limit:
        return cands, []
    kept = cands[:limit]
    skipped = [{"subject": c["subject"], "attribute": c["attribute"], "reason": "超过上限"}
               for c in cands[limit:]]
    return kept, skipped
```

```python
# src/ligaotai/book.py，DEFAULT_SETTINGS 里追加
    "contradictions_batch_tokens": 30000,  # 矛盾扫描一批的输入上限（按 1 字符 1 token 估）
    "contradictions_max_groups": 2000,     # 候选组超过这个数就按权重截断，其余记进 skipped
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_contradictions.py tests/test_book.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/contradictions.py src/ligaotai/book.py tests/test_contradictions.py tests/test_book.py
git commit -m "feat: 矛盾候选上限保护与两个配置项

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 12: 支线档案的输入准备与开放伏笔

**Files:**
- Create: `src/ligaotai/archive_input.py`
- Test: `tests/test_archive_input.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_archive_input.py
from ligaotai.archive_input import open_hooks, thread_input, world_input


def test_开放伏笔是埋了没回收的():
    cards = {
        "S-0001": {"hooks_planted": ["令牌来历不明", "老人的身份"], "hooks_resolved": []},
        "S-0002": {"hooks_planted": [], "hooks_resolved": ["老人的身份"]},
    }
    got = open_hooks(["S-0001", "S-0002"], cards, all_resolved={"老人的身份"})
    assert got == [{"hook": "令牌来历不明", "scene": "S-0001"}]


def test_开放伏笔按语义相近去重():
    cards = {"S-0001": {"hooks_planted": ["令牌的来历不明"], "hooks_resolved": []}}
    got = open_hooks(["S-0001"], cards, all_resolved={"令牌来历不明"})
    assert got == [], "去掉标点和虚词后一样的算回收了"


def test_线的输入带顺序摘要人物地点时间():
    cards = {"S-0002": {"summary": "林清救人", "characters": [{"name": "林清", "role": "主要"}],
                        "locations": ["青州"], "hooks_planted": [], "hooks_resolved": []},
             "S-0001": {"summary": "赵五受伤", "characters": [], "locations": [],
                        "hooks_planted": [], "hooks_resolved": []}}
    thread = {"id": "L-001", "name": "林清线", "world": "W-01",
              "scenes": ["S-0002", "S-0001"],
              "end": {"state": "待定", "note": "写到一半", "last": "S-0001"}}
    text = thread_input(thread, cards, cmap={}, gaps=[{"event": "青州城破", "mentioned_in": ["S-0002"],
                                                      "after": "S-0001", "before": None}],
                        times={"S-0002": {"t": 1.0, "conf": "高", "thread": "L-001"}}, unit="年")
    assert text.index("S-0002") < text.index("S-0001"), "按线内顺序，不是编号顺序"
    assert "林清救人" in text and "青州" in text
    assert "青州城破" in text and "写到一半" in text
    assert "Q-" not in text, "缺口按内容认，不给 Q- 编号"


def test_世界的输入是facts不是摘要():
    from ligaotai.facts import FactRow
    rows = [FactRow("S-0001", "孙悟空", "兵器", "金箍棒", "取出金箍棒"),
            FactRow("S-0002", "孙悟空", "其他", "打妖怪", "打妖怪去了")]
    text = world_input({"id": "W-01", "name": "取经路", "reason": "有佛道"}, rows,
                       notes=[], threads=[{"id": "L-001", "name": "林清线"}])
    assert "金箍棒" in text and "S-0001" in text
    assert "打妖怪" in text, "设定集包含「其他」类 facts（spec 第 5 节）"
    assert "L-001" in text and "有佛道" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_archive_input.py -v`
Expected: FAIL，`No module named 'ligaotai.archive_input'`

- [ ] **Step 3: 写实现**

```python
# src/ligaotai/archive_input.py
"""步骤 7 每次模型调用的输入准备。

「开放的伏笔」先由程序算（这条线埋了、全书没回收的），再交模型润色成句——
先程序后模型，避免模型漏（spec 第 4 节）。
"""

from __future__ import annotations

import re

from .facts import FactRow
from .threads_input import card_line

_LOOSE = re.compile(r"[\s\W_的了着过之其此]+")


def _loose(s: str) -> str:
    """去掉标点和几个常见虚词，用来判断两句伏笔说的是不是同一件事。"""
    return _LOOSE.sub("", s or "")


def open_hooks(scenes: list[str], cards: dict[str, dict], all_resolved: set[str]) -> list[dict]:
    """这条线埋下、但全书 hooks_resolved 里没有语义相近项的伏笔。"""
    resolved = {_loose(r) for r in all_resolved}
    out, seen = [], set()
    for sid in scenes:
        for h in (cards.get(sid) or {}).get("hooks_planted") or []:
            key = _loose(h)
            if not key or key in resolved or key in seen:
                continue
            seen.add(key)
            out.append({"hook": h, "scene": sid})
    return out


def _time_bit(sid: str, times: dict[str, dict], unit: str) -> str:
    info = times.get(sid) or {}
    if info.get("t") is None:
        return ""
    conf = info.get("conf") or ""
    return f"（故事时间约 {info['t']}{unit}" + (f"，把握{conf}" if conf else "") + "）"


def thread_input(thread: dict, cards: dict[str, dict], cmap: dict, gaps: list[dict],
                 times: dict[str, dict], unit: str) -> str:
    """一条线的输入：按线内顺序的卡片行 + 断点 + 这条线的缺口 + 开放的伏笔。"""
    scenes = list(thread.get("scenes") or [])
    lines = [f"线编号：{thread.get('id','')}　线名：{thread.get('name','')}　"
             f"所属世界：{thread.get('world','')}", "", "## 按顺序的场景"]
    for sid in scenes:
        card = cards.get(sid)
        if not card:
            continue
        lines.append(card_line(sid, card, cmap) + _time_bit(sid, times, unit))

    end = thread.get("end") or {}
    lines += ["", "## 写到哪",
              f"状态：{end.get('state','待定')}　最后一块：[{end.get('last','')}]",
              f"断点说明：{end.get('note','') or '（没有）'}"]

    lines += ["", "## 缺口（提到过、但书里找不到对应场景的事件）"]
    if gaps:
        for g in gaps:
            where = "、".join(f"[{s}]" for s in (g.get("mentioned_in") or []))
            span = "".join([f"在 [{g['after']}] 之后" if g.get("after") else "",
                            f"、[{g['before']}] 之前" if g.get("before") else ""])
            lines.append(f"- {g.get('event','')}：提到于 {where}{('，位置大约' + span) if span else ''}")
    else:
        lines.append("（没有）")

    hooks = open_hooks(scenes, cards, {r for c in cards.values() for r in (c.get("hooks_resolved") or [])})
    lines += ["", "## 埋了还没回收的伏笔（程序算的，照着写就行，别自己另找）"]
    lines += [f"- {h['hook']}：埋于 [{h['scene']}]" for h in hooks] or ["（没有）"]
    return "\n".join(lines)


def world_input(world: dict, rows: list[FactRow], notes: list[dict],
                threads: list[dict]) -> str:
    """一个世界的输入：这个世界所有 facts（含「其他」类，spec 第 5 节）+ 设定笔记原文 + 有哪几条线。"""
    lines = [f"世界编号：{world.get('id','')}　世界名：{world.get('name','')}",
             f"判定依据：{world.get('reason','')}", "", "## 这个世界下的线"]
    lines += [f"- {t.get('id','')} {t.get('name','')}" for t in threads] or ["（没有）"]

    lines += ["", "## 设定（每条带出处编号）"]
    by_attr: dict[str, list[FactRow]] = {}
    for r in rows:
        by_attr.setdefault(r.attribute, []).append(r)
    for attr in sorted(by_attr):
        lines.append(f"### {attr}")
        for r in sorted(by_attr[attr], key=lambda r: (r.subject, r.scene)):
            lines.append(f"- {r.subject}：{r.value}　[{r.scene}]　原文「{r.quote}」")

    if notes:
        lines += ["", "## 这个世界下的设定笔记原文"]
        for n in notes:
            lines.append(f"[{n['id']}] {n.get('text','')}")
    return "\n".join(lines)
```

`card_line` 是 `threads_input.py` 里现成的（编号 + summary + 规范化人物 + 地点 + 世界线索 + 时间线索），签名 `card_line(sid, card, cmap)`，直接复用，别重写。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_archive_input.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/archive_input.py tests/test_archive_input.py
git commit -m "feat: 支线档案与世界设定集的输入准备

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 13: 档案的提示词与引用格式校验

**Files:**
- Create: `prompts/archive_thread.md`、`prompts/archive_world.md`
- Modify: `src/ligaotai/archive.py`
- Test: `tests/test_archive_check.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_archive_check.py
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_archive_check.py -v`
Expected: FAIL，`ImportError: cannot import name 'SCENE_REF'`

- [ ] **Step 3: 写实现**

```python
# src/ligaotai/archive.py 追加
import re

SCENE_REF = re.compile(r"\[(S-\d{4}(?:,S-\d{4})*)\]")


def refs_in(text: str) -> list[str]:
    """抓出正文里所有场景引用编号，按出现顺序。"""
    out = []
    for m in SCENE_REF.finditer(text or ""):
        out.extend(m.group(1).split(","))
    return out


def check_archive(md: str, allowed: set[str], required_headings: list[str]) -> list[str]:
    """档案的检查，返回要反馈给模型的问题（空列表 = 没问题）。"""
    problems = []
    missing = [h for h in required_headings if f"## {h}" not in (md or "")]
    if missing:
        problems.append("缺这几个小节：" + "、".join(missing))
    refs = refs_in(md)
    if not refs:
        problems.append("正文里一个场景编号都没有，每句结论都要带 [S-0003] 这样的编号")
    bad = sorted({r for r in refs if r not in allowed})
    if bad:
        problems.append("这些编号不属于这份档案的范围，不许写：" + "、".join(bad[:10]))
    return problems
```

- [ ] **Step 4: 写两个提示词**

```markdown
<!-- prompts/archive_thread.md -->
给一条支线写档案：来龙去脉、写到哪、缺口、开放的伏笔。

## system

你在帮一位作者整理一部长篇小说的乱稿。下面是一条支线按顺序排好的场景摘要，你要写一份这条线的档案。

硬规则：
1. **每一句结论都要带场景编号**，写成 [S-0003]；一句话有多个出处写 [S-0003,S-0120]。**拿不出编号的话，这句就别写**。
2. 只写我给你的材料里有的东西。不要用你对这部作品的已有知识补，不要推测。
3. 缺口和伏笔照我给你的列表写，别自己另找、别漏。缺口只写事件本身，**不要编缺口编号**。
4. 用简体中文，Markdown 输出，小节标题和顺序照下面的模板，一个都不能少。

模板：

# $tid $tname
- 所属世界：$world
- 一句话：这条线讲什么

## 来龙去脉
按顺序讲清楚，每句带编号。

## 主要人物
- 规范名：在这条线里是什么角色、做了什么 [S-0003]

## 写到哪
- 状态：完结 / 待定
- 最后一块：[S-0120]
- 断点说明：……

## 缺口
- 事件：提到于 [S-0150]，位置大约在 [S-0004] 和 [S-0120] 之间

## 开放的伏笔
- 伏笔：埋于 [S-0030]，至今没回收

只输出 JSON：{"body": "<这里放上面那份 Markdown 正文>"}

## user

$body
```

```markdown
<!-- prompts/archive_world.md -->
给一个世界写设定集：把这个世界所有场景卡的 facts 汇总成一份可查的设定资料。

## system

你在帮一位作者整理一部长篇小说的乱稿。下面是一个「世界」里所有的设定条目（每条带出处编号和原文），你要汇总成一份设定集。

硬规则：
1. **每一条都要带场景编号** [S-0003]；多个出处写 [S-0003,S-0120]。拿不出编号就别写这条。
2. 只汇总我给你的条目，不要用已有知识补，不要推测。
3. 同一个人（或地方、组织）的同一个属性，如果我给的材料里出现了**不一样的值**，你要**把几个值并列写出来**，不要替作者选一个，并在这一条的末尾固定写上「（多个说法）」五个字，一字不差。
4. 按属性分节，节标题用属性名。用简体中文，Markdown 输出。

模板：

# $wid $wname
- 判定依据：……
- 这个世界下的线：L-001 ……

## 年龄
- 林清：十六 [S-0003]

## 兵器
- 孙悟空：如意金箍棒 / 降妖宝杖（多个说法）[S-0014,S-0207]

只输出 JSON：{"body": "<这里放上面那份 Markdown 正文>"}

## user

$body
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_archive_check.py tests/test_prompts.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add prompts/archive_thread.md prompts/archive_world.md src/ligaotai/archive.py tests/test_archive_check.py
git commit -m "feat: 档案提示词与引用格式校验

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 14: C- 编号回填

**Files:**
- Modify: `src/ligaotai/archive.py`
- Test: `tests/test_archive_check.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_archive_check.py 追加
from ligaotai.archive import backfill_refs


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_archive_check.py -v -k 回填`
Expected: FAIL，`ImportError: cannot import name 'backfill_refs'`

- [ ] **Step 3: 写实现**

设定集和矛盾扫描是并行跑的，写档案时 `C-` 编号还不存在，所以提示词让模型固定写「（多个说法）」，跑完由程序回填（spec 第 5 节、3 节）。

```python
# src/ligaotai/archive.py 追加
_MULTI = "（多个说法）"


def backfill_refs(md: str, groups: list[dict]) -> str:
    """把世界设定集里的「（多个说法）」补上对应的矛盾编号。纯文本替换，不花钱。

    按「这一行的属性节 + 行首的主语」对到 (subject, attribute)；对不上的原样留着。
    """
    by_key = {(g.get("subject"), g.get("attribute")): g.get("id") for g in groups}
    attr = ""
    out = []
    for line in (md or "").splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("## "):
            attr = stripped[3:].strip()
        elif _MULTI in line and stripped.startswith("- ") and "：" in line:
            subject = stripped[2:].split("：", 1)[0].strip()
            gid = by_key.get((subject, attr))
            if gid:
                line = line.replace(_MULTI, f"（多个说法，见矛盾 {gid}）")
        out.append(line)
    return "".join(out)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_archive_check.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/archive.py tests/test_archive_check.py
git commit -m "feat: 世界设定集回填矛盾编号

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 15: 全书地图

**Files:**
- Create: `prompts/map.md`
- Modify: `src/ligaotai/archive_input.py`、`src/ligaotai/archive.py`
- Test: `tests/test_archive_input.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_archive_input.py 追加
from ligaotai.archive_input import map_input


def test_地图的输入是档案正文不是场景卡(tmp_path):
    t = tmp_path / "L-001.md"
    w = tmp_path / "W-01.md"
    t.write_text("# L-001 林清线\n他救了人 [S-0003]。\n", encoding="utf-8")
    w.write_text("# W-01 人间\n- 林清：十六 [S-0003]\n", encoding="utf-8")
    text = map_input([w], [t],
                     contradictions=[{"id": "C-007", "subject": "孙悟空", "attribute": "兵器",
                                      "status": "真矛盾", "level": "严重",
                                      "reason": "两处不一样 [S-0014]"}],
                     gaps=[{"event": "青州城破", "world": "W-01"}],
                     ends=[{"id": "L-001", "name": "林清线", "state": "待定", "last": "S-0003"}])
    assert "林清线" in text and "人间" in text
    assert "C-007" in text and "青州城破" in text
    assert "S-0003" in text


def test_地图输入只带严重矛盾():
    text = map_input([], [],
                     contradictions=[
                         {"id": "C-001", "subject": "甲", "attribute": "兵器", "status": "真矛盾",
                          "level": "轻微", "reason": "x [S-0001]"},
                         {"id": "C-002", "subject": "乙", "attribute": "外貌", "status": "真矛盾",
                          "level": "严重", "reason": "y [S-0002]"},
                         {"id": "C-003", "subject": "丙", "attribute": "年龄", "status": "合理变化",
                          "level": "", "reason": "z [S-0003]"}],
                     gaps=[], ends=[])
    assert "C-002" in text
    assert "C-001" not in text and "C-003" not in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_archive_input.py -v -k 地图`
Expected: FAIL，`ImportError: cannot import name 'map_input'`

- [ ] **Step 3: 写实现**

```python
# src/ligaotai/archive_input.py 追加
from pathlib import Path


def map_input(world_files: list[Path], thread_files: list[Path], contradictions: list[dict],
              gaps: list[dict], ends: list[dict]) -> str:
    """地图的输入是**档案正文**（不是场景卡），所以装得下（spec 7.3）。
    矛盾只带严重的——地图是给人看全局的，轻微的留在 矛盾.json 里。"""
    lines = ["# 全部世界设定集"]
    for p in sorted(world_files, key=lambda p: p.name):
        lines.append(p.read_text(encoding="utf-8"))
    lines.append("# 全部支线档案")
    for p in sorted(thread_files, key=lambda p: p.name):
        lines.append(p.read_text(encoding="utf-8"))

    lines.append("# 严重矛盾")
    bad = [c for c in contradictions if c.get("status") == "真矛盾" and c.get("level") == "严重"]
    lines += [f"- {c['id']} {c.get('subject','')}·{c.get('attribute','')}：{c.get('reason','')}"
              for c in bad] or ["（没有）"]

    lines.append("# 缺口总览")
    lines += [f"- [{g.get('world','')}] {g.get('event','')}" for g in gaps] or ["（没有）"]

    lines.append("# 各条线写到哪")
    lines += [f"- {e.get('id','')} {e.get('name','')}：{e.get('state','')}，"
              f"最后一块 [{e.get('last','')}]" for e in ends] or ["（没有）"]
    return "\n\n".join(lines)
```

- [ ] **Step 4: 写提示词**

```markdown
<!-- prompts/map.md -->
用全部档案写一份全书地图（L3），给作者一眼看清全局。

## system

你在帮一位作者整理一部长篇小说的乱稿。下面是这本书全部的世界设定集和支线档案，你要写一份「全书地图」。

硬规则：
1. **每一句结论都要带场景编号** [S-0003]；拿不出编号就别写这句。提到矛盾时写矛盾编号 C-007。
2. 只写材料里有的东西，不要用已有知识补，不要推测。
3. 用简体中文，Markdown 输出，小节顺序照模板。篇幅约两万字，别偷懒压缩成提纲。

模板：

# 全书地图

## 全书概况

## 世界：<世界名>
### 这个世界是什么样
### 这个世界下的线
（每条线一段：讲什么、走到哪、跟别的线怎么交汇）

## 严重矛盾
（照我给的清单写，带 C- 编号）

## 缺口总览

## 全书断点
（哪些线没写完）

只输出 JSON：{"body": "<这里放上面那份 Markdown 正文>"}

## user

$body
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_archive_input.py tests/test_prompts.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add prompts/map.md src/ligaotai/archive_input.py tests/test_archive_input.py
git commit -m "feat: 全书地图的输入准备与提示词

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 16: 步骤 7 编排（并行 + 回填 + 地图）

**Files:**
- Modify: `src/ligaotai/archive.py`
- Test: `tests/test_archive_run.py`

- [ ] **Step 1: 写失败的测试**

照 `tests/test_threads_run.py` 里现成的假模型写法搭一本小书（2 条线、1 个世界、若干场景卡），然后：

```python
# tests/test_archive_run.py
import asyncio

from ligaotai.archive import run_archive


def test_四件都产出(book_with_threads, fake_client):
    res = run_archive(book_with_threads, fake_client)
    b = book_with_threads
    assert (b.thread_archive_dir / "L-001.md").exists()
    assert (b.world_archive_dir / "W-01.md").exists()
    assert b.contradictions_path.exists()
    assert b.map_path.exists()
    assert res["threads"] == 2 and res["worlds"] == 1


def test_地图在三件都完成之后才跑(book_with_threads, fake_client):
    """假模型记录调用顺序：地图那次调用必须排在所有档案调用之后。"""
    run_archive(book_with_threads, fake_client)
    tags = [t for t in fake_client.calls]
    assert tags.index("archive/map") > max(
        i for i, t in enumerate(tags) if t.startswith("archive/thread") or t.startswith("archive/world"))


def test_回填在地图之前(book_with_threads, fake_client):
    """世界设定集里的「（多个说法）」在地图跑之前已经补上 C- 编号——
    地图的输入里不该再出现光秃秃的「（多个说法）」。"""
    run_archive(book_with_threads, fake_client)
    body = (book_with_threads.world_archive_dir / "W-01.md").read_text(encoding="utf-8")
    assert "（多个说法）" not in body or "见矛盾 C-" in body


def test_index记下每份档案的签名(book_with_threads, fake_client):
    from ligaotai.archive import load_index
    run_archive(book_with_threads, fake_client)
    idx = load_index(book_with_threads)
    assert idx["threads"]["L-001"]["sig"]
    assert idx["threads"]["L-001"]["outdated"] is False
    assert idx["map"]["sig"]


def test_某一件调用失败不拖垮别的(book_with_threads, failing_world_client):
    """世界设定集那次调用失败，支线档案照样产出，失败记进 summary。"""
    res = run_archive(book_with_threads, failing_world_client)
    assert (book_with_threads.thread_archive_dir / "L-001.md").exists()
    assert res["failed"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_archive_run.py -v`
Expected: FAIL，`ImportError: cannot import name 'run_archive'`

- [ ] **Step 3: 写实现**

```python
# src/ligaotai/archive.py 追加
import asyncio

from . import archive_input as ai
from . import contradictions as cd
from .entities import canonical_map
from .facts import collect_facts, group_facts, candidates
from .llm_caller import Caller, _noop
from .threads_input import name_map
from .prompts import render


def run_archive(book: Book, client, progress=_noop) -> dict:
    """步骤 7 入口。三件并行 → 程序回填 C- 编号 → 全书地图（spec 第 3 节）。"""
    return asyncio.run(_run_archive(book, client, progress))


async def _run_archive(book: Book, client, progress) -> dict:
    threads_data = read_json(book.threads_path, {}) or {}
    worlds = threads_data.get("worlds") or []
    threads = threads_data.get("threads") or []
    unit = threads_data.get("time_unit") or "年"
    cards = _load_cards(book)          # {S-xxxx: card 部分}
    hashes = _load_hashes(book)        # {S-xxxx: scene_hash}
    cmap = canonical_map(book)
    times = cd.scene_times(threads)

    caller = Caller(book, client, progress,
                    cache_path=book.archive_cache_path, tag_prefix="archive")
    caller.plan(len(threads) + len(worlds))

    index = load_index(book)
    reconcile(index, {t["id"] for t in threads}, {w["id"] for w in worlds})

    results = await asyncio.gather(
        _run_threads_archives(book, caller, threads, threads_data, cards, cmap, times, unit, hashes, index),
        _run_worlds_archives(book, caller, worlds, threads, cards, cmap, hashes, index),
        _run_contradictions(book, caller, cards, cmap, times, unit),
    )
    n_threads, n_worlds, contra = results

    # 回填：矛盾跑完才有 C- 编号，设定集是并行写的，这里补（纯文本替换，不花钱）
    for w in worlds:
        p = book.world_archive_dir / f"{w['id']}.md"
        if p.exists():
            p.write_text(backfill_refs(p.read_text(encoding="utf-8"), contra.get("groups") or []),
                         encoding="utf-8")

    await _run_map(book, caller, worlds, threads, threads_data, contra, index)

    caller.prune_cache()
    write_index(book, index)
    summary = {
        "threads": n_threads, "worlds": n_worlds,
        "contradictions": len(contra.get("groups") or []),
        "严重": sum(1 for g in contra.get("groups") or []
                    if g.get("status") == "真矛盾" and g.get("level") == "严重"),
        "skipped": len(contra.get("skipped") or []),
        "calls": caller.done, "failed": caller.failed, "unresolved": caller.unresolved,
    }
    book.set_step("archive", "done", summary=summary)
    return summary
```

读场景卡的两个小工具——**卡片正文在 `card` 子字段里**（文件形状是 `{"id","scene_hash","model","created","problems","dropped","card":{...}}`），别读错层：

```python
def _load_cards(book: Book) -> dict[str, dict]:
    out = {}
    for p in sorted(book.cards_dir.glob("S-*.json")):
        d = read_json(p, None)
        if isinstance(d, dict) and isinstance(d.get("card"), dict):
            out[p.stem] = d["card"]
    return out


def _load_hashes(book: Book) -> dict[str, str]:
    out = {}
    for p in sorted(book.cards_dir.glob("S-*.json")):
        d = read_json(p, None)
        if isinstance(d, dict):
            out[p.stem] = d.get("scene_hash", "")
    return out
```

矛盾扫描那个子协程最复杂，完整写出来：

```python
async def _run_contradictions(book: Book, caller: Caller, cards: dict[str, dict],
                              cmap: dict, times: dict[str, dict], unit: str) -> dict:
    st = book.settings()
    rows = collect_facts(cards, cmap)
    cands = candidates(group_facts(rows))
    cands, skipped = cd.cap(cands, st["contradictions_max_groups"])
    parts = cd.batches(cands, times, unit, st["contradictions_batch_tokens"])
    caller.plan(len(parts))   # 批数要先分组才知道，所以在这里才补进度分母

    judged: dict[int, dict] = {}
    start = 0
    for i, part in enumerate(parts):
        text, numbered = cd.render_values(part, start, times, unit)
        ids = set(numbered)
        got = await caller.call(
            "contradictions",
            {"unit": unit, "groups": text},
            check=lambda d, ids=ids: cd.check_output(d, ids),
            clean=lambda d, ids=ids: cd.clean_output(d, ids),
            tag=f"contradictions/{i}",
        )
        if got:  # 调用失败返回 None，这一批留在 caller.failed 里，build_result 会兜底
            # judged 的键是 cands 的下标。numbered 跟 part 同序，按位置对回去最稳，
            # 别去解析 "C-007" 里的数字再换算——批起点一变就错。
            for k, cid in enumerate(numbered):
                if cid in got:
                    judged[start + k] = got[cid]
        start += len(part)

    stats = {
        "facts": len(rows),
        "grouped": len(group_facts(rows)),
        "dropped_other": sum(1 for r in rows if r.attribute == "其他"),
        "candidates": len(cands),
        "merged_by_program": sum(c.get("merged", 0) for c in cands),
        "sent": sum(len(p) for p in parts),
    }
    old = read_json(book.contradictions_path, {"next_id": 1, "groups": []}) or {}
    result = cd.build_result(cands, judged, times, old, stats, skipped)
    for key in ("真矛盾", "合理变化", "无法判断"):
        result["stats"][key] = sum(1 for g in result["groups"] if g["status"] == key)
    write_json(book.contradictions_path, result)
    return result
```

另外三个子协程同样的骨架（`check=` 传校验、`clean=` 不传、失败返回 `None` 就跳过这一份并留在 `caller.failed` 里）：

- `_run_threads_archives`：逐条线算 `thread_sig(thread, hashes, 这条线的 gaps)`。跟 `index["threads"][tid]["sig"]` 一样、文件还在、且 `index["threads"][tid].get("outdated")` 不为真 → **跳过不花钱**（三个条件缺一不可，第三个是给 Task 18 的单独重跑接口用的）。否则：

```python
        got = await caller.call(
            "archive_thread",
            {"tid": t["id"], "tname": t.get("name", ""), "world": t.get("world", ""),
             "body": ai.thread_input(t, cards, cmap, gaps_of[t["id"]], times, unit)},
            check=lambda d, scope=set(t["scenes"]): check_archive(
                (d or {}).get("body", ""), scope,
                ["来龙去脉", "主要人物", "写到哪", "缺口", "开放的伏笔"]),
            clean=lambda d: (d or {}).get("body", ""),
            usable=lambda md: bool((md or "").strip()),
            tag=f"thread/{t['id']}",
        )
        if got:
            book.thread_archive_dir.mkdir(parents=True, exist_ok=True)
            (book.thread_archive_dir / f"{t['id']}.md").write_text(got, encoding="utf-8")
            index["threads"][t["id"]] = {"file": f"档案/支线/{t['id']}.md", "sig": sig,
                                         "scenes": list(t["scenes"]), "world": t.get("world", ""),
                                         "outdated": False, "generated": now_iso()}
```

  **注意**：档案和地图的正文是 Markdown，但 `caller.call` 走的是 `chat_json`，所以三个提示词（`archive_thread` / `archive_world` / `map`）的 system 段末尾都写了 `只输出 JSON：{"body": "<这里放 Markdown 正文>"}`（Task 13、15 里已经写进去了）。因此 `check` 拿到的是 dict，要先取 `body` 再核；`clean` 负责把 `body` 取出来，`caller.call` 返回的就是 Markdown 字符串。

- `_run_worlds_archives`：同上，`allowed` 是这个世界下所有线的场景并集，小节名是属性名所以 `required_headings=[]`（`check_archive` 对空列表不报缺小节，仍然核引用）。签名用 `world_sig(w, 该世界的场景, hashes, cmap_sig)`，`cmap_sig` 取 `_digest(sorted(cmap.items()))`。
- `_run_map`：`map_sig(全部档案文件)` 跟 `index["map"]["sig"]` 比对，一样且文件还在、没被标过期就跳过；否则 `caller.call("map", {"body": ai.map_input(...)}, check=lambda d: check_archive((d or {}).get("body",""), 全书场景编号集合, ["全书概况"]), clean=lambda d: (d or {}).get("body",""), usable=lambda md: bool((md or "").strip()), tag="map")` → 写 `全书地图.md` → 更新 `index["map"]`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_archive_run.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/archive.py tests/test_archive_run.py
git commit -m "feat: 步骤 7 编排（三件并行、回填、地图）

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 17: 过期规则与跑的途中上游变了

**Files:**
- Modify: `src/ligaotai/archive.py`
- Test: `tests/test_archive_run.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_archive_run.py 追加
def test_只有受影响的线重跑(book_with_threads, fake_client):
    """改一条线的成员，只有那条线的档案重跑，别的线不花钱。"""
    from ligaotai.archive import run_archive
    from ligaotai.fsutil import read_json, write_json
    run_archive(book_with_threads, fake_client)
    before = fake_client.calls.count("archive/thread/L-002")

    data = read_json(book_with_threads.threads_path, {})
    data["threads"][0]["scenes"].append("S-0009")   # 只动 L-001
    write_json(book_with_threads.threads_path, data)

    fake_client.calls.clear()
    run_archive(book_with_threads, fake_client)
    assert "archive/thread/L-001" in fake_client.calls
    assert fake_client.calls.count("archive/thread/L-002") == 0, "没动的线不该重跑"


def test_任何档案重跑地图就重跑(book_with_threads, fake_client):
    from ligaotai.archive import run_archive
    from ligaotai.fsutil import read_json, write_json
    run_archive(book_with_threads, fake_client)
    data = read_json(book_with_threads.threads_path, {})
    data["threads"][0]["scenes"].append("S-0009")
    write_json(book_with_threads.threads_path, data)
    fake_client.calls.clear()
    run_archive(book_with_threads, fake_client)
    assert "archive/map" in fake_client.calls


def test_什么都没变就一次都不调(book_with_threads, fake_client):
    from ligaotai.archive import run_archive
    run_archive(book_with_threads, fake_client)
    fake_client.calls.clear()
    run_archive(book_with_threads, fake_client)
    assert fake_client.calls == []


def test_跑的途中上游变了记outdated(book_with_threads, mutating_client):
    """假模型在第一次调用之后偷偷改 世界与支线.json，这一步要记 outdated 不记 done。"""
    from ligaotai.archive import run_archive
    run_archive(book_with_threads, mutating_client)
    assert book_with_threads.step("archive")["status"] == "outdated"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_archive_run.py -v -k "只有受影响 or 地图就重跑 or 什么都没变 or 途中"`
Expected: FAIL

- [ ] **Step 3: 写实现**

沿用 ②b 第 5 节的做法：

```python
# src/ligaotai/archive.py 追加
from .threads_input import fingerprint as _threads_fingerprint


def input_fingerprint(book: Book) -> str:
    """开跑和跑完各算一次；不一致说明上游在跑的途中变了，这一步记 outdated 不记 done。"""
    data = read_json(book.threads_path, {}) or {}
    return _digest(
        _threads_fingerprint_safe(book),
        [(t.get("id"), list(t.get("scenes") or []), t.get("name"), t.get("offset"))
         for t in data.get("threads") or []],
        [(w.get("id"), w.get("name")) for w in data.get("worlds") or []],
        [g.get("event") for g in data.get("gaps") or []],
    )
```

`_threads_fingerprint_safe` 包一层 `threads_input.fingerprint`（它要的是 `items` 和 `unassigned`，按 `threads_input.prepare(book)` 的产物取；prepare 失败就返回空串）。

在 `_run_archive` 开头存 `fp0 = input_fingerprint(book)`，结尾比 `fp1`：

```python
    status = "done" if input_fingerprint(book) == fp0 else "outdated"
    book.set_step("archive", status, summary=summary)
```

过期判断已经在 Task 16 的各个子协程里做了（`sig` 一样就跳过）；这里补两条：
- 地图的 `sig` 用 `map_sig(全部档案文件)` 算，任何一份档案重写了内容就变 → 自动重跑；
- `矛盾.json` 用 `facts` 和规范名映射的哈希判：一样就整体跳过（它本来就是全书一把算的）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_archive_run.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/archive.py tests/test_archive_run.py
git commit -m "feat: 步骤 7 的过期规则与途中变更检测

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 18: 接进 API

**Files:**
- Modify: `src/ligaotai/api.py:33,35,160`
- Test: `tests/test_api_archive.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_api_archive.py
def test_archive在可跑的步骤里(client_with_book):
    from ligaotai.api import RUNNABLE
    assert "archive" in RUNNABLE


def test_读档案列表(client_with_book):
    r = client_with_book.get("/api/books/测试书/archive")
    assert r.status_code == 200
    assert set(r.json()) >= {"threads", "worlds", "map"}


def test_读矛盾(client_with_book):
    r = client_with_book.get("/api/books/测试书/contradictions")
    assert r.status_code == 200
    assert "groups" in r.json()


def test_读一份档案的正文(client_with_book_run):
    r = client_with_book_run.get("/api/books/测试书/archive/thread/L-001")
    assert r.status_code == 200
    assert "来龙去脉" in r.json()["body"]


def test_读不存在的档案给404(client_with_book):
    assert client_with_book.get("/api/books/测试书/archive/thread/L-999").status_code == 404


def test_单独重跑接口(client_with_book_run):
    r = client_with_book_run.post("/api/books/测试书/archive/rerun",
                                  json={"threads": ["L-001"], "worlds": [], "map": True})
    assert r.status_code == 200


def test_重跑不存在的线给400(client_with_book_run):
    r = client_with_book_run.post("/api/books/测试书/archive/rerun",
                                  json={"threads": ["L-999"], "worlds": [], "map": False})
    assert r.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_api_archive.py -v`
Expected: FAIL，404 / `RUNNABLE` 里没有 `archive`

- [ ] **Step 3: 写实现**

```python
# src/ligaotai/api.py
from .archive import load_index, run_archive, write_index   # 第 33 行附近

RUNNABLE = ("split", "dedup", "cards", "entities", "threads", "archive")   # 第 35 行

        # 第 160 行附近，紧接 threads 那个分支
        if step == "archive":
            return lambda p: run_archive(book, client, p)
```

四个新接口（照 `threads` 那几个的写法，同样用 `ensure_within` 防路径穿越）：

```python
    @app.get("/api/books/{name}/archive")
    def archive_index(name: str) -> dict:
        b = _book(name)
        return load_index(b)

    @app.get("/api/books/{name}/contradictions")
    def contradictions(name: str) -> dict:
        b = _book(name)
        return read_json(b.contradictions_path, {"groups": [], "stats": {}})

    @app.get("/api/books/{name}/archive/{kind}/{oid}")
    def archive_body(name: str, kind: str, oid: str) -> dict:
        b = _book(name)
        if kind not in ("thread", "world"):
            raise HTTPException(400, "kind 只能是 thread 或 world")
        base = b.thread_archive_dir if kind == "thread" else b.world_archive_dir
        path = ensure_within(base, f"{safe_name(oid)}.md")
        if not path.exists():
            raise HTTPException(404, "没有这份档案")
        return {"id": oid, "body": path.read_text(encoding="utf-8")}

    @app.post("/api/books/{name}/archive/rerun")
    def archive_rerun(name: str, req: RerunReq) -> dict:
        """把指定的档案标过期，下次跑步骤 7 只重跑它们。"""
        b = _book(name)
        data = read_json(b.threads_path, {}) or {}
        tids = {t["id"] for t in data.get("threads") or []}
        wids = {w["id"] for w in data.get("worlds") or []}
        bad = [x for x in req.threads if x not in tids] + [x for x in req.worlds if x not in wids]
        if bad:
            raise HTTPException(400, "没有这些编号：" + "、".join(bad))
        index = load_index(b)
        for tid in req.threads:
            index["threads"].setdefault(tid, {})["outdated"] = True
        for wid in req.worlds:
            index["worlds"].setdefault(wid, {})["outdated"] = True
        if req.map:
            index["map"]["outdated"] = True
        write_index(b, index)
        return {"ok": True}
```

```python
# api.py 里跟别的请求体模型放一起
class RerunReq(BaseModel):
    threads: list[str] = []
    worlds: list[str] = []
    map: bool = False
```

**注意**：Task 16/17 里子协程判「要不要跳过」时，除了比 `sig`，还要看 `index[...]["outdated"]` 是不是 `True`——被这个接口标过期的，即使 `sig` 没变也要重跑。

**注意（I2，9-20 定）**：换模型 / 改模型配置**不进 `input_sig`**（换一次模型 = 全部档案重付一次钱，
不值）。`archive.py` 已经在每份档案 / `矛盾.json` / 全书地图落盘时把生成它用的模型名记进
`index[...]["model"]`（跟 `cache_config(client, "synth")` 取同一个来源）。`archive_index` /
`archive_body` 这几个接口接进来时，要把这个字段吐给界面——界面对比 index 里的 `model` 和当前
`config.json` 里配的 `synth.model`，不一样就提示作者「这份档案是用 X 模型生成的，当前配置是 Y，
要不要重跑」。见 `docs/已知问题与待办.md`「已知问题」一节同一条。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_api_archive.py tests/test_api.py tests/test_api_threads.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/api.py tests/test_api_archive.py
git commit -m "feat: 步骤 7 接进 API（读档案、读矛盾、单独重跑）

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 19: scramble 植入人造矛盾

**Files:**
- Modify: `tools/scramble.py`
- Test: `tests/test_scramble.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_scramble.py 追加
from tools.scramble import Chapter, plant_contradictions


def test_植入的是原文里真出现的词():
    chapters = [Chapter(1, "第一回", "行者取出金箍棒，年方十六，左臂有伤。"),
                Chapter(2, "第二回", "行者又取金箍棒来，仍是十六岁。")]
    import random
    planted = plant_contradictions(chapters, random.Random(1), n=1)
    assert len(planted) == 1
    p = planted[0]
    assert p["new"] != p["old"]
    assert p["attribute"] in ("年龄", "兵器", "外貌")
    body = next(c.body for c in chapters if c.num == p["chapter"])
    assert p["new"] in body, "改完要真的写回正文"
    assert p["old"] not in body or body.count(p["old"]) < 2


def test_一个章节最多植入一处():
    chapters = [Chapter(1, "第一回", "行者取出金箍棒，年方十六，左臂有伤，穿红衣。")]
    import random
    planted = plant_contradictions(chapters, random.Random(1), n=5)
    assert len({p["chapter"] for p in planted}) == len(planted)


def test_没有锚点时不硬植入():
    chapters = [Chapter(1, "第一回", "天气很好。")]
    import random
    assert plant_contradictions(chapters, random.Random(1), n=3) == []


def test_答案文件带植入记录(tmp_path):
    from tools.scramble import main
    src = tmp_path / "book.txt"
    src.write_text("第一回 起头\n行者取出金箍棒，年方十六。\n" * 3 +
                   "第二回 再来\n行者又见金箍棒，左臂有伤。\n" * 3 +
                   "第三回 收尾\n行者归来，年方十六。\n" * 3, encoding="utf-8")
    out = tmp_path / "乱稿"
    main(["--src", str(src), "--out", str(out), "--contradictions", "1",
          "--n-delete", "0", "--n-truncate", "0", "--n-full", "0", "--n-excerpt", "0"])
    import json
    key = json.loads((tmp_path / "乱稿-答案.json").read_text(encoding="utf-8"))
    assert len(key["contradictions"]) == 1
    assert set(key["contradictions"][0]) >= {"chapter", "subject", "attribute", "old", "new"}


def test_不给contradictions参数时行为不变(tmp_path):
    """②b 的乱稿重跑不能受影响。"""
    from tools.scramble import main
    src = tmp_path / "book.txt"
    src.write_text("第一回 起头\n甲乙丙。\n" * 5 + "第二回 再来\n丁戊己。\n" * 5 +
                   "第三回 收尾\n庚辛壬。\n" * 5, encoding="utf-8")
    out = tmp_path / "乱稿"
    main(["--src", str(src), "--out", str(out), "--n-delete", "0", "--n-truncate", "0",
          "--n-full", "0", "--n-excerpt", "0"])
    import json
    key = json.loads((tmp_path / "乱稿-答案.json").read_text(encoding="utf-8"))
    assert key["contradictions"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_scramble.py -v -k 植入`
Expected: FAIL，`ImportError: cannot import name 'plant_contradictions'`

- [ ] **Step 3: 写实现**

```python
# tools/scramble.py 追加
# 锚点：正则 → (属性, 换成什么)。换的值必须跟原值同类但不同，好让矛盾扫描能认出来。
_ANCHORS: list[tuple[str, str, dict[str, str]]] = [
    ("年龄", r"年方([一二三四五六七八九十]+)", {"十六": "二十", "二十": "十六",
                                              "十八": "二十四", "十五": "十九"}),
    ("年龄", r"([一二三四五六七八九十]+)岁", {"十六": "二十", "二十": "十六",
                                            "十八": "二十四", "十五": "十九"}),
    ("兵器", r"(金箍棒|九齿钉耙|降妖宝杖|青锋剑|方天画戟)",
     {"金箍棒": "降妖宝杖", "降妖宝杖": "金箍棒", "九齿钉耙": "青锋剑",
      "青锋剑": "九齿钉耙", "方天画戟": "青锋剑"}),
    ("外貌", r"(左臂|右臂|左脸|右脸|左手|右手)",
     {"左臂": "右臂", "右臂": "左臂", "左脸": "右脸", "右脸": "左脸",
      "左手": "右手", "右手": "左手"}),
    ("外貌", r"(红衣|白衣|青衣|皂衣)",
     {"红衣": "青衣", "青衣": "红衣", "白衣": "皂衣", "皂衣": "白衣"}),
]


def plant_contradictions(chapters: list[Chapter], rng: random.Random, n: int) -> list[dict]:
    """在章节正文里植入 n 处人造矛盾，一个章节最多一处，就地改 chapters 的 body。

    只改**原文里真出现的词**，换成同类但不同的值，答案记 (章节, 属性, 原值, 新值)。
    找不到锚点就少植入几处，不硬来（spec 9.1）。
    """
    spots = []
    for c in chapters:
        for attribute, pattern, table in _ANCHORS:
            for m in re.finditer(pattern, c.body):
                old = m.group(1)
                new = table.get(old)
                if new and new not in c.body:
                    spots.append({"chapter": c.num, "attribute": attribute,
                                  "old": old, "new": new, "pos": m.start(1)})
    rng.shuffle(spots)
    by_chapter: dict[int, dict] = {}
    for s in spots:
        by_chapter.setdefault(s["chapter"], s)
        if len(by_chapter) >= n:
            break
    planted = []
    for c in chapters:
        s = by_chapter.get(c.num)
        if not s:
            continue
        c.body = c.body[:s["pos"]] + s["new"] + c.body[s["pos"] + len(s["old"]):]
        planted.append({"chapter": c.num, "subject": "", "attribute": s["attribute"],
                        "old": s["old"], "new": s["new"]})
    return sorted(planted, key=lambda p: p["chapter"])
```

`Chapter` 现在是 `@dataclass`（第 41 行），要能改 `body`——如果它是 `frozen=True`，去掉 frozen；不是就直接改。

`scramble()` 加参数 `n_contradictions: int = 0`，**在截断和别名替换之前**调 `plant_contradictions`（不然可能改到会被截掉的那半），返回的 key 加 `"contradictions": planted`。`main()` 加 `--contradictions`（默认 0）以及 `--n-delete` / `--n-truncate` / `--n-full` / `--n-excerpt`（默认值跟 `scramble()` 现在的默认值一样，加这几个只为测试能关掉别的弄乱方式）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_scramble.py tests/test_tools_scripts.py -q`
Expected: PASS（含原有的 scramble 用例，一个都不能挂）

- [ ] **Step 5: Commit**

```bash
git add tools/scramble.py tests/test_scramble.py
git commit -m "feat: scramble 支持植入人造矛盾

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 20: 引用核对（编造率、无引用句率）

**Files:**
- Create: `tools/eval_archives.py`
- Test: `tests/test_eval_archives.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_eval_archives.py
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_eval_archives.py -v`
Expected: FAIL，`No module named 'tools.eval_archives'`

- [ ] **Step 3: 写实现**

```python
# tools/eval_archives.py
"""计划②c 的验收：引用核对（编造率、无引用句率）、植入矛盾召回率、人工抽查抽样。

用法：
  uv run python tools/eval_archives.py --book <书库>/<书名> --key data/乱稿-xxx-答案.json
  uv run python tools/eval_archives.py --book ... --sample 10 --out 抽查.md
门槛（spec 第 9 节）：编造率 ≤ 2%，无引用句率 ≤ 10%，植入矛盾召回 ≥ 8/10。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ligaotai.archive import refs_in  # noqa: E402
from ligaotai.book import Book  # noqa: E402

_SENT = re.compile(r"[^。！？\n]+[。！？]?")
FABRICATED_LIMIT = 0.02
NO_REF_LIMIT = 0.10


def sentences(text: str) -> list[str]:
    """按句切，跳过标题行和空行——标题不是结论句，不该算进无引用句率。"""
    out = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        for m in _SENT.finditer(s):
            piece = m.group(0).strip()
            if piece:
                out.append(piece)
    return out


def check_refs(bodies: dict[str, str], allowed: dict[str, set[str]],
               existing: set[str]) -> dict:
    """逐条核每个引用：编号存在、且属于这份档案的范围（spec 9.2）。"""
    total = bad = n_sent = no_ref = 0
    details = []
    for oid, body in sorted(bodies.items()):
        scope = allowed.get(oid, set())
        for s in sentences(body):
            n_sent += 1
            refs = refs_in(s)
            if not refs:
                no_ref += 1
            for r in refs:
                total += 1
                why = ""
                if r not in existing:
                    why = "编号不存在"
                elif scope and r not in scope:
                    why = "不属于这份档案"
                if why:
                    bad += 1
                    details.append({"archive": oid, "ref": r, "why": why, "sentence": s[:60]})
    return {
        "total": total, "bad": bad,
        "fabricated_rate": round(bad / total, 4) if total else 0.0,
        "sentences": n_sent, "no_ref": no_ref,
        "no_ref_rate": round(no_ref / n_sent, 4) if n_sent else 0.0,
        "details": details[:50],
    }
```

`main()` 读 `book.archive_index_path` 拿到各份档案的路径与范围（线的范围 = `世界与支线.json` 里那条线的 `scenes`；世界的范围 = 这个世界下所有线的场景并集；地图的范围 = 全书场景），跑 `check_refs`，把结果写成 JSON（`--report`）并 print 一行汇总，**超门槛就 `sys.exit(1)`**。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_eval_archives.py tests/test_tools_scripts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/eval_archives.py tests/test_eval_archives.py
git commit -m "feat: 档案引用核对（编造率与无引用句率）

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 21: 植入矛盾的召回率

**Files:**
- Modify: `tools/eval_archives.py`
- Test: `tests/test_eval_archives.py`

- [ ] **Step 1: 写失败的测试**

答案文件记的是**章节号**（`S-xxxx` 是导入后才分配的），所以要先把章节映射到场景编号——跟 `tools/eval_threads.py` 的 `truth_positions` 一个套路：用 `key["files"]` 里每个文件的 `chapter` 和 `path`，再用书的导入清单反查这个文件切出了哪些场景。

```python
# tests/test_eval_archives.py 追加
from tools.eval_archives import recall


def test_命中判据是场景编号加属性():
    key = {"contradictions": [{"chapter": 3, "attribute": "兵器", "old": "金箍棒", "new": "降妖宝杖"}]}
    chapter_scenes = {3: {"S-0005", "S-0006"}}
    result = {"groups": [{"id": "C-001", "subject": "孙悟空", "attribute": "兵器",
                          "status": "真矛盾", "level": "严重",
                          "values": [{"value": "金箍棒", "scenes": [{"id": "S-0005"}]},
                                     {"value": "降妖宝杖", "scenes": [{"id": "S-0099"}]}]}]}
    res = recall(key, chapter_scenes, result)
    assert res["hit"] == 1 and res["planted"] == 1
    assert res["recall"] == 1.0


def test_属性对不上不算命中():
    key = {"contradictions": [{"chapter": 3, "attribute": "兵器", "old": "金箍棒", "new": "降妖宝杖"}]}
    result = {"groups": [{"id": "C-001", "subject": "孙悟空", "attribute": "外貌",
                          "status": "真矛盾", "level": "严重",
                          "values": [{"value": "x", "scenes": [{"id": "S-0005"}]}]}]}
    assert recall(key, {3: {"S-0005"}}, result)["hit"] == 0


def test_无法判断也算命中():
    """作者定了宁可多报，「无法判断」跟「真矛盾」一起显示，所以一起算召回。"""
    key = {"contradictions": [{"chapter": 3, "attribute": "兵器", "old": "a", "new": "b"}]}
    result = {"groups": [{"id": "C-001", "subject": "x", "attribute": "兵器",
                          "status": "无法判断", "level": "",
                          "values": [{"value": "a", "scenes": [{"id": "S-0005"}]}]}]}
    assert recall(key, {3: {"S-0005"}}, result)["hit"] == 1


def test_合理变化不算命中():
    key = {"contradictions": [{"chapter": 3, "attribute": "兵器", "old": "a", "new": "b"}]}
    result = {"groups": [{"id": "C-001", "subject": "x", "attribute": "兵器",
                          "status": "合理变化", "level": "",
                          "values": [{"value": "a", "scenes": [{"id": "S-0005"}]}]}]}
    assert recall(key, {3: {"S-0005"}}, result)["hit"] == 0


def test_误报只报数():
    key = {"contradictions": [{"chapter": 3, "attribute": "兵器", "old": "a", "new": "b"}]}
    result = {"groups": [
        {"id": "C-001", "subject": "x", "attribute": "兵器", "status": "真矛盾", "level": "严重",
         "values": [{"value": "a", "scenes": [{"id": "S-0005"}]}]},
        {"id": "C-002", "subject": "y", "attribute": "外貌", "status": "真矛盾", "level": "中等",
         "values": [{"value": "c", "scenes": [{"id": "S-0100"}]}]}]}
    res = recall(key, {3: {"S-0005"}}, result)
    assert res["hit"] == 1 and res["false_positives"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_eval_archives.py -v -k "命中 or 误报 or 无法判断 or 合理变化"`
Expected: FAIL，`ImportError: cannot import name 'recall'`

- [ ] **Step 3: 写实现**

```python
# tools/eval_archives.py 追加
RECALL_FLOOR = 0.8
_HIT_STATUS = ("真矛盾", "无法判断")  # 宁可多报：这两种在界面上一起显示，一起算召回


def recall(key: dict, chapter_scenes: dict[int, set[str]], result: dict) -> dict:
    """植入矛盾的召回（spec 9.1）：植入点所在章节的场景编号，出现在某个
    status ∈ {真矛盾, 无法判断} 的组里，且该组属性等于植入的属性，就算召回。"""
    groups = [g for g in (result.get("groups") or []) if g.get("status") in _HIT_STATUS]
    planted = key.get("contradictions") or []
    hit, misses = 0, []
    matched_ids = set()
    for p in planted:
        scenes = chapter_scenes.get(p["chapter"], set())
        found = None
        for g in groups:
            if g.get("attribute") != p["attribute"]:
                continue
            ids = {s["id"] for v in g.get("values") or [] for s in v.get("scenes") or []}
            if ids & scenes:
                found = g["id"]
                break
        if found:
            hit += 1
            matched_ids.add(found)
        else:
            misses.append(p)
    return {
        "planted": len(planted), "hit": hit,
        "recall": round(hit / len(planted), 4) if planted else 0.0,
        "misses": misses,
        # 误报只报数不设门槛——作者定了宁可多报，留着人工翻
        "false_positives": sum(1 for g in groups if g.get("status") == "真矛盾"
                               and g["id"] not in matched_ids),
    }


def chapter_to_scenes(book: Book, key: dict, folder_name: str) -> dict[int, set[str]]:
    """章节号 → 场景编号集合。答案文件记的是章节，S- 编号是导入时才分配的，
    所以要通过 key["files"] 的 path 和书的导入清单反查。

    直接复用 eval_threads.truth_positions——它返回 {场景编号: (章节, 段序, 段数)}，
    这边只要反过来聚合。别另起炉灶，两处读法不一致就会对不上。
    """
    from eval_threads import truth_positions   # tools/ 已在 sys.path 里

    out: dict[int, set[str]] = {}
    for sid, pos in truth_positions(book, key, folder_name).items():
        out.setdefault(pos[0], set()).add(sid)
    return out
```

`truth_positions` 在 `tools/eval_threads.py:72`，签名是 `truth_positions(book, key, folder_name)`——写实现时先读一遍确认返回值的元组次序（第一项是不是章节号），不是就按实际的取。`tools/` 目录要先进 `sys.path`：文件顶部已经加了仓库根的 `src`，再补一行 `sys.path.insert(0, str(Path(__file__).resolve().parent))`。

`main()` 里加 `--key`：给了就跑 `recall`，结果并进报告；召回低于 `RECALL_FLOOR` 就 `sys.exit(1)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_eval_archives.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/eval_archives.py tests/test_eval_archives.py
git commit -m "feat: 植入矛盾的召回率评估

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 22: 人工抽查抽样与费用估算

**Files:**
- Modify: `tools/eval_archives.py`
- Test: `tests/test_eval_archives.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_eval_archives.py 追加
from tools.eval_archives import sample_for_review


def test_抽查材料是结论句配原文():
    bodies = {"L-001": "他救了人 [S-0003]。后来去了青州 [S-0004]。"}
    scenes = {"S-0003": "林清救下受伤的赵五。", "S-0004": "林清一路行至青州。"}
    import random
    md = sample_for_review(bodies, scenes, random.Random(1), n=2)
    assert "他救了人" in md and "林清救下受伤的赵五" in md
    assert "S-0003" in md


def test_抽查只抽带编号的句子():
    bodies = {"L-001": "天气很好。他救了人 [S-0003]。"}
    scenes = {"S-0003": "林清救下受伤的赵五。"}
    import random
    md = sample_for_review(bodies, scenes, random.Random(1), n=5)
    assert "天气很好" not in md


def test_抽不满n条就有几条给几条():
    bodies = {"L-001": "他救了人 [S-0003]。"}
    import random
    md = sample_for_review(bodies, {"S-0003": "原文"}, random.Random(1), n=10)
    assert md.count("## 第") == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_eval_archives.py -v -k 抽查`
Expected: FAIL，`ImportError: cannot import name 'sample_for_review'`

- [ ] **Step 3: 写实现**

```python
# tools/eval_archives.py 追加
import random as _random


def sample_for_review(bodies: dict[str, str], scenes: dict[str, str],
                      rng: _random.Random, n: int) -> str:
    """随机抽 n 条带编号的结论句，配上它引用的场景原文，写成对照材料给作者人工判（spec 9.3）。"""
    pool = []
    for oid, body in sorted(bodies.items()):
        for s in sentences(body):
            refs = refs_in(s)
            if refs:
                pool.append((oid, s, refs))
    rng.shuffle(pool)
    picked = pool[:n]
    out = ["# 档案人工抽查", "", f"共 {len(picked)} 条。逐条判：这句结论，它引用的原文撑得住吗？", ""]
    for i, (oid, s, refs) in enumerate(picked, 1):
        out += [f"## 第 {i} 条（来自 {oid}）", "", f"**档案里写的**：{s}", "", "**引用的原文**："]
        for r in refs:
            text = scenes.get(r, "（找不到这个场景）")
            out.append(f"- [{r}] {text[:300]}")
        out += ["", "判断：□ 撑得住　□ 撑不住　□ 不好说", "", "---", ""]
    return "\n".join(out)
```

`main()` 加 `--sample N --out <文件>`：读书里各份档案和 `场景/*.md` 正文，抽样写文件。

再加 `--estimate`（不花钱，只估价，同 `eval_threads.py` 的 `estimate`）：按「支线档案 = 线数 × 每线输入字符数」「世界设定集 = 世界数 × 该世界 facts 字符数」「矛盾 = 批数 × 批输入字符数」「地图 = 全部档案字符数」估输入 token，**输出按输入的 1.0 倍算**（②b 的教训：这类步骤输出可能比输入还多，按 0.5 倍估会偏低），乘 `config.json` 里的单价。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_eval_archives.py tests/test_tools_scripts.py -q`
Expected: PASS

- [ ] **Step 5: 手跑一遍脚本确认能直接执行**

Run: `uv run python tools/eval_archives.py --help`
Expected: 打出帮助，退出码 0

- [ ] **Step 6: Commit**

```bash
git add tools/eval_archives.py tests/test_eval_archives.py
git commit -m "feat: 人工抽查抽样与费用估算

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 23: 全链路集成测试（假模型）

**Files:**
- Create: `tests/test_archive_integration.py`

- [ ] **Step 1: 写测试**

```python
# tests/test_archive_integration.py
"""假模型跑通步骤 4→7 的全链路，验证并行调度、缓存命中、暂停取消、单独重跑。"""


def test_从场景卡跑到地图(book_with_threads, fake_client):
    """跑完步骤 7，四件产出都在，且引用核对一条都不该不合格。"""
    from ligaotai.archive import run_archive
    from tools.eval_archives import check_refs

    b = book_with_threads
    run_archive(b, fake_client)

    bodies = {p.stem: p.read_text(encoding="utf-8")
              for p in b.thread_archive_dir.glob("*.md")}
    data = read_json(b.threads_path, {})
    allowed = {t["id"]: set(t["scenes"]) for t in data["threads"]}
    existing = {p.stem for p in b.scenes_dir.glob("S-*.md")}

    res = check_refs(bodies, allowed, existing)
    assert res["bad"] == 0, res["details"]
    assert res["no_ref_rate"] <= 0.10


def test_缓存命中第二次不花钱(library, fake_client):
    run_archive(book, fake_client)
    n = len(fake_client.calls)
    fake_client.calls.clear()
    # 删掉产物但保留缓存，重跑应该全部命中缓存、一次模型都不调
    book.map_path.unlink()
    run_archive(book, fake_client)
    assert fake_client.model_calls == 0, "缓存该挡住"
    assert book.map_path.exists()


def test_暂停能取消(library, cancelling_client):
    from ligaotai.jobs import JobCancelled
    import pytest
    with pytest.raises(JobCancelled):
        run_archive(book, cancelling_client)


def test_欠费直接让整步失败(library, fatal_client):
    from ligaotai.llm import FatalLLMError
    import pytest
    with pytest.raises(FatalLLMError):
        run_archive(book, fatal_client)


def test_单独重跑一条线不动别的(library, fake_client):
    run_archive(book, fake_client)
    before = (book.thread_archive_dir / "L-002.md").read_text(encoding="utf-8")
    index = load_index(book)
    index["threads"]["L-001"]["outdated"] = True
    write_index(book, index)
    fake_client.calls.clear()
    run_archive(book, fake_client)
    assert "archive/thread/L-001" in fake_client.calls
    assert "archive/thread/L-002" not in fake_client.calls
    assert (book.thread_archive_dir / "L-002.md").read_text(encoding="utf-8") == before
```

**先在 `tests/conftest.py` 加这两个 fixture**（Task 16 起的所有测试都用它们）：

- `book_with_threads`：照 `tests/test_threads_run.py` 现成的搭书写法，造一本小书——6 个场景（`场景/S-0001.md`…`S-0006.md` 有正文）、6 张场景卡（`card` 子字段里有 `summary` / `characters` / `facts` / `hooks_planted` / `hooks_resolved`，其中至少有两张卡对同一个 (主语, 属性) 给了不同的值，好让矛盾扫描有候选）、`实体.json`（含一组别名合并）、`世界与支线.json`（1 个世界 W-01、2 条线 L-001/L-002，各有 `scenes` / `times` / `offset` / `end`，另有 1 条 gap）。
- `fake_client`：假模型。记录每次调用的 `tag` 到 `self.calls`（列表），真正产生"调用"的次数记到 `self.model_calls`（缓存命中时不增加），按 `tag` 前缀返回：
  - `archive/thread/*` → `{"body": "# L-001 x\n\n## 来龙去脉\n他救了人 [S-0001]。\n\n## 主要人物\n- 甲：主角 [S-0001]\n\n## 写到哪\n状态：待定 [S-0002]\n\n## 缺口\n- 无 [S-0001]\n\n## 开放的伏笔\n- 无 [S-0001]\n"}`（编号必须是这条线真有的，否则 `check_archive` 会判不合格）；
  - `archive/world/*` → `{"body": "# W-01 人间\n\n## 兵器\n- 甲：刀 / 剑（多个说法）[S-0001,S-0002]\n"}`；
  - `archive/contradictions/*` → 解析 user 里的 `C-xxx` 编号，**每个都答**，返回 `{"groups": [{"id": cid, "status": "真矛盾", "level": "严重", "category": "人物", "reason": "对不上 [S-0001]"}, ...]}`；
  - `archive/map` → `{"body": "# 全书地图\n\n## 全书概况\n讲了个故事 [S-0001]。\n"}`。

另外两个专用假模型：`failing_world_client`（`archive/world/*` 抛 `LLMError`，其余同 `fake_client`）、`mutating_client`（第一次调用之后往 `世界与支线.json` 里加一条线，模拟跑的途中上游变了）、`cancelling_client`（第二次调用抛 `JobCancelled`）、`fatal_client`（第一次调用抛 `FatalLLMError`）。

- [ ] **Step 2: 跑测试**

Run: `uv run pytest tests/test_archive_integration.py -v`
Expected: PASS（挂了就修实现，不是改断言）

- [ ] **Step 3: 跑全量测试**

Run: `uv run pytest -q`
Expected: PASS，测试数应在 595 + 本计划新增之上，**原有 595 个一个都不能挂**

- [ ] **Step 4: Commit**

```bash
git add tests/test_archive_integration.py
git commit -m "test: 步骤 7 全链路集成测试

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 24: 重跑两本验收书的场景卡，出 facts 对照表

**Files:**
- Create: `docs/验收记录/2026-09-16-计划2c-facts改造.md`

这一步**要花钱**（估 $0.3 上下），跑之前先 `--estimate`，并跟作者确认。

- [x] **Step 1: 估价**

```bash
uv run python tools/eval_threads.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json \
  --report /tmp/est.json --estimate
```

把两本书重跑场景卡的估价报给作者，等他点头再跑。

- [x] **Step 2: 重跑两本书的场景卡**

用现有的验收书库副本（`data/验收书库/验收-实体-乱稿-西游记-s7`、`…-雪月梅-s7`），把步骤 `cards` 标过期后重跑。

- [x] **Step 3: 出对照表**

写一个一次性脚本（放 scratchpad，不进仓库）统计改造前后的：facts 条数、不同属性名数、(主语,属性) 分组数、值不一致的组数、`attrs_normalized` / `long_values_dropped` 计数。

**中文输出别信终端**：结果写文件再用 Read 看。

- [x] **Step 4: 写验收记录**

`docs/验收记录/2026-09-16-计划2c-facts改造.md`，表格对照 spec 2.1 那张表，并写明：模型对受控表的听话程度（`attrs_normalized` 占比）、候选组数是否落在「几十到几百」的预期区间（spec 6.2）、实花费用与估价的倍数。

- [x] **Step 5: Commit**

```bash
git add docs/验收记录/2026-09-16-计划2c-facts改造.md
git commit -m "docs: facts 改造前后对照（计划②c 验收）

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 25: 真模型验收与收尾

**Files:**
- Create: `docs/验收记录/2026-09-16-计划2c-档案矛盾地图.md`
- Modify: `README.md`、`docs/已知问题与待办.md`

这一步**要花钱**，跑之前先 `--estimate` 并跟作者确认。

- [x] **Step 1: 造带人造矛盾的乱稿**

```bash
uv run python tools/scramble.py --src data/xiyouji-pg23962.txt --out data/乱稿-西游记-矛盾 --contradictions 10
uv run python tools/scramble.py --src data/pg26739.txt --out data/乱稿-雪月梅-矛盾 --contradictions 10 --aliases data/别名-雪月梅.json
```

- [x] **Step 2: 估价，报给作者，等点头**

```bash
uv run python tools/eval_archives.py --book <书库>/<书名> --estimate
```

- [x] **Step 3: 两本书跑完步骤 1→7，再跑验收**

```bash
uv run python tools/eval_archives.py --book <书库>/<书名> --key data/乱稿-西游记-矛盾-答案.json --report data/验收-档案-西游记.json
uv run python tools/eval_archives.py --book <书库>/<书名> --sample 10 --out data/抽查-西游记.md
```

- [x] **Step 4: 写验收记录**

`docs/验收记录/2026-09-16-计划2c-档案矛盾地图.md`，照 ②b 那份的格式写，必须包含：

- 三个门槛的实测值：召回 ≥8/10、编造率 ≤2%、无引用句率 ≤10%（**过了写过，没过写没过，别粉饰**）；
- 误报数（只报数，不设门槛）；
- 人工抽查 10 段的结果（作者判的）；
- 估价 vs 实花，倍数；
- **真跑才发现的毛病**，一条不落地写进 `docs/已知问题与待办.md`。

- [x] **Step 5: 更新 README 和待办**

- `README.md`：步骤 7 的说明、新增的四个提示词、`tools/eval_archives.py` 的用法。
- `docs/已知问题与待办.md`：删掉「计划②c 要处理的」那一节（两条都在本计划里处理了：按编号对账在 Task 7，缺口不引用 `Q-` 编号在 Task 12），新增「计划③ 要处理的」——至少记上「故事时间线冲突检查等时间估准了再做」。

- [x] **Step 6: 全量测试 + Commit**

Run: `uv run pytest -q`
Expected: PASS

```bash
git add docs/验收记录/2026-09-16-计划2c-档案矛盾地图.md README.md docs/已知问题与待办.md
git commit -m "docs: 计划②c 验收记录与收尾

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## 自查清单（执行完整个计划后）

- [x] `uv run pytest -q` 全绿，原有 595 个测试一个没挂 —— 9-21：860 个全绿
- [x] 四件产出都在：`档案/支线/*.md`、`档案/世界/*.md`、`矛盾.json`、`全书地图.md`
- [x] `档案/index.json` 里每份档案有 `sig`，改一条线只重跑那一份
- [x] 找不到对应线的档案标了过期，文件没被删
- [x] 缺口在档案里按内容写，没有 `Q-` 编号
- [ ] 世界设定集里的「（多个说法）」都补上了 `C-` 编号 —— **9-21 真跑没过**：已回填 146 处、未回填 5 处。不影响三条门槛，已记进 `docs/已知问题与待办.md`
- [x] `prompts/` 下四个新提示词齐了，受控属性表跟 `facts.ATTRS` 一致
- [x] `tools/eval_archives.py` 能 `uv run python` 直接跑
- [x] 三个门槛的实测值写进了验收记录

