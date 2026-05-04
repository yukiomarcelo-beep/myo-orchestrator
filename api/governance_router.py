#!/usr/bin/env python3
"""
Governance Router — endpoints FastAPI para controle de autonomia.

Montado em run_server.py via app.include_router().

Endpoints:
    GET  /api/governance/config          — lê config atual
    POST /api/governance/config          — salva config (limites + modo)
    POST /api/governance/mode            — muda só o modo
    GET  /api/governance/budget          — status do orçamento
    POST /api/governance/avaliar         — avalia uma ação antes de executar
    POST /api/governance/registrar-gasto — acumula gasto aprovado
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from policies.governance import (
    avaliar_execucao,
    budget_status,
    get_config,
    registrar_gasto,
    save_config,
    set_mode,
)

router = APIRouter()


# Request models


class ModoBody(BaseModel):
    modo: str  # manual | assistido | autonomo


class ConfigBody(BaseModel):
    modo: Optional[str] = None
    limite_mensal: Optional[float] = None
    limite_por_acao: Optional[float] = None


class AvaliarBody(BaseModel):
    custo: float
    lucro_estimado: float = 0.0


class GastoBody(BaseModel):
    custo: float


# Endpoints


@router.get("/api/governance/config")
async def governance_get_config():
    cfg = get_config()
    return JSONResponse({**cfg, "budget": budget_status(cfg)})


@router.post("/api/governance/config")
async def governance_save_config(body: ConfigBody):
    cfg = get_config()
    if body.modo is not None:
        if body.modo not in ("manual", "assistido", "autonomo"):
            return JSONResponse({"error": "modo inválido"}, status_code=422)
        cfg["modo"] = body.modo
    if body.limite_mensal is not None:
        cfg["limite_mensal"] = max(0.0, body.limite_mensal)
    if body.limite_por_acao is not None:
        cfg["limite_por_acao"] = max(0.0, body.limite_por_acao)
    save_config(cfg)
    return JSONResponse({**cfg, "budget": budget_status(cfg)})


@router.post("/api/governance/mode")
async def governance_set_mode(body: ModoBody):
    try:
        cfg = set_mode(body.modo)
        return JSONResponse({"ok": True, "modo": cfg["modo"]})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)


@router.get("/api/governance/budget")
async def governance_budget():
    cfg = get_config()
    return JSONResponse(budget_status(cfg))


@router.post("/api/governance/avaliar")
async def governance_avaliar(body: AvaliarBody):
    result = avaliar_execucao(body.custo, body.lucro_estimado)
    return JSONResponse(result)


@router.post("/api/governance/registrar-gasto")
async def governance_registrar_gasto(body: GastoBody):
    cfg = registrar_gasto(body.custo)
    return JSONResponse(
        {"ok": True, "gasto_atual": cfg["gasto_atual"], "budget": budget_status(cfg)}
    )
