# 理稿台 计划④（二期取舍）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让作者裁决矛盾、决定每条线的去留、生成并编辑卷章骨架、把现成场景按骨架拼成一本可读的书（md / txt）。

**Architecture:** 不加流水线步骤。后端新增 `verdicts.py`（裁决）、`triage.py`（看板）、`impact.py`（影响检查）、`advice.py`（AI 建议）、`skeleton_order.py` / `chapters.py` / `skeleton.py`（骨架）、`export.py`（导出）；要调模型的走现有 `JobRunner` + `llm_caller.Caller`（缓存在 `取舍/缓存.json`）。前端新增看板页、骨架页，矛盾页加裁决操作。

**Tech Stack:** Python 3.11 + FastAPI + pytest（`uv run`）；Vue 3 + TS + Pinia + Vitest（`web/`，npm）。

**Spec:** `docs/superpowers/specs/2026-09-22-ligaotai-plan4-triage-design.md`（下称 spec）。

---

## 给执行者的硬规矩（每个子代理都要读）

1. **只在 `plan4` 分支上干。** 禁止 `git stash` / `git checkout --` / `git reset` / `git restore`；只 `git add` 自己改的文件。
2. **本计划里的代码没跑过。** 照抄前先读一遍、对照真实代码验证；发现计划写错了，按真实契约改，并在报告里写清「计划哪里错了、怎么改的」。前几个计划的计划代码被抓出过十几个真 bug。
3. **测试断言是手算 / 独立算出来的，不许为了迁就实现去改断言。** 断言本身错了要在报告里论证，不许悄悄改。
4. **测试要用真实数据契约。** 例：`实体.json` 的 `type` 是 `person` / `location` / `organization`，不是中文；`矛盾.json` 组里的字段以 `src/ligaotai/contradictions.py` 的 `build_result()` 为准；`世界与支线.json` 以 `threads.normalize()` 为准。②c 就是因为测试自己捏了中文键的假数据，28 个测试全绿、真跑一条都对不上。
5. **别在工具参数里敲 `\u` 转义**（会变成看不见的真字符）；要反斜杠用 `chr(92)` 拼。含中文的临时脚本用 Write 写成 `.py` 再跑，别用 bash heredoc 传中文。
6. **终端里的中文输出不可信**（Windows 按 GBK 解码）：要看中文结果就写文件再用 Read 看。
7. 仓库里**不写作者本名、不写本机路径**（公开仓库）。
8. 界面**不显示任何费用数字**（计划③ spec 7.3）。
9. 跑测试：后端 `uv run pytest -q`，前端 `cd web && npm run test && npm run typecheck`。每个 Task 结束两边都要绿。
10. 提交信息结尾加：
    ```
    Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
    ```

## 已经存在、直接复用的东西（别重造）

| 东西 | 在哪 | 用法 |
|---|---|---|
| 书文件夹路径 | `src/ligaotai/book.py` 的 `Book` 属性 | `book.threads_path`、`book.contradictions_path`… |
| 进程内文件锁 | `book.FILE_LOCK`（可重入） | 所有「读-改-写」包在 `with FILE_LOCK:` 里 |
| 原子写 JSON | `fsutil.write_json` / `read_json(path, default)` | `read_json` 对坏 JSON 抛 `ValueError`（`json.JSONDecodeError` 是它的子类） |
| 读归线结果 | `threads_ops.load_threads(book)` | 没有文件抛 `FileNotFoundError`，坏了抛 `threads_ops.BrokenThreadsFile`；返回 `normalize()` 过的 dict |
| 场景 | `scenes.load_scenes(book)` → `Scene`（`id`/`chars`/`removed`/`heading`…）；`scenes.get_scene(book, sid).text` | |
| 场景卡 | `cards.load_cards(book)` → `{sid: {"id","card":{...}}}` | 卡字段：`summary`/`characters[{name,role}]`/`hooks_planted`/`hooks_resolved`/`refs_elsewhere` |
| 规范名映射 | `threads_input.name_map(book)` → `{(type, 叫法): 规范名}` | |
| 代词表 | `entities.PRONOUNS` | 人物统计要剔掉「我」「他」 |
| 引用编号 | `archive.refs_in(text)` → 文本里 `[S-0001]` / `[S-0001,S-0002]` 抓出的编号列表 | 模型输出核编号 |
| 输入签名 | `archive.input_sig(text, prompt_name)` | 缓存 / 过期判断 |
| 模型调用 | `llm_caller.Caller(book, client, progress, cache_path=..., tag_prefix=...)`；`await caller.call(prompt, values, check, tag)` 失败返回 `None`、失败记在 `caller.failed` | 综合档（`synth`）；**本计划不调 `prune_cache()`**（缓存文件三类调用共用） |
| 提示词 | `prompts/<名字>.md`，`## system` / `## user` 两段，变量 `$名字` | |
| 自然排序 | `fsutil.natural_key` | |
| 测试假模型 | `tests/helpers.py` 的 `FakeBackend(handler=fn)`；`LLMClient(AppConfig(), backend, log_dir=book.logs_dir)` | handler 收 `(tier, messages)`，返回 JSON 字符串 |
| 测试小书 | `tests/conftest.py` 的 `book_with_threads` fixture | 6 个场景；L-001（S-0001~3，offset 0，t=0/1/2）、L-002（S-0004~5，offset 3，t=0/1）；主线 L-001；缺口 Q-001（L-001，after S-0001，before S-0003）；S-0001~3 人物「悟空/行者」（规范名 孙悟空），S-0004~5「敖广」；S-0002 埋伏笔「紧箍咒的来历」 |
| 真书归线 fixture | `web/src/components/__fixtures__/xueyuemei-threads.json`、`xiyouji-threads.json` | 后端测试可以直接读这两个文件 |

## 文件地图

**后端新建**
- `src/ligaotai/verdicts.py` — 写裁决、派生定稿设定、要跟着改的场景
- `src/ligaotai/triage.py` — 看板读写、对账、每条线统计
- `src/ligaotai/impact.py` — 影响检查（程序化 + 模型伏笔配对）
- `src/ligaotai/advice.py` — AI 取舍建议
- `src/ligaotai/skeleton_order.py` — 纯函数：全局时间交织、空洞插入、章节备注
- `src/ligaotai/chapters.py` — 纯函数：分章输入渲染、结果核对、兜底切法、窗口切分与合并、组装
- `src/ligaotai/skeleton.py` — 生成（调模型）、保存编辑、校验、对账标注
- `src/ligaotai/export.py` — 按骨架拼书
- `prompts/triage_advice.md`、`prompts/triage_impact.md`、`prompts/skeleton_chapters.md`、`prompts/skeleton_holes.md`
- `tools/eval_skeleton.py` — 验收硬判据
- 测试：`tests/test_verdicts.py`、`test_triage.py`、`test_impact.py`、`test_advice.py`、`test_skeleton_order.py`、`test_chapters.py`、`test_skeleton.py`、`test_export.py`、`test_api_triage.py`、`test_eval_skeleton.py`

**后端修改**
- `src/ligaotai/book.py` — 新路径属性、`skeleton_max_input_tokens` 默认设置
- `src/ligaotai/api.py` — 新接口

**前端新建**
- `web/src/pages/BoardPage.vue` + `.test.ts`
- `web/src/pages/SkeletonPage.vue` + `.test.ts`

**前端修改**
- `web/src/api/types.ts`、`web/src/api/endpoints.ts`
- `web/src/pages/ContradictionsPage.vue` + `.test.ts`（裁决）
- `web/src/router.ts`、`web/src/components/NavRail.vue` + `.test.ts`、`web/src/components/AppShell.vue`、`web/src/layouts/BookLayout.vue`
- `web/src/components/JobBar.vue`（新任务名的中文标签）

**文档**
- `README.md`、`docs/superpowers/specs/2026-09-10-ligaotai-design.md`、`docs/已知问题与待办.md`、`docs/验收记录/2026-XX-XX-计划4-取舍.md`

## 对 spec 的细化（执行时以这里为准）

- spec 第 4 节写 `triage.py` 包揽看板 + 影响 + 建议，这里按「一个文件一件事」拆成 `triage.py` / `impact.py` / `advice.py`；骨架拆成 `skeleton_order.py`（纯排序）/ `chapters.py`（纯分章）/ `skeleton.py`（编排）。
- 新增两个结果文件：`取舍/建议.json`（AI 建议）、`取舍/影响.json`（每条线最近一次伏笔影响），缓存仍在 `取舍/缓存.json`。
- spec 9 节的 `PUT /triage/board` 细化成 `PUT /triage/board/{tid}`（改一张卡）+ `DELETE /triage/board/{tid}`（删孤儿卡）。
- 程序化影响第 3 项（别处引用）只拿「**只在这条线出场的人物**」的叫法去匹配别的线的 `refs_elsewhere`。拿全部人物匹配，主角在所有线都出现，会把每条引用都报上来，等于没报。
- 归线结果里的 `unassigned`（没归到任何线的块）进骨架 `unplaced`，`why` 为 `unassigned`，不然导出时这些块悄悄消失。
- 导出：卷名用 `#`、章名用 `##`（spec 第 8 节「卷一级、章二级」），书末附录 `# 附：未定位`。

---

# 里程碑 1：地基 + 矛盾裁决

### Task 1: Book 新路径与设置

**Files:**
- Modify: `src/ligaotai/book.py`
- Test: `tests/test_book.py`

- [ ] **Step 1: 写失败的测试**（追加到 `tests/test_book.py` 末尾）

```python
def test_二期的文件路径(book):
    r = book.root
    assert book.canon_path == r / "定稿设定.json"
    assert book.triage_dir == r / "取舍"
    assert book.board_path == r / "取舍" / "看板.json"
    assert book.advice_path == r / "取舍" / "建议.json"
    assert book.impact_path == r / "取舍" / "影响.json"
    assert book.skeleton_path == r / "取舍" / "骨架.json"
    assert book.skeleton_bak_path == r / "取舍" / "骨架.bak.json"
    assert book.triage_cache_path == r / "取舍" / "缓存.json"
    assert book.export_dir == r / "导出"


def test_骨架分章的输入上限有默认值(book):
    assert book.settings()["skeleton_max_input_tokens"] == 600000
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest -q tests/test_book.py -k "二期 or 骨架"`
Expected: FAIL，`AttributeError: 'Book' object has no attribute 'canon_path'`

- [ ] **Step 3: 实现**

`DEFAULT_SETTINGS` 里 `"threads_max_input_tokens"` 那行下面加：

```python
    "skeleton_max_input_tokens": 600000,  # 骨架分章一次调用的输入上限（跟归线同一估法），超过就按窗口分批
```

`Book` 类里 `archive_cache_path` 属性后面加：

```python
    @property
    def canon_path(self) -> Path:
        """定稿设定：从 矛盾.json 里作者的裁决派生，三期补写要遵守。"""
        return self.root / "定稿设定.json"

    @property
    def triage_dir(self) -> Path:
        return self.root / "取舍"

    @property
    def board_path(self) -> Path:
        return self.triage_dir / "看板.json"

    @property
    def advice_path(self) -> Path:
        return self.triage_dir / "建议.json"

    @property
    def impact_path(self) -> Path:
        return self.triage_dir / "影响.json"

    @property
    def skeleton_path(self) -> Path:
        return self.triage_dir / "骨架.json"

    @property
    def skeleton_bak_path(self) -> Path:
        return self.triage_dir / "骨架.bak.json"

    @property
    def triage_cache_path(self) -> Path:
        """二期所有模型调用（AI 建议、影响检查、分章、空洞说明）共用的缓存。"""
        return self.triage_dir / "缓存.json"

    @property
    def export_dir(self) -> Path:
        return self.root / "导出"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q tests/test_book.py`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/book.py tests/test_book.py
git commit -m "feat: 二期文件路径与骨架分章输入上限设置"
```

### Task 2: verdicts.py——写裁决、定稿设定、要跟着改的场景

**Files:**
- Create: `src/ligaotai/verdicts.py`
- Test: `tests/test_verdicts.py`

背景（spec 第 5 节）：`矛盾.json` 每组已有 `verdict` / `verdict_sig` / `verdict_stale`；组编号按 (规范主语, 属性) 永久固定；步骤 7 重跑时 `contradictions.build_result()` 会把 `verdict` 迁到新组上，值集合跟 `verdict_sig` 不同就标 stale。**本 Task 只负责写 `verdict`，迁移逻辑一行不动。**

- [ ] **Step 1: 写失败的测试** `tests/test_verdicts.py`

```python
import pytest

from ligaotai.contradictions import build_result
from ligaotai.fsutil import read_json, write_json
from ligaotai.verdicts import (
    BrokenContradictions,
    NoSuchGroup,
    current_canon,
    followups,
    set_verdict,
)


def _group(values_sig="sig1", **kw):
    g = {
        "id": "C-001", "subject": "小梅", "attribute": "年龄", "status": "真矛盾", "level": "严重",
        "category": "人物", "reason": "对不上 [S-0001]",
        "values": [
            {"value": "十三", "scenes": [{"id": "S-0001", "quote": "年方十三", "thread": "L-001", "t": 0, "conf": "高"}]},
            {"value": "十七", "scenes": [
                {"id": "S-0002", "quote": "今年十七", "thread": "L-001", "t": 1, "conf": "中"},
                {"id": "S-0003", "quote": "十七歲", "thread": "L-002", "t": 2, "conf": "中"}]},
        ],
        "values_sig": values_sig, "verdict": None, "verdict_sig": None, "verdict_stale": False,
    }
    g.update(kw)
    return g


@pytest.fixture
def cbook(book):
    write_json(book.contradictions_path, {"groups": [_group()], "stats": {}, "next_id": 2,
                                          "id_registry": [{"subject": "小梅", "attribute": "年龄", "id": "C-001"}]})
    return book


def test_以某个值为准_写进verdict并记下判定依据(cbook):
    g = set_verdict(cbook, "C-001", "pick", "十三")
    assert g["verdict"]["kind"] == "pick"
    assert g["verdict"]["value"] == "十三"
    assert g["verdict"]["by"] == "author"
    assert g["verdict_sig"] == "sig1"
    assert g["verdict_stale"] is False
    on_disk = read_json(cbook.contradictions_path)["groups"][0]
    assert on_disk["verdict"]["value"] == "十三"


def test_以某个值为准_值必须是这一组里的(cbook):
    with pytest.raises(ValueError):
        set_verdict(cbook, "C-001", "pick", "十八")


def test_自己写_不能为空(cbook):
    with pytest.raises(ValueError):
        set_verdict(cbook, "C-001", "own", "   ")


def test_裁决种类不认识就拒绝(cbook):
    with pytest.raises(ValueError):
        set_verdict(cbook, "C-001", "guess", "十三")


def test_定稿设定_pick带支持这个值的场景_own不带(cbook):
    set_verdict(cbook, "C-001", "pick", "十七")
    canon = read_json(cbook.canon_path)
    assert canon["items"] == [{"id": "C-001", "subject": "小梅", "attribute": "年龄", "value": "十七",
                               "sources": ["S-0002", "S-0003"], "note": ""}]
    set_verdict(cbook, "C-001", "own", "十五", note="按第三回改")
    canon = read_json(cbook.canon_path)
    assert canon["items"][0]["value"] == "十五"
    assert canon["items"][0]["sources"] == []
    assert canon["items"][0]["note"] == "按第三回改"


def test_先放着和撤销都不进定稿设定(cbook):
    set_verdict(cbook, "C-001", "later")
    assert read_json(cbook.canon_path)["items"] == []
    set_verdict(cbook, "C-001", "pick", "十三")
    g = set_verdict(cbook, "C-001", None)
    assert g["verdict"] is None and g["verdict_sig"] is None
    assert read_json(cbook.canon_path)["items"] == []


def test_stale的裁决不进定稿设定_重新裁决清掉stale(book):
    write_json(book.contradictions_path, {"groups": [_group(
        verdict={"kind": "pick", "value": "十三", "note": "", "by": "author", "at": "x"},
        verdict_sig="old", verdict_stale=True)], "stats": {}})
    assert current_canon(book)["items"] == []
    g = set_verdict(book, "C-001", "pick", "十三")
    assert g["verdict_stale"] is False
    assert [i["id"] for i in current_canon(book)["items"]] == ["C-001"]


def test_current_canon_发现文件跟裁决对不上就重写(cbook):
    set_verdict(cbook, "C-001", "pick", "十三")
    write_json(cbook.canon_path, {"generated": "x", "items": []})  # 模拟步骤 7 重跑后文件过时
    c = current_canon(cbook)
    assert [i["value"] for i in c["items"]] == ["十三"]
    assert [i["value"] for i in read_json(cbook.canon_path)["items"]] == ["十三"]


def test_要跟着改的场景_列出其他值出现的地方(cbook):
    set_verdict(cbook, "C-001", "pick", "十三")
    f = followups(cbook, "C-001")
    assert [(s["id"], s["value"]) for s in f["scenes"]] == [("S-0002", "十七"), ("S-0003", "十七")]
    assert f["scenes"][0]["quote"] == "今年十七"


def test_要跟着改的场景_自己写时每个值的场景都要改(cbook):
    set_verdict(cbook, "C-001", "own", "十五")
    assert [s["id"] for s in followups(cbook, "C-001")["scenes"]] == ["S-0001", "S-0002", "S-0003"]


def test_要跟着改的场景_没裁决时为空(cbook):
    assert followups(cbook, "C-001")["scenes"] == []


def test_没有矛盾文件和编号不存在(book, cbook):
    with pytest.raises(NoSuchGroup):
        set_verdict(cbook, "C-999", "later")


def test_没跑过步骤7(book):
    with pytest.raises(FileNotFoundError):
        set_verdict(book, "C-001", "later")


def test_矛盾文件坏了(book):
    book.contradictions_path.write_text("{坏", encoding="utf-8")
    with pytest.raises(BrokenContradictions):
        set_verdict(book, "C-001", "later")


def _cand(values):
    return {"subject": "小梅", "attribute": "年龄", "merged": 0,
            "values": [{"value": v, "scenes": [{"id": s, "quote": "q"}]} for v, s in values]}


def test_跟步骤7的迁移联动_值没变裁决保留_值变了标stale(book):
    """真实契约：裁决写进去之后，contradictions.build_result 重跑能原样接回；多了新值要标 stale。"""
    first = build_result([_cand([("十三", "S-0001"), ("十七", "S-0002")])], {}, {}, {}, {})
    write_json(book.contradictions_path, first)
    set_verdict(book, first["groups"][0]["id"], "pick", "十三")
    old = read_json(book.contradictions_path)
    again = build_result([_cand([("十三", "S-0001"), ("十七", "S-0002")])], {}, {}, old, {})
    g = again["groups"][0]
    assert g["verdict"]["value"] == "十三" and g["verdict_stale"] is False
    changed = build_result([_cand([("十三", "S-0001"), ("十七", "S-0002"), ("十八", "S-0003")])], {}, {}, old, {})
    assert changed["groups"][0]["verdict_stale"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest -q tests/test_verdicts.py`
Expected: FAIL，`ModuleNotFoundError: No module named 'ligaotai.verdicts'`

- [ ] **Step 3: 实现** `src/ligaotai/verdicts.py`

```python
"""二期：矛盾裁决与定稿设定（计划④ spec 第 5 节）。

裁决的唯一真源是 矛盾.json 每组的 verdict；定稿设定.json 由它派生，每次裁决后整体重写。
编号固定、重跑迁移、值集合变了标 stale，都是步骤 7（contradictions.build_result）已经做好的，
这里只负责写 verdict，不碰迁移逻辑。
"""

from __future__ import annotations

from .book import FILE_LOCK, Book, now_iso
from .fsutil import read_json, write_json

KINDS = ("pick", "own", "later")


class BrokenContradictions(ValueError):
    """矛盾.json 不是合法 JSON，或者形状不对。"""


class NoSuchGroup(KeyError):
    """给的矛盾编号找不到。"""


def load_contradictions(book: Book) -> dict:
    try:
        data = read_json(book.contradictions_path)
    except ValueError as e:
        raise BrokenContradictions(f"矛盾.json 不是合法 JSON：{e}") from e
    if data is None:
        raise FileNotFoundError("还没有矛盾扫描结果，先跑步骤 7")
    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        raise BrokenContradictions("矛盾.json 的 groups 不是列表")
    return data


def _find(data: dict, cid: str) -> dict:
    for g in data["groups"]:
        if isinstance(g, dict) and g.get("id") == cid:
            return g
    raise NoSuchGroup(cid)


def _values(g: dict) -> list[dict]:
    return [v for v in g.get("values") or [] if isinstance(v, dict)]


def make_verdict(g: dict, kind: str, value: str | None = None, note: str = "") -> dict:
    if kind not in KINDS:
        raise ValueError(f"裁决只能是 {' / '.join(KINDS)}")
    v: dict = {"kind": kind, "by": "author", "at": now_iso()}
    note = (note or "").strip()
    if kind == "pick":
        if value not in [x.get("value") for x in _values(g)]:
            raise ValueError(f"「{value}」不是这一组里的值")
        v.update(value=value, note=note)
    elif kind == "own":
        value = (value or "").strip()
        if not value:
            raise ValueError("自己写的说法不能为空")
        v.update(value=value, note=note)
    return v


def canon_items(data: dict) -> list[dict]:
    """有效裁决（pick / own，且没标 stale）→ 定稿设定条目。"""
    items = []
    for g in data.get("groups") or []:
        if not isinstance(g, dict):
            continue
        v = g.get("verdict")
        if not isinstance(v, dict) or v.get("kind") not in ("pick", "own") or g.get("verdict_stale"):
            continue
        sources: list[str] = []
        if v["kind"] == "pick":
            for val in _values(g):
                if val.get("value") == v.get("value"):
                    sources = [s.get("id") for s in val.get("scenes") or [] if isinstance(s, dict)]
        items.append({"id": g.get("id"), "subject": g.get("subject"), "attribute": g.get("attribute"),
                      "value": v.get("value"), "sources": sources, "note": v.get("note", "")})
    return items


def _write_canon(book: Book, items: list[dict]) -> dict:
    canon = {"generated": now_iso(), "items": items}
    write_json(book.canon_path, canon)
    return canon


def set_verdict(book: Book, cid: str, kind: str | None, value: str | None = None, note: str = "") -> dict:
    """写（kind 为 None 时撤销）一组的裁决，同时重写定稿设定。返回改后的组。"""
    with FILE_LOCK:
        data = load_contradictions(book)
        g = _find(data, cid)
        if kind is None:
            g["verdict"] = None
            g["verdict_sig"] = None
        else:
            g["verdict"] = make_verdict(g, kind, value, note)
            # 判定依据 = 作者下判定这一刻的值集合；步骤 7 重跑时拿它比，值变了才标 stale
            g["verdict_sig"] = g.get("values_sig")
        g["verdict_stale"] = False
        write_json(book.contradictions_path, data)
        _write_canon(book, canon_items(data))
    return g


def current_canon(book: Book) -> dict:
    """按 矛盾.json 现算定稿设定；文件跟现算结果不一样（比如步骤 7 重跑后有裁决变 stale）就重写。"""
    with FILE_LOCK:
        items = canon_items(load_contradictions(book))
        try:
            old = read_json(book.canon_path)
        except ValueError:
            old = None
        if isinstance(old, dict) and old.get("items") == items:
            return old
        return _write_canon(book, items)


def followups(book: Book, cid: str) -> dict:
    """定下说法后，出现其他值、要跟着改的场景。只展示，不改原文。"""
    g = _find(load_contradictions(book), cid)
    v = g.get("verdict")
    scenes: list[dict] = []
    if isinstance(v, dict) and v.get("kind") in ("pick", "own"):
        for val in _values(g):
            if v["kind"] == "pick" and val.get("value") == v.get("value"):
                continue
            for s in val.get("scenes") or []:
                if isinstance(s, dict):
                    scenes.append({"id": s.get("id"), "quote": s.get("quote", ""), "value": val.get("value")})
    return {"id": cid, "verdict": v, "scenes": scenes}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q tests/test_verdicts.py`
Expected: 全部 PASS。`test_跟步骤7的迁移联动…` 挂了先别改断言——读 `contradictions.build_result` 的迁移代码，确认是 `set_verdict` 写的形状不对还是计划理解错了契约，报告里写清。

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/verdicts.py tests/test_verdicts.py
git commit -m "feat: 矛盾裁决写进 矛盾.json，派生定稿设定"
```

### Task 3: 裁决接口

**Files:**
- Modify: `src/ligaotai/api.py`
- Test: `tests/test_api_triage.py`（新建，后面几个 Task 继续往里加）

- [ ] **Step 1: 写失败的测试** `tests/test_api_triage.py`

```python
"""二期接口：裁决、看板、影响、骨架、导出。"""

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from helpers import FakeBackend

from ligaotai.api import create_app
from ligaotai.book import create_book, open_book
from ligaotai.config import library_path, load_config
from ligaotai.fsutil import read_json, write_json

BOOK = "/api/books/" + quote("测试书")


def _client(tmp_path, handler=None):
    backend = FakeBackend(handler=handler or (lambda tier, messages: "{}"))
    app = create_app(app_dir=tmp_path, allowed_hosts=("testserver",), backend_factory=lambda cfg: backend)
    c = TestClient(app)
    c.backend = backend
    return c


def _book(tmp_path):
    lib = library_path(load_config(tmp_path), tmp_path)
    lib.mkdir(parents=True, exist_ok=True)
    try:
        return open_book(lib, "测试书")
    except FileNotFoundError:
        return create_book(lib, "测试书")


def _contradictions(book):
    write_json(book.contradictions_path, {"groups": [{
        "id": "C-001", "subject": "小梅", "attribute": "年龄", "status": "真矛盾", "level": "严重",
        "category": "人物", "reason": "r [S-0001]",
        "values": [{"value": "十三", "scenes": [{"id": "S-0001", "quote": "年方十三", "thread": "L-001", "t": 0, "conf": "高"}]},
                   {"value": "十七", "scenes": [{"id": "S-0002", "quote": "今年十七", "thread": "L-001", "t": 1, "conf": "中"}]}],
        "values_sig": "sig1", "verdict": None, "verdict_sig": None, "verdict_stale": False}], "stats": {}})


def test_写裁决_读定稿设定_读要跟着改的场景(tmp_path):
    c = _client(tmp_path)
    _contradictions(_book(tmp_path))
    r = c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": "pick", "value": "十三"})
    assert r.status_code == 200, r.text
    assert r.json()["verdict"]["value"] == "十三"
    assert c.get(f"{BOOK}/canon").json()["items"][0]["value"] == "十三"
    f = c.get(f"{BOOK}/contradictions/C-001/followups").json()
    assert [s["id"] for s in f["scenes"]] == ["S-0002"]


def test_撤销裁决(tmp_path):
    c = _client(tmp_path)
    _contradictions(_book(tmp_path))
    c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": "later"})
    r = c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": None})
    assert r.json()["verdict"] is None


def test_裁决的错误映射(tmp_path):
    c = _client(tmp_path)
    b = _book(tmp_path)
    assert c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": "later"}).status_code == 404  # 没跑步骤 7
    _contradictions(b)
    assert c.put(f"{BOOK}/contradictions/C-009/verdict", json={"kind": "later"}).status_code == 404
    assert c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": "pick", "value": "九十"}).status_code == 400
    b.contradictions_path.write_text("{坏", encoding="utf-8")
    r = c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": "later"})
    assert r.status_code == 500 and "矛盾.json" in r.json()["detail"]


def test_有任务在跑时写裁决返回409(tmp_path, monkeypatch):
    c = _client(tmp_path)
    _contradictions(_book(tmp_path))

    class _Job:
        status, name, book = "running", "archive", "测试书"

    monkeypatch.setattr(c.app.state.runner, "current", lambda: _Job())
    assert c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": "later"}).status_code == 409
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest -q tests/test_api_triage.py`
Expected: FAIL（404 / 405，路由不存在）

- [ ] **Step 3: 实现**（`src/ligaotai/api.py`）

import 区加：

```python
from . import verdicts as vd
```

请求体模型（放在 `RerunReq` 后面）：

```python
class VerdictReq(BaseModel):
    kind: str | None
    value: str | None = None
    note: str = ""
```

`create_app` 里 `thread_op` 定义之后加两个小工具：

```python
    def require_idle() -> None:
        """二期所有写接口：有任务在跑（不分哪本书）就 409，不做读-改-写（照 archive_rerun 的做法）。"""
        cur = runner.current()
        if cur is not None and cur.status in ("queued", "running"):
            raise HTTPException(409, f"已有任务在跑：{cur.name}（{cur.book}）")

    def verdict_op(fn: Callable[[], object]):
        try:
            return fn()
        except vd.NoSuchGroup:
            raise HTTPException(404, "没有这组矛盾")
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except vd.BrokenContradictions as e:
            raise _读坏了("矛盾.json", str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
```

路由（放在 `contradictions` 路由后面）：

```python
    @app.put("/api/books/{name}/contradictions/{cid}/verdict")
    def put_verdict(name: str, cid: str, req: VerdictReq) -> dict:
        require_idle()
        b = get_book(name)
        return verdict_op(lambda: vd.set_verdict(b, cid, req.kind, req.value, req.note))

    @app.get("/api/books/{name}/canon")
    def canon(name: str) -> dict:
        b = get_book(name)
        return verdict_op(lambda: vd.current_canon(b))

    @app.get("/api/books/{name}/contradictions/{cid}/followups")
    def verdict_followups(name: str, cid: str) -> dict:
        b = get_book(name)
        return verdict_op(lambda: vd.followups(b, cid))
```

注意 `verdict_op` 里 `NoSuchGroup` 要排在 `ValueError` 前面无所谓（它是 `KeyError`），但 `BrokenContradictions` 是 `ValueError` 子类，**必须排在 `ValueError` 前面**，不然坏文件会被报成 400。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q tests/test_api_triage.py`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/api.py tests/test_api_triage.py
git commit -m "feat: 裁决、定稿设定、要跟着改的场景三个接口"
```

---

# 里程碑 2：取舍看板

### Task 4: triage.py——看板读写、对账、每条线统计

**Files:**
- Create: `src/ligaotai/triage.py`
- Test: `tests/test_triage.py`

- [ ] **Step 1: 写失败的测试** `tests/test_triage.py`

```python
import pytest

from ligaotai.fsutil import read_json, write_json
from ligaotai.threads_ops import load_threads
from ligaotai.triage import BrokenBoardFile, delete_orphan, load_board, reconcile, set_card, thread_stats


def test_空看板_每条线默认还没想好(book_with_threads):
    th = load_threads(book_with_threads)
    cards = reconcile(load_board(book_with_threads), th)["cards"]
    assert {k: v["col"] for k, v in cards.items()} == {"L-001": "undecided", "L-002": "undecided"}
    assert not any(v["orphan"] or v["merge_invalid"] for v in cards.values())


def test_合并要选另一条存在且没砍的线(book_with_threads):
    b = book_with_threads
    th = load_threads(b)
    with pytest.raises(ValueError):
        set_card(b, th, "L-002", "merge", merge_into="L-002")
    with pytest.raises(ValueError):
        set_card(b, th, "L-002", "merge", merge_into="L-009")
    set_card(b, th, "L-001", "cut")
    with pytest.raises(ValueError):
        set_card(b, th, "L-002", "merge", merge_into="L-001")


def test_合并目标后来被砍_标合并目标失效(book_with_threads):
    b = book_with_threads
    th = load_threads(b)
    set_card(b, th, "L-002", "merge", merge_into="L-001")
    cards = set_card(b, th, "L-001", "cut")["cards"]
    assert cards["L-002"]["merge_invalid"] is True
    assert read_json(b.board_path)["cards"]["L-002"] == {"col": "merge", "merge_into": "L-001", "note": ""}


def test_列不认识或线不存在(book_with_threads):
    b = book_with_threads
    th = load_threads(b)
    with pytest.raises(ValueError):
        set_card(b, th, "L-001", "maybe")
    with pytest.raises(KeyError):
        set_card(b, th, "L-009", "keep")


def test_非合并列不留合并目标_备注保留(book_with_threads):
    b = book_with_threads
    th = load_threads(b)
    set_card(b, th, "L-002", "merge", merge_into="L-001", note="并进取经")
    cards = set_card(b, th, "L-002", "keep")["cards"]
    assert cards["L-002"]["merge_into"] is None
    assert cards["L-002"]["note"] == "并进取经"


def test_线消失_卡保留标孤儿_可以删(book_with_threads):
    b = book_with_threads
    write_json(b.board_path, {"cards": {"L-009": {"col": "cut", "merge_into": None, "note": ""}}})
    th = load_threads(b)
    cards = reconcile(load_board(b), th)["cards"]
    assert cards["L-009"]["orphan"] is True and cards["L-009"]["col"] == "cut"
    delete_orphan(b, th, "L-009")
    assert "L-009" not in read_json(b.board_path)["cards"]
    with pytest.raises(ValueError):
        delete_orphan(b, th, "L-001")  # 活着的线不许删


def test_看板文件坏了不当空(book_with_threads):
    book_with_threads.triage_dir.mkdir(parents=True, exist_ok=True)
    book_with_threads.board_path.write_text("{坏", encoding="utf-8")
    with pytest.raises(BrokenBoardFile):
        load_board(book_with_threads)
    write_json(book_with_threads.board_path, {"cards": []})
    with pytest.raises(BrokenBoardFile):
        load_board(book_with_threads)


def test_每条线统计_字数只算主版本(book_with_threads):
    b = book_with_threads
    # 每块正文都是「S-000x 的正文。」共 11 个字；S-0002 是 S-0001 的非主版本
    write_json(b.versions_path, {"params": {}, "groups": [
        {"id": "G-001", "members": ["S-0001", "S-0002"], "main": "S-0001", "main_by": "auto", "pairs": []}]})
    st = thread_stats(b, load_threads(b))
    assert st["L-001"] == {"name": "取经", "world": "W-01", "words": 22, "scenes": 3, "state": "待定",
                           "gaps": 1, "is_main": True, "order_failed": False}
    assert st["L-002"]["words"] == 22 and st["L-002"]["state"] == "完结" and st["L-002"]["gaps"] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest -q tests/test_triage.py`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现** `src/ligaotai/triage.py`

```python
"""二期：取舍看板（计划④ spec 第 6.1、6.2 节）。

看板.json 只存作者的决定：{"cards": {线编号: {"col", "merge_into", "note"}}}。
读的时候按 世界与支线.json 对账（新线补「还没想好」、消失的线标孤儿、合并目标失效要标出来），
对账结果不落盘——落盘只在作者改卡的时候。
"""

from __future__ import annotations

from .book import FILE_LOCK, Book
from .fsutil import read_json, write_json
from .scenes import load_scenes

COLS = ("keep", "merge", "cut", "undecided")


class BrokenBoardFile(ValueError):
    """看板.json 坏了。作者的决定不能当空处理，得让作者自己修。"""


def load_board(book: Book) -> dict:
    try:
        data = read_json(book.board_path, {"cards": {}})
    except ValueError as e:
        raise BrokenBoardFile(f"取舍/看板.json 不是合法 JSON：{e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("cards"), dict):
        raise BrokenBoardFile("取舍/看板.json 的 cards 不是对象")
    return data


def thread_ids(threads: dict) -> list[str]:
    return [t["id"] for t in threads.get("threads") or []
            if isinstance(t, dict) and isinstance(t.get("id"), str) and t["id"]]


def _entry(c) -> dict:
    c = c if isinstance(c, dict) else {}
    col = c.get("col") if c.get("col") in COLS else "undecided"
    return {"col": col, "merge_into": c.get("merge_into") if col == "merge" else None,
            "note": str(c.get("note") or "")}


def reconcile(board: dict, threads: dict) -> dict:
    """带标注的看板副本（orphan / merge_invalid），不落盘。"""
    ids = thread_ids(threads)
    cards: dict[str, dict] = {}
    for tid in ids:
        cards[tid] = {**_entry(board["cards"].get(tid)), "orphan": False, "merge_invalid": False}
    for tid, c in board["cards"].items():
        if tid not in cards:
            cards[tid] = {**_entry(c), "orphan": True, "merge_invalid": False}
    for tid, c in cards.items():
        if c["col"] == "merge":
            tgt = c["merge_into"]
            if tgt == tid or tgt not in ids or cards[tgt]["col"] == "cut":
                c["merge_invalid"] = True
    return {"cards": cards}


def columns(book: Book, threads: dict) -> dict[str, dict]:
    """活着的线 → {"col", "merge_into"}，给骨架用。"""
    cards = reconcile(load_board(book), threads)["cards"]
    return {tid: {"col": c["col"], "merge_into": c["merge_into"]} for tid, c in cards.items() if not c["orphan"]}


def set_card(book: Book, threads: dict, tid: str, col: str,
             merge_into: str | None = None, note: str | None = None) -> dict:
    """改一张卡。返回对账后的整个看板。"""
    if col not in COLS:
        raise ValueError(f"列只能是 {' / '.join(COLS)}")
    ids = thread_ids(threads)
    if tid not in ids:
        raise KeyError(tid)
    with FILE_LOCK:
        board = load_board(book)
        cur = reconcile(board, threads)["cards"]
        if col == "merge":
            if merge_into == tid or merge_into not in ids:
                raise ValueError("合并要选另一条存在的线")
            if cur[merge_into]["col"] == "cut":
                raise ValueError("不能并入已经砍掉的线")
        old = _entry(board["cards"].get(tid))
        board["cards"][tid] = {"col": col, "merge_into": merge_into if col == "merge" else None,
                               "note": old["note"] if note is None else str(note)}
        write_json(book.board_path, board)
        return reconcile(board, threads)


def delete_orphan(book: Book, threads: dict, tid: str) -> dict:
    with FILE_LOCK:
        board = load_board(book)
        if tid in thread_ids(threads):
            raise ValueError("这条线还在，不能删它的卡")
        board["cards"].pop(tid, None)
        write_json(book.board_path, board)
        return reconcile(board, threads)


def non_main_versions(book: Book) -> set[str]:
    """版本组里不是主版本的场景：骨架和字数都只算主版本。"""
    try:
        data = read_json(book.versions_path, {"groups": []})
    except ValueError:
        data = {"groups": []}
    out: set[str] = set()
    for g in (data or {}).get("groups") or []:
        if isinstance(g, dict):
            out.update(m for m in g.get("members") or [] if m != g.get("main"))
    return out


def thread_stats(book: Book, threads: dict) -> dict[str, dict]:
    chars = {s.id: s.chars for s in load_scenes(book) if not s.removed}
    drop = non_main_versions(book)
    gaps: dict[str, int] = {}
    for g in threads.get("gaps") or []:
        if isinstance(g, dict) and g.get("thread"):
            gaps[g["thread"]] = gaps.get(g["thread"], 0) + 1
    out = {}
    for t in threads.get("threads") or []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        scenes = [s for s in t.get("scenes") or [] if isinstance(s, str)]
        out[t["id"]] = {
            "name": t.get("name", ""),
            "world": t.get("world", ""),
            "words": sum(chars.get(s, 0) for s in scenes if s not in drop),
            "scenes": len(scenes),
            "state": (t.get("end") or {}).get("state") or "待定",
            "gaps": gaps.get(t["id"], 0),
            "is_main": t["id"] == threads.get("main_thread"),
            "order_failed": bool(t.get("order_failed")),
        }
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q tests/test_triage.py`
Expected: PASS。`words == 22` 若不对，先确认 `seed_book` 写的正文真是「S-0001 的正文。」（11 个字），不对就按真实字数改**测试注释里的推导**并在报告里说明，别直接改数。

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/triage.py tests/test_triage.py
git commit -m "feat: 取舍看板读写、对账、每条线统计"
```

### Task 5: impact.py 程序化部分——交汇点、只在这条线出场的人物、别处的可能引用

**Files:**
- Create: `src/ligaotai/impact.py`
- Test: `tests/test_impact.py`

- [ ] **Step 1: 写失败的测试** `tests/test_impact.py`

```python
import pytest

from ligaotai.cards import card_path
from ligaotai.fsutil import read_json, write_json
from ligaotai.impact import program_impact
from ligaotai.threads_ops import load_threads


def _set_card(book, sid, **changes):
    rec = read_json(card_path(book, sid))
    rec["card"].update(changes)
    write_json(card_path(book, sid), rec)


@pytest.fixture
def ib(book_with_threads):
    b = book_with_threads
    data = read_json(b.threads_path)
    data["intersections"] = [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "龙宫借宝"}]
    write_json(b.threads_path, data)
    # 主线 S-0001 提到了支线独有人物敖广（「敖广」是规范名本身）
    _set_card(b, "S-0001", refs_elsewhere=["敖广献宝的旧事", "五行山的来历"])
    return b


def test_支线的交汇点_对方是主线(ib):
    r = program_impact(ib, load_threads(ib), "L-002")
    assert r["crossings"] == [{"other": "L-001", "scene": "S-0004", "main_scene": "S-0002", "reason": "龙宫借宝"}]


def test_主线的交汇点_对方是支线(ib):
    r = program_impact(ib, load_threads(ib), "L-001")
    assert r["crossings"] == [{"other": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "龙宫借宝"}]


def test_只在这条线出场的人物_用规范名归一(ib):
    assert program_impact(ib, load_threads(ib), "L-002")["only_characters"] == [
        {"name": "敖广", "scenes": ["S-0004", "S-0005"]}]
    # 「悟空」「行者」归到规范名 孙悟空，只在 L-001 出场
    assert program_impact(ib, load_threads(ib), "L-001")["only_characters"] == [
        {"name": "孙悟空", "scenes": ["S-0001", "S-0002", "S-0003"]}]


def test_别的线提到独有人物_算可能的引用(ib):
    refs = program_impact(ib, load_threads(ib), "L-002")["maybe_refs"]
    assert refs == [{"scene": "S-0001", "thread": "L-001", "text": "敖广献宝的旧事", "names": ["敖广"]}]


def test_人物在两条线都出场就不算独有(ib):
    _set_card(ib, "S-0001", characters=[{"name": "悟空", "role": "主要"}, {"name": "敖广", "role": "提及"}])
    assert program_impact(ib, load_threads(ib), "L-002")["only_characters"] == []


def test_代词不算人物(ib):
    _set_card(ib, "S-0004", characters=[{"name": "我", "role": "主要"}, {"name": "敖广", "role": "主要"}])
    names = [c["name"] for c in program_impact(ib, load_threads(ib), "L-002")["only_characters"]]
    assert names == ["敖广"]


def test_线不存在(ib):
    with pytest.raises(KeyError):
        program_impact(ib, load_threads(ib), "L-009")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest -q tests/test_impact.py`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现** `src/ligaotai/impact.py`（本 Task 只写程序化部分；模型部分 Task 7 加在同一个文件）

```python
"""二期：砍掉 / 合并一条线之前的影响检查（计划④ spec 第 6.3 节）。

程序化部分不花钱、立刻出：交汇点、只在这条线出场的人物、别的线里可能引用了这条线的地方。
模型部分（伏笔配对）见本文件下半部分。
"""

from __future__ import annotations

from .book import Book
from .cards import load_cards
from .entities import PRONOUNS
from .fsutil import natural_key, read_json
from .threads_input import name_map
from .triage import thread_ids

STRONG_ROLES = ("主要", "次要")


def _card(cards: dict, sid: str) -> dict:
    rec = cards.get(sid) or {}
    c = rec.get("card") if isinstance(rec, dict) else None
    return c if isinstance(c, dict) else {}


def _aliases(book: Book, canon: str) -> list[str]:
    try:
        data = read_json(book.entities_path, {"entities": []})
    except ValueError:
        data = {"entities": []}
    names = {canon}
    for e in (data or {}).get("entities") or []:
        if isinstance(e, dict) and e.get("type") == "person" and e.get("canonical") == canon:
            names.update(n for n in e.get("names") or [] if isinstance(n, str) and n)
    return sorted(names, key=len, reverse=True)


def program_impact(book: Book, threads: dict, tid: str) -> dict:
    if tid not in thread_ids(threads):
        raise KeyError(tid)
    main = threads.get("main_thread")

    crossings = []
    for x in threads.get("intersections") or []:
        if not isinstance(x, dict) or not x.get("thread"):
            continue
        if x["thread"] == tid:
            other = main
        elif tid == main:
            other = x["thread"]
        else:
            continue
        crossings.append({"other": other, "scene": x.get("scene"), "main_scene": x.get("main_scene"),
                          "reason": x.get("reason", "")})

    cards = load_cards(book)
    cmap = name_map(book)
    appear: dict[str, set[str]] = {}
    strong: dict[str, set[str]] = {}
    for t in threads.get("threads") or []:
        if not isinstance(t, dict):
            continue
        for sid in t.get("scenes") or []:
            for ch in _card(cards, sid).get("characters") or []:
                if not isinstance(ch, dict):
                    continue
                name = str(ch.get("name") or "").strip()
                if not name or name in PRONOUNS:
                    continue
                canon = cmap.get(("person", name), name)
                appear.setdefault(canon, set()).add(t["id"])
                if t["id"] == tid and ch.get("role") in STRONG_ROLES:
                    strong.setdefault(canon, set()).add(sid)
    only = [{"name": n, "scenes": sorted(s, key=natural_key)}
            for n, s in strong.items() if appear.get(n) == {tid}]
    only.sort(key=lambda c: (-len(c["scenes"]), c["name"]))

    aliases = {c["name"]: _aliases(book, c["name"]) for c in only}
    refs = []
    for t in threads.get("threads") or []:
        if not isinstance(t, dict) or t.get("id") == tid:
            continue
        for sid in t.get("scenes") or []:
            for r in _card(cards, sid).get("refs_elsewhere") or []:
                text = str(r)
                hit = [n for n, al in aliases.items() if any(a in text for a in al)]
                if hit:
                    refs.append({"scene": sid, "thread": t["id"], "text": text, "names": hit})
    return {"thread": tid, "crossings": crossings, "only_characters": only, "maybe_refs": refs}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q tests/test_impact.py`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/impact.py tests/test_impact.py
git commit -m "feat: 影响检查程序化部分：交汇点、独有人物、别处引用"
```

### Task 6: advice.py——AI 取舍建议

**Files:**
- Create: `src/ligaotai/advice.py`、`prompts/triage_advice.md`
- Test: `tests/test_advice.py`

- [ ] **Step 1: 写提示词** `prompts/triage_advice.md`

```markdown
取舍看板的 AI 建议：所有线一次调用，给每条线一个去留建议和理由。理由里的每个结论都要带场景编号。

## system
你是长篇小说的责任编辑。作者的稿子已经被理成若干条故事线，现在要决定每条线的去留。

对每条线给一个建议：
- keep：保留；
- merge：并入另一条线（写 merge_into，填那条线的编号）；
- cut：砍掉；
- flashback：改写成回忆 / 侧写，不再单独成线。

判断依据：这条线跟主线的关系、完成度、篇幅、是否重复、砍掉后损失什么。
理由写一两句话，**每句话都要带场景编号**，写法是 [S-0003] 或 [S-0003,S-0010]，编号只能用输入里列出的。

只输出 JSON，形如：
{"advice": [{"thread": "L-001", "advice": "keep", "merge_into": null, "reason": "……[S-0003]"}]}
每条线都要给，且只给一次。

## user
全书地图（节选）：
$map

各条线：
$threads
```

- [ ] **Step 2: 写失败的测试** `tests/test_advice.py`

```python
import json

from helpers import FakeBackend

from ligaotai.advice import advice_input, advice_status, check_advice, run_advice
from ligaotai.config import AppConfig
from ligaotai.fsutil import atomic_write_text, read_json
from ligaotai.llm import LLMClient
from ligaotai.threads_ops import load_threads

GOOD = {"advice": [
    {"thread": "L-001", "advice": "keep", "merge_into": None, "reason": "主线 [S-0001]"},
    {"thread": "L-002", "advice": "merge", "merge_into": "L-001", "reason": "篇幅短 [S-0004]"},
]}


def test_输入_有档案用档案摘要_没档案用about_列出场景编号(book_with_threads):
    b = book_with_threads
    atomic_write_text(b.thread_archive_dir / "L-001.md",
                      "# L-001 取经\n- 一句话：取经的主线 [S-0001]\n\n## 来龙去脉\n一路西行 [S-0002]\n\n## 主要人物\n- 略\n")
    values, tids, allowed = advice_input(b, load_threads(b))
    assert tids == ["L-001", "L-002"]
    assert allowed == {"S-0001", "S-0002", "S-0003", "S-0004", "S-0005"}
    assert "一路西行 [S-0002]" in values["threads"]
    assert "主要人物" not in values["threads"]          # 只取到「主要人物」之前
    assert "场景：S-0004、S-0005" in values["threads"]
    assert values["map"] == "（还没有全书地图）"


def test_核对_漏线_重复_编号不在范围_合并目标不对(book_with_threads):
    tids, allowed = ["L-001", "L-002"], {"S-0001", "S-0004"}
    assert check_advice(GOOD, tids, allowed) == []
    bad = {"advice": [{"thread": "L-001", "advice": "merge", "merge_into": "L-001", "reason": "x [S-0009]"},
                      {"thread": "L-001", "advice": "drop", "reason": "没编号"}]}
    problems = "\n".join(check_advice(bad, tids, allowed))
    for word in ["L-002", "重复", "S-0009", "merge_into", "drop", "场景编号"]:
        assert word in problems


def test_跑一次_写进建议文件_再跑命中缓存不再调模型(book_with_threads):
    b = book_with_threads
    backend = FakeBackend(handler=lambda tier, messages: json.dumps(GOOD, ensure_ascii=False))
    client = LLMClient(AppConfig(), backend, log_dir=b.logs_dir)
    r = run_advice(b, client)
    assert r["ok"] is True and r["count"] == 2
    saved = read_json(b.advice_path)
    assert [i["advice"] for i in saved["items"]] == ["keep", "merge"]
    assert advice_status(b, load_threads(b))["stale"] is False
    run_advice(b, client)
    assert len(backend.calls) == 1


def test_模型一直不合规_不写文件_报失败(book_with_threads):
    b = book_with_threads
    backend = FakeBackend(handler=lambda tier, messages: json.dumps({"advice": []}))
    client = LLMClient(AppConfig(), backend, log_dir=b.logs_dir)
    r = run_advice(b, client)
    assert r["ok"] is False and r["failed"]
    assert not b.advice_path.exists()


def test_线变了_建议标过期(book_with_threads):
    b = book_with_threads
    backend = FakeBackend(handler=lambda tier, messages: json.dumps(GOOD, ensure_ascii=False))
    run_advice(b, LLMClient(AppConfig(), backend, log_dir=b.logs_dir))
    data = read_json(b.threads_path)
    data["threads"][1]["about"] = "改过的概述"
    from ligaotai.fsutil import write_json
    write_json(b.threads_path, data)
    assert advice_status(b, load_threads(b))["stale"] is True
```

注意：`test_模型一直不合规…` 里模型返回 `{"advice": []}`，`check_advice` 会一直报漏线，`chat_json` 重试用尽后返回「最好的那次」——**它不抛错**（见 `llm.chat_json` 末尾 `if best is not None: return best`），而且 `Caller` 会把这个不合规的结果**存进缓存**。所以调用时必须传 `usable=lambda d: not check(d)`：Caller 见到不可用会删缓存、记 `failed`、返回 `None`。下面补一条测试守住「失败后重跑会真的再调模型」。

追加这条测试：

```python
def test_失败的结果不留缓存_重跑会再调模型(book_with_threads):
    b = book_with_threads
    backend = FakeBackend(handler=lambda tier, messages: json.dumps({"advice": []}))
    client = LLMClient(AppConfig(), backend, log_dir=b.logs_dir)
    run_advice(b, client)
    n = len(backend.calls)
    run_advice(b, client)
    assert len(backend.calls) == 2 * n
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest -q tests/test_advice.py`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 4: 实现** `src/ligaotai/advice.py`

```python
"""二期：取舍看板的 AI 建议（计划④ spec 第 6.2 节）。所有线一次调用，结果写 取舍/建议.json。"""

from __future__ import annotations

import asyncio

from .archive import input_sig, refs_in
from .book import Book, now_iso
from .fsutil import read_json, write_json
from .llm import LLMClient
from .llm_caller import Caller, Progress, _noop
from .threads_ops import load_threads
from .triage import thread_ids, thread_stats

PROMPT = "triage_advice"
ADVICE = ("keep", "merge", "cut", "flashback")
SUMMARY_MAX = 1500
MAP_MAX = 6000


def _summary(book: Book, t: dict) -> str:
    """档案开头到「## 主要人物」之前（一句话 + 来龙去脉）；没有档案就用线的 about。"""
    p = book.thread_archive_dir / f"{t['id']}.md"
    if p.exists():
        text = p.read_text(encoding="utf-8")
        cut = text.find("## 主要人物")
        return (text if cut < 0 else text[:cut]).strip()[:SUMMARY_MAX]
    return str(t.get("about") or "（没有概述）")


def advice_input(book: Book, threads: dict) -> tuple[dict, list[str], set[str]]:
    stats = thread_stats(book, threads)
    blocks, allowed = [], set()
    for t in threads.get("threads") or []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        s = stats[t["id"]]
        scenes = [x for x in t.get("scenes") or [] if isinstance(x, str)]
        allowed.update(scenes)
        head = (f"## {t['id']} {s['name']}（{'主线；' if s['is_main'] else ''}{s['scenes']} 块；"
                f"约 {s['words']} 字；{s['state']}）")
        blocks.append(f"{head}\n{_summary(book, t)}\n场景：{'、'.join(scenes)}")
    map_text = book.map_path.read_text(encoding="utf-8")[:MAP_MAX] if book.map_path.exists() else "（还没有全书地图）"
    return {"map": map_text, "threads": "\n\n".join(blocks)}, thread_ids(threads), allowed


def check_advice(data, tids: list[str], allowed: set[str]) -> list[str]:
    items = data.get("advice") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return ["要输出 {\"advice\": [...]}"]
    problems, seen = [], []
    for it in items:
        if not isinstance(it, dict):
            problems.append("advice 里每一项都要是对象")
            continue
        tid = it.get("thread")
        if tid in seen:
            problems.append(f"{tid} 重复出现了，每条线只给一次")
        seen.append(tid)
        if tid not in tids:
            problems.append(f"没有这条线：{tid}")
        a = it.get("advice")
        if a not in ADVICE:
            problems.append(f"{tid} 的 advice 只能是 {' / '.join(ADVICE)}，不能是 {a}")
        if a == "merge" and (it.get("merge_into") not in tids or it.get("merge_into") == tid):
            problems.append(f"{tid} 建议合并，merge_into 要填另一条存在的线的编号")
        refs = refs_in(str(it.get("reason") or ""))
        if not refs:
            problems.append(f"{tid} 的理由没带场景编号")
        bad = sorted({r for r in refs if r not in allowed})
        if bad:
            problems.append(f"{tid} 的理由用了不存在的编号：" + "、".join(bad))
    missing = [t for t in tids if t not in seen]
    if missing:
        problems.append("这几条线没给建议：" + "、".join(missing))
    return problems


def _sig(values: dict) -> str:
    return input_sig(values["map"] + "\n\x1f\n" + values["threads"], PROMPT)


def advice_status(book: Book, threads: dict) -> dict | None:
    """已有建议 + 是否过期（输入变了）。没有建议返回 None。"""
    try:
        saved = read_json(book.advice_path)
    except ValueError:
        saved = None
    if not isinstance(saved, dict) or not isinstance(saved.get("items"), list):
        return None
    values, _, _ = advice_input(book, threads)
    return {**saved, "stale": saved.get("sig") != _sig(values)}


def run_advice(book: Book, client: LLMClient, progress: Progress = _noop) -> dict:
    return asyncio.run(_run_advice(book, client, progress))


async def _run_advice(book: Book, client: LLMClient, progress: Progress) -> dict:
    threads = load_threads(book)
    values, tids, allowed = advice_input(book, threads)
    caller = Caller(book, client, progress, cache_path=book.triage_cache_path, tag_prefix="triage")
    caller.plan(1)

    def check(d):
        return check_advice(d, tids, allowed)

    # chat_json 重试用尽时返回「最好的一次」而不是报错，Caller 还会把它存进缓存——不传 usable 的话，
    # 一次不合规的结果会钉死在缓存里，以后每次重跑都命中它、永远不再重试。usable 返回假时
    # Caller 会删掉这条缓存、记进 failed、返回 None。
    data = await caller.call(PROMPT, values, check, "advice", usable=lambda d: not check(d))
    if data is None:
        return {"ok": False, "failed": caller.failed}
    write_json(book.advice_path, {"generated": now_iso(), "sig": _sig(values), "items": data["advice"]})
    return {"ok": True, "count": len(data["advice"])}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest -q tests/test_advice.py`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add src/ligaotai/advice.py prompts/triage_advice.md tests/test_advice.py
git commit -m "feat: 取舍看板 AI 建议（所有线一次调用，按签名缓存）"
```

### Task 7: impact.py 模型部分——伏笔配对与补救建议

**Files:**
- Modify: `src/ligaotai/impact.py`
- Create: `prompts/triage_impact.md`
- Test: `tests/test_impact.py`（追加）

- [ ] **Step 1: 写提示词** `prompts/triage_impact.md`

```markdown
影响检查的模型部分：一条线要被砍掉或并入别的线时，找出会落空的伏笔，并写补救建议。

## system
作者打算对一条故事线做处理（砍掉，或并入另一条线）。下面给出这条线里埋下 / 回收的伏笔，以及其他线里埋下 / 回收的伏笔，每条都带场景编号。

请找出**跨线的伏笔对**：
- 这条线埋下、在别的线回收的；
- 别的线埋下、在这条线回收的。
只收你有把握是同一件事的对，没有就给空列表。

然后写一段补救建议：处理之后这些伏笔怎么办（删掉、改到哪条线收、改写成什么），合并时要针对并入的那条线写。补救建议里的每句话都要带场景编号，写法 [S-0003]，编号只能用输入里出现的。

只输出 JSON：
{"pairs": [{"planted": "S-0002", "resolved": "S-0040", "hook": "一句话说是什么伏笔"}], "remedy": "……[S-0002]"}

## user
$action

这条线的伏笔：
$own

其他线的伏笔：
$others
```

- [ ] **Step 2: 写失败的测试**（追加到 `tests/test_impact.py`）

```python
import json

from helpers import FakeBackend

from ligaotai.config import AppConfig
from ligaotai.impact import check_impact, impact_input, model_impact_status, run_impact
from ligaotai.llm import LLMClient
from ligaotai.triage import set_card


def _hooks(b):
    # S-0002（L-001）埋「紧箍咒的来历」（fixture 自带）；S-0004（L-002）回收它；S-0005 埋一个没人收的
    _set_card(b, "S-0004", hooks_resolved=["紧箍咒原来是观音所赐"])
    _set_card(b, "S-0005", hooks_planted=["定海神针的去向"])


def test_输入_这条线和其他线分开列_带动作(ib):
    _hooks(ib)
    th = load_threads(ib)
    set_card(ib, th, "L-002", "cut")
    values, own, others = impact_input(ib, th, "L-002")
    assert "砍掉 L-002" in values["action"]
    assert "S-0004｜收｜紧箍咒原来是观音所赐" in values["own"]
    assert "S-0005｜埋｜定海神针的去向" in values["own"]
    assert "L-001｜S-0002｜埋｜紧箍咒的来历" in values["others"]
    assert own == {"S-0004", "S-0005"} and others == {"S-0002"}


def test_合并时动作写明并入哪条线(ib):
    th = load_threads(ib)
    set_card(ib, th, "L-002", "merge", merge_into="L-001")
    values, _, _ = impact_input(ib, load_threads(ib), "L-002")
    assert "把 L-002 并入 L-001" in values["action"]


def test_被砍的线不算其他线(ib):
    _hooks(ib)
    th = load_threads(ib)
    set_card(ib, th, "L-001", "cut")
    set_card(ib, th, "L-002", "cut")
    _, _, others = impact_input(ib, th, "L-002")
    assert others == set()


def test_核对_两端要一端在这条线一端在别的线(ib):
    own, others = {"S-0004", "S-0005"}, {"S-0002"}
    ok = {"pairs": [{"planted": "S-0002", "resolved": "S-0004", "hook": "紧箍咒"}], "remedy": "改到主线收 [S-0002]"}
    assert check_impact(ok, own, others) == []
    bad = {"pairs": [{"planted": "S-0004", "resolved": "S-0005", "hook": "x"},
                     {"planted": "S-0002", "resolved": "S-0099", "hook": "y"}],
           "remedy": "没编号"}
    text = "\n".join(check_impact(bad, own, others))
    assert "S-0004" in text and "S-0099" in text and "补救建议" in text


def test_跑一次_结果存影响文件_看板动作变了就过期(ib):
    _hooks(ib)
    th = load_threads(ib)
    set_card(ib, th, "L-002", "cut")
    reply = {"pairs": [{"planted": "S-0002", "resolved": "S-0004", "hook": "紧箍咒"}], "remedy": "改到主线收 [S-0002]"}
    backend = FakeBackend(handler=lambda tier, messages: json.dumps(reply, ensure_ascii=False))
    r = run_impact(ib, LLMClient(AppConfig(), backend, log_dir=ib.logs_dir), "L-002")
    assert r["ok"] is True
    st = model_impact_status(ib, load_threads(ib), "L-002")
    assert st["stale"] is False and st["pairs"][0]["resolved"] == "S-0004"
    set_card(ib, th, "L-002", "merge", merge_into="L-001")
    assert model_impact_status(ib, load_threads(ib), "L-002")["stale"] is True


def test_这条线一个伏笔都没有_不调模型(ib):
    th = load_threads(ib)
    set_card(ib, th, "L-002", "cut")
    backend = FakeBackend(handler=lambda tier, messages: "{}")
    r = run_impact(ib, LLMClient(AppConfig(), backend, log_dir=ib.logs_dir), "L-002")
    assert r["ok"] is True and backend.calls == []
    assert model_impact_status(ib, load_threads(ib), "L-002")["pairs"] == []


def test_卡不在砍掉或合并列_不许跑(ib):
    backend = FakeBackend(handler=lambda tier, messages: "{}")
    with pytest.raises(ValueError):
        run_impact(ib, LLMClient(AppConfig(), backend, log_dir=ib.logs_dir), "L-002")
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest -q tests/test_impact.py`
Expected: 新测试 FAIL（`ImportError: cannot import name 'check_impact'`）

- [ ] **Step 4: 实现**（追加到 `src/ligaotai/impact.py`，并在文件顶部补 import）

顶部 import 区改成：

```python
from __future__ import annotations

import asyncio

from .archive import input_sig, refs_in
from .book import FILE_LOCK, Book, now_iso
from .cards import load_cards
from .entities import PRONOUNS
from .fsutil import natural_key, read_json, write_json
from .llm import LLMClient
from .llm_caller import Caller, Progress, _noop
from .threads_input import name_map
from .threads_ops import load_threads
from .triage import columns, thread_ids
```

文件末尾追加：

```python
# ---------------------------------------------------------------------------
# 模型部分：跨线伏笔配对 + 补救建议（按需一次调用，结果存 取舍/影响.json）
# ---------------------------------------------------------------------------

PROMPT = "triage_impact"


def _hook_lines(cards: dict, sid: str, prefix: str = "") -> list[str]:
    c = _card(cards, sid)
    out = [f"{prefix}{sid}｜埋｜{h}" for h in c.get("hooks_planted") or [] if str(h).strip()]
    out += [f"{prefix}{sid}｜收｜{h}" for h in c.get("hooks_resolved") or [] if str(h).strip()]
    return out


def impact_input(book: Book, threads: dict, tid: str) -> tuple[dict, set[str], set[str]]:
    """渲染模型输入。返回 (values, 这条线有伏笔的场景, 其他未砍线有伏笔的场景)。"""
    if tid not in thread_ids(threads):
        raise KeyError(tid)
    cols = columns(book, threads)
    me = cols.get(tid, {"col": "undecided", "merge_into": None})
    if me["col"] == "merge":
        action = f"动作：把 {tid} 并入 {me['merge_into']}"
    else:
        action = f"动作：砍掉 {tid}"
    cards = load_cards(book)
    own_lines, own_ids, other_lines, other_ids = [], set(), [], set()
    for t in threads.get("threads") or []:
        if not isinstance(t, dict):
            continue
        is_me = t.get("id") == tid
        if not is_me and cols.get(t.get("id"), {}).get("col") == "cut":
            continue
        for sid in t.get("scenes") or []:
            lines = _hook_lines(cards, sid, "" if is_me else f"{t['id']}｜")
            if not lines:
                continue
            (own_lines if is_me else other_lines).extend(lines)
            (own_ids if is_me else other_ids).add(sid)
    values = {"action": action, "own": "\n".join(own_lines) or "（没有）",
              "others": "\n".join(other_lines) or "（没有）"}
    return values, own_ids, other_ids


def check_impact(data, own: set[str], others: set[str]) -> list[str]:
    if not isinstance(data, dict) or not isinstance(data.get("pairs"), list):
        return ["要输出 {\"pairs\": [...], \"remedy\": \"...\"}"]
    problems = []
    for p in data["pairs"]:
        if not isinstance(p, dict):
            problems.append("pairs 里每一项都要是对象")
            continue
        a, b = p.get("planted"), p.get("resolved")
        if not ((a in own and b in others) or (a in others and b in own)):
            problems.append(f"伏笔对 {a} → {b} 不对：必须一端在这条线、另一端在其他线，编号只能用输入里的")
        if not str(p.get("hook") or "").strip():
            problems.append(f"伏笔对 {a} → {b} 没写是什么伏笔")
    allowed = own | others
    refs = refs_in(str(data.get("remedy") or ""))
    if not refs:
        problems.append("补救建议里没带场景编号")
    bad = sorted({r for r in refs if r not in allowed})
    if bad:
        problems.append("补救建议用了不在输入里的编号：" + "、".join(bad))
    return problems


def _impact_sig(values: dict) -> str:
    return input_sig(values["action"] + "\n\x1f\n" + values["own"] + "\n\x1f\n" + values["others"], PROMPT)


def _load_impacts(book: Book) -> dict:
    try:
        data = read_json(book.impact_path, {})
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def model_impact_status(book: Book, threads: dict, tid: str) -> dict | None:
    """这条线最近一次伏笔影响 + 是否过期（看板动作或伏笔输入变了）。没有返回 None。"""
    saved = _load_impacts(book).get(tid)
    if not isinstance(saved, dict):
        return None
    values, _, _ = impact_input(book, threads, tid)
    return {**saved, "stale": saved.get("sig") != _impact_sig(values)}


def run_impact(book: Book, client: LLMClient, tid: str, progress: Progress = _noop) -> dict:
    return asyncio.run(_run_impact(book, client, tid, progress))


async def _run_impact(book: Book, client: LLMClient, tid: str, progress: Progress) -> dict:
    threads = load_threads(book)
    col = columns(book, threads).get(tid, {}).get("col")
    if col not in ("cut", "merge"):
        raise ValueError("只有放进「砍掉」或「合并」的线才做影响检查")
    values, own, others = impact_input(book, threads, tid)
    result = {"pairs": [], "remedy": ""}
    failed: list = []
    if own:
        caller = Caller(book, client, progress, cache_path=book.triage_cache_path, tag_prefix="triage")
        caller.plan(1)

        def check(d):
            return check_impact(d, own, others)

        # usable：不合规的结果别留在缓存里（见 advice.py 同一处注释）
        data = await caller.call(PROMPT, values, check, f"impact/{tid}", usable=lambda d: not check(d))
        if data is None:
            return {"ok": False, "failed": caller.failed}
        result = {"pairs": data["pairs"], "remedy": data["remedy"]}
    with FILE_LOCK:
        impacts = _load_impacts(book)
        impacts[tid] = {"sig": _impact_sig(values), "generated": now_iso(), **result}
        write_json(book.impact_path, impacts)
    return {"ok": True, "pairs": len(result["pairs"]), "failed": failed}
```

（提醒：别把核对放宽成「两端都在输入范围里」，那会放过「两端都在这条线」的错对——必须一端在这条线、一端在其他线。）

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest -q tests/test_impact.py`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add src/ligaotai/impact.py prompts/triage_impact.md tests/test_impact.py
git commit -m "feat: 影响检查模型部分：跨线伏笔配对与补救建议"
```

### Task 8: 看板 / 建议 / 影响接口

**Files:**
- Modify: `src/ligaotai/api.py`
- Test: `tests/test_api_triage.py`（追加）

- [ ] **Step 1: 写失败的测试**（追加）

```python
import json

from helpers import seed_book


def _seed_threads(tmp_path):
    b = _book(tmp_path)
    seed_book(b, [{"id": f"S-000{i}", "persons": ["敖广"] if i >= 4 else ["悟空"]} for i in range(1, 6)])
    write_json(b.threads_path, {
        "next_world": 2, "next_thread": 3, "time_unit": "年", "main_thread": "L-001", "main_by": "auto",
        "worlds": [{"id": "W-01", "name": "西游", "reason": "", "status": "draft", "notes": [], "outlines": []}],
        "threads": [
            {"id": "L-001", "world": "W-01", "name": "取经", "about": "主线", "status": "draft",
             "scenes": ["S-0001", "S-0002", "S-0003"],
             "times": {"S-0001": {"t": 0, "conf": "高"}, "S-0002": {"t": 1, "conf": "高"}, "S-0003": {"t": 2, "conf": "高"}},
             "outlines": [], "offset": 0, "end": {"state": "待定", "note": "", "last": "S-0003"}, "order_failed": False},
            {"id": "L-002", "world": "W-01", "name": "龙宫", "about": "支线", "status": "draft",
             "scenes": ["S-0004", "S-0005"],
             "times": {"S-0004": {"t": 0, "conf": "高"}, "S-0005": {"t": 1, "conf": "高"}},
             "outlines": [], "offset": 3, "end": {"state": "完结", "note": "", "last": "S-0005"}, "order_failed": False}],
        "intersections": [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "借宝"}],
        "gaps": [], "unassigned": [], "pending": []})
    return b


def _wait(c, r):
    assert r.status_code == 202, r.text
    job = c.app.state.runner.wait(r.json()["id"]).to_dict()
    assert job["status"] == "done", job["error"]
    return job


def test_读看板_带统计和空建议(tmp_path):
    c = _client(tmp_path)
    _seed_threads(tmp_path)
    r = c.get(f"{BOOK}/triage/board").json()
    assert r["cards"]["L-001"]["col"] == "undecided"
    assert r["stats"]["L-001"]["is_main"] is True
    assert r["advice"] is None


def test_改卡_错误映射(tmp_path):
    c = _client(tmp_path)
    _seed_threads(tmp_path)
    r = c.put(f"{BOOK}/triage/board/L-002", json={"col": "merge", "merge_into": "L-001"})
    assert r.status_code == 200 and r.json()["cards"]["L-002"]["merge_into"] == "L-001"
    assert c.put(f"{BOOK}/triage/board/L-009", json={"col": "keep"}).status_code == 404
    assert c.put(f"{BOOK}/triage/board/L-002", json={"col": "maybe"}).status_code == 400
    assert c.delete(f"{BOOK}/triage/board/L-001").status_code == 400


def test_看板文件坏了报500带文件名(tmp_path):
    c = _client(tmp_path)
    b = _seed_threads(tmp_path)
    b.triage_dir.mkdir(parents=True, exist_ok=True)
    b.board_path.write_text("{坏", encoding="utf-8")
    r = c.get(f"{BOOK}/triage/board")
    assert r.status_code == 500 and "看板.json" in r.json()["detail"]


def test_没跑归线时看板404(tmp_path):
    c = _client(tmp_path)
    _book(tmp_path)
    assert c.get(f"{BOOK}/triage/board").status_code == 404


def test_生成建议是任务_跑完看板里带建议(tmp_path):
    reply = {"advice": [{"thread": "L-001", "advice": "keep", "merge_into": None, "reason": "主线 [S-0001]"},
                        {"thread": "L-002", "advice": "cut", "merge_into": None, "reason": "可删 [S-0004]"}]}
    c = _client(tmp_path, handler=lambda tier, messages: json.dumps(reply, ensure_ascii=False))
    _seed_threads(tmp_path)
    _wait(c, c.post(f"{BOOK}/triage/advice"))
    adv = c.get(f"{BOOK}/triage/board").json()["advice"]
    assert [i["advice"] for i in adv["items"]] == ["keep", "cut"] and adv["stale"] is False


def test_影响检查_程序部分即时_模型部分是任务(tmp_path):
    reply = {"pairs": [], "remedy": "无须补救 [S-0004]"}
    c = _client(tmp_path, handler=lambda tier, messages: json.dumps(reply, ensure_ascii=False))
    b = _seed_threads(tmp_path)
    r = c.get(f"{BOOK}/triage/impact/L-002").json()
    assert r["program"]["crossings"][0]["main_scene"] == "S-0002"
    assert r["model"] is None
    assert c.post(f"{BOOK}/triage/impact/L-002").status_code == 400  # 还在「还没想好」列
    c.put(f"{BOOK}/triage/board/L-002", json={"col": "cut"})
    from ligaotai.cards import card_path
    rec = read_json(card_path(b, "S-0004"))
    rec["card"]["hooks_planted"] = ["龙宫宝物的下落"]
    write_json(card_path(b, "S-0004"), rec)
    _wait(c, c.post(f"{BOOK}/triage/impact/L-002"))
    m = c.get(f"{BOOK}/triage/impact/L-002").json()["model"]
    assert m["remedy"] == "无须补救 [S-0004]" and m["stale"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest -q tests/test_api_triage.py`
Expected: 新测试 FAIL

- [ ] **Step 3: 实现**（`src/ligaotai/api.py`）

import 区加：

```python
from . import advice as adv
from . import impact as imp
from . import triage as tri
```

请求体：

```python
class CardReq(BaseModel):
    col: str
    merge_into: str | None = None
    note: str | None = None
```

`create_app` 里加一个读归线 + 看板错误映射的工具（放在 `verdict_op` 后面）：

```python
    def triage_op(fn: Callable[[], object]):
        try:
            return fn()
        except KeyError:
            raise HTTPException(404, "没有这条线")
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except tops.BrokenThreadsFile as e:
            raise HTTPException(409, str(e))
        except tri.BrokenBoardFile as e:
            raise _读坏了("取舍/看板.json", str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
```

路由（放在裁决路由后面）：

```python
    @app.get("/api/books/{name}/triage/board")
    def triage_board(name: str) -> dict:
        b = get_book(name)

        def read():
            th = tops.load_threads(b)
            return {**tri.reconcile(tri.load_board(b), th), "stats": tri.thread_stats(b, th),
                    "advice": adv.advice_status(b, th)}

        return triage_op(read)

    @app.put("/api/books/{name}/triage/board/{tid}")
    def triage_card(name: str, tid: str, req: CardReq) -> dict:
        require_idle()
        b = get_book(name)
        return triage_op(lambda: tri.set_card(b, tops.load_threads(b), tid, req.col, req.merge_into, req.note))

    @app.delete("/api/books/{name}/triage/board/{tid}")
    def triage_delete_card(name: str, tid: str) -> dict:
        require_idle()
        b = get_book(name)
        return triage_op(lambda: tri.delete_orphan(b, tops.load_threads(b), tid))

    @app.post("/api/books/{name}/triage/advice", status_code=202)
    def triage_advice(name: str) -> dict:
        b = get_book(name)
        triage_op(lambda: tops.load_threads(b))  # 没跑归线先报 404，别等任务里再炸
        client = make_client(b)
        return submit(b, "triage_advice", lambda p: adv.run_advice(b, client, p), track_step=False)

    @app.get("/api/books/{name}/triage/impact/{tid}")
    def triage_impact(name: str, tid: str) -> dict:
        b = get_book(name)

        def read():
            th = tops.load_threads(b)
            return {"program": imp.program_impact(b, th, tid), "model": imp.model_impact_status(b, th, tid)}

        return triage_op(read)

    @app.post("/api/books/{name}/triage/impact/{tid}", status_code=202)
    def triage_impact_run(name: str, tid: str) -> dict:
        b = get_book(name)

        def precheck():
            th = tops.load_threads(b)
            if tid not in tri.thread_ids(th):
                raise KeyError(tid)
            if tri.columns(b, th).get(tid, {}).get("col") not in ("cut", "merge"):
                raise ValueError("只有放进「砍掉」或「合并」的线才做影响检查")

        triage_op(precheck)
        client = make_client(b)
        return submit(b, "triage_impact", lambda p: imp.run_impact(b, client, tid, p), track_step=False)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q tests/test_api_triage.py && uv run pytest -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/api.py tests/test_api_triage.py
git commit -m "feat: 看板、AI 建议、影响检查接口"
```

---

# 里程碑 3：成书骨架

### Task 9: skeleton_order.py——全局时间交织、空洞插入、章节备注（纯函数）

**Files:**
- Create: `src/ligaotai/skeleton_order.py`
- Test: `tests/test_skeleton_order.py`

**这一步的期望值是用独立脚本从真书 fixture 算出来的**（不依赖实现），实现算错测试当场红，**不许改断言迁就实现**。

雪月梅（`xueyuemei-threads.json`，主线 L-001，5 条线 101 块）：
- 能排进时间轴 100 块，排不进 1 块：`S-0084`，原因 `no_time`
- 前 10 块：`S-0086`(L-002, -10) `S-0001`(L-001, 0) `S-0012`(L-002, 0) `S-0006`(L-003, 0) `S-0022` `S-0071` `S-0090` `S-0087`(L-002, 0.0999…) `S-0074` `S-0023`
  - 注意全局时间 0 的三块：**主线优先**，再按线编号（L-002 在 L-003 前）
  - `S-0087` 的全局时间是浮点误差的 0.09999999999999964，排在 0.07 和 0.12 之间，**别用四舍五入去「修」它**
- 最后 3 块：`S-0129` `S-0130` `S-0091`
- 81 个缺口：按 `after` 定位 34 个、按 `before` 定位 41 个、两端都没有 6 个（进 `unplaced.holes`）
- 砍掉 L-002：剩 92 块；只属于 L-002 的缺口不插，剩 74 个缺口里定位 68 个、未定位 6 个；L-002 的交汇点 3 个，主线端是 `S-0001` `S-0066` `S-0002`

西游记（`xiyouji-threads.json`）：238 块全部能排、0 块排不进；前两块 `S-0142` `S-0143` 全局时间都是 -871.8、同一条线，按线内原顺序；42 个缺口全部定位。

- [ ] **Step 1: 写失败的测试** `tests/test_skeleton_order.py`

```python
import json
from pathlib import Path

from ligaotai.skeleton_order import build_sequence, insert_holes, notes_for

FIX = Path(__file__).resolve().parents[1] / "web" / "src" / "components" / "__fixtures__"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _cut(*tids):
    return {t: {"col": "cut", "merge_into": None} for t in tids}


def test_雪月梅_全留_交织顺序():
    th = _load("xueyuemei-threads.json")
    seq, unplaced = build_sequence(th, {}, set())
    assert len(seq) == 100
    assert unplaced == [{"id": "S-0084", "thread": unplaced[0]["thread"], "why": "no_time"}]
    assert [x["id"] for x in seq[:10]] == ["S-0086", "S-0001", "S-0012", "S-0006", "S-0022",
                                           "S-0071", "S-0090", "S-0087", "S-0074", "S-0023"]
    assert [x["thread"] for x in seq[:4]] == ["L-002", "L-001", "L-002", "L-003"]
    assert [x["id"] for x in seq[-3:]] == ["S-0129", "S-0130", "S-0091"]


def test_雪月梅_空洞定位():
    th = _load("xueyuemei-threads.json")
    seq, _ = build_sequence(th, {}, set())
    items, holes_unplaced = insert_holes(seq, th["gaps"], {})
    placed = [i for i in items if i["type"] == "hole"]
    assert len(placed) == 75 and len(holes_unplaced) == 6
    assert all(h["why"] == "no_anchor" for h in holes_unplaced)
    ids = [h["id"] for h in placed] + [h["id"] for h in holes_unplaced]
    assert ids == [f"H-{i:03d}" for i in range(1, 82)]


def test_雪月梅_砍掉L002():
    th = _load("xueyuemei-threads.json")
    seq, _ = build_sequence(th, _cut("L-002"), set())
    assert len(seq) == 92 and all(x["thread"] != "L-002" for x in seq)
    items, holes_unplaced = insert_holes(seq, th["gaps"], _cut("L-002"))
    placed = [i for i in items if i["type"] == "hole"]
    assert len(placed) == 68 and len(holes_unplaced) == 6
    assert all(h["thread"] != "L-002" for h in placed + holes_unplaced)


def test_西游记_同一时刻同一条线按线内顺序():
    th = _load("xiyouji-threads.json")
    seq, unplaced = build_sequence(th, {}, set())
    assert len(seq) == 238 and unplaced == []
    assert [x["id"] for x in seq[:2]] == ["S-0142", "S-0143"]
    items, holes_unplaced = insert_holes(seq, th["gaps"], {})
    assert sum(1 for i in items if i["type"] == "hole") == 42 and holes_unplaced == []


def _mini():
    return {
        "main_thread": "L-001",
        "threads": [
            {"id": "L-001", "scenes": ["S-0001", "S-0002", "S-0003"], "offset": 0,
             "times": {"S-0001": {"t": 0}, "S-0002": {"t": 2}, "S-0003": {"t": None}}},
            {"id": "L-002", "scenes": ["S-0004", "S-0005"], "offset": 1,
             "times": {"S-0004": {"t": 0}, "S-0005": {"t": 5}}},
            {"id": "L-003", "scenes": ["S-0006"], "offset": None, "times": {"S-0006": {"t": 0}}},
        ],
        "unassigned": [{"scene": "S-0007", "reason": "x"}],
        "intersections": [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "r"}],
    }


def test_排不进时间轴的三种原因_非主版本不出现():
    seq, unplaced = build_sequence(_mini(), {}, {"S-0005"})
    assert [x["id"] for x in seq] == ["S-0001", "S-0004", "S-0002"]
    assert [(u["id"], u["why"]) for u in unplaced] == [
        ("S-0003", "no_time"), ("S-0006", "unaligned_thread"), ("S-0007", "unassigned")]


def test_空洞_after优先_都没有就进未定位_同锚点保持缺口顺序():
    seq, _ = build_sequence(_mini(), {}, set())
    gaps = [
        {"id": "Q-001", "thread": "L-001", "after": "S-0001", "before": "S-0002", "event": "甲", "mentioned_in": []},
        {"id": "Q-002", "thread": "L-001", "after": None, "before": "S-0002", "event": "乙", "mentioned_in": ["S-0001"]},
        {"id": "Q-003", "thread": "L-001", "after": "S-0001", "before": None, "event": "丙", "mentioned_in": []},
        {"id": "Q-004", "thread": None, "after": "S-0099", "before": None, "event": "丁", "mentioned_in": []},
    ]
    items, un = insert_holes(seq, gaps, {})
    assert [(i["type"], i.get("gap") or i["id"]) for i in items] == [
        ("scene", "S-0001"), ("hole", "Q-001"), ("hole", "Q-003"), ("scene", "S-0004"),
        ("hole", "Q-002"), ("scene", "S-0002"), ("scene", "S-0005")]
    assert [(h["gap"], h["why"]) for h in un] == [("Q-004", "no_anchor")]
    assert items[1]["event"] == "甲" and items[4]["mentioned_in"] == ["S-0001"]


def test_章节备注():
    th = _mini()
    items = [{"type": "scene", "id": "S-0002", "thread": "L-001"},
             {"type": "scene", "id": "S-0004", "thread": "L-002"},
             {"type": "hole", "id": "H-001", "thread": "L-001"}]
    cols = {"L-001": {"col": "keep", "merge_into": None}, "L-002": {"col": "merge", "merge_into": "L-001"}}
    assert notes_for(items, cols, th) == [{"kind": "merge", "thread": "L-002", "into": "L-001"}]
    cols["L-002"] = {"col": "cut", "merge_into": None}
    assert notes_for(items[:1], cols, th) == [{"kind": "cut_crossing", "thread": "L-002", "scene": "S-0002"}]
    assert notes_for(items[:1], {}, th) == [{"kind": "undecided", "thread": "L-001"}]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest -q tests/test_skeleton_order.py`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现** `src/ligaotai/skeleton_order.py`

```python
"""骨架的排序部分（纯函数，不读文件、不调模型）——计划④ spec 第 7.2 节。

全局时间 = 线 offset + times[sid].t，跟前端 lib/segments.ts 同一规则：offset 为 null 的线
（没对齐主线）和 t 为 null / 缺键的场景都放不进时间轴，进「未定位」，不当 0。
同一时刻：主线优先，再按线编号，再按线内原顺序。
cols：{线编号: {"col", "merge_into"}}（triage.columns 的返回值）；缺的线当「还没想好」。
"""

from __future__ import annotations

from .fsutil import natural_key

UNDECIDED = {"col": "undecided", "merge_into": None}


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _col(cols: dict, tid) -> dict:
    return cols.get(tid) or UNDECIDED


def build_sequence(threads: dict, cols: dict, drop: set[str]) -> tuple[list[dict], list[dict]]:
    """参与的线的场景按全局时间排好。返回 (排好的场景条目, 排不进时间轴的场景)。
    drop：不参与的场景（版本组里的非主版本、已移除的块）。"""
    main = threads.get("main_thread")
    placed, unplaced = [], []
    for t in threads.get("threads") or []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        tid = t["id"]
        if _col(cols, tid)["col"] == "cut":
            continue
        off = t.get("offset")
        times = t.get("times") or {}
        for i, sid in enumerate(t.get("scenes") or []):
            if sid in drop:
                continue
            if not _num(off):
                unplaced.append({"id": sid, "thread": tid, "why": "unaligned_thread"})
                continue
            tm = times.get(sid)
            tv = tm.get("t") if isinstance(tm, dict) else None
            if not _num(tv):
                unplaced.append({"id": sid, "thread": tid, "why": "no_time"})
                continue
            key = (off + tv, 0 if tid == main else 1, natural_key(tid), i)
            placed.append((key, {"type": "scene", "id": sid, "thread": tid}))
    for u in threads.get("unassigned") or []:
        sid = u.get("scene") if isinstance(u, dict) else u
        if isinstance(sid, str) and sid not in drop:
            unplaced.append({"id": sid, "thread": None, "why": "unassigned"})
    placed.sort(key=lambda p: p[0])
    return [p[1] for p in placed], unplaced


def _hole(g: dict) -> dict:
    return {"type": "hole", "id": "", "gap": g.get("id"), "thread": g.get("thread"),
            "after": g.get("after"), "before": g.get("before"), "event": str(g.get("event") or ""),
            "mentioned_in": [m for m in g.get("mentioned_in") or [] if isinstance(m, str)]}


def insert_holes(seq: list[dict], gaps: list, cols: dict) -> tuple[list[dict], list[dict]]:
    """缺口按锚点插成空洞：after 在序列里就插在它后面，否则 before 在就插在它前面，都不在进未定位。
    只属于被砍的线的缺口不插。空洞编号 H-001… 按最终顺序（先序列里的，再未定位的）。"""
    pos = {it["id"] for it in seq}
    after_map: dict[str, list[dict]] = {}
    before_map: dict[str, list[dict]] = {}
    unplaced: list[dict] = []
    for g in gaps or []:
        if not isinstance(g, dict):
            continue
        if g.get("thread") and _col(cols, g["thread"])["col"] == "cut":
            continue
        h = _hole(g)
        if g.get("after") in pos:
            after_map.setdefault(g["after"], []).append(h)
        elif g.get("before") in pos:
            before_map.setdefault(g["before"], []).append(h)
        else:
            unplaced.append({**h, "why": "no_anchor"})
    out: list[dict] = []
    for it in seq:
        out.extend(before_map.get(it["id"], []))
        out.append(it)
        out.extend(after_map.get(it["id"], []))
    n = 0
    for it in out + unplaced:
        if it["type"] == "hole":
            n += 1
            it["id"] = f"H-{n:03d}"
    return out, unplaced


def notes_for(items: list[dict], cols: dict, threads: dict) -> list[dict]:
    """一章的备注：去留未定的线、待并入改写的线、跟被砍线的交汇点。去重、保持出现顺序。"""
    cut_x: dict[str, list[str]] = {}
    for x in threads.get("intersections") or []:
        if isinstance(x, dict) and x.get("thread") and _col(cols, x["thread"])["col"] == "cut":
            cut_x.setdefault(x.get("main_scene"), []).append(x["thread"])
    notes: list[dict] = []
    for it in items:
        if it.get("type") != "scene":
            continue
        c = _col(cols, it.get("thread"))
        if it.get("thread"):
            if c["col"] == "undecided":
                n = {"kind": "undecided", "thread": it["thread"]}
            elif c["col"] == "merge":
                n = {"kind": "merge", "thread": it["thread"], "into": c["merge_into"]}
            else:
                n = None
            if n and n not in notes:
                notes.append(n)
        for ct in cut_x.get(it["id"], []):
            n = {"kind": "cut_crossing", "thread": ct, "scene": it["id"]}
            if n not in notes:
                notes.append(n)
    return notes
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q tests/test_skeleton_order.py`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/skeleton_order.py tests/test_skeleton_order.py
git commit -m "feat: 骨架排序：全局时间交织、空洞插入、章节备注"
```

### Task 10: chapters.py——分章的输入、核对、兜底、窗口、组装（纯函数）

**Files:**
- Create: `src/ligaotai/chapters.py`
- Test: `tests/test_chapters.py`

模型只回卷 / 章的**起点序号**和名字：`{"volumes": [{"title", "start"}], "chapters": [{"title", "start"}]}`，序号是这一窗口里的行号（从 0 开始）。

- [ ] **Step 1: 写失败的测试** `tests/test_chapters.py`

```python
from ligaotai.chapters import (
    assemble,
    check_chapters,
    fallback_chapters,
    merge_windows,
    render_rows,
    windows,
)


def _scene(sid, thread="L-001"):
    return {"type": "scene", "id": sid, "thread": thread}


def test_渲染行_场景和空洞_序号从0开始():
    items = [_scene("S-0001"), {"type": "hole", "id": "H-001", "thread": "L-001", "event": "大闹\n天宫"}]
    info = {"S-0001": {"chars": 1200, "summary": "开篇\n两行"}}
    assert render_rows(items, info) == ["0｜S-0001｜L-001｜1200｜开篇 两行", "1｜空洞｜L-001｜0｜大闹 天宫"]


def test_核对分章():
    ok = {"volumes": [{"title": "卷一", "start": 0}], "chapters": [{"title": "甲", "start": 0}, {"title": "乙", "start": 3}]}
    assert check_chapters(ok, 5) == []
    cases = [
        ({"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "甲", "start": 1}]}, "0"),
        ({"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "甲", "start": 0}, {"title": "乙", "start": 0}]}, "递增"),
        ({"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "甲", "start": 0}, {"title": "乙", "start": 9}]}, "0 到 4"),
        ({"volumes": [{"title": "卷", "start": 0}, {"title": "卷二", "start": 2}], "chapters": [{"title": "甲", "start": 0}, {"title": "乙", "start": 3}]}, "卷的起点"),
        ({"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "", "start": 0}]}, "标题"),
        ({"chapters": [{"title": "甲", "start": 0}]}, "volumes"),
        ({"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "甲", "start": "0"}]}, "整数"),
    ]
    for data, word in cases:
        assert any(word in p for p in check_chapters(data, 5)), (data, check_chapters(data, 5))


def test_兜底切法_每章约一万字_每卷若干章():
    items = [_scene(f"S-000{i}") for i in range(1, 6)]
    info = {f"S-000{i}": {"chars": 6000, "summary": f"第{i}块的摘要很长很长很长"} for i in range(1, 6)}
    d = fallback_chapters(items, info)
    assert [c["start"] for c in d["chapters"]] == [0, 2, 4]
    assert d["chapters"][0]["title"] == "第1块的摘要很长很长很长"[:12]
    assert d["volumes"] == [{"title": "第1卷", "start": 0}]
    d2 = fallback_chapters(items, info, per_volume=2)
    assert [v["start"] for v in d2["volumes"]] == [0, 4]
    assert check_chapters(d, 5) == []


def test_兜底切法_空洞当章首_空列表():
    items = [{"type": "hole", "id": "H-001", "event": "x"}]
    assert fallback_chapters(items, {})["chapters"] == [{"title": "空洞", "start": 0}]
    assert fallback_chapters([], {}) == {"volumes": [], "chapters": []}


def test_窗口切分_相邻窗口重叠():
    rows = ["x" * 9] * 25          # 每行 9 字 + 换行 = 10
    assert windows(rows, 100, overlap=3) == [(0, 10), (7, 17), (14, 24), (21, 25)]
    assert windows(rows, 10_000, overlap=3) == [(0, 25)]
    assert windows([], 100) == []
    assert windows(["x" * 500] * 5, 100, overlap=2) == [(0, 3), (1, 4), (2, 5)]  # 单行超预算也要往前走


def test_合并窗口_重叠区按中点切_卷起点对齐到章起点():
    results = [
        (0, 12, {"chapters": [{"title": "a", "start": 0}, {"title": "b", "start": 6}, {"title": "c", "start": 11}],
                 "volumes": [{"title": "v1", "start": 0}]}),
        (8, 20, {"chapters": [{"title": "x", "start": 0}, {"title": "y", "start": 3}, {"title": "z", "start": 8}],
                 "volumes": [{"title": "v2", "start": 0}, {"title": "v3", "start": 3}]}),
    ]
    d = merge_windows(results, 20, overlap=4)
    assert [(c["title"], c["start"]) for c in d["chapters"]] == [("a", 0), ("b", 6), ("y", 11), ("z", 16)]
    assert [(v["title"], v["start"]) for v in d["volumes"]] == [("v1", 0), ("v3", 11)]
    assert check_chapters(d, 20) == []


def test_组装成卷章():
    items = [_scene(f"S-000{i}") for i in range(1, 6)]
    d = {"volumes": [{"title": "上", "start": 0}, {"title": "下", "start": 3}],
         "chapters": [{"title": "一", "start": 0}, {"title": "二", "start": 2}, {"title": "三", "start": 3}]}
    vols = assemble(items, d)
    assert [v["title"] for v in vols] == ["上", "下"]
    assert [[c["title"] for c in v["chapters"]] for v in vols] == [["一", "二"], ["三"]]
    assert [i["id"] for i in vols[0]["chapters"][1]["items"]] == ["S-0003"]
    assert [i["id"] for i in vols[1]["chapters"][0]["items"]] == ["S-0004", "S-0005"]
    assert vols[0]["chapters"][0]["notes"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest -q tests/test_chapters.py`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现** `src/ligaotai/chapters.py`

```python
"""骨架的分章部分（纯函数）——计划④ spec 第 7.3 节。

模型只回卷 / 章的起点序号和名字，程序核对：起点从 0 开始、严格递增、不越界、卷起点也是章起点。
大书按窗口分批（相邻窗口重叠 OVERLAP 行做衔接），合并时重叠区按中点切，各取一半。
模型怎么都不合规就用兜底切法：每章约 1 万字、每卷 10 章，章名用首块摘要前 12 字。
"""

from __future__ import annotations

OVERLAP = 10
PER_CHAPTER = 10000
PER_VOLUME = 10


def _one_line(s) -> str:
    return " ".join(str(s or "").split())


def render_rows(items: list[dict], info: dict) -> list[str]:
    rows = []
    for i, it in enumerate(items):
        if it["type"] == "scene":
            x = info.get(it["id"]) or {}
            rows.append(f"{i}｜{it['id']}｜{it.get('thread') or ''}｜{x.get('chars', 0)}｜{_one_line(x.get('summary'))}")
        else:
            rows.append(f"{i}｜空洞｜{it.get('thread') or ''}｜0｜{_one_line(it.get('event'))}")
    return rows


def _starts(lst, what: str) -> tuple[list[int], list[str]]:
    if not isinstance(lst, list) or not lst:
        return [], [f"要有非空的 {what} 列表"]
    starts, problems = [], []
    for x in lst:
        st = x.get("start") if isinstance(x, dict) else None
        if not isinstance(st, int) or isinstance(st, bool):
            problems.append(f"{what} 里每一项都要有整数 start")
            continue
        if not str(x.get("title") or "").strip():
            problems.append(f"{what} 里第 {st} 行开始的那一项没有标题")
        starts.append(st)
    return starts, problems


def check_chapters(data, n: int) -> list[str]:
    if not isinstance(data, dict):
        return ['要输出 {"volumes": [...], "chapters": [...]}']
    cs, p1 = _starts(data.get("chapters"), "chapters")
    vs, p2 = _starts(data.get("volumes"), "volumes")
    problems = p1 + p2
    for what, st in (("chapters", cs), ("volumes", vs)):
        if not st:
            continue
        if st[0] != 0:
            problems.append(f"{what} 第一项的 start 必须是 0")
        if any(b <= a for a, b in zip(st, st[1:])):
            problems.append(f"{what} 的 start 要严格递增，不许重复或倒序")
        if any(x < 0 or x >= n for x in st):
            problems.append(f"{what} 的 start 要在 0 到 {n - 1} 之间")
    miss = [v for v in vs if v not in set(cs)]
    if cs and miss:
        problems.append("卷的起点必须也是某一章的起点：" + "、".join(map(str, miss)))
    return problems


def _auto_title(it: dict, info: dict) -> str:
    if it["type"] != "scene":
        return "空洞"
    return _one_line((info.get(it["id"]) or {}).get("summary"))[:12] or it["id"]


def fallback_chapters(items: list[dict], info: dict, per_chapter: int = PER_CHAPTER,
                      per_volume: int = PER_VOLUME) -> dict:
    chapters, acc = [], 0
    for i, it in enumerate(items):
        if i == 0 or acc >= per_chapter:
            chapters.append({"title": _auto_title(it, info), "start": i})
            acc = 0
        if it["type"] == "scene":
            acc += (info.get(it["id"]) or {}).get("chars", 0)
    volumes = [{"title": f"第{k // per_volume + 1}卷", "start": chapters[k]["start"]}
               for k in range(0, len(chapters), per_volume)]
    return {"volumes": volumes, "chapters": chapters}


def windows(rows: list[str], budget: int, overlap: int = OVERLAP) -> list[tuple[int, int]]:
    """按字数预算切窗口 [start, end)。每个窗口至少比重叠多一行，保证一定往前走。"""
    n = len(rows)
    out: list[tuple[int, int]] = []
    s = 0
    while n:
        e, size = s, 0
        while e < n and (e == s or size + len(rows[e]) + 1 <= budget):
            size += len(rows[e]) + 1
            e += 1
        if e < n and e - s <= overlap:
            e = min(n, s + overlap + 1)
        out.append((s, e))
        if e >= n:
            break
        s = e - overlap
    return out


def merge_windows(results: list[tuple[int, int, dict]], n: int, overlap: int = OVERLAP) -> dict:
    """results：[(窗口起点, 窗口终点, 模型结果)]，结果里的 start 是窗口内行号。"""
    cuts = [0] + [s + overlap // 2 for s, _, _ in results[1:]] + [n]
    merged: dict[str, list] = {"chapters": [], "volumes": []}
    for k, (s, _, d) in enumerate(results):
        lo, hi = cuts[k], cuts[k + 1]
        for key in ("chapters", "volumes"):
            for x in d.get(key) or []:
                g = s + x["start"]
                if lo <= g < hi:
                    merged[key].append({"title": x["title"], "start": g})
    cs = [c["start"] for c in merged["chapters"]]
    vols: list[dict] = []
    for v in merged["volumes"]:
        nxt = next((c for c in cs if c >= v["start"]), None)
        if nxt is not None and (not vols or nxt > vols[-1]["start"]):
            vols.append({"title": v["title"], "start": nxt})
    return {"volumes": vols, "chapters": merged["chapters"]}


def assemble(items: list[dict], data: dict) -> list[dict]:
    cs, n = data["chapters"], len(items)
    vol_title = {v["start"]: v["title"] for v in data["volumes"]}
    vols: list[dict] = []
    for i, c in enumerate(cs):
        s = c["start"]
        e = cs[i + 1]["start"] if i + 1 < len(cs) else n
        if s in vol_title or not vols:
            vols.append({"title": vol_title.get(s, "第1卷"), "chapters": []})
        vols[-1]["chapters"].append({"title": c["title"], "items": [dict(it) for it in items[s:e]], "notes": []})
    return vols
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q tests/test_chapters.py`
Expected: PASS。`windows(["x"*500]*5, 100, overlap=2)` 这条是「单行就超预算」的边界：每窗口强制 3 行（重叠 2 + 1）才能往前走——实现若算出别的，先手推一遍再决定谁错。

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/chapters.py tests/test_chapters.py
git commit -m "feat: 骨架分章：核对、兜底切法、窗口切分与合并、组装"
```

### Task 11: skeleton.py——生成骨架（模型分章 + 空洞说明）

**Files:**
- Create: `src/ligaotai/skeleton.py`、`prompts/skeleton_chapters.md`、`prompts/skeleton_holes.md`
- Test: `tests/test_skeleton.py`

- [ ] **Step 1: 写提示词**

`prompts/skeleton_chapters.md`：

```markdown
成书骨架的分卷分章：程序已经排好了顺序，模型只切卷切章、起名。只回起点序号，不许改顺序。

## system
你在给一部长篇小说分卷分章。下面每一行是按故事顺序排好的一块：「序号｜编号｜所属线｜字数｜摘要」，「空洞」是还没写的部分。
**顺序已经定了，不许调整**，你只决定：从哪一行开始新的一章、从哪一行开始新的一卷，并给每卷每章起名。

要求：
- 一章大约 5000～15000 字（空洞算 0 字），在情节自然的转折处断开；
- 一卷由若干章组成，在大的段落转折处断开；
- 第一章、第一卷都从第 0 行开始；每一卷的起点必须也是某一章的起点；
- 章名、卷名用中文，简短，概括这一段的内容。

只输出 JSON：
{"volumes": [{"title": "第一卷 ……", "start": 0}], "chapters": [{"title": "……", "start": 0}, {"title": "……", "start": 7}]}
start 是行首的序号。

## user
共 $n 行：
$rows
```

`prompts/skeleton_holes.md`：

```markdown
成书骨架的空洞说明：每个空洞写一段补写任务说明，三期补写直接用。说明里的每个结论要带场景编号。

## system
成书骨架里有一些「空洞」：故事需要、但原稿里没写的部分。请给每个空洞写一段补写任务说明（两三句话）：
在哪两块之间、要写什么、原稿里哪些地方提到过这件事。
每句话都要带场景编号，写法 [S-0003]，**只能用这个空洞下面列出的编号**。

只输出 JSON：
{"holes": [{"id": "H-001", "task": "……[S-0003]……"}]}
每个空洞都要写，且只写一次。

## user
$holes
```

- [ ] **Step 2: 写失败的测试** `tests/test_skeleton.py`

```python
import json
import re

import pytest
from helpers import FakeBackend

from ligaotai.config import AppConfig
from ligaotai.fsutil import read_json, write_json
from ligaotai.llm import LLMClient
from ligaotai.skeleton import check_holes, fallback_task, generate
from ligaotai.threads_ops import load_threads
from ligaotai.triage import set_card

_HID = re.compile(r"^### (H-\d{3})$", re.M)
_SID = re.compile(r"S-\d{4}")


def _handler(chapters=None, holes_ok=True, on_call=None):
    def h(tier, messages):
        system, user = messages[0]["content"], messages[1]["content"]
        if on_call:
            on_call()
        if "分卷分章" in system:
            return json.dumps(chapters or {"volumes": [{"title": "卷一", "start": 0}],
                                           "chapters": [{"title": "开篇", "start": 0}, {"title": "龙宫", "start": 3}]},
                              ensure_ascii=False)
        if "补写任务说明" in system:
            if not holes_ok:
                return json.dumps({"holes": []})
            out = []
            for block in user.split("\n\n"):
                m = _HID.search(block)
                sid = _SID.search(block.split("\n", 1)[1]).group(0)
                out.append({"id": m.group(1), "task": f"补上这件事 [{sid}]"})
            return json.dumps({"holes": out}, ensure_ascii=False)
        raise AssertionError("没见过的提示词")
    return h


def _client(b, handler):
    backend = FakeBackend(handler=handler)
    return LLMClient(AppConfig(), backend, log_dir=b.logs_dir), backend


def _ids(ch):
    return [i["id"] for i in ch["items"]]


def test_生成骨架_顺序_分章_空洞说明_备注(book_with_threads):
    b = book_with_threads
    client, _ = _client(b, _handler())
    r = generate(b, client)
    assert r["written"] is True and r["fallback_chapters"] is False
    sk = read_json(b.skeleton_path)
    assert sk["by"] == "program"
    [vol] = sk["volumes"]
    assert vol["title"] == "卷一"
    assert [c["title"] for c in vol["chapters"]] == ["开篇", "龙宫"]
    assert _ids(vol["chapters"][0]) == ["S-0001", "H-001", "S-0002"]
    assert _ids(vol["chapters"][1]) == ["S-0003", "S-0004", "S-0005"]
    hole = vol["chapters"][0]["items"][1]
    assert hole["gap"] == "Q-001" and hole["task"].startswith("补上这件事 [S-")
    assert vol["chapters"][0]["notes"] == [{"kind": "undecided", "thread": "L-001"}]
    assert vol["chapters"][1]["notes"] == [{"kind": "undecided", "thread": "L-001"},
                                           {"kind": "undecided", "thread": "L-002"}]
    assert sk["unplaced"] == {"scenes": [], "holes": []}


def test_砍掉的线不进骨架_交汇处挂备注(book_with_threads):
    b = book_with_threads
    data = read_json(b.threads_path)
    data["intersections"] = [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "r"}]
    write_json(b.threads_path, data)
    th = load_threads(b)
    set_card(b, th, "L-001", "keep")
    set_card(b, th, "L-002", "cut")
    client, _ = _client(b, _handler(chapters={"volumes": [{"title": "卷一", "start": 0}],
                                              "chapters": [{"title": "全", "start": 0}]}))
    generate(b, client)
    [ch] = read_json(b.skeleton_path)["volumes"][0]["chapters"]
    assert _ids(ch) == ["S-0001", "H-001", "S-0002", "S-0003"]
    assert ch["notes"] == [{"kind": "cut_crossing", "thread": "L-002", "scene": "S-0002"}]


def test_分章一直不合规_用兜底切法(book_with_threads):
    b = book_with_threads
    bad = {"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "甲", "start": 3}]}
    client, _ = _client(b, _handler(chapters=bad))
    r = generate(b, client)
    assert r["fallback_chapters"] is True
    [vol] = read_json(b.skeleton_path)["volumes"]
    assert vol["title"] == "第1卷"
    assert [c["title"] for c in vol["chapters"]] == ["S-0001 摘要"]    # seed_book 的摘要默认是「S-000x 摘要」


def test_空洞说明模型失败_用程序拼的说明(book_with_threads):
    b = book_with_threads
    client, _ = _client(b, _handler(holes_ok=False))
    generate(b, client)
    hole = read_json(b.skeleton_path)["volumes"][0]["chapters"][0]["items"][1]
    assert hole["task"] == "在 S-0001 与 S-0003 之间补写：大闹天宫；原稿提到于 S-0002"


def test_重新生成先备份旧骨架(book_with_threads):
    b = book_with_threads
    client, _ = _client(b, _handler())
    generate(b, client)
    first = read_json(b.skeleton_path)
    generate(b, client)
    assert read_json(b.skeleton_bak_path) == first


def test_跑的途中看板被改_不写入(book_with_threads):
    b = book_with_threads
    state = {"n": 0}

    def touch():
        state["n"] += 1
        if state["n"] == 1:
            write_json(b.board_path, {"cards": {"L-002": {"col": "cut", "merge_into": None, "note": ""}}})

    client, _ = _client(b, _handler(on_call=touch))
    r = generate(b, client)
    assert r["written"] is False and r["input_changed"] is True
    assert not b.skeleton_path.exists()


def test_空洞说明核对():
    expect = {"H-001": {"S-0001", "S-0003"}, "H-002": {"S-0005"}}
    ok = {"holes": [{"id": "H-001", "task": "补 [S-0001]"}, {"id": "H-002", "task": "补 [S-0005]"}]}
    assert check_holes(ok, expect) == []
    bad = {"holes": [{"id": "H-001", "task": "补 [S-0005]"}, {"id": "H-001", "task": "没编号"}, {"id": "H-009", "task": "x"}]}
    text = "\n".join(check_holes(bad, expect))
    for word in ["S-0005", "重复", "H-009", "H-002", "场景编号"]:
        assert word in text


def test_兜底说明_没有锚点和出处也能写():
    assert fallback_task({"after": None, "before": None, "event": "某事", "mentioned_in": []}) == \
        "在 （开头） 与 （结尾） 之间补写：某事"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest -q tests/test_skeleton.py`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 4: 实现** `src/ligaotai/skeleton.py`（本 Task 只写生成部分；Task 12 在同一文件加编辑 / 校验 / 对账）

```python
"""成书骨架（计划④ spec 第 7 节）：程序排顺序，模型只分卷分章、起名、写空洞说明。

生成前后各算一次输入指纹（世界与支线.json、看板.json、版本组.json 的原文），
跑的途中变了就不写入（沿用步骤 6 input_changed 的做法）。重新生成前把旧骨架备份成 骨架.bak.json。
"""

from __future__ import annotations

import asyncio
import shutil

from .archive import _digest, refs_in
from .book import FILE_LOCK, Book, now_iso
from .cards import load_cards
from .chapters import assemble, check_chapters, fallback_chapters, merge_windows, render_rows, windows
from .fsutil import write_json
from .llm import LLMClient
from .llm_caller import Caller, Progress, _noop
from .scenes import load_scenes
from .skeleton_order import build_sequence, insert_holes, notes_for
from .threads_ops import load_threads
from .triage import columns, non_main_versions

PROMPT_CHAPTERS = "skeleton_chapters"
PROMPT_HOLES = "skeleton_holes"
HOLE_BATCH = 20


def scene_info(book: Book) -> dict[str, dict]:
    cards = load_cards(book)
    out = {}
    for s in load_scenes(book):
        rec = cards.get(s.id) or {}
        card = rec.get("card") if isinstance(rec.get("card"), dict) else {}
        out[s.id] = {"chars": s.chars, "summary": str(card.get("summary") or s.heading or ""), "removed": s.removed}
    return out


def input_fingerprint(book: Book) -> str:
    parts = [p.read_text(encoding="utf-8") if p.exists() else ""
             for p in (book.threads_path, book.board_path, book.versions_path)]
    return _digest(*parts)


def hole_allowed(h: dict) -> set[str]:
    return {x for x in [h.get("after"), h.get("before"), *(h.get("mentioned_in") or [])] if x}


def hole_block(h: dict, info: dict) -> str:
    def line(label, sid):
        return f"{label} {sid}：{(info.get(sid) or {}).get('summary', '')}"

    lines = [f"### {h['id']}", f"缺的事：{h.get('event', '')}"]
    if h.get("after"):
        lines.append(line("前一块", h["after"]))
    if h.get("before"):
        lines.append(line("后一块", h["before"]))
    for m in h.get("mentioned_in") or []:
        lines.append(line("提到它的场景", m))
    return "\n".join(lines)


def check_holes(data, expect: dict[str, set[str]]) -> list[str]:
    lst = data.get("holes") if isinstance(data, dict) else None
    if not isinstance(lst, list):
        return ['要输出 {"holes": [...]}']
    problems, seen = [], []
    for x in lst:
        if not isinstance(x, dict):
            problems.append("holes 里每一项都要是对象")
            continue
        hid = x.get("id")
        if hid not in expect:
            problems.append(f"没有这个空洞：{hid}")
            continue
        if hid in seen:
            problems.append(f"{hid} 重复了，每个空洞只写一次")
        seen.append(hid)
        task = str(x.get("task") or "").strip()
        refs = refs_in(task)
        if not refs:
            problems.append(f"{hid} 的说明没带场景编号")
        bad = sorted({r for r in refs if r not in expect[hid]})
        if bad:
            problems.append(f"{hid} 的说明用了不属于它的编号：" + "、".join(bad))
    missing = [h for h in expect if h not in seen]
    if missing:
        problems.append("这几个空洞没写说明：" + "、".join(missing))
    return problems


def fallback_task(h: dict) -> str:
    text = f"在 {h.get('after') or '（开头）'} 与 {h.get('before') or '（结尾）'} 之间补写：{h.get('event', '')}"
    m = h.get("mentioned_in") or []
    return text + (f"；原稿提到于 {'、'.join(m)}" if m else "")


def generate(book: Book, client: LLMClient, progress: Progress = _noop) -> dict:
    return asyncio.run(_generate(book, client, progress))


async def _generate(book: Book, client: LLMClient, progress: Progress) -> dict:
    fp0 = input_fingerprint(book)
    threads = load_threads(book)
    cols = columns(book, threads)
    info = scene_info(book)
    drop = non_main_versions(book) | {sid for sid, x in info.items() if x["removed"]}
    seq, unplaced_scenes = build_sequence(threads, cols, drop)
    items, unplaced_holes = insert_holes(seq, threads.get("gaps") or [], cols)

    caller = Caller(book, client, progress, cache_path=book.triage_cache_path, tag_prefix="skeleton")
    wins = windows(render_rows(items, info), book.settings()["skeleton_max_input_tokens"])
    holes = [it for it in items if it["type"] == "hole"] + unplaced_holes
    ask = [h for h in holes if hole_allowed(h)]
    batches = [ask[i:i + HOLE_BATCH] for i in range(0, len(ask), HOLE_BATCH)]
    caller.plan(len(wins) + len(batches))

    # 分卷分章：任何一个窗口失败，整本用兜底切法（不拼半截模型结果）
    results, ok = [], bool(items)
    for s, e in wins:
        n = e - s

        def check(d, n=n):
            return check_chapters(d, n)

        d = await caller.call(PROMPT_CHAPTERS, {"n": str(n), "rows": "\n".join(render_rows(items[s:e], info))},
                              check, f"chapters/{s}", usable=lambda d, n=n: not check_chapters(d, n))
        if d is None:
            ok = False
            break
        results.append((s, e, d))
    chapters = None
    if ok and results:
        chapters = results[0][2] if len(results) == 1 else merge_windows(results, len(items))
        if check_chapters(chapters, len(items)):
            chapters = None
    used_fallback = chapters is None and bool(items)
    if chapters is None:
        chapters = fallback_chapters(items, info)

    # 空洞说明：一批 HOLE_BATCH 个；失败的空洞用程序拼的说明
    tasks: dict[str, str] = {}
    for k, batch in enumerate(batches):
        expect = {h["id"]: hole_allowed(h) for h in batch}
        text = "\n\n".join(hole_block(h, info) for h in batch)
        d = await caller.call(PROMPT_HOLES, {"holes": text}, lambda d, ex=expect: check_holes(d, ex),
                              f"holes/{k}", usable=lambda d, ex=expect: not check_holes(d, ex))
        if d is not None:
            tasks.update({x["id"]: x["task"] for x in d["holes"]})
    for h in holes:
        h["task"] = tasks.get(h["id"]) or fallback_task(h)

    vols = assemble(items, chapters) if items else []
    for v in vols:
        for ch in v["chapters"]:
            ch["notes"] = notes_for(ch["items"], cols, threads)
    sk = {"generated": now_iso(), "by": "program", "fallback_chapters": used_fallback, "volumes": vols,
          "unplaced": {"scenes": unplaced_scenes, "holes": unplaced_holes}}

    if input_fingerprint(book) != fp0:
        return {"written": False, "input_changed": True, "failed": caller.failed}
    with FILE_LOCK:
        if book.skeleton_path.exists():
            shutil.copyfile(book.skeleton_path, book.skeleton_bak_path)
        write_json(book.skeleton_path, sk)
    return {"written": True, "input_changed": False, "volumes": len(vols),
            "chapters": sum(len(v["chapters"]) for v in vols), "holes": len(holes),
            "unplaced_scenes": len(unplaced_scenes), "fallback_chapters": used_fallback,
            "failed": caller.failed}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest -q tests/test_skeleton.py`
Expected: PASS。注意 `test_分章一直不合规…` 的假模型每次都回同一个坏结果，`chat_json` 会重试 `MAX_ATTEMPTS` 次；`usable` 让 Caller 丢掉这条缓存。

- [ ] **Step 6: 提交**

```bash
git add src/ligaotai/skeleton.py prompts/skeleton_chapters.md prompts/skeleton_holes.md tests/test_skeleton.py
git commit -m "feat: 生成成书骨架：程序排序 + 模型分章起名 + 空洞说明"
```

### Task 12: skeleton.py——读、保存编辑、校验、对账标注

**Files:**
- Modify: `src/ligaotai/skeleton.py`
- Test: `tests/test_skeleton.py`（追加）

- [ ] **Step 1: 写失败的测试**（追加）

```python
from ligaotai.skeleton import BrokenSkeletonFile, annotate, load_skeleton, save_skeleton


def _sk(items, unplaced=None):
    return {"generated": "x", "by": "program", "volumes": [{"title": "卷一", "chapters": [
        {"title": "章一", "items": items, "notes": []}]}],
            "unplaced": unplaced or {"scenes": [], "holes": []}}


def test_保存编辑_标成作者改过(book_with_threads):
    b = book_with_threads
    sk = save_skeleton(b, _sk([{"type": "scene", "id": "S-0001", "thread": "L-001"},
                               {"type": "hole", "id": "H-009", "task": "作者自己加的空洞"}]))
    assert sk["by"] == "author" and read_json(b.skeleton_path)["by"] == "author"


def test_保存编辑_校验(book_with_threads):
    b = book_with_threads
    cases = [
        (_sk([{"type": "scene", "id": "S-0099"}]), "S-0099"),
        (_sk([{"type": "scene", "id": "S-0001"}, {"type": "scene", "id": "S-0001"}]), "不止一次"),
        (_sk([{"type": "scene", "id": "S-0001"}], {"scenes": [{"id": "S-0001", "why": "no_time"}], "holes": []}), "不止一次"),
        (_sk([{"type": "hole", "id": "H-001"}]), "任务说明"),
        (_sk([{"type": "hole", "id": "H-001", "task": "a"}, {"type": "hole", "id": "H-001", "task": "b"}]), "H-001"),
        (_sk([{"type": "note", "id": "x"}]), "scene 或 hole"),
        ({"volumes": [{"title": "", "chapters": []}]}, "标题"),
        ({"volumes": "x"}, "volumes"),
    ]
    for sk, word in cases:
        with pytest.raises(ValueError) as e:
            save_skeleton(b, sk)
        assert word in str(e.value), (sk, str(e.value))


def test_保存时去掉界面标注(book_with_threads):
    b = book_with_threads
    save_skeleton(b, _sk([{"type": "scene", "id": "S-0001", "thread": "L-001", "flag": "cut"}]))
    item = read_json(b.skeleton_path)["volumes"][0]["chapters"][0]["items"][0]
    assert "flag" not in item


def test_读骨架_没有和坏了(book_with_threads):
    b = book_with_threads
    with pytest.raises(FileNotFoundError):
        load_skeleton(b)
    b.triage_dir.mkdir(parents=True, exist_ok=True)
    b.skeleton_path.write_text("{坏", encoding="utf-8")
    with pytest.raises(BrokenSkeletonFile):
        load_skeleton(b)


def test_对账标注_场景没了或线被砍(book_with_threads):
    b = book_with_threads
    th = load_threads(b)
    set_card(b, th, "L-002", "cut")
    sk = _sk([{"type": "scene", "id": "S-0001", "thread": "L-001"},
              {"type": "scene", "id": "S-0004", "thread": "L-002"},
              {"type": "scene", "id": "S-0099", "thread": "L-001"}],
             {"scenes": [{"id": "S-0005", "thread": "L-002", "why": "no_time"}], "holes": []})
    out = annotate(b, sk, th)
    flags = [i.get("flag") for i in out["volumes"][0]["chapters"][0]["items"]]
    assert flags == [None, "cut", "missing"]
    assert out["unplaced"]["scenes"][0]["flag"] == "cut"
    assert "flag" not in sk["volumes"][0]["chapters"][0]["items"][1]   # 不改原对象
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest -q tests/test_skeleton.py`
Expected: 新测试 FAIL（`ImportError`）

- [ ] **Step 3: 实现**（追加到 `src/ligaotai/skeleton.py`；顶部 import 加 `import copy`，`from .fsutil import read_json, write_json`）

```python
# ---------------------------------------------------------------------------
# 读、保存编辑、校验、对账标注
# ---------------------------------------------------------------------------


class BrokenSkeletonFile(ValueError):
    """骨架.json 坏了。作者改过的骨架不能当空处理。"""


def load_skeleton(book: Book) -> dict:
    try:
        data = read_json(book.skeleton_path)
    except ValueError as e:
        raise BrokenSkeletonFile(f"取舍/骨架.json 不是合法 JSON：{e}") from e
    if data is None:
        raise FileNotFoundError("还没有骨架，先生成一次")
    if not isinstance(data, dict) or not isinstance(data.get("volumes"), list):
        raise BrokenSkeletonFile("取舍/骨架.json 没有 volumes 列表")
    return data


def validate_skeleton(sk, known: set[str]) -> list[str]:
    if not isinstance(sk, dict) or not isinstance(sk.get("volumes"), list):
        return ["骨架要有 volumes 列表"]
    problems: list[str] = []
    seen_s: set[str] = set()
    seen_h: set[str] = set()

    def item(it, where: str) -> None:
        if not isinstance(it, dict):
            problems.append(f"{where}：条目要是对象")
            return
        if it.get("type") == "scene":
            sid = it.get("id")
            if sid not in known:
                problems.append(f"{where}：没有这个场景 {sid}")
            elif sid in seen_s:
                problems.append(f"{where}：场景 {sid} 出现了不止一次")
            seen_s.add(sid)
        elif it.get("type") == "hole":
            hid = it.get("id")
            if not isinstance(hid, str) or not hid:
                problems.append(f"{where}：空洞要有编号")
            elif hid in seen_h:
                problems.append(f"{where}：空洞编号 {hid} 重复了")
            seen_h.add(hid)
            if not isinstance(it.get("task"), str):
                problems.append(f"{where}：空洞 {hid} 要有任务说明")
        else:
            problems.append(f"{where}：条目类型只能是 scene 或 hole")

    for vi, v in enumerate(sk["volumes"], 1):
        if not isinstance(v, dict) or not str(v.get("title") or "").strip() or not isinstance(v.get("chapters"), list):
            problems.append(f"第 {vi} 卷要有标题和 chapters")
            continue
        for ci, ch in enumerate(v["chapters"], 1):
            where = f"第 {vi} 卷第 {ci} 章"
            if not isinstance(ch, dict) or not str(ch.get("title") or "").strip() or not isinstance(ch.get("items"), list):
                problems.append(f"{where}要有标题和 items")
                continue
            for it in ch["items"]:
                item(it, where)
    up = sk.get("unplaced") or {}
    if not isinstance(up, dict):
        problems.append("unplaced 要是对象")
    else:
        for x in up.get("scenes") or []:
            item({"type": "scene", "id": x.get("id") if isinstance(x, dict) else None}, "未定位")
        for x in up.get("holes") or []:
            item({**x, "type": "hole"} if isinstance(x, dict) else x, "未定位")
    return problems


def _strip_flags(sk: dict) -> dict:
    sk = copy.deepcopy(sk)
    for v in sk.get("volumes") or []:
        for ch in v.get("chapters") or []:
            for it in ch.get("items") or []:
                if isinstance(it, dict):
                    it.pop("flag", None)
    for x in (sk.get("unplaced") or {}).get("scenes") or []:
        if isinstance(x, dict):
            x.pop("flag", None)
    return sk


def save_skeleton(book: Book, sk) -> dict:
    """保存作者编辑后的整份骨架。场景编号认所有场景（含已移除的），已移除的由 annotate 标出来。"""
    known = {s.id for s in load_scenes(book)}
    problems = validate_skeleton(sk, known)
    if problems:
        raise ValueError("；".join(problems[:10]))
    sk = _strip_flags(sk)
    sk.setdefault("unplaced", {"scenes": [], "holes": []})
    sk["by"] = "author"
    sk["edited"] = now_iso()
    with FILE_LOCK:
        write_json(book.skeleton_path, sk)
    return sk


def annotate(book: Book, sk: dict, threads: dict) -> dict:
    """给界面看的副本：场景已经没了标 missing，所属线后来被砍标 cut。不落盘。"""
    out = copy.deepcopy(sk)
    live = {s.id for s in load_scenes(book) if not s.removed}
    cols = columns(book, threads)
    thread_of = {sid: t["id"] for t in threads.get("threads") or [] if isinstance(t, dict)
                 for sid in t.get("scenes") or []}

    def mark(it: dict) -> None:
        sid = it.get("id")
        if sid not in live:
            it["flag"] = "missing"
        elif cols.get(thread_of.get(sid), {}).get("col") == "cut":
            it["flag"] = "cut"

    for v in out.get("volumes") or []:
        for ch in v.get("chapters") or []:
            for it in ch.get("items") or []:
                if isinstance(it, dict) and it.get("type") == "scene":
                    mark(it)
    for x in (out.get("unplaced") or {}).get("scenes") or []:
        if isinstance(x, dict):
            mark(x)
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q tests/test_skeleton.py`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/skeleton.py tests/test_skeleton.py
git commit -m "feat: 骨架的读、保存编辑、校验与对账标注"
```

---

# 里程碑 4：导出

### Task 13: export.py——按骨架拼书

**Files:**
- Create: `src/ligaotai/export.py`
- Test: `tests/test_export.py`

- [ ] **Step 1: 写失败的测试** `tests/test_export.py`

```python
import pytest

from ligaotai.export import export_book, export_path
from ligaotai.fsutil import write_json

SK = {"generated": "x", "by": "author", "volumes": [{"title": "第一卷 起", "chapters": [
    {"title": "开篇", "notes": [], "items": [
        {"type": "scene", "id": "S-0001", "thread": "L-001"},
        {"type": "hole", "id": "H-001", "task": "在 S-0001 与 S-0003 之间补写：\n大闹天宫"},
        {"type": "scene", "id": "S-0099", "thread": "L-001"}]}]}],
    "unplaced": {"scenes": [{"id": "S-0005", "thread": "L-002", "why": "no_time"}], "holes": []}}

MD = """# 第一卷 起

## 开篇

<!-- S-0001 -->
S-0001 的正文。

> 【空洞 H-001】在 S-0001 与 S-0003 之间补写： 大闹天宫

> 【缺失场景 S-0099：原稿里已经没有这一块了】

# 附：未定位

<!-- S-0005 -->
S-0005 的正文。
"""

TXT = """第一卷 起

开篇

S-0001 的正文。

【空洞 H-001】在 S-0001 与 S-0003 之间补写： 大闹天宫

【缺失场景 S-0099：原稿里已经没有这一块了】

附：未定位

S-0005 的正文。
"""


def test_导出md和txt(book_with_threads):
    b = book_with_threads
    write_json(b.skeleton_path, SK)
    r = export_book(b)
    assert r == {"md": "导出/测试书.md", "txt": "导出/测试书.txt", "scenes": 2, "holes": 1, "missing": 1}
    assert export_path(b, "md").read_text(encoding="utf-8") == MD
    assert export_path(b, "txt").read_text(encoding="utf-8") == TXT


def test_没有骨架不能导出(book_with_threads):
    with pytest.raises(FileNotFoundError):
        export_book(book_with_threads)


def test_格式只认md和txt(book_with_threads):
    with pytest.raises(ValueError):
        export_path(book_with_threads, "docx")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest -q tests/test_export.py`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现** `src/ligaotai/export.py`

```python
"""按骨架拼书，导出 md / txt（计划④ spec 第 8 节）。只导出，不回写原稿。"""

from __future__ import annotations

from pathlib import Path

from .book import Book
from .fsutil import atomic_write_text, safe_name
from .scenes import BrokenSceneFile, get_scene
from .skeleton import load_skeleton

FORMATS = ("md", "txt")


def export_path(book: Book, fmt: str) -> Path:
    if fmt not in FORMATS:
        raise ValueError("只能导出 md 或 txt")
    title = book.load().get("title") or book.name
    return book.export_dir / f"{safe_name(title)}.{fmt}"


def _text(book: Book, sid: str) -> str | None:
    try:
        sc = get_scene(book, sid)
    except (BrokenSceneFile, ValueError, FileNotFoundError):
        return None
    return None if sc.removed else sc.text.strip()


def export_book(book: Book) -> dict:
    sk = load_skeleton(book)
    md: list[str] = []
    txt: list[str] = []
    counts = {"scenes": 0, "holes": 0, "missing": 0}

    def emit(it: dict) -> None:
        if it.get("type") == "hole":
            counts["holes"] += 1
            task = " ".join(str(it.get("task") or "").splitlines())
            md.append(f"> 【空洞 {it['id']}】{task}")
            txt.append(f"【空洞 {it['id']}】{task}")
            return
        sid = it.get("id")
        text = _text(book, sid)
        if text is None:
            counts["missing"] += 1
            md.append(f"> 【缺失场景 {sid}：原稿里已经没有这一块了】")
            txt.append(f"【缺失场景 {sid}：原稿里已经没有这一块了】")
            return
        counts["scenes"] += 1
        md.append(f"<!-- {sid} -->\n{text}")
        txt.append(text)

    for v in sk.get("volumes") or []:
        md.append(f"# {v['title']}")
        txt.append(v["title"])
        for ch in v.get("chapters") or []:
            md.append(f"## {ch['title']}")
            txt.append(ch["title"])
            for it in ch.get("items") or []:
                emit(it)
    up = sk.get("unplaced") or {}
    rest = [{"type": "scene", "id": x.get("id")} for x in up.get("scenes") or []] + \
           [{**x, "type": "hole"} for x in up.get("holes") or []]
    if rest:
        md.append("# 附：未定位")
        txt.append("附：未定位")
        for it in rest:
            emit(it)

    md_path, txt_path = export_path(book, "md"), export_path(book, "txt")
    atomic_write_text(md_path, "\n\n".join(md) + "\n")
    atomic_write_text(txt_path, "\n\n".join(txt) + "\n")
    rel = lambda p: p.relative_to(book.root).as_posix()  # noqa: E731
    return {"md": rel(md_path), "txt": rel(txt_path), **counts}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q tests/test_export.py`
Expected: PASS（`book_with_threads` 的书名是「测试书」，来自 conftest 的 `book` fixture）

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/export.py tests/test_export.py
git commit -m "feat: 按骨架导出 md / txt"
```

### Task 14: 骨架与导出接口

**Files:**
- Modify: `src/ligaotai/api.py`
- Test: `tests/test_api_triage.py`（追加）

- [ ] **Step 1: 写失败的测试**（追加）

```python
def _sk_handler(tier, messages):
    system, user = messages[0]["content"], messages[1]["content"]
    if "分卷分章" in system:
        return json.dumps({"volumes": [{"title": "卷一", "start": 0}], "chapters": [{"title": "全", "start": 0}]},
                          ensure_ascii=False)
    return json.dumps({"holes": []})


def test_生成骨架_读_改_导出_下载(tmp_path):
    c = _client(tmp_path, handler=_sk_handler)
    _seed_threads(tmp_path)
    _wait(c, c.post(f"{BOOK}/skeleton/generate"))
    sk = c.get(f"{BOOK}/skeleton").json()
    assert [i["id"] for i in sk["volumes"][0]["chapters"][0]["items"]] == ["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"]
    sk["volumes"][0]["chapters"][0]["title"] = "改过的章名"
    r = c.put(f"{BOOK}/skeleton", json=sk)
    assert r.status_code == 200 and r.json()["by"] == "author"
    bad = {**sk, "volumes": [{"title": "卷", "chapters": [{"title": "章", "items": [{"type": "scene", "id": "S-0099"}]}]}]}
    assert c.put(f"{BOOK}/skeleton", json=bad).status_code == 400
    r = c.post(f"{BOOK}/export")
    assert r.status_code == 200 and r.json()["scenes"] == 5
    d = c.get(f"{BOOK}/export/md")
    assert d.status_code == 200 and "## 改过的章名" in d.content.decode("utf-8")
    assert c.get(f"{BOOK}/export/docx").status_code == 400


def test_骨架的错误映射(tmp_path):
    c = _client(tmp_path)
    b = _seed_threads(tmp_path)
    assert c.get(f"{BOOK}/skeleton").status_code == 404
    assert c.post(f"{BOOK}/export").status_code == 404
    assert c.get(f"{BOOK}/export/md").status_code == 404
    b.triage_dir.mkdir(parents=True, exist_ok=True)
    b.skeleton_path.write_text("{坏", encoding="utf-8")
    r = c.get(f"{BOOK}/skeleton")
    assert r.status_code == 500 and "骨架.json" in r.json()["detail"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest -q tests/test_api_triage.py`
Expected: 新测试 FAIL

- [ ] **Step 3: 实现**（`src/ligaotai/api.py`）

import 区加：

```python
from fastapi import Body

from . import export as exp
from . import skeleton as skl
```

（`Body` 并进已有的 `from fastapi import FastAPI, HTTPException` 那一行。）

`triage_op` 里在 `except tri.BrokenBoardFile` 后面、`except ValueError` 前面加：

```python
        except skl.BrokenSkeletonFile as e:
            raise _读坏了("取舍/骨架.json", str(e))
```

路由：

```python
    @app.get("/api/books/{name}/skeleton")
    def skeleton_get(name: str) -> dict:
        b = get_book(name)
        return triage_op(lambda: skl.annotate(b, skl.load_skeleton(b), tops.load_threads(b)))

    @app.put("/api/books/{name}/skeleton")
    def skeleton_put(name: str, sk: dict = Body(...)) -> dict:
        require_idle()
        b = get_book(name)
        return triage_op(lambda: skl.save_skeleton(b, sk))

    @app.post("/api/books/{name}/skeleton/generate", status_code=202)
    def skeleton_generate(name: str) -> dict:
        b = get_book(name)
        triage_op(lambda: tri.columns(b, tops.load_threads(b)))  # 没归线 / 看板坏了先报错
        client = make_client(b)
        return submit(b, "skeleton", lambda p: skl.generate(b, client, p), track_step=False)

    @app.post("/api/books/{name}/export")
    def export_run(name: str) -> dict:
        require_idle()
        b = get_book(name)
        return triage_op(lambda: exp.export_book(b))

    @app.get("/api/books/{name}/export/{fmt}")
    def export_download(name: str, fmt: str) -> FileResponse:
        b = get_book(name)
        try:
            path = exp.export_path(b, fmt)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not path.exists():
            raise HTTPException(404, "还没有导出过")
        return FileResponse(path, filename=path.name)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/ligaotai/api.py tests/test_api_triage.py
git commit -m "feat: 骨架读写、生成、导出、下载接口"
```

---

# 前端

前端规矩（计划③ 的教训）：
- **测试全绿抓不到画面问题**，计划③ 一共 9 个画面 bug 全是截图抓到的。每个页面 Task 做完，执行者要在报告里写「没截图验」，由主会话在里程碑 5 统一截图；页面结构别偷懒。
- 页面照计划③ 的写法：`defineProps<{ name: string }>()`、`useJobStore()`、`onMounted(jobStore.start)` / `onUnmounted(jobStore.stop)`、错误用 `ErrorBox`、触发任务后 `jobStore.track(job)`、`jobStore.onFinish` 里重新加载。
- 测试照现有页面测试的写法：`vi.spyOn(api, 'xxx').mockResolvedValue(...)`、`RouterLink` 用会渲染插槽的桩。
- 样式只用 `tokens.css` 里的变量，不写死颜色；深色模式靠变量自动适配。

### Task 15: 类型、接口函数、DELETE、任务名标签

**Files:**
- Modify: `web/src/api/types.ts`、`web/src/api/endpoints.ts`、`web/src/api/client.ts`、`web/src/components/JobBar.vue`
- Test: `web/src/api/client.test.ts`（追加一条）、`web/src/components/JobBar.test.ts`（追加一条）

- [ ] **Step 1: 写失败的测试**

`web/src/api/client.test.ts` 追加（照文件里已有的 fetch 桩写法；下面假设已有 `mockFetch` 这类工具，没有就照文件里现成的写法 `vi.spyOn(globalThis, 'fetch')`）：

```ts
it('del 发 DELETE 请求', async () => {
  const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
  await del('/books/x/triage/board/L-009')
  expect(f).toHaveBeenCalledWith('/api/books/x/triage/board/L-009', expect.objectContaining({ method: 'DELETE' }))
})
```

`web/src/components/JobBar.test.ts` 追加：

```ts
it('二期任务显示中文名', () => {
  useJobStore().current = { ...造任务('running'), name: 'skeleton' }
  expect(mount(JobBar).text()).toContain('生成骨架')
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/api/client.test.ts src/components/JobBar.test.ts`
Expected: FAIL（`del` 未导出；显示的是 `skeleton`）

- [ ] **Step 3: 实现**

`client.ts` 在 `put` 后面加：

```ts
export function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' })
}
```

`types.ts` 末尾追加：

```ts
// ---- 二期：取舍（计划④）----

/** 不是流水线步骤的任务名（submit 时的 name），JobBar 显示用。 */
export const EXTRA_JOB_LABELS: Record<string, string> = {
  triage_advice: 'AI 取舍建议',
  triage_impact: '影响检查',
  skeleton: '生成骨架',
}

export type VerdictKind = 'pick' | 'own' | 'later'
export interface Verdict { kind: VerdictKind; value?: string; note?: string; by: string; at: string }
export interface VerdictReq { kind: VerdictKind | null; value?: string; note?: string }
export interface CanonItem { id: string; subject: string; attribute: string; value: string; sources: string[]; note: string }
export interface CanonFile { generated: string; items: CanonItem[] }
export interface Followups { id: string; verdict: Verdict | null; scenes: { id: string; quote: string; value: string }[] }

export type BoardCol = 'keep' | 'merge' | 'cut' | 'undecided'
export interface BoardCard { col: BoardCol; merge_into: string | null; note: string; orphan: boolean; merge_invalid: boolean }
export interface ThreadStat {
  name: string; world: string; words: number; scenes: number; state: string
  gaps: number; is_main: boolean; order_failed: boolean
}
export type AdviceKind = 'keep' | 'merge' | 'cut' | 'flashback'
export interface AdviceItem { thread: string; advice: AdviceKind; merge_into?: string | null; reason: string }
export interface AdviceStatus { generated: string; sig: string; items: AdviceItem[]; stale: boolean }
export interface BoardView { cards: Record<string, BoardCard>; stats: Record<string, ThreadStat>; advice: AdviceStatus | null }
export interface CardReq { col: BoardCol; merge_into?: string | null; note?: string | null }

export interface ProgramImpact {
  thread: string
  crossings: { other: string; scene: string; main_scene: string; reason: string }[]
  only_characters: { name: string; scenes: string[] }[]
  maybe_refs: { scene: string; thread: string; text: string; names: string[] }[]
}
export interface ModelImpact {
  sig: string; generated: string; stale: boolean; remedy: string
  pairs: { planted: string; resolved: string; hook: string }[]
}
export interface ImpactView { program: ProgramImpact; model: ModelImpact | null }

export type SkFlag = 'missing' | 'cut'
export interface SkScene { type: 'scene'; id: string; thread?: string | null; flag?: SkFlag }
export interface SkHole {
  type: 'hole'; id: string; task: string; gap?: string | null; after?: string | null; before?: string | null
  event?: string; thread?: string | null; mentioned_in?: string[]
}
export type SkItem = SkScene | SkHole
export interface SkNote { kind: 'undecided' | 'merge' | 'cut_crossing'; thread: string; into?: string; scene?: string }
export interface SkChapter { title: string; items: SkItem[]; notes: SkNote[] }
export interface SkVolume { title: string; chapters: SkChapter[] }
export interface SkUnplacedScene { id: string; thread: string | null; why: string; flag?: SkFlag }
export interface Skeleton {
  generated: string; by: 'program' | 'author'; edited?: string; fallback_chapters?: boolean
  volumes: SkVolume[]
  unplaced: { scenes: SkUnplacedScene[]; holes: (SkHole & { why?: string })[] }
}
export interface ExportResult { md: string; txt: string; scenes: number; holes: number; missing: number }
```

同时把 `ContradictionGroup` 里 `verdict: unknown | null` 改成 `verdict: Verdict | null`，并把那段「一期永远是 null」的注释改成「二期起作者裁决写这里（计划④ spec 第 5 节）」。

`endpoints.ts`：import 里补上新类型和 `del`，末尾追加：

```ts
// 二期：裁决
export const putVerdict = (name: string, cid: string, body: VerdictReq) =>
  put<ContradictionGroup>(`${b(name)}/contradictions/${cid}/verdict`, body)
export const getCanon = (name: string) => get<CanonFile>(`${b(name)}/canon`)
export const getFollowups = (name: string, cid: string) => get<Followups>(`${b(name)}/contradictions/${cid}/followups`)

// 二期：看板
export const getBoard = (name: string) => get<BoardView>(`${b(name)}/triage/board`)
export const putCard = (name: string, tid: string, body: CardReq) =>
  put<{ cards: Record<string, BoardCard> }>(`${b(name)}/triage/board/${tid}`, body)
export const deleteCard = (name: string, tid: string) =>
  del<{ cards: Record<string, BoardCard> }>(`${b(name)}/triage/board/${tid}`)
export const runAdvice = (name: string) => post<Job>(`${b(name)}/triage/advice`)
export const getImpact = (name: string, tid: string) => get<ImpactView>(`${b(name)}/triage/impact/${tid}`)
export const runImpact = (name: string, tid: string) => post<Job>(`${b(name)}/triage/impact/${tid}`)

// 二期：骨架与导出
export const getSkeleton = (name: string) => get<Skeleton>(`${b(name)}/skeleton`)
export const putSkeleton = (name: string, sk: Skeleton) => put<Skeleton>(`${b(name)}/skeleton`, sk)
export const generateSkeleton = (name: string) => post<Job>(`${b(name)}/skeleton/generate`)
export const exportBook = (name: string) => post<ExportResult>(`${b(name)}/export`)
export const exportUrl = (name: string, fmt: 'md' | 'txt') => `/api${b(name)}/export/${fmt}`
```

`JobBar.vue` 的 `步骤名` 改成：

```ts
const 步骤名 = computed(() => {
  const job = jobStore.current
  if (!job) return ''
  return STEP_LABELS[job.name as StepName] ?? EXTRA_JOB_LABELS[job.name] ?? job.name
})
```

（import 补 `EXTRA_JOB_LABELS`。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test && npm run typecheck`
Expected: 全绿（`ContradictionGroup.verdict` 类型收紧后，现有测试里 `verdict: null` 仍合法）

- [ ] **Step 5: 提交**

```bash
git add web/src/api web/src/components/JobBar.vue web/src/components/JobBar.test.ts
git commit -m "feat(web): 二期类型、接口函数、DELETE、任务名标签"
```

### Task 16: 矛盾页加裁决

**Files:**
- Modify: `web/src/pages/ContradictionsPage.vue`
- Test: `web/src/pages/ContradictionsPage.test.ts`（追加）

界面（spec 第 5 节）：每组下面一排操作——每个值一个「以「X」为准」按钮（值有几个就几个，不写死左右）、「都不对，我自己写」（点开输入框 + 确定）、「先放着」。已裁决的组显示结论（「定为：X」/「先放着」）和「撤销」按钮，并显示「另一边要跟着改的 N 处」（点开列出场景编号和原句，来自 `getFollowups`）。`verdict_stale` 的组提示「值变了，请重看」（原来那个「这条判断是在旧数据上做的」标签文案改成这句）。页头加筛选：全部 / 未裁决 / 需重看。

- [ ] **Step 1: 写失败的测试**（追加到 `describe` 里）

```ts
it('每个值一个「以此为准」按钮，点了写裁决并刷新', async () => {
  const get = vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组()]))
  const put = vi.spyOn(api, 'putVerdict').mockResolvedValue(造组({
    verdict: { kind: 'pick', value: '如意金箍棒', by: 'author', at: 'x' } }))
  const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  const btns = w.findAll('[data-test^="以此为准-"]')
  expect(btns.map((b) => b.text())).toEqual(['以「如意金箍棒」为准', '以「降妖宝杖」为准'])
  await btns[0].trigger('click')
  await flushPromises()
  expect(put).toHaveBeenCalledWith('guixu', 'C-001', { kind: 'pick', value: '如意金箍棒' })
  expect(get).toHaveBeenCalledTimes(2)
})

it('自己写：空的不许提交', async () => {
  vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组()]))
  const put = vi.spyOn(api, 'putVerdict').mockResolvedValue(造组())
  const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  await w.find('[data-test="自己写-C-001"]').trigger('click')
  expect(w.find('[data-test="自己写确定-C-001"]').attributes('disabled')).toBeDefined()
  await w.find('[data-test="自己写输入-C-001"]').setValue('金箍棒')
  await w.find('[data-test="自己写确定-C-001"]').trigger('click')
  await flushPromises()
  expect(put).toHaveBeenCalledWith('guixu', 'C-001', { kind: 'own', value: '金箍棒' })
})

it('已裁决的显示结论和撤销，要跟着改的场景点开才拉', async () => {
  vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组({
    verdict: { kind: 'pick', value: '如意金箍棒', by: 'author', at: 'x' } })]))
  const fu = vi.spyOn(api, 'getFollowups').mockResolvedValue({ id: 'C-001', verdict: null,
    scenes: [{ id: 'S-0207', quote: '行者举起降妖宝杖', value: '降妖宝杖' }] })
  const put = vi.spyOn(api, 'putVerdict').mockResolvedValue(造组())
  const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.find('[data-test="结论-C-001"]').text()).toContain('定为：如意金箍棒')
  expect(fu).not.toHaveBeenCalled()
  await w.find('[data-test="跟着改-C-001"]').trigger('click')
  await flushPromises()
  expect(w.text()).toContain('S-0207')
  await w.find('[data-test="撤销-C-001"]').trigger('click')
  expect(put).toHaveBeenCalledWith('guixu', 'C-001', { kind: null })
})

it('筛选：未裁决 / 需重看', async () => {
  vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([
    造组({ id: 'C-001' }),
    造组({ id: 'C-002', verdict: { kind: 'later', by: 'author', at: 'x' } }),
    造组({ id: 'C-003', verdict: { kind: 'pick', value: '降妖宝杖', by: 'author', at: 'x' }, verdict_stale: true }),
  ]))
  const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  await w.find('[data-test="筛选-未裁决"]').trigger('click')
  expect(w.findAll('[data-test="矛盾组"]').length).toBe(1)
  await w.find('[data-test="筛选-需重看"]').trigger('click')
  const groups = w.findAll('[data-test="矛盾组"]')
  expect(groups.length).toBe(1)
  expect(groups[0].text()).toContain('值变了，请重看')
})

it('有任务在跑时裁决按钮禁用', async () => {
  vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组()]))
  const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  useJobStore().current = { id: 'j', name: 'archive', book: 'guixu', status: 'running', done: 0, total: 1,
    message: '', error: '', result: null, started: '', finished: '', cancel_requested: false }
  await flushPromises()
  expect(w.find('[data-test="以此为准-C-001-0"]').attributes('disabled')).toBeDefined()
})
```

（文件顶部 import 补 `import { useJobStore } from '@/stores/job'`。）

「未裁决」= `verdict` 为 `null`（「先放着」算已经看过，不算未裁决）；「需重看」= `verdict_stale` 为真。筛选时桶照旧分，空桶不显示。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/pages/ContradictionsPage.test.ts`
Expected: 新测试 FAIL

- [ ] **Step 3: 实现**（`ContradictionsPage.vue`）

`<script setup>` 里：import 补 `putVerdict, getFollowups` 和 `Followups, VerdictReq` 类型；加：

```ts
type 筛选 = '全部' | '未裁决' | '需重看'
const 筛选项: 筛选[] = ['全部', '未裁决', '需重看']
const 当前筛选 = ref<筛选>('全部')

function 留下(g: ContradictionGroup): boolean {
  if (当前筛选.value === '未裁决') return g.verdict === null
  if (当前筛选.value === '需重看') return g.verdict_stale
  return true
}

const 自己写开着 = ref<Record<string, boolean>>({})
const 自己写草稿 = ref<Record<string, string>>({})
const 跟着改 = ref<Record<string, Followups | undefined>>({})

async function 裁决(g: ContradictionGroup, body: VerdictReq): Promise<void> {
  error.value = ''
  try {
    await putVerdict(props.name, g.id, body)
    自己写开着.value[g.id] = false
    跟着改.value[g.id] = undefined
    await 加载()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
  }
}

async function 看跟着改(g: ContradictionGroup): Promise<void> {
  try {
    跟着改.value[g.id] = await getFollowups(props.name, g.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
  }
}

function 结论(g: ContradictionGroup): string {
  const v = g.verdict
  if (!v) return ''
  if (v.kind === 'later') return '先放着'
  return `定为：${v.value}${v.kind === 'own' ? '（作者自己写的）' : ''}`
}
```

`桶列表` 里 `const groups = data.value?.groups ?? []` 改成 `const groups = (data.value?.groups ?? []).filter(留下)`。

模板：`<template v-else-if="data">` 里 `skip-note` 前面加筛选条：

```html
<div class="filters">
  <button v-for="f in 筛选项" :key="f" :class="{ on: 当前筛选 === f }" :data-test="`筛选-${f}`" @click="当前筛选 = f">{{ f }}</button>
</div>
```

`verdict过期` 那个标签文案改成「值变了，请重看」。每组 `.value` 循环后面加：

```html
<div class="verdict">
  <template v-if="g.verdict">
    <span class="conclusion" :data-test="`结论-${g.id}`">{{ 结论(g) }}</span>
    <button :data-test="`撤销-${g.id}`" :disabled="jobStore.busy" @click="裁决(g, { kind: null })">撤销</button>
    <button v-if="g.verdict.kind !== 'later'" class="link" :data-test="`跟着改-${g.id}`" @click="看跟着改(g)">另一边要跟着改的地方</button>
    <ul v-if="跟着改[g.id]" class="followups">
      <li v-for="s in 跟着改[g.id]!.scenes" :key="s.id + s.value"><span class="sid">[{{ s.id }}]</span> {{ s.quote }}（写的是「{{ s.value }}」）</li>
      <li v-if="跟着改[g.id]!.scenes.length === 0" class="none">没有要跟着改的地方</li>
    </ul>
  </template>
  <template v-if="!g.verdict || g.verdict_stale">
    <button v-for="(v, i) in g.values" :key="i" :data-test="`以此为准-${g.id}-${i}`" :disabled="jobStore.busy"
            @click="裁决(g, { kind: 'pick', value: v.value })">以「{{ v.value }}」为准</button>
    <button :data-test="`自己写-${g.id}`" :disabled="jobStore.busy" @click="自己写开着[g.id] = true">都不对，我自己写</button>
    <button :data-test="`先放着-${g.id}`" :disabled="jobStore.busy" @click="裁决(g, { kind: 'later' })">先放着</button>
    <span v-if="自己写开着[g.id]" class="own">
      <input v-model="自己写草稿[g.id]" :data-test="`自己写输入-${g.id}`" placeholder="写下正确的说法" />
      <button :data-test="`自己写确定-${g.id}`" :disabled="jobStore.busy || !(自己写草稿[g.id] ?? '').trim()"
              @click="裁决(g, { kind: 'own', value: (自己写草稿[g.id] ?? '').trim() })">确定</button>
    </span>
  </template>
</div>
```

注意测试里 `data-test="以此为准-C-001-0"` 和 `findAll('[data-test^="以此为准-"]')`——按钮文字是「以「值」为准」。

样式追加：

```css
.filters{display:flex;gap:6px;margin-bottom:12px}
.filters .on{border-color:var(--accent);color:var(--accent)}
.verdict{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:8px}
.conclusion{font-weight:600;color:var(--green)}
.link{border:none;background:none;color:var(--accent);padding:0;text-decoration:underline}
.followups{width:100%;margin:4px 0 0;padding-left:16px;font-size:13px;color:var(--ink-2)}
.followups .none{color:var(--ink-3);list-style:none}
.own{display:inline-flex;gap:6px}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test && npm run typecheck`
Expected: 全绿（原来断言「这条判断是在旧数据上做的」的测试要跟着改成新文案——**这是本 Task 有意改的文案，不算迁就实现**，报告里写明）

- [ ] **Step 5: 提交**

```bash
git add web/src/pages/ContradictionsPage.vue web/src/pages/ContradictionsPage.test.ts
git commit -m "feat(web): 矛盾页裁决：以某值为准 / 自己写 / 先放着 / 撤销 / 筛选"
```

### Task 17: 导航与路由

**Files:**
- Modify: `web/src/router.ts`、`web/src/components/NavRail.vue`、`web/src/components/NavRail.test.ts`、`web/src/components/AppShell.vue`、`web/src/layouts/BookLayout.vue`

spec 第 10 节：侧栏在一期常驻项下面加一组「取舍」：**取舍看板**（`/b/:name/board`）、**成书骨架**（`/b/:name/skeleton`）。矛盾角标改为「**未裁决的严重矛盾数**」。

- [ ] **Step 1: 写失败的测试**（`NavRail.test.ts` 追加；`基本` 里的 `contradictions` 语义变成未裁决严重数，名字不改）

```ts
it('取舍一组：看板和骨架两项常驻', () => {
  const w = mount(NavRail, { props: 基本, global: { stubs: { RouterLink: routerLinkStub } } })
  expect(w.find('[data-test="取舍组"]').text()).toContain('取舍看板')
  expect(w.find('[data-test="取舍组"]').text()).toContain('成书骨架')
})
```

同时把现有测试 `二期页面不出现在导航里` 改成只断言「补写」「导出 docx」这类三期入口不出现（`取舍`、`骨架` 现在应该出现了）——**这是二期上线后有意改的断言**，报告里写明：

```ts
it('三期页面不出现在导航里', () => {
  const w = mount(NavRail, { props: 基本, global: { stubs: { RouterLink: routerLinkStub } } })
  expect(w.text()).not.toContain('补写')
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/components/NavRail.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现**

`router.ts` 的书内 children 里 `contradictions` 后面加：

```ts
        { path: 'board', name: 'board', component: () => import('./pages/BoardPage.vue'), props: true },
        { path: 'skeleton', name: 'skeleton', component: () => import('./pages/SkeletonPage.vue'), props: true },
```

（`BoardPage.vue` / `SkeletonPage.vue` 在 Task 18 / 19 才写，本 Task 先建两个最小占位文件，免得 typecheck 挂：）

```vue
<script setup lang="ts">
defineProps<{ name: string }>()
</script>

<template>
  <div class="page"><h1>取舍看板</h1></div>
</template>
```

（骨架那个写「成书骨架」。）

`NavRail.vue` 在矛盾那个 `RouterLink` 后面、`</nav>` 前面加：

```html
      <div class="group" data-test="取舍组">
        <div class="glabel">取舍</div>
        <RouterLink class="tab" :to="`/b/${bookName}/board`"><span>取舍看板</span></RouterLink>
        <RouterLink class="tab" :to="`/b/${bookName}/skeleton`"><span>成书骨架</span></RouterLink>
      </div>
```

样式：

```css
.group{margin-top:10px;padding-top:8px;border-top:1px solid var(--line-2);display:flex;flex-direction:column;gap:2px}
.glabel{font-size:12px;color:var(--ink-3);padding:0 10px 4px}
```

`BookLayout.vue`：`矛盾` 改成从矛盾文件现算未裁决的严重数：

```ts
import { getBook, getContradictions } from '@/api/endpoints'
// ……
const 未裁决严重 = ref(0)

async function 数矛盾(): Promise<void> {
  try {
    const f = await getContradictions(props.name)
    未裁决严重.value = f.groups.filter((g) => g.status === '真矛盾' && g.level === '严重' && g.verdict === null).length
  } catch {
    未裁决严重.value = 0 // 还没跑步骤 7：角标不显示，不当错误
  }
}
```

`加载()` 末尾加 `await 数矛盾()`；模板里 `:contradictions="矛盾"` 改成 `:contradictions="未裁决严重"`，删掉原来的 `矛盾` computed。矛盾页裁决后要让角标立刻变：`ContradictionsPage` 的 `裁决()` 成功后调 `inject('刷新书')`（BookLayout 已经 `provide('刷新书', 加载)`）：

```ts
const 刷新书 = inject<() => Promise<void>>('刷新书', async () => {})
// 裁决() 里 await 加载() 之后：
await 刷新书()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test && npm run typecheck`
Expected: 全绿。`BookLayout` 若有测试断言矛盾角标来自 `steps.archive.summary.contradictions`，改成 mock `getContradictions` 并按新口径断言——**有意改的口径**，报告里写明。

- [ ] **Step 5: 提交**

```bash
git add web/src/router.ts web/src/components web/src/layouts web/src/pages/BoardPage.vue web/src/pages/SkeletonPage.vue web/src/pages/ContradictionsPage.vue
git commit -m "feat(web): 导航加取舍一组；矛盾角标改为未裁决的严重矛盾数"
```

### Task 18: 取舍看板页

**Files:**
- Modify: `web/src/pages/BoardPage.vue`（替换占位）
- Create: `web/src/pages/BoardPage.test.ts`

界面（spec 6.2、6.3，原型 `docs/prototype/ligaotai-prototype.html` 的「取舍与骨架」一节）：
- 顶部：「让 AI 给建议」按钮（有建议且没过期时文字是「重新生成建议」；过期时提示「线变了，建议可能过时」）。
- 四列：保留 / 合并 / 砍掉 / 还没想好。每张卡：线名（主线加 ★）、世界、`N 块 · 约 N 字 · 完结/待定 · 缺口 N`、排序失败时红字提示；AI 建议那一行（「AI：建议砍掉——理由」，理由原样显示）；「移到…」下拉（四列，选「合并」时再出一个「并入哪条线」下拉，选完才提交）；孤儿卡灰显 + 「删掉这张卡」；合并目标失效红字提示。
- 卡片可以原生拖放（`draggable="true"`，列上 `@dragover.prevent` + `@drop`）；拖进合并列时同样要选并入哪条线，**拖放和下拉走同一个 `移到(tid, col)` 函数**。
- 卡进了「砍掉 / 合并」列后，卡下方出「影响」区：先显示程序化部分（交汇点、独有人物、可能的引用——标「可能」），再显示模型部分；模型部分没有或过期时给「检查伏笔影响」按钮（触发任务）。
- 所有写操作在 `jobStore.busy` 时禁用。

- [ ] **Step 1: 写失败的测试** `web/src/pages/BoardPage.test.ts`

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BoardPage from './BoardPage.vue'
import * as api from '@/api/endpoints'
import type { BoardView, ImpactView, Job } from '@/api/types'

const stubs = { RouterLink: { template: '<a><slot /></a>', props: ['to'] } }

function 造看板(over: Partial<BoardView> = {}): BoardView {
  const stat = (name: string, is_main = false) => ({ name, world: 'W-01', words: 12000, scenes: 8, state: '待定',
    gaps: 2, is_main, order_failed: false })
  return {
    cards: {
      'L-001': { col: 'keep', merge_into: null, note: '', orphan: false, merge_invalid: false },
      'L-002': { col: 'undecided', merge_into: null, note: '', orphan: false, merge_invalid: false },
    },
    stats: { 'L-001': stat('岑秀入仕', true), 'L-002': stat('小梅身世') },
    advice: null,
    ...over,
  }
}

const 影响: ImpactView = {
  program: { thread: 'L-002', crossings: [{ other: 'L-001', scene: 'S-0087', main_scene: 'S-0001', reason: '同赴山东' }],
    only_characters: [{ name: '小梅', scenes: ['S-0086'] }], maybe_refs: [] },
  model: null,
}

const job: Job = { id: 'j', name: 'triage_impact', book: 'x', status: 'queued', done: 0, total: 1, message: '',
  error: '', result: null, started: '', finished: '', cancel_requested: false }

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('BoardPage', () => {
  it('四列按看板分好，卡片显示统计，主线有星号，没有费用数字', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="列-keep"]').text()).toContain('岑秀入仕')
    expect(w.find('[data-test="列-undecided"]').text()).toContain('小梅身世')
    expect(w.find('[data-test="卡-L-001"]').text()).toContain('★')
    expect(w.find('[data-test="卡-L-001"]').text()).toContain('8 块')
    expect(w.text()).not.toContain('$')
  })

  it('「移到」砍掉：写看板，并拉影响检查', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    const put = vi.spyOn(api, 'putCard').mockResolvedValue({ cards: 造看板().cards })
    const imp = vi.spyOn(api, 'getImpact').mockResolvedValue(影响)
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="移到-L-002"]').setValue('cut')
    await flushPromises()
    expect(put).toHaveBeenCalledWith('x', 'L-002', { col: 'cut' })
    expect(imp).toHaveBeenCalledWith('x', 'L-002')
  })

  it('移到合并：先选并入哪条线才提交', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    const put = vi.spyOn(api, 'putCard').mockResolvedValue({ cards: 造看板().cards })
    vi.spyOn(api, 'getImpact').mockResolvedValue(影响)
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="移到-L-002"]').setValue('merge')
    expect(put).not.toHaveBeenCalled()
    await w.find('[data-test="并入-L-002"]').setValue('L-001')
    await flushPromises()
    expect(put).toHaveBeenCalledWith('x', 'L-002', { col: 'merge', merge_into: 'L-001' })
  })

  it('砍掉列的卡显示程序化影响，模型部分没有时给按钮', async () => {
    const view = 造看板()
    view.cards['L-002'].col = 'cut'
    vi.spyOn(api, 'getBoard').mockResolvedValue(view)
    vi.spyOn(api, 'getImpact').mockResolvedValue(影响)
    const run = vi.spyOn(api, 'runImpact').mockResolvedValue(job)
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    const box = w.find('[data-test="影响-L-002"]')
    expect(box.text()).toContain('S-0087')
    expect(box.text()).toContain('小梅')
    await w.find('[data-test="检查伏笔-L-002"]').trigger('click')
    expect(run).toHaveBeenCalledWith('x', 'L-002')
  })

  it('AI 建议显示在卡上，过期要提示', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板({ advice: { generated: 'x', sig: 's', stale: true,
      items: [{ thread: 'L-002', advice: 'cut', merge_into: null, reason: '篇幅短 [S-0086]' }] } }))
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="卡-L-002"]').text()).toContain('建议砍掉')
    expect(w.find('[data-test="卡-L-002"]').text()).toContain('篇幅短 [S-0086]')
    expect(w.text()).toContain('建议可能过时')
  })

  it('让 AI 给建议：触发任务并交给 job store', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    const run = vi.spyOn(api, 'runAdvice').mockResolvedValue({ ...job, name: 'triage_advice' })
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="AI建议"]').trigger('click')
    expect(run).toHaveBeenCalledWith('x')
  })

  it('孤儿卡可以删，合并目标失效要提示', async () => {
    const view = 造看板()
    view.cards['L-009'] = { col: 'cut', merge_into: null, note: '', orphan: true, merge_invalid: false }
    view.cards['L-002'] = { col: 'merge', merge_into: 'L-001', note: '', orphan: false, merge_invalid: true }
    vi.spyOn(api, 'getBoard').mockResolvedValue(view)
    vi.spyOn(api, 'getImpact').mockResolvedValue(影响)
    const del = vi.spyOn(api, 'deleteCard').mockResolvedValue({ cards: {} })
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="卡-L-002"]').text()).toContain('合并目标失效')
    await w.find('[data-test="删卡-L-009"]').trigger('click')
    expect(del).toHaveBeenCalledWith('x', 'L-009')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/pages/BoardPage.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现** `web/src/pages/BoardPage.vue`

```vue
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { deleteCard, getBoard, getImpact, putCard, runAdvice, runImpact } from '@/api/endpoints'
import type { AdviceItem, BoardCol, BoardView, ImpactView } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'

const props = defineProps<{ name: string }>()
const jobStore = useJobStore()

const view = ref<BoardView | null>(null)
const error = ref('')
const 影响 = ref<Record<string, ImpactView | undefined>>({})
const 待选并入 = ref<Record<string, boolean>>({})

const 列: { key: BoardCol; label: string }[] = [
  { key: 'keep', label: '保留' },
  { key: 'merge', label: '合并' },
  { key: 'cut', label: '砍掉' },
  { key: 'undecided', label: '还没想好' },
]
const 建议文字: Record<string, string> = { keep: '建议保留', merge: '建议合并', cut: '建议砍掉', flashback: '建议改成回忆' }

function 报错(e: unknown): void {
  error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
}

async function 加载(): Promise<void> {
  error.value = ''
  try {
    view.value = await getBoard(props.name)
    for (const [tid, c] of Object.entries(view.value.cards)) {
      if (!c.orphan && (c.col === 'cut' || c.col === 'merge')) void 拉影响(tid)
    }
  } catch (e) {
    报错(e)
  }
}

async function 拉影响(tid: string): Promise<void> {
  try {
    影响.value[tid] = await getImpact(props.name, tid)
  } catch (e) {
    报错(e)
  }
}

const 按列 = computed(() => {
  const out: Record<BoardCol, string[]> = { keep: [], merge: [], cut: [], undecided: [] }
  for (const [tid, c] of Object.entries(view.value?.cards ?? {})) out[c.col].push(tid)
  for (const k of Object.keys(out) as BoardCol[]) out[k].sort()
  return out
})

const 活线 = computed(() => Object.entries(view.value?.cards ?? {}).filter(([, c]) => !c.orphan).map(([t]) => t).sort())

function 建议(tid: string): AdviceItem | undefined {
  return view.value?.advice?.items.find((i) => i.thread === tid)
}

function 线名(tid: string): string {
  return view.value?.stats[tid]?.name ?? tid
}

async function 移到(tid: string, col: BoardCol, mergeInto?: string): Promise<void> {
  if (col === 'merge' && !mergeInto) {
    待选并入.value[tid] = true
    return
  }
  error.value = ''
  try {
    await putCard(props.name, tid, col === 'merge' ? { col, merge_into: mergeInto } : { col })
    待选并入.value[tid] = false
    await 加载()
  } catch (e) {
    报错(e)
  }
}

async function 删卡(tid: string): Promise<void> {
  try {
    await deleteCard(props.name, tid)
    await 加载()
  } catch (e) {
    报错(e)
  }
}

async function 要建议(): Promise<void> {
  try {
    jobStore.track(await runAdvice(props.name))
  } catch (e) {
    报错(e)
  }
}

async function 查伏笔(tid: string): Promise<void> {
  try {
    jobStore.track(await runImpact(props.name, tid))
  } catch (e) {
    报错(e)
  }
}

// 拖放：跟「移到」下拉走同一个函数
const 拖着 = ref('')
function 放下(col: BoardCol): void {
  if (拖着.value) void 移到(拖着.value, col)
  拖着.value = ''
}

const 退订 = jobStore.onFinish(() => { void 加载() })
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
  <div class="page">
    <h1>取舍看板 —— 《{{ name }}》</h1>
    <ErrorBox :message="error" />
    <div class="bar">
      <button data-test="AI建议" :disabled="jobStore.busy" @click="要建议">
        {{ view?.advice ? '重新生成建议' : '让 AI 给建议' }}
      </button>
      <span v-if="view?.advice?.stale" class="warn">线变了，建议可能过时</span>
    </div>

    <div v-if="view" class="cols">
      <section v-for="c in 列" :key="c.key" class="col" :data-test="`列-${c.key}`"
               @dragover.prevent @drop="放下(c.key)">
        <h2>{{ c.label }}（{{ 按列[c.key].length }}）</h2>
        <article v-for="tid in 按列[c.key]" :key="tid" class="card" :class="{ orphan: view.cards[tid].orphan }"
                 :data-test="`卡-${tid}`" :draggable="!view.cards[tid].orphan && !jobStore.busy"
                 @dragstart="拖着 = tid">
          <header>
            <b>{{ view.stats[tid]?.is_main ? '★ ' : '' }}{{ 线名(tid) }}</b>
            <span class="id">{{ tid }}</span>
          </header>
          <p v-if="view.stats[tid]" class="meta">
            {{ view.stats[tid].world }} · {{ view.stats[tid].scenes }} 块 · 约 {{ view.stats[tid].words }} 字 ·
            {{ view.stats[tid].state }} · 缺口 {{ view.stats[tid].gaps }}
          </p>
          <p v-if="view.stats[tid]?.order_failed" class="bad">这条线排序失败，顺序不可信</p>
          <p v-if="view.cards[tid].orphan" class="muted">这条线已经不在了
            <button :data-test="`删卡-${tid}`" :disabled="jobStore.busy" @click="删卡(tid)">删掉这张卡</button>
          </p>
          <p v-if="view.cards[tid].col === 'merge'" class="meta">并入 {{ 线名(view.cards[tid].merge_into ?? '') }}</p>
          <p v-if="view.cards[tid].merge_invalid" class="bad">合并目标失效：并入的线已经被砍或不存在了</p>
          <p v-if="建议(tid)" class="advice">AI：{{ 建议文字[建议(tid)!.advice] }}<template v-if="建议(tid)!.merge_into">（并入 {{ 线名(建议(tid)!.merge_into!) }}）</template>——{{ 建议(tid)!.reason }}</p>

          <div v-if="!view.cards[tid].orphan" class="move">
            <select :data-test="`移到-${tid}`" :disabled="jobStore.busy" :value="view.cards[tid].col"
                    @change="移到(tid, ($event.target as HTMLSelectElement).value as BoardCol)">
              <option v-for="o in 列" :key="o.key" :value="o.key">移到：{{ o.label }}</option>
            </select>
            <select v-if="待选并入[tid]" :data-test="`并入-${tid}`" :disabled="jobStore.busy" value=""
                    @change="移到(tid, 'merge', ($event.target as HTMLSelectElement).value)">
              <option value="" disabled>并入哪条线？</option>
              <option v-for="o in 活线.filter((x) => x !== tid && view!.cards[x].col !== 'cut')" :key="o" :value="o">{{ 线名(o) }}</option>
            </select>
          </div>

          <div v-if="影响[tid] && (view.cards[tid].col === 'cut' || view.cards[tid].col === 'merge')"
               class="impact" :data-test="`影响-${tid}`">
            <div class="k">会影响</div>
            <ul>
              <li v-for="x in 影响[tid]!.program.crossings" :key="x.scene + x.main_scene">
                和 {{ 线名(x.other) }} 的交汇点：{{ x.scene }} ↔ {{ x.main_scene }}（{{ x.reason }}）
              </li>
              <li v-for="p in 影响[tid]!.program.only_characters" :key="p.name">
                只在这条线出场的人物：{{ p.name }}（{{ p.scenes.join('、') }}）
              </li>
              <li v-for="r in 影响[tid]!.program.maybe_refs" :key="r.scene + r.text">
                可能：{{ 线名(r.thread) }} 的 {{ r.scene }} 提到「{{ r.text }}」
              </li>
              <li v-for="p in 影响[tid]!.model?.pairs ?? []" :key="p.planted + p.resolved">
                伏笔：{{ p.planted }} 埋 → {{ p.resolved }} 收（{{ p.hook }}）
              </li>
            </ul>
            <p v-if="影响[tid]!.model && !影响[tid]!.model!.stale" class="remedy">{{ 影响[tid]!.model!.remedy }}</p>
            <button v-else :data-test="`检查伏笔-${tid}`" :disabled="jobStore.busy" @click="查伏笔(tid)">
              {{ 影响[tid]!.model ? '看板变了，重新检查伏笔影响' : '检查伏笔影响' }}
            </button>
          </div>
        </article>
      </section>
    </div>
  </div>
</template>

<style scoped>
.page{padding:24px}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
.bar{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.warn{color:var(--amber);font-size:13px}
.cols{display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:12px;align-items:start}
.col{background:var(--sunk);border-radius:8px;padding:10px;min-height:120px}
.col h2{font-size:14px;margin:0 0 8px}
.card{background:var(--panel);border:1px solid var(--line-2);border-radius:8px;padding:10px;margin-bottom:8px;font-size:13px}
.card.orphan{opacity:.6}
.card header{display:flex;justify-content:space-between;gap:6px}
.card .id{color:var(--ink-3);font-size:12px}
.meta{color:var(--ink-2);margin:4px 0}
.bad{color:var(--red);margin:4px 0}
.muted{color:var(--ink-3)}
.advice{color:var(--ink-2);background:var(--accent-soft);border-radius:6px;padding:6px;margin:6px 0}
.move{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.impact{margin-top:8px;border-top:1px dashed var(--line);padding-top:6px}
.impact .k{font-weight:600;color:var(--red)}
.impact ul{margin:4px 0;padding-left:16px}
.remedy{color:var(--ink-2)}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test && npm run typecheck`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add web/src/pages/BoardPage.vue web/src/pages/BoardPage.test.ts
git commit -m "feat(web): 取舍看板页：四列、AI 建议、移到/拖放、影响检查"
```

### Task 19: 成书骨架页（含导出）

**Files:**
- Modify: `web/src/pages/SkeletonPage.vue`（替换占位）
- Create: `web/src/pages/SkeletonPage.test.ts`

界面（spec 7.6、第 8 节）：
- 顶部：「生成骨架」（已有骨架且 `by === 'author'` 时先确认「会覆盖你的手改，旧版本会备份成 骨架.bak.json」——**用页面里的确认条，不用 `window.confirm`**，浏览器弹窗会卡住自动化截图）、「导出」（导出后显示两个文件名、场景 / 空洞 / 缺失数，和 md、txt 两个下载链接）。`fallback_chapters` 为真时提示「模型分章没成功，用了按字数的兜底切法」。
- 左栏卷章树：卷名、章名可点改名（输入框，回车或失焦保存）；章可以「上移 / 下移」（跨卷时移到相邻卷末 / 卷首）。
- 右栏选中章的条目：场景显示编号 + 所属线；`flag` 为 `missing` / `cut` 灰显并写原因；空洞红框、展开显示任务说明（可改）、可删；「在这里加空洞」；场景可「移到上一章 / 下一章」。章的 `notes` 用小标签：「去留未定：L-003」「待并入 L-001 改写：L-002」「此处原与被砍的 L-004 交汇」。
- 底部「未定位」：场景列出原因（没有时间 / 这条线没对齐主线 / 没归到任何线），可以「放进当前章」；未定位空洞列出。
- 编辑都是改本地副本后整份 `putSkeleton`；保存失败显示后端给的原因。

- [ ] **Step 1: 写失败的测试** `web/src/pages/SkeletonPage.test.ts`

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SkeletonPage from './SkeletonPage.vue'
import * as api from '@/api/endpoints'
import { ApiError } from '@/api/client'
import type { Skeleton, Job } from '@/api/types'

const stubs = { RouterLink: { template: '<a><slot /></a>', props: ['to'] } }

function 造骨架(over: Partial<Skeleton> = {}): Skeleton {
  return {
    generated: 'x', by: 'program',
    volumes: [{ title: '第一卷', chapters: [
      { title: '开篇', notes: [{ kind: 'undecided', thread: 'L-003' }], items: [
        { type: 'scene', id: 'S-0001', thread: 'L-001' },
        { type: 'hole', id: 'H-001', task: '在 S-0001 与 S-0003 之间补写：大闹天宫 [S-0001]' },
        { type: 'scene', id: 'S-0004', thread: 'L-002', flag: 'cut' }] },
      { title: '龙宫', notes: [{ kind: 'cut_crossing', thread: 'L-004', scene: 'S-0066' }], items: [
        { type: 'scene', id: 'S-0005', thread: 'L-002' }] }] }],
    unplaced: { scenes: [{ id: 'S-0084', thread: 'L-001', why: 'no_time' }], holes: [] },
    ...over,
  }
}

const job: Job = { id: 'j', name: 'skeleton', book: 'x', status: 'queued', done: 0, total: 1, message: '',
  error: '', result: null, started: '', finished: '', cancel_requested: false }

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('SkeletonPage', () => {
  it('卷章树、条目、备注、未定位', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="卷章树"]').text()).toContain('开篇')
    expect(w.find('[data-test="卷章树"]').text()).toContain('龙宫')
    const items = w.find('[data-test="条目"]')
    expect(items.text()).toContain('S-0001')
    expect(items.find('[data-test="空洞-H-001"]').text()).toContain('大闹天宫')
    expect(items.find('[data-test="场景-S-0004"]').classes()).toContain('flagged')
    expect(w.text()).toContain('去留未定：L-003')
    expect(w.find('[data-test="未定位"]').text()).toContain('S-0084')
    expect(w.find('[data-test="未定位"]').text()).toContain('没有时间')
  })

  it('还没有骨架：显示空态和生成按钮', async () => {
    vi.spyOn(api, 'getSkeleton').mockRejectedValue(new ApiError(404, '还没有骨架，先生成一次'))
    const gen = vi.spyOn(api, 'generateSkeleton').mockResolvedValue(job)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="空态"]').exists()).toBe(true)
    await w.find('[data-test="生成"]').trigger('click')
    expect(gen).toHaveBeenCalledWith('x')
  })

  it('作者改过时生成要先确认', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架({ by: 'author' }))
    const gen = vi.spyOn(api, 'generateSkeleton').mockResolvedValue(job)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="生成"]').trigger('click')
    expect(gen).not.toHaveBeenCalled()
    expect(w.text()).toContain('骨架.bak.json')
    await w.find('[data-test="确认覆盖"]').trigger('click')
    expect(gen).toHaveBeenCalled()
  })

  it('改章名：整份保存', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    const put = vi.spyOn(api, 'putSkeleton').mockImplementation(async (_n, sk) => ({ ...sk, by: 'author' }))
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="章名-0-0"]').trigger('dblclick')
    const input = w.find('[data-test="章名输入-0-0"]')
    await input.setValue('新章名')
    await input.trigger('keyup.enter')
    await flushPromises()
    expect(put).toHaveBeenCalled()
    expect(put.mock.calls[0][1].volumes[0].chapters[0].title).toBe('新章名')
  })

  it('场景移到下一章、删空洞', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    const put = vi.spyOn(api, 'putSkeleton').mockImplementation(async (_n, sk) => sk)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="下移场景-S-0001"]').trigger('click')
    await flushPromises()
    const sk1 = put.mock.calls[0][1]
    expect(sk1.volumes[0].chapters[0].items.map((i) => i.id)).toEqual(['H-001', 'S-0004'])
    expect(sk1.volumes[0].chapters[1].items.map((i) => i.id)).toEqual(['S-0001', 'S-0005'])
    await w.find('[data-test="删空洞-H-001"]').trigger('click')
    await flushPromises()
    expect(put.mock.calls[1][1].volumes[0].chapters[0].items.map((i) => i.id)).toEqual(['S-0004'])
  })

  it('导出：显示结果和下载链接', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    vi.spyOn(api, 'exportBook').mockResolvedValue({ md: '导出/x.md', txt: '导出/x.txt', scenes: 3, holes: 1, missing: 0 })
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="导出"]').trigger('click')
    await flushPromises()
    const r = w.find('[data-test="导出结果"]')
    expect(r.text()).toContain('导出/x.md')
    expect(r.find('a[href$="/export/md"]').exists()).toBe(true)
  })
})
```

「移到下一章」说明：场景从当前章移出，放到**下一章的开头**；当前是本卷最后一章时放到下一卷第一章开头；已经是全书最后一章则按钮禁用。「移到上一章」对称（放到上一章末尾）。测试里 `S-0001` 下移后在「龙宫」开头。

`getSkeleton` 404 判定：`client.ts` 的 `ApiError(status, detail)` 本来就带 `status`，用 `e instanceof ApiError && e.status === 404`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/pages/SkeletonPage.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现** `web/src/pages/SkeletonPage.vue`

```vue
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { exportBook, exportUrl, generateSkeleton, getSkeleton, putSkeleton } from '@/api/endpoints'
import type { ExportResult, SkChapter, SkHole, SkItem, SkNote, Skeleton } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'

const props = defineProps<{ name: string }>()
const jobStore = useJobStore()

const sk = ref<Skeleton | null>(null)
const 没有 = ref(false)
const error = ref('')
const 选中 = ref<[number, number]>([0, 0])
const 确认中 = ref(false)
const 导出结果 = ref<ExportResult | null>(null)
const 改名 = ref<Record<string, string | undefined>>({})

const 原因: Record<string, string> = { no_time: '没有时间', unaligned_thread: '这条线没对齐主线', unassigned: '没归到任何线', no_anchor: '前后都没有锚点' }

function 报错(e: unknown): void {
  error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
}

function 是404(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404
}

async function 加载(): Promise<void> {
  error.value = ''
  try {
    sk.value = await getSkeleton(props.name)
    没有.value = false
  } catch (e) {
    if (是404(e)) {
      没有.value = true
      sk.value = null
    } else 报错(e)
  }
}

const 当前章 = computed<SkChapter | null>(() => {
  const [v, c] = 选中.value
  return sk.value?.volumes[v]?.chapters[c] ?? null
})

/** 全书章节按顺序摊平，给「上一章 / 下一章」用。 */
const 章序 = computed<[number, number][]>(() =>
  (sk.value?.volumes ?? []).flatMap((v, vi) => v.chapters.map((_, ci) => [vi, ci] as [number, number])))

function 章位置(v: number, c: number): number {
  return 章序.value.findIndex(([a, b]) => a === v && b === c)
}

async function 保存(next: Skeleton): Promise<void> {
  error.value = ''
  try {
    sk.value = await putSkeleton(props.name, next)
  } catch (e) {
    报错(e)
    await 加载()
  }
}

function 副本(): Skeleton {
  return JSON.parse(JSON.stringify(sk.value)) as Skeleton
}

async function 生成(强制 = false): Promise<void> {
  if (sk.value?.by === 'author' && !强制) {
    确认中.value = true
    return
  }
  确认中.value = false
  try {
    jobStore.track(await generateSkeleton(props.name))
  } catch (e) {
    报错(e)
  }
}

async function 导出(): Promise<void> {
  try {
    导出结果.value = await exportBook(props.name)
  } catch (e) {
    报错(e)
  }
}

function key(kind: string, v: number, c = -1): string {
  return `${kind}-${v}-${c}`
}

async function 存名字(kind: 'vol' | 'ch', v: number, c = -1): Promise<void> {
  const k = key(kind, v, c)
  const name = (改名.value[k] ?? '').trim()
  改名.value[k] = undefined
  if (!name || !sk.value) return
  const next = 副本()
  if (kind === 'vol') next.volumes[v].title = name
  else next.volumes[v].chapters[c].title = name
  await 保存(next)
}

/** 同卷内跟相邻章交换；卷首章上移挪到上一卷末尾，卷末章下移挪到下一卷开头。
 *  全书第一章 / 最后一章的按钮已经禁用，所以跨卷时相邻卷一定存在。 */
async function 移章(v: number, c: number, dir: -1 | 1): Promise<void> {
  const next = 副本()
  const vols = next.volumes
  const [ch] = vols[v].chapters.splice(c, 1)
  if (dir === -1) {
    if (c > 0) vols[v].chapters.splice(c - 1, 0, ch)
    else vols[v - 1].chapters.push(ch)
  } else if (c < vols[v].chapters.length) {
    vols[v].chapters.splice(c + 1, 0, ch)
  } else {
    vols[v + 1].chapters.unshift(ch)
  }
  await 保存(next)
}

async function 移场景(item: SkItem, dir: -1 | 1): Promise<void> {
  const [v, c] = 选中.value
  const pos = 章位置(v, c)
  const target = 章序.value[pos + dir]
  if (!target) return
  const next = 副本()
  const from = next.volumes[v].chapters[c].items
  const i = from.findIndex((x) => x.type === item.type && x.id === item.id)
  const [moved] = from.splice(i, 1)
  const to = next.volumes[target[0]].chapters[target[1]].items
  if (dir === 1) to.unshift(moved)
  else to.push(moved)
  await 保存(next)
}

async function 删空洞(h: SkHole): Promise<void> {
  const [v, c] = 选中.value
  const next = 副本()
  const items = next.volumes[v].chapters[c].items
  items.splice(items.findIndex((x) => x.type === 'hole' && x.id === h.id), 1)
  await 保存(next)
}

async function 加空洞(): Promise<void> {
  const [v, c] = 选中.value
  const next = 副本()
  const used = new Set<string>()
  for (const vol of next.volumes) for (const ch of vol.chapters) for (const it of ch.items) if (it.type === 'hole') used.add(it.id)
  for (const h of next.unplaced.holes) used.add(h.id)
  let n = used.size + 1
  while (used.has(`H-${String(n).padStart(3, '0')}`)) n++
  next.volumes[v].chapters[c].items.push({ type: 'hole', id: `H-${String(n).padStart(3, '0')}`, task: '（作者新增的空洞，写下要补什么）' })
  await 保存(next)
}

async function 改说明(h: SkHole, task: string): Promise<void> {
  const [v, c] = 选中.value
  const next = 副本()
  const it = next.volumes[v].chapters[c].items.find((x) => x.type === 'hole' && x.id === h.id) as SkHole
  it.task = task
  await 保存(next)
}

async function 放进当前章(sid: string): Promise<void> {
  const [v, c] = 选中.value
  const next = 副本()
  const i = next.unplaced.scenes.findIndex((s) => s.id === sid)
  const [s] = next.unplaced.scenes.splice(i, 1)
  next.volumes[v].chapters[c].items.push({ type: 'scene', id: s.id, thread: s.thread })
  await 保存(next)
}

function 备注(n: SkNote): string {
  if (n.kind === 'undecided') return `去留未定：${n.thread}`
  if (n.kind === 'merge') return `待并入 ${n.into} 改写：${n.thread}`
  return `此处原与被砍的 ${n.thread} 交汇`
}

const 退订 = jobStore.onFinish(() => { void 加载() })
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
  <div class="page">
    <h1>成书骨架 —— 《{{ name }}》</h1>
    <ErrorBox :message="error" />
    <div class="bar">
      <button data-test="生成" :disabled="jobStore.busy" @click="生成()">{{ sk ? '重新生成骨架' : '生成骨架' }}</button>
      <button v-if="sk" data-test="导出" :disabled="jobStore.busy" @click="导出">导出 md / txt</button>
    </div>
    <div v-if="确认中" class="confirm">
      你改过这份骨架，重新生成会覆盖你的手改（旧版本会备份成 骨架.bak.json）。
      <button data-test="确认覆盖" :disabled="jobStore.busy" @click="生成(true)">照样重新生成</button>
      <button @click="确认中 = false">算了</button>
    </div>
    <p v-if="sk?.fallback_chapters" class="warn">模型分章没成功，用了按字数的兜底切法，章名是临时的。</p>
    <div v-if="导出结果" class="export" data-test="导出结果">
      已导出 {{ 导出结果.md }}、{{ 导出结果.txt }}：{{ 导出结果.scenes }} 块场景、{{ 导出结果.holes }} 个空洞<template v-if="导出结果.missing">、{{ 导出结果.missing }} 块缺失</template>。
      <a :href="exportUrl(name, 'md')">下载 md</a> · <a :href="exportUrl(name, 'txt')">下载 txt</a>
    </div>

    <p v-if="没有" class="empty" data-test="空态">还没有骨架。先在取舍看板上定好去留（没想好的线也会先排进来），再生成。</p>

    <div v-if="sk" class="layout">
      <nav class="tree" data-test="卷章树">
        <div v-for="(v, vi) in sk.volumes" :key="vi" class="vol">
          <input v-if="改名[key('vol', vi)] !== undefined" v-model="改名[key('vol', vi)]"
                 @keyup.enter="存名字('vol', vi)" @blur="存名字('vol', vi)" />
          <b v-else @dblclick="改名[key('vol', vi)] = v.title">{{ v.title }}</b>
          <div v-for="(ch, ci) in v.chapters" :key="ci" class="ch" :class="{ on: 选中[0] === vi && 选中[1] === ci }">
            <input v-if="改名[key('ch', vi, ci)] !== undefined" v-model="改名[key('ch', vi, ci)]"
                   :data-test="`章名输入-${vi}-${ci}`" @keyup.enter="存名字('ch', vi, ci)" @blur="存名字('ch', vi, ci)" />
            <span v-else :data-test="`章名-${vi}-${ci}`" @click="选中 = [vi, ci]" @dblclick="改名[key('ch', vi, ci)] = ch.title">{{ ch.title }}</span>
            <span class="ops">
              <button :data-test="`章上移-${vi}-${ci}`" :disabled="jobStore.busy || 章位置(vi, ci) === 0" title="上移" @click="移章(vi, ci, -1)">↑</button>
              <button :data-test="`章下移-${vi}-${ci}`" :disabled="jobStore.busy || 章位置(vi, ci) === 章序.length - 1" title="下移" @click="移章(vi, ci, 1)">↓</button>
            </span>
          </div>
        </div>
      </nav>

      <section v-if="当前章" class="items" data-test="条目">
        <h2>{{ 当前章.title }}</h2>
        <div class="notes">
          <span v-for="(n, i) in 当前章.notes" :key="i" class="tag" :class="n.kind">{{ 备注(n) }}</span>
        </div>
        <template v-for="it in 当前章.items" :key="it.type + it.id">
          <div v-if="it.type === 'scene'" class="scene" :class="{ flagged: it.flag }" :data-test="`场景-${it.id}`">
            <span class="sid">{{ it.id }}</span>
            <span class="thread">{{ it.thread }}</span>
            <span v-if="it.flag === 'missing'" class="why">原稿里已经没有这一块了</span>
            <span v-if="it.flag === 'cut'" class="why">这条线已经在看板上砍掉了</span>
            <span class="ops">
              <button :disabled="jobStore.busy || 章位置(选中[0], 选中[1]) === 0" @click="移场景(it, -1)">移到上一章</button>
              <button :data-test="`下移场景-${it.id}`" :disabled="jobStore.busy || 章位置(选中[0], 选中[1]) === 章序.length - 1" @click="移场景(it, 1)">移到下一章</button>
            </span>
          </div>
          <details v-else class="hole" :data-test="`空洞-${it.id}`" open>
            <summary>空洞 {{ it.id }}</summary>
            <textarea :value="it.task" :disabled="jobStore.busy" @change="改说明(it, ($event.target as HTMLTextAreaElement).value)" />
            <button :data-test="`删空洞-${it.id}`" :disabled="jobStore.busy" @click="删空洞(it)">删掉这个空洞</button>
          </details>
        </template>
        <button :disabled="jobStore.busy" @click="加空洞">在这里加空洞</button>
      </section>
    </div>

    <section v-if="sk && (sk.unplaced.scenes.length || sk.unplaced.holes.length)" class="unplaced" data-test="未定位">
      <h2>未定位</h2>
      <div v-for="s in sk.unplaced.scenes" :key="s.id" class="scene">
        <span class="sid">{{ s.id }}</span><span class="thread">{{ s.thread ?? '' }}</span>
        <span class="why">{{ 原因[s.why] ?? s.why }}</span>
        <button :disabled="jobStore.busy || !当前章" @click="放进当前章(s.id)">放进当前章</button>
      </div>
      <div v-for="h in sk.unplaced.holes" :key="h.id" class="hole-line">空洞 {{ h.id }}：{{ h.task }}</div>
    </section>
  </div>
</template>

<style scoped>
.page{padding:24px}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
.bar{display:flex;gap:8px;margin-bottom:10px}
.confirm{background:var(--amber-soft);color:var(--ink);padding:8px 10px;border-radius:6px;margin-bottom:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.warn{color:var(--amber);font-size:13px}
.export{background:var(--green-soft);padding:8px 10px;border-radius:6px;margin-bottom:10px;font-size:13px}
.empty{color:var(--ink-3)}
.layout{display:grid;grid-template-columns:260px minmax(0,1fr);gap:16px;align-items:start}
.tree{background:var(--panel);border:1px solid var(--line-2);border-radius:8px;padding:10px;font-size:13px}
.vol{margin-bottom:10px}
.vol b{font-family:var(--serif)}
.ch{display:flex;justify-content:space-between;align-items:center;padding:3px 6px;border-radius:4px;cursor:pointer}
.ch.on{background:var(--accent-soft);color:var(--accent)}
.ch .ops button{padding:0 6px}
.items h2{font-size:16px;margin:0 0 6px}
.notes{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.tag{font-size:11px;padding:1px 6px;border-radius:999px;background:var(--sunk);color:var(--ink-2)}
.tag.cut_crossing{background:var(--red-soft);color:var(--red)}
.tag.merge{background:var(--accent-soft);color:var(--accent)}
.scene{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:6px 8px;border-bottom:1px solid var(--line-2);font-size:13px}
.scene.flagged{opacity:.55}
.sid{font-family:var(--mono)}
.thread{color:var(--accent)}
.why{color:var(--ink-3)}
.scene .ops{margin-left:auto;display:flex;gap:4px}
.hole{border:1px solid var(--red);border-radius:6px;padding:6px 8px;margin:6px 0;font-size:13px}
.hole summary{color:var(--red);cursor:pointer}
.hole textarea{width:100%;min-height:60px;margin:6px 0}
.unplaced{margin-top:18px}
.unplaced h2{font-size:15px}
.hole-line{font-size:13px;color:var(--ink-2);padding:4px 0}
</style>
```

`移章` 的两条测试追加到 `SkeletonPage.test.ts`：

```ts
it('章下移：同卷交换；卷末章下移到下一卷开头', async () => {
  const sk = 造骨架()
  sk.volumes.push({ title: '第二卷', chapters: [{ title: '归来', notes: [], items: [] }] })
  vi.spyOn(api, 'getSkeleton').mockResolvedValue(sk)
  const put = vi.spyOn(api, 'putSkeleton').mockImplementation(async (_n, x) => x)
  const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
  await flushPromises()
  await w.find('[data-test="章下移-0-0"]').trigger('click')
  await flushPromises()
  expect(put.mock.calls[0][1].volumes[0].chapters.map((c) => c.title)).toEqual(['龙宫', '开篇'])
  await w.find('[data-test="章下移-0-1"]').trigger('click')
  await flushPromises()
  const last = put.mock.calls[1][1]
  expect(last.volumes[0].chapters.map((c) => c.title)).toEqual(['龙宫'])
  expect(last.volumes[1].chapters.map((c) => c.title)).toEqual(['开篇', '归来'])
})

it('全书第一章不能上移、最后一章不能下移', async () => {
  vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
  const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
  await flushPromises()
  expect(w.find('[data-test="章上移-0-0"]').attributes('disabled')).toBeDefined()
  expect(w.find('[data-test="章下移-0-1"]').attributes('disabled')).toBeDefined()
})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test && npm run typecheck && npm run build`
Expected: 全绿、build 通过

- [ ] **Step 5: 提交**

```bash
git add web/src/pages/SkeletonPage.vue web/src/pages/SkeletonPage.test.ts
git commit -m "feat(web): 成书骨架页：卷章树、条目编辑、未定位、生成与导出"
```

---

# 里程碑 5：验收

### Task 20: tools/eval_skeleton.py——验收硬判据

**Files:**
- Create: `tools/eval_skeleton.py`
- Test: `tests/test_eval_skeleton.py`

spec 第 13 节的程序硬判据：
1. 导出的书里每块参与场景（主版本）**恰好出现一次**（按 md 里的 `<!-- S-xxxx -->` 注释数）。
2. 导出场景顺序跟原书顺序的 Kendall τ ≥ 0.9（原书位置用 `tools/eval_threads.truth_positions`，τ 用 `tools/eval_threads.kendall_tau_b`；只算骨架正文里的场景，不算「附：未定位」）。
3. 骨架里的空洞数 = 能定位的缺口数（参与线的、至少一端锚点在序列里的；直接复用 `skeleton_order.build_sequence` + `insert_holes` 重算一遍比对）。
4. 砍掉的线（`--cut` 传入）：导出里不含它的场景，也不含只属于它的缺口；程序化影响里包含它在 `intersections` 里的全部交汇点。
5. 骨架里空洞说明、AI 建议理由、伏笔影响里的场景编号 0 条编造（都得是书里真实存在的场景编号）。

- [ ] **Step 1: 写失败的测试** `tests/test_eval_skeleton.py`

```python
from ligaotai.export import export_book
from ligaotai.fsutil import write_json
from tools.eval_skeleton import check_book


def _sk(items, unplaced=None):
    return {"generated": "x", "by": "program", "volumes": [{"title": "卷", "chapters": [
        {"title": "章", "items": items, "notes": []}]}], "unplaced": unplaced or {"scenes": [], "holes": []}}


def test_全留_每块恰好一次_空洞数对得上_编号不编造(book_with_threads):
    b = book_with_threads
    items = [{"type": "scene", "id": "S-0001", "thread": "L-001"},
             {"type": "hole", "id": "H-001", "gap": "Q-001", "task": "补 [S-0002]"},
             *[{"type": "scene", "id": f"S-000{i}", "thread": "L-001" if i < 4 else "L-002"} for i in range(2, 6)]]
    write_json(b.skeleton_path, _sk(items))
    export_book(b)
    r = check_book(b, truth=None, cut=[])
    assert r["each_once"] is True and r["duplicates"] == [] and r["missing"] == []
    assert r["holes_expected"] == 1 and r["holes_in_skeleton"] == 1
    assert r["fabricated_refs"] == []


def test_重复和漏掉_编造编号都要报出来(book_with_threads):
    b = book_with_threads
    items = [{"type": "scene", "id": "S-0001", "thread": "L-001"},
             {"type": "scene", "id": "S-0001", "thread": "L-001"},
             {"type": "hole", "id": "H-001", "gap": "Q-001", "task": "补 [S-0999]"}]
    write_json(b.skeleton_path, _sk(items))
    export_book(b)
    r = check_book(b, truth=None, cut=[])
    assert r["each_once"] is False
    assert r["duplicates"] == ["S-0001"]
    assert r["missing"] == ["S-0002", "S-0003", "S-0004", "S-0005"]
    assert r["fabricated_refs"] == ["S-0999"]


def test_砍掉的线不许出现(book_with_threads):
    b = book_with_threads
    items = [{"type": "scene", "id": f"S-000{i}", "thread": "L-001"} for i in range(1, 4)] + \
            [{"type": "scene", "id": "S-0004", "thread": "L-002"}]
    write_json(b.skeleton_path, _sk(items))
    write_json(b.board_path, {"cards": {"L-002": {"col": "cut", "merge_into": None, "note": ""}}})
    export_book(b)
    r = check_book(b, truth=None, cut=["L-002"])
    assert r["cut_leaks"] == ["S-0004"]
```

`truth` 传 `None` 时不算 τ（`r["tau"]` 为 `None`）；真跑时由 `main()` 按 `--key` 答案文件算。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest -q tests/test_eval_skeleton.py`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现** `tools/eval_skeleton.py`

```python
"""计划④ 验收：骨架 + 导出的程序硬判据（spec 第 13 节）。

用法：
    uv run python tools/eval_skeleton.py --library data/验收书库 --book <书文件夹名> \
        --folder 乱稿-雪月梅-c --key data/乱稿-雪月梅-c-答案.json [--cut L-002] --report data/验收-骨架.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ligaotai.archive import refs_in  # noqa: E402
from ligaotai.book import Book, open_book  # noqa: E402
from ligaotai.export import export_path  # noqa: E402
from ligaotai.fsutil import read_json, write_json  # noqa: E402
from ligaotai.scenes import load_scenes  # noqa: E402
from ligaotai.skeleton import load_skeleton, scene_info  # noqa: E402
from ligaotai.skeleton_order import build_sequence, insert_holes  # noqa: E402
from ligaotai.threads_ops import load_threads  # noqa: E402
from ligaotai.triage import columns, non_main_versions  # noqa: E402
from tools.eval_threads import kendall_tau_b, truth_positions  # noqa: E402

_MARK = re.compile(r"^<!-- (S-\d{4,}) -->$", re.M)


def _body_md(md: str) -> str:
    """去掉书末「附：未定位」一节，只看正文。"""
    cut = md.find("\n# 附：未定位")
    return md if cut < 0 else md[:cut]


def check_book(book: Book, truth: dict | None, cut: list[str]) -> dict:
    threads = load_threads(book)
    cols = columns(book, threads)
    info = scene_info(book)
    drop = non_main_versions(book) | {sid for sid, x in info.items() if x["removed"]}
    seq, unplaced = build_sequence(threads, cols, drop)
    items, holes_unplaced = insert_holes(seq, threads.get("gaps") or [], cols)
    expected = [x["id"] for x in seq] + [u["id"] for u in unplaced]

    md = export_path(book, "md").read_text(encoding="utf-8")
    all_ids = _MARK.findall(md)
    body_ids = _MARK.findall(_body_md(md))
    counts: dict[str, int] = {}
    for s in all_ids:
        counts[s] = counts.get(s, 0) + 1
    duplicates = sorted(s for s, n in counts.items() if n > 1)
    missing = sorted(s for s in expected if s not in counts)

    thread_of = {sid: t["id"] for t in threads.get("threads") or [] for sid in t.get("scenes") or []}
    cut_leaks = sorted(s for s in counts if thread_of.get(s) in set(cut))

    sk = load_skeleton(book)
    holes_in_skeleton = sum(1 for v in sk["volumes"] for ch in v["chapters"] for it in ch["items"]
                            if it.get("type") == "hole")
    known = {s.id for s in load_scenes(book)}
    texts = [it.get("task", "") for v in sk["volumes"] for ch in v["chapters"] for it in ch["items"]
             if it.get("type") == "hole"]
    adv = read_json(book.advice_path, {}) or {}
    texts += [i.get("reason", "") for i in adv.get("items") or []]
    imp = read_json(book.impact_path, {}) or {}
    for x in imp.values():
        texts.append(x.get("remedy", ""))
        texts += [f"[{p.get('planted')}] [{p.get('resolved')}]" for p in x.get("pairs") or []]
    fabricated = sorted({r for t in texts for r in refs_in(str(t)) if r not in known})

    tau = None
    if truth:
        ranked = [s for s in body_ids if s in truth]
        tau, _ = kendall_tau_b(list(range(len(ranked))), [truth[s] for s in ranked])

    return {
        "each_once": not duplicates and not missing,
        "duplicates": duplicates, "missing": missing,
        "holes_expected": sum(1 for i in items if i["type"] == "hole"),
        "holes_in_skeleton": holes_in_skeleton,
        "holes_unplaced_expected": len(holes_unplaced),
        "cut_leaks": cut_leaks,
        "fabricated_refs": fabricated,
        "tau": tau,
        "scenes_in_body": len(body_ids),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="check skeleton/export against the acceptance criteria")
    ap.add_argument("--library", default="data/验收书库")
    ap.add_argument("--book", required=True)
    ap.add_argument("--folder", help="乱稿文件夹名（算 τ 用）")
    ap.add_argument("--key", help="答案文件（算 τ 用）")
    ap.add_argument("--cut", action="append", default=[])
    ap.add_argument("--report", default="data/验收-骨架.json")
    a = ap.parse_args(argv)
    book = open_book(Path(a.library), a.book)
    truth = None
    if a.key and a.folder:
        key = json.loads(Path(a.key).read_text(encoding="utf-8"))
        truth = truth_positions(book, key, Path(a.folder).name)
    r = check_book(book, truth, a.cut)
    r["pass"] = (r["each_once"] and r["holes_expected"] == r["holes_in_skeleton"] and not r["cut_leaks"]
                 and not r["fabricated_refs"] and (r["tau"] is None or r["tau"] >= 0.9))
    write_json(Path(a.report), r)
    print(json.dumps({k: r[k] for k in ("pass", "each_once", "tau", "holes_expected", "holes_in_skeleton")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
```

注意：`each_once` 判据里的 `missing` 是「**应该参与**但导出里一次都没有」——作者手动把场景拖出骨架是合法编辑，验收时用的是**程序刚生成、没手改过**的骨架，所以这条在验收场景下成立。测试 1 里 `S-0006`（设定笔记）不在任何线里，也不在 `unassigned` 里，所以不算「应该参与」。

`tests/test_tools_scripts.py` 守着「`tools/` 下脚本能 `uv run python tools/xxx.py` 直接跑」，跑一下确认新脚本也过。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q tests/test_eval_skeleton.py tests/test_tools_scripts.py`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tools/eval_skeleton.py tests/test_eval_skeleton.py
git commit -m "feat: 计划④ 验收脚本：每块恰好一次、顺序 τ、空洞数、砍线泄漏、编号编造"
```

### Task 21: 文档

**Files:**
- Modify: `README.md`、`docs/superpowers/specs/2026-09-10-ligaotai-design.md`、`docs/已知问题与待办.md`

- [ ] **Step 1: README**
  - 「已经能做的」末尾那句「所有数据都是书文件夹里的 md / json，用 Obsidian 也能直接打开。」改成「所有数据都是书文件夹里的 md / json，普通文本编辑器就能打开。」
  - 进度表 ④ 那行改成：`| ④ | 二期：矛盾裁决、取舍看板、成书骨架、导出 md / txt | ✅ 完成 |`（验收过了再改；没过就写「开发完成，验收中」）
  - 「已经能做的」加一条「**取舍**（二期）」：裁决矛盾写进定稿设定；看板四列定去留，AI 给建议、拖进砍掉 / 合并时列出会断掉的交汇点、独有人物、伏笔；程序按故事时间排出骨架、模型分卷分章并给每个空洞写补写说明，骨架可以手改；按骨架导出 md / txt。
  - 「界面」一节的页面清单加「取舍看板」「成书骨架」两行，矛盾那行改成「裁决：以某个值为准 / 自己写 / 先放着」。
- [ ] **Step 2: 总 spec**
  - 第 4 节存储那条「每本书一个文件夹，用 Obsidian 也能直接打开。」改成「每本书一个文件夹，普通文本编辑器就能打开。」
  - 第 7 章标题下加一句：「细化设计见 `2026-09-22-ligaotai-plan4-triage-design.md`（计划④），冲突处以它为准。」
  - 7.2 末尾加一句：「裁决写在 `矛盾.json` 每组的 `verdict`（唯一真源），`定稿设定.json` 由它派生。」
- [ ] **Step 3: 待办文档**：新增「计划④ 之后留下的」一节，至少写：
  - 程序化影响第 3 项（别处引用）只用独有人物的叫法匹配，漏报在所难免；
  - 骨架编辑只有上下移、没有拖拽；
  - 导出不做 docx / EPUB（spec 范围外）。
- [ ] **Step 4: 自查**：`git grep -n "Obsidian" -- README.md docs/superpowers/specs/2026-09-10-ligaotai-design.md` 应该没有结果。
- [ ] **Step 5: 提交**

```bash
git add README.md docs/superpowers/specs/2026-09-10-ligaotai-design.md docs/已知问题与待办.md
git commit -m "docs: 二期取舍写进 README 与总设计；去掉对 Obsidian 的绑定"
```

### Task 22: 真书验收（主会话自己做，要看图、要花钱）

**这一步不派子代理。** 照计划③ 的做法：临时书库拷验收书的副本，不碰真书库。

- [ ] **Step 1: 准备**：把 `data/验收书库/验收-实体-乱稿-雪月梅-c-s7` 拷一份到临时书库（照计划③ 的 `serve_demo.py`），起服务。
- [ ] **Step 2: 验 key**：先发一次 5 token 的 ping（设置页「测试连接」或 `/api/config/test`），401 就停下找作者换 key。
- [ ] **Step 3: 全留跑一遍**：看板全部设「保留」→ 让 AI 给建议 → 生成骨架 → 导出。跑 `tools/eval_skeleton.py --cut` 不传，记下 τ、每块一次、空洞数、编号编造。
- [ ] **Step 4: 砍 L-002 跑一遍**：看板把 L-002 拖进砍掉 → 检查伏笔影响 → 重新生成骨架 → 导出 → `eval_skeleton.py --cut L-002`。核：程序化影响里有 `S-0001` `S-0066` `S-0002` 三个交汇点（Task 9 算出来的）。
- [ ] **Step 5: 裁决**：在矛盾页对三组严重矛盾各做一种裁决（以某值为准 / 自己写 / 先放着），核 `定稿设定.json`。
- [ ] **Step 6: 截图**：看板、骨架、矛盾（裁决后）三页 + 影响展开 + 导出结果，浅色 / 深色 / 1000px 窄窗口，Console 无报错；照计划③ 验收的做法先验报警器本身。
- [ ] **Step 7: 作者抽查**：把 L-002 的伏笔影响、分卷分章、5 个空洞说明拿给作者看，记下判定原话。
- [ ] **Step 8: 验收记录** `docs/验收记录/2026-XX-XX-计划4-取舍.md`：硬判据表、截图抓到的问题、没验到的情形、作者判定；截图放 `docs/验收记录/图/计划4/`（带本机路径的设置页不进仓库）。
- [ ] **Step 9: 做完问作者：合进 master？推 GitHub？**（推前照 9-22 的做法清历史里的作者称呼：只改 `origin/master..master`，改写后树哈希必须跟改写前一样。）
