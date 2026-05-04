"""
orch_core.adapters.asyncio_adapter
===================================

Ponte async sobre o Scheduler sincrono.

Motivo: FastAPI e qualquer stack async precisam de AsyncIterator pra
StreamingResponse. O Scheduler canonico e sincrono por design (simplifica
testabilidade e raciocinio). Este adapter resolve a ponte SEM adicionar
asyncio ao nucleo.

Uso em FastAPI:

    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    from orch_core.adapters.asyncio_adapter import async_stream_sse

    app = FastAPI()

    @app.get("/runs/{run_id}/stream")
    async def stream(run_id: str):
        return StreamingResponse(
            async_stream_sse(scheduler, run_id, tenant_id=...),
            media_type="text/event-stream",
        )
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator
from uuid import UUID

from orch_core.adapters.war_room import format_sse_event
from orch_core.contracts import Event
from orch_core.control.scheduler import Scheduler


async def async_stream(
    scheduler: Scheduler,
    run_id: str | UUID,
    *,
    tenant_id: str | None = None,
    timeout: float | None = None,
) -> AsyncIterator[Event]:
    """AsyncIterator de Events. Roda o iterator sincrono num executor
    pra nao bloquear o event loop."""
    rid = run_id if isinstance(run_id, UUID) else UUID(run_id)
    it = scheduler.stream(rid, tenant_id=tenant_id, timeout=timeout)
    loop = asyncio.get_event_loop()
    while True:
        ev = await loop.run_in_executor(None, _next_or_none, it)
        if ev is None:
            return
        yield ev


async def async_stream_sse(
    scheduler: Scheduler,
    run_id: str | UUID,
    *,
    tenant_id: str | None = None,
    timeout: float | None = None,
) -> AsyncIterator[str]:
    """AsyncIterator de chunks SSE formatados."""
    async for ev in async_stream(scheduler, run_id, tenant_id=tenant_id, timeout=timeout):
        yield format_sse_event(ev)


def _next_or_none(it):  # type: ignore[no-untyped-def]
    try:
        return next(it)
    except StopIteration:
        return None


__all__ = ["async_stream", "async_stream_sse"]
