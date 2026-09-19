"""矛盾扫描：程序分组 → 按批交模型判断（spec 第 6 节）。

时间只作参考给模型判断「是不是随故事推进的合理变化」，不拿它做硬判断——
②b 验收已证实步骤 6 的故事时间估计不硬（L-003 单线 τ 只有 0.32）。
"""

from __future__ import annotations

import hashlib
import re

from .book import now_iso
from .facts import norm_number

STATUSES = ("真矛盾", "合理变化", "无法判断")
LEVELS = ("严重", "中等", "轻微")
CATEGORIES = ("人物", "设定", "时间", "称谓")
# 场景引用：[S-0003] / [S-0003,S-0120]。模型常在逗号后加空格、写全角逗号或顿号，括号里首尾带空格，
# 这些都得认——认漏了，编造的编号会从档案检查里漏过去、合法引用被当成「没带编号」白白重试
# （DE 审查必须修4）。archive.refs_in / check_archive、Task 20 的编造率统计都用这一个正则。
SCENE_REF = re.compile(r"\[\s*(S-\d{4}(?:\s*[,，、]\s*S-\d{4})*)\s*\]")
_SCENE_ID = re.compile(r"S-\d{4}")


def scene_times(threads: list[dict]) -> dict[str, dict]:
    """每个场景的全局故事时间 = 这条线的 offset + 线内时间。没估过的 t 给 None。"""
    out: dict[str, dict] = {}
    for t in threads:
        offset = t.get("offset") or 0
        times = t.get("times") or {}
        for sid in t.get("scenes") or []:
            row = times.get(sid) or {}
            v = row.get("t")
            out[sid] = {
                "t": (offset + v) if isinstance(v, (int, float)) else None,
                "conf": row.get("conf", ""),
                "thread": t.get("id", ""),
            }
    return out


def _scene_line(s: dict, times: dict[str, dict], unit: str) -> str:
    info = times.get(s["id"]) or {}
    bits = [f"[{s['id']}]"]
    if info.get("thread"):
        bits.append(info["thread"])
    if info.get("t") is not None:
        conf = info.get("conf") or ""
        bits.append(f"故事时间约 {info['t']}{unit}" + (f"（把握{conf}）" if conf else ""))
    else:
        bits.append("故事时间未知")
    return "    " + " ".join(bits) + "：" + (s.get("quote") or "")


def group_text(cid: str, cand: dict, times: dict[str, dict], unit: str) -> str:
    """把一个候选组渲染成交给模型的文本。"""
    lines = [f"{cid} 主语：{cand['subject']}　属性：{cand['attribute']}"]
    for v in cand["values"]:
        lines.append(f"  值「{v['value']}」出现在：")
        for s in v["scenes"]:
            lines.append(_scene_line(s, times, unit))
    return "\n".join(lines)


def batches(cands: list[dict], times: dict[str, dict], unit: str, budget: int,
            max_groups: int | None = None) -> list[list[dict]]:
    """按输入字符数上限切批（按 1 字符 1 token 估，偏保守，同 ②b 的做法），
    另外按 max_groups 限制每批最多多少组（审查建议修6：小组多时字符预算一批能塞
    进几百组，单组输出约 60 token，几百组的输出+重试成本容易失控，且一组格式不对
    整批就要重来）。两个上限谁先到就切批。单个组自己就超字符预算的，自成一批——
    不丢任何组。"""
    out: list[list[dict]] = []
    cur: list[dict] = []
    cost = 0
    for i, c in enumerate(cands):
        n = len(group_text(f"C-{i:03d}", c, times, unit))
        if cur and (cost + n > budget or (max_groups is not None and len(cur) >= max_groups)):
            out.append(cur)
            cur, cost = [], 0
        cur.append(c)
        cost += n
    if cur:
        out.append(cur)
    return out


def check_output(data, ids: set[str]) -> list[str]:
    """模型输出的检查，返回要反馈给模型的问题（空列表 = 没问题）。

    宁可多报：groups 里混进非 dict 元素、顶层给成 list、id 是 list 这类畸形输出，
    都必须在这里报出问题触发重试，不能因为其余合法项齐全就悄悄放过——放过了
    clean_output 就会在处理垃圾项时崩溃，把已经花钱拿到的合法判断也一起扔掉。
    """
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        return ["输出要是 {\"groups\": [...]} 的形状"]
    problems = []
    bad = [g for g in groups if not isinstance(g, dict) or not isinstance(g.get("id"), str)]
    got = [g for g in groups if isinstance(g, dict) and isinstance(g.get("id"), str)]
    if bad:
        problems.append(f"有 {len(bad)} 组格式不对（不是对象，或者 id 不是字符串），照给的样例重新输出")
    seen = {g["id"] for g in got}
    missing = sorted(ids - seen)
    extra = sorted(x for x in seen - ids if x)
    if missing:
        problems.append("这些编号没答：" + "、".join(missing[:10]))
    if extra:
        problems.append("这些编号不在我给你的列表里：" + "、".join(extra[:10]))
    for g in got:
        gid = g["id"]
        if g.get("status") not in STATUSES:
            problems.append(f"{gid} 的 status 只能是：" + " / ".join(STATUSES))
        if g.get("status") == "真矛盾" and g.get("level") not in LEVELS:
            problems.append(f"{gid} 判了真矛盾就要给 level：" + " / ".join(LEVELS))
        if g.get("category") not in CATEGORIES:
            problems.append(f"{gid} 的 category 只能是：" + " / ".join(CATEGORIES))
        if not SCENE_REF.search(g.get("reason") or ""):
            problems.append(f"{gid} 的 reason 里要带场景编号，写成 [S-0014] 这样")
    return problems[:8]


def clean_output(data, ids: set[str]) -> dict[str, dict]:
    """整理成 {编号: 判断}。编造的编号丢掉；模型没答的、格式畸形的一律按「宁可多报」
    兜底成「无法判断」——不许抛异常（groups 混非 dict 元素、顶层是 list、id 是 list
    这类不可哈希类型都要能扛住，见 D 组审查必须修2）。"""
    out: dict[str, dict] = {}
    groups = data.get("groups") if isinstance(data, dict) else None
    for g in groups if isinstance(groups, list) else []:
        if not isinstance(g, dict):
            continue
        gid = g.get("id")
        if not isinstance(gid, str) or gid not in ids or gid in out:
            continue
        status = g.get("status") if g.get("status") in STATUSES else "无法判断"
        level = g.get("level") if g.get("level") in LEVELS else ""
        out[gid] = {
            "status": status,
            "level": level if status == "真矛盾" else "",
            "category": g.get("category") if g.get("category") in CATEGORIES else "设定",
            "reason": (g.get("reason") or "").strip(),
        }
    for gid in sorted(ids - set(out)):
        out[gid] = {"status": "无法判断", "level": "", "category": "设定",
                    "reason": "模型没有给出判断，按宁可多报保留，请人工看一眼"}
    return out


def render_values(cands: list[dict], start: int, times: dict[str, dict], unit: str) -> tuple[str, dict[str, dict]]:
    """把一批候选组渲染成提示词的 $groups，同时返回 {本批编号: 候选组}。
    编号在这一批里从 start 开始连号，落盘时再换成 矛盾.json 的正式编号。"""
    numbered = {f"C-{start + i:03d}": c for i, c in enumerate(cands)}
    text = "\n\n".join(group_text(cid, c, times, unit) for cid, c in numbered.items())
    return text, numbered


def values_sig(values: list[dict]) -> str:
    """值集合签名：判断重跑后这一组的值集合是不是变了（多了新值、或原来的值不在了），
    好决定要不要把 verdict 标成 verdict_stale（D 组审查必须修4，作者 9-17 拍板：
    值集合变了，旧判定保留但标需重看）。

    繁简、首尾空白的差异不该算变化——值先做规范化（strip + facts.norm_number 的数字
    规范化）再签名。项目里没有通用繁转简（facts._to_simplified 只覆盖属性名归一用的
    24 项受控属性繁体写法，不能拿来转任意值文本，见 facts.py 的警告），所以这里做不到
    「繁体简体一律算同一个值」；值本身的繁简差异（老卡繁体、新卡简体）仍会被判定为
    「变了」，比不管漏报更安全，报告里会说明这个已知限制。
    """
    norm = sorted(norm_number((v.get("value") or "").strip()) for v in values)
    return hashlib.sha256("\x1f".join(norm).encode("utf-8")).hexdigest()


def _verdict_basis(prev: dict) -> tuple[str | None, bool]:
    """上一轮条目（活跃组或 orphan）里的判定依据：(verdict_sig, 上一轮是否已 stale)。

    verdict_sig = 作者下判定时这一组的值集合签名。二期写裁决时要一起写入；还没有它的
    老条目按下面推：上一轮没标 stale，说明判定对上一轮的值集合有效，用上一轮的
    values_sig 当依据；上一轮已经 stale 就说不清依据是哪一版，返回 None，stale 一直带着
    直到作者重新判定（重新判定会写入新的 verdict_sig）。"""
    vsig = prev.get("verdict_sig")
    if vsig:
        return vsig, False
    if prev.get("verdict_stale"):
        return None, True
    return prev.get("values_sig"), False


def build_result(cands: list[dict], judged: dict[int, dict], times: dict[str, dict],
                 old: dict, stats: dict, skipped: list[dict] | None = None) -> dict:
    """拼出 矛盾.json（spec 7.2）。

    `judged` 的键是 cands 的下标。编号按 (规范主语, 属性) 沿用上一次的，沿用不到的取
    只增不减的 next_id（②a / ②b 撞号踩过的坑）。作者的 verdict 也按 (主语, 属性) 迁移。
    """
    # 索引既要包含上一轮还在的组，也要包含上一轮已经是 orphan 的——不然组消失一轮
    # 再回来时，既接不回原编号也接不回 verdict（D 组审查必须修3）。当前活跃组优先。
    old_by_key: dict[tuple, dict] = {}
    for o in old.get("orphan_verdicts") or []:
        old_by_key[(o.get("subject"), o.get("attribute"))] = o
    for g in old.get("groups") or []:
        old_by_key[(g.get("subject"), g.get("attribute"))] = g
    # 编号登记表：只增不减的 {(主语, 属性): 编号}。orphan 只收有 verdict 的组，没判过的组
    # （二期之前是全部）一消失原号就找不回来了（DE 审查必须修2）；登记表不看 verdict，
    # 出现过的 (主语, 属性) 永远占着自己的号。老数据没有登记表，从 groups / orphan 补。
    registry: dict[tuple, str] = {}
    for e in old.get("id_registry") or []:
        if isinstance(e, dict) and isinstance(e.get("id"), str) and e["id"]:
            registry[(e.get("subject"), e.get("attribute"))] = e["id"]
    for k, g in old_by_key.items():
        if isinstance(g.get("id"), str) and g["id"]:
            registry.setdefault(k, g["id"])
    next_id = int(old.get("next_id") or 1)
    used_keys = set()
    groups = []
    for i, c in enumerate(cands):
        key = (c["subject"], c["attribute"])
        used_keys.add(key)
        prev = old_by_key.get(key)
        if key in registry:
            gid = registry[key]
        else:
            gid = f"C-{next_id:03d}"
            next_id += 1
            registry[key] = gid
        j = judged.get(i) or {"status": "无法判断", "level": "", "category": "设定",
                              "reason": "这一批调用失败，没拿到判断"}
        values = []
        for v in c["values"]:
            scenes = []
            for s in v["scenes"]:
                info = times.get(s["id"]) or {}
                scenes.append({"id": s["id"], "quote": s.get("quote", ""),
                               "thread": info.get("thread", ""),
                               "t": info.get("t"), "conf": info.get("conf", "")})
            values.append({"value": v["value"], "scenes": scenes})
        sig = values_sig(c["values"])
        verdict = (prev or {}).get("verdict")
        vsig, stale = _verdict_basis(prev or {}) if verdict is not None else (None, False)
        # 值集合跟作者下判定时不一样了（多了新值、或原来选中的值不在了）：verdict 保留，
        # 不做任何猜测性处理，只标 verdict_stale 交给界面重新亮出来。比的是「判定依据的
        # 值集合」verdict_sig，不是上一轮的值集合——不然值变了之后再重跑一轮，stale 就
        # 自己消失了（DE 审查必须修1）。依据未知（老格式数据）时沿用上一轮的 stale 标记。
        if vsig is not None:
            stale = vsig != sig
        groups.append({
            "id": gid, "subject": c["subject"], "attribute": c["attribute"],
            "status": j["status"], "level": j["level"], "category": j["category"],
            "reason": j["reason"], "values": values, "values_sig": sig,
            "verdict": verdict, "verdict_sig": vsig, "verdict_stale": stale,
        })
    # orphan 条目带上原 id、values_sig、verdict_sig 和 stale 标记：组回来时才能沿用原编号、
    # 接回原 verdict、判断值集合跟判定时比有没有变；没回来的继续往下传，不丢。
    orphans = []
    for k, g in sorted(old_by_key.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if k in used_keys or not g.get("verdict"):
            continue
        vsig, stale = _verdict_basis(g)
        if vsig is not None:
            stale = vsig != g.get("values_sig")
        orphans.append({"id": g.get("id"), "subject": k[0], "attribute": k[1],
                        "verdict": g["verdict"], "values_sig": g.get("values_sig"),
                        "verdict_sig": vsig, "verdict_stale": stale})
    return {
        "generated": now_iso(),
        "next_id": next_id,
        "groups": groups,
        "skipped": list(skipped or []),
        "orphan_verdicts": orphans,
        "id_registry": [{"subject": k[0], "attribute": k[1], "id": v}
                        for k, v in sorted(registry.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))],
        "stats": dict(stats),
    }


def cap(cands: list[dict], limit: int) -> tuple[list[dict], list[dict]]:
    """候选组超上限就截断（cands 已按权重排好序），被砍掉的记进 skipped，
    不静默丢弃（spec 6.2）。"""
    if len(cands) <= limit:
        return cands, []
    kept = cands[:limit]
    skipped = [{"subject": c["subject"], "attribute": c["attribute"], "reason": "超过上限"}
               for c in cands[limit:]]
    return kept, skipped
