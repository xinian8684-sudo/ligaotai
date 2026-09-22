"""二期接口：裁决、看板、影响、骨架、导出。"""

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from helpers import FakeBackend

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
