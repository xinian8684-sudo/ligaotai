from ligaotai.archive import input_sig, load_index, map_sig, reconcile, thread_sig, world_sig, write_index

# 9-17 作者拍板改的签名契约：签名 = 哈希「渲染好、真正送给模型的输入文本」+ 提示词模板名。
# 见 dispatch.md「C 组审查后的待办 1」。旧版本按几个挑出来的字段算签名，
# 漏了 canonical_map、move_thread、故事时间、缺口位置、世界判定依据/设定笔记，
# 这些东西改了档案会被判「没变」悄悄跳过。新契约下这些全部自动被文本渲染带上，
# 不用再回头给签名函数一个一个补参数。


def test_签名跟着渲染文本变():
    base = thread_sig("甲文本")
    assert thread_sig("甲文本") == base, "同样的输入要稳定"
    assert thread_sig("乙文本") != base, "文本变了要变"


def test_签名跟着提示词模板名变():
    """哪怕渲染文本一样，换了提示词模板名（模型看到的指令变了）签名也要变——
    以后改提示词大版本，靠改模板名就能让所有档案重跑，不用去猜文本有没有变。"""
    # 9-19 起签名还带提示词内容（DE 审查第 6 条），模板名必须是真有的提示词文件
    assert thread_sig("甲文本", prompt="archive_thread") != thread_sig("甲文本", prompt="archive_world")


def test_三个签名函数默认命名空间不串():
    text = "同一段文本"
    assert len({thread_sig(text), world_sig(text), map_sig(text)}) == 3


def test_input_sig是三个函数共用的底层实现():
    assert thread_sig("x", prompt="map") == input_sig("x", "map")
    assert world_sig("x", prompt="map") == input_sig("x", "map")
    assert map_sig("x", prompt="map") == input_sig("x", "map")


# --- 用 archive_input 的真实渲染函数造输入，不手捏假契约（前车之鉴：手捏的假结构会跟真实代码脱节）---


def _thread_and_cards():
    cards = {
        "S-0001": {"summary": "行者救人", "characters": [{"name": "行者", "role": "主要"}],
                   "locations": ["山中"], "hooks_planted": [], "hooks_resolved": []},
    }
    thread = {"id": "L-001", "name": "取经线", "world": "W-01", "scenes": ["S-0001"],
              "end": {"state": "待定", "note": "", "last": "S-0001"}}
    return thread, cards


def test_改规范名映射签名会变():
    """C 组审查实测漏的第一项：canonical_map 变了（比如把「行者」并进「孙悟空」），
    thread_input 里 card_line 用 cmap 归一人物名，渲染文本会变，签名要跟着变。"""
    from ligaotai.archive_input import thread_input

    thread, cards = _thread_and_cards()
    base = thread_sig(thread_input(thread, cards, cmap={}, gaps=[], times={}, unit="年"))
    cmap = {("person", "行者"): "孙悟空"}
    changed = thread_sig(thread_input(thread, cards, cmap=cmap, gaps=[], times={}, unit="年"))
    assert changed != base


def test_线换所属世界签名会变():
    """C 组审查实测漏的第二项：move_thread 换世界。thread_input 第一行写了
    「所属世界：$world」，world 变了渲染文本就变。"""
    from ligaotai.archive_input import thread_input

    thread, cards = _thread_and_cards()
    base = thread_sig(thread_input(thread, cards, cmap={}, gaps=[], times={}, unit="年"))
    moved = {**thread, "world": "W-02"}
    changed = thread_sig(thread_input(moved, cards, cmap={}, gaps=[], times={}, unit="年"))
    assert changed != base


def test_故事时间变签名会变():
    """C 组审查实测漏的第三项：线的故事时间（times[sid].t / conf）。"""
    from ligaotai.archive_input import thread_input

    thread, cards = _thread_and_cards()
    base = thread_sig(thread_input(thread, cards, cmap={}, gaps=[],
                                   times={"S-0001": {"t": 1.0, "conf": "高"}}, unit="年"))
    changed = thread_sig(thread_input(thread, cards, cmap={}, gaps=[],
                                      times={"S-0001": {"t": 3.0, "conf": "低"}}, unit="年"))
    assert changed != base


def test_缺口的位置变签名会变():
    """C 组审查实测漏的第四项：缺口的 after/before/mentioned_in。"""
    from ligaotai.archive_input import thread_input

    thread, cards = _thread_and_cards()
    gap1 = [{"event": "青州城破", "mentioned_in": ["S-0001"], "after": "S-0001", "before": None}]
    gap2 = [{"event": "青州城破", "mentioned_in": ["S-0001"], "after": None, "before": "S-0001"}]
    base = thread_sig(thread_input(thread, cards, cmap={}, gaps=gap1, times={}, unit="年"))
    changed = thread_sig(thread_input(thread, cards, cmap={}, gaps=gap2, times={}, unit="年"))
    assert changed != base


def test_世界判定依据变签名会变():
    """C 组审查实测漏的第五项：世界的 reason（判定依据）。"""
    from ligaotai.archive_input import world_input

    base = world_sig(world_input({"id": "W-01", "name": "取经路", "reason": "有佛道元素"},
                                 [], notes=[], threads=[]))
    changed = world_sig(world_input({"id": "W-01", "name": "取经路", "reason": "有仙侠元素"},
                                    [], notes=[], threads=[]))
    assert changed != base


def test_设定笔记内容变签名会变():
    """C 组审查实测漏的第六项：设定笔记（notes）原文。真实数据里雪月梅 W-01.notes=[S-0060]，
    且 S-0060 不在任何线的场景里——按字段签名算不出这块内容，按渲染文本签名就自动带上。"""
    from ligaotai.archive_input import world_input

    world = {"id": "W-01", "name": "取经路", "reason": "有佛道"}
    base = world_sig(world_input(world, [], notes=[{"id": "S-0060", "text": "这里是设定笔记原文"}], threads=[]))
    changed = world_sig(world_input(world, [], notes=[{"id": "S-0060", "text": "改过的设定笔记原文"}], threads=[]))
    assert changed != base


def test_地图的严重矛盾缺口断点变签名会变():
    """C 组审查「必须修 5」：map_input 已经把严重矛盾/缺口总览/各条线写到哪都拼进渲染文本，
    map_sig 直接哈希这份文本，这三样变了签名自动跟着变，不用再补参数。"""
    from ligaotai.archive_input import map_input

    base_args = dict(world_files=[], thread_files=[],
                     contradictions=[{"id": "C-001", "subject": "甲", "attribute": "兵器",
                                       "status": "真矛盾", "level": "严重", "reason": "x [S-0001]"}],
                     gaps=[{"event": "青州城破", "world": "W-01"}],
                     ends=[{"id": "L-001", "name": "线", "state": "待定", "last": "S-0001"}])
    base = map_sig(map_input(**base_args))

    new_contradiction = {**base_args, "contradictions": base_args["contradictions"] +
                         [{"id": "C-002", "subject": "乙", "attribute": "外貌",
                           "status": "真矛盾", "level": "严重", "reason": "y [S-0002]"}]}
    assert map_sig(map_input(**new_contradiction)) != base

    new_gap = {**base_args, "gaps": base_args["gaps"] + [{"event": "新缺口", "world": "W-01"}]}
    assert map_sig(map_input(**new_gap)) != base

    new_end = {**base_args, "ends": [{"id": "L-001", "name": "线", "state": "完结", "last": "S-0001"}]}
    assert map_sig(map_input(**new_end)) != base


def test_只改用不到的无关卡片签名不变():
    """反过来验证：thread_input 根本不读的场景卡（不在这条线的 scenes 里，
    hooks_resolved 也是空的，不影响全书回收集合）改了，签名不该变——
    不是签名对什么都敏感，是只对「真进了渲染文本」的东西敏感。"""
    from ligaotai.archive_input import thread_input

    thread, cards = _thread_and_cards()
    base = thread_sig(thread_input(thread, cards, cmap={}, gaps=[], times={}, unit="年"))
    cards_with_unrelated = {**cards, "S-9999": {"summary": "跟这条线无关", "characters": [],
                                                 "locations": [], "hooks_planted": [], "hooks_resolved": []}}
    same = thread_sig(thread_input(thread, cards_with_unrelated, cmap={}, gaps=[], times={}, unit="年"))
    assert same == base


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


def test_index文件JSON坏了当空壳处理不抛异常(tmp_path, caplog):
    from ligaotai.book import Book

    book = Book(tmp_path)
    book.root.mkdir(exist_ok=True)
    book.archive_index_path.parent.mkdir(parents=True, exist_ok=True)
    book.archive_index_path.write_text("{坏掉的 json", encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert load_index(book) == {"threads": {}, "worlds": {}, "map": {}}
    assert any("index" in r.message or "档案" in r.message for r in caplog.records)


def test_index字段类型不对当空壳处理不抛异常(tmp_path, caplog):
    from ligaotai.book import Book

    book = Book(tmp_path)
    book.root.mkdir(exist_ok=True)
    write_index(book, {"threads": ["不是字典"], "worlds": {"W-01": {"outdated": False}}, "map": {}})
    with caplog.at_level("WARNING"):
        assert load_index(book) == {"threads": {}, "worlds": {}, "map": {}}
    assert any("index" in r.message or "档案" in r.message for r in caplog.records)
