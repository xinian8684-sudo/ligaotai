"""步骤 6 各次模型调用的输出检查（给 chat_json 的 check）和收尾清理（3 次后还有问题时用）。

检查函数只返回问题清单，不抛异常；清理函数把输出修成能用的样子：编造的编号丢掉，
重复的只留第一次出现的，漏掉的交给调用方记进「未分配」。"""

from __future__ import annotations

import math

from .fsutil import natural_key

MAX_LISTED = 20
CONFS = ("高", "中", "低")
UNNAMED_WORLD = "未命名世界"
UNNAMED_THREAD = "未命名支线"


def str_list(v) -> list[str]:
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def text(v) -> str:
    return str(v).strip() if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def coverage_problems(listed: list[str], expected: set[str], what: str = "场景") -> list[str]:
    unknown = [x for x in dict.fromkeys(listed) if x not in expected]
    seen: set[str] = set()
    dup: list[str] = []
    for x in listed:
        if x in seen and x not in dup:
            dup.append(x)
        seen.add(x)
    missing = sorted(expected - seen, key=natural_key)
    problems = []
    if unknown:
        problems.append(f"这些编号不在给你的{what}里，不要编造：" + "、".join(unknown[:MAX_LISTED]))
    if dup:
        problems.append("这些编号出现了不止一次，每个只能放一处：" + "、".join(dup[:MAX_LISTED]))
    if missing:
        problems.append(f"这些{what}漏掉了，每个都要放进去：" + "、".join(missing[:MAX_LISTED]))
    return problems


# --- 6.1 划世界 ---


def check_worlds(data: dict, expected: set[str], known: set[str], need_unit: bool) -> list[str]:
    problems: list[str] = []
    if need_unit and not text(data.get("time_unit")):
        problems.append("缺少 time_unit（全书统一的故事时间单位，比如「年」）")
    worlds = data.get("worlds")
    if not isinstance(worlds, list):
        return problems + ["缺少 worlds 列表"]
    listed: list[str] = []
    for i, w in enumerate(worlds, 1):
        if not isinstance(w, dict):
            problems.append(f"第 {i} 个世界格式不对")
            continue
        wid = w.get("id")
        if wid not in (None, "") and wid not in known:
            problems.append(f"第 {i} 个世界的 id「{wid}」不是已有的世界；新世界不要写 id")
        elif wid in (None, "") and not text(w.get("name")):
            problems.append(f"第 {i} 个世界没有 name")
        listed += str_list(w.get("scenes"))
    return problems + coverage_problems(listed, expected)


def clean_worlds(data: dict, expected: set[str], known: set[str]) -> tuple[list[dict], list[str], str]:
    """返回 (世界列表, 漏掉的场景, 时间单位)。世界：{"key", "name", "reason", "scenes"}；
    key 是已有世界的键，新世界是 None（调用方再编号）。"""
    taken: set[str] = set()
    out: list[dict] = []
    by_key: dict[str, dict] = {}
    for w in data.get("worlds") or []:
        if not isinstance(w, dict):
            continue
        wid = w.get("id") if w.get("id") in known else None
        scenes = []
        for s in str_list(w.get("scenes")):
            if s in expected and s not in taken:
                taken.add(s)
                scenes.append(s)
        if wid is not None and wid in by_key:
            by_key[wid]["scenes"] += scenes
            continue
        if wid is None and not scenes:
            continue
        name = text(w.get("name")) if wid is None else ""
        entry = {"key": wid, "name": name or ("" if wid else UNNAMED_WORLD), "reason": text(w.get("reason")), "scenes": scenes}
        out.append(entry)
        if wid is not None:
            by_key[wid] = entry
    missing = [s for s in sorted(expected, key=natural_key) if s not in taken]
    return out, missing, text(data.get("time_unit"))
