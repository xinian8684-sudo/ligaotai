"""计划②c 的验收：引用核对（编造率、无引用句率）、植入矛盾召回率、人工抽查抽样。

用法：
  uv run python tools/eval_archives.py --book <书库>/<书名> --key data/乱稿-xxx-答案.json
  uv run python tools/eval_archives.py --book ... --sample 10 --out 抽查.md
门槛（spec 第 9 节）：编造率 ≤ 2%，无引用句率 ≤ 10%，植入矛盾召回 ≥ 8/10。
"""

from __future__ import annotations

import argparse
import json
import random as _random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # 自己所在目录，给 `from eval_threads import ...` 用

from ligaotai.archive import _DECOR, prepare_inputs, refs_in  # noqa: E402
from ligaotai.book import Book  # noqa: E402
from ligaotai.config import AppConfig, load_config  # noqa: E402
from ligaotai.scenes import read_scene, scene_path  # noqa: E402

_SENT = re.compile(r"[^。！？\n]+[。！？]?")
# 这两个小节里的编号是程序发给模型的材料，合法地可能不属于本线（见 check_refs）。
_LENIENT_SECTIONS = ("缺口", "开放的伏笔")
FABRICATED_LIMIT = 0.02
NO_REF_LIMIT = 0.10
RECALL_FLOOR = 0.8
# I1（9-20 GHIJ 审查）经验重试系数：llm.py 的 MAX_ATTEMPTS=3 是最坏情况——一次调用
# 失败重试到底，3 次全额计费；但多数调用一次就成功，按 3 倍算会明显高估。这里跟
# tools/eval_threads.py 的 CARD_CALLS(1.75)/THREAD_PASSES(5) 一样按经验系数估，不按
# 最坏情况的整数倍算。步骤 7 的 check_archive 硬规则（每句结论都要带编号+编号必须在
# 范围内）触发重试的概率不低，1.5 比「完全不算重试」（旧版）更诚实。
RETRY_FACTOR = 1.5
_HIT_STATUS = ("真矛盾", "无法判断")  # 宁可多报：这两种在界面上一起显示，一起算召回


# C3 修复（9-20 GHIJ 审查，75c866a 的漏）：旧版 sections() 认标题只看 `#` 前缀、
# 小节名直接拿 lstrip("#").strip() 的原文比对，而生成期 archive.check_archive() 判
# 小节齐不齐用的是子串（`f"## {h}" not in md`），两边口径不一致。模型只要在标题后面
# 加个括号或冒号（真数据上很常见），`## 缺口（3 处）` 生成期放行、验收却判「缺口」小节
# 不存在，把合规引用当编造。改成：标题识别、去装饰跟 archive._section_attr 同一套口径
# （容忍加粗/反引号/方括号等装饰、末尾冒号，也认模型整行用加粗包住标题、没有 # 前缀
# 的写法，比如 `**缺口**`），小节名比对从「相等」改成「去装饰后前缀匹配」。
_HEADING_HASH = re.compile(r"^#{1,4}\s*(.+)$")
_HEADING_BOLD = re.compile(r"^(?:\*\*|__)(.+?)(?:\*\*|__)$")


def _heading_title(line: str) -> str | None:
    """一行是不是标题，是就返回标题原文（还没去装饰）。跟生成期 archive._HEADING 一样
    认 `#{1,4}` 开头；另外模型偶尔整行只用加粗包住标题、不带 `#`（比如 `**缺口**`），
    `archive.backfill_refs` 那边专门为这种写法做了 `_DECOR` 去装饰，这边原来没认，
    顺手补上。不是标题返回 None。"""
    m = _HEADING_HASH.match(line)
    if m:
        return m.group(1)
    m = _HEADING_BOLD.match(line)
    if m:
        return m.group(1)
    return None


def sections(text: str) -> list[tuple[str, str]]:
    """按句切，同时记下每句在哪个小节下（标题行不算句子）。"""
    cur = ""
    out = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        title = _heading_title(s)
        if title is not None:
            cur = _DECOR.sub("", title).strip().rstrip("：:")
            continue
        for m in _SENT.finditer(s):
            piece = m.group(0).strip()
            if piece:
                out.append((cur, piece))
    return out


def sentences(text: str) -> list[str]:
    """按句切，跳过标题行和空行——标题不是结论句，不该算进无引用句率。

    直接复用 `sections()`，别另起一套切句实现：两份平行实现改一处漏一处，会出现
    「抽查材料里的句子和核对时数的句子不是一批」（GHIJ 审查 Minor 条目，顺手做掉）。"""
    return [s for _, s in sections(text)]


def check_refs(bodies: dict[str, str], allowed: dict[str, set[str]],
               existing: set[str], lenient: dict[str, set[str]] | None = None) -> dict:
    """逐条核每个引用：编号存在、且属于这份档案的范围（spec 9.2）。

    `lenient` 给「缺口」「开放的伏笔」这两个小节用的宽范围。这两段里的编号合法地可能不
    属于这条线：缺口就是「提到过、但书里找不到对应场景的事件」，提到它的那个场景常常在
    别的线上；而且这些编号是程序渲染进输入材料、明确发给模型的（见 prompts/
    archive_thread.md 的「## 缺口」行，`archive.py` 算 thread_scope 时也是这么并进去的）。
    拿 spec 9.2 的严格归属去核这两段，会把合规引用判成编造。正文其余小节照旧严格按本线核，
    编造出来的编号（不在 existing 里）无论在哪个小节都照抓。不传 `lenient` 时行为不变。

    小节名判据是「去装饰后前缀匹配」，不是相等（C3，9-20 GHIJ 审查）：`sections()` 判小节
    齐不齐用的口径原来是相等，生成期 `archive.check_archive()` 判小节存在用的是子串
    （`f"## {h}" not in md`），模型只要在标题后面加个括号或冒号（真数据上很常见），
    比如 `## 缺口（3 处）`，旧版就认不出这是「缺口」小节，把合规引用误判成编造。"""
    lenient = lenient or {}
    total = bad = n_sent = no_ref = 0
    details = []
    for oid, body in sorted(bodies.items()):
        scope = allowed.get(oid, set())
        wide = lenient.get(oid) or scope
        for sec, s in sections(body):
            n_sent += 1
            refs = refs_in(s)
            if not refs:
                no_ref += 1
            use = wide if any(sec.startswith(h) for h in _LENIENT_SECTIONS) else scope
            for r in refs:
                total += 1
                why = ""
                if r not in existing:
                    why = "编号不存在"
                elif use and r not in use:
                    why = "不属于这份档案"
                if why:
                    bad += 1
                    details.append({"archive": oid, "ref": r, "why": why, "sentence": s[:60]})
    return {
        "total": total, "bad": bad,
        "fabricated_rate": round(bad / total, 4) if total else 0.0,
        "sentences": n_sent, "no_ref": no_ref,
        "no_ref_rate": round(no_ref / n_sent, 4) if n_sent else 0.0,
        "details": details[:50],
    }


def recall(key: dict, chapter_scenes: dict[int, set[str]], result: dict) -> dict:
    """植入矛盾的召回（spec 9.1）。

    一处植入 = 同一个人物在两个不同章节被写成两个不同的年龄（见 `tools/scramble.py`
    的 `plant_contradictions`）。命中要求**两处说法都被同一个组覆盖、且落在两个不同的值上**——
    只引了其中一处，说明扫描没把两处对比起来，那就不算发现了这对矛盾。

    旧判据只要「属性相同 + 场景编号有交集」，宽得多。9-21 真跑《雪月梅传》时，植入点所在
    场景往往还涉及书里本来就有的别的矛盾，属性一撞就算命中——那种命中证明不了任何事。
    """
    planted = key.get("contradictions") or []
    if planted and "chapters" not in planted[0]:
        sys.exit("答案文件是旧格式（每条只有一个 chapter + old/new），新判据要的是 "
                 "{chapters: [a, b], values: [v1, v2]}。拿新版 tools/scramble.py 重新生成乱稿。")

    groups = [g for g in (result.get("groups") or []) if g.get("status") in _HIT_STATUS]
    hit, misses, matched_ids, subject_mismatch = 0, [], set(), 0
    for p in planted:
        want = [chapter_scenes.get(ch, set()) for ch in p["chapters"]]
        found = None
        for g in groups:
            if g.get("attribute") != p["attribute"]:
                continue
            # 两处说法要落在两个不同的值上：同一个值出现在两章里是一致，不是矛盾
            covering = []
            for v in g.get("values") or []:
                ids = {s["id"] for s in v.get("scenes") or []}
                covering.append([bool(ids & w) for w in want])
            if not covering:
                continue
            pairs = [(i, j) for i in range(len(covering)) for j in range(len(covering))
                     if i != j and covering[i][0] and covering[j][1]]
            if pairs:
                found = g
                break
        if found:
            hit += 1
            matched_ids.add(found["id"])
            names = set(p.get("names") or []) | {p.get("subject", "")}
            got = found.get("subject", "")
            if not any(nm and (nm in got or got in nm) for nm in names):
                subject_mismatch += 1
        else:
            misses.append(p)
    return {
        "planted": len(planted), "hit": hit,
        "recall": round(hit / len(planted), 4) if planted else 0.0,
        "misses": misses,
        # 命中了但主语归错（9-21 实测：玉霜娘的年龄被算到小梅名下）。不影响命中，单独记。
        "subject_mismatch": subject_mismatch,
        # 没对上植入点的真矛盾。**这不等于误报**——验收语料本身就有自己的矛盾，
        # 9-21 真跑报的 3 条全是书里真有的分歧，一条瞎编的都没有。只报数，不设门槛。
        "unmatched_true": sum(1 for g in groups if g.get("status") == "真矛盾"
                              and g["id"] not in matched_ids),
    }

def chapter_to_scenes(book: Book, key: dict, folder_name: str) -> dict[int, set[str]]:
    """章节号 → 场景编号集合。答案文件记的是章节，S- 编号是导入时才分配的，
    所以要通过 key["files"] 的 path 和书的导入清单反查。

    直接复用 eval_threads.truth_positions——它返回 {场景编号: (章节, 段序, 段数)}，
    这边只要反过来聚合。别另起炉灶，两处读法不一致就会对不上。"""
    from eval_threads import truth_positions  # tools/ 已在 sys.path 里

    out: dict[int, set[str]] = {}
    for sid, pos in truth_positions(book, key, folder_name).items():
        out.setdefault(pos[0], set()).add(sid)
    return out


def sample_for_review(bodies: dict[str, str], scenes: dict[str, str],
                      rng: _random.Random, n: int) -> str:
    """随机抽 n 条带编号的结论句，配上它引用的场景原文，写成对照材料给作者人工判（spec 9.3）。"""
    pool = []
    for oid, body in sorted(bodies.items()):
        for s in sentences(body):
            refs = refs_in(s)
            if refs:
                pool.append((oid, s, refs))
    rng.shuffle(pool)
    picked = pool[:n]
    out = ["# 档案人工抽查", "", f"共 {len(picked)} 条。逐条判：这句结论，它引用的原文撑得住吗？", ""]
    for i, (oid, s, refs) in enumerate(picked, 1):
        out += [f"## 第 {i} 条（来自 {oid}）", "", f"**档案里写的**：{s}", "", "**引用的原文**："]
        for r in refs:
            text = scenes.get(r, "（找不到这个场景）")
            out.append(f"- [{r}] {text[:300]}")
        out += ["", "判断：□ 撑得住　□ 撑不住　□ 不好说", "", "---", ""]
    return "\n".join(out)


def estimate(book: Book, cfg: AppConfig) -> dict:
    """不调模型，只粗估要花多少钱（spec 9.4）。分项给，别只给总数——作者要据此决定
    跑不跑、跑几本。

    I1 订正（9-20 GHIJ 审查）：旧版有三处偏差，方向相反、互相抵消得不明不白——
    1. 不算重试：`llm.py` 的 `MAX_ATTEMPTS=3`，且 `finish_reason=="length"` 时会把
       `max_tokens` 翻倍再调一次，一次调用最坏 3 次全额计费。这里按 `RETRY_FACTOR`
       的经验系数估（同 `tools/eval_threads.py` 的 `CARD_CALLS`/`THREAD_PASSES` 口径），
       不按最坏情况的 3 倍算。
    2. 输出不受 `max_tokens` 约束：旧版按「输出 = 输入 × 1.0」算总字符数，但 synth 档
       `max_tokens=32768`（`config.py`），世界设定集/全书地图这类大输入根本不可能真
       输出那么多——实测西游记世界设定集输入 128888 字、全书地图输入 221435 字，
       实际输出最多 32768，旧版把这两项高估 4-7 倍。这里按**每次调用**（每条线/每个
       世界/每批矛盾/地图这一次）把输出封顶在 `min(该次输入字符数, synth.max_tokens)`，
       再对所有调用求和——不能对聚合后的总字符数封顶，那样会把「很多次小调用」错误地
       压成「一次大调用」的量级，反而低估。
    3. docstring 曾经写「②b 的教训是归线输出比输入还多」——这句话跟这个仓库自己的
       ②b 真实日志相反：threads 的输出只有输入的 0.407 倍、entities 0.931 倍、cards
       0.326 倍，一次都没超过 1（见 `reports/GHIJ-审查.md` 的日志校准表）。这次订正为
       实话：char→token 按 1:1 估是保守的上界（②b 真值 0.700–0.845 token/字符，比
       1:1 更省），输出按输入 1.0 倍（封顶前）也是上界假设，不是「归线输出比输入多」
       这条（查无实据的）经验。

    - 支线档案：线数 × 每线输入字符数（archive_input.thread_input 渲染出的文本，用
      prepare_inputs() 算好的 thread_text 直接求和，比「平均每线」更准）。
    - 世界设定集：世界数 × 该世界渲染文本字符数（world_text，含 facts + 设定笔记原文）。
    - 矛盾扫描：批数 × 批输入字符数（contradictions.batches 已经按预算切好的批）。
    - 全书地图：全部档案字符数——地图读的是**生成好的档案正文**，不是这些输入文本；
      估算时档案还没生成，用「输出 = 输入 × 1.0（封顶前）」这同一条假设，拿支线 + 世界的
      输入字符数近似档案生成后的大小；这是上界近似，不是真实的地图输入渲染。
    """
    inp = prepare_inputs(book)
    price_in, price_out = cfg.price_input, cfg.price_output
    cap = cfg.synth.max_tokens

    def usd(input_chars: int, per_call_chars: list[int]) -> float:
        # 输入按 1 字符 1 token 估（偏保守，同全项目口径）；输出按每次调用自己的输入
        # 字符数封顶在 synth.max_tokens（不能对聚合总数封顶，见上面 docstring 第 2 条），
        # 再乘经验重试系数。
        output_tokens = sum(min(c, cap) for c in per_call_chars)
        return round((input_chars * price_in / 1e6 + output_tokens * price_out / 1e6) * RETRY_FACTOR, 4)

    thread_lens = [len(t) for t in inp.thread_text.values()]
    world_lens = [len(t) for t in inp.world_text.values()]
    contra_lens = [len(b["text"]) for b in inp.contra["batches"]]
    thread_chars, world_chars, contra_chars = sum(thread_lens), sum(world_lens), sum(contra_lens)
    map_chars = thread_chars + world_chars  # 见上面 docstring 关于全书地图的注释

    parts = {
        "支线档案": {"n": len(thread_lens), "input_chars": thread_chars,
                   "usd": usd(thread_chars, thread_lens)},
        "世界设定集": {"n": len(world_lens), "input_chars": world_chars,
                    "usd": usd(world_chars, world_lens)},
        "矛盾扫描": {"n": len(contra_lens), "input_chars": contra_chars,
                  "usd": usd(contra_chars, contra_lens)},
        "全书地图": {"n": 1, "input_chars": map_chars, "usd": usd(map_chars, [map_chars])},
    }
    return {**parts, "total_usd": round(sum(p["usd"] for p in parts.values()), 4),
            "retry_factor": RETRY_FACTOR, "output_cap_tokens": cap}


def _scene_texts(book: Book, ids: set[str]) -> dict[str, str]:
    out = {}
    for sid in ids:
        try:
            out[sid] = read_scene(scene_path(book, sid)).text.strip()
        except (OSError, ValueError):
            out[sid] = ""
    return out


# --------------------------------------------------------------------------------------
# main() 用到的书内数据装配
# --------------------------------------------------------------------------------------

def generation_scopes(book: Book) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """生成档案时模型真正被允许引用的范围（`archive.py` 的 thread_scope / world_scope：
    本线场景 ∪ 渲染进输入材料的全部编号）。上游数据不全时返回空的，调用方退回严格范围。"""
    try:
        inp = prepare_inputs(book)
    except (OSError, ValueError, KeyError, TypeError):
        return {}, {}
    return dict(inp.thread_scope), dict(inp.world_scope)


def load_scopes_and_bodies(book: Book) -> tuple[dict[str, str], dict[str, set[str]],
                                                set[str], dict[str, set[str]], dict]:
    """从 档案/index.json 拿到各份档案的路径与范围：线的范围 = index 里记的这条线的
    scenes；世界的范围 = 这个世界下所有线（index 线条目的 world 字段）的场景并集；
    地图的范围 = 全书场景（场景/ 目录下现存的编号）。

    第四个返回值是「缺口 / 开放的伏笔」两个小节用的宽范围（见 `check_refs`），取自生成
    档案时的真实 scope。世界设定集没有可区分的小节结构，它要用到的设定笔记场景同样可能
    落在本世界各线之外，所以世界的严格范围直接并上生成时的 world_scope。

    第五个返回值是 outdated 统计（C2，9-20 GHIJ 审查）：`archive.py` 的设计是一份档案
    生成失败、或跑的途中上游变了，旧文件留着给作者看，只在 index 里标 `outdated`
    （`archive.py:422-427`、`settle()`、`map()` 的 blocked 分支）。**标了 outdated 的
    档案不进 bodies/allowed**——不然验收工具会拿一份作废的旧档案打分，产物目录里留着
    上一轮的东西，读进来算出来的编造率/无引用句率照样很漂亮，报 pass=True，
    而这其实是一次假通过。调用方要检查这个返回值，有 outdated 就不能信这次验收结果。"""
    index = {}
    if book.archive_index_path.exists():
        try:
            index = json.loads(book.archive_index_path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            index = {}
    threads = index.get("threads") if isinstance(index.get("threads"), dict) else {}
    worlds = index.get("worlds") if isinstance(index.get("worlds"), dict) else {}
    map_entry = index.get("map") if isinstance(index.get("map"), dict) else {}

    thread_scope = {tid: set(e.get("scenes") or []) for tid, e in threads.items() if isinstance(e, dict)}
    world_scope: dict[str, set[str]] = {wid: set() for wid, e in worlds.items() if isinstance(e, dict)}
    for e in threads.values():
        if not isinstance(e, dict):
            continue
        wid = e.get("world")
        if wid in world_scope:
            world_scope[wid] |= set(e.get("scenes") or [])

    existing = {p.stem for p in book.scenes_dir.glob("S-*.md")} if book.scenes_dir.exists() else set()

    gen_thread, gen_world = generation_scopes(book)

    bodies: dict[str, str] = {}
    allowed: dict[str, set[str]] = {}
    lenient: dict[str, set[str]] = {}
    outdated: dict = {"threads": [], "worlds": [], "map": False, "map_blocked_by": []}
    for tid, e in threads.items():
        if not (isinstance(e, dict) and e.get("file")):
            continue
        if e.get("outdated"):
            outdated["threads"].append(tid)
            continue
        p = book.root / e["file"]
        if p.exists():
            bodies[tid] = p.read_text(encoding="utf-8")
            allowed[tid] = thread_scope.get(tid, set())
            lenient[tid] = allowed[tid] | gen_thread.get(tid, set())
    for wid, e in worlds.items():
        if not (isinstance(e, dict) and e.get("file")):
            continue
        if e.get("outdated"):
            outdated["worlds"].append(wid)
            continue
        p = book.root / e["file"]
        if p.exists():
            bodies[wid] = p.read_text(encoding="utf-8")
            allowed[wid] = world_scope.get(wid, set()) | gen_world.get(wid, set())
    if map_entry.get("outdated"):
        outdated["map"] = True
        outdated["map_blocked_by"] = list(map_entry.get("blocked_by") or [])
    elif book.map_path.exists():
        bodies["全书地图"] = book.map_path.read_text(encoding="utf-8")
        allowed["全书地图"] = set(existing)  # 地图的范围 = 全书场景
    return bodies, allowed, existing, lenient, outdated


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="验收步骤 7（档案/矛盾/地图）产出的引用质量与植入矛盾召回")
    ap.add_argument("--book", required=True, help="书目录路径，比如 data/验收书库/验收-归档-西游记")
    ap.add_argument("--key", help="乱稿答案文件（含 --contradictions 植入的矛盾），给了就顺带算召回率")
    ap.add_argument("--folder", help="--key 对应的乱稿文件夹名（章节→场景映射要用），跟 --key 搭配必填")
    ap.add_argument("--report", default="data/验收-档案.json")
    ap.add_argument("--sample", type=int, help="随机抽这么多条带编号的结论句给作者人工判（spec 9.3），不跑引用核对")
    ap.add_argument("--out", default="data/验收-档案-抽查.md", help="--sample 的输出文件")
    ap.add_argument("--seed", type=int, default=1, help="--sample 用的随机种子")
    ap.add_argument("--estimate", action="store_true", help="只粗估四件产出要花多少钱，不调模型")
    args = ap.parse_args(argv)

    cfg = load_config()

    if args.estimate:
        est = estimate(Book(Path(args.book)), cfg)
        out_path = Path(args.report).with_name(Path(args.report).stem + "-估算.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(est, ensure_ascii=False, indent=2), encoding="utf-8")
        print("total_usd=" + str(est["total_usd"]) + " report=" + str(out_path))
        return

    book = Book(Path(args.book))

    if args.sample:
        bodies, _, existing, _lenient, _outdated = load_scopes_and_bodies(book)
        scenes = _scene_texts(book, existing)
        md = sample_for_review(bodies, scenes, _random.Random(args.seed), args.sample)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"sampled={md.count('## 第')} out={out_path}")
        return

    bodies, allowed, existing, lenient, outdated = load_scopes_and_bodies(book)
    refs = check_refs(bodies, allowed, existing, lenient)
    report: dict = {"refs": refs}
    ok = refs["fabricated_rate"] <= FABRICATED_LIMIT and refs["no_ref_rate"] <= NO_REF_LIMIT

    n_outdated = len(outdated["threads"]) + len(outdated["worlds"]) + (1 if outdated["map"] else 0)
    if n_outdated:
        report["outdated"] = outdated
        ok = False

    if args.key:
        if not args.folder:
            sys.exit("--key 需要搭配 --folder（乱稿文件夹名）")
        key = json.loads(Path(args.key).read_text(encoding="utf-8"))
        # I3（9-20 GHIJ 审查）：答案文件没有 contradictions（加这功能之前生成的旧答案文件）
        # 时，召回门槛原来会被静默跳过、还打印 recall=0.0 pass=True——看着像失败，退出码
        # 却是 0。拿 --key 就是为了顺带算召回率，答案文件里压根没植入矛盾就没什么可算的，
        # 硬报错逼着换一份带矛盾的答案文件，别让「没法算」悄悄看起来像「算出来是 0」。
        if not key.get("contradictions"):
            sys.exit("这份答案文件没有植入矛盾，重新跑 scramble --contradictions N")
        chapter_scenes = chapter_to_scenes(book, key, args.folder)
        # 对称的坑：--folder 传错时 by_path 一个都对不上，chapter_scenes 全空，recall
        # 会静默变 0（这次 pass=False，但原因跟上面「没有 contradictions」完全不同，
        # 报告里分不出来）。同样硬报错，别让两种「0」看起来一样。
        if not chapter_scenes:
            sys.exit(f"--folder {args.folder} 在这本书里一个场景都没对上，"
                      "多半是乱稿文件夹名传错了")
        result = {}
        if book.contradictions_path.exists():
            try:
                result = json.loads(book.contradictions_path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                result = {}
        rec = recall(key, chapter_scenes, result)
        report["recall"] = rec
        ok = ok and (rec["planted"] == 0 or rec["recall"] >= RECALL_FLOOR)

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if n_outdated:
        print(f"警告：本次读到的档案里有 {n_outdated} 份被标 outdated / 地图 blocked，验收结果不可信 "
              f"（threads={outdated['threads']} worlds={outdated['worlds']} map_blocked={outdated['map']}）")
    print(
        f"fabricated_rate={refs['fabricated_rate']} no_ref_rate={refs['no_ref_rate']} "
        f"bad={refs['bad']}/{refs['total']} recall={report.get('recall', {}).get('recall')} "
        f"pass={ok} report={report_path}"
    )
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
