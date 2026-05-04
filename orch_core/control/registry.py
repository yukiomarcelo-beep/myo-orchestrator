"""
orch_core.control.registry
==========================

Registry canonico unificado (LESSON-009).

Substitui os lookups de agent/tool espalhados em master_controller,
orch_core (antigo) e orchestrator.py. Fonte UNICA.

Invariantes:
- Escopo sempre por tenant_id (isolation por construcao)
- Thread-safe via lock interno
- Duplicacao detectada (falha alto e cedo)
- Miss explicito via AgentNotFound / ToolNotFound
"""
from __future__ import annotations

import threading
from typing import Iterator

from orch_core.contracts import (
    Agent,
    AgentNotFound,
    Tool,
    ToolNotFound,
)


class Registry:
    """Registry thread-safe de agents e tools, com escopo por tenant."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # (tenant_id, agent_id) -> Agent
        self._agents: dict[tuple[str, str], Agent] = {}
        # tool_name -> Tool (tools sao globais por ora; pode virar per-tenant)
        self._tools: dict[str, Tool] = {}

    # -- agents ---------------------------------------------------------------

    def register_agent(self, agent: Agent) -> None:
        if not agent.tenant_id or not agent.tenant_id.strip():
            raise ValueError("agent.tenant_id is required")
        if not agent.agent_id or not agent.agent_id.strip():
            raise ValueError("agent.agent_id is required")
        key = (agent.tenant_id, agent.agent_id)
        with self._lock:
            if key in self._agents:
                raise ValueError(
                    f"agent already registered: tenant={agent.tenant_id} "
                    f"agent_id={agent.agent_id}"
                )
            self._agents[key] = agent

    def get_agent(self, tenant_id: str, agent_id: str) -> Agent:
        key = (tenant_id, agent_id)
        with self._lock:
            agent = self._agents.get(key)
        if agent is None:
            raise AgentNotFound(
                f"agent not found: tenant={tenant_id} agent_id={agent_id}"
            )
        return agent

    def list_agents(self, tenant_id: str) -> Iterator[Agent]:
        with self._lock:
            snapshot = [
                a for (t, _), a in self._agents.items() if t == tenant_id
            ]
        return iter(snapshot)

    def unregister_agent(self, tenant_id: str, agent_id: str) -> bool:
        with self._lock:
            return self._agents.pop((tenant_id, agent_id), None) is not None

    # -- tools ----------------------------------------------------------------

    def register_tool(self, tool: Tool) -> None:
        if not tool.name or not tool.name.strip():
            raise ValueError("tool.name is required")
        with self._lock:
            if tool.name in self._tools:
                raise ValueError(f"tool already registered: {tool.name}")
            self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Tool:
        with self._lock:
            tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFound(f"tool not found: {name}")
        return tool

    def list_tools(self) -> Iterator[Tool]:
        with self._lock:
            snapshot = list(self._tools.values())
        return iter(snapshot)

    def unregister_tool(self, name: str) -> bool:
        with self._lock:
            return self._tools.pop(name, None) is not None

    # -- housekeeping ---------------------------------------------------------

    def clear(self) -> None:
        """Limpa tudo. Util em smoke tests."""
        with self._lock:
            self._agents.clear()
            self._tools.clear()


# -----------------------------------------------------------------------------
# Singleton de modulo (opcional, conveniente, mas NAO obrigatorio)
# -----------------------------------------------------------------------------

_default_registry: Registry | None = None
_default_lock = threading.Lock()


def default_registry() -> Registry:
    """Retorna o registry global padrao. Preguicoso."""
    global _default_registry
    if _default_registry is None:
        with _default_lock:
            if _default_registry is None:
                _default_registry = Registry()
    return _default_registry


def reset_default_registry() -> None:
    """So pra testes. Nao usar em producao."""
    global _default_registry
    with _default_lock:
        _default_registry = None


__all__ = [
    "Registry",
    "default_registry",
    "reset_default_registry",
]
