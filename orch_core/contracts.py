"""
orch_core.contracts
===================

Contratos canônicos da unificação dos orquestradores (LESSON-008).

Fonte única de verdade pros tipos que atravessam o control plane,
execution plane e adapters. Tudo imutável por design (frozen dataclasses
+ Literals), compatível com execution_context (LESSON-002) e audit_log
(LESSON-004).

Invariantes desta camada:
- tenant_id é sempre obrigatório
- run_id é sempre UUID
- status segue máquina de estados fechada
- parent_run_id existe desde o dia um (sub-runs no futuro)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import (
    Any,
    Literal,
    Mapping,
    Protocol,
    TypedDict,
    runtime_checkable,
)
from uuid import UUID, uuid4

# -----------------------------------------------------------------------------
# Enums / Literals
# -----------------------------------------------------------------------------

RunStatus = Literal[
    "pending",
    "running",
    "done",
    "failed",
    "cancelled",
]

VALID_TRANSITIONS: Mapping[RunStatus, frozenset[RunStatus]] = {
    "pending": frozenset({"running", "cancelled", "failed"}),
    "running": frozenset({"done", "failed", "cancelled"}),
    "done": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def is_valid_transition(src: RunStatus, dst: RunStatus) -> bool:
    return dst in VALID_TRANSITIONS.get(src, frozenset())


# -----------------------------------------------------------------------------
# Core dataclasses
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Run:
    """Identidade imutavel de uma execucao."""

    run_id: UUID
    tenant_id: str
    project_id: str
    agent_id: str
    status: RunStatus = "pending"
    parent_run_id: UUID | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("tenant_id is required and cannot be empty")
        if not self.project_id or not self.project_id.strip():
            raise ValueError("project_id is required and cannot be empty")
        if not self.agent_id or not self.agent_id.strip():
            raise ValueError("agent_id is required and cannot be empty")
        if not isinstance(self.run_id, UUID):
            raise TypeError(f"run_id must be UUID, got {type(self.run_id)}")
        if self.parent_run_id is not None and not isinstance(
            self.parent_run_id, UUID
        ):
            raise TypeError("parent_run_id must be UUID or None")
        if self.status not in VALID_TRANSITIONS:
            raise ValueError(f"invalid status: {self.status}")

    def with_status(self, new_status: RunStatus) -> "Run":
        """Retorna novo Run com status transicionado. Falha se invalido."""
        if not is_valid_transition(self.status, new_status):
            raise ValueError(
                f"invalid transition {self.status} -> {new_status}"
            )
        now = datetime.now(timezone.utc)
        extra: dict[str, Any] = {"status": new_status}
        if new_status == "running" and self.started_at is None:
            extra["started_at"] = now
        if new_status in ("done", "failed", "cancelled"):
            extra["finished_at"] = now
        return replace_run(self, **extra)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["run_id"] = str(self.run_id)
        d["parent_run_id"] = (
            str(self.parent_run_id) if self.parent_run_id else None
        )
        d["created_at"] = self.created_at.isoformat()
        d["started_at"] = (
            self.started_at.isoformat() if self.started_at else None
        )
        d["finished_at"] = (
            self.finished_at.isoformat() if self.finished_at else None
        )
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Run":
        return cls(
            run_id=UUID(data["run_id"]),
            tenant_id=data["tenant_id"],
            project_id=data["project_id"],
            agent_id=data["agent_id"],
            status=data.get("status", "pending"),
            parent_run_id=(
                UUID(data["parent_run_id"])
                if data.get("parent_run_id")
                else None
            ),
            created_at=_parse_dt(data["created_at"]),
            started_at=_parse_dt(data.get("started_at")),
            finished_at=_parse_dt(data.get("finished_at")),
            metadata=dict(data.get("metadata") or {}),
        )


def replace_run(run: Run, **changes: Any) -> Run:
    """Helper imutavel pra trocar campos do Run."""
    base = {
        "run_id": run.run_id,
        "tenant_id": run.tenant_id,
        "project_id": run.project_id,
        "agent_id": run.agent_id,
        "status": run.status,
        "parent_run_id": run.parent_run_id,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "metadata": dict(run.metadata),
    }
    base.update(changes)
    return Run(**base)


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def new_run(
    tenant_id: str,
    project_id: str,
    agent_id: str,
    *,
    parent_run_id: UUID | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Run:
    """Factory canonica. Gera run_id automatico."""
    return Run(
        run_id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        agent_id=agent_id,
        parent_run_id=parent_run_id,
        metadata=dict(metadata or {}),
    )


@dataclass(frozen=True, slots=True)
class Step:
    """Um passo dentro de um Run. Equivale a 1 round no loop tool_use."""

    step_id: UUID
    run_id: UUID
    index: int
    kind: Literal["message", "tool_use", "tool_result", "error"]
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass(frozen=True, slots=True)
class Event:
    """Evento emitido durante a execucao. Consumido via Scheduler.stream()."""

    event_id: UUID
    run_id: UUID
    kind: Literal[
        "run.created",
        "run.started",
        "run.step",
        "run.finished",
        "run.failed",
        "run.cancelled",
    ]
    payload: Mapping[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# -----------------------------------------------------------------------------
# Protocols (contratos de capacidade)
# -----------------------------------------------------------------------------


@runtime_checkable
class Agent(Protocol):
    """Contrato minimo de um agente registravel."""

    agent_id: str
    tenant_id: str

    def describe(self) -> Mapping[str, Any]: ...


@runtime_checkable
class Tool(Protocol):
    """Contrato minimo de uma tool registravel."""

    name: str

    def schema(self) -> Mapping[str, Any]: ...


# -----------------------------------------------------------------------------
# TypedDicts para especificacao de submit
# -----------------------------------------------------------------------------


class RunSpec(TypedDict, total=False):
    """Especificacao pra Scheduler.submit()."""

    tenant_id: str  # obrigatorio
    project_id: str  # obrigatorio
    agent_id: str  # obrigatorio
    parent_run_id: str | None
    input: Mapping[str, Any]
    metadata: Mapping[str, Any]


# -----------------------------------------------------------------------------
# Exceptions canonicas
# -----------------------------------------------------------------------------


class OrchError(Exception):
    """Base de todas as excecoes do orch_core."""


class AgentNotFound(OrchError):
    pass


class ToolNotFound(OrchError):
    pass


class InvalidTransition(OrchError):
    pass


class TenantIsolationViolation(OrchError):
    pass


__all__ = [
    "Agent",
    "AgentNotFound",
    "Event",
    "InvalidTransition",
    "OrchError",
    "Run",
    "RunSpec",
    "RunStatus",
    "Step",
    "TenantIsolationViolation",
    "Tool",
    "ToolNotFound",
    "VALID_TRANSITIONS",
    "is_valid_transition",
    "new_run",
    "replace_run",
]
