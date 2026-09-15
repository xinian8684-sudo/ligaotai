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
