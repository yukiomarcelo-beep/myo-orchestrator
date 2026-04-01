#!/usr/bin/env python3
"""
Governance — Controle de autonomia e limites financeiros.

Regras:
    Baixo impacto  -> executa automaticamente
    Médio impacto  -> executa + alerta
    Alto impacto   -> aguarda aprovação humana

    Limite mensal  -> bloqueia se gasto_atual + custo > limite_mensal
    Limite por ação -> eleva impacto para alto se custo > limite_por_acao
    Modo manual    -> tudo aguarda aprovação
    Modo autônomo  -> alto impacto ainda requer aprovação
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).parent
GOVERNANCE_FILE = BASE_DIR / "outputs" / "governance_config.json"
_gov_lock = threading.Lock()

_DEFAULT_CONFIG: Dict[str, Any] = {
    "modo": "assistido",          # manual | assistido | autonomo
    "limite_mensal": 3000.0,      # R$
    "limite_por_acao": 1000.0,    # R$ — acima disso impacto vira "alto"
    "gasto_atual": 0.0,           # acumulado no mês (atualizado automaticamente)
    "mes_referencia": "",         # YYYY-MM para reset automático
}


# Config I/O

def get_config() -> Dict[str, Any]:
    """Retorna config atual, criando o arquivo com defaults se necessário."""
    if GOVERNANCE_FILE.exists():
        try:
            data = json.loads(GOVERNANCE_FILE.read_text(encoding="utf-8"))
            # reset mensal automático
            mes_atual = datetime.now(timezone.utc).strftime("%Y-%m")
            if data.get("mes_referencia") != mes_atual:
                data["gasto_atual"] = 0.0
                data["mes_referencia"] = mes_atual
                save_config(data)
            return {**_DEFAULT_CONFIG, **data}
        except Exception:
            pass
    cfg = {**_DEFAULT_CONFIG, "mes_referencia": datetime.now(timezone.utc).strftime("%Y-%m")}
    save_config(cfg)
    return cfg


def save_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Persiste config em disco."""
    with _gov_lock:
        GOVERNANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        GOVERNANCE_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return cfg


def set_mode(modo: str) -> Dict[str, Any]:
    """Muda o modo de autonomia: manual | assistido | autonomo."""
    if modo not in ("manual", "assistido", "autonomo"):
        raise ValueError(f"Modo inválido: {modo}")
    cfg = get_config()
    cfg["modo"] = modo
    return save_config(cfg)


def update_limits(limite_mensal: float = None, limite_por_acao: float = None) -> Dict[str, Any]:
    """Atualiza limites financeiros."""
    cfg = get_config()
    if limite_mensal is not None:
        cfg["limite_mensal"] = max(0.0, float(limite_mensal))
    if limite_por_acao is not None:
        cfg["limite_por_acao"] = max(0.0, float(limite_por_acao))
    return save_config(cfg)


def registrar_gasto(custo: float) -> Dict[str, Any]:
    """Acumula custo aprovado no orçamento mensal."""
    cfg = get_config()
    cfg["gasto_atual"] = round(cfg.get("gasto_atual", 0.0) + max(0.0, custo), 2)
    return save_config(cfg)


# Lógica central

def avaliar_execucao(custo: float, lucro_estimado: float = 0.0,
                     cfg: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Avalia se uma ação pode ser executada.

    Returns dict com:
        decisao: executar | executar_com_alerta | aguardar_aprovacao | bloqueado_orcamento
        impacto: baixo | medio | alto
        motivo:  string explicando a decisão
        roi_pct: float
    """
    if cfg is None:
        cfg = get_config()

    modo = cfg.get("modo", "assistido")
    limite_mensal = float(cfg.get("limite_mensal", 3000))
    limite_por_acao = float(cfg.get("limite_por_acao", 1000))
    gasto_atual = float(cfg.get("gasto_atual", 0))

    roi = lucro_estimado - custo
    roi_pct = round((roi / custo * 100) if custo > 0 else 0, 1)

    # 1 — Teto mensal
    if gasto_atual + custo > limite_mensal:
        return {
            "decisao": "bloqueado_orcamento",
            "impacto": "alto",
            "motivo": (f"Orçamento mensal esgotado: "
                       f"R${gasto_atual:.0f} + R${custo:.0f} > R${limite_mensal:.0f}"),
            "roi_pct": roi_pct,
            "custo": round(custo, 2),
            "lucro_estimado": round(lucro_estimado, 2),
        }

    # 2 — Classificar impacto
    if custo > limite_por_acao:
        impacto = "alto"
    elif custo > 200:
        impacto = "medio"
    else:
        impacto = "baixo"

    # 3 — Modo manual — tudo aguarda
    if modo == "manual":
        return {
            "decisao": "aguardar_aprovacao",
            "impacto": impacto,
            "motivo": "Modo manual: toda ação requer aprovação humana",
            "roi_pct": roi_pct,
            "custo": round(custo, 2),
            "lucro_estimado": round(lucro_estimado, 2),
        }

    # 4 — Modo assistido
    if modo == "assistido":
        if impacto == "alto":
            return {
                "decisao": "aguardar_aprovacao",
                "impacto": "alto",
                "motivo": f"Alto impacto (R${custo:.0f} > limite R${limite_por_acao:.0f})",
                "roi_pct": roi_pct,
                "custo": round(custo, 2),
                "lucro_estimado": round(lucro_estimado, 2),
            }
        if impacto == "medio":
            return {
                "decisao": "executar_com_alerta",
                "impacto": "medio",
                "motivo": f"Impacto médio — executado com notificação (R${custo:.0f})",
                "roi_pct": roi_pct,
                "custo": round(custo, 2),
                "lucro_estimado": round(lucro_estimado, 2),
            }
        return {
            "decisao": "executar",
            "impacto": "baixo",
            "motivo": f"Baixo impacto (R${custo:.0f}) — executado automaticamente",
            "roi_pct": roi_pct,
            "custo": round(custo, 2),
            "lucro_estimado": round(lucro_estimado, 2),
        }

    # 5 — Modo autônomo — só bloqueia alto
    if impacto == "alto":
        return {
            "decisao": "aguardar_aprovacao",
            "impacto": "alto",
            "motivo": f"Alto impacto mesmo em modo autônomo (R${custo:.0f})",
            "roi_pct": roi_pct,
            "custo": round(custo, 2),
            "lucro_estimado": round(lucro_estimado, 2),
        }
    return {
        "decisao": "executar",
        "impacto": impacto,
        "motivo": f"Modo autônomo — executado (R${custo:.0f})",
        "roi_pct": roi_pct,
        "custo": round(custo, 2),
        "lucro_estimado": round(lucro_estimado, 2),
    }


def budget_status(cfg: Dict[str, Any] = None) -> Dict[str, Any]:
    """Retorna status do orçamento mensal."""
    if cfg is None:
        cfg = get_config()
    limite = float(cfg.get("limite_mensal", 3000))
    gasto = float(cfg.get("gasto_atual", 0))
    pct = round((gasto / limite * 100) if limite > 0 else 0, 1)
    restante = max(0.0, limite - gasto)
    return {
        "gasto": round(gasto, 2),
        "limite": round(limite, 2),
        "restante": round(restante, 2),
        "pct_usado": pct,
        "status": "critico" if pct >= 90 else "aviso" if pct >= 70 else "ok",
    }
