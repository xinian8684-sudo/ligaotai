import pytest

from ligaotai.book import create_book


@pytest.fixture
def library(tmp_path):
    lib = tmp_path / "书库"
    lib.mkdir()
    return lib


@pytest.fixture
def book(library):
    return create_book(library, "测试书")


@pytest.fixture(autouse=True)
def _no_real_key(monkeypatch):
    """测试一律用不到真的 API key。"""
    monkeypatch.delenv("LIGAOTAI_API_KEY", raising=False)
