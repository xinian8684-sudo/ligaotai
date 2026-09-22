"""二期：取舍看板（计划④ spec 第 6.1、6.2 节）。

看板.json 只存作者的决定：{"cards": {线编号: {"col", "merge_into", "note"}}}。
读的时候按 世界与支线.json 对账（新线补「还没想好」、消失的线标孤儿、合并目标失效要标出来），
对账结果不落盘——落盘只在作者改卡的时候。
"""

from __future__ import annotations

from .book import FILE_LOCK, Book
from .fsutil import read_json, write_json
from .scenes import load_scenes

COLS = ("keep", "merge", "cut", "undecided")


class BrokenBoardFile(ValueError):
    """看板.json 坏了。作者的决定不能当空处理，得让作者自己修。"""


def load_board(book: Book) -> dict:
    try:
        data = read_json(book.board_path, {"cards": {}})
    except ValueError as e:
        raise BrokenBoardFile(f"取舍/看板.json 不是合法 JSON：{e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("cards"), dict):
        raise BrokenBoardFile("取舍/看板.json 的 cards 不是对象")
    return data


def thread_ids(threads: dict) -> list[str]:
    return [t["id"] for t in threads.get("threads") or []
            if isinstance(t, dict) and isinstance(t.get("id"), str) and t["id"]]


def _entry(c) -> dict:
    c = c if isinstance(c, dict) else {}
    col = c.get("col") if c.get("col") in COLS else "undecided"
    return {"col": col, "merge_into": c.get("merge_into") if col == "merge" else None,
            "note": str(c.get("note") or "")}


def reconcile(board: dict, threads: dict) -> dict:
    """带标注的看板副本（orphan / merge_invalid），不落盘。"""
    ids = thread_ids(threads)
    cards: dict[str, dict] = {}
    for tid in ids:
        cards[tid] = {**_entry(board["cards"].get(tid)), "orphan": False, "merge_invalid": False}
    for tid, c in board["cards"].items():
        if tid not in cards:
            cards[tid] = {**_entry(c), "orphan": True, "merge_invalid": False}
    for tid, c in cards.items():
        if c["col"] == "merge":
            tgt = c["merge_into"]
            if tgt == tid or tgt not in ids or cards[tgt]["col"] == "cut":
                c["merge_invalid"] = True
    return {"cards": cards}


def columns(book: Book, threads: dict) -> dict[str, dict]:
    """活着的线 → {"col", "merge_into"}，给骨架用。"""
    cards = reconcile(load_board(book), threads)["cards"]
    return {tid: {"col": c["col"], "merge_into": c["merge_into"]} for tid, c in cards.items() if not c["orphan"]}


def set_card(book: Book, threads: dict, tid: str, col: str,
             merge_into: str | None = None, note: str | None = None) -> dict:
    """改一张卡。返回对账后的整个看板。"""
    if col not in COLS:
        raise ValueError(f"列只能是 {' / '.join(COLS)}")
    ids = thread_ids(threads)
    if tid not in ids:
        raise KeyError(tid)
    with FILE_LOCK:
        board = load_board(book)
        cur = reconcile(board, threads)["cards"]
        if col == "merge":
            if merge_into == tid or merge_into not in ids:
                raise ValueError("合并要选另一条存在的线")
            if cur[merge_into]["col"] == "cut":
                raise ValueError("不能并入已经砍掉的线")
        old = _entry(board["cards"].get(tid))
        board["cards"][tid] = {"col": col, "merge_into": merge_into if col == "merge" else None,
                               "note": old["note"] if note is None else str(note)}
        write_json(book.board_path, board)
        return reconcile(board, threads)


def delete_orphan(book: Book, threads: dict, tid: str) -> dict:
    with FILE_LOCK:
        board = load_board(book)
        if tid in thread_ids(threads):
            raise ValueError("这条线还在，不能删它的卡")
        board["cards"].pop(tid, None)
        write_json(book.board_path, board)
        return reconcile(board, threads)


def non_main_versions(book: Book) -> set[str]:
    """版本组里不是主版本的场景：骨架和字数都只算主版本。"""
    try:
        data = read_json(book.versions_path, {"groups": []})
    except ValueError:
        data = {"groups": []}
    out: set[str] = set()
    for g in (data or {}).get("groups") or []:
        if isinstance(g, dict):
            out.update(m for m in g.get("members") or [] if m != g.get("main"))
    return out


def thread_stats(book: Book, threads: dict) -> dict[str, dict]:
    chars = {s.id: s.chars for s in load_scenes(book) if not s.removed}
    drop = non_main_versions(book)
    gaps: dict[str, int] = {}
    for g in threads.get("gaps") or []:
        if isinstance(g, dict) and g.get("thread"):
            gaps[g["thread"]] = gaps.get(g["thread"], 0) + 1
    out = {}
    for t in threads.get("threads") or []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        scenes = [s for s in t.get("scenes") or [] if isinstance(s, str)]
        out[t["id"]] = {
            "name": t.get("name", ""),
            "world": t.get("world", ""),
            "words": sum(chars.get(s, 0) for s in scenes if s not in drop),
            "scenes": len(scenes),
            "state": (t.get("end") or {}).get("state") or "待定",
            "gaps": gaps.get(t["id"], 0),
            "is_main": t["id"] == threads.get("main_thread"),
            "order_failed": bool(t.get("order_failed")),
        }
    return out
