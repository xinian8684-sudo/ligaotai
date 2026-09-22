"""二期：矛盾裁决与定稿设定（计划④ spec 第 5 节）。

裁决的唯一真源是 矛盾.json 每组的 verdict；定稿设定.json 由它派生，每次裁决后整体重写。
编号固定、重跑迁移、值集合变了标 stale，都是步骤 7（contradictions.build_result）已经做好的，
这里只负责写 verdict，不碰迁移逻辑。
"""

from __future__ import annotations

from .book import FILE_LOCK, Book, now_iso
from .fsutil import read_json, write_json

KINDS = ("pick", "own", "later")


class BrokenContradictions(ValueError):
    """矛盾.json 不是合法 JSON，或者形状不对。"""


class NoSuchGroup(KeyError):
    """给的矛盾编号找不到。"""


def load_contradictions(book: Book) -> dict:
    try:
        data = read_json(book.contradictions_path)
    except ValueError as e:
        raise BrokenContradictions(f"矛盾.json 不是合法 JSON：{e}") from e
    if data is None:
        raise FileNotFoundError("还没有矛盾扫描结果，先跑步骤 7")
    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        raise BrokenContradictions("矛盾.json 的 groups 不是列表")
    return data


def _find(data: dict, cid: str) -> dict:
    for g in data["groups"]:
        if isinstance(g, dict) and g.get("id") == cid:
            return g
    raise NoSuchGroup(cid)


def _values(g: dict) -> list[dict]:
    return [v for v in g.get("values") or [] if isinstance(v, dict)]


def make_verdict(g: dict, kind: str, value: str | None = None, note: str = "") -> dict:
    if kind not in KINDS:
        raise ValueError(f"裁决只能是 {' / '.join(KINDS)}")
    v: dict = {"kind": kind, "by": "author", "at": now_iso()}
    note = (note or "").strip()
    if kind == "pick":
        if value not in [x.get("value") for x in _values(g)]:
            raise ValueError(f"「{value}」不是这一组里的值")
        v.update(value=value, note=note)
    elif kind == "own":
        value = (value or "").strip()
        if not value:
            raise ValueError("自己写的说法不能为空")
        v.update(value=value, note=note)
    return v


def canon_items(data: dict) -> list[dict]:
    """有效裁决（pick / own，且没标 stale）→ 定稿设定条目。"""
    items = []
    for g in data.get("groups") or []:
        if not isinstance(g, dict):
            continue
        v = g.get("verdict")
        if not isinstance(v, dict) or v.get("kind") not in ("pick", "own") or g.get("verdict_stale"):
            continue
        sources: list[str] = []
        if v["kind"] == "pick":
            for val in _values(g):
                if val.get("value") == v.get("value"):
                    sources = [s.get("id") for s in val.get("scenes") or [] if isinstance(s, dict)]
        items.append({"id": g.get("id"), "subject": g.get("subject"), "attribute": g.get("attribute"),
                      "value": v.get("value"), "sources": sources, "note": v.get("note", "")})
    return items


def _write_canon(book: Book, items: list[dict]) -> dict:
    canon = {"generated": now_iso(), "items": items}
    write_json(book.canon_path, canon)
    return canon


def set_verdict(book: Book, cid: str, kind: str | None, value: str | None = None, note: str = "") -> dict:
    """写（kind 为 None 时撤销）一组的裁决，同时重写定稿设定。返回改后的组。"""
    with FILE_LOCK:
        data = load_contradictions(book)
        g = _find(data, cid)
        if kind is None:
            g["verdict"] = None
            g["verdict_sig"] = None
        else:
            g["verdict"] = make_verdict(g, kind, value, note)
            # 判定依据 = 作者下判定这一刻的值集合；步骤 7 重跑时拿它比，值变了才标 stale
            g["verdict_sig"] = g.get("values_sig")
        g["verdict_stale"] = False
        write_json(book.contradictions_path, data)
        _write_canon(book, canon_items(data))
    return g


def current_canon(book: Book) -> dict:
    """按 矛盾.json 现算定稿设定；文件跟现算结果不一样（比如步骤 7 重跑后有裁决变 stale）就重写。"""
    with FILE_LOCK:
        items = canon_items(load_contradictions(book))
        try:
            old = read_json(book.canon_path)
        except ValueError:
            old = None
        if isinstance(old, dict) and old.get("items") == items:
            return old
        return _write_canon(book, items)


def followups(book: Book, cid: str) -> dict:
    """定下说法后，出现其他值、要跟着改的场景。只展示，不改原文。"""
    g = _find(load_contradictions(book), cid)
    v = g.get("verdict")
    scenes: list[dict] = []
    if isinstance(v, dict) and v.get("kind") in ("pick", "own"):
        for val in _values(g):
            if v["kind"] == "pick" and val.get("value") == v.get("value"):
                continue
            for s in val.get("scenes") or []:
                if isinstance(s, dict):
                    scenes.append({"id": s.get("id"), "quote": s.get("quote", ""), "value": val.get("value")})
    return {"id": cid, "verdict": v, "scenes": scenes}
