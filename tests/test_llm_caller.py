import asyncio
import json

import pytest
from helpers import FakeBackend, threads_handler

from ligaotai.book import Book
from ligaotai.config import AppConfig
from ligaotai.llm import LLMClient
from ligaotai.llm_caller import Caller


@pytest.fixture
def fake_client(tmp_path):
    """跟 tests/test_threads_run.py 里 client() 一样的假模型接口，没实际用到的话不用管 handler。"""
    return LLMClient(AppConfig(), FakeBackend(), log_dir=tmp_path / "日志")


def client(book, **handlers):
    """跟 tests/test_threads.py 里的 client() 一样，造一个会回真实回复的假模型接口。"""
    return LLMClient(AppConfig(), FakeBackend(handler=threads_handler(**handlers)), log_dir=book.logs_dir)


GAPS_ARGS = {"world": "w", "threads": "t", "refs": "r"}


def test_caller_用传进来的缓存路径(tmp_path, fake_client):
    book = Book(tmp_path)
    book.root.mkdir(exist_ok=True)
    c = Caller(book, fake_client, lambda *a: None, cache_path=book.archive_cache_path, tag_prefix="archive")
    assert c.cache_path == book.root / "档案缓存.json"


def test_caller_缓存路径必填(tmp_path, fake_client):
    """不传 cache_path 不该再悄悄落回归线自己的缓存文件——必须显式指定。"""
    book = Book(tmp_path)
    book.root.mkdir(exist_ok=True)
    with pytest.raises(TypeError):
        Caller(book, fake_client, lambda *a: None)


def test_两个caller各用自己的缓存路径_清一个不影响另一个(book):
    """归线 Caller 和档案 Caller 分开传缓存路径，清掉一个的缓存，另一个的文件内容不变。"""
    caller_t = Caller(book, client(book), lambda *a: None, cache_path=book.threads_cache_path, tag_prefix="threads")
    caller_a = Caller(book, client(book), lambda *a: None, cache_path=book.archive_cache_path, tag_prefix="archive")

    async def go():
        caller_t.plan(1)
        caller_a.plan(1)
        await caller_t.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-t")
        await caller_a.call("threads_gaps", GAPS_ARGS, lambda d: [], "gaps-a")

    asyncio.run(go())

    assert book.threads_cache_path.exists()
    assert book.archive_cache_path.exists()
    archive_before = book.archive_cache_path.read_text(encoding="utf-8")

    # 对着归线缓存路径新开一个 Caller（模拟下一次运行），这次没用到任何 key，prune 会把它清空
    fresh = Caller(book, client(book), lambda *a: None, cache_path=book.threads_cache_path, tag_prefix="threads")
    fresh.prune_cache()

    assert json.loads(book.threads_cache_path.read_text(encoding="utf-8")) == {}
    assert book.archive_cache_path.read_text(encoding="utf-8") == archive_before


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
