import pytest

from ligaotai.prompts import render


def test_load_and_render(tmp_path):
    (tmp_path / "x.md").write_text(
        "说明文字\n\n## system\n你好 $who，价格 $$5\n\n## user\n正文：$text\n", encoding="utf-8"
    )
    assert render("x", tmp_path, who="作者", text="甲") == ("你好 作者，价格 $5", "正文：甲")


def test_missing_section(tmp_path):
    (tmp_path / "x.md").write_text("## system\n只有一段\n", encoding="utf-8")
    with pytest.raises(ValueError):
        render("x", tmp_path)


def test_missing_variable(tmp_path):
    (tmp_path / "x.md").write_text("## system\n$who\n## user\n$text\n", encoding="utf-8")
    with pytest.raises(KeyError):
        render("x", tmp_path, text="甲")


def test_real_cards_prompt():
    system, user = render("cards", scene_id="S-0001", source="稿/a.txt", heading="第一章", text="林清年方十六。")
    assert "json" in system and "场景卡" in system
    assert "S-0001" in user and "林清年方十六。" in user
    assert "$" not in system + user


def test_real_cards_prompt_has_pov_and_quote_rules():
    """作者批准的两条新规则：pov 没有明确视角人物就留空、不要写「第三人称/全知」；
    quote 不许用省略号/分号拼接几处原文。"""
    system, _ = render("cards", scene_id="S-0001", source="稿/a.txt", heading="第一章", text="林清年方十六。")
    assert "第三人称" in system
    assert "省略号" in system


def test_real_entities_prompt():
    system, user = render("entities", type_label="人物", names="- 林清（3 个场景）：林清年方十六", hints="（无）")
    assert "json" in system and "人物" in system and "归成一组" in system
    assert "林清" in user
    assert "$" not in system + user


THREAD_PROMPTS = [
    ("threads_worlds", {"unit_rule": "x", "known": "k", "lines": "l"}, "划分世界"),
    ("threads_lines", {"world": "w", "locked": "k", "lines": "l"}, "划分支线"),
    ("threads_order", {"thread": "t", "unit": "年", "segments": "s", "lines": "l"}, "线内排序"),
    ("threads_align", {"unit": "年", "main": "L-001", "threads": "t"}, "跨线对齐"),
    ("threads_gaps", {"world": "w", "threads": "t", "refs": "r"}, "找缺口"),
]


@pytest.mark.parametrize("name,values,mark", THREAD_PROMPTS)
def test_threads_prompts_render(name, values, mark):
    from ligaotai.prompts import render

    system, user = render(name, **values)
    assert "json" in system and mark in system
    assert "$" not in system + user
    others = [m for _, _, m in THREAD_PROMPTS if m != mark]
    assert not any(m in system for m in others)


def test_threads_marks_not_in_older_prompts():
    from ligaotai.prompts import load_prompt

    for name in ("cards", "entities"):
        system, _ = load_prompt(name)
        assert not any(m in system.template for _, _, m in THREAD_PROMPTS)
