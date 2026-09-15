import json

import pytest
from helpers import FakeBackend, make_chapters

import tools.probe_book as probe_book
from ligaotai.config import AppConfig
from ligaotai.llm import FatalLLMError
from tools.probe_book import probe
from tools.scramble import Chapter


def test_probe_puts_model_answers_next_to_headings():
    reply = json.dumps({"known": "有印象", "chapters": [{"n": "1", "plot": "开头"}, {"n": 2, "plot": None}, {"n": "x"}]},
                       ensure_ascii=False)
    chapters = [Chapter(1, "第一回 甲", "正文"), Chapter(2, "第二回 乙", "正文")]
    r = probe("某书", chapters, AppConfig(), FakeBackend(replies=[reply]))
    assert r["known"] == "有印象" and (r["answered"], r["chapters"], r["calls"]) == (1, 2, 1)
    assert r["rows"] == [
        {"n": 1, "heading": "第一回 甲", "model": "开头"},
        {"n": 2, "heading": "第二回 乙", "model": None},
    ]


def test_probe_handles_malformed_chapter_numbers_and_plots():
    """回数是 bool / Infinity 时跳过（不能被 int() 接住）；plot 不是字符串当 None；
    同一回写了两次，留第一次（哪怕第一次的 plot 因为不是字符串而变成了 None）。"""
    reply = json.dumps(
        {
            "known": "不知道",
            "chapters": [
                {"n": True, "plot": "x"},    # bool，int(True) 会变成第 1 回，要跳过
                {"n": 1e999},                # json 里写 1e999 会解析成 Infinity，int(inf) 抛 OverflowError，要跳过
                {"n": 2, "plot": {"a": 1}},  # 第一个合法的 n=2；plot 是字典，不收，记 None
                {"n": 2, "plot": "第二次"},   # 又一次 n=2，要被当成重复丢掉，不能覆盖第一次的 None
            ],
        },
        ensure_ascii=False,
    )
    chapters = [Chapter(1, "第一回 甲", "正文"), Chapter(2, "第二回 乙", "正文")]
    r = probe("某书", chapters, AppConfig(), FakeBackend(replies=[reply]))
    assert r["known"] == "不知道"
    assert r["rows"] == [
        {"n": 1, "heading": "第一回 甲", "model": None},
        {"n": 2, "heading": "第二回 乙", "model": None},
    ]
    assert r["answered"] == 0


def test_probe_plot_only_accepts_nonempty_strings():
    """plot 只收字符串（去掉首尾空白后非空）；数字/字典/列表/空串/纯空白都当 None，不计入 answered。"""
    reply = json.dumps(
        {
            "known": "熟悉",
            "chapters": [
                {"n": 1, "plot": "  开头  "},
                {"n": 2, "plot": "   "},
                {"n": 3, "plot": 123},
                {"n": 4, "plot": []},
                {"n": 5, "plot": ""},
            ],
        },
        ensure_ascii=False,
    )
    chapters = [Chapter(i, f"第{i}回 标题{i}", "正文") for i in range(1, 6)]
    r = probe("某书", chapters, AppConfig(), FakeBackend(replies=[reply]))
    assert [row["model"] for row in r["rows"]] == ["开头", None, None, None, None]
    assert r["answered"] == 1


def test_probe_known_missing_becomes_empty_string():
    """known 不是字符串（含缺失）时按 threads_check.text() 的规则转成空串。"""
    reply = json.dumps({"chapters": []}, ensure_ascii=False)
    chapters = [Chapter(1, "第一回 甲", "正文")]
    r = probe("某书", chapters, AppConfig(), FakeBackend(replies=[reply]))
    assert r["known"] == ""
    assert r["rows"] == [{"n": 1, "heading": "第一回 甲", "model": None}]


# --- 修复批次 6（T17-2，见 reports/review_t15_18.md）---


def test_main_writes_error_report_on_llm_error(tmp_path, monkeypatch):
    """三次都回不出能用的 JSON：main 接住 LLMError，写 -error.json，终端提示是 ASCII（T17-2）。"""
    chapters = make_chapters(3)
    src = tmp_path / "book.txt"
    src.write_text("\n".join(f"{c.heading}\n\n{c.body}\n" for c in chapters), encoding="utf-8")
    report_path = tmp_path / "报告.json"

    fake = FakeBackend(replies=["not json", "not json", "not json"])
    monkeypatch.setattr(probe_book, "load_config", lambda: AppConfig())
    monkeypatch.setattr(probe_book, "OpenAIBackend", lambda cfg: fake)

    with pytest.raises(SystemExit) as ei:
        probe_book.main(["--title", "某书", "--src", str(src), "--report", str(report_path)])
    assert str(ei.value).isascii()

    error_path = report_path.with_name(report_path.stem + "-error.json")
    data = json.loads(error_path.read_text(encoding="utf-8"))
    assert data["error"].startswith("LLMError")
    assert not report_path.exists()  # 没跑成功，正式报告不该写出来


def test_main_does_not_treat_fatal_error_as_plain(tmp_path, monkeypatch):
    """FatalLLMError（欠费 / key 失效）也走同一条报告路径，提示分「fatal」（T17-2）。"""
    chapters = make_chapters(3)
    src = tmp_path / "book.txt"
    src.write_text("\n".join(f"{c.heading}\n\n{c.body}\n" for c in chapters), encoding="utf-8")
    report_path = tmp_path / "报告.json"

    fake = FakeBackend(replies=[FatalLLMError("欠费了")])
    monkeypatch.setattr(probe_book, "load_config", lambda: AppConfig())
    monkeypatch.setattr(probe_book, "OpenAIBackend", lambda cfg: fake)

    with pytest.raises(SystemExit) as ei:
        probe_book.main(["--title", "某书", "--src", str(src), "--report", str(report_path)])
    assert str(ei.value).startswith("fatal")

    error_path = report_path.with_name(report_path.stem + "-error.json")
    data = json.loads(error_path.read_text(encoding="utf-8"))
    assert data["error"].startswith("FatalLLMError")
