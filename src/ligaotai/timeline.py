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


# 死亡词：值里出现就算死了（「亲属」这类属性说的是别人，不看）
DEATH_WORDS = ("死", "亡", "殁", "歿", "卒", "身故", "病故", "已故", "归天", "歸天", "逝",
               "阵亡", "陣亡", "斩", "斬", "枭首", "梟首", "丧命", "喪命", "殒命", "殞命",
               "去世", "坐化")
# 值里出现这些就不算（免死、被抓、只是差点死、说的是别的意思）
NOT_DEATH = ("免死", "未死", "不死", "没死", "沒死", "幾乎", "几乎", "险些", "險些", "差点", "差點",
             "被擒", "监禁", "監禁", "车囚", "車囚", "丁艱", "丁艰", "生还", "生還", "得救",
             "亡命", "视死", "視死", "死战", "死戰", "死守")
DEATH_ATTRS = ("生死", "身份", "其他", "伤病", "結局", "结局")


def is_death(attribute: str, value: str) -> bool:
    """这条 fact 说的是不是「主语死了」。只负责缩小范围：拿不准的放进来，模型后面还要判。"""
    a, v = (attribute or "").strip(), (value or "").strip()
    if a not in DEATH_ATTRS or not v:
        return False
    if any(w in v for w in NOT_DEATH):
        return False
    return any(w in v for w in DEATH_WORDS)
