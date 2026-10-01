"""时间线检查验收：植入的 A / C 冲突召回（各 ≥ 4/5）、没命中归因、全部冲突写成人工核对表。

用法：
  uv run python tools/eval_timeline.py --library <书库> --book <书文件夹名> \
      --folder 乱稿-雪月梅-c --key data/乱稿-雪月梅-c-答案.json --report data/验收-时间线.json --review 核对.md
只读结果文件，不调模型。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ligaotai.book import open_book  # noqa: E402
from ligaotai.cards import load_cards  # noqa: E402
from ligaotai.timeline import _card, input_fingerprint, is_death, persons_of  # noqa: E402
from ligaotai.threads_input import name_map  # noqa: E402

FLOOR = 4  # 每类 5 处里至少抓到 4 处


def _canon(n, cmap):
    return cmap.get(("person", n), n)


def _who_variants(p: dict, cmap: dict) -> set[str]:
    """②b M4：答案里 p 的 who、name、人物名单（names）里他的全部叫法，都过 _canon 得到
    一个集合。旧实现只把 c.who 过 _canon，p["who"] 是原样比——p["who"] 来自 scramble 自己
    的人物名单（--characters），不一定跟书的 entities.json（cmap）算出的规范名一致
    （书里真正的规范名可能是「薰儿」，scramble 的人物名单写的是「萧薰儿」），两边不归一
    到同一个基准直接比较，会把本该命中的判成没命中。"""
    names = {p.get("who"), p.get("name"), *(p.get("names") or [])}
    return {_canon(n, cmap) for n in names if n}


def recall_timeline(key: dict, chapter_scenes: dict[int, set[str]], result: dict,
                    cmap: dict, cards: dict | None = None) -> dict:
    planted = key.get("timeline") or []
    confs = result.get("conflicts") or []
    out = {}
    for kind in ("A", "C"):
        ps = [p for p in planted if p["kind"] == kind]
        hit, misses = 0, []
        for p in ps:
            a_sc = chapter_scenes.get(p["chapters"][0], set())
            # C 类的事件可能跨几章（答案里的 span），A 类死后他说过话的章都算（speaks_in），
            # 范围里哪章的场都算；旧答案没这两个字段就是那一章
            if kind == "A":
                b_chs = p.get("speaks_in") or [p["chapters"][1]]
            else:
                lo, hi = p.get("span") or [p["chapters"][1]] * 2
                b_chs = range(lo, hi + 1)
            b_sc = set().union(*(chapter_scenes.get(ch, set()) for ch in b_chs))
            if kind == "A":
                who_set = _who_variants(p, cmap)
                ok = any(c.get("kind") == "A" and c["scenes"][0] in a_sc and c["scenes"][1] in b_sc
                         and _canon(c.get("who") or "", cmap) in who_set for c in confs)
            else:
                ok = any(c.get("kind") == "C" and c["scenes"][0] in a_sc and c["scenes"][1] in b_sc
                         and _c_ref_matches(c.get("ref") or "", p.get("event") or "") for c in confs)
            if ok:
                hit += 1
                continue
            m = dict(p)
            if cards is not None:
                m["cause"] = _cause_a(p, a_sc, b_sc, result, cards, cmap) if kind == "A" else _cause_c(p, a_sc, b_sc, result)
            misses.append(m)
        out[kind] = {"planted": len(ps), "hit": hit, "misses": misses,
                     "pass": len(ps) == 0 or hit >= min(FLOOR, len(ps))}
    return out


def _c_ref_matches(ref: str, event: str) -> bool:
    """②b S1：C 命中还要求 ref 确实是在讲这处植入——含 plant_foreknowledge 模板里的
    「想起那日」，或者跟被植入的事件原文有至少一个 2 字以上的连续重合片段。没有这条，
    场景对齐纯属巧合（那场恰好也有个别的、真实的回指）也会被算成命中。"""
    if not ref:
        return False
    if "想起那日" in ref:
        return True
    n = len(event)
    return any(event[i:j] in ref for i in range(n) for j in range(i + 2, n + 1))


def _cause_a(p, a_sc, b_sc, result, cards, cmap) -> str:
    who_set = _who_variants(p, cmap)
    died = any(is_death(f.get("attribute", ""), f.get("value", "")) and _canon(f.get("subject", ""), cmap) in who_set
               for s in a_sc for f in _card(cards, s).get("facts") or [] if isinstance(f, dict))
    if not died:
        return "死亡没被抽成 fact"
    if not any(who_set & persons_of(_card(cards, s), cmap) for s in b_sc):
        return "后一章的卡人物名单里没有他"
    if any(_canon(d["who"], cmap) in who_set and d["scenes"][1] in b_sc for d in result.get("dismissed") or []):
        return "模型判成只是提到"
    return "没进嫌疑（故事顺序里死亡场排在后面，或超了每人 5 场的上限）"


def _cause_c(p, a_sc, b_sc, result) -> str:
    # ②b S1：asked 也按 ref 过滤——a_sc 那场可能还有别的、跟这处植入无关的回指被问了，
    # 不按 ref 过滤会拿那条不相干的 asked 记录去诊断，说出错误的没命中原因。
    asked = [x for x in result.get("asked_refs") or []
            if x["scene"] in a_sc and _c_ref_matches(x.get("ref") or "", p.get("event") or "")]
    if not asked:
        return "没问到（回指没抽出来，或候选全在前面）"
    if not any(set(x["candidates"]) & b_sc for x in asked):
        return "候选里没有事件那一场"
    return "模型判错了场"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="evaluate timeline conflict check against planted answers")
    ap.add_argument("--library", required=True)
    ap.add_argument("--book", required=True)
    ap.add_argument("--folder", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--report", default="data/验收-时间线.json")
    ap.add_argument("--review", default="")
    args = ap.parse_args(argv)
    from eval_archives import chapter_to_scenes
    book = open_book(Path(args.library), args.book)
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    if not key.get("timeline"):
        sys.exit("答案文件里没有 timeline 植入，拿 scramble --deaths / --foreknowledge 重新生成")
    ch = chapter_to_scenes(book, key, Path(args.folder).name)
    result = json.loads(book.timeline_path.read_text(encoding="utf-8"))
    # ②b S5：结果文件本身不存 stale（那是 GET 接口现算的），验收脚本自己重算一次——
    # 拿旧结果判卷、书其实已经变了（比如又跑了一轮归线）会悄悄验收一份过期的数据。
    stale = result.get("fingerprint") != input_fingerprint(book)
    failed_n = len(result.get("failed") or [])
    rep = recall_timeline(key, ch, result, name_map(book), load_cards(book))
    Path(args.report).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.review:
        lines = ["# 时间线冲突人工核对", "", "每条标：书里真有的时间问题 / 我们的顺序排错 / 模型判错", ""]
        for c in result.get("conflicts") or []:
            lines += [f"## {c['id']} {c['kind']} {c.get('who') or c.get('ref')}", "",
                      f"- 场景：{c['scenes'][0]}（第 {c['pos'][0] + 1} 位）→ {c['scenes'][1]}（第 {c['pos'][1] + 1} 位）",
                      f"- 原文：{c['quotes'][0]} ／ {c['quotes'][1]}", f"- 模型：{c['reason']}", "- 判定：", ""]
        Path(args.review).write_text("\n".join(lines), encoding="utf-8")
    print(f"A {rep['A']['hit']}/{rep['A']['planted']} C {rep['C']['hit']}/{rep['C']['planted']} "
          f"pass={rep['A']['pass'] and rep['C']['pass']} stale={stale} failed_batches={failed_n} "
          f"report={args.report}")
    if stale:
        print("警告：时间冲突.json 的指纹跟当前书的状态对不上，结果可能是过期的，"
             "建议重新跑一次检查再验收", file=sys.stderr)
    if not (rep["A"]["pass"] and rep["C"]["pass"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
