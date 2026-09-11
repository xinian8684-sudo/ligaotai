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
