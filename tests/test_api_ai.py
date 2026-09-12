import threading

import pytest
from fastapi.testclient import TestClient
from helpers import FakeBackend, fake_ai_handler

from ligaotai.api import create_app
from ligaotai.book import open_book

STORY = {
    "1.txt": "第一章 雪夜\n林清年方十六，住在青州城外。\n\n第二章 离城\n清儿背着包袱出了门，赵五在后面跟着。",
    "2.txt": "第三章 天机\n林姑娘进了天机阁，赵五守在门口。",
}
BOOK = "/api/books/我的书"


def make_client(tmp_path, groups=(["林清", "清儿", "林姑娘"],)):
    fake = FakeBackend(handler=fake_ai_handler(groups))
    app = create_app(app_dir=tmp_path, allowed_hosts=("testserver",), backend_factory=lambda cfg: fake)
    return TestClient(app)


def wait(client, response):
    assert response.status_code == 202, response.text
    job = client.app.state.runner.wait(response.json()["id"]).to_dict()
    assert job["status"] == "done", job["error"]
    return job


@pytest.fixture
def ready(tmp_path):
    c = make_client(tmp_path)
    src = tmp_path / "稿"
    src.mkdir()
    for name, text in STORY.items():
        (src / name).write_text(text, encoding="utf-8")
    c.post("/api/books", json={"title": "我的书"})
    wait(c, c.post(f"{BOOK}/import", json={"folder": str(src)}))
    wait(c, c.post(f"{BOOK}/steps/split/run"))
    wait(c, c.post(f"{BOOK}/steps/dedup/run"))
    return c


def test_cards_then_entities_flow(ready):
    c = ready
    wait(c, c.post(f"{BOOK}/steps/cards/run"))
    cards = c.get(f"{BOOK}/cards").json()
    assert [x["id"] for x in cards] == ["S-0001", "S-0002", "S-0003"]
    assert all(x["fresh"] and x["kind"] == "正文" for x in cards)
    assert c.get(f"{BOOK}/cards/S-0001").json()["card"]["characters"][0]["name"] == "林清"
    assert c.get(f"{BOOK}/cards/S-9999").status_code == 404
    wait(c, c.post(f"{BOOK}/cards/S-0002/regenerate"))

    wait(c, c.post(f"{BOOK}/steps/entities/run"))
    ents = c.get(f"{BOOK}/entities").json()["entities"]
    group = next(e for e in ents if e["status"] == "draft")
    assert set(group["names"]) == {"林清", "清儿", "林姑娘"}
    zhao = next(e for e in ents if e["canonical"] == "赵五")

    assert c.post(f"{BOOK}/entities/confirm", json={"ids": [group["id"]]}).json()[0]["status"] == "confirmed"
    assert c.put(f"{BOOK}/entities/{group['id']}", json={"canonical": "林小清"}).json()["canonical"] == "林小清"
    merged = c.post(f"{BOOK}/entities/merge", json={"ids": [group["id"], zhao["id"]]}).json()
    assert "赵五" in merged["names"]
    new = c.post(f"{BOOK}/entities/{group['id']}/split", json={"names": ["赵五"]}).json()
    assert new["names"] == ["赵五"]

    usage = c.get(BOOK).json()["usage"]
    assert usage["by_step"]["cards"]["calls"] == 4 and usage["by_step"]["entities"]["calls"] == 1


def test_entity_errors(ready):
    c = ready
    wait(c, c.post(f"{BOOK}/steps/cards/run"))
    wait(c, c.post(f"{BOOK}/steps/entities/run"))
    ents = c.get(f"{BOOK}/entities").json()["entities"]
    assert c.post(f"{BOOK}/entities/merge", json={"ids": [ents[0]["id"]]}).status_code == 400
    assert c.post(f"{BOOK}/entities/confirm", json={"ids": ["E-9999"]}).status_code == 404
    assert c.put(f"{BOOK}/entities/E-9999", json={"canonical": "x"}).status_code == 404


def test_entities_need_cards_first(ready):
    assert ready.post(f"{BOOK}/steps/entities/run").status_code == 409


def test_entity_ops_before_run_are_404(ready):
    assert ready.post(f"{BOOK}/entities/confirm", json={"ids": ["E-0001"]}).status_code == 404


def test_no_key_is_400(tmp_path):
    c = TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",)))
    c.post("/api/books", json={"title": "我的书"})
    book = open_book(tmp_path / "书库", "我的书")
    for step in ("import", "split", "dedup"):
        book.set_step(step, "done")
    r = c.post(f"{BOOK}/steps/cards/run")
    assert r.status_code == 400 and "API key" in r.json()["detail"]
    assert c.post("/api/config/test").status_code == 400


def test_config_test_endpoint(tmp_path):
    results = make_client(tmp_path).post("/api/config/test").json()
    assert [(r["tier"], r["ok"]) for r in results] == [("batch", True), ("synth", True)]


def test_cancel_endpoint(tmp_path):
    c = make_client(tmp_path)
    started, release = threading.Event(), threading.Event()

    def fn(progress):
        started.set()
        release.wait(5)
        progress(1, 1)
        return {}

    job = c.app.state.runner.submit("cards", "我的书", fn)
    started.wait(5)
    assert c.post(f"/api/jobs/{job.id}/cancel").json()["cancel_requested"] is True
    release.set()
    assert c.app.state.runner.wait(job.id).status == "cancelled"
    assert c.post("/api/jobs/nope/cancel").status_code == 404


def test_paused_step_is_marked(ready):
    c = ready
    runner = c.app.state.runner
    r = c.post(f"{BOOK}/steps/cards/run")
    job_id = r.json()["id"]
    runner.cancel(job_id)
    job = runner.wait(job_id)
    if job.status == "cancelled":
        assert "已暂停" in c.get(BOOK).json()["steps"]["cards"]["summary"]["error"]
