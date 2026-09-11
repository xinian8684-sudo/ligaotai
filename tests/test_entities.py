from helpers import FakeBackend, fake_ai_handler

from ligaotai.cards import run_cards
from ligaotai.config import AppConfig
from ligaotai.entities import chunk_names, collect_mentions, core, hint_pairs
from ligaotai.llm import LLMClient


def client_for(book, groups=(), **cfg):
    return LLMClient(AppConfig(**cfg), FakeBackend(handler=fake_ai_handler(groups)), log_dir=book.logs_dir)


def test_collect_mentions(story_book):
    run_cards(story_book, client_for(story_book))
    m = collect_mentions(story_book)
    assert set(m["person"]) == {"林清", "清儿", "林姑娘", "赵五"}
    assert m["person"]["赵五"].scenes == ["S-0002", "S-0003"]
    assert m["person"]["赵五"].count == 2
    assert all("赵五" in ctx for ctx in m["person"]["赵五"].contexts)
    assert set(m["location"]) == {"青州城外"}
    assert set(m["organization"]) == {"天机阁"}


def test_stale_cards_are_ignored(story_book):
    run_cards(story_book, client_for(story_book))
    from ligaotai.importer import run_import
    from ligaotai.scenes import run_split

    (story_book.story_src / "2.txt").write_text("第三章 天机\n改成了别的内容。", encoding="utf-8")
    run_import(story_book, story_book.story_src)
    run_split(story_book)
    m = collect_mentions(story_book)
    assert "林姑娘" not in m["person"] and "天机阁" not in m["organization"]


def test_core():
    assert core("唐師父") == "唐"
    assert core("阿清") == "清"
    assert core("清兒") == "清"
    assert core("師父") == "師父"


def test_hint_pairs():
    pairs = {frozenset((a, b)) for a, b, _ in hint_pairs(["孫悟空", "悟空", "孫行者", "行者", "八戒", "阿清", "清兒"])}
    assert frozenset(("悟空", "孫悟空")) in pairs
    assert frozenset(("行者", "孫行者")) in pairs
    assert frozenset(("阿清", "清兒")) in pairs
    assert not any("八戒" in p for p in pairs)


def test_chunk_names():
    names = [f"n{i}" for i in range(10)]
    assert chunk_names(names, 20, 3) == [names]
    chunks = chunk_names(names, 6, 2)
    assert chunks == [["n0", "n1", "n2", "n3", "n4", "n5"], ["n0", "n1", "n6", "n7", "n8", "n9"]]
