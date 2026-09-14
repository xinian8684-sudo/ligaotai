from helpers import seed_book

from ligaotai.threads_input import (
    MAIN_REMOVED,
    NO_CARD,
    NO_SUMMARY,
    Item,
    card_line,
    prepare,
    segments,
    split_by_budget,
)


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


def test_group_whose_main_was_removed_goes_to_unassigned(book):
    """主版本已删除、查重还没重跑：同组其余块不能静默丢掉，进未分配并写明原因。"""
    seed_book(book, [
        {"id": "S-0001"},
        {"id": "S-0002", "removed": True},
        {"id": "S-0003"},
        {"id": "S-0004", "no_card": True},
    ], groups=[("S-0002", ["S-0002", "S-0003", "S-0004"])])
    p = prepare(book)
    assert list(p.items) == ["S-0001"]
    assert p.unassigned == [{"scene": "S-0003", "reason": MAIN_REMOVED}, {"scene": "S-0004", "reason": MAIN_REMOVED}]
    assert p.all_ids == {"S-0001", "S-0003", "S-0004"}
    assert p.all_ids == set(p.items) | {u["scene"] for u in p.unassigned}


def test_card_line_escapes_separator_and_dedupes():
    card = {"summary": "甲｜乙\n丙", "pov": "林清", "characters": [{"name": "林清"}, {"name": "清儿"}], "kind": "碎片"}
    assert card_line("S-0009", card, {("person", "清儿"): "林清"}) == "S-0009｜碎片｜甲/乙 丙｜人物：林清"


def test_card_line_drops_pronouns_from_persons():
    card = {"summary": "s", "pov": "我", "characters": [{"name": "他"}, {"name": "张三"}, {"name": "我们"}]}
    assert card_line("S-0001", card, {}) == "S-0001｜正文｜s｜人物：张三"
    assert card_line("S-0001", {"summary": "s", "pov": "我"}, {}) == "S-0001｜正文｜s"


def test_card_line_empty_summary():
    assert card_line("S-0001", {"summary": "  "}, {}) == f"S-0001｜正文｜{NO_SUMMARY}"
    assert card_line("S-0001", {}, {}) == f"S-0001｜正文｜{NO_SUMMARY}"


def test_card_line_uses_canonical_locations_and_organizations():
    card = {"summary": "s", "locations": ["京师", "青州"], "organizations": ["锦衣卫", "东厂"]}
    cmap = {("location", "京师"): "京城", ("organization", "锦衣卫"): "北镇抚司", ("person", "青州"): "某人"}
    assert card_line("S-0001", card, cmap) == "S-0001｜正文｜s｜地点：京城、青州｜组织：北镇抚司、东厂"


def test_prepare_replaces_location_names(book):
    seed_book(book, [{"id": "S-0001", "places": ["京师"]}], entities=[("location", "京城", ["京城", "京师"])])
    assert prepare(book).items["S-0001"].line.endswith("地点：京城")


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


def test_fingerprint_changes_when_main_version_changes(book):
    scenes = [{"id": "S-0001"}, {"id": "S-0002"}]
    seed_book(book, scenes, groups=[("S-0001", ["S-0001", "S-0002"])])
    fp1 = prepare(book).fingerprint
    seed_book(book, scenes, groups=[("S-0002", ["S-0001", "S-0002"])])
    assert prepare(book).fingerprint != fp1


def test_fingerprint_changes_when_a_card_goes_stale(book):
    seed_book(book, [{"id": "S-0001"}, {"id": "S-0002"}])
    fp1 = prepare(book).fingerprint
    seed_book(book, [{"id": "S-0001"}, {"id": "S-0002", "stale_card": True}])
    assert prepare(book).fingerprint != fp1


def test_fingerprint_ignores_unrelated_entity_changes(book):
    scenes = [{"id": "S-0001", "persons": ["清儿"]}]
    seed_book(book, scenes, entities=[("person", "林清", ["林清", "清儿"])])
    fp1 = prepare(book).fingerprint
    seed_book(book, scenes, entities=[
        ("person", "林清", ["林清", "清儿"]), ("person", "张三", ["张三", "三儿"]), ("location", "青州", ["青州", "青城"]),
    ])
    assert prepare(book).fingerprint == fp1


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


def test_segments_do_not_mix_files_with_the_same_natural_key():
    """a01.txt 和 a1.txt 的自然排序键一样：两个文件的块不能交错，各自的片段要绑上。"""
    items = {
        "S-0001": Item("S-0001", "a01.txt", 0, "正文", ""),
        "S-0002": Item("S-0002", "a01.txt", 1, "正文", ""),
        "S-0003": Item("S-0003", "a1.txt", 0, "正文", ""),
        "S-0004": Item("S-0004", "a1.txt", 1, "正文", ""),
    }
    ids = ["S-0001", "S-0003", "S-0002", "S-0004"]
    assert segments(ids, items) == [["S-0001", "S-0002"], ["S-0003", "S-0004"]]
    assert segments(list(reversed(ids)), items) == [["S-0001", "S-0002"], ["S-0003", "S-0004"]]


def test_prepare_then_segments_breaks_at_non_main_no_card_and_notes(book):
    """真实链路：非主版本、没卡的块、设定笔记夹在中间都会把片段断开。"""
    seed_book(book, [
        {"id": "S-0001", "index": 0},
        {"id": "S-0002", "index": 1},  # 版本组的主版本
        {"id": "S-0003", "index": 2},  # 非主版本
        {"id": "S-0004", "index": 3},
        {"id": "S-0005", "index": 4, "no_card": True},
        {"id": "S-0006", "index": 5},
        {"id": "S-0007", "index": 6, "kind": "设定笔记"},
        {"id": "S-0008", "index": 7},
    ], groups=[("S-0002", ["S-0002", "S-0003"])])
    p = prepare(book)
    assert segments(list(p.items), p.items) == [["S-0001", "S-0002"], ["S-0004"], ["S-0006"], ["S-0008"]]


def test_prepare_then_segments_across_files(book):
    seed_book(book, [
        {"id": "S-0001", "source": "b.txt", "index": 0},
        {"id": "S-0002", "source": "a.txt", "index": 0},
        {"id": "S-0003", "source": "b.txt", "index": 1},
        {"id": "S-0004", "source": "a.txt", "index": 1},
    ])
    p = prepare(book)
    assert segments(list(p.items), p.items) == [["S-0002", "S-0004"], ["S-0001", "S-0003"]]


def test_split_by_budget():
    cost = {"a": 4, "b": 4, "c": 4, "d": 20, "e": 1}
    assert split_by_budget(list(cost), cost, 10) == [["a", "b"], ["c"], ["d"], ["e"]]
    assert split_by_budget([], cost, 10) == []


def test_split_by_budget_exactly_at_budget_stays_together():
    assert split_by_budget(["a", "b"], {"a": 5, "b": 5}, 10) == [["a", "b"]]
    assert split_by_budget(["a", "b"], {"a": 5, "b": 6}, 10) == [["a"], ["b"]]
