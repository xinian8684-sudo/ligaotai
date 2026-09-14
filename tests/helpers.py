"""测试共用的小工具。"""

import asyncio
import json
import random
import re

CHARS = (
    "天地玄黄宇宙洪荒日月盈昃辰宿列张寒来暑往秋收冬藏闰余成岁律吕调阳云腾致雨"
    "露结为霜金生丽水玉出昆冈剑号巨阙珠称夜光果珍李柰菜重芥姜海咸河淡鳞潜羽翔"
)


def gen_text(seed: int, n: int) -> str:
    """n 个随机汉字，每 20 字一个句号，每 200 字分一段（单个空行）。5 字串几乎不会撞。"""
    rng = random.Random(seed)
    out = []
    for i in range(1, n + 1):
        out.append(rng.choice(CHARS))
        if i % 200 == 0:
            out.append("。\n\n")
        elif i % 20 == 0:
            out.append("。")
    return "".join(out)


def make_chapters(n: int, seed: int = 0) -> list:
    """合成一本 n 回的小书，每回约 6000 字，中间一句带「悟空 / 八戒 / 唐僧」。"""
    from tools.scramble import Chapter

    chapters = []
    for num in range(1, n + 1):
        body = (
            gen_text(seed * 1000 + num * 2, 2990)
            + "\n\n悟空說道，八戒和唐僧都在。\n\n"
            + gen_text(seed * 1000 + num * 2 + 1, 2990)
        )
        chapters.append(Chapter(num, f"第{num}回 標題{num}", body))
    return chapters


def make_verse_chapter(num: int, seed: int = 0):
    """合成一回带「诗曰」全角空格缩进诗句的章节（真实古典小说里常见的排版），
    用来测试 mutate() 删句时不会把缩进诗行变成空白行。"""
    from tools.scramble import Chapter

    FW = "　"
    verse_lines = [f"{FW * 2}{gen_text(seed * 7 + i, 10)}。" for i in range(4)]
    body = (
        gen_text(seed * 1000 + num * 2, 1000)
        + "\n\n詩曰：\n"
        + "\n".join(verse_lines)
        + "\n\n"
        + gen_text(seed * 1000 + num * 2 + 1, 1000)
    )
    return Chapter(num, f"第{num}回 標題{num}", body)


from ligaotai.llm import Reply


class FakeBackend:
    """假的模型接口：按顺序吐预设的回复，或者交给 handler(tier, messages) 现算。

    回复可以是字符串（当作 content）、Reply、或者异常实例（会被抛出）。
    """

    def __init__(self, replies=None, handler=None, delay=0.0):
        self.replies = list(replies or [])
        self.handler = handler
        self.delay = delay
        self.calls = []
        self.active = 0
        self.max_active = 0

    async def complete(self, tier, messages, max_tokens):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            self.calls.append({"tier": tier, "messages": [dict(m) for m in messages], "max_tokens": max_tokens})
            # 哪怕 delay=0 也要真正让出一次事件循环：不然整段 await 链一步做完，
            # TaskGroup 永远来不及在别的任务开工前应用取消/中止。
            await asyncio.sleep(self.delay)
            out = self.handler(tier, messages) if self.handler else self.replies.pop(0)
            if isinstance(out, Exception):
                raise out
            if isinstance(out, Reply):
                return out
            return Reply(content=out, prompt_tokens=100, completion_tokens=20)
        finally:
            self.active -= 1


CARD_PERSONS = ["林清", "清儿", "林姑娘", "赵五", "悟空", "八戒", "唐僧", "金箍郎", "天蓬郎", "御弟師父"]
CARD_PLACES = ["青州城外"]
CARD_ORGS = ["天机阁"]


def scene_text_from(messages) -> str:
    """从场景卡提示词的 user 消息里取出片段原文。"""
    user = messages[1]["content"]
    return user.split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0]


def card_reply(text: str) -> str:
    """按原文里出现的已知名字造一张合格的场景卡。"""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    first = lines[1] if len(lines) > 1 else (lines[0] if lines else "")
    quote = first[:6]
    persons = [n for n in CARD_PERSONS if n in text]
    # fact 的 subject 也要能在原文里核对（cards.py A2），不能再用「某人」这种编出来的占位名字，
    # 否则 check_card 会一直报问题、run_cards 的用量断言全部要重跑。用片段里真实出现的人名。
    subject = persons[0] if persons else None
    card = {
        "summary": "测试摘要。",
        "pov": "",
        "characters": [{"name": n, "role": "主要"} for n in persons],
        "locations": [n for n in CARD_PLACES if n in text],
        "organizations": [n for n in CARD_ORGS if n in text],
        "facts": [{"subject": subject, "attribute": "原文", "value": quote, "quote": quote}] if quote and subject else [],
        "kind": "正文",
    }
    return json.dumps(card, ensure_ascii=False)


def names_from_prompt(messages) -> list[str]:
    """从实体合并提示词的 user 消息里取出叫法列表。"""
    user = messages[1]["content"].split("字面上相近", 1)[0]
    return [ln[2:].split("（", 1)[0] for ln in user.split("\n") if ln.startswith("- ")]


def entity_reply(messages, groups) -> str:
    present = set(names_from_prompt(messages))
    out = []
    for g in groups:
        members = [n for n in g if n in present]
        if len(members) >= 2:
            out.append({"canonical": members[0], "members": members, "reason": "测试"})
    return json.dumps({"groups": out}, ensure_ascii=False)


def fake_ai_handler(groups=()):
    """按提示词种类回复：连通性测试 / 场景卡 / 实体合并。"""

    def handler(tier, messages):
        system = messages[0]["content"]
        if "连通性" in system:
            return '{"ok": true}'
        if "场景卡" in system:
            return card_reply(scene_text_from(messages))
        if "归成一组" in system:
            return entity_reply(messages, groups)
        raise AssertionError("没见过的提示词")

    return handler


def seed_book(book, scenes, entities=(), groups=()):
    """不走导入/切场景/场景卡，直接往书里写场景文件、场景卡、实体.json、版本组.json。

    scenes：字典列表。键：id（必填）、source（默认 a.txt）、index（默认在列表里的位置）、
    kind（默认 正文）、summary、persons、places、refs、world、times、removed、
    no_card（不写卡）、stale_card（卡的 scene_hash 对不上）。
    entities：[(类型, 规范名, [叫法...])]，都写成 draft。groups：[(主版本, [成员...])]。
    """
    from ligaotai.cards import card_path
    from ligaotai.fsutil import write_json
    from ligaotai.scenes import Scene, write_scene

    for i, s in enumerate(scenes):
        sid = s["id"]
        text = s.get("text", f"{sid} 的正文。")
        h = f"h-{sid}"
        write_scene(book, Scene(
            id=sid, source=s.get("source", "a.txt"), index=s.get("index", i), start=0, end=len(text),
            chars=len(text), hash=h, removed=s.get("removed", False), text=text,
        ))
        if s.get("no_card"):
            continue
        card = {
            "summary": s.get("summary", f"{sid} 摘要"),
            "pov": "",
            "characters": [{"name": n, "role": "主要"} for n in s.get("persons", [])],
            "locations": list(s.get("places", [])),
            "organizations": [],
            "world_hint": s.get("world", ""),
            "time_hints": list(s.get("times", [])),
            "refs_elsewhere": list(s.get("refs", [])),
            "kind": s.get("kind", "正文"),
        }
        scene_hash = "old" if s.get("stale_card") else h
        write_json(card_path(book, sid), {"id": sid, "scene_hash": scene_hash, "card": card})
    ents = [
        {"id": f"E-{i:04d}", "type": t, "canonical": c, "names": list(ns), "status": "draft", "reason": "", "scenes": []}
        for i, (t, c, ns) in enumerate(entities, 1)
    ]
    write_json(book.entities_path, {"next_id": len(ents) + 1, "entities": ents})
    write_json(book.versions_path, {"params": {}, "groups": [
        {"id": f"G-{i:03d}", "members": list(ms), "main": m, "main_by": "auto", "pairs": []}
        for i, (m, ms) in enumerate(groups, 1)
    ]})


_LISTED = re.compile(r"^(?:\[[^\]]*\] )?(S-\d{4,})｜", re.M)
_THREAD_HEAD = re.compile(r"^## (L-\d+)", re.M)


def listed_scenes(messages) -> list[str]:
    """归线提示词 user 消息里列出的场景编号（行首的 S-编号｜，缩进的示例行不算）。"""
    return _LISTED.findall(messages[1]["content"])


def threads_handler(worlds=None, lines=None, order=None, align=None, gaps=None, fallback=None):
    """步骤 6 各次调用的假回复。每个参数是 fn(messages) -> 回复（字符串 / Reply / 异常实例）；不给就用默认：
    全部归一个世界「世界一」、正文碎片全归一条主线（提纲挂上去）、按列出的顺序排、偏移都是 0、没有缺口。
    认不出的提示词交给 fallback（比如 fake_ai_handler()），没有 fallback 就报错。"""

    def d_worlds(m):
        return json.dumps(
            {"time_unit": "年", "worlds": [{"name": "世界一", "reason": "测试", "scenes": listed_scenes(m)}]},
            ensure_ascii=False,
        )

    def d_lines(m):
        user = m[1]["content"]
        ids = listed_scenes(m)
        outl = [i for i in ids if f"{i}｜提纲" in user]
        sc = [i for i in ids if i not in outl]
        threads = [{"name": "主线", "about": "测试", "main": True, "scenes": sc, "outlines": outl}] if sc else []
        return json.dumps({"threads": threads, "world_outlines": [] if sc else outl}, ensure_ascii=False)

    def d_order(m):
        ids = listed_scenes(m)
        return json.dumps(
            {"order": ids, "times": {s: [i, "高"] for i, s in enumerate(ids)}, "end": {"state": "待定", "note": "测试"}},
            ensure_ascii=False,
        )

    def d_align(m):
        tids = _THREAD_HEAD.findall(m[1]["content"])
        return json.dumps({"threads": [{"id": t, "offset": 0} for t in tids], "intersections": []})

    def d_gaps(m):
        return '{"gaps": []}'

    table = [
        ("划分世界", worlds or d_worlds),
        ("划分支线", lines or d_lines),
        ("线内排序", order or d_order),
        ("跨线对齐", align or d_align),
        ("找缺口", gaps or d_gaps),
    ]

    def handler(tier, messages):
        system = messages[0]["content"]
        for mark, fn in table:
            if mark in system:
                return fn(messages)
        if fallback is not None:
            return fallback(tier, messages)
        raise AssertionError("没见过的提示词")

    return handler
