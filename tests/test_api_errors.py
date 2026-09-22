"""手改坏的文件不能让接口返回裸 500 —— 要把出错的文件名和原因告诉界面。

程序自己写的文件不会长这样，这几条只影响手改和外来文件。
"""

import json

import pytest
from fastapi.testclient import TestClient
from helpers import seed_book

from ligaotai.api import create_app
from ligaotai.book import create_book


@pytest.fixture
def 客户端和书(tmp_path):
    lib = tmp_path / "书库"
    lib.mkdir()
    (tmp_path / "config.json").write_text(json.dumps({"library_dir": str(lib)}), encoding="utf-8")
    b = create_book(lib, "测试书")
    app = create_app(
        app_dir=tmp_path, allowed_hosts=("testserver",), web_dist=tmp_path / "不存在"
    )
    return TestClient(app), b


def test_场景文件坏了要报出是哪个文件(客户端和书):
    c, b = 客户端和书
    # 场景文件是 .md（yaml frontmatter + 正文），不是 .json——任务书模板写的是
    # "S-0012.json"，跟 scenes.py 的真实落盘格式（scene_path -> f"{sid}.md"）对不上，
    # 按实际格式改成 .md，内容随便什么读不出合法 frontmatter 的东西都行。
    b.scenes_dir.mkdir(parents=True, exist_ok=True)
    (b.scenes_dir / "S-0012.md").write_text("这不是合法的场景文件头", encoding="utf-8")

    r = c.get("/api/books/测试书/scenes")
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "S-0012" in detail, f"出错的文件名没告诉界面：{detail}"


def test_场景目录正常时照常返回(客户端和书):
    c, _ = 客户端和书
    r = c.get("/api/books/测试书/scenes")
    assert r.status_code == 200
    assert r.json() == []


# --- Task 7：卡片列表与实体接口的坏文件处理 ---


def test_卡文件被改坏时报出是哪张卡(客户端和书):
    c, b = 客户端和书
    # 先造一个正常的场景，卡片接口才会去读卡：用 tests/helpers.py 里 seed_book 这个现成的
    # helper（不走真的导入/切场景，直接按 scenes.py 的真实落盘格式写场景文件），no_card=True
    # 让它不写卡，卡文件由下面手动造一份「结构被改坏」的。
    seed_book(b, [{"id": "S-0001", "no_card": True}])

    b.cards_dir.mkdir(parents=True, exist_ok=True)
    # 任务书模板里原样写的是 {"card": "本该是个对象"}，没有 "id" 字段——但
    # cards.load_cards() 要求 data.get("id") == 文件名（p.stem）才会收进结果，
    # 缺了 "id" 这张卡会被 load_cards 直接当成「没有这张卡」跳过，根本走不到
    # 卡片接口里 card.get(...) 那一步，测不出裸 500。补上 "id": "S-0001" 让它
    # 先能被 load_cards 收进来，再在 card.get("kind") 那一步因为 card 是字符串炸开。
    (b.cards_dir / "S-0001.json").write_text(
        json.dumps({"id": "S-0001", "card": "本该是个对象"}), encoding="utf-8"
    )

    r = c.get("/api/books/测试书/cards")
    assert r.status_code == 500
    assert "S-0001" in r.json()["detail"]


def test_实体文件不是合法JSON时给得出人话(客户端和书):
    c, b = 客户端和书
    b.entities_path.parent.mkdir(parents=True, exist_ok=True)
    b.entities_path.write_text("{坏掉的", encoding="utf-8")

    r = c.get("/api/books/测试书/entities")
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "实体" in detail
    assert "JSONDecodeError" not in detail, "别把 Python 异常类名甩给界面"


def test_实体条目缺字段不能报成404(客户端和书):
    c, b = 客户端和书
    b.entities_path.parent.mkdir(parents=True, exist_ok=True)
    b.entities_path.write_text(
        json.dumps({"next_id": 2, "entities": [{"id": "E-0001"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    r = c.put("/api/books/测试书/entities/E-0001", json={"canonical": "张三"})
    assert r.status_code != 404, "缺字段是文件坏了，不是『没有这个实体』"
    assert r.status_code == 500
    assert "E-0001" in r.json()["detail"]


# --- Task 8：safe_name 的边界输入不能裸 500 ---


@pytest.mark.parametrize(
    "坏名字,url段",
    [
        # 任务书模板直接把 ".." 拼进 URL 路径——但 URL 路径里裸的 ".." 是个
        # dot-segment，httpx/RFC 3986 在发请求前就会把它连同前一段（"thread"）
        # 一起折叠掉（"…/archive/thread/.." -> "…/archive"），请求根本走不到
        # archive_body 这个路由，测的是另一个接口（archive_index，200）。
        # 把两个点分别 percent-encode 成 %2e，绕开客户端自己的路径折叠，
        # 让服务端收到的 oid 真的是 ".."。
        ("..", "%2e%2e"),
        (".", "."),
        ("   ", "   "),
    ],
)
def test_档案接口遇到边界名字返回404(客户端和书, 坏名字, url段):
    c, _ = 客户端和书
    r = c.get(f"/api/books/测试书/archive/thread/{url段}")
    assert r.status_code == 404, f"{坏名字!r} 应该是 404 不是 {r.status_code}"


@pytest.mark.parametrize("坏名字", ["..", ".", "   "])
def test_建书遇到边界名字返回400(坏名字, tmp_path):
    lib = tmp_path / "书库"
    lib.mkdir()
    (tmp_path / "config.json").write_text(json.dumps({"library_dir": str(lib)}), encoding="utf-8")
    c = TestClient(
        create_app(app_dir=tmp_path, allowed_hosts=("testserver",), web_dist=tmp_path / "不存在")
    )
    r = c.post("/api/books", json={"title": 坏名字})
    assert r.status_code == 400


# --- F1（审查 S4 / S5）---


def test_单个场景文件坏了报500带文件名_不能说没有这个场景(客户端和书):
    c, b = 客户端和书
    b.scenes_dir.mkdir(parents=True, exist_ok=True)
    (b.scenes_dir / "S-0012.md").write_text("这不是合法的场景文件头", encoding="utf-8")

    r = c.get("/api/books/测试书/scenes/S-0012")
    assert r.status_code == 500, f"坏文件被吃成了 {r.status_code}：{r.text}"
    assert "S-0012" in r.json()["detail"]

    r = c.post("/api/books/测试书/cards/S-0012/regenerate")
    assert r.status_code == 500
    assert "S-0012" in r.json()["detail"]


def test_真没有的场景照常404(客户端和书):
    c, _ = 客户端和书
    assert c.get("/api/books/测试书/scenes/S-0099").status_code == 404


@pytest.mark.parametrize(
    "卡",
    [
        {"id": "S-0001", "card": {}, "problems": 5},
        {"id": "S-0001", "card": {}, "dropped": {"facts": 5}},
    ],
)
def test_卡文件字段类型被改坏时也报出是哪张卡(客户端和书, 卡):
    c, b = 客户端和书
    seed_book(b, [{"id": "S-0001", "no_card": True}])
    b.cards_dir.mkdir(parents=True, exist_ok=True)
    (b.cards_dir / "S-0001.json").write_text(json.dumps(卡), encoding="utf-8")

    r = c.get("/api/books/测试书/cards")
    assert r.status_code == 500
    assert "S-0001" in r.json()["detail"]


@pytest.mark.parametrize(
    "内容,原因里要有",
    [
        ([], "顶层"),
        ({"entities": 3}, '"entities" 应该是列表'),
        ([None], "顶层"),
        ({"entities": [None]}, "第 1 条"),
        ({"next_id": 1}, '"entities"'),
    ],
)
def test_实体文件顶层形状不对时给具体原因(客户端和书, 内容, 原因里要有):
    c, b = 客户端和书
    b.entities_path.parent.mkdir(parents=True, exist_ok=True)
    b.entities_path.write_text(json.dumps(内容), encoding="utf-8")

    for r in (
        c.get("/api/books/测试书/entities"),
        c.post("/api/books/测试书/entities/confirm", json={"ids": ["E-0001"]}),
    ):
        assert r.status_code == 500, f"{内容!r} -> {r.status_code} {r.text}"
        detail = r.json()["detail"]
        assert "实体.json" in detail
        assert 原因里要有 in detail, detail


def test_还没有实体文件时GET照常给空列表(客户端和书):
    c, _ = 客户端和书
    r = c.get("/api/books/测试书/entities")
    assert r.status_code == 200
    assert r.json() == {"entities": []}

