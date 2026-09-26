"""跨线时间锚定（步骤 6.4 之后，纯程序）。

对齐那一步模型给每条线一个整体偏移，只能平移、不能伸缩：一条线的线内时间估得太紧
（雪月梅 L-003 把原书第 6～45 回压进 1.5 年，主线同期过了 5 年），平移怎么都对不上。
可同一步模型还标了交汇点，其中「同一时刻」的（same_time，两处写的是同一件事）本身就是
支线某块 = 主线某块的时间锚。这里拿这些锚点把支线时间分段线性映射到主线时间：
锚点之间线性插值，第一个之前、最后一个之后按斜率 1 平移；锚点之间前后矛盾时取
「线内时间递增、主线时间不减」的最长子序列，保证线内顺序不被打乱。

映射完直接改写线内时间（全局 = 偏移 + 线内的规则不变，下游全部不用改）。模型给不出
偏移（null）的线，有锚点就用第一个锚点定偏移。「前后呼应」的交汇点（西游记「压五行山」对
「五百年后揭帖」）不当锚点。
"""
from __future__ import annotations

from typing import Any


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _t(times: dict, sid: str):
    v = times.get(sid) if isinstance(times, dict) else None
    t = v.get("t") if isinstance(v, dict) else None
    return t if _num(t) else None


def _chain(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """线内时间相同的锚点先合并（主线时间取平均），再取主线时间不减的最长子序列。"""
    merged: dict[float, list[float]] = {}
    for lt, mt in pts:
        merged.setdefault(lt, []).append(mt)
    xs = sorted((lt, sum(m) / len(m)) for lt, m in merged.items())
    n = len(xs)
    if n <= 1:
        return xs
    best = [1] * n
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if xs[j][1] <= xs[i][1] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    i = max(range(n), key=lambda k: (best[k], -k))
    out = []
    while i != -1:
        out.append(xs[i])
        i = prev[i]
    return out[::-1]


def _map(pts: list[tuple[float, float]], t: float) -> float:
    if t <= pts[0][0]:
        return pts[0][1] + (t - pts[0][0])
    if t >= pts[-1][0]:
        return pts[-1][1] + (t - pts[-1][0])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= t <= x1:
            return y0 + (y1 - y0) * (t - x0) / (x1 - x0)
    return t  # 不会走到


def anchor_times(threads: list, main: str | None, offsets: dict, intersections: list[dict]) -> dict:
    """改写非主线的 times（原地），返回新的偏移表。threads 是 ThreadDraft 列表。"""
    offsets = dict(offsets)
    by_key = {t.key: t for t in threads}
    if main is None or main not in by_key:
        return offsets
    main_times = by_key[main].times
    anchors: dict[str, list[tuple[float, float]]] = {}
    for x in intersections or []:
        if not isinstance(x, dict) or x.get("same_time") is not True:
            continue
        t = by_key.get(x.get("thread"))
        if t is None or t.key == main:
            continue
        lt, mt = _t(t.times, x.get("scene")), _t(main_times, x.get("main_scene"))
        if lt is not None and mt is not None:
            anchors.setdefault(t.key, []).append((float(lt), float(mt)))
    for key, raw in anchors.items():
        pts = _chain(raw)
        t = by_key[key]
        off = offsets.get(key)
        if not _num(off):
            off = pts[0][1] - pts[0][0]
            offsets[key] = off
        for sid, v in t.times.items():
            lt = _t(t.times, sid)
            if lt is not None:
                v["t"] = round(_map(pts, float(lt)) - off, 4)
    return offsets
