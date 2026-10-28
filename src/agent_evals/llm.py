"""Minimal chat clients for the providers the harness talks to (agent under test and judge).

Provider specs look like "ollama:gemma4:12b", "openai:gpt-4.1-mini" or "anthropic:claude-haiku-5-5".
The OpenAI client works with any OpenAI-compatible server (vLLM, LM Studio, llama.cpp) via OPENAI_BASE_URL.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from .schema import Usage


@dataclass
class LLMToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ChatResponse:
    content: str
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    latency_ms: float = 0.0
    message: dict[str, Any] = field(default_factory=dict)  # assistant message to append to the history


class LLMClient:
    provider = ""

    def __init__(self, model: str, timeout: float = 300.0):
        self.model = model
        self.http = httpx.Client(timeout=timeout)

    @property
    def spec(self) -> str:
        return f"{self.provider}:{self.model}"

    def chat(self, messages: list[dict], tools: list[dict] | None = None, json_schema: dict | None = None,
             temperature: float = 0.0) -> ChatResponse:
        raise NotImplementedError

    def tool_result_message(self, call: LLMToolCall, content: str) -> dict:
        raise NotImplementedError


class OllamaClient(LLMClient):
    provider = "ollama"

    def __init__(self, model: str, base_url: str | None = None, think: bool = False, num_ctx: int | None = None,
                 seed: int | None = 7, **kw):
        super().__init__(model, **kw)
        self.base_url = (base_url or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        if not self.base_url.startswith("http"):
            self.base_url = f"http://{self.base_url}"
        self.think = think
        self.num_ctx = num_ctx
        self.seed = seed  # None lets Ollama sample freely

    def chat(self, messages, tools=None, json_schema=None, temperature=0.0):
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": self.think,
            "options": {"temperature": temperature, **({"seed": self.seed} if self.seed is not None else {}),
                        **({"num_ctx": self.num_ctx} if self.num_ctx else {})},
        }
        if tools:
            body["tools"] = tools
        if json_schema:
            body["format"] = json_schema
        t0 = time.perf_counter()
        r = self.http.post(f"{self.base_url}/api/chat", json=body)
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {})
        calls = [
            LLMToolCall(id=uuid.uuid4().hex[:8], name=tc["function"]["name"], args=_as_dict(tc["function"].get("arguments")))
            for tc in msg.get("tool_calls") or []
        ]
        history_msg = {"role": "assistant", "content": msg.get("content", "")}
        if msg.get("tool_calls"):
            history_msg["tool_calls"] = msg["tool_calls"]
        return ChatResponse(
            content=msg.get("content", "") or "",
            tool_calls=calls,
            usage=Usage(input_tokens=data.get("prompt_eval_count", 0) or 0, output_tokens=data.get("eval_count", 0) or 0),
            latency_ms=(time.perf_counter() - t0) * 1000,
            message=history_msg,
        )

    def tool_result_message(self, call, content):
        return {"role": "tool", "tool_name": call.name, "content": content}


class OpenAIClient(LLMClient):
    provider = "openai"

    def __init__(self, model: str, base_url: str | None = None, api_key: str | None = None, **kw):
        super().__init__(model, **kw)
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    def chat(self, messages, tools=None, json_schema=None, temperature=0.0):
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": temperature}
        if tools:
            body["tools"] = tools
        if json_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "verdict", "schema": json_schema}}
        t0 = time.perf_counter()
        r = self.http.post(f"{self.base_url}/chat/completions", json=body, headers={"Authorization": f"Bearer {self.api_key}"})
        r.raise_for_status()
        data = r.json()
        msg = data["choices"][0]["message"]
        calls = [
            LLMToolCall(id=tc["id"], name=tc["function"]["name"], args=_as_dict(tc["function"].get("arguments")))
            for tc in msg.get("tool_calls") or []
        ]
        u = data.get("usage") or {}
        history_msg = {"role": "assistant", "content": msg.get("content") or ""}
        if msg.get("tool_calls"):
            history_msg["tool_calls"] = msg["tool_calls"]
        return ChatResponse(
            content=msg.get("content") or "",
            tool_calls=calls,
            usage=Usage(input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0)),
            latency_ms=(time.perf_counter() - t0) * 1000,
            message=history_msg,
        )

    def tool_result_message(self, call, content):
        return {"role": "tool", "tool_call_id": call.id, "content": content}


class AnthropicClient(LLMClient):
    """Text-only client, used as a judge. Tools are not needed there."""

    provider = "anthropic"

    def __init__(self, model: str, api_key: str | None = None, **kw):
        super().__init__(model, **kw)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def chat(self, messages, tools=None, json_schema=None, temperature=0.0):
        if tools:
            raise NotImplementedError("The Anthropic client is only used as a judge (no tools).")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [m for m in messages if m["role"] != "system"]
        if json_schema:
            system += "\n\nReply with a single JSON object matching this schema and nothing else:\n" + json.dumps(json_schema)
        t0 = time.perf_counter()
        r = self.http.post(
            "https://api.anthropic.com/v1/messages",
            json={"model": self.model, "max_tokens": 1024, "temperature": temperature, "system": system, "messages": rest},
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
        )
        r.raise_for_status()
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        u = data.get("usage") or {}
        return ChatResponse(
            content=text,
            usage=Usage(input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0)),
            latency_ms=(time.perf_counter() - t0) * 1000,
            message={"role": "assistant", "content": text},
        )


PROVIDERS = {"ollama": OllamaClient, "openai": OpenAIClient, "anthropic": AnthropicClient}


def make_client(spec: str, **options: Any) -> LLMClient:
    provider, _, model = spec.partition(":")
    if provider not in PROVIDERS or not model:
        raise ValueError(f'Invalid model spec "{spec}". Use provider:model with provider in {sorted(PROVIDERS)}.')
    return PROVIDERS[provider](model, **options)


def _as_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip():
        try:
            out = json.loads(v)
            return out if isinstance(out, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
