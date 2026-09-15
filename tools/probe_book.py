"""真跑验收前的「熟悉度」探测：不给原文，只问模型记不记得这本书各回讲了什么。

模型能按顺序大致说出多数回目的情节，说明它背过这本书，拿它做顺序验收会偏乐观（它可以凭记忆排），
要换一本。报告里把模型的回答和原书的回目并排放，人工对照判断。一次综合档调用，花费几美分。

用法：
  uv run python tools/probe_book.py --title 雪月梅傳 --src data/pg26739.txt --report data/验收-熟悉度-雪月梅傳.json
终端只打 ASCII，中文内容看报告文件。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from ligaotai.config import AppConfig, load_config
from ligaotai.llm import ChatBackend, FatalLLMError, LLMClient, LLMError, NoKeyError, OpenAIBackend
from ligaotai.threads_check import text

if __package__ in (None, ""):  # 按脚本路径跑（uv run python tools/probe_book.py）时，仓库根不在 sys.path 里
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.scramble import Chapter, parse_chapters, strip_gutenberg  # noqa: E402

SYSTEM = "你是中国古典小说专家。只凭记忆回答，记不清就老实说记不清，不要编。只输出一个 json 对象。"
USER = (
    "清代小说《{title}》一共 {n} 回。请凭记忆，按顺序写出每一回的主要情节，每回一句话；记不清的回写 null。"
    "known 说明你对这本书熟不熟，只能是「熟悉」「有印象」「不知道」。\n"
    '格式（示例）：{{"known": "有印象", "chapters": [{{"n": 1, "plot": "……"}}, {{"n": 2, "plot": null}}]}}'
)


def _check(d: dict) -> list[str]:
    return [] if isinstance(d.get("chapters"), list) else ["缺少 chapters 列表"]


def _chapter_n(v) -> int | None:
    """回数：不是 bool 的 int/float/字符串才收；转不成有限整数（含 bool、Infinity、非数字字符串）返回 None。"""
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return None


def _plot(v) -> str | None:
    """情节：只收字符串（去掉首尾空白后非空），其他（数字、字典、列表、空串、纯空白）都当 None。"""
    if not isinstance(v, str):
        return None
    v = v.strip()
    return v or None


def probe(title: str, chapters: list[Chapter], cfg: AppConfig, backend: ChatBackend) -> dict:
    client = LLMClient(cfg, backend)
    data, problems = asyncio.run(
        client.chat_json("synth", SYSTEM, USER.format(title=title, n=len(chapters)), _check, tag="probe")
    )
    answers: dict[int, str | None] = {}
    for c in data.get("chapters") or []:
        if not isinstance(c, dict):
            continue
        n = _chapter_n(c.get("n"))
        if n is None:
            continue
        answers.setdefault(n, _plot(c.get("plot")))  # 同一回写了两次，留第一次
    rows = [{"n": c.num, "heading": c.heading, "model": answers.get(c.num)} for c in chapters]
    return {
        "title": title,
        "known": text(data.get("known")),
        "answered": sum(1 for r in rows if r["model"]),
        "chapters": len(rows),
        "rows": rows,
        "problems": problems,
        "calls": client.usage.calls,
        "cost_usd": round(client.usage.cost(cfg), 4),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="ask the model whether it remembers a book before using it for evaluation")
    ap.add_argument("--title", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args(argv)
    cfg = load_config()
    try:
        backend = OpenAIBackend(cfg)
    except NoKeyError:
        sys.exit("no API key configured (config.json api_key or env LIGAOTAI_API_KEY)")
    raw = Path(args.src).read_text(encoding="utf-8")
    chapters = parse_chapters(strip_gutenberg(raw))
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    error_path = report_path.with_name(report_path.stem + "-error.json")
    try:
        report = probe(args.title, chapters, cfg, backend)
    except LLMError as e:
        partial = {"error": f"{type(e).__name__}: {e}"}
        error_path.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")
        kind = "fatal" if isinstance(e, FatalLLMError) else "a step"
        sys.exit(f"{kind} model error, see the -error report next to your --report path")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    error_path.unlink(missing_ok=True)
    print(f"answered={report['answered']}/{report['chapters']} calls={report['calls']} cost_usd={report['cost_usd']}")


if __name__ == "__main__":
    main()
