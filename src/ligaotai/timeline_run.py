"""时间线检查：调模型、落盘、读、裁决（spec 第 4、5 节）。纯函数在 timeline.py。"""

from __future__ import annotations

import asyncio

from .book import FILE_LOCK, Book, now_iso
from .cards import load_cards
from .contradictions import SCENE_REF
from .fsutil import read_json, write_json
from .llm import LLMClient
from .llm_caller import Caller, Progress, _noop
from .scenes import get_scene
from .threads_input import name_map
from .threads_ops import load_threads
from . import timeline as tl

A_STATUSES = ("在场", "提到", "说不准")


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


def _aliases(cmap: dict, who: str) -> list[str]:
    return [who] + [n for (t, n), c in cmap.items() if t == "person" and c == who and n != who]


def _summary(cards: dict, sid: str) -> str:
    return " ".join(str(tl._card(cards, sid).get("summary") or "").split())[:120]


def _death_text(i: int, s: dict, snippets: list[str]) -> str:
    return "\n".join([f"A-{i:02d} 人：{s['who']}",
                      f"  死亡那场 [{s['death']}]：{s['death_quote']}",
                      f"  后面那场 [{s['later']}]：" + " …… ".join(snippets)])


def _ref_text(i: int, a: dict, cards: dict) -> str:
    lines = [f"C-{i:02d} 回指所在场 [{a['scene']}]：{_summary(cards, a['scene'])}",
             f"  回指原话：{a['ref']}", "  候选："]
    lines += [f"    [{c}] {_summary(cards, c)}" for c in a["candidates"]]
    return "\n".join(lines)


def run_timeline(book: Book, client: LLMClient, progress: Progress = _noop) -> dict:
    return asyncio.run(_run(book, client, progress))


async def _run(book: Book, client: LLMClient, progress: Progress) -> dict:
    fp = tl.input_fingerprint(book)
    seq, pos, n_unplaced = tl.story_order(book)
    cards = load_cards(book)
    cmap = name_map(book)
    line_of = {s: t["id"] for t in load_threads(book).get("threads") or [] if isinstance(t, dict)
               for s in t.get("scenes") or []}
    deaths, capped = tl.death_suspects(seq, pos, cards, cmap)
    asks, no_cand, all_before = tl.ref_suspects(seq, pos, cards, cmap, line_of)

    caller = Caller(book, client, progress, cache_path=book.timeline_cache_path, tag_prefix="timeline")
    a_batches = [deaths[i:i + A_BATCH] for i in range(0, len(deaths), A_BATCH)]
    c_batches = [asks[i:i + C_BATCH] for i in range(0, len(asks), C_BATCH)]
    caller.plan(len(a_batches) + len(c_batches))

    async def one_a(k: int, batch: list[dict]) -> list[dict]:
        ids = {f"A-{i:02d}" for i in range(1, len(batch) + 1)}
        texts = []
        for i, s in enumerate(batch, 1):
            snips = tl.name_snippets(get_scene(book, s["later"]).text, _aliases(cmap, s["who"]))
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
        judged = got or {i: {"happens_in": None, "reason": "这一批调用失败，没拿到判断"} for i in cands}
        return [{**a, **judged[f"C-{i:02d}"]} for i, a in enumerate(batch, 1)]

    a_res = [x for r in await asyncio.gather(*(one_a(k, b) for k, b in enumerate(a_batches))) for x in r]
    c_res = [x for r in await asyncio.gather(*(one_c(k, b) for k, b in enumerate(c_batches))) for x in r]

    conflicts, dismissed = [], []
    for s in a_res:
        if s["status"] == "提到":
            dismissed.append({"who": s["who"], "scenes": [s["death"], s["later"]]})
            continue
        later_text = get_scene(book, s["later"]).text
        conflicts.append({"kind": "A", "who": s["who"], "ref": None, "scenes": [s["death"], s["later"]],
                          "pos": [pos[s["death"]], pos[s["later"]]],
                          "quotes": [s["death_quote"], tl.name_snippets(later_text, _aliases(cmap, s["who"]), limit=1)[0]],
                          "reason": s["reason"], "status": s["status"]})
    for a in c_res:
        h = a["happens_in"]
        if h is not None and pos[h] > pos[a["scene"]]:
            conflicts.append({"kind": "C", "who": None, "ref": a["ref"], "scenes": [a["scene"], h],
                              "pos": [pos[a["scene"]], pos[h]], "quotes": [a["ref"], _summary(cards, h)],
                              "reason": a["reason"], "status": ""})
    conflicts.sort(key=lambda c: (c["kind"], c["pos"][0], c["pos"][1]))  # 先 A 后 C，各自按故事位置

    with FILE_LOCK:
        try:
            old = read_json(book.timeline_path, {})
        except ValueError:
            old = {}
        result = {"generated": now_iso(), "fingerprint": fp, **tl.assemble(conflicts, old),
                  "dismissed": dismissed,
                  "asked_refs": [{k: a[k] for k in ("scene", "ref", "candidates", "happens_in")} for a in c_res],
                  "stats": {"placed": len(seq), "unplaced": n_unplaced, "a_suspects": len(deaths), "a_capped": capped,
                            "refs_asked": len(asks), "refs_no_candidate": no_cand, "refs_all_before": all_before},
                  "failed": list(caller.failed)}
        write_json(book.timeline_path, result)
    return {"ok": True, "conflicts": len(result["conflicts"]), "failed": len(caller.failed)}


VERDICT_KINDS = ("author_error", "order_error", "ignore")


def load_timeline(book: Book) -> dict:
    """GET 用：结果文件 + never_run + stale（输入指纹对不上）。文件坏了抛 ValueError，接口层报 500。"""
    if not book.timeline_path.exists():
        return {"conflicts": [], "never_run": True, "stale": False}
    data = read_json(book.timeline_path, {})
    if not isinstance(data, dict):
        raise ValueError("时间冲突.json 不是一个 json 对象，多半被手改坏了")
    try:
        stale = data.get("fingerprint") != tl.input_fingerprint(book)
    except FileNotFoundError:
        stale = True  # 归线结果没了
    return {**data, "never_run": False, "stale": stale}


def set_timeline_verdict(book: Book, tid: str, kind: str | None) -> dict:
    if kind is not None and kind not in VERDICT_KINDS:
        raise ValueError("裁决只能是：" + " / ".join(VERDICT_KINDS))
    with FILE_LOCK:
        data = read_json(book.timeline_path, {})
        for c in data.get("conflicts") or []:
            if isinstance(c, dict) and c.get("id") == tid:
                c["verdict"] = None if kind is None else {"kind": kind, "at": now_iso()}
                write_json(book.timeline_path, data)
                return c
    raise KeyError(tid)
