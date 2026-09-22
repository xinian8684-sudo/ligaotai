"""二期：取舍看板的 AI 建议（计划④ spec 第 6.2 节）。所有线一次调用，结果写 取舍/建议.json。"""

from __future__ import annotations

import asyncio

from .archive import input_sig, refs_in
from .book import Book, now_iso
from .fsutil import read_json, write_json
from .llm import LLMClient
from .llm_caller import Caller, Progress, _noop
from .threads_ops import load_threads
from .triage import thread_ids, thread_stats

PROMPT = "triage_advice"
ADVICE = ("keep", "merge", "cut", "flashback")
SUMMARY_MAX = 1500
MAP_MAX = 6000


def _summary(book: Book, t: dict) -> str:
    """档案开头到「## 主要人物」之前（一句话 + 来龙去脉）；没有档案就用线的 about。"""
    p = book.thread_archive_dir / f"{t['id']}.md"
    if p.exists():
        text = p.read_text(encoding="utf-8")
        cut = text.find("## 主要人物")
        return (text if cut < 0 else text[:cut]).strip()[:SUMMARY_MAX]
    return str(t.get("about") or "（没有概述）")


def advice_input(book: Book, threads: dict) -> tuple[dict, list[str], set[str]]:
    stats = thread_stats(book, threads)
    blocks, allowed = [], set()
    for t in threads.get("threads") or []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        s = stats[t["id"]]
        scenes = [x for x in t.get("scenes") or [] if isinstance(x, str)]
        allowed.update(scenes)
        head = (f"## {t['id']} {s['name']}（{'主线；' if s['is_main'] else ''}{s['scenes']} 块；"
                f"约 {s['words']} 字；{s['state']}）")
        blocks.append(f"{head}\n{_summary(book, t)}\n场景：{'、'.join(scenes)}")
    map_text = book.map_path.read_text(encoding="utf-8")[:MAP_MAX] if book.map_path.exists() else "（还没有全书地图）"
    return {"map": map_text, "threads": "\n\n".join(blocks)}, thread_ids(threads), allowed


def check_advice(data, tids: list[str], allowed: set[str]) -> list[str]:
    items = data.get("advice") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return ["要输出 {\"advice\": [...]}"]
    problems, seen = [], []
    for it in items:
        if not isinstance(it, dict):
            problems.append("advice 里每一项都要是对象")
            continue
        tid = it.get("thread")
        if tid in seen:
            problems.append(f"{tid} 重复出现了，每条线只给一次")
        seen.append(tid)
        if tid not in tids:
            problems.append(f"没有这条线：{tid}")
        a = it.get("advice")
        if a not in ADVICE:
            problems.append(f"{tid} 的 advice 只能是 {' / '.join(ADVICE)}，不能是 {a}")
        if a == "merge" and (it.get("merge_into") not in tids or it.get("merge_into") == tid):
            problems.append(f"{tid} 建议合并，merge_into 要填另一条存在的线的编号")
        refs = refs_in(str(it.get("reason") or ""))
        if not refs:
            problems.append(f"{tid} 的理由没带场景编号")
        bad = sorted({r for r in refs if r not in allowed})
        if bad:
            problems.append(f"{tid} 的理由用了不存在的编号：" + "、".join(bad))
    missing = [t for t in tids if t not in seen]
    if missing:
        problems.append("这几条线没给建议：" + "、".join(missing))
    return problems


def _sig(values: dict) -> str:
    return input_sig(values["map"] + "\n\x1f\n" + values["threads"], PROMPT)


def advice_status(book: Book, threads: dict) -> dict | None:
    """已有建议 + 是否过期（输入变了）。没有建议返回 None。"""
    try:
        saved = read_json(book.advice_path)
    except ValueError:
        saved = None
    if not isinstance(saved, dict) or not isinstance(saved.get("items"), list):
        return None
    values, _, _ = advice_input(book, threads)
    return {**saved, "stale": saved.get("sig") != _sig(values)}


def run_advice(book: Book, client: LLMClient, progress: Progress = _noop) -> dict:
    return asyncio.run(_run_advice(book, client, progress))


async def _run_advice(book: Book, client: LLMClient, progress: Progress) -> dict:
    threads = load_threads(book)
    values, tids, allowed = advice_input(book, threads)
    caller = Caller(book, client, progress, cache_path=book.triage_cache_path, tag_prefix="triage")
    caller.plan(1)

    def check(d):
        return check_advice(d, tids, allowed)

    # chat_json 重试用尽时返回「最好的一次」而不是报错，Caller 还会把它存进缓存——不传 usable 的话，
    # 一次不合规的结果会钉死在缓存里，以后每次重跑都命中它、永远不再重试。usable 返回假时
    # Caller 会删掉这条缓存、记进 failed、返回 None。
    data = await caller.call(PROMPT, values, check, "advice", usable=lambda d: not check(d))
    if data is None:
        return {"ok": False, "failed": caller.failed}
    write_json(book.advice_path, {"generated": now_iso(), "sig": _sig(values), "items": data["advice"]})
    return {"ok": True, "count": len(data["advice"])}
