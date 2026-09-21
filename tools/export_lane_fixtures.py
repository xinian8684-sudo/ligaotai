"""把验收书库里的归线结果瘦身成前端泳道图测试用的 fixture。

长文本字段截断到 60 字，**结构和数值一个不动**：体积小下来，但
「offset 差三个数量级」「times[sid].t 有 null」「gaps 只有 before」
「gaps 两端都没有」这些会写错的真实形态全留着。

用法：
  uv run python tools/export_lane_fixtures.py
终端只打 ASCII，中文内容看导出的 json。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_SRC = REPO / "data" / "验收书库"
DEFAULT_OUT = REPO / "web" / "src" / "components" / "__fixtures__"

SOURCES = {
    "xiyouji-threads.json": "验收-实体-乱稿-西游记-s7",
    "xueyuemei-threads.json": "验收-实体-乱稿-雪月梅-c-s7",
}

# 只截长文本。**别把 scenes / times / gaps / offset 之类结构性字段列进来。**
LONG_TEXT_KEYS = ("about", "reason", "note", "event", "name")
LIMIT = 60


def shrink(obj):
    if isinstance(obj, dict):
        return {
            k: (cut(v) if k in LONG_TEXT_KEYS and isinstance(v, str) else shrink(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [shrink(x) for x in obj]
    if isinstance(obj, str):
        return obj
    return obj


def cut(s: str) -> str:
    return s if len(s) <= LIMIT else s[:LIMIT] + "…"


def main() -> int:
    ap = argparse.ArgumentParser(description="export lane-chart fixtures")
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC, help="acceptance library dir")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="fixture output dir")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    missing = []
    for filename, book in SOURCES.items():
        src = args.src / book / "世界与支线.json"
        if not src.exists():
            missing.append(str(src))
            continue
        data = json.loads(src.read_text(encoding="utf-8"))
        out = args.out / filename
        out.write_text(
            json.dumps(shrink(data), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(
            f"{filename}: {len(data['threads'])} threads, "
            f"{len(data.get('gaps') or [])} gaps, {out.stat().st_size // 1024} KB"
        )
    if missing:
        print("source files not found (normal if the acceptance library was never run):")
        for s in missing:
            print("  " + s)
        return 1 if len(missing) == len(SOURCES) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
