#!/usr/bin/env python3
"""
LLM Router -- Fallback inteligente entre provedores

Cadeia: Claude (Anthropic) -> OpenAI GPT -> Heuristica

Rastreia custos em outputs/llm_costs.json por provedor/mes.

Uso:
    from llm_router import get_router
    text, cost, latency_ms, provider = get_router().safe_call(prompt, system)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import httpx
from dotenv import load_dotenv

load_dotenv()
from observability import tracker  # noqa: E402

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4o")
OFFLINE = os.getenv("OFFLINE", "false").lower() == "true"

BASE_DIR = Path(__file__).parent
COSTS_FILE = BASE_DIR / "outputs" / "llm_costs.json"


# Rastreamento de custos


def _read_costs() -> dict:
    if COSTS_FILE.exists():
        try:
            return json.loads(COSTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_costs(data: dict) -> None:
    COSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    COSTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def track_cost(provider: str, cost_usd: float) -> None:
    """Acumula custo por provedor no mes corrente."""
    month_key = time.strftime("%Y-%m")
    data = _read_costs()
    month = data.setdefault(month_key, {})
    month[provider] = round(month.get(provider, 0.0) + cost_usd, 6)
    month["total"] = round(sum(v for k, v in month.items() if k != "total"), 6)
    _write_costs(data)


def get_monthly_cost_usd() -> float:
    """Retorna custo total de LLM no mes corrente (USD)."""
    month_key = time.strftime("%Y-%m")
    data = _read_costs()
    return data.get(month_key, {}).get("total", 0.0)


# LLMRouter


class LLMRouter:
    """
    Roteador de LLM com fallback automatico.

    Ordem de tentativa: Claude -> OpenAI -> Heuristica.
    Rastreia custos em outputs/llm_costs.json.
    """

    def __init__(self) -> None:
        self.last_provider: str = "none"
        self.degraded: bool = False  # True quando alguma API falhou

    def safe_call(
        self,
        prompt: str,
        system: str = "",
        context_hint: str = "generic",
        max_tokens: int = 1500,
        temperature: float = 0.5,
    ) -> Tuple[str, float, int, str]:
        """
        Tenta Claude -> OpenAI -> heuristica.

        Returns:
            (text, cost_usd, latency_ms, provider_used)
        """
        # Modo offline: pula APIs direto para heurística
        if OFFLINE:
            text = self._heuristic(prompt, context_hint)
            self.last_provider = "heuristic"
            self.degraded = True
            return text, 0.0, 0, "heuristic"

        # Tenta Claude
        if ANTHROPIC_API_KEY:
            try:
                text, cost, lat = self._call_claude(prompt, system, max_tokens, temperature)
                track_cost("claude", cost)
                self.last_provider = "claude"
                self.degraded = False
                return text, cost, lat, "claude"
            except Exception as exc:
                print(f" Claude falhou ({type(exc).__name__}): {str(exc)[:100]}")
                self.degraded = True

        # Tenta OpenAI
        if OPENAI_API_KEY:
            try:
                text, cost, lat = self._call_openai(prompt, system, max_tokens, temperature)
                track_cost("openai", cost)
                self.last_provider = "openai"
                self.degraded = True  # ainda degradado (Claude caiu)
                return text, cost, lat, "openai"
            except Exception as exc:
                print(f" OpenAI falhou ({type(exc).__name__}): {str(exc)[:100]}")

        # Heuristica
        print(" Modo heuristico -- resposta simulada (APIs indisponiveis)")
        text = self._heuristic(prompt, context_hint)
        self.last_provider = "heuristic"
        self.degraded = True
        return text, 0.0, 0, "heuristic"

    # Chamadas diretas

    def _call_claude(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> Tuple[str, float, int]:
        if os.getenv("MYO_USE_LLM_GATEWAY", "false").lower() == "true":
            from core.llm_gateway import get_gateway

            gw_resp = get_gateway().chat(
                system, prompt, max_tokens=max_tokens, temperature=temperature
            )
            with tracker.track(
                agent="llm_router",
                model=CLAUDE_MODEL,
                action="route_llm_call",
                engine_name="llm_router",
                confidence="observed",
            ) as t:
                t.set_tokens(input=gw_resp.input_tokens, output=gw_resp.output_tokens)
            return gw_resp.text, gw_resp.cost_usd, gw_resp.latency_ms

        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload: dict = {
            "model": CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        t0 = time.time()
        with tracker.track(
            agent="llm_router",
            model=CLAUDE_MODEL,
            action="route_llm_call",
            engine_name="llm_router",
            confidence="observed",
        ) as t:
            with httpx.Client(timeout=90) as c:
                resp = c.post(
                    "https://api.anthropic.com/v1/messages", json=payload, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
            u = data.get("usage", {})
            t.set_tokens(
                input=u.get("input_tokens", 0),
                output=u.get("output_tokens", 0),
            )
        text = data["content"][0]["text"]
        lat = int((time.time() - t0) * 1000)
        cost = round(u.get("input_tokens", 0) * 3e-6 + u.get("output_tokens", 0) * 15e-6, 6)
        return text, cost, lat

    def _call_openai(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> Tuple[str, float, int]:
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": GPT_MODEL,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        t0 = time.time()
        with tracker.track(
            agent="llm_router",
            model=GPT_MODEL,
            action="route_llm_call",
            engine_name="llm_router",
            confidence="observed",
        ) as t:
            with httpx.Client(timeout=90) as c:
                resp = c.post(
                    "https://api.openai.com/v1/chat/completions", json=payload, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
            u = data.get("usage", {})
            t.set_tokens(
                input=u.get("prompt_tokens", 0),
                output=u.get("completion_tokens", 0),
            )
        text = data["choices"][0]["message"]["content"]
        lat = int((time.time() - t0) * 1000)
        cost = round(u.get("prompt_tokens", 0) * 2.5e-6 + u.get("completion_tokens", 0) * 10e-6, 6)
        return text, cost, lat

    # Heuristica

    def _heuristic(self, prompt: str, context_hint: str) -> str:
        """
        Resposta heuristica quando todas as APIs falham.
        Detecta tipo de prompt e retorna JSON estruturado minimo.
        """
        p = prompt.lower()

        # Clustering de dores (pain_radar)
        if "cluster" in p or "reclamacoes" in p or "reclamacao" in p or "reclamações" in p:
            return json.dumps(
                {
                    "clusters": [
                        {
                            "name": "Dor Financeira Principal",
                            "core_pain": "Falta de clareza financeira e de precificacao",
                            "complaint_indices": [0, 1, 2, 3],
                            "frequency_score": 7.5,
                            "urgency_score": 8.0,
                            "monetization_score": 8.5,
                            "total_score": 8.0,
                            "tags": ["financeiro", "precificacao", "margem", "lucro"],
                        }
                    ],
                    "initial_product": {
                        "name": "CFO Digital Simplificado",
                        "tagline": "Clareza financeira para pequenos negocios em minutos",
                        "format": "assinatura mensal",
                        "target": "Donos de restaurantes e pequenos negocios (fat. R$30k-R$500k/mes)",
                        "core_feature": "DRE automatico + alerta de margem negativa",
                        "price_range": "R$97-R$297/mes",
                        "delivery": "App web + relatorio semanal automatizado",
                    },
                },
                ensure_ascii=False,
            )

        # Proposta de negocio (orch proposer)
        if "proponha" in p or "oportunidade" in p or "sinal" in p:
            return json.dumps(
                {
                    "idea_name": "CFO Digital para PMEs",
                    "target_customer": "Donos de restaurantes e pequenos negocios (fat. R$30k-R$500k/mes)",
                    "core_problem": "Dono nao sabe se esta lucrando de verdade -- precifica no achismo",
                    "proposed_solution": "Dashboard financeiro automatizado com DRE, CMV e alerta de margem",
                    "offer_format": "Assinatura mensal SaaS",
                    "delivery_model": "App web + integracao PDV + relatorio semanal por WhatsApp",
                    "pricing_hint": "R$197/mes -- abaixo do custo de 1 consultoria avulsa, com recorrencia",
                    "key_assumptions": [
                        "Dono usa smartphone e aceita automacao basica",
                        "Integracao com PDV e viavel via CSV ou API",
                        "R$197 e palatavel frente ao risco de fechar no vermelho",
                    ],
                    "next_actions": [
                        "Entrevistar 5 donos de restaurante esta semana",
                        "Montar landing page com proposta de valor",
                        "Criar MVP em planilha validada manualmente",
                    ],
                },
                ensure_ascii=False,
            )

        # Critica (orch critic)
        if "critic" in p or "criticamente" in p or "falha" in p or "risco" in p:
            return json.dumps(
                {
                    "verdict": "refinar",
                    "fatal_flaws": [
                        "Integracao com PDV pode ser complexa e cara de manter",
                        "Mercado tem ERPs estabelecidos com mais funcionalidades",
                    ],
                    "risks": [
                        "Churn alto se onboarding for dificil",
                        "Dependencia de integracao tecnica com terceiros",
                        "Preco pode parecer alto para micro negocios",
                    ],
                    "weak_assumptions": [
                        "Dono vai inserir dados manualmente se nao houver integracao",
                        "R$197 pode ser pesado para quem fatura R$30k/mes",
                    ],
                    "suggested_pivots": [
                        "Comecar com planilha premium + suporte humano",
                        "Focar nicho especifico (ex: so restaurantes) para integracao mais simples",
                    ],
                    "strongest_point": "Dor e real e frequente -- donos realmente nao sabem a margem",
                    "critique_summary": "Proposta valida. Entrada pelo nicho restaurante simplifica integracao. Validar preco com entrevistas antes de desenvolver.",
                },
                ensure_ascii=False,
            )

        # Scoring (orch scorer)
        if "score" in p or "avalie" in p or "criterio" in p or "nota" in p or "critério" in p:
            return json.dumps(
                {
                    "scores": {
                        "dor_do_mercado": {
                            "score": 4,
                            "justificativa": "Dor real e frequente -- dono nao sabe a margem",
                        },
                        "urgencia": {
                            "score": 4,
                            "justificativa": "Risco de fechar no negativo cria urgencia",
                        },
                        "monetizacao": {
                            "score": 4,
                            "justificativa": "R$197/mes x 100 clientes = R$19.700 MRR viavel",
                        },
                        "escalabilidade": {
                            "score": 3,
                            "justificativa": "SaaS escalavel mas onboarding pode ser gargalo",
                        },
                        "aquisicao": {
                            "score": 3,
                            "justificativa": "Donos de restaurante acessiveis via redes sociais",
                        },
                        "diferenciacao": {
                            "score": 3,
                            "justificativa": "Diferenciacao por nicho e simplicidade",
                        },
                        "execucao": {
                            "score": 4,
                            "justificativa": "Stack Python/API/Claude plenamente viavel",
                        },
                        "potencial_de_conteudo": {
                            "score": 4,
                            "justificativa": "Rico em conteudo educacional sobre margem",
                        },
                    },
                    "rejection_reasons": [],
                    "recommendation": "testar",
                },
                ensure_ascii=False,
            )

        # Analise competitiva (competitor_research)
        if (
            "competitor" in p
            or "concorrente" in p
            or "lacuna" in p
            or "market_gap" in p
            or "attack_vector" in p
        ):
            return json.dumps(
                {
                    "market_gaps": [
                        {
                            "description": "Falta de solucao simples e acessivel para pequenos negocios",
                            "severity": "alta",
                            "exploitable": True,
                        },
                        {
                            "description": "ERPs complexos nao servem para negocios com 1-5 funcionarios",
                            "severity": "alta",
                            "exploitable": True,
                        },
                    ],
                    "attack_vectors": [
                        {
                            "competitor": "ERP Alpha",
                            "weakness": "Complexo e caro",
                            "our_advantage": "Onboarding em 5 minutos, preco fixo acessivel",
                            "priority": "alta",
                        },
                        {
                            "competitor": "Consultoria Beta",
                            "weakness": "Nao escala, ticket alto",
                            "our_advantage": "Automacao substitui consultor a 1/10 do custo",
                            "priority": "media",
                        },
                    ],
                    "positioning": {
                        "headline": "O CFO digital para quem nao tem tempo de ser CFO",
                        "differentiators": [
                            "Onboarding em minutos",
                            "Preco fixo sem surpresas",
                            "Relatorio automatico semanal",
                        ],
                        "avoid": ["Nao copiar interface de ERP", "Nao usar jargao contabil"],
                        "price_strategy": "R$97-R$297/mes -- abaixo de 1 consultoria avulsa",
                    },
                    "market_summary": (
                        "Mercado dominado por ERPs caros e consultorias inacessiveis. "
                        "Gap claro para SaaS simples focado em visibilidade financeira."
                    ),
                    "risk_level": "medio",
                    "opportunity_size": "grande",
                },
                ensure_ascii=False,
            )

        # Generico
        return json.dumps(
            {
                "status": "heuristic",
                "message": "Resposta heuristica -- APIs indisponiveis",
                "result": "Configure ANTHROPIC_API_KEY ou OPENAI_API_KEY no .env para analise real.",
            },
            ensure_ascii=False,
        )


# Singleton global

_router: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
