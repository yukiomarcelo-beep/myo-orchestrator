"""
api/orchestrator_canonical.py
==============================

Rotas CANONICAS que substituem in-place o bloco linhas 3746-4268 do
myo_server.py (5 rotas do War Room legado).

Paths PRESERVADOS:
    POST /api/orchestrator/run
    GET  /api/orchestrator/status
    GET  /api/orchestrator/result
    GET  /api/orchestrator/opportunity
    GET  /orch                          (HTML cockpit)

Paths NOVOS (aditivos, nao quebram nada):
    POST /api/orchestrator/cancel/{run_id}
    GET  /api/orchestrator/stream/{run_id}   (SSE do Scheduler.stream)
    GET  /api/orchestrator/runs              (list_runs)

Shape de resposta preservado onde possivel (vide _legacy_shape helpers).
Callers existentes (cockpit antigo, scripts MYO, n8n) continuam
funcionando. Por dentro, tudo delega pro WarRoomAdapter.

INTEGRACAO NO myo_server.py:
    1. REMOVER o bloco de linhas ~3746-4268 (as 5 rotas legadas)
    2. No topo do myo_server.py, ADICIONAR:

        from api.orchestrator_canonical import (
            mount_canonical_orchestrator,
            bootstrap_scheduler,
        )

    3. Apos `app = FastAPI(...)`, ADICIONAR:

        _scheduler = bootstrap_scheduler()
        mount_canonical_orchestrator(app, scheduler=_scheduler)

    4. No shutdown handler (ou lifespan), ADICIONAR:

        _scheduler.close(wait=True)

TODO Sonnet 4.6 ao aplicar:
    - Ler bloco 3746-4268 e identificar chaves especificas do JSON de
      resposta que precisam ser preservadas exatamente. Ajustar
      _legacy_shape_* abaixo se divergir.
    - bootstrap_scheduler() usa adapters placeholder. Trocar pelos
      reais quando a FASE 2 do runbook estiver feita.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from orch_core.adapters.asyncio_adapter import async_stream_sse
from orch_core.adapters.war_room import WarRoomAdapter
from orch_core.contracts import TenantIsolationViolation

# -----------------------------------------------------------------------------
# Tenant resolution
# -----------------------------------------------------------------------------


def resolve_tenant(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> str:
    """Header X-Tenant-Id ou env MYO_DEFAULT_TENANT (fallback 'marcelo')."""
    if x_tenant_id:
        return x_tenant_id
    return os.environ.get("MYO_DEFAULT_TENANT", "marcelo")


# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------


class RunRequest(BaseModel):
    """Shape do body aceito pelo POST /api/orchestrator/run.

    Mantem compat com callers antigos: campos que o legado aceitava
    continuam aceitos, mapeados pro RunSpec canonico.
    """

    project_id: str = Field(default="myo-default")
    agent_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    parent_run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# -----------------------------------------------------------------------------
# Shape helpers — preservam compat com cockpit antigo
# -----------------------------------------------------------------------------


def _legacy_shape_status(run_dict: dict[str, Any]) -> dict[str, Any]:
    """Converte Run.to_dict() canonico no shape do _orch_state legado.

    _orch_state legado: {running, mode, started_at, pid, log}
    Aliases para compat com cockpit antigo e callers externos (n8n etc).
    """
    meta = run_dict.get("metadata") or {}
    return {
        **run_dict,
        # Aliases de compat com cockpit antigo:
        "state": run_dict.get("status"),
        "id": run_dict.get("run_id"),
        # Campos do _orch_state legado preservados para nao quebrar callers:
        "running": run_dict.get("status") == "running",
        "mode": meta.get("mode", ""),
        "pid": None,  # canonical nao usa subprocess
        "log": [],  # canonical usa AuditLog; sem log in-memory
    }


def _legacy_shape_result(run_dict: dict[str, Any], output: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "run_id": run_dict.get("run_id"),
        "status": run_dict.get("status"),
        "result": output or {},
        "output": output or {},  # alias
    }


# -----------------------------------------------------------------------------
# Mount function — e o que o myo_server.py chama
# -----------------------------------------------------------------------------


def mount_canonical_orchestrator(app: FastAPI, *, scheduler) -> None:  # type: ignore[no-untyped-def]
    """Registra as 5 rotas legadas (paths preservados) + 3 rotas novas
    no app FastAPI, delegando tudo pro WarRoomAdapter/Scheduler."""

    adapter = WarRoomAdapter(scheduler=scheduler)

    # -------------------------------------------------------------------------
    # POST /api/orchestrator/run  (substitui linha 3746 legada)
    # -------------------------------------------------------------------------
    @app.post("/api/orchestrator/run")
    def orch_run(
        body: RunRequest,
        tenant_id: str = Depends(resolve_tenant),
    ) -> dict[str, Any]:
        try:
            resp = adapter.handle_submit(
                {
                    "tenant_id": tenant_id,
                    "project_id": body.project_id,
                    "agent_id": body.agent_id,
                    "input": body.input,
                    "parent_run_id": body.parent_run_id,
                    "metadata": body.metadata,
                }
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        # Compat com cockpit antigo: inclui aliases
        return {**resp, "id": resp["run_id"], "state": resp["status"]}

    # -------------------------------------------------------------------------
    # GET /api/orchestrator/status  (substitui linha 4057)
    # -------------------------------------------------------------------------
    @app.get("/api/orchestrator/status")
    def orch_status(
        run_id: str = Query(..., alias="run_id"),
        tenant_id: str = Depends(resolve_tenant),
    ) -> dict[str, Any]:
        try:
            run_dict = adapter.handle_status(run_id, tenant_id=tenant_id)
        except TenantIsolationViolation:
            raise HTTPException(status_code=403, detail="tenant mismatch")
        return _legacy_shape_status(run_dict)

    # -------------------------------------------------------------------------
    # GET /api/orchestrator/result  (substitui linha 4217)
    # -------------------------------------------------------------------------
    @app.get("/api/orchestrator/result")
    def orch_result(
        run_id: str = Query(..., alias="run_id"),
        tenant_id: str = Depends(resolve_tenant),
    ) -> dict[str, Any]:
        try:
            run_dict = adapter.handle_status(run_id, tenant_id=tenant_id)
        except TenantIsolationViolation:
            raise HTTPException(status_code=403, detail="tenant mismatch")
        # Puxa o resultado do Scheduler (ja terminou? devolve output)
        try:
            rid = UUID(run_id)
            run_result = scheduler.result(rid, tenant_id=tenant_id, timeout=0.1)
            output = dict(run_result.output or {})
        except Exception:
            output = {}
        return _legacy_shape_result(run_dict, output)

    # -------------------------------------------------------------------------
    # GET /api/orchestrator/opportunity  (substitui linha 4231)
    # -------------------------------------------------------------------------
    # Semantica legada: retornava decisao salva. No canonico, isso vira
    # metadata/output do run. Preserva a rota devolvendo o campo
    # 'opportunity' do output se existir, senao dict vazio.
    @app.get("/api/orchestrator/opportunity")
    def orch_opportunity(
        run_id: str = Query(..., alias="run_id"),
        tenant_id: str = Depends(resolve_tenant),
    ) -> dict[str, Any]:
        try:
            rid = UUID(run_id)
            run_result = scheduler.result(rid, tenant_id=tenant_id, timeout=0.1)
            output = dict(run_result.output or {})
        except TenantIsolationViolation:
            raise HTTPException(status_code=403, detail="tenant mismatch")
        except Exception:
            return {"opportunity": None, "run_id": run_id}
        return {
            "run_id": run_id,
            "opportunity": output.get("opportunity") or output.get("decision"),
            "raw_output": output,
        }

    # -------------------------------------------------------------------------
    # POST /api/orchestrator/cancel/{run_id}  (NOVA - antes nao existia)
    # -------------------------------------------------------------------------
    @app.post("/api/orchestrator/cancel/{run_id}")
    def orch_cancel(
        run_id: str,
        tenant_id: str = Depends(resolve_tenant),
    ) -> dict[str, Any]:
        try:
            return adapter.handle_cancel(run_id, tenant_id=tenant_id)
        except TenantIsolationViolation:
            raise HTTPException(status_code=403, detail="tenant mismatch")

    # -------------------------------------------------------------------------
    # GET /api/orchestrator/stream/{run_id}  (NOVA - SSE canonico)
    # -------------------------------------------------------------------------
    @app.get("/api/orchestrator/stream/{run_id}")
    async def orch_stream(
        run_id: str,
        tenant_id: str = Depends(resolve_tenant),
    ) -> StreamingResponse:
        return StreamingResponse(
            async_stream_sse(scheduler, run_id, tenant_id=tenant_id, timeout=None),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # -------------------------------------------------------------------------
    # GET /api/orchestrator/runs  (NOVA - list_runs)
    # -------------------------------------------------------------------------
    @app.get("/api/orchestrator/runs")
    def orch_list(
        project_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
        tenant_id: str = Depends(resolve_tenant),
    ) -> list[dict[str, Any]]:
        return adapter.handle_list(tenant_id, project_id=project_id, status=status)

    # -------------------------------------------------------------------------
    # GET /orch  (substitui linha 4268 — cockpit HTML)
    # -------------------------------------------------------------------------
    @app.get("/orch", response_class=HTMLResponse)
    def orch_cockpit() -> HTMLResponse:
        from api.orchestrator_cockpit_html import COCKPIT_HTML

        return HTMLResponse(content=COCKPIT_HTML)


# -----------------------------------------------------------------------------
# Bootstrap do Scheduler
# -----------------------------------------------------------------------------


def bootstrap_scheduler():  # type: ignore[no-untyped-def]
    """Cria Scheduler canonico com adapters reais (FASE 2 concluida).

    Requer env: ANTHROPIC_API_KEY
    Opcional:   MYO_DEFAULT_TENANT (default: 'marcelo')
                ORCH_RUNNER_MAX_STEPS
                ORCH_RUNNER_SHADOW_MODE

    Para testar sem API real: MYO_DEV_MODE=1 usa dev_scheduler().
    """
    import os

    from orch_core.control.registry import Registry
    from orch_core.control.scheduler import Scheduler
    from orch_core.execution import FeatureFlags, Runner
    from orch_core.observability.adapters.anthropic_agent_executor import (
        AnthropicAgentExecutor,
    )
    from orch_core.observability.adapters.audit_log_adapter import AuditLogAdapter
    from orch_core.observability.adapters.runtime_guard_adapter import (
        RuntimeGuardAdapter,
    )
    from orch_core.observability.event_bus import InMemoryEventBus

    reg = Registry()
    # Agents e tools sao registrados em tempo de execucao pelos callers.
    # Para registrar agents fixos: reg.register_agent(MyAgent())

    bus = InMemoryEventBus()
    runner = Runner(
        registry=reg,
        audit=AuditLogAdapter(),
        guard=RuntimeGuardAdapter(execution_context=os.getenv("ORCH_EXEC_CONTEXT", "mvp")),
        agent_executor=AnthropicAgentExecutor(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        ),
        events=bus,
        flags=FeatureFlags(),
    )
    return Scheduler(runner=runner, event_bus=bus, max_workers=8)


__all__ = [
    "bootstrap_scheduler",
    "mount_canonical_orchestrator",
    "resolve_tenant",
]
