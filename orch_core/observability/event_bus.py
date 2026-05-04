"""
orch_core.observability.event_bus
==================================

EventBus in-memory com suporte a:
- Broadcast a multiplos subscribers
- Fan-out por run_id (stream() do Scheduler consome daqui)
- Thread-safe

Implementa EventSink (port LESSON-010). Alimenta
Scheduler.stream(run_id). No futuro pode ser trocado por adapter sobre
Redis Pub/Sub / Kafka sem mudar API.
"""
from __future__ import annotations

import queue
import threading
from typing import Iterator
from uuid import UUID

from orch_core.contracts import Event
from orch_core.observability.ports import EventSink

_SENTINEL = object()


class InMemoryEventBus(EventSink):
    """Fan-out de eventos por run_id. Um stream por run."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # run_id -> lista de queues (cada subscriber tem a sua)
        self._subs: dict[UUID, list[queue.Queue]] = {}
        # run_ids ja fechados (stream emitiu terminal event)
        self._closed: set[UUID] = set()
        # Buffer de eventos emitidos ANTES do subscriber se conectar.
        # Chave: run_id. Necessario pro stream nao perder run.created
        # se o subscriber chegar tarde.
        self._backlog: dict[UUID, list[Event]] = {}

    # -- EventSink ------------------------------------------------------------

    def emit(self, event: Event) -> None:
        with self._lock:
            # Guarda no backlog ate o run fechar
            self._backlog.setdefault(event.run_id, []).append(event)
            subs = list(self._subs.get(event.run_id, []))
            if event.kind in ("run.finished", "run.failed", "run.cancelled"):
                self._closed.add(event.run_id)

        for q in subs:
            q.put(event)

        # Se eh terminal, fecha todos os subscribers desse run
        if event.kind in ("run.finished", "run.failed", "run.cancelled"):
            for q in subs:
                q.put(_SENTINEL)

    # -- consumo --------------------------------------------------------------

    def stream(self, run_id: UUID, *, timeout: float | None = None) -> Iterator[Event]:
        """Iterator bloqueante de eventos do run_id.

        Entrega o backlog ja acumulado antes de comecar a consumir live.
        Encerra quando recebe evento terminal (finished/failed/cancelled).
        """
        q: queue.Queue = queue.Queue()

        with self._lock:
            backlog = list(self._backlog.get(run_id, []))
            already_closed = run_id in self._closed
            self._subs.setdefault(run_id, []).append(q)

        # Entrega backlog fora do lock
        seen_ids: set[UUID] = set()
        for ev in backlog:
            seen_ids.add(ev.event_id)
            yield ev

        if already_closed:
            # Backlog ja contem tudo; fim
            with self._lock:
                self._subs[run_id].remove(q)
            return

        try:
            while True:
                item = q.get(timeout=timeout) if timeout else q.get()
                if item is _SENTINEL:
                    return
                # Dedup via event_id (contrato LESSON-008)
                if item.event_id in seen_ids:
                    continue
                seen_ids.add(item.event_id)
                yield item
        finally:
            with self._lock:
                if q in self._subs.get(run_id, []):
                    self._subs[run_id].remove(q)

    # -- housekeeping ---------------------------------------------------------

    def clear(self) -> None:
        with self._lock:
            self._subs.clear()
            self._closed.clear()
            self._backlog.clear()


__all__ = ["InMemoryEventBus"]
