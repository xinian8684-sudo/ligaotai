"""步骤 6 归线排序的输入准备：选出参与的块、每张卡压成一行、输入指纹、片段、按预算分段。

全是本地计算，不调模型。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .book import Book
from .cards import is_fresh, load_cards
from .fsutil import natural_key, read_json
from .scenes import load_scenes

ORDERED_KINDS = ("正文", "碎片")  # 进支线、参与排序
OUTLINE = "提纲"  # 挂在线上，不排序
NOTE = "设定笔记"  # 只挂在世界上
NO_CARD = "没有可用的场景卡"
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
    unassigned: list[dict]  # [{"scene", "reason"}]：主版本块但没有可用的场景卡
    all_ids: set[str]  # 全部没删除的主版本块（含没卡的）
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
    persons = [c.get("name", "") for c in card.get("characters", [])]
    if card.get("pov"):
        persons.insert(0, card["pov"])
    fields = [
        ("人物", "、".join(_canon(persons, "person", cmap))),
        ("地点", "、".join(_canon(card.get("locations", []), "location", cmap))),
        ("组织", "、".join(_canon(card.get("organizations", []), "organization", cmap))),
        ("世界线索", card.get("world_hint", "")),
        ("时间线索", "；".join(card.get("time_hints", []))),
    ]
    parts = [sid, card.get("kind", "正文"), clean_text(card.get("summary", ""))]
    parts += [f"{k}：{clean_text(v)}" for k, v in fields if clean_text(v)]
    return SEP.join(parts)


def fingerprint(items: dict[str, Item], unassigned: list[dict]) -> str:
    """喂给模型的全部内容的指纹：规范名、主版本、卡片内容一变，行就变，指纹跟着变。"""
    payload: list = [[i.id, i.source, i.index, i.kind, i.line, i.refs] for i in items.values()]
    payload.append(sorted((u["scene"] for u in unassigned), key=natural_key))
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def prepare(book: Book) -> Prepared:
    scenes = [s for s in load_scenes(book) if not s.removed]
    groups = read_json(book.versions_path, {"groups": []}).get("groups", [])
    not_main = {m for g in groups for m in g["members"] if m != g["main"]}
    records = load_cards(book)
    cmap = name_map(book)
    items: dict[str, Item] = {}
    unassigned: list[dict] = []
    all_ids: set[str] = set()
    for s in scenes:
        if s.id in not_main:
            continue
        all_ids.add(s.id)
        record = records.get(s.id)
        if not is_fresh(record, s):
            unassigned.append({"scene": s.id, "reason": NO_CARD})
            continue
        card = record["card"]
        refs = [clean_text(r) for r in card.get("refs_elsewhere", [])]
        items[s.id] = Item(s.id, s.source, s.index, card.get("kind", "正文"), card_line(s.id, card, cmap),
                           [r for r in refs if r])
    return Prepared(items, unassigned, all_ids, fingerprint(items, unassigned))
