import json
import threading

import pytest
from helpers import FakeBackend, fake_ai_handler, names_from_prompt

from ligaotai import entities as ent
from ligaotai.cards import run_cards
from ligaotai.config import AppConfig, TierConfig
from ligaotai.entities import (
    canonical_map,
    check_groups,
    chunk_names,
    clean_groups,
    collect_mentions,
    confirm,
    core,
    hint_pairs,
    merge,
    merge_groups,
    rename,
    run_entities,
    split,
)
from ligaotai.fsutil import read_json, write_json
from ligaotai.jobs import JobCancelled
from ligaotai.llm import FatalLLMError, LLMClient
from ligaotai.scenes import Scene

LIN = ["林清", "清儿", "林姑娘"]


def client_for(book, groups=(), **cfg):
    return LLMClient(AppConfig(**cfg), FakeBackend(handler=fake_ai_handler(groups)), log_dir=book.logs_dir)


def client_with(book, fn, **cfg):
    """实体合并那一步的回复交给 fn(这批的叫法列表) 现算；fn 可以返回字符串，也可以返回异常实例（会被抛出）。"""
    base = fake_ai_handler()

    def handler(tier, messages):
        if "归成一组" in messages[0]["content"]:
            return fn(names_from_prompt(messages))
        return base(tier, messages)

    return LLMClient(AppConfig(**cfg), FakeBackend(handler=handler), log_dir=book.logs_dir)


def reply(*groups):
    return json.dumps(
        {"groups": [{"canonical": g[0], "members": list(g), "reason": "测试"} for g in groups]}, ensure_ascii=False
    )


class Denied(Exception):
    status_code = 401


def entities_of(book, typ="person"):
    return [e for e in read_json(book.entities_path)["entities"] if e["type"] == typ]


def by_canonical(book):
    return {e["canonical"]: e for e in entities_of(book)}


# --- 汇总叫法 ---


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


def fake_book(monkeypatch, scenes, cards):
    """不走导入/切场景，直接给 collect_mentions 喂场景和卡。scenes: [(编号, 原文, 是否已删除)]。"""
    objs = [
        Scene(id=sid, source="a.txt", index=i, start=0, end=0, chars=len(t), hash=f"h-{sid}", removed=rm, text=t)
        for i, (sid, t, rm) in enumerate(scenes, 1)
    ]
    records = {sid: {"id": sid, "scene_hash": f"h-{sid}", "card": c} for sid, c in cards.items()}
    monkeypatch.setattr(ent, "load_scenes", lambda book, with_text=False: objs)
    monkeypatch.setattr(ent, "load_cards", lambda book: records)


def card(persons=(), pov="", locations=()):
    return {
        "pov": pov,
        "characters": [{"name": n, "role": "主要"} for n in persons],
        "locations": list(locations),
        "organizations": [],
    }


def test_collect_mentions_details(monkeypatch):
    fake_book(
        monkeypatch,
        [
            ("S-0001", "林清来了。", False),
            ("S-0002", "林清又来了，\n\n  林清笑了。", False),
            ("S-0003", "林清第三次来。", False),
            ("S-0004", "林清和赵五在删掉的场景里。", True),
        ],
        {
            "S-0001": card(["林清", "  "], pov="林清"),
            "S-0002": card(["林清"]),
            "S-0003": card(["林清"], locations=["　"]),
            "S-0004": card(["林清", "赵五"]),
        },
    )
    m = collect_mentions(None)
    lin = m["person"]["林清"]
    assert lin.scenes == ["S-0001", "S-0002", "S-0003"]  # 已删除的场景跳过；pov 和角色同名只记一次
    assert len(lin.contexts) == 2  # 上下文最多 2 段
    assert lin.contexts[1] == "林清又来了， 林清笑了。"  # 空白压成一个空格
    assert set(m["person"]) == {"林清"}  # 空名字丢掉；赵五只出现在已删除的场景里
    assert m["location"] == {}


def test_collect_mentions_drops_pronouns(monkeypatch):
    fake_book(
        monkeypatch,
        [("S-0001", "我对你说，他们和她們都走了，咱们也走吧，林清。", False)],
        {"S-0001": card(["我", "你", "他们", "她們", "咱们", "自己", "林清"], pov="我")},
    )
    assert set(collect_mentions(None)["person"]) == {"林清"}


# --- 字面提示 ---


def test_core():
    assert core("唐師父") == "唐"
    assert core("阿清") == "清"
    assert core("清兒") == "清"
    assert core("師父") == "師父"


def test_core_keeps_titles_whole():
    for title in ("師兄", "师兄", "長老", "长老", "老爺", "老爷", "小姐", "姑娘", "大王"):
        assert core(title) == title
    assert core("林老爷") == "林" and core("王小姐") == "王" and core("赵大哥") == "赵"


def test_hint_pairs():
    pairs = {frozenset((a, b)) for a, b, _ in hint_pairs(["孫悟空", "悟空", "孫行者", "行者", "八戒", "阿清", "清兒"])}
    assert frozenset(("悟空", "孫悟空")) in pairs
    assert frozenset(("行者", "孫行者")) in pairs
    assert frozenset(("阿清", "清兒")) in pairs
    assert not any("八戒" in p for p in pairs)


def test_hint_pairs_noise_does_not_crowd_out_containment():
    surnames = "王李张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗"
    titles = ["大人", "公子", "老爷", "兄", "姑娘", "夫人", "先生", "大哥", "小姐"]
    names = [s + t for s in surnames for t in titles] + ["老" + s for s in surnames] + ["小" + s for s in surnames]
    names += ["姑娘", "公子", "大人", "师父", "师兄", "师弟", "长老", "老爷"]
    names += ["孙悟空", "悟空", "孙行者", "行者", "猪八戒", "八戒"]
    assert len(names) > 230
    pairs = hint_pairs(names)
    assert len(pairs) <= ent.HINT_LIMIT
    kept = {frozenset((a, b)) for a, b, _ in pairs}
    for a, b in [("孙悟空", "悟空"), ("孙行者", "行者"), ("猪八戒", "八戒")]:
        assert frozenset((a, b)) in kept
    assert frozenset(("黄夫人", "黄兄")) not in kept  # 只剩一个姓的组太大，不两两出提示
    assert not any("姑娘" in (a, b) for a, b, _ in pairs)  # 泛称不当包含关系里较短的那个


def test_hint_pairs_nickname_matches_full_name():
    pairs = {frozenset((a, b)) for a, b, _ in hint_pairs(["林清", "清儿", "林姑娘", "赵五", "老赵", "小清", "阿清"])}
    for nick in ("清儿", "小清", "阿清"):
        assert frozenset((nick, "林清")) in pairs
    assert frozenset(("老赵", "赵五")) not in pairs  # 老X 跟姓连用，不算昵称


# --- 分批 ---


def test_chunk_names():
    names = [f"n{i}" for i in range(10)]
    assert chunk_names(names, 20, 3) == [names]
    chunks = chunk_names(names, 6, 2)
    assert chunks == [["n0", "n1", "n2", "n3", "n4", "n5"], ["n0", "n1", "n6", "n7", "n8", "n9"]]


def test_chunk_names_keeps_linked_names_together():
    names = ["A", "x1", "y1", "x2", "y2"]
    assert chunk_names(names, 3, 1) == [["A", "x1", "y1"], ["A", "x2", "y2"]]
    linked = chunk_names(names, 3, 1, [("x1", "x2", "r"), ("y2", "y1", "r")])
    assert linked == [["A", "x1", "x2"], ["A", "y1", "y2"]]


def test_chunk_names_even_split_and_bad_anchors():
    names = [f"n{i}" for i in range(601)]
    chunks = chunk_names(names, 600, 150)
    assert [len(c) for c in chunks] == [376, 375]
    assert all(c[:150] == names[:150] for c in chunks)
    assert sorted(n for c in chunks for n in c[150:]) == sorted(names[150:])
    assert chunk_names([], 5, 2) == [[]]
    for anchors in (5, 7):
        with pytest.raises(ValueError):
            chunk_names(names, 5, anchors)


# --- 模型归组、跨批合并 ---


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


def g(canonical, *members, reason="r"):
    return {"canonical": canonical, "members": list(members), "reason": reason}


def test_merge_groups_across_chunks():
    merged, conflicts = merge_groups(
        [
            [g("清儿", "清儿", "林清", reason="a"), g("赵五", "赵五", "老赵", reason="")],
            [g("林清", "林清", "林姑娘", reason="b")],
        ],
        {"林清": 5, "清儿": 2, "林姑娘": 1, "赵五": 3, "老赵": 1},
        anchors=["林清", "赵五"],
    )
    assert merged[0] == {"canonical": "林清", "members": ["林清", "清儿", "林姑娘"], "reason": "a；b"}
    assert merged[1]["canonical"] == "赵五"
    assert conflicts == []


def test_merge_groups_anchor_conflict_is_not_merged():
    merged, conflicts = merge_groups(
        [
            [g("唐僧", "唐僧", "师父"), g("孙悟空", "孙悟空", "行者")],
            [g("孙悟空", "孙悟空", "师父")],
        ],
        {"唐僧": 50, "孙悟空": 80, "师父": 60, "行者": 30},
        anchors=["孙悟空", "师父", "唐僧"],
    )
    assert sorted(sorted(x["members"]) for x in merged) == sorted([sorted(["唐僧", "师父"]), sorted(["孙悟空", "行者"])])
    assert conflicts == [{"chunk": 2, "names": ["孙悟空", "师父"]}]


def test_merge_groups_first_chunk_with_result_decides_anchors():
    merged, conflicts = merge_groups(
        [None, [g("孙悟空", "孙悟空", "悟空")], [g("悟空", "悟空", "猴王")]],
        {"孙悟空": 9, "悟空": 8, "猴王": 1},
        anchors=["孙悟空", "悟空"],
    )
    assert [set(x["members"]) for x in merged] == [{"孙悟空", "悟空", "猴王"}] and conflicts == []


def test_merge_groups_canonical_by_votes():
    batches = [[g("孙悟空", "孙悟空", "悟空")] for _ in range(4)] + [[g("悟空", "悟空", "孙悟空")]]
    merged, _ = merge_groups(batches, {"孙悟空": 10, "悟空": 50}, anchors=["孙悟空", "悟空"])
    assert [m["canonical"] for m in merged] == ["孙悟空"]


# --- 步骤 5 ---


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
    assert data["next_id"] == 5
    assert c.usage.calls == 1  # 地点、组织各只有一个叫法，不调模型
    assert summary["draft_groups"] == 1 and summary["chunks"] == 1
    assert summary["failed_chunks"] == [] and summary["conflicts"] == [] and summary["unresolved"] == []
    assert story_book.step("entities")["status"] == "done"
    assert story_book.load()["usage"]["by_step"]["entities"]["calls"] == 1


def test_confirmed_group_survives_rerun(story_book):
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    data = read_json(story_book.entities_path)
    group = next(e for e in data["entities"] if e["status"] == "draft")
    group["status"] = "confirmed"
    group["names"] = ["林清", "清儿"]  # 林姑娘放出来，人物还剩两个可以重算的名字，模型才会被调用
    write_json(story_book.entities_path, data)
    story_book.entities_cache_path.unlink()

    c = client_for(story_book, groups=[["林清", "赵五"]])
    run_entities(story_book, c)
    assert c.usage.calls == 1
    data = read_json(story_book.entities_path)
    kept = next(e for e in data["entities"] if e["id"] == group["id"])
    assert kept["status"] == "confirmed" and set(kept["names"]) == {"林清", "清儿"}
    persons = by_canonical(story_book)
    assert persons["赵五"]["status"] == "single" and persons["林姑娘"]["status"] == "single"
    assert len({e["id"] for e in data["entities"]}) == len(data["entities"])


def test_names_split_into_chunks(story_book, monkeypatch):
    """锚点（出现最多的两个：赵五、林姑娘）每批都在；林清、清儿各在一批，靠锚点林姑娘跨批合上。"""
    run_cards(story_book, client_for(story_book))
    monkeypatch.setattr(ent, "MAX_NAMES_PER_CALL", 3)
    monkeypatch.setattr(ent, "ANCHOR_NAMES", 2)
    c = client_for(story_book, groups=[LIN])
    s = run_entities(story_book, c)
    assert c.usage.calls == 2 and s["chunks"] == 2
    draft = [e for e in entities_of(story_book) if e["status"] == "draft"]
    assert len(draft) == 1 and set(draft[0]["names"]) == set(LIN)
    assert draft[0]["canonical"] == "林清"


def test_linked_names_share_a_chunk(story_book, monkeypatch):
    run_cards(story_book, client_for(story_book))
    monkeypatch.setattr(ent, "MAX_NAMES_PER_CALL", 3)
    monkeypatch.setattr(ent, "ANCHOR_NAMES", 1)
    c = client_for(story_book, groups=[LIN])
    run_entities(story_book, c)
    prompts = [names_from_prompt(call["messages"]) for call in c.backend.calls]
    assert len(prompts) == 2 and any({"林清", "清儿"} <= set(p) for p in prompts)
    draft = [e for e in entities_of(story_book) if e["status"] == "draft"]
    assert [set(e["names"]) for e in draft] == [{"林清", "清儿"}]


def test_anchor_conflict_between_chunks_is_reported_not_merged(story_book, monkeypatch):
    run_cards(story_book, client_for(story_book))
    monkeypatch.setattr(ent, "MAX_NAMES_PER_CALL", 3)
    monkeypatch.setattr(ent, "ANCHOR_NAMES", 2)

    def fn(names):
        if "林清" in names:  # 第一批：分对了，赵五单独
            return reply(["林清", "林姑娘"])
        return reply(["赵五", "林姑娘"])  # 第二批：把两个锚点连到了一起

    s = run_entities(story_book, client_with(story_book, fn))
    persons = by_canonical(story_book)
    assert set(persons["林清"]["names"]) == {"林清", "林姑娘"} and persons["林清"]["status"] == "draft"
    assert persons["赵五"]["status"] == "single" and persons["清儿"]["status"] == "single"
    assert s["conflicts"] == [{"type": "person", "chunk": 2, "names": ["赵五", "林姑娘"]}]


# --- 失败、暂停、缓存 ---


def test_failed_chunk_is_reported_and_step_still_done(story_book, monkeypatch):
    run_cards(story_book, client_for(story_book))
    monkeypatch.setattr(ent, "MAX_NAMES_PER_CALL", 3)
    monkeypatch.setattr(ent, "ANCHOR_NAMES", 2)

    def fn(names):
        return reply(["林清", "林姑娘"]) if "林清" in names else ""  # 第二批一直返回空内容

    c = client_with(story_book, fn)
    s = run_entities(story_book, c)
    assert c.usage.calls == 1 + 3
    assert [(f["type"], f["chunk"]) for f in s["failed_chunks"]] == [("person", 2)]
    assert story_book.step("entities")["status"] == "done"
    persons = by_canonical(story_book)
    assert set(persons["林清"]["names"]) == {"林清", "林姑娘"} and persons["清儿"]["status"] == "single"

    c2 = client_for(story_book, groups=[LIN])  # 失败的那批没进缓存，重跑只补它
    s2 = run_entities(story_book, c2)
    assert c2.usage.calls == 1 and s2["failed_chunks"] == []
    assert set(by_canonical(story_book)["林清"]["names"]) == set(LIN)


def test_fatal_error_aborts_but_keeps_finished_chunks(story_book, monkeypatch):
    run_cards(story_book, client_for(story_book))
    monkeypatch.setattr(ent, "MAX_NAMES_PER_CALL", 3)
    monkeypatch.setattr(ent, "ANCHOR_NAMES", 2)

    def fn(names):
        return reply(["林清", "林姑娘"]) if "林清" in names else Denied("欠费")

    with pytest.raises(FatalLLMError):
        run_entities(story_book, client_with(story_book, fn))
    assert not story_book.entities_path.exists()
    assert story_book.load()["usage"]["by_step"]["entities"]["calls"] == 1
    assert len(read_json(story_book.entities_cache_path)) == 1

    c = client_for(story_book, groups=[LIN])
    run_entities(story_book, c)
    assert c.usage.calls == 1


def test_fatal_error_wins_over_pause(story_book, monkeypatch):
    run_cards(story_book, client_for(story_book))
    monkeypatch.setattr(ent, "MAX_NAMES_PER_CALL", 3)
    monkeypatch.setattr(ent, "ANCHOR_NAMES", 2)

    def fn(names):
        return reply(["林清", "林姑娘"]) if "林清" in names else Denied("欠费")

    def progress(done, total):
        if done >= 1:
            raise JobCancelled()

    with pytest.raises(FatalLLMError):
        run_entities(story_book, client_with(story_book, fn), progress)


def test_pause_keeps_finished_chunks(story_book, monkeypatch):
    run_cards(story_book, client_for(story_book))
    monkeypatch.setattr(ent, "MAX_NAMES_PER_CALL", 3)
    monkeypatch.setattr(ent, "ANCHOR_NAMES", 2)

    def progress(done, total):
        if done >= 1:
            raise JobCancelled()

    with pytest.raises(JobCancelled):
        run_entities(story_book, client_for(story_book, groups=[LIN], concurrency=1), progress)
    assert not story_book.entities_path.exists()
    assert story_book.load()["usage"]["by_step"]["entities"]["calls"] == 1
    assert len(read_json(story_book.entities_cache_path)) == 1

    c = client_for(story_book, groups=[LIN])
    run_entities(story_book, c)
    assert c.usage.calls == 1
    assert set(by_canonical(story_book)["林清"]["names"]) == set(LIN)


def test_rerun_uses_cache_and_prunes_unused_entries(story_book):
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    cache = read_json(story_book.entities_cache_path)
    assert len(cache) == 1
    write_json(story_book.entities_cache_path, {**cache, "old": {"groups": [], "problems": []}})

    c = client_for(story_book, groups=[])  # 缓存命中：不调模型，也就不看它这次会说什么
    run_entities(story_book, c)
    assert c.usage.calls == 0
    assert read_json(story_book.entities_cache_path) == cache
    assert set(by_canonical(story_book)["林清"]["names"]) == set(LIN)

    c2 = client_for(story_book, groups=[LIN], synth=TierConfig(model="another-model"))  # 换了综合档模型要重调
    run_entities(story_book, c2)
    assert c2.usage.calls == 1


def test_unresolved_problems_are_reported(story_book):
    run_cards(story_book, client_for(story_book))
    c = client_with(story_book, lambda names: reply(["林清", "清儿", "张三"]))
    s = run_entities(story_book, c)
    assert c.usage.calls == 3
    [u] = s["unresolved"]
    assert (u["type"], u["chunk"]) == ("person", 1) and "张三" in "".join(u["problems"])
    assert set(by_canonical(story_book)["林清"]["names"]) == {"林清", "清儿"}


def test_type_with_fewer_than_two_free_names_is_not_sent(story_book):
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    data = read_json(story_book.entities_path)
    next(e for e in data["entities"] if e["status"] == "draft")["status"] = "confirmed"
    write_json(story_book.entities_path, data)
    story_book.entities_cache_path.unlink()

    c = client_for(story_book, groups=[LIN])
    s = run_entities(story_book, c)
    assert c.usage.calls == 0 and s["chunks"] == 0
    assert by_canonical(story_book)["赵五"]["status"] == "single"


# --- 读写窗口、编号、状态 ---


def test_author_confirm_during_run_is_kept(story_book):
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    story_book.entities_cache_path.unlink()
    touched = []

    def fn(names):  # 模型还在算的时候，作者在界面上确认了一个草稿、还改了规范名
        data = read_json(story_book.entities_path)
        d = next(e for e in data["entities"] if e["status"] == "draft")
        d["status"], d["canonical"] = "confirmed", "林小清"
        write_json(story_book.entities_path, data)
        touched.append(d["id"])
        return reply(["林清", "清儿"])

    run_entities(story_book, client_with(story_book, fn))
    kept = next(e for e in entities_of(story_book) if e["id"] == touched[0])
    assert kept["status"] == "confirmed" and kept["canonical"] == "林小清" and set(kept["names"]) == set(LIN)
    assert not any(e["status"] == "draft" for e in entities_of(story_book))


def test_identical_rerun_keeps_ids_and_does_not_outdate(story_book):
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    first = read_json(story_book.entities_path)
    story_book.set_step("threads", "done")

    run_entities(story_book, client_for(story_book, groups=[LIN]))
    second = read_json(story_book.entities_path)
    assert [(e["id"], e["canonical"]) for e in second["entities"]] == [(e["id"], e["canonical"]) for e in first["entities"]]
    assert second["next_id"] == first["next_id"] == 5
    assert story_book.step("threads")["status"] == "done"

    del second["next_id"]  # 旧文件没有 next_id：按现有最大编号 + 1 算
    write_json(story_book.entities_path, second)
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    assert read_json(story_book.entities_path)["next_id"] == 5


def test_deleted_max_id_is_never_reused(story_book):
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    data = read_json(story_book.entities_path)
    top = max(data["entities"], key=lambda e: e["id"])
    data["entities"].remove(top)
    write_json(story_book.entities_path, data)

    run_entities(story_book, client_for(story_book, groups=[LIN]))
    after = read_json(story_book.entities_path)
    assert top["id"] not in {e["id"] for e in after["entities"]}
    again = next(e for e in after["entities"] if e["canonical"] == top["canonical"])
    assert again["id"] == "E-0005" and after["next_id"] == 6


def test_unknown_status_is_kept(story_book):
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    data = read_json(story_book.entities_path)
    target = next(e for e in data["entities"] if e["status"] == "draft")
    target["status"] = "ignored"
    write_json(story_book.entities_path, data)

    run_entities(story_book, client_for(story_book, groups=[]))
    after = entities_of(story_book)
    kept = next(e for e in after if e["id"] == target["id"])
    assert kept["status"] == "ignored" and set(kept["names"]) == set(LIN)
    assert not any(e["status"] == "single" and e["canonical"] in LIN for e in after)


# --- 作者的确认 / 改名 / 合并 / 拆分 ---


@pytest.fixture
def grouped(story_book):
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    story_book.set_step("threads", "done")
    return story_book


def find(book, canonical):
    return next(e for e in read_json(book.entities_path)["entities"] if e["canonical"] == canonical)


def test_confirm(grouped):
    e = find(grouped, "林清")
    out = confirm(grouped, [e["id"], e["id"]])  # 重复的 id 只返回一次
    assert len(out) == 1 and out[0]["status"] == "confirmed" and find(grouped, "林清")["status"] == "confirmed"
    assert grouped.step("threads")["status"] == "done"  # 确认不改规范名映射，下游不过期


def test_confirm_without_changes_does_not_write(grouped, monkeypatch):
    e = find(grouped, "林清")
    confirm(grouped, [e["id"]])
    writes = []
    monkeypatch.setattr(ent, "write_json", lambda path, data: writes.append(path))
    assert confirm(grouped, []) == []
    assert [x["id"] for x in confirm(grouped, [e["id"]])] == [e["id"]]  # 已经确认过
    assert writes == []


def test_rename(grouped):
    zhao = find(grouped, "赵五")
    rename(grouped, zhao["id"], " 赵五 ")  # 改成同一个名字：状态变已确认，但规范名映射没变，下游不过期
    assert find(grouped, "赵五")["status"] == "confirmed"
    assert grouped.step("threads")["status"] == "done"

    e = find(grouped, "林清")
    assert rename(grouped, e["id"], " 林小清 ")["canonical"] == "林小清"
    saved = next(x for x in read_json(grouped.entities_path)["entities"] if x["id"] == e["id"])
    assert saved["canonical"] == "林小清" and saved["status"] == "confirmed"  # 写回了文件
    assert grouped.step("threads")["status"] == "outdated"
    with pytest.raises(ValueError):
        rename(grouped, e["id"], "  ")


def test_merge(grouped):
    lin, zhao = find(grouped, "林清"), find(grouped, "赵五")
    out = merge(grouped, [lin["id"], zhao["id"]])
    assert out["id"] == lin["id"] and set(out["names"]) == set(LIN) | {"赵五"}
    assert out["scenes"] == ["S-0001", "S-0002", "S-0003"] and out["status"] == "confirmed"
    ids = [e["id"] for e in read_json(grouped.entities_path)["entities"]]
    assert zhao["id"] not in ids
    assert grouped.step("threads")["status"] == "outdated"


def test_merge_rejects_bad_input(grouped):
    lin, place = find(grouped, "林清"), find(grouped, "青州城外")
    with pytest.raises(ValueError):
        merge(grouped, [lin["id"]])
    with pytest.raises(ValueError):
        merge(grouped, [lin["id"], place["id"]])
    with pytest.raises(KeyError):
        merge(grouped, [lin["id"], "E-9999"])


def test_split(grouped):
    lin = find(grouped, "林清")
    new = split(grouped, lin["id"], ["林姑娘"])
    assert new["names"] == ["林姑娘"] and new["scenes"] == ["S-0003"] and new["status"] == "confirmed"
    rest = find(grouped, "林清")
    assert set(rest["names"]) == {"林清", "清儿"} and rest["scenes"] == ["S-0001", "S-0002"]
    with pytest.raises(ValueError):
        split(grouped, lin["id"], ["林清", "清儿"])
    with pytest.raises(ValueError):
        split(grouped, lin["id"], ["不存在"])


def test_split_after_merge_does_not_reuse_deleted_max_id(grouped):
    """先拆出一个新实体（拿到当时最大的编号），把它合并掉（删掉当时的最大号），
    再拆一次：新编号必须接着 next_id 往后排，不能因为「当前最大号」变小了就把刚被删的号发出去。"""
    lin, zhao = find(grouped, "林清"), find(grouped, "赵五")
    moved = split(grouped, lin["id"], ["林姑娘"])  # 新建的实体此刻是编号最大的
    before = read_json(grouped.entities_path)
    assert before["next_id"] == ent._id_num(moved["id"]) + 1

    combined = merge(grouped, [zhao["id"], moved["id"]])  # 保留赵五，删掉刚才那个最大号
    ids_after_merge = {e["id"] for e in read_json(grouped.entities_path)["entities"]}
    assert moved["id"] not in ids_after_merge

    again = split(grouped, combined["id"], ["林姑娘"])
    assert ent._id_num(again["id"]) > ent._id_num(moved["id"])
    ids = [e["id"] for e in read_json(grouped.entities_path)["entities"]]
    assert moved["id"] not in ids and ids.count(again["id"]) == 1


def test_canonical_map(grouped):
    m = canonical_map(grouped)
    assert m[("person", "清儿")] == "林清" and m[("person", "赵五")] == "赵五"
    assert m[("location", "青州城外")] == "青州城外"


def test_ops_before_run_raise(story_book):
    with pytest.raises(FileNotFoundError):
        confirm(story_book, ["E-0001"])


# --- 顺手修的 Minor ---


def test_cache_write_failure_does_not_fail_the_step(story_book, monkeypatch):
    """缓存目录写不进去（比如磁盘只读、被占用）不该让这一步跟着失败：大不了下次重跑再花一次钱。"""
    run_cards(story_book, client_for(story_book))
    real_write_json = ent.write_json

    def flaky(path, data):
        if path == story_book.entities_cache_path:
            raise OSError("模拟磁盘写入失败")
        return real_write_json(path, data)

    monkeypatch.setattr(ent, "write_json", flaky)
    s = run_entities(story_book, client_for(story_book, groups=[LIN]))
    assert s["draft_groups"] == 1
    assert not story_book.entities_cache_path.exists()  # 缓存确实没写成功，但这不影响实体.json


def test_load_cache_drops_malformed_entries(book, monkeypatch):
    good = {"groups": [{"canonical": "a", "members": ["a", "b"], "reason": ""}], "problems": []}
    data = {
        "good": good,
        "not_a_dict": "oops",
        "bad_groups": {"groups": "oops", "problems": []},
        "bad_problems": {"groups": [], "problems": "oops"},
        "missing_problems": {"groups": []},
    }
    monkeypatch.setattr(ent, "read_json", lambda path, default=None: data)
    assert ent._load_cache(book) == {"good": good}


def test_assemble_tolerates_non_int_next_id():
    old = {"next_id": "oops", "entities": [{"id": "E-0002", "type": "person", "canonical": "a",
                                             "names": ["a"], "status": "confirmed", "reason": "", "scenes": []}]}
    mentions = {t: {} for t in ent.TYPES}
    out = ent._assemble(old, mentions, {})
    assert out["next_id"] == 3  # 非 int 的 next_id 当 0 处理，退回按现有最大编号 + 1 兜底


def test_cache_key_changes_with_synth_tier_settings(story_book):
    """模型名没变，只改了综合档的思考强度：缓存键要跟着变，不能误命中旧缓存。"""
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))
    assert len(read_json(story_book.entities_cache_path)) == 1

    same_model_diff_effort = TierConfig(model="deepseek-flash", thinking="on", effort="low", max_tokens=32768)
    c2 = client_for(story_book, groups=[LIN], synth=same_model_diff_effort)
    run_entities(story_book, c2)
    assert c2.usage.calls == 1  # 没有命中缓存，重新调了模型


def test_affixes_two_char_generic_terms():
    for name, expect in [
        ("张阿哥", "张"), ("王大姐", "王"), ("李阿姐", "李"),
        ("赵小哥", "赵"), ("钱小妹", "钱"), ("孙师妹", "孙"), ("孙師妹", "孙"),
    ]:
        assert core(name) == expect
    for title in ("阿哥", "大姐", "阿姐", "小哥", "小妹", "师妹", "師妹"):
        assert core(title) == title  # 称谓本身原样返回，不再被单字词缀拆开


# --- 任务 11 审查意见 ---


def test_merge_canonical_param(grouped):
    lin, zhao = find(grouped, "林清"), find(grouped, "赵五")
    before = read_json(grouped.entities_path)
    for blank in ("", "   "):
        with pytest.raises(ValueError):
            merge(grouped, [lin["id"], zhao["id"]], canonical=blank)
    assert read_json(grouped.entities_path) == before  # 报错时什么都没写
    out = merge(grouped, [lin["id"], zhao["id"]], canonical=" 新名 ")
    assert out["canonical"] == "新名" and find(grouped, "新名")["id"] == lin["id"]
    m = canonical_map(grouped)
    assert all(m[("person", n)] == "新名" for n in [*LIN, "赵五"])


def test_merge_recomputes_scenes_and_orders_names(grouped):
    """存盘的场景列表过时了（场景卡重做过、步骤 5 没重跑）：合并按当前场景卡重算，名字按出现次数排。"""
    data = read_json(grouped.entities_path)
    lin = next(e for e in data["entities"] if e["canonical"] == "林清")
    lin["scenes"] = ["S-0099"]
    lin["names"] = list(reversed(lin["names"]))
    write_json(grouped.entities_path, data)
    zhao = find(grouped, "赵五")
    out = merge(grouped, [lin["id"], zhao["id"]])
    assert out["scenes"] == ["S-0001", "S-0002", "S-0003"]
    assert out["names"][0] == "赵五"  # 赵五出现在两个场景，其余各一个
    assert out["names"] == ent._order_names(out["names"], collect_mentions(grouped)["person"])
    assert find(grouped, "林清")["scenes"] == out["scenes"]


def test_split_moves_canonical(grouped):
    lin = find(grouped, "林清")
    new = split(grouped, lin["id"], ["林清"])
    assert new["canonical"] == "林清" and new["names"] == ["林清"] and new["scenes"] == ["S-0001"]
    rest = next(e for e in read_json(grouped.entities_path)["entities"] if e["id"] == lin["id"])
    assert rest["canonical"] in rest["names"] and "林清" not in rest["names"]
    assert set(rest["names"]) == {"清儿", "林姑娘"} and rest["scenes"] == ["S-0002", "S-0003"]
    m = canonical_map(grouped)
    assert m[("person", "林清")] == "林清" and m[("person", "清儿")] == rest["canonical"]
    assert grouped.step("threads")["status"] == "outdated"


def test_cache_key_ignores_max_tokens_and_key_but_not_api_base(story_book):
    run_cards(story_book, client_for(story_book))
    run_entities(story_book, client_for(story_book, groups=[LIN]))

    bigger = TierConfig(thinking="on", effort="high", max_tokens=65536)  # 只改上限：照样命中
    c = client_for(story_book, groups=[LIN], synth=bigger)
    run_entities(story_book, c)
    assert c.usage.calls == 0

    relay = "https://relay.example.com/v1"  # 模型名一样、换了服务商：不能命中
    c2 = client_for(story_book, groups=[LIN], api_base=relay)
    run_entities(story_book, c2)
    assert c2.usage.calls == 1

    c3 = client_for(story_book, groups=[LIN], api_base=relay, api_key="sk-test-not-a-real-key")  # 换 key 不影响
    run_entities(story_book, c3)
    assert c3.usage.calls == 0


def _locked(book) -> dict:
    data = read_json(book.entities_path)
    return {e["id"]: {k: v for k, v in e.items() if k != "scenes"} for e in data["entities"]
            if e["status"] not in ("draft", "single")}


def _assert_rerun_keeps_author_work(book, client):
    before = read_json(book.entities_path)
    locked = _locked(book)
    book.entities_cache_path.unlink()
    run_entities(book, client)
    after = read_json(book.entities_path)
    now = _locked(book)
    assert {eid: now.get(eid) for eid in locked} == locked  # 作者确认过的实体原样保留
    seen = [(e["type"], n) for e in after["entities"] for n in e["names"]]
    assert len(seen) == len(set(seen))  # 没有叫法同时出现在两个实体里
    assert after["next_id"] >= before["next_id"]  # 编号只增不减
    return after


def test_rerun_after_split_merge_rename_confirm(grouped):
    lin, zhao = find(grouped, "林清"), find(grouped, "赵五")
    place, org = find(grouped, "青州城外"), find(grouped, "天机阁")
    moved = split(grouped, lin["id"], ["林姑娘"])
    merge(grouped, [zhao["id"], moved["id"]], canonical="赵五")  # 删掉刚发出去的最大号
    rename(grouped, org["id"], "天机阁总舵")
    confirm(grouped, [place["id"]])

    after = _assert_rerun_keeps_author_work(grouped, client_for(grouped, groups=[[*LIN, "赵五"]]))
    assert moved["id"] not in {e["id"] for e in after["entities"]}
    assert after["next_id"] > ent._id_num(moved["id"])


def test_rerun_after_rename_and_confirm_model_cannot_take_locked_names(grouped):
    zhao, place = find(grouped, "赵五"), find(grouped, "青州城外")
    rename(grouped, zhao["id"], "赵五爷")
    confirm(grouped, [place["id"]])

    c = client_for(grouped, groups=[[*LIN, "赵五"]])  # 模型想把已确认的赵五也拉进林清这组
    after = _assert_rerun_keeps_author_work(grouped, c)
    assert c.usage.calls == 1
    persons = [e for e in after["entities"] if e["type"] == "person"]
    draft = [e for e in persons if e["status"] == "draft"]
    assert len(draft) == 1 and set(draft[0]["names"]) == set(LIN)
    assert next(e for e in persons if e["id"] == zhao["id"])["canonical"] == "赵五爷"


def _probe_lock_held() -> bool:
    """另开一个线程试着不阻塞地拿 FILE_LOCK：拿不到（False）说明锁正被别的线程占着；
    万一拿到了，立刻释放，别把锁悬在那——调用方把返回值当探针结果，锁被改坏时这里会
    变成 True，断言随之失败，不靠计时去猜。"""
    got = []

    def probe():
        ok = ent.FILE_LOCK.acquire(blocking=False)
        got.append(ok)
        if ok:
            ent.FILE_LOCK.release()

    t = threading.Thread(target=probe)
    t.start()
    t.join(timeout=10)
    return got[0]


def test_confirm_during_step5_write_is_not_lost(grouped, monkeypatch):
    """步骤 5 读了旧 实体.json、还没写回的时候作者点了确认：确认要等步骤 5 写完再读改写，不能被它覆盖。"""
    draft = find(grouped, "林清")
    real_assemble = ent._assemble
    errors, workers, probe_results = [], [], []

    def author():
        try:
            confirm(grouped, [draft["id"]])
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def assemble(old, mentions, groups):  # 此时步骤 5 正拿着锁
        t = threading.Thread(target=author)
        workers.append(t)
        t.start()
        # 锁被步骤 5 占着：另一个线程非阻塞拿锁必须拿不到。
        probe_results.append(_probe_lock_held())
        return real_assemble(old, mentions, groups)

    monkeypatch.setattr(ent, "_assemble", assemble)
    run_entities(grouped, client_for(grouped, groups=[LIN]))
    workers[0].join(timeout=10)
    assert not workers[0].is_alive() and errors == []
    assert probe_results == [False]
    kept = find(grouped, "林清")
    assert kept["id"] == draft["id"] and kept["status"] == "confirmed"


def test_concurrent_confirms_keep_both(grouped, monkeypatch):
    lin, zhao = find(grouped, "林清"), find(grouped, "赵五")
    real_load = ent.load_entities
    first_loaded = threading.Event()
    errors, probe_results = [], []

    def load(book):
        data = real_load(book)
        if threading.current_thread().name == "first":  # 第一个确认拿着锁，读完文件、还没写回
            # 锁被第一个确认占着：另一个线程非阻塞拿锁必须拿不到。
            probe_results.append(_probe_lock_held())
            first_loaded.set()
        return data

    def run(eid):
        try:
            confirm(grouped, [eid])
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    monkeypatch.setattr(ent, "load_entities", load)
    t1 = threading.Thread(target=run, args=(lin["id"],), name="first")
    t2 = threading.Thread(target=run, args=(zhao["id"],), name="second")
    t1.start()
    assert first_loaded.wait(timeout=10)
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not t1.is_alive() and not t2.is_alive() and errors == []
    assert probe_results == [False]
    assert find(grouped, "林清")["status"] == "confirmed" and find(grouped, "赵五")["status"] == "confirmed"


def test_split_and_merge_read_cards_outside_lock(grouped, monkeypatch):
    """读全部场景卡的 collect_mentions 不能在锁里跑：另一个线程这时要能拿到锁。"""
    real_collect = ent.collect_mentions
    free = []

    def collect(book):
        got = []

        def probe():
            ok = ent.FILE_LOCK.acquire(blocking=False)
            got.append(ok)
            if ok:
                ent.FILE_LOCK.release()

        t = threading.Thread(target=probe)
        t.start()
        t.join(timeout=10)
        free.append(got == [True])
        return real_collect(book)

    monkeypatch.setattr(ent, "collect_mentions", collect)
    lin, zhao = find(grouped, "林清"), find(grouped, "赵五")
    moved = split(grouped, lin["id"], ["林姑娘"])
    merge(grouped, [zhao["id"], moved["id"]])
    assert free == [True, True]
