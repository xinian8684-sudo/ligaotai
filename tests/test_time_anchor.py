"""跨线时间锚定：拿「同一时刻」的交汇点把支线时间分段线性映射到主线时间（9-26 真书验收后加）。
期望值都是手算的。"""
from ligaotai.threads import ThreadDraft
from ligaotai.time_anchor import anchor_times


def _t(key: str, times: dict[str, float | None]) -> ThreadDraft:
    return ThreadDraft(key=key, world="W-01", name=key, about="", scenes=list(times),
                       times={s: {"t": v, "conf": "中"} for s, v in times.items()})


def _x(thread: str, scene: str, main_scene: str, same: bool = True) -> dict:
    return {"thread": thread, "scene": scene, "main_scene": main_scene, "reason": "r", "same_time": same}


def _g(t: ThreadDraft, offsets: dict, s: str) -> float:
    return offsets[t.key] + t.times[s]["t"]


def test_两个锚点之间线性插值_最后一个锚点之后按斜率1平移():
    """雪月梅 L-003 的形状：线内 0～1.5 年，但 C 跟主线第 5 年是同一件事。
    B：0 + (5-0) × 0.8/1.1 = 3.636…；D：5 + (1.5-1.1) = 5.4。"""
    main = _t("L-001", {"M1": 0, "M2": 5})
    sub = _t("L-003", {"A": 0, "B": 0.8, "C": 1.1, "D": 1.5})
    offsets = anchor_times([main, sub], "L-001", {"L-001": 0, "L-003": 0.0},
                           [_x("L-003", "A", "M1"), _x("L-003", "C", "M2")])
    assert abs(_g(sub, offsets, "A") - 0) < 1e-6
    assert abs(_g(sub, offsets, "B") - 5 * 0.8 / 1.1) < 1e-3
    assert abs(_g(sub, offsets, "C") - 5) < 1e-6
    assert abs(_g(sub, offsets, "D") - 5.4) < 1e-6
    assert main.times["M2"]["t"] == 5 and offsets["L-001"] == 0  # 主线不动
    assert sub.times["B"]["conf"] == "中"  # 把握原样保留


def test_不是同一时刻的交汇点不当锚点():
    """西游记：「压五行山」对应「五百年后揭帖救出」，是呼应不是同一时刻，拿它锚定会把整条线拽错 500 年。"""
    main = _t("L-001", {"M1": 0.2})
    sub = _t("L-002", {"A": 372})
    offsets = anchor_times([main, sub], "L-001", {"L-001": 0, "L-002": -871.8},
                           [_x("L-002", "A", "M1", same=False)])
    assert offsets["L-002"] == -871.8
    assert sub.times["A"]["t"] == 372


def test_没有偏移的线_有一个锚点就能对上():
    """模型给不出偏移（null）的线：一个同一时刻的交汇点就够定位，偏移 = 10 - 2 = 8，线内时间不变。"""
    main = _t("L-001", {"M1": 10})
    sub = _t("L-002", {"A": 2, "B": 3})
    offsets = anchor_times([main, sub], "L-001", {"L-001": 0, "L-002": None}, [_x("L-002", "A", "M1")])
    assert offsets["L-002"] == 8
    assert sub.times["A"]["t"] == 2 and sub.times["B"]["t"] == 3


def test_锚点前后矛盾_取最长的一致子序列():
    """锚点（线内→主线）：0→1、1→9、2→2、3→3。不减的最长子序列是 0→1、2→2、3→3（长 3），
    1→9 被丢掉；线内 1 这一块插在 0→1 和 2→2 之间：1 + (2-1) × 1/2 = 1.5。"""
    main = _t("L-001", {"M1": 1, "M9": 9, "M2": 2, "M3": 3})
    sub = _t("L-002", {"A": 0, "B": 1, "C": 2, "D": 3})
    offsets = anchor_times([main, sub], "L-001", {"L-001": 0, "L-002": 0},
                           [_x("L-002", "A", "M1"), _x("L-002", "B", "M9"),
                            _x("L-002", "C", "M2"), _x("L-002", "D", "M3")])
    assert abs(_g(sub, offsets, "B") - 1.5) < 1e-6
    assert abs(_g(sub, offsets, "D") - 3) < 1e-6


def test_没时间的块和没时间的锚点都跳过():
    """线内时间是 null 的块保持 null；主线那一块没时间的交汇点不当锚点（只剩 A→M1 一个锚点 = 整体平移 +4）。"""
    main = _t("L-001", {"M1": 4, "M2": None})
    sub = _t("L-002", {"A": 0, "B": None, "C": 1})
    offsets = anchor_times([main, sub], "L-001", {"L-001": 0, "L-002": 0},
                           [_x("L-002", "A", "M1"), _x("L-002", "C", "M2")])
    assert sub.times["B"]["t"] is None
    assert abs(_g(sub, offsets, "A") - 4) < 1e-6
    assert abs(_g(sub, offsets, "C") - 5) < 1e-6


def test_线内同一时间的两个锚点取主线时间平均():
    """A 同时对上主线 2 和 4：取平均 3，整条线平移 +3。"""
    main = _t("L-001", {"M1": 2, "M2": 4})
    sub = _t("L-002", {"A": 0, "B": 1})
    offsets = anchor_times([main, sub], "L-001", {"L-001": 0, "L-002": 0},
                           [_x("L-002", "A", "M1"), _x("L-002", "A", "M2")])
    assert abs(_g(sub, offsets, "B") - 4) < 1e-6


def test_锚定不会打乱线内顺序():
    main = _t("L-001", {"M1": 0, "M2": 1, "M3": 10})
    sub = _t("L-002", {"A": 0, "B": 0.5, "C": 1, "D": 1.2, "E": 3})
    offsets = anchor_times([main, sub], "L-001", {"L-001": 0, "L-002": 0},
                           [_x("L-002", "A", "M1"), _x("L-002", "C", "M2"), _x("L-002", "D", "M3")])
    g = [_g(sub, offsets, s) for s in "ABCDE"]
    assert g == sorted(g)


def test_没有主线或主线没时间时原样返回():
    sub = _t("L-002", {"A": 0})
    offsets = anchor_times([sub], None, {"L-002": None}, [])
    assert offsets == {"L-002": None} and sub.times["A"]["t"] == 0
