import json
import re
from dataclasses import replace

import pytest
from helpers import FakeBackend, seed_book

from ligaotai.config import AppConfig
from ligaotai.export import export_book, export_path
from ligaotai.fsutil import read_json, write_json
from ligaotai.llm import LLMClient
from ligaotai.scenes import get_scene, write_scene
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

_HID = re.compile(r"^### (\S+)$", re.M)  # S4：提示词里现在用缺口自己的编号（Q-xxx），不是 H-xxx
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


def test_模型一直不合规_坏结果不进缓存_再生成还会真调模型(book_with_threads):
    """T1/T2：分章、空洞两处调用都要传 usable。不传的话 Caller 会把重试用尽仍不合规的
    结果存进缓存，下次生成直接命中坏缓存、模型一次都不调，作者永远拿不到好结果。"""
    b = book_with_threads
    bad = {"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "甲", "start": 3}]}
    calls = {"n": 0}

    def count():
        calls["n"] += 1

    client, _ = _client(b, _handler(chapters=bad, holes_ok=False, on_call=count))
    generate(b, client)
    first = calls["n"]
    assert first > 0
    generate(b, client)
    assert calls["n"] == 2 * first    # 两处都没进缓存，第二次原样再调一遍


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


def test_空洞说明核对_id不是字符串不炸_报问题而不是抛异常():
    expect = {"H-001": {"S-0001"}}
    bad = {"holes": [{"id": ["H-001"], "task": "补 [S-0001]"}]}
    problems = check_holes(bad, expect)  # 不该抛 TypeError: unhashable type: 'list'
    assert any("没有这个空洞" in p for p in problems)


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


# ---------------------------------------------------------------------------
# F2 审 2（C 组）修复：M1/M3/S1-S6/T3-T7 的回归测试
# ---------------------------------------------------------------------------


def _ok_single_chapter() -> str:
    return json.dumps({"volumes": [{"title": "卷一", "start": 0}], "chapters": [{"title": "全", "start": 0}]},
                      ensure_ascii=False)


def _no_holes(tier, messages):
    if "分卷分章" in messages[0]["content"]:
        return _ok_single_chapter()
    return json.dumps({"holes": []})


def _ids_in(sk: dict) -> list[str]:
    ids = [i["id"] for v in sk["volumes"] for c in v["chapters"] for i in c["items"]]
    return ids + [x["id"] for x in sk["unplaced"]["scenes"]]


def test_空洞说明_模型第一次坏第二次好_重试用上第二次结果(book_with_threads):
    """M1：check_holes 对怪 id 报问题而不是抛异常，chat_json 的内部重试才有机会真的
    再问一次模型；旧代码一抛 TypeError，generate 就中断，模型只被调了一次、退回程序兜底，
    第二次模型明明会给出好结果也用不上。"""
    b = book_with_threads
    calls = {"holes": 0}

    def h(tier, messages):
        system, user = messages[0]["content"], messages[1]["content"]
        if "分卷分章" in system:
            return _ok_single_chapter()
        calls["holes"] += 1
        if calls["holes"] == 1:
            return json.dumps({"holes": [{"id": ["Q-001"], "task": "坏的 [S-0001]"}]}, ensure_ascii=False)
        return json.dumps({"holes": [{"id": "Q-001", "task": "补好了 [S-0001]"}]}, ensure_ascii=False)

    client, _ = _client(b, h)
    r = generate(b, client)
    hole = read_json(b.skeleton_path)["volumes"][0]["chapters"][0]["items"][1]
    assert calls["holes"] == 2
    assert hole["gap"] == "Q-001" and hole["task"] == "补好了 [S-0001]"
    assert r["failed"] == []   # 第二次成功了，不该算进失败清单


def test_换主版本后生成_非主成员替换成当前主版本_不整组消失(book_with_threads):
    """M3 / R6a：S-0002 归到 L-001 里那一刻还是主版本，作者后来把这组的主版本改成
    S-0006（S-0006 本身从没出现在任何线的 scenes 列表里）。生成骨架时 S-0002 的位置
    应该变成 S-0006，两个都消失才是 bug。"""
    b = book_with_threads
    write_json(b.versions_path, {"groups": [{"id": "V-001", "members": ["S-0002", "S-0006"],
                                             "main": "S-0006", "main_by": "author"}]})
    client, _ = _client(b, _no_holes)
    r = generate(b, client)
    assert r["written"] is True
    ids = _ids_in(read_json(b.skeleton_path))
    assert "S-0002" not in ids
    assert set(ids) == {"S-0001", "H-001", "S-0006", "S-0003", "S-0004", "S-0005"}


def test_骨架生成后才换主版本_标not_main_导出取主版本正文(book_with_threads):
    """M3 / R6b：骨架是在换主版本之前生成的，还留着 S-0002。GET 要标出这一项已经不是
    当前主版本；导出（spec 8「场景正文取原稿原文（主版本）」）不能继续印 S-0002 的旧文字，
    要换成 S-0006 现在的正文。"""
    b = book_with_threads
    client, _ = _client(b, _no_holes)
    generate(b, client)
    write_json(b.versions_path, {"groups": [{"id": "V-001", "members": ["S-0002", "S-0006"],
                                             "main": "S-0006", "main_by": "author"}]})
    th = load_threads(b)
    ann = annotate(b, load_skeleton(b), th)
    flags = {i["id"]: i.get("flag") for v in ann["volumes"] for c in v["chapters"] for i in c["items"]}
    assert flags["S-0002"] == "not_main"
    export_book(b)
    md = export_path(b, "md").read_text(encoding="utf-8")
    assert "<!-- S-0006 -->" in md and "<!-- S-0002 -->" not in md
    assert "花果山在东胜神洲" in md


def test_已移除场景不进骨架_也不进未定位(book_with_threads):
    """T4：drop 集合去掉「已移除的场景」这半边，现有测试都不会红——book_with_threads
    默认没有任何 removed 场景，没有一个 skeleton.py 级别的测试会因为漏传这半边而失败。"""
    b = book_with_threads
    sc = get_scene(b, "S-0002")
    write_scene(b, replace(sc, removed=True))
    client, _ = _client(b, _no_holes)
    generate(b, client)
    ids = _ids_in(read_json(b.skeleton_path))
    assert "S-0002" not in ids


def test_保存时删场景被拒绝(book_with_threads):
    """S3：PUT 把骨架里的场景删掉不该被静默接受——导出会悄悄少一块，作者很难发现。"""
    b = book_with_threads
    client, _ = _client(b, _no_holes)
    generate(b, client)
    sk = read_json(b.skeleton_path)
    items = sk["volumes"][0]["chapters"][0]["items"]
    sk["volumes"][0]["chapters"][0]["items"] = [i for i in items if i.get("id") != "S-0002"]
    with pytest.raises(ValueError) as e:
        save_skeleton(b, sk)
    assert "S-0002" in str(e.value)
    # 磁盘上原来的骨架没被这次失败的保存改坏
    assert any(i.get("id") == "S-0002" for i in read_json(b.skeleton_path)["volumes"][0]["chapters"][0]["items"])


def test_读骨架_列出应该在书里却找不到的场景(book_with_threads):
    """S3：绕开 save_skeleton 校验的场景丢失（手改文件、旧数据）——GET 要在 absent 里报出来，
    不能装作没看见。"""
    b = book_with_threads
    client, _ = _client(b, _no_holes)
    generate(b, client)
    sk = read_json(b.skeleton_path)
    items = sk["volumes"][0]["chapters"][0]["items"]
    sk["volumes"][0]["chapters"][0]["items"] = [i for i in items if i.get("id") != "S-0002"]
    write_json(b.skeleton_path, sk)
    ann = annotate(b, load_skeleton(b), load_threads(b))
    assert ann["absent"] == ["S-0002"]


def test_读骨架_归线后新增的场景也列进absent(book_with_threads):
    """S3：骨架生成之后又重跑了一次归线，新场景进了线里，骨架却是旧的——覆盖「重跑归线后
    的新场景」这条（context.md S3 描述的第二种情形）。"""
    b = book_with_threads
    client, _ = _client(b, _no_holes)
    generate(b, client)
    data = read_json(b.threads_path)
    data["threads"][1]["scenes"].append("S-0006")
    data["threads"][1]["times"]["S-0006"] = {"t": 2}
    write_json(b.threads_path, data)
    ann = annotate(b, load_skeleton(b), load_threads(b))
    assert "S-0006" in ann["absent"]


def test_插入新缺口_原有空洞批命中缓存_只增加新批调用(book_with_threads, monkeypatch):
    """S4：分批要按缺口自己的编号（稳定）分桶，不能按它们在序列里的位置分桶——插一个新
    缺口会让后面所有缺口的位置往后挪，拿位置分批会让原来那些批次的请求文本、缓存键跟着
    全变，明明没改的空洞也要重新真调一次模型（重付一次钱）。"""
    import ligaotai.skeleton as skl_mod

    b = book_with_threads
    monkeypatch.setattr(skl_mod, "HOLE_BATCH", 1)
    data = read_json(b.threads_path)
    data["gaps"] = [
        {"id": "Q-001", "world": "W-01", "event": "甲事", "mentioned_in": [], "thread": "L-001",
         "after": "S-0002", "before": None},
        {"id": "Q-002", "world": "W-01", "event": "乙事", "mentioned_in": [], "thread": "L-002",
         "after": "S-0005", "before": None},
    ]
    write_json(b.threads_path, data)
    hole_calls = []

    def h(tier, messages):
        system, user = messages[0]["content"], messages[1]["content"]
        if "分卷分章" in system:
            return _ok_single_chapter()
        gid = _HID.search(user).group(1)
        sid = _SID.search(user).group(0)
        hole_calls.append(gid)
        return json.dumps({"holes": [{"id": gid, "task": f"补 [{sid}]"}]}, ensure_ascii=False)

    client, _ = _client(b, h)
    generate(b, client)
    first = list(hole_calls)
    hole_calls.clear()
    data["gaps"].insert(0, {"id": "Q-003", "world": "W-01", "event": "新加的丙事", "mentioned_in": [],
                            "thread": "L-001", "after": "S-0001", "before": None})
    write_json(b.threads_path, data)
    generate(b, client)
    assert first == ["Q-001", "Q-002"]
    assert hole_calls == ["Q-003"]   # 原有两批命中缓存，真调模型的只有新插入的这一批


def test_跑的途中版本组被改_不写入(book_with_threads):
    """T5：input_fingerprint 去掉版本组.json 这一路不会让现有测试变红——补一条跟
    「跑的途中看板被改」对称的用例。"""
    b = book_with_threads
    state = {"n": 0}

    def touch():
        state["n"] += 1
        if state["n"] == 1:
            write_json(b.versions_path, {"groups": [{"id": "V-001", "members": ["S-0001", "S-0099"],
                                                      "main": "S-0001", "main_by": "author"}]})

    client, _ = _client(b, _handler(on_call=touch))
    r = generate(b, client)
    assert r["written"] is False and r["input_changed"] is True
    assert not b.skeleton_path.exists()


def test_多窗口生成_不重不漏(book):
    """T7：把审查 R11（预算小、场景多、真的走多窗口 + 合并分支）固化成正式测试——之前没有
    任何测试真的让 generate() 切出两个以上窗口。"""
    b = book
    seed_book(b, [{"id": f"S-{i:04d}"} for i in range(1, 41)])
    write_json(b.threads_path, {"main_thread": "L-001", "worlds": [], "intersections": [], "gaps": [],
                                "unassigned": [], "pending": [],
                                "threads": [{"id": "L-001", "scenes": [f"S-{i:04d}" for i in range(1, 41)],
                                             "offset": 0, "times": {f"S-{i:04d}": {"t": i} for i in range(1, 41)}}]})
    b.update(lambda d: d.setdefault("settings", {}).update({"skeleton_max_input_tokens": 500}))
    wins = []

    def h(tier, messages):
        user = messages[1]["content"]
        n = int(re.search(r"共 (\d+) 行", user).group(1))
        first = re.search(r"^0｜(S-\d{4})", user, re.M).group(1)
        wins.append((first, n))
        return json.dumps({"volumes": [{"title": f"卷@{first}", "start": 0},
                                       {"title": f"卷2@{first}", "start": n // 2}],
                           "chapters": [{"title": f"章@{first}", "start": 0},
                                       {"title": f"中@{first}", "start": n // 2}]},
                          ensure_ascii=False)

    client, _ = _client(b, h)
    r = generate(b, client)
    assert r["written"] is True
    assert len(wins) >= 2   # 真的切出了不止一个窗口，走到了 merge_windows 分支
    sk = read_json(b.skeleton_path)
    ids = [i["id"] for v in sk["volumes"] for c in v["chapters"] for i in c["items"]]
    assert len(ids) == 40 and len(set(ids)) == 40
    assert ids == [f"S-{i:04d}" for i in range(1, 41)]   # 顺序不因为切窗口/合并而乱
