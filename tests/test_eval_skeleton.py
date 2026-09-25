import json

from helpers import FakeBackend

from ligaotai.config import AppConfig
from ligaotai.export import export_book
from ligaotai.fsutil import read_json, write_json
from ligaotai.llm import LLMClient
from ligaotai.skeleton import generate
from tools.eval_skeleton import check_book, main


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


def _chapters_handler(tier, messages):
    system = messages[0]["content"]
    if "分卷分章" in system:
        return json.dumps({"volumes": [{"title": "卷一", "start": 0}],
                           "chapters": [{"title": "全", "start": 0}]}, ensure_ascii=False)
    return json.dumps({"holes": []})


def test_M5_生成器悄悄丢一条线的场景_判据1要红(book_with_threads, monkeypatch):
    """M5：判据 1、3 原来拿 skeleton_order.build_sequence/insert_holes 自己算期望值再拿它
    验自己——生成器真的悄悄丢了一条线的场景，期望值会跟着一起丢，两边一起错，判据照样绿。
    这里 monkeypatch 生成器（ligaotai.skeleton 模块里 import 进来的 build_sequence 名字），
    让它在真实生成时悄悄把 L-002 的场景过滤掉，验证改用独立重算之后判据 1 真的会报出来。"""
    import ligaotai.skeleton as skl_mod
    from ligaotai.skeleton_order import build_sequence as real_build_sequence

    def buggy(threads, cols, drop, vmap=None):
        seq, unplaced = real_build_sequence(threads, cols, drop, vmap)
        seq = [it for it in seq if it["thread"] != "L-002"]  # 悄悄丢掉 L-002 的场景
        return seq, unplaced

    monkeypatch.setattr(skl_mod, "build_sequence", buggy)

    b = book_with_threads
    client = LLMClient(AppConfig(), FakeBackend(handler=_chapters_handler), log_dir=b.logs_dir)
    r = generate(b, client)
    assert r["written"] is True
    export_book(b)
    result = check_book(b, truth=None, cut=[])
    assert result["each_once"] is False
    assert "S-0004" in result["missing"] and "S-0005" in result["missing"]


def test_M6_只属于砍线的缺口泄漏进骨架(book_with_threads):
    """M6：判据 4 原来只查场景层面的砍线泄漏，没查空洞——手改骨架（或者线砍了骨架没
    重新生成）时，只属于被砍线的缺口还留在骨架里、照样导出，测不出来。"""
    b = book_with_threads
    items = [{"type": "scene", "id": f"S-000{i}", "thread": "L-001"} for i in range(1, 4)] + \
            [{"type": "hole", "id": "H-001", "gap": "Q-001", "task": "补 [S-0001]"}]
    write_json(b.skeleton_path, _sk(items))
    write_json(b.board_path, {"cards": {"L-001": {"col": "cut", "merge_into": None, "note": ""}}})
    export_book(b)
    r = check_book(b, truth=None, cut=["L-001"])
    assert r["cut_hole_leaks"] == ["Q-001"]


def test_建议8_给了key但算不出tau不能算pass(book_with_threads, tmp_path):
    """建议 8：--key/--folder 都给了，就是真的想验证顺序；答案文件跟书里场景的来源对不上号，
    算出来的 τ 会是 None——这不是「没要求」，不能悄悄放过，pass 必须是 False。
    骨架本身其它方面（每块恰好一次、空洞对得上、没有编造）都是干净的，这样 pass=False
    才能确定是 tau 这一项拖的，不是被别的问题顺带带崩的（不然测试测不出 tau_ok 这条逻辑）。"""
    b = book_with_threads
    items = [{"type": "scene", "id": "S-0001", "thread": "L-001"},
             {"type": "hole", "id": "H-001", "gap": "Q-001", "task": "补 [S-0002]"},
             *[{"type": "scene", "id": f"S-000{i}", "thread": "L-001" if i < 4 else "L-002"} for i in range(2, 6)]]
    write_json(b.skeleton_path, _sk(items))
    export_book(b)
    r0 = check_book(b, truth=None, cut=[])
    assert r0["each_once"] and not r0["holes_missing"] and not r0["holes_extra"] and not r0["fabricated_refs"]
    key_path = tmp_path / "答案.json"
    key_path.write_text(json.dumps({"files": []}, ensure_ascii=False), encoding="utf-8")
    report_path = tmp_path / "报告.json"
    main(["--library", str(b.root.parent), "--book", b.name,
         "--folder", "不存在的乱稿文件夹", "--key", str(key_path), "--report", str(report_path)])
    r = read_json(report_path)
    assert r["tau"] is None
    assert r["pass"] is False


def test_建议8_cut不给时默认从看板读(book_with_threads, tmp_path):
    """建议 8：--cut 不给时默认从看板现读 cut 列，不强制每次都手填。"""
    b = book_with_threads
    items = [{"type": "scene", "id": f"S-000{i}", "thread": "L-001"} for i in range(1, 4)] + \
            [{"type": "scene", "id": "S-0004", "thread": "L-002"}]
    write_json(b.skeleton_path, _sk(items))
    write_json(b.board_path, {"cards": {"L-002": {"col": "cut", "merge_into": None, "note": ""}}})
    export_book(b)
    report_path = tmp_path / "报告.json"
    main(["--library", str(b.root.parent), "--book", b.name, "--report", str(report_path)])
    r = read_json(report_path)
    assert r["cut_leaks"] == ["S-0004"]


def test_建议9_正常情况两边一致(book_with_threads):
    b = book_with_threads
    data = read_json(b.threads_path)
    data["intersections"] = [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "r"}]
    write_json(b.threads_path, data)
    items = [{"type": "scene", "id": f"S-000{i}", "thread": "L-001"} for i in range(1, 4)]
    write_json(b.skeleton_path, _sk(items))
    write_json(b.board_path, {"cards": {"L-002": {"col": "cut", "merge_into": None, "note": ""}}})
    export_book(b)
    r = check_book(b, truth=None, cut=["L-002"])
    assert r["crossing_mismatch"] == []  # 正常情况下两边一致


def test_建议9_program_impact漏交汇点时要报出来(book_with_threads, monkeypatch):
    """建议 9：program_impact 算出来的交汇点跟 threads.intersections 原始列表直接筛出来的
    对不上（这里 monkeypatch program_impact 模拟它漏了一个交汇点）时，crossing_mismatch
    要把那条线的编号列出来——不能因为「program_impact 反正也是从 intersections 算的」
    就假定它俩永远一致。"""
    import tools.eval_skeleton as ev_mod

    def buggy(book, threads, tid):
        return {"thread": tid, "crossings": [], "only_characters": [], "maybe_refs": []}

    monkeypatch.setattr(ev_mod, "program_impact", buggy)

    b = book_with_threads
    data = read_json(b.threads_path)
    data["intersections"] = [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "r"}]
    write_json(b.threads_path, data)
    items = [{"type": "scene", "id": f"S-000{i}", "thread": "L-001"} for i in range(1, 4)]
    write_json(b.skeleton_path, _sk(items))
    write_json(b.board_path, {"cards": {"L-002": {"col": "cut", "merge_into": None, "note": ""}}})
    export_book(b)
    r = check_book(b, truth=None, cut=["L-002"])
    assert r["crossing_mismatch"] == ["L-002"]
