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


def _as_list(h) -> list | None:
    """happens_in 收列表；模型照旧答单个编号或 null 也收（统一成列表）。别的形状返回 None。"""
    if h is None:
        return []
    if isinstance(h, str):
        return [h]
    if isinstance(h, list) and all(isinstance(v, str) for v in h):
        return h
    return None


def check_refs(data, cands: dict[str, list[str]]) -> list[str]:
    items = _items(data)
    if items is None:
        return ['输出要是 {"items": [...]} 的形状']
    problems, got = _common(items, set(cands))
    for x in got:
        hs = _as_list(x.get("happens_in"))
        if hs is None:
            problems.append(f"{x['id']} 的 happens_in 要是场景编号的列表，一个都不是就填 []")
        else:
            bad = [h for h in hs if h not in cands[x["id"]]]
            if bad:
                problems.append(f"{x['id']} 的 happens_in 只能填它自己的候选（" + "、".join(cands[x["id"]])
                                + "），不能填：" + "、".join(bad[:5]))
        if not isinstance(x.get("reason"), str):
            problems.append(f"{x['id']} 的 reason 要是一句话（字符串）")
    return problems[:8]


def clean_refs(data, cands: dict[str, list[str]]) -> dict[str, dict]:
    out = {}
    for x in _items(data) or []:
        if isinstance(x, dict) and x.get("id") in cands and x["id"] not in out:
            hs = _as_list(x.get("happens_in")) or []
            out[x["id"]] = {"happens_in": [h for h in dict.fromkeys(hs) if h in cands[x["id"]]],
                            "reason": x["reason"].strip() if isinstance(x.get("reason"), str) else ""}
    for i in sorted(set(cands) - set(out)):
        out[i] = {"happens_in": [], "reason": ""}
    return out


INDEX_MAX_PICKS = 2  # 查目录时每条回指在一段目录里最多挑几场


def check_index(data, ids: set[str], chunk: set[str]) -> list[str]:
    items = _items(data)
    if items is None:
        return ['输出要是 {"items": [...]} 的形状']
    problems, got = _common(items, ids)
    for x in got:
        sc = x.get("scenes")
        if not isinstance(sc, list) or not all(isinstance(v, str) for v in sc):
            problems.append(f"{x['id']} 的 scenes 要是场景编号的列表，没有就填 []")
            continue
        if len(sc) > INDEX_MAX_PICKS:
            problems.append(f"{x['id']} 的 scenes 最多 {INDEX_MAX_PICKS} 个")
        bad = [v for v in sc if v not in chunk]
        if bad:
            problems.append(f"{x['id']} 填了目录里没有的编号：" + "、".join(bad[:5]))
    return problems[:8]


def clean_index(data, ids: set[str], chunk: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for x in _items(data) or []:
        if isinstance(x, dict) and x.get("id") in ids and x["id"] not in out:
            sc = x.get("scenes") if isinstance(x.get("scenes"), list) else []
            out[x["id"]] = [v for v in dict.fromkeys(sc) if isinstance(v, str) and v in chunk][:INDEX_MAX_PICKS]
    for i in sorted(ids - set(out)):
        out[i] = []
    return out


A_BATCH = 20  # A 类一批几条
C_BATCH = 10  # C 类一批几条（每条带 8 个候选摘要，比 A 长）
INDEX_MAX_CHARS = 400_000  # 目录一段最多几字。10-02：前 100 章目录后面掺 2700 多场干扰（30 万字）一次给全，
# 5 处 C 植入照样 5/5、没有一条挑到干扰场；原来按 300 场分段，全本斗破要 10 段 × 136 批 = 1360 次
INDEX_REF_BATCH = 40  # 查目录一次问几条回指
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


SCENE_TEXT_LIMIT = 3000  # 回指所在场的原文最多给多少字（切分上限 5000，斗破中位 1176、最长 4300）
_SENT_END = "。！？!?\n"


def ref_context(text: str, refs: list[str], limit: int = SCENE_TEXT_LIMIT) -> str:
    """回指所在场给模型看的原文：不超过 limit 就整段；太长就以跟回指原话（汉字二元组）最像的
    那句为中心截 limit 字。卡片里的回指是改写过的，定不准原文哪一句，所以不只给那一句。"""
    if len(text) <= limit:
        return text
    want = set().union(*(tl._bigrams(r) for r in refs)) if refs else set()
    best, best_score, start = 0, -1, 0
    for i, ch in enumerate(text):
        if ch in _SENT_END or i == len(text) - 1:
            score = len(want & tl._bigrams(text[start:i + 1]))
            if score > best_score:
                best, best_score = (start + i) // 2, score
            start = i + 1
    lo = max(0, min(best - limit // 2, len(text) - limit))
    return text[lo:lo + limit]


def _refs_block(book: Book, cards: dict, batch: list[dict], missing: set[str]) -> str:
    """一批回指的判断材料：按回指所在场分组，每场给一次原文（10-01：只给卡片摘要和改写过的
    回指原话，模型分不清这是将来的事、本场正在发生的事，还是往事），下面列这场的各条回指和
    它们的候选（候选照旧给摘要）。"""
    parts: list[str] = []
    cur = None
    for i, a in enumerate(batch, 1):
        if a["scene"] != cur:
            cur = a["scene"]
            refs = [x["ref"] for x in batch if x["scene"] == cur]
            parts.append(f"回指所在场 [{cur}] 原文：\n{ref_context(_safe_scene_text(book, cards, cur, missing), refs)}")
        lines = [f"C-{i:02d} 回指原话：{a['ref']}", "  候选："]
        lines += [f"    [{c}] {_summary(cards, c)}" for c in a["candidates"]]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


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
    try:
        return asyncio.run(_run(book, client, progress))
    finally:  # 10-01 前时间线检查不记用量，花了多少查不到
        u = client.usage
        book.add_usage("timeline", u.calls, u.prompt_tokens, u.completion_tokens, u.cost(client.cfg),
                       cache_hit_tokens=u.cache_hit_tokens)


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


async def _index_picks(caller: Caller, seq: list[str], cards: dict) -> dict[tuple[str, str], list[str]]:
    """先让模型拿着全书目录（每场一行摘要）给每条回指挑事情发生的场，挑中的进候选最前面。
    书长就把目录分段，每段把回指分批问一遍，各段挑的按段的先后合起来。某一批失败了，
    那一批的回指在那一段就当没挑（记进 failed），还有字面候选兜底。"""
    refs = tl.ref_items(seq, cards)
    chunks = tl.index_chunks(seq, cards, INDEX_MAX_CHARS)
    batches = [refs[i:i + INDEX_REF_BATCH] for i in range(0, len(refs), INDEX_REF_BATCH)]
    caller.plan(len(chunks) * len(batches))

    async def one(k: int, chunk: list[str], batch: list[tuple[str, str]]) -> dict[tuple[str, str], list[str]]:
        ids = {f"R-{i:02d}" for i in range(1, len(batch) + 1)}
        cset = set(chunk)
        values = {"index": "\n".join(tl.index_line(cards, s) for s in chunk),
                  "refs": "\n".join(f"R-{i:02d} [{sid}] {r}" for i, (sid, r) in enumerate(batch, 1))}
        got = await caller.call("timeline_index", values, lambda d: check_index(d, ids, cset), f"index/{k}",
                                clean=lambda d: clean_index(d, ids, cset))
        return {key: (got or {}).get(f"R-{i:02d}") or [] for i, key in enumerate(batch, 1)}

    jobs = [(chunk, batch) for chunk in chunks for batch in batches]
    # 同一段目录的各批开头一字不差（系统提示 + 目录在前）：先单独问每段的第一批，接口缓存住这段开头，
    # 其余再一起发。10-02 七批同时发，164 万输入只命中 9 万；全本 136 批每批 22 万，没命中要多花约 ¥30
    first = [n for n, (_, b) in enumerate(jobs) if b is batches[0]] if batches else []
    head = await asyncio.gather(*(one(n, *jobs[n]) for n in first))
    rest = await asyncio.gather(*(one(n, *jobs[n]) for n in range(len(jobs)) if n not in set(first)))
    by_n = dict(zip(first, head)) | dict(zip([n for n in range(len(jobs)) if n not in set(first)], rest))
    results = [by_n[n] for n in range(len(jobs))]
    picks: dict[tuple[str, str], list[str]] = {}
    for got in results:  # jobs 按段的先后排，合起来就是段序
        for key, sc in got.items():
            picks.setdefault(key, []).extend(sc)
    return picks


async def _run(book: Book, client: LLMClient, progress: Progress) -> dict:
    fp = tl.input_fingerprint(book)
    seq, pos, n_unplaced, n_untracked = tl.story_order(book)
    cards = load_cards(book)
    cmap = name_map(book)
    line_of = _line_of(book)
    deaths, capped = tl.death_suspects(seq, pos, cards, cmap)
    missing_scenes: set[str] = set()

    caller = Caller(book, client, progress, cache_path=book.timeline_cache_path, tag_prefix="timeline")
    picks = await _index_picks(caller, seq, cards)
    asks, no_cand, all_before = tl.ref_suspects(seq, pos, cards, cmap, line_of, picks=picks)
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
        text = _refs_block(book, cards, batch, missing_scenes)
        got = await caller.call("timeline_refs", {"items": text}, lambda d: check_refs(d, cands), f"refs/{k}",
                                clean=lambda d: clean_refs(d, cands))
        call_failed = got is None
        judged = got or {i: {"happens_in": [], "reason": "这一批调用失败，没拿到判断"} for i in cands}
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
        # 同一类事发生过多次（两次拍卖会、测验和复测），模型列出所有说得通的场：有一次排在回指
        # 之前，就说明「之前发生过」，不报；全在后面才报，报最早那一场（10-01 斗破 12 条误报
        # 大多是候选里本来有更早那次、单选规则逼模型挑了后面那次）
        hs = a["happens_in"]
        h = min(hs, key=lambda x: pos[x]) if hs else None
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
