"""步骤 1 导入：把文件夹里的 txt/md/docx 复制进 原稿/，登记到 原稿清单.json。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from .book import Book, now_iso
from .fsutil import natural_key, read_json, safe_name, write_json
from .readers import SUPPORTED, read_text

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


def _skip_reason(folder: Path, rel: Path) -> str | None:
    if any(part.startswith(".") for part in rel.parts):
        return "隐藏文件"
    if rel.name.startswith("~$"):
        return "Word 临时文件"
    if _under_book_dir(folder, rel):
        return "理稿台书库"
    if rel.suffix.lower() not in SUPPORTED:
        return "格式不支持"
    return None


def _under_book_dir(folder: Path, rel: Path) -> bool:
    """文件是不是躺在某个「书」文件夹（含 book.json）底下，避免把书库自己导进书库。"""
    p = folder
    for part in rel.parts[:-1]:
        p = p / part
        if (p / "book.json").exists():
            return True
    return False


def _import_one(book: Book, manifest: dict, key: str, src: Path) -> str:
    """导入一个文件，返回 added / changed / unchanged。读失败直接抛异常，不动旧副本。"""
    data = src.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    old = manifest["files"].get(key)
    dest = book.originals_dir / key
    if old and old["sha256"] == digest and dest.exists():
        return "unchanged"
    text, enc = read_text(src)  # 先读，读得出来才复制
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    manifest["files"][key] = {
        "sha256": digest,
        "encoding": enc,
        "chars": len(text),
        "mtime": src.stat().st_mtime,
        "imported": now_iso(),
    }
    return "changed" if old else "added"


def check_import_folder(book: Book, folder: Path) -> Path:
    """校验要导入的文件夹，返回解析后的绝对路径。folder 在书自己的文件夹里就报错，
    避免把 书库/<书>/原稿、场景 之类导入自己。"""
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise NotADirectoryError(str(folder))
    book_root = book.root.resolve()
    if folder == book_root or book_root in folder.parents:
        raise ValueError(f"不能把书自己的文件夹导入自己：{folder}")
    return folder


def run_import(book: Book, folder: Path, progress: Progress = _noop) -> dict:
    folder = check_import_folder(book, folder)
    root_name = safe_name(folder.name)
    manifest = read_json(book.manifest_path, {"files": {}})
    files = sorted(
        (p for p in folder.rglob("*") if p.is_file()),
        key=lambda p: natural_key(p.relative_to(folder).as_posix()),
    )
    counts = {"added": 0, "changed": 0, "unchanged": 0}
    skipped: list[dict] = []
    failed: list[dict] = []
    for i, src in enumerate(files, 1):
        rel = src.relative_to(folder)
        reason = _skip_reason(folder, rel)
        if reason:
            skipped.append({"path": rel.as_posix(), "reason": reason})
        else:
            key = f"{root_name}/{rel.as_posix()}"
            try:
                counts[_import_one(book, manifest, key, src)] += 1
            except Exception as e:  # 坏文件不能拖垮整次导入
                failed.append({"path": key, "error": f"{type(e).__name__}: {e}"})
        progress(i, len(files))
    write_json(book.manifest_path, manifest)
    summary = {
        "folder": str(folder),
        "root": root_name,
        **counts,
        "skipped": skipped,
        "failed": failed,
        "total_files": len(manifest["files"]),
    }
    book.set_step("import", "done", summary, changed=bool(counts["added"] or counts["changed"]))
    return summary
