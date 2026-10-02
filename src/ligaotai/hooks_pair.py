"""伏笔配对（步骤 7 开头）：拿全书目录，让模型给每条埋下的伏笔找后文交代它的那一场。

原来按「去标点后字面相同」配 hooks_planted / hooks_resolved，10-02 实测两本斗破一条都没配上
（「萧炎三年前斗之气旋一夜消失的原因」vs「萧炎三年斗之气消失之谜」），档案里的「开放的伏笔」
几乎等于全部埋下的（全本 6898 条）。场景卡只看得到自己这一场，回收本来就很少记（埋 15 : 收 1）。
现在按意思查目录（跟时间线检查的查目录同一套做法），配出来存进 伏笔配对.json；交代那一场必须在
埋下之后（故事顺序），配到前面的不算——前 100 章那本 350 条里有 32 条配到了前面，基本是配错。
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from .book import Book, now_iso
from .fsutil import read_json, write_json
from .llm_caller import Caller
from .prompts import load_prompt

# timeline / timeline_run 在函数里才 import：timeline → skeleton → archive → 本模块，放顶上会循环引用

HOOK_BATCH = 40  # 一批问几条伏笔（前 100 章 350 条 9 批，每批输出约 2.6 万 token）


def story_order(data: dict, cards: dict) -> list[str]:
    """全书故事顺序：优先 世界与支线.json 的 global_order，没有就把各条线首尾相接。只留有卡片的场。"""
    order = [s for s in data.get("global_order") or [] if isinstance(s, str)]
    if not order:
        order = [s for t in data.get("threads") or [] if isinstance(t, dict)
                 for s in t.get("scenes") or [] if isinstance(s, str)]
    return [s for s in dict.fromkeys(order) if s in cards]


def hook_items(order: list[str], cards: dict) -> list[tuple[str, str]]:
    """按故事顺序列出全部埋下的伏笔 (场景, 原话)；同一场里重复的只留一条，空的跳过。"""
    out = []
    for s in order:
        hs = [h.strip() for h in (cards.get(s) or {}).get("hooks_planted") or [] if isinstance(h, str) and h.strip()]
        out += [(s, h) for h in dict.fromkeys(hs)]
    return out


def index_line(cards: dict, sid: str) -> str:
    """目录一行：摘要 + 这一场自己记下的「回收了什么」（卡片上的 hooks_resolved，帮模型认）。"""
    from . import timeline as tl

    res = [h.strip() for h in (cards.get(sid) or {}).get("hooks_resolved") or [] if isinstance(h, str) and h.strip()]
    return tl.index_line(cards, sid) + (f"（这场收了：{'；'.join(res)}）" if res else "")


def signature(order: list[str], cards: dict) -> str:
    """配对结果的签名：目录、伏笔、提示词任一变了就重配。"""
    system, user = load_prompt("archive_hooks")
    blob = json.dumps([[index_line(cards, s) for s in order], hook_items(order, cards),
                       system.template, user.template], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def closed_hooks(pairing: dict | None, order: list[str]) -> set[tuple[str, str]] | None:
    """配对结果里「交代了」的伏笔 (场景, 原话)：交代场要在埋下之后（故事顺序）。没有配对结果返回 None。"""
    if not isinstance(pairing, dict) or not isinstance(pairing.get("pairs"), list):
        return None
    pos = {s: i for i, s in enumerate(order)}
    out = set()
    for p in pairing["pairs"]:
        if not isinstance(p, dict) or p.get("scene") not in pos:
            continue
        if any(x in pos and pos[x] > pos[p["scene"]] for x in p.get("resolved_in") or []):
            out.add((p["scene"], p.get("hook")))
    return out


def load_fresh(book: Book, order: list[str], cards: dict) -> dict | None:
    """读 伏笔配对.json；跟当前目录 / 伏笔对不上（签名变了）就当没有。"""
    try:
        data = read_json(book.hooks_pair_path, None)
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data.get("sig") == signature(order, cards):
        return data
    return None


async def run_pairing(book: Book, caller: Caller, order: list[str], cards: dict) -> dict:
    """签名没变就沿用（占住缓存条目）；变了就查目录重配、落盘。返回配对结果（落盘的那份）。
    某一批失败：那一批的伏笔当没交代（照样列进开放的伏笔，宁可多列不错删），失败记进 caller.failed，
    结果标 failed，下次跑档案重配。"""
    from . import timeline as tl
    from .timeline_run import INDEX_MAX_CHARS, check_index, clean_index

    hooks = hook_items(order, cards)
    chunks = tl.index_chunks(order, cards, INDEX_MAX_CHARS) if hooks else []
    batches = [hooks[i:i + HOOK_BATCH] for i in range(0, len(hooks), HOOK_BATCH)]
    jobs = [(chunk, batch) for chunk in chunks for batch in batches]

    def values(chunk, batch):
        return {"index": "\n".join(index_line(cards, s) for s in chunk),
                "hooks": "\n".join(f"H-{i:02d} [{s}] {h}" for i, (s, h) in enumerate(batch, 1))}

    old = load_fresh(book, order, cards)
    if old is not None and not old.get("failed"):
        for chunk, batch in jobs:  # 没真调模型：对应的缓存条目也占住位置，别被 prune_cache 清掉
            caller.keep("archive_hooks", values(chunk, batch))
        return old

    caller.plan(len(jobs))
    failed_before = len(caller.failed)

    async def one(n: int, chunk: list[str], batch: list[tuple[str, str]]) -> dict[int, list[str]]:
        ids = {f"H-{i:02d}" for i in range(1, len(batch) + 1)}
        cset = set(chunk)
        got = await caller.call("archive_hooks", values(chunk, batch), lambda d: check_index(d, ids, cset),
                                f"hooks/{n}", clean=lambda d: clean_index(d, ids, cset))
        return {i: (got or {}).get(f"H-{i:02d}") or [] for i in range(1, len(batch) + 1)}

    # 同一段目录的各批开头一样：先问每段第一批让接口缓存住开头，其余再一起发（同时间线查目录）
    first = [n for n, (_, b) in enumerate(jobs) if b is batches[0]]
    rest = [n for n in range(len(jobs)) if n not in set(first)]
    got = dict(zip(first, await asyncio.gather(*(one(n, *jobs[n]) for n in first))))
    got |= dict(zip(rest, await asyncio.gather(*(one(n, *jobs[n]) for n in rest))))

    picks: dict[tuple[str, str], list[str]] = {}
    for n, (_, batch) in enumerate(jobs):
        for i, key in enumerate(batch, 1):
            picks.setdefault(key, []).extend(x for x in got[n][i] if x != key[0])
    # 有一批失败：照样落盘（这次的档案照它写），但标 failed，下次重配（成功的批命中缓存不花钱）
    data = {"sig": signature(order, cards), "generated": now_iso(), "failed": len(caller.failed) > failed_before,
            "pairs": [{"scene": s, "hook": h, "resolved_in": list(dict.fromkeys(picks.get((s, h), [])))}
                      for s, h in hooks]}
    write_json(book.hooks_pair_path, data)
    return data


# --- 合并同一个悬念的多种说法（配对之后，只看还开放的） ---

MERGE_MAX_CHARS = 150_000  # 一次给多少字的开放伏笔；超了按故事顺序分段，各段分别合（跨段的同一悬念合不上）


def open_items(pairing: dict | None, order: list[str], cards: dict) -> list[tuple[str, str]]:
    closed = closed_hooks(pairing, order) or set()
    return [k for k in hook_items(order, cards) if k not in closed]


def merge_signature(items: list[tuple[str, str]]) -> str:
    system, user = load_prompt("archive_hooks_merge")
    blob = json.dumps([items, system.template, user.template], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _groups(data) -> list | None:
    g = data.get("groups") if isinstance(data, dict) else None
    return g if isinstance(g, list) else None


def check_merge(data, ids: set[str]) -> list[str]:
    groups = _groups(data)
    if groups is None:
        return ['输出要是 {"groups": [[编号, 编号], ...]} 的形状']
    problems, seen = [], set()
    for g in groups:
        if not isinstance(g, list) or not all(isinstance(x, str) for x in g):
            problems.append("每一组要是编号的列表")
            continue
        bad = [x for x in g if x not in ids]
        if bad:
            problems.append("这些编号不在我给你的列表里：" + "、".join(bad[:5]))
        again = [x for x in g if x in seen]
        if again:
            problems.append("这些编号出现在不止一组里：" + "、".join(again[:5]))
        seen.update(g)
    return problems


def clean_merge(data, ids: set[str]) -> list[list[str]]:
    """只留编号对得上的；一个编号只算第一次出现的那组；不到两条的组丢掉。"""
    out, seen = [], set()
    for g in _groups(data) or []:
        if not isinstance(g, list):
            continue
        keep = [x for x in dict.fromkeys(g) if isinstance(x, str) and x in ids and x not in seen]
        seen.update(keep)
        if len(keep) >= 2:
            out.append(keep)
    return out


def same_groups(pairing: dict | None, order: list[str], cards: dict) -> dict[tuple[str, str], int] | None:
    """(场景, 原话) → 组号；合并结果跟当前开放的伏笔对不上（签名变了）就当没有。"""
    if not isinstance(pairing, dict) or pairing.get("same_sig") != merge_signature(open_items(pairing, order, cards)):
        return None
    out = {}
    for n, g in enumerate(pairing.get("same") or []):
        for k in g:
            if isinstance(k, list) and len(k) == 2:
                out[(k[0], k[1])] = n
    return out


async def run_merge(book: Book, caller: Caller, order: list[str], cards: dict, pairing: dict) -> dict:
    """把还开放的伏笔里同一个悬念的几条合成一组，结果写回 伏笔配对.json（same / same_sig）。
    签名没变就沿用；某段失败那段当不合并，标 same_failed，下次重合。"""
    items = open_items(pairing, order, cards)
    sig = merge_signature(items)
    rows = [f"K-{i:04d} [{s}] {h}" for i, (s, h) in enumerate(items, 1)]
    chunks: list[list[int]] = []
    size = MERGE_MAX_CHARS
    for i, r in enumerate(rows):
        if chunks and size + len(r) + 1 <= MERGE_MAX_CHARS:
            chunks[-1].append(i)
            size += len(r) + 1
        else:
            chunks.append([i])
            size = len(r) + 1
    chunks = [c for c in chunks if len(c) >= 2]

    if pairing.get("same_sig") == sig and not pairing.get("same_failed"):
        for c in chunks:
            caller.keep("archive_hooks_merge", {"hooks": "\n".join(rows[i] for i in c)})
        return pairing

    if chunks:
        caller.plan(len(chunks))
    failed_before = len(caller.failed)

    async def one(k: int, c: list[int]) -> list[list[str]]:
        ids = {rows[i].split(" ", 1)[0] for i in c}
        got = await caller.call("archive_hooks_merge", {"hooks": "\n".join(rows[i] for i in c)},
                                lambda d: check_merge(d, ids), f"hooks_merge/{k}", clean=lambda d: clean_merge(d, ids))
        return got or []

    groups = [g for gs in await asyncio.gather(*(one(k, c) for k, c in enumerate(chunks, 1))) for g in gs]
    data = {**pairing, "same_sig": sig, "same_failed": len(caller.failed) > failed_before,
            "same": [[list(items[int(x[2:]) - 1]) for x in g] for g in groups]}
    write_json(book.hooks_pair_path, data)
    return data
