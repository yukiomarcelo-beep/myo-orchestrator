"""
Audit Engine — Pipeline AI / MYO
Analisa o decision_log.jsonl para detectar bias, inconsistências e padrões.

Checks implementados:
 1. Bias por engine → algum engine é bloqueado desproporcionalmente?
 2. Bias por tópico → algum tópico é sistematicamente favorecido?
 3. Bias por contexto → contextos mais permissivos que outros sem justificativa?
 4. Cenários extremos → claims com score = 0 ou 100 (suspeito)
 5. Tendência temporal → taxa de bloqueio aumentando ou diminuindo?
 6. Cobertura de revisão → % de decisões que requeriam humano e foram marcadas

Uso:
 python3 audit_engine.py → roda todos os checks
 python3 audit_engine.py --export → salva relatório em outputs/audit/audit_report.json
"""
import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path("outputs/audit/decision_log.jsonl")
REPORT_FILE = Path("outputs/audit/audit_report.json")

BIAS_THRESHOLD = 0.25 # diferença de 25pp entre grupos = potencial bias
EXTREME_SCORES = {0, 100}
MIN_SAMPLE_SIZE = 5 # mínimo de decisões para comparar grupos


# Carregar decisões

def load_decisions() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    decisions = []
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                decisions.append(json.loads(line.strip()))
            except Exception:
                pass
    return decisions


# Helpers

def _block_rate(decisions: list[dict]) -> float:
    if not decisions:
        return 0.0
    blocked = sum(1 for d in decisions if d["output"]["decision"] == "BLOQUEADO")
    return round(blocked / len(decisions), 3)


def _avg_confidence(decisions: list[dict]) -> float:
    if not decisions:
        return 0.0
    return round(sum(d["output"]["confidence"] for d in decisions) / len(decisions), 1)


# Checks

def check_bias_by_engine(decisions: list[dict]) -> dict:
    groups: dict[str, list] = defaultdict(list)
    for d in decisions:
        groups[d["engine"]].append(d)

    rates = {
        eng: {"block_rate": _block_rate(ds), "n": len(ds), "avg_conf": _avg_confidence(ds)}
        for eng, ds in groups.items()
        if len(ds) >= MIN_SAMPLE_SIZE
    }
    if len(rates) < 2:
        return {"status": "insuficiente", "reason": f"< {MIN_SAMPLE_SIZE} engines com dados suficientes"}

    max_rate = max(rates.values(), key=lambda x: x["block_rate"])
    min_rate = min(rates.values(), key=lambda x: x["block_rate"])
    delta = max_rate["block_rate"] - min_rate["block_rate"]

    flagged = [
        {"engine": eng, **v}
        for eng, v in rates.items()
        if v["block_rate"] > 0.5
    ]

    return {
        "status": "ATENÇÃO" if delta > BIAS_THRESHOLD else "OK",
        "delta": round(delta, 3),
        "rates": rates,
        "flagged": flagged,
        "message": f"Spread de {delta:.0%} entre engines — {'possível bias' if delta > BIAS_THRESHOLD else 'dentro do esperado'}",
    }


def check_bias_by_topic(decisions: list[dict]) -> dict:
    groups: dict[str, list] = defaultdict(list)
    for d in decisions:
        groups[d["topic"]].append(d)

    rates = {
        t: {"block_rate": _block_rate(ds), "n": len(ds), "avg_conf": _avg_confidence(ds)}
        for t, ds in groups.items()
        if len(ds) >= MIN_SAMPLE_SIZE
    }

    consistently_blocked = [
        {"topic": t, **v} for t, v in rates.items() if v["block_rate"] > 0.6
    ]
    never_blocked = [
        {"topic": t, **v} for t, v in rates.items() if v["block_rate"] == 0.0
    ]

    return {
        "status": "ATENÇÃO" if consistently_blocked else "OK",
        "rates": rates,
        "consistently_blocked": consistently_blocked,
        "never_blocked": never_blocked,
        "message": (
            f"{len(consistently_blocked)} tópico(s) bloqueados >60% do tempo"
            if consistently_blocked else "Distribuição de bloqueio por tópico normal"
        ),
    }


def check_bias_by_context(decisions: list[dict]) -> dict:
    groups: dict[str, list] = defaultdict(list)
    for d in decisions:
        groups[d["execution_context"]].append(d)

    rates = {
        ctx: {"block_rate": _block_rate(ds), "n": len(ds)}
        for ctx, ds in groups.items()
        if len(ds) >= MIN_SAMPLE_SIZE
    }

    if len(rates) < 2:
        return {"status": "insuficiente", "reason": "poucos contextos com dados"}

    max_r = max(rates.values(), key=lambda x: x["block_rate"])["block_rate"]
    min_r = min(rates.values(), key=lambda x: x["block_rate"])["block_rate"]
    delta = max_r - min_r

    return {
        "status": "ATENÇÃO" if delta > BIAS_THRESHOLD else "OK",
        "delta": round(delta, 3),
        "rates": rates,
        "message": f"Spread de {delta:.0%} entre contextos — {'revisar policy' if delta > BIAS_THRESHOLD else 'normal (contexts têm thresholds diferentes por design)'}",
    }


def check_extreme_scores(decisions: list[dict]) -> dict:
    extremes = [
        {"decision_id": d["decision_id"], "engine": d["engine"],
         "topic": d["topic"], "confidence": d["output"]["confidence"],
         "decision": d["output"]["decision"]}
        for d in decisions
        if d["output"]["confidence"] in EXTREME_SCORES
    ]
    return {
        "status": "ATENÇÃO" if len(extremes) > 3 else "OK",
        "count": len(extremes),
        "samples": extremes[:5],
        "message": f"{len(extremes)} decisão(ões) com score extremo (0 ou 100) — verificar calibração",
    }


def check_temporal_trend(decisions: list[dict]) -> dict:
    sorted_d = sorted(decisions, key=lambda x: x.get("timestamp", ""))
    if len(sorted_d) < 6:
        return {"status": "insuficiente", "reason": "< 6 decisões para análise temporal"}

    chunk = max(1, len(sorted_d) // 3)
    windows = [sorted_d[:chunk], sorted_d[chunk:2*chunk], sorted_d[2*chunk:]]
    rates = [_block_rate(w) for w in windows]

    delta = rates[-1] - rates[0]
    direction = "piorando" if delta > 0.08 else "melhorando" if delta < -0.08 else "estável"

    return {
        "status": "ATENÇÃO" if direction == "piorando" else "OK",
        "windows": [round(r, 3) for r in rates],
        "direction": direction,
        "delta": round(delta, 3),
        "message": f"Taxa de bloqueio: {rates[0]:.0%} → {rates[-1]:.0%} ({direction})",
    }


def check_human_review_coverage(decisions: list[dict]) -> dict:
    required = [d for d in decisions if d.get("human_review_required")]
    pct = round(len(required) / len(decisions), 3) if decisions else 0.0
    return {
        "status": "INFO",
        "required": len(required),
        "total": len(decisions),
        "pct": pct,
        "message": f"{len(required)} de {len(decisions)} decisões ({pct:.0%}) requerem revisão humana",
        "note": "Garantir que estas decisões foram revisadas antes de uso em produção",
    }


# Relatório completo

def run_audit(export: bool = False) -> dict:
    decisions = load_decisions()

    if not decisions:
        print(" decision_log.jsonl não encontrado ou vazio.")
        print(" Rode: python3 decision_logger.py primeiro.")
        return {}

    total = len(decisions)
    print(f"\n Auditoria — {total} decisões")
    print(f" {''*55}")

    checks = {
        "bias_by_engine": check_bias_by_engine(decisions),
        "bias_by_topic": check_bias_by_topic(decisions),
        "bias_by_context": check_bias_by_context(decisions),
        "extreme_scores": check_extreme_scores(decisions),
        "temporal_trend": check_temporal_trend(decisions),
        "human_review": check_human_review_coverage(decisions),
    }

    STATUS_ICON = {"OK": "", "ATENÇÃO": "", "INFO": "ℹ", "insuficiente": ""}
    n_warnings = 0

    for check_name, result in checks.items():
        icon = STATUS_ICON.get(result.get("status", ""), "•")
        msg = result.get("message", "—")
        print(f" {icon} {check_name:<25} {msg}")
        if result.get("status") == "ATENÇÃO":
            n_warnings += 1

    print(f"\n {''*55}")
    print(f" Resultado: {n_warnings} aviso(s) de atenção")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_decisions": total,
        "n_warnings": n_warnings,
        "checks": checks,
    }

    if export:
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n Relatório salvo: {REPORT_FILE}")

    return report


# Main

def main():
    parser = argparse.ArgumentParser(description="Audit Engine — MYO Compliance")
    parser.add_argument("--export", action="store_true", help="Salva relatório JSON")
    args = parser.parse_args()
    run_audit(export=args.export)


if __name__ == "__main__":
    main()
