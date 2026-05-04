"""
orch_core.execution.context_builder
====================================

Monta messages[] e tools[] pra passar ao AgentExecutor.

Fonte unica de construcao de contexto. Substitui as tres montagens
diferentes de prompt/messages que existem hoje nos orquestradores
concorrentes.
"""
from __future__ import annotations

from typing import Any, Mapping

from orch_core.contracts import Agent, Run, Tool
from orch_core.control.registry import Registry


def build_messages(
    *,
    run: Run,
    input_payload: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None = None,
) -> list[Mapping[str, Any]]:
    """Monta a lista de messages canonica.

    - Historico (se houver) entra primeiro
    - Input do run vira ultima mensagem do usuario
    - tenant_id/run_id sao propagados via metadata (nao via prompt)
    """
    messages: list[Mapping[str, Any]] = []
    if history:
        messages.extend(history)

    user_content = input_payload.get("content")
    if user_content is None:
        user_content = input_payload.get("text", "")

    messages.append(
        {
            "role": "user",
            "content": user_content,
        }
    )
    return messages


def build_tools(
    *,
    run: Run,
    registry: Registry,
    allowed_tools: list[str] | None = None,
) -> list[Mapping[str, Any]]:
    """Resolve tools disponiveis pro agente.

    Se allowed_tools for None: todas as tools do registry.
    Caso contrario: interseccao.
    """
    all_tools = list(registry.list_tools())
    if allowed_tools is not None:
        filtered = [t for t in all_tools if t.name in set(allowed_tools)]
    else:
        filtered = all_tools
    return [_tool_to_schema(t) for t in filtered]


def resolve_agent(*, run: Run, registry: Registry) -> Agent:
    """Resolve o Agent canonico pra um Run. Falha com AgentNotFound
    se nao existir no escopo do tenant."""
    return registry.get_agent(run.tenant_id, run.agent_id)


def _tool_to_schema(tool: Tool) -> Mapping[str, Any]:
    return {"name": tool.name, **dict(tool.schema())}


__all__ = ["build_messages", "build_tools", "resolve_agent"]
