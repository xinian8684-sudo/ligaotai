import json
import random

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
