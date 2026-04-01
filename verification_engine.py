"""
Verification Engine — Pipeline AI
Camada de confiança entre pesquisa/análise e execução.

Missões:
 1. Classificar afirmações via Claude (fato / estimativa / inferência / hipótese / recomendação)
 2. Avaliar qualidade de fontes via source_policy
 3. Detectar claims críticas via claim_policy (preço, mercado, concorrente, API)
 4. Decidir: execução normal | experimento | validação obrigatória
 5. Gerar validation tasks agrupadas por tema

Regra de gate (todas devem passar para NORMAL):
 confidence_score >= 80
 source_quality_score >= 7.0
 unverified_claims <= 2
 NENHUMA claim crítica abaixo do threshold

Se qualquer claim crítica falhar → VALIDATION_REQUIRED (independente da média).
"""
import asyncio, json, os
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any

import httpx
from dotenv import load_dotenv
import claim_policy
import source_policy
from claim_policy import is_high_risk_numeric_claim
from source_policy import TRUSTED_API_SOURCES

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"
OUTPUTS_DIR = "outputs/verification"


# =========================
# ENUMS
# =========================

class ClaimType(str, Enum):
 FACT = "fact" # dado confirmado por fonte primária
 ESTIMATE = "estimate" # estimativa com alguma base
 INFERENCE = "inference" # inferência plausível
 HYPOTHESIS = "hypothesis" # hipótese não testada
 RECOMMENDATION = "recommendation" # sugestão estratégica da IA


class SourceType(str, Enum):
 PRIMARY = "primary" # dados oficiais, pesquisa própria
 INDUSTRY_REPORT = "industry_report" # relatório de mercado
 RECOGNIZED_PUBLICATION = "recognized_publication" # publicação reconhecida
 BLOG = "blog"
 AGGREGATOR = "aggregator"
 SOCIAL = "social"
 AI_GENERATED = "ai_generated"
 UNKNOWN = "unknown"


class ExecutionMode(str, Enum):
 NORMAL = "normal" # evidência suficiente
 EXPERIMENT = "experiment" # hipótese plausível, marcar como teste
 VALIDATION_REQUIRED = "validation_required" # precisa validar antes de executar


# =========================
# DATA MODELS
# =========================

@dataclass
class Source:
 url: str
 source_type: SourceType
 quality_score: int # 1–10
 date: Optional[str] = None
 is_recent: bool = True
 notes: str = ""


@dataclass
class EvidencePack:
 claim: str
 claim_type: ClaimType
 confidence: int # 0–100
 verified: bool
 topic: str = "general" # classificado por claim_policy
 criticality: str = "moderate" # "critical" | "moderate" | "low"
 is_critical_failure: bool = False # True se claim crítica abaixo do threshold
 specific_policy_triggered: Optional[str] = None # "benchmark_block" | "api_cost_block"
 sources: List[Source] = field(default_factory=list)
 notes: str = ""
 requires_validation: bool = False
 validation_question: str = ""


@dataclass
class VerificationResult:
 input_summary: str
 verified_claims: List[EvidencePack]
 unverified_claims: List[EvidencePack]
 assumptions: List[str]

 confidence_score: int # 0–100 (média ponderada)
 source_quality_score: float # 0–10 (média das fontes informadas)
 source_count: int

 safe_to_execute: bool
 execution_mode: ExecutionMode
 requires_validation: List[str]
 critical_failures: List[str] = field(default_factory=list) # claims críticas que bloquearam

 created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
 raw_analysis: Dict[str, Any] = field(default_factory=dict)


# =========================
# HELPERS
# =========================

def _parse_json(raw: str) -> dict:
 try:
 return json.loads(raw)
 except json.JSONDecodeError:
 s, e = raw.find("{"), raw.rfind("}") + 1
 if s != -1 and e > s:
 return json.loads(raw[s:e])
 raise ValueError(f"JSON inválido: {raw[:300]}")


async def _claude(prompt: str, max_tokens: int = 2000) -> dict:
 if not ANTHROPIC_API_KEY or "sua-chave" in ANTHROPIC_API_KEY:
 raise ValueError("ANTHROPIC_API_KEY não configurada")
 payload = {
 "model": CLAUDE_MODEL,
 "max_tokens": max_tokens,
 "messages": [{"role": "user", "content": prompt}],
 }
 headers = {
 "x-api-key": ANTHROPIC_API_KEY,
 "anthropic-version": "2023-06-01",
 "content-type": "application/json",
 }
 async with httpx.AsyncClient(timeout=120) as c:
 r = await c.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
 r.raise_for_status()
 data = r.json()
 raw = data.get("content", [{}])[0].get("text", "")
 return _parse_json(raw)


# =========================
# VETOS ESPECÍFICOS
# =========================

def should_block_benchmark_claim(
 numeric_claim_type: Optional[str],
 source_quality_score: float,
 source_count: int,
 confidence: int,
) -> bool:
 """
 benchmark sem base forte → bloquear.
 Exige: source_quality >= 8, >= 2 fontes, confiança >= 75.
 Razão: benchmark falha por generalização, amostra ruim, fonte indireta.
 """
 if numeric_claim_type != "benchmark":
 return False
 return (
 source_quality_score < 8
 or source_count < 2
 or confidence < 75
 )


def should_block_api_cost_claim(
 topic: str,
 source_quality_score: float,
 confidence: int,
 sources: List[Dict[str, Any]],
) -> bool:
 """
 api_cost sem data recente + fonte confiável → bloquear.
 Razão: custo de API muda por provedor, modelo, volume, plano e data.
 Aceita: primary, official_docs, vendor_pricing, trusted_partner_docs, industry_report.
 """
 if topic != "api_cost":
 return False
 has_dated_source = any(s.get("date") for s in sources)
 has_trusted_source = any(s.get("type") in TRUSTED_API_SOURCES for s in sources)
 return (
 not has_dated_source
 or not has_trusted_source
 or source_quality_score < 8
 or confidence < 80
 )


# =========================
# PROMPTS
# =========================

def _prompt_classify_claims(text: str, context: str = "") -> str:
 return f"""Você é um auditor crítico de informação estratégica.

Analise o texto abaixo e extraia TODAS as afirmações relevantes — especialmente números, tendências, comparações e conclusões de negócio.

{f"Contexto adicional: {context}" if context else ""}

Texto para análise:
---
{text}
---

Para cada afirmação, classifique usando EXATAMENTE um destes tipos:
- "fact" → dado verificável com fonte primária clara
- "estimate" → estimativa com alguma base, mas sem confirmação definitiva
- "inference" → conclusão lógica a partir de evidências parciais
- "hypothesis" → hipótese plausível mas não testada
- "recommendation" → sugestão estratégica da IA ou do autor

Também identifique:
- "assumptions": lista de premissas implícitas no texto
- "confidence_score": sua avaliação geral de confiança do texto inteiro (0–100)
- "source_quality_score": qualidade média das fontes citadas (0–10). Se não há fontes citadas, use 4.
- "requires_validation": lista de perguntas críticas que precisam ser respondidas antes de agir

Responda APENAS em JSON válido, sem markdown:

{{
 "claims": [
 {{
 "claim": "texto da afirmação",
 "claim_type": "fact|estimate|inference|hypothesis|recommendation",
 "confidence": 0-100,
 "verified": true|false,
 "notes": "observação crítica",
 "requires_validation": true|false,
 "validation_question": "pergunta para validar esta afirmação"
 }}
 ],
 "assumptions": ["..."],
 "confidence_score": 0-100,
 "source_quality_score": 0-10,
 "requires_validation": ["pergunta 1", "pergunta 2"]
}}"""


# =========================
# ENGINE
# =========================

class VerificationEngine:

 def __init__(self, output_dir: str = OUTPUTS_DIR):
 self.output_dir = Path(output_dir)
 self.output_dir.mkdir(parents=True, exist_ok=True)

 # Verificação principal 

 async def verify(
 self,
 text: str,
 context: str = "",
 known_sources: Optional[List[Source]] = None,
 origin_engine: str = "unknown",
 entity_id: str = "",
 execution_context: str = "",
 ) -> VerificationResult:
 """
 execution_context: estágio do negócio onde a claim foi gerada.
 Valores válidos: idea | research | mvp | launch_ready | scaling
 """
 """
 Analisa o texto via Claude, classifica afirmações e retorna VerificationResult.
 """
 print(f"[verification] Analisando confiança do input ({len(text)} chars)...")

 raw = await _claude(_prompt_classify_claims(text, context))

 claims_raw = raw.get("claims", [])
 assumptions = raw.get("assumptions", [])
 confidence_score = int(raw.get("confidence_score", 50))
 source_quality_raw = float(raw.get("source_quality_score", 4.0))
 validation_required = raw.get("requires_validation", [])

 # Calcular qualidade de fontes via source_policy
 sources = known_sources or []
 if sources:
 scores = [
 source_policy.adjusted_score(
 s.source_type.value,
 date_str=s.date,
 is_volatile_topic=False,
 )
 for s in sources
 ]
 source_quality_score = source_policy.aggregate_quality(scores)
 else:
 source_quality_score = source_quality_raw

 # Montar EvidencePacks com claim_policy
 verified_claims: List[EvidencePack] = []
 unverified_claims: List[EvidencePack] = []

 for c in claims_raw:
 claim_text = c.get("claim", "")
 topic = claim_policy.classify_topic(claim_text)
 criticality = claim_policy.get_criticality(topic)
 # 6C: threshold ajustado por contexto se disponível
 threshold = claim_policy.confidence_threshold_for_context(topic, execution_context)
 conf = int(c.get("confidence", 50))
 is_verified = bool(c.get("verified", False))

 # Claim crítica abaixo do threshold = critical failure
 num_type = claim_policy.numeric_claim_type(claim_text)
 is_crit_fail = (
 criticality == "critical"
 and (conf < threshold or not is_verified)
 )

 # Vetos específicos por tipo (sobrepõem o gate genérico)
 specific_policy: Optional[str] = None
 if not is_crit_fail:
 src_dicts = [{"type": s.source_type.value, "date": s.date} for s in sources]
 if should_block_benchmark_claim(num_type, source_quality_score, len(sources), conf):
 is_crit_fail = True
 specific_policy = "benchmark_block"
 elif should_block_api_cost_claim(topic, source_quality_score, conf, src_dicts):
 is_crit_fail = True
 specific_policy = "api_cost_block"

 pack = EvidencePack(
 claim = claim_text,
 claim_type = ClaimType(c.get("claim_type", "inference")),
 confidence = conf,
 verified = is_verified,
 topic = topic,
 criticality = criticality,
 is_critical_failure = is_crit_fail,
 specific_policy_triggered = specific_policy,
 notes = c.get("notes", ""),
 requires_validation = bool(c.get("requires_validation", False)) or is_crit_fail,
 validation_question = c.get("validation_question", ""),
 )
 if is_verified and not is_crit_fail:
 verified_claims.append(pack)
 else:
 unverified_claims.append(pack)

 critical_failures = [p.claim for p in unverified_claims if p.is_critical_failure]

 # Gate de execução: score agregado + veto por claim crítica (6C: context-aware)
 safe, mode = self._execution_gate(
 confidence_score, source_quality_score, len(unverified_claims),
 critical_failures, execution_context=execution_context
 )

 result = VerificationResult(
 input_summary = text[:200] + ("..." if len(text) > 200 else ""),
 verified_claims = verified_claims,
 unverified_claims = unverified_claims,
 assumptions = assumptions,
 confidence_score = confidence_score,
 source_quality_score = source_quality_score,
 source_count = len(sources),
 safe_to_execute = safe,
 execution_mode = mode,
 requires_validation = validation_required,
 critical_failures = critical_failures,
 raw_analysis = raw,
 )

 self._save(result)
 self._print(result)
 self._log(result, origin_engine=origin_engine, entity_id=entity_id, execution_context=execution_context)
 return result

 # Gate de execução 

 def _execution_gate(
 self,
 confidence: int,
 source_quality: float,
 unverified_count: int,
 critical_failures: List[str],
 execution_context: str = "",
 ) -> tuple[bool, ExecutionMode]:
 """
 Gate duplo (6C: thresholds ajustados por contexto via context_policy.json):
 1. Veto imediato: qualquer claim crítica com confiança insuficiente
 → VALIDATION_REQUIRED, independente da média agregada
 2. Score agregado (context-aware):
 confidence >= T_normal AND source_quality >= SQ AND unverified <= UL → NORMAL
 confidence >= T_experiment → EXPERIMENT
 abaixo → VALIDATION_REQUIRED
 """
 # 6C: carrega thresholds do contexto atual
 thresholds = claim_policy.gate_thresholds_for_context(execution_context)
 t_normal = thresholds["confidence_normal"]
 t_experiment = thresholds["confidence_experiment"]
 sq_min = thresholds["source_quality"]
 uv_limit = thresholds["unverified_limit"]

 # Veto por claim crítica (score agregado não pode mascarar falha crítica)
 if critical_failures:
 return False, ExecutionMode.VALIDATION_REQUIRED

 if confidence >= t_normal and source_quality >= sq_min and unverified_count <= uv_limit:
 return True, ExecutionMode.NORMAL

 if confidence >= t_experiment:
 return False, ExecutionMode.EXPERIMENT

 return False, ExecutionMode.VALIDATION_REQUIRED

 # Validation tasks 

 def generate_validation_tasks(
 self,
 result: VerificationResult,
 origin_engine: str = "verification_engine",
 ) -> list:
 """
 Agrupa afirmações frágeis por tema (claim_policy) e gera UMA task por grupo.
 Evita fila infinita de micro-tasks soltas.
 Retorna lista de ExecutionTask criadas.
 """
 from execution_engine import ExecutionEngine, TaskType, TaskPriority, AgentType

 engine = ExecutionEngine()
 tasks = []

 candidates = [
 p for p in result.unverified_claims
 if p.requires_validation
 ]
 if not candidates:
 return tasks

 # Agrupar por tópico
 groups: Dict[str, List[EvidencePack]] = defaultdict(list)
 for pack in candidates:
 groups[pack.topic].append(pack)

 for topic, packs in groups.items():
 label = claim_policy.group_label(topic)
 criticality = claim_policy.get_criticality(topic)
 priority = TaskPriority.HIGH if criticality == "critical" else TaskPriority.MEDIUM

 # Consolidar perguntas e claims do grupo
 questions = [
 p.validation_question for p in packs if p.validation_question
 ]
 claims_list = [p.claim for p in packs]
 avg_conf = int(sum(p.confidence for p in packs) / len(packs))

 description = (
 f"Grupo de validação: '{label}'.\n"
 f"Confiança média das afirmações: {avg_conf}/100.\n\n"
 f"Afirmações a validar:\n" +
 "\n".join(f" - {c}" for c in claims_list) +
 (f"\n\nPerguntas abertas:\n" + "\n".join(f" ? {q}" for q in questions) if questions else "")
 )

 task = engine.create_task(
 title = label,
 description = description,
 origin_engine = origin_engine,
 task_type = TaskType.VALIDATION,
 priority = priority,
 suggested_agent = AgentType.CLAUDE,
 execution_ready = False,
 context={
 "topic": topic,
 "criticality": criticality,
 "avg_confidence": avg_conf,
 "claims": claims_list,
 "questions": questions,
 },
 acceptance_criteria=[
 f"Todas as {len(packs)} afirmação(ões) do grupo respondidas com fonte identificável",
 "Cada afirmação reclassificada como fact, estimate ou descartada",
 ],
 deliverables=[
 f"relatório de validação do grupo '{topic}'",
 "classificação atualizada por afirmação",
 ],
 tags=["verification", "validation", topic, criticality],
 )
 tasks.append(task)
 print(f"[verification] Validation task ({topic}): {task.task_id} — {len(packs)} claim(s)")

 return tasks

 # Persistência e display 

 def _log(self, result: VerificationResult, origin_engine: str = "unknown", entity_id: str = "", execution_context: str = ""):
 try:
 from verification_logger import VerificationLogger
 VerificationLogger().log(result, origin_engine=origin_engine, entity_id=entity_id, execution_context=execution_context)
 except Exception as e:
 print(f"[verification] Aviso: falha ao gravar trust_log: {e}")

 def _save(self, result: VerificationResult):
 ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
 path = self.output_dir / f"verification_{ts}.json"

 def _serialize(obj):
 if isinstance(obj, (ClaimType, SourceType, ExecutionMode)):
 return obj.value
 if hasattr(obj, "__dataclass_fields__"):
 return asdict(obj)
 return str(obj)

 with open(path, "w", encoding="utf-8") as f:
 json.dump(asdict(result), f, ensure_ascii=False, indent=2, default=_serialize)
 print(f"[verification] Resultado salvo em: {path}")

 def _print(self, r: VerificationResult):
 mode_label = {
 ExecutionMode.NORMAL: " NORMAL",
 ExecutionMode.EXPERIMENT: " EXPERIMENTO",
 ExecutionMode.VALIDATION_REQUIRED: " VALIDAÇÃO OBRIGATÓRIA",
 }.get(r.execution_mode, r.execution_mode.value)

 print("\n" + "" * 60)
 print(" VERIFICATION RESULT")
 print("" * 60)
 print(f" Confidence score : {r.confidence_score}/100")
 print(f" Source quality : {r.source_quality_score}/10")
 print(f" Verified claims : {len(r.verified_claims)}")
 print(f" Unverified claims : {len(r.unverified_claims)}")
 print(f" Assumptions : {len(r.assumptions)}")
 print(f" Safe to execute : {r.safe_to_execute}")
 print(f" Execution mode : {mode_label}")

 if r.critical_failures:
 print(f"\n Claims críticas bloqueando execução ({len(r.critical_failures)}):")
 for cf in r.critical_failures[:3]:
 print(f" {cf[:70]}")

 if r.unverified_claims:
 print(f"\n Afirmações não verificadas ({len(r.unverified_claims)}):")
 for p in r.unverified_claims[:5]:
 flag = " [CRÍTICA]" if p.is_critical_failure else ""
 print(f" [{p.topic:<12}] {p.claim[:55]}{flag}")

 if r.requires_validation:
 print("\n Validações necessárias:")
 for q in r.requires_validation[:4]:
 print(f" ? {q[:70]}")

 print("" * 60 + "\n")


# =========================
# STANDALONE / TESTE
# =========================

async def _demo():
 sample = """
 O mercado de automação para restaurantes está crescendo 40% ao ano.
 A principal dor dos donos de restaurante é a falta de controle financeiro.
 CFO Digital pode ser vendido por R$ 497 com alta aceitação do mercado.
 A concorrência ainda não tem uma solução integrada para esse nicho.
 Existe espaço claro para um produto de ticket médio neste segmento.
 """

 engine = VerificationEngine()
 result = await engine.verify(
 text=sample,
 context="Análise gerada pelo product_engine para o produto CFO Digital",
 origin_engine="product_engine",
 entity_id="cfo_digital",
 )

 if result.execution_mode != ExecutionMode.NORMAL:
 tasks = engine.generate_validation_tasks(result, origin_engine="demo")
 print(f" {len(tasks)} validation task(s) criada(s).")

 return result


if __name__ == "__main__":
 asyncio.run(_demo())
