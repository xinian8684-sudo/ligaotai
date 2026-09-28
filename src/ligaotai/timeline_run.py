"""时间线检查：调模型、落盘、读、裁决（spec 第 4、5 节）。纯函数在 timeline.py。"""

from __future__ import annotations

from .contradictions import SCENE_REF

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
