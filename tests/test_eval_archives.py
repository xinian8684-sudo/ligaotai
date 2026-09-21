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


import pytest

from tools.eval_archives import recall


def _key(**over):
    p = {"subject": "岑秀", "names": ["岑秀", "岑公子"], "attribute": "年龄",
         "chapters": [3, 8], "ages": [16, 20], "values": ["十六", "二十"]}
    p.update(over)
    return {"contradictions": [p]}


CH = {3: {"S-0005"}, 8: {"S-0009"}}


def _group(**over):
    g = {"id": "C-001", "subject": "岑秀", "attribute": "年龄", "status": "真矛盾", "level": "严重",
         "values": [{"value": "十六", "scenes": [{"id": "S-0005"}]},
                    {"value": "二十", "scenes": [{"id": "S-0009"}]}]}
    g.update(over)
    return {"groups": [g]}


def test_两处说法都被同一组覆盖才算命中():
    """新植入策略下一处矛盾横跨两个章节。只引了其中一处，说明扫描没把两处对比起来，
    那就不算发现了这对矛盾。"""
    res = recall(_key(), CH, _group())
    assert res["hit"] == 1 and res["planted"] == 1 and res["recall"] == 1.0


def test_只覆盖一处不算命中():
    g = _group(values=[{"value": "十六", "scenes": [{"id": "S-0005"}]},
                       {"value": "三十", "scenes": [{"id": "S-0777"}]}])
    assert recall(_key(), CH, g)["hit"] == 0


def test_两处落在同一个值上不算命中():
    """同一个值出现在两章里不是矛盾，是一致。"""
    g = _group(values=[{"value": "十六", "scenes": [{"id": "S-0005"}, {"id": "S-0009"}]}])
    assert recall(_key(), CH, g)["hit"] == 0


def test_属性对不上不算命中():
    assert recall(_key(), CH, _group(attribute="外貌"))["hit"] == 0


def test_无法判断也算命中():
    """作者定了宁可多报，「无法判断」跟「真矛盾」一起显示，所以一起算召回。"""
    assert recall(_key(), CH, _group(status="无法判断"))["hit"] == 1


def test_合理变化不算命中():
    assert recall(_key(), CH, _group(status="合理变化"))["hit"] == 0


def test_主语对不对另外记不影响命中():
    """模型可能用别名称呼（岑公子/岑御史），拿主语当硬判据会冤枉它；
    但主语归错了（上次 ch15 把玉霜娘的话算到小梅名下）是真问题，单独记下来。"""
    res = recall(_key(), CH, _group(subject="小梅"))
    assert res["hit"] == 1
    assert res["subject_mismatch"] == 1

    res2 = recall(_key(), CH, _group(subject="岑公子"))
    assert res2["hit"] == 1 and res2["subject_mismatch"] == 0


def test_旧格式答案硬报错():
    """旧答案文件是 {chapter, old, new}，新判据看的是 {chapters, values}。
    静默算成 0 召回会让人以为是产品不行（I3 的精神：别静默出错数）。"""
    old = {"contradictions": [{"chapter": 3, "attribute": "年龄", "old": "十六", "new": "二十"}]}
    with pytest.raises(SystemExit, match="答案文件是旧格式"):
        recall(old, CH, _group())


def test_没对上植入点的真矛盾单独报_不叫误报():
    """验收语料本身就有自己的矛盾。9-21 真跑报的 3 个「误报」全是书里真有的分歧
    （蘇小姐年龄十八/十六、殷勇兵器鐵鐧/鋼刀、許俊卿位置），一条瞎编的都没有。
    这个字段叫 false_positives 会误导，改名 unmatched_true，报告里写明它不等于误报。"""
    g = {"groups": [
        _group()["groups"][0],
        {"id": "C-002", "subject": "蘇小姐", "attribute": "年龄", "status": "真矛盾", "level": "中等",
         "values": [{"value": "十八", "scenes": [{"id": "S-0100"}]}]}]}
    res = recall(_key(), CH, g)
    assert res["hit"] == 1 and res["unmatched_true"] == 1
    assert "false_positives" not in res


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


# --------------------------------------------------------------------------------------
# C2（9-20 GHIJ 审查）：outdated 的档案不能进 bodies/allowed，也不能让验收报 pass=True
# --------------------------------------------------------------------------------------

import json as _json

from ligaotai.book import Book
from tools.eval_archives import load_scopes_and_bodies, main as eval_main


def _make_book_with_outdated(tmp_path):
    """一本最小的书：一条线是 outdated（模拟步骤 7 跑了一半坏掉，旧档案还留着），
    一条线正常，地图也被标了 outdated + blocked_by。"""
    book = Book(tmp_path)
    (book.thread_archive_dir).mkdir(parents=True, exist_ok=True)
    (book.world_archive_dir).mkdir(parents=True, exist_ok=True)
    book.scenes_dir.mkdir(parents=True, exist_ok=True)
    (book.thread_archive_dir / "L-001.md").write_text(
        "## 来龙去脉\n他救了人 [S-0001]。\n", encoding="utf-8")
    (book.thread_archive_dir / "L-002.md").write_text(
        "## 来龙去脉\n（这是上一轮跑坏之前留下的旧档案）[S-0002]。\n", encoding="utf-8")
    (book.world_archive_dir / "W-01.md").write_text("## 设定\n无引用。\n", encoding="utf-8")
    book.map_path.write_text("## 全书概况\n（上一轮的旧地图）[S-0001]。\n", encoding="utf-8")
    (book.scenes_dir / "S-0001.md").write_text("正文", encoding="utf-8")
    (book.scenes_dir / "S-0002.md").write_text("正文", encoding="utf-8")
    index = {
        "threads": {
            "L-001": {"file": "档案/支线/L-001.md", "scenes": ["S-0001"], "world": "W-01",
                      "outdated": False},
            "L-002": {"file": "档案/支线/L-002.md", "scenes": ["S-0002"], "world": "W-01",
                      "outdated": True},
        },
        "worlds": {"W-01": {"file": "档案/世界/W-01.md", "outdated": False}},
        "map": {"file": "全书地图.md", "outdated": True, "blocked_by": ["L-002"]},
    }
    book.archive_index_path.parent.mkdir(parents=True, exist_ok=True)
    book.archive_index_path.write_text(_json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return book


def test_outdated的线和地图不进bodies(tmp_path):
    book = _make_book_with_outdated(tmp_path)
    bodies, allowed, existing, lenient, outdated = load_scopes_and_bodies(book)
    assert "L-001" in bodies
    assert "L-002" not in bodies  # outdated，旧档案不该被读进来打分
    assert "全书地图" not in bodies  # map 也 outdated
    assert outdated["threads"] == ["L-002"]
    assert outdated["worlds"] == []
    assert outdated["map"] is True
    assert outdated["map_blocked_by"] == ["L-002"]


def test_有outdated档案时main报不通过且退出码非0(tmp_path, capsys):
    """C2 的核心场景：产物目录里全绿（L-001 引用合规），但有一份 outdated 的旧档案，
    验收结果不可信，不能 pass=True、退出码不能是 0。"""
    book = _make_book_with_outdated(tmp_path)
    try:
        eval_main(["--book", str(tmp_path), "--report", str(tmp_path / "验收.json")])
        assert False, "应该以非 0 退出"
    except SystemExit as e:
        assert e.code != 0 and e.code is not None
    report = _json.loads((tmp_path / "验收.json").read_text(encoding="utf-8"))
    assert "outdated" in report
    assert report["outdated"]["threads"] == ["L-002"]


# --------------------------------------------------------------------------------------
# C3（9-20 GHIJ 审查，75c866a 的漏）：小节名判据要跟生成期一样是「前缀/去装饰」，不是「相等」
# --------------------------------------------------------------------------------------

def test_缺口标题带括号也按宽范围核():
    """真数据上模型常写 `## 缺口（3 处）`，生成期 archive.check_archive 认（子串匹配），
    验收不能因为多了个括号就把这段当严格范围核，冤枉合规引用。"""
    body = ("## 来龙去脉\n他救了人 [S-0003]。\n"
            "## 缺口（3 处）\n- 夺宝一事：提到于 [S-0150]\n")
    res = check_refs({"L-001": body}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003", "S-0150"},
                     lenient={"L-001": {"S-0003", "S-0150"}})
    assert res["bad"] == 0, res["details"]


def test_缺口标题带冒号也按宽范围核():
    body = ("## 来龙去脉\n他救了人 [S-0003]。\n"
            "## 缺口：\n- 夺宝一事：提到于 [S-0150]\n")
    res = check_refs({"L-001": body}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003", "S-0150"},
                     lenient={"L-001": {"S-0003", "S-0150"}})
    assert res["bad"] == 0, res["details"]


def test_加粗不带井号的缺口标题也能识别():
    """模型整行只用加粗包住标题、不带 `#`：`**缺口**`。archive.backfill_refs 那边专门
    为这种写法做了去装饰，check_refs 这边原来认不出来，会把这行之后的内容错记到
    上一个小节名下，按错误的范围核。"""
    body = ("## 来龙去脉\n他救了人 [S-0003]。\n"
            "**缺口**\n- 夺宝一事：提到于 [S-0150]\n")
    res = check_refs({"L-001": body}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003", "S-0150"},
                     lenient={"L-001": {"S-0003", "S-0150"}})
    assert res["bad"] == 0, res["details"]


def test_不相关标题带括号不会被当成缺口():
    """前缀匹配不能太松：跟「缺口」不沾边的标题即便带括号，也不该被并入宽范围。"""
    body = "## 人物设定（补充）\n他在别处露过面 [S-0150]。\n"
    res = check_refs({"L-001": body}, allowed={"L-001": {"S-0003"}},
                     existing={"S-0003", "S-0150"},
                     lenient={"L-001": {"S-0003", "S-0150"}})
    assert res["bad"] == 1 and res["details"][0]["why"] == "不属于这份档案"


# --------------------------------------------------------------------------------------
# I1（9-20 GHIJ 审查）：estimate() 原来一个测试都没有（M9/M10/M18/M19 全部漏网）
# --------------------------------------------------------------------------------------

from ligaotai.archive import Inputs
from ligaotai.config import AppConfig
from tools.eval_archives import estimate


def _fake_inputs(thread_chars=1000, n_threads=2, world_chars=2000, n_worlds=1,
                  contra_chars=500, n_batches=1):
    inp = Inputs(unit="年", threads=[], worlds=[], gaps=[], times={})
    inp.thread_text = {f"L-{i:03d}": "字" * thread_chars for i in range(n_threads)}
    inp.world_text = {f"W-{i:02d}": "字" * world_chars for i in range(n_worlds)}
    inp.contra = {"batches": [{"text": "字" * contra_chars} for _ in range(n_batches)]}
    return inp


def test_estimate四项分项都在且总数是分项之和(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.eval_archives.prepare_inputs", lambda book: _fake_inputs())
    est = estimate(Book(tmp_path), AppConfig())
    for key in ("支线档案", "世界设定集", "矛盾扫描", "全书地图"):
        assert key in est and est[key]["usd"] > 0
    assert est["total_usd"] == round(sum(est[k]["usd"] for k in
                                         ("支线档案", "世界设定集", "矛盾扫描", "全书地图")), 4)


def test_estimate输出计价_price_output为0和非0结果不同(monkeypatch, tmp_path):
    """M9：估算里去掉输出 token 那一项。price_output=0 和 price_output=1.2 必须算出不同的钱。"""
    monkeypatch.setattr("tools.eval_archives.prepare_inputs", lambda book: _fake_inputs())
    est_zero = estimate(Book(tmp_path), AppConfig(price_output=0.0))
    est_paid = estimate(Book(tmp_path), AppConfig(price_output=1.2))
    assert est_zero["total_usd"] < est_paid["total_usd"]
    for key in ("支线档案", "世界设定集", "矛盾扫描", "全书地图"):
        assert est_zero[key]["usd"] < est_paid[key]["usd"]


def test_estimate矛盾扫描分项算进总数(monkeypatch, tmp_path):
    """M10：估算漏掉「矛盾扫描」分项。有矛盾批次时总价必须比没有时高。"""
    monkeypatch.setattr("tools.eval_archives.prepare_inputs",
                        lambda book: _fake_inputs(n_batches=0))
    est_no_contra = estimate(Book(tmp_path), AppConfig())
    monkeypatch.setattr("tools.eval_archives.prepare_inputs",
                        lambda book: _fake_inputs(n_batches=1, contra_chars=5000))
    est_with_contra = estimate(Book(tmp_path), AppConfig())
    assert est_no_contra["矛盾扫描"]["usd"] == 0.0
    assert est_with_contra["矛盾扫描"]["usd"] > 0
    assert est_with_contra["total_usd"] > est_no_contra["total_usd"]


def test_estimate全书地图分项算进总数(monkeypatch, tmp_path):
    """M19：估算把「全书地图」一项去掉。地图的 usd 必须 > 0 且计入 total_usd。"""
    monkeypatch.setattr("tools.eval_archives.prepare_inputs", lambda book: _fake_inputs())
    est = estimate(Book(tmp_path), AppConfig())
    assert est["全书地图"]["usd"] > 0
    others = sum(est[k]["usd"] for k in ("支线档案", "世界设定集", "矛盾扫描"))
    assert est["total_usd"] > round(others, 4)


def test_estimate输出按maxtokens封顶(monkeypatch, tmp_path):
    """I1：单次调用的输出不能超过 synth.max_tokens，大输入不该被当成「输出=输入×1.0」
    不封顶地算钱——世界设定集/全书地图这种大文本会被高估好几倍。"""
    cfg = AppConfig()
    cap = cfg.synth.max_tokens
    big = cap * 3  # 远超封顶
    monkeypatch.setattr("tools.eval_archives.prepare_inputs",
                        lambda book: _fake_inputs(world_chars=big, n_worlds=1,
                                                  n_threads=0, n_batches=0))
    est = estimate(Book(tmp_path), AppConfig(price_input=0.0))  # 只看输出那一项
    expected_output_usd = round(cap * cfg.price_output / 1e6 * est["retry_factor"], 4)
    assert est["世界设定集"]["usd"] == expected_output_usd


def test_estimate带重试系数(monkeypatch, tmp_path):
    """I1：不算重试会把钱估低——llm.py 的 MAX_ATTEMPTS=3、超长还会翻倍重调。
    estimate() 必须报出用了多大的重试系数，且系数 > 1。"""
    monkeypatch.setattr("tools.eval_archives.prepare_inputs", lambda book: _fake_inputs())
    est = estimate(Book(tmp_path), AppConfig())
    assert est["retry_factor"] > 1.0


def test_门槛常量没被改动():
    """M18：门槛常量全拉满（2%→100%、10%→100%、0.8→0.0）也没有测试报警。"""
    from tools.eval_archives import FABRICATED_LIMIT, NO_REF_LIMIT, RECALL_FLOOR
    assert (FABRICATED_LIMIT, NO_REF_LIMIT, RECALL_FLOOR) == (0.02, 0.10, 0.8)


def test_编造率超门槛时main退出码非0(tmp_path):
    """端到端：编号不存在（编造）超过 2% 门槛，main() 必须以非 0 退出，不能悄悄 pass。"""
    from tools.eval_archives import main as eval_main
    book = Book(tmp_path)
    book.thread_archive_dir.mkdir(parents=True, exist_ok=True)
    book.scenes_dir.mkdir(parents=True, exist_ok=True)
    (book.thread_archive_dir / "L-001.md").write_text(
        "## 来龙去脉\n他救了人 [S-9999]。\n", encoding="utf-8")  # S-9999 不存在，编造
    (book.scenes_dir / "S-0001.md").write_text("正文", encoding="utf-8")
    index = {"threads": {"L-001": {"file": "档案/支线/L-001.md", "scenes": ["S-0001"],
                                    "world": "", "outdated": False}}}
    book.archive_index_path.parent.mkdir(parents=True, exist_ok=True)
    book.archive_index_path.write_text(_json.dumps(index, ensure_ascii=False), encoding="utf-8")
    try:
        eval_main(["--book", str(tmp_path), "--report", str(tmp_path / "验收.json")])
        assert False, "编造率超门槛应该以非 0 退出"
    except SystemExit as e:
        assert e.code != 0 and e.code is not None


# --------------------------------------------------------------------------------------
# I3（9-20 GHIJ 审查）：答案文件没有 contradictions / --folder 传错时不能静默出错数
# --------------------------------------------------------------------------------------

def test_答案文件没有contradictions键时硬报错(tmp_path):
    """仓库里现有的旧答案文件就没有 contradictions 键（加这功能之前生成的）。拿它跑
    验收不能打印 recall=0.0 pass=True——那是假通过，得硬报错逼着换一份带矛盾的答案。"""
    from tools.eval_archives import main as eval_main
    book = Book(tmp_path)
    book.thread_archive_dir.mkdir(parents=True, exist_ok=True)
    book.scenes_dir.mkdir(parents=True, exist_ok=True)
    (book.thread_archive_dir / "L-001.md").write_text("## 来龙去脉\n他救了人 [S-0001]。\n",
                                                        encoding="utf-8")
    (book.scenes_dir / "S-0001.md").write_text("正文", encoding="utf-8")
    index = {"threads": {"L-001": {"file": "档案/支线/L-001.md", "scenes": ["S-0001"],
                                    "world": "", "outdated": False}}}
    book.archive_index_path.parent.mkdir(parents=True, exist_ok=True)
    book.archive_index_path.write_text(_json.dumps(index, ensure_ascii=False), encoding="utf-8")
    key_path = tmp_path / "旧答案.json"
    key_path.write_text(_json.dumps({"seed": 1, "files": []}), encoding="utf-8")  # 没有 contradictions 键
    try:
        eval_main(["--book", str(tmp_path), "--key", str(key_path), "--folder", "乱稿",
                  "--report", str(tmp_path / "验收.json")])
        assert False, "没有 contradictions 键应该直接报错退出，不能悄悄 pass"
    except SystemExit as e:
        assert e.code != 0 and "contradictions" in str(e.code)


def test_folder传错导致chapter_scenes全空时硬报错(tmp_path):
    """--folder 传错时 truth_positions 的 by_path 一个都对不上，chapter_scenes 全空，
    recall 会静默变 0——这跟「答案文件没有 contradictions」是两种完全不同的 0，
    不能都表现成看不出原因的 pass=False/pass=True。"""
    from ligaotai.scenes import Scene, write_scene
    from tools.eval_archives import main as eval_main
    book = Book(tmp_path)
    book.thread_archive_dir.mkdir(parents=True, exist_ok=True)
    book.scenes_dir.mkdir(parents=True, exist_ok=True)
    (book.thread_archive_dir / "L-001.md").write_text("## 来龙去脉\n他救了人 [S-0001]。\n",
                                                        encoding="utf-8")
    write_scene(book, Scene(id="S-0001", source="真实乱稿文件夹/x.txt", index=1,
                            start=0, end=2, chars=2, hash="h", text="正文"))
    index = {"threads": {"L-001": {"file": "档案/支线/L-001.md", "scenes": ["S-0001"],
                                    "world": "", "outdated": False}}}
    book.archive_index_path.parent.mkdir(parents=True, exist_ok=True)
    book.archive_index_path.write_text(_json.dumps(index, ensure_ascii=False), encoding="utf-8")
    key_path = tmp_path / "答案.json"
    key_path.write_text(_json.dumps({
        "seed": 1, "files": [{"path": "x.txt", "chapter": 1, "piece": 1, "pieces": 1, "kind": "original"}],
        "contradictions": [{"chapter": 1, "subject": "x", "attribute": "兵器", "old": "a", "new": "b"}],
    }), encoding="utf-8")
    try:
        eval_main(["--book", str(tmp_path), "--key", str(key_path), "--folder", "不存在的乱稿文件夹",
                  "--report", str(tmp_path / "验收.json")])
        assert False, "--folder 传错、chapter_scenes 全空时应该直接报错退出"
    except SystemExit as e:
        assert e.code != 0 and "folder" in str(e.code)
