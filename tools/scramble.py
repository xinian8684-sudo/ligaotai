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


# 锚点：换的值必须跟原值同类但不同，好让矛盾扫描能认出来。
# spec 9.1 还提到「地名（从答案文件里已有的实体取）」一类锚点，这里没做——scramble 在切场景、
# 建实体表之前跑，这个阶段还没有「答案文件里已有的实体」可取，留给以后有实体表可用时再补。
#
# C1 修复（9-20 GHIJ 审查）：旧版词表全是简体，验收语料（西游记）是繁体，整张表在那本书上
# 只有「金箍棒」（简繁同形）能匹配，10 处植入 8 处落在同一个 (孫悟空,兵器) 组，召回门槛
# ≥8/10 形同虚设。修法：
# 1. 每个词按 (简体写法, 繁体写法) 成对登记；正则同时认两种写法，新值按「匹配到的这段文本
#    整体是简体还是繁体」（见 _script_of）挑对应写法写回去，不会把简体新词塞进繁体正文。
# 2. 加配额（见 plant_contradictions 的 max_per_pair）：同一个 (old,new) 有向对最多用
#    max_per_pair 次，逼植入分散到不同的兵器/部位/颜色上——这些锚点本来就对应不同人物，
#    分散锚点约等于分散 (主语,属性) 分组。
_ANCHOR_GROUPS: list[tuple[str, list[tuple[str, str]], dict[str, str]]] = [
    ("兵器", [
        ("金箍棒", "金箍棒"), ("九齿钉耙", "九齒釘鈀"), ("降妖宝杖", "降妖寶杖"),
        ("青锋剑", "青鋒劍"), ("方天画戟", "方天畫戟"),
    ], {
        "金箍棒": "降妖宝杖", "降妖宝杖": "金箍棒", "九齿钉耙": "青锋剑",
        "青锋剑": "九齿钉耙", "方天画戟": "青锋剑",
    }),
    ("外貌", [
        ("左臂", "左臂"), ("右臂", "右臂"), ("左脸", "左臉"), ("右脸", "右臉"),
        ("左手", "左手"), ("右手", "右手"),
    ], {
        "左臂": "右臂", "右臂": "左臂", "左脸": "右脸", "右脸": "左脸",
        "左手": "右手", "右手": "左手",
    }),
    ("外貌", [
        ("红衣", "紅衣"), ("白衣", "白衣"), ("青衣", "青衣"), ("皂衣", "皂衣"),
    ], {
        "红衣": "青衣", "青衣": "红衣", "白衣": "皂衣", "皂衣": "白衣",
    }),
]
# 年龄锚点：汉字数字（十六、二十…）两岸同形，不受简繁影响；唯独单位字有「岁/歲」两种
# 写法，正则里两种都认，数字本身直接用同一张表换，不用另外分简繁。
_AGE_TABLE = {"十六": "二十", "二十": "十六", "十八": "二十四", "十五": "十九"}

_TRAD_CHARS = frozenset(hanfold._TRAD)
_SIMP_CHARS = frozenset(hanfold._SIMP)


def _script_of(text: str) -> str:
    """粗略判断一段文本整体是简体还是繁体：数繁体专属字符和简体专属字符各出现多少次，
    谁多算谁（`hanfold` 那张表的 2473 对字形几乎不重叠，样本一大，多数书几千字以内
    就能分出胜负）。只用来决定植入新值时写哪种字形，不做任何文本转换、不追求识别单字。"""
    trad = sum(1 for ch in text if ch in _TRAD_CHARS)
    simp = sum(1 for ch in text if ch in _SIMP_CHARS)
    return "trad" if trad > simp else "simp"


def _make_word_resolver(pairs: list[tuple[str, str]], swap: dict[str, str]):
    """把 (简体,繁体) 词对 + 简体换表，展开成 old(任意字形) -> new(按 script 挑字形) 的函数。"""
    simp_to_trad = dict(pairs)
    canon = {}
    for s, t in pairs:
        canon[s] = s
        canon[t] = s

    def resolve(old: str, script: str) -> str | None:
        s = canon.get(old)
        if s is None:
            return None
        new_s = swap.get(s)
        if new_s is None:
            return None
        return simp_to_trad[new_s] if script == "trad" else new_s

    return resolve


def _age_resolver(old: str, script: str) -> str | None:
    return _AGE_TABLE.get(old)


_ANCHORS: list[tuple[str, re.Pattern, object]] = [
    ("年龄", re.compile(r"年方([一二三四五六七八九十]+)"), _age_resolver),
    ("年龄", re.compile(r"([一二三四五六七八九十]+)(?:岁|歲)"), _age_resolver),
    *[
        (attribute, re.compile("(" + "|".join(sorted({f for p in pairs for f in p},
                                                       key=len, reverse=True)) + ")"),
         _make_word_resolver(pairs, swap))
        for attribute, pairs, swap in _ANCHOR_GROUPS
    ],
]

_CLAUSE_BOUND = re.compile(r"[，,。！？；：\n]")
_SUBJECT_STOP_CHARS = set("将把手舉举執执拿佩戴穿披是有來来仍又也便就卻却年方歲岁正慌急直忙早")
_SUBJECT_DECOR = re.compile(r"[「『“」』”\s]")
# 章回小说里最常见的「点名」形态是「XX道/說/曰」——古白话零主语（承前省略）很多，
# 锚点所在分句往往没有名字，反而是往前一两句的「某某道：」把名字重新点出来。
# 优先找这个，比纯分句截取准得多；找不到再退回分句启发式。
_SPEAKER = re.compile(r"([一-鿿]{1,8})(?:道|說|说|曰)[：:，,「『]")
_SPEAKER_TRIM = re.compile(r"(?:那|這|这|那個|这个|又|便|忙|连忙|連忙|冷笑|大笑|笑|喝|叫|哭|應聲|应声|答)+$")


def _extract_subject(body: str, pos: int, lookback: int = 200) -> str:
    """从锚点前的文本里粗略挑一个「像主语」的候选，两级启发式：

    1. 先找 `lookback` 范围内最近一处「某某道/說/曰」（`_SPEAKER`），去掉「那/这/笑/
       忙」这类前缀修饰词，当作最近提到的说话人——章回小说的零主语句多，这一招覆盖
       的场景比只看锚点所在分句多得多。
    2. 找不到就退回分句启发式：从上一个标点切开，取分句开头到第一个常见谓语/虚词
       字符之前的汉字串；这一分句抓不到（太短或全是虚词）就退到再前一个分句。

    这是个粗糙的启发式，**不是命名实体识别**——scramble 在实体表建好之前跑，这个阶段
    拿不到规范名。目的只是 spec 9.1 要求的「至少填上一个东西，供人工核对扫描结果时
    判断主语对不对」，不追求精确；抓错、抓到虚词残留都可能发生，真实语料上的实测
    结果（含抓错的例子）见 `reports/GHIJ-修复.md`。抓不到就留空，不瞎编。"""
    left = _SUBJECT_DECOR.sub("", body[max(0, pos - lookback):pos])
    speakers = list(_SPEAKER.finditer(left))
    if speakers:
        name = _SPEAKER_TRIM.sub("", speakers[-1].group(1))
        if len(name) >= 1:
            return name[-4:]
    clauses = _CLAUSE_BOUND.split(left)
    for clause in reversed(clauses):
        if not clause:
            continue
        cut = len(clause)
        for i, ch in enumerate(clause):
            if ch in _SUBJECT_STOP_CHARS:
                cut = i
                break
        chunk = clause[:cut]
        if len(chunk) >= 2:
            return chunk[:4]
    return ""


def plant_contradictions(chapters: list[Chapter], rng: random.Random, n: int,
                          max_per_pair: int = 2, skip: set[int] | None = None) -> list[dict]:
    """在章节正文里植入 n 处人造矛盾，一个章节最多一处，就地改 chapters 的 body。

    只改**原文里真出现的词**，换成同类但不同的值，答案记 (章节, 主语, 属性, 原值, 新值)。
    找不到锚点就少植入几处，不硬来（spec 9.1）。同一个 (old,new) 有向对最多用
    `max_per_pair` 次，避免像旧版那样 10 处里 8 处都是同一条替换（C1）。

    `skip` 里的章节不植入。调用方拿它排掉会被截断的章节：截断保留前 40%-70%，锚点落在
    被切掉的后半段就会被吃掉，答案里记着这处矛盾、乱稿正文里新旧值都搜不到，召回上限
    白白掉一处（9-21：雪月梅真语料上实测 10 处里 ch7 被吃掉了一处）。

    注：任务书给的实现里 n=0 时会误植入 1 处——「先 setdefault 进去、再判断
    len(by_chapter) >= n」在 n=0 时第一条就已经 1 >= 0，立刻当「够了」保留下来。
    这里补一道 n <= 0 直接短路，保证不给 --contradictions 参数时（默认 0）行为
    跟改之前完全一样，一处都不植入。
    """
    if n <= 0:
        return []
    skipped = skip or set()
    script = _script_of("".join(c.body for c in chapters))
    spots = []
    for c in chapters:
        for attribute, pattern, resolver in _ANCHORS:
            for m in pattern.finditer(c.body):
                old = m.group(1)
                new = resolver(old, script)
                if new and new != old and new not in c.body:
                    subject = _extract_subject(c.body, m.start(1))
                    spots.append({"chapter": c.num, "attribute": attribute, "subject": subject,
                                  "old": old, "new": new, "pos": m.start(1)})
    rng.shuffle(spots)
    by_chapter: dict[int, dict] = {}
    pair_count: dict[tuple[str, str], int] = {}
    for s in spots:
        if s["chapter"] in by_chapter or s["chapter"] in skipped:
            continue
        key = (s["old"], s["new"])
        if pair_count.get(key, 0) >= max_per_pair:
            continue
        by_chapter[s["chapter"]] = s
        pair_count[key] = pair_count.get(key, 0) + 1
        if len(by_chapter) >= n:
            break
    planted = []
    for c in chapters:
        s = by_chapter.get(c.num)
        if not s:
            continue
        c.body = c.body[:s["pos"]] + s["new"] + c.body[s["pos"] + len(s["old"]):]
        planted.append({"chapter": c.num, "subject": s["subject"], "attribute": s["attribute"],
                        "old": s["old"], "new": s["new"]})
    return sorted(planted, key=lambda p: p["chapter"])


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
    contradictions = plant_contradictions(kept, rng, n_contradictions, skip=set(truncated))

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
    key = scramble(chapters, out, args.seed, aliases=aliases, n_delete=args.n_delete,
                   n_truncate=args.n_truncate, n_full=args.n_full, n_excerpt=args.n_excerpt,
                   n_contradictions=args.contradictions)
    key_path = out.parent / f"{out.name}-答案.json"
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"chapters={len(chapters)} files={len(key['files'])} "
        f"deleted={len(key['deleted'])} variants={len(key['variants'])} "
        f"contradictions={len(key['contradictions'])}"
    )


if __name__ == "__main__":
    main()
