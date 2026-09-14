"""步骤 6 归线排序的输入准备：选出参与的块、每张卡压成一行、输入指纹、片段、按预算分段。

全是本地计算，不调模型。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .book import Book
from .cards import is_fresh, load_cards
from .entities import PRONOUNS
from .fsutil import natural_key, read_json
from .scenes import load_scenes

ORDERED_KINDS = ("正文", "碎片")  # 进支线、参与排序
OUTLINE = "提纲"  # 挂在线上，不排序
NOTE = "设定笔记"  # 只挂在世界上
NO_CARD = "没有可用的场景卡"
MAIN_REMOVED = "版本组的主版本已删除，要重跑查重"
NO_SUMMARY = "（无摘要）"
SEP = "｜"


@dataclass
class Item:
    id: str
    source: str
    index: int
    kind: str
    line: str
    refs: list[str] = field(default_factory=list)


@dataclass
class Prepared:
    items: dict[str, Item]  # 有新鲜场景卡的主版本块，按编号顺序
    unassigned: list[dict]  # [{"scene", "reason"}]：没有可用的场景卡（NO_CARD）；版本组的主版本已删除（MAIN_REMOVED）
    all_ids: set[str]  # 全部没删除的主版本块（含没卡的）+ 主版本已删除的版本组成员；= items 的编号 ∪ unassigned 的编号
    fingerprint: str


def name_map(book: Book) -> dict[tuple[str, str], str]:
    """（类型, 叫法）→ 规范名。还没有 实体.json 时是空的。"""
    data = read_json(book.entities_path, {"entities": []})
    return {(e["type"], n): e["canonical"] for e in data.get("entities", []) for n in e.get("names", [])}


def clean_text(s) -> str:
    return " ".join(str(s).replace(SEP, "/").split())


def _canon(names, typ: str, cmap: dict) -> list[str]:
    out: list[str] = []
    for n in names:
        c = cmap.get((typ, n), n)
        if c and c not in out:
            out.append(c)
    return out


def card_line(sid: str, card: dict, cmap: dict) -> str:
    """一张卡压成一行。人物栏去掉代词（「我」「他」……，跟实体合并一样）：不同文件里的「我」不是同一个人。
    摘要是空的写「（无摘要）」。"""
    persons = [c.get("name", "") for c in card.get("characters", [])]
    if card.get("pov"):
        persons.insert(0, card["pov"])
    persons = [p for p in persons if p.strip() not in PRONOUNS]
    fields = [
        ("人物", "、".join(_canon(persons, "person", cmap))),
        ("地点", "、".join(_canon(card.get("locations", []), "location", cmap))),
        ("组织", "、".join(_canon(card.get("organizations", []), "organization", cmap))),
        ("世界线索", card.get("world_hint", "")),
        ("时间线索", "；".join(card.get("time_hints", []))),
    ]
    parts = [sid, card.get("kind", "正文"), clean_text(card.get("summary", "")) or NO_SUMMARY]
    parts += [f"{k}：{clean_text(v)}" for k, v in fields if clean_text(v)]
    return SEP.join(parts)


def fingerprint(items: dict[str, Item], unassigned: list[dict]) -> str:
    """喂给模型的全部内容的指纹：规范名、主版本、卡片内容一变，行就变，指纹跟着变。"""
    payload: list = [[i.id, i.source, i.index, i.kind, i.line, i.refs] for i in items.values()]
    payload.append(sorted((u["scene"] for u in unassigned), key=natural_key))
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def prepare(book: Book) -> Prepared:
    """选块：不在任何版本组里的块 + 每组的主版本，删除的跳过。

    版本组的主版本已经删除（或者不在场景里了）、查重还没重跑时，这组其余的块没有主版本可认，
    不能静默丢掉，也不能自作主张挑一个当主版本：放进 unassigned，原因 MAIN_REMOVED，作者重跑查重就好。
    （正常走接口碰不到：切场景后查重会被标 outdated，步骤 6 被挡住；直接调 run_threads / prepare 时才会有。）"""
    scenes = [s for s in load_scenes(book) if not s.removed]
    live = {s.id for s in scenes}
    groups = read_json(book.versions_path, {"groups": []}).get("groups", [])
    not_main: set[str] = set()
    orphans: set[str] = set()
    for g in groups:
        rest = {m for m in g["members"] if m != g["main"]}
        if g["main"] in live:
            not_main |= rest
        else:
            orphans |= rest
    records = load_cards(book)
    cmap = name_map(book)
    items: dict[str, Item] = {}
    unassigned: list[dict] = []
    all_ids: set[str] = set()
    for s in scenes:
        if s.id in not_main:
            continue
        all_ids.add(s.id)
        if s.id in orphans:
            unassigned.append({"scene": s.id, "reason": MAIN_REMOVED})
            continue
        record = records.get(s.id)
        if not is_fresh(record, s):
            unassigned.append({"scene": s.id, "reason": NO_CARD})
            continue
        card = record["card"]
        refs = [clean_text(r) for r in card.get("refs_elsewhere", [])]
        items[s.id] = Item(s.id, s.source, s.index, card.get("kind", "正文"), card_line(s.id, card, cmap),
                           [r for r in refs if r])
    return Prepared(items, unassigned, all_ids, fingerprint(items, unassigned))


def segments(ids: list[str], items: dict[str, Item]) -> list[list[str]]:
    """把一条线里的正文 / 碎片块按「源文件 + 文件内位置」排好，同一文件里位置紧挨着的连成片段。
    只有一块的也当一个片段返回。

    调用方负责：
    - ids 必须都在 items 里，不在就抛 KeyError；
    - 不是正文 / 碎片的块会被静默跳过，既不在结果里、也不报漏。线里混了提纲时，不能拿结果直接覆盖 scenes。
    排序键先按自然顺序、再按文件名原文：「a01.txt」「a1.txt」自然顺序一样，也不会交错。"""
    ordered = sorted(
        (items[i] for i in ids if items[i].kind in ORDERED_KINDS),
        key=lambda it: (natural_key(it.source), it.source, it.index),
    )
    out: list[list[str]] = []
    prev: Item | None = None
    for it in ordered:
        if prev is not None and it.source == prev.source and it.index == prev.index + 1:
            out[-1].append(it.id)
        else:
            out.append([it.id])
        prev = it
    return out


def split_by_budget(ids: list[str], cost: dict[str, int], budget: int) -> list[list[str]]:
    """按顺序切成几段，每段的 cost 之和不超过 budget；单个就超过 budget 的自成一段。"""
    chunks: list[list[str]] = []
    total = 0
    for i in ids:
        c = cost[i]
        if chunks and total + c <= budget:
            chunks[-1].append(i)
            total += c
        else:
            chunks.append([i])
            total = c
    return chunks
