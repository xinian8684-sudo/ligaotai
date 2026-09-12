"""步骤 5 实体合并：把场景卡里的人名、地名、组织名，按「是不是同一个」归组，给出规范名。

1. 程序汇总所有叫法：出现在哪些场景、原文上下文；再按字面找出一些「看着像」的提示对。
2. 按类型把全部叫法（带上下文和提示）交给综合档模型，让它把指同一对象的叫法归组。
   叫法太多时分批，出现次数最多的一批放进每一批，冷门外号才能挂到主要人物身上。
3. 结果写进 实体.json。模型给的组是草稿（draft），作者确认、改名、合并、拆分后才算数（confirmed）。
   作者确认过的组重跑时原样保留，里面的叫法不会被模型挪走。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable

from .book import Book
from .cards import is_fresh, load_cards
from .fsutil import natural_key, read_json, write_json
from .llm import LLMClient
from .prompts import render
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

DRAFT, CONFIRMED, SINGLE = "draft", "confirmed", "single"

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


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
