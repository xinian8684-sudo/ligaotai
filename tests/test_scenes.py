import pytest

from ligaotai.importer import run_import
from ligaotai.scenes import (
    Scene,
    dump_scene,
    get_scene,
    load_scenes,
    parse_scene,
    run_split,
    scene_path,
)

LONG = "林清走在雪地里，" * 50  # 400 字，不算碎片


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "稿"
    write(d / "片段2.txt", f"第一章 雪夜\n{LONG}\n第二章 离城\n{LONG}")
    write(d / "片段10.txt", f"第三章 渡口\n{LONG}")
    return d


def by_id(book):
    return {s.id: s for s in load_scenes(book, with_text=True)}


def test_dump_parse_roundtrip():
    sc = Scene(
        id="S-0001", source="稿/a.txt", index=0, start=0, end=9, chars=9,
        hash="1234567890123456", heading="第一回     靈根", part=1,
        text="正文\n---\n还是正文",
    )
    assert parse_scene(dump_scene(sc)) == sc


def test_split_numbers_by_natural_path_order(book, src):
    run_import(book, src)
    summary = run_split(book)
    scenes = load_scenes(book, with_text=True)
    assert [(s.id, s.source, s.index, s.heading) for s in scenes] == [
        ("S-0001", "稿/片段2.txt", 0, "第一章 雪夜"),
        ("S-0002", "稿/片段2.txt", 1, "第二章 离城"),
        ("S-0003", "稿/片段10.txt", 0, "第三章 渡口"),
    ]
    assert scenes[0].text == f"第一章 雪夜\n{LONG}"
    assert scenes[0].kind_hint == ""
    assert (summary["added"], summary["scenes"], summary["fragments"]) == (3, 3, 0)
    assert book.step("split")["status"] == "done"


def test_short_block_is_fragment(book, tmp_path):
    d = tmp_path / "稿"
    write(d / "a.txt", "第一章 渡口\n短短一句。")
    run_import(book, d)
    assert run_split(book)["fragments"] == 1
    assert load_scenes(book)[0].kind_hint == "碎片"


def test_load_without_text(book, src):
    run_import(book, src)
    run_split(book)
    assert all(s.text == "" for s in load_scenes(book))


def test_rerun_unchanged_keeps_downstream(book, src):
    run_import(book, src)
    run_split(book)
    book.set_step("dedup", "done")
    s2 = run_split(book)
    assert (s2["added"], s2["changed"], s2["unchanged"], s2["removed"]) == (0, 0, 3, 0)
    assert book.step("dedup")["status"] == "done"


def test_changed_text_marks_stale(book, src):
    run_import(book, src)
    run_split(book)
    book.set_step("dedup", "done")
    write(src / "片段2.txt", f"第一章 雪夜\n{LONG}\n第二章 离城\n{LONG}改了一句。")
    run_import(book, src)
    summary = run_split(book)
    assert summary["changed"] == 1
    scenes = by_id(book)
    assert scenes["S-0002"].stale is True
    assert scenes["S-0002"].text.endswith("改了一句。")
    assert scenes["S-0001"].stale is False
    assert book.step("dedup")["status"] == "outdated"


def test_new_file_appends_numbers(book, src):
    run_import(book, src)
    run_split(book)
    write(src / "片段1.txt", f"第零章 序\n{LONG}")
    run_import(book, src)
    run_split(book)
    assert by_id(book)["S-0004"].source == "稿/片段1.txt"


def test_vanished_block_removed_then_restored(book, src):
    run_import(book, src)
    run_split(book)
    write(src / "片段2.txt", f"第一章 雪夜\n{LONG}")
    run_import(book, src)
    assert run_split(book)["removed"] == 1
    assert by_id(book)["S-0002"].removed is True
    assert scene_path(book, "S-0002").exists()

    write(src / "片段2.txt", f"第一章 雪夜\n{LONG}\n第二章 离城\n{LONG}")
    run_import(book, src)
    assert run_split(book)["changed"] == 1
    assert by_id(book)["S-0002"].removed is False


def test_get_scene(book, src):
    run_import(book, src)
    run_split(book)
    assert get_scene(book, "S-0003").text == f"第三章 渡口\n{LONG}"
    with pytest.raises(ValueError):
        get_scene(book, "../book")
    with pytest.raises(FileNotFoundError):
        get_scene(book, "S-9999")


def test_stray_copies_are_ignored(book, src):
    run_import(book, src)
    run_split(book)
    real = scene_path(book, "S-0001")
    content = real.read_text(encoding="utf-8")
    (book.scenes_dir / "S-0001 (1).md").write_text(content, encoding="utf-8")
    (book.scenes_dir / "S-0001.sync-conflict-x.md").write_text(content, encoding="utf-8")
    scenes = load_scenes(book, with_text=True)
    ids = [s.id for s in scenes]
    assert ids.count("S-0001") == 1
    assert sorted(ids) == ["S-0001", "S-0002", "S-0003"]
    assert by_id(book)["S-0001"].text == parse_scene(content).text


def test_corrupt_scene_file_error_names_the_file(book, src):
    run_import(book, src)
    run_split(book)
    scene_path(book, "S-0002").write_text("坏掉了", encoding="utf-8")
    with pytest.raises(ValueError, match="S-0002"):
        load_scenes(book)
