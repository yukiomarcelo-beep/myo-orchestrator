#!/usr/bin/env python3
"""
ORCH -- Pain to Product Engine

Ponto unico de entrada do sistema.

Modos:
    demo -- dados simulados, testa estrutura sem Reddit/Perplexity
    auto -- coleta dores + concorrencia e cria oportunidade
    json -- roda com arquivos ja prontos

Exemplos:
    python main.py
    python main.py --mode auto --niche restaurant --problem "profit margin pricing" --subreddits restaurantowners,smallbusiness
    python main.py --mode json --complaints-file outputs/complaints_reddit.json --competitors-file outputs/competitors_auto.json
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

from adapters.complaint_collector import ComplaintCollector
from adapters.competitor_collector import CompetitorCollector
from engines.opportunity_pipeline import OpportunityPipeline


# Argparse


def parse_args() -> Dict[str, Any]:
    parser = argparse.ArgumentParser(
        description="ORCH -- Pain to Product Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
    python main.py
    python main.py --mode auto --niche restaurant --problem "profit margin cash flow" --subreddits restaurantowners,smallbusiness,entrepreneur
    python main.py --mode json --complaints-file outputs/complaints_reddit.json --competitors-file outputs/competitors_auto.json
""",
    )
    parser.add_argument(
        "--mode", default="demo",
        choices=["demo", "auto", "json"],
        help="Modo de execucao (padrao: demo)",
    )
    parser.add_argument("--niche", default="restaurant",
                        help="Nicho principal (modo auto)")
    parser.add_argument("--problem", default="profit margin pricing cash flow",
                        help="Problema principal (modo auto)")
    parser.add_argument(
        "--subreddits",
        default="restaurantowners,smallbusiness,entrepreneur",
        help="Subreddits separados por virgula (modo auto)",
    )
    parser.add_argument("--complaints-file", default="",
                        help="JSON com reclamacoes prontas (modo json)")
    parser.add_argument("--competitors-file", default="",
                        help="JSON com concorrentes prontos (modo json)")
    parser.add_argument("--output-dir", default="outputs/main_run",
                        help="Diretorio de saida (padrao: outputs/main_run)")
    parser.add_argument("--reddit-limit", type=int, default=10,
                        help="Limite de posts por query no Reddit (modo auto)")
    parser.add_argument("--rounds", type=int, default=3,
                        help="Rodadas de debate GPT x Claude (padrao: 3)")
    parser.add_argument("--quiet", action="store_true",
                        help="Menos logs no terminal")
    return vars(parser.parse_args())


# MainApp


class MainApp:
    """
    Ponto de entrada que orquestra os coletores e o pipeline.

    Metodos publicos:
        run(config) -- executa no modo configurado
    """

    def __init__(self) -> None:
        self.complaint_collector = ComplaintCollector()
        self.competitor_collector = CompetitorCollector()
        self.pipeline = OpportunityPipeline(
            verbose=True,  # sobrescrito por config em run()
        )

    # Entry point

    def run(self, config: Dict[str, Any]) -> Dict[str, Any]:
        mode = config.get("mode", "demo")
        output_dir = Path(config.get("output_dir", "outputs/main_run"))
        output_dir.mkdir(parents=True, exist_ok=True)

        verbose = not config.get("quiet", False)
        self.pipeline.orchestrator.verbose = verbose
        self.pipeline.verbose = verbose

        self._validate_env(mode)
        self._print_header(mode, config)

        if mode == "demo":
            return self._run_demo(output_dir, config)
        if mode == "auto":
            return self._run_auto(config, output_dir)
        if mode == "json":
            return self._run_json(config, output_dir)

        raise ValueError(f"Modo desconhecido: {mode}")

    # Modo demo

    def _run_demo(
        self, output_dir: Path, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        print("\n Modo DEMO -- usando dados simulados\n")

        complaints_payload = [
            {
                "text": "Nao sei se meu restaurante esta dando lucro de verdade.",
                "source": "reddit/demo",
                "frequency_hint": 3.0,
                "emotional_intensity": 8.0,
                "commercial_intent": 9.0,
            },
            {
                "text": "Precifico no achismo e minha margem some no fim do mes.",
                "source": "reddit/demo",
                "frequency_hint": 2.5,
                "emotional_intensity": 8.0,
                "commercial_intent": 9.0,
            },
            {
                "text": "Planilha funciona ate certo ponto, depois vira bagaca.",
                "source": "forum/demo",
                "frequency_hint": 2.0,
                "emotional_intensity": 6.5,
                "commercial_intent": 7.5,
            },
            {
                "text": "Nao tenho DRE, nao sei qual produto tira mais margem.",
                "source": "youtube/demo",
                "frequency_hint": 2.0,
                "emotional_intensity": 7.5,
                "commercial_intent": 8.5,
            },
        ]
        competitors_payload = [
            {
                "name": "ERP Alpha",
                "url": "https://exemplo.com/erp-alpha",
                "category": "erp",
                "summary": "Gestao empresarial completa.",
                "strengths": ["robusto", "muitos relatorios"],
                "weaknesses": ["complexo", "caro", "implantacao lenta"],
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
                "pricing": "R$2500/mes",
                "target_customer": "restaurantes",
            },
        ]

        return self._run_pipeline(
            complaints_payload=complaints_payload,
            competitors_payload=competitors_payload,
            output_dir=output_dir,
            debate_rounds=config.get("rounds", 3),
        )

    # Modo auto

    def _run_auto(
        self, config: Dict[str, Any], output_dir: Path
    ) -> Dict[str, Any]:
        niche = config["niche"]
        problem = config["problem"]
        subreddits = [s.strip() for s in config["subreddits"].split(",") if s.strip()]
        limit = config.get("reddit_limit", 10)

        # Etapa 1: reclamacoes
        print(f"\n Coletando reclamacoes -- Reddit")
        print(f" Queries: [{niche} {problem}]")
        print(f" Subreddits: {', '.join(subreddits)}")

        complaints = self.complaint_collector.collect_reddit_search(
            queries=[f"{niche} {problem}", problem, f"{niche} problem"],
            subreddits=subreddits,
            limit_per_query=limit,
        )
        if not complaints:
            print(" Nenhuma reclamacao coletada. Verifique as queries e subreddits.")
            print(" Tente --mode demo para testar sem coleta ao vivo.")
            return {"status": "error", "reason": "no_complaints_collected"}

        complaints_payload = self.complaint_collector.export_payload(
            complaints,
            str(output_dir / "complaints_auto.json"),
        )
        print(f" {len(complaints_payload)} reclamacoes coletadas")

        # Etapa 2: concorrentes
        print(f"\n Pesquisando concorrentes -- Perplexity")
        competitors = self.competitor_collector.search(
            niche_query=niche,
            problem_query=problem,
            max_results=8,
        )
        competitors_payload = self.competitor_collector.export_payload(
            competitors,
            str(output_dir / "competitors_auto.json"),
        )
        print(f" {len(competitors_payload)} concorrentes perfilizados")

        # Etapa 3: pipeline
        return self._run_pipeline(
            complaints_payload=complaints_payload,
            competitors_payload=competitors_payload,
            output_dir=output_dir,
            debate_rounds=config.get("rounds", 3),
        )

    # Modo json

    def _run_json(
        self, config: Dict[str, Any], output_dir: Path
    ) -> Dict[str, Any]:
        complaints_file = config.get("complaints_file", "")
        competitors_file = config.get("competitors_file", "")

        if not complaints_file:
            print(" --complaints-file e obrigatorio no modo json")
            sys.exit(1)

        complaints_path = Path(complaints_file)
        if not complaints_path.exists():
            print(f" Arquivo nao encontrado: {complaints_file}")
            sys.exit(1)

        print(f"\n Carregando reclamacoes: {complaints_file}")
        complaints_payload = json.loads(
            complaints_path.read_text(encoding="utf-8")
        )
        if not isinstance(complaints_payload, list):
            complaints_payload = complaints_payload.get("complaints", [])
        print(f" {len(complaints_payload)} reclamacoes carregadas")

        competitors_payload: List[Dict[str, Any]] = []
        if competitors_file:
            comp_path = Path(competitors_file)
            if comp_path.exists():
                print(f" Carregando concorrentes: {competitors_file}")
                competitors_payload = json.loads(
                    comp_path.read_text(encoding="utf-8")
                )
                print(f" {len(competitors_payload)} concorrentes carregados")
            else:
                print(f" Arquivo de concorrentes nao encontrado: {competitors_file}")

        return self._run_pipeline(
            complaints_payload=complaints_payload,
            competitors_payload=competitors_payload,
            output_dir=output_dir,
            debate_rounds=config.get("rounds", 3),
        )

    # Pipeline comum

    def _run_pipeline(
        self,
        complaints_payload: List[Dict[str, Any]],
        competitors_payload: List[Dict[str, Any]],
        output_dir: Path,
        debate_rounds: int = 3,
    ) -> Dict[str, Any]:
        result = self.pipeline.run(
            complaints_payload=complaints_payload,
            competitors_payload=competitors_payload,
            output_dir=str(output_dir),
            debate_rounds=debate_rounds,
        )
        self._save_json(result, str(output_dir / "main_result.json"))
        self._print_result(result)
        return result

    # Validacao de ambiente

    def _validate_env(self, mode: str) -> None:
        """
        Verifica chaves necessarias para o modo escolhido.
        Com llm_router instalado, a ausencia de chaves ativa modo heuristico
        em vez de bloquear a execucao.
        """
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        openai_key = os.getenv("OPENAI_API_KEY", "")

        if not anthropic_key and not openai_key:
            print("\n Nenhuma chave LLM configurada -- rodando em modo HEURISTICO")
            print(" (respostas simuladas, sem custo de API)\n")
        elif not anthropic_key:
            print(" ANTHROPIC_API_KEY ausente -- fallback para OpenAI")
        elif not openai_key:
            print(" OPENAI_API_KEY ausente -- fallback para Claude")

        # No modo auto, competitor_collector precisa de Perplexity ou OpenAI
        if mode == "auto":
            if not os.getenv("PERPLEXITY_API_KEY") and not openai_key:
                print(" Modo auto sem PERPLEXITY_API_KEY nem OPENAI_API_KEY -- "
                      "competitor_collector usara heuristica")

    # Print helpers

    def _print_header(self, mode: str, config: Dict[str, Any]) -> None:
        print("\n" + "-" * 60)
        print(" ORCH -- Pain to Product Engine")
        print("-" * 60)
        print(f" Modo: {mode.upper()}")
        if mode == "auto":
            print(f" Nicho:    {config['niche']}")
            print(f" Problema: {config['problem']}")
        print(f" Saida:    {config.get('output_dir', 'outputs/main_run')}/")
        print(f" Rodadas:  {config.get('rounds', 3)} debate(s) GPT x Claude")
        print("-" * 60)

    def _print_result(self, result: Dict[str, Any]) -> None:
        status = result.get("status", "?")
        print("\n" + "-" * 60)
        print(" RESULTADO FINAL")
        print("-" * 60)

        if status == "rejeitado":
            score = result.get("score", {})
            reasons = score.get("rejection_reasons", [])
            print(f" REJEITADA -- Score: {score.get('total', '?')}/100")
            for r in reasons:
                print(f"   - {r}")
        else:
            s = result.get("summary", {})
            score = result.get("score", {})
            print(f" APROVADA")
            print(f" Ideia:    {result.get('idea_name', '?')}")
            print(f" Cliente:  {s.get('target_customer', '?')}")
            print(f" Dor:      {s.get('core_problem', '?')}")
            print(f" Solucao:  {s.get('proposed_solution', '?')}")
            print(f" Oferta:   {s.get('offer_format', '?')}")
            print(f" Preco:    {s.get('pricing_hint', '?')}")
            print(f" Score:    {score.get('total', '?')}/100 "
                  f"| Rec: {score.get('recommendation', '?')} "
                  f"| Confianca: {int((score.get('confidence', 0)) * 100)}%")
            print(f" Mercado:  {result.get('opportunity_size', '?')} "
                  f"| Risco: {result.get('risk_level', '?')}")
            print(f"\n Proximas acoes:")
            for a in result.get("next_actions", [])[:5]:
                print(f"   -> {a}")

        print(f"\n Custo total: US$ {result.get('total_cost_usd', 0)}")
        print(f" Tempo total: {result.get('total_latency_ms', 0) // 1000}s")
        print(f" Arquivos:   {result.get('output_dir', 'outputs/main_run')}/")
        print("-" * 60 + "\n")

    @staticmethod
    def _save_json(payload: Dict[str, Any], filepath: str) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f" Resultado principal salvo em: {filepath}")


# Entry point


def main() -> None:
    config = parse_args()
    app = MainApp()
    result = app.run(config)
    sys.exit(0 if result.get("status") != "error" else 1)


if __name__ == "__main__":
    main()
