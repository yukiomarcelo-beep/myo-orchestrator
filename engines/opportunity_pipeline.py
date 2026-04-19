#!/usr/bin/env python3
"""
Opportunity Pipeline

Pipeline completo: reclamações → dor → concorrência → sinal → debate → decisão.

FLUXO:
 reclamações brutas
 → PainRadarAdapter (clusteriza dores, pontua, gera produto inicial)
 → CompetitorResearch (gaps de mercado, vetores de ataque, posicionamento)
 → signal_builder (monta TrendSignal com dados das duas etapas)
 → Orchestrator (debate GPT×Claude, scoring, filtro)
 → OpportunityDecision (decisão final pronta para o Executor)

Uso direto:
 python opportunity_pipeline.py # roda exemplo embutido
 python opportunity_pipeline.py --input data.json
 python opportunity_pipeline.py --rounds 5 --output-dir outputs/meu_run

Como módulo:
 from opportunity_pipeline import OpportunityPipeline
 pipeline = OpportunityPipeline()
 result = pipeline.run(complaints_payload, competitors_payload, output_dir)
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()
from observability import tracker, tracer

from adapters.pain_radar_adapter import PainRadarAdapter
from adapters.competitor_research_adapter import CompetitorResearchAdapter
from core.orch_core import (
    Orchestrator,
    OpportunityDecision,
    TrendSignal,
    trend_signal_from_dict,
    save_decision_json,
)


# Signal Builder

def _build_signal(pain_result: Dict[str, Any],
                  comp_result: Dict[str, Any]) -> TrendSignal:
    """
    Monta um TrendSignal rico combinando saídas do Pain Radar
    e do Competitor Research para alimentar o Orchestrator.
    """
    top = pain_result["top_cluster"]
    intel = comp_result["intel"]
    prod = pain_result["initial_product"]

    # Evidências: reclamações top + gaps de mercado
    evidence: List[str] = []
    for c in top.get("complaints", [])[:4]:
        txt = c.get("text", "")
        if txt:
            evidence.append(f'[{c.get("source","?")}] "{txt}"')
    for gap in intel.get("market_gaps", [])[:3]:
        if gap.get("severity") in ("alta", "media"):
            evidence.append(f'Gap [{gap["severity"]}]: {gap["description"]}')

    # Descrição enriquecida com posicionamento competitivo
    pos = intel.get("positioning", {})
    diff_txt = " | ".join(pos.get("differentiators", [])[:2])
    description = (
        f"{top['core_pain']} "
        f"Produto inicial: {prod['name']} — {prod['tagline']}. "
        f"Diferenciadores: {diff_txt}. "
        f"Tamanho do mercado: {intel.get('opportunity_size','?')} | "
        f"Risco: {intel.get('risk_level','?')}."
    )

    # Scores do sinal: média entre cluster + dados do intel
    freq = top.get("frequency_score", 5.0)
    urg = top.get("urgency_score", 5.0)
    heat = top.get("monetization_score", 5.0)

    return trend_signal_from_dict({
        "title": top["name"],
        "description": description,
        "source": "opportunity_pipeline",
        "pain_level": min(10.0, freq),
        "urgency": min(10.0, urg),
        "market_heat": min(10.0, heat),
        "evidence": evidence,
        "metadata": {
            "pain_cluster": top["name"],
            "product_name": prod["name"],
            "opportunity_size": intel.get("opportunity_size", ""),
            "risk_level": intel.get("risk_level", ""),
            "competitor_count": comp_result.get("competitor_count", 0),
        },
    })


# Pipeline

class OpportunityPipeline:
    """
    Orquestra os três estágios: Pain Radar → Competitor Research → Orch Core.

    Args:
        debate_rounds: padrão 3, pode ser sobrescrito em run()
        verbose: imprime progresso de cada etapa
    """

    def __init__(
        self,
        pain_adapter: Optional[PainRadarAdapter] = None,
        competitor_adapter: Optional[CompetitorResearchAdapter] = None,
        orchestrator: Optional[Orchestrator] = None,
        verbose: bool = True,
    ):
        self.pain_adapter = pain_adapter or PainRadarAdapter()
        self.competitor_adapter = competitor_adapter or CompetitorResearchAdapter()
        self.orchestrator = orchestrator or Orchestrator(verbose=verbose)
        self.verbose = verbose

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def run(
        self,
        complaints_payload: List[Dict[str, Any]],
        competitors_payload: List[Dict[str, Any]],
        output_dir: Optional[str] = None,
        debate_rounds: int = 3,
    ) -> Dict[str, Any]:
        """
        Executa o pipeline completo.

        Args:
            complaints_payload: reclamações brutas do Radar
            competitors_payload: concorrentes já coletados
            output_dir: diretório para salvar os 3 JSONs de saída
            debate_rounds: rodadas de debate no Orchestrator

        Returns:
            dict com pain_result, comp_result, decision e metadados consolidados
        """
        t_start = time.time()
        run_id = uuid.uuid4().hex[:8]
        tracer.start_run(run_id,
                         pipeline="opportunity_pipeline",
                         objective=f"{len(complaints_payload)} reclamações → decisão",
                         engine_name="opportunity_pipeline")

        # Etapa 1: Pain Radar
        self._log("\n" + "" * 60)
        self._log(" ETAPA 1/3 — Pain Radar")
        self._log("" * 60)
        pain_out = output_dir and str(Path(output_dir) / "01_pain_radar.json")
        pain_result = self.pain_adapter.run(
            complaints_payload = complaints_payload,
            competitors_payload = competitors_payload,
            output_path = pain_out,
        )
        top = pain_result["top_cluster"]
        self._log(f" Top cluster: {top['name']} (score {top['total_score']})")
        self._log(f" Dor: {top['core_pain']}")
        tracer.step(run_id, agent="opportunity_pipeline", action="pain_radar",
                    cluster=top["name"], score=top["total_score"], status="success")
        tracer.update_progress(run_id, progress=33, action="pain_radar")

        # Etapa 2: Competitor Research
        self._log("\n" + "" * 60)
        self._log(" ETAPA 2/3 — Competitor Research")
        self._log("" * 60)
        comp_out = output_dir and str(Path(output_dir) / "02_competitor_intel.json")
        comp_result = self.competitor_adapter.run(
            pain_cluster_payload = top,
            competitors_payload = competitors_payload,
            output_path = comp_out,
        )
        intel = comp_result["intel"]
        self._log(f" Gaps: {len(intel['market_gaps'])} | Vetores: {len(intel['attack_vectors'])}")
        self._log(f" Mercado: {intel['opportunity_size']} | Risco: {intel['risk_level']}")
        tracer.step(run_id, agent="opportunity_pipeline", action="competitor_research",
                    gaps=len(intel["market_gaps"]), vectors=len(intel["attack_vectors"]),
                    opportunity_size=intel["opportunity_size"], status="success")
        tracer.update_progress(run_id, progress=66, action="competitor_research")

        # Etapa 3: Orchestrator (debate GPT × Claude)
        self._log("\n" + "" * 60)
        self._log(" ETAPA 3/3 — Orchestrator (debate GPT × Claude)")
        self._log("" * 60)
        signal = _build_signal(pain_result, comp_result)
        decision = self.orchestrator.process_signal(signal, debate_rounds=debate_rounds)

        if output_dir:
            dec_path = str(Path(output_dir) / "03_decision.json")
            save_decision_json(decision, dec_path)
        tracer.step(run_id, agent="opportunity_pipeline", action="orchestrator",
                    idea=decision.idea_name, score=decision.score.total_score,
                    rejected=decision.score.rejected, status="success")
        tracer.update_progress(run_id, progress=100, action="orchestrator")

        # Saída consolidada
        total_ms = int((time.time() - t_start) * 1000)
        total_cost = round(
            pain_result.get("cost_usd", 0) +
            comp_result.get("cost_usd", 0) +
            decision.total_cost_usd, 4
        )

        output = self._build_output(pain_result, comp_result, decision,
                                    total_ms, total_cost)

        if output_dir:
            self._save_json(output, str(Path(output_dir) / "00_pipeline_output.json"))

        self._log("\n" + "" * 60)
        self._log(f" PIPELINE COMPLETO em {total_ms}ms | Custo total: US$ {total_cost}")
        self._log("" * 60)

        tracer.end_run(run_id, pipeline="opportunity_pipeline",
                       status=output["status"], total_ms=total_ms,
                       total_cost_usd=total_cost)
        return output

    def _build_output(
        self,
        pain_result: Dict[str, Any],
        comp_result: Dict[str, Any],
        decision: OpportunityDecision,
        total_ms: int,
        total_cost: float,
    ) -> Dict[str, Any]:
        top = pain_result["top_cluster"]
        intel = comp_result["intel"]
        score = decision.score

        return {
            "status": "aprovado" if not score.rejected else "rejeitado",
            "idea_name": decision.idea_name,
            "summary": {
                "core_pain": top["core_pain"],
                "target_customer": decision.target_customer,
                "proposed_solution": decision.proposed_solution,
                "offer_format": decision.offer_format,
                "pricing_hint": decision.pricing_hint,
                "positioning": intel["positioning"]["headline"],
            },
            "score": {
                "total": score.total_score,
                "rejected": score.rejected,
                "recommendation": score.recommendation,
                "confidence": score.confidence,
                "rejection_reasons": score.rejection_reasons,
            },
            "next_actions": decision.next_actions,
            "pain_cluster": top["name"],
            "opportunity_size": intel["opportunity_size"],
            "risk_level": intel["risk_level"],
            "attack_vectors": intel["attack_vectors"],
            "market_gaps": intel["market_gaps"],
            "generated_at": decision.generated_at,
            "total_latency_ms": total_ms,
            "total_cost_usd": total_cost,
            "metadata": {
                "complaint_count": pain_result.get("total_complaints", 0),
                "cluster_count": len(pain_result.get("clusters", [])),
                "competitor_count": comp_result.get("competitor_count", 0),
            },
        }

    def _serialize_dataclass(self, obj: Any) -> Any:
        if hasattr(obj, "__dataclass_fields__"):
            return {k: self._serialize_dataclass(v) for k, v in obj.__dict__.items()}
        if isinstance(obj, list):
            return [self._serialize_dataclass(i) for i in obj]
        if isinstance(obj, dict):
            return {k: self._serialize_dataclass(v) for k, v in obj.items()}
        return obj

    def _save_json(self, payload: Dict[str, Any], filepath: str) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f" Salvo em: {filepath}")


# Exemplo de uso

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Opportunity Pipeline completo")
    parser.add_argument("--input", help="JSON com complaints e competitors")
    parser.add_argument("--output-dir", default="outputs/demo_pipeline")
    parser.add_argument("--rounds", type=int, default=3,
                        help="Rodadas de debate GPT×Claude (padrão: 3)")
    args = parser.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
        complaints_payload = data.get("complaints", [])
        competitors_payload = data.get("competitors", [])
    else:
        complaints_payload = [
            {
                "text": "Não sei se meu restaurante está dando lucro de verdade.",
                "source": "reddit",
                "frequency_hint": 3,
                "emotional_intensity": 8,
                "commercial_intent": 9,
            },
            {
                "text": "Meu preço está errado e eu descubro tarde demais.",
                "source": "youtube_comments",
                "frequency_hint": 2,
                "emotional_intensity": 8,
                "commercial_intent": 9,
            },
            {
                "text": "Planilha sozinha não resolve minha operação financeira.",
                "source": "forum",
                "frequency_hint": 2,
                "emotional_intensity": 7,
                "commercial_intent": 8,
            },
        ]
        competitors_payload = [
            {
                "name": "ERP Alpha",
                "url": "https://exemplo.com/erp-alpha",
                "category": "erp",
                "summary": "Gestão empresarial completa.",
                "strengths": ["robusto", "muitos relatórios"],
                "weaknesses": ["complexo", "caro", "implantação lenta"],
                "pricing": "Sob consulta",
                "target_customer": "PMEs",
            },
            {
                "name": "Consultoria Beta",
                "url": "https://exemplo.com/consultoria-beta",
                "category": "consultoria financeira",
                "summary": "Consultoria mensal focada em margem.",
                "strengths": ["humana", "profunda"],
                "weaknesses": ["ticket alto", "baixa escala"],
                "pricing": "R$2500/mês",
                "target_customer": "restaurantes",
            },
        ]

    pipeline = OpportunityPipeline(verbose=True)
    output = pipeline.run(
        complaints_payload = complaints_payload,
        competitors_payload = competitors_payload,
        output_dir = args.output_dir,
        debate_rounds = args.rounds,
    )

    print("\n" + "" * 60)
    print(" RESULTADO FINAL")
    print("" * 60)
    print(f" Status: {output['status'].upper()}")
    print(f" Ideia: {output['idea_name']}")
    print(f" Dor: {output['summary']['core_pain']}")
    print(f" Solução: {output['summary']['proposed_solution']}")
    print(f" Score: {output['score']['total']}/100")
    print(f" Rec: {output['score']['recommendation']}")
    print(f" Mercado: {output['opportunity_size']} | Risco: {output['risk_level']}")
    print(f"\n Próximas ações:")
    for a in output["next_actions"]:
        print(f" → {a}")
    print(f"\n Custo total: US$ {output['total_cost_usd']}")
    print(f" Latência: {output['total_latency_ms']}ms")
    print(f"\n Arquivos salvos em: {args.output_dir}/")
