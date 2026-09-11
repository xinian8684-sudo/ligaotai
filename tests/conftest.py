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


STORY = {
    "1.txt": "第一章 雪夜\n林清年方十六，住在青州城外。\n\n第二章 离城\n清儿背着包袱出了门，赵五在后面跟着。",
    "2.txt": "第三章 天机\n林姑娘进了天机阁，赵五守在门口。",
}


@pytest.fixture
def story_book(book, tmp_path):
    """三个场景的小书：S-0001 林清，S-0002 清儿/赵五，S-0003 林姑娘/赵五/天机阁。"""
    from ligaotai.importer import run_import
    from ligaotai.scenes import run_split

    src = tmp_path / "稿"
    src.mkdir()
    for name, text in STORY.items():
        (src / name).write_text(text, encoding="utf-8")
    run_import(book, src)
    run_split(book)
    book.story_src = src
    return book
