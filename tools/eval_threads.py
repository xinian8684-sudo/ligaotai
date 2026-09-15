"""验收：线内顺序（总 spec 11.3「线内顺序与原书顺序的 Kendall τ ≥ 0.8」，②b 设计 6.2）。

书沿用 eval_entities 的书名（验收-实体-<乱稿文件夹名>-s<seed>）：导入 → 核对原稿清单 → 切场景 →
查重 → 场景卡 → 实体合并 → 归线，做过的都走缓存不花钱。然后对照弄乱脚本的答案算 τ。

用法：
  uv run python tools/eval_threads.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json --estimate
  uv run python tools/eval_threads.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json --report data/验收-归线-西游记.json
--estimate 只做导入 / 切场景 / 查重（不花钱），按 ②a 实测参数粗估要花多少，不调模型，结果写到 <报告名>-估算.json。
终端只打 ASCII，中文内容看报告文件。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Callable

from ligaotai.book import Book
from ligaotai.cards import is_fresh, load_cards, run_cards
from ligaotai.config import AppConfig, load_config
from ligaotai.dedup import run_dedup
from ligaotai.entities import run_entities
from ligaotai.fsutil import read_json, safe_name
from ligaotai.importer import run_import
from ligaotai.llm import ChatBackend, FatalLLMError, LLMClient, LLMError, NoKeyError, OpenAIBackend
from ligaotai.scenes import load_scenes, run_split
from ligaotai.threads import run_threads
from ligaotai.threads_input import prepare

if __package__ in (None, ""):  # 按脚本路径跑（uv run python tools/eval_threads.py）时，仓库根不在 sys.path 里
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.eval_entities import TITLE_PREFIX, _check_manifest, open_or_create  # noqa: E402

PASS_TAU = 0.8
# ②a 验收实测（西游记 268 张卡）：每次调用约 6.6k 输入、1.24k 输出，平均每卡 1.75 次调用；实体合并约每个场景 $0.0013
CARD_IN, CARD_OUT, CARD_CALLS = 6600, 1240, 1.75
ENTITY_USD_PER_SCENE = 0.0013
MISSING_LINE_CHARS = 150  # 还没有卡的块，压成一行大约多长
# 归线粗估：输入约 5 倍全部行（划世界、划支线、排序、对齐、缺口各过一遍）；调用约 3 + 场景数/25 次，每次输出（含思考）约 8k
THREAD_PASSES, THREAD_OUT_PER_CALL, SCENES_PER_CALL = 5, 8000, 25


def kendall_tau_b(xs: list, ys: list, keep: Callable[[int, int], bool] | None = None) -> tuple[float | None, int]:
    """Kendall τ-b（能处理并列）。返回 (τ, 参与比较的块对数)；keep(i, j) 为 False 的块对不算。
    没有可比较的块对（或者全部并列）时 τ 是 None。"""
    p = q = tx = ty = n = 0
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            if keep is not None and not keep(i, j):
                continue
            n += 1
            dx = (xs[i] > xs[j]) - (xs[i] < xs[j])
            dy = (ys[i] > ys[j]) - (ys[i] < ys[j])
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                tx += 1
            elif dy == 0:
                ty += 1
            elif dx == dy:
                p += 1
            else:
                q += 1
    denom = math.sqrt((p + q + tx) * (p + q + ty))
    return ((p - q) / denom if denom else None), n


def truth_positions(book: Book, key: dict, folder_name: str) -> dict[str, tuple[int, int, int]]:
    """每块在原书里的位置：（第几回, 第几片, 文件里第几块）。来源不在答案里的块不算。"""
    root = safe_name(folder_name)
    by_path = {f"{root}/{f['path']}": (f["chapter"], f["piece"]) for f in key["files"]}
    out = {}
    for s in load_scenes(book):
        if s.removed:
            continue
        cp = by_path.get(s.source)
        if cp is not None:
            out[s.id] = (cp[0], cp[1], s.index)
    return out


def _wavg(rows: list[dict], k: str, w: str) -> float | None:
    got = [(r[k], r[w]) for r in rows if r[k] is not None and r[w]]
    den = sum(x for _, x in got)
    return round(sum(v * x for v, x in got) / den, 4) if den else None


def evaluate(data: dict, pos: dict, source_of: dict[str, str], key: dict) -> dict:
    threads = data.get("threads", [])
    rows = []
    for t in threads:
        ids = [s for s in t["scenes"] if s in pos]
        xs, ys = list(range(len(ids))), [pos[s] for s in ids]
        tau, pairs = kendall_tau_b(xs, ys)
        seg, seg_pairs = kendall_tau_b(xs, ys, keep=lambda i, j: source_of.get(ids[i]) != source_of.get(ids[j]))
        rows.append({
            "id": t["id"], "name": t["name"], "scenes": len(t["scenes"]), "scored": len(ids),
            "tau": None if tau is None else round(tau, 4), "pairs": pairs,
            "seg_tau": None if seg is None else round(seg, 4), "seg_pairs": seg_pairs,
            "order_failed": t.get("order_failed", False), "end": t.get("end"),
        })
    thread_of = {s: t["id"] for t in threads for s in t["scenes"]}
    last_of = {t["id"]: t["scenes"][-1] for t in threads if t["scenes"]}
    truncated = []
    for tr in key.get("truncated", []):
        mine = [s for s in thread_of if s in pos and pos[s][0] == tr["chapter"]]
        last = max(mine, key=lambda s: pos[s]) if mine else None
        th = thread_of.get(last)
        truncated.append({"chapter": tr["chapter"], "last_scene": last, "thread": th,
                          "is_thread_end": th is not None and last_of.get(th) == last})
    tau = _wavg(rows, "tau", "pairs")
    return {
        "tau": tau,
        "seg_tau": _wavg(rows, "seg_tau", "seg_pairs"),
        "pass": tau is not None and tau >= PASS_TAU,
        "worlds": [{"id": w["id"], "name": w["name"], "notes": len(w.get("notes", []))} for w in data.get("worlds", [])],
        "threads": rows,
        "unassigned": data.get("unassigned", []),
        "pending": data.get("pending", []),
        "deleted_chapters": key.get("deleted", []),
        "gaps": data.get("gaps", []),
        "truncated": truncated,
    }


def estimate(book: Book, cfg: AppConfig) -> dict:
    scenes = [s for s in load_scenes(book) if not s.removed]
    records = load_cards(book)
    need = sum(1 for s in scenes if not is_fresh(records.get(s.id), s))
    cards_usd = need * CARD_CALLS * (CARD_IN * cfg.price_input + CARD_OUT * cfg.price_output) / 1e6
    entities_done = need == 0 and book.step("entities")["status"] == "done"
    entities_usd = 0.0 if entities_done else len(scenes) * ENTITY_USD_PER_SCENE
    chars = sum(len(i.line) + 1 for i in prepare(book).items.values()) + MISSING_LINE_CHARS * need
    calls = 3 + len(scenes) / SCENES_PER_CALL
    threads_usd = (THREAD_PASSES * chars * cfg.price_input + calls * THREAD_OUT_PER_CALL * cfg.price_output) / 1e6
    return {
        "scenes": len(scenes),
        "cards_needed": need,
        "cards_usd": round(cards_usd, 4),
        "entities_usd": round(entities_usd, 4),
        "threads_usd": round(threads_usd, 4),
        "total_usd": round(cards_usd + entities_usd + threads_usd, 4),
    }


def _open(folder: Path, key: dict, library: Path) -> Book:
    folder = Path(folder).resolve()
    Path(library).mkdir(parents=True, exist_ok=True)
    book = open_or_create(Path(library), f"{TITLE_PREFIX}{folder.name}-s{key['seed']}")
    run_import(book, folder)
    _check_manifest(book, folder, key)
    run_split(book)
    run_dedup(book)
    return book


def run_eval(folder: Path, key: dict, library: Path, cfg: AppConfig, backend: ChatBackend) -> dict:
    book = _open(folder, key, library)
    try:
        cards = run_cards(book, LLMClient(cfg, backend, log_dir=book.logs_dir))
        ents = run_entities(book, LLMClient(cfg, backend, log_dir=book.logs_dir))
        threads = run_threads(book, LLMClient(cfg, backend, log_dir=book.logs_dir))
    except LLMError as e:
        # 欠费/key 失效（FatalLLMError）或者一步彻底失败（比如划世界全部分段都没法用，
        # run_threads 抛的是普通 LLMError）：都把已经落盘的用量和书路径挂到异常上，main() 好写进报告文件。
        e.book = str(book.root)
        e.usage = book.load().get("usage", {})
        raise
    pos = truth_positions(book, key, Path(folder).resolve().name)
    source_of = {s.id: s.source for s in load_scenes(book)}
    report = evaluate(read_json(book.threads_path), pos, source_of, key)
    parts = (cards, ents, threads)
    report.update(
        book=str(book.root),
        threads_summary=threads,
        this_run={  # 这一次运行的调用 / 花费（跟 usage.total 的累计值分开看）
            "calls": sum(p["calls"] for p in parts),
            "cost_usd": round(sum(p["cost_usd"] for p in parts), 4),
        },
        usage=book.load().get("usage", {}),
        model_tiers={"batch": cfg.batch.model_dump(), "synth": cfg.synth.model_dump()},  # 不含 api_key
    )
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="evaluate thread ordering against a scramble answer key")
    ap.add_argument("--folder", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--library", default="data/验收书库")
    ap.add_argument("--report", default="data/验收-归线.json")
    ap.add_argument("--estimate", action="store_true", help="只粗估费用，不调模型")
    args = ap.parse_args(argv)
    cfg = load_config()
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if args.estimate:
        est = estimate(_open(Path(args.folder), key, Path(args.library)), cfg)
        report_path.with_name(report_path.stem + "-估算.json").write_text(
            json.dumps(est, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(" ".join(f"{k}={v}" for k, v in est.items()))
        return
    try:
        backend = OpenAIBackend(cfg)
    except NoKeyError:
        sys.exit("no API key configured (config.json api_key or env LIGAOTAI_API_KEY)")
    error_path = report_path.with_name(report_path.stem + "-error.json")
    try:
        report = run_eval(Path(args.folder), key, Path(args.library), cfg, backend)
    except LLMError as e:
        partial = {"error": f"{type(e).__name__}: {e}", "book": getattr(e, "book", None), "usage": getattr(e, "usage", {})}
        error_path.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")
        kind = "fatal" if isinstance(e, FatalLLMError) else "a step"
        sys.exit(f"{kind} model error, see the -error report next to your --report path")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    error_path.unlink(missing_ok=True)
    print(
        f"tau={report['tau']} seg_tau={report['seg_tau']} pass={report['pass']} threads={len(report['threads'])} "
        f"unassigned={len(report['unassigned'])} gaps={len(report['gaps'])} "
        f"this_run_calls={report['this_run']['calls']} this_run_cost_usd={report['this_run']['cost_usd']}"
    )


if __name__ == "__main__":
    main()
