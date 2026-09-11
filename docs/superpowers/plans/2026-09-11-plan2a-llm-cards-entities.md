# 理稿台 计划②a：接入模型 + 场景卡 + 实体合并 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接入 OpenAI 兼容的模型接口（默认 DeepSeek），做出流水线第 4 步「场景卡」和第 5 步「实体合并」（含作者确认用的接口），并用人造乱稿《西游记》验收「植入的别名被提议合并 ≥ 90%」。

**Architecture:** `llm.py` 里的 `LLMClient` 负责要 JSON、校验、带着问题重试、统计用量、写调用日志，真正发请求的 `OpenAIBackend` 用 OpenAI 官方 SDK，测试里换成假的 `FakeBackend`，所以全部测试不联网、不花钱。提示词放在仓库根目录 `prompts/`，一个任务一个 md 文件。第 4、5 步和计划①的步骤一样，是在任务队列线程里跑的 `run_xxx(book, client, progress)`，内部用 asyncio 并发调用模型，每处理完一项就落盘，所以暂停、崩溃后重跑会接着做。

**Tech Stack:** 在计划①的基础上加 `openai>=3.13`（官方 Python SDK，2026-09-11 最新 3.13.0；已实测 `chat.completions.create`、`extra_body`、`httpx.MockTransport` 在这个版本下可用）。

**设计依据：** `docs/superpowers/specs/2026-09-10-ligaotai-design.md` 第 5.2 节、第 6 章步骤 4–5、第 9、10、11 章。计划①的实现就是现在仓库里的代码。

**计划②的拆分：** spec 里的「计划②」拆成两份。本计划 ②a = 模型接入 + 步骤 4 + 步骤 5；下一份 ②b = 步骤 6 归线排序 + 步骤 7 档案/矛盾/地图 + 顺序验收（Kendall τ）。

**2026-09-11 查的 DeepSeek 官方文档（决定了默认配置）：**
- `deepseek-flash`：上下文 100 万 token，支持 JSON 输出。每百万 token 高峰价输入 $0.30、输出 $1.20，闲时半价（高峰 = 北京时间工作日 9–12 点、14–18 点）。`deepseek-v4-pro` 9 月 14 日起并入 Flash。
- JSON 模式：传 `response_format={"type": "json_object"}`，提示词里必须出现「json」并给示例；**偶尔会返回空内容**；`max_tokens` 太小会截断。
- **flash 默认开着思考模式，强度 high**。开关用请求体里的 `thinking: {"type": "enabled"/"disabled"}`，强度用 `reasoning_effort`（low/medium/high/max…）。思考模式下 `temperature` 不起作用。

**跟 spec 的偏差（执行时照这里做）：**
1. **两档模型各自控制思考模式**：批量档（场景卡）默认关思考（抽卡用不着，开着会让输出 token 翻几倍）；综合档（实体合并，以及计划②b 的归线、矛盾）默认开，强度 high。
2. **场景卡加一个 `organizations` 字段**。spec 5.2 没有，但步骤 5 要合并组织名。
3. **场景卡要核对原文**：`facts` 的 `quote`、人名 / 地名 / 组织名，去掉空白和标点后必须能在原文里找到。找不到就把问题反馈给模型重试；3 次后还有，就删掉这些条目并记在卡上（`dropped`），卡照样保存。
4. **实体合并改由模型对全部叫法归组**。spec 写的是「程序先找候选组，再交给模型判断」，但「金箍郎」和「悟空」这类外号一个字都不重合，字面规则找不到。所以改成：按类型把全部叫法连同原文上下文交给综合档模型归组，程序找到的「字面相近」只作为提示附上。叫法太多时分批，出现次数最多的一批放进每一批。
5. **作者确认过的实体组，重跑时原样保留**，里面的叫法不会被模型挪走。之后新出现的同一人物叫法会单独列出来，由作者手动合并。
6. **场景卡是否要重做，看卡上记的 `scene_hash` 和场景当前的 `hash` 是否一致**，不看计划①里那个粘性的 `stale` 标记。
7. **暂停 = 取消当前任务**。已经做完的卡都落了盘，重跑会接着做，不需要单独的「继续」逻辑。

**不做（留给后续计划）：** 步骤 6、7（计划②b）；网页界面（计划③）；录制真实模型返回做回放测试（先用手写的假返回）。

---

## 文件结构

```
ligaotai/
  pyproject.toml                加 openai 依赖
  prompts/
    cards.md                    场景卡提示词（步骤 4，批量档）
    entities.md                 实体合并提示词（步骤 5，综合档）
  src/ligaotai/
    config.py                   改：模型接口、两档模型、并发、单价、key 打码
    book.py                     改：场景卡 / 实体 / 日志的路径，用量累计
    llm.py                      新：Reply / Usage / LLMClient / OpenAIBackend / check_model
    prompts.py                  新：读 prompts/*.md，填变量
    cards.py                    新：场景卡字段、原文核对、步骤 4
    entities.py                 新：叫法汇总、字面提示、模型归组、步骤 5、作者的确认/改名/合并/拆分
    jobs.py                     改：暂停（取消）
    api.py                      改：跑 AI 步骤、测试连接、暂停、场景卡和实体的接口
  tests/
    conftest.py                 改：每个测试都清掉环境变量里的 key
    helpers.py                  改：FakeBackend、假场景卡、假的 AI 回复
    test_config.py test_book.py test_jobs.py test_api.py        改
    test_llm.py test_llm_openai.py test_prompts.py              新
    test_cards.py test_entities.py test_api_ai.py test_eval_entities.py   新
  tools/
    eval_entities.py            新：别名合并验收
  docs/验收记录/                  新增一份实体合并的验收记录
```

**路径约定：** 所有命令都在仓库根目录下执行，用 Git Bash。

**Windows 注意：**
- 终端显示中文会乱码。测试断言和脚本打印只用 ASCII，要看中文结果就写成文件再用 Read 工具读。
- 在工具参数里敲的反斜杠加 u 的转义序列会被变成真字符。本计划的代码里没有这种转义，也别加。
- 并行执行时，**禁止** `git stash` / `git checkout -- 文件` / `git reset` / `git restore`，只 `git add` 自己改的文件。

---

## Task 1: 依赖 + 模型配置 + key 打码

**Files:**
- Modify: `pyproject.toml`（dependencies 加 `"openai>=3.13"`）
- Modify: `src/ligaotai/config.py`（整个文件替换）
- Modify: `src/ligaotai/api.py`（`get_config` / `put_config` 两个接口）
- Modify: `tests/conftest.py`（加 autouse fixture）
- Test: `tests/test_config.py`、`tests/test_api.py`（追加）

要点：
- key 可以写在 `config.json` 里，也可以用环境变量 `LIGAOTAI_API_KEY`，前者优先。
- **接口永远不返回完整 key**：`GET /api/config` 只给 `sk-…abcd` 这种打码后的样子，外加 `has_key`、`key_from_env`。
- 界面提交配置时，key 字段是空的或还是打码的样子，就沿用原来的 key，这样改别的设置不会把 key 冲掉。
- 所有测试都要保证用不到真 key：conftest 里加一个自动生效的 fixture，清掉环境变量。

- [ ] **Step 1: 加依赖**

在 `pyproject.toml` 的 `dependencies` 列表末尾加一行 `"openai>=3.13",`，然后：

Run: `uv sync`
Expected: 装上 openai，`uv run python -c "import openai; print(openai.__version__)"` 打印 3.13 或更高。

- [ ] **Step 2: conftest 加 fixture**

在 `tests/conftest.py` 末尾追加：
```python
@pytest.fixture(autouse=True)
def _no_real_key(monkeypatch):
    """测试一律用不到真的 API key。"""
    monkeypatch.delenv("LIGAOTAI_API_KEY", raising=False)
```

- [ ] **Step 3: 写失败的测试**

在 `tests/test_config.py` 末尾追加：
```python
from ligaotai.config import KEY_ENV, apply_update, effective_key, mask_key, public_config


def test_model_defaults():
    cfg = AppConfig()
    assert cfg.api_base == "https://api.deepseek.com"
    assert (cfg.batch.model, cfg.batch.thinking, cfg.batch.json_mode) == ("deepseek-flash", "off", True)
    assert (cfg.synth.thinking, cfg.synth.effort, cfg.synth.max_tokens) == ("on", "high", 32768)
    assert cfg.concurrency == 8


def test_old_config_file_still_loads(tmp_path):
    (tmp_path / "config.json").write_text('{"library_dir": ""}', encoding="utf-8")
    assert load_config(tmp_path).batch.thinking == "off"


def test_effective_key_prefers_file_then_env(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "sk-from-env-123")
    assert effective_key(AppConfig()) == "sk-from-env-123"
    assert effective_key(AppConfig(api_key="sk-from-file-9")) == "sk-from-file-9"


def test_mask_key():
    assert mask_key("") == ""
    assert mask_key("sk-abcdefghijkl") == "sk-…ijkl"
    assert mask_key("short") == "…"


def test_public_config_never_shows_key(tmp_path):
    data = public_config(AppConfig(api_key="sk-abcdefghijkl"), tmp_path)
    assert "sk-abcdefghijkl" not in str(data)
    assert data["has_key"] is True and data["key_from_env"] is False
    assert data["library_path"] == str(tmp_path / "书库")


def test_apply_update_keeps_old_key():
    old = AppConfig(api_key="sk-abcdefghijkl")
    assert apply_update(old, AppConfig(api_key="")).api_key == "sk-abcdefghijkl"
    assert apply_update(old, AppConfig(api_key="sk-…ijkl")).api_key == "sk-abcdefghijkl"
    assert apply_update(old, AppConfig(api_key="sk-new-key-0000")).api_key == "sk-new-key-0000"
```

在 `tests/test_api.py` 末尾追加：
```python
def test_config_key_is_masked_and_kept(client, tmp_path):
    from ligaotai.config import load_config

    r = client.put("/api/config", json={"api_key": "sk-abcdefghijkl", "concurrency": 4})
    assert r.status_code == 200
    body = r.json()
    assert body["api_key"] == "sk-…ijkl" and body["has_key"] is True and body["concurrency"] == 4
    client.put("/api/config", json={"api_key": body["api_key"], "concurrency": 2})
    cfg = load_config(tmp_path)
    assert cfg.api_key == "sk-abcdefghijkl" and cfg.concurrency == 2
```

- [ ] **Step 4: 跑测试确认失败**

Run: `uv run pytest tests/test_config.py tests/test_api.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'KEY_ENV'` 等）

- [ ] **Step 5: 实现 config.py**

`src/ligaotai/config.py` 整个替换为：
```python
"""应用级配置：<应用目录>/config.json。API key 只放在这里（或环境变量），不进书文件夹。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .fsutil import read_json, write_json

# src/ligaotai/config.py → parents[2] 是仓库根目录
APP_DIR = Path(__file__).resolve().parents[2]
CONFIG_NAME = "config.json"
KEY_ENV = "LIGAOTAI_API_KEY"
MASK = "…"


class TierConfig(BaseModel):
    """一档模型。批量档抽场景卡，综合档做需要通盘考虑的判断。"""

    model: str = "deepseek-flash"
    thinking: Literal["on", "off", "default"] = "off"  # default = 不传，按接口自己的默认
    effort: str = ""  # 思考强度（reasoning_effort），空 = 不传
    json_mode: bool = True  # 传 response_format={"type": "json_object"}
    max_tokens: int = Field(8192, ge=256)


def _batch_tier() -> TierConfig:
    return TierConfig(thinking="off")


def _synth_tier() -> TierConfig:
    return TierConfig(thinking="on", effort="high", max_tokens=32768)


class AppConfig(BaseModel):
    library_dir: str = ""
    api_base: str = "https://api.deepseek.com"
    api_key: str = ""
    concurrency: int = Field(8, ge=1, le=64)
    timeout: float = Field(120, gt=0)  # 单次调用超时（秒）
    price_input: float = Field(0.30, ge=0)  # 美元 / 百万输入 token，默认按 deepseek-flash 高峰价（偏保守）
    price_output: float = Field(1.20, ge=0)  # 美元 / 百万输出 token
    batch: TierConfig = Field(default_factory=_batch_tier)
    synth: TierConfig = Field(default_factory=_synth_tier)


def load_config(app_dir: Path = APP_DIR) -> AppConfig:
    return AppConfig(**read_json(Path(app_dir) / CONFIG_NAME, {}))


def save_config(cfg: AppConfig, app_dir: Path = APP_DIR) -> None:
    write_json(Path(app_dir) / CONFIG_NAME, cfg.model_dump())


def library_path(cfg: AppConfig, app_dir: Path = APP_DIR) -> Path:
    return Path(cfg.library_dir) if cfg.library_dir else Path(app_dir) / "书库"


def effective_key(cfg: AppConfig) -> str:
    return cfg.api_key or os.environ.get(KEY_ENV, "")


def mask_key(key: str) -> str:
    if not key:
        return ""
    return key[:3] + MASK + key[-4:] if len(key) > 10 else MASK


def public_config(cfg: AppConfig, app_dir: Path = APP_DIR) -> dict:
    """给界面看的配置：key 只露头尾。"""
    key = effective_key(cfg)
    data = cfg.model_dump()
    data["api_key"] = mask_key(key)
    data["has_key"] = bool(key)
    data["key_from_env"] = bool(key) and not cfg.api_key
    data["library_path"] = str(library_path(cfg, app_dir))
    return data


def apply_update(old: AppConfig, new: AppConfig) -> AppConfig:
    """界面提交的配置里，key 是空的或还是打码的样子，就沿用原来的 key。"""
    if not new.api_key or MASK in new.api_key:
        return new.model_copy(update={"api_key": old.api_key})
    return new
```

- [ ] **Step 6: 改 api.py 的两个配置接口**

`src/ligaotai/api.py` 的 import 里，把
```python
from .config import APP_DIR, AppConfig, library_path, load_config, save_config
```
换成
```python
from .config import APP_DIR, AppConfig, apply_update, library_path, load_config, public_config, save_config
```
把 `get_config` 和 `put_config` 两个函数换成：
```python
    @app.get("/api/config")
    def get_config() -> dict:
        return public_config(load_config(app_dir), app_dir)

    @app.put("/api/config")
    def put_config(cfg: AppConfig) -> dict:
        save_config(apply_update(load_config(app_dir), cfg), app_dir)
        return get_config()
```

- [ ] **Step 7: 跑测试确认通过**

Run: `uv run pytest -q`
Expected: 全部通过（原来的 173 个 + 新增 7 个）

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/ligaotai/config.py src/ligaotai/api.py tests/conftest.py tests/test_config.py tests/test_api.py
git commit -m "feat: 模型配置（两档模型/思考开关/单价）与 key 打码"
```

---

## Task 2: 书的新路径 + 用量累计

**Files:**
- Modify: `src/ligaotai/book.py`
- Test: `tests/test_book.py`（追加）

要点：场景卡放 `场景卡/S-0001.json`，实体放 `实体.json`，模型调用日志放 `日志/`。每次跑 AI 步骤后，把这次的调用次数、token、估算费用累加进 `book.json` 的 `usage`（总计 + 分步骤），流水线页面要显示累计费用。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_book.py` 末尾追加：
```python
def test_new_paths(book):
    assert book.cards_dir.name == "场景卡"
    assert book.entities_path.name == "实体.json"
    assert book.logs_dir.name == "日志"


def test_add_usage_accumulates(book):
    book.add_usage("cards", calls=3, prompt_tokens=1000, completion_tokens=200, cost_usd=0.0012)
    book.add_usage("cards", calls=1, prompt_tokens=10, completion_tokens=5, cost_usd=0.0001)
    book.add_usage("entities", calls=2, prompt_tokens=50, completion_tokens=50, cost_usd=0.002)
    usage = book.load()["usage"]
    assert usage["total"] == {"calls": 6, "prompt_tokens": 1060, "completion_tokens": 255, "cost_usd": 0.0033}
    assert usage["by_step"]["cards"]["calls"] == 4
    assert usage["by_step"]["entities"]["cost_usd"] == 0.002
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_book.py -q`
Expected: 新测试 FAIL（`AttributeError: 'Book' object has no attribute 'cards_dir'`）

- [ ] **Step 3: 实现**

在 `src/ligaotai/book.py` 的 `Book` 类里，`versions_path` 属性后面加：
```python
    @property
    def cards_dir(self) -> Path:
        return self.root / "场景卡"

    @property
    def entities_path(self) -> Path:
        return self.root / "实体.json"

    @property
    def logs_dir(self) -> Path:
        return self.root / "日志"
```

在 `mark_downstream_outdated` 方法后面加：
```python
    def add_usage(
        self, step: str, calls: int, prompt_tokens: int, completion_tokens: int, cost_usd: float
    ) -> None:
        """把一次运行的模型用量累加进 book.json 的 usage（总计 + 分步骤）。"""

        def fn(data: dict) -> None:
            usage = data.setdefault("usage", {"total": _zero_usage(), "by_step": {}})
            for bucket in (usage["total"], usage["by_step"].setdefault(step, _zero_usage())):
                bucket["calls"] += calls
                bucket["prompt_tokens"] += prompt_tokens
                bucket["completion_tokens"] += completion_tokens
                bucket["cost_usd"] = round(bucket["cost_usd"] + cost_usd, 6)

        self.update(fn)
```

在模块里 `_outdate_after` 函数前面加：
```python
def _zero_usage() -> dict:
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_book.py -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/book.py tests/test_book.py
git commit -m "feat: 场景卡/实体/日志路径与模型用量累计"
```

## Task 3: 模型调用核心 LLMClient

**Files:**
- Create: `src/ligaotai/llm.py`（本任务先写 Reply / Usage / 异常 / parse_json / LLMClient）
- Modify: `tests/helpers.py`（加 `FakeBackend`）
- Test: `tests/test_llm.py`

`LLMClient.chat_json(tier_name, system, user, check, tag=...)` 的流程：
1. 发 `[system, user]`；拿到回复后先累加用量、写日志（`日志/<tag>-<第几次>.json`，内容是请求消息和回复，**不含 key**）。
2. 回复是空的 → 记问题「模型返回了空内容」，原样再发一次。
3. `finish_reason == "length"`（被截断）→ `max_tokens` 翻倍（最多 65536），原样再发一次。截断的内容不喂回去。
4. 不是合法 JSON → 把模型的回复和一条「你上一次的输出有这些问题……」追加进对话再发。
5. 是 JSON 就交给 `check(data)`，返回问题清单。没问题直接返回 `(data, [])`；有问题同 4 一样反馈重试。
6. 最多 3 次。3 次都没合格：只要中间有一次解析成功，就返回最后一次解析成功的 `(data, problems)`，由调用方决定怎么处理；一次都没解析成功就抛 `LLMError`。
7. 后端抛的异常：带 `status_code` 401/402/403（key 不对、欠费、没权限）→ `FatalLLMError`，整个步骤都该停；其他 → `LLMError`，只算这一项失败。`asyncio.CancelledError` 不拦。
8. 并发：同一个 client 的所有调用共用一个 `asyncio.Semaphore(cfg.concurrency)`。

- [ ] **Step 1: 给 helpers 加 FakeBackend**

在 `tests/helpers.py` 顶部 import 区加 `import asyncio`，末尾追加：
```python
from ligaotai.llm import Reply


class FakeBackend:
    """假的模型接口：按顺序吐预设的回复，或者交给 handler(tier, messages) 现算。

    回复可以是字符串（当作 content）、Reply、或者异常实例（会被抛出）。
    """

    def __init__(self, replies=None, handler=None, delay=0.0):
        self.replies = list(replies or [])
        self.handler = handler
        self.delay = delay
        self.calls = []
        self.active = 0
        self.max_active = 0

    async def complete(self, tier, messages, max_tokens):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            self.calls.append({"tier": tier, "messages": [dict(m) for m in messages], "max_tokens": max_tokens})
            if self.delay:
                await asyncio.sleep(self.delay)
            out = self.handler(tier, messages) if self.handler else self.replies.pop(0)
            if isinstance(out, Exception):
                raise out
            if isinstance(out, Reply):
                return out
            return Reply(content=out, prompt_tokens=100, completion_tokens=20)
        finally:
            self.active -= 1
```

- [ ] **Step 2: 写失败的测试**

`tests/test_llm.py`：
```python
import asyncio

import pytest
from helpers import FakeBackend

from ligaotai.config import AppConfig
from ligaotai.llm import FatalLLMError, LLMClient, LLMError, Reply, Usage, parse_json


def run(coro):
    return asyncio.run(coro)


def ok(data):
    return []


def make(backend, **cfg):
    return LLMClient(AppConfig(**cfg), backend)


def test_parse_json_strips_fence():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json("[1, 2]")


def test_first_try_ok():
    fb = FakeBackend(['{"a": 1}'])
    c = make(fb)
    assert run(c.chat_json("batch", "sys", "user", ok, tag="t")) == ({"a": 1}, [])
    assert (c.usage.calls, c.usage.prompt_tokens, c.usage.completion_tokens) == (1, 100, 20)
    assert fb.calls[0]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]
    assert fb.calls[0]["max_tokens"] == 8192


def test_bad_json_is_fed_back():
    fb = FakeBackend(["不是json", '{"a": 1}'])
    assert run(make(fb).chat_json("batch", "s", "u", ok, tag="t")) == ({"a": 1}, [])
    msgs = fb.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[2]["content"] == "不是json"
    assert "JSON" in msgs[3]["content"]


def test_check_problems_are_fed_back():
    fb = FakeBackend(['{"a": 0}', '{"a": 1}'])

    def check(d):
        return [] if d["a"] == 1 else ["a 必须是 1"]

    assert run(make(fb).chat_json("batch", "s", "u", check, tag="t")) == ({"a": 1}, [])
    assert "a 必须是 1" in fb.calls[1]["messages"][3]["content"]


def test_persistent_problems_return_last_data():
    fb = FakeBackend(['{"a": 0}'] * 3)
    data, problems = run(make(fb).chat_json("batch", "s", "u", lambda d: ["还是不对"], tag="t"))
    assert (data, problems, len(fb.calls)) == ({"a": 0}, ["还是不对"], 3)


def test_empty_reply_retried_as_is():
    fb = FakeBackend([Reply(content=""), '{"a": 1}'])
    assert run(make(fb).chat_json("batch", "s", "u", ok, tag="t"))[0] == {"a": 1}
    assert len(fb.calls[1]["messages"]) == 2


def test_truncated_reply_retried_with_more_tokens():
    fb = FakeBackend([Reply(content='{"a": ', finish_reason="length"), '{"a": 1}'])
    run(make(fb).chat_json("batch", "s", "u", ok, tag="t"))
    assert fb.calls[1]["max_tokens"] == 16384
    assert len(fb.calls[1]["messages"]) == 2


def test_never_parseable_raises():
    with pytest.raises(LLMError):
        run(make(FakeBackend(["坏"] * 3)).chat_json("batch", "s", "u", ok, tag="t"))


def test_auth_error_is_fatal():
    class Denied(Exception):
        status_code = 401

    with pytest.raises(FatalLLMError):
        run(make(FakeBackend([Denied("bad key")])).chat_json("batch", "s", "u", ok, tag="t"))


def test_other_error_is_item_error():
    with pytest.raises(LLMError) as ei:
        run(make(FakeBackend([RuntimeError("timeout")])).chat_json("batch", "s", "u", ok, tag="t"))
    assert not isinstance(ei.value, FatalLLMError)


def test_synth_tier():
    fb = FakeBackend(['{"a": 1}'])
    run(make(fb).chat_json("synth", "s", "u", ok, tag="t"))
    assert fb.calls[0]["tier"].thinking == "on"
    assert fb.calls[0]["max_tokens"] == 32768


def test_unknown_tier():
    with pytest.raises(ValueError):
        make(FakeBackend([])).tier("big")


def test_log_written_without_key(tmp_path):
    c = LLMClient(AppConfig(api_key="sk-secret-123456"), FakeBackend(['{"a": 1}']), log_dir=tmp_path / "日志")
    run(c.chat_json("batch", "s", "u", ok, tag="cards/S-0001"))
    log = tmp_path / "日志" / "cards" / "S-0001-1.json"
    text = log.read_text(encoding="utf-8")
    assert "sk-secret" not in text
    assert '"u"' in text


def test_concurrency_limited():
    fb = FakeBackend(handler=lambda tier, messages: '{"a": 1}', delay=0.02)
    c = make(fb, concurrency=3)

    async def many():
        await asyncio.gather(*(c.chat_json("batch", "s", "u", ok, tag=f"t{i}") for i in range(10)))

    run(many())
    assert len(fb.calls) == 10
    assert fb.max_active <= 3


def test_usage_cost():
    u = Usage(calls=1, prompt_tokens=1_000_000, completion_tokens=500_000)
    assert u.cost(AppConfig()) == pytest.approx(0.30 + 0.60)
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_llm.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'ligaotai.llm'`（helpers 导入就会失败，所以其他用 helpers 的测试这时也会报错，属正常，本任务结束时全部恢复）

- [ ] **Step 4: 实现**

`src/ligaotai/llm.py`：
```python
"""模型调用：OpenAI 兼容的 Chat Completions 接口（默认 DeepSeek）。

LLMClient.chat_json 负责：要 JSON → 解析 → 调用方给的检查函数 → 有问题就带着问题重试，
统计 token 用量，每次调用的请求和返回写进书的 日志/ 目录。并发由一个信号量控制。
真正发请求的是 backend（OpenAIBackend），测试里换成假的。
"""

from __future__ import annotations

import json
import re
import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol

from .book import now_iso
from .config import AppConfig, TierConfig
from .fsutil import write_json

MAX_ATTEMPTS = 3
MAX_TOKENS_CAP = 65536
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")

Checker = Callable[[dict], list]  # 返回问题清单（字符串），空列表 = 合格


class LLMError(RuntimeError):
    """这一项调用失败（可以单独重跑）。"""


class FatalLLMError(LLMError):
    """整个步骤都不用再跑了：key 不对、欠费、没权限。"""


@dataclass
class Reply:
    content: str
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatBackend(Protocol):
    async def complete(self, tier: TierConfig, messages: list[dict], max_tokens: int) -> Reply: ...


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, reply: Reply) -> None:
        self.calls += 1
        self.prompt_tokens += reply.prompt_tokens
        self.completion_tokens += reply.completion_tokens

    def cost(self, cfg: AppConfig) -> float:
        return (self.prompt_tokens * cfg.price_input + self.completion_tokens * cfg.price_output) / 1_000_000


def parse_json(text: str) -> dict:
    obj = json.loads(_FENCE.sub("", text.strip()))
    if not isinstance(obj, dict):
        raise ValueError("顶层不是 JSON 对象")
    return obj


def feedback(problems: list[str]) -> str:
    lines = "\n".join(f"- {p}" for p in problems)
    return f"你上一次的输出有这些问题：\n{lines}\n请修正后重新输出完整的 json，不要加任何解释。"


class LLMClient:
    def __init__(self, cfg: AppConfig, backend: ChatBackend, log_dir: Path | None = None):
        self.cfg = cfg
        self.backend = backend
        self.log_dir = log_dir
        self.usage = Usage()
        self._sem = asyncio.Semaphore(cfg.concurrency)

    def tier(self, name: str) -> TierConfig:
        if name not in ("batch", "synth"):
            raise ValueError(f"没有这一档模型：{name}")
        return getattr(self.cfg, name)

    async def _call(self, tier: TierConfig, messages: list[dict], max_tokens: int) -> Reply:
        try:
            async with self._sem:
                return await self.backend.complete(tier, messages, max_tokens)
        except Exception as e:
            status = getattr(e, "status_code", None)
            if status in (401, 402, 403):
                raise FatalLLMError(f"接口拒绝了请求（{status}）：{e}") from e
            raise LLMError(f"{type(e).__name__}: {e}") from e

    async def chat_json(
        self,
        tier_name: str,
        system: str,
        user: str,
        check: Checker,
        *,
        tag: str,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> tuple[dict, list[str]]:
        """返回 (结果, 仍存在的问题)。见 Task 3 的流程说明。"""
        tier = self.tier(tier_name)
        base = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        messages = list(base)
        max_tokens = tier.max_tokens
        best: tuple[dict, list[str]] | None = None
        problems: list[str] = []
        for attempt in range(1, max_attempts + 1):
            reply = await self._call(tier, messages, max_tokens)
            self.usage.add(reply)
            self._log(tag, attempt, tier, messages, reply)
            if not reply.content.strip():
                problems = ["模型返回了空内容"]
                continue
            if reply.finish_reason == "length":
                problems = ["输出太长被截断了"]
                max_tokens = min(max_tokens * 2, MAX_TOKENS_CAP)
                continue
            try:
                data = parse_json(reply.content)
            except ValueError as e:
                problems = [f"不是合法的 JSON：{e}"]
            else:
                problems = check(data)
                best = (data, problems)
                if not problems:
                    return best
            messages = base + [
                {"role": "assistant", "content": reply.content},
                {"role": "user", "content": feedback(problems)},
            ]
        if best is not None:
            return best
        raise LLMError("；".join(problems))

    def _log(self, tag: str, attempt: int, tier: TierConfig, messages: list[dict], reply: Reply) -> None:
        if self.log_dir is None:
            return
        write_json(
            self.log_dir / f"{tag}-{attempt}.json",
            {"time": now_iso(), "tier": tier.model_dump(), "messages": messages, "reply": asdict(reply)},
        )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest -q`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add src/ligaotai/llm.py tests/helpers.py tests/test_llm.py
git commit -m "feat: LLMClient（JSON 校验、带问题重试、用量、日志、并发）"
```

---

## Task 4: 真实接口 OpenAIBackend + 测试连接

**Files:**
- Modify: `src/ligaotai/llm.py`（追加）
- Test: `tests/test_llm_openai.py`

要点：
- 用 OpenAI 官方 SDK 的 `AsyncOpenAI(base_url=配置的接口地址, api_key=..., timeout=配置, max_retries=4)`。429 / 5xx / 连接错误由 SDK 自己按指数退避重试，401 这类不重试。
- 请求体：`model`、`messages`、`max_tokens`；`json_mode` 开着就带 `response_format`；思考开关和强度通过 `extra_body` 放进请求体（`thinking: {"type": ...}`、`reasoning_effort`），`thinking` 为 `default` 时什么都不传，这样换成别家接口也不会被多余参数卡住。
- 没有 key 时，构造就抛 `NoKeyError`（属于 `FatalLLMError`），API 层把它变成 400。
- `check_model(cfg, backend)`：两档各发一个极小的请求（让模型原样输出 `{"ok": true}`），返回每档是否可用、耗时和出错原因，供设置页的「测试连接」和验收脚本用。
- 测试用 `httpx.MockTransport` 截住 SDK 发出去的真实 HTTP 请求来检查，不联网。

- [ ] **Step 1: 写失败的测试**

`tests/test_llm_openai.py`：
```python
import asyncio
import json

import httpx
import pytest
from helpers import FakeBackend

from ligaotai.config import KEY_ENV, AppConfig
from ligaotai.llm import NoKeyError, OpenAIBackend, check_model

MSGS = [{"role": "user", "content": "输出 json"}]


def completion(content='{"ok": true}', finish="stop"):
    return {
        "id": "x", "object": "chat.completion", "created": 0, "model": "deepseek-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    }


def make_backend(cfg, status=200, body=None):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json=body if body is not None else completion())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAIBackend(cfg, http_client=client), seen


def test_batch_request_shape():
    cfg = AppConfig(api_key="sk-test-123456")
    backend, seen = make_backend(cfg)
    reply = asyncio.run(backend.complete(cfg.batch, MSGS, 100))
    assert (reply.content, reply.finish_reason, reply.prompt_tokens, reply.completion_tokens) == (
        '{"ok": true}', "stop", 7, 3,
    )
    request = seen[0]
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-test-123456"
    body = json.loads(request.content)
    assert (body["model"], body["max_tokens"]) == ("deepseek-flash", 100)
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in body


def test_synth_request_turns_thinking_on():
    cfg = AppConfig(api_key="sk-test-123456")
    backend, seen = make_backend(cfg)
    asyncio.run(backend.complete(cfg.synth, MSGS, 100))
    body = json.loads(seen[0].content)
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "high"


def test_default_thinking_sends_nothing_extra():
    cfg = AppConfig(api_key="sk-test-123456")
    tier = cfg.batch.model_copy(update={"thinking": "default", "json_mode": False})
    backend, seen = make_backend(cfg)
    asyncio.run(backend.complete(tier, MSGS, 100))
    body = json.loads(seen[0].content)
    assert "thinking" not in body and "response_format" not in body


def test_auth_error_carries_status_code():
    cfg = AppConfig(api_key="sk-test-123456")
    backend, _ = make_backend(cfg, status=401, body={"error": {"message": "bad key"}})
    with pytest.raises(Exception) as ei:
        asyncio.run(backend.complete(cfg.batch, MSGS, 100))
    assert getattr(ei.value, "status_code", None) == 401


def test_no_key():
    with pytest.raises(NoKeyError):
        OpenAIBackend(AppConfig())


def test_key_from_env(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "sk-env-123456")
    cfg = AppConfig()
    backend, seen = make_backend(cfg)
    asyncio.run(backend.complete(cfg.batch, MSGS, 10))
    assert seen[0].headers["authorization"] == "Bearer sk-env-123456"


def test_check_model_reports_each_tier():
    results = check_model(AppConfig(), FakeBackend(['{"ok": true}', RuntimeError("down"), RuntimeError("down")]))
    assert [(r["tier"], r["ok"]) for r in results] == [("batch", True), ("synth", False)]
    assert "down" in results[1]["error"]
    assert results[0]["model"] == "deepseek-flash"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_llm_openai.py -q`
Expected: FAIL，`ImportError: cannot import name 'NoKeyError'`

- [ ] **Step 3: 实现**

在 `src/ligaotai/llm.py` 的 import 区加：
```python
import time

from openai import AsyncOpenAI
```
并把 `from .config import AppConfig, TierConfig` 改成 `from .config import AppConfig, TierConfig, effective_key`。

在 `FatalLLMError` 类后面加：
```python
class NoKeyError(FatalLLMError):
    """还没配置 API key。"""
```

在文件末尾追加：
```python
def request_extras(tier: TierConfig) -> dict:
    """思考开关和强度：放进请求体。thinking=default 时什么都不传。"""
    extra: dict = {}
    if tier.thinking != "default":
        extra["thinking"] = {"type": "enabled" if tier.thinking == "on" else "disabled"}
    if tier.effort:
        extra["reasoning_effort"] = tier.effort
    return extra


class OpenAIBackend:
    """真正发请求：OpenAI 官方 SDK，指向配置里的接口地址。429/5xx/超时由 SDK 自动退避重试。"""

    def __init__(self, cfg: AppConfig, http_client=None):
        key = effective_key(cfg)
        if not key:
            raise NoKeyError("还没配置 API key：在设置里填写，或者设置环境变量 LIGAOTAI_API_KEY")
        self._client = AsyncOpenAI(
            base_url=cfg.api_base,
            api_key=key,
            timeout=cfg.timeout,
            max_retries=4,
            http_client=http_client,
        )

    async def complete(self, tier: TierConfig, messages: list[dict], max_tokens: int) -> Reply:
        kwargs: dict = {"model": tier.model, "messages": messages, "max_tokens": max_tokens}
        if tier.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        extra = request_extras(tier)
        if extra:
            kwargs["extra_body"] = extra
        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        usage = resp.usage
        return Reply(
            content=choice.message.content or "",
            finish_reason=choice.finish_reason or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )


PING_SYSTEM = "你在做接口连通性测试。只输出一个 json 对象，不要解释。"
PING_USER = '请原样输出这个 json：{"ok": true}'


def _ping_check(data: dict) -> list[str]:
    return [] if data.get("ok") is True else ['缺少 "ok": true']


def check_model(cfg: AppConfig, backend: ChatBackend) -> list[dict]:
    """两档模型各发一个极小的请求，返回每档是否可用、耗时、出错原因。"""

    async def one(client: LLMClient, tier_name: str) -> dict:
        start = time.perf_counter()
        try:
            await client.chat_json(tier_name, PING_SYSTEM, PING_USER, _ping_check, tag=f"check/{tier_name}", max_attempts=2)
            ok, error = True, ""
        except LLMError as e:
            ok, error = False, str(e)
        return {
            "tier": tier_name,
            "model": client.tier(tier_name).model,
            "ok": ok,
            "error": error,
            "seconds": round(time.perf_counter() - start, 1),
        }

    async def both() -> list[dict]:
        client = LLMClient(cfg, backend)
        return [await one(client, "batch"), await one(client, "synth")]

    return asyncio.run(both())
```

注意：`test_check_model_reports_each_tier` 里 synth 档连着失败两次（`max_attempts=2`），所以 FakeBackend 预设了两个异常。第一个异常就会让 `_call` 抛 `LLMError` 直接结束这一档（异常不重试），第二个预设不会被用到——这没关系。如果测试因为预设用不完而失败，不是问题；如果因为不够用而失败，说明实现在异常时也重试了，要改实现。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_llm_openai.py tests/test_llm.py -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/llm.py tests/test_llm_openai.py
git commit -m "feat: OpenAIBackend（官方 SDK、思考开关、JSON 模式）与测试连接"
```

## Task 5: 提示词文件 prompts.py + prompts/cards.md + prompts/entities.md

**Files:**
- Create: `src/ligaotai/prompts.py`
- Create: `prompts/cards.md`
- Create: `prompts/entities.md`
- Test: `tests/test_prompts.py`

格式：`## system` 和 `## user` 两个标题分段，第一个标题前面是写给人看的说明（会被忽略）。变量写 `$名字`（Python `string.Template`，ASCII 变量名后面紧跟中文也能正确断开），真要写美元符号写 `$$`。每次调用都重新读文件，改了提示词不用重启。

- [ ] **Step 1: 写失败的测试**

`tests/test_prompts.py`：
```python
import pytest

from ligaotai.prompts import render


def test_load_and_render(tmp_path):
    (tmp_path / "x.md").write_text(
        "说明文字\n\n## system\n你好 $who，价格 $$5\n\n## user\n正文：$text\n", encoding="utf-8"
    )
    assert render("x", tmp_path, who="作者", text="甲") == ("你好 作者，价格 $5", "正文：甲")


def test_missing_section(tmp_path):
    (tmp_path / "x.md").write_text("## system\n只有一段\n", encoding="utf-8")
    with pytest.raises(ValueError):
        render("x", tmp_path)


def test_missing_variable(tmp_path):
    (tmp_path / "x.md").write_text("## system\n$who\n## user\n$text\n", encoding="utf-8")
    with pytest.raises(KeyError):
        render("x", tmp_path, text="甲")


def test_real_cards_prompt():
    system, user = render("cards", scene_id="S-0001", source="稿/a.txt", heading="第一章", text="林清年方十六。")
    assert "json" in system and "场景卡" in system
    assert "S-0001" in user and "林清年方十六。" in user
    assert "$" not in system + user


def test_real_entities_prompt():
    system, user = render("entities", type_label="人物", names="- 林清（3 个场景）：林清年方十六", hints="（无）")
    assert "json" in system and "人物" in system and "归成一组" in system
    assert "林清" in user
    assert "$" not in system + user
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_prompts.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'ligaotai.prompts'`

- [ ] **Step 3: 实现 prompts.py**

`src/ligaotai/prompts.py`：
```python
"""提示词：仓库根目录 prompts/<名字>.md。

文件里用「## system」「## user」两个标题分段，第一个标题之前是写给人看的说明（会被忽略）。
变量写成 $名字（string.Template），真要写美元符号就写 $$。每次都重新读文件，改了不用重启。
"""

from __future__ import annotations

import re
from pathlib import Path
from string import Template

from .config import APP_DIR

PROMPTS_DIR = APP_DIR / "prompts"
_SECTION = re.compile(r"^## (system|user)[ \t]*$", re.M)


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> tuple[Template, Template]:
    text = (Path(prompts_dir) / f"{name}.md").read_text(encoding="utf-8")
    parts = _SECTION.split(text)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if set(sections) != {"system", "user"}:
        raise ValueError(f"提示词 {name}.md 要有「## system」和「## user」两段")
    return Template(sections["system"]), Template(sections["user"])


def render(name: str, prompts_dir: Path = PROMPTS_DIR, **values: str) -> tuple[str, str]:
    system, user = load_prompt(name, prompts_dir)
    return system.substitute(values), user.substitute(values)
```

- [ ] **Step 4: 写 prompts/cards.md**

`prompts/cards.md`：
```markdown
# 场景卡提示词（步骤 4，批量档）

变量：$scene_id 场景编号、$source 来源文件、$heading 所在章节、$text 片段原文。
这一段在第一个「## system」之前，只是说明，不会发给模型。

## system
你是一名细心的小说编辑助手。你的任务是阅读长篇小说手稿中的一个片段（场景），为它做一张结构化的「场景卡」。只输出一个 json 对象，不要输出任何解释。

规则：
1. 只根据这个片段本身填写，不要用你对这部作品的已有知识去补片段里没有的内容。
2. 人名、地名、组织名一律照片段原文的写法抄（包括繁体字、外号、称谓），不要统一，不要改写成你认为的正式名字。
3. facts 里每条的 quote 必须是从片段中逐字复制的一句话（或一句中连续的一段），用来证明这条事实。不要改字，不要把繁体改成简体。
4. summary 用简体中文写，不超过 150 字，说清楚这个片段里发生了什么。
5. 没有内容的字段给空字符串或空列表，不要编造。
6. kind 只能是：正文、提纲、设定笔记、碎片。提纲 = 列要点的大纲；设定笔记 = 人物或世界设定的说明；碎片 = 很短、不成段的零碎文字。
7. role 只能是：主要、次要、提及。
8. incomplete：这个片段是不是明显写到一半就断了（句子或情节中途断掉）。是的话在 incomplete_note 里说明。
9. refs_elsewhere：片段里提到、但没有在本片段写出来的事件。比如「自从青州城破之后」里的「青州城破」。
10. world_hint：判断这个片段属于哪个世界的原文线索（出现了什么地方、制度、法术、器物）。

输出的 json 格式如下（示例）：
{"summary": "林清在青州城外的雪夜里救下受伤的赵五，发现他身上带着官府的令牌。",
 "pov": "林清",
 "characters": [{"name": "林清", "role": "主要"}, {"name": "赵五", "role": "次要"}],
 "locations": ["青州城外"],
 "organizations": ["官府"],
 "world_hint": "出现官府、令牌、青州，像是古代人间",
 "time_hints": ["那一年冬天", "三更时分"],
 "events": ["林清救下受伤的赵五", "林清发现赵五身上的令牌"],
 "facts": [{"subject": "林清", "attribute": "年龄", "value": "十六", "quote": "林清年方十六"}],
 "hooks_planted": ["赵五身上的令牌来历不明"],
 "hooks_resolved": [],
 "refs_elsewhere": ["青州城破"],
 "incomplete": false,
 "incomplete_note": "",
 "kind": "正文"}

## user
场景编号：$scene_id
来源文件：$source
所在章节：$heading

片段原文：
<<<
$text
>>>
```

- [ ] **Step 5: 写 prompts/entities.md**

`prompts/entities.md`：
```markdown
# 实体合并提示词（步骤 5，综合档）

变量：$type_label（人物 / 地点 / 组织）、$names（每行一个叫法，带场景数和上下文）、$hints（字面相近的提示）。

## system
你是一名熟悉中文小说的编辑助手。下面给你一部小说手稿里出现过的全部「$type_label」叫法。同一个$type_label常常有好几种叫法：全名、名、字号、外号、称谓、昵称、官职、别人对他的称呼，作者写作时也可能前后改过名。你的任务是把指同一个$type_label的叫法归成一组。

规则：
1. 根据给出的原文上下文和常识判断；拿不准就不要合并，宁可漏，不要错。
2. 泛称不要并进具体的组，比如「师父」「那人」「老者」「妖怪」「城里」这类在不同段落里可能指不同对象的叫法。
3. 同名不同人（上下文明显是两个人）不能合并。
4. 每组给一个 canonical（规范名）：从这组的叫法里选最完整、最正式的那个，通常是全名。
5. 只输出包含两个或以上叫法的组；只有一种叫法的不用列。一个叫法最多出现在一个组里。
6. members 和 canonical 必须一字不差地使用列表里的写法。
7. reason 用一句话说明为什么是同一个。

只输出一个 json 对象，格式如下（示例）：
{"groups": [
  {"canonical": "林清", "members": ["林清", "清儿", "林姑娘"], "reason": "清儿、林姑娘都是别人对林清的称呼，上下文是同一个人的经历"}
]}

## user
下面是全部「$type_label」叫法（按出现的场景数从多到少排），每行后面是原文里的上下文：

$names

字面上相近、可能是同一个的叫法（仅供参考，不一定对）：
$hints
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_prompts.py -q`
Expected: `5 passed`

- [ ] **Step 7: Commit**

```bash
git add src/ligaotai/prompts.py prompts/cards.md prompts/entities.md tests/test_prompts.py
git commit -m "feat: 提示词文件（场景卡、实体合并）与加载"
```

---

## Task 6: 任务可以暂停 jobs.py

**Files:**
- Modify: `src/ligaotai/jobs.py`
- Test: `tests/test_jobs.py`（追加）

要点：`runner.cancel(job_id)` 只是给任务打一个「请求暂停」的标记；任务下一次调用 `progress(...)` 时抛 `JobCancelled`，任务状态记为 `cancelled`。已经完成的项都落了盘，重跑会接着做。已经结束的任务再点暂停不起作用。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_jobs.py` 末尾追加：
```python
def test_cancel_running_job():
    from ligaotai.jobs import JobCancelled  # noqa: F401  确认异常类存在

    runner = JobRunner()
    started, release = threading.Event(), threading.Event()

    def fn(progress):
        started.set()
        release.wait(5)
        progress(1, 2)  # 这里发现已请求暂停
        return {}

    job = runner.submit("cards", "测试书", fn)
    started.wait(5)
    assert runner.cancel(job.id) is job
    release.set()
    job = runner.wait(job.id)
    assert (job.status, job.error) == ("cancelled", "已暂停")
    assert runner.wait(runner.submit("x", "测试书", lambda p: {}).id).status == "done"


def test_cancel_finished_or_unknown_job():
    runner = JobRunner()
    job = runner.wait(runner.submit("x", "测试书", lambda p: {}).id)
    runner.cancel(job.id)
    assert job.status == "done" and job.cancel_requested is False
    assert runner.cancel("nope") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_jobs.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'JobCancelled'`）

- [ ] **Step 3: 实现**

在 `src/ligaotai/jobs.py` 里：

`BusyError` 类后面加：
```python
class JobCancelled(Exception):
    """作者点了暂停。已经做完的部分都落了盘，重跑会接着做。"""
```

`Job` 的字段里、`finished: str = ""` 后面加：
```python
    cancel_requested: bool = False
```
并把 `status` 那行的注释改成 `# queued / running / done / failed / cancelled`。

`JobRunner` 里、`get` 方法前面加：
```python
    def cancel(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is not None and job.status in ("queued", "running"):
            job.cancel_requested = True
        return job
```

`_run` 里的 `progress` 函数开头加两行：
```python
        def progress(done: int, total: int, message: str = "") -> None:
            if job.cancel_requested:
                raise JobCancelled("已暂停")
            job.done, job.total = done, total
            if message:
                job.message = message
```

`_run` 的 `try` 块在 `except BaseException` 之前加一个分支：
```python
        except JobCancelled:
            job.error = "已暂停"
            job.finished = now_iso()
            job.status = "cancelled"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_jobs.py -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/jobs.py tests/test_jobs.py
git commit -m "feat: 任务可以暂停（下一次汇报进度时停下）"
```

## Task 7: 场景卡字段 + 原文核对 cards.py（上）

**Files:**
- Create: `src/ligaotai/cards.py`（本任务写字段模型、`check_card`、`clean_card`）
- Test: `tests/test_cards.py`

要点：
- 字段按 spec 5.2，外加 `organizations`（见偏差 2）。多出来的字段忽略，缺的给默认值。
- `check_card(data, text)` 返回问题清单，给 LLMClient 用来反馈重试：字段格式不对；summary 超过 200 字（提示词要求 150，留点余量）；quote 不在原文里；名字不在原文里。「在原文里」= 两边都用 `dedup.normalize` 去掉空白和标点后做子串判断，所以标点、换行不同不算错。
- `clean_card(card, text)` 在 3 次都没改好时用：删掉不在原文里的 fact、人物、地点、组织，pov 不在原文里就清空；返回清理后的卡和被删掉的清单。

- [ ] **Step 1: 写失败的测试**

`tests/test_cards.py`：
```python
from ligaotai.cards import Card, check_card, clean_card

TEXT = "第一章 雪夜\n林清年方十六，住在青州城外。那一年冬天，赵五来了。"
GOOD = {
    "summary": "林清在雪夜遇到赵五。",
    "pov": "林清",
    "characters": [{"name": "林清", "role": "主要"}, {"name": "赵五", "role": "次要"}],
    "locations": ["青州城外"],
    "organizations": [],
    "facts": [{"subject": "林清", "attribute": "年龄", "value": "十六", "quote": "林清年方十六"}],
    "kind": "正文",
}


def with_(**changes):
    return {**GOOD, **changes}


def test_good_card_has_no_problems():
    assert check_card(GOOD, TEXT) == []


def test_extra_fields_ignored_and_defaults_filled():
    card = Card.model_validate(with_(id="S-0001"))
    assert card.hooks_planted == [] and card.incomplete is False


def test_quote_compared_without_punctuation():
    data = with_(facts=[{"subject": "林清", "attribute": "住处", "value": "青州城外", "quote": "林清年方十六住在青州城外"}])
    assert check_card(data, TEXT) == []


def test_quote_not_in_text():
    problems = check_card(with_(facts=[{"subject": "林清", "attribute": "年龄", "value": "十七", "quote": "林清年方十七"}]), TEXT)
    assert len(problems) == 1 and "林清年方十七" in problems[0]


def test_name_not_in_text():
    data = with_(characters=[{"name": "孙悟空", "role": "主要"}])
    problems = check_card(data, TEXT)
    assert len(problems) == 1 and "孙悟空" in problems[0]


def test_bad_kind_is_format_problem():
    problems = check_card(with_(kind="小说"), TEXT)
    assert len(problems) == 1 and "格式" in problems[0]


def test_long_summary():
    assert check_card(with_(summary="长" * 201), TEXT) != []


def test_clean_card_drops_unverifiable_items():
    data = with_(
        pov="张三",
        characters=[{"name": "林清", "role": "主要"}, {"name": "孙悟空", "role": "提及"}],
        locations=["青州城外", "花果山"],
        facts=[
            {"subject": "林清", "attribute": "年龄", "value": "十六", "quote": "林清年方十六"},
            {"subject": "林清", "attribute": "年龄", "value": "十七", "quote": "林清年方十七"},
        ],
    )
    card, dropped = clean_card(Card.model_validate(data), TEXT)
    assert [c.name for c in card.characters] == ["林清"]
    assert card.locations == ["青州城外"] and card.pov == ""
    assert [f.quote for f in card.facts] == ["林清年方十六"]
    assert dropped == {"facts": ["林清年方十七"], "names": ["孙悟空", "张三", "花果山"]}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cards.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'ligaotai.cards'`

- [ ] **Step 3: 实现**

`src/ligaotai/cards.py`：
```python
"""步骤 4 场景卡：每个场景块单独调一次模型（批量档），按 spec 5.2 的字段出 JSON。

模型写的 quote 和人名、地名、组织名都要能在原文里找到（去掉空白和标点后比较）。
找不到就带着问题重试；3 次后还有，就删掉这些条目，记在卡的 dropped 里。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from .dedup import normalize

SUMMARY_LIMIT = 200  # 提示词要求 150 字，这里留点余量


class Character(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    role: Literal["主要", "次要", "提及"] = "提及"


class Fact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subject: str
    attribute: str
    value: str
    quote: str


class Card(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: str
    pov: str = ""
    characters: list[Character] = []
    locations: list[str] = []
    organizations: list[str] = []
    world_hint: str = ""
    time_hints: list[str] = []
    events: list[str] = []
    facts: list[Fact] = []
    hooks_planted: list[str] = []
    hooks_resolved: list[str] = []
    refs_elsewhere: list[str] = []
    incomplete: bool = False
    incomplete_note: str = ""
    kind: Literal["正文", "提纲", "设定笔记", "碎片"] = "正文"


def brief_errors(e: ValidationError) -> str:
    return "；".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:3])


def card_names(card: Card) -> list[str]:
    names = [c.name for c in card.characters] + card.locations + card.organizations
    if card.pov:
        names.append(card.pov)
    return names


def _in_text(s: str, body: str) -> bool:
    n = normalize(s)
    return bool(n) and n in body


def check_card(data: dict, text: str) -> list[str]:
    try:
        card = Card.model_validate(data)
    except ValidationError as e:
        return [f"字段格式不对：{brief_errors(e)}"]
    body = normalize(text)
    problems = []
    if len(card.summary) > SUMMARY_LIMIT:
        problems.append("summary 太长了，请压到 150 字以内")
    bad_quotes = [f.quote for f in card.facts if not _in_text(f.quote, body)]
    if bad_quotes:
        problems.append("这些 quote 不是从原文逐字复制的：" + "；".join(bad_quotes[:5]))
    bad_names = sorted({n for n in card_names(card) if not _in_text(n, body)})
    if bad_names:
        problems.append("这些名字在原文里找不到，请照原文的写法：" + "、".join(bad_names[:10]))
    return problems


def clean_card(card: Card, text: str) -> tuple[Card, dict]:
    body = normalize(text)

    def keep(s: str) -> bool:
        return _in_text(s, body)

    dropped = {
        "facts": [f.quote for f in card.facts if not keep(f.quote)],
        "names": sorted({n for n in card_names(card) if not keep(n)}),
    }
    cleaned = card.model_copy(
        update={
            "facts": [f for f in card.facts if keep(f.quote)],
            "characters": [c for c in card.characters if keep(c.name)],
            "locations": [n for n in card.locations if keep(n)],
            "organizations": [n for n in card.organizations if keep(n)],
            "pov": card.pov if not card.pov or keep(card.pov) else "",
        }
    )
    return cleaned, dropped
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_cards.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/cards.py tests/test_cards.py
git commit -m "feat: 场景卡字段与原文核对"
```

---

## Task 8: 步骤 4 跑场景卡 cards.py（下）

**Files:**
- Modify: `src/ligaotai/cards.py`（追加）
- Modify: `tests/helpers.py`（假场景卡、假 AI 回复）
- Modify: `tests/conftest.py`（`story_book` fixture）
- Test: `tests/test_cards.py`（追加）

要点：
- 场景卡文件 `场景卡/S-0001.json`：`{"id", "scene_hash", "model", "created", "problems", "dropped", "card": {...}}`。
- 要做的场景 = 没被删除、而且（没有卡，或卡上的 `scene_hash` 和场景当前 `hash` 不一致）。`only=[编号]` 时只做指定的几个（「单独重跑」）。版本组里的非主版本也做卡（版本对比要用）。
- 并发由 LLMClient 的信号量控制；用 `asyncio.TaskGroup` 同时起所有场景的任务。
- 单个场景失败（`LLMError` 等）只记进 `failed`，别的照常做；`FatalLLMError`（key 不对、欠费）和 `JobCancelled`（暂停）会让整个步骤停下。TaskGroup 会把它包成异常组，要拆出来原样抛。
- 不管成功、失败、暂停，都把这次的用量累加进 book.json（`finally`）。
- 步骤状态总是 `done`，摘要描述**整本书**当前的状态：场景数、有新鲜卡的数量、还缺卡的编号（最多列 200 个）、这次写了几张、几张有问题、失败清单、调用次数和费用。写了新卡才让下游过期。

- [ ] **Step 1: helpers 加假场景卡和假 AI**

在 `tests/helpers.py` 顶部 import 区加 `import json`，末尾追加：
```python
CARD_PERSONS = ["林清", "清儿", "林姑娘", "赵五", "悟空", "八戒", "唐僧", "金箍郎", "天蓬郎", "御弟師父"]
CARD_PLACES = ["青州城外"]
CARD_ORGS = ["天机阁"]


def scene_text_from(messages) -> str:
    """从场景卡提示词的 user 消息里取出片段原文。"""
    user = messages[1]["content"]
    return user.split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0]


def card_reply(text: str) -> str:
    """按原文里出现的已知名字造一张合格的场景卡。"""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    first = lines[1] if len(lines) > 1 else (lines[0] if lines else "")
    quote = first[:6]
    card = {
        "summary": "测试摘要。",
        "pov": "",
        "characters": [{"name": n, "role": "主要"} for n in CARD_PERSONS if n in text],
        "locations": [n for n in CARD_PLACES if n in text],
        "organizations": [n for n in CARD_ORGS if n in text],
        "facts": [{"subject": "某人", "attribute": "原文", "value": quote, "quote": quote}] if quote else [],
        "kind": "正文",
    }
    return json.dumps(card, ensure_ascii=False)


def names_from_prompt(messages) -> list[str]:
    """从实体合并提示词的 user 消息里取出叫法列表。"""
    user = messages[1]["content"].split("字面上相近", 1)[0]
    return [ln[2:].split("（", 1)[0] for ln in user.split("\n") if ln.startswith("- ")]


def entity_reply(messages, groups) -> str:
    present = set(names_from_prompt(messages))
    out = []
    for g in groups:
        members = [n for n in g if n in present]
        if len(members) >= 2:
            out.append({"canonical": members[0], "members": members, "reason": "测试"})
    return json.dumps({"groups": out}, ensure_ascii=False)


def fake_ai_handler(groups=()):
    """按提示词种类回复：连通性测试 / 场景卡 / 实体合并。"""

    def handler(tier, messages):
        system = messages[0]["content"]
        if "连通性" in system:
            return '{"ok": true}'
        if "场景卡" in system:
            return card_reply(scene_text_from(messages))
        if "归成一组" in system:
            return entity_reply(messages, groups)
        raise AssertionError("没见过的提示词")

    return handler
```

- [ ] **Step 2: conftest 加 story_book**

在 `tests/conftest.py` 末尾追加：
```python
STORY = {
    "1.txt": "第一章 雪夜\n林清年方十六，住在青州城外。\n\n第二章 离城\n清儿背着包袱出了门，赵五在后面跟着。",
    "2.txt": "第三章 天机\n林姑娘进了天机阁，赵五守在门口。",
}


@pytest.fixture
def story_book(book, tmp_path):
    """三个场景的小书：S-0001 林清，S-0002 清儿/赵五，S-0003 林姑娘/赵五/天机阁。"""
    from ligaotai.importer import run_import
    from ligaotai.scenes import run_split

    src = tmp_path / "稿"
    src.mkdir()
    for name, text in STORY.items():
        (src / name).write_text(text, encoding="utf-8")
    run_import(book, src)
    run_split(book)
    book.story_src = src
    return book
```

- [ ] **Step 3: 追加失败的测试**

在 `tests/test_cards.py` 末尾追加：
```python
import pytest
from helpers import FakeBackend, card_reply, fake_ai_handler, scene_text_from

from ligaotai.cards import load_card, run_cards
from ligaotai.config import AppConfig
from ligaotai.importer import run_import
from ligaotai.jobs import JobCancelled
from ligaotai.llm import FatalLLMError, LLMClient
from ligaotai.scenes import run_split


def client_for(book, handler=None, **cfg):
    return LLMClient(AppConfig(**cfg), FakeBackend(handler=handler or fake_ai_handler()), log_dir=book.logs_dir)


def test_run_cards_writes_and_skips_fresh(story_book):
    c = client_for(story_book)
    s = run_cards(story_book, c)
    assert (s["scenes"], s["fresh"], s["written"], s["failed"], s["missing"]) == (3, 3, 3, [], [])
    record = load_card(story_book, "S-0001")
    assert record["card"]["characters"] == [{"name": "林清", "role": "主要"}]
    assert record["scene_hash"] and record["model"] == "deepseek-flash"
    assert story_book.load()["usage"]["by_step"]["cards"]["calls"] == 3
    assert story_book.step("cards")["status"] == "done"
    assert (story_book.logs_dir / "cards" / "S-0001-1.json").exists()

    c2 = client_for(story_book)
    s2 = run_cards(story_book, c2)
    assert c2.usage.calls == 0 and s2["written"] == 0 and s2["fresh"] == 3


def test_changed_scene_is_redone(story_book):
    run_cards(story_book, client_for(story_book))
    (story_book.story_src / "2.txt").write_text("第三章 天机\n林姑娘进了天机阁，改了一句。", encoding="utf-8")
    run_import(story_book, story_book.story_src)
    run_split(story_book)
    c = client_for(story_book)
    run_cards(story_book, c)
    assert c.usage.calls == 1


def test_failed_item_is_listed_and_retried_later(story_book):
    def handler(tier, messages):
        text = scene_text_from(messages)
        return "坏" if "天机阁" in text else card_reply(text)

    c = client_for(story_book, handler)
    s = run_cards(story_book, c)
    assert [f["id"] for f in s["failed"]] == ["S-0003"]
    assert s["missing"] == ["S-0003"] and s["fresh"] == 2
    assert c.usage.calls == 2 + 3

    c2 = client_for(story_book)
    run_cards(story_book, c2)
    assert c2.usage.calls == 1


def test_fatal_error_stops_step(story_book):
    class Denied(Exception):
        status_code = 401

    with pytest.raises(FatalLLMError):
        run_cards(story_book, client_for(story_book, lambda t, m: Denied("bad key")))
    assert not list(story_book.cards_dir.glob("*.json")) if story_book.cards_dir.exists() else True


def test_cancel_keeps_finished_cards(story_book):
    def progress(done, total):
        if done >= 1:
            raise JobCancelled()

    with pytest.raises(JobCancelled):
        run_cards(story_book, client_for(story_book, concurrency=1), progress)
    assert len(list(story_book.cards_dir.glob("S-*.json"))) == 1

    c = client_for(story_book)
    run_cards(story_book, c)
    assert c.usage.calls == 2


def test_only_regenerates_given_scene(story_book):
    run_cards(story_book, client_for(story_book))
    c = client_for(story_book)
    s = run_cards(story_book, c, only=["S-0002"])
    assert c.usage.calls == 1 and s["written"] == 1 and s["fresh"] == 3


def test_unverifiable_items_dropped_after_retries(story_book):
    def handler(tier, messages):
        text = scene_text_from(messages)
        if "林清年方" not in text:
            return card_reply(text)
        return (
            '{"summary": "s", "characters": [{"name": "孙悟空", "role": "主要"}, {"name": "林清", "role": "主要"}],'
            ' "facts": [{"subject": "林清", "attribute": "a", "value": "v", "quote": "不存在的话"}], "kind": "正文"}'
        )

    c = client_for(story_book, handler)
    s = run_cards(story_book, c)
    record = load_card(story_book, "S-0001")
    assert record["problems"] and record["dropped"] == {"facts": ["不存在的话"], "names": ["孙悟空"]}
    assert record["card"]["characters"] == [{"name": "林清", "role": "主要"}]
    assert s["with_problems"] == 1
    assert c.usage.calls == 3 + 2
```

- [ ] **Step 4: 跑测试确认失败**

Run: `uv run pytest tests/test_cards.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'load_card'`）

- [ ] **Step 5: 实现**

在 `src/ligaotai/cards.py` 的 import 区改成：
```python
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from .book import Book, now_iso
from .dedup import normalize
from .fsutil import read_json, write_json
from .jobs import JobCancelled
from .llm import FatalLLMError, LLMClient, LLMError
from .prompts import render
from .scenes import SCENE_ID_RE, Scene, load_scenes
```

在 `SUMMARY_LIMIT` 后面加：
```python
MISSING_LIST_LIMIT = 200

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass
```

在文件末尾追加：
```python
def card_path(book: Book, sid: str) -> Path:
    return book.cards_dir / f"{sid}.json"


def load_card(book: Book, sid: str) -> dict | None:
    return read_json(card_path(book, sid))


def load_cards(book: Book) -> dict[str, dict]:
    if not book.cards_dir.exists():
        return {}
    out = {}
    for p in book.cards_dir.glob("S-*.json"):
        if not SCENE_ID_RE.match(p.stem):
            continue  # 同步冲突之类的副本
        data = read_json(p)
        if data and data.get("id") == p.stem:
            out[p.stem] = data
    return out


def is_fresh(record: dict | None, scene: Scene) -> bool:
    return bool(record) and record.get("scene_hash") == scene.hash


async def make_card(book: Book, client: LLMClient, scene: Scene) -> dict:
    system, user = render(
        "cards", scene_id=scene.id, source=scene.source, heading=scene.heading or "（无）", text=scene.text
    )
    data, problems = await client.chat_json(
        "batch", system, user, lambda d: check_card(d, scene.text), tag=f"cards/{scene.id}"
    )
    try:
        card = Card.model_validate(data)
    except ValidationError as e:
        raise LLMError(f"场景卡格式始终不对：{brief_errors(e)}") from e
    card, dropped = clean_card(card, scene.text)
    record = {
        "id": scene.id,
        "scene_hash": scene.hash,
        "model": client.tier("batch").model,
        "created": now_iso(),
        "problems": problems,
        "dropped": dropped,
        "card": card.model_dump(),
    }
    write_json(card_path(book, scene.id), record)
    return record


def run_cards(
    book: Book, client: LLMClient, progress: Progress = _noop, only: list[str] | None = None
) -> dict:
    return asyncio.run(_run_cards(book, client, progress, only))


async def _run_cards(book: Book, client: LLMClient, progress: Progress, only: list[str] | None) -> dict:
    scenes = [s for s in load_scenes(book, with_text=True) if not s.removed]
    records = load_cards(book)
    if only is not None:
        wanted = set(only)
        todo = [s for s in scenes if s.id in wanted]
    else:
        todo = [s for s in scenes if not is_fresh(records.get(s.id), s)]
    failed: list[dict] = []
    counts = {"done": 0, "written": 0, "with_problems": 0}
    progress(0, len(todo))

    async def one(scene: Scene) -> None:
        try:
            record = await make_card(book, client, scene)
        except (JobCancelled, FatalLLMError):
            raise
        except Exception as e:  # 单个场景失败不拖垮整步
            failed.append({"id": scene.id, "error": f"{type(e).__name__}: {e}"})
        else:
            records[scene.id] = record
            counts["written"] += 1
            if record["problems"] or any(record["dropped"].values()):
                counts["with_problems"] += 1
        counts["done"] += 1
        progress(counts["done"], len(todo))

    try:
        async with asyncio.TaskGroup() as tg:
            for scene in todo:
                tg.create_task(one(scene))
    except BaseExceptionGroup as eg:
        raise eg.exceptions[0] from None
    finally:
        u = client.usage
        book.add_usage("cards", u.calls, u.prompt_tokens, u.completion_tokens, u.cost(client.cfg))

    missing = [s.id for s in scenes if not is_fresh(records.get(s.id), s)]
    summary = {
        "scenes": len(scenes),
        "fresh": len(scenes) - len(missing),
        "missing": missing[:MISSING_LIST_LIMIT],
        "missing_count": len(missing),
        "written": counts["written"],
        "with_problems": counts["with_problems"],
        "failed": failed,
        "calls": client.usage.calls,
        "cost_usd": round(client.usage.cost(client.cfg), 4),
    }
    book.set_step("cards", "done", summary, changed=counts["written"] > 0)
    return summary
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_cards.py -q`
Expected: 全部通过。

如果 `test_cancel_keeps_finished_cards` 写出了 2 张卡而不是 1 张：说明第二个场景在暂停生效前已经跑完了（FakeBackend 没有真正的等待，任务按顺序一口气跑完）。先确认 `progress` 是在 `one()` 里、每张卡写完后调用的；如果逻辑没错，只是调度顺序造成的，把断言改成「至少 1 张、少于 3 张」，并在报告里说明。

- [ ] **Step 7: Commit**

```bash
git add src/ligaotai/cards.py tests/helpers.py tests/conftest.py tests/test_cards.py
git commit -m "feat: 步骤4 场景卡（并发、只做过期的、失败单列、暂停、用量）"
```

## Task 9: 实体合并（上）：汇总叫法 + 字面提示 + 分批

**Files:**
- Create: `src/ligaotai/entities.py`（本任务写 Mention、collect_mentions、core、hint_pairs、chunk_names）
- Test: `tests/test_entities.py`

要点：
- 只看**新鲜**的场景卡（卡的 scene_hash 等于场景当前 hash），跳过已删除的场景。
- 三类：`person`（characters 的 name，外加 pov）、`location`、`organization`。每个叫法记下出现在哪些场景（按编号自然排序）和最多 2 段原文上下文（名字前后各 20 字，空白压成一个空格）。
- 字面提示 `hint_pairs`：一个包含另一个（较短的至少 2 个字），或去掉常见称谓前后缀后相同。只是给模型的参考。
- 分批 `chunk_names`：叫法按出现次数从多到少排；不超过 `max_names` 就一批；超过时，出现最多的前 `anchors` 个放进每一批，其余的切开，这样冷门外号才能挂到主要人物身上。

- [ ] **Step 1: 写失败的测试**

`tests/test_entities.py`：
```python
from helpers import FakeBackend, fake_ai_handler

from ligaotai.cards import run_cards
from ligaotai.config import AppConfig
from ligaotai.entities import chunk_names, collect_mentions, core, hint_pairs
from ligaotai.llm import LLMClient


def client_for(book, groups=(), **cfg):
    return LLMClient(AppConfig(**cfg), FakeBackend(handler=fake_ai_handler(groups)), log_dir=book.logs_dir)


def test_collect_mentions(story_book):
    run_cards(story_book, client_for(story_book))
    m = collect_mentions(story_book)
    assert set(m["person"]) == {"林清", "清儿", "林姑娘", "赵五"}
    assert m["person"]["赵五"].scenes == ["S-0002", "S-0003"]
    assert m["person"]["赵五"].count == 2
    assert all("赵五" in ctx for ctx in m["person"]["赵五"].contexts)
    assert set(m["location"]) == {"青州城外"}
    assert set(m["organization"]) == {"天机阁"}


def test_stale_cards_are_ignored(story_book):
    run_cards(story_book, client_for(story_book))
    from ligaotai.importer import run_import
    from ligaotai.scenes import run_split

    (story_book.story_src / "2.txt").write_text("第三章 天机\n改成了别的内容。", encoding="utf-8")
    run_import(story_book, story_book.story_src)
    run_split(story_book)
    m = collect_mentions(story_book)
    assert "林姑娘" not in m["person"] and "天机阁" not in m["organization"]


def test_core():
    assert core("唐師父") == "唐"
    assert core("阿清") == "清"
    assert core("清兒") == "清"
    assert core("師父") == "師父"


def test_hint_pairs():
    pairs = {frozenset((a, b)) for a, b, _ in hint_pairs(["孫悟空", "悟空", "孫行者", "行者", "八戒", "阿清", "清兒"])}
    assert frozenset(("悟空", "孫悟空")) in pairs
    assert frozenset(("行者", "孫行者")) in pairs
    assert frozenset(("阿清", "清兒")) in pairs
    assert not any("八戒" in p for p in pairs)


def test_chunk_names():
    names = [f"n{i}" for i in range(10)]
    assert chunk_names(names, 20, 3) == [names]
    chunks = chunk_names(names, 6, 2)
    assert chunks == [["n0", "n1", "n2", "n3", "n4", "n5"], ["n0", "n1", "n6", "n7", "n8", "n9"]]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_entities.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'ligaotai.entities'`

- [ ] **Step 3: 实现**

`src/ligaotai/entities.py`：
```python
"""步骤 5 实体合并：把场景卡里的人名、地名、组织名，按「是不是同一个」归组，给出规范名。

1. 程序汇总所有叫法：出现在哪些场景、原文上下文；再按字面找出一些「看着像」的提示对。
2. 按类型把全部叫法（带上下文和提示）交给综合档模型，让它把指同一对象的叫法归组。
   叫法太多时分批，出现次数最多的一批放进每一批，冷门外号才能挂到主要人物身上。
3. 结果写进 实体.json。模型给的组是草稿（draft），作者确认、改名、合并、拆分后才算数（confirmed）。
   作者确认过的组重跑时原样保留，里面的叫法不会被模型挪走。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from .book import Book
from .cards import is_fresh, load_cards
from .fsutil import natural_key
from .scenes import load_scenes

TYPES = ("person", "location", "organization")
TYPE_LABELS = {"person": "人物", "location": "地点", "organization": "组织"}
CONTEXTS_PER_NAME = 2
CONTEXT_RADIUS = 20
MAX_NAMES_PER_CALL = 600
ANCHOR_NAMES = 150
HINT_LIMIT = 300
AFFIXES = (
    "大人", "姑娘", "公子", "先生", "夫人", "娘子", "師父", "师父", "師兄", "师兄", "師弟", "师弟",
    "長老", "长老", "大王", "老爺", "老爷", "兄", "哥", "姐", "妹", "兒", "儿", "阿", "老", "小",
)


@dataclass
class Mention:
    type: str
    name: str
    scenes: list[str] = field(default_factory=list)
    contexts: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.scenes)


def _context(text: str, name: str) -> str:
    i = text.find(name)
    if i < 0:
        return ""
    return " ".join(text[max(0, i - CONTEXT_RADIUS) : i + len(name) + CONTEXT_RADIUS].split())


def collect_mentions(book: Book) -> dict[str, dict[str, Mention]]:
    scenes = {s.id: s for s in load_scenes(book, with_text=True) if not s.removed}
    out: dict[str, dict[str, Mention]] = {t: {} for t in TYPES}
    for sid, record in sorted(load_cards(book).items(), key=lambda kv: natural_key(kv[0])):
        scene = scenes.get(sid)
        if scene is None or not is_fresh(record, scene):
            continue
        card = record["card"]
        found = [("person", c["name"]) for c in card["characters"]]
        if card.get("pov"):
            found.append(("person", card["pov"]))
        found += [("location", n) for n in card["locations"]]
        found += [("organization", n) for n in card.get("organizations", [])]
        for typ, raw in found:
            name = raw.strip()
            if not name:
                continue
            m = out[typ].setdefault(name, Mention(typ, name))
            if sid in m.scenes:
                continue
            m.scenes.append(sid)
            if len(m.contexts) < CONTEXTS_PER_NAME:
                snippet = _context(scene.text, name)
                if snippet:
                    m.contexts.append(snippet)
    return out


def core(name: str) -> str:
    """去掉常见称谓前后缀。整个名字就是称谓时保留原样。"""
    changed = True
    while changed:
        changed = False
        for a in AFFIXES:
            if len(name) > len(a) and name.startswith(a):
                name, changed = name[len(a) :], True
            elif len(name) > len(a) and name.endswith(a):
                name, changed = name[: -len(a)], True
    return name


def hint_pairs(names: list[str], limit: int = HINT_LIMIT) -> list[tuple[str, str, str]]:
    pairs: dict[frozenset, tuple[str, str, str]] = {}
    by_core: dict[str, list[str]] = defaultdict(list)
    for n in names:
        by_core[core(n)].append(n)
    for group in by_core.values():
        for a, b in combinations(group, 2):
            pairs.setdefault(frozenset((a, b)), (a, b, "去掉称谓后相同"))
    by_len = sorted(names, key=len)
    for i, a in enumerate(by_len):
        if len(a) < 2:
            continue
        for b in by_len[i + 1 :]:
            if a != b and a in b:
                pairs.setdefault(frozenset((a, b)), (a, b, "一个包含另一个"))
    return list(pairs.values())[:limit]


def chunk_names(names: list[str], max_names: int, anchors: int) -> list[list[str]]:
    if len(names) <= max_names:
        return [names]
    head, rest = names[:anchors], names[anchors:]
    size = max_names - anchors
    return [head + rest[i : i + size] for i in range(0, len(rest), size)]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_entities.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/entities.py tests/test_entities.py
git commit -m "feat: 实体合并 汇总叫法/字面提示/分批"
```

---

## Task 10: 实体合并（中）：模型归组 + 步骤 5

**Files:**
- Modify: `src/ligaotai/entities.py`（追加）
- Test: `tests/test_entities.py`（追加）

要点：
- `check_groups(data, allowed)`：给 LLMClient 反馈用。检查 groups 是列表；名字都在给出的列表里；canonical 是 members 之一；一个名字不能出现在两个组里。
- `clean_groups(data, allowed)`：3 次后仍有问题时的兜底：丢掉未知名字、重复出现的名字（先到先得）、不足 2 个名字的组；canonical 不合法就用第一个成员。
- `merge_groups`：各批的结果用并查集合并；规范名取各批提议里出现次数最多的那个。
- `run_entities`：每种类型叫法不足 2 个就不调模型。模型看得到**全部**叫法（包括作者已确认组里的，当作参照），但出结果时，已确认组里的名字一律不动；剩下的名字组成草稿组，其余每个名字各成一个 `single` 实体。编号接着文件里用过的最大编号往后排，已确认组保留原编号。
- `实体.json`：`{"entities": [{"id": "E-0001", "type": "person", "canonical": "林清", "names": [...], "status": "draft|confirmed|single", "reason": "...", "scenes": [...]}]}`。
- 调用在 `finally` 里记用量；结果和上次不同才让下游过期。

- [ ] **Step 1: 追加失败的测试**

在 `tests/test_entities.py` 末尾追加：
```python
import pytest

from ligaotai import entities as ent
from ligaotai.entities import check_groups, clean_groups, merge_groups, run_entities
from ligaotai.fsutil import read_json, write_json

LIN = ["林清", "清儿", "林姑娘"]


def test_check_groups():
    allowed = {"林清", "清儿", "赵五"}
    assert check_groups({"groups": [{"canonical": "林清", "members": ["林清", "清儿"]}]}, allowed) == []
    assert check_groups({"x": 1}, allowed) == ["缺少 groups 列表"]
    problems = check_groups(
        {"groups": [
            {"canonical": "张三", "members": ["林清", "张三"]},
            {"canonical": "清儿", "members": ["清儿", "林清"]},
        ]},
        allowed,
    )
    text = "；".join(problems)
    assert "张三" in text and "同时出现在两个组" in text


def test_clean_groups():
    data = {"groups": [
        {"canonical": "张三", "members": ["林清", "张三", "清儿"], "reason": "r"},
        {"canonical": "清儿", "members": ["清儿", "赵五"]},
        {"canonical": "赵五", "members": ["赵五"]},
    ]}
    assert clean_groups(data, {"林清", "清儿", "赵五"}) == [
        {"canonical": "林清", "members": ["林清", "清儿"], "reason": "r"}
    ]


def test_merge_groups_across_chunks():
    groups = [
        {"canonical": "清儿", "members": ["清儿", "林清"], "reason": "a"},
        {"canonical": "林清", "members": ["林清", "林姑娘"], "reason": "b"},
        {"canonical": "赵五", "members": ["赵五", "老赵"], "reason": ""},
    ]
    merged = merge_groups(groups, {"林清": 5, "清儿": 2, "林姑娘": 1, "赵五": 3, "老赵": 1})
    assert merged[0] == {"canonical": "林清", "members": ["林清", "清儿", "林姑娘"], "reason": "a；b"}
    assert merged[1]["canonical"] == "赵五"


def test_run_entities_groups_aliases(story_book):
    run_cards(story_book, client_for(story_book))
    c = client_for(story_book, groups=[LIN])
    summary = run_entities(story_book, c)
    data = read_json(story_book.entities_path)
    persons = [e for e in data["entities"] if e["type"] == "person"]
    draft = [e for e in persons if e["status"] == "draft"]
    assert len(draft) == 1 and set(draft[0]["names"]) == set(LIN)
    assert draft[0]["canonical"] == "林清"
    assert [e["canonical"] for e in persons if e["status"] == "single"] == ["赵五"]
    assert {e["type"] for e in data["entities"]} == {"person", "location", "organization"}
    assert c.usage.calls == 1  # 地点、组织各只有一个叫法，不调模型
    assert summary["draft_groups"] == 1
    assert story_book.step("entities")["status"] == "done"
    assert story_book.load()["usage"]["by_step"]["entities"]["calls"] == 1


def test_confirmed_group_survives_rerun(story_book):
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    data = read_json(story_book.entities_path)
    group = next(e for e in data["entities"] if e["status"] == "draft")
    group["status"] = "confirmed"
    write_json(story_book.entities_path, data)

    run_entities(story_book, client_for(story_book, groups=[["林清", "赵五"]]))
    data = read_json(story_book.entities_path)
    kept = next(e for e in data["entities"] if e["id"] == group["id"])
    assert kept["status"] == "confirmed" and set(kept["names"]) == set(LIN)
    zhao = next(e for e in data["entities"] if e["canonical"] == "赵五")
    assert zhao["status"] == "single"
    assert len({e["id"] for e in data["entities"]}) == len(data["entities"])


def test_names_split_into_chunks(story_book, monkeypatch):
    run_cards(story_book, client_for(story_book))
    monkeypatch.setattr(ent, "MAX_NAMES_PER_CALL", 3)
    monkeypatch.setattr(ent, "ANCHOR_NAMES", 1)
    c = client_for(story_book, groups=[LIN])
    run_entities(story_book, c)
    assert c.usage.calls == 2
    data = read_json(story_book.entities_path)
    assert sum(e["status"] == "draft" for e in data["entities"]) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_entities.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'check_groups'`）

- [ ] **Step 3: 实现**

在 `src/ligaotai/entities.py` 的 import 区加：
```python
import asyncio
from typing import Callable

from .fsutil import read_json, write_json
from .llm import LLMClient
from .prompts import render
```

常量区加：
```python
DRAFT, CONFIRMED, SINGLE = "draft", "confirmed", "single"

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass
```

文件末尾追加：
```python
def check_groups(data: dict, allowed: set[str]) -> list[str]:
    groups = data.get("groups")
    if not isinstance(groups, list):
        return ["缺少 groups 列表"]
    problems: list[str] = []
    seen: dict[str, int] = {}
    for i, g in enumerate(groups):
        if not isinstance(g, dict) or not isinstance(g.get("members"), list):
            problems.append(f"第 {i + 1} 组格式不对")
            continue
        members = [m for m in g["members"] if isinstance(m, str)]
        unknown = [m for m in members if m not in allowed]
        if unknown:
            problems.append("这些名字不在给你的列表里：" + "、".join(unknown[:10]))
        if g.get("canonical") not in members:
            problems.append(f"「{g.get('canonical')}」这组的 canonical 必须是 members 里的一个")
        for m in members:
            if m in seen and seen[m] != i:
                problems.append(f"「{m}」同时出现在两个组里")
            seen[m] = i
    return problems[:20]


def clean_groups(data: dict, allowed: set[str]) -> list[dict]:
    out: list[dict] = []
    taken: set[str] = set()
    for g in data.get("groups") or []:
        if not isinstance(g, dict):
            continue
        members: list[str] = []
        for m in g.get("members") or []:
            if isinstance(m, str) and m in allowed and m not in taken and m not in members:
                members.append(m)
        if len(members) < 2:
            continue
        taken.update(members)
        canonical = g.get("canonical") if g.get("canonical") in members else members[0]
        out.append({"canonical": canonical, "members": members, "reason": str(g.get("reason") or "")})
    return out


def merge_groups(groups: list[dict], counts: dict[str, int]) -> list[dict]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for g in groups:
        for m in g["members"][1:]:
            ra, rb = find(g["members"][0]), find(m)
            if ra != rb:
                parent[rb] = ra
    buckets: dict[str, list[dict]] = defaultdict(list)
    for g in groups:
        buckets[find(g["members"][0])].append(g)
    out = []
    for gs in buckets.values():
        members = sorted({m for g in gs for m in g["members"]}, key=lambda n: (-counts.get(n, 0), n))
        proposed = [g["canonical"] for g in gs if g["canonical"] in members]
        canonical = max(proposed, key=lambda n: counts.get(n, 0)) if proposed else members[0]
        reason = "；".join(dict.fromkeys(g["reason"] for g in gs if g["reason"]))
        out.append({"canonical": canonical, "members": members, "reason": reason})
    return out


def _name_lines(names: list[str], mentions: dict[str, Mention]) -> str:
    return "\n".join(
        f"- {n}（{mentions[n].count} 个场景）：" + (" ／ ".join(mentions[n].contexts) or "（无上下文）")
        for n in names
    )


def _hint_lines(pairs: list[tuple[str, str, str]]) -> str:
    return "\n".join(f"- {a} ↔ {b}（{why}）" for a, b, why in pairs) or "（无）"


async def cluster_type(client: LLMClient, typ: str, mentions: dict[str, Mention]) -> list[dict]:
    names = sorted(mentions, key=lambda n: (-mentions[n].count, n))
    if len(names) < 2:
        return []
    groups: list[dict] = []
    for i, chunk in enumerate(chunk_names(names, MAX_NAMES_PER_CALL, ANCHOR_NAMES), 1):
        allowed = set(chunk)
        system, user = render(
            "entities",
            type_label=TYPE_LABELS[typ],
            names=_name_lines(chunk, mentions),
            hints=_hint_lines(hint_pairs(chunk)),
        )
        data, _ = await client.chat_json(
            "synth", system, user, lambda d, allowed=allowed: check_groups(d, allowed), tag=f"entities/{typ}-{i}"
        )
        groups.extend(clean_groups(data, allowed))
    return merge_groups(groups, {n: m.count for n, m in mentions.items()})


def _scenes_of(names: list[str], mentions: dict[str, Mention]) -> list[str]:
    return sorted({s for n in names if n in mentions for s in mentions[n].scenes}, key=natural_key)


def _entity(num: int, typ: str, canonical: str, names: list[str], status: str, reason: str,
            mentions: dict[str, Mention]) -> dict:
    ordered = sorted(names, key=lambda n: (-(mentions[n].count if n in mentions else 0), n))
    return {
        "id": f"E-{num:04d}",
        "type": typ,
        "canonical": canonical,
        "names": ordered,
        "status": status,
        "reason": reason,
        "scenes": _scenes_of(names, mentions),
    }


def _signature(data: dict) -> list:
    return sorted((e["type"], e["canonical"], tuple(sorted(e["names"])), e["status"]) for e in data["entities"])


def run_entities(book: Book, client: LLMClient, progress: Progress = _noop) -> dict:
    return asyncio.run(_run_entities(book, client, progress))


async def _run_entities(book: Book, client: LLMClient, progress: Progress) -> dict:
    mentions = collect_mentions(book)
    old = read_json(book.entities_path, {"entities": []})
    confirmed = [e for e in old["entities"] if e["status"] == CONFIRMED]
    locked = {(e["type"], n) for e in confirmed for n in e["names"]}
    next_num = max((int(e["id"][2:]) for e in old["entities"]), default=0) + 1
    entities = [{**e, "scenes": _scenes_of(e["names"], mentions[e["type"]])} for e in confirmed]
    progress(0, len(TYPES))
    try:
        for i, typ in enumerate(TYPES, 1):
            ms = mentions[typ]
            free = {n for n in ms if (typ, n) not in locked}
            grouped: set[str] = set()
            for g in await cluster_type(client, typ, ms):
                members = [n for n in g["members"] if n in free]
                if len(members) < 2:
                    continue
                canonical = g["canonical"] if g["canonical"] in members else members[0]
                entities.append(_entity(next_num, typ, canonical, members, DRAFT, g["reason"], ms))
                next_num += 1
                grouped.update(members)
            for n in sorted(free - grouped, key=lambda n: (-ms[n].count, n)):
                entities.append(_entity(next_num, typ, n, [n], SINGLE, "", ms))
                next_num += 1
            progress(i, len(TYPES))
    finally:
        u = client.usage
        book.add_usage("entities", u.calls, u.prompt_tokens, u.completion_tokens, u.cost(client.cfg))
    data = {"entities": entities}
    changed = _signature(old) != _signature(data)
    write_json(book.entities_path, data)
    summary = {
        "names": sum(len(v) for v in mentions.values()),
        "entities": len(entities),
        "draft_groups": sum(e["status"] == DRAFT for e in entities),
        "confirmed": len(confirmed),
        "calls": client.usage.calls,
        "cost_usd": round(client.usage.cost(client.cfg), 4),
    }
    book.set_step("entities", "done", summary, changed=changed)
    return summary
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_entities.py -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/entities.py tests/test_entities.py
git commit -m "feat: 步骤5 实体合并（模型归组、分批合并、保留作者确认）"
```

---

## Task 11: 实体合并（下）：作者的确认 / 改名 / 合并 / 拆分

**Files:**
- Modify: `src/ligaotai/entities.py`（追加）
- Test: `tests/test_entities.py`（追加）

要点：每个操作都把相关实体标成 `confirmed`，写回 `实体.json`，并让下游步骤过期（归线要用规范名）。`canonical_map(book)` 给计划②b 用：`{(类型, 叫法): 规范名}`。

- 确认 `confirm(book, ids)`：这几个实体标成已确认。
- 改名 `rename(book, eid, canonical)`：规范名不能为空，可以不是现有叫法之一。
- 合并 `merge(book, ids, canonical=None)`：至少两个、类型相同；保留第一个的编号，名字和场景取并集，规范名默认用第一个的。
- 拆分 `split(book, eid, names)`：把指定叫法拆成一个新实体（编号接着最大的往后排），不能全拆走；两边的场景列表按当前场景卡重新算。

- [ ] **Step 1: 追加失败的测试**

在 `tests/test_entities.py` 末尾追加：
```python
from ligaotai.entities import canonical_map, confirm, merge, rename, split


@pytest.fixture
def grouped(story_book):
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    story_book.set_step("threads", "done")
    return story_book


def find(book, canonical):
    return next(e for e in read_json(book.entities_path)["entities"] if e["canonical"] == canonical)


def test_confirm(grouped):
    e = find(grouped, "林清")
    [out] = confirm(grouped, [e["id"]])
    assert out["status"] == "confirmed" and find(grouped, "林清")["status"] == "confirmed"
    assert grouped.step("threads")["status"] == "outdated"


def test_rename(grouped):
    e = find(grouped, "林清")
    assert rename(grouped, e["id"], " 林小清 ")["canonical"] == "林小清"
    with pytest.raises(ValueError):
        rename(grouped, e["id"], "  ")


def test_merge(grouped):
    lin, zhao = find(grouped, "林清"), find(grouped, "赵五")
    out = merge(grouped, [lin["id"], zhao["id"]])
    assert out["id"] == lin["id"] and set(out["names"]) == set(LIN) | {"赵五"}
    assert out["scenes"] == ["S-0001", "S-0002", "S-0003"] and out["status"] == "confirmed"
    ids = [e["id"] for e in read_json(grouped.entities_path)["entities"]]
    assert zhao["id"] not in ids


def test_merge_rejects_bad_input(grouped):
    lin, place = find(grouped, "林清"), find(grouped, "青州城外")
    with pytest.raises(ValueError):
        merge(grouped, [lin["id"]])
    with pytest.raises(ValueError):
        merge(grouped, [lin["id"], place["id"]])
    with pytest.raises(KeyError):
        merge(grouped, [lin["id"], "E-9999"])


def test_split(grouped):
    lin = find(grouped, "林清")
    new = split(grouped, lin["id"], ["林姑娘"])
    assert new["names"] == ["林姑娘"] and new["scenes"] == ["S-0003"] and new["status"] == "confirmed"
    rest = find(grouped, "林清")
    assert set(rest["names"]) == {"林清", "清儿"} and rest["scenes"] == ["S-0001", "S-0002"]
    with pytest.raises(ValueError):
        split(grouped, lin["id"], ["林清", "清儿"])
    with pytest.raises(ValueError):
        split(grouped, lin["id"], ["不存在"])


def test_canonical_map(grouped):
    m = canonical_map(grouped)
    assert m[("person", "清儿")] == "林清" and m[("person", "赵五")] == "赵五"
    assert m[("location", "青州城外")] == "青州城外"


def test_ops_before_run_raise(story_book):
    with pytest.raises(FileNotFoundError):
        confirm(story_book, ["E-0001"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_entities.py -q`
Expected: 新测试 FAIL（`ImportError: cannot import name 'canonical_map'`）

- [ ] **Step 3: 实现**

在 `src/ligaotai/entities.py` 末尾追加：
```python
def load_entities(book: Book) -> dict:
    data = read_json(book.entities_path)
    if data is None:
        raise FileNotFoundError("还没有实体合并的结果，先跑步骤 5")
    return data


def _save(book: Book, data: dict) -> None:
    write_json(book.entities_path, data)
    book.mark_downstream_outdated("entities")


def _get(data: dict, eid: str) -> dict:
    for e in data["entities"]:
        if e["id"] == eid:
            return e
    raise KeyError(eid)


def confirm(book: Book, ids: list[str]) -> list[dict]:
    data = load_entities(book)
    out = []
    for eid in ids:
        e = _get(data, eid)
        e["status"] = CONFIRMED
        out.append(e)
    _save(book, data)
    return out


def rename(book: Book, eid: str, canonical: str) -> dict:
    canonical = canonical.strip()
    if not canonical:
        raise ValueError("规范名不能为空")
    data = load_entities(book)
    e = _get(data, eid)
    e["canonical"], e["status"] = canonical, CONFIRMED
    _save(book, data)
    return e


def merge(book: Book, ids: list[str], canonical: str | None = None) -> dict:
    if len(set(ids)) < 2:
        raise ValueError("至少要选两个实体才能合并")
    data = load_entities(book)
    ents = [_get(data, eid) for eid in dict.fromkeys(ids)]
    if len({e["type"] for e in ents}) > 1:
        raise ValueError("不同类型的实体不能合并")
    keep = ents[0]
    keep.update(
        names=list(dict.fromkeys(n for e in ents for n in e["names"])),
        scenes=sorted({s for e in ents for s in e["scenes"]}, key=natural_key),
        canonical=(canonical or keep["canonical"]).strip(),
        status=CONFIRMED,
        reason="作者合并",
    )
    dropped = {e["id"] for e in ents[1:]}
    data["entities"] = [e for e in data["entities"] if e["id"] not in dropped]
    _save(book, data)
    return keep


def split(book: Book, eid: str, names: list[str]) -> dict:
    data = load_entities(book)
    e = _get(data, eid)
    wanted = set(names)
    moving = [n for n in e["names"] if n in wanted]
    if not moving or len(moving) != len(wanted):
        raise ValueError("要拆出去的叫法必须都在这个实体里")
    if len(moving) == len(e["names"]):
        raise ValueError("不能把全部叫法都拆出去")
    mentions = collect_mentions(book)[e["type"]]
    e["names"] = [n for n in e["names"] if n not in wanted]
    if e["canonical"] in wanted:
        e["canonical"] = e["names"][0]
    e["status"] = CONFIRMED
    e["scenes"] = _scenes_of(e["names"], mentions)
    num = max(int(x["id"][2:]) for x in data["entities"]) + 1
    new = _entity(num, e["type"], moving[0], moving, CONFIRMED, "作者拆分", mentions)
    data["entities"].append(new)
    _save(book, data)
    return new


def canonical_map(book: Book) -> dict[tuple[str, str], str]:
    return {(e["type"], n): e["canonical"] for e in load_entities(book)["entities"] for n in e["names"]}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_entities.py -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/entities.py tests/test_entities.py
git commit -m "feat: 实体合并 作者确认/改名/合并/拆分"
```

## Task 12: API：跑 AI 步骤、测试连接、暂停、场景卡和实体接口

**Files:**
- Modify: `src/ligaotai/api.py`（整个文件替换）
- Test: `tests/test_api_ai.py`

新增 / 变化的接口：

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/books/{name}/steps/{step}/run` | 现在也能跑 `cards`、`entities`；上游没 done → 409；没配 key → 400 |
| POST | `/api/config/test` | 两档模型各测一次，返回 `check_model` 的结果；没 key → 400 |
| POST | `/api/jobs/{id}/cancel` | 暂停当前任务 |
| GET | `/api/books/{name}/cards` | 每个场景的卡片概况：是否新鲜、kind、summary、问题数、删掉的条目数 |
| GET | `/api/books/{name}/cards/{sid}` | 一张卡的完整记录 |
| POST | `/api/books/{name}/cards/{sid}/regenerate` | 单独重做一张卡（任务） |
| GET | `/api/books/{name}/entities` | 实体.json |
| POST | `/api/books/{name}/entities/confirm` | body `{"ids": [...]}` |
| PUT | `/api/books/{name}/entities/{eid}` | 改规范名，body `{"canonical": "..."}` |
| POST | `/api/books/{name}/entities/merge` | body `{"ids": [...], "canonical": 可选}` |
| POST | `/api/books/{name}/entities/{eid}/split` | body `{"names": [...]}` |

`create_app` 多一个参数 `backend_factory`（默认 `OpenAIBackend`），测试里传一个返回 FakeBackend 的函数。任务被暂停时，步骤状态记为 `failed`，错误信息写「已暂停：做完的部分已经保存，重跑会接着做」。

- [ ] **Step 1: 写失败的测试**

`tests/test_api_ai.py`：
```python
import threading

import pytest
from fastapi.testclient import TestClient
from helpers import FakeBackend, fake_ai_handler

from ligaotai.api import create_app
from ligaotai.book import open_book

STORY = {
    "1.txt": "第一章 雪夜\n林清年方十六，住在青州城外。\n\n第二章 离城\n清儿背着包袱出了门，赵五在后面跟着。",
    "2.txt": "第三章 天机\n林姑娘进了天机阁，赵五守在门口。",
}
BOOK = "/api/books/我的书"


def make_client(tmp_path, groups=(["林清", "清儿", "林姑娘"],)):
    fake = FakeBackend(handler=fake_ai_handler(groups))
    app = create_app(app_dir=tmp_path, allowed_hosts=("testserver",), backend_factory=lambda cfg: fake)
    return TestClient(app)


def wait(client, response):
    assert response.status_code == 202, response.text
    job = client.app.state.runner.wait(response.json()["id"]).to_dict()
    assert job["status"] == "done", job["error"]
    return job


@pytest.fixture
def ready(tmp_path):
    c = make_client(tmp_path)
    src = tmp_path / "稿"
    src.mkdir()
    for name, text in STORY.items():
        (src / name).write_text(text, encoding="utf-8")
    c.post("/api/books", json={"title": "我的书"})
    wait(c, c.post(f"{BOOK}/import", json={"folder": str(src)}))
    wait(c, c.post(f"{BOOK}/steps/split/run"))
    wait(c, c.post(f"{BOOK}/steps/dedup/run"))
    return c


def test_cards_then_entities_flow(ready):
    c = ready
    wait(c, c.post(f"{BOOK}/steps/cards/run"))
    cards = c.get(f"{BOOK}/cards").json()
    assert [x["id"] for x in cards] == ["S-0001", "S-0002", "S-0003"]
    assert all(x["fresh"] and x["kind"] == "正文" for x in cards)
    assert c.get(f"{BOOK}/cards/S-0001").json()["card"]["characters"][0]["name"] == "林清"
    assert c.get(f"{BOOK}/cards/S-9999").status_code == 404
    wait(c, c.post(f"{BOOK}/cards/S-0002/regenerate"))

    wait(c, c.post(f"{BOOK}/steps/entities/run"))
    ents = c.get(f"{BOOK}/entities").json()["entities"]
    group = next(e for e in ents if e["status"] == "draft")
    assert set(group["names"]) == {"林清", "清儿", "林姑娘"}
    zhao = next(e for e in ents if e["canonical"] == "赵五")

    assert c.post(f"{BOOK}/entities/confirm", json={"ids": [group["id"]]}).json()[0]["status"] == "confirmed"
    assert c.put(f"{BOOK}/entities/{group['id']}", json={"canonical": "林小清"}).json()["canonical"] == "林小清"
    merged = c.post(f"{BOOK}/entities/merge", json={"ids": [group["id"], zhao["id"]]}).json()
    assert "赵五" in merged["names"]
    new = c.post(f"{BOOK}/entities/{group['id']}/split", json={"names": ["赵五"]}).json()
    assert new["names"] == ["赵五"]

    usage = c.get(BOOK).json()["usage"]
    assert usage["by_step"]["cards"]["calls"] == 4 and usage["by_step"]["entities"]["calls"] == 1


def test_entity_errors(ready):
    c = ready
    wait(c, c.post(f"{BOOK}/steps/cards/run"))
    wait(c, c.post(f"{BOOK}/steps/entities/run"))
    ents = c.get(f"{BOOK}/entities").json()["entities"]
    assert c.post(f"{BOOK}/entities/merge", json={"ids": [ents[0]["id"]]}).status_code == 400
    assert c.post(f"{BOOK}/entities/confirm", json={"ids": ["E-9999"]}).status_code == 404
    assert c.put(f"{BOOK}/entities/E-9999", json={"canonical": "x"}).status_code == 404


def test_entities_need_cards_first(ready):
    assert ready.post(f"{BOOK}/steps/entities/run").status_code == 409


def test_entity_ops_before_run_are_404(ready):
    assert ready.post(f"{BOOK}/entities/confirm", json={"ids": ["E-0001"]}).status_code == 404


def test_no_key_is_400(tmp_path):
    c = TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",)))
    c.post("/api/books", json={"title": "我的书"})
    book = open_book(tmp_path / "书库", "我的书")
    for step in ("import", "split", "dedup"):
        book.set_step(step, "done")
    r = c.post(f"{BOOK}/steps/cards/run")
    assert r.status_code == 400 and "API key" in r.json()["detail"]
    assert c.post("/api/config/test").status_code == 400


def test_config_test_endpoint(tmp_path):
    results = make_client(tmp_path).post("/api/config/test").json()
    assert [(r["tier"], r["ok"]) for r in results] == [("batch", True), ("synth", True)]


def test_cancel_endpoint(tmp_path):
    c = make_client(tmp_path)
    started, release = threading.Event(), threading.Event()

    def fn(progress):
        started.set()
        release.wait(5)
        progress(1, 1)
        return {}

    job = c.app.state.runner.submit("cards", "我的书", fn)
    started.wait(5)
    assert c.post(f"/api/jobs/{job.id}/cancel").json()["cancel_requested"] is True
    release.set()
    assert c.app.state.runner.wait(job.id).status == "cancelled"
    assert c.post("/api/jobs/nope/cancel").status_code == 404


def test_paused_step_is_marked(ready):
    c = ready
    runner = c.app.state.runner
    r = c.post(f"{BOOK}/steps/cards/run")
    job_id = r.json()["id"]
    runner.cancel(job_id)
    job = runner.wait(job_id)
    if job.status == "cancelled":
        assert "已暂停" in c.get(BOOK).json()["steps"]["cards"]["summary"]["error"]
```

说明：`test_paused_step_is_marked` 里，暂停请求可能在任务已经跑完之后才到（假接口很快），所以只在确实被暂停时检查步骤状态。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_api_ai.py -q`
Expected: FAIL（`create_app() got an unexpected keyword argument 'backend_factory'` 等）

- [ ] **Step 3: 实现 api.py**

`src/ligaotai/api.py` 整个替换为：
```python
"""FastAPI 应用。只给本机用：只认 127.0.0.1 / localhost 的 Host，不开 CORS。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel

from . import __version__
from . import entities as ent
from .book import STEP_LABELS, STEPS, Book, create_book, list_books, open_book, recover_interrupted
from .cards import is_fresh, load_card, load_cards, run_cards
from .config import (
    APP_DIR,
    AppConfig,
    apply_update,
    library_path,
    load_config,
    public_config,
    save_config,
)
from .dedup import run_dedup, set_main
from .fsutil import ensure_within, read_json
from .importer import check_import_folder, run_import
from .jobs import BusyError, JobCancelled, JobRunner
from .llm import ChatBackend, LLMClient, NoKeyError, OpenAIBackend, check_model
from .readers import read_text
from .scenes import SCENE_ID_RE, get_scene, load_scenes, run_split

RUNNABLE = ("split", "dedup", "cards", "entities")
PAUSED = "已暂停：做完的部分已经保存，重跑会接着做"


class NewBook(BaseModel):
    title: str


class ImportReq(BaseModel):
    folder: str


class MainReq(BaseModel):
    scene_id: str


class IdsReq(BaseModel):
    ids: list[str]


class MergeReq(BaseModel):
    ids: list[str]
    canonical: str | None = None


class RenameReq(BaseModel):
    canonical: str


class SplitReq(BaseModel):
    names: list[str]


def create_app(
    app_dir: Path = APP_DIR,
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost"),
    backend_factory: Callable[[AppConfig], ChatBackend] = OpenAIBackend,
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

    def make_backend(cfg: AppConfig) -> ChatBackend:
        try:
            return backend_factory(cfg)
        except NoKeyError as e:
            raise HTTPException(400, str(e))

    def make_client(book: Book) -> LLMClient:
        cfg = load_config(app_dir)
        return LLMClient(cfg, make_backend(cfg), log_dir=book.logs_dir)

    def submit(book: Book, step: str, fn: Callable[[Callable], dict]) -> dict:
        def work(progress: Callable) -> dict:
            book.set_step(step, "running")
            try:
                return fn(progress)
            except JobCancelled:
                book.set_step(step, "failed", {"error": PAUSED})
                raise
            except BaseException as e:
                book.set_step(step, "failed", {"error": f"{type(e).__name__}: {e}"})
                raise

        try:
            return runner.submit(step, book.name, work).to_dict()
        except BusyError as e:
            raise HTTPException(409, str(e))

    def require_upstream(book: Book, step: str) -> None:
        for prev in STEPS[: STEPS.index(step)]:
            if book.step(prev)["status"] != "done":
                raise HTTPException(409, f"请先完成上一步：{STEP_LABELS[prev]}")

    def step_work(book: Book, step: str) -> Callable[[Callable], dict]:
        if step == "split":
            return lambda p: run_split(book, p)
        if step == "dedup":
            return lambda p: run_dedup(book, p)
        client = make_client(book)
        if step == "cards":
            return lambda p: run_cards(book, client, p)
        return lambda p: ent.run_entities(book, client, p)

    def entity_op(fn: Callable[[], object]):
        try:
            return fn()
        except KeyError:
            raise HTTPException(404, "没有这个实体")
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/config")
    def get_config() -> dict:
        return public_config(load_config(app_dir), app_dir)

    @app.put("/api/config")
    def put_config(cfg: AppConfig) -> dict:
        save_config(apply_update(load_config(app_dir), cfg), app_dir)
        return get_config()

    @app.post("/api/config/test")
    def test_config() -> list:
        cfg = load_config(app_dir)
        return check_model(cfg, make_backend(cfg))

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
        try:
            check_import_folder(b, folder)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return submit(b, "import", lambda p: run_import(b, folder, p))

    @app.post("/api/books/{name}/steps/{step}/run", status_code=202)
    def run_step(name: str, step: str) -> dict:
        b = get_book(name)
        if step not in RUNNABLE:
            raise HTTPException(400, f"这一步现在还不能跑：{step}")
        require_upstream(b, step)
        return submit(b, step, step_work(b, step))

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

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        job = runner.cancel(job_id)
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

    @app.get("/api/books/{name}/cards")
    def cards(name: str) -> list:
        b = get_book(name)
        records = load_cards(b)
        out = []
        for s in load_scenes(b):
            if s.removed:
                continue
            r = records.get(s.id)
            out.append({
                "id": s.id,
                "fresh": is_fresh(r, s),
                "kind": r["card"]["kind"] if r else None,
                "summary": r["card"]["summary"] if r else "",
                "problems": len(r["problems"]) if r else 0,
                "dropped": sum(len(v) for v in r["dropped"].values()) if r else 0,
            })
        return out

    @app.get("/api/books/{name}/cards/{sid}")
    def card(name: str, sid: str) -> dict:
        b = get_book(name)
        record = load_card(b, sid) if SCENE_ID_RE.match(sid) else None
        if record is None:
            raise HTTPException(404, "这个场景还没有场景卡")
        return record

    @app.post("/api/books/{name}/cards/{sid}/regenerate", status_code=202)
    def regenerate_card(name: str, sid: str) -> dict:
        b = get_book(name)
        try:
            get_scene(b, sid)
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, "没有这个场景")
        require_upstream(b, "cards")
        client = make_client(b)
        return submit(b, "cards", lambda p: run_cards(b, client, p, only=[sid]))

    @app.get("/api/books/{name}/entities")
    def entities(name: str) -> dict:
        b = get_book(name)
        return read_json(b.entities_path, {"entities": []})

    @app.post("/api/books/{name}/entities/confirm")
    def confirm_entities(name: str, req: IdsReq) -> list:
        b = get_book(name)
        return entity_op(lambda: ent.confirm(b, req.ids))

    @app.post("/api/books/{name}/entities/merge")
    def merge_entities(name: str, req: MergeReq) -> dict:
        b = get_book(name)
        return entity_op(lambda: ent.merge(b, req.ids, req.canonical))

    @app.put("/api/books/{name}/entities/{eid}")
    def rename_entity(name: str, eid: str, req: RenameReq) -> dict:
        b = get_book(name)
        return entity_op(lambda: ent.rename(b, eid, req.canonical))

    @app.post("/api/books/{name}/entities/{eid}/split")
    def split_entity(name: str, eid: str, req: SplitReq) -> dict:
        b = get_book(name)
        return entity_op(lambda: ent.split(b, eid, req.names))

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

**执行前先比对**：这份替换是基于计划①结束时的 api.py 写的。动手前 `git diff` 看一眼当前 api.py 和上面的差别，除了本任务新增的部分，其余逻辑（导入检查、上游检查、原稿接口等）必须保持一致；如果当前文件里有这份代码没有的东西，保留它并在报告里说明。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -q`
Expected: 全部通过（包括计划①原有的 API 测试）

- [ ] **Step 5: Commit**

```bash
git add src/ligaotai/api.py tests/test_api_ai.py
git commit -m "feat: API 跑场景卡/实体合并、测试连接、暂停、实体确认合并拆分"
```

## Task 13: 别名合并验收脚本 tools/eval_entities.py

**Files:**
- Create: `tools/eval_entities.py`
- Test: `tests/test_eval_entities.py`

判定（spec 11.3「植入的别名被提议合并 ≥ 90%」）：弄乱脚本植入的每个新别名（金箍郎 / 天蓬郎 / 御弟師父），看场景卡抽出来的、**包含这个别名**的所有叫法（比如「金箍郎」「孫金箍郎」）里，有没有一个和这个人物的原名落进同一个实体。原名 = 答案里的 `replaces`、`canonical`，外加下面手写的标准别名表。召回率 = 命中数 / 植入数。

另外记录（不设门槛）：
- 标准别名表里每个人物，有几个叫法被合进了同一个实体、哪些没合进来；
- 误合并：一个实体里混进了两个不同主角的叫法。

书名固定为「验收-实体-<乱稿文件夹名>」，重跑时直接打开这本书：已经做好的新鲜场景卡会跳过，不重复花钱，只重新做实体合并。

- [ ] **Step 1: 写失败的测试**

`tests/test_eval_entities.py`：
```python
from helpers import FakeBackend, fake_ai_handler, make_chapters

from ligaotai.config import AppConfig
from tools.eval_entities import evaluate, run_eval
from tools.scramble import scramble

KEY = {"aliases": [
    {"replaces": "悟空", "alias": "金箍郎", "canonical": "孫悟空", "chapters": [1]},
    {"replaces": "八戒", "alias": "天蓬郎", "canonical": "豬八戒", "chapters": [1]},
]}


def person(eid, canonical, names):
    return {"id": eid, "type": "person", "canonical": canonical, "names": names, "status": "draft"}


def test_evaluate_counts_injected_and_gold():
    entities = [
        person("E-1", "孫悟空", ["孫悟空", "悟空", "金箍郎", "行者"]),
        person("E-2", "孫行者", ["孫行者"]),
        person("E-3", "天蓬郎", ["天蓬郎"]),
        person("E-4", "八戒", ["八戒", "唐僧"]),
    ]
    r = evaluate(entities, KEY)
    assert (r["injected_found"], r["injected_total"], r["pass"]) == (1, 2, False)
    assert r["injected"][0]["extracted"] == ["金箍郎"] and r["injected"][0]["merged"] is True
    assert r["gold"]["孫悟空"]["present"] == 4 and r["gold"]["孫悟空"]["left_out"] == ["孫行者"]
    assert r["wrong_merges"] == [{"id": "E-4", "canonical": "八戒", "characters": ["唐三藏", "豬八戒"]}]


def test_alias_never_extracted_is_a_miss():
    r = evaluate([person("E-1", "孫悟空", ["孫悟空", "悟空"])], KEY)
    assert r["injected"][0]["extracted"] == [] and r["injected_found"] == 0


GROUPS = [["悟空", "金箍郎"], ["八戒", "天蓬郎"], ["唐僧", "御弟師父"]]
SMALL = dict(n_delete=2, n_truncate=2, n_full=3, n_excerpt=2, alias_chapters=5)


def test_end_to_end_with_fake_model(tmp_path):
    out = tmp_path / "乱稿"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    report = run_eval(out, key, tmp_path / "书库", AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))
    assert report["injected_total"] == 3
    assert report["injected_recall"] == 1.0 and report["pass"] is True
    assert report["cards"]["fresh"] == report["cards"]["scenes"]
    first_calls = report["usage"]["by_step"]["cards"]["calls"]

    again = run_eval(out, key, tmp_path / "书库", AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))
    assert again["usage"]["by_step"]["cards"]["calls"] == first_calls  # 场景卡没有重做


def test_end_to_end_without_merges_fails(tmp_path):
    out = tmp_path / "乱稿"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    report = run_eval(out, key, tmp_path / "书库", AppConfig(), FakeBackend(handler=fake_ai_handler([])))
    assert report["injected_recall"] == 0.0 and report["pass"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_eval_entities.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'tools.eval_entities'`

- [ ] **Step 3: 实现**

`tools/eval_entities.py`：
```python
"""验收：别名合并（spec 11.3「植入的别名被提议合并 ≥ 90%」）。

在验收书库里用固定书名建（或打开）一本书：导入乱稿 → 切场景 → 查重 → 场景卡 → 实体合并，
然后对照弄乱脚本的答案。书名固定，所以重跑时新鲜的场景卡会跳过，不重复花钱。

用法：
  uv run python tools/eval_entities.py --check-only
  uv run python tools/eval_entities.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json
报告写到 --report（默认 data/验收-实体.json）。终端只打 ASCII，中文内容看报告文件。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from ligaotai.book import Book, create_book, open_book
from ligaotai.cards import run_cards
from ligaotai.config import AppConfig, load_config
from ligaotai.dedup import run_dedup
from ligaotai.entities import run_entities
from ligaotai.fsutil import read_json, safe_name
from ligaotai.importer import run_import
from ligaotai.llm import ChatBackend, LLMClient, NoKeyError, OpenAIBackend, check_model
from ligaotai.scenes import run_split

PASS_RECALL = 0.9
TITLE_PREFIX = "验收-实体-"
# 《西游记》主角的标准叫法（繁体，古登堡版的写法）。不含弄乱脚本植入的新别名。
GOLD = {
    "孫悟空": ["孫悟空", "悟空", "行者", "孫行者", "大聖", "齊天大聖", "美猴王", "猴王", "孫大聖"],
    "豬八戒": ["豬八戒", "八戒", "悟能", "豬悟能", "豬剛鬣", "呆子"],
    "唐三藏": ["唐三藏", "唐僧", "三藏", "玄奘", "陳玄奘", "御弟", "唐御弟"],
    "沙悟淨": ["沙悟淨", "沙僧", "悟淨", "沙和尚"],
}


def evaluate(entities: list[dict], key: dict, gold: dict = GOLD) -> dict:
    ent_of = {n: e["id"] for e in entities if e["type"] == "person" for n in e["names"]}
    injected = []
    for a in key["aliases"]:
        variants = sorted(n for n in ent_of if a["alias"] in n)
        targets = set(gold.get(a["canonical"], [])) | {a["replaces"], a["canonical"]}
        target_ids = {ent_of[n] for n in targets if n in ent_of}
        merged = any(ent_of[v] in target_ids for v in variants)
        injected.append({"alias": a["alias"], "canonical": a["canonical"], "extracted": variants, "merged": merged})
    found = sum(x["merged"] for x in injected)
    total = len(injected)

    gold_report = {}
    for canon, names in gold.items():
        present = [n for n in names if n in ent_of]
        if not present:
            gold_report[canon] = {"present": 0, "merged": 0, "left_out": []}
            continue
        main = Counter(ent_of[n] for n in present).most_common(1)[0][0]
        gold_report[canon] = {
            "present": len(present),
            "merged": sum(ent_of[n] == main for n in present),
            "left_out": [n for n in present if ent_of[n] != main],
        }

    char_of = {n: c for c, names in gold.items() for n in names}
    wrong = []
    for e in entities:
        if e["type"] != "person":
            continue
        chars = sorted({char_of[n] for n in e["names"] if n in char_of})
        if len(chars) > 1:
            wrong.append({"id": e["id"], "canonical": e["canonical"], "characters": chars})

    recall = found / total if total else 1.0
    return {
        "injected_found": found,
        "injected_total": total,
        "injected_recall": round(recall, 4),
        "pass": recall >= PASS_RECALL,
        "injected": injected,
        "gold": gold_report,
        "wrong_merges": wrong,
    }


def open_or_create(library: Path, title: str) -> Book:
    try:
        return open_book(library, safe_name(title))
    except FileNotFoundError:
        return create_book(library, title)


def run_eval(folder: Path, key: dict, library: Path, cfg: AppConfig, backend: ChatBackend) -> dict:
    folder = Path(folder).resolve()
    Path(library).mkdir(parents=True, exist_ok=True)
    book = open_or_create(Path(library), TITLE_PREFIX + folder.name)
    run_import(book, folder)
    run_split(book)
    run_dedup(book)
    cards = run_cards(book, LLMClient(cfg, backend, log_dir=book.logs_dir))
    entities = run_entities(book, LLMClient(cfg, backend, log_dir=book.logs_dir))
    report = evaluate(read_json(book.entities_path)["entities"], key)
    report.update(
        book=str(book.root),
        cards={k: cards[k] for k in ("scenes", "fresh", "written", "with_problems", "missing_count")},
        cards_failed=cards["failed"],
        entities=entities,
        usage=book.load().get("usage", {}),
    )
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="evaluate alias merging against a scramble answer key")
    ap.add_argument("--check-only", action="store_true", help="only test both model tiers")
    ap.add_argument("--folder")
    ap.add_argument("--key")
    ap.add_argument("--library", default="data/验收书库")
    ap.add_argument("--report", default="data/验收-实体.json")
    args = ap.parse_args(argv)
    cfg = load_config()
    try:
        backend = OpenAIBackend(cfg)
    except NoKeyError:
        sys.exit("no API key configured (config.json api_key or env LIGAOTAI_API_KEY)")
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if args.check_only:
        results = check_model(cfg, backend)
        report_path.with_name("验收-连接测试.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for r in results:
            print(f"{r['tier']} model={r['model']} ok={r['ok']} seconds={r['seconds']}")
        sys.exit(0 if all(r["ok"] for r in results) else 1)
    if not args.folder or not args.key:
        sys.exit("--folder and --key are required")
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    report = run_eval(Path(args.folder), key, Path(args.library), cfg, backend)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    total = report["usage"].get("total", {})
    print(
        f"injected={report['injected_found']}/{report['injected_total']} recall={report['injected_recall']} "
        f"pass={report['pass']} wrong_merges={len(report['wrong_merges'])} "
        f"cards={report['cards']['fresh']}/{report['cards']['scenes']} failed={len(report['cards_failed'])} "
        f"calls={total.get('calls', 0)} cost_usd={total.get('cost_usd', 0)}"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_eval_entities.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add tools/eval_entities.py tests/test_eval_entities.py
git commit -m "feat: 别名合并验收脚本"
```

---

## Task 14: 用真模型跑验收（要作者配合）

**Files:**
- Create: `docs/验收记录/<执行当天日期>-计划2a-实体合并.md`

这一步会花真钱（估计不到 1 美元），而且需要作者的 API key。**不许为了过门槛去改提示词或阈值**：没过就按排查步骤找原因，报给作者，等作者点头再改。

- [ ] **Step 1: 请作者配置 key**

请作者自己在终端里执行（**key 不要发在聊天里**）：`notepad config.json`，写入
```json
{"api_key": "sk-你的key"}
```
保存。然后确认（只打印有没有，不打印 key）：

Run: `uv run python -c "from ligaotai.config import load_config, public_config; print(public_config(load_config())['has_key'])"`
Expected: `True`

- [ ] **Step 2: 测两档模型**

Run: `uv run python tools/eval_entities.py --check-only`
Expected: 两行，`batch ... ok=True`、`synth ... ok=True`

如果 synth 失败，读 `data/验收-连接测试.json` 看错误。若是「思考模式和 JSON 模式不能同时用」一类的 400 错误：报给作者，建议把综合档的默认值改成 `json_mode=False`（改 `config.py` 的 `_synth_tier` 并更新 `test_model_defaults`，提示词里本来就要求只输出 json，`parse_json` 能去掉代码块围栏），作者同意后再改。

- [ ] **Step 3: 报费用估算，等作者同意**

西游记验收书约 268 个场景，每个场景输入约 3–4 千 token、输出约 1 千 token，按默认的高峰单价估算约 0.5–0.8 美元（闲时减半）。把这个估算告诉作者，同意后再跑。

- [ ] **Step 4: 跑验收**

Run（预计 5–15 分钟，放后台跑）: `uv run python tools/eval_entities.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json`
Expected: 一行 ASCII，`injected=3/3 ... pass=True`

然后用 Read 工具读 `data/验收-实体.json`：看 `injected`、`gold`、`wrong_merges`、`cards_failed`、`usage`。

- [ ] **Step 5: 没过门槛时的排查（过了就跳过）**

使用 superpowers:systematic-debugging。对每个没命中的别名：
- `extracted` 是空的 → 场景卡没抽出这个名字。在 `data/验收书库/验收-实体-乱稿-西游记/场景卡/` 里找含这个别名的章节对应的卡，看 `characters` 和 `dropped`，再看 `日志/cards/` 里的原始回复。
- 抽出来了但没合并 → 看 `日志/entities/person-*.json` 里模型的回复和理由。

把原因和打算怎么改写下来，报给作者，**等作者点头再改**。

- [ ] **Step 6: 抽查 10 张场景卡**

随机打开 10 个 `场景卡/S-*.json`，检查：summary 是否说对了发生什么；人名是否照原文（繁体）抄；facts 的 quote 是否真的在原文里；`dropped` 里删掉了什么。把观察写进验收记录。

- [ ] **Step 7: 写验收记录并提交**

`docs/验收记录/<日期>-计划2a-实体合并.md`，数字从 `data/验收-实体.json` 抄：
```markdown
# 计划②a 验收：场景卡 + 实体合并（人造乱稿《西游记》）

- 日期：
- 模型：批量档 / 综合档的模型名、思考设置
- 乱稿：同计划①验收（seed=7），植入别名 金箍郎 / 天蓬郎 / 御弟師父

## 结果
| 指标 | 结果 | 门槛 |
|---|---|---|
| 植入别名被合并 | found / total | ≥ 90% |
| 孫悟空 标准叫法合并 | merged / present（没合进来的：…） | 只记录 |
| 豬八戒 / 唐三藏 / 沙悟淨 | 同上 | 只记录 |
| 误合并（一个实体混了两个主角） | 个数 | 只记录 |
| 场景卡：新鲜 / 总数，有问题的，失败的 | | 只记录 |
| 调用次数、token、费用、耗时 | | 只记录 |

## 场景卡抽查
（10 张的观察）

## 发现的问题
```

```bash
git add docs/验收记录/
git commit -m "docs: 计划②a 实体合并验收记录"
```

---

## Task 15: 收尾

- [ ] **Step 1: 全量测试**

Run: `uv run pytest -q`
Expected: 全部通过，0 failed

- [ ] **Step 2: 起服务，用真 key 测一次连接接口**

Run（后台）: `uv run python -m ligaotai`，然后 `curl -s -X POST http://127.0.0.1:8765/api/config/test`
Expected: 两档都 `"ok":true`。确认后停掉服务。

- [ ] **Step 3: 确认 key 没进仓库**

Run: `git status --short; git log -p --all | grep -c "sk-"`
Expected: 没有未提交文件；grep 计数为 0（`config.json` 在 .gitignore 里）。

- [ ] **Step 4: 交给作者**

用 superpowers:finishing-a-development-branch。仓库是公开的，**推送到 GitHub 前先问作者**。汇报：测试数、别名合并召回、误合并、场景卡抽查结论、实际花费。

