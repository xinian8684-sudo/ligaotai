"""步骤 7 每次模型调用的输入准备。

「开放的伏笔」先由程序算（这条线埋了、全书没回收的），再交模型润色成句——
先程序后模型，避免模型漏（spec 第 4 节）。
"""

from __future__ import annotations

import re
from pathlib import Path

from .facts import FactRow
from .threads_input import card_line

_LOOSE = re.compile(r"[\s\W_的了着过之其此]+")


def _loose(s: str) -> str:
    """去掉标点和几个常见虚词，用来判断两句伏笔说的是不是同一件事。"""
    return _LOOSE.sub("", s or "")


def open_hooks(scenes: list[str], cards: dict[str, dict], all_resolved: set[str],
               closed: set[tuple[str, str]] | None = None,
               same: dict[tuple[str, str], int] | None = None) -> list[dict]:
    """这条线埋下、但全书 hooks_resolved 里没有语义相近项的伏笔。

    `all_resolved` 是调用方算好的全书 hooks_resolved 集合（不是只看这条线），
    因为一个伏笔可能在另一条线的场景里被回收。
    `closed`：伏笔配对（hooks_pair）配出来、后文已交代的 (场景, 原话)，这些也不算开放。
    `same`：(场景, 原话) → 组号，同一个悬念的几种说法只列第一条，scenes 里记上这条线里全部出处。"""
    resolved = {_loose(r) for r in all_resolved}
    out, seen, by_group = [], set(), {}
    for sid in scenes:
        for h in (cards.get(sid) or {}).get("hooks_planted") or []:
            key = _loose(h)
            if not key or key in resolved or key in seen or (closed and (sid, h.strip()) in closed):
                continue
            seen.add(key)
            g = (same or {}).get((sid, h.strip()))
            if g is not None and g in by_group:
                if sid not in by_group[g]["scenes"]:
                    by_group[g]["scenes"].append(sid)
                continue
            out.append({"hook": h, "scene": sid, "scenes": [sid]})
            if g is not None:
                by_group[g] = out[-1]
    return out


def _time_bit(sid: str, times: dict[str, dict], unit: str) -> str:
    info = times.get(sid) or {}
    if info.get("t") is None:
        return ""
    conf = info.get("conf") or ""
    return f"（故事时间约 {info['t']}{unit}" + (f"，把握{conf}" if conf else "") + "）"


def thread_input(thread: dict, cards: dict[str, dict], cmap: dict, gaps: list[dict],
                 times: dict[str, dict], unit: str, closed: set[tuple[str, str]] | None = None,
                 same: dict[tuple[str, str], int] | None = None) -> str:
    """一条线的输入：按线内顺序的卡片行 + 断点 + 这条线的缺口 + 开放的伏笔。

    `cards` 传全书的卡片（不只是这条线的），因为 open_hooks 判断伏笔是否回收要看全书。
    `thread['world']` 写进正文第一行——线换了所属世界，这里的文本就会变（配合渲染文本
    做签名，换世界档案会自动被标过期，不用额外维护一个「世界」字段的签名）。"""
    p = thread_parts(thread, cards, cmap, gaps, times, unit, closed, same)
    lines = [p["head"], "", "## 按顺序的场景", *p["rows"]]
    lines += ["", "## 写到哪", *p["end"]]
    lines += ["", "## 缺口（提到过、但书里找不到对应场景的事件）", *(p["gaps"] or ["（没有）"])]
    lines += ["", "## 埋了还没回收的伏笔（程序算的，照着写就行，别自己另找）", *(p["hooks"] or ["（没有）"])]
    return "\n".join(lines)


def thread_parts(thread: dict, cards: dict[str, dict], cmap: dict, gaps: list[dict],
                 times: dict[str, dict], unit: str, closed: set[tuple[str, str]] | None = None,
                 same: dict[tuple[str, str], int] | None = None) -> dict:
    """thread_input 的各块：head 第一行、rows 场景行、end 写到哪、gaps 缺口行、hooks 伏笔行（后两样没有时是空列表）。
    长线分段写档案（write_long_thread）也用它。"""
    scenes = list(thread.get("scenes") or [])
    rows = [card_line(sid, cards[sid], cmap) + _time_bit(sid, times, unit) for sid in scenes if cards.get(sid)]
    end = thread.get("end") or {}
    gap_rows = []
    for g in gaps:
        where = "、".join(f"[{s}]" for s in (g.get("mentioned_in") or []))
        span = "".join([f"在 [{g['after']}] 之后" if g.get("after") else "",
                        f"、[{g['before']}] 之前" if g.get("before") else ""])
        gap_rows.append(f"- {g.get('event','')}：提到于 {where}{('，位置大约' + span) if span else ''}")
    hooks = open_hooks(scenes, cards, {r for c in cards.values() for r in (c.get("hooks_resolved") or [])}, closed, same)
    return {
        "head": f"线编号：{thread.get('id','')}　线名：{thread.get('name','')}　所属世界：{thread.get('world','')}",
        "rows": rows,
        "end": [f"状态：{end.get('state','待定')}　最后一块：[{end.get('last','')}]",
                f"断点说明：{end.get('note','') or '（没有）'}"],
        "gaps": gap_rows,
        "hooks": [f"- {h['hook']}：埋于 [{','.join(h['scenes'])}]" for h in hooks],
    }


def split_rows(rows: list[str], max_chars: int) -> list[list[str]]:
    """按顺序切段，每段字数（含换行）不超过 max_chars；单独一行就超的自成一段。"""
    out: list[list[str]] = []
    total = 0
    for r in rows:
        n = len(r) + 1
        if out and total + n <= max_chars:
            out[-1].append(r)
            total += n
        else:
            out.append([r])
            total = n
    return out


def thread_part_input(head: str, rows: list[str], k: int, n: int) -> str:
    return "\n".join([head, "", f"## 按顺序的场景（全线太长，这是第 {k} 段，共 {n} 段）", *rows])


def thread_merge_input(p: dict, bodies: list[str]) -> str:
    lines = [p["head"], "", "## 各段档案（按先后）"]
    for k, b in enumerate(bodies, 1):
        lines += [f"### 第 {k} 段", b.strip(), ""]
    lines += ["## 写到哪", *p["end"]]
    return "\n".join(lines)


def thread_tail(p: dict) -> str:
    """长线档案的「缺口」「开放的伏笔」两节：列表本来就是程序算的，由程序照着写（全本斗破主线 6898 条伏笔，
    让模型照抄写不完）。格式跟 archive_thread 模板一致。"""
    gaps = p["gaps"] or ["（没有）"]
    hooks = [f"{h}，至今没回收" for h in p["hooks"]] or ["（没有）"]
    return "\n".join(["## 缺口", *gaps, "", "## 开放的伏笔", *hooks])


def world_input(world: dict, rows: list[FactRow], notes: list[dict],
                threads: list[dict]) -> str:
    """一个世界的输入：这个世界所有 facts（含「其他」类，spec 第 5 节）+ 设定笔记原文 + 有哪几条线。

    `threads` 传这个世界下的线列表——线搬到别的世界后，两边的 `threads` 都会变，
    渲染文本跟着变，签名自然跟着变。`notes` 是调用方已经把 `world['notes']`
    里的场景编号解析成 {"id", "text"} 之后的结果，这里只管渲染。"""
    p = world_parts(world, rows, notes, threads)
    lines = [*p["head"], "", "## 设定（每条带出处编号）"]
    for attr, groups in p["attrs"]:
        lines.append(f"### {attr}")
        lines += [ln for g in groups for ln in g]
    if p["notes"]:
        lines += ["", "## 这个世界下的设定笔记原文", *p["notes"]]
    return "\n".join(lines)


def world_parts(world: dict, rows: list[FactRow], notes: list[dict], threads: list[dict]) -> dict:
    """world_input 的各块：head 开头几行、attrs [(属性, [同一主语的几行, ...])]、notes 笔记行。"""
    head = [f"世界编号：{world.get('id','')}　世界名：{world.get('name','')}",
            f"判定依据：{world.get('reason','')}", "", "## 这个世界下的线"]
    head += [f"- {t.get('id','')} {t.get('name','')}" for t in threads] or ["（没有）"]
    by_attr: dict[str, list[FactRow]] = {}
    for r in rows:
        by_attr.setdefault(r.attribute, []).append(r)
    attrs = []
    for attr in sorted(by_attr):
        groups: dict[str, list[str]] = {}
        for r in sorted(by_attr[attr], key=lambda r: (r.subject, r.scene)):
            groups.setdefault(r.subject, []).append(f"- {r.subject}：{r.value}　[{r.scene}]　原文「{r.quote}」")
        attrs.append((attr, list(groups.values())))
    return {"head": head, "attrs": attrs, "notes": [f"[{n['id']}] {n.get('text','')}" for n in notes]}


def world_batches(p: dict, max_chars: int) -> list[str]:
    """长世界分批写设定集：按属性、再按主语装批，同一主语同一属性的几行不拆开（「多个说法」要在一批里看全）。
    笔记原文放第一批。每批都带开头几行，模型照模板写出完整的小设定集，再由 merge_world_bodies 合并。"""
    head = "\n".join([*p["head"], "", "## 设定（每条带出处编号）"])
    batches: list[list[str]] = []
    size = max_chars  # 让第一组就开新批
    for attr, groups in p["attrs"]:
        cur_attr = None
        for g in groups:
            n = sum(len(x) + 1 for x in g)
            if batches and size + n <= max_chars:
                if cur_attr != attr:
                    batches[-1].append(f"### {attr}")
                    size += len(attr) + 5
                    cur_attr = attr
                batches[-1] += g
                size += n
            else:
                batches.append([f"### {attr}", *g])
                size = len(head) + len(attr) + 5 + n
                cur_attr = attr
    if not batches:
        batches = [[]]
    out = ["\n".join([head, *b]) for b in batches]
    if p["notes"]:
        out[0] += "\n\n## 这个世界下的设定笔记原文\n" + "\n".join(p["notes"])
    return out


def merge_world_bodies(bodies: list[str]) -> str:
    """几批设定集合成一份：开头（第一个「## 」之前）用第一批的，同名小节按批的先后接起来。"""
    head, order, sections = "", [], {}
    for k, b in enumerate(bodies):
        parts = re.split(r"(?m)^(?=## )", b.strip())
        if k == 0 and parts and not parts[0].startswith("## "):
            head = parts[0].strip()
        for sec in parts:
            if not sec.startswith("## "):
                continue
            title, _, rest = sec.partition("\n")
            if title not in sections:
                order.append(title)
                sections[title] = []
            if rest.strip():
                sections[title].append(rest.strip())
    out = [head] if head else []
    out += [title + "\n" + "\n".join(sections[title]) for title in order]
    return "\n\n".join(out) + "\n"


def map_input(world_files: list[Path], thread_files: list[Path], contradictions: list[dict],
              gaps: list[dict], ends: list[dict], intersections: list[dict] | None = None) -> str:
    """地图的输入是**档案正文**（不是场景卡），所以装得下（spec 7.3）。
    矛盾只带严重的——地图是给人看全局的，轻微的留在 矛盾.json 里。

    这份渲染结果就是「真正送给模型的地图输入文本」：archive.map_sig 直接哈希它，
    严重矛盾清单、缺口总览、各条线写到哪、线之间的交汇只要变了，签名就跟着变（C 组审查「必须修 5」：
    这三样以前不在 map_sig 里，档案文件没变时地图会停在旧清单）。"""
    lines = ["# 全部世界设定集"]
    for p in sorted(world_files, key=lambda p: p.name):
        lines.append(p.read_text(encoding="utf-8"))
    lines.append("# 全部支线档案")
    for p in sorted(thread_files, key=lambda p: p.name):
        lines.append(p.read_text(encoding="utf-8"))

    lines.append("# 严重矛盾")
    bad = [c for c in contradictions if c.get("status") == "真矛盾" and c.get("level") == "严重"]
    lines += [f"- {c['id']} {c.get('subject','')}·{c.get('attribute','')}：{c.get('reason','')}"
              for c in bad] or ["（没有）"]

    lines.append("# 缺口总览")
    lines += [f"- [{g.get('world','')}] {g.get('event','')}" for g in gaps] or ["（没有）"]

    lines.append("# 各条线写到哪")
    lines += [f"- {e.get('id','')} {e.get('name','')}：{e.get('state','')}，"
              f"最后一块 [{e.get('last','')}]" for e in ends] or ["（没有）"]

    # 交汇点（spec 7.3：每个世界一节写「各条线一段摘要 + 交汇点」）：来自 世界与支线.json 的
    # intersections。以前不在输入里，模型拿不到材料只能漏写或编，交汇变了地图签名也不变（DE 审查必须修5）。
    names = {e.get("id"): e.get("name", "") for e in ends}
    lines.append("# 线之间的交汇")
    lines += [f"- {c.get('thread','')} {names.get(c.get('thread'), '')} 的 [{c.get('scene','')}] "
              f"跟主线的 [{c.get('main_scene','')}] 交汇：{c.get('reason','')}"
              for c in intersections or [] if isinstance(c, dict)] or ["（没有）"]
    return "\n\n".join(lines)
