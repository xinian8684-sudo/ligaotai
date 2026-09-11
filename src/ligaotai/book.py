"""书：书库里的一个文件夹。book.json 记元信息、本书参数、流水线各步状态。"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from .fsutil import ensure_within, natural_key, read_json, safe_name, write_json

STEPS = ["import", "split", "dedup", "cards", "entities", "threads", "archive"]
STEP_LABELS = {
    "import": "导入",
    "split": "切场景",
    "dedup": "查重",
    "cards": "场景卡",
    "entities": "实体合并",
    "threads": "归线排序",
    "archive": "档案+矛盾+地图",
}
STATUSES = ("todo", "running", "done", "failed", "outdated")

DEFAULT_SETTINGS = {
    "split_max_chars": 5000,     # 超过就再切
    "split_target_chars": 3000,  # 再切时尽量切在这个位置附近
    "split_blank_lines": 2,      # 连续这么多个空行算场景分隔
    "fragment_max_chars": 300,   # 短于这个的块标成「碎片」候选
    "dedup_shingle": 5,          # 查重用几个字一组
    "dedup_jaccard": 0.5,        # 相似度达到这个算同一场景的不同版本
    "dedup_containment": 0.8,    # 短块有这么多内容出现在长块里，也算同一组
    "dedup_min_shingles": 100,   # 太短的块（约 100 字以下）不参与查重
    "dedup_common_df": 200,      # 出现在超过这么多块里的字串当套话，不计数（真实文本 21~200 块之间几乎没有套话，调大避免误伤 21+ 份重复场景）
}

_lock = threading.RLock()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Book:
    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def meta_path(self) -> Path:
        return self.root / "book.json"

    @property
    def originals_dir(self) -> Path:
        return self.root / "原稿"

    @property
    def manifest_path(self) -> Path:
        return self.root / "原稿清单.json"

    @property
    def scenes_dir(self) -> Path:
        return self.root / "场景"

    @property
    def versions_path(self) -> Path:
        return self.root / "版本组.json"

    def load(self) -> dict:
        data = read_json(self.meta_path)
        if data is None:
            raise FileNotFoundError(self.meta_path)
        return data

    def update(self, fn: Callable[[dict], None]) -> dict:
        """在锁里读 → 改 → 写 book.json。"""
        with _lock:
            data = self.load()
            fn(data)
            write_json(self.meta_path, data)
            return data

    def settings(self) -> dict:
        return {**DEFAULT_SETTINGS, **self.load().get("settings", {})}

    def step(self, name: str) -> dict:
        return self.load()["steps"][name]

    def set_step(
        self, name: str, status: str, summary: dict | None = None, changed: bool = False
    ) -> None:
        if name not in STEPS:
            raise ValueError(f"没有这一步：{name}")
        if status not in STATUSES:
            raise ValueError(f"没有这种状态：{status}")

        def fn(data: dict) -> None:
            st = data["steps"][name]
            st["status"] = status
            st["updated"] = now_iso()
            if summary is not None:
                st["summary"] = summary
            if changed:
                _outdate_after(data, name)

        self.update(fn)

    def mark_downstream_outdated(self, name: str) -> None:
        self.update(lambda data: _outdate_after(data, name))


def _outdate_after(data: dict, name: str) -> None:
    for later in STEPS[STEPS.index(name) + 1 :]:
        st = data["steps"][later]
        if st["status"] == "done":
            st["status"] = "outdated"
            st["updated"] = now_iso()


def _new_meta(title: str) -> dict:
    return {
        "schema": 1,
        "title": title,
        "created": now_iso(),
        "settings": {},
        "steps": {s: {"status": "todo", "updated": None, "summary": {}} for s in STEPS},
    }


def create_book(library: Path, title: str) -> Book:
    root = Path(library) / safe_name(title)
    if root.exists():
        raise FileExistsError(title)
    root.mkdir(parents=True)
    write_json(root / "book.json", _new_meta(title))
    return Book(root)


def open_book(library: Path, name: str) -> Book:
    if name != safe_name(name):
        raise ValueError(f"书名不合法：{name}")
    root = ensure_within(library, Path(library) / name)
    if not (root / "book.json").exists():
        raise FileNotFoundError(name)
    return Book(root)


def list_books(library: Path) -> list[dict]:
    lib = Path(library)
    if not lib.exists():
        return []
    out = []
    for d in sorted(lib.iterdir(), key=lambda p: natural_key(p.name)):
        meta = read_json(d / "book.json") if d.is_dir() else None
        if meta:
            out.append({"name": d.name, "title": meta["title"], "created": meta["created"]})
    return out


def recover_interrupted(library: Path) -> list[str]:
    """启动时调用：上次关机或崩溃时还标着 running 的步骤改成 failed。"""
    fixed = []
    for info in list_books(library):
        b = Book(Path(library) / info["name"])
        for s in STEPS:
            if b.step(s)["status"] == "running":
                b.set_step(s, "failed", {"error": "上次运行被中断，请重跑"})
                fixed.append(f"{info['name']}:{s}")
    return fixed
