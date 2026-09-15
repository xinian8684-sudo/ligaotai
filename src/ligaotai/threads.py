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
import re
from dataclasses import dataclass, field
from typing import Callable

from .book import FILE_LOCK, Book
from .cards import pick_error
from .fsutil import natural_key, read_json, write_json
from .jobs import JobCancelled
from .llm import FatalLLMError, LLMClient, LLMError, cache_config, cache_key
from .prompts import render
from .threads_check import (
    check_align,
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

DRAFT, CONFIRMED = "draft", "confirmed"
MISSED = "模型没分配"
PENDING = "模型建议归入已确认的线"
LOCKED_EXAMPLES = 3  # 已有的线在提示词里带几行示例
UNIT_PROPOSE = "time_unit 填一个适合本书的故事时间单位（「年」「月」「天」等），全书统一用它。"
UNIT_FIXED = "故事时间单位已经定为「{unit}」，time_unit 照填「{unit}」。"

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


def load_cache(book: Book) -> dict[str, dict]:
    """缓存坏了就当没有：大不了重新调一遍模型。形状不对的条目丢掉。"""
    try:
        data = read_json(book.threads_cache_path, {})
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        k: v
        for k, v in data.items()
        if isinstance(v, dict) and isinstance(v.get("data"), dict) and isinstance(v.get("problems"), list)
    }


def _broken(e: Exception) -> str:
    return f"检查或清理出错：{type(e).__name__}: {e}"


def _one_line(v) -> str:
    """名字 / 说明拼进提示词前压成一行，免得里面的换行被模型看成一个假的 `## ` 标题
    或者列表条目（不改存进 ThreadDraft / WorldDraft 的值，只在拼提示词的地方用）。"""
    return " ".join(str(v).split())


class Caller:
    """一次运行里所有模型调用共用：缓存、失败清单、没解决的问题、进度。"""

    def __init__(self, book: Book, client: LLMClient, progress: Progress):
        self.book = book
        self.client = client
        self.progress = progress
        self.cfg = cache_config(client, "synth")
        self.cache = load_cache(book)
        self.used: set[str] = set()
        self.failed: list[dict] = []
        self.unresolved: list[dict] = []
        self.done = 0
        self.total = 0

    def plan(self, n: int) -> None:
        """又要调 n 次：总数加上去（进度条的分母随阶段增长）。"""
        self.total += n
        self.progress(self.done, self.total)

    def _save(self) -> None:
        try:
            write_json(self.book.threads_cache_path, self.cache)
        except OSError:
            pass  # 缓存写失败不该让已经花了钱的这次调用也跟着失败

    async def call(self, prompt: str, values: dict, check, tag: str, *, score=None, clean=None, usable=None):
        """调一次综合档（先查缓存）。返回 clean(模型输出)，没给 clean 就返回模型输出；失败返回 None。

        失败有三种，都记进 failed、返回 None，由调用方兜底：
        - 这一次调用失败（LLMError）；
        - 检查 / 打分 / 清理抛了异常（本不该发生）：这条缓存删掉，免得坏结果钉死在缓存里，
          下次同样的调用会重新调模型；
        - 传了 usable（清理结果 → 这次回复能不能用）：清理之后调 usable(结果)，返回假、或者
          usable 自己抛异常，都当「这次回复没法用」——跟清理出错走同一条路：缓存删掉、记
          「模型回复没法用（重试后仍然没有可用的结果）」，下次同样的调用会重新调模型（重跑正是
          作者想要的：花钱换一次新的重试）。
        FatalLLMError（欠费、key 失效）、JobCancelled（暂停）和 BaseException 系照样往外抛。"""
        system, user = render(prompt, **values)
        key = cache_key(system, user, self.cfg)
        entry = self.cache.get(key)
        if entry is None:
            try:
                data, problems = await self.client.chat_json(
                    "synth", system, user, check, tag=f"threads/{tag}", score=score
                )
            except FatalLLMError:
                raise
            except LLMError as e:  # 这一次调用失败，由调用方决定怎么兜底
                self.failed.append({"call": tag, "error": str(e)})
            except JobCancelled:
                raise
            except Exception as e:  # 检查 / 打分抛了异常，chat_json 没返回结果，缓存里也没有这条
                self.failed.append({"call": tag, "error": _broken(e)})
            else:
                entry = self.cache[key] = {"data": data, "problems": problems}
                self._save()
        result = None
        if entry is not None:
            result = entry["data"]
            if clean is not None:
                try:
                    result = clean(entry["data"])
                except (FatalLLMError, JobCancelled):
                    raise
                except Exception as e:
                    self.failed.append({"call": tag, "error": _broken(e)})
                    self.cache.pop(key, None)
                    self._save()
                    entry = result = None
        if entry is not None and usable is not None:
            try:
                bad = not usable(result)
            except (FatalLLMError, JobCancelled):
                raise
            except Exception as e:
                self.failed.append({"call": tag, "error": _broken(e)})
                bad = True
            else:
                if bad:
                    self.failed.append({"call": tag, "error": "模型回复没法用（重试后仍然没有可用的结果）"})
            if bad:
                self.cache.pop(key, None)
                self._save()
                entry = result = None
        if entry is not None:
            self.used.add(key)
            if entry["problems"]:
                self.unresolved.append({"call": tag, "problems": list(entry["problems"])[:5]})
        self.done += 1
        self.progress(self.done, self.total)  # 暂停检查点：做完的调用都在缓存里
        return result

    def prune_cache(self) -> None:
        """跑成功了：这次没用到的缓存条目清掉，免得越积越多。"""
        if set(self.cache) - self.used:
            try:
                write_json(self.book.threads_cache_path, {k: v for k, v in self.cache.items() if k in self.used})
            except OSError:
                pass


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
    caller: Caller, free: list[Item], known: list[WorldDraft], unit: str, budget: int
) -> tuple[list[WorldDraft], list[str], str]:
    """划世界。known：已确认的世界（锁定，新块可以归进去）。返回 (全部世界, 漏掉的块, 时间单位)。
    新世界跟已有的世界（含前面几段新建的 N 键世界）同名时，检查会报、清理会归进那个世界。"""
    worlds = [WorldDraft(w.key, w.name, w.reason) for w in known]
    if not free:
        return worlds, [], unit
    line_of = {it.id: it.line for it in free}
    chunks = split_by_budget(list(line_of), {i: len(v) + 1 for i, v in line_of.items()}, budget)
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
                worlds.append(WorldDraft(f"N{sum(w.key.startswith('N') for w in worlds) + 1}", g["name"], g["reason"], g["scenes"]))
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
    *, main: str | None = None,
) -> LinesResult:
    """划支线（一个世界一次，太大就分段）。locked：这个世界里已确认的线。
    main：调用方已知的这个世界的全书主线的键（T14 组装时传旧文件里的全书主线）；不在 locked 里就忽略。"""
    res = LinesResult()
    ids = [s for s in world.scenes if items[s].kind in ORDERED_KINDS or items[s].kind == OUTLINE]
    if not ids:
        return res
    locked_keys = {t.key for t in locked}
    known_main = main if main in locked_keys else None
    chunks = split_by_budget(ids, {s: len(items[s].line) + 1 for s in ids}, budget)
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


async def stage_order(caller: Caller, t: ThreadDraft, items: dict[str, Item], unit: str) -> list[str]:
    """线内排序（一条线一次）。直接改 t 的 scenes / times / end / order_failed，返回漏掉的块。"""
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
    values = {
        "thread": f"{name}（{about}）" if about else name,
        "unit": unit or "年",
        "segments": segments_text(segs),
        "lines": "\n".join(items[s].line for s in fallback),
    }
    caller.plan(1)
    got = await caller.call(
        "threads_order",
        values,
        lambda d: check_order(d, segs, expected),
        f"order-{t.key}",
        score=lambda d: score_order(d, segs, expected),
        clean=lambda d: clean_order(d, segs, expected, fallback),
        usable=lambda r: not r["failed"],
    )
    if got is None:
        t.scenes, t.times, t.order_failed = fallback, {}, True
        t.end = {"state": "待定", "note": ""}
        return []
    t.scenes, t.times, t.end = got["scenes"], got["times"], got["end"]
    return got["missing"]


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


def thread_block(t: ThreadDraft, items: dict[str, Item], main: bool = False) -> str:
    head = f"## {t.key} {_one_line(t.name)}" + ("（主线）" if main else "")
    rows = [
        f"[{_num(_time_of(t.times, s))}] {items[s].line if s in items else s}"
        for s in t.scenes
    ]
    return "\n".join([head, *rows])


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
        caller.failed.append({"call": "align", "error": "输入太大，跳过跨线对齐"})
        return offsets, []
    members = {t.key: set(t.scenes) for t in threads}
    ids = set(members)
    caller.plan(1)
    got = await caller.call(
        "threads_align", {"unit": unit or "年", "main": main, "threads": text},
        lambda d: check_align(d, ids, main, members), "align",
        score=lambda d: score_align(d, ids, main, members),
        clean=lambda d: clean_align(d, ids, main, members),
    )
    if got is None:
        return offsets, []
    return got


async def stage_gaps(
    caller: Caller, world_key: str, world_name: str, threads: list[ThreadDraft],
    world_scenes: list[str], items: dict[str, Item], budget: int,
) -> list[dict]:
    """找缺口（一个世界一次）。world_scenes：这个世界的全部块（线里的、提纲、设定笔记）。"""
    refs = [(r, s) for s in world_scenes if s in items for r in items[s].refs]
    if not refs or not threads:
        return []
    text = "\n\n".join(thread_block(t, items) for t in threads)
    ref_text = "\n".join(f"- {r}｜{s}" for r, s in refs)
    if len(text) + len(ref_text) > budget:
        caller.failed.append({"call": f"gaps-{world_key}", "error": "输入太大，跳过找缺口"})
        return []
    ref_scenes = {s for _, s in refs}
    lines = {t.key: list(t.scenes) for t in threads}
    caller.plan(1)
    got = await caller.call(
        "threads_gaps", {"world": _one_line(world_name), "threads": text, "refs": ref_text},
        lambda d: check_gaps(d, ref_scenes, lines), f"gaps-{world_key}",
        score=lambda d: score_gaps(d, ref_scenes, lines),
        clean=lambda d: clean_gaps(d, ref_scenes, lines),
    )
    if got is None:
        return []
    return [{"world": world_key, **g} for g in got]


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
    "gaps": [],
    "unassigned": [],
    "pending": [],
}
_LIST_KEYS = ("worlds", "threads", "intersections", "gaps", "unassigned", "pending")
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
    """去掉所有 status 后的内容：只确认、不改内容时签名不变。"""

    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k != "status"}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x

    return json.dumps(strip(data), ensure_ascii=False, sort_keys=True)


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
            key = call[len("order-"):]
            if key in tmap:
                e["call"] = f"order-{tmap[key]}"


async def _run_threads(book: Book, client: LLMClient, progress: Progress) -> dict:
    prep = prepare(book)
    items = prep.items
    budget = book.settings()["threads_max_input_tokens"]
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

    caller = Caller(book, client, progress)
    try:
        known = [WorldDraft(w["id"], text(w.get("name")), text(w.get("reason"))) for w in locked_worlds]
        worlds, missing, unit = await stage_worlds(caller, free, known, unit, budget)
        wmap, next_world = assign_world_ids(old, worlds, locked=locked_world_ids)
        for w in worlds:
            w.key = wmap[w.key]
        results = await _all(
            stage_lines(caller, w, items, [t for t in locked if t.world == w.key], budget, main=old["main_thread"])
            for w in worlds
        )
        new = [t for r in results for t in r.threads]
        lost = await _all(stage_order(caller, t, items, unit) for t in new)
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
        book.add_usage("threads", u.calls, u.prompt_tokens, u.completion_tokens, u.cost(client.cfg))

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
