"""按骨架拼书，导出 md / txt（计划④ spec 第 8 节）。只导出，不回写原稿。"""

from __future__ import annotations

from pathlib import Path

from .book import Book
from .fsutil import atomic_write_text, safe_name
from .scenes import BrokenSceneFile, get_scene
from .skeleton import load_skeleton

FORMATS = ("md", "txt")


def export_path(book: Book, fmt: str) -> Path:
    if fmt not in FORMATS:
        raise ValueError("只能导出 md 或 txt")
    title = book.load().get("title") or book.name
    return book.export_dir / f"{safe_name(title)}.{fmt}"


def _text(book: Book, sid: str) -> str | None:
    try:
        sc = get_scene(book, sid)
    except (BrokenSceneFile, ValueError, FileNotFoundError):
        return None
    return None if sc.removed else sc.text.strip()


def export_book(book: Book) -> dict:
    sk = load_skeleton(book)
    md: list[str] = []
    txt: list[str] = []
    counts = {"scenes": 0, "holes": 0, "missing": 0}

    def emit(it: dict) -> None:
        if it.get("type") == "hole":
            counts["holes"] += 1
            task = " ".join(str(it.get("task") or "").splitlines())
            md.append(f"> 【空洞 {it['id']}】{task}")
            txt.append(f"【空洞 {it['id']}】{task}")
            return
        sid = it.get("id")
        text = _text(book, sid)
        if text is None:
            counts["missing"] += 1
            md.append(f"> 【缺失场景 {sid}：原稿里已经没有这一块了】")
            txt.append(f"【缺失场景 {sid}：原稿里已经没有这一块了】")
            return
        counts["scenes"] += 1
        md.append(f"<!-- {sid} -->\n{text}")
        txt.append(text)

    for v in sk.get("volumes") or []:
        md.append(f"# {v['title']}")
        txt.append(v["title"])
        for ch in v.get("chapters") or []:
            md.append(f"## {ch['title']}")
            txt.append(ch["title"])
            for it in ch.get("items") or []:
                emit(it)
    up = sk.get("unplaced") or {}
    rest = [{"type": "scene", "id": x.get("id")} for x in up.get("scenes") or []] + \
           [{**x, "type": "hole"} for x in up.get("holes") or []]
    if rest:
        md.append("# 附：未定位")
        txt.append("附：未定位")
        for it in rest:
            emit(it)

    md_path, txt_path = export_path(book, "md"), export_path(book, "txt")
    atomic_write_text(md_path, "\n\n".join(md) + "\n")
    atomic_write_text(txt_path, "\n\n".join(txt) + "\n")
    rel = lambda p: p.relative_to(book.root).as_posix()  # noqa: E731
    return {"md": rel(md_path), "txt": rel(txt_path), **counts}
