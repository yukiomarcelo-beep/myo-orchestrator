#!/usr/bin/env python3
"""
Orch Core — Motor de Orquestração GPT × Claude

Núcleo autônomo que encaixa entre Radar e Executor.

FLUXO:
 Radar -> TrendSignal -> Orchestrator -> OpportunityDecision -> Executor

Uso direto:
 python orch_core.py # roda exemplo embutido
 python orch_core.py --payload signal.json # lê sinal de arquivo
 python orch_core.py --rounds 5 # mais rodadas de debate

Como módulo:
 from orch_core import Orchestrator, trend_signal_from_dict
 orch = Orchestrator()
 decision = orch.process_signal(signal)
"""

import argparse
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()
from observability import tracer, tracker  # noqa: E402

# Configuração

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"
GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4o")

# Score mínimo para não rejeitar automaticamente (0–100)
REJECTION_THRESHOLD = 52.0

# Pesos do scoring final (somam 100)
SCORE_WEIGHTS: Dict[str, float] = {
    "dor_do_mercado": 20,
    "urgencia": 15,
    "monetizacao": 15,
    "escalabilidade": 15,
    "aquisicao": 10,
    "diferenciacao": 10,
    "execucao": 10,
    "potencial_de_conteudo": 5,
}


# Dataclasses


@dataclass
class TrendSignal:
    """Sinal de tendência gerado pelo Radar."""

    title: str
    description: str
    source: str
    pain_level: float  # 1–10
    urgency: float  # 1–10
    market_heat: float  # 1–10
    evidence: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def raw_score(self) -> float:
        """Score bruto do sinal antes do debate."""
        return round((self.pain_level + self.urgency + self.market_heat) / 3, 2)


@dataclass
class OpportunityScore:
    """Score detalhado de viabilidade."""

    total_score: float
    dimension_scores: Dict[str, float] = field(default_factory=dict)
    rejection_reasons: List[str] = field(default_factory=list)
    rejected: bool = False
    recommendation: str = "testar"  # descartar | testar | priorizar
    confidence: float = 0.0  # 0–1 — concordância entre modelos


@dataclass
class DebateRound:
    """Registro de uma rodada do debate GPT × Claude."""

    round_num: int
    gpt_proposal: str
    claude_critique: str
    refined_idea: str  # GPT refina após crítica


@dataclass
class OpportunityDecision:
    """Decisão final do Orchestrator."""

    idea_name: str
    target_customer: str
    core_problem: str
    proposed_solution: str
    offer_format: str
    delivery_model: str
    pricing_hint: str
    score: OpportunityScore
    next_actions: List[str] = field(default_factory=list)
    debate_log: List[DebateRound] = field(default_factory=list)
    signal_title: str = ""
    signal_source: str = ""
    generated_at: str = ""
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0


# Utilitários


def _extract_json(text: str) -> dict:
    """Extrai JSON de uma resposta que pode conter texto extra."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"JSON não encontrado na resposta:\n{text[:300]}")


def _calc_score(dimension_scores: Dict[str, float]) -> float:
    """Calcula score ponderado 0–100 a partir de notas 1–5 por dimensão."""
    total = 0.0
    for dim, weight in SCORE_WEIGHTS.items():
        nota = dimension_scores.get(dim, 3.0)
        total += (nota / 5.0) * weight
    return round(total, 1)


# Providers


class OpenAIProvider:
    """Chamadas à API OpenAI via httpx."""

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key or OPENAI_API_KEY
        self.model = model or GPT_MODEL
        # Chave não obrigatória — llm_router faz fallback Claude/heurística

    def chat(
        self, system: str, user: str, max_tokens: int = 1500, temperature: float = 0.7
    ) -> tuple[str, float, int]:
        """Retorna (texto, custo_usd, latencia_ms). Fallback: Claude → heurística."""
        from agents.llm_router import get_router

        text, cost, latency_ms, provider = get_router().safe_call(
            user,
            system,
            context_hint="orch_gpt",
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if provider != "openai":
            print(f" GPT role via {provider}")
        return text, cost, latency_ms


class AnthropicProvider:
    """Chamadas à API Anthropic via httpx."""

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key or ANTHROPIC_API_KEY
        self.model = model or CLAUDE_MODEL
        # Chave não obrigatória — llm_router faz fallback OpenAI/heurística

    def chat(
        self, system: str, user: str, max_tokens: int = 1500, temperature: float = 0.7
    ) -> tuple[str, float, int]:
        """Retorna (texto, custo_usd, latencia_ms). Fallback: OpenAI → heurística."""
        if os.getenv("MYO_USE_LLM_GATEWAY", "false").lower() == "true":
            from core.llm_gateway import get_gateway

            resp = get_gateway().chat(system, user, max_tokens=max_tokens, temperature=temperature)
            return resp.text, resp.cost_usd, resp.latency_ms

        from agents.llm_router import get_router

        text, cost, latency_ms, provider = get_router().safe_call(
            user,
            system,
            context_hint="orch_claude",
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if provider != "claude":
            print(f" Claude role via {provider}")
        return text, cost, latency_ms


# Prompts

_SYS_GPT_PROPOSER = """Você é um estrategista de negócios digitais especializado em criar
oportunidades de alto potencial a partir de sinais de mercado. Seja objetivo, prático e direto.
Pense como um fundador com experiência em lançar produtos rápidos e rentáveis."""

_SYS_CLAUDE_CRITIC = """Você é um analista de negócios crítico e rigoroso. Sua função é
identificar falhas reais em propostas de negócio: suposições não validadas, riscos subestimados,
mercados saturados, modelos frágeis. Não valide o que não merece validação. Seja honesto."""

_SYS_SCORER = """Você é um avaliador especialista em oportunidades de negócio digital.
Avalie com rigor e objetividade. Responda APENAS com JSON válido, sem markdown."""


def _prompt_propose(signal: TrendSignal, prev_refinement: str = "") -> str:
    context = f"\nIdeia refinada anterior:\n{prev_refinement}" if prev_refinement else ""
    evidence = (
        "\n".join(f"- {e}" for e in signal.evidence)
        if signal.evidence
        else "- nenhuma evidência fornecida"
    )
    return f"""Com base neste sinal de mercado, proponha uma oportunidade de negócio clara e executável.

SINAL:
Título: {signal.title}
Descrição: {signal.description}
Fonte: {signal.source}
Dor (1–10): {signal.pain_level}
Urgência (1–10): {signal.urgency}
Calor de mercado (1–10): {signal.market_heat}
Evidências:
{evidence}
{context}

Responda em JSON:
{{
 "idea_name": "nome da oportunidade",
 "target_customer": "perfil exato do cliente",
 "core_problem": "dor central em 1 frase",
 "proposed_solution": "como resolve a dor",
 "offer_format": "formato da oferta (ex: assinatura mensal, serviço pontual, produto digital)",
 "delivery_model": "como entrega valor (ex: app, planilha + suporte, consultoria, automação)",
 "pricing_hint": "faixa de preço sugerida e justificativa",
 "key_assumptions": ["hipótese 1", "hipótese 2", "hipótese 3"],
 "next_actions": ["ação 1", "ação 2", "ação 3"]
}}"""


def _prompt_critique(proposal: dict, signal: TrendSignal, round_num: int) -> str:
    return f"""Analise criticamente esta proposta de negócio (rodada {round_num}).

SINAL ORIGINAL:
{signal.title} — {signal.description}

PROPOSTA:
{json.dumps(proposal, ensure_ascii=False, indent=2)}

Seja implacável. Identifique:
1. Hipóteses mais frágeis
2. Riscos de execução reais
3. Por que o cliente pode NÃO comprar
4. O que está sendo subestimado

Responda em JSON:
{{
 "verdict": "aceito" | "refinar" | "rejeitar",
 "fatal_flaws": ["falha grave 1", "falha grave 2"],
 "risks": ["risco 1", "risco 2", "risco 3"],
 "weak_assumptions": ["hipótese fraca 1", "hipótese fraca 2"],
 "suggested_pivots": ["ajuste 1", "ajuste 2"],
 "strongest_point": "o que é genuinamente forte na proposta",
 "critique_summary": "resumo da crítica em 2 frases"
}}"""


def _prompt_refine(proposal: dict, critique: dict, signal: TrendSignal) -> str:
    return f"""Você propôs uma ideia e recebeu uma crítica. Refine a proposta incorporando os pontos válidos.

PROPOSTA ORIGINAL:
{json.dumps(proposal, ensure_ascii=False, indent=2)}

CRÍTICA RECEBIDA:
{json.dumps(critique, ensure_ascii=False, indent=2)}

SINAL ORIGINAL:
{signal.title} — {signal.description}

Refine mantendo o que é forte, corrigindo as falhas reais. Ignore críticas genéricas sem substância.

Responda em JSON (mesmo formato da proposta original):
{{
 "idea_name": "",
 "target_customer": "",
 "core_problem": "",
 "proposed_solution": "",
 "offer_format": "",
 "delivery_model": "",
 "pricing_hint": "",
 "key_assumptions": [],
 "next_actions": []
}}"""


def _prompt_score(final_proposal: dict, signal: TrendSignal, debate_summary: str) -> str:
    return f"""Avalie esta oportunidade de negócio com rigor.

SINAL:
{signal.title} — Dor: {signal.pain_level}/10 | Urgência: {signal.urgency}/10 | Calor: {signal.market_heat}/10

PROPOSTA FINAL (após {debate_summary}):
{json.dumps(final_proposal, ensure_ascii=False, indent=2)}

Notas de 1 a 5 para cada critério (1=péssimo, 5=excelente):
- dor_do_mercado: A dor é real, frequente e custosa?
- urgencia: As pessoas querem resolver isso agora?
- monetizacao: Dá para cobrar bem, com margens saudáveis?
- escalabilidade: Dá para vender em volume sem custo proporcional?
- aquisicao: É fácil encontrar esse público?
- diferenciacao: Tem diferenciação real ou vira commodity?
- execucao: Dá para executar com stack Python/API/Claude?
- potencial_de_conteudo: Gera ganchos e autoridade orgânica?

Responda APENAS em JSON válido:
{{
 "scores": {{
  "dor_do_mercado": {{"score": 0, "justificativa": ""}},
  "urgencia": {{"score": 0, "justificativa": ""}},
  "monetizacao": {{"score": 0, "justificativa": ""}},
  "escalabilidade": {{"score": 0, "justificativa": ""}},
  "aquisicao": {{"score": 0, "justificativa": ""}},
  "diferenciacao": {{"score": 0, "justificativa": ""}},
  "execucao": {{"score": 0, "justificativa": ""}},
  "potencial_de_conteudo": {{"score": 0, "justificativa": ""}}
 }},
 "rejection_reasons": [],
 "recommendation": "descartar | testar | priorizar"
}}"""


# Orchestrator


class Orchestrator:
    """
    Motor principal — debate GPT × Claude + scoring + filtro de rejeição.

    Parâmetros:
        gpt: instância OpenAIProvider (criada automaticamente se omitida)
        anthropic: instância AnthropicProvider (criada automaticamente se omitida)
        verbose: imprime progresso durante o debate
    """

    def __init__(
        self,
        gpt: Optional[OpenAIProvider] = None,
        anthropic: Optional[AnthropicProvider] = None,
        verbose: bool = True,
    ):
        self.gpt = gpt or OpenAIProvider()
        self.anthropic = anthropic or AnthropicProvider()
        self.verbose = verbose
        self._total_cost = 0.0
        self._total_latency = 0

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    # Passo 1: GPT propõe

    def _gpt_propose(self, signal: TrendSignal, prev_refinement: str = "") -> dict:
        self._log(" GPT propondo...")
        prompt = _prompt_propose(signal, prev_refinement)
        with tracker.track(
            agent="orch_core",
            model=self.gpt.model,
            action="gpt_propose",
            engine_name="orch_core",
            confidence="observed",
            run_type="internal_ops",
            tenant_mode="internal_portfolio",
        ):
            text, cost, lat = self.gpt.chat(_SYS_GPT_PROPOSER, prompt, max_tokens=1200)
        self._total_cost += cost
        self._total_latency += lat
        return _extract_json(text)

    # Passo 2: Claude critica

    def _claude_critique(self, proposal: dict, signal: TrendSignal, round_num: int) -> dict:
        self._log(" Claude criticando...")
        prompt = _prompt_critique(proposal, signal, round_num)
        with tracker.track(
            agent="orch_core",
            model=self.anthropic.model,
            action="claude_critique",
            engine_name="orch_core",
            confidence="observed",
            run_type="internal_ops",
            tenant_mode="internal_portfolio",
        ):
            text, cost, lat = self.anthropic.chat(
                _SYS_CLAUDE_CRITIC, prompt, max_tokens=1000, temperature=0.5
            )
        self._total_cost += cost
        self._total_latency += lat
        return _extract_json(text)

    # Passo 3: GPT refina

    def _gpt_refine(self, proposal: dict, critique: dict, signal: TrendSignal) -> dict:
        self._log(" GPT refinando...")
        prompt = _prompt_refine(proposal, critique, signal)
        with tracker.track(
            agent="orch_core",
            model=self.gpt.model,
            action="gpt_refine",
            engine_name="orch_core",
            confidence="observed",
            run_type="internal_ops",
            tenant_mode="internal_portfolio",
        ):
            text, cost, lat = self.gpt.chat(_SYS_GPT_PROPOSER, prompt, max_tokens=1200)
        self._total_cost += cost
        self._total_latency += lat
        return _extract_json(text)

    # Passo 4: Score final (Claude pontua)

    def _score_final(
        self, final_proposal: dict, signal: TrendSignal, debate_summary: str
    ) -> tuple[dict, float]:
        self._log(" Calculando score final...")
        prompt = _prompt_score(final_proposal, signal, debate_summary)
        with tracker.track(
            agent="orch_core",
            model=self.anthropic.model,
            action="score_final",
            engine_name="orch_core",
            confidence="observed",
            run_type="internal_ops",
            tenant_mode="internal_portfolio",
        ):
            text, cost, lat = self.anthropic.chat(
                _SYS_SCORER, prompt, max_tokens=800, temperature=0.2
            )
        self._total_cost += cost
        self._total_latency += lat
        return _extract_json(text), cost

    # Rejeição automática por regras duras

    def _apply_rejection_rules(
        self, proposal: dict, signal: TrendSignal, score_data: dict, total_score: float
    ) -> tuple[bool, List[str]]:
        reasons: List[str] = list(score_data.get("rejection_reasons", []))
        rejected = False

        # Regra 1: score total abaixo do threshold
        if total_score < REJECTION_THRESHOLD:
            reasons.append(f"Score {total_score}/100 abaixo do mínimo {REJECTION_THRESHOLD}")
            rejected = True

        # Regra 2: dor ou monetização nota ≤ 2
        scores = {k: v["score"] for k, v in score_data.get("scores", {}).items()}
        if scores.get("dor_do_mercado", 3) <= 2:
            reasons.append("Dor do mercado insuficiente (nota ≤ 2)")
            rejected = True
        if scores.get("monetizacao", 3) <= 2:
            reasons.append("Potencial de monetização insuficiente (nota ≤ 2)")
            rejected = True

        # Regra 3: sinal muito frio (médio < 4)
        if signal.raw_score < 4.0:
            reasons.append(f"Sinal fraco (média radar: {signal.raw_score}/10)")
            rejected = True

        # Regra 4: modelo de scorer diz descartar
        if score_data.get("recommendation") == "descartar":
            reasons.append("Scorer recomenda descarte direto")
            rejected = True

        return rejected, reasons

    # Método público principal

    def process_signal(self, signal: TrendSignal, debate_rounds: int = 3) -> OpportunityDecision:
        """
        Executa o pipeline completo: debate → scoring → filtro → decisão.

        Args:
            signal: sinal de tendência do Radar
            debate_rounds: número de rodadas GPT×Claude (mín 1, recomendado 3)

        Returns:
            OpportunityDecision com todos os campos preenchidos
        """
        self._total_cost = 0.0
        self._total_latency = 0
        debate_rounds = max(1, debate_rounds)
        debate_log: List[DebateRound] = []
        run_id = uuid.uuid4().hex[:8]

        tracer.start_run(
            run_id,
            agent="orch_core",
            signal=signal.title,
            rounds=debate_rounds,
            source=signal.source,
            raw_score=signal.raw_score,
        )

        self._log(f"\n{''*56}")
        self._log(f" ORCH CORE — {signal.title[:50]}")
        self._log(f" Radar score: {signal.raw_score}/10 | Rodadas: {debate_rounds}")
        self._log(f"{''*56}")

        proposal: dict = {}
        critique: dict = {}

        for r in range(1, debate_rounds + 1):
            self._log(f"\n Rodada {r}/{debate_rounds} ")
            prev_text = json.dumps(proposal, ensure_ascii=False) if proposal else ""
            proposal = self._gpt_propose(signal, prev_text)
            tracer.step(
                run_id,
                agent="orch_core",
                action="gpt_propose",
                round=r,
                input_summary=signal.title[:100],
                status="success",
            )

            critique = self._claude_critique(proposal, signal, r)
            tracer.step(
                run_id,
                agent="orch_core",
                action="claude_critique",
                round=r,
                verdict=critique.get("verdict", ""),
                input_summary=str(critique.get("critique_summary", ""))[:100],
                status="success",
            )

            # Se Claude detecta falha fatal e não é a última rodada → refina
            if critique.get("verdict") == "rejeitar" and r < debate_rounds:
                self._log(" Claude: rejeitar — GPT vai refinar")

            refined = (
                self._gpt_refine(proposal, critique, signal)
                if r < debate_rounds or critique.get("verdict") != "aceito"
                else proposal
            )
            tracer.step(
                run_id,
                agent="orch_core",
                action="gpt_refine",
                round=r,
                input_summary=str(refined.get("idea_name", ""))[:100],
                status="success",
            )

            debate_log.append(
                DebateRound(
                    round_num=r,
                    gpt_proposal=json.dumps(proposal, ensure_ascii=False),
                    claude_critique=json.dumps(critique, ensure_ascii=False),
                    refined_idea=json.dumps(refined, ensure_ascii=False),
                )
            )
            proposal = refined  # próxima rodada parte do refinamento

        # Score final
        debate_summary = f"{debate_rounds} rodadas de debate"
        score_raw, _ = self._score_final(proposal, signal, debate_summary)
        dim_scores = {k: v["score"] for k, v in score_raw.get("scores", {}).items()}
        total_score = _calc_score(dim_scores)
        tracer.step(
            run_id,
            agent="orch_core",
            action="score_final",
            total_score=total_score,
            input_summary=signal.title[:100],
            status="success",
        )

        # Confiança: concordância entre rodadas (simplificado: baseado em verdict)
        verdicts = []
        for dr in debate_log:
            try:
                c = json.loads(dr.claude_critique)
                verdicts.append(c.get("verdict", "refinar"))
            except Exception:
                pass
        n_accept = sum(1 for v in verdicts if v == "aceito")
        confidence = round(n_accept / max(len(verdicts), 1), 2)

        # Regras de rejeição
        rejected, rejection_reasons = self._apply_rejection_rules(
            proposal, signal, score_raw, total_score
        )
        tracer.step(
            run_id,
            agent="orch_core",
            action="rejection_check",
            rejected=rejected,
            reasons=rejection_reasons[:3] if rejection_reasons else [],
            status="success",
        )

        recommendation = score_raw.get("recommendation", "testar")
        if rejected and recommendation != "descartar":
            recommendation = "descartar"

        opp_score = OpportunityScore(
            total_score=total_score,
            dimension_scores=dim_scores,
            rejection_reasons=rejection_reasons,
            rejected=rejected,
            recommendation=recommendation,
            confidence=confidence,
        )

        self._log(f"\n{''*56}")
        self._log(f" Score final: {total_score}/100 | {' REJEITADA' if rejected else ' APROVADA'}")
        self._log(f" Recomendação: {recommendation} | Confiança: {confidence*100:.0f}%")
        self._log(f" Custo total: US$ {self._total_cost:.4f} | Latência: {self._total_latency}ms")

        tracer.end_run(
            run_id,
            agent="orch_core",
            total_score=total_score,
            rejected=rejected,
            recommendation=recommendation,
            confidence=confidence,
            cost_usd=round(self._total_cost, 4),
            latency_ms=self._total_latency,
        )

        return OpportunityDecision(
            idea_name=proposal.get("idea_name", "Oportunidade sem nome"),
            target_customer=proposal.get("target_customer", ""),
            core_problem=proposal.get("core_problem", ""),
            proposed_solution=proposal.get("proposed_solution", ""),
            offer_format=proposal.get("offer_format", ""),
            delivery_model=proposal.get("delivery_model", ""),
            pricing_hint=proposal.get("pricing_hint", ""),
            score=opp_score,
            next_actions=proposal.get("next_actions", []),
            debate_log=debate_log,
            signal_title=signal.title,
            signal_source=signal.source,
            generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            total_cost_usd=round(self._total_cost, 4),
            total_latency_ms=self._total_latency,
        )


# Funções utilitárias públicas


def trend_signal_from_dict(payload: Dict[str, Any]) -> TrendSignal:
    """Converte um dict do Radar em TrendSignal."""
    return TrendSignal(
        title=payload.get("title", "Sinal sem título"),
        description=payload.get("description", "Sem descrição"),
        source=payload.get("source", "desconhecida"),
        pain_level=float(payload.get("pain_level", 5.0)),
        urgency=float(payload.get("urgency", 5.0)),
        market_heat=float(payload.get("market_heat", 5.0)),
        evidence=payload.get("evidence", []),
        metadata=payload.get("metadata", {}),
    )


def save_decision_json(decision: OpportunityDecision, filepath: str) -> None:
    """Salva a decisão em JSON com todos os campos."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(asdict(decision), f, ensure_ascii=False, indent=2)
    print(f" Decisão salva em: {filepath}")


def load_decision_json(filepath: str) -> OpportunityDecision:
    """Lê um decision_output.json e reconstrói o objeto."""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    score = OpportunityScore(**data.pop("score"))
    log = [DebateRound(**r) for r in data.pop("debate_log", [])]
    return OpportunityDecision(score=score, debate_log=log, **data)


# Exemplo de uso


def main() -> None:
    parser = argparse.ArgumentParser(description="Orch Core — GPT × Claude debate")
    parser.add_argument("--payload", help="Arquivo JSON com o sinal de tendência")
    parser.add_argument("--rounds", type=int, default=3, help="Rodadas de debate (padrão: 3)")
    parser.add_argument("--output", default="decision_output.json", help="Arquivo de saída")
    args = parser.parse_args()

    if args.payload:
        with open(args.payload, encoding="utf-8") as f:
            signal_payload = json.load(f)
    else:
        signal_payload = {
            "title": "Pequenos negócios perdidos no controle financeiro diário",
            "description": (
                "Empresas pequenas têm dificuldade em entender caixa, margem, compras e preço. "
                "Buscam algo simples, rápido e que não exija implantação complexa."
            ),
            "source": "radar_interno",
            "pain_level": 9,
            "urgency": 8,
            "market_heat": 8,
            "evidence": [
                "Muitos negócios operam sem DRE gerencial.",
                "Baixa clareza de precificação e CMV.",
                "Busca por solução prática em WhatsApp/planilha.",
            ],
            "metadata": {"niche": "financeiro", "priority": "alta"},
        }

    signal = trend_signal_from_dict(signal_payload)

    orchestrator = Orchestrator(verbose=True)
    decision = orchestrator.process_signal(signal, debate_rounds=args.rounds)

    print("\n" + "" * 56)
    print(" OPORTUNIDADE PRIORIZADA")
    print("" * 56)
    print(f" Ideia: {decision.idea_name}")
    print(f" Cliente-alvo: {decision.target_customer}")
    print(f" Dor central: {decision.core_problem}")
    print(f" Solução: {decision.proposed_solution}")
    print(f" Oferta: {decision.offer_format}")
    print(f" Entrega: {decision.delivery_model}")
    print(f" Preço: {decision.pricing_hint}")
    print(f" Score: {decision.score.total_score}/100")
    print(f" Rejeitada: {decision.score.rejected}")
    if decision.score.rejection_reasons:
        for r in decision.score.rejection_reasons:
            print(f" • {r}")
    print(f" Recomendação: {decision.score.recommendation}")
    print(f" Confiança: {decision.score.confidence * 100:.0f}%")
    print("\n Próximas ações:")
    for action in decision.next_actions:
        print(f" → {action}")

    save_decision_json(decision, args.output)


if __name__ == "__main__":
    main()
