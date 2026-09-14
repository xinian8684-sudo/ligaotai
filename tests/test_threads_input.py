from helpers import seed_book

from ligaotai.threads_input import NO_CARD, card_line, prepare


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
