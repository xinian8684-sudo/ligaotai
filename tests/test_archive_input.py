from ligaotai.archive_input import map_input, open_hooks, thread_input, world_input


def test_开放伏笔是埋了没回收的():
    cards = {
        "S-0001": {"hooks_planted": ["令牌来历不明", "老人的身份"], "hooks_resolved": []},
        "S-0002": {"hooks_planted": [], "hooks_resolved": ["老人的身份"]},
    }
    got = open_hooks(["S-0001", "S-0002"], cards, all_resolved={"老人的身份"})
    assert got == [{"hook": "令牌来历不明", "scene": "S-0001"}]


def test_开放伏笔按语义相近去重():
    cards = {"S-0001": {"hooks_planted": ["令牌的来历不明"], "hooks_resolved": []}}
    got = open_hooks(["S-0001"], cards, all_resolved={"令牌来历不明"})
    assert got == [], "去掉标点和虚词后一样的算回收了"


def test_线的输入带顺序摘要人物地点时间():
    cards = {"S-0002": {"summary": "林清救人", "characters": [{"name": "林清", "role": "主要"}],
                        "locations": ["青州"], "hooks_planted": [], "hooks_resolved": []},
             "S-0001": {"summary": "赵五受伤", "characters": [], "locations": [],
                        "hooks_planted": [], "hooks_resolved": []}}
    thread = {"id": "L-001", "name": "林清线", "world": "W-01",
              "scenes": ["S-0002", "S-0001"],
              "end": {"state": "待定", "note": "写到一半", "last": "S-0001"}}
    text = thread_input(thread, cards, cmap={}, gaps=[{"event": "青州城破", "mentioned_in": ["S-0002"],
                                                      "after": "S-0001", "before": None}],
                        times={"S-0002": {"t": 1.0, "conf": "高", "thread": "L-001"}}, unit="年")
    assert text.index("S-0002") < text.index("S-0001"), "按线内顺序，不是编号顺序"
    assert "林清救人" in text and "青州" in text
    assert "青州城破" in text and "写到一半" in text
    assert "Q-" not in text, "缺口按内容认，不给 Q- 编号"


def test_世界的输入是facts不是摘要():
    from ligaotai.facts import FactRow
    rows = [FactRow("S-0001", "孙悟空", "兵器", "金箍棒", "取出金箍棒"),
            FactRow("S-0002", "孙悟空", "其他", "打妖怪", "打妖怪去了")]
    text = world_input({"id": "W-01", "name": "取经路", "reason": "有佛道"}, rows,
                       notes=[], threads=[{"id": "L-001", "name": "林清线"}])
    assert "金箍棒" in text and "S-0001" in text
    assert "打妖怪" in text, "设定集包含「其他」类 facts（spec 第 5 节）"
    assert "L-001" in text and "有佛道" in text


def test_地图的输入是档案正文不是场景卡(tmp_path):
    t = tmp_path / "L-001.md"
    w = tmp_path / "W-01.md"
    t.write_text("# L-001 林清线\n他救了人 [S-0003]。\n", encoding="utf-8")
    w.write_text("# W-01 人间\n- 林清：十六 [S-0003]\n", encoding="utf-8")
    text = map_input([w], [t],
                     contradictions=[{"id": "C-007", "subject": "孙悟空", "attribute": "兵器",
                                      "status": "真矛盾", "level": "严重",
                                      "reason": "两处不一样 [S-0014]"}],
                     gaps=[{"event": "青州城破", "world": "W-01"}],
                     ends=[{"id": "L-001", "name": "林清线", "state": "待定", "last": "S-0003"}])
    assert "林清线" in text and "人间" in text
    assert "C-007" in text and "青州城破" in text
    assert "S-0003" in text


def test_地图输入只带严重矛盾():
    text = map_input([], [],
                     contradictions=[
                         {"id": "C-001", "subject": "甲", "attribute": "兵器", "status": "真矛盾",
                          "level": "轻微", "reason": "x [S-0001]"},
                         {"id": "C-002", "subject": "乙", "attribute": "外貌", "status": "真矛盾",
                          "level": "严重", "reason": "y [S-0002]"},
                         {"id": "C-003", "subject": "丙", "attribute": "年龄", "status": "合理变化",
                          "level": "", "reason": "z [S-0003]"}],
                     gaps=[], ends=[])
    assert "C-002" in text
    assert "C-001" not in text and "C-003" not in text


# --- DE 审查必须修5：交汇点（spec 7.3「该世界下各条线一段摘要 + 交汇点」）要进地图输入 ---

_IX = [{"thread": "L-005", "scene": "S-0085", "main_scene": "S-0081",
        "reason": "两处写的是文进救王夫人后与岑秀在途中相遇的同一事件"}]


def test_地图输入带线之间的交汇():
    text = map_input([], [], contradictions=[], gaps=[],
                     ends=[{"id": "L-005", "name": "文进线", "state": "待定", "last": "S-0085"}],
                     intersections=_IX)
    assert "# 线之间的交汇" in text
    line = next(x for x in text.splitlines() if "S-0085" in x and "S-0081" in x)
    assert "L-005" in line and "文进线" in line and "途中相遇" in line


def test_交汇变了地图签名就变():
    from ligaotai.archive import map_sig

    base = map_sig(map_input([], [], contradictions=[], gaps=[], ends=[], intersections=_IX))
    moved = [dict(_IX[0], main_scene="S-0090")]
    assert map_sig(map_input([], [], contradictions=[], gaps=[], ends=[], intersections=moved)) != base
    assert map_sig(map_input([], [], contradictions=[], gaps=[], ends=[], intersections=[])) != base
