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

from dataclasses import dataclass, field
from typing import Callable

from .book import Book
from .fsutil import natural_key, read_json, write_json
from .jobs import JobCancelled
from .llm import FatalLLMError, LLMClient, LLMError, cache_config, cache_key
from .prompts import render
from .threads_check import check_lines, check_worlds, clean_lines, clean_worlds, score_lines, score_worlds
from .threads_input import ORDERED_KINDS, OUTLINE, Item, split_by_budget

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

    async def call(self, prompt: str, values: dict, check, tag: str, *, score=None, clean=None):
        """调一次综合档（先查缓存）。返回 clean(模型输出)，没给 clean 就返回模型输出；失败返回 None。

        失败有两种，都记进 failed、返回 None，由调用方兜底：
        - 这一次调用失败（LLMError）；
        - 检查 / 打分 / 清理抛了异常（本不该发生）：这条缓存删掉，免得坏结果钉死在缓存里，
          下次同样的调用会重新调模型。
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
    return "已有的世界：\n" + "\n".join(f"- {w.key} {w.name}：{w.reason}" for w in worlds)


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
        out.append(f"- {t.key} {t.name}{tag}：{t.about}" if t.about else f"- {t.key} {t.name}{tag}")
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
