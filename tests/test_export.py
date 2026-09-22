import pytest

from ligaotai.export import export_book, export_path
from ligaotai.fsutil import write_json

SK = {"generated": "x", "by": "author", "volumes": [{"title": "第一卷 起", "chapters": [
    {"title": "开篇", "notes": [], "items": [
        {"type": "scene", "id": "S-0001", "thread": "L-001"},
        {"type": "hole", "id": "H-001", "task": "在 S-0001 与 S-0003 之间补写：\n大闹天宫"},
        {"type": "scene", "id": "S-0099", "thread": "L-001"}]}]}],
    "unplaced": {"scenes": [{"id": "S-0005", "thread": "L-002", "why": "no_time"}], "holes": []}}

MD = """# 第一卷 起

## 开篇

<!-- S-0001 -->
S-0001 的正文。

> 【空洞 H-001】在 S-0001 与 S-0003 之间补写： 大闹天宫

> 【缺失场景 S-0099：原稿里已经没有这一块了】

# 附：未定位

<!-- S-0005 -->
S-0005 的正文。
"""

TXT = """第一卷 起

开篇

S-0001 的正文。

【空洞 H-001】在 S-0001 与 S-0003 之间补写： 大闹天宫

【缺失场景 S-0099：原稿里已经没有这一块了】

附：未定位

S-0005 的正文。
"""


def test_导出md和txt(book_with_threads):
    b = book_with_threads
    write_json(b.skeleton_path, SK)
    r = export_book(b)
    assert r == {"md": "导出/测试书.md", "txt": "导出/测试书.txt", "scenes": 2, "holes": 1, "missing": 1}
    assert export_path(b, "md").read_text(encoding="utf-8") == MD
    assert export_path(b, "txt").read_text(encoding="utf-8") == TXT


def test_没有骨架不能导出(book_with_threads):
    with pytest.raises(FileNotFoundError):
        export_book(book_with_threads)


def test_格式只认md和txt(book_with_threads):
    with pytest.raises(ValueError):
        export_path(book_with_threads, "docx")
