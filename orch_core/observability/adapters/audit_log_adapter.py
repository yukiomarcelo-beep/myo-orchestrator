"""
orch_core.observability.adapters.audit_log_adapter
====================================================

Adapter que conecta o port AuditSink ao AuditLog canonico (LESSON-004).

Mapeamento:
  AuditSink.append(run_id, tenant_id, kind, payload)
    -> AuditLog.record(session_id=str(run_id), agent=tenant_id,
                       action=kind, decision=APPROVED, input_data=json(payload))

  AuditSink.events_of(run_id)
    -> AuditLog.query_session(str(run_id))
"""
from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID

from core.audit_log import AuditLog, GatekeeperDecision


class AuditLogAdapter:
    """Implementa AuditSink usando o AuditLog canonico (LESSON-004)."""

    def __init__(self, audit_log: AuditLog | None = None) -> None:
        self._log = audit_log or AuditLog()

    def append(
        self,
        *,
        run_id: UUID,
        tenant_id: str,
        kind: str,
        payload: Mapping[str, Any],
    ) -> None:
        self._log.record(
            session_id=str(run_id),
            agent=tenant_id,
            action=kind,
            decision=GatekeeperDecision.APPROVED,
            input_data=json.dumps(dict(payload), ensure_ascii=False, default=str),
        )

    def events_of(self, run_id: UUID) -> list[Mapping[str, Any]]:
        return self._log.query_session(str(run_id))


__all__ = ["AuditLogAdapter"]
