from helpers import FakeBackend, fake_ai_handler, make_chapters

from ligaotai.config import AppConfig
from tools.eval_entities import evaluate, run_eval
from tools.scramble import scramble

KEY = {"aliases": [
    {"replaces": "悟空", "alias": "金箍郎", "canonical": "孫悟空", "chapters": [1]},
    {"replaces": "八戒", "alias": "天蓬郎", "canonical": "豬八戒", "chapters": [1]},
]}


def person(eid, canonical, names):
    return {"id": eid, "type": "person", "canonical": canonical, "names": names, "status": "draft"}


def test_evaluate_counts_injected_and_gold():
    entities = [
        person("E-1", "孫悟空", ["孫悟空", "悟空", "金箍郎", "行者"]),
        person("E-2", "孫行者", ["孫行者"]),
        person("E-3", "天蓬郎", ["天蓬郎"]),
        person("E-4", "八戒", ["八戒", "唐僧"]),
    ]
    r = evaluate(entities, KEY)
    assert (r["injected_found"], r["injected_total"], r["pass"]) == (1, 2, False)
    assert r["injected"][0]["extracted"] == ["金箍郎"] and r["injected"][0]["merged"] is True
    assert r["gold"]["孫悟空"]["present"] == 4 and r["gold"]["孫悟空"]["left_out"] == ["孫行者"]
    assert r["wrong_merges"] == [{"id": "E-4", "canonical": "八戒", "characters": ["唐三藏", "豬八戒"]}]


def test_alias_never_extracted_is_a_miss():
    r = evaluate([person("E-1", "孫悟空", ["孫悟空", "悟空"])], KEY)
    assert r["injected"][0]["extracted"] == [] and r["injected_found"] == 0


GROUPS = [["悟空", "金箍郎"], ["八戒", "天蓬郎"], ["唐僧", "御弟師父"]]
SMALL = dict(n_delete=2, n_truncate=2, n_full=3, n_excerpt=2, alias_chapters=5)


def test_end_to_end_with_fake_model(tmp_path):
    out = tmp_path / "乱稿"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    report = run_eval(out, key, tmp_path / "书库", AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))
    assert report["injected_total"] == 3
    assert report["injected_recall"] == 1.0 and report["pass"] is True
    assert report["cards"]["fresh"] == report["cards"]["scenes"]
    first_calls = report["usage"]["by_step"]["cards"]["calls"]

    again = run_eval(out, key, tmp_path / "书库", AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))
    assert again["usage"]["by_step"]["cards"]["calls"] == first_calls  # 场景卡没有重做


def test_end_to_end_without_merges_fails(tmp_path):
    out = tmp_path / "乱稿"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    report = run_eval(out, key, tmp_path / "书库", AppConfig(), FakeBackend(handler=fake_ai_handler([])))
    assert report["injected_recall"] == 0.0 and report["pass"] is False
