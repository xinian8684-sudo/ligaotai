"""场景：场景/S-0001.md 的读写，以及步骤 2（切场景 + 编号对账）。

块的身份 =（来源文件, 文件里第几块）：
- 身份和内容都没变：不动；
- 身份在、内容变了：改写正文，标 stale（场景卡要重做）；
- 新身份：接着最大编号往后排，不重排旧编号；
- 旧身份这次没切出来：标 removed，不删文件、不回收编号。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from .book import Book
from .fsutil import atomic_write_text, natural_key, read_json
from .readers import read_text
from .split import SplitRules, split_text

SCENE_ID_RE = re.compile(r"^S-\d{4,}$")
FRAGMENT = "碎片"

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


@dataclass
class Scene:
    id: str
    source: str
    index: int
    start: int
    end: int
    chars: int
    hash: str
    heading: str = ""
    part: int = 1
    kind_hint: str = ""
    stale: bool = False
    removed: bool = False
    text: str = field(default="", repr=False)

    def meta(self) -> dict:
        d = asdict(self)
        d.pop("text")
        return d


def scene_num(sid: str) -> int:
    return int(sid[2:])


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class BrokenSceneFile(ValueError):
    """某个场景文件读不出来。带上文件名，好让界面说清是哪一个。

    继承 ValueError 是为了兼容既有调用方（get_scene 的 `except (ValueError, FileNotFoundError)`
    等）——它们不用改，照样能接住；API 层想单独区分「场景文件坏了」时再单独 except 这个类型。
    """

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"场景文件读不了：{path.name}（{reason}）")


def scene_path(book: Book, sid: str) -> Path:
    return book.scenes_dir / f"{sid}.md"


def dump_scene(scene: Scene) -> str:
    head = yaml.safe_dump(scene.meta(), allow_unicode=True, sort_keys=False)
    return f"---\n{head}---\n{scene.text}"


def parse_scene(content: str) -> Scene:
    if not content.startswith("---\n"):
        raise ValueError("场景文件缺少头信息")
    end = content.index("\n---\n", 4)
    meta = yaml.safe_load(content[4 : end + 1])
    return Scene(**meta, text=content[end + 5 :])


def write_scene(book: Book, scene: Scene) -> None:
    atomic_write_text(scene_path(book, scene.id), dump_scene(scene))


def read_scene(path: Path) -> Scene:
    path = Path(path)
    try:
        return parse_scene(path.read_text(encoding="utf-8"))
    except Exception as e:  # 手改坏了一个场景文件，报错要指出是哪个
        raise BrokenSceneFile(path, f"{type(e).__name__}: {e}") from e


def load_scenes(book: Book, with_text: bool = False) -> list[Scene]:
    if not book.scenes_dir.exists():
        return []
    out = []
    for p in book.scenes_dir.glob("S-*.md"):
        if not SCENE_ID_RE.match(p.stem):
            continue  # 同步冲突/重复副本，如 "S-0001 (1).md"、"S-0001.sync-conflict-x.md"
        sc = read_scene(p)
        if sc.id != p.stem:
            continue  # 文件名和头信息里的编号对不上，不是这个场景真正的文件
        if not with_text:
            sc.text = ""
        out.append(sc)
    out.sort(key=lambda s: scene_num(s.id))
    return out


def get_scene(book: Book, sid: str) -> Scene:
    if not SCENE_ID_RE.match(sid):
        raise ValueError(f"场景编号不合法：{sid}")
    p = scene_path(book, sid)
    if not p.exists():
        raise FileNotFoundError(sid)
    return read_scene(p)


def rules_from_settings(settings: dict) -> SplitRules:
    return SplitRules(
        max_chars=settings["split_max_chars"],
        target_chars=settings["split_target_chars"],
        blank_lines=settings["split_blank_lines"],
    )


def run_split(book: Book, progress: Progress = _noop) -> dict:
    settings = book.settings()
    rules = rules_from_settings(settings)
    frag_max = settings["fragment_max_chars"]
    files = read_json(book.manifest_path, {"files": {}})["files"]
    existing = {(s.source, s.index): s for s in load_scenes(book, with_text=True)}
    next_num = max((scene_num(s.id) for s in existing.values()), default=0) + 1
    seen: set[tuple[str, int]] = set()
    counts = {"added": 0, "changed": 0, "unchanged": 0, "removed": 0}
    fragments = 0
    keys = sorted(files, key=natural_key)
    for i, key in enumerate(keys, 1):
        text, _ = read_text(book.originals_dir / key)
        for idx, b in enumerate(split_text(text, rules)):
            body = text[b.start : b.end]
            seen.add((key, idx))
            old = existing.get((key, idx))
            new = Scene(
                id=old.id if old else f"S-{next_num:04d}",
                source=key,
                index=idx,
                start=b.start,
                end=b.end,
                chars=len(body),
                hash=text_hash(body),
                heading=b.heading,
                part=b.part,
                kind_hint=FRAGMENT if len(body.strip()) < frag_max else "",
                text=body,
            )
            fragments += new.kind_hint == FRAGMENT
            if old is None:
                next_num += 1
                counts["added"] += 1
            elif old.hash != new.hash:
                new.stale = True
                counts["changed"] += 1
            else:
                new.stale = old.stale
                counts["changed" if old.removed else "unchanged"] += 1
                if new == old:
                    continue
            write_scene(book, new)
        progress(i, len(keys))
    for k, old in existing.items():
        if k not in seen and not old.removed:
            old.removed = True
            write_scene(book, old)
            counts["removed"] += 1
    summary = {**counts, "scenes": len(seen), "fragments": fragments, "files": len(keys)}
    changed = bool(counts["added"] or counts["changed"] or counts["removed"])
    book.set_step("split", "done", summary, changed=changed)
    return summary
