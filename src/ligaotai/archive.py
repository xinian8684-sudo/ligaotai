"""步骤 7：支线档案 + 世界设定集 + 矛盾扫描 + 全书地图。

这里只实现「输入签名」和「按编号对账」：档案要能单独重跑（作者只改了一条线，
只重跑那一份，别的不花钱），所以每份档案要记住它的输入长什么样。编排（什么
时候该重跑哪份档案、写文件、调模型）是步骤 7 的其他部分，不在这个文件里。

见 docs/superpowers/specs/2026-09-16-ligaotai-plan2c-archives-design.md。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re

from .book import Book
from .fsutil import read_json, write_json

EMPTY_INDEX = {"threads": {}, "worlds": {}, "map": {}}

log = logging.getLogger(__name__)


def _digest(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(p, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


# 9-17 作者拍板改的签名契约（C 组审查「必须修 1」）：原先按 spec 7.1 挑出来的几个字段算签名
# （线名/场景哈希/断点/缺口……），实测漏了模型实际会看到的输入——规范名映射（canonical_map）、
# move_thread 换世界、这条线的故事时间、缺口的 after/before/mentioned_in、世界判定依据/设定
# 笔记。这些字段改了，档案被判「签名没变」悄悄跳过，内容永远是旧的。
# 改法：签名直接哈希「渲染好、真正会发给模型的输入文本」（archive_input.thread_input() /
# world_input() / map_input() 的返回值）+ 提示词模板名。输入里有什么，签名就管什么——
# 以后 archive_input 加字段，不用再回头给这里补参数。


def input_sig(text: str, prompt: str) -> str:
    """通用输入签名：哈希渲染好的模型输入文本 + 提示词模板名/版本。
    thread_sig / world_sig / map_sig 都是它的薄封装，只是给调用方一个更好认的名字。"""
    return _digest(prompt, text)


def thread_sig(text: str, prompt: str = "archive_thread") -> str:
    """一条线的输入签名：哈希 archive_input.thread_input() 渲染出来的文本。"""
    return input_sig(text, prompt)


def world_sig(text: str, prompt: str = "archive_world") -> str:
    """一个世界的输入签名：哈希 archive_input.world_input() 渲染出来的文本。"""
    return input_sig(text, prompt)


def map_sig(text: str, prompt: str = "map") -> str:
    """地图的输入签名：哈希 archive_input.map_input() 渲染出来的文本——已经包含严重矛盾清单、
    缺口总览、各条线写到哪（C 组审查「必须修 5」：这三样以前不在签名里，档案文件没变时
    地图会停在旧清单，现在跟着渲染文本一起哈希，自动解决）。"""
    return input_sig(text, prompt)


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
    """index 只是省钱用的记录：文件 JSON 坏了、或者字段类型对不上，都当空壳处理——
    最多是多花点钱重跑，不该让步骤 7 直接崩掉（作者手改、同步冲突都可能产生坏文件）。"""
    try:
        data = read_json(book.archive_index_path, None)
    except (OSError, ValueError) as e:
        log.warning("档案 index %s 读取失败（%s），当空壳处理", book.archive_index_path, e)
        return json.loads(json.dumps(EMPTY_INDEX))
    if not isinstance(data, dict):
        if data is not None:
            log.warning("档案 index %s 顶层不是字典，当空壳处理", book.archive_index_path)
        return json.loads(json.dumps(EMPTY_INDEX))
    for k in ("threads", "worlds", "map"):
        if k in data and not isinstance(data[k], dict):
            log.warning("档案 index %s 字段 %s 类型不对，当空壳处理", book.archive_index_path, k)
            return json.loads(json.dumps(EMPTY_INDEX))
    for k, empty in (("threads", {}), ("worlds", {}), ("map", {})):
        data.setdefault(k, json.loads(json.dumps(empty)))
    return data


def write_index(book: Book, data: dict) -> None:
    book.archive_dir.mkdir(parents=True, exist_ok=True)
    write_json(book.archive_index_path, data)


SCENE_REF = re.compile(r"\[(S-\d{4}(?:,S-\d{4})*)\]")


def refs_in(text: str) -> list[str]:
    """抓出正文里所有场景引用编号，按出现顺序。"""
    out = []
    for m in SCENE_REF.finditer(text or ""):
        out.extend(m.group(1).split(","))
    return out


def check_archive(md: str, allowed: set[str], required_headings: list[str]) -> list[str]:
    """档案（支线档案 / 世界设定集 / 全书地图共用）的检查，返回要反馈给模型的问题（空列表 = 没问题）。
    引用格式是四件产出共同的硬规则（spec 3.1）：编不出场景编号的结论不许写。"""
    problems = []
    missing = [h for h in required_headings if f"## {h}" not in (md or "")]
    if missing:
        problems.append("缺这几个小节：" + "、".join(missing))
    refs = refs_in(md)
    if not refs:
        problems.append("正文里一个场景编号都没有，每句结论都要带 [S-0003] 这样的编号")
    bad = sorted({r for r in refs if r not in allowed})
    if bad:
        problems.append("这些编号不属于这份档案的范围，不许写：" + "、".join(bad[:10]))
    return problems


_MULTI = "（多个说法）"


def backfill_refs(md: str, groups: list[dict]) -> str:
    """把世界设定集里的「（多个说法）」补上对应的矛盾编号。纯文本替换，不花钱（spec 第 5 节）。

    设定集和矛盾扫描并行跑，写档案时 C- 编号还不存在，模型固定写「（多个说法）」占位，
    两边都跑完后由这个函数回填。按「这一行的属性节 + 行首的主语」对到 (subject, attribute)；
    对不上的原样留着。"""
    by_key = {(g.get("subject"), g.get("attribute")): g.get("id") for g in groups}
    attr = ""
    out = []
    for line in (md or "").splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("## "):
            attr = stripped[3:].strip()
        elif _MULTI in line and stripped.startswith("- ") and "：" in line:
            subject = stripped[2:].split("：", 1)[0].strip()
            gid = by_key.get((subject, attr))
            if gid:
                line = line.replace(_MULTI, f"（多个说法，见矛盾 {gid}）")
        out.append(line)
    return "".join(out)
