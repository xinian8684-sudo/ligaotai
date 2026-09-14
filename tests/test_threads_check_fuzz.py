"""随机乱输出：threads_check 的检查、打分、清理对任何形状的回复都不抛异常，清理后满足各阶段的不变量。

每轮先造一份正确的回复，再按随机的噪声强度乱改（换成怪值、删键、删 / 重复列表项、编号写成变体），
噪声为 0 时就是正确回复，所以「检查通过 → 清理不会悄悄改掉东西」也能测到。"""

import math
import random

from ligaotai.threads_check import (
    CONFS,
    END_STATES,
    UNNAMED_WORLD,
    _name_key,
    check_align,
    check_gaps,
    check_lines,
    check_order,
    check_worlds,
    clean_align,
    clean_gaps,
    clean_lines,
    clean_order,
    clean_worlds,
    score_align,
    score_gaps,
    score_lines,
    score_order,
    score_worlds,
)

ROUNDS = 1500
NOISE = [0, 0, 0.03, 0.1, 0.3, 0.6]
KEYS = ["id", "name", "scenes", "outlines", "main", "offset", "thread", "scene", "main_scene",
        "t", "conf", "event", "mentioned_in", "after", "before", "state"]
JUNK = [None, True, False, 0, 1, -3, 2.5, 1e308, -1e308, 10**400, -(10**400), float("nan"), float("inf"),
        "", " ", "x", "高", " 高 ", "high", "完结", "待定", "?", "inf", "1e400", [], {}, [None], [[1]],
        {"a": 1}, {"id": "L-001"}, {"t": 1}, ["S-0001"], "S-0001", "S-9999", "L-001", "W-01", "P-001"]
TOP_JUNK = [None, 5, "x", [], [1, 2], {"worlds": 5}, {"threads": True}, {"order": "乱写"}, {"gaps": 5}]


def junk(rng, depth=0):
    r = rng.random()
    if depth < 2 and r < 0.1:
        return [junk(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    if depth < 2 and r < 0.2:
        return {rng.choice(KEYS): junk(rng, depth + 1) for _ in range(rng.randint(0, 3))}
    return rng.choice(JUNK)


def fullwidth(s):
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in s)


def variant(s, rng):
    return rng.choice([s.lower(), fullwidth(s), f" {s} ", s + "9", s])


def mutate(v, rng, noise):
    if rng.random() < noise:
        return junk(rng)
    if isinstance(v, dict):
        return {k: mutate(x, rng, noise) for k, x in v.items() if rng.random() >= noise / 2}
    if isinstance(v, list):
        out = []
        for x in v:
            r = rng.random()
            if r < noise / 3:
                continue
            y = mutate(x, rng, noise)
            out.append(y)
            if r > 1 - noise / 3:
                out.append(y)
        return out
    if isinstance(v, str) and rng.random() < noise:
        return variant(v, rng)
    return v


def noisy(base, rng):
    if rng.random() < 0.03:
        return rng.choice(TOP_JUNK)
    return mutate(base, rng, rng.choice(NOISE))


def contract(check, score, *args):
    """检查返回字符串列表，打分返回非负整数，打分是 0 当且仅当没有问题。"""
    p = check(*args)
    s = score(*args)
    assert isinstance(p, list) and all(isinstance(x, str) for x in p)
    assert isinstance(s, int) and s >= 0
    assert (s == 0) == (p == [])
    return p


def chunks(rng, ids):
    ids = list(ids)
    rng.shuffle(ids)
    out = []
    while ids:
        n = rng.randint(1, 3)
        out.append(ids[:n])
        ids = ids[n:]
    return out


def test_fuzz_worlds():
    rng = random.Random(1)
    for _ in range(ROUNDS):
        expected = {f"S-{i:04d}" for i in rng.sample(range(1, 30), rng.randint(0, 8))}
        known = set(rng.sample(["W-01", "W-02", "N1"], rng.randint(0, 3)))
        names = {k: rng.choice(["人间", "天界", "冥府", ""]) for k in known} if rng.random() < 0.6 else None
        need_unit = rng.random() < 0.5
        worlds = []
        for n, part in enumerate(chunks(rng, expected), 1):
            if known and rng.random() < 0.4:
                worlds.append({"id": rng.choice(sorted(known)), "scenes": part})
            else:
                worlds.append({"name": f"新世界{n}", "reason": "r", "scenes": part})
        data = noisy({"time_unit": "年", "worlds": worlds}, rng)

        p = contract(check_worlds, score_worlds, data, expected, known, need_unit, names)
        out, missing, unit = clean_worlds(data, expected, known, names)
        placed = [s for w in out for s in w["scenes"]] + missing
        assert sorted(placed) == sorted(expected) and len(placed) == len(set(placed))
        assert isinstance(unit, str)
        keys = [w["key"] for w in out if w["key"] is not None]
        assert len(keys) == len(set(keys)) and all(k in known for k in keys)
        known_names = {_name_key(names[k]) for k in known if names and names.get(k)}
        new_names = [_name_key(w["name"]) for w in out if w["key"] is None and w["name"] != UNNAMED_WORLD]
        assert len(new_names) == len(set(new_names)) and not set(new_names) & known_names
        for w in out:
            assert w["key"] is not None or (w["scenes"] and w["name"])
            assert isinstance(w["reason"], str)
        if p == []:
            assert missing == []


def test_fuzz_lines():
    rng = random.Random(2)
    for _ in range(ROUNDS):
        ordered = {f"S-{i:04d}" for i in rng.sample(range(1, 30), rng.randint(0, 8))}
        outl = {f"S-{i:04d}" for i in rng.sample(range(40, 60), rng.randint(0, 4))}
        known = set(rng.sample(["L-003", "W-01#1", "W-01#2"], rng.randint(0, 3)))
        names = {k: rng.choice(["旧线", "甲", "乙", ""]) for k in known} if rng.random() < 0.6 else None
        held = {"S-0404": "L-003", "S-0405": "W-01#1"} if rng.random() < 0.5 else None
        left = sorted(outl)
        threads = []
        for n, part in enumerate(chunks(rng, ordered), 1):
            outs = [left.pop()] if left and rng.random() < 0.5 else []
            if known and rng.random() < 0.3:
                threads.append({"id": rng.choice(sorted(known)), "scenes": part, "outlines": outs})
            else:
                threads.append({"name": f"线{n}", "about": "a", "scenes": part, "outlines": outs})
        if threads:
            threads[rng.randrange(len(threads))]["main"] = True
            if held and rng.random() < 0.3:
                threads[0]["scenes"] = threads[0]["scenes"] + ["S-0404"]
        data = noisy({"threads": threads, "world_outlines": left}, rng)

        p = contract(check_lines, score_lines, data, ordered, outl, known, names, held)
        got = clean_lines(data, ordered, outl, known, names)
        sc = [s for t in got["threads"] for s in t["scenes"]] + got["missing"]
        ou = [s for t in got["threads"] for s in t["outlines"]] + got["world_outlines"]
        assert sorted(sc) == sorted(ordered) and len(sc) == len(set(sc))
        assert sorted(ou) == sorted(outl) and len(ou) == len(set(ou))
        if got["threads"]:
            assert sum(t["main"] for t in got["threads"]) == 1
        for t in got["threads"]:
            assert t["key"] is None or t["key"] in known
            assert t["key"] is not None or (t["scenes"] and t["name"])
            assert isinstance(t["about"], str) and isinstance(t["main"], bool)
        keys = [t["key"] for t in got["threads"] if t["key"] is not None]
        assert len(keys) == len(set(keys))
        known_names = {_name_key(names[k]) for k in known if names and names.get(k)}
        new_names = [_name_key(t["name"]) for t in got["threads"] if t["key"] is None and t["name"] != "未命名支线"]
        assert len(new_names) == len(set(new_names)) and not set(new_names) & known_names
        if p == []:
            assert got["missing"] == []


def test_fuzz_order():
    rng = random.Random(3)
    for _ in range(ROUNDS):
        exp = sorted({f"S-{i:04d}" for i in rng.sample(range(1, 20), rng.randint(0, 7))})
        expected = set(exp)
        segs, order, i = {}, [], 0
        while i < len(exp):
            part = exp[i:i + rng.randint(1, 3)]
            i += len(part)
            if len(part) > 1 and rng.random() < 0.7:
                p = f"P-{len(segs) + 1:03d}"
                segs[p] = part
                order.append(p)
            else:
                order += part
        rng.shuffle(order)
        fallback = list(exp) if rng.random() < 0.9 else exp[:-1]
        times = {s: [rng.choice([n, None, 1.5, "2"]), rng.choice(CONFS)] for n, s in enumerate(exp)}
        data = noisy({"order": order, "times": times, "end": {"state": rng.choice(END_STATES), "note": "n"}}, rng)

        p = contract(check_order, score_order, data, segs, expected)
        got = clean_order(data, segs, expected, fallback)
        allb = got["scenes"] + got["missing"]
        assert sorted(allb) == sorted(expected) and len(allb) == len(set(allb))
        assert set(got["times"]) <= set(got["scenes"])
        for v in got["times"].values():
            t = v["t"]
            assert v["conf"] in CONFS
            assert t is None or (isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t))
        assert got["end"]["state"] in END_STATES and isinstance(got["end"]["note"], str)
        assert isinstance(got["failed"], bool)
        if got["failed"]:
            assert got["missing"] == [] and got["times"] == {}
            assert got["scenes"][:len(fallback)] == [s for s in fallback if s in expected]
        if p == []:
            assert not got["failed"] and got["missing"] == [] and set(got["times"]) == expected


def test_fuzz_align():
    rng = random.Random(4)
    for _ in range(ROUNDS):
        tids = [f"L-{i:03d}" for i in range(1, rng.randint(1, 4) + 1)]
        members = {t: {f"S-{n * 10 + j:04d}" for j in range(rng.randint(0, 3))} for n, t in enumerate(tids, 1)}
        main = rng.choice(tids)
        thread_ids = set(tids)
        threads = [{"id": t, "offset": 0 if t == main else rng.choice([1, -2.5, None, "3"])} for t in tids]
        rng.shuffle(threads)
        crosses = []
        for t in tids:
            if t != main and members[t] and members[main] and rng.random() < 0.6:
                sc, ms = rng.choice(sorted(members[t])), rng.choice(sorted(members[main]))
                crosses.append({"thread": t, "scene": sc, "main_scene": ms, "reason": "r"})
        data = noisy({"threads": threads, "intersections": crosses}, rng)

        contract(check_align, score_align, data, thread_ids, main, members)
        offsets, cross = clean_align(data, thread_ids, main, members)
        assert set(offsets) == thread_ids and offsets[main] == 0
        for v in offsets.values():
            assert v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v))
        seen = set()
        for x in cross:
            assert x["thread"] in thread_ids and x["thread"] != main
            assert x["scene"] in members[x["thread"]] and x["main_scene"] in members[main]
            assert isinstance(x["reason"], str)
            k = (x["thread"], x["scene"], x["main_scene"])
            assert k not in seen
            seen.add(k)


def test_fuzz_gaps():
    rng = random.Random(5)
    for _ in range(ROUNDS):
        lines = {f"L-{i:03d}": [f"S-{i * 10 + j:04d}" for j in range(rng.randint(0, 4))]
                 for i in range(1, rng.randint(1, 3) + 1)}
        blocks = [s for v in lines.values() for s in v] + ["S-0999"]
        ref_scenes = set(rng.sample(blocks, rng.randint(0, min(3, len(blocks)))))
        gaps = []
        for k in range(rng.randint(0, 3) if ref_scenes else 0):
            t = rng.choice([*lines, None])
            g = {"event": f"事件{k}", "mentioned_in": rng.sample(sorted(ref_scenes), rng.randint(1, len(ref_scenes))),
                 "thread": t, "after": None, "before": None}
            order = lines[t] if t else []
            if len(order) >= 2 and rng.random() < 0.7:
                a, b = sorted(rng.sample(range(len(order)), 2))
                g["after"], g["before"] = order[a], order[b]
            gaps.append(g)
        data = noisy({"gaps": gaps}, rng)

        p = contract(check_gaps, score_gaps, data, ref_scenes, lines)
        got = clean_gaps(data, ref_scenes, lines)
        keys = set()
        for g in got:
            assert isinstance(g["event"], str) and g["event"]
            assert g["mentioned_in"] and all(s in ref_scenes for s in g["mentioned_in"])
            assert len(g["mentioned_in"]) == len(set(g["mentioned_in"]))
            t = g["thread"]
            assert t is None or t in lines
            if t is None:
                assert g["after"] is None and g["before"] is None
            else:
                for k in ("after", "before"):
                    assert g[k] is None or g[k] in lines[t]
                if g["after"] is not None and g["before"] is not None:
                    assert lines[t].index(g["after"]) < lines[t].index(g["before"])
            k = (_name_key(g["event"]), t)
            assert k not in keys
            keys.add(k)
        if p == []:
            assert len(got) == len(data["gaps"])
