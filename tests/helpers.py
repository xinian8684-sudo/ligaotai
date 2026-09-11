"""测试共用的小工具。"""

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
