"""时间线检查：调模型、落盘、读、裁决（spec 第 4、5 节）。纯函数在 timeline.py。"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime

from .book import FILE_LOCK, Book, now_iso
from .cards import load_cards
from .contradictions import SCENE_REF
from .fsutil import read_json, write_json
from .llm import LLMClient
from .llm_caller import Caller, Progress, _noop
from .scenes import BrokenSceneFile, get_scene
from .threads_input import name_map
from .threads_ops import BrokenThreadsFile, load_threads
from .triage import version_map
from . import timeline as tl

log = logging.getLogger(__name__)

A_STATUSES = ("在场", "提到", "说不准", "记录不成立")


def _items(data) -> list | None:
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else None


def _common(items: list, ids: set[str]) -> tuple[list[str], list[dict]]:
    problems = []
    got = [x for x in items if isinstance(x, dict) and isinstance(x.get("id"), str)]
    if len(got) != len(items):
        problems.append("有几条格式不对（不是对象，或者 id 不是字符串），照样例重新输出")
    seen = {x["id"] for x in got}
    if ids - seen:
        problems.append("这些编号没答：" + "、".join(sorted(ids - seen)[:10]))
    if seen - ids:
        problems.append("这些编号不在我给你的列表里：" + "、".join(sorted(seen - ids)[:10]))
    return problems, [x for x in got if x["id"] in ids]


def check_death(data, ids: set[str]) -> list[str]:
    items = _items(data)
    if items is None:
        return ['输出要是 {"items": [...]} 的形状']
    problems, got = _common(items, ids)
    for x in got:
        if x.get("status") not in A_STATUSES:
            problems.append(f"{x['id']} 的 status 只能是：" + " / ".join(A_STATUSES))
        if not isinstance(x.get("reason"), str) or not SCENE_REF.search(x["reason"]):
            problems.append(f"{x['id']} 的 reason 要是一句话，里面带场景编号，写成 [S-0014] 这样")
    return problems[:8]


def clean_death(data, ids: set[str]) -> dict[str, dict]:
    out = {}
    for x in _items(data) or []:
        if isinstance(x, dict) and x.get("id") in ids and x["id"] not in out:
            out[x["id"]] = {"status": x.get("status") if x.get("status") in A_STATUSES else "说不准",
                            "reason": x["reason"].strip() if isinstance(x.get("reason"), str) else ""}
    for i in sorted(ids - set(out)):
        out[i] = {"status": "说不准", "reason": "模型没有给出判断，按宁可多报保留"}
    return out


def check_refs(data, cands: dict[str, list[str]]) -> list[str]:
    items = _items(data)
    if items is None:
        return ['输出要是 {"items": [...]} 的形状']
    problems, got = _common(items, set(cands))
    for x in got:
        h = x.get("happens_in")
        if h is not None and h not in cands[x["id"]]:
            problems.append(f"{x['id']} 的 happens_in 只能是它自己的候选之一或者 null：" + "、".join(cands[x["id"]]))
        if not isinstance(x.get("reason"), str):
            problems.append(f"{x['id']} 的 reason 要是一句话（字符串）")
    return problems[:8]


def clean_refs(data, cands: dict[str, list[str]]) -> dict[str, dict]:
    out = {}
    for x in _items(data) or []:
        if isinstance(x, dict) and x.get("id") in cands and x["id"] not in out:
            h = x.get("happens_in")
            out[x["id"]] = {"happens_in": h if h in cands[x["id"]] else None,
                            "reason": x["reason"].strip() if isinstance(x.get("reason"), str) else ""}
    for i in sorted(set(cands) - set(out)):
        out[i] = {"happens_in": None, "reason": ""}
    return out


A_BATCH = 20  # A 类一批几条
C_BATCH = 10  # C 类一批几条（每条带 8 个候选摘要，比 A 长）
SUMMARY_LIMIT = 200  # 候选摘要总长上限（summary + events），够看清场里发生了什么，别无限长


def _aliases(cmap: dict, who: str) -> list[str]:
    return [who] + [n for (t, n), c in cmap.items() if t == "person" and c == who and n != who]


def _summary(cards: dict, sid: str) -> str:
    """候选场景给模型看的摘要：summary 加上卡片的 events（这场做的事），不然候选描述太单薄，
    光凭 120 字的 summary 经常看不出这场跟回指原话是不是同一件事。"""
    card = tl._card(cards, sid)
    events = card.get("events") or []
    text = " ".join([str(card.get("summary") or "")] + [str(e) for e in events if isinstance(e, str)])
    return " ".join(text.split())[:SUMMARY_LIMIT]


def _safe_scene_text(book: Book, cards: dict, sid: str, missing: set[str]) -> str:
    """取场景原文；文件缺了、或者手改坏了（BrokenSceneFile 是 ValueError 子类），退回卡片
    摘要当摘录——这条照样问模型，不让一个坏场景文件拖垮整批、更不能拖垮别的批次。"""
    try:
        return get_scene(book, sid).text
    except (FileNotFoundError, ValueError):
        missing.add(sid)
        return str(tl._card(cards, sid).get("summary") or "")


def _group_batches(items: list[dict], key, size: int) -> list[list[dict]]:
    """同一个 key（A 类按死的人、C 类按回指所在场）的条目分到同一批，攒到 size 左右就切——
    绝不把同一组切开（除非这组自己就比 size 大）。items 里同 key 的条目本来就挨在一起
    （death_suspects / ref_suspects 都是按 key 连续产出的）。这样以后加一条新嫌疑，只会
    影响它自己所在的那一批，后面所有批次的缓存键不会跟着全部变掉（S4：不然加一条就要
    把后面所有批次重新真调一遍模型）。"""
    batches: list[list[dict]] = []
    cur: list[dict] = []
    for it in items:
        if cur and key(it) != key(cur[-1]) and len(cur) >= size:
            batches.append(cur)
            cur = []
        cur.append(it)
    if cur:
        batches.append(cur)
    return batches


def _death_text(i: int, s: dict, snippets: list[str]) -> str:
    return "\n".join([f"A-{i:02d} 人：{s['who']}",
                      f"  死亡那场 [{s['death']}]：{s['death_quote']}",
                      f"  后面那场 [{s['later']}]：" + " …… ".join(snippets)])


def _ref_text(i: int, a: dict, cards: dict) -> str:
    lines = [f"C-{i:02d} 回指所在场 [{a['scene']}]：{_summary(cards, a['scene'])}",
             f"  回指原话：{a['ref']}", "  候选："]
    lines += [f"    [{c}] {_summary(cards, c)}" for c in a["candidates"]]
    return "\n".join(lines)


def _read_old_timeline(book: Book) -> dict:
    """读上一轮的 时间冲突.json（里面可能有作者的裁决，不能直接盖掉）。读不了（坏 JSON /
    OSError）或者不是一个字典，就先备份一份再当没有——照 archive._read_contradictions
    的做法，坏文件不能假装是空的，作者手改的裁决要留个底。"""
    p = book.timeline_path
    try:
        data = read_json(p, None)
    except (OSError, ValueError):
        data = False
    if data is None:  # 本来就没有上一轮，不用备份
        return {}
    if not isinstance(data, dict):
        backup = p.with_name(f"时间冲突.损坏备份-{datetime.now():%Y%m%d-%H%M%S}.json")
        try:
            shutil.copy2(p, backup)
            log.warning("时间冲突.json 读不了，已备份到 %s，按没有上一轮处理", backup.name)
        except OSError:
            pass
        return {}
    return data


def run_timeline(book: Book, client: LLMClient, progress: Progress = _noop) -> dict:
    return asyncio.run(_run(book, client, progress))


def _line_of(book: Book) -> dict[str, str]:
    """场景 -> 所在线编号，键经过 version_map 换成当前主版本编号——线里存的可能是旧主版本
    引用（骨架换过主版本），不换的话跟 seq 里的（已换成新主版本的）编号对不上，
    ref_suspects 的「同线优先」会悄悄失效（两边 line_of.get 都是 None，永远判成不同线）。"""
    vmap = version_map(book)
    out: dict[str, str] = {}
    for t in load_threads(book).get("threads") or []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        for s in t.get("scenes") or []:
            if isinstance(s, str):
                out[vmap.get(s, s)] = t["id"]
    return out


async def _run(book: Book, client: LLMClient, progress: Progress) -> dict:
    fp = tl.input_fingerprint(book)
    seq, pos, n_unplaced, n_untracked = tl.story_order(book)
    cards = load_cards(book)
    cmap = name_map(book)
    line_of = _line_of(book)
    deaths, capped = tl.death_suspects(seq, pos, cards, cmap)
    asks, no_cand, all_before = tl.ref_suspects(seq, pos, cards, cmap, line_of)
    missing_scenes: set[str] = set()

    caller = Caller(book, client, progress, cache_path=book.timeline_cache_path, tag_prefix="timeline")
    a_batches = _group_batches(deaths, lambda s: s["who"], A_BATCH)
    c_batches = _group_batches(asks, lambda a: a["scene"], C_BATCH)
    caller.plan(len(a_batches) + len(c_batches))

    async def one_a(k: int, batch: list[dict]) -> list[dict]:
        ids = {f"A-{i:02d}" for i in range(1, len(batch) + 1)}
        texts = []
        for i, s in enumerate(batch, 1):
            later_text = _safe_scene_text(book, cards, s["later"], missing_scenes)
            snips = tl.name_snippets(later_text, _aliases(cmap, s["who"])) if later_text.strip() \
                else ["（场景原文和卡片摘要都缺失）"]
            texts.append(_death_text(i, s, snips))
        got = await caller.call("timeline_death", {"items": "\n\n".join(texts)},
                                lambda d: check_death(d, ids), f"death/{k}",
                                clean=lambda d: clean_death(d, ids))
        judged = got or {i: {"status": "说不准", "reason": "这一批调用失败，没拿到判断"} for i in ids}
        return [{**s, **judged[f"A-{i:02d}"]} for i, s in enumerate(batch, 1)]

    async def one_c(k: int, batch: list[dict]) -> list[dict]:
        cands = {f"C-{i:02d}": a["candidates"] for i, a in enumerate(batch, 1)}
        text = "\n\n".join(_ref_text(i, a, cards) for i, a in enumerate(batch, 1))
        got = await caller.call("timeline_refs", {"items": text}, lambda d: check_refs(d, cands), f"refs/{k}",
                                clean=lambda d: clean_refs(d, cands))
        call_failed = got is None
        judged = got or {i: {"happens_in": None, "reason": "这一批调用失败，没拿到判断"} for i in cands}
        return [{**a, **judged[f"C-{i:02d}"], "failed": call_failed} for i, a in enumerate(batch, 1)]

    a_res = [x for r in await asyncio.gather(*(one_a(k, b) for k, b in enumerate(a_batches))) for x in r]
    c_res = [x for r in await asyncio.gather(*(one_c(k, b) for k, b in enumerate(c_batches))) for x in r]
    if not caller.failed:
        caller.prune_cache()  # 这次每批都真跑了或命中了缓存，没用到的旧缓存条目可以清

    conflicts, dismissed = [], []
    for s in a_res:
        if s["status"] in ("提到", "记录不成立"):
            dismissed.append({"who": s["who"], "scenes": [s["death"], s["later"]], "status": s["status"]})
            continue
        later_text = _safe_scene_text(book, cards, s["later"], missing_scenes)
        later_quote = tl.name_snippets(later_text, _aliases(cmap, s["who"]), limit=1)[0] if later_text.strip() \
            else "（场景原文和卡片摘要都缺失）"
        conflicts.append({"kind": "A", "who": s["who"], "ref": None, "scenes": [s["death"], s["later"]],
                          "pos": [pos[s["death"]], pos[s["later"]]],
                          "quotes": [s["death_quote"], later_quote],
                          "reason": s["reason"], "status": s["status"]})
    for a in c_res:
        h = a["happens_in"]
        if h is not None and pos[h] > pos[a["scene"]]:
            conflicts.append({"kind": "C", "who": None, "ref": a["ref"], "scenes": [a["scene"], h],
                              "pos": [pos[a["scene"]], pos[h]], "quotes": [a["ref"], _summary(cards, h)],
                              "reason": a["reason"], "status": ""})
    conflicts.sort(key=lambda c: (c["kind"], c["pos"][0], c["pos"][1]))  # 先 A 后 C，各自按故事位置

    with FILE_LOCK:
        old = _read_old_timeline(book)
        result = {"generated": now_iso(), "fingerprint": fp, **tl.assemble(conflicts, old),
                  "dismissed": dismissed,
                  "asked_refs": [{k: a[k] for k in ("scene", "ref", "candidates", "happens_in", "failed")} for a in c_res],
                  "stats": {"placed": len(seq), "unplaced": n_unplaced, "untracked": n_untracked,
                            "a_suspects": len(deaths), "a_capped": capped,
                            "refs_asked": len(asks), "refs_no_candidate": no_cand, "refs_all_before": all_before,
                            "text_missing": len(missing_scenes)},
                  "failed": list(caller.failed)}
        write_json(book.timeline_path, result)
    return {"ok": True, "conflicts": len(result["conflicts"]), "failed": len(caller.failed)}


VERDICT_KINDS = ("author_error", "order_error", "ignore")


class BrokenTimelineFile(Exception):
    """时间冲突.json 读不了、或者形状不对（不是字典、conflicts 不是列表）：手改坏的，
    不能假装是空的，也不能直接覆盖——得让作者自己处理，接口层报 500 并指出是这个文件。"""


def load_timeline(book: Book) -> dict:
    """GET 用：结果文件 + never_run + stale（输入指纹对不上）。

    时间冲突.json 本身读不了才抛 ValueError（接口层报 500）；算指纹要用到的上游文件
    （归线结果、场景文件、实体表）读不了，不该让 GET 崩——那只影响「过期没过期」这个
    判断本身，旧结果照样返回，标 stale 并在 stale_reason 里说清是哪个文件读不了。"""
    if not book.timeline_path.exists():
        return {"conflicts": [], "never_run": True, "stale": False}
    data = read_json(book.timeline_path, {})
    if not isinstance(data, dict):
        raise ValueError("时间冲突.json 不是一个 json 对象，多半被手改坏了")
    stale, stale_reason = False, None
    try:
        stale = data.get("fingerprint") != tl.input_fingerprint(book)
    except FileNotFoundError:
        stale, stale_reason = True, "归线结果文件没了，先重跑步骤 6"
    except BrokenThreadsFile as e:
        stale, stale_reason = True, f"世界与支线.json 读不了：{e}"
    except BrokenSceneFile as e:
        stale, stale_reason = True, f"场景文件读不了：{e}"
    except json.JSONDecodeError as e:
        stale, stale_reason = True, f"实体.json 不是合法 JSON，第 {e.lineno} 行"
    result = {**data, "never_run": False, "stale": stale}
    if stale_reason:
        result["stale_reason"] = stale_reason
    return result


def set_timeline_verdict(book: Book, tid: str, kind: str | None) -> dict:
    if kind is not None and kind not in VERDICT_KINDS:
        raise ValueError("裁决只能是：" + " / ".join(VERDICT_KINDS))
    with FILE_LOCK:
        try:
            data = read_json(book.timeline_path, {})
        except (OSError, ValueError) as e:
            raise BrokenTimelineFile(str(e)) from e
        if not isinstance(data, dict):
            raise BrokenTimelineFile("时间冲突.json 不是一个 json 对象，多半被手改坏了")
        conflicts = data.get("conflicts")
        if not isinstance(conflicts, list):
            raise BrokenTimelineFile("时间冲突.json 的 conflicts 不是一个列表，多半被手改坏了")
        for c in conflicts:
            if isinstance(c, dict) and c.get("id") == tid:
                c["verdict"] = None if kind is None else {"kind": kind, "at": now_iso()}
                write_json(book.timeline_path, data)
                return c
    raise KeyError(tid)
