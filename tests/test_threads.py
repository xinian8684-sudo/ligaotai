import asyncio
import json

import pytest
from helpers import FakeBackend, listed_scenes, seed_book, threads_handler

from ligaotai.config import AppConfig
from ligaotai.llm import FatalLLMError, LLMClient, LLMError
from ligaotai.threads import Caller, WorldDraft, stage_worlds
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
