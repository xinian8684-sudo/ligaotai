import json

import pytest
from helpers import FakeBackend, fake_ai_handler, make_chapters, seed_book, threads_handler

import tools.eval_threads as eval_threads
from ligaotai.config import AppConfig
from ligaotai.llm import FatalLLMError, LLMError
from tools.eval_threads import estimate, evaluate, kendall_tau_b, run_eval, truth_positions
from tools.scramble import scramble

SMALL = dict(n_delete=2, n_truncate=2, n_full=3, n_excerpt=2, alias_chapters=5)
GROUPS = [["悟空", "金箍郎"], ["八戒", "天蓬郎"], ["唐僧", "御弟師父"]]


def test_kendall_tau_b():
    assert kendall_tau_b([0, 1, 2], [1, 2, 3]) == (1.0, 3)
    assert kendall_tau_b([0, 1, 2], [3, 2, 1]) == (-1.0, 3)
    tau, n = kendall_tau_b([0, 1, 2], [1, 3, 2])
    assert n == 3 and abs(tau - 1 / 3) < 1e-9
    tau, n = kendall_tau_b([0, 1, 2], [(1, 0), (1, 0), (2, 0)])  # 前两块标准位置并列
    assert n == 3 and abs(tau - 2 / 6 ** 0.5) < 1e-9
    assert kendall_tau_b([0], [5]) == (None, 0)
    assert kendall_tau_b([0, 1, 2], [3, 2, 1], keep=lambda i, j: (i, j) == (0, 1)) == (-1.0, 1)


def test_truth_positions(book):
    seed_book(book, [
        {"id": "S-0001", "source": "乱稿/x.txt", "index": 0},
        {"id": "S-0002", "source": "乱稿/x.txt", "index": 1},
        {"id": "S-0003", "source": "乱稿/y.txt", "index": 0},
        {"id": "S-0004", "source": "别的/z.txt", "index": 0},
    ])
    key = {"files": [{"path": "x.txt", "chapter": 3, "piece": 2}, {"path": "y.txt", "chapter": 1, "piece": 1}]}
    assert truth_positions(book, key, "乱稿") == {"S-0001": (3, 2, 0), "S-0002": (3, 2, 1), "S-0003": (1, 1, 0)}


def test_evaluate():
    pos = {"S-0001": (1, 1, 0), "S-0002": (1, 1, 1), "S-0003": (2, 1, 0), "S-0004": (3, 1, 0)}
    source_of = {"S-0001": "a", "S-0002": "a", "S-0003": "b", "S-0004": "c"}
    data = {"worlds": [], "threads": [
        {"id": "L-001", "name": "甲", "scenes": ["S-0001", "S-0002", "S-0004", "S-0003"], "end": {}},
        {"id": "L-002", "name": "乙", "scenes": ["S-0099"], "end": {}},
    ], "unassigned": [], "pending": [], "gaps": []}
    key = {"deleted": [5], "truncated": [{"chapter": 3, "kept_ratio": 0.5}]}
    r = evaluate(data, pos, source_of, key)
    # L-001：6 对里 5 对顺、1 对反（S-0004 排在了 S-0003 前面）→ τ = 4/6
    assert r["threads"][0]["tau"] == round(4 / 6, 4) and r["threads"][0]["pairs"] == 6
    # 片段级去掉同一文件的 S-0001/S-0002 那一对：5 对里 4 顺 1 反 → 3/5
    assert r["threads"][0]["seg_tau"] == 0.6 and r["threads"][0]["seg_pairs"] == 5
    assert r["threads"][1]["tau"] is None
    assert r["tau"] == round(4 / 6, 4) and r["pass"] is False
    assert r["truncated"] == [{"chapter": 3, "last_scene": "S-0004", "thread": "L-001", "is_thread_end": False}]
    assert r["deleted_chapters"] == [5]


def test_estimate(book):
    seed_book(book, [{"id": "S-0001"}, {"id": "S-0002", "no_card": True}])
    est = estimate(book, AppConfig())
    assert est["scenes"] == 2 and est["cards_needed"] == 1
    assert est["cards_usd"] > 0 and est["entities_usd"] > 0 and est["threads_usd"] > 0
    assert est["total_usd"] >= est["threads_usd"]


def test_run_eval_end_to_end_with_fake_model(tmp_path):
    out = tmp_path / "乱稿"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)

    def backend():
        return FakeBackend(handler=threads_handler(fallback=fake_ai_handler(GROUPS)))

    report = run_eval(out, key, tmp_path / "书库", AppConfig(), backend())
    assert report["threads"] and report["tau"] is not None and -1 <= report["tau"] <= 1
    assert report["this_run"]["calls"] > 0
    again = run_eval(out, key, tmp_path / "书库", AppConfig(), backend())
    assert again["this_run"]["calls"] == 0 and again["tau"] == report["tau"]  # 全部走缓存


# --- notes: 修复批次 4 之后，划世界全部分段都失败时 run_threads 抛的是普通 LLMError，
# 不只是 FatalLLMError（欠费/key 失效）；run_eval / main 也要接住它，别让钱白花了还查不了。


def test_run_eval_attaches_book_and_usage_to_plain_llm_error(tmp_path):
    out = tmp_path / "乱稿"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    # 划世界的回复每次都不是合法 json：三次重试用尽，chat_json 没有可用的结果，
    # 抛的是普通 LLMError；stage_worlds 全部分段都失败，run_threads 再抛一层普通 LLMError。
    backend = FakeBackend(handler=threads_handler(worlds=lambda m: "not json", fallback=fake_ai_handler(GROUPS)))
    with pytest.raises(LLMError) as ei:
        run_eval(out, key, tmp_path / "书库", AppConfig(), backend)
    assert not isinstance(ei.value, FatalLLMError)
    assert ei.value.book
    assert "total" in ei.value.usage  # 用量已经在 finally 里落盘，重跑能接着做（走缓存不花钱）


def test_main_writes_error_report_on_plain_llm_error(tmp_path, monkeypatch):
    out = tmp_path / "乱稿"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    key_path = tmp_path / "答案.json"
    key_path.write_text(json.dumps(key), encoding="utf-8")
    report_path = tmp_path / "报告.json"
    library = tmp_path / "书库"

    fake = FakeBackend(handler=threads_handler(worlds=lambda m: "not json", fallback=fake_ai_handler(GROUPS)))
    monkeypatch.setattr(eval_threads, "load_config", lambda: AppConfig())
    monkeypatch.setattr(eval_threads, "OpenAIBackend", lambda cfg: fake)

    with pytest.raises(SystemExit) as ei:
        eval_threads.main([
            "--folder", str(out), "--key", str(key_path), "--library", str(library), "--report", str(report_path),
        ])
    assert str(ei.value).isascii()  # 终端只打 ASCII，中文细节走 -error.json

    error_path = report_path.with_name(report_path.stem + "-error.json")
    data = json.loads(error_path.read_text(encoding="utf-8"))
    assert data["error"].startswith("LLMError")
    assert data["book"]
    assert "total" in data["usage"]
    assert not report_path.exists()  # 没跑成功，正式报告不该写出来
