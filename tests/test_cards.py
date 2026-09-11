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
