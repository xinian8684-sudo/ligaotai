import pytest

from ligaotai.cards import card_path
from ligaotai.fsutil import read_json, write_json
from ligaotai.impact import program_impact
from ligaotai.threads_ops import load_threads


def _set_card(book, sid, **changes):
    rec = read_json(card_path(book, sid))
    rec["card"].update(changes)
    write_json(card_path(book, sid), rec)


@pytest.fixture
def ib(book_with_threads):
    b = book_with_threads
    data = read_json(b.threads_path)
    data["intersections"] = [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "龙宫借宝"}]
    write_json(b.threads_path, data)
    # 主线 S-0001 提到了支线独有人物敖广（「敖广」是规范名本身）
    _set_card(b, "S-0001", refs_elsewhere=["敖广献宝的旧事", "五行山的来历"])
    return b


def test_支线的交汇点_对方是主线(ib):
    r = program_impact(ib, load_threads(ib), "L-002")
    assert r["crossings"] == [{"other": "L-001", "scene": "S-0004", "main_scene": "S-0002", "reason": "龙宫借宝"}]


def test_主线的交汇点_对方是支线(ib):
    r = program_impact(ib, load_threads(ib), "L-001")
    assert r["crossings"] == [{"other": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "龙宫借宝"}]


def test_只在这条线出场的人物_用规范名归一(ib):
    assert program_impact(ib, load_threads(ib), "L-002")["only_characters"] == [
        {"name": "敖广", "scenes": ["S-0004", "S-0005"]}]
    # 「悟空」「行者」归到规范名 孙悟空，只在 L-001 出场
    assert program_impact(ib, load_threads(ib), "L-001")["only_characters"] == [
        {"name": "孙悟空", "scenes": ["S-0001", "S-0002", "S-0003"]}]


def test_别的线提到独有人物_算可能的引用(ib):
    refs = program_impact(ib, load_threads(ib), "L-002")["maybe_refs"]
    assert refs == [{"scene": "S-0001", "thread": "L-001", "text": "敖广献宝的旧事", "names": ["敖广"]}]


def test_人物在两条线都出场就不算独有(ib):
    _set_card(ib, "S-0001", characters=[{"name": "悟空", "role": "主要"}, {"name": "敖广", "role": "提及"}])
    assert program_impact(ib, load_threads(ib), "L-002")["only_characters"] == []


def test_代词不算人物(ib):
    _set_card(ib, "S-0004", characters=[{"name": "我", "role": "主要"}, {"name": "敖广", "role": "主要"}])
    names = [c["name"] for c in program_impact(ib, load_threads(ib), "L-002")["only_characters"]]
    assert names == ["敖广"]


def test_线不存在(ib):
    with pytest.raises(KeyError):
        program_impact(ib, load_threads(ib), "L-009")
