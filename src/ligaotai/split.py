"""切场景：把一个文件的文本切成场景块。纯函数，不碰文件。

切法按优先级：章节标题 → 分隔符行 / 连续空行 → 太长的再切（见 _size_split）。
返回的位置都指向传入的文本，界面据此跳回原件。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SplitRules:
    max_chars: int = 5000
    target_chars: int = 3000
    blank_lines: int = 2


@dataclass(frozen=True)
class Block:
    start: int
    end: int
    heading: str  # 所在章节标题，可能为空
    part: int     # 同一标题下的第几块，从 1 开始


_NUM = "0-9０-９一二三四五六七八九十百千零〇○两"
HEADING_PATTERNS = [
    re.compile(rf"^第[{_NUM}]+[章节回卷集部篇幕]"),
    re.compile(r"^chapter\s+[0-9ivxlc]+\b", re.IGNORECASE),
    re.compile(r"^#{1,6}\s+\S"),
    re.compile(r"^[0-9０-９]{1,4}[.、．]?$"),
    re.compile(r"^[一二三四五六七八九十百零〇]{1,6}$"),
]
HEADING_MAX_LEN = 50
_SENTENCE_END = "。！？!?，,；;…」”』"
_SEPARATOR_CHARS = set("*＊-—－_=＝~～·•◇◆○●□■☆★※#＃")
_WS = " \t\u3000"

# 一段：(起, 止, 标题, 章节序号)
Piece = tuple[int, int, str, int]


def is_heading(line: str) -> bool:
    s = line.strip(_WS)
    if not s or len(s) > HEADING_MAX_LEN or s[-1] in _SENTENCE_END:
        return False
    return any(p.match(s) for p in HEADING_PATTERNS)


def is_separator(line: str) -> bool:
    s = "".join(line.split())
    return len(s) >= 3 and set(s) <= _SEPARATOR_CHARS


def _is_blank(line: str) -> bool:
    return not line.strip(_WS)


def _line_spans(text: str) -> list[tuple[int, int, str]]:
    spans = []
    pos = 0
    for line in text.split("\n"):
        spans.append((pos, pos + len(line), line))
        pos += len(line) + 1
    return spans


def _raw_pieces(text: str, rules: SplitRules) -> list[Piece]:
    """按标题、分隔符、连续空行切成若干段（还没去空白）。"""
    pieces: list[Piece] = []
    heading, section = "", 0
    piece_start = 0
    blank_start, blank_count = 0, 0
    for start, end, line in _line_spans(text):
        if _is_blank(line):
            if blank_count == 0:
                blank_start = start
            blank_count += 1
            continue
        if blank_count >= rules.blank_lines:
            pieces.append((piece_start, blank_start, heading, section))
            piece_start = start
        blank_count = 0
        if is_separator(line):
            pieces.append((piece_start, start, heading, section))
            piece_start = end
        elif is_heading(line):
            pieces.append((piece_start, start, heading, section))
            piece_start = start
            heading = line.strip(_WS)
            section += 1
    pieces.append((piece_start, len(text), heading, section))
    return pieces


def _trim(text: str, s: int, e: int) -> tuple[int, int] | None:
    """去掉首尾空行，保留第一行缩进。全是空白返回 None。"""
    seg = text[s:e]
    left = len(seg) - len(seg.lstrip())
    if left == len(seg):
        return None
    first = s + left
    line_start = text.rfind("\n", s, first)
    s2 = line_start + 1 if line_start != -1 else s
    return s2, s + len(seg.rstrip())


def _is_heading_only(text: str, s: int, e: int) -> bool:
    lines = [ln for ln in text[s:e].split("\n") if not _is_blank(ln)]
    return bool(lines) and all(is_heading(ln) for ln in lines)


def _join_heading(a: str, b: str) -> str:
    if not a:
        return b
    if not b or a == b:
        return a
    return f"{a} / {b}"


def _merge_heading_only(text: str, pieces: list[Piece]) -> list[Piece]:
    merged: list[Piece] = []
    pending: Piece | None = None
    for s, e, h, sec in pieces:
        if _is_heading_only(text, s, e):
            pending = (s, e, h, sec) if pending is None else (
                pending[0], e, _join_heading(pending[2], h), sec
            )
            continue
        if pending is not None:
            s, h = pending[0], _join_heading(pending[2], h)
            pending = None
        merged.append((s, e, h, sec))
    if pending is not None:
        merged.append(pending)
    return merged


_BLANK_BOUNDARY = re.compile(r"\n[ \t\u3000]*\n")
_NEWLINE = re.compile(r"\n")
_SENTENCE_CUT = re.compile(r"[。！？!?…][」”』）)]?")


def _find_cut(text: str, s: int, e: int, rules: SplitRules) -> int:
    """在 [s, e) 里找一个最接近 s + target 的切点。"""
    ideal = s + rules.target_chars
    min_side = rules.target_chars // 3
    lo, hi = s + min_side, e - min_side
    candidate_sets = (
        (m.start() for m in _BLANK_BOUNDARY.finditer(text, s, e)),
        (m.start() for m in _NEWLINE.finditer(text, s, e)),
        (m.end() for m in _SENTENCE_CUT.finditer(text, s, e)),
    )
    for candidates in candidate_sets:
        best = min(
            (c for c in candidates if lo <= c <= hi),
            key=lambda c: abs(c - ideal),
            default=None,
        )
        if best is not None:
            return best
    return ideal


def _size_split(text: str, s: int, e: int, rules: SplitRules) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    while e - s > rules.max_chars:
        cut = _find_cut(text, s, e, rules)
        head = _trim(text, s, cut)
        if head:
            out.append(head)
        rest = _trim(text, cut, e)
        if rest is None:
            return out
        s = rest[0]
    out.append((s, e))
    return out


def _number_parts(pieces: list[Piece]) -> list[Block]:
    blocks = []
    counts: dict[int, int] = {}
    for s, e, h, sec in pieces:
        counts[sec] = counts.get(sec, 0) + 1
        blocks.append(Block(s, e, h, counts[sec]))
    return blocks


def split_text(text: str, rules: SplitRules = SplitRules()) -> list[Block]:
    pieces: list[Piece] = []
    for s, e, h, sec in _raw_pieces(text, rules):
        t = _trim(text, s, e)
        if t:
            pieces.append((t[0], t[1], h, sec))
    sized: list[Piece] = []
    for s, e, h, sec in _merge_heading_only(text, pieces):
        for s2, e2 in _size_split(text, s, e, rules):
            sized.append((s2, e2, h, sec))
    return _number_parts(sized)
