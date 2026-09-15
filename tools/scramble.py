"""把一本按「第X回」分好的书弄乱，生成带标准答案的乱稿，用来验收理稿台。

用法：
  uv run python tools/scramble.py --src data/xiyouji-pg23962.txt --out data/乱稿-西游记 --seed 7
  uv run python tools/scramble.py --src data/pg26739.txt --out data/乱稿-雪月梅 --seed 7 --aliases data/别名-雪月梅.json
生成乱稿文件夹 <out>/ 和标准答案 <out>-答案.json（答案放在文件夹外面，免得被一起导入）。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from docx import Document

from ligaotai.split import split_text

DEFAULT_ALIASES = [
    {"replaces": "悟空", "alias": "金箍郎", "canonical": "孫悟空"},
    {"replaces": "八戒", "alias": "天蓬郎", "canonical": "豬八戒"},
    {"replaces": "唐僧", "alias": "御弟師父", "canonical": "唐三藏"},
]
FOLDERS = ["", "旧稿", "备份/2019", "备份/2020-重写", "手机导出", "杂"]
FILLERS = ["他心下暗暗思量。", "一時間無人答話。", "眾人都不做聲。", "這話且按下不題。"]
SUBS = [("道：", "說道："), ("卻", "却"), ("那", "這"), ("了", "咧")]
T_START, T_END = 1514736000, 1703980800  # 2018-01-01 ~ 2023-12-31

_HEADING = re.compile(r"^[ \t\u3000]*第\S{1,4}回.*$", re.M)
_PARA_BREAK = re.compile(r"\n(?:[ \t\u3000]*\n)+")
_LEADING_BLANK = re.compile(r"^(?:[ \t\u3000]*\n)+")
_SENTENCE = re.compile(r"(?<=[。！？])")


@dataclass
class Chapter:
    num: int      # 从 1 起
    heading: str  # 回目那一行，去掉首尾空白
    body: str     # 回目之后的正文，去掉开头空行和结尾空白


def strip_gutenberg(raw: str) -> str:
    raw = raw.replace("\r\n", "\n")
    s, e = raw.find("*** START OF"), raw.find("*** END OF")
    if s == -1 or e == -1:
        return raw
    body = raw[raw.index("\n", s) + 1 : e]
    return re.sub(r"^Produced by.*$", "", body, flags=re.M)


def parse_chapters(body: str) -> list[Chapter]:
    ms = list(_HEADING.finditer(body))
    chapters = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(body)
        text = _LEADING_BLANK.sub("", body[m.end() + 1 : end]).rstrip()
        chapters.append(Chapter(i + 1, m.group(0).strip(" \t\u3000"), text))
    return chapters


def para_cuts(body: str) -> list[int]:
    return [m.start() for m in _PARA_BREAK.finditer(body)]


def cut_at_ratio(body: str, ratio: float) -> str:
    cuts = para_cuts(body)
    target = len(body) * ratio
    pos = min(cuts, key=lambda c: abs(c - target)) if cuts else int(target)
    return body[:pos].rstrip()


def split_body(body: str, k: int) -> list[str]:
    cuts = para_cuts(body)
    if k <= 1 or not cuts:
        return [body]
    chosen = sorted({min(cuts, key=lambda c: abs(c - len(body) * j / k)) for j in range(1, k)})
    pieces, prev = [], 0
    for c in chosen:
        pieces.append(body[prev:c].strip("\n"))
        prev = c
    pieces.append(body[prev:].strip("\n"))
    return [p for p in pieces if p.strip()]


def _pick_excerpt_span(heading: str, body: str, rng: random.Random) -> tuple[int, int]:
    """在这一回「原始单文件」（回目+正文）里选一个 1200-2400 字的整段落窗口，
    窗口必须落在 split.py 按场景切出的同一个块里，不然片段会横跨两个场景，
    验收时没法判断它该跟哪个场景块比对。"""
    file_text = f"{heading}\n\n{body}"
    body_start = len(heading) + 2  # 跳过回目那一行和它后面的空行
    blocks = split_text(file_text)
    first_big = next((blk for blk in blocks if blk.end - blk.start >= 1500), None)
    if first_big is not None:
        lo = max(first_big.start, body_start)
        bounds = sorted(
            {first_big.start, first_big.end}
            | {
                body_start + c
                for c in para_cuts(body)
                if first_big.start <= body_start + c <= first_big.end
            }
        )
        cands = sorted(
            (a, b)
            for a in bounds
            for b in bounds
            if a >= lo and b <= first_big.end and 1200 <= b - a <= 2400
        )
        if cands:
            return rng.choice(cands)
    # 兜底：没有 >=1500 字的场景块，或者块里凑不出合适的窗口，就退回最长的那个块，
    # 从回目那行之后开始，最多截前 2000 字。
    block = max(blocks, key=lambda b: b.end - b.start)
    lo = max(block.start, body_start)
    return lo, min(block.end, lo + 2000)


def pick_excerpt(heading: str, body: str, rng: random.Random) -> str:
    a, b = _pick_excerpt_span(heading, body, rng)
    return f"{heading}\n\n{body}"[a:b].strip()


def mutate(text: str, rng: random.Random, drop=0.08, modify=0.08, add=0.04) -> str:
    """按句子随机删、改、加。

    删掉一句时不能连它开头的换行一起留下——如果那句本来是缩进诗行（前面是
    换行 + 全角空格），留下缩进会变成一行「看起来空、实际有全角空格」的行，
    被 split.py 当成空行，两行这样的就拼成假的场景分隔。规则：删句不留任何
    痕迹，但记住它开头换行的「强度」（\\n 的个数）；下一句保留时，如果它自己
    开头的换行强度不如被删句子的强，就用被删句子的换行 + 自己的缩进来补上，
    这样两句保留下来的句子之间的换行强度，绝不会超过原文里两者之间本来的强度。
    """
    out: list[str] = []
    pending = ""  # 被删句子里最强的那个「换行前缀」，留给下一个保留的句子
    for s in _SENTENCE.split(text):
        lead = re.match(r"\s*", s).group(0)
        nl = lead.rfind("\n")
        brk = lead[: nl + 1] if nl != -1 else ""
        indent = lead[len(brk):]
        body = s[len(lead):]
        r = rng.random()
        if body and r < drop:
            if brk.count("\n") > pending.count("\n"):
                pending = brk
            continue
        if pending.count("\n") > brk.count("\n"):
            lead = pending + indent
        pending = ""
        if body and r < drop + modify:
            old, new = rng.choice(SUBS)
            body = body.replace(old, new, 1) if old in body else body + rng.choice(FILLERS)
        elif body and r < drop + modify + add:
            body = body + rng.choice(FILLERS)
        out.append(lead + body)
    return "".join(out)


class NameGen:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.used: set[str] = set()

    def next(self, fmt: str) -> str:
        while True:
            n = self.rng.randint(1, 999)
            stem = self.rng.choice([
                f"新建文本文档 ({n})", f"草稿{n:03d}", f"片段_{self.rng.randrange(16**4):04x}",
                f"未命名{n}", f"稿子{n}", f"{n}",
            ])
            folder = self.rng.choice(FOLDERS)
            rel = f"{folder}/{stem}.{fmt}" if folder else f"{stem}.{fmt}"
            if rel not in self.used:
                self.used.add(rel)
                return rel


def write_file(path: Path, text: str, fmt: str, enc: str, heading_first: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "docx":
        doc = Document()
        for i, line in enumerate(text.split("\n")):
            if i == 0 and heading_first:
                doc.add_heading(line, level=1)
            else:
                doc.add_paragraph(line)
        doc.save(str(path))
    else:
        path.write_bytes(text.encode(enc))


def scramble(
    chapters: list[Chapter],
    out_dir: Path,
    seed: int,
    aliases: list[dict] = DEFAULT_ALIASES,
    n_delete: int = 5,
    n_truncate: int = 5,
    n_full: int = 10,
    n_excerpt: int = 5,
    alias_chapters: int = 15,
) -> dict:
    rng = random.Random(seed)
    source_text = "\n".join(f"{c.heading}\n{c.body}" for c in chapters)
    for a in aliases:
        if a["alias"] in source_text:
            raise ValueError(f"alias already appears in source: {a['alias']}")

    pool = [c.num for c in chapters[1:-1]]

    def take(k: int) -> list[int]:
        chosen = sorted(rng.sample(pool, k))
        pool[:] = [x for x in pool if x not in chosen]
        return chosen

    deleted = take(n_delete)
    truncated = take(n_truncate)
    full = take(n_full)
    excerpt = take(n_excerpt)
    kept = [c for c in chapters if c.num not in deleted]

    # 先把截断做完：别名要挑「截断之后的正文里真的还有这个词」的章节，不然会挑到
    # 词恰好被切掉了的章节，答案里写着有别名、实际打开文件搜不到（空跑）。
    truncated_log = []
    after_truncate: dict[int, tuple[str, str]] = {}
    for c in kept:
        heading, body = c.heading, c.body
        if c.num in truncated:
            body = cut_at_ratio(body, rng.uniform(0.4, 0.7))
            truncated_log.append({"chapter": c.num, "kept_ratio": round(len(body) / len(c.body), 3)})
        after_truncate[c.num] = (heading, body)

    alias_log = []
    for a in aliases:
        candidates = [
            num for num, (heading, body) in after_truncate.items() if a["replaces"] in heading + body
        ]
        chosen = sorted(rng.sample(candidates, min(alias_chapters, len(candidates))))
        alias_log.append({**a, "chapters": chosen})

    final: dict[int, tuple[str, str]] = {}
    for num, (heading, body) in after_truncate.items():
        for a in alias_log:
            if num in a["chapters"]:
                heading = heading.replace(a["replaces"], a["alias"])
                body = body.replace(a["replaces"], a["alias"])
        final[num] = (heading, body)

    files: list[dict] = []
    for c in kept:
        heading, body = final[c.num]
        k = 1 if c.num in full or c.num in excerpt else rng.choice([1, 1, 2, 2, 3])
        pieces = split_body(body, k)
        for i, piece in enumerate(pieces, 1):
            files.append({
                "text": f"{heading}\n\n{piece}" if i == 1 else piece,
                "chapter": c.num, "piece": i, "pieces": len(pieces),
                "kind": "original", "heading_first": i == 1,
            })
    for num in full:
        heading, body = final[num]
        files.append({
            "text": f"{heading}\n\n{mutate(body, rng)}", "chapter": num, "piece": 1,
            "pieces": 1, "kind": "variant_full", "heading_first": True,
        })
    for num in excerpt:
        heading, body = final[num]
        excerpt_text = mutate(pick_excerpt(heading, body, rng), rng, 0.03, 0.03, 0.02)
        files.append({
            "text": excerpt_text, "chapter": num, "piece": 1, "pieces": 1,
            "kind": "variant_excerpt", "heading_first": False,
        })

    rng.shuffle(files)
    names = NameGen(rng)
    for f in files:
        fmt = rng.choices(["txt", "md", "docx"], weights=[7, 2, 1])[0]
        enc = "docx" if fmt == "docx" else ("gb18030" if fmt == "txt" and rng.random() < 0.15 else "utf-8")
        rel = names.next(fmt)
        path = out_dir / rel
        write_file(path, f.pop("text"), fmt, enc, f.pop("heading_first"))
        t = rng.uniform(T_START, T_END)
        os.utime(path, (t, t))
        f.update(path=rel, format=fmt, encoding=enc)

    original_of = {f["chapter"]: f["path"] for f in files if f["kind"] == "original" and f["pieces"] == 1}
    variants = [
        {"chapter": f["chapter"], "kind": f["kind"], "file": f["path"], "original_file": original_of[f["chapter"]]}
        for f in files
        if f["kind"] != "original"
    ]
    variants.sort(key=lambda v: (v["chapter"], v["kind"]))
    files.sort(key=lambda f: f["path"])
    return {
        "seed": seed,
        "chapters": len(chapters),
        "deleted": deleted,
        "truncated": truncated_log,
        "variants": variants,
        "aliases": alias_log,
        "files": files,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="scramble a chaptered book into a messy manuscript")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--aliases", help="JSON 文件：替换规则列表，每条有 replaces / alias / canonical；不给就用西游记的默认别名")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        sys.exit("output folder is not empty")
    raw = Path(args.src).read_text(encoding="utf-8")
    chapters = parse_chapters(strip_gutenberg(raw))
    aliases = json.loads(Path(args.aliases).read_text(encoding="utf-8")) if args.aliases else DEFAULT_ALIASES
    key = scramble(chapters, out, args.seed, aliases=aliases)
    key_path = out.parent / f"{out.name}-答案.json"
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"chapters={len(chapters)} files={len(key['files'])} "
        f"deleted={len(key['deleted'])} variants={len(key['variants'])}"
    )


if __name__ == "__main__":
    main()
