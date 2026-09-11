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
