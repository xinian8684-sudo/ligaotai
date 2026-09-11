"""测试共用的小工具。"""

import asyncio
import json
import random

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
    card = {
        "summary": "测试摘要。",
        "pov": "",
        "characters": [{"name": n, "role": "主要"} for n in CARD_PERSONS if n in text],
        "locations": [n for n in CARD_PLACES if n in text],
        "organizations": [n for n in CARD_ORGS if n in text],
        "facts": [{"subject": "某人", "attribute": "原文", "value": quote, "quote": quote}] if quote else [],
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
