from ligaotai.contradictions import batches, group_text, scene_times


def test_场景的全局故事时间是线的offset加线内时间():
    threads = [
        {"id": "L-001", "offset": 0, "scenes": ["S-0001"], "times": {"S-0001": {"t": 3.0, "conf": "高"}}},
        {"id": "L-002", "offset": 10, "scenes": ["S-0100"], "times": {"S-0100": {"t": 2.0, "conf": "低"}}},
    ]
    t = scene_times(threads)
    assert t["S-0001"] == {"t": 3.0, "conf": "高", "thread": "L-001"}
    assert t["S-0100"] == {"t": 12.0, "conf": "低", "thread": "L-002"}


def test_没有时间估计的场景不报错():
    threads = [{"id": "L-001", "offset": 0, "scenes": ["S-0001"], "times": {}}]
    assert scene_times(threads)["S-0001"]["t"] is None


def test_渲染的组带引用编号和时间():
    cand = {"subject": "孙悟空", "attribute": "兵器", "values": [
        {"value": "金箍棒", "scenes": [{"id": "S-0014", "quote": "取出金箍棒"}]},
        {"value": "降妖宝杖", "scenes": [{"id": "S-0207", "quote": "使降妖宝杖"}]},
    ]}
    times = {"S-0014": {"t": 3.0, "conf": "高", "thread": "L-001"},
             "S-0207": {"t": 5.0, "conf": "低", "thread": "L-001"}}
    text = group_text("C-001", cand, times, unit="年")
    assert "C-001" in text and "孙悟空" in text and "兵器" in text
    assert "S-0014" in text and "取出金箍棒" in text
    assert "低" in text, "置信度低的要标出来给模型"
    assert "年" in text


def test_按token上限切批():
    cands = [{"subject": f"人{i}", "attribute": "兵器", "values": [
        {"value": "甲", "scenes": [{"id": "S-0001", "quote": "x" * 100}]},
        {"value": "乙", "scenes": [{"id": "S-0002", "quote": "y" * 100}]}]} for i in range(10)]
    got = batches(cands, {}, unit="年", budget=600)
    assert len(got) > 1
    assert sum(len(b) for b in got) == 10, "一个组都不能丢"


def test_单个组超预算也自成一批():
    cands = [{"subject": "甲", "attribute": "兵器", "values": [
        {"value": "v", "scenes": [{"id": "S-0001", "quote": "x" * 5000}]},
        {"value": "w", "scenes": [{"id": "S-0002", "quote": "y" * 5000}]}]}]
    got = batches(cands, {}, unit="年", budget=100)
    assert len(got) == 1 and len(got[0]) == 1


def test_小组数量多时按组数上限切批_不靠字符预算兜底():
    """审查建议修6：小组多时字符预算一批可能塞进几百组，输出和重试成本失控。
    加一个每批组数上限（独立于字符预算），即使字符预算远没到也要切批。"""
    cands = [{"subject": f"人{i}", "attribute": "兵器", "values": [
        {"value": "甲", "scenes": [{"id": "S-0001", "quote": "x"}]},
        {"value": "乙", "scenes": [{"id": "S-0002", "quote": "y"}]}]} for i in range(10)]
    got = batches(cands, {}, unit="年", budget=100000, max_groups=3)
    assert [len(b) for b in got] == [3, 3, 3, 1]
    assert sum(len(b) for b in got) == 10, "一个组都不能丢"


import pytest

from ligaotai.contradictions import check_output, clean_output


def _out(**kw):
    base = {"id": "C-001", "status": "真矛盾", "level": "严重",
            "category": "人物", "reason": "两处写的不是一件兵器 [S-0014][S-0207]"}
    base.update(kw)
    return {"groups": [base]}


def test_输出覆盖不全要报问题():
    assert check_output(_out(), {"C-001", "C-002"}) != []


def test_多出来的编号要报问题():
    assert check_output(_out(), set()) != []


def test_status不在三值里要报问题():
    assert check_output(_out(status="也许"), {"C-001"}) != []


def test_真矛盾没给严重度要报问题():
    assert check_output(_out(level=""), {"C-001"}) != []


def test_合理变化的严重度留空是对的():
    assert check_output(_out(status="合理变化", level=""), {"C-001"}) == []


def test_reason不带场景编号要报问题():
    assert check_output(_out(reason="就是不一样"), {"C-001"}) != []


def test_正常输出没问题():
    assert check_output(_out(), {"C-001"}) == []


def test_clean丢掉编造的编号并给漏掉的兜底():
    data = {"groups": [
        {"id": "C-001", "status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0014]"},
        {"id": "C-999", "status": "真矛盾", "level": "严重", "category": "人物", "reason": "y [S-0001]"},
    ]}
    got = clean_output(data, {"C-001", "C-002"})
    assert set(got) == {"C-001", "C-002"}
    assert got["C-002"]["status"] == "无法判断", "模型没答的按宁可多报兜底"
    assert got["C-002"]["reason"]


def test_clean_output非法status兜底成无法判断():
    data = {"groups": [
        {"id": "C-001", "status": "也许", "level": "严重", "category": "人物", "reason": "x [S-0014]"},
    ]}
    got = clean_output(data, {"C-001"})
    assert got["C-001"]["status"] == "无法判断"


# --- D 组审查后的待办 必须修2：groups 里混进非 dict 元素 / 顶层给成 list / id 是
# list 这类不可哈希类型时，check_output 得报问题触发重试，clean_output 不许抛异常
# （宁可多报：拿不到合法判断的组一律补成「无法判断」，绝不静默丢组）---

def test_groups里混入非dict元素_check要报问题_clean不能崩且不丢合法项():
    data = {"groups": [
        "C-001 真矛盾",  # 模型输出格式错乱，混进了字符串
        {"id": "C-002", "status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"},
    ]}
    ids = {"C-002"}
    problems = check_output(data, ids)
    assert problems != [], "混入非dict项即使合法项齐全也要报问题触发重试，不能悄悄放过"
    got = clean_output(data, ids)  # 不该抛异常
    assert got["C-002"]["status"] == "真矛盾", "混进去的垃圾项不能连累后面合法的判断被扔掉"


def test_顶层是list_check要报问题_clean不崩且全部兜底成无法判断():
    data = [{"id": "C-001", "status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}]
    ids = {"C-001"}
    assert check_output(data, ids) != []
    got = clean_output(data, ids)  # 不该抛异常
    assert got["C-001"]["status"] == "无法判断", "顶层格式都不对，拿不到合法判断，宁可多报兜底"


def test_id是list不可哈希_check要报问题_clean不崩():
    data = {"groups": [
        {"id": ["C-001"], "status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"},
    ]}
    ids = {"C-001"}
    assert check_output(data, ids) != []
    got = clean_output(data, ids)  # 不该抛异常（旧代码 TypeError: unhashable type: 'list'）
    assert got["C-001"]["status"] == "无法判断"


from ligaotai.contradictions import build_result


def _cand(subject, attribute, values):
    return {"subject": subject, "attribute": attribute, "merged": 0,
            "values": [{"value": v, "scenes": [{"id": s, "quote": "q"}]} for v, s in values]}


# --- 审查建议修9：「宁可多报」的两处兜底原来没有测试守住（变异测试全部存活），
# 补测试并做同样的变异确认会红，再手动改回来（不用 git checkout/restore）---

def test_build_result没拿到判断的组兜底成无法判断():
    """judged 缺下标（这一批调用失败）时，build_result 要按宁可多报兜底成
    「无法判断」，不能悄悄当「合理变化」处理漏掉真矛盾。"""
    res = build_result(
        [_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
        {}, {}, {"next_id": 1, "groups": []}, stats={})
    assert res["groups"][0]["status"] == "无法判断"
    assert res["groups"][0]["reason"]


def test_编号取next_id只增不减():
    old = {"next_id": 5, "groups": []}
    res = build_result([_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
                       {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
                       {}, old, stats={})
    assert res["groups"][0]["id"] == "C-005"
    assert res["next_id"] == 6


def test_同一主语属性重跑沿用原编号():
    old = {"next_id": 9, "groups": [{"id": "C-003", "subject": "甲", "attribute": "兵器", "verdict": None}]}
    res = build_result([_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
                       {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
                       {}, old, stats={})
    assert res["groups"][0]["id"] == "C-003"
    assert res["next_id"] == 9, "沿用了就不该消耗新号"


def test_verdict按主语属性迁移():
    old = {"next_id": 9, "groups": [
        {"id": "C-003", "subject": "甲", "attribute": "兵器", "verdict": {"choice": "v"}},
        {"id": "C-004", "subject": "乙", "attribute": "外貌", "verdict": {"choice": "x"}},
    ]}
    res = build_result([_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
                       {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
                       {}, old, stats={})
    assert res["groups"][0]["verdict"] == {"choice": "v"}
    assert res["orphan_verdicts"] == [
        {"id": "C-004", "subject": "乙", "attribute": "外貌", "verdict": {"choice": "x"}, "values_sig": None,
         "verdict_sig": None, "verdict_stale": False}
    ]


# --- D 组审查后的待办 必须修3：组消失一轮再回来，要沿用原编号、接回原 verdict；
# 在没回来之前，orphan 要继续往下传，不能丢 ---

def test_组消失一轮再回来_沿用原编号且verdict能接回():
    old1 = {"next_id": 2, "groups": [
        {"id": "C-001", "subject": "甲", "attribute": "兵器", "verdict": {"choice": "v"}},
    ]}
    # 第二轮：甲这次没进候选，verdict 应该进 orphan_verdicts，且带着原编号
    res2 = build_result([], {}, {}, old1, stats={})
    assert res2["groups"] == []
    assert res2["orphan_verdicts"] == [
        {"id": "C-001", "subject": "甲", "attribute": "兵器", "verdict": {"choice": "v"}, "values_sig": None,
         "verdict_sig": None, "verdict_stale": False}
    ]

    # 第三轮：甲回来了
    res3 = build_result(
        [_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
        {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
        {}, res2, stats={})
    assert res3["groups"][0]["id"] == "C-001", "沿用原编号，不能换新号"
    assert res3["groups"][0]["verdict"] == {"choice": "v"}, "verdict 要能接回来，不能永久丢失"
    assert res3["orphan_verdicts"] == [], "回来了就不再是 orphan"


def test_orphan在未回来前继续往下传_不会消失一轮就丢():
    old1 = {"next_id": 2, "groups": [
        {"id": "C-001", "subject": "甲", "attribute": "兵器", "verdict": {"choice": "v"}},
    ]}
    res2 = build_result([], {}, {}, old1, stats={})
    # 第三轮：甲还是没回来（比如又没抽出候选），orphan 得继续保留，不能凭空消失
    res3 = build_result([], {}, {}, res2, stats={})
    assert res3["orphan_verdicts"] == res2["orphan_verdicts"]


# --- D 组审查后的待办 必须修4：值集合变了（多了新值，或作者选中的值不在了），
# 旧判定保留但要标 verdict_stale=true，交给界面重新亮出来（作者 9-17 拍板）---

from ligaotai.contradictions import values_sig


def test_值集合签名_空白与数字规范化后相同即视为没变():
    a = values_sig([{"value": "十六"}, {"value": " 十七 "}])
    b = values_sig([{"value": "16"}, {"value": "17"}])
    assert a == b


def test_值集合签名_顺序不影响结果():
    a = values_sig([{"value": "甲"}, {"value": "乙"}])
    b = values_sig([{"value": "乙"}, {"value": "甲"}])
    assert a == b


def test_值集合签名_值真不同就不同():
    a = values_sig([{"value": "金箍棒"}, {"value": "降妖宝杖"}])
    b = values_sig([{"value": "金箍棒"}])
    assert a != b


def test_值集合签名不转繁简_是已知限制不是bug():
    """项目里没有通用繁转简（facts._to_simplified 只覆盖属性名归一，不能拿来转值文本），
    所以签名只做 strip 和 facts 已有的数字规范化，值本身的繁简差异（老卡繁体、新卡简体）
    仍会被判定为"变了"，需要人工重新看一眼——保守，不算误报。"""
    a = values_sig([{"value": "十七歲"}])
    b = values_sig([{"value": "十七岁"}])
    assert a != b


def test_值集合变了_多了新值_verdict保留但标记需重看():
    old = {"next_id": 2, "groups": [
        {"id": "C-001", "subject": "甲", "attribute": "兵器", "verdict": {"choice": "v"},
         "values_sig": values_sig([{"value": "v"}, {"value": "w"}])},
    ]}
    res = build_result(
        [_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002"), ("z", "S-0003")])],
        {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
        {}, old, stats={})
    g = res["groups"][0]
    assert g["id"] == "C-001", "编号还是要沿用"
    assert g["verdict"] == {"choice": "v"}, "旧判定保留，不能张冠李戴地扔掉"
    assert g["verdict_stale"] is True, "值集合变了要标记需重看"


def test_值集合变了_原选中的值不在了_verdict保留但标记需重看():
    old = {"next_id": 2, "groups": [
        {"id": "C-001", "subject": "甲", "attribute": "兵器", "verdict": {"choice": "v"},
         "values_sig": values_sig([{"value": "v"}, {"value": "w"}])},
    ]}
    res = build_result(
        [_cand("甲", "兵器", [("v", "S-0001"), ("z", "S-0003")])],  # w 没了，换成 z
        {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
        {}, old, stats={})
    assert res["groups"][0]["verdict_stale"] is True


def test_值集合没变_不标记stale():
    old = {"next_id": 2, "groups": [
        {"id": "C-001", "subject": "甲", "attribute": "兵器", "verdict": {"choice": "v"},
         "values_sig": values_sig([{"value": "v"}, {"value": "w"}])},
    ]}
    res = build_result(
        [_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
        {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
        {}, old, stats={})
    assert res["groups"][0]["verdict_stale"] is False


def test_没有verdict时不标记stale():
    old = {"next_id": 2, "groups": [
        {"id": "C-001", "subject": "甲", "attribute": "兵器", "verdict": None,
         "values_sig": values_sig([{"value": "v"}, {"value": "w"}])},
    ]}
    res = build_result(
        [_cand("甲", "兵器", [("v", "S-0001"), ("z", "S-0003")])],
        {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
        {}, old, stats={})
    assert res["groups"][0]["verdict"] is None
    assert res["groups"][0]["verdict_stale"] is False, "没有旧判定，谈不上需要重看"


def test_旧数据没存values_sig字段时不误判stale():
    """老格式数据（这次改动之前落盘的）没有 values_sig，没有依据就不该瞎报 stale。"""
    old = {"next_id": 9, "groups": [
        {"id": "C-003", "subject": "甲", "attribute": "兵器", "verdict": {"choice": "v"}},
    ]}
    res = build_result(
        [_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
        {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
        {}, old, stats={})
    assert res["groups"][0]["verdict_stale"] is False


# --- DE 审查必须修1：stale 要跟「作者当初判定时的值集合」比，不是跟上一轮比；
# 值变了之后接着重跑（二期之前的常态），stale 不能自己消失，经过 orphan 回来也不能丢 ---

_J = {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}


def _run(cands, old):
    return build_result(cands, {i: dict(_J) for i in range(len(cands))}, {}, old, stats={})


def _judged_round1():
    r1 = _run([_cand("甲", "兵器", [("金箍棒", "S-0001"), ("宝杖", "S-0002")])], {})
    r1["groups"][0]["verdict"] = {"choice": "金箍棒"}  # 作者在第 1 轮的值集合上下了判定
    return r1


def test_值变了之后再跑一轮_仍然标需重看():
    r1 = _judged_round1()
    three = [_cand("甲", "兵器", [("金箍棒", "S-0001"), ("宝杖", "S-0002"), ("钉耙", "S-0003")])]
    r2 = _run(three, r1)
    assert r2["groups"][0]["verdict_stale"] is True
    r3 = _run(three, r2)  # 什么都没变，但作者还没看过「钉耙」
    assert r3["groups"][0]["verdict_stale"] is True, "作者没重新判定前，stale 要一直带着"
    r4 = _run(three, r3)
    assert r4["groups"][0]["verdict_stale"] is True


def test_值集合变回作者判定时的样子_不再标需重看():
    r1 = _judged_round1()
    r2 = _run([_cand("甲", "兵器", [("金箍棒", "S-0001"), ("宝杖", "S-0002"), ("钉耙", "S-0003")])], r1)
    r3 = _run([_cand("甲", "兵器", [("金箍棒", "S-0001"), ("宝杖", "S-0002")])], r2)
    assert r3["groups"][0]["verdict_stale"] is False, "跟作者判定时的值集合一样了，判定重新有效"


def test_stale经过orphan回来仍然标需重看():
    r1 = _judged_round1()
    three = [_cand("甲", "兵器", [("金箍棒", "S-0001"), ("宝杖", "S-0002"), ("钉耙", "S-0003")])]
    other = [_cand("乙", "年龄", [("十六", "S-0004"), ("二十", "S-0005")])]
    r2 = _run(three, r1)
    assert r2["groups"][0]["verdict_stale"] is True
    r3 = _run(other, r2)  # 甲消失一轮，进 orphan
    r4 = _run(three + other, r3)
    g = next(g for g in r4["groups"] if g["subject"] == "甲")
    assert g["verdict"] == {"choice": "金箍棒"}
    assert g["verdict_stale"] is True, "经过 orphan 回来不能把 stale 洗掉"


def test_verdict_sig记下判定依据的值集合_随组和orphan一起传():
    r1 = _judged_round1()
    sig1 = r1["groups"][0]["values_sig"]
    r2 = _run([_cand("甲", "兵器", [("金箍棒", "S-0001"), ("宝杖", "S-0002"), ("钉耙", "S-0003")])], r1)
    assert r2["groups"][0]["verdict_sig"] == sig1
    r3 = _run([], r2)
    assert r3["orphan_verdicts"][0]["verdict_sig"] == sig1


def test_场景里带上故事时间和所属线():
    times = {"S-0001": {"t": 3.0, "conf": "高", "thread": "L-001"}}
    res = build_result([_cand("甲", "兵器", [("v", "S-0001"), ("w", "S-0002")])],
                       {0: {"status": "真矛盾", "level": "严重", "category": "人物", "reason": "x [S-0001]"}},
                       times, {"next_id": 1, "groups": []}, stats={})
    s = res["groups"][0]["values"][0]["scenes"][0]
    assert s["t"] == 3.0 and s["conf"] == "高" and s["thread"] == "L-001"


from ligaotai.contradictions import cap


def test_超上限的按权重截断且不静默丢弃():
    cands = [{"subject": f"人{i}", "attribute": "兵器", "weight": i,
              "values": [{"value": "v", "scenes": [{"id": "S-0001", "quote": "q"}]},
                         {"value": "w", "scenes": [{"id": "S-0002", "quote": "q"}]}]}
             for i in range(5)]
    cands.sort(key=lambda c: -c["weight"])
    kept, skipped = cap(cands, 2)
    assert len(kept) == 2
    assert [c["subject"] for c in kept] == ["人4", "人3"]
    assert len(skipped) == 3
    assert skipped[0] == {"subject": "人2", "attribute": "兵器", "reason": "超过上限"}


def test_没超上限就原样返回():
    cands = [{"subject": "甲", "attribute": "兵器", "weight": 1, "values": []}]
    kept, skipped = cap(cands, 10)
    assert kept == cands and skipped == []


# --- 用真实 facts.py / entities.py 的产出走一遍整条管线，不手捏契约
# （task08~11 的教训：测试里手捏的候选组结构跟真实 candidates() 产出一旦不一致，
# 单测全绿也救不了真实数据跑不通）---

from ligaotai.contradictions import render_values
from ligaotai.entities import _cmap as _entities_cmap
from ligaotai.facts import candidates, collect_facts, group_facts


def _real_cmap(*entities):
    return _entities_cmap({"entities": [
        {"type": t, "names": names, "canonical": canonical}
        for t, names, canonical in entities
    ]})


def test_真实candidates产出能完整走完渲染批次判断落盘一遍():
    cmap = _real_cmap(("person", ["孙悟空", "行者"], "孙悟空"))
    cards = {
        "S-0014": {"facts": [
            {"subject": "孙悟空", "attribute": "兵器", "value": "金箍棒", "quote": "取出金箍棒"},
        ]},
        "S-0207": {"facts": [
            {"subject": "行者", "attribute": "兵器", "value": "降妖宝杖", "quote": "使降妖宝杖"},
        ]},
    }
    rows = collect_facts(cards, cmap)
    cands = candidates(group_facts(rows))
    assert cands and cands[0]["subject"] == "孙悟空" and cands[0]["attribute"] == "兵器"

    threads = [{"id": "L-001", "offset": 0, "scenes": ["S-0014", "S-0207"],
                "times": {"S-0014": {"t": 3.0, "conf": "高"}, "S-0207": {"t": 5.0, "conf": "低"}}}]
    times = scene_times(threads)

    batched = batches(cands, times, unit="年", budget=30000)
    assert sum(len(b) for b in batched) == len(cands)

    text, numbered = render_values(batched[0], start=1, times=times, unit="年")
    assert "C-001" in text and "孙悟空" in text and "S-0014" in text

    fake_output = {"groups": [
        {"id": "C-001", "status": "真矛盾", "level": "严重", "category": "人物",
         "reason": "同一件兵器写成了两个名字 [S-0014,S-0207]"},
    ]}
    ids = set(numbered)
    assert check_output(fake_output, ids) == []
    judged_by_id = clean_output(fake_output, ids)
    # clean_output 按这一批临时编号回，build_result 要的是按 cands 下标的 judged——
    # 这里下标 0 就对应本批第一个（也是唯一一个）候选组。
    judged = {0: judged_by_id["C-001"]}
    result = build_result(batched[0], judged, times, {"next_id": 1, "groups": []}, stats={})
    assert result["groups"][0]["subject"] == "孙悟空"
    assert result["groups"][0]["status"] == "真矛盾"
    assert result["groups"][0]["values"][0]["scenes"][0]["t"] in (3.0, 5.0)
