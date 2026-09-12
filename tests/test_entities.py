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


import pytest

from ligaotai import entities as ent
from ligaotai.entities import check_groups, clean_groups, merge_groups, run_entities
from ligaotai.fsutil import read_json, write_json

LIN = ["林清", "清儿", "林姑娘"]


def test_check_groups():
    allowed = {"林清", "清儿", "赵五"}
    assert check_groups({"groups": [{"canonical": "林清", "members": ["林清", "清儿"]}]}, allowed) == []
    assert check_groups({"x": 1}, allowed) == ["缺少 groups 列表"]
    problems = check_groups(
        {"groups": [
            {"canonical": "张三", "members": ["林清", "张三"]},
            {"canonical": "清儿", "members": ["清儿", "林清"]},
        ]},
        allowed,
    )
    text = "；".join(problems)
    assert "张三" in text and "同时出现在两个组" in text


def test_clean_groups():
    data = {"groups": [
        {"canonical": "张三", "members": ["林清", "张三", "清儿"], "reason": "r"},
        {"canonical": "清儿", "members": ["清儿", "赵五"]},
        {"canonical": "赵五", "members": ["赵五"]},
    ]}
    assert clean_groups(data, {"林清", "清儿", "赵五"}) == [
        {"canonical": "林清", "members": ["林清", "清儿"], "reason": "r"}
    ]


def test_merge_groups_across_chunks():
    groups = [
        {"canonical": "清儿", "members": ["清儿", "林清"], "reason": "a"},
        {"canonical": "林清", "members": ["林清", "林姑娘"], "reason": "b"},
        {"canonical": "赵五", "members": ["赵五", "老赵"], "reason": ""},
    ]
    merged = merge_groups(groups, {"林清": 5, "清儿": 2, "林姑娘": 1, "赵五": 3, "老赵": 1})
    assert merged[0] == {"canonical": "林清", "members": ["林清", "清儿", "林姑娘"], "reason": "a；b"}
    assert merged[1]["canonical"] == "赵五"


def test_run_entities_groups_aliases(story_book):
    run_cards(story_book, client_for(story_book))
    c = client_for(story_book, groups=[LIN])
    summary = run_entities(story_book, c)
    data = read_json(story_book.entities_path)
    persons = [e for e in data["entities"] if e["type"] == "person"]
    draft = [e for e in persons if e["status"] == "draft"]
    assert len(draft) == 1 and set(draft[0]["names"]) == set(LIN)
    assert draft[0]["canonical"] == "林清"
    assert [e["canonical"] for e in persons if e["status"] == "single"] == ["赵五"]
    assert {e["type"] for e in data["entities"]} == {"person", "location", "organization"}
    assert c.usage.calls == 1  # 地点、组织各只有一个叫法，不调模型
    assert summary["draft_groups"] == 1
    assert story_book.step("entities")["status"] == "done"
    assert story_book.load()["usage"]["by_step"]["entities"]["calls"] == 1


def test_confirmed_group_survives_rerun(story_book):
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    data = read_json(story_book.entities_path)
    group = next(e for e in data["entities"] if e["status"] == "draft")
    group["status"] = "confirmed"
    write_json(story_book.entities_path, data)

    run_entities(story_book, client_for(story_book, groups=[["林清", "赵五"]]))
    data = read_json(story_book.entities_path)
    kept = next(e for e in data["entities"] if e["id"] == group["id"])
    assert kept["status"] == "confirmed" and set(kept["names"]) == set(LIN)
    zhao = next(e for e in data["entities"] if e["canonical"] == "赵五")
    assert zhao["status"] == "single"
    assert len({e["id"] for e in data["entities"]}) == len(data["entities"])


def test_names_split_into_chunks(story_book, monkeypatch):
    run_cards(story_book, client_for(story_book))
    monkeypatch.setattr(ent, "MAX_NAMES_PER_CALL", 3)
    monkeypatch.setattr(ent, "ANCHOR_NAMES", 1)
    c = client_for(story_book, groups=[LIN])
    run_entities(story_book, c)
    assert c.usage.calls == 2
    data = read_json(story_book.entities_path)
    assert sum(e["status"] == "draft" for e in data["entities"]) == 1
