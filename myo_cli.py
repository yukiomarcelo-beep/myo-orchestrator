"""
MYO CLI — Controle direto do pipeline.
Uso: python3 myo_cli.py
"""
import asyncio
import json
import os
import glob

# Imports do sistema 
from product_engine import build_product
from execution_engine import ExecutionEngine, ExecutionTask

TASKS_DIR = "outputs/execution_tasks"
FEEDBACK_JSON = "outputs/trust/feedback_report.json"
VALID_CONTEXTS = ["idea", "research", "mvp", "launch_ready", "scaling"]

PRIORITY_ICON = {"high": "", "medium": "", "low": "", "critical": ""}
PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "": 4}

STATUS_RUNNING = {"in_progress", "dispatched", "running"}
STATUS_PENDING = {"pending", "created"}
STATUS_FAILED = {"failed", "error"}


# Trust hint 

def _trust_hint(task: dict) -> tuple[str, int]:
 """
 Retorna (motivo_provável, ocorrências) com base no trust_feedback_engine.
 ocorrências = nº de alerts do mesmo tipo no feedback_report.
 """
 try:
 with open(FEEDBACK_JSON, encoding="utf-8") as f:
 fb = json.load(f)
 cpr = fb.get("context_policy_readiness", {})
 rch = cpr.get("root_cause_hypothesis")
 if not rch:
 return "", 0

 labels = {
 "policy_rigidity": "policy rígida (benchmark/api_cost bloqueando sem distinção de contexto)",
 "agent_inference": "inferência frágil do agent (claim sem fonte suficiente)",
 "source_quality": "fonte de baixa qualidade associada a este tipo de claim",
 "numeric_type": "tipo numérico problemático (benchmark/forecast sem base sólida)",
 }

 # Conta alerts do mesmo tipo para mostrar frequência
 alerts = fb.get("alerts", [])
 rch_map = {"policy_rigidity": "topic", "agent_inference": "engine",
 "source_quality": "source", "numeric_type": "numeric"}
 category = rch_map.get(rch, "")
 count = sum(1 for a in alerts if a.get("category") == category)

 return labels.get(rch, rch), count
 except Exception:
 return "", 0


def _classify_failure_type(task: dict) -> str:
 """
 Classifica a causa raiz da falha.
 Retorna: 'policy_rigidity' | 'agent_instability' | 'bad_source' | 'unknown'
 """
 hint, _ = _trust_hint(task)
 if "policy" in hint:
 return "policy_rigidity"
 if "inferência" in hint or "agent" in hint:
 return "agent_instability"
 if "fonte" in hint or "source" in hint:
 return "bad_source"
 return "unknown"


def _retry_recommendation(task: dict) -> str:
 """
 Sugere modo de retry com base na causa provável.
 Retorna: 'direct' | 'experiment' | 'skip'
 """
 failure_type = _classify_failure_type(task)
 if failure_type == "policy_rigidity":
 return "experiment" # policy_rigidity → tentar como EXPERIMENT
 if failure_type == "agent_instability":
 return "experiment" # agent instável → EXPERIMENT reduz exigência
 if failure_type == "bad_source":
 return "skip" # fonte ruim → retry direto não resolve
 return "direct"


# Display 

def header():
 print("\n" + "=" * 42)
 print(" MYO CONTROL")
 print("=" * 42)


def ask(prompt: str, default: str = "") -> str:
 val = input(f" → {prompt} ").strip()
 return val if val else default


# Contexto 

def choose_context() -> str:
 print("\n Contexto:")
 for i, ctx in enumerate(VALID_CONTEXTS, 1):
 print(f" {i}. {ctx}")
 raw = ask("Escolha [1]:", "1")
 try:
 return VALID_CONTEXTS[int(raw) - 1]
 except (ValueError, IndexError):
 print(" Inválido — usando 'research'")
 return "research"


# 1. Nova ideia 

async def handle_idea():
 print("\n Nova ideia\n")
 title = ask("Nome / título da ideia:")
 if not title:
 print(" Título obrigatório.")
 return

 desc = ask("Descrição curta (Enter para pular):")
 publico = ask("Público-alvo (Enter para pular):")
 mercado = ask("Mercado/nicho (Enter para pular):")
 ctx = choose_context()

 winner = {
 "idea_title": title,
 "idea_description": desc,
 "target_audience": publico,
 "market_context": mercado,
 "final_score": 70,
 "priority": ctx,
 }

 print(f"\n Processando '{title}'...\n")
 try:
 result = await build_product(winner)
 if isinstance(result, dict):
 bp = result.get("blueprint", result)
 saved = result.get("saved_path", "")
 print(f"\n Produto criado: {bp.get('idea_title', title)}")
 if saved:
 print(f" Arquivo: {saved}")
 task = result.get("execution_task")
 if task:
 print(f" Task gerada: {getattr(task, 'task_id', '—')}")
 except Exception as e:
 print(f"\n Erro: {e}")

 input("\n Enter para voltar...")


# 2. Status de tasks 

def _load_tasks(ctx_filter: str = "") -> list[dict]:
 """Carrega tasks, aplica filtro de contexto opcional e ordena por prioridade."""
 tasks = []
 for path in glob.glob(f"{TASKS_DIR}/*.json"):
 try:
 with open(path, encoding="utf-8") as f:
 t = json.load(f)
 t["_path"] = path
 tasks.append(t)
 except Exception:
 pass

 if ctx_filter:
 tasks = [t for t in tasks if ctx_filter.lower() in str(t.get("context", {}) or t.get("tags", [])).lower()]

 tasks.sort(key=lambda t: (
 PRIORITY_ORDER.get(str(t.get("priority", "")).lower(), 4),
 t.get("status", ""),
 ))
 return tasks


def handle_status(ctx_filter: str = ""):
 label = f" [{ctx_filter}]" if ctx_filter else ""
 print(f"\n Tasks de execução{label}\n")

 all_tasks = _load_tasks() # sempre conta sem filtro para a fila
 n_running = sum(1 for t in all_tasks if t.get("status","") in STATUS_RUNNING)
 n_pending = sum(1 for t in all_tasks if t.get("status","") in STATUS_PENDING)
 n_failed = sum(1 for t in all_tasks if t.get("status","") in STATUS_FAILED)

 print(f" EM EXECUÇÃO : {n_running}")
 print(f" PENDENTES : {n_pending}")
 print(f" FALHARAM : {n_failed}")
 print()

 tasks = _load_tasks(ctx_filter)
 if not tasks:
 msg = f"Nenhuma task para contexto '{ctx_filter}'." if ctx_filter else "Nenhuma task encontrada."
 print(f" {msg}")
 input("\n Enter para voltar...")
 return

 last_priority = None
 for t in tasks[:15]:
 prio = str(t.get("priority", "")).lower()
 icon = PRIORITY_ICON.get(prio, " ")
 status = t.get("status", "—")
 title = t.get("title", "—")[:48]
 task_id = t.get("task_id", os.path.basename(t["_path"]))
 executor = t.get("execution_channel") or t.get("assigned_agent") or "—"
 ctx = t.get("context", {})
 ctx_str = ctx.get("execution_context", "") if isinstance(ctx, dict) else ""

 if prio != last_priority:
 print(f" {icon} {prio.upper() or 'SEM PRIORIDADE'}")
 last_priority = prio

 print(f" [{status:<12}] {title}")
 detail = f"id={task_id} executor={executor}"
 if ctx_str:
 detail += f" ctx={ctx_str}"
 print(f" {' ' * 15}{detail}")

 # Link da issue GitHub
 if t.get("issue_url"):
 print(f" {'':15} {t['issue_url']}")

 # Trust hint para tasks falhadas
 if status in STATUS_FAILED:
 hint, count = _trust_hint(t)
 if hint:
 freq = f" ({count}x — frequente)" if count >= 3 else (f" ({count}x)" if count else "")
 print(f" {'':15}↳ Motivo provável: {hint}{freq}")

 print()

 if ctx_filter:
 print(f" (filtro ativo: context='{ctx_filter}' | 0 para limpar)")
 else:
 print(f" Total: {len(tasks)} task(s) | filtrar: '2 research'")

 # Ações rápidas se houver tasks falhadas visíveis
 failed_visible = [t for t in tasks[:15] if t.get("status","") in STATUS_FAILED]
 if failed_visible:
 print(f"\n Ações em tasks falhadas: [r] retry [d] detalhes [x] descartar [Enter] voltar")
 action = ask("Ação:").strip().lower()
 if action in ("r", "d", "x"):
 if len(failed_visible) > 1:
 for i, t in enumerate(failed_visible, 1):
 print(f" {i}. {t.get('title','—')[:50]}")
 raw = ask("Número [1]:", "1")
 try:
 target = failed_visible[int(raw) - 1]
 except (ValueError, IndexError):
 target = failed_visible[0]
 else:
 target = failed_visible[0]

 if action == "r":
 _retry_task(target)
 elif action == "d":
 _task_details(target)
 elif action == "x":
 _discard_task(target)
 return
 else:
 input("\n Enter para voltar...")


# Ações rápidas 

def _retry_task(t: dict):
 """Retry com recomendação baseada na causa provável do trust."""
 path = t.get("_path", "")
 if not path or not os.path.exists(path):
 print(" Arquivo não encontrado.")
 return

 hint, count = _trust_hint(t)
 rec = _retry_recommendation(t)

 # Mostrar contexto antes de decidir
 print(f"\n Task: {t.get('title','—')[:55]}")
 if hint:
 freq = f" ({count}x)" if count else ""
 print(f" Causa provável: {hint}{freq}")

 rec_label = {
 "direct": "Retry direto (sem mudança)",
 "experiment": "Retry como EXPERIMENT (exigência reduzida)",
 "skip": "Não recomendado (fonte ruim — retry não resolve)",
 }
 print(f"\n Recomendação: {rec_label.get(rec, rec)}")
 print(f"\n 1. Retry direto")
 print(f" 2. Retry como EXPERIMENT")
 print(f" 3. Cancelar")

 op = ask("Opção [1]:", "1").strip()
 if op == "3":
 print(" Cancelado.")
 input(" Enter para continuar...")
 return

 t["status"] = "pending"
 t.pop("error_message", None)
 t.pop("dispatch_error", None)

 # Registrar metadados do retry para retroalimentação da 6C
 hint, _ = _trust_hint(t)
 t["retry_mode"] = "experiment" if op == "2" else "direct"
 t["original_failure_type"] = _classify_failure_type(t) # causa raiz real
 t["original_hint"] = hint
 t["experiment_context"] = (
 t.get("execution_context")
 or (t.get("context") or {}).get("execution_context")
 or "research"
 ) # contexto real da task (não priority)
 t["experiment_result"] = None # preenchido após execução em handle_execute

 if op == "2":
 # Força modo EXPERIMENT no contexto da task
 ctx = t.get("context") or {}
 if isinstance(ctx, dict):
 ctx["force_execution_mode"] = "experiment"
 t["context"] = ctx
 print(" Modo EXPERIMENT ativado.")

 t.pop("_path", None)
 with open(path, "w", encoding="utf-8") as f:
 json.dump(t, f, ensure_ascii=False, indent=2)
 print(f" Task '{t.get('title','—')[:40]}' marcada como pending.")
 input(" Enter para continuar...")


def _task_details(t: dict):
 """Mostra detalhes completos da task."""
 print(f"\n Detalhes: {t.get('task_id','—')} ")
 fields = ["title", "status", "priority", "execution_channel",
 "assigned_agent", "issue_number", "issue_url",
 "error_message", "dispatch_error",
 "created_at", "updated_at", "dispatched_at", "attempts"]
 for f in fields:
 val = t.get(f)
 if val is not None:
 print(f" {f:<20}: {str(val)[:70]}")
 hint, count = _trust_hint(t)
 if hint:
 freq = f" ({count}x — frequente)" if count >= 3 else (f" ({count}x)" if count else "")
 print(f"\n Motivo provável (trust): {hint}{freq}")
 input("\n Enter para voltar...")


def _discard_task(t: dict):
 """Descarta task e registra motivo para alimentar o trust_feedback_engine."""
 path = t.get("_path", "")
 print(f"\n Task: {t.get('title','—')[:55]}")
 print(f"\n Motivo do descarte:")
 print(f" 1. Irrelevante (ideia descartada)")
 print(f" 2. Bloqueada por policy (falhou demais)")
 print(f" 3. Decisão minha (mudei de plano)")
 print(f" 0. Cancelar")

 op = ask("Motivo [1]:", "1").strip()
 if op == "0":
 print(" Cancelado.")
 return

 reason_map = {"1": "irrelevant", "2": "blocked_by_policy", "3": "user_decision"}
 reason = reason_map.get(op, "user_decision")

 if path and os.path.exists(path):
 t["status"] = "discarded"
 t["discard_reason"] = reason
 t["discarded_at"] = __import__("datetime").datetime.utcnow().isoformat()
 t.pop("_path", None)
 with open(path, "w", encoding="utf-8") as f:
 json.dump(t, f, ensure_ascii=False, indent=2)
 print(f" Task descartada. Motivo registrado: {reason}")
 input(" Enter para continuar...")


# 3. Executar task manual 

async def handle_execute():
 print("\n Executar task\n")

 files = sorted(glob.glob(f"{TASKS_DIR}/*.json"), key=os.path.getmtime, reverse=True)
 if not files:
 print(" Nenhuma task disponível.")
 input("\n Enter para voltar...")
 return

 # Lista tasks pendentes
 pending = []
 for path in files:
 try:
 with open(path, encoding="utf-8") as f:
 t = json.load(f)
 if t.get("status") in ("pending", "failed"):
 pending.append((path, t))
 except Exception:
 pass

 if not pending:
 print(" Nenhuma task pendente ou com falha.")
 input("\n Enter para voltar...")
 return

 for i, (_, t) in enumerate(pending[:8], 1):
 print(f" {i}. [{t.get('status','—')}] {t.get('title','—')[:50]}")
 print(f" id={t.get('task_id','—')}\n")

 raw = ask("Número da task [1]:", "1")
 try:
 idx = int(raw) - 1
 path, t_data = pending[idx]
 except (ValueError, IndexError):
 print(" Inválido.")
 return

 try:
 task = ExecutionTask(**{k: v for k, v in t_data.items() if k in ExecutionTask.__dataclass_fields__})
 engine = ExecutionEngine()
 result = await engine.dispatch_task(task)

 status = getattr(result, "status", "—")
 executor = getattr(result, "assigned_agent", None) or getattr(result, "execution_channel", "—")
 dispatched_at = getattr(result, "dispatched_at", None) or getattr(result, "updated_at", "—")
 error = getattr(result, "dispatch_error", None) or getattr(result, "error_message", None)
 attempts = getattr(result, "attempts", None)

 succeeded = "complet" in str(status).lower() or status == "dispatched"
 icon = "" if succeeded else ""
 print(f"\n {icon} Resultado da execução:")
 print(f" Status : {status}")
 print(f" Executor : {executor}")
 print(f" Executado em: {dispatched_at}")
 if attempts is not None:
 print(f" Tentativas : {attempts}")
 if error:
 print(f" Erro : {error}")

 # Atualizar experiment_result se era um retry de experimento
 if t_data.get("retry_mode") and t_data.get("experiment_result") is None:
 t_data["experiment_result"] = "success" if succeeded else "failed"
 t_data["experiment_result_status"] = status
 try:
 with open(path, "w", encoding="utf-8") as f_out:
 save_data = {k: v for k, v in t_data.items() if k != "_path"}
 json.dump(save_data, f_out, ensure_ascii=False, indent=2)
 mode = t_data.get("retry_mode", "direct")
 cause = t_data.get("original_failure_type", "—")
 ctx = t_data.get("experiment_context", "—")
 outcome = " sucesso" if succeeded else " falhou"
 print(f"\n Experimento registrado: mode={mode} | causa={cause} | ctx={ctx} | resultado={outcome}")
 except Exception:
 pass

 except Exception as e:
 print(f"\n Erro: {e}")

 input("\n Enter para voltar...")


# 4. Relatórios 

def handle_reports():
 print("\n Gerando relatórios...\n")
 os.system("cd /Users/marceloyukio/Documents/orchestrator && python3 trust_aggregator.py")
 os.system("cd /Users/marceloyukio/Documents/orchestrator && python3 trust_feedback_engine.py")
 print("\n Relatórios atualizados.")
 print(" Arquivos: outputs/trust/trust_summary.md | feedback_report.md")
 input("\n Enter para voltar...")


# Menu principal 

async def main():
 ctx_filter = "" # filtro de contexto persistente para status

 while True:
 header()
 ctx_hint = f" (filtro ativo: {ctx_filter})" if ctx_filter else ""
 print(f"""
 1. Nova ideia
 2. Status de tasks{ctx_hint}
 3. Executar task
 4. Rodar relatórios
 0. Sair

 Dica: '2 research' filtra status por contexto
""")
 op = ask("Opção:").strip()

 # suporte a "2 research", "2 launch_ready", etc.
 parts = op.split(None, 1)
 cmd = parts[0]
 arg = parts[1] if len(parts) > 1 else ""

 if cmd == "1": await handle_idea()
 elif cmd == "2":
 ctx_filter = arg if arg in VALID_CONTEXTS else arg # aceita qualquer filtro livre
 handle_status(ctx_filter)
 elif cmd == "3": await handle_execute()
 elif cmd == "4": handle_reports()
 elif cmd == "0":
 print("\n Até logo.\n")
 break
 else:
 print(" Opção inválida.")


if __name__ == "__main__":
 asyncio.run(main())
