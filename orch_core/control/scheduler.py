"""
orch_core.control.scheduler
============================

Scheduler canonico (LESSON-011). PONTO UNICO de entrada pra execucao.

Invariantes reforcados:
- Nenhum caller externo instancia Runner direto. Sempre passa por aqui.
- submit() eh nao-bloqueante. Retorna run_id imediatamente.
- status(), cancel(), stream(), list_runs() sao as unicas formas de
  observar/intervir num run submetido.
- tenant_id e verificado em TODA leitura/escrita. Isolation por
  construcao.
- Concorrencia controlada por max_workers. Semafaro global + por tenant
  (quota).

Implementacao MVP: ThreadPoolExecutor single-process. Na LESSON-011.1
vira pool distribuido (Redis queue / dramatiq) sem mudar API publica.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Iterator, Mapping
from uuid import UUID, uuid4

from orch_core.contracts import (
    Event,
    OrchError,
    Run,
    RunSpec,
    TenantIsolationViolation,
    new_run,
)
from orch_core.control.session import SessionStore
from orch_core.execution.runner import Runner, RunResult
from orch_core.observability.event_bus import InMemoryEventBus


class SchedulerError(OrchError):
    pass


class Scheduler:
    """Choke point unico. NAO instanciar Runner em outro lugar."""

    def __init__(
        self,
        *,
        runner: Runner,
        store: SessionStore | None = None,
        event_bus: InMemoryEventBus | None = None,
        max_workers: int = 8,
        tenant_quotas: Mapping[str, int] | None = None,
    ) -> None:
        self._runner = runner
        self._store = store or SessionStore()
        self._bus = event_bus or InMemoryEventBus()
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="orch-worker"
        )
        self._max_workers = max_workers
        # Semaforo por tenant pra quota de concorrencia
        self._tenant_quotas = dict(tenant_quotas or {})
        self._tenant_sems: dict[str, threading.BoundedSemaphore] = {}
        self._tenant_sems_lock = threading.Lock()
        self._closed = False

    # -- API publica ----------------------------------------------------------

    def submit(self, spec: RunSpec) -> UUID:
        """Submete RunSpec. Retorna run_id imediato. Nao bloqueia."""
        if self._closed:
            raise SchedulerError("scheduler is closed")
        tenant_id = spec.get("tenant_id")
        project_id = spec.get("project_id")
        agent_id = spec.get("agent_id")
        if not (tenant_id and project_id and agent_id):
            raise SchedulerError(
                "RunSpec must include tenant_id, project_id, agent_id"
            )

        parent_raw = spec.get("parent_run_id")
        parent_uuid: UUID | None = None
        if isinstance(parent_raw, UUID):
            parent_uuid = parent_raw
        elif isinstance(parent_raw, str):
            parent_uuid = UUID(parent_raw)

        run = new_run(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_id=agent_id,
            parent_run_id=parent_uuid,
            metadata=spec.get("metadata") or {},
        )
        self._store.create(run)

        # Dispara no pool. O Runner gerencia o ciclo de vida completo.
        future = self._pool.submit(self._run_task, run, spec)
        self._store.attach_future(run.run_id, future)
        return run.run_id

    def status(self, run_id: UUID, *, tenant_id: str | None = None) -> Run:
        entry = self._store.get(run_id, tenant_id=tenant_id)
        return entry.run

    def cancel(self, run_id: UUID, *, tenant_id: str | None = None) -> bool:
        """Sinaliza cancelamento cooperativo. Retorna True se o sinal
        foi levantado agora. False se run ja terminou ou ja estava
        cancelando."""
        return self._store.request_cancel(run_id, tenant_id=tenant_id)

    def stream(
        self,
        run_id: UUID,
        *,
        tenant_id: str | None = None,
        timeout: float | None = None,
    ) -> Iterator[Event]:
        """Stream de eventos do run. Bloqueante. Encerra em terminal event.

        Tenant isolation: se tenant_id for passado, valida antes de abrir
        o stream; runs de outros tenants ficam invisiveis.
        """
        # Valida visibilidade antes de streamar
        self._store.get(run_id, tenant_id=tenant_id)
        yield from self._bus.stream(run_id, timeout=timeout)

    def list_runs(
        self,
        tenant_id: str,
        *,
        project_id: str | None = None,
        status: str | None = None,
    ) -> list[Run]:
        return self._store.list_by_tenant(
            tenant_id, project_id=project_id, status=status
        )

    def result(
        self, run_id: UUID, *, tenant_id: str | None = None, timeout: float | None = None
    ) -> RunResult:
        """Bloqueia ate o run terminar. Retorna RunResult."""
        entry = self._store.get(run_id, tenant_id=tenant_id)
        if entry.future is None:
            raise SchedulerError(f"run {run_id} has no future attached")
        return entry.future.result(timeout=timeout)  # type: ignore[no-any-return]

    def close(self, *, wait: bool = True) -> None:
        self._closed = True
        self._pool.shutdown(wait=wait)

    # -- interno --------------------------------------------------------------

    def _tenant_sem(self, tenant_id: str) -> threading.BoundedSemaphore | None:
        quota = self._tenant_quotas.get(tenant_id)
        if quota is None:
            return None
        with self._tenant_sems_lock:
            sem = self._tenant_sems.get(tenant_id)
            if sem is None:
                sem = threading.BoundedSemaphore(quota)
                self._tenant_sems[tenant_id] = sem
            return sem

    def _run_task(self, run: Run, spec: RunSpec) -> RunResult:
        sem = self._tenant_sem(run.tenant_id)
        if sem is not None:
            sem.acquire()
        try:
            input_payload = dict(spec.get("input", {}))
            result = self._runner.execute_run(
                run,
                input_payload=input_payload,
                is_cancelled=lambda: self._store.is_cancelled(run.run_id),
            )
            self._store.update_run(run.run_id, result.run)
            self._store.set_result(run.run_id, result, error=result.error)
            return result
        finally:
            if sem is not None:
                sem.release()


__all__ = ["Scheduler", "SchedulerError"]
