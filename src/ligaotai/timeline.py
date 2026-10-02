"""故事时间线冲突检查的纯函数部分（spec 2026-09-28-ligaotai-timeline-check-design.md）。

只用先后顺序，不用估出来的时间数值（数值不硬，②c 以来的结论）。不读模型、不写文件。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from .book import Book
from .cards import load_cards
from .skeleton import scene_info
from .skeleton_order import build_sequence
from .threads_input import name_map
from .threads_ops import load_threads
from .triage import non_main_versions, version_map


def story_order(book: Book) -> tuple[list[str], dict[str, int], int, int]:
    """全书故事顺序（跟骨架同一个排法，所有线都参与，不看看板）。
    返回 (排好的场景编号, 编号 -> 位置, 排不进时间轴的块数, 完全没进任何线/未定区的块数)。

    第 3 项（unplaced）跟骨架一样：块本来在某条线里，但没时间、没对齐主线，或者在
    unassigned 里——build_sequence 已经把这些都记出来了。第 4 项是另一种情况：场景文件
    存在，但压根没被任何线的 scenes、也没被 unassigned 提到（比如挂在世界上的设定笔记、
    只在 outlines 里的提纲）——这类块不算「排不进」，是压根没参与检查，用单独字段区分，
    别悄悄漏计（审查：真书 4 个设定笔记原来没算进任何统计）。"""
    threads = load_threads(book)
    vmap = version_map(book)
    info = scene_info(book)
    removed = {sid for sid, x in info.items() if x["removed"]} | (non_main_versions(book) - set(vmap))
    seq, unplaced = build_sequence(threads, {}, removed, vmap)
    ids = [x["id"] for x in seq]
    tracked = set(ids) | {u["id"] for u in unplaced}
    untracked = len([sid for sid in info if sid not in removed and sid not in vmap and sid not in tracked])
    return ids, {s: i for i, s in enumerate(ids)}, len(unplaced), untracked


# 死亡词：值里出现就算死了（「亲属」这类属性说的是别人，不看）
DEATH_WORDS = ("死", "亡", "殁", "歿", "卒", "身故", "病故", "已故", "归天", "歸天", "逝",
               "阵亡", "陣亡", "斩", "斬", "枭首", "梟首", "丧命", "喪命", "殒命", "殞命",
               "去世", "坐化")
# 值里出现这些就不算（免死、被抓、只是差点死、说的是别的意思）
NOT_DEATH = ("免死", "未死", "不死", "没死", "沒死", "幾乎", "几乎", "险些", "險些", "差点", "差點",
             "被擒", "监禁", "監禁", "车囚", "車囚", "丁艱", "丁艰", "生还", "生還", "得救",
             "亡命", "视死", "視死", "死战", "死戰", "死守",
             "士卒", "兵卒", "狱卒", "獄卒", "走卒", "死囚", "逃亡", "诈死", "詐死", "假死",
             "死活", "生死不明", "存亡未卜")
DEATH_ATTRS = ("生死", "身份", "其他", "伤病", "結局", "结局")


def is_death(attribute: str, value: str) -> bool:
    """这条 fact 说的是不是「主语死了」。只负责缩小范围：拿不准的放进来，模型后面还要判。"""
    a, v = (attribute or "").strip(), (value or "").strip()
    if a not in DEATH_ATTRS or not v:
        return False
    if any(w in v for w in NOT_DEATH):
        return False
    return any(w in v for w in DEATH_WORDS)


MAX_LATER = 5  # A 类每人最多查死后多少场（防主角被误判「已死」时嫌疑爆炸）


def _canon(name: str, cmap: dict) -> str:
    n = (name or "").strip()
    return cmap.get(("person", n), n)


def _card(cards: dict, sid: str) -> dict:
    rec = cards.get(sid) or {}
    c = rec.get("card") if isinstance(rec, dict) else None
    return c if isinstance(c, dict) else {}


def persons_of(card: dict, cmap: dict) -> set[str]:
    out = {_canon(c.get("name", ""), cmap) for c in card.get("characters") or [] if isinstance(c, dict)}
    if card.get("pov"):
        out.add(_canon(card["pov"], cmap))
    out.discard("")
    return out


def death_suspects(seq: list[str], pos: dict[str, int], cards: dict, cmap: dict) -> tuple[list[dict], int]:
    """(嫌疑列表, 因上限截掉的个数)。嫌疑 = {who, death, death_quote, later}，按 (death 位置, later 位置) 排。"""
    first: dict[str, tuple[int, str, str]] = {}  # who -> (位置, 场景, 引文)
    for sid in seq:
        for f in _card(cards, sid).get("facts") or []:
            if not isinstance(f, dict) or not is_death(f.get("attribute", ""), f.get("value", "")):
                continue
            who = _canon(f.get("subject", ""), cmap)
            if who and who not in first:
                first[who] = (pos[sid], sid, str(f.get("quote") or f.get("value") or ""))
    out, capped = [], 0
    for who, (p, dsid, quote) in sorted(first.items(), key=lambda kv: (kv[1][0], kv[0])):
        later = [s for s in seq[p + 1:] if who in persons_of(_card(cards, s), cmap)]
        capped += max(0, len(later) - MAX_LATER)
        out += [{"who": who, "death": dsid, "death_quote": quote, "later": s} for s in later[:MAX_LATER]]
    return out, capped


MAX_CANDIDATES = 8  # C 类每条回指最多给模型几个候选场景


def _person_names_and_canon(cmap: dict) -> dict[str, str]:
    """所有 person 类型的叫法、以及规范名本身 -> 规范名，用来判断回指原话里有没有点到谁。"""
    out = {n: c for (t, n), c in cmap.items() if t == "person"}
    for c in set(out.values()):
        out.setdefault(c, c)
    return out


def _named_in_ref(ref: str, alias_to_canon: dict[str, str]) -> set[str]:
    """回指原话里出现的人物叫法（任一叫法），归一成规范名。"""
    return {c for n, c in alias_to_canon.items() if n and n in ref}


_HAN_LO, _HAN_HI = "一", "鿿"
HIGH_FREQ_FRACTION = 0.3  # 在超过这个比例的（参与检查的）场景里都出现的 bigram，不算重合


def _bigrams(text: str) -> set[str]:
    """文本里相邻两个字都是汉字的二元组集合（只用于比对重合度，不做任何分词）。"""
    return {text[i:i + 2] for i in range(len(text) - 1)
            if _HAN_LO <= text[i] <= _HAN_HI and _HAN_LO <= text[i + 1] <= _HAN_HI}


def _candidate_text(card: dict) -> str:
    events = card.get("events") or []
    return " ".join([str(card.get("summary") or "")] + [str(e) for e in events if isinstance(e, str)])


def _scene_bigrams(seq: list[str], cards: dict) -> tuple[dict[str, set[str]], set[str]]:
    """每个参与检查的场景（summary + events）的 bigram 集合，剔掉本次检查里超过 30% 场景都
    出现的高频 bigram（现算，不写死词表——书不同、高频虚词组合也不同）。"""
    raw = {sid: _bigrams(_candidate_text(_card(cards, sid))) for sid in seq}
    df: Counter[str] = Counter()
    for bg in raw.values():
        df.update(bg)
    thresh = HIGH_FREQ_FRACTION * len(seq)
    high = {b for b, c in df.items() if c > thresh}
    return {sid: bg - high for sid, bg in raw.items()}, high


def ref_suspects(seq: list[str], pos: dict[str, int], cards: dict, cmap: dict,
                 line_of: dict[str, str], picks: dict[tuple[str, str], list[str]] | None = None,
                 ) -> tuple[list[dict], int, int]:
    """(要问模型的回指, 没有候选的回指数, 候选全在前面、不用问的回指数)。
    要问的 = {scene, ref, candidates}。每条回指单独挑候选（不再是同一场所有回指共用一组）：
    候选场景要么人物名单（归一后）里有回指原话点名的人（任一叫法或规范名），要么跟回指所在场
    至少有 2 个共同人物（归一后）——只有 1 个共同人物、又没点名的不算候选，排序先看点没点名，
    再看回指原话跟候选场（summary + events）的汉字二元组重合数（降序，去掉高频 bigram——
    主角章章都在时「点名」「共同人物」对他没有区分度，这一键专门补上：回指原话里的专名
    通常只在真正相关的那场的 events 里出现），再看共同人物数降序、是否同线（同线优先）、
    跟回指场的距离（近的优先）、位置，取前 MAX_CANDIDATES 个。
    同一场里重复的回指原话去重，只问一次。
    picks：{(回指所在场, 回指原话): 模型从全书目录里挑的场}。挑中的排在最前、不受上面门槛限制，
    剩下的位置再按上面的规则补满——10-01 斗破真卡上字面候选只有 2/5 能把事件那场排进前 8
    （「晋级斗者」对「冲击斗者……突破成功」字面几乎不重合），意思上的对应只能靠模型。"""
    people = {s: persons_of(_card(cards, s), cmap) for s in seq}
    alias_to_canon = _person_names_and_canon(cmap)
    scene_bg, high_bg = _scene_bigrams(seq, cards)
    asks, no_cand, no_later = [], 0, 0
    for sid in seq:
        raw_refs = [r.strip() for r in _card(cards, sid).get("refs_elsewhere") or [] if isinstance(r, str) and r.strip()]
        refs = list(dict.fromkeys(raw_refs))
        if not refs:
            continue
        mine = people[sid]
        for r in refs:
            named = _named_in_ref(r, alias_to_canon)
            ref_bg = _bigrams(r) - high_bg
            picked = [p for p in dict.fromkeys((picks or {}).get((sid, r)) or []) if p in pos and p != sid]
            scored = []
            for o in seq:
                if o == sid or o in picked:
                    continue
                k = len(mine & people[o])
                hit = bool(named & people[o])
                if not (hit or k >= 2):
                    continue
                overlap = len(ref_bg & scene_bg.get(o, set()))
                scored.append((0 if hit else 1, -overlap, -k, line_of.get(o) != line_of.get(sid),
                              abs(pos[o] - pos[sid]), pos[o], o))
            cands = (picked + [x[-1] for x in sorted(scored)])[:MAX_CANDIDATES]
            if not cands:
                no_cand += 1
            elif all(pos[c] < pos[sid] for c in cands):
                no_later += 1
            else:
                asks.append({"scene": sid, "ref": r, "candidates": cands})
    return asks, no_cand, no_later


def ref_items(seq: list[str], cards: dict) -> list[tuple[str, str]]:
    """全书的回指（所在场, 原话），按故事顺序；同一场里重复的原话只留一条，空的跳过。"""
    out = []
    for sid in seq:
        raw = [r.strip() for r in _card(cards, sid).get("refs_elsewhere") or [] if isinstance(r, str) and r.strip()]
        out += [(sid, r) for r in dict.fromkeys(raw)]
    return out


INDEX_LINE = 100  # 目录里每场摘要留多少字：60 字时斗破 S-0088 的「最终成功突破」被截掉，模型认不出这场是晋级斗者


def index_line(cards: dict, sid: str) -> str:
    text = " ".join(str(_card(cards, sid).get("summary") or "").split())
    return f"[{sid}] {text[:INDEX_LINE]}"


def index_chunks(seq: list[str], cards: dict, max_chars: int) -> list[list[str]]:
    """目录按字数分段（每场一行 index_line，加换行），一段不超过 max_chars；单独一行就超的自成一段。"""
    out: list[list[str]] = []
    total = 0
    for s in seq:
        n = len(index_line(cards, s)) + 1
        if out and total + n <= max_chars:
            out[-1].append(s)
            total += n
        else:
            out.append([s])
            total = n
    return out


def name_snippets(text: str, names: list[str], width: int = 40, limit: int = 3) -> list[str]:
    """正文里提到这个人（任一叫法）的地方，每处取前后 width 字，最多 limit 处，互不重叠。
    一处都没有（叫法没对上）就给开头 40 字，让模型至少看到这场在讲什么。"""
    hits = []
    for n in sorted({n for n in names if n}, key=len, reverse=True):
        start = 0
        while (i := text.find(n, start)) >= 0:
            hits.append((i, i + len(n)))
            start = i + len(n)
    out, last_end = [], -1
    for a, b in sorted(hits):
        if a < last_end:
            continue
        lo, hi = max(0, a - width), min(len(text), b + width)
        out.append(text[lo:hi].replace("\n", " "))
        last_end = hi
        if len(out) >= limit:
            break
    return out or [text[:40].replace("\n", " ")]


def conflict_sig(c: dict) -> str:
    key = "\x1f".join([c.get("kind") or "", c.get("who") or "", c.get("ref") or "", *(c.get("scenes") or [])])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def assemble(conflicts: list[dict], old: dict) -> dict:
    """拼出 时间冲突.json 的 conflicts / next_id / id_registry。编号按签名沿用，裁决按签名沿用。
    旧文件是作者可以手改的，坏了当空的，不崩。"""
    old = old if isinstance(old, dict) else {}
    prev = {c.get("sig"): c for c in old.get("conflicts") or [] if isinstance(c, dict)} \
        if isinstance(old.get("conflicts"), list) else {}
    registry = {e["sig"]: e["id"] for e in old.get("id_registry") or []
                if isinstance(e, dict) and isinstance(e.get("sig"), str) and isinstance(e.get("id"), str)}
    for s, c in prev.items():
        if isinstance(s, str) and isinstance(c.get("id"), str):
            registry.setdefault(s, c["id"])
    try:
        next_id = int(old.get("next_id") or 1)
    except (TypeError, ValueError):
        next_id = 1
    used = [int(v[2:]) for v in registry.values() if v[2:].isdigit()]
    if used:
        next_id = max(next_id, max(used) + 1)
    out = []
    seen: set[str] = set()
    for c in conflicts:
        sig = conflict_sig(c)
        if sig in seen:
            continue  # 保险：同一签名出两条（比如同一场景的重复回指没被上游去重）只留一条
        seen.add(sig)
        if sig not in registry:
            registry[sig] = f"T-{next_id:03d}"
            next_id += 1
        verdict = (prev.get(sig) or {}).get("verdict")
        out.append({"id": registry[sig], **c, "sig": sig,
                    "verdict": verdict if isinstance(verdict, dict) else None})
    return {"conflicts": out, "next_id": next_id,
            "id_registry": [{"sig": s, "id": i} for s, i in sorted(registry.items(), key=lambda kv: kv[1])]}


def _relevant(card: dict) -> dict:
    return {k: card.get(k) for k in ("characters", "pov", "facts", "refs_elsewhere", "summary")}


def input_fingerprint(book: Book) -> str:
    """故事顺序 + 参与场景的卡（只取用得到的字段）+ 参与场景的正文哈希 + 实体规范名。
    任何一样变了，旧结果就过期。正文哈希用场景文件头信息里现成的 hash 字段（scene_info
    已经解析过场景文件了），不为了这个再整篇读一遍原文重算。"""
    seq, _, _, _ = story_order(book)
    cards = load_cards(book)
    info = scene_info(book)
    payload = {"seq": seq, "cards": {s: _relevant(_card(cards, s)) for s in seq},
               "text_hashes": {s: info.get(s, {}).get("hash", "") for s in seq},
               "names": sorted([list(k) + [v] for k, v in name_map(book).items()])}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
