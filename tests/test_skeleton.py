import json
import re

import pytest
from helpers import FakeBackend

from ligaotai.config import AppConfig
from ligaotai.fsutil import read_json, write_json
from ligaotai.llm import LLMClient
from ligaotai.skeleton import (
    BrokenSkeletonFile,
    annotate,
    check_holes,
    fallback_task,
    generate,
    load_skeleton,
    save_skeleton,
)
from ligaotai.threads_ops import load_threads
from ligaotai.triage import set_card

_HID = re.compile(r"^### (H-\d{3})$", re.M)
_SID = re.compile(r"S-\d{4}")


def _handler(chapters=None, holes_ok=True, on_call=None):
    def h(tier, messages):
        system, user = messages[0]["content"], messages[1]["content"]
        if on_call:
            on_call()
        if "分卷分章" in system:
            return json.dumps(chapters or {"volumes": [{"title": "卷一", "start": 0}],
                                           "chapters": [{"title": "开篇", "start": 0}, {"title": "龙宫", "start": 3}]},
                              ensure_ascii=False)
        if "补写任务说明" in system:
            if not holes_ok:
                return json.dumps({"holes": []})
            out = []
            for block in user.split("\n\n"):
                m = _HID.search(block)
                sid = _SID.search(block.split("\n", 1)[1]).group(0)
                out.append({"id": m.group(1), "task": f"补上这件事 [{sid}]"})
            return json.dumps({"holes": out}, ensure_ascii=False)
        raise AssertionError("没见过的提示词")
    return h


def _client(b, handler):
    backend = FakeBackend(handler=handler)
    return LLMClient(AppConfig(), backend, log_dir=b.logs_dir), backend


def _ids(ch):
    return [i["id"] for i in ch["items"]]


def test_生成骨架_顺序_分章_空洞说明_备注(book_with_threads):
    b = book_with_threads
    client, _ = _client(b, _handler())
    r = generate(b, client)
    assert r["written"] is True and r["fallback_chapters"] is False
    sk = read_json(b.skeleton_path)
    assert sk["by"] == "program"
    [vol] = sk["volumes"]
    assert vol["title"] == "卷一"
    assert [c["title"] for c in vol["chapters"]] == ["开篇", "龙宫"]
    assert _ids(vol["chapters"][0]) == ["S-0001", "H-001", "S-0002"]
    assert _ids(vol["chapters"][1]) == ["S-0003", "S-0004", "S-0005"]
    hole = vol["chapters"][0]["items"][1]
    assert hole["gap"] == "Q-001" and hole["task"].startswith("补上这件事 [S-")
    assert vol["chapters"][0]["notes"] == [{"kind": "undecided", "thread": "L-001"}]
    assert vol["chapters"][1]["notes"] == [{"kind": "undecided", "thread": "L-001"},
                                           {"kind": "undecided", "thread": "L-002"}]
    assert sk["unplaced"] == {"scenes": [], "holes": []}


def test_砍掉的线不进骨架_交汇处挂备注(book_with_threads):
    b = book_with_threads
    data = read_json(b.threads_path)
    data["intersections"] = [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "r"}]
    write_json(b.threads_path, data)
    th = load_threads(b)
    set_card(b, th, "L-001", "keep")
    set_card(b, th, "L-002", "cut")
    client, _ = _client(b, _handler(chapters={"volumes": [{"title": "卷一", "start": 0}],
                                              "chapters": [{"title": "全", "start": 0}]}))
    generate(b, client)
    [ch] = read_json(b.skeleton_path)["volumes"][0]["chapters"]
    assert _ids(ch) == ["S-0001", "H-001", "S-0002", "S-0003"]
    assert ch["notes"] == [{"kind": "cut_crossing", "thread": "L-002", "scene": "S-0002"}]


def test_分章一直不合规_用兜底切法(book_with_threads):
    b = book_with_threads
    bad = {"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "甲", "start": 3}]}
    client, _ = _client(b, _handler(chapters=bad))
    r = generate(b, client)
    assert r["fallback_chapters"] is True
    [vol] = read_json(b.skeleton_path)["volumes"]
    assert vol["title"] == "第1卷"
    assert [c["title"] for c in vol["chapters"]] == ["S-0001 摘要"]    # seed_book 的摘要默认是「S-000x 摘要」


def test_空洞说明模型失败_用程序拼的说明(book_with_threads):
    b = book_with_threads
    client, _ = _client(b, _handler(holes_ok=False))
    generate(b, client)
    hole = read_json(b.skeleton_path)["volumes"][0]["chapters"][0]["items"][1]
    assert hole["task"] == "在 S-0001 与 S-0003 之间补写：大闹天宫；原稿提到于 S-0002"


def test_重新生成先备份旧骨架(book_with_threads):
    b = book_with_threads
    client, _ = _client(b, _handler())
    generate(b, client)
    first = read_json(b.skeleton_path)
    generate(b, client)
    assert read_json(b.skeleton_bak_path) == first


def test_跑的途中看板被改_不写入(book_with_threads):
    b = book_with_threads
    state = {"n": 0}

    def touch():
        state["n"] += 1
        if state["n"] == 1:
            write_json(b.board_path, {"cards": {"L-002": {"col": "cut", "merge_into": None, "note": ""}}})

    client, _ = _client(b, _handler(on_call=touch))
    r = generate(b, client)
    assert r["written"] is False and r["input_changed"] is True
    assert not b.skeleton_path.exists()


def test_空洞说明核对():
    expect = {"H-001": {"S-0001", "S-0003"}, "H-002": {"S-0005"}}
    ok = {"holes": [{"id": "H-001", "task": "补 [S-0001]"}, {"id": "H-002", "task": "补 [S-0005]"}]}
    assert check_holes(ok, expect) == []
    bad = {"holes": [{"id": "H-001", "task": "补 [S-0005]"}, {"id": "H-001", "task": "没编号"}, {"id": "H-009", "task": "x"}]}
    text = "\n".join(check_holes(bad, expect))
    for word in ["S-0005", "重复", "H-009", "H-002", "场景编号"]:
        assert word in text


def test_兜底说明_没有锚点和出处也能写():
    assert fallback_task({"after": None, "before": None, "event": "某事", "mentioned_in": []}) == \
        "在 （开头） 与 （结尾） 之间补写：某事"


def _sk(items, unplaced=None):
    return {"generated": "x", "by": "program", "volumes": [{"title": "卷一", "chapters": [
        {"title": "章一", "items": items, "notes": []}]}],
            "unplaced": unplaced or {"scenes": [], "holes": []}}


def test_保存编辑_标成作者改过(book_with_threads):
    b = book_with_threads
    sk = save_skeleton(b, _sk([{"type": "scene", "id": "S-0001", "thread": "L-001"},
                               {"type": "hole", "id": "H-009", "task": "作者自己加的空洞"}]))
    assert sk["by"] == "author" and read_json(b.skeleton_path)["by"] == "author"


def test_保存编辑_校验(book_with_threads):
    b = book_with_threads
    cases = [
        (_sk([{"type": "scene", "id": "S-0099"}]), "S-0099"),
        (_sk([{"type": "scene", "id": "S-0001"}, {"type": "scene", "id": "S-0001"}]), "不止一次"),
        (_sk([{"type": "scene", "id": "S-0001"}], {"scenes": [{"id": "S-0001", "why": "no_time"}], "holes": []}), "不止一次"),
        (_sk([{"type": "hole", "id": "H-001"}]), "任务说明"),
        (_sk([{"type": "hole", "id": "H-001", "task": "a"}, {"type": "hole", "id": "H-001", "task": "b"}]), "H-001"),
        (_sk([{"type": "note", "id": "x"}]), "scene 或 hole"),
        ({"volumes": [{"title": "", "chapters": []}]}, "标题"),
        ({"volumes": "x"}, "volumes"),
    ]
    for sk, word in cases:
        with pytest.raises(ValueError) as e:
            save_skeleton(b, sk)
        assert word in str(e.value), (sk, str(e.value))


def test_保存时去掉界面标注(book_with_threads):
    b = book_with_threads
    save_skeleton(b, _sk([{"type": "scene", "id": "S-0001", "thread": "L-001", "flag": "cut"}]))
    item = read_json(b.skeleton_path)["volumes"][0]["chapters"][0]["items"][0]
    assert "flag" not in item


def test_读骨架_没有和坏了(book_with_threads):
    b = book_with_threads
    with pytest.raises(FileNotFoundError):
        load_skeleton(b)
    b.triage_dir.mkdir(parents=True, exist_ok=True)
    b.skeleton_path.write_text("{坏", encoding="utf-8")
    with pytest.raises(BrokenSkeletonFile):
        load_skeleton(b)


def test_对账标注_场景没了或线被砍(book_with_threads):
    b = book_with_threads
    th = load_threads(b)
    set_card(b, th, "L-002", "cut")
    sk = _sk([{"type": "scene", "id": "S-0001", "thread": "L-001"},
              {"type": "scene", "id": "S-0004", "thread": "L-002"},
              {"type": "scene", "id": "S-0099", "thread": "L-001"}],
             {"scenes": [{"id": "S-0005", "thread": "L-002", "why": "no_time"}], "holes": []})
    out = annotate(b, sk, th)
    flags = [i.get("flag") for i in out["volumes"][0]["chapters"][0]["items"]]
    assert flags == [None, "cut", "missing"]
    assert out["unplaced"]["scenes"][0]["flag"] == "cut"
    assert "flag" not in sk["volumes"][0]["chapters"][0]["items"][1]   # 不改原对象
