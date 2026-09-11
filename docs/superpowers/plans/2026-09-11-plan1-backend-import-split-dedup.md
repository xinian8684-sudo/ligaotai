# 理稿台 计划①：后端骨架 + 导入 / 切场景 / 查重 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 做出理稿台的 Python 后端骨架，跑通一期流水线前 3 步（导入、切场景、查重，都不花 AI 钱），并用「人为弄乱的《西游记》」验证查重召回率 ≥ 90%。

**Architecture:** FastAPI 服务只监听 127.0.0.1；每本书是书库里的一个文件夹，所有数据都是 md/json 文件，没有数据库。流水线每一步是一个纯函数式的 `run_xxx(book, progress)`，由单线程任务队列（JobRunner）在后台执行，一次只跑一个。切场景和查重的核心算法是不碰文件的纯函数，单独测试。

**Tech Stack:** Python 3.11、uv、FastAPI、pydantic 2、charset-normalizer、python-docx、PyYAML、pytest、httpx（测试用）。

**设计依据：** `docs/superpowers/specs/2026-09-10-ligaotai-design.md` 第 4、5、6 章（步骤 1–3）、第 10、11 章。

**这份计划覆盖 / 不覆盖：**
- 覆盖：spec 步骤 1 导入、步骤 2 切场景、步骤 3 查重；5.1 场景编号与过期标记；book.json 流水线状态与下游过期传播；任务队列；这 3 步用到的 API；弄乱脚本和查重验收。
- 不覆盖（后续计划）：模型接入与步骤 4–7（计划②）、前端页面和 `启动理稿台.bat`（计划③）、二期（计划④）。

**跟 spec 的三处实现偏差（已想清楚，执行时照这里做）：**
1. **查重不用 MinHash + LSH，改用「倒排索引精确计数」**。理由：结果确定（测试可复现）；同一趟就能算出 Jaccard 和包含度，不用再引入 LSHEnsemble；1000 多块的规模下内存和速度都够。所以不装 `datasketch`。
2. **新增 `原稿清单.json`**（spec 数据布局里没有），记录每个导入文件的哈希、编码、字数、原始修改时间。放进 book.json 会让这个频繁改写的文件变得很大，所以单独存。
3. **分隔符字符集先写死在 `split.py` 里**。spec 说「规则表可配置」，本计划按书可调的只有：连续空行数、超长上限、切点目标、碎片上限。等真稿里碰到没收录的分隔符，再决定是加进字符集，还是做成可配置。

**已知局限（写进验收记录，不在本计划解决）：**
- 查重以「场景块」为单位。同一场景的两个版本如果被切在很不一样的位置，可能认不出来。验收脚本会把漏掉的列出来。
- 同一个文件中间插入一块新内容，会让它后面的块全部被标成「改动过」（块的身份是「来源文件 + 第几块」）。
- 繁体 Big5 编码的 txt 会被误判成 GB18030。作者的稿子是简体，暂不处理。

---

## 文件结构

```
ligaotai/
  pyproject.toml              依赖和 pytest 配置
  .gitignore
  src/ligaotai/
    __init__.py               版本号
    __main__.py               python -m ligaotai 启动服务
    fsutil.py                 原子写入、安全文件名、自然排序、路径越界检查
    config.py                 应用级配置 config.json（书库目录）
    book.py                   书：建书/列书/打开、book.json、流水线状态、下游过期、默认参数
    readers.py                读 txt/md/docx，识别编码
    importer.py               步骤 1 导入
    split.py                  切场景算法（纯函数，不碰文件）
    scenes.py                 场景文件格式、读写、步骤 2（切场景 + 编号对账）
    dedup.py                  查重算法 + 步骤 3 + 作者改主版本
    jobs.py                   后台任务队列
    api.py                    FastAPI 应用
  tests/
    conftest.py
    test_fsutil.py test_config.py test_book.py test_readers.py test_importer.py
    test_split.py test_scenes.py test_dedup.py test_jobs.py test_api.py
    test_scramble.py          弄乱脚本 + 端到端（合成小书，不联网）
  tools/
    __init__.py
    scramble.py               把一本书弄乱，生成带标准答案的乱稿
    eval_dedup.py             导入 → 切 → 查重 → 对照答案出报告
  data/                       （gitignore）西游记原文、乱稿、验收报告
  docs/验收记录/               验收结果（进 git）
```

**路径约定：** 所有命令都在仓库根目录下执行，用 Git Bash。

**Windows 注意：** 终端输出中文会乱码。测试断言和脚本打印一律只打 ASCII；要看中文结果就写成文件再用 Read 工具读。

---

## Task 1: 项目脚手架

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/ligaotai/__init__.py`
- Create: `tools/__init__.py`
- Test: `tests/test_smoke.py`

（`tests/conftest.py` 依赖 `ligaotai.book`，放到 Task 4 再建。）

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "ligaotai"
version = "0.1.0"
description = "理稿台：把乱手稿理清、取舍、补写成书的本地工作台"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "pydantic>=2.7",
  "charset-normalizer>=3.3",
  "python-docx>=1.1",
  "pyyaml>=6.0",
]

[dependency-groups]
dev = ["pytest>=8", "httpx>=0.27"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ligaotai"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src", "."]
```

- [ ] **Step 2: 写 .gitignore**

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
config.json
书库/
data/
```

- [ ] **Step 3: 写包入口和空的 tools 包**

`src/ligaotai/__init__.py`：
```python
"""理稿台后端。"""

__version__ = "0.1.0"
```

`tools/__init__.py`：空文件（让 `tools` 能被测试 import）。

- [ ] **Step 4: 写冒烟测试**

`tests/test_smoke.py`：
```python
import ligaotai


def test_version():
    assert ligaotai.__version__ == "0.1.0"
```

- [ ] **Step 5: 装依赖并跑测试**

Run: `uv sync && uv run pytest -q`
Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .gitignore src/ligaotai/__init__.py tools/__init__.py tests/test_smoke.py
git commit -m "chore: 项目脚手架（uv + pytest）"
```

---

## Task 2: fsutil 文件小工具

**Files:**
- Create: `src/ligaotai/fsutil.py`
- Test: `tests/test_fsutil.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_fsutil.py`：
```python
import pytest

from ligaotai.fsutil import (
    atomic_write_text,
    ensure_within,
    natural_key,
    read_json,
    safe_name,
    write_json,
)


def test_atomic_write_roundtrip_and_no_temp_left(tmp_path):
    p = tmp_path / "sub" / "a.md"
    atomic_write_text(p, "第一行\n第二行")
    assert p.read_text(encoding="utf-8") == "第一行\n第二行"
    assert [x.name for x in p.parent.iterdir()] == ["a.md"]


def test_atomic_write_keeps_lf(tmp_path):
    p = tmp_path / "a.txt"
    atomic_write_text(p, "a\nb")
    assert p.read_bytes() == b"a\nb"


def test_json_roundtrip_keeps_chinese(tmp_path):
    p = tmp_path / "x.json"
    write_json(p, {"名字": "林清"})
    assert "林清" in p.read_text(encoding="utf-8")
    assert read_json(p) == {"名字": "林清"}


def test_read_json_default_when_missing(tmp_path):
    assert read_json(tmp_path / "none.json", {"a": 1}) == {"a": 1}


def test_safe_name():
    assert safe_name('我的:书/第一部?') == "我的_书_第一部_"
    with pytest.raises(ValueError):
        safe_name("  ..  ")


def test_natural_key_sorts_numbers_as_numbers():
    names = ["片段10.txt", "片段2.txt", "片段1.txt"]
    assert sorted(names, key=natural_key) == ["片段1.txt", "片段2.txt", "片段10.txt"]


def test_ensure_within(tmp_path):
    base = tmp_path / "book"
    base.mkdir()
    assert ensure_within(base, base / "a" / "b.md") == (base / "a" / "b.md").resolve()
    with pytest.raises(ValueError):
        ensure_within(base, base / ".." / "evil.md")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_fsutil.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'ligaotai.fsutil'`

- [ ] **Step 3: 实现**

`src/ligaotai/fsutil.py`：
```python
"""文件小工具：原子写入、JSON 读写、安全文件名、自然排序、路径越界检查。"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def atomic_write_text(path: Path, text: str) -> None:
    """先写临时文件再替换，写到一半断电也不会留下半截文件。统一用 LF 换行。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        # Windows 上目标文件被 Obsidian / 杀毒软件短暂占用时 replace 会失败，重试几次
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def safe_name(name: str) -> str:
    """把书名等变成能当文件夹名的字符串。"""
    cleaned = _INVALID_CHARS.sub("_", name).strip().strip(".").strip()
    if not cleaned:
        raise ValueError("名字不能为空")
    return cleaned


def natural_key(s: str) -> list:
    """自然排序：片段2 排在 片段10 前面。"""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s)]


def ensure_within(base: Path, target: Path) -> Path:
    """确认 target 在 base 里面，防止 ../ 越界。返回解析后的绝对路径。"""
    base_r = Path(base).resolve()
    target_r = Path(target).resolve()
    if target_r != base_r and base_r not in target_r.parents:
        raise ValueError(f"路径越界：{target}")
    return target_r
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_fsutil.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/fsutil.py tests/test_fsutil.py
git commit -m "feat: fsutil 原子写入/安全文件名/自然排序"
```

---

## Task 3: 应用配置 config.py

**Files:**
- Create: `src/ligaotai/config.py`
- Test: `tests/test_config.py`

本计划只需要「书库目录」一项。模型相关的配置项在计划②加。`config.json` 放在应用目录（仓库根目录），不放进书文件夹，这样分享书文件夹不会带出 key。

- [ ] **Step 1: 写失败的测试**

`tests/test_config.py`：
```python
from ligaotai.config import AppConfig, library_path, load_config, save_config


def test_default_when_no_file(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.library_dir == ""
    assert library_path(cfg, tmp_path) == tmp_path / "书库"


def test_save_and_load(tmp_path):
    save_config(AppConfig(library_dir=str(tmp_path / "别处")), tmp_path)
    cfg = load_config(tmp_path)
    assert library_path(cfg, tmp_path) == tmp_path / "别处"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

`src/ligaotai/config.py`：
```python
"""应用级配置：<应用目录>/config.json。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .fsutil import read_json, write_json

# src/ligaotai/config.py → parents[2] 是仓库根目录
APP_DIR = Path(__file__).resolve().parents[2]
CONFIG_NAME = "config.json"


class AppConfig(BaseModel):
    library_dir: str = ""


def load_config(app_dir: Path = APP_DIR) -> AppConfig:
    return AppConfig(**read_json(Path(app_dir) / CONFIG_NAME, {}))


def save_config(cfg: AppConfig, app_dir: Path = APP_DIR) -> None:
    write_json(Path(app_dir) / CONFIG_NAME, cfg.model_dump())


def library_path(cfg: AppConfig, app_dir: Path = APP_DIR) -> Path:
    return Path(cfg.library_dir) if cfg.library_dir else Path(app_dir) / "书库"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_config.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/config.py tests/test_config.py
git commit -m "feat: 应用配置（书库目录）"
```

## Task 4: 书与流水线状态 book.py

**Files:**
- Create: `src/ligaotai/book.py`
- Create: `tests/conftest.py`
- Test: `tests/test_book.py`

要点：
- 一本书 = 书库里一个文件夹，文件夹名 = `safe_name(书名)`。
- `book.json` 记录：书名、创建时间、本书参数（切场景、查重的阈值，可以按书调）、7 步流水线每一步的状态。
- 状态有 5 种：`todo`（没跑过）、`running`、`done`、`failed`、`outdated`（上游变了，结果要重跑）。
- 某一步跑完且**确实改动了数据**（`changed=True`），它下游所有 `done` 的步骤变成 `outdated`。只是重跑一遍、结果没变，就不影响下游。
- 读改写 book.json 用一把进程级的锁，因为后台任务线程和 API 线程都会写它。

- [ ] **Step 1: 写 conftest 和失败的测试**

`tests/conftest.py`：
```python
import pytest

from ligaotai.book import create_book


@pytest.fixture
def library(tmp_path):
    lib = tmp_path / "书库"
    lib.mkdir()
    return lib


@pytest.fixture
def book(library):
    return create_book(library, "测试书")
```

`tests/test_book.py`：
```python
import pytest

from ligaotai.book import (
    DEFAULT_SETTINGS,
    STEPS,
    create_book,
    list_books,
    open_book,
    recover_interrupted,
)


def test_create_book_writes_meta(library):
    b = create_book(library, "我的书")
    meta = b.load()
    assert meta["title"] == "我的书"
    assert set(meta["steps"]) == set(STEPS)
    assert all(s["status"] == "todo" for s in meta["steps"].values())


def test_create_duplicate_raises(library):
    create_book(library, "我的书")
    with pytest.raises(FileExistsError):
        create_book(library, "我的书")


def test_open_book(library):
    create_book(library, "我的书")
    assert open_book(library, "我的书").load()["title"] == "我的书"
    with pytest.raises(FileNotFoundError):
        open_book(library, "没有这本")
    with pytest.raises(ValueError):
        open_book(library, "../我的书")


def test_list_books(library):
    create_book(library, "乙书")
    create_book(library, "甲书")
    assert sorted(b["title"] for b in list_books(library)) == ["乙书", "甲书"]


def test_settings_default_and_override(book):
    assert book.settings() == DEFAULT_SETTINGS
    book.update(lambda d: d["settings"].update(split_max_chars=4000))
    s = book.settings()
    assert s["split_max_chars"] == 4000
    assert s["dedup_jaccard"] == DEFAULT_SETTINGS["dedup_jaccard"]


def test_changed_step_outdates_done_downstream_only(book):
    book.set_step("split", "done")
    book.set_step("dedup", "done")
    book.set_step("import", "done", {"added": 3}, changed=True)
    assert book.step("import")["summary"] == {"added": 3}
    assert book.step("split")["status"] == "outdated"
    assert book.step("dedup")["status"] == "outdated"
    assert book.step("cards")["status"] == "todo"


def test_unchanged_step_does_not_outdate(book):
    book.set_step("split", "done")
    book.set_step("import", "done", changed=False)
    assert book.step("split")["status"] == "done"


def test_set_step_rejects_unknown(book):
    with pytest.raises(ValueError):
        book.set_step("nope", "done")
    with pytest.raises(ValueError):
        book.set_step("split", "weird")


def test_recover_interrupted(library, book):
    book.set_step("split", "running")
    fixed = recover_interrupted(library)
    assert fixed == ["测试书:split"]
    assert book.step("split")["status"] == "failed"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_book.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'ligaotai.book'`

- [ ] **Step 3: 实现**

`src/ligaotai/book.py`：
```python
"""书：书库里的一个文件夹。book.json 记元信息、本书参数、流水线各步状态。"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from .fsutil import ensure_within, natural_key, read_json, safe_name, write_json

STEPS = ["import", "split", "dedup", "cards", "entities", "threads", "archive"]
STEP_LABELS = {
    "import": "导入",
    "split": "切场景",
    "dedup": "查重",
    "cards": "场景卡",
    "entities": "实体合并",
    "threads": "归线排序",
    "archive": "档案+矛盾+地图",
}
STATUSES = ("todo", "running", "done", "failed", "outdated")

DEFAULT_SETTINGS = {
    "split_max_chars": 5000,     # 超过就再切
    "split_target_chars": 3000,  # 再切时尽量切在这个位置附近
    "split_blank_lines": 2,      # 连续这么多个空行算场景分隔
    "fragment_max_chars": 300,   # 短于这个的块标成「碎片」候选
    "dedup_shingle": 5,          # 查重用几个字一组
    "dedup_jaccard": 0.5,        # 相似度达到这个算同一场景的不同版本
    "dedup_containment": 0.8,    # 短块有这么多内容出现在长块里，也算同一组
    "dedup_min_shingles": 100,   # 太短的块（约 100 字以下）不参与查重
    "dedup_common_df": 20,       # 出现在超过这么多块里的字串当套话，不计数
}

_lock = threading.RLock()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Book:
    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def meta_path(self) -> Path:
        return self.root / "book.json"

    @property
    def originals_dir(self) -> Path:
        return self.root / "原稿"

    @property
    def manifest_path(self) -> Path:
        return self.root / "原稿清单.json"

    @property
    def scenes_dir(self) -> Path:
        return self.root / "场景"

    @property
    def versions_path(self) -> Path:
        return self.root / "版本组.json"

    def load(self) -> dict:
        data = read_json(self.meta_path)
        if data is None:
            raise FileNotFoundError(self.meta_path)
        return data

    def update(self, fn: Callable[[dict], None]) -> dict:
        """在锁里读 → 改 → 写 book.json。"""
        with _lock:
            data = self.load()
            fn(data)
            write_json(self.meta_path, data)
            return data

    def settings(self) -> dict:
        return {**DEFAULT_SETTINGS, **self.load().get("settings", {})}

    def step(self, name: str) -> dict:
        return self.load()["steps"][name]

    def set_step(
        self, name: str, status: str, summary: dict | None = None, changed: bool = False
    ) -> None:
        if name not in STEPS:
            raise ValueError(f"没有这一步：{name}")
        if status not in STATUSES:
            raise ValueError(f"没有这种状态：{status}")

        def fn(data: dict) -> None:
            st = data["steps"][name]
            st["status"] = status
            st["updated"] = now_iso()
            if summary is not None:
                st["summary"] = summary
            if changed:
                _outdate_after(data, name)

        self.update(fn)

    def mark_downstream_outdated(self, name: str) -> None:
        self.update(lambda data: _outdate_after(data, name))


def _outdate_after(data: dict, name: str) -> None:
    for later in STEPS[STEPS.index(name) + 1 :]:
        st = data["steps"][later]
        if st["status"] == "done":
            st["status"] = "outdated"
            st["updated"] = now_iso()


def _new_meta(title: str) -> dict:
    return {
        "schema": 1,
        "title": title,
        "created": now_iso(),
        "settings": {},
        "steps": {s: {"status": "todo", "updated": None, "summary": {}} for s in STEPS},
    }


def create_book(library: Path, title: str) -> Book:
    root = Path(library) / safe_name(title)
    if root.exists():
        raise FileExistsError(title)
    root.mkdir(parents=True)
    write_json(root / "book.json", _new_meta(title))
    return Book(root)


def open_book(library: Path, name: str) -> Book:
    if name != safe_name(name):
        raise ValueError(f"书名不合法：{name}")
    root = ensure_within(library, Path(library) / name)
    if not (root / "book.json").exists():
        raise FileNotFoundError(name)
    return Book(root)


def list_books(library: Path) -> list[dict]:
    lib = Path(library)
    if not lib.exists():
        return []
    out = []
    for d in sorted(lib.iterdir(), key=lambda p: natural_key(p.name)):
        meta = read_json(d / "book.json") if d.is_dir() else None
        if meta:
            out.append({"name": d.name, "title": meta["title"], "created": meta["created"]})
    return out


def recover_interrupted(library: Path) -> list[str]:
    """启动时调用：上次关机或崩溃时还标着 running 的步骤改成 failed。"""
    fixed = []
    for info in list_books(library):
        b = Book(Path(library) / info["name"])
        for s in STEPS:
            if b.step(s)["status"] == "running":
                b.set_step(s, "failed", {"error": "上次运行被中断，请重跑"})
                fixed.append(f"{info['name']}:{s}")
    return fixed
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_book.py -q`
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/book.py tests/conftest.py tests/test_book.py
git commit -m "feat: 书与流水线状态（下游过期传播）"
```

## Task 5: 读原稿 readers.py

**Files:**
- Create: `src/ligaotai/readers.py`
- Test: `tests/test_readers.py`

要点：
- 编码识别顺序：带 BOM 的按 BOM → 严格 UTF-8 → 严格 GB18030（GBK 的超集，老 Windows 记事本存的中文基本都是它）→ charset-normalizer 兜底。先试严格解码，是因为短文本上 charset-normalizer 容易把 GBK 认错。
- 换行统一成 `\n`，去掉开头的 BOM 字符。后面所有「位置」都按这个统一后的文本算。
- docx：逐段取文字，标题样式（Heading N / 标题 N / Title）的段落转成 Markdown `#` 标题，这样切场景时走同一条标题规则。表格不取。

- [ ] **Step 1: 写失败的测试**

`tests/test_readers.py`：
```python
from docx import Document

from ligaotai.readers import SUPPORTED, detect_encoding, read_text

TEXT = "林清年方十六，住在青州城外。那一年雪下得很大。\n第二段。"


def test_supported():
    assert SUPPORTED == {".txt", ".md", ".docx"}


def test_utf8(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(TEXT.encode("utf-8"))
    assert read_text(p) == (TEXT, "utf-8")


def test_utf8_bom_removed(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(TEXT.encode("utf-8-sig"))
    text, enc = read_text(p)
    assert enc == "utf-8-sig"
    assert text == TEXT


def test_gbk(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes((TEXT * 3).encode("gbk"))
    assert read_text(p) == (TEXT * 3, "gb18030")


def test_utf16_bom(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(TEXT.encode("utf-16"))
    text, enc = read_text(p)
    assert enc == "utf-16"
    assert text == TEXT


def test_crlf_normalized(tmp_path):
    p = tmp_path / "a.md"
    p.write_bytes("第一行\r\n第二行\r第三行".encode("utf-8"))
    assert read_text(p)[0] == "第一行\n第二行\n第三行"


def test_ascii_is_utf8():
    assert detect_encoding(b"hello") == "utf-8"


def test_docx_headings_become_markdown(tmp_path):
    doc = Document()
    doc.add_heading("全书名", level=0)
    doc.add_heading("第一章 开端", level=1)
    doc.add_paragraph("正文一")
    doc.add_paragraph("")
    doc.add_heading("小节", level=2)
    doc.add_paragraph("正文二")
    p = tmp_path / "a.docx"
    doc.save(str(p))
    text, enc = read_text(p)
    assert enc == "docx"
    assert text == "# 全书名\n# 第一章 开端\n正文一\n\n## 小节\n正文二"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_readers.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

`src/ligaotai/readers.py`：
```python
"""读原稿：txt / md 自动识别编码；docx 取段落，标题样式转成 Markdown #。"""

from __future__ import annotations

import codecs
from pathlib import Path

from charset_normalizer import from_bytes
from docx import Document

SUPPORTED = {".txt", ".md", ".docx"}


def detect_encoding(data: bytes) -> str:
    if data.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    for enc in ("utf-8", "gb18030"):
        try:
            data.decode(enc)
            return enc
        except UnicodeDecodeError:
            pass
    best = from_bytes(data).best()
    return best.encoding if best else "utf-8"


def _heading_level(style_name: str) -> int:
    """Word 段落样式名 → 标题级别；不是标题返回 0。"""
    n = (style_name or "").strip().lower()
    if n == "title":
        return 1
    for prefix in ("heading", "标题"):
        if n.startswith(prefix):
            digits = "".join(ch for ch in n[len(prefix):] if ch.isdigit())
            return max(1, min(6, int(digits))) if digits else 1
    return 0


def docx_to_text(path: Path) -> str:
    doc = Document(str(path))
    lines = []
    for p in doc.paragraphs:
        level = _heading_level(p.style.name if p.style is not None else "")
        if level and p.text.strip():
            lines.append("#" * level + " " + p.text.strip())
        else:
            lines.append(p.text)
    return "\n".join(lines)


def read_text(path: Path) -> tuple[str, str]:
    """返回 (统一成 \\n 换行的文本, 编码名)。docx 的编码名记为 "docx"。"""
    path = Path(path)
    if path.suffix.lower() == ".docx":
        return docx_to_text(path), "docx"
    data = path.read_bytes()
    enc = detect_encoding(data)
    text = data.decode(enc, errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):
        text = text[1:]
    return text, enc
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_readers.py -q`
Expected: `8 passed`

如果 `test_docx_headings_become_markdown` 失败，先打印 `[p.style.name for p in Document(str(p)).paragraphs]` 写到文件里看 python-docx 实际给的样式名，再调 `_heading_level`，不要改测试的期望值。

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/readers.py tests/test_readers.py
git commit -m "feat: 读 txt/md/docx 并识别编码"
```

## Task 6: 步骤 1 导入 importer.py

**Files:**
- Create: `src/ligaotai/importer.py`
- Test: `tests/test_importer.py`

要点：
- 递归扫描所选文件夹，txt/md/docx 复制到 `原稿/<文件夹名>/<原相对路径>`。带上文件夹名，是为了导入两个不同文件夹时，同名的相对路径不会撞车。
- 跳过：隐藏文件和隐藏目录（`.obsidian`、`.git`）、Word 临时文件（`~$` 开头）、其他格式。跳过的文件在结果里列出来。
- `原稿清单.json` 里每个文件记：内容哈希、编码、字数、**原件**的修改时间（查重时选主版本要用）、导入时间。键就是 `原稿/` 下的相对路径，后面所有步骤都用这个键指代来源文件。
- 重新导入同一个文件夹：哈希没变的跳过；变了的覆盖并算作「改动」。**先读后复制**：读失败（比如 docx 坏了）就不覆盖旧副本，记进 failed。
- 源文件夹里删掉的文件不会从书里删（作者可能只是挪走了），本计划不处理。
- 有新增或改动时，下游步骤标记为过期。

- [ ] **Step 1: 写失败的测试**

`tests/test_importer.py`：
```python
import pytest
from docx import Document

from ligaotai.fsutil import read_json
from ligaotai.importer import run_import


def make_src(tmp_path):
    src = tmp_path / "我的稿子"
    (src / "旧稿").mkdir(parents=True)
    (src / ".obsidian").mkdir()
    (src / "a.txt").write_bytes("第一章 开端\n林清年方十六。".encode("gbk"))
    (src / "旧稿" / "b.md").write_text("# 第二章\n雪夜。", encoding="utf-8")
    doc = Document()
    doc.add_heading("第三章", level=1)
    doc.add_paragraph("正文。")
    doc.save(str(src / "c.docx"))
    (src / "d.pdf").write_bytes(b"%PDF")
    (src / ".obsidian" / "e.txt").write_text("x", encoding="utf-8")
    (src / "~$f.docx").write_bytes(b"lock")
    return src


def test_first_import(tmp_path, book):
    src = make_src(tmp_path)
    calls = []
    summary = run_import(book, src, lambda done, total, *a: calls.append((done, total)))
    assert summary["added"] == 3
    assert summary["changed"] == 0
    assert summary["failed"] == []
    assert sorted(s["path"] for s in summary["skipped"]) == [".obsidian/e.txt", "d.pdf", "~$f.docx"]
    assert (book.originals_dir / "我的稿子" / "旧稿" / "b.md").exists()
    files = read_json(book.manifest_path)["files"]
    assert set(files) == {"我的稿子/a.txt", "我的稿子/旧稿/b.md", "我的稿子/c.docx"}
    assert files["我的稿子/a.txt"]["encoding"] == "gb18030"
    assert files["我的稿子/c.docx"]["encoding"] == "docx"
    assert book.step("import")["status"] == "done"
    assert calls[-1] == (6, 6)


def test_reimport_unchanged_keeps_downstream(tmp_path, book):
    src = make_src(tmp_path)
    run_import(book, src)
    book.set_step("split", "done")
    summary = run_import(book, src)
    assert (summary["added"], summary["changed"], summary["unchanged"]) == (0, 0, 3)
    assert book.step("split")["status"] == "done"


def test_reimport_changed_outdates_downstream(tmp_path, book):
    src = make_src(tmp_path)
    run_import(book, src)
    book.set_step("split", "done")
    (src / "旧稿" / "b.md").write_text("# 第二章\n雪夜，改过了。", encoding="utf-8")
    summary = run_import(book, src)
    assert summary["changed"] == 1
    assert book.step("split")["status"] == "outdated"
    copied = (book.originals_dir / "我的稿子" / "旧稿" / "b.md").read_text(encoding="utf-8")
    assert "改过了" in copied


def test_broken_docx_is_reported_not_copied(tmp_path, book):
    src = tmp_path / "稿"
    src.mkdir()
    (src / "坏.docx").write_bytes(b"not a zip")
    summary = run_import(book, src)
    assert [f["path"] for f in summary["failed"]] == ["稿/坏.docx"]
    assert not (book.originals_dir / "稿" / "坏.docx").exists()
    assert read_json(book.manifest_path)["files"] == {}


def test_not_a_folder(tmp_path, book):
    with pytest.raises(NotADirectoryError):
        run_import(book, tmp_path / "没有")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_importer.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

`src/ligaotai/importer.py`：
```python
"""步骤 1 导入：把文件夹里的 txt/md/docx 复制进 原稿/，登记到 原稿清单.json。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from .book import Book, now_iso
from .fsutil import natural_key, read_json, safe_name, write_json
from .readers import SUPPORTED, read_text

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


def _skip_reason(rel: Path) -> str | None:
    if any(part.startswith(".") for part in rel.parts):
        return "隐藏文件"
    if rel.name.startswith("~$"):
        return "Word 临时文件"
    if rel.suffix.lower() not in SUPPORTED:
        return "格式不支持"
    return None


def _import_one(book: Book, manifest: dict, key: str, src: Path) -> str:
    """导入一个文件，返回 added / changed / unchanged。读失败直接抛异常，不动旧副本。"""
    data = src.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    old = manifest["files"].get(key)
    if old and old["sha256"] == digest:
        return "unchanged"
    text, enc = read_text(src)  # 先读，读得出来才复制
    dest = book.originals_dir / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    manifest["files"][key] = {
        "sha256": digest,
        "encoding": enc,
        "chars": len(text),
        "mtime": src.stat().st_mtime,
        "imported": now_iso(),
    }
    return "changed" if old else "added"


def run_import(book: Book, folder: Path, progress: Progress = _noop) -> dict:
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise NotADirectoryError(str(folder))
    root_name = safe_name(folder.name)
    manifest = read_json(book.manifest_path, {"files": {}})
    files = sorted(
        (p for p in folder.rglob("*") if p.is_file()),
        key=lambda p: natural_key(p.relative_to(folder).as_posix()),
    )
    counts = {"added": 0, "changed": 0, "unchanged": 0}
    skipped: list[dict] = []
    failed: list[dict] = []
    for i, src in enumerate(files, 1):
        rel = src.relative_to(folder)
        reason = _skip_reason(rel)
        if reason:
            skipped.append({"path": rel.as_posix(), "reason": reason})
        else:
            key = f"{root_name}/{rel.as_posix()}"
            try:
                counts[_import_one(book, manifest, key, src)] += 1
            except Exception as e:  # 坏文件不能拖垮整次导入
                failed.append({"path": key, "error": f"{type(e).__name__}: {e}"})
        progress(i, len(files))
    write_json(book.manifest_path, manifest)
    summary = {
        "folder": str(folder),
        "root": root_name,
        **counts,
        "skipped": skipped,
        "failed": failed,
        "total_files": len(manifest["files"]),
    }
    book.set_step("import", "done", summary, changed=bool(counts["added"] or counts["changed"]))
    return summary
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_importer.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/importer.py tests/test_importer.py
git commit -m "feat: 步骤1 导入（编码识别、跳过清单、重复导入只处理改动）"
```

## Task 7: 切场景（标题 / 分隔符 / 空行）split.py

**Files:**
- Create: `src/ligaotai/split.py`
- Test: `tests/test_split.py`

纯函数，输入一段文本，输出若干 `Block(start, end, heading, part)`，`text[start:end]` 就是这一块的正文。本任务先做前两级切法，下一个任务加「太长再切」。

规则：
1. **标题行**（去掉首尾空格和全角空格后，长度 ≤ 50、结尾不是句读标点）：
   - `第X章/节/回/卷/集/部/篇/幕`，X 可以是阿拉伯数字、全角数字、中文数字，含 `〇`、`○`、`零`、`两`（西游记里有「第一○回」「第八十七回」这两种写法）；
   - `Chapter N`（大小写都行）；
   - Markdown `#` 标题（docx 的标题样式在 readers 里已经转成了这种）；
   - 单独一行的数字编号：`12`、`１２．`、`十三`。
   - 「结尾不是句读标点」是用来挡「第三回合，他又扑了上来。」这种正文行的。
2. **分隔符行**：去掉空白后 ≥ 3 个字符，并且全部由 `* ＊ - — － _ = ＝ ~ ～ · • ◇ ◆ ○ ● □ ■ ☆ ★ ※ # ＃` 组成。分隔符行本身不进任何块。
3. **连续空行** ≥ `blank_lines`（默认 2）个：切开。只有空格或全角空格的行也算空行。单个空行是普通段落间隔，不切。
4. 每块去掉首尾的空行，但**保留第一行的缩进**（从行首开始）。去完是空的块丢掉。
5. **只有标题、没有正文的块**并到下一块，标题用「 / 」连起来（例：「第一卷 风起 / 第一章 雪夜」）。最后一块如果只有标题，就单独留着。
6. `part`：同一个标题下的第几块，从 1 开始。

- [ ] **Step 1: 写失败的测试**

`tests/test_split.py`：
```python
import pytest

from ligaotai.split import SplitRules, is_heading, is_separator, split_text


def spans(text, rules=SplitRules()):
    return [(text[b.start:b.end], b.heading, b.part) for b in split_text(text, rules)]


@pytest.mark.parametrize(
    "line",
    [
        "第一○回     靈根育孕源流出　心性修持大道生",
        " 第八三回     心猿識得丹頭　姹女還歸本性",
        "第八十七回 鳳仙郡冒天止雨　孫大圣勸善施霖",
        "第12章",
        "第一卷 风起",
        "# 第一章",
        "## 小节",
        "Chapter 3",
        "CHAPTER IV",
        "12",
        "１２．",
        "十三",
    ],
)
def test_is_heading_true(line):
    assert is_heading(line)


@pytest.mark.parametrize(
    "line",
    [
        "第三回合，他又扑了上来。",
        "第三回合他扑了上来，",
        "#没空格",
        "",
        "这是一段普通的话",
        "第一章" + "长" * 60,
    ],
)
def test_is_heading_false(line):
    assert not is_heading(line)


@pytest.mark.parametrize("line,expected", [
    ("***", True), ("* * *", True), ("———", True), ("◇◇◇", True), ("　＊＊＊　", True),
    ("——", False), ("***好", False), ("", False),
])
def test_is_separator(line, expected):
    assert is_separator(line) is expected


def test_split_by_chapter_heading():
    text = "第一章 开端\n林清出场。\n\n第二章 转折\n雪夜。"
    assert spans(text) == [
        ("第一章 开端\n林清出场。", "第一章 开端", 1),
        ("第二章 转折\n雪夜。", "第二章 转折", 1),
    ]


def test_preface_before_first_heading():
    assert spans("序言。\n第一章\n正文。") == [("序言。", "", 1), ("第一章\n正文。", "第一章", 1)]


def test_separators_split_and_are_dropped():
    text = "开头。\n***\n中间。\n◇◇◇\n结尾。"
    assert spans(text) == [("开头。", "", 1), ("中间。", "", 2), ("结尾。", "", 3)]


def test_single_blank_line_does_not_split():
    assert spans("甲。\n\n乙。") == [("甲。\n\n乙。", "", 1)]


def test_two_blank_lines_split():
    assert spans("甲。\n\n\n乙。") == [("甲。", "", 1), ("乙。", "", 2)]


def test_whitespace_only_lines_count_as_blank():
    assert spans("甲。\n　　\n \n乙。") == [("甲。", "", 1), ("乙。", "", 2)]


def test_blank_lines_setting():
    assert spans("甲。\n\n\n乙。", SplitRules(blank_lines=3)) == [("甲。\n\n\n乙。", "", 1)]


def test_heading_only_block_merges_forward():
    text = "第一卷 风起\n\n\n第一章 雪夜\n正文。"
    assert spans(text) == [(text, "第一卷 风起 / 第一章 雪夜", 1)]


def test_xiyouji_style_heading_then_blank_lines():
    text = "第一回     靈根育孕\n\n\n\n\n　　詩曰：\n混沌未分。"
    assert spans(text) == [(text, "第一回     靈根育孕", 1)]


def test_first_line_indent_is_kept():
    assert spans("\n\n　　第一段。") == [("　　第一段。", "", 1)]


def test_trailing_heading_only_block_is_kept():
    assert spans("正文。\n第九章") == [("正文。", "", 1), ("第九章", "第九章", 1)]


def test_empty_text():
    assert split_text("") == []
    assert split_text("\n\n  \n") == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_split.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

`src/ligaotai/split.py`：
```python
"""切场景：把一个文件的文本切成场景块。纯函数，不碰文件。

切法按优先级：章节标题 → 分隔符行 / 连续空行 → 太长的再切（见 _size_split）。
返回的位置都指向传入的文本，界面据此跳回原件。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SplitRules:
    max_chars: int = 5000
    target_chars: int = 3000
    blank_lines: int = 2


@dataclass(frozen=True)
class Block:
    start: int
    end: int
    heading: str  # 所在章节标题，可能为空
    part: int     # 同一标题下的第几块，从 1 开始


_NUM = "0-9０-９一二三四五六七八九十百千零〇○两"
HEADING_PATTERNS = [
    re.compile(rf"^第[{_NUM}]+[章节回卷集部篇幕]"),
    re.compile(r"^chapter\s+[0-9ivxlc]+\b", re.IGNORECASE),
    re.compile(r"^#{1,6}\s+\S"),
    re.compile(r"^[0-9０-９]{1,4}[.、．]?$"),
    re.compile(r"^[一二三四五六七八九十百零〇]{1,6}$"),
]
HEADING_MAX_LEN = 50
_SENTENCE_END = "。！？!?，,；;…」”』"
_SEPARATOR_CHARS = set("*＊-—－_=＝~～·•◇◆○●□■☆★※#＃")
_WS = " \t　"

# 一段：(起, 止, 标题, 章节序号)
Piece = tuple[int, int, str, int]


def is_heading(line: str) -> bool:
    s = line.strip(_WS)
    if not s or len(s) > HEADING_MAX_LEN or s[-1] in _SENTENCE_END:
        return False
    return any(p.match(s) for p in HEADING_PATTERNS)


def is_separator(line: str) -> bool:
    s = "".join(line.split())
    return len(s) >= 3 and set(s) <= _SEPARATOR_CHARS


def _is_blank(line: str) -> bool:
    return not line.strip(_WS)


def _line_spans(text: str) -> list[tuple[int, int, str]]:
    spans = []
    pos = 0
    for line in text.split("\n"):
        spans.append((pos, pos + len(line), line))
        pos += len(line) + 1
    return spans


def _raw_pieces(text: str, rules: SplitRules) -> list[Piece]:
    """按标题、分隔符、连续空行切成若干段（还没去空白）。"""
    pieces: list[Piece] = []
    heading, section = "", 0
    piece_start = 0
    blank_start, blank_count = 0, 0
    for start, end, line in _line_spans(text):
        if _is_blank(line):
            if blank_count == 0:
                blank_start = start
            blank_count += 1
            continue
        if blank_count >= rules.blank_lines:
            pieces.append((piece_start, blank_start, heading, section))
            piece_start = start
        blank_count = 0
        if is_separator(line):
            pieces.append((piece_start, start, heading, section))
            piece_start = end
        elif is_heading(line):
            pieces.append((piece_start, start, heading, section))
            piece_start = start
            heading = line.strip(_WS)
            section += 1
    pieces.append((piece_start, len(text), heading, section))
    return pieces


def _trim(text: str, s: int, e: int) -> tuple[int, int] | None:
    """去掉首尾空行，保留第一行缩进。全是空白返回 None。"""
    seg = text[s:e]
    left = len(seg) - len(seg.lstrip())
    if left == len(seg):
        return None
    first = s + left
    line_start = text.rfind("\n", s, first)
    s2 = line_start + 1 if line_start != -1 else s
    return s2, s + len(seg.rstrip())


def _is_heading_only(text: str, s: int, e: int) -> bool:
    lines = [ln for ln in text[s:e].split("\n") if not _is_blank(ln)]
    return bool(lines) and all(is_heading(ln) for ln in lines)


def _join_heading(a: str, b: str) -> str:
    if not a:
        return b
    if not b or a == b:
        return a
    return f"{a} / {b}"


def _merge_heading_only(text: str, pieces: list[Piece]) -> list[Piece]:
    merged: list[Piece] = []
    pending: Piece | None = None
    for s, e, h, sec in pieces:
        if _is_heading_only(text, s, e):
            pending = (s, e, h, sec) if pending is None else (
                pending[0], e, _join_heading(pending[2], h), sec
            )
            continue
        if pending is not None:
            s, h = pending[0], _join_heading(pending[2], h)
            pending = None
        merged.append((s, e, h, sec))
    if pending is not None:
        merged.append(pending)
    return merged


def _number_parts(pieces: list[Piece]) -> list[Block]:
    blocks = []
    counts: dict[int, int] = {}
    for s, e, h, sec in pieces:
        counts[sec] = counts.get(sec, 0) + 1
        blocks.append(Block(s, e, h, counts[sec]))
    return blocks


def split_text(text: str, rules: SplitRules = SplitRules()) -> list[Block]:
    pieces: list[Piece] = []
    for s, e, h, sec in _raw_pieces(text, rules):
        t = _trim(text, s, e)
        if t:
            pieces.append((t[0], t[1], h, sec))
    return _number_parts(_merge_heading_only(text, pieces))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_split.py -q`
Expected: `38 passed`（参数化用例各算一个）

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/split.py tests/test_split.py
git commit -m "feat: 切场景（标题/分隔符/连续空行/标题并入下一块）"
```

---

## Task 8: 切场景（太长再切）

**Files:**
- Modify: `src/ligaotai/split.py`（加 `_find_cut`、`_size_split`，改 `split_text`）
- Test: `tests/test_split.py`（追加）

规则：一块超过 `max_chars`（默认 5000 字，按字符数算，含换行）就切一刀，切点尽量靠近「块起点 + `target_chars`（3000）」，并且两边都至少留 `target_chars // 3` 字。候选切点按优先级找，找到就用：
1. 空行处（段落之间）；
2. 换行处（一段一行、没有空行的稿子）；
3. 句末标点之后（`。！？!?…`，后面跟着的引号括号一起带走）；
4. 都没有：硬切在 `起点 + target_chars`。

切完剩下的部分如果还超长，继续切。切出来的块共用原来的标题，`part` 依次编号。

- [ ] **Step 1: 追加失败的测试**

在 `tests/test_split.py` 末尾追加：
```python
def _nows(s):
    return "".join(s.split())


def test_long_block_cut_at_blank_line_near_target():
    para = "甲" * 279 + "。"
    text = "\n\n".join([para] * 40)
    blocks = split_text(text)
    lengths = [b.end - b.start for b in blocks]
    assert all(n <= 5000 for n in lengths)
    assert abs(lengths[0] - 3000) <= 300
    assert text[blocks[0].end:blocks[0].end + 2] == "\n\n"
    assert [b.part for b in blocks] == list(range(1, len(blocks) + 1))
    assert _nows("".join(text[b.start:b.end] for b in blocks)) == _nows(text)


def test_long_block_without_blank_lines_cuts_at_newline():
    line = "乙" * 199 + "。"
    text = "\n".join([line] * 50)
    blocks = split_text(text)
    assert all(b.end - b.start <= 5000 for b in blocks)
    assert all(text[b.end] == "\n" for b in blocks[:-1])
    assert _nows("".join(text[b.start:b.end] for b in blocks)) == _nows(text)


def test_long_single_line_cuts_after_sentence_end():
    text = ("丙" * 99 + "。") * 80
    blocks = split_text(text)
    assert all(b.end - b.start <= 5000 for b in blocks)
    assert all(text[b.end - 1] == "。" for b in blocks)
    assert "".join(text[b.start:b.end] for b in blocks) == text


def test_no_punctuation_hard_cut():
    text = "丁" * 12000
    assert [b.end - b.start for b in split_text(text)] == [3000, 3000, 3000, 3000]


def test_long_blocks_keep_heading():
    text = "第一章 雪夜\n" + "\n\n".join(["戊" * 279 + "。"] * 30)
    blocks = split_text(text)
    assert len(blocks) >= 2
    assert all(b.heading == "第一章 雪夜" for b in blocks)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_split.py -q`
Expected: 新加的 5 个 FAIL（块长度超过 5000）

- [ ] **Step 3: 实现**

在 `src/ligaotai/split.py` 里、`_number_parts` 之前加入：
```python
_BLANK_BOUNDARY = re.compile(r"\n[ \t　]*\n")
_NEWLINE = re.compile(r"\n")
_SENTENCE_CUT = re.compile(r"[。！？!?…][」”』）)]?")


def _find_cut(text: str, s: int, e: int, rules: SplitRules) -> int:
    """在 [s, e) 里找一个最接近 s + target 的切点。"""
    ideal = s + rules.target_chars
    min_side = rules.target_chars // 3
    lo, hi = s + min_side, e - min_side
    candidate_sets = (
        (m.start() for m in _BLANK_BOUNDARY.finditer(text, s, e)),
        (m.start() for m in _NEWLINE.finditer(text, s, e)),
        (m.end() for m in _SENTENCE_CUT.finditer(text, s, e)),
    )
    for candidates in candidate_sets:
        best = min(
            (c for c in candidates if lo <= c <= hi),
            key=lambda c: abs(c - ideal),
            default=None,
        )
        if best is not None:
            return best
    return ideal


def _size_split(text: str, s: int, e: int, rules: SplitRules) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    while e - s > rules.max_chars:
        cut = _find_cut(text, s, e, rules)
        head = _trim(text, s, cut)
        if head:
            out.append(head)
        rest = _trim(text, cut, e)
        if rest is None:
            return out
        s = rest[0]
    out.append((s, e))
    return out
```

把 `split_text` 整个换成：
```python
def split_text(text: str, rules: SplitRules = SplitRules()) -> list[Block]:
    pieces: list[Piece] = []
    for s, e, h, sec in _raw_pieces(text, rules):
        t = _trim(text, s, e)
        if t:
            pieces.append((t[0], t[1], h, sec))
    sized: list[Piece] = []
    for s, e, h, sec in _merge_heading_only(text, pieces):
        for s2, e2 in _size_split(text, s, e, rules):
            sized.append((s2, e2, h, sec))
    return _number_parts(sized)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_split.py -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/split.py tests/test_split.py
git commit -m "feat: 切场景（超长块按空行/换行/句末就近切开）"
```

## Task 9: 场景文件 + 步骤 2 切场景 scenes.py

**Files:**
- Create: `src/ligaotai/scenes.py`
- Test: `tests/test_scenes.py`

要点：
- 场景文件 `场景/S-0001.md` = YAML 头信息 + 正文。头信息字段：`id`、`source`（原稿清单里的键）、`index`（这个文件里第几块，从 0 起）、`start`/`end`（在读出来的文本里的位置）、`chars`、`hash`（正文 sha256 前 16 位）、`heading`、`part`、`kind_hint`（`碎片` 或空）、`stale`（正文变过，场景卡要重做）、`removed`（这次没切出来）。
- **场景文件是唯一的数据源**，不另建索引文件；要列表就把 `场景/` 扫一遍（1000 多个文件，很快）。
- 块的身份 =（来源文件, 第几块）。重跑步骤 2 时的对账规则：
  - 身份在、内容没变：不动（位置、标题等变了就改写，但不标 stale）；
  - 身份在、内容变了：改写，`stale: true`；
  - 新身份：接着**当前最大编号**往后排，不重排旧编号（所以新导入的「片段1」会排在最后）；
  - 旧身份这次没切出来：`removed: true`，文件和编号都保留；以后又切出来了就恢复。
- 编号顺序：来源文件按自然排序，文件内按块的先后。
- 有新增、改动、删除时，下游步骤标记为过期。

- [ ] **Step 1: 写失败的测试**

`tests/test_scenes.py`：
```python
import pytest

from ligaotai.importer import run_import
from ligaotai.scenes import (
    Scene,
    dump_scene,
    get_scene,
    load_scenes,
    parse_scene,
    run_split,
    scene_path,
)

LONG = "林清走在雪地里，" * 50  # 400 字，不算碎片


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "稿"
    write(d / "片段2.txt", f"第一章 雪夜\n{LONG}\n第二章 离城\n{LONG}")
    write(d / "片段10.txt", f"第三章 渡口\n{LONG}")
    return d


def by_id(book):
    return {s.id: s for s in load_scenes(book, with_text=True)}


def test_dump_parse_roundtrip():
    sc = Scene(
        id="S-0001", source="稿/a.txt", index=0, start=0, end=9, chars=9,
        hash="1234567890123456", heading="第一回     靈根", part=1,
        text="正文\n---\n还是正文",
    )
    assert parse_scene(dump_scene(sc)) == sc


def test_split_numbers_by_natural_path_order(book, src):
    run_import(book, src)
    summary = run_split(book)
    scenes = load_scenes(book, with_text=True)
    assert [(s.id, s.source, s.index, s.heading) for s in scenes] == [
        ("S-0001", "稿/片段2.txt", 0, "第一章 雪夜"),
        ("S-0002", "稿/片段2.txt", 1, "第二章 离城"),
        ("S-0003", "稿/片段10.txt", 0, "第三章 渡口"),
    ]
    assert scenes[0].text == f"第一章 雪夜\n{LONG}"
    assert scenes[0].kind_hint == ""
    assert (summary["added"], summary["scenes"], summary["fragments"]) == (3, 3, 0)
    assert book.step("split")["status"] == "done"


def test_short_block_is_fragment(book, tmp_path):
    d = tmp_path / "稿"
    write(d / "a.txt", "第一章 渡口\n短短一句。")
    run_import(book, d)
    assert run_split(book)["fragments"] == 1
    assert load_scenes(book)[0].kind_hint == "碎片"


def test_load_without_text(book, src):
    run_import(book, src)
    run_split(book)
    assert all(s.text == "" for s in load_scenes(book))


def test_rerun_unchanged_keeps_downstream(book, src):
    run_import(book, src)
    run_split(book)
    book.set_step("dedup", "done")
    s2 = run_split(book)
    assert (s2["added"], s2["changed"], s2["unchanged"], s2["removed"]) == (0, 0, 3, 0)
    assert book.step("dedup")["status"] == "done"


def test_changed_text_marks_stale(book, src):
    run_import(book, src)
    run_split(book)
    book.set_step("dedup", "done")
    write(src / "片段2.txt", f"第一章 雪夜\n{LONG}\n第二章 离城\n{LONG}改了一句。")
    run_import(book, src)
    summary = run_split(book)
    assert summary["changed"] == 1
    scenes = by_id(book)
    assert scenes["S-0002"].stale is True
    assert scenes["S-0002"].text.endswith("改了一句。")
    assert scenes["S-0001"].stale is False
    assert book.step("dedup")["status"] == "outdated"


def test_new_file_appends_numbers(book, src):
    run_import(book, src)
    run_split(book)
    write(src / "片段1.txt", f"第零章 序\n{LONG}")
    run_import(book, src)
    run_split(book)
    assert by_id(book)["S-0004"].source == "稿/片段1.txt"


def test_vanished_block_removed_then_restored(book, src):
    run_import(book, src)
    run_split(book)
    write(src / "片段2.txt", f"第一章 雪夜\n{LONG}")
    run_import(book, src)
    assert run_split(book)["removed"] == 1
    assert by_id(book)["S-0002"].removed is True
    assert scene_path(book, "S-0002").exists()

    write(src / "片段2.txt", f"第一章 雪夜\n{LONG}\n第二章 离城\n{LONG}")
    run_import(book, src)
    assert run_split(book)["changed"] == 1
    assert by_id(book)["S-0002"].removed is False


def test_get_scene(book, src):
    run_import(book, src)
    run_split(book)
    assert get_scene(book, "S-0003").text == f"第三章 渡口\n{LONG}"
    with pytest.raises(ValueError):
        get_scene(book, "../book")
    with pytest.raises(FileNotFoundError):
        get_scene(book, "S-9999")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_scenes.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

`src/ligaotai/scenes.py`：
```python
"""场景：场景/S-0001.md 的读写，以及步骤 2（切场景 + 编号对账）。

块的身份 =（来源文件, 文件里第几块）：
- 身份和内容都没变：不动；
- 身份在、内容变了：改写正文，标 stale（场景卡要重做）；
- 新身份：接着最大编号往后排，不重排旧编号；
- 旧身份这次没切出来：标 removed，不删文件、不回收编号。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from .book import Book
from .fsutil import atomic_write_text, natural_key, read_json
from .readers import read_text
from .split import SplitRules, split_text

SCENE_ID_RE = re.compile(r"^S-\d{4,}$")
FRAGMENT = "碎片"

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


@dataclass
class Scene:
    id: str
    source: str
    index: int
    start: int
    end: int
    chars: int
    hash: str
    heading: str = ""
    part: int = 1
    kind_hint: str = ""
    stale: bool = False
    removed: bool = False
    text: str = field(default="", repr=False)

    def meta(self) -> dict:
        d = asdict(self)
        d.pop("text")
        return d


def scene_num(sid: str) -> int:
    return int(sid[2:])


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def scene_path(book: Book, sid: str) -> Path:
    return book.scenes_dir / f"{sid}.md"


def dump_scene(scene: Scene) -> str:
    head = yaml.safe_dump(scene.meta(), allow_unicode=True, sort_keys=False)
    return f"---\n{head}---\n{scene.text}"


def parse_scene(content: str) -> Scene:
    if not content.startswith("---\n"):
        raise ValueError("场景文件缺少头信息")
    end = content.index("\n---\n", 4)
    meta = yaml.safe_load(content[4 : end + 1])
    return Scene(**meta, text=content[end + 5 :])


def write_scene(book: Book, scene: Scene) -> None:
    atomic_write_text(scene_path(book, scene.id), dump_scene(scene))


def read_scene(path: Path) -> Scene:
    return parse_scene(Path(path).read_text(encoding="utf-8"))


def load_scenes(book: Book, with_text: bool = False) -> list[Scene]:
    if not book.scenes_dir.exists():
        return []
    out = []
    for p in book.scenes_dir.glob("S-*.md"):
        sc = read_scene(p)
        if not with_text:
            sc.text = ""
        out.append(sc)
    out.sort(key=lambda s: scene_num(s.id))
    return out


def get_scene(book: Book, sid: str) -> Scene:
    if not SCENE_ID_RE.match(sid):
        raise ValueError(f"场景编号不合法：{sid}")
    p = scene_path(book, sid)
    if not p.exists():
        raise FileNotFoundError(sid)
    return read_scene(p)


def rules_from_settings(settings: dict) -> SplitRules:
    return SplitRules(
        max_chars=settings["split_max_chars"],
        target_chars=settings["split_target_chars"],
        blank_lines=settings["split_blank_lines"],
    )


def run_split(book: Book, progress: Progress = _noop) -> dict:
    settings = book.settings()
    rules = rules_from_settings(settings)
    frag_max = settings["fragment_max_chars"]
    files = read_json(book.manifest_path, {"files": {}})["files"]
    existing = {(s.source, s.index): s for s in load_scenes(book, with_text=True)}
    next_num = max((scene_num(s.id) for s in existing.values()), default=0) + 1
    seen: set[tuple[str, int]] = set()
    counts = {"added": 0, "changed": 0, "unchanged": 0, "removed": 0}
    fragments = 0
    keys = sorted(files, key=natural_key)
    for i, key in enumerate(keys, 1):
        text, _ = read_text(book.originals_dir / key)
        for idx, b in enumerate(split_text(text, rules)):
            body = text[b.start : b.end]
            seen.add((key, idx))
            old = existing.get((key, idx))
            new = Scene(
                id=old.id if old else f"S-{next_num:04d}",
                source=key,
                index=idx,
                start=b.start,
                end=b.end,
                chars=len(body),
                hash=text_hash(body),
                heading=b.heading,
                part=b.part,
                kind_hint=FRAGMENT if len(body.strip()) < frag_max else "",
                text=body,
            )
            fragments += new.kind_hint == FRAGMENT
            if old is None:
                next_num += 1
                counts["added"] += 1
            elif old.hash != new.hash:
                new.stale = True
                counts["changed"] += 1
            else:
                new.stale = old.stale
                counts["changed" if old.removed else "unchanged"] += 1
                if new == old:
                    continue
            write_scene(book, new)
        progress(i, len(keys))
    for k, old in existing.items():
        if k not in seen and not old.removed:
            old.removed = True
            write_scene(book, old)
            counts["removed"] += 1
    summary = {**counts, "scenes": len(seen), "fragments": fragments, "files": len(keys)}
    changed = bool(counts["added"] or counts["changed"] or counts["removed"])
    book.set_step("split", "done", summary, changed=changed)
    return summary
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_scenes.py -q`
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/scenes.py tests/test_scenes.py
git commit -m "feat: 步骤2 切场景（场景文件、编号稳定、改动标过期）"
```

## Task 10: 步骤 3 查重 dedup.py

**Files:**
- Create: `src/ligaotai/dedup.py`
- Create: `tests/helpers.py`（测试共用的随机文本生成器，后面 API 和弄乱脚本的测试也用）
- Test: `tests/test_dedup.py`

做法（跟 spec 的偏差见文件开头）：
1. 每块正文去掉空白和标点，切成 5 字一组的字串（shingle），存成整数哈希集合。
2. 建倒排索引「字串 → 含它的块」，对每个字串把含它的块两两计数，得到每两块共有多少字串。出现在超过 `dedup_common_df`（默认 20）块里的字串当套话，不计数。
3. 每一对算 Jaccard = 共有 / 并集，包含度 = 共有 / 较小那块。Jaccard ≥ 0.5 **或** 包含度 ≥ 0.8 就连起来。少于 `dedup_min_shingles`（100）个字串的块不参与，否则一句「且听下回分解」就能让碎片「包含」在任何章节里。
4. 连通的块成一个版本组。主版本默认选最长的，一样长选原件修改时间最新的，还一样选编号小的。
5. 作者手动选过主版本（`main_by: "author"`）的，重跑时只要那块还在组里就保留。
6. `removed` 的场景不参与。
7. 结果和上次比有变化才让下游过期；作者改主版本也会让下游过期。

`版本组.json` 格式：
```json
{
  "params": {"dedup_shingle": 5, "dedup_jaccard": 0.5, "...": "..."},
  "groups": [
    {"id": "G-001", "members": ["S-0001", "S-0002"], "main": "S-0001", "main_by": "auto",
     "pairs": [{"a": "S-0001", "b": "S-0002", "jaccard": 0.81, "containment": 0.9}]}
  ]
}
```

- [ ] **Step 1: 写测试辅助和失败的测试**

`tests/helpers.py`（测试文件里用 `from helpers import gen_text` 引用；pytest 会把 `tests/` 加进 sys.path）：
```python
"""测试共用的小工具。"""

import random

CHARS = (
    "天地玄黄宇宙洪荒日月盈昃辰宿列张寒来暑往秋收冬藏闰余成岁律吕调阳云腾致雨"
    "露结为霜金生丽水玉出昆冈剑号巨阙珠称夜光果珍李柰菜重芥姜海咸河淡鳞潜羽翔"
)


def gen_text(seed: int, n: int) -> str:
    """n 个随机汉字，每 20 字一个句号，每 200 字分一段（单个空行）。5 字串几乎不会撞。"""
    rng = random.Random(seed)
    out = []
    for i in range(1, n + 1):
        out.append(rng.choice(CHARS))
        if i % 200 == 0:
            out.append("。\n\n")
        elif i % 20 == 0:
            out.append("。")
    return "".join(out)
```

`tests/test_dedup.py`：
```python
import pytest
from helpers import gen_text

from ligaotai.dedup import (
    find_pairs,
    group_pairs,
    normalize,
    run_dedup,
    set_main,
    shingles,
)
from ligaotai.fsutil import read_json
from ligaotai.importer import run_import
from ligaotai.scenes import run_split


def test_normalize():
    assert normalize("林清，\n　走了。abc") == "林清走了abc"


def test_shingles():
    assert len(shingles("甲乙丙丁戊己", 5)) == 2
    assert len(shingles("甲乙", 5)) == 1
    assert shingles("，。 ", 5) == set()


def test_jaccard_pair():
    docs = {"a": set(range(0, 200)), "b": set(range(40, 240))}
    [p] = find_pairs(docs, 0.5, 0.8, 100, 20)
    assert (p.a, p.b, p.inter, p.jaccard) == ("a", "b", 160, 0.6667)


def test_containment_pair():
    docs = {"a": set(range(0, 400)), "c": set(range(0, 120))}
    [p] = find_pairs(docs, 0.5, 0.8, 100, 20)
    assert (p.jaccard, p.containment) == (0.3, 1.0)


def test_below_thresholds_no_pair():
    docs = {"b": set(range(1000, 1200)), "d": set(range(1100, 1300))}
    assert find_pairs(docs, 0.5, 0.8, 100, 20) == []


def test_tiny_docs_ignored():
    docs = {"a": set(range(0, 400)), "e": set(range(0, 50))}
    assert find_pairs(docs, 0.5, 0.8, 100, 20) == []


def test_common_shingles_not_counted():
    docs = {
        f"d{i:02d}": set(range(250)) | set(range(10000 * (i + 1), 10000 * (i + 1) + 50))
        for i in range(25)
    }
    assert len(find_pairs(docs, 0.5, 0.8, 100, 30)) == 300
    assert find_pairs(docs, 0.5, 0.8, 100, 20) == []


def test_group_pairs_natural_order():
    docs = {
        "S-2": set(range(0, 200)), "S-10": set(range(0, 200)),
        "S-3": set(range(0, 200)), "S-7": set(range(5000, 5200)), "S-8": set(range(5000, 5200)),
    }
    groups = group_pairs(find_pairs(docs, 0.5, 0.8, 100, 20))
    assert groups == [["S-2", "S-3", "S-10"], ["S-7", "S-8"]]


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def dup_book(book, tmp_path):
    a = gen_text(1, 2000)
    sentences = a.split("。")
    b = "。".join(s for i, s in enumerate(sentences) if i % 7 != 3)
    d = tmp_path / "稿"
    write(d / "1甲.txt", "第一章 甲\n" + a)
    write(d / "2乙.txt", "第一章 甲\n" + b)
    write(d / "3丙.txt", a[400:1400])
    write(d / "4丁.txt", "第二章 丁\n" + gen_text(2, 2000))
    run_import(book, d)
    run_split(book)
    return book


def test_run_dedup_groups_versions(dup_book):
    summary = run_dedup(dup_book)
    data = read_json(dup_book.versions_path)
    [g] = data["groups"]
    assert g["members"] == ["S-0001", "S-0002", "S-0003"]
    assert g["main"] == "S-0001"
    assert g["main_by"] == "auto"
    assert summary["groups"] == 1
    assert summary["scenes_in_groups"] == 3
    assert dup_book.step("dedup")["status"] == "done"


def test_author_main_survives_rerun(dup_book):
    run_dedup(dup_book)
    dup_book.set_step("cards", "done")
    g = set_main(dup_book, "G-001", "S-0002")
    assert (g["main"], g["main_by"]) == ("S-0002", "author")
    assert dup_book.step("cards")["status"] == "outdated"
    run_dedup(dup_book)
    [g] = read_json(dup_book.versions_path)["groups"]
    assert (g["main"], g["main_by"]) == ("S-0002", "author")


def test_rerun_unchanged_keeps_downstream(dup_book):
    run_dedup(dup_book)
    dup_book.set_step("cards", "done")
    run_dedup(dup_book)
    assert dup_book.step("cards")["status"] == "done"


def test_set_main_errors(dup_book):
    run_dedup(dup_book)
    with pytest.raises(ValueError):
        set_main(dup_book, "G-001", "S-0004")
    with pytest.raises(KeyError):
        set_main(dup_book, "G-999", "S-0001")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_dedup.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

`src/ligaotai/dedup.py`：
```python
"""步骤 3 查重：找出同一场景的不同版本。

正文去掉空白和标点后切成 k 字一组的字串（shingle），建倒排索引，
精确数出每两块共有多少字串，算 Jaccard 和包含度。出现在太多块里的字串是套话，不计数。
两块满足任一阈值就连起来，连通的块成一个版本组。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Callable

from .book import Book
from .fsutil import natural_key, read_json, write_json
from .scenes import load_scenes

PARAM_KEYS = (
    "dedup_shingle",
    "dedup_jaccard",
    "dedup_containment",
    "dedup_min_shingles",
    "dedup_common_df",
)
_NOISE = re.compile(r"[\W_]+")

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


def normalize(text: str) -> str:
    return _NOISE.sub("", text)


def shingles(text: str, k: int = 5) -> set[int]:
    s = normalize(text)
    if len(s) < k:
        return {hash(s)} if s else set()
    return {hash(s[i : i + k]) for i in range(len(s) - k + 1)}


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    inter: int
    jaccard: float
    containment: float


def find_pairs(
    docs: dict[str, set[int]],
    jaccard_min: float,
    containment_min: float,
    min_shingles: int,
    common_df: int,
) -> list[Pair]:
    eligible = sorted((d for d in docs if len(docs[d]) >= min_shingles), key=natural_key)
    postings: dict[int, list[int]] = defaultdict(list)
    for i, d in enumerate(eligible):
        for x in docs[d]:
            postings[x].append(i)
    counts: Counter = Counter()
    for plist in postings.values():
        if 2 <= len(plist) <= common_df:
            counts.update(combinations(plist, 2))
    pairs = []
    for (i, j), inter in counts.items():
        a, b = eligible[i], eligible[j]
        na, nb = len(docs[a]), len(docs[b])
        jac = inter / (na + nb - inter)
        cont = inter / min(na, nb)
        if jac >= jaccard_min or cont >= containment_min:
            pairs.append(Pair(a, b, inter, round(jac, 4), round(cont, 4)))
    pairs.sort(key=lambda p: (natural_key(p.a), natural_key(p.b)))
    return pairs


def group_pairs(pairs: list[Pair]) -> list[list[str]]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        ra, rb = find(p.a), find(p.b)
        if ra != rb:
            parent[rb] = ra
    groups: dict[str, list[str]] = defaultdict(list)
    for x in list(parent):
        groups[find(x)].append(x)
    ordered = [sorted(g, key=natural_key) for g in groups.values()]
    return sorted(ordered, key=lambda g: natural_key(g[0]))


def choose_main(members: list[str], chars: dict[str, int], mtime: dict[str, float]) -> str:
    """最长的；一样长选原件修改时间最新的；还一样选编号小的（max 取第一个最大值）。"""
    return max(sorted(members, key=natural_key), key=lambda s: (chars[s], mtime.get(s, 0)))


def _signature(data: dict) -> list:
    return sorted((tuple(g["members"]), g["main"]) for g in data["groups"])


def run_dedup(book: Book, progress: Progress = _noop) -> dict:
    s = book.settings()
    scenes = [sc for sc in load_scenes(book, with_text=True) if not sc.removed]
    files = read_json(book.manifest_path, {"files": {}})["files"]
    docs: dict[str, set[int]] = {}
    for i, sc in enumerate(scenes, 1):
        docs[sc.id] = shingles(sc.text, s["dedup_shingle"])
        progress(i, len(scenes))
    pairs = find_pairs(
        docs,
        s["dedup_jaccard"],
        s["dedup_containment"],
        s["dedup_min_shingles"],
        s["dedup_common_df"],
    )
    chars = {sc.id: sc.chars for sc in scenes}
    mtime = {sc.id: files.get(sc.source, {}).get("mtime", 0) for sc in scenes}
    old = read_json(book.versions_path, {"groups": []})
    author_mains = {g["main"] for g in old["groups"] if g.get("main_by") == "author"}

    groups = []
    for n, members in enumerate(group_pairs(pairs), 1):
        picked = [m for m in members if m in author_mains]
        if len(picked) == 1:
            main, by = picked[0], "author"
        else:
            main, by = choose_main(members, chars, mtime), "auto"
        mset = set(members)
        groups.append({
            "id": f"G-{n:03d}",
            "members": members,
            "main": main,
            "main_by": by,
            "pairs": [
                {"a": p.a, "b": p.b, "jaccard": p.jaccard, "containment": p.containment}
                for p in pairs
                if p.a in mset
            ],
        })
    data = {"params": {k: s[k] for k in PARAM_KEYS}, "groups": groups}
    changed = _signature(old) != _signature(data)
    write_json(book.versions_path, data)
    summary = {
        "scenes": len(scenes),
        "pairs": len(pairs),
        "groups": len(groups),
        "scenes_in_groups": sum(len(g["members"]) for g in groups),
    }
    book.set_step("dedup", "done", summary, changed=changed)
    return summary


def set_main(book: Book, group_id: str, scene_id: str) -> dict:
    """作者手动指定主版本。"""
    data = read_json(book.versions_path, {"groups": []})
    for g in data["groups"]:
        if g["id"] != group_id:
            continue
        if scene_id not in g["members"]:
            raise ValueError(f"{scene_id} 不在 {group_id} 里")
        moved = g["main"] != scene_id
        g["main"], g["main_by"] = scene_id, "author"
        write_json(book.versions_path, data)
        if moved:
            book.mark_downstream_outdated("dedup")
        return g
    raise KeyError(group_id)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_dedup.py -q`
Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/dedup.py tests/helpers.py tests/test_dedup.py
git commit -m "feat: 步骤3 查重（倒排精确计数、版本组、作者选主版本）"
```

## Task 11: 后台任务队列 jobs.py

**Files:**
- Create: `src/ligaotai/jobs.py`
- Test: `tests/test_jobs.py`

要点：一次只跑一个任务（spec 第 4 章）。任务在单独的线程里跑，函数签名是 `fn(progress) -> dict`，`progress(done, total, message="")` 更新进度。已经有任务在排队或在跑时再提交，抛 `BusyError`。计划②里的模型并发调用会在这个线程里自己开事件循环，不影响这里的设计。

- [ ] **Step 1: 写失败的测试**

`tests/test_jobs.py`：
```python
import threading

import pytest

from ligaotai.jobs import BusyError, JobRunner


def test_job_runs_and_records_result():
    runner = JobRunner()

    def fn(progress):
        progress(1, 2, "一半")
        progress(2, 2)
        return {"ok": 1}

    job = runner.submit("split", "测试书", fn)
    job = runner.wait(job.id)
    assert job.status == "done"
    assert job.result == {"ok": 1}
    assert (job.done, job.total, job.message) == (2, 2, "一半")
    assert job.started and job.finished
    assert runner.get(job.id) is job
    assert runner.current() is job


def test_job_failure_is_captured():
    runner = JobRunner()

    def fn(progress):
        raise RuntimeError("boom")

    job = runner.wait(runner.submit("dedup", "测试书", fn).id)
    assert job.status == "failed"
    assert job.error == "RuntimeError: boom"


def test_only_one_job_at_a_time():
    runner = JobRunner()
    gate = threading.Event()
    first = runner.submit("split", "测试书", lambda p: gate.wait(5) and {})
    with pytest.raises(BusyError):
        runner.submit("dedup", "测试书", lambda p: {})
    gate.set()
    runner.wait(first.id)
    second = runner.wait(runner.submit("dedup", "测试书", lambda p: {}).id)
    assert second.status == "done"


def test_get_unknown():
    assert JobRunner().get("nope") is None
    assert JobRunner().current() is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_jobs.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

`src/ligaotai/jobs.py`：
```python
"""后台任务队列：一次只跑一个任务，跑在单独的线程里。"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from dataclasses import asdict, dataclass
from typing import Callable

from .book import now_iso

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    name: str
    book: str
    status: str = "queued"  # queued / running / done / failed
    done: int = 0
    total: int = 0
    message: str = ""
    error: str = ""
    result: dict | None = None
    started: str = ""
    finished: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class BusyError(RuntimeError):
    pass


class JobRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._current: Job | None = None

    def submit(self, name: str, book: str, fn: Callable[[Callable], dict]) -> Job:
        with self._lock:
            cur = self._current
            if cur is not None and cur.status in ("queued", "running"):
                raise BusyError(f"已有任务在跑：{cur.name}（{cur.book}）")
            job = Job(id=uuid.uuid4().hex[:8], name=name, book=book)
            self._jobs[job.id] = job
            self._current = job
            thread = threading.Thread(target=self._run, args=(job, fn), daemon=True)
            self._threads[job.id] = thread
        thread.start()
        return job

    def _run(self, job: Job, fn: Callable[[Callable], dict]) -> None:
        job.status = "running"
        job.started = now_iso()

        def progress(done: int, total: int, message: str = "") -> None:
            job.done, job.total = done, total
            if message:
                job.message = message

        try:
            job.result = fn(progress)
            job.finished = now_iso()
            job.status = "done"
        except Exception as e:
            job.error = f"{type(e).__name__}: {e}"
            job.finished = now_iso()
            job.status = "failed"
            log.error("任务失败 %s\n%s", job.name, traceback.format_exc())

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def current(self) -> Job | None:
        return self._current

    def wait(self, job_id: str, timeout: float = 30.0) -> Job:
        thread = self._threads.get(job_id)
        if thread is not None:
            thread.join(timeout)
        return self._jobs[job_id]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_jobs.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/jobs.py tests/test_jobs.py
git commit -m "feat: 后台任务队列（一次一个）"
```

---

## Task 12: API 与启动入口 api.py / __main__.py

**Files:**
- Create: `src/ligaotai/api.py`
- Create: `src/ligaotai/__main__.py`
- Test: `tests/test_api.py`

接口一览（本计划范围内）：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/health` | 活着没 |
| GET / PUT | `/api/config` | 读 / 改应用配置（书库目录） |
| GET / POST | `/api/books` | 列书 / 建书（重名 409） |
| GET | `/api/books/{name}` | 书的元信息和流水线状态 |
| POST | `/api/books/{name}/import` | 步骤 1，body `{"folder": "..."}`，返回任务 |
| POST | `/api/books/{name}/steps/{step}/run` | 步骤 2、3（`split` / `dedup`），返回任务 |
| GET | `/api/jobs/current`、`/api/jobs/{id}` | 任务进度 |
| GET | `/api/books/{name}/scenes` | 场景列表（不含正文），`?include_removed=true` 含已删除 |
| GET | `/api/books/{name}/scenes/{sid}` | 单个场景含正文 |
| GET | `/api/books/{name}/versions` | 版本组 |
| PUT | `/api/books/{name}/versions/{gid}/main` | 作者指定主版本，body `{"scene_id": "..."}` |
| GET | `/api/books/{name}/source?path=...` | 原稿全文（「跳回原件看」用），只允许清单里有的路径 |

安全：
- 只认 Host 为 `127.0.0.1` / `localhost` 的请求（`TrustedHostMiddleware`），挡 DNS 重绑定。
- 不开 CORS，写操作都要 JSON body，别的网页没法跨站调这些接口。
- 书名、场景编号、原稿路径都校验，防 `../` 越界。

任务包装：跑之前把这一步标成 `running`，出错标成 `failed` 并记下错误，再把异常抛给任务队列。已经有任务在跑，返回 409。服务启动时把上次中断时还标着 `running` 的步骤改成 `failed`。

- [ ] **Step 1: 写失败的测试**

`tests/test_api.py`：
```python
import threading

import pytest
from fastapi.testclient import TestClient
from helpers import gen_text

from ligaotai.api import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",)))


def wait(client, job):
    return client.app.state.runner.wait(job["id"]).to_dict()


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "稿"
    d.mkdir()
    text = gen_text(1, 2000)
    (d / "1甲.txt").write_text("第一章 甲\n" + text, encoding="utf-8")
    (d / "2乙.txt").write_text("第一章 甲\n" + text + "多写了一句。", encoding="utf-8")
    return d


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_rejects_foreign_host(tmp_path):
    c = TestClient(create_app(app_dir=tmp_path))  # 默认只认 127.0.0.1 / localhost
    assert c.get("/api/health").status_code == 400


def test_config_default_library(client, tmp_path):
    assert client.get("/api/config").json()["library_path"] == str(tmp_path / "书库")


def test_books_crud(client):
    r = client.post("/api/books", json={"title": "我的书"})
    assert r.status_code == 201
    assert r.json()["name"] == "我的书"
    assert client.post("/api/books", json={"title": "我的书"}).status_code == 409
    assert [b["title"] for b in client.get("/api/books").json()] == ["我的书"]
    assert client.get("/api/books/我的书").json()["steps"]["import"]["status"] == "todo"
    assert client.get("/api/books/没有").status_code == 404


def test_full_flow(client, src):
    client.post("/api/books", json={"title": "我的书"})

    r = client.post("/api/books/我的书/import", json={"folder": str(src)})
    assert r.status_code == 202
    assert wait(client, r.json())["status"] == "done"

    for step in ("split", "dedup"):
        r = client.post(f"/api/books/我的书/steps/{step}/run")
        assert r.status_code == 202
        job = wait(client, r.json())
        assert job["status"] == "done", job["error"]

    steps = client.get("/api/books/我的书").json()["steps"]
    assert [steps[s]["status"] for s in ("import", "split", "dedup")] == ["done"] * 3

    scenes = client.get("/api/books/我的书/scenes").json()
    assert [s["id"] for s in scenes] == ["S-0001", "S-0002"]
    assert "text" not in scenes[0]
    one = client.get("/api/books/我的书/scenes/S-0002").json()
    assert one["text"].endswith("多写了一句。")

    [g] = client.get("/api/books/我的书/versions").json()["groups"]
    assert g["members"] == ["S-0001", "S-0002"]
    assert g["main"] == "S-0002"  # 更长
    r = client.put(f"/api/books/我的书/versions/{g['id']}/main", json={"scene_id": "S-0001"})
    assert r.json()["main_by"] == "author"

    r = client.get("/api/books/我的书/source", params={"path": "稿/1甲.txt"})
    assert r.json()["text"].startswith("第一章 甲")


def test_errors(client, src):
    client.post("/api/books", json={"title": "我的书"})
    assert client.post("/api/books/我的书/steps/cards/run").status_code == 400
    assert client.post("/api/books/我的书/import", json={"folder": str(src / "没有")}).status_code == 400
    assert client.get("/api/books/我的书/scenes/..%2Fbook").status_code == 404
    assert client.get("/api/books/我的书/scenes/S-0001").status_code == 404
    assert client.get("/api/books/我的书/source", params={"path": "../book.json"}).status_code == 404
    assert client.put("/api/books/我的书/versions/G-001/main", json={"scene_id": "S-0001"}).status_code == 404
    assert client.get("/api/jobs/nope").status_code == 404


def test_busy_returns_409(client):
    client.post("/api/books", json={"title": "我的书"})
    gate = threading.Event()
    job = client.app.state.runner.submit("x", "我的书", lambda p: gate.wait(5) and {})
    assert client.post("/api/books/我的书/steps/split/run").status_code == 409
    assert client.get("/api/jobs/current").json()["id"] == job.id
    gate.set()
    client.app.state.runner.wait(job.id)


def test_interrupted_step_recovered_on_startup(tmp_path):
    c1 = TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",)))
    c1.post("/api/books", json={"title": "我的书"})
    from ligaotai.book import open_book

    open_book(tmp_path / "书库", "我的书").set_step("split", "running")
    c2 = TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",)))
    assert c2.get("/api/books/我的书").json()["steps"]["split"]["status"] == "failed"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_api.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'ligaotai.api'`

- [ ] **Step 3: 实现 api.py**

`src/ligaotai/api.py`：
```python
"""FastAPI 应用。只给本机用：只认 127.0.0.1 / localhost 的 Host，不开 CORS。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel

from . import __version__
from .book import Book, create_book, list_books, open_book, recover_interrupted
from .config import APP_DIR, AppConfig, library_path, load_config, save_config
from .dedup import run_dedup, set_main
from .fsutil import ensure_within, read_json
from .importer import run_import
from .jobs import BusyError, JobRunner
from .readers import read_text
from .scenes import get_scene, load_scenes, run_split

STEP_RUNNERS = {"split": run_split, "dedup": run_dedup}


class NewBook(BaseModel):
    title: str


class ImportReq(BaseModel):
    folder: str


class MainReq(BaseModel):
    scene_id: str


def create_app(
    app_dir: Path = APP_DIR, allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")
) -> FastAPI:
    app = FastAPI(title="理稿台", version=__version__)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))
    runner = JobRunner()
    app.state.runner = runner

    def library() -> Path:
        lib = library_path(load_config(app_dir), app_dir)
        lib.mkdir(parents=True, exist_ok=True)
        return lib

    recover_interrupted(library())

    def get_book(name: str) -> Book:
        try:
            return open_book(library(), name)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "没有这本书")

    def submit(book: Book, step: str, fn: Callable[[Callable], dict]) -> dict:
        def work(progress: Callable) -> dict:
            book.set_step(step, "running")
            try:
                return fn(progress)
            except Exception as e:
                book.set_step(step, "failed", {"error": f"{type(e).__name__}: {e}"})
                raise

        try:
            return runner.submit(step, book.name, work).to_dict()
        except BusyError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/config")
    def get_config() -> dict:
        cfg = load_config(app_dir)
        return {**cfg.model_dump(), "library_path": str(library_path(cfg, app_dir))}

    @app.put("/api/config")
    def put_config(cfg: AppConfig) -> dict:
        save_config(cfg, app_dir)
        return get_config()

    @app.get("/api/books")
    def books() -> list:
        return list_books(library())

    @app.post("/api/books", status_code=201)
    def new_book(req: NewBook) -> dict:
        try:
            b = create_book(library(), req.title)
        except FileExistsError:
            raise HTTPException(409, "这本书已经有了")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"name": b.name, **b.load()}

    @app.get("/api/books/{name}")
    def book_meta(name: str) -> dict:
        b = get_book(name)
        return {"name": b.name, **b.load()}

    @app.post("/api/books/{name}/import", status_code=202)
    def do_import(name: str, req: ImportReq) -> dict:
        b = get_book(name)
        folder = Path(req.folder)
        if not folder.is_dir():
            raise HTTPException(400, f"文件夹不存在：{req.folder}")
        return submit(b, "import", lambda p: run_import(b, folder, p))

    @app.post("/api/books/{name}/steps/{step}/run", status_code=202)
    def run_step(name: str, step: str) -> dict:
        b = get_book(name)
        fn = STEP_RUNNERS.get(step)
        if fn is None:
            raise HTTPException(400, f"这一步现在还不能跑：{step}")
        return submit(b, step, lambda p: fn(b, p))

    @app.get("/api/jobs/current")
    def current_job() -> dict | None:
        job = runner.current()
        return job.to_dict() if job else None

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = runner.get(job_id)
        if job is None:
            raise HTTPException(404, "没有这个任务")
        return job.to_dict()

    @app.get("/api/books/{name}/scenes")
    def scenes(name: str, include_removed: bool = False) -> list:
        b = get_book(name)
        return [s.meta() for s in load_scenes(b) if include_removed or not s.removed]

    @app.get("/api/books/{name}/scenes/{sid}")
    def scene(name: str, sid: str) -> dict:
        b = get_book(name)
        try:
            sc = get_scene(b, sid)
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, "没有这个场景")
        return {**sc.meta(), "text": sc.text}

    @app.get("/api/books/{name}/versions")
    def versions(name: str) -> dict:
        b = get_book(name)
        return read_json(b.versions_path, {"params": {}, "groups": []})

    @app.put("/api/books/{name}/versions/{gid}/main")
    def put_main(name: str, gid: str, req: MainReq) -> dict:
        b = get_book(name)
        try:
            return set_main(b, gid, req.scene_id)
        except KeyError:
            raise HTTPException(404, "没有这个版本组")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/books/{name}/source")
    def source(name: str, path: str) -> dict:
        b = get_book(name)
        files = read_json(b.manifest_path, {"files": {}})["files"]
        if path not in files:
            raise HTTPException(404, "没有这个原稿")
        text, enc = read_text(ensure_within(b.originals_dir, b.originals_dir / path))
        return {"path": path, "encoding": enc, "text": text}

    return app
```

- [ ] **Step 4: 实现 __main__.py**

`src/ligaotai/__main__.py`：
```python
"""python -m ligaotai：在 127.0.0.1:8765 启动理稿台后端。"""

import uvicorn

from .api import create_app

HOST, PORT = "127.0.0.1", 8765


def main() -> None:
    uvicorn.run(create_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_api.py -q`
Expected: `8 passed`

- [ ] **Step 6: 手动起一次服务确认能启动**

Run（后台跑）: `uv run python -m ligaotai`
然后: `curl -s http://127.0.0.1:8765/api/health`
Expected: `{"ok":true,"version":"0.1.0"}`；确认后停掉服务。

- [ ] **Step 7: Commit**

```bash
git add src/ligaotai/api.py src/ligaotai/__main__.py tests/test_api.py
git commit -m "feat: API（书/导入/切场景/查重/任务/场景/版本组/原稿）"
```

## Task 13: 弄乱脚本 tools/scramble.py

**Files:**
- Create: `tools/scramble.py`
- Modify: `tests/helpers.py`（加 `make_chapters`）
- Test: `tests/test_scramble.py`

输入一本按「第X回」分好的书，输出一个乱稿文件夹和一份标准答案（spec 11.3）。同一个种子每次生成的结果完全一样。

弄乱的手法（括号里是给 100 回西游记的默认数量）：
1. **删章**（5 回，不删第一回和最后一回）→ 制造缺口。
2. **截断**（5 回，保留 40%–70%，切在段落边界）→ 制造「写到一半」。
3. **别名**（3 个新别名各替换进 15 回）：悟空→金箍郎、八戒→天蓬郎、唐僧→御弟師父。这三个名字已查过，原书里一次都没出现；脚本会再检查一遍，撞了就报错。
4. **整章重写版**（10 回）：整章复制一份，按句子随机删 8%、改 8%（换个词或补一句）、加 4% 的句子，当作「同一场景的第二版」。
5. **片段重写版**（5 回）：从章节前 2600 字里截一段 1200–2400 字的连续段落，轻改（删 3%、改 3%、加 2%），当作「写过的一个片段」。
6. **拆文件**：每回拆成 1–3 个文件（切在段落边界），只有第一个文件带回目；有重写版的回不拆，保持一个文件。
7. **乱命名**：`新建文本文档 (12).txt`、`草稿042.txt`、`片段_3fa1.md`、`未命名7.txt` 等，随机放进 `旧稿/`、`备份/2019/`、`手机导出/` 等子目录。
8. **乱格式**：约 70% txt、20% md、10% docx；txt 里约 15% 存成 GBK（用 gb18030 编码写，西游记里有 2 个 GBK 装不下的字）。
9. **乱时间**：文件修改时间随机分布在 2018–2023 年。

「弄乱」只动需要动的部分，没动过的章节正文原样保留（包括原书自带的连续空行），这样也顺带检验切场景对原书格式的处理。

标准答案 `<out>-答案.json`（放在乱稿文件夹**外面**）：
```json
{
  "seed": 7, "chapters": 100,
  "deleted": [12, 40],
  "truncated": [{"chapter": 23, "kept_ratio": 0.55}],
  "variants": [{"chapter": 33, "kind": "variant_full", "file": "旧稿/草稿042.txt", "original_file": "未命名7.txt"}],
  "aliases": [{"replaces": "悟空", "alias": "金箍郎", "canonical": "孫悟空", "chapters": [3, 8]}],
  "files": [{"path": "旧稿/草稿042.txt", "format": "txt", "encoding": "utf-8", "chapter": 33, "piece": 1, "pieces": 1, "kind": "variant_full"}]
}
```

- [ ] **Step 1: 给 helpers 加合成书**

在 `tests/helpers.py` 末尾追加：
```python
def make_chapters(n: int, seed: int = 0) -> list:
    """合成一本 n 回的小书，每回约 6000 字，中间一句带「悟空 / 八戒 / 唐僧」。"""
    from tools.scramble import Chapter

    chapters = []
    for num in range(1, n + 1):
        body = (
            gen_text(seed * 1000 + num * 2, 2990)
            + "\n\n悟空說道，八戒和唐僧都在。\n\n"
            + gen_text(seed * 1000 + num * 2 + 1, 2990)
        )
        chapters.append(Chapter(num, f"第{num}回 標題{num}", body))
    return chapters
```

（用 2990 字而不是 3000，是为了生成的文本不以空行结尾，否则和后面拼的空行凑成「连续两个空行」，会被切成单独一块。）

- [ ] **Step 2: 写失败的测试**

`tests/test_scramble.py`：
```python
import json

import pytest
from helpers import make_chapters

from ligaotai.readers import read_text
from tools.scramble import main, parse_chapters, scramble, strip_gutenberg

SMALL = dict(n_delete=2, n_truncate=2, n_full=3, n_excerpt=2, alias_chapters=5)


def all_text(out, key, chapter=None, kind=None):
    parts = []
    for f in key["files"]:
        if chapter is not None and f["chapter"] != chapter:
            continue
        if kind is not None and f["kind"] != kind:
            continue
        parts.append(read_text(out / f["path"])[0])
    return "\n".join(parts)


def test_strip_and_parse_gutenberg_like():
    raw = (
        "The Project Gutenberg eBook\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\n\n"
        "Produced by Someone\n\n第一回     標題\n\n\n\n　　詩曰：\n正文一。\n\n"
        " 第二回 標題二\n正文二。\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\nlicense"
    )
    chapters = parse_chapters(strip_gutenberg(raw))
    assert [c.heading for c in chapters] == ["第一回     標題", "第二回 標題二"]
    assert chapters[0].body.startswith("　　詩曰：")
    assert chapters[1].body == "正文二。"


@pytest.fixture
def scrambled(tmp_path):
    out = tmp_path / "乱稿"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    return out, key


def test_counts_and_files_exist(scrambled):
    out, key = scrambled
    assert len(key["deleted"]) == 2
    assert len(key["truncated"]) == 2
    kinds = [f["kind"] for f in key["files"]]
    assert kinds.count("variant_full") == 3
    assert kinds.count("variant_excerpt") == 2
    assert all((out / f["path"]).exists() for f in key["files"])
    assert len({f["path"] for f in key["files"]}) == len(key["files"])
    assert {f["format"] for f in key["files"]} <= {"txt", "md", "docx"}
    assert not set(key["deleted"]) & {f["chapter"] for f in key["files"]}


def test_variants_point_to_single_file_originals(scrambled):
    _, key = scrambled
    by_path = {f["path"]: f for f in key["files"]}
    assert len(key["variants"]) == 5
    for v in key["variants"]:
        orig = by_path[v["original_file"]]
        assert (orig["kind"], orig["chapter"], orig["pieces"]) == ("original", v["chapter"], 1)


def test_deleted_chapter_text_is_gone(scrambled):
    out, key = scrambled
    chapters = make_chapters(20)
    everything = all_text(out, key)
    for num in key["deleted"]:
        assert chapters[num - 1].body[:100] not in everything


def test_aliases_applied(scrambled):
    out, key = scrambled
    truncated = {t["chapter"] for t in key["truncated"]}
    for a in key["aliases"]:
        assert len(a["chapters"]) == 5
        num = next(c for c in a["chapters"] if c not in truncated)
        text = all_text(out, key, chapter=num, kind="original")
        assert a["alias"] in text
        assert a["replaces"] not in text


def test_deterministic(tmp_path):
    k1 = scramble(make_chapters(20), tmp_path / "a", seed=3, **SMALL)
    k2 = scramble(make_chapters(20), tmp_path / "b", seed=3, **SMALL)
    assert k1 == k2


def test_alias_collision_raises(tmp_path):
    chapters = make_chapters(20)
    chapters[5].body += "金箍郎"
    with pytest.raises(ValueError):
        scramble(chapters, tmp_path / "x", seed=3, **SMALL)


def test_cli_writes_key_outside_folder(tmp_path):
    src = tmp_path / "book.txt"
    src.write_text(
        "\n".join(f"{c.heading}\n\n{c.body}\n" for c in make_chapters(30)), encoding="utf-8"
    )
    out = tmp_path / "乱稿"
    main(["--src", str(src), "--out", str(out), "--seed", "5"])
    key = json.loads((tmp_path / "乱稿-答案.json").read_text(encoding="utf-8"))
    assert key["chapters"] == 30
    assert not (out / "乱稿-答案.json").exists()
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_scramble.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'tools.scramble'`

- [ ] **Step 4: 实现**

`tools/scramble.py`：
```python
"""把一本按「第X回」分好的书弄乱，生成带标准答案的乱稿，用来验收理稿台。

用法：
  uv run python tools/scramble.py --src data/xiyouji-pg23962.txt --out data/乱稿-西游记 --seed 7
生成乱稿文件夹 <out>/ 和标准答案 <out>-答案.json（答案放在文件夹外面，免得被一起导入）。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from docx import Document

DEFAULT_ALIASES = [
    {"replaces": "悟空", "alias": "金箍郎", "canonical": "孫悟空"},
    {"replaces": "八戒", "alias": "天蓬郎", "canonical": "豬八戒"},
    {"replaces": "唐僧", "alias": "御弟師父", "canonical": "唐三藏"},
]
FOLDERS = ["", "旧稿", "备份/2019", "备份/2020-重写", "手机导出", "杂"]
FILLERS = ["他心下暗暗思量。", "一時間無人答話。", "眾人都不做聲。", "這話且按下不題。"]
SUBS = [("道：", "說道："), ("卻", "却"), ("那", "這"), ("了", "咧")]
T_START, T_END = 1514736000, 1703980800  # 2018-01-01 ~ 2023-12-31

_HEADING = re.compile(r"^[ \t　]*第\S{1,4}回.*$", re.M)
_PARA_BREAK = re.compile(r"\n(?:[ \t　]*\n)+")
_LEADING_BLANK = re.compile(r"^(?:[ \t　]*\n)+")
_SENTENCE = re.compile(r"(?<=[。！？])")


@dataclass
class Chapter:
    num: int      # 从 1 起
    heading: str  # 回目那一行，去掉首尾空白
    body: str     # 回目之后的正文，去掉开头空行和结尾空白


def strip_gutenberg(raw: str) -> str:
    raw = raw.replace("\r\n", "\n")
    s, e = raw.find("*** START OF"), raw.find("*** END OF")
    if s == -1 or e == -1:
        return raw
    body = raw[raw.index("\n", s) + 1 : e]
    return re.sub(r"^Produced by.*$", "", body, flags=re.M)


def parse_chapters(body: str) -> list[Chapter]:
    ms = list(_HEADING.finditer(body))
    chapters = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(body)
        text = _LEADING_BLANK.sub("", body[m.end() + 1 : end]).rstrip()
        chapters.append(Chapter(i + 1, m.group(0).strip(" \t　"), text))
    return chapters


def para_cuts(body: str) -> list[int]:
    return [m.start() for m in _PARA_BREAK.finditer(body)]


def cut_at_ratio(body: str, ratio: float) -> str:
    cuts = para_cuts(body)
    target = len(body) * ratio
    pos = min(cuts, key=lambda c: abs(c - target)) if cuts else int(target)
    return body[:pos].rstrip()


def split_body(body: str, k: int) -> list[str]:
    cuts = para_cuts(body)
    if k <= 1 or not cuts:
        return [body]
    chosen = sorted({min(cuts, key=lambda c: abs(c - len(body) * j / k)) for j in range(1, k)})
    pieces, prev = [], 0
    for c in chosen:
        pieces.append(body[prev:c].strip("\n"))
        prev = c
    pieces.append(body[prev:].strip("\n"))
    return [p for p in pieces if p.strip()]


def pick_excerpt(body: str, rng: random.Random) -> str:
    starts = [0] + para_cuts(body)
    cands = [(a, b) for a in starts for b in starts if 1200 <= b - a <= 2400 and b <= 2600]
    a, b = rng.choice(cands) if cands else (0, min(len(body), 2000))
    return body[a:b].strip()


def mutate(text: str, rng: random.Random, drop=0.08, modify=0.08, add=0.04) -> str:
    """按句子随机删、改、加。删掉的句子保留它开头的换行，段落结构不乱。"""
    out = []
    for s in _SENTENCE.split(text):
        r = rng.random()
        if s.strip() and r < drop:
            out.append(re.match(r"\s*", s).group(0))
        elif s.strip() and r < drop + modify:
            old, new = rng.choice(SUBS)
            out.append(s.replace(old, new, 1) if old in s else s + rng.choice(FILLERS))
        elif s.strip() and r < drop + modify + add:
            out.append(s + rng.choice(FILLERS))
        else:
            out.append(s)
    return "".join(out)


class NameGen:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.used: set[str] = set()

    def next(self, fmt: str) -> str:
        while True:
            n = self.rng.randint(1, 999)
            stem = self.rng.choice([
                f"新建文本文档 ({n})", f"草稿{n:03d}", f"片段_{self.rng.randrange(16**4):04x}",
                f"未命名{n}", f"稿子{n}", f"{n}",
            ])
            folder = self.rng.choice(FOLDERS)
            rel = f"{folder}/{stem}.{fmt}" if folder else f"{stem}.{fmt}"
            if rel not in self.used:
                self.used.add(rel)
                return rel


def write_file(path: Path, text: str, fmt: str, enc: str, heading_first: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "docx":
        doc = Document()
        for i, line in enumerate(text.split("\n")):
            if i == 0 and heading_first:
                doc.add_heading(line, level=1)
            else:
                doc.add_paragraph(line)
        doc.save(str(path))
    else:
        path.write_bytes(text.encode(enc))


def scramble(
    chapters: list[Chapter],
    out_dir: Path,
    seed: int,
    aliases: list[dict] = DEFAULT_ALIASES,
    n_delete: int = 5,
    n_truncate: int = 5,
    n_full: int = 10,
    n_excerpt: int = 5,
    alias_chapters: int = 15,
) -> dict:
    rng = random.Random(seed)
    source_text = "\n".join(f"{c.heading}\n{c.body}" for c in chapters)
    for a in aliases:
        if a["alias"] in source_text:
            raise ValueError(f"alias already appears in source: {a['alias']}")

    pool = [c.num for c in chapters[1:-1]]

    def take(k: int) -> list[int]:
        chosen = sorted(rng.sample(pool, k))
        pool[:] = [x for x in pool if x not in chosen]
        return chosen

    deleted = take(n_delete)
    truncated = take(n_truncate)
    full = take(n_full)
    excerpt = take(n_excerpt)
    kept = [c for c in chapters if c.num not in deleted]
    alias_log = [
        {**a, "chapters": sorted(rng.sample([c.num for c in kept], min(alias_chapters, len(kept))))}
        for a in aliases
    ]

    final: dict[int, tuple[str, str]] = {}
    truncated_log = []
    for c in kept:
        heading, body = c.heading, c.body
        if c.num in truncated:
            body = cut_at_ratio(body, rng.uniform(0.4, 0.7))
            truncated_log.append({"chapter": c.num, "kept_ratio": round(len(body) / len(c.body), 3)})
        for a in alias_log:
            if c.num in a["chapters"]:
                heading = heading.replace(a["replaces"], a["alias"])
                body = body.replace(a["replaces"], a["alias"])
        final[c.num] = (heading, body)

    files: list[dict] = []
    for c in kept:
        heading, body = final[c.num]
        k = 1 if c.num in full or c.num in excerpt else rng.choice([1, 1, 2, 2, 3])
        pieces = split_body(body, k)
        for i, piece in enumerate(pieces, 1):
            files.append({
                "text": f"{heading}\n\n{piece}" if i == 1 else piece,
                "chapter": c.num, "piece": i, "pieces": len(pieces),
                "kind": "original", "heading_first": i == 1,
            })
    for num in full:
        heading, body = final[num]
        files.append({
            "text": f"{heading}\n\n{mutate(body, rng)}", "chapter": num, "piece": 1,
            "pieces": 1, "kind": "variant_full", "heading_first": True,
        })
    for num in excerpt:
        excerpt_text = mutate(pick_excerpt(final[num][1], rng), rng, 0.03, 0.03, 0.02)
        files.append({
            "text": excerpt_text, "chapter": num, "piece": 1, "pieces": 1,
            "kind": "variant_excerpt", "heading_first": False,
        })

    rng.shuffle(files)
    names = NameGen(rng)
    for f in files:
        fmt = rng.choices(["txt", "md", "docx"], weights=[7, 2, 1])[0]
        enc = "docx" if fmt == "docx" else ("gb18030" if fmt == "txt" and rng.random() < 0.15 else "utf-8")
        rel = names.next(fmt)
        path = out_dir / rel
        write_file(path, f.pop("text"), fmt, enc, f.pop("heading_first"))
        t = rng.uniform(T_START, T_END)
        os.utime(path, (t, t))
        f.update(path=rel, format=fmt, encoding=enc)

    original_of = {f["chapter"]: f["path"] for f in files if f["kind"] == "original" and f["pieces"] == 1}
    variants = [
        {"chapter": f["chapter"], "kind": f["kind"], "file": f["path"], "original_file": original_of[f["chapter"]]}
        for f in files
        if f["kind"] != "original"
    ]
    variants.sort(key=lambda v: (v["chapter"], v["kind"]))
    files.sort(key=lambda f: f["path"])
    return {
        "seed": seed,
        "chapters": len(chapters),
        "deleted": deleted,
        "truncated": truncated_log,
        "variants": variants,
        "aliases": alias_log,
        "files": files,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="scramble a chaptered book into a messy manuscript")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        sys.exit("output folder is not empty")
    raw = Path(args.src).read_text(encoding="utf-8")
    chapters = parse_chapters(strip_gutenberg(raw))
    key = scramble(chapters, out, args.seed)
    key_path = out.parent / f"{out.name}-答案.json"
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"chapters={len(chapters)} files={len(key['files'])} "
        f"deleted={len(key['deleted'])} variants={len(key['variants'])}"
    )


if __name__ == "__main__":
    main()
```

注意 `test_cli_writes_key_outside_folder` 用的是 30 回的合成书，而 `main` 用的是默认数量（删 5、截 5、整章重写 10、片段 5，共 25 回，从中间 28 回里挑），所以够用。

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_scramble.py -q`
Expected: `8 passed`

- [ ] **Step 6: Commit**

```bash
git add tools/scramble.py tests/helpers.py tests/test_scramble.py
git commit -m "feat: 弄乱脚本（删章/截断/别名/重写版/拆文件/乱命名乱编码）"
```

## Task 14: 查重验收脚本 tools/eval_dedup.py

**Files:**
- Create: `tools/eval_dedup.py`
- Test: `tests/test_eval_dedup.py`

流程：在一个验收用的书库里新建一本书 → 导入乱稿 → 切场景 → 查重 → 对照答案。

判定：答案里的每一个重写版（整章 / 片段），只要有**任意一块**重写版的场景和**任意一块**原版的场景落在同一个版本组里，就算找到。召回率 = 找到 / 总数，门槛 ≥ 90%（spec 11.3）。

另外记录（不设门槛）：
- 跨章节的版本组（组里的块来自不同的回）——基本就是误合并，列出来人工看；
- 场景总数、碎片数、场景字数的最小 / 中位 / 最大值，用来判断切场景切得合不合理。

- [ ] **Step 1: 写失败的测试**

`tests/test_eval_dedup.py`：
```python
from helpers import make_chapters

from tools.eval_dedup import run_eval
from tools.scramble import scramble


def test_end_to_end_recall_on_synthetic_book(tmp_path):
    out = tmp_path / "乱稿"
    key = scramble(
        make_chapters(20), out, seed=3,
        n_delete=2, n_truncate=2, n_full=3, n_excerpt=2, alias_chapters=5,
    )
    report = run_eval(out, key, tmp_path / "书库")
    assert report["variants"] == 5
    assert report["recall"] == 1.0, report["missed"]
    assert report["cross_chapter_groups"] == []
    assert report["pass"] is True
    assert report["scenes"] > 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_eval_dedup.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'tools.eval_dedup'`

- [ ] **Step 3: 实现**

`tools/eval_dedup.py`：
```python
"""验收：导入乱稿 → 切场景 → 查重，对照标准答案算查重召回率。

用法：
  uv run python tools/eval_dedup.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json
报告写到 --report（默认 data/验收-查重.json）。终端只打 ASCII 数字，中文内容看报告文件。
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ligaotai.book import Book, create_book
from ligaotai.dedup import run_dedup
from ligaotai.fsutil import read_json, safe_name
from ligaotai.importer import run_import
from ligaotai.scenes import FRAGMENT, load_scenes, run_split

PASS_RECALL = 0.9


def evaluate(book: Book, key: dict, root: str) -> dict:
    scenes = [s for s in load_scenes(book) if not s.removed]
    source_of = {s.id: s.source for s in scenes}
    ids_by_file: dict[str, list[str]] = defaultdict(list)
    for s in scenes:
        ids_by_file[s.source].append(s.id)
    groups = read_json(book.versions_path, {"groups": []})["groups"]
    group_of = {m: g["id"] for g in groups for m in g["members"]}
    chapter_of = {f"{root}/{f['path']}": f["chapter"] for f in key["files"]}

    found, missed = [], []
    by_kind: dict[str, dict] = defaultdict(lambda: {"total": 0, "found": 0})
    for v in key["variants"]:
        vs = ids_by_file[f"{root}/{v['file']}"]
        os_ = ids_by_file[f"{root}/{v['original_file']}"]
        hit = any(a in group_of and group_of[a] == group_of.get(b) for a in vs for b in os_)
        by_kind[v["kind"]]["total"] += 1
        if hit:
            by_kind[v["kind"]]["found"] += 1
            found.append(v)
        else:
            missed.append({**v, "variant_scenes": vs, "original_scenes": os_})

    cross = []
    for g in groups:
        chapters = sorted({chapter_of.get(source_of[m], -1) for m in g["members"]})
        if len(chapters) > 1:
            cross.append({"group": g["id"], "members": g["members"], "chapters": chapters})

    chars = [s.chars for s in scenes]
    total = len(key["variants"])
    recall = len(found) / total if total else 1.0
    return {
        "variants": total,
        "found": len(found),
        "recall": round(recall, 4),
        "pass": recall >= PASS_RECALL,
        "by_kind": dict(by_kind),
        "missed": missed,
        "groups": len(groups),
        "cross_chapter_groups": cross,
        "scenes": len(scenes),
        "fragments": sum(s.kind_hint == FRAGMENT for s in scenes),
        "scene_chars": {
            "min": min(chars, default=0),
            "median": statistics.median(chars) if chars else 0,
            "max": max(chars, default=0),
        },
    }


def run_eval(folder: Path, key: dict, library: Path) -> dict:
    folder = Path(folder).resolve()
    title = f"验收-{folder.name}-{datetime.now():%Y%m%d-%H%M%S-%f}"
    book = create_book(library, title)
    run_import(book, folder)
    run_split(book)
    run_dedup(book)
    report = evaluate(book, key, safe_name(folder.name))
    report["book"] = str(book.root)
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="evaluate dedup recall against a scramble answer key")
    ap.add_argument("--folder", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--library", default="data/验收书库")
    ap.add_argument("--report", default="data/验收-查重.json")
    args = ap.parse_args(argv)
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    report = run_eval(Path(args.folder), key, Path(args.library))
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"variants={report['variants']} found={report['found']} recall={report['recall']} "
        f"pass={report['pass']} scenes={report['scenes']} fragments={report['fragments']} "
        f"groups={report['groups']} cross_chapter_groups={len(report['cross_chapter_groups'])}"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_eval_dedup.py -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tools/eval_dedup.py tests/test_eval_dedup.py
git commit -m "feat: 查重验收脚本（对照答案算召回率）"
```

---

## Task 15: 用真西游记跑验收

**Files:**
- Create: `docs/验收记录/2026-09-计划1-查重.md`（日期按实际执行那天改）

这一步不写新代码，是拿真书检验前面的东西。**不许为了过门槛去调阈值或改弄乱参数**：没过就按下面的排查步骤找原因，把原因和改法报给作者再动。

- [ ] **Step 1: 下载西游记原文（公版，古登堡 #23962，繁体）**

```bash
mkdir -p data
curl -sL -o data/xiyouji-pg23962.txt https://www.gutenberg.org/cache/epub/23962/pg23962.txt
wc -c data/xiyouji-pg23962.txt
```
Expected: `2264069 data/xiyouji-pg23962.txt`（2026-09-11 实测的大小；对不上就先打开看看是不是下到了错误页）

- [ ] **Step 2: 生成乱稿**

Run: `uv run python tools/scramble.py --src data/xiyouji-pg23962.txt --out data/乱稿-西游记 --seed 7`
Expected: `chapters=100 files=<约200> deleted=5 variants=15`

`chapters` 不是 100，说明回目正则漏了或多了，先修 `tools/scramble.py` 的 `_HEADING`（2026-09-11 用 `^\s*第\S{1,4}回` 实测正好 100 个）。

- [ ] **Step 3: 跑验收**

Run: `uv run python tools/eval_dedup.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json`
Expected: 一行 ASCII 结果，`recall` ≥ 0.9，`pass=True`

然后用 Read 工具打开 `data/验收-查重.json` 看 `missed`、`cross_chapter_groups`、`scene_chars`。

- [ ] **Step 4: 没过门槛时的排查（过了就跳过）**

使用 superpowers:systematic-debugging。先看 `missed` 里每一条的 `variant_scenes` 和 `original_scenes`，打开对应的 `场景/S-xxxx.md` 比对：
- 原版和重写版的块是不是切在很不一样的位置（已知局限）？
- 是不是整块被当成了碎片（< 100 个字串）而没参与查重？
- 用 `ligaotai.dedup.shingles` 手算这两块的 Jaccard 和包含度，看差多少。

把结论和打算怎么改写下来，报给作者，**等作者点头再改**。

- [ ] **Step 5: 顺带检查切场景质量**

从 `data/验收书库/验收-*/场景/` 里随机打开 5 个场景文件，确认：
- 回目被识别成了标题（`heading` 字段是回目）；
- 没有「只有一行回目」的空块；
- 场景字数大多在 1000–5000 之间（对照报告里的 `scene_chars`）。

有问题记进验收记录的「发现的问题」一节，不在本计划里修，除非作者要求。

- [ ] **Step 6: 写验收记录**

`docs/验收记录/2026-09-计划1-查重.md` 按下面的结构写，数字全部从 `data/验收-查重.json` 抄：
```markdown
# 计划① 验收：查重（人造乱稿《西游记》）

- 日期：
- 原文：古登堡 #23962（繁体，100 回，约 75.8 万字）
- 乱稿：seed=7，删 5 回、截断 5 回、3 个新别名各 15 回、整章重写版 10、片段重写版 5
- 参数：book.json 默认值（jaccard 0.5 / 包含度 0.8 / 5 字串 / 最少 100 字串 / 套话 df 20）

## 结果
| 指标 | 结果 | 门槛 |
|---|---|---|
| 重写版召回率（总） | found / variants = recall | ≥ 90% |
| 整章重写版 | by_kind.variant_full | — |
| 片段重写版 | by_kind.variant_excerpt | — |
| 跨章节版本组（疑似误合并） | 个数 | 只记录 |
| 场景数 / 碎片数 | scenes / fragments | 只记录 |
| 场景字数 最小 / 中位 / 最大 | scene_chars | 只记录 |

## 漏掉的
（逐条列 missed：第几回、哪种重写版、原因）

## 发现的问题
（切场景质量检查里看到的）
```

- [ ] **Step 7: Commit**

```bash
git add docs/验收记录/
git commit -m "docs: 计划①查重验收记录（人造乱稿西游记）"
```

---

## Task 16: 收尾

- [ ] **Step 1: 全量测试**

Run: `uv run pytest -q`
Expected: 全部通过，0 failed

- [ ] **Step 2: 起服务冒烟**

Run（后台跑）: `uv run python -m ligaotai`，然后 `curl -s http://127.0.0.1:8765/api/health`
Expected: `{"ok":true,"version":"0.1.0"}`；确认后停掉服务。

- [ ] **Step 3: 看一眼 git 状态**

Run: `git status --short`
Expected: 没有未提交的文件（`data/`、`.venv/` 都被 gitignore 了）

- [ ] **Step 4: 交给作者**

用 superpowers:finishing-a-development-branch 决定怎么合并。汇报时给出：测试数、验收召回率、跨章节误合并个数、切场景发现的问题。

