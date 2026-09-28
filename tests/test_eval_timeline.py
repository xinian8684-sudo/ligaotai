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
