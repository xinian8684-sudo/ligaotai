"""前端静态托管：dist 在就发，不在也不能让后端起不来。"""

import pytest
from fastapi.testclient import TestClient

from ligaotai.api import create_app


@pytest.fixture
def 假dist(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text("<!doctype html><title>理稿台</title>", encoding="utf-8")
    assets = d / "assets"
    assets.mkdir()
    (assets / "main.js").write_text("console.log(1)", encoding="utf-8")
    return d


def test_没有dist时后端照常起得来(tmp_path):
    app = create_app(app_dir=tmp_path, allowed_hosts=("testserver",), web_dist=tmp_path / "不存在")
    c = TestClient(app)
    assert c.get("/api/health").json()["ok"] is True


def test_根路径发index(tmp_path, 假dist):
    c = TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",), web_dist=假dist))
    r = c.get("/")
    assert r.status_code == 200
    assert "理稿台" in r.text


def test_静态资源按原路径发(tmp_path, 假dist):
    c = TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",), web_dist=假dist))
    r = c.get("/assets/main.js")
    assert r.status_code == 200
    assert "console.log" in r.text


def test_前端路由刷新回index(tmp_path, 假dist):
    """SPA：/b/某书/panorama 直接刷新要拿到 index.html，不是 404。"""
    c = TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",), web_dist=假dist))
    r = c.get("/b/某书/panorama")
    assert r.status_code == 200
    assert "理稿台" in r.text


def test_不存在的api路径仍然404(tmp_path, 假dist):
    """兜底不能把 /api 下的 404 也吃掉，否则前端拿到一坨 HTML 当 JSON 解。"""
    c = TestClient(create_app(app_dir=tmp_path, allowed_hosts=("testserver",), web_dist=假dist))
    r = c.get("/api/没有这个接口")
    assert r.status_code == 404
    assert "text/html" not in r.headers.get("content-type", "")
