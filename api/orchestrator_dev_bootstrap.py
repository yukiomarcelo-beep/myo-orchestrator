"""
api/orchestrator_dev_bootstrap.py
==================================

Bootstrap de DESENVOLVIMENTO com agentes e tools fake, pra testar o
cockpit e validar as rotas canonicas ANTES de os adapters reais da
FASE 2 estarem prontos.

NAO usar em producao. Producao usa bootstrap_scheduler() de
api.orchestrator_canonical com adapters reais.

Uso no myo_server.py durante desenvolvimento:

    import os
    from api.orchestrator_canonical import mount_canonical_orchestrator

    if os.environ.get("MYO_DEV_MODE") == "1":
        from api.orchestrator_dev_bootstrap import dev_scheduler
        _scheduler = dev_scheduler()
    else:
        from api.orchestrator_canonical import bootstrap_scheduler
        _scheduler = bootstrap_scheduler()

    mount_canonical_orchestrator(app, scheduler=_scheduler)
"""

from __future__ import annotations

import time
from typing import Any, Mapping
from uuid import UUID

from orch_core.control.registry import Registry
from orch_core.control.scheduler import Scheduler
from orch_core.execution import FeatureFlags, Runner
from orch_core.observability.event_bus import InMemoryEventBus
from orch_core.observability.ports import (
    AgentExecutor,
    AuditSink,
    RuntimeGuard,
)


class _DevAudit(AuditSink):
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def append(self, *, run_id, tenant_id, kind, payload):  # type: ignore[no-untyped-def]
        self.records.append(
            {
                "run_id": str(run_id),
                "tenant_id": tenant_id,
                "kind": kind,
                "payload": dict(payload),
            }
        )
        # cap em 10k pra nao estourar memoria
        if len(self.records) > 10_000:
            self.records = self.records[-5_000:]

    def events_of(self, run_id: UUID) -> list[Mapping[str, Any]]:
        sid = str(run_id)
        return [r for r in self.records if r["run_id"] == sid]


class _DevGuard(RuntimeGuard):
    """Permite tudo em dev. Producao usa RuntimeGuardAdapter real."""

    def allow_tool_call(self, *, tenant_id, agent_id, tool_name, args):  # type: ignore[no-untyped-def]
        return True

    def reason(self) -> str | None:
        return None


class _DevAgent(AgentExecutor):
    """Agente fake: responde baseado em 'scripts' por agent_id.

    Pra testar o cockpit com comportamentos diferentes, use agent_id:
    - 'echo' : responde texto simples e termina
    - 'slow' : dorme 1s antes de responder (mostra running)
    - 'tool' : chama 1 tool e depois termina
    """

    def step(self, *, run, messages, tools):  # type: ignore[no-untyped-def]
        agent_id = run.agent_id
        if agent_id == "slow":
            time.sleep(1.0)
            return {
                "stop_reason": "end_turn",
                "text": f"slow agent done (run {str(run.run_id)[:8]})",
                "tool_calls": [],
            }
        if agent_id == "tool":
            return {
                "stop_reason": "tool_use",
                "text": "chamando echo",
                "tool_calls": [{"id": "c1", "name": "echo", "args": {"msg": "hello"}}],
            }
        return {
            "stop_reason": "end_turn",
            "text": f"echo agent done (run {str(run.run_id)[:8]})",
            "tool_calls": [],
        }


class _SimpleAgent:
    def __init__(self, tenant_id: str, agent_id: str) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id

    def describe(self) -> dict:
        return {"id": self.agent_id, "tenant": self.tenant_id}


class _EchoTool:
    name = "echo"

    def schema(self) -> dict:
        return {"input_schema": {"type": "object"}}

    def __call__(self, **kwargs: Any) -> str:
        return f"echo: {kwargs}"


def dev_scheduler() -> Scheduler:
    """Cria Scheduler dev com 3 agentes fake registrados no tenant
    padrao 'marcelo'. Usar SO em desenvolvimento."""
    import os
    import warnings

    warnings.warn(
        "dev_scheduler() esta em uso — NUNCA habilitar em producao",
        RuntimeWarning,
        stacklevel=2,
    )
    tenant = os.environ.get("MYO_DEFAULT_TENANT", "marcelo")

    reg = Registry()
    for agent_id in ("echo", "slow", "tool"):
        reg.register_agent(_SimpleAgent(tenant, agent_id))
    reg.register_tool(_EchoTool())

    bus = InMemoryEventBus()
    runner = Runner(
        registry=reg,
        audit=_DevAudit(),
        guard=_DevGuard(),
        agent_executor=_DevAgent(),
        events=bus,
        flags=FeatureFlags(runner_max_steps=10),
    )
    return Scheduler(runner=runner, event_bus=bus, max_workers=4)


__all__ = ["dev_scheduler"]
