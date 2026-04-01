"""
Result Ingestor — Pipeline AI
Fecha o loop: lê resultados do claude_runner, verifica semanticamente
via VerificationEngine e alimenta o trust pipeline.

Fluxo:
 outputs/claude_results/*.json
 → VerificationEngine.verify() ← validação semântica (não estrutural)
 → enriquece JSON com campos verification_*
 → verification_logger → trust_aggregator → trust_feedback_engine

Por que não usar experiment_quality diretamente no trust?
 - experiment_quality (valid/weak/risky) é ESTRUTURAL (seções, tamanho)
 - VerificationEngine é SEMÂNTICA (faz sentido? resolve o problema?)
 - "weak" estrutural pode ser "valid" semanticamente — ou vice-versa
 - "risky" estrutural é ignorado (não vale custo de verificar)

Uso:
 python3 result_ingestor.py → processa todos os não-ingeridos
 python3 result_ingestor.py --all → reprocessa todos (ignora _ingested_at)
 python3 result_ingestor.py --no-trust → só verifica, não roda trust pipeline
"""
import asyncio
import json
import os
import subprocess
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RESULTS_DIR = Path("outputs/claude_results")
ORCHESTRATOR_DIR = Path(__file__).parent


# Contextos válidos para VerificationEngine 
# Mapeamento de experiment_context (task) → execution_context (verification)
CONTEXT_MAP = {
 "research": "research",
 "mvp": "mvp",
 "launch_ready": "launch_ready",
 "scaling": "scaling",
 "idea": "idea",
}


def _map_context(raw: str) -> str:
 """Converte experiment_context da task para execution_context da verification."""
 return CONTEXT_MAP.get(str(raw).lower(), "research")


# Carregar resultados 

def load_results(reprocess_all: bool = False) -> list[tuple[Path, dict]]:
 """
 Carrega JSONs de outputs/claude_results/.
 Ignora arquivos já ingeridos (com _ingested_at) a menos que reprocess_all=True.
 Ignora resultados risky — não vale verificar semanticamente output vazio/ruim.
 """
 if not RESULTS_DIR.exists():
 print(" Nenhum resultado encontrado. Rode o claude_runner primeiro.")
 return []

 results = []
 for path in sorted(RESULTS_DIR.glob("*.json")):
 try:
 with open(path, encoding="utf-8") as f:
 data = json.load(f)
 except Exception as e:
 print(f" Falha ao ler {path.name}: {e}")
 continue

 # Pular risky — sem valor semântico
 if data.get("experiment_quality") == "risky":
 print(f" ⊘ {path.name} — risky, ignorado")
 continue

 # Pular já ingeridos (a menos que --all)
 if not reprocess_all and data.get("_ingested_at"):
 print(f" {path.name} — já ingerido ({data['_ingested_at'][:10]}), pulando")
 continue

 results.append((path, data))

 return results


# Verificação semântica 

async def verify_result(data: dict) -> dict:
 """
 Roda VerificationEngine.verify() no texto do resultado.
 Retorna campos de verificação para enriquecer o JSON.
 """
 from verification_engine import VerificationEngine

 text = data.get("result", "")
 issue_number = data.get("issue_number", "—")
 experiment_ctx = data.get("experiment_context", "research")
 execution_context = _map_context(experiment_ctx)

 print(f"\n Verificando issue #{issue_number} "
 f"(ctx={execution_context}, {len(text)} chars)...")

 engine = VerificationEngine()
 result = await engine.verify(
 text = text,
 context = f"Resultado gerado pelo Claude Code para issue #{issue_number}",
 origin_engine = "claude_runner",
 entity_id = f"issue_{issue_number}",
 execution_context = execution_context,
 )

 return {
 "verification_safe": result.safe_to_execute,
 "verification_mode": result.execution_mode.value,
 "verification_confidence": result.confidence_score,
 "verification_source_quality": result.source_quality_score,
 "verification_unverified": len(result.unverified_claims),
 "verification_critical_failures": len(result.critical_failures),
 }


# Enriquecer e salvar JSON 

def enrich_and_save(path: Path, data: dict, verification: dict):
 """Adiciona campos de verificação e marca como ingerido."""
 data.update(verification)
 data["_ingested_at"] = datetime.now(timezone.utc).isoformat()

 with open(path, "w", encoding="utf-8") as f:
 json.dump(data, f, ensure_ascii=False, indent=2)

 print(f" Enriquecido: {path.name}")
 print(f" safe={verification['verification_safe']} "
 f"| mode={verification['verification_mode']} "
 f"| confidence={verification['verification_confidence']}")


# Trust pipeline 

def run_trust_pipeline():
 """Roda trust_aggregator e trust_feedback_engine em sequência."""
 print("\n Rodando trust pipeline...")

 for script in ["trust_aggregator.py", "trust_feedback_engine.py"]:
 path = ORCHESTRATOR_DIR / script
 if not path.exists():
 print(f" {script} não encontrado, pulando.")
 continue

 proc = subprocess.run(
 [sys.executable, str(path)],
 cwd=str(ORCHESTRATOR_DIR),
 capture_output=True,
 text=True,
 )
 if proc.returncode == 0:
 print(f" {script} — OK")
 else:
 print(f" {script} — falhou:\n{proc.stderr[:200]}")

 print("\n Relatórios: outputs/trust/trust_summary.md | feedback_report.md")


# Sumário do run 

def _print_summary(stats: dict):
 total = stats["total"]
 if total == 0:
 return
 print(f"\n {''*50}")
 print(f" Sumário do ingestor")
 print(f" {''*50}")
 print(f" Processados : {total}")
 print(f" Safe : {stats['safe']} / {total}")
 print(f" Experiment : {stats['experiment']} / {total}")
 print(f" Bloqueados : {stats['blocked']} / {total}")
 print(f" Erros : {stats['errors']} / {total}")
 if stats["blocked"] > 0:
 print(f"\n {stats['blocked']} resultado(s) com VALIDATION_REQUIRED — revisar antes de usar no trust.")


# Main 

async def _run(reprocess_all: bool, run_trust: bool):
 results = load_results(reprocess_all=reprocess_all)

 if not results:
 print("\n Nada a processar.")
 return

 print(f"\n {len(results)} resultado(s) para verificar.\n")

 stats = {"total": 0, "safe": 0, "experiment": 0, "blocked": 0, "errors": 0}

 for path, data in results:
 stats["total"] += 1
 try:
 verification = await verify_result(data)
 enrich_and_save(path, data, verification)

 mode = verification["verification_mode"]
 if verification["verification_safe"]:
 stats["safe"] += 1
 elif mode == "experiment":
 stats["experiment"] += 1
 else:
 stats["blocked"] += 1

 except Exception as e:
 stats["errors"] += 1
 print(f" Erro ao verificar {path.name}: {e}")

 _print_summary(stats)

 # Alertas Telegram 
 try:
 from telegram_bot import send_alert, send_trust_alert
 if stats["blocked"] > 0:
 send_alert(
 f"{stats['blocked']} resultado(s) BLOQUEADOS pelo trust (VALIDATION_REQUIRED)\n"
 f"→ Revisar outputs/claude_results/ antes de usar",
 level="warn",
 )
 if stats["total"] > 0:
 send_alert(
 f"Ingestor concluído: {stats['safe']} safe · {stats['experiment']} exp · {stats['blocked']} bloqueados",
 level="info",
 )
 except Exception:
 pass # Telegram opcional

 if run_trust and stats["total"] > stats["errors"]:
 run_trust_pipeline()


def main():
 parser = argparse.ArgumentParser(description="Result Ingestor — fecha o loop MYO → trust")
 parser.add_argument("--all", action="store_true", help="Reprocessa todos (ignora _ingested_at)")
 parser.add_argument("--no-trust", action="store_true", help="Não roda trust pipeline ao final")
 args = parser.parse_args()

 asyncio.run(_run(
 reprocess_all = args.all,
 run_trust = not args.no_trust,
 ))


if __name__ == "__main__":
 main()
