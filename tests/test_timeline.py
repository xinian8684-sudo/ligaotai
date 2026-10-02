def test_书有时间冲突的两个路径(book):
    assert book.timeline_path == book.root / "时间冲突.json"
    assert book.timeline_cache_path == book.root / "时间冲突缓存.json"


from ligaotai.fsutil import write_json
from ligaotai.timeline import story_order


def _threads(book, threads, global_order=None, unassigned=()):
    write_json(book.threads_path, {"threads": threads, "worlds": [], "main_thread": threads[0]["id"],
                                   "global_order": list(global_order or []), "unassigned": list(unassigned),
                                   "pending": [], "gaps": [], "intersections": []})


def _seed(book, specs):
    """specs: [(sid, persons, refs, facts, text)]。facts: [(subject, attribute, value, quote)]"""
    from helpers import seed_book
    from ligaotai.cards import card_path
    from ligaotai.fsutil import read_json
    seed_book(book, [{"id": s, "persons": p, "refs": r, "text": t} for s, p, r, _, t in specs])
    for s, _, _, facts, _ in specs:
        rec = read_json(card_path(book, s))
        rec["card"]["facts"] = [{"subject": a, "attribute": b, "value": c, "quote": q} for a, b, c, q in facts]
        write_json(card_path(book, s), rec)


def test_故事顺序按全书穿插_排不进的单独数(book):
    _seed(book, [(f"S-000{i}", [], [], [], "x") for i in range(1, 5)])
    _threads(book, [
        {"id": "L-001", "offset": 0, "scenes": ["S-0001", "S-0002"],
         "times": {"S-0001": {"t": 0}, "S-0002": {"t": 2}}},
        {"id": "L-002", "offset": 0, "scenes": ["S-0003", "S-0004"],
         "times": {"S-0003": {"t": 1}}},  # S-0004 没时间
    ], global_order=["S-0001", "S-0003", "S-0002"])
    seq, pos, unplaced, untracked = story_order(book)
    assert seq == ["S-0001", "S-0003", "S-0002"]
    assert pos == {"S-0001": 0, "S-0003": 1, "S-0002": 2}
    assert unplaced == 1
    assert untracked == 0  # 4 个块全都在某条线的 scenes 里，没有压根没提到的


def test_故事顺序_压根没被任何线或未定区提到的块单独计数(book):
    """场景文件存在，但既不在任何线的 scenes 里、也不在 unassigned 里（比如挂在世界上的
    设定笔记、只在 outlines 里的提纲）：不算「排不进时间轴」（unplaced），单独计数。"""
    _seed(book, [(f"S-000{i}", [], [], [], "x") for i in range(1, 6)])
    _threads(book, [
        {"id": "L-001", "offset": 0, "scenes": ["S-0001", "S-0002"],
         "times": {"S-0001": {"t": 0}, "S-0002": {"t": 1}}},
    ], unassigned=["S-0003"])
    seq, pos, unplaced, untracked = story_order(book)
    assert seq == ["S-0001", "S-0002"]
    assert unplaced == 1  # S-0003 在 unassigned 里
    assert untracked == 2  # S-0004、S-0005 压根没被提到


def test_故事顺序_已移除的块不排进去(book):
    from ligaotai.scenes import get_scene, write_scene
    _seed(book, [("S-0001", [], [], [], "x"), ("S-0002", [], [], [], "y")])
    sc = get_scene(book, "S-0002")
    sc.removed = True
    write_scene(book, sc)
    _threads(book, [{"id": "L-001", "offset": 0, "scenes": ["S-0001", "S-0002"],
                     "times": {"S-0001": {"t": 0}, "S-0002": {"t": 1}}}])
    seq, pos, unplaced, untracked = story_order(book)
    assert seq == ["S-0001"]


def test_故事顺序_版本组非主成员换成当前主版本(book):
    from helpers import seed_book
    seed_book(book, [{"id": "S-0001", "text": "旧版本"}, {"id": "S-0002", "text": "新主版本"}],
              groups=[("S-0002", ["S-0001", "S-0002"])])
    _threads(book, [{"id": "L-001", "offset": 0, "scenes": ["S-0001"], "times": {"S-0001": {"t": 0}}}])
    seq, pos, unplaced, untracked = story_order(book)
    assert seq == ["S-0002"]  # 线里引用的是旧主版本 S-0001，换成当前主版本 S-0002 才不会整组消失


def test_故事顺序_版本组主版本字段坏了整组丢(book):
    from helpers import seed_book
    seed_book(book, [{"id": "S-0001", "text": "a"}, {"id": "S-0002", "text": "b"}])
    write_json(book.versions_path, {"params": {}, "groups": [
        {"id": "G-001", "members": ["S-0001", "S-0002"], "main": None, "main_by": "auto", "pairs": []}]})
    _threads(book, [{"id": "L-001", "offset": 0, "scenes": ["S-0001", "S-0002"],
                     "times": {"S-0001": {"t": 0}, "S-0002": {"t": 1}}}])
    seq, pos, unplaced, untracked = story_order(book)
    assert seq == []


from ligaotai.timeline import is_death


def test_哪些fact算死了():
    yes = [("生死", "已死"), ("生死", "被文進刺死"), ("生死", "阵亡"), ("生死", "已歸天"),
           ("生死", "梟首傳示江浙"), ("身份", "已故封君"), ("其他", "得病身故"), ("伤病", "病故"),
           ("生死", "已去世好幾年"), ("生死", "本月十九日坐化了")]
    no = [("生死", "免死編氓"), ("生死", "被擒"), ("生死", "嚴行監禁"), ("生死", "車囚"),
          ("生死", "丁艱"), ("亲属", "母已亡"), ("身份", "亡命之徒"), ("性格", "视死如归"),
          ("生死", "幾乎死了"), ("生死", "未死"),
          ("身份", "军中士卒"), ("身份", "兵卒一名"), ("身份", "狱卒"), ("身份", "獄卒出身"),
          ("身份", "市井走卒"), ("生死", "打入死囚牢"), ("生死", "畏罪逃亡"),
          ("生死", "诈死脱身"), ("生死", "詐死脱身"), ("生死", "假死躲过一劫"),
          ("生死", "重伤昏迷，死活不明"), ("生死", "生死不明"), ("生死", "不知死活"), ("生死", "存亡未卜")]
    for a, v in yes:
        assert is_death(a, v), (a, v)
    for a, v in no:
        assert not is_death(a, v), (a, v)


from ligaotai.timeline import death_suspects


def _cards(spec):
    """spec: {sid: (persons, facts)}，facts: [(subject, attribute, value, quote)]"""
    return {s: {"id": s, "card": {"characters": [{"name": n} for n in p],
                                  "facts": [{"subject": a, "attribute": b, "value": c, "quote": q} for a, b, c, q in f],
                                  "refs_elsewhere": []}}
            for s, (p, f) in spec.items()}


def test_A嫌疑_死后出现在人物名单里_别名归一_取最早的死亡(book):
    seq = ["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"]
    pos = {s: i for i, s in enumerate(seq)}
    cmap = {("person", "劉公"): "劉芳", ("person", "劉芳"): "劉芳"}
    cards = _cards({
        "S-0001": (["劉芳"], []),
        "S-0002": (["劉公"], [("劉公", "生死", "已死", "劉公已死多年")]),
        "S-0003": (["張三"], []),
        "S-0004": (["劉芳"], [("劉芳", "生死", "已死", "劉芳死了")]),  # 更晚的死亡记录不另算
        "S-0005": (["劉公"], []),
    })
    got, capped = death_suspects(seq, pos, cards, cmap)
    assert [(x["who"], x["death"], x["later"]) for x in got] == [
        ("劉芳", "S-0002", "S-0004"), ("劉芳", "S-0002", "S-0005")]
    assert got[0]["death_quote"] == "劉公已死多年"
    assert capped == 0


def test_A嫌疑_每人最多取离死亡最近的5场():
    seq = [f"S-{i:04d}" for i in range(1, 10)]
    pos = {s: i for i, s in enumerate(seq)}
    spec = {s: (["甲"], []) for s in seq}
    spec["S-0001"] = (["甲"], [("甲", "生死", "已死", "甲已死")])
    got, capped = death_suspects(seq, pos, _cards(spec), {})
    assert [x["later"] for x in got] == ["S-0002", "S-0003", "S-0004", "S-0005", "S-0006"]
    assert capped == 3


def test_A嫌疑_死亡场不在故事顺序里就不查():
    seq = ["S-0002"]
    pos = {"S-0002": 0}
    cards = _cards({"S-0001": (["甲"], [("甲", "生死", "已死", "q")]), "S-0002": (["甲"], [])})
    assert death_suspects(seq, pos, cards, {}) == ([], 0)


def test_persons_of只在pov里的人也算():
    from ligaotai.timeline import persons_of
    assert persons_of({"characters": [], "pov": "甲"}, {}) == {"甲"}
    assert persons_of({"characters": [{"name": "乙"}], "pov": "甲"}, {}) == {"甲", "乙"}


def test_A嫌疑_人物名单只在pov里也算():
    # persons_of 不看 pov 的话，S-0002 的人物名单里就没有「甲」，这条嫌疑会漏掉（补测清单第 7 条）。
    seq = ["S-0001", "S-0002"]
    pos = {"S-0001": 0, "S-0002": 1}
    cards = {
        "S-0001": {"card": {"characters": [], "pov": "甲",
                            "facts": [{"subject": "甲", "attribute": "生死", "value": "已死", "quote": "q"}]}},
        "S-0002": {"card": {"characters": [], "pov": "甲", "facts": []}},
    }
    got, capped = death_suspects(seq, pos, cards, {})
    assert [(x["who"], x["later"]) for x in got] == [("甲", "S-0002")]


from ligaotai.timeline import ref_suspects


def _rcards(spec):
    """spec: {sid: (persons, refs, summary)}"""
    return {s: {"id": s, "card": {"characters": [{"name": n} for n in p], "facts": [],
                                  "refs_elsewhere": list(r), "summary": sm}}
            for s, (p, r, sm) in spec.items()}


def test_C嫌疑_候选按共同人物数排_同分同线优先_只问候选里有排在后面的():
    # 审 F1 第 6 条改完：只有 1 个共同人物、又没点名的不算候选了，所以这里只剩 S-0003（2 个共同人物）；
    # S-0001、S-0004（各 1 个共同人物、回指原话没点名）被过滤掉（旧断言曾是 3 个候选，语义已变）。
    seq = ["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"]
    pos = {s: i for i, s in enumerate(seq)}
    line = {"S-0001": "L-001", "S-0002": "L-001", "S-0003": "L-002", "S-0004": "L-001", "S-0005": "L-002"}
    cards = _rcards({
        "S-0001": (["甲"], [], "一"),
        "S-0002": (["甲", "乙"], ["那日比箭之事"], "二"),
        "S-0003": (["甲", "乙"], [], "三"),
        "S-0004": (["甲"], [], "四"),
        "S-0005": (["丙"], ["只有丙"], "五"),  # 没有共同人物的候选 → 跳过
    })
    asks, no_cand, no_later = ref_suspects(seq, pos, cards, {}, line)
    assert len(asks) == 1
    a = asks[0]
    assert (a["scene"], a["ref"]) == ("S-0002", "那日比箭之事")
    assert a["candidates"] == ["S-0003"]
    assert (no_cand, no_later) == (1, 0)


def test_C嫌疑_候选按回指原话点名的人优先_哪怕共同人物少():
    # S-0127 跟回指所在场 S-0002 一个共同人物都没有，但回指原话点了「刘公」（归一到「刘芳」），
    # S-0127 的人物名单里有他 → 该排第一；S-0003 共同人物 2 个但没点名 → 排后面。
    # 对应真书 S-0014「劉封君所託三事已完其二」要抓到 S-0127（刘芳托付三事）这个场景。
    seq = ["S-0001", "S-0002", "S-0003", "S-0127"]
    pos = {s: i for i, s in enumerate(seq)}
    cmap = {("person", "刘芳"): "刘芳", ("person", "刘公"): "刘芳"}
    cards = _rcards({
        "S-0001": (["甲"], [], "一"),
        "S-0002": (["甲", "乙"], ["刘公所托三事已完其二"], "二"),
        "S-0003": (["甲", "乙"], [], "三"),
        "S-0127": (["刘芳"], [], "刘芳托付三事"),
    })
    asks, _, _ = ref_suspects(seq, pos, cards, cmap, {})
    assert asks[0]["candidates"][0] == "S-0127"


def test_C嫌疑_候选按词面重合排序_主角哪里都在时专名决定候选():
    # 审2 B1：主角在所有候选场景的人物名单里，「点名」「共同人物数」对他没有区分度——
    # S-0002 共同人物数(2)比 S-0003 (1)多，旧排序会把 S-0002 排第一；但回指原话里的专名
    # 「八极崩」只出现在 S-0003 的卡片 events 里，加了词面重合键之后 S-0003 该排第一。
    seq = ["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"]
    pos = {s: i for i, s in enumerate(seq)}
    cmap = {("person", "萧炎"): "萧炎"}
    cards = _rcards({
        "S-0001": (["萧炎", "药老"], ["萧炎想起那日学会八极崩之事"], "开场"),
        "S-0002": (["萧炎", "药老"], [], "学功夫"),
        "S-0003": (["萧炎"], [], ""),
        "S-0004": (["甲"], [], "四"),
        "S-0005": (["乙"], [], "五"),
    })
    cards["S-0002"]["card"]["events"] = ["苦练心法"]
    cards["S-0003"]["card"]["events"] = ["学会八极崩"]
    asks, _, _ = ref_suspects(seq, pos, cards, cmap, {})
    a = next(x for x in asks if x["ref"] == "萧炎想起那日学会八极崩之事")
    assert a["candidates"][0] == "S-0003"


def test_C嫌疑_词面重合排除高频bigram():
    # 参与检查的场景里，「众人」这个 bigram 在超过 30% 的场景（3/5）里都出现，属于高频，
    # 不该被算作重合——不然到处都是的虚词会制造假的词面重合信号。
    seq = ["S-0001", "S-0002", "S-0003", "S-0004", "S-0005"]
    pos = {s: i for i, s in enumerate(seq)}
    cards = _rcards({
        "S-0001": (["甲", "乙"], ["回指提到众人围观"], "一"),
        "S-0002": (["甲", "乙"], [], "众人围观热闹"),
        "S-0003": (["甲"], [], "众人也都在场"),
        "S-0004": (["丙"], [], "众人散去了"),
        "S-0005": (["丁"], [], "无关内容"),
    })
    asks, _, _ = ref_suspects(seq, pos, cards, {}, {})
    a = asks[0]
    # S-0002（共同人物 2）该排在只共享 1 个共同人物、又没被词面重合帮衬的 S-0003 之前——
    # 如果「众人围观」被当成有效重合，S-0003 反而会因为词面分并列/占先，排序会乱。
    assert a["candidates"][0] == "S-0002"


def test_C嫌疑_候选全在前面的不问():
    seq = ["S-0001", "S-0002"]
    pos = {"S-0001": 0, "S-0002": 1}
    cards = _rcards({"S-0001": (["甲", "乙"], [], "一"), "S-0002": (["甲", "乙"], ["前事"], "二")})
    asks, no_cand, no_later = ref_suspects(seq, pos, cards, {}, {})
    assert asks == [] and (no_cand, no_later) == (0, 1)


def test_C嫌疑_候选最多8个():
    seq = [f"S-{i:04d}" for i in range(1, 13)]
    pos = {s: i for i, s in enumerate(seq)}
    spec = {s: (["甲", "乙"], [], s) for s in seq}
    spec["S-0001"] = (["甲", "乙"], ["某事"], "一")
    asks, _, _ = ref_suspects(seq, pos, _rcards(spec), {}, {})
    assert len(asks[0]["candidates"]) == 8


def test_C嫌疑_候选场景的人物只在pov里也算():
    # persons_of 不看 pov 的话，S-0002 跟 S-0001 就只剩「乙」1 个共同人物，够不上新的候选门槛
    # （共同人物≥2 或点名），这条候选会被漏掉（补测清单第 7 条，C 类场景）。
    seq = ["S-0001", "S-0002", "S-0003"]
    pos = {s: i for i, s in enumerate(seq)}
    cards = {
        "S-0001": {"card": {"characters": [{"name": "乙"}], "pov": "甲", "facts": [],
                            "refs_elsewhere": ["某事"], "summary": "一"}},
        "S-0002": {"card": {"characters": [{"name": "乙"}], "pov": "甲", "facts": [],
                            "refs_elsewhere": [], "summary": "二"}},
        "S-0003": {"card": {"characters": [{"name": "丙"}], "pov": "", "facts": [],
                            "refs_elsewhere": [], "summary": "三"}},
    }
    asks, no_cand, no_later = ref_suspects(seq, pos, cards, {}, {})
    assert len(asks) == 1 and asks[0]["candidates"] == ["S-0002"]


def test_C嫌疑_距离优先于位置():
    # S-0008 距回指场（S-0005）3 步，S-0001 距 4 步——S-0001 的位置数字更小，但 S-0008 该排前面；
    # 去掉「按距离排」、改成直接按位置排的话，S-0001 会排到 S-0008 前面（补测清单：距离不同但位置序相反）。
    seq = [f"S-{i:04d}" for i in range(10)]
    pos = {s: i for i, s in enumerate(seq)}
    line = {s: "L-1" for s in seq}
    spec = {f"S-{i:04d}": ([], [], str(i)) for i in range(10) if i not in (5, 8, 1)}
    spec["S-0005"] = (["甲", "乙"], ["某事"], "ref")
    spec["S-0008"] = (["甲", "乙"], [], "近")
    spec["S-0001"] = (["甲", "乙"], [], "远但位置数字小")
    asks, _, _ = ref_suspects(seq, pos, _rcards(spec), {}, line)
    assert asks[0]["candidates"][:2] == ["S-0008", "S-0001"]


def test_C嫌疑_同线优先于距离():
    # S-0009 跟回指场（S-0005）距离 4、同线；S-0002 距离 3（更近）、不同线——同线的该排前面。
    # S-0009 的位置数字(9)也比 S-0002(2)大，纯按距离排或纯按位置排都会把 S-0002 排前面，
    # 只有「同线优先」生效才会让 S-0009 排到 S-0002 前面（补测清单：共同人物数相同、线不同）。
    seq = [f"S-{i:04d}" for i in range(10)]
    pos = {s: i for i, s in enumerate(seq)}
    line = {s: "L-A" for s in seq}
    line["S-0002"] = "L-B"
    spec = {f"S-{i:04d}": ([], [], str(i)) for i in range(10) if i not in (5, 9, 2)}
    spec["S-0005"] = (["甲", "乙"], ["某事"], "ref")
    spec["S-0002"] = (["甲", "乙"], [], "距离更近但不同线")
    spec["S-0009"] = (["甲", "乙"], [], "距离更远但同线")
    asks, _, _ = ref_suspects(seq, pos, _rcards(spec), {}, line)
    assert asks[0]["candidates"][:2] == ["S-0009", "S-0002"]


def test_C嫌疑_目录挑中的排最前_不受门槛限制():
    # 10-01 斗破真卡：回指「那日得到焚决之事」没点名，事件那场（S-0060）跟回指场只有 1 个共同
    # 人物，字面门槛把它挡在外面。模型从目录里挑中了它，就该排第一，不管门槛和词面重合。
    seq = ["S-0001", "S-0002", "S-0003", "S-0004"]
    pos = {s: i for i, s in enumerate(seq)}
    cards = _rcards({
        "S-0001": (["甲", "乙"], ["那日得到焚决之事"], "一"),
        "S-0002": (["甲", "乙"], [], "二"),
        "S-0003": (["甲", "乙"], [], "三"),
        "S-0004": (["甲"], [], "晋升，药老告知功法名为焚决"),
    })
    asks, _, _ = ref_suspects(seq, pos, cards, {}, {}, picks={("S-0001", "那日得到焚决之事"): ["S-0004"]})
    assert asks[0]["candidates"] == ["S-0004", "S-0002", "S-0003"]


def test_C嫌疑_目录挑中的去掉回指场自己和不认识的编号_不重复():
    seq = ["S-0001", "S-0002", "S-0003"]
    pos = {s: i for i, s in enumerate(seq)}
    cards = _rcards({"S-0001": (["甲", "乙"], ["某事"], "一"), "S-0002": (["甲", "乙"], [], "二"),
                     "S-0003": (["丙"], [], "三")})
    picks = {("S-0001", "某事"): ["S-0001", "S-9999", "S-0003", "S-0003"]}
    asks, _, _ = ref_suspects(seq, pos, cards, {}, {}, picks=picks)
    assert asks[0]["candidates"] == ["S-0003", "S-0002"]


def test_C嫌疑_目录挑中的让原来没候选的回指也有候选():
    seq = ["S-0001", "S-0002"]
    pos = {s: i for i, s in enumerate(seq)}
    cards = _rcards({"S-0001": (["甲"], ["某事"], "一"), "S-0002": (["丙"], [], "二")})
    asks, no_cand, _ = ref_suspects(seq, pos, cards, {}, {})
    assert asks == [] and no_cand == 1
    asks, no_cand, _ = ref_suspects(seq, pos, cards, {}, {}, picks={("S-0001", "某事"): ["S-0002"]})
    assert [a["candidates"] for a in asks] == [["S-0002"]] and no_cand == 0


def test_C嫌疑_目录挑中的加上字面候选总数还是最多8个():
    seq = [f"S-{i:04d}" for i in range(1, 13)]
    pos = {s: i for i, s in enumerate(seq)}
    spec = {s: (["甲", "乙"], [], s) for s in seq}
    spec["S-0001"] = (["甲", "乙"], ["某事"], "一")
    asks, _, _ = ref_suspects(seq, pos, _rcards(spec), {}, {}, picks={("S-0001", "某事"): ["S-0012", "S-0011"]})
    c = asks[0]["candidates"]
    assert len(c) == 8 and c[:2] == ["S-0012", "S-0011"] and len(set(c)) == 8


from ligaotai.timeline import index_chunks, index_line, ref_items


def test_回指清单_按故事顺序_同场去重_空的跳过():
    cards = _rcards({"S-0002": (["甲"], ["甲事", "甲事", " ", "乙事"], "二"), "S-0001": (["甲"], ["丙事"], "一")})
    assert ref_items(["S-0001", "S-0002", "S-0003"], cards) == [("S-0001", "丙事"), ("S-0002", "甲事"), ("S-0002", "乙事")]


def test_目录一行_编号加摘要截短_空白压掉():
    cards = _rcards({"S-0001": ([], [], "萧炎\n冲击  斗者" + "字" * 200)})
    line = index_line(cards, "S-0001")
    assert line.startswith("[S-0001] 萧炎 冲击 斗者")
    assert len(line) == len("[S-0001] ") + 100


def test_目录分段():
    seq = [f"S-{i:04d}" for i in range(7)]
    cards = _rcards({s: ([], [], "摘要") for s in seq})  # 每行「[S-0000] 摘要」11 字，加换行 12
    assert index_chunks(seq, cards, 36) == [seq[0:3], seq[3:6], seq[6:7]]
    assert index_chunks(seq, cards, 35) == [seq[0:2], seq[2:4], seq[4:6], seq[6:7]]
    assert index_chunks(seq, cards, 5) == [[s] for s in seq]  # 一行就超的自成一段
    assert index_chunks([], cards, 36) == []


from ligaotai.timeline import name_snippets


def test_摘录_按任一叫法找_最多3处_前后带一点上下文_不重叠():
    text = "開頭。劉公道：你來了。中間很多字" + "。" * 60 + "劉芳笑了。又過了很久" + "。" * 60 + "劉公走了。" + "。" * 60 + "劉公又來。"
    got = name_snippets(text, ["劉芳", "劉公"], width=6, limit=3)
    assert len(got) == 3
    assert "劉公道" in got[0] and "劉芳笑了" in got[1] and "劉公走了" in got[2]


def test_摘录_找不到就给开头一段():
    assert name_snippets("完全沒有這個人的一段話。", ["甲"], width=4, limit=3) == ["完全沒有這個人的一段話。"[:40]]


from ligaotai.timeline import assemble, conflict_sig


def _c(kind, scenes, who=None, ref=None):
    return {"kind": kind, "who": who, "ref": ref, "scenes": scenes, "pos": [0, 1], "quotes": ["a", "b"],
            "reason": "r", "status": "在场" if kind == "A" else ""}


def test_签名只看类型_两场_人名或回指():
    a = conflict_sig(_c("A", ["S-0001", "S-0002"], who="甲"))
    assert a == conflict_sig({**_c("A", ["S-0001", "S-0002"], who="甲"), "reason": "别的说法", "pos": [5, 9]})
    assert a != conflict_sig(_c("A", ["S-0001", "S-0003"], who="甲"))
    assert a != conflict_sig(_c("C", ["S-0001", "S-0002"], ref="甲"))


def test_编号按签名沿用_新的接着编_裁决跟着签名走_消失的丢掉():
    old = {"next_id": 3, "conflicts": [
        {**_c("A", ["S-0001", "S-0002"], who="甲"), "id": "T-001",
         "sig": conflict_sig(_c("A", ["S-0001", "S-0002"], who="甲")),
         "verdict": {"kind": "order_error", "at": "x"}},
        {**_c("C", ["S-0003", "S-0004"], ref="某事"), "id": "T-002",
         "sig": conflict_sig(_c("C", ["S-0003", "S-0004"], ref="某事")),
         "verdict": {"kind": "ignore", "at": "x"}},
    ]}
    new = [_c("C", ["S-0005", "S-0006"], ref="新事"), _c("A", ["S-0001", "S-0002"], who="甲")]
    got = assemble(new, old)
    assert [(c["id"], c["verdict"]) for c in got["conflicts"]] == [
        ("T-003", None), ("T-001", {"kind": "order_error", "at": "x"})]
    assert got["next_id"] == 4
    assert {e["sig"]: e["id"] for e in got["id_registry"]}[conflict_sig(_c("C", ["S-0003", "S-0004"], ref="某事"))] == "T-002"


def test_旧文件坏了当空的():
    got = assemble([_c("A", ["S-0001", "S-0002"], who="甲")], {"conflicts": "坏了", "next_id": "x"})
    assert got["conflicts"][0]["id"] == "T-001" and got["next_id"] == 2


def test_id_registry里两轮前消失的签名这轮又出现_沿用原编号():
    # sig 只在 id_registry 里登记过（对应的那条冲突这轮的 conflicts 列表里已经没有了，
    # 比如上上轮报过、上一轮没报、这一轮又报出来），重新出现时还是要沿用原编号，不能
    # 当成全新的重编——这条覆盖率原来没测（补测清单第 4 条）。
    old_c = _c("A", ["S-0001", "S-0002"], who="甲")
    old_sig = conflict_sig(old_c)
    old = {"next_id": 3, "conflicts": [], "id_registry": [{"sig": old_sig, "id": "T-002"}]}
    got = assemble([old_c], old)
    assert [(c["id"], c["sig"]) for c in got["conflicts"]] == [("T-002", old_sig)]


def test_next_id按id_registry里已用的最大编号往后编_不看老next_id():
    # 旧 next_id=1，但 id_registry 里已经登记到 T-007（比如作者手改过、或者 next_id 字段
    # 本身跟不上 registry），新冲突要接着 T-008 编，不能沿用过时的 next_id=1（补测清单第 5 条）。
    old = {"next_id": 1, "conflicts": [],
          "id_registry": [{"sig": "sig-不会被匹配到的旧签名", "id": "T-007"}]}
    new_c = _c("A", ["S-0001", "S-0002"], who="甲")
    got = assemble([new_c], old)
    assert got["conflicts"][0]["id"] == "T-008"
    assert got["next_id"] == 9


def test_assemble对重复签名的冲突只留一条_保险去重():
    # ref_suspects 已经对同场景重复回指去重了；这里测 assemble 自己的第二道保险——万一
    # 上游哪里没去干净，两条一样签名的冲突不该产出两个编号（补测清单：同一场景重复回指
    # 生成两条同编号冲突）。
    c1 = _c("C", ["S-0001", "S-0002"], ref="某事")
    c2 = _c("C", ["S-0001", "S-0002"], ref="某事")  # 内容一样、签名一样
    got = assemble([c1, c2], {})
    assert len(got["conflicts"]) == 1
    assert got["next_id"] == 2


from ligaotai.timeline import input_fingerprint


def test_指纹_顺序或卡或规范名变了就变(book):
    _seed(book, [("S-0001", ["甲"], ["某事"], [], "x"), ("S-0002", ["甲"], [], [], "y")])
    _threads(book, [{"id": "L-001", "offset": 0, "scenes": ["S-0001", "S-0002"],
                     "times": {"S-0001": {"t": 0}, "S-0002": {"t": 1}}}])
    f0 = input_fingerprint(book)
    assert input_fingerprint(book) == f0
    _threads(book, [{"id": "L-001", "offset": 0, "scenes": ["S-0002", "S-0001"],
                     "times": {"S-0001": {"t": 1}, "S-0002": {"t": 0}}}])
    f1 = input_fingerprint(book)
    assert f1 != f0
    from ligaotai.cards import card_path
    from ligaotai.fsutil import read_json
    rec = read_json(card_path(book, "S-0001"))
    rec["card"]["refs_elsewhere"] = ["另一件事"]
    write_json(card_path(book, "S-0001"), rec)
    assert input_fingerprint(book) != f1


def _fp_one_scene_book(book):
    from helpers import seed_book
    seed_book(book, [{"id": "S-0001", "persons": ["甲"], "text": "x", "summary": "原摘要"}],
              entities=[("person", "甲", ["甲"])])
    _threads(book, [{"id": "L-001", "offset": 0, "scenes": ["S-0001"], "times": {"S-0001": {"t": 0}}}])


def test_指纹_规范名变了就变(book):
    _fp_one_scene_book(book)
    f0 = input_fingerprint(book)
    from ligaotai.fsutil import read_json
    ents = read_json(book.entities_path)
    ents["entities"][0]["canonical"] = "乙"
    write_json(book.entities_path, ents)
    assert input_fingerprint(book) != f0


def test_指纹_人物名单变了就变(book):
    _fp_one_scene_book(book)
    f0 = input_fingerprint(book)
    from ligaotai.cards import card_path
    from ligaotai.fsutil import read_json
    rec = read_json(card_path(book, "S-0001"))
    rec["card"]["characters"] = [{"name": "甲"}, {"name": "乙"}]
    write_json(card_path(book, "S-0001"), rec)
    assert input_fingerprint(book) != f0


def test_指纹_pov变了就变(book):
    _fp_one_scene_book(book)
    f0 = input_fingerprint(book)
    from ligaotai.cards import card_path
    from ligaotai.fsutil import read_json
    rec = read_json(card_path(book, "S-0001"))
    rec["card"]["pov"] = "甲"
    write_json(card_path(book, "S-0001"), rec)
    assert input_fingerprint(book) != f0


def test_指纹_facts变了就变(book):
    _fp_one_scene_book(book)
    f0 = input_fingerprint(book)
    from ligaotai.cards import card_path
    from ligaotai.fsutil import read_json
    rec = read_json(card_path(book, "S-0001"))
    rec["card"]["facts"] = [{"subject": "甲", "attribute": "生死", "value": "已死", "quote": "q"}]
    write_json(card_path(book, "S-0001"), rec)
    assert input_fingerprint(book) != f0


def test_指纹_summary变了就变(book):
    _fp_one_scene_book(book)
    f0 = input_fingerprint(book)
    from ligaotai.cards import card_path
    from ligaotai.fsutil import read_json
    rec = read_json(card_path(book, "S-0001"))
    rec["card"]["summary"] = "改过的摘要"
    write_json(card_path(book, "S-0001"), rec)
    assert input_fingerprint(book) != f0


def test_指纹_场景正文哈希变了就变_卡没变也算(book):
    # 作者直接手改了场景原文（没走重做卡），卡片字段没变，但正文哈希变了——指纹也要跟着变，
    # 不然这类改动会被漏判成没过期（补测清单：指纹去掉 xxx / 只剩 refs 字段，这里补正文哈希那部分）。
    _fp_one_scene_book(book)
    f0 = input_fingerprint(book)
    from ligaotai.scenes import get_scene, write_scene
    sc = get_scene(book, "S-0001")
    sc.hash = "换了个哈希"
    write_scene(book, sc)
    assert input_fingerprint(book) != f0
