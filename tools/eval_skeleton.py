"""计划④ 验收：骨架 + 导出的程序硬判据（spec 第 13 节）。

用法：
    uv run python tools/eval_skeleton.py --library data/验收书库 --book <书文件夹名> \
        --folder 乱稿-雪月梅-c --key data/乱稿-雪月梅-c-答案.json [--cut L-002] --report data/验收-骨架.json

五条判据（对应返回字典）：
1. 每块参与场景（主版本）在导出里恰好出现一次 —— each_once / duplicates / missing。
2. 导出场景顺序跟原书顺序的 Kendall τ ≥ 0.9 —— tau（`--key`/`--folder` 都给了才算，只看正文，
   不算「附：未定位」）。**给了 `--key` 但算出来 τ 是 None（没有可比较的块对）不算 pass**——
   那不是「没要求」，是「想验但验不出来」，不能悄悄放过（建议 8）。
3. 骨架里的空洞数 = 能定位的缺口数 —— holes_expected（重算）对 holes_in_skeleton（现存骨架），
   而且要比缺口**编号集合**（holes_missing / holes_extra），不只比个数——个数凑巧相等、
   编号对不上的情况比个数对不上更隐蔽。
4. 砍掉的线（`--cut`；不给就从看板现读 cut 列，建议 8）导出里不含它的场景 —— cut_leaks；
   空洞层面同理 —— cut_hole_leaks（M6：判据 4 原来只查了场景，没查「只属于砍掉线的缺口」
   有没有泄漏进骨架）。另外对每条 cut 线独立核一遍程序化影响的交汇点全不全
   —— crossing_mismatch（建议 9：拿 `impact.program_impact` 的结果跟直接从
   `threads.intersections` 算出来的原始交汇点比集合，不信任前者自己的过滤逻辑）。
5. 骨架里空洞说明（含未定位的）、AI 建议理由、伏笔影响的场景编号 0 条编造 —— fabricated_refs，
   对照 `known`（书里真实存在的场景文件）。

跟真实代码契约对齐的两点（计划草稿的示例代码没处理，这里按真实契约补上，见报告）：
- `skeleton._generate` / `skeleton.annotate` 认场景的规则是「主版本」：非主成员如果在
  `triage.version_map` 里能查到当前主版本，就换算成主版本（位置/时间沿用旧引用），只有
  主版本字段本身坏了、查不到替换目标的组才整组当丢弃。这里重算「应该出现的编号」时必须
  同样把 `version_map` 传给独立重算的逻辑，`drop` 也只用
  `non_main_versions(book) - set(vmap)`，不能拿全量 `non_main_versions(book)` 当 drop、又不换算
  主版本——不然换过主版本的组，这里算出来的「应该出现的编号」还是旧引用，导出里实际写的是新
  主版本编号，两边对不上会假报 missing，更糟的是主版本编号本来就该出现却从没被要求过，
  真的漏收也测不出来。
- 砍线泄漏的 `thread_of` 映射也跟 `export._cut_lookup` 一样，原始引用和主版本都映射到线编号，
  不然版本组换过主版本后，导出里真正出现的是主版本编号，原始映射查不到会漏判。
- 空洞说明的编造检查要看现存骨架里全部空洞的 `task`，不只是卷章正文里排上位置的那些——
  没锚点、进了 `unplaced.holes` 的空洞照样有说明文字，同样可能编号编造。

M5（审 3 必须修）：判据 1、3 原来拿 `skeleton_order.build_sequence`/`insert_holes`（生成器
本身用来排序、插空洞的那两个函数）算「应该出现的编号」——这是循环论证：生成器真的悄悄丢了
一条线的场景，期望值会跟着一起丢，两边一起错、判据照样绿。下面 `_expected_ids`/
`_expected_gap_ids` 直接从 `世界与支线.json` 的原始结构（`threads`/`unassigned`/`gaps` 列表）
独立重算，不调用 `skeleton_order` 里的任何函数——跟生成器的实现细节脱钩，生成器的排序/插入
逻辑本身有 bug 时这里才有机会抓到。定义上跟 `skeleton_order.py` 的文档字符串保持一致（谁的
规则对不上，那就是生成器的 bug，不是这里的定义错了——目前核对下来两边一致）。
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
from ligaotai.impact import program_impact  # noqa: E402
from ligaotai.scenes import load_scenes  # noqa: E402
from ligaotai.skeleton import load_skeleton, scene_info  # noqa: E402
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


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _col(cols: dict, tid) -> dict:
    return cols.get(tid) or {"col": "undecided", "merge_into": None}


def _resolve(sid0: str, vmap: dict[str, str], removed: set[str]) -> str | None:
    """跟 skeleton_order.build_sequence 的 resolve() 同一套规则（但独立实现，不调用它）：
    非主成员换算成组里当前主版本，换算后落在 removed（已移除 / 主版本字段坏的组）里就不算。
    这里不做「同一主版本只算一次」的去重判断——独立重算的是**集合**，集合本来就天然去重，
    不需要额外的 seen 状态。"""
    sid = vmap.get(sid0, sid0)
    return None if sid in removed else sid


def _expected_ids(threads: dict, cols: dict, removed: set[str],
                   vmap: dict[str, str]) -> tuple[set[str], set[str]]:
    """独立算「应该出现在导出里的场景编号」（正文 + 未定位一起，判据 1 用）和「真正排进
    正文时间轴、给空洞当锚点用的编号」（判据 3 用）。不调用 skeleton_order 里的任何函数，
    直接从 threads 原始的 threads/unassigned 列表重新推一遍。"""
    expected: set[str] = set()
    placed: set[str] = set()
    for t in threads.get("threads") or []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        if _col(cols, t["id"])["col"] == "cut":
            continue
        off = t.get("offset")
        times = t.get("times") or {}
        for sid0 in t.get("scenes") or []:
            sid = _resolve(sid0, vmap, removed)
            if sid is None:
                continue
            expected.add(sid)
            if _is_num(off):
                tm = times.get(sid0)
                tv = tm.get("t") if isinstance(tm, dict) else None
                if _is_num(tv):
                    placed.add(sid)
    for u in threads.get("unassigned") or []:
        sid0 = u.get("scene") if isinstance(u, dict) else u
        if isinstance(sid0, str):
            sid = _resolve(sid0, vmap, removed)
            if sid is not None:
                expected.add(sid)
    return expected, placed


def _expected_gap_ids(threads: dict, cols: dict, placed: set[str]) -> set[str]:
    """独立算「应该定位得到的缺口编号集合」：所属线没被砍、且 after 或 before 落在正文
    场景（`placed`，即真排进了时间轴的那些，不含「未定位」）里——跟
    skeleton_order.insert_holes 的锚点规则一致（它拿 build_sequence 排出的 seq 当锚点池），
    但从 threads.gaps 原始列表独立重算。"""
    out: set[str] = set()
    for g in threads.get("gaps") or []:
        if not isinstance(g, dict):
            continue
        gid = g.get("id")
        if not isinstance(gid, str) or not gid:
            continue
        if g.get("thread") and _col(cols, g["thread"])["col"] == "cut":
            continue
        if g.get("after") in placed or g.get("before") in placed:
            out.add(gid)
    return out


def _cut_hole_leaks(threads: dict, hole_placed: list[dict], hole_unplaced: list[dict],
                    cut: set[str]) -> list[str]:
    """M6：判据 4 原来只查场景层面的砍线泄漏，没查空洞——只属于被砍的线的缺口，理论上
    insert_holes 生成时就该跳过（不插进骨架），这里独立核一遍：现存骨架里（卷章内 +
    未定位）每个带 gap 字段的空洞，去 threads.gaps 查它原本所属的线，线在 cut 集合里
    就是泄漏。"""
    gap_thread = {g.get("id"): g.get("thread") for g in threads.get("gaps") or [] if isinstance(g, dict)}
    leaks = []
    for h in hole_placed + hole_unplaced:
        gid = h.get("gap")
        if isinstance(gid, str) and gid and gap_thread.get(gid) in cut:
            leaks.append(gid)
    return sorted(set(leaks))


def _crossing_mismatch(book: Book, threads: dict, cut: set[str]) -> list[str]:
    """建议 9：判据 4「交汇点全列」——对每条被砍的线，拿 `impact.program_impact` 算出来的
    交汇点，跟直接从 `threads.intersections` 原始列表筛出来的交汇点比集合（不信任
    program_impact 自己的过滤逻辑对不对），对不上的线编号列进报告。"""
    mismatched = []
    for tid in sorted(cut):
        expect = {(x.get("scene"), x.get("main_scene")) for x in threads.get("intersections") or []
                 if isinstance(x, dict) and x.get("thread") == tid}
        got = {(c.get("scene"), c.get("main_scene")) for c in program_impact(book, threads, tid)["crossings"]}
        if expect != got:
            mismatched.append(tid)
    return mismatched


def check_book(book: Book, truth: dict | None, cut: list[str] | None) -> dict:
    threads = load_threads(book)
    cols = columns(book, threads)
    info = scene_info(book)
    vmap = version_map(book)
    # 跟 skeleton._generate / skeleton.annotate 同一套丢块规则：非主版本能在 vmap 里查到替换
    # 目标的，不当丢弃（换算成主版本）；查不到替换目标（主版本字段坏了）的组才整组当丢弃。
    removed = {sid for sid, x in info.items() if x["removed"]} | (non_main_versions(book) - set(vmap))
    # 建议 8：--cut 没给（None）时默认从看板现读 cut 列，不强制每次都手填。
    if cut is None:
        cut = [tid for tid, c in cols.items() if c["col"] == "cut"]
    cut_set = set(cut)

    expected, placed = _expected_ids(threads, cols, removed, vmap)
    expected_gaps = _expected_gap_ids(threads, cols, placed)

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
    cut_leaks = sorted(s for s in counts if thread_of.get(s) in cut_set)

    sk = load_skeleton(book)
    hole_placed, hole_unplaced = _hole_items(sk)
    holes_in_skeleton = len(hole_placed)
    actual_gaps_placed = {h.get("gap") for h in hole_placed
                          if isinstance(h.get("gap"), str) and h.get("gap")}
    holes_missing = sorted(expected_gaps - actual_gaps_placed)
    holes_extra = sorted(actual_gaps_placed - expected_gaps)
    cut_hole_leaks = _cut_hole_leaks(threads, hole_placed, hole_unplaced, cut_set)
    crossing_mismatch = _crossing_mismatch(book, threads, cut_set)

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
        "holes_expected": len(expected_gaps),
        "holes_in_skeleton": holes_in_skeleton,
        "holes_missing": holes_missing, "holes_extra": holes_extra,
        "holes_unplaced_expected": len(hole_unplaced),
        "cut_leaks": cut_leaks,
        "cut_hole_leaks": cut_hole_leaks,
        "crossing_mismatch": crossing_mismatch,
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
    ap.add_argument("--cut", action="append", default=[], help="不给就从看板现读 cut 列")
    ap.add_argument("--report", default="data/验收-骨架.json")
    a = ap.parse_args(argv)
    book = open_book(Path(a.library), a.book)
    truth = None
    truth_requested = bool(a.key and a.folder)
    if truth_requested:
        key = json.loads(Path(a.key).read_text(encoding="utf-8"))
        truth = truth_positions(book, key, Path(a.folder).name)
    r = check_book(book, truth, a.cut or None)
    # 建议 8：给了 --key 就是真的想验顺序，算出来的 τ 是 None（没有可比较的块对）不能悄悄
    # 当「没要求」放过——那是「想验但验不出来」，得报不过。
    tau_ok = r["tau"] is not None and r["tau"] >= 0.9 if truth_requested else True
    r["pass"] = (r["each_once"] and not r["holes_missing"] and not r["holes_extra"]
                and not r["cut_leaks"] and not r["cut_hole_leaks"] and not r["crossing_mismatch"]
                and not r["fabricated_refs"] and tau_ok)
    write_json(Path(a.report), r)
    print(json.dumps({k: r[k] for k in ("pass", "each_once", "tau", "holes_expected", "holes_in_skeleton")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
