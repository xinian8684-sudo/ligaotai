import pytest
from helpers import gen_text

from ligaotai.dedup import (
    find_pairs,
    group_pairs,
    normalize,
    run_dedup,
    set_main,
    shingles,
)
from ligaotai.fsutil import read_json
from ligaotai.importer import run_import
from ligaotai.scenes import run_split


def test_normalize():
    assert normalize("林清，\n　走了。abc") == "林清走了abc"


def test_shingles():
    assert len(shingles("甲乙丙丁戊己", 5)) == 2
    assert len(shingles("甲乙", 5)) == 1
    assert shingles("，。 ", 5) == set()


def test_jaccard_pair():
    docs = {"a": set(range(0, 200)), "b": set(range(40, 240))}
    [p] = find_pairs(docs, 0.5, 0.8, 100, 20)
    assert (p.a, p.b, p.inter, p.jaccard) == ("a", "b", 160, 0.6667)


def test_containment_pair():
    docs = {"a": set(range(0, 400)), "c": set(range(0, 120))}
    [p] = find_pairs(docs, 0.5, 0.8, 100, 20)
    assert (p.jaccard, p.containment) == (0.3, 1.0)


def test_below_thresholds_no_pair():
    docs = {"b": set(range(1000, 1200)), "d": set(range(1100, 1300))}
    assert find_pairs(docs, 0.5, 0.8, 100, 20) == []


def test_tiny_docs_ignored():
    docs = {"a": set(range(0, 400)), "e": set(range(0, 50))}
    assert find_pairs(docs, 0.5, 0.8, 100, 20) == []


def test_common_shingles_not_counted():
    docs = {
        f"d{i:02d}": set(range(250)) | set(range(10000 * (i + 1), 10000 * (i + 1) + 50))
        for i in range(25)
    }
    assert len(find_pairs(docs, 0.5, 0.8, 100, 30)) == 300
    assert find_pairs(docs, 0.5, 0.8, 100, 20) == []


def test_group_pairs_natural_order():
    docs = {
        "S-2": set(range(0, 200)), "S-10": set(range(0, 200)),
        "S-3": set(range(0, 200)), "S-7": set(range(5000, 5200)), "S-8": set(range(5000, 5200)),
    }
    groups = group_pairs(find_pairs(docs, 0.5, 0.8, 100, 20))
    assert groups == [["S-2", "S-3", "S-10"], ["S-7", "S-8"]]


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def dup_book(book, tmp_path):
    a = gen_text(1, 2000)
    sentences = a.split("。")
    b = "。".join(s for i, s in enumerate(sentences) if i % 7 != 3)
    d = tmp_path / "稿"
    write(d / "1甲.txt", "第一章 甲\n" + a)
    write(d / "2乙.txt", "第一章 甲\n" + b)
    write(d / "3丙.txt", a[400:1400])
    write(d / "4丁.txt", "第二章 丁\n" + gen_text(2, 2000))
    run_import(book, d)
    run_split(book)
    return book


def test_run_dedup_groups_versions(dup_book):
    summary = run_dedup(dup_book)
    data = read_json(dup_book.versions_path)
    [g] = data["groups"]
    assert g["members"] == ["S-0001", "S-0002", "S-0003"]
    assert g["main"] == "S-0001"
    assert g["main_by"] == "auto"
    assert summary["groups"] == 1
    assert summary["scenes_in_groups"] == 3
    assert dup_book.step("dedup")["status"] == "done"


def test_author_main_survives_rerun(dup_book):
    run_dedup(dup_book)
    dup_book.set_step("cards", "done")
    g = set_main(dup_book, "G-001", "S-0002")
    assert (g["main"], g["main_by"]) == ("S-0002", "author")
    assert dup_book.step("cards")["status"] == "outdated"
    run_dedup(dup_book)
    [g] = read_json(dup_book.versions_path)["groups"]
    assert (g["main"], g["main_by"]) == ("S-0002", "author")


def test_rerun_unchanged_keeps_downstream(dup_book):
    run_dedup(dup_book)
    dup_book.set_step("cards", "done")
    run_dedup(dup_book)
    assert dup_book.step("cards")["status"] == "done"


def test_set_main_errors(dup_book):
    run_dedup(dup_book)
    with pytest.raises(ValueError):
        set_main(dup_book, "G-001", "S-0004")
    with pytest.raises(KeyError):
        set_main(dup_book, "G-999", "S-0001")
