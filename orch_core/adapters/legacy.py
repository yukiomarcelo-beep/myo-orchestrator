"""
orch_core.adapters.legacy
==========================

Shim pro `orchestrator.py` legado (LESSON-012).

Superficie historica assumida (a validar na LESSON-007 do repo):
- run_agent(agent_id, input, ...) -> dict
- execute(agent_name, messages, ...) -> dict

O shim:
1. Emite DeprecationWarning + log estruturado
2. Converte argumentos antigos em RunSpec
3. Delega pro Scheduler canonico
4. Retorna resultado no shape esperado pelo caller antigo

Se a assinatura real no repo for diferente da assumida aqui, Sonnet 4.6
ajusta na LESSON-007/012 sem mudar o nucleo (Scheduler eh agnostico).
"""
from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from orch_core.contracts import RunSpec
from orch_core.control.scheduler import Scheduler
from orch_core.adapters.deprecation import emit_deprecation


class LegacyOrchestratorShim:
    """Wrapper que emula a API do `orchestrator.py` original.

    Uso de migracao:
        # antes (codigo antigo espalhado no repo):
        from orchestrator import run_agent
        result = run_agent("agent-x", {"content": "..."})

        # depois (via shim, com warning):
        from orch_core.adapters.legacy import LegacyOrchestratorShim
        shim = LegacyOrchestratorShim(scheduler=..., default_tenant="t1",
                                       default_project="p1")
        result = shim.run_agent("agent-x", {"content": "..."})

        # meta (destino final da LESSON-013):
        scheduler.submit({"tenant_id": ..., "project_id": ...,
                          "agent_id": ..., "input": {...}})
    """

    SHIM_NAME = "orchestrator.py (legacy)"
    REPLACEMENT = "orch_core.control.scheduler.Scheduler"

    def __init__(
        self,
        *,
        scheduler: Scheduler,
        default_tenant: str,
        default_project: str,
        default_timeout: float = 60.0,
    ) -> None:
        self._scheduler = scheduler
        self._default_tenant = default_tenant
        self._default_project = default_project
        self._default_timeout = default_timeout

    def run_agent(
        self,
        agent_id: str,
        input_payload: Mapping[str, Any] | None = None,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        emit_deprecation(
            shim=f"{self.SHIM_NAME}.run_agent",
            replacement=f"{self.REPLACEMENT}.submit",
        )
        spec: RunSpec = {
            "tenant_id": tenant_id or self._default_tenant,
            "project_id": project_id or self._default_project,
            "agent_id": agent_id,
            "input": dict(input_payload or {}),
        }
        run_id = self._scheduler.submit(spec)
        result = self._scheduler.result(
            run_id,
            tenant_id=spec["tenant_id"],
            timeout=timeout or self._default_timeout,
        )
        return _result_to_legacy_shape(result)

    def execute(
        self,
        agent_name: str,
        messages: list[Mapping[str, Any]] | None = None,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """API historica do orchestrator.py. Extrai ultima mensagem do
        usuario como input canonico."""
        emit_deprecation(
            shim=f"{self.SHIM_NAME}.execute",
            replacement=f"{self.REPLACEMENT}.submit",
        )
        last_user = ""
        for m in reversed(messages or []):
            if m.get("role") == "user":
                last_user = str(m.get("content", ""))
                break
        return self.run_agent(
            agent_name,
            {"content": last_user},
            tenant_id=tenant_id,
            project_id=project_id,
        )


def _result_to_legacy_shape(result: Any) -> dict[str, Any]:
    """Converte RunResult canonico no shape esperado pelos callers
    antigos. Conservador: inclui campos comuns sem inventar."""
    run = result.run
    return {
        "run_id": str(run.run_id),
        "status": run.status,
        "output": dict(result.output) if result.output else {},
        "error": result.error,
        "tenant_id": run.tenant_id,
        "agent_id": run.agent_id,
    }


__all__ = ["LegacyOrchestratorShim"]
