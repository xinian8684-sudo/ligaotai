from ligaotai.cards import Card, Character, check_card, clean_card

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


# --- R2: summary 为空（null 或只有空白）也算问题 ---


def test_null_summary_is_a_problem():
    problems = check_card(with_(summary=None), TEXT)
    assert len(problems) == 1 and "summary" in problems[0] and "空" in problems[0]


def test_whitespace_only_summary_is_a_problem():
    problems = check_card(with_(summary="   "), TEXT)
    assert len(problems) == 1 and "空" in problems[0]


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
    # A8：dropped 里的 facts 存整条 fact（dict），不再只存 quote 字符串。
    assert dropped["facts"] == [{"subject": "林清", "attribute": "年龄", "value": "十七", "quote": "林清年方十七"}]
    assert dropped["names"] == ["孙悟空", "张三", "花果山"]
    # 2c task04：受控属性表接入后 dropped 多了 attrs / long_values 两个计数键，
    # 这条 fact 本身没有触发它们。
    assert dropped["attrs"] == 0 and dropped["long_values"] == 0


# --- A1: 宽松 validator ---


def test_null_fields_become_defaults():
    data = with_(pov=None, locations=None, incomplete=None, world_hint=None)
    card = Card.model_validate(data)
    assert card.pov == "" and card.locations == [] and card.incomplete is False and card.world_hint == ""


def test_list_field_given_single_string_is_wrapped():
    data = with_(locations="青州城外")
    card = Card.model_validate(data)
    assert card.locations == ["青州城外"]


def test_character_as_bare_string_becomes_dict():
    data = with_(characters=["林清"])
    card = Card.model_validate(data)
    assert card.characters == [Character(name="林清", role="提及")]


def test_bad_role_falls_back_to_mentioned():
    data = with_(characters=[{"name": "林清", "role": "路人"}])
    card = Card.model_validate(data)
    assert card.characters[0].role == "提及"


def test_number_value_coerced_to_string():
    data = with_(facts=[{"subject": "林清", "attribute": "年龄", "value": 16, "quote": "林清年方十六"}])
    card = Card.model_validate(data)
    assert card.facts[0].value == "16"


# --- R3: Fact 的 attribute/value/quote 为 null 或缺失时当成空字符串，不算格式错；
# 列表字段里的 None 元素直接过滤掉；characters[i].name 为 None 静默丢掉 ---


def test_fact_value_null_is_not_a_format_error():
    data = with_(facts=[{"subject": "林清", "attribute": "年龄", "value": None, "quote": "林清年方十六"}])
    card = Card.model_validate(data)
    assert card.facts[0].value == ""


def test_fact_missing_quote_is_not_a_format_error_and_gets_reported_as_too_short():
    data = with_(facts=[{"subject": "林清", "attribute": "年龄", "value": "十六"}])
    card = Card.model_validate(data)
    assert card.facts[0].quote == ""
    problems = check_card(data, TEXT)
    assert len(problems) == 1 and "太短" in problems[0]


def test_events_null_element_is_filtered_out():
    data = with_(events=[None, "赵五来了"])
    card = Card.model_validate(data)
    assert card.events == ["赵五来了"]


def test_character_name_null_is_silently_dropped():
    data = with_(characters=[{"name": None, "role": "主要"}])
    card = Card.model_validate(data)
    assert card.characters == []
    assert check_card(data, TEXT) == []


# --- A2: fact 的 subject 也要核对 ---


def test_fact_subject_not_in_text_or_names_is_a_problem():
    data = with_(facts=[{"subject": "某人", "attribute": "年龄", "value": "十六", "quote": "林清年方十六"}])
    problems = check_card(data, TEXT)
    assert len(problems) == 1 and "某人" in problems[0]


def test_fact_subject_matching_a_card_name_does_not_double_report():
    # subject 是本卡自己列出的一个名字（哪怕这名字本身也没在原文里核对通过），
    # 不该再单独报一次「subject 找不到」——名字本身的问题已经由 bad_names 报过一次了。
    data = with_(pov="张三", facts=[{"subject": "张三", "attribute": "关系", "value": "路人", "quote": "赵五来了"}])
    problems = check_card(data, TEXT)
    assert len(problems) == 1 and "张三" in problems[0]


def test_clean_card_drops_facts_whose_subject_name_was_dropped():
    data = with_(
        characters=[{"name": "林清", "role": "主要"}, {"name": "孙悟空", "role": "提及"}],
        facts=[{"subject": "孙悟空", "attribute": "来历", "value": "不明", "quote": "赵五来了"}],
    )
    card, dropped = clean_card(Card.model_validate(data), TEXT)
    assert card.facts == []
    assert dropped["facts"] == [{"subject": "孙悟空", "attribute": "来历", "value": "不明", "quote": "赵五来了"}]
    assert "孙悟空" in dropped["names"]


# --- R4: subject 去标点后是空串的 fact，不能静默丢——check_card 要报出来，
# clean_card 要放进 dropped，不能悄无声息地消失 ---


def test_fact_with_punctuation_only_subject_is_reported_as_a_problem():
    data = with_(facts=[{"subject": "，", "attribute": "a", "value": "v", "quote": "林清年方十六"}])
    problems = check_card(data, TEXT)
    assert len(problems) == 1 and "subject" in problems[0]


def test_clean_card_drops_fact_with_punctuation_only_subject_into_dropped():
    data = with_(facts=[{"subject": "，", "attribute": "a", "value": "v", "quote": "林清年方十六"}])
    card, dropped = clean_card(Card.model_validate(data), TEXT)
    assert card.facts == []
    assert dropped["facts"] == [{"subject": "", "attribute": "a", "value": "v", "quote": "林清年方十六"}]


def test_blank_subject_problem_carries_attribute_and_quote_hint():
    # subject 去标点后是空串时，问题文案要带上这条 fact 的 attribute 和 quote（不能是空的，
    # 模型看不出说的是哪条 fact）。
    data = with_(facts=[{"subject": "，", "attribute": "身份", "value": "v", "quote": "林清年方十六"}])
    problems = check_card(data, TEXT)
    assert len(problems) == 1 and "身份" in problems[0] and "林清年方十六" in problems[0]


def test_blank_subject_quote_hint_is_truncated():
    # quote 截到约 20 字，太长的 quote 不能整段塞进问题文案里。
    quote = "林清年方十六，住在青州城外。那一年冬天，赵五来了。"
    data = with_(facts=[{"subject": "，", "attribute": "身份", "value": "v", "quote": quote}])
    problems = check_card(data, TEXT)
    assert len(problems) == 1
    assert quote[:20] in problems[0] and quote not in problems[0]


# --- A3: quote 太短（去空白标点后 < 4 字）也算问题 ---


def test_short_quote_is_a_problem():
    data = with_(facts=[{"subject": "林清", "attribute": "称呼", "value": "他", "quote": "他"}])
    problems = check_card(data, TEXT)
    assert len(problems) == 1 and "他" in problems[0]


def test_clean_card_drops_short_quote():
    data = with_(facts=[{"subject": "林清", "attribute": "称呼", "value": "是", "quote": "是"}])
    card, dropped = clean_card(Card.model_validate(data), TEXT)
    assert card.facts == [] and dropped["facts"][0]["quote"] == "是"


# --- R6: 空串 / 纯标点的 quote 都报问题（太短） ---


def test_empty_quote_is_a_problem():
    data = with_(facts=[{"subject": "林清", "attribute": "a", "value": "v", "quote": ""}])
    problems = check_card(data, TEXT)
    assert len(problems) == 1 and "太短" in problems[0]


def test_punctuation_only_quote_is_a_problem():
    data = with_(facts=[{"subject": "林清", "attribute": "a", "value": "v", "quote": "，。！？"}])
    problems = check_card(data, TEXT)
    assert len(problems) == 1 and "太短" in problems[0]


# --- A5: 全角半角、大小写都要能对上 ---


ENGLISH_TEXT = "第一章 异客\nTom住在青州城外，Lin是他的朋友。"


def test_fullwidth_and_case_insensitive_name_match():
    data = with_(characters=[{"name": "ｔｏｍ", "role": "主要"}], locations=[], organizations=[], facts=[], pov="")
    assert check_card(data, ENGLISH_TEXT) == []


# --- A6/A7: 名字去首尾标点；去完是空串静默丢掉 ---


def test_name_with_trailing_punctuation_matches():
    data = with_(characters=[{"name": "林清，", "role": "主要"}])
    card = Card.model_validate(data)
    assert card.characters[0].name == "林清"
    assert check_card(data, TEXT) == []


def test_blank_or_punctuation_only_names_are_silently_dropped():
    data = with_(
        characters=[{"name": "", "role": "主要"}, {"name": "，。！", "role": "提及"}],
        locations=["", "——"],
        pov="…",
    )
    card = Card.model_validate(data)
    assert card.characters == [] and card.locations == [] and card.pov == ""
    # 静默丢掉：不报问题，也不出现在 dropped 里（dropped 是 clean_card 的产物，这里连 check_card 都不该报问题）
    assert check_card(data, TEXT) == []


# --- A9: summary 截断到 SUMMARY_LIMIT ---


def test_clean_card_truncates_long_summary():
    data = with_(summary="长" * 250)
    card, _ = clean_card(Card.model_validate(data), TEXT)
    assert len(card.summary) == 200


import pytest
from helpers import FakeBackend, card_reply, fake_ai_handler, scene_text_from

from ligaotai.cards import load_card, pick_error, run_cards
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
    # B2：卡数依赖调度细节（FakeBackend 没有真等待，可能不止 1 张已经写完），
    # 只断言「至少写了 1 张、没写完全部 3 张」，别死抠具体数字。
    n = len(list(story_book.cards_dir.glob("S-*.json")))
    assert 1 <= n < 3
    # B2：异常路径（暂停）也要记进用量，不能因为中途抛异常就漏记这次已经花掉的调用。
    assert story_book.load()["usage"]["by_step"]["cards"]["calls"] >= 1

    c = client_for(story_book)
    run_cards(story_book, c)
    assert c.usage.calls == 3 - n


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
    dropped = record["dropped"]
    assert record["problems"]
    assert dropped["facts"] == [{"subject": "林清", "attribute": "a", "value": "v", "quote": "不存在的话"}]
    assert dropped["names"] == ["孙悟空"]
    assert dropped["attrs"] == 0 and dropped["long_values"] == 0
    assert record["card"]["characters"] == [{"name": "林清", "role": "主要"}]
    assert s["with_problems"] == 1
    assert c.usage.calls == 3 + 2


# --- B1/R5：异常组里 Fatal 优先于 Cancelled ---


def test_pick_error_prefers_fatal_over_cancelled():
    eg = BaseExceptionGroup("x", [JobCancelled(), FatalLLMError("x")])
    assert isinstance(pick_error(eg), FatalLLMError)


def test_fatal_error_wins_over_cancelled_in_exception_group(story_book):
    def handler(tier, messages):
        text = scene_text_from(messages)
        if "天机阁" in text:
            class Denied(Exception):
                status_code = 401

            raise Denied("no balance")
        return card_reply(text)

    def progress(done, total):
        if done >= 1:
            raise JobCancelled()

    with pytest.raises(FatalLLMError):
        run_cards(story_book, client_for(story_book, handler), progress)


# --- B3：坏卡文件不能把整个步骤炸掉 ---


def test_corrupt_card_file_is_treated_as_missing_and_redone(story_book):
    run_cards(story_book, client_for(story_book))
    (story_book.cards_dir / "S-0002.json").write_text("", encoding="utf-8")
    c = client_for(story_book)
    s = run_cards(story_book, c)
    assert c.usage.calls == 1 and s["written"] == 1 and s["fresh"] == 3
    assert load_card(story_book, "S-0002") is not None


def test_not_a_dict_card_file_is_treated_as_missing_and_redone(story_book):
    run_cards(story_book, client_for(story_book))
    (story_book.cards_dir / "S-0003.json").write_text("[1, 2, 3]", encoding="utf-8")
    c = client_for(story_book)
    s = run_cards(story_book, c)
    assert c.usage.calls == 1 and s["written"] == 1 and s["fresh"] == 3


# --- B4：only 里给了不存在/已删除的场景编号，要记进 failed，不能静默忽略 ---


def test_only_with_unknown_scene_is_recorded_as_failed(story_book):
    c = client_for(story_book)
    s = run_cards(story_book, c, only=["S-9999"])
    assert s["failed"] == [{"id": "S-9999", "error": "场景不存在或已删除"}]
    assert c.usage.calls == 0 and s["written"] == 0


# --- I1：单卡重做（only）不许改 cards 步骤自己的状态 ---


def test_only_mode_keeps_todo_status(story_book):
    assert story_book.step("cards")["status"] == "todo"
    run_cards(story_book, client_for(story_book), only=["S-0002"])
    assert story_book.step("cards")["status"] == "todo"


def test_only_mode_keeps_failed_status(story_book):
    story_book.set_step("cards", "failed", {"error": "已暂停：做完的部分已经保存，重跑会接着做"})
    run_cards(story_book, client_for(story_book), only=["S-0002"])
    assert story_book.step("cards")["status"] == "failed"


def test_only_mode_keeps_done_status(story_book):
    run_cards(story_book, client_for(story_book))
    assert story_book.step("cards")["status"] == "done"
    run_cards(story_book, client_for(story_book), only=["S-0002"])
    assert story_book.step("cards")["status"] == "done"


def test_only_mode_keeps_status_on_fatal_error(story_book):
    """欠费/key 失效时也不能碰 cards 步骤自己的状态（已知问题 M5 的反方向）。"""
    story_book.set_step("cards", "failed", {"error": "上一次欠费失败"})

    class Denied(Exception):
        status_code = 401

    with pytest.raises(FatalLLMError):
        run_cards(story_book, client_for(story_book, lambda t, m: Denied("bad key")), only=["S-0002"])
    assert story_book.step("cards")["status"] == "failed"


def test_only_mode_keeps_status_on_cancel(story_book):
    """暂停单卡重做时，已经是 done 的 cards 步骤不能被打回 failed。"""
    run_cards(story_book, client_for(story_book))
    assert story_book.step("cards")["status"] == "done"

    def progress(done, total):
        if done >= 1:
            raise JobCancelled()

    with pytest.raises(JobCancelled):
        run_cards(story_book, client_for(story_book), progress, only=["S-0002"])
    assert story_book.step("cards")["status"] == "done"


# --- 2c task04: 场景卡校验接入受控属性表 ---


def _card(**kw) -> dict:
    base = {"summary": "林清救人", "characters": [{"name": "林清", "role": "主要"}],
            "facts": [], "kind": "正文"}
    base.update(kw)
    return base


def test_表外属性归到其他不当失败():
    text = "林清年方十六，行至青州。"
    data = _card(facts=[{"subject": "林清", "attribute": "行動", "value": "行至青州",
                         "quote": "林清年方十六"}])
    assert check_card(data, text) == [], "属性不对不该触发重试"
    cleaned, dropped = clean_card(Card.model_validate(data), text)
    assert cleaned.facts[0].attribute == "其他"
    assert dropped["attrs"] == 1


def test_value超15字的fact丢掉():
    text = "林清年方十六，行至青州，遇见一个背着竹篓的老人。"
    long_value = "行至青州遇见一个背着竹篓的老人并与之交谈"
    assert len(long_value) > 15
    data = _card(facts=[{"subject": "林清", "attribute": "年龄", "value": long_value,
                         "quote": "林清年方十六"}])
    cleaned, dropped = clean_card(Card.model_validate(data), text)
    assert cleaned.facts == []
    assert dropped["long_values"] == 1


def test_受控属性的短值正常保留():
    text = "林清年方十六，行至青州。"
    data = _card(facts=[{"subject": "林清", "attribute": "年龄", "value": "十六",
                         "quote": "林清年方十六"}])
    cleaned, dropped = clean_card(Card.model_validate(data), text)
    assert len(cleaned.facts) == 1
    assert cleaned.facts[0].attribute == "年龄"
    assert dropped["attrs"] == 0 and dropped["long_values"] == 0
