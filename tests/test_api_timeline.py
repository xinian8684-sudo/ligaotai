from urllib.parse import quote

from fastapi.testclient import TestClient
from helpers import FakeBackend

from ligaotai.api import create_app
from ligaotai.book import create_book, open_book
from ligaotai.config import library_path, load_config
from test_timeline_run import _book as _seed_timeline_book, _handler

BOOK = "/api/books/" + quote("测试书")


def _client(tmp_path):
    backend = FakeBackend(handler=_handler)
    app = create_app(app_dir=tmp_path, allowed_hosts=("testserver",), backend_factory=lambda cfg: backend)
    return TestClient(app)


def _book(tmp_path):
    lib = library_path(load_config(tmp_path), tmp_path)
    lib.mkdir(parents=True, exist_ok=True)
    try:
        return open_book(lib, "测试书")
    except FileNotFoundError:
        return create_book(lib, "测试书")


def _wait(c, r):
    assert r.status_code == 202, r.text
    job = c.app.state.runner.wait(r.json()["id"]).to_dict()
    assert job["status"] == "done", job["error"]
    return job


def _ready(tmp_path):
    b = _seed_timeline_book(_book(tmp_path))
    b.set_step("threads", "done")
    return b


def test_没归线不能跑(tmp_path):
    c = _client(tmp_path)
    _book(tmp_path)
    r = c.post(f"{BOOK}/timeline/run")
    assert r.status_code == 409 and "归线" in r.json()["detail"]


def test_跑_读_裁决(tmp_path):
    c = _client(tmp_path)
    _ready(tmp_path)
    assert c.get(f"{BOOK}/timeline").json()["never_run"] is True
    _wait(c, c.post(f"{BOOK}/timeline/run"))
    d = c.get(f"{BOOK}/timeline").json()
    assert [x["id"] for x in d["conflicts"]] == ["T-001", "T-002"] and d["stale"] is False
    r = c.put(f"{BOOK}/timeline/T-002/verdict", json={"kind": "order_error"})
    assert r.status_code == 200 and r.json()["verdict"]["kind"] == "order_error"
    assert c.put(f"{BOOK}/timeline/T-099/verdict", json={"kind": "ignore"}).status_code == 404
    assert c.put(f"{BOOK}/timeline/T-001/verdict", json={"kind": "乱写"}).status_code == 400


def test_结果文件坏了报500带文件名(tmp_path):
    c = _client(tmp_path)
    b = _ready(tmp_path)
    b.timeline_path.write_text("[1]", encoding="utf-8")
    r = c.get(f"{BOOK}/timeline")
    assert r.status_code == 500 and "时间冲突.json" in r.json()["detail"]


def test_归线或场景或实体文件坏了_GET照常200带stale(tmp_path):
    c = _client(tmp_path)
    b = _ready(tmp_path)
    _wait(c, c.post(f"{BOOK}/timeline/run"))

    b.threads_path.write_text("{bad", encoding="utf-8")
    d = c.get(f"{BOOK}/timeline")
    assert d.status_code == 200 and d.json()["stale"] is True and "支线" in d.json()["stale_reason"]

    b.threads_path.write_text(
        '{"threads": [{"id": "L-001", "offset": 0, "scenes": ["S-0001", "S-0002", "S-0003", "S-0004"], '
        '"times": {"S-0001": {"t": 0}, "S-0002": {"t": 1}, "S-0003": {"t": 2}, "S-0004": {"t": 3}}}], '
        '"worlds": [], "main_thread": "L-001", "global_order": [], "unassigned": [], "pending": [], '
        '"gaps": [], "intersections": []}', encoding="utf-8")  # 修回去，换成场景文件坏
    from ligaotai.scenes import scene_path
    scene_path(b, "S-0001").write_text("坏的场景文件", encoding="utf-8")
    d = c.get(f"{BOOK}/timeline")
    assert d.status_code == 200 and d.json()["stale"] is True and "场景" in d.json()["stale_reason"]


def test_裁决_时间冲突json坏了或不是字典_报500带文件名(tmp_path):
    c = _client(tmp_path)
    b = _ready(tmp_path)
    _wait(c, c.post(f"{BOOK}/timeline/run"))

    b.timeline_path.write_text("{bad", encoding="utf-8")
    r = c.put(f"{BOOK}/timeline/T-001/verdict", json={"kind": "ignore"})
    assert r.status_code == 500 and "时间冲突.json" in r.json()["detail"]

    b.timeline_path.write_text("[1]", encoding="utf-8")
    r = c.put(f"{BOOK}/timeline/T-001/verdict", json={"kind": "ignore"})
    assert r.status_code == 500 and "时间冲突.json" in r.json()["detail"]
