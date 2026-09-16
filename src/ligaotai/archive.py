"""步骤 7：支线档案 + 世界设定集 + 矛盾扫描 + 全书地图。

这里只实现「输入签名」和「按编号对账」：档案要能单独重跑（作者只改了一条线，
只重跑那一份，别的不花钱），所以每份档案要记住它的输入长什么样。编排（什么
时候该重跑哪份档案、写文件、调模型）是步骤 7 的其他部分，不在这个文件里。

见 docs/superpowers/specs/2026-09-16-ligaotai-plan2c-archives-design.md。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .book import Book
from .fsutil import read_json, write_json

EMPTY_INDEX = {"threads": {}, "worlds": {}, "map": {}}


def _digest(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(p, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def thread_sig(thread: dict, scene_hashes: dict[str, str], gaps: list[dict]) -> str:
    """一条线的输入签名：线名 + 有序场景编号 + 每块的 scene_hash + 断点 + 这条线的缺口。"""
    scenes = list(thread.get("scenes") or [])
    return _digest(
        thread.get("name", ""),
        scenes,
        [scene_hashes.get(s, "") for s in scenes],
        thread.get("end") or {},
        [g.get("event", "") for g in gaps],
    )


def world_sig(world: dict, scenes: list[str], scene_hashes: dict[str, str], cmap_sig: str) -> str:
    """一个世界的输入签名：世界名 + 该世界所有块的 scene_hash + 规范名映射版本。"""
    ordered = sorted(scenes)
    return _digest(world.get("name", ""), ordered,
                    [scene_hashes.get(s, "") for s in ordered], cmap_sig)


def map_sig(files: list[Path]) -> str:
    """地图的输入签名：全部档案文件内容的哈希。"""
    parts = []
    for p in sorted(files, key=lambda p: p.name):
        try:
            parts.append(p.read_text(encoding="utf-8"))
        except OSError:
            parts.append("")
    return _digest(parts)


def reconcile(index: dict, thread_ids: set[str], world_ids: set[str]) -> list[str]:
    """按编号对账（spec 7.1）：index 里有、但线 / 世界已经不存在的档案标过期。
    不删文件——作者可能还想看。返回被标过期的编号。"""
    stale = []
    for oid, entry in sorted(index.get("threads", {}).items()):
        if oid not in thread_ids:
            entry["outdated"] = True
            stale.append(oid)
    for oid, entry in sorted(index.get("worlds", {}).items()):
        if oid not in world_ids:
            entry["outdated"] = True
            stale.append(oid)
    return stale


def load_index(book: Book) -> dict:
    data = read_json(book.archive_index_path, None)
    if not isinstance(data, dict):
        return json.loads(json.dumps(EMPTY_INDEX))
    for k, empty in (("threads", {}), ("worlds", {}), ("map", {})):
        data.setdefault(k, json.loads(json.dumps(empty)))
    return data


def write_index(book: Book, data: dict) -> None:
    book.archive_dir.mkdir(parents=True, exist_ok=True)
    write_json(book.archive_index_path, data)
