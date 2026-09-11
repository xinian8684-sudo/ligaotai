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
