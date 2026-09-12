import json
import shutil

import pytest
from helpers import FakeBackend, fake_ai_handler, make_chapters

import tools.eval_entities as eval_entities
from ligaotai.book import open_book
from ligaotai.config import AppConfig
from ligaotai.fsutil import read_json, safe_name, write_json
from ligaotai.llm import FatalLLMError
from tools.eval_entities import GOLD, TITLE_PREFIX, evaluate, run_eval
from tools.scramble import scramble

KEY = {"aliases": [
    {"replaces": "悟空", "alias": "金箍郎", "canonical": "孫悟空", "chapters": [1]},
    {"replaces": "八戒", "alias": "天蓬郎", "canonical": "豬八戒", "chapters": [1]},
]}

KEY3 = {"aliases": [
    {"replaces": "悟空", "alias": "金箍郎", "canonical": "孫悟空", "chapters": [1]},
    {"replaces": "八戒", "alias": "天蓬郎", "canonical": "豬八戒", "chapters": [1]},
    {"replaces": "唐僧", "alias": "御弟師父", "canonical": "唐三藏", "chapters": [1]},
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


# --- I1: 命中判定收紧 ---


def test_i1_alias_that_is_a_prefix_of_a_gold_name_is_not_a_free_hit():
    """「御弟」是植入别名「御弟師父」的前缀：御弟/御弟師父 自己单独成组，唐僧其他叫法在另一组，
    不能因为「御弟」落在唐僧那一组就算命中——御弟師父根本没跟唐僧合到一起。"""
    entities = [
        person("E-1", "御弟", ["御弟", "御弟師父"]),
        person("E-2", "唐三藏", ["唐三藏", "唐僧", "三藏", "玄奘", "陳玄奘", "唐御弟"]),
    ]
    r = evaluate(entities, KEY3)
    hit = next(x for x in r["injected"] if x["alias"] == "御弟師父")
    assert hit["extracted"] == ["御弟師父"]
    assert hit["merged"] is False


def test_i1_grand_merge_of_all_protagonists_is_not_a_hit():
    """四个主角连同三个植入别名全归进一个大杂烩实体：wrong_merges 里能查到，三个别名都不算命中。"""
    entities = [
        person("E-1", "孫悟空", [
            "孫悟空", "悟空", "金箍郎", "行者",
            "豬八戒", "八戒", "天蓬郎",
            "唐三藏", "唐僧", "御弟師父",
            "沙悟淨", "沙僧",
        ]),
    ]
    r = evaluate(entities, KEY3)
    assert r["injected_found"] == 0
    assert r["injected_total"] == 3
    assert [w["id"] for w in r["wrong_merges"]] == ["E-1"]


# --- M1: 空答案不算通过 ---


def test_m1_empty_alias_list_never_passes():
    r = evaluate([person("E-1", "孫悟空", ["孫悟空"])], {"aliases": []})
    assert r["injected_total"] == 0
    assert r["pass"] is False


# --- M2: 别名错合进另一个主角的实体也要算进 wrong_merges ---


def test_m2_alias_merged_into_another_protagonist_is_a_wrong_merge():
    entities = [
        person("E-1", "八戒", ["八戒", "金箍郎"]),  # 金箍郎本该是孫悟空的别名，被错合进了八戒
        person("E-2", "孫悟空", ["孫悟空", "悟空"]),
    ]
    r = evaluate(entities, KEY)
    assert r["wrong_merges"] == [{"id": "E-1", "canonical": "八戒", "characters": ["孫悟空", "豬八戒"]}]
    hit = next(x for x in r["injected"] if x["alias"] == "金箍郎")
    assert hit["merged"] is False


# --- M3: GOLD 用繁体高频写法 ---


def test_m3_gold_uses_traditional_high_frequency_forms():
    assert "獃子" in GOLD["豬八戒"] and "呆子" not in GOLD["豬八戒"]
    assert "老孫" in GOLD["孫悟空"]


# --- I2: 书名带 seed，导入后核对原稿清单 ---


def test_i2_title_includes_seed_so_a_new_scramble_gets_a_new_book(tmp_path):
    out = tmp_path / "乱稿"
    library = tmp_path / "书库"
    key1 = scramble(make_chapters(20), out, seed=3, **SMALL)
    r1 = run_eval(out, key1, library, AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))

    shutil.rmtree(out)
    key2 = scramble(make_chapters(20), out, seed=4, **SMALL)
    r2 = run_eval(out, key2, library, AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))

    assert r1["book"] != r2["book"]


def test_i2_stale_manifest_entry_aborts_with_system_exit(tmp_path):
    out = tmp_path / "乱稿"
    library = tmp_path / "书库"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    run_eval(out, key, library, AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))

    book = open_book(library, safe_name(f"{TITLE_PREFIX}乱稿-s3"))
    manifest = read_json(book.manifest_path)
    manifest["files"]["乱稿/杂/漏网的旧稿.txt"] = {
        "sha256": "0" * 64, "encoding": "utf-8", "chars": 1, "mtime": 0, "imported": "2020-01-01T00:00:00",
    }
    write_json(book.manifest_path, manifest)

    with pytest.raises(SystemExit):
        run_eval(out, key, library, AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))


# --- I3: --fresh-entities ---


def test_i3_fresh_entities_forces_recompute(tmp_path):
    out = tmp_path / "乱稿"
    library = tmp_path / "书库"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    run_eval(out, key, library, AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))

    again = run_eval(out, key, library, AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))
    assert again["entities"]["calls"] == 0  # 命中实体合并缓存，不重复花钱

    fresh = run_eval(
        out, key, library, AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)), fresh_entities=True
    )
    assert fresh["entities"]["calls"] > 0  # 强制重做


# --- M4: 区分「本次运行」和「这本书累计」 ---


def test_m4_report_separates_this_run_from_cumulative(tmp_path):
    out = tmp_path / "乱稿"
    library = tmp_path / "书库"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    report = run_eval(out, key, library, AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))
    assert report["cards"]["calls"] > 0 and "cost_usd" in report["cards"]
    assert report["this_run"]["calls"] == report["cards"]["calls"] + report["entities"]["calls"]
    total_after_first = report["usage"]["total"]["calls"]

    again = run_eval(out, key, library, AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))
    assert again["this_run"]["calls"] == 0  # 场景卡和实体合并全命中缓存，本次没花钱
    assert again["usage"]["total"]["calls"] == total_after_first  # 累计值没跟着涨


# --- M5: 模型致命错误干净退出 ---


def test_m5_run_eval_attaches_book_and_usage_to_fatal_error(tmp_path):
    out = tmp_path / "乱稿"
    library = tmp_path / "书库"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    ok_handler = fake_ai_handler(GROUPS)

    def dying_handler(tier, messages):
        if "归成一组" in messages[0]["content"]:
            raise FatalLLMError("欠费")
        return ok_handler(tier, messages)

    with pytest.raises(FatalLLMError) as ei:
        run_eval(out, key, library, AppConfig(), FakeBackend(handler=dying_handler))
    assert ei.value.book
    assert "total" in ei.value.usage  # 用量已经在 finally 里落盘，重跑能接着做


def test_m5_main_exits_cleanly_and_writes_report_on_fatal_error(tmp_path, monkeypatch):
    key_path = tmp_path / "答案.json"
    key_path.write_text(json.dumps({"aliases": [], "seed": 1, "files": []}), encoding="utf-8")
    report_path = tmp_path / "报告.json"

    monkeypatch.setattr(eval_entities, "OpenAIBackend", lambda cfg: object())

    def boom(*args, **kwargs):
        e = FatalLLMError("欠费")
        e.book = str(tmp_path / "书库" / "验收-实体-乱稿-s1")
        e.usage = {"total": {"calls": 3, "cost_usd": 0.5}}
        raise e

    monkeypatch.setattr(eval_entities, "run_eval", boom)

    with pytest.raises(SystemExit):
        eval_entities.main(["--folder", str(tmp_path), "--key", str(key_path), "--report", str(report_path)])

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["error"].startswith("FatalLLMError")
    assert data["usage"]["total"]["calls"] == 3
