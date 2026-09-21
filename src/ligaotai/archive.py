"""步骤 7：支线档案 + 世界设定集 + 矛盾扫描 + 全书地图。

- 输入签名、按编号对账：档案要能单独重跑（作者只改了一条线，只重跑那一份，别的不花钱），
  所以每份档案在 档案/index.json 里记住它的输入签名。
- 编排 run_archive：支线档案、世界设定集、矛盾扫描三件并行 → 程序回填 C- 编号 → 全书地图。
  开跑、跑地图之前、跑完各渲染一遍全部输入比对，跑的途中上游变了，基于旧输入生成的档案标过期，
  这一步记 outdated 不记 done。

见 docs/superpowers/specs/2026-09-16-ligaotai-plan2c-archives-design.md。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime

from . import archive_input as ai
from . import hanfold
from . import contradictions as cd
from .book import Book, now_iso
from .cards import load_cards, pick_error
from .facts import OTHER, candidates, collect_facts, group_facts, norm_attr
from .fsutil import atomic_write_text, read_json, write_json
from .llm import LLMClient
from .llm_caller import Caller, Progress, _noop
from .prompts import load_prompt
from .scenes import read_scene, scene_path
from .threads_input import name_map

EMPTY_INDEX = {"threads": {}, "worlds": {}, "map": {}}

log = logging.getLogger(__name__)


def _digest(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(p, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


# 9-17 改的签名契约（C 组审查「必须修 1」）：原先按 spec 7.1 挑出来的几个字段算签名
# （线名/场景哈希/断点/缺口……），实测漏了模型实际会看到的输入——规范名映射（canonical_map）、
# move_thread 换世界、这条线的故事时间、缺口的 after/before/mentioned_in、世界判定依据/设定
# 笔记。这些字段改了，档案被判「签名没变」悄悄跳过，内容永远是旧的。
# 改法：签名直接哈希「渲染好、真正会发给模型的输入文本」（archive_input.thread_input() /
# world_input() / map_input() 的返回值）+ 提示词模板名。输入里有什么，签名就管什么——
# 以后 archive_input 加字段，不用再回头给这里补参数。


def prompt_sig(name: str) -> str:
    """提示词内容的签名：哈希 prompts/<name>.md 里真正发给模型的「## system」「## user」两段模板。
    第一个标题之前给人看的说明不算——改说明不该让档案重跑花钱。

    DE 审查第 6 条（9-19 定）：签名原来只带提示词**名字**，调了提示词已有档案
    被判「没过期」跳过，改提示词不生效。现在改了提示词，用到它的档案 / 矛盾 / 地图都判过期。"""
    system, user = load_prompt(name)
    return _digest(system.template, user.template)


def input_sig(text: str, prompt: str) -> str:
    """通用输入签名：哈希渲染好的模型输入文本 + 提示词模板名 + 提示词内容。
    thread_sig / world_sig / map_sig 都是它的薄封装，只是给调用方一个更好认的名字。"""
    return _digest(prompt, prompt_sig(prompt), text)


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
    # 条目级别也兜底：{"threads": {"L-001": "x"}} 这种，丢掉坏条目（当没生成过，重跑一份），
    # 不然 reconcile / 编排给它设 outdated 时会抛 TypeError（C 组审查建议修 3）。
    for k in ("threads", "worlds"):
        bad = [oid for oid, e in data[k].items() if not isinstance(e, dict)]
        for oid in bad:
            log.warning("档案 index %s 里 %s/%s 不是字典，丢掉", book.archive_index_path, k, oid)
            del data[k][oid]
    if "contradictions" in data and not isinstance(data["contradictions"], dict):
        del data["contradictions"]
    return data


def write_index(book: Book, data: dict) -> None:
    book.archive_dir.mkdir(parents=True, exist_ok=True)
    write_json(book.archive_index_path, data)


SCENE_REF = cd.SCENE_REF  # 跟矛盾扫描 reason 检查同源，写法变体见那边的注释


def refs_in(text: str) -> list[str]:
    """抓出正文里所有场景引用编号，按出现顺序。"""
    out = []
    for m in SCENE_REF.finditer(text or ""):
        out.extend(cd._SCENE_ID.findall(m.group(1)))
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


_HEADING = re.compile(r"^#{2,4}\s+(.+)$")
_BULLET = re.compile(r"^[-*+]\s+(.+?)\s*[：:]")
_DECOR = re.compile(r"[*`_\s【】\[\]]+")


def _section_attr(title: str) -> str:
    """节标题 → 受控属性名；不是受控属性（含「其他」和「设定」这类总标题）一律返回空串，
    切断上一节，免得下面的行按上一节的属性去对。容忍加粗、「设定·兵器」这类前缀、末尾冒号。"""
    t = _DECOR.sub("", title).rstrip("：:")
    t = re.split(r"[·：:、/]", t)[-1]
    a = norm_attr(t)
    return a if a != OTHER else ""


def _subject_key(s: str) -> str:
    """主语比对键：去掉加粗等装饰和空白，繁体折叠成简体（只用于比对）。"""
    return hanfold.fold(_DECOR.sub("", s or ""))


def backfill_refs(md: str, groups: list[dict], aliases: dict[str, str] | None = None) -> str:
    """把世界设定集里的「（多个说法）」补上对应的矛盾编号。纯文本替换，不花钱（spec 第 5 节）。

    设定集和矛盾扫描并行跑，写档案时 C- 编号还不存在，模型固定写「（多个说法）」占位，
    两边都跑完后由这个函数回填。按「这一行的属性节 + 行首的主语」对到 (subject, attribute)；
    对不上的原样留着。

    真数据上模型的写法五花八门（DE 审查必须修3，西游记 47 组只对上 24 / 0 / 0 组）：规范名是
    繁体、模型写成简体；属性节写成 `### 兵器`；主语加粗；写的是别名。所以两边都做繁简折叠
    （hanfold，只用于比对）、去装饰，属性节认二到四级标题，再用 aliases（{原文名: 规范名}，
    即实体的规范名映射）把别名映射回规范名。"""
    by_key = {(_subject_key(g.get("subject")), g.get("attribute")): g.get("id") for g in groups
              if isinstance(g, dict) and g.get("id")}
    alias_key: dict[str, str] = {}
    for name, canon in (aliases or {}).items():
        k = _subject_key(name)
        if alias_key.get(k, canon) != canon:
            alias_key[k] = ""  # 同一个折叠键指向两个规范名：说不清，不用
        else:
            alias_key[k] = canon
    attr = ""
    out = []
    for line in (md or "").splitlines(keepends=True):
        stripped = line.strip()
        h = _HEADING.match(stripped)
        if h:
            attr = _section_attr(h.group(1))
        elif _MULTI in line and attr:
            b = _BULLET.match(stripped)
            if b:
                key = _subject_key(b.group(1))
                gid = by_key.get((key, attr))
                if not gid and alias_key.get(key):
                    gid = by_key.get((_subject_key(alias_key[key]), attr))
                if gid:
                    line = line.replace(_MULTI, f"（多个说法，见矛盾 {gid}）")
        out.append(line)
    return "".join(out)


# --------------------------------------------------------------------------------------
# 编排（Task 16/17）
# --------------------------------------------------------------------------------------

THREAD_HEADINGS = ["来龙去脉", "主要人物", "写到哪", "缺口", "开放的伏笔"]
MAP_HEADINGS = ["全书概况"]
_ANY_SCENE = re.compile(r"S-\d{4}")
_BACKFILLED = re.compile(r"（多个说法，见矛盾 C-\d+）")


@dataclass
class Inputs:
    """步骤 7 全部模型输入，渲染好的文本。开跑、跑地图前、跑完各算一次，比对它们判断上游变没变。"""

    unit: str
    threads: list[dict]
    worlds: list[dict]
    gaps: list[dict]
    times: dict[str, dict]
    intersections: list[dict] = field(default_factory=list)
    thread_text: dict[str, str] = field(default_factory=dict)
    thread_scope: dict[str, set[str]] = field(default_factory=dict)
    world_text: dict[str, str] = field(default_factory=dict)
    world_scope: dict[str, set[str]] = field(default_factory=dict)
    contra: dict = field(default_factory=dict)  # cands / skipped / batches / stats / sig
    aliases: dict[str, str] = field(default_factory=dict)  # {原文名: 规范名}，回填时把别名对回规范名

    def sigs(self) -> dict:
        return {
            "threads": {tid: thread_sig(t) for tid, t in self.thread_text.items()},
            "worlds": {wid: world_sig(t) for wid, t in self.world_text.items()},
            "contradictions": self.contra["sig"],
            # 只进地图输入、不进任何一份档案的东西（不归任何线的缺口等）：也得算进指纹，
            # 不然跑的途中改了它发现不了。线的写到哪已经在线档案的输入文本里了。
            "map_only": _digest(self.gaps, self.intersections),
        }

    def fingerprint(self) -> str:
        return _digest(self.sigs())


def _ids(v) -> list[str]:
    return [s for s in (v or []) if isinstance(s, str)] if isinstance(v, list) else []


def _world_scene_ids(w: dict, threads: list[dict]) -> list[str]:
    """一个世界的全部块：它名下线里的正文、提纲，加上世界自己挂的设定笔记、提纲（同 threads._world_scenes）。"""
    ids = [s for t in threads if t.get("world") == w["id"] for s in _ids(t.get("scenes")) + _ids(t.get("outlines"))]
    ids += _ids(w.get("notes")) + _ids(w.get("outlines"))
    return list(dict.fromkeys(ids))


def _note_text(book: Book, sid: str) -> str:
    """设定笔记要给模型看**正文原文**（不是卡片摘要），去掉场景文件的头信息。读不了给空串。"""
    try:
        return read_scene(scene_path(book, sid)).text.strip()
    except (OSError, ValueError):
        return ""


def prepare_inputs(book: Book) -> Inputs:
    """读 世界与支线.json、场景卡、实体.json，渲染出步骤 7 每次调用真正要发给模型的文本。纯本地计算。"""
    data = read_json(book.threads_path, None)
    if not isinstance(data, dict):
        raise ValueError("还没有归线结果（世界与支线.json），先跑归线排序")
    threads = [t for t in data.get("threads") or [] if isinstance(t, dict) and isinstance(t.get("id"), str) and t["id"]]
    worlds = [w for w in data.get("worlds") or [] if isinstance(w, dict) and isinstance(w.get("id"), str) and w["id"]]
    gaps = [g for g in data.get("gaps") or [] if isinstance(g, dict)]
    unit = data.get("time_unit") or "年"
    cards = {sid: r["card"] for sid, r in load_cards(book).items() if isinstance(r.get("card"), dict)}
    cmap = name_map(book)
    times = cd.scene_times(threads)
    inp = Inputs(unit, threads, worlds, gaps, times,
                 [c for c in data.get("intersections") or [] if isinstance(c, dict)])
    for (_, name), canon in cmap.items():
        # 同一个叫法在不同类型下指向不同规范名：说不清，记空串，回填时不用它
        inp.aliases[name] = canon if inp.aliases.get(name, canon) == canon else ""

    for t in threads:
        text = ai.thread_input(t, cards, cmap, [g for g in gaps if g.get("thread") == t["id"]], times, unit)
        inp.thread_text[t["id"]] = text
        # 缺口「提到于」的场景可能在别的线里；材料里给了模型的编号都算合法引用，不然白白重试
        inp.thread_scope[t["id"]] = set(_ids(t.get("scenes"))) | set(_ANY_SCENE.findall(text))

    covered: list[str] = []
    for w in worlds:
        sids = _world_scene_ids(w, threads)
        covered += sids
        rows = collect_facts({s: cards[s] for s in sids if s in cards}, cmap)
        notes = [{"id": s, "text": _note_text(book, s)} for s in _ids(w.get("notes"))]
        text = ai.world_input(w, rows, notes, [t for t in threads if t.get("world") == w["id"]])
        inp.world_text[w["id"]] = text
        inp.world_scope[w["id"]] = set(sids) | set(_ANY_SCENE.findall(text))

    # 矛盾只比对归进了世界 / 线的块：版本组里的非主版本、没分配的块不参与（否则同一场景的两个版本会被当成矛盾）
    covered += [s for t in threads for s in _ids(t.get("scenes")) + _ids(t.get("outlines"))]
    scope = dict.fromkeys(covered)
    rows = collect_facts({s: cards[s] for s in scope if s in cards}, cmap)
    grouped = group_facts(rows)
    st = book.settings()
    cands, skipped = cd.cap(candidates(grouped), st["contradictions_max_groups"])
    parts = cd.batches(cands, times, unit, st["contradictions_batch_tokens"], st["contradictions_max_batch_groups"])
    batches, start = [], 0
    for part in parts:
        text, numbered = cd.render_values(part, start, times, unit)
        batches.append({"start": start, "text": text, "ids": list(numbered)})
        start += len(part)
    stats = {
        "facts": len(rows),
        "grouped": len(grouped),
        "dropped_other": sum(1 for r in rows if r.attribute == OTHER),
        "candidates": len(cands),
        "merged_by_program": sum(c.get("merged", 0) for c in cands),
        "sent": len(cands),
    }
    sig = _digest("contradictions", prompt_sig("contradictions"), unit, [b["text"] for b in batches], skipped, stats)
    inp.contra = {"cands": cands, "skipped": skipped, "batches": batches, "stats": stats, "sig": sig}
    return inp


def _try_prepare(book: Book) -> Inputs | None:
    try:
        return prepare_inputs(book)
    except Exception as e:  # 跑的途中 世界与支线.json 被改坏了：当「上游变了」处理
        log.warning("重新读取步骤 7 的输入失败：%s", e)
        return None


def _fresh(entry, sig: str, path) -> bool:
    """跳过不花钱的三个条件缺一不可：签名一样、文件还在、没被标过期（单独重跑接口会标）。"""
    return isinstance(entry, dict) and entry.get("sig") == sig and not entry.get("outdated") and path.exists()


def _body(d) -> str:
    return d["body"] if isinstance(d, dict) and isinstance(d.get("body"), str) else ""


def _check_body(d, allowed: set[str], headings: list[str]) -> list[str]:
    if not _body(d).strip():
        return ['只输出 JSON：{"body": "<Markdown 正文>"}，body 不能是空的']
    return check_archive(_body(d), allowed, headings)


async def _gather(coros) -> list:
    """并行跑，一个出错**不掐断**别的：作者点暂停时，已经发出去的调用让它跑完进缓存（钱已经花了），
    各自停在下一个进度检查点，不再开新调用。全部结束后再抛（欠费 / key 失效优先，别被「已暂停」盖住）。"""
    results = await asyncio.gather(*coros, return_exceptions=True)
    errors = [r for r in results if isinstance(r, BaseException)]
    if errors:
        raise pick_error(BaseExceptionGroup("步骤 7", errors))
    return results


class _Run:
    def __init__(self, book: Book, caller: Caller, inp: Inputs, index: dict):
        self.book, self.caller, self.inp, self.index = book, caller, inp, index
        self.generated: dict[str, list] = {"threads": [], "worlds": []}
        self.reused: dict[str, list] = {"threads": [], "worlds": []}
        self.contra_status = ""
        self.contra_failed = False

    def _save_index(self) -> None:
        # 每落一份档案就写一次 index：暂停、崩溃后重跑，已经落盘的按签名跳过
        write_index(self.book, self.index)

    async def archive(self, kind: str, oid: str) -> None:
        inp, book = self.inp, self.book
        if kind == "threads":
            text, sig, prompt = inp.thread_text[oid], thread_sig(inp.thread_text[oid]), "archive_thread"
            path, rel, scope, headings = (book.thread_archive_dir / f"{oid}.md", f"档案/支线/{oid}.md",
                                          inp.thread_scope[oid], THREAD_HEADINGS)
            tag = f"thread/{oid}"
        else:
            text, sig, prompt = inp.world_text[oid], world_sig(inp.world_text[oid]), "archive_world"
            path, rel, scope, headings = (book.world_archive_dir / f"{oid}.md", f"档案/世界/{oid}.md",
                                          inp.world_scope[oid], [])
            tag = f"world/{oid}"
        entry = self.index[kind].get(oid)
        if _fresh(entry, sig, path):
            self.reused[kind].append(oid)
            # 按签名跳过、没真调模型：这一项对应的缓存条目也占住位置，别被 prune_cache 清掉（C1）
            self.caller.keep(prompt, {"body": text})
            return
        self.caller.plan(1)
        got = await self.caller.call(
            prompt, {"body": text},
            check=lambda d: _check_body(d, scope, headings),
            clean=_body,
            usable=lambda md: bool((md or "").strip()),
            tag=tag,
        )
        if not got:
            # 失败：旧文件（如果有）留着给作者看，但标过期；新签名不记，下次一定重跑
            if isinstance(entry, dict):
                entry["outdated"] = True
                self._save_index()
            return
        atomic_write_text(path, got)
        # I2（9-20 定）：换模型不进签名（换一次模型 = 全部档案重付一次钱，不值），
        # 但记下生成时用的模型名，给界面对比 index 里的模型名和当前配置、提示作者要不要重跑
        # （docs/已知问题与待办.md）。
        model = self.caller.cfg.get("model", "")
        new = {"file": rel, "sig": sig, "outdated": False, "generated": now_iso(), "model": model}
        if kind == "threads":
            t = next(t for t in inp.threads if t["id"] == oid)
            new = {"file": rel, "sig": sig, "scenes": _ids(t.get("scenes")), "world": t.get("world", ""),
                   "outdated": False, "generated": new["generated"], "model": model}
        self.index[kind][oid] = new
        self.generated[kind].append(oid)
        self._save_index()

    def _read_contradictions(self) -> dict | None:
        """读上一轮的 矛盾.json。坏了先备份一份再当没有（里面可能有作者的裁决，不能直接盖掉）。"""
        p = self.book.contradictions_path
        try:
            data = read_json(p, None)
        except (OSError, ValueError):
            data = False
        if data is None:
            return None
        if not isinstance(data, dict):
            backup = p.with_name(f"矛盾.损坏备份-{datetime.now():%Y%m%d-%H%M%S}.json")
            try:
                shutil.copy2(p, backup)
                log.warning("矛盾.json 读不了，已备份到 %s，按没有上一轮处理", backup.name)
            except OSError:
                pass
            return None
        return data

    async def contradictions(self) -> dict:
        c, index = self.inp.contra, self.index
        entry = index.get("contradictions")
        if isinstance(entry, dict) and entry.get("sig") == c["sig"] and not entry.get("failed") \
                and not entry.get("outdated"):
            old = self._read_contradictions()
            if old is not None:
                self.contra_status = "reused"
                # 沿用上一轮的矛盾判断、没真调模型：每一批对应的缓存条目也占住位置（C1）
                for b in c["batches"]:
                    self.caller.keep("contradictions", {"unit": self.inp.unit, "groups": b["text"]})
                return old
        batches = c["batches"]
        self.caller.plan(len(batches))
        judged: dict[int, dict] = {}
        failed: list[int] = []

        async def one(i: int, b: dict) -> None:
            ids = set(b["ids"])
            got = await self.caller.call(
                "contradictions", {"unit": self.inp.unit, "groups": b["text"]},
                check=lambda d: cd.check_output(d, ids),
                clean=lambda d: cd.clean_output(d, ids),
                tag=f"contradictions/{i}",
            )
            if got is None:  # 这一批失败：build_result 兜底成「无法判断」，index 记 failed，下次重跑
                failed.append(i)
                return
            # judged 的键是 cands 的下标；按批内位置对回去，别解析 C-编号里的数字
            for k, cid in enumerate(b["ids"]):
                if cid in got:
                    judged[b["start"] + k] = got[cid]

        await _gather([one(i, b) for i, b in enumerate(batches)])
        # 上一轮的结果在模型跑完之后才读：跑的途中作者可能改了裁决，别拿开跑时的旧快照盖掉
        old = self._read_contradictions() or {"next_id": 1, "groups": []}
        if failed:
            # 失败批次里的组：上一轮判过、值集合没变的，沿用上一轮的判断（花过钱的结果），
            # 别让 build_result 兜底成「这一批调用失败」盖掉；index 照样记 failed，下次重跑。
            prev = {(g.get("subject"), g.get("attribute")): g for g in old.get("groups") or []
                    if isinstance(g, dict) and g.get("status") in cd.STATUSES}
            for i in failed:
                b = batches[i]
                for k in range(len(b["ids"])):
                    cand = c["cands"][b["start"] + k]
                    g = prev.get((cand["subject"], cand["attribute"]))
                    if g and g.get("values_sig") == cd.values_sig(cand["values"]):
                        judged[b["start"] + k] = {x: g.get(x, "") for x in ("status", "level", "category", "reason")}
        result = cd.build_result(c["cands"], judged, self.inp.times, old, c["stats"], c["skipped"])
        for key in cd.STATUSES:
            result["stats"][key] = sum(1 for g in result["groups"] if g["status"] == key)
        write_json(self.book.contradictions_path, result)
        self.contra_failed = bool(failed)
        self.contra_status = "generated"
        index["contradictions"] = {"file": "矛盾.json", "sig": c["sig"], "failed": bool(failed),
                                   "outdated": False, "generated": now_iso(),
                                   "model": self.caller.cfg.get("model", "")}
        self._save_index()
        return result

    def backfill(self, groups: list[dict]) -> int:
        """回填 C- 编号。先把上一轮回填过的还原成占位再填：矛盾编号变了不会留下指错的旧编号，
        重复跑结果不变（地图签名才能稳定）。返回回填后仍然光秃秃的「（多个说法）」个数——
        对不上的不静默，进 summary 给作者看（DE 审查必须修3）。"""
        left = 0
        for wid in self.inp.world_text:
            p = self.book.world_archive_dir / f"{wid}.md"
            if not p.exists():
                continue
            before = p.read_text(encoding="utf-8")
            after = backfill_refs(_BACKFILLED.sub(_MULTI, before), groups, self.inp.aliases)
            left += after.count(_MULTI)
            if after != before:
                atomic_write_text(p, after)
        return left

    def map_blockers(self) -> list[str]:
        out = []
        inp, book = self.inp, self.book
        for tid, text in inp.thread_text.items():
            if not _fresh(self.index["threads"].get(tid), thread_sig(text), book.thread_archive_dir / f"{tid}.md"):
                out.append(tid)
        for wid, text in inp.world_text.items():
            if not _fresh(self.index["worlds"].get(wid), world_sig(text), book.world_archive_dir / f"{wid}.md"):
                out.append(wid)
        if self.contra_failed:
            out.append("矛盾扫描有批次失败")
        return out

    async def map(self, contra: dict) -> str:
        inp, book = self.inp, self.book
        blockers = self.map_blockers()
        if not inp.thread_text and not inp.world_text:
            # m8：一条线一个世界都没有，渲染出的输入里一个场景编号都没有，allowed 是空集，
            # check_archive 必然报「一个场景编号都没有」→ 模型重试到底才失败。别发这笔请求。
            blockers.append("一条线一个世界都没有，地图没有可引的场景")
        mid = _try_prepare(book)
        if mid is None or mid.fingerprint() != inp.fingerprint():
            blockers.append("跑的途中上游变了")
        if blockers:
            # 地图读全部档案：缺一份、或者档案是拿旧输入写的，跑了也是错的，先不花这笔钱
            self.index["map"]["outdated"] = True
            self.index["map"]["blocked_by"] = blockers[:20]
            self._save_index()
            return "blocked"
        text = ai.map_input(
            [book.world_archive_dir / f"{w}.md" for w in inp.world_text],
            [book.thread_archive_dir / f"{t}.md" for t in inp.thread_text],
            contra.get("groups") or [], inp.gaps,
            [{"id": t["id"], "name": t.get("name", ""), "state": (t.get("end") or {}).get("state", ""),
              "last": (t.get("end") or {}).get("last", "")} for t in inp.threads],
            inp.intersections,
        )
        sig = map_sig(text)
        if _fresh(self.index["map"], sig, book.map_path):
            # 按签名跳过、没真调模型：这份地图对应的缓存条目也占住位置，别被 prune_cache 清掉（C1）
            self.caller.keep("map", {"body": text})
            return "reused"
        allowed = set(_ANY_SCENE.findall(text)) | {s for sc in inp.world_scope.values() for s in sc} \
            | {s for sc in inp.thread_scope.values() for s in sc}
        self.caller.plan(1)
        got = await self.caller.call(
            "map", {"body": text},
            check=lambda d: _check_body(d, allowed, MAP_HEADINGS),
            clean=_body,
            usable=lambda md: bool((md or "").strip()),
            tag="map",
        )
        if not got:
            self.index["map"]["outdated"] = True
            self._save_index()
            return "failed"
        atomic_write_text(book.map_path, got)
        self.index["map"] = {"file": "全书地图.md", "sig": sig, "outdated": False, "generated": now_iso(),
                             "model": self.caller.cfg.get("model", "")}
        self._save_index()
        return "generated"

    def settle(self, end: Inputs | None) -> bool:
        """跑完：拿跑完时的输入重新比一遍，基于旧输入生成的档案标过期（不删文件）。返回上游是不是变了。"""
        changed = end is None or end.fingerprint() != self.inp.fingerprint()
        if end is None:
            for kind in ("threads", "worlds"):
                for e in self.index[kind].values():
                    e["outdated"] = True
            self.index["map"]["outdated"] = True
            if isinstance(self.index.get("contradictions"), dict):
                self.index["contradictions"]["outdated"] = True
            return True
        now = end.sigs()
        reconcile(self.index, set(now["threads"]), set(now["worlds"]))
        for kind in ("threads", "worlds"):
            for oid, e in self.index[kind].items():
                if oid in now[kind] and e.get("sig") != now[kind][oid]:
                    e["outdated"] = True
        ce = self.index.get("contradictions")
        if isinstance(ce, dict) and ce.get("sig") != now["contradictions"]:
            ce["outdated"] = True
        # 地图依赖全部档案：有一份当前的档案不是最新，地图也不是；上游在途中变过，
        # 地图是拿旧输入写的（哪怕只改了只进地图的缺口），也不是
        stale = [oid for kind in ("threads", "worlds") for oid in now[kind]
                 if not isinstance(self.index[kind].get(oid), dict) or self.index[kind][oid].get("outdated")]
        if changed or stale or (isinstance(ce, dict) and ce.get("outdated")):
            self.index["map"]["outdated"] = True
        return changed


def run_archive(book: Book, client: LLMClient, progress: Progress = _noop) -> dict:
    """步骤 7 入口。三件并行 → 程序回填 C- 编号 → 全书地图（spec 第 3 节）。"""
    return asyncio.run(_run_archive(book, client, progress))


async def _run_archive(book: Book, client: LLMClient, progress: Progress) -> dict:
    inp = prepare_inputs(book)
    index = load_index(book)
    removed = reconcile(index, set(inp.thread_text), set(inp.world_text))
    write_index(book, index)
    # 缓存路径必须是档案自己的：归线缓存是花过钱的结果，prune 时会被清掉
    caller = Caller(book, client, progress, cache_path=book.archive_cache_path, tag_prefix="archive")
    run = _Run(book, caller, inp, index)
    try:
        _, _, contra = await _gather([
            _gather([run.archive("threads", tid) for tid in inp.thread_text]),
            _gather([run.archive("worlds", wid) for wid in inp.world_text]),
            run.contradictions(),
        ])
        # 回填：矛盾跑完才有 C- 编号，设定集是并行写的，这里补（纯文本替换，不花钱），必须在地图之前
        unfilled = run.backfill(contra.get("groups") or [])
        map_status = await run.map(contra)
    finally:
        u = client.usage
        book.add_usage("archive", u.calls, u.prompt_tokens, u.completion_tokens, u.cost(client.cfg))

    input_changed = run.settle(_try_prepare(book))
    write_index(book, index)
    caller.prune_cache()

    groups = contra.get("groups") or []
    incomplete = bool(index["map"].get("outdated")) or run.contra_failed or any(
        not isinstance(index[k].get(oid), dict) or index[k][oid].get("outdated")
        for k, texts in (("threads", inp.thread_text), ("worlds", inp.world_text)) for oid in texts)
    summary = {
        "threads": len(inp.thread_text),
        "worlds": len(inp.world_text),
        "contradictions": len(groups),
        "严重": sum(1 for g in groups if g.get("status") == "真矛盾" and g.get("level") == "严重"),
        "skipped": len(contra.get("skipped") or []),
        "unfilled_multi": unfilled,  # 世界设定集里回填不上矛盾编号的「（多个说法）」
        "generated": {**run.generated, "contradictions": run.contra_status == "generated",
                      "map": map_status == "generated"},
        "reused": {**run.reused, "contradictions": run.contra_status == "reused", "map": map_status == "reused"},
        "map": map_status,
        "outdated_removed": removed,
        "input_changed": input_changed,
        "calls": client.usage.calls,
        "cost_usd": round(client.usage.cost(client.cfg), 4),
        "failed": caller.failed,
        "unresolved": caller.unresolved,
    }
    status = "outdated" if (input_changed or incomplete) else "done"
    book.set_step("archive", status, summary=summary)
    return summary
