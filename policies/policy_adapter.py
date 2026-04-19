"""
Policy Adapter — Pipeline AI (6C: Context-Aware Policy)
Lê evidências reais e ajusta context_policy.json automaticamente.

Fontes de evidência:
    1. outputs/trust/verification_events.jsonl → falha real por tópico × contexto
    2. outputs/execution_tasks/*.json → experimentos de policy_rigidity

Regras de ajuste (com guardrails):
    ENDURECER   → topic failure_rate > TIGHTEN_RATE em contexto (+ MIN_EVENTS)
    RELAXAR     → policy_rigidity experiments success_rate > RELAX_RATE em contexto
    api_strict  → api_cost failure_rate > API_STRICT_RATE → liga strict

Guardrails absolutos:
    threshold mínimo: 40 (nunca deixar totalmente livre)
    threshold máximo: 90 (nunca bloquear tudo)
    step máximo por run: ±5 (mudança suave, não abrupta)

Proteção contra overfitting:
    MIN_EVENTS_TOPIC = 10 (por tópico × contexto)
    MIN_EXPERIMENTS  = 5  (policy_rigidity experiments por contexto)
    MIN_EVENTS_GATE  = 15 (total de eventos no contexto para relaxar gate)

Versionamento:
    config/history/context_policy_YYYY-MM-DD_HHMMSS.json ← snapshot antes de cada mudança

Uso:
    python3 policy_adapter.py            → roda ajuste e salva policy
    python3 policy_adapter.py --dry-run  → mostra o que mudaria sem salvar
    python3 policy_adapter.py --report   → só mostra evidências sem ajustar
"""
import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

POLICY_FILE = Path("config/context_policy.json")
EVENTS_FILE = Path("outputs/trust/verification_events.jsonl")
TASKS_DIR = Path("outputs/execution_tasks")

# Parâmetros de ajuste
TIGHTEN_RATE = 0.60      # failure_rate > 60% no tópico → endurecer +5
RELAX_RATE = 0.60        # experiment_success_rate > 60% → relaxar -5
API_STRICT_RATE = 0.50   # api_cost failure_rate > 50% → ligar strict
STEP = 5                 # pontos por ajuste

THRESHOLD_MIN = 40       # drift floor: nunca abaixo disso
THRESHOLD_MAX = 90       # drift ceiling: nunca acima disso

MIN_EVENTS_TOPIC = 10    # mínimo por tópico×contexto para ajustar threshold
MIN_EXPERIMENTS = 5      # mínimo de experimentos por contexto para relaxar gate
MIN_EVENTS_GATE = 15     # mínimo de eventos totais no contexto para relaxar gate global

VALID_CONTEXTS = {"idea", "research", "mvp", "launch_ready", "scaling"}


# =========================
# Leitura da policy
# =========================

def load_policy() -> dict:
    if not POLICY_FILE.exists():
        raise FileNotFoundError(f"Policy não encontrada: {POLICY_FILE}")
    with open(POLICY_FILE, encoding="utf-8") as f:
        return json.load(f)


def _snapshot_policy(policy: dict) -> Optional[Path]:
    """Salva snapshot do estado ATUAL (antes das mudanças) em config/history/."""
    try:
        history_dir = POLICY_FILE.parent / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        snapshot_path = history_dir / f"context_policy_{ts}.json"
        with open(snapshot_path, "w", encoding="utf-8") as f:
            json.dump(policy, f, ensure_ascii=False, indent=2)
        return snapshot_path
    except Exception as e:
        print(f" Snapshot falhou (não crítico): {e}")
        return None


def save_policy(policy: dict, changes: list[str]):
    # Snapshot antes de qualquer mudança (rollback possível)
    snapshot_path = _snapshot_policy(policy)
    if snapshot_path:
        print(f" Snapshot: {snapshot_path.name}")

    meta = policy.setdefault("_meta", {})
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    meta["version"] = meta.get("version", 1) + 1
    history = meta.setdefault("adjustment_history", [])
    history.append({
        "timestamp": meta["updated_at"],
        "changes": changes,
        "snapshot_file": snapshot_path.name if snapshot_path else None,
    })
    # Manter histórico últimos 50 runs
    if len(history) > 50:
        meta["adjustment_history"] = history[-50:]

    POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(POLICY_FILE, "w", encoding="utf-8") as f:
        json.dump(policy, f, ensure_ascii=False, indent=2)
    print(f" Policy salva: {POLICY_FILE} (v{meta['version']})")


# =========================
# Evidência 1: falha por tópico × contexto (eventos)
# =========================

def compute_topic_failure_by_context() -> dict[str, dict[str, dict]]:
    """
    Lê verification_events.jsonl.
    Retorna: {context: {topic: {total, failures, failure_rate}}}
    """
    if not EVENTS_FILE.exists():
        return {}

    totals: dict[tuple, int] = defaultdict(int)
    failures: dict[tuple, int] = defaultdict(int)

    with open(EVENTS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            ctx = ev.get("execution_context", "unknown")
            topic = ev.get("topic", "general")
            key = (ctx, topic)
            totals[key] += 1
            if ev.get("is_critical_failure"):
                failures[key] += 1

    # Organizar por contexto
    result: dict[str, dict[str, dict]] = defaultdict(dict)
    for (ctx, topic), n in totals.items():
        f_count = failures[(ctx, topic)]
        result[ctx][topic] = {
            "total": n,
            "failures": f_count,
            "failure_rate": round(f_count / n, 3),
        }
    return dict(result)


# =========================
# Evidência 2: experimentos de policy_rigidity
# =========================

def compute_experiment_success_by_context() -> dict[str, dict]:
    """
    Lê execution tasks com original_failure_type=policy_rigidity.
    Retorna: {context: {total, successes, success_rate}}
    """
    if not TASKS_DIR.exists():
        return {}

    totals: dict[str, int] = defaultdict(int)
    successes: dict[str, int] = defaultdict(int)

    for path in TASKS_DIR.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                task = json.load(f)
        except Exception:
            continue

        if task.get("original_failure_type") != "policy_rigidity":
            continue
        if task.get("experiment_result") is None:
            continue  # experimento não concluído

        ctx = task.get("experiment_context", "research")
        totals[ctx] += 1
        if task.get("experiment_result") == "success":
            successes[ctx] += 1

    result = {}
    for ctx, n in totals.items():
        s = successes[ctx]
        result[ctx] = {
            "total": n,
            "successes": s,
            "success_rate": round(s / n, 3) if n > 0 else 0.0,
        }
    return result


# =========================
# Aplicar ajustes
# =========================

def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def apply_adjustments(
    policy: dict,
    topic_failures: dict[str, dict[str, dict]],
    exp_success: dict[str, dict],
    dry_run: bool = False,
) -> list[str]:
    """Aplica ajustes na policy em memória. Retorna lista de changes realizadas."""
    changes: list[str] = []

    for ctx in VALID_CONTEXTS:
        ctx_policy = policy.get(ctx)
        if not ctx_policy:
            continue

        ctx_topic_data = topic_failures.get(ctx, {})
        exp_data = exp_success.get(ctx, {})

        # Regra 1: endurecer tópico com alta falha
        for topic, stats in ctx_topic_data.items():
            if stats["total"] < MIN_EVENTS_TOPIC:
                continue  # evidência insuficiente

            rate = stats["failure_rate"]
            topic_thresholds = ctx_policy.setdefault("topic_thresholds", {})
            current = topic_thresholds.get(topic)

            if current is None:
                continue  # tópico não configurado para este contexto

            if rate > TIGHTEN_RATE:
                new_val = int(_clamp(current + STEP, THRESHOLD_MIN, THRESHOLD_MAX))
                if new_val != current:
                    msg = (
                        f"TIGHTEN ctx={ctx} topic={topic}: "
                        f"{current}→{new_val} (failure_rate={rate:.0%}, n={stats['total']})"
                    )
                    changes.append(msg)
                    if not dry_run:
                        topic_thresholds[topic] = new_val

            elif rate < (TIGHTEN_RATE - 0.30) and stats["total"] >= MIN_EVENTS_TOPIC * 2:
                # Falha bem baixa com volume alto → suavizar threshold
                new_val = int(_clamp(current - (STEP - 2), THRESHOLD_MIN, THRESHOLD_MAX))
                if new_val != current:
                    msg = (
                        f"SOFTEN ctx={ctx} topic={topic}: "
                        f"{current}→{new_val} (failure_rate={rate:.0%}, n={stats['total']})"
                    )
                    changes.append(msg)
                    if not dry_run:
                        topic_thresholds[topic] = new_val

        # Regra 2: relaxar gate global se experiments policy_rigidity têm sucesso
        ctx_total_events = sum(s["total"] for s in ctx_topic_data.values())
        if (
            exp_data.get("total", 0) >= MIN_EXPERIMENTS
            and ctx_total_events >= MIN_EVENTS_GATE
        ):
            sr = exp_data["success_rate"]
            if sr > RELAX_RATE:
                for gate_key in ("gate_confidence_normal", "gate_confidence_experiment"):
                    current = ctx_policy.get(gate_key)
                    if current is None:
                        continue
                    new_val = int(_clamp(current - STEP, THRESHOLD_MIN, THRESHOLD_MAX))
                    if new_val != current:
                        msg = (
                            f"RELAX ctx={ctx} gate={gate_key}: "
                            f"{current}→{new_val} "
                            f"(policy_rigidity success_rate={sr:.0%}, n={exp_data['total']})"
                        )
                        changes.append(msg)
                        if not dry_run:
                            ctx_policy[gate_key] = new_val

        # Regra 3: ligar api_cost strict se falha muito
        api_stats = ctx_topic_data.get("api_cost", {})
        if (
            api_stats.get("total", 0) >= MIN_EVENTS_TOPIC
            and api_stats.get("failure_rate", 0) > API_STRICT_RATE
        ):
            if not ctx_policy.get("api_cost_strict"):
                changes.append(
                    f"STRICT ctx={ctx} api_cost_strict: false→true "
                    f"(failure_rate={api_stats['failure_rate']:.0%})"
                )
                if not dry_run:
                    ctx_policy["api_cost_strict"] = True

    return changes


# =========================
# Relatório de evidências
# =========================

def print_evidence(topic_failures: dict, exp_success: dict):
    print("\n Evidência 1: falha por tópico × contexto ")
    if not topic_failures:
        print("  (sem dados — rode result_ingestor.py primeiro)")
    else:
        for ctx in sorted(topic_failures):
            for topic, stats in sorted(
                topic_failures[ctx].items(),
                key=lambda x: x[1]["failure_rate"],
                reverse=True,
            ):
                flag = (
                    " ← TIGHTEN"
                    if stats["failure_rate"] > TIGHTEN_RATE
                    and stats["total"] >= MIN_EVENTS_TOPIC
                    else ""
                )
                print(
                    f"  [{ctx:<12}] {topic:<14} "
                    f"fail={stats['failure_rate']:.0%} n={stats['total']}{flag}"
                )

    print("\n Evidência 2: experimentos policy_rigidity ")
    if not exp_success:
        print("  (sem experimentos concluídos)")
    else:
        for ctx, stats in sorted(exp_success.items()):
            flag = (
                " ← RELAX"
                if stats["success_rate"] > RELAX_RATE
                and stats["total"] >= MIN_EXPERIMENTS
                else ""
            )
            print(
                f"  [{ctx:<12}] success={stats['success_rate']:.0%} n={stats['total']}{flag}"
            )


# =========================
# Main
# =========================

def main():
    parser = argparse.ArgumentParser(description="Policy Adapter — 6C Context-Aware Policy")
    parser.add_argument("--dry-run", action="store_true", help="Mostra mudanças sem salvar")
    parser.add_argument("--report", action="store_true", help="Só mostra evidências, não ajusta")
    parser.add_argument(
        "--rollback",
        metavar="SNAPSHOT",
        help="Restaura policy de um snapshot (ex: context_policy_2026-03-26_143000.json)",
    )
    args = parser.parse_args()

    # Rollback
    if args.rollback:
        snapshot_path = POLICY_FILE.parent / "history" / args.rollback
        if not snapshot_path.exists():
            print(f" Snapshot não encontrado: {snapshot_path}")
            history_dir = POLICY_FILE.parent / "history"
            if history_dir.exists():
                snaps = sorted(history_dir.glob("context_policy_*.json"), reverse=True)
                if snaps:
                    print(f"\n Snapshots disponíveis:")
                    for s in snaps[:10]:
                        print(f"  {s.name}")
            return

        # Salva snapshot do estado atual antes do rollback
        current = load_policy()
        _snapshot_policy(current)
        with open(snapshot_path, encoding="utf-8") as f:
            restored = json.load(f)
        with open(POLICY_FILE, "w", encoding="utf-8") as f:
            json.dump(restored, f, ensure_ascii=False, indent=2)
        print(f" Rollback concluído: policy restaurada de {args.rollback}")
        return

    print("\n Coletando evidências...")
    topic_failures = compute_topic_failure_by_context()
    exp_success = compute_experiment_success_by_context()

    print_evidence(topic_failures, exp_success)

    if args.report:
        return

    print("\n Calculando ajustes...")
    policy = load_policy()
    changes = apply_adjustments(policy, topic_failures, exp_success, dry_run=args.dry_run)

    if not changes:
        print(" Nenhum ajuste necessário — evidência insuficiente ou policy já adequada.")
        return

    print(f"\n {'[DRY RUN] ' if args.dry_run else ''}Ajustes ({len(changes)}):")
    for c in changes:
        print(f"  {c}")

    if not args.dry_run:
        save_policy(policy, changes)
        # Notificar via Telegram
        try:
            from telegram_bot import send_policy_change
            send_policy_change(changes)
        except Exception:
            pass  # Telegram opcional
    else:
        print("\n (dry-run: nada foi salvo)")


if __name__ == "__main__":
    main()
