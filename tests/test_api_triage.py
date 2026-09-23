"""二期接口：裁决、看板、影响、骨架、导出。"""

import json
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from helpers import FakeBackend, seed_book

from ligaotai.api import create_app
from ligaotai.book import create_book, open_book
from ligaotai.config import library_path, load_config
from ligaotai.fsutil import read_json, write_json

BOOK = "/api/books/" + quote("测试书")


def _client(tmp_path, handler=None):
    backend = FakeBackend(handler=handler or (lambda tier, messages: "{}"))
    app = create_app(app_dir=tmp_path, allowed_hosts=("testserver",), backend_factory=lambda cfg: backend)
    c = TestClient(app)
    c.backend = backend
    return c


def _book(tmp_path):
    lib = library_path(load_config(tmp_path), tmp_path)
    lib.mkdir(parents=True, exist_ok=True)
    try:
        return open_book(lib, "测试书")
    except FileNotFoundError:
        return create_book(lib, "测试书")


def _contradictions(book):
    write_json(book.contradictions_path, {"groups": [{
        "id": "C-001", "subject": "小梅", "attribute": "年龄", "status": "真矛盾", "level": "严重",
        "category": "人物", "reason": "r [S-0001]",
        "values": [{"value": "十三", "scenes": [{"id": "S-0001", "quote": "年方十三", "thread": "L-001", "t": 0, "conf": "高"}]},
                   {"value": "十七", "scenes": [{"id": "S-0002", "quote": "今年十七", "thread": "L-001", "t": 1, "conf": "中"}]}],
        "values_sig": "sig1", "verdict": None, "verdict_sig": None, "verdict_stale": False}], "stats": {}})


def test_写裁决_读定稿设定_读要跟着改的场景(tmp_path):
    c = _client(tmp_path)
    _contradictions(_book(tmp_path))
    r = c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": "pick", "value": "十三"})
    assert r.status_code == 200, r.text
    assert r.json()["verdict"]["value"] == "十三"
    assert c.get(f"{BOOK}/canon").json()["items"][0]["value"] == "十三"
    f = c.get(f"{BOOK}/contradictions/C-001/followups").json()
    assert [s["id"] for s in f["scenes"]] == ["S-0002"]


def test_撤销裁决(tmp_path):
    c = _client(tmp_path)
    _contradictions(_book(tmp_path))
    c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": "later"})
    r = c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": None})
    assert r.json()["verdict"] is None


def test_裁决的错误映射(tmp_path):
    c = _client(tmp_path)
    b = _book(tmp_path)
    assert c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": "later"}).status_code == 404  # 没跑步骤 7
    _contradictions(b)
    assert c.put(f"{BOOK}/contradictions/C-009/verdict", json={"kind": "later"}).status_code == 404
    assert c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": "pick", "value": "九十"}).status_code == 400
    b.contradictions_path.write_text("{坏", encoding="utf-8")
    r = c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": "later"})
    assert r.status_code == 500 and "矛盾.json" in r.json()["detail"]


def test_有任务在跑时写裁决返回409(tmp_path, monkeypatch):
    c = _client(tmp_path)
    _contradictions(_book(tmp_path))

    class _Job:
        status, name, book = "running", "archive", "测试书"

    monkeypatch.setattr(c.app.state.runner, "current", lambda: _Job())
    assert c.put(f"{BOOK}/contradictions/C-001/verdict", json={"kind": "later"}).status_code == 409


def _seed_threads(tmp_path):
    b = _book(tmp_path)
    seed_book(b, [{"id": f"S-000{i}", "persons": ["敖广"] if i >= 4 else ["悟空"]} for i in range(1, 6)])
    write_json(b.threads_path, {
        "next_world": 2, "next_thread": 3, "time_unit": "年", "main_thread": "L-001", "main_by": "auto",
        "worlds": [{"id": "W-01", "name": "西游", "reason": "", "status": "draft", "notes": [], "outlines": []}],
        "threads": [
            {"id": "L-001", "world": "W-01", "name": "取经", "about": "主线", "status": "draft",
             "scenes": ["S-0001", "S-0002", "S-0003"],
             "times": {"S-0001": {"t": 0, "conf": "高"}, "S-0002": {"t": 1, "conf": "高"}, "S-0003": {"t": 2, "conf": "高"}},
             "outlines": [], "offset": 0, "end": {"state": "待定", "note": "", "last": "S-0003"}, "order_failed": False},
            {"id": "L-002", "world": "W-01", "name": "龙宫", "about": "支线", "status": "draft",
             "scenes": ["S-0004", "S-0005"],
             "times": {"S-0004": {"t": 0, "conf": "高"}, "S-0005": {"t": 1, "conf": "高"}},
             "outlines": [], "offset": 3, "end": {"state": "完结", "note": "", "last": "S-0005"}, "order_failed": False}],
        "intersections": [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "借宝"}],
        "gaps": [], "unassigned": [], "pending": []})
    return b


def _wait(c, r):
    assert r.status_code == 202, r.text
    job = c.app.state.runner.wait(r.json()["id"]).to_dict()
    assert job["status"] == "done", job["error"]
    return job


def test_读看板_带统计和空建议(tmp_path):
    c = _client(tmp_path)
    _seed_threads(tmp_path)
    r = c.get(f"{BOOK}/triage/board").json()
    assert r["cards"]["L-001"]["col"] == "undecided"
    assert r["stats"]["L-001"]["is_main"] is True
    assert r["advice"] is None


def test_改卡_错误映射(tmp_path):
    c = _client(tmp_path)
    _seed_threads(tmp_path)
    r = c.put(f"{BOOK}/triage/board/L-002", json={"col": "merge", "merge_into": "L-001"})
    assert r.status_code == 200 and r.json()["cards"]["L-002"]["merge_into"] == "L-001"
    assert c.put(f"{BOOK}/triage/board/L-009", json={"col": "keep"}).status_code == 404
    assert c.put(f"{BOOK}/triage/board/L-002", json={"col": "maybe"}).status_code == 400
    assert c.delete(f"{BOOK}/triage/board/L-001").status_code == 400


def test_实体文件坏了_报500带文件名(tmp_path):
    c = _client(tmp_path)
    b = _seed_threads(tmp_path)
    b.entities_path.parent.mkdir(parents=True, exist_ok=True)
    b.entities_path.write_text("{坏", encoding="utf-8")
    r = c.get(f"{BOOK}/triage/impact/L-002")
    assert r.status_code == 500 and "实体.json" in r.json()["detail"]


def test_实体条目缺canonical_报500不是404(tmp_path):
    c = _client(tmp_path)
    b = _seed_threads(tmp_path)
    write_json(b.entities_path, {"next_id": 2, "entities": [
        {"id": "E-0001", "type": "person", "names": ["悟空"], "status": "draft", "reason": "", "scenes": []}]})
    r = c.get(f"{BOOK}/triage/impact/L-002")
    assert r.status_code == 500 and "文件缺字段" in r.json()["detail"]


def test_场景文件坏了_报500不是400(tmp_path):
    c = _client(tmp_path)
    b = _seed_threads(tmp_path)
    from ligaotai.scenes import scene_path
    scene_path(b, "S-0001").write_bytes(b"\xff\xfe\x00broken")
    r = c.get(f"{BOOK}/triage/board")
    assert r.status_code == 500 and "S-0001" in r.json()["detail"]


def test_看板文件坏了报500带文件名(tmp_path):
    c = _client(tmp_path)
    b = _seed_threads(tmp_path)
    b.triage_dir.mkdir(parents=True, exist_ok=True)
    b.board_path.write_text("{坏", encoding="utf-8")
    r = c.get(f"{BOOK}/triage/board")
    assert r.status_code == 500 and "看板.json" in r.json()["detail"]


def test_没跑归线时看板404(tmp_path):
    c = _client(tmp_path)
    _book(tmp_path)
    assert c.get(f"{BOOK}/triage/board").status_code == 404


def test_生成建议是任务_跑完看板里带建议(tmp_path):
    reply = {"advice": [{"thread": "L-001", "advice": "keep", "merge_into": None, "reason": "主线 [S-0001]"},
                        {"thread": "L-002", "advice": "cut", "merge_into": None, "reason": "可删 [S-0004]"}]}
    c = _client(tmp_path, handler=lambda tier, messages: json.dumps(reply, ensure_ascii=False))
    _seed_threads(tmp_path)
    _wait(c, c.post(f"{BOOK}/triage/advice"))
    adv = c.get(f"{BOOK}/triage/board").json()["advice"]
    assert [i["advice"] for i in adv["items"]] == ["keep", "cut"] and adv["stale"] is False


def test_影响检查_程序部分即时_模型部分是任务(tmp_path):
    reply = {"pairs": [], "remedy": "无须补救 [S-0004]"}
    c = _client(tmp_path, handler=lambda tier, messages: json.dumps(reply, ensure_ascii=False))
    b = _seed_threads(tmp_path)
    r = c.get(f"{BOOK}/triage/impact/L-002").json()
    assert r["program"]["crossings"][0]["main_scene"] == "S-0002"
    assert r["model"] is None
    assert c.post(f"{BOOK}/triage/impact/L-002").status_code == 400  # 还在「还没想好」列
    c.put(f"{BOOK}/triage/board/L-002", json={"col": "cut"})
    from ligaotai.cards import card_path
    rec = read_json(card_path(b, "S-0004"))
    rec["card"]["hooks_planted"] = ["龙宫宝物的下落"]
    write_json(card_path(b, "S-0004"), rec)
    _wait(c, c.post(f"{BOOK}/triage/impact/L-002"))
    m = c.get(f"{BOOK}/triage/impact/L-002").json()["model"]
    assert m["remedy"] == "无须补救 [S-0004]" and m["stale"] is False


def test_有任务在跑时改卡或删孤儿卡返回409(tmp_path, monkeypatch):
    c = _client(tmp_path)
    _seed_threads(tmp_path)

    class _Job:
        status, name, book = "running", "archive", "测试书"

    monkeypatch.setattr(c.app.state.runner, "current", lambda: _Job())
    assert c.put(f"{BOOK}/triage/board/L-002", json={"col": "cut"}).status_code == 409
    assert c.delete(f"{BOOK}/triage/board/L-009").status_code == 409


def _sk_handler(tier, messages):
    system, user = messages[0]["content"], messages[1]["content"]
    if "分卷分章" in system:
        return json.dumps({"volumes": [{"title": "卷一", "start": 0}], "chapters": [{"title": "全", "start": 0}]},
                          ensure_ascii=False)
    return json.dumps({"holes": []})


def test_生成骨架_读_改_导出_下载(tmp_path):
    c = _client(tmp_path, handler=_sk_handler)
    _seed_threads(tmp_path)
    _wait(c, c.post(f"{BOOK}/skeleton/generate"))
    sk = c.get(f"{BOOK}/skeleton").json()
    assert [i["id"] for i in sk["volumes"][0]["chapters"][0]["items"]] == ["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"]
    sk["volumes"][0]["chapters"][0]["title"] = "改过的章名"
    r = c.put(f"{BOOK}/skeleton", json=sk)
    assert r.status_code == 200 and r.json()["by"] == "author"
    bad = {**sk, "volumes": [{"title": "卷", "chapters": [{"title": "章", "items": [{"type": "scene", "id": "S-0099"}]}]}]}
    assert c.put(f"{BOOK}/skeleton", json=bad).status_code == 400
    r = c.post(f"{BOOK}/export")
    assert r.status_code == 200 and r.json()["scenes"] == 5
    d = c.get(f"{BOOK}/export/md")
    assert d.status_code == 200 and "## 改过的章名" in d.content.decode("utf-8")
    assert c.get(f"{BOOK}/export/docx").status_code == 400


def test_骨架的错误映射(tmp_path):
    c = _client(tmp_path)
    b = _seed_threads(tmp_path)
    assert c.get(f"{BOOK}/skeleton").status_code == 404
    assert c.post(f"{BOOK}/export").status_code == 404
    assert c.get(f"{BOOK}/export/md").status_code == 404
    b.triage_dir.mkdir(parents=True, exist_ok=True)
    b.skeleton_path.write_text("{坏", encoding="utf-8")
    r = c.get(f"{BOOK}/skeleton")
    assert r.status_code == 500 and "骨架.json" in r.json()["detail"]
