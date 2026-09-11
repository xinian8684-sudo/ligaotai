import pytest

from ligaotai.fsutil import (
    atomic_write_text,
    ensure_within,
    natural_key,
    read_json,
    safe_name,
    write_json,
)


def test_atomic_write_roundtrip_and_no_temp_left(tmp_path):
    p = tmp_path / "sub" / "a.md"
    atomic_write_text(p, "第一行\n第二行")
    assert p.read_text(encoding="utf-8") == "第一行\n第二行"
    assert [x.name for x in p.parent.iterdir()] == ["a.md"]


def test_atomic_write_keeps_lf(tmp_path):
    p = tmp_path / "a.txt"
    atomic_write_text(p, "a\nb")
    assert p.read_bytes() == b"a\nb"


def test_json_roundtrip_keeps_chinese(tmp_path):
    p = tmp_path / "x.json"
    write_json(p, {"名字": "林清"})
    assert "林清" in p.read_text(encoding="utf-8")
    assert read_json(p) == {"名字": "林清"}


def test_read_json_default_when_missing(tmp_path):
    assert read_json(tmp_path / "none.json", {"a": 1}) == {"a": 1}


def test_safe_name():
    assert safe_name('我的:书/第一部?') == "我的_书_第一部_"
    with pytest.raises(ValueError):
        safe_name("  ..  ")


def test_natural_key_sorts_numbers_as_numbers():
    names = ["片段10.txt", "片段2.txt", "片段1.txt"]
    assert sorted(names, key=natural_key) == ["片段1.txt", "片段2.txt", "片段10.txt"]


def test_ensure_within(tmp_path):
    base = tmp_path / "book"
    base.mkdir()
    assert ensure_within(base, base / "a" / "b.md") == (base / "a" / "b.md").resolve()
    with pytest.raises(ValueError):
        ensure_within(base, base / ".." / "evil.md")
