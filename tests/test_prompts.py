import pytest

from ligaotai.facts import ATTRS, OTHER, VALUE_LIMIT
from ligaotai.prompts import PROMPTS_DIR, render


def test_load_and_render(tmp_path):
    (tmp_path / "x.md").write_text(
        "说明文字\n\n## system\n你好 $who，价格 $$5\n\n## user\n正文：$text\n", encoding="utf-8"
    )
    assert render("x", tmp_path, who="作者", text="甲") == ("你好 作者，价格 $5", "正文：甲")


def test_missing_section(tmp_path):
    (tmp_path / "x.md").write_text("## system\n只有一段\n", encoding="utf-8")
    with pytest.raises(ValueError):
        render("x", tmp_path)


def test_missing_variable(tmp_path):
    (tmp_path / "x.md").write_text("## system\n$who\n## user\n$text\n", encoding="utf-8")
    with pytest.raises(KeyError):
        render("x", tmp_path, text="甲")


def test_real_cards_prompt():
    system, user = render("cards", scene_id="S-0001", source="稿/a.txt", heading="第一章", text="林清年方十六。")
    assert "json" in system and "场景卡" in system
    assert "S-0001" in user and "林清年方十六。" in user
    assert "$" not in system + user


def test_real_cards_prompt_has_pov_and_quote_rules():
    """作者批准的两条新规则：pov 没有明确视角人物就留空、不要写「第三人称/全知」；
    quote 不许用省略号/分号拼接几处原文。"""
    system, _ = render("cards", scene_id="S-0001", source="稿/a.txt", heading="第一章", text="林清年方十六。")
    assert "第三人称" in system
    assert "省略号" in system


def test_real_entities_prompt():
    system, user = render("entities", type_label="人物", names="- 林清（3 个场景）：林清年方十六", hints="（无）")
    assert "json" in system and "人物" in system and "归成一组" in system
    assert "林清" in user
    assert "$" not in system + user


THREAD_PROMPTS = [
    ("threads_worlds", {"unit_rule": "x", "known": "k", "lines": "l"}, "划分世界"),
    ("threads_lines", {"world": "w", "locked": "k", "lines": "l"}, "划分支线"),
    ("threads_order", {"thread": "t", "unit": "年", "segments": "s", "lines": "l"}, "线内排序"),
    ("threads_align", {"unit": "年", "main": "L-001", "threads": "t"}, "跨线对齐"),
    ("threads_gaps", {"world": "w", "threads": "t", "refs": "r"}, "找缺口"),
]


@pytest.mark.parametrize("name,values,mark", THREAD_PROMPTS)
def test_threads_prompts_render(name, values, mark):
    from ligaotai.prompts import render

    system, user = render(name, **values)
    assert "json" in system and mark in system
    assert "$" not in system + user
    others = [m for _, _, m in THREAD_PROMPTS if m != mark]
    assert not any(m in system for m in others)
    assert "而是" not in system  # 写给模型的话不用「不是A而是B」的句式


def test_threads_unit_rules_have_no_ershi():
    """threads.py 填进划世界提示词的两段时间单位规则，也不用「不是A而是B」的句式。"""
    from ligaotai.threads import UNIT_FIXED, UNIT_PROPOSE

    for rule in (UNIT_PROPOSE, UNIT_FIXED.format(unit="年")):
        system, _ = render("threads_worlds", unit_rule=rule, known="k", lines="l")
        assert rule in system and "而是" not in system


def test_threads_marks_not_in_older_prompts():
    from ligaotai.prompts import load_prompt

    for name in ("cards", "entities"):
        system, _ = load_prompt(name)
        assert not any(m in system.template for _, _, m in THREAD_PROMPTS)


# --- 提示词里的示例 json 送进对应的 check_*，必须一次过（review_t08 第 3 条）---
# 示例从提示词文件里现解析，不在这里抄一份：以后改提示词或检查函数改得对不上，这里当场抓到。

import json
import re

from ligaotai.fsutil import natural_key
from ligaotai.threads_check import check_align, check_gaps, check_lines, check_order, check_worlds

VALUES = {name: values for name, values, _ in THREAD_PROMPTS}


def _objects(text: str) -> list:
    """text 里能解析出来的顶层 json 对象，按出现顺序。"""
    dec = json.JSONDecoder()
    out, i = [], text.find("{")
    while i != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        out.append(obj)
        i = text.find("{", end)
    return out


def example(name: str) -> tuple[dict, list]:
    """(「格式如下」后面的示例, 规则里夹带的 json 片段)。"""
    system, _ = render(name, **VALUES[name])
    rules, tail = system.split("格式如下", 1)
    return _objects(tail)[0], _objects(rules)


def test_worlds_example_passes_check_on_first_run():
    ex, rules = example("threads_worlds")
    expected = {s for w in ex["worlds"] for s in w["scenes"]}
    assert expected
    assert check_worlds(ex, expected, set(), True, {}) == []  # 第一次跑：已有的世界是（无）
    # 规则里教的「归入已有的世界」写法：上面列了这个世界时，跟新世界写在一起也能过
    refs = [o for o in rules if "id" in o]
    assert refs
    known = {o["id"] for o in refs}
    expected |= {s for o in refs for s in o["scenes"]}
    data = {**ex, "worlds": ex["worlds"] + refs}
    assert check_worlds(data, expected, known, True, {k: "旧世界" for k in known}) == []


def test_lines_example_passes_check_on_first_run():
    ex, rules = example("threads_lines")
    ordered = {s for t in ex["threads"] for s in t.get("scenes", [])}
    outlines = {s for t in ex["threads"] for s in t.get("outlines", [])} | set(ex.get("world_outlines", []))
    assert ordered
    assert check_lines(ex, ordered, outlines, set(), {}) == []  # 第一次跑：已有的线是（无）
    # 规则里教的写法：归入已有的线、已有的主线这次没新块（scenes 空、标 main）
    refs = [o for o in rules if "id" in o]
    assert any(o.get("main") is True and o.get("scenes") == [] for o in refs)
    known = {o["id"] for o in refs}
    ordered |= {s for o in refs for s in o.get("scenes", [])}
    new = [{k: v for k, v in t.items() if k != "main"} for t in ex["threads"]]
    data = {**ex, "threads": new + refs}
    assert check_lines(data, ordered, outlines, known, {k: "旧线" for k in known}) == []
    # 规则 5 靠这个标记认已有的主线；T10 的已有线列表里主线那行要照这个写法带上
    assert "（主线）" in render("threads_lines", **VALUES["threads_lines"])[0]


def test_order_example_passes_check():
    ex, _ = example("threads_order")
    expected = set(ex["times"])
    assert all(k.startswith("S-") for k in expected)  # times 按场景编号给
    singles = [x for x in ex["order"] if x.startswith("S-")]
    segs_ids = [x for x in ex["order"] if x.startswith("P-")]
    assert len(segs_ids) <= 1, "示例里有几个片段时，这个测试要改成按片段分块"
    rest = sorted(expected - set(singles), key=natural_key)
    assert check_order(ex, {p: rest for p in segs_ids}, expected) == []


def test_align_example_passes_check():
    ex, _ = example("threads_align")
    main = VALUES["threads_align"]["main"]
    ids = {t["id"] for t in ex["threads"]}
    assert main in ids
    for t in ids | {c["thread"] for c in ex["intersections"]}:  # 线的编号写成线名这类回归，下面的推法抓不到
        assert re.fullmatch(r"L-\d{3}", t), t
    members: dict[str, set] = {t: set() for t in ids}
    for c in ex["intersections"]:
        members[c["thread"]].add(c["scene"])
        members[main].add(c["main_scene"])
    assert check_align(ex, ids, main, members) == []


def test_gaps_example_passes_check():
    ex, _ = example("threads_gaps")
    refs = {s for g in ex["gaps"] for s in g["mentioned_in"]}
    for g in ex["gaps"]:  # thread 写成线名这类回归，下面的推法抓不到
        assert g["thread"] is None or re.fullmatch(r"L-\d{3}", g["thread"]), g["thread"]
    lines: dict[str, set] = {}
    for g in ex["gaps"]:
        lines.setdefault(g["thread"], set()).update(x for x in (g.get("after"), g.get("before")) if x)
    ordered = {t: sorted(v, key=natural_key) for t, v in lines.items()}  # 线里的块按编号先后排
    assert check_gaps(ex, refs, ordered) == []


# --- 2c task05: 场景卡提示词与受控属性表一致 ---


def _cards_text() -> str:
    return (PROMPTS_DIR / "cards.md").read_text(encoding="utf-8")


def test_档案提示词渲染无残留变量():
    """archive_thread / archive_world / map 只有一个变量 $body（渲染好的输入正文），
    模板里给模型看的示例块用的是 L-001 / W-01 这类具体占位符，不是 $ 变量——
    这里跟一次渲染确认没有 Template 变量残留、也没混进 $ 字面量以外的坑。"""
    for name in ("archive_thread", "archive_world", "map"):
        system, user = render(name, body="正文示例 [S-0003]")
        assert "$" not in system + user
        assert "而是" not in system
        assert "正文示例" in user


def test_提示词里的受控属性表和代码一致():
    lines = _cards_text().splitlines()
    i = next(n for n, line in enumerate(lines) if "只能从下面这张表里挑一个" in line)
    assert lines[i + 1].strip().split("、") == list(ATTRS) + [OTHER]  # 逐项、顺序、无多余
    limits = re.findall(r"value 是\*\*短值\*\*，不超过 (\d+) 个字", _cards_text())
    assert limits == [str(VALUE_LIMIT)]


def test_提示词写明只记稳定设定且value写简体():
    text = _cards_text()
    assert "跨场景稳定的设定" in text and "一律不许进 facts" in text
    assert "value 一律写简体" in text


def test_cards_example_facts_follow_rules():
    system, _ = render("cards", scene_id="S-0001", source="稿/a.txt", heading="第一章", text="林清年方十六。")
    ex = _objects(system.split("格式如下", 1)[1])[0]
    assert ex["facts"]
    for f in ex["facts"]:
        assert f["attribute"] in (*ATTRS, OTHER)
        assert len(f["value"]) <= VALUE_LIMIT


# --- D 组审查后的待办 1：合理变化的措辞不能无条件把「换了兵器」算合理变化，
# 否则会漏掉验收植入的「金箍棒→降妖宝杖」样本（spec 9.1、Task 21）---

def _contradictions_system():
    system, _ = render("contradictions", unit="年", groups="G")
    return system


def test_合理变化措辞要求原文交代变化经过_不能无条件因为换了兵器就判合理():
    system = _contradictions_system()
    # 旧措辞「、换了兵器、」把换兵器无条件列为合理变化，跟验收植入的金箍棒→降妖宝杖正面冲突
    assert "、换了兵器、" not in system, "不能无条件把换兵器算合理变化"
    assert "写明换了兵器" in system, "只有原文交代了换兵器的来由才算合理变化"
    assert "没交代任何变化经过的，不算合理变化" in system


def test_合理变化措辞覆盖验收植入样本_金箍棒换降妖宝杖应能判成真矛盾():
    """spec 9.1 的植入方式：原文没有交代任何换兵器的经过，只是两处写了不同兵器名——
    按新措辞这种情况不算合理变化，不会被规则本身误导成"看到换兵器就想当然判合理"。"""
    system = _contradictions_system()
    assert "两个值之间原文没交代任何变化经过的" in system or "原文没交代任何变化经过的" in system


def test_提示词补了繁简写法不同的措辞_并带四海龙王东海龙王真不同的反例():
    system = _contradictions_system()
    assert "繁体" in system and "简体" in system
    assert "四海龍王" in system and "東海龍王" in system, "反例：只差一字就是真不同，不是繁简"


# --- DE 审查必须修3：世界设定集回填要按主语对规范名，规范名常是繁体；
# 提示词不能再叫模型把人名改成简体，属性节标题级别要说清 ---

def test_世界设定集提示词要求人名地名照材料原样抄_不改简体():
    system, _ = render("archive_world", body="B")
    assert "照材料原样抄" in system
    assert "不要改成简体" in system
    assert "## 属性名" in system or "二级标题" in system
