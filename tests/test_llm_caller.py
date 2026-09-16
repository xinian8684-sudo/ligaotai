import pytest
from helpers import FakeBackend

from ligaotai.book import Book
from ligaotai.config import AppConfig
from ligaotai.llm import LLMClient
from ligaotai.llm_caller import Caller


@pytest.fixture
def fake_client(tmp_path):
    """跟 tests/test_threads_run.py 里 client() 一样的假模型接口，没实际用到的话不用管 handler。"""
    return LLMClient(AppConfig(), FakeBackend(), log_dir=tmp_path / "日志")


def test_caller_用传进来的缓存路径(tmp_path, fake_client):
    book = Book(tmp_path)
    book.root.mkdir(exist_ok=True)
    c = Caller(book, fake_client, lambda *a: None, cache_path=book.archive_cache_path, tag_prefix="archive")
    assert c.cache_path == book.root / "档案缓存.json"


def test_book_档案路径():
    from pathlib import Path

    b = Book(Path("/tmp/x"))
    assert b.archive_dir.name == "档案"
    assert b.thread_archive_dir == b.archive_dir / "支线"
    assert b.world_archive_dir == b.archive_dir / "世界"
    assert b.archive_index_path == b.archive_dir / "index.json"
    assert b.contradictions_path.name == "矛盾.json"
    assert b.map_path.name == "全书地图.md"
    assert b.archive_cache_path.name == "档案缓存.json"
