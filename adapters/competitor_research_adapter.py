#!/usr/bin/env python3
"""
Competitor Research Adapter

Analisa concorrentes contra um cluster de dor priorizado.
Usa GPT para mapear gaps, vetores de ataque e posicionamento.

Uso direto:
 python competitor_research_adapter.py # roda exemplo embutido
 python competitor_research_adapter.py --input data.json

Como módulo:
 from competitor_research_adapter import CompetitorResearchAdapter
 adapter = CompetitorResearchAdapter()
 result = adapter.run(pain_cluster_payload, competitors_payload, output_path)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4o")


# Dataclasses

@dataclass
class MarketGap:
    """Lacuna identificada no mercado atual."""
    description: str
    severity: str # alta | media | baixa
    exploitable: bool = True


@dataclass
class AttackVector:
    """Vetor de ataque contra um concorrente específico."""
    competitor: str
    weakness: str
    our_advantage: str
    priority: str # alta | media | baixa


@dataclass
class Positioning:
    """Posicionamento estratégico recomendado."""
    headline: str # 1 frase de posicionamento
    differentiators: List[str]
    avoid: List[str] # o que não fazer / não copiar
    price_strategy: str


@dataclass
class CompetitorIntel:
    """Inteligência competitiva completa para um cluster de dor."""
    pain_name: str
    market_gaps: List[MarketGap]
    attack_vectors: List[AttackVector]
    positioning: Positioning
    market_summary: str
    risk_level: str # baixo | medio | alto
    opportunity_size: str # pequeno | medio | grande


@dataclass
class CompetitorResearchResult:
    """Saída completa do Competitor Research."""
    intel: CompetitorIntel
    raw_clusters: List[Dict[str, Any]]
    competitor_count: int
    latency_ms: int = 0
    cost_usd: float = 0.0
    generated_at: str = ""


# Competitor Engine (GPT)

class CompetitorEngine:
    """
    Motor de análise competitiva usando GPT.
    Analisa gaps, vetores de ataque e posicionamento.
    """

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key or OPENAI_API_KEY
        self.model = model or GPT_MODEL
        # Chave não obrigatória — llm_router faz fallback Claude/heurística

    def _call(self, system: str, user: str, max_tokens: int = 2000,
              temperature: float = 0.4) -> tuple[str, float, int]:
        from agents.llm_router import get_router
        text, cost, latency_ms, provider = get_router().safe_call(
            user, system, context_hint="competitor_research",
            max_tokens=max_tokens, temperature=temperature,
        )
        if provider not in ("openai",):
            print(f" Competitor Research via {provider}")
        return text, cost, latency_ms

    @staticmethod
    def _extract_json(text: str) -> Any:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
        raise ValueError(f"JSON não encontrado:\n{text[:200]}")

    def _build_analysis_prompt(self, cluster: Dict, competitors: List[Dict]) -> str:
        complaints_txt = "\n".join(
            f' - "{c.get("text", "")}"' for c in cluster.get("complaints", [])
        )
        comps_txt = "\n".join(
            f"""- {c['name']} ({c.get('category','')})
  Resumo: {c.get('summary','')}
  Pontos fortes: {', '.join(c.get('strengths',[]))}
  Fraquezas: {', '.join(c.get('weaknesses',[]))}
  Preço: {c.get('pricing','desconhecido')}
  Cliente-alvo: {c.get('target_customer','desconhecido')}"""
            for c in competitors
        )

        return f"""Você é um estrategista de produto com especialidade em análise competitiva.

CLUSTER DE DOR PRIORIZADO:
Nome: {cluster.get('name', '')}
Dor central: {cluster.get('core_pain', '')}
Score: {cluster.get('total_score', 0)} | Frequência: {cluster.get('frequency_score', 0)} | Urgência: {cluster.get('urgency_score', 0)} | Monetização: {cluster.get('monetization_score', 0)}

Reclamações representativas:
{complaints_txt}

CONCORRENTES ({len(competitors)}):
{comps_txt}

Analise o mercado e responda APENAS em JSON válido:
{{
 "market_gaps": [
  {{
   "description": "lacuna específica não atendida",
   "severity": "alta | media | baixa",
   "exploitable": true
  }}
 ],
 "attack_vectors": [
  {{
   "competitor": "nome do concorrente",
   "weakness": "fraqueza específica a explorar",
   "our_advantage": "como podemos ser melhores neste ponto",
   "priority": "alta | media | baixa"
  }}
 ],
 "positioning": {{
  "headline": "nosso posicionamento em 1 frase",
  "differentiators": ["diferenciador 1", "diferenciador 2", "diferenciador 3"],
  "avoid": ["o que não fazer / não copiar"],
  "price_strategy": "estratégia de precificação recomendada"
 }},
 "market_summary": "resumo do mercado em 2 frases objetivas",
 "risk_level": "baixo | medio | alto",
 "opportunity_size": "pequeno | medio | grande"
}}"""

    def analyze(self, cluster: Dict, competitors: List[Dict]) -> Dict[str, Any]:
        """
        Analisa mercado competitivo para um cluster de dor.
        Retorna dict serializável compatível com CompetitorResearchResult.
        """
        prompt = self._build_analysis_prompt(cluster, competitors)
        text, cost, latency = self._call(
            system="Você é um estrategista de produto especializado em análise competitiva. "
                   "Responda apenas com JSON válido.",
            user=prompt,
        )
        data = self._extract_json(text)

        # Monta dataclasses
        gaps = [MarketGap(**g) for g in data.get("market_gaps", [])]

        vectors = [
            AttackVector(
                competitor = v.get("competitor", ""),
                weakness = v.get("weakness", ""),
                our_advantage = v.get("our_advantage", ""),
                priority = v.get("priority", "media"),
            )
            for v in data.get("attack_vectors", [])
        ]

        pos_raw = data.get("positioning", {})
        positioning = Positioning(
            headline = pos_raw.get("headline", ""),
            differentiators = pos_raw.get("differentiators", []),
            avoid = pos_raw.get("avoid", []),
            price_strategy = pos_raw.get("price_strategy", ""),
        )

        intel = CompetitorIntel(
            pain_name = cluster.get("name", ""),
            market_gaps = gaps,
            attack_vectors = vectors,
            positioning = positioning,
            market_summary = data.get("market_summary", ""),
            risk_level = data.get("risk_level", "medio"),
            opportunity_size = data.get("opportunity_size", "medio"),
        )

        result = CompetitorResearchResult(
            intel = intel,
            raw_clusters = [cluster],
            competitor_count = len(competitors),
            latency_ms = latency,
            cost_usd = round(cost, 4),
            generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        return asdict(result)


# Adapter

class CompetitorResearchAdapter:
    """
    Camada focada em inteligência competitiva.
    Recebe um cluster de dor priorizado + concorrentes.
    Devolve mapa competitivo + estratégia de ataque.
    """

    def __init__(self, engine: Optional[CompetitorEngine] = None):
        self.engine = engine or CompetitorEngine()

    def run(
        self,
        pain_cluster_payload: Dict[str, Any],
        competitors_payload: List[Dict[str, Any]],
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executa análise competitiva.

        Args:
            pain_cluster_payload: cluster de dor priorizado (formato PainRadarResult.top_cluster)
            competitors_payload: lista de concorrentes
            output_path: caminho para salvar JSON (opcional)

        Returns:
            dict com intel competitiva completa
        """
        cluster = self._normalize_cluster(pain_cluster_payload)
        competitors = [self._normalize_competitor(c) for c in competitors_payload]

        result = self.engine.analyze(
            cluster = cluster,
            competitors = competitors,
        )

        if output_path:
            self._save_json(result, output_path)

        return result

    def _normalize_cluster(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": item.get("name", "Cluster"),
            "core_pain": item.get("core_pain", ""),
            "complaints": item.get("complaints", []),
            "frequency_score": float(item.get("frequency_score", 5.0)),
            "urgency_score": float(item.get("urgency_score", 5.0)),
            "monetization_score": float(item.get("monetization_score", 5.0)),
            "total_score": float(item.get("total_score", 5.0)),
            "tags": item.get("tags", []),
        }

    def _normalize_competitor(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": item.get("name", "Concorrente sem nome"),
            "url": item.get("url"),
            "category": item.get("category", "unknown"),
            "summary": item.get("summary", "Sem resumo"),
            "strengths": item.get("strengths", []) or [],
            "weaknesses": item.get("weaknesses", []) or [],
            "pricing": item.get("pricing"),
            "target_customer": item.get("target_customer"),
            "metadata": item.get("metadata", {}),
        }

    def _save_json(self, payload: Dict[str, Any], filepath: str) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f" Salvo em: {filepath}")


# Exemplo de uso

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Competitor Research Adapter")
    parser.add_argument("--input", help="JSON com pain_cluster_payload e competitors_payload")
    parser.add_argument("--output", default="outputs/competitor_intel_output.json")
    args = parser.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
        pain_cluster_payload = data["pain_cluster"]
        competitors_payload = data["competitors"]
    else:
        pain_cluster_payload = {
            "name": "Financeiro",
            "core_pain": "Donos de pequenos negócios não entendem margem, lucro e precificação.",
            "complaints": [
                {
                    "text": "Meu preço está errado e não sei onde perco dinheiro.",
                    "source": "reddit",
                    "frequency_hint": 2,
                    "emotional_intensity": 8,
                    "commercial_intent": 9,
                }
            ],
            "frequency_score": 8,
            "urgency_score": 8,
            "monetization_score": 9,
            "total_score": 8.3,
        }
        competitors_payload = [
            {
                "name": "ERP Alpha",
                "url": "https://exemplo.com/erp-alpha",
                "category": "erp",
                "summary": "Sistema robusto para gestão empresarial.",
                "strengths": ["muitos módulos", "relatórios completos"],
                "weaknesses": ["complexo", "implantação lenta", "caro"],
                "pricing": "Sob consulta",
                "target_customer": "PMEs",
            },
            {
                "name": "Consultoria Beta",
                "url": "https://exemplo.com/consultoria-beta",
                "category": "consultoria financeira",
                "summary": "Consultoria para margem e gestão de caixa.",
                "strengths": ["ajuste humano", "diagnóstico profundo"],
                "weaknesses": ["baixa escala", "ticket alto"],
                "pricing": "R$2500/mês",
                "target_customer": "restaurantes e varejo",
            },
        ]

    adapter = CompetitorResearchAdapter()
    output = adapter.run(
        pain_cluster_payload = pain_cluster_payload,
        competitors_payload = competitors_payload,
        output_path = args.output,
    )

    print("\n=== COMPETITOR INTEL ===")
    intel = output["intel"]
    print(f"Cluster: {intel['pain_name']}")
    print(f"Tamanho do mercado: {intel['opportunity_size']} | Risco: {intel['risk_level']}")
    print(f"Resumo: {intel['market_summary']}")
    print(f"\nLacunas ({len(intel['market_gaps'])}):")
    for g in intel["market_gaps"]:
        print(f" [{g['severity']}] {g['description']}")
    print(f"\nVetores de ataque ({len(intel['attack_vectors'])}):")
    for v in intel["attack_vectors"]:
        print(f" vs {v['competitor']}: {v['weakness']} → {v['our_advantage']}")
    print(f"\nPositionamento: {intel['positioning']['headline']}")
    print(f"Custo: US$ {output['cost_usd']} | Latência: {output['latency_ms']}ms")
