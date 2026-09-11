from ligaotai.cards import Card, check_card, clean_card

TEXT = "第一章 雪夜\n林清年方十六，住在青州城外。那一年冬天，赵五来了。"
GOOD = {
    "summary": "林清在雪夜遇到赵五。",
    "pov": "林清",
    "characters": [{"name": "林清", "role": "主要"}, {"name": "赵五", "role": "次要"}],
    "locations": ["青州城外"],
    "organizations": [],
    "facts": [{"subject": "林清", "attribute": "年龄", "value": "十六", "quote": "林清年方十六"}],
    "kind": "正文",
}


def with_(**changes):
    return {**GOOD, **changes}


def test_good_card_has_no_problems():
    assert check_card(GOOD, TEXT) == []


def test_extra_fields_ignored_and_defaults_filled():
    card = Card.model_validate(with_(id="S-0001"))
    assert card.hooks_planted == [] and card.incomplete is False


def test_quote_compared_without_punctuation():
    data = with_(facts=[{"subject": "林清", "attribute": "住处", "value": "青州城外", "quote": "林清年方十六住在青州城外"}])
    assert check_card(data, TEXT) == []


def test_quote_not_in_text():
    problems = check_card(with_(facts=[{"subject": "林清", "attribute": "年龄", "value": "十七", "quote": "林清年方十七"}]), TEXT)
    assert len(problems) == 1 and "林清年方十七" in problems[0]


def test_name_not_in_text():
    data = with_(characters=[{"name": "孙悟空", "role": "主要"}])
    problems = check_card(data, TEXT)
    assert len(problems) == 1 and "孙悟空" in problems[0]


def test_bad_kind_is_format_problem():
    problems = check_card(with_(kind="小说"), TEXT)
    assert len(problems) == 1 and "格式" in problems[0]


def test_long_summary():
    assert check_card(with_(summary="长" * 201), TEXT) != []


def test_clean_card_drops_unverifiable_items():
    data = with_(
        pov="张三",
        characters=[{"name": "林清", "role": "主要"}, {"name": "孙悟空", "role": "提及"}],
        locations=["青州城外", "花果山"],
        facts=[
            {"subject": "林清", "attribute": "年龄", "value": "十六", "quote": "林清年方十六"},
            {"subject": "林清", "attribute": "年龄", "value": "十七", "quote": "林清年方十七"},
        ],
    )
    card, dropped = clean_card(Card.model_validate(data), TEXT)
    assert [c.name for c in card.characters] == ["林清"]
    assert card.locations == ["青州城外"] and card.pov == ""
    assert [f.quote for f in card.facts] == ["林清年方十六"]
    assert dropped == {"facts": ["林清年方十七"], "names": ["孙悟空", "张三", "花果山"]}


import pytest
from helpers import FakeBackend, card_reply, fake_ai_handler, scene_text_from

from ligaotai.cards import load_card, run_cards
from ligaotai.config import AppConfig
from ligaotai.importer import run_import
from ligaotai.jobs import JobCancelled
from ligaotai.llm import FatalLLMError, LLMClient
from ligaotai.scenes import run_split


def client_for(book, handler=None, **cfg):
    return LLMClient(AppConfig(**cfg), FakeBackend(handler=handler or fake_ai_handler()), log_dir=book.logs_dir)


def test_run_cards_writes_and_skips_fresh(story_book):
    c = client_for(story_book)
    s = run_cards(story_book, c)
    assert (s["scenes"], s["fresh"], s["written"], s["failed"], s["missing"]) == (3, 3, 3, [], [])
    record = load_card(story_book, "S-0001")
    assert record["card"]["characters"] == [{"name": "林清", "role": "主要"}]
    assert record["scene_hash"] and record["model"] == "deepseek-flash"
    assert story_book.load()["usage"]["by_step"]["cards"]["calls"] == 3
    assert story_book.step("cards")["status"] == "done"
    assert (story_book.logs_dir / "cards" / "S-0001-1.json").exists()

    c2 = client_for(story_book)
    s2 = run_cards(story_book, c2)
    assert c2.usage.calls == 0 and s2["written"] == 0 and s2["fresh"] == 3


def test_changed_scene_is_redone(story_book):
    run_cards(story_book, client_for(story_book))
    (story_book.story_src / "2.txt").write_text("第三章 天机\n林姑娘进了天机阁，改了一句。", encoding="utf-8")
    run_import(story_book, story_book.story_src)
    run_split(story_book)
    c = client_for(story_book)
    run_cards(story_book, c)
    assert c.usage.calls == 1


def test_failed_item_is_listed_and_retried_later(story_book):
    def handler(tier, messages):
        text = scene_text_from(messages)
        return "坏" if "天机阁" in text else card_reply(text)

    c = client_for(story_book, handler)
    s = run_cards(story_book, c)
    assert [f["id"] for f in s["failed"]] == ["S-0003"]
    assert s["missing"] == ["S-0003"] and s["fresh"] == 2
    assert c.usage.calls == 2 + 3

    c2 = client_for(story_book)
    run_cards(story_book, c2)
    assert c2.usage.calls == 1


def test_fatal_error_stops_step(story_book):
    class Denied(Exception):
        status_code = 401

    with pytest.raises(FatalLLMError):
        run_cards(story_book, client_for(story_book, lambda t, m: Denied("bad key")))
    assert not list(story_book.cards_dir.glob("*.json")) if story_book.cards_dir.exists() else True


def test_cancel_keeps_finished_cards(story_book):
    def progress(done, total):
        if done >= 1:
            raise JobCancelled()

    with pytest.raises(JobCancelled):
        run_cards(story_book, client_for(story_book, concurrency=1), progress)
    assert len(list(story_book.cards_dir.glob("S-*.json"))) == 1

    c = client_for(story_book)
    run_cards(story_book, c)
    assert c.usage.calls == 2


def test_only_regenerates_given_scene(story_book):
    run_cards(story_book, client_for(story_book))
    c = client_for(story_book)
    s = run_cards(story_book, c, only=["S-0002"])
    assert c.usage.calls == 1 and s["written"] == 1 and s["fresh"] == 3


def test_unverifiable_items_dropped_after_retries(story_book):
    def handler(tier, messages):
        text = scene_text_from(messages)
        if "林清年方" not in text:
            return card_reply(text)
        return (
            '{"summary": "s", "characters": [{"name": "孙悟空", "role": "主要"}, {"name": "林清", "role": "主要"}],'
            ' "facts": [{"subject": "林清", "attribute": "a", "value": "v", "quote": "不存在的话"}], "kind": "正文"}'
        )

    c = client_for(story_book, handler)
    s = run_cards(story_book, c)
    record = load_card(story_book, "S-0001")
    assert record["problems"] and record["dropped"] == {"facts": ["不存在的话"], "names": ["孙悟空"]}
    assert record["card"]["characters"] == [{"name": "林清", "role": "主要"}]
    assert s["with_problems"] == 1
    assert c.usage.calls == 3 + 2
