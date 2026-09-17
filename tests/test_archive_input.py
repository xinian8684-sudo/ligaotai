from ligaotai.archive_input import open_hooks, thread_input, world_input


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
