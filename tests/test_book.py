import pytest

from ligaotai.book import (
    DEFAULT_SETTINGS,
    STEPS,
    create_book,
    list_books,
    open_book,
    recover_interrupted,
)


def test_create_book_writes_meta(library):
    b = create_book(library, "我的书")
    meta = b.load()
    assert meta["title"] == "我的书"
    assert set(meta["steps"]) == set(STEPS)
    assert all(s["status"] == "todo" for s in meta["steps"].values())


def test_create_duplicate_raises(library):
    create_book(library, "我的书")
    with pytest.raises(FileExistsError):
        create_book(library, "我的书")


def test_open_book(library):
    create_book(library, "我的书")
    assert open_book(library, "我的书").load()["title"] == "我的书"
    with pytest.raises(FileNotFoundError):
        open_book(library, "没有这本")
    with pytest.raises(ValueError):
        open_book(library, "../我的书")


def test_list_books(library):
    create_book(library, "乙书")
    create_book(library, "甲书")
    assert sorted(b["title"] for b in list_books(library)) == ["乙书", "甲书"]


def test_settings_default_and_override(book):
    assert book.settings() == DEFAULT_SETTINGS
    book.update(lambda d: d["settings"].update(split_max_chars=4000))
    s = book.settings()
    assert s["split_max_chars"] == 4000
    assert s["dedup_jaccard"] == DEFAULT_SETTINGS["dedup_jaccard"]


def test_changed_step_outdates_done_downstream_only(book):
    book.set_step("split", "done")
    book.set_step("dedup", "done")
    book.set_step("import", "done", {"added": 3}, changed=True)
    assert book.step("import")["summary"] == {"added": 3}
    assert book.step("split")["status"] == "outdated"
    assert book.step("dedup")["status"] == "outdated"
    assert book.step("cards")["status"] == "todo"


def test_unchanged_step_does_not_outdate(book):
    book.set_step("split", "done")
    book.set_step("import", "done", changed=False)
    assert book.step("split")["status"] == "done"


def test_set_step_rejects_unknown(book):
    with pytest.raises(ValueError):
        book.set_step("nope", "done")
    with pytest.raises(ValueError):
        book.set_step("split", "weird")


def test_list_books_skips_corrupt(library, book):
    bad = library / "坏书"
    bad.mkdir()
    (bad / "book.json").write_text("{", encoding="utf-8")
    assert [b["name"] for b in list_books(library)] == [book.name]
    recover_interrupted(library)  # 不该抛异常


def test_recover_interrupted(library, book):
    book.set_step("split", "running")
    fixed = recover_interrupted(library)
    assert fixed == ["测试书:split"]
    assert book.step("split")["status"] == "failed"
