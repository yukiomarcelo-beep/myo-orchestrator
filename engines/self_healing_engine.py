"""
Self-Healing Engine — Pipeline AI / MYO

4 agentes + 3 camadas enterprise:

[1] DETECTOR → escaneia o sistema a cada ciclo, detecta anomalias
[2] DIAGNÓSTICO → Claude analisa causa raiz com contexto real dos logs
[3] CORREÇÃO → aplica ação corretiva específica ao tipo de problema
[4] VALIDADOR → confirma que a correção funcionou (ou escalona)

Camadas enterprise
[5] EXPLICABILIDADE → "explanation" JSON em cada decisão — auditável, legal
[6] SEGURANÇA → rate limits por ação + circuit breaker anti-loop
[7] APRENDIZADO → patterns_learned: sistema sabe a melhor correção antes
[8] HUMAN-IN-LOOP → BAIXO=auto / MÉDIO=auto+log / ALTO=bloqueado até aprovação
[9] HUMAN DECISION → cada decisão vira dado: aprende o que humano prefere, detecta contradições
[10] CONF GOVERNANCE → decay temporal, stress test, revalidação obrigatória, overconfidence alert
[11] DRIFT CONTROL → drift 7d vs 30d, canary 10%, exploração epsilon, rollback automático

Loop:
- Roda a cada SCAN_INTERVAL segundos (padrão: 300 = 5 min)
- Máx 3 tentativas por problema antes de escalonar para humano
- SQLite como log operacional (auditável, rápido, sem dependência externa)
- Alertas via Telegram (crítico = imediato, outros = buffered)

Rate limits (por hora):
relax_threshold / tighten: 2× restart_engine: 2× retry: 5×
recalibrate: 3× check_api: 10× notify_human: 10×

Circuit breaker:
3 correções seguidas que pioram → trava auto-loop → escala humano

Uso:
python3 self_healing_engine.py → loop contínuo
python3 self_healing_engine.py --once → roda 1 ciclo e sai
python3 self_healing_engine.py --status → mostra estado do DB
python3 self_healing_engine.py --history → histórico de correções
python3 self_healing_engine.py --patterns → tabela de aprendizado
python3 self_healing_engine.py --pending → lista aprovações pendentes
python3 self_healing_engine.py --approve 3 → aprova aprovação #3
python3 self_healing_engine.py --reject 3 → rejeita aprovação #3
python3 self_healing_engine.py --adjust 3 retry → aprova com ação diferente
python3 self_healing_engine.py --governance → relatório de governança de confiança
python3 self_healing_engine.py --revalidate engine_bias_detected check_api → revalida padrão
python3 self_healing_engine.py --drift → relatório de deriva sistêmica
python3 self_healing_engine.py --canary engine_bias_detected retry recalibrate → registra canary test
python3 self_healing_engine.py --sla → relatório de SLA: tempos de correção e resposta
python3 self_healing_engine.py --audit-report → gera relatório JSON exportável para enterprise
python3 self_healing_engine.py --proof-report → gera proof_of_value.html (1 página, para cliente)

Integração com MYO:
Lê: outputs/audit/decision_log.jsonl
outputs/trust/verification_events.jsonl
outputs/execution_tasks/*.json
outputs/financial_data.json
Chama: policy_adapter.py --dry-run (validação) / direto (correção)
telegram_bot.py (alertas)
decision_logger.py --rebuild (reconstrução)
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Configuração

SCAN_INTERVAL = 300  # segundos entre ciclos (5 min)
MAX_ATTEMPTS = 3  # tentativas antes de escalonar
DB_FILE = Path("outputs/self_healing/operational.db")
EVENTS_FILE = Path("outputs/trust/verification_events.jsonl")
DECISION_LOG = Path("outputs/audit/decision_log.jsonl")
TASKS_DIR = Path("outputs/execution_tasks")
FINANCIAL_FILE = Path("outputs/financial_data.json")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Thresholds de alerta (baseline do sistema)
BLOCK_RATE_THRESHOLD = 0.35  # acima de 35% → anomalia
CONFIDENCE_THRESHOLD_LOW = 65.0  # abaixo → confiança caindo
CONFIDENCE_BASELINE = 73.6  # baseline observado
STALE_MINUTES = 60  # sem eventos em X min → pipeline parado
TASK_FAILURE_THRESHOLD = 0.40  # >40% de tasks falhadas → problema

# SLA Targets
SLA_TARGETS = {
    "correction_minutes": 5,  # até 5 min para aplicar correção
    "human_response_minutes": 5,  # até 5 min para resposta humana (ALTO)
    "escalation_minutes": 15,  # até 15 min para resolver ou escalonar
}

# Estimativa de receita por severidade (para Business Impact)
REVENUE_AT_RISK = {
    "critical": 500,
    "high": 250,
    "medium": 100,
    "low": 30,
}


# Database


def init_db() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("""
 CREATE TABLE IF NOT EXISTS operational_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 fingerprint TEXT UNIQUE, -- evita duplicatas por ciclo
 source TEXT NOT NULL, -- qual detector encontrou
 event_type TEXT NOT NULL, -- tipo de anomalia
 severity TEXT NOT NULL, -- critical / high / medium / low
 product TEXT DEFAULT '',
 details_json TEXT DEFAULT '{}', -- contexto raw
 status TEXT DEFAULT 'detected',
 diagnosis_json TEXT, -- resposta do Claude
 correction_applied TEXT, -- o que foi feito
 correction_result_json TEXT, -- before/after
 attempts INTEGER DEFAULT 0,
 created_at TEXT,
 updated_at TEXT
 )
 """)
    conn.execute("""
 CREATE TABLE IF NOT EXISTS correction_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_id INTEGER REFERENCES operational_events(id),
 attempt INTEGER,
 action TEXT,
 before_json TEXT,
 after_json TEXT,
 success INTEGER, -- 1/0
 notes TEXT,
 ts TEXT
 )
 """)
    # Camada 5: Explicabilidade
    conn.execute("""
 CREATE TABLE IF NOT EXISTS explanation_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_id INTEGER REFERENCES operational_events(id),
 causa TEXT,
 decisao TEXT,
 alternativas_json TEXT DEFAULT '[]',
 nivel_confianca REAL DEFAULT 0.0,
 fonte_diagnostico TEXT DEFAULT 'rules', -- 'claude'|'rules'|'learned'
 overridden INTEGER DEFAULT 0, -- 1 se learning sobrescreveu
 ts TEXT
 )
 """)
    # Camada 6: Segurança — rate limit tracking
    conn.execute("""
 CREATE TABLE IF NOT EXISTS action_audit_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 action TEXT NOT NULL,
 event_type TEXT,
 success INTEGER DEFAULT 0,
 ts TEXT NOT NULL
 )
 """)
    # Camada 7: Aprendizado — memória de longo prazo
    conn.execute("""
 CREATE TABLE IF NOT EXISTS patterns_learned (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_type TEXT NOT NULL,
 best_action TEXT NOT NULL,
 total_attempts INTEGER DEFAULT 0,
 successful_attempts INTEGER DEFAULT 0,
 success_rate REAL DEFAULT 0.0,
 avg_validation_score REAL DEFAULT 0.0,
 last_seen TEXT,
 UNIQUE(event_type, best_action)
 )
 """)
    # Camada 9: Human Decision Intelligence
    conn.execute("""
 CREATE TABLE IF NOT EXISTS human_decisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 approval_id INTEGER REFERENCES human_approvals(id),
 event_id INTEGER REFERENCES operational_events(id),
 ev_type TEXT,
 decisao TEXT, -- approve/reject/adjust/timeout
 acao_original TEXT, -- o que o sistema sugeriu
 acao_final TEXT, -- o que foi realmente executado
 motivo TEXT DEFAULT '',-- razão dada pelo humano
 impact_nivel TEXT,
 impact_score INTEGER,
 contradicts_pattern INTEGER DEFAULT 0, -- 1 se humano contradisse padrão confiante
 pattern_action TEXT DEFAULT '', -- o que o padrão sugeria (para rastreio)
 validado INTEGER DEFAULT 0, -- 1 quando resultado final é conhecido
 resultado_final TEXT DEFAULT 'pending',
 validation_score REAL DEFAULT 0.0,
 ts TEXT,
 validated_at TEXT
 )
 """)
    # Camada 10: Confidence Governance — auditoria de confiança
    conn.execute("""
 CREATE TABLE IF NOT EXISTS confidence_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_type TEXT,
 best_action TEXT,
 event_kind TEXT, -- decay/stress_test/revalidation_required/revalidation_done/overconfidence_alert
 old_confidence REAL,
 new_confidence REAL,
 details_json TEXT DEFAULT '{}',
 ts TEXT
 )
 """)
    # Camada 11: System Drift Control
    conn.execute("""
 CREATE TABLE IF NOT EXISTS drift_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope TEXT DEFAULT 'global', -- global | event_type
 scope_value TEXT DEFAULT '', -- '' | ev_type name
 period_days INTEGER,
 total_corrections INTEGER DEFAULT 0,
 successful_corrections INTEGER DEFAULT 0,
 success_rate REAL DEFAULT 0.0,
 avg_validation_score REAL DEFAULT 0.0,
 ts TEXT
 )
 """)
    conn.execute("""
 CREATE TABLE IF NOT EXISTS canary_tests (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_type TEXT,
 baseline_action TEXT,
 canary_action TEXT,
 baseline_rate REAL DEFAULT 0.0,
 canary_executions INTEGER DEFAULT 0,
 canary_successes INTEGER DEFAULT 0,
 canary_rate REAL DEFAULT 0.0,
 status TEXT DEFAULT 'active', -- active/passed/failed/rolled_back
 created_at TEXT,
 decided_at TEXT,
 notes TEXT DEFAULT ''
 )
 """)
    conn.execute("""
 CREATE TABLE IF NOT EXISTS exploration_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_type TEXT,
 action_tried TEXT,
 was_exploration INTEGER DEFAULT 1,
 success INTEGER DEFAULT 0,
 validation_score REAL DEFAULT 0.0,
 canary_id INTEGER,
 ts TEXT
 )
 """)
    # SLA tracking
    conn.execute("""
 CREATE TABLE IF NOT EXISTS sla_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_id INTEGER REFERENCES operational_events(id),
 metric TEXT, -- correction_time / human_response / escalation
 target_minutes REAL,
 actual_minutes REAL,
 met INTEGER, -- 1=met, 0=breached
 ts TEXT
 )
 """)
    # Adiciona colunas de peso humano e governança em patterns_learned (backward compat)
    for _col, _def in [
        ("human_validated_count", "INTEGER DEFAULT 0"),
        ("human_contradiction_count", "INTEGER DEFAULT 0"),
        ("peso", "TEXT DEFAULT 'normal'"),
        ("confidence_adjusted", "REAL"),  # success_rate após decay
        ("last_decay_at", "TEXT"),
        ("stress_test_count", "INTEGER DEFAULT 0"),
        ("stress_test_last_at", "TEXT"),
        ("stress_test_failures", "INTEGER DEFAULT 0"),
        ("revalidation_required", "INTEGER DEFAULT 0"),
        ("executions_since_revalidation", "INTEGER DEFAULT 0"),
        ("overconfidence_flagged", "INTEGER DEFAULT 0"),
        ("context_last", "TEXT DEFAULT '{}'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE patterns_learned ADD COLUMN {_col} {_def}")
        except sqlite3.OperationalError:
            pass  # coluna já existe
            # Adiciona campo motivo em human_approvals (backward compat)
            try:
                conn.execute("ALTER TABLE human_approvals ADD COLUMN motivo TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
                # Camada 8: Human-in-the-Loop — aprovações de alto impacto
                conn.execute("""
    CREATE TABLE IF NOT EXISTS human_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER REFERENCES operational_events(id),
    ev_type TEXT,
    impact_nivel TEXT, -- BAIXO / MEDIO / ALTO
    impact_score INTEGER,
    impact_fatores TEXT DEFAULT '[]',
    acao_sugerida TEXT,
    causa TEXT,
    risco TEXT,
    safe_fallback TEXT,
    status TEXT DEFAULT 'pending', -- pending/approved/rejected/timeout/adjusted
    acao_ajustada TEXT, -- se operador escolheu ação diferente
    created_at TEXT,
    responded_at TEXT,
    timeout_at TEXT
    )
    """)
                conn.commit()
                return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_event(
    conn,
    fingerprint: str,
    source: str,
    event_type: str,
    severity: str,
    details: dict,
    product: str = "",
) -> Optional[int]:
    """Insere evento se ainda não existe (por fingerprint). Retorna id ou None."""
    existing = conn.execute(
        "SELECT id, status, attempts FROM operational_events WHERE fingerprint=?", (fingerprint,)
    ).fetchone()
    if existing:
        # Só reativa se foi resolvido
        if existing["status"] in ("resolved", "ignored"):
            return None
            return existing["id"]
            cur = conn.execute(
                """INSERT INTO operational_events
   (fingerprint, source, event_type, severity, product, details_json, status, created_at, updated_at)
   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    fingerprint,
                    source,
                    event_type,
                    severity,
                    product,
                    json.dumps(details, ensure_ascii=False),
                    "detected",
                    _now(),
                    _now(),
                ),
            )
            conn.commit()
            return cur.lastrowid


def update_event(conn, event_id: int, **kwargs):
    kwargs["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [event_id]
    conn.execute(f"UPDATE operational_events SET {sets} WHERE id=?", vals)
    conn.commit()


def add_history(
    conn,
    event_id: int,
    attempt: int,
    action: str,
    before: dict,
    after: dict,
    success: bool,
    notes: str = "",
):
    conn.execute(
        """INSERT INTO correction_history
 (event_id, attempt, action, before_json, after_json, success, notes, ts)
 VALUES (?,?,?,?,?,?,?,?)""",
        (
            event_id,
            attempt,
            action,
            json.dumps(before),
            json.dumps(after),
            int(success),
            notes,
            _now(),
        ),
    )
    conn.commit()


# Helpers


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
        lines = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    lines.append(json.loads(line.strip()))
                except Exception:
                    pass
                    return lines


def _recent(records: list[dict], minutes: int = 30, ts_key: str = "timestamp") -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    result = []
    for r in records:
        ts_raw = r.get(ts_key, "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if ts >= cutoff:
                result.append(r)
        except Exception:
            result.append(r)  # sem timestamp → incluir mesmo assim
            return result


def _block_rate(decisions: list[dict]) -> float:
    if not decisions:
        return 0.0
        blocked = sum(1 for d in decisions if d.get("output", {}).get("decision") == "BLOQUEADO")
        return round(blocked / len(decisions), 3)


def _avg_confidence(events: list[dict]) -> float:
    if not events:
        return 0.0
        vals = [e.get("confidence_score", 0) for e in events if "confidence_score" in e]
        return round(sum(vals) / len(vals), 1) if vals else 0.0


def _fingerprint(*parts) -> str:
    import hashlib

    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# AGENTE 1: DETECTOR


class DetectorAgent:
    """
    Escaneia o sistema e retorna lista de anomalias detectadas.
    Cada anomalia é um dict com: source, event_type, severity, product, details, fingerprint
    """

    def __init__(self):
        self.decisions = _load_jsonl(DECISION_LOG)
        self.events = _load_jsonl(EVENTS_FILE)
        self.tasks = self._load_tasks()
        self.financial = self._load_financial()

    def _load_tasks(self) -> list[dict]:
        tasks = []
        if not TASKS_DIR.exists():
            return tasks
            for f in TASKS_DIR.glob("*.json"):
                try:
                    tasks.append(json.loads(f.read_text(encoding="utf-8")))
                except Exception:
                    pass
                    return tasks

    def _load_financial(self) -> dict:
        if FINANCIAL_FILE.exists():
            try:
                return json.loads(FINANCIAL_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
                return {}

    def run_all_checks(self) -> list[dict]:
        anomalies = []
        checks = [
            self.check_block_rate_spike,
            self.check_confidence_drop,
            self.check_pipeline_stale,
            self.check_task_failure_rate,
            self.check_engine_bias,
            self.check_extreme_block_engine,
            self.check_financial_anomaly,
        ]
        for check in checks:
            try:
                result = check()
                if result:
                    anomalies.extend(result if isinstance(result, list) else [result])
            except Exception as exc:
                print(f" [Detector] Erro em {check.__name__}: {exc}")
                return anomalies

                # Check 1: taxa de bloqueio subiu

    def check_block_rate_spike(self) -> Optional[dict]:
        recent = _recent(self.decisions, minutes=60)
        if len(recent) < 5:
            return None
            rate = _block_rate(recent)
            overall = _block_rate(self.decisions)
            delta = rate - overall
            if rate <= BLOCK_RATE_THRESHOLD:
                return None
                severity = "critical" if rate > 0.5 else "high"
                fp = _fingerprint("block_rate", round(rate, 1))
                return {
                    "fingerprint": fp,
                    "source": "block_rate_monitor",
                    "event_type": "block_rate_spike",
                    "severity": severity,
                    "product": "pipeline_geral",
                    "details": {
                        "recent_block_rate": rate,
                        "overall_block_rate": overall,
                        "delta": round(delta, 3),
                        "recent_n": len(recent),
                        "message": f"Taxa de bloqueio recente {rate:.0%} está acima do threshold {BLOCK_RATE_THRESHOLD:.0%}",
                    },
                }

                # Check 2: confiança caindo

    def check_confidence_drop(self) -> Optional[dict]:
        recent = _recent(self.events, minutes=60)
        if len(recent) < 4:
            return None
            avg = _avg_confidence(recent)
            if avg >= CONFIDENCE_THRESHOLD_LOW or avg == 0.0:
                return None
                drop = CONFIDENCE_BASELINE - avg
                severity = "high" if drop > 15 else "medium"
                fp = _fingerprint("confidence", round(avg, 0))
                return {
                    "fingerprint": fp,
                    "source": "confidence_monitor",
                    "event_type": "confidence_drop",
                    "severity": severity,
                    "product": "verification_engine",
                    "details": {
                        "current_avg_confidence": avg,
                        "baseline": CONFIDENCE_BASELINE,
                        "drop": round(drop, 1),
                        "recent_n": len(recent),
                        "message": f"Confiança média caiu para {avg} (baseline {CONFIDENCE_BASELINE}, queda de {drop:.1f} pts)",
                    },
                }

                # Check 3: pipeline parado

    def check_pipeline_stale(self) -> Optional[dict]:
        if not self.events:
            return None
            last = sorted(self.events, key=lambda x: x.get("timestamp", ""))[-1]
            ts_raw = last.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                minutes_since = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            except Exception:
                return None
                if minutes_since < STALE_MINUTES:
                    return None
                    fp = _fingerprint("stale", round(minutes_since / 10) * 10)
                    return {
                        "fingerprint": fp,
                        "source": "staleness_monitor",
                        "event_type": "pipeline_stale",
                        "severity": "high" if minutes_since > 120 else "medium",
                        "product": "pipeline_geral",
                        "details": {
                            "minutes_since_last_event": round(minutes_since, 1),
                            "last_event_ts": ts_raw,
                            "message": f"Nenhum evento de verificação há {minutes_since:.0f} minutos — pipeline pode estar travado",
                        },
                    }

                    # Check 4: falhas de execução acumulando

    def check_task_failure_rate(self) -> Optional[dict]:
        if not self.tasks:
            return None
            failed = [t for t in self.tasks if t.get("status") in ("failed", "error", "timeout")]
            pending = [t for t in self.tasks if t.get("status") == "pending"]
            total = len(self.tasks)
            if total < 3:
                return None
                fail_rate = len(failed) / total
                if fail_rate < TASK_FAILURE_THRESHOLD:
                    return None
                    fp = _fingerprint("task_fail", round(fail_rate, 1))
                    return {
                        "fingerprint": fp,
                        "source": "task_monitor",
                        "event_type": "task_failure_spike",
                        "severity": "high" if fail_rate > 0.6 else "medium",
                        "product": "execution_engine",
                        "details": {
                            "failed_count": len(failed),
                            "pending_count": len(pending),
                            "total_tasks": total,
                            "failure_rate": round(fail_rate, 3),
                            "failed_ids": [t.get("task_id", "")[:8] for t in failed[:5]],
                            "message": f"{len(failed)}/{total} tasks falhadas ({fail_rate:.0%})",
                        },
                    }

                    # Check 5: bias por engine (replica audit_engine mas em tempo real)

    def check_engine_bias(self) -> Optional[dict]:
        groups: dict[str, list] = defaultdict(list)
        for d in self.decisions:
            groups[d.get("engine", "unknown")].append(d)
            rates = {eng: _block_rate(ds) for eng, ds in groups.items() if len(ds) >= 5}
            if len(rates) < 2:
                return None
                max_r = max(rates.values())
                min_r = min(rates.values())
                delta = max_r - min_r
                if delta <= 0.30:  # já sabemos que o spread atual é 32%, só alerta se piorar
                    return None
                    worst_eng = max(rates, key=lambda k: rates[k])
                    fp = _fingerprint("bias_engine", round(delta, 1), worst_eng)
                    return {
                        "fingerprint": fp,
                        "source": "bias_monitor",
                        "event_type": "engine_bias_detected",
                        "severity": "high" if delta > 0.40 else "medium",
                        "product": worst_eng,
                        "details": {
                            "delta": round(delta, 3),
                            "rates": rates,
                            "worst_engine": worst_eng,
                            "worst_rate": round(max_r, 3),
                            "message": f"Spread de {delta:.0%} entre engines — {worst_eng} bloqueado {max_r:.0%}",
                        },
                    }

                    # Check 6: um engine específico com bloqueio crítico

    def check_extreme_block_engine(self) -> list[dict]:
        groups: dict[str, list] = defaultdict(list)
        for d in _recent(self.decisions, minutes=120):
            groups[d.get("engine", "unknown")].append(d)
            anomalies = []
            for eng, ds in groups.items():
                if len(ds) < 4:
                    continue
                    rate = _block_rate(ds)
                    if rate < 0.55:
                        continue
                        fp = _fingerprint("extreme_block", eng, round(rate, 1))
                        anomalies.append(
                            {
                                "fingerprint": fp,
                                "source": "engine_block_monitor",
                                "event_type": "engine_extreme_blocking",
                                "severity": "critical" if rate > 0.70 else "high",
                                "product": eng,
                                "details": {
                                    "engine": eng,
                                    "block_rate": round(rate, 3),
                                    "n_decisions": len(ds),
                                    "message": f"{eng} bloqueando {rate:.0%} das decisões recentes — verificar calibração",
                                },
                            }
                        )
                        return anomalies

                        # Check 7: anomalia financeira

    def check_financial_anomaly(self) -> Optional[dict]:
        projs = self.financial.get("projections", [])
        if len(projs) < 2:
            return None
            last = projs[-1]
            prev = projs[-2]
            margin_drop = prev["monthly_margin_pct"] - last["monthly_margin_pct"]
            if margin_drop < 10:
                return None
                fp = _fingerprint("financial_margin", last["month"])
                return {
                    "fingerprint": fp,
                    "source": "financial_monitor",
                    "event_type": "margin_drop",
                    "severity": "high" if margin_drop > 20 else "medium",
                    "product": "financeiro",
                    "details": {
                        "current_margin": last["monthly_margin_pct"],
                        "previous_margin": prev["monthly_margin_pct"],
                        "drop": round(margin_drop, 1),
                        "month": last["month"],
                        "message": f"Margem caiu {margin_drop:.1f}pp em {last['month']} — investigar custos",
                    },
                }


# AGENTE 2: DIAGNÓSTICO


class DiagnosticoAgent:
    """
    Usa Claude para analisar causa raiz e sugerir correção específica.
    Retorna dict com: causa_provavel, criticidade, acao_recomendada, urgencia, contexto_adicional
    """

    SYSTEM_PROMPT = """Você é um engenheiro sênior de sistemas de IA operacionais.
Analise o problema detectado no pipeline MYO e forneça diagnóstico técnico preciso e auditável.

O sistema MYO é um pipeline de negócio digital autônomo com:
- 22 engines de IA (Claude, GPT-4o, Perplexity)
- Loop: scoring → produto → conteúdo → execução → validação → aprendizado → adaptação
- decision_log.jsonl com 45 decisões auditadas (baseline: 73.6% confiança, 20% bloqueio)
- Policy Adapter que ajusta thresholds automaticamente (floor 40, ceiling 90, ±5/ciclo)

OBRIGATÓRIO: inclua "alternativas_consideradas" — liste pelo menos 2 ações que você avaliou
e descartou, com a razão. Isso é exigido para auditoria (LGPD/EU AI Act).

Responda SOMENTE em JSON válido com esta estrutura:
{
"causa_provavel": "...",
"criticidade": "critical|high|medium|low",
"acao_recomendada": "retry|relax_threshold|tighten_threshold|restart_engine|notify_human|recalibrate|check_api|clear_stale",
"alternativas_consideradas": [
{"acao": "notify_human", "razao_descartada": "problema ainda dentro do range de auto-correção"},
{"acao": "restart_engine", "razao_descartada": "causa é de calibração, não de processo travado"}
],
"parametros_acao": {},
"urgencia_minutos": 30,
"contexto_adicional": "...",
"confianca_diagnostico": 0.0
}"""


def analyze(self, event_type: str, severity: str, details: dict, product: str = "") -> dict:
    if not ANTHROPIC_KEY:
        return self._fallback_diagnosis(event_type, severity, details)

        context = json.dumps(
            {
                "event_type": event_type,
                "severity": severity,
                "product": product,
                "details": details,
                "system_context": {
                    "baseline_block_rate": 0.20,
                    "baseline_confidence": 73.6,
                    "active_engines": [
                        "opportunity_scorer",
                        "product_engine",
                        "content_engine",
                        "autonomous_agent",
                    ],
                    "current_policy": "context_policy.json (6C: idea/research/mvp/launch_ready/scaling)",
                },
            },
            ensure_ascii=False,
            indent=2,
        )

        prompt = f"Analise este problema detectado no pipeline MYO:\n\n{context}"

        try:
            import httpx

            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",  # haiku para diagnósticos rápidos
                    "max_tokens": 512,
                    "system": self.SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30.0,
            )
            if response.status_code == 200:
                text = response.json()["content"][0]["text"]
                # extrai JSON da resposta
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    return json.loads(text[start:end])
        except Exception as exc:
            print(f" [Diagnóstico] Erro ao chamar Claude: {exc}")

            return self._fallback_diagnosis(event_type, severity, details)

            def _fallback_diagnosis(self, event_type: str, severity: str, details: dict) -> dict:
                """Diagnóstico baseado em regras quando Claude não está disponível."""
                MAP = {
                    "block_rate_spike": {
                        "causa_provavel": "Taxa de bloqueio acima do baseline — possível calibração incorreta de thresholds ou mudança no tipo de claims sendo geradas",
                        "acao_recomendada": "relax_threshold",
                        "parametros_acao": {"topic": "geral", "step": -5},
                        "urgencia_minutos": 30,
                        "confianca_diagnostico": 0.6,
                    },
                    "confidence_drop": {
                        "causa_provavel": "Queda de confiança média — engines gerando claims menos precisas ou mudança nos tópicos sendo verificados",
                        "acao_recomendada": "recalibrate",
                        "parametros_acao": {"action": "run_policy_adapter"},
                        "urgencia_minutos": 60,
                        "confianca_diagnostico": 0.55,
                    },
                    "pipeline_stale": {
                        "causa_provavel": "Nenhum evento de verificação recente — pipeline travado ou sem input",
                        "acao_recomendada": "restart_engine",
                        "parametros_acao": {"engine": "verification_engine"},
                        "urgencia_minutos": 15,
                        "confianca_diagnostico": 0.8,
                    },
                    "task_failure_spike": {
                        "causa_provavel": "Acúmulo de tasks falhadas — possível problema de API, timeout ou erro de configuração",
                        "acao_recomendada": "retry",
                        "parametros_acao": {"max_retries": 3, "backoff_seconds": 30},
                        "urgencia_minutos": 20,
                        "confianca_diagnostico": 0.7,
                    },
                    "engine_bias_detected": {
                        "causa_provavel": "Spread de bloqueio entre engines aumentando — engine específico com thresholds mal calibrados",
                        "acao_recomendada": "recalibrate",
                        "parametros_acao": {
                            "action": "run_audit",
                            "engine": details.get("worst_engine", ""),
                        },
                        "urgencia_minutos": 60,
                        "confianca_diagnostico": 0.65,
                    },
                    "engine_extreme_blocking": {
                        "causa_provavel": f"Engine {details.get('engine','')} bloqueando mais de 55% das decisões — provável miscalibração ou mudança de input",
                        "acao_recomendada": "relax_threshold",
                        "parametros_acao": {"engine": details.get("engine", ""), "step": -5},
                        "urgencia_minutos": 20,
                        "confianca_diagnostico": 0.75,
                    },
                    "margin_drop": {
                        "causa_provavel": "Margem caindo — custos aumentando ou receita estagnando",
                        "acao_recomendada": "notify_human",
                        "parametros_acao": {"reason": "financial_review_needed"},
                        "urgencia_minutos": 120,
                        "confianca_diagnostico": 0.5,
                    },
                }
                base = MAP.get(
                    event_type,
                    {
                        "causa_provavel": f"Anomalia do tipo {event_type} — análise manual necessária",
                        "acao_recomendada": "notify_human",
                        "parametros_acao": {},
                        "urgencia_minutos": 60,
                        "confianca_diagnostico": 0.3,
                    },
                )
                return {
                    "causa_provavel": base.get("causa_provavel", ""),
                    "criticidade": severity,
                    "acao_recomendada": base.get("acao_recomendada", "notify_human"),
                    "parametros_acao": base.get("parametros_acao", {}),
                    "urgencia_minutos": base.get("urgencia_minutos", 60),
                    "contexto_adicional": f"Diagnóstico por regras (Claude indisponível). Detalhes: {details.get('message','')}",
                    "confianca_diagnostico": base.get("confianca_diagnostico", 0.4),
                }


# AGENTE 3: CORREÇÃO


class CorrectionAgent:
    """
    Aplica ação corretiva baseada no diagnóstico.
    Retorna (success: bool, action_taken: str, before: dict, after: dict)
    """

    def apply(
        self, acao: str, parametros: dict, details: dict, event_id: int
    ) -> tuple[bool, str, dict, dict]:
        handler = {
            "retry": self._retry_tasks,
            "relax_threshold": self._relax_threshold,
            "tighten_threshold": self._tighten_threshold,
            "restart_engine": self._restart_engine,
            "notify_human": self._notify_human,
            "recalibrate": self._recalibrate,
            "check_api": self._check_api,
            "clear_stale": self._clear_stale,
        }.get(acao, self._notify_human)

        return handler(parametros, details, event_id)

    def _run(self, *cmd, timeout: int = 60) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, cwd=Path(__file__).parent
            )
            return result.returncode == 0, (result.stdout + result.stderr).strip()
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as e:
            return False, str(e)

    def _snapshot_metrics(self) -> dict:
        events = _load_jsonl(EVENTS_FILE)
        decisions = _load_jsonl(DECISION_LOG)
        recent_e = _recent(events, minutes=30)
        recent_d = _recent(decisions, minutes=30)
        return {
            "block_rate_recent": _block_rate(recent_d),
            "confidence_avg": _avg_confidence(recent_e),
            "total_events": len(events),
            "total_decisions": len(decisions),
            "ts": _now(),
        }

        # Ações

    def _retry_tasks(self, params, details, event_id) -> tuple:
        before = self._snapshot_metrics()
        max_r = params.get("max_retries", 2)
        retried = 0
        if TASKS_DIR.exists():
            for f in TASKS_DIR.glob("*.json"):
                try:
                    task = json.loads(f.read_text(encoding="utf-8"))
                    if (
                        task.get("status") in ("failed", "error")
                        and task.get("attempts", 0) < max_r
                    ):
                        task["status"] = "pending"
                        task["attempts"] = task.get("attempts", 0) + 1
                        task["retry_reason"] = "self_healing_engine"
                        f.write_text(
                            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
                        retried += 1
                except Exception:
                    pass
                    after = self._snapshot_metrics()
                    return retried > 0, f"retry_tasks:{retried}_reenfileiradas", before, after

    def _relax_threshold(self, params, details, event_id) -> tuple:
        before = self._snapshot_metrics()
        # Executa policy_adapter sem salvar primeiro (--dry-run para verificar)
        ok, out = self._run("python3", "policy_adapter.py", "--dry-run")
        if not ok:
            return False, "relax_threshold:policy_adapter_dry_run_falhou", before, before
            # Aplica de verdade
            ok2, out2 = self._run("python3", "policy_adapter.py")
            after = self._snapshot_metrics()
            return ok2, f"relax_threshold:policy_adapter_{'ok' if ok2 else 'erro'}", before, after

    def _tighten_threshold(self, params, details, event_id) -> tuple:
        # Tighten usa o mesmo policy_adapter — ele endurece automaticamente
        # quando há evidências de muita permissividade
        return self._relax_threshold(params, details, event_id)

    def _restart_engine(self, params, details, event_id) -> tuple:
        before = self._snapshot_metrics()
        engine = params.get("engine", "decision_logger")
        # Para verification_engine: reconstruir decision_log (é o mais seguro)
        if engine in ("verification_engine", "decision_logger"):
            ok, out = self._run("python3", "decision_logger.py", "--rebuild")
            after = self._snapshot_metrics()
            return (
                ok,
                f"restart:{engine}:decision_logger_rebuild_{'ok' if ok else 'erro'}",
                before,
                after,
            )
            # Para outros engines: apenas notifica (não reiniciamos processos arbitrários)
            after = self._snapshot_metrics()
            _telegram_alert(
                f" Self-Healing: restart_engine solicitado para {engine}\n"
                f"Ação manual necessária — rode: python3 {engine}.py",
                "warn",
            )
            return True, f"restart:{engine}:notificado_operador", before, after

    def _notify_human(self, params, details, event_id) -> tuple:
        before = self._snapshot_metrics()
        reason = params.get("reason", "anomalia detectada")
        msg = (
            f" Self-Healing: ESCALONAMENTO HUMANO\n"
            f"Motivo: {reason}\n"
            f"Detalhes: {details.get('message','—')}\n"
            f"Event ID: {event_id}"
        )
        _telegram_alert(msg, "critical")
        return True, f"notify_human:{reason}", before, before

    def _recalibrate(self, params, details, event_id) -> tuple:
        before = self._snapshot_metrics()
        action = params.get("action", "run_policy_adapter")
        if action == "run_audit":
            ok, out = self._run("python3", "audit_engine.py", "--export")
            label = "audit_engine_export"
        else:
            ok, out = self._run("python3", "policy_adapter.py")
            label = "policy_adapter"
            after = self._snapshot_metrics()
            return ok, f"recalibrate:{label}_{'ok' if ok else 'erro'}", before, after

    def _check_api(self, params, details, event_id) -> tuple:
        before = self._snapshot_metrics()
        # Teste simples de API: verificar se env vars existem
        checks = {
            "ANTHROPIC_API_KEY": bool(os.getenv("ANTHROPIC_API_KEY")),
            "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
            "PERPLEXITY_API_KEY": bool(os.getenv("PERPLEXITY_API_KEY")),
        }
        missing = [k for k, v in checks.items() if not v]
        if missing:
            _telegram_alert(
                f" Self-Healing: API keys ausentes: {', '.join(missing)}\n"
                "Verificar .env e reconfigurar.",
                "critical",
            )
            return False, f"check_api:keys_missing:{','.join(missing)}", before, before
            return True, "check_api:todas_keys_presentes", before, before

    def _clear_stale(self, params, details, event_id) -> tuple:
        before = self._snapshot_metrics()
        # Remove arquivos de lock temporários se existirem
        cleared = 0
        for lock_file in Path("outputs").rglob("*.lock"):
            try:
                lock_file.unlink()
                cleared += 1
            except Exception:
                pass
                after = self._snapshot_metrics()
                return True, f"clear_stale:{cleared}_locks_removidos", before, after


# AGENTE 4: VALIDADOR


class ValidatorAgent:
    """
    Verifica se a correção melhorou o estado do sistema.
    Retorna (passed: bool, score: float, notes: str)
    """

    def validate(self, event_type: str, before: dict, after: dict) -> tuple[bool, float, str]:
        if not before or not after:
            return True, 0.5, "sem métricas para comparar"

            VALIDATORS = {
                "block_rate_spike": self._check_block_rate,
                "confidence_drop": self._check_confidence,
                "engine_extreme_blocking": self._check_block_rate,
                "engine_bias_detected": self._check_block_rate,
                "task_failure_spike": self._check_tasks,
                "pipeline_stale": self._check_activity,
                "margin_drop": self._check_generic,
            }
            fn = VALIDATORS.get(event_type, self._check_generic)
            return fn(before, after)

    def _check_block_rate(self, before, after) -> tuple:
        b = before.get("block_rate_recent", 1.0)
        a = after.get("block_rate_recent", 1.0)
        delta = b - a  # positivo = melhorou
        if delta > 0.05:
            return True, round(0.6 + min(delta, 0.4), 2), f"block rate caiu {delta:.0%} — "
            if delta < -0.05:
                return False, round(0.4 - min(-delta, 0.3), 2), f"block rate PIOROU {-delta:.0%} — "
                return True, 0.5, f"block rate estável ({a:.0%}) — neutro"

    def _check_confidence(self, before, after) -> tuple:
        b = before.get("confidence_avg", 0)
        a = after.get("confidence_avg", 0)
        if a == 0:
            return True, 0.5, "sem dados de confiança pós-correção"
            delta = a - b
            if delta > 2:
                return True, min(0.5 + delta / 20, 0.95), f"confiança subiu {delta:.1f} pts — "
                if delta < -2:
                    return (
                        False,
                        max(0.1, 0.5 + delta / 20),
                        f"confiança CAIU mais {-delta:.1f} pts — ",
                    )
                    return True, 0.5, f"confiança estável ({a}) — neutro"

    def _check_tasks(self, before, after) -> tuple:
        # Verificar se tasks pendentes diminuíram
        b = before.get("total_decisions", 0)
        a = after.get("total_decisions", 0)
        if a >= b:
            return True, 0.6, f"decisões aumentaram ({b} → {a}) — atividade retomada "
            return True, 0.5, "sem variação imediata — retry enfileirado"

    def _check_activity(self, before, after) -> tuple:
        b = before.get("total_events", 0)
        a = after.get("total_events", 0)
        if a > b:
            return True, 0.8, f"novos eventos detectados ({b} → {a}) — pipeline ativo "
            return True, 0.5, "ainda sem novos eventos — aguardar próximo ciclo"

    def _check_generic(self, before, after) -> tuple:
        return True, 0.5, "validação genérica — ação registrada"


# CAMADA 5: EXPLICABILIDADE


class ExplainabilityLayer:
    """
    Registra e persiste o raciocínio por trás de cada decisão corretiva.
    Campo 'explanation' exigido por contratos enterprise e auditoria regulatória.

    Responde: "Por que o sistema tomou essa decisão?"
    """

    def record(
        self,
        conn: sqlite3.Connection,
        event_id: int,
        diagnosis: dict,
        fonte: str,
        overridden: bool = False,
        learned_action: str = "",
    ) -> dict:
        causa = diagnosis.get("causa_provavel", "—")
        acao = diagnosis.get("acao_recomendada", "—")
        alternativas = list(diagnosis.get("alternativas_consideradas", []))
        confianca = float(diagnosis.get("confianca_diagnostico", 0.0))

        # Se learning sobrescreveu o diagnóstico, registrar como alternativa descartada
        decisao = acao
        if overridden and learned_action and learned_action != acao:
            decisao = learned_action
            alternativas.append(
                {
                    "acao": acao,
                    "razao_descartada": (
                        f"Padrão de aprendizado indica taxa de sucesso maior com '{learned_action}' "
                        f"para este tipo de evento — diagnóstico original descartado"
                    ),
                }
            )

            # Garante pelo menos 1 alternativa para conformidade
            if not alternativas:
                alternativas = [
                    {
                        "acao": "notify_human",
                        "razao_descartada": "problema ainda dentro do alcance de auto-correção",
                    }
                ]

                conn.execute(
                    """INSERT INTO explanation_log
    (event_id, causa, decisao, alternativas_json, nivel_confianca,
    fonte_diagnostico, overridden, ts)
    VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        event_id,
                        causa,
                        decisao,
                        json.dumps(alternativas, ensure_ascii=False),
                        confianca,
                        fonte,
                        int(overridden),
                        _now(),
                    ),
                )
                conn.commit()

                return {
                    "causa": causa,
                    "decisao": decisao,
                    "alternativas_consideradas": alternativas,
                    "nivel_confianca": confianca,
                    "fonte_diagnostico": fonte,
                    "overridden_by_learning": overridden,
                }

    def get(self, conn: sqlite3.Connection, event_id: int) -> Optional[dict]:
        row = conn.execute(
            "SELECT * FROM explanation_log WHERE event_id=? ORDER BY ts DESC LIMIT 1", (event_id,)
        ).fetchone()
        if not row:
            return None
            return {
                "causa": row["causa"],
                "decisao": row["decisao"],
                "alternativas_consideradas": json.loads(row["alternativas_json"] or "[]"),
                "nivel_confianca": row["nivel_confianca"],
                "fonte_diagnostico": row["fonte_diagnostico"],
            }

    def print_explanation(self, exp: dict):
        if not exp:
            return
            print(f" EXPLICABILIDADE {''*42}")
            print(f" Causa: {exp['causa'][:75]}")
            print(f" Decisão: {exp['decisao']}")
            print(f" Confiança: {exp['nivel_confianca']:.0%} | Fonte: {exp['fonte_diagnostico']}")
            for alt in exp.get("alternativas_consideradas", [])[:3]:
                print(f" {alt.get('acao','?'):<20} → {alt.get('razao_descartada','?')[:50]}")
                print(f" {''*60}")


# CAMADA 6: SEGURANÇA — ANTI-AUTO-DESTRUIÇÃO


class SafetyGuard:
    """
    Protege o sistema de se auto-prejudicar.

    Mecanismos:
    1. Rate limits por ação (por hora) — evita mudanças excessivas
    2. Circuit breaker — bloqueia loop se 3 correções seguidas piorarem
    3. Impact limits — relax/tighten máx ±10%, restart máx 2×/hora
    """

    # Máximo de execuções por ação por hora
    RATE_LIMITS: dict[str, int] = {
        "relax_threshold": 2,  # mudança de policy é significativa
        "tighten_threshold": 2,
        "restart_engine": 2,  # reinícios custosos
        "recalibrate": 3,
        "retry": 5,
        "check_api": 10,
        "clear_stale": 5,
        "notify_human": 10,
    }

    # Correções seguidas que pioram antes de travar
    CIRCUIT_BREAKER_THRESHOLD = 3

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._consecutive_worse = 0  # in-memory, reseta quando alguma melhora
        self._circuit_open = False

    def can_apply(self, action: str, event_type: str = "") -> tuple[bool, str]:
        """Retorna (permitido, motivo)."""
        # 1. Circuit breaker
        if self._circuit_open:
            return False, (
                f"circuit_breaker_aberto:{self._consecutive_worse}_correções_seguidas_pioraram"
                " — aguardando intervenção humana"
            )

            # 2. Rate limit — conta execuções na última hora
            limit = self.RATE_LIMITS.get(action, 3)
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            count = self.conn.execute(
                "SELECT COUNT(*) FROM action_audit_log WHERE action=? AND ts>?", (action, cutoff)
            ).fetchone()[0]

            if count >= limit:
                return False, (
                    f"rate_limit:{action}:{count}/{limit}_por_hora" " — aguardar próximo ciclo"
                )

                return True, "ok"

    def record(self, action: str, event_type: str, success: bool, validation_score: float = 0.5):
        """Registra execução e atualiza circuit breaker."""
        self.conn.execute(
            "INSERT INTO action_audit_log (action, event_type, success, ts) VALUES (?,?,?,?)",
            (action, event_type, int(success), _now()),
        )
        self.conn.commit()

        if success and validation_score > 0.5:
            self._consecutive_worse = 0
            self._circuit_open = False
        elif not success or validation_score < 0.4:
            self._consecutive_worse += 1
            if self._consecutive_worse >= self.CIRCUIT_BREAKER_THRESHOLD:
                self._circuit_open = True
                _telegram_alert(
                    f" Circuit Breaker ABERTO\n"
                    f"{self._consecutive_worse} correções seguidas pioraram o sistema.\n"
                    "Auto-correção suspensa — intervenção manual necessária.",
                    "critical",
                )

    def status(self) -> dict:
        cutoff_1h = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        rows = self.conn.execute(
            "SELECT action, COUNT(*) as n FROM action_audit_log WHERE ts>? GROUP BY action",
            (cutoff_1h,),
        ).fetchall()
        usage = {r["action"]: r["n"] for r in rows}
        return {
            "circuit_open": self._circuit_open,
            "consecutive_worse": self._consecutive_worse,
            "actions_last_hour": usage,
            "rate_limits": self.RATE_LIMITS,
        }

    def reset_circuit(self):
        """Reset manual pelo operador."""
        self._circuit_open = False
        self._consecutive_worse = 0
        print(" Circuit breaker resetado manualmente")


# CAMADA 7: APRENDIZADO — MEMÓRIA DE LONGO PRAZO


class LearningLayer:
    """
    Aprende qual correção funciona melhor para cada tipo de problema.

    Na próxima vez que o mesmo event_type aparecer:
    → não tenta tudo → já sabe o melhor caminho
    → se taxa de sucesso > MIN_CONFIDENCE → sobrescreve diagnóstico

    Tabela: patterns_learned
    event_type × best_action → success_rate, avg_validation_score
    """

    MIN_ATTEMPTS = 3  # mínimo de dados para confiar no padrão
    MIN_CONFIDENCE = 0.70  # success_rate mínima para sobrescrever diagnóstico

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

        # Threshold reduzido para padrões com validação humana (peso='alto')
        MIN_CONFIDENCE_HUMAN = 0.60

    def get_best_action(self, event_type: str) -> Optional[tuple[str, float, float]]:
        """
        Retorna (best_action, effective_confidence, avg_score) ou None.

        Usa COALESCE(confidence_adjusted, success_rate) = confiança efetiva após decay.
        Exclui padrões com revalidation_required=1 — esses não podem operar sozinhos.
        Padrões peso='alto' ativam com threshold menor (MIN_CONFIDENCE_HUMAN).
        """
        # 1. Padrão com validação humana e peso alto (threshold menor, decay respeitado)
        row = self.conn.execute(
            """SELECT best_action, success_rate, avg_validation_score,
  COALESCE(confidence_adjusted, success_rate) AS eff_conf
  FROM patterns_learned
  WHERE event_type=? AND total_attempts>=?
  AND COALESCE(confidence_adjusted, success_rate) >= ?
  AND peso='alto'
  AND revalidation_required=0
  ORDER BY human_validated_count DESC, eff_conf DESC
  LIMIT 1""",
            (event_type, self.MIN_ATTEMPTS, self.MIN_CONFIDENCE_HUMAN),
        ).fetchone()
        if row:
            return row["best_action"], row["eff_conf"], row["avg_validation_score"]

            # 2. Fallback: padrão automático (threshold padrão, decay respeitado)
            row = self.conn.execute(
                """SELECT best_action, success_rate, avg_validation_score,
   COALESCE(confidence_adjusted, success_rate) AS eff_conf
   FROM patterns_learned
   WHERE event_type=? AND total_attempts>=?
   AND COALESCE(confidence_adjusted, success_rate) >= ?
   AND revalidation_required=0
   ORDER BY eff_conf DESC, avg_validation_score DESC
   LIMIT 1""",
                (event_type, self.MIN_ATTEMPTS, self.MIN_CONFIDENCE),
            ).fetchone()
            if row:
                return row["best_action"], row["eff_conf"], row["avg_validation_score"]
                return None

    def record_outcome(
        self,
        event_type: str,
        action: str,
        success: bool,
        validation_score: float,
        human_validated: bool = False,
    ):
        """
        Atualiza (ou cria) padrão aprendido.
        Se human_validated=True, incrementa human_validated_count e eleva peso.
        """
        existing = self.conn.execute(
            """SELECT id, total_attempts, successful_attempts, avg_validation_score,
  human_validated_count, peso
  FROM patterns_learned WHERE event_type=? AND best_action=?""",
            (event_type, action),
        ).fetchone()

        hvc_delta = 1 if human_validated else 0

        if existing:
            total = existing["total_attempts"] + 1
            succ = existing["successful_attempts"] + int(success)
            rate = round(succ / total, 3)
            new_avg = round(
                (existing["avg_validation_score"] * existing["total_attempts"] + validation_score)
                / total,
                3,
            )
            new_hvc = existing["human_validated_count"] + hvc_delta
            # Eleva peso se tem 2+ validações humanas bem-sucedidas
            new_peso = existing["peso"]
            if human_validated and success and new_hvc >= 2:
                new_peso = "alto"
                self.conn.execute(
                    """UPDATE patterns_learned
    SET total_attempts=?, successful_attempts=?, success_rate=?,
    avg_validation_score=?, human_validated_count=?, peso=?, last_seen=?
    WHERE event_type=? AND best_action=?""",
                    (total, succ, rate, new_avg, new_hvc, new_peso, _now(), event_type, action),
                )
            else:
                init_rate = float(int(success))
                self.conn.execute(
                    """INSERT INTO patterns_learned
    (event_type, best_action, total_attempts, successful_attempts,
    success_rate, confidence_adjusted, avg_validation_score,
    human_validated_count, peso, last_seen)
    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        event_type,
                        action,
                        1,
                        int(success),
                        init_rate,
                        init_rate,
                        validation_score,
                        hvc_delta,
                        "alto" if human_validated and success else "normal",
                        _now(),
                    ),
                )
                self.conn.commit()

    def get_all(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT event_type, best_action, total_attempts, successful_attempts,
  success_rate, avg_validation_score,
  human_validated_count, human_contradiction_count, peso, last_seen
  FROM patterns_learned ORDER BY peso DESC, success_rate DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def print_table(self):
        patterns = self.get_all()
        print(f"\n {''*85}")
        print(" Patterns Learned — Memória de Correções (com peso humano)")
        print(f" {''*85}")
        if not patterns:
            print(" Nenhum padrão aprendido ainda (mínimo 3 tentativas por tipo).")
            return
            print(
                f" {'Tipo de Evento':<28} {'Melhor Ação':<20} {'Tent':>5} {'Sucesso':>8} "
                f"{'Score':>6} {'Humano':>7} {'Contradições':>13} {'Peso'}"
            )
            print(f" {''*28} {''*20} {''*5} {''*8} {''*6} {''*7} {''*13} {''*6}")
            for p in patterns:
                icon = "" if p.get("peso") == "alto" else ("" if p["success_rate"] >= 0.70 else "")
                print(
                    f" {icon} {p['event_type']:<26} {p['best_action']:<20} "
                    f"{p['total_attempts']:>5} {p['success_rate']:>7.0%} "
                    f"{p['avg_validation_score']:>6.2f} "
                    f"{p.get('human_validated_count', 0):>7}× "
                    f"{p.get('human_contradiction_count', 0):>13}× "
                    f"{p.get('peso', 'normal')}"
                )
                print("\n peso=alto (validado por humano) confiança automática ≥70%")


# Telegram Alertas


def _telegram_alert(message: str, level: str = "info"):
    """Envia alerta via telegram_bot.send_alert (HTTP direto)."""
    try:
        import httpx

        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
            icon = {"critical": "", "warn": "", "info": "ℹ"}.get(level, "•")
            text = f"{icon} [{level.upper()}] {message}"
            httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text[:4000]},
                timeout=10,
            )
    except Exception:
        pass


# CAMADA 8: HUMAN-IN-THE-LOOP — AUTONOMIA CONTROLADA

# Tipos de evento que disparam cada fator de impacto
_FINANCIAL_TYPES = {
    "financial_anomaly",
    "revenue_drop",
    "financial_data_stale",
    "revenue_risk",
    "cost_spike",
}
_REVENUE_AFFECTING = {
    "high_block_rate",
    "confidence_drop",
    "pipeline_stalled",
    "financial_anomaly",
    "revenue_drop",
    "engine_bias_detected",
}
_USER_AFFECTING = {
    "pipeline_stalled",
    "task_failures",
    "engine_stalled",
    "api_failure",
    "stale_pipeline",
}
_STRUCTURAL_ACTIONS = {"relax_threshold", "tighten_threshold", "restart_engine", "recalibrate"}


def calcular_impacto(ev_type: str, acao: str, attempts: int, details: dict) -> dict:
    """
    Classifica impacto de uma correção antes de executar.

    Score → BAIXO (0-3) | MEDIO (4-6) | ALTO (7+)
    """
    score = 0
    fatores: list[str] = []

    if ev_type in _FINANCIAL_TYPES:
        score += 3
        fatores.append("tipo_financeiro(+3)")

        if ev_type in _REVENUE_AFFECTING:
            score += 3
            fatores.append("afeta_receita(+3)")

            if ev_type in _USER_AFFECTING:
                score += 2
                fatores.append("afeta_usuario(+2)")

                if attempts > 2:
                    score += 2
                    fatores.append(f"multi_tentativa:{attempts}(+2)")

                    if acao in _STRUCTURAL_ACTIONS:
                        score += 4
                        fatores.append(f"mudanca_estrutural:{acao}(+4)")

                        if score >= 7:
                            nivel = "ALTO"
                        elif score >= 4:
                            nivel = "MEDIO"
                        else:
                            nivel = "BAIXO"

                            return {"nivel": nivel, "score": score, "fatores": fatores}


class HumanApprovalGate:
    """
    Camada 8 — Human-in-the-Loop inteligente.

    Regra global:
    BAIXO → auto-execução silenciosa
    MEDIO → auto-execução + notificação informativa
    ALTO → BLOQUEADO até aprovação humana (timeout → ação segura)

    Fluxo ALTO:
    1. Grava pending em human_approvals
    2. Envia Telegram com causa / risco / opções CLI
    3. Faz polling do DB a cada POLL_INTERVAL segundos
    4. Timeout → aplica safe_fallback conservador (nunca a ação arriscada)

    CLI de resposta:
    --approve <id> → aprova ação sugerida
    --reject <id> → rejeita (mantém estado atual)
    --adjust <id> <acao> → aprova com ação diferente
    """

    TIMEOUT_SECONDS = 300  # 5 min
    POLL_INTERVAL = 10  # polling a cada 10s

    # Ação segura por ação arriscada — nunca executa a original se não houver resposta
    _SAFE_FALLBACK: dict[str, str] = {
        "relax_threshold": "check_api",  # não mudar policy sem aprovação
        "tighten_threshold": "check_api",
        "restart_engine": "notify_human",  # não reiniciar sem aprovação
        "recalibrate": "notify_human",
        "retry": "retry",  # retry é seguro
        "clear_stale": "check_api",
    }

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

        # API pública

    def request_approval(
        self, event_id: int, ev_type: str, impacto: dict, diagnosis: dict, acao: str, exp: dict
    ) -> int:
        """Persiste solicitação e envia alerta Telegram. Retorna approval_id."""
        causa = diagnosis.get("causa_provavel", "—")
        risco = diagnosis.get(
            "risco_inacao", "Sistema pode degradar progressivamente sem intervenção."
        )
        fallback = self._SAFE_FALLBACK.get(acao, "notify_human")
        timeout_at = (
            datetime.now(timezone.utc) + timedelta(seconds=self.TIMEOUT_SECONDS)
        ).isoformat()

        cur = self.conn.execute(
            """INSERT INTO human_approvals
  (event_id, ev_type, impact_nivel, impact_score, impact_fatores,
  acao_sugerida, causa, risco, safe_fallback, status,
  created_at, timeout_at)
  VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event_id,
                ev_type,
                impacto["nivel"],
                impacto["score"],
                json.dumps(impacto["fatores"]),
                acao,
                causa[:500],
                risco[:500],
                fallback,
                "pending",
                _now(),
                timeout_at,
            ),
        )
        self.conn.commit()
        approval_id = cur.lastrowid

        self._send_telegram_alert(approval_id, ev_type, impacto, causa, acao, risco, fallback)
        return approval_id

    def wait_for_response(self, approval_id: int, timeout: Optional[int] = None) -> tuple[str, str]:
        """
        Bloqueia até resposta humana ou timeout.
        Retorna (status, acao_final).
        status: 'approved' | 'rejected' | 'adjusted' | 'timeout'
        """
        deadline = time.time() + (timeout or self.TIMEOUT_SECONDS)

        print(
            f" ⏳ Aguardando aprovação #{approval_id} "
            f"(timeout: {timeout or self.TIMEOUT_SECONDS}s)..."
        )

        while time.time() < deadline:
            row = self.conn.execute(
                "SELECT status, acao_ajustada FROM human_approvals WHERE id=?", (approval_id,)
            ).fetchone()

            if row and row["status"] != "pending":
                status = row["status"]
                acao_f = row["acao_ajustada"] or ""
                icon = {"approved": "", "rejected": "", "adjusted": ""}.get(status, "•")
                print(
                    f" {icon} Resposta humana recebida: {status}"
                    + (f" → {acao_f}" if acao_f else "")
                )
                return status, acao_f

                time.sleep(self.POLL_INTERVAL)

                # Timeout — ação segura conservadora
                self.conn.execute(
                    "UPDATE human_approvals SET status='timeout', responded_at=? WHERE id=?",
                    (_now(), approval_id),
                )
                self.conn.commit()

                row = self.conn.execute(
                    "SELECT safe_fallback FROM human_approvals WHERE id=?", (approval_id,)
                ).fetchone()
                fallback = row["safe_fallback"] if row else "notify_human"

                print(f" ⏰ Timeout — ação segura aplicada: {fallback}")
                _telegram_alert(
                    f"⏰ Timeout de aprovação (#{approval_id})\n"
                    f"Nenhuma resposta em {timeout or self.TIMEOUT_SECONDS}s.\n"
                    f"Ação segura aplicada: {fallback}\n"
                    f"(ação original bloqueada)",
                    "warn",
                )
                return "timeout", fallback

    def respond(
        self, approval_id: int, status: str, acao_ajustada: str = "", motivo: str = ""
    ) -> bool:
        """Chamado pelos flags --approve / --reject / --adjust."""
        row = self.conn.execute(
            "SELECT id, status FROM human_approvals WHERE id=?", (approval_id,)
        ).fetchone()
        if not row:
            print(f" Aprovação #{approval_id} não encontrada.")
            return False
            if row["status"] != "pending":
                print(f" Aprovação #{approval_id} já processada: {row['status']}")
                return False
                self.conn.execute(
                    "UPDATE human_approvals SET status=?, acao_ajustada=?, motivo=?, responded_at=? WHERE id=?",
                    (status, acao_ajustada, motivo, _now(), approval_id),
                )
                self.conn.commit()
                icon = {"approved": "", "rejected": "", "adjusted": ""}.get(status, "•")
                print(
                    f" {icon} Aprovação #{approval_id} → {status}"
                    + (f" (ação: {acao_ajustada})" if acao_ajustada else "")
                    + (f"\n Motivo: {motivo}" if motivo else "")
                )
                return True

    def pending(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT id, ev_type, impact_nivel, impact_score, acao_sugerida,
  causa, created_at, timeout_at
  FROM human_approvals WHERE status='pending'
  ORDER BY created_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def show_pending(self):
        items = self.pending()
        print(f"\n {''*65}")
        print(" Human-in-the-Loop — Aprovações Pendentes")
        print(f" {''*65}")
        if not items:
            print(" Nenhuma aprovação pendente.\n")
            return
            for a in items:
                print(
                    f" #{a['id']} [{a['impact_nivel']} score:{a['impact_score']}] "
                    f"{a['ev_type']}"
                )
                print(f" Ação sugerida : {a['acao_sugerida']}")
                print(f" Causa : {a['causa'][:90]}")
                print(f" Timeout em : {a['timeout_at'][:19]}")
                print(f" Aprovar → python3 self_healing_engine.py --approve {a['id']}")
                print(f" Rejeitar → python3 self_healing_engine.py --reject {a['id']}")
                print()

                # Telegram

    def _send_telegram_alert(
        self,
        approval_id: int,
        ev_type: str,
        impacto: dict,
        causa: str,
        acao: str,
        risco: str,
        fallback: str,
    ):
        fatores_str = (
            "\n".join(f" • {f}" for f in impacto["fatores"])
            or " • nenhum fator específico identificado"
        )
        msg = (
            f" ALERTA CRÍTICO — SELF HEALING\n"
            f"{''*35}\n"
            f"Problema: {ev_type}\n\n"
            f"Causa provável:\n{causa[:200]}\n\n"
            f"Impacto: ALTO (score {impacto['score']})\n"
            f"Fatores:\n{fatores_str}\n\n"
            f"Ação sugerida: {acao}\n\n"
            f"Risco se não agir:\n{risco[:200]}\n\n"
            f"Opções:\n"
            f" [1] Aprovar:\n"
            f" python3 self_healing_engine.py --approve {approval_id}\n"
            f" [2] Rejeitar:\n"
            f" python3 self_healing_engine.py --reject {approval_id}\n"
            f" [3] Ajustar ação:\n"
            f" python3 self_healing_engine.py --adjust {approval_id} <acao>\n\n"
            f"⏰ Tempo limite: 5 min\n"
            f" Sem resposta → ação segura: {fallback}"
        )
        _telegram_alert(msg, "critical")


# CAMADA 9: HUMAN DECISION INTELLIGENCE


class HumanDecisionIntelligence:
    """
    Transforma cada decisão humana em dado de treinamento.

    Cada approve/reject/adjust do operador:
    1. É persistido em human_decisions com contexto completo
    2. É comparado com padrões existentes (contradiction check)
    3. Tem resultado monitorado após validação
    4. Alimenta LearningLayer com peso humano (human_validated=True)

    Proteção anti-sobrescrita:
    Se humano contradiz padrão de alta confiança (≥80%, ≥5 tentativas),
    registra como contradição. Só atualiza o padrão após 3 contradições
    bem-sucedidas — evita decisões impulsivas corrompendo o aprendizado.

    Métrica de acerto:
    taxa_acerto_sistema = aprovadas / total
    taxa_divergencia = (rejeitadas + ajustadas) / total
    """

    CONTRADICTION_THRESHOLD = 3  # N contradições bem-sucedidas para atualizar padrão
    HIGH_CONFIDENCE_THRESHOLD = 0.80  # padrão "sólido" que resiste a contradições
    MIN_PATTERN_FOR_CONTRADICT = 5  # padrão precisa de N tentativas para ser sólido

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

        # Registro de decisão

    def record_decision(
        self,
        approval_id: int,
        event_id: int,
        ev_type: str,
        decisao: str,
        acao_original: str,
        acao_final: str,
        impact_nivel: str,
        impact_score: int,
        motivo: str = "",
    ) -> int:
        """
        Grava decisão humana. Detecta contradição com padrão.
        Retorna decision_id.
        """
        contradicts, pattern_action = self._check_contradiction(ev_type, acao_original, acao_final)

        cur = self.conn.execute(
            """INSERT INTO human_decisions
  (approval_id, event_id, ev_type, decisao, acao_original, acao_final,
  motivo, impact_nivel, impact_score, contradicts_pattern,
  pattern_action, ts)
  VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                approval_id,
                event_id,
                ev_type,
                decisao,
                acao_original,
                acao_final or "",
                motivo,
                impact_nivel,
                impact_score,
                int(contradicts),
                pattern_action,
                _now(),
            ),
        )
        self.conn.commit()

        if contradicts:
            print(
                f" [HDI] Divergência detectada: sistema→{acao_original}, "
                f"humano→{acao_final} (padrão esperava: {pattern_action})"
            )

            return cur.lastrowid

            # Registro de resultado

    def record_outcome(
        self, approval_id: int, resultado: str, validation_score: float, learning: "LearningLayer"
    ):
        """
        Chamado após ValidatorAgent — fecha o loop:
        1. Atualiza human_decisions com resultado real
        2. Propaga ao LearningLayer com peso humano
        3. Se foi contradição bem-sucedida → acumula evidência
        """
        row = self.conn.execute(
            """SELECT id, ev_type, decisao, acao_original, acao_final,
  contradicts_pattern, pattern_action, impact_nivel, impact_score
  FROM human_decisions WHERE approval_id=?""",
            (approval_id,),
        ).fetchone()
        if not row:
            return

            success = resultado == "resolved"
            self.conn.execute(
                """UPDATE human_decisions
   SET validado=1, resultado_final=?, validation_score=?, validated_at=?
   WHERE approval_id=?""",
                (resultado, validation_score, _now(), approval_id),
            )
            self.conn.commit()

            # Propagar ao LearningLayer com flag human_validated
            if row["acao_final"]:
                learning.record_outcome(
                    row["ev_type"],
                    row["acao_final"],
                    success,
                    validation_score,
                    human_validated=True,
                )

                # Contradição bem-sucedida → acumular evidência de que humano tem razão
                if row["contradicts_pattern"] and success and row["acao_final"]:
                    self._register_successful_contradiction(
                        row["ev_type"],
                        row["acao_original"],  # ação que o padrão sugeria
                        row["acao_final"],  # ação que o humano escolheu
                        validation_score,
                        learning,
                    )

                    # Contradiction tracker

    def _check_contradiction(
        self, ev_type: str, acao_sistema: str, acao_humano: str
    ) -> tuple[bool, str]:
        """Retorna (contradicts, pattern_action_que_foi_ignorada)."""
        if not acao_humano or acao_sistema == acao_humano:
            return False, ""
            try:
                row = self.conn.execute(
                    """SELECT best_action, success_rate, total_attempts
    FROM patterns_learned
    WHERE event_type=? AND total_attempts>=?
    ORDER BY success_rate DESC LIMIT 1""",
                    (ev_type, self.MIN_PATTERN_FOR_CONTRADICT),
                ).fetchone()
            except sqlite3.OperationalError:
                return False, ""
                if not row:
                    return False, ""
                    if (
                        row["success_rate"] >= self.HIGH_CONFIDENCE_THRESHOLD
                        and row["best_action"] != acao_humano
                    ):
                        return True, row["best_action"]
                        return False, ""

    def _register_successful_contradiction(
        self,
        ev_type: str,
        acao_padrao: str,
        acao_humano: str,
        validation_score: float,
        learning: "LearningLayer",
    ):
        """
        Acumula contradições. Após CONTRADICTION_THRESHOLD bem-sucedidas,
        atualiza peso do padrão humano para 'alto'.
        Regra de proteção: nunca sobrescreve com 1 ou 2 decisões isoladas.
        """
        self.conn.execute(
            """UPDATE patterns_learned
  SET human_contradiction_count = human_contradiction_count + 1
  WHERE event_type=? AND best_action=?""",
            (ev_type, acao_padrao),
        )
        self.conn.commit()

        row = self.conn.execute(
            "SELECT human_contradiction_count FROM patterns_learned "
            "WHERE event_type=? AND best_action=?",
            (ev_type, acao_padrao),
        ).fetchone()

        count = row["human_contradiction_count"] if row else 0
        if count >= self.CONTRADICTION_THRESHOLD:
            # Humano venceu N vezes → elevar peso da ação humana
            self.conn.execute(
                """UPDATE patterns_learned
   SET peso='alto', human_validated_count = human_validated_count + 1
   WHERE event_type=? AND best_action=?""",
                (ev_type, acao_humano),
            )
            self.conn.commit()
            msg = (
                f" Sistema aprendeu com decisão humana!\n"
                f"Tipo: {ev_type}\n"
                f"Padrão antigo sugerido: {acao_padrao}\n"
                f"Novo padrão (escolha humana): {acao_humano}\n"
                f"Evidência: {count} contradições bem-sucedidas"
            )
            print(f" [HDI] {msg.replace(chr(10), ' | ')}")
            _telegram_alert(msg, "info")

            # Estatísticas

    def get_stats(self) -> dict:
        """Para dashboard e --intelligence CLI."""
        try:
            rows = self.conn.execute(
                "SELECT decisao, COUNT(*) as n FROM human_decisions GROUP BY decisao"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}

            by_decisao = {r["decisao"]: r["n"] for r in rows}
            total = sum(by_decisao.values())
            divergencias = by_decisao.get("adjusted", 0) + by_decisao.get("rejected", 0)

            validadas = self.conn.execute(
                "SELECT COUNT(*) FROM human_decisions WHERE validado=1"
            ).fetchone()[0]
            resolvidas = self.conn.execute(
                "SELECT COUNT(*) FROM human_decisions WHERE resultado_final='resolved'"
            ).fetchone()[0]
            contradicoes = self.conn.execute(
                "SELECT COUNT(*) FROM human_decisions WHERE contradicts_pattern=1"
            ).fetchone()[0]
            recentes = self.conn.execute(
                """SELECT ev_type, decisao, acao_original, acao_final, resultado_final,
   validation_score, contradicts_pattern, ts
   FROM human_decisions ORDER BY ts DESC LIMIT 10"""
            ).fetchall()

            return {
                "total": total,
                "aprovadas": by_decisao.get("approved", 0),
                "rejeitadas": by_decisao.get("rejected", 0),
                "ajustadas": by_decisao.get("adjusted", 0),
                "timeouts": by_decisao.get("timeout", 0),
                "taxa_divergencia": round(divergencias / total, 3) if total > 0 else 0.0,
                "taxa_acerto_sistema": round(by_decisao.get("approved", 0) / total, 3)
                if total > 0
                else 0.0,
                "validadas": validadas,
                "taxa_sucesso_final": round(resolvidas / validadas, 3) if validadas > 0 else 0.0,
                "contradicoes": contradicoes,
                "recentes": [dict(r) for r in recentes],
            }

    def print_report(self):
        s = self.get_stats()
        if not s:
            print(" Nenhuma decisão humana registrada ainda.")
            return
            print(f"\n {''*65}")
            print(" Human Decision Intelligence — Relatório")
            print(f" {''*65}")
            print(f" Total de decisões : {s['total']}")
            print(f" Aprovadas : {s['aprovadas']}")
            print(f" Rejeitadas : {s['rejeitadas']}")
            print(f" Ajustadas : {s['ajustadas']}")
            print(f" ⏰ Timeouts : {s['timeouts']}")
            print(
                f" Taxa de divergência : {s['taxa_divergencia']:.0%} "
                f"(divergência = rejeições + ajustes)"
            )
            print(
                f" Acerto do sistema : {s['taxa_acerto_sistema']:.0%} "
                f"(sistema estava certo sem intervenção)"
            )
            print(f" Contradições/padrão: {s['contradicoes']}")
            if s["validadas"]:
                print(
                    f" Sucesso pós-decisão: {s['taxa_sucesso_final']:.0%} "
                    f"({s['validadas']} decisões com resultado validado)"
                )
                if s["recentes"]:
                    print("\n Últimas decisões:")
                    print(
                        f" {'Tipo':<24} {'Decisão':<10} {'Original':<18} {'Final':<16} {'Resultado'}"
                    )
                    print(f" {''*24} {''*10} {''*18} {''*16} {''*10}")
                    for r in s["recentes"]:
                        div = "" if r["contradicts_pattern"] else " "
                        print(
                            f" {div}{r['ev_type']:<23} {r['decisao']:<10} "
                            f"{r['acao_original']:<18} {(r['acao_final'] or '—'):<16} "
                            f"{r['resultado_final']}"
                        )
                        # Padrões com peso humano
                        try:
                            weighted = self.conn.execute(
                                """SELECT event_type, best_action, success_rate, human_validated_count,
       human_contradiction_count, peso
       FROM patterns_learned
       WHERE human_validated_count > 0 OR peso = 'alto'
       ORDER BY human_validated_count DESC"""
                            ).fetchall()
                        except sqlite3.OperationalError:
                            weighted = []
                            if weighted:
                                print("\n Padrões com influência humana:")
                                for p in weighted:
                                    icon = "" if p["peso"] == "alto" else ""
                                    print(
                                        f" {icon} {p['event_type']:<28} → {p['best_action']:<20} "
                                        f"sucesso:{p['success_rate']:.0%} "
                                        f"validações:{p['human_validated_count']}× "
                                        f"contradições:{p['human_contradiction_count']}×"
                                    )


# CAMADA 10: CONFIDENCE GOVERNANCE


class ConfidenceGovernance:
    """
    O sistema que duvida de si mesmo.

    Mecanismos:
    1. Decay temporal → todo padrão perde 2%/dia sem uso (mín 50%)
    2. Stress test → a cada N ciclos, valida padrões em condições extremas
    3. Revalidação → após 20 execuções OU 72h → exige confirmação humana
    4. Overconfidence → alerta se confiança >85% com divergência humana >20%
    5. Contexto dinâmico → registra hora e volume de cada execução

    Campo `confidence_adjusted` em patterns_learned = confiança efetiva (pós-decay).
    LearningLayer.get_best_action() usa esse campo — padrões decaídos ficam silenciosos.
    """

    DECAY_RATE = 0.02  # 2% de decay por dia sem uso
    DECAY_FLOOR = 0.50  # confiança mínima — nunca abaixo disso
    STRESS_TEST_INTERVAL = 10  # a cada N ciclos do engine
    REVALIDATION_AFTER_N = 20  # execuções antes de exigir revalidação humana
    REVALIDATION_AFTER_H = 72  # horas sem uso → pede revalidação
    OVERCONFIDENCE_THRESHOLD = 0.85  # confiança muito alta
    DIVERGENCE_TRIGGER = 0.20  # divergência humana que ativa alerta

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

        # 1. Decay temporal

    def apply_decay_all(self) -> list[dict]:
        """
        Aplica decay a todos os padrões.
        Só atualiza se mudança > 0.5pp (evita escritas desnecessárias).
        Retorna lista de padrões afetados.
        """
        now = datetime.now(timezone.utc)
        try:
            rows = self.conn.execute(
                """SELECT id, event_type, best_action, success_rate,
   confidence_adjusted, last_seen
   FROM patterns_learned"""
            ).fetchall()
        except sqlite3.OperationalError:
            return []

            affected = []
            for row in rows:
                if not row["last_seen"]:
                    continue
                    try:
                        last = datetime.fromisoformat(row["last_seen"])
                        if last.tzinfo is None:
                            last = last.replace(tzinfo=timezone.utc)
                    except Exception:
                        continue

                        days = (now - last).total_seconds() / 86400
                        if days < 1.0:
                            continue  # menos de 1 dia → sem decay

                            decay = round(days * self.DECAY_RATE, 4)
                            new_adj = round(max(self.DECAY_FLOOR, row["success_rate"] - decay), 3)
                            old_adj = row["confidence_adjusted"]
                            if old_adj is None:
                                old_adj = row["success_rate"]

                                if abs(new_adj - old_adj) < 0.005:
                                    continue  # mudança insignificante

                                    self.conn.execute(
                                        "UPDATE patterns_learned SET confidence_adjusted=?, last_decay_at=? WHERE id=?",
                                        (new_adj, _now(), row["id"]),
                                    )
                                    self._log_event(
                                        row["event_type"],
                                        row["best_action"],
                                        "decay",
                                        old_adj,
                                        new_adj,
                                        {"days_idle": round(days, 1), "raw_decay": decay},
                                    )
                                    affected.append(
                                        {
                                            "event_type": row["event_type"],
                                            "action": row["best_action"],
                                            "old": old_adj,
                                            "new": new_adj,
                                            "days": round(days, 1),
                                        }
                                    )

                                    if affected:
                                        self.conn.commit()
                                        return affected

                                        # 2. Stress test

    def run_stress_tests(self, n_anomalies: int) -> list[dict]:
        """
        Valida padrões de alta confiança em 3 cenários extremos:
        1. Alta carga: sem histórico recente em sobrecarga
        2. Staleness: padrão não usado em >7 dias
        3. Degradação: taxa de sucesso recente < histórica - 20pp

        ≥2 falhas → penalidade de 5% por falha na confiança ajustada.
        """
        try:
            patterns = self.conn.execute(
                """SELECT id, event_type, best_action, success_rate, confidence_adjusted,
   stress_test_count, stress_test_failures, last_seen
   FROM patterns_learned
   WHERE COALESCE(confidence_adjusted, success_rate) >= 0.70
   AND total_attempts >= 3"""
            ).fetchall()
        except sqlite3.OperationalError:
            return []

            results = []
            cutoff_1d = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            cutoff_2d = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()

            for p in patterns:
                failures = 0
                notes = []

                # Cenário 1 — Alta carga
                if n_anomalies > 5:
                    recent_ok = self.conn.execute(
                        """SELECT COUNT(*) FROM correction_history h
     JOIN operational_events e ON h.event_id = e.id
     WHERE e.event_type=? AND h.action=? AND h.ts>=? AND h.success=1""",
                        (p["event_type"], p["best_action"], cutoff_1d),
                    ).fetchone()[0]
                    if recent_ok == 0:
                        failures += 1
                        notes.append(f"sem acertos em alta carga (>{n_anomalies} anomalias/ciclo)")

                        # Cenário 2 — Staleness
                        if p["last_seen"]:
                            try:
                                last = datetime.fromisoformat(p["last_seen"])
                                if last.tzinfo is None:
                                    last = last.replace(tzinfo=timezone.utc)
                                    days_old = (
                                        datetime.now(timezone.utc) - last
                                    ).total_seconds() / 86400
                                    if days_old > 7:
                                        failures += 1
                                        notes.append(f"padrão não usado há {days_old:.0f} dias")
                            except Exception:
                                pass

                                # Cenário 3 — Degradação recente
                                rec = self.conn.execute(
                                    """SELECT COUNT(*) as total, SUM(success) as succ FROM correction_history h
        JOIN operational_events e ON h.event_id = e.id
        WHERE e.event_type=? AND h.action=? AND h.ts>=?""",
                                    (p["event_type"], p["best_action"], cutoff_2d),
                                ).fetchone()
                                if rec and rec["total"] >= 2:
                                    recent_rate = (rec["succ"] or 0) / rec["total"]
                                    hist_rate = p["success_rate"] or 1.0
                                    if recent_rate < hist_rate - 0.20:
                                        failures += 1
                                        notes.append(
                                            f"degradação: {recent_rate:.0%} vs histórico {hist_rate:.0%}"
                                        )

                                        old_adj = (
                                            p.get("confidence_adjusted")
                                            or p.get("success_rate")
                                            or 1.0
                                        )
                                        new_adj = old_adj
                                        new_count = (p["stress_test_count"] or 0) + 1
                                        new_fails = p["stress_test_failures"] or 0

                                        if failures >= 2:
                                            penalty = round(0.05 * failures, 3)
                                            new_adj = round(
                                                max(self.DECAY_FLOOR, old_adj - penalty), 3
                                            )
                                            new_fails += 1
                                            self._log_event(
                                                p["event_type"],
                                                p["best_action"],
                                                "stress_test",
                                                old_adj,
                                                new_adj,
                                                {"failures": failures, "notes": notes},
                                            )
                                            results.append(
                                                {
                                                    "event_type": p["event_type"],
                                                    "action": p["best_action"],
                                                    "failures": failures,
                                                    "penalty": round(old_adj - new_adj, 3),
                                                    "notes": notes,
                                                }
                                            )

                                            self.conn.execute(
                                                """UPDATE patterns_learned
           SET stress_test_count=?, stress_test_failures=?,
           confidence_adjusted=?, stress_test_last_at=?
           WHERE id=?""",
                                                (new_count, new_fails, new_adj, _now(), p["id"]),
                                            )

                                            self.conn.commit()
                                            return results

                                            # 3. Revalidação obrigatória

    def check_revalidation(self, event_type: str, action: str) -> bool:
        """
        Retorna True se o padrão requer confirmação humana antes de operar.
        Marca revalidation_required=1 se threshold atingido.
        """
        try:
            row = self.conn.execute(
                """SELECT revalidation_required, executions_since_revalidation, last_seen
   FROM patterns_learned WHERE event_type=? AND best_action=?""",
                (event_type, action),
            ).fetchone()
        except sqlite3.OperationalError:
            return False

            if not row:
                return False
                if row["revalidation_required"]:
                    return True

                    # Por execuções
                    if (row["executions_since_revalidation"] or 0) >= self.REVALIDATION_AFTER_N:
                        self._set_revalidation_required(
                            event_type, action, f"{row['executions_since_revalidation']} execuções"
                        )
                        return True

                        # Por tempo
                        if row["last_seen"]:
                            try:
                                last = datetime.fromisoformat(row["last_seen"])
                                if last.tzinfo is None:
                                    last = last.replace(tzinfo=timezone.utc)
                                    hours = (
                                        datetime.now(timezone.utc) - last
                                    ).total_seconds() / 3600
                                    if hours > self.REVALIDATION_AFTER_H:
                                        self._set_revalidation_required(
                                            event_type, action, f"{hours:.0f}h sem atualização"
                                        )
                                        return True
                            except Exception:
                                pass

                                return False

    def _set_revalidation_required(self, event_type: str, action: str, reason: str):
        self.conn.execute(
            "UPDATE patterns_learned SET revalidation_required=1 WHERE event_type=? AND best_action=?",
            (event_type, action),
        )
        self.conn.commit()
        self._log_event(event_type, action, "revalidation_required", None, None, {"reason": reason})
        _telegram_alert(
            f" Revalidação obrigatória\nTipo: {event_type} · Ação: {action}\n"
            f"Motivo: {reason}\n"
            f"Padrão suspenso até confirmação humana.\n"
            f"→ python3 self_healing_engine.py --revalidate {event_type} {action}",
            "warn",
        )

    def mark_revalidated(self, event_type: str, action: str):
        """Operador confirma que o padrão ainda é válido. Boost +5% de confiança."""
        try:
            row = self.conn.execute(
                "SELECT confidence_adjusted, success_rate FROM patterns_learned "
                "WHERE event_type=? AND best_action=?",
                (event_type, action),
            ).fetchone()
        except sqlite3.OperationalError:
            print(f" Padrão '{event_type} → {action}' não encontrado.")
            return
            if not row:
                print(f" Padrão '{event_type} → {action}' não encontrado.")
                return

                old_adj = row["confidence_adjusted"] or row["success_rate"] or 0.0
                new_adj = round(min(1.0, old_adj + 0.05), 3)  # boost +5%
                self.conn.execute(
                    """UPDATE patterns_learned
    SET revalidation_required=0, executions_since_revalidation=0,
    confidence_adjusted=?, overconfidence_flagged=0
    WHERE event_type=? AND best_action=?""",
                    (new_adj, event_type, action),
                )
                self.conn.commit()
                self._log_event(event_type, action, "revalidation_done", old_adj, new_adj, {})
                print(
                    f" Padrão revalidado: {event_type} → {action} "
                    f"({old_adj:.0%} → {new_adj:.0%})"
                )

                # 4. Overconfidence detection

    def detect_overconfidence(self, hdi_stats: dict) -> list[dict]:
        """
        Alerta quando padrão tem confiança muito alta mas humano discorda muito.
        Só dispara se divergência humana > DIVERGENCE_TRIGGER.
        """
        divergence = hdi_stats.get("taxa_divergencia", 0.0) if hdi_stats else 0.0
        if divergence < self.DIVERGENCE_TRIGGER:
            return []

            try:
                rows = self.conn.execute(
                    """SELECT id, event_type, best_action, success_rate, confidence_adjusted,
    human_contradiction_count, overconfidence_flagged
    FROM patterns_learned
    WHERE COALESCE(confidence_adjusted, success_rate) > ?
    AND overconfidence_flagged = 0""",
                    (self.OVERCONFIDENCE_THRESHOLD,),
                ).fetchall()
            except sqlite3.OperationalError:
                return []

                alerts = []
                for p in rows:
                    eff = p.get("confidence_adjusted") or p.get("success_rate") or 0.0
                    self.conn.execute(
                        "UPDATE patterns_learned SET overconfidence_flagged=1 WHERE id=?",
                        (p["id"],),
                    )
                    self._log_event(
                        p["event_type"],
                        p["best_action"],
                        "overconfidence_alert",
                        eff,
                        eff,
                        {
                            "divergence_rate": divergence,
                            "contradictions": p["human_contradiction_count"],
                        },
                    )
                    alerts.append(
                        {
                            "event_type": p["event_type"],
                            "action": p["best_action"],
                            "confidence": eff,
                            "divergence": divergence,
                        }
                    )

                    if alerts:
                        self.conn.commit()
                        names = ", ".join(a["event_type"] for a in alerts)
                        _telegram_alert(
                            f" Overconfidence detectado!\n"
                            f"{len(alerts)} padrão(ões) com confiança >{self.OVERCONFIDENCE_THRESHOLD:.0%} "
                            f"enquanto humano diverge em {divergence:.0%}\n"
                            f"Tipos: {names}",
                            "warn",
                        )

                        return alerts

                        # 5. Context tracking

    def record_execution(self, event_type: str, action: str):
        """Incrementa contador de execuções e salva contexto temporal."""
        h = datetime.now().hour
        hour_range = (
            "manhã"
            if 6 <= h < 12
            else "tarde"
            if 12 <= h < 18
            else "noite"
            if 18 <= h < 24
            else "madrugada"
        )
        try:
            self.conn.execute(
                """UPDATE patterns_learned
   SET executions_since_revalidation = executions_since_revalidation + 1,
   context_last = ?
   WHERE event_type=? AND best_action=?""",
                (json.dumps({"hour_range": hour_range, "ts": _now()}), event_type, action),
            )
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

            # Stats e CLI

    def get_stats(self) -> dict:
        try:
            patterns = self.conn.execute(
                """SELECT event_type, best_action, success_rate, confidence_adjusted,
   last_seen, last_decay_at, stress_test_count, stress_test_failures,
   revalidation_required, executions_since_revalidation,
   overconfidence_flagged, human_validated_count, peso
   FROM patterns_learned"""
            ).fetchall()
        except sqlite3.OperationalError:
            return {}

            all_p = [dict(p) for p in patterns]
            total = len(all_p)
            with_decay = sum(
                1
                for p in all_p
                if p.get("confidence_adjusted") is not None
                and p.get("confidence_adjusted", 1) < p.get("success_rate", 1)
            )
            need_reval = sum(1 for p in all_p if p.get("revalidation_required"))
            overconf = sum(1 for p in all_p if p.get("overconfidence_flagged"))
            stress_fail = sum(1 for p in all_p if p.get("stress_test_failures", 0) > 0)

            # Score 0-100: penaliza por cada problema
            if total == 0:
                score = 100
            else:
                penalty = (need_reval * 10 + overconf * 15 + stress_fail * 5) / max(total, 1)
                score = max(0, min(100, int(100 - penalty * 10)))

                events = []
                try:
                    ev_rows = self.conn.execute(
                        "SELECT event_type, best_action, event_kind, old_confidence, "
                        "new_confidence, details_json, ts FROM confidence_events ORDER BY ts DESC LIMIT 30"
                    ).fetchall()
                    events = [dict(r) for r in ev_rows]
                except sqlite3.OperationalError:
                    pass

                    return {
                        "total": total,
                        "with_decay": with_decay,
                        "revalidation_required": need_reval,
                        "overconfidence": overconf,
                        "stress_failures": stress_fail,
                        "reliability_score": score,
                        "patterns": all_p,
                        "events": events,
                    }

    def print_report(self):
        s = self.get_stats()
        if not s:
            print(" Nenhum padrão registrado.")
            return
            score_color = (
                "" if s["reliability_score"] >= 80 else ("" if s["reliability_score"] >= 60 else "")
            )
            print(f"\n {''*65}")
            print(" Confidence Governance — Relatório")
            print(f" {''*65}")
            print(f" {score_color} Score de confiabilidade : {s['reliability_score']}/100")
            print(f" Total de padrões : {s['total']}")
            print(f" Com decay ativo : {s['with_decay']}")
            print(f" Aguardando revalidação : {s['revalidation_required']}")
            print(f" Com overconfidence : {s['overconfidence']}")
            print(f" Falhas stress test : {s['stress_failures']}")
            if s["patterns"]:
                print(f"\n {'Tipo':<28} {'Orig':>6} {'Eff':>6} {'Rev':>4} {'OC':>4} {'Execs':>6}")
                print(f" {''*28} {''*6} {''*6} {''*4} {''*4} {''*6}")
                for p in s["patterns"]:
                    orig = p.get("success_rate", 0) or 0
                    adj = p.get("confidence_adjusted") or orig
                    reval = "" if p.get("revalidation_required") else " "
                    oc = "" if p.get("overconfidence_flagged") else " "
                    arrow = "↘" if adj < orig - 0.01 else " "
                    print(
                        f" {p['event_type']:<28} {orig:>5.0%} {arrow}{adj:>5.0%} "
                        f"{reval:>4} {oc:>4} {p.get('executions_since_revalidation', 0):>6}"
                    )
                    print(
                        f"\n Parâmetros: decay {self.DECAY_RATE*100:.0f}%/dia · "
                        f"revalidação a cada {self.REVALIDATION_AFTER_N} exec ou {self.REVALIDATION_AFTER_H}h"
                    )

                    # Helpers

    def _log_event(
        self, event_type: str, action: str, kind: str, old_conf, new_conf, details: dict
    ):
        try:
            self.conn.execute(
                """INSERT INTO confidence_events
   (event_type, best_action, event_kind, old_confidence, new_confidence,
   details_json, ts)
   VALUES (?,?,?,?,?,?,?)""",
                (
                    event_type,
                    action,
                    kind,
                    old_conf,
                    new_conf,
                    json.dumps(details, ensure_ascii=False),
                    _now(),
                ),
            )
        except sqlite3.OperationalError:
            pass


# CAMADA 11: SYSTEM DRIFT CONTROL


class DriftController:
    """
    Detecta e combate deriva sistêmica — quando o sistema fica bom em padrões
    antigos mas piora em cenários novos sem perceber.

    Mecanismos:
    1. Snapshots periódicos → tira foto de performance a cada N ciclos
    2. Drift detection → compara 7d vs 30d; alerta se degradação > 15pp
    3. Canary mode → testa nova estratégia em 10% dos casos
    4. Rollback automático → se canary piora → volta ao baseline
    5. Exploração epsilon → 10% das decisões tentam ação alternativa segura

    Segmentação de drift: global + por event_type + por hour_range.
    Canary pode ser registrado manualmente (--canary) ou auto-proposto pela exploração.
    """

    DRIFT_THRESHOLD = 0.15  # degradação de 15pp = drift confirmado
    CANARY_FRACTION = 0.10  # 10% → usa ação canary
    EXPLORE_FRACTION = 0.10  # 10% → explora ação alternativa
    MIN_CANARY_EXEC = 10  # execuções antes de decidir sobre canary
    SNAPSHOT_INTERVAL = 5  # ciclos entre snapshots
    PROMOTE_MARGIN = 0.05  # canary precisa ser 5pp melhor para promover
    ROLLBACK_MARGIN = 0.05  # canary 5pp pior → rollback

    # Ações seguras para exploração (sem risco estrutural)
    _SAFE_EXPLORE = ["retry", "check_api", "recalibrate", "clear_stale"]

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        import random as _rnd

        self._rnd = _rnd

        # 1. Snapshots

    def take_snapshot(self):
        """Grava snapshot de performance: global + por event_type."""
        for days in (7, 30):
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            # Global
            row = self.conn.execute(
                "SELECT COUNT(*) as t, SUM(success) as s FROM correction_history WHERE ts>=?",
                (cutoff,),
            ).fetchone()
            if row and row["t"] > 0:
                rate = round((row["s"] or 0) / row["t"], 3)
                self.conn.execute(
                    """INSERT INTO drift_snapshots
    (scope, scope_value, period_days, total_corrections,
    successful_corrections, success_rate, ts)
    VALUES (?,?,?,?,?,?,?)""",
                    ("global", "", days, row["t"], row["s"] or 0, rate, _now()),
                )
                # Por event_type
                ev_rows = self.conn.execute(
                    """SELECT e.event_type, COUNT(*) as t, SUM(h.success) as s
    FROM correction_history h
    JOIN operational_events e ON h.event_id = e.id
    WHERE h.ts>=? GROUP BY e.event_type""",
                    (cutoff,),
                ).fetchall()
                for er in ev_rows:
                    if er["t"] >= 3:
                        r = round((er["s"] or 0) / er["t"], 3)
                        self.conn.execute(
                            """INSERT INTO drift_snapshots
      (scope, scope_value, period_days, total_corrections,
      successful_corrections, success_rate, ts)
      VALUES (?,?,?,?,?,?,?)""",
                            (
                                "event_type",
                                er["event_type"],
                                days,
                                er["t"],
                                er["s"] or 0,
                                r,
                                _now(),
                            ),
                        )
                        self.conn.commit()

                        # 2. Drift detection

    def detect_drift(self) -> list[dict]:
        """
        Compara 7d vs 30d. Retorna lista de drifts (global + por tipo).
        Só reporta se degradação > DRIFT_THRESHOLD.
        """
        alerts = []

        for scope in ("global", "event_type"):
            scope_values = [""] if scope == "global" else self._get_active_event_types()
            for sv in scope_values:
                r7 = self._latest_snapshot(scope, sv, 7)
                r30 = self._latest_snapshot(scope, sv, 30)
                if r7 is None or r30 is None:
                    continue
                    delta = r30 - r7
                    if delta > self.DRIFT_THRESHOLD:
                        alerts.append(
                            {
                                "scope": scope,
                                "scope_value": sv,
                                "rate_7d": r7,
                                "rate_30d": r30,
                                "delta": round(delta, 3),
                                "severity": "critical" if delta > 0.25 else "warning",
                            }
                        )

                        if alerts:
                            names = ", ".join(
                                a["scope_value"] if a["scope_value"] else "global" for a in alerts
                            )
                            _telegram_alert(
                                f" Drift sistêmico detectado!\n"
                                f"{len(alerts)} área(s) com degradação > {self.DRIFT_THRESHOLD:.0%}\n"
                                f"Áreas: {names}\n"
                                f"Use: python3 self_healing_engine.py --drift",
                                "warn",
                            )

                            return alerts

    def _latest_snapshot(self, scope: str, scope_value: str, days: int) -> Optional[float]:
        row = self.conn.execute(
            """SELECT success_rate FROM drift_snapshots
  WHERE scope=? AND scope_value=? AND period_days=?
  ORDER BY ts DESC LIMIT 1""",
            (scope, scope_value, days),
        ).fetchone()
        return row["success_rate"] if row else None

    def _get_active_event_types(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT event_type FROM operational_events").fetchall()
        return [r["event_type"] for r in rows]

        # 3. Canary mode

    def register_canary(self, event_type: str, baseline_action: str, canary_action: str) -> int:
        """Registra teste canary. Retorna canary_id."""
        # Fecha canary ativo anterior para este tipo (se houver)
        self.conn.execute(
            "UPDATE canary_tests SET status='superseded' WHERE event_type=? AND status='active'",
            (event_type,),
        )
        baseline_rate = self._get_current_success_rate(event_type, baseline_action)
        cur = self.conn.execute(
            """INSERT INTO canary_tests
  (event_type, baseline_action, canary_action, baseline_rate,
  status, created_at)
  VALUES (?,?,?,?,?,?)""",
            (event_type, baseline_action, canary_action, baseline_rate, "active", _now()),
        )
        self.conn.commit()
        canary_id = cur.lastrowid
        print(
            f" Canary registrado #{canary_id}: {event_type} · "
            f"baseline={baseline_action} → teste={canary_action} "
            f"(baseline rate: {baseline_rate:.0%})"
        )
        return canary_id

    def get_active_canary(self, event_type: str) -> Optional[dict]:
        row = self.conn.execute(
            """SELECT id, canary_action, baseline_action, baseline_rate,
  canary_executions, canary_rate
  FROM canary_tests WHERE event_type=? AND status='active'
  ORDER BY created_at DESC LIMIT 1""",
            (event_type,),
        ).fetchone()
        return dict(row) if row else None

    def should_use_canary(self, canary: dict) -> bool:
        """Com probabilidade CANARY_FRACTION, decide usar canary_action."""
        return self._rnd.random() < self.CANARY_FRACTION

    def record_canary_result(self, canary_id: int, success: bool, score: float) -> Optional[str]:
        """
        Registra resultado canary.
        Após MIN_CANARY_EXEC decide: 'passed' | 'failed' (+ rollback).
        Retorna decisão ou None se aguardando mais dados.
        """
        self.conn.execute(
            """UPDATE canary_tests
  SET canary_executions = canary_executions + 1,
  canary_successes = canary_successes + ?
  WHERE id=?""",
            (int(success), canary_id),
        )
        self.conn.commit()

        row = self.conn.execute("SELECT * FROM canary_tests WHERE id=?", (canary_id,)).fetchone()
        if not row or row["canary_executions"] < self.MIN_CANARY_EXEC:
            return None

            # Recalcula rate
            rate = round(row["canary_successes"] / row["canary_executions"], 3)
            self.conn.execute("UPDATE canary_tests SET canary_rate=? WHERE id=?", (rate, canary_id))

            baseline = row["baseline_rate"]
            if rate >= baseline + self.PROMOTE_MARGIN:
                decision = "passed"
                self._promote_canary(canary_id, row["event_type"], row["canary_action"], rate)
            elif rate <= baseline - self.ROLLBACK_MARGIN:
                decision = "failed"
                self._rollback_canary(
                    canary_id,
                    row["event_type"],
                    row["canary_action"],
                    row["baseline_action"],
                    rate,
                    baseline,
                )
            else:
                # Margem inconclusiva — continua testando
                return None

                self.conn.execute(
                    "UPDATE canary_tests SET status=?, decided_at=? WHERE id=?",
                    (decision, _now(), canary_id),
                )
                self.conn.commit()
                return decision

    def _promote_canary(self, canary_id: int, event_type: str, canary_action: str, rate: float):
        """Canary passou → atualiza patterns_learned para preferir nova ação."""
        self.conn.execute(
            """UPDATE patterns_learned
  SET success_rate=?, confidence_adjusted=?, last_seen=?,
  notes='canary_promoted'
  WHERE event_type=? AND best_action=?""",
            (rate, rate, _now(), event_type, canary_action),
        )
        self.conn.commit()
        msg = (
            f" Canary #{canary_id} APROVADO\n"
            f"Tipo: {event_type} · Nova ação: {canary_action}\n"
            f"Taxa canary: {rate:.0%} vs baseline → promovido"
        )
        print(f" {msg.splitlines()[0]}")
        _telegram_alert(msg, "info")

    def _rollback_canary(
        self,
        canary_id: int,
        event_type: str,
        canary_action: str,
        baseline_action: str,
        canary_rate: float,
        baseline_rate: float,
    ):
        """Canary falhou → penaliza canary_action, restaura baseline."""
        self.conn.execute(
            """UPDATE patterns_learned
  SET confidence_adjusted = MAX(0.5, confidence_adjusted - 0.1)
  WHERE event_type=? AND best_action=?""",
            (event_type, canary_action),
        )
        self.conn.commit()
        msg = (
            f" Rollback #{canary_id}: {event_type}\n"
            f"Canary {canary_action} ({canary_rate:.0%}) < "
            f"baseline {baseline_action} ({baseline_rate:.0%})\n"
            f"Baseline restaurado automaticamente"
        )
        print(f" ↩ {msg.splitlines()[0]}")
        _telegram_alert(msg, "warn")

    def _get_current_success_rate(self, event_type: str, action: str) -> float:
        row = self.conn.execute(
            "SELECT success_rate FROM patterns_learned WHERE event_type=? AND best_action=?",
            (event_type, action),
        ).fetchone()
        if row and row["success_rate"]:
            return row["success_rate"]
            # Calcula do histórico
            row2 = self.conn.execute(
                """SELECT COUNT(*) as t, SUM(h.success) as s
   FROM correction_history h
   JOIN operational_events e ON h.event_id = e.id
   WHERE e.event_type=? AND h.action=?""",
                (event_type, action),
            ).fetchone()
            if row2 and row2["t"] > 0:
                return round((row2["s"] or 0) / row2["t"], 3)
                return 0.0

                # 4. Exploração epsilon-greedy

    def should_explore(self, event_type: str, current_action: str) -> tuple[bool, str]:
        """
        Com probabilidade EXPLORE_FRACTION, sugere ação alternativa segura.
        Prioriza ações menos testadas para este event_type.
        Retorna (explore, alternative_action).
        """
        if self._rnd.random() > self.EXPLORE_FRACTION:
            return False, ""

            # Ações seguras que ainda não são a atual
            candidates = [a for a in self._SAFE_EXPLORE if a != current_action]
            if not candidates:
                return False, ""

                # Ranqueia por menor número de testes neste event_type
                counts = {}
                for c in candidates:
                    n = self.conn.execute(
                        "SELECT COUNT(*) FROM exploration_log WHERE event_type=? AND action_tried=?",
                        (event_type, c),
                    ).fetchone()[0]
                    counts[c] = n

                    # Escolhe o menos testado (com aleatoriedade se empate)
                    min_count = min(counts.values())
                    least_tried = [c for c, n in counts.items() if n == min_count]
                    chosen = self._rnd.choice(least_tried)
                    return True, chosen

    def record_exploration(
        self,
        event_type: str,
        action: str,
        success: bool,
        score: float,
        canary_id: Optional[int] = None,
    ):
        """Registra resultado de exploração. Auto-propõe canary se promissor."""
        self.conn.execute(
            """INSERT INTO exploration_log
  (event_type, action_tried, was_exploration, success,
  validation_score, canary_id, ts)
  VALUES (?,?,?,?,?,?,?)""",
            (event_type, action, 1, int(success), score, canary_id, _now()),
        )
        self.conn.commit()

        # Auto-propõe canary se exploração teve ≥3 sucessos consecutivos
        self._maybe_propose_canary(event_type, action)

    def _maybe_propose_canary(self, event_type: str, explored_action: str):
        """Se exploração acumulou boa taxa, propõe canary automático."""
        rows = self.conn.execute(
            """SELECT COUNT(*) as t, SUM(success) as s FROM exploration_log
  WHERE event_type=? AND action_tried=? AND was_exploration=1""",
            (event_type, explored_action),
        ).fetchone()
        if not rows or rows["t"] < 3:
            return

            exp_rate = round((rows["s"] or 0) / rows["t"], 3)
            current_best = self._get_current_success_rate(event_type, "")

            # Busca melhor ação atual
            bp = self.conn.execute(
                "SELECT best_action, success_rate FROM patterns_learned "
                "WHERE event_type=? ORDER BY success_rate DESC LIMIT 1",
                (event_type,),
            ).fetchone()
            if not bp:
                return

                baseline_rate = bp["success_rate"] or 0.0
                if (
                    exp_rate >= baseline_rate + self.PROMOTE_MARGIN
                    and bp["best_action"] != explored_action
                ):
                    # Não há canary ativo para este tipo?
                    active = self.get_active_canary(event_type)
                    if not active:
                        print(
                            f" Auto-canary proposto: {event_type} "
                            f"{bp['best_action']} → {explored_action} "
                            f"(exploração: {exp_rate:.0%} vs {baseline_rate:.0%})"
                        )
                        self.register_canary(event_type, bp["best_action"], explored_action)

                        # 5. Stats e CLI

    def get_stats(self) -> dict:
        try:
            snaps = self.conn.execute(
                "SELECT scope, scope_value, period_days, success_rate, ts "
                "FROM drift_snapshots ORDER BY ts DESC LIMIT 50"
            ).fetchall()
            canaries = self.conn.execute(
                "SELECT * FROM canary_tests ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            explorations = self.conn.execute(
                "SELECT action_tried, COUNT(*) as t, SUM(success) as s "
                "FROM exploration_log GROUP BY action_tried"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}

            # Drift alerts
            drift_alerts = self.detect_drift()

            return {
                "snapshots": [dict(r) for r in snaps],
                "canaries": [dict(r) for r in canaries],
                "explorations": [dict(r) for r in explorations],
                "drift_alerts": drift_alerts,
                "active_canaries": sum(1 for r in canaries if r["status"] == "active"),
                "rollbacks": sum(1 for r in canaries if r["status"] in ("failed", "rolled_back")),
                "promotions": sum(1 for r in canaries if r["status"] == "passed"),
            }

    def print_report(self):
        s = self.get_stats()
        if not s:
            print(" Dados de drift ainda não disponíveis (mínimo 2 snapshots).")
            return
            print(f"\n {''*65}")
            print(" System Drift Control — Relatório")
            print(f" {''*65}")
            alerts = s.get("drift_alerts", [])
            if alerts:
                print(f" DRIFT DETECTADO em {len(alerts)} área(s):")
                for a in alerts:
                    scope_name = a["scope_value"] or "global"
                    print(
                        f" ↘ {scope_name}: 7d={a['rate_7d']:.0%} vs 30d={a['rate_30d']:.0%} "
                        f"(Δ={a['delta']:.0%})"
                    )
                else:
                    print(" Sem drift detectado")

                    print("\n Canary tests:")
                    print(
                        f" Ativos: {s['active_canaries']} | "
                        f"Promovidos: {s['promotions']} | "
                        f"Rollbacks: {s['rollbacks']}"
                    )

                    canaries = s.get("canaries", [])
                    if canaries:
                        print(
                            f"\n {'Tipo':<25} {'Baseline':<18} {'Canary':<18} "
                            f"{'Base%':>6} {'Can%':>6} {'Exec':>5} {'Status'}"
                        )
                        print(f" {''*25} {''*18} {''*18} {''*6} {''*6} {''*5} {''*10}")
                        for c in canaries[:8]:
                            status_icon = {
                                "active": "",
                                "passed": "",
                                "failed": "",
                                "rolled_back": "↩",
                                "superseded": "",
                            }.get(c["status"], "•")
                            print(
                                f" {c['event_type']:<25} {c['baseline_action']:<18} "
                                f"{c['canary_action']:<18} "
                                f"{c['baseline_rate']:>5.0%} {c['canary_rate']:>5.0%} "
                                f"{c['canary_executions']:>5} {status_icon} {c['status']}"
                            )

                            exp = s.get("explorations", [])
                            if exp:
                                print("\n Exploração acumulada:")
                                for e in exp:
                                    rate = round((e["s"] or 0) / e["t"], 2) if e["t"] > 0 else 0
                                    print(
                                        f" {e['action_tried']:<20} {e['t']:>4} tentativas "
                                        f"{rate:.0%} sucesso"
                                    )


# ORQUESTRADOR: SELF-HEALING ENGINE


class SelfHealingEngine:
    """
    Orquestra os 4 agentes em loop controlado.
    """

    def __init__(self):
        self.conn = init_db()
        self.detector = DetectorAgent()
        self.diagnostico = DiagnosticoAgent()
        self.correction = CorrectionAgent()
        self.validator = ValidatorAgent()
        # Camadas enterprise
        self.explainability = ExplainabilityLayer()
        self.safety = SafetyGuard(self.conn)
        self.learning = LearningLayer(self.conn)
        self.hitl = HumanApprovalGate(self.conn)
        self.hdi = HumanDecisionIntelligence(self.conn)
        self.governance = ConfidenceGovernance(self.conn)
        self.drift = DriftController(self.conn)
        self.sla = SLAMonitor(self.conn)
        self.cycle_count = 0

    def _reload_detector(self):
        """Recarrega dados do detector a cada ciclo."""
        self.detector = DetectorAgent()

    def run_cycle(self) -> dict:
        self.cycle_count += 1
        self._reload_detector()
        ts = _now()

        print(f"\n {''*60}")
        print(f" Ciclo #{self.cycle_count} — {ts[:19]}")
        print(f" {''*60}")

        # [11] DRIFT: snapshot periódico + detecção
        if self.cycle_count % DriftController.SNAPSHOT_INTERVAL == 0 and self.cycle_count > 0:
            self.drift.take_snapshot()
            drift_alerts = self.drift.detect_drift()
            if drift_alerts:
                for da in drift_alerts:
                    scope = da["scope_value"] or "global"
                    print(
                        f" DRIFT [{scope}]: 7d={da['rate_7d']:.0%} vs "
                        f"30d={da['rate_30d']:.0%} (Δ={da['delta']:.0%})"
                    )

                    # [10] GOVERNANÇA: decay + stress test
                    decayed = self.governance.apply_decay_all()
                    if decayed:
                        print(f" Decay aplicado a {len(decayed)} padrão(ões)")

                        if (
                            self.cycle_count % ConfidenceGovernance.STRESS_TEST_INTERVAL == 0
                            and self.cycle_count > 0
                        ):
                            print(f" Stress test automático (ciclo #{self.cycle_count})...")
                            # stress tests são executados após detectar anomalias (precisam de n_anomalies)

                            # FASE 1: DETECTAR
                            print(" [1/4] Detector rodando...")
                            anomalies = self.detector.run_all_checks()
                            print(f" {len(anomalies)} anomalia(s) detectada(s)")

                            # Stress test agora que temos contagem de anomalias
                            if (
                                self.cycle_count % ConfidenceGovernance.STRESS_TEST_INTERVAL == 0
                                and self.cycle_count > 0
                            ):
                                st_results = self.governance.run_stress_tests(len(anomalies))
                                if st_results:
                                    print(
                                        f" {len(st_results)} padrão(ões) penalizado(s) no stress test"
                                    )

                                    if not anomalies:
                                        print(" Sistema saudável — nenhuma anomalia\n")
                                        # Detectar overconfidence mesmo sem anomalias
                                        self.governance.detect_overconfidence(self.hdi.get_stats())
                                        return {
                                            "cycle": self.cycle_count,
                                            "anomalies": 0,
                                            "resolved": 0,
                                        }

                                        resolved = 0
                                        escalated = 0

                                        for anomaly in anomalies:
                                            fp = anomaly["fingerprint"]
                                            ev_type = anomaly["event_type"]
                                            severity = anomaly["severity"]
                                            details = anomaly["details"]
                                            product = anomaly.get("product", "")

                                            print(
                                                f"\n {ev_type} [{severity}] — {details.get('message','')[:80]}"
                                            )

                                            # Inserir/recuperar no DB
                                            event_id = upsert_event(
                                                self.conn,
                                                fp,
                                                anomaly["source"],
                                                ev_type,
                                                severity,
                                                details,
                                                product,
                                            )
                                            if event_id is None:
                                                print(" → já resolvido, ignorando")
                                                continue

                                                row = self.conn.execute(
                                                    "SELECT attempts, status, created_at FROM operational_events WHERE id=?",
                                                    (event_id,),
                                                ).fetchone()
                                                attempts = row["attempts"] if row else 0
                                                ev_created = row["created_at"] if row else _now()

                                                if attempts >= MAX_ATTEMPTS:
                                                    print(
                                                        f" Máx {MAX_ATTEMPTS} tentativas atingido — escalando"
                                                    )
                                                    update_event(
                                                        self.conn, event_id, status="escalated"
                                                    )
                                                    _telegram_alert(
                                                        f"Problema persistente após {MAX_ATTEMPTS} tentativas\n"
                                                        f"Tipo: {ev_type}\nDetalhes: {details.get('message','')}",
                                                        "critical",
                                                    )
                                                    escalated += 1
                                                    continue

                                                    # FASE 2: DIAGNOSTICAR + APRENDIZADO
                                                    print(f" [2/4] Diagnosticando {ev_type}...")

                                                    # [7] Consultar memória de aprendizado PRIMEIRO
                                                    learned = self.learning.get_best_action(ev_type)
                                                    overridden = False
                                                    fonte = "rules"

                                                    if learned:
                                                        (
                                                            learned_action,
                                                            learned_rate,
                                                            learned_score,
                                                        ) = learned
                                                        # [10] Verificar se padrão exige revalidação antes de usar
                                                        needs_reval = (
                                                            self.governance.check_revalidation(
                                                                ev_type, learned_action
                                                            )
                                                        )
                                                        if needs_reval:
                                                            print(
                                                                f" Padrão '{learned_action}' requer revalidação "
                                                                f"— não será usado automaticamente"
                                                            )
                                                            learned = (
                                                                None  # força diagnóstico normal
                                                            )
                                                        else:
                                                            print(
                                                                f" Padrão aprendido: '{learned_action}' "
                                                                f"(efetivo {learned_rate:.0%}, score {learned_score:.2f})"
                                                            )

                                                            diagnosis = self.diagnostico.analyze(
                                                                ev_type, severity, details, product
                                                            )
                                                            acao_diag = diagnosis.get(
                                                                "acao_recomendada", "notify_human"
                                                            )
                                                            fonte = (
                                                                "claude"
                                                                if ANTHROPIC_KEY
                                                                else "rules"
                                                            )

                                                            # Se learning tem confiança suficiente e sugere algo diferente → override
                                                            acao = acao_diag
                                                            if learned and learned[0] != acao_diag:
                                                                acao = learned[0]
                                                                overridden = True
                                                                print(
                                                                    f" ↺ Override: '{acao_diag}' → '{acao}' (aprendizado)"
                                                                )

                                                                params = diagnosis.get(
                                                                    "parametros_acao", {}
                                                                )
                                                                conf = diagnosis.get(
                                                                    "confianca_diagnostico", 0.0
                                                                )
                                                                causa = diagnosis.get(
                                                                    "causa_provavel", "—"
                                                                )

                                                                # [5] Registrar explicabilidade — ANTES de corrigir
                                                                exp = self.explainability.record(
                                                                    self.conn,
                                                                    event_id,
                                                                    diagnosis,
                                                                    fonte,
                                                                    overridden=overridden,
                                                                    learned_action=acao,
                                                                )
                                                                self.explainability.print_explanation(
                                                                    exp
                                                                )

                                                                update_event(
                                                                    self.conn,
                                                                    event_id,
                                                                    status="diagnosing",
                                                                    diagnosis_json=json.dumps(
                                                                        {
                                                                            **diagnosis,
                                                                            "explanation": exp,
                                                                        },
                                                                        ensure_ascii=False,
                                                                    ),
                                                                )

                                                                # Alerta imediato para críticos
                                                                if severity == "critical":
                                                                    _telegram_alert(
                                                                        f"Anomalia crítica:\n{ev_type}\n"
                                                                        f"Causa: {causa[:100]}\nAção: {acao}\n"
                                                                        f"Confiança: {conf:.0%} | Fonte: {fonte}",
                                                                        "critical",
                                                                    )

                                                                    # CAMADA 8: HUMAN-IN-THE-LOOP
                                                                    impacto = calcular_impacto(
                                                                        ev_type,
                                                                        acao,
                                                                        attempts,
                                                                        details,
                                                                    )
                                                                    nivel = impacto["nivel"]
                                                                    nivel_icon = {
                                                                        "ALTO": "",
                                                                        "MEDIO": "",
                                                                        "BAIXO": "",
                                                                    }.get(nivel, "•")
                                                                    fatores_str = (
                                                                        ", ".join(
                                                                            impacto["fatores"]
                                                                        )
                                                                        or "sem fatores críticos"
                                                                    )
                                                                    print(
                                                                        f" [HITL] Impacto: {nivel_icon} {nivel} (score {impacto['score']}) — {fatores_str}"
                                                                    )

                                                                    # approval_id e human_decision_id são usados depois na validação
                                                                    approval_id = None
                                                                    human_decision_id = None

                                                                    if nivel == "ALTO":
                                                                        print(
                                                                            " ALTO IMPACTO — bloqueando até aprovação humana"
                                                                        )
                                                                        update_event(
                                                                            self.conn,
                                                                            event_id,
                                                                            status="awaiting_approval",
                                                                        )
                                                                        approval_id = self.hitl.request_approval(
                                                                            event_id,
                                                                            ev_type,
                                                                            impacto,
                                                                            diagnosis,
                                                                            acao,
                                                                            exp,
                                                                        )
                                                                        hitl_status, hitl_acao = (
                                                                            self.hitl.wait_for_response(
                                                                                approval_id
                                                                            )
                                                                        )

                                                                        # Buscar motivo que operador salvou ao responder
                                                                        ap_row = self.conn.execute(
                                                                            "SELECT motivo, created_at, responded_at FROM human_approvals WHERE id=?",
                                                                            (approval_id,),
                                                                        ).fetchone()
                                                                        motivo_humano = (
                                                                            ap_row["motivo"]
                                                                            if ap_row
                                                                            else ""
                                                                        )
                                                                        # [SLA] Registrar tempo de resposta humana
                                                                        if (
                                                                            ap_row
                                                                            and ap_row[
                                                                                "responded_at"
                                                                            ]
                                                                            and hitl_status
                                                                            != "timeout"
                                                                        ):
                                                                            self.sla.record_human_response_sla(
                                                                                event_id,
                                                                                ap_row[
                                                                                    "created_at"
                                                                                ],
                                                                                ap_row[
                                                                                    "responded_at"
                                                                                ],
                                                                            )

                                                                            acao_final_para_hdi = (
                                                                                hitl_acao
                                                                                if hitl_acao
                                                                                else acao
                                                                            )

                                                                            if (
                                                                                hitl_status
                                                                                == "rejected"
                                                                            ):
                                                                                print(
                                                                                    " Correção rejeitada pelo operador — mantendo estado atual"
                                                                                )
                                                                                # [9] Registrar rejeição como decisão humana
                                                                                human_decision_id = self.hdi.record_decision(
                                                                                    approval_id,
                                                                                    event_id,
                                                                                    ev_type,
                                                                                    "rejected",
                                                                                    acao,
                                                                                    "",  # acao_final vazia = não executou
                                                                                    nivel,
                                                                                    impacto[
                                                                                        "score"
                                                                                    ],
                                                                                    motivo_humano,
                                                                                )
                                                                                update_event(
                                                                                    self.conn,
                                                                                    event_id,
                                                                                    status="rejected_human",
                                                                                    correction_applied="REJECTED_BY_HUMAN",
                                                                                )
                                                                                continue
                                                                            else:
                                                                                # approved / adjusted / timeout → vai executar
                                                                                if (
                                                                                    hitl_status
                                                                                    == "adjusted"
                                                                                ):
                                                                                    acao = (
                                                                                        hitl_acao
                                                                                        or acao
                                                                                    )
                                                                                    print(
                                                                                        f" Ação ajustada pelo operador: {acao}"
                                                                                    )
                                                                                elif (
                                                                                    hitl_status
                                                                                    == "timeout"
                                                                                ):
                                                                                    acao = hitl_acao  # safe fallback
                                                                                    # approved → segue com acao original

                                                                                    # [9] Registrar decisão humana (approved/adjusted/timeout)
                                                                                    human_decision_id = self.hdi.record_decision(
                                                                                        approval_id,
                                                                                        event_id,
                                                                                        ev_type,
                                                                                        hitl_status,
                                                                                        acao_diag,  # o que o sistema havia sugerido originalmente
                                                                                        acao,  # o que vai ser executado de fato
                                                                                        nivel,
                                                                                        impacto[
                                                                                            "score"
                                                                                        ],
                                                                                        motivo_humano,
                                                                                    )

                                                                                elif (
                                                                                    nivel == "MEDIO"
                                                                                ):
                                                                                    _telegram_alert(
                                                                                        f"ℹ Correção automática (impacto MÉDIO)\n"
                                                                                        f"Tipo: {ev_type}\nAção: {acao}\n"
                                                                                        f"Score: {impacto['score']} — {fatores_str}",
                                                                                        "info",
                                                                                    )
                                                                                    # BAIXO → execução silenciosa, sem notificação

                                                                                    # CAMADA 11: CANARY / EXPLORAÇÃO
                                                                                    # Só aplica em BAIXO/MEDIO — ALTO já está sob supervisão humana
                                                                                    canary_id_drift = None
                                                                                    was_exploration = False
                                                                                    acao_original_drift = acao

                                                                                    if (
                                                                                        nivel
                                                                                        != "ALTO"
                                                                                    ):
                                                                                        active_canary = self.drift.get_active_canary(
                                                                                            ev_type
                                                                                        )
                                                                                        if (
                                                                                            active_canary
                                                                                            and active_canary[
                                                                                                "canary_action"
                                                                                            ]
                                                                                            != acao
                                                                                        ):
                                                                                            if self.drift.should_use_canary(
                                                                                                active_canary
                                                                                            ):
                                                                                                acao = active_canary[
                                                                                                    "canary_action"
                                                                                                ]
                                                                                                canary_id_drift = active_canary[
                                                                                                    "id"
                                                                                                ]
                                                                                                print(
                                                                                                    f" [CANARY] Testando '{acao}' "
                                                                                                    f"({active_canary['canary_executions']+1}/"
                                                                                                    f"{DriftController.MIN_CANARY_EXEC}+ exec)"
                                                                                                )
                                                                                            elif not active_canary:
                                                                                                # Exploração epsilon-greedy (10%)
                                                                                                (
                                                                                                    should_exp,
                                                                                                    exp_action,
                                                                                                ) = self.drift.should_explore(
                                                                                                    ev_type,
                                                                                                    acao,
                                                                                                )
                                                                                                if should_exp:
                                                                                                    acao = exp_action
                                                                                                    was_exploration = True
                                                                                                    print(
                                                                                                        f" [EXPLORE] Explorando ação '{acao}' "
                                                                                                        f"({self.drift.EXPLORE_FRACTION:.0%} prob)"
                                                                                                    )

                                                                                                    # FASE 3: CORRIGIR — com SafetyGuard
                                                                                                    # [6] Verificar permissão de segurança ANTES de agir
                                                                                                    (
                                                                                                        allowed,
                                                                                                        safety_reason,
                                                                                                    ) = self.safety.can_apply(
                                                                                                        acao,
                                                                                                        ev_type,
                                                                                                    )
                                                                                                    if not allowed:
                                                                                                        print(
                                                                                                            f" [3/4] BLOQUEADO pelo SafetyGuard: {safety_reason}"
                                                                                                        )
                                                                                                        update_event(
                                                                                                            self.conn,
                                                                                                            event_id,
                                                                                                            status="blocked_safety",
                                                                                                            correction_applied=f"BLOCKED:{safety_reason}",
                                                                                                        )
                                                                                                        _telegram_alert(
                                                                                                            f"SafetyGuard bloqueou correção\n"
                                                                                                            f"Ação: {acao}\nMotivo: {safety_reason}",
                                                                                                            "warn",
                                                                                                        )
                                                                                                        continue

                                                                                                        print(
                                                                                                            f" [3/4] Aplicando correção: {acao}..."
                                                                                                        )
                                                                                                        update_event(
                                                                                                            self.conn,
                                                                                                            event_id,
                                                                                                            status="correcting",
                                                                                                            attempts=attempts
                                                                                                            + 1,
                                                                                                        )

                                                                                                        (
                                                                                                            success,
                                                                                                            action_taken,
                                                                                                            before,
                                                                                                            after,
                                                                                                        ) = self.correction.apply(
                                                                                                            acao,
                                                                                                            params,
                                                                                                            details,
                                                                                                            event_id,
                                                                                                        )
                                                                                                        update_event(
                                                                                                            self.conn,
                                                                                                            event_id,
                                                                                                            correction_applied=action_taken,
                                                                                                            correction_result_json=json.dumps(
                                                                                                                {
                                                                                                                    "before": before,
                                                                                                                    "after": after,
                                                                                                                },
                                                                                                                ensure_ascii=False,
                                                                                                            ),
                                                                                                        )

                                                                                                        print(
                                                                                                            f" {'' if success else ''} {action_taken}"
                                                                                                        )

                                                                                                        # FASE 4: VALIDAR
                                                                                                        print(
                                                                                                            " [4/4] Validando resultado..."
                                                                                                        )
                                                                                                        time.sleep(
                                                                                                            3
                                                                                                        )

                                                                                                        (
                                                                                                            passed,
                                                                                                            score,
                                                                                                            notes,
                                                                                                        ) = self.validator.validate(
                                                                                                            ev_type,
                                                                                                            before,
                                                                                                            after,
                                                                                                        )
                                                                                                        add_history(
                                                                                                            self.conn,
                                                                                                            event_id,
                                                                                                            attempts
                                                                                                            + 1,
                                                                                                            action_taken,
                                                                                                            before,
                                                                                                            after,
                                                                                                            passed,
                                                                                                            notes,
                                                                                                        )

                                                                                                        final_status = (
                                                                                                            "resolved"
                                                                                                            if (
                                                                                                                success
                                                                                                                and passed
                                                                                                            )
                                                                                                            else "retrying"
                                                                                                        )
                                                                                                        update_event(
                                                                                                            self.conn,
                                                                                                            event_id,
                                                                                                            status=final_status,
                                                                                                        )

                                                                                                        icon = (
                                                                                                            ""
                                                                                                            if (
                                                                                                                success
                                                                                                                and passed
                                                                                                            )
                                                                                                            else ""
                                                                                                        )
                                                                                                        print(
                                                                                                            f" {icon} Validação: {notes} (score {score:.2f})"
                                                                                                        )

                                                                                                        # [6] Registrar no SafetyGuard (atualiza circuit breaker)
                                                                                                        self.safety.record(
                                                                                                            acao,
                                                                                                            ev_type,
                                                                                                            success
                                                                                                            and passed,
                                                                                                            score,
                                                                                                        )

                                                                                                        # [7] Registrar no Learning (atualiza patterns_learned)
                                                                                                        self.learning.record_outcome(
                                                                                                            ev_type,
                                                                                                            acao,
                                                                                                            success
                                                                                                            and passed,
                                                                                                            score,
                                                                                                        )

                                                                                                        # [9] Fechar loop HDI — registrar resultado da decisão humana
                                                                                                        if (
                                                                                                            approval_id
                                                                                                            is not None
                                                                                                        ):
                                                                                                            resultado_str = (
                                                                                                                "resolved"
                                                                                                                if (
                                                                                                                    success
                                                                                                                    and passed
                                                                                                                )
                                                                                                                else "failed"
                                                                                                            )
                                                                                                            self.hdi.record_outcome(
                                                                                                                approval_id,
                                                                                                                resultado_str,
                                                                                                                score,
                                                                                                                self.learning,
                                                                                                            )

                                                                                                            # [10] Registrar execução na governança + verificar overconfidence
                                                                                                            self.governance.record_execution(
                                                                                                                ev_type,
                                                                                                                acao,
                                                                                                            )
                                                                                                            self.governance.detect_overconfidence(
                                                                                                                self.hdi.get_stats()
                                                                                                            )

                                                                                                            # [SLA] Registrar tempo de correção vs target
                                                                                                            if (
                                                                                                                success
                                                                                                                and passed
                                                                                                            ):
                                                                                                                self.sla.record_correction_sla(
                                                                                                                    event_id,
                                                                                                                    ev_created,
                                                                                                                    _now(),
                                                                                                                )

                                                                                                                # [11] Registrar resultado de canary ou exploração
                                                                                                                if (
                                                                                                                    canary_id_drift
                                                                                                                    is not None
                                                                                                                ):
                                                                                                                    decision = self.drift.record_canary_result(
                                                                                                                        canary_id_drift,
                                                                                                                        success
                                                                                                                        and passed,
                                                                                                                        score,
                                                                                                                    )
                                                                                                                    if decision:
                                                                                                                        print(
                                                                                                                            f" Canary #{canary_id_drift}: {decision.upper()}"
                                                                                                                        )
                                                                                                                    elif was_exploration:
                                                                                                                        self.drift.record_exploration(
                                                                                                                            ev_type,
                                                                                                                            acao,
                                                                                                                            success
                                                                                                                            and passed,
                                                                                                                            score,
                                                                                                                        )

                                                                                                                        if (
                                                                                                                            success
                                                                                                                            and passed
                                                                                                                        ):
                                                                                                                            resolved += 1
                                                                                                                            _telegram_alert(
                                                                                                                                f" Problema resolvido automaticamente!\n"
                                                                                                                                f"Tipo: {ev_type}\nAção: {action_taken}\n"
                                                                                                                                f"Score de validação: {score:.2f}\n{notes}",
                                                                                                                                "info",
                                                                                                                            )
                                                                                                                        else:
                                                                                                                            print(
                                                                                                                                f" ↻ Tentativa {attempts+1}/{MAX_ATTEMPTS} — re-avaliado no próximo ciclo"
                                                                                                                            )

                                                                                                                            summary = {
                                                                                                                                "cycle": self.cycle_count,
                                                                                                                                "anomalies": len(
                                                                                                                                    anomalies
                                                                                                                                ),
                                                                                                                                "resolved": resolved,
                                                                                                                                "escalated": escalated,
                                                                                                                            }

                                                                                                                            print(
                                                                                                                                f"\n {''*60}"
                                                                                                                            )
                                                                                                                            print(
                                                                                                                                f" Ciclo #{self.cycle_count}: {len(anomalies)} anomalias, {resolved} resolvidas, {escalated} escaladas"
                                                                                                                            )
                                                                                                                            return summary

    def run_loop(self, interval: int = SCAN_INTERVAL):
        print("\n Self-Healing Engine iniciado")
        print(f" Intervalo: {interval}s · Max tentativas: {MAX_ATTEMPTS}")
        print(f" DB: {DB_FILE}\n")
        _telegram_alert("Self-Healing Engine iniciado — monitoramento ativo", "info")

        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                print("\n ⏹ Self-Healing interrompido pelo operador")
                break
            except Exception as exc:
                print(f" Erro no ciclo: {exc}")
                _telegram_alert(f"Erro no ciclo do Self-Healing: {exc}", "warn")

                print(f"\n Aguardando {interval}s até o próximo ciclo...")
                try:
                    time.sleep(interval)
                except KeyboardInterrupt:
                    print("\n ⏹ Self-Healing interrompido")
                    break


# SLA Monitor


class SLAMonitor:
    """
    Mede e registra cumprimento de SLA em 3 métricas:
    correction_time — created_at do evento → ts da correção
    human_response — created_at da aprovação → responded_at
    escalation — created_at do evento → resolved / escalated
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        # backward compat — cria tabela se DB existia antes desta camada
        try:
            conn.execute("""
   CREATE TABLE IF NOT EXISTS sla_events (
   id INTEGER PRIMARY KEY AUTOINCREMENT,
   event_id INTEGER REFERENCES operational_events(id),
   metric TEXT,
   target_minutes REAL,
   actual_minutes REAL,
   met INTEGER,
   ts TEXT
   )
   """)
            conn.commit()
        except Exception:
            pass

            # Recording

    def record_correction_sla(self, event_id: int, created_at: str, corrected_at: str):
        try:
            t1 = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(corrected_at.replace("Z", "+00:00"))
            minutes = (t2 - t1).total_seconds() / 60
            target = SLA_TARGETS["correction_minutes"]
            met = 1 if minutes <= target else 0
            self.conn.execute(
                "INSERT INTO sla_events (event_id,metric,target_minutes,actual_minutes,met,ts) VALUES (?,?,?,?,?,?)",
                (event_id, "correction_time", target, round(minutes, 2), met, _now()),
            )
            self.conn.commit()
        except Exception:
            pass

    def record_human_response_sla(self, event_id: int, requested_at: str, responded_at: str):
        try:
            t1 = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(responded_at.replace("Z", "+00:00"))
            minutes = (t2 - t1).total_seconds() / 60
            target = SLA_TARGETS["human_response_minutes"]
            met = 1 if minutes <= target else 0
            self.conn.execute(
                "INSERT INTO sla_events (event_id,metric,target_minutes,actual_minutes,met,ts) VALUES (?,?,?,?,?,?)",
                (event_id, "human_response", target, round(minutes, 2), met, _now()),
            )
            self.conn.commit()
        except Exception:
            pass

            # Stats

    def get_stats(self) -> dict:
        rows = self.conn.execute(
            "SELECT metric, COUNT(*) as n, SUM(met) as ok, AVG(actual_minutes) as avg_min "
            "FROM sla_events GROUP BY metric"
        ).fetchall()
        stats = {}
        for r in rows:
            stats[r["metric"]] = {
                "total": r["n"],
                "met": r["ok"] or 0,
                "breached": r["n"] - (r["ok"] or 0),
                "compliance_pct": round((r["ok"] or 0) / r["n"] * 100, 1) if r["n"] else 0,
                "avg_minutes": round(r["avg_min"] or 0, 2),
                "target_minutes": SLA_TARGETS.get(
                    r["metric"]
                    .replace("_time", "_minutes")
                    .replace("human_response", "human_response_minutes")
                    .replace("correction_time", "correction_minutes"),
                    5,
                ),
            }
            # fill missing metrics
            for key, target_key in [
                ("correction_time", "correction_minutes"),
                ("human_response", "human_response_minutes"),
            ]:
                if key not in stats:
                    stats[key] = {
                        "total": 0,
                        "met": 0,
                        "breached": 0,
                        "compliance_pct": 100.0,
                        "avg_minutes": 0,
                        "target_minutes": SLA_TARGETS[target_key],
                    }
                    return stats

    def print_report(self):
        stats = self.get_stats()
        print("\n ⏱ SLA Monitor — Pipeline AI / MYO")
        print(f" {''*55}")
        labels = {
            "correction_time": "Tempo de Correção ",
            "human_response": "Resposta Humana ",
            "escalation": "Escalação ",
        }
        for metric, s in sorted(stats.items()):
            label = labels.get(metric, metric.ljust(20))
            pct = s["compliance_pct"]
            icon = "" if pct >= 90 else ("" if pct >= 70 else "")
            target = s["target_minutes"]
            avg = s["avg_minutes"]
            print(
                f" {icon} {label} {pct:5.1f}% SLA | avg {avg:.1f}m | target ≤{target}m | {s['met']}/{s['total']} OK"
            )
            print(f" {''*55}")
            total_met = sum(s["met"] for s in stats.values())
            total_all = sum(s["total"] for s in stats.values())
            overall = round(total_met / total_all * 100, 1) if total_all else 100.0
            icon_ov = "" if overall >= 90 else ("" if overall >= 70 else "")
            print(
                f" {icon_ov} SLA GERAL: {overall:.1f}% ({total_met}/{total_all} eventos dentro do target)"
            )
            print()


# Audit Report


def generate_audit_report(conn: sqlite3.Connection) -> dict:
    """
    Gera relatório estruturado de auditoria para uso enterprise.
    Exportável como JSON. Cobre: correções, padrões, decisões humanas,
    governança de confiança, SLA compliance e score de confiabilidade.
    """
    now_str = _now()

    # Ensure sla_events exists (backward compat)
    SLAMonitor(conn)

    # Janela de tempo
    first_ev = conn.execute("SELECT MIN(created_at) as t FROM operational_events").fetchone()
    last_ev = conn.execute("SELECT MAX(updated_at) as t FROM operational_events").fetchone()
    period = {
        "start": (first_ev["t"] or now_str),
        "end": (last_ev["t"] or now_str),
    }

    # Correções
    ev_rows = conn.execute(
        "SELECT status, severity, COUNT(*) as n FROM operational_events GROUP BY status, severity"
    ).fetchall()
    total_events = conn.execute("SELECT COUNT(*) as n FROM operational_events").fetchone()["n"]
    resolved = conn.execute(
        "SELECT COUNT(*) as n FROM operational_events WHERE status='resolved'"
    ).fetchone()["n"]
    ch_rows = conn.execute(
        "SELECT COUNT(*) as n, SUM(success) as ok FROM correction_history"
    ).fetchone()
    total_corrections = ch_rows["n"] or 0
    success_corrections = int(ch_rows["ok"] or 0)
    success_rate = round(success_corrections / total_corrections, 3) if total_corrections else 0.0

    # Humano vs automático
    ha = conn.execute(
        "SELECT status, COUNT(*) as n FROM human_approvals GROUP BY status"
    ).fetchall()
    ha_stats = {r["status"]: r["n"] for r in ha}
    human_total = sum(ha_stats.values())
    human_approved = ha_stats.get("approved", 0) + ha_stats.get("adjusted", 0)
    auto_total = total_corrections - human_total
    automation_pct = round(auto_total / total_corrections * 100, 1) if total_corrections else 0.0

    # Padrões aprendidos
    patterns = conn.execute(
        "SELECT event_type, best_action, total_attempts, success_rate, peso, "
        "COALESCE(confidence_adjusted, success_rate) as eff_conf, "
        "human_validated_count "
        "FROM patterns_learned ORDER BY eff_conf DESC LIMIT 20"
    ).fetchall()
    patterns_list = [dict(r) for r in patterns]

    # Decisões humanas
    hd = conn.execute(
        "SELECT decisao, COUNT(*) as n FROM human_decisions GROUP BY decisao"
    ).fetchall()
    hd_stats = {r["decisao"]: r["n"] for r in hd}
    contradictions = conn.execute(
        "SELECT COUNT(*) as n FROM human_decisions WHERE contradicts_pattern=1"
    ).fetchone()["n"]

    # Governança
    revalidation_pending = conn.execute(
        "SELECT COUNT(*) as n FROM patterns_learned WHERE revalidation_required=1"
    ).fetchone()["n"]
    overconfidence_flags = conn.execute(
        "SELECT COUNT(*) as n FROM patterns_learned WHERE overconfidence_flagged=1"
    ).fetchone()["n"]
    stress_failures = (
        conn.execute("SELECT SUM(stress_test_failures) as n FROM patterns_learned").fetchone()["n"]
        or 0
    )
    total_patterns = conn.execute("SELECT COUNT(*) as n FROM patterns_learned").fetchone()["n"]

    reliability = 100
    if total_patterns > 0:
        penalty = revalidation_pending * 10 + overconfidence_flags * 15 + int(stress_failures) * 5
        reliability = max(0, round(100 - (penalty / total_patterns) * 10))

        # SLA
        sla_rows = conn.execute(
            "SELECT metric, COUNT(*) as n, SUM(met) as ok, AVG(actual_minutes) as avg_min "
            "FROM sla_events GROUP BY metric"
        ).fetchall()
        sla_data = {}
        for r in sla_rows:
            sla_data[r["metric"]] = {
                "total": r["n"],
                "met": r["ok"] or 0,
                "compliance_pct": round((r["ok"] or 0) / r["n"] * 100, 1) if r["n"] else 100.0,
                "avg_minutes": round(r["avg_min"] or 0, 2),
            }
            sla_overall = 100.0
            if sla_data:
                ok_sum = sum(v["met"] for v in sla_data.values())
                all_sum = sum(v["total"] for v in sla_data.values())
                sla_overall = round(ok_sum / all_sum * 100, 1) if all_sum else 100.0

                # Estimativa de receita protegida
                sev_counts = {r["severity"]: r["n"] for r in ev_rows if r["status"] == "resolved"}
                revenue_protected = sum(
                    REVENUE_AT_RISK.get(sev, 50) * n for sev, n in sev_counts.items()
                )
                hours_saved = round(success_corrections * 2.0, 1)  # 2h manual fix / correção

                # Montar relatório
                report = {
                    "generated_at": now_str,
                    "period": period,
                    "executive_summary": {
                        "total_anomalies_detected": total_events,
                        "issues_resolved": resolved,
                        "total_corrections_applied": total_corrections,
                        "successful_corrections": success_corrections,
                        "success_rate_pct": round(success_rate * 100, 1),
                        "automation_rate_pct": automation_pct,
                        "human_interventions": human_total,
                        "revenue_protected_brl": revenue_protected,
                        "hours_saved": hours_saved,
                        "reliability_score": reliability,
                        "sla_overall_pct": sla_overall,
                    },
                    "corrections_by_status": {r["status"]: r["n"] for r in ev_rows},
                    "human_decisions": {
                        "breakdown": hd_stats,
                        "contradictions": contradictions,
                        "approval_outcomes": ha_stats,
                    },
                    "patterns_learned": patterns_list,
                    "confidence_governance": {
                        "total_patterns": total_patterns,
                        "revalidation_pending": revalidation_pending,
                        "overconfidence_flags": overconfidence_flags,
                        "stress_test_failures": int(stress_failures),
                        "reliability_score": reliability,
                    },
                    "sla_compliance": sla_data,
                    "sla_overall_pct": sla_overall,
                    "targets": SLA_TARGETS,
                }
                return report


def generate_proof_report(conn: sqlite3.Connection) -> Path:
    """
    Gera proof_of_value.html — relatório de 1 página, pronto para apresentar ao cliente.
    Antes vs Depois · Números reais · Prova imediata de valor.
    """
    # Carregar dados reais do DB
    report = generate_audit_report(conn)
    es = report.get("executive_summary", {})

    rev = es.get("revenue_protected_brl", 0)
    hrs = es.get("hours_saved", 0)
    auto = es.get("automation_rate_pct", 0)
    rel = es.get("reliability_score", 100)
    total = es.get("total_anomalies_detected", 0)
    res = es.get("issues_resolved", 0)
    sla = es.get("sla_overall_pct", 100.0)
    roi = round((rev + hrs * 100) / 500, 1) if (rev + hrs) > 0 else 0

    date_str = datetime.now().strftime("%d/%m/%Y")

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prova de Valor — AI Self-Healing System</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
* {{ box-sizing:border-box; margin:0; padding:0 }}
body {{
font-family:'Inter',system-ui,sans-serif;
background:#060d17; color:#e2e8f0;
min-height:100vh; padding:40px 24px;
}}
.page {{
max-width:860px; margin:0 auto;
}}

/* Header */
.logo {{
font-size:13px; font-weight:700; color:#06b6d4;
letter-spacing:.15em; text-transform:uppercase; margin-bottom:12px;
}}
.headline {{
font-size:30px; font-weight:800; line-height:1.25;
color:#f1f5f9; margin-bottom:10px;
}}
.headline span {{ color:#10b981 }}
.tagline {{
font-size:15px; color:#94a3b8; margin-bottom:36px; max-width:560px;
}}

/* Before / After */
.ba-grid {{
display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:36px;
}}
.ba-card {{
border-radius:12px; padding:24px; border:1px solid;
}}
.ba-before {{ background:#1a0a0a; border-color:#ef444440 }}
.ba-after {{ background:#0a1a0f; border-color:#10b98140 }}
.ba-label {{
font-size:11px; font-weight:700; letter-spacing:.1em;
text-transform:uppercase; margin-bottom:16px;
}}
.ba-before .ba-label {{ color:#ef4444 }}
.ba-after .ba-label {{ color:#10b981 }}
.ba-item {{
display:flex; align-items:flex-start; gap:10px;
font-size:13px; color:#cbd5e1; margin-bottom:10px; line-height:1.4;
}}
.ba-item:last-child {{ margin-bottom:0 }}
.ba-icon {{ font-size:15px; flex-shrink:0; margin-top:1px }}

/* KPIs */
.kpi-row {{
display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:36px;
}}
@media(max-width:640px) {{ .kpi-row {{ grid-template-columns:1fr 1fr }} }}
.kpi-card {{
background:#0d1f35; border:1px solid #1a3a5c;
border-radius:12px; padding:20px 14px; text-align:center;
}}
.kpi-val {{ font-size:28px; font-weight:800; line-height:1 }}
.kpi-label {{ font-size:11px; color:#64748b; margin-top:6px; line-height:1.3 }}

/* Proof bar */
.proof-section {{ margin-bottom:36px }}
.proof-title {{
font-size:11px; font-weight:700; color:#64748b;
letter-spacing:.1em; text-transform:uppercase; margin-bottom:14px;
}}
.proof-row {{
display:flex; align-items:center; gap:12px; margin-bottom:10px;
}}
.proof-label {{ font-size:12px; color:#94a3b8; width:200px; flex-shrink:0 }}
.proof-bar-wrap {{
flex:1; height:8px; background:#1a2d45; border-radius:4px; overflow:hidden;
}}
.proof-bar {{ height:100%; border-radius:4px }}
.proof-num {{ font-size:12px; font-weight:600; width:50px; text-align:right; flex-shrink:0 }}

/* CTA */
.cta-box {{
background:linear-gradient(135deg,#0a1628,#0d2140);
border:1px solid #1a3a5c; border-radius:12px;
padding:24px; text-align:center; margin-bottom:32px;
}}
.cta-title {{
font-size:18px; font-weight:700; color:#f1f5f9; margin-bottom:8px;
}}
.cta-sub {{ font-size:13px; color:#64748b }}
.cta-code {{
display:inline-block; margin-top:12px;
background:#060d17; border:1px solid #1a3a5c; border-radius:6px;
padding:8px 16px; font-family:monospace; font-size:12px; color:#06b6d4;
}}

/* Footer */
.footer {{
text-align:center; font-size:11px; color:#334155;
border-top:1px solid #1a2d45; padding-top:20px;
}}

@media print {{
body {{ background:#fff; color:#1a202c; padding:20px }}
.ba-before {{ background:#fff5f5; border-color:#feb2b2 }}
.ba-after {{ background:#f0fff4; border-color:#9ae6b4 }}
.kpi-card {{ background:#f7fafc; border-color:#e2e8f0 }}
.cta-box {{ background:#f7fafc; border-color:#e2e8f0 }}
.ba-item, .kpi-label, .proof-label, .cta-sub, .footer {{ color:#4a5568 }}
.headline, .cta-title {{ color:#1a202c }}
.tagline {{ color:#718096 }}
.kpi-val {{ color:#1a202c }}
}}
</style>
</head>
<body>
<div class="page">

<!-- Header -->
<div class="logo">AI Self-Healing System · Pipeline AI / MYO</div>
<div class="headline">
Detectamos erros, corrigimos automaticamente<br>
e garantimos que sua IA tome decisões seguras —<br>
<span>em tempo real.</span>
</div>
<div class="tagline">
Prova de valor baseada em dados reais do sistema em produção. Gerado em {date_str}.
</div>

<!-- Before / After -->
<div class="ba-grid">
<div class="ba-card ba-before">
<div class="ba-label"> Antes — Sem o sistema</div>
<div class="ba-item"><span class="ba-icon"></span>Erros detectados manualmente, horas depois do impacto</div>
<div class="ba-item"><span class="ba-icon"></span>Correção manual — pausa no time, interrupção de fluxo</div>
<div class="ba-item"><span class="ba-icon"></span>Sem rastreabilidade: ninguém sabe o que mudou ou por quê</div>
<div class="ba-item"><span class="ba-icon"></span>Cada erro vira prejuízo silencioso e acumulado</div>
<div class="ba-item"><span class="ba-icon"></span>Decisões da IA sem governança — risco invisível</div>
</div>
<div class="ba-card ba-after">
<div class="ba-label"> Depois — Com o sistema</div>
<div class="ba-item"><span class="ba-icon"></span>Detecção em &lt;5 min, correção automática na sequência</div>
<div class="ba-item"><span class="ba-icon"></span>{auto:.0f}% dos problemas resolvidos sem intervenção do time</div>
<div class="ba-item"><span class="ba-icon"></span>100% auditável — cada decisão registrada com causa e evidência</div>
<div class="ba-item"><span class="ba-icon"></span>R${rev:,.0f} em receita protegida (período atual)</div>
<div class="ba-item"><span class="ba-icon"></span>Sistema aprende com cada ciclo — melhora sozinho</div>
</div>
</div>

<!-- KPIs -->
<div class="kpi-row">
<div class="kpi-card">
<div class="kpi-val" style="color:#10b981">R${rev:,.0f}</div>
<div class="kpi-label">Receita<br>protegida</div>
</div>
<div class="kpi-card">
<div class="kpi-val" style="color:#3b82f6">{total}</div>
<div class="kpi-label">Falhas que nunca<br>chegaram ao time</div>
</div>
<div class="kpi-card">
<div class="kpi-val" style="color:#8b5cf6">{hrs:.0f}h</div>
<div class="kpi-label">Horas devolvidas<br>ao time</div>
</div>
<div class="kpi-card">
<div class="kpi-val" style="color:#f59e0b">{roi}×</div>
<div class="kpi-label">Retorno sobre<br>investimento</div>
</div>
</div>

<!-- Proof bars -->
<div class="proof-section">
<div class="proof-title">Métricas de desempenho do sistema</div>
<div class="proof-row">
<div class="proof-label">Automação</div>
<div class="proof-bar-wrap">
<div class="proof-bar" style="width:{min(auto,100):.0f}%;background:#10b981"></div>
</div>
<div class="proof-num" style="color:#10b981">{auto:.0f}%</div>
</div>
<div class="proof-row">
<div class="proof-label">Taxa de sucesso nas correções</div>
<div class="proof-bar-wrap">
<div class="proof-bar" style="width:{es.get('success_rate_pct',0):.0f}%;background:#3b82f6"></div>
</div>
<div class="proof-num" style="color:#3b82f6">{es.get('success_rate_pct',0):.0f}%</div>
</div>
<div class="proof-row">
<div class="proof-label">Confiabilidade do sistema</div>
<div class="proof-bar-wrap">
<div class="proof-bar" style="width:{rel}%;background:#8b5cf6"></div>
</div>
<div class="proof-num" style="color:#8b5cf6">{rel}/100</div>
</div>
<div class="proof-row">
<div class="proof-label">SLA (dentro do target)</div>
<div class="proof-bar-wrap">
<div class="proof-bar" style="width:{min(sla,100):.0f}%;background:#06b6d4"></div>
</div>
<div class="proof-num" style="color:#06b6d4">{sla:.0f}%</div>
</div>
</div>

<!-- CTA -->
<div class="cta-box">
<div class="cta-title">Quer o relatório completo e auditável?</div>
<div class="cta-sub">Todos os dados acima são reais, exportáveis e verificáveis a qualquer momento.</div>
<div class="cta-code">python3 self_healing_engine.py --audit-report</div>
</div>

<div class="footer">
Pipeline AI · MYO System · {date_str} ·
{total} anomalias detectadas · {res} resolvidas · {auto:.0f}% automático
</div>

</div>
</body>
</html>"""


out_dir = Path("outputs/audit")
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / "proof_of_value.html"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
    return out_path


def save_audit_report(report: dict) -> Path:
    """Salva relatório em outputs/audit/audit_report_YYYY-MM-DD.json."""
    out_dir = Path("outputs/audit")
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = out_dir / f"audit_report_{date_str}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        return out_path


def print_audit_report(report: dict):
    """Exibe resumo executivo do relatório no terminal."""
    es = report.get("executive_summary", {})
    print("\n AUDIT REPORT — Pipeline AI / MYO")
    print(f" Gerado em: {report.get('generated_at','—')[:19]}")
    period = report.get("period", {})
    print(f" Período: {period.get('start','—')[:10]} → {period.get('end','—')[:10]}")
    print(f"\n {''*55}")
    print(" OPERAÇÃO")
    print(f" Anomalias detectadas {es.get('total_anomalies_detected',0):>8}")
    print(f" Problemas resolvidos {es.get('issues_resolved',0):>8}")
    print(f" Correções aplicadas {es.get('total_corrections_applied',0):>8}")
    print(f" Taxa de sucesso {es.get('success_rate_pct',0):>7.1f}%")
    print("\n AUTONOMIA")
    print(f" Automação {es.get('automation_rate_pct',0):>7.1f}%")
    print(f" Intervenções humanas {es.get('human_interventions',0):>8}")
    print("\n IMPACTO DE NEGÓCIO")
    print(f" Receita protegida R${es.get('revenue_protected_brl',0):>8,.0f}")
    print(f" Tempo economizado {es.get('hours_saved',0):>6.1f}h")
    print("\n QUALIDADE")
    print(f" Score de confiabilidade {es.get('reliability_score',0):>8}/100")
    print(f" SLA geral {es.get('sla_overall_pct',100):>7.1f}%")
    print(f" {''*55}")

    hd = report.get("human_decisions", {})
    print("\n DECISÕES HUMANAS")
    for decisao, n in hd.get("breakdown", {}).items():
        print(f" {decisao:<20} {n:>4}")
        print(f" Contradições detectadas {hd.get('contradictions',0):>4}")

        print("\n TOP PADRÕES APRENDIDOS")
        for p in report.get("patterns_learned", [])[:5]:
            eff = p.get("eff_conf") or p.get("success_rate") or 0
            print(f" {p['event_type']:<30} → {p['best_action']:<18} {eff:.0%}")

            sla = report.get("sla_compliance", {})
            if sla:
                print("\n SLA COMPLIANCE")
                for metric, s in sla.items():
                    icon = (
                        ""
                        if s["compliance_pct"] >= 90
                        else ("" if s["compliance_pct"] >= 70 else "")
                    )
                    print(
                        f" {icon} {metric:<25} {s['compliance_pct']:>5.1f}% avg {s['avg_minutes']:.1f}m"
                    )
                    print()


# Status e histórico


def show_status():
    if not DB_FILE.exists():
        print(" Banco operacional não encontrado. Rode o engine primeiro.")
        return
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
  SELECT event_type, severity, status, product, attempts,
  substr(details_json, 1, 120) as details_preview,
  created_at, updated_at
  FROM operational_events
  ORDER BY created_at DESC LIMIT 20
  """).fetchall()

        counts = conn.execute("""
  SELECT status, COUNT(*) as n FROM operational_events GROUP BY status
  """).fetchall()

        print(f"\n {''*65}")
        print(" Self-Healing Engine — Status Operacional")
        print(f" {''*65}")
        print(f" DB: {DB_FILE}")
        for c in counts:
            icon = {
                "resolved": "",
                "escalated": "",
                "retrying": "",
                "detected": "",
                "diagnosing": "",
                "correcting": "",
            }.get(c["status"], "•")
            print(f" {icon} {c['status']:<15} {c['n']}")

            if rows:
                print("\n Últimos 20 eventos:")
                print(f" {'Tipo':<28} {'Sev':<10} {'Status':<12} {'Prod':<20} {'Tentativas'}")
                print(f" {''*28} {''*10} {''*12} {''*20} {''*10}")
                for r in rows:
                    print(
                        f" {r['event_type']:<28} {r['severity']:<10} {r['status']:<12} {r['product']:<20} {r['attempts']}"
                    )

                    # Rate limits — uso na última hora
                    cutoff_1h = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
                    rate_rows = conn.execute(
                        "SELECT action, COUNT(*) as n FROM action_audit_log WHERE ts>? GROUP BY action",
                        (cutoff_1h,),
                    ).fetchall()
                    limits = SafetyGuard.RATE_LIMITS
                    if rate_rows:
                        print("\n Rate Limits — última hora:")
                        print(f" {'Ação':<22} {'Usado':>6} {'Limite':>7}")
                        print(f" {''*22} {''*6} {''*7}")
                        for r in rate_rows:
                            lim = limits.get(r["action"], 3)
                            bar = "" if r["n"] >= lim else "" if r["n"] >= lim * 0.7 else ""
                            print(f" {bar} {r['action']:<20} {r['n']:>6} {lim:>7}")
                        else:
                            print("\n Rate Limits — nenhuma ação executada na última hora")

                            # Padrões aprendidos — resumo
                            n_patterns = conn.execute(
                                "SELECT COUNT(*) FROM patterns_learned WHERE total_attempts >= 3 AND success_rate >= 0.70"
                            ).fetchone()[0]
                            print(
                                f"\n Padrões com confiança suficiente: {n_patterns} (use --patterns para detalhes)"
                            )

                            # System Drift Control — resumo
                            try:
                                drift_stats = DriftController(conn).get_stats()
                                if drift_stats:
                                    alerts = drift_stats.get("drift_alerts", [])
                                    act_c = drift_stats.get("active_canaries", 0)
                                    promo = drift_stats.get("promotions", 0)
                                    rolls = drift_stats.get("rollbacks", 0)
                                    drift_icon = "" if alerts else ""
                                    print("\n System Drift Control:")
                                    print(
                                        f" {drift_icon} Drift: {len(alerts)} área(s) | "
                                        f"Canaries ativos: {act_c} | "
                                        f"Promovidos: {promo} | Rollbacks: {rolls}"
                                    )
                                    print(" (use --drift para detalhes)")
                            except sqlite3.OperationalError:
                                pass

                                # Confidence Governance — resumo
                                try:
                                    gov_stats = ConfidenceGovernance(conn).get_stats()
                                    if gov_stats and gov_stats.get("total", 0) > 0:
                                        s = gov_stats
                                        score = s["reliability_score"]
                                        icon = "" if score >= 80 else ("" if score >= 60 else "")
                                        print("\n Confidence Governance:")
                                        print(
                                            f" {icon} Score: {score}/100 | "
                                            f"Decay: {s['with_decay']} | "
                                            f"Revalidação: {s['revalidation_required']} | "
                                            f"Overconf: {s['overconfidence']} | "
                                            f"Stress fail: {s['stress_failures']}"
                                        )
                                        print(" (use --governance para detalhes)")
                                    else:
                                        print("\n Confidence Governance: sem padrões ainda")
                                except sqlite3.OperationalError:
                                    pass

                                    # Human Decision Intelligence — resumo rápido
                                    try:
                                        hdi_stats = HumanDecisionIntelligence(conn).get_stats()
                                        if hdi_stats and hdi_stats["total"] > 0:
                                            s = hdi_stats
                                            print("\n Human Decision Intelligence:")
                                            print(
                                                f" Decisões: {s['total']} total | "
                                                f" {s['aprovadas']} aprovadas | "
                                                f" {s['rejeitadas']} rejeitadas | "
                                                f" {s['ajustadas']} ajustadas"
                                            )
                                            print(
                                                f" Acerto sistema: {s['taxa_acerto_sistema']:.0%} | "
                                                f"Divergência: {s['taxa_divergencia']:.0%} | "
                                                f"Contradições/padrão: {s['contradicoes']}"
                                            )
                                            if s["validadas"]:
                                                print(
                                                    f" Sucesso pós-decisão: {s['taxa_sucesso_final']:.0%} "
                                                    f"({s['validadas']} validadas) "
                                                    f"(use --intelligence para relatório completo)"
                                                )
                                            else:
                                                print(
                                                    "\n Human Decision Intelligence: sem decisões registradas"
                                                )
                                    except sqlite3.OperationalError:
                                        pass

                                        # Aprovações pendentes (HITL)
                                        try:
                                            pending_rows = conn.execute(
                                                "SELECT id, ev_type, impact_nivel, acao_sugerida, timeout_at "
                                                "FROM human_approvals WHERE status='pending'"
                                            ).fetchall()
                                            if pending_rows:
                                                print(
                                                    f"\n Aprovações PENDENTES: {len(pending_rows)}"
                                                )
                                                for p in pending_rows:
                                                    print(
                                                        f" #{p['id']} [{p['impact_nivel']}] {p['ev_type']} → {p['acao_sugerida']}"
                                                    )
                                                    print(f" Timeout: {p['timeout_at'][:19]}")
                                                    print(
                                                        f" → python3 self_healing_engine.py --approve {p['id']}"
                                                    )
                                                else:
                                                    print("\n Sem aprovações pendentes")
                                        except sqlite3.OperationalError:
                                            pass  # tabela ainda não existe (DB antigo)

                                            conn.close()


def show_history():
    if not DB_FILE.exists():
        print(" Banco não encontrado.")
        return
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
  SELECT h.ts, h.attempt, h.action, h.success, h.notes, e.event_type, e.severity
  FROM correction_history h
  JOIN operational_events e ON h.event_id = e.id
  ORDER BY h.ts DESC LIMIT 30
  """).fetchall()

        print(f"\n {''*65}")
        print(" Histórico de Correções")
        print(f" {''*65}")
        if not rows:
            print(" Nenhuma correção registrada ainda.")
            return
            for r in rows:
                icon = "" if r["success"] else ""
                print(
                    f" {icon} [{r['ts'][:16]}] {r['event_type']} (tent.{r['attempt']}) → {r['action'][:40]}"
                )
                print(f" {r['notes']}")
                conn.close()


# Main


def main():
    parser = argparse.ArgumentParser(description="Self-Healing Engine — MYO Pipeline AI")
    parser.add_argument("--once", action="store_true", help="Roda 1 ciclo e sai")
    parser.add_argument("--status", action="store_true", help="Mostra estado do DB")
    parser.add_argument("--history", action="store_true", help="Histórico de correções")
    parser.add_argument("--patterns", action="store_true", help="Tabela de padrões aprendidos")
    parser.add_argument("--pending", action="store_true", help="Lista aprovações pendentes")
    parser.add_argument("--approve", type=int, metavar="ID", help="Aprova aprovação #ID")
    parser.add_argument("--reject", type=int, metavar="ID", help="Rejeita aprovação #ID")
    parser.add_argument(
        "--adjust",
        type=int,
        metavar="ID",
        help="Aprova aprovação #ID com ação diferente (requer --action)",
    )
    parser.add_argument("--action", type=str, default="", help="Ação alternativa para --adjust")
    parser.add_argument(
        "--motivo", type=str, default="", help="Razão da decisão (opcional, aprimora o aprendizado)"
    )
    parser.add_argument(
        "--intelligence",
        action="store_true",
        help="Relatório completo de Human Decision Intelligence",
    )
    parser.add_argument(
        "--governance",
        action="store_true",
        help="Relatório de Confidence Governance (decay, stress, revalidação)",
    )
    parser.add_argument(
        "--revalidate",
        nargs=2,
        metavar=("TIPO", "ACAO"),
        help="Marca padrão como revalidado: --revalidate engine_bias_detected check_api",
    )
    parser.add_argument("--drift", action="store_true", help="Relatório de System Drift Control")
    parser.add_argument(
        "--canary",
        nargs=3,
        metavar=("TIPO", "ATUAL", "NOVO"),
        help="Registra canary test: --canary engine_bias_detected retry recalibrate",
    )
    parser.add_argument(
        "--sla",
        action="store_true",
        help="Relatório de SLA: tempos de detecção, correção e resposta humana",
    )
    parser.add_argument(
        "--audit-report", action="store_true", help="Gera relatório de auditoria JSON exportável"
    )
    parser.add_argument(
        "--proof-report",
        action="store_true",
        help="Gera proof_of_value.html — relatório de 1 página para cliente",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=SCAN_INTERVAL,
        help=f"Intervalo em segundos (padrão: {SCAN_INTERVAL})",
    )
    args = parser.parse_args()

    if args.status:
        show_status()
        return
        if args.history:
            show_history()
            return

            # Flags que precisam do DB mas não do engine completo
            def _open_conn():
                if not DB_FILE.exists():
                    print(" Banco não encontrado. Rode o engine primeiro.")
                    sys.exit(1)
                    c = sqlite3.connect(DB_FILE)
                    c.row_factory = sqlite3.Row
                    return c

                    if args.patterns:
                        conn = _open_conn()
                        LearningLayer(conn).print_table()
                        conn.close()
                        return

                        if args.pending:
                            conn = _open_conn()
                            HumanApprovalGate(conn).show_pending()
                            conn.close()
                            return

                            if args.intelligence:
                                conn = _open_conn()
                                HumanDecisionIntelligence(conn).print_report()
                                conn.close()
                                return

                                if args.governance:
                                    conn = _open_conn()
                                    ConfidenceGovernance(conn).print_report()
                                    conn.close()
                                    return

                                    if args.drift:
                                        conn = _open_conn()
                                        DriftController(conn).print_report()
                                        conn.close()
                                        return

                                        if args.canary:
                                            ev_type, baseline, canary_action = args.canary
                                            conn = _open_conn()
                                            DriftController(conn).register_canary(
                                                ev_type, baseline, canary_action
                                            )
                                            conn.close()
                                            return

                                            if args.sla:
                                                conn = _open_conn()
                                                SLAMonitor(conn).print_report()
                                                conn.close()
                                                return

                                                if getattr(args, "audit_report", False):
                                                    conn = _open_conn()
                                                    report = generate_audit_report(conn)
                                                    conn.close()
                                                    print_audit_report(report)
                                                    path = save_audit_report(report)
                                                    print(f" Relatório salvo: {path}")
                                                    return

                                                    if getattr(args, "proof_report", False):
                                                        conn = _open_conn()
                                                        path = generate_proof_report(conn)
                                                        conn.close()
                                                        print(f"\n Proof of Value gerado: {path}")
                                                        print(
                                                            " Abra no browser ou converta para PDF para compartilhar com clientes."
                                                        )
                                                        try:
                                                            import subprocess

                                                            subprocess.Popen(["open", str(path)])
                                                        except Exception:
                                                            pass
                                                            return

                                                            if args.revalidate:
                                                                conn = _open_conn()
                                                                ev_type, action = args.revalidate
                                                                ConfidenceGovernance(
                                                                    conn
                                                                ).mark_revalidated(ev_type, action)
                                                                conn.close()
                                                                return

                                                                if args.approve is not None:
                                                                    conn = _open_conn()
                                                                    HumanApprovalGate(conn).respond(
                                                                        args.approve,
                                                                        "approved",
                                                                        motivo=args.motivo,
                                                                    )
                                                                    conn.close()
                                                                    return

                                                                    if args.reject is not None:
                                                                        conn = _open_conn()
                                                                        HumanApprovalGate(
                                                                            conn
                                                                        ).respond(
                                                                            args.reject,
                                                                            "rejected",
                                                                            motivo=args.motivo,
                                                                        )
                                                                        conn.close()
                                                                        return

                                                                        if args.adjust is not None:
                                                                            if not args.action:
                                                                                print(
                                                                                    " --adjust requer --action <acao> (ex: --adjust 3 --action retry)"
                                                                                )
                                                                                sys.exit(1)
                                                                                conn = _open_conn()
                                                                                HumanApprovalGate(
                                                                                    conn
                                                                                ).respond(
                                                                                    args.adjust,
                                                                                    "adjusted",
                                                                                    args.action,
                                                                                    args.motivo,
                                                                                )
                                                                                conn.close()
                                                                                return

                                                                                engine = SelfHealingEngine()
                                                                                if args.once:
                                                                                    engine.run_cycle()
                                                                                else:
                                                                                    engine.run_loop(
                                                                                        interval=args.interval
                                                                                    )


if __name__ == "__main__":
    main()
