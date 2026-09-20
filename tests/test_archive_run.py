"""步骤 7 编排（Task 16/17）：三件并行 → 回填 C- 编号 → 全书地图；过期规则与跑的途中上游变了。

假模型不花钱：按 system 提示词认出是哪一种调用，照输入现造一份能过检查的回复，并把
「archive/thread/L-001」这样的标签记进 client.calls，测试靠它数到底调了几次模型、调了谁。
"""

import json
import re

import pytest
from helpers import FakeBackend, seed_book

from ligaotai.cards import card_path
from ligaotai.config import AppConfig
from ligaotai.fsutil import read_json, write_json
from ligaotai.jobs import JobCancelled
from ligaotai.llm import LLMClient, LLMError

SCENES = [{"id": f"S-{i:04d}", "source": "a.txt", "index": i} for i in range(1, 10)]
ENTS = [("person", "孙悟空", ["悟空", "行者"])]

FACTS = {
    "S-0001": [{"subject": "悟空", "attribute": "兵器", "value": "如意金箍棒", "quote": "悟空掣出如意金箍棒"}],
    "S-0003": [{"subject": "行者", "attribute": "兵器", "value": "降妖宝杖", "quote": "行者举起降妖宝杖"}],
    "S-0004": [{"subject": "敖广", "attribute": "居所", "value": "东海龙宫", "quote": "敖广住在东海龙宫"}],
    "S-0008": [{"subject": "花果山", "attribute": "位置", "value": "东胜神洲", "quote": "花果山在东胜神洲"}],
}
PERSONS = {"S-0001": ["悟空"], "S-0002": ["悟空"], "S-0003": ["行者"], "S-0004": ["敖广"], "S-0005": ["敖广"]}
HOOKS = {"S-0002": ["紧箍咒的来历"]}


def threads_data() -> dict:
    return {
        "next_world": 2, "next_thread": 3, "time_unit": "年", "main_thread": "L-001", "main_by": "auto",
        "worlds": [{"id": "W-01", "name": "西游世界", "reason": "测试", "status": "draft",
                    "notes": ["S-0008"], "outlines": []}],
        "threads": [
            {"id": "L-001", "world": "W-01", "name": "取经", "about": "", "status": "draft",
             "scenes": ["S-0001", "S-0002", "S-0003"],
             "times": {"S-0001": {"t": 0, "conf": "高"}, "S-0002": {"t": 1, "conf": "高"},
                       "S-0003": {"t": 2, "conf": "低"}},
             "outlines": [], "offset": 0, "end": {"state": "待定", "note": "测试", "last": "S-0003"},
             "order_failed": False},
            {"id": "L-002", "world": "W-01", "name": "龙宫", "about": "", "status": "draft",
             "scenes": ["S-0004", "S-0005"],
             "times": {"S-0004": {"t": 0, "conf": "高"}, "S-0005": {"t": 1, "conf": "高"}},
             "outlines": [], "offset": 3, "end": {"state": "完结", "note": "", "last": "S-0005"},
             "order_failed": False},
        ],
        "intersections": [],
        "gaps": [{"id": "Q-001", "world": "W-01", "event": "大闹天宫", "mentioned_in": ["S-0002"],
                  "thread": "L-001", "after": "S-0001", "before": "S-0003"}],
        "unassigned": [{"scene": "S-0009", "reason": "模型没分配"}],
        "pending": [],
    }


def set_card(book, sid, **changes):
    rec = read_json(card_path(book, sid))
    rec["card"].update(changes)
    write_json(card_path(book, sid), rec)


@pytest.fixture
def book_with_threads(book):
    texts = {"S-0008": "花果山在东胜神洲，是十洲之祖脉。"}
    seed_book(book, [{**s, "text": texts.get(s["id"], f"{s['id']} 的正文。"), "persons": PERSONS.get(s["id"], []),
                      "kind": "设定笔记" if s["id"] == "S-0008" else "正文"} for s in SCENES], entities=ENTS)
    for sid in [s["id"] for s in SCENES]:
        set_card(book, sid, facts=FACTS.get(sid, []), hooks_planted=HOOKS.get(sid, []), hooks_resolved=[])
    write_json(book.threads_path, threads_data())
    return book


# ---------- 假模型 ----------

_SID = re.compile(r"S-\d{4}")


def _reply_thread(user: str) -> tuple[str, str]:
    tid = re.search(r"线编号：(L-\d+)", user).group(1)
    ids = re.findall(r"^(S-\d{4})｜", user, re.M)
    first, last = ids[0], ids[-1]
    body = (f"# {tid}\n- 所属世界：W-01\n- 一句话：测试 [{first}]\n\n## 来龙去脉\n"
            + "".join(f"第 {i} 块 [{s}]。" for i, s in enumerate(ids))
            + f"\n\n## 主要人物\n- 孙悟空：主角 [{first}]\n\n## 写到哪\n- 最后一块：[{last}]\n\n"
            "## 缺口\n（没有）\n\n## 开放的伏笔\n（没有）")
    return f"thread/{tid}", body


def _reply_world(user: str) -> tuple[str, str]:
    wid = re.search(r"世界编号：(W-\d+)", user).group(1)
    attr, by_key = "", {}
    for line in user.splitlines():
        if line.startswith("### "):
            attr = line[4:].strip()
        m = re.match(r"- (.+?)：(.+?)　\[(S-\d{4})\]", line)
        if m and attr:
            by_key.setdefault((attr, m.group(1)), []).append((m.group(2), m.group(3)))
    parts = [f"# {wid} 测试世界"]
    for a in sorted({k[0] for k in by_key}):
        parts.append(f"\n## {a}")
        for (aa, subj), vals in sorted(by_key.items()):
            if aa != a:
                continue
            values = sorted({v for v, _ in vals})
            refs = ",".join(sorted({s for _, s in vals}))
            multi = "（多个说法）" if len(values) > 1 else ""
            parts.append(f"- {subj}：{' / '.join(values)}{multi}[{refs}]")
    return f"world/{wid}", "\n".join(parts)


def _reply_contradictions(user: str) -> tuple[str, dict]:
    groups = []
    for block in re.split(r"\n\n(?=C-\d{3} )", user.split("\n\n", 1)[1]):
        cid = block.split(" ", 1)[0]
        sid = _SID.search(block).group(0)
        groups.append({"id": cid, "status": "真矛盾", "level": "严重", "category": "人物",
                       "reason": f"测试 [{sid}]"})
    first = groups[0]["id"] if groups else "none"
    return f"contradictions/{first}", {"groups": groups}


def archive_handler(record: list, overrides: dict | None = None, on_call=None):
    """overrides：{标签前缀: fn(user) -> 回复}，用来造失败或别的回复。"""
    overrides = overrides or {}

    def handler(tier, messages):
        system, user = messages[0]["content"], messages[1]["content"]
        if "全书地图" in system:  # 地图的 system 里也提到「设定集」「支线档案」，要先认
            sid = _SID.search(user).group(0)
            tag = "map"
            out = json.dumps({"body": f"# 全书地图\n\n## 全书概况\n测试 [{sid}]"}, ensure_ascii=False)
        elif "这条线的档案" in system:
            tag, body = _reply_thread(user)
            out = json.dumps({"body": body}, ensure_ascii=False)
        elif "设定集" in system:
            tag, body = _reply_world(user)
            out = json.dumps({"body": body}, ensure_ascii=False)
        elif "逐组判断" in system:
            tag, data = _reply_contradictions(user)
            out = json.dumps(data, ensure_ascii=False)
        else:
            raise AssertionError("没见过的提示词")
        tag = f"archive/{tag}"
        record.append(tag)
        if on_call is not None:
            on_call(tag, messages)
        for prefix, fn in overrides.items():
            if tag.startswith(prefix):
                return fn(user)
        return out

    return handler


def make_client(book, **kw):
    record: list = []
    backend = FakeBackend(handler=archive_handler(record, **kw))
    c = LLMClient(AppConfig(), backend, log_dir=book.logs_dir)
    c.calls = record
    return c


@pytest.fixture
def fake_client(book_with_threads):
    return make_client(book_with_threads)


@pytest.fixture
def failing_world_client(book_with_threads):
    return make_client(book_with_threads, overrides={"archive/world": lambda u: LLMError("假的失败")})


def map_user(client) -> str:
    [m] = [x["messages"][1]["content"] for x in client.backend.calls if "全书地图" in x["messages"][0]["content"]]
    return m


# ---------- Task 16：编排 ----------


def test_四件都产出(book_with_threads, fake_client):
    from ligaotai.archive import run_archive

    res = run_archive(book_with_threads, fake_client)
    b = book_with_threads
    assert (b.thread_archive_dir / "L-001.md").exists()
    assert (b.thread_archive_dir / "L-002.md").exists()
    assert (b.world_archive_dir / "W-01.md").exists()
    assert b.contradictions_path.exists()
    assert b.map_path.exists()
    assert res["threads"] == 2 and res["worlds"] == 1
    assert res["contradictions"] == 1 and res["严重"] == 1
    assert b.step("archive")["status"] == "done"
    assert sorted(fake_client.calls) == sorted(
        ["archive/thread/L-001", "archive/thread/L-002", "archive/world/W-01",
         "archive/contradictions/C-000", "archive/map"])
    assert b.load()["usage"]["by_step"]["archive"]["calls"] == 5


def test_地图在三件都完成之后才跑(book_with_threads, fake_client):
    from ligaotai.archive import run_archive

    run_archive(book_with_threads, fake_client)
    tags = fake_client.calls
    assert tags[-1] == "archive/map"
    assert tags.index("archive/map") > max(
        i for i, t in enumerate(tags) if t.startswith(("archive/thread", "archive/world", "archive/contradictions")))


def test_回填在地图之前(book_with_threads, fake_client):
    """世界设定集里的「（多个说法）」在地图跑之前已经补上 C- 编号——地图的输入里不该再出现光秃秃的「（多个说法）」。"""
    from ligaotai.archive import run_archive

    run_archive(book_with_threads, fake_client)
    body = (book_with_threads.world_archive_dir / "W-01.md").read_text(encoding="utf-8")
    assert "（多个说法，见矛盾 C-001）" in body
    user = map_user(fake_client)
    assert "（多个说法，见矛盾 C-001）" in user and "（多个说法）" not in user


def test_index记下每份档案的签名(book_with_threads, fake_client):
    from ligaotai.archive import load_index

    from ligaotai.archive import run_archive

    run_archive(book_with_threads, fake_client)
    idx = load_index(book_with_threads)
    assert idx["threads"]["L-001"]["sig"] and idx["threads"]["L-001"]["outdated"] is False
    assert idx["threads"]["L-001"]["scenes"] == ["S-0001", "S-0002", "S-0003"]
    assert idx["threads"]["L-001"]["world"] == "W-01"
    assert idx["worlds"]["W-01"]["sig"] and idx["worlds"]["W-01"]["outdated"] is False
    assert idx["map"]["sig"] and idx["map"]["outdated"] is False


def test_index记下生成每份档案用的模型名(book_with_threads, fake_client):
    """I2（F+DE 合并审查，作者 9-20 拍板）：换模型不进签名（换一次模型 = 全部档案重付一次钱，
    不值），但要记下生成时用的模型名，好让界面对比 index 里的模型名和当前配置提示作者重跑。"""
    from ligaotai.archive import load_index, run_archive

    run_archive(book_with_threads, fake_client)
    idx = load_index(book_with_threads)
    model = fake_client.cfg.synth.model
    assert idx["threads"]["L-001"]["model"] == model
    assert idx["threads"]["L-002"]["model"] == model
    assert idx["worlds"]["W-01"]["model"] == model
    assert idx["contradictions"]["model"] == model
    assert idx["map"]["model"] == model


def test_输入是真实渲染的文本_设定笔记读的是正文(book_with_threads, fake_client):
    from ligaotai.archive import run_archive

    run_archive(book_with_threads, fake_client)
    [world_user] = [x["messages"][1]["content"] for x in fake_client.backend.calls
                    if "汇总成一份设定集" in x["messages"][0]["content"]]
    assert "[S-0008] 花果山在东胜神洲，是十洲之祖脉。" in world_user
    assert "---" not in world_user, "场景文件的头信息不能混进设定笔记原文"
    [thread_user] = [x["messages"][1]["content"] for x in fake_client.backend.calls
                     if "线编号：L-002" in x["messages"][1]["content"]]
    assert "故事时间约 3年" in thread_user, "故事时间要加上线的 offset"


def test_某一件调用失败不拖垮别的(book_with_threads, failing_world_client):
    """世界设定集那次调用失败，支线档案、矛盾照样产出，失败记进 summary；
    地图要读全部档案，缺一份就不跑（省钱），标过期，这一步记 outdated 不记 done。"""
    from ligaotai.archive import load_index, run_archive

    b = book_with_threads
    res = run_archive(b, failing_world_client)
    assert (b.thread_archive_dir / "L-001.md").exists() and (b.thread_archive_dir / "L-002.md").exists()
    assert b.contradictions_path.exists()
    assert res["failed"] and res["failed"][0]["call"] == "world/W-01"
    assert not (b.world_archive_dir / "W-01.md").exists()
    assert "archive/map" not in failing_world_client.calls
    idx = load_index(b)
    assert idx["threads"]["L-001"]["outdated"] is False
    assert idx["map"].get("outdated") is True
    assert b.step("archive")["status"] == "outdated"

    # 重跑：只补失败的那份和地图，成功过的不再花钱
    c2 = make_client(b)
    run_archive(b, c2)
    assert sorted(c2.calls) == ["archive/map", "archive/world/W-01"]
    assert b.step("archive")["status"] == "done"


def test_矛盾某批失败_沿用上一轮花钱买的判断(book_with_threads, fake_client):
    """上一轮已经判过的组，这一轮所在批次调用失败：值集合没变就沿用上一轮的判断，
    别用「这一批调用失败」盖掉花过钱的结果；index 仍记 failed，下次重跑补上。"""
    from ligaotai.archive import load_index, run_archive

    b = book_with_threads
    run_archive(b, fake_client)
    [g0] = read_json(b.contradictions_path)["groups"]
    assert g0["status"] == "真矛盾"

    # 只改原文摘录：批次文本变了（缓存命中不了），值集合没变
    rec = read_json(card_path(b, "S-0001"))
    rec["card"]["facts"][0]["quote"] = "悟空掣出如意金箍棒，喝一声"
    write_json(card_path(b, "S-0001"), rec)
    c2 = make_client(b, overrides={"archive/contradictions": lambda u: LLMError("假的失败")})
    res = run_archive(b, c2)
    assert any(f["call"].startswith("contradictions/") for f in res["failed"])
    [g1] = read_json(b.contradictions_path)["groups"]
    assert (g1["id"], g1["status"], g1["level"], g1["reason"]) == (g0["id"], g0["status"], g0["level"], g0["reason"])
    assert load_index(b)["contradictions"]["failed"] is True
    assert b.step("archive")["status"] == "outdated"


def test_档案用自己的缓存_不碰归线缓存(book_with_threads, fake_client):
    from ligaotai.archive import run_archive

    b = book_with_threads
    b.threads_cache_path.write_text('{"k": {"data": {"x": 1}, "problems": []}}', encoding="utf-8")
    before = b.threads_cache_path.read_bytes()
    run_archive(b, fake_client)
    assert b.threads_cache_path.read_bytes() == before
    assert len(read_json(b.archive_cache_path)) == 5

    # 第二次跑：什么都没变，全部按签名跳过（0 次调用）；跳过的条目也不该被 prune 清掉——
    # 花过钱买的缓存不能因为「这一轮没真调用」就被当垃圾扫掉（C1）
    c2 = make_client(b)
    run_archive(b, c2)
    assert c2.calls == []
    assert len(read_json(b.archive_cache_path)) == 5


def test_空转一次之后标过期重跑_命中缓存不花钱(book_with_threads, fake_client):
    """C1 回归：第一次跑完，第二次空转（0 次调用，缓存本该保留）；
    第三次把 L-001 标过期重跑——输入文本一个字都没变，只是 index 里的 outdated 标记变了。
    如果空转把缓存清空了（C1 的 bug），这一步会真调用模型重付一次钱；
    缓存留着的话，L-001 会走 caller.call() 那条「没被判定为 fresh，得重新走一遍」的路，
    但 render 出来的文本没变，命中的还是原来那条缓存，一分钱不花（对照 client.usage.calls）。"""
    from ligaotai.archive import load_index, run_archive, write_index

    b = book_with_threads
    run_archive(b, fake_client)
    assert len(read_json(b.archive_cache_path)) == 5

    c2 = make_client(b)
    run_archive(b, c2)
    assert c2.calls == []

    idx = load_index(b)
    idx["threads"]["L-001"]["outdated"] = True
    write_index(b, idx)

    c3 = make_client(b)
    res = run_archive(b, c3)
    assert c3.calls == [], "输入没变，应该命中缓存，不该真调模型"
    assert c3.usage.calls == 0
    assert res["calls"] == 0
    assert res["generated"]["threads"] == ["L-001"], "L-001 走了非 fresh 那条路，只是命中了缓存"
    assert "L-002" in res["reused"]["threads"]


def test_暂停后重跑_做完的不重复花钱(book_with_threads):
    """暂停（JobCancelled）时正在路上的调用让它跑完进缓存，不再开新的；
    重跑时已经落盘的按签名跳过，进了缓存没落盘的走缓存——两次加起来跟一次跑完调模型的次数一样。"""
    from ligaotai.archive import load_index, run_archive

    b = book_with_threads
    c1 = make_client(b)
    n = {"k": 0}

    def progress(done, total, message=""):
        n["k"] += 1
        if n["k"] > 5:  # 四件开工各报一次进度之后，第一份做完时作者点了暂停
            raise JobCancelled("已暂停")

    with pytest.raises(JobCancelled):
        run_archive(b, c1, progress)
    idx = load_index(b)
    written = [f"archive/thread/{t}" for t in idx["threads"]] + [f"archive/world/{w}" for w in idx["worlds"]]
    assert written, "暂停前做完的档案要落盘并记进 index"
    assert "archive/map" not in c1.calls

    c2 = make_client(b)
    run_archive(b, c2)
    assert not set(written) & set(c2.calls), "已经落盘的档案不该重调"
    assert len(c1.calls) + len(c2.calls) == 5
    assert b.step("archive")["status"] == "done"


# ---------- Task 17：过期规则与跑的途中上游变了 ----------


def _edit_threads(book, fn):
    data = read_json(book.threads_path, {})
    fn(data)
    write_json(book.threads_path, data)


def test_只有受影响的线重跑(book_with_threads, fake_client):
    """改一条线的成员，只有那条线的档案重跑，别的线不花钱；世界（成员变了）和地图跟着重跑，矛盾不动。"""
    from ligaotai.archive import run_archive

    b = book_with_threads
    run_archive(b, fake_client)
    _edit_threads(b, lambda d: d["threads"][0]["scenes"].append("S-0006"))
    c2 = make_client(b)
    res = run_archive(b, c2)
    assert "archive/thread/L-001" in c2.calls
    assert c2.calls.count("archive/thread/L-002") == 0, "没动的线不该重跑"
    assert "archive/map" in c2.calls
    assert not [t for t in c2.calls if t.startswith("archive/contradictions")], "facts 没变，矛盾不该重跑"
    assert res["reused"]["threads"] == ["L-002"] and res["reused"]["contradictions"] is True
    assert b.step("archive")["status"] == "done"


def test_任何档案重跑地图就重跑(book_with_threads, fake_client):
    from ligaotai.archive import run_archive

    b = book_with_threads
    run_archive(b, fake_client)
    _edit_threads(b, lambda d: d["threads"][1].__setitem__("name", "龙宫夜宴"))
    c2 = make_client(b)
    run_archive(b, c2)
    assert sorted(c2.calls) == ["archive/map", "archive/thread/L-002", "archive/world/W-01"]


def test_什么都没变就一次都不调(book_with_threads, fake_client):
    from ligaotai.archive import run_archive

    b = book_with_threads
    run_archive(b, fake_client)
    c2 = make_client(b)
    res = run_archive(b, c2)
    assert c2.calls == []
    assert res["map"] == "reused" and b.step("archive")["status"] == "done"


def test_只有签名以外的字段改了也要重跑_规范名映射(book_with_threads, fake_client):
    """签名 = 渲染后的输入文本：实体规范名映射变了（卡片行里的人名跟着变），线档案和矛盾都要重跑。"""
    from ligaotai.archive import run_archive

    b = book_with_threads
    run_archive(b, fake_client)
    ents = read_json(b.entities_path)
    for e in ents["entities"]:
        if e.get("canonical") == "孙悟空":
            e["canonical"] = "美猴王"
    write_json(b.entities_path, ents)
    c2 = make_client(b)
    run_archive(b, c2)
    assert "archive/thread/L-001" in c2.calls
    assert [t for t in c2.calls if t.startswith("archive/contradictions")], "主语规范名变了，矛盾要重跑"
    assert "archive/map" in c2.calls


def test_改场景卡的facts_矛盾和世界重跑(book_with_threads, fake_client):
    from ligaotai.archive import run_archive

    b = book_with_threads
    run_archive(b, fake_client)
    rec = read_json(card_path(b, "S-0005"))
    rec["card"]["facts"] = [{"subject": "敖广", "attribute": "居所", "value": "西海龙宫", "quote": "敖广回了西海龙宫"}]
    write_json(card_path(b, "S-0005"), rec)
    c2 = make_client(b)
    run_archive(b, c2)
    assert "archive/world/W-01" in c2.calls
    # 线档案的输入是卡片摘要行，不含 facts：facts 改了线档案的输入文本不变，不该重跑
    assert not [t for t in c2.calls if t.startswith("archive/thread")]
    assert [t for t in c2.calls if t.startswith("archive/contradictions")]
    assert len(read_json(b.contradictions_path)["groups"]) == 2


def mutating(book, change, when=lambda tag: True):
    """假模型：第一次满足 when 的调用时，偷偷改 世界与支线.json（作者在跑的途中动了归线结果）。"""
    done = {"x": False}

    def on_call(tag, messages):
        if not done["x"] and when(tag):
            done["x"] = True
            _edit_threads(book, change)

    return make_client(book, on_call=on_call)


@pytest.fixture
def mutating_client(book_with_threads):
    return mutating(book_with_threads, lambda d: d["threads"][1].__setitem__("name", "龙宫夜宴"))


def test_跑的途中上游变了记outdated(book_with_threads, mutating_client):
    """假模型在第一次调用之后偷偷改 世界与支线.json，这一步要记 outdated 不记 done；
    拿旧输入写的档案标过期，地图不花这笔钱。"""
    from ligaotai.archive import load_index, run_archive

    b = book_with_threads
    res = run_archive(b, mutating_client)
    assert b.step("archive")["status"] == "outdated"
    assert res["input_changed"] is True
    idx = load_index(b)
    assert idx["threads"]["L-002"]["outdated"] is True, "L-002 是拿旧线名写的"
    assert idx["threads"]["L-001"]["outdated"] is False
    assert idx["map"]["outdated"] is True
    assert "archive/map" not in mutating_client.calls

    # 再跑一次：只补被改动影响的，状态回到 done
    c2 = make_client(b)
    run_archive(b, c2)
    assert sorted(c2.calls) == ["archive/map", "archive/thread/L-002", "archive/world/W-01"]
    assert b.step("archive")["status"] == "done"


def test_跑地图时上游变了_地图也标过期(book_with_threads):
    """地图调用途中才改：档案都是新的，但地图是拿旧输入写的，要标过期、记 outdated。"""
    from ligaotai.archive import load_index, run_archive

    b = book_with_threads
    c = mutating(b, lambda d: d["threads"][1].__setitem__("name", "龙宫夜宴"), when=lambda tag: tag == "archive/map")
    run_archive(b, c)
    assert "archive/map" in c.calls
    assert b.step("archive")["status"] == "outdated"
    assert load_index(b)["map"]["outdated"] is True


def test_途中只改了不归任何线的缺口_地图也算过期(book_with_threads):
    """缺口总览只进地图的输入，不进任何一份档案：途中改了它，也要被发现。"""
    from ligaotai.archive import load_index, run_archive

    b = book_with_threads
    gap = {"id": "Q-002", "world": "W-01", "event": "蟠桃会", "mentioned_in": ["S-0004"],
           "thread": "", "after": "", "before": ""}
    c = mutating(b, lambda d: d["gaps"].append(gap), when=lambda tag: tag == "archive/map")
    res = run_archive(b, c)
    assert res["input_changed"] is True
    assert b.step("archive")["status"] == "outdated"
    assert load_index(b)["map"]["outdated"] is True
    c2 = make_client(b)
    run_archive(b, c2)
    assert c2.calls == ["archive/map"]


def test_单独标过期的档案会重跑(book_with_threads, fake_client):
    """给 Task 18 单独重跑接口用：index 里 outdated=True，签名一样也要重跑。"""
    from ligaotai.archive import load_index, run_archive, write_index

    b = book_with_threads
    run_archive(b, fake_client)
    idx = load_index(b)
    idx["threads"]["L-002"]["outdated"] = True
    write_index(b, idx)
    c2 = make_client(b)
    res = run_archive(b, c2)
    # 输入没变，重新生成走的是缓存（不花钱）；要不要绕过缓存换一版，是 Task 18 接口的事
    assert res["generated"]["threads"] == ["L-002"] and res["reused"]["threads"] == ["L-001"]
    assert load_index(b)["threads"]["L-002"]["outdated"] is False
    assert b.step("archive")["status"] == "done"


def test_线被删了_旧档案标过期不删文件(book_with_threads, fake_client):
    from ligaotai.archive import load_index, run_archive

    b = book_with_threads
    run_archive(b, fake_client)
    _edit_threads(b, lambda d: d.__setitem__("threads", d["threads"][:1]))
    c2 = make_client(b)
    res = run_archive(b, c2)
    assert res["outdated_removed"] == ["L-002"]
    assert (b.thread_archive_dir / "L-002.md").exists()
    assert load_index(b)["threads"]["L-002"]["outdated"] is True
    assert "archive/map" in c2.calls


# ---------- DE 审查必须修3：回填对不上的不静默 ----------


def test_回填不上的多个说法计数进summary(book_with_threads):
    """模型把受控属性下的主语写成材料里没有的名字，回填对不上：原样留着，但个数要进 summary。
    模型写的是别名（行者）时按规范名映射对得上。"""
    from ligaotai.archive import run_archive

    def world(user):
        return json.dumps({"body": "# W-01 测试世界\n\n### 兵器\n- **行者**：如意金箍棒 / 降妖宝杖（多个说法）[S-0001,S-0003]\n"
                                   "\n## 外貌\n- 林清：清瘦 / 胖（多个说法）[S-0001]\n"}, ensure_ascii=False)

    b = book_with_threads
    c = make_client(b, overrides={"archive/world": world})
    res = run_archive(b, c)
    body = (b.world_archive_dir / "W-01.md").read_text(encoding="utf-8")
    assert "降妖宝杖（多个说法，见矛盾 C-001）" in body
    assert res["unfilled_multi"] == 1


# ---------- DE 审查必须修5：交汇点进地图输入，变了地图重跑 ----------

_IX = {"thread": "L-002", "scene": "S-0004", "main_scene": "S-0002", "reason": "龙王献宝与取经同一场"}


def test_交汇点进地图输入_改了交汇只重跑地图(book_with_threads, fake_client):
    from ligaotai.archive import run_archive

    b = book_with_threads
    _edit_threads(b, lambda d: d["intersections"].append(dict(_IX)))
    run_archive(b, fake_client)
    user = map_user(fake_client)
    assert "龙王献宝与取经同一场" in user and "S-0004" in user

    _edit_threads(b, lambda d: d["intersections"][0].__setitem__("main_scene", "S-0003"))
    c2 = make_client(b)
    run_archive(b, c2)
    assert c2.calls == ["archive/map"]
    assert b.step("archive")["status"] == "done"


def test_途中只改了交汇_地图也算过期(book_with_threads):
    from ligaotai.archive import load_index, run_archive

    b = book_with_threads
    c = mutating(b, lambda d: d["intersections"].append(dict(_IX)), when=lambda tag: tag == "archive/map")
    res = run_archive(b, c)
    assert res["input_changed"] is True
    assert load_index(b)["map"]["outdated"] is True


# ---------- 每批组数上限（contradictions_max_batch_groups）接进编排 ----------


def test_矛盾每批组数上限按本书参数切批(book_with_threads):
    from ligaotai.archive import run_archive

    b = book_with_threads
    set_card(b, "S-0005", facts=[{"subject": "敖广", "attribute": "居所", "value": "西海龙宫", "quote": "敖广回了西海龙宫"}])
    b.update(lambda d: d["settings"].update(contradictions_max_batch_groups=1))
    c = make_client(b)
    run_archive(b, c)
    batches = [t for t in c.calls if t.startswith("archive/contradictions")]
    assert len(batches) == 2, "两个候选组、每批最多 1 组，要切成两批"
    assert len(read_json(b.contradictions_path)["groups"]) == 2


# ---------- DE 审查第 6 条（作者 9-19 拍板要做）：签名带提示词内容，改了提示词用到它的档案判过期 ----------


@pytest.fixture
def own_prompts(tmp_path, monkeypatch):
    """把提示词复制一份到临时目录，让测试可以改它（不动仓库里的 prompts/）。"""
    import shutil

    from ligaotai import prompts

    d = tmp_path / "prompts"
    shutil.copytree(prompts.PROMPTS_DIR, d)
    monkeypatch.setattr(prompts, "PROMPTS_DIR", d)
    return d


def _touch_prompt(d, name, section="system"):
    p = d / f"{name}.md"
    text = p.read_text(encoding="utf-8")
    head = f"## {section}\n"
    assert head in text
    p.write_text(text.replace(head, head + "（改了一个字）\n", 1), encoding="utf-8")


def test_签名带提示词内容_改世界设定集提示词只重跑世界(book_with_threads, own_prompts):
    from ligaotai.archive import run_archive

    b = book_with_threads
    run_archive(b, make_client(b))
    _touch_prompt(own_prompts, "archive_world")
    c2 = make_client(b)
    run_archive(b, c2)
    # 假模型重写出来的设定集跟原来一字不差，地图输入没变，地图不重跑（真模型写出来的不一样，地图会跟着重跑）
    assert c2.calls == ["archive/world/W-01"]
    assert b.step("archive")["status"] == "done"


def test_签名带提示词内容_改线档案提示词所有线重跑(book_with_threads, own_prompts):
    from ligaotai.archive import run_archive

    b = book_with_threads
    run_archive(b, make_client(b))
    _touch_prompt(own_prompts, "archive_thread", "user")
    c2 = make_client(b)
    run_archive(b, c2)
    assert sorted(c2.calls) == ["archive/thread/L-001", "archive/thread/L-002"]


def test_签名带提示词内容_改矛盾提示词矛盾重跑(book_with_threads, own_prompts):
    from ligaotai.archive import run_archive

    b = book_with_threads
    run_archive(b, make_client(b))
    _touch_prompt(own_prompts, "contradictions")
    c2 = make_client(b)
    run_archive(b, c2)
    assert [t for t in c2.calls if t.startswith("archive/contradictions")]
    assert not [t for t in c2.calls if t.startswith(("archive/thread", "archive/world"))]


def test_签名带提示词内容_改地图提示词只重跑地图(book_with_threads, own_prompts):
    from ligaotai.archive import run_archive

    b = book_with_threads
    run_archive(b, make_client(b))
    _touch_prompt(own_prompts, "map")
    c2 = make_client(b)
    run_archive(b, c2)
    assert c2.calls == ["archive/map"]


def test_只改提示词开头给人看的说明_不重跑(book_with_threads, own_prompts):
    """第一个「## system」之前的说明不发给模型，改它不该花钱。"""
    from ligaotai.archive import run_archive

    b = book_with_threads
    run_archive(b, make_client(b))
    for name in ("archive_thread", "archive_world", "contradictions", "map"):
        p = own_prompts / f"{name}.md"
        p.write_text("说明改了。\n" + p.read_text(encoding="utf-8"), encoding="utf-8")
    c2 = make_client(b)
    run_archive(b, c2)
    assert c2.calls == []
