from ligaotai.export import export_book
from ligaotai.fsutil import write_json
from tools.eval_skeleton import check_book


def _sk(items, unplaced=None):
    return {"generated": "x", "by": "program", "volumes": [{"title": "卷", "chapters": [
        {"title": "章", "items": items, "notes": []}]}], "unplaced": unplaced or {"scenes": [], "holes": []}}


def test_全留_每块恰好一次_空洞数对得上_编号不编造(book_with_threads):
    b = book_with_threads
    items = [{"type": "scene", "id": "S-0001", "thread": "L-001"},
             {"type": "hole", "id": "H-001", "gap": "Q-001", "task": "补 [S-0002]"},
             *[{"type": "scene", "id": f"S-000{i}", "thread": "L-001" if i < 4 else "L-002"} for i in range(2, 6)]]
    write_json(b.skeleton_path, _sk(items))
    export_book(b)
    r = check_book(b, truth=None, cut=[])
    assert r["each_once"] is True and r["duplicates"] == [] and r["missing"] == []
    assert r["holes_expected"] == 1 and r["holes_in_skeleton"] == 1
    assert r["fabricated_refs"] == []


def test_重复和漏掉_编造编号都要报出来(book_with_threads):
    """计划草稿里这条测试原本是往骨架里塞两个一模一样的 id（S-0001 两次）来触发「重复」——
    这跟真实代码矛盾：`skeleton.load_skeleton`（`export_book` 导出前第一步就调它）的结构检查
    本身就不允许同一个原始编号在骨架里出现两次（不看 known 也拦），塞进去 `export_book(b)`
    这一步就会直接抛 `BrokenSkeletonFile`，走不到 check_book。真实世界里「重复」只可能来自
    版本组：两个不同的原始编号（一个非主成员、一个是组里当前主版本）各自都合法、互不相同，
    但导出时都会按主版本换算成同一个编号——这里改用这种方式触发重复，missing / fabricated_refs
    测的内容不变。"""
    b = book_with_threads
    write_json(b.versions_path, {"groups": [{"id": "V-001", "members": ["S-0002", "S-0006"],
                                             "main": "S-0006", "main_by": "author"}]})
    items = [{"type": "scene", "id": "S-0002", "thread": "L-001"},
             {"type": "scene", "id": "S-0006", "thread": "L-001"},
             {"type": "hole", "id": "H-001", "gap": "Q-001", "task": "补 [S-0999]"}]
    write_json(b.skeleton_path, _sk(items))
    export_book(b)
    r = check_book(b, truth=None, cut=[])
    assert r["each_once"] is False
    assert r["duplicates"] == ["S-0006"]
    assert r["missing"] == ["S-0001", "S-0003", "S-0004", "S-0005"]
    assert r["fabricated_refs"] == ["S-0999"]


def test_砍掉的线不许出现(book_with_threads):
    b = book_with_threads
    items = [{"type": "scene", "id": f"S-000{i}", "thread": "L-001"} for i in range(1, 4)] + \
            [{"type": "scene", "id": "S-0004", "thread": "L-002"}]
    write_json(b.skeleton_path, _sk(items))
    write_json(b.board_path, {"cards": {"L-002": {"col": "cut", "merge_into": None, "note": ""}}})
    export_book(b)
    r = check_book(b, truth=None, cut=["L-002"])
    assert r["cut_leaks"] == ["S-0004"]


def test_换主版本后_缺主版本场景要报missing_不能因为drop了非主就放过(book_with_threads):
    """真实契约（skeleton._generate / skeleton.annotate）：非主版本如果在 version_map 里能查到
    当前主版本，就换算成主版本，不是直接丢弃——直接丢弃只丢非主成员会让「应该出现的编号」漏掉
    它换算后的主版本，真漏收了也测不出来。这里造一个「骨架里 S-0002 整个不见了、组的当前主版本
    S-0006 也从没进过骨架」的场景：按真实契约，S-0006 是这个时间位应该出现的编号，必须报
    missing；如果重算时只拿 non_main_versions(book) 当 drop、不把 version_map 传给
    build_sequence，S-0002 会被直接跳过、S-0006 也从来没被要求出现过，missing 就会假绿。"""
    b = book_with_threads
    write_json(b.versions_path, {"groups": [{"id": "V-001", "members": ["S-0002", "S-0006"],
                                             "main": "S-0006", "main_by": "author"}]})
    items = [{"type": "scene", "id": "S-0001", "thread": "L-001"},
             {"type": "scene", "id": "S-0003", "thread": "L-001"},
             {"type": "scene", "id": "S-0004", "thread": "L-002"},
             {"type": "scene", "id": "S-0005", "thread": "L-002"}]
    write_json(b.skeleton_path, _sk(items))
    export_book(b)
    r = check_book(b, truth=None, cut=[])
    assert r["missing"] == ["S-0006"]


def test_未定位里的空洞说明也要查编造(book_with_threads):
    """没锚点、落进 unplaced.holes 的空洞照样有 task 说明文字，同样可能编号编造——
    只扫卷章正文里排上位置的空洞会漏掉这半边。"""
    b = book_with_threads
    items = [{"type": "scene", "id": "S-0001", "thread": "L-001"}]
    unplaced = {"scenes": [], "holes": [{"id": "H-001", "task": "补 [S-0999]"}]}
    write_json(b.skeleton_path, _sk(items, unplaced))
    export_book(b)
    r = check_book(b, truth=None, cut=[])
    assert r["fabricated_refs"] == ["S-0999"]
