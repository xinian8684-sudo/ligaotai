"""线内排序排几遍，按多数票合并。

为什么：同一条线同样的输入排三遍，结果可以差很多（9-28 实测雪月梅 L-005 三遍 τ 0.994 /
0.897 / 0.641，L-002 四遍里两遍 1.0 两遍 0.714）。模型每次错的地方多半不一样，两两投票就能把
偶发的错投掉；按平均名次合并反而会把错拉进来（同样三遍只有 0.89），所以用多数票。
系统性的错（每遍都犯的）投不掉，那要靠别的办法。
"""

from __future__ import annotations


def consensus(orders: list[list[str]]) -> list[str]:
    """先按平均相对名次排个初稿（第一份的先后打破平局），再反复做相邻交换：
    同时排了这两块的那几份里，超过半数说后一块在前，就交换，直到不再变。
    某一份没有的块不算它的票；结果含所有份里出现过的块。"""
    orders = [o for o in orders if o]
    if not orders:
        return []
    if len(orders) == 1:
        return list(orders[0])
    ids = list(dict.fromkeys(s for o in orders for s in o))
    at = [{s: i / max(len(o) - 1, 1) for i, s in enumerate(o)} for o in orders]
    first = {s: i for i, s in enumerate(ids)}

    def mean(s: str) -> float:
        got = [p[s] for p in at if s in p]
        return sum(got) / len(got)

    out = sorted(ids, key=lambda s: (mean(s), first[s]))
    changed = True
    while changed:
        changed = False
        for i in range(len(out) - 1):
            a, b = out[i], out[i + 1]
            voters = [p for p in at if a in p and b in p]
            if sum(p[b] < p[a] for p in voters) * 2 > len(voters):
                out[i], out[i + 1] = b, a
                changed = True
    return out


def agreement(x: list[str], y: list[str]) -> float:
    """两份顺序里（共有的块）同向的块对占多少。拿来挑「跟共识最像」的那一遍的时间估计。"""
    py = {s: i for i, s in enumerate(y)}
    common = [s for s in x if s in py]
    pairs = same = 0
    for i in range(len(common)):
        for j in range(i + 1, len(common)):
            pairs += 1
            same += py[common[i]] < py[common[j]]
    return same / pairs if pairs else 1.0
