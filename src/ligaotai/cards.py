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
from .facts import VALUE_LIMIT, norm_attr
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
            if data.get("name") is None:
                data["name"] = ""
            elif isinstance(data.get("name"), str):
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
    def _lenient(cls, data: Any) -> Any:
        """subject 去首尾标点；attribute / value / quote 缺失或为 null 时当成空字符串——
        quote 空了会被 A3 判太短，3 次后只丢这一条 fact，不会让整张卡格式错。"""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if isinstance(data.get("subject"), str):
            data["subject"] = strip_edges(data["subject"])
        for name in ("attribute", "value", "quote"):
            if data.get(name) is None:
                data[name] = ""
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
            if get_origin(ann) is list:
                if not isinstance(value, list):
                    value = [value]
                data[name] = [v for v in value if v is not None]
        return data

    @model_validator(mode="after")
    def _drop_blank_names(self) -> "Card":
        """名字（characters.name / locations / organizations / pov / facts.subject）
        去掉首尾标点后如果变成空串，静默丢掉：不报问题，也不进 dropped。"""
        self.pov = strip_edges(self.pov) if self.pov else ""
        self.locations = [n for n in (strip_edges(x) for x in self.locations) if n]
        self.organizations = [n for n in (strip_edges(x) for x in self.organizations) if n]
        self.characters = [c for c in self.characters if c.name]
        # facts 不在这里按 subject 过滤：subject 去标点后是空串的 fact 要留到
        # check_card / clean_card 里当成 subject 问题处理（报出来 + 进 dropped），
        # 不能在这里就静默丢掉，否则问题不会被报出来（R4）。
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


def _quote_len_ok(quote: str) -> bool:
    return len(cards_normalize(quote)) >= MIN_QUOTE_LEN


def _quote_ok(quote: str, body: str) -> bool:
    n = cards_normalize(quote)
    return len(n) >= MIN_QUOTE_LEN and n in body


SUBJECT_QUOTE_HINT_LEN = 20  # subject 空着时，用 attribute/quote 拼线索，quote 截到这么长


def _fact_hint(f: Fact) -> str:
    """subject 去标点后是空串时，报出来的问题里没法带上这条 fact 的名字——用 attribute
    和 quote（截断到 SUBJECT_QUOTE_HINT_LEN 字左右）拼一条线索，让模型看出问题指的是哪条 fact。"""
    quote = f.quote.strip()
    if len(quote) > SUBJECT_QUOTE_HINT_LEN:
        quote = quote[:SUBJECT_QUOTE_HINT_LEN] + "…"
    parts = [p for p in (f.attribute.strip(), quote) if p]
    return "、".join(parts) if parts else "（没有更多线索）"


def check_card(data: dict, text: str) -> list[str]:
    try:
        card = Card.model_validate(data)
    except ValidationError as e:
        return [f"字段格式不对：{brief_errors(e)}"]
    body = cards_normalize(text)
    problems = []
    if not card.summary.strip():
        problems.append("summary 是空的，请写一句话概括这一段")
    if len(card.summary) > SUMMARY_LIMIT:
        problems.append("summary 太长了，请压到 150 字以内")
    short_quotes = [f.quote for f in card.facts if not _quote_len_ok(f.quote)]
    if short_quotes:
        problems.append("这些 quote 太短（至少 4 个字）：" + "；".join(short_quotes[:5]))
    not_verbatim = [f.quote for f in card.facts if _quote_len_ok(f.quote) and not _quote_ok(f.quote, body)]
    if not_verbatim:
        problems.append("这些 quote 不是从原文逐字复制的：" + "；".join(not_verbatim[:5]))
    bad_names = sorted({n for n in card_names(card) if not _in_text(n, body)})
    if bad_names:
        problems.append("这些名字在原文里找不到，请照原文的写法：" + "、".join(bad_names[:10]))
    # fact 的 subject 也要核对：能在原文里找到，或者是本卡自己列出的某个名字
    # （哪怕那个名字本身也没核对过——它的问题已经在上面的 bad_names 里报过一次了，不重复报）。
    names_norm = {cards_normalize(n) for n in card_names(card)} - {""}

    def subject_bad(f: Fact) -> bool:
        return not _in_text(f.subject, body) and cards_normalize(f.subject) not in names_norm

    bad_subjects = sorted({f.subject for f in card.facts if f.subject and subject_bad(f)})
    if bad_subjects:
        problems.append("这些 fact 的 subject 找不到对应的人物/地点/组织：" + "、".join(bad_subjects[:10]))
    # subject 去标点后是空串：光报「subject 是空的」模型看不出说的是哪条，带上这条 fact
    # 的 attribute/quote 当线索（见 _fact_hint）。
    blank_hints = sorted({_fact_hint(f) for f in card.facts if not f.subject and subject_bad(f)})
    if blank_hints:
        problems.append(
            "这些 fact 的 subject 是空的，请照原文补上具体的人名/地名/组织名（这条 fact 的线索："
            + "；".join(blank_hints[:10]) + "）"
        )
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

    # 受控属性表（spec 2.4）：属性对不上归「其他」，不当失败也不重试——为这种小事
    # 重试 3 次不划算；value 超长说明模型又在写流水账，这条直接丢。
    # 放在 keep_fact 过滤之后，这样被 quote / subject 刷掉的不重复计数。
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
    dropped = {
        "facts": dropped_facts,
        "names": dropped_names,
        "attrs": n_attrs,
        "long_values": len(long_values),
    }
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


def pick_error(eg: BaseExceptionGroup) -> BaseException:
    """异常组里如果同时有 FatalLLMError（欠费/key 失效）和别的异常（比如 JobCancelled
    表示已暂停），优先返回 FatalLLMError——不能让「已暂停」盖住作者需要看到的欠费/key 问题。
    没有 Fatal 就返回第一个异常。"""
    fatal = [e for e in eg.exceptions if isinstance(e, FatalLLMError)]
    return (fatal or list(eg.exceptions))[0]


def run_cards(
    book: Book, client: LLMClient, progress: Progress = _noop, only: list[str] | None = None
) -> dict:
    return asyncio.run(_run_cards(book, client, progress, only))


async def _run_cards(book: Book, client: LLMClient, progress: Progress, only: list[str] | None) -> dict:
    # 单卡重做（only 不为空）不改 cards 步骤自己的状态：先把当前状态记下来，
    # 跑完原样写回去（done 还是 done、failed 还是 failed、todo 还是 todo）。
    # 这里必须在做任何事之前读，因为 api.submit 对单卡重做不会再把状态标成 running。
    keep_status = book.step("cards")["status"] if only is not None else None
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
    counts = {"done": 0, "written": 0, "with_problems": 0, "attrs_normalized": 0, "long_values_dropped": 0}
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
            # with_problems 只算真丢了数据或 check_card 报过问题的卡。被丢的 fact 包括
            # quote/名字对不上的和超长 value（long_values 已并进 dropped["facts"]，所以会算）；
            # attrs 只是属性名归一、数据没丢，不算（否则几乎每张卡都会中）。
            dropped = record["dropped"]
            if record["problems"] or dropped["facts"] or dropped["names"]:
                counts["with_problems"] += 1
            counts["attrs_normalized"] += dropped["attrs"]
            counts["long_values_dropped"] += dropped["long_values"]
        counts["done"] += 1
        progress(counts["done"], len(todo))

    try:
        async with asyncio.TaskGroup() as tg:
            for scene in todo:
                tg.create_task(one(scene))
    except BaseExceptionGroup as eg:
        raise pick_error(eg) from None
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
        "attrs_normalized": counts["attrs_normalized"],
        "long_values_dropped": counts["long_values_dropped"],
        "failed": failed,
        "calls": client.usage.calls,
        "cost_usd": round(client.usage.cost(client.cfg), 4),
    }
    status = keep_status if only is not None else "done"
    # only 模式（单卡重做）：如果步骤本来不是 done（比如刚被暂停，summary.error 里记着
    # 「已暂停：做完 N 张，还剩 M 张」），这次单卡重做只是补一张卡，不该让这一次的统计
    # 把原来的 summary/error 盖掉——不然作者看到的是一个 failed 的步骤配一张看起来全部
    # 成功的 summary，「已暂停」这条信息就没了。status 该保留还是保留（keep_status 已经
    # 处理了），这里只是不让 summary 跟着被换掉；返回值仍然是这一次单卡重做的真实统计，
    # 调用方（比如 API 的任务结果）看到的是这一次到底做了什么。
    write_summary = None if (only is not None and keep_status != "done") else summary
    book.set_step("cards", status, write_summary, changed=counts["written"] > 0)
    return summary
