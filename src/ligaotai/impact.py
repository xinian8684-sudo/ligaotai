"""二期：砍掉 / 合并一条线之前的影响检查（计划④ spec 第 6.3 节）。

程序化部分不花钱、立刻出：交汇点、只在这条线出场的人物、别的线里可能引用了这条线的地方。
模型部分（伏笔配对）见本文件下半部分。
"""

from __future__ import annotations

from .book import Book
from .cards import load_cards
from .entities import PRONOUNS
from .fsutil import natural_key, read_json
from .threads_input import name_map
from .triage import thread_ids

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
        raise KeyError(tid)
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
