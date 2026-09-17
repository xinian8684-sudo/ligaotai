"""矛盾扫描：程序分组 → 按批交模型判断（spec 第 6 节）。

时间只作参考给模型判断「是不是随故事推进的合理变化」，不拿它做硬判断——
②b 验收已证实步骤 6 的故事时间估计不硬（L-003 单线 τ 只有 0.32）。
"""

from __future__ import annotations


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


def batches(cands: list[dict], times: dict[str, dict], unit: str, budget: int) -> list[list[dict]]:
    """按输入字符数上限切批（按 1 字符 1 token 估，偏保守，同 ②b 的做法）。
    单个组自己就超预算的，自成一批——不丢任何组。"""
    out: list[list[dict]] = []
    cur: list[dict] = []
    cost = 0
    for i, c in enumerate(cands):
        n = len(group_text(f"C-{i:03d}", c, times, unit))
        if cur and cost + n > budget:
            out.append(cur)
            cur, cost = [], 0
        cur.append(c)
        cost += n
    if cur:
        out.append(cur)
    return out
