"""
orch_core.observability.adapters.anthropic_agent_executor
==========================================================

Adapter que implementa o port AgentExecutor usando a API Anthropic.

Usa httpx sync (mesmo padrao do resto do projeto) para manter o Runner
estateless e síncrono. A model e lida de run.metadata["model"] ou do
construtor (default: claude-sonnet-4-6).

Mapeamento de saida (Anthropic -> shape canonico):
  stop_reason: "end_turn" | "tool_use" | "max_tokens" | "error"
  content:     lista de blocos Anthropic (repassada intacta)
  tool_calls:  [{"name": str, "args": dict, "id": str}] — extraido de content
  text:        texto concatenado dos blocos de tipo "text"
"""
from __future__ import annotations

import json
import os
from typing import Any, Mapping

import httpx

from orch_core.contracts import Run

_DEFAULT_MODEL = "claude-sonnet-4-6"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_TIMEOUT = 90.0


class AnthropicAgentExecutor:
    """Implementa AgentExecutor chamando a API Anthropic de forma sincrona."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = _DEFAULT_MODEL,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._default_model = default_model
        self._max_tokens = max_tokens
        self._timeout = timeout

    def step(
        self,
        *,
        run: Run,
        messages: list[Mapping[str, Any]],
        tools: list[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        model = (
            run.metadata.get("model")
            if run.metadata
            else None
        ) or self._default_model

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": self._max_tokens,
            "messages": [dict(m) for m in messages],
        }
        if tools:
            payload["tools"] = [dict(t) for t in tools]

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(_ANTHROPIC_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            return {
                "stop_reason": "error",
                "content": [],
                "tool_calls": [],
                "text": None,
                "error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
            }
        except Exception as exc:
            return {
                "stop_reason": "error",
                "content": [],
                "tool_calls": [],
                "text": None,
                "error": str(exc),
            }

        content_blocks: list[Any] = data.get("content") or []
        stop_reason: str = data.get("stop_reason") or "end_turn"

        tool_calls = [
            {
                "name": block["name"],
                "args": block.get("input") or {},
                "id": block.get("id", ""),
            }
            for block in content_blocks
            if block.get("type") == "tool_use"
        ]

        text_parts = [
            block.get("text", "")
            for block in content_blocks
            if block.get("type") == "text"
        ]
        text = "\n".join(text_parts) if text_parts else None

        return {
            "stop_reason": stop_reason,
            "content": content_blocks,
            "tool_calls": tool_calls,
            "text": text,
        }


__all__ = ["AnthropicAgentExecutor"]
