"""
orch_core.adapters.war_room
============================

Adapter HTTP/SSE do War Room (LESSON-012).

Substitui o codigo HTTP + streaming que vivia dentro do `orchestrator.py`
original. Delega TUDO pro Scheduler canonico.

Este modulo nao importa Flask/FastAPI/etc. Fornece funcoes puras que
convertem entre shapes HTTP e chamadas do Scheduler. O caller escolhe o
framework: WSGI tradicional usa `handle_submit`/`format_sse_event`;
async/FastAPI usa `async_stream` (adapter asyncio separado).

Isto mantem orch_core sem dependencias web.
"""
from __future__ import annotations

import json
from typing import Any, Iterator, Mapping
from uuid import UUID

from orch_core.contracts import Event, RunSpec, TenantIsolationViolation
from orch_core.control.scheduler import Scheduler


class WarRoomAdapter:
    """Adapter fino que expoe operacoes do War Room sobre o Scheduler.

    Um adapter por Scheduler — thread-safe porque o Scheduler e.
    """

    def __init__(self, *, scheduler: Scheduler) -> None:
        self._scheduler = scheduler

    # -- HTTP-like handlers ---------------------------------------------------

    def handle_submit(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """POST /runs — espera JSON com tenant_id/project_id/agent_id/input."""
        spec = _body_to_spec(body)
        run_id = self._scheduler.submit(spec)
        return {"run_id": str(run_id), "status": "pending"}

    def handle_status(
        self, run_id: str, *, tenant_id: str | None = None
    ) -> dict[str, Any]:
        """GET /runs/{id}."""
        run = self._scheduler.status(UUID(run_id), tenant_id=tenant_id)
        return run.to_dict()

    def handle_cancel(
        self, run_id: str, *, tenant_id: str | None = None
    ) -> dict[str, Any]:
        """POST /runs/{id}/cancel."""
        signaled = self._scheduler.cancel(UUID(run_id), tenant_id=tenant_id)
        return {"run_id": run_id, "cancel_signaled": signaled}

    def handle_list(
        self,
        tenant_id: str,
        *,
        project_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /runs?tenant=..."""
        return [
            r.to_dict()
            for r in self._scheduler.list_runs(
                tenant_id, project_id=project_id, status=status
            )
        ]

    # -- SSE stream -----------------------------------------------------------

    def stream_sse(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        timeout: float | None = None,
    ) -> Iterator[str]:
        """Gera chunks formatados em Server-Sent Events protocol.

        Uso em WSGI/Flask:
            return Response(adapter.stream_sse(run_id, ...),
                            mimetype="text/event-stream")
        """
        events = self._scheduler.stream(
            UUID(run_id), tenant_id=tenant_id, timeout=timeout
        )
        for event in events:
            yield format_sse_event(event)


# -----------------------------------------------------------------------------
# helpers puras
# -----------------------------------------------------------------------------


def _body_to_spec(body: Mapping[str, Any]) -> RunSpec:
    required = ("tenant_id", "project_id", "agent_id")
    for key in required:
        if not body.get(key):
            raise ValueError(f"missing field: {key}")
    spec: RunSpec = {
        "tenant_id": body["tenant_id"],
        "project_id": body["project_id"],
        "agent_id": body["agent_id"],
    }
    if body.get("input") is not None:
        spec["input"] = dict(body["input"])
    if body.get("parent_run_id"):
        spec["parent_run_id"] = str(body["parent_run_id"])
    if body.get("metadata"):
        spec["metadata"] = dict(body["metadata"])
    return spec


def format_sse_event(event: Event) -> str:
    """Formata Event canonico como chunk SSE."""
    payload = {
        "event_id": str(event.event_id),
        "run_id": str(event.run_id),
        "kind": event.kind,
        "payload": dict(event.payload),
        "timestamp": event.timestamp.isoformat(),
    }
    return (
        f"event: {event.kind}\n"
        f"id: {event.event_id}\n"
        f"data: {json.dumps(payload)}\n\n"
    )


__all__ = ["WarRoomAdapter", "format_sse_event"]
