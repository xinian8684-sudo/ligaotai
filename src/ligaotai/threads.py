"""步骤 6 归线排序：划世界 → 划支线 → 线内排序 → 跨线对齐 → 找缺口，结果写 世界与支线.json。

- 输入由 threads_input.prepare 准备：只取主版本块，每张卡压成一行，人名地名换成规范名。
- 每次模型调用走综合档，结果按「提示词全文 + 综合档配置」缓存进 归线缓存.json：暂停、崩溃、
  重跑时输入没变的调用都不再花钱。
- 作者确认过（或动过）的线和世界原样保留，里面的块不进模型的输入；模型想往已确认的线里加块，
  放进 pending 等作者点头。
- 开跑时和跑完各算一次输入指纹，不一样（跑的途中作者改了实体、换了主版本……）就把这一步记成
  outdated，不记 done；跑的途中作者动了 世界与支线.json，这次结果不写入，也记 outdated。
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
import random
import re
from dataclasses import dataclass, field
from typing import Callable

from .book import FILE_LOCK, Book
from .cards import pick_error
from .fsutil import natural_key, read_json, write_json
from .llm import LLMClient, LLMError
from .llm_caller import Caller, _noop, load_cache
from .order_vote import agreement, consensus
from .threads_check import (
    check_align,
    check_assign,
    check_volumes,
    clean_assign,
    clean_volumes,
    score_assign,
    score_volumes,
    check_gaps,
    check_lines,
    check_order,
    check_worlds,
    clean_align,
    clean_gaps,
    clean_lines,
    clean_order,
    clean_worlds,
    parse_time,
    score_align,
    score_gaps,
    score_lines,
    score_order,
    score_worlds,
    str_list,
    text,
)
from .threads_input import NOTE, ORDERED_KINDS, OUTLINE, Item, prepare, segments, split_by_budget
from .time_anchor import anchor_times
from .interleave import (
    check_interleave, clean_interleave, mostly_there, score_interleave, sub_lines, time_base, windows,
)

DRAFT, CONFIRMED = "draft", "confirmed"
MISSED = "模型没分配"
PENDING = "模型建议归入已确认的线"
LOCKED_EXAMPLES = 3  # 已有的线在提示词里带几行示例
UNIT_PROPOSE = "time_unit 填一个适合本书的故事时间单位（「年」「月」「天」等），全书统一用它。"
UNIT_FIXED = "故事时间单位已经定为「{unit}」，time_unit 照填「{unit}」。"

Progress = Callable[..., None]


def _one_line(v) -> str:
    """名字 / 说明拼进提示词前压成一行，免得里面的换行被模型看成一个假的 `## ` 标题
    或者列表条目（不改存进 ThreadDraft / WorldDraft 的值，只在拼提示词的地方用）。"""
    return " ".join(str(v).split())


# --- 6.1 划世界 ---


@dataclass
class WorldDraft:
    key: str  # 已确认世界的 id，或者这次新建的临时键 N1、N2……
    name: str
    reason: str = ""
    scenes: list[str] = field(default_factory=list)  # 这次分给它的块


def known_worlds_text(worlds: list[WorldDraft]) -> str:
    if not worlds:
        return "已有的世界：（无）"
    return "已有的世界：\n" + "\n".join(f"- {w.key} {_one_line(w.name)}：{_one_line(w.reason)}" for w in worlds)


async def stage_worlds(
    caller: Caller, free: list[Item], known: list[WorldDraft], unit: str, budget: int,
    *, max_blocks: int | None = None,
) -> tuple[list[WorldDraft], list[str], str]:
    """划世界。known：已确认的世界（锁定，新块可以归进去）。返回 (全部世界, 漏掉的块, 时间单位)。
    新世界跟已有的世界（含前面几段新建的 N 键世界）同名时，检查会报、清理会归进那个世界。"""
    worlds = [WorldDraft(w.key, w.name, w.reason) for w in known]
    if not free:
        return worlds, [], unit
    line_of = {it.id: it.line for it in free}
    chunks = split_by_budget(list(line_of), {i: len(v) + 1 for i, v in line_of.items()}, budget, max_blocks)
    caller.plan(len(chunks))
    missing: list[str] = []
    failed = 0
    for no, chunk in enumerate(chunks, 1):
        keys = {w.key for w in worlds}
        names = {w.key: w.name for w in worlds}
        need_unit = not unit
        expected = set(chunk)
        values = {
            "unit_rule": UNIT_PROPOSE if need_unit else UNIT_FIXED.format(unit=unit),
            "known": known_worlds_text(worlds),
            "lines": "\n".join(line_of[i] for i in chunk),
        }
        got_all = await caller.call(
            "threads_worlds",
            values,
            lambda d: check_worlds(d, expected, keys, need_unit, names),
            f"worlds-{no}",
            score=lambda d: score_worlds(d, expected, keys, need_unit, names),
            clean=lambda d: clean_worlds(d, expected, keys, names),
            usable=lambda r: len(r[1]) < len(expected),  # 一块都没分进任何世界就算没法用
        )
        if got_all is None:
            failed += 1
            missing += chunk
            continue
        got, miss, got_unit = got_all
        missing += miss
        unit = unit or got_unit
        by_key = {w.key: w for w in worlds}
        for g in got:
            if g["key"] is not None:
                by_key[g["key"]].scenes += g["scenes"]
            else:
                taken = {w.key for w in worlds}  # 已确认世界的键可能被手改成 N 开头，临时键要跳过用掉的
                key = next(f"N{i}" for i in range(1, len(worlds) + 2) if f"N{i}" not in taken)
                worlds.append(WorldDraft(key, g["name"], g["reason"], g["scenes"]))
    if failed == len(chunks):
        raise LLMError(f"划世界失败：{caller.failed[-1]['error']}")
    return worlds, missing, unit


# --- 6.2 划支线 ---


@dataclass
class ThreadDraft:
    key: str  # 已确认线的 id，或者临时键 <世界键>#<n>（组装时换成正式编号）
    world: str
    name: str
    about: str = ""
    scenes: list[str] = field(default_factory=list)
    outlines: list[str] = field(default_factory=list)
    times: dict = field(default_factory=dict)
    end: dict = field(default_factory=dict)
    order_failed: bool = False
    locked: bool = False


def _examples(t: ThreadDraft, items: dict[str, Item]) -> list[str]:
    """已有的线在提示词里带的示例块：跟提示词里真列出来的一模一样，held 也要用它。"""
    return [s for s in t.scenes if s in items][:LOCKED_EXAMPLES]


def known_threads_text(threads: list[ThreadDraft], items: dict[str, Item], main: str | None = None) -> str:
    """main：这个世界已知的主线的键，那一行加「（主线）」标记。"""
    if not threads:
        return "已有的线：（无）"
    out = ["已有的线（块属于它就写它的 id）："]
    for t in threads:
        tag = "（主线）" if t.key == main else ""
        name, about = _one_line(t.name), _one_line(t.about)
        out.append(f"- {t.key} {name}{tag}：{about}" if about else f"- {t.key} {name}{tag}")
        out += [f"  {items[s].line}" for s in _examples(t, items)]
    return "\n".join(out)


@dataclass
class LinesResult:
    threads: list[ThreadDraft] = field(default_factory=list)  # 新线
    main: str | None = None  # 这个世界的主线的键（可能是已确认线的 id）
    pending: list[dict] = field(default_factory=list)
    world_outlines: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


async def stage_lines(
    caller: Caller, world: WorldDraft, items: dict[str, Item], locked: list[ThreadDraft], budget: int,
    *, main: str | None = None, max_blocks: int | None = None,
) -> LinesResult:
    """划支线（一个世界一次，太大就分段）。locked：这个世界里已确认的线。
    main：调用方已知的这个世界的全书主线的键（T14 组装时传旧文件里的全书主线）；不在 locked 里就忽略。"""
    res = LinesResult()
    ids = [s for s in world.scenes if items[s].kind in ORDERED_KINDS or items[s].kind == OUTLINE]
    if not ids:
        return res
    locked_keys = {t.key for t in locked}
    known_main = main if main in locked_keys else None
    chunks = split_by_budget(ids, {s: len(items[s].line) + 1 for s in ids}, budget, max_blocks)
    caller.plan(len(chunks))
    for no, chunk in enumerate(chunks, 1):
        ref = locked + res.threads
        known = {t.key for t in ref}
        names = {t.key: t.name for t in ref}
        held = {s: t.key for t in ref for s in _examples(t, items)}
        need_main = res.main is None
        exp_o = {s for s in chunk if items[s].kind in ORDERED_KINDS}
        exp_l = {s for s in chunk if items[s].kind == OUTLINE}
        mark = res.main if res.main is not None else known_main
        values = {
            "world": world.name,
            "locked": known_threads_text(ref, items, mark),
            "lines": "\n".join(items[s].line for s in chunk),
        }
        got = await caller.call(
            "threads_lines",
            values,
            lambda d: check_lines(d, exp_o, exp_l, known, names, held, need_main),
            f"lines-{world.key}-{no}",
            score=lambda d: score_lines(d, exp_o, exp_l, known, names, held, need_main),
            clean=lambda d: clean_lines(d, exp_o, exp_l, known, names),
            # 这段有正文/碎片却一块都没归进线就算没法用；只有提纲的段永远可用。
            usable=lambda r: not exp_o or len(r["missing"]) < len(exp_o),
        )
        if got is None:
            res.missing += sorted(exp_o, key=natural_key)
            res.world_outlines += sorted(exp_l, key=natural_key)
            continue
        res.missing += got["missing"]
        res.world_outlines += got["world_outlines"]
        by_key = {t.key: t for t in res.threads}
        for g in got["threads"]:
            if g["key"] in locked_keys:
                key = g["key"]
                res.pending += [{"scene": s, "thread": key, "reason": PENDING} for s in g["scenes"] + g["outlines"]]
            elif g["key"] in by_key:
                t = by_key[g["key"]]
                t.scenes += g["scenes"]
                t.outlines += g["outlines"]
                key = t.key
            else:
                t = ThreadDraft(f"{world.key}#{len(res.threads) + 1}", world.key, g["name"], g["about"], g["scenes"], g["outlines"])
                res.threads.append(t)
                by_key[t.key] = t
                key = t.key
            if g["main"] and res.main is None:
                res.main = key
    return res


# --- 6.3 线内排序 ---


def segments_text(segs: dict[str, list[str]]) -> str:
    if not segs:
        return "（无）"
    return "\n".join(f"- {p}：{' → '.join(ss)}（同一个文件里紧挨着）" for p, ss in segs.items())


async def stage_order(caller: Caller, t: ThreadDraft, items: dict[str, Item], unit: str, passes: int = 1) -> list[str]:
    """线内排序。直接改 t 的 scenes / times / end / order_failed，返回漏掉的块。

    passes > 1：同一条线排几遍、按多数票合并（`order_vote`）。同样的输入排几遍结果能差很多
    （9-28 实测一条 27 块的线三遍 τ 0.994 / 0.897 / 0.641），偶发的错投票能投掉。第 1 遍的
    输入跟只排一遍时一模一样（旧缓存照样命中），往后每遍把片段的列出顺序换一种（固定种子），
    既让缓存键不同，也免得几遍都被同一个列出顺序带偏。时间和结局取跟共识最像的那一遍，
    不把几遍的数混着用（各遍的时间刻度不一定一样）。全部失败才算排序失败。"""
    parts = segments(t.scenes, items)
    fallback = [s for p in parts for s in p]
    if len(fallback) <= 1:
        t.scenes = fallback
        t.times = {s: {"t": 0, "conf": "低"} for s in fallback}
        t.end = {"state": "待定", "note": ""}
        return []
    segs = {f"P-{i:03d}": p for i, p in enumerate((p for p in parts if len(p) > 1), 1)}
    expected = set(fallback)
    name, about = _one_line(t.name), _one_line(t.about)
    seed = ",".join(sorted(expected, key=natural_key))

    async def one(k: int):
        ps = list(parts)
        if k:
            random.Random(f"{k}:{seed}").shuffle(ps)
        values = {
            "thread": f"{name}（{about}）" if about else name,
            "unit": unit or "年",
            "segments": segments_text(segs),
            "lines": "\n".join(items[s].line for p in ps for s in p),
        }
        return await caller.call(
            "threads_order",
            values,
            lambda d: check_order(d, segs, expected),
            f"order-{t.key}" + (f"~{k + 1}" if k else ""),
            score=lambda d: score_order(d, segs, expected),
            clean=lambda d: clean_order(d, segs, expected, fallback),
            usable=lambda r: not r["failed"],
        )

    passes = max(1, passes)
    caller.plan(passes)
    good = [g for g in await asyncio.gather(*(one(k) for k in range(passes))) if g is not None]
    if not good:
        t.scenes, t.times, t.order_failed = fallback, {}, True
        t.end = {"state": "待定", "note": ""}
        return []
    order = consensus([g["scenes"] for g in good])
    best = max(good, key=lambda g: agreement(g["scenes"], order))  # 平局取靠前的一遍
    t.scenes, t.end = order, best["end"]
    t.times = {s: v for s, v in best["times"].items() if s in order}
    return [s for s in fallback if s not in order]


VOLUME_TARGET = 150  # 长线分卷：每卷大约几块（前 100 章验收书主线 82 块，5 遍投票排得很好）


def _sample_to_budget(ids: list[str], cost: dict[str, int], budget: int) -> list[str]:
    """总长放不下就等距抽样（从第一块开始），抽到放得下为止。"""
    total = sum(cost[i] for i in ids)
    if total <= budget or not ids:
        return ids
    step = math.ceil(total / budget)
    while True:
        picked = ids[::step]
        if sum(cost[i] for i in picked) <= budget or step >= len(ids):
            return picked
        step += 1


async def order_thread(
    caller: Caller, t: ThreadDraft, items: dict[str, Item], unit: str, passes: int = 1,
    *, max_order: int | None = None, budget: int = 600000, max_blocks: int | None = None,
) -> list[str]:
    """线内排序的入口：块数不超过 max_order 照旧一次排（stage_order）；超过就先定卷、归卷，
    再每卷各排一次（spec 2026-10-01-ligaotai-long-thread-order-design.md）。10-01 全本斗破
    主线 2891 块一次排，回复写不下，5 遍全失败。返回漏掉的块。"""
    parts = segments(t.scenes, items)
    fallback = [s for p in parts for s in p]
    if max_order is None or len(fallback) <= max_order:
        return await stage_order(caller, t, items, unit, passes)

    name, about = _one_line(t.name), _one_line(t.about)
    label = f"{name}（{about}）" if about else name
    n = math.ceil(len(fallback) / VOLUME_TARGET)
    lo, hi = max(2, n // 2), max(2, n * 2)
    cost = {s: len(items[s].line) + 1 for s in fallback}
    shown = _sample_to_budget(fallback, cost, max(budget - 2000, 1))
    caller.plan(1)
    vols = await caller.call(
        "threads_volumes",
        {"thread": label, "count": f"大约 {n} 卷（{lo} 到 {hi} 卷之间）。",
         "lines": "\n".join(items[s].line for s in shown)},
        lambda d: check_volumes(d, lo, hi), f"volumes-{t.key}",
        score=lambda d: score_volumes(d, lo, hi), clean=clean_volumes,
        usable=lambda r: len(r) >= 2,
    )
    if vols is None:
        t.scenes, t.times, t.order_failed = fallback, {}, True
        t.end = {"state": "待定", "note": ""}
        return []
    vol_ids = {v["id"] for v in vols}
    vol_text = "\n".join(f"- {v['id']} {v['title']}：{v['about']}" + (f"（状态：{v['state']}）" if v.get("state") else "")
                         for v in vols)
    batches = split_by_budget(fallback, cost, max(budget - len(vol_text) - 2000, 1), max_blocks)
    caller.plan(len(batches))

    async def assign(k: int, batch: list[str]) -> dict[str, str]:
        exp = set(batch)
        got = await caller.call(
            "threads_volume_assign",
            {"thread": label, "volumes": vol_text, "lines": "\n".join(items[s].line for s in batch)},
            lambda d: check_assign(d, exp, vol_ids), f"volassign-{t.key}-{k}",
            score=lambda d: score_assign(d, exp, vol_ids),
            clean=lambda d: clean_assign(d, exp, vol_ids),
        )
        return got or {}

    vol_of: dict[str, str] = {}
    for got in await _all(assign(k, b) for k, b in enumerate(batches, 1)):
        vol_of.update(got)
    order_of_vol = {v["id"]: i for i, v in enumerate(vols)}
    missing: list[str] = []
    for p in parts:  # 片段不拆：按片段里多数块的卷（平局取靠前的卷）；一块都没标上就算漏掉
        votes = [vol_of[s] for s in p if s in vol_of]
        if not votes:
            missing += p
            continue
        pick = min(set(votes), key=lambda v: (-votes.count(v), order_of_vol[v]))
        for s in p:
            vol_of[s] = pick

    subs = [ThreadDraft(f"{t.key}·{v['id']}", t.world, f"{name}·{v['title']}", v["about"],
                        [s for s in fallback if vol_of.get(s) == v["id"]]) for v in vols]
    subs = [sub for sub in subs if sub.scenes]
    lost = await _all(stage_order(caller, sub, items, unit, passes) for sub in subs)
    missing += [s for m in lost for s in m]

    scenes: list[str] = []
    times: dict = {}
    offset = 0.0
    for sub in subs:  # 卷内时间从卷头算起：第 k 卷整体挪到前面各卷最大时间之后
        scenes += sub.scenes
        nums = [v["t"] for v in sub.times.values() if isinstance(v, dict) and isinstance(v.get("t"), (int, float))]
        for s, v in sub.times.items():
            if isinstance(v, dict) and isinstance(v.get("t"), (int, float)):
                times[s] = {**v, "t": v["t"] + offset}
            else:
                times[s] = v
        if nums:
            offset += max(nums)
    t.scenes, t.times = scenes, times
    t.end = subs[-1].end if subs else {"state": "待定", "note": ""}
    t.order_failed = any(sub.order_failed for sub in subs)
    return missing


# --- 6.4 跨线对齐 / 6.5 找缺口 ---


def _num(t) -> str:
    """线内时间格式化成一行里的 [数字] 或 [?]。防御：已确认的线的 times 是从 世界与支线.json 读回来的
    （作者 / 旧版本写的，不一定干净）：None、bool、非 int/float/str、转 float 失败或超出范围、
    非有限数（NaN、inf）都当没有时间。"""
    if t is None or isinstance(t, bool) or not isinstance(t, (int, float, str)):
        return "?"
    try:
        f = float(t)
    except (ValueError, OverflowError, TypeError):
        return "?"
    if not math.isfinite(f):
        return "?"
    return f"{f:g}"


def _time_of(times, s: str):
    """t.times.get(s) 拿 "t" 字段；times 或者 times[s] 形状不对（不是字典）也当没有时间。"""
    v = times.get(s) if isinstance(times, dict) else None
    return v.get("t") if isinstance(v, dict) else None


def short_line(line: str) -> str:
    """一块的一行只留「编号｜类型｜摘要」，去掉人物 / 地点 / 世界线索等字段（长书对齐、找缺口放不下时用）。"""
    return "｜".join(line.split("｜")[:3])


def thread_block(t: ThreadDraft, items: dict[str, Item], main: bool = False, *, short: bool = False,
                 shown: list[str] | None = None) -> str:
    """shown：只列这些块（等距抽样后的，按线内顺序），标题里注明抽了多少。"""
    rows_of = t.scenes if shown is None else shown
    head = f"## {t.key} {_one_line(t.name)}" + ("（主线）" if main else "")
    if len(rows_of) < len(t.scenes):
        head += f"（太长，等距列出 {len(t.scenes)} 块中的 {len(rows_of)} 块）"
    rows = []
    for s in rows_of:
        line = items[s].line if s in items else s
        rows.append(f"[{_num(_time_of(t.times, s))}] {short_line(line) if short else line}")
    return "\n".join([head, *rows])


def _row_cost(t: ThreadDraft, items: dict[str, Item]) -> dict[str, int]:
    """压短后每块那一行占多少字（含时间前缀和换行），抽样按它算。"""
    return {s: len(f"[{_num(_time_of(t.times, s))}] {short_line(items[s].line) if s in items else s}") + 1
            for s in t.scenes}


def _sampled_block(t: ThreadDraft, items: dict[str, Item], main: bool, budget: int) -> str:
    """压短后整条线放得下就全列，放不下就等距抽样到放得下（标题算在预算里）。"""
    head = len(f"## {t.key} {_one_line(t.name)}（主线）（太长，等距列出 {len(t.scenes)} 块中的 {len(t.scenes)} 块）")
    shown = _sample_to_budget(list(t.scenes), _row_cost(t, items), max(budget - head - 1, 1))
    return thread_block(t, items, main, short=True, shown=shown)


async def stage_align(
    caller: Caller, threads: list[ThreadDraft], main: str | None, items: dict[str, Item], unit: str, budget: int
) -> tuple[dict[str, float | None], list[dict]]:
    offsets: dict[str, float | None] = {t.key: None for t in threads}
    if main is None or main not in offsets:
        return offsets, []
    offsets[main] = 0
    if len(threads) == 1:
        return offsets, []
    text = "\n\n".join(thread_block(t, items, t.key == main) for t in threads)
    if len(text) > budget:
        text = "\n\n".join(thread_block(t, items, t.key == main, short=True) for t in threads)
    if len(text) <= budget:
        batches = [(threads, text)]
    else:
        # 压短还放不下（10-02 全本斗破主线 2891 块 65 万字）：支线按一半预算分批，每批配一份等距抽样的主线
        main_t = next(t for t in threads if t.key == main)
        side = [t for t in threads if t.key != main]
        side_text = {t.key: thread_block(t, items, short=True) for t in side}
        groups = split_by_budget([t.key for t in side], {k: len(v) + 2 for k, v in side_text.items()}, budget // 2)
        batches = []
        for g in groups:
            g_text = "\n\n".join(side_text[k] for k in g)
            if len(g_text) > budget // 2:
                caller.failed.append({"call": "align", "error": f"支线 {'、'.join(g)} 太长，跳过跨线对齐"})
                continue
            m_text = _sampled_block(main_t, items, True, budget - len(g_text) - 2)
            batches.append(([main_t, *(t for t in side if t.key in g)], m_text + "\n\n" + g_text))
    caller.plan(len(batches))

    async def one(k: int, group: list[ThreadDraft], body: str):
        members = {t.key: set(t.scenes) for t in group}
        ids = set(members)
        return await caller.call(
            "threads_align", {"unit": unit or "年", "main": main, "threads": body},
            lambda d: check_align(d, ids, main, members), "align" if len(batches) == 1 else f"align/{k}",
            score=lambda d: score_align(d, ids, main, members),
            clean=lambda d: clean_align(d, ids, main, members),
        )

    cross: list[dict] = []
    for got in await _all(one(k, g, b) for k, (g, b) in enumerate(batches, 1)):
        if got is None:
            continue
        offs, inter = got
        offsets.update({k: v for k, v in offs.items() if k != main})
        cross += inter
    return offsets, cross


async def stage_interleave(
    caller: Caller, threads: list[ThreadDraft], main: str | None, items: dict[str, Item],
    offsets: dict[str, float | None], budget: int,
) -> list[str]:
    """全书穿插（见 interleave.py）：先按全书时间排出底稿，切成连续的窗口（每个最多
    MAX_WINDOW 块、输入不超预算），每个窗口让模型重新穿插。窗口连续，拼回去线内顺序照样保住。
    某个窗口模型给不出像样的结果，就留这个窗口的底稿顺序。只有一条线时返回 []（按时间排就是线内顺序）。"""
    lines = {t.key: list(t.scenes) for t in threads if t.scenes}
    if len(lines) <= 1:
        return []
    gtime: dict[str, float] = {}
    for t in threads:
        off = offsets.get(t.key)
        if not isinstance(off, (int, float)) or isinstance(off, bool):
            continue
        for s in t.scenes:
            v = _time_of(t.times, s)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                gtime[s] = off + v
    base = time_base(lines, gtime, main)
    cost = {s: len(items[s].line if s in items else s) + 1 for s in base}
    wins = [c for w in windows(base) for c in split_by_budget(w, cost, max(budget - 200, 1))]
    caller.plan(sum(1 for w in wins if len(sub_lines(w, lines)) > 1))

    async def one(k: int, w: list[str]) -> list[str]:
        wl = sub_lines(w, lines)
        if len(wl) <= 1:
            return w
        text = "\n\n".join(
            "\n".join([f"## {t.key} {_one_line(t.name)}" + ("（主线）" if t.key == main else ""),
                       *(items[s].line if s in items else s for s in wl[t.key])])
            for t in threads if t.key in wl
        )
        got = await caller.call(
            "threads_interleave", {"main": main or "", "threads": text},
            lambda d: check_interleave(d, wl), "interleave" if len(wins) == 1 else f"interleave/{k}",
            score=lambda d: score_interleave(d, wl),
            clean=lambda d: clean_interleave(d, wl) if mostly_there(d, wl) else None,
            usable=lambda r: r is not None,
        )
        return got or w

    parts = await _all(one(k, w) for k, w in enumerate(wins, 1))
    return [s for p in parts for s in p]


async def stage_gaps(
    caller: Caller, world_key: str, world_name: str, threads: list[ThreadDraft],
    world_scenes: list[str], items: dict[str, Item], budget: int,
) -> list[dict]:
    """找缺口（一个世界一次）。world_scenes：这个世界的全部块（线里的、提纲、设定笔记）。"""
    refs = [(r, s) for s in world_scenes if s in items for r in items[s].refs]
    if not refs or not threads:
        return []
    text = "\n\n".join(thread_block(t, items) for t in threads)
    ref_rows = [f"- {r}｜{s}" for r, s in refs]
    ref_len = len("\n".join(ref_rows))
    if len(text) + ref_len > budget:
        text = "\n\n".join(thread_block(t, items, short=True) for t in threads)
    if len(text) + ref_len <= budget:
        ref_batches = [list(range(len(refs)))]
    else:
        # 压短还放不下（10-02 全本斗破：线 65 万字 + 出处 5419 条）：线最多占四分之三预算（超了就每条线
        # 按字数比例等距抽样），剩下的给出处分批，每批都看同一份线
        if len(text) > budget * 3 // 4:
            total = sum(sum(_row_cost(t, items).values()) for t in threads) or 1
            text = "\n\n".join(
                _sampled_block(t, items, False, budget * 3 // 4 * sum(_row_cost(t, items).values()) // total)
                for t in threads)
        room = budget - len(text)
        if room <= 0:
            caller.failed.append({"call": f"gaps-{world_key}", "error": "输入太大，跳过找缺口"})
            return []
        ref_batches = split_by_budget(list(range(len(refs))), {i: len(ref_rows[i]) + 1 for i in range(len(refs))},
                                      room)
        if any(sum(len(ref_rows[i]) + 1 for i in b) > room for b in ref_batches):
            caller.failed.append({"call": f"gaps-{world_key}", "error": "输入太大，跳过找缺口"})
            return []
    lines = {t.key: list(t.scenes) for t in threads}
    caller.plan(len(ref_batches))

    async def one(k: int, idx: list[int]):
        ref_scenes = {refs[i][1] for i in idx}
        tag = f"gaps-{world_key}" if len(ref_batches) == 1 else f"gaps-{world_key}/{k}"
        return await caller.call(
            "threads_gaps", {"world": _one_line(world_name), "threads": text, "refs": "\n".join(ref_rows[i] for i in idx)},
            lambda d: check_gaps(d, ref_scenes, lines), tag,
            score=lambda d: score_gaps(d, ref_scenes, lines),
            clean=lambda d: clean_gaps(d, ref_scenes, lines),
        )

    out: list[dict] = []
    for got in await _all(one(k, b) for k, b in enumerate(ref_batches, 1)):
        out += [{"world": world_key, **g} for g in got or []]
    return out


# --- 编号、主线、旧文件 ---

EMPTY: dict = {
    "next_world": 1,
    "next_thread": 1,
    "time_unit": "",
    "main_thread": None,
    "main_by": "auto",
    "worlds": [],
    "threads": [],
    "intersections": [],
    "global_order": [],
    "gaps": [],
    "unassigned": [],
    "pending": [],
}
_LIST_KEYS = ("worlds", "threads", "intersections", "global_order", "gaps", "unassigned", "pending")
_KINDS = {"world": ("W", "worlds", "next_world"), "thread": ("L", "threads", "next_thread")}


def normalize(data) -> dict:
    """旧文件读进来：补齐缺的键、丢掉不认识的键、类型不对的值换成空结构的默认值；不是 dict 就当空的。"""
    out = copy.deepcopy(EMPTY)
    if isinstance(data, dict):
        out.update({k: copy.deepcopy(v) for k, v in data.items() if k in EMPTY})
    for k in _LIST_KEYS:
        if not isinstance(out[k], list):
            out[k] = []
    if not isinstance(out["time_unit"], str):
        out["time_unit"] = ""
    if not isinstance(out["main_thread"], str):
        out["main_thread"] = None
    if out["main_by"] != "author":
        out["main_by"] = "auto"
    return out


def content_signature(data: dict) -> str:
    """去掉所有 status、顶层 main_by 后的内容：status 和 main_by 是元信息，不算内容。
    只确认、或者只改主线是怎么定下来的（不改 main_thread 本身）时，签名不变。"""

    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k != "status"}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x

    stripped = strip(data)
    if isinstance(stripped, dict):
        stripped.pop("main_by", None)
    return json.dumps(stripped, ensure_ascii=False, sort_keys=True)


def _id_num(oid, prefix: str) -> int:
    m = re.fullmatch(rf"{prefix}-(\d+)", oid) if isinstance(oid, str) else None
    return int(m.group(1)) if m else 0


def next_number(data: dict, kind: str) -> int:
    prefix, key, field_name = _KINDS[kind]
    top = max((_id_num(x.get("id"), prefix) for x in data.get(key, []) if isinstance(x, dict)), default=0)
    n = data.get(field_name)
    if not isinstance(n, int) or isinstance(n, bool):
        n = 0
    return max(n, top + 1)


def world_id(n: int) -> str:
    return f"W-{n:02d}"


def thread_id(n: int) -> str:
    return f"L-{n:03d}"


def assign_world_ids(old: dict, worlds: list[WorldDraft], locked: set[str] | None = None) -> tuple[dict[str, str], int]:
    """临时键 N… → 正式编号；已确认世界的键本来就是正式编号。草稿世界按名字沿用旧的草稿世界编号。

    old 里的元素形状不一定干净（作者手改或旧版本写的）：不是 dict、没有字符串 id 的一律跳过；
    name 不是字符串就过 text() 当空名字，空名字不参与按名沿用。
    locked：已锁定（已确认 / 已确认线所属）的世界键集合，传了就原样保留、不当临时键判断；
    不传才退回按 "N" 前缀认临时键的老规则（作者手改文件把已确认世界的键改成 "N…" 开头时，
    不传 locked 会把这个已确认世界错当成临时键换号，导致它和它的线一起从结果里消失）。
    """
    in_use = set(locked) if locked is not None else {w.key for w in worlds if not w.key.startswith("N")}
    reuse: dict[str, str] = {}
    for w in old["worlds"]:
        if not isinstance(w, dict):
            continue
        wid = w.get("id")
        if not isinstance(wid, str) or w.get("status") == CONFIRMED or wid in in_use:
            continue
        name = text(w.get("name"))
        if name:
            reuse.setdefault(name, wid)
    # 发号起点：不能只看旧文件（next_number），还要避开这次原样保留的编号（locked / 已在用的编号），
    # 免得旧文件丢了 next_world 时，新世界的编号撞上已确认世界的编号（同一个编号出现两次、块被算两遍）。
    n = max(next_number(old, "world"), max((_id_num(k, "W") for k in in_use), default=0) + 1)
    out: dict[str, str] = {}
    for w in worlds:
        if w.key in in_use:
            out[w.key] = w.key
            continue
        wid = reuse.pop(w.name, None)
        if wid is None:
            wid, n = world_id(n), n + 1
        out[w.key] = wid
    return out, n


def assign_thread_ids(old: dict, threads: list[ThreadDraft]) -> tuple[dict[str, str], int]:
    """新线的临时键 → 正式编号。块集合跟旧的某条草稿线一样就沿用它的编号。

    old 里的元素形状不一定干净：不是 dict、没有字符串 id 的跳过；scenes 不是 list，
    或者里面有不能哈希 / 不是字符串的元素，只取字符串元素建 frozenset（不让 frozenset 抛异常）。
    """
    reuse: dict[frozenset, str] = {}
    for t in old["threads"]:
        if not isinstance(t, dict):
            continue
        tid = t.get("id")
        if not isinstance(tid, str) or t.get("status") == CONFIRMED:
            continue
        reuse.setdefault(frozenset(str_list(t.get("scenes"))), tid)
    n = next_number(old, "thread")
    out: dict[str, str] = {}
    for t in threads:
        tid = reuse.pop(frozenset(t.scenes), None)
        if tid is None:
            tid, n = thread_id(n), n + 1
        out[t.key] = tid
    return out, n


def thread_from_dict(t: dict, all_ids: set[str]) -> ThreadDraft:
    """旧文件里已确认的线 → ThreadDraft(locked=True)。块和提纲只留还是没删除的主版本的（all_ids）；
    时间过一遍 parse_time，脏值丢掉，免得下游的算术碰到脏值。"""
    scenes = [s for s in str_list(t.get("scenes")) if s in all_ids]
    outlines = [s for s in str_list(t.get("outlines")) if s in all_ids]
    times_raw = t.get("times")
    times: dict = {}
    if isinstance(times_raw, dict):
        for k, v in times_raw.items():
            if k in scenes:
                parsed = parse_time(v)
                if parsed is not None:
                    times[k] = parsed
    end = t.get("end")
    return ThreadDraft(
        key=t["id"],
        world=text(t.get("world")),
        name=text(t.get("name")),
        about=text(t.get("about")),
        scenes=scenes,
        outlines=outlines,
        times=times,
        end=dict(end) if isinstance(end, dict) else {},
        order_failed=bool(t.get("order_failed")),
        locked=True,
    )


def choose_main(
    old: dict, threads: list[ThreadDraft], world_mains: dict[str, str | None], world_order: list[str]
) -> tuple[str | None, str]:
    """作者设过（main_by == "author"）且那条线还在就留；否则在块最多的世界里（平票取靠前的世界）
    取这个世界被标 main 的线，那条线不在了就取这个世界里块最多的线。"""
    ids = {t.key for t in threads}
    if old.get("main_by") == "author" and old.get("main_thread") in ids:
        return old["main_thread"], "author"
    if not threads:
        return None, "auto"
    size = {w: sum(len(t.scenes) for t in threads if t.world == w) for w in world_order}
    best = max(world_order, key=lambda w: size[w])  # max 平票取第一个
    main = world_mains.get(best)
    if main not in ids:
        mine = [t for t in threads if t.world == best] or threads
        main = max(mine, key=lambda t: len(t.scenes)).key
    return main, "auto"


# --- 组装、run_threads ---


def run_threads(book: Book, client: LLMClient, progress: Progress = _noop) -> dict:
    return asyncio.run(_run_threads(book, client, progress))


async def _all(coros) -> list:
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(c) for c in coros]
    return [t.result() for t in tasks]


def _thread_dict(t: ThreadDraft, offset) -> dict:
    return {
        "id": t.key,
        "world": t.world,
        "name": t.name,
        "about": t.about,
        "status": CONFIRMED if t.locked else DRAFT,
        "scenes": t.scenes,
        "times": t.times,
        "outlines": t.outlines,
        "offset": offset,
        "end": {"state": t.end.get("state", "待定"), "note": t.end.get("note", ""), "last": t.scenes[-1] if t.scenes else None},
        "order_failed": t.order_failed,
    }


def _world_dicts(
    worlds: list[WorldDraft], old_worlds: dict[str, dict], locked_ids: set[str],
    items: dict[str, Item], world_outlines: dict[str, list[str]], all_ids: set[str],
) -> list[dict]:
    out = []
    for w in worlds:
        notes = [s for s in w.scenes if items[s].kind == NOTE]
        outs = world_outlines.get(w.key, [])
        if w.key in locked_ids:
            o = old_worlds[w.key]
            out.append({
                **o,
                "status": CONFIRMED,
                "notes": [s for s in str_list(o.get("notes")) if s in all_ids] + notes,
                "outlines": [s for s in str_list(o.get("outlines")) if s in all_ids] + outs,
            })
        else:
            out.append({"id": w.key, "name": w.name, "reason": w.reason, "status": DRAFT, "notes": notes, "outlines": outs})
    return out


def _world_scenes(w: dict, threads: list[ThreadDraft]) -> list[str]:
    inside = [s for t in threads if t.world == w["id"] for s in t.scenes + t.outlines]
    return inside + w["notes"] + w["outlines"]


def _remap_order_tags(entries: list[dict], tmap: dict[str, str]) -> None:
    """失败 / 没解决清单里 `order-<临时键>` 的 call：定完线编号后换成 `order-<正式编号>`，
    免得作者在结果里对不上号。排空被丢掉的线不在 tmap 里，原样留着。"""
    for e in entries:
        call = e.get("call")
        if isinstance(call, str) and call.startswith("order-"):
            key, sep, nth = call[len("order-"):].partition("~")  # 「~2」是第几遍
            key, dot, vol = key.partition("·")  # 长线分卷时卷内排序的调用名带「·V-03」
            if key in tmap:
                e["call"] = f"order-{tmap[key]}{dot}{vol}{sep}{nth}"


async def _run_threads(book: Book, client: LLMClient, progress: Progress) -> dict:
    prep = prepare(book)
    items = prep.items
    budget = book.settings()["threads_max_input_tokens"]
    max_blocks = book.settings().get("threads_max_blocks_per_call")
    snapshot = read_json(book.threads_path, None)
    old = normalize(snapshot)

    locked = [
        thread_from_dict(t, prep.all_ids)
        for t in old["threads"]
        if isinstance(t, dict) and isinstance(t.get("id"), str) and t.get("id") and t.get("status") == CONFIRMED
    ]
    old_worlds = {
        w["id"]: w for w in old["worlds"] if isinstance(w, dict) and isinstance(w.get("id"), str) and w.get("id")
    }
    locked_world_ids = {wid for wid, w in old_worlds.items() if w.get("status") == CONFIRMED} | {t.world for t in locked}
    for wid in sorted(locked_world_ids - set(old_worlds)):  # 旧文件里找不到的世界：补个占位，别把线弄丢
        old_worlds[wid] = {"id": wid, "name": wid, "reason": "", "status": CONFIRMED, "notes": [], "outlines": []}
    locked_worlds = [w for wid, w in old_worlds.items() if wid in locked_world_ids]
    held = {s for t in locked for s in t.scenes + t.outlines}
    held |= {s for w in locked_worlds for s in str_list(w.get("notes")) + str_list(w.get("outlines")) if s in prep.all_ids}
    free = [it for sid, it in items.items() if sid not in held]
    unit = old["time_unit"] if any(t.times for t in locked) else ""

    caller = Caller(book, client, progress, cache_path=book.threads_cache_path, tag_prefix="threads")
    try:
        known = [WorldDraft(w["id"], text(w.get("name")), text(w.get("reason"))) for w in locked_worlds]
        worlds, missing, unit = await stage_worlds(caller, free, known, unit, budget, max_blocks=max_blocks)
        wmap, next_world = assign_world_ids(old, worlds, locked=locked_world_ids)
        for w in worlds:
            w.key = wmap[w.key]
        results = await _all(
            stage_lines(caller, w, items, [t for t in locked if t.world == w.key], budget, main=old["main_thread"],
                        max_blocks=max_blocks)
            for w in worlds
        )
        new = [t for r in results for t in r.threads]
        passes = int(book.settings().get("threads_order_passes") or 1)
        order_max = book.settings().get("threads_order_max_blocks")
        lost = await _all(order_thread(caller, t, items, unit, passes, max_order=order_max, budget=budget,
                                       max_blocks=max_blocks) for t in new)
        missing += [s for r in results for s in r.missing] + [s for m in lost for s in m]
        world_outlines = {w.key: list(r.world_outlines) for w, r in zip(worlds, results)}
        for t in new + locked:
            if not t.scenes:  # 排空了（或者块都没了）的线丢掉，提纲挂回世界
                world_outlines.setdefault(t.world, []).extend(t.outlines)
        new = [t for t in new if t.scenes]
        tmap, next_thread = assign_thread_ids(old, new)
        _remap_order_tags(caller.failed, tmap)
        _remap_order_tags(caller.unresolved, tmap)
        for t in new:
            t.key = tmap[t.key]
        world_mains = {w.key: tmap.get(r.main, r.main) for w, r in zip(worlds, results)}
        alive = [t for t in locked if t.scenes] + new
        threads = [t for w in worlds for t in alive if t.world == w.key]
        main, main_by = choose_main(old, threads, world_mains, [w.key for w in worlds])
        offsets, intersections = await stage_align(caller, threads, main, items, unit, budget)
        offsets = anchor_times(threads, main, offsets, intersections)
        global_order = await stage_interleave(caller, threads, main, items, offsets, budget)
        world_dicts = _world_dicts(worlds, old_worlds, locked_world_ids, items, world_outlines, prep.all_ids)
        gap_lists = await _all(
            stage_gaps(caller, w["id"], w["name"], [t for t in threads if t.world == w["id"]],
                       _world_scenes(w, threads), items, budget)
            for w in world_dicts
        )
    except BaseExceptionGroup as eg:
        raise pick_error(eg) from None  # 欠费 / key 失效要让作者看到，不能被「已暂停」盖住
    finally:
        u = client.usage
        book.add_usage("threads", u.calls, u.prompt_tokens, u.completion_tokens, u.cost(client.cfg),
                       cache_hit_tokens=u.cache_hit_tokens)

    no_card = [u for u in prep.unassigned if u["scene"] not in held]
    unassigned = no_card + [{"scene": s, "reason": MISSED} for s in dict.fromkeys(missing)]
    unassigned.sort(key=lambda u: natural_key(u["scene"]))
    pending = [p for r in results for p in r.pending]
    thread_dicts = [_thread_dict(t, offsets.get(t.key)) for t in threads]
    gaps = [{"id": f"Q-{i:03d}", **g} for i, g in enumerate((g for gs in gap_lists for g in gs), 1)]
    data = {
        "next_world": next_world,
        "next_thread": next_thread,
        "time_unit": unit or "年",
        "main_thread": main,
        "main_by": main_by,
        "worlds": world_dicts,
        "threads": thread_dicts,
        "intersections": intersections,
        "global_order": global_order,
        "gaps": gaps,
        "unassigned": unassigned,
        "pending": pending,
    }

    fp_end = prepare(book).fingerprint
    # 只把「重新读文件 → 比对 → 写回」放进锁里，都是毫秒级的本地操作；调模型在上面，绝不能进锁。
    with FILE_LOCK:
        not_written = read_json(book.threads_path, None) != snapshot
        changed = not not_written and content_signature(old) != content_signature(data)
        if not not_written:
            write_json(book.threads_path, data)
    if not not_written:
        caller.prune_cache()
    input_changed = fp_end != prep.fingerprint
    summary = {
        "worlds": len(world_dicts),
        "threads": len(thread_dicts),
        "confirmed_threads": sum(t["status"] == CONFIRMED for t in thread_dicts),
        "scenes": len(items),
        "unassigned": len(unassigned),
        "pending": len(pending),
        "gaps": len(gaps),
        "order_failed": [t["id"] for t in thread_dicts if t["order_failed"]],
        "failed_calls": caller.failed,
        "unresolved": caller.unresolved,
        "input_changed": input_changed,
        "not_written": not_written,
        "calls": client.usage.calls,
        "cost_usd": round(client.usage.cost(client.cfg), 4),
    }
    status = "outdated" if (input_changed or not_written) else "done"
    book.set_step("threads", status, summary, changed=changed)
    return summary
