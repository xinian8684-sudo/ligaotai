import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import FakeBackend, fake_ai_handler, make_chapters

import tools.eval_entities as eval_entities
from ligaotai.book import open_book
from ligaotai.config import AppConfig
from ligaotai.fsutil import read_json, safe_name, write_json
from ligaotai.llm import FatalLLMError
from tools.eval_entities import GOLD, TITLE_PREFIX, evaluate, run_eval
from tools.scramble import scramble

REPO_ROOT = Path(__file__).resolve().parents[1]

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


# --- N1: 主实体平局时判定固定，跟 PYTHONHASHSEED 无关 ---


def test_n1_tie_break_prefers_the_entity_that_holds_replaces():
    """御弟師父的候选叫法 2 比 2 打平：唐僧+三藏 在 E-1，唐三藏+玄奘 在 E-2。固定顺序
    [replaces, canonical, *gold] 里 replaces「唐僧」排最前面，平局时 E-1（唐僧所在的实体）赢。"""
    entities = [
        person("E-1", "唐僧", ["唐僧", "三藏", "御弟師父"]),
        person("E-2", "唐三藏", ["唐三藏", "玄奘"]),
    ]
    key = {"aliases": [{"replaces": "唐僧", "alias": "御弟師父", "canonical": "唐三藏", "chapters": [1]}]}
    r = evaluate(entities, key)
    hit = r["injected"][0]
    assert hit["main_id"] == "E-1"
    assert hit["merged"] is True


def test_n1_tie_break_is_independent_of_pythonhashseed(tmp_path):
    """跟上一个测试同一份数据，换两个不同的 PYTHONHASHSEED 各跑一次 evaluate，子进程里的
    判定必须一样——证明结果不是靠 set 的迭代顺序（随哈希种子乱跳）算出来的。"""
    entities = [
        person("E-1", "唐僧", ["唐僧", "三藏", "御弟師父"]),
        person("E-2", "唐三藏", ["唐三藏", "玄奘"]),
    ]
    key = {"aliases": [{"replaces": "唐僧", "alias": "御弟師父", "canonical": "唐三藏", "chapters": [1]}]}
    data_path = tmp_path / "input.json"
    data_path.write_text(json.dumps({"entities": entities, "key": key}), encoding="utf-8")

    script = (
        "import json, sys\n"
        "from tools.eval_entities import evaluate\n"
        "data = json.loads(open(sys.argv[1], encoding='utf-8').read())\n"
        "r = evaluate(data['entities'], data['key'])\n"
        "print(json.dumps(r['injected'][0]))\n"
    )
    script_path = tmp_path / "run_evaluate.py"
    script_path.write_text(script, encoding="utf-8")

    outcomes = []
    for seed in ("0", "1000003"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = os.pathsep.join(
            [str(REPO_ROOT), str(REPO_ROOT / "src"), env.get("PYTHONPATH", "")]
        )
        proc = subprocess.run(
            [sys.executable, str(script_path), str(data_path)],
            capture_output=True, text=True, cwd=REPO_ROOT, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        outcomes.append(json.loads(proc.stdout.strip()))

    assert outcomes[0] == outcomes[1]
    assert outcomes[0]["main_id"] == "E-1"
    assert outcomes[0]["merged"] is True


# --- M-a: 报告条目带主实体编号、变体所在实体编号、主实体是否混进别的主角 ---


def test_ma_injected_entries_report_main_id_variant_ids_and_wrong_merge_flag():
    # S3：别名合到了原名「唐僧」那一组，但主实体是唐三藏那一组（人数更多），未命中——
    # 不是因为混进了别的主角，main_in_wrong_merge 应该是 False。
    entities_s3 = [
        person("E-1", "唐僧", ["唐僧", "御弟師父"]),
        person("E-2", "唐三藏", ["唐三藏", "三藏", "玄奘"]),
    ]
    r = evaluate(entities_s3, KEY3)
    hit = next(x for x in r["injected"] if x["alias"] == "御弟師父")
    assert hit["main_id"] == "E-2"
    assert hit["variant_ids"] == ["E-1"]
    assert hit["main_in_wrong_merge"] is False
    assert hit["merged"] is False

    # S5：悟空的实体里混进了八戒的「獃子」，这个实体本身就是 wrong_merge，金箍郎（在同一个
    # 实体里）跟着判未命中，main_in_wrong_merge 应该是 True。
    entities_s5 = [person("E-1", "孫悟空", ["孫悟空", "悟空", "金箍郎", "獃子"])]
    r = evaluate(entities_s5, KEY)
    hit = next(x for x in r["injected"] if x["alias"] == "金箍郎")
    assert hit["main_id"] == "E-1"
    assert hit["variant_ids"] == ["E-1"]
    assert hit["main_in_wrong_merge"] is True
    assert hit["merged"] is False


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

    with pytest.raises(SystemExit) as ei:
        run_eval(out, key, library, AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))
    # M-b：多出的条目单独报数量，提示「混进了别的乱稿」；终端只打 ASCII，具体文件名走异常属性。
    msg = str(ei.value)
    assert msg.isascii()
    assert "1 extra" in msg and "mixed with another draft" in msg
    assert "missing" not in msg
    assert ei.value.extra == ["乱稿/杂/漏网的旧稿.txt"]
    assert ei.value.missing == []


# --- M-b: 清单核对里「多出」和「缺少」分开报数量、给不同的排查提示 ---


def test_mb_manifest_missing_files_hints_at_failed_import(tmp_path):
    out = tmp_path / "乱稿"
    library = tmp_path / "书库"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    # 模拟「有文件导入失败」：答案里记着这份文件，但书库导入时它已经不在磁盘上了——
    # 跟真的导入失败（比如某个 docx 读不出来）落到清单里的结果一样：答案有、清单没有。
    missing_rel = key["files"][0]["path"]
    (out / missing_rel).unlink()

    with pytest.raises(SystemExit) as ei:
        run_eval(out, key, library, AppConfig(), FakeBackend(handler=fake_ai_handler(GROUPS)))
    msg = str(ei.value)
    assert msg.isascii()
    assert "1 missing" in msg and "check import results" in msg
    assert "extra" not in msg
    assert ei.value.missing == [f"乱稿/{missing_rel}"]
    assert ei.value.extra == []


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

    with pytest.raises(SystemExit) as ei:
        eval_entities.main(["--folder", str(tmp_path), "--key", str(key_path), "--report", str(report_path)])
    assert str(ei.value).isascii()  # M-c：终端只打 ASCII，残缺报告的中文细节走文件

    # M-c：残缺报告写到 <report>-error.json，不是 --report 本身
    error_path = report_path.with_name(report_path.stem + "-error.json")
    data = json.loads(error_path.read_text(encoding="utf-8"))
    assert data["error"].startswith("FatalLLMError")
    assert data["usage"]["total"]["calls"] == 3


def test_a4_manifest_mismatch_in_main_writes_details_to_error_report(tmp_path, monkeypatch):
    """A4：main() 接住清单核对的 SystemExit，把多出/缺少的文件名和书路径写进 -error.json；
    终端（SystemExit 的 message）仍然只有 ASCII。"""
    out = tmp_path / "乱稿"
    library = tmp_path / "书库"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    key_path = tmp_path / "答案.json"
    key_path.write_text(json.dumps(key), encoding="utf-8")
    report_path = tmp_path / "报告.json"
    fake = FakeBackend(handler=fake_ai_handler(GROUPS))
    monkeypatch.setattr(eval_entities, "OpenAIBackend", lambda cfg: fake)

    argv = [
        "--folder", str(out), "--key", str(key_path), "--library", str(library), "--report", str(report_path),
    ]
    eval_entities.main(argv)  # 第一次正常跑完，建好书

    book = open_book(library, safe_name(f"{TITLE_PREFIX}乱稿-s3"))
    manifest = read_json(book.manifest_path)
    manifest["files"]["乱稿/杂/漏网的旧稿.txt"] = {
        "sha256": "0" * 64, "encoding": "utf-8", "chars": 1, "mtime": 0, "imported": "2020-01-01T00:00:00",
    }
    write_json(book.manifest_path, manifest)

    with pytest.raises(SystemExit) as ei:
        eval_entities.main(argv)
    assert str(ei.value).isascii()

    error_path = report_path.with_name(report_path.stem + "-error.json")
    data = json.loads(error_path.read_text(encoding="utf-8"))
    assert data["extra"] == ["乱稿/杂/漏网的旧稿.txt"]
    assert data["missing"] == []
    assert data["book"]


def test_a4_successful_run_removes_stale_error_report(tmp_path, monkeypatch):
    """A4：这次跑成功了，同目录上一次留下的 -error.json 要清掉，别让作者以为还有残留问题。"""
    out = tmp_path / "乱稿"
    library = tmp_path / "书库"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    key_path = tmp_path / "答案.json"
    key_path.write_text(json.dumps(key), encoding="utf-8")
    report_path = tmp_path / "报告.json"
    error_path = report_path.with_name(report_path.stem + "-error.json")
    error_path.write_text("{}", encoding="utf-8")  # 上一次失败留下的旧残缺报告
    fake = FakeBackend(handler=fake_ai_handler(GROUPS))
    monkeypatch.setattr(eval_entities, "OpenAIBackend", lambda cfg: fake)

    eval_entities.main([
        "--folder", str(out), "--key", str(key_path), "--library", str(library), "--report", str(report_path),
    ])

    assert not error_path.exists()
    assert report_path.exists()


def test_mc_fatal_error_does_not_overwrite_the_last_successful_report(tmp_path, monkeypatch):
    key_path = tmp_path / "答案.json"
    key_path.write_text(json.dumps({"aliases": [], "seed": 1, "files": []}), encoding="utf-8")
    report_path = tmp_path / "报告.json"
    # 上一次成功跑完留下的完整报告。
    report_path.write_text(json.dumps({"injected_total": 3, "pass": True}), encoding="utf-8")

    monkeypatch.setattr(eval_entities, "OpenAIBackend", lambda cfg: object())

    def boom(*args, **kwargs):
        e = FatalLLMError("欠费")
        e.book = str(tmp_path / "书库" / "验收-实体-乱稿-s1")
        e.usage = {"total": {"calls": 3, "cost_usd": 0.5}}
        raise e

    monkeypatch.setattr(eval_entities, "run_eval", boom)

    with pytest.raises(SystemExit):
        eval_entities.main(["--folder", str(tmp_path), "--key", str(key_path), "--report", str(report_path)])

    kept = json.loads(report_path.read_text(encoding="utf-8"))
    assert kept == {"injected_total": 3, "pass": True}  # 上一次成功的完整报告没被覆盖

    error_path = report_path.with_name(report_path.stem + "-error.json")
    data = json.loads(error_path.read_text(encoding="utf-8"))
    assert data["error"].startswith("FatalLLMError")
    assert data["usage"]["total"]["calls"] == 3
