import asyncio
import json

import httpx
import pytest
from helpers import FakeBackend

from ligaotai.config import KEY_ENV, AppConfig
from ligaotai.llm import NoKeyError, OpenAIBackend, check_model

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
