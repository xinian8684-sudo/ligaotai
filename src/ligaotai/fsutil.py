"""文件小工具：原子写入、JSON 读写、安全文件名、自然排序、路径越界检查。"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def atomic_write_text(path: Path, text: str) -> None:
    """先写临时文件再替换，写到一半断电也不会留下半截文件。统一用 LF 换行。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        # Windows 上目标文件被 Obsidian / 杀毒软件短暂占用时 replace 会失败，重试几次
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def safe_name(name: str) -> str:
    """把书名等变成能当文件夹名的字符串。"""
    cleaned = _INVALID_CHARS.sub("_", name).strip().strip(".").strip()
    if not cleaned:
        raise ValueError("名字不能为空")
    return cleaned


def natural_key(s: str) -> list:
    """自然排序：片段2 排在 片段10 前面。"""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s)]


def ensure_within(base: Path, target: Path) -> Path:
    """确认 target 在 base 里面，防止 ../ 越界。返回解析后的绝对路径。"""
    base_r = Path(base).resolve()
    target_r = Path(target).resolve()
    if target_r != base_r and base_r not in target_r.parents:
        raise ValueError(f"路径越界：{target}")
    return target_r
