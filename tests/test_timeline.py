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


from ligaotai.timeline import is_death


def test_哪些fact算死了():
    yes = [("生死", "已死"), ("生死", "被文進刺死"), ("生死", "阵亡"), ("生死", "已歸天"),
           ("生死", "梟首傳示江浙"), ("身份", "已故封君"), ("其他", "得病身故"), ("伤病", "病故"),
           ("生死", "已去世好幾年"), ("生死", "本月十九日坐化了")]
    no = [("生死", "免死編氓"), ("生死", "被擒"), ("生死", "嚴行監禁"), ("生死", "車囚"),
          ("生死", "丁艱"), ("亲属", "母已亡"), ("身份", "亡命之徒"), ("性格", "视死如归"),
          ("生死", "幾乎死了"), ("生死", "未死")]
    for a, v in yes:
        assert is_death(a, v), (a, v)
    for a, v in no:
        assert not is_death(a, v), (a, v)


from ligaotai.timeline import death_suspects


def _cards(spec):
    """spec: {sid: (persons, facts)}，facts: [(subject, attribute, value, quote)]"""
    return {s: {"id": s, "card": {"characters": [{"name": n} for n in p],
                                  "facts": [{"subject": a, "attribute": b, "value": c, "quote": q} for a, b, c, q in f],
                                  "refs_elsewhere": []}}
            for s, (p, f) in spec.items()}


def test_A嫌疑_死后出现在人物名单里_别名归一_取最早的死亡(book):
    seq = ["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"]
    pos = {s: i for i, s in enumerate(seq)}
    cmap = {("person", "劉公"): "劉芳", ("person", "劉芳"): "劉芳"}
    cards = _cards({
        "S-0001": (["劉芳"], []),
        "S-0002": (["劉公"], [("劉公", "生死", "已死", "劉公已死多年")]),
        "S-0003": (["張三"], []),
        "S-0004": (["劉芳"], [("劉芳", "生死", "已死", "劉芳死了")]),  # 更晚的死亡记录不另算
        "S-0005": (["劉公"], []),
    })
    got, capped = death_suspects(seq, pos, cards, cmap)
    assert [(x["who"], x["death"], x["later"]) for x in got] == [
        ("劉芳", "S-0002", "S-0004"), ("劉芳", "S-0002", "S-0005")]
    assert got[0]["death_quote"] == "劉公已死多年"
    assert capped == 0


def test_A嫌疑_每人最多取离死亡最近的5场():
    seq = [f"S-{i:04d}" for i in range(1, 10)]
    pos = {s: i for i, s in enumerate(seq)}
    spec = {s: (["甲"], []) for s in seq}
    spec["S-0001"] = (["甲"], [("甲", "生死", "已死", "甲已死")])
    got, capped = death_suspects(seq, pos, _cards(spec), {})
    assert [x["later"] for x in got] == ["S-0002", "S-0003", "S-0004", "S-0005", "S-0006"]
    assert capped == 3


def test_A嫌疑_死亡场不在故事顺序里就不查():
    seq = ["S-0002"]
    pos = {"S-0002": 0}
    cards = _cards({"S-0001": (["甲"], [("甲", "生死", "已死", "q")]), "S-0002": (["甲"], [])})
    assert death_suspects(seq, pos, cards, {}) == ([], 0)
