from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx

from app.domain.model_runner import ModelRequest, ModelResponse, ModelStreamEvent
from app.providers.adk_runner import AdkModelRunner


def _source_context(request: ModelRequest) -> str:
    return "\n\n".join(
        f'<source position="{position}">\n{text}\n</source>'
        for position, text in enumerate(request.source_texts, start=1)
    )


def _google_access_token() -> str:
    try:
        import google.auth
        from google.auth.transport.requests import Request
    except ImportError as error:
        raise RuntimeError(
            "Install backend[model] to use Claude on Vertex: "
            "pip install -e './backend[model]'"
        ) from error

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    if not credentials.token:
        raise RuntimeError("Application Default Credentials did not return an access token")
    return credentials.token


class ConfiguredModelRunner:
    """Dispatch model calls to the adapter declared in the backend model registry."""

    def __init__(self, xai_api_key: str | None = None) -> None:
        self.gemini = AdkModelRunner()
        self.xai_api_key = xai_api_key

    async def run(self, request: ModelRequest) -> ModelResponse:
        if request.endpoint_type == "vertex_gemini":
            return await self.gemini.run(request)
        if request.endpoint_type == "vertex_anthropic":
            return await self._run_vertex_anthropic(request)
        if request.endpoint_type == "xai_responses":
            return await self._run_xai(request)
        raise ValueError(f"Unsupported model endpoint: {request.endpoint_type}")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if request.endpoint_type == "vertex_gemini":
            async for event in self.gemini.stream(request):
                yield event
            return
        if request.endpoint_type == "vertex_anthropic":
            async for event in self._stream_vertex_anthropic(request):
                yield event
            return
        if request.endpoint_type == "xai_responses":
            async for event in self._stream_xai(request):
                yield event
            return
        raise ValueError(f"Unsupported model endpoint: {request.endpoint_type}")

    async def _run_vertex_anthropic(self, request: ModelRequest) -> ModelResponse:
        if request.response_json_schema is not None:
            raise ValueError("Claude evaluation output schemas are not enabled in this version")
        if request.location == "global":
            host = "https://aiplatform.googleapis.com"
        else:
            host = f"https://{request.location}-aiplatform.googleapis.com"
        endpoint = (
            f"{host}/v1/projects/{quote(request.project, safe='')}/locations/"
            f"{quote(request.location, safe='')}/publishers/anthropic/models/"
            f"{quote(request.model_id, safe='')}:rawPredict"
        )
        content = _source_context(request)
        if content:
            content += "\n\n"
        content += request.user_prompt
        body: dict[str, Any] = {
            "anthropic_version": "vertex-2023-10-16",
            "max_tokens": request.max_output_tokens,
            "stream": False,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": content}],
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p

        token = await asyncio.to_thread(_google_access_token)
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
        payload = response.json()
        text = "".join(
            str(item.get("text", ""))
            for item in payload.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()
        if not text:
            raise RuntimeError("Claude returned no usable final text")
        usage = payload.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        input_tokens = _optional_int(usage.get("input_tokens"))
        output_tokens = _optional_int(usage.get("output_tokens"))
        total_tokens = (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        )
        return ModelResponse(
            text=text,
            model_id_actual=str(payload.get("model") or request.model_id),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            request_id=_optional_str(payload.get("id")),
            trace_id=None,
        )

    async def _stream_vertex_anthropic(
        self, request: ModelRequest
    ) -> AsyncIterator[ModelStreamEvent]:
        if request.response_json_schema is not None:
            raise ValueError("Claude evaluation output schemas are not enabled in this version")
        if request.location == "global":
            host = "https://aiplatform.googleapis.com"
        else:
            host = f"https://{request.location}-aiplatform.googleapis.com"
        endpoint = (
            f"{host}/v1/projects/{quote(request.project, safe='')}/locations/"
            f"{quote(request.location, safe='')}/publishers/anthropic/models/"
            f"{quote(request.model_id, safe='')}:streamRawPredict"
        )
        content = _source_context(request)
        if content:
            content += "\n\n"
        content += request.user_prompt
        body: dict[str, Any] = {
            "anthropic_version": "vertex-2023-10-16",
            "max_tokens": request.max_output_tokens,
            "stream": True,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": content}],
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p

        token = await asyncio.to_thread(_google_access_token)
        text_parts: list[str] = []
        model_id_actual = request.model_id
        request_id: str | None = None
        input_tokens = output_tokens = None
        async with httpx.AsyncClient(timeout=180) as client:
            async with client.stream(
                "POST",
                endpoint,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=body,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    payload = json.loads(data)
                    event_type = payload.get("type")
                    if event_type == "error":
                        raise RuntimeError("Claude stream returned an error")
                    if event_type == "message_start":
                        message = payload.get("message", {})
                        model_id_actual = str(message.get("model") or request.model_id)
                        request_id = _optional_str(message.get("id"))
                        usage = message.get("usage", {})
                        if isinstance(usage, dict):
                            input_tokens = _optional_int(usage.get("input_tokens"))
                    elif event_type == "content_block_delta":
                        delta = payload.get("delta", {})
                        text = delta.get("text") if isinstance(delta, dict) else None
                        if isinstance(text, str) and text:
                            text_parts.append(text)
                            yield ModelStreamEvent(text_delta=text)
                    elif event_type == "message_delta":
                        usage = payload.get("usage", {})
                        if isinstance(usage, dict):
                            output_tokens = _optional_int(usage.get("output_tokens"))

        response_text = "".join(text_parts).strip()
        if not response_text:
            raise RuntimeError("Claude returned no usable final text")
        yield ModelStreamEvent(
            response=ModelResponse(
                text=response_text,
                model_id_actual=model_id_actual,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=(
                    input_tokens + output_tokens
                    if input_tokens is not None and output_tokens is not None
                    else None
                ),
                request_id=request_id,
                trace_id=None,
            )
        )

    async def _run_xai(self, request: ModelRequest) -> ModelResponse:
        if not self.xai_api_key:
            raise RuntimeError("APP_XAI_API_KEY must be configured to use Grok models")
        if request.response_json_schema is not None:
            raise ValueError("Grok evaluation output schemas are not enabled in this version")
        content = _source_context(request)
        if content:
            content += "\n\n"
        content += request.user_prompt
        body = {
            "model": request.model_id,
            "input": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": content},
            ],
            "max_output_tokens": request.max_output_tokens,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                "https://api.x.ai/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.xai_api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
        payload = response.json()
        text_parts = [
            str(part.get("text", ""))
            for item in payload.get("output", [])
            if isinstance(item, dict) and item.get("role") == "assistant"
            for part in item.get("content", [])
            if isinstance(part, dict) and part.get("type") == "output_text"
        ]
        text = "".join(text_parts).strip()
        if not text:
            raise RuntimeError("Grok returned no usable final text")
        usage = payload.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        input_tokens = _optional_int(usage.get("input_tokens"))
        output_tokens = _optional_int(usage.get("output_tokens"))
        total_tokens = _optional_int(usage.get("total_tokens"))
        return ModelResponse(
            text=text,
            model_id_actual=str(payload.get("model") or request.model_id),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            request_id=_optional_str(payload.get("id")),
            trace_id=None,
        )

    async def _stream_xai(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if not self.xai_api_key:
            raise RuntimeError("APP_XAI_API_KEY must be configured to use Grok models")
        if request.response_json_schema is not None:
            raise ValueError("Grok evaluation output schemas are not enabled in this version")
        content = _source_context(request)
        if content:
            content += "\n\n"
        content += request.user_prompt
        body: dict[str, Any] = {
            "model": request.model_id,
            "input": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": content},
            ],
            "max_output_tokens": request.max_output_tokens,
            "stream": True,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        text_parts: list[str] = []
        model_id_actual = request.model_id
        request_id: str | None = None
        input_tokens = output_tokens = total_tokens = None
        async with httpx.AsyncClient(timeout=180) as client:
            async with client.stream(
                "POST",
                "https://api.x.ai/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.xai_api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=body,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    payload = json.loads(data)
                    event_type = payload.get("type")
                    if event_type == "error":
                        raise RuntimeError("Grok stream returned an error")
                    if event_type in {"response.output_text.delta", "response.text.delta"}:
                        delta = payload.get("delta")
                        if isinstance(delta, str) and delta:
                            text_parts.append(delta)
                            yield ModelStreamEvent(text_delta=delta)
                    elif event_type == "response.completed":
                        final = payload.get("response", {})
                        if isinstance(final, dict):
                            model_id_actual = str(final.get("model") or request.model_id)
                            request_id = _optional_str(final.get("id"))
                            usage = final.get("usage", {})
                            if isinstance(usage, dict):
                                input_tokens = _optional_int(usage.get("input_tokens"))
                                output_tokens = _optional_int(usage.get("output_tokens"))
                                total_tokens = _optional_int(usage.get("total_tokens"))
                            if not text_parts:
                                text_parts.extend(_extract_xai_text(final.get("output", [])))

        response_text = "".join(text_parts).strip()
        if not response_text:
            raise RuntimeError("Grok returned no usable final text")
        yield ModelStreamEvent(
            response=ModelResponse(
                text=response_text,
                model_id_actual=model_id_actual,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=(
                    total_tokens
                    if total_tokens is not None
                    else input_tokens + output_tokens
                    if input_tokens is not None and output_tokens is not None
                    else None
                ),
                request_id=request_id,
                trace_id=None,
            )
        )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _extract_xai_text(output: object) -> list[str]:
    if not isinstance(output, list):
        return []
    return [
        str(part.get("text", ""))
        for item in output
        if isinstance(item, dict) and item.get("role") == "assistant"
        for part in item.get("content", [])
        if isinstance(part, dict) and part.get("type") == "output_text"
    ]
