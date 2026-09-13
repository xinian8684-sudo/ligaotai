# 理稿台 计划②b：步骤 6 归线排序 + 顺序验收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 做出流水线第 6 步「归线排序」（划世界 → 划支线 → 线内排序 → 跨线对齐 → 找缺口）和作者调整接口，并用西游记 + 一本冷门书验收「线内顺序 Kendall τ ≥ 0.8」。

**Architecture:** 输入准备（`threads_input.py`）、输出检查与清理（`threads_check.py`）都是不调模型的纯函数；`threads.py` 按阶段调综合档模型，每次调用按「提示词全文 + 综合档配置」缓存进 `归线缓存.json`，结果写 `世界与支线.json`；`threads_ops.py` 是作者的调整操作。做法沿用计划②a 的实体合并：已确认的东西重跑时原样保留，读改写都在 `FILE_LOCK` 里，暂停 = 取消任务。

**Tech Stack:** 在计划②a 的基础上不加新依赖（Kendall τ-b 自己写，不引 scipy）。

**设计依据：** `docs/superpowers/specs/2026-09-13-ligaotai-plan2b-threads-design.md`（下称「②b 设计」），上级是 `docs/superpowers/specs/2026-09-10-ligaotai-design.md`。计划①、②a 的实现就是现在仓库里的代码。

**实现时要知道的几个决定（②b 设计里没写到这么细，这里定下来）：**
1. **编号**：世界 `W-01`，线 `L-001`，缺口 `Q-001`。世界和线的编号取文件顶层只增不减的 `next_world` / `next_thread`。草稿世界按**名字**沿用旧编号，草稿线按**块集合**沿用旧编号。
2. **编号时机**：划完世界就给世界定编号；排完序（块集合定了）再给线定编号。所以跨线对齐、找缺口的提示词里用的都是正式编号，重跑时提示词一样，缓存能命中。划支线时如果一个世界要分段，前面几段新建的线用临时键 `<世界编号>#<n>` 告诉后面几段。
3. **划世界整段失败**（所有分段都调用失败）整步失败；部分分段失败，那几段的块进「未分配」。
4. **一块的线不调模型排序**：顺序就是它自己，时间记 0、把握「低」。
5. **跑的途中作者动了 `世界与支线.json`**：跑完时文件跟开跑时读到的不一样，这次结果不写入，步骤记 `outdated`，summary 里 `not_written: true`。所有调用都缓存了，重跑不花钱。
6. **已确认线里的块**：只要还是没删除的主版本，就一直留在线里，没有场景卡也留（作者手动放的）；没有卡的块在提示词里只显示编号。
7. **全书主线**：作者设过（`main_by: "author"`）且那条线还在，就保留；否则取块最多的那个世界里被标 main 的线。
8. **故事时间单位**：已确认的线里有时间，就沿用旧单位、提示词里告诉模型照用；否则让模型重新提议。

**不做（留给后续计划）：** 步骤 7（计划②c）；网页界面（计划③）。

---

## 文件结构

```
ligaotai/
  prompts/
    threads_worlds.md           新：划世界（6.1）
    threads_lines.md            新：划支线（6.2）
    threads_order.md            新：线内排序 + 故事时间（6.3）
    threads_align.md            新：跨线对齐（6.4）
    threads_gaps.md             新：找缺口（6.5）
  src/ligaotai/
    llm.py                      改：加 cache_config / cache_key（从 entities.py 挪过来，公用）
    entities.py                 改：_cache_cfg / _cache_key 改成调 llm.py 的
    book.py                     改：世界与支线.json / 归线缓存.json 路径，本书参数 threads_max_input_tokens
    threads_input.py            新：选块、压行、指纹、片段、按预算分段
    threads_check.py            新：五种调用输出的检查（给 chat_json）和清理（3 次后）
    threads.py                  新：Caller（缓存+进度）、五个阶段、编号、组装、run_threads
    threads_ops.py              新：作者的确认/改名/挪块/合并/拆线/设主线/挪线
    api.py                      改：跑步骤 6、读结果、作者操作的接口
  tests/
    helpers.py                  改：seed_book（直接往书里写场景和卡）、threads_handler（步骤 6 的假回复）
    test_llm.py test_book.py test_api.py test_prompts.py test_scramble.py   改
    test_threads_input.py test_threads_check.py test_threads.py             新
    test_threads_ops.py test_api_threads.py test_eval_threads.py test_probe_book.py   新
  tools/
    scramble.py                 改：--aliases
    probe_book.py               新：真跑前问模型熟不熟这本书
    eval_threads.py             新：顺序验收 + 费用粗估
  docs/验收记录/                  新增一份归线的验收记录
```

**路径约定：** 所有命令都在仓库根目录下执行，用 Git Bash。

**Windows 注意：**
- 终端显示中文会乱码。测试断言和脚本打印只用 ASCII，要看中文结果就写成文件再用 Read 工具读。
- 在工具参数里敲的反斜杠加 u 的转义序列会被变成真字符。本计划的代码里没有这种转义，也别加；要用就用 `chr(92)` 拼。
- 并行执行时，**禁止** `git stash` / `git checkout -- 文件` / `git reset` / `git restore`，只 `git add` 自己改的文件。
- 计划里的代码没有实际跑过。跟计划不一致、或者计划有错的地方，照正确的做，在报告里写明改了什么、为什么。

---
## Task 1: 共用缓存键 + 书的路径和参数

**Files:**
- Modify: `src/ligaotai/llm.py`（加 `import hashlib` 和两个函数）
- Modify: `src/ligaotai/entities.py:334-346`（`_cache_cfg` / `_cache_key` 改成调 llm.py 的）
- Modify: `src/ligaotai/book.py`（两个路径、一个本书参数）
- Test: `tests/test_llm.py`、`tests/test_book.py`（追加）

要点：缓存键的算法**一个字都不能变**，不然 ②a 验收书里已经付过钱的实体合并缓存全部作废。

- [ ] **Step 1: 写失败的测试**

`tests/test_llm.py` 末尾追加：
```python
def test_cache_key_is_shared_with_entities_and_ignores_max_tokens():
    from ligaotai import entities as ent
    from ligaotai.llm import cache_config, cache_key

    c1 = LLMClient(AppConfig(), FakeBackend())
    c2 = LLMClient(AppConfig(synth=TierConfig(thinking="on", effort="high", max_tokens=999)), FakeBackend())
    c3 = LLMClient(AppConfig(api_base="https://other.example"), FakeBackend())
    assert cache_config(c1, "synth") == cache_config(c2, "synth")
    assert cache_config(c3, "synth") != cache_config(c1, "synth")
    assert "api_key" not in cache_config(c1, "synth")
    assert cache_key("s", "u", cache_config(c1, "synth")) == ent._cache_key("s", "u", ent._cache_cfg(c1))
    # 算法固定：sha256(json.dumps([system, user, cfg], ensure_ascii=False, sort_keys=True))
    import hashlib, json

    cfg = {"model": "m"}
    raw = json.dumps(["s", "u", cfg], ensure_ascii=False, sort_keys=True).encode("utf-8")
    assert cache_key("s", "u", cfg) == hashlib.sha256(raw).hexdigest()
```

`tests/test_book.py` 末尾追加：
```python
def test_threads_paths_and_setting(book):
    assert book.threads_path.name == "世界与支线.json"
    assert book.threads_cache_path.name == "归线缓存.json"
    assert book.settings()["threads_max_input_tokens"] == 600000
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_llm.py tests/test_book.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'cache_config'`、`AttributeError: 'Book' object has no attribute 'threads_path'`）

- [ ] **Step 3: 实现**

`src/ligaotai/llm.py`：import 区加 `import hashlib`；在 `class LLMClient` 整个定义之后、`def request_extras` 之前加：
```python
def cache_config(client: LLMClient, tier_name: str) -> dict:
    """缓存键里的配置部分：这一档的配置（不含 max_tokens）+ 接口地址。
    max_tokens 不算——截断由 chat_json 自动加大上限重试，改上限不改变结果，不该让付过钱的调用作废；
    接口地址要算——换了服务商（比如都叫 deepseek-flash 的中转站），模型名一样也不是同一个模型。
    API key 不进缓存键。"""
    return {**client.tier(tier_name).model_dump(exclude={"max_tokens"}), "api_base": client.cfg.api_base}


def cache_key(system: str, user: str, cfg: dict) -> str:
    """提示词全文 + cache_config 给的配置的 sha256。"""
    return hashlib.sha256(
        json.dumps([system, user, cfg], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
```

`src/ligaotai/entities.py`：
- `from .llm import FatalLLMError, LLMClient, LLMError` 改成 `from .llm import FatalLLMError, LLMClient, LLMError, cache_config, cache_key`
- 删掉 `import hashlib`（如果别处没用到；用 Grep 确认）
- `_cache_cfg` / `_cache_key` 两个函数的函数体换成（docstring 保留原样）：
```python
def _cache_cfg(client: LLMClient) -> dict:
    """（原 docstring 不变）"""
    return cache_config(client, "synth")


def _cache_key(system: str, user: str, synth_cfg: dict) -> str:
    """（原 docstring 不变）"""
    return cache_key(system, user, synth_cfg)
```

`src/ligaotai/book.py`：
- `DEFAULT_SETTINGS` 末尾加一项：
```python
    "threads_max_input_tokens": 600000,  # 归线一次调用的输入上限（按 1 个字符 1 个 token 估，偏保守），超过就分段
```
- `class Book` 里 `entities_cache_path` 之后加：
```python
    @property
    def threads_path(self) -> Path:
        return self.root / "世界与支线.json"

    @property
    def threads_cache_path(self) -> Path:
        """归线每次模型调用的缓存：暂停、失败后重跑，输入没变的调用不用再花钱。"""
        return self.root / "归线缓存.json"
```

- [ ] **Step 4: 跑全部测试**

Run: `uv run pytest -q`
Expected: 全部 PASS（原来的 380 个 + 新的 2 个）

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/llm.py src/ligaotai/entities.py src/ligaotai/book.py tests/test_llm.py tests/test_book.py
git commit -m "refactor: 缓存键挪到 llm.py 公用；书加归线的路径和参数"
```

---

## Task 2: 输入准备——选块、压行、指纹

**Files:**
- Create: `src/ligaotai/threads_input.py`
- Modify: `tests/helpers.py`（加 `seed_book`）
- Test: `tests/test_threads_input.py`

要点（②b 设计 2.0）：
- 只取没删除的主版本块（不在任何版本组里的块，加上每组的 `main`）。
- 有新鲜场景卡（`is_fresh`）的块才进 `items`；没有的记进 `unassigned`，原因「没有可用的场景卡」。另外 `all_ids` 记下全部没删除的主版本块（含没卡的），给「已确认线里的块一直留着」用。
- 每张卡压成一行：`编号｜类型｜摘要｜人物：…｜地点：…｜组织：…｜世界线索：…｜时间线索：…`，空字段省略；人物、地点、组织换成规范名并去重；值里的 `｜` 换成 `/`，换行和连续空白压成一个空格。pov 放在人物最前面。
- 指纹 = 喂给模型的全部内容（每块的编号、来源、位置、类型、行、refs）加上 unassigned 的编号。规范名、主版本、卡片内容一变，指纹就变。

- [ ] **Step 1: helpers 加 seed_book**

`tests/helpers.py` 末尾追加：
```python
def seed_book(book, scenes, entities=(), groups=()):
    """不走导入/切场景/场景卡，直接往书里写场景文件、场景卡、实体.json、版本组.json。

    scenes：字典列表。键：id（必填）、source（默认 a.txt）、index（默认在列表里的位置）、
    kind（默认 正文）、summary、persons、places、refs、world、times、removed、
    no_card（不写卡）、stale_card（卡的 scene_hash 对不上）。
    entities：[(类型, 规范名, [叫法...])]，都写成 draft。groups：[(主版本, [成员...])]。
    """
    from ligaotai.cards import card_path
    from ligaotai.fsutil import write_json
    from ligaotai.scenes import Scene, write_scene

    for i, s in enumerate(scenes):
        sid = s["id"]
        text = s.get("text", f"{sid} 的正文。")
        h = f"h-{sid}"
        write_scene(book, Scene(
            id=sid, source=s.get("source", "a.txt"), index=s.get("index", i), start=0, end=len(text),
            chars=len(text), hash=h, removed=s.get("removed", False), text=text,
        ))
        if s.get("no_card"):
            continue
        card = {
            "summary": s.get("summary", f"{sid} 摘要"),
            "pov": "",
            "characters": [{"name": n, "role": "主要"} for n in s.get("persons", [])],
            "locations": list(s.get("places", [])),
            "organizations": [],
            "world_hint": s.get("world", ""),
            "time_hints": list(s.get("times", [])),
            "refs_elsewhere": list(s.get("refs", [])),
            "kind": s.get("kind", "正文"),
        }
        scene_hash = "old" if s.get("stale_card") else h
        write_json(card_path(book, sid), {"id": sid, "scene_hash": scene_hash, "card": card})
    ents = [
        {"id": f"E-{i:04d}", "type": t, "canonical": c, "names": list(ns), "status": "draft", "reason": "", "scenes": []}
        for i, (t, c, ns) in enumerate(entities, 1)
    ]
    write_json(book.entities_path, {"next_id": len(ents) + 1, "entities": ents})
    write_json(book.versions_path, {"params": {}, "groups": [
        {"id": f"G-{i:03d}", "members": list(ms), "main": m, "main_by": "auto", "pairs": []}
        for i, (m, ms) in enumerate(groups, 1)
    ]})
```

- [ ] **Step 2: 写失败的测试**

`tests/test_threads_input.py`：
```python
from helpers import seed_book

from ligaotai.threads_input import NO_CARD, card_line, prepare


def test_prepare_picks_main_versions_and_uses_canonical_names(book):
    seed_book(book, [
        {"id": "S-0001", "persons": ["清儿"], "places": ["青州"], "summary": "林清出门", "times": ["那年冬天"]},
        {"id": "S-0002", "persons": ["林清"]},
        {"id": "S-0003", "persons": ["林清"]},
        {"id": "S-0004", "no_card": True},
        {"id": "S-0005", "removed": True},
        {"id": "S-0006", "stale_card": True},
    ], entities=[("person", "林清", ["林清", "清儿"])], groups=[("S-0002", ["S-0002", "S-0003"])])
    p = prepare(book)
    assert list(p.items) == ["S-0001", "S-0002"]
    assert p.items["S-0001"].line == "S-0001｜正文｜林清出门｜人物：林清｜地点：青州｜时间线索：那年冬天"
    assert p.unassigned == [{"scene": "S-0004", "reason": NO_CARD}, {"scene": "S-0006", "reason": NO_CARD}]
    assert p.all_ids == {"S-0001", "S-0002", "S-0004", "S-0006"}


def test_card_line_escapes_separator_and_dedupes():
    card = {"summary": "甲｜乙\n丙", "pov": "林清", "characters": [{"name": "林清"}, {"name": "清儿"}], "kind": "碎片"}
    assert card_line("S-0009", card, {("person", "清儿"): "林清"}) == "S-0009｜碎片｜甲/乙 丙｜人物：林清"


def test_refs_are_kept(book):
    seed_book(book, [{"id": "S-0001", "refs": ["青州城破", "  "]}])
    assert prepare(book).items["S-0001"].refs == ["青州城破"]


def test_fingerprint_follows_what_the_model_sees(book):
    scenes = [{"id": "S-0001", "persons": ["清儿"]}]
    seed_book(book, scenes, entities=[("person", "林清", ["林清", "清儿"])])
    fp1 = prepare(book).fingerprint
    assert prepare(book).fingerprint == fp1
    seed_book(book, scenes, entities=[("person", "林小清", ["林清", "清儿"])])
    assert prepare(book).fingerprint != fp1
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_threads_input.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'ligaotai.threads_input'`）

- [ ] **Step 4: 实现**

`src/ligaotai/threads_input.py`：
```python
"""步骤 6 归线排序的输入准备：选出参与的块、每张卡压成一行、输入指纹、片段、按预算分段。

全是本地计算，不调模型。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .book import Book
from .cards import is_fresh, load_cards
from .fsutil import natural_key, read_json
from .scenes import load_scenes

ORDERED_KINDS = ("正文", "碎片")  # 进支线、参与排序
OUTLINE = "提纲"  # 挂在线上，不排序
NOTE = "设定笔记"  # 只挂在世界上
NO_CARD = "没有可用的场景卡"
SEP = "｜"


@dataclass
class Item:
    id: str
    source: str
    index: int
    kind: str
    line: str
    refs: list[str] = field(default_factory=list)


@dataclass
class Prepared:
    items: dict[str, Item]  # 有新鲜场景卡的主版本块，按编号顺序
    unassigned: list[dict]  # [{"scene", "reason"}]：主版本块但没有可用的场景卡
    all_ids: set[str]  # 全部没删除的主版本块（含没卡的）
    fingerprint: str


def name_map(book: Book) -> dict[tuple[str, str], str]:
    """（类型, 叫法）→ 规范名。还没有 实体.json 时是空的。"""
    data = read_json(book.entities_path, {"entities": []})
    return {(e["type"], n): e["canonical"] for e in data.get("entities", []) for n in e.get("names", [])}


def clean_text(s) -> str:
    return " ".join(str(s).replace(SEP, "/").split())


def _canon(names, typ: str, cmap: dict) -> list[str]:
    out: list[str] = []
    for n in names:
        c = cmap.get((typ, n), n)
        if c and c not in out:
            out.append(c)
    return out


def card_line(sid: str, card: dict, cmap: dict) -> str:
    persons = [c.get("name", "") for c in card.get("characters", [])]
    if card.get("pov"):
        persons.insert(0, card["pov"])
    fields = [
        ("人物", "、".join(_canon(persons, "person", cmap))),
        ("地点", "、".join(_canon(card.get("locations", []), "location", cmap))),
        ("组织", "、".join(_canon(card.get("organizations", []), "organization", cmap))),
        ("世界线索", card.get("world_hint", "")),
        ("时间线索", "；".join(card.get("time_hints", []))),
    ]
    parts = [sid, card.get("kind", "正文"), clean_text(card.get("summary", ""))]
    parts += [f"{k}：{clean_text(v)}" for k, v in fields if clean_text(v)]
    return SEP.join(parts)


def fingerprint(items: dict[str, Item], unassigned: list[dict]) -> str:
    """喂给模型的全部内容的指纹：规范名、主版本、卡片内容一变，行就变，指纹跟着变。"""
    payload: list = [[i.id, i.source, i.index, i.kind, i.line, i.refs] for i in items.values()]
    payload.append(sorted((u["scene"] for u in unassigned), key=natural_key))
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def prepare(book: Book) -> Prepared:
    scenes = [s for s in load_scenes(book) if not s.removed]
    groups = read_json(book.versions_path, {"groups": []}).get("groups", [])
    not_main = {m for g in groups for m in g["members"] if m != g["main"]}
    records = load_cards(book)
    cmap = name_map(book)
    items: dict[str, Item] = {}
    unassigned: list[dict] = []
    all_ids: set[str] = set()
    for s in scenes:
        if s.id in not_main:
            continue
        all_ids.add(s.id)
        record = records.get(s.id)
        if not is_fresh(record, s):
            unassigned.append({"scene": s.id, "reason": NO_CARD})
            continue
        card = record["card"]
        refs = [clean_text(r) for r in card.get("refs_elsewhere", [])]
        items[s.id] = Item(s.id, s.source, s.index, card.get("kind", "正文"), card_line(s.id, card, cmap),
                           [r for r in refs if r])
    return Prepared(items, unassigned, all_ids, fingerprint(items, unassigned))
```

- [ ] **Step 5: 跑测试**

Run: `uv run pytest tests/test_threads_input.py -q`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
git add src/ligaotai/threads_input.py tests/helpers.py tests/test_threads_input.py
git commit -m "feat: 归线输入准备（选主版本块、压行换规范名、输入指纹）"
```

---

## Task 3: 输入准备——片段、按预算分段

**Files:**
- Modify: `src/ligaotai/threads_input.py`（追加两个函数）
- Test: `tests/test_threads_input.py`（追加）

要点：
- **片段**（②b 设计 2.3）：一条线里的正文 / 碎片块按「源文件（自然排序）+ 文件内位置」排好，同一文件里位置紧挨着（`index` 差 1）的连成一个片段。中间隔着提纲、设定笔记、非主版本、别的线的块，因为它们不在传进来的列表里，位置就不连续，自然断开。只有一块的也当一个片段返回。
- **按预算分段**（②b 设计 2.1 大书保护）：按顺序切，每段的成本之和不超过预算；单个就超预算的自成一段。成本按「行的字数 + 1」算（1 字 1 token，偏保守）。

- [ ] **Step 1: 写失败的测试**

`tests/test_threads_input.py` 末尾追加：
```python
from ligaotai.threads_input import Item, segments, split_by_budget


def test_segments_bind_adjacent_blocks_of_the_same_file():
    items = {
        "S-0001": Item("S-0001", "b.txt", 0, "正文", ""),
        "S-0002": Item("S-0002", "b.txt", 1, "碎片", ""),
        "S-0003": Item("S-0003", "b.txt", 3, "正文", ""),  # 跟前面隔了一块
        "S-0004": Item("S-0004", "a.txt", 0, "正文", ""),
        "S-0005": Item("S-0005", "a.txt", 1, "提纲", ""),  # 提纲不参与，也把前后隔开
        "S-0006": Item("S-0006", "a.txt", 2, "正文", ""),
        "S-0007": Item("S-0007", "文件10.txt", 0, "正文", ""),
        "S-0008": Item("S-0008", "文件2.txt", 0, "正文", ""),
    }
    assert segments(list(items), items) == [
        ["S-0004"], ["S-0006"], ["S-0001", "S-0002"], ["S-0003"], ["S-0008"], ["S-0007"],
    ]


def test_segments_only_use_the_given_ids():
    items = {f"S-000{i}": Item(f"S-000{i}", "a.txt", i, "正文", "") for i in range(1, 4)}
    assert segments(["S-0001", "S-0003"], items) == [["S-0001"], ["S-0003"]]


def test_split_by_budget():
    cost = {"a": 4, "b": 4, "c": 4, "d": 20, "e": 1}
    assert split_by_budget(list(cost), cost, 10) == [["a", "b"], ["c"], ["d"], ["e"]]
    assert split_by_budget([], cost, 10) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_threads_input.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'segments'`）

- [ ] **Step 3: 实现**

`src/ligaotai/threads_input.py` 末尾追加：
```python
def segments(ids: list[str], items: dict[str, Item]) -> list[list[str]]:
    """把一条线里的正文 / 碎片块按「源文件 + 文件内位置」排好，同一文件里位置紧挨着的连成片段。
    只有一块的也当一个片段返回。不是正文 / 碎片的块跳过。"""
    ordered = sorted(
        (items[i] for i in ids if items[i].kind in ORDERED_KINDS),
        key=lambda it: (natural_key(it.source), it.index),
    )
    out: list[list[str]] = []
    prev: Item | None = None
    for it in ordered:
        if prev is not None and it.source == prev.source and it.index == prev.index + 1:
            out[-1].append(it.id)
        else:
            out.append([it.id])
        prev = it
    return out


def split_by_budget(ids: list[str], cost: dict[str, int], budget: int) -> list[list[str]]:
    """按顺序切成几段，每段的 cost 之和不超过 budget；单个就超过 budget 的自成一段。"""
    chunks: list[list[str]] = []
    total = 0
    for i in ids:
        c = cost[i]
        if chunks and total + c <= budget:
            chunks[-1].append(i)
            total += c
        else:
            chunks.append([i])
            total = c
    return chunks
```

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_threads_input.py -q`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/threads_input.py tests/test_threads_input.py
git commit -m "feat: 归线输入的片段绑定和按预算分段"
```

---
## Task 4: 输出检查——覆盖校验 + 划世界

**Files:**
- Create: `src/ligaotai/threads_check.py`
- Test: `tests/test_threads_check.py`

要点（②b 设计 2.1、2.6）：
- 检查函数（给 `chat_json` 的 check）只返回问题清单，**不许抛异常**，输出长什么样都不能炸。
- 覆盖校验：列出来的编号必须恰好把期望的编号覆盖一遍。编造的、重复的、漏掉的分别报，每类最多列 20 个。
- 划世界的输出：`{"time_unit": "年", "worlds": [{"id"?, "name", "reason", "scenes": [...]}]}`。`id` 只能是「已有的世界」里的键；新世界不写 id，要有 name。`need_unit` 为真时 time_unit 不能空。
- 清理（3 次后还有问题时用）：编造的丢掉，重复的留第一次出现的，漏掉的返回给调用方记「未分配」；同一个已有 id 出现两次就合到一起；新世界没名字叫「未命名世界」；新世界一个块都没剩就丢掉。

- [ ] **Step 1: 写失败的测试**

`tests/test_threads_check.py`：
```python
from ligaotai.threads_check import check_worlds, clean_worlds, coverage_problems


def test_coverage_problems():
    assert coverage_problems(["S-0001", "S-0002"], {"S-0001", "S-0002"}) == []
    p = coverage_problems(["S-0001", "S-0001", "S-0009"], {"S-0001", "S-0002"})
    assert len(p) == 3
    assert "S-0009" in p[0] and "S-0001" in p[1] and "S-0002" in p[2]


def test_coverage_lists_at_most_20():
    p = coverage_problems([], {f"S-{i:04d}" for i in range(1, 31)})
    assert p[0].count("S-") == 20


def test_check_worlds():
    ok = {"time_unit": "年", "worlds": [{"name": "人间", "reason": "r", "scenes": ["S-0001"]}, {"id": "W-01", "scenes": ["S-0002"]}]}
    assert check_worlds(ok, {"S-0001", "S-0002"}, {"W-01"}, need_unit=True) == []
    assert check_worlds({"worlds": ok["worlds"]}, {"S-0001", "S-0002"}, {"W-01"}, need_unit=True) != []
    assert check_worlds({"worlds": ok["worlds"]}, {"S-0001", "S-0002"}, {"W-01"}, need_unit=False) == []
    assert check_worlds({"worlds": [{"id": "W-09", "scenes": ["S-0001"]}]}, {"S-0001"}, set(), False) != []
    assert check_worlds({"worlds": [{"scenes": ["S-0001"]}]}, {"S-0001"}, set(), False) != []
    assert check_worlds({"worlds": "乱写"}, {"S-0001"}, set(), False) == ["缺少 worlds 列表"]
    assert check_worlds({"worlds": [1, None]}, set(), set(), False) != []


def test_clean_worlds():
    data = {"time_unit": " 年 ", "worlds": [
        {"name": "人间", "reason": "r", "scenes": ["S-0001", "S-0009", "S-0001"]},
        {"id": "W-01", "scenes": ["S-0002"]},
        {"id": "W-01", "scenes": ["S-0003", "S-0001"]},
        {"scenes": ["S-0004"]},
        {"name": "空的", "scenes": ["S-0009"]},
        "乱写",
    ]}
    worlds, missing, unit = clean_worlds(data, {"S-0001", "S-0002", "S-0003", "S-0004", "S-0005"}, {"W-01"})
    assert unit == "年"
    assert worlds == [
        {"key": None, "name": "人间", "reason": "r", "scenes": ["S-0001"]},
        {"key": "W-01", "name": "", "reason": "", "scenes": ["S-0002", "S-0003"]},
        {"key": None, "name": "未命名世界", "reason": "", "scenes": ["S-0004"]},
    ]
    assert missing == ["S-0005"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_threads_check.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'ligaotai.threads_check'`）

- [ ] **Step 3: 实现**

`src/ligaotai/threads_check.py`：
```python
"""步骤 6 各次模型调用的输出检查（给 chat_json 的 check）和收尾清理（3 次后还有问题时用）。

检查函数只返回问题清单，不抛异常；清理函数把输出修成能用的样子：编造的编号丢掉，
重复的只留第一次出现的，漏掉的交给调用方记进「未分配」。"""

from __future__ import annotations

import math

from .fsutil import natural_key

MAX_LISTED = 20
CONFS = ("高", "中", "低")
UNNAMED_WORLD = "未命名世界"
UNNAMED_THREAD = "未命名支线"


def str_list(v) -> list[str]:
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def text(v) -> str:
    return str(v).strip() if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def coverage_problems(listed: list[str], expected: set[str], what: str = "场景") -> list[str]:
    unknown = [x for x in dict.fromkeys(listed) if x not in expected]
    seen: set[str] = set()
    dup: list[str] = []
    for x in listed:
        if x in seen and x not in dup:
            dup.append(x)
        seen.add(x)
    missing = sorted(expected - seen, key=natural_key)
    problems = []
    if unknown:
        problems.append(f"这些编号不在给你的{what}里，不要编造：" + "、".join(unknown[:MAX_LISTED]))
    if dup:
        problems.append("这些编号出现了不止一次，每个只能放一处：" + "、".join(dup[:MAX_LISTED]))
    if missing:
        problems.append(f"这些{what}漏掉了，每个都要放进去：" + "、".join(missing[:MAX_LISTED]))
    return problems


# --- 6.1 划世界 ---


def check_worlds(data: dict, expected: set[str], known: set[str], need_unit: bool) -> list[str]:
    problems: list[str] = []
    if need_unit and not text(data.get("time_unit")):
        problems.append("缺少 time_unit（全书统一的故事时间单位，比如「年」）")
    worlds = data.get("worlds")
    if not isinstance(worlds, list):
        return problems + ["缺少 worlds 列表"]
    listed: list[str] = []
    for i, w in enumerate(worlds, 1):
        if not isinstance(w, dict):
            problems.append(f"第 {i} 个世界格式不对")
            continue
        wid = w.get("id")
        if wid not in (None, "") and wid not in known:
            problems.append(f"第 {i} 个世界的 id「{wid}」不是已有的世界；新世界不要写 id")
        elif wid in (None, "") and not text(w.get("name")):
            problems.append(f"第 {i} 个世界没有 name")
        listed += str_list(w.get("scenes"))
    return problems + coverage_problems(listed, expected)


def clean_worlds(data: dict, expected: set[str], known: set[str]) -> tuple[list[dict], list[str], str]:
    """返回 (世界列表, 漏掉的场景, 时间单位)。世界：{"key", "name", "reason", "scenes"}；
    key 是已有世界的键，新世界是 None（调用方再编号）。"""
    taken: set[str] = set()
    out: list[dict] = []
    by_key: dict[str, dict] = {}
    for w in data.get("worlds") or []:
        if not isinstance(w, dict):
            continue
        wid = w.get("id") if w.get("id") in known else None
        scenes = []
        for s in str_list(w.get("scenes")):
            if s in expected and s not in taken:
                taken.add(s)
                scenes.append(s)
        if wid is not None and wid in by_key:
            by_key[wid]["scenes"] += scenes
            continue
        if wid is None and not scenes:
            continue
        name = text(w.get("name")) if wid is None else ""
        entry = {"key": wid, "name": name or ("" if wid else UNNAMED_WORLD), "reason": text(w.get("reason")), "scenes": scenes}
        out.append(entry)
        if wid is not None:
            by_key[wid] = entry
    missing = [s for s in sorted(expected, key=natural_key) if s not in taken]
    return out, missing, text(data.get("time_unit"))
```

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_threads_check.py -q`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/threads_check.py tests/test_threads_check.py
git commit -m "feat: 归线输出检查——覆盖校验和划世界"
```

---

## Task 5: 输出检查——划支线

**Files:**
- Modify: `src/ligaotai/threads_check.py`（追加）
- Test: `tests/test_threads_check.py`（追加）

要点（②b 设计 2.2）：
- 输出：`{"threads": [{"id"?, "name", "about", "main", "scenes": [...], "outlines": [...]}], "world_outlines": [...]}`。
- `ordered`（正文 / 碎片）要被全部线的 `scenes` 恰好覆盖一遍；`outlines`（提纲）要被全部线的 `outlines` 加 `world_outlines` 恰好覆盖一遍。
- `id` 只能是 `known` 里的键（作者已确认的线、前几段新建的线）；新线不写 id，要有 name。
- 有线的时候，恰好一条标 `"main": true`。
- 清理：
  - 同一个已有 id 出现两次就合到一起。
  - 新线没名字叫「未命名支线」。
  - 新线没有 scenes，它的提纲挪到 `world_outlines`，线丢掉。
  - 漏掉的提纲放进 `world_outlines`（提纲本来就可以只挂世界），漏掉的正文 / 碎片进 `missing`。
  - main 只留第一条；一条都没有就给 scenes 最多的那条（平票取靠前的）。

- [ ] **Step 1: 写失败的测试**

`tests/test_threads_check.py` 末尾追加：
```python
from ligaotai.threads_check import check_lines, clean_lines

ORD = {"S-0001", "S-0002", "S-0003"}
OUT = {"S-0009"}


def line_reply(*threads, world_outlines=()):
    return {"threads": list(threads), "world_outlines": list(world_outlines)}


def test_check_lines_ok():
    data = line_reply(
        {"name": "甲", "about": "a", "main": True, "scenes": ["S-0001", "S-0002"], "outlines": ["S-0009"]},
        {"id": "L-003", "scenes": ["S-0003"]},
    )
    assert check_lines(data, ORD, OUT, {"L-003"}) == []


def test_check_lines_problems():
    base = {"name": "甲", "main": True, "scenes": ["S-0001", "S-0002", "S-0003"], "outlines": []}
    assert check_lines(line_reply(base), ORD, OUT, set()) != []  # 提纲漏了
    assert check_lines(line_reply(base, world_outlines=["S-0009"]), ORD, OUT, set()) == []
    no_main = {**base, "main": False}
    assert check_lines(line_reply(no_main, world_outlines=["S-0009"]), ORD, OUT, set()) != []
    two_main = [base, {"name": "乙", "main": True, "scenes": []}]
    assert check_lines(line_reply(*two_main, world_outlines=["S-0009"]), ORD, OUT, set()) != []
    bad_id = {**base, "id": "L-099"}
    assert check_lines(line_reply(bad_id, world_outlines=["S-0009"]), ORD, OUT, set()) != []
    assert check_lines({"threads": None}, ORD, OUT, set()) == ["缺少 threads 列表"]
    assert check_lines(line_reply(), set(), OUT, set()) != []  # 只有提纲、没线：提纲要放 world_outlines
    assert check_lines(line_reply(world_outlines=["S-0009"]), set(), OUT, set()) == []


def test_clean_lines():
    data = line_reply(
        {"name": "甲", "about": "a", "main": False, "scenes": ["S-0001", "S-0001", "S-0077"], "outlines": []},
        {"id": "L-003", "scenes": ["S-0002"]},
        {"id": "L-003", "scenes": ["S-0003"], "outlines": ["S-0009"]},
        {"name": "", "main": True, "scenes": [], "outlines": []},
    )
    got = clean_lines(data, ORD | {"S-0004"}, OUT | {"S-0008"}, {"L-003"})
    assert got["threads"] == [
        {"key": None, "name": "甲", "about": "a", "main": False, "scenes": ["S-0001"], "outlines": []},
        {"key": "L-003", "name": "", "about": "", "main": True, "scenes": ["S-0002", "S-0003"], "outlines": ["S-0009"]},
    ]
    assert got["world_outlines"] == ["S-0008"]
    assert got["missing"] == ["S-0004"]


def test_clean_lines_keeps_first_main_and_moves_orphan_outlines():
    data = line_reply(
        {"name": "甲", "main": True, "scenes": ["S-0001"]},
        {"name": "乙", "main": True, "scenes": ["S-0002", "S-0003"]},
        {"name": "丙", "scenes": [], "outlines": ["S-0009"]},
    )
    got = clean_lines(data, ORD, OUT, set())
    assert [t["main"] for t in got["threads"]] == [True, False]
    assert got["threads"][1]["name"] == "乙"
    assert got["world_outlines"] == ["S-0009"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_threads_check.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'check_lines'`）

- [ ] **Step 3: 实现**

`src/ligaotai/threads_check.py` 末尾追加：
```python
# --- 6.2 划支线 ---


def check_lines(data: dict, ordered: set[str], outlines: set[str], known: set[str]) -> list[str]:
    threads = data.get("threads")
    if not isinstance(threads, list):
        return ["缺少 threads 列表"]
    problems: list[str] = []
    scene_list: list[str] = []
    outline_list: list[str] = str_list(data.get("world_outlines"))
    mains = 0
    for i, t in enumerate(threads, 1):
        if not isinstance(t, dict):
            problems.append(f"第 {i} 条线格式不对")
            continue
        tid = t.get("id")
        if tid not in (None, "") and tid not in known:
            problems.append(f"第 {i} 条线的 id「{tid}」不是已有的线；新线不要写 id")
        elif tid in (None, "") and not text(t.get("name")):
            problems.append(f"第 {i} 条线没有 name")
        mains += t.get("main") is True
        scene_list += str_list(t.get("scenes"))
        outline_list += str_list(t.get("outlines"))
    if threads and mains != 1:
        problems.append(f"要恰好有一条线标 \"main\": true，现在有 {mains} 条")
    problems += coverage_problems(scene_list, ordered, "正文/碎片块")
    problems += coverage_problems(outline_list, outlines, "提纲块")
    return problems


def clean_lines(data: dict, ordered: set[str], outlines: set[str], known: set[str]) -> dict:
    """返回 {"threads": [{"key", "name", "about", "main", "scenes", "outlines"}], "world_outlines", "missing"}。
    key 是已有线的键，新线是 None。"""
    taken: set[str] = set()

    def pick(ids, allowed: set[str]) -> list[str]:
        out = []
        for s in str_list(ids):
            if s in allowed and s not in taken:
                taken.add(s)
                out.append(s)
        return out

    threads: list[dict] = []
    by_key: dict[str, dict] = {}
    world_outlines: list[str] = []
    for t in data.get("threads") or []:
        if not isinstance(t, dict):
            continue
        key = t.get("id") if t.get("id") in known else None
        scenes, outs = pick(t.get("scenes"), ordered), pick(t.get("outlines"), outlines)
        if key is not None and key in by_key:
            by_key[key]["scenes"] += scenes
            by_key[key]["outlines"] += outs
            by_key[key]["main"] = by_key[key]["main"] or t.get("main") is True
            continue
        if key is None and not scenes:
            world_outlines += outs
            continue
        entry = {
            "key": key,
            "name": "" if key else (text(t.get("name")) or UNNAMED_THREAD),
            "about": "" if key else text(t.get("about")),
            "main": t.get("main") is True,
            "scenes": scenes,
            "outlines": outs,
        }
        threads.append(entry)
        if key is not None:
            by_key[key] = entry
    world_outlines += pick(data.get("world_outlines"), outlines)
    world_outlines += [s for s in sorted(outlines, key=natural_key) if s not in taken]
    missing = [s for s in sorted(ordered, key=natural_key) if s not in taken]
    first = next((t for t in threads if t["main"]), None)
    if first is None and threads:
        first = max(threads, key=lambda t: len(t["scenes"]))  # max 平票取第一个
    for t in threads:
        t["main"] = t is first
    return {"threads": threads, "world_outlines": world_outlines, "missing": missing}
```

注意 `test_clean_lines` 里第二个 `L-003`（带 `"main"` 缺省）和最后一个无名空线：无名空线 `main: true` 但没有 scenes，被丢掉；于是一条 main 都没有，main 给 scenes 最多的 `L-003`（2 块）。

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_threads_check.py -q`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/threads_check.py tests/test_threads_check.py
git commit -m "feat: 归线输出检查——划支线"
```

---

## Task 6: 输出检查——线内排序

**Files:**
- Modify: `src/ligaotai/threads_check.py`（追加）
- Test: `tests/test_threads_check.py`（追加）

要点（②b 设计 2.3）：
- 输出：`{"order": ["P-001", "S-0007", ...], "times": {"S-0001": [数值或 null, "高|中|低"]}, "end": {"state": "完结|待定", "note": "..."}}`。
- `order` 里的片段编号展开成它的块；展开后要恰好覆盖这条线的全部块（一个块既通过片段又单独出现就算重复）。
- 每块都要有时间：`[数值或 null, 把握]`，也接受 `{"t":…, "conf":…}`；数值可以是数字字符串；把握不认识就当「低」。格式不对的、缺的都报问题。
- `end.state` 只能是「完结」「待定」。
- 清理：按展开后的顺序、只留期望里的、第一次出现的；漏掉的按 fallback 的顺序返回；时间只留格式对的；state 不认识就「待定」。

- [ ] **Step 1: 写失败的测试**

`tests/test_threads_check.py` 末尾追加：
```python
from ligaotai.threads_check import check_order, clean_order, parse_time

SEGS = {"P-001": ["S-0001", "S-0002"]}
EXP = {"S-0001", "S-0002", "S-0003"}


def order_reply(order, times=None, state="待定"):
    times = {s: [i, "高"] for i, s in enumerate(sorted(EXP))} if times is None else times
    return {"order": order, "times": times, "end": {"state": state, "note": "n"}}


def test_parse_time():
    assert parse_time([1, "高"]) == {"t": 1, "conf": "高"}
    assert parse_time(["2.5", "中"]) == {"t": 2.5, "conf": "中"}
    assert parse_time([None, "很有把握"]) == {"t": None, "conf": "低"}
    assert parse_time({"t": 3, "conf": "低"}) == {"t": 3, "conf": "低"}
    assert parse_time([True, "高"]) is None
    assert parse_time(["不知道", "高"]) is None
    assert parse_time([float("nan"), "高"]) is None
    assert parse_time(5) is None


def test_check_order():
    assert check_order(order_reply(["S-0003", "P-001"]), SEGS, EXP) == []
    assert check_order(order_reply(["S-0003", "S-0002", "S-0001"]), SEGS, EXP) == []  # 片段可以拆
    assert check_order(order_reply(["P-001", "S-0001", "S-0003"]), SEGS, EXP) != []  # 重复
    assert check_order(order_reply(["P-001"]), SEGS, EXP) != []  # 漏
    assert check_order(order_reply(["P-001", "S-0003", "P-009"]), SEGS, EXP) != []  # 编造
    assert check_order(order_reply(["P-001", "S-0003"], times={}), SEGS, EXP) != []
    assert check_order(order_reply(["P-001", "S-0003"], state="写完了"), SEGS, EXP) != []
    assert check_order({"order": "乱写"}, SEGS, EXP) == ["缺少 order 列表"]


def test_clean_order():
    data = order_reply(["S-0003", "P-001", "S-0003", "S-0099"], times={"S-0003": [5, "中"], "S-0001": "乱写"}, state="?")
    got = clean_order(data, SEGS, EXP | {"S-0004"}, ["S-0001", "S-0002", "S-0003", "S-0004"])
    assert got["scenes"] == ["S-0003", "S-0001", "S-0002"]
    assert got["times"] == {"S-0003": {"t": 5, "conf": "中"}}
    assert got["end"] == {"state": "待定", "note": "n"}
    assert got["missing"] == ["S-0004"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_threads_check.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'check_order'`）

- [ ] **Step 3: 实现**

`src/ligaotai/threads_check.py` 末尾追加：
```python
# --- 6.3 线内排序 ---

END_STATES = ("完结", "待定")


def parse_time(v) -> dict | None:
    """[数值或 null, 把握] 或 {"t", "conf"} → {"t", "conf"}；格式不对返回 None。"""
    if isinstance(v, dict):
        v = [v.get("t"), v.get("conf")]
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return None
    t, conf = v
    if isinstance(t, str):
        try:
            t = float(t)
        except ValueError:
            return None
    if t is not None and (isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t)):
        return None
    return {"t": t, "conf": conf if conf in CONFS else "低"}


def expand_order(order, segs: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    for x in str_list(order):
        out += segs.get(x, [x])
    return out


def check_order(data: dict, segs: dict[str, list[str]], expected: set[str]) -> list[str]:
    if not isinstance(data.get("order"), list):
        return ["缺少 order 列表"]
    problems = coverage_problems(expand_order(data["order"], segs), expected, "场景（或片段里的场景）")
    times = data.get("times") if isinstance(data.get("times"), dict) else {}
    no_time = [s for s in sorted(expected, key=natural_key) if s not in times]
    bad_time = [s for s in sorted(expected, key=natural_key) if s in times and parse_time(times[s]) is None]
    if no_time:
        problems.append("这些块没有给故事时间：" + "、".join(no_time[:MAX_LISTED]))
    if bad_time:
        problems.append("这些块的时间格式不对，要写成 [数值或 null, \"高/中/低\"]：" + "、".join(bad_time[:MAX_LISTED]))
    end = data.get("end")
    if not isinstance(end, dict) or end.get("state") not in END_STATES:
        problems.append("end.state 只能是「完结」或「待定」")
    return problems


def clean_order(data: dict, segs: dict[str, list[str]], expected: set[str], fallback: list[str]) -> dict:
    """返回 {"scenes", "times", "end", "missing"}；missing 按 fallback 的顺序。"""
    scenes: list[str] = []
    for s in expand_order(data.get("order"), segs):
        if s in expected and s not in scenes:
            scenes.append(s)
    got = set(scenes)
    raw = data.get("times") if isinstance(data.get("times"), dict) else {}
    times = {}
    for s in scenes:
        t = parse_time(raw.get(s)) if s in raw else None
        if t is not None:
            times[s] = t
    end = data.get("end") if isinstance(data.get("end"), dict) else {}
    state = end.get("state") if end.get("state") in END_STATES else "待定"
    return {
        "scenes": scenes,
        "times": times,
        "end": {"state": state, "note": text(end.get("note"))},
        "missing": [s for s in fallback if s in expected and s not in got],
    }
```

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_threads_check.py -q`
Expected: 11 passed

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/threads_check.py tests/test_threads_check.py
git commit -m "feat: 归线输出检查——线内排序"
```

---
## Task 7: 输出检查——跨线对齐 + 找缺口

**Files:**
- Modify: `src/ligaotai/threads_check.py`（追加）
- Test: `tests/test_threads_check.py`（追加）

要点（②b 设计 2.4、2.5）：
- 对齐输出：`{"threads": [{"id", "offset"}], "intersections": [{"thread", "scene", "main_scene", "reason"}]}`。每条线的 id 恰好出现一次；offset 是数字或 null；交汇点的 thread 必须是主线以外的线，scene 在那条线里，main_scene 在主线里。
- 对齐清理：主线 offset 固定 0；其他线 offset 格式不对就 null；不合格的交汇点丢掉，重复的去重。
- 缺口输出：`{"gaps": [{"event", "mentioned_in", "thread", "after", "before"}]}`。event 不能空；mentioned_in 不能空，且只能是提到过事件的块；thread 为 null 或这个世界的线；after / before 为 null 或那条线里的块。
- 缺口清理：event 空或 mentioned_in 一个合格的都没有 → 丢掉；thread 不合格 → thread / after / before 全置 null；after / before 不在线里 → 置 null。

- [ ] **Step 1: 写失败的测试**

`tests/test_threads_check.py` 末尾追加：
```python
from ligaotai.threads_check import check_align, check_gaps, clean_align, clean_gaps

MEMBERS = {"L-001": {"S-0001", "S-0002"}, "L-002": {"S-0003"}, "L-003": {"S-0004"}}


def test_check_align():
    ok = {"threads": [{"id": "L-001", "offset": 0}, {"id": "L-002", "offset": 1.5}, {"id": "L-003", "offset": None}],
          "intersections": [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "r"}]}
    assert check_align(ok, set(MEMBERS), "L-001", MEMBERS) == []
    assert check_align({"threads": ok["threads"][:2]}, set(MEMBERS), "L-001", MEMBERS) != []
    bad_offset = {"threads": [{**t, "offset": "很久"} for t in ok["threads"]]}
    assert check_align(bad_offset, set(MEMBERS), "L-001", MEMBERS) != []
    bad_cross = {**ok, "intersections": [{"thread": "L-001", "scene": "S-0001", "main_scene": "S-0002"}]}
    assert check_align(bad_cross, set(MEMBERS), "L-001", MEMBERS) != []
    assert check_align({"threads": 3}, set(MEMBERS), "L-001", MEMBERS) == ["缺少 threads 列表"]


def test_clean_align():
    data = {"threads": [{"id": "L-001", "offset": 9}, {"id": "L-002", "offset": "2"}, {"id": "L-003", "offset": "?"}],
            "intersections": [
                {"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "r"},
                {"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "重复"},
                {"thread": "L-003", "scene": "S-0003", "main_scene": "S-0002"},
            ]}
    offsets, cross = clean_align(data, set(MEMBERS), "L-001", MEMBERS)
    assert offsets == {"L-001": 0, "L-002": 2.0, "L-003": None}
    assert cross == [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "r"}]


LINES = {"L-001": ["S-0001", "S-0002", "S-0003"]}


def test_check_gaps():
    ok = {"gaps": [{"event": "城破", "mentioned_in": ["S-0002"], "thread": "L-001", "after": "S-0001", "before": None}]}
    assert check_gaps(ok, {"S-0002"}, LINES) == []
    assert check_gaps({"gaps": []}, {"S-0002"}, LINES) == []
    assert check_gaps({"gaps": [{**ok["gaps"][0], "event": ""}]}, {"S-0002"}, LINES) != []
    assert check_gaps({"gaps": [{**ok["gaps"][0], "mentioned_in": ["S-0003"]}]}, {"S-0002"}, LINES) != []
    assert check_gaps({"gaps": [{**ok["gaps"][0], "thread": "L-009"}]}, {"S-0002"}, LINES) != []
    assert check_gaps({"gaps": [{**ok["gaps"][0], "after": "S-0099"}]}, {"S-0002"}, LINES) != []
    assert check_gaps({}, {"S-0002"}, LINES) == ["缺少 gaps 列表"]


def test_clean_gaps():
    data = {"gaps": [
        {"event": "城破", "mentioned_in": ["S-0002", "S-0099"], "thread": "L-001", "after": "S-0001", "before": "S-0099"},
        {"event": "婚宴", "mentioned_in": ["S-0002"], "thread": "L-009", "after": "S-0001"},
        {"event": "", "mentioned_in": ["S-0002"]},
        {"event": "没出处", "mentioned_in": ["S-0099"]},
    ]}
    assert clean_gaps(data, {"S-0002"}, LINES) == [
        {"event": "城破", "mentioned_in": ["S-0002"], "thread": "L-001", "after": "S-0001", "before": None},
        {"event": "婚宴", "mentioned_in": ["S-0002"], "thread": None, "after": None, "before": None},
    ]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_threads_check.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'check_align'`）

- [ ] **Step 3: 实现**

`src/ligaotai/threads_check.py` 末尾追加：
```python
# --- 6.4 跨线对齐 ---


def _offset(v) -> tuple[bool, float | None]:
    """(格式对不对, 值)。null 是合法的「对不上」。"""
    if v is None:
        return True, None
    t = parse_time([v, "低"])
    return (t is not None and t["t"] is not None), (t["t"] if t else None)


def _cross_ok(c, thread_ids: set[str], main: str, members: dict[str, set[str]]) -> bool:
    return (
        isinstance(c, dict)
        and c.get("thread") in thread_ids
        and c.get("thread") != main
        and c.get("scene") in members[c["thread"]]
        and c.get("main_scene") in members[main]
    )


def check_align(data: dict, thread_ids: set[str], main: str, members: dict[str, set[str]]) -> list[str]:
    threads = data.get("threads")
    if not isinstance(threads, list):
        return ["缺少 threads 列表"]
    listed = [t.get("id") for t in threads if isinstance(t, dict) and isinstance(t.get("id"), str)]
    problems = coverage_problems(listed, thread_ids, "线")
    bad = [t.get("id") for t in threads if isinstance(t, dict) and not _offset(t.get("offset"))[0]]
    if bad:
        problems.append("这些线的 offset 要写数字或 null：" + "、".join(str(x) for x in bad[:MAX_LISTED]))
    crosses = data.get("intersections", [])
    if not isinstance(crosses, list):
        problems.append("intersections 要是列表")
    else:
        for i, c in enumerate(crosses, 1):
            if not _cross_ok(c, thread_ids, main, members):
                problems.append(f"第 {i} 个交汇点不对：thread 要是主线以外的线，scene 在那条线里，main_scene 在主线 {main} 里")
    return problems


def clean_align(
    data: dict, thread_ids: set[str], main: str, members: dict[str, set[str]]
) -> tuple[dict[str, float | None], list[dict]]:
    offsets: dict[str, float | None] = {t: None for t in thread_ids}
    for t in data.get("threads") or []:
        if isinstance(t, dict) and t.get("id") in thread_ids:
            ok, v = _offset(t.get("offset"))
            if ok:
                offsets[t["id"]] = v
    offsets[main] = 0
    cross: list[dict] = []
    seen: set[tuple] = set()
    raw = data.get("intersections") if isinstance(data.get("intersections"), list) else []
    for c in raw:
        if not _cross_ok(c, thread_ids, main, members):
            continue
        k = (c["thread"], c["scene"], c["main_scene"])
        if k in seen:
            continue
        seen.add(k)
        cross.append({"thread": k[0], "scene": k[1], "main_scene": k[2], "reason": text(c.get("reason"))})
    return offsets, cross


# --- 6.5 找缺口 ---


def check_gaps(data: dict, ref_scenes: set[str], lines: dict[str, list[str]]) -> list[str]:
    gaps = data.get("gaps")
    if not isinstance(gaps, list):
        return ["缺少 gaps 列表"]
    problems: list[str] = []
    for i, g in enumerate(gaps, 1):
        if not isinstance(g, dict):
            problems.append(f"第 {i} 个缺口格式不对")
            continue
        if not text(g.get("event")):
            problems.append(f"第 {i} 个缺口没有 event")
        refs = str_list(g.get("mentioned_in"))
        if not refs or any(s not in ref_scenes for s in refs):
            problems.append(f"第 {i} 个缺口的 mentioned_in 只能用列出的出处编号，而且不能空")
        tid = g.get("thread")
        if tid is not None and tid not in lines:
            problems.append(f"第 {i} 个缺口的 thread「{tid}」不是这个世界的线")
        elif tid is not None:
            for k in ("after", "before"):
                if g.get(k) is not None and g.get(k) not in lines[tid]:
                    problems.append(f"第 {i} 个缺口的 {k} 不在 {tid} 里")
    return problems


def clean_gaps(data: dict, ref_scenes: set[str], lines: dict[str, list[str]]) -> list[dict]:
    out: list[dict] = []
    for g in data.get("gaps") or []:
        if not isinstance(g, dict):
            continue
        event = text(g.get("event"))
        refs = [s for s in dict.fromkeys(str_list(g.get("mentioned_in"))) if s in ref_scenes]
        if not event or not refs:
            continue
        tid = g.get("thread") if g.get("thread") in lines else None
        members = lines.get(tid, []) if tid else []
        after = g.get("after") if tid and g.get("after") in members else None
        before = g.get("before") if tid and g.get("before") in members else None
        out.append({"event": event, "mentioned_in": refs, "thread": tid, "after": after, "before": before})
    return out
```

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_threads_check.py -q`
Expected: 15 passed

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/threads_check.py tests/test_threads_check.py
git commit -m "feat: 归线输出检查——跨线对齐和找缺口"
```

---

## Task 8: 五个提示词 + 测试用的假回复

**Files:**
- Create: `prompts/threads_worlds.md`、`prompts/threads_lines.md`、`prompts/threads_order.md`、`prompts/threads_align.md`、`prompts/threads_gaps.md`
- Modify: `tests/helpers.py`（加 `listed_scenes`、`threads_handler`）
- Test: `tests/test_prompts.py`（追加）

要点：
- 格式同 `prompts/entities.md`：第一个标题前是写给人看的说明；`## system`、`## user` 两段；变量 `$名字`。
- 每个 system 里都带一个**识别词**，假回复靠它分辨是哪一种调用：「划分世界」「划分支线」「线内排序」「跨线对齐」「找缺口」。五个识别词互不包含，也不出现在场景卡、实体合并的提示词里。注意找缺口的 system 里有「场景卡」三个字，所以 `threads_handler` 要先认自己的识别词，认不出再交给 `fallback`。
- 每个 system 都要出现「json」并给示例（DeepSeek 的 JSON 模式要求）。
- 行的格式约定（`threads.py` 生成、假回复解析都靠它）：
  - 场景块一行一个，**行首**就是 `S-编号｜`；排序、对齐、缺口提示词里行首可以多一个 `[时间] `。
  - 已确认线的示例行前面有两个空格缩进，不算列出的块。
  - 对齐、缺口提示词里每条线一个标题行：`## L-001 线名`，主线后面加「（主线）」。
  - 片段一行一个：`- P-001：S-0001 → S-0002（同一个文件里紧挨着）`。
  - 缺口的出处一行一个：`- 事件｜S-0001`。

- [ ] **Step 1: 写失败的测试**

`tests/test_prompts.py` 末尾追加：
```python
import pytest

THREAD_PROMPTS = [
    ("threads_worlds", {"unit_rule": "x", "known": "k", "lines": "l"}, "划分世界"),
    ("threads_lines", {"world": "w", "locked": "k", "lines": "l"}, "划分支线"),
    ("threads_order", {"thread": "t", "unit": "年", "segments": "s", "lines": "l"}, "线内排序"),
    ("threads_align", {"unit": "年", "main": "L-001", "threads": "t"}, "跨线对齐"),
    ("threads_gaps", {"world": "w", "threads": "t", "refs": "r"}, "找缺口"),
]


@pytest.mark.parametrize("name,values,mark", THREAD_PROMPTS)
def test_threads_prompts_render(name, values, mark):
    from ligaotai.prompts import render

    system, user = render(name, **values)
    assert "json" in system and mark in system
    assert "$" not in system + user
    others = [m for _, _, m in THREAD_PROMPTS if m != mark]
    assert not any(m in system for m in others)


def test_threads_marks_not_in_older_prompts():
    from ligaotai.prompts import load_prompt

    for name in ("cards", "entities"):
        system, _ = load_prompt(name)
        assert not any(m in system.template for _, _, m in THREAD_PROMPTS)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_prompts.py -q`
Expected: 新测试 FAIL（`FileNotFoundError: ...threads_worlds.md`）

- [ ] **Step 3: 写五个提示词**

`prompts/threads_worlds.md`：
```markdown
# 归线：划分世界（步骤 6.1，综合档）

变量：$unit_rule（时间单位要提议还是照用）、$known（已有的世界）、$lines（每块一行）。

## system
你是一名熟悉中文小说的编辑助手，正在帮作者整理一部很乱的长篇手稿。下面每一行是手稿里的一个场景块：编号｜类型｜摘要｜人物｜地点｜组织｜世界线索｜时间线索（空的字段省略）。你的任务是划分世界：这部书里有几个彼此独立的「世界」（不同的时空、位面、平行宇宙；同一个世界里的不同地方不算不同世界），每个场景块属于哪个世界。

规则：
1. 大多数书只有一个世界。只有原文线索明确显示是不同的时空设定时才分开，拿不准就归到同一个世界。
2. 每个编号必须恰好出现一次，不许漏、不许重复、不许编造。
3. 类型是「设定笔记」「提纲」的块也要归到世界里。
4. 下面如果列了「已有的世界」，属于它的块写它的 id；新世界不写 id，写 name 和 reason。
5. reason 用一两句话说明这个世界的判定依据，引用原文线索。
6. $unit_rule

只输出一个 json 对象，格式如下（示例）：
{"time_unit": "年", "worlds": [
  {"name": "人间", "reason": "林清所在的青州、京城都属于同一朝代的人间", "scenes": ["S-0001", "S-0002"]},
  {"id": "W-01", "scenes": ["S-0003"]}
]}

## user
$known

场景块：
$lines
```

`prompts/threads_lines.md`：
```markdown
# 归线：划分支线（步骤 6.2，综合档）

变量：$world（世界名）、$locked（这个世界里已有的线）、$lines（每块一行）。

## system
你是一名熟悉中文小说的编辑助手。下面是手稿里属于「$world」这个世界的场景块，每行：编号｜类型｜摘要｜人物｜地点｜……（空的字段省略）。你的任务是划分支线：把讲同一条故事线（同一组主要人物、同一个事件链）的块聚成一条线。

规则：
1. 类型是「正文」「碎片」的块放进某条线的 scenes，每个恰好出现一次，不许漏、不许重复、不许编造。
2. 类型是「提纲」的块放进它讲的那条线的 outlines；说不清是哪条线的放进 world_outlines。
3. 恰好有一条线标 "main": true，它是这个世界的主线（通常是主角的主要经历、块最多的那条）。
4. 下面如果列了「已有的线」，块属于它就写它的 id（不用写 name）；新线不写 id，写 name 和 about。
5. name 是简短的线名（比如「林清入京」），about 用一句话说明这条线讲什么。
6. 线不要分得太碎：一两块的零星片段，能归进大线就归进大线。

只输出一个 json 对象，格式如下（示例）：
{"threads": [
  {"name": "林清入京", "about": "林清离开青州进京赶考的经历", "main": true, "scenes": ["S-0001", "S-0002"], "outlines": ["S-0009"]},
  {"id": "L-003", "scenes": ["S-0005"]}
], "world_outlines": []}

## user
$locked

场景块：
$lines
```

`prompts/threads_order.md`：
```markdown
# 归线：线内排序 + 故事时间（步骤 6.3，综合档）

变量：$thread（线名和说明）、$unit（时间单位）、$segments（片段说明）、$lines（每块一行）。

## system
你是一名熟悉中文小说的编辑助手。下面是支线「$thread」的全部场景块，每行：编号｜类型｜摘要｜……（空的字段省略）。这些块在手稿里是乱序的。你的任务是线内排序：按故事发生的先后排好顺序，并估计每块的故事时间。

规则：
1. order 是排好的顺序，每一项是一个片段编号（P- 开头）或一个场景编号（S- 开头）。
2. 片段是同一个文件里紧挨着的几块，原文顺序通常就是故事顺序：整段放进去就写片段编号。如果你判断片段内部接不上，可以不用片段编号，把它的块分别放。
3. 每个场景恰好出现一次（通过片段或者单独），不许漏、不许重复、不许编造。
4. times 给每个场景一个故事时间：[数值, 把握]。数值的单位是「$unit」，从这条线的开头算起（开头是 0），可以是小数；看不出来就写 null。把握只能是「高」「中」「低」。
5. end 说明这条线的结局：state 只能是「完结」或「待定」（写到一半、没收尾就是待定），note 用一句话说明写到哪停了。

只输出一个 json 对象，格式如下（示例）：
{"order": ["P-001", "S-0007", "S-0003"],
 "times": {"S-0001": [0, "高"], "S-0002": [0.1, "高"], "S-0007": [2, "中"], "S-0003": [null, "低"]},
 "end": {"state": "待定", "note": "写到林清抵达京城就停了"}}

## user
片段：
$segments

场景块：
$lines
```

`prompts/threads_align.md`：
```markdown
# 归线：跨线对齐（步骤 6.4，综合档）

变量：$unit（时间单位）、$main（主线编号）、$threads（每条线按顺序排好的块，行首方括号里是线内时间）。

## system
你是一名熟悉中文小说的编辑助手。下面是一部手稿里的各条支线，每条线的块已经按顺序排好，行首方括号里是线内故事时间（单位「$unit」，每条线从自己的开头算起，? 表示不知道）。你的任务是跨线对齐：以主线 $main 的时间为准，给每条线一个偏移（全书时间 = 线内时间 + 偏移），并找出每条线和主线的交汇点。

规则：
1. threads 里每条线恰好出现一次；主线的 offset 写 0。
2. 依据共同事件、共同出场人物、原文里的时间线索对齐。完全找不到依据的线 offset 写 null，不要硬凑。
3. intersections 列出支线和主线交汇的地方：thread 是支线编号，scene 是这条支线里的块，main_scene 是主线里对应的块，reason 用一句话说明（比如「两处写的是同一场婚宴」）。没有就给空列表。

只输出一个 json 对象，格式如下（示例）：
{"threads": [{"id": "L-001", "offset": 0}, {"id": "L-002", "offset": 3.5}, {"id": "L-004", "offset": null}],
 "intersections": [{"thread": "L-002", "scene": "S-0150", "main_scene": "S-0004", "reason": "两处写的是同一场婚宴"}]}

## user
$threads
```

`prompts/threads_gaps.md`：
```markdown
# 归线：找缺口（步骤 6.5，综合档）

变量：$world（世界名）、$threads（这个世界的线，块已按顺序排好）、$refs（场景卡里提到但本块没写的事件）。

## system
你是一名熟悉中文小说的编辑助手。下面是手稿里「$world」这个世界的各条支线（块已按顺序排好），以及场景卡里记下的「提到但本块没写的事件」。你的任务是找缺口：哪些被提到的事件，在全部场景里都找不到对应的描写。

规则：
1. 只有确实找不到对应场景的事件才算缺口；某个块已经写了这件事，就不是缺口。
2. 同一件事被好几块提到，合成一个缺口，mentioned_in 列出全部提到它的块（只能用下面列出的出处编号）。
3. thread 写这件事应该属于哪条线；after / before 写它大概应该插在这条线的哪两块之间（在开头就 after 写 null，在结尾就 before 写 null）；判断不了就都写 null。
4. event 用一句话写这件事，尽量用原文的说法。

只输出一个 json 对象，格式如下（示例）：
{"gaps": [{"event": "青州城破", "mentioned_in": ["S-0150", "S-0161"], "thread": "L-001", "after": "S-0004", "before": "S-0120"}]}
没有缺口就输出 {"gaps": []}。

## user
各条支线：
$threads

提到但没写的事件（事件｜出处）：
$refs
```

- [ ] **Step 4: helpers 加步骤 6 的假回复**

`tests/helpers.py` 顶部 import 区加 `import re`；文件末尾追加：
```python
_LISTED = re.compile(r"^(?:\[[^\]]*\] )?(S-\d{4,})｜", re.M)
_THREAD_HEAD = re.compile(r"^## (L-\d+)", re.M)


def listed_scenes(messages) -> list[str]:
    """归线提示词 user 消息里列出的场景编号（行首的 S-编号｜，缩进的示例行不算）。"""
    return _LISTED.findall(messages[1]["content"])


def threads_handler(worlds=None, lines=None, order=None, align=None, gaps=None, fallback=None):
    """步骤 6 各次调用的假回复。每个参数是 fn(messages) -> 回复（字符串 / Reply / 异常实例）；不给就用默认：
    全部归一个世界「世界一」、正文碎片全归一条主线（提纲挂上去）、按列出的顺序排、偏移都是 0、没有缺口。
    认不出的提示词交给 fallback（比如 fake_ai_handler()），没有 fallback 就报错。"""

    def d_worlds(m):
        return json.dumps(
            {"time_unit": "年", "worlds": [{"name": "世界一", "reason": "测试", "scenes": listed_scenes(m)}]},
            ensure_ascii=False,
        )

    def d_lines(m):
        user = m[1]["content"]
        ids = listed_scenes(m)
        outl = [i for i in ids if f"{i}｜提纲" in user]
        sc = [i for i in ids if i not in outl]
        threads = [{"name": "主线", "about": "测试", "main": True, "scenes": sc, "outlines": outl}] if sc else []
        return json.dumps({"threads": threads, "world_outlines": [] if sc else outl}, ensure_ascii=False)

    def d_order(m):
        ids = listed_scenes(m)
        return json.dumps(
            {"order": ids, "times": {s: [i, "高"] for i, s in enumerate(ids)}, "end": {"state": "待定", "note": "测试"}},
            ensure_ascii=False,
        )

    def d_align(m):
        tids = _THREAD_HEAD.findall(m[1]["content"])
        return json.dumps({"threads": [{"id": t, "offset": 0} for t in tids], "intersections": []})

    def d_gaps(m):
        return '{"gaps": []}'

    table = [
        ("划分世界", worlds or d_worlds),
        ("划分支线", lines or d_lines),
        ("线内排序", order or d_order),
        ("跨线对齐", align or d_align),
        ("找缺口", gaps or d_gaps),
    ]

    def handler(tier, messages):
        system = messages[0]["content"]
        for mark, fn in table:
            if mark in system:
                return fn(messages)
        if fallback is not None:
            return fallback(tier, messages)
        raise AssertionError("没见过的提示词")

    return handler
```

- [ ] **Step 5: 跑测试**

Run: `uv run pytest tests/test_prompts.py -q`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add prompts/threads_worlds.md prompts/threads_lines.md prompts/threads_order.md prompts/threads_align.md prompts/threads_gaps.md tests/helpers.py tests/test_prompts.py
git commit -m "feat: 归线五个提示词 + 测试用的假回复"
```

---
## Task 9: threads.py——调用器 + 划世界

**Files:**
- Create: `src/ligaotai/threads.py`
- Test: `tests/test_threads.py`

要点：
- **Caller**：一次运行里所有模型调用共用。
  - 按「提示词全文 + 综合档配置」查缓存 `归线缓存.json`，命中就不调模型；没命中就调综合档 `chat_json`，结果连同剩下的问题写进缓存（写缓存失败不影响这次调用）。
  - `LLMError`（这一次调用失败）记进 `failed`，返回 None；`FatalLLMError`（欠费、key 失效）直接往外抛。
  - 每次调用完调一次 `progress(done, total)`，这也是暂停检查点；`plan(n)` 把总数加 n（总数随阶段增长）。
  - 缓存条目：`{"data": 模型输出（检查过的最好一版）, "problems": [...]}`；清理放在调用方。
- **划世界**（②b 设计 2.1）：
  - 已确认的世界作为「已有的世界」列给模型（键就是 `W-xx`）。新世界在这一阶段用临时键 `N1`、`N2`……，按创建顺序编（各段依次调用，所以编号是确定的）。
  - 输入超过预算就用 `split_by_budget` 分段依次调用，后一段带上前面已有的世界（含 N 键）。
  - 时间单位：传进来的 `unit` 非空就告诉模型照用，不要求它填；空的就让它提议，第一段给出的单位定下来后，后面几段照用。
  - 某一段调用失败，那一段的块全算漏掉；**所有段都失败**就抛 `LLMError`，整步失败。

- [ ] **Step 1: 写失败的测试**

`tests/test_threads.py`：
```python
import asyncio
import json

import pytest
from helpers import FakeBackend, listed_scenes, seed_book, threads_handler

from ligaotai.config import AppConfig
from ligaotai.llm import FatalLLMError, LLMClient, LLMError
from ligaotai.threads import Caller, WorldDraft, stage_worlds
from ligaotai.threads_input import Item


def client(book, **handlers):
    return LLMClient(AppConfig(), FakeBackend(handler=threads_handler(**handlers)), log_dir=book.logs_dir)


def items_of(*specs):
    """specs：场景编号，或者 (编号, 类型)。都在 a.txt 里，位置按顺序。"""
    out = {}
    for i, s in enumerate(specs):
        sid, kind = (s, "正文") if isinstance(s, str) else s
        out[sid] = Item(sid, "a.txt", i, kind, f"{sid}｜{kind}｜摘要{sid}")
    return out


def users(c, mark):
    """某一种调用发出去的全部 user 消息（按调用顺序）。"""
    return [x["messages"][1]["content"] for x in c.backend.calls if mark in x["messages"][0]["content"]]


GAPS_ARGS = {"world": "w", "threads": "t", "refs": "r"}


# --- 调用器 ---


def test_caller_caches(book):
    c = client(book)
    caller = Caller(book, c, lambda *a: None)

    async def go():
        caller.plan(2)
        a = await caller.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x")
        b = await caller.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x")
        return a, b

    a, b = asyncio.run(go())
    assert a == b == {"gaps": []}
    assert c.usage.calls == 1 and (caller.done, caller.total) == (2, 2)
    assert len(json.loads(book.threads_cache_path.read_text(encoding="utf-8"))) == 1
    again = Caller(book, client(book), lambda *a: None)
    assert asyncio.run(again.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x")) == {"gaps": []}
    assert again.client.usage.calls == 0


def test_caller_records_failure_and_raises_fatal(book):
    caller = Caller(book, client(book, gaps=lambda m: LLMError("坏了")), lambda *a: None)
    assert asyncio.run(caller.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x")) is None
    assert caller.failed == [{"call": "gaps-x", "error": "坏了"}]
    fatal = Caller(book, client(book, gaps=lambda m: FatalLLMError("欠费")), lambda *a: None)
    with pytest.raises(FatalLLMError):
        asyncio.run(fatal.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x"))


def test_caller_records_unresolved(book):
    caller = Caller(book, client(book), lambda *a: None)
    asyncio.run(caller.call("threads_gaps", GAPS_ARGS, lambda d: ["还是不对"], "gaps-x"))
    assert caller.unresolved == [{"call": "gaps-x", "problems": ["还是不对"]}]
    assert caller.client.usage.calls == 3


def test_caller_progress_is_a_pause_point(book):
    from ligaotai.jobs import JobCancelled

    def progress(done, total, *a):
        if done >= 1:
            raise JobCancelled("已暂停")

    caller = Caller(book, client(book), progress)
    with pytest.raises(JobCancelled):
        asyncio.run(caller.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x"))
    assert book.threads_cache_path.exists()  # 暂停前做完的调用已经进了缓存


# --- 划世界 ---


def worlds_of(book, items, known=(), unit="", budget=10**6, **handlers):
    c = client(book, **handlers)
    caller = Caller(book, c, lambda *a: None)
    got = asyncio.run(stage_worlds(caller, list(items.values()), list(known), unit, budget))
    return got, c, caller


def test_stage_worlds_default(book):
    (worlds, missing, unit), c, _ = worlds_of(book, items_of("S-0001", "S-0002"))
    assert [(w.key, w.name, w.scenes) for w in worlds] == [("N1", "世界一", ["S-0001", "S-0002"])]
    assert (missing, unit, c.usage.calls) == ([], "年", 1)
    assert "time_unit 填一个" in c.backend.calls[0]["messages"][0]["content"]


def test_stage_worlds_known_world_and_fixed_unit(book):
    def reply(m):
        return json.dumps({"time_unit": "年", "worlds": [
            {"id": "W-01", "scenes": ["S-0001"]}, {"name": "天界", "reason": "r", "scenes": ["S-0002"]},
        ]}, ensure_ascii=False)

    known = [WorldDraft("W-01", "人间", "旧依据")]
    (worlds, missing, unit), c, _ = worlds_of(book, items_of("S-0001", "S-0002"), known, unit="天", worlds=reply)
    assert [(w.key, w.name, w.scenes) for w in worlds] == [("W-01", "人间", ["S-0001"]), ("N1", "天界", ["S-0002"])]
    assert unit == "天"
    assert "已经定为「天」" in c.backend.calls[0]["messages"][0]["content"]
    assert "- W-01 人间：旧依据" in users(c, "划分世界")[0]


def test_stage_worlds_chunks_carry_earlier_worlds(book):
    def reply(m):
        ids = listed_scenes(m)
        if "N1 世界一" in m[1]["content"]:
            return json.dumps({"worlds": [{"id": "N1", "scenes": ids}]})
        return json.dumps({"time_unit": "年", "worlds": [{"name": "世界一", "reason": "r", "scenes": ids}]}, ensure_ascii=False)

    items = items_of("S-0001", "S-0002", "S-0003")
    (worlds, missing, unit), c, _ = worlds_of(book, items, budget=20, worlds=reply)
    assert c.usage.calls == 3
    assert [(w.key, w.scenes) for w in worlds] == [("N1", ["S-0001", "S-0002", "S-0003"])]
    assert "已经定为「年」" in c.backend.calls[1]["messages"][0]["content"]


def test_stage_worlds_missing_scenes(book):
    reply = lambda m: json.dumps({"time_unit": "年", "worlds": [{"name": "甲", "scenes": ["S-0001"]}]}, ensure_ascii=False)
    (worlds, missing, _), c, caller = worlds_of(book, items_of("S-0001", "S-0002"), worlds=reply)
    assert missing == ["S-0002"] and c.usage.calls == 3 and caller.unresolved


def test_stage_worlds_all_failed_raises(book):
    with pytest.raises(LLMError):
        worlds_of(book, items_of("S-0001"), worlds=lambda m: LLMError("坏了"))


def test_stage_worlds_one_chunk_failed(book):
    def reply(m):
        if "S-0002" in listed_scenes(m):
            return LLMError("坏了")
        return json.dumps({"time_unit": "年", "worlds": [{"name": "甲", "scenes": listed_scenes(m)}]}, ensure_ascii=False)

    (worlds, missing, _), _, caller = worlds_of(book, items_of("S-0001", "S-0002"), budget=20, worlds=reply)
    assert [w.scenes for w in worlds] == [["S-0001"]] and missing == ["S-0002"] and len(caller.failed) == 1


def test_stage_worlds_nothing_free(book):
    known = [WorldDraft("W-01", "人间")]
    (worlds, missing, unit), c, _ = worlds_of(book, {}, known, unit="年")
    assert [w.key for w in worlds] == ["W-01"] and c.usage.calls == 0 and unit == "年"
```

每个场景行是 `S-000x｜正文｜摘要S-000x`，18 个字符，加换行算 19；`budget=20` 时每段只装得下一行，三行就是三段。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_threads.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'ligaotai.threads'`）

- [ ] **Step 3: 实现**

`src/ligaotai/threads.py`：
```python
"""步骤 6 归线排序：划世界 → 划支线 → 线内排序 → 跨线对齐 → 找缺口，结果写 世界与支线.json。

- 输入由 threads_input.prepare 准备：只取主版本块，每张卡压成一行，人名地名换成规范名。
- 每次模型调用走综合档，结果按「提示词全文 + 综合档配置」缓存进 归线缓存.json：暂停、崩溃、
  重跑时输入没变的调用都不再花钱。
- 作者确认过（或动过）的线和世界原样保留，里面的块不进模型的输入；模型想往已确认的线里加块，
  放进 pending 等作者点头。
- 开跑时和跑完各算一次输入指纹，不一样（跑的途中作者改了实体、换了主版本……）就把这一步记成
  outdated，不记 done；跑的途中作者动了 世界与支线.json，这次结果不写入，也记 outdated。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .book import Book
from .fsutil import read_json, write_json
from .llm import FatalLLMError, LLMClient, LLMError, cache_config, cache_key
from .prompts import render
from .threads_check import check_worlds, clean_worlds
from .threads_input import Item, split_by_budget

DRAFT, CONFIRMED = "draft", "confirmed"
MISSED = "模型没分配"
UNIT_PROPOSE = "time_unit 填一个适合本书的故事时间单位（「年」「月」「天」等），全书统一用它。"
UNIT_FIXED = "故事时间单位已经定为「{unit}」，time_unit 照填「{unit}」。"

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


def load_cache(book: Book) -> dict[str, dict]:
    """缓存坏了就当没有：大不了重新调一遍模型。形状不对的条目丢掉。"""
    try:
        data = read_json(book.threads_cache_path, {})
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        k: v
        for k, v in data.items()
        if isinstance(v, dict) and isinstance(v.get("data"), dict) and isinstance(v.get("problems"), list)
    }


class Caller:
    """一次运行里所有模型调用共用：缓存、失败清单、没解决的问题、进度。"""

    def __init__(self, book: Book, client: LLMClient, progress: Progress):
        self.book = book
        self.client = client
        self.progress = progress
        self.cfg = cache_config(client, "synth")
        self.cache = load_cache(book)
        self.used: set[str] = set()
        self.failed: list[dict] = []
        self.unresolved: list[dict] = []
        self.done = 0
        self.total = 0

    def plan(self, n: int) -> None:
        """又要调 n 次：总数加上去（进度条的分母随阶段增长）。"""
        self.total += n
        self.progress(self.done, self.total)

    async def call(self, prompt: str, values: dict, check, tag: str) -> dict | None:
        system, user = render(prompt, **values)
        key = cache_key(system, user, self.cfg)
        entry = self.cache.get(key)
        if entry is None:
            try:
                data, problems = await self.client.chat_json("synth", system, user, check, tag=f"threads/{tag}")
            except FatalLLMError:
                raise
            except LLMError as e:  # 这一次调用失败，由调用方决定怎么兜底
                self.failed.append({"call": tag, "error": str(e)})
            else:
                entry = self.cache[key] = {"data": data, "problems": problems}
                try:
                    write_json(self.book.threads_cache_path, self.cache)
                except OSError:
                    pass  # 缓存写失败不该让已经花了钱的这次调用也跟着失败
        if entry is not None:
            self.used.add(key)
            if entry["problems"]:
                self.unresolved.append({"call": tag, "problems": list(entry["problems"])[:5]})
        self.done += 1
        self.progress(self.done, self.total)  # 暂停检查点：做完的调用都在缓存里
        return entry["data"] if entry is not None else None

    def prune_cache(self) -> None:
        """跑成功了：这次没用到的缓存条目清掉，免得越积越多。"""
        if set(self.cache) - self.used:
            try:
                write_json(self.book.threads_cache_path, {k: v for k, v in self.cache.items() if k in self.used})
            except OSError:
                pass


# --- 6.1 划世界 ---


@dataclass
class WorldDraft:
    key: str  # 已确认世界的 id，或者这次新建的临时键 N1、N2……
    name: str
    reason: str = ""
    scenes: list[str] = field(default_factory=list)  # 这次分给它的块


def known_worlds_text(worlds: list[WorldDraft]) -> str:
    if not worlds:
        return "已有的世界：（无）"
    return "已有的世界：\n" + "\n".join(f"- {w.key} {w.name}：{w.reason}" for w in worlds)


async def stage_worlds(
    caller: Caller, free: list[Item], known: list[WorldDraft], unit: str, budget: int
) -> tuple[list[WorldDraft], list[str], str]:
    """划世界。known：已确认的世界（锁定，新块可以归进去）。返回 (全部世界, 漏掉的块, 时间单位)。"""
    worlds = [WorldDraft(w.key, w.name, w.reason) for w in known]
    if not free:
        return worlds, [], unit
    line_of = {it.id: it.line for it in free}
    chunks = split_by_budget(list(line_of), {i: len(v) + 1 for i, v in line_of.items()}, budget)
    caller.plan(len(chunks))
    missing: list[str] = []
    failed = 0
    for no, chunk in enumerate(chunks, 1):
        keys = {w.key for w in worlds}
        need_unit = not unit
        expected = set(chunk)
        values = {
            "unit_rule": UNIT_PROPOSE if need_unit else UNIT_FIXED.format(unit=unit),
            "known": known_worlds_text(worlds),
            "lines": "\n".join(line_of[i] for i in chunk),
        }
        data = await caller.call(
            "threads_worlds", values, lambda d: check_worlds(d, expected, keys, need_unit), f"worlds-{no}"
        )
        if data is None:
            failed += 1
            missing += chunk
            continue
        got, miss, got_unit = clean_worlds(data, expected, keys)
        missing += miss
        unit = unit or got_unit
        by_key = {w.key: w for w in worlds}
        for g in got:
            if g["key"] is not None:
                by_key[g["key"]].scenes += g["scenes"]
            else:
                worlds.append(WorldDraft(f"N{sum(w.key.startswith('N') for w in worlds) + 1}", g["name"], g["reason"], g["scenes"]))
    if failed == len(chunks):
        raise LLMError(f"划世界失败：{caller.failed[-1]['error']}")
    return worlds, missing, unit
```

注意 `test_stage_worlds_chunks_carry_earlier_worlds`：第一段的 user 里是「已有的世界：（无）」，回复新建「世界一」→ N1；第二、三段 user 里有「- N1 世界一：r」，回复归进 N1。临时键用「已有几个 N 开头的键 + 1」来编，已确认世界的键是 `W-` 开头，不会撞。

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_threads.py -q`
Expected: 11 passed

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/threads.py tests/test_threads.py
git commit -m "feat: 归线调用器（缓存/失败/进度）和划世界"
```

---

## Task 10: threads.py——划支线

**Files:**
- Modify: `src/ligaotai/threads.py`（追加）
- Test: `tests/test_threads.py`（追加）

要点（②b 设计 2.2）：
- 一个世界一次调用；只送正文、碎片、提纲，设定笔记不送（它们只挂世界，由组装那一步处理）。
- 这个世界里已确认的线作为「已有的线」列给模型：`- L-003 线名：说明`，下面带最多 3 行它的块（两个空格缩进，不算列出的块；没有卡的块不显示）。
- 模型把块归进已确认的线 → 不改那条线，放进 pending（`{"scene", "thread", "reason": "模型建议归入已确认的线"}`）。
- 新线用临时键 `<世界键>#<n>`（比如 `W-02#1`），组装时再换成正式编号。一个世界的行超过预算就分段依次调用，前面几段新建的线也列进后面几段的「已有的线」，归进它们就直接加进去。
- 这个世界的主线：第一个被标 main 的线（可能是已确认线的 id）。
- 调用失败：这一段的正文 / 碎片进 missing，提纲挂世界。

- [ ] **Step 1: 写失败的测试**

`tests/test_threads.py` 末尾追加：
```python
from ligaotai.threads import ThreadDraft, stage_lines


def lines_of(book, world, items, locked=(), budget=10**6, **handlers):
    c = client(book, **handlers)
    caller = Caller(book, c, lambda *a: None)
    return asyncio.run(stage_lines(caller, world, items, list(locked), budget)), c, caller


def test_stage_lines_default(book):
    items = items_of("S-0001", ("S-0002", "碎片"), ("S-0003", "提纲"), ("S-0004", "设定笔记"))
    world = WorldDraft("W-01", "人间", scenes=list(items))
    res, c, _ = lines_of(book, world, items)
    assert [(t.key, t.world, t.name, t.scenes, t.outlines) for t in res.threads] == [
        ("W-01#1", "W-01", "主线", ["S-0001", "S-0002"], ["S-0003"]),
    ]
    assert res.main == "W-01#1" and res.pending == [] and res.world_outlines == [] and res.missing == []
    user = users(c, "划分支线")[0]
    assert "S-0004" not in user and "已有的线：（无）" in user


def test_stage_lines_locked_thread_gets_pending(book):
    items = items_of("S-0001", "S-0002", "S-0009")
    locked = [ThreadDraft("L-003", "W-01", "旧线", "旧说明", scenes=["S-0009", "S-0404"], locked=True)]

    def reply(m):
        return json.dumps({"threads": [
            {"id": "L-003", "main": True, "scenes": ["S-0001"]},
            {"name": "新线", "about": "a", "scenes": ["S-0002"]},
        ]}, ensure_ascii=False)

    world = WorldDraft("W-01", "人间", scenes=["S-0001", "S-0002"])
    res, c, _ = lines_of(book, world, items, locked, lines=reply)
    assert res.pending == [{"scene": "S-0001", "thread": "L-003", "reason": "模型建议归入已确认的线"}]
    assert [(t.key, t.scenes) for t in res.threads] == [("W-01#1", ["S-0002"])]
    assert res.main == "L-003"
    user = users(c, "划分支线")[0]
    assert "- L-003 旧线：旧说明" in user and "  S-0009｜正文" in user and "S-0404" not in user


def test_stage_lines_chunks_carry_new_threads(book):
    def reply(m):
        ids = listed_scenes(m)
        if "W-01#1" in m[1]["content"]:
            return json.dumps({"threads": [{"id": "W-01#1", "main": True, "scenes": ids}]})
        return json.dumps({"threads": [{"name": "甲", "main": True, "scenes": ids}]}, ensure_ascii=False)

    items = items_of("S-0001", "S-0002")
    world = WorldDraft("W-01", "人间", scenes=list(items))
    res, c, _ = lines_of(book, world, items, budget=20, lines=reply)
    assert c.usage.calls == 2
    assert [(t.key, t.scenes) for t in res.threads] == [("W-01#1", ["S-0001", "S-0002"])]


def test_stage_lines_failed_call(book):
    items = items_of("S-0001", ("S-0002", "提纲"))
    world = WorldDraft("W-01", "人间", scenes=list(items))
    res, _, caller = lines_of(book, world, items, lines=lambda m: LLMError("坏了"))
    assert res.threads == [] and res.missing == ["S-0001"] and res.world_outlines == ["S-0002"]
    assert len(caller.failed) == 1


def test_stage_lines_only_outlines_or_notes(book):
    items = items_of(("S-0001", "提纲"), ("S-0002", "设定笔记"))
    res, c, _ = lines_of(book, WorldDraft("W-01", "人间", scenes=["S-0001"]), items)
    assert res.threads == [] and res.world_outlines == ["S-0001"]
    res2, c2, _ = lines_of(book, WorldDraft("W-01", "人间", scenes=["S-0002"]), items)
    assert res2.threads == [] and c2.usage.calls == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_threads.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'ThreadDraft'`）

- [ ] **Step 3: 实现**

`src/ligaotai/threads.py`：
- import 区：`from .fsutil import read_json, write_json` 改成 `from .fsutil import natural_key, read_json, write_json`；`from .threads_check import check_worlds, clean_worlds` 改成 `from .threads_check import check_lines, check_worlds, clean_lines, clean_worlds`；`from .threads_input import Item, split_by_budget` 改成 `from .threads_input import ORDERED_KINDS, OUTLINE, Item, split_by_budget`
- 常量区加：
```python
PENDING = "模型建议归入已确认的线"
LOCKED_EXAMPLES = 3  # 已有的线在提示词里带几行示例
```
- 文件末尾追加：
```python
# --- 6.2 划支线 ---


@dataclass
class ThreadDraft:
    key: str  # 已确认线的 id，或者临时键 <世界键>#<n>（组装时换成正式编号）
    world: str
    name: str
    about: str = ""
    scenes: list[str] = field(default_factory=list)
    outlines: list[str] = field(default_factory=list)
    times: dict = field(default_factory=dict)
    end: dict = field(default_factory=dict)
    order_failed: bool = False
    locked: bool = False


def known_threads_text(threads: list[ThreadDraft], items: dict[str, Item]) -> str:
    if not threads:
        return "已有的线：（无）"
    out = ["已有的线（块属于它就写它的 id）："]
    for t in threads:
        out.append(f"- {t.key} {t.name}：{t.about}" if t.about else f"- {t.key} {t.name}")
        out += [f"  {items[s].line}" for s in t.scenes if s in items][:LOCKED_EXAMPLES]
    return "\n".join(out)


@dataclass
class LinesResult:
    threads: list[ThreadDraft] = field(default_factory=list)  # 新线
    main: str | None = None  # 这个世界的主线的键（可能是已确认线的 id）
    pending: list[dict] = field(default_factory=list)
    world_outlines: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


async def stage_lines(
    caller: Caller, world: WorldDraft, items: dict[str, Item], locked: list[ThreadDraft], budget: int
) -> LinesResult:
    """划支线（一个世界一次，太大就分段）。locked：这个世界里已确认的线。"""
    res = LinesResult()
    ids = [s for s in world.scenes if items[s].kind in ORDERED_KINDS or items[s].kind == OUTLINE]
    if not ids:
        return res
    locked_keys = {t.key for t in locked}
    chunks = split_by_budget(ids, {s: len(items[s].line) + 1 for s in ids}, budget)
    caller.plan(len(chunks))
    for no, chunk in enumerate(chunks, 1):
        ref = locked + res.threads
        known = {t.key for t in ref}
        exp_o = {s for s in chunk if items[s].kind in ORDERED_KINDS}
        exp_l = {s for s in chunk if items[s].kind == OUTLINE}
        values = {
            "world": world.name,
            "locked": known_threads_text(ref, items),
            "lines": "\n".join(items[s].line for s in chunk),
        }
        data = await caller.call(
            "threads_lines", values, lambda d: check_lines(d, exp_o, exp_l, known), f"lines-{world.key}-{no}"
        )
        if data is None:
            res.missing += sorted(exp_o, key=natural_key)
            res.world_outlines += sorted(exp_l, key=natural_key)
            continue
        got = clean_lines(data, exp_o, exp_l, known)
        res.missing += got["missing"]
        res.world_outlines += got["world_outlines"]
        by_key = {t.key: t for t in res.threads}
        for g in got["threads"]:
            if g["key"] in locked_keys:
                key = g["key"]
                res.pending += [{"scene": s, "thread": key, "reason": PENDING} for s in g["scenes"] + g["outlines"]]
            elif g["key"] in by_key:
                t = by_key[g["key"]]
                t.scenes += g["scenes"]
                t.outlines += g["outlines"]
                key = t.key
            else:
                t = ThreadDraft(f"{world.key}#{len(res.threads) + 1}", world.key, g["name"], g["about"], g["scenes"], g["outlines"])
                res.threads.append(t)
                by_key[t.key] = t
                key = t.key
            if g["main"] and res.main is None:
                res.main = key
    return res
```

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_threads.py -q`
Expected: 16 passed

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/threads.py tests/test_threads.py
git commit -m "feat: 归线划支线（已确认的线进 pending，大世界分段）"
```

---
## Task 11: threads.py——线内排序

**Files:**
- Modify: `src/ligaotai/threads.py`（追加）
- Test: `tests/test_threads.py`（追加）

要点（②b 设计 2.3，本计划开头决定 4）：
- 一条新线一次调用（已确认的线不排）。直接改这条线的 `scenes` / `times` / `end` / `order_failed`，返回漏掉的块。
- 片段：`segments()` 算出来的、两块及以上的，编成 `P-001`、`P-002`……（只在这次调用里有效）。提示词里的「场景块」按片段顺序（源文件 + 文件内位置）列。
- 只有一块的线不调模型：时间记 0、把握「低」，结局「待定」。
- 调用失败：按「源文件 + 文件内位置」暂排，`order_failed = True`，没有时间，结局「待定」。

- [ ] **Step 1: 写失败的测试**

`tests/test_threads.py` 末尾追加：
```python
from ligaotai.threads import stage_order


def order_items():
    """S-0001、S-0002 是 b.txt 里挨着的两块（一个片段），S-0003 在 a.txt。"""
    return {
        "S-0001": Item("S-0001", "b.txt", 0, "正文", "S-0001｜正文｜甲"),
        "S-0002": Item("S-0002", "b.txt", 1, "正文", "S-0002｜正文｜乙"),
        "S-0003": Item("S-0003", "a.txt", 0, "正文", "S-0003｜正文｜丙"),
    }


def order_of(book, scenes, **handlers):
    c = client(book, **handlers)
    caller = Caller(book, c, lambda *a: None)
    t = ThreadDraft("W-01#1", "W-01", "主线", "说明", scenes=list(scenes))
    missing = asyncio.run(stage_order(caller, t, order_items(), "年"))
    return t, missing, c


def test_stage_order_default(book):
    t, missing, c = order_of(book, ["S-0001", "S-0002", "S-0003"])
    user = users(c, "线内排序")[0]
    assert "- P-001：S-0001 → S-0002（同一个文件里紧挨着）" in user
    assert user.index("S-0003｜") < user.index("S-0001｜")  # 场景块按片段顺序列：a.txt 在 b.txt 前面
    assert t.scenes == ["S-0003", "S-0001", "S-0002"] and missing == []
    assert t.times == {"S-0003": {"t": 0, "conf": "高"}, "S-0001": {"t": 1, "conf": "高"}, "S-0002": {"t": 2, "conf": "高"}}
    assert t.end == {"state": "待定", "note": "测试"} and t.order_failed is False
    assert "「主线（说明）」" in c.backend.calls[0]["messages"][0]["content"]


def test_stage_order_uses_segment_ids(book):
    def reply(m):
        return json.dumps({"order": ["P-001", "S-0003"], "times": {"S-0001": [0, "高"], "S-0002": [1, "高"], "S-0003": [5, "中"]},
                           "end": {"state": "完结", "note": "收尾了"}}, ensure_ascii=False)

    t, missing, _ = order_of(book, ["S-0001", "S-0002", "S-0003"], order=reply)
    assert t.scenes == ["S-0001", "S-0002", "S-0003"] and t.end["state"] == "完结"


def test_stage_order_missing_scene(book):
    def reply(m):
        return json.dumps({"order": ["P-001"], "times": {"S-0001": [0, "高"], "S-0002": [1, "高"]},
                           "end": {"state": "待定", "note": ""}}, ensure_ascii=False)

    t, missing, c = order_of(book, ["S-0001", "S-0002", "S-0003"], order=reply)
    assert t.scenes == ["S-0001", "S-0002"] and missing == ["S-0003"] and c.usage.calls == 3


def test_stage_order_failed_falls_back_to_file_order(book):
    t, missing, _ = order_of(book, ["S-0001", "S-0002", "S-0003"], order=lambda m: LLMError("坏了"))
    assert t.scenes == ["S-0003", "S-0001", "S-0002"] and t.order_failed is True
    assert t.times == {} and t.end == {"state": "待定", "note": ""} and missing == []


def test_stage_order_single_scene_needs_no_call(book):
    t, missing, c = order_of(book, ["S-0002"])
    assert c.usage.calls == 0 and t.scenes == ["S-0002"]
    assert t.times == {"S-0002": {"t": 0, "conf": "低"}} and t.end == {"state": "待定", "note": ""}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_threads.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'stage_order'`）

- [ ] **Step 3: 实现**

`src/ligaotai/threads.py`：
- import：`from .threads_check import ...` 加上 `check_order, clean_order`；`from .threads_input import ...` 加上 `segments`
- 文件末尾追加：
```python
# --- 6.3 线内排序 ---


def segments_text(segs: dict[str, list[str]]) -> str:
    if not segs:
        return "（无）"
    return "\n".join(f"- {p}：{' → '.join(ss)}（同一个文件里紧挨着）" for p, ss in segs.items())


async def stage_order(caller: Caller, t: ThreadDraft, items: dict[str, Item], unit: str) -> list[str]:
    """线内排序（一条线一次）。直接改 t 的 scenes / times / end / order_failed，返回漏掉的块。"""
    parts = segments(t.scenes, items)
    fallback = [s for p in parts for s in p]
    if len(fallback) <= 1:
        t.scenes = fallback
        t.times = {s: {"t": 0, "conf": "低"} for s in fallback}
        t.end = {"state": "待定", "note": ""}
        return []
    segs = {f"P-{i:03d}": p for i, p in enumerate((p for p in parts if len(p) > 1), 1)}
    expected = set(fallback)
    values = {
        "thread": f"{t.name}（{t.about}）" if t.about else t.name,
        "unit": unit or "年",
        "segments": segments_text(segs),
        "lines": "\n".join(items[s].line for s in fallback),
    }
    caller.plan(1)
    data = await caller.call("threads_order", values, lambda d: check_order(d, segs, expected), f"order-{t.key}")
    if data is None:
        t.scenes, t.times, t.order_failed = fallback, {}, True
        t.end = {"state": "待定", "note": ""}
        return []
    got = clean_order(data, segs, expected, fallback)
    t.scenes, t.times, t.end = got["scenes"], got["times"], got["end"]
    return got["missing"]
```

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_threads.py -q`
Expected: 21 passed

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/threads.py tests/test_threads.py
git commit -m "feat: 归线线内排序（片段、失败按原稿位置暂排）"
```

---

## Task 12: threads.py——跨线对齐 + 找缺口

**Files:**
- Modify: `src/ligaotai/threads.py`（追加）
- Test: `tests/test_threads.py`（追加）

要点（②b 设计 2.4、2.5）：
- 每条线在提示词里是一段：标题行 `## L-001 线名`（主线加「（主线）」），下面每块一行 `[线内时间] 行`，时间不知道写 `?`；没有卡的块只写编号。
- **对齐**（全书一次）：没有主线 → 全部偏移 null，不调；只有一条线 → 主线偏移 0，不调；输入超过预算 → 跳过、记失败；调用失败 → 主线 0、其他 null、没有交汇点。
- **缺口**（每个世界一次）：这个世界所有块（线里的块、提纲、设定笔记）的 refs 都送；没有 refs 或者没有线就不调；超过预算跳过、记失败；调用失败返回空。结果每条加上 `"world"`。

- [ ] **Step 1: 写失败的测试**

`tests/test_threads.py` 末尾追加：
```python
from ligaotai.threads import stage_align, stage_gaps, thread_block


def two_threads():
    items = items_of("S-0001", "S-0002", "S-0003")
    a = ThreadDraft("L-001", "W-01", "甲", scenes=["S-0001", "S-0002"], times={"S-0001": {"t": 0, "conf": "高"}})
    b = ThreadDraft("L-002", "W-01", "乙", scenes=["S-0003", "S-0404"])
    return items, a, b


def test_thread_block():
    items, a, b = two_threads()
    assert thread_block(a, items, main=True) == "## L-001 甲（主线）\n[0] S-0001｜正文｜摘要S-0001\n[?] S-0002｜正文｜摘要S-0002"
    assert thread_block(b, items) == "## L-002 乙\n[?] S-0003｜正文｜摘要S-0003\n[?] S-0404"


def align_of(book, threads, main, budget=10**6, **handlers):
    c = client(book, **handlers)
    caller = Caller(book, c, lambda *a: None)
    items = items_of("S-0001", "S-0002", "S-0003")
    return asyncio.run(stage_align(caller, threads, main, items, "年", budget)), c, caller


def test_stage_align_default(book):
    _, a, b = two_threads()
    (offsets, cross), c, _ = align_of(book, [a, b], "L-001")
    assert offsets == {"L-001": 0, "L-002": 0} and cross == []
    assert "## L-001 甲（主线）" in users(c, "跨线对齐")[0]


def test_stage_align_reply(book):
    _, a, b = two_threads()

    def reply(m):
        return json.dumps({"threads": [{"id": "L-001", "offset": 0}, {"id": "L-002", "offset": None}],
                           "intersections": [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "同一场"}]},
                          ensure_ascii=False)

    (offsets, cross), _, _ = align_of(book, [a, b], "L-001", align=reply)
    assert offsets == {"L-001": 0, "L-002": None}
    assert cross == [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "同一场"}]


def test_stage_align_skips(book):
    _, a, b = two_threads()
    (offsets, _), c, _ = align_of(book, [a], "L-001")
    assert offsets == {"L-001": 0} and c.usage.calls == 0
    (offsets, _), c, _ = align_of(book, [a, b], None)
    assert offsets == {"L-001": None, "L-002": None} and c.usage.calls == 0
    (offsets, _), c, caller = align_of(book, [a, b], "L-001", budget=10)
    assert offsets == {"L-001": 0, "L-002": None} and c.usage.calls == 0 and caller.failed


def test_stage_align_failed(book):
    _, a, b = two_threads()
    (offsets, cross), _, caller = align_of(book, [a, b], "L-001", align=lambda m: LLMError("坏了"))
    assert offsets == {"L-001": 0, "L-002": None} and cross == [] and len(caller.failed) == 1


def gaps_of(book, refs, threads, budget=10**6, **handlers):
    items = items_of("S-0001", "S-0002", "S-0003")
    for sid, rs in refs.items():
        items[sid].refs = rs
    c = client(book, **handlers)
    caller = Caller(book, c, lambda *a: None)
    got = asyncio.run(stage_gaps(caller, "W-01", "人间", threads, list(items), items, budget))
    return got, c


def test_stage_gaps(book):
    _, a, _ = two_threads()
    got, c = gaps_of(book, {}, [a])
    assert got == [] and c.usage.calls == 0

    def reply(m):
        return json.dumps({"gaps": [{"event": "城破", "mentioned_in": ["S-0003"], "thread": "L-001", "after": "S-0001", "before": None}]},
                          ensure_ascii=False)

    got, c = gaps_of(book, {"S-0003": ["青州城破"]}, [a], gaps=reply)
    assert got == [{"world": "W-01", "event": "城破", "mentioned_in": ["S-0003"], "thread": "L-001", "after": "S-0001", "before": None}]
    assert "- 青州城破｜S-0003" in users(c, "找缺口")[0]
    got, c = gaps_of(book, {"S-0003": ["青州城破"]}, [a], gaps=lambda m: LLMError("坏了"))
    assert got == []
    got, c = gaps_of(book, {"S-0003": ["青州城破"]}, [a], budget=10)
    assert got == [] and c.usage.calls == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_threads.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'stage_align'`）

- [ ] **Step 3: 实现**

`src/ligaotai/threads.py`：
- import：`from .threads_check import ...` 加上 `check_align, check_gaps, clean_align, clean_gaps`
- 文件末尾追加：
```python
# --- 6.4 跨线对齐 / 6.5 找缺口 ---


def _num(t) -> str:
    return "?" if t is None else f"{t:g}"


def thread_block(t: ThreadDraft, items: dict[str, Item], main: bool = False) -> str:
    head = f"## {t.key} {t.name}" + ("（主线）" if main else "")
    rows = [
        f"[{_num((t.times.get(s) or {}).get('t'))}] {items[s].line if s in items else s}"
        for s in t.scenes
    ]
    return "\n".join([head, *rows])


async def stage_align(
    caller: Caller, threads: list[ThreadDraft], main: str | None, items: dict[str, Item], unit: str, budget: int
) -> tuple[dict[str, float | None], list[dict]]:
    offsets: dict[str, float | None] = {t.key: None for t in threads}
    if main is None or main not in offsets:
        return offsets, []
    offsets[main] = 0
    if len(threads) == 1:
        return offsets, []
    text = "\n\n".join(thread_block(t, items, t.key == main) for t in threads)
    if len(text) > budget:
        caller.failed.append({"call": "align", "error": "输入太大，跳过跨线对齐"})
        return offsets, []
    members = {t.key: set(t.scenes) for t in threads}
    ids = set(members)
    caller.plan(1)
    data = await caller.call(
        "threads_align", {"unit": unit or "年", "main": main, "threads": text},
        lambda d: check_align(d, ids, main, members), "align",
    )
    if data is None:
        return offsets, []
    return clean_align(data, ids, main, members)


async def stage_gaps(
    caller: Caller, world_key: str, world_name: str, threads: list[ThreadDraft],
    world_scenes: list[str], items: dict[str, Item], budget: int,
) -> list[dict]:
    """找缺口（一个世界一次）。world_scenes：这个世界的全部块（线里的、提纲、设定笔记）。"""
    refs = [(r, s) for s in world_scenes if s in items for r in items[s].refs]
    if not refs or not threads:
        return []
    text = "\n\n".join(thread_block(t, items) for t in threads)
    ref_text = "\n".join(f"- {r}｜{s}" for r, s in refs)
    if len(text) + len(ref_text) > budget:
        caller.failed.append({"call": f"gaps-{world_key}", "error": "输入太大，跳过找缺口"})
        return []
    ref_scenes = {s for _, s in refs}
    lines = {t.key: list(t.scenes) for t in threads}
    caller.plan(1)
    data = await caller.call(
        "threads_gaps", {"world": world_name, "threads": text, "refs": ref_text},
        lambda d: check_gaps(d, ref_scenes, lines), f"gaps-{world_key}",
    )
    if data is None:
        return []
    return [{"world": world_key, **g} for g in clean_gaps(data, ref_scenes, lines)]
```

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_threads.py -q`
Expected: 27 passed

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/threads.py tests/test_threads.py
git commit -m "feat: 归线跨线对齐和找缺口"
```

---
## Task 13: threads.py——编号、主线、旧文件补齐（纯函数）

**Files:**
- Modify: `src/ligaotai/threads.py`（追加）
- Test: `tests/test_threads.py`（追加）

要点（本计划开头决定 1、2、6、7）：
- `EMPTY`：`世界与支线.json` 的完整空结构；`normalize(旧文件内容)` 补齐缺的键、丢掉不认识的键，不是 dict 就当空的。
- `content_signature(data)`：去掉所有 `status` 字段后的 JSON（排好键）。只确认不改内容时签名不变，下游不该过期。
- `next_number(data, "world"|"thread")`：取文件顶层 `next_world` / `next_thread`；缺失、不是 int（bool 也不算）时，按现有最大编号 + 1 兜底；两者取大的。
- `assign_world_ids(old, worlds)`：临时键 `N…` 换成正式编号。草稿世界按**名字**沿用旧的草稿世界编号——但已经在这次世界列表里的正式编号（已确认的世界）不能再发出去。返回 (映射, 新的 next_world)。
- `assign_thread_ids(old, threads)`：新线按**块集合**沿用旧的草稿线编号，其他的从 next_thread 取。返回 (映射, 新的 next_thread)。
- `thread_from_dict(t, all_ids)`：旧文件里已确认的线 → `ThreadDraft(locked=True)`；块和提纲只留还是没删除的主版本的（`all_ids`），时间也跟着过滤。
- `choose_main(old, threads, world_mains, world_order)`：作者设过（`main_by == "author"`）且那条线还在就留；否则在块最多的世界里（平票取靠前的世界）取这个世界被标 main 的线，那条线不在了就取这个世界里块最多的线。返回 (主线, main_by)。

- [ ] **Step 1: 写失败的测试**

`tests/test_threads.py` 末尾追加：
```python
from ligaotai.threads import (
    EMPTY,
    assign_thread_ids,
    assign_world_ids,
    choose_main,
    content_signature,
    next_number,
    normalize,
    thread_from_dict,
)


def test_normalize():
    assert normalize(None) == EMPTY and normalize(None) is not EMPTY
    got = normalize({"threads": [{"id": "L-001"}], "junk": 1})
    assert got["threads"] == [{"id": "L-001"}] and "junk" not in got and got["worlds"] == []
    got["worlds"].append(1)
    assert EMPTY["worlds"] == []  # 不能改到共用的空结构


def test_content_signature_ignores_status():
    a = {"threads": [{"id": "L-001", "status": "draft", "scenes": ["S-0001"]}]}
    b = {"threads": [{"id": "L-001", "status": "confirmed", "scenes": ["S-0001"]}]}
    c = {"threads": [{"id": "L-001", "status": "draft", "scenes": ["S-0002"]}]}
    assert content_signature(a) == content_signature(b) != content_signature(c)


def test_next_number():
    assert next_number({"worlds": [{"id": "W-03"}], "next_world": 2}, "world") == 4
    assert next_number({"worlds": [], "next_world": 9}, "world") == 9
    assert next_number({"threads": [{"id": "L-007"}], "next_thread": True}, "thread") == 8
    assert next_number({}, "thread") == 1


def test_assign_world_ids():
    old = normalize({"worlds": [
        {"id": "W-01", "name": "甲", "status": "draft"},
        {"id": "W-02", "name": "乙", "status": "confirmed"},
    ]})
    worlds = [WorldDraft("W-02", "乙"), WorldDraft("N1", "甲"), WorldDraft("N2", "丙")]
    assert assign_world_ids(old, worlds) == ({"W-02": "W-02", "N1": "W-01", "N2": "W-03"}, 4)


def test_assign_world_ids_never_reissues_a_world_in_use():
    old = normalize({"worlds": [{"id": "W-01", "name": "甲", "status": "draft"}]})
    worlds = [WorldDraft("W-01", "甲"), WorldDraft("N1", "甲")]  # W-01 因为有已确认的线而锁定
    assert assign_world_ids(old, worlds) == ({"W-01": "W-01", "N1": "W-02"}, 3)


def test_assign_thread_ids():
    old = normalize({"threads": [
        {"id": "L-001", "status": "draft", "scenes": ["S-0001", "S-0002"]},
        {"id": "L-002", "status": "confirmed", "scenes": ["S-0003"]},
    ]})
    new = [ThreadDraft("W-01#1", "W-01", "a", scenes=["S-0002", "S-0001"]), ThreadDraft("W-01#2", "W-01", "b", scenes=["S-0003"])]
    assert assign_thread_ids(old, new) == ({"W-01#1": "L-001", "W-01#2": "L-003"}, 4)


def test_thread_from_dict():
    t = thread_from_dict({"id": "L-002", "world": "W-01", "name": "乙", "scenes": ["S-0001", "S-0009"],
                          "outlines": ["S-0009"], "times": {"S-0001": {"t": 1, "conf": "高"}, "S-0009": {"t": 2, "conf": "高"}},
                          "end": {"state": "完结", "note": "n", "last": "S-0009"}}, {"S-0001"})
    assert (t.key, t.world, t.name, t.scenes, t.outlines, t.locked) == ("L-002", "W-01", "乙", ["S-0001"], [], True)
    assert t.times == {"S-0001": {"t": 1, "conf": "高"}} and t.end["state"] == "完结"


def test_choose_main():
    a = ThreadDraft("L-001", "W-01", "a", scenes=["S-0001"])
    b = ThreadDraft("L-002", "W-02", "b", scenes=["S-0002", "S-0003"])
    c = ThreadDraft("L-003", "W-02", "c", scenes=["S-0004"])
    threads, order = [a, b, c], ["W-01", "W-02"]
    assert choose_main(normalize({"main_thread": "L-001", "main_by": "author"}), threads, {}, order) == ("L-001", "author")
    assert choose_main(normalize({"main_thread": "L-009", "main_by": "author"}), threads, {"W-02": "L-003"}, order) == ("L-003", "auto")
    assert choose_main(normalize(None), threads, {"W-02": "L-404"}, order) == ("L-002", "auto")
    assert choose_main(normalize(None), [], {}, []) == (None, "auto")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_threads.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'EMPTY'`）

- [ ] **Step 3: 实现**

`src/ligaotai/threads.py`：
- import 区加 `import copy`、`import json`、`import re`
- 文件末尾追加：
```python
# --- 编号、主线、旧文件 ---

EMPTY: dict = {
    "next_world": 1,
    "next_thread": 1,
    "time_unit": "",
    "main_thread": None,
    "main_by": "auto",
    "worlds": [],
    "threads": [],
    "intersections": [],
    "gaps": [],
    "unassigned": [],
    "pending": [],
}
_KINDS = {"world": ("W", "worlds", "next_world"), "thread": ("L", "threads", "next_thread")}


def normalize(data) -> dict:
    """旧文件读进来：补齐缺的键、丢掉不认识的键；不是 dict 就当空的。"""
    out = copy.deepcopy(EMPTY)
    if isinstance(data, dict):
        out.update({k: copy.deepcopy(v) for k, v in data.items() if k in EMPTY})
    return out


def content_signature(data: dict) -> str:
    """去掉所有 status 后的内容：只确认、不改内容时签名不变。"""

    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k != "status"}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x

    return json.dumps(strip(data), ensure_ascii=False, sort_keys=True)


def _id_num(oid, prefix: str) -> int:
    m = re.fullmatch(rf"{prefix}-(\d+)", oid) if isinstance(oid, str) else None
    return int(m.group(1)) if m else 0


def next_number(data: dict, kind: str) -> int:
    prefix, key, field_name = _KINDS[kind]
    top = max((_id_num(x.get("id"), prefix) for x in data.get(key, []) if isinstance(x, dict)), default=0)
    n = data.get(field_name)
    if not isinstance(n, int) or isinstance(n, bool):
        n = 0
    return max(n, top + 1)


def world_id(n: int) -> str:
    return f"W-{n:02d}"


def thread_id(n: int) -> str:
    return f"L-{n:03d}"


def assign_world_ids(old: dict, worlds: list[WorldDraft]) -> tuple[dict[str, str], int]:
    """临时键 N… → 正式编号；已确认世界的键本来就是正式编号。草稿世界按名字沿用旧的草稿世界编号。"""
    in_use = {w.key for w in worlds if not w.key.startswith("N")}
    reuse: dict[str, str] = {}
    for w in old["worlds"]:
        if w.get("status") != CONFIRMED and w.get("id") not in in_use:
            reuse.setdefault(w.get("name"), w["id"])
    n = next_number(old, "world")
    out: dict[str, str] = {}
    for w in worlds:
        if w.key in in_use:
            out[w.key] = w.key
            continue
        wid = reuse.pop(w.name, None)
        if wid is None:
            wid, n = world_id(n), n + 1
        out[w.key] = wid
    return out, n


def assign_thread_ids(old: dict, threads: list[ThreadDraft]) -> tuple[dict[str, str], int]:
    """新线的临时键 → 正式编号。块集合跟旧的某条草稿线一样就沿用它的编号。"""
    reuse = {
        frozenset(t.get("scenes", [])): t["id"]
        for t in old["threads"]
        if t.get("status") != CONFIRMED and isinstance(t.get("id"), str)
    }
    n = next_number(old, "thread")
    out: dict[str, str] = {}
    for t in threads:
        tid = reuse.pop(frozenset(t.scenes), None)
        if tid is None:
            tid, n = thread_id(n), n + 1
        out[t.key] = tid
    return out, n


def thread_from_dict(t: dict, all_ids: set[str]) -> ThreadDraft:
    scenes = [s for s in t.get("scenes", []) if s in all_ids]
    return ThreadDraft(
        key=t["id"],
        world=t.get("world", ""),
        name=t.get("name", ""),
        about=t.get("about", ""),
        scenes=scenes,
        outlines=[s for s in t.get("outlines", []) if s in all_ids],
        times={k: v for k, v in (t.get("times") or {}).items() if k in scenes},
        end=dict(t.get("end") or {}),
        order_failed=bool(t.get("order_failed")),
        locked=True,
    )


def choose_main(
    old: dict, threads: list[ThreadDraft], world_mains: dict[str, str | None], world_order: list[str]
) -> tuple[str | None, str]:
    ids = {t.key for t in threads}
    if old.get("main_by") == "author" and old.get("main_thread") in ids:
        return old["main_thread"], "author"
    if not threads:
        return None, "auto"
    size = {w: sum(len(t.scenes) for t in threads if t.world == w) for w in world_order}
    best = max(world_order, key=lambda w: size[w])  # max 平票取第一个
    main = world_mains.get(best)
    if main not in ids:
        mine = [t for t in threads if t.world == best] or threads
        main = max(mine, key=lambda t: len(t.scenes)).key
    return main, "auto"
```

注意 `test_choose_main` 第二条：作者设的 `L-009` 已经不在了，改按块数选：W-02 有 3 块比 W-01 多，它被标 main 的是 `L-003`，就用 `L-003`（不是块最多的 `L-002`）。第三条：W-02 标的 `L-404` 不存在，退回 W-02 里块最多的 `L-002`。

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_threads.py -q`
Expected: 35 passed

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/threads.py tests/test_threads.py
git commit -m "feat: 归线的编号分配、主线选择、旧文件补齐"
```

---
## Task 14: threads.py——组装 + run_threads

**Files:**
- Modify: `src/ligaotai/threads.py`（追加）
- Test: `tests/test_threads_run.py`（新）

流程（②b 设计第 2、3、5 章）：
1. `prepare(book)` 拿到块、未分配、`all_ids`、开跑时的指纹；读 `世界与支线.json` 当快照（`snapshot`），`normalize` 成 `old`。
2. **锁定的东西**：`old` 里 `status == "confirmed"` 的线（用 `thread_from_dict` 转）；已确认的世界，加上有已确认线的世界（旧文件里找不到的世界补一个同名占位）。锁定线的块和提纲、锁定世界的设定笔记和提纲，都不进模型的输入（`held`）。
3. 时间单位：锁定的线里有时间就沿用旧单位，否则让模型提议。
4. 划世界 → 定世界编号 → 各世界并发划支线 → 各新线并发排序 → 排空了的线丢掉（提纲挂回世界）→ 定线编号 → 选主线 → 对齐 → 拼世界 → 各世界并发找缺口。并发用 `asyncio.TaskGroup`，异常组用 `pick_error` 挑出来（欠费优先于暂停）；用量在 `finally` 里记账。
5. 组装：线按世界顺序排，每个世界里先锁定的线后新线；锁定世界沿用旧的字段、状态 confirmed，设定笔记 / 提纲 = 旧的（还在的）+ 这次新分来的；未分配 = `prepare` 的（去掉作者放进锁定线里的）+ 模型漏掉的，按编号排；缺口编号 `Q-001` 起。
6. 写回：再算一次指纹。进 `FILE_LOCK`，重新读文件：跟快照不一样（跑的途中作者动过）就不写；否则写入，`changed` = 内容签名变了没有。写入了才清理没用到的缓存。
7. 步骤状态：指纹变了或者没写入 → `outdated`；否则 `done`。

- [ ] **Step 1: 写失败的测试**

`tests/test_threads_run.py`：
```python
import json

import pytest
from helpers import FakeBackend, listed_scenes, seed_book, threads_handler

from ligaotai.config import AppConfig
from ligaotai.fsutil import read_json, write_json
from ligaotai.jobs import JobCancelled
from ligaotai.llm import FatalLLMError, LLMClient, LLMError
from ligaotai.threads import MISSED, PENDING, run_threads
from ligaotai.threads_input import NO_CARD

# S-0001、S-0002 是 b.txt 里挨着的两块；S-0003 在 a.txt，提到「青州城破」；S-0004 提纲；S-0005 设定笔记；S-0006 没卡
SCENES = [
    {"id": "S-0001", "source": "b.txt", "index": 0, "persons": ["林清"]},
    {"id": "S-0002", "source": "b.txt", "index": 1},
    {"id": "S-0003", "source": "a.txt", "index": 0, "refs": ["青州城破"]},
    {"id": "S-0004", "source": "a.txt", "index": 1, "kind": "提纲"},
    {"id": "S-0005", "source": "a.txt", "index": 2, "kind": "设定笔记"},
    {"id": "S-0006", "source": "a.txt", "index": 3, "no_card": True},
]
ENTS = [("person", "林清", ["林清"])]


@pytest.fixture
def seeded(book):
    seed_book(book, SCENES, entities=ENTS)
    return book


def client(book, **handlers):
    return LLMClient(AppConfig(), FakeBackend(handler=threads_handler(**handlers)), log_dir=book.logs_dir)


def default(m):
    """某一种调用里先做点手脚、再照默认回复时用。"""
    return threads_handler()(None, m)


def result(book):
    return read_json(book.threads_path)


def edit(book, fn):
    data = result(book)
    fn(data)
    write_json(book.threads_path, data)


def test_run_threads_end_to_end(seeded):
    c = client(seeded)
    summary = run_threads(seeded, c)
    data = result(seeded)
    assert data["worlds"] == [
        {"id": "W-01", "name": "世界一", "reason": "测试", "status": "draft", "notes": ["S-0005"], "outlines": []}
    ]
    [t] = data["threads"]
    assert (t["id"], t["world"], t["name"], t["status"]) == ("L-001", "W-01", "主线", "draft")
    assert t["scenes"] == ["S-0003", "S-0001", "S-0002"] and t["outlines"] == ["S-0004"]
    assert t["times"]["S-0001"] == {"t": 1, "conf": "高"} and t["offset"] == 0
    assert t["end"] == {"state": "待定", "note": "测试", "last": "S-0002"} and t["order_failed"] is False
    assert (data["main_thread"], data["main_by"], data["time_unit"]) == ("L-001", "auto", "年")
    assert data["unassigned"] == [{"scene": "S-0006", "reason": NO_CARD}]
    assert data["pending"] == [] and data["gaps"] == [] and data["intersections"] == []
    assert (data["next_world"], data["next_thread"]) == (2, 2)
    assert c.usage.calls == 4  # 划世界、划支线、排序、找缺口；只有一条线，不用对齐
    assert summary["threads"] == 1 and summary["unassigned"] == 1 and summary["not_written"] is False
    assert seeded.step("threads")["status"] == "done"
    assert seeded.load()["usage"]["by_step"]["threads"]["calls"] == 4


def test_rerun_uses_the_cache(seeded):
    run_threads(seeded, client(seeded))
    first = result(seeded)
    c = client(seeded)
    run_threads(seeded, c)
    assert c.usage.calls == 0 and result(seeded) == first
    assert seeded.step("threads")["status"] == "done"


def test_ids_stay_the_same_when_rerun_without_cache(seeded):
    run_threads(seeded, client(seeded))
    seeded.threads_cache_path.unlink()
    c = client(seeded)
    run_threads(seeded, c)
    data = result(seeded)
    assert c.usage.calls == 4
    assert [w["id"] for w in data["worlds"]] == ["W-01"] and [t["id"] for t in data["threads"]] == ["L-001"]
    assert (data["next_world"], data["next_thread"]) == (2, 2)


def test_confirmed_thread_is_kept_and_new_scene_goes_to_pending(seeded):
    run_threads(seeded, client(seeded))
    edit(seeded, lambda d: d["threads"][0].update(status="confirmed"))
    before = result(seeded)["threads"][0]
    seed_book(seeded, SCENES + [{"id": "S-0007", "source": "c.txt", "index": 0}], entities=ENTS)

    def worlds(m):
        return json.dumps({"worlds": [{"id": "W-01", "scenes": listed_scenes(m)}]})

    def lines(m):
        return json.dumps({"threads": [{"id": "L-001", "main": True, "scenes": listed_scenes(m)}]})

    c = client(seeded, worlds=worlds, lines=lines)
    run_threads(seeded, c)
    data = result(seeded)
    [t] = data["threads"]
    keys = ("id", "scenes", "times", "outlines", "status")
    assert {k: t[k] for k in keys} == {k: before[k] for k in keys}
    assert data["pending"] == [{"scene": "S-0007", "thread": "L-001", "reason": PENDING}]
    assert data["worlds"][0]["status"] == "confirmed" and data["worlds"][0]["notes"] == ["S-0005"]
    world_prompts = [x["messages"][1]["content"] for x in c.backend.calls if "划分世界" in x["messages"][0]["content"]]
    assert world_prompts and all("S-0001" not in p for p in world_prompts)


def test_confirmed_thread_keeps_a_scene_without_card_and_author_main(seeded):
    run_threads(seeded, client(seeded))

    def confirm(d):
        d["threads"][0]["status"] = "confirmed"
        d["threads"][0]["scenes"].append("S-0006")
        d["main_by"] = "author"

    edit(seeded, confirm)
    run_threads(seeded, client(seeded))
    data = result(seeded)
    assert data["threads"][0]["scenes"][-1] == "S-0006"
    assert all(u["scene"] != "S-0006" for u in data["unassigned"])
    assert data["main_by"] == "author"


def test_scene_the_model_keeps_missing_goes_to_unassigned(seeded):
    def order(m):
        ids = [s for s in listed_scenes(m) if s != "S-0001"]
        return json.dumps({"order": ids, "times": {s: [0, "高"] for s in ids}, "end": {"state": "待定", "note": ""}},
                          ensure_ascii=False)

    summary = run_threads(seeded, client(seeded, order=order))
    data = result(seeded)
    assert data["threads"][0]["scenes"] == ["S-0003", "S-0002"]
    assert {"scene": "S-0001", "reason": MISSED} in data["unassigned"]
    assert summary["unresolved"][0]["call"] == "order-W-01#1"


def test_order_failure_falls_back_to_file_order(seeded):
    summary = run_threads(seeded, client(seeded, order=lambda m: LLMError("坏了")))
    t = result(seeded)["threads"][0]
    assert t["scenes"] == ["S-0003", "S-0001", "S-0002"] and t["order_failed"] is True and t["times"] == {}
    assert summary["order_failed"] == ["L-001"] and summary["failed_calls"][0]["call"] == "order-W-01#1"


def test_input_changed_during_the_run_is_outdated(seeded):
    def order(m):
        seed_book(seeded, SCENES, entities=[("person", "林小清", ["林清"])])
        return default(m)

    summary = run_threads(seeded, client(seeded, order=order))
    assert summary["input_changed"] is True and seeded.step("threads")["status"] == "outdated"
    assert result(seeded)["threads"]  # 结果照样写了，只是要重跑


def test_author_edit_during_the_run_is_not_overwritten(seeded):
    run_threads(seeded, client(seeded))
    seeded.threads_cache_path.unlink()

    def worlds(m):
        edit(seeded, lambda d: d["threads"][0].update(name="作者改的名"))
        return default(m)

    summary = run_threads(seeded, client(seeded, worlds=worlds))
    assert summary["not_written"] is True and seeded.step("threads")["status"] == "outdated"
    assert result(seeded)["threads"][0]["name"] == "作者改的名"
    assert seeded.threads_cache_path.exists()  # 没清缓存，重跑不花钱


def test_fatal_error_stops_the_step_and_keeps_usage(seeded):
    with pytest.raises(FatalLLMError):
        run_threads(seeded, client(seeded, lines=lambda m: FatalLLMError("欠费")))
    assert seeded.load()["usage"]["by_step"]["threads"]["calls"] == 1
    assert not seeded.threads_path.exists()


def test_pause_then_rerun_uses_the_cache(seeded):
    def progress(done, total, *a):
        if done >= 1:
            raise JobCancelled("已暂停")

    c1 = client(seeded)
    with pytest.raises(JobCancelled):
        run_threads(seeded, c1, progress)
    c2 = client(seeded)
    run_threads(seeded, c2)
    assert (c1.usage.calls, c2.usage.calls) == (1, 3)
```

几个测试的推演（实现时对照）：
- 端到端：划世界把 S-0001～S-0005 归「世界一」；划支线只送 S-0001～S-0004（设定笔记不送），S-0004 是提纲挂上主线；排序时片段是 `[S-0003]`、`[S-0001, S-0002]`（a.txt 排在 b.txt 前），默认回复按列出的顺序排；找缺口时 S-0003 有 refs，调一次。
- 已确认的线：第二次跑时 S-0001～S-0005 都锁住了，只有 S-0007 进划世界；归到 W-01；划支线的回复把它放进 L-001 → 进 pending；找缺口的提示词跟第一次一样，走缓存。
- 没卡的块：作者把 S-0006 放进已确认的线后，没有新块要划；找缺口的提示词因为多了一行 `[?] S-0006` 变了，要调一次。
- 欠费：划世界调了 1 次；划支线抛 `FatalLLMError`，这次调用没有返回 usage，不计数。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_threads_run.py -q`
Expected: FAIL（`ImportError: cannot import name 'run_threads'`）

- [ ] **Step 3: 实现**

`src/ligaotai/threads.py`：
- import 区加 `import asyncio`；`from .book import Book` 改成 `from .book import FILE_LOCK, Book`；加 `from .cards import pick_error`；`from .threads_input import ...` 加上 `NOTE, prepare`
- 文件末尾追加：
```python
# --- 组装、run_threads ---


def run_threads(book: Book, client: LLMClient, progress: Progress = _noop) -> dict:
    return asyncio.run(_run_threads(book, client, progress))


async def _all(coros) -> list:
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(c) for c in coros]
    return [t.result() for t in tasks]


def _thread_dict(t: ThreadDraft, offset) -> dict:
    return {
        "id": t.key,
        "world": t.world,
        "name": t.name,
        "about": t.about,
        "status": CONFIRMED if t.locked else DRAFT,
        "scenes": t.scenes,
        "times": t.times,
        "outlines": t.outlines,
        "offset": offset,
        "end": {"state": t.end.get("state", "待定"), "note": t.end.get("note", ""), "last": t.scenes[-1] if t.scenes else None},
        "order_failed": t.order_failed,
    }


def _world_dicts(
    worlds: list[WorldDraft], old_worlds: dict[str, dict], locked_ids: set[str],
    items: dict[str, Item], world_outlines: dict[str, list[str]], all_ids: set[str],
) -> list[dict]:
    out = []
    for w in worlds:
        notes = [s for s in w.scenes if items[s].kind == NOTE]
        outs = world_outlines.get(w.key, [])
        if w.key in locked_ids:
            o = old_worlds[w.key]
            out.append({
                **o,
                "status": CONFIRMED,
                "notes": [s for s in o.get("notes", []) if s in all_ids] + notes,
                "outlines": [s for s in o.get("outlines", []) if s in all_ids] + outs,
            })
        else:
            out.append({"id": w.key, "name": w.name, "reason": w.reason, "status": DRAFT, "notes": notes, "outlines": outs})
    return out


def _world_scenes(w: dict, threads: list[ThreadDraft]) -> list[str]:
    inside = [s for t in threads if t.world == w["id"] for s in t.scenes + t.outlines]
    return inside + w["notes"] + w["outlines"]


async def _run_threads(book: Book, client: LLMClient, progress: Progress) -> dict:
    prep = prepare(book)
    items = prep.items
    budget = book.settings()["threads_max_input_tokens"]
    snapshot = read_json(book.threads_path, None)
    old = normalize(snapshot)

    locked = [
        thread_from_dict(t, prep.all_ids)
        for t in old["threads"]
        if isinstance(t, dict) and t.get("id") and t.get("status") == CONFIRMED
    ]
    old_worlds = {w["id"]: w for w in old["worlds"] if isinstance(w, dict) and w.get("id")}
    locked_world_ids = {wid for wid, w in old_worlds.items() if w.get("status") == CONFIRMED} | {t.world for t in locked}
    for wid in sorted(locked_world_ids - set(old_worlds)):  # 旧文件里找不到的世界：补个占位，别把线弄丢
        old_worlds[wid] = {"id": wid, "name": wid, "reason": "", "status": CONFIRMED, "notes": [], "outlines": []}
    locked_worlds = [w for wid, w in old_worlds.items() if wid in locked_world_ids]
    held = {s for t in locked for s in t.scenes + t.outlines}
    held |= {s for w in locked_worlds for s in w.get("notes", []) + w.get("outlines", []) if s in prep.all_ids}
    free = [it for sid, it in items.items() if sid not in held]
    unit = old["time_unit"] if any(t.times for t in locked) else ""

    caller = Caller(book, client, progress)
    try:
        known = [WorldDraft(w["id"], w.get("name", ""), w.get("reason", "")) for w in locked_worlds]
        worlds, missing, unit = await stage_worlds(caller, free, known, unit, budget)
        wmap, next_world = assign_world_ids(old, worlds)
        for w in worlds:
            w.key = wmap[w.key]
        results = await _all(
            stage_lines(caller, w, items, [t for t in locked if t.world == w.key], budget) for w in worlds
        )
        new = [t for r in results for t in r.threads]
        lost = await _all(stage_order(caller, t, items, unit) for t in new)
        missing += [s for r in results for s in r.missing] + [s for m in lost for s in m]
        world_outlines = {w.key: list(r.world_outlines) for w, r in zip(worlds, results)}
        for t in new + locked:
            if not t.scenes:  # 排空了（或者块都没了）的线丢掉，提纲挂回世界
                world_outlines.setdefault(t.world, []).extend(t.outlines)
        new = [t for t in new if t.scenes]
        tmap, next_thread = assign_thread_ids(old, new)
        for t in new:
            t.key = tmap[t.key]
        world_mains = {w.key: tmap.get(r.main, r.main) for w, r in zip(worlds, results)}
        alive = [t for t in locked if t.scenes] + new
        threads = [t for w in worlds for t in alive if t.world == w.key]
        main, main_by = choose_main(old, threads, world_mains, [w.key for w in worlds])
        offsets, intersections = await stage_align(caller, threads, main, items, unit, budget)
        world_dicts = _world_dicts(worlds, old_worlds, locked_world_ids, items, world_outlines, prep.all_ids)
        gap_lists = await _all(
            stage_gaps(caller, w["id"], w["name"], [t for t in threads if t.world == w["id"]],
                       _world_scenes(w, threads), items, budget)
            for w in world_dicts
        )
    except BaseExceptionGroup as eg:
        raise pick_error(eg) from None  # 欠费 / key 失效要让作者看到，不能被「已暂停」盖住
    finally:
        u = client.usage
        book.add_usage("threads", u.calls, u.prompt_tokens, u.completion_tokens, u.cost(client.cfg))

    no_card = [u for u in prep.unassigned if u["scene"] not in held]
    unassigned = no_card + [{"scene": s, "reason": MISSED} for s in dict.fromkeys(missing)]
    unassigned.sort(key=lambda u: natural_key(u["scene"]))
    pending = [p for r in results for p in r.pending]
    thread_dicts = [_thread_dict(t, offsets.get(t.key)) for t in threads]
    gaps = [{"id": f"Q-{i:03d}", **g} for i, g in enumerate((g for gs in gap_lists for g in gs), 1)]
    data = {
        "next_world": next_world,
        "next_thread": next_thread,
        "time_unit": unit,
        "main_thread": main,
        "main_by": main_by,
        "worlds": world_dicts,
        "threads": thread_dicts,
        "intersections": intersections,
        "gaps": gaps,
        "unassigned": unassigned,
        "pending": pending,
    }

    fp_end = prepare(book).fingerprint
    # 只把「重新读文件 → 比对 → 写回」放进锁里，都是毫秒级的本地操作；调模型在上面，绝不能进锁。
    with FILE_LOCK:
        not_written = read_json(book.threads_path, None) != snapshot
        changed = not not_written and content_signature(old) != content_signature(data)
        if not not_written:
            write_json(book.threads_path, data)
    if not not_written:
        caller.prune_cache()
    input_changed = fp_end != prep.fingerprint
    summary = {
        "worlds": len(world_dicts),
        "threads": len(thread_dicts),
        "confirmed_threads": sum(t["status"] == CONFIRMED for t in thread_dicts),
        "scenes": len(items),
        "unassigned": len(unassigned),
        "pending": len(pending),
        "gaps": len(gaps),
        "order_failed": [t["id"] for t in thread_dicts if t["order_failed"]],
        "failed_calls": caller.failed,
        "unresolved": caller.unresolved,
        "input_changed": input_changed,
        "not_written": not_written,
        "calls": client.usage.calls,
        "cost_usd": round(client.usage.cost(client.cfg), 4),
    }
    status = "outdated" if (input_changed or not_written) else "done"
    book.set_step("threads", status, summary, changed=changed)
    return summary
```

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_threads_run.py tests/test_threads.py -q`
Expected: 全部 PASS（test_threads_run 11 个）

- [ ] **Step 5: 跑全部测试**

Run: `uv run pytest -q`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add src/ligaotai/threads.py tests/test_threads_run.py
git commit -m "feat: 步骤 6 归线排序 run_threads（组装、锁定保留、输入指纹、跑中改动不覆盖）"
```

---
## Task 15: 作者调整（threads_ops.py）

**Files:**
- Create: `src/ligaotai/threads_ops.py`
- Test: `tests/test_threads_ops.py`

要点（②b 设计第 4 章）：
- 每个操作「读 → 改 → 写」整段在 `FILE_LOCK` 里（跟 `run_threads` 的写回、跟彼此都串行）。
- 作者动过的线自动 `confirmed`，它所在的世界也 `confirmed`；改世界名只确认那个世界。
- 写回前统一整理（`_tidy`）：
  - 挪空了的线删掉，它的提纲挂回世界
  - 指向已删线的 pending 挪进未分配（原因「建议归入的线已被删除」）
  - 没有线、没有设定笔记、没有提纲的世界删掉
  - 主线没了就换成块最多的线（`main_by` 回到 auto）
  - 交汇点里对不上的删掉（线没了、块不在那条线里、main_scene 不在主线里）
  - 缺口指向的线没了就 thread / after / before 全置 null，after / before 不在线里就置 null
  - 每条线的 `end.last` 跟着最后一块走
- 内容签名（`content_signature`，不看 status）变了才把下游（步骤 7）标过期；只确认不改内容，下游不过期。
- 找不到线 / 世界 → `KeyError`；参数不对 → `ValueError`；还没跑过步骤 6 → `FileNotFoundError`。
- 挪块：先从原来的地方（任何线的块和提纲、世界的笔记和提纲、未分配、建议归入）拿掉，再插进目标线的 `position`（拿掉之后的列表里的位置，`None` = 末尾）；同一条线里挪（调顺序）时保留这些块原来的时间，从别的线挪来的不带时间（不同线的线内时间对不上）。
- 合并：合成第一条；其余线的块按原顺序接在后面，它们的时间丢掉；指向被合并线的 pending、缺口改指第一条；主线是被合并的线就改成第一条。
- 拆线：从某一块起（不能是第一块）后面的拆成新线，编号取 `next_thread`，名字「原名（拆出）」，带走这些块的时间；新线插在原线后面。

- [ ] **Step 1: 写失败的测试**

`tests/test_threads_ops.py`：
```python
import pytest

from ligaotai import threads_ops as ops
from ligaotai.fsutil import read_json, write_json


def sample():
    return {
        "next_world": 3, "next_thread": 4, "time_unit": "年", "main_thread": "L-001", "main_by": "auto",
        "worlds": [
            {"id": "W-01", "name": "人间", "reason": "", "status": "draft", "notes": ["S-0009"], "outlines": []},
            {"id": "W-02", "name": "天界", "reason": "", "status": "draft", "notes": [], "outlines": []},
        ],
        "threads": [
            {"id": "L-001", "world": "W-01", "name": "甲", "about": "", "status": "draft",
             "scenes": ["S-0001", "S-0002", "S-0003"],
             "times": {"S-0001": {"t": 0, "conf": "高"}, "S-0003": {"t": 2, "conf": "高"}},
             "outlines": ["S-0008"], "offset": 0, "end": {"state": "待定", "note": "", "last": "S-0003"}, "order_failed": False},
            {"id": "L-002", "world": "W-01", "name": "乙", "about": "", "status": "draft", "scenes": ["S-0004"],
             "times": {"S-0004": {"t": 1, "conf": "低"}}, "outlines": [], "offset": 1,
             "end": {"state": "待定", "note": "", "last": "S-0004"}, "order_failed": False},
            {"id": "L-003", "world": "W-02", "name": "丙", "about": "", "status": "draft", "scenes": ["S-0005"],
             "times": {}, "outlines": [], "offset": None, "end": {"state": "待定", "note": "", "last": "S-0005"}, "order_failed": False},
        ],
        "intersections": [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "r"}],
        "gaps": [{"id": "Q-001", "world": "W-01", "event": "城破", "mentioned_in": ["S-0001"],
                  "thread": "L-002", "after": "S-0004", "before": None}],
        "unassigned": [{"scene": "S-0006", "reason": "模型没分配"}],
        "pending": [{"scene": "S-0007", "thread": "L-002", "reason": "模型建议归入已确认的线"}],
    }


@pytest.fixture
def tbook(book):
    write_json(book.threads_path, sample())
    book.set_step("archive", "done")
    return book


def data_of(book):
    return read_json(book.threads_path)


def archive(book):
    return book.step("archive")["status"]


def test_nothing_to_adjust_before_step_6(book):
    with pytest.raises(FileNotFoundError):
        ops.load_threads(book)


def test_confirm_does_not_outdate_downstream(tbook):
    [t] = ops.confirm(tbook, ["L-001", "L-001"])
    d = data_of(tbook)
    assert t["status"] == "confirmed" and d["threads"][0]["status"] == "confirmed"
    assert d["worlds"][0]["status"] == "confirmed" and archive(tbook) == "done"
    with pytest.raises(KeyError):
        ops.confirm(tbook, ["L-099"])


def test_rename(tbook):
    assert ops.rename(tbook, "L-002", " 新名 ")["name"] == "新名"
    d = data_of(tbook)
    assert d["threads"][1]["status"] == "confirmed" and d["worlds"][0]["status"] == "confirmed"
    assert archive(tbook) == "outdated"
    ops.rename(tbook, "W-02", "仙界")
    assert data_of(tbook)["worlds"][1] == {**sample()["worlds"][1], "name": "仙界", "status": "confirmed"}
    with pytest.raises(ValueError):
        ops.rename(tbook, "L-001", "  ")
    with pytest.raises(KeyError):
        ops.rename(tbook, "W-09", "x")


def test_move_scenes_within_and_across(tbook):
    ops.move_scenes(tbook, ["S-0003"], "L-001", position=0)
    t = data_of(tbook)["threads"][0]
    assert t["scenes"] == ["S-0003", "S-0001", "S-0002"] and t["status"] == "confirmed"
    assert t["times"]["S-0003"] == {"t": 2, "conf": "高"}  # 同一条线里调顺序，时间留着
    assert t["end"]["last"] == "S-0002"
    ops.move_scenes(tbook, ["S-0006", "S-0007", "S-0009", "S-0004"], "L-001")
    d = data_of(tbook)
    assert d["threads"][0]["scenes"][-4:] == ["S-0006", "S-0007", "S-0009", "S-0004"]
    assert "S-0004" not in d["threads"][0]["times"]  # 别的线挪来的不带时间
    assert d["unassigned"] == [] and d["pending"] == [] and d["worlds"][0]["notes"] == []
    ops.move_scenes(tbook, ["S-0008"], "L-003", as_outline=True)
    assert data_of(tbook)["threads"][-1]["outlines"] == ["S-0008"]
    with pytest.raises(ValueError):
        ops.move_scenes(tbook, ["S-0404"], "L-001")
    with pytest.raises(ValueError):
        ops.move_scenes(tbook, [], "L-001")
    with pytest.raises(KeyError):
        ops.move_scenes(tbook, ["S-0001"], "L-099")


def test_emptied_thread_is_removed_and_references_fixed(tbook):
    ops.move_scenes(tbook, ["S-0004"], "L-001")
    d = data_of(tbook)
    assert [t["id"] for t in d["threads"]] == ["L-001", "L-003"]
    assert d["intersections"] == []
    assert (d["gaps"][0]["thread"], d["gaps"][0]["after"]) == (None, None)
    assert d["unassigned"][-1] == {"scene": "S-0007", "reason": "建议归入的线已被删除"}


def test_merge_threads(tbook):
    keep = ops.merge_threads(tbook, ["L-001", "L-002"])
    d = data_of(tbook)
    assert keep["scenes"] == ["S-0001", "S-0002", "S-0003", "S-0004"]
    assert [t["id"] for t in d["threads"]] == ["L-001", "L-003"]
    assert "S-0004" not in d["threads"][0]["times"]
    assert d["pending"][0]["thread"] == "L-001" and d["gaps"][0]["thread"] == "L-001"
    assert d["gaps"][0]["after"] == "S-0004" and archive(tbook) == "outdated"
    with pytest.raises(ValueError):
        ops.merge_threads(tbook, ["L-001"])


def test_split_thread(tbook):
    new = ops.split_thread(tbook, "L-001", "S-0002")
    d = data_of(tbook)
    assert new["id"] == "L-004" and new["scenes"] == ["S-0002", "S-0003"]
    assert new["times"] == {"S-0003": {"t": 2, "conf": "高"}} and new["name"] == "甲（拆出）"
    assert [t["id"] for t in d["threads"]] == ["L-001", "L-004", "L-002", "L-003"]
    assert d["threads"][0]["scenes"] == ["S-0001"] and d["next_thread"] == 5
    assert d["intersections"] == []  # 交汇点对着的主线块 S-0002 被拆到新线了
    with pytest.raises(ValueError):
        ops.split_thread(tbook, "L-001", "S-0001")  # 现在 S-0001 是第一块
    with pytest.raises(ValueError):
        ops.split_thread(tbook, "L-001", "S-0404")


def test_set_main_and_move_thread(tbook):
    ops.set_main(tbook, "L-003")
    d = data_of(tbook)
    assert (d["main_thread"], d["main_by"]) == ("L-003", "author") and archive(tbook) == "outdated"
    ops.move_thread(tbook, "L-003", "W-01")
    d = data_of(tbook)
    assert d["threads"][2]["world"] == "W-01" and [w["id"] for w in d["worlds"]] == ["W-01"]
    with pytest.raises(KeyError):
        ops.move_thread(tbook, "L-001", "W-09")
    with pytest.raises(KeyError):
        ops.set_main(tbook, "L-099")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_threads_ops.py -q`
Expected: FAIL（`ImportError: cannot import name 'threads_ops'`）

- [ ] **Step 3: 实现**

`src/ligaotai/threads_ops.py`：
```python
"""步骤 6 的作者调整：确认、改名、挪块、合并线、拆线、设主线、挪线。

每个操作「读 → 改 → 写」整段在 FILE_LOCK 里，跟 run_threads 的写回、跟彼此都串行。
作者动过的线（和它所在的世界）都算已确认，重跑时原样保留。
内容真的变了（不只是确认状态）才把下游（步骤 7）标过期。"""

from __future__ import annotations

from .book import FILE_LOCK, Book
from .fsutil import read_json, write_json
from .threads import CONFIRMED, content_signature, next_number, thread_id

GONE_PENDING = "建议归入的线已被删除"


def load_threads(book: Book) -> dict:
    data = read_json(book.threads_path)
    if data is None:
        raise FileNotFoundError("还没有归线结果，先跑步骤 6")
    return data


def _thread(data: dict, tid: str) -> dict:
    for t in data["threads"]:
        if t["id"] == tid:
            return t
    raise KeyError(tid)


def _world(data: dict, wid: str) -> dict:
    for w in data["worlds"]:
        if w["id"] == wid:
            return w
    raise KeyError(wid)


def _touch(data: dict, t: dict) -> None:
    """作者动过这条线：线和它所在的世界都算已确认。"""
    t["status"] = CONFIRMED
    _world(data, t["world"])["status"] = CONFIRMED


def _all_scene_ids(data: dict) -> set[str]:
    ids = {s for t in data["threads"] for s in t["scenes"] + t["outlines"]}
    ids |= {s for w in data["worlds"] for s in w.get("notes", []) + w.get("outlines", [])}
    ids |= {u["scene"] for u in data.get("unassigned", [])}
    ids |= {p["scene"] for p in data.get("pending", [])}
    return ids


def _remove(data: dict, ids: set[str]) -> None:
    for t in data["threads"]:
        t["scenes"] = [s for s in t["scenes"] if s not in ids]
        t["outlines"] = [s for s in t["outlines"] if s not in ids]
        t["times"] = {k: v for k, v in (t.get("times") or {}).items() if k not in ids}
    for w in data["worlds"]:
        w["notes"] = [s for s in w.get("notes", []) if s not in ids]
        w["outlines"] = [s for s in w.get("outlines", []) if s not in ids]
    data["unassigned"] = [u for u in data.get("unassigned", []) if u["scene"] not in ids]
    data["pending"] = [p for p in data.get("pending", []) if p["scene"] not in ids]


def _tidy(data: dict) -> None:
    for t in data["threads"]:
        if not t["scenes"]:
            w = next((w for w in data["worlds"] if w["id"] == t["world"]), None)
            if w is not None:
                w.setdefault("outlines", []).extend(t["outlines"])
    data["threads"] = [t for t in data["threads"] if t["scenes"]]
    by_id = {t["id"]: t for t in data["threads"]}
    for t in data["threads"]:
        t["end"] = {**(t.get("end") or {}), "last": t["scenes"][-1]}
    pending = data.get("pending", [])
    data["pending"] = [p for p in pending if p["thread"] in by_id]
    data["unassigned"] = data.get("unassigned", []) + [
        {"scene": p["scene"], "reason": GONE_PENDING} for p in pending if p["thread"] not in by_id
    ]
    alive = {t["world"] for t in data["threads"]}
    data["worlds"] = [w for w in data["worlds"] if w["id"] in alive or w.get("notes") or w.get("outlines")]
    if data.get("main_thread") not in by_id:
        best = max(data["threads"], key=lambda t: len(t["scenes"]), default=None)
        data["main_thread"] = best["id"] if best else None
        data["main_by"] = "auto"
    main = by_id.get(data["main_thread"])
    data["intersections"] = [
        c for c in data.get("intersections", [])
        if c["thread"] in by_id and c["thread"] != data["main_thread"]
        and c["scene"] in by_id[c["thread"]]["scenes"]
        and main is not None and c["main_scene"] in main["scenes"]
    ]
    for g in data.get("gaps", []):
        t = by_id.get(g.get("thread"))
        if t is None:
            g["thread"] = g["after"] = g["before"] = None
            continue
        for k in ("after", "before"):
            if g.get(k) not in t["scenes"]:
                g[k] = None


def _save(book: Book, data: dict, before: str) -> None:
    """整理后写回；内容签名变了才让下游过期。要在 FILE_LOCK 里调。"""
    _tidy(data)
    write_json(book.threads_path, data)
    if content_signature(data) != before:
        book.mark_downstream_outdated("threads")


def confirm(book: Book, ids: list[str]) -> list[dict]:
    with FILE_LOCK:
        data = load_threads(book)
        before = content_signature(data)
        ts = [_thread(data, tid) for tid in dict.fromkeys(ids)]  # 有找不到的就在改动前抛 KeyError
        for t in ts:
            _touch(data, t)
        _save(book, data, before)
    return ts


def rename(book: Book, oid: str, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("名字不能为空")
    with FILE_LOCK:
        data = load_threads(book)
        before = content_signature(data)
        if oid.startswith("L-"):
            obj = _thread(data, oid)
            _touch(data, obj)
        else:
            obj = _world(data, oid)
            obj["status"] = CONFIRMED
        obj["name"] = name
        _save(book, data, before)
    return obj


def move_scenes(book: Book, ids: list[str], tid: str, position: int | None = None, as_outline: bool = False) -> dict:
    """把 ids 挪进线 tid 的 scenes（as_outline 时是 outlines），插在 position（拿掉之后的列表里的位置，None = 末尾）。"""
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise ValueError("要挪的块不能为空")
    with FILE_LOCK:
        data = load_threads(book)
        before = content_signature(data)
        t = _thread(data, tid)
        unknown = [s for s in ids if s not in _all_scene_ids(data)]
        if unknown:
            raise ValueError("这些块不在归线结果里：" + "、".join(unknown[:10]))
        own_times = {s: v for s, v in (t.get("times") or {}).items() if s in ids}  # 同一条线里调顺序，时间留着
        _remove(data, set(ids))
        target = t["outlines"] if as_outline else t["scenes"]
        pos = len(target) if position is None else max(0, min(position, len(target)))
        target[pos:pos] = ids
        if not as_outline:
            t["times"].update(own_times)
        _touch(data, t)
        _save(book, data, before)
    return t


def merge_threads(book: Book, ids: list[str]) -> dict:
    ids = list(dict.fromkeys(ids))
    if len(ids) < 2:
        raise ValueError("至少要选两条线才能合并")
    with FILE_LOCK:
        data = load_threads(book)
        before = content_signature(data)
        ts = [_thread(data, tid) for tid in ids]
        keep, rest = ts[0], ts[1:]
        gone = {t["id"] for t in rest}
        for t in rest:  # 别的线的时间是它们自己的线内时间，合进来对不上，不带
            keep["scenes"] += t["scenes"]
            keep["outlines"] += t["outlines"]
        data["threads"] = [t for t in data["threads"] if t["id"] not in gone]
        for p in data.get("pending", []):
            if p["thread"] in gone:
                p["thread"] = keep["id"]
        for g in data.get("gaps", []):
            if g.get("thread") in gone:
                g["thread"] = keep["id"]
        if data.get("main_thread") in gone:
            data["main_thread"] = keep["id"]
        _touch(data, keep)
        _save(book, data, before)
    return keep


def split_thread(book: Book, tid: str, from_scene: str) -> dict:
    with FILE_LOCK:
        data = load_threads(book)
        before = content_signature(data)
        t = _thread(data, tid)
        if from_scene not in t["scenes"]:
            raise ValueError(f"{from_scene} 不在 {tid} 里")
        i = t["scenes"].index(from_scene)
        if i == 0:
            raise ValueError("从第一块拆就是整条线，不用拆")
        n = next_number(data, "thread")
        data["next_thread"] = n + 1
        moving = t["scenes"][i:]
        times = t.get("times") or {}
        new = {
            "id": thread_id(n), "world": t["world"], "name": f"{t['name']}（拆出）", "about": "",
            "status": CONFIRMED, "scenes": moving, "times": {s: v for s, v in times.items() if s in moving},
            "outlines": [], "offset": t.get("offset"), "end": {"state": "待定", "note": ""}, "order_failed": False,
        }
        t["scenes"] = t["scenes"][:i]
        t["times"] = {s: v for s, v in times.items() if s in t["scenes"]}
        _touch(data, t)
        data["threads"].insert(data["threads"].index(t) + 1, new)
        _save(book, data, before)
    return new


def set_main(book: Book, tid: str) -> dict:
    with FILE_LOCK:
        data = load_threads(book)
        before = content_signature(data)
        t = _thread(data, tid)
        data["main_thread"], data["main_by"] = tid, "author"
        _save(book, data, before)
    return t


def move_thread(book: Book, tid: str, wid: str) -> dict:
    with FILE_LOCK:
        data = load_threads(book)
        before = content_signature(data)
        t = _thread(data, tid)
        _world(data, wid)  # 世界不存在就在改动前抛 KeyError
        t["world"] = wid
        _touch(data, t)
        _save(book, data, before)
    return t
```

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_threads_ops.py -q`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/threads_ops.py tests/test_threads_ops.py
git commit -m "feat: 归线的作者调整（确认/改名/挪块/合并/拆线/设主线/挪线）"
```

---
## Task 16: API——跑步骤 6、读结果、作者操作

**Files:**
- Modify: `src/ligaotai/api.py`
- Modify: `tests/test_api.py:93-95`（threads 现在是合法步骤了）
- Test: `tests/test_api_threads.py`（新）

接口：

| 方法 | 路径 | 请求体 | 作用 |
|---|---|---|---|
| POST | `/api/books/{name}/steps/threads/run` | — | 跑步骤 6（上游没做完 409） |
| GET | `/api/books/{name}/threads` | — | 读 `世界与支线.json`（没有就给空的 worlds / threads） |
| POST | `/api/books/{name}/threads/confirm` | `{"ids": [...]}` | 确认线 |
| PUT | `/api/books/{name}/threads/main` | `{"thread": "L-001"}` | 设主线 |
| POST | `/api/books/{name}/threads/merge` | `{"ids": [...]}` | 合并线 |
| PUT | `/api/books/{name}/threads/{oid}/name` | `{"name": "..."}` | 改线名 / 世界名 |
| POST | `/api/books/{name}/threads/{tid}/scenes` | `{"ids": [...], "position": 0, "as_outline": false}` | 挪块进线 |
| POST | `/api/books/{name}/threads/{tid}/split` | `{"from_scene": "S-0003"}` | 拆线 |
| PUT | `/api/books/{name}/threads/{tid}/world` | `{"world": "W-01"}` | 挪线到别的世界 |

错误：找不到线 / 世界 404，还没跑过步骤 6 也是 404，参数不对 400。

- [ ] **Step 1: 改 test_api.py 里过时的断言**

`tests/test_api.py` 的 `test_errors` 里，把
```python
    # threads 是计划②b 才做的步骤，现在还不能跑；cards 从任务 12 起是合法步骤名
    # （上游没做完时返回 409，见 test_entities_need_cards_first 之类的测试）。
    assert client.post("/api/books/我的书/steps/threads/run").status_code == 400
```
换成
```python
    # threads 从计划②b 起是合法步骤名，上游没做完时返回 409；archive（计划②c）还不能跑，返回 400。
    assert client.post("/api/books/我的书/steps/threads/run").status_code == 409
    assert client.post("/api/books/我的书/steps/archive/run").status_code == 400
```

- [ ] **Step 2: 写失败的测试**

`tests/test_api_threads.py`：
```python
import pytest
from fastapi.testclient import TestClient
from helpers import FakeBackend, fake_ai_handler, threads_handler

from ligaotai.api import create_app

STORY = {
    "1.txt": "第一章 雪夜\n林清年方十六，住在青州城外。\n\n第二章 离城\n清儿背着包袱出了门，赵五在后面跟着。",
    "2.txt": "第三章 天机\n林姑娘进了天机阁，赵五守在门口。",
}
BOOK = "/api/books/我的书"


def make_client(tmp_path):
    fake = FakeBackend(handler=threads_handler(fallback=fake_ai_handler([["林清", "清儿", "林姑娘"]])))
    app = create_app(app_dir=tmp_path, allowed_hosts=("testserver",), backend_factory=lambda cfg: fake)
    return TestClient(app)


def wait(client, response):
    assert response.status_code == 202, response.text
    job = client.app.state.runner.wait(response.json()["id"]).to_dict()
    assert job["status"] == "done", job["error"]
    return job


@pytest.fixture
def carded(tmp_path):
    c = make_client(tmp_path)
    src = tmp_path / "稿"
    src.mkdir()
    for name, text in STORY.items():
        (src / name).write_text(text, encoding="utf-8")
    c.post("/api/books", json={"title": "我的书"})
    wait(c, c.post(f"{BOOK}/import", json={"folder": str(src)}))
    for step in ("split", "dedup", "cards"):
        wait(c, c.post(f"{BOOK}/steps/{step}/run"))
    return c


@pytest.fixture
def ready(carded):
    wait(carded, carded.post(f"{BOOK}/steps/entities/run"))
    return carded


def test_threads_need_entities_first(carded):
    assert carded.post(f"{BOOK}/steps/threads/run").status_code == 409


def test_threads_flow(ready):
    c = ready
    wait(c, c.post(f"{BOOK}/steps/threads/run"))
    [t] = c.get(f"{BOOK}/threads").json()["threads"]
    assert t["id"] == "L-001" and t["scenes"] == ["S-0001", "S-0002", "S-0003"]
    assert c.post(f"{BOOK}/threads/confirm", json={"ids": ["L-001"]}).json()[0]["status"] == "confirmed"
    assert c.put(f"{BOOK}/threads/L-001/name", json={"name": "林清的路"}).json()["name"] == "林清的路"
    assert c.put(f"{BOOK}/threads/W-01/name", json={"name": "人间"}).json()["name"] == "人间"
    moved = c.post(f"{BOOK}/threads/L-001/scenes", json={"ids": ["S-0003"], "position": 0}).json()
    assert moved["scenes"] == ["S-0003", "S-0001", "S-0002"]
    new = c.post(f"{BOOK}/threads/L-001/split", json={"from_scene": "S-0001"}).json()
    assert new["id"] == "L-002" and new["scenes"] == ["S-0001", "S-0002"]
    merged = c.post(f"{BOOK}/threads/merge", json={"ids": ["L-001", "L-002"]}).json()
    assert merged["scenes"] == ["S-0003", "S-0001", "S-0002"]
    assert c.put(f"{BOOK}/threads/main", json={"thread": "L-001"}).json()["id"] == "L-001"
    assert c.put(f"{BOOK}/threads/L-001/world", json={"world": "W-01"}).json()["world"] == "W-01"
    assert c.get(BOOK).json()["usage"]["by_step"]["threads"]["calls"] == 3  # 划世界、划支线、排序


def test_threads_errors(ready):
    c = ready
    assert c.get(f"{BOOK}/threads").json()["threads"] == []
    assert c.post(f"{BOOK}/threads/confirm", json={"ids": ["L-001"]}).status_code == 404  # 还没跑步骤 6
    wait(c, c.post(f"{BOOK}/steps/threads/run"))
    assert c.post(f"{BOOK}/threads/confirm", json={"ids": ["L-099"]}).status_code == 404
    assert c.put(f"{BOOK}/threads/L-001/name", json={"name": " "}).status_code == 400
    assert c.post(f"{BOOK}/threads/merge", json={"ids": ["L-001"]}).status_code == 400
    assert c.post(f"{BOOK}/threads/L-001/scenes", json={"ids": ["S-0404"]}).status_code == 400
    assert c.post(f"{BOOK}/threads/L-001/split", json={"from_scene": "S-0001"}).status_code == 400
    assert c.put(f"{BOOK}/threads/L-001/world", json={"world": "W-09"}).status_code == 404
    assert c.put(f"{BOOK}/threads/main", json={"thread": "L-099"}).status_code == 404
```

推演：三块都是正文、没有 refs（假场景卡不写 refs_elsewhere），所以不找缺口；只有一条线，不对齐。排序时 1.txt 的两块是一个片段，2.txt 一块，片段顺序是 1.txt、2.txt，默认回复按列出的顺序排，结果 `S-0001, S-0002, S-0003`。

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_api_threads.py tests/test_api.py -q`
Expected: 新测试 FAIL（threads 还不在 RUNNABLE 里，返回 400）

- [ ] **Step 4: 实现**

`src/ligaotai/api.py`：
- import 区加：
```python
from . import threads_ops as tops
from .threads import run_threads
```
- `RUNNABLE = ("split", "dedup", "cards", "entities")` 改成 `RUNNABLE = ("split", "dedup", "cards", "entities", "threads")`
- `class SplitReq` 之后加：
```python
class NameReq(BaseModel):
    name: str


class MoveReq(BaseModel):
    ids: list[str]
    position: int | None = None
    as_outline: bool = False


class SplitThreadReq(BaseModel):
    from_scene: str


class MainThreadReq(BaseModel):
    thread: str


class WorldReq(BaseModel):
    world: str
```
- `step_work` 里，`if step == "cards": ...` 之后、`return lambda p: ent.run_entities(...)` 之前加：
```python
        if step == "threads":
            return lambda p: run_threads(book, client, p)
```
- `entity_op` 之后加：
```python
    def thread_op(fn: Callable[[], object]):
        try:
            return fn()
        except KeyError:
            raise HTTPException(404, "没有这条线或这个世界")
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
```
- `split_entity` 接口之后加：
```python
    @app.get("/api/books/{name}/threads")
    def threads(name: str) -> dict:
        b = get_book(name)
        return read_json(b.threads_path, {"worlds": [], "threads": []})

    @app.post("/api/books/{name}/threads/confirm")
    def confirm_threads(name: str, req: IdsReq) -> list:
        b = get_book(name)
        return thread_op(lambda: tops.confirm(b, req.ids))

    @app.put("/api/books/{name}/threads/main")
    def set_main_thread(name: str, req: MainThreadReq) -> dict:
        b = get_book(name)
        return thread_op(lambda: tops.set_main(b, req.thread))

    @app.post("/api/books/{name}/threads/merge")
    def merge_threads(name: str, req: IdsReq) -> dict:
        b = get_book(name)
        return thread_op(lambda: tops.merge_threads(b, req.ids))

    @app.put("/api/books/{name}/threads/{oid}/name")
    def rename_thread(name: str, oid: str, req: NameReq) -> dict:
        b = get_book(name)
        return thread_op(lambda: tops.rename(b, oid, req.name))

    @app.post("/api/books/{name}/threads/{tid}/scenes")
    def move_scenes(name: str, tid: str, req: MoveReq) -> dict:
        b = get_book(name)
        return thread_op(lambda: tops.move_scenes(b, req.ids, tid, req.position, req.as_outline))

    @app.post("/api/books/{name}/threads/{tid}/split")
    def split_thread(name: str, tid: str, req: SplitThreadReq) -> dict:
        b = get_book(name)
        return thread_op(lambda: tops.split_thread(b, tid, req.from_scene))

    @app.put("/api/books/{name}/threads/{tid}/world")
    def move_thread(name: str, tid: str, req: WorldReq) -> dict:
        b = get_book(name)
        return thread_op(lambda: tops.move_thread(b, tid, req.world))
```

- [ ] **Step 5: 跑测试**

Run: `uv run pytest -q`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add src/ligaotai/api.py tests/test_api.py tests/test_api_threads.py
git commit -m "feat: 步骤 6 的接口（跑归线、读结果、作者调整）"
```

---

## Task 17: 弄乱脚本加 --aliases + 熟悉度探测

**Files:**
- Modify: `tools/scramble.py`（`main` 加 `--aliases`）
- Create: `tools/probe_book.py`
- Test: `tests/test_scramble.py`（追加）、`tests/test_probe_book.py`（新）

要点（②b 设计 6.1）：
- 冷门书要换它自己的三个主要人物的别名，西游记的默认别名用不上。`--aliases` 指向一个 JSON 文件，格式同 `DEFAULT_ALIASES`；不给就用默认的。`scramble()` 本来就会检查别名不能已经出现在原文里。
- 熟悉度探测：不给原文，只问模型「这本书各回讲了什么」，一次综合档调用。报告把模型的回答和原书回目并排放，人工对照判断。模型给的回数 `n` 可能是字符串，要转成整数。

- [ ] **Step 1: 写失败的测试**

`tests/test_scramble.py` 末尾追加：
```python
def test_main_accepts_custom_aliases(tmp_path):
    chapters = make_chapters(30)
    src = tmp_path / "book.txt"
    src.write_text("\n".join(f"{c.heading}\n{c.body}" for c in chapters), encoding="utf-8")
    aliases = tmp_path / "aliases.json"
    aliases.write_text(
        json.dumps([{"replaces": "八戒", "alias": "豬先生", "canonical": "豬八戒"}], ensure_ascii=False), encoding="utf-8"
    )
    out = tmp_path / "乱稿"
    main(["--src", str(src), "--out", str(out), "--seed", "5", "--aliases", str(aliases)])
    key = json.loads((tmp_path / "乱稿-答案.json").read_text(encoding="utf-8"))
    assert [a["alias"] for a in key["aliases"]] == ["豬先生"] and key["aliases"][0]["chapters"]
```
（`main` 如果还没在文件顶部的 `from tools.scramble import (...)` 里，就加进去。）

`tests/test_probe_book.py`：
```python
import json

from helpers import FakeBackend

from ligaotai.config import AppConfig
from tools.probe_book import probe
from tools.scramble import Chapter


def test_probe_puts_model_answers_next_to_headings():
    reply = json.dumps({"known": "有印象", "chapters": [{"n": "1", "plot": "开头"}, {"n": 2, "plot": None}, {"n": "x"}]},
                       ensure_ascii=False)
    chapters = [Chapter(1, "第一回 甲", "正文"), Chapter(2, "第二回 乙", "正文")]
    r = probe("某书", chapters, AppConfig(), FakeBackend(replies=[reply]))
    assert r["known"] == "有印象" and (r["answered"], r["chapters"], r["calls"]) == (1, 2, 1)
    assert r["rows"] == [
        {"n": 1, "heading": "第一回 甲", "model": "开头"},
        {"n": 2, "heading": "第二回 乙", "model": None},
    ]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_scramble.py tests/test_probe_book.py -q`
Expected: 新测试 FAIL（`unrecognized arguments: --aliases`、`ModuleNotFoundError: No module named 'tools.probe_book'`）

- [ ] **Step 3: 实现 --aliases**

`tools/scramble.py` 的 `main` 里：
- `ap.add_argument("--seed", type=int, default=7)` 之后加：
```python
    ap.add_argument("--aliases", help="JSON 文件：替换规则列表，每条有 replaces / alias / canonical；不给就用西游记的默认别名")
```
- `key = scramble(chapters, out, args.seed)` 换成：
```python
    aliases = json.loads(Path(args.aliases).read_text(encoding="utf-8")) if args.aliases else DEFAULT_ALIASES
    key = scramble(chapters, out, args.seed, aliases=aliases)
```
- 文件开头 docstring 的用法里加一行：
```
  uv run python tools/scramble.py --src data/pg26739.txt --out data/乱稿-雪月梅 --seed 7 --aliases data/别名-雪月梅.json
```

- [ ] **Step 4: 实现 probe_book.py**

`tools/probe_book.py`：
```python
"""真跑验收前的「熟悉度」探测：不给原文，只问模型记不记得这本书各回讲了什么。

模型能按顺序大致说出多数回目的情节，说明它背过这本书，拿它做顺序验收会偏乐观（它可以凭记忆排），
要换一本。报告里把模型的回答和原书的回目并排放，人工对照判断。一次综合档调用，花费几美分。

用法：
  uv run python tools/probe_book.py --title 雪月梅傳 --src data/pg26739.txt --report data/验收-熟悉度-雪月梅傳.json
终端只打 ASCII，中文内容看报告文件。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from ligaotai.config import AppConfig, load_config
from ligaotai.llm import ChatBackend, LLMClient, NoKeyError, OpenAIBackend
from tools.scramble import Chapter, parse_chapters, strip_gutenberg

SYSTEM = "你是中国古典小说专家。只凭记忆回答，记不清就老实说记不清，不要编。只输出一个 json 对象。"
USER = (
    "清代小说《{title}》一共 {n} 回。请凭记忆，按顺序写出每一回的主要情节，每回一句话；记不清的回写 null。"
    "known 说明你对这本书熟不熟，只能是「熟悉」「有印象」「不知道」。\n"
    '格式（示例）：{{"known": "有印象", "chapters": [{{"n": 1, "plot": "……"}}, {{"n": 2, "plot": null}}]}}'
)


def _check(d: dict) -> list[str]:
    return [] if isinstance(d.get("chapters"), list) else ["缺少 chapters 列表"]


def probe(title: str, chapters: list[Chapter], cfg: AppConfig, backend: ChatBackend) -> dict:
    client = LLMClient(cfg, backend)
    data, problems = asyncio.run(
        client.chat_json("synth", SYSTEM, USER.format(title=title, n=len(chapters)), _check, tag="probe")
    )
    answers: dict[int, object] = {}
    for c in data.get("chapters") or []:
        if not isinstance(c, dict):
            continue
        try:
            answers[int(c.get("n"))] = c.get("plot")
        except (TypeError, ValueError):
            continue
    rows = [{"n": c.num, "heading": c.heading, "model": answers.get(c.num)} for c in chapters]
    return {
        "title": title,
        "known": data.get("known"),
        "answered": sum(1 for r in rows if r["model"]),
        "chapters": len(rows),
        "rows": rows,
        "problems": problems,
        "calls": client.usage.calls,
        "cost_usd": round(client.usage.cost(cfg), 4),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="ask the model whether it remembers a book before using it for evaluation")
    ap.add_argument("--title", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args(argv)
    cfg = load_config()
    try:
        backend = OpenAIBackend(cfg)
    except NoKeyError:
        sys.exit("no API key configured (config.json api_key or env LIGAOTAI_API_KEY)")
    raw = Path(args.src).read_text(encoding="utf-8")
    report = probe(args.title, parse_chapters(strip_gutenberg(raw)), cfg, backend)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"answered={report['answered']}/{report['chapters']} calls={report['calls']} cost_usd={report['cost_usd']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 跑测试**

Run: `uv run pytest tests/test_scramble.py tests/test_probe_book.py -q`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add tools/scramble.py tools/probe_book.py tests/test_scramble.py tests/test_probe_book.py
git commit -m "feat: 弄乱脚本支持自定义别名；真跑前的熟悉度探测"
```

---
## Task 18: 顺序验收脚本（eval_threads.py）

**Files:**
- Create: `tools/eval_threads.py`
- Test: `tests/test_eval_threads.py`

要点（②b 设计 6.2、6.3）：
- **书**：沿用 `eval_entities` 的书名（`验收-实体-<乱稿文件夹名>-s<seed>`）和它的 `open_or_create`、`_check_manifest`，西游记那本书的场景卡和实体合并直接复用、走缓存不花钱。
- **标准位置**：块的 `source` 是「乱稿文件夹名/答案里的 path」，查到（第几回, 第几片），再加块在文件里的 `index`，就是（回, 片, 块）三元组，直接比大小。来源不在答案里的块不算。
- **Kendall τ-b**：自己写（几百块，O(n²) 够用），能处理并列（两个不同文件的块标准位置相同）。每条线算一个，按块对数加权平均，≥ 0.8 通过。
- **片段级 τ**：同一个源文件里的块对不算（它们本来就按原文顺序绑着排，白送分），只记录。
- **只记录**：线的条数和块数、未分配、建议归入、被删的回（人工拿缺口清单对照）、被截断的回（它最后一块是不是所在线的最后一块）。
- **费用粗估**（`--estimate`）：只做导入 / 切场景 / 查重，不调模型。按 ②a 实测参数算：场景卡每次调用约 6.6k 输入、1.24k 输出，每卡平均 1.75 次；实体合并约每个场景 $0.0013（场景卡都新鲜且实体合并已做过就算 0，走缓存）；归线按「5 倍全部行的字数」算输入、「(3 + 场景数/25) 次调用 × 每次 8k 输出」算输出。偏保守，保留 4 位小数。

- [ ] **Step 1: 写失败的测试**

`tests/test_eval_threads.py`：
```python
from helpers import FakeBackend, fake_ai_handler, make_chapters, seed_book, threads_handler

from ligaotai.config import AppConfig
from tools.eval_threads import estimate, evaluate, kendall_tau_b, run_eval, truth_positions
from tools.scramble import scramble

SMALL = dict(n_delete=2, n_truncate=2, n_full=3, n_excerpt=2, alias_chapters=5)
GROUPS = [["悟空", "金箍郎"], ["八戒", "天蓬郎"], ["唐僧", "御弟師父"]]


def test_kendall_tau_b():
    assert kendall_tau_b([0, 1, 2], [1, 2, 3]) == (1.0, 3)
    assert kendall_tau_b([0, 1, 2], [3, 2, 1]) == (-1.0, 3)
    tau, n = kendall_tau_b([0, 1, 2], [1, 3, 2])
    assert n == 3 and abs(tau - 1 / 3) < 1e-9
    tau, n = kendall_tau_b([0, 1, 2], [(1, 0), (1, 0), (2, 0)])  # 前两块标准位置并列
    assert n == 3 and abs(tau - 2 / 6 ** 0.5) < 1e-9
    assert kendall_tau_b([0], [5]) == (None, 0)
    assert kendall_tau_b([0, 1, 2], [3, 2, 1], keep=lambda i, j: (i, j) == (0, 1)) == (-1.0, 1)


def test_truth_positions(book):
    seed_book(book, [
        {"id": "S-0001", "source": "乱稿/x.txt", "index": 0},
        {"id": "S-0002", "source": "乱稿/x.txt", "index": 1},
        {"id": "S-0003", "source": "乱稿/y.txt", "index": 0},
        {"id": "S-0004", "source": "别的/z.txt", "index": 0},
    ])
    key = {"files": [{"path": "x.txt", "chapter": 3, "piece": 2}, {"path": "y.txt", "chapter": 1, "piece": 1}]}
    assert truth_positions(book, key, "乱稿") == {"S-0001": (3, 2, 0), "S-0002": (3, 2, 1), "S-0003": (1, 1, 0)}


def test_evaluate():
    pos = {"S-0001": (1, 1, 0), "S-0002": (1, 1, 1), "S-0003": (2, 1, 0), "S-0004": (3, 1, 0)}
    source_of = {"S-0001": "a", "S-0002": "a", "S-0003": "b", "S-0004": "c"}
    data = {"worlds": [], "threads": [
        {"id": "L-001", "name": "甲", "scenes": ["S-0001", "S-0002", "S-0004", "S-0003"], "end": {}},
        {"id": "L-002", "name": "乙", "scenes": ["S-0099"], "end": {}},
    ], "unassigned": [], "pending": [], "gaps": []}
    key = {"deleted": [5], "truncated": [{"chapter": 3, "kept_ratio": 0.5}]}
    r = evaluate(data, pos, source_of, key)
    # L-001：6 对里 5 对顺、1 对反（S-0004 排在了 S-0003 前面）→ τ = 4/6
    assert r["threads"][0]["tau"] == round(4 / 6, 4) and r["threads"][0]["pairs"] == 6
    # 片段级去掉同一文件的 S-0001/S-0002 那一对：5 对里 4 顺 1 反 → 3/5
    assert r["threads"][0]["seg_tau"] == 0.6 and r["threads"][0]["seg_pairs"] == 5
    assert r["threads"][1]["tau"] is None
    assert r["tau"] == round(4 / 6, 4) and r["pass"] is False
    assert r["truncated"] == [{"chapter": 3, "last_scene": "S-0004", "thread": "L-001", "is_thread_end": False}]
    assert r["deleted_chapters"] == [5]


def test_estimate(book):
    seed_book(book, [{"id": "S-0001"}, {"id": "S-0002", "no_card": True}])
    est = estimate(book, AppConfig())
    assert est["scenes"] == 2 and est["cards_needed"] == 1
    assert est["cards_usd"] > 0 and est["entities_usd"] > 0 and est["threads_usd"] > 0
    assert est["total_usd"] >= est["threads_usd"]


def test_run_eval_end_to_end_with_fake_model(tmp_path):
    out = tmp_path / "乱稿"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)

    def backend():
        return FakeBackend(handler=threads_handler(fallback=fake_ai_handler(GROUPS)))

    report = run_eval(out, key, tmp_path / "书库", AppConfig(), backend())
    assert report["threads"] and report["tau"] is not None and -1 <= report["tau"] <= 1
    assert report["this_run"]["calls"] > 0
    again = run_eval(out, key, tmp_path / "书库", AppConfig(), backend())
    assert again["this_run"]["calls"] == 0 and again["tau"] == report["tau"]  # 全部走缓存
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_eval_threads.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'tools.eval_threads'`）

- [ ] **Step 3: 实现**

`tools/eval_threads.py`：
```python
"""验收：线内顺序（总 spec 11.3「线内顺序与原书顺序的 Kendall τ ≥ 0.8」，②b 设计 6.2）。

书沿用 eval_entities 的书名（验收-实体-<乱稿文件夹名>-s<seed>）：导入 → 核对原稿清单 → 切场景 →
查重 → 场景卡 → 实体合并 → 归线，做过的都走缓存不花钱。然后对照弄乱脚本的答案算 τ。

用法：
  uv run python tools/eval_threads.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json --estimate
  uv run python tools/eval_threads.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json --report data/验收-归线-西游记.json
--estimate 只做导入 / 切场景 / 查重（不花钱），按 ②a 实测参数粗估要花多少，不调模型，结果写到 <报告名>-估算.json。
终端只打 ASCII，中文内容看报告文件。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Callable

from ligaotai.book import Book
from ligaotai.cards import is_fresh, load_cards, run_cards
from ligaotai.config import AppConfig, load_config
from ligaotai.dedup import run_dedup
from ligaotai.entities import run_entities
from ligaotai.fsutil import read_json, safe_name
from ligaotai.importer import run_import
from ligaotai.llm import ChatBackend, FatalLLMError, LLMClient, NoKeyError, OpenAIBackend
from ligaotai.scenes import load_scenes, run_split
from ligaotai.threads import run_threads
from ligaotai.threads_input import prepare
from tools.eval_entities import TITLE_PREFIX, _check_manifest, open_or_create

PASS_TAU = 0.8
# ②a 验收实测（西游记 268 张卡）：每次调用约 6.6k 输入、1.24k 输出，平均每卡 1.75 次调用；实体合并约每个场景 $0.0013
CARD_IN, CARD_OUT, CARD_CALLS = 6600, 1240, 1.75
ENTITY_USD_PER_SCENE = 0.0013
MISSING_LINE_CHARS = 150  # 还没有卡的块，压成一行大约多长
# 归线粗估：输入约 5 倍全部行（划世界、划支线、排序、对齐、缺口各过一遍）；调用约 3 + 场景数/25 次，每次输出（含思考）约 8k
THREAD_PASSES, THREAD_OUT_PER_CALL, SCENES_PER_CALL = 5, 8000, 25


def kendall_tau_b(xs: list, ys: list, keep: Callable[[int, int], bool] | None = None) -> tuple[float | None, int]:
    """Kendall τ-b（能处理并列）。返回 (τ, 参与比较的块对数)；keep(i, j) 为 False 的块对不算。
    没有可比较的块对（或者全部并列）时 τ 是 None。"""
    p = q = tx = ty = n = 0
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            if keep is not None and not keep(i, j):
                continue
            n += 1
            dx = (xs[i] > xs[j]) - (xs[i] < xs[j])
            dy = (ys[i] > ys[j]) - (ys[i] < ys[j])
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                tx += 1
            elif dy == 0:
                ty += 1
            elif dx == dy:
                p += 1
            else:
                q += 1
    denom = math.sqrt((p + q + tx) * (p + q + ty))
    return ((p - q) / denom if denom else None), n


def truth_positions(book: Book, key: dict, folder_name: str) -> dict[str, tuple[int, int, int]]:
    """每块在原书里的位置：（第几回, 第几片, 文件里第几块）。来源不在答案里的块不算。"""
    root = safe_name(folder_name)
    by_path = {f"{root}/{f['path']}": (f["chapter"], f["piece"]) for f in key["files"]}
    out = {}
    for s in load_scenes(book):
        if s.removed:
            continue
        cp = by_path.get(s.source)
        if cp is not None:
            out[s.id] = (cp[0], cp[1], s.index)
    return out


def _wavg(rows: list[dict], k: str, w: str) -> float | None:
    got = [(r[k], r[w]) for r in rows if r[k] is not None and r[w]]
    den = sum(x for _, x in got)
    return round(sum(v * x for v, x in got) / den, 4) if den else None


def evaluate(data: dict, pos: dict, source_of: dict[str, str], key: dict) -> dict:
    threads = data.get("threads", [])
    rows = []
    for t in threads:
        ids = [s for s in t["scenes"] if s in pos]
        xs, ys = list(range(len(ids))), [pos[s] for s in ids]
        tau, pairs = kendall_tau_b(xs, ys)
        seg, seg_pairs = kendall_tau_b(xs, ys, keep=lambda i, j: source_of.get(ids[i]) != source_of.get(ids[j]))
        rows.append({
            "id": t["id"], "name": t["name"], "scenes": len(t["scenes"]), "scored": len(ids),
            "tau": None if tau is None else round(tau, 4), "pairs": pairs,
            "seg_tau": None if seg is None else round(seg, 4), "seg_pairs": seg_pairs,
            "order_failed": t.get("order_failed", False), "end": t.get("end"),
        })
    thread_of = {s: t["id"] for t in threads for s in t["scenes"]}
    last_of = {t["id"]: t["scenes"][-1] for t in threads if t["scenes"]}
    truncated = []
    for tr in key.get("truncated", []):
        mine = [s for s in thread_of if s in pos and pos[s][0] == tr["chapter"]]
        last = max(mine, key=lambda s: pos[s]) if mine else None
        th = thread_of.get(last)
        truncated.append({"chapter": tr["chapter"], "last_scene": last, "thread": th,
                          "is_thread_end": th is not None and last_of.get(th) == last})
    tau = _wavg(rows, "tau", "pairs")
    return {
        "tau": tau,
        "seg_tau": _wavg(rows, "seg_tau", "seg_pairs"),
        "pass": tau is not None and tau >= PASS_TAU,
        "worlds": [{"id": w["id"], "name": w["name"], "notes": len(w.get("notes", []))} for w in data.get("worlds", [])],
        "threads": rows,
        "unassigned": data.get("unassigned", []),
        "pending": data.get("pending", []),
        "deleted_chapters": key.get("deleted", []),
        "gaps": data.get("gaps", []),
        "truncated": truncated,
    }


def estimate(book: Book, cfg: AppConfig) -> dict:
    scenes = [s for s in load_scenes(book) if not s.removed]
    records = load_cards(book)
    need = sum(1 for s in scenes if not is_fresh(records.get(s.id), s))
    cards_usd = need * CARD_CALLS * (CARD_IN * cfg.price_input + CARD_OUT * cfg.price_output) / 1e6
    entities_done = need == 0 and book.step("entities")["status"] == "done"
    entities_usd = 0.0 if entities_done else len(scenes) * ENTITY_USD_PER_SCENE
    chars = sum(len(i.line) + 1 for i in prepare(book).items.values()) + MISSING_LINE_CHARS * need
    calls = 3 + len(scenes) / SCENES_PER_CALL
    threads_usd = (THREAD_PASSES * chars * cfg.price_input + calls * THREAD_OUT_PER_CALL * cfg.price_output) / 1e6
    return {
        "scenes": len(scenes),
        "cards_needed": need,
        "cards_usd": round(cards_usd, 4),
        "entities_usd": round(entities_usd, 4),
        "threads_usd": round(threads_usd, 4),
        "total_usd": round(cards_usd + entities_usd + threads_usd, 4),
    }


def _open(folder: Path, key: dict, library: Path) -> Book:
    folder = Path(folder).resolve()
    Path(library).mkdir(parents=True, exist_ok=True)
    book = open_or_create(Path(library), f"{TITLE_PREFIX}{folder.name}-s{key['seed']}")
    run_import(book, folder)
    _check_manifest(book, folder, key)
    run_split(book)
    run_dedup(book)
    return book


def run_eval(folder: Path, key: dict, library: Path, cfg: AppConfig, backend: ChatBackend) -> dict:
    book = _open(folder, key, library)
    try:
        cards = run_cards(book, LLMClient(cfg, backend, log_dir=book.logs_dir))
        ents = run_entities(book, LLMClient(cfg, backend, log_dir=book.logs_dir))
        threads = run_threads(book, LLMClient(cfg, backend, log_dir=book.logs_dir))
    except FatalLLMError as e:
        # 欠费 / key 失效：把已经落盘的用量和书路径挂到异常上，main() 好写进报告文件。
        e.book = str(book.root)
        e.usage = book.load().get("usage", {})
        raise
    pos = truth_positions(book, key, Path(folder).resolve().name)
    source_of = {s.id: s.source for s in load_scenes(book)}
    report = evaluate(read_json(book.threads_path), pos, source_of, key)
    parts = (cards, ents, threads)
    report.update(
        book=str(book.root),
        threads_summary=threads,
        this_run={  # 这一次运行的调用 / 花费（跟 usage.total 的累计值分开看）
            "calls": sum(p["calls"] for p in parts),
            "cost_usd": round(sum(p["cost_usd"] for p in parts), 4),
        },
        usage=book.load().get("usage", {}),
        model_tiers={"batch": cfg.batch.model_dump(), "synth": cfg.synth.model_dump()},  # 不含 api_key
    )
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="evaluate thread ordering against a scramble answer key")
    ap.add_argument("--folder", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--library", default="data/验收书库")
    ap.add_argument("--report", default="data/验收-归线.json")
    ap.add_argument("--estimate", action="store_true", help="只粗估费用，不调模型")
    args = ap.parse_args(argv)
    cfg = load_config()
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if args.estimate:
        est = estimate(_open(Path(args.folder), key, Path(args.library)), cfg)
        report_path.with_name(report_path.stem + "-估算.json").write_text(
            json.dumps(est, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(" ".join(f"{k}={v}" for k, v in est.items()))
        return
    try:
        backend = OpenAIBackend(cfg)
    except NoKeyError:
        sys.exit("no API key configured (config.json api_key or env LIGAOTAI_API_KEY)")
    error_path = report_path.with_name(report_path.stem + "-error.json")
    try:
        report = run_eval(Path(args.folder), key, Path(args.library), cfg, backend)
    except FatalLLMError as e:
        partial = {"error": f"{type(e).__name__}: {e}", "book": getattr(e, "book", None), "usage": getattr(e, "usage", {})}
        error_path.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.exit("fatal model error, see the -error report next to your --report path")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    error_path.unlink(missing_ok=True)
    print(
        f"tau={report['tau']} seg_tau={report['seg_tau']} pass={report['pass']} threads={len(report['threads'])} "
        f"unassigned={len(report['unassigned'])} gaps={len(report['gaps'])} "
        f"this_run_calls={report['this_run']['calls']} this_run_cost_usd={report['this_run']['cost_usd']}"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试**

Run: `uv run pytest tests/test_eval_threads.py -q`
Expected: 5 passed

- [ ] **Step 5: 跑全部测试**

Run: `uv run pytest -q`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add tools/eval_threads.py tests/test_eval_threads.py
git commit -m "feat: 归线顺序验收脚本（Kendall τ-b、片段级 τ、费用粗估）"
```

---
## Task 19: 真跑验收（花钱，要作者同意）

**Files:**
- Create: `docs/验收记录/2026-09-XX-计划2b-归线.md`（XX 换成真跑那天）
- 数据（gitignore，不进仓库）：`data/pg26739.txt`、`data/别名-雪月梅.json`、`data/乱稿-雪月梅/`、`data/乱稿-雪月梅-答案.json`、各份报告

这一步不写代码，按顺序做；**每一步的结果都写进报告文件再用 Read 看**（终端中文会乱码）。

- [ ] **Step 1: 连接测试**

Run: `uv run python tools/eval_entities.py --check-only`
Expected: `batch ... ok=True`、`synth ... ok=True`。不通就停下报告，不往下走。

- [ ] **Step 2: 下冷门书 + 熟悉度探测**

```bash
curl -sSL -o data/pg26739.txt https://www.gutenberg.org/cache/epub/26739/pg26739.txt
uv run python tools/probe_book.py --title 雪月梅傳 --src data/pg26739.txt --report data/验收-熟悉度-雪月梅傳.json
```
用 Read 看报告，逐回对照 `heading`（原书回目）和 `model`（模型凭记忆说的）。
- **换书的判据**：`known` 是「熟悉」，或者模型说的情节跟回目对得上的超过一半 → 换《天豹圖》（古腾堡 26904，40 回），重做这一步（`--title 天豹圖 --src data/pg26904.txt`），后面的文件名跟着改。
- 判断结果（对得上几回、依据）要写进验收记录。

- [ ] **Step 3: 挑别名**

1. 写个一次性脚本（放 scratchpad，不进仓库）统计原文里出现最多的几个人名，结果写文件用 Read 看，定下三个主要人物。
2. 每个人物挑一个原文里**完全没出现过**的新叫法（比如在名字后面加「郎」「生」），用 Grep 在 `data/pg26739.txt` 里确认搜不到。
3. 写 `data/别名-雪月梅.json`：`[{"replaces": "原文里的叫法", "alias": "新叫法", "canonical": "规范名"}, …]`，三条。`replaces` 要是原文里真出现的写法（繁体）。

- [ ] **Step 4: 弄乱**

Run: `uv run python tools/scramble.py --src data/pg26739.txt --out data/乱稿-雪月梅 --seed 7 --aliases data/别名-雪月梅.json`
Expected: 打印 `chapters=50 files=… deleted=5 variants=15`。

- [ ] **Step 5: 估算费用，报给作者，等同意**

```bash
uv run python tools/eval_threads.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json --report data/验收-归线-西游记.json --estimate
uv run python tools/eval_threads.py --folder data/乱稿-雪月梅 --key data/乱稿-雪月梅-答案.json --report data/验收-归线-雪月梅.json --estimate
```
把两份 `-估算.json` 的 `total_usd` 加起来，连同明细报给作者。**作者同意之前不许跑下一步。** 估算是粗估（②a 的教训：估少了一倍多），报的时候说明「实际可能到估算的 2 倍」。

- [ ] **Step 6: 真跑**

```bash
uv run python tools/eval_threads.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json --report data/验收-归线-西游记.json
uv run python tools/eval_threads.py --folder data/乱稿-雪月梅 --key data/乱稿-雪月梅-答案.json --report data/验收-归线-雪月梅.json
```
西游记那本书的场景卡和实体合并走缓存，只有归线花钱；雪月梅从场景卡跑起。欠费 / key 失效会写 `-error.json` 并退出。

- [ ] **Step 7: 看报告，人工核**

每本书用 Read 看报告，记下：
- `tau`、`seg_tau`、`pass`；每条线的块数和 τ；有没有 `order_failed`
- 线的条数、未分配、建议归入各多少；抽 5 个未分配的块看原因
- **缺口 vs 被删的回**：拿 `deleted_chapters` 的回目（从原文找回目标题），对照 `gaps` 里的事件，逐条判断「被删的这一回有没有被标成缺口」。只记录，不设门槛
- **截断的回**：`truncated` 里 `is_thread_end` 为 true 的有几个；再看对应线的 `end.note` 有没有说写到一半
- 西游记：线分得是否合理（比如取经缘起、大闹天宫是不是单独成线）

- [ ] **Step 8: 判定**

- 两本的 `tau` 都 ≥ 0.8 → 通过。
- **雪月梅没到 0.8** → 停下来，把报告要点（哪几条线拖了后腿、片段级 τ 多少、看到的错排例子）报给作者，**不自己改提示词重跑**，等作者定。
- 西游记没到 0.8 → 同样停下报告（西游记模型背过，没过说明流程本身有问题）。

- [ ] **Step 9: 写验收记录**

`docs/验收记录/2026-09-XX-计划2b-归线.md`，格式参照 `docs/验收记录/2026-09-12-计划2a-实体合并.md`：
- 日期、模型配置、两本乱稿的来历（书、回数、seed、别名）、代码版本（提交号）
- 熟悉度探测结论（对得上几回、为什么判定为冷门）
- 结果表：τ、片段级 τ、线数、未分配、建议归入、缺口数、被删的回标出了几个、截断的回、调用次数、token、费用（两本分开，再合计）
- 发现的问题（每条写清楚现象、例子、是否已处理）
- 估算 vs 实际花费

```bash
git add "docs/验收记录/2026-09-XX-计划2b-归线.md"
git commit -m "docs: 计划②b 验收记录（归线排序，西游记 + 雪月梅传）"
```

---

## Task 20: 收尾

**Files:**
- Modify: `docs/已知问题与待办.md`
- Modify: `README.md`

- [ ] **Step 1: 更新已知问题文档**

`docs/已知问题与待办.md`：
- 「计划②b 要处理的」一节里「过期判定」那条删掉，改记到已解决（写一句：步骤 6 开跑和跑完各算一次输入指纹，不一样就记 outdated；跑的途中 `世界与支线.json` 被改就不写入）。这一节空了就整节删掉。
- 新加一节「计划②c 要处理的」：
  - 步骤 7 读 `世界与支线.json` 时只认 `status` 以外的内容；线和世界的编号可能因为作者合并 / 拆分而消失，档案要按编号对账，找不到的档案标过期
  - 缺口编号（`Q-…`）每次重跑都会重排，步骤 7 引用缺口要按内容，不按编号
- 「已知局限（暂不处理）」加：
  - **归线**：跨线对齐、找缺口的输入超过 `threads_max_input_tokens` 时直接跳过（记在 `failed_calls`），不分段
  - **归线**：模型建议归入已确认线的块（`pending`）不参与找缺口
  - **归线**：从别的线挪来的块、合并进来的线不带故事时间（不同线的线内时间对不上），要重跑步骤 6 或者作者自己排
  - **归线**：世界按名字沿用编号，模型重跑时给世界换了名字，编号就会变
  - **作者操作**：归线文件的锁也是进程内的，只支持单进程服务（同实体合并）
- 计划③界面要处理的（加进已有的对应一节）：`pending`（建议归入）要让作者一键接受 / 拒绝；`unassigned` 要能拖进线；`order_failed` 的线要醒目提示

- [ ] **Step 2: 更新 README**

`README.md` 里写进度的地方加上计划②b：步骤 6 归线排序（划世界、划支线、线内排序、跨线对齐、找缺口）和作者调整接口已完成，验收结果（两本书的 τ）引用验收记录。**仓库文档里不写作者的名字，也不写本机路径。**

- [ ] **Step 3: 全部测试**

Run: `uv run pytest -q`
Expected: 全部 PASS。记下总数。

- [ ] **Step 4: 检查公开仓库不该出现的东西**

用 Grep 在整个仓库（排除 `data/`、`.venv/`）搜：作者的名字、Windows 用户目录的路径、带盘符的本机绝对路径、以 `sk-` 开头的 key。都不应该有（本计划文件里提到这几类东西时只写了类别，没写具体字符串）。

- [ ] **Step 5: 提交**

```bash
git add docs/已知问题与待办.md README.md
git commit -m "docs: 计划②b 收尾（已知问题、README）"
```

推送到 GitHub 之前**先问作者**。
