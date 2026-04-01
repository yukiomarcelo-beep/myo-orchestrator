#!/usr/bin/env python3
"""
Telegram Command Router

Controlador via Telegram para o pipeline completo.

Comandos disponíveis:
 /scan_dores <nicho>|<problema>|<sub1,sub2> — coleta reclamações + análise de dores
 /scan_concorrencia <nicho>|<problema> — pesquisa e perfiliza concorrentes
 /criar_produto <nicho>|<problema>|<subs> — pipeline completo → decisão final
 /top_oportunidades — lista últimas decisões salvas

Como funciona:
 - handle_update(dict) processa update Telegram e retorna imediatamente
 - Pipeline roda em thread de background
 - Resultado é enviado ao chat via send_message quando completo

Uso direto (teste):
 python telegram_command_router.py

Como servidor webhook (FastAPI / myo_server.py):
 from telegram_command_router import TelegramCommandRouter
 router = TelegramCommandRouter(token)
 # em sua rota POST /webhook:
 router.handle_update(request.json())
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
OUTPUTS = BASE_DIR / "outputs"


# Telegram API helper 

class TelegramAPI:
 """Envio de mensagens via Telegram Bot API (urllib, sem dependência extra)."""

 def __init__(self, token: str):
 self.token = token
 self.base = f"https://api.telegram.org/bot{token}"

 def send(self, chat_id: int | str, text: str,
 parse_mode: str = "HTML") -> None:
 """Envia mensagem para um chat."""
 url = f"{self.base}/sendMessage"
 data = urllib.parse.urlencode({
 "chat_id": str(chat_id),
 "text": text[:4096], # limite Telegram
 "parse_mode": parse_mode,
 }).encode()
 try:
 req = urllib.request.Request(url, data=data, method="POST")
 req.add_header("Content-Type", "application/x-www-form-urlencoded")
 urllib.request.urlopen(req, timeout=15)
 except Exception as e:
 print(f" Telegram send error: {e}")

 def send_long(self, chat_id: int | str, text: str) -> None:
 """Envia mensagem longa dividindo em blocos de 4096 chars."""
 for i in range(0, len(text), 4096):
 self.send(chat_id, text[i:i+4096])
 if i + 4096 < len(text):
 time.sleep(0.3)


# Router 

class TelegramCommandRouter:
 """
 Roteador de comandos Telegram → pipeline MYO.

 Args:
 token: TELEGRAM_BOT_TOKEN
 output_base: diretório para salvar saídas (padrão: outputs/)
 """

 COMMANDS = {
 "/scan_dores": "Coleta dores do Reddit + análise Pain Radar",
 "/scan_concorrencia": "Pesquisa e perfiliza concorrentes",
 "/criar_produto": "Pipeline completo → decisão final",
 "/top_oportunidades": "Lista últimas oportunidades avaliadas",
 "/ajuda": "Mostra este menu",
 }

 def __init__(
 self,
 token: str = "",
 output_base: Optional[str] = None,
 ):
 self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
 self.api = TelegramAPI(self.token)
 self.output_base = Path(output_base or OUTPUTS)
 self.output_base.mkdir(parents=True, exist_ok=True)

 # Entry point 

 def handle_update(self, update: Dict[str, Any]) -> Dict[str, Any]:
 """
 Processa um update Telegram.

 Retorna imediatamente com {ok: true, action: "..."}.
 O processamento pesado roda em background thread.

 Args:
 update: dict do update Telegram (formato da Bot API)
 """
 message = update.get("message") or update.get("edited_message", {})
 if not message:
 return {"ok": True, "action": "ignored"}

 chat_id = (message.get("chat") or {}).get("id")
 text = (message.get("text") or "").strip()

 if not chat_id or not text:
 return {"ok": True, "action": "ignored"}

 # Rota pelo primeiro token do texto
 command = text.split()[0].lower().split("@")[0] # remove @botname se presente

 handlers = {
 "/scan_dores": self._handle_scan_dores,
 "/scan_concorrencia": self._handle_scan_concorrencia,
 "/criar_produto": self._handle_criar_produto,
 "/top_oportunidades": self._handle_top_oportunidades,
 "/ajuda": self._handle_ajuda,
 "/start": self._handle_ajuda,
 }

 handler = handlers.get(command)
 if not handler:
 if text.startswith("/"):
 self.api.send(chat_id, "Comando não reconhecido. Use /ajuda para ver os disponíveis.")
 return {"ok": True, "action": "unknown_command"}

 # Dispara em background para não bloquear o webhook
 thread = threading.Thread(
 target=handler,
 args=(chat_id, text),
 daemon=True,
 )
 thread.start()

 return {"ok": True, "action": command, "chat_id": chat_id}

 # Handlers 

 def _handle_ajuda(self, chat_id: int, text: str) -> None:
 lines = ["<b> MYO — Comandos disponíveis</b>\n"]
 for cmd, desc in self.COMMANDS.items():
 lines.append(f"<code>{cmd}</code> — {desc}")
 lines.append("\n<b>Exemplos:</b>")
 lines.append("<code>/scan_dores restaurant|profit margin|restaurantowners,smallbusiness</code>")
 lines.append("<code>/scan_concorrencia restaurant|profit margin</code>")
 lines.append("<code>/criar_produto restaurant|profit margin pricing|restaurantowners,entrepreneur</code>")
 self.api.send(chat_id, "\n".join(lines))

 def _handle_scan_dores(self, chat_id: int, text: str) -> None:
 """
 /scan_dores <nicho>|<problema>|<subreddit1,subreddit2>
 """
 try:
 niche, problem, subreddits = self._parse_three_part_command(text, "/scan_dores")
 except ValueError as e:
 self.api.send(chat_id, f" {e}")
 return

 self.api.send(chat_id,
 f" <b>Escaneando dores…</b>\n"
 f"Nicho: <code>{niche}</code>\n"
 f"Problema: <code>{problem}</code>\n"
 f"Subreddits: <code>{', '.join(subreddits)}</code>\n\n"
 "Aguarde — coletando reclamações no Reddit…"
 )

 try:
 from complaint_collector import ComplaintCollector
 from pain_radar_adapter import PainRadarAdapter

 collector = ComplaintCollector()
 complaints = collector.collect_reddit_search(
 queries = [f"{niche} {problem}", f"{niche} problem", problem],
 subreddits = subreddits,
 limit_per_query = 12,
 )

 if not complaints:
 self.api.send(chat_id, " Nenhuma reclamação encontrada. Tente outros subreddits.")
 return

 slug = self._safe_slug(niche)
 out_path = str(self.output_base / f"complaints_{slug}.json")
 payload = collector.export_payload(complaints, out_path)

 self.api.send(chat_id,
 f" <b>{len(payload)} reclamações coletadas</b>\n\n" +
 self._build_complaints_summary(payload)
 )

 # Análise Pain Radar
 self.api.send(chat_id, " Analisando clusters de dor com IA…")
 adapter = PainRadarAdapter()
 result = adapter.run(
 complaints_payload = payload,
 competitors_payload = [],
 output_path = str(self.output_base / f"pain_radar_{slug}.json"),
 )
 top = result["top_cluster"]
 prod = result["initial_product"]

 self.api.send(chat_id,
 f" <b>Dor prioritária encontrada</b>\n\n"
 f"<b>Cluster:</b> {top['name']}\n"
 f"<b>Dor central:</b> {top['core_pain']}\n"
 f"<b>Score:</b> {top['total_score']}/10\n\n"
 f"<b>Produto inicial sugerido:</b> {prod['name']}\n"
 f"<i>{prod['tagline']}</i>\n"
 f"Formato: {prod['format']} | Preço: {prod['price_range']}\n\n"
 f"Use /criar_produto para o pipeline completo."
 )

 except Exception as e:
 self.api.send(chat_id, f" Erro: {e}")

 def _handle_scan_concorrencia(self, chat_id: int, text: str) -> None:
 """
 /scan_concorrencia <nicho>|<problema>
 """
 try:
 niche, problem = self._parse_two_part_command(text, "/scan_concorrencia")
 except ValueError as e:
 self.api.send(chat_id, f" {e}")
 return

 self.api.send(chat_id,
 f" <b>Pesquisando concorrentes…</b>\n"
 f"Nicho: <code>{niche}</code>\n"
 f"Problema: <code>{problem}</code>\n\n"
 "Buscando com Perplexity — aguarde…"
 )

 try:
 from competitor_collector import CompetitorCollector

 slug = self._safe_slug(niche)
 collector = CompetitorCollector()
 competitors = collector.search(
 niche_query = niche,
 problem_query = problem,
 max_results = 8,
 )
 payload = collector.export_payload(
 competitors,
 str(self.output_base / f"competitors_{slug}.json"),
 )

 self.api.send(chat_id,
 f" <b>{len(payload)} concorrentes encontrados</b>\n\n" +
 self._build_competitors_summary(payload)
 )

 except Exception as e:
 self.api.send(chat_id, f" Erro: {e}")

 def _handle_criar_produto(self, chat_id: int, text: str) -> None:
 """
 /criar_produto <nicho>|<problema>|<subreddit1,subreddit2>
 Pipeline completo: coleta → análise → concorrência → debate → decisão.
 """
 try:
 niche, problem, subreddits = self._parse_three_part_command(
 text, "/criar_produto"
 )
 except ValueError as e:
 self.api.send(chat_id, f" {e}")
 return

 self.api.send(chat_id,
 f" <b>Pipeline iniciado</b>\n\n"
 f"Nicho: <code>{niche}</code>\n"
 f"Problema: <code>{problem}</code>\n"
 f"Subreddits: <code>{', '.join(subreddits)}</code>\n\n"
 "⏳ Etapa 1/4 — Coletando reclamações no Reddit…"
 )

 try:
 from complaint_collector import ComplaintCollector
 from competitor_collector import CompetitorCollector
 from opportunity_pipeline import OpportunityPipeline

 slug = self._safe_slug(niche)

 # Etapa 1: reclamações
 cc = ComplaintCollector()
 complaints = cc.collect_reddit_search(
 queries = [f"{niche} {problem}", problem],
 subreddits = subreddits,
 limit_per_query = 12,
 )
 complaints_payload = cc.export_payload(
 complaints,
 str(self.output_base / f"complaints_{slug}.json"),
 )
 self.api.send(chat_id,
 f" {len(complaints_payload)} reclamações coletadas\n"
 "⏳ Etapa 2/4 — Pesquisando concorrentes…"
 )

 # Etapa 2: concorrentes
 compco = CompetitorCollector()
 competitors = compco.search(
 niche_query = niche,
 problem_query = problem,
 max_results = 6,
 )
 competitors_payload = compco.export_payload(
 competitors,
 str(self.output_base / f"competitors_{slug}.json"),
 )
 self.api.send(chat_id,
 f" {len(competitors_payload)} concorrentes perfilizados\n"
 "⏳ Etapa 3/4 — Analisando dores e mercado…"
 )

 # Etapa 3+4: pipeline completo
 self.api.send(chat_id, "⏳ Etapa 4/4 — Debate GPT × Claude (pode levar ~2 min)…")
 pipeline = OpportunityPipeline(verbose=False)
 output_dir = str(self.output_base / f"pipeline_{slug}_{int(time.time())}")
 result = pipeline.run(
 complaints_payload = complaints_payload,
 competitors_payload = competitors_payload,
 output_dir = output_dir,
 debate_rounds = 3,
 )

 self.api.send_long(chat_id, self._build_pipeline_summary(result))

 except Exception as e:
 self.api.send(chat_id, f" Erro no pipeline: {e}")

 def _handle_top_oportunidades(self, chat_id: int, text: str) -> None:
 """Lista últimas decisões salvas em outputs/."""
 decisions: List[Dict[str, Any]] = []

 for f in sorted(self.output_base.rglob("03_decision.json"))[-5:]:
 try:
 data = json.loads(f.read_text(encoding="utf-8"))
 decisions.append(data)
 except Exception:
 continue

 if not decisions:
 self.api.send(chat_id,
 " Nenhuma oportunidade avaliada ainda.\n"
 "Use /criar_produto para iniciar o pipeline."
 )
 return

 lines = [f"<b> Últimas {len(decisions)} oportunidades avaliadas</b>\n"]
 for i, d in enumerate(reversed(decisions), 1):
 score = (d.get("score") or {})
 rejected = score.get("rejected", False)
 status = "" if rejected else ""
 ts = d.get("generated_at", "")[:10]
 lines.append(
 f"{status} <b>{i}. {d.get('idea_name','?')}</b>\n"
 f" Score: {score.get('total_score','?')}/100 | "
 f"{score.get('recommendation','?')} | {ts}\n"
 f" {d.get('signal_title','')}"
 )

 self.api.send(chat_id, "\n".join(lines))

 # Summary builders 

 def _build_complaints_summary(
 self, payload: List[Dict[str, Any]]
 ) -> str:
 if not payload:
 return "Nenhuma reclamação encontrada."
 lines = [f"<b>Top reclamações ({len(payload)} total):</b>"]
 for item in payload[:5]:
 ei = item.get("emotional_intensity", 0)
 ci = item.get("commercial_intent", 0)
 txt = (item.get("text") or "")[:180]
 lines.append(
 f"• {txt}\n"
 f" <i>dor: {ei} | intenção: {ci}</i>"
 )
 return "\n".join(lines)

 def _build_competitors_summary(
 self, payload: List[Dict[str, Any]]
 ) -> str:
 if not payload:
 return "Nenhum concorrente encontrado."
 lines = [f"<b>Concorrentes encontrados ({len(payload)}):</b>"]
 for item in payload[:5]:
 pricing = item.get("pricing") or "n/i"
 lines.append(
 f"• <b>{item.get('name','?')}</b> | {item.get('category','?')} | "
 f"preço: {pricing}"
 )
 if item.get("weaknesses"):
 lines.append(f" Fraquezas: {', '.join(item['weaknesses'][:2])}")
 return "\n".join(lines)

 def _build_pipeline_summary(self, result: Dict[str, Any]) -> str:
 status = result.get("status", "unknown")
 if status == "rejeitado":
 score = result.get("score", {})
 reasons = "\n".join(f" • {r}" for r in score.get("rejection_reasons", []))
 return (
 f" <b>Oportunidade rejeitada</b>\n\n"
 f"Score: {score.get('total','?')}/100\n"
 f"Motivos:\n{reasons or ' Sem detalhes'}"
 )

 summary = result.get("summary", {})
 score = result.get("score", {})
 actions = result.get("next_actions", [])

 lines = [
 f" <b>PRODUTO CRIADO: {result.get('idea_name','?')}</b>\n",
 f"<b>Cliente:</b> {summary.get('target_customer','?')}",
 f"<b>Dor:</b> {summary.get('core_problem','?')}",
 f"<b>Solução:</b> {summary.get('proposed_solution','?')}",
 f"<b>Oferta:</b> {summary.get('offer_format','?')}",
 f"<b>Preço:</b> {summary.get('pricing_hint','?')}",
 f"<b>Posicionamento:</b> {summary.get('positioning','?')}",
 "",
 f"<b>Score:</b> {score.get('total','?')}/100 | "
 f"{score.get('recommendation','?')} | "
 f"Confiança: {int((score.get('confidence',0))*100)}%",
 f"<b>Mercado:</b> {result.get('opportunity_size','?')} | "
 f"Risco: {result.get('risk_level','?')}",
 "",
 "<b>Próximas ações:</b>",
 ]
 for a in actions[:5]:
 lines.append(f" → {a}")

 cost = result.get("total_cost_usd", 0)
 ms = result.get("total_latency_ms", 0)
 lines.append(f"\n<i>Custo: US$ {cost} | {ms//1000}s</i>")

 return "\n".join(lines)

 # Parsers 

 @staticmethod
 def _parse_two_part_command(
 text: str, command: str
 ) -> tuple[str, str]:
 content = text.replace(command, "", 1).strip()
 parts = [p.strip() for p in content.split("|")]
 if len(parts) < 2:
 raise ValueError(f"Use: {command} &lt;nicho&gt;|&lt;problema&gt;")
 return parts[0], parts[1]

 @staticmethod
 def _parse_three_part_command(
 text: str, command: str
 ) -> tuple[str, str, List[str]]:
 content = text.replace(command, "", 1).strip()
 parts = [p.strip() for p in content.split("|")]
 if len(parts) < 3:
 raise ValueError(
 f"Use: {command} &lt;nicho&gt;|&lt;problema&gt;|&lt;sub1,sub2&gt;"
 )
 subreddits = [s.strip() for s in parts[2].split(",") if s.strip()]
 return parts[0], parts[1], subreddits

 @staticmethod
 def _safe_slug(text: str) -> str:
 slug = "".join(ch if ch.isalnum() else "_" for ch in text.lower())
 return "_".join(filter(None, slug.split("_")))[:80]


# Polling (modo CLI) 

def _run_polling(router: TelegramCommandRouter, interval: float = 2.0) -> None:
 """
 Polling simples para uso em CLI.
 Produção: prefira webhook via myo_server.py.
 """
 token = router.token
 api = router.api
 offset = 0
 base_url = f"https://api.telegram.org/bot{token}"

 print(f"\n Telegram Bot rodando (polling) — Ctrl+C para parar\n")
 while True:
 try:
 url = f"{base_url}/getUpdates?timeout=20&offset={offset}"
 req = urllib.request.Request(url)
 with urllib.request.urlopen(req, timeout=25) as resp:
 data = json.loads(resp.read().decode())

 for update in data.get("result", []):
 offset = update["update_id"] + 1
 router.handle_update(update)

 except KeyboardInterrupt:
 print("\n Encerrando polling…")
 break
 except Exception as e:
 print(f" Polling error: {e}")
 time.sleep(interval)


# Exemplo de uso 

if __name__ == "__main__":
 token = os.getenv("TELEGRAM_BOT_TOKEN", "")
 if not token:
 raise RuntimeError("Defina TELEGRAM_BOT_TOKEN no .env")

 router = TelegramCommandRouter(token)

 import sys
 if "--poll" in sys.argv:
 _run_polling(router)
 else:
 # Simulação de update para teste local
 sample_update = {
 "update_id": 1,
 "message": {
 "chat": {"id": int(os.getenv("TELEGRAM_CHAT_ID", "123456789"))},
 "text": "/criar_produto restaurant|profit margin pricing cash flow"
 "|restaurantowners,smallbusiness,entrepreneur",
 },
 }
 print(" Simulando update:")
 print(json.dumps(sample_update, indent=2))
 print()
 response = router.handle_update(sample_update)
 print(" Resposta imediata:")
 print(json.dumps(response, ensure_ascii=False, indent=2))
 print("\n (pipeline rodando em background thread…)")
 time.sleep(300) # aguarda o pipeline completar antes de encerrar
