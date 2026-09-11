import pytest

from ligaotai.split import SplitRules, is_heading, is_separator, split_text


def spans(text, rules=SplitRules()):
    return [(text[b.start:b.end], b.heading, b.part) for b in split_text(text, rules)]


@pytest.mark.parametrize(
    "line",
    [
        "第一○回     靈根育孕源流出　心性修持大道生",
        " 第八三回     心猿識得丹頭　姹女還歸本性",
        "第八十七回 鳳仙郡冒天止雨　孫大圣勸善施霖",
        "第12章",
        "第一卷 风起",
        "# 第一章",
        "## 小节",
        "Chapter 3",
        "CHAPTER IV",
        "12",
        "１２．",
        "十三",
    ],
)
def test_is_heading_true(line):
    assert is_heading(line)


@pytest.mark.parametrize(
    "line",
    [
        "第三回合，他又扑了上来。",
        "第三回合他扑了上来，",
        "#没空格",
        "",
        "这是一段普通的话",
        "第一章" + "长" * 60,
    ],
)
def test_is_heading_false(line):
    assert not is_heading(line)


@pytest.mark.parametrize("line,expected", [
    ("***", True), ("* * *", True), ("———", True), ("◇◇◇", True), ("　＊＊＊　", True),
    ("——", False), ("***好", False), ("", False),
])
def test_is_separator(line, expected):
    assert is_separator(line) is expected


def test_split_by_chapter_heading():
    text = "第一章 开端\n林清出场。\n\n第二章 转折\n雪夜。"
    assert spans(text) == [
        ("第一章 开端\n林清出场。", "第一章 开端", 1),
        ("第二章 转折\n雪夜。", "第二章 转折", 1),
    ]


def test_preface_before_first_heading():
    assert spans("序言。\n第一章\n正文。") == [("序言。", "", 1), ("第一章\n正文。", "第一章", 1)]


def test_separators_split_and_are_dropped():
    text = "开头。\n***\n中间。\n◇◇◇\n结尾。"
    assert spans(text) == [("开头。", "", 1), ("中间。", "", 2), ("结尾。", "", 3)]


def test_single_blank_line_does_not_split():
    assert spans("甲。\n\n乙。") == [("甲。\n\n乙。", "", 1)]


def test_two_blank_lines_split():
    assert spans("甲。\n\n\n乙。") == [("甲。", "", 1), ("乙。", "", 2)]


def test_whitespace_only_lines_count_as_blank():
    assert spans("甲。\n　　\n \n乙。") == [("甲。", "", 1), ("乙。", "", 2)]


def test_blank_lines_setting():
    assert spans("甲。\n\n\n乙。", SplitRules(blank_lines=3)) == [("甲。\n\n\n乙。", "", 1)]


def test_heading_only_block_merges_forward():
    text = "第一卷 风起\n\n\n第一章 雪夜\n正文。"
    assert spans(text) == [(text, "第一卷 风起 / 第一章 雪夜", 1)]


def test_xiyouji_style_heading_then_blank_lines():
    text = "第一回     靈根育孕\n\n\n\n\n　　詩曰：\n混沌未分。"
    assert spans(text) == [(text, "第一回     靈根育孕", 1)]


def test_first_line_indent_is_kept():
    assert spans("\n\n　　第一段。") == [("　　第一段。", "", 1)]


def test_trailing_heading_only_block_is_kept():
    assert spans("正文。\n第九章") == [("正文。", "", 1), ("第九章", "第九章", 1)]


def test_empty_text():
    assert split_text("") == []
    assert split_text("\n\n  \n") == []


def _nows(s):
    return "".join(s.split())


def test_long_block_cut_at_blank_line_near_target():
    para = "甲" * 279 + "。"
    text = "\n\n".join([para] * 40)
    blocks = split_text(text)
    lengths = [b.end - b.start for b in blocks]
    assert all(n <= 5000 for n in lengths)
    assert abs(lengths[0] - 3000) <= 300
    assert text[blocks[0].end:blocks[0].end + 2] == "\n\n"
    assert [b.part for b in blocks] == list(range(1, len(blocks) + 1))
    assert _nows("".join(text[b.start:b.end] for b in blocks)) == _nows(text)


def test_long_block_without_blank_lines_cuts_at_newline():
    line = "乙" * 199 + "。"
    text = "\n".join([line] * 50)
    blocks = split_text(text)
    assert all(b.end - b.start <= 5000 for b in blocks)
    assert all(text[b.end] == "\n" for b in blocks[:-1])
    assert _nows("".join(text[b.start:b.end] for b in blocks)) == _nows(text)


def test_long_single_line_cuts_after_sentence_end():
    text = ("丙" * 99 + "。") * 80
    blocks = split_text(text)
    assert all(b.end - b.start <= 5000 for b in blocks)
    assert all(text[b.end - 1] == "。" for b in blocks)
    assert "".join(text[b.start:b.end] for b in blocks) == text


def test_no_punctuation_hard_cut():
    text = "丁" * 12000
    assert [b.end - b.start for b in split_text(text)] == [3000, 3000, 3000, 3000]


def test_long_blocks_keep_heading():
    text = "第一章 雪夜\n" + "\n\n".join(["戊" * 279 + "。"] * 30)
    blocks = split_text(text)
    assert len(blocks) >= 2
    assert all(b.heading == "第一章 雪夜" for b in blocks)
