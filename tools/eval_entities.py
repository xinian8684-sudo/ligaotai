"""验收：别名合并（spec 11.3「植入的别名被提议合并 ≥ 90%」）。

在验收书库里用固定书名建（或打开）一本书：导入乱稿 → 切场景 → 查重 → 场景卡 → 实体合并，
然后对照弄乱脚本的答案。书名固定，所以重跑时新鲜的场景卡会跳过，不重复花钱。

用法：
  uv run python tools/eval_entities.py --check-only
  uv run python tools/eval_entities.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json
报告写到 --report（默认 data/验收-实体.json）。终端只打 ASCII，中文内容看报告文件。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from ligaotai.book import Book, create_book, open_book
from ligaotai.cards import run_cards
from ligaotai.config import AppConfig, load_config
from ligaotai.dedup import run_dedup
from ligaotai.entities import run_entities
from ligaotai.fsutil import read_json, safe_name
from ligaotai.importer import run_import
from ligaotai.llm import ChatBackend, LLMClient, NoKeyError, OpenAIBackend, check_model
from ligaotai.scenes import run_split

PASS_RECALL = 0.9
TITLE_PREFIX = "验收-实体-"
# 《西游记》主角的标准叫法（繁体，古登堡版的写法）。不含弄乱脚本植入的新别名。
GOLD = {
    "孫悟空": ["孫悟空", "悟空", "行者", "孫行者", "大聖", "齊天大聖", "美猴王", "猴王", "孫大聖"],
    "豬八戒": ["豬八戒", "八戒", "悟能", "豬悟能", "豬剛鬣", "呆子"],
    "唐三藏": ["唐三藏", "唐僧", "三藏", "玄奘", "陳玄奘", "御弟", "唐御弟"],
    "沙悟淨": ["沙悟淨", "沙僧", "悟淨", "沙和尚"],
}


def evaluate(entities: list[dict], key: dict, gold: dict = GOLD) -> dict:
    ent_of = {n: e["id"] for e in entities if e["type"] == "person" for n in e["names"]}
    injected = []
    for a in key["aliases"]:
        variants = sorted(n for n in ent_of if a["alias"] in n)
        targets = set(gold.get(a["canonical"], [])) | {a["replaces"], a["canonical"]}
        target_ids = {ent_of[n] for n in targets if n in ent_of}
        merged = any(ent_of[v] in target_ids for v in variants)
        injected.append({"alias": a["alias"], "canonical": a["canonical"], "extracted": variants, "merged": merged})
    found = sum(x["merged"] for x in injected)
    total = len(injected)

    gold_report = {}
    for canon, names in gold.items():
        present = [n for n in names if n in ent_of]
        if not present:
            gold_report[canon] = {"present": 0, "merged": 0, "left_out": []}
            continue
        main = Counter(ent_of[n] for n in present).most_common(1)[0][0]
        gold_report[canon] = {
            "present": len(present),
            "merged": sum(ent_of[n] == main for n in present),
            "left_out": [n for n in present if ent_of[n] != main],
        }

    char_of = {n: c for c, names in gold.items() for n in names}
    wrong = []
    for e in entities:
        if e["type"] != "person":
            continue
        chars = sorted({char_of[n] for n in e["names"] if n in char_of})
        if len(chars) > 1:
            wrong.append({"id": e["id"], "canonical": e["canonical"], "characters": chars})

    recall = found / total if total else 1.0
    return {
        "injected_found": found,
        "injected_total": total,
        "injected_recall": round(recall, 4),
        "pass": recall >= PASS_RECALL,
        "injected": injected,
        "gold": gold_report,
        "wrong_merges": wrong,
    }


def open_or_create(library: Path, title: str) -> Book:
    try:
        return open_book(library, safe_name(title))
    except FileNotFoundError:
        return create_book(library, title)


def run_eval(folder: Path, key: dict, library: Path, cfg: AppConfig, backend: ChatBackend) -> dict:
    folder = Path(folder).resolve()
    Path(library).mkdir(parents=True, exist_ok=True)
    book = open_or_create(Path(library), TITLE_PREFIX + folder.name)
    run_import(book, folder)
    run_split(book)
    run_dedup(book)
    cards = run_cards(book, LLMClient(cfg, backend, log_dir=book.logs_dir))
    entities = run_entities(book, LLMClient(cfg, backend, log_dir=book.logs_dir))
    report = evaluate(read_json(book.entities_path)["entities"], key)
    report.update(
        book=str(book.root),
        cards={k: cards[k] for k in ("scenes", "fresh", "written", "with_problems", "missing_count")},
        cards_failed=cards["failed"],
        entities=entities,
        usage=book.load().get("usage", {}),
    )
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="evaluate alias merging against a scramble answer key")
    ap.add_argument("--check-only", action="store_true", help="only test both model tiers")
    ap.add_argument("--folder")
    ap.add_argument("--key")
    ap.add_argument("--library", default="data/验收书库")
    ap.add_argument("--report", default="data/验收-实体.json")
    args = ap.parse_args(argv)
    cfg = load_config()
    try:
        backend = OpenAIBackend(cfg)
    except NoKeyError:
        sys.exit("no API key configured (config.json api_key or env LIGAOTAI_API_KEY)")
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if args.check_only:
        results = check_model(cfg, backend)
        report_path.with_name("验收-连接测试.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for r in results:
            print(f"{r['tier']} model={r['model']} ok={r['ok']} seconds={r['seconds']}")
        sys.exit(0 if all(r["ok"] for r in results) else 1)
    if not args.folder or not args.key:
        sys.exit("--folder and --key are required")
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    report = run_eval(Path(args.folder), key, Path(args.library), cfg, backend)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    total = report["usage"].get("total", {})
    print(
        f"injected={report['injected_found']}/{report['injected_total']} recall={report['injected_recall']} "
        f"pass={report['pass']} wrong_merges={len(report['wrong_merges'])} "
        f"cards={report['cards']['fresh']}/{report['cards']['scenes']} failed={len(report['cards_failed'])} "
        f"calls={total.get('calls', 0)} cost_usd={total.get('cost_usd', 0)}"
    )


if __name__ == "__main__":
    main()
