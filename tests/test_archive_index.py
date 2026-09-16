from ligaotai.archive import load_index, map_sig, reconcile, thread_sig, world_sig, write_index


def test_线的签名跟着成员和顺序变():
    t = {"id": "L-001", "name": "取经", "scenes": ["S-0001", "S-0002"],
         "end": {"state": "待定", "note": "", "last": "S-0002"}}
    hashes = {"S-0001": "a", "S-0002": "b"}
    gaps = []
    base = thread_sig(t, hashes, gaps)
    assert thread_sig(t, hashes, gaps) == base, "同样的输入要稳定"
    assert thread_sig({**t, "scenes": ["S-0002", "S-0001"]}, hashes, gaps) != base, "顺序变了要变"
    assert thread_sig(t, {"S-0001": "a", "S-0002": "c"}, gaps) != base, "块内容变了要变"
    assert thread_sig(t, hashes, [{"event": "青州城破"}]) != base, "缺口变了要变"


def test_世界的签名跟着成员和规范名映射变():
    w = {"id": "W-01", "name": "人间"}
    base = world_sig(w, ["S-0001"], {"S-0001": "a"}, "cmap-v1")
    assert world_sig(w, ["S-0001"], {"S-0001": "a"}, "cmap-v2") != base


def test_地图签名是全部档案内容的哈希(tmp_path):
    f1, f2 = tmp_path / "a.md", tmp_path / "b.md"
    f1.write_text("甲", encoding="utf-8")
    f2.write_text("乙", encoding="utf-8")
    base = map_sig([f1, f2])
    f2.write_text("丙", encoding="utf-8")
    assert map_sig([f1, f2]) != base


def test_对账把找不到对应线的档案标过期():
    index = {"threads": {"L-001": {"outdated": False}, "L-009": {"outdated": False}},
             "worlds": {"W-01": {"outdated": False}}, "map": {"outdated": False}}
    stale = reconcile(index, thread_ids={"L-001"}, world_ids={"W-01"})
    assert stale == ["L-009"]
    assert index["threads"]["L-009"]["outdated"] is True
    assert index["threads"]["L-001"]["outdated"] is False


def test_index读写往返(tmp_path):
    from ligaotai.book import Book

    book = Book(tmp_path)
    book.root.mkdir(exist_ok=True)
    data = {"threads": {}, "worlds": {}, "map": {}}
    write_index(book, data)
    assert load_index(book) == data


def test_index不存在时给空壳(tmp_path):
    from ligaotai.book import Book

    book = Book(tmp_path)
    book.root.mkdir(exist_ok=True)
    assert load_index(book) == {"threads": {}, "worlds": {}, "map": {}}
