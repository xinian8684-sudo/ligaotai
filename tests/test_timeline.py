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


from ligaotai.timeline import ref_suspects


def _rcards(spec):
    """spec: {sid: (persons, refs, summary)}"""
    return {s: {"id": s, "card": {"characters": [{"name": n} for n in p], "facts": [],
                                  "refs_elsewhere": list(r), "summary": sm}}
            for s, (p, r, sm) in spec.items()}


def test_C嫌疑_候选按共同人物数排_同分同线优先_只问候选里有排在后面的():
    seq = ["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"]
    pos = {s: i for i, s in enumerate(seq)}
    line = {"S-0001": "L-001", "S-0002": "L-001", "S-0003": "L-002", "S-0004": "L-001", "S-0005": "L-002"}
    cards = _rcards({
        "S-0001": (["甲"], [], "一"),
        "S-0002": (["甲", "乙"], ["那日比箭之事"], "二"),
        "S-0003": (["甲", "乙"], [], "三"),
        "S-0004": (["甲"], [], "四"),
        "S-0005": (["丙"], ["只有丙"], "五"),  # 没有共同人物的候选 → 跳过
    })
    asks, no_cand, no_later = ref_suspects(seq, pos, cards, {}, line)
    assert len(asks) == 1
    a = asks[0]
    assert (a["scene"], a["ref"]) == ("S-0002", "那日比箭之事")
    # S-0003 共同人物 2 个排第一；S-0001、S-0004 各 1 个，同线（L-001）都同线，按跟 S-0002 的距离：S-0001、S-0004 都距 1，再按位置
    assert a["candidates"] == ["S-0003", "S-0001", "S-0004"]
    assert (no_cand, no_later) == (1, 0)


def test_C嫌疑_候选全在前面的不问():
    seq = ["S-0001", "S-0002"]
    pos = {"S-0001": 0, "S-0002": 1}
    cards = _rcards({"S-0001": (["甲"], [], "一"), "S-0002": (["甲"], ["前事"], "二")})
    asks, no_cand, no_later = ref_suspects(seq, pos, cards, {}, {})
    assert asks == [] and (no_cand, no_later) == (0, 1)


def test_C嫌疑_候选最多8个():
    seq = [f"S-{i:04d}" for i in range(1, 13)]
    pos = {s: i for i, s in enumerate(seq)}
    spec = {s: (["甲"], [], s) for s in seq}
    spec["S-0001"] = (["甲"], ["某事"], "一")
    asks, _, _ = ref_suspects(seq, pos, _rcards(spec), {}, {})
    assert len(asks[0]["candidates"]) == 8


from ligaotai.timeline import name_snippets


def test_摘录_按任一叫法找_最多3处_前后带一点上下文_不重叠():
    text = "開頭。劉公道：你來了。中間很多字" + "。" * 60 + "劉芳笑了。又過了很久" + "。" * 60 + "劉公走了。" + "。" * 60 + "劉公又來。"
    got = name_snippets(text, ["劉芳", "劉公"], width=6, limit=3)
    assert len(got) == 3
    assert "劉公道" in got[0] and "劉芳笑了" in got[1] and "劉公走了" in got[2]


def test_摘录_找不到就给开头一段():
    assert name_snippets("完全沒有這個人的一段話。", ["甲"], width=4, limit=3) == ["完全沒有這個人的一段話。"[:40]]


from ligaotai.timeline import assemble, conflict_sig


def _c(kind, scenes, who=None, ref=None):
    return {"kind": kind, "who": who, "ref": ref, "scenes": scenes, "pos": [0, 1], "quotes": ["a", "b"],
            "reason": "r", "status": "在场" if kind == "A" else ""}


def test_签名只看类型_两场_人名或回指():
    a = conflict_sig(_c("A", ["S-0001", "S-0002"], who="甲"))
    assert a == conflict_sig({**_c("A", ["S-0001", "S-0002"], who="甲"), "reason": "别的说法", "pos": [5, 9]})
    assert a != conflict_sig(_c("A", ["S-0001", "S-0003"], who="甲"))
    assert a != conflict_sig(_c("C", ["S-0001", "S-0002"], ref="甲"))


def test_编号按签名沿用_新的接着编_裁决跟着签名走_消失的丢掉():
    old = {"next_id": 3, "conflicts": [
        {**_c("A", ["S-0001", "S-0002"], who="甲"), "id": "T-001",
         "sig": conflict_sig(_c("A", ["S-0001", "S-0002"], who="甲")),
         "verdict": {"kind": "order_error", "at": "x"}},
        {**_c("C", ["S-0003", "S-0004"], ref="某事"), "id": "T-002",
         "sig": conflict_sig(_c("C", ["S-0003", "S-0004"], ref="某事")),
         "verdict": {"kind": "ignore", "at": "x"}},
    ]}
    new = [_c("C", ["S-0005", "S-0006"], ref="新事"), _c("A", ["S-0001", "S-0002"], who="甲")]
    got = assemble(new, old)
    assert [(c["id"], c["verdict"]) for c in got["conflicts"]] == [
        ("T-003", None), ("T-001", {"kind": "order_error", "at": "x"})]
    assert got["next_id"] == 4
    assert {e["sig"]: e["id"] for e in got["id_registry"]}[conflict_sig(_c("C", ["S-0003", "S-0004"], ref="某事"))] == "T-002"


def test_旧文件坏了当空的():
    got = assemble([_c("A", ["S-0001", "S-0002"], who="甲")], {"conflicts": "坏了", "next_id": "x"})
    assert got["conflicts"][0]["id"] == "T-001" and got["next_id"] == 2


from ligaotai.timeline import input_fingerprint


def test_指纹_顺序或卡或规范名变了就变(book):
    _seed(book, [("S-0001", ["甲"], ["某事"], [], "x"), ("S-0002", ["甲"], [], [], "y")])
    _threads(book, [{"id": "L-001", "offset": 0, "scenes": ["S-0001", "S-0002"],
                     "times": {"S-0001": {"t": 0}, "S-0002": {"t": 1}}}])
    f0 = input_fingerprint(book)
    assert input_fingerprint(book) == f0
    _threads(book, [{"id": "L-001", "offset": 0, "scenes": ["S-0002", "S-0001"],
                     "times": {"S-0001": {"t": 1}, "S-0002": {"t": 0}}}])
    f1 = input_fingerprint(book)
    assert f1 != f0
    from ligaotai.cards import card_path
    from ligaotai.fsutil import read_json
    rec = read_json(card_path(book, "S-0001"))
    rec["card"]["refs_elsewhere"] = ["另一件事"]
    write_json(card_path(book, "S-0001"), rec)
    assert input_fingerprint(book) != f1
