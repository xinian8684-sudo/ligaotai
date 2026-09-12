"""验收：别名合并（spec 11.3「植入的别名被提议合并 ≥ 90%」）。

在验收书库里用固定书名建（或打开）一本书：导入乱稿 → 核对原稿清单 → 切场景 → 查重 → 场景卡 →
实体合并，然后对照弄乱脚本的答案。书名里带着乱稿文件夹名和答案里的 seed，同一份答案重跑时
接着用同一本书：新鲜的场景卡（按场景 hash）会跳过，实体合并的每一批也按「提示词 + 综合档完整
配置」缓存（模型、思考开关/强度等都在内），改了 config.json 里 synth 档的设置也会跳过旧结果——
两者重跑时都不重复花钱。想强制重做实体合并（比如刚改完 synth 档配置要对比效果），加
--fresh-entities：删掉实体合并缓存文件，重新调模型；场景卡不受影响，作者没确认过的实体本来
就会跟着重算。

用法：
  uv run python tools/eval_entities.py --check-only
  uv run python tools/eval_entities.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json
  uv run python tools/eval_entities.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json --fresh-entities
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
from ligaotai.llm import ChatBackend, FatalLLMError, LLMClient, NoKeyError, OpenAIBackend, check_model
from ligaotai.scenes import run_split

PASS_RECALL = 0.9
TITLE_PREFIX = "验收-实体-"
# 《西游记》主角的标准叫法（繁体，古登堡版的写法）。不含弄乱脚本植入的新别名。
GOLD = {
    "孫悟空": ["孫悟空", "悟空", "行者", "孫行者", "大聖", "齊天大聖", "美猴王", "猴王", "孫大聖", "老孫"],
    "豬八戒": ["豬八戒", "八戒", "悟能", "豬悟能", "豬剛鬣", "獃子"],
    "唐三藏": ["唐三藏", "唐僧", "三藏", "玄奘", "陳玄奘", "御弟", "唐御弟"],
    "沙悟淨": ["沙悟淨", "沙僧", "悟淨", "沙和尚"],
}


def _main_entity(names: set[str], ent_of: dict[str, str]) -> str | None:
    """这组叫法里出现次数最多的实体（沿用 gold 统计的算法）；一个都没落进任何实体就是 None。"""
    present = [n for n in names if n in ent_of]
    if not present:
        return None
    return Counter(ent_of[n] for n in present).most_common(1)[0][0]


def evaluate(entities: list[dict], key: dict, gold: dict = GOLD) -> dict:
    ent_of = {n: e["id"] for e in entities if e["type"] == "person" for n in e["names"]}

    # char_of：GOLD 的标准叫法 + 植入别名（不管有没有被模型抽出来，只要哪个实体的叫法里含着这个
    # 别名，这个叫法就算这个人物的），用来发现「一个实体混进了两个主角」——包括别名被错合进
    # 另一个主角的实体这种情况。
    char_of = {n: c for c, names in gold.items() for n in names}
    for a in key["aliases"]:
        for n in ent_of:
            if a["alias"] in n:
                char_of.setdefault(n, a["canonical"])

    wrong = []
    for e in entities:
        if e["type"] != "person":
            continue
        chars = sorted({char_of[n] for n in e["names"] if n in char_of})
        if len(chars) > 1:
            wrong.append({"id": e["id"], "canonical": e["canonical"], "characters": chars})
    wrong_ids = {w["id"] for w in wrong}

    injected = []
    for a in key["aliases"]:
        variants = sorted(n for n in ent_of if a["alias"] in n)
        variant_ids = {ent_of[v] for v in variants}
        # 主实体 = 这个人物的 gold 叫法 + replaces + canonical 里出现次数最多的实体（沿用 gold
        # 统计的算法）。挑主实体时排除跟这个植入别名互相包含的叫法（比如「御弟」是「御弟師父」
        # 的前缀）——不然别名不用真被模型合并，光靠字面包含关系就能借 gold 那边的统计蹭到命中。
        pool = set(gold.get(a["canonical"], [])) | {a["replaces"], a["canonical"]}
        pool = {n for n in pool if a["alias"] not in n and n not in a["alias"]}
        main_id = _main_entity(pool, ent_of)
        # 命中 = 含这个别名的某个叫法所在实体就是主实体，且这个实体没混进别的主角。
        merged = main_id is not None and main_id in variant_ids and main_id not in wrong_ids
        injected.append({
            "alias": a["alias"], "canonical": a["canonical"], "extracted": variants, "merged": merged,
        })
    found = sum(x["merged"] for x in injected)
    total = len(injected)
    recall = found / total if total else 0.0

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

    return {
        "injected_found": found,
        "injected_total": total,
        "injected_recall": round(recall, 4),
        "pass": total > 0 and recall >= PASS_RECALL,  # 答案里一个别名都没有时，空考卷不算通过
        "injected": injected,
        "gold": gold_report,
        "wrong_merges": wrong,
    }


def open_or_create(library: Path, title: str) -> Book:
    try:
        return open_book(library, safe_name(title))
    except FileNotFoundError:
        return create_book(library, title)


def _check_manifest(book: Book, folder: Path, key: dict) -> None:
    """核对导入后的原稿清单跟答案里的文件列表是不是同一份乱稿。

    书名已经带着乱稿文件夹名和 seed，正常情况下不会撞上别的乱稿；但万一手动搬过书库、或者
    答案和乱稿文件夹没对上，run_import 只会新增/更新清单，不会删掉文件夹里已经不存在的旧条目，
    新旧两份乱稿的场景、叫法会一直混在一起验收，而且报告里看不出来。"""
    root_name = safe_name(folder.name)
    expected = {f"{root_name}/{f['path']}" for f in key["files"]}
    actual = set(read_json(book.manifest_path, {"files": {}})["files"])
    if actual != expected:
        sys.exit(f"验收书里混进了别的乱稿，删掉这本书重跑：{book.root}")


def run_eval(
    folder: Path,
    key: dict,
    library: Path,
    cfg: AppConfig,
    backend: ChatBackend,
    fresh_entities: bool = False,
) -> dict:
    folder = Path(folder).resolve()
    Path(library).mkdir(parents=True, exist_ok=True)
    title = f"{TITLE_PREFIX}{folder.name}-s{key['seed']}"
    book = open_or_create(Path(library), title)
    run_import(book, folder)
    _check_manifest(book, folder, key)
    run_split(book)
    run_dedup(book)
    if fresh_entities:
        book.entities_cache_path.unlink(missing_ok=True)
    try:
        cards = run_cards(book, LLMClient(cfg, backend, log_dir=book.logs_dir))
        entities = run_entities(book, LLMClient(cfg, backend, log_dir=book.logs_dir))
    except FatalLLMError as e:
        # 欠费/key 失效：把已经落盘的用量和书路径挂到异常上，main() 好尽量写进报告文件。
        e.book = str(book.root)
        e.usage = book.load().get("usage", {})
        raise
    report = evaluate(read_json(book.entities_path)["entities"], key)
    report.update(
        book=str(book.root),
        cards={
            k: cards[k]
            for k in ("scenes", "fresh", "written", "with_problems", "missing_count", "calls", "cost_usd")
        },
        cards_failed=cards["failed"],
        entities=entities,
        usage=book.load().get("usage", {}),
        model_tiers={"batch": cfg.batch.model_dump(), "synth": cfg.synth.model_dump()},  # 不含 api_key
        this_run={  # 这一次运行的调用/花费（跟 usage.total 的累计值分开看）
            "calls": cards["calls"] + entities["calls"],
            "cost_usd": round(cards["cost_usd"] + entities["cost_usd"], 4),
        },
    )
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="evaluate alias merging against a scramble answer key")
    ap.add_argument("--check-only", action="store_true", help="only test both model tiers")
    ap.add_argument("--folder")
    ap.add_argument("--key")
    ap.add_argument("--library", default="data/验收书库")
    ap.add_argument("--report", default="data/验收-实体.json")
    ap.add_argument(
        "--fresh-entities", action="store_true",
        help="重新做实体合并（删掉实体合并缓存重新调模型），场景卡照样按场景 hash 跳过",
    )
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
    try:
        report = run_eval(
            Path(args.folder), key, Path(args.library), cfg, backend, fresh_entities=args.fresh_entities
        )
    except FatalLLMError as e:
        partial = {
            "error": f"{type(e).__name__}: {e}",
            "book": getattr(e, "book", None),
            "usage": getattr(e, "usage", {}),
        }
        report_path.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.exit(f"fatal model error, see {report_path}")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    total = report["usage"].get("total", {})
    this_run = report["this_run"]
    print(
        f"injected={report['injected_found']}/{report['injected_total']} recall={report['injected_recall']} "
        f"pass={report['pass']} wrong_merges={len(report['wrong_merges'])} "
        f"cards={report['cards']['fresh']}/{report['cards']['scenes']} failed={len(report['cards_failed'])} "
        f"this_run_calls={this_run['calls']} this_run_cost_usd={this_run['cost_usd']} "
        f"total_calls={total.get('calls', 0)} total_cost_usd={total.get('cost_usd', 0)}"
    )


if __name__ == "__main__":
    main()
