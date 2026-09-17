"""步骤 7 每次模型调用的输入准备。

「开放的伏笔」先由程序算（这条线埋了、全书没回收的），再交模型润色成句——
先程序后模型，避免模型漏（spec 第 4 节）。
"""

from __future__ import annotations

import re

from .facts import FactRow
from .threads_input import card_line

_LOOSE = re.compile(r"[\s\W_的了着过之其此]+")


def _loose(s: str) -> str:
    """去掉标点和几个常见虚词，用来判断两句伏笔说的是不是同一件事。"""
    return _LOOSE.sub("", s or "")


def open_hooks(scenes: list[str], cards: dict[str, dict], all_resolved: set[str]) -> list[dict]:
    """这条线埋下、但全书 hooks_resolved 里没有语义相近项的伏笔。

    `all_resolved` 是调用方算好的全书 hooks_resolved 集合（不是只看这条线），
    因为一个伏笔可能在另一条线的场景里被回收。"""
    resolved = {_loose(r) for r in all_resolved}
    out, seen = [], set()
    for sid in scenes:
        for h in (cards.get(sid) or {}).get("hooks_planted") or []:
            key = _loose(h)
            if not key or key in resolved or key in seen:
                continue
            seen.add(key)
            out.append({"hook": h, "scene": sid})
    return out


def _time_bit(sid: str, times: dict[str, dict], unit: str) -> str:
    info = times.get(sid) or {}
    if info.get("t") is None:
        return ""
    conf = info.get("conf") or ""
    return f"（故事时间约 {info['t']}{unit}" + (f"，把握{conf}" if conf else "") + "）"


def thread_input(thread: dict, cards: dict[str, dict], cmap: dict, gaps: list[dict],
                 times: dict[str, dict], unit: str) -> str:
    """一条线的输入：按线内顺序的卡片行 + 断点 + 这条线的缺口 + 开放的伏笔。

    `cards` 传全书的卡片（不只是这条线的），因为 open_hooks 判断伏笔是否回收要看全书。
    `thread['world']` 写进正文第一行——线换了所属世界，这里的文本就会变（配合渲染文本
    做签名，换世界档案会自动被标过期，不用额外维护一个「世界」字段的签名）。"""
    scenes = list(thread.get("scenes") or [])
    lines = [f"线编号：{thread.get('id','')}　线名：{thread.get('name','')}　"
             f"所属世界：{thread.get('world','')}", "", "## 按顺序的场景"]
    for sid in scenes:
        card = cards.get(sid)
        if not card:
            continue
        lines.append(card_line(sid, card, cmap) + _time_bit(sid, times, unit))

    end = thread.get("end") or {}
    lines += ["", "## 写到哪",
              f"状态：{end.get('state','待定')}　最后一块：[{end.get('last','')}]",
              f"断点说明：{end.get('note','') or '（没有）'}"]

    lines += ["", "## 缺口（提到过、但书里找不到对应场景的事件）"]
    if gaps:
        for g in gaps:
            where = "、".join(f"[{s}]" for s in (g.get("mentioned_in") or []))
            span = "".join([f"在 [{g['after']}] 之后" if g.get("after") else "",
                            f"、[{g['before']}] 之前" if g.get("before") else ""])
            lines.append(f"- {g.get('event','')}：提到于 {where}{('，位置大约' + span) if span else ''}")
    else:
        lines.append("（没有）")

    hooks = open_hooks(scenes, cards, {r for c in cards.values() for r in (c.get("hooks_resolved") or [])})
    lines += ["", "## 埋了还没回收的伏笔（程序算的，照着写就行，别自己另找）"]
    lines += [f"- {h['hook']}：埋于 [{h['scene']}]" for h in hooks] or ["（没有）"]
    return "\n".join(lines)


def world_input(world: dict, rows: list[FactRow], notes: list[dict],
                threads: list[dict]) -> str:
    """一个世界的输入：这个世界所有 facts（含「其他」类，spec 第 5 节）+ 设定笔记原文 + 有哪几条线。

    `threads` 传这个世界下的线列表——线搬到别的世界后，两边的 `threads` 都会变，
    渲染文本跟着变，签名自然跟着变。`notes` 是调用方已经把 `world['notes']`
    里的场景编号解析成 {"id", "text"} 之后的结果，这里只管渲染。"""
    lines = [f"世界编号：{world.get('id','')}　世界名：{world.get('name','')}",
             f"判定依据：{world.get('reason','')}", "", "## 这个世界下的线"]
    lines += [f"- {t.get('id','')} {t.get('name','')}" for t in threads] or ["（没有）"]

    lines += ["", "## 设定（每条带出处编号）"]
    by_attr: dict[str, list[FactRow]] = {}
    for r in rows:
        by_attr.setdefault(r.attribute, []).append(r)
    for attr in sorted(by_attr):
        lines.append(f"### {attr}")
        for r in sorted(by_attr[attr], key=lambda r: (r.subject, r.scene)):
            lines.append(f"- {r.subject}：{r.value}　[{r.scene}]　原文「{r.quote}」")

    if notes:
        lines += ["", "## 这个世界下的设定笔记原文"]
        for n in notes:
            lines.append(f"[{n['id']}] {n.get('text','')}")
    return "\n".join(lines)
