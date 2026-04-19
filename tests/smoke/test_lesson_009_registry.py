"""
Smoke tests LESSON-009 — registry unificado.

Cobre 10 casos (minimo >= 8):
1. register + get_agent retorna o mesmo objeto
2. get_agent com id inexistente levanta AgentNotFound
3. Escopo por tenant: mesmo agent_id em tenants diferentes nao colide
4. Duplicacao (mesmo tenant + agent_id) rejeitada
5. tool lookup basico
6. tool lookup miss levanta ToolNotFound
7. list_agents so retorna agents do tenant pedido
8. thread-safety basico (concorrencia de register)
9. unregister_agent devolve bool + idempotencia
10. default_registry eh singleton
"""
from __future__ import annotations

import threading

import pytest

from orch_core.contracts import AgentNotFound, ToolNotFound
from orch_core.control.registry import (
    Registry,
    default_registry,
    reset_default_registry,
)


# ---- stubs minimos de Agent / Tool ----------------------------------------


class _StubAgent:
    def __init__(self, tenant_id: str, agent_id: str) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id

    def describe(self) -> dict:
        return {"id": self.agent_id, "tenant": self.tenant_id}


class _StubTool:
    def __init__(self, name: str) -> None:
        self.name = name

    def schema(self) -> dict:
        return {"name": self.name}


# ---- fixtures -------------------------------------------------------------


@pytest.fixture
def registry() -> Registry:
    return Registry()


# 1
def test_register_and_get_agent(registry: Registry) -> None:
    a = _StubAgent("t1", "agent-x")
    registry.register_agent(a)
    got = registry.get_agent("t1", "agent-x")
    assert got is a


# 2
def test_get_agent_miss_raises(registry: Registry) -> None:
    with pytest.raises(AgentNotFound, match="agent not found"):
        registry.get_agent("t1", "nope")


# 3
def test_tenant_scope_isolation(registry: Registry) -> None:
    a1 = _StubAgent("t1", "agent-x")
    a2 = _StubAgent("t2", "agent-x")
    registry.register_agent(a1)
    registry.register_agent(a2)
    assert registry.get_agent("t1", "agent-x") is a1
    assert registry.get_agent("t2", "agent-x") is a2


# 4
def test_duplicate_agent_rejected(registry: Registry) -> None:
    registry.register_agent(_StubAgent("t1", "agent-x"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register_agent(_StubAgent("t1", "agent-x"))


# 5
def test_tool_register_and_lookup(registry: Registry) -> None:
    t = _StubTool("search")
    registry.register_tool(t)
    assert registry.get_tool("search") is t


# 6
def test_tool_miss_raises(registry: Registry) -> None:
    with pytest.raises(ToolNotFound, match="tool not found"):
        registry.get_tool("ghost")


# 7
def test_list_agents_scoped_by_tenant(registry: Registry) -> None:
    registry.register_agent(_StubAgent("t1", "a1"))
    registry.register_agent(_StubAgent("t1", "a2"))
    registry.register_agent(_StubAgent("t2", "a1"))
    t1_agents = {a.agent_id for a in registry.list_agents("t1")}
    assert t1_agents == {"a1", "a2"}


# 8
def test_thread_safety_register(registry: Registry) -> None:
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            registry.register_agent(_StubAgent("t1", f"agent-{i}"))
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(list(registry.list_agents("t1"))) == 50


# 9
def test_unregister_agent_idempotent(registry: Registry) -> None:
    registry.register_agent(_StubAgent("t1", "agent-x"))
    assert registry.unregister_agent("t1", "agent-x") is True
    assert registry.unregister_agent("t1", "agent-x") is False
    with pytest.raises(AgentNotFound):
        registry.get_agent("t1", "agent-x")


# 10
def test_default_registry_singleton() -> None:
    reset_default_registry()
    r1 = default_registry()
    r2 = default_registry()
    assert r1 is r2
    reset_default_registry()
