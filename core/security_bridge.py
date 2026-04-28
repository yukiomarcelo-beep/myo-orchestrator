"""
security_bridge.py
Caminho: core/security_bridge.py  (novo arquivo no MYO)

Ponte entre a Security Layer e os módulos existentes do MYO.
NÃO substitui audit_engine, governance nem trust_feedback_engine.
ADICIONA as 5 defesas que faltam, integradas ao fluxo existente.
"""

import json
import os

from security_layer import (
    MAX_TURNS,
    GatekeeperDecision,
    SecureOrchestrator,
)

# ══════════════════════════════════════════════════════════════════
# INSTÂNCIA GLOBAL — compartilhada por todo o MYO
# ══════════════════════════════════════════════════════════════════

_orch = SecureOrchestrator(db_url=os.getenv("DATABASE_URL"))

try:
    _orch.setup()
except Exception as e:
    print(f"[SecurityBridge] AuditLog indisponível: {e}")


# ══════════════════════════════════════════════════════════════════
# 1. INPUT GUARD — Camada 1 (01_Input)
#    Uso: master_controller.py ou orchestrator.py no recebimento do input
# ══════════════════════════════════════════════════════════════════


def guard_input(raw_input: str) -> tuple[bool, str]:
    """
    Valida input bruto antes de qualquer processamento.
    Retorna (True, "OK") ou (False, motivo_do_bloqueio).

    Integração no master_controller.py:
        from core.security_bridge import guard_input
        ok, reason = guard_input(user_input)
        if not ok:
            return {"error": reason}
    """
    gate = _orch.gatekeeper
    result = gate.validate("input", {"input": raw_input}, confidence=1.0)
    if result.decision == GatekeeperDecision.ALLOW:
        return True, "OK"
    return False, result.reason


# ══════════════════════════════════════════════════════════════════
# 2. ENGINE GUARD — Camada 3 (07_Execute_Path)
#    Uso: antes de cada engine em orchestrator.py
#    Integra com trust_feedback_engine (usa trust_score como confidence)
# ══════════════════════════════════════════════════════════════════


def guard_engine(
    session_id: str,
    agent: str,
    action: str,
    payload: dict,
    trust_score: float = 0.95,  # vem do trust_feedback_engine
) -> dict:
    """
    Gate check antes de executar qualquer engine.
    Retorna {"status": "allowed"} ou {"status": "blocked/pending", "reason": ...}

    Integração no orchestrator.py (substitui o _gate_check existente):
        from core.security_bridge import guard_engine
        result = guard_engine(session_id, "research_agent", "web_search", payload, trust_score)
        if result["status"] != "allowed":
            return result
    """
    return _orch.execute(
        session_id=session_id,
        agent=agent,
        action=action,
        payload=payload,
        confidence=trust_score,
    )


# ══════════════════════════════════════════════════════════════════
# 3. OUTPUT GUARD — Camada 5 (antes de envio externo)
#    Uso: notion_logger.py, telegram_bot.py, WhatsApp Central
# ══════════════════════════════════════════════════════════════════


def guard_output(data: dict | str, destination: str = "external") -> tuple[bool, str]:
    """
    DLP scan antes de qualquer envio externo.
    Bloqueia CPF, CNPJ, tokens JWT, API keys no output.

    Integração no notion_logger.py:
        from core.security_bridge import guard_output
        ok, reason = guard_output(resultado, destination="notion")
        if not ok:
            logger.warning(f"OUTPUT BLOQUEADO: {reason}")
            return

    Integração no telegram_bot.py:
        ok, reason = guard_output(mensagem, destination="telegram")
        if not ok:
            await bot.send_message(chat_id, f"⚠️ Envio bloqueado: {reason}")
            return
    """
    payload_str = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data)

    from security_layer import _contains_sensitive_data

    sensitive, reason = _contains_sensitive_data(payload_str)
    if sensitive:
        return False, f"DLP bloqueado no output para {destination}: {reason}"
    return True, "OK"


# ══════════════════════════════════════════════════════════════════
# 4. AUTONOMOUS AGENT GUARD — autonomous_agent.py
#    Adiciona MAX_TURNS ao loop existente
# ══════════════════════════════════════════════════════════════════


class AutonomousSessionGuard:
    """
    Wrapper para o loop do autonomous_agent.py.
    Adiciona controle de MAX_TURNS sem alterar a lógica existente.

    Uso em autonomous_agent.py:
        from core.security_bridge import AutonomousSessionGuard

        guard = AutonomousSessionGuard(session_id)
        for task in tasks:
            if not guard.next_turn():
                logger.warning("MAX_TURNS atingido — contexto resetado")
                break
            # ... executa task normalmente
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.turns = 0

    def next_turn(self) -> bool:
        """Retorna False quando MAX_TURNS é atingido."""
        self.turns += 1
        if self.turns > MAX_TURNS:
            self.turns = 1
            return False
        return True

    def reset(self):
        self.turns = 0


# ══════════════════════════════════════════════════════════════════
# 5. COST BRIDGE — integra CostTracker com observability.py
# ══════════════════════════════════════════════════════════════════


def record_cost(
    tokens_in: int,
    tokens_out: int,
    model: str = "claude-sonnet",
) -> dict:
    """
    Registra custo e retorna status do limite diário.
    Integra com observability.py para alimentar métricas.

    Retorno:
        {"status": "ok"|"warn"|"shutdown_non_critical"|"emergency_stop",
         "cost": float, "daily_total": float}

    Integração no observability.py:
        from core.security_bridge import record_cost
        cost_status = record_cost(prompt_tokens, completion_tokens, model)
        metrics.gauge("daily_cost_usd", cost_status["daily_total"])
        if cost_status["status"] == "emergency_stop":
            trigger_alert("CUSTO CRÍTICO")
    """
    cost = _orch.cost_tracker.record(tokens_in, tokens_out, model)
    status, daily_total = _orch.cost_tracker.check_limits()
    return {
        "status": status,
        "cost": cost,
        "daily_total": daily_total,
    }


# ══════════════════════════════════════════════════════════════════
# 6. SESSION LIFECYCLE — para master_controller.py
# ══════════════════════════════════════════════════════════════════


def new_session() -> str:
    """Abre sessão isolada. Chamar no início de cada pipeline run."""
    return _orch.start_session()


def close_session(session_id: str):
    """Fecha sessão. Chamar no finally de master_controller.py."""
    _orch.close_session(session_id)


def get_audit_trail(session_id: str) -> list[dict]:
    """
    Retorna trace completo da sessão para LGPD / debugging.
    Complementa (não substitui) o audit_engine.py existente.
    """
    try:
        return _orch.audit.query_session(session_id)
    except Exception:
        return []
