"""二期：砍掉 / 合并一条线之前的影响检查（计划④ spec 第 6.3 节）。

程序化部分不花钱、立刻出：交汇点、只在这条线出场的人物、别的线里可能引用了这条线的地方。
模型部分（伏笔配对）见本文件下半部分。
"""

from __future__ import annotations

import asyncio

from .archive import input_sig, refs_in
from .book import FILE_LOCK, Book, now_iso
from .cards import load_cards
from .entities import PRONOUNS
from .fsutil import natural_key, read_json, write_json
from .llm import LLMClient
from .llm_caller import Caller, Progress, _noop
from .threads_input import name_map
from .threads_ops import load_threads
from .triage import NoSuchThread, columns, thread_ids

STRONG_ROLES = ("主要", "次要")


def _card(cards: dict, sid: str) -> dict:
    rec = cards.get(sid) or {}
    c = rec.get("card") if isinstance(rec, dict) else None
    return c if isinstance(c, dict) else {}


def _aliases(book: Book, canon: str) -> list[str]:
    try:
        data = read_json(book.entities_path, {"entities": []})
    except ValueError:
        data = {"entities": []}
    names = {canon}
    for e in (data or {}).get("entities") or []:
        if isinstance(e, dict) and e.get("type") == "person" and e.get("canonical") == canon:
            names.update(n for n in e.get("names") or [] if isinstance(n, str) and n)
    return sorted(names, key=len, reverse=True)


def program_impact(book: Book, threads: dict, tid: str) -> dict:
    if tid not in thread_ids(threads):
        raise NoSuchThread(tid)
    main = threads.get("main_thread")

    crossings = []
    for x in threads.get("intersections") or []:
        if not isinstance(x, dict) or not x.get("thread"):
            continue
        if x["thread"] == tid:
            other = main
        elif tid == main:
            other = x["thread"]
        else:
            continue
        crossings.append({"other": other, "scene": x.get("scene"), "main_scene": x.get("main_scene"),
                          "reason": x.get("reason", "")})

    cards = load_cards(book)
    cmap = name_map(book)
    appear: dict[str, set[str]] = {}
    strong: dict[str, set[str]] = {}
    for t in threads.get("threads") or []:
        if not isinstance(t, dict):
            continue
        for sid in t.get("scenes") or []:
            for ch in _card(cards, sid).get("characters") or []:
                if not isinstance(ch, dict):
                    continue
                name = str(ch.get("name") or "").strip()
                if not name or name in PRONOUNS:
                    continue
                canon = cmap.get(("person", name), name)
                appear.setdefault(canon, set()).add(t["id"])
                if t["id"] == tid and ch.get("role") in STRONG_ROLES:
                    strong.setdefault(canon, set()).add(sid)
    only = [{"name": n, "scenes": sorted(s, key=natural_key)}
            for n, s in strong.items() if appear.get(n) == {tid}]
    only.sort(key=lambda c: (-len(c["scenes"]), c["name"]))

    aliases = {c["name"]: _aliases(book, c["name"]) for c in only}
    refs = []
    for t in threads.get("threads") or []:
        if not isinstance(t, dict) or t.get("id") == tid:
            continue
        for sid in t.get("scenes") or []:
            for r in _card(cards, sid).get("refs_elsewhere") or []:
                text = str(r)
                hit = [n for n, al in aliases.items() if any(a in text for a in al)]
                if hit:
                    refs.append({"scene": sid, "thread": t["id"], "text": text, "names": hit})
    return {"thread": tid, "crossings": crossings, "only_characters": only, "maybe_refs": refs}


# ---------------------------------------------------------------------------
# 模型部分：跨线伏笔配对 + 补救建议（按需一次调用，结果存 取舍/影响.json）
# ---------------------------------------------------------------------------

PROMPT = "triage_impact"


def _hook_lines(cards: dict, sid: str, prefix: str = "") -> list[str]:
    c = _card(cards, sid)
    out = [f"{prefix}{sid}｜埋｜{h}" for h in c.get("hooks_planted") or [] if str(h).strip()]
    out += [f"{prefix}{sid}｜收｜{h}" for h in c.get("hooks_resolved") or [] if str(h).strip()]
    return out


def impact_input(book: Book, threads: dict, tid: str) -> tuple[dict, set[str], set[str]]:
    """渲染模型输入。返回 (values, 这条线有伏笔的场景, 其他未砍线有伏笔的场景)。"""
    if tid not in thread_ids(threads):
        raise NoSuchThread(tid)
    cols = columns(book, threads)
    me = cols.get(tid, {"col": "undecided", "merge_into": None})
    if me["col"] == "merge":
        action = f"动作：把 {tid} 并入 {me['merge_into']}"
    else:
        action = f"动作：砍掉 {tid}"
    cards = load_cards(book)
    own_lines, own_ids, other_lines, other_ids = [], set(), [], set()
    for t in threads.get("threads") or []:
        if not isinstance(t, dict):
            continue
        is_me = t.get("id") == tid
        if not is_me and cols.get(t.get("id"), {}).get("col") == "cut":
            continue
        for sid in t.get("scenes") or []:
            lines = _hook_lines(cards, sid, "" if is_me else f"{t['id']}｜")
            if not lines:
                continue
            (own_lines if is_me else other_lines).extend(lines)
            (own_ids if is_me else other_ids).add(sid)
    values = {"action": action, "own": "\n".join(own_lines) or "（没有）",
              "others": "\n".join(other_lines) or "（没有）"}
    return values, own_ids, other_ids


def check_impact(data, own: set[str], others: set[str]) -> list[str]:
    if not isinstance(data, dict) or not isinstance(data.get("pairs"), list):
        return ["要输出 {\"pairs\": [...], \"remedy\": \"...\"}"]
    problems = []
    for p in data["pairs"]:
        if not isinstance(p, dict):
            problems.append("pairs 里每一项都要是对象")
            continue
        a, b = p.get("planted"), p.get("resolved")
        if not (isinstance(a, str) and isinstance(b, str)
                and ((a in own and b in others) or (a in others and b in own))):
            problems.append(f"伏笔对 {a} → {b} 不对：必须一端在这条线、另一端在其他线，编号只能用输入里的")
        if not str(p.get("hook") or "").strip():
            problems.append(f"伏笔对 {a} → {b} 没写是什么伏笔")
    allowed = own | others
    refs = refs_in(str(data.get("remedy") or ""))
    if not refs:
        problems.append("补救建议里没带场景编号")
    bad = sorted({r for r in refs if r not in allowed})
    if bad:
        problems.append("补救建议用了不在输入里的编号：" + "、".join(bad))
    return problems


def _impact_sig(values: dict) -> str:
    return input_sig(values["action"] + "\n\x1f\n" + values["own"] + "\n\x1f\n" + values["others"], PROMPT)


def _load_impacts(book: Book) -> dict:
    try:
        data = read_json(book.impact_path, {})
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def model_impact_status(book: Book, threads: dict, tid: str) -> dict | None:
    """这条线最近一次伏笔影响 + 是否过期（看板动作或伏笔输入变了）。没有返回 None。

    卡片当前不在 cut / merge 列时也返回 None：拖回「还没想好」/「保留」就是撤销这次检查
    （spec 6.3），旧结果不该继续显示成「没过期」（M3）。"""
    saved = _load_impacts(book).get(tid)
    if not isinstance(saved, dict):
        return None
    if columns(book, threads).get(tid, {}).get("col") not in ("cut", "merge"):
        return None
    values, _, _ = impact_input(book, threads, tid)
    return {**saved, "stale": saved.get("sig") != _impact_sig(values)}


def run_impact(book: Book, client: LLMClient, tid: str, progress: Progress = _noop) -> dict:
    return asyncio.run(_run_impact(book, client, tid, progress))


async def _run_impact(book: Book, client: LLMClient, tid: str, progress: Progress) -> dict:
    threads = load_threads(book)
    col = columns(book, threads).get(tid, {}).get("col")
    if col not in ("cut", "merge"):
        raise ValueError("只有放进「砍掉」或「合并」的线才做影响检查")
    values, own, others = impact_input(book, threads, tid)
    result = {"pairs": [], "remedy": ""}
    failed: list = []
    if own:
        caller = Caller(book, client, progress, cache_path=book.triage_cache_path, tag_prefix="triage")
        caller.plan(1)

        def check(d):
            return check_impact(d, own, others)

        # usable：不合规的结果别留在缓存里（见 advice.py 同一处注释）
        data = await caller.call(PROMPT, values, check, f"impact/{tid}", usable=lambda d: not check(d))
        if data is None:
            return {"ok": False, "failed": caller.failed}
        result = {"pairs": data["pairs"], "remedy": data["remedy"]}
    with FILE_LOCK:
        impacts = _load_impacts(book)
        impacts[tid] = {"sig": _impact_sig(values), "generated": now_iso(), **result}
        write_json(book.impact_path, impacts)
    return {"ok": True, "pairs": len(result["pairs"]), "failed": failed}
