from tools.eval_archives import check_refs, sentences


def test_按句切分带编号的正文():
    text = "他救了人 [S-0003]。后来去了青州 [S-0004]。天气很好。"
    assert len(sentences(text)) == 3


def test_标题行不算结论句():
    text = "# L-001 林清线\n## 来龙去脉\n他救了人 [S-0003]。"
    assert len(sentences(text)) == 1


def test_编号不存在算编造():
    res = check_refs({"L-001": "他救了人 [S-9999]。"}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003"})
    assert res["bad"] == 1 and res["total"] == 1
    assert res["fabricated_rate"] == 1.0


def test_编号存在但不属于这条线也算不合格():
    res = check_refs({"L-001": "他救了人 [S-0007]。"}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003", "S-0007"})
    assert res["bad"] == 1
    assert res["details"][0]["why"] == "不属于这份档案"


def test_无引用句率():
    res = check_refs({"L-001": "他救了人 [S-0003]。天气很好。"},
                     allowed={"L-001": {"S-0003"}}, existing={"S-0003"})
    assert res["sentences"] == 2 and res["no_ref"] == 1
    assert res["no_ref_rate"] == 0.5


def test_全部合格时两个率都是0():
    res = check_refs({"L-001": "他救了人 [S-0003]。"}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003"})
    assert res["fabricated_rate"] == 0.0 and res["no_ref_rate"] == 0.0


# 缺口小节的「提到于 [S-xxxx]」合法地可能不属于这条线——缺口就是「书里找不到对应场景
# 的事件」，提到它的那个场景常常在别的线上，而且这个编号是程序渲染进输入材料、明确发给
# 模型的（prompts/archive_thread.md 的「## 缺口」行、archive.py 的 thread_scope 也是
# 这么算的）。拿 spec 9.2 的严格归属去核这一段，会把合规引用judgment成编造。
# 开放的伏笔同理。正文其余小节仍然严格按本线核。

def test_缺口小节引用别的线的场景不算编造():
    body = ("## 来龙去脉\n他救了人 [S-0003]。\n"
            "## 缺口\n- 夺宝一事：提到于 [S-0150]，位置大约在 [S-0003] 之后\n")
    res = check_refs({"L-001": body}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003", "S-0150"},
                     lenient={"L-001": {"S-0003", "S-0150"}})
    assert res["bad"] == 0, res["details"]


def test_开放的伏笔小节同样按宽范围核():
    body = "## 开放的伏笔\n- 那封信：埋于 [S-0150]，至今没回收\n"
    res = check_refs({"L-001": body}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003", "S-0150"},
                     lenient={"L-001": {"S-0003", "S-0150"}})
    assert res["bad"] == 0


def test_宽范围只管那两个小节_来龙去脉还是严格按本线核():
    body = ("## 来龙去脉\n他在别处露过面 [S-0150]。\n"
            "## 缺口\n- 夺宝一事：提到于 [S-0150]\n")
    res = check_refs({"L-001": body}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003", "S-0150"},
                     lenient={"L-001": {"S-0003", "S-0150"}})
    assert res["bad"] == 1, "来龙去脉里的越界引用必须照抓"
    assert res["details"][0]["why"] == "不属于这份档案"


def test_缺口小节里编造出来的编号照样抓():
    body = "## 缺口\n- 夺宝一事：提到于 [S-9999]\n"
    res = check_refs({"L-001": body}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003", "S-0150"},
                     lenient={"L-001": {"S-0003", "S-0150"}})
    assert res["bad"] == 1 and res["details"][0]["why"] == "编号不存在"


def test_不给lenient时行为跟以前一模一样():
    body = "## 缺口\n- 夺宝一事：提到于 [S-0150]\n"
    res = check_refs({"L-001": body}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003", "S-0150"})
    assert res["bad"] == 1


from tools.eval_archives import recall


def test_命中判据是场景编号加属性():
    key = {"contradictions": [{"chapter": 3, "attribute": "兵器", "old": "金箍棒", "new": "降妖宝杖"}]}
    chapter_scenes = {3: {"S-0005", "S-0006"}}
    result = {"groups": [{"id": "C-001", "subject": "孙悟空", "attribute": "兵器",
                          "status": "真矛盾", "level": "严重",
                          "values": [{"value": "金箍棒", "scenes": [{"id": "S-0005"}]},
                                     {"value": "降妖宝杖", "scenes": [{"id": "S-0099"}]}]}]}
    res = recall(key, chapter_scenes, result)
    assert res["hit"] == 1 and res["planted"] == 1
    assert res["recall"] == 1.0


def test_属性对不上不算命中():
    key = {"contradictions": [{"chapter": 3, "attribute": "兵器", "old": "金箍棒", "new": "降妖宝杖"}]}
    result = {"groups": [{"id": "C-001", "subject": "孙悟空", "attribute": "外貌",
                          "status": "真矛盾", "level": "严重",
                          "values": [{"value": "x", "scenes": [{"id": "S-0005"}]}]}]}
    assert recall(key, {3: {"S-0005"}}, result)["hit"] == 0


def test_无法判断也算命中():
    """作者定了宁可多报，「无法判断」跟「真矛盾」一起显示，所以一起算召回。"""
    key = {"contradictions": [{"chapter": 3, "attribute": "兵器", "old": "a", "new": "b"}]}
    result = {"groups": [{"id": "C-001", "subject": "x", "attribute": "兵器",
                          "status": "无法判断", "level": "",
                          "values": [{"value": "a", "scenes": [{"id": "S-0005"}]}]}]}
    assert recall(key, {3: {"S-0005"}}, result)["hit"] == 1


def test_合理变化不算命中():
    key = {"contradictions": [{"chapter": 3, "attribute": "兵器", "old": "a", "new": "b"}]}
    result = {"groups": [{"id": "C-001", "subject": "x", "attribute": "兵器",
                          "status": "合理变化", "level": "",
                          "values": [{"value": "a", "scenes": [{"id": "S-0005"}]}]}]}
    assert recall(key, {3: {"S-0005"}}, result)["hit"] == 0


def test_误报只报数():
    key = {"contradictions": [{"chapter": 3, "attribute": "兵器", "old": "a", "new": "b"}]}
    result = {"groups": [
        {"id": "C-001", "subject": "x", "attribute": "兵器", "status": "真矛盾", "level": "严重",
         "values": [{"value": "a", "scenes": [{"id": "S-0005"}]}]},
        {"id": "C-002", "subject": "y", "attribute": "外貌", "status": "真矛盾", "level": "中等",
         "values": [{"value": "c", "scenes": [{"id": "S-0100"}]}]}]}
    res = recall(key, {3: {"S-0005"}}, result)
    assert res["hit"] == 1 and res["false_positives"] == 1


from tools.eval_archives import sample_for_review


def test_抽查材料是结论句配原文():
    bodies = {"L-001": "他救了人 [S-0003]。后来去了青州 [S-0004]。"}
    scenes = {"S-0003": "林清救下受伤的赵五。", "S-0004": "林清一路行至青州。"}
    import random
    md = sample_for_review(bodies, scenes, random.Random(1), n=2)
    assert "他救了人" in md and "林清救下受伤的赵五" in md
    assert "S-0003" in md


def test_抽查只抽带编号的句子():
    bodies = {"L-001": "天气很好。他救了人 [S-0003]。"}
    scenes = {"S-0003": "林清救下受伤的赵五。"}
    import random
    md = sample_for_review(bodies, scenes, random.Random(1), n=5)
    assert "天气很好" not in md


def test_抽不满n条就有几条给几条():
    bodies = {"L-001": "他救了人 [S-0003]。"}
    import random
    md = sample_for_review(bodies, {"S-0003": "原文"}, random.Random(1), n=10)
    assert md.count("## 第") == 1
