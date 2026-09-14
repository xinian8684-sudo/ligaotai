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


# --- 6.2 划支线 ---


def check_lines(data: dict, ordered: set[str], outlines: set[str], known: set[str]) -> list[str]:
    threads = data.get("threads")
    if not isinstance(threads, list):
        return ["缺少 threads 列表"]
    problems: list[str] = []
    scene_list: list[str] = []
    outline_list: list[str] = str_list(data.get("world_outlines"))
    mains = 0
    for i, t in enumerate(threads, 1):
        if not isinstance(t, dict):
            problems.append(f"第 {i} 条线格式不对")
            continue
        tid = t.get("id")
        if tid not in (None, "") and tid not in known:
            problems.append(f"第 {i} 条线的 id「{tid}」不是已有的线；新线不要写 id")
        elif tid in (None, "") and not text(t.get("name")):
            problems.append(f"第 {i} 条线没有 name")
        mains += t.get("main") is True
        scene_list += str_list(t.get("scenes"))
        outline_list += str_list(t.get("outlines"))
    if threads and mains != 1:
        problems.append(f"要恰好有一条线标 \"main\": true，现在有 {mains} 条")
    problems += coverage_problems(scene_list, ordered, "正文/碎片块")
    problems += coverage_problems(outline_list, outlines, "提纲块")
    return problems


def clean_lines(data: dict, ordered: set[str], outlines: set[str], known: set[str]) -> dict:
    """返回 {"threads": [{"key", "name", "about", "main", "scenes", "outlines"}], "world_outlines", "missing"}。
    key 是已有线的键，新线是 None。"""
    taken: set[str] = set()

    def pick(ids, allowed: set[str]) -> list[str]:
        out = []
        for s in str_list(ids):
            if s in allowed and s not in taken:
                taken.add(s)
                out.append(s)
        return out

    threads: list[dict] = []
    by_key: dict[str, dict] = {}
    world_outlines: list[str] = []
    for t in data.get("threads") or []:
        if not isinstance(t, dict):
            continue
        key = t.get("id") if t.get("id") in known else None
        scenes, outs = pick(t.get("scenes"), ordered), pick(t.get("outlines"), outlines)
        if key is not None and key in by_key:
            by_key[key]["scenes"] += scenes
            by_key[key]["outlines"] += outs
            by_key[key]["main"] = by_key[key]["main"] or t.get("main") is True
            continue
        if key is None and not scenes:
            world_outlines += outs
            continue
        entry = {
            "key": key,
            "name": "" if key else (text(t.get("name")) or UNNAMED_THREAD),
            "about": "" if key else text(t.get("about")),
            "main": t.get("main") is True,
            "scenes": scenes,
            "outlines": outs,
        }
        threads.append(entry)
        if key is not None:
            by_key[key] = entry
    world_outlines += pick(data.get("world_outlines"), outlines)
    world_outlines += [s for s in sorted(outlines, key=natural_key) if s not in taken]
    missing = [s for s in sorted(ordered, key=natural_key) if s not in taken]
    first = next((t for t in threads if t["main"]), None)
    if first is None and threads:
        first = max(threads, key=lambda t: len(t["scenes"]))  # max 平票取第一个
    for t in threads:
        t["main"] = t is first
    return {"threads": threads, "world_outlines": world_outlines, "missing": missing}


# --- 6.3 线内排序 ---

END_STATES = ("完结", "待定")


def parse_time(v) -> dict | None:
    """[数值或 null, 把握] 或 {"t", "conf"} → {"t", "conf"}；格式不对返回 None。"""
    if isinstance(v, dict):
        v = [v.get("t"), v.get("conf")]
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return None
    t, conf = v
    if isinstance(t, str):
        try:
            t = float(t)
        except ValueError:
            return None
    if t is not None and (isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t)):
        return None
    return {"t": t, "conf": conf if conf in CONFS else "低"}


def expand_order(order, segs: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    for x in str_list(order):
        out += segs.get(x, [x])
    return out


def check_order(data: dict, segs: dict[str, list[str]], expected: set[str]) -> list[str]:
    if not isinstance(data.get("order"), list):
        return ["缺少 order 列表"]
    problems = coverage_problems(expand_order(data["order"], segs), expected, "场景（或片段里的场景）")
    times = data.get("times") if isinstance(data.get("times"), dict) else {}
    no_time = [s for s in sorted(expected, key=natural_key) if s not in times]
    bad_time = [s for s in sorted(expected, key=natural_key) if s in times and parse_time(times[s]) is None]
    if no_time:
        problems.append("这些块没有给故事时间：" + "、".join(no_time[:MAX_LISTED]))
    if bad_time:
        problems.append("这些块的时间格式不对，要写成 [数值或 null, \"高/中/低\"]：" + "、".join(bad_time[:MAX_LISTED]))
    end = data.get("end")
    if not isinstance(end, dict) or end.get("state") not in END_STATES:
        problems.append("end.state 只能是「完结」或「待定」")
    return problems


def clean_order(data: dict, segs: dict[str, list[str]], expected: set[str], fallback: list[str]) -> dict:
    """返回 {"scenes", "times", "end", "missing"}；missing 按 fallback 的顺序。"""
    scenes: list[str] = []
    for s in expand_order(data.get("order"), segs):
        if s in expected and s not in scenes:
            scenes.append(s)
    got = set(scenes)
    raw = data.get("times") if isinstance(data.get("times"), dict) else {}
    times = {}
    for s in scenes:
        t = parse_time(raw.get(s)) if s in raw else None
        if t is not None:
            times[s] = t
    end = data.get("end") if isinstance(data.get("end"), dict) else {}
    state = end.get("state") if end.get("state") in END_STATES else "待定"
    return {
        "scenes": scenes,
        "times": times,
        "end": {"state": state, "note": text(end.get("note"))},
        "missing": [s for s in fallback if s in expected and s not in got],
    }
