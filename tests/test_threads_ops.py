import pytest

from ligaotai import threads_ops as ops
from ligaotai.fsutil import read_json, write_json


def sample():
    return {
        "next_world": 3, "next_thread": 4, "time_unit": "年", "main_thread": "L-001", "main_by": "auto",
        "worlds": [
            {"id": "W-01", "name": "人间", "reason": "", "status": "draft", "notes": ["S-0009"], "outlines": []},
            {"id": "W-02", "name": "天界", "reason": "", "status": "draft", "notes": [], "outlines": []},
        ],
        "threads": [
            {"id": "L-001", "world": "W-01", "name": "甲", "about": "", "status": "draft",
             "scenes": ["S-0001", "S-0002", "S-0003"],
             "times": {"S-0001": {"t": 0, "conf": "高"}, "S-0003": {"t": 2, "conf": "高"}},
             "outlines": ["S-0008"], "offset": 0, "end": {"state": "待定", "note": "", "last": "S-0003"}, "order_failed": False},
            {"id": "L-002", "world": "W-01", "name": "乙", "about": "", "status": "draft", "scenes": ["S-0004"],
             "times": {"S-0004": {"t": 1, "conf": "低"}}, "outlines": [], "offset": 1,
             "end": {"state": "待定", "note": "", "last": "S-0004"}, "order_failed": False},
            {"id": "L-003", "world": "W-02", "name": "丙", "about": "", "status": "draft", "scenes": ["S-0005"],
             "times": {}, "outlines": [], "offset": None, "end": {"state": "待定", "note": "", "last": "S-0005"}, "order_failed": False},
        ],
        "intersections": [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "r"}],
        "gaps": [{"id": "Q-001", "world": "W-01", "event": "城破", "mentioned_in": ["S-0001"],
                  "thread": "L-002", "after": "S-0004", "before": None}],
        "unassigned": [{"scene": "S-0006", "reason": "模型没分配"}],
        "pending": [{"scene": "S-0007", "thread": "L-002", "reason": "模型建议归入已确认的线"}],
    }


@pytest.fixture
def tbook(book):
    write_json(book.threads_path, sample())
    book.set_step("archive", "done")
    return book


def data_of(book):
    return read_json(book.threads_path)


def archive(book):
    return book.step("archive")["status"]


def test_nothing_to_adjust_before_step_6(book):
    with pytest.raises(FileNotFoundError):
        ops.load_threads(book)


def test_load_threads_raises_broken_threads_file_on_bad_json(book):
    book.threads_path.parent.mkdir(parents=True, exist_ok=True)
    book.threads_path.write_text("{不是合法 json", encoding="utf-8")
    with pytest.raises(ops.BrokenThreadsFile):
        ops.load_threads(book)


def test_confirm_does_not_outdate_downstream(tbook):
    [t] = ops.confirm(tbook, ["L-001", "L-001"])
    d = data_of(tbook)
    assert t["status"] == "confirmed" and d["threads"][0]["status"] == "confirmed"
    assert d["worlds"][0]["status"] == "confirmed" and archive(tbook) == "done"
    with pytest.raises(KeyError):
        ops.confirm(tbook, ["L-099"])


def test_rename(tbook):
    assert ops.rename(tbook, "L-002", " 新名 ")["name"] == "新名"
    d = data_of(tbook)
    assert d["threads"][1]["status"] == "confirmed" and d["worlds"][0]["status"] == "confirmed"
    assert archive(tbook) == "outdated"
    ops.rename(tbook, "W-02", "仙界")
    assert data_of(tbook)["worlds"][1] == {**sample()["worlds"][1], "name": "仙界", "status": "confirmed"}
    with pytest.raises(ValueError):
        ops.rename(tbook, "L-001", "  ")
    with pytest.raises(KeyError):
        ops.rename(tbook, "W-09", "x")


def test_move_scenes_within_and_across(tbook):
    ops.move_scenes(tbook, ["S-0003"], "L-001", position=0)
    t = data_of(tbook)["threads"][0]
    assert t["scenes"] == ["S-0003", "S-0001", "S-0002"] and t["status"] == "confirmed"
    assert t["times"]["S-0003"] == {"t": 2, "conf": "高"}  # 同一条线里调顺序，时间留着
    assert t["end"]["last"] == "S-0002"
    ops.move_scenes(tbook, ["S-0006", "S-0007", "S-0009", "S-0004"], "L-001")
    d = data_of(tbook)
    assert d["threads"][0]["scenes"][-4:] == ["S-0006", "S-0007", "S-0009", "S-0004"]
    assert "S-0004" not in d["threads"][0]["times"]  # 别的线挪来的不带时间
    assert d["unassigned"] == [] and d["pending"] == [] and d["worlds"][0]["notes"] == []
    ops.move_scenes(tbook, ["S-0008"], "L-003", as_outline=True)
    assert data_of(tbook)["threads"][-1]["outlines"] == ["S-0008"]
    with pytest.raises(ValueError):
        ops.move_scenes(tbook, ["S-0404"], "L-001")
    with pytest.raises(ValueError):
        ops.move_scenes(tbook, [], "L-001")
    with pytest.raises(KeyError):
        ops.move_scenes(tbook, ["S-0001"], "L-099")


def test_emptied_thread_is_removed_and_references_fixed(tbook):
    ops.move_scenes(tbook, ["S-0004"], "L-001")
    d = data_of(tbook)
    assert [t["id"] for t in d["threads"]] == ["L-001", "L-003"]
    assert d["intersections"] == []
    assert (d["gaps"][0]["thread"], d["gaps"][0]["after"]) == (None, None)
    assert d["unassigned"][-1] == {"scene": "S-0007", "reason": "建议归入的线已被删除"}


def test_merge_threads(tbook):
    keep = ops.merge_threads(tbook, ["L-001", "L-002"])
    d = data_of(tbook)
    assert keep["scenes"] == ["S-0001", "S-0002", "S-0003", "S-0004"]
    assert [t["id"] for t in d["threads"]] == ["L-001", "L-003"]
    assert "S-0004" not in d["threads"][0]["times"]
    assert d["pending"][0]["thread"] == "L-001" and d["gaps"][0]["thread"] == "L-001"
    assert d["gaps"][0]["after"] == "S-0004" and archive(tbook) == "outdated"
    with pytest.raises(ValueError):
        ops.merge_threads(tbook, ["L-001"])


def test_split_thread(tbook):
    new = ops.split_thread(tbook, "L-001", "S-0002")
    d = data_of(tbook)
    assert new["id"] == "L-004" and new["scenes"] == ["S-0002", "S-0003"]
    assert new["times"] == {"S-0003": {"t": 2, "conf": "高"}} and new["name"] == "甲（拆出）"
    assert [t["id"] for t in d["threads"]] == ["L-001", "L-004", "L-002", "L-003"]
    assert d["threads"][0]["scenes"] == ["S-0001"] and d["next_thread"] == 5
    assert d["intersections"] == []  # 交汇点对着的主线块 S-0002 被拆到新线了
    with pytest.raises(ValueError):
        ops.split_thread(tbook, "L-001", "S-0001")  # 现在 S-0001 是第一块
    with pytest.raises(ValueError):
        ops.split_thread(tbook, "L-001", "S-0404")


def test_set_main_and_move_thread(tbook):
    ops.set_main(tbook, "L-003")
    d = data_of(tbook)
    assert (d["main_thread"], d["main_by"]) == ("L-003", "author") and archive(tbook) == "outdated"
    assert d["threads"][2]["status"] == "confirmed" and d["worlds"][1]["status"] == "confirmed"  # 设主线也算动过这条线
    ops.move_thread(tbook, "L-003", "W-01")
    d = data_of(tbook)
    assert d["threads"][2]["world"] == "W-01" and [w["id"] for w in d["worlds"]] == ["W-01"]
    with pytest.raises(KeyError):
        ops.move_thread(tbook, "L-001", "W-09")
    with pytest.raises(KeyError):
        ops.set_main(tbook, "L-099")


# --- 补测试（task15_notes.md）---


def test_missing_optional_keys_still_work(tbook):
    """文件里缺 pending / gaps / intersections 等键，各操作照常工作（load_threads 过 normalize 补齐）。"""
    data = data_of(tbook)
    del data["pending"]
    del data["gaps"]
    del data["intersections"]
    write_json(tbook.threads_path, data)
    ops.confirm(tbook, ["L-001"])
    d = data_of(tbook)
    assert d["threads"][0]["status"] == "confirmed"
    assert d["pending"] == [] and d["gaps"] == [] and d["intersections"] == []


def test_dangling_world_tidied_without_outdating_downstream(tbook):
    """没有线、没有笔记、没有提纲的世界：确认一条线后被整理掉，且不让下游过期
    （签名在 _tidy 之后才算，孤儿世界在 load 时就已经被摘掉）。"""
    data = data_of(tbook)
    data["worlds"].append({"id": "W-03", "name": "孤儿", "reason": "", "status": "draft", "notes": [], "outlines": []})
    write_json(tbook.threads_path, data)
    ops.confirm(tbook, ["L-001"])
    d = data_of(tbook)
    assert [w["id"] for w in d["worlds"]] == ["W-01", "W-02"]
    assert archive(tbook) == "done"


def test_move_scenes_target_without_times_key(tbook):
    """线本身没有 times 键也不报错（setdefault 而不是直接 update）。"""
    data = data_of(tbook)
    del data["threads"][2]["times"]  # L-003 没有 times 键
    write_json(tbook.threads_path, data)
    ops.move_scenes(tbook, ["S-0006"], "L-003")
    d = data_of(tbook)
    assert d["threads"][2]["scenes"] == ["S-0005", "S-0006"]
    assert d["threads"][2]["times"] == {}
