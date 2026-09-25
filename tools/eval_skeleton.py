"""计划④ 验收：骨架 + 导出的程序硬判据（spec 第 13 节）。

用法：
    uv run python tools/eval_skeleton.py --library data/验收书库 --book <书文件夹名> \
        --folder 乱稿-雪月梅-c --key data/乱稿-雪月梅-c-答案.json [--cut L-002] --report data/验收-骨架.json

五条判据（对应返回字典）：
1. 每块参与场景（主版本）在导出里恰好出现一次 —— each_once / duplicates / missing。
2. 导出场景顺序跟原书顺序的 Kendall τ ≥ 0.9 —— tau（`--key`/`--folder` 都给了才算，只看正文，
   不算「附：未定位」）。
3. 骨架里的空洞数 = 能定位的缺口数 —— holes_expected（重算）对 holes_in_skeleton（现存骨架）。
4. 砍掉的线（`--cut`）导出里不含它的场景 —— cut_leaks。这条判据是对「砍线后重新生成骨架再
   导出」而言的：`skeleton_order.build_sequence`/`insert_holes` 生成时会把 cut 列的线整条跳过，
   所以只要骨架是刚生成、没手改过，判据 3（空洞数对不上）会先一步抓出「线砍了但骨架没跟着
   重生成」的情况；这里只单独核对场景层面有没有泄漏。程序化影响（`impact.program_impact`）
   本身是从当前 `threads.intersections` 纯计算出来的，不经过任何缓存/落盘，天然不会漏交汇点
   （读过源码确认：遍历的是全部 `intersections`，没有会丢条目的过滤分支），这一层由
   `tests/test_impact.py` 覆盖，这里不重复造一遍同样的逻辑再拿它来验它自己。
5. 骨架里空洞说明（含未定位的）、AI 建议理由、伏笔影响的场景编号 0 条编造 —— fabricated_refs，
   对照 `known`（书里真实存在的场景文件）。

跟真实代码契约对齐的两点（计划草稿的示例代码没处理，这里按真实契约补上，见报告）：
- `skeleton._generate` / `skeleton.annotate` 认场景的规则是「主版本」：非主成员如果在
  `triage.version_map` 里能查到当前主版本，就换算成主版本（位置/时间沿用旧引用），只有
  主版本字段本身坏了、查不到替换目标的组才整组当丢弃。这里重算「应该出现的编号」时必须
  同样把 `version_map` 传给 `build_sequence`，`drop` 也只用
  `non_main_versions(book) - set(vmap)`，不能拿全量 `non_main_versions(book)` 当 drop、又不传
  vmap——不然换过主版本的组，这里算出来的「应该出现的编号」还是旧引用，导出里实际写的是新
  主版本编号，两边对不上会假报 missing，更糟的是主版本编号本来就该出现却从没被要求过，
  真的漏收也测不出来。
- 砍线泄漏的 `thread_of` 映射也跟 `export._cut_lookup` 一样，原始引用和主版本都映射到线编号，
  不然版本组换过主版本后，导出里真正出现的是主版本编号，原始映射查不到会漏判。
- 空洞说明的编造检查要看现存骨架里全部空洞的 `task`，不只是卷章正文里排上位置的那些——
  没锚点、进了 `unplaced.holes` 的空洞照样有说明文字，同样可能编号编造。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ligaotai.archive import refs_in  # noqa: E402
from ligaotai.book import Book, open_book  # noqa: E402
from ligaotai.export import export_path  # noqa: E402
from ligaotai.fsutil import read_json, write_json  # noqa: E402
from ligaotai.scenes import load_scenes  # noqa: E402
from ligaotai.skeleton import load_skeleton, scene_info  # noqa: E402
from ligaotai.skeleton_order import build_sequence, insert_holes  # noqa: E402
from ligaotai.threads_ops import load_threads  # noqa: E402
from ligaotai.triage import columns, non_main_versions, version_map  # noqa: E402
from tools.eval_threads import kendall_tau_b, truth_positions  # noqa: E402

_MARK = re.compile(r"^<!-- (S-\d{4,}) -->$", re.M)


def _body_md(md: str) -> str:
    """去掉书末「附：未定位」一节，只看正文。"""
    cut = md.find("\n# 附：未定位")
    return md if cut < 0 else md[:cut]


def _hole_items(sk: dict) -> tuple[list[dict], list[dict]]:
    """骨架里全部空洞条目：(排上卷章位置的, 落在 unplaced.holes 里的)。"""
    placed = [it for v in sk["volumes"] for ch in v["chapters"] for it in ch["items"] if it.get("type") == "hole"]
    unplaced = [x for x in (sk.get("unplaced") or {}).get("holes") or [] if isinstance(x, dict)]
    return placed, unplaced


def check_book(book: Book, truth: dict | None, cut: list[str]) -> dict:
    threads = load_threads(book)
    cols = columns(book, threads)
    info = scene_info(book)
    vmap = version_map(book)
    # 跟 skeleton._generate / skeleton.annotate 同一套丢块规则：非主版本能在 vmap 里查到替换
    # 目标的，不当丢弃（换算成主版本）；查不到替换目标（主版本字段坏了）的组才整组当丢弃。
    removed = {sid for sid, x in info.items() if x["removed"]} | (non_main_versions(book) - set(vmap))
    seq, unplaced = build_sequence(threads, cols, removed, vmap)
    items, holes_unplaced = insert_holes(seq, threads.get("gaps") or [], cols)
    expected = [x["id"] for x in seq] + [u["id"] for u in unplaced]

    md = export_path(book, "md").read_text(encoding="utf-8")
    all_ids = _MARK.findall(md)
    body_ids = _MARK.findall(_body_md(md))
    counts: dict[str, int] = {}
    for s in all_ids:
        counts[s] = counts.get(s, 0) + 1
    duplicates = sorted(s for s, n in counts.items() if n > 1)
    missing = sorted(s for s in expected if s not in counts)

    # 砍线泄漏：跟 export._cut_lookup 同一套 thread_of——原始引用和（如果换过版本）当前主版本
    # 都映射到线编号，不然版本组换过主版本后，导出里真正写的是主版本编号，原始映射查不到。
    thread_of: dict[str, str] = {}
    for t in threads.get("threads") or []:
        if isinstance(t, dict) and t.get("id"):
            for sid0 in t.get("scenes") or []:
                thread_of.setdefault(sid0, t["id"])
                thread_of.setdefault(vmap.get(sid0, sid0), t["id"])
    cut_leaks = sorted(s for s in counts if thread_of.get(s) in set(cut))

    sk = load_skeleton(book)
    hole_placed, hole_unplaced = _hole_items(sk)
    holes_in_skeleton = len(hole_placed)
    known = {s.id for s in load_scenes(book)}
    texts = [it.get("task", "") for it in hole_placed + hole_unplaced]
    adv = read_json(book.advice_path, {}) or {}
    texts += [i.get("reason", "") for i in adv.get("items") or []]
    imp = read_json(book.impact_path, {}) or {}
    for x in imp.values():
        texts.append(x.get("remedy", ""))
        texts += [f"[{p.get('planted')}] [{p.get('resolved')}]" for p in x.get("pairs") or []]
    fabricated = sorted({r for t in texts for r in refs_in(str(t)) if r not in known})

    tau = None
    if truth:
        ranked = [s for s in body_ids if s in truth]
        tau, _ = kendall_tau_b(list(range(len(ranked))), [truth[s] for s in ranked])

    return {
        "each_once": not duplicates and not missing,
        "duplicates": duplicates, "missing": missing,
        "holes_expected": sum(1 for i in items if i["type"] == "hole"),
        "holes_in_skeleton": holes_in_skeleton,
        "holes_unplaced_expected": len(holes_unplaced),
        "cut_leaks": cut_leaks,
        "fabricated_refs": fabricated,
        "tau": tau,
        "scenes_in_body": len(body_ids),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="check skeleton/export against the acceptance criteria")
    ap.add_argument("--library", default="data/验收书库")
    ap.add_argument("--book", required=True)
    ap.add_argument("--folder", help="乱稿文件夹名（算 τ 用）")
    ap.add_argument("--key", help="答案文件（算 τ 用）")
    ap.add_argument("--cut", action="append", default=[])
    ap.add_argument("--report", default="data/验收-骨架.json")
    a = ap.parse_args(argv)
    book = open_book(Path(a.library), a.book)
    truth = None
    if a.key and a.folder:
        key = json.loads(Path(a.key).read_text(encoding="utf-8"))
        truth = truth_positions(book, key, Path(a.folder).name)
    r = check_book(book, truth, a.cut)
    r["pass"] = (r["each_once"] and r["holes_expected"] == r["holes_in_skeleton"] and not r["cut_leaks"]
                 and not r["fabricated_refs"] and (r["tau"] is None or r["tau"] >= 0.9))
    write_json(Path(a.report), r)
    print(json.dumps({k: r[k] for k in ("pass", "each_once", "tau", "holes_expected", "holes_in_skeleton")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
