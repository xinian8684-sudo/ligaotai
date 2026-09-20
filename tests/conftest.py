import json
import re

import pytest

from ligaotai.book import create_book
from ligaotai.fsutil import read_json, write_json
from ligaotai.jobs import JobCancelled


@pytest.fixture
def library(tmp_path):
    lib = tmp_path / "书库"
    lib.mkdir()
    return lib


@pytest.fixture
def book(library):
    return create_book(library, "测试书")


@pytest.fixture(autouse=True)
def _no_real_key(monkeypatch):
    """测试一律用不到真的 API key。"""
    monkeypatch.delenv("LIGAOTAI_API_KEY", raising=False)


STORY = {
    "1.txt": "第一章 雪夜\n林清年方十六，住在青州城外。\n\n第二章 离城\n清儿背着包袱出了门，赵五在后面跟着。",
    "2.txt": "第三章 天机\n林姑娘进了天机阁，赵五守在门口。",
}


@pytest.fixture
def story_book(book, tmp_path):
    """三个场景的小书：S-0001 林清，S-0002 清儿/赵五，S-0003 林姑娘/赵五/天机阁。"""
    from ligaotai.importer import run_import
    from ligaotai.scenes import run_split

    src = tmp_path / "稿"
    src.mkdir()
    for name, text in STORY.items():
        (src / name).write_text(text, encoding="utf-8")
    run_import(book, src)
    run_split(book)
    book.story_src = src
    return book


# --------------------------------------------------------------------------------------
# Task 23：步骤 7 全链路集成测试共用的 fixture（跟 tests/test_archive_run.py 用的是同一套
# 假模型套路：认提示词种类、拿真实场景编号/线编号现造回复，不能拿写死的编号糊弄，不然
# 换一本书结构就对不上 check_archive 的范围检查）。
# --------------------------------------------------------------------------------------

_ARCHIVE_SCENES = [{"id": f"S-{i:04d}", "source": "a.txt", "index": i - 1} for i in range(1, 7)]
_ARCHIVE_ENTS = [("person", "孙悟空", ["悟空", "行者"])]
_ARCHIVE_PERSONS = {
    "S-0001": ["悟空"], "S-0002": ["悟空"], "S-0003": ["行者"],
    "S-0004": ["敖广"], "S-0005": ["敖广"],
}
# S-0001/S-0003 对 (孙悟空, 兵器) 给了不同的值——矛盾扫描唯一的候选组来源。
_ARCHIVE_FACTS = {
    "S-0001": [{"subject": "悟空", "attribute": "兵器", "value": "如意金箍棒", "quote": "悟空掣出如意金箍棒"}],
    "S-0003": [{"subject": "行者", "attribute": "兵器", "value": "降妖宝杖", "quote": "行者举起降妖宝杖"}],
}
_ARCHIVE_HOOKS_PLANTED = {"S-0002": ["紧箍咒的来历"]}
_ARCHIVE_TEXTS = {"S-0006": "花果山在东胜神洲，是十洲之祖脉。"}


def _archive_threads_data() -> dict:
    return {
        "next_world": 2, "next_thread": 3, "time_unit": "年", "main_thread": "L-001", "main_by": "auto",
        "worlds": [{"id": "W-01", "name": "西游世界", "reason": "测试", "status": "draft",
                    "notes": ["S-0006"], "outlines": []}],
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
        "unassigned": [],
        "pending": [],
    }


def _archive_set_card(book, sid, **changes):
    from ligaotai.cards import card_path

    rec = read_json(card_path(book, sid))
    rec["card"].update(changes)
    write_json(card_path(book, sid), rec)


@pytest.fixture
def book_with_threads(book):
    """步骤 4→7 全链路集成测试共用的小书：6 个场景、W-01 一个世界、L-001/L-002 两条线、
    1 个 gap；S-0001/S-0003 对 (孙悟空, 兵器) 给了不同的值，供矛盾扫描找候选。"""
    from helpers import seed_book

    seed_book(book, [
        {**s, "text": _ARCHIVE_TEXTS.get(s["id"], f"{s['id']} 的正文。"),
         "persons": _ARCHIVE_PERSONS.get(s["id"], []),
         "kind": "设定笔记" if s["id"] == "S-0006" else "正文"}
        for s in _ARCHIVE_SCENES
    ], entities=_ARCHIVE_ENTS)
    for sid in [s["id"] for s in _ARCHIVE_SCENES]:
        _archive_set_card(book, sid, facts=_ARCHIVE_FACTS.get(sid, []),
                          hooks_planted=_ARCHIVE_HOOKS_PLANTED.get(sid, []), hooks_resolved=[])
    write_json(book.threads_path, _archive_threads_data())
    return book


_SID = re.compile(r"S-\d{4}")


def _archive_reply_thread(user: str) -> tuple[str, str]:
    """每一行都带场景编号——「缺口」「开放的伏笔」两节也不例外（哪怕没内容也带一个引用），
    不然 check_refs 的无引用句率一算就爆表，测不出真正想测的编造率/范围问题。"""
    tid = re.search(r"线编号：(L-\d+)", user).group(1)
    ids = re.findall(r"^(S-\d{4})｜", user, re.M)
    first, last = ids[0], ids[-1]
    body = (f"# {tid} 测试\n\n## 来龙去脉\n"
            + "".join(f"第 {i} 块 [{s}]。" for i, s in enumerate(ids))
            + f"\n\n## 主要人物\n- 孙悟空：主角 [{first}]\n\n## 写到哪\n- 最后一块：[{last}]\n\n"
            f"## 缺口\n- 无 [{first}]\n\n## 开放的伏笔\n- 无 [{first}]\n")
    return f"thread/{tid}", body


def _archive_reply_world(user: str) -> tuple[str, str]:
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


def _archive_reply_contradictions(user: str) -> tuple[str, dict]:
    groups = []
    for block in re.split(r"\n\n(?=C-\d{3} )", user.split("\n\n", 1)[1]):
        cid = block.split(" ", 1)[0]
        sid = _SID.search(block).group(0)
        groups.append({"id": cid, "status": "真矛盾", "level": "严重", "category": "人物",
                       "reason": f"测试 [{sid}]"})
    first = groups[0]["id"] if groups else "none"
    return f"contradictions/{first}", {"groups": groups}


def _make_archive_client(book, overrides: dict | None = None, on_call=None):
    """造一个假 LLMClient，按提示词种类现算合格回复（跟 tests/test_archive_run.py 同一套写法）。

    `client.calls`：每次真的打到假后端上的调用标签（缓存命中时不会追加，因为
    `Caller.call()` 命中缓存就不会调 `client.chat_json`，假后端压根不会被触发）。
    `client.model_calls`：同一个计数，单独暴露一个整数属性，方便测试直接断言
    「这一轮一次模型都没调」，不用每次都去数 `len(client.calls)`。
    `overrides`：{标签前缀: fn(user) -> 回复}，回复可以是字符串/dict，也可以是异常实例
    （比如 `LLMError`、`FatalLLMError`）——假后端见到异常实例会直接抛出。
    `on_call`：每次真调用之后回调 `(tag, messages)`，给 `mutating_client` 这类
    「模型跑到一半，作者动了上游文件」的场景用。
    """
    from helpers import FakeBackend
    from ligaotai.config import AppConfig
    from ligaotai.llm import LLMClient

    overrides = overrides or {}
    record: list = []
    backend = FakeBackend(handler=None)
    client = LLMClient(AppConfig(), backend, log_dir=book.logs_dir)
    client.calls = record
    client.model_calls = 0

    def handler(tier, messages):
        system, user = messages[0]["content"], messages[1]["content"]
        if "全书地图" in system:
            sid = _SID.search(user).group(0)
            tag, out = "map", json.dumps({"body": f"# 全书地图\n\n## 全书概况\n讲了个故事 [{sid}]。"},
                                        ensure_ascii=False)
        elif "这条线的档案" in system:
            tag, body = _archive_reply_thread(user)
            out = json.dumps({"body": body}, ensure_ascii=False)
        elif "设定集" in system:
            tag, body = _archive_reply_world(user)
            out = json.dumps({"body": body}, ensure_ascii=False)
        elif "逐组判断" in system:
            tag, data = _archive_reply_contradictions(user)
            out = json.dumps(data, ensure_ascii=False)
        else:
            raise AssertionError("没见过的提示词")
        tag = f"archive/{tag}"
        record.append(tag)
        client.model_calls += 1
        if on_call is not None:
            on_call(tag, messages)
        for prefix, fn in overrides.items():
            if tag.startswith(prefix):
                return fn(user)
        return out

    backend.handler = handler
    return client


@pytest.fixture
def fake_client(book_with_threads):
    return _make_archive_client(book_with_threads)


@pytest.fixture
def failing_world_client(book_with_threads):
    """世界设定集那次调用一直失败，其余照常——跟 test_archive_run.py 的同名 fixture 一个套路。"""
    from ligaotai.llm import LLMError

    return _make_archive_client(book_with_threads, overrides={"archive/world": lambda u: LLMError("假的失败")})


@pytest.fixture
def mutating_client(book_with_threads):
    """第一次真调用之后，偷偷往 世界与支线.json 加一条线改名——模拟作者在跑的途中动了归线结果。"""
    b = book_with_threads
    done = {"x": False}

    def on_call(tag, messages):
        if not done["x"]:
            done["x"] = True
            data = read_json(b.threads_path, {})
            data["threads"][1]["name"] = "龙宫夜宴"
            write_json(b.threads_path, data)

    return _make_archive_client(b, on_call=on_call)


@pytest.fixture
def fatal_client(book_with_threads):
    """随便哪次调用都直接欠费：验证 FatalLLMError 会让整个步骤失败、不会被当成普通失败吞掉。"""
    from ligaotai.llm import FatalLLMError

    return _make_archive_client(book_with_threads, overrides={"archive/": lambda u: FatalLLMError("假的欠费")})


@pytest.fixture
def cancelling_client(book_with_threads):
    """假模型本身照常应答；`JobCancelled` 真正要抛的位置是 `progress` 回调，不是后端——
    `llm.LLMClient._call` 只放行 `LLMError`（含 `FatalLLMError`），别的异常一律会被
    包装成普通 `LLMError`，从假后端里直接抛 `JobCancelled` 只会变成一次「这一项调用失败」，
    测不出「暂停」这条路径（这是任务书 task23.md 里 `cancelling_client` 描述和实际代码
    对不上的地方，写测试时改用真实生效的机制，见报告）。

    这个 fixture 顺带挂一个 `.progress`：跑够几次进度回调就抛 `JobCancelled`，
    模拟作者在跑到一半时点了暂停；调用方拿 `run_archive(book, cancelling_client,
    cancelling_client.progress)` 用。"""
    client = _make_archive_client(book_with_threads)
    n = {"k": 0}

    def progress(done, total, message=""):
        n["k"] += 1
        if n["k"] > 5:
            raise JobCancelled("已暂停")

    client.progress = progress
    return client


@pytest.fixture
def make_archive_client():
    """给测试自己再造一个 client（比如重跑第二轮）用，跟 fixture 里那几个共用同一套假模型逻辑。"""
    return _make_archive_client
