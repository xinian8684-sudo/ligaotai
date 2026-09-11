"""步骤 3 查重：找出同一场景的不同版本。

正文去掉空白和标点后切成 k 字一组的字串（shingle），建倒排索引，
精确数出每两块共有多少字串，算 Jaccard 和包含度。出现在太多块里的字串是套话，不计数。
两块满足任一阈值就连起来，连通的块成一个版本组。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Callable

from .book import Book
from .fsutil import natural_key, read_json, write_json
from .scenes import load_scenes

PARAM_KEYS = (
    "dedup_shingle",
    "dedup_jaccard",
    "dedup_containment",
    "dedup_min_shingles",
    "dedup_common_df",
)
_NOISE = re.compile(r"[\W_]+")

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


def normalize(text: str) -> str:
    return _NOISE.sub("", text)


def shingles(text: str, k: int = 5) -> set[int]:
    s = normalize(text)
    if len(s) < k:
        return {hash(s)} if s else set()
    return {hash(s[i : i + k]) for i in range(len(s) - k + 1)}


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    inter: int
    jaccard: float
    containment: float
    smaller: str


def find_pairs(
    docs: dict[str, set[int]],
    jaccard_min: float,
    containment_min: float,
    min_shingles: int,
    common_df: int,
) -> list[Pair]:
    """满足 Jaccard 阈值的边照常保留。只满足包含度阈值的边，一个块只挂到它「最佳」
    的容器上（inter 最大；再打平按 Jaccard 更高的优先；还打平按容器 natural_key 靠前），
    避免一个短碎片把两个不相关的长块串成一组。"""
    eligible = sorted((d for d in docs if len(docs[d]) >= min_shingles), key=natural_key)
    postings: dict[int, list[int]] = defaultdict(list)
    for i, d in enumerate(eligible):
        for x in docs[d]:
            postings[x].append(i)
    counts: Counter = Counter()
    for plist in postings.values():
        if 2 <= len(plist) <= common_df:
            counts.update(combinations(plist, 2))

    jaccard_pairs: list[Pair] = []
    containment_only: dict[str, list[Pair]] = defaultdict(list)
    for (i, j), inter in counts.items():
        a, b = eligible[i], eligible[j]
        na, nb = len(docs[a]), len(docs[b])
        jac = inter / (na + nb - inter)
        cont = inter / min(na, nb)
        if jac < jaccard_min and cont < containment_min:
            continue
        if na != nb:
            smaller = a if na < nb else b
        else:
            smaller = min(a, b, key=natural_key)
        pair = Pair(a, b, inter, round(jac, 4), round(cont, 4), smaller)
        if jac >= jaccard_min:
            jaccard_pairs.append(pair)
        else:
            containment_only[smaller].append(pair)

    def container_of(p: Pair) -> str:
        return p.b if p.smaller == p.a else p.a

    best_containment = [
        min(plist, key=lambda p: (-p.inter, -p.jaccard, natural_key(container_of(p))))
        for plist in containment_only.values()
    ]
    pairs = jaccard_pairs + best_containment
    pairs.sort(key=lambda p: (natural_key(p.a), natural_key(p.b)))
    return pairs


def group_pairs(pairs: list[Pair]) -> list[list[str]]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        ra, rb = find(p.a), find(p.b)
        if ra != rb:
            parent[rb] = ra
    groups: dict[str, list[str]] = defaultdict(list)
    for x in list(parent):
        groups[find(x)].append(x)
    ordered = [sorted(g, key=natural_key) for g in groups.values()]
    return sorted(ordered, key=lambda g: natural_key(g[0]))


def choose_main(members: list[str], chars: dict[str, int], mtime: dict[str, float]) -> str:
    """最长的；一样长选原件修改时间最新的；还一样选编号小的（max 取第一个最大值）。"""
    return max(sorted(members, key=natural_key), key=lambda s: (chars[s], mtime.get(s, 0)))


def _signature(data: dict) -> list:
    return sorted((tuple(g["members"]), g["main"]) for g in data["groups"])


def run_dedup(book: Book, progress: Progress = _noop) -> dict:
    s = book.settings()
    scenes = [sc for sc in load_scenes(book, with_text=True) if not sc.removed]
    files = read_json(book.manifest_path, {"files": {}})["files"]
    docs: dict[str, set[int]] = {}
    for i, sc in enumerate(scenes, 1):
        docs[sc.id] = shingles(sc.text, s["dedup_shingle"])
        progress(i, len(scenes))
    pairs = find_pairs(
        docs,
        s["dedup_jaccard"],
        s["dedup_containment"],
        s["dedup_min_shingles"],
        s["dedup_common_df"],
    )
    chars = {sc.id: sc.chars for sc in scenes}
    mtime = {sc.id: files.get(sc.source, {}).get("mtime", 0) for sc in scenes}
    old = read_json(book.versions_path, {"groups": []})
    author_mains = {g["main"] for g in old["groups"] if g.get("main_by") == "author"}

    groups = []
    for n, members in enumerate(group_pairs(pairs), 1):
        picked = [m for m in members if m in author_mains]
        if len(picked) == 1:
            main, by = picked[0], "author"
        else:
            main, by = choose_main(members, chars, mtime), "auto"
        mset = set(members)
        groups.append({
            "id": f"G-{n:03d}",
            "members": members,
            "main": main,
            "main_by": by,
            "pairs": [
                {"a": p.a, "b": p.b, "jaccard": p.jaccard, "containment": p.containment}
                for p in pairs
                if p.a in mset
            ],
        })
    data = {"params": {k: s[k] for k in PARAM_KEYS}, "groups": groups}
    changed = _signature(old) != _signature(data)
    write_json(book.versions_path, data)
    summary = {
        "scenes": len(scenes),
        "pairs": len(pairs),
        "groups": len(groups),
        "scenes_in_groups": sum(len(g["members"]) for g in groups),
    }
    book.set_step("dedup", "done", summary, changed=changed)
    return summary


def set_main(book: Book, group_id: str, scene_id: str) -> dict:
    """作者手动指定主版本。"""
    data = read_json(book.versions_path, {"groups": []})
    for g in data["groups"]:
        if g["id"] != group_id:
            continue
        if scene_id not in g["members"]:
            raise ValueError(f"{scene_id} 不在 {group_id} 里")
        moved = g["main"] != scene_id
        g["main"], g["main_by"] = scene_id, "author"
        write_json(book.versions_path, data)
        if moved:
            book.mark_downstream_outdated("dedup")
        return g
    raise KeyError(group_id)
