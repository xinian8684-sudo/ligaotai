"""全书穿插（步骤 6.4 之后）：把各条线排好的场景合并成一条全书先后顺序。

为什么不用「线内时间 + 偏移」排：9-26 真书验收，雪月梅线内顺序 τ 0.985，跨线穿插只有
0.78；各线的年份是各估各的，一年以内互相对不上，拿交汇点锚定后三次真跑 0.75～0.80，
波动比改进还大。判断「这块在那块前面还是后面」比估年份容易得多，而线内顺序已经很准，
所以这一步只让模型做合并，不许动线内顺序（清理时程序强制保住）。
做法：先按（锚定后的）年份排出底稿，切成连续的小窗口（MAX_WINDOW），每个窗口让模型重新穿插。
底稿管大方向，模型管窗口里的局部先后；窗口连续，拼回去线内顺序不变，再长的书也能分段跑。

结果存 世界与支线.json 的 global_order（场景编号列表）。骨架排序优先用它；作者事后改了线
（移块、拆线、线内调序），它跟现在的线对不上，`usable_order` 判不可用，退回按时间排。
"""
from __future__ import annotations

from .fsutil import natural_key
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


# 一个窗口最多几块。9-26 雪月梅（101 块）实测跨线 τ：整本一段 0.808/0.840/0.808，
# 60 块 0.872/0.882，40 块 0.882/0.892/0.849，20 块 0.828/0.780——底稿定大方向、模型只管
# 一小段里的先后判得最准；太小看不到上下文。西游记 40、60 块都是 1.0。
MAX_WINDOW = 60


def windows(base: list[str], max_n: int | None = None) -> list[list[str]]:
    """底稿顺序切成连续的几段，段数 = ⌈N / max_n⌉，各段一样长（多出来的从前往后各分一个）。
    max_n 不给就用调用时的 MAX_WINDOW（不在定义时绑死，测试才能改小）。"""
    max_n = max_n or MAX_WINDOW
    n = len(base)
    if n == 0:
        return []
    k = -(-n // max_n)
    sizes = [n // k + (1 if i < n % k else 0) for i in range(k)]
    out, i = [], 0
    for sz in sizes:
        out.append(base[i:i + sz])
        i += sz
    return out


def time_base(lines: dict[str, list[str]], gtime: dict[str, float], main: str | None) -> list[str]:
    """按全书时间排的底稿：有时间的块按 (时间, 主线优先, 线编号, 线内位置) 排——跟骨架退回按时间排
    的规则一样；没时间的块跟在同线前一块后面（clean_interleave 的补法），保证是合法的合并。"""
    keyed = []
    for tid, ss in lines.items():
        for i, s in enumerate(ss):
            if s in gtime:
                keyed.append(((gtime[s], 0 if tid == main else 1, natural_key(tid), i), s))
    keyed.sort(key=lambda x: x[0])
    return clean_interleave({"order": [s for _, s in keyed]}, lines)


def sub_lines(window: list[str], lines: dict[str, list[str]]) -> dict[str, list[str]]:
    """窗口里每条线的块（按窗口里的顺序，也就是线内顺序）；窗口里没有块的线不列。"""
    owner = _members(lines)
    out: dict[str, list[str]] = {}
    for s in window:
        out.setdefault(owner[s], []).append(s)
    return out
