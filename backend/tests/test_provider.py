import asyncio
import httpx
import pytest
from app.providers import DeepSeekProvider
from app.config import Settings
from app.errors import AppError


def settings():
    return Settings(_env_file=None, csrf_secret="test-secret-with-at-least-32-characters", deepseek_api_key="fake-test-key")


def test_deepseek_adapter_wire_contract():
    captured = []
    def handler(request):
        import json
        payload = json.loads(request.content)
        captured.append(payload)
        return httpx.Response(200, json={"model": "test-response-model", "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "choices": [{"finish_reason": "stop", "message": {"content": "{}", "reasoning_content": "must not persist"}}]})
    provider = DeepSeekProvider(settings(), httpx.MockTransport(handler))
    message, meta = asyncio.run(provider.complete([{"role": "user", "content": "JSON"}], final=True))
    assert captured[0]["thinking"] == {"type": "disabled"}
    assert captured[0]["response_format"] == {"type": "json_object"}
    assert captured[0]["messages"][-1]["role"] == "user"
    assert '"additionalProperties": false' in captured[0]["messages"][-1]["content"]
    assert "evidence_ids" in captured[0]["messages"][-1]["content"]
    assert "工具未提供的明细必须说明待核实" not in captured[0]["messages"][-1]["content"]
    assert "建议须标明" in captured[0]["messages"][-1]["content"]
    assert meta["prompt_release"] == "v12-claims-1"
    assert "reasoning_content" not in message
    assert meta["usage"]["prompt_tokens"] == 10 and meta["cost"] is None


@pytest.mark.parametrize("status,code", [(429, "PROVIDER_RATE_LIMITED"), (401, "PROVIDER_ERROR"), (503, "PROVIDER_ERROR")])
def test_http_errors(status, code):
    provider = DeepSeekProvider(settings(), httpx.MockTransport(lambda _: httpx.Response(status, text="sensitive provider text")))
    with pytest.raises(AppError) as caught:
        asyncio.run(provider.complete([]))
    assert caught.value.body["code"] == code
    assert "sensitive" not in str(caught.value)


def test_provider_network_timeout():
    def handler(request):
        raise httpx.ReadTimeout("sensitive", request=request)
    with pytest.raises(AppError) as caught:
        asyncio.run(DeepSeekProvider(settings(), httpx.MockTransport(handler)).complete([]))
    assert caught.value.body["code"] == "PROVIDER_TIMEOUT"
