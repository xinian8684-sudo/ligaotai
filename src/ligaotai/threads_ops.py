"""步骤 6 的作者调整：确认、改名、挪块、合并线、拆线、设主线、挪线。

每个操作「读 → 改 → 写」整段在 FILE_LOCK 里，跟 run_threads 的写回、跟彼此都串行。
作者动过的线（和它所在的世界）都算已确认，重跑时原样保留；设主线也算动过这条线。
内容真的变了（不只是确认状态）才把下游（步骤 7）标过期。"""

from __future__ import annotations

from .book import FILE_LOCK, Book
from .fsutil import read_json, write_json
from .threads import CONFIRMED, content_signature, next_number, normalize, thread_id

GONE_PENDING = "建议归入的线已被删除"


class BrokenThreadsFile(Exception):
    """世界与支线.json 不是合法 JSON（作者手改坏了 / 写到一半）：读不出来，不能覆盖，
    也不能假装它是空的，得让作者自己去处理。"""


def read_threads(book: Book) -> dict | None:
    """读 世界与支线.json 的原始内容（没规范化）：文件不存在返回 None；JSON 解析失败抛
    BrokenThreadsFile（GET /threads 和 load_threads 都走这条读法，行为一致）。"""
    try:
        return read_json(book.threads_path)
    except ValueError as e:
        raise BrokenThreadsFile("世界与支线.json 格式坏了，要手动修好或删掉后重跑步骤 6") from e


def load_threads(book: Book) -> dict:
    data = read_threads(book)
    if data is None:
        raise FileNotFoundError("还没有归线结果，先跑步骤 6")
    return normalize(data)


def _load_tidy(book: Book) -> tuple[dict, str]:
    """读出来先整理一遍再算签名：run_threads 写出来的文件不一定是 _tidy 过的形状
    （比如有个世界的线全被排空了、没有笔记和提纲），签名要在整理之后算，
    免得作者第一次「只确认」时 _tidy 顺手删掉这种世界就把签名带变了、误标下游过期。"""
    data = load_threads(book)
    _tidy(data)
    return data, content_signature(data)


def _thread(data: dict, tid: str) -> dict:
    for t in data["threads"]:
        if t["id"] == tid:
            return t
    raise KeyError(tid)


def _world(data: dict, wid: str) -> dict:
    for w in data["worlds"]:
        if w["id"] == wid:
            return w
    raise KeyError(wid)


def _touch(data: dict, t: dict) -> None:
    """作者动过这条线：线和它所在的世界都算已确认。"""
    t["status"] = CONFIRMED
    _world(data, t["world"])["status"] = CONFIRMED


def _all_scene_ids(data: dict) -> set[str]:
    ids = {s for t in data["threads"] for s in t["scenes"] + t["outlines"]}
    ids |= {s for w in data["worlds"] for s in w.get("notes", []) + w.get("outlines", [])}
    ids |= {u["scene"] for u in data.get("unassigned", [])}
    ids |= {p["scene"] for p in data.get("pending", [])}
    return ids


def _remove(data: dict, ids: set[str]) -> None:
    for t in data["threads"]:
        t["scenes"] = [s for s in t["scenes"] if s not in ids]
        t["outlines"] = [s for s in t["outlines"] if s not in ids]
        t["times"] = {k: v for k, v in (t.get("times") or {}).items() if k not in ids}
    for w in data["worlds"]:
        w["notes"] = [s for s in w.get("notes", []) if s not in ids]
        w["outlines"] = [s for s in w.get("outlines", []) if s not in ids]
    data["unassigned"] = [u for u in data.get("unassigned", []) if u["scene"] not in ids]
    data["pending"] = [p for p in data.get("pending", []) if p["scene"] not in ids]


def _tidy(data: dict) -> None:
    for t in data["threads"]:
        if not t["scenes"]:
            w = next((w for w in data["worlds"] if w["id"] == t["world"]), None)
            if w is not None:
                w.setdefault("outlines", []).extend(t["outlines"])
    data["threads"] = [t for t in data["threads"] if t["scenes"]]
    by_id = {t["id"]: t for t in data["threads"]}
    for t in data["threads"]:
        t["end"] = {**(t.get("end") or {}), "last": t["scenes"][-1]}
    pending = data.get("pending", [])
    data["pending"] = [p for p in pending if p["thread"] in by_id]
    data["unassigned"] = data.get("unassigned", []) + [
        {"scene": p["scene"], "reason": GONE_PENDING} for p in pending if p["thread"] not in by_id
    ]
    alive = {t["world"] for t in data["threads"]}
    data["worlds"] = [w for w in data["worlds"] if w["id"] in alive or w.get("notes") or w.get("outlines")]
    if data.get("main_thread") not in by_id:
        best = max(data["threads"], key=lambda t: len(t["scenes"]), default=None)
        data["main_thread"] = best["id"] if best else None
        data["main_by"] = "auto"
    main = by_id.get(data["main_thread"])
    data["intersections"] = [
        c for c in data.get("intersections", [])
        if c["thread"] in by_id and c["thread"] != data["main_thread"]
        and c["scene"] in by_id[c["thread"]]["scenes"]
        and main is not None and c["main_scene"] in main["scenes"]
    ]
    for g in data.get("gaps", []):
        t = by_id.get(g.get("thread"))
        if t is None:
            g["thread"] = g["after"] = g["before"] = None
            continue
        for k in ("after", "before"):
            if g.get(k) not in t["scenes"]:
                g[k] = None


def _save(book: Book, data: dict, before: str) -> None:
    """整理后写回；内容签名变了才让下游过期。要在 FILE_LOCK 里调。"""
    _tidy(data)
    write_json(book.threads_path, data)
    if content_signature(data) != before:
        book.mark_downstream_outdated("threads")


def confirm(book: Book, ids: list[str]) -> list[dict]:
    with FILE_LOCK:
        data, before = _load_tidy(book)
        ts = [_thread(data, tid) for tid in dict.fromkeys(ids)]  # 有找不到的就在改动前抛 KeyError
        for t in ts:
            _touch(data, t)
        _save(book, data, before)
    return ts


def rename(book: Book, oid: str, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("名字不能为空")
    with FILE_LOCK:
        data, before = _load_tidy(book)
        if oid.startswith("L-"):
            obj = _thread(data, oid)
            _touch(data, obj)
        else:
            obj = _world(data, oid)
            obj["status"] = CONFIRMED
        obj["name"] = name
        _save(book, data, before)
    return obj


def move_scenes(book: Book, ids: list[str], tid: str, position: int | None = None, as_outline: bool = False) -> dict:
    """把 ids 挪进线 tid 的 scenes（as_outline 时是 outlines），插在 position（拿掉之后的列表里的位置，None = 末尾）。"""
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise ValueError("要挪的块不能为空")
    with FILE_LOCK:
        data, before = _load_tidy(book)
        t = _thread(data, tid)
        unknown = [s for s in ids if s not in _all_scene_ids(data)]
        if unknown:
            raise ValueError("这些块不在归线结果里：" + "、".join(unknown[:10]))
        own_times = {s: v for s, v in (t.get("times") or {}).items() if s in ids}  # 同一条线里调顺序，时间留着
        _remove(data, set(ids))
        target = t["outlines"] if as_outline else t["scenes"]
        pos = len(target) if position is None else max(0, min(position, len(target)))
        target[pos:pos] = ids
        if not as_outline:
            t.setdefault("times", {}).update(own_times)  # 线可能没有 times 键
        _touch(data, t)
        _save(book, data, before)
    return t


def merge_threads(book: Book, ids: list[str]) -> dict:
    ids = list(dict.fromkeys(ids))
    if len(ids) < 2:
        raise ValueError("至少要选两条线才能合并")
    with FILE_LOCK:
        data, before = _load_tidy(book)
        ts = [_thread(data, tid) for tid in ids]
        keep, rest = ts[0], ts[1:]
        gone = {t["id"] for t in rest}
        for t in rest:  # 别的线的时间是它们自己的线内时间，合进来对不上，不带
            keep["scenes"] += t["scenes"]
            keep["outlines"] += t["outlines"]
        data["threads"] = [t for t in data["threads"] if t["id"] not in gone]
        for p in data.get("pending", []):
            if p["thread"] in gone:
                p["thread"] = keep["id"]
        for g in data.get("gaps", []):
            if g.get("thread") in gone:
                g["thread"] = keep["id"]
        if data.get("main_thread") in gone:
            data["main_thread"] = keep["id"]
        _touch(data, keep)
        _save(book, data, before)
    return keep


def split_thread(book: Book, tid: str, from_scene: str) -> dict:
    with FILE_LOCK:
        data, before = _load_tidy(book)
        t = _thread(data, tid)
        if from_scene not in t["scenes"]:
            raise ValueError(f"{from_scene} 不在 {tid} 里")
        i = t["scenes"].index(from_scene)
        if i == 0:
            raise ValueError("从第一块拆就是整条线，不用拆")
        n = next_number(data, "thread")
        data["next_thread"] = n + 1
        moving = t["scenes"][i:]
        times = t.get("times") or {}
        new = {
            "id": thread_id(n), "world": t["world"], "name": f"{t['name']}（拆出）", "about": "",
            "status": CONFIRMED, "scenes": moving, "times": {s: v for s, v in times.items() if s in moving},
            "outlines": [], "offset": t.get("offset"), "end": {"state": "待定", "note": ""}, "order_failed": False,
        }
        t["scenes"] = t["scenes"][:i]
        t["times"] = {s: v for s, v in times.items() if s in t["scenes"]}
        _touch(data, t)
        data["threads"].insert(data["threads"].index(t) + 1, new)
        _save(book, data, before)
    return new


def set_main(book: Book, tid: str) -> dict:
    """设主线也算动过这条线：不确认的话，这条线之后重跑可能因为块集合变了换成新编号，
    choose_main 找不到旧编号就把作者的选择悄悄换回 auto。"""
    with FILE_LOCK:
        data, before = _load_tidy(book)
        t = _thread(data, tid)
        data["main_thread"], data["main_by"] = tid, "author"
        _touch(data, t)
        _save(book, data, before)
    return t


def move_thread(book: Book, tid: str, wid: str) -> dict:
    with FILE_LOCK:
        data, before = _load_tidy(book)
        t = _thread(data, tid)
        _world(data, wid)  # 世界不存在就在改动前抛 KeyError
        t["world"] = wid
        _touch(data, t)
        _save(book, data, before)
    return t
