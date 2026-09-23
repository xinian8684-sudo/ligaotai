"""骨架的分章部分（纯函数）——计划④ spec 第 7.3 节。

模型只回卷 / 章的起点序号和名字，程序核对：起点从 0 开始、严格递增、不越界、卷起点也是章起点。
大书按窗口分批（相邻窗口重叠 OVERLAP 行做衔接），合并时重叠区按中点切，各取一半。
模型怎么都不合规就用兜底切法：每章约 1 万字、每卷 10 章，章名用首块摘要前 12 字。
"""

from __future__ import annotations

OVERLAP = 10
PER_CHAPTER = 10000
PER_VOLUME = 10


def one_line(s) -> str:
    """折成一行：换行 / 多空白压成单个空格。写进骨架的标题、任务说明都要过一遍，
    不然模型回的换行（甚至夹带 Markdown 标题符号）会被原样写进导出的 md，跟真正的
    卷/章标题混在一起（M2）。"""
    return " ".join(str(s or "").split())


def render_rows(items: list[dict], info: dict) -> list[str]:
    rows = []
    for i, it in enumerate(items):
        if it["type"] == "scene":
            x = info.get(it["id"]) or {}
            rows.append(f"{i}｜{it['id']}｜{it.get('thread') or ''}｜{x.get('chars', 0)}｜{one_line(x.get('summary'))}")
        else:
            rows.append(f"{i}｜空洞｜{it.get('thread') or ''}｜0｜{one_line(it.get('event'))}")
    return rows


def _starts(lst, what: str) -> tuple[list[int], list[str]]:
    if not isinstance(lst, list) or not lst:
        return [], [f"要有非空的 {what} 列表"]
    starts, problems = [], []
    for x in lst:
        st = x.get("start") if isinstance(x, dict) else None
        if not isinstance(st, int) or isinstance(st, bool):
            problems.append(f"{what} 里每一项都要有整数 start")
            continue
        title = x.get("title")
        # M2：原先 str(title or "").strip() 会把 ["甲"] 这种非字符串也当成「有标题」放过，
        # 写进骨架后 assemble() 直接落地就是个列表，不是真正的标题。
        if not isinstance(title, str) or not title.strip():
            problems.append(f"{what} 里第 {st} 行开始的那一项没有标题")
        starts.append(st)
    return starts, problems


def check_chapters(data, n: int) -> list[str]:
    if not isinstance(data, dict):
        return ['要输出 {"volumes": [...], "chapters": [...]}']
    cs, p1 = _starts(data.get("chapters"), "chapters")
    vs, p2 = _starts(data.get("volumes"), "volumes")
    problems = p1 + p2
    for what, st in (("chapters", cs), ("volumes", vs)):
        if not st:
            continue
        if st[0] != 0:
            problems.append(f"{what} 第一项的 start 必须是 0")
        if any(b <= a for a, b in zip(st, st[1:])):
            problems.append(f"{what} 的 start 要严格递增，不许重复或倒序")
        if any(x < 0 or x >= n for x in st):
            problems.append(f"{what} 的 start 要在 0 到 {n - 1} 之间")
    miss = [v for v in vs if v not in set(cs)]
    if cs and miss:
        problems.append("卷的起点必须也是某一章的起点：" + "、".join(map(str, miss)))
    return problems


def _auto_title(it: dict, info: dict) -> str:
    if it["type"] != "scene":
        return "空洞"
    return one_line((info.get(it["id"]) or {}).get("summary"))[:12] or it["id"]


def fallback_chapters(items: list[dict], info: dict, per_chapter: int = PER_CHAPTER,
                      per_volume: int = PER_VOLUME) -> dict:
    chapters, acc = [], 0
    for i, it in enumerate(items):
        if i == 0 or acc >= per_chapter:
            chapters.append({"title": _auto_title(it, info), "start": i})
            acc = 0
        if it["type"] == "scene":
            acc += (info.get(it["id"]) or {}).get("chars", 0)
    volumes = [{"title": f"第{k // per_volume + 1}卷", "start": chapters[k]["start"]}
               for k in range(0, len(chapters), per_volume)]
    return {"volumes": volumes, "chapters": chapters}


def windows(rows: list[str], budget: int, overlap: int = OVERLAP) -> list[tuple[int, int]]:
    """按字数预算切窗口 [start, end)。每个窗口至少比重叠多一行，保证一定往前走。"""
    n = len(rows)
    out: list[tuple[int, int]] = []
    s = 0
    while n:
        e, size = s, 0
        while e < n and (e == s or size + len(rows[e]) + 1 <= budget):
            size += len(rows[e]) + 1
            e += 1
        if e < n and e - s <= overlap:
            e = min(n, s + overlap + 1)
        out.append((s, e))
        if e >= n:
            break
        s = e - overlap
    return out


def merge_windows(results: list[tuple[int, int, dict]], n: int, overlap: int = OVERLAP) -> dict:
    """results：[(窗口起点, 窗口终点, 模型结果)]，结果里的 start 是窗口内行号。"""
    cuts = [0] + [s + overlap // 2 for s, _, _ in results[1:]] + [n]
    merged: dict[str, list] = {"chapters": [], "volumes": []}
    for k, (s, _, d) in enumerate(results):
        lo, hi = cuts[k], cuts[k + 1]
        for key in ("chapters", "volumes"):
            for x in d.get(key) or []:
                g = s + x["start"]
                if lo <= g < hi:
                    merged[key].append({"title": x["title"], "start": g})
    cs = [c["start"] for c in merged["chapters"]]
    vols: list[dict] = []
    for v in merged["volumes"]:
        nxt = next((c for c in cs if c >= v["start"]), None)
        if nxt is not None and (not vols or nxt > vols[-1]["start"]):
            vols.append({"title": v["title"], "start": nxt})
    return {"volumes": vols, "chapters": merged["chapters"]}


def assemble(items: list[dict], data: dict) -> list[dict]:
    cs, n = data["chapters"], len(items)
    vol_title = {v["start"]: one_line(v["title"]) for v in data["volumes"]}
    vols: list[dict] = []
    for i, c in enumerate(cs):
        s = c["start"]
        e = cs[i + 1]["start"] if i + 1 < len(cs) else n
        if s in vol_title or not vols:
            vols.append({"title": vol_title.get(s, "第1卷"), "chapters": []})
        vols[-1]["chapters"].append({"title": one_line(c["title"]), "items": [dict(it) for it in items[s:e]], "notes": []})
    return vols
