# 故事时间线冲突检查 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在矛盾页加「时间线」分页：程序找「人死了又出场（A）」「提前知道后面的事（C）」的嫌疑，模型逐条判，作者逐条裁决。

**Architecture:** `timeline.py` 放纯函数（故事顺序、嫌疑、摘录、拼结果、延续裁决，不调模型）；`timeline_run.py` 调模型分批判、落盘 `时间冲突.json`、提供读/裁决；API 三个路由；前端新组件 `TimelinePanel.vue` 挂进矛盾页的分页。验收：`tools/scramble.py` 加两种植入，`tools/eval_timeline.py` 判卷。

**Tech Stack:** Python 3.11 + FastAPI + pytest（`uv run pytest`）；Vue 3 + TS + Vitest（`cd web && npx vitest run`）。

**Spec:** `docs/superpowers/specs/2026-09-28-ligaotai-timeline-check-design.md`

## 通用规矩（每个任务都适用）

- 只在分支 `todo-0928` 上干（或执行时新开的分支）。**禁止** `git stash` / `git checkout --` / `git reset` / `git restore`；只 `git add` 自己改的文件；小步提交。
- **计划里的代码没跑过**，照抄前先读一遍、对照现有代码核字段名（②c 教训：计划写错键名，测试照抄假数据全绿、真跑全错）。**测试断言是手算的，不许改断言迁就实现**；觉得断言错了，停下来说明理由。
- 写含反斜杠转义的代码用 Write / Edit 工具，不用 bash heredoc（heredoc 会吃反斜杠）。别在工具参数里敲 `\u` 转义，要全角空格就写 `chr(0x3000)`。
- 终端中文会乱码，看中文结果写文件再 Read。
- 本计划的实现与测试**一次模型都不真调**（全用 FakeBackend）。真跑只在最后的验收任务，而且要在 DeepSeek 低峰（工作日 9–12、14–18 之外，周末节假日全天）并先跟作者确认。
- 界面不显示任何费用数字。

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `src/ligaotai/book.py` | 改 | 加 `timeline_path`、`timeline_cache_path` 两个属性 |
| `src/ligaotai/timeline.py` | 新建 | 纯函数：故事顺序、死亡事实、A/C 嫌疑、原文摘录、签名、拼结果、延续裁决、指纹 |
| `src/ligaotai/timeline_run.py` | 新建 | 分批调模型、检查/清理输出、落盘、`load_timeline`（带过期标记）、`set_timeline_verdict` |
| `prompts/timeline_death.md` | 新建 | A 类判「在场 / 提到 / 说不准」 |
| `prompts/timeline_refs.md` | 新建 | C 类判「事情发生在哪一场」 |
| `src/ligaotai/api.py` | 改 | `POST /timeline/run`、`GET /timeline`、`PUT /timeline/{tid}/verdict` |
| `web/src/api/types.ts`、`web/src/api/endpoints.ts` | 改 | 类型和三个接口 |
| `web/src/components/TimelinePanel.vue` | 新建 | 时间线分页 |
| `web/src/pages/ContradictionsPage.vue` | 改 | 顶部加「矛盾 / 时间线」分页切换 |
| `tools/scramble.py` | 改 | `plant_deaths`、`plant_foreknowledge`，CLI 参数 |
| `tools/eval_timeline.py` | 新建 | 召回、没命中归因、全部冲突写成人工核对表 |
| `data/事件-雪月梅.json` | 新建（gitignore，不进仓库） | C 类植入用的事件清单 |
| 测试 | 新建 | `tests/test_timeline.py`、`tests/test_timeline_run.py`、`tests/test_api_timeline.py`、`tests/test_scramble.py`（加）、`tests/test_eval_timeline.py`、`web/src/components/TimelinePanel.test.ts` |

---

### Task 1: 书的两个路径

**Files:**
- Modify: `src/ligaotai/book.py`（`contradictions_path` 属性后面）
- Test: `tests/test_timeline.py`（新建）

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_timeline.py
def test_书有时间冲突的两个路径(book):
    assert book.timeline_path == book.root / "时间冲突.json"
    assert book.timeline_cache_path == book.root / "时间冲突缓存.json"
```

- [ ] **Step 2: 跑，确认失败**

Run: `uv run pytest tests/test_timeline.py -q`
Expected: FAIL，`AttributeError: 'Book' object has no attribute 'timeline_path'`

- [ ] **Step 3: 实现**（`book.py` 里紧跟 `contradictions_path`）

```python
    @property
    def timeline_path(self) -> Path:
        """时间线冲突检查的结果（跟 矛盾.json 一样放书的根目录）。"""
        return self.root / "时间冲突.json"

    @property
    def timeline_cache_path(self) -> Path:
        """时间线检查自己的模型调用缓存，不跟归线 / 档案的缓存混。"""
        return self.root / "时间冲突缓存.json"
```

- [ ] **Step 4: 跑，确认通过**

Run: `uv run pytest tests/test_timeline.py -q` → PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/book.py tests/test_timeline.py
git commit -m "feat(timeline): 书加时间冲突结果和缓存两个路径"
```

---

### Task 2: 故事顺序

用骨架同一个函数 `skeleton_order.build_sequence`，传空看板（不砍线）；移除的块和非主版本照骨架的做法排除。

**Files:**
- Create: `src/ligaotai/timeline.py`
- Test: `tests/test_timeline.py`

- [ ] **Step 1: 写失败的测试**（追加）

```python
from ligaotai.fsutil import write_json
from ligaotai.timeline import story_order


def _threads(book, threads, global_order=None, unassigned=()):
    write_json(book.threads_path, {"threads": threads, "worlds": [], "main_thread": threads[0]["id"],
                                   "global_order": list(global_order or []), "unassigned": list(unassigned),
                                   "pending": [], "gaps": [], "intersections": []})


def _seed(book, specs):
    """specs: [(sid, persons, refs, facts, text)]。facts: [(subject, attribute, value, quote)]"""
    from helpers import seed_book
    from ligaotai.cards import card_path
    from ligaotai.fsutil import read_json
    seed_book(book, [{"id": s, "persons": p, "refs": r, "text": t} for s, p, r, _, t in specs])
    for s, _, _, facts, _ in specs:
        rec = read_json(card_path(book, s))
        rec["card"]["facts"] = [{"subject": a, "attribute": b, "value": c, "quote": q} for a, b, c, q in facts]
        write_json(card_path(book, s), rec)


def test_故事顺序按全书穿插_排不进的单独数(book):
    _seed(book, [(f"S-000{i}", [], [], [], "x") for i in range(1, 5)])
    _threads(book, [
        {"id": "L-001", "offset": 0, "scenes": ["S-0001", "S-0002"],
         "times": {"S-0001": {"t": 0}, "S-0002": {"t": 2}}},
        {"id": "L-002", "offset": 0, "scenes": ["S-0003", "S-0004"],
         "times": {"S-0003": {"t": 1}}},  # S-0004 没时间
    ], global_order=["S-0001", "S-0003", "S-0002"])
    seq, pos, unplaced = story_order(book)
    assert seq == ["S-0001", "S-0003", "S-0002"]
    assert pos == {"S-0001": 0, "S-0003": 1, "S-0002": 2}
    assert unplaced == 1
```

注意：`usable_order` 要求 `global_order` 跟线对得上，这里 S-0004 没时间、不在 global_order 里。先读 `skeleton_order.usable_order`，要是它因为缺 S-0004 判定 global_order 不可用、退回按时间排，结果也是 `S-0001(t0) S-0003(t1) S-0002(t2)`，断言照样成立。

- [ ] **Step 2: 跑，确认失败**

Run: `uv run pytest tests/test_timeline.py -q` → FAIL，`ModuleNotFoundError: ligaotai.timeline`

- [ ] **Step 3: 实现**

```python
# src/ligaotai/timeline.py
"""故事时间线冲突检查的纯函数部分（spec 2026-09-28-ligaotai-timeline-check-design.md）。

只用先后顺序，不用估出来的时间数值（数值不硬，②c 以来的结论）。不读模型、不写文件。
"""

from __future__ import annotations

from .book import Book
from .skeleton import scene_info
from .skeleton_order import build_sequence
from .threads_ops import load_threads
from .triage import non_main_versions, version_map


def story_order(book: Book) -> tuple[list[str], dict[str, int], int]:
    """全书故事顺序（跟骨架同一个排法，所有线都参与，不看看板）。
    返回 (排好的场景编号, 编号 -> 位置, 排不进时间轴的块数)。"""
    threads = load_threads(book)
    vmap = version_map(book)
    info = scene_info(book)
    removed = {sid for sid, x in info.items() if x["removed"]} | (non_main_versions(book) - set(vmap))
    seq, unplaced = build_sequence(threads, {}, removed, vmap)
    ids = [x["id"] for x in seq]
    return ids, {s: i for i, s in enumerate(ids)}, len(unplaced)
```

- [ ] **Step 4: 跑，确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/timeline.py tests/test_timeline.py
git commit -m "feat(timeline): 故事顺序跟骨架同一个排法"
```

---

### Task 3: 死亡事实

**Files:** Modify `src/ligaotai/timeline.py`；Test `tests/test_timeline.py`

- [ ] **Step 1: 写失败的测试**

```python
from ligaotai.timeline import is_death


def test_哪些fact算死了():
    yes = [("生死", "已死"), ("生死", "被文進刺死"), ("生死", "阵亡"), ("生死", "已歸天"),
           ("生死", "梟首傳示江浙"), ("身份", "已故封君"), ("其他", "得病身故"), ("伤病", "病故")]
    no = [("生死", "免死編氓"), ("生死", "被擒"), ("生死", "嚴行監禁"), ("生死", "車囚"),
          ("生死", "丁艱"), ("亲属", "母已亡"), ("身份", "亡命之徒"), ("性格", "视死如归"),
          ("生死", "幾乎死了"), ("生死", "未死")]
    for a, v in yes:
        assert is_death(a, v), (a, v)
    for a, v in no:
        assert not is_death(a, v), (a, v)
```

「梟首傳示江浙」：值里有「梟首」算死。「幾乎死了」「視死如歸」不算。

- [ ] **Step 2: 跑** → FAIL（ImportError）

- [ ] **Step 3: 实现**（追加到 `timeline.py`）

```python
# 死亡词：值里出现就算死了（「亲属」这类属性说的是别人，不看）
DEATH_WORDS = ("死", "亡", "殁", "歿", "卒", "身故", "病故", "已故", "归天", "歸天", "逝",
               "阵亡", "陣亡", "斩", "斬", "枭首", "梟首", "丧命", "喪命", "殒命", "殞命")
# 值里出现这些就不算（免死、被抓、只是差点死、说的是别的意思）
NOT_DEATH = ("免死", "未死", "不死", "没死", "沒死", "幾乎", "几乎", "险些", "險些", "差点", "差點",
             "被擒", "监禁", "監禁", "车囚", "車囚", "丁艱", "丁艰", "生还", "生還", "得救",
             "亡命", "视死", "視死", "死战", "死戰", "死守")
DEATH_ATTRS = ("生死", "身份", "其他", "伤病", "結局", "结局")


def is_death(attribute: str, value: str) -> bool:
    """这条 fact 说的是不是「主语死了」。只负责缩小范围：拿不准的放进来，模型后面还要判。"""
    a, v = (attribute or "").strip(), (value or "").strip()
    if a not in DEATH_ATTRS or not v:
        return False
    if any(w in v for w in NOT_DEATH):
        return False
    return any(w in v for w in DEATH_WORDS)
```

- [ ] **Step 4: 跑** → PASS。**另外**写个一次性脚本（放 scratchpad，不进仓库）拿 `data/验收书库/验收-实体-乱稿-雪月梅-c-s7/场景卡/*.json` 全部 facts 过一遍 `is_death`，把判成死的列出来写文件、Read 看一遍，确认没有明显漏判误判；有就补词表并在测试里加一条。

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/timeline.py tests/test_timeline.py
git commit -m "feat(timeline): 判断哪些 fact 算死了"
```

---

### Task 4: A 类嫌疑

**Files:** Modify `src/ligaotai/timeline.py`；Test `tests/test_timeline.py`

输入：`seq`、`pos`、`cards`（`load_cards` 的返回：`{sid: {"id", "card": {...}}}`）、`cmap`（`threads_input.name_map(book)`：`{(类型, 叫法): 规范名}`）。

- [ ] **Step 1: 写失败的测试**

```python
from ligaotai.timeline import death_suspects


def _cards(spec):
    """spec: {sid: (persons, facts)}，facts: [(subject, attribute, value, quote)]"""
    return {s: {"id": s, "card": {"characters": [{"name": n} for n in p],
                                  "facts": [{"subject": a, "attribute": b, "value": c, "quote": q} for a, b, c, q in f],
                                  "refs_elsewhere": []}}
            for s, (p, f) in spec.items()}


def test_A嫌疑_死后出现在人物名单里_别名归一_取最早的死亡(book):
    seq = ["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"]
    pos = {s: i for i, s in enumerate(seq)}
    cmap = {("person", "劉公"): "劉芳", ("person", "劉芳"): "劉芳"}
    cards = _cards({
        "S-0001": (["劉芳"], []),
        "S-0002": (["劉公"], [("劉公", "生死", "已死", "劉公已死多年")]),
        "S-0003": (["張三"], []),
        "S-0004": (["劉芳"], [("劉芳", "生死", "已死", "劉芳死了")]),  # 更晚的死亡记录不另算
        "S-0005": (["劉公"], []),
    })
    got, capped = death_suspects(seq, pos, cards, cmap)
    assert [(x["who"], x["death"], x["later"]) for x in got] == [
        ("劉芳", "S-0002", "S-0004"), ("劉芳", "S-0002", "S-0005")]
    assert got[0]["death_quote"] == "劉公已死多年"
    assert capped == 0


def test_A嫌疑_每人最多取离死亡最近的5场():
    seq = [f"S-{i:04d}" for i in range(1, 10)]
    pos = {s: i for i, s in enumerate(seq)}
    spec = {s: (["甲"], []) for s in seq}
    spec["S-0001"] = (["甲"], [("甲", "生死", "已死", "甲已死")])
    got, capped = death_suspects(seq, pos, _cards(spec), {})
    assert [x["later"] for x in got] == ["S-0002", "S-0003", "S-0004", "S-0005", "S-0006"]
    assert capped == 3


def test_A嫌疑_死亡场不在故事顺序里就不查():
    seq = ["S-0002"]
    pos = {"S-0002": 0}
    cards = _cards({"S-0001": (["甲"], [("甲", "生死", "已死", "q")]), "S-0002": (["甲"], [])})
    assert death_suspects(seq, pos, cards, {}) == ([], 0)
```

- [ ] **Step 2: 跑** → FAIL（ImportError）

- [ ] **Step 3: 实现**

```python
MAX_LATER = 5  # A 类每人最多查死后多少场（防主角被误判「已死」时嫌疑爆炸）


def _canon(name: str, cmap: dict) -> str:
    n = (name or "").strip()
    return cmap.get(("person", n), n)


def _card(cards: dict, sid: str) -> dict:
    rec = cards.get(sid) or {}
    c = rec.get("card") if isinstance(rec, dict) else None
    return c if isinstance(c, dict) else {}


def persons_of(card: dict, cmap: dict) -> set[str]:
    out = {_canon(c.get("name", ""), cmap) for c in card.get("characters") or [] if isinstance(c, dict)}
    if card.get("pov"):
        out.add(_canon(card["pov"], cmap))
    out.discard("")
    return out


def death_suspects(seq: list[str], pos: dict[str, int], cards: dict, cmap: dict) -> tuple[list[dict], int]:
    """(嫌疑列表, 因上限截掉的个数)。嫌疑 = {who, death, death_quote, later}，按 (death 位置, later 位置) 排。"""
    first: dict[str, tuple[int, str, str]] = {}  # who -> (位置, 场景, 引文)
    for sid in seq:
        for f in _card(cards, sid).get("facts") or []:
            if not isinstance(f, dict) or not is_death(f.get("attribute", ""), f.get("value", "")):
                continue
            who = _canon(f.get("subject", ""), cmap)
            if who and who not in first:
                first[who] = (pos[sid], sid, str(f.get("quote") or f.get("value") or ""))
    out, capped = [], 0
    for who, (p, dsid, quote) in sorted(first.items(), key=lambda kv: (kv[1][0], kv[0])):
        later = [s for s in seq[p + 1:] if who in persons_of(_card(cards, s), cmap)]
        capped += max(0, len(later) - MAX_LATER)
        out += [{"who": who, "death": dsid, "death_quote": quote, "later": s} for s in later[:MAX_LATER]]
    return out, capped
```

- [ ] **Step 4: 跑** → PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/timeline.py tests/test_timeline.py
git commit -m "feat(timeline): A 类嫌疑（死后又出现在人物名单里）"
```

---

### Task 5: C 类嫌疑

**Files:** Modify `src/ligaotai/timeline.py`；Test `tests/test_timeline.py`

- [ ] **Step 1: 写失败的测试**

```python
from ligaotai.timeline import ref_suspects


def _rcards(spec):
    """spec: {sid: (persons, refs, summary)}"""
    return {s: {"id": s, "card": {"characters": [{"name": n} for n in p], "facts": [],
                                  "refs_elsewhere": list(r), "summary": sm}}
            for s, (p, r, sm) in spec.items()}


def test_C嫌疑_候选按共同人物数排_同分同线优先_只问候选里有排在后面的():
    seq = ["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"]
    pos = {s: i for i, s in enumerate(seq)}
    line = {"S-0001": "L-001", "S-0002": "L-001", "S-0003": "L-002", "S-0004": "L-001", "S-0005": "L-002"}
    cards = _rcards({
        "S-0001": (["甲"], [], "一"),
        "S-0002": (["甲", "乙"], ["那日比箭之事"], "二"),
        "S-0003": (["甲", "乙"], [], "三"),
        "S-0004": (["甲"], [], "四"),
        "S-0005": (["丙"], ["只有丙"], "五"),  # 没有共同人物的候选 → 跳过
    })
    asks, no_cand, no_later = ref_suspects(seq, pos, cards, {}, line)
    assert len(asks) == 1
    a = asks[0]
    assert (a["scene"], a["ref"]) == ("S-0002", "那日比箭之事")
    # S-0003 共同人物 2 个排第一；S-0001、S-0004 各 1 个，同线（L-001）都同线，按跟 S-0002 的距离：S-0001、S-0004 都距 1，再按位置
    assert a["candidates"] == ["S-0003", "S-0001", "S-0004"]
    assert (no_cand, no_later) == (1, 0)


def test_C嫌疑_候选全在前面的不问():
    seq = ["S-0001", "S-0002"]
    pos = {"S-0001": 0, "S-0002": 1}
    cards = _rcards({"S-0001": (["甲"], [], "一"), "S-0002": (["甲"], ["前事"], "二")})
    asks, no_cand, no_later = ref_suspects(seq, pos, cards, {}, {})
    assert asks == [] and (no_cand, no_later) == (0, 1)


def test_C嫌疑_候选最多8个():
    seq = [f"S-{i:04d}" for i in range(1, 13)]
    pos = {s: i for i, s in enumerate(seq)}
    spec = {s: (["甲"], [], s) for s in seq}
    spec["S-0001"] = (["甲"], ["某事"], "一")
    asks, _, _ = ref_suspects(seq, pos, _rcards(spec), {}, {})
    assert len(asks[0]["candidates"]) == 8
```

- [ ] **Step 2: 跑** → FAIL

- [ ] **Step 3: 实现**

```python
MAX_CANDIDATES = 8  # C 类每条回指最多给模型几个候选场景


def ref_suspects(seq: list[str], pos: dict[str, int], cards: dict, cmap: dict,
                 line_of: dict[str, str]) -> tuple[list[dict], int, int]:
    """(要问模型的回指, 没有候选的回指数, 候选全在前面、不用问的回指数)。
    要问的 = {scene, ref, candidates}。候选：跟回指所在场有共同人物的其他场景，
    按 (共同人物数 降序, 不同线排后, 跟回指场的距离, 位置) 排，取前 MAX_CANDIDATES 个。"""
    people = {s: persons_of(_card(cards, s), cmap) for s in seq}
    asks, no_cand, no_later = [], 0, 0
    for sid in seq:
        refs = [r.strip() for r in _card(cards, sid).get("refs_elsewhere") or [] if isinstance(r, str) and r.strip()]
        if not refs:
            continue
        mine = people[sid]
        scored = []
        for o in seq:
            if o == sid:
                continue
            k = len(mine & people[o])
            if k:
                scored.append((-k, line_of.get(o) != line_of.get(sid), abs(pos[o] - pos[sid]), pos[o], o))
        cands = [x[-1] for x in sorted(scored)[:MAX_CANDIDATES]]
        for r in refs:
            if not cands:
                no_cand += 1
            elif all(pos[c] < pos[sid] for c in cands):
                no_later += 1
            else:
                asks.append({"scene": sid, "ref": r, "candidates": cands})
    return asks, no_cand, no_later
```

`line_of`：`{场景: 线编号}`，从 `load_threads(book)` 的 `threads[*].scenes` 现拼，Task 8 里做。

- [ ] **Step 4: 跑** → PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/timeline.py tests/test_timeline.py
git commit -m "feat(timeline): C 类嫌疑（回指配候选场景）"
```

---

### Task 6: 原文摘录

A 类要给模型看「后面那场里提到这个人的几句」。

**Files:** Modify `src/ligaotai/timeline.py`；Test `tests/test_timeline.py`

- [ ] **Step 1: 写失败的测试**

```python
from ligaotai.timeline import name_snippets


def test_摘录_按任一叫法找_最多3处_前后带一点上下文_不重叠():
    text = "開頭。劉公道：你來了。中間很多字" + "。" * 60 + "劉芳笑了。又過了很久" + "。" * 60 + "劉公走了。" + "。" * 60 + "劉公又來。"
    got = name_snippets(text, ["劉芳", "劉公"], width=6, limit=3)
    assert len(got) == 3
    assert "劉公道" in got[0] and "劉芳笑了" in got[1] and "劉公走了" in got[2]


def test_摘录_找不到就给开头一段():
    assert name_snippets("完全沒有這個人的一段話。", ["甲"], width=4, limit=3) == ["完全沒有這個人的一段話。"[:40]]
```

- [ ] **Step 2: 跑** → FAIL

- [ ] **Step 3: 实现**

```python
def name_snippets(text: str, names: list[str], width: int = 40, limit: int = 3) -> list[str]:
    """正文里提到这个人（任一叫法）的地方，每处取前后 width 字，最多 limit 处，互不重叠。
    一处都没有（叫法没对上）就给开头 40 字，让模型至少看到这场在讲什么。"""
    hits = []
    for n in sorted({n for n in names if n}, key=len, reverse=True):
        start = 0
        while (i := text.find(n, start)) >= 0:
            hits.append((i, i + len(n)))
            start = i + len(n)
    out, last_end = [], -1
    for a, b in sorted(hits):
        if a < last_end:
            continue
        lo, hi = max(0, a - width), min(len(text), b + width)
        out.append(text[lo:hi].replace("\n", " "))
        last_end = hi
        if len(out) >= limit:
            break
    return out or [text[:40].replace("\n", " ")]
```

- [ ] **Step 4: 跑** → PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/timeline.py tests/test_timeline.py
git commit -m "feat(timeline): 按人名摘原文"
```

---

### Task 7: 签名、编号、延续裁决

**Files:** Modify `src/ligaotai/timeline.py`；Test `tests/test_timeline.py`

冲突条目（落盘格式，spec 4.3）：

```python
{"id": "T-003", "kind": "A", "who": "劉公", "ref": None, "scenes": ["S-0021", "S-0046"],
 "pos": [12, 30], "quotes": ["……", "……"], "reason": "……", "status": "在场",
 "sig": "…", "verdict": None}
```

`verdict` 是 `None` 或 `{"kind": "author_error" | "order_error" | "ignore", "at": "<时间>"}`。

- [ ] **Step 1: 写失败的测试**

```python
from ligaotai.timeline import assemble, conflict_sig


def _c(kind, scenes, who=None, ref=None):
    return {"kind": kind, "who": who, "ref": ref, "scenes": scenes, "pos": [0, 1], "quotes": ["a", "b"],
            "reason": "r", "status": "在场" if kind == "A" else ""}


def test_签名只看类型_两场_人名或回指():
    a = conflict_sig(_c("A", ["S-0001", "S-0002"], who="甲"))
    assert a == conflict_sig({**_c("A", ["S-0001", "S-0002"], who="甲"), "reason": "别的说法", "pos": [5, 9]})
    assert a != conflict_sig(_c("A", ["S-0001", "S-0003"], who="甲"))
    assert a != conflict_sig(_c("C", ["S-0001", "S-0002"], ref="甲"))


def test_编号按签名沿用_新的接着编_裁决跟着签名走_消失的丢掉():
    old = {"next_id": 3, "conflicts": [
        {**_c("A", ["S-0001", "S-0002"], who="甲"), "id": "T-001",
         "sig": conflict_sig(_c("A", ["S-0001", "S-0002"], who="甲")),
         "verdict": {"kind": "order_error", "at": "x"}},
        {**_c("C", ["S-0003", "S-0004"], ref="某事"), "id": "T-002",
         "sig": conflict_sig(_c("C", ["S-0003", "S-0004"], ref="某事")),
         "verdict": {"kind": "ignore", "at": "x"}},
    ]}
    new = [_c("C", ["S-0005", "S-0006"], ref="新事"), _c("A", ["S-0001", "S-0002"], who="甲")]
    got = assemble(new, old)
    assert [(c["id"], c["verdict"]) for c in got["conflicts"]] == [
        ("T-003", None), ("T-001", {"kind": "order_error", "at": "x"})]
    assert got["next_id"] == 4
    assert {e["sig"]: e["id"] for e in got["id_registry"]}[conflict_sig(_c("C", ["S-0003", "S-0004"], ref="某事"))] == "T-002"


def test_旧文件坏了当空的():
    got = assemble([_c("A", ["S-0001", "S-0002"], who="甲")], {"conflicts": "坏了", "next_id": "x"})
    assert got["conflicts"][0]["id"] == "T-001" and got["next_id"] == 2
```

编号登记表（`id_registry`）跟 `矛盾.json` 一个道理：签名出现过就永久占号，消失一轮再回来还是原来的号（但裁决不留——spec 5「sig 对不上的旧裁决丢掉」只丢**这一轮不存在的**冲突的裁决；这一轮存在的沿用）。

- [ ] **Step 2: 跑** → FAIL

- [ ] **Step 3: 实现**

```python
import hashlib


def conflict_sig(c: dict) -> str:
    key = "\x1f".join([c.get("kind") or "", c.get("who") or "", c.get("ref") or "", *(c.get("scenes") or [])])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def assemble(conflicts: list[dict], old: dict) -> dict:
    """拼出 时间冲突.json 的 conflicts / next_id / id_registry。编号按签名沿用，裁决按签名沿用。
    旧文件是作者可以手改的，坏了当空的，不崩。"""
    old = old if isinstance(old, dict) else {}
    prev = {c.get("sig"): c for c in old.get("conflicts") or [] if isinstance(c, dict)} \
        if isinstance(old.get("conflicts"), list) else {}
    registry = {e["sig"]: e["id"] for e in old.get("id_registry") or []
                if isinstance(e, dict) and isinstance(e.get("sig"), str) and isinstance(e.get("id"), str)}
    for s, c in prev.items():
        if isinstance(s, str) and isinstance(c.get("id"), str):
            registry.setdefault(s, c["id"])
    try:
        next_id = int(old.get("next_id") or 1)
    except (TypeError, ValueError):
        next_id = 1
    used = [int(v[2:]) for v in registry.values() if v[2:].isdigit()]
    if used:
        next_id = max(next_id, max(used) + 1)
    out = []
    for c in conflicts:
        sig = conflict_sig(c)
        if sig not in registry:
            registry[sig] = f"T-{next_id:03d}"
            next_id += 1
        verdict = (prev.get(sig) or {}).get("verdict")
        out.append({"id": registry[sig], **c, "sig": sig,
                    "verdict": verdict if isinstance(verdict, dict) else None})
    return {"conflicts": out, "next_id": next_id,
            "id_registry": [{"sig": s, "id": i} for s, i in sorted(registry.items(), key=lambda kv: kv[1])]}
```

- [ ] **Step 4: 跑** → PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/timeline.py tests/test_timeline.py
git commit -m "feat(timeline): 冲突签名、编号登记、裁决沿用"
```

---

### Task 8: 输入指纹

**Files:** Modify `src/ligaotai/timeline.py`；Test `tests/test_timeline.py`

- [ ] **Step 1: 写失败的测试**

```python
from ligaotai.timeline import input_fingerprint


def test_指纹_顺序或卡或规范名变了就变(book):
    _seed(book, [("S-0001", ["甲"], ["某事"], [], "x"), ("S-0002", ["甲"], [], [], "y")])
    _threads(book, [{"id": "L-001", "offset": 0, "scenes": ["S-0001", "S-0002"],
                     "times": {"S-0001": {"t": 0}, "S-0002": {"t": 1}}}])
    f0 = input_fingerprint(book)
    assert input_fingerprint(book) == f0
    _threads(book, [{"id": "L-001", "offset": 0, "scenes": ["S-0002", "S-0001"],
                     "times": {"S-0001": {"t": 1}, "S-0002": {"t": 0}}}])
    f1 = input_fingerprint(book)
    assert f1 != f0
    from ligaotai.cards import card_path
    from ligaotai.fsutil import read_json
    rec = read_json(card_path(book, "S-0001"))
    rec["card"]["refs_elsewhere"] = ["另一件事"]
    write_json(card_path(book, "S-0001"), rec)
    assert input_fingerprint(book) != f1
```

- [ ] **Step 2: 跑** → FAIL

- [ ] **Step 3: 实现**

```python
import json

from .cards import load_cards
from .threads_input import name_map


def _relevant(card: dict) -> dict:
    return {k: card.get(k) for k in ("characters", "pov", "facts", "refs_elsewhere", "summary")}


def input_fingerprint(book: Book) -> str:
    """故事顺序 + 参与场景的卡（只取用得到的字段）+ 实体规范名。任何一样变了，旧结果就过期。"""
    seq, _, _ = story_order(book)
    cards = load_cards(book)
    payload = {"seq": seq, "cards": {s: _relevant(_card(cards, s)) for s in seq},
               "names": sorted([list(k) + [v] for k, v in name_map(book).items()])}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
```

- [ ] **Step 4: 跑** → PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/timeline.py tests/test_timeline.py
git commit -m "feat(timeline): 输入指纹，判断结果过期"
```

---

### Task 9: 两份提示词

**Files:**
- Create: `prompts/timeline_death.md`、`prompts/timeline_refs.md`
- Modify: `tests/test_prompts.py`（它有一张「每份提示词能渲染」的表，照着加两行）

- [ ] **Step 1: 先读 `tests/test_prompts.py` 第 40–60 行那张表的格式**，加两行：

```python
    ("timeline_death", {"items": "i"}, "在场"),
    ("timeline_refs", {"items": "i"}, "发生"),
```

（第三列是「渲染后的 system 里必须出现的字」，照表里现有行的含义核一下。）

- [ ] **Step 2: 跑** `uv run pytest tests/test_prompts.py -q` → FAIL（文件不存在）

- [ ] **Step 3: 写两份提示词**

```markdown
# 时间线检查：死了的人后面还在不在场（A 类）

变量：$items（每条：编号、人名、死亡那场的原文、后面那场里提到他的原文）。

## system
你在帮一位作者检查长篇小说乱稿的时间线。下面每一条是：某人在前一场里已经死了（或者写他已经死了），后面一场里又提到了这个人。你要判断后面那场里他是什么情况。

规则：
1. 每一条都要答，不许漏，也不许答我没给你的编号。
2. status 三选一：
   - 在场：他活着出现在这一场里——说话、行动、被人当面见到。
   - 提到：只是别人说起他、回忆他、梦见他、祭奠他，或者说的是他生前的事。
   - 说不准：看不出来。拿不准就写说不准，不要硬判成提到——作者宁可多看几条，也不想漏掉真问题。
3. reason 一句话说清楚为什么，必须带两场的场景编号，写成 [S-0014] 这样。
4. 死亡那场的原文可能是写错的、或者说的是别人，看出来就在 reason 里说明，status 照样按后面那场的情况填。

只输出 JSON：
{"items": [{"id": "A-01", "status": "在场", "reason": "……[S-0021][S-0046]"}]}

## user
$items
```

```markdown
# 时间线检查：回指的事发生在哪一场（C 类）

变量：$items（每条：编号、回指原话、回指所在场的摘要、候选场景的编号和摘要）。

## system
你在帮一位作者检查长篇小说乱稿的时间线。下面每一条是：某一场里提到、回忆、承接了一件别处的事（回指）。你要从给的候选场景里找出这件事是在哪一场发生的。

规则：
1. 每一条都要答，不许漏，也不许答我没给你的编号。
2. happens_in 填候选里的一个场景编号；这件事不是在任何一个候选里发生的，或者看不出来，填 null。只能填这一条自己的候选，不能填别的编号。
3. 要的是「事情本身发生」的那一场，不是「又有人提起这件事」的那一场。
4. reason 一句话说明，带场景编号，写成 [S-0014] 这样；填 null 的也写一句为什么。
5. 候选的列出顺序跟故事先后无关，别从顺序或编号大小推先后。

只输出 JSON：
{"items": [{"id": "C-01", "happens_in": "S-0127", "reason": "……[S-0127]"}]}

## user
$items
```

- [ ] **Step 4: 跑** → PASS

- [ ] **Step 5: 提交**

```bash
git add prompts/timeline_death.md prompts/timeline_refs.md tests/test_prompts.py
git commit -m "feat(timeline): A / C 两份提示词"
```

---

### Task 10: 检查和清理模型输出

**Files:**
- Create: `src/ligaotai/timeline_run.py`
- Test: `tests/test_timeline_run.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_timeline_run.py
from ligaotai.timeline_run import check_death, check_refs, clean_death, clean_refs


def test_A输出检查():
    ids = {"A-01", "A-02"}
    ok = {"items": [{"id": "A-01", "status": "在场", "reason": "x[S-0001]"},
                    {"id": "A-02", "status": "提到", "reason": "y[S-0002]"}]}
    assert check_death(ok, ids) == []
    bad = {"items": [{"id": "A-01", "status": "活着", "reason": "x"}, {"id": "A-09", "status": "在场", "reason": "[S-0001]"}]}
    probs = check_death(bad, ids)
    assert any("A-02" in p for p in probs)          # 漏答
    assert any("A-09" in p for p in probs)          # 编造编号
    assert any("status" in p for p in probs)
    assert any("场景编号" in p for p in probs)
    assert check_death([], ids)                      # 形状不对


def test_A清理_没答的按说不准保留():
    got = clean_death({"items": [{"id": "A-01", "status": "提到", "reason": "r"}]}, {"A-01", "A-02"})
    assert got["A-01"]["status"] == "提到"
    assert got["A-02"]["status"] == "说不准"


def test_C输出检查_happens_in只能是这条自己的候选或null():
    cands = {"C-01": ["S-0001", "S-0002"], "C-02": ["S-0003"]}
    ok = {"items": [{"id": "C-01", "happens_in": "S-0002", "reason": "[S-0002]"},
                    {"id": "C-02", "happens_in": None, "reason": "都不是"}]}
    assert check_refs(ok, cands) == []
    bad = {"items": [{"id": "C-01", "happens_in": "S-0003", "reason": "[S-0003]"}]}
    probs = check_refs(bad, cands)
    assert any("C-01" in p and "候选" in p for p in probs)
    assert any("C-02" in p for p in probs)


def test_C清理_不合法的当null():
    got = clean_refs({"items": [{"id": "C-01", "happens_in": "S-0009", "reason": "r"}]}, {"C-01": ["S-0001"], "C-02": ["S-0002"]})
    assert got == {"C-01": {"happens_in": None, "reason": "r"}, "C-02": {"happens_in": None, "reason": ""}}
```

- [ ] **Step 2: 跑** → FAIL

- [ ] **Step 3: 实现**

```python
# src/ligaotai/timeline_run.py
"""时间线检查：调模型、落盘、读、裁决（spec 第 4、5 节）。纯函数在 timeline.py。"""

from __future__ import annotations

from .contradictions import SCENE_REF

A_STATUSES = ("在场", "提到", "说不准")


def _items(data) -> list | None:
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else None


def _common(items: list, ids: set[str]) -> tuple[list[str], list[dict]]:
    problems = []
    got = [x for x in items if isinstance(x, dict) and isinstance(x.get("id"), str)]
    if len(got) != len(items):
        problems.append("有几条格式不对（不是对象，或者 id 不是字符串），照样例重新输出")
    seen = {x["id"] for x in got}
    if ids - seen:
        problems.append("这些编号没答：" + "、".join(sorted(ids - seen)[:10]))
    if seen - ids:
        problems.append("这些编号不在我给你的列表里：" + "、".join(sorted(seen - ids)[:10]))
    return problems, [x for x in got if x["id"] in ids]


def check_death(data, ids: set[str]) -> list[str]:
    items = _items(data)
    if items is None:
        return ['输出要是 {"items": [...]} 的形状']
    problems, got = _common(items, ids)
    for x in got:
        if x.get("status") not in A_STATUSES:
            problems.append(f"{x['id']} 的 status 只能是：" + " / ".join(A_STATUSES))
        if not isinstance(x.get("reason"), str) or not SCENE_REF.search(x["reason"]):
            problems.append(f"{x['id']} 的 reason 要是一句话，里面带场景编号，写成 [S-0014] 这样")
    return problems[:8]


def clean_death(data, ids: set[str]) -> dict[str, dict]:
    out = {}
    for x in _items(data) or []:
        if isinstance(x, dict) and x.get("id") in ids and x["id"] not in out:
            out[x["id"]] = {"status": x.get("status") if x.get("status") in A_STATUSES else "说不准",
                            "reason": x["reason"].strip() if isinstance(x.get("reason"), str) else ""}
    for i in sorted(ids - set(out)):
        out[i] = {"status": "说不准", "reason": "模型没有给出判断，按宁可多报保留"}
    return out


def check_refs(data, cands: dict[str, list[str]]) -> list[str]:
    items = _items(data)
    if items is None:
        return ['输出要是 {"items": [...]} 的形状']
    problems, got = _common(items, set(cands))
    for x in got:
        h = x.get("happens_in")
        if h is not None and h not in cands[x["id"]]:
            problems.append(f"{x['id']} 的 happens_in 只能是它自己的候选之一或者 null：" + "、".join(cands[x["id"]]))
        if not isinstance(x.get("reason"), str):
            problems.append(f"{x['id']} 的 reason 要是一句话（字符串）")
    return problems[:8]


def clean_refs(data, cands: dict[str, list[str]]) -> dict[str, dict]:
    out = {}
    for x in _items(data) or []:
        if isinstance(x, dict) and x.get("id") in cands and x["id"] not in out:
            h = x.get("happens_in")
            out[x["id"]] = {"happens_in": h if h in cands[x["id"]] else None,
                            "reason": x["reason"].strip() if isinstance(x.get("reason"), str) else ""}
    for i in sorted(set(cands) - set(out)):
        out[i] = {"happens_in": None, "reason": ""}
    return out
```

- [ ] **Step 4: 跑** → PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/timeline_run.py tests/test_timeline_run.py
git commit -m "feat(timeline): 模型输出的检查和清理"
```

---

### Task 11: 跑检查（调模型、拼结果、落盘）

**Files:** Modify `src/ligaotai/timeline_run.py`；Test `tests/test_timeline_run.py`

结果文件（spec 2、4.3）：

```python
{"generated": "...", "fingerprint": "...", "conflicts": [...], "next_id": 4, "id_registry": [...],
 "dismissed": [{"who": "甲", "scenes": ["S-0002", "S-0004"]}],   # A 类判成「提到」的，验收归因用
 "asked_refs": [{"scene": "S-0002", "ref": "…", "candidates": [...], "happens_in": "S-0004"}],  # 验收归因用
 "stats": {"placed": 100, "unplaced": 3, "a_suspects": 10, "a_capped": 0,
           "refs_asked": 20, "refs_no_candidate": 5, "refs_all_before": 30},
 "failed": [...]}
```

- [ ] **Step 1: 写失败的测试**

```python
import json

from helpers import FakeBackend
from ligaotai.config import AppConfig
from ligaotai.fsutil import read_json, write_json
from ligaotai.llm import LLMClient
from ligaotai.timeline_run import run_timeline


def _book(book):
    """甲在 S-0002 死了，S-0004 又出现；S-0001 回指「比箭」，比箭在 S-0003（排在后面）。"""
    from helpers import seed_book
    from ligaotai.cards import card_path
    seed_book(book, [
        {"id": "S-0001", "persons": ["乙", "丙"], "refs": ["那日比箭之事"], "text": "乙想起那日比箭之事。"},
        {"id": "S-0002", "persons": ["甲"], "text": "甲已死了。"},
        {"id": "S-0003", "persons": ["乙", "丙"], "text": "乙丙比箭。"},
        {"id": "S-0004", "persons": ["甲"], "text": "甲道：我回來了。"},
    ])
    rec = read_json(card_path(book, "S-0002"))
    rec["card"]["facts"] = [{"subject": "甲", "attribute": "生死", "value": "已死", "quote": "甲已死了"}]
    write_json(card_path(book, "S-0002"), rec)
    write_json(book.threads_path, {"threads": [{"id": "L-001", "offset": 0,
        "scenes": ["S-0001", "S-0002", "S-0003", "S-0004"],
        "times": {s: {"t": i} for i, s in enumerate(["S-0001", "S-0002", "S-0003", "S-0004"])}}],
        "worlds": [], "main_thread": "L-001", "global_order": [], "unassigned": [], "pending": [],
        "gaps": [], "intersections": []})
    return book


def _handler(tier, messages):
    system, user = messages[0]["content"], messages[1]["content"]
    if "死了" in system:
        return json.dumps({"items": [{"id": "A-01", "status": "在场", "reason": "甲在说话[S-0004]"}]}, ensure_ascii=False)
    if "回指" in system:
        return json.dumps({"items": [{"id": "C-01", "happens_in": "S-0003", "reason": "比箭在这[S-0003]"}]}, ensure_ascii=False)
    raise AssertionError(system[:30])


def test_跑一遍_报出A和C_落盘带指纹和统计(book):
    b = _book(book)
    client = LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir)
    summary = run_timeline(b, client)
    data = read_json(b.timeline_path)
    got = [(c["id"], c["kind"], c["scenes"], c.get("who"), c.get("ref")) for c in data["conflicts"]]
    assert got == [("T-001", "A", ["S-0002", "S-0004"], "甲", None),
                   ("T-002", "C", ["S-0001", "S-0003"], None, "那日比箭之事")]
    assert data["conflicts"][0]["pos"] == [1, 3]
    assert data["fingerprint"] and data["stats"]["placed"] == 4
    assert summary == {"ok": True, "conflicts": 2, "failed": 0}


def test_A判成提到的不报_记进dismissed(book):
    b = _book(book)

    def h(tier, messages):
        if "死了" in messages[0]["content"]:
            return json.dumps({"items": [{"id": "A-01", "status": "提到", "reason": "只是回忆[S-0004]"}]}, ensure_ascii=False)
        return json.dumps({"items": [{"id": "C-01", "happens_in": None, "reason": "都不是"}]}, ensure_ascii=False)

    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=h), log_dir=b.logs_dir))
    data = read_json(b.timeline_path)
    assert data["conflicts"] == []
    assert data["dismissed"] == [{"who": "甲", "scenes": ["S-0002", "S-0004"]}]
    assert data["asked_refs"][0]["happens_in"] is None


def test_重跑沿用编号和裁决(book):
    b = _book(book)
    client = LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir)
    run_timeline(b, client)
    data = read_json(b.timeline_path)
    data["conflicts"][1]["verdict"] = {"kind": "order_error", "at": "x"}
    write_json(b.timeline_path, data)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    again = read_json(b.timeline_path)
    assert [(c["id"], c["verdict"]) for c in again["conflicts"]] == [
        ("T-001", None), ("T-002", {"kind": "order_error", "at": "x"})]


def test_一批调用失败_记进failed_不崩(book):
    from ligaotai.llm import LLMError
    b = _book(book)

    def h(tier, messages):
        if "死了" in messages[0]["content"]:
            return LLMError("坏了")
        return _handler(tier, messages)

    s = run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=h), log_dir=b.logs_dir))
    data = read_json(b.timeline_path)
    assert s["failed"] == 1 and len(data["failed"]) == 1
    # 失败批次里的 A 嫌疑按「说不准」报出来（宁可多报），不静默丢
    assert [c["kind"] for c in data["conflicts"]] == ["A", "C"]
    assert data["conflicts"][0]["status"] == "说不准"
```

- [ ] **Step 2: 跑** → FAIL（ImportError）

- [ ] **Step 3: 实现**（追加到 `timeline_run.py`；先读 `impact.py` 的 `_run_impact` 和 `llm_caller.Caller.call` 核对签名）

```python
import asyncio

from .book import FILE_LOCK, Book, now_iso
from .cards import load_cards
from .fsutil import read_json, write_json
from .llm import LLMClient
from .llm_caller import Caller, Progress, _noop
from .scenes import get_scene
from .threads_input import name_map
from .threads_ops import load_threads
from . import timeline as tl

A_BATCH = 20  # A 类一批几条
C_BATCH = 10  # C 类一批几条（每条带 8 个候选摘要，比 A 长）


def _aliases(cmap: dict, who: str) -> list[str]:
    return [who] + [n for (t, n), c in cmap.items() if t == "person" and c == who and n != who]


def _summary(cards: dict, sid: str) -> str:
    return " ".join(str(tl._card(cards, sid).get("summary") or "").split())[:120]


def _death_text(i: int, s: dict, snippets: list[str]) -> str:
    return "\n".join([f"A-{i:02d} 人：{s['who']}",
                      f"  死亡那场 [{s['death']}]：{s['death_quote']}",
                      f"  后面那场 [{s['later']}]：" + " …… ".join(snippets)])


def _ref_text(i: int, a: dict, cards: dict) -> str:
    lines = [f"C-{i:02d} 回指所在场 [{a['scene']}]：{_summary(cards, a['scene'])}",
             f"  回指原话：{a['ref']}", "  候选："]
    lines += [f"    [{c}] {_summary(cards, c)}" for c in a["candidates"]]
    return "\n".join(lines)


def run_timeline(book: Book, client: LLMClient, progress: Progress = _noop) -> dict:
    return asyncio.run(_run(book, client, progress))


async def _run(book: Book, client: LLMClient, progress: Progress) -> dict:
    fp = tl.input_fingerprint(book)
    seq, pos, n_unplaced = tl.story_order(book)
    cards = load_cards(book)
    cmap = name_map(book)
    line_of = {s: t["id"] for t in load_threads(book).get("threads") or [] if isinstance(t, dict)
               for s in t.get("scenes") or []}
    deaths, capped = tl.death_suspects(seq, pos, cards, cmap)
    asks, no_cand, all_before = tl.ref_suspects(seq, pos, cards, cmap, line_of)

    caller = Caller(book, client, progress, cache_path=book.timeline_cache_path, tag_prefix="timeline")
    a_batches = [deaths[i:i + A_BATCH] for i in range(0, len(deaths), A_BATCH)]
    c_batches = [asks[i:i + C_BATCH] for i in range(0, len(asks), C_BATCH)]
    caller.plan(len(a_batches) + len(c_batches))

    async def one_a(k: int, batch: list[dict]) -> list[dict]:
        ids = {f"A-{i:02d}" for i in range(1, len(batch) + 1)}
        texts = []
        for i, s in enumerate(batch, 1):
            snips = tl.name_snippets(get_scene(book, s["later"]).text, _aliases(cmap, s["who"]))
            texts.append(_death_text(i, s, snips))
        got = await caller.call("timeline_death", {"items": "\n\n".join(texts)},
                                lambda d: check_death(d, ids), f"death/{k}",
                                clean=lambda d: clean_death(d, ids))
        judged = got or {i: {"status": "说不准", "reason": "这一批调用失败，没拿到判断"} for i in ids}
        return [{**s, **judged[f"A-{i:02d}"]} for i, s in enumerate(batch, 1)]

    async def one_c(k: int, batch: list[dict]) -> list[dict]:
        cands = {f"C-{i:02d}": a["candidates"] for i, a in enumerate(batch, 1)}
        text = "\n\n".join(_ref_text(i, a, cards) for i, a in enumerate(batch, 1))
        got = await caller.call("timeline_refs", {"items": text}, lambda d: check_refs(d, cands), f"refs/{k}",
                                clean=lambda d: clean_refs(d, cands))
        judged = got or {i: {"happens_in": None, "reason": "这一批调用失败，没拿到判断"} for i in cands}
        return [{**a, **judged[f"C-{i:02d}"]} for i, a in enumerate(batch, 1)]

    a_res = [x for r in await asyncio.gather(*(one_a(k, b) for k, b in enumerate(a_batches))) for x in r]
    c_res = [x for r in await asyncio.gather(*(one_c(k, b) for k, b in enumerate(c_batches))) for x in r]

    conflicts, dismissed = [], []
    for s in a_res:
        if s["status"] == "提到":
            dismissed.append({"who": s["who"], "scenes": [s["death"], s["later"]]})
            continue
        later_text = get_scene(book, s["later"]).text
        conflicts.append({"kind": "A", "who": s["who"], "ref": None, "scenes": [s["death"], s["later"]],
                          "pos": [pos[s["death"]], pos[s["later"]]],
                          "quotes": [s["death_quote"], tl.name_snippets(later_text, _aliases(cmap, s["who"]), limit=1)[0]],
                          "reason": s["reason"], "status": s["status"]})
    for a in c_res:
        h = a["happens_in"]
        if h is not None and pos[h] > pos[a["scene"]]:
            conflicts.append({"kind": "C", "who": None, "ref": a["ref"], "scenes": [a["scene"], h],
                              "pos": [pos[a["scene"]], pos[h]], "quotes": [a["ref"], _summary(cards, h)],
                              "reason": a["reason"], "status": ""})
    conflicts.sort(key=lambda c: (c["kind"], c["pos"][0], c["pos"][1]))  # 先 A 后 C，各自按故事位置

    with FILE_LOCK:
        try:
            old = read_json(book.timeline_path, {})
        except ValueError:
            old = {}
        result = {"generated": now_iso(), "fingerprint": fp, **tl.assemble(conflicts, old),
                  "dismissed": dismissed,
                  "asked_refs": [{k: a[k] for k in ("scene", "ref", "candidates", "happens_in")} for a in c_res],
                  "stats": {"placed": len(seq), "unplaced": n_unplaced, "a_suspects": len(deaths), "a_capped": capped,
                            "refs_asked": len(asks), "refs_no_candidate": no_cand, "refs_all_before": all_before},
                  "failed": list(caller.failed)}
        write_json(book.timeline_path, result)
    return {"ok": True, "conflicts": len(result["conflicts"]), "failed": len(caller.failed)}
```

注意几个核对点：
- `Caller.call` 失败时返回 `None`，上面用 `got or {...}` 兜底，**不能**让一批失败丢掉这批的嫌疑（测试 `test_一批调用失败_记进failed_不崩` 守着）。
- 排序先 A 后 C、各自按故事位置：新编号按 `conflicts` 列表顺序发，测试里 A（pos [1,3]）是 T-001、C（pos [0,2]）是 T-002，就是按这个键手算的。

- [ ] **Step 4: 跑** `uv run pytest tests/test_timeline_run.py -q` → PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/timeline_run.py tests/test_timeline_run.py
git commit -m "feat(timeline): 跑检查——分批调模型、拼冲突、落盘"
```

---

### Task 12: 读结果（带过期）和裁决

**Files:** Modify `src/ligaotai/timeline_run.py`；Test `tests/test_timeline_run.py`

- [ ] **Step 1: 写失败的测试**

```python
import pytest

from ligaotai.timeline_run import VERDICT_KINDS, load_timeline, set_timeline_verdict


def test_读结果_没跑过返回空_跑过带stale(book):
    b = _book(book)
    assert load_timeline(b) == {"conflicts": [], "never_run": True, "stale": False}
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    d = load_timeline(b)
    assert d["stale"] is False and d["never_run"] is False
    # 故事顺序按时间值排，只改 scenes 的排列不会让顺序变；改一张卡的回指，指纹一定变
    from ligaotai.cards import card_path
    rec = read_json(card_path(b, "S-0001"))
    rec["card"]["refs_elsewhere"] = ["另一件事"]
    write_json(card_path(b, "S-0001"), rec)
    assert load_timeline(b)["stale"] is True


def test_裁决_设置_改_撤销_没有这条报KeyError_类型不对报ValueError(book):
    b = _book(book)
    run_timeline(b, LLMClient(AppConfig(), FakeBackend(handler=_handler), log_dir=b.logs_dir))
    c = set_timeline_verdict(b, "T-001", "author_error")
    assert c["verdict"]["kind"] == "author_error"
    assert set_timeline_verdict(b, "T-001", "ignore")["verdict"]["kind"] == "ignore"
    assert set_timeline_verdict(b, "T-001", None)["verdict"] is None
    assert read_json(b.timeline_path)["conflicts"][0]["verdict"] is None
    with pytest.raises(KeyError):
        set_timeline_verdict(b, "T-099", "ignore")
    with pytest.raises(ValueError):
        set_timeline_verdict(b, "T-001", "随便")
    assert VERDICT_KINDS == ("author_error", "order_error", "ignore")
```

- [ ] **Step 2: 跑** → FAIL

- [ ] **Step 3: 实现**

```python
VERDICT_KINDS = ("author_error", "order_error", "ignore")


def load_timeline(book: Book) -> dict:
    """GET 用：结果文件 + never_run + stale（输入指纹对不上）。文件坏了抛 ValueError，接口层报 500。"""
    if not book.timeline_path.exists():
        return {"conflicts": [], "never_run": True, "stale": False}
    data = read_json(book.timeline_path, {})
    if not isinstance(data, dict):
        raise ValueError("时间冲突.json 不是一个 json 对象，多半被手改坏了")
    try:
        stale = data.get("fingerprint") != tl.input_fingerprint(book)
    except FileNotFoundError:
        stale = True  # 归线结果没了
    return {**data, "never_run": False, "stale": stale}


def set_timeline_verdict(book: Book, tid: str, kind: str | None) -> dict:
    if kind is not None and kind not in VERDICT_KINDS:
        raise ValueError("裁决只能是：" + " / ".join(VERDICT_KINDS))
    with FILE_LOCK:
        data = read_json(book.timeline_path, {})
        for c in data.get("conflicts") or []:
            if isinstance(c, dict) and c.get("id") == tid:
                c["verdict"] = None if kind is None else {"kind": kind, "at": now_iso()}
                write_json(book.timeline_path, data)
                return c
    raise KeyError(tid)
```

`book.timeline_path` 不存在时 `read_json(..., {})` 返回 `{}`，走到 `raise KeyError`——接口层映射成 404「没有这条」。

- [ ] **Step 4: 跑** → PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/timeline_run.py tests/test_timeline_run.py
git commit -m "feat(timeline): 读结果带过期标记、设置裁决"
```

---

### Task 13: 接口

**Files:**
- Modify: `src/ligaotai/api.py`（`put_verdict` 路由后面）
- Test: `tests/test_api_timeline.py`（新建；照 `tests/test_api_triage.py` 顶部的 `_client` / `_wait` 写法）

- [ ] **Step 1: 写失败的测试**（夹具照 `tests/test_api_triage.py` 的 `_client` / `_book` / `_wait`）

```python
# tests/test_api_timeline.py
from urllib.parse import quote

from fastapi.testclient import TestClient
from helpers import FakeBackend

from ligaotai.api import create_app
from ligaotai.book import create_book, open_book
from ligaotai.config import library_path, load_config
from test_timeline_run import _book as _seed_timeline_book, _handler

BOOK = "/api/books/" + quote("测试书")


def _client(tmp_path):
    backend = FakeBackend(handler=_handler)
    app = create_app(app_dir=tmp_path, allowed_hosts=("testserver",), backend_factory=lambda cfg: backend)
    return TestClient(app)


def _book(tmp_path):
    lib = library_path(load_config(tmp_path), tmp_path)
    lib.mkdir(parents=True, exist_ok=True)
    try:
        return open_book(lib, "测试书")
    except FileNotFoundError:
        return create_book(lib, "测试书")


def _wait(c, r):
    assert r.status_code == 202, r.text
    job = c.app.state.runner.wait(r.json()["id"]).to_dict()
    assert job["status"] == "done", job["error"]
    return job


def _ready(tmp_path):
    b = _seed_timeline_book(_book(tmp_path))
    b.set_step("threads", "done")
    return b


def test_没归线不能跑(tmp_path):
    c = _client(tmp_path)
    _book(tmp_path)
    r = c.post(f"{BOOK}/timeline/run")
    assert r.status_code == 409 and "归线" in r.json()["detail"]


def test_跑_读_裁决(tmp_path):
    c = _client(tmp_path)
    _ready(tmp_path)
    assert c.get(f"{BOOK}/timeline").json()["never_run"] is True
    _wait(c, c.post(f"{BOOK}/timeline/run"))
    d = c.get(f"{BOOK}/timeline").json()
    assert [x["id"] for x in d["conflicts"]] == ["T-001", "T-002"] and d["stale"] is False
    r = c.put(f"{BOOK}/timeline/T-002/verdict", json={"kind": "order_error"})
    assert r.status_code == 200 and r.json()["verdict"]["kind"] == "order_error"
    assert c.put(f"{BOOK}/timeline/T-099/verdict", json={"kind": "ignore"}).status_code == 404
    assert c.put(f"{BOOK}/timeline/T-001/verdict", json={"kind": "乱写"}).status_code == 400


def test_结果文件坏了报500带文件名(tmp_path):
    c = _client(tmp_path)
    b = _ready(tmp_path)
    b.timeline_path.write_text("[1]", encoding="utf-8")
    r = c.get(f"{BOOK}/timeline")
    assert r.status_code == 500 and "时间冲突.json" in r.json()["detail"]
```

`test_timeline_run._book` 要求传进来的 book 已经建好（它调 `seed_book`）；`set_step("threads", "done")` 前先读 `book.py` 确认步骤名就叫 `threads`。`from test_timeline_run import ...` 能用是因为 pytest 的 `pythonpath` 含 `tests/` 的 rootdir 规则——先在一个空测试里试 import，不行就把 `_book` / `_handler` 挪进 `tests/helpers.py`。

- [ ] **Step 2: 跑** → FAIL（404 路由不存在）

- [ ] **Step 3: 实现**（`api.py`，`from . import timeline_run as tlr` 加进 import 区）

```python
    class TimelineVerdictReq(BaseModel):
        kind: str | None = None

    @app.post("/api/books/{name}/timeline/run", status_code=202)
    def timeline_run(name: str) -> dict:
        b = get_book(name)
        if b.step("threads")["status"] != "done":
            raise HTTPException(409, "请先完成归线（步骤 6），时间线检查要用它排出来的故事顺序")
        client = make_client(b)
        return submit(b, "timeline", lambda p: tlr.run_timeline(b, client, p), track_step=False)

    @app.get("/api/books/{name}/timeline")
    def timeline_get(name: str) -> dict:
        b = get_book(name)
        try:
            return tlr.load_timeline(b)
        except ValueError as e:
            raise _读坏了("时间冲突.json", str(e))

    @app.put("/api/books/{name}/timeline/{tid}/verdict")
    def timeline_verdict(name: str, tid: str, req: TimelineVerdictReq) -> dict:
        require_idle()
        b = get_book(name)
        try:
            return tlr.set_timeline_verdict(b, tid, req.kind)
        except KeyError:
            raise HTTPException(404, "没有这条时间线冲突")
        except ValueError as e:
            raise HTTPException(400, str(e))
```

核对：`BaseModel` 在 api.py 里的 import 名、`_读坏了` 的签名、`submit` 的 `step` 名 `"timeline"` 会不会被 `runner` 校验（先读 `jobs.py`，要是有步骤名白名单，把 `"timeline"` 加进去）；`load_timeline` 里 `read_json` 遇到非法 JSON 抛的是不是 `ValueError`（`json.JSONDecodeError` 是 `ValueError` 子类，是）。

- [ ] **Step 4: 跑** `uv run pytest tests/test_api_timeline.py -q` → PASS；再跑全量 `uv run pytest -q`

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/api.py tests/test_api_timeline.py
git commit -m "feat(api): 时间线检查的跑 / 读 / 裁决三个接口"
```

---

### Task 14: 前端类型和接口

**Files:** Modify `web/src/api/types.ts`、`web/src/api/endpoints.ts`

- [ ] **Step 1: 加类型**（`types.ts` 末尾）

```ts
export type TimelineVerdictKind = 'author_error' | 'order_error' | 'ignore'
export interface TimelineConflict {
  id: string
  kind: 'A' | 'C'
  who: string | null
  ref: string | null
  scenes: [string, string]
  pos: [number, number]
  quotes: [string, string]
  reason: string
  status: string
  verdict: { kind: TimelineVerdictKind; at: string } | null
}
export interface TimelineFile {
  conflicts: TimelineConflict[]
  never_run: boolean
  stale: boolean
  stats?: { placed: number; unplaced: number; a_suspects: number; a_capped: number; refs_asked: number; refs_no_candidate: number; refs_all_before: number }
  failed?: { call: string; error: string }[]
}
```

- [ ] **Step 2: 加接口**（`endpoints.ts`，矛盾那几行后面；import 里加 `TimelineConflict, TimelineFile, TimelineVerdictKind`）

```ts
export const getTimeline = (name: string) => get<TimelineFile>(`${b(name)}/timeline`)
export const runTimeline = (name: string) => post<Job>(`${b(name)}/timeline/run`)
export const putTimelineVerdict = (name: string, tid: string, kind: TimelineVerdictKind | null) =>
  put<TimelineConflict>(`${b(name)}/timeline/${tid}/verdict`, { kind })
```

- [ ] **Step 3: 类型检查** `cd web && npx vue-tsc --noEmit` → 无输出

- [ ] **Step 4: 提交**

```bash
git add web/src/api/types.ts web/src/api/endpoints.ts
git commit -m "feat(web): 时间线检查的类型和接口"
```

---

### Task 15: 时间线分页组件

**Files:**
- Create: `web/src/components/TimelinePanel.vue`
- Test: `web/src/components/TimelinePanel.test.ts`

- [ ] **Step 1: 写失败的测试**（照 `SkeletonPage.test.ts` 的挂载写法：`createPinia`、`vi.spyOn(api, ...)`、`flushPromises`、`RouterLink` 桩）

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import TimelinePanel from './TimelinePanel.vue'
import * as api from '@/api/endpoints'
import type { Job, TimelineFile } from '@/api/types'

const stubs = { RouterLink: { template: '<a><slot /></a>', props: ['to'] } }
const job: Job = { id: 'j', name: 'timeline', book: 'x', status: 'queued', done: 0, total: 1, message: '',
  error: '', result: null, started: '', finished: '', cancel_requested: false }

function 造(over: Partial<TimelineFile> = {}): TimelineFile {
  return {
    never_run: false, stale: false,
    stats: { placed: 100, unplaced: 3, a_suspects: 4, a_capped: 0, refs_asked: 9, refs_no_candidate: 2, refs_all_before: 5 },
    conflicts: [
      { id: 'T-001', kind: 'A', who: '劉公', ref: null, scenes: ['S-0021', 'S-0046'], pos: [12, 30],
        quotes: ['劉公已死', '劉公道'], reason: '在说话[S-0046]', status: '在场', verdict: null },
      { id: 'T-002', kind: 'C', who: null, ref: '那日比箭之事', scenes: ['S-0014', 'S-0127'], pos: [3, 5],
        quotes: ['那日比箭之事', '托付刘电'], reason: '比箭在后[S-0127]', status: '', verdict: { kind: 'ignore', at: 'x' } },
    ],
    ...over,
  }
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('TimelinePanel', () => {
  it('没跑过：说明 + 检查按钮', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue({ conflicts: [], never_run: true, stale: false })
    const run = vi.spyOn(api, 'runTimeline').mockResolvedValue(job)
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="时间线空态"]').exists()).toBe(true)
    await w.find('[data-test="检查时间线"]').trigger('click')
    expect(run).toHaveBeenCalledWith('x')
  })

  it('统计行、默认只看待看、类型标签、两场位置', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue(造())
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="时间线统计"]').text()).toContain('待看 1')
    expect(w.find('[data-test="时间线统计"]').text()).toContain('已忽略 1')
    expect(w.find('[data-test="时间线统计"]').text()).toContain('3 块没有故事位置')
    expect(w.find('[data-test="冲突-T-001"]').text()).toContain('人死了又出场')
    expect(w.find('[data-test="冲突-T-001"]').text()).toContain('第 13 位')  // pos 从 0 数，显示 +1
    expect(w.find('[data-test="冲突-T-002"]').exists()).toBe(false)         // 已忽略，默认不显示
    await w.find('[data-test="看全部"]').trigger('click')
    expect(w.find('[data-test="冲突-T-002"]').text()).toContain('提前知道后面的事')
  })

  it('裁决：点了调接口，撤销传 null；排错了显示去归线页的链接', async () => {
    const d = 造()
    vi.spyOn(api, 'getTimeline').mockImplementation(async () => d)
    const put = vi.spyOn(api, 'putTimelineVerdict').mockImplementation(async (_n, tid, kind) => {
      const c = d.conflicts.find((x) => x.id === tid)!
      c.verdict = kind ? { kind, at: 'y' } : null
      return c
    })
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="裁决-T-001-order_error"]').trigger('click')
    await flushPromises()
    expect(put).toHaveBeenCalledWith('x', 'T-001', 'order_error')
    await w.find('[data-test="看全部"]').trigger('click')
    expect(w.find('[data-test="冲突-T-001"] [data-test="去归线页"]').exists()).toBe(true)
    await w.find('[data-test="撤销-T-001"]').trigger('click')
    await flushPromises()
    expect(put).toHaveBeenLastCalledWith('x', 'T-001', null)
  })

  it('过期提示、失败批次提示', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue(造({ stale: true, failed: [{ call: 'death/0', error: '坏了' }] }))
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="时间线过期"]').exists()).toBe(true)
    expect(w.text()).toContain('1 批模型没给出结果')
  })

  it('任务进行中按钮禁用', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue(造())
    vi.spyOn(api, 'runTimeline').mockResolvedValue(job)
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="检查时间线"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="检查时间线"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="裁决-T-001-ignore"]').attributes('disabled')).toBeDefined()
  })
})
```

- [ ] **Step 2: 跑** `cd web && npx vitest run src/components/TimelinePanel.test.ts` → FAIL（组件不存在）

- [ ] **Step 3: 实现**

```vue
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getTimeline, putTimelineVerdict, runTimeline } from '@/api/endpoints'
import type { TimelineConflict, TimelineFile, TimelineVerdictKind } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'
import SceneRefs from '@/components/SceneRefs.vue'

const props = defineProps<{ name: string }>()
const jobStore = useJobStore()
const data = ref<TimelineFile | null>(null)
const error = ref('')
const 看全部 = ref(false)

const 类型名: Record<string, string> = { A: '人死了又出场', C: '提前知道后面的事' }
const 裁决名: Record<TimelineVerdictKind, string> = { author_error: '确实写错了', order_error: '是顺序排错了', ignore: '没问题，忽略' }
const 裁决顺序: TimelineVerdictKind[] = ['author_error', 'order_error', 'ignore']

function 报错(e: unknown): void {
  error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
}

async function 加载(): Promise<void> {
  error.value = ''
  try {
    data.value = await getTimeline(props.name)
  } catch (e) {
    报错(e)
  }
}

async function 检查(): Promise<void> {
  try {
    jobStore.track(await runTimeline(props.name))
  } catch (e) {
    报错(e)
  }
}

async function 裁决(c: TimelineConflict, kind: TimelineVerdictKind | null): Promise<void> {
  try {
    await putTimelineVerdict(props.name, c.id, kind)
    await 加载()
  } catch (e) {
    报错(e)
  }
}

const 统计 = computed(() => {
  const cs = data.value?.conflicts ?? []
  const n = (k: TimelineVerdictKind) => cs.filter((c) => c.verdict?.kind === k).length
  return { 待看: cs.filter((c) => !c.verdict).length, 写错: n('author_error'), 排错: n('order_error'), 忽略: n('ignore') }
})

const 显示的 = computed(() => (data.value?.conflicts ?? []).filter((c) => 看全部.value || !c.verdict))

const 退订 = jobStore.onFinish((job) => {
  if (job.name !== 'timeline') return
  void (async () => {
    await 加载()
    if (job.status !== 'done') error.value = `时间线检查${job.status === 'cancelled' ? '被取消' : '失败'}：${job.error || '原因不明'}`
  })()
})
onMounted(() => {
  jobStore.start()
  void 加载()
})
onUnmounted(() => {
  退订()
  jobStore.stop()
})
</script>

<template>
  <section class="timeline">
    <ErrorBox :message="error" />
    <div class="bar">
      <button data-test="检查时间线" :disabled="jobStore.busy" @click="检查">{{ data?.never_run ? '检查时间线' : '重新检查' }}</button>
    </div>
    <p v-if="data?.never_run" class="empty" data-test="时间线空态">
      还没检查过。会找两类问题：某人前面已经死了、后面又活着出场；某场提到的事，按故事顺序要到后面才发生。
      要先跑完归线（步骤 6）。查出来的不一定是写错了，也可能是故事顺序排错了，每条你来定。
    </p>
    <template v-else-if="data">
      <p v-if="data.stale" class="warn" data-test="时间线过期">顺序或场景卡变了，下面的结果可能过时，建议重新检查。</p>
      <p v-if="data.failed?.length" class="warn">有 {{ data.failed.length }} 批模型没给出结果，那些嫌疑按「说不准」列出来了。</p>
      <p class="stats" data-test="时间线统计">
        待看 {{ 统计.待看 }} · 写错了 {{ 统计.写错 }} · 排错了 {{ 统计.排错 }} · 已忽略 {{ 统计.忽略 }}
        <template v-if="data.stats?.unplaced">（另有 {{ data.stats.unplaced }} 块没有故事位置，没查）</template>
      </p>
      <div class="filters">
        <button :class="{ on: !看全部 }" data-test="只看待看" @click="看全部 = false">只看待看</button>
        <button :class="{ on: 看全部 }" data-test="看全部" @click="看全部 = true">全部</button>
      </div>
      <p v-if="显示的.length === 0" class="empty">{{ 看全部 ? '没有查出冲突。' : '没有待看的了。' }}</p>
      <div v-for="c in 显示的" :key="c.id" class="card" :data-test="`冲突-${c.id}`">
        <div class="head">
          <span class="kind" :class="c.kind">{{ 类型名[c.kind] }}</span>
          <b>{{ c.kind === 'A' ? c.who : `「${c.ref}」` }}</b>
          <span v-if="c.status === '说不准'" class="unsure">模型拿不准</span>
          <span class="id">{{ c.id }}</span>
        </div>
        <div class="pair">
          <div><SceneRefs :text="c.scenes[0]" :book="name" /> <span class="pos">故事顺序第 {{ c.pos[0] + 1 }} 位</span>
            <q>{{ c.quotes[0] }}</q></div>
          <div><SceneRefs :text="c.scenes[1]" :book="name" /> <span class="pos">故事顺序第 {{ c.pos[1] + 1 }} 位</span>
            <q>{{ c.quotes[1] }}</q></div>
        </div>
        <p class="reason"><SceneRefs :text="c.reason" :book="name" /></p>
        <div class="ops">
          <button v-for="k in 裁决顺序" :key="k" :data-test="`裁决-${c.id}-${k}`" :class="{ on: c.verdict?.kind === k }"
                  :disabled="jobStore.busy" @click="裁决(c, k)">{{ 裁决名[k] }}</button>
          <button v-if="c.verdict" :data-test="`撤销-${c.id}`" :disabled="jobStore.busy" @click="裁决(c, null)">撤销</button>
          <RouterLink v-if="c.verdict?.kind === 'order_error'" data-test="去归线页" :to="`/b/${encodeURIComponent(name)}/pipeline/threads`">去归线页调顺序</RouterLink>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.bar{margin-bottom:10px}
.empty{color:var(--ink-3)}
.warn{color:var(--amber);font-size:13px}
.stats{font-size:13px;color:var(--ink-2)}
.filters{display:flex;gap:6px;margin:8px 0}
.filters .on{background:var(--accent-soft);color:var(--accent)}
.card{border:1px solid var(--line-2);border-radius:8px;padding:10px 12px;margin-bottom:10px;background:var(--panel)}
.head{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.kind{font-size:11px;padding:1px 6px;border-radius:999px;background:var(--red-soft);color:var(--red)}
.kind.C{background:var(--amber-soft);color:var(--amber)}
.unsure{font-size:11px;color:var(--ink-3)}
.id{margin-left:auto;font-family:var(--mono);font-size:12px;color:var(--ink-3)}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:8px 0;font-size:13px}
.pair q{display:block;color:var(--ink-2);margin-top:4px}
.pos{color:var(--ink-3);font-size:12px}
.reason{font-size:13px;color:var(--ink-2);margin:4px 0}
.ops{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.ops .on{background:var(--accent-soft);color:var(--accent)}
@media (max-width: 900px){.pair{grid-template-columns:1fr}}
</style>
```

核对：`jobStore.onFinish` / `start` / `stop` / `track` 的用法照 `SkeletonPage.vue`；CSS 变量名照原型变量表（`--red-soft` / `--amber-soft` 这些在 `SkeletonPage.vue` / `BoardPage.vue` 里用过的才用）。

- [ ] **Step 4: 跑** → PASS；`npx vue-tsc --noEmit` 无输出

- [ ] **Step 5: 提交**

```bash
git add web/src/components/TimelinePanel.vue web/src/components/TimelinePanel.test.ts
git commit -m "feat(web): 时间线分页组件"
```

---

### Task 16: 矛盾页加分页切换

**Files:** Modify `web/src/pages/ContradictionsPage.vue`；Test `web/src/pages/ContradictionsPage.test.ts`

分页用 URL 查询参数 `?tab=timeline` 记住（刷新不丢、别的页能直接链过来）。

- [ ] **Step 1: 写失败的测试**（追加到 `ContradictionsPage.test.ts`；先读文件顶部看它怎么挂载、有没有路由）

```ts
  it('分页：默认矛盾，点「时间线」切过去', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue({ groups: [], stats: {} } as never)
    vi.spyOn(api, 'getTimeline').mockResolvedValue({ conflicts: [], never_run: true, stale: false })
    const w = mount(ContradictionsPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="时间线空态"]').exists()).toBe(false)
    await w.find('[data-test="分页-时间线"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="时间线空态"]').exists()).toBe(true)
  })
```

（页面要是用了 `useRoute` / `useRouter`，测试里照 `ScenesPage.route.test.ts` 的办法挂一个内存路由。）

- [ ] **Step 2: 跑** → FAIL

- [ ] **Step 3: 实现**：script 里加

```ts
import { useRoute, useRouter } from 'vue-router'
import TimelinePanel from '@/components/TimelinePanel.vue'

const route = useRoute()
const router = useRouter()
// 本地状态是准的；路由只是顺手记一下（刷新不丢、别的页能链过来）。没挂路由（单测）时照样能切。
const 分页 = ref<'contra' | 'timeline'>(route?.query.tab === 'timeline' ? 'timeline' : 'contra')
function 切到(tab: 'contra' | 'timeline'): void {
  分页.value = tab
  void router?.replace({ query: { ...route?.query, tab: tab === 'timeline' ? 'timeline' : undefined } })
}
```

模板 `<h1>` 下面加

```vue
    <div class="tabs">
      <button :class="{ on: 分页 === 'contra' }" data-test="分页-矛盾" @click="切到('contra')">矛盾</button>
      <button :class="{ on: 分页 === 'timeline' }" data-test="分页-时间线" @click="切到('timeline')">时间线</button>
    </div>
    <TimelinePanel v-if="分页 === 'timeline'" :name="name" />
```

原来 `<ErrorBox>` 之后的整块内容包进 `<template v-if="分页 === 'contra'">…</template>`。样式加 `.tabs{display:flex;gap:6px;margin-bottom:12px}.tabs .on{background:var(--accent-soft);color:var(--accent)}`。

注意：矛盾页原来 `onMounted` 里 `jobStore.start()`、`onUnmounted` 里 `stop()`，`TimelinePanel` 自己也 start/stop——先读 `stores/job.ts` 确认 start/stop 是计数的（嵌套调用安全）；不是的话，`TimelinePanel` 不要自己 start/stop，改成由页面负责。

- [ ] **Step 4: 跑** 前端全量 `npx vitest run` → 全绿；`npx vue-tsc --noEmit`

- [ ] **Step 5: 提交**

```bash
git add web/src/pages/ContradictionsPage.vue web/src/pages/ContradictionsPage.test.ts
git commit -m "feat(web): 矛盾页加「时间线」分页"
```

---

### Task 17: 乱稿工具——A 类植入

**Files:** Modify `tools/scramble.py`；Test `tests/test_scramble.py`

- [ ] **Step 1: 写失败的测试**（追加；`_chapters_with` / `CHARS` 是文件里已有的）

```python
from tools.scramble import plant_deaths


def _talk_chapters(n):
    out = []
    for i in range(1, n + 1):
        out.append(Chapter(i, f"第{i}回", f"這日天氣晴和。岑秀道：「好。」眾人都不做聲。劉電看了一眼。"))
    return out


def test_A植入_前一章插死亡_后一章他有对话_答案记两章():
    chapters = _talk_chapters(8)
    got = plant_deaths(chapters, random.Random(1), n=1, characters=CHARS, used=set())
    assert len(got) == 1
    p = got[0]
    a, b = p["chapters"]
    assert p["kind"] == "A" and a < b
    bodies = {c.num: c.body for c in chapters}
    assert f"{p['name']}染病身亡。" in bodies[a]
    assert f"{p['name']}道" in bodies[b] or f"{p['name']}說" in bodies[b]  # b 章里他有对话


def test_A植入_用过的章节不再用_跳过的章节不用():
    chapters = _talk_chapters(8)
    used = {1, 2, 3}
    got = plant_deaths(chapters, random.Random(2), n=2, characters=CHARS, used=used, skip={8})
    for p in got:
        assert not set(p["chapters"]) & {1, 2, 3, 8}
    assert len(used) == 3 + 2 * len(got)  # 用过的会记进 used


def test_A植入_没人物名单不植():
    assert plant_deaths(_talk_chapters(4), random.Random(1), n=3, characters=[], used=set()) == []
```

注意：`_talk_chapters` 里只有岑秀有对话（「岑秀道」），劉電没有，所以植入的只能是岑秀。

- [ ] **Step 2: 跑** → FAIL

- [ ] **Step 3: 实现**（`plant_contradictions` 后面）

```python
_SPEAK = ("道", "說", "说", "問", "问", "笑道", "答")


def _speaks(body: str, name: str) -> bool:
    return any(f"{name}{w}" in body for w in _SPEAK)


def plant_deaths(chapters: list[Chapter], rng: random.Random, n: int,
                 characters: list[dict] | None, used: set[int],
                 skip: set[int] | None = None, avoid: set[str] | None = None) -> list[dict]:
    """时间线检查验收用（A 类）：挑一个人，在他出现过的前一章 a 插「某某染病身亡。」，
    后一章 b 里他有对话——这样 b 章他活着说话就跟 a 章的死亡冲突。
    used：已经被别的植入占用的章节（会就地加进去），一个章节只参与一处植入。
    skip / avoid：同 plant_contradictions（被截断的章节、会被别名替换的人）。"""
    if n <= 0 or not characters:
        return []
    skipped, avoided = set(skip or ()), set(avoid or ())
    people = []
    for ch in characters:
        names = [x for x in (ch.get("names") or [ch["canonical"]]) if x]
        if avoided and any(a in nm or nm in a for nm in names for a in avoided):
            continue
        people.append((ch["canonical"], names))
    rng.shuffle(people)
    planted = []
    for canon, names in people:
        if len(planted) >= n:
            break
        free = [c for c in chapters if c.num not in skipped and c.num not in used]
        talk = [(c, nm) for c in free for nm in names if _speaks(c.body, nm)]
        if not talk:
            continue
        b, _ = rng.choice(talk)
        before = [(c, nm) for c in free if c.num < b.num for nm in names if nm in c.body]
        if not before:
            continue
        a, nm = rng.choice(before)
        cut = _sentence_end(a.body, a.body.find(nm))
        a.body = a.body[:cut] + f"{nm}染病身亡。" + a.body[cut:]
        used |= {a.num, b.num}
        planted.append({"kind": "A", "who": canon, "name": nm, "chapters": [a.num, b.num]})
    return sorted(planted, key=lambda p: p["chapters"])
```

- [ ] **Step 4: 跑** → PASS

- [ ] **Step 5: 提交**

```bash
git add tools/scramble.py tests/test_scramble.py
git commit -m "feat(tools): 乱稿植入 A 类时间线冲突（前死后说话）"
```

---

### Task 18: 乱稿工具——C 类植入 + 接进 scramble / CLI

**Files:** Modify `tools/scramble.py`；Test `tests/test_scramble.py`

事件清单格式：`[{"chapter": 16, "who": "岑秀", "event": "比箭連中三箭"}]`。

- [ ] **Step 1: 写失败的测试**

```python
from tools.scramble import plant_foreknowledge


def test_C植入_在事件章之前某章插回忆_答案记两章():
    chapters = _talk_chapters(8)
    events = [{"chapter": 6, "who": "岑秀", "event": "比箭連中三箭"}]
    got = plant_foreknowledge(chapters, random.Random(1), n=1, events=events, used=set())
    p = got[0]
    a, b = p["chapters"]
    assert p["kind"] == "C" and a < b == 6
    assert "岑秀想起那日比箭連中三箭之事。" in {c.num: c.body for c in chapters}[a]


def test_C植入_事件章被占用或跳过就换一条():
    chapters = _talk_chapters(8)
    events = [{"chapter": 6, "who": "岑秀", "event": "甲"}, {"chapter": 7, "who": "岑秀", "event": "乙"}]
    got = plant_foreknowledge(chapters, random.Random(1), n=2, events=events, used={6})
    assert [p["event"] for p in got] == ["乙"]


def test_scramble_答案里带timeline(tmp_path):
    """接进 scramble()：--deaths / --foreknowledge 植入的记在答案的 timeline 里。"""
    from tools.scramble import scramble
    chapters = _talk_chapters(20)
    key = scramble(chapters, tmp_path / "out", 7, aliases=[], n_delete=1, n_truncate=1, n_full=1, n_excerpt=1,
                   n_deaths=1, n_foreknowledge=1, characters=CHARS,
                   events=[{"chapter": 15, "who": "岑秀", "event": "比箭"}])
    kinds = sorted(p["kind"] for p in key["timeline"])
    assert kinds == ["A", "C"] or kinds == ["A"] or kinds == ["C"]  # 章节可能被删 / 截断占掉
    assert all(set(p["chapters"]).isdisjoint(key["deleted"]) for p in key["timeline"])
```

第三条断言写得宽，是因为随机删章节可能正好删掉事件章。执行时换几个 seed 看看，挑一个两种都植上的 seed 把断言收紧成 `== ["A", "C"]`。

- [ ] **Step 2: 跑** → FAIL

- [ ] **Step 3: 实现**

```python
def plant_foreknowledge(chapters: list[Chapter], rng: random.Random, n: int,
                        events: list[dict] | None, used: set[int], skip: set[int] | None = None) -> list[dict]:
    """时间线检查验收用（C 类）：事件清单里每条是「第 b 章 who 做了 event」。挑 b 之前、who 出现过的
    一章 a，插「{who}想起那日{event}之事。」——a 章里提前知道了 b 章才发生的事。
    事件清单手写（程序编不出像样的事件），放 data/，不进仓库。"""
    if n <= 0 or not events:
        return []
    skipped = set(skip or ())
    have = {c.num for c in chapters}
    pool = [e for e in events if e.get("chapter") in have]
    rng.shuffle(pool)
    planted = []
    for e in pool:
        if len(planted) >= n:
            break
        b = e["chapter"]
        if b in used or b in skipped:
            continue
        before = [c for c in chapters if c.num < b and c.num not in used and c.num not in skipped and e["who"] in c.body]
        if not before:
            continue
        a = rng.choice(before)
        cut = _sentence_end(a.body, a.body.find(e["who"]))
        a.body = a.body[:cut] + f"{e['who']}想起那日{e['event']}之事。" + a.body[cut:]
        used |= {a.num, b}
        planted.append({"kind": "C", "who": e["who"], "event": e["event"], "chapters": [a.num, b]})
    return sorted(planted, key=lambda p: p["chapters"])
```

接进 `scramble()`：签名加 `n_deaths: int = 0, n_foreknowledge: int = 0, events: list[dict] | None = None`；在 `plant_contradictions(...)` 之后加

```python
    # 时间线植入：跟年龄矛盾不抢章节（年龄矛盾占用的章节先记进 used），同样排掉会被截断的章节
    used = {ch for p in contradictions for ch in p["chapters"]}
    timeline = plant_deaths(kept, rng, n_deaths, characters, used, skip=set(truncated),
                            avoid={a["replaces"] for a in aliases})
    timeline += plant_foreknowledge(kept, rng, n_foreknowledge, events, used, skip=set(truncated))
```

返回的 dict 加 `"timeline": timeline`。`main()` 加参数：

```python
    ap.add_argument("--deaths", type=int, default=0, help="植入 N 处「前一章死、后一章说话」（时间线检查验收用，要 --characters）")
    ap.add_argument("--foreknowledge", type=int, default=0, help="植入 N 处「提前回忆后面的事」（要 --events）")
    ap.add_argument("--events", help="JSON 文件：事件清单，每条 chapter / who / event")
```

并传给 `scramble(..., n_deaths=args.deaths, n_foreknowledge=args.foreknowledge, events=events)`，`events = json.loads(...) if args.events else None`；打印行加 `timeline={len(key['timeline'])}`。

- [ ] **Step 4: 跑** `uv run pytest tests/test_scramble.py -q` → PASS；再跑 `tests/test_tools_scripts.py`

- [ ] **Step 5: 提交**

```bash
git add tools/scramble.py tests/test_scramble.py
git commit -m "feat(tools): 乱稿植入 C 类时间线冲突（提前回忆后面的事），接进 CLI"
```

---

### Task 19: 判卷脚本

**Files:**
- Create: `tools/eval_timeline.py`
- Test: `tests/test_eval_timeline.py`

- [ ] **Step 1: 写失败的测试**（纯函数 `recall_timeline`，不碰书）

```python
# tests/test_eval_timeline.py
from tools.eval_timeline import recall_timeline

CH = {3: {"S-0003"}, 8: {"S-0008"}, 5: {"S-0005"}, 9: {"S-0009"}}
KEY = {"timeline": [{"kind": "A", "who": "岑秀", "name": "岑秀", "chapters": [3, 8]},
                    {"kind": "C", "who": "岑秀", "event": "比箭", "chapters": [5, 9]}]}


def test_两类都命中():
    res = {"conflicts": [
        {"kind": "A", "who": "岑秀", "scenes": ["S-0003", "S-0008"]},
        {"kind": "C", "ref": "想起比箭", "scenes": ["S-0005", "S-0009"]}]}
    r = recall_timeline(KEY, CH, res, cmap={})
    assert (r["A"]["hit"], r["A"]["planted"], r["C"]["hit"], r["C"]["planted"]) == (1, 1, 1, 1)


def test_A人名要归一_场景要落在对的章():
    res = {"conflicts": [{"kind": "A", "who": "岑公子", "scenes": ["S-0003", "S-0009"]}]}
    assert recall_timeline(KEY, CH, res, cmap={("person", "岑公子"): "岑秀"})["A"]["hit"] == 0  # 后一场章不对
    res = {"conflicts": [{"kind": "A", "who": "岑公子", "scenes": ["S-0003", "S-0008"]}]}
    assert recall_timeline(KEY, CH, res, cmap={("person", "岑公子"): "岑秀"})["A"]["hit"] == 1


def test_没命中归因_A():
    cards = {"S-0003": {"card": {"facts": [], "characters": []}},
             "S-0008": {"card": {"facts": [], "characters": [{"name": "岑秀"}]}}}
    r = recall_timeline(KEY, CH, {"conflicts": [], "dismissed": [], "asked_refs": []}, cmap={}, cards=cards)
    assert r["A"]["misses"][0]["cause"] == "死亡没被抽成 fact"
    cards["S-0003"]["card"]["facts"] = [{"subject": "岑秀", "attribute": "生死", "value": "染病身亡", "quote": "q"}]
    r = recall_timeline(KEY, CH, {"conflicts": [], "dismissed": [{"who": "岑秀", "scenes": ["S-0003", "S-0008"]}],
                                  "asked_refs": []}, cmap={}, cards=cards)
    assert r["A"]["misses"][0]["cause"] == "模型判成只是提到"


def test_没命中归因_C():
    base = {"conflicts": [], "dismissed": []}
    r = recall_timeline(KEY, CH, {**base, "asked_refs": []}, cmap={}, cards={})
    assert r["C"]["misses"][0]["cause"] == "没问到（回指没抽出来，或候选全在前面）"
    r = recall_timeline(KEY, CH, {**base, "asked_refs": [{"scene": "S-0005", "ref": "想起比箭", "candidates": ["S-0003"], "happens_in": None}]}, cmap={}, cards={})
    assert r["C"]["misses"][0]["cause"] == "候选里没有事件那一场"
    r = recall_timeline(KEY, CH, {**base, "asked_refs": [{"scene": "S-0005", "ref": "想起比箭", "candidates": ["S-0009"], "happens_in": None}]}, cmap={}, cards={})
    assert r["C"]["misses"][0]["cause"] == "模型判错了场"
```

- [ ] **Step 2: 跑** → FAIL

- [ ] **Step 3: 实现**

```python
# tools/eval_timeline.py
"""时间线检查验收：植入的 A / C 冲突召回（各 ≥ 4/5）、没命中归因、全部冲突写成人工核对表。

用法：
  uv run python tools/eval_timeline.py --library <书库> --book <书文件夹名> \
      --folder 乱稿-雪月梅-c --key data/乱稿-雪月梅-c-答案.json --report data/验收-时间线.json --review 核对.md
只读结果文件，不调模型。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ligaotai.book import open_book  # noqa: E402
from ligaotai.cards import load_cards  # noqa: E402
from ligaotai.timeline import _card, is_death, persons_of  # noqa: E402
from ligaotai.threads_input import name_map  # noqa: E402

FLOOR = 4  # 每类 5 处里至少抓到 4 处


def _canon(n, cmap):
    return cmap.get(("person", n), n)


def recall_timeline(key: dict, chapter_scenes: dict[int, set[str]], result: dict,
                    cmap: dict, cards: dict | None = None) -> dict:
    planted = key.get("timeline") or []
    confs = result.get("conflicts") or []
    out = {}
    for kind in ("A", "C"):
        ps = [p for p in planted if p["kind"] == kind]
        hit, misses = 0, []
        for p in ps:
            a_sc, b_sc = (chapter_scenes.get(ch, set()) for ch in p["chapters"])
            ok = any(c.get("kind") == kind and c["scenes"][0] in a_sc and c["scenes"][1] in b_sc
                     and (kind == "C" or _canon(c.get("who") or "", cmap) == p["who"]) for c in confs)
            if ok:
                hit += 1
                continue
            m = dict(p)
            if cards is not None:
                m["cause"] = _cause_a(p, a_sc, b_sc, result, cards, cmap) if kind == "A" else _cause_c(a_sc, b_sc, result)
            misses.append(m)
        out[kind] = {"planted": len(ps), "hit": hit, "misses": misses,
                     "pass": len(ps) == 0 or hit >= min(FLOOR, len(ps))}
    return out


def _cause_a(p, a_sc, b_sc, result, cards, cmap) -> str:
    died = any(is_death(f.get("attribute", ""), f.get("value", "")) and _canon(f.get("subject", ""), cmap) == p["who"]
               for s in a_sc for f in _card(cards, s).get("facts") or [] if isinstance(f, dict))
    if not died:
        return "死亡没被抽成 fact"
    if not any(p["who"] in persons_of(_card(cards, s), cmap) for s in b_sc):
        return "后一章的卡人物名单里没有他"
    if any(_canon(d["who"], cmap) == p["who"] and d["scenes"][1] in b_sc for d in result.get("dismissed") or []):
        return "模型判成只是提到"
    return "没进嫌疑（故事顺序里死亡场排在后面，或超了每人 5 场的上限）"


def _cause_c(a_sc, b_sc, result) -> str:
    asked = [x for x in result.get("asked_refs") or [] if x["scene"] in a_sc]
    if not asked:
        return "没问到（回指没抽出来，或候选全在前面）"
    if not any(set(x["candidates"]) & b_sc for x in asked):
        return "候选里没有事件那一场"
    return "模型判错了场"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="evaluate timeline conflict check against planted answers")
    ap.add_argument("--library", required=True)
    ap.add_argument("--book", required=True)
    ap.add_argument("--folder", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--report", default="data/验收-时间线.json")
    ap.add_argument("--review", default="")
    args = ap.parse_args(argv)
    from eval_archives import chapter_to_scenes
    book = open_book(Path(args.library), args.book)
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    if not key.get("timeline"):
        sys.exit("答案文件里没有 timeline 植入，拿 scramble --deaths / --foreknowledge 重新生成")
    ch = chapter_to_scenes(book, key, Path(args.folder).name)
    result = json.loads(book.timeline_path.read_text(encoding="utf-8"))
    rep = recall_timeline(key, ch, result, name_map(book), load_cards(book))
    Path(args.report).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.review:
        lines = ["# 时间线冲突人工核对", "", "每条标：书里真有的时间问题 / 我们的顺序排错 / 模型判错", ""]
        for c in result.get("conflicts") or []:
            lines += [f"## {c['id']} {c['kind']} {c.get('who') or c.get('ref')}", "",
                      f"- 场景：{c['scenes'][0]}（第 {c['pos'][0] + 1} 位）→ {c['scenes'][1]}（第 {c['pos'][1] + 1} 位）",
                      f"- 原文：{c['quotes'][0]} ／ {c['quotes'][1]}", f"- 模型：{c['reason']}", "- 判定：", ""]
        Path(args.review).write_text("\n".join(lines), encoding="utf-8")
    print(f"A {rep['A']['hit']}/{rep['A']['planted']} C {rep['C']['hit']}/{rep['C']['planted']} "
          f"pass={rep['A']['pass'] and rep['C']['pass']} report={args.report}")
    if not (rep["A"]["pass"] and rep["C"]["pass"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
```

核对：`eval_archives.chapter_to_scenes` 的 import 方式（它自己 `from eval_threads import ...`，靠 `tools/` 在 sys.path 里）；`tests/test_tools_scripts.py` 要求 `tools/` 下脚本能 `uv run python tools/xxx.py` 直接跑，跑一下 `--help`。

- [ ] **Step 4: 跑** `uv run pytest tests/test_eval_timeline.py tests/test_tools_scripts.py -q` → PASS

- [ ] **Step 5: 提交**

```bash
git add tools/eval_timeline.py tests/test_eval_timeline.py
git commit -m "feat(tools): 时间线检查判卷——召回、没命中归因、人工核对表"
```

---

### Task 20: 雪月梅事件清单（不进仓库）

**Files:** Create `data/事件-雪月梅.json`（`data/` 在 gitignore 里，确认 `git status` 看不到它）

- [ ] **Step 1**：照 `data/pg26904.txt`（或雪月梅原文所在的那个 txt，先 `grep -l 雪月梅 data/*.txt` 确认）按回目挑 12 条事件：分布在第 10 回以后（植入要在它之前找一章），每条 `who` 用原文里的写法（繁体）、`event` 是 4–10 字、原文里那一回确实发生的事。例：`{"chapter": 16, "who": "岑秀", "event": "比箭連中三箭"}`。
- [ ] **Step 2**：写个 scratchpad 脚本核：每条 `who` 在那一回正文里出现、`event` 的关键两三个字在那一回正文里出现；结果写文件 Read 看。
- [ ] **Step 3**：请作者过一眼清单（不花钱），他点头再用。

---

### Task 21: 全量回归 + 截图验收（不花钱）

- [ ] **Step 1**：`uv run pytest -q`、`cd web && npx vitest run && npx vue-tsc --noEmit`，全绿。
- [ ] **Step 2**：`cd web && npm run build`。
- [ ] **Step 3**：拿 9-28 scratchpad 的 `ui_check.py` 办法起一个副本书库，**手写一份假的 `时间冲突.json`**（两条 A、两条 C，一条带裁决，`fingerprint` 随便写让它显示过期），真浏览器打开矛盾页 → 点「时间线」→ 截图；点一次裁决、撤销，确认后端文件变了；切「全部」；1000px 窄窗再截一张。console 0 报错。截图用 Read 看。
- [ ] **Step 4**：更新 `docs/已知问题与待办.md`：时间线冲突检查那条改成「A / C 已做（9-28 设计），B / D 以后」，并写清验收还没真跑。
- [ ] **Step 5**：提交。

---

### Task 22: 真跑验收（花钱，低峰，先问作者）

- [ ] **Step 1**：确认当前是 DeepSeek 低峰（`date`，工作日 9–12、14–18 之外，或周末节假日），**跟作者确认可以跑**；发一次 5 token 的 ping 验 key。
- [ ] **Step 2**：重新生成乱稿（带年龄矛盾 10 处 + A 5 处 + C 5 处）：

```bash
uv run python tools/scramble.py --src <雪月梅原文> --out data/乱稿-雪月梅-t --seed 7 \
  --aliases data/别名-雪月梅.json --characters data/人物-雪月梅.json \
  --contradictions 10 --deaths 5 --foreknowledge 5 --events data/事件-雪月梅.json
```

（参数照 9-21 生成 `乱稿-雪月梅-c` 时的命令核对：`docs/验收记录/2026-09-21-计划2c-档案矛盾地图.md`。）
- [ ] **Step 3**：临时书库里跑步骤 1–7（照 `eval_archives.py` / 9-21 验收记录的流程），然后点「检查时间线」（或直接调 `run_timeline`）。
- [ ] **Step 4**：`eval_archives.py`（年龄矛盾召回，顺带验植入方向那条待办）+ `eval_timeline.py --review 核对.md`。
- [ ] **Step 5**：人工过 `核对.md` 全部条目，统计三类；请作者抽查 5 条。
- [ ] **Step 6**：写验收记录 `docs/验收记录/2026-09-xx-时间线检查.md`（召回、归因、误报三类数、比箭那处抓没抓到、花了多少——记录里可以写钱，界面不显示），提交。
