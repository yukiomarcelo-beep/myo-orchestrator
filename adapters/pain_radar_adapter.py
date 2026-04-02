#!/usr/bin/env python3
"""
Pain Radar Adapter

Porta de entrada das reclamações brutas.
Usa Claude para clusterizar dores, pontuar e gerar produto inicial.

Uso direto:
 python pain_radar_adapter.py # roda exemplo embutido
 python pain_radar_adapter.py --input c.json # lê reclamações de arquivo

Como módulo:
 from pain_radar_adapter import PainRadarAdapter
 adapter = PainRadarAdapter()
 result = adapter.run(complaints_payload, competitors_payload, output_path)
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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"


# Dataclasses

@dataclass
class Complaint:
    text: str
    source: str = "unknown"
    author: Optional[str] = None
    url: Optional[str] = None
    frequency_hint: float = 1.0
    emotional_intensity: float = 5.0
    commercial_intent: float = 5.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComplaintCluster:
    """Grupo de dores similares já pontuado."""
    name: str
    core_pain: str
    complaints: List[Dict[str, Any]]
    frequency_score: float = 0.0 # 0–10
    urgency_score: float = 0.0 # 0–10
    monetization_score: float = 0.0 # 0–10
    total_score: float = 0.0
    tags: List[str] = field(default_factory=list)


@dataclass
class InitialProduct:
    """Produto inicial gerado a partir do cluster vencedor."""
    name: str
    tagline: str
    format: str # ex: assinatura, serviço pontual, produto digital
    target: str
    core_feature: str
    price_range: str
    delivery: str


@dataclass
class PainRadarResult:
    """Saída completa do Pain Radar."""
    clusters: List[ComplaintCluster]
    top_cluster: ComplaintCluster
    initial_product: InitialProduct
    total_complaints: int
    has_competitors: bool
    latency_ms: int = 0
    cost_usd: float = 0.0
    generated_at: str = ""


# Pain Engine (Claude)

class PainEngine:
    """
    Motor de análise de dores usando Claude.
    Clusteriza reclamações, pontua clusters e gera produto inicial.
    """

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key or ANTHROPIC_API_KEY
        self.model = model or CLAUDE_MODEL
        # Chave não obrigatória — llm_router faz fallback para OpenAI/heurística

    def _call(self, prompt: str, system: str = "", max_tokens: int = 2000,
              temperature: float = 0.3) -> tuple[str, float, int]:
        from agents.llm_router import get_router
        text, cost, latency_ms, provider = get_router().safe_call(
            prompt, system,
            context_hint="pain_radar",
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if provider != "claude":
            print(f" Pain Radar via {provider}")
        return text, cost, latency_ms

    @staticmethod
    def _extract_json(text: str) -> Any:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        start = text.find("{") if "{" in text else text.find("[")
        end = text.rfind("}") + 1 if "}" in text else text.rfind("]") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
        raise ValueError(f"JSON não encontrado:\n{text[:200]}")

    def _build_cluster_prompt(self, complaints: List[Dict],
                              competitors: List[Dict]) -> str:
        complaints_txt = "\n".join(
            f'{i+1}. [{c["source"]}] "{c["text"]}" '
            f'(freq={c["frequency_hint"]}, intensidade={c["emotional_intensity"]}, '
            f'intent_comercial={c["commercial_intent"]})'
            for i, c in enumerate(complaints)
        )
        comp_txt = ""
        if competitors:
            comp_txt = "\n\nCONCORRENTES PRESENTES:\n" + "\n".join(
                f'- {c["name"]}: {c["summary"]} | Fraquezas: {", ".join(c.get("weaknesses", []))}'
                for c in competitors
            )

        return f"""Você é um analista de mercado especializado em identificar dores reais de consumidores.

Analise as reclamações abaixo e:
1. Agrupe em clusters de dor (máx 4, mín 1)
2. Para cada cluster, identifique a dor central em 1 frase objetiva
3. Pontue cada cluster de 0 a 10 em: frequência, urgência, monetização
4. Calcule total_score = (frequência * 0.3 + urgência * 0.4 + monetização * 0.3)
5. Proponha um produto inicial para o cluster com maior total_score

RECLAMAÇÕES ({len(complaints)} itens):
{complaints_txt}
{comp_txt}

Responda APENAS em JSON válido:
{{
 "clusters": [
  {{
   "name": "nome curto do cluster",
   "core_pain": "a dor central em 1 frase direta",
   "complaint_indices": [0, 1],
   "frequency_score": 0,
   "urgency_score": 0,
   "monetization_score": 0,
   "total_score": 0,
   "tags": ["tag1", "tag2"]
  }}
 ],
 "initial_product": {{
  "name": "nome do produto",
  "tagline": "proposta de valor em 1 frase",
  "format": "formato (ex: assinatura mensal, app, consultoria)",
  "target": "perfil exato do cliente",
  "core_feature": "funcionalidade principal",
  "price_range": "faixa de preço sugerida",
  "delivery": "como entrega valor"
 }}
}}"""

    def process_complaints(self, raw_items: List[Dict],
                           competitors: List[Dict]) -> Dict[str, Any]:
        """
        Clusteriza reclamações e gera produto inicial.
        Retorna dict serializável compatível com PainRadarResult.
        """
        prompt = self._build_cluster_prompt(raw_items, competitors)
        text, cost, latency = self._call(
            prompt,
            system="Você é um analista de mercado preciso. Responda apenas com JSON válido.",
        )
        data = self._extract_json(text)

        # Monta ComplaintCluster para cada cluster retornado
        clusters: List[ComplaintCluster] = []
        for c in data.get("clusters", []):
            indices = c.get("complaint_indices", [])
            complaints = [raw_items[i] for i in indices if i < len(raw_items)]
            clusters.append(ComplaintCluster(
                name = c.get("name", "Cluster"),
                core_pain = c.get("core_pain", ""),
                complaints = complaints,
                frequency_score = float(c.get("frequency_score", 0)),
                urgency_score = float(c.get("urgency_score", 0)),
                monetization_score = float(c.get("monetization_score", 0)),
                total_score = float(c.get("total_score", 0)),
                tags = c.get("tags", []),
            ))

        clusters.sort(key=lambda x: x.total_score, reverse=True)
        top = clusters[0] if clusters else ComplaintCluster(
            name="Geral", core_pain="Dor não identificada", complaints=raw_items
        )

        prod_raw = data.get("initial_product", {})
        product = InitialProduct(
            name = prod_raw.get("name", "Produto sem nome"),
            tagline = prod_raw.get("tagline", ""),
            format = prod_raw.get("format", ""),
            target = prod_raw.get("target", ""),
            core_feature = prod_raw.get("core_feature", ""),
            price_range = prod_raw.get("price_range", ""),
            delivery = prod_raw.get("delivery", ""),
        )

        result = PainRadarResult(
            clusters = clusters,
            top_cluster = top,
            initial_product = product,
            total_complaints = len(raw_items),
            has_competitors = bool(competitors),
            latency_ms = latency,
            cost_usd = round(cost, 4),
            generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        return asdict(result)


# Adapter

class PainRadarAdapter:
    """
    Porta de entrada das reclamações.
    Normaliza, aciona o PainEngine e salva saída.
    """

    def __init__(self, engine: Optional[PainEngine] = None):
        self.engine = engine or PainEngine()

    def run(
        self,
        complaints_payload: List[Dict[str, Any]],
        competitors_payload: List[Dict[str, Any]] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executa análise de dores.

        Args:
            complaints_payload: lista de reclamações brutas
            competitors_payload: lista de concorrentes (opcional)
            output_path: caminho para salvar JSON (opcional)

        Returns:
            dict com clusters, top_cluster, initial_product
        """
        complaints = [self._normalize_complaint(c) for c in complaints_payload]
        competitors = [self._normalize_competitor(c) for c in (competitors_payload or [])]

        result = self.engine.process_complaints(
            raw_items = complaints,
            competitors = competitors,
        )

        if output_path:
            self._save_json(result, output_path)

        return result

    def _normalize_complaint(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "text": str(item.get("text", "")).strip(),
            "source": item.get("source", "unknown"),
            "author": item.get("author"),
            "url": item.get("url"),
            "frequency_hint": float(item.get("frequency_hint", 1.0)),
            "emotional_intensity": float(item.get("emotional_intensity", 5.0)),
            "commercial_intent": float(item.get("commercial_intent", 5.0)),
            "metadata": item.get("metadata", {}),
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
    parser = argparse.ArgumentParser(description="Pain Radar Adapter")
    parser.add_argument("--input", help="JSON com complaints_payload")
    parser.add_argument("--output", default="outputs/pain_radar_output.json")
    args = parser.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
        complaints_payload = data.get("complaints", data if isinstance(data, list) else [])
        competitors_payload = data.get("competitors", [])
    else:
        complaints_payload = [
            {
                "text": "Não consigo saber se meu restaurante realmente deu lucro no mês.",
                "source": "reddit",
                "frequency_hint": 3,
                "emotional_intensity": 8,
                "commercial_intent": 9,
            },
            {
                "text": "Precifico no achismo e minha margem some.",
                "source": "youtube_comments",
                "frequency_hint": 2,
                "emotional_intensity": 8,
                "commercial_intent": 9,
            },
            {
                "text": "Planilha funciona até certo ponto, depois vira bagunça.",
                "source": "forum",
                "frequency_hint": 2,
                "emotional_intensity": 6,
                "commercial_intent": 7,
            },
        ]
        competitors_payload = [
            {
                "name": "Sistema Financeiro X",
                "url": "https://exemplo.com/x",
                "category": "software financeiro",
                "summary": "Controle de caixa e relatórios básicos.",
                "strengths": ["interface simples", "marca conhecida"],
                "weaknesses": ["não resolve precificação", "implantação lenta"],
                "pricing": "R$149/mês",
                "target_customer": "pequenos negócios",
            }
        ]

    adapter = PainRadarAdapter()
    output = adapter.run(
        complaints_payload = complaints_payload,
        competitors_payload = competitors_payload,
        output_path = args.output,
    )

    print("\n=== PAIN RADAR ===")
    print(f"Clusters encontrados: {len(output['clusters'])}")
    print(f"Top cluster: {output['top_cluster']['name']} (score: {output['top_cluster']['total_score']})")
    print(f"Dor central: {output['top_cluster']['core_pain']}")
    print(f"Produto inicial: {output['initial_product']['name']}")
    print(f"Tagline: {output['initial_product']['tagline']}")
    print(f"Custo: US$ {output['cost_usd']} | Latência: {output['latency_ms']}ms")
