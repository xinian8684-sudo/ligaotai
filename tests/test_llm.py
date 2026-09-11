import asyncio

import pytest
from helpers import FakeBackend

from ligaotai.config import AppConfig
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


def test_empty_reply_retried_as_is():
    fb = FakeBackend([Reply(content=""), '{"a": 1}'])
    assert run(make(fb).chat_json("batch", "s", "u", ok, tag="t"))[0] == {"a": 1}
    assert len(fb.calls[1]["messages"]) == 2


def test_truncated_reply_retried_with_more_tokens():
    fb = FakeBackend([Reply(content='{"a": ', finish_reason="length"), '{"a": 1}'])
    run(make(fb).chat_json("batch", "s", "u", ok, tag="t"))
    assert fb.calls[1]["max_tokens"] == 16384
    assert len(fb.calls[1]["messages"]) == 2


def test_never_parseable_raises():
    with pytest.raises(LLMError):
        run(make(FakeBackend(["坏"] * 3)).chat_json("batch", "s", "u", ok, tag="t"))


def test_auth_error_is_fatal():
    class Denied(Exception):
        status_code = 401

    with pytest.raises(FatalLLMError):
        run(make(FakeBackend([Denied("bad key")])).chat_json("batch", "s", "u", ok, tag="t"))


def test_other_error_is_item_error():
    with pytest.raises(LLMError) as ei:
        run(make(FakeBackend([RuntimeError("timeout")])).chat_json("batch", "s", "u", ok, tag="t"))
    assert not isinstance(ei.value, FatalLLMError)


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
    assert fb.max_active <= 3


def test_usage_cost():
    u = Usage(calls=1, prompt_tokens=1_000_000, completion_tokens=500_000)
    assert u.cost(AppConfig()) == pytest.approx(0.30 + 0.60)
