from ligaotai.chapters import (
    assemble,
    check_chapters,
    fallback_chapters,
    merge_windows,
    render_rows,
    windows,
)


def _scene(sid, thread="L-001"):
    return {"type": "scene", "id": sid, "thread": thread}


def test_渲染行_场景和空洞_序号从0开始():
    items = [_scene("S-0001"), {"type": "hole", "id": "H-001", "thread": "L-001", "event": "大闹\n天宫"}]
    info = {"S-0001": {"chars": 1200, "summary": "开篇\n两行"}}
    assert render_rows(items, info) == ["0｜S-0001｜L-001｜1200｜开篇 两行", "1｜空洞｜L-001｜0｜大闹 天宫"]


def test_核对分章():
    ok = {"volumes": [{"title": "卷一", "start": 0}], "chapters": [{"title": "甲", "start": 0}, {"title": "乙", "start": 3}]}
    assert check_chapters(ok, 5) == []
    cases = [
        ({"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "甲", "start": 1}]}, "0"),
        ({"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "甲", "start": 0}, {"title": "乙", "start": 0}]}, "递增"),
        ({"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "甲", "start": 0}, {"title": "乙", "start": 9}]}, "0 到 4"),
        ({"volumes": [{"title": "卷", "start": 0}, {"title": "卷二", "start": 2}], "chapters": [{"title": "甲", "start": 0}, {"title": "乙", "start": 3}]}, "卷的起点"),
        ({"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "", "start": 0}]}, "标题"),
        ({"chapters": [{"title": "甲", "start": 0}]}, "volumes"),
        ({"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": "甲", "start": "0"}]}, "整数"),
    ]
    for data, word in cases:
        assert any(word in p for p in check_chapters(data, 5)), (data, check_chapters(data, 5))


def test_核对分章_标题不是字符串不该被当成有效标题():
    # M2：旧代码用 str(title or "").strip() 判断「有没有标题」，["甲"] 这种非字符串会被
    # str() 硬转成非空字符串蒙混过去，写进骨架后 assemble() 原样落地就是个列表。
    bad = {"volumes": [{"title": "卷", "start": 0}], "chapters": [{"title": ["甲"], "start": 0}]}
    assert any("标题" in p for p in check_chapters(bad, 3))


def test_兜底切法_每章约一万字_每卷若干章():
    items = [_scene(f"S-000{i}") for i in range(1, 6)]
    info = {f"S-000{i}": {"chars": 6000, "summary": f"第{i}块的摘要很长很长很长"} for i in range(1, 6)}
    d = fallback_chapters(items, info)
    assert [c["start"] for c in d["chapters"]] == [0, 2, 4]
    assert d["chapters"][0]["title"] == "第1块的摘要很长很长很长"[:12]
    assert d["volumes"] == [{"title": "第1卷", "start": 0}]
    d2 = fallback_chapters(items, info, per_volume=2)
    assert [v["start"] for v in d2["volumes"]] == [0, 4]
    assert check_chapters(d, 5) == []


def test_兜底切法_空洞当章首_空列表():
    items = [{"type": "hole", "id": "H-001", "event": "x"}]
    assert fallback_chapters(items, {})["chapters"] == [{"title": "空洞", "start": 0}]
    assert fallback_chapters([], {}) == {"volumes": [], "chapters": []}


def test_窗口切分_相邻窗口重叠():
    rows = ["x" * 9] * 25          # 每行 9 字 + 换行 = 10
    assert windows(rows, 100, overlap=3) == [(0, 10), (7, 17), (14, 24), (21, 25)]
    assert windows(rows, 10_000, overlap=3) == [(0, 25)]
    assert windows([], 100) == []
    assert windows(["x" * 500] * 5, 100, overlap=2) == [(0, 3), (1, 4), (2, 5)]  # 单行超预算也要往前走


def test_合并窗口_重叠区按中点切_卷起点对齐到章起点():
    results = [
        (0, 12, {"chapters": [{"title": "a", "start": 0}, {"title": "b", "start": 6}, {"title": "c", "start": 11}],
                 "volumes": [{"title": "v1", "start": 0}]}),
        (8, 20, {"chapters": [{"title": "x", "start": 0}, {"title": "y", "start": 3}, {"title": "z", "start": 8}],
                 "volumes": [{"title": "v2", "start": 0}, {"title": "v3", "start": 3}]}),
    ]
    d = merge_windows(results, 20, overlap=4)
    assert [(c["title"], c["start"]) for c in d["chapters"]] == [("a", 0), ("b", 6), ("y", 11), ("z", 16)]
    assert [(v["title"], v["start"]) for v in d["volumes"]] == [("v1", 0), ("v3", 11)]
    assert check_chapters(d, 20) == []


def test_组装成卷章():
    items = [_scene(f"S-000{i}") for i in range(1, 6)]
    d = {"volumes": [{"title": "上", "start": 0}, {"title": "下", "start": 3}],
         "chapters": [{"title": "一", "start": 0}, {"title": "二", "start": 2}, {"title": "三", "start": 3}]}
    vols = assemble(items, d)
    assert [v["title"] for v in vols] == ["上", "下"]
    assert [[c["title"] for c in v["chapters"]] for v in vols] == [["一", "二"], ["三"]]
    assert [i["id"] for i in vols[0]["chapters"][1]["items"]] == ["S-0003"]
    assert [i["id"] for i in vols[1]["chapters"][0]["items"]] == ["S-0004", "S-0005"]
    assert vols[0]["chapters"][0]["notes"] == []


def test_组装成卷章_标题里的换行折成一行():
    # M2：模型回的标题夹带换行（甚至一个冒充的 Markdown 标题符号），写进骨架前要折成一行，
    # 不然导出 md 时会被当成一个额外的一级/二级标题，跟真正的卷章标题混在一起。
    items = [_scene("S-0001")]
    d = {"volumes": [{"title": "上\n卷", "start": 0}],
         "chapters": [{"title": "开篇\n# 冒充的标题", "start": 0}]}
    vols = assemble(items, d)
    assert vols[0]["title"] == "上 卷"
    assert vols[0]["chapters"][0]["title"] == "开篇 # 冒充的标题"
