"""按骨架拼书，导出 md / txt（计划④ spec 第 8 节）。只导出，不回写原稿。"""

from __future__ import annotations

from pathlib import Path

from .book import Book
from .fsutil import atomic_write_text, safe_name
from .scenes import BrokenSceneFile, get_scene
from .skeleton import load_skeleton
from .threads_ops import BrokenThreadsFile, load_threads
from .triage import BrokenBoardFile, columns, version_map

FORMATS = ("md", "txt")


def export_path(book: Book, fmt: str) -> Path:
    if fmt not in FORMATS:
        raise ValueError("只能导出 md 或 txt")
    title = book.load().get("title") or book.name
    return book.export_dir / f"{safe_name(title)}.{fmt}"


def _text(book: Book, sid: str) -> str | None:
    try:
        sc = get_scene(book, sid)
    except BrokenSceneFile:
        # BrokenSceneFile 继承 ValueError，必须排在下面那条前面，不然被吃成「原稿里已经
        # 没有这一块了」——场景文件手改坏了跟场景真的被删掉，是两件不一样的事，前者要
        # 让接口报 500、把哪个文件坏了说清楚，不能悄悄说成后者（S2）。
        raise
    except (ValueError, FileNotFoundError):
        return None
    return None if sc.removed else sc.text.strip()


def _cut_lookup(book: Book) -> tuple[dict, dict]:
    """场景所属线现在是不是被砍掉了——只用来给导出结果附带一个 cut 计数提醒界面，
    线 / 看板文件不存在或者坏了就当查不出来（不影响导出本身，导出不依赖归线结果）。"""
    try:
        threads = load_threads(book)
        cols = columns(book, threads)
    except (FileNotFoundError, BrokenThreadsFile, BrokenBoardFile):
        return {}, {}
    vmap = version_map(book)
    thread_of: dict[str, str] = {}
    for t in threads.get("threads") or []:
        if isinstance(t, dict) and t.get("id"):
            for sid0 in t.get("scenes") or []:
                thread_of.setdefault(sid0, t["id"])
                thread_of.setdefault(vmap.get(sid0, sid0), t["id"])
    return cols, thread_of


def export_book(book: Book) -> dict:
    sk = load_skeleton(book)
    vmap = version_map(book)
    cols, thread_of = _cut_lookup(book)
    md: list[str] = []
    txt: list[str] = []
    counts = {"scenes": 0, "holes": 0, "missing": 0, "chars": 0, "cut": 0}

    def emit(it: dict) -> None:
        if it.get("type") == "hole":
            counts["holes"] += 1
            task = " ".join(str(it.get("task") or "").splitlines())
            md.append(f"> 【空洞 {it['id']}】{task}")
            txt.append(f"【空洞 {it['id']}】{task}")
            return
        sid = it.get("id")
        # M3：场景正文取组里现在的主版本，不是骨架里原样存的那个引用——骨架可能是在作者
        # 换主版本之前生成的，spec 8 要求导出的是主版本原文。
        real = vmap.get(sid, sid)
        text = _text(book, real)
        if text is None:
            counts["missing"] += 1
            md.append(f"> 【缺失场景 {sid}：原稿里已经没有这一块了】")
            txt.append(f"【缺失场景 {sid}：原稿里已经没有这一块了】")
            return
        counts["scenes"] += 1
        counts["chars"] += len(text)
        if cols.get(thread_of.get(sid), {}).get("col") == "cut":
            counts["cut"] += 1
        md.append(f"<!-- {real} -->\n{text}")
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
