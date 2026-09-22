"""书：书库里的一个文件夹。book.json 记元信息、本书参数、流水线各步状态。"""

from __future__ import annotations

import json
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
    "dedup_containment": 0.8,    # 短块有这么多内容出现在长块里，就挂到那个最佳容器上
    "dedup_min_shingles": 100,   # 太短的块（约 100 字以下）不参与查重
    "dedup_common_df": 200,      # 出现在超过这么多块里的字串当套话，不计数（真实文本 21~200 块之间几乎没有套话，调大避免误伤 21+ 份重复场景）
    "threads_max_input_tokens": 600000,  # 归线一次调用的输入上限（按 1 个字符 1 个 token 估，偏保守），超过就分段
    "skeleton_max_input_tokens": 600000,  # 骨架分章一次调用的输入上限（跟归线同一估法），超过就按窗口分批
    "contradictions_batch_tokens": 30000,  # 矛盾扫描一批的输入上限（按 1 字符 1 token 估）
    "contradictions_max_groups": 2000,     # 候选组超过这个数就按权重截断，其余记进 skipped
    "contradictions_max_batch_groups": 80,  # 矛盾扫描一批最多这么多组（独立于字符预算）：
    # 审查实测 2000 个两值小组按字符预算一批能塞进约 327 组，单组输出约 60 token，
    # 一批就要约 2 万输出 token，容易顶到 max_tokens、且一组格式不对整批都要重试；
    # 80 组约 5000 输出 token，留足安全余量。真实两本验收书全书最大批才 47 组、14
    # 组，正常场景不会触顶。
}

# 进程内一把可重入锁：book.json、实体.json 的「读 → 改 → 写」都在它里面串行。
# 可重入，所以拿着它再调 book.update（比如 mark_downstream_outdated）不会死锁。
FILE_LOCK = threading.RLock()


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

    @property
    def cards_dir(self) -> Path:
        return self.root / "场景卡"

    @property
    def entities_path(self) -> Path:
        return self.root / "实体.json"

    @property
    def entities_cache_path(self) -> Path:
        """实体合并每一批模型结果的缓存：暂停、失败后重跑，做完的批不用再花钱。"""
        return self.root / "实体合并缓存.json"

    @property
    def threads_path(self) -> Path:
        return self.root / "世界与支线.json"

    @property
    def threads_cache_path(self) -> Path:
        """归线每次模型调用的缓存：暂停、失败后重跑，输入没变的调用不用再花钱。"""
        return self.root / "归线缓存.json"

    @property
    def archive_dir(self) -> Path:
        return self.root / "档案"

    @property
    def thread_archive_dir(self) -> Path:
        return self.archive_dir / "支线"

    @property
    def world_archive_dir(self) -> Path:
        return self.archive_dir / "世界"

    @property
    def archive_index_path(self) -> Path:
        """每份档案对应的编号、输入签名、是否过期。"""
        return self.archive_dir / "index.json"

    @property
    def contradictions_path(self) -> Path:
        return self.root / "矛盾.json"

    @property
    def map_path(self) -> Path:
        return self.root / "全书地图.md"

    @property
    def archive_cache_path(self) -> Path:
        """步骤 7 每次模型调用的缓存。"""
        return self.root / "档案缓存.json"

    @property
    def canon_path(self) -> Path:
        """定稿设定：从 矛盾.json 里作者的裁决派生，三期补写要遵守。"""
        return self.root / "定稿设定.json"

    @property
    def triage_dir(self) -> Path:
        return self.root / "取舍"

    @property
    def board_path(self) -> Path:
        return self.triage_dir / "看板.json"

    @property
    def advice_path(self) -> Path:
        return self.triage_dir / "建议.json"

    @property
    def impact_path(self) -> Path:
        return self.triage_dir / "影响.json"

    @property
    def skeleton_path(self) -> Path:
        return self.triage_dir / "骨架.json"

    @property
    def skeleton_bak_path(self) -> Path:
        return self.triage_dir / "骨架.bak.json"

    @property
    def triage_cache_path(self) -> Path:
        """二期所有模型调用（AI 建议、影响检查、分章、空洞说明）共用的缓存。"""
        return self.triage_dir / "缓存.json"

    @property
    def export_dir(self) -> Path:
        return self.root / "导出"

    @property
    def logs_dir(self) -> Path:
        return self.root / "日志"

    def load(self) -> dict:
        data = read_json(self.meta_path)
        if data is None:
            raise FileNotFoundError(self.meta_path)
        return data

    def update(self, fn: Callable[[dict], None]) -> dict:
        """在锁里读 → 改 → 写 book.json。"""
        with FILE_LOCK:
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

    def add_usage(
        self, step: str, calls: int, prompt_tokens: int, completion_tokens: int, cost_usd: float
    ) -> None:
        """把一次运行的模型用量累加进 book.json 的 usage（总计 + 分步骤）。"""

        def fn(data: dict) -> None:
            usage = data.setdefault("usage", {"total": _zero_usage(), "by_step": {}})
            for bucket in (usage["total"], usage["by_step"].setdefault(step, _zero_usage())):
                bucket["calls"] += calls
                bucket["prompt_tokens"] += prompt_tokens
                bucket["completion_tokens"] += completion_tokens
                bucket["cost_usd"] = round(bucket["cost_usd"] + cost_usd, 6)

        self.update(fn)


def _zero_usage() -> dict:
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}


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
        if not d.is_dir():
            continue
        try:
            meta = read_json(d / "book.json")
        except (json.JSONDecodeError, OSError):
            continue  # book.json 坏了，跳过这本，别拖垮整个书库
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
