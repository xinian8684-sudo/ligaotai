import asyncio
import json

import httpx
import pytest
from helpers import FakeBackend

from ligaotai.config import KEY_ENV, AppConfig, TierConfig
from ligaotai.llm import FatalLLMError, LLMClient, LLMError, NoKeyError, OpenAIBackend, check_model, request_extras

MSGS = [{"role": "user", "content": "输出 json"}]


def completion(content='{"ok": true}', finish="stop"):
    return {
        "id": "x", "object": "chat.completion", "created": 0, "model": "deepseek-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    }


def make_backend(cfg, status=200, body=None):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json=body if body is not None else completion())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAIBackend(cfg, http_client=client), seen


def test_batch_request_shape():
    cfg = AppConfig(api_key="sk-test-123456")
    backend, seen = make_backend(cfg)
    reply = asyncio.run(backend.complete(cfg.batch, MSGS, 100))
    assert (reply.content, reply.finish_reason, reply.prompt_tokens, reply.completion_tokens) == (
        '{"ok": true}', "stop", 7, 3,
    )
    request = seen[0]
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-test-123456"
    body = json.loads(request.content)
    assert (body["model"], body["max_tokens"]) == ("deepseek-flash", 100)
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in body


def test_synth_request_turns_thinking_on():
    cfg = AppConfig(api_key="sk-test-123456")
    backend, seen = make_backend(cfg)
    asyncio.run(backend.complete(cfg.synth, MSGS, 100))
    body = json.loads(seen[0].content)
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "high"


def test_default_thinking_sends_nothing_extra():
    cfg = AppConfig(api_key="sk-test-123456")
    tier = cfg.batch.model_copy(update={"thinking": "default", "json_mode": False})
    backend, seen = make_backend(cfg)
    asyncio.run(backend.complete(tier, MSGS, 100))
    body = json.loads(seen[0].content)
    assert "thinking" not in body and "response_format" not in body


def test_request_extras_off_with_effort_skips_reasoning_effort():
    """关着思考时发强度没意义，还可能被别家接口拒绝：thinking=off 时不发 reasoning_effort。"""
    tier = TierConfig(thinking="off", effort="high")
    assert request_extras(tier) == {"thinking": {"type": "disabled"}}


def test_request_extras_default_with_effort_sends_it():
    """thinking=default 时用户明确填了 effort 就尊重它。"""
    tier = TierConfig(thinking="default", effort="high")
    assert request_extras(tier) == {"reasoning_effort": "high"}


def test_request_extras_default_without_effort_sends_nothing():
    tier = TierConfig(thinking="default", effort="")
    assert request_extras(tier) == {}


def test_auth_error_carries_status_code():
    cfg = AppConfig(api_key="sk-test-123456")
    backend, _ = make_backend(cfg, status=401, body={"error": {"message": "bad key"}})
    with pytest.raises(Exception) as ei:
        asyncio.run(backend.complete(cfg.batch, MSGS, 100))
    assert getattr(ei.value, "status_code", None) == 401


def test_no_key():
    with pytest.raises(NoKeyError):
        OpenAIBackend(AppConfig())


def test_key_from_env(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "sk-env-123456")
    cfg = AppConfig()
    backend, seen = make_backend(cfg)
    asyncio.run(backend.complete(cfg.batch, MSGS, 10))
    assert seen[0].headers["authorization"] == "Bearer sk-env-123456"


def test_check_model_reports_each_tier():
    results = check_model(AppConfig(), FakeBackend(['{"ok": true}', RuntimeError("down"), RuntimeError("down")]))
    assert [(r["tier"], r["ok"]) for r in results] == [("batch", True), ("synth", False)]
    assert "down" in results[1]["error"]
    assert results[0]["model"] == "deepseek-flash"


def _fast_failing_backend(cfg, exc):
    """MockTransport 的 handler 直接抛网络异常；SDK 自带的 max_retries 改成 0，
    不然默认 4 次重试会真的 sleep 退避，测试跑得很久。"""

    def handler(request):
        raise exc

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = OpenAIBackend(cfg, http_client=http_client)
    backend._client = backend._client.with_options(max_retries=0)
    return backend


@pytest.mark.parametrize("exc", [httpx.TimeoutException("超时"), httpx.ConnectError("连不上")])
def test_network_error_is_retryable_not_fatal(exc):
    cfg = AppConfig(api_key="sk-test-123456")
    backend = _fast_failing_backend(cfg, exc)
    client = LLMClient(cfg, backend)
    with pytest.raises(LLMError) as ei:
        asyncio.run(client.chat_json("batch", "s", "u", lambda d: [], tag="t", max_attempts=1))
    assert not isinstance(ei.value, FatalLLMError)


def test_null_message_content_becomes_empty_reply():
    cfg = AppConfig(api_key="sk-test-123456")
    backend, _ = make_backend(cfg, body=completion(content=None))
    reply = asyncio.run(backend.complete(cfg.batch, MSGS, 100))
    assert reply.content == ""


def test_null_message_content_triggers_empty_reply_retry():
    cfg = AppConfig(api_key="sk-test-123456")
    calls = []

    def handler(request):
        calls.append(request)
        body = completion(content=None) if len(calls) == 1 else completion(content='{"ok": true}')
        return httpx.Response(200, json=body)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = OpenAIBackend(cfg, http_client=http_client)
    client = LLMClient(cfg, backend)
    data, problems = asyncio.run(client.chat_json("batch", "s", "u", lambda d: [], tag="t"))
    assert (data, problems, len(calls)) == ({"ok": True}, [], 2)


def test_check_model_runs_both_tiers_concurrently():
    fb = FakeBackend(handler=lambda tier, messages: '{"ok": true}', delay=0.05)
    results = check_model(AppConfig(), fb)
    assert [r["tier"] for r in results] == ["batch", "synth"]
    assert fb.max_active == 2
