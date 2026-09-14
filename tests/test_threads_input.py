from helpers import seed_book

from ligaotai.threads_input import NO_CARD, Item, card_line, prepare, segments, split_by_budget


def test_prepare_picks_main_versions_and_uses_canonical_names(book):
    seed_book(book, [
        {"id": "S-0001", "persons": ["清儿"], "places": ["青州"], "summary": "林清出门", "times": ["那年冬天"]},
        {"id": "S-0002", "persons": ["林清"]},
        {"id": "S-0003", "persons": ["林清"]},
        {"id": "S-0004", "no_card": True},
        {"id": "S-0005", "removed": True},
        {"id": "S-0006", "stale_card": True},
    ], entities=[("person", "林清", ["林清", "清儿"])], groups=[("S-0002", ["S-0002", "S-0003"])])
    p = prepare(book)
    assert list(p.items) == ["S-0001", "S-0002"]
    assert p.items["S-0001"].line == "S-0001｜正文｜林清出门｜人物：林清｜地点：青州｜时间线索：那年冬天"
    assert p.unassigned == [{"scene": "S-0004", "reason": NO_CARD}, {"scene": "S-0006", "reason": NO_CARD}]
    assert p.all_ids == {"S-0001", "S-0002", "S-0004", "S-0006"}


def test_card_line_escapes_separator_and_dedupes():
    card = {"summary": "甲｜乙\n丙", "pov": "林清", "characters": [{"name": "林清"}, {"name": "清儿"}], "kind": "碎片"}
    assert card_line("S-0009", card, {("person", "清儿"): "林清"}) == "S-0009｜碎片｜甲/乙 丙｜人物：林清"


def test_refs_are_kept(book):
    seed_book(book, [{"id": "S-0001", "refs": ["青州城破", "  "]}])
    assert prepare(book).items["S-0001"].refs == ["青州城破"]


def test_fingerprint_follows_what_the_model_sees(book):
    scenes = [{"id": "S-0001", "persons": ["清儿"]}]
    seed_book(book, scenes, entities=[("person", "林清", ["林清", "清儿"])])
    fp1 = prepare(book).fingerprint
    assert prepare(book).fingerprint == fp1
    seed_book(book, scenes, entities=[("person", "林小清", ["林清", "清儿"])])
    assert prepare(book).fingerprint != fp1


def test_segments_bind_adjacent_blocks_of_the_same_file():
    items = {
        "S-0001": Item("S-0001", "b.txt", 0, "正文", ""),
        "S-0002": Item("S-0002", "b.txt", 1, "碎片", ""),
        "S-0003": Item("S-0003", "b.txt", 3, "正文", ""),  # 跟前面隔了一块
        "S-0004": Item("S-0004", "a.txt", 0, "正文", ""),
        "S-0005": Item("S-0005", "a.txt", 1, "提纲", ""),  # 提纲不参与，也把前后隔开
        "S-0006": Item("S-0006", "a.txt", 2, "正文", ""),
        "S-0007": Item("S-0007", "文件10.txt", 0, "正文", ""),
        "S-0008": Item("S-0008", "文件2.txt", 0, "正文", ""),
    }
    assert segments(list(items), items) == [
        ["S-0004"], ["S-0006"], ["S-0001", "S-0002"], ["S-0003"], ["S-0008"], ["S-0007"],
    ]


def test_segments_only_use_the_given_ids():
    items = {f"S-000{i}": Item(f"S-000{i}", "a.txt", i, "正文", "") for i in range(1, 4)}
    assert segments(["S-0001", "S-0003"], items) == [["S-0001"], ["S-0003"]]


def test_split_by_budget():
    cost = {"a": 4, "b": 4, "c": 4, "d": 20, "e": 1}
    assert split_by_budget(list(cost), cost, 10) == [["a", "b"], ["c"], ["d"], ["e"]]
    assert split_by_budget([], cost, 10) == []
