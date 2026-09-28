"""故事时间线冲突检查的纯函数部分（spec 2026-09-28-ligaotai-timeline-check-design.md）。

只用先后顺序，不用估出来的时间数值（数值不硬，②c 以来的结论）。不读模型、不写文件。
"""

from __future__ import annotations

import hashlib

from .book import Book
from .skeleton import scene_info
from .skeleton_order import build_sequence
from .threads_ops import load_threads
from .triage import non_main_versions, version_map


def story_order(book: Book) -> tuple[list[str], dict[str, int], int]:
    """全书故事顺序（跟骨架同一个排法，所有线都参与，不看看板）。
    返回 (排好的场景编号, 编号 -> 位置, 排不进时间轴的块数)。"""
    threads = load_threads(book)
    vmap = version_map(book)
    info = scene_info(book)
    removed = {sid for sid, x in info.items() if x["removed"]} | (non_main_versions(book) - set(vmap))
    seq, unplaced = build_sequence(threads, {}, removed, vmap)
    ids = [x["id"] for x in seq]
    return ids, {s: i for i, s in enumerate(ids)}, len(unplaced)


# 死亡词：值里出现就算死了（「亲属」这类属性说的是别人，不看）
DEATH_WORDS = ("死", "亡", "殁", "歿", "卒", "身故", "病故", "已故", "归天", "歸天", "逝",
               "阵亡", "陣亡", "斩", "斬", "枭首", "梟首", "丧命", "喪命", "殒命", "殞命",
               "去世", "坐化")
# 值里出现这些就不算（免死、被抓、只是差点死、说的是别的意思）
NOT_DEATH = ("免死", "未死", "不死", "没死", "沒死", "幾乎", "几乎", "险些", "險些", "差点", "差點",
             "被擒", "监禁", "監禁", "车囚", "車囚", "丁艱", "丁艰", "生还", "生還", "得救",
             "亡命", "视死", "視死", "死战", "死戰", "死守")
DEATH_ATTRS = ("生死", "身份", "其他", "伤病", "結局", "结局")


def is_death(attribute: str, value: str) -> bool:
    """这条 fact 说的是不是「主语死了」。只负责缩小范围：拿不准的放进来，模型后面还要判。"""
    a, v = (attribute or "").strip(), (value or "").strip()
    if a not in DEATH_ATTRS or not v:
        return False
    if any(w in v for w in NOT_DEATH):
        return False
    return any(w in v for w in DEATH_WORDS)


MAX_LATER = 5  # A 类每人最多查死后多少场（防主角被误判「已死」时嫌疑爆炸）


def _canon(name: str, cmap: dict) -> str:
    n = (name or "").strip()
    return cmap.get(("person", n), n)


def _card(cards: dict, sid: str) -> dict:
    rec = cards.get(sid) or {}
    c = rec.get("card") if isinstance(rec, dict) else None
    return c if isinstance(c, dict) else {}


def persons_of(card: dict, cmap: dict) -> set[str]:
    out = {_canon(c.get("name", ""), cmap) for c in card.get("characters") or [] if isinstance(c, dict)}
    if card.get("pov"):
        out.add(_canon(card["pov"], cmap))
    out.discard("")
    return out


def death_suspects(seq: list[str], pos: dict[str, int], cards: dict, cmap: dict) -> tuple[list[dict], int]:
    """(嫌疑列表, 因上限截掉的个数)。嫌疑 = {who, death, death_quote, later}，按 (death 位置, later 位置) 排。"""
    first: dict[str, tuple[int, str, str]] = {}  # who -> (位置, 场景, 引文)
    for sid in seq:
        for f in _card(cards, sid).get("facts") or []:
            if not isinstance(f, dict) or not is_death(f.get("attribute", ""), f.get("value", "")):
                continue
            who = _canon(f.get("subject", ""), cmap)
            if who and who not in first:
                first[who] = (pos[sid], sid, str(f.get("quote") or f.get("value") or ""))
    out, capped = [], 0
    for who, (p, dsid, quote) in sorted(first.items(), key=lambda kv: (kv[1][0], kv[0])):
        later = [s for s in seq[p + 1:] if who in persons_of(_card(cards, s), cmap)]
        capped += max(0, len(later) - MAX_LATER)
        out += [{"who": who, "death": dsid, "death_quote": quote, "later": s} for s in later[:MAX_LATER]]
    return out, capped


MAX_CANDIDATES = 8  # C 类每条回指最多给模型几个候选场景


def ref_suspects(seq: list[str], pos: dict[str, int], cards: dict, cmap: dict,
                 line_of: dict[str, str]) -> tuple[list[dict], int, int]:
    """(要问模型的回指, 没有候选的回指数, 候选全在前面、不用问的回指数)。
    要问的 = {scene, ref, candidates}。候选：跟回指所在场有共同人物的其他场景，
    按 (共同人物数 降序, 不同线排后, 跟回指场的距离, 位置) 排，取前 MAX_CANDIDATES 个。"""
    people = {s: persons_of(_card(cards, s), cmap) for s in seq}
    asks, no_cand, no_later = [], 0, 0
    for sid in seq:
        refs = [r.strip() for r in _card(cards, sid).get("refs_elsewhere") or [] if isinstance(r, str) and r.strip()]
        if not refs:
            continue
        mine = people[sid]
        scored = []
        for o in seq:
            if o == sid:
                continue
            k = len(mine & people[o])
            if k:
                scored.append((-k, line_of.get(o) != line_of.get(sid), abs(pos[o] - pos[sid]), pos[o], o))
        cands = [x[-1] for x in sorted(scored)[:MAX_CANDIDATES]]
        for r in refs:
            if not cands:
                no_cand += 1
            elif all(pos[c] < pos[sid] for c in cands):
                no_later += 1
            else:
                asks.append({"scene": sid, "ref": r, "candidates": cands})
    return asks, no_cand, no_later


def name_snippets(text: str, names: list[str], width: int = 40, limit: int = 3) -> list[str]:
    """正文里提到这个人（任一叫法）的地方，每处取前后 width 字，最多 limit 处，互不重叠。
    一处都没有（叫法没对上）就给开头 40 字，让模型至少看到这场在讲什么。"""
    hits = []
    for n in sorted({n for n in names if n}, key=len, reverse=True):
        start = 0
        while (i := text.find(n, start)) >= 0:
            hits.append((i, i + len(n)))
            start = i + len(n)
    out, last_end = [], -1
    for a, b in sorted(hits):
        if a < last_end:
            continue
        lo, hi = max(0, a - width), min(len(text), b + width)
        out.append(text[lo:hi].replace("\n", " "))
        last_end = hi
        if len(out) >= limit:
            break
    return out or [text[:40].replace("\n", " ")]


def conflict_sig(c: dict) -> str:
    key = "\x1f".join([c.get("kind") or "", c.get("who") or "", c.get("ref") or "", *(c.get("scenes") or [])])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def assemble(conflicts: list[dict], old: dict) -> dict:
    """拼出 时间冲突.json 的 conflicts / next_id / id_registry。编号按签名沿用，裁决按签名沿用。
    旧文件是作者可以手改的，坏了当空的，不崩。"""
    old = old if isinstance(old, dict) else {}
    prev = {c.get("sig"): c for c in old.get("conflicts") or [] if isinstance(c, dict)} \
        if isinstance(old.get("conflicts"), list) else {}
    registry = {e["sig"]: e["id"] for e in old.get("id_registry") or []
                if isinstance(e, dict) and isinstance(e.get("sig"), str) and isinstance(e.get("id"), str)}
    for s, c in prev.items():
        if isinstance(s, str) and isinstance(c.get("id"), str):
            registry.setdefault(s, c["id"])
    try:
        next_id = int(old.get("next_id") or 1)
    except (TypeError, ValueError):
        next_id = 1
    used = [int(v[2:]) for v in registry.values() if v[2:].isdigit()]
    if used:
        next_id = max(next_id, max(used) + 1)
    out = []
    for c in conflicts:
        sig = conflict_sig(c)
        if sig not in registry:
            registry[sig] = f"T-{next_id:03d}"
            next_id += 1
        verdict = (prev.get(sig) or {}).get("verdict")
        out.append({"id": registry[sig], **c, "sig": sig,
                    "verdict": verdict if isinstance(verdict, dict) else None})
    return {"conflicts": out, "next_id": next_id,
            "id_registry": [{"sig": s, "id": i} for s, i in sorted(registry.items(), key=lambda kv: kv[1])]}
