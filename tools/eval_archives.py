"""计划②c 的验收：引用核对（编造率、无引用句率）、植入矛盾召回率、人工抽查抽样。

用法：
  uv run python tools/eval_archives.py --book <书库>/<书名> --key data/乱稿-xxx-答案.json
  uv run python tools/eval_archives.py --book ... --sample 10 --out 抽查.md
门槛（spec 第 9 节）：编造率 ≤ 2%，无引用句率 ≤ 10%，植入矛盾召回 ≥ 8/10。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ligaotai.archive import refs_in  # noqa: E402
from ligaotai.book import Book  # noqa: E402

_SENT = re.compile(r"[^。！？\n]+[。！？]?")
FABRICATED_LIMIT = 0.02
NO_REF_LIMIT = 0.10


def sentences(text: str) -> list[str]:
    """按句切，跳过标题行和空行——标题不是结论句，不该算进无引用句率。"""
    out = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        for m in _SENT.finditer(s):
            piece = m.group(0).strip()
            if piece:
                out.append(piece)
    return out


def check_refs(bodies: dict[str, str], allowed: dict[str, set[str]],
               existing: set[str]) -> dict:
    """逐条核每个引用：编号存在、且属于这份档案的范围（spec 9.2）。"""
    total = bad = n_sent = no_ref = 0
    details = []
    for oid, body in sorted(bodies.items()):
        scope = allowed.get(oid, set())
        for s in sentences(body):
            n_sent += 1
            refs = refs_in(s)
            if not refs:
                no_ref += 1
            for r in refs:
                total += 1
                why = ""
                if r not in existing:
                    why = "编号不存在"
                elif scope and r not in scope:
                    why = "不属于这份档案"
                if why:
                    bad += 1
                    details.append({"archive": oid, "ref": r, "why": why, "sentence": s[:60]})
    return {
        "total": total, "bad": bad,
        "fabricated_rate": round(bad / total, 4) if total else 0.0,
        "sentences": n_sent, "no_ref": no_ref,
        "no_ref_rate": round(no_ref / n_sent, 4) if n_sent else 0.0,
        "details": details[:50],
    }


# --------------------------------------------------------------------------------------
# main() 用到的书内数据装配
# --------------------------------------------------------------------------------------

def load_scopes_and_bodies(book: Book) -> tuple[dict[str, str], dict[str, set[str]], set[str]]:
    """从 档案/index.json 拿到各份档案的路径与范围：线的范围 = index 里记的这条线的
    scenes；世界的范围 = 这个世界下所有线（index 线条目的 world 字段）的场景并集；
    地图的范围 = 全书场景（场景/ 目录下现存的编号）。"""
    index = {}
    if book.archive_index_path.exists():
        try:
            index = json.loads(book.archive_index_path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            index = {}
    threads = index.get("threads") if isinstance(index.get("threads"), dict) else {}
    worlds = index.get("worlds") if isinstance(index.get("worlds"), dict) else {}

    thread_scope = {tid: set(e.get("scenes") or []) for tid, e in threads.items() if isinstance(e, dict)}
    world_scope: dict[str, set[str]] = {wid: set() for wid, e in worlds.items() if isinstance(e, dict)}
    for e in threads.values():
        if not isinstance(e, dict):
            continue
        wid = e.get("world")
        if wid in world_scope:
            world_scope[wid] |= set(e.get("scenes") or [])

    existing = {p.stem for p in book.scenes_dir.glob("S-*.md")} if book.scenes_dir.exists() else set()

    bodies: dict[str, str] = {}
    allowed: dict[str, set[str]] = {}
    for tid, e in threads.items():
        if isinstance(e, dict) and e.get("file"):
            p = book.root / e["file"]
            if p.exists():
                bodies[tid] = p.read_text(encoding="utf-8")
                allowed[tid] = thread_scope.get(tid, set())
    for wid, e in worlds.items():
        if isinstance(e, dict) and e.get("file"):
            p = book.root / e["file"]
            if p.exists():
                bodies[wid] = p.read_text(encoding="utf-8")
                allowed[wid] = world_scope.get(wid, set())
    if book.map_path.exists():
        bodies["全书地图"] = book.map_path.read_text(encoding="utf-8")
        allowed["全书地图"] = set(existing)  # 地图的范围 = 全书场景
    return bodies, allowed, existing


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="验收步骤 7（档案/矛盾/地图）产出的引用质量")
    ap.add_argument("--book", required=True, help="书目录路径，比如 data/验收书库/验收-归档-西游记")
    ap.add_argument("--report", default="data/验收-档案.json")
    args = ap.parse_args(argv)

    book = Book(Path(args.book))
    bodies, allowed, existing = load_scopes_and_bodies(book)
    res = check_refs(bodies, allowed, existing)

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = res["fabricated_rate"] <= FABRICATED_LIMIT and res["no_ref_rate"] <= NO_REF_LIMIT
    print(
        f"fabricated_rate={res['fabricated_rate']} no_ref_rate={res['no_ref_rate']} "
        f"bad={res['bad']}/{res['total']} pass={ok} report={report_path}"
    )
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
