"""模型调用：OpenAI 兼容的 Chat Completions 接口（默认 DeepSeek）。

LLMClient.chat_json 负责：要 JSON → 解析 → 调用方给的检查函数 → 有问题就带着问题重试，
统计 token 用量，每次调用的请求和返回写进书的 日志/ 目录。并发由一个信号量控制。
真正发请求的是 backend（OpenAIBackend），测试里换成假的。
"""

from __future__ import annotations

import json
import re
import asyncio
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol

from openai import AsyncOpenAI

from .book import now_iso
from .config import AppConfig, TierConfig, effective_key
from .fsutil import write_json

MAX_ATTEMPTS = 3
MAX_TOKENS_CAP = 65536
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")

Checker = Callable[[dict], list]  # 返回问题清单（字符串），空列表 = 合格；检查函数不许抛异常，有问题就返回问题清单


class LLMError(RuntimeError):
    """这一项调用失败（可以单独重跑）。"""


class FatalLLMError(LLMError):
    """整个步骤都不用再跑了：key 不对、欠费、没权限。"""


class NoKeyError(FatalLLMError):
    """还没配置 API key。"""


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
        self._sem: asyncio.Semaphore | None = None
        self._sem_loop: asyncio.AbstractEventLoop | None = None

    def tier(self, name: str) -> TierConfig:
        if name not in ("batch", "synth"):
            raise ValueError(f"没有这一档模型：{name}")
        return getattr(self.cfg, name)

    def _semaphore(self) -> asyncio.Semaphore:
        """懒建信号量：跨两次 asyncio.run 用同一个 client 时，第一次绑定的循环已经关掉了，
        不能继续用同一个信号量，所属循环变了就重建。"""
        loop = asyncio.get_running_loop()
        if self._sem is None or self._sem_loop is not loop:
            self._sem = asyncio.Semaphore(self.cfg.concurrency)
            self._sem_loop = loop
        return self._sem

    async def _call(self, tier: TierConfig, messages: list[dict], max_tokens: int) -> Reply:
        try:
            async with self._semaphore():
                return await self.backend.complete(tier, messages, max_tokens)
        except LLMError:
            raise
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
            if reply.finish_reason == "length":
                # 思考模式把 max_tokens 用光时，回复常常是空内容 + finish_reason="length"；
                # 截断要先判断，不然会被下面的空内容分支接住，额度不翻倍，白白再花一次满额度的钱。
                problems = ["输出太长被截断了"]
                max_tokens = max(max_tokens, min(max_tokens * 2, MAX_TOKENS_CAP))
                continue
            if not reply.content.strip():
                problems = ["模型返回了空内容"]
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
        try:
            write_json(
                self.log_dir / f"{tag}-{attempt}.json",
                {"time": now_iso(), "tier": tier.model_dump(), "messages": messages, "reply": asdict(reply)},
            )
        except OSError:
            pass  # 日志是辅助功能，写失败不该让已经花了钱的这次调用也跟着失败


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
