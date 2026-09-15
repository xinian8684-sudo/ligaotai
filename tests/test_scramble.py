import json
import random

import pytest
from helpers import gen_text, make_chapters, make_verse_chapter

from ligaotai.readers import read_text
from ligaotai.split import split_text
from tools.scramble import (
    _pick_excerpt_span,
    main,
    mutate,
    parse_chapters,
    scramble,
    strip_gutenberg,
)

SMALL = dict(n_delete=2, n_truncate=2, n_full=3, n_excerpt=2, alias_chapters=5)


def all_text(out, key, chapter=None, kind=None):
    parts = []
    for f in key["files"]:
        if chapter is not None and f["chapter"] != chapter:
            continue
        if kind is not None and f["kind"] != kind:
            continue
        parts.append(read_text(out / f["path"])[0])
    return "\n".join(parts)


def test_strip_and_parse_gutenberg_like():
    raw = (
        "The Project Gutenberg eBook\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\n\n"
        "Produced by Someone\n\n第一回     標題\n\n\n\n　　詩曰：\n正文一。\n\n"
        " 第二回 標題二\n正文二。\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\nlicense"
    )
    chapters = parse_chapters(strip_gutenberg(raw))
    assert [c.heading for c in chapters] == ["第一回     標題", "第二回 標題二"]
    assert chapters[0].body.startswith("　　詩曰：")
    assert chapters[1].body == "正文二。"


@pytest.fixture
def scrambled(tmp_path):
    out = tmp_path / "乱稿"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    return out, key


def test_counts_and_files_exist(scrambled):
    out, key = scrambled
    assert len(key["deleted"]) == 2
    assert len(key["truncated"]) == 2
    kinds = [f["kind"] for f in key["files"]]
    assert kinds.count("variant_full") == 3
    assert kinds.count("variant_excerpt") == 2
    assert all((out / f["path"]).exists() for f in key["files"])
    assert len({f["path"] for f in key["files"]}) == len(key["files"])
    assert {f["format"] for f in key["files"]} <= {"txt", "md", "docx"}
    assert not set(key["deleted"]) & {f["chapter"] for f in key["files"]}


def test_variants_point_to_single_file_originals(scrambled):
    _, key = scrambled
    by_path = {f["path"]: f for f in key["files"]}
    assert len(key["variants"]) == 5
    for v in key["variants"]:
        orig = by_path[v["original_file"]]
        assert (orig["kind"], orig["chapter"], orig["pieces"]) == ("original", v["chapter"], 1)


def test_deleted_chapter_text_is_gone(scrambled):
    out, key = scrambled
    chapters = make_chapters(20)
    everything = all_text(out, key)
    for num in key["deleted"]:
        assert chapters[num - 1].body[:100] not in everything


def test_aliases_applied(scrambled):
    out, key = scrambled
    truncated = {t["chapter"] for t in key["truncated"]}
    for a in key["aliases"]:
        assert len(a["chapters"]) == 5
        num = next(c for c in a["chapters"] if c not in truncated)
        text = all_text(out, key, chapter=num, kind="original")
        assert a["alias"] in text
        assert a["replaces"] not in text


def test_deterministic(tmp_path):
    k1 = scramble(make_chapters(20), tmp_path / "a", seed=3, **SMALL)
    k2 = scramble(make_chapters(20), tmp_path / "b", seed=3, **SMALL)
    assert k1 == k2


def test_alias_collision_raises(tmp_path):
    chapters = make_chapters(20)
    chapters[5].body += "金箍郎"
    with pytest.raises(ValueError):
        scramble(chapters, tmp_path / "x", seed=3, **SMALL)


def test_alias_replaces_not_in_source_raises(tmp_path):
    """replaces 写的词原文里一回都没有：抛 ValueError，不悄悄生成一个出现 0 回的别名（T17-1）。"""
    chapters = make_chapters(20)
    aliases = [{"replaces": "不存在的人名", "alias": "某某郎", "canonical": "某某"}]
    with pytest.raises(ValueError, match="不存在的人名"):
        scramble(chapters, tmp_path / "x", seed=3, aliases=aliases, **SMALL)


def test_alias_candidates_require_term(tmp_path):
    """别名章节必须真的含有被替换的词，别名候选要在截断之后的正文里挑（Fix 1）。"""
    chapters = make_chapters(20)
    for c in chapters:
        if c.num not in (3, 5, 7):
            c.body = c.body.replace("八戒", "某人")
    out = tmp_path / "乱稿"
    key = scramble(
        chapters, out, seed=3,
        n_delete=0, n_truncate=0, n_full=0, n_excerpt=0, alias_chapters=5,
    )
    ba = next(a for a in key["aliases"] if a["replaces"] == "八戒")
    assert set(ba["chapters"]) <= {3, 5, 7}
    assert ba["chapters"]
    for num in ba["chapters"]:
        text = all_text(out, key, chapter=num, kind="original")
        assert "天蓬郎" in text


class FakeRng:
    """固定 random() 序列，choice 永远取第一个元素。"""

    def __init__(self, values):
        self.values = list(values)
        self.i = 0

    def random(self):
        v = self.values[self.i]
        self.i += 1
        return v

    def choice(self, seq):
        return seq[0]


def test_mutate_drop_leaves_no_blank_run():
    """删掉缩进诗句时不能留下只剩全角空格的行，否则会被 split.py 当成空行制造假场景分隔（Fix 2）。"""
    FW = "　"
    text = "前文。\n" + FW * 4 + "甲句。\n" + FW * 4 + "乙句。\n" + FW * 4 + "丙句。\n後文。"
    # _SENTENCE.split 在这段文本上切出 6 个片段（含结尾一个空片段），每个都要抽一次 random()。
    rng = FakeRng([0.9, 0.0, 0.0, 0.9, 0.9, 0.9])  # 保留、删、删、保留、保留、（空片段）
    result = mutate(text, rng)
    assert result == "前文。\n" + FW * 4 + "丙句。\n後文。"


def _blank_line_runs(text: str) -> int:
    """统计连续 >=2 行「去空白后为空」的行的运行段数（含全角空格）。"""
    lines = text.split("\n")
    runs, i, n = 0, 0, len(lines)
    while i < n:
        if not lines[i].strip():
            j = i
            while j < n and not lines[j].strip():
                j += 1
            if j - i >= 2:
                runs += 1
            i = j
        else:
            i += 1
    return runs


def test_mutate_never_increases_blank_line_runs():
    """跑 20 个种子：mutate 之后「连续 >=2 空行」的段数不能比原文多（Fix 2）。"""
    for seed in range(20):
        chapter = make_verse_chapter(1, seed=seed)
        rng = random.Random(seed)
        result = mutate(chapter.body, rng)
        assert _blank_line_runs(result) <= _blank_line_runs(chapter.body)


def test_pick_excerpt_span_within_one_block():
    """新的选段函数选出的窗口必须落在 split_text 切出的单个场景块里（Fix 3）。"""
    heading = "第1回 標題1"
    body = gen_text(1, 2990) + "\n\n悟空說道，八戒和唐僧都在。\n\n" + gen_text(2, 2990)
    rng = random.Random(5)
    a, b = _pick_excerpt_span(heading, body, rng)
    file_text = f"{heading}\n\n{body}"
    blocks = split_text(file_text)
    containing = [blk for blk in blocks if blk.start <= a and b <= blk.end]
    assert containing, f"span [{a},{b}) not inside any single block; blocks={blocks}"
    assert 1200 <= b - a <= 2400 or (b - a) <= 2000  # 正常窗口或退回兜底截断


def test_variant_excerpts_within_single_block(tmp_path, monkeypatch):
    """整合测试：真跑一次 scramble（关掉 mutate），片段重写版的原文不能横跨两个场景块（Fix 3）。"""
    import tools.scramble as scr

    monkeypatch.setattr(scr, "mutate", lambda text, rng, *a, **k: text)
    out = tmp_path / "乱稿"
    key = scr.scramble(make_chapters(20), out, seed=3, **SMALL)
    for v in key["variants"]:
        if v["kind"] != "variant_excerpt":
            continue
        orig_text, _ = read_text(out / v["original_file"])
        excerpt_text, _ = read_text(out / v["file"])
        start = orig_text.find(excerpt_text)
        assert start != -1, f"chapter {v['chapter']}: excerpt text not found verbatim in original"
        end = start + len(excerpt_text)
        blocks = split_text(orig_text)
        containing = [blk for blk in blocks if blk.start <= start and end <= blk.end]
        assert containing, f"chapter {v['chapter']} excerpt spans blocks: {blocks}"


def test_cli_writes_key_outside_folder(tmp_path):
    src = tmp_path / "book.txt"
    src.write_text(
        "\n".join(f"{c.heading}\n\n{c.body}\n" for c in make_chapters(30)), encoding="utf-8"
    )
    out = tmp_path / "乱稿"
    main(["--src", str(src), "--out", str(out), "--seed", "5"])
    key = json.loads((tmp_path / "乱稿-答案.json").read_text(encoding="utf-8"))
    assert key["chapters"] == 30
    assert not (out / "乱稿-答案.json").exists()


def test_main_accepts_custom_aliases(tmp_path):
    chapters = make_chapters(30)
    src = tmp_path / "book.txt"
    src.write_text("\n".join(f"{c.heading}\n{c.body}" for c in chapters), encoding="utf-8")
    aliases = tmp_path / "aliases.json"
    aliases.write_text(
        json.dumps([{"replaces": "八戒", "alias": "豬先生", "canonical": "豬八戒"}], ensure_ascii=False), encoding="utf-8"
    )
    out = tmp_path / "乱稿"
    main(["--src", str(src), "--out", str(out), "--seed", "5", "--aliases", str(aliases)])
    key = json.loads((tmp_path / "乱稿-答案.json").read_text(encoding="utf-8"))
    assert [a["alias"] for a in key["aliases"]] == ["豬先生"] and key["aliases"][0]["chapters"]
