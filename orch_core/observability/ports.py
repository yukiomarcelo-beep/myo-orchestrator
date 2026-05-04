"""
orch_core.observability.ports
==============================

Ports (Protocols) que o Runner consome. Permite:
- Testar o Runner com fakes leves
- Plugar as implementacoes canonicas LESSON-002 (execution_context),
  LESSON-003 (runtime_guard) e LESSON-004 (audit_log) via adaptadores
  finos (LESSON-010 delivery)

Princípio: o Runner NUNCA importa concretos. Só Protocols.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable
from uuid import UUID

from orch_core.contracts import Event, Run


@runtime_checkable
class AuditSink(Protocol):
    """Port pra AuditLog canonico (LESSON-004).

    A implementacao real pode ser PostgreSQL com hash chain.
    Aqui so precisamos de append + query basica.
    """

    def append(
        self,
        *,
        run_id: UUID,
        tenant_id: str,
        kind: str,
        payload: Mapping[str, Any],
    ) -> None: ...

    def events_of(self, run_id: UUID) -> list[Mapping[str, Any]]: ...


@runtime_checkable
class RuntimeGuard(Protocol):
    """Port pra runtime_guard canonico (LESSON-003, 4 camadas).

    Retorna True se a acao e permitida, False caso contrario.
    Se False, Runner aborta o step com erro estruturado.
    """

    def allow_tool_call(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        tool_name: str,
        args: Mapping[str, Any],
    ) -> bool: ...

    def reason(self) -> str | None:
        """Ultima razao de bloqueio, se houver."""
        ...


@runtime_checkable
class ExecutionContext(Protocol):
    """Port pra execution_context canonico (LESSON-002).

    Carrega tenant_id, run_id e metadados durante um run.
    """

    @property
    def run_id(self) -> UUID: ...

    @property
    def tenant_id(self) -> str: ...

    def get(self, key: str, default: Any = None) -> Any: ...

    def with_value(self, key: str, value: Any) -> "ExecutionContext": ...


@runtime_checkable
class EventSink(Protocol):
    """Port pra consumo de eventos em tempo real (futuro: EventBus).

    Na LESSON-010 a implementacao default escreve no AuditSink.
    Na fase de EventBus, troca-se apenas o adaptador.
    """

    def emit(self, event: Event) -> None: ...


@runtime_checkable
class AgentExecutor(Protocol):
    """Port pra 'chamar o agente' (provedor LLM).

    Abstraido pro Runner ser testavel sem bater em API externa.
    Implementacao real: wrapper do Claude SDK com prompt do agente.
    """

    def step(
        self,
        *,
        run: Run,
        messages: list[Mapping[str, Any]],
        tools: list[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        """Retorna dict com shape:
        {
          "stop_reason": "end_turn" | "tool_use" | "max_tokens" | "error",
          "content": [ ... blocks ... ],
          "tool_calls": [ {"name": str, "args": dict, "id": str}, ... ],
          "text": str | None,
        }
        """
        ...


__all__ = [
    "AgentExecutor",
    "AuditSink",
    "EventSink",
    "ExecutionContext",
    "RuntimeGuard",
]
