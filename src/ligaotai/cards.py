"""步骤 4 场景卡：每个场景块单独调一次模型（批量档），按 spec 5.2 的字段出 JSON。

模型写的 quote 和人名、地名、组织名都要能在原文里找到（去掉空白和标点后比较）。
找不到就带着问题重试；3 次后还有，就删掉这些条目，记在卡的 dropped 里。

对模型输出宽松一些：null、该给列表却给了单个字符串、role 写错、数字当字符串……
这些不算格式错，直接纠正，别让作者的调用额度浪费在无意义的重试上。
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, Literal, get_origin

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .book import Book, now_iso
from .dedup import normalize
from .fsutil import read_json, write_json
from .jobs import JobCancelled
from .llm import FatalLLMError, LLMClient, LLMError
from .prompts import render
from .scenes import SCENE_ID_RE, Scene, load_scenes

SUMMARY_LIMIT = 200  # 提示词要求 150 字，这里留点余量
MIN_QUOTE_LEN = 4  # quote 去掉空白标点后至少要这么长，否则「他」「是」这种到处都能匹配上
MISSING_LIST_LIMIT = 200

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


_EDGE = re.compile(r"^[\W_]+|[\W_]+$")


def strip_edges(s: str) -> str:
    """去掉字符串首尾的空白和标点，保留中间内容（如「林清，」→「林清」）。"""
    return _EDGE.sub("", s)


def cards_normalize(s: str) -> str:
    """场景卡自己的比较函数：NFKC 归一（全角变半角）→ 去空白标点（复用 dedup.normalize）
    → casefold（英文大小写不敏感）。原文 body 和被核对的字符串必须用同一个函数处理，
    否则「Ｔｏｍ」「TOM」「tom」互相对不上。"""
    return normalize(unicodedata.normalize("NFKC", s)).casefold()


class Character(BaseModel):
    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)
    name: str
    role: Literal["主要", "次要", "提及"] = "提及"

    @model_validator(mode="before")
    @classmethod
    def _lenient(cls, data: Any) -> Any:
        if isinstance(data, str):
            data = {"name": data}
        if isinstance(data, dict):
            data = dict(data)
            if isinstance(data.get("name"), str):
                data["name"] = strip_edges(data["name"])
            if data.get("role") not in ("主要", "次要", "提及"):
                data["role"] = "提及"
        return data


class Fact(BaseModel):
    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)
    subject: str
    attribute: str
    value: str
    quote: str

    @model_validator(mode="before")
    @classmethod
    def _strip_subject(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("subject"), str):
            data = dict(data)
            data["subject"] = strip_edges(data["subject"])
        return data


class Card(BaseModel):
    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)
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

    @model_validator(mode="before")
    @classmethod
    def _lenient(cls, data: Any) -> Any:
        """模型输出常见的小毛病，直接纠正，别判格式错白白重试：
        字段值是 null → 按字段类型给默认值；该给列表却给了单个值 → 包成单元素列表。
        kind 给了不认识的值不在这里处理，让下面正常的字段校验去报格式错。"""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for name, info in cls.model_fields.items():
            if name not in data:
                continue
            value = data[name]
            ann = info.annotation
            if value is None:
                if get_origin(ann) is list:
                    data[name] = []
                elif ann is str:
                    data[name] = ""
                elif ann is bool:
                    data[name] = False
                elif info.is_required():
                    del data[name]
                else:
                    data[name] = info.get_default(call_default_factory=True)
                continue
            if get_origin(ann) is list and not isinstance(value, list):
                data[name] = [value]
        return data

    @model_validator(mode="after")
    def _drop_blank_names(self) -> "Card":
        """名字（characters.name / locations / organizations / pov / facts.subject）
        去掉首尾标点后如果变成空串，静默丢掉：不报问题，也不进 dropped。"""
        self.pov = strip_edges(self.pov) if self.pov else ""
        self.locations = [n for n in (strip_edges(x) for x in self.locations) if n]
        self.organizations = [n for n in (strip_edges(x) for x in self.organizations) if n]
        self.characters = [c for c in self.characters if c.name]
        self.facts = [f for f in self.facts if f.subject]
        return self


def brief_errors(e: ValidationError) -> str:
    return "；".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:3])


def card_names(card: Card) -> list[str]:
    names = [c.name for c in card.characters] + card.locations + card.organizations
    if card.pov:
        names.append(card.pov)
    return names


def _in_text(s: str, body: str) -> bool:
    n = cards_normalize(s)
    return bool(n) and n in body


def _quote_ok(quote: str, body: str) -> bool:
    n = cards_normalize(quote)
    return len(n) >= MIN_QUOTE_LEN and n in body


def check_card(data: dict, text: str) -> list[str]:
    try:
        card = Card.model_validate(data)
    except ValidationError as e:
        return [f"字段格式不对：{brief_errors(e)}"]
    body = cards_normalize(text)
    problems = []
    if len(card.summary) > SUMMARY_LIMIT:
        problems.append("summary 太长了，请压到 150 字以内")
    bad_quotes = [f.quote for f in card.facts if not _quote_ok(f.quote, body)]
    if bad_quotes:
        problems.append("这些 quote 不是从原文逐字复制的（或太短，没法核对）：" + "；".join(bad_quotes[:5]))
    bad_names = sorted({n for n in card_names(card) if not _in_text(n, body)})
    if bad_names:
        problems.append("这些名字在原文里找不到，请照原文的写法：" + "、".join(bad_names[:10]))
    # fact 的 subject 也要核对：能在原文里找到，或者是本卡自己列出的某个名字
    # （哪怕那个名字本身也没核对过——它的问题已经在上面的 bad_names 里报过一次了，不重复报）。
    names_norm = {cards_normalize(n) for n in card_names(card)} - {""}
    bad_subjects = sorted(
        {
            f.subject
            for f in card.facts
            if not _in_text(f.subject, body) and cards_normalize(f.subject) not in names_norm
        }
    )
    if bad_subjects:
        problems.append("这些 fact 的 subject 找不到对应的人物/地点/组织：" + "、".join(bad_subjects[:10]))
    return problems


def clean_card(card: Card, text: str) -> tuple[Card, dict]:
    body = cards_normalize(text)

    def keep_name(s: str) -> bool:
        return _in_text(s, body)

    kept_characters = [c for c in card.characters if keep_name(c.name)]
    kept_locations = [n for n in card.locations if keep_name(n)]
    kept_organizations = [n for n in card.organizations if keep_name(n)]
    kept_pov = card.pov if not card.pov or keep_name(card.pov) else ""

    dropped_names = sorted({n for n in card_names(card) if not keep_name(n)})

    # 名字被删了，以它为 subject 的 fact 也要一起删：只用「留下来的」名字集合去核对 subject。
    kept_names_norm = {
        cards_normalize(n)
        for n in [c.name for c in kept_characters]
        + kept_locations
        + kept_organizations
        + ([kept_pov] if kept_pov else [])
    } - {""}

    def keep_fact(f: Fact) -> bool:
        return _quote_ok(f.quote, body) and (
            _in_text(f.subject, body) or cards_normalize(f.subject) in kept_names_norm
        )

    kept_facts = [f for f in card.facts if keep_fact(f)]
    dropped_facts = [f.model_dump() for f in card.facts if not keep_fact(f)]

    summary = card.summary[:SUMMARY_LIMIT] if len(card.summary) > SUMMARY_LIMIT else card.summary

    cleaned = card.model_copy(
        update={
            "facts": kept_facts,
            "characters": kept_characters,
            "locations": kept_locations,
            "organizations": kept_organizations,
            "pov": kept_pov,
            "summary": summary,
        }
    )
    dropped = {"facts": dropped_facts, "names": dropped_names}
    return cleaned, dropped


def card_path(book: Book, sid: str) -> Path:
    return book.cards_dir / f"{sid}.json"


def load_card(book: Book, sid: str) -> dict | None:
    """卡文件不存在、是空文件/坏 JSON、或者顶层不是一个 json 对象，都当作「没有这张卡」，
    不让 JSONDecodeError 之类的异常冒出去炸掉整个步骤——下次跑会把它当缺卡重做。"""
    try:
        data = read_json(card_path(book, sid))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_cards(book: Book) -> dict[str, dict]:
    if not book.cards_dir.exists():
        return {}
    out = {}
    for p in book.cards_dir.glob("S-*.json"):
        if not SCENE_ID_RE.match(p.stem):
            continue  # 同步冲突之类的副本
        try:
            data = read_json(p)
        except (OSError, ValueError):
            continue  # 坏文件当作没有这张卡，下次会重做
        if isinstance(data, dict) and data.get("id") == p.stem:
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
    failed: list[dict] = []
    if only is not None:
        wanted = set(only)
        todo = [s for s in scenes if s.id in wanted]
        unknown = sorted(wanted - {s.id for s in todo})
        for sid in unknown:
            failed.append({"id": sid, "error": "场景不存在或已删除"})
    else:
        todo = [s for s in scenes if not is_fresh(records.get(s.id), s)]
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
        # 欠费/key 失效（FatalLLMError）要让作者看到，不能被「已暂停」（JobCancelled）盖住：
        # 两种异常同时出现在异常组里时，优先抛 FatalLLMError。
        fatal = [e for e in eg.exceptions if isinstance(e, FatalLLMError)]
        raise (fatal or list(eg.exceptions))[0] from None
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
