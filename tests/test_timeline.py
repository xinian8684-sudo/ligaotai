def test_书有时间冲突的两个路径(book):
    assert book.timeline_path == book.root / "时间冲突.json"
    assert book.timeline_cache_path == book.root / "时间冲突缓存.json"


from ligaotai.fsutil import write_json
from ligaotai.timeline import story_order


def _threads(book, threads, global_order=None, unassigned=()):
    write_json(book.threads_path, {"threads": threads, "worlds": [], "main_thread": threads[0]["id"],
                                   "global_order": list(global_order or []), "unassigned": list(unassigned),
                                   "pending": [], "gaps": [], "intersections": []})


def _seed(book, specs):
    """specs: [(sid, persons, refs, facts, text)]。facts: [(subject, attribute, value, quote)]"""
    from helpers import seed_book
    from ligaotai.cards import card_path
    from ligaotai.fsutil import read_json
    seed_book(book, [{"id": s, "persons": p, "refs": r, "text": t} for s, p, r, _, t in specs])
    for s, _, _, facts, _ in specs:
        rec = read_json(card_path(book, s))
        rec["card"]["facts"] = [{"subject": a, "attribute": b, "value": c, "quote": q} for a, b, c, q in facts]
        write_json(card_path(book, s), rec)


def test_故事顺序按全书穿插_排不进的单独数(book):
    _seed(book, [(f"S-000{i}", [], [], [], "x") for i in range(1, 5)])
    _threads(book, [
        {"id": "L-001", "offset": 0, "scenes": ["S-0001", "S-0002"],
         "times": {"S-0001": {"t": 0}, "S-0002": {"t": 2}}},
        {"id": "L-002", "offset": 0, "scenes": ["S-0003", "S-0004"],
         "times": {"S-0003": {"t": 1}}},  # S-0004 没时间
    ], global_order=["S-0001", "S-0003", "S-0002"])
    seq, pos, unplaced = story_order(book)
    assert seq == ["S-0001", "S-0003", "S-0002"]
    assert pos == {"S-0001": 0, "S-0003": 1, "S-0002": 2}
    assert unplaced == 1
