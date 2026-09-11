import json

import pytest
from helpers import make_chapters

from ligaotai.readers import read_text
from tools.scramble import main, parse_chapters, scramble, strip_gutenberg

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
