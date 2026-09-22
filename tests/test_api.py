import threading

import pytest
from fastapi.testclient import TestClient
from helpers import gen_text

from ligaotai.api import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",)))


def wait(client, job):
    return client.app.state.runner.wait(job["id"]).to_dict()


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "稿"
    d.mkdir()
    text = gen_text(1, 2000)
    (d / "1甲.txt").write_text("第一章 甲\n" + text, encoding="utf-8")
    (d / "2乙.txt").write_text("第一章 甲\n" + text + "多写了一句。", encoding="utf-8")
    return d


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_rejects_foreign_host(tmp_path):
    c = TestClient(create_app(app_dir=tmp_path))  # 默认只认 127.0.0.1 / localhost
    assert c.get("/api/health").status_code == 400


def test_config_default_library(client, tmp_path):
    assert client.get("/api/config").json()["library_path"] == str(tmp_path / "书库")


def test_books_crud(client):
    r = client.post("/api/books", json={"title": "我的书"})
    assert r.status_code == 201
    assert r.json()["name"] == "我的书"
    assert client.post("/api/books", json={"title": "我的书"}).status_code == 409
    assert [b["title"] for b in client.get("/api/books").json()] == ["我的书"]
    assert client.get("/api/books/我的书").json()["steps"]["import"]["status"] == "todo"
    assert client.get("/api/books/没有").status_code == 404


def test_book_meta_有来源路径(client, src):
    client.post("/api/books", json={"title": "我的书"})
    r = client.post("/api/books/我的书/import", json={"folder": str(src)})
    wait(client, r.json())
    roots = client.get("/api/books/我的书").json()["roots"]
    assert roots["稿"] == str(src.resolve())


def test_full_flow(client, src):
    client.post("/api/books", json={"title": "我的书"})

    r = client.post("/api/books/我的书/import", json={"folder": str(src)})
    assert r.status_code == 202
    assert wait(client, r.json())["status"] == "done"

    for step in ("split", "dedup"):
        r = client.post(f"/api/books/我的书/steps/{step}/run")
        assert r.status_code == 202
        job = wait(client, r.json())
        assert job["status"] == "done", job["error"]

    steps = client.get("/api/books/我的书").json()["steps"]
    assert [steps[s]["status"] for s in ("import", "split", "dedup")] == ["done"] * 3

    scenes = client.get("/api/books/我的书/scenes").json()
    assert [s["id"] for s in scenes] == ["S-0001", "S-0002"]
    assert "text" not in scenes[0]
    one = client.get("/api/books/我的书/scenes/S-0002").json()
    assert one["text"].endswith("多写了一句。")

    [g] = client.get("/api/books/我的书/versions").json()["groups"]
    assert g["members"] == ["S-0001", "S-0002"]
    assert g["main"] == "S-0002"  # 更长
    r = client.put(f"/api/books/我的书/versions/{g['id']}/main", json={"scene_id": "S-0001"})
    assert r.json()["main_by"] == "author"

    r = client.get("/api/books/我的书/source", params={"path": "稿/1甲.txt"})
    assert r.json()["text"].startswith("第一章 甲")


def test_import_own_book_folder_is_400(client, tmp_path):
    client.post("/api/books", json={"title": "我的书"})
    own = tmp_path / "书库" / "我的书"
    r = client.post("/api/books/我的书/import", json={"folder": str(own)})
    assert r.status_code == 400


def test_errors(client, src):
    client.post("/api/books", json={"title": "我的书"})
    # threads / archive 从计划②b、②c 起都是合法步骤名，上游没做完时统一返回 409。
    assert client.post("/api/books/我的书/steps/threads/run").status_code == 409
    assert client.post("/api/books/我的书/steps/archive/run").status_code == 409
    assert client.post("/api/books/我的书/import", json={"folder": str(src / "没有")}).status_code == 400
    assert client.get("/api/books/我的书/scenes/..%2Fbook").status_code == 404
    assert client.get("/api/books/我的书/scenes/S-0001").status_code == 404
    assert client.get("/api/books/我的书/source", params={"path": "../book.json"}).status_code == 404
    assert client.put("/api/books/我的书/versions/G-001/main", json={"scene_id": "S-0001"}).status_code == 404
    assert client.get("/api/jobs/nope").status_code == 404


def test_step_requires_upstream_done(client, src):
    client.post("/api/books", json={"title": "我的书"})

    r = client.post("/api/books/我的书/steps/split/run")
    assert r.status_code == 409

    r = client.post("/api/books/我的书/import", json={"folder": str(src)})
    wait(client, r.json())

    r = client.post("/api/books/我的书/steps/split/run")
    assert r.status_code == 202
    wait(client, r.json())

    r = client.post("/api/books/我的书/steps/dedup/run")
    assert r.status_code == 202
    wait(client, r.json())


def test_dedup_requires_split_done(client, src):
    client.post("/api/books", json={"title": "我的书"})
    r = client.post("/api/books/我的书/import", json={"folder": str(src)})
    wait(client, r.json())

    r = client.post("/api/books/我的书/steps/dedup/run")
    assert r.status_code == 409


def test_busy_returns_409(client):
    client.post("/api/books", json={"title": "我的书"})
    gate = threading.Event()
    job = client.app.state.runner.submit("x", "我的书", lambda p: gate.wait(5) and {})
    assert client.post("/api/books/我的书/steps/split/run").status_code == 409
    assert client.get("/api/jobs/current").json()["id"] == job.id
    gate.set()
    client.app.state.runner.wait(job.id)


def test_startup_survives_corrupt_book_json(tmp_path):
    lib = tmp_path / "书库"
    lib.mkdir()
    (lib / "坏书").mkdir()
    (lib / "坏书" / "book.json").write_text("{", encoding="utf-8")
    c = TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",)))
    assert c.get("/api/health").json()["ok"] is True
    assert c.get("/api/books").json() == []


def test_interrupted_step_recovered_on_startup(tmp_path):
    c1 = TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",)))
    c1.post("/api/books", json={"title": "我的书"})
    from ligaotai.book import open_book

    open_book(tmp_path / "书库", "我的书").set_step("split", "running")
    c2 = TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",)))
    assert c2.get("/api/books/我的书").json()["steps"]["split"]["status"] == "failed"


def test_config_key_is_masked_and_kept(client, tmp_path):
    from ligaotai.config import load_config

    r = client.put("/api/config", json={"api_key": "sk-abcdefghijkl", "concurrency": 4})
    assert r.status_code == 200
    body = r.json()
    assert body["api_key"] == "sk-…ijkl" and body["has_key"] is True and body["concurrency"] == 4
    client.put("/api/config", json={"api_key": body["api_key"], "concurrency": 2})
    cfg = load_config(tmp_path)
    assert cfg.api_key == "sk-abcdefghijkl" and cfg.concurrency == 2
