import asyncio

import pytest
from helpers import FakeBackend

from ligaotai.config import AppConfig, TierConfig, mask_key
from ligaotai.llm import FatalLLMError, LLMClient, LLMError, Reply, Usage, parse_json


def run(coro):
    return asyncio.run(coro)


def ok(data):
    return []


def make(backend, **cfg):
    return LLMClient(AppConfig(**cfg), backend)


def test_parse_json_strips_fence():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json("[1, 2]")


def test_first_try_ok():
    fb = FakeBackend(['{"a": 1}'])
    c = make(fb)
    assert run(c.chat_json("batch", "sys", "user", ok, tag="t")) == ({"a": 1}, [])
    assert (c.usage.calls, c.usage.prompt_tokens, c.usage.completion_tokens) == (1, 100, 20)
    assert fb.calls[0]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]
    assert fb.calls[0]["max_tokens"] == 8192


def test_bad_json_is_fed_back():
    fb = FakeBackend(["不是json", '{"a": 1}'])
    assert run(make(fb).chat_json("batch", "s", "u", ok, tag="t")) == ({"a": 1}, [])
    msgs = fb.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[2]["content"] == "不是json"
    assert "JSON" in msgs[3]["content"]


def test_check_problems_are_fed_back():
    fb = FakeBackend(['{"a": 0}', '{"a": 1}'])

    def check(d):
        return [] if d["a"] == 1 else ["a 必须是 1"]

    assert run(make(fb).chat_json("batch", "s", "u", check, tag="t")) == ({"a": 1}, [])
    assert "a 必须是 1" in fb.calls[1]["messages"][3]["content"]


def test_persistent_problems_return_last_data():
    fb = FakeBackend(['{"a": 0}'] * 3)
    data, problems = run(make(fb).chat_json("batch", "s", "u", lambda d: ["还是不对"], tag="t"))
    assert (data, problems, len(fb.calls)) == ({"a": 0}, ["还是不对"], 3)


def test_returns_result_with_fewest_problems_not_the_last_one():
    """重试用尽时应该返回问题最少的一次，不是最后一次解析成功的那次。
    第 1 次 2 个问题、第 2 次 1 个问题、第 3 次 3 个问题 → 应该返回第 2 次的结果。"""
    fb = FakeBackend(['{"n": 1}', '{"n": 2}', '{"n": 3}'])
    problem_counts = {1: 2, 2: 1, 3: 3}

    def check(d):
        return [f"问题{i}" for i in range(problem_counts[d["n"]])]

    data, problems = run(make(fb).chat_json("batch", "s", "u", check, tag="t"))
    assert (data, problems) == ({"n": 2}, ["问题0"])


def test_empty_reply_retried_as_is():
    fb = FakeBackend([Reply(content=""), '{"a": 1}'])
    assert run(make(fb).chat_json("batch", "s", "u", ok, tag="t"))[0] == {"a": 1}
    assert len(fb.calls[1]["messages"]) == 2


def test_truncated_reply_retried_with_more_tokens():
    fb = FakeBackend([Reply(content='{"a": ', finish_reason="length"), '{"a": 1}'])
    run(make(fb).chat_json("batch", "s", "u", ok, tag="t"))
    assert fb.calls[1]["max_tokens"] == 16384
    assert len(fb.calls[1]["messages"]) == 2


def test_truncated_with_empty_content_doubles_tokens():
    """思考模式把 max_tokens 用光时，回复是 content="" + finish_reason="length"。
    截断判断必须排在空内容判断前面，否则额度不会翻倍，白白再花一次满额度的钱。"""
    fb = FakeBackend([Reply(content="", finish_reason="length"), '{"a": 1}'])
    run(make(fb).chat_json("synth", "s", "u", ok, tag="t"))
    assert fb.calls[1]["max_tokens"] == 65536


def test_truncated_does_not_shrink_max_tokens():
    """max_tokens=100000 时，min(200000, 65536)=65536 反而比原值小，翻倍不能把额度调小。"""
    fb = FakeBackend([Reply(content="x", finish_reason="length"), '{"a": 1}'])
    cfg = AppConfig(synth=TierConfig(max_tokens=100000))
    c = LLMClient(cfg, fb)
    run(c.chat_json("synth", "s", "u", ok, tag="t"))
    assert fb.calls[1]["max_tokens"] == 100000


def test_never_parseable_raises():
    fb = FakeBackend(["坏"] * 3)
    with pytest.raises(LLMError):
        run(make(fb).chat_json("batch", "s", "u", ok, tag="t"))
    assert len(fb.calls) == 3


def test_auth_error_is_fatal():
    class Denied(Exception):
        status_code = 401

    with pytest.raises(FatalLLMError):
        run(make(FakeBackend([Denied("bad key")])).chat_json("batch", "s", "u", ok, tag="t"))


@pytest.mark.parametrize("status", [402, 403])
def test_payment_or_forbidden_error_is_fatal(status):
    class Denied(Exception):
        status_code = status

    with pytest.raises(FatalLLMError):
        run(make(FakeBackend([Denied("no")])).chat_json("batch", "s", "u", ok, tag="t"))


def test_upstream_error_key_is_masked():
    """M7：中转站如果把完整 key 回显在错误原文里，异常信息里不能出现原 key（复用 config
    里已有的打码函数），否则 key 会顺着 job.error / book.json / /api 的返回泄露出去。"""

    class Denied(Exception):
        status_code = 401

    key = "sk-SECRET123456"
    c = make(FakeBackend([Denied(f"Error code: 401 - Your api key: {key} is invalid")]), api_key=key)
    with pytest.raises(FatalLLMError) as ei:
        run(c.chat_json("batch", "s", "u", ok, tag="t"))
    assert key not in str(ei.value)
    assert mask_key(key) in str(ei.value)


def test_upstream_error_key_is_masked_for_item_error():
    """同一处打码逻辑也要覆盖非 401/402/403 的普通 LLMError 路径。"""
    key = "sk-SECRET123456"
    c = make(FakeBackend([RuntimeError(f"timeout, key={key}")]), api_key=key)
    with pytest.raises(LLMError) as ei:
        run(c.chat_json("batch", "s", "u", ok, tag="t"))
    assert key not in str(ei.value)
    assert mask_key(key) in str(ei.value)


def test_other_error_is_item_error():
    fb = FakeBackend([RuntimeError("timeout")])
    with pytest.raises(LLMError) as ei:
        run(make(fb).chat_json("batch", "s", "u", ok, tag="t"))
    assert not isinstance(ei.value, FatalLLMError)
    assert len(fb.calls) == 1


def test_backend_fatal_error_passes_through_unchanged():
    """后端自己抛的 FatalLLMError（比如自定义的欠费判断）不该被 _call 降级成普通 LLMError。"""
    with pytest.raises(FatalLLMError):
        run(make(FakeBackend([FatalLLMError("余额不足")])).chat_json("batch", "s", "u", ok, tag="t"))


def test_parseable_with_problems_then_unparseable_returns_first_result():
    """第一次解析成功但带问题，后两次都不是合法 JSON：应该返回第一次那次的 (结果, 问题)。"""
    fb = FakeBackend(['{"a": 0}', "坏1", "坏2"])

    def check(d):
        return ["a 必须是 1"]

    data, problems = run(make(fb).chat_json("batch", "s", "u", check, tag="t"))
    assert (data, problems) == ({"a": 0}, ["a 必须是 1"])


def test_synth_tier():
    fb = FakeBackend(['{"a": 1}'])
    run(make(fb).chat_json("synth", "s", "u", ok, tag="t"))
    assert fb.calls[0]["tier"].thinking == "on"
    assert fb.calls[0]["max_tokens"] == 32768


def test_unknown_tier():
    with pytest.raises(ValueError):
        make(FakeBackend([])).tier("big")


def test_log_written_without_key(tmp_path):
    c = LLMClient(AppConfig(api_key="sk-secret-123456"), FakeBackend(['{"a": 1}']), log_dir=tmp_path / "日志")
    run(c.chat_json("batch", "s", "u", ok, tag="cards/S-0001"))
    log = tmp_path / "日志" / "cards" / "S-0001-1.json"
    text = log.read_text(encoding="utf-8")
    assert "sk-secret" not in text
    assert '"u"' in text


def test_concurrency_limited():
    fb = FakeBackend(handler=lambda tier, messages: '{"a": 1}', delay=0.02)
    c = make(fb, concurrency=3)

    async def many():
        await asyncio.gather(*(c.chat_json("batch", "s", "u", ok, tag=f"t{i}") for i in range(10)))

    run(many())
    assert len(fb.calls) == 10
    assert fb.max_active == 3


def test_client_reusable_across_two_event_loops():
    """同一个 client 跨两次 asyncio.run 用：信号量不能绑死第一个事件循环。
    asyncio.Semaphore 只有真的等待过（发生过并发争抢）才会绑定循环，所以并发度设成 1，
    每轮跑两个并发任务逼出等待路径，不然测不出这个坑。"""
    fb = FakeBackend(handler=lambda tier, messages: '{"a": 1}', delay=0.01)
    c = make(fb, concurrency=1)

    async def twice(prefix):
        await asyncio.gather(
            c.chat_json("batch", "s", "u", ok, tag=f"{prefix}-1"),
            c.chat_json("batch", "s", "u", ok, tag=f"{prefix}-2"),
        )

    run(twice("a"))
    run(twice("b"))
    assert len(fb.calls) == 4


def test_log_failure_does_not_fail_the_call(tmp_path, monkeypatch):
    """写日志失败（比如没权限）不该让已经花了钱的这次调用也跟着失败。"""
    import ligaotai.llm as llm_module

    def boom(*a, **k):
        raise PermissionError("没有写权限")

    monkeypatch.setattr(llm_module, "write_json", boom)
    c = LLMClient(AppConfig(), FakeBackend(['{"a": 1}']), log_dir=tmp_path / "日志")
    assert run(c.chat_json("batch", "s", "u", ok, tag="t")) == ({"a": 1}, [])


def test_usage_cost():
    u = Usage(calls=1, prompt_tokens=1_000_000, completion_tokens=500_000)
    assert u.cost(AppConfig()) == pytest.approx(0.30 + 0.60)
