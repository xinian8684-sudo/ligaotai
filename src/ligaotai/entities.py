"""步骤 5 实体合并：把场景卡里的人名、地名、组织名，按「是不是同一个」归组，给出规范名。

1. 程序汇总所有叫法：出现在哪些场景、原文上下文；再按字面找出一些「看着像」的提示对。
2. 按类型把全部叫法（带上下文和提示）交给综合档模型，让它把指同一对象的叫法归组。
   叫法太多时分批：出现次数最多的一批（锚点）放进每一批，冷门外号才能挂到主要人物身上；
   字面提示连起来的叫法尽量装进同一批。锚点之间是不是同一个，以第一批的判断为准，
   后面的批跟它冲突的组不合并，记进 summary 的 conflicts。
3. 所有类型的所有批一起并发。每批的结果按提示词全文 + 综合档配置（不含 max_tokens）+ 接口地址
   缓存进 实体合并缓存.json，暂停、单批失败、欠费中止后重跑，做完的批不用再花钱。
4. 模型全部调完才读 实体.json，「读 → 拼结果 → 写回」整段在 FILE_LOCK 里；作者的确认、改名、合并、
   拆分也在同一把锁里读改写，所以运行期间作者做的操作不会被覆盖，作者的操作之间也不会互相覆盖。
   模型给的组是草稿（draft），作者确认、改名、合并、拆分后才算数（confirmed）。
   只有 draft 和 single 会被重算，其他状态（confirmed 或不认识的）原样保留，里面的叫法不会被模型挪走。
   编号用文件顶层只增不减的 next_id；结果没变的草稿/single 沿用原编号。
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable

from .book import FILE_LOCK, Book
from .cards import is_fresh, load_cards, pick_error
from .fsutil import natural_key, read_json, write_json
from .llm import FatalLLMError, LLMClient, LLMError, cache_config, cache_key
from .prompts import render
from .scenes import load_scenes

TYPES = ("person", "location", "organization")
TYPE_LABELS = {"person": "人物", "location": "地点", "organization": "组织"}
CONTEXTS_PER_NAME = 2
CONTEXT_RADIUS = 20
MAX_NAMES_PER_CALL = 600
ANCHOR_NAMES = 150
HINT_LIMIT = 300
AFFIXES = (
    "大人", "姑娘", "公子", "先生", "夫人", "娘子", "小姐", "大哥", "阿哥", "大姐", "阿姐", "小哥", "小妹",
    "師父", "师父", "師兄", "师兄", "師弟", "师弟", "師妹", "师妹",
    "長老", "长老", "大王", "老爺", "老爷", "兄", "哥", "姐", "妹", "兒", "儿", "阿", "老", "小",
)
NICK_PREFIXES = ("阿", "小")
NICK_SUFFIXES = ("儿", "兒")
CROWDED = 3  # 只剩一个字的 core 撞在一起、或者昵称能对上的全名超过这么多个：多半是同姓不同人，不出提示
PRONOUNS = frozenset({
    "我", "你", "您", "他", "她", "它", "我们", "你们", "他们", "她们", "它们", "我們", "你們", "他們", "她們", "它們",
    "咱", "咱们", "咱們", "俺", "俺们", "俺們", "本人", "自己", "在下", "老子", "人家",
})

DRAFT, CONFIRMED, SINGLE = "draft", "confirmed", "single"
RECOMPUTED = (DRAFT, SINGLE)  # 只有这两种会被重算，其他状态一律当锁定原样保留

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


@dataclass
class Mention:
    type: str
    name: str
    scenes: list[str] = field(default_factory=list)
    contexts: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.scenes)


def _context(text: str, name: str) -> str:
    i = text.find(name)
    if i < 0:
        return ""
    return " ".join(text[max(0, i - CONTEXT_RADIUS) : i + len(name) + CONTEXT_RADIUS].split())


def collect_mentions(book: Book) -> dict[str, dict[str, Mention]]:
    scenes = {s.id: s for s in load_scenes(book, with_text=True) if not s.removed}
    out: dict[str, dict[str, Mention]] = {t: {} for t in TYPES}
    for sid, record in sorted(load_cards(book).items(), key=lambda kv: natural_key(kv[0])):
        scene = scenes.get(sid)
        if scene is None or not is_fresh(record, scene):
            continue
        card = record["card"]
        found = [("person", c["name"]) for c in card["characters"]]
        if card.get("pov"):
            found.append(("person", card["pov"]))
        found += [("location", n) for n in card["locations"]]
        found += [("organization", n) for n in card.get("organizations", [])]
        for typ, raw in found:
            name = raw.strip()
            if not name or name in PRONOUNS:
                continue
            m = out[typ].setdefault(name, Mention(typ, name))
            if sid in m.scenes:
                continue
            m.scenes.append(sid)
            if len(m.contexts) < CONTEXTS_PER_NAME:
                snippet = _context(scene.text, name)
                if snippet:
                    m.contexts.append(snippet)
    return out


def core(name: str) -> str:
    """去掉常见称谓前后缀。名字本身就是称谓（在 AFFIXES 里）时原样返回，不再被单字词缀拆开。"""
    while name not in AFFIXES:
        for a in AFFIXES:
            if len(name) > len(a) and name.startswith(a):
                name = name[len(a) :]
                break
            if len(name) > len(a) and name.endswith(a):
                name = name[: -len(a)]
                break
        else:
            break
    return name


def _nick_core(name: str) -> str:
    """去掉昵称词缀：阿X、小X、X儿。"""
    for p in NICK_PREFIXES:
        if len(name) > 1 and name.startswith(p):
            name = name[1:]
            break
    for s in NICK_SUFFIXES:
        if len(name) > 1 and name.endswith(s):
            name = name[:-1]
            break
    return name


def hint_pairs(names: list[str], limit: int | None = HINT_LIMIT) -> list[tuple[str, str, str]]:
    """字面上「看着像」的叫法对 (a, b, 原因)，只是给模型的参考。limit=None 不截断。

    按有用程度排：一个包含另一个 → 昵称对上全名的结尾 → 去掉称谓后相同；同一类里，
    names 里排得靠前（出现多）的名字优先。本身就是称谓的名字不当包含关系里较短的那个，
    只剩一个字的 core 撞在一起的名字太多时不两两出提示（黄夫人、黄兄、黄老爷多半是不同的人）。
    """
    pos = {n: i for i, n in enumerate(names)}

    def order(p: tuple[str, str, str]) -> tuple[int, int]:
        return min(pos[p[0]], pos[p[1]]), max(pos[p[0]], pos[p[1]])

    contain: list[tuple[str, str, str]] = []
    for b in names:
        subs = {b[i:j] for i in range(len(b)) for j in range(i + 2, len(b) + 1)} - {b}
        contain += [(a, b, "一个包含另一个") for a in subs if a in pos and a not in AFFIXES]

    # 昵称（清儿 / 阿清 / 小清）去掉昵称词缀后，恰好是某个不带称谓的全名（林清）的结尾
    full_by_suffix: dict[str, list[str]] = defaultdict(list)
    for b in names:
        if b not in AFFIXES and core(b) == b:
            for i in range(1, len(b)):
                full_by_suffix[b[i:]].append(b)
    nick: list[tuple[str, str, str]] = []
    for a in names:
        c = _nick_core(a)
        if c == a or a in AFFIXES:
            continue
        full = [b for b in full_by_suffix.get(c, []) if b != a]
        if len(full) <= CROWDED:
            nick += [(a, b, "去掉儿/阿/小后是另一个名字的结尾") for b in full]

    by_core: dict[str, list[str]] = defaultdict(list)
    for n in names:
        by_core[core(n)].append(n)
    same: list[tuple[str, str, str]] = []
    for c, group in by_core.items():
        if len(c) == 1 and len(group) > CROWDED:
            continue
        same += [(a, b, "去掉称谓后相同") for a, b in combinations(group, 2)]

    pairs: dict[frozenset, tuple[str, str, str]] = {}
    for p in sorted(contain, key=order) + sorted(nick, key=order) + sorted(same, key=order):
        pairs.setdefault(frozenset(p[:2]), p)
    out = list(pairs.values())
    return out if limit is None else out[:limit]


def _find(parent: dict[str, str], x: str) -> str:
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def chunk_names(names: list[str], max_names: int, anchors: int, pairs=()) -> list[list[str]]:
    """names 按出现次数从多到少排好传进来。不超过 max_names 就一批；超过时，前 anchors 个（锚点）
    放进每一批，其余的平均分成 ceil(其余个数 / 每批容量) 批。pairs（字面提示对）连起来的名字
    当一个整体装进同一批，整体本身比一批的容量还大才拆开。"""
    if anchors >= max_names:
        raise ValueError(f"每批最多 {max_names} 个叫法，锚点却要 {anchors} 个：锚点数必须小于每批上限")
    if len(names) <= max_names:
        return [names]
    head, rest = names[:anchors], names[anchors:]
    size = max_names - anchors
    count = math.ceil(len(rest) / size)
    target = math.ceil(len(rest) / count)
    pos = {n: i for i, n in enumerate(rest)}
    parent: dict[str, str] = {}
    for a, b, *_ in pairs:
        if a in pos and b in pos:
            parent[_find(parent, a)] = _find(parent, b)
    comps: dict[str, list[str]] = {}
    for n in rest:
        comps.setdefault(_find(parent, n), []).append(n)
    bins: list[list[str]] = []
    for comp in comps.values():
        for piece in (comp[i : i + size] for i in range(0, len(comp), size)):
            dest = next((b for b in bins if len(b) + len(piece) <= target), None)
            if dest is None and len(bins) >= count:
                dest = min((b for b in bins if len(b) + len(piece) <= size), key=len, default=None)
            if dest is None:
                dest = []
                bins.append(dest)
            dest.extend(piece)
    return [head + sorted(b, key=pos.__getitem__) for b in bins]


def check_groups(data: dict, allowed: set[str]) -> list[str]:
    groups = data.get("groups")
    if not isinstance(groups, list):
        return ["缺少 groups 列表"]
    problems: list[str] = []
    seen: dict[str, int] = {}
    for i, g in enumerate(groups):
        if not isinstance(g, dict) or not isinstance(g.get("members"), list):
            problems.append(f"第 {i + 1} 组格式不对")
            continue
        members = [m for m in g["members"] if isinstance(m, str)]
        unknown = [m for m in members if m not in allowed]
        if unknown:
            problems.append("这些名字不在给你的列表里：" + "、".join(unknown[:10]))
        if g.get("canonical") not in members:
            problems.append(f"「{g.get('canonical')}」这组的 canonical 必须是 members 里的一个")
        for m in members:
            if m in seen and seen[m] != i:
                problems.append(f"「{m}」同时出现在两个组里")
            seen[m] = i
    return problems[:20]


def clean_groups(data: dict, allowed: set[str]) -> list[dict]:
    out: list[dict] = []
    taken: set[str] = set()
    for g in data.get("groups") or []:
        if not isinstance(g, dict):
            continue
        members: list[str] = []
        for m in g.get("members") or []:
            if isinstance(m, str) and m in allowed and m not in taken and m not in members:
                members.append(m)
        if len(members) < 2:
            continue
        taken.update(members)
        canonical = g.get("canonical") if g.get("canonical") in members else members[0]
        out.append({"canonical": canonical, "members": members, "reason": str(g.get("reason") or "")})
    return out


def merge_groups(
    batches: list[list[dict] | None], counts: dict[str, int], anchors=()
) -> tuple[list[dict], list[dict]]:
    """合并各批的组。batches 按批次顺序排，失败的批是 None。返回 (合并后的组, 冲突)。

    锚点每批都在，它们之间是不是同一个，以第一批（第一个有结果的批）的分组为准：后面某批的
    一个组如果碰到了第一批里分属不同组的锚点，就是冲突——这个组整个不参与合并（它的非锚点名字
    也不借它挂上去），记进冲突列表。其余的组按共同名字连起来。
    规范名取被提议次数最多的，平票比场景数，再比字面。
    """
    anchor_set = set(anchors)
    side = {a: a for a in anchor_set}  # 锚点 → 它在第一批里所在组的代表锚点
    for g in next((gs for gs in batches if gs is not None), []):
        rep = next((m for m in g["members"] if m in anchor_set), None)
        for m in g["members"]:
            if m in anchor_set:
                side[m] = rep
    accepted: list[dict] = []
    conflicts: list[dict] = []
    for i, gs in enumerate(batches, 1):
        for g in gs or []:
            if len({side[m] for m in g["members"] if m in anchor_set}) > 1:
                conflicts.append({"chunk": i, "names": list(g["members"])})
            else:
                accepted.append(g)
    parent: dict[str, str] = {}
    for g in accepted:
        for m in g["members"][1:]:
            parent[_find(parent, m)] = _find(parent, g["members"][0])
    buckets: dict[str, list[dict]] = defaultdict(list)
    for g in accepted:
        buckets[_find(parent, g["members"][0])].append(g)
    out = []
    for gs in buckets.values():
        members = sorted({m for g in gs for m in g["members"]}, key=lambda n: (-counts.get(n, 0), n))
        votes = Counter(g["canonical"] for g in gs if g["canonical"] in members)
        canonical = min(votes, key=lambda n: (-votes[n], -counts.get(n, 0), n)) if votes else members[0]
        reason = "；".join(dict.fromkeys(g["reason"] for g in gs if g["reason"]))
        out.append({"canonical": canonical, "members": members, "reason": reason})
    return out, conflicts


def _name_lines(names: list[str], mentions: dict[str, Mention]) -> str:
    return "\n".join(
        f"- {n}（{mentions[n].count} 个场景）：" + (" ／ ".join(mentions[n].contexts) or "（无上下文）")
        for n in names
    )


def _hint_lines(pairs: list[tuple[str, str, str]]) -> str:
    return "\n".join(f"- {a} ↔ {b}（{why}）" for a, b, why in pairs) or "（无）"


@dataclass
class _Batch:
    typ: str
    no: int
    names: list[str]
    system: str
    user: str
    key: str  # 缓存键，见 _cache_key


def _cache_cfg(client: LLMClient) -> dict:
    """缓存键里的配置部分：综合档配置 + 接口地址。
    max_tokens 不算——截断由 chat_json 自动加大上限重试，改上限不改变结果，不该让付过钱的批作废；
    接口地址要算——换了服务商（比如都叫 deepseek-flash 的中转站），模型名一样也不是同一个模型。
    API key 不进缓存键。"""
    return cache_config(client, "synth")


def _cache_key(system: str, user: str, synth_cfg: dict) -> str:
    """提示词全文 + _cache_cfg 给的配置（模型、思考开关/强度、接口地址等）的 sha256。"""
    return cache_key(system, user, synth_cfg)


def _plan_type(typ: str, mentions: dict[str, Mention], synth_cfg: dict) -> tuple[list[str], list[_Batch]]:
    """一个类型要发给模型的各批。返回 (锚点, 各批)；只有一批时没有锚点。"""
    names = sorted(mentions, key=lambda n: (-mentions[n].count, n))
    chunks = chunk_names(names, MAX_NAMES_PER_CALL, ANCHOR_NAMES, hint_pairs(names, limit=None))
    anchors = names[:ANCHOR_NAMES] if len(chunks) > 1 else []
    batches = []
    for no, chunk in enumerate(chunks, 1):
        system, user = render(
            "entities",
            type_label=TYPE_LABELS[typ],
            names=_name_lines(chunk, mentions),
            hints=_hint_lines(hint_pairs(chunk)),
        )
        batches.append(_Batch(typ, no, chunk, system, user, _cache_key(system, user, synth_cfg)))
    return anchors, batches


def _load_cache(book: Book) -> dict[str, dict]:
    """缓存坏了就当没有：大不了重新调一遍模型。条目里 groups/problems 形状不对的也丢掉。"""
    try:
        data = read_json(book.entities_cache_path, {})
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        k: v
        for k, v in data.items()
        if isinstance(v, dict) and isinstance(v.get("groups"), list) and isinstance(v.get("problems"), list)
    }


def _scenes_of(names: list[str], mentions: dict[str, Mention]) -> list[str]:
    return sorted({s for n in names if n in mentions for s in mentions[n].scenes}, key=natural_key)


def _order_names(names: list[str], mentions: dict[str, Mention]) -> list[str]:
    """出现的场景多的在前，平票按字面。"""
    return sorted(names, key=lambda n: (-(mentions[n].count if n in mentions else 0), n))


def _entity(num: int, typ: str, canonical: str, names: list[str], status: str, reason: str,
            mentions: dict[str, Mention]) -> dict:
    return {
        "id": f"E-{num:04d}",
        "type": typ,
        "canonical": canonical,
        "names": _order_names(names, mentions),
        "status": status,
        "reason": reason,
        "scenes": _scenes_of(names, mentions),
    }


_ID = re.compile(r"E-(\d+)")


def _id_num(eid) -> int:
    m = _ID.fullmatch(eid) if isinstance(eid, str) else None
    return int(m.group(1)) if m else 0


def _next_id(data: dict) -> int:
    """下一个可用编号：取文件顶层 next_id；缺失或不是 int 时按现有最大编号 + 1 兜底。"""
    top = max((_id_num(e.get("id")) for e in data["entities"]), default=0)
    n = data.get("next_id")
    if not isinstance(n, int):
        n = 0
    return max(n, top + 1)


def _locked_names(data: dict) -> set[tuple[str, str]]:
    return {(e["type"], n) for e in data["entities"] if e.get("status") not in RECOMPUTED for n in e["names"]}


def _signature(data: dict) -> list:
    return sorted(
        (e["type"], e["canonical"], tuple(sorted(e["names"])), str(e.get("status"))) for e in data["entities"]
    )


def _assemble(old: dict, mentions: dict[str, dict[str, Mention]], groups: dict[str, list[dict]]) -> dict:
    """用刚读到的 实体.json 和模型的分组拼出新结果。锁定的实体原样保留（只刷新场景）；
    其余名字组成草稿组或 single。和旧文件里同类型、名字集合完全相同的草稿/single 沿用原编号，
    新的从只增不减的 next_id 取。"""
    kept = [e for e in old["entities"] if e.get("status") not in RECOMPUTED]
    locked = _locked_names(old)
    reuse = {
        (e["type"], frozenset(e["names"])): _id_num(e.get("id"))
        for e in old["entities"]
        if e.get("status") in RECOMPUTED and _id_num(e.get("id"))
    }
    next_id = _next_id(old)
    entities = [{**e, "scenes": _scenes_of(e["names"], mentions.get(e["type"], {}))} for e in kept]

    def number(typ: str, names: list[str]) -> int:
        nonlocal next_id
        num = reuse.pop((typ, frozenset(names)), None)
        if num is None:
            num, next_id = next_id, next_id + 1
        return num

    for typ in TYPES:
        ms = mentions[typ]
        free = {n for n in ms if (typ, n) not in locked}
        grouped: set[str] = set()
        for g in groups.get(typ, []):
            members = [n for n in g["members"] if n in free]
            if len(members) < 2:
                continue
            canonical = g["canonical"] if g["canonical"] in members else members[0]
            entities.append(_entity(number(typ, members), typ, canonical, members, DRAFT, g["reason"], ms))
            grouped.update(members)
        for n in sorted(free - grouped, key=lambda n: (-ms[n].count, n)):
            entities.append(_entity(number(typ, [n]), typ, n, [n], SINGLE, "", ms))
    return {"next_id": next_id, "entities": entities}


def run_entities(book: Book, client: LLMClient, progress: Progress = _noop) -> dict:
    return asyncio.run(_run_entities(book, client, progress))


async def _run_entities(book: Book, client: LLMClient, progress: Progress) -> dict:
    mentions = collect_mentions(book)
    synth_cfg = _cache_cfg(client)
    # 这里读 实体.json 只为决定哪些类型不用调模型；拼结果时等模型全部调完再重新读。
    locked_now = _locked_names(read_json(book.entities_path, {"entities": []}))
    plans: dict[str, tuple[list[str], list[_Batch]]] = {}
    for typ in TYPES:
        free = [n for n in mentions[typ] if (typ, n) not in locked_now]
        if len(free) >= 2:
            plans[typ] = _plan_type(typ, mentions[typ], synth_cfg)
    batches = [b for _, bs in plans.values() for b in bs]

    cache = _load_cache(book)
    used: set[str] = set()
    results: dict[tuple[str, int], list[dict]] = {}
    failed: list[dict] = []
    unresolved: list[dict] = []
    done = 0
    progress(0, len(batches))

    async def one(b: _Batch) -> None:
        nonlocal done
        allowed = set(b.names)
        entry = cache.get(b.key)
        if entry is None:
            try:
                data, problems = await client.chat_json(
                    "synth", b.system, b.user, lambda d: check_groups(d, allowed), tag=f"entities/{b.typ}-{b.no}"
                )
            except FatalLLMError:
                raise
            except LLMError as e:  # 这一批不贡献分组，整步不失败
                failed.append({"type": b.typ, "chunk": b.no, "error": str(e)})
            else:
                entry = cache[b.key] = {"groups": clean_groups(data, allowed), "problems": problems}
                try:
                    write_json(book.entities_cache_path, cache)
                except OSError:
                    pass  # 缓存写失败不该让已经花了钱的这次调用也跟着失败
        if entry is not None:
            used.add(b.key)
            results[(b.typ, b.no)] = clean_groups(entry, allowed)
            if entry.get("problems"):
                unresolved.append({"type": b.typ, "chunk": b.no, "problems": list(entry["problems"])[:5]})
        done += 1
        progress(done, len(batches))  # 暂停检查点：已经做完的批都在缓存里

    try:
        async with asyncio.TaskGroup() as tg:
            for b in batches:
                tg.create_task(one(b))
    except BaseExceptionGroup as eg:
        # 欠费/key 失效（FatalLLMError）要让作者看到，不能被「已暂停」（JobCancelled）盖住
        raise pick_error(eg) from None
    finally:
        u = client.usage
        book.add_usage("entities", u.calls, u.prompt_tokens, u.completion_tokens, u.cost(client.cfg))

    groups: dict[str, list[dict]] = {}
    conflicts: list[dict] = []
    for typ, (anchors, bs) in plans.items():
        counts = {n: m.count for n, m in mentions[typ].items()}
        groups[typ], conf = merge_groups([results.get((typ, b.no)) for b in bs], counts, anchors)
        conflicts += [{"type": typ, **c} for c in conf]

    # 只把「读旧文件 → 拼结果 → 写回」放进锁里，都是毫秒级的纯本地操作；调模型在上面，绝不能进锁。
    with FILE_LOCK:
        old = read_json(book.entities_path, {"entities": []})
        data = _assemble(old, mentions, groups)
        changed = _signature(old) != _signature(data)
        write_json(book.entities_path, data)
    if set(cache) - used:  # 跑成功了，这次没用到的缓存条目清掉，免得越积越多
        try:
            write_json(book.entities_cache_path, {k: v for k, v in cache.items() if k in used})
        except OSError:
            pass

    def by_chunk(x: dict) -> tuple[int, int]:
        return TYPES.index(x["type"]), x["chunk"]

    ents = data["entities"]
    summary = {
        "names": sum(len(v) for v in mentions.values()),
        "entities": len(ents),
        "draft_groups": sum(e.get("status") == DRAFT for e in ents),
        "confirmed": sum(e.get("status") not in RECOMPUTED for e in ents),
        "chunks": len(batches),
        "failed_chunks": sorted(failed, key=by_chunk),
        "conflicts": conflicts,
        "unresolved": sorted(unresolved, key=by_chunk),
        "calls": client.usage.calls,
        "cost_usd": round(client.usage.cost(client.cfg), 4),
    }
    book.set_step("entities", "done", summary, changed=changed)
    return summary


# --- 作者的确认 / 改名 / 合并 / 拆分 ---


def load_entities(book: Book) -> dict:
    data = read_json(book.entities_path)
    if data is None:
        raise FileNotFoundError("还没有实体合并的结果，先跑步骤 5")
    return data


def _cmap(data: dict) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for e in data["entities"]:
        try:
            for n in e["names"]:
                out[(e["type"], n)] = e["canonical"]
        except KeyError as exc:
            # 条目缺字段（比如手改坏了 实体.json，少了 canonical/type/names）：带上是
            # 哪个实体 id，好让 API 层报出来的 500 里能看出具体哪一条坏了，不是笼统的
            # 一个字段名。id 本身也可能没有，退到 "?"。
            raise KeyError(f"{e.get('id', '?')} 缺字段 {exc}") from exc
    return out


def _save(book: Book, data: dict, before: dict[tuple[str, str], str]) -> None:
    """写回 实体.json。规范名映射（_cmap，即给下游用的 canonical_map）真的变了才让下游过期：
    单纯确认、改成同一个名字都不改映射，作者一条条确认几百个组时归线不该被反复标过期。
    要在 FILE_LOCK 里调。"""
    write_json(book.entities_path, data)
    if _cmap(data) != before:
        book.mark_downstream_outdated("entities")


class NoSuchEntity(KeyError):
    """给的实体编号在文件里找不到。

    继承 KeyError 是为了兼容既有调用方（比如 tests/test_entities.py 里
    `pytest.raises(KeyError)` 那种写法）——不用改，照样能接住；API 层想把
    「真的没有这个实体」（该 404）和「条目本身缺字段」（该 500，见 _cmap）分开时，
    再单独 except 这个更具体的类型。
    """


def _get(data: dict, eid: str) -> dict:
    for e in data["entities"]:
        if e["id"] == eid:
            return e
    raise NoSuchEntity(eid)


# 下面四个操作：读 实体.json → 改 → 写回 整段在 FILE_LOCK 里，跟步骤 5 的写回、跟彼此都串行，
# 不会拿旧数据把别人的改动整个覆盖掉。要读全部场景卡的 collect_mentions 不碰 实体.json，放在锁外先算好。


def confirm(book: Book, ids: list[str]) -> list[dict]:
    """标成已确认。重复的 id 只算一次；没有任何状态变化（比如 ids 为空、都已确认）就不写文件。"""
    ids = list(dict.fromkeys(ids))
    with FILE_LOCK:
        data = load_entities(book)
        before = _cmap(data)
        out = [_get(data, eid) for eid in ids]  # 有找不到的 id 就在改动前抛 KeyError
        if any(e.get("status") != CONFIRMED for e in out):
            for e in out:
                e["status"] = CONFIRMED
            _save(book, data, before)
    return out


def rename(book: Book, eid: str, canonical: str) -> dict:
    canonical = canonical.strip()
    if not canonical:
        raise ValueError("规范名不能为空")
    with FILE_LOCK:
        data = load_entities(book)
        before = _cmap(data)
        e = _get(data, eid)
        e["canonical"], e["status"] = canonical, CONFIRMED
        _save(book, data, before)
    return e


def merge(book: Book, ids: list[str], canonical: str | None = None) -> dict:
    """合并成第一个实体。名字按出现次数排，场景按当前场景卡重算（跟拆分一样）。"""
    if len(set(ids)) < 2:
        raise ValueError("至少要选两个实体才能合并")
    if canonical is not None:
        canonical = canonical.strip()
        if not canonical:
            raise ValueError("规范名不能为空")
    mentions = collect_mentions(book)
    with FILE_LOCK:
        data = load_entities(book)
        before = _cmap(data)
        ents = [_get(data, eid) for eid in dict.fromkeys(ids)]
        if len({e["type"] for e in ents}) > 1:
            raise ValueError("不同类型的实体不能合并")
        keep = ents[0]
        ms = mentions.get(keep["type"], {})
        names = list(dict.fromkeys(n for e in ents for n in e["names"]))
        keep.update(
            names=_order_names(names, ms),
            scenes=_scenes_of(names, ms),
            canonical=canonical or keep["canonical"],
            status=CONFIRMED,
            reason="作者合并",
        )
        dropped = {e["id"] for e in ents[1:]}
        data["entities"] = [e for e in data["entities"] if e["id"] not in dropped]
        _save(book, data, before)
    return keep


def split(book: Book, eid: str, names: list[str]) -> dict:
    mentions = collect_mentions(book)
    with FILE_LOCK:
        data = load_entities(book)
        before = _cmap(data)
        e = _get(data, eid)
        wanted = set(names)
        moving = [n for n in e["names"] if n in wanted]
        if not moving or len(moving) != len(wanted):
            raise ValueError("要拆出去的叫法必须都在这个实体里")
        if len(moving) == len(e["names"]):
            raise ValueError("不能把全部叫法都拆出去")
        ms = mentions.get(e["type"], {})
        e["names"] = [n for n in e["names"] if n not in wanted]
        if e["canonical"] in wanted:
            e["canonical"] = e["names"][0]
        e["status"] = CONFIRMED
        e["scenes"] = _scenes_of(e["names"], ms)
        # 编号用文件顶层只增不减的 next_id 取号，不能只看当前实体列表里的最大号——否则合并删掉
        # 最大号的实体后，编号可能被重新发出去，跟已经删掉的旧实体撞号。
        num = _next_id(data)
        data["next_id"] = num + 1
        new = _entity(num, e["type"], moving[0], moving, CONFIRMED, "作者拆分", ms)
        data["entities"].append(new)
        _save(book, data, before)
    return new


def canonical_map(book: Book) -> dict[tuple[str, str], str]:
    return _cmap(load_entities(book))
