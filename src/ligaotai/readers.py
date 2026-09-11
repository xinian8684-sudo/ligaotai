"""读原稿：txt / md 自动识别编码；docx 取段落，标题样式转成 Markdown #。"""

from __future__ import annotations

import codecs
from pathlib import Path

from charset_normalizer import from_bytes
from docx import Document

SUPPORTED = {".txt", ".md", ".docx"}


def detect_encoding(data: bytes) -> str:
    if data.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    for enc in ("utf-8", "gb18030"):
        try:
            data.decode(enc)
            return enc
        except UnicodeDecodeError:
            pass
    best = from_bytes(data).best()
    return best.encoding if best else "utf-8"


def _heading_level(style_name: str) -> int:
    """Word 段落样式名 → 标题级别；不是标题返回 0。"""
    n = (style_name or "").strip().lower()
    if n == "title":
        return 1
    for prefix in ("heading", "标题"):
        if n.startswith(prefix):
            digits = "".join(ch for ch in n[len(prefix):] if ch.isdigit())
            return max(1, min(6, int(digits))) if digits else 1
    return 0


def docx_to_text(path: Path) -> str:
    doc = Document(str(path))
    lines = []
    for p in doc.paragraphs:
        level = _heading_level(p.style.name if p.style is not None else "")
        if level and p.text.strip():
            lines.append("#" * level + " " + p.text.strip())
        else:
            lines.append(p.text)
    return "\n".join(lines)


def read_text(path: Path) -> tuple[str, str]:
    """返回 (统一成 \\n 换行的文本, 编码名)。docx 的编码名记为 "docx"。"""
    path = Path(path)
    if path.suffix.lower() == ".docx":
        return docx_to_text(path), "docx"
    data = path.read_bytes()
    enc = detect_encoding(data)
    text = data.decode(enc, errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):
        text = text[1:]
    return text, enc
