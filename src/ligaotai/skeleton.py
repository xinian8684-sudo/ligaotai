"""成书骨架（计划④ spec 第 7 节）：程序排顺序，模型只分卷分章、起名、写空洞说明。

生成前后各算一次输入指纹（世界与支线.json、看板.json、版本组.json 的原文），
跑的途中变了就不写入（沿用步骤 6 input_changed 的做法）。重新生成前把旧骨架备份成 骨架.bak.json。
"""

from __future__ import annotations

import asyncio
import copy
import shutil

from .archive import _digest, refs_in
from .book import FILE_LOCK, Book, now_iso
from .cards import load_cards
from .chapters import assemble, check_chapters, fallback_chapters, merge_windows, one_line, render_rows, windows
from .fsutil import natural_key, read_json, write_json
from .llm import LLMClient
from .llm_caller import Caller, Progress, _noop
from .scenes import load_scenes
from .skeleton_order import build_sequence, insert_holes, notes_for
from .threads_ops import load_threads
from .triage import columns, non_main_versions, version_map

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


def hole_key(h: dict) -> str:
    """发给模型、也用来分批的稳定标识：缺口自己的编号（Q-xxx），不是 H-xxx。
    H-xxx 是按最终排好的位置临时编的，前面插一个缺口，后面所有空洞的 H 号都会跟着挪，
    要是拿它来分批、当发给模型的标识，插一个缺口就会让后面所有批次的请求文本全变、
    缓存全部失效重付一次钱（S4）。缺口没有自己的编号（理论上不该发生）才退回用 H-xxx。"""
    gap = h.get("gap")
    return gap if isinstance(gap, str) and gap else str(h["id"])


def hole_block(h: dict, info: dict) -> str:
    def line(label, sid):
        return f"{label} {sid}：{(info.get(sid) or {}).get('summary', '')}"

    lines = [f"### {hole_key(h)}", f"缺的事：{h.get('event', '')}"]
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
        if not isinstance(hid, str) or hid not in expect:
            problems.append(f"没有这个空洞：{hid}")
            continue
        if hid in seen:
            problems.append(f"{hid} 重复了，每个空洞只写一次")
        seen.append(hid)
        # M2：task 不是字符串（模型偶尔会把它回成列表/对象）时旧代码只用 str(task) 走一遍
        # 核对就放过，原始的非字符串值照样写进骨架，作者后面存不进去（validate_skeleton
        # 会拒）。这里当场报问题，让 llm.chat_json 的重试机制重新问一次模型。
        raw_task = x.get("task")
        if not isinstance(raw_task, str) or not raw_task.strip():
            problems.append(f"{hid} 的说明必须是非空文字")
            continue
        refs = refs_in(raw_task)
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
    vmap = version_map(book)
    # M3：非主版本不能整个丢——线里原来引用的是换主版本之前的那个块，得替换成组里现在的
    # 主版本（位置、时间沿用原来那个引用），不然换过主版本的组会整组从书里消失。主版本字段
    # 坏了、分不清该留哪个的组，version_map 不给替换目标，那些成员照旧当移除处理。
    removed = {sid for sid, x in info.items() if x["removed"]} | (non_main_versions(book) - set(vmap))
    seq, unplaced_scenes = build_sequence(threads, cols, removed, vmap)
    items, unplaced_holes = insert_holes(seq, threads.get("gaps") or [], cols)

    caller = Caller(book, client, progress, cache_path=book.triage_cache_path, tag_prefix="skeleton")
    wins = windows(render_rows(items, info), book.settings()["skeleton_max_input_tokens"])
    holes = [it for it in items if it["type"] == "hole"] + unplaced_holes
    # S4：按缺口自己的编号（hole_key，稳定）排序后再切批，不按它们在序列里的位置切——
    # 位置会因为前面插入/删掉别的缺口而挪动，拿位置分批会让新插入点之后所有批次的请求
    # 文本、缓存键全变，插一个缺口就让所有空洞批全部重新真调模型（重付一次钱）。
    ask = sorted((h for h in holes if hole_allowed(h)), key=lambda h: natural_key(hole_key(h)))
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
        key_of = {hole_key(h): h for h in batch}
        expect = {key: hole_allowed(h) for key, h in key_of.items()}
        text = "\n\n".join(hole_block(h, info) for h in batch)
        d = await caller.call(PROMPT_HOLES, {"holes": text}, lambda d, ex=expect: check_holes(d, ex),
                              f"holes/{k}", usable=lambda d, ex=expect: not check_holes(d, ex))
        if d is not None:
            for x in d["holes"]:
                h = key_of.get(x["id"])
                if h is not None:
                    tasks[h["id"]] = one_line(x["task"])
    for h in holes:
        h["task"] = tasks.get(h["id"]) or one_line(fallback_task(h))

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


# ---------------------------------------------------------------------------
# 读、保存编辑、校验、对账标注
# ---------------------------------------------------------------------------


class BrokenSkeletonFile(ValueError):
    """骨架.json 坏了。作者改过的骨架不能当空处理。"""


def _structure_problems(sk, known: set[str] | None) -> list[str]:
    """结构检查：类型对不对、标题/编号是不是真字符串、场景 / 空洞编号有没有重复。
    known 是 None 时只查结构，不查「这个场景编号存不存在」——读文件（load_skeleton）时
    只该管结构对不对，「编号存不存在」是保存时（validate_skeleton）才查的事，读的时候
    交给 annotate 标 missing（S1：手改坏的骨架结构错了要能报清楚，不是走到哪炸到哪）。"""
    if not isinstance(sk, dict) or not isinstance(sk.get("volumes"), list):
        return ["骨架要有 volumes 列表"]
    problems: list[str] = []
    seen_s: set[str] = set()
    seen_h: set[str] = set()

    def item(it, where: str) -> None:
        if not isinstance(it, dict):
            problems.append(f"{where}：条目要是对象")
            return
        if it.get("type") == "scene":
            sid = it.get("id")
            if not isinstance(sid, str) or not sid:
                problems.append(f"{where}：场景要有编号")
                return
            if known is not None and sid not in known:
                problems.append(f"{where}：没有这个场景 {sid}")
            elif sid in seen_s:
                problems.append(f"{where}：场景 {sid} 出现了不止一次")
            seen_s.add(sid)
        elif it.get("type") == "hole":
            hid = it.get("id")
            if not isinstance(hid, str) or not hid:
                problems.append(f"{where}：空洞要有编号")
            elif hid in seen_h:
                problems.append(f"{where}：空洞编号 {hid} 重复了")
            seen_h.add(hid)
            if not isinstance(it.get("task"), str):
                problems.append(f"{where}：空洞 {hid} 要有任务说明")
        else:
            problems.append(f"{where}：条目类型只能是 scene 或 hole")

    for vi, v in enumerate(sk["volumes"], 1):
        if not isinstance(v, dict) or not isinstance(v.get("title"), str) or not v.get("title").strip() \
           or not isinstance(v.get("chapters"), list):
            problems.append(f"第 {vi} 卷要有标题和 chapters")
            continue
        for ci, ch in enumerate(v["chapters"], 1):
            where = f"第 {vi} 卷第 {ci} 章"
            if not isinstance(ch, dict) or not isinstance(ch.get("title"), str) or not ch.get("title").strip() \
               or not isinstance(ch.get("items"), list):
                problems.append(f"{where}要有标题和 items")
                continue
            for it in ch["items"]:
                item(it, where)
    up = sk.get("unplaced") or {}
    if not isinstance(up, dict):
        problems.append("unplaced 要是对象")
    else:
        for x in up.get("scenes") or []:
            item({"type": "scene", "id": x.get("id") if isinstance(x, dict) else None}, "未定位")
        for x in up.get("holes") or []:
            item({**x, "type": "hole"} if isinstance(x, dict) else x, "未定位")
    return problems


def load_skeleton(book: Book) -> dict:
    try:
        data = read_json(book.skeleton_path)
    except ValueError as e:
        raise BrokenSkeletonFile(f"取舍/骨架.json 不是合法 JSON：{e}") from e
    if data is None:
        raise FileNotFoundError("还没有骨架，先生成一次")
    problems = _structure_problems(data, None)
    if problems:
        raise BrokenSkeletonFile("取舍/骨架.json 结构不对：" + "；".join(problems[:10]))
    return data


def validate_skeleton(sk, known: set[str]) -> list[str]:
    return _structure_problems(sk, known)


def _strip_flags(sk: dict) -> dict:
    sk = copy.deepcopy(sk)
    for v in sk.get("volumes") or []:
        for ch in v.get("chapters") or []:
            for it in ch.get("items") or []:
                if isinstance(it, dict):
                    it.pop("flag", None)
    for x in (sk.get("unplaced") or {}).get("scenes") or []:
        if isinstance(x, dict):
            x.pop("flag", None)
    return sk


def _normalize_titles(sk: dict) -> dict:
    """卷名、章名、空洞说明压成单行——不管是模型生成的还是作者手改提交的，都不能让换行
    （甚至夹带 Markdown 标题符号）原样写进去，混进导出的 md 里当成真正的标题（M2）。"""
    sk = copy.deepcopy(sk)
    for v in sk.get("volumes") or []:
        if isinstance(v, dict) and isinstance(v.get("title"), str):
            v["title"] = one_line(v["title"])
        for ch in (v.get("chapters") or []) if isinstance(v, dict) else []:
            if isinstance(ch, dict) and isinstance(ch.get("title"), str):
                ch["title"] = one_line(ch["title"])
            for it in (ch.get("items") or []) if isinstance(ch, dict) else []:
                if isinstance(it, dict) and it.get("type") == "hole" and isinstance(it.get("task"), str):
                    it["task"] = one_line(it["task"])
    for x in (sk.get("unplaced") or {}).get("holes") or []:
        if isinstance(x, dict) and isinstance(x.get("task"), str):
            x["task"] = one_line(x["task"])
    return sk


def _scene_ids(sk: dict) -> set[str]:
    """骨架里出现过的所有场景编号（卷章里的 + 未定位的），不管当时合不合法。"""
    out: set[str] = set()
    for v in sk.get("volumes") or []:
        for ch in (v.get("chapters") or []) if isinstance(v, dict) else []:
            for it in (ch.get("items") or []) if isinstance(ch, dict) else []:
                if isinstance(it, dict) and it.get("type") == "scene" and isinstance(it.get("id"), str):
                    out.add(it["id"])
    for x in (sk.get("unplaced") or {}).get("scenes") or []:
        if isinstance(x, dict) and isinstance(x.get("id"), str):
            out.add(x["id"])
    return out


def save_skeleton(book: Book, sk) -> dict:
    """保存作者编辑后的整份骨架。场景编号认所有场景（含已移除的），已移除的由 annotate 标出来。

    S3：跟磁盘上现有的骨架比，场景编号少了的不接受——静默丢一块，导出就悄悄少一块，
    作者很难发现。真要去掉一块场景，先经过删除线（cut）或者放进未定位，不能直接从
    卷章条目里消失。"""
    known = {s.id for s in load_scenes(book)}
    problems = validate_skeleton(sk, known)
    if problems:
        raise ValueError("；".join(problems[:10]))
    try:
        old = load_skeleton(book)
    except (BrokenSkeletonFile, FileNotFoundError):
        old = None
    if old is not None:
        gone = sorted(_scene_ids(old) - _scene_ids(sk), key=natural_key)
        if gone:
            raise ValueError("这些场景从骨架里消失了，不能这样保存（先放进未定位或经过删除线）："
                              + "、".join(gone))
    sk = _normalize_titles(_strip_flags(sk))
    sk.setdefault("unplaced", {"scenes": [], "holes": []})
    sk["by"] = "author"
    sk["edited"] = now_iso()
    with FILE_LOCK:
        write_json(book.skeleton_path, sk)
    return sk


def annotate(book: Book, sk: dict, threads: dict) -> dict:
    """给界面看的副本：场景已经没了标 missing，换过主版本的标 not_main，所属线后来被砍标 cut；
    章节备注每次用当前的看板 / 线重算，不用生成那一刻存的快照（S5：看板改了、场景挪了，
    界面显示的应该是现在的状态，不是生成那一刻的旧备注）；另外把「按现在的线应该在书里、
    骨架里却找不到」的场景列进 absent——PUT 挡住了新的静默丢场景（S3），但手改文件、
    或者生成骨架之后归线又加了新场景，都可能出现这种缺口，读的时候补上提醒。不落盘。"""
    out = copy.deepcopy(sk)
    live = {s.id for s in load_scenes(book) if not s.removed}
    cols = columns(book, threads)
    vmap = version_map(book)
    thread_of: dict[str, str] = {}
    for t in threads.get("threads") or []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        for sid0 in t.get("scenes") or []:
            thread_of.setdefault(sid0, t["id"])
            thread_of.setdefault(vmap.get(sid0, sid0), t["id"])

    def mark(it: dict) -> None:
        sid = it.get("id")
        if sid not in live:
            it["flag"] = "missing"
        elif sid in vmap:
            it["flag"] = "not_main"
        elif cols.get(thread_of.get(sid), {}).get("col") == "cut":
            it["flag"] = "cut"

    present: set[str] = set()
    for v in out.get("volumes") or []:
        for ch in v.get("chapters") or []:
            items = ch.get("items")
            if isinstance(items, list):
                ch["notes"] = notes_for(items, cols, threads)
                for it in items:
                    if isinstance(it, dict) and it.get("type") == "scene":
                        mark(it)
                        if isinstance(it.get("id"), str):
                            present.add(it["id"])
    for x in (out.get("unplaced") or {}).get("scenes") or []:
        if isinstance(x, dict):
            mark(x)
            if isinstance(x.get("id"), str):
                present.add(x["id"])

    info = scene_info(book)
    removed = {sid for sid, y in info.items() if y["removed"]} | (non_main_versions(book) - set(vmap))
    seq, unplaced_scenes = build_sequence(threads, cols, removed, vmap)
    expected = {it["id"] for it in seq} | {u["id"] for u in unplaced_scenes}
    out["absent"] = sorted(expected - present, key=natural_key)
    return out
