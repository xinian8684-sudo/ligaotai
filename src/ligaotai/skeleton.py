"""成书骨架（计划④ spec 第 7 节）：程序排顺序，模型只分卷分章、起名、写空洞说明。

生成前后各算一次输入指纹（世界与支线.json、看板.json、版本组.json 的原文），
跑的途中变了就不写入（沿用步骤 6 input_changed 的做法）。重新生成前把旧骨架备份成 骨架.bak.json。
"""

from __future__ import annotations

import asyncio
import shutil

from .archive import _digest, refs_in
from .book import FILE_LOCK, Book, now_iso
from .cards import load_cards
from .chapters import assemble, check_chapters, fallback_chapters, merge_windows, render_rows, windows
from .fsutil import write_json
from .llm import LLMClient
from .llm_caller import Caller, Progress, _noop
from .scenes import load_scenes
from .skeleton_order import build_sequence, insert_holes, notes_for
from .threads_ops import load_threads
from .triage import columns, non_main_versions

PROMPT_CHAPTERS = "skeleton_chapters"
PROMPT_HOLES = "skeleton_holes"
HOLE_BATCH = 20


def scene_info(book: Book) -> dict[str, dict]:
    cards = load_cards(book)
    out = {}
    for s in load_scenes(book):
        rec = cards.get(s.id) or {}
        card = rec.get("card") if isinstance(rec.get("card"), dict) else {}
        out[s.id] = {"chars": s.chars, "summary": str(card.get("summary") or s.heading or ""), "removed": s.removed}
    return out


def input_fingerprint(book: Book) -> str:
    parts = [p.read_text(encoding="utf-8") if p.exists() else ""
             for p in (book.threads_path, book.board_path, book.versions_path)]
    return _digest(*parts)


def hole_allowed(h: dict) -> set[str]:
    return {x for x in [h.get("after"), h.get("before"), *(h.get("mentioned_in") or [])] if x}


def hole_block(h: dict, info: dict) -> str:
    def line(label, sid):
        return f"{label} {sid}：{(info.get(sid) or {}).get('summary', '')}"

    lines = [f"### {h['id']}", f"缺的事：{h.get('event', '')}"]
    if h.get("after"):
        lines.append(line("前一块", h["after"]))
    if h.get("before"):
        lines.append(line("后一块", h["before"]))
    for m in h.get("mentioned_in") or []:
        lines.append(line("提到它的场景", m))
    return "\n".join(lines)


def check_holes(data, expect: dict[str, set[str]]) -> list[str]:
    lst = data.get("holes") if isinstance(data, dict) else None
    if not isinstance(lst, list):
        return ['要输出 {"holes": [...]}']
    problems, seen = [], []
    for x in lst:
        if not isinstance(x, dict):
            problems.append("holes 里每一项都要是对象")
            continue
        hid = x.get("id")
        if hid not in expect:
            problems.append(f"没有这个空洞：{hid}")
            continue
        if hid in seen:
            problems.append(f"{hid} 重复了，每个空洞只写一次")
        seen.append(hid)
        task = str(x.get("task") or "").strip()
        refs = refs_in(task)
        if not refs:
            problems.append(f"{hid} 的说明没带场景编号")
        bad = sorted({r for r in refs if r not in expect[hid]})
        if bad:
            problems.append(f"{hid} 的说明用了不属于它的编号：" + "、".join(bad))
    missing = [h for h in expect if h not in seen]
    if missing:
        problems.append("这几个空洞没写说明：" + "、".join(missing))
    return problems


def fallback_task(h: dict) -> str:
    text = f"在 {h.get('after') or '（开头）'} 与 {h.get('before') or '（结尾）'} 之间补写：{h.get('event', '')}"
    m = h.get("mentioned_in") or []
    return text + (f"；原稿提到于 {'、'.join(m)}" if m else "")


def generate(book: Book, client: LLMClient, progress: Progress = _noop) -> dict:
    return asyncio.run(_generate(book, client, progress))


async def _generate(book: Book, client: LLMClient, progress: Progress) -> dict:
    fp0 = input_fingerprint(book)
    threads = load_threads(book)
    cols = columns(book, threads)
    info = scene_info(book)
    drop = non_main_versions(book) | {sid for sid, x in info.items() if x["removed"]}
    seq, unplaced_scenes = build_sequence(threads, cols, drop)
    items, unplaced_holes = insert_holes(seq, threads.get("gaps") or [], cols)

    caller = Caller(book, client, progress, cache_path=book.triage_cache_path, tag_prefix="skeleton")
    wins = windows(render_rows(items, info), book.settings()["skeleton_max_input_tokens"])
    holes = [it for it in items if it["type"] == "hole"] + unplaced_holes
    ask = [h for h in holes if hole_allowed(h)]
    batches = [ask[i:i + HOLE_BATCH] for i in range(0, len(ask), HOLE_BATCH)]
    caller.plan(len(wins) + len(batches))

    # 分卷分章：任何一个窗口失败，整本用兜底切法（不拼半截模型结果）
    results, ok = [], bool(items)
    for s, e in wins:
        n = e - s

        def check(d, n=n):
            return check_chapters(d, n)

        d = await caller.call(PROMPT_CHAPTERS, {"n": str(n), "rows": "\n".join(render_rows(items[s:e], info))},
                              check, f"chapters/{s}", usable=lambda d, n=n: not check_chapters(d, n))
        if d is None:
            ok = False
            break
        results.append((s, e, d))
    chapters = None
    if ok and results:
        chapters = results[0][2] if len(results) == 1 else merge_windows(results, len(items))
        if check_chapters(chapters, len(items)):
            chapters = None
    used_fallback = chapters is None and bool(items)
    if chapters is None:
        chapters = fallback_chapters(items, info)

    # 空洞说明：一批 HOLE_BATCH 个；失败的空洞用程序拼的说明
    tasks: dict[str, str] = {}
    for k, batch in enumerate(batches):
        expect = {h["id"]: hole_allowed(h) for h in batch}
        text = "\n\n".join(hole_block(h, info) for h in batch)
        d = await caller.call(PROMPT_HOLES, {"holes": text}, lambda d, ex=expect: check_holes(d, ex),
                              f"holes/{k}", usable=lambda d, ex=expect: not check_holes(d, ex))
        if d is not None:
            tasks.update({x["id"]: x["task"] for x in d["holes"]})
    for h in holes:
        h["task"] = tasks.get(h["id"]) or fallback_task(h)

    vols = assemble(items, chapters) if items else []
    for v in vols:
        for ch in v["chapters"]:
            ch["notes"] = notes_for(ch["items"], cols, threads)
    sk = {"generated": now_iso(), "by": "program", "fallback_chapters": used_fallback, "volumes": vols,
          "unplaced": {"scenes": unplaced_scenes, "holes": unplaced_holes}}

    if input_fingerprint(book) != fp0:
        return {"written": False, "input_changed": True, "failed": caller.failed}
    with FILE_LOCK:
        if book.skeleton_path.exists():
            shutil.copyfile(book.skeleton_path, book.skeleton_bak_path)
        write_json(book.skeleton_path, sk)
    return {"written": True, "input_changed": False, "volumes": len(vols),
            "chapters": sum(len(v["chapters"]) for v in vols), "holes": len(holes),
            "unplaced_scenes": len(unplaced_scenes), "fallback_chapters": used_fallback,
            "failed": caller.failed}
