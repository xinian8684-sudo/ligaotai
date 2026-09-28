"""故事时间线冲突检查的纯函数部分（spec 2026-09-28-ligaotai-timeline-check-design.md）。

只用先后顺序，不用估出来的时间数值（数值不硬，②c 以来的结论）。不读模型、不写文件。
"""

from __future__ import annotations

from .book import Book
from .skeleton import scene_info
from .skeleton_order import build_sequence
from .threads_ops import load_threads
from .triage import non_main_versions, version_map


def story_order(book: Book) -> tuple[list[str], dict[str, int], int]:
    """全书故事顺序（跟骨架同一个排法，所有线都参与，不看看板）。
    返回 (排好的场景编号, 编号 -> 位置, 排不进时间轴的块数)。"""
    threads = load_threads(book)
    vmap = version_map(book)
    info = scene_info(book)
    removed = {sid for sid, x in info.items() if x["removed"]} | (non_main_versions(book) - set(vmap))
    seq, unplaced = build_sequence(threads, {}, removed, vmap)
    ids = [x["id"] for x in seq]
    return ids, {s: i for i, s in enumerate(ids)}, len(unplaced)
