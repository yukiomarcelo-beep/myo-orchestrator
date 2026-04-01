"""
Trust Feedback Engine — Pipeline AI
Lê trust_metrics.json e gera alertas e recomendações de ajuste controladas.

Níveis de ação:
 OBSERVE → registra padrão sem sugerir mudança
 RECOMMEND → sugere ajuste de threshold, prompt ou fonte
 ENFORCE → (não implementado) aplicaria mudança automaticamente

Volumes mínimos para agir:
 MIN_EVENTS_FOR_LEARNING = 20 (total de eventos)
 MIN_TOPIC_EVENTS = 8 (por tópico)
 MIN_ENGINE_EVENTS = 10 (por engine)
 MIN_SOURCE_APPEARANCES = 5 (por tipo de fonte)
 MIN_CLAIM_RECURRENCE = 3 (aparições para watchlist)

Saída:
 outputs/trust/feedback_report.json
 outputs/trust/feedback_report.md
"""
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

TRUST_DIR = Path("outputs/trust")
METRICS_FILE = TRUST_DIR / "trust_metrics.json"
FEEDBACK_JSON = TRUST_DIR / "feedback_report.json"
FEEDBACK_MD = TRUST_DIR / "feedback_report.md"

# Thresholds de volume (sem volume suficiente, não age) 

MIN_EVENTS_FOR_LEARNING = 20
MIN_TOPIC_EVENTS = 8
MIN_ENGINE_EVENTS = 10
MIN_SOURCE_APPEARANCES = 5
MIN_CLAIM_RECURRENCE = 3

# Thresholds de alerta 

VETO_RATE_WARN = 0.40 # tópico com mais de 40% de veto → RECOMMEND
VETO_RATE_CRITICAL = 0.65 # tópico com mais de 65% de veto → alerta crítico
ENGINE_FAILURE_WARN = 0.25 # engine com > 25% de falha crítica → RECOMMEND
SOURCE_RISK_WARN = 0.45 # fonte com > 45% de veto-association → RECOMMEND
NUMERIC_FAIL_WARN = 0.50 # tipo numérico com > 50% de falha → OBSERVE


# =========================
# ENUMS E MODELOS
# =========================

class FeedbackLevel(str, Enum):
 OBSERVE = "observe" # padrão detectado, sem ação imediata
 RECOMMEND = "recommend" # ajuste sugerido para humano aprovar
 ENFORCE = "enforce" # (reservado — não ativo)


class FeedbackCategory(str, Enum):
 TOPIC = "topic"
 ENGINE = "engine"
 SOURCE = "source"
 CLAIM = "claim"
 NUMERIC = "numeric"
 GLOBAL = "global"


@dataclass
class Alert:
 level: FeedbackLevel
 category: FeedbackCategory
 subject: str
 message: str
 metric_value: float
 threshold: float
 recommendation: str

 # Campos para ciclo de correção (preenchidos futuramente)
 policy_adjustment_triggered: bool = False
 resolved_after_validation: Optional[bool] = None
 repeat_failure: bool = False


@dataclass
class FeedbackReport:
 generated_at: str
 total_events_analyzed: int
 sufficient_data: bool
 data_warning: str

 alerts: list = field(default_factory=list)
 topic_recommendations: list = field(default_factory=list)
 engine_recommendations: list = field(default_factory=list)
 source_recommendations: list = field(default_factory=list)
 numeric_observations: list = field(default_factory=list)
 claim_watchlist: list = field(default_factory=list)
 context_policy_readiness: dict = field(default_factory=dict) # avaliação para 6C


# =========================
# ENGINE
# =========================

class TrustFeedbackEngine:

 def __init__(self, metrics_file: Path = METRICS_FILE):
 self.metrics_file = metrics_file

 # Principal 

 def run(self) -> FeedbackReport:
 """Lê métricas e gera o relatório de feedback."""
 metrics = self._load_metrics()
 total = metrics.get("total_claims", 0)

 sufficient = total >= MIN_EVENTS_FOR_LEARNING
 warning = (
 "" if sufficient
 else f"Dados insuficientes para aprendizado ({total}/{MIN_EVENTS_FOR_LEARNING} eventos). "
 "Resultados são observacionais."
 )

 report = FeedbackReport(
 generated_at = datetime.utcnow().isoformat(),
 total_events_analyzed = total,
 sufficient_data = sufficient,
 data_warning = warning,
 )

 if total == 0:
 print("[trust_feedback] Nenhum evento para analisar.")
 self._save(report)
 return report

 # Análise por camada
 self._analyze_topics(metrics, report)
 self._analyze_engines(metrics, report)
 self._analyze_sources(metrics, report)
 self._analyze_numerics(metrics, report)
 self._analyze_claims(metrics, report)
 self._analyze_global(metrics, report)
 self._analyze_6c_readiness(metrics, report)

 self._save(report)
 self._print(report)
 return report

 # Análise por tópico 

 def _analyze_topics(self, metrics: dict, report: FeedbackReport):
 for row in metrics.get("veto_rate_by_topic", []):
 topic = row["topic"]
 n = row["total_claims"]
 vr = row["veto_rate"]
 conf = row["avg_confidence"]
 sq = row["avg_source_quality"]

 if n < MIN_TOPIC_EVENTS:
 report.topic_recommendations.append({
 "topic": topic,
 "status": "volume_insuficiente",
 "events": n,
 "min_required": MIN_TOPIC_EVENTS,
 "note": f"Aguardar {MIN_TOPIC_EVENTS - n} eventos a mais para conclusão.",
 })
 continue

 recs = []
 level = FeedbackLevel.OBSERVE

 if vr >= VETO_RATE_CRITICAL:
 level = FeedbackLevel.RECOMMEND
 recs.append(f"Subir confidence_threshold para '{topic}' de 70 para 80+")
 recs.append(f"Exigir pelo menos 1 fonte primária ou industry_report para claims deste tópico")
 recs.append(f"Revisar prompt do(s) engine(s) que mais geram claims de '{topic}'")
 # Causa provável específica por tópico
 if topic == "api_cost":
 recs.append(
 "api_cost: causa provável = dado desatualizado ou sem fonte oficial. "
 "Exigir data recente + fonte do provedor."
 )
 elif topic == "benchmark":
 recs.append(
 "benchmark: causa provável = generalização ou amostra ruim. "
 "Exigir >= 2 fontes com score >= 8."
 )
 elif topic == "competitor":
 recs.append(
 "competitor: causa provável = informação desatualizada ou inferida. "
 "Exigir verificação direta de funcionalidades/preços atuais."
 )
 elif vr >= VETO_RATE_WARN:
 level = FeedbackLevel.RECOMMEND
 recs.append(f"Monitorar '{topic}': veto_rate {vr:.0%} acima de {VETO_RATE_WARN:.0%}")
 recs.append(f"Considerar pedir fonte adicional para claims numéricas de '{topic}'")
 else:
 recs.append(f"'{topic}' está dentro do limite aceitável. Monitorar.")

 if sq < 5.0:
 recs.append(f"Source quality média baixa ({sq}): encorajar fontes mais sólidas para este tópico")

 alert = Alert(
 level = level,
 category = FeedbackCategory.TOPIC,
 subject = topic,
 message = f"veto_rate={vr:.0%} | conf={conf} | source_quality={sq} | n={n}",
 metric_value = vr,
 threshold = VETO_RATE_WARN,
 recommendation = " | ".join(recs),
 )
 report.alerts.append(alert)
 report.topic_recommendations.append({
 "topic": topic,
 "level": level.value,
 "veto_rate": vr,
 "n": n,
 "recommendations": recs,
 })

 # Análise por engine 

 def _analyze_engines(self, metrics: dict, report: FeedbackReport):
 for row in metrics.get("critical_failure_rate_by_engine", []):
 engine = row["engine"]
 n = row["total_claims"]
 cfr = row["critical_failure_rate"]
 vr_n = row.get("validation_required", 0)

 if n < MIN_ENGINE_EVENTS:
 report.engine_recommendations.append({
 "engine": engine,
 "status": "volume_insuficiente",
 "events": n,
 "min_required": MIN_ENGINE_EVENTS,
 })
 continue

 recs = []
 level = FeedbackLevel.OBSERVE

 if cfr >= ENGINE_FAILURE_WARN:
 level = FeedbackLevel.RECOMMEND
 recs.append(f"Revisar prompt de '{engine}' para separar melhor fato de inferência")
 recs.append(f"Adicionar instrução explícita para citar fontes numéricas em '{engine}'")
 if vr_n > n * 0.4:
 recs.append(f"Alta taxa de validation_required ({vr_n}/{n}): considerar pré-filtro de qualidade no output deste engine")
 else:
 recs.append(f"'{engine}' dentro do aceitável. Manter monitoramento.")

 alert = Alert(
 level = level,
 category = FeedbackCategory.ENGINE,
 subject = engine,
 message = f"critical_failure_rate={cfr:.0%} | n={n}",
 metric_value = cfr,
 threshold = ENGINE_FAILURE_WARN,
 recommendation = " | ".join(recs),
 )
 report.alerts.append(alert)
 report.engine_recommendations.append({
 "engine": engine,
 "level": level.value,
 "cfr": cfr,
 "n": n,
 "recommendations": recs,
 })

 # Análise por fonte 

 def _analyze_sources(self, metrics: dict, report: FeedbackReport):
 for row in metrics.get("source_risk_index", []):
 stype = row["source_type"]
 n = row["appearances"]
 veto_a = row["veto_association"]
 score = row["avg_score"]
 risk = row["risk_level"]

 if n < MIN_SOURCE_APPEARANCES:
 continue

 recs = []
 level = FeedbackLevel.OBSERVE

 if veto_a >= SOURCE_RISK_WARN:
 level = FeedbackLevel.RECOMMEND
 recs.append(f"Fontes do tipo '{stype}' estão associadas a {veto_a:.0%} dos vetos")
 recs.append(f"Reduzir peso efetivo de '{stype}' em tópicos críticos (pricing, competitor, api_cost)")
 if score < 4:
 recs.append(f"Score médio baixo ({score}/10): considerar exigir fonte adicional quando '{stype}' for a única")
 else:
 recs.append(f"'{stype}' com risco={risk}. Monitorar se o volume crescer.")

 alert = Alert(
 level = level,
 category = FeedbackCategory.SOURCE,
 subject = stype,
 message = f"veto_association={veto_a:.0%} | avg_score={score} | n={n}",
 metric_value = veto_a,
 threshold = SOURCE_RISK_WARN,
 recommendation = " | ".join(recs),
 )
 report.alerts.append(alert)
 report.source_recommendations.append({
 "source_type": stype,
 "level": level.value,
 "veto_association": veto_a,
 "avg_score": score,
 "n": n,
 "recommendations": recs,
 })

 # Análise numérica 

 def _analyze_numerics(self, metrics: dict, report: FeedbackReport):
 for row in metrics.get("numeric_failure_rate", []):
 ntype = row["numeric_type"]
 n = row["total"]
 fr = row["failure_rate"]

 obs = {
 "numeric_type": ntype,
 "total": n,
 "failure_rate": fr,
 "level": FeedbackLevel.OBSERVE.value,
 "note": "",
 }

 # Alerta específico para benchmark (generalização + fonte indireta)
 if ntype == "benchmark" and fr > 0.50 and n >= 3:
 obs["level"] = FeedbackLevel.RECOMMEND.value
 obs["note"] = (
 f"benchmark falha em {fr:.0%} dos casos — causa provável: generalização "
 "ou fonte indireta. "
 "Elevar threshold: exigir source_quality >= 8, >= 2 fontes, confiança >= 75."
 )
 report.alerts.append(Alert(
 level = FeedbackLevel.RECOMMEND,
 category = FeedbackCategory.NUMERIC,
 subject = "benchmark",
 message = f"failure_rate={fr:.0%} | n={n}",
 metric_value = fr,
 threshold = NUMERIC_FAIL_WARN,
 recommendation = obs["note"],
 ))

 # Alerta específico para api_cost (volatilidade + dado velho)
 elif ntype in {"cost_estimate", "benchmark"} and fr > 0.50 and n >= 3:
 obs["level"] = FeedbackLevel.RECOMMEND.value
 obs["note"] = (
 f"'{ntype}' falha em {fr:.0%} dos casos — causa provável: dado desatualizado "
 "ou sem fonte oficial. Exigir data recente + fonte primária para este tipo."
 )
 report.alerts.append(Alert(
 level = FeedbackLevel.RECOMMEND,
 category = FeedbackCategory.NUMERIC,
 subject = ntype,
 message = f"failure_rate={fr:.0%} | n={n}",
 metric_value = fr,
 threshold = NUMERIC_FAIL_WARN,
 recommendation = obs["note"],
 ))

 elif fr >= NUMERIC_FAIL_WARN and n >= 3:
 obs["level"] = FeedbackLevel.RECOMMEND.value
 obs["note"] = (
 f"Claims do tipo '{ntype}' falham em {fr:.0%} dos casos. "
 "Reforçar exigência de fonte ou aumentar threshold."
 )
 report.alerts.append(Alert(
 level = FeedbackLevel.RECOMMEND,
 category = FeedbackCategory.NUMERIC,
 subject = ntype,
 message = f"failure_rate={fr:.0%} | n={n}",
 metric_value = fr,
 threshold = NUMERIC_FAIL_WARN,
 recommendation = obs["note"],
 ))
 else:
 obs["note"] = f"failure_rate={fr:.0%} dentro do aceitável ou volume baixo ({n})."

 report.numeric_observations.append(obs)

 # Watchlist de claims 

 def _analyze_claims(self, metrics: dict, report: FeedbackReport):
 for row in metrics.get("validation_recurrence", []):
 count = row["count"]
 question = row["question"]

 if count < MIN_CLAIM_RECURRENCE:
 continue

 entry = {
 "question": question,
 "recurrences": count,
 "status": "watchlist",
 "note": (
 f"Esta pergunta de validação apareceu {count}x. "
 "Considerar: (a) melhorar prompt para evitar a afirmação frágil, "
 "ou (b) adicionar esta validação como claim_policy padrão."
 ),
 # Campos para ciclo de correção
 "resolved_after_validation": None,
 "repeat_failure": count >= MIN_CLAIM_RECURRENCE * 2,
 "policy_adjustment_triggered": False,
 }
 report.claim_watchlist.append(entry)

 if count >= MIN_CLAIM_RECURRENCE * 2:
 alert = Alert(
 level = FeedbackLevel.RECOMMEND,
 category = FeedbackCategory.CLAIM,
 subject = question[:60],
 message = f"Reincidência alta: {count}x",
 metric_value = float(count),
 threshold = float(MIN_CLAIM_RECURRENCE),
 recommendation = (
 "Transformar em regra explícita no claim_policy ou "
 "adicionar instrução no prompt do engine de origem."
 ),
 repeat_failure = True,
 )
 report.alerts.append(alert)

 # Avaliação de prontidão para 6C (context-aware policy) 

 def _analyze_6c_readiness(self, metrics: dict, report: FeedbackReport):
 """
 Avalia se já existe evidência suficiente para implementar a 6C (policy contextual).
 Responde 4 perguntas diagnósticas e define critério de liberação.
 """
 fbc = metrics.get("failure_rate_by_context", [])
 fbec = metrics.get("failure_by_engine_and_context", [])
 dist = metrics.get("execution_mode_distribution", {})
 cfe = metrics.get("critical_failure_rate_by_engine", [])

 ctx_map = {r["context"]: r for r in fbc}
 eng_map = {r["engine"]: r for r in cfe}

 # Pergunta 1: autonomous_agent mais obediente ou só usando fallback? 
 aa = eng_map.get("autonomous_agent", {})
 aa_cfr = aa.get("critical_failure_rate", None)
 aa_fallback = sum(r["fallback_used"] for r in fbec if r["engine"] == "autonomous_agent")
 aa_total = sum(r["total_claims"] for r in fbec if r["engine"] == "autonomous_agent")
 aa_fallback_rate = round(aa_fallback / aa_total, 3) if aa_total else None

 q1_status = "sem_dados"
 if aa_cfr is not None:
 if aa_cfr <= 0.20 and (aa_fallback_rate is None or aa_fallback_rate < 0.15):
 q1_status = "obediente"
 elif aa_fallback_rate is not None and aa_fallback_rate >= 0.20:
 q1_status = "fallback_alto"
 else:
 q1_status = "indefinido"

 # Pergunta 2: benchmark_block segurando claim ruim ou bloqueando demais? 
 vbt = metrics.get("veto_rate_by_topic", [])
 benchmark_row = next((r for r in vbt if r["topic"] == "competitor"), None)
 research_ctx = ctx_map.get("research", {})
 q2_status = "sem_dados"
 if benchmark_row:
 benchmark_vr = benchmark_row.get("veto_rate", 0)
 research_cfr = research_ctx.get("critical_failure_rate", 0)
 if benchmark_vr > 0.60 and research_cfr > 0.50:
 q2_status = "bloqueando_demais_em_research"
 elif benchmark_vr > 0.40:
 q2_status = "contencao_adequada"
 else:
 q2_status = "subativo"

 # Pergunta 3: api_cost_block mais preciso após patch de fontes? 
 api_cost_row = next((r for r in vbt if r["topic"] == "api_cost"), None)
 q3_status = "sem_dados"
 if api_cost_row:
 api_vr = api_cost_row.get("veto_rate", 0)
 if api_vr > 0.65:
 q3_status = "ainda_agressivo"
 elif api_vr > 0.30:
 q3_status = "calibrado"
 else:
 q3_status = "permissivo"

 # Pergunta 4: divergência clara por contexto que justifica 6C? 
 launch_cfr = ctx_map.get("launch_ready", {}).get("critical_failure_rate", None)
 research_cfr = ctx_map.get("research", {}).get("critical_failure_rate", None)
 idea_cfr = ctx_map.get("idea", {}).get("critical_failure_rate", None)

 q4_status = "sem_dados"
 divergence_delta = None
 if launch_cfr is not None and research_cfr is not None:
 divergence_delta = round(research_cfr - launch_cfr, 3)
 if divergence_delta >= 0.25:
 q4_status = "divergencia_clara"
 elif divergence_delta >= 0.10:
 q4_status = "divergencia_parcial"
 else:
 q4_status = "sem_divergencia"
 elif idea_cfr is not None and launch_cfr is not None:
 divergence_delta = round(idea_cfr - launch_cfr, 3)
 if divergence_delta >= 0.25:
 q4_status = "divergencia_clara"

 # Hipótese de causa raiz da divergência 
 root_cause_hypothesis = None
 if q4_status in ("divergencia_clara", "divergencia_parcial"):
 # Tenta identificar qual camada explica melhor a divergência
 api_vr = next((r["veto_rate"] for r in vbt if r["topic"] == "api_cost"), 0)
 benchmark_vr = next((r["veto_rate"] for r in vbt if r["topic"] == "competitor"), 0)
 sri = metrics.get("source_risk_index", [])
 high_risk_src = any(r["risk_level"] == "alto" for r in sri)

 if aa_cfr is not None and aa_cfr > 0.30:
 root_cause_hypothesis = "agent_inference"
 elif benchmark_vr > 0.50:
 root_cause_hypothesis = "policy_rigidity"
 elif api_vr > 0.50:
 root_cause_hypothesis = "policy_rigidity"
 elif high_risk_src:
 root_cause_hypothesis = "source_quality"
 else:
 root_cause_hypothesis = "numeric_type"

 # Checklist de liberação (taxa + volume mínimo) 
 checklist = {
 "autonomous_agent_reduziu_critical_failure": aa_cfr is not None and aa_cfr <= 0.20,
 "fallback_permaneceu_baixo": aa_fallback_rate is not None and aa_fallback_rate < 0.15,
 "benchmark_block_sem_travar_research": q2_status not in ("bloqueando_demais_em_research", "sem_dados"),
 "api_cost_block_mais_preciso": q3_status == "calibrado",
 "divergencia_clara_entre_contextos": q4_status == "divergencia_clara" and (divergence_delta or 0) >= 0.25,
 # volume mínimo por contexto = 8 eventos (consistente com threshold de divergência)
 "amostra_suficiente_por_contexto": len([r for r in fbc if r["total_claims"] >= 8]) >= 2,
 }

 criteria_met = sum(checklist.values())
 ready_for_6c = (
 checklist["divergencia_clara_entre_contextos"]
 and checklist["amostra_suficiente_por_contexto"]
 and criteria_met >= 3
 and unknown_rate_local <= 0.10 # integridade mínima do contexto
 )

 # Verificar se unknown_context_rate está alto o suficiente para bloquear a 6C
 fbc_unknown = next((r for r in fbc if r["context"] == "unknown"), None)
 unknown_n_local = fbc_unknown["total_claims"] if fbc_unknown else 0
 total_local = sum(r["total_claims"] for r in fbc) if fbc else 0
 unknown_rate_local = round(unknown_n_local / total_local, 3) if total_local else 0

 # Breakdown de unknown por engine (recomputa a partir das métricas)
 _unk_by_eng: dict[str, int] = {}
 _eng_totals: dict[str, int] = {}
 for r in fbec:
 eng = r["engine"]
 _eng_totals[eng] = _eng_totals.get(eng, 0) + r["total_claims"]
 if r["context"] == "unknown":
 _unk_by_eng[eng] = r["total_claims"]
 unknown_engine_rates = {
 eng: round(_unk_by_eng[eng] / _eng_totals[eng], 3)
 for eng in _unk_by_eng
 if _eng_totals.get(eng, 0) > 0
 }

 blockers = []
 if aa_fallback_rate is not None and aa_fallback_rate >= 0.20:
 blockers.append("fallback_alto_no_autonomous_agent")
 if q4_status == "sem_dados":
 blockers.append("pouca_amostra_por_contexto")
 if not checklist["divergencia_clara_entre_contextos"]:
 blockers.append("sem_divergencia_suficiente_entre_contextos")
 if unknown_rate_local > 0.10:
 blockers.append("high_unknown_context_rate")

 report.context_policy_readiness = {
 "q1_autonomous_agent_status": q1_status,
 "q1_aa_cfr": aa_cfr,
 "q1_aa_fallback_rate": aa_fallback_rate,
 "q2_benchmark_block_status": q2_status,
 "q3_api_cost_block_status": q3_status,
 "q4_context_divergence_status": q4_status,
 "q4_divergence_delta": divergence_delta,
 "root_cause_hypothesis": root_cause_hypothesis,
 "unknown_context_rate": unknown_rate_local,
 "unknown_context_by_engine": unknown_engine_rates,
 "checklist": checklist,
 "criteria_met": criteria_met,
 "ready_for_6c": ready_for_6c,
 "blockers": blockers,
 }

 # Avaliação global 

 def _analyze_global(self, metrics: dict, report: FeedbackReport):
 dist = metrics.get("execution_mode_distribution", {})
 vr_n = dist.get("validation_required", {}).get("pct", 0)
 exp = dist.get("experiment", {}).get("pct", 0)
 total = metrics.get("total_claims", 0)

 # Monitor de unknown_context_rate 
 fbc = metrics.get("failure_rate_by_context", [])
 unknown_row = next((r for r in fbc if r["context"] == "unknown"), None)
 unknown_n = unknown_row["total_claims"] if unknown_row else 0
 unknown_rate = round(unknown_n / total, 3) if total else 0

 # Breakdown de unknown por engine (para apontar origem com precisão)
 unknown_by_engine: dict[str, int] = {}
 engine_totals: dict[str, int] = {}
 for r in metrics.get("failure_by_engine_and_context", []):
 eng = r["engine"]
 engine_totals[eng] = engine_totals.get(eng, 0) + r["total_claims"]
 if r["context"] == "unknown":
 unknown_by_engine[eng] = r["total_claims"]

 unknown_engine_rates = {
 eng: round(unknown_by_engine[eng] / engine_totals[eng], 3)
 for eng in unknown_by_engine
 if engine_totals.get(eng, 0) > 0
 }

 if unknown_rate > 0.10 and total >= MIN_EVENTS_FOR_LEARNING:
 breakdown_str = ", ".join(
 f"{eng}={pct:.0%}" for eng, pct in sorted(unknown_engine_rates.items(), key=lambda x: -x[1])
 ) or "sem dados por engine"
 report.alerts.append(Alert(
 level = FeedbackLevel.RECOMMEND,
 category = FeedbackCategory.GLOBAL,
 subject = "execution_context",
 message = (
 f"unknown_context_rate={unknown_rate:.0%} ({unknown_n}/{total} eventos). "
 f"Por engine: {breakdown_str}"
 ),
 metric_value = unknown_rate,
 threshold = 0.10,
 recommendation = (
 "Mais de 10% dos eventos não têm execution_context válido. "
 "Corrigir na origem: engines com maior taxa de unknown são os prioritários. "
 "Contextos inválidos degradam a análise de divergência e bloqueiam liberação da 6C."
 ),
 ))

 if vr_n > 0.5:
 report.alerts.append(Alert(
 level = FeedbackLevel.RECOMMEND,
 category = FeedbackCategory.GLOBAL,
 subject = "sistema",
 message = f"Mais de {vr_n:.0%} das verificações caem em VALIDATION_REQUIRED",
 metric_value = vr_n,
 threshold = 0.5,
 recommendation = (
 "O sistema está bloqueando muito. Revisar se os thresholds de claim_policy "
 "estão calibrados para o estágio atual do negócio (ideia vs mvp vs lançamento)."
 ),
 ))
 elif vr_n + exp < 0.1 and metrics.get("total_claims", 0) >= MIN_EVENTS_FOR_LEARNING:
 report.alerts.append(Alert(
 level = FeedbackLevel.OBSERVE,
 category = FeedbackCategory.GLOBAL,
 subject = "sistema",
 message = "Taxa de bloqueio muito baixa — sistema pode estar leniente",
 metric_value = vr_n + exp,
 threshold = 0.1,
 recommendation = (
 "Verificar se o verification_engine está sendo acionado com textos reais "
 "ou se os inputs já chegam muito filtrados."
 ),
 ))

 # Persistência 

 def _save(self, report: FeedbackReport):
 TRUST_DIR.mkdir(parents=True, exist_ok=True)

 # JSON
 data = asdict(report)
 # Converter Enum para valor string
 data["alerts"] = [
 {**a, "level": a["level"].value if hasattr(a["level"], "value") else a["level"],
 "category": a["category"].value if hasattr(a["category"], "value") else a["category"]}
 for a in data["alerts"]
 ]
 with open(FEEDBACK_JSON, "w", encoding="utf-8") as f:
 json.dump(data, f, ensure_ascii=False, indent=2)

 # Markdown
 self._save_md(report)
 print(f"[trust_feedback] Relatório salvo: {FEEDBACK_JSON}")

 def _save_md(self, report: FeedbackReport):
 recommend_alerts = [a for a in report.alerts if a.level == FeedbackLevel.RECOMMEND]
 observe_alerts = [a for a in report.alerts if a.level == FeedbackLevel.OBSERVE]

 lines = [
 "# Trust Feedback Report — MYO",
 f"\n_Gerado em: {report.generated_at}_",
 f"\n**Eventos analisados:** {report.total_events_analyzed}",
 f"**Dados suficientes para aprendizado:** {' Sim' if report.sufficient_data else ' Não'}",
 ]

 if report.data_warning:
 lines.append(f"\n> {report.data_warning}")

 if recommend_alerts:
 lines.append(f"\n## Recomendações ({len(recommend_alerts)})\n")
 for a in recommend_alerts:
 lines += [
 f"### [{a.category.value.upper()}] {a.subject}",
 f"- **Métrica:** {a.message}",
 f"- **Recomendação:** {a.recommendation}",
 "",
 ]

 if observe_alerts:
 lines.append(f"\n## Observações ({len(observe_alerts)})\n")
 for a in observe_alerts:
 lines += [
 f"- **[{a.category.value}] {a.subject}:** {a.message}",
 ]

 if report.claim_watchlist:
 lines.append(f"\n## Watchlist de claims recorrentes ({len(report.claim_watchlist)})\n")
 for w in report.claim_watchlist:
 flag = " repeat_failure" if w["repeat_failure"] else ""
 lines.append(f"- [{w['recurrences']}x] {w['question'][:80]}{flag}")

 # 6C readiness
 cpr = report.context_policy_readiness
 if cpr:
 ready = cpr.get("ready_for_6c", False)
 label = " LIBERADA" if ready else " NÃO LIBERADA"
 lines.append(f"\n## 6C — Context-Aware Policy: {label}\n")

 lines.append("### Diagnóstico\n")
 lines.append(f"| Pergunta | Status |")
 lines.append(f"|----------|--------|")
 lines.append(f"| Q1 — autonomous_agent obediente ou só fallback? | `{cpr.get('q1_autonomous_agent_status', '—')}` (cfr={cpr.get('q1_aa_cfr','—')}, fallback={cpr.get('q1_aa_fallback_rate','—')}) |")
 lines.append(f"| Q2 — benchmark_block segurando ou bloqueando demais? | `{cpr.get('q2_benchmark_block_status', '—')}` |")
 lines.append(f"| Q3 — api_cost_block preciso após patch? | `{cpr.get('q3_api_cost_block_status', '—')}` |")
 lines.append(f"| Q4 — divergência clara por contexto? | `{cpr.get('q4_context_divergence_status', '—')}` (delta={cpr.get('q4_divergence_delta','—')}) |")

 rch = cpr.get("root_cause_hypothesis")
 if rch:
 rch_labels = {
 "policy_rigidity": "rigidez de policy (benchmark/api_cost bloqueando por igual em todos os contextos)",
 "agent_inference": "inferência do agent (autonomous_agent instável em contextos exploratórios)",
 "source_quality": "qualidade de fonte (fontes de alto risco concentradas em contextos específicos)",
 "numeric_type": "tipo numérico (claims de benchmark/forecast mais frequentes em certos contextos)",
 }
 lines.append(f"\n**Hipótese de causa raiz:** `{rch}` — {rch_labels.get(rch, rch)}")

 lines.append("\n### Checklist de liberação\n")
 for item, val in cpr.get("checklist", {}).items():
 mark = "- [x]" if val else "- [ ]"
 lines.append(f"{mark} {item.replace('_', ' ')}")

 met = cpr.get("criteria_met", 0)
 lines.append(f"\n**Critérios atendidos:** {met}/6")

 ucr = cpr.get("unknown_context_rate", 0)
 ube = cpr.get("unknown_context_by_engine", {})
 if ucr > 0:
 ube_str = ", ".join(f"{e}={v:.0%}" for e, v in sorted(ube.items(), key=lambda x: -x[1])) or "—"
 flag = " BLOQUEADOR" if ucr > 0.10 else ""
 lines.append(f"\n**unknown_context_rate:** {ucr:.0%}{flag}")
 lines.append(f"**Por engine:** {ube_str}")

 blockers = cpr.get("blockers", [])
 if blockers:
 lines.append("\n**Bloqueadores:**")
 for b in blockers:
 lines.append(f"- {b.replace('_', ' ')}")

 lines += [
 "\n---",
 "### Regra operacional",
 "- **RECOMMEND** = sugestão para humano aprovar antes de aplicar",
 "- **OBSERVE** = padrão registrado, sem ação imediata",
 "- **ENFORCE** = reservado (não ativo)",
 "\n_MYO Trust Feedback Engine — gerado automaticamente_",
 ]

 with open(FEEDBACK_MD, "w", encoding="utf-8") as f:
 f.write("\n".join(lines))
 print(f"[trust_feedback] Summary MD salvo: {FEEDBACK_MD}")

 # Display terminal 

 def _print(self, report: FeedbackReport):
 rec = [a for a in report.alerts if a.level == FeedbackLevel.RECOMMEND]
 obs = [a for a in report.alerts if a.level == FeedbackLevel.OBSERVE]

 print("\n" + "" * 64)
 print(" TRUST FEEDBACK ENGINE")
 print("" * 64)
 print(f" Eventos : {report.total_events_analyzed}")
 print(f" Suficiente : {' sim' if report.sufficient_data else ' não — dados parciais'}")
 if report.data_warning:
 print(f" Aviso : {report.data_warning}")

 # Exibir unknown_context_rate como linha de saúde do sistema
 unknown_alert = next(
 (a for a in report.alerts if a.category == FeedbackCategory.GLOBAL and a.subject == "execution_context"),
 None,
 )
 if unknown_alert:
 print(f" Contexto : {unknown_alert.message}")

 print(f" RECOMMEND : {len(rec)}")
 print(f" OBSERVE : {len(obs)}")
 print(f" Watchlist : {len(report.claim_watchlist)}")

 if rec:
 print("\n Recomendações ")
 for a in rec:
 print(f" [{a.category.value.upper():<8}] {a.subject:<20} {a.message}")
 print(f" → {a.recommendation[:70]}")

 if report.claim_watchlist:
 print("\n Watchlist ")
 for w in report.claim_watchlist[:5]:
 flag = " [REINCIDENTE]" if w["repeat_failure"] else ""
 print(f" [{w['recurrences']}x]{flag} {w['question'][:60]}")

 cpr = report.context_policy_readiness
 if cpr:
 ready = cpr.get("ready_for_6c", False)
 label = " LIBERADA" if ready else " não liberada"
 print(f"\n 6C Context-Aware Policy: {label} ")
 print(f" Q1 autonomous_agent : {cpr.get('q1_autonomous_agent_status','—')}"
 f" (fallback={cpr.get('q1_aa_fallback_rate','—')})")
 print(f" Q2 benchmark_block : {cpr.get('q2_benchmark_block_status','—')}")
 print(f" Q3 api_cost_block : {cpr.get('q3_api_cost_block_status','—')}")
 print(f" Q4 divergência : {cpr.get('q4_context_divergence_status','—')}"
 f" (delta={cpr.get('q4_divergence_delta','—')})")
 rch = cpr.get("root_cause_hypothesis")
 if rch:
 print(f" Causa raiz hipótese : {rch}")
 print(f" Critérios atendidos : {cpr.get('criteria_met',0)}/6")
 ucr = cpr.get("unknown_context_rate", 0)
 if ucr > 0:
 ube = cpr.get("unknown_context_by_engine", {})
 ube_str = ", ".join(f"{e}={v:.0%}" for e, v in sorted(ube.items(), key=lambda x: -x[1])) or "—"
 flag = " BLOQUEADOR" if ucr > 0.10 else ""
 print(f" Context integridade : unknown={ucr:.0%}{flag} [{ube_str}]")
 if cpr.get("blockers"):
 print(f" Bloqueadores : {', '.join(cpr['blockers'])}")

 print("" * 64 + "\n")

 # Helpers 

 def _load_metrics(self) -> dict:
 if not self.metrics_file.exists():
 return {}
 with open(self.metrics_file, encoding="utf-8") as f:
 return json.load(f)


# =========================
# CLI
# =========================

if __name__ == "__main__":
 TrustFeedbackEngine().run()
