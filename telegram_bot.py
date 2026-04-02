#!/usr/bin/env python3
"""
Telegram Bot — Pipeline AI / MYO
Não é um chat GPT. Só faz: alertas, resumos, ações rápidas.

Comandos:
 /status → contagens + problema topo
 /retry <id> → reenfileira task falhada
 /discard <id> → descarta task
 /run → dispara ciclo de execução (policy_adapter + result_ingestor)
 /policy → mostra resumo da policy atual

Alertas automáticos (chamados por result_ingestor.py e policy_adapter.py):
 send_alert(message, level="info"|"warn"|"critical")
 send_policy_change(changes: list[str])
 send_trust_alert(engine, rate, context="")

Uso:
 python3 telegram_bot.py → sobe o bot (polling)
 python3 telegram_bot.py --test → envia mensagem de teste e sai

Configurar no .env:
 TELEGRAM_BOT_TOKEN=123456:ABC-...
 TELEGRAM_CHAT_ID=-100...
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Dependência opcional: python-telegram-bot v20+ 
try:
 from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
 from telegram.ext import (
 Application, CommandHandler, CallbackQueryHandler, ContextTypes
 )
 TELEGRAM_AVAILABLE = True
except ImportError:
 TELEGRAM_AVAILABLE = False

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TASKS_DIR = Path("outputs/execution_tasks")
POLICY_FILE = Path("config/context_policy.json")

# Helpers de dados 

def _load_tasks() -> list[dict]:
 tasks = []
 if not TASKS_DIR.exists():
  return tasks
  for p in sorted(TASKS_DIR.glob("*.json"), reverse=True)[:100]:
   try:
    with open(p, encoding="utf-8") as f:
     t = json.load(f)
     t["_file"] = p.name
     tasks.append(t)
   except Exception:
    pass
    return tasks


def _task_by_id(task_id: str) -> tuple[dict | None, Path | None]:
 if not TASKS_DIR.exists():
  return None, None
  for p in TASKS_DIR.glob("*.json"):
   try:
    with open(p, encoding="utf-8") as f:
     t = json.load(f)
     if t.get("task_id", "") == task_id or p.stem == task_id:
      return t, p
   except Exception:
    pass
    return None, None


def _status_summary() -> str:
 tasks = _load_tasks()
 if not tasks:
  return "Nenhuma task encontrada."

  counts: dict[str, int] = {}
  for t in tasks:
   s = t.get("status", "unknown")
   counts[s] = counts.get(s, 0) + 1

   lines = [
   f" *Status MYO*",
   f"Total: {len(tasks)} tasks",
   "",
   ]
   STATUS_ICONS = {
   "completed": "", "in_progress": "", "routed": "",
   "pending": "⏳", "failed": "", "discarded": "",
   }
   for s, n in sorted(counts.items(), key=lambda x: -x[1]):
    icon = STATUS_ICONS.get(s, "•")
    lines.append(f"{icon} {s}: {n}")

    # Top problema
    failed = [t for t in tasks if t.get("status") == "failed"]
    if failed:
     top = failed[0]
     lines += [
     "",
     f" *Top falha:*",
     f"`{top.get('task_id', '—')[:20]}` — {top.get('title', '—')[:40]}",
     f"Causa: {top.get('original_failure_type', '?')}",
     ]

     return "\n".join(lines)


def _policy_summary() -> str:
 if not POLICY_FILE.exists():
  return "config/context_policy.json não encontrado."
  try:
   with open(POLICY_FILE, encoding="utf-8") as f:
    policy = json.load(f)
  except Exception as e:
   return f"Erro ao ler policy: {e}"

   meta = policy.get("_meta", {})
   version = meta.get("version", 1)
   updated = (meta.get("updated_at", "")[:10]) or "—"

   lines = [f" *Policy 6C* — v{version} · {updated}", ""]
   CTXS = ["idea", "research", "mvp", "launch_ready", "scaling"]
   for ctx in CTXS:
    cp = policy.get(ctx)
    if not cp:
     continue
     t_n = cp.get("gate_confidence_normal", "—")
     t_e = cp.get("gate_confidence_experiment", "—")
     strict = "" if cp.get("api_cost_strict") else ""
     lines.append(f"`{ctx:<12}` normal:{t_n} exp:{t_e} {strict}")

     last = (meta.get("adjustment_history") or [{}])[-1].get("changes", [])
     if last:
      lines += ["", " Último ajuste:"]
      for c in last[:2]:
       lines.append(f" · {c[:60]}")

       return "\n".join(lines)


# Envio de alertas (chamado por outros módulos) 

def send_alert(message: str, level: str = "info"):
 """
 Envia alerta ao Telegram. Pode ser chamado por result_ingestor.py ou policy_adapter.py.
 Usa HTTP direto (sem biblioteca), funciona mesmo sem o bot rodando em polling.
 """
 if not BOT_TOKEN or not CHAT_ID:
  print(f" [telegram] Token/chat não configurado — alerta ignorado: {message[:60]}")
  return

  icon = {"critical": "", "warn": "", "info": "ℹ"}.get(level, "•")
  text = f"{icon} *MYO ALERT*\n{message}"

  try:
   import urllib.request, urllib.parse
   url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
   data = urllib.parse.urlencode({
   "chat_id": CHAT_ID,
   "text": text,
   }).encode()
   req = urllib.request.Request(url, data=data, method="POST")
   with urllib.request.urlopen(req, timeout=5) as resp:
    pass # fire and forget
  except Exception as e:
   print(f" [telegram] Falha ao enviar alerta: {e}")


def send_policy_change(changes: list[str]):
 """Notifica mudanças de policy com destaque visual."""
 if not changes:
  return
  lines = [" *Policy atualizada*", ""]
  OP_ICONS = {"TIGHTEN": "", "RELAX": "", "SOFTEN": "", "STRICT": ""}
  for c in changes[:5]:
   op = c.split()[0] if c else ""
   icon = OP_ICONS.get(op, "·")
   lines.append(f"{icon} `{c[:65]}`")
   send_alert("\n".join(lines[1:]), level="info")


def send_trust_alert(engine: str, rate: float, context: str = ""):
 """Alerta de alta taxa de falha em engine."""
 ctx_suffix = f" ({context})" if context else ""
 level = "critical" if rate > 0.50 else "warn"
 send_alert(
 f"*{engine}*{ctx_suffix}: {rate:.0%} falha crítica\n→ Revisar prompts ou fontes",
 level=level,
 )


# Handlers do bot 

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
 summary = _status_summary()
 # Botões de ação rápida
 keyboard = [[
 InlineKeyboardButton(" Rodar ciclo", callback_data="run_cycle"),
 InlineKeyboardButton(" Policy", callback_data="show_policy"),
 ]]
 await update.message.reply_text(
 summary,
 parse_mode="Markdown",
 reply_markup=InlineKeyboardMarkup(keyboard),
 )


async def cmd_retry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
 if not ctx.args:
  await update.message.reply_text("Uso: /retry <task_id>")
  return
  task_id = ctx.args[0]
  task, path = _task_by_id(task_id)
  if not task:
   await update.message.reply_text(f"Task `{task_id}` não encontrada.", parse_mode="Markdown")
   return
   if task.get("status") != "failed":
    await update.message.reply_text(f"Task não está em status `failed` (atual: {task.get('status')}).", parse_mode="Markdown")
    return
    # Recolocar status pending para nova execução
    task["status"] = "pending"
    task.pop("error", None)
    with open(path, "w", encoding="utf-8") as f:
     json.dump(task, f, ensure_ascii=False, indent=2)
     await update.message.reply_text(
     f" Task `{task_id[:20]}` voltou para *pending*.\nRode `python3 myo_cli.py run` para executar.",
     parse_mode="Markdown",
     )


async def cmd_discard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
 if not ctx.args:
  await update.message.reply_text("Uso: /discard <task_id>")
  return
  task_id = ctx.args[0]
  task, path = _task_by_id(task_id)
  if not task:
   await update.message.reply_text(f"Task `{task_id}` não encontrada.", parse_mode="Markdown")
   return
   task["status"] = "discarded"
   with open(path, "w", encoding="utf-8") as f:
    json.dump(task, f, ensure_ascii=False, indent=2)
    await update.message.reply_text(f" Task `{task_id[:20]}` descartada.", parse_mode="Markdown")


async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
 await update.message.reply_text(" Iniciando ciclo: result_ingestor → policy_adapter...")
 errors = []
 for script, label in [
 ("result_ingestor.py", "result_ingestor"),
 ("policy_adapter.py", "policy_adapter"),
 ]:
  try:
   result = subprocess.run(
   [sys.executable, script],
   capture_output=True, text=True, timeout=120,
   cwd=Path(__file__).parent,
   )
   if result.returncode != 0:
    errors.append(f"{label}: {result.stderr.strip()[:80]}")
  except subprocess.TimeoutExpired:
   errors.append(f"{label}: timeout")
  except Exception as e:
   errors.append(f"{label}: {e}")

   if errors:
    await update.message.reply_text(
    " Ciclo concluído com erros:\n" + "\n".join(f"· {e}" for e in errors),
    parse_mode="Markdown",
    )
   else:
    await update.message.reply_text(" Ciclo concluído com sucesso.")


async def cmd_policy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
 await update.message.reply_text(_policy_summary(), parse_mode="Markdown")


async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
 query = update.callback_query
 await query.answer()
 if query.data == "run_cycle":
  await query.edit_message_text(" Disparando ciclo...")
  errors = []
  for script in ["result_ingestor.py", "policy_adapter.py"]:
   try:
    r = subprocess.run(
    [sys.executable, script], capture_output=True, text=True,
    timeout=120, cwd=Path(__file__).parent,
    )
    if r.returncode != 0:
     errors.append(f"{script}: {r.stderr.strip()[:60]}")
   except Exception as e:
    errors.append(f"{script}: {e}")
    msg = " Ciclo concluído." if not errors else " Erros:\n" + "\n".join(f"· {e}" for e in errors)
    await query.edit_message_text(msg)
 elif query.data == "show_policy":
  await query.edit_message_text(_policy_summary(), parse_mode="Markdown")


# Main 

def main():
 parser = argparse.ArgumentParser(description="MYO Telegram Bot")
 parser.add_argument("--test", action="store_true", help="Envia mensagem de teste e sai")
 args = parser.parse_args()

 if not BOT_TOKEN:
  print(" TELEGRAM_BOT_TOKEN não configurado no .env")
  print(" Adicione: TELEGRAM_BOT_TOKEN=<token>")
  print(" TELEGRAM_CHAT_ID=<chat_id>")
  sys.exit(1)

  if args.test:
   send_alert("Bot MYO conectado. /status para ver tarefas.", level="info")
   print(" Mensagem de teste enviada.")
   return

   if not TELEGRAM_AVAILABLE:
    print(" python-telegram-bot não instalado.")
    print(" pip install python-telegram-bot")
    sys.exit(1)

    print(f" MYO Bot iniciando (polling)...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("retry", cmd_retry))
    app.add_handler(CommandHandler("discard", cmd_discard))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("policy", cmd_policy))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.run_polling()


if __name__ == "__main__":
 main()
