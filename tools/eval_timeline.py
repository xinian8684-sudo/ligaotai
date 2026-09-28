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
from ligaotai.timeline import _card, is_death, persons_of  # noqa: E402
from ligaotai.threads_input import name_map  # noqa: E402

FLOOR = 4  # 每类 5 处里至少抓到 4 处


def _canon(n, cmap):
    return cmap.get(("person", n), n)


def recall_timeline(key: dict, chapter_scenes: dict[int, set[str]], result: dict,
                    cmap: dict, cards: dict | None = None) -> dict:
    planted = key.get("timeline") or []
    confs = result.get("conflicts") or []
    out = {}
    for kind in ("A", "C"):
        ps = [p for p in planted if p["kind"] == kind]
        hit, misses = 0, []
        for p in ps:
            a_sc, b_sc = (chapter_scenes.get(ch, set()) for ch in p["chapters"])
            ok = any(c.get("kind") == kind and c["scenes"][0] in a_sc and c["scenes"][1] in b_sc
                     and (kind == "C" or _canon(c.get("who") or "", cmap) == p["who"]) for c in confs)
            if ok:
                hit += 1
                continue
            m = dict(p)
            if cards is not None:
                m["cause"] = _cause_a(p, a_sc, b_sc, result, cards, cmap) if kind == "A" else _cause_c(a_sc, b_sc, result)
            misses.append(m)
        out[kind] = {"planted": len(ps), "hit": hit, "misses": misses,
                     "pass": len(ps) == 0 or hit >= min(FLOOR, len(ps))}
    return out


def _cause_a(p, a_sc, b_sc, result, cards, cmap) -> str:
    died = any(is_death(f.get("attribute", ""), f.get("value", "")) and _canon(f.get("subject", ""), cmap) == p["who"]
               for s in a_sc for f in _card(cards, s).get("facts") or [] if isinstance(f, dict))
    if not died:
        return "死亡没被抽成 fact"
    if not any(p["who"] in persons_of(_card(cards, s), cmap) for s in b_sc):
        return "后一章的卡人物名单里没有他"
    if any(_canon(d["who"], cmap) == p["who"] and d["scenes"][1] in b_sc for d in result.get("dismissed") or []):
        return "模型判成只是提到"
    return "没进嫌疑（故事顺序里死亡场排在后面，或超了每人 5 场的上限）"


def _cause_c(a_sc, b_sc, result) -> str:
    asked = [x for x in result.get("asked_refs") or [] if x["scene"] in a_sc]
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
          f"pass={rep['A']['pass'] and rep['C']['pass']} report={args.report}")
    if not (rep["A"]["pass"] and rep["C"]["pass"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
