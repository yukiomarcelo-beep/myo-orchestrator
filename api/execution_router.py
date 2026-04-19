#!/usr/bin/env python3
"""
Execution Control Router — endpoints FastAPI para RBAC + Gatekeeper + Audit.

Montado em run_server.py via app.include_router().

Endpoints:
    POST /api/execution/session            — abre nova sessão isolada
    DELETE /api/execution/session/{id}     — fecha sessão
    POST /api/execution/run                — executa ação com todos os controles
    POST /api/execution/validate           — só valida (gatekeeper), sem executar
    GET  /api/execution/cost               — status de custo hoje
    GET  /api/execution/audit/{session_id} — log de auditoria da sessão
    GET  /api/execution/audit/recent       — últimas 100 entradas
    GET  /api/execution/audit/cost-summary — custo por agente hoje
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.execution_control import get_secure_orchestrator, AGENT_PERMISSIONS

router = APIRouter()


# ─── Request models ────────────────────────────────────────────────────────────

class RunBody(BaseModel):
    session_id: str
    agent: str
    action: str
    payload: dict
    confidence: float = 1.0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = "claude-sonnet"


class ValidateBody(BaseModel):
    action: str
    payload: dict
    confidence: float = 1.0


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/api/execution/session")
async def open_session():
    orch = get_secure_orchestrator()
    session_id = orch.start_session()
    return JSONResponse({"session_id": session_id})


@router.delete("/api/execution/session/{session_id}")
async def close_session(session_id: str):
    orch = get_secure_orchestrator()
    orch.close_session(session_id)
    return JSONResponse({"ok": True})


@router.post("/api/execution/run")
async def execute_action(body: RunBody):
    orch = get_secure_orchestrator()
    try:
        result = orch.execute(
            session_id=body.session_id,
            agent=body.agent,
            action=body.action,
            payload=body.payload,
            confidence=body.confidence,
            tokens_in=body.tokens_in,
            tokens_out=body.tokens_out,
            model=body.model,
        )
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/execution/validate")
async def validate_action(body: ValidateBody):
    """Dry-run: verifica gatekeeper sem executar nem logar."""
    orch = get_secure_orchestrator()
    gate = orch.gatekeeper.validate(body.action, body.payload, body.confidence)
    return JSONResponse({
        "decision": gate.decision.value,
        "reason": gate.reason,
        "requires_approval": gate.requires_approval,
    })


@router.get("/api/execution/cost")
async def cost_status():
    orch = get_secure_orchestrator()
    return JSONResponse(orch.cost_status())


@router.get("/api/execution/agents")
async def list_agents():
    """Lista agentes registrados e suas permissões."""
    return JSONResponse({
        agent: {
            "actions": cfg["actions"],
            "blocked_actions": cfg.get("blocked_actions", []),
            "limits": cfg.get("limits", {}),
        }
        for agent, cfg in AGENT_PERMISSIONS.items()
    })


@router.get("/api/execution/audit/recent")
async def audit_recent():
    orch = get_secure_orchestrator()
    if not orch._db_available:
        return JSONResponse({"error": "DATABASE_URL não configurada"}, status_code=503)
    try:
        entries = orch.audit.query_recent(100)
        return JSONResponse({"entries": entries})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/execution/audit/cost-summary")
async def audit_cost_summary():
    """Custo por agente hoje (em memória — não requer DB)."""
    orch = get_secure_orchestrator()
    if not orch._db_available:
        return JSONResponse({"error": "DATABASE_URL não configurada"}, status_code=503)
    try:
        summary = orch.audit.cost_summary_today()
        return JSONResponse({"summary": summary})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/execution/audit/daily-costs")
async def audit_daily_costs():
    """View daily_costs do PostgreSQL — histórico por agente/dia."""
    orch = get_secure_orchestrator()
    if not orch._db_available:
        return JSONResponse({"error": "DATABASE_URL não configurada"}, status_code=503)
    try:
        import psycopg2.extras
        conn = orch.audit._connect()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM daily_costs LIMIT 90")
            rows = [dict(r) for r in cur.fetchall()]
        return JSONResponse({"daily_costs": rows})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/execution/setup")
async def run_setup():
    """Cria tabelas e views no PostgreSQL (idempotente — IF NOT EXISTS)."""
    orch = get_secure_orchestrator()
    if not orch._db_available:
        return JSONResponse({"error": "DATABASE_URL não configurada"}, status_code=503)
    try:
        orch.setup()
        return JSONResponse({"ok": True, "message": "Tabelas e views criadas/verificadas."})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/execution/audit/{session_id}")
async def audit_session(session_id: str):
    orch = get_secure_orchestrator()
    if not orch._db_available:
        return JSONResponse({"error": "DATABASE_URL não configurada"}, status_code=503)
    try:
        entries = orch.audit.query_session(session_id)
        return JSONResponse({"session_id": session_id, "entries": entries})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
