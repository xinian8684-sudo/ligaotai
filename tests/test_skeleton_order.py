import json
from pathlib import Path

from ligaotai.skeleton_order import build_sequence, insert_holes, notes_for

FIX = Path(__file__).resolve().parents[1] / "web" / "src" / "components" / "__fixtures__"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _cut(*tids):
    return {t: {"col": "cut", "merge_into": None} for t in tids}


def test_雪月梅_全留_交织顺序():
    th = _load("xueyuemei-threads.json")
    seq, unplaced = build_sequence(th, {}, set())
    assert len(seq) == 100
    assert unplaced == [{"id": "S-0084", "thread": unplaced[0]["thread"], "why": "no_time"}]
    assert [x["id"] for x in seq[:10]] == ["S-0086", "S-0001", "S-0012", "S-0006", "S-0022",
                                           "S-0071", "S-0090", "S-0087", "S-0074", "S-0023"]
    assert [x["thread"] for x in seq[:4]] == ["L-002", "L-001", "L-002", "L-003"]
    assert [x["id"] for x in seq[-3:]] == ["S-0129", "S-0130", "S-0091"]


def test_雪月梅_空洞定位():
    th = _load("xueyuemei-threads.json")
    seq, _ = build_sequence(th, {}, set())
    items, holes_unplaced = insert_holes(seq, th["gaps"], {})
    placed = [i for i in items if i["type"] == "hole"]
    assert len(placed) == 75 and len(holes_unplaced) == 6
    assert all(h["why"] == "no_anchor" for h in holes_unplaced)
    ids = [h["id"] for h in placed] + [h["id"] for h in holes_unplaced]
    assert ids == [f"H-{i:03d}" for i in range(1, 82)]


def test_雪月梅_砍掉L002():
    th = _load("xueyuemei-threads.json")
    seq, _ = build_sequence(th, _cut("L-002"), set())
    assert len(seq) == 92 and all(x["thread"] != "L-002" for x in seq)
    items, holes_unplaced = insert_holes(seq, th["gaps"], _cut("L-002"))
    placed = [i for i in items if i["type"] == "hole"]
    assert len(placed) == 68 and len(holes_unplaced) == 6
    assert all(h["thread"] != "L-002" for h in placed + holes_unplaced)


def test_西游记_同一时刻同一条线按线内顺序():
    th = _load("xiyouji-threads.json")
    seq, unplaced = build_sequence(th, {}, set())
    assert len(seq) == 238 and unplaced == []
    assert [x["id"] for x in seq[:2]] == ["S-0142", "S-0143"]
    items, holes_unplaced = insert_holes(seq, th["gaps"], {})
    assert sum(1 for i in items if i["type"] == "hole") == 42 and holes_unplaced == []


def _mini():
    return {
        "main_thread": "L-001",
        "threads": [
            {"id": "L-001", "scenes": ["S-0001", "S-0002", "S-0003"], "offset": 0,
             "times": {"S-0001": {"t": 0}, "S-0002": {"t": 2}, "S-0003": {"t": None}}},
            {"id": "L-002", "scenes": ["S-0004", "S-0005"], "offset": 1,
             "times": {"S-0004": {"t": 0}, "S-0005": {"t": 5}}},
            {"id": "L-003", "scenes": ["S-0006"], "offset": None, "times": {"S-0006": {"t": 0}}},
        ],
        "unassigned": [{"scene": "S-0007", "reason": "x"}],
        "intersections": [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "r"}],
    }


def test_排不进时间轴的三种原因_非主版本不出现():
    seq, unplaced = build_sequence(_mini(), {}, {"S-0005"})
    assert [x["id"] for x in seq] == ["S-0001", "S-0004", "S-0002"]
    assert [(u["id"], u["why"]) for u in unplaced] == [
        ("S-0003", "no_time"), ("S-0006", "unaligned_thread"), ("S-0007", "unassigned")]


def test_空洞_after优先_都没有就进未定位_同锚点保持缺口顺序():
    seq, _ = build_sequence(_mini(), {}, set())
    gaps = [
        {"id": "Q-001", "thread": "L-001", "after": "S-0001", "before": "S-0002", "event": "甲", "mentioned_in": []},
        {"id": "Q-002", "thread": "L-001", "after": None, "before": "S-0002", "event": "乙", "mentioned_in": ["S-0001"]},
        {"id": "Q-003", "thread": "L-001", "after": "S-0001", "before": None, "event": "丙", "mentioned_in": []},
        {"id": "Q-004", "thread": None, "after": "S-0099", "before": None, "event": "丁", "mentioned_in": []},
    ]
    items, un = insert_holes(seq, gaps, {})
    assert [(i["type"], i.get("gap") or i["id"]) for i in items] == [
        ("scene", "S-0001"), ("hole", "Q-001"), ("hole", "Q-003"), ("scene", "S-0004"),
        ("hole", "Q-002"), ("scene", "S-0002"), ("scene", "S-0005")]
    assert [(h["gap"], h["why"]) for h in un] == [("Q-004", "no_anchor")]
    assert items[1]["event"] == "甲" and items[4]["mentioned_in"] == ["S-0001"]


def test_版本组换主版本_替换成组里当前主版本_而不是丢整组():
    # M3：作者把 S-0002/S-0006 这组的主版本从 S-0002 改成 S-0006，S-0006 本身不在任何线的
    # scenes 列表里（归线的时候还没这回事）。换主版本后，S-0002 原来的位置（t=1）应该
    # 变成 S-0006，而不是两个都从书里消失。
    th = {
        "main_thread": "L-001",
        "threads": [
            {"id": "L-001", "scenes": ["S-0001", "S-0002", "S-0003"], "offset": 0,
             "times": {"S-0001": {"t": 0}, "S-0002": {"t": 1}, "S-0003": {"t": 2}}},
        ],
        "unassigned": [],
    }
    seq, unplaced = build_sequence(th, {}, set(), {"S-0002": "S-0006"})
    assert [x["id"] for x in seq] == ["S-0001", "S-0006", "S-0003"]
    assert unplaced == []


def test_同一个主版本只出现一次_不管是原有的还是替换来的():
    th = {
        "main_thread": "L-001",
        "threads": [
            {"id": "L-001", "scenes": ["S-0001", "S-0002"], "offset": 0,
             "times": {"S-0001": {"t": 0}, "S-0002": {"t": 1}}},
            {"id": "L-002", "scenes": ["S-0006"], "offset": 0, "times": {"S-0006": {"t": 2}}},
        ],
        "unassigned": [],
    }
    seq, unplaced = build_sequence(th, {}, set(), {"S-0002": "S-0006"})
    assert [x["id"] for x in seq] == ["S-0001", "S-0006"]
    assert unplaced == []


def test_版本组_unassigned里的非主版本也换成主版本():
    th = {"main_thread": None, "threads": [], "unassigned": [{"scene": "S-0002", "reason": "x"}]}
    seq, unplaced = build_sequence(th, {}, set(), {"S-0002": "S-0006"})
    assert seq == []
    assert unplaced == [{"id": "S-0006", "thread": None, "why": "unassigned"}]


def test_章节备注():
    th = _mini()
    items = [{"type": "scene", "id": "S-0002", "thread": "L-001"},
             {"type": "scene", "id": "S-0004", "thread": "L-002"},
             {"type": "hole", "id": "H-001", "thread": "L-001"}]
    cols = {"L-001": {"col": "keep", "merge_into": None}, "L-002": {"col": "merge", "merge_into": "L-001"}}
    assert notes_for(items, cols, th) == [{"kind": "merge", "thread": "L-002", "into": "L-001"}]
    cols["L-002"] = {"col": "cut", "merge_into": None}
    assert notes_for(items[:1], cols, th) == [{"kind": "cut_crossing", "thread": "L-002", "scene": "S-0002"}]
    assert notes_for(items[:1], {}, th) == [{"kind": "undecided", "thread": "L-001"}]


def test_有全书穿插顺序就按它排_进不进时间轴规则不变():
    """global_order 把 L-002 整条排到 L-001 前面：进时间轴的四块按它排成 S-0004、S-0005、S-0001、S-0002；
    S-0003（没时间）、S-0006（线没对齐）照旧进未定位——哪些块进正文不因为有了穿插顺序而变。"""
    th = {**_mini(), "global_order": ["S-0004", "S-0005", "S-0006", "S-0001", "S-0002", "S-0003"]}
    seq, unplaced = build_sequence(th, {}, set())
    assert [x["id"] for x in seq] == ["S-0004", "S-0005", "S-0001", "S-0002"]
    assert [(u["id"], u["why"]) for u in unplaced] == [
        ("S-0003", "no_time"), ("S-0006", "unaligned_thread"), ("S-0007", "unassigned")]


def test_穿插顺序跟现在的线对不上就退回按时间排():
    """作者把 L-001 的线内顺序调过了（存的 global_order 里还是旧顺序 S-0002 在 S-0001 前）→ 不用它。
    按时间：S-0001(0)、S-0004(1)、S-0002(2)、S-0005(6)。"""
    th = {**_mini(), "global_order": ["S-0004", "S-0005", "S-0006", "S-0002", "S-0001", "S-0003"]}
    seq, _ = build_sequence(th, {}, set())
    assert [x["id"] for x in seq] == ["S-0001", "S-0004", "S-0002", "S-0005"]
