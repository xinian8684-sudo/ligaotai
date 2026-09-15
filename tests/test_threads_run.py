import json

import pytest
from helpers import FakeBackend, listed_scenes, seed_book, threads_handler

from ligaotai.config import AppConfig
from ligaotai.fsutil import read_json, write_json
from ligaotai.jobs import JobCancelled
from ligaotai.llm import FatalLLMError, LLMClient, LLMError
from ligaotai.threads import MISSED, PENDING, run_threads
from ligaotai.threads_input import NO_CARD

# S-0001、S-0002 是 b.txt 里挨着的两块；S-0003 在 a.txt，提到「青州城破」；S-0004 提纲；S-0005 设定笔记；S-0006 没卡
SCENES = [
    {"id": "S-0001", "source": "b.txt", "index": 0, "persons": ["林清"]},
    {"id": "S-0002", "source": "b.txt", "index": 1},
    {"id": "S-0003", "source": "a.txt", "index": 0, "refs": ["青州城破"]},
    {"id": "S-0004", "source": "a.txt", "index": 1, "kind": "提纲"},
    {"id": "S-0005", "source": "a.txt", "index": 2, "kind": "设定笔记"},
    {"id": "S-0006", "source": "a.txt", "index": 3, "no_card": True},
]
ENTS = [("person", "林清", ["林清"])]


@pytest.fixture
def seeded(book):
    seed_book(book, SCENES, entities=ENTS)
    return book


def client(book, **handlers):
    return LLMClient(AppConfig(), FakeBackend(handler=threads_handler(**handlers)), log_dir=book.logs_dir)


def default(m):
    """某一种调用里先做点手脚、再照默认回复时用。"""
    return threads_handler()(None, m)


def result(book):
    return read_json(book.threads_path)


def edit(book, fn):
    data = result(book)
    fn(data)
    write_json(book.threads_path, data)


def test_run_threads_end_to_end(seeded):
    c = client(seeded)
    summary = run_threads(seeded, c)
    data = result(seeded)
    assert data["worlds"] == [
        {"id": "W-01", "name": "世界一", "reason": "测试", "status": "draft", "notes": ["S-0005"], "outlines": []}
    ]
    [t] = data["threads"]
    assert (t["id"], t["world"], t["name"], t["status"]) == ("L-001", "W-01", "主线", "draft")
    assert t["scenes"] == ["S-0003", "S-0001", "S-0002"] and t["outlines"] == ["S-0004"]
    assert t["times"]["S-0001"] == {"t": 1, "conf": "高"} and t["offset"] == 0
    assert t["end"] == {"state": "待定", "note": "测试", "last": "S-0002"} and t["order_failed"] is False
    assert (data["main_thread"], data["main_by"], data["time_unit"]) == ("L-001", "auto", "年")
    assert data["unassigned"] == [{"scene": "S-0006", "reason": NO_CARD}]
    assert data["pending"] == [] and data["gaps"] == [] and data["intersections"] == []
    assert (data["next_world"], data["next_thread"]) == (2, 2)
    assert c.usage.calls == 4  # 划世界、划支线、排序、找缺口；只有一条线，不用对齐
    assert summary["threads"] == 1 and summary["unassigned"] == 1 and summary["not_written"] is False
    assert seeded.step("threads")["status"] == "done"
    assert seeded.load()["usage"]["by_step"]["threads"]["calls"] == 4


def test_rerun_uses_the_cache(seeded):
    run_threads(seeded, client(seeded))
    first = result(seeded)
    c = client(seeded)
    run_threads(seeded, c)
    assert c.usage.calls == 0 and result(seeded) == first
    assert seeded.step("threads")["status"] == "done"


def test_ids_stay_the_same_when_rerun_without_cache(seeded):
    run_threads(seeded, client(seeded))
    seeded.threads_cache_path.unlink()
    c = client(seeded)
    run_threads(seeded, c)
    data = result(seeded)
    assert c.usage.calls == 4
    assert [w["id"] for w in data["worlds"]] == ["W-01"] and [t["id"] for t in data["threads"]] == ["L-001"]
    assert (data["next_world"], data["next_thread"]) == (2, 2)


def test_confirmed_thread_is_kept_and_new_scene_goes_to_pending(seeded):
    run_threads(seeded, client(seeded))
    edit(seeded, lambda d: d["threads"][0].update(status="confirmed"))
    before = result(seeded)["threads"][0]
    seed_book(seeded, SCENES + [{"id": "S-0007", "source": "c.txt", "index": 0}], entities=ENTS)

    def worlds(m):
        return json.dumps({"worlds": [{"id": "W-01", "scenes": listed_scenes(m)}]})

    def lines(m):
        return json.dumps({"threads": [{"id": "L-001", "main": True, "scenes": listed_scenes(m)}]})

    c = client(seeded, worlds=worlds, lines=lines)
    run_threads(seeded, c)
    data = result(seeded)
    [t] = data["threads"]
    keys = ("id", "scenes", "times", "outlines", "status")
    assert {k: t[k] for k in keys} == {k: before[k] for k in keys}
    assert data["pending"] == [{"scene": "S-0007", "thread": "L-001", "reason": PENDING}]
    assert data["worlds"][0]["status"] == "confirmed" and data["worlds"][0]["notes"] == ["S-0005"]
    world_prompts = [x["messages"][1]["content"] for x in c.backend.calls if "划分世界" in x["messages"][0]["content"]]
    assert world_prompts and all("S-0001" not in p for p in world_prompts)


def test_confirmed_thread_keeps_a_scene_without_card_and_author_main(seeded):
    run_threads(seeded, client(seeded))

    def confirm(d):
        d["threads"][0]["status"] = "confirmed"
        d["threads"][0]["scenes"].append("S-0006")
        d["main_by"] = "author"

    edit(seeded, confirm)
    run_threads(seeded, client(seeded))
    data = result(seeded)
    assert data["threads"][0]["scenes"][-1] == "S-0006"
    assert all(u["scene"] != "S-0006" for u in data["unassigned"])
    assert data["main_by"] == "author"


def test_scene_the_model_keeps_missing_goes_to_unassigned(seeded):
    def order(m):
        ids = [s for s in listed_scenes(m) if s != "S-0001"]
        return json.dumps({"order": ids, "times": {s: [0, "高"] for s in ids}, "end": {"state": "待定", "note": ""}},
                          ensure_ascii=False)

    summary = run_threads(seeded, client(seeded, order=order))
    data = result(seeded)
    assert data["threads"][0]["scenes"] == ["S-0003", "S-0002"]
    assert {"scene": "S-0001", "reason": MISSED} in data["unassigned"]
    assert summary["unresolved"][0]["call"] == "order-L-001"


def test_order_failure_falls_back_to_file_order(seeded):
    summary = run_threads(seeded, client(seeded, order=lambda m: LLMError("坏了")))
    t = result(seeded)["threads"][0]
    assert t["scenes"] == ["S-0003", "S-0001", "S-0002"] and t["order_failed"] is True and t["times"] == {}
    assert summary["order_failed"] == ["L-001"] and summary["failed_calls"][0]["call"] == "order-L-001"


def test_input_changed_during_the_run_is_outdated(seeded):
    def order(m):
        seed_book(seeded, SCENES, entities=[("person", "林小清", ["林清"])])
        return default(m)

    summary = run_threads(seeded, client(seeded, order=order))
    assert summary["input_changed"] is True and seeded.step("threads")["status"] == "outdated"
    assert result(seeded)["threads"]  # 结果照样写了，只是要重跑


def test_author_edit_during_the_run_is_not_overwritten(seeded):
    run_threads(seeded, client(seeded))
    seeded.threads_cache_path.unlink()

    def worlds(m):
        edit(seeded, lambda d: d["threads"][0].update(name="作者改的名"))
        return default(m)

    summary = run_threads(seeded, client(seeded, worlds=worlds))
    assert summary["not_written"] is True and seeded.step("threads")["status"] == "outdated"
    assert result(seeded)["threads"][0]["name"] == "作者改的名"
    assert seeded.threads_cache_path.exists()  # 没清缓存，重跑不花钱


def test_fatal_error_stops_the_step_and_keeps_usage(seeded):
    with pytest.raises(FatalLLMError):
        run_threads(seeded, client(seeded, lines=lambda m: FatalLLMError("欠费")))
    assert seeded.load()["usage"]["by_step"]["threads"]["calls"] == 1
    assert not seeded.threads_path.exists()


def test_run_threads_defends_against_dirty_old_file(seeded):
    """世界与支线.json 是作者能手改的文件：已确认的线 id 是列表、已确认世界的 notes 不是列表，
    读到什么形状都不能让 run_threads 抛异常，照常跑完。"""
    run_threads(seeded, client(seeded))

    def corrupt(d):
        d["threads"][0]["id"] = ["not", "a", "string"]
        d["threads"][0]["status"] = "confirmed"
        d["worlds"][0]["status"] = "confirmed"
        d["worlds"][0]["notes"] = 5
        d["worlds"][0]["outlines"] = "S-0004"

    edit(seeded, corrupt)
    summary = run_threads(seeded, client(seeded))
    assert summary is not None
    assert seeded.step("threads")["status"] in ("done", "outdated")
    data = result(seeded)
    # id 是列表的那条线不是合法的已确认线，不能沿用旧编号也不算已确认（它的块被重新划线）
    assert all(isinstance(t["id"], str) for t in data["threads"])
    assert all(t["status"] != "confirmed" for t in data["threads"])
    # W-01 的 notes / outlines 是脏值（5、字符串），读回来清成了列表
    [w] = [w for w in data["worlds"] if w["id"] == "W-01"]
    assert isinstance(w["notes"], list) and isinstance(w["outlines"], list)


def test_draft_world_with_non_string_name_does_not_crash(seeded):
    """旧文件里一个草稿世界的 name 被手改成列表（不是字符串）：assign_world_ids 不能因为
    拿它当 dict 的 key 而抛 TypeError，run_threads 照常跑完（修复批次 5 第 1 条）。"""
    run_threads(seeded, client(seeded))
    edit(seeded, lambda d: d["worlds"][0].update(name=["世界一"]))
    summary = run_threads(seeded, client(seeded))
    assert summary is not None
    assert seeded.step("threads")["status"] in ("done", "outdated")


def test_confirmed_thread_in_n_prefixed_world_is_not_dropped(seeded):
    """已确认线所属的世界编号被手改成以 "N" 开头（比如 "N1"）：assign_world_ids 不能把它当成
    这次新分配的临时键，不然这条线连同它的块会从结果里消失、也不报错（修复批次 5 第 2 条）。"""
    run_threads(seeded, client(seeded))
    edit(seeded, lambda d: d["threads"][0].update(status="confirmed", world="N1"))
    before_ids = [t["id"] for t in result(seeded)["threads"]]
    run_threads(seeded, client(seeded))
    data = result(seeded)
    after_ids = [t["id"] for t in data["threads"]]
    assert after_ids == before_ids  # 线还在
    [t] = data["threads"]
    assert t["world"] == "N1" and t["status"] == "confirmed"
    placed = {s for t in data["threads"] for s in t["scenes"]} | {u["scene"] for u in data["unassigned"]}
    assert {"S-0001", "S-0002", "S-0003"} <= placed  # 它的块也还在（不是丢了、也不是没归位）


def test_new_world_number_does_not_collide_with_placeholder(seeded):
    """旧文件同时丢了 worlds 列表和 next_world，只剩一条已确认的线指向 W-01：run_threads 会给它
    补一个占位世界 W-01；新分配的世界编号不能也发成 W-01，不然两个世界都叫 W-01、这条线在
    threads 里会出现两次（修复批次 5 第 3 条）。"""
    run_threads(seeded, client(seeded))

    def drop_worlds(d):
        d["threads"][0]["status"] = "confirmed"
        d["worlds"] = []
        del d["next_world"]

    edit(seeded, drop_worlds)
    run_threads(seeded, client(seeded))
    data = result(seeded)
    world_ids = [w["id"] for w in data["worlds"]]
    assert len(world_ids) == len(set(world_ids))  # 世界编号不重复
    thread_ids = [t["id"] for t in data["threads"]]
    assert len(thread_ids) == len(set(thread_ids))  # 每条线只出现一次


def test_new_world_temp_key_skips_a_confirmed_world_keyed_like_one(seeded):
    """已确认线所属的世界编号被手改成 "N2"：划世界给新世界起临时键时不能也起成 N2，
    不然两个世界都叫 N2、这条线在 threads 里出现两次（批次 5/6 复查的 Minor）。"""
    run_threads(seeded, client(seeded))
    edit(seeded, lambda d: d["threads"][0].update(status="confirmed", world="N2"))
    run_threads(seeded, client(seeded))
    data = result(seeded)
    world_ids = [w["id"] for w in data["worlds"]]
    assert len(world_ids) == len(set(world_ids))  # 世界编号不重复
    thread_ids = [t["id"] for t in data["threads"]]
    assert len(thread_ids) == len(set(thread_ids))  # 每条线只出现一次


def test_worlds_prompt_marks_confirmed_main_thread(seeded):
    """已确认的全书主线在划支线的提示词里要标「（主线）」，不然模型不知道哪条是主线
    （修复批次 5 第 4 条 notes 1）。"""
    run_threads(seeded, client(seeded))
    edit(seeded, lambda d: d["threads"][0].update(status="confirmed"))
    seed_book(seeded, SCENES + [{"id": "S-0007", "source": "c.txt", "index": 0}], entities=ENTS)

    def worlds(m):
        return json.dumps({"worlds": [{"id": "W-01", "scenes": listed_scenes(m)}]})

    def lines(m):
        return json.dumps({"threads": [{"id": "L-001", "main": True, "scenes": listed_scenes(m)}]})

    c = client(seeded, worlds=worlds, lines=lines)
    run_threads(seeded, c)
    lines_prompts = [x["messages"][1]["content"] for x in c.backend.calls if "划分支线" in x["messages"][0]["content"]]
    assert lines_prompts and any("- L-001 主线（主线）：测试" in p for p in lines_prompts)


def test_time_unit_falls_back_to_year_when_model_never_gives_one(seeded):
    """模型划世界的回复一直不带 time_unit（3 次重试都不带）：检查会报问题，但 worlds 字段本身能用，
    最后写文件时兜底成「年」，步骤照常算 done（修复批次 5 第 4 条 notes 2）。"""

    def worlds(m):
        return json.dumps(
            {"worlds": [{"name": "世界一", "reason": "r", "scenes": listed_scenes(m)}]}, ensure_ascii=False
        )

    summary = run_threads(seeded, client(seeded, worlds=worlds))
    data = result(seeded)
    assert data["time_unit"] == "年"
    assert seeded.step("threads")["status"] == "done"
    assert summary["unresolved"]  # time_unit 缺失被记成没解决的问题，但不影响这次结果能用


def test_set_main_survives_rerun(seeded):
    """作者用 set_main 把一条草稿线设成主线，之后来了新块重跑：这条线还是主线、main_by 还是
    author（修复批次 5 第 5 条：set_main 也算动过这条线，得确认，不然重跑换了号就悄悄变回 auto）。"""
    from ligaotai import threads_ops as ops

    run_threads(seeded, client(seeded))
    ops.set_main(seeded, "L-001")
    seed_book(seeded, SCENES + [{"id": "S-0007", "source": "c.txt", "index": 0}], entities=ENTS)
    run_threads(seeded, client(seeded))
    data = result(seeded)
    assert data["main_thread"] == "L-001" and data["main_by"] == "author"


def test_pause_then_rerun_uses_the_cache(seeded):
    def progress(done, total, *a):
        if done >= 1:
            raise JobCancelled("已暂停")

    c1 = client(seeded)
    with pytest.raises(JobCancelled):
        run_threads(seeded, c1, progress)
    c2 = client(seeded)
    run_threads(seeded, c2)
    assert (c1.usage.calls, c2.usage.calls) == (1, 3)
