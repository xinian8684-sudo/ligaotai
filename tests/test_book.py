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


def test_new_paths(book):
    assert book.cards_dir.name == "场景卡"
    assert book.entities_path.name == "实体.json"
    assert book.logs_dir.name == "日志"


def test_add_usage_accumulates(book):
    book.add_usage("cards", calls=3, prompt_tokens=1000, completion_tokens=200, cost_usd=0.0012)
    book.add_usage("cards", calls=1, prompt_tokens=10, completion_tokens=5, cost_usd=0.0001)
    book.add_usage("entities", calls=2, prompt_tokens=50, completion_tokens=50, cost_usd=0.002)
    usage = book.load()["usage"]
    assert usage["total"] == {"calls": 6, "prompt_tokens": 1060, "completion_tokens": 255, "cost_usd": 0.0033}
    assert usage["by_step"]["cards"]["calls"] == 4
    assert usage["by_step"]["entities"]["cost_usd"] == 0.002


def test_threads_paths_and_setting(book):
    assert book.threads_path.name == "世界与支线.json"
    assert book.threads_cache_path.name == "归线缓存.json"
    assert book.settings()["threads_max_input_tokens"] == 600000


def test_默认设置有矛盾扫描的两个上限():
    from ligaotai.book import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["contradictions_batch_tokens"] == 30000
    assert DEFAULT_SETTINGS["contradictions_max_groups"] == 2000


def test_默认设置有矛盾扫描的每批组数上限():
    """审查建议修6：小组多时按字符预算一批能塞进几百组，加一个独立的组数上限。"""
    from ligaotai.book import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["contradictions_max_batch_groups"] == 80


def test_二期的文件路径(book):
    r = book.root
    assert book.canon_path == r / "定稿设定.json"
    assert book.triage_dir == r / "取舍"
    assert book.board_path == r / "取舍" / "看板.json"
    assert book.advice_path == r / "取舍" / "建议.json"
    assert book.impact_path == r / "取舍" / "影响.json"
    assert book.skeleton_path == r / "取舍" / "骨架.json"
    assert book.skeleton_bak_path == r / "取舍" / "骨架.bak.json"
    assert book.triage_cache_path == r / "取舍" / "缓存.json"
    assert book.export_dir == r / "导出"


def test_骨架分章的输入上限有默认值(book):
    assert book.settings()["skeleton_max_input_tokens"] == 600000
