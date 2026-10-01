import json
import random
from pathlib import Path

import pytest
from helpers import gen_text, make_chapters, make_verse_chapter

from ligaotai.readers import read_text
from ligaotai.split import split_text
from tools.scramble import (
    _pick_excerpt_span,
    main,
    mutate,
    parse_chapters,
    scramble,
    strip_gutenberg,
)

SMALL = dict(n_delete=2, n_truncate=2, n_full=3, n_excerpt=2, alias_chapters=5)


def all_text(out, key, chapter=None, kind=None):
    parts = []
    for f in key["files"]:
        if chapter is not None and f["chapter"] != chapter:
            continue
        if kind is not None and f["kind"] != kind:
            continue
        parts.append(read_text(out / f["path"])[0])
    return "\n".join(parts)


def test_strip_and_parse_gutenberg_like():
    raw = (
        "The Project Gutenberg eBook\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\n\n"
        "Produced by Someone\n\n第一回     標題\n\n\n\n　　詩曰：\n正文一。\n\n"
        " 第二回 標題二\n正文二。\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\nlicense"
    )
    chapters = parse_chapters(strip_gutenberg(raw))
    assert [c.heading for c in chapters] == ["第一回     標題", "第二回 標題二"]
    assert chapters[0].body.startswith("　　詩曰：")
    assert chapters[1].body == "正文二。"


@pytest.fixture
def scrambled(tmp_path):
    out = tmp_path / "乱稿"
    key = scramble(make_chapters(20), out, seed=3, **SMALL)
    return out, key


def test_counts_and_files_exist(scrambled):
    out, key = scrambled
    assert len(key["deleted"]) == 2
    assert len(key["truncated"]) == 2
    kinds = [f["kind"] for f in key["files"]]
    assert kinds.count("variant_full") == 3
    assert kinds.count("variant_excerpt") == 2
    assert all((out / f["path"]).exists() for f in key["files"])
    assert len({f["path"] for f in key["files"]}) == len(key["files"])
    assert {f["format"] for f in key["files"]} <= {"txt", "md", "docx"}
    assert not set(key["deleted"]) & {f["chapter"] for f in key["files"]}


def test_variants_point_to_single_file_originals(scrambled):
    _, key = scrambled
    by_path = {f["path"]: f for f in key["files"]}
    assert len(key["variants"]) == 5
    for v in key["variants"]:
        orig = by_path[v["original_file"]]
        assert (orig["kind"], orig["chapter"], orig["pieces"]) == ("original", v["chapter"], 1)


def test_deleted_chapter_text_is_gone(scrambled):
    out, key = scrambled
    chapters = make_chapters(20)
    everything = all_text(out, key)
    for num in key["deleted"]:
        assert chapters[num - 1].body[:100] not in everything


def test_aliases_applied(scrambled):
    out, key = scrambled
    truncated = {t["chapter"] for t in key["truncated"]}
    for a in key["aliases"]:
        assert len(a["chapters"]) == 5
        num = next(c for c in a["chapters"] if c not in truncated)
        text = all_text(out, key, chapter=num, kind="original")
        assert a["alias"] in text
        assert a["replaces"] not in text


def test_deterministic(tmp_path):
    k1 = scramble(make_chapters(20), tmp_path / "a", seed=3, **SMALL)
    k2 = scramble(make_chapters(20), tmp_path / "b", seed=3, **SMALL)
    assert k1 == k2


def test_alias_collision_raises(tmp_path):
    chapters = make_chapters(20)
    chapters[5].body += "金箍郎"
    with pytest.raises(ValueError):
        scramble(chapters, tmp_path / "x", seed=3, **SMALL)


def test_alias_replaces_not_in_source_raises(tmp_path):
    """replaces 写的词原文里一回都没有：抛 ValueError，不悄悄生成一个出现 0 回的别名（T17-1）。"""
    chapters = make_chapters(20)
    aliases = [{"replaces": "不存在的人名", "alias": "某某郎", "canonical": "某某"}]
    with pytest.raises(ValueError, match="不存在的人名"):
        scramble(chapters, tmp_path / "x", seed=3, aliases=aliases, **SMALL)


def test_alias_candidates_require_term(tmp_path):
    """别名章节必须真的含有被替换的词，别名候选要在截断之后的正文里挑（Fix 1）。"""
    chapters = make_chapters(20)
    for c in chapters:
        if c.num not in (3, 5, 7):
            c.body = c.body.replace("八戒", "某人")
    out = tmp_path / "乱稿"
    key = scramble(
        chapters, out, seed=3,
        n_delete=0, n_truncate=0, n_full=0, n_excerpt=0, alias_chapters=5,
    )
    ba = next(a for a in key["aliases"] if a["replaces"] == "八戒")
    assert set(ba["chapters"]) <= {3, 5, 7}
    assert ba["chapters"]
    for num in ba["chapters"]:
        text = all_text(out, key, chapter=num, kind="original")
        assert "天蓬郎" in text


class FakeRng:
    """固定 random() 序列，choice 永远取第一个元素。"""

    def __init__(self, values):
        self.values = list(values)
        self.i = 0

    def random(self):
        v = self.values[self.i]
        self.i += 1
        return v

    def choice(self, seq):
        return seq[0]


def test_mutate_drop_leaves_no_blank_run():
    """删掉缩进诗句时不能留下只剩全角空格的行，否则会被 split.py 当成空行制造假场景分隔（Fix 2）。"""
    FW = "　"
    text = "前文。\n" + FW * 4 + "甲句。\n" + FW * 4 + "乙句。\n" + FW * 4 + "丙句。\n後文。"
    # _SENTENCE.split 在这段文本上切出 6 个片段（含结尾一个空片段），每个都要抽一次 random()。
    rng = FakeRng([0.9, 0.0, 0.0, 0.9, 0.9, 0.9])  # 保留、删、删、保留、保留、（空片段）
    result = mutate(text, rng)
    assert result == "前文。\n" + FW * 4 + "丙句。\n後文。"


def _blank_line_runs(text: str) -> int:
    """统计连续 >=2 行「去空白后为空」的行的运行段数（含全角空格）。"""
    lines = text.split("\n")
    runs, i, n = 0, 0, len(lines)
    while i < n:
        if not lines[i].strip():
            j = i
            while j < n and not lines[j].strip():
                j += 1
            if j - i >= 2:
                runs += 1
            i = j
        else:
            i += 1
    return runs


def test_mutate_never_increases_blank_line_runs():
    """跑 20 个种子：mutate 之后「连续 >=2 空行」的段数不能比原文多（Fix 2）。"""
    for seed in range(20):
        chapter = make_verse_chapter(1, seed=seed)
        rng = random.Random(seed)
        result = mutate(chapter.body, rng)
        assert _blank_line_runs(result) <= _blank_line_runs(chapter.body)


def test_pick_excerpt_span_within_one_block():
    """新的选段函数选出的窗口必须落在 split_text 切出的单个场景块里（Fix 3）。"""
    heading = "第1回 標題1"
    body = gen_text(1, 2990) + "\n\n悟空說道，八戒和唐僧都在。\n\n" + gen_text(2, 2990)
    rng = random.Random(5)
    a, b = _pick_excerpt_span(heading, body, rng)
    file_text = f"{heading}\n\n{body}"
    blocks = split_text(file_text)
    containing = [blk for blk in blocks if blk.start <= a and b <= blk.end]
    assert containing, f"span [{a},{b}) not inside any single block; blocks={blocks}"
    assert 1200 <= b - a <= 2400 or (b - a) <= 2000  # 正常窗口或退回兜底截断


def test_variant_excerpts_within_single_block(tmp_path, monkeypatch):
    """整合测试：真跑一次 scramble（关掉 mutate），片段重写版的原文不能横跨两个场景块（Fix 3）。"""
    import tools.scramble as scr

    monkeypatch.setattr(scr, "mutate", lambda text, rng, *a, **k: text)
    out = tmp_path / "乱稿"
    key = scr.scramble(make_chapters(20), out, seed=3, **SMALL)
    for v in key["variants"]:
        if v["kind"] != "variant_excerpt":
            continue
        orig_text, _ = read_text(out / v["original_file"])
        excerpt_text, _ = read_text(out / v["file"])
        start = orig_text.find(excerpt_text)
        assert start != -1, f"chapter {v['chapter']}: excerpt text not found verbatim in original"
        end = start + len(excerpt_text)
        blocks = split_text(orig_text)
        containing = [blk for blk in blocks if blk.start <= start and end <= blk.end]
        assert containing, f"chapter {v['chapter']} excerpt spans blocks: {blocks}"


def test_cli_writes_key_outside_folder(tmp_path):
    src = tmp_path / "book.txt"
    src.write_text(
        "\n".join(f"{c.heading}\n\n{c.body}\n" for c in make_chapters(30)), encoding="utf-8"
    )
    out = tmp_path / "乱稿"
    main(["--src", str(src), "--out", str(out), "--seed", "5"])
    key = json.loads((tmp_path / "乱稿-答案.json").read_text(encoding="utf-8"))
    assert key["chapters"] == 30
    assert not (out / "乱稿-答案.json").exists()


def test_main_accepts_custom_aliases(tmp_path):
    chapters = make_chapters(30)
    src = tmp_path / "book.txt"
    src.write_text("\n".join(f"{c.heading}\n{c.body}" for c in chapters), encoding="utf-8")
    aliases = tmp_path / "aliases.json"
    aliases.write_text(
        json.dumps([{"replaces": "八戒", "alias": "豬先生", "canonical": "豬八戒"}], ensure_ascii=False), encoding="utf-8"
    )
    out = tmp_path / "乱稿"
    main(["--src", str(src), "--out", str(out), "--seed", "5", "--aliases", str(aliases)])
    key = json.loads((tmp_path / "乱稿-答案.json").read_text(encoding="utf-8"))
    assert [a["alias"] for a in key["aliases"]] == ["豬先生"] and key["aliases"][0]["chapters"]


from tools.scramble import Chapter, plant_contradictions


def test_不给contradictions参数时行为不变(tmp_path):
    """②b 的乱稿重跑不能受影响。同样传空别名列表绕开默认别名表找不到源词的问题。"""
    from tools.scramble import main
    src = tmp_path / "book.txt"
    src.write_text("第一回 起头\n甲乙丙。\n" * 5 + "第二回 再来\n丁戊己。\n" * 5 +
                   "第三回 收尾\n庚辛壬。\n" * 5, encoding="utf-8")
    aliases = tmp_path / "aliases.json"
    aliases.write_text("[]", encoding="utf-8")
    out = tmp_path / "乱稿"
    main(["--src", str(src), "--out", str(out), "--aliases", str(aliases), "--n-delete", "0",
          "--n-truncate", "0", "--n-full", "0", "--n-excerpt", "0"])
    import json
    key = json.loads((tmp_path / "乱稿-答案.json").read_text(encoding="utf-8"))
    assert key["contradictions"] == []


# --------------------------------------------------------------------------------------
# C1（9-20 GHIJ 审查）：锚点表繁简都认、配额分散、subject 不再恒为空
# --------------------------------------------------------------------------------------

def _read_piece(path, encoding: str) -> str:
    """按答案里记的编码读一个乱稿文件。docx 也要读——跳过它会让「新值搜不到」的断言出现
    盲区：植入落在一个恰好被写成 docx 的章节时，跳过等于默认它没问题（9-21 扫 30 个种子
    时先被这个盲区骗出过 4 个假缺失）。"""
    if encoding == "docx":
        from docx import Document
        return "\n".join(x.text for x in Document(path).paragraphs)
    return path.read_text(encoding=encoding)


# ==== 新植入策略（2026-09-21 重写）====
# 旧实现「把原文里的一个词换成另一个词」造不出矛盾：矛盾需要两处说法并存，而替换改掉的
# 是原值。真跑《雪月梅传》实测 10 处植入里 7 处从来就不是矛盾（docs/验收记录/2026-09-21）。
# 新实现：给指定人物在两个不同章节各插一句年龄陈述、数值不同，主语一定相同、两处说法一定并存。

CHARS = [
    {"canonical": "岑秀", "names": ["岑秀", "岑公子"]},
    {"canonical": "劉電", "names": ["劉電", "劉生"]},
    {"canonical": "小梅", "names": ["小梅"]},
]


def _chapters_with(names, n=8):
    """造 n 回，每回正文里带一个人名。"""
    out = []
    for i in range(1, n + 1):
        who = names[(i - 1) % len(names)]
        out.append(Chapter(i, f"第{i}回", f"這日天氣晴和。{who}生得丰神俊雅，氣宇不凡。眾人都不做聲。"))
    return out


def test_植入造出的是一对并存的说法():
    """核心：一处植入 = 同一个人、两个不同章节、两个不同的值。
    只有两处说法并存才构成矛盾——这正是旧实现缺的东西。"""
    chapters = _chapters_with(["岑秀"], 6)
    planted = plant_contradictions(chapters, random.Random(1), n=1, characters=CHARS)
    assert len(planted) == 1
    p = planted[0]
    assert p["subject"] == "岑秀"
    assert p["attribute"] == "年龄"
    assert len(p["chapters"]) == 2 and p["chapters"][0] != p["chapters"][1]
    assert len(p["values"]) == 2 and p["values"][0] != p["values"][1]
    bodies = {c.num: c.body for c in chapters}
    for ch, val in zip(p["chapters"], p["values"]):
        assert val in bodies[ch], f"第 {ch} 回正文里应该有值 {val}"
        assert "岑秀" in bodies[ch]


def test_两个值差得够远():
    """十六 vs 十七 会被判成合理变化，拉不开的差距测不出东西。"""
    chapters = _chapters_with(["岑秀"], 8)
    planted = plant_contradictions(chapters, random.Random(3), n=1, characters=CHARS)
    p = planted[0]
    assert abs(p["ages"][0] - p["ages"][1]) >= 4


def test_年龄跟时间方向反着来_前面的章节岁数更大():
    """9-21 第二轮真跑：前面写 16 岁、后面写 24 岁，模型判「合理变化」是对的——书里时间
    本来就在往前走，这处白植了。要造真正的矛盾就得让年龄倒退：前面的章节岁数大、后面的小。"""
    for seed in range(30):
        chapters = _chapters_with(["岑秀", "劉電"], 10)
        for p in plant_contradictions(chapters, random.Random(seed), n=2, characters=CHARS):
            assert p["chapters"][0] < p["chapters"][1]
            assert p["ages"][0] > p["ages"][1], f"seed={seed} {p}"
            bodies = {c.num: c.body for c in chapters}
            for ch, val in zip(p["chapters"], p["values"]):
                assert f"年方{val}" in bodies[ch]


def test_没有人物名单时不硬植入():
    chapters = _chapters_with(["岑秀"], 6)
    assert plant_contradictions(chapters, random.Random(1), n=3, characters=[]) == []


def test_人物在书里只出现一个章节时跳过():
    """只有一个章节提到这个人，插不出两处并存的说法，得跳过他而不是硬插。"""
    chapters = [Chapter(1, "第一回", "岑秀生得丰神俊雅。"),
                Chapter(2, "第二回", "這日天氣晴和。")]
    planted = plant_contradictions(chapters, random.Random(1), n=3, characters=CHARS)
    assert planted == []


def test_一个章节最多参与一处植入():
    chapters = _chapters_with(["岑秀", "劉電", "小梅"], 8)
    planted = plant_contradictions(chapters, random.Random(2), n=3, characters=CHARS)
    used = [ch for p in planted for ch in p["chapters"]]
    assert len(used) == len(set(used)), "同一个章节被两处植入用了"


def test_插入的句子跟着正文的字形走():
    """繁体语料插繁体「歲」，简体语料插简体「岁」——简体新词混在繁体段落里是明显的人造痕迹（C1）。"""
    trad = _chapters_with(["岑秀"], 6)
    planted = plant_contradictions(trad, random.Random(1), n=1, characters=CHARS)
    body = next(c.body for c in trad if c.num == planted[0]["chapters"][0])
    assert "歲" in body and "岁" not in body

    simp = [Chapter(i, f"第{i}回", f"这日天气晴和。岑秀生得丰神俊雅，气宇不凡。")
            for i in range(1, 7)]
    planted2 = plant_contradictions(simp, random.Random(1), n=1, characters=CHARS)
    body2 = next(c.body for c in simp if c.num == planted2[0]["chapters"][0])
    assert "岁" in body2 and "歲" not in body2


def test_植入不落在被删或被截断的章节(tmp_path):
    chapters = _chapters_with(["岑秀", "劉電", "小梅"], 20)
    out = tmp_path / "乱稿"
    key = scramble(chapters, out, seed=1, n_delete=2, n_truncate=8, n_full=0, n_excerpt=0,
                   alias_chapters=0, aliases=[], n_contradictions=3, characters=CHARS)
    bad = set(key["deleted"]) | {t["chapter"] for t in key["truncated"]}
    used = {ch for p in key["contradictions"] for ch in p["chapters"]}
    assert used and not (used & bad)


def test_答案里每处矛盾的两个值在乱稿正文里都搜得到(tmp_path):
    """端到端：打开输出文件核字。这是「花了钱才发现召回上限不是 10/10」的最后一道闸。"""
    chapters = _chapters_with(["岑秀", "劉電", "小梅"], 20)
    out = tmp_path / "乱稿"
    key = scramble(chapters, out, seed=1, n_delete=2, n_truncate=8, n_full=0, n_excerpt=0,
                   alias_chapters=0, aliases=[], n_contradictions=3, characters=CHARS)
    by_ch: dict[int, list] = {}
    for f in key["files"]:
        by_ch.setdefault(f["chapter"], []).append(f)
    for p in key["contradictions"]:
        for ch, val in zip(p["chapters"], p["values"]):
            body = "".join(
                _read_piece(out / f["path"], f["encoding"])
                for f in sorted(by_ch[ch], key=lambda x: x["piece"])
            )
            assert val in body, f"第 {ch} 回植入的 {val} 在乱稿正文里搜不到"
            assert p["subject"] in body or any(nm in body for nm in p.get("names", [])), \
                f"第 {ch} 回搜不到主语 {p['subject']}"


def test_n为0时真的不植入且正文一个字没变_新版():
    chapters = _chapters_with(["岑秀"], 6)
    before = [c.body for c in chapters]
    assert plant_contradictions(chapters, random.Random(1), n=0, characters=CHARS) == []
    assert [c.body for c in chapters] == before


def test_植入避开会被别名替换掉的人物(tmp_path):
    """别名替换在植入之后跑，会把插入句里的人名一起换掉：答案记「雪姐年方二十」，
    正文里却是「玉霜娘年方二十」，主语对不上，这处植入成不成还要看实体合并有没有把
    两个名字并到一起——引入了跟矛盾扫描无关的变量。9-21 真语料上实测撞到过（雪姐 ch8）。
    修法：名字会被别名替换的人物，直接不拿来植入。"""
    chapters = _chapters_with(["岑秀", "劉電", "小梅"], 20)
    aliases = [{"replaces": "劉電", "alias": "雷公將", "canonical": "劉電"}]
    out = tmp_path / "乱稿"
    key = scramble(chapters, out, seed=1, n_delete=2, n_truncate=4, n_full=0, n_excerpt=0,
                   alias_chapters=6, aliases=aliases, n_contradictions=3, characters=CHARS)
    assert key["contradictions"], "这个用例要真植入了才有意义"
    assert all(p["subject"] != "劉電" for p in key["contradictions"]), \
        "劉電 会被替换成雷公將，不该拿来当植入的主语"

    by_ch: dict[int, list] = {}
    for f in key["files"]:
        by_ch.setdefault(f["chapter"], []).append(f)
    for p in key["contradictions"]:
        for ch in p["chapters"]:
            body = "".join(_read_piece(out / f["path"], f["encoding"])
                           for f in sorted(by_ch[ch], key=lambda x: x["piece"]))
            assert p["subject"] in body, f"第 {ch} 回搜不到主语 {p['subject']}"


# --------------------------------------------------------------------------------------
# 9-28 换书验收（斗破苍穹，简体网文）才发现的三个坑，补在 Task17-19 之前
# --------------------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DOUPO_TXT = DATA_DIR / "斗破苍穹-前100章.txt"
DOUPO_CHARS = DATA_DIR / "人物-斗破.json"


def test_HEADING_认阿拉伯数字章_小样例():
    raw = "第1章 起头\n甲乙丙。\n\n第2章 再来\n丁戊己。\n"
    chapters = parse_chapters(raw)
    assert [c.heading for c in chapters] == ["第1章 起头", "第2章 再来"]


def test_HEADING_认汉字数字章_小样例():
    raw = "第一章 起头\n甲乙丙。\n\n第二章 再来\n丁戊己。\n"
    chapters = parse_chapters(raw)
    assert [c.heading for c in chapters] == ["第一章 起头", "第二章 再来"]


def test_HEADING_仍然认回_没有破坏原来的西游记雪月梅语料():
    raw = "第一回 起头\n甲乙丙。\n\n第二回 再来\n丁戊己。\n"
    chapters = parse_chapters(raw)
    assert [c.heading for c in chapters] == ["第一回 起头", "第二回 再来"]


def test_HEADING_斗破苍穹真实文件_100章():
    if not DOUPO_TXT.exists():
        pytest.skip("data/ 不在 CI 里")
    raw = strip_gutenberg(DOUPO_TXT.read_text(encoding="utf-8"))
    chapters = parse_chapters(raw)
    assert len(chapters) == 100
    assert chapters[0].heading == "第1章 陨落的天才"


def test_mutate_简体输入不混入繁体填充句():
    """FILLERS/SUBS 原来写死繁体，简体正文会被塞进「眾人都不做聲」这类繁体句子——
    这正好污染我们要测的「简体稿会不会冒繁体」。"""
    text = "岑秀道你好。" * 40  # 全是通用汉字，_script_of 判不出繁简，按平局规则落到 simp
    rng = random.Random(1)
    result = mutate(text, rng, drop=0.0, modify=0.0, add=1.0)
    assert "眾" not in result and "聲" not in result and "無" not in result and "這" not in result


def test_mutate_繁体输入不混入简体填充句():
    text = "劉電道你好。" * 40  # 劉 是繁体专属字，_script_of 判成 trad
    rng = random.Random(1)
    result = mutate(text, rng, drop=0.0, modify=0.0, add=1.0)
    assert "众" not in result and "声" not in result and "无" not in result


class FakeRngFirst:
    """random() 按固定序列吐值，choice 永远取第一个元素——逼 mutate 走 modify 分支、
    且总选中 SUBS 列表里的第一条替换规则，用来核对简繁两套替换值分别对不对。"""

    def __init__(self, values):
        self.values = list(values)
        self.i = 0

    def random(self):
        v = self.values[self.i]
        self.i += 1
        return v

    def choice(self, seq):
        return seq[0]


def test_mutate_简体替换值不带繁体字():
    text = "岑秀道：你好。"  # 通用汉字，判成 simp；SUBS_SIMP[0] = ("道：", "说道：")
    result = mutate(text, FakeRngFirst([0.5, 0.9]), drop=0.0, modify=1.0, add=0.0)
    assert "说道：" in result and "說道：" not in result


def test_mutate_繁体替换值不带简体字():
    text = "劉電道：你好。"  # 劉 是繁体专属字，判成 trad；SUBS_TRAD[0] = ("道：", "說道：")
    result = mutate(text, FakeRngFirst([0.5, 0.9]), drop=0.0, modify=1.0, add=0.0)
    assert "說道：" in result and "说道：" not in result


from tools.scramble import _speaks  # noqa: E402


def test_speaks_网文写法_隔着逗号也算():
    assert _speaks("萧炎微微一笑，道：你好。", "萧炎")
    assert _speaks("药老淡淡的道。", "药老")


def test_speaks_古典白话紧贴写法仍然认():
    assert _speaks("岑秀道：「好。」", "岑秀")


def test_speaks_跨句号不算():
    assert not _speaks("萧炎走了很远的路。有人道：你好。", "萧炎")


def test_speaks_超过12字不算():
    assert not _speaks("萧炎" + "甲" * 12 + "道。", "萧炎")


def test_speaks_没有这个名字():
    assert not _speaks("这里谁也没提到。", "萧炎")


def test_speaks_斗破苍穹真实文本_至少5人各有5章说过话():
    if not (DOUPO_TXT.exists() and DOUPO_CHARS.exists()):
        pytest.skip("data/ 不在 CI 里")
    chapters = parse_chapters(strip_gutenberg(DOUPO_TXT.read_text(encoding="utf-8")))
    people = json.loads(DOUPO_CHARS.read_text(encoding="utf-8"))
    counts = {}
    for p in people:
        names = [n for n in (p.get("names") or [p["canonical"]]) if n]
        counts[p["canonical"]] = sum(
            1 for c in chapters if any(_speaks(c.body, nm) for nm in names)
        )
    qualifying = {k: v for k, v in counts.items() if v >= 5}
    assert len(qualifying) >= 5, counts


# --------------------------------------------------------------------------------------
# Task 17: 乱稿工具——A 类植入（时间线检查验收）
# --------------------------------------------------------------------------------------

from tools.scramble import plant_deaths  # noqa: E402


def _talk_chapters(n):
    # 岑秀只在奇数章出场说话，劉電只在偶数章出场说话（各占约一半章节，都在 M1 新加的
    # MAIN_CHAR_FRACTION=0.6 门槛以内）；正文不带引号——原来「岑秀道：「好。」」这种写法
    # 名字后唯一的句末标点就落在别人台词的引号里，M3 修完之后（插入点必须在引号外）这个
    # 位置永远拿不到合法插入点，这份 fixture 本身就是 M3 要修的那种 bug 的活教材。
    out = []
    for i in range(1, n + 1):
        if i % 2 == 1:
            out.append(Chapter(i, f"第{i}回", "這日天氣晴和。岑秀笑道，心情甚好。眾人都不做聲。"))
        else:
            out.append(Chapter(i, f"第{i}回", "這日天氣晴和。劉電也笑道，甚是欣慰。眾人都不做聲。"))
    return out


def test_A植入_前一章插死亡_后一章他有对话_答案记两章():
    chapters = _talk_chapters(8)
    got = plant_deaths(chapters, random.Random(1), n=1, characters=CHARS, used=set())
    assert len(got) == 1
    p = got[0]
    a, b = p["chapters"]
    assert p["kind"] == "A" and a < b
    bodies = {c.num: c.body for c in chapters}
    assert f"{p['name']}染病身亡。" in bodies[a]
    # b 章里他有对话：新 fixture（M3 修复后）用的是网文式「名字，……笑道」而不是旧的
    # 「名字+道」紧贴写法，直接断言 _speaks() 成立才是这条测试真正要保证的东西，
    # 不该绑死某一种具体写法的字面子串（M1/M3 修复导致的必要断言更新，见报告）。
    assert _speaks(bodies[b], p["name"])


def test_A植入_答案记下死后他还说过话的所有章():
    # 10-01：人死了以后任何一场再出场说话都是冲突，判卷不该只认紧挨着的那一章。
    # 岑秀在奇数章说话：在第 a 章死，答案的 speaks_in 就是 a 之后所有奇数章（跳过的章不算）。
    chapters = _talk_chapters(9)
    got = plant_deaths(chapters, random.Random(1), n=1, characters=CHARS, used=set(), skip={9})
    p = got[0]
    a = p["chapters"][0]
    want = [n for n in range(a + 1, 9) if (n % 2 == 1) == (p["who"] == "岑秀")]
    assert p["speaks_in"] == want and p["chapters"][1] in want


def test_A植入_用过的章节不再用_跳过的章节不用():
    chapters = _talk_chapters(8)
    used = {1, 2, 3}
    got = plant_deaths(chapters, random.Random(2), n=2, characters=CHARS, used=used, skip={8})
    for p in got:
        assert not set(p["chapters"]) & {1, 2, 3, 8}
    assert len(used) == 3 + 2 * len(got)  # 用过的会记进 used


def test_A植入_没人物名单不植():
    assert plant_deaths(_talk_chapters(4), random.Random(1), n=3, characters=[], used=set()) == []


# --------------------------------------------------------------------------------------
# Task 18: 乱稿工具——C 类植入 + 接进 scramble / CLI
# --------------------------------------------------------------------------------------

from tools.scramble import plant_foreknowledge  # noqa: E402


def test_C植入_在事件章之前某章插回忆_答案记两章():
    chapters = _talk_chapters(8)
    events = [{"chapter": 6, "who": "岑秀", "event": "比箭連中三箭"}]
    got = plant_foreknowledge(chapters, random.Random(1), n=1, events=events, used=set())
    p = got[0]
    a, b = p["chapters"]
    assert p["kind"] == "C" and a < b == 6
    assert "岑秀想起那日比箭連中三箭之事。" in {c.num: c.body for c in chapters}[a]


def test_C植入_事件跨几章_答案记范围_没给范围就是单章():
    # 10-01：一件事常常跨好几章（斗破「去拍卖场」20–24 章），答案只记一章会把模型挑对的别章判错。
    chapters = _talk_chapters(8)
    events = [{"chapter": 5, "span": [5, 7], "who": "岑秀", "event": "比箭"}]
    p = plant_foreknowledge(chapters, random.Random(1), n=1, events=events, used=set())[0]
    assert p["span"] == [5, 7] and p["chapters"][0] < 5
    chapters = _talk_chapters(8)
    p = plant_foreknowledge(chapters, random.Random(1), n=1, events=[{"chapter": 6, "who": "岑秀", "event": "甲"}],
                            used=set())[0]
    assert p["span"] == [6, 6]


def test_C植入_事件章被占用或跳过就换一条():
    chapters = _talk_chapters(8)
    events = [{"chapter": 6, "who": "岑秀", "event": "甲"}, {"chapter": 7, "who": "岑秀", "event": "乙"}]
    got = plant_foreknowledge(chapters, random.Random(1), n=2, events=events, used={6})
    assert [p["event"] for p in got] == ["乙"]


def test_scramble_答案里带timeline(tmp_path):
    """接进 scramble()：--deaths / --foreknowledge 植入的记在答案的 timeline 里。"""
    from tools.scramble import scramble
    chapters = _talk_chapters(20)
    key = scramble(chapters, tmp_path / "out", 7, aliases=[], n_delete=1, n_truncate=1, n_full=1, n_excerpt=1,
                   n_deaths=1, n_foreknowledge=1, characters=CHARS,
                   events=[{"chapter": 15, "who": "岑秀", "event": "比箭"}])
    kinds = sorted(p["kind"] for p in key["timeline"])
    # seed=7 这套材料实测两类都能植上（9-28 扫了 seed 0-49，只有少数几个种子因为删章/截断
    # 刚好吃掉事件章而只剩一种），断言收紧成 == ["A", "C"]，比原计划写宽的三选一更能测出东西。
    assert kinds == ["A", "C"]
    assert all(set(p["chapters"]).isdisjoint(key["deleted"]) for p in key["timeline"])


# --------------------------------------------------------------------------------------
# 审 2（F1 之后）修复：B1/M1/M3/S2/S3/S4/S6 + 补测 T5/T6/T8/T9
# --------------------------------------------------------------------------------------

from tools.scramble import _insertion_point, _in_quote, _appearances  # noqa: E402


def test_M1_a和b之间没有他别的出场章_小样例():
    """②b M1：b 必须是 a 之后这个人第一次再出场的章，中间不能有他别的出场章。"""
    for seed in range(20):
        chapters = _talk_chapters(20)
        got = plant_deaths(chapters, random.Random(seed), n=3, characters=CHARS, used=set())
        appear = {"岑秀": _appearances(chapters, ["岑秀"]), "劉電": _appearances(chapters, ["劉電"])}
        for p in got:
            a, b = p["chapters"]
            mine = appear[p["who"]]
            between = [c for c in mine if a < c < b]
            assert between == [], (seed, p, between)


def test_M1_出场章数超过60比例的人不用():
    """岑秀在 18/20 = 90% 的章节里出场，超过 MAIN_CHAR_FRACTION，不该被用于 A 类植入。"""
    chapters = _talk_chapters(20)
    for i in range(1, 19):  # 补插到几乎每章都出场（保留 19、20 两章不出场，够 appear>=2 判定）
        if chapters[i - 1].num not in (19, 20) and "岑秀" not in chapters[i - 1].body:
            chapters[i - 1].body += "岑秀笑道，心情甚好。"
    got = plant_deaths(chapters, random.Random(1), n=5, characters=CHARS, used=set())
    assert all(p["who"] != "岑秀" for p in got)


def test_M1_斗破真文件_A植入a和b之间没有他别的出场章():
    if not (DOUPO_TXT.exists() and DOUPO_CHARS.exists()):
        pytest.skip("data/ 不在 CI 里")
    chapters = parse_chapters(strip_gutenberg(DOUPO_TXT.read_text(encoding="utf-8")))
    people = json.loads(DOUPO_CHARS.read_text(encoding="utf-8"))
    for seed in range(10):
        got = plant_deaths(list(chapters), random.Random(seed), n=5, characters=people, used=set())
        appear_cache: dict[str, list[int]] = {}
        for p in got:
            a, b = p["chapters"]
            assert a < b
            if p["who"] not in appear_cache:
                names = next(pp.get("names") or [pp["canonical"]] for pp in people if pp["canonical"] == p["who"])
                appear_cache[p["who"]] = _appearances(chapters, [n for n in names if n])
            between = [c for c in appear_cache[p["who"]] if a < c < b]
            assert between == [], (seed, p, between)


def test_M3_插入点不落在引号里_死亡植入():
    """b 章原有的唯一名字提及后面紧跟别人的台词引号，a 章（另一处提及）在引号外才能用。
    多垫两章空白（不提岑秀）把出场比例压到 60% 以内，不然会被 M1 的主角门槛排除。"""
    quoted = Chapter(1, "第1回", "這日岑秀道：「我很好。」")  # 名字后唯一句末标点在引号内
    plain = Chapter(2, "第2回", "岑秀神情淡然，心中自有计较。")  # 引号外有合法插入点
    speak = Chapter(3, "第3回", "岑秀笑道，心中甚喜。")
    filler1 = Chapter(4, "第4回", "这日风平浪静，无事发生。")
    filler2 = Chapter(5, "第5回", "又过了几日，仍是平淡。")
    got = plant_deaths([quoted, plain, speak, filler1, filler2], random.Random(1), n=1,
                       characters=CHARS, used=set())
    assert len(got) == 1
    a = got[0]["chapters"][0]
    assert a != 1  # 只有引号里那处提及的章节不能被选为死亡植入的 a 章
    a_body = {1: quoted, 2: plain, 3: speak}[a].body
    assert not _in_quote(a_body, a_body.find("染病身亡"))


def test_M3_插入点必须在引号外_单元测试():
    body = "他望着岑秀道：「岑秀，你可安好？」岑秀转身离去，不再看他。"
    cut = _insertion_point(body, "岑秀")
    assert cut is not None
    assert not _in_quote(body, cut)
    # 找到的是最后一次在引号外提到的那句之后（rfind 方向），不是第一次
    assert body[:cut].rstrip().endswith("不再看他。")


def test_M3_只在引号里出现就找不到插入点():
    assert _insertion_point("他望着岑秀道：「岑秀，你好。」", "岑秀") is None


def test_M3_植入的年龄矛盾也不落在引号里():
    chapters = [
        Chapter(1, "第1回", "有人问岑秀道：「岑秀，你多大了？」"),  # 唯一的句末标点在引号内，没有合法插入点
        Chapter(2, "第2回", "岑秀答道，语气平静。"),
        Chapter(3, "第3回", "岑秀神情自若，未曾多言。"),
    ]
    planted = plant_contradictions(chapters, random.Random(1), n=1, characters=CHARS)
    assert len(planted) == 1
    assert set(planted[0]["chapters"]) <= {2, 3}  # 引号里那章（1）不该被选中
    for ch, val in zip(planted[0]["chapters"], planted[0]["values"]):
        body = next(c.body for c in chapters if c.num == ch)
        pos = body.find(val)
        assert pos != -1 and not _in_quote(body, pos)


def test_S2_speaks排除所说知道难道一道说不():
    assert not _speaks("纳兰嫣然所说的话，又能怎样", "纳兰嫣然")
    assert not _speaks("萧炎肩膀之上，顿时留下一道长痕", "萧炎")
    assert not _speaks("萧薰儿哥哥难道不知道这些", "萧薰儿")
    assert not _speaks("萧宁却是知道，无奈叹气", "萧宁")
    assert not _speaks("加列毕那家伙老奸巨猾说不出话", "加列毕")


def test_S2_speaks窗口内有别人名字就不算():
    text = "萧炎望着萧媚，柔声道：你好。"
    assert not _speaks(text, "萧炎", other_names=frozenset({"萧媚"}))
    assert _speaks(text, "萧炎")  # 不传 other_names 时按原逻辑，仍然算


def test_S3_植入不落在full或excerpt变体章(tmp_path):
    chapters = _chapters_with(["岑秀", "劉電", "小梅"], 30)
    out = tmp_path / "乱稿"
    key = scramble(chapters, out, seed=4, n_delete=0, n_truncate=3, n_full=4, n_excerpt=3,
                   alias_chapters=0, aliases=[], n_contradictions=3, characters=CHARS,
                   n_deaths=2, n_foreknowledge=0)
    variant_nums = {v["chapter"] for v in key["variants"] if v["kind"] in ("variant_full", "variant_excerpt")}
    used = {ch for p in key["contradictions"] for ch in p["chapters"]} | \
           {ch for p in key["timeline"] for ch in p["chapters"]}
    assert used and not (used & variant_nums)


def test_S4_foreknowledge避开会被别名替换的人():
    chapters = _talk_chapters(20)
    for c in chapters:
        c.body += "劉電近日行踪不定。"  # 让「劉電」在每章都出现，事件才有的用
    events = [{"chapter": 15, "who": "劉電", "event": "比箭"}]
    got = plant_foreknowledge(chapters, random.Random(1), n=1, events=events, used=set(),
                              avoid={"劉電"})
    assert got == []


def test_S6_mutate传script时不再自己判繁简():
    # 单独这一小段文字（不传 script）会被 _script_of 判成简体（无繁体专属字）；
    # 传 script="trad" 之后必须用繁体的填充句/替换值，不能再自己判。
    text = "岑秀道：你好。"
    result = mutate(text, FakeRngFirst([0.5, 0.9]), drop=0.0, modify=1.0, add=0.0, script="trad")
    assert "說道：" in result and "说道：" not in result


def test_S6_scramble里excerpt字形跟全书一致不跟片段自己判(tmp_path):
    # 全书基本是繁体（劉電名字本身就是繁体专属字），但被选中做 excerpt 的那一章如果本身
    # 巧合只有通用汉字，旧实现会把它自己判成简体、混入简体填充句；新实现全书统一判一次。
    chapters = [Chapter(i, f"第{i}回", f"這日岑秀劉電同行，{('岑秀' if i % 2 else '劉電')}神情自若。") for i in range(1, 21)]
    out = tmp_path / "乱稿"
    key = scramble(chapters, out, seed=9, n_delete=0, n_truncate=0, n_full=0, n_excerpt=5,
                   alias_chapters=0, aliases=[])
    for v in key["variants"]:
        text, _ = read_text(out / v["file"])
        assert "众" not in text and "这" not in text and "众人" not in text


def test_T5_A植入_a总是早于b_扫多个种子():
    for seed in range(30):
        chapters = _talk_chapters(20)
        got = plant_deaths(chapters, random.Random(seed), n=3, characters=CHARS, used=set())
        for p in got:
            assert p["chapters"][0] < p["chapters"][1], (seed, p)


def test_T6_C植入_a总是早于b_扫多个种子():
    for seed in range(30):
        chapters = _talk_chapters(20)
        events = [{"chapter": ch, "who": "岑秀", "event": f"事{ch}"} for ch in range(3, 20, 2)]
        got = plant_foreknowledge(chapters, random.Random(seed), n=3, events=events, used=set())
        for p in got:
            assert p["chapters"][0] < p["chapters"][1], (seed, p)


def test_T8_C植入更新used集合():
    chapters = _talk_chapters(8)
    events = [{"chapter": 6, "who": "岑秀", "event": "甲"}]
    used = set()
    got = plant_foreknowledge(chapters, random.Random(1), n=1, events=events, used=used)
    assert used == {got[0]["chapters"][0], 6}


def test_T9_timeline植入不落在被截断的章节(tmp_path):
    chapters = _talk_chapters(30)
    out = tmp_path / "乱稿"
    key = scramble(chapters, out, seed=3, n_delete=0, n_truncate=6, n_full=0, n_excerpt=0,
                   alias_chapters=0, aliases=[], characters=CHARS, n_deaths=3, n_foreknowledge=2,
                   events=[{"chapter": ch, "who": "岑秀", "event": f"事{ch}"} for ch in range(5, 30, 3)])
    truncated_nums = {t["chapter"] for t in key["truncated"]}
    used_by_timeline = {ch for p in key["timeline"] for ch in p["chapters"]}
    assert used_by_timeline and not (used_by_timeline & truncated_nums)


