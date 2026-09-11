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
