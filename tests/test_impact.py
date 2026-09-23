import json

import pytest

from helpers import FakeBackend

from ligaotai.cards import card_path
from ligaotai.config import AppConfig
from ligaotai.fsutil import read_json, write_json
from ligaotai.impact import check_impact, impact_input, model_impact_status, program_impact, run_impact
from ligaotai.llm import LLMClient
from ligaotai.threads_ops import load_threads
from ligaotai.triage import set_card


def _set_card(book, sid, **changes):
    rec = read_json(card_path(book, sid))
    rec["card"].update(changes)
    write_json(card_path(book, sid), rec)


@pytest.fixture
def ib(book_with_threads):
    b = book_with_threads
    data = read_json(b.threads_path)
    data["intersections"] = [{"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "龙宫借宝"}]
    write_json(b.threads_path, data)
    # 主线 S-0001 提到了支线独有人物敖广（「敖广」是规范名本身）
    _set_card(b, "S-0001", refs_elsewhere=["敖广献宝的旧事", "五行山的来历"])
    return b


def test_支线的交汇点_对方是主线(ib):
    r = program_impact(ib, load_threads(ib), "L-002")
    assert r["crossings"] == [{"other": "L-001", "scene": "S-0004", "main_scene": "S-0002", "reason": "龙宫借宝"}]


def test_主线的交汇点_对方是支线(ib):
    r = program_impact(ib, load_threads(ib), "L-001")
    assert r["crossings"] == [{"other": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "龙宫借宝"}]


def test_只在这条线出场的人物_用规范名归一(ib):
    assert program_impact(ib, load_threads(ib), "L-002")["only_characters"] == [
        {"name": "敖广", "scenes": ["S-0004", "S-0005"]}]
    # 「悟空」「行者」归到规范名 孙悟空，只在 L-001 出场
    assert program_impact(ib, load_threads(ib), "L-001")["only_characters"] == [
        {"name": "孙悟空", "scenes": ["S-0001", "S-0002", "S-0003"]}]


def test_别的线提到独有人物_算可能的引用(ib):
    refs = program_impact(ib, load_threads(ib), "L-002")["maybe_refs"]
    assert refs == [{"scene": "S-0001", "thread": "L-001", "text": "敖广献宝的旧事", "names": ["敖广"]}]


def test_人物在两条线都出场就不算独有(ib):
    _set_card(ib, "S-0001", characters=[{"name": "悟空", "role": "主要"}, {"name": "敖广", "role": "提及"}])
    assert program_impact(ib, load_threads(ib), "L-002")["only_characters"] == []


def test_提及角色不算独有人物(ib):
    # 「打杂的」只在 L-002 出场，但角色是「提及」，不是「主要/次要」——不该进 only_characters
    _set_card(ib, "S-0004", characters=[{"name": "敖广", "role": "主要"}, {"name": "打杂的", "role": "提及"}])
    names = [c["name"] for c in program_impact(ib, load_threads(ib), "L-002")["only_characters"]]
    assert names == ["敖广"]
    assert "打杂的" not in names


def test_代词不算人物(ib):
    _set_card(ib, "S-0004", characters=[{"name": "我", "role": "主要"}, {"name": "敖广", "role": "主要"}])
    names = [c["name"] for c in program_impact(ib, load_threads(ib), "L-002")["only_characters"]]
    assert names == ["敖广"]


def test_线不存在(ib):
    with pytest.raises(KeyError):
        program_impact(ib, load_threads(ib), "L-009")


def _hooks(b):
    # S-0002（L-001）埋「紧箍咒的来历」（fixture 自带）；S-0004（L-002）回收它；S-0005 埋一个没人收的
    _set_card(b, "S-0004", hooks_resolved=["紧箍咒原来是观音所赐"])
    _set_card(b, "S-0005", hooks_planted=["定海神针的去向"])


def test_输入_这条线和其他线分开列_带动作(ib):
    _hooks(ib)
    th = load_threads(ib)
    set_card(ib, th, "L-002", "cut")
    values, own, others = impact_input(ib, th, "L-002")
    assert "砍掉 L-002" in values["action"]
    assert "S-0004｜收｜紧箍咒原来是观音所赐" in values["own"]
    assert "S-0005｜埋｜定海神针的去向" in values["own"]
    assert "L-001｜S-0002｜埋｜紧箍咒的来历" in values["others"]
    assert own == {"S-0004", "S-0005"} and others == {"S-0002"}


def test_合并时动作写明并入哪条线(ib):
    th = load_threads(ib)
    set_card(ib, th, "L-002", "merge", merge_into="L-001")
    values, _, _ = impact_input(ib, load_threads(ib), "L-002")
    assert "把 L-002 并入 L-001" in values["action"]


def test_被砍的线不算其他线(ib):
    _hooks(ib)
    th = load_threads(ib)
    set_card(ib, th, "L-001", "cut")
    set_card(ib, th, "L-002", "cut")
    _, _, others = impact_input(ib, th, "L-002")
    assert others == set()


def test_核对_编号不是字符串不炸_报问题而不是抛异常(ib):
    own, others = {"S-0004", "S-0005"}, {"S-0002"}
    bad = {"pairs": [{"planted": ["S-0002"], "resolved": "S-0004", "hook": "紧箍咒"}],
           "remedy": "改到主线收 [S-0002]"}
    problems = check_impact(bad, own, others)  # 不该抛 TypeError: unhashable type: 'list'
    assert any("不对" in p for p in problems)


def test_模型第一次回不可哈希的编号_重试后成功(ib):
    _hooks(ib)
    th = load_threads(ib)
    set_card(ib, th, "L-002", "cut")
    bad = json.dumps({"pairs": [{"planted": ["S-0002"], "resolved": "S-0004", "hook": "紧箍咒"}],
                      "remedy": "改到主线收 [S-0002]"}, ensure_ascii=False)
    good = json.dumps({"pairs": [{"planted": "S-0002", "resolved": "S-0004", "hook": "紧箍咒"}],
                       "remedy": "改到主线收 [S-0002]"}, ensure_ascii=False)
    backend = FakeBackend(replies=[bad, good])
    r = run_impact(ib, LLMClient(AppConfig(), backend, log_dir=ib.logs_dir), "L-002")
    assert r["ok"] is True
    assert len(backend.calls) == 2


def test_核对_两端要一端在这条线一端在别的线(ib):
    own, others = {"S-0004", "S-0005"}, {"S-0002"}
    ok = {"pairs": [{"planted": "S-0002", "resolved": "S-0004", "hook": "紧箍咒"}], "remedy": "改到主线收 [S-0002]"}
    assert check_impact(ok, own, others) == []
    bad = {"pairs": [{"planted": "S-0004", "resolved": "S-0005", "hook": "x"},
                     {"planted": "S-0002", "resolved": "S-0099", "hook": "y"}],
           "remedy": "没编号"}
    text = "\n".join(check_impact(bad, own, others))
    assert "S-0004" in text and "S-0099" in text and "补救建议" in text


def test_跑一次_结果存影响文件_看板动作变了就过期(ib):
    _hooks(ib)
    th = load_threads(ib)
    set_card(ib, th, "L-002", "cut")
    reply = {"pairs": [{"planted": "S-0002", "resolved": "S-0004", "hook": "紧箍咒"}], "remedy": "改到主线收 [S-0002]"}
    backend = FakeBackend(handler=lambda tier, messages: json.dumps(reply, ensure_ascii=False))
    r = run_impact(ib, LLMClient(AppConfig(), backend, log_dir=ib.logs_dir), "L-002")
    assert r["ok"] is True
    st = model_impact_status(ib, load_threads(ib), "L-002")
    assert st["stale"] is False and st["pairs"][0]["resolved"] == "S-0004"
    set_card(ib, th, "L-002", "merge", merge_into="L-001")
    assert model_impact_status(ib, load_threads(ib), "L-002")["stale"] is True


def test_这条线一个伏笔都没有_不调模型(ib):
    th = load_threads(ib)
    set_card(ib, th, "L-002", "cut")
    backend = FakeBackend(handler=lambda tier, messages: "{}")
    r = run_impact(ib, LLMClient(AppConfig(), backend, log_dir=ib.logs_dir), "L-002")
    assert r["ok"] is True and backend.calls == []
    assert model_impact_status(ib, load_threads(ib), "L-002")["pairs"] == []


def test_拖回还没想好_旧影响结果不再显示(ib):
    _hooks(ib)
    th = load_threads(ib)
    set_card(ib, th, "L-002", "cut")
    reply = {"pairs": [{"planted": "S-0002", "resolved": "S-0004", "hook": "紧箍咒"}], "remedy": "改到主线收 [S-0002]"}
    backend = FakeBackend(handler=lambda tier, messages: json.dumps(reply, ensure_ascii=False))
    run_impact(ib, LLMClient(AppConfig(), backend, log_dir=ib.logs_dir), "L-002")
    assert model_impact_status(ib, load_threads(ib), "L-002") is not None
    set_card(ib, load_threads(ib), "L-002", "undecided")
    assert model_impact_status(ib, load_threads(ib), "L-002") is None
    # 再拖回砍掉：原结果原样回来，签名没变，stale 仍是 False（钱不重花）
    set_card(ib, load_threads(ib), "L-002", "cut")
    st = model_impact_status(ib, load_threads(ib), "L-002")
    assert st is not None and st["stale"] is False and st["pairs"][0]["resolved"] == "S-0004"


def test_别的线改列_没变own_others输入_不算过期(ib):
    _hooks(ib)
    th = load_threads(ib)
    set_card(ib, th, "L-002", "cut")
    reply = {"pairs": [{"planted": "S-0002", "resolved": "S-0004", "hook": "紧箍咒"}], "remedy": "改到主线收 [S-0002]"}
    backend = FakeBackend(handler=lambda tier, messages: json.dumps(reply, ensure_ascii=False))
    run_impact(ib, LLMClient(AppConfig(), backend, log_dir=ib.logs_dir), "L-002")
    assert model_impact_status(ib, load_threads(ib), "L-002")["stale"] is False
    # L-001 从「还没想好」改成「保留」：既不是 cut，也没碰 L-001 的伏笔内容，
    # impact_input 的 own / others 完全不变，不该被判成过期（不重花钱）
    set_card(ib, load_threads(ib), "L-001", "keep")
    assert model_impact_status(ib, load_threads(ib), "L-002")["stale"] is False


def test_卡不在砍掉或合并列_不许跑(ib):
    backend = FakeBackend(handler=lambda tier, messages: "{}")
    with pytest.raises(ValueError):
        run_impact(ib, LLMClient(AppConfig(), backend, log_dir=ib.logs_dir), "L-002")
