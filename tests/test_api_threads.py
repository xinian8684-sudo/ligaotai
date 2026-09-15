import pytest
from fastapi.testclient import TestClient
from helpers import FakeBackend, fake_ai_handler, threads_handler

from ligaotai.api import create_app

STORY = {
    "1.txt": "第一章 雪夜\n林清年方十六，住在青州城外。\n\n第二章 离城\n清儿背着包袱出了门，赵五在后面跟着。",
    "2.txt": "第三章 天机\n林姑娘进了天机阁，赵五守在门口。",
}
BOOK = "/api/books/我的书"


def make_client(tmp_path):
    fake = FakeBackend(handler=threads_handler(fallback=fake_ai_handler([["林清", "清儿", "林姑娘"]])))
    app = create_app(app_dir=tmp_path, allowed_hosts=("testserver",), backend_factory=lambda cfg: fake)
    return TestClient(app)


def wait(client, response):
    assert response.status_code == 202, response.text
    job = client.app.state.runner.wait(response.json()["id"]).to_dict()
    assert job["status"] == "done", job["error"]
    return job


@pytest.fixture
def carded(tmp_path):
    c = make_client(tmp_path)
    src = tmp_path / "稿"
    src.mkdir()
    for name, text in STORY.items():
        (src / name).write_text(text, encoding="utf-8")
    c.post("/api/books", json={"title": "我的书"})
    wait(c, c.post(f"{BOOK}/import", json={"folder": str(src)}))
    for step in ("split", "dedup", "cards"):
        wait(c, c.post(f"{BOOK}/steps/{step}/run"))
    return c


@pytest.fixture
def ready(carded):
    wait(carded, carded.post(f"{BOOK}/steps/entities/run"))
    return carded


def test_threads_need_entities_first(carded):
    assert carded.post(f"{BOOK}/steps/threads/run").status_code == 409


def test_threads_flow(ready):
    c = ready
    wait(c, c.post(f"{BOOK}/steps/threads/run"))
    [t] = c.get(f"{BOOK}/threads").json()["threads"]
    assert t["id"] == "L-001" and t["scenes"] == ["S-0001", "S-0002", "S-0003"]
    assert c.post(f"{BOOK}/threads/confirm", json={"ids": ["L-001"]}).json()[0]["status"] == "confirmed"
    assert c.put(f"{BOOK}/threads/L-001/name", json={"name": "林清的路"}).json()["name"] == "林清的路"
    assert c.put(f"{BOOK}/threads/W-01/name", json={"name": "人间"}).json()["name"] == "人间"
    moved = c.post(f"{BOOK}/threads/L-001/scenes", json={"ids": ["S-0003"], "position": 0}).json()
    assert moved["scenes"] == ["S-0003", "S-0001", "S-0002"]
    new = c.post(f"{BOOK}/threads/L-001/split", json={"from_scene": "S-0001"}).json()
    assert new["id"] == "L-002" and new["scenes"] == ["S-0001", "S-0002"]
    merged = c.post(f"{BOOK}/threads/merge", json={"ids": ["L-001", "L-002"]}).json()
    assert merged["scenes"] == ["S-0003", "S-0001", "S-0002"]
    assert c.put(f"{BOOK}/threads/main", json={"thread": "L-001"}).json()["id"] == "L-001"
    assert c.put(f"{BOOK}/threads/L-001/world", json={"world": "W-01"}).json()["world"] == "W-01"
    assert c.get(BOOK).json()["usage"]["by_step"]["threads"]["calls"] == 3  # 划世界、划支线、排序


def test_threads_errors(ready):
    c = ready
    assert c.get(f"{BOOK}/threads").json()["threads"] == []
    assert c.post(f"{BOOK}/threads/confirm", json={"ids": ["L-001"]}).status_code == 404  # 还没跑步骤 6
    wait(c, c.post(f"{BOOK}/steps/threads/run"))
    assert c.post(f"{BOOK}/threads/confirm", json={"ids": ["L-099"]}).status_code == 404
    assert c.put(f"{BOOK}/threads/L-001/name", json={"name": " "}).status_code == 400
    assert c.post(f"{BOOK}/threads/merge", json={"ids": ["L-001"]}).status_code == 400
    assert c.post(f"{BOOK}/threads/L-001/scenes", json={"ids": ["S-0404"]}).status_code == 400
    assert c.post(f"{BOOK}/threads/L-001/split", json={"from_scene": "S-0001"}).status_code == 400
    assert c.put(f"{BOOK}/threads/L-001/world", json={"world": "W-09"}).status_code == 404
    assert c.put(f"{BOOK}/threads/main", json={"thread": "L-099"}).status_code == 404


def test_threads_get_before_run_has_full_shape(ready):
    """还没跑过步骤 6 时，GET /threads 也给完整结构（含 pending / unassigned / main_thread 等键），
    前端不用猜哪些键可能没有（task16_notes.md 第 1 条）。"""
    d = ready.get(f"{BOOK}/threads").json()
    assert d["threads"] == [] and d["worlds"] == []
    assert d["pending"] == [] and d["unassigned"] == [] and d["gaps"] == [] and d["intersections"] == []
    assert d["main_thread"] is None and d["main_by"] == "auto"
