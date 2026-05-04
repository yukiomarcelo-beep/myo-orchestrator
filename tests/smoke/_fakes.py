"""Fakes reutilizaveis pros smokes. NAO usar em producao."""
from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from orch_core.contracts import Event
from orch_core.observability.ports import (
    AgentExecutor,
    AuditSink,
    EventSink,
    RuntimeGuard,
)


class FakeAudit(AuditSink):
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def append(
        self,
        *,
        run_id: UUID,
        tenant_id: str,
        kind: str,
        payload: Mapping[str, Any],
    ) -> None:
        self.records.append(
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "kind": kind,
                "payload": dict(payload),
            }
        )

    def events_of(self, run_id: UUID) -> list[Mapping[str, Any]]:
        return [r for r in self.records if r["run_id"] == run_id]

    def kinds_of(self, run_id: UUID) -> list[str]:
        return [r["kind"] for r in self.records if r["run_id"] == run_id]


class FakeGuard(RuntimeGuard):
    def __init__(
        self,
        *,
        deny_tools: set[str] | None = None,
        deny_reason: str = "blocked in test",
    ) -> None:
        self.deny_tools = deny_tools or set()
        self.deny_reason_text = deny_reason
        self._last_reason: str | None = None

    def allow_tool_call(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        tool_name: str,
        args: Mapping[str, Any],
    ) -> bool:
        if tool_name in self.deny_tools:
            self._last_reason = self.deny_reason_text
            return False
        self._last_reason = None
        return True

    def reason(self) -> str | None:
        return self._last_reason


class FakeEvents(EventSink):
    def __init__(self) -> None:
        self.emitted: list[Event] = []

    def emit(self, event: Event) -> None:
        self.emitted.append(event)

    def kinds(self) -> list[str]:
        return [e.kind for e in self.emitted]


class ScriptedExecutor(AgentExecutor):
    """AgentExecutor que retorna respostas pre-definidas em ordem.

    Cada item da lista vira uma resposta. Se acabar, retorna end_turn
    com texto vazio (evita loop infinito nos testes).
    """

    def __init__(self, responses: list[Mapping[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def step(
        self,
        *,
        run: Any,
        messages: list[Mapping[str, Any]],
        tools: list[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        self.calls += 1
        if not self.responses:
            return {"stop_reason": "end_turn", "text": "", "tool_calls": []}
        return self.responses.pop(0)


class SimpleAgent:
    def __init__(self, tenant_id: str, agent_id: str) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id

    def describe(self) -> dict:
        return {"id": self.agent_id, "tenant": self.tenant_id}


class EchoTool:
    name = "echo"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def schema(self) -> dict:
        return {"input_schema": {"type": "object"}}

    def __call__(self, **kwargs: Any) -> str:
        self.calls.append(dict(kwargs))
        return f"echo:{kwargs}"


class BoomTool:
    name = "boom"

    def schema(self) -> dict:
        return {"input_schema": {"type": "object"}}

    def __call__(self, **kwargs: Any) -> Any:
        raise RuntimeError("boom!")


class DangerTool:
    name = "danger"

    def schema(self) -> dict:
        return {"input_schema": {"type": "object"}}

    def __call__(self, **kwargs: Any) -> Any:
        return "should never run"
