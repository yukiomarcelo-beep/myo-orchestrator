"""
Verification Logger — Pipeline AI
Grava um evento por claim verificada em JSONL auditável.

Saída:
    outputs/trust/verification_events.jsonl ← eventos brutos (um por linha)

Cada evento captura:
    - origin_engine, entity_id, topic, criticality
    - claim_type, numeric_claim_detected, numeric_claim_type
    - confidence_score, source_quality_score, execution_mode
    - is_critical_failure, requires_validation, validation_questions
    - sources com tipo e score
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from policies import claim_policy

TRUST_DIR = Path("outputs/trust")
EVENTS_FILE = TRUST_DIR / "verification_events.jsonl"

VALID_CONTEXTS = {"idea", "research", "mvp", "launch_ready", "scaling"}


def _normalize_context(ctx: str) -> str:
    """Valida e normaliza execution_context. Retorna 'unknown' se inválido."""
    normalized = ctx.strip().lower() if ctx else ""
    if normalized in VALID_CONTEXTS:
        return normalized
    if normalized:
        print(f"[trust_log] Aviso: execution_context inválido '{ctx}' → gravado como 'unknown'")
    return "unknown"


# =========================
# BUILDER DE EVENTO
# =========================

def _build_event(
    pack,           # EvidencePack
    result,         # VerificationResult (contexto global)
    origin_engine: str,
    entity_id: str,
    execution_context: str = "",
) -> dict:
    """Monta um evento por claim com toda a rastreabilidade necessária."""
    numeric_detected = claim_policy.has_numeric_claim(pack.claim)
    num_type = claim_policy.numeric_claim_type(pack.claim)

    # sources pode não existir em EvidencePack (depende da versão do verification_engine)
    pack_sources = getattr(pack, "sources", []) or []

    return {
        "event_id": f"verif_{uuid.uuid4().hex[:10]}",
        "timestamp": datetime.utcnow().isoformat(),
        "origin_engine": origin_engine,
        "entity_id": entity_id,
        "execution_context": _normalize_context(execution_context),

        # Classificação da claim
        "topic": pack.topic,
        "criticality": pack.criticality,
        "claim_type": pack.claim_type.value,
        "claim": pack.claim,

        # Detecção numérica
        "numeric_claim_detected": numeric_detected,
        "numeric_claim_type": num_type,

        # Scores
        "confidence_score": pack.confidence,
        "source_quality_score": result.source_quality_score,
        "source_count": result.source_count,

        # Resultado da verificação
        "execution_mode": result.execution_mode.value,
        "safe_to_execute": result.safe_to_execute,
        "verified": pack.verified,
        "requires_validation": pack.requires_validation,
        "is_critical_failure": pack.is_critical_failure,
        "validation_questions": [pack.validation_question] if pack.validation_question else [],

        # Fontes (quando disponíveis)
        "sources": [
            {
                "type": s.source_type.value if hasattr(s, "source_type") else str(s),
                "score": getattr(s, "quality_score", None),
            }
            for s in pack_sources
        ],

        # Metadados do contexto
        "total_verified_in_run": len(result.verified_claims),
        "total_unverified_in_run": len(result.unverified_claims),
        "critical_failures_in_run": len(result.critical_failures),

        # Rastreabilidade de causa: qual política específica disparou o bloqueio
        "specific_policy_triggered": pack.specific_policy_triggered,

        # Preenchido externamente (ex: autonomous_agent) quando disponível
        "fallback_used": None,
    }


# =========================
# LOGGER
# =========================

class VerificationLogger:
    """Grava eventos de verificação em JSONL auditável."""

    def __init__(self, events_file: Path = EVENTS_FILE):
        self.events_file = events_file
        self.events_file.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        result,
        origin_engine: str = "unknown",
        entity_id: str = "",
        execution_context: str = "",
    ) -> list[dict]:
        """
        Grava um evento por claim (verified + unverified) do VerificationResult.
        Retorna lista de eventos gravados.
        """
        all_packs = list(result.verified_claims) + list(result.unverified_claims)
        events = []

        with open(self.events_file, "a", encoding="utf-8") as f:
            for pack in all_packs:
                event = _build_event(
                    pack, result, origin_engine, entity_id, execution_context
                )
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
                events.append(event)

        print(
            f"[trust_log] {len(events)} evento(s) gravado(s) "
            f"| engine={origin_engine} | entity={entity_id or '—'}"
        )
        return events

    def load_events(self) -> list[dict]:
        """Carrega todos os eventos gravados."""
        if not self.events_file.exists():
            return []
        events = []
        with open(self.events_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events
