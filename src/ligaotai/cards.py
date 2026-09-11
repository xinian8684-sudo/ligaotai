"""步骤 4 场景卡：每个场景块单独调一次模型（批量档），按 spec 5.2 的字段出 JSON。

模型写的 quote 和人名、地名、组织名都要能在原文里找到（去掉空白和标点后比较）。
找不到就带着问题重试；3 次后还有，就删掉这些条目，记在卡的 dropped 里。
"""

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

SUMMARY_LIMIT = 200  # 提示词要求 150 字，这里留点余量
MISSING_LIST_LIMIT = 200

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


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
