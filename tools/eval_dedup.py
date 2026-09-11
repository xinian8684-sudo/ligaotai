"""验收：导入乱稿 → 切场景 → 查重，对照标准答案算查重召回率。

用法：
  uv run python tools/eval_dedup.py --folder data/乱稿-西游记 --key data/乱稿-西游记-答案.json
报告写到 --report（默认 data/验收-查重.json）。终端只打 ASCII 数字，中文内容看报告文件。
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ligaotai.book import Book, create_book
from ligaotai.dedup import run_dedup
from ligaotai.fsutil import read_json, safe_name
from ligaotai.importer import run_import
from ligaotai.scenes import FRAGMENT, load_scenes, run_split

PASS_RECALL = 0.9


def evaluate(book: Book, key: dict, root: str) -> dict:
    scenes = [s for s in load_scenes(book) if not s.removed]
    source_of = {s.id: s.source for s in scenes}
    ids_by_file: dict[str, list[str]] = defaultdict(list)
    for s in scenes:
        ids_by_file[s.source].append(s.id)
    groups = read_json(book.versions_path, {"groups": []})["groups"]
    group_of = {m: g["id"] for g in groups for m in g["members"]}
    chapter_of = {f"{root}/{f['path']}": f["chapter"] for f in key["files"]}

    found, missed = [], []
    by_kind: dict[str, dict] = defaultdict(lambda: {"total": 0, "found": 0})
    for v in key["variants"]:
        vs = ids_by_file[f"{root}/{v['file']}"]
        os_ = ids_by_file[f"{root}/{v['original_file']}"]
        hit = any(a in group_of and group_of[a] == group_of.get(b) for a in vs for b in os_)
        by_kind[v["kind"]]["total"] += 1
        if hit:
            by_kind[v["kind"]]["found"] += 1
            found.append(v)
        else:
            missed.append({**v, "variant_scenes": vs, "original_scenes": os_})

    cross = []
    for g in groups:
        chapters = sorted({chapter_of.get(source_of[m], -1) for m in g["members"]})
        if len(chapters) > 1:
            cross.append({"group": g["id"], "members": g["members"], "chapters": chapters})

    chars = [s.chars for s in scenes]
    total = len(key["variants"])
    recall = len(found) / total if total else 1.0
    return {
        "variants": total,
        "found": len(found),
        "recall": round(recall, 4),
        "pass": recall >= PASS_RECALL,
        "by_kind": dict(by_kind),
        "missed": missed,
        "groups": len(groups),
        "cross_chapter_groups": cross,
        "scenes": len(scenes),
        "fragments": sum(s.kind_hint == FRAGMENT for s in scenes),
        "scene_chars": {
            "min": min(chars, default=0),
            "median": statistics.median(chars) if chars else 0,
            "max": max(chars, default=0),
        },
    }


def run_eval(folder: Path, key: dict, library: Path) -> dict:
    folder = Path(folder).resolve()
    title = f"验收-{folder.name}-{datetime.now():%Y%m%d-%H%M%S-%f}"
    book = create_book(library, title)
    run_import(book, folder)
    run_split(book)
    run_dedup(book)
    report = evaluate(book, key, safe_name(folder.name))
    report["book"] = str(book.root)
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="evaluate dedup recall against a scramble answer key")
    ap.add_argument("--folder", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--library", default="data/验收书库")
    ap.add_argument("--report", default="data/验收-查重.json")
    args = ap.parse_args(argv)
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    report = run_eval(Path(args.folder), key, Path(args.library))
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"variants={report['variants']} found={report['found']} recall={report['recall']} "
        f"pass={report['pass']} scenes={report['scenes']} fragments={report['fragments']} "
        f"groups={report['groups']} cross_chapter_groups={len(report['cross_chapter_groups'])}"
    )


if __name__ == "__main__":
    main()
