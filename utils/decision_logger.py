"""
Decision Logger — Pipeline AI / MYO
Transforma verification_events em log formal de decisões auditáveis.

Estrutura de cada entrada:
 decision_id, timestamp, engine, entity_id, topic, criticality
 input: {claim, claim_type, numeric, numeric_type}
 output: {decision, confidence, source_quality, safe_to_execute}
 rule_applied: {policy_context, threshold_used, triggered_by}
 human_review_required, human_review_reason
 audit_flags: {is_critical_topic, is_numeric, is_volatile}

Uso:
 python3 decision_logger.py → processa novos eventos e gera decision_log.jsonl
 python3 decision_logger.py --rebuild → reconstrói log do zero
 python3 decision_logger.py --summary → mostra resumo do log atual
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from policies.claim_policy import is_critical, is_volatile, has_numeric_claim

EVENTS_FILE = Path("outputs/trust/verification_events.jsonl")
LOG_FILE = Path("outputs/audit/decision_log.jsonl")
POLICY_FILE = Path("config/context_policy.json")

# Mapeamento execution_mode → decisão legível
MODE_TO_DECISION = {
    "normal": "APROVADO",
    "experiment": "EXPERIMENTO",
    "validation_required": "BLOQUEADO",
}

# Razões de bloqueio/experimento derivadas dos dados
def _infer_trigger(ev: dict) -> str:
    conf = ev.get("confidence_score", 100)
    sq = ev.get("source_quality_score", 10)
    crit = ev.get("criticality", "low")
    mode = ev.get("execution_mode", "normal")

    if mode == "validation_required":
        if crit == "critical" and conf < 70:
            return "critical_claim_low_confidence"
        if sq < 5:
            return "insufficient_source_quality"
        return "policy_threshold_exceeded"
    if mode == "experiment":
        if conf < 60:
            return "low_confidence_experiment_mode"
        return "moderate_claim_below_threshold"
    return "approved_within_policy"


def _load_policy_threshold(topic: str, context: str) -> int:
    """Lê o threshold usado para decisão (retroativo)."""
    try:
        from policies.claim_policy import confidence_threshold_for_context
        return confidence_threshold_for_context(topic, context)
    except Exception:
        return 70


def _event_to_decision(ev: dict) -> dict:
    """Converte um verification_event em entrada de decision_log."""
    topic = ev.get("topic", "general")
    context = ev.get("execution_context", "")
    mode = ev.get("execution_mode", "normal")
    conf = ev.get("confidence_score", 0)
    sq = ev.get("source_quality_score", 0)
    claim = ev.get("claim", "")
    thresh = _load_policy_threshold(topic, context)

    return {
        "decision_id": f"dec_{ev.get('event_id', '')[-8:]}",
        "event_id": ev.get("event_id", ""),
        "timestamp": ev.get("timestamp", ""),
        "system": "MYO Pipeline AI",
        "engine": ev.get("origin_engine", "unknown"),
        "entity_id": ev.get("entity_id", ""),
        "topic": topic,
        "criticality": ev.get("criticality", "low"),
        "execution_context": context or "unknown",

        "input": {
            "claim": claim[:200],
            "claim_type": ev.get("claim_type", "unknown"),
            "numeric": ev.get("numeric_claim_detected", False),
            "numeric_type": ev.get("numeric_claim_type"),
            "source_count": ev.get("source_count", 0),
        },

        "output": {
            "decision": MODE_TO_DECISION.get(mode, mode.upper()),
            "confidence": conf,
            "source_quality": sq,
            "safe_to_execute": ev.get("safe_to_execute", True),
            "verified": ev.get("verified", False),
        },

        "rule_applied": {
            "policy_context": context or "default",
            "threshold_used": thresh,
            "delta_confidence": round(conf - thresh, 1),
            "triggered_by": _infer_trigger(ev),
        },

        "human_review_required": mode == "validation_required",
        "human_review_reason": (
            "Claim crítica com confiança abaixo do threshold" if mode == "validation_required" else None
        ),

        "audit_flags": {
            "is_critical_topic": is_critical(topic),
            "is_volatile_topic": is_volatile(topic),
            "is_numeric_claim": ev.get("numeric_claim_detected", False),
            "is_critical_failure": ev.get("is_critical_failure", False),
        },
    }


# Processar eventos

def _load_existing_event_ids() -> set:
    if not LOG_FILE.exists():
        return set()
    ids = set()
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line.strip())
                ids.add(d.get("event_id", ""))
            except Exception:
                pass
    return ids


def process(rebuild: bool = False):
    if not EVENTS_FILE.exists():
        print(" verification_events.jsonl não encontrado.")
        return 0

    existing_ids = set() if rebuild else _load_existing_event_ids()
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    mode = "w" if rebuild else "a"
    new_count = 0

    with open(EVENTS_FILE, encoding="utf-8") as ef, \
         open(LOG_FILE, mode, encoding="utf-8") as lf:
        for line in ef:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            eid = ev.get("event_id", "")
            if eid in existing_ids:
                continue
            decision = _event_to_decision(ev)
            lf.write(json.dumps(decision, ensure_ascii=False) + "\n")
            existing_ids.add(eid)
            new_count += 1

    return new_count


# Resumo do log

def summary():
    if not LOG_FILE.exists():
        print(" Log não encontrado. Rode sem --summary primeiro.")
        return

    decisions = []
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                decisions.append(json.loads(line.strip()))
            except Exception:
                pass

    if not decisions:
        print(" Log vazio.")
        return

    total = len(decisions)
    by_decision: dict[str, int] = {}
    by_engine: dict[str, int] = {}
    human_req = 0
    critical_blocked = 0

    for d in decisions:
        dec = d["output"]["decision"]
        eng = d["engine"]
        by_decision[dec] = by_decision.get(dec, 0) + 1
        by_engine[eng] = by_engine.get(eng, 0) + 1
        if d.get("human_review_required"):
            human_req += 1
        if d["audit_flags"].get("is_critical_failure"):
            critical_blocked += 1

    print(f"\n {''*55}")
    print(f" Decision Log — {total} decisões registradas")
    print(f" {''*55}")
    print(f" Por decisão:")
    for dec, n in sorted(by_decision.items(), key=lambda x: -x[1]):
        pct = n / total
        bar = "" * round(pct * 20)
        print(f" {dec:<20} {bar:<20} {n:>4} ({pct:.0%})")
    print(f"\n Por engine (top 5):")
    for eng, n in sorted(by_engine.items(), key=lambda x: -x[1])[:5]:
        print(f" {eng:<30} {n}")
    print(f"\n Revisão humana necessária : {human_req}")
    print(f" Falhas críticas bloqueadas: {critical_blocked}")
    print(f"\n Log: {LOG_FILE}")


# Main

def main():
    parser = argparse.ArgumentParser(description="Decision Logger — MYO Audit")
    parser.add_argument("--rebuild", action="store_true", help="Reconstrói log do zero")
    parser.add_argument("--summary", action="store_true", help="Mostra resumo do log")
    args = parser.parse_args()

    if args.summary:
        summary()
        return

    print(f"\n Processando decision log{' [REBUILD]' if args.rebuild else ''}...")
    n = process(rebuild=args.rebuild)
    print(f" {n} nova(s) decisão(ões) registrada(s) → {LOG_FILE}")

    if n > 0:
        summary()


if __name__ == "__main__":
    main()
