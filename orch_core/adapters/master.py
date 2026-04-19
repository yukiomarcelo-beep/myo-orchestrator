"""
orch_core.adapters.master
==========================

Shim pro `master_controller` legado (LESSON-012).

Superficie historica assumida (a validar na LESSON-007):
- start_session(agent_id, ...) -> session_id
- send_message(session_id, message) -> reply
- end_session(session_id) -> None
- get_session_status(session_id) -> status

A noticao de "sessao longa" do master_controller mapeia 1:1 pro
conceito de Run do canonico. O shim:
1. start_session -> Scheduler.submit(...); guarda mapping session_id -> run_id
2. send_message -> nao ha analogo direto (Runner eh single-shot por
   design); retorna NotImplementedError claro
3. end_session -> Scheduler.cancel(run_id)
4. get_session_status -> Scheduler.status(run_id)

Nota arquitetural: send_message no master_controller antigo provavelmente
usava persistencia de conversation state. Como o canonico e stateless,
sessoes multi-turno sao um CASO A RESOLVER na LESSON-007. Se o uso real
de send_message for baixo, aceitamos o break e forcamos migracao. Se for
alto, precisa LESSON-014 (sessoes conversacionais persistentes).
"""
from __future__ import annotations

import threading
from typing import Any, Mapping
from uuid import UUID

from orch_core.contracts import RunSpec
from orch_core.control.scheduler import Scheduler
from orch_core.adapters.deprecation import emit_deprecation


class MasterControllerShim:
    """Wrapper que emula a API do `master_controller` original."""

    SHIM_NAME = "master_controller (legacy)"
    REPLACEMENT = "orch_core.control.scheduler.Scheduler"

    def __init__(
        self,
        *,
        scheduler: Scheduler,
        default_tenant: str,
        default_project: str,
    ) -> None:
        self._scheduler = scheduler
        self._default_tenant = default_tenant
        self._default_project = default_project
        self._lock = threading.Lock()
        # session_id (str) <-> run_id (UUID). session_id mantem compat
        # com callers antigos que guardam o id como string.
        self._sessions: dict[str, UUID] = {}

    def start_session(
        self,
        agent_id: str,
        input_payload: Mapping[str, Any] | None = None,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> str:
        emit_deprecation(
            shim=f"{self.SHIM_NAME}.start_session",
            replacement=f"{self.REPLACEMENT}.submit",
        )
        spec: RunSpec = {
            "tenant_id": tenant_id or self._default_tenant,
            "project_id": project_id or self._default_project,
            "agent_id": agent_id,
            "input": dict(input_payload or {}),
        }
        run_id = self._scheduler.submit(spec)
        session_id = str(run_id)
        with self._lock:
            self._sessions[session_id] = run_id
        return session_id

    def send_message(
        self, session_id: str, message: Mapping[str, Any]
    ) -> None:
        """Multi-turno nao tem suporte direto no canonico stateless.

        Comportamento do shim: levanta NotImplementedError explicito com
        ponteiro de migracao. Isso forca o caller a mover pra padrao
        correto (submit um novo Run com historico carregado no input).
        """
        emit_deprecation(
            shim=f"{self.SHIM_NAME}.send_message",
            replacement=f"{self.REPLACEMENT}.submit (com historico no input)",
        )
        raise NotImplementedError(
            "send_message nao tem equivalente direto no Scheduler canonico. "
            "Submeta um novo Run via Scheduler.submit carregando o historico "
            "no campo 'input'. Veja docs/memoria/LESSON-012-adapters.md "
            "secao 'Migracao de sessoes multi-turno'."
        )

    def end_session(self, session_id: str) -> bool:
        emit_deprecation(
            shim=f"{self.SHIM_NAME}.end_session",
            replacement=f"{self.REPLACEMENT}.cancel",
        )
        run_id = self._resolve(session_id)
        return self._scheduler.cancel(run_id)

    def get_session_status(self, session_id: str) -> str:
        emit_deprecation(
            shim=f"{self.SHIM_NAME}.get_session_status",
            replacement=f"{self.REPLACEMENT}.status",
        )
        run_id = self._resolve(session_id)
        return self._scheduler.status(run_id).status

    def _resolve(self, session_id: str) -> UUID:
        with self._lock:
            run_id = self._sessions.get(session_id)
        if run_id is None:
            # Pode ser que o caller tenha o run_id direto como string
            try:
                return UUID(session_id)
            except (ValueError, TypeError):
                raise KeyError(f"unknown session_id: {session_id}")
        return run_id


__all__ = ["MasterControllerShim"]
