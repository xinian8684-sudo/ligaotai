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
