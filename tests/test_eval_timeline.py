from tools.eval_timeline import recall_timeline

CH = {3: {"S-0003"}, 8: {"S-0008"}, 5: {"S-0005"}, 9: {"S-0009"}}
KEY = {"timeline": [{"kind": "A", "who": "岑秀", "name": "岑秀", "chapters": [3, 8]},
                    {"kind": "C", "who": "岑秀", "event": "比箭", "chapters": [5, 9]}]}


def test_两类都命中():
    res = {"conflicts": [
        {"kind": "A", "who": "岑秀", "scenes": ["S-0003", "S-0008"]},
        {"kind": "C", "ref": "想起比箭", "scenes": ["S-0005", "S-0009"]}]}
    r = recall_timeline(KEY, CH, res, cmap={})
    assert (r["A"]["hit"], r["A"]["planted"], r["C"]["hit"], r["C"]["planted"]) == (1, 1, 1, 1)


def test_A人名要归一_场景要落在对的章():
    res = {"conflicts": [{"kind": "A", "who": "岑公子", "scenes": ["S-0003", "S-0009"]}]}
    assert recall_timeline(KEY, CH, res, cmap={("person", "岑公子"): "岑秀"})["A"]["hit"] == 0  # 后一场章不对
    res = {"conflicts": [{"kind": "A", "who": "岑公子", "scenes": ["S-0003", "S-0008"]}]}
    assert recall_timeline(KEY, CH, res, cmap={("person", "岑公子"): "岑秀"})["A"]["hit"] == 1


def test_没命中归因_A():
    cards = {"S-0003": {"card": {"facts": [], "characters": []}},
             "S-0008": {"card": {"facts": [], "characters": [{"name": "岑秀"}]}}}
    r = recall_timeline(KEY, CH, {"conflicts": [], "dismissed": [], "asked_refs": []}, cmap={}, cards=cards)
    assert r["A"]["misses"][0]["cause"] == "死亡没被抽成 fact"
    cards["S-0003"]["card"]["facts"] = [{"subject": "岑秀", "attribute": "生死", "value": "染病身亡", "quote": "q"}]
    r = recall_timeline(KEY, CH, {"conflicts": [], "dismissed": [{"who": "岑秀", "scenes": ["S-0003", "S-0008"]}],
                                  "asked_refs": []}, cmap={}, cards=cards)
    assert r["A"]["misses"][0]["cause"] == "模型判成只是提到"


def test_没命中归因_C():
    base = {"conflicts": [], "dismissed": []}
    r = recall_timeline(KEY, CH, {**base, "asked_refs": []}, cmap={}, cards={})
    assert r["C"]["misses"][0]["cause"] == "没问到（回指没抽出来，或候选全在前面）"
    r = recall_timeline(KEY, CH, {**base, "asked_refs": [{"scene": "S-0005", "ref": "想起比箭", "candidates": ["S-0003"], "happens_in": None}]}, cmap={}, cards={})
    assert r["C"]["misses"][0]["cause"] == "候选里没有事件那一场"
    r = recall_timeline(KEY, CH, {**base, "asked_refs": [{"scene": "S-0005", "ref": "想起比箭", "candidates": ["S-0009"], "happens_in": None}]}, cmap={}, cards={})
    assert r["C"]["misses"][0]["cause"] == "模型判错了场"


# --------------------------------------------------------------------------------------
# 审 2（F1 之后）修复：M4/S1 + 补测 T2/T3/T4
# --------------------------------------------------------------------------------------


def test_M4_A人名比对两边都归一():
    # 书里真正的规范名（entities.json / cmap）是「薰儿」，但 scramble 的 --characters
    # 人物名单写的是「萧薰儿」（plant_deaths 拿它当 who、也记进了 names），模型报对了
    # （c.who = "薰儿"）应该算命中——旧实现只把 c.who 过 _canon，p["who"] 原样比较，
    # "薰儿" != "萧薰儿"，会误判没命中。
    key = {"timeline": [{"kind": "A", "who": "萧薰儿", "name": "萧薰儿", "names": ["萧薰儿", "薰儿"], "chapters": [3, 8]}]}
    cmap = {("person", "薰儿"): "薰儿", ("person", "萧薰儿"): "薰儿"}
    res = {"conflicts": [{"kind": "A", "who": "薰儿", "scenes": ["S-0003", "S-0008"]}]}
    assert recall_timeline(key, CH, res, cmap=cmap)["A"]["hit"] == 1


def test_S1_C命中要求ref含想起那日或事件片段():
    key = {"timeline": [{"kind": "C", "who": "岑秀", "event": "比箭连中三箭", "chapters": [5, 9]}]}
    # ref 里没有「想起那日」，也跟事件原文没有 2 字以上重合，场景对上纯属巧合，不该算命中
    res_miss = {"conflicts": [{"kind": "C", "ref": "另一件不相干的事", "scenes": ["S-0005", "S-0009"]}]}
    assert recall_timeline(key, CH, res_miss, cmap={})["C"]["hit"] == 0
    # 含模板短语「想起那日」，算命中
    res_hit1 = {"conflicts": [{"kind": "C", "ref": "岑秀想起那日连中三箭之事", "scenes": ["S-0005", "S-0009"]}]}
    assert recall_timeline(key, CH, res_hit1, cmap={})["C"]["hit"] == 1
    # 没有「想起那日」，但跟事件原文有 2 字以上重合（「连中」），也算命中
    res_hit2 = {"conflicts": [{"kind": "C", "ref": "他清楚记得那次连中的事", "scenes": ["S-0005", "S-0009"]}]}
    assert recall_timeline(key, CH, res_hit2, cmap={})["C"]["hit"] == 1


def test_S1_cause_c的asked也按ref过滤():
    key = {"timeline": [{"kind": "C", "who": "岑秀", "event": "比箭", "chapters": [5, 9]}]}
    base = {"conflicts": [], "dismissed": []}
    # a_sc（S-0005）被问到的是另一条不相干的回指，不该被当成这处植入「问到了」
    r = recall_timeline(key, CH, {**base, "asked_refs": [
        {"scene": "S-0005", "ref": "跟这处植入无关的另一件事", "candidates": ["S-0003"], "happens_in": None}]},
        cmap={}, cards={})
    assert r["C"]["misses"][0]["cause"] == "没问到（回指没抽出来，或候选全在前面）"


def test_T2_A命中要求人名对得上不只是场景对():
    key = {"timeline": [{"kind": "A", "who": "岑秀", "name": "岑秀", "chapters": [3, 8]}]}
    res = {"conflicts": [{"kind": "A", "who": "别人", "scenes": ["S-0003", "S-0008"]}]}
    assert recall_timeline(key, CH, res, cmap={})["A"]["hit"] == 0


def test_T3_及格线_4_5过_3_5不过_0处算过():
    planted5 = [{"kind": "A", "who": f"人{i}", "name": f"人{i}", "chapters": [i, i + 1]} for i in range(5)]
    ch = {i: {f"S-{i:04d}"} for i in range(10)}

    def _conflicts(n):
        return [{"kind": "A", "who": f"人{i}", "scenes": [f"S-{i:04d}", f"S-{i + 1:04d}"]} for i in range(n)]

    assert recall_timeline({"timeline": planted5}, ch, {"conflicts": _conflicts(4)}, cmap={})["A"]["pass"] is True
    assert recall_timeline({"timeline": planted5}, ch, {"conflicts": _conflicts(3)}, cmap={})["A"]["pass"] is False
    assert recall_timeline({"timeline": []}, ch, {"conflicts": []}, cmap={})["A"]["pass"] is True


def test_T4_A类冲突不能被C类结果冒充命中_反之亦然():
    # 特意让「除了 kind 之外」的其它字段都对得上（who / ref），把 kind 这一项本身
    # 单独隔离出来测——不然拿掉 kind 检查之后，别的字段（比如 C 类结果通常没有 who）
    # 恰好也不匹配，测试照样是绿的，测不出 kind 检查被删掉了。
    key_a = {"timeline": [{"kind": "A", "who": "岑秀", "name": "岑秀", "chapters": [3, 8]}]}
    res_a = {"conflicts": [{"kind": "C", "who": "岑秀", "ref": "无关", "scenes": ["S-0003", "S-0008"]}]}
    assert recall_timeline(key_a, CH, res_a, cmap={})["A"]["hit"] == 0

    key_c = {"timeline": [{"kind": "C", "who": "岑秀", "event": "比箭", "chapters": [5, 9]}]}
    res_c = {"conflicts": [{"kind": "A", "who": "岑秀", "ref": "岑秀想起那日比箭之事", "scenes": ["S-0005", "S-0009"]}]}
    assert recall_timeline(key_c, CH, res_c, cmap={})["C"]["hit"] == 0
