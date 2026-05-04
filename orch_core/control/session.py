"""
orch_core.control.session
==========================

Session store — fonte unica do estado de runs in-flight e concluidos.

Responsabilidades:
- Guardar Run -> estado atual (pending/running/done/failed/cancelled)
- Guardar flag de cancelamento cooperativo por run_id
- Guardar referencias a tarefas em execucao (Future)
- Permitir lookup por run_id com tenant isolation
- Thread-safe por design

NAO faz:
- Persistencia em PostgreSQL (adapter futuro, plugavel)
- Propagacao de eventos (isso e EventSink)
- Execucao (isso e Runner)

Hoje implementacao em memoria. Na LESSON-011.1 pode virar adapter sobre
AuditLog (LESSON-004) pra sobreviver a restart de processo.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from orch_core.contracts import (
    OrchError,
    Run,
    TenantIsolationViolation,
)


class RunNotFound(OrchError):
    pass


@dataclass
class SessionEntry:
    """Entrada mutavel no store. O Run dentro e imutavel; o wrapper troca
    a referencia quando o status transiciona."""

    run: Run
    future: Future[Any] | None = None
    cancel_flag: threading.Event = field(default_factory=threading.Event)
    result: Any | None = None
    error: str | None = None


class SessionStore:
    """Store thread-safe de sessions. Uma instancia serve um processo."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[UUID, SessionEntry] = {}

    # -- escrita --------------------------------------------------------------

    def create(self, run: Run) -> SessionEntry:
        with self._lock:
            if run.run_id in self._entries:
                raise ValueError(f"run_id {run.run_id} already exists")
            entry = SessionEntry(run=run)
            self._entries[run.run_id] = entry
            return entry

    def update_run(self, run_id: UUID, new_run: Run) -> None:
        with self._lock:
            entry = self._entries.get(run_id)
            if entry is None:
                raise RunNotFound(f"run {run_id} not found")
            if entry.run.tenant_id != new_run.tenant_id:
                raise TenantIsolationViolation(f"tenant mismatch on run {run_id}")
            entry.run = new_run

    def attach_future(self, run_id: UUID, future: Future[Any]) -> None:
        with self._lock:
            entry = self._entries.get(run_id)
            if entry is None:
                raise RunNotFound(f"run {run_id} not found")
            entry.future = future

    def set_result(self, run_id: UUID, result: Any, *, error: str | None = None) -> None:
        with self._lock:
            entry = self._entries.get(run_id)
            if entry is None:
                raise RunNotFound(f"run {run_id} not found")
            entry.result = result
            entry.error = error

    # -- leitura --------------------------------------------------------------

    def get(self, run_id: UUID, *, tenant_id: str | None = None) -> SessionEntry:
        with self._lock:
            entry = self._entries.get(run_id)
        if entry is None:
            raise RunNotFound(f"run {run_id} not found")
        if tenant_id is not None and entry.run.tenant_id != tenant_id:
            raise TenantIsolationViolation(f"run {run_id} not visible to tenant {tenant_id}")
        return entry

    def list_by_tenant(
        self,
        tenant_id: str,
        *,
        project_id: str | None = None,
        status: str | None = None,
    ) -> list[Run]:
        with self._lock:
            runs = [e.run for e in self._entries.values() if e.run.tenant_id == tenant_id]
        if project_id is not None:
            runs = [r for r in runs if r.project_id == project_id]
        if status is not None:
            runs = [r for r in runs if r.status == status]
        return runs

    # -- cancelamento ---------------------------------------------------------

    def request_cancel(self, run_id: UUID, *, tenant_id: str | None = None) -> bool:
        """Sinaliza cancel. Retorna True se sinal foi levantado agora,
        False se ja estava levantado ou run ja terminou."""
        entry = self.get(run_id, tenant_id=tenant_id)
        if entry.run.status in ("done", "failed", "cancelled"):
            return False
        if entry.cancel_flag.is_set():
            return False
        entry.cancel_flag.set()
        return True

    def is_cancelled(self, run_id: UUID) -> bool:
        with self._lock:
            entry = self._entries.get(run_id)
        return entry is not None and entry.cancel_flag.is_set()

    # -- housekeeping ---------------------------------------------------------

    def clear(self) -> None:
        """So pra testes."""
        with self._lock:
            self._entries.clear()


__all__ = [
    "RunNotFound",
    "SessionEntry",
    "SessionStore",
]
