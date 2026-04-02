"""
Trust Aggregator — Pipeline AI
Lê verification_events.jsonl e gera métricas consolidadas de confiabilidade.

Saída:
 outputs/trust/trust_metrics.json ← métricas brutas
 outputs/trust/trust_summary.md ← relatório legível

Métricas:
 1. veto_rate_by_topic — quais tópicos mais bloqueiam execução
 2. critical_failure_rate_by_engine — quais engines geram mais claims frágeis
 3. source_risk_index — tipos de fonte por risco histórico
 4. validation_recurrence — perguntas de validação mais repetidas
 5. numeric_failure_rate — afirmações numéricas que mais falham
"""
import json
import re
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from verification_logger import VerificationLogger

TRUST_DIR = Path("outputs/trust")
METRICS_FILE = TRUST_DIR / "trust_metrics.json"
SUMMARY_FILE = TRUST_DIR / "trust_summary.md"


# =========================
# AGGREGATOR
# =========================

class TrustAggregator:

 def __init__(self, logger: Optional[VerificationLogger] = None):
  self.logger = logger or VerificationLogger()
 TRUST_DIR.mkdir(parents=True, exist_ok=True)

 # Principal 

 def aggregate(self) -> dict:
  """Lê todos os eventos e retorna dict de métricas."""
 events = self.logger.load_events()
 if not events:
  print("[trust_aggregator] Nenhum evento disponível.")
 return {}

 metrics = {
 "generated_at": datetime.utcnow().isoformat(),
 "total_claims": len(events),
 "total_engines": len({e["origin_engine"] for e in events}),

 "veto_rate_by_topic": self._veto_by_topic(events),
 "critical_failure_rate_by_engine": self._failure_by_engine(events),
 "source_risk_index": self._source_risk(events),
 "validation_recurrence": self._validation_recurrence(events),
 "numeric_failure_rate": self._numeric_failure(events),
 "execution_mode_distribution": self._mode_distribution(events),
 "failure_rate_by_context": self._failure_by_context(events),
 "failure_by_engine_and_context": self._failure_by_engine_and_context(events),
 }

 self._save_metrics(metrics)
 self._save_summary(metrics)
 return metrics

 # Métricas 

 def _veto_by_topic(self, events: list[dict]) -> list[dict]:
  """Taxa de veto (is_critical_failure=True) por tópico."""
 totals: dict[str, int] = defaultdict(int)
 vetoed: dict[str, int] = defaultdict(int)
 conf_sum: dict[str, float] = defaultdict(float)
 sq_sum: dict[str, float] = defaultdict(float)

 for ev in events:
  topic = ev.get("topic", "general")
 totals[topic] += 1
 conf_sum[topic] += ev.get("confidence_score", 0)
 sq_sum[topic] += ev.get("source_quality_score", 0)
 if ev.get("is_critical_failure"):
  vetoed[topic] += 1

 result = []
 for topic in sorted(totals, key=lambda t: vetoed[t] / totals[t], reverse=True):
  n = totals[topic]
 vr = vetoed[topic] / n
 result.append({
 "topic": topic,
 "total_claims": n,
 "vetoed": vetoed[topic],
 "veto_rate": round(vr, 3),
 "avg_confidence": round(conf_sum[topic] / n, 1),
 "avg_source_quality": round(sq_sum[topic] / n, 1),
 })
 return result

 def _failure_by_engine(self, events: list[dict]) -> list[dict]:
  """Taxa de falha crítica por engine de origem."""
 totals: dict[str, int] = defaultdict(int)
 critical: dict[str, int] = defaultdict(int)
 val_req: dict[str, int] = defaultdict(int)
 normal: dict[str, int] = defaultdict(int)

 for ev in events:
  eng = ev.get("origin_engine", "unknown")
 totals[eng] += 1
 if ev.get("is_critical_failure"):
  critical[eng] += 1
 mode = ev.get("execution_mode", "")
 if mode == "validation_required":
  val_req[eng] += 1
 elif mode == "normal":
  normal[eng] += 1

 result = []
 for eng in sorted(totals, key=lambda e: critical[e] / totals[e], reverse=True):
  n = totals[eng]
 result.append({
 "engine": eng,
 "total_claims": n,
 "critical_failures": critical[eng],
 "critical_failure_rate": round(critical[eng] / n, 3),
 "validation_required": val_req[eng],
 "normal": normal[eng],
 })
 return result

 def _source_risk(self, events: list[dict]) -> list[dict]:
  """Índice de risco por tipo de fonte."""
 type_counts: dict[str, int] = defaultdict(int)
 type_scores: dict[str, float] = defaultdict(float)
 type_vetoed: dict[str, int] = defaultdict(int)

 for ev in events:
  is_veto = ev.get("is_critical_failure", False)
 for src in ev.get("sources", []):
  stype = src.get("type", "unknown")
 score = src.get("score", 0)
 type_counts[stype] += 1
 type_scores[stype] += score
 if is_veto:
  type_vetoed[stype] += 1

 result = []
 for stype in sorted(type_counts, key=lambda s: type_vetoed[s] / type_counts[s], reverse=True):
  n = type_counts[stype]
 result.append({
 "source_type": stype,
 "appearances": n,
 "avg_score": round(type_scores[stype] / n, 1),
 "veto_association": round(type_vetoed[stype] / n, 3),
 "risk_level": _risk_label(type_vetoed[stype] / n),
 })
 return result

 def _validation_recurrence(self, events: list[dict]) -> list[dict]:
  """Agrupa perguntas de validação recorrentes por similaridade."""
 all_questions: list[str] = []
 for ev in events:
  all_questions.extend(ev.get("validation_questions", []))

 clusters = _cluster_texts(all_questions, threshold=0.60)
 return [
 {"question": c["representative"], "count": c["count"]}
 for c in clusters[:15]
 ]

 def _numeric_failure(self, events: list[dict]) -> list[dict]:
  """Taxa de falha para claims com valor numérico, por tipo."""
 totals: dict[str, int] = defaultdict(int)
 failed: dict[str, int] = defaultdict(int)

 for ev in events:
  if not ev.get("numeric_claim_detected"):
   continue
 ntype = ev.get("numeric_claim_type") or "numeric"
 totals[ntype] += 1
 if ev.get("is_critical_failure") or ev.get("requires_validation"):
  failed[ntype] += 1

 result = []
 for ntype in sorted(totals, key=lambda t: failed[t] / totals[t], reverse=True):
  n = totals[ntype]
 result.append({
 "numeric_type": ntype,
 "total": n,
 "failed": failed[ntype],
 "failure_rate": round(failed[ntype] / n, 3),
 })
 return result

 def _failure_by_context(self, events: list[dict]) -> list[dict]:
  """Taxa de falha crítica por execution_context (idea/research/mvp/launch_ready/scaling)."""
 totals: dict[str, int] = defaultdict(int)
 critical: dict[str, int] = defaultdict(int)
 val_req: dict[str, int] = defaultdict(int)

 for ev in events:
  ctx = ev.get("execution_context", "unknown")
 totals[ctx] += 1
 if ev.get("is_critical_failure"):
  critical[ctx] += 1
 if ev.get("execution_mode") == "validation_required":
  val_req[ctx] += 1

 result = []
 for ctx in sorted(totals, key=lambda c: critical[c] / totals[c], reverse=True):
  n = totals[ctx]
 result.append({
 "context": ctx,
 "total_claims": n,
 "critical_failures": critical[ctx],
 "critical_failure_rate": round(critical[ctx] / n, 3),
 "validation_required": val_req[ctx],
 })
 return result

 def _failure_by_engine_and_context(self, events: list[dict]) -> list[dict]:
  """
 Comportamento separado por engine E contexto.
 Permite ver: product_engine em research vs launch_ready; autonomous_agent em idea vs scaling.
 """
 # chave: (engine, context)
 totals: dict[tuple, int] = defaultdict(int)
 critical: dict[tuple, int] = defaultdict(int)
 fallback: dict[tuple, int] = defaultdict(int)

 for ev in events:
  key = (ev.get("origin_engine", "unknown"), ev.get("execution_context", "unknown"))
 totals[key] += 1
 if ev.get("is_critical_failure"):
  critical[key] += 1
 if ev.get("fallback_used"):
  fallback[key] += 1

 result = []
 for (eng, ctx) in sorted(totals, key=lambda k: critical[k] / totals[k], reverse=True):
  n = totals[(eng, ctx)]
 result.append({
 "engine": eng,
 "context": ctx,
 "total_claims": n,
 "critical_failures": critical[(eng, ctx)],
 "critical_failure_rate": round(critical[(eng, ctx)] / n, 3),
 "fallback_used": fallback[(eng, ctx)],
 })
 return result

 def _mode_distribution(self, events: list[dict]) -> dict:
  counts: dict[str, int] = defaultdict(int)
 for ev in events:
  counts[ev.get("execution_mode", "unknown")] += 1
 total = len(events)
 return {
 mode: {"count": n, "pct": round(n / total, 3)}
 for mode, n in sorted(counts.items(), key=lambda x: x[1], reverse=True)
 }

 # Persistência 

 def _save_metrics(self, metrics: dict):
  with open(METRICS_FILE, "w", encoding="utf-8") as f:
   json.dump(metrics, f, ensure_ascii=False, indent=2)
 print(f"[trust_aggregator] Métricas salvas: {METRICS_FILE}")

 def _save_summary(self, metrics: dict):
  lines = [
 "# Trust Summary — MYO Verification Layer",
 f"\n_Gerado em: {metrics['generated_at']}_",
 f"\n**Total de claims analisadas:** {metrics['total_claims']}",
 f"**Engines monitorados:** {metrics['total_engines']}",
 ]

 # Distribuição de modos
 dist = metrics.get("execution_mode_distribution", {})
 if dist:
  lines.append("\n## Distribuição de modo de execução\n")
 for mode, d in dist.items():
  bar = _bar(d["pct"])
 lines.append(f"- **{mode}**: {bar} {d['pct']:.0%} ({d['count']} claims)")

 # Veto por tópico
 vbt = metrics.get("veto_rate_by_topic", [])
 if vbt:
  lines.append("\n## Veto rate por tópico\n")
 lines.append("| Tópico | Claims | Vetadas | Veto Rate | Conf. Média |")
 lines.append("|--------|--------|---------|-----------|-------------|")
 for row in vbt:
  lines.append(
 f"| {row['topic']} | {row['total_claims']} | {row['vetoed']} "
 f"| {row['veto_rate']:.0%} | {row['avg_confidence']} |"
 )

 # Falha crítica por engine
 cfe = metrics.get("critical_failure_rate_by_engine", [])
 if cfe:
  lines.append("\n## Taxa de falha crítica por engine\n")
 lines.append("| Engine | Claims | Críticas | Taxa |")
 lines.append("|--------|--------|----------|------|")
 for row in cfe:
  lines.append(
 f"| {row['engine']} | {row['total_claims']} "
 f"| {row['critical_failures']} | {row['critical_failure_rate']:.0%} |"
 )

 # Source risk
 sri = metrics.get("source_risk_index", [])
 if sri:
  lines.append("\n## Source risk index\n")
 lines.append("| Tipo de fonte | Aparições | Score médio | Risco |")
 lines.append("|---------------|-----------|-------------|-------|")
 for row in sri:
  lines.append(
 f"| {row['source_type']} | {row['appearances']} "
 f"| {row['avg_score']} | {row['risk_level']} |"
 )

 # Numeric failure
 nfr = metrics.get("numeric_failure_rate", [])
 if nfr:
  lines.append("\n## Falha por tipo de afirmação numérica\n")
 lines.append("| Tipo | Total | Falharam | Taxa |")
 lines.append("|------|-------|----------|------|")
 for row in nfr:
  lines.append(
 f"| {row['numeric_type']} | {row['total']} "
 f"| {row['failed']} | {row['failure_rate']:.0%} |"
 )

 # Falha por contexto
 fbc = metrics.get("failure_rate_by_context", [])
 if fbc:
  lines.append("\n## Taxa de falha crítica por contexto\n")
 lines.append("| Contexto | Claims | Críticas | Taxa | Val.Required |")
 lines.append("|----------|--------|----------|------|--------------|")
 for row in fbc:
  divergence = " " if row["critical_failure_rate"] > 0.5 and row["total_claims"] >= 8 else ""
 lines.append(
 f"| {row['context']} | {row['total_claims']} "
 f"| {row['critical_failures']} | {row['critical_failure_rate']:.0%}{divergence} "
 f"| {row['validation_required']} |"
 )

 # Comportamento por engine × contexto
 fbec = metrics.get("failure_by_engine_and_context", [])
 if fbec:
  lines.append("\n## Comportamento por engine × contexto\n")
 lines.append("| Engine | Contexto | Claims | Críticas | Taxa | Fallback |")
 lines.append("|--------|----------|--------|----------|------|----------|")
 for row in fbec:
  lines.append(
 f"| {row['engine']} | {row['context']} | {row['total_claims']} "
 f"| {row['critical_failures']} | {row['critical_failure_rate']:.0%} "
 f"| {row['fallback_used']} |"
 )

 # Recorrência de perguntas
 vr = metrics.get("validation_recurrence", [])
 if vr:
  lines.append("\n## Perguntas de validação mais recorrentes\n")
 for row in vr[:8]:
  lines.append(f"- [{row['count']}x] {row['question']}")

 lines.append("\n---\n_MYO Trust Layer — gerado automaticamente_")

 with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
  f.write("\n".join(lines))
 print(f"[trust_aggregator] Summary salvo: {SUMMARY_FILE}")

 # CLI 

 def print_dashboard(self):
  """Imprime o dashboard de confiabilidade no terminal."""
 metrics = self.aggregate()
 if not metrics:
  return

 print("\n" + "" * 64)
 print(" TRUST DASHBOARD — MYO Verification Layer")
 print("" * 64)
 print(f" Total de claims : {metrics['total_claims']}")
 print(f" Engines : {metrics['total_engines']}")

 dist = metrics.get("execution_mode_distribution", {})
 if dist:
  print("\n Distribuição de modos:")
 for mode, d in dist.items():
  bar = _bar(d["pct"])
 print(f" {mode:<22} {bar} {d['pct']:.0%}")

 vbt = metrics.get("veto_rate_by_topic", [])
 if vbt:
  print("\n Veto rate por tópico:")
 for row in vbt:
  bar = _bar(row["veto_rate"])
 flag = " ← ATENÇÃO" if row["veto_rate"] > 0.5 else ""
 print(f" {row['topic']:<16} {bar} {row['veto_rate']:.0%}{flag}")

 cfe = metrics.get("critical_failure_rate_by_engine", [])
 if cfe:
  print("\n Fragilidade por engine:")
 for row in cfe:
  bar = _bar(row["critical_failure_rate"])
 print(f" {row['engine']:<25} {bar} {row['critical_failure_rate']:.0%}")

 sri = metrics.get("source_risk_index", [])
 if sri:
  print("\n Source risk index:")
 for row in sri:
  print(f" {row['source_type']:<22} risco={row['risk_level']:<6} score_médio={row['avg_score']}")

 nfr = metrics.get("numeric_failure_rate", [])
 if nfr:
  print("\n Falha por tipo numérico:")
 for row in nfr:
  bar = _bar(row["failure_rate"])
 print(f" {row['numeric_type']:<16} {bar} {row['failure_rate']:.0%}")

 fbc = metrics.get("failure_rate_by_context", [])
 if fbc:
  print("\n Falha crítica por contexto:")
 for row in fbc:
  bar = _bar(row["critical_failure_rate"])
 flag = " ← DIVERGÊNCIA" if row["critical_failure_rate"] > 0.5 and row["total_claims"] >= 8 else ""
 print(f" {row['context']:<14} {bar} {row['critical_failure_rate']:.0%} n={row['total_claims']}{flag}")

 fbec = metrics.get("failure_by_engine_and_context", [])
 if fbec:
  print("\n Engine × Contexto:")
 for row in fbec:
  bar = _bar(row["critical_failure_rate"])
 fb = f" fallback={row['fallback_used']}" if row["fallback_used"] else ""
 print(f" {row['engine']:<25} [{row['context']:<12}] {bar} {row['critical_failure_rate']:.0%}{fb}")

 vr = metrics.get("validation_recurrence", [])
 if vr:
  print("\n Perguntas de validação recorrentes:")
 for row in vr[:5]:
  print(f" [{row['count']}x] {row['question'][:60]}")

 print("" * 64 + "\n")


# =========================
# HELPERS
# =========================

def _similarity(a: str, b: str) -> float:
 return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _cluster_texts(texts: list[str], threshold: float = 0.60) -> list[dict]:
 clusters: list[dict] = []
 for text in texts:
  if not text.strip():
   continue
 matched = False
 for cluster in clusters:
  if _similarity(text, cluster["representative"]) >= threshold:
   cluster["count"] += 1
 matched = True
 break
 if not matched:
  clusters.append({"representative": text, "count": 1})
 return sorted(clusters, key=lambda x: x["count"], reverse=True)


def _risk_label(veto_rate: float) -> str:
 if veto_rate >= 0.6:
  return "alto"
 if veto_rate >= 0.3:
  return "médio"
 return "baixo"


def _bar(rate: float, width: int = 10) -> str:
 filled = round(min(rate, 1.0) * width)
 return "" * filled + "" * (width - filled)


# =========================
# CLI
# =========================

if __name__ == "__main__":
 TrustAggregator().print_dashboard()
