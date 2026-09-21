"""手改坏的文件不能让接口返回裸 500 —— 要把出错的文件名和原因告诉界面。

程序自己写的文件不会长这样，这几条只影响手改和外来文件。
"""

import json

import pytest
from fastapi.testclient import TestClient

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
