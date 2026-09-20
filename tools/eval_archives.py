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
sys.path.insert(0, str(Path(__file__).resolve().parent))  # 自己所在目录，给 `from eval_threads import ...` 用

from ligaotai.archive import refs_in  # noqa: E402
from ligaotai.book import Book  # noqa: E402

_SENT = re.compile(r"[^。！？\n]+[。！？]?")
FABRICATED_LIMIT = 0.02
NO_REF_LIMIT = 0.10
RECALL_FLOOR = 0.8
_HIT_STATUS = ("真矛盾", "无法判断")  # 宁可多报：这两种在界面上一起显示，一起算召回


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


def recall(key: dict, chapter_scenes: dict[int, set[str]], result: dict) -> dict:
    """植入矛盾的召回（spec 9.1）：植入点所在章节的场景编号，出现在某个
    status ∈ {真矛盾, 无法判断} 的组里，且该组属性等于植入的属性，就算召回。"""
    groups = [g for g in (result.get("groups") or []) if g.get("status") in _HIT_STATUS]
    planted = key.get("contradictions") or []
    hit, misses = 0, []
    matched_ids = set()
    for p in planted:
        scenes = chapter_scenes.get(p["chapter"], set())
        found = None
        for g in groups:
            if g.get("attribute") != p["attribute"]:
                continue
            ids = {s["id"] for v in g.get("values") or [] for s in v.get("scenes") or []}
            if ids & scenes:
                found = g["id"]
                break
        if found:
            hit += 1
            matched_ids.add(found)
        else:
            misses.append(p)
    return {
        "planted": len(planted), "hit": hit,
        "recall": round(hit / len(planted), 4) if planted else 0.0,
        "misses": misses,
        # 误报只报数不设门槛——作者定了宁可多报，留着人工翻
        "false_positives": sum(1 for g in groups if g.get("status") == "真矛盾"
                               and g["id"] not in matched_ids),
    }


def chapter_to_scenes(book: Book, key: dict, folder_name: str) -> dict[int, set[str]]:
    """章节号 → 场景编号集合。答案文件记的是章节，S- 编号是导入时才分配的，
    所以要通过 key["files"] 的 path 和书的导入清单反查。

    直接复用 eval_threads.truth_positions——它返回 {场景编号: (章节, 段序, 段数)}，
    这边只要反过来聚合。别另起炉灶，两处读法不一致就会对不上。"""
    from eval_threads import truth_positions  # tools/ 已在 sys.path 里

    out: dict[int, set[str]] = {}
    for sid, pos in truth_positions(book, key, folder_name).items():
        out.setdefault(pos[0], set()).add(sid)
    return out


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
    ap = argparse.ArgumentParser(description="验收步骤 7（档案/矛盾/地图）产出的引用质量与植入矛盾召回")
    ap.add_argument("--book", required=True, help="书目录路径，比如 data/验收书库/验收-归档-西游记")
    ap.add_argument("--key", help="乱稿答案文件（含 --contradictions 植入的矛盾），给了就顺带算召回率")
    ap.add_argument("--folder", help="--key 对应的乱稿文件夹名（章节→场景映射要用），跟 --key 搭配必填")
    ap.add_argument("--report", default="data/验收-档案.json")
    args = ap.parse_args(argv)

    book = Book(Path(args.book))
    bodies, allowed, existing = load_scopes_and_bodies(book)
    refs = check_refs(bodies, allowed, existing)
    report: dict = {"refs": refs}
    ok = refs["fabricated_rate"] <= FABRICATED_LIMIT and refs["no_ref_rate"] <= NO_REF_LIMIT

    if args.key:
        if not args.folder:
            sys.exit("--key 需要搭配 --folder（乱稿文件夹名）")
        key = json.loads(Path(args.key).read_text(encoding="utf-8"))
        chapter_scenes = chapter_to_scenes(book, key, args.folder)
        result = {}
        if book.contradictions_path.exists():
            try:
                result = json.loads(book.contradictions_path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                result = {}
        rec = recall(key, chapter_scenes, result)
        report["recall"] = rec
        ok = ok and (rec["planted"] == 0 or rec["recall"] >= RECALL_FLOOR)

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"fabricated_rate={refs['fabricated_rate']} no_ref_rate={refs['no_ref_rate']} "
        f"bad={refs['bad']}/{refs['total']} recall={report.get('recall', {}).get('recall')} "
        f"pass={ok} report={report_path}"
    )
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
