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

from ligaotai import hanfold
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


_TRAD_CHARS = frozenset(hanfold._TRAD)
_SIMP_CHARS = frozenset(hanfold._SIMP)


def _script_of(text: str) -> str:
    """粗略判断一段文本整体是简体还是繁体：数繁体专属字符和简体专属字符各出现多少次，
    谁多算谁（`hanfold` 那张表的 2473 对字形几乎不重叠，样本一大，多数书几千字以内
    就能分出胜负）。只用来决定植入新值时写哪种字形，不做任何文本转换、不追求识别单字。"""
    trad = sum(1 for ch in text if ch in _TRAD_CHARS)
    simp = sum(1 for ch in text if ch in _SIMP_CHARS)
    return "trad" if trad > simp else "simp"


# 年龄池：两个值要差得够远，差一两岁会被判成「合理变化」，测不出东西。
_AGES = [14, 16, 18, 20, 22, 24, 28, 32, 36, 40, 46, 52]
_AGE_GAP = 4  # 同一处矛盾的两个值至少差这么多岁
_CN_DIGITS = "〇一二三四五六七八九"


def _cn_number(n: int) -> str:
    """阿拉伯数字转汉字（只需要 10-99，年龄够用）。"""
    if n < 10:
        return _CN_DIGITS[n]
    tens, ones = divmod(n, 10)
    head = "" if tens == 1 else _CN_DIGITS[tens]
    return f"{head}十{_CN_DIGITS[ones] if ones else ''}"


def plant_contradictions(chapters: list[Chapter], rng: random.Random, n: int,
                          characters: list[dict] | None = None,
                          skip: set[int] | None = None,
                          avoid: set[str] | None = None) -> list[dict]:
    """植入 n 处人造矛盾：给一个人物在**两个不同章节**各插一句年龄陈述，数值不同。
    就地改 chapters 的 body，一个章节最多参与一处。

    ## 为什么不再用「把原文里的词换成另一个词」

    旧实现找原文里的锚点词（金箍棒/十六/红衣…）替换成同类的另一个值。那**造不出矛盾**：
    矛盾要两处说法并存，而替换改掉的是原值——这个词在书里只出现这一次的话，改完全书自洽。
    2026-09-21 真跑《雪月梅传》实测：10 处植入里 7 处从来就不是矛盾（3 处压根没被抽成
    fact、2 处那个 (主语,属性) 全书只有一个值、2 处属性/主语跑偏），召回 3/10，而命中的
    3 处全部落在书里本来就被反复提到的人物年龄上。详见 docs/验收记录/2026-09-21-计划2c-档案矛盾地图.md。

    换成「插一对说法」之后，每处植入天然满足三个条件：主语相同、两处说法并存、
    属性是模型确实会抽成 fact 的那类（年龄）。**这是个下限测试**——矛盾造得直白，
    测的是「这么明显的前后不一致能不能发现」，不能拿它的高分宣称产品多强。

    ## 参数

    `characters`：人物名单 `[{"canonical": "岑秀", "names": ["岑秀", "岑公子"]}, ...]`。
    没名单就不植入——宁可少植几处，也不瞎认主语（旧实现的 `_extract_subject` 抽出来一半
    是虚词残留，像 `個不用你`、`那火光中`）。

    `skip`：不植入的章节。调用方拿它排掉会被截断的章节——截断保留前 40%-70%，插入的句子
    落在被切掉的后半段就会被吃掉，答案里记着、乱稿里搜不到（9-21 实测真咬过一次）。

    `avoid`：名字在这个集合里的人物不拿来植入。调用方拿它排掉会被别名替换的人——别名
    替换在植入之后跑，会把插入句里的人名一起换掉（答案记「雪姐年方二十」、正文里成了
    「玉霜娘年方二十」），这处植入成不成就还要看实体合并有没有把两个名字并到一起，
    引入了跟矛盾扫描无关的变量。9-21 真语料上实测撞到过。
    """
    if n <= 0 or not characters:
        return []
    skipped = set(skip or ())
    script = _script_of("".join(c.body for c in chapters))
    unit = "歲" if script == "trad" else "岁"

    # 每个人物在哪些章节露过面（按名字直接搜；别名替换发生在这之后，不影响）
    avoided = set(avoid or ())
    usable = []
    for ch in characters:
        names = [x for x in (ch.get("names") or [ch["canonical"]]) if x]
        if avoided and any(a in nm or nm in a for nm in names for a in avoided):
            continue
        spots = []
        for c in chapters:
            if c.num in skipped:
                continue
            hit = next(((nm, c.body.find(nm)) for nm in names if nm in c.body), None)
            if hit:
                spots.append({"chapter": c.num, "name": hit[0], "pos": hit[1]})
        if len(spots) >= 2:  # 少于两个章节插不出两处并存的说法，跳过这个人
            usable.append({"subject": ch["canonical"], "names": names, "spots": spots})

    rng.shuffle(usable)
    planted: list[dict] = []
    used_chapters: set[int] = set()
    for person in usable:
        if len(planted) >= n:
            break
        free = [s for s in person["spots"] if s["chapter"] not in used_chapters]
        if len(free) < 2:
            continue
        a, b = rng.sample(free, 2)
        lo = rng.choice(_AGES)
        far = [v for v in _AGES if abs(v - lo) >= _AGE_GAP]
        if not far:
            continue
        hi = rng.choice(far)
        planted.append({
            "subject": person["subject"], "names": person["names"], "attribute": "年龄",
            "chapters": [a["chapter"], b["chapter"]], "ages": [lo, hi],
            "values": [_cn_number(lo), _cn_number(hi)],
            "_spots": [a, b],
        })
        used_chapters |= {a["chapter"], b["chapter"]}

    # 落笔：在含该人名的那一句之后插一句独立陈述，语法一定通顺、主语一定明确
    by_chapter = {}
    for p in planted:
        for spot, age in zip(p["_spots"], p["ages"]):
            by_chapter[spot["chapter"]] = (spot, p["subject"], age)
    for c in chapters:
        got = by_chapter.get(c.num)
        if not got:
            continue
        spot, subject, age = got
        cut = _sentence_end(c.body, spot["pos"])
        sentence = f"{spot['name']}年方{_cn_number(age)}{unit}。"
        c.body = c.body[:cut] + sentence + c.body[cut:]

    for p in planted:
        p.pop("_spots", None)
    return sorted(planted, key=lambda p: p["chapters"])


def _sentence_end(body: str, pos: int) -> int:
    """从 pos 往后找最近的句末标点，返回它后面一个位置；找不到就退到正文末尾。
    插在句子中间会把原句切坏，插在段落之外又容易被当成孤立行。"""
    m = re.compile(r"[。！？]").search(body, pos)
    return m.end() if m else len(body)

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
    n_contradictions: int = 0,
    characters: list[dict] | None = None,
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

    # 矛盾在截断、别名替换之前植入，只挑 kept（会被删掉的章节植了也白植，答案里记的东西
    # 压根不会出现在任何输出文件里），并且跳过 truncated（9-21 修）。
    # 先植入、后截断这个顺序本身是有风险的一侧：截断保留前 40%-70%（cut_at_ratio），锚点词
    # 落在被切掉的后半段就会被吃掉，答案里记了但输出文件里根本没有，召回上限白掉一处。
    # GHIJ 审查当时报「20 个种子 × 10 处 0 处被吃」，那是运气：9-21 真跑雪月梅生成乱稿时
    # ch7 的「十五→十九」就被吃掉了（新旧值在乱稿里都是 0 次），合成语料上 20 个种子有 12 个
    # 出现植入/截断重叠。这里传 truncated 进去从源头排掉。
    contradictions = plant_contradictions(kept, rng, n_contradictions,
                                           characters=characters, skip=set(truncated),
                                           avoid={a["replaces"] for a in aliases})

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
        if not candidates:
            raise ValueError(f"replaces not found in source: {a['replaces']!r}")
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
        "contradictions": contradictions,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="scramble a chaptered book into a messy manuscript")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--aliases", help="JSON 文件：替换规则列表，每条有 replaces / alias / canonical；不给就用西游记的默认别名")
    ap.add_argument("--characters", help="JSON 文件：人物名单，每条有 canonical / names；--contradictions 要用它当植入矛盾的主语，不给就一处也不植入")
    ap.add_argument("--contradictions", type=int, default=0,
                     help="植入 N 处人造矛盾（年龄/兵器/外貌类锚点），默认 0 不植入")
    ap.add_argument("--n-delete", type=int, default=5)
    ap.add_argument("--n-truncate", type=int, default=5)
    ap.add_argument("--n-full", type=int, default=10)
    ap.add_argument("--n-excerpt", type=int, default=5)
    args = ap.parse_args(argv)
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        sys.exit("output folder is not empty")
    raw = Path(args.src).read_text(encoding="utf-8")
    chapters = parse_chapters(strip_gutenberg(raw))
    aliases = json.loads(Path(args.aliases).read_text(encoding="utf-8")) if args.aliases else DEFAULT_ALIASES
    characters = json.loads(Path(args.characters).read_text(encoding="utf-8")) if args.characters else None
    key = scramble(chapters, out, args.seed, aliases=aliases, n_delete=args.n_delete,
                   n_truncate=args.n_truncate, n_full=args.n_full, n_excerpt=args.n_excerpt,
                   n_contradictions=args.contradictions, characters=characters)
    key_path = out.parent / f"{out.name}-答案.json"
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"chapters={len(chapters)} files={len(key['files'])} "
        f"deleted={len(key['deleted'])} variants={len(key['variants'])} "
        f"contradictions={len(key['contradictions'])}"
    )


if __name__ == "__main__":
    main()
