"""全书穿插（步骤 6.4 之后）：把各条线排好的场景合并成一条全书先后顺序。

为什么不用「线内时间 + 偏移」排：9-26 真书验收，雪月梅线内顺序 τ 0.985，跨线穿插只有
0.78；各线的年份是各估各的，一年以内互相对不上，拿交汇点锚定后三次真跑 0.75～0.80，
波动比改进还大。判断「这块在那块前面还是后面」比估年份容易得多，而线内顺序已经很准，
所以这一步只让模型做合并，不许动线内顺序（清理时程序强制保住）。

结果存 世界与支线.json 的 global_order（场景编号列表）。骨架排序优先用它；作者事后改了线
（移块、拆线、线内调序），它跟现在的线对不上，`usable_order` 判不可用，退回按时间排。
"""
from __future__ import annotations

from .threads_check import _Ids, _list, _obj


def _members(threads: dict[str, list[str]]) -> dict[str, str]:
    return {s: tid for tid, ss in threads.items() for s in ss}


def _read(data, threads: dict[str, list[str]]) -> tuple[list[str], list[str], list[str], list[str]]:
    """(认得出的顺序（去重）, 重复的, 编造的, 漏掉的)。"""
    owner = _members(threads)
    ids = _Ids(set(owner))
    seen: list[str] = []
    got: set[str] = set()
    dup, fake = [], []
    for x in _list(_obj(data).get("order")):
        s = ids.one(x)
        if s not in owner:
            fake.append(str(x))
        elif s in got:
            dup.append(s)
        else:
            seen.append(s)
            got.add(s)
    missing = [s for s in owner if s not in got]
    return seen, dup, fake, missing


def _broken(order: list[str], threads: dict[str, list[str]]) -> list[str]:
    """线内顺序被打乱的线。"""
    owner = _members(threads)
    bad = []
    for tid, ss in threads.items():
        got = [s for s in order if owner.get(s) == tid]
        if got != [s for s in ss if s in got]:
            bad.append(tid)
    return bad


def check_interleave(data, threads: dict[str, list[str]]) -> list[str]:
    order, dup, fake, missing = _read(data, threads)
    if not isinstance(_obj(data).get("order"), list):
        return ["要输出 {\"order\": [场景编号, ...]}"]
    problems = []
    if missing:
        problems.append("这些场景漏了，每个都要出现一次：" + "、".join(missing[:30]))
    if dup:
        problems.append("这些场景重复了：" + "、".join(dict.fromkeys(dup)))
    if fake:
        problems.append("这些编号不在输入里：" + "、".join(fake[:30]))
    bad = _broken(order, threads)
    if bad:
        problems.append("这些线内部的先后被打乱了，同一条线的场景要保持输入里的顺序：" + "、".join(bad))
    return problems


def score_interleave(data, threads: dict[str, list[str]]) -> int:
    order, dup, fake, missing = _read(data, threads)
    return len(dup) + len(fake) + 3 * len(missing) + 5 * len(_broken(order, threads))


def clean_interleave(data, threads: dict[str, list[str]]) -> list[str]:
    """修成合法的合并：每条线占住模型给它的那些位置，但按线内原顺序依次填进去；
    漏掉的块紧跟在同线前一块后面（线首漏了就放在同线第一块前面，整条线都漏了就接在最后）。"""
    order, _, _, _ = _read(data, threads)
    owner = _members(threads)
    slots = {tid: iter([s for s in ss if s in order]) for tid, ss in threads.items()}
    fixed = [next(slots[owner[s]]) for s in order]
    for tid, ss in threads.items():
        for i, s in enumerate(ss):
            if s in fixed:
                continue
            prev = next((p for p in reversed(ss[:i]) if p in fixed), None)
            if prev is not None:
                fixed.insert(fixed.index(prev) + 1, s)
                continue
            nxt = next((n for n in ss[i + 1:] if n in fixed), None)
            if nxt is not None:
                fixed.insert(fixed.index(nxt), s)
            else:
                fixed.append(s)
    return fixed


def usable_order(order, threads: dict[str, list[str]]) -> list[str] | None:
    """存下来的 global_order 还能不能用：必须恰好覆盖这些线的全部场景、线内顺序一致。"""
    if not isinstance(order, list) or not all(isinstance(s, str) for s in order):
        return None
    owner = _members(threads)
    if len(order) != len(set(order)) or set(order) != set(owner):
        return None
    return None if _broken(order, threads) else list(order)


def mostly_there(data, threads: dict[str, list[str]], need: float = 0.8) -> bool:
    """模型自己排进来的块够不够多：大半都是程序补的，那就不算模型排的顺序，不如退回按时间排。"""
    order, _, _, _ = _read(data, threads)
    total = sum(len(ss) for ss in threads.values())
    return total > 0 and len(order) >= need * total
