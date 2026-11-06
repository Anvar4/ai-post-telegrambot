import base64
import json
from typing import Any

import httpx
import httpx2
import respx

from app.ai.images.fal_img import FalImageClient
from app.ai.images.openai_img import OpenAIImageClient
from app.ai.images.replicate_img import ReplicateImageClient
from app.ai.images.stability_img import StabilityImageClient
from app.ai.providers.anthropic import AnthropicClient
from app.ai.providers.gemini import GeminiClient
from app.ai.providers.openai import OpenAIClient
from app.ai.providers.openai_compat import OpenAICompatClient
from app.ai.types import Message


def mock_http(handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def chat_response(text: str, prompt: int = 12, completion: int = 7, cached: int = 0) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-6-sol",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "prompt_tokens_details": {"cached_tokens": cached},
        },
    }


async def test_openai_client_parses_usage_and_sends_json_mode() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=chat_response('{"a": 1}', cached=5))

    client = OpenAIClient("sk-test", "gpt-6-sol", http_client=mock_http(handler))
    res = await client.complete(
        [Message("system", "s"), Message("user", "u")], json_mode=True, max_tokens=300
    )
    assert res.text == '{"a": 1}'
    assert (res.input_tokens, res.output_tokens, res.cached_tokens) == (12, 7, 5)
    body = seen[0]
    assert body["model"] == "gpt-6-sol"
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_completion_tokens"] == 300
    assert "max_tokens" not in body
    assert body["messages"][0] == {"role": "system", "content": "s"}


async def test_openai_client_retries_without_temperature() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        seen.append(body)
        if "temperature" in body:
            return httpx2.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported value: 'temperature' does not support 0.4 with this model.",
                        "type": "invalid_request_error",
                        "param": "temperature",
                        "code": "unsupported_value",
                    }
                },
            )
        return httpx2.Response(200, json=chat_response("ok"))

    client = OpenAIClient("sk-test", "gpt-6-sol", http_client=mock_http(handler))
    assert (await client.complete([Message("user", "u")])).text == "ok"
    assert (await client.complete([Message("user", "u")])).text == "ok"
    assert "temperature" in seen[0]
    assert all("temperature" not in b for b in seen[1:])
    assert len(seen) == 3


async def test_openai_vision_message_has_image_url() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=chat_response("ok"))

    client = OpenAIClient("sk-test", "gpt-6-sol", http_client=mock_http(handler))
    await client.complete([Message("user", "Rasmni baholang", images=[b"\x89PNG"])])
    content = seen[0]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Rasmni baholang"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_openai_compat_uses_max_tokens_and_base_url() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=chat_response("ok"))

    client = OpenAICompatClient(
        "key", "deepseek-chat", base_url="https://api.deepseek.com/v1", http_client=mock_http(handler)
    )
    await client.complete([Message("user", "u")], max_tokens=200)
    body = json.loads(seen[0].content)
    assert body["max_tokens"] == 200
    assert "max_completion_tokens" not in body
    assert str(seen[0].url).startswith("https://api.deepseek.com/v1/chat/completions")
    assert client.provider == "openai_compatible"


async def test_openai_list_models() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "gpt-6-sol", "object": "model", "created": 1, "owned_by": "openai"},
                    {"id": "gpt-6-luna", "object": "model", "created": 1, "owned_by": "openai"},
                ],
            },
        )

    client = OpenAIClient("sk-test", "gpt-6-sol", http_client=mock_http(handler))
    assert await client.list_models() == ["gpt-6-sol", "gpt-6-luna"]


async def test_anthropic_client_parses_usage_and_caches_system() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-x",
                "content": [{"type": "text", "text": "salom"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 0,
                },
            },
        )

    client = AnthropicClient("sk-ant-test", "claude-x", http_client=mock_http(handler))
    res = await client.complete([Message("system", "statik", cache=True), Message("user", "u")])
    assert res.text == "salom"
    assert res.input_tokens == 110
    assert res.cached_tokens == 100
    assert res.output_tokens == 5
    body = seen[0]
    assert body["system"][0]["text"] == "statik"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"] == [{"role": "user", "content": "u"}]


async def test_gemini_client_parses_text_and_json_mime() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": '{"a": 1}'}], "role": "model"}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 7, "totalTokenCount": 19},
            },
        )

    client = GeminiClient("AIza-test", "gemini-x", http_client=mock_http(handler))
    res = await client.complete([Message("system", "sys"), Message("user", "u")], json_mode=True)
    assert res.text == '{"a": 1}'
    assert (res.input_tokens, res.output_tokens) == (12, 7)
    body = seen[0]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"


async def test_openai_image_b64() -> None:
    png = b"\x89PNGfake"

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        assert body["size"] == "1536x1024"
        return httpx2.Response(
            200, json={"created": 1, "data": [{"b64_json": base64.b64encode(png).decode()}]}
        )

    client = OpenAIImageClient("sk-test", "gpt-image-2", http_client=mock_http(handler))
    assert await client.generate("tech", size="1536x1024") == png


@respx.mock
async def test_stability_image() -> None:
    route = respx.post("https://api.stability.ai/v2beta/stable-image/generate/core").mock(
        return_value=httpx.Response(200, content=b"PNGDATA", headers={"content-type": "image/png"})
    )
    async with httpx.AsyncClient() as http:
        client = StabilityImageClient("key", "core", http=http)
        assert await client.generate("tech", size="1536x1024") == b"PNGDATA"
    req = route.calls[0].request
    assert req.headers["authorization"] == "Bearer key"
    assert b'name="aspect_ratio"' in req.content and b"16:9" in req.content


@respx.mock
async def test_fal_image() -> None:
    respx.post("https://fal.run/fal-ai/flux/schnell").mock(
        return_value=httpx.Response(200, json={"images": [{"url": "https://cdn.fal.media/x.png"}]})
    )
    respx.get("https://cdn.fal.media/x.png").mock(return_value=httpx.Response(200, content=b"IMG"))
    async with httpx.AsyncClient() as http:
        client = FalImageClient("key", "fal-ai/flux/schnell", http=http)
        assert await client.generate("tech") == b"IMG"


@respx.mock
async def test_replicate_image() -> None:
    route = respx.post("https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions").mock(
        return_value=httpx.Response(
            201, json={"status": "succeeded", "output": ["https://replicate.delivery/a.png"]}
        )
    )
    respx.get("https://replicate.delivery/a.png").mock(return_value=httpx.Response(200, content=b"IMG2"))
    async with httpx.AsyncClient() as http:
        client = ReplicateImageClient("r8_key", "black-forest-labs/flux-schnell", http=http)
        assert await client.generate("tech") == b"IMG2"
    assert route.calls[0].request.headers["prefer"] == "wait"


async def test_openai_client_marks_length_truncation() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = chat_response("")
        body["choices"][0]["finish_reason"] = "length"
        return httpx2.Response(200, json=body)

    client = OpenAICompatClient(
        "k", "deepseek-v4-pro", base_url="https://api.deepseek.com", http_client=mock_http(handler)
    )
    assert (await client.complete([Message("user", "u")])).truncated is True


async def test_anthropic_client_marks_max_tokens_truncation() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": "claude-x",
                "content": [{"type": "text", "text": "{"}],
                "stop_reason": "max_tokens",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 5},
            },
        )

    client = AnthropicClient("k", "claude-x", http_client=mock_http(handler))
    assert (await client.complete([Message("user", "u")])).truncated is True


async def test_gemini_client_marks_max_tokens_truncation() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "{"}], "role": "model"}, "finishReason": "MAX_TOKENS"}
                ],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
            },
        )

    client = GeminiClient("k", "gemini-x", http_client=mock_http(handler))
    assert (await client.complete([Message("user", "u")])).truncated is True
