"""骨架的排序部分（纯函数，不读文件、不调模型）——计划④ spec 第 7.2 节。

全局时间 = 线 offset + times[sid].t，跟前端 lib/segments.ts 同一规则：offset 为 null 的线
（没对齐主线）和 t 为 null / 缺键的场景都放不进时间轴，进「未定位」，不当 0。
同一时刻：主线优先，再按线编号，再按线内原顺序。
cols：{线编号: {"col", "merge_into"}}（triage.columns 的返回值）；缺的线当「还没想好」。
"""

from __future__ import annotations

from .fsutil import natural_key

UNDECIDED = {"col": "undecided", "merge_into": None}


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _col(cols: dict, tid) -> dict:
    return cols.get(tid) or UNDECIDED


def build_sequence(threads: dict, cols: dict, drop: set[str]) -> tuple[list[dict], list[dict]]:
    """参与的线的场景按全局时间排好。返回 (排好的场景条目, 排不进时间轴的场景)。
    drop：不参与的场景（版本组里的非主版本、已移除的块）。"""
    main = threads.get("main_thread")
    placed, unplaced = [], []
    for t in threads.get("threads") or []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        tid = t["id"]
        if _col(cols, tid)["col"] == "cut":
            continue
        off = t.get("offset")
        times = t.get("times") or {}
        for i, sid in enumerate(t.get("scenes") or []):
            if sid in drop:
                continue
            if not _num(off):
                unplaced.append({"id": sid, "thread": tid, "why": "unaligned_thread"})
                continue
            tm = times.get(sid)
            tv = tm.get("t") if isinstance(tm, dict) else None
            if not _num(tv):
                unplaced.append({"id": sid, "thread": tid, "why": "no_time"})
                continue
            key = (off + tv, 0 if tid == main else 1, natural_key(tid), i)
            placed.append((key, {"type": "scene", "id": sid, "thread": tid}))
    for u in threads.get("unassigned") or []:
        sid = u.get("scene") if isinstance(u, dict) else u
        if isinstance(sid, str) and sid not in drop:
            unplaced.append({"id": sid, "thread": None, "why": "unassigned"})
    placed.sort(key=lambda p: p[0])
    return [p[1] for p in placed], unplaced


def _hole(g: dict) -> dict:
    return {"type": "hole", "id": "", "gap": g.get("id"), "thread": g.get("thread"),
            "after": g.get("after"), "before": g.get("before"), "event": str(g.get("event") or ""),
            "mentioned_in": [m for m in g.get("mentioned_in") or [] if isinstance(m, str)]}


def insert_holes(seq: list[dict], gaps: list, cols: dict) -> tuple[list[dict], list[dict]]:
    """缺口按锚点插成空洞：after 在序列里就插在它后面，否则 before 在就插在它前面，都不在进未定位。
    只属于被砍的线的缺口不插。空洞编号 H-001… 按最终顺序（先序列里的，再未定位的）。"""
    pos = {it["id"] for it in seq}
    after_map: dict[str, list[dict]] = {}
    before_map: dict[str, list[dict]] = {}
    unplaced: list[dict] = []
    for g in gaps or []:
        if not isinstance(g, dict):
            continue
        if g.get("thread") and _col(cols, g["thread"])["col"] == "cut":
            continue
        h = _hole(g)
        if g.get("after") in pos:
            after_map.setdefault(g["after"], []).append(h)
        elif g.get("before") in pos:
            before_map.setdefault(g["before"], []).append(h)
        else:
            unplaced.append({**h, "why": "no_anchor"})
    out: list[dict] = []
    for it in seq:
        out.extend(before_map.get(it["id"], []))
        out.append(it)
        out.extend(after_map.get(it["id"], []))
    n = 0
    for it in out + unplaced:
        if it["type"] == "hole":
            n += 1
            it["id"] = f"H-{n:03d}"
    return out, unplaced


def notes_for(items: list[dict], cols: dict, threads: dict) -> list[dict]:
    """一章的备注：去留未定的线、待并入改写的线、跟被砍线的交汇点。去重、保持出现顺序。"""
    cut_x: dict[str, list[str]] = {}
    for x in threads.get("intersections") or []:
        if isinstance(x, dict) and x.get("thread") and _col(cols, x["thread"])["col"] == "cut":
            cut_x.setdefault(x.get("main_scene"), []).append(x["thread"])
    notes: list[dict] = []
    for it in items:
        if it.get("type") != "scene":
            continue
        c = _col(cols, it.get("thread"))
        if it.get("thread"):
            if c["col"] == "undecided":
                n = {"kind": "undecided", "thread": it["thread"]}
            elif c["col"] == "merge":
                n = {"kind": "merge", "thread": it["thread"], "into": c["merge_into"]}
            else:
                n = None
            if n and n not in notes:
                notes.append(n)
        for ct in cut_x.get(it["id"], []):
            n = {"kind": "cut_crossing", "thread": ct, "scene": it["id"]}
            if n not in notes:
                notes.append(n)
    return notes
