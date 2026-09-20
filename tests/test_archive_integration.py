"""Task 23：步骤 4→7 的全链路集成测试（假模型，零花费）。

跑通整条链——建书 → 归线 → 步骤 7 四件产出（支线档案 / 世界设定集 / 矛盾扫描 / 全书地图）
→ 验收工具（tools/eval_archives.py 的 check_refs）——验证每一环的契约真的能对上，不是
「自己捏一套假设、自己验证」：check_refs 用的 bodies/allowed/existing/lenient 全部来自
`load_scopes_and_bodies(book)`，直接读 run_archive 真正落盘的 档案/index.json 和产物文件，
不手工拼一份材料塞给它。

fixture（book_with_threads / fake_client / cancelling_client / fatal_client /
make_archive_client）在 tests/conftest.py 里，跟 tests/test_archive_run.py 用的是
同一套「认提示词种类、拿真实场景/线编号现造回复」的假模型写法。
"""

import pytest

from ligaotai.archive import load_index, run_archive
from ligaotai.fsutil import read_json, write_json
from ligaotai.jobs import JobCancelled
from ligaotai.llm import FatalLLMError
from tools.eval_archives import check_refs, load_scopes_and_bodies


def test_从场景卡跑到地图(book_with_threads, fake_client):
    """跑完步骤 7，四件产出都在、内容结构合格，引用核对一条都不该不合格。"""
    b = book_with_threads
    res = run_archive(b, fake_client)

    # ---- 编排结果：数字对得上这本小书的真实结构（2 条线、1 个世界、1 组候选矛盾）----
    assert res["threads"] == 2 and res["worlds"] == 1
    assert res["contradictions"] == 1 and res["严重"] == 1
    assert res["calls"] == 5  # L-001、L-002、W-01、矛盾一批、地图
    assert b.step("archive")["status"] == "done"
    assert sorted(fake_client.calls) == sorted([
        "archive/thread/L-001", "archive/thread/L-002", "archive/world/W-01",
        "archive/contradictions/C-000", "archive/map",
    ])

    # ---- 四件产出都落了盘 ----
    assert (b.thread_archive_dir / "L-001.md").exists()
    assert (b.thread_archive_dir / "L-002.md").exists()
    assert (b.world_archive_dir / "W-01.md").exists()
    assert b.contradictions_path.exists()
    assert b.map_path.exists()

    # ---- 支线档案：必须有的小节一个不能少 ----
    for tid in ("L-001", "L-002"):
        body = (b.thread_archive_dir / f"{tid}.md").read_text(encoding="utf-8")
        for heading in ("来龙去脉", "主要人物", "写到哪", "缺口", "开放的伏笔"):
            assert f"## {heading}" in body, f"{tid}.md 缺 {heading} 小节"

    # ---- 矛盾扫描：候选组确实是模型判断算出来的「真矛盾/严重」，编号规则是 C-001 起 ----
    contra = read_json(b.contradictions_path)
    assert len(contra["groups"]) == 1
    [g] = contra["groups"]
    assert g["id"] == "C-001"
    assert (g["subject"], g["attribute"]) == ("孙悟空", "兵器")
    assert (g["status"], g["level"], g["category"]) == ("真矛盾", "严重", "人物")
    values = {v["value"] for v in g["values"]}
    assert values == {"如意金箍棒", "降妖宝杖"}

    # ---- 回填：世界设定集里的「（多个说法）」在地图跑之前就该补上这组的 C- 编号 ----
    world_body = (b.world_archive_dir / "W-01.md").read_text(encoding="utf-8")
    assert "（多个说法，见矛盾 C-001）" in world_body
    assert "（多个说法）" not in world_body.replace("（多个说法，见矛盾 C-001）", "")

    # ---- 全书地图：必须有的小节在、且引用了真实场景编号 ----
    map_body = b.map_path.read_text(encoding="utf-8")
    assert "## 全书概况" in map_body

    # ---- 验收工具能吃下这些产出并算出数：中间数据全部来自 run_archive 真正落盘的
    #      档案/index.json + 产物文件，不是这个测试自己手工拼的一份材料。----
    bodies, allowed, existing, lenient, outdated = load_scopes_and_bodies(b)
    assert set(bodies) == {"L-001", "L-002", "W-01", "全书地图"}
    assert existing == {f"S-{i:04d}" for i in range(1, 7)}
    assert outdated == {"threads": [], "worlds": [], "map": False, "map_blocked_by": []}

    check = check_refs(bodies, allowed, existing, lenient)
    assert check["bad"] == 0, check["details"]
    assert check["no_ref_rate"] <= 0.10
    assert check["fabricated_rate"] <= 0.02


def test_缓存命中第二次不花钱(book_with_threads, fake_client, make_archive_client):
    """产物删掉但 index.json 和档案自己的缓存还在：重跑应该整轮命中缓存，一次模型都不调。"""
    b = book_with_threads
    run_archive(b, fake_client)
    assert fake_client.model_calls == 5
    assert len(read_json(b.archive_cache_path)) == 5

    b.map_path.unlink()  # 只删产物，不动 index.json / 档案自己的缓存文件
    c2 = make_archive_client(b)
    res = run_archive(b, c2)

    assert c2.model_calls == 0, "输入没变，缓存该挡住，不该真调模型"
    assert c2.calls == []
    assert b.map_path.exists(), "地图产物要从缓存里重新写出来，不是干脆不管"
    assert b.step("archive")["status"] == "done"
    assert res["calls"] == 0


def test_暂停能取消(book_with_threads, cancelling_client, make_archive_client):
    """作者跑到一半点了暂停：已经做完的落盘不丢，重跑接着做，两次加起来跟一次跑完调用次数一样。

    真实的 JobCancelled 只能从 `progress` 回调抛出——`llm.LLMClient._call` 只放行
    `LLMError`（含 `FatalLLMError`），别的异常一律被包成普通 `LLMError`，从假后端直接
    抛 `JobCancelled` 测不出「暂停」这条路径。`cancelling_client` fixture 挂了一个
    `.progress`，走的是 tests/test_archive_run.py 已经验证过的机制。
    """
    b = book_with_threads
    with pytest.raises(JobCancelled):
        run_archive(b, cancelling_client, cancelling_client.progress)

    idx = load_index(b)
    written = [f"archive/thread/{t}" for t in idx["threads"]] + [f"archive/world/{w}" for w in idx["worlds"]]
    assert written, "暂停前做完的档案要落盘并记进 index"
    assert "archive/map" not in cancelling_client.calls, "地图要等三件都完成才跑，暂停时不该跑到这一步"

    c2 = make_archive_client(b)
    run_archive(b, c2)
    assert not set(written) & set(c2.calls), "已经落盘的档案不该重调"
    assert cancelling_client.model_calls + c2.model_calls == 5
    assert b.step("archive")["status"] == "done"


def test_欠费直接让整步失败(book_with_threads, fatal_client):
    """欠费（FatalLLMError）不能被当成「这一项调用失败」悄悄吞掉，整个步骤要失败。"""
    b = book_with_threads
    with pytest.raises(FatalLLMError):
        run_archive(b, fatal_client)

    # 用量记录的桶要建好（哪怕这次是 0）：FatalLLMError 在拿到 Reply、算进 usage 之前就
    # 从 backend 直接抛出，client.usage.calls 本来就是 0，这不是 bug——真按量计费的接口，
    # 请求在网络层就被拒绝时本就没有 token 用量。这里只确认 usage 分桶机制没被异常绕过。
    assert b.load()["usage"]["by_step"]["archive"]["calls"] == 0
    # 不该有任何产物落盘——欠费时生成的东西不可信
    assert list(b.thread_archive_dir.glob("*.md")) == []
    assert list(b.world_archive_dir.glob("*.md")) == []
    assert not b.contradictions_path.exists()
    assert not b.map_path.exists()


def test_单独重跑一条线不动别的(book_with_threads, fake_client, make_archive_client):
    """改一条线的场景成员：只有这条线（以及跟着重跑的地图，因为它读的是全部档案正文）
    真的调用模型，另一条线和世界设定集的文件内容要一个字都不变。

    （task23.md 原设计是标 index 里的 outdated=True 后重跑；实测那条路径的输入文本
    一个字没变，会命中 archive.py 自己的模型调用缓存（Caller.cache，按渲染文本算键），
    假后端压根不会被再次触发——`res["generated"]` 会显示"重新生成了"，但 `client.calls`
    里不会出现对应标签，这是 archive.py 的既有设计（注释里写明"要不要绕过缓存换一版，是
    Task 18 接口的事"），不是 bug。改成本测试这种"真的改了输入文本"的方式，才能验证
    "只有受影响的这条线真花钱调用模型"。）
    """
    b = book_with_threads
    run_archive(b, fake_client)
    world_before = (b.world_archive_dir / "W-01.md").read_text(encoding="utf-8")
    l2_before = (b.thread_archive_dir / "L-002.md").read_text(encoding="utf-8")

    data = read_json(b.threads_path, {})
    data["threads"][0]["scenes"].append("S-0006")  # 只动 L-001 的成员
    write_json(b.threads_path, data)

    c2 = make_archive_client(b)
    run_archive(b, c2)

    assert "archive/thread/L-001" in c2.calls
    assert "archive/map" in c2.calls, "地图读全部档案正文，L-001 变了地图也该跟着重跑"
    assert "archive/thread/L-002" not in c2.calls, "没动的线不该真调模型"
    assert "archive/world/W-01" not in c2.calls, "世界没变不该真调模型"
    assert not [t for t in c2.calls if t.startswith("archive/contradictions")], "facts 没变，矛盾不该重跑"
    assert (b.thread_archive_dir / "L-002.md").read_text(encoding="utf-8") == l2_before
    assert (b.world_archive_dir / "W-01.md").read_text(encoding="utf-8") == world_before
    assert b.step("archive")["status"] == "done"
