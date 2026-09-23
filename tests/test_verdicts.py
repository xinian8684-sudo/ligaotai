import pytest

from ligaotai.contradictions import build_result
from ligaotai.fsutil import read_json, write_json
from ligaotai.verdicts import (
    BrokenContradictions,
    NoSuchGroup,
    current_canon,
    followups,
    set_verdict,
)


def _group(values_sig="sig1", **kw):
    g = {
        "id": "C-001", "subject": "小梅", "attribute": "年龄", "status": "真矛盾", "level": "严重",
        "category": "人物", "reason": "对不上 [S-0001]",
        "values": [
            {"value": "十三", "scenes": [{"id": "S-0001", "quote": "年方十三", "thread": "L-001", "t": 0, "conf": "高"}]},
            {"value": "十七", "scenes": [
                {"id": "S-0002", "quote": "今年十七", "thread": "L-001", "t": 1, "conf": "中"},
                {"id": "S-0003", "quote": "十七歲", "thread": "L-002", "t": 2, "conf": "中"}]},
        ],
        "values_sig": values_sig, "verdict": None, "verdict_sig": None, "verdict_stale": False,
    }
    g.update(kw)
    return g


@pytest.fixture
def cbook(book):
    write_json(book.contradictions_path, {"groups": [_group()], "stats": {}, "next_id": 2,
                                          "id_registry": [{"subject": "小梅", "attribute": "年龄", "id": "C-001"}]})
    return book


def test_以某个值为准_写进verdict并记下判定依据(cbook):
    g = set_verdict(cbook, "C-001", "pick", "十三")
    assert g["verdict"]["kind"] == "pick"
    assert g["verdict"]["value"] == "十三"
    assert g["verdict"]["by"] == "author"
    assert g["verdict_sig"] == "sig1"
    assert g["verdict_stale"] is False
    on_disk = read_json(cbook.contradictions_path)["groups"][0]
    assert on_disk["verdict"]["value"] == "十三"


def test_以某个值为准_值必须是这一组里的(cbook):
    with pytest.raises(ValueError):
        set_verdict(cbook, "C-001", "pick", "十八")


def test_自己写_不能为空(cbook):
    with pytest.raises(ValueError):
        set_verdict(cbook, "C-001", "own", "   ")


def test_裁决种类不认识就拒绝(cbook):
    with pytest.raises(ValueError):
        set_verdict(cbook, "C-001", "guess", "十三")


def test_定稿设定_pick带支持这个值的场景_own不带(cbook):
    set_verdict(cbook, "C-001", "pick", "十七")
    canon = read_json(cbook.canon_path)
    assert canon["items"] == [{"id": "C-001", "subject": "小梅", "attribute": "年龄", "value": "十七",
                               "sources": ["S-0002", "S-0003"], "note": ""}]
    set_verdict(cbook, "C-001", "own", "十五", note="按第三回改")
    canon = read_json(cbook.canon_path)
    assert canon["items"][0]["value"] == "十五"
    assert canon["items"][0]["sources"] == []
    assert canon["items"][0]["note"] == "按第三回改"


def test_先放着和撤销都不进定稿设定(cbook):
    set_verdict(cbook, "C-001", "later")
    assert read_json(cbook.canon_path)["items"] == []
    set_verdict(cbook, "C-001", "pick", "十三")
    g = set_verdict(cbook, "C-001", None)
    assert g["verdict"] is None and g["verdict_sig"] is None
    assert read_json(cbook.canon_path)["items"] == []


def test_stale的裁决不进定稿设定_重新裁决清掉stale(book):
    write_json(book.contradictions_path, {"groups": [_group(
        verdict={"kind": "pick", "value": "十三", "note": "", "by": "author", "at": "x"},
        verdict_sig="old", verdict_stale=True)], "stats": {}})
    assert current_canon(book)["items"] == []
    g = set_verdict(book, "C-001", "pick", "十三")
    assert g["verdict_stale"] is False
    assert [i["id"] for i in current_canon(book)["items"]] == ["C-001"]


def test_current_canon_发现文件跟裁决对不上就重写(cbook):
    set_verdict(cbook, "C-001", "pick", "十三")
    write_json(cbook.canon_path, {"generated": "x", "items": []})  # 模拟步骤 7 重跑后文件过时
    c = current_canon(cbook)
    assert [i["value"] for i in c["items"]] == ["十三"]
    assert [i["value"] for i in read_json(cbook.canon_path)["items"]] == ["十三"]


def test_要跟着改的场景_列出其他值出现的地方(cbook):
    set_verdict(cbook, "C-001", "pick", "十三")
    f = followups(cbook, "C-001")
    assert [(s["id"], s["value"]) for s in f["scenes"]] == [("S-0002", "十七"), ("S-0003", "十七")]
    assert f["scenes"][0]["quote"] == "今年十七"


def test_要跟着改的场景_自己写时每个值的场景都要改(cbook):
    set_verdict(cbook, "C-001", "own", "十五")
    assert [s["id"] for s in followups(cbook, "C-001")["scenes"]] == ["S-0001", "S-0002", "S-0003"]


def test_要跟着改的场景_没裁决时为空(cbook):
    assert followups(cbook, "C-001")["scenes"] == []


def test_值写法变了但签名没变_定稿设定和followups按norm_number比对(book):
    """R1：values_sig 用 facts.norm_number 规范化过的值算签名（步骤7 contradictions.values_sig
    同一套逻辑）；canon_items / followups 原来直接比原字符串，值的代表写法从「十六」变成
    「16」时（签名不变，判定不标 stale）会一条都对不上——定稿设定丢了出处场景，
    followups 把选中值自己的场景也当成「要跟着改」报出来。"""
    from ligaotai.contradictions import values_sig

    values = [
        {"value": "十六", "scenes": [{"id": "S-0001", "quote": "年方十六", "thread": "L-001", "t": 0, "conf": "高"}]},
        {"value": "十七", "scenes": [{"id": "S-0002", "quote": "今年十七", "thread": "L-001", "t": 1, "conf": "中"}]},
    ]
    sig = values_sig(values)
    write_json(book.contradictions_path, {"groups": [{
        "id": "C-001", "subject": "小梅", "attribute": "年龄", "status": "真矛盾", "level": "严重",
        "category": "人物", "reason": "r [S-0001]", "values": values, "values_sig": sig,
        "verdict": None, "verdict_sig": None, "verdict_stale": False}], "stats": {}})
    set_verdict(book, "C-001", "pick", "十六")
    # 模拟步骤 7 重跑：组里「十六」的代表写法换成了「16」，规范化后签名没变
    data = read_json(book.contradictions_path)
    data["groups"][0]["values"][0]["value"] = "16"
    assert values_sig(data["groups"][0]["values"]) == sig
    write_json(book.contradictions_path, data)
    canon = current_canon(book)
    assert canon["items"][0]["value"] == "十六"
    assert canon["items"][0]["sources"] == ["S-0001"]
    f = followups(book, "C-001")
    assert [s["id"] for s in f["scenes"]] == ["S-0002"]


def test_没有矛盾文件和编号不存在(book, cbook):
    with pytest.raises(NoSuchGroup):
        set_verdict(cbook, "C-999", "later")


def test_没跑过步骤7(book):
    with pytest.raises(FileNotFoundError):
        set_verdict(book, "C-001", "later")


def test_矛盾文件坏了(book):
    book.contradictions_path.write_text("{坏", encoding="utf-8")
    with pytest.raises(BrokenContradictions):
        set_verdict(book, "C-001", "later")


def _cand(values):
    return {"subject": "小梅", "attribute": "年龄", "merged": 0,
            "values": [{"value": v, "scenes": [{"id": s, "quote": "q"}]} for v, s in values]}


def test_跟步骤7的迁移联动_值没变裁决保留_值变了标stale(book):
    """真实契约：裁决写进去之后，contradictions.build_result 重跑能原样接回；多了新值要标 stale。"""
    first = build_result([_cand([("十三", "S-0001"), ("十七", "S-0002")])], {}, {}, {}, {})
    write_json(book.contradictions_path, first)
    set_verdict(book, first["groups"][0]["id"], "pick", "十三")
    old = read_json(book.contradictions_path)
    again = build_result([_cand([("十三", "S-0001"), ("十七", "S-0002")])], {}, {}, old, {})
    g = again["groups"][0]
    assert g["verdict"]["value"] == "十三" and g["verdict_stale"] is False
    changed = build_result([_cand([("十三", "S-0001"), ("十七", "S-0002"), ("十八", "S-0003")])], {}, {}, old, {})
    assert changed["groups"][0]["verdict_stale"] is True
