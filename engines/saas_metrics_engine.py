#!/usr/bin/env python3
"""
SaaS Metrics Engine — Pipeline AI
Controla os três números que definem a saúde de um negócio recorrente:
 CAC — Custo de Aquisição de Cliente
 LTV — Lifetime Value
 Churn — % de perda mensal

Fluxo:
 Input (clientes + receita + marketing + churn)
 → Calculate SaaS Metrics (lógica) — CAC, LTV, churn_rate, LTV/CAC
 → Decision Engine (lógica) — scale / healthy / optimize / danger / critical
 → Claude SaaS Analysis (Claude) — diagnóstico, alertas, ações
 → Historical Trend (local) — lê sessões anteriores para detectar tendência
 → Save (local) — persiste em saas_metrics_*.json
 → Output (terminal + Notion + Dashboard)

Regras LTV/CAC:
 ≥ 5 → scale aggressively (escalar agressivamente)
 ≥ 3 → healthy (saudável)
 ≥ 2 → optimize (otimizar)
 ≥ 1 → danger (perigoso)
 < 1 → critical (parar imediatamente)

Churn saudável (SaaS):
 < 2% → excelente
 < 5% → ok
 < 10% → alto
 ≥ 10% → crítico

Uso:
 python saas_metrics_engine.py # modo interativo
 python saas_metrics_engine.py --json '{...}' # input manual
 python saas_metrics_engine.py --history # histórico de sessões
 python saas_metrics_engine.py --title "CFO Digital" # produto específico
"""
import asyncio, json, os, sys, time, glob
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"
OUTPUTS_DIR = "outputs"

# Thresholds LTV/CAC
LTV_CAC_SCALE = 5.0
LTV_CAC_HEALTHY = 3.0
LTV_CAC_OPTIMIZE = 2.0
LTV_CAC_DANGER = 1.0

# Thresholds Churn mensal
CHURN_EXCELLENT = 0.02
CHURN_OK = 0.05
CHURN_HIGH = 0.10


# API helper 

def _parse_json(raw: str) -> dict | list:
 raw = raw.strip()
 try:
  return json.loads(raw)
 except json.JSONDecodeError:
  for a, b in [("{", "}"), ("[", "]")]:
   s, e = raw.find(a), raw.rfind(b) + 1
   if s != -1 and e > s:
    try:
     return json.loads(raw[s:e])
    except Exception:
     pass
     return {"raw": raw}


async def _claude(prompt: str, max_tokens: int = 1600) -> tuple[dict, dict]:
 if not ANTHROPIC_API_KEY or "sua-chave" in ANTHROPIC_API_KEY:
  raise ValueError("ANTHROPIC_API_KEY não configurada")
  payload = {
  "model": CLAUDE_MODEL, "max_tokens": max_tokens,
  "messages": [{"role": "user", "content": prompt}],
  }
  headers = {
  "x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
  "content-type": "application/json",
  }
  t0 = time.time()
  async with httpx.AsyncClient(timeout=90) as c:
   r = await c.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
   r.raise_for_status()
   data = r.json()
   raw = data.get("content", [{}])[0].get("text", "")
   u = data.get("usage", {})
   return _parse_json(raw), {
   "latency_ms": int((time.time() - t0) * 1000),
   "cost": round((u.get("input_tokens", 0) * 3e-6) + (u.get("output_tokens", 0) * 15e-6), 6),
   }


# Prompts 

def _p_saas_analysis(data: dict) -> str:
 cac = data.get("cac", 0)
 ltv = data.get("ltv", 0)
 ratio = data.get("ltv_cac_ratio", 0)
 churn = data.get("churn_rate", 0) * 100
 status = data.get("status", "danger")
 mrr = data.get("mrr", 0)
 arr = mrr * 12
 payback = data.get("payback_months", 0)

 return f"""Você é um especialista em métricas SaaS e negócios recorrentes.

Analise a saúde financeira deste negócio:

Produto : {data.get('product_name', '')}
MRR (receita/mês): ${mrr:,.2f}
ARR (receita/ano): ${arr:,.2f}

CAC : ${cac:.2f} (custo para adquirir 1 cliente)
LTV : ${ltv:.2f} (valor total do cliente)
LTV/CAC Ratio : {ratio:.2f}x → {status.upper()}
Churn mensal : {churn:.1f}%
Payback period : {payback:.1f} meses
Clientes totais : {data.get('total_customers', 0)}
Clientes novos : {data.get('new_customers', 0)}
Churned : {data.get('churned_customers', 0)}

Retorne análise completa em JSON:

{{
 "diagnostic": "",
 "biggest_risk": "",
 "cac_alert": "",
 "ltv_alert": "",
 "churn_alert": "",
 "actions": [],
 "retention_tactics": [],
 "acquisition_efficiency": "",
 "growth_path": "",
 "burn_warning": ""
}}

- diagnostic: diagnóstico direto em 1-2 frases
- biggest_risk: maior risco para o negócio agora
- cac_alert: alerta sobre o CAC (vazio se ok)
- ltv_alert: alerta sobre o LTV (vazio se ok)
- churn_alert: alerta sobre churn (vazio se ok)
- actions: 3-5 ações concretas para melhorar a saúde do negócio
- retention_tactics: 3 táticas específicas para reduzir churn
- acquisition_efficiency: como melhorar o CAC (1 frase)
- growth_path: caminho mais seguro para crescer agora (1 frase)
- burn_warning: alerta crítico se o negócio está queimando caixa (ou "")

Responda APENAS em JSON válido."""


# Lógica de cálculo 

def _calculate(raw: dict) -> dict:
 """Calculate SaaS Metrics Node."""
 new_customers = raw.get("new_customers", 0) or 0
 churned = raw.get("churned_customers", 0) or 0
 total_customers = max(raw.get("total_customers", 1) or 1, 1)
 revenue = raw.get("revenue", 0) or 0
 marketing_cost = raw.get("marketing_cost", 0) or 0
 avg_ticket = raw.get("avg_ticket", 0) or 0

 # CAC
 cac = (marketing_cost / new_customers) if new_customers > 0 else 0

 # MRR
 mrr = revenue if revenue > 0 else (avg_ticket * total_customers)

 # Receita média por cliente
 avg_revenue = (mrr / total_customers) if total_customers > 0 else avg_ticket

 # Churn Rate
 churn_rate = (churned / total_customers) if total_customers > 0 else raw.get("churn_rate", 0) or 0

 # Lifetime (meses)
 lifetime = (1 / churn_rate) if churn_rate > 0 else raw.get("lifetime_months", 12) or 12

 # LTV
 ltv = avg_revenue * lifetime

 # LTV/CAC Ratio
 ltv_cac_ratio = (ltv / cac) if cac > 0 else 0

 # Payback period (meses para recuperar CAC)
 payback_months = (cac / avg_revenue) if avg_revenue > 0 else 0

 # Status
 if ltv_cac_ratio >= LTV_CAC_SCALE:
  status = "scale"
 elif ltv_cac_ratio >= LTV_CAC_HEALTHY:
  status = "healthy"
 elif ltv_cac_ratio >= LTV_CAC_OPTIMIZE:
  status = "optimize"
 elif ltv_cac_ratio >= LTV_CAC_DANGER:
  status = "danger"
 else:
  status = "critical"

  # Churn classification
  if churn_rate < CHURN_EXCELLENT:
   churn_status = "excellent"
  elif churn_rate < CHURN_OK:
   churn_status = "ok"
  elif churn_rate < CHURN_HIGH:
   churn_status = "high"
  else:
   churn_status = "critical"

   # Net Revenue Retention (simplificado)
   nrr = 1 - churn_rate

   return {
   **raw,
   "cac": round(cac, 2),
   "ltv": round(ltv, 2),
   "mrr": round(mrr, 2),
   "avg_revenue": round(avg_revenue, 2),
   "churn_rate": round(churn_rate, 6),
   "churn_status": churn_status,
   "lifetime": round(lifetime, 1),
   "ltv_cac_ratio": round(ltv_cac_ratio, 2),
   "payback_months": round(payback_months, 1),
   "nrr": round(nrr, 4),
   "status": status,
   }


def _growth_projection(data: dict) -> dict:
 """Projeta crescimento em 3, 6 e 12 meses mantendo métricas atuais."""
 mrr = data.get("mrr", 0)
 churn_rate = data.get("churn_rate", 0)
 new_customers= data.get("new_customers", 0)
 avg_revenue = data.get("avg_revenue", 0)
 total = data.get("total_customers", 0)

 scenarios = {}
 for months in [3, 6, 12]:
  c = total
  r = mrr
  for _ in range(months):
   churned = c * churn_rate
   c = max(c + new_customers - churned, 0)
   r = c * avg_revenue
   scenarios[str(months)] = {
   "months": months,
   "customers": round(c),
   "mrr": round(r, 2),
   "arr": round(r * 12, 2),
   }
   return scenarios


def _load_history(product_name: Optional[str] = None) -> list:
 """Carrega histórico de sessões para detectar tendência."""
 records = []
 for path in sorted(glob.glob(f"{OUTPUTS_DIR}/saas_metrics_*.json")):
  try:
   with open(path, encoding="utf-8") as f:
    d = json.load(f)
    if product_name and product_name.lower() not in d.get("product_name", "").lower():
     continue
     records.append({
     "timestamp": d.get("timestamp", ""),
     "ltv_cac": d.get("ltv_cac_ratio", 0),
     "churn_rate": d.get("churn_rate", 0),
     "mrr": d.get("mrr", 0),
     "status": d.get("status", ""),
     })
  except Exception:
   pass
   return records[-6:] # últimas 6 sessões


# Fluxo principal 

async def run_saas_metrics(raw_input: dict) -> dict:
 name = raw_input.get("product_name", "?")
 print(f"\n SaaS Metrics Engine: {name[:55]}")
 print(" " + "" * 56)

 # [1] Calculate
 print(" [1/5] Calculando métricas SaaS...")
 data = _calculate(raw_input)

 RATIO_ICON = {"scale": "", "healthy": "", "optimize": "", "danger": "", "critical": ""}
 CHURN_ICON = {"excellent": "", "ok": "", "high": "", "critical": ""}

 print(f" CAC ${data['cac']:.2f} | LTV ${data['ltv']:.2f} | "
 f"Ratio {data['ltv_cac_ratio']:.1f}x {RATIO_ICON.get(data['status'],'')} {data['status'].upper()}")
 print(f" Churn {data['churn_rate']*100:.1f}% {CHURN_ICON.get(data['churn_status'],'')} | "
 f"MRR ${data['mrr']:,.2f} | Payback {data['payback_months']:.0f}m")

 # [2] Growth Projection
 print(" [2/5] Projetando crescimento...")
 data["timestamp"] = time.strftime("%Y%m%d_%H%M%S")
 projection = _growth_projection(data)
 data["growth_projection"] = projection
 proj_12 = projection.get("12", {})
 print(f" 12 meses → {proj_12.get('customers',0)} clientes | "
 f"MRR ${proj_12.get('mrr',0):,.0f} | ARR ${proj_12.get('arr',0):,.0f}")

 # [3] Historical trend
 print(" [3/5] Verificando histórico...")
 history = _load_history(name)
 data["history"] = history
 if len(history) > 1:
  trend = "↑ melhorando" if history[-1]["ltv_cac"] >= history[-2]["ltv_cac"] else "↓ piorando"
  print(f" {len(history)} sessões anteriores — LTV/CAC {trend}")
 else:
  print(f" Primeira sessão registrada")

  # [4] Claude Analysis
  print(" [4/5] Claude SaaS Analysis...")
  analysis_raw, m1 = await _claude(_p_saas_analysis(data))
  analysis = analysis_raw if isinstance(analysis_raw, dict) else {}
  print(f" {m1['latency_ms']}ms · ${m1['cost']:.4f}")

  # [5] Save
  print(" [5/5] Salvando resultado...")
  result = {
  "product_name": name,
  "new_customers": data.get("new_customers", 0),
  "churned_customers": data.get("churned_customers", 0),
  "total_customers": data.get("total_customers", 0),
  "mrr": data["mrr"],
  "arr": round(data["mrr"] * 12, 2),
  "avg_revenue": data["avg_revenue"],
  "marketing_cost": data.get("marketing_cost", 0),
  "cac": data["cac"],
  "ltv": data["ltv"],
  "churn_rate": data["churn_rate"],
  "churn_status": data["churn_status"],
  "lifetime": data["lifetime"],
  "ltv_cac_ratio": data["ltv_cac_ratio"],
  "payback_months": data["payback_months"],
  "nrr": data["nrr"],
  "status": data["status"],
  "growth_projection": projection,
  "history": history,
  "analysis": analysis,
  "total_cost": m1["cost"],
  "timestamp": data["timestamp"],
  "response": {
  "status": "success",
  "product_name": name,
  "ltv_cac_ratio": data["ltv_cac_ratio"],
  "saas_status": data["status"],
  "cac": data["cac"],
  "ltv": data["ltv"],
  "churn_rate": round(data["churn_rate"] * 100, 1),
  "mrr": data["mrr"],
  "payback_months": data["payback_months"],
  "growth_path": analysis.get("growth_path", ""),
  "biggest_risk": analysis.get("biggest_risk", ""),
  },
  }

  fname = _salvar_local(result)
  print(f" Salvo em {fname}")

  _imprimir(result)
  await _salvar_notion(result)
  _atualizar_dashboard()

  return result


# Histórico 

def show_history():
 records = []
 for path in sorted(glob.glob(f"{OUTPUTS_DIR}/saas_metrics_*.json"), reverse=True):
  try:
   with open(path, encoding="utf-8") as f:
    records.append(json.load(f))
  except Exception:
   pass

   if not records:
    print("\n Nenhuma sessão de SaaS Metrics encontrada.")
    return

    RATIO_ICON = {"scale": "", "healthy": "", "optimize": "", "danger": "", "critical": ""}

    print("\n" + "" * 72)
    print(" SAAS METRICS — Histórico de Sessões")
    print("" * 72)
    print(f" {'#':<3} {'Produto':<22} {'LTV/CAC':>8} {'CAC':>8} {'LTV':>8} {'Churn':>7} {'MRR':>10} Status")
    print(" " + "" * 68)

    for i, r in enumerate(records[:15], 1):
     ratio = r.get("ltv_cac_ratio", 0)
     status = r.get("status", "danger")
     icon = RATIO_ICON.get(status, "?")
     print(f" {i:<3} {r.get('product_name','?')[:20]:<22} "
     f"{ratio:>6.1f}x "
     f"${r.get('cac',0):>6.0f} "
     f"${r.get('ltv',0):>6.0f} "
     f"{r.get('churn_rate',0)*100:>5.1f}% "
     f"${r.get('mrr',0):>8,.0f} "
     f"{icon} {status}")

     print("" * 72 + "\n")


# Persistência 

def _salvar_local(result: dict) -> str:
 os.makedirs(OUTPUTS_DIR, exist_ok=True)
 slug = result["product_name"].replace(" ", "_")[:28]
 fname = f"{OUTPUTS_DIR}/saas_metrics_{slug}_{result['timestamp']}.json"
 with open(fname, "w", encoding="utf-8") as f:
  json.dump(result, f, ensure_ascii=False, indent=2)
  return fname


async def _salvar_notion(result: dict):
 try:
  from integrations.notion_logger import salvar_tarefa
  a = result.get("analysis", {})
  p = result.get("growth_projection", {})
  body = (
  f"LTV/CAC: {result['ltv_cac_ratio']:.1f}x → {result['status'].upper()}\n"
  f"CAC: ${result['cac']:.2f} | LTV: ${result['ltv']:.2f} | "
  f"Churn: {result['churn_rate']*100:.1f}% | MRR: ${result['mrr']:,.2f}\n\n"
  f"Diagnóstico: {a.get('diagnostic','')}\n"
  f"Maior risco: {a.get('biggest_risk','')}\n\n"
  f"Projeção 12 meses:\n"
  f" Clientes: {p.get('12',{}).get('customers',0)}\n"
  f" MRR: ${p.get('12',{}).get('mrr',0):,.0f}\n"
  f" ARR: ${p.get('12',{}).get('arr',0):,.0f}\n\n"
  f"Caminho de crescimento: {a.get('growth_path','')}"
  )
  await salvar_tarefa(
  f"SaaS Metrics: {result['product_name'][:45]} → "
  f"{result['ltv_cac_ratio']:.1f}x LTV/CAC ({result['status'].upper()})",
  "saas_metrics_engine",
  body,
  )
 except Exception:
  pass


def _atualizar_dashboard():
 import subprocess, sys as _sys
 script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generate_dashboard.py")
 if not os.path.exists(script):
  return
  try:
   subprocess.run([_sys.executable, script], check=True, capture_output=True)
   dashboard = os.path.join(os.path.dirname(script), "dashboard.html")
   subprocess.Popen(["open", dashboard])
   print(" Dashboard atualizado.")
  except Exception as e:
   print(f" Dashboard: {e}")


# Display terminal 

def _imprimir(result: dict):
 a = result.get("analysis", {})
 proj = result.get("growth_projection", {})
 hist = result.get("history", [])

 STATUS_BLOCK = {
 "scale": " ESCALAR AGRESSIVAMENTE",
 "healthy": " NEGÓCIO SAUDÁVEL",
 "optimize": " OTIMIZAR ANTES DE ESCALAR",
 "danger": " PERIGO — AJUSTAR AGORA",
 "critical": " CRÍTICO — PARAR IMEDIATAMENTE",
 }
 CHURN_ICON = {
 "excellent": " EXCELENTE",
 "ok": " OK",
 "high": " ALTO",
 "critical": " CRÍTICO",
 }

 ratio = result["ltv_cac_ratio"]
 churn = result["churn_rate"] * 100

 print("\n" + "" * 62)
 print(f" SAAS METRICS ENGINE — {result['product_name'][:35]}")
 print("" * 62)

 # Bloco principal
 print(f"\n {''*58}")
 print(f" {'CAC':<28}: ${result['cac']:>10.2f}")
 print(f" {'LTV':<28}: ${result['ltv']:>10.2f}")
 print(f" {'LTV / CAC Ratio':<28}: {ratio:>10.2f}x")
 print(f" {''*58}")
 print(f" {'MRR':<28}: ${result['mrr']:>10,.2f}")
 print(f" {'ARR':<28}: ${result['arr']:>10,.2f}")
 print(f" {'Ticket médio':<28}: ${result['avg_revenue']:>10.2f}")
 print(f" {'Churn mensal':<28}: {churn:>9.1f}% {CHURN_ICON.get(result['churn_status'],'')}")
 print(f" {'Lifetime (meses)':<28}: {result['lifetime']:>10.1f}")
 print(f" {'Payback period':<28}: {result['payback_months']:>9.1f}m")
 print(f" {''*58}")
 print(f" {STATUS_BLOCK.get(result['status'], result['status'].upper())}")
 print(f" {''*58}")

 # Alertas
 alerts = [
 a.get("cac_alert"), a.get("ltv_alert"),
 a.get("churn_alert"), a.get("burn_warning"),
 ]
 alerts = [al for al in alerts if al]
 if alerts:
  print(f"\n Alertas ")
  for al in alerts:
   print(f" {al[:100]}")

   if a.get("diagnostic"):
    print(f"\n Diagnóstico: {a['diagnostic']}")
    if a.get("biggest_risk"):
     print(f" Maior risco: {a['biggest_risk'][:100]}")

     if a.get("actions"):
      print(f"\n Ações para melhorar a saúde ")
      for ac in a["actions"]:
       print(f" → {ac[:100]}")

       if a.get("retention_tactics"):
        print(f"\n Táticas de Retenção (anti-churn) ")
        for t in a["retention_tactics"]:
         print(f" {t[:100]}")

         if a.get("acquisition_efficiency"):
          print(f"\n Eficiência de aquisição: {a['acquisition_efficiency'][:100]}")

          if a.get("growth_path"):
           print(f" Caminho de crescimento: {a['growth_path'][:100]}")

           # Projeção
           print(f"\n Projeção de Crescimento ")
           print(f" {'Período':<10} {'Clientes':>10} {'MRR':>12} {'ARR':>12}")
           print(f" {''*48}")
           for k in ["3", "6", "12"]:
            sc = proj.get(k, {})
            print(f" {k+'m':<10} {sc.get('customers',0):>10} ${sc.get('mrr',0):>11,.0f} ${sc.get('arr',0):>11,.0f}")

            # Tendência histórica
            if len(hist) > 1:
             print(f"\n Tendência LTV/CAC ({len(hist)} sessões) ")
             for h in hist:
              icon = "↑" if h["ltv_cac"] >= 3 else "↓"
              print(f" {icon} {h['timestamp'][:15]} ratio {h['ltv_cac']:.1f}x "
              f"churn {h['churn_rate']*100:.1f}% MRR ${h['mrr']:,.0f}")

              print(f"\n Custo análise: ~${result.get('total_cost',0):.4f}")
              print("" * 62 + "\n")

              print(" Response (Node):")
              print(json.dumps(result["response"], ensure_ascii=False, indent=2))
              print()


# Modo interativo 

def _interactive_input() -> dict:
 print("\n" + "" * 62)
 print(" SAAS METRICS ENGINE — Input Interativo")
 print("" * 62)

 name = input(" Produto: ").strip() or "Produto"
 total = int(input(" Total de clientes ativos: ").strip() or "0")
 new_c = int(input(" Clientes novos este mês: ").strip() or "0")
 churned = int(input(" Clientes que saíram este mês: ").strip() or "0")
 revenue = float(input(" Receita mensal total ($): ").strip() or "0")
 ticket = float(input(" Ticket médio/cliente ($, se souber): ").strip() or "0")
 mkt_cost = float(input(" Gasto em marketing este mês ($): ").strip() or "0")

 print(f"\n Churn manual (deixe 0 para calcular automaticamente):")
 churn_manual = float(input(" Churn rate % [0]: ").strip() or "0") / 100

 return {
 "product_name": name,
 "total_customers": total,
 "new_customers": new_c,
 "churned_customers": churned,
 "revenue": revenue,
 "avg_ticket": ticket,
 "marketing_cost": mkt_cost,
 "churn_rate": churn_manual,
 }


# CLI 

async def main():
 args = sys.argv[1:]

 if "--history" in args:
  show_history()
  return

  if "--json" in args:
   idx = args.index("--json")
   raw = json.loads(args[idx + 1])
   await run_saas_metrics(raw)
   return

   if "--title" in args:
    idx = args.index("--title")
    title = args[idx + 1] if idx + 1 < len(args) else ""
    records = []
    for path in sorted(glob.glob(f"{OUTPUTS_DIR}/saas_metrics_*.json"), reverse=True):
     try:
      with open(path, encoding="utf-8") as f:
       d = json.load(f)
       if title.lower() in d.get("product_name", "").lower():
        records.append(d)
     except Exception:
      pass
      if not records:
       print(f"\n Nenhum dado encontrado para: {title}")
      else:
       show_history()
       return

       raw = _interactive_input()
       await run_saas_metrics(raw)


if __name__ == "__main__":
 asyncio.run(main())
