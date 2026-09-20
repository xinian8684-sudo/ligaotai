"""步骤 7（档案 + 矛盾 + 地图）接进 API：读档案列表、读矛盾、读单份档案正文、单独重跑。

复用 test_archive_run.py 里已经验证过能跑通 run_archive 的假模型和种子数据，好让
client_with_book_run 拿到一本真的跑完步骤 7 的书，不用重新造一遍 archive_handler。
"""

import threading

import pytest
from fastapi.testclient import TestClient
from helpers import FakeBackend, seed_book
from test_archive_run import ENTS, FACTS, HOOKS, PERSONS, SCENES, archive_handler, set_card, threads_data

from ligaotai.api import create_app
from ligaotai.book import open_book
from ligaotai.config import library_path, load_config
from ligaotai.fsutil import write_json

BOOK = "/api/books/测试书"
UPSTREAM_STEPS = ("import", "split", "dedup", "cards", "entities", "threads")


def make_client(tmp_path, **kw):
    record: list = []
    backend = FakeBackend(handler=archive_handler(record, **kw))
    app = create_app(app_dir=tmp_path, allowed_hosts=("testserver",), backend_factory=lambda cfg: backend)
    c = TestClient(app)
    c.calls = record
    return c


def wait(client, response):
    assert response.status_code == 202, response.text
    job = client.app.state.runner.wait(response.json()["id"]).to_dict()
    assert job["status"] == "done", job["error"]
    return job


def _open(tmp_path):
    return open_book(library_path(load_config(tmp_path), tmp_path), "测试书")


def _seed(book):
    """跟 test_archive_run.py 的 book_with_threads 一样的种子数据：两条线 L-001/L-002，
    一个世界 W-01，够 run_archive 真的跑出档案 + 矛盾 + 地图。"""
    texts = {"S-0008": "花果山在东胜神洲，是十洲之祖脉。"}
    seed_book(
        book,
        [
            {
                **s,
                "text": texts.get(s["id"], f"{s['id']} 的正文。"),
                "persons": PERSONS.get(s["id"], []),
                "kind": "设定笔记" if s["id"] == "S-0008" else "正文",
            }
            for s in SCENES
        ],
        entities=ENTS,
    )
    for sid in [s["id"] for s in SCENES]:
        set_card(book, sid, facts=FACTS.get(sid, []), hooks_planted=HOOKS.get(sid, []), hooks_resolved=[])
    write_json(book.threads_path, threads_data())


@pytest.fixture
def client_with_book(tmp_path):
    c = make_client(tmp_path)
    c.post("/api/books", json={"title": "测试书"})
    return c


@pytest.fixture
def client_with_book_run(tmp_path):
    c = make_client(tmp_path)
    c.post("/api/books", json={"title": "测试书"})
    b = _open(tmp_path)
    _seed(b)
    for s in UPSTREAM_STEPS:
        b.set_step(s, "done")
    wait(c, c.post(f"{BOOK}/steps/archive/run"))
    return c


def test_archive在可跑的步骤里(client_with_book):
    from ligaotai.api import RUNNABLE

    assert "archive" in RUNNABLE


def test_读档案列表(client_with_book):
    r = client_with_book.get(f"{BOOK}/archive")
    assert r.status_code == 200
    assert set(r.json()) >= {"threads", "worlds", "map"}


def test_读档案列表带当前配置的模型名(client_with_book_run):
    """I2（9-20 作者拍板）：接口要同时给每份档案生成时用的模型名、和当前配置的模型名，
    界面才能对比、提示作者要不要重跑。"""
    r = client_with_book_run.get(f"{BOOK}/archive")
    assert r.status_code == 200
    body = r.json()
    assert body["current_model"]  # 当前配置的模型名，非空
    assert body["threads"]["L-001"]["model"] == body["current_model"]
    assert body["worlds"]["W-01"]["model"] == body["current_model"]
    assert body["map"]["model"] == body["current_model"]


def test_读矛盾(client_with_book):
    r = client_with_book.get(f"{BOOK}/contradictions")
    assert r.status_code == 200
    assert "groups" in r.json()


def test_读一份档案的正文(client_with_book_run):
    r = client_with_book_run.get(f"{BOOK}/archive/thread/L-001")
    assert r.status_code == 200
    assert "来龙去脉" in r.json()["body"]


def test_读世界档案的正文(client_with_book_run):
    r = client_with_book_run.get(f"{BOOK}/archive/world/W-01")
    assert r.status_code == 200
    assert r.json()["id"] == "W-01"


def test_读不存在的档案给404(client_with_book):
    assert client_with_book.get(f"{BOOK}/archive/thread/L-999").status_code == 404


def test_kind不对给400(client_with_book):
    assert client_with_book.get(f"{BOOK}/archive/xxx/L-001").status_code == 400


def test_单独重跑接口(client_with_book_run):
    r = client_with_book_run.post(f"{BOOK}/archive/rerun", json={"threads": ["L-001"], "worlds": [], "map": True})
    assert r.status_code == 200
    idx = client_with_book_run.get(f"{BOOK}/archive").json()
    assert idx["threads"]["L-001"]["outdated"] is True
    assert idx["map"]["outdated"] is True
    assert idx["threads"]["L-002"]["outdated"] is False  # 没点它，没被连带标过期


def test_重跑不存在的线给400(client_with_book_run):
    r = client_with_book_run.post(f"{BOOK}/archive/rerun", json={"threads": ["L-999"], "worlds": [], "map": False})
    assert r.status_code == 400


def test_有任务在跑时重跑接口给409(client_with_book_run):
    """I2（9-20 GHIJ 审查）：archive_rerun 对 档案/index.json 做读-改-写，跟正在跑的
    步骤 7（_Run._save_index() 每落一份档案就整份覆盖写）互相没锁。有任务在跑时点
    重跑，标记可能被下一次 _save_index() 静默盖掉，作者以为标了、其实没标。最小修法：
    有任务在跑就 409，不做读-改-写——这里直接验证 index.json 真的没被改。"""
    c = client_with_book_run
    before = c.get(f"{BOOK}/archive").json()
    gate = threading.Event()
    job = c.app.state.runner.submit("x", "测试书", lambda p: gate.wait(5) and {})
    try:
        r = c.post(f"{BOOK}/archive/rerun", json={"threads": ["L-001"], "worlds": [], "map": True})
        assert r.status_code == 409
    finally:
        gate.set()
        c.app.state.runner.wait(job.id)
    after = c.get(f"{BOOK}/archive").json()
    assert after["threads"]["L-001"]["outdated"] == before["threads"]["L-001"]["outdated"] is False
    assert after["map"]["outdated"] == before["map"]["outdated"] is False


def test_重跑标过期后再跑步骤7只重跑那一份(client_with_book_run):
    """确认 Task 16/17 的 _fresh() 判断确实认 index[...]["outdated"]（任务书里说这条已经做好，
    这里当回归测试钉住，免得以后改坏）。

    注意：这里不能拿「有没有真的打到假后端」当判据——archive_thread 的渲染输入（system+user）
    没变，Caller 自己那层按内容算的缓存（archive_cache.json）会在 chat_json 之前先命中，
    根本走不到假后端，record 不会新增。能观察到的是 archive.py 里「reused（走 _fresh 快路径）」
    和「generated（走了 caller.call，哪怕命中的是它自己的缓存）」的区分：被标过期的 L-001
    要落在 generated 里、不能停留在 reused 里；没被点的 L-002 反过来。"""
    c = client_with_book_run
    c.post(f"{BOOK}/archive/rerun", json={"threads": ["L-001"], "worlds": [], "map": False})
    job = wait(c, c.post(f"{BOOK}/steps/archive/run"))
    result = job["result"]
    assert "L-001" in result["generated"]["threads"]
    assert "L-001" not in result["reused"]["threads"]
    assert "L-002" in result["reused"]["threads"]
    assert "L-002" not in result["generated"]["threads"]


def test_跑archive时抛异常步骤状态记成failed不停在跑着(tmp_path):
    """Task 16/17 审查提过的风险点（I1）：run_archive 抛异常时，步骤状态要落地成 failed，
    不能停在上一轮的 done / running。这里不需要专门补代码——api.submit() 的通用异常处理
    （见 create_app.submit.work）已经覆盖：任何步骤的 fn 抛 BaseException 都会被捕到、
    book.set_step(step, "failed", ...) 记下来再重新抛出。用「上游步骤都标了 done，但
    世界与支线.json 其实不存在」制造 run_archive 一开始就失败的场景来钉住这条。"""
    c = make_client(tmp_path)
    c.post("/api/books", json={"title": "测试书"})
    b = _open(tmp_path)
    for s in UPSTREAM_STEPS:
        b.set_step(s, "done")  # 骗过 require_upstream，但没真的写 世界与支线.json
    r = c.post(f"{BOOK}/steps/archive/run")
    job = c.app.state.runner.wait(r.json()["id"])
    assert job.status == "failed"
    st = c.get(BOOK).json()["steps"]["archive"]
    assert st["status"] == "failed"
    assert "ValueError" in st["summary"]["error"]
