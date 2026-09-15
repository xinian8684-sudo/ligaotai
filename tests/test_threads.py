import asyncio
import json

import pytest
from helpers import FakeBackend, listed_scenes, seed_book, threads_handler

from ligaotai.config import AppConfig
from ligaotai.llm import FatalLLMError, LLMClient, LLMError
from ligaotai.threads import (
    Caller,
    ThreadDraft,
    WorldDraft,
    known_threads_text,
    stage_align,
    stage_gaps,
    stage_lines,
    stage_order,
    stage_worlds,
    thread_block,
)
from ligaotai.threads_input import Item


def client(book, **handlers):
    return LLMClient(AppConfig(), FakeBackend(handler=threads_handler(**handlers)), log_dir=book.logs_dir)


def items_of(*specs):
    """specs：场景编号，或者 (编号, 类型)。都在 a.txt 里，位置按顺序。"""
    out = {}
    for i, s in enumerate(specs):
        sid, kind = (s, "正文") if isinstance(s, str) else s
        out[sid] = Item(sid, "a.txt", i, kind, f"{sid}｜{kind}｜摘要{sid}")
    return out


def users(c, mark):
    """某一种调用发出去的全部 user 消息（按调用顺序）。"""
    return [x["messages"][1]["content"] for x in c.backend.calls if mark in x["messages"][0]["content"]]


GAPS_ARGS = {"world": "w", "threads": "t", "refs": "r"}


# --- 调用器 ---


def test_caller_caches(book):
    c = client(book)
    caller = Caller(book, c, lambda *a: None)

    async def go():
        caller.plan(2)
        a = await caller.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x")
        b = await caller.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x")
        return a, b

    a, b = asyncio.run(go())
    assert a == b == {"gaps": []}
    assert c.usage.calls == 1 and (caller.done, caller.total) == (2, 2)
    assert len(json.loads(book.threads_cache_path.read_text(encoding="utf-8"))) == 1
    again = Caller(book, client(book), lambda *a: None)
    assert asyncio.run(again.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x")) == {"gaps": []}
    assert again.client.usage.calls == 0


def test_caller_records_failure_and_raises_fatal(book):
    caller = Caller(book, client(book, gaps=lambda m: LLMError("坏了")), lambda *a: None)
    assert asyncio.run(caller.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x")) is None
    assert caller.failed == [{"call": "gaps-x", "error": "坏了"}]
    fatal = Caller(book, client(book, gaps=lambda m: FatalLLMError("欠费")), lambda *a: None)
    with pytest.raises(FatalLLMError):
        asyncio.run(fatal.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x"))


def test_caller_records_unresolved(book):
    caller = Caller(book, client(book), lambda *a: None)
    asyncio.run(caller.call("threads_gaps", GAPS_ARGS, lambda d: ["还是不对"], "gaps-x"))
    assert caller.unresolved == [{"call": "gaps-x", "problems": ["还是不对"]}]
    assert caller.client.usage.calls == 3


def test_caller_progress_is_a_pause_point(book):
    from ligaotai.jobs import JobCancelled

    def progress(done, total, *a):
        if done >= 1:
            raise JobCancelled("已暂停")

    caller = Caller(book, client(book), progress)
    with pytest.raises(JobCancelled):
        asyncio.run(caller.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x"))
    assert book.threads_cache_path.exists()  # 暂停前做完的调用已经进了缓存


def test_caller_passes_score_to_chat_json(book):
    """score 原样转给 chat_json：重试用尽时按分数挑，不按问题条数挑（条数都是 1，按条数会挑最后一次）。"""
    replies = ['{"gaps": [1]}', '{"gaps": []}', '{"gaps": [1, 2]}']
    c = LLMClient(AppConfig(), FakeBackend(replies=replies), log_dir=book.logs_dir)
    caller = Caller(book, c, lambda *a: None)
    got = asyncio.run(caller.call("threads_gaps", GAPS_ARGS, lambda d: ["不对"], "gaps-x", score=lambda d: len(d["gaps"])))
    assert got == {"gaps": []} and c.usage.calls == 3


def test_caller_clean_result_is_returned(book):
    caller = Caller(book, client(book), lambda *a: None)
    got = asyncio.run(caller.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x", clean=lambda d: ("清过", d)))
    assert got == ("清过", {"gaps": []})
    # 缓存里存的是模型输出，不是清理结果：命中缓存时照样现清一遍
    again = Caller(book, client(book), lambda *a: None)
    assert asyncio.run(again.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x", clean=lambda d: d["gaps"])) == []
    assert again.client.usage.calls == 0


@pytest.mark.parametrize("where", ["check", "score"])
def test_caller_check_or_score_error_is_a_failure(book, where):
    """检查 / 打分抛异常（本不该发生，只靠 fuzz 守着）：跟调用失败走同一条路，不写缓存，下次重新调模型。"""

    def boom(d):
        raise ValueError("大整数")

    check = boom if where == "check" else (lambda d: ["不对"])
    score = boom if where == "score" else None
    caller = Caller(book, client(book), lambda *a: None)
    assert asyncio.run(caller.call("threads_gaps", GAPS_ARGS, check, "gaps-x", score=score)) is None
    assert caller.failed == [{"call": "gaps-x", "error": "检查或清理出错：ValueError: 大整数"}]
    assert caller.done == 1 and not caller.unresolved
    path = book.threads_cache_path
    assert not path.exists() or json.loads(path.read_text(encoding="utf-8")) == {}  # 没写进缓存
    again = Caller(book, client(book), lambda *a: None)
    assert asyncio.run(again.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x")) == {"gaps": []}
    assert again.client.usage.calls == 1


def test_caller_clean_error_drops_cache_entry(book):
    """清理抛异常：记进 failed、返回 None，这条缓存删掉并写回文件，下次同样的调用重新调模型。"""

    def boom(d):
        raise ValueError("清不动")

    def cache():
        return json.loads(book.threads_cache_path.read_text(encoding="utf-8"))

    # 没命中缓存：调了模型、写了缓存，清理出错后删掉
    caller = Caller(book, client(book), lambda *a: None)
    assert asyncio.run(caller.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x", clean=boom)) is None
    assert caller.failed == [{"call": "gaps-x", "error": "检查或清理出错：ValueError: 清不动"}]
    assert caller.done == 1 and not caller.unresolved and cache() == {}

    # 命中缓存（先前存下的）但清理出错：也删掉，不把坏结果钉死在缓存里
    first = Caller(book, client(book), lambda *a: None)
    asyncio.run(first.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x"))
    assert len(cache()) == 1
    hit = Caller(book, client(book), lambda *a: None)
    assert asyncio.run(hit.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x", clean=boom)) is None
    assert hit.client.usage.calls == 0 and len(hit.failed) == 1 and cache() == {}

    again = Caller(book, client(book), lambda *a: None)
    assert asyncio.run(again.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-x", clean=lambda d: d["gaps"])) == []
    assert again.client.usage.calls == 1 and len(cache()) == 1


@pytest.mark.parametrize("exc", ["fatal", "cancelled", "asyncio"])
def test_caller_does_not_swallow_fatal_or_cancel(book, exc):
    from ligaotai.jobs import JobCancelled

    err = {"fatal": FatalLLMError("欠费"), "cancelled": JobCancelled("已暂停"), "asyncio": asyncio.CancelledError()}[exc]

    def boom(d):
        raise err

    for kw in ({"check": boom}, {"clean": boom}):
        caller = Caller(book, client(book), lambda *a: None)
        check = kw.get("check", lambda d: [])
        with pytest.raises(type(err)):
            asyncio.run(caller.call("threads_gaps", GAPS_ARGS, check, "gaps-x", clean=kw.get("clean")))
        assert caller.failed == []


# --- 划世界 ---


def worlds_of(book, items, known=(), unit="", budget=10**6, **handlers):
    c = client(book, **handlers)
    caller = Caller(book, c, lambda *a: None)
    got = asyncio.run(stage_worlds(caller, list(items.values()), list(known), unit, budget))
    return got, c, caller


def test_stage_worlds_default(book):
    (worlds, missing, unit), c, _ = worlds_of(book, items_of("S-0001", "S-0002"))
    assert [(w.key, w.name, w.scenes) for w in worlds] == [("N1", "世界一", ["S-0001", "S-0002"])]
    assert (missing, unit, c.usage.calls) == ([], "年", 1)
    assert "time_unit 填一个" in c.backend.calls[0]["messages"][0]["content"]


def test_stage_worlds_known_world_and_fixed_unit(book):
    def reply(m):
        return json.dumps({"time_unit": "年", "worlds": [
            {"id": "W-01", "scenes": ["S-0001"]}, {"name": "天界", "reason": "r", "scenes": ["S-0002"]},
        ]}, ensure_ascii=False)

    known = [WorldDraft("W-01", "人间", "旧依据")]
    (worlds, missing, unit), c, _ = worlds_of(book, items_of("S-0001", "S-0002"), known, unit="天", worlds=reply)
    assert [(w.key, w.name, w.scenes) for w in worlds] == [("W-01", "人间", ["S-0001"]), ("N1", "天界", ["S-0002"])]
    assert unit == "天"
    assert "已经定为「天」" in c.backend.calls[0]["messages"][0]["content"]
    assert "- W-01 人间：旧依据" in users(c, "划分世界")[0]


def test_stage_worlds_chunks_carry_earlier_worlds(book):
    def reply(m):
        ids = listed_scenes(m)
        if "N1 世界一" in m[1]["content"]:
            return json.dumps({"worlds": [{"id": "N1", "scenes": ids}]})
        return json.dumps({"time_unit": "年", "worlds": [{"name": "世界一", "reason": "r", "scenes": ids}]}, ensure_ascii=False)

    items = items_of("S-0001", "S-0002", "S-0003")
    (worlds, missing, unit), c, _ = worlds_of(book, items, budget=20, worlds=reply)
    assert c.usage.calls == 3
    assert [(w.key, w.scenes) for w in worlds] == [("N1", ["S-0001", "S-0002", "S-0003"])]
    assert "已经定为「年」" in c.backend.calls[1]["messages"][0]["content"]


def test_stage_worlds_chunk_reuses_name_of_earlier_new_world(book):
    """默认假回复每段都新建「世界一」：第二段起跟 N1 同名，检查报出来、重试到用尽（1 + 3 次），
    清理按 names 归进 N1，不会多出一个同名世界。"""
    (worlds, missing, _), c, caller = worlds_of(book, items_of("S-0001", "S-0002"), budget=20)
    assert [(w.key, w.name, w.scenes) for w in worlds] == [("N1", "世界一", ["S-0001", "S-0002"])]
    assert missing == [] and c.usage.calls == 4
    assert [u["call"] for u in caller.unresolved] == ["worlds-2"]
    assert "N1" in caller.unresolved[0]["problems"][0]


def test_stage_worlds_missing_scenes(book):
    reply = lambda m: json.dumps({"time_unit": "年", "worlds": [{"name": "甲", "scenes": ["S-0001"]}]}, ensure_ascii=False)
    (worlds, missing, _), c, caller = worlds_of(book, items_of("S-0001", "S-0002"), worlds=reply)
    assert missing == ["S-0002"] and c.usage.calls == 3 and caller.unresolved


def test_stage_worlds_all_failed_raises(book):
    with pytest.raises(LLMError):
        worlds_of(book, items_of("S-0001"), worlds=lambda m: LLMError("坏了"))


def test_stage_worlds_one_chunk_failed(book):
    def reply(m):
        if "S-0002" in listed_scenes(m):
            return LLMError("坏了")
        return json.dumps({"time_unit": "年", "worlds": [{"name": "甲", "scenes": listed_scenes(m)}]}, ensure_ascii=False)

    (worlds, missing, _), _, caller = worlds_of(book, items_of("S-0001", "S-0002"), budget=20, worlds=reply)
    assert [w.scenes for w in worlds] == [["S-0001"]] and missing == ["S-0002"] and len(caller.failed) == 1


def test_stage_worlds_nothing_free(book):
    known = [WorldDraft("W-01", "人间")]
    (worlds, missing, unit), c, _ = worlds_of(book, {}, known, unit="年")
    assert [w.key for w in worlds] == ["W-01"] and c.usage.calls == 0 and unit == "年"


# --- 划支线 ---


def lines_of(book, world, items, locked=(), budget=10**6, **handlers):
    c = client(book, **handlers)
    caller = Caller(book, c, lambda *a: None)
    return asyncio.run(stage_lines(caller, world, items, list(locked), budget)), c, caller


def test_stage_lines_default(book):
    items = items_of("S-0001", ("S-0002", "碎片"), ("S-0003", "提纲"), ("S-0004", "设定笔记"))
    world = WorldDraft("W-01", "人间", scenes=list(items))
    res, c, _ = lines_of(book, world, items)
    assert [(t.key, t.world, t.name, t.scenes, t.outlines) for t in res.threads] == [
        ("W-01#1", "W-01", "主线", ["S-0001", "S-0002"], ["S-0003"]),
    ]
    assert res.main == "W-01#1" and res.pending == [] and res.world_outlines == [] and res.missing == []
    user = users(c, "划分支线")[0]
    assert "S-0004" not in user and "已有的线：（无）" in user


def test_stage_lines_locked_thread_gets_pending(book):
    items = items_of("S-0001", "S-0002", "S-0009")
    locked = [ThreadDraft("L-003", "W-01", "旧线", "旧说明", scenes=["S-0009", "S-0404"], locked=True)]

    def reply(m):
        return json.dumps({"threads": [
            {"id": "L-003", "main": True, "scenes": ["S-0001"]},
            {"name": "新线", "about": "a", "scenes": ["S-0002"]},
        ]}, ensure_ascii=False)

    world = WorldDraft("W-01", "人间", scenes=["S-0001", "S-0002"])
    res, c, _ = lines_of(book, world, items, locked, lines=reply)
    assert res.pending == [{"scene": "S-0001", "thread": "L-003", "reason": "模型建议归入已确认的线"}]
    assert [(t.key, t.scenes) for t in res.threads] == [("W-01#1", ["S-0002"])]
    assert res.main == "L-003"
    user = users(c, "划分支线")[0]
    assert "- L-003 旧线：旧说明" in user and "  S-0009｜正文" in user and "S-0404" not in user


def test_stage_lines_chunks_carry_new_threads(book):
    def reply(m):
        ids = listed_scenes(m)
        if "W-01#1" in m[1]["content"]:
            return json.dumps({"threads": [{"id": "W-01#1", "main": True, "scenes": ids}]})
        return json.dumps({"threads": [{"name": "甲", "main": True, "scenes": ids}]}, ensure_ascii=False)

    items = items_of("S-0001", "S-0002")
    world = WorldDraft("W-01", "人间", scenes=list(items))
    res, c, _ = lines_of(book, world, items, budget=20, lines=reply)
    assert c.usage.calls == 2
    assert [(t.key, t.scenes) for t in res.threads] == [("W-01#1", ["S-0001", "S-0002"])]


def test_stage_lines_failed_call(book):
    items = items_of("S-0001", ("S-0002", "提纲"))
    world = WorldDraft("W-01", "人间", scenes=list(items))
    res, _, caller = lines_of(book, world, items, lines=lambda m: LLMError("坏了"))
    assert res.threads == [] and res.missing == ["S-0001"] and res.world_outlines == ["S-0002"]
    assert len(caller.failed) == 1


def test_stage_lines_only_outlines_or_notes(book):
    items = items_of(("S-0001", "提纲"), ("S-0002", "设定笔记"))
    res, c, _ = lines_of(book, WorldDraft("W-01", "人间", scenes=["S-0001"]), items)
    assert res.threads == [] and res.world_outlines == ["S-0001"]
    res2, c2, _ = lines_of(book, WorldDraft("W-01", "人间", scenes=["S-0002"]), items)
    assert res2.threads == [] and c2.usage.calls == 0


# --- 划支线：主线标记 / 已有线示例（held）/ 同名（names）/ require_main ---


def test_known_threads_text_marks_main():
    items = items_of("S-0001")
    with_about = [ThreadDraft("L-001", "W-01", "线一", "说明")]
    without_about = [ThreadDraft("L-002", "W-01", "线二")]
    assert known_threads_text(with_about, items, "L-001") == (
        "已有的线（块属于它就写它的 id）：\n- L-001 线一（主线）：说明"
    )
    assert known_threads_text(without_about, items, "L-002") == (
        "已有的线（块属于它就写它的 id）：\n- L-002 线二（主线）"
    )
    assert known_threads_text(with_about, items, None) == (
        "已有的线（块属于它就写它的 id）：\n- L-001 线一：说明"
    )


def test_stage_lines_main_param_marks_locked_thread_if_present(book):
    items = items_of("S-0001", "S-0009")
    locked = [ThreadDraft("L-003", "W-01", "旧线", "旧说明", scenes=["S-0009"])]
    world = WorldDraft("W-01", "人间", scenes=["S-0001"])

    c = client(book)
    caller = Caller(book, c, lambda *a: None)
    asyncio.run(stage_lines(caller, world, items, locked, 10**6, main="L-003"))
    user = users(c, "划分支线")[0]
    assert "- L-003 旧线（主线）：旧说明" in user

    c2 = client(book)
    caller2 = Caller(book, c2, lambda *a: None)
    asyncio.run(stage_lines(caller2, world, items, locked, 10**6, main="L-404"))
    user2 = users(c2, "划分支线")[0]
    assert "（主线）" not in user2


def test_stage_lines_chunk_marks_new_main_thread(book):
    def reply(m):
        ids = listed_scenes(m)
        if "W-01#1" in m[1]["content"]:
            return json.dumps({"threads": [{"id": "W-01#1", "main": True, "scenes": ids}]})
        return json.dumps({"threads": [{"name": "甲", "main": True, "scenes": ids}]}, ensure_ascii=False)

    items = items_of("S-0001", "S-0002")
    world = WorldDraft("W-01", "人间", scenes=list(items))
    c = client(book, lines=reply)
    caller = Caller(book, c, lambda *a: None)
    res = asyncio.run(stage_lines(caller, world, items, [], 20))
    assert c.usage.calls == 2
    assert "- W-01#1 甲（主线）" in users(c, "划分支线")[1]


def test_stage_lines_held_conflict_retries_then_dedupes(book):
    """第二段回复把第一段已经在 W-01#1 里的示例块 S-0001 又写了一遍：检查报「不用再列」，
    重试到用尽（1 + 3 = 4 次调用），最终 W-01#1 的 scenes 里 S-0001 不重复。"""

    def reply(m):
        ids = listed_scenes(m)
        if "W-01#1" in m[1]["content"]:
            return json.dumps({"threads": [{"id": "W-01#1", "main": True, "scenes": ["S-0001"] + ids}]})
        return json.dumps({"threads": [{"name": "甲", "main": True, "scenes": ids}]}, ensure_ascii=False)

    items = items_of("S-0001", "S-0002")
    world = WorldDraft("W-01", "人间", scenes=list(items))
    c = client(book, lines=reply)
    caller = Caller(book, c, lambda *a: None)
    res = asyncio.run(stage_lines(caller, world, items, [], 20))
    assert c.usage.calls == 4
    assert [u["call"] for u in caller.unresolved] == ["lines-W-01-2"]
    assert "不用再列" in caller.unresolved[0]["problems"][0]
    assert [(t.key, t.scenes) for t in res.threads] == [("W-01#1", ["S-0001", "S-0002"])]


def test_stage_lines_names_conflict_retries_then_merges(book):
    """默认假回复分两段：第二段又新建「主线」跟第一段新建的 W-01#1 同名，检查报同名、
    重试到用尽（4 次调用），最后只有一条线 W-01#1，两块都在里面。"""
    items = items_of("S-0001", "S-0002")
    world = WorldDraft("W-01", "人间", scenes=list(items))
    c = client(book)
    caller = Caller(book, c, lambda *a: None)
    res = asyncio.run(stage_lines(caller, world, items, [], 20))
    assert c.usage.calls == 4
    assert [(t.key, sorted(t.scenes)) for t in res.threads] == [("W-01#1", ["S-0001", "S-0002"])]
    assert [u["call"] for u in caller.unresolved] == ["lines-W-01-2"]


def test_stage_lines_require_main_only_first_chunk(book):
    """第一段标了 main、第二段回复一条 main 都没标：不重试（2 次调用）。"""

    def reply(m):
        ids = listed_scenes(m)
        if "W-01#1" in m[1]["content"]:
            return json.dumps({"threads": [{"id": "W-01#1", "scenes": ids}]})
        return json.dumps({"threads": [{"name": "甲", "main": True, "scenes": ids}]}, ensure_ascii=False)

    items = items_of("S-0001", "S-0002")
    world = WorldDraft("W-01", "人间", scenes=list(items))
    c = client(book, lines=reply)
    caller = Caller(book, c, lambda *a: None)
    asyncio.run(stage_lines(caller, world, items, [], 20))
    assert c.usage.calls == 2 and not caller.unresolved


def test_stage_lines_require_main_still_needed_after_first_chunk_fails(book):
    """第一段调用失败（整段没定出主线）、第二段回复没标 main：第二段检查会报（还要标 main）。"""

    def reply(m):
        if "S-0001" in listed_scenes(m):
            return LLMError("坏了")
        return json.dumps({"threads": [{"name": "甲", "scenes": listed_scenes(m)}]}, ensure_ascii=False)

    items = items_of("S-0001", "S-0002")
    world = WorldDraft("W-01", "人间", scenes=list(items))
    c = client(book, lines=reply)
    caller = Caller(book, c, lambda *a: None)
    asyncio.run(stage_lines(caller, world, items, [], 20))
    assert [u["call"] for u in caller.unresolved] == ["lines-W-01-2"]


# --- 线内排序 ---


def order_items():
    """S-0001、S-0002 是 b.txt 里挨着的两块（一个片段），S-0003 在 a.txt。"""
    return {
        "S-0001": Item("S-0001", "b.txt", 0, "正文", "S-0001｜正文｜甲"),
        "S-0002": Item("S-0002", "b.txt", 1, "正文", "S-0002｜正文｜乙"),
        "S-0003": Item("S-0003", "a.txt", 0, "正文", "S-0003｜正文｜丙"),
    }


def order_of(book, scenes, **handlers):
    c = client(book, **handlers)
    caller = Caller(book, c, lambda *a: None)
    t = ThreadDraft("W-01#1", "W-01", "主线", "说明", scenes=list(scenes))
    missing = asyncio.run(stage_order(caller, t, order_items(), "年"))
    return t, missing, c


def test_stage_order_default(book):
    t, missing, c = order_of(book, ["S-0001", "S-0002", "S-0003"])
    user = users(c, "线内排序")[0]
    assert "- P-001：S-0001 → S-0002（同一个文件里紧挨着）" in user
    assert user.index("S-0003｜") < user.index("S-0001｜")  # 场景块按片段顺序列：a.txt 在 b.txt 前面
    assert t.scenes == ["S-0003", "S-0001", "S-0002"] and missing == []
    assert t.times == {"S-0003": {"t": 0, "conf": "高"}, "S-0001": {"t": 1, "conf": "高"}, "S-0002": {"t": 2, "conf": "高"}}
    assert t.end == {"state": "待定", "note": "测试"} and t.order_failed is False
    assert "「主线（说明）」" in c.backend.calls[0]["messages"][0]["content"]


def test_stage_order_uses_segment_ids(book):
    def reply(m):
        return json.dumps({"order": ["P-001", "S-0003"], "times": {"S-0001": [0, "高"], "S-0002": [1, "高"], "S-0003": [5, "中"]},
                           "end": {"state": "完结", "note": "收尾了"}}, ensure_ascii=False)

    t, missing, _ = order_of(book, ["S-0001", "S-0002", "S-0003"], order=reply)
    assert t.scenes == ["S-0001", "S-0002", "S-0003"] and t.end["state"] == "完结"


def test_stage_order_missing_scene(book):
    def reply(m):
        return json.dumps({"order": ["P-001"], "times": {"S-0001": [0, "高"], "S-0002": [1, "高"]},
                           "end": {"state": "待定", "note": ""}}, ensure_ascii=False)

    t, missing, c = order_of(book, ["S-0001", "S-0002", "S-0003"], order=reply)
    assert t.scenes == ["S-0001", "S-0002"] and missing == ["S-0003"] and c.usage.calls == 3


def test_stage_order_failed_falls_back_to_file_order(book):
    t, missing, _ = order_of(book, ["S-0001", "S-0002", "S-0003"], order=lambda m: LLMError("坏了"))
    assert t.scenes == ["S-0003", "S-0001", "S-0002"] and t.order_failed is True
    assert t.times == {} and t.end == {"state": "待定", "note": ""} and missing == []


def test_stage_order_single_scene_needs_no_call(book):
    t, missing, c = order_of(book, ["S-0002"])
    assert c.usage.calls == 0 and t.scenes == ["S-0002"]
    assert t.times == {"S-0002": {"t": 0, "conf": "低"}} and t.end == {"state": "待定", "note": ""}


def test_stage_order_unusable_reply_marks_failed_and_records_caller_failure(book):
    """回复的 order 不是列表（3 次都这样）：跟调用直接失败不同路——这次是「回复解析出来了，
    但清理判定没法用」，除了标 order_failed，还要往 caller.failed 记一条，方便作者在结果里看到。"""
    c = client(book, order=lambda m: json.dumps({"order": "乱写"}))
    caller = Caller(book, c, lambda *a: None)
    t = ThreadDraft("W-01#1", "W-01", "主线", "说明", scenes=["S-0001", "S-0002", "S-0003"])
    missing = asyncio.run(stage_order(caller, t, order_items(), "年"))
    assert t.order_failed is True
    assert t.scenes == ["S-0003", "S-0001", "S-0002"]
    assert t.times == {} and t.end == {"state": "待定", "note": ""} and missing == []
    assert c.usage.calls == 3
    assert [f["call"] for f in caller.failed] == ["order-W-01#1"]


# --- 跨线对齐 + 找缺口 ---


def two_threads():
    items = items_of("S-0001", "S-0002", "S-0003")
    a = ThreadDraft("L-001", "W-01", "甲", scenes=["S-0001", "S-0002"], times={"S-0001": {"t": 0, "conf": "高"}})
    b = ThreadDraft("L-002", "W-01", "乙", scenes=["S-0003", "S-0404"])
    return items, a, b


def test_thread_block():
    items, a, b = two_threads()
    assert thread_block(a, items, main=True) == "## L-001 甲（主线）\n[0] S-0001｜正文｜摘要S-0001\n[?] S-0002｜正文｜摘要S-0002"
    assert thread_block(b, items) == "## L-002 乙\n[?] S-0003｜正文｜摘要S-0003\n[?] S-0404"


def test_thread_block_defends_against_bad_times():
    """已确认的线的 times 是从 世界与支线.json 读回来的，形状不一定干净：bool、非数字字符串、
    超大整数、NaN、times[s] 本身不是字典，都当没有时间显示 [?]，不抛异常。"""
    items = items_of("S-0001", "S-0002", "S-0003", "S-0004", "S-0005")
    t = ThreadDraft("L-001", "W-01", "甲", scenes=["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"], times={
        "S-0001": {"t": True, "conf": "高"},
        "S-0002": {"t": "abc", "conf": "高"},
        "S-0003": {"t": 10**400, "conf": "高"},
        "S-0004": {"t": float("nan"), "conf": "高"},
        "S-0005": 5,  # times["S-0005"] 本身不是字典
    })
    block = thread_block(t, items)
    assert block.count("[?]") == 5


def test_num_formats_finite_numbers_with_g():
    items = items_of("S-0001", "S-0002")
    t = ThreadDraft("L-001", "W-01", "甲", scenes=["S-0001", "S-0002"], times={
        "S-0001": {"t": 3, "conf": "高"}, "S-0002": {"t": 2.5, "conf": "高"},
    })
    block = thread_block(t, items)
    assert "[3]" in block and "[2.5]" in block


def align_of(book, threads, main, budget=10**6, **handlers):
    c = client(book, **handlers)
    caller = Caller(book, c, lambda *a: None)
    items = items_of("S-0001", "S-0002", "S-0003")
    return asyncio.run(stage_align(caller, threads, main, items, "年", budget)), c, caller


def test_stage_align_default(book):
    _, a, b = two_threads()
    (offsets, cross), c, _ = align_of(book, [a, b], "L-001")
    assert offsets == {"L-001": 0, "L-002": 0} and cross == []
    assert "## L-001 甲（主线）" in users(c, "跨线对齐")[0]


def test_stage_align_reply(book):
    _, a, b = two_threads()

    def reply(m):
        return json.dumps({"threads": [{"id": "L-001", "offset": 0}, {"id": "L-002", "offset": None}],
                           "intersections": [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "同一场"}]},
                          ensure_ascii=False)

    (offsets, cross), _, _ = align_of(book, [a, b], "L-001", align=reply)
    assert offsets == {"L-001": 0, "L-002": None}
    assert cross == [{"thread": "L-002", "scene": "S-0003", "main_scene": "S-0002", "reason": "同一场"}]


def test_stage_align_shifts_offsets_relative_to_main(book):
    """主线 offset 不是 0（模型没照规则写）：clean_align 把其他线平移，保持相对关系，主线固定 0。"""
    _, a, b = two_threads()

    def reply(m):
        return json.dumps({"threads": [{"id": "L-001", "offset": 5}, {"id": "L-002", "offset": 7}],
                           "intersections": []}, ensure_ascii=False)

    (offsets, cross), _, _ = align_of(book, [a, b], "L-001", align=reply)
    assert offsets == {"L-001": 0, "L-002": 2} and cross == []


def test_stage_align_skips(book):
    _, a, b = two_threads()
    (offsets, _), c, _ = align_of(book, [a], "L-001")
    assert offsets == {"L-001": 0} and c.usage.calls == 0
    (offsets, _), c, _ = align_of(book, [a, b], None)
    assert offsets == {"L-001": None, "L-002": None} and c.usage.calls == 0
    (offsets, _), c, caller = align_of(book, [a, b], "L-001", budget=10)
    assert offsets == {"L-001": 0, "L-002": None} and c.usage.calls == 0 and caller.failed


def test_stage_align_failed(book):
    _, a, b = two_threads()
    (offsets, cross), _, caller = align_of(book, [a, b], "L-001", align=lambda m: LLMError("坏了"))
    assert offsets == {"L-001": 0, "L-002": None} and cross == [] and len(caller.failed) == 1


def gaps_of(book, refs, threads, budget=10**6, **handlers):
    items = items_of("S-0001", "S-0002", "S-0003")
    for sid, rs in refs.items():
        items[sid].refs = rs
    c = client(book, **handlers)
    caller = Caller(book, c, lambda *a: None)
    got = asyncio.run(stage_gaps(caller, "W-01", "人间", threads, list(items), items, budget))
    return got, c


def test_stage_gaps(book):
    _, a, _ = two_threads()
    got, c = gaps_of(book, {}, [a])
    assert got == [] and c.usage.calls == 0

    def reply(m):
        return json.dumps({"gaps": [{"event": "城破", "mentioned_in": ["S-0003"], "thread": "L-001", "after": "S-0001", "before": None}]},
                          ensure_ascii=False)

    got, c = gaps_of(book, {"S-0003": ["青州城破"]}, [a], gaps=reply)
    assert got == [{"world": "W-01", "event": "城破", "mentioned_in": ["S-0003"], "thread": "L-001", "after": "S-0001", "before": None}]
    assert "- 青州城破｜S-0003" in users(c, "找缺口")[0]
    # 换一件不一样的事：跟上面那次调用的提示词不同，避免命中同一本书缓存里刚写的那条，
    # 真的走到 gaps=lambda 这个失败处理分支（计划原文重用同一个 refs，会命中缓存、测不到失败路径）
    got, c = gaps_of(book, {"S-0003": ["另一件没写的事"]}, [a], gaps=lambda m: LLMError("坏了"))
    assert got == []
    got, c = gaps_of(book, {"S-0003": ["青州城破"]}, [a], budget=10)
    assert got == [] and c.usage.calls == 0
