import pytest

from ligaotai.fsutil import read_json, write_json
from ligaotai.threads_ops import load_threads
from ligaotai.triage import BrokenBoardFile, delete_orphan, load_board, reconcile, set_card, thread_stats


def test_空看板_每条线默认还没想好(book_with_threads):
    th = load_threads(book_with_threads)
    cards = reconcile(load_board(book_with_threads), th)["cards"]
    assert {k: v["col"] for k, v in cards.items()} == {"L-001": "undecided", "L-002": "undecided"}
    assert not any(v["orphan"] or v["merge_invalid"] for v in cards.values())


def test_合并要选另一条存在且没砍的线(book_with_threads):
    b = book_with_threads
    th = load_threads(b)
    with pytest.raises(ValueError):
        set_card(b, th, "L-002", "merge", merge_into="L-002")
    with pytest.raises(ValueError):
        set_card(b, th, "L-002", "merge", merge_into="L-009")
    set_card(b, th, "L-001", "cut")
    with pytest.raises(ValueError):
        set_card(b, th, "L-002", "merge", merge_into="L-001")


def test_合并目标后来被砍_标合并目标失效(book_with_threads):
    b = book_with_threads
    th = load_threads(b)
    set_card(b, th, "L-002", "merge", merge_into="L-001")
    cards = set_card(b, th, "L-001", "cut")["cards"]
    assert cards["L-002"]["merge_invalid"] is True
    assert read_json(b.board_path)["cards"]["L-002"] == {"col": "merge", "merge_into": "L-001", "note": ""}


def test_列不认识或线不存在(book_with_threads):
    b = book_with_threads
    th = load_threads(b)
    with pytest.raises(ValueError):
        set_card(b, th, "L-001", "maybe")
    with pytest.raises(KeyError):
        set_card(b, th, "L-009", "keep")


def test_非合并列不留合并目标_备注保留(book_with_threads):
    b = book_with_threads
    th = load_threads(b)
    set_card(b, th, "L-002", "merge", merge_into="L-001", note="并进取经")
    cards = set_card(b, th, "L-002", "keep")["cards"]
    assert cards["L-002"]["merge_into"] is None
    assert cards["L-002"]["note"] == "并进取经"


def test_不能并入一条也在合并列的线(book_with_threads):
    b = book_with_threads
    th = load_threads(b)
    set_card(b, th, "L-001", "merge", merge_into="L-002")
    with pytest.raises(ValueError):
        set_card(b, load_threads(b), "L-002", "merge", merge_into="L-001")


def test_不能把已经被并入的线再设为合并(book_with_threads):
    b = book_with_threads
    data = read_json(b.threads_path)
    data["threads"].append({"id": "L-003", "world": "W-01", "name": "三", "about": "", "status": "draft",
                            "scenes": [], "times": {}, "outlines": [], "offset": 0,
                            "end": {"state": "待定", "note": "", "last": None}, "order_failed": False})
    write_json(b.threads_path, data)
    th = load_threads(b)
    set_card(b, th, "L-001", "merge", merge_into="L-002")
    # L-002 已经是 L-001 的合并目标（L-002 本身列是「还没想好」，不是 merge，所以不会被前一条
    # 「目标也在合并列」的检查挡住）；再把 L-002 设成合并会串成 L-001→L-002→L-003 的链，也要拒绝
    with pytest.raises(ValueError):
        set_card(b, load_threads(b), "L-002", "merge", merge_into="L-003")


def test_对账时自并入标失效(book_with_threads):
    b = book_with_threads
    write_json(b.board_path, {"cards": {"L-002": {"col": "merge", "merge_into": "L-002", "note": ""}}})
    th = load_threads(b)
    cards = reconcile(load_board(b), th)["cards"]
    assert cards["L-002"]["merge_invalid"] is True


def test_线消失_卡保留标孤儿_可以删(book_with_threads):
    b = book_with_threads
    write_json(b.board_path, {"cards": {"L-009": {"col": "cut", "merge_into": None, "note": ""}}})
    th = load_threads(b)
    cards = reconcile(load_board(b), th)["cards"]
    assert cards["L-009"]["orphan"] is True and cards["L-009"]["col"] == "cut"
    delete_orphan(b, th, "L-009")
    assert "L-009" not in read_json(b.board_path)["cards"]
    with pytest.raises(ValueError):
        delete_orphan(b, th, "L-001")  # 活着的线不许删


def test_看板文件坏了不当空(book_with_threads):
    book_with_threads.triage_dir.mkdir(parents=True, exist_ok=True)
    book_with_threads.board_path.write_text("{坏", encoding="utf-8")
    with pytest.raises(BrokenBoardFile):
        load_board(book_with_threads)
    write_json(book_with_threads.board_path, {"cards": []})
    with pytest.raises(BrokenBoardFile):
        load_board(book_with_threads)


def test_每条线统计_字数只算主版本(book_with_threads):
    b = book_with_threads
    # 每块正文都是「S-000x 的正文。」共 11 个字；S-0002 是 S-0001 的非主版本
    write_json(b.versions_path, {"params": {}, "groups": [
        {"id": "G-001", "members": ["S-0001", "S-0002"], "main": "S-0001", "main_by": "auto", "pairs": []}]})
    st = thread_stats(b, load_threads(b))
    assert st["L-001"] == {"name": "取经", "world": "W-01", "words": 22, "scenes": 3, "state": "待定",
                           "gaps": 1, "is_main": True, "order_failed": False}
    assert st["L-002"]["words"] == 22 and st["L-002"]["state"] == "完结" and st["L-002"]["gaps"] == 0
