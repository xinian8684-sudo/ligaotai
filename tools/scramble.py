"""把一本按「第X回」分好的书弄乱，生成带标准答案的乱稿，用来验收理稿台。

用法：
  uv run python tools/scramble.py --src data/xiyouji-pg23962.txt --out data/乱稿-西游记 --seed 7
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


def pick_excerpt(body: str, rng: random.Random) -> str:
    starts = [0] + para_cuts(body)
    cands = [(a, b) for a in starts for b in starts if 1200 <= b - a <= 2400 and b <= 2600]
    a, b = rng.choice(cands) if cands else (0, min(len(body), 2000))
    return body[a:b].strip()


def mutate(text: str, rng: random.Random, drop=0.08, modify=0.08, add=0.04) -> str:
    """按句子随机删、改、加。删掉的句子保留它开头的换行，段落结构不乱。"""
    out = []
    for s in _SENTENCE.split(text):
        r = rng.random()
        if s.strip() and r < drop:
            out.append(re.match(r"\s*", s).group(0))
        elif s.strip() and r < drop + modify:
            old, new = rng.choice(SUBS)
            out.append(s.replace(old, new, 1) if old in s else s + rng.choice(FILLERS))
        elif s.strip() and r < drop + modify + add:
            out.append(s + rng.choice(FILLERS))
        else:
            out.append(s)
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
    alias_log = [
        {**a, "chapters": sorted(rng.sample([c.num for c in kept], min(alias_chapters, len(kept))))}
        for a in aliases
    ]

    final: dict[int, tuple[str, str]] = {}
    truncated_log = []
    for c in kept:
        heading, body = c.heading, c.body
        if c.num in truncated:
            body = cut_at_ratio(body, rng.uniform(0.4, 0.7))
            truncated_log.append({"chapter": c.num, "kept_ratio": round(len(body) / len(c.body), 3)})
        for a in alias_log:
            if c.num in a["chapters"]:
                heading = heading.replace(a["replaces"], a["alias"])
                body = body.replace(a["replaces"], a["alias"])
        final[c.num] = (heading, body)

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
        excerpt_text = mutate(pick_excerpt(final[num][1], rng), rng, 0.03, 0.03, 0.02)
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
    args = ap.parse_args(argv)
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        sys.exit("output folder is not empty")
    raw = Path(args.src).read_text(encoding="utf-8")
    chapters = parse_chapters(strip_gutenberg(raw))
    key = scramble(chapters, out, args.seed)
    key_path = out.parent / f"{out.name}-答案.json"
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"chapters={len(chapters)} files={len(key['files'])} "
        f"deleted={len(key['deleted'])} variants={len(key['variants'])}"
    )


if __name__ == "__main__":
    main()
