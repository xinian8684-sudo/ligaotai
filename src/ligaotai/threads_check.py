"""步骤 6 各次模型调用的输出检查（给 chat_json 的 check）、打分（给 chat_json 的 score）和收尾清理。

- 检查函数（check_*）只返回问题清单，空列表 = 合格。
- 打分函数（score_*）返回这次回复「坏了多少」，越小越好，chat_json 重试用尽时拿它在几次回复里挑最好的一次。
  问题清单是按类合并的（漏 1 块和漏 1000 块都是 1 条），不能拿条数比。打分的权重：
  - 清理后会丢掉的一个单位（块进「未分配」、偏移置空、交汇点 / 缺口被丢掉）记 LOST；
  - 清理能无损修好的一处（编造的编号、重复、放错字段、没名字、主线偏移不是 0 ……）记 FIX；
  - 线内排序里块没给时间、时间格式不对，也记 FIX（清理时这块的时间置空，块还在）；
  - 顶层列表整个没有，按「全部单位都丢了」再加一个 LOST 算；找缺口不知道原本有几个，记 NO_LIST。
  每条问题至少记 1 分，所以「分数是 0」和「没有问题」是一回事。
- 清理函数（clean_*）把输出修成能用的样子：编造的编号丢掉，重复的只留第一次出现的，
  漏掉的交给调用方记进「未分配」。

三种函数对任何形状的模型输出都不抛异常：编号、字段写成列表、对象、数字、true、null，
顶层列表写成数字或字符串，都当成格式不对处理（先写进缓存再清理，清理抛异常会把坏结果钉死在缓存里）。
编号先规范化（NFKC、转大写、去掉字母或 # 跟数字之间的空白 /「-」/「_」、每段数字各自去前导 0）再比对：
「s-0001」「Ｓ－０００１」「 S-0001 」「S-1」「W-1」都认成对应的真编号（S-0001、W-01）；
数字跟数字之间的分隔符不去，「S-0001-3」不会被拼成 S-0013。
"""

from __future__ import annotations

import math
import re
import unicodedata

from .fsutil import natural_key

MAX_LISTED = 20
CONFS = ("高", "中", "低")
UNNAMED_WORLD = "未命名世界"
UNNAMED_THREAD = "未命名支线"

LOST = 2
FIX = 1
NO_LIST = 1_000_000


def str_list(v) -> list[str]:
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def text(v) -> str:
    return str(v).strip() if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def norm(v) -> str:
    """编号的规范写法：NFKC（全角转半角）、去首尾空白、转大写。不是字符串 / 数字就是空串。"""
    return unicodedata.normalize("NFKC", text(v)).strip().upper()


_DIGITS = re.compile(r"[0-9]+")
_SEP = re.compile(r"(?<=[A-Z#])[\s_-]+(?=[0-9])")  # 字母或 # 跟数字之间的分隔符


def _id_key(v) -> str:
    """比对用的键：规范写法去掉「字母或 # 跟数字之间」的空白、「-」「_」，每段数字各自去掉前导 0。
    「W-1」「W01」「w-01」「Ｗ－０１」都跟 W-01 是同一个键；真编号的位数是固定的，不会撞。
    数字跟数字之间的分隔符留着：「S-0001-3」的键是 S1-3，对不上 S-0013，按编造报给模型。"""
    s = _SEP.sub("", norm(v))
    return _DIGITS.sub(lambda m: m.group().lstrip("0") or "0", s)  # 不用 int()：超长数字串会抛 ValueError


def _name_key(v) -> str:
    return unicodedata.normalize("NFKC", text(v)).strip().casefold()


def _obj(v) -> dict:
    return v if isinstance(v, dict) else {}


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _uniq(xs: list[str]) -> list[str]:
    return list(dict.fromkeys(xs))


def _listing(ids: list[str]) -> str:
    shown = "、".join(ids[:MAX_LISTED])
    if len(ids) > MAX_LISTED:
        shown += f"（共 {len(ids)} 个，这里只列了前 {MAX_LISTED} 个）"
    return shown


class _Ids:
    """把模型写的编号对回真编号：规范化后能对上的换成真编号，对不上的原样（去首尾空白）留着。"""

    def __init__(self, *pools):
        self.table: dict[str, str] = {}
        for pool in pools:
            for x in pool:
                if isinstance(x, str):
                    self.table.setdefault(_id_key(x), x)

    def one(self, v) -> str:
        """单个编号；不是字符串 / 数字、或者是空串时返回空串。"""
        s = text(v)
        return self.table.get(_id_key(s), s) if s else ""

    def many(self, v) -> list[str]:
        """编号列表：只认列表里的字符串，空串跳过。"""
        return [y for y in (self.one(x) for x in str_list(v)) if y]


def _id_field(v, ids: _Ids) -> tuple[str, bool]:
    """编号字段 → (对回真编号后的编号, 格式是不是不对)。null / 空串 → ("", False)；
    列表、对象、true / false → ("", True)。"""
    if v is None:
        return "", False
    s = ids.one(v)
    return (s, False) if s else ("", not isinstance(v, str))


def _names(known, names) -> dict[str, tuple[str, str]]:
    """已有的世界 / 线：规范化后的名字 → (键, 名字)。只认 known 里有的键。"""
    out: dict[str, tuple[str, str]] = {}
    if isinstance(names, dict):
        for k in sorted((k for k in known if isinstance(k, str)), key=natural_key):
            n = text(names.get(k))
            if n:
                out.setdefault(_name_key(n), (k, n))
    return out


class _Report:
    def __init__(self) -> None:
        self.problems: list[str] = []
        self.bad = 0

    def add(self, msg: str, weight: int) -> None:
        self.problems.append(msg)
        self.bad += max(1, weight)


def _coverage(r: _Report, listed: list[str], expected, what: str, missing_weight: int = LOST) -> None:
    unknown = [x for x in dict.fromkeys(listed) if x not in expected]
    seen: set[str] = set()
    dup: list[str] = []
    extra = 0
    for x in listed:
        if x in seen:
            extra += 1
            if x not in dup:
                dup.append(x)
        seen.add(x)
    missing = sorted(set(expected) - seen, key=natural_key)
    if unknown:
        r.add(f"这些编号不在给你的{what}里，不要编造：" + _listing(unknown), FIX * len(unknown))
    if dup:
        r.add("这些编号出现了不止一次，每个只能放一处：" + _listing(dup), FIX * extra)
    if missing:
        r.add(f"这些{what}漏掉了，每个都要放进去：" + _listing(missing), missing_weight * len(missing))


def coverage_problems(listed: list[str], expected: set[str], what: str = "场景") -> list[str]:
    r = _Report()
    _coverage(r, listed, expected, what)
    return r.problems


# --- 6.1 划世界 ---


def _worlds(data, expected: set[str], known: set[str], need_unit: bool, names) -> _Report:
    r = _Report()
    data = _obj(data)
    if need_unit and not text(data.get("time_unit")):
        r.add("缺少 time_unit（全书统一的故事时间单位，比如「年」）", FIX)
    worlds = data.get("worlds")
    if not isinstance(worlds, list):
        r.add("缺少 worlds 列表", LOST * len(expected) + LOST)
        return r
    blocks, wids = _Ids(expected), _Ids(known)
    known_names = _names(known, names)
    new_names: dict[str, int] = {}
    listed: list[str] = []
    for i, w in enumerate(worlds, 1):
        if not isinstance(w, dict):
            r.add(f"第 {i} 个世界格式不对", FIX)
            continue
        wid, bad = _id_field(w.get("id"), wids)
        name = text(w.get("name"))
        if bad:
            r.add(f"第 {i} 个世界的 id 要写成字符串（比如「W-01」）；新世界不要写 id", FIX)
        elif wid and wid not in known:
            r.add(f"第 {i} 个世界的 id「{wid}」不是已有的世界；新世界不要写 id", FIX)
        elif not wid and not name:
            r.add(f"第 {i} 个世界没有 name", FIX)
        elif not wid:
            k = _name_key(name)
            if k in known_names:
                key, shown = known_names[k]
                r.add(f"第 {i} 个世界跟已有的世界「{shown}」同名；属于它就写 id「{key}」，不属于就换个名字", FIX)
            elif k in new_names:
                r.add(f"第 {i} 个世界跟第 {new_names[k]} 个世界同名；同一个世界的块要写在一起，不是同一个就换个名字", FIX)
            else:
                new_names[k] = i
        listed += blocks.many(w.get("scenes"))
    _coverage(r, listed, expected, "场景")
    return r


def check_worlds(data: dict, expected: set[str], known: set[str], need_unit: bool,
                 names: dict[str, str] | None = None) -> list[str]:
    """names：已有世界的键 → 名字（可选）。传了就查「新世界跟已有世界同名」。"""
    return _worlds(data, expected, known, need_unit, names).problems


def score_worlds(data: dict, expected: set[str], known: set[str], need_unit: bool,
                 names: dict[str, str] | None = None) -> int:
    return _worlds(data, expected, known, need_unit, names).bad


def clean_worlds(data: dict, expected: set[str], known: set[str],
                 names: dict[str, str] | None = None) -> tuple[list[dict], list[str], str]:
    """返回 (世界列表, 漏掉的场景, 时间单位)。世界：{"key", "name", "reason", "scenes"}；
    key 是已有世界的键，新世界是 None（调用方再编号）。
    新世界跟已有世界同名（传了 names 时）就归进那个世界；几个新世界同名就合成一个。"""
    data = _obj(data)
    blocks, wids = _Ids(expected), _Ids(known)
    known_names = _names(known, names)
    taken: set[str] = set()
    out: list[dict] = []
    by_key: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for w in _list(data.get("worlds")):
        if not isinstance(w, dict):
            continue
        wid, _ = _id_field(w.get("id"), wids)
        key = wid if wid in known else None
        name = text(w.get("name")) if key is None else ""
        if key is None and name and _name_key(name) in known_names:
            key, name = known_names[_name_key(name)][0], ""
        scenes = []
        for s in blocks.many(w.get("scenes")):
            if s in expected and s not in taken:
                taken.add(s)
                scenes.append(s)
        same = by_key.get(key) if key is not None else by_name.get(_name_key(name)) if name else None
        if same is not None:
            same["scenes"] += scenes
            continue
        if key is None and not scenes:
            continue
        entry = {"key": key, "name": name or ("" if key else UNNAMED_WORLD), "reason": text(w.get("reason")), "scenes": scenes}
        out.append(entry)
        if key is not None:
            by_key[key] = entry
        elif name:
            by_name[_name_key(name)] = entry
    missing = [s for s in sorted(expected, key=natural_key) if s not in taken]
    return out, missing, text(data.get("time_unit"))


# --- 6.2 划支线 ---


def _lines(data, ordered: set[str], outlines: set[str], known: set[str], names, held, require_main: bool = True) -> _Report:
    r = _Report()
    data = _obj(data)
    threads = data.get("threads")
    if not isinstance(threads, list):
        r.add("缺少 threads 列表", LOST * len(ordered) + FIX * len(outlines) + LOST)
        return r
    held = held if isinstance(held, dict) else {}
    blocks, tids = _Ids(ordered, outlines, held), _Ids(known)
    known_names = _names(known, names)
    new_names: dict[str, int] = {}
    o_list: list[str] = []  # 列到的正文 / 碎片块（放错字段的也算列到了，另外报放错）
    l_list: list[str] = []  # 列到的提纲块
    to_scenes: list[str] = []  # 正文 / 碎片放进了 outlines（清理能救回同一条线的 scenes）
    to_outlines: list[str] = []  # 提纲放进了 scenes（清理能救回同一条线的 outlines）
    in_world: list[str] = []  # 正文 / 碎片放进了 world_outlines（救不回，进未分配）
    relisted: list[str] = []  # 已有线里的块又写了一遍

    def sort_in(ids: list[str], where: str) -> None:
        for s in ids:
            if s in ordered:
                o_list.append(s)
                if where == "outlines":
                    to_scenes.append(s)
                elif where == "world":
                    in_world.append(s)
            elif s in outlines:
                l_list.append(s)
                if where == "scenes":
                    to_outlines.append(s)
            elif s in held:
                relisted.append(s)
            elif where == "scenes":
                o_list.append(s)
            else:
                l_list.append(s)

    mains = 0
    for i, t in enumerate(threads, 1):
        if not isinstance(t, dict):
            r.add(f"第 {i} 条线格式不对", FIX)
            continue
        tid, bad = _id_field(t.get("id"), tids)
        name = text(t.get("name"))
        name_known = bool(name) and _name_key(name) in known_names
        if bad:
            r.add(f"第 {i} 条线的 id 要写成字符串（比如「L-003」）；新线不要写 id", FIX)
        elif tid and tid not in known:
            r.add(f"第 {i} 条线的 id「{tid}」不是已有的线；新线不要写 id", FIX)
        elif not tid and not name:
            r.add(f"第 {i} 条线没有 name", FIX)
        elif not tid and name_known:
            key, shown = known_names[_name_key(name)]
            r.add(f"第 {i} 条线跟已有的线「{shown}」同名；属于它就写 id「{key}」，不属于就换个名字", FIX)
        elif not tid:
            k = _name_key(name)
            if k in new_names:
                r.add(f"第 {i} 条线跟第 {new_names[k]} 条线同名；同一条线的块要写在一起，不是同一条就换个名字", FIX)
            else:
                new_names[k] = i
        main = t.get("main") is True
        mains += main
        sc, ol = blocks.many(t.get("scenes")), blocks.many(t.get("outlines"))
        sort_in(sc, "scenes")
        sort_in(ol, "outlines")
        is_new = tid not in known and not name_known
        if is_new and not any(s in ordered for s in sc + ol):
            r.add(
                f"第 {i} 条线是新线，却没有正文/碎片块" + ("，main 不能标在它上面" if main else "")
                + "；只有提纲的话，提纲放进它讲的那条线的 outlines，或者 world_outlines",
                FIX,
            )
    sort_in(blocks.many(data.get("world_outlines")), "world")
    if threads and require_main and mains != 1:
        r.add(f"要恰好有一条线标 \"main\": true，现在有 {mains} 条", FIX)
    if to_scenes:
        ids = _uniq(to_scenes)
        r.add("这些块是正文/碎片，要放进线的 scenes，不要放 outlines：" + _listing(ids), FIX * len(ids))
    if to_outlines:
        ids = _uniq(to_outlines)
        r.add("这些块是提纲，要放进线的 outlines 或者 world_outlines，不要放 scenes：" + _listing(ids), FIX * len(ids))
    if in_world:
        ids = _uniq(in_world)
        r.add("这些块是正文/碎片，要放进某条线的 scenes，不能放 world_outlines：" + _listing(ids), LOST * len(ids))
    if relisted:
        ids = _uniq(relisted)
        shown = [f"{s}（{text(held[s])}）" if text(held[s]) else s for s in ids]
        r.add("这些块已经在已有的线里了，不用再列：" + _listing(shown), FIX * len(ids))
    _coverage(r, o_list, ordered, "正文/碎片块")
    _coverage(r, l_list, outlines, "提纲块", FIX)
    return r


def check_lines(data: dict, ordered: set[str], outlines: set[str], known: set[str],
                names: dict[str, str] | None = None, held: dict[str, str] | None = None,
                require_main: bool = True) -> list[str]:
    """ordered / outlines：这次要分的正文碎片块 / 提纲块；known：已有的线的键（已确认的线、前面几段新建的线）。
    names（可选）：已有的线的键 → 名字，传了就查「新线跟已有的线同名」。
    held（可选）：已经在已有的线里的块 → 那条线的键（提示词里当示例列出来的），模型又写一遍时
    提示「不用再列」，不说成编造。
    require_main：threads 不空时要不要恰好一条标 main。这个世界的主线已经定了时传 False：
    标几条 main 都不查（调用方不用这次的 main，清理也只留一条，重试只花钱）。"""
    return _lines(data, ordered, outlines, known, names, held, require_main).problems


def score_lines(data: dict, ordered: set[str], outlines: set[str], known: set[str],
                names: dict[str, str] | None = None, held: dict[str, str] | None = None,
                require_main: bool = True) -> int:
    return _lines(data, ordered, outlines, known, names, held, require_main).bad


def clean_lines(data: dict, ordered: set[str], outlines: set[str], known: set[str],
                names: dict[str, str] | None = None) -> dict:
    """返回 {"threads": [{"key", "name", "about", "main", "scenes", "outlines"}], "world_outlines", "missing"}。
    key 是已有线的键，新线是 None。
    - 正文放进了 outlines、提纲放进了 scenes：救回同一条线的正确字段。
    - 新线跟已有的线同名（传了 names 时）就当成那条线；几条新线同名就合成一条。
    - 没有正文 / 碎片块的新线丢掉，它的提纲改挂世界；main 落到没了的线上时，改给块最多的那条。"""
    data = _obj(data)
    blocks, tids = _Ids(ordered, outlines), _Ids(known)
    known_names = _names(known, names)
    taken: set[str] = set()

    def take(s: str, allowed: set[str]) -> bool:
        if s in allowed and s not in taken:
            taken.add(s)
            return True
        return False

    threads: list[dict] = []
    by_key: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    world_outlines: list[str] = []
    for t in _list(data.get("threads")):
        if not isinstance(t, dict):
            continue
        tid, _ = _id_field(t.get("id"), tids)
        key = tid if tid in known else None
        name = text(t.get("name")) if key is None else ""
        if key is None and name and _name_key(name) in known_names:
            key, name = known_names[_name_key(name)][0], ""
        scenes: list[str] = []
        outs: list[str] = []
        for s in blocks.many(t.get("scenes")):
            if take(s, ordered):
                scenes.append(s)
            elif take(s, outlines):
                outs.append(s)
        for s in blocks.many(t.get("outlines")):
            if take(s, outlines):
                outs.append(s)
            elif take(s, ordered):
                scenes.append(s)
        main = t.get("main") is True
        same = by_key.get(key) if key is not None else by_name.get(_name_key(name)) if name else None
        if same is not None:
            same["scenes"] += scenes
            same["outlines"] += outs
            same["main"] = same["main"] or main
            continue
        if key is None and not scenes:
            world_outlines += outs
            continue
        entry = {
            "key": key,
            "name": "" if key else (name or UNNAMED_THREAD),
            "about": "" if key else text(t.get("about")),
            "main": main,
            "scenes": scenes,
            "outlines": outs,
        }
        threads.append(entry)
        if key is not None:
            by_key[key] = entry
        elif name:
            by_name[_name_key(name)] = entry
    world_outlines += [s for s in blocks.many(data.get("world_outlines")) if take(s, outlines)]
    world_outlines += [s for s in sorted(outlines, key=natural_key) if s not in taken]
    missing = [s for s in sorted(ordered, key=natural_key) if s not in taken]
    first = next((t for t in threads if t["main"]), None)
    if first is None and threads:
        first = max(threads, key=lambda t: len(t["scenes"]))  # max 平票取第一个
    for t in threads:
        t["main"] = t is first
    return {"threads": threads, "world_outlines": world_outlines, "missing": missing}


# --- 6.3 线内排序 ---

END_STATES = ("完结", "待定")


def parse_time(v, strict: bool = False) -> dict | None:
    """[数值或 null, 把握] 或 {"t", "conf"} → {"t", "conf"}；格式不对返回 None。
    数值可以是数字字符串；字典写法必须有 "t" 键。把握去掉首尾空白后不认识时：strict 返回 None
    （检查时让模型改），否则当「低」（清理时用）。"""
    if isinstance(v, dict):
        if "t" not in v:
            return None
        v = [v.get("t"), v.get("conf")]
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return None
    t, conf = v
    if t is not None:
        if isinstance(t, bool) or not isinstance(t, (int, float, str)):
            return None
        try:
            f = float(t)
        except (ValueError, OverflowError, TypeError):
            return None
        if not math.isfinite(f):
            return None
        if not isinstance(t, int):
            t = f
    conf = text(conf)
    if conf not in CONFS:
        if strict:
            return None
        conf = "低"
    return {"t": t, "conf": conf}


def expand_order(order, segs: dict[str, list[str]], expected=()) -> list[str]:
    """order 里的片段编号展开成它的块；编号先对回真编号（expected 给了就连单块编号一起对）。"""
    ids = _Ids(segs, expected)
    out: list[str] = []
    for x in str_list(order):
        k = ids.one(x)
        if k:
            out += segs.get(k, [k])
    return out


def _times(data: dict, ids: _Ids) -> dict:
    """times 的键对回真编号；同一块写了两次留第一次。"""
    out: dict = {}
    for k, v in _obj(data.get("times")).items():
        out.setdefault(ids.one(k), v)
    return out


def _order(data, segs: dict[str, list[str]], expected: set[str]) -> _Report:
    r = _Report()
    data = _obj(data)
    if not isinstance(data.get("order"), list):
        r.add("缺少 order 列表", LOST * len(expected) + LOST)
        return r
    ids = _Ids(segs, expected)
    _coverage(r, expand_order(data["order"], segs, expected), expected, "场景（或片段里的场景）")
    times = _times(data, ids)
    no_time, bad_time, bad_conf = [], [], []
    for s in sorted(expected, key=natural_key):
        if s not in times:
            no_time.append(s)
        elif parse_time(times[s]) is None:
            bad_time.append(s)
        elif parse_time(times[s], strict=True) is None:
            bad_conf.append(s)
    if no_time:
        r.add("这些块没有给故事时间：" + _listing(no_time), FIX * len(no_time))
    if bad_time:
        r.add("这些块的时间格式不对，要写成 [数值或 null, \"高/中/低\"]：" + _listing(bad_time), FIX * len(bad_time))
    if bad_conf:
        r.add("这些块的把握只能写「高」「中」「低」：" + _listing(bad_conf), FIX * len(bad_conf))
    end = data.get("end")
    if not isinstance(end, dict) or text(end.get("state")) not in END_STATES:
        r.add("end.state 只能是「完结」或「待定」", FIX)
    return r


def check_order(data: dict, segs: dict[str, list[str]], expected: set[str]) -> list[str]:
    return _order(data, segs, expected).problems


def score_order(data: dict, segs: dict[str, list[str]], expected: set[str]) -> int:
    return _order(data, segs, expected).bad


def clean_order(data: dict, segs: dict[str, list[str]], expected: set[str], fallback: list[str]) -> dict:
    """返回 {"scenes", "times", "end", "missing", "failed"}；missing 按 fallback 的顺序。
    failed 为真：order 不是列表，或者展开后一块都没对上——这次回复没法用。这时 scenes 按 fallback
    （原稿位置）排，没有时间，结局「待定」，missing 为空；调用方照「调用失败」处理（order_failed）。"""
    data = _obj(data)
    ids = _Ids(segs, expected)
    base = [s for s in dict.fromkeys(fallback) if s in expected]
    base += sorted(set(expected) - set(base), key=natural_key)  # fallback 没列到的块也不能丢
    order = data.get("order")
    scenes: list[str] = []
    got: set[str] = set()
    if isinstance(order, list):
        for s in expand_order(order, segs, expected):
            if s in expected and s not in got:
                got.add(s)
                scenes.append(s)
    if expected and not scenes:
        return {"scenes": base, "times": {}, "end": {"state": "待定", "note": ""}, "missing": [], "failed": True}
    raw = _times(data, ids)
    times = {}
    for s in scenes:
        t = parse_time(raw[s]) if s in raw else None
        if t is not None:
            times[s] = t
    end = _obj(data.get("end"))
    state = text(end.get("state"))
    return {
        "scenes": scenes,
        "times": times,
        "end": {"state": state if state in END_STATES else "待定", "note": text(end.get("note"))},
        "missing": [s for s in base if s not in got],
        "failed": False,
    }


# --- 6.4 跨线对齐 ---


def _offset(v) -> tuple[bool, float | None]:
    """(格式对不对, 值)。null 是合法的「对不上」。值一律转成 float：整数偏移平移时 int 减 int 可能超出
    float 的范围，isfinite 会抛 OverflowError；float 相减溢出只得到 inf，清理时置 null。"""
    if v is None:
        return True, None
    t = parse_time([v, "低"])
    if t is None or t["t"] is None:
        return False, None
    return True, float(t["t"])  # parse_time 已经确认 float(t) 有限，这里不会溢出


def _cross(c, tids: _Ids, bids: _Ids, main: str, members: dict) -> tuple[tuple[str, str, str] | None, str, bool]:
    """交汇点 → ((thread, scene, main_scene) 或 None, 问题说明, 清理能不能修好)。
    scene 和 main_scene 写反了（scene 在主线里、main_scene 在支线里）清理时换回来。"""
    if not isinstance(c, dict):
        return None, "格式不对", False
    th = tids.one(c.get("thread"))
    if th not in members or th == main:
        return None, f"thread 要写主线以外的线的编号（现在是「{th}」）", False
    mine, theirs = members[th], members.get(main, ())
    sc, ms = bids.one(c.get("scene")), bids.one(c.get("main_scene"))
    if sc in mine and ms in theirs:
        return (th, sc, ms), "", True
    if sc in theirs and ms in mine:
        return (th, ms, sc), f"scene 和 main_scene 写反了：scene 写 {th} 里的块，main_scene 写主线 {main} 里的块", True
    wrong = []
    if sc not in mine:
        wrong.append(f"scene「{sc}」不在 {th} 里")
    if ms not in theirs:
        wrong.append(f"main_scene「{ms}」不在主线 {main} 里")
    return None, "，".join(wrong), False


def _align(data, thread_ids: set[str], main: str, members: dict) -> _Report:
    r = _Report()
    data = _obj(data)
    threads = data.get("threads")
    if not isinstance(threads, list):
        r.add("缺少 threads 列表", LOST * len(thread_ids) + LOST)
        return r
    tids, bids = _Ids(thread_ids), _Ids(*members.values())
    listed: list[str] = []
    bad_off: list[str] = []
    first: dict[str, float | None] = {}
    for i, t in enumerate(threads, 1):
        if not isinstance(t, dict):
            r.add(f"第 {i} 条线格式不对", FIX)
            continue
        tid = tids.one(t.get("id"))
        if tid:
            listed.append(tid)
        ok, v = _offset(t.get("offset"))
        if not ok:
            bad_off.append(tid or f"第 {i} 条")
        elif tid in thread_ids:
            first.setdefault(tid, v)
    _coverage(r, listed, thread_ids, "线")
    if bad_off:
        r.add("这些线的 offset 要写数字或 null：" + _listing(bad_off), LOST * len(bad_off))
    m0 = first.get(main)
    if m0 is not None and m0 != 0:
        r.add(f"主线 {main} 的 offset 要写 0，其他线相对主线写", FIX)
    crosses = data.get("intersections", [])
    if not isinstance(crosses, list):
        r.add("intersections 要是列表", LOST)
    else:
        for i, c in enumerate(crosses, 1):
            _, why, fixable = _cross(c, tids, bids, main, members)
            if why:
                r.add(f"第 {i} 个交汇点不对：{why}", FIX if fixable else LOST)
    return r


def check_align(data: dict, thread_ids: set[str], main: str, members: dict[str, set[str]]) -> list[str]:
    return _align(data, thread_ids, main, members).problems


def score_align(data: dict, thread_ids: set[str], main: str, members: dict[str, set[str]]) -> int:
    return _align(data, thread_ids, main, members).bad


def clean_align(
    data: dict, thread_ids: set[str], main: str, members: dict[str, set[str]]
) -> tuple[dict[str, float | None], list[dict]]:
    """返回 (每条线的偏移, 交汇点)。同一条线写了两次留第一次；主线写了非 0 的偏移时，
    其他线都减去它（保持相对关系），主线固定 0；交汇点 scene / main_scene 写反了换回来。"""
    data = _obj(data)
    tids, bids = _Ids(thread_ids), _Ids(*members.values())
    offsets: dict[str, float | None] = {t: None for t in thread_ids}
    seen: set[str] = set()
    for t in _list(data.get("threads")):
        if not isinstance(t, dict):
            continue
        tid = tids.one(t.get("id"))
        if tid not in thread_ids or tid in seen:
            continue
        seen.add(tid)
        ok, v = _offset(t.get("offset"))
        if ok:
            offsets[tid] = v
    m0 = offsets.get(main)
    if m0:
        shifted = {k: (None if v is None else v - m0) for k, v in offsets.items()}
        offsets = {k: (v if v is None or math.isfinite(v) else None) for k, v in shifted.items()}
    offsets[main] = 0
    cross: list[dict] = []
    keys: set[tuple] = set()
    for c in _list(data.get("intersections")):
        k, _, _ = _cross(c, tids, bids, main, members)
        if k is None or k in keys:
            continue
        keys.add(k)
        cross.append({"thread": k[0], "scene": k[1], "main_scene": k[2], "reason": text(c.get("reason"))})
    return offsets, cross


# --- 6.5 找缺口 ---


def _refs(v, rids: _Ids) -> list[str]:
    """mentioned_in：列表；单个字符串当成只有一项的列表。"""
    return rids.many([v] if isinstance(v, str) else v)


def _gap_place(g: dict, tids: _Ids, bids: _Ids, lines: dict) -> tuple[str | None, str | None, str | None, list[str]]:
    """(线, after, before, 问题说明)。线不对三个都是 None；after / before 不在线里的置 None，
    前后颠倒或相等时两个都置 None。"""
    why: list[str] = []
    tid, bad = _id_field(g.get("thread"), tids)
    if bad or (tid and tid not in lines):
        return None, None, None, [f"thread「{tid}」不是这个世界的线" if tid else "thread 要写线的编号或 null"]
    if not tid:
        return None, None, None, []
    order = list(lines[tid])
    pos: dict[str, int] = {}
    for k in ("after", "before"):
        b, bad_b = _id_field(g.get(k), bids)
        if bad_b or (b and b not in order):
            why.append(f"{k} 不在 {tid} 里")
        elif b:
            pos[k] = order.index(b)
    if len(pos) == 2 and pos["after"] >= pos["before"]:
        why.append(f"after 要写在 before 前面的块（{tid} 里的顺序）")
        pos = {}
    after = order[pos["after"]] if "after" in pos else None
    before = order[pos["before"]] if "before" in pos else None
    return tid, after, before, why


def _gaps(data, ref_scenes: set[str], lines: dict) -> _Report:
    r = _Report()
    data = _obj(data)
    gaps = data.get("gaps")
    if not isinstance(gaps, list):
        r.add("缺少 gaps 列表", NO_LIST)
        return r
    rids, tids, bids = _Ids(ref_scenes), _Ids(lines), _Ids(*lines.values())
    seen: dict[tuple, int] = {}
    for i, g in enumerate(gaps, 1):
        if not isinstance(g, dict):
            r.add(f"第 {i} 个缺口格式不对", LOST)
            continue
        event = text(g.get("event"))
        if not event:
            r.add(f"第 {i} 个缺口没有 event", LOST)
        refs = _refs(g.get("mentioned_in"), rids)
        good = [s for s in refs if s in ref_scenes]
        if not good or len(good) < len(refs):
            r.add(f"第 {i} 个缺口的 mentioned_in 只能用列出的出处编号，而且不能空", FIX if good else LOST)
        tid, _, _, why = _gap_place(g, tids, bids, lines)
        for w in why:
            r.add(f"第 {i} 个缺口的 {w}", FIX)
        if event and good:
            k = (_name_key(event), tid)
            if k in seen:
                r.add(f"第 {i} 个缺口跟第 {seen[k]} 个是同一件事，要合成一个，mentioned_in 写在一起", FIX)
            else:
                seen[k] = i
    return r


def check_gaps(data: dict, ref_scenes: set[str], lines: dict[str, list[str]]) -> list[str]:
    """lines：这个世界的线 → 按顺序排好的块。"""
    return _gaps(data, ref_scenes, lines).problems


def score_gaps(data: dict, ref_scenes: set[str], lines: dict[str, list[str]]) -> int:
    return _gaps(data, ref_scenes, lines).bad


def clean_gaps(data: dict, ref_scenes: set[str], lines: dict[str, list[str]]) -> list[dict]:
    """event 空或 mentioned_in 一个合格的都没有 → 丢掉；thread 不合格 → thread / after / before 全置 null；
    after / before 不在线里 → 置 null，前后颠倒或相等 → 两个都置 null；同一件事（event + thread）
    写了几次合成一个，mentioned_in 合并。"""
    data = _obj(data)
    rids, tids, bids = _Ids(ref_scenes), _Ids(lines), _Ids(*lines.values())
    out: list[dict] = []
    by_key: dict[tuple, dict] = {}
    for g in _list(data.get("gaps")):
        if not isinstance(g, dict):
            continue
        event = text(g.get("event"))
        refs = [s for s in _uniq(_refs(g.get("mentioned_in"), rids)) if s in ref_scenes]
        if not event or not refs:
            continue
        tid, after, before, _ = _gap_place(g, tids, bids, lines)
        k = (_name_key(event), tid)
        if k in by_key:
            e = by_key[k]
            e["mentioned_in"] += [s for s in refs if s not in e["mentioned_in"]]
            continue
        entry = {"event": event, "mentioned_in": refs, "thread": tid, "after": after, "before": before}
        out.append(entry)
        by_key[k] = entry
    return out
