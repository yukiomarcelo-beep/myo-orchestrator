#!/usr/bin/env python3
"""
AI Pricing Engine — Pipeline AI
Define preço ideal, estrutura de planos e estratégia de entrada.

Responde:
 1. Qual é o preço mínimo seguro?
 2. Qual é o preço ideal para margem-alvo?
 3. Qual é o preço premium possível?
 4. Qual estrutura de planos maximiza receita?

Fluxo:
 Input (produto + custo + mercado)
 → Pricing Calculation (lógica) — min / ideal / premium
 → Plan Structure (lógica) — basic / pro / premium
 → Claude Pricing AI (Claude) — percepção, risco, estratégia
 → Impact Simulation (lógica) — comparativo preço atual vs ideal
 → Save (local) — persiste em pricing_*.json
 → Output (terminal + Notion + Dashboard)

Regras:
 Preço mínimo = custo / (1 - margem_alvo)
 Preço ideal = mínimo × 1.2 (buffer de segurança)
 Premium = ideal × 1.5 (valor percebido alto)

Uso:
 python pricing_engine.py # modo interativo
 python pricing_engine.py --json '{...}' # input manual
 python pricing_engine.py --ranking # ranking de produtos
"""
import asyncio
import json
import os
import sys
import time
import glob
import math
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"
OUTPUTS_DIR = "outputs"

VALUE_LEVELS = {
    "low": {"label": "Baixo", "multiplier": 0.85},
    "medium": {"label": "Médio", "multiplier": 1.0},
    "high": {"label": "Alto", "multiplier": 1.25},
    "ultra": {"label": "Ultra", "multiplier": 1.5},
}


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

def _p_pricing_intelligence(data: dict) -> str:
    comp_prices = data.get("competitor_prices", [])
    comp_str = f"${min(comp_prices)} – ${max(comp_prices)}" if comp_prices else "não informado"
    value_label = VALUE_LEVELS.get(data.get("value_level", "medium"), {}).get("label", "Médio")

    return f"""Você é um especialista em precificação de produtos SaaS e digitais.

Analise a estratégia de preços para este produto:

Produto : {data.get('product_name', '')}
Mercado : {data.get('market', 'BR')}
Custo/usuário : ${data.get('cost_per_user', 0):.2f}
Margem-alvo : {data.get('target_margin', 0.7)*100:.0f}%
Nível de valor : {value_label}
Range concorrência: {comp_str}

Preços calculados:
- Preço mínimo (garante margem): ${data.get('min_price', 0):.2f}
- Preço ideal (buffer 20%): ${data.get('suggested_price', 0):.2f}
- Preço premium: ${data.get('premium_price', 0):.2f}

Preço atual (se informado): ${data.get('current_price', 0):.2f}

Retorne análise completa em JSON:

{{
 "final_price": 0,
 "value_perception": "",
 "rejection_risk": "",
 "entry_strategy": "",
 "plans": [
 {{"name": "Basic", "price": 0, "features": [], "limit": ""}},
 {{"name": "Pro", "price": 0, "features": [], "limit": ""}},
 {{"name": "Premium", "price": 0, "features": [], "limit": ""}}
 ],
 "positioning": "",
 "anchor_price": 0,
 "launch_tactic": "",
 "warning": ""
}}

- final_price: preço ideal final recomendado (número inteiro)
- value_perception: como o cliente percebe o valor (1-2 frases)
- rejection_risk: "baixo" / "médio" / "alto" — explique o motivo
- entry_strategy: "agressivo" / "valor" / "premium" — com justificativa
- plans: 3 planos com nomes, preços, lista de 3-4 features e limite de uso
- positioning: como posicionar o produto no mercado
- anchor_price: preço âncora para usar no marketing (sempre maior que final_price)
- launch_tactic: tática de lançamento específica para o mercado informado
- warning: alerta crítico se preço atual estiver abaixo do mínimo seguro (ou "" se ok)

Responda APENAS em JSON válido."""


def _p_impact_analysis(data: dict, pricing: dict) -> str:
    current = data.get("current_price", 0)
    ideal = pricing.get("final_price", data.get("suggested_price", 0))
    cost = data.get("cost_per_user", 0)

    margin_current = ((current - cost) / current * 100) if current > 0 else 0
    margin_ideal = ((ideal - cost) / ideal * 100) if ideal > 0 else 0

    return f"""Produto: {data.get('product_name', '')}
Custo/usuário: ${cost:.2f}

Cenário atual: Preço ${current:.2f} → Margem {margin_current:.1f}%
Cenário ideal: Preço ${ideal:.2f} → Margem {margin_ideal:.1f}%

Com base nisso, gere uma simulação de impacto financeiro para 3 escalas de usuários.

Responda APENAS em JSON válido:

{{
 "scenarios": [
 {{
 "users": 100,
 "current_profit": 0,
 "ideal_profit": 0,
 "delta_pct": 0
 }},
 {{
 "users": 500,
 "current_profit": 0,
 "ideal_profit": 0,
 "delta_pct": 0
 }},
 {{
 "users": 1000,
 "current_profit": 0,
 "ideal_profit": 0,
 "delta_pct": 0
 }}
 ],
 "summary": ""
}}

- Calcule current_profit = (current_price - cost) * users
- Calcule ideal_profit = (ideal_price - cost) * users
- delta_pct = ((ideal - current) / current) * 100 se current > 0
- summary: frase direta sobre o impacto da mudança de preço"""


# Lógica de cálculo

def _calculate_prices(raw: dict) -> dict:
    """Pricing Calculation Node."""
    cost = raw.get("cost_per_user", 0) or 0
    target_margin = raw.get("target_margin", 0.7) or 0.7
    value_level = raw.get("value_level", "medium")
    multiplier = VALUE_LEVELS.get(value_level, {}).get("multiplier", 1.0)

    # Preço mínimo para atingir margem-alvo
    min_price = cost / (1 - target_margin) if target_margin < 1 else cost * 3

    # Preço sugerido com buffer de segurança + ajuste de valor percebido
    suggested_price = min_price * 1.2 * multiplier

    # Preço premium
    premium_price = suggested_price * 1.5

    # Arredonda para número de marketing (ex: 43 → 47, 52 → 57)
    # Para valores < 10, retorna o próximo inteiro sem ancoragem psicológica
    def market_round(p):
        base = math.ceil(p)
    if base < 10:
        return base
    if base % 10 <= 5:
        return (base // 10) * 10 + 7
    return (base // 10) * 10 + 9

    return {
        **raw,
        "min_price": round(min_price, 2),
        "suggested_price": market_round(suggested_price),
        "premium_price": market_round(premium_price),
    }


def _plan_structure(data: dict) -> dict:
    """Plan Structure Node."""
    min_p = data.get("min_price", 0)
    sug_p = data.get("suggested_price", 0)
    pre_p = data.get("premium_price", 0)

    def mkt(p):
        import math
    base = math.ceil(p)
    if base < 10:
        return base
    return (base // 10) * 10 + (7 if base % 10 <= 5 else 9)

    return {
        "basic": {"price": mkt(min_p * 0.7), "limit": "uso limitado"},
        "pro": {"price": sug_p, "limit": "uso padrão"},
        "premium": {"price": pre_p, "limit": "uso completo"},
    }


def _impact_simulation(data: dict, final_price: float) -> list:
    """Simula impacto financeiro comparando preço atual vs ideal."""
    cost = data.get("cost_per_user", 0)
    current = data.get("current_price", 0)
    ideal = final_price

    scenarios = []
    for n in [100, 500, 1000]:
        curr_profit = (current - cost) * n if current > 0 else 0
    ideal_profit = (ideal - cost) * n
    if curr_profit != 0:
        delta = (ideal_profit - curr_profit) / abs(curr_profit) * 100
    elif ideal_profit != 0:
        delta = 100.0  # sem base de comparação: mostra ganho de 100%
    else:
        delta = 0.0
    scenarios.append({
        "users": n,
        "current_profit": round(curr_profit, 2),
        "ideal_profit": round(ideal_profit, 2),
        "delta_pct": round(delta, 1),
        "no_base": current == 0,  # flag para o display omitir a coluna "atual"
    })
    return scenarios


# Fluxo principal

async def run_pricing(raw_input: dict) -> dict:
    name = raw_input.get("product_name", "?")
    print(f"\n AI Pricing Engine: {name[:55]}")
    print(" " + "" * 56)

    # [1] Calculate Prices
    print(" [1/5] Calculando preços...")
    data = _calculate_prices(raw_input)
    margin_at_suggested = ((data["suggested_price"] - data["cost_per_user"]) / data["suggested_price"] * 100) if data["suggested_price"] > 0 else 0
    print(f" Mínimo ${data['min_price']:.2f} | "
          f"Ideal ${data['suggested_price']} | "
          f"Premium ${data['premium_price']}")
    print(f" Margem no ideal: {margin_at_suggested:.1f}%")

    # [2] Plan Structure
    print(" [2/5] Estruturando planos...")
    data["timestamp"] = time.strftime("%Y%m%d_%H%M%S")
    plans_calc = _plan_structure(data)
    data["plans_calculated"] = plans_calc
    print(f" Basic ${plans_calc['basic']['price']} | "
          f"Pro ${plans_calc['pro']['price']} | "
          f"Premium ${plans_calc['premium']['price']}")

    # [3] Claude Pricing Intelligence
    print(" [3/5] Claude Pricing Intelligence...")
    pricing_raw, m1 = await _claude(_p_pricing_intelligence(data))
    pricing = pricing_raw if isinstance(pricing_raw, dict) else {}
    final_price = pricing.get("final_price") or data["suggested_price"]
    print(f" Preço final recomendado: ${final_price} · {m1['latency_ms']}ms · ${m1['cost']:.4f}")

    # [4] Impact Simulation
    print(" [4/5] Simulando impacto financeiro...")
    scenarios_local = _impact_simulation(data, final_price)
    total_cost = m1["cost"]
    delta_1k = next((s["delta_pct"] for s in scenarios_local if s["users"] == 1000), 0)
    print(f" 1.000 usuários → lucro ideal ${scenarios_local[2]['ideal_profit']:,.0f} "
          f"({'+' if delta_1k >= 0 else ''}{delta_1k:.0f}% vs atual)")

    # [5] Save
    print(" [5/5] Salvando resultado...")

    current_price = raw_input.get("current_price", 0)
    current_margin = ((current_price - data["cost_per_user"]) / current_price * 100) if current_price > 0 else 0
    ideal_margin = ((final_price - data["cost_per_user"]) / final_price * 100) if final_price > 0 else 0

    result = {
        "product_name": name,
        "cost_per_user": data["cost_per_user"],
        "target_margin": data.get("target_margin", 0.7),
        "current_price": current_price,
        "min_price": data["min_price"],
        "suggested_price": data["suggested_price"],
        "premium_price": data["premium_price"],
        "final_price": final_price,
        "current_margin": round(current_margin, 3),
        "ideal_margin": round(ideal_margin, 3),
        "plans_calculated": plans_calc,
        "competitor_prices": raw_input.get("competitor_prices", []),
        "value_level": raw_input.get("value_level", "medium"),
        "market": raw_input.get("market", "BR"),
        "pricing_intel": pricing,
        "impact_scenarios": scenarios_local,
        "total_cost": total_cost,
        "timestamp": data["timestamp"],
        "response": {
            "status": "success",
            "product_name": name,
            "final_price": final_price,
            "current_price": current_price,
            "current_margin": round(current_margin, 1),
            "ideal_margin": round(ideal_margin, 1),
            "entry_strategy": pricing.get("entry_strategy", ""),
            "rejection_risk": pricing.get("rejection_risk", ""),
            "warning": pricing.get("warning", ""),
        },
    }

    fname = _salvar_local(result)
    print(f" Salvo em {fname}")

    _imprimir(result)
    await _salvar_notion(result)
    _atualizar_dashboard()

    return result


# Ranking

def show_ranking():
    files = sorted(glob.glob(f"{OUTPUTS_DIR}/pricing_*.json"), reverse=True)
    if not files:
        print("\n Nenhuma análise de pricing encontrada.")
    print(" Rode: python pricing_engine.py")
    return

    records = []
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                records.append(json.load(f))
        except Exception:
                    pass

    print("\n" + "" * 72)
    print(" AI PRICING ENGINE — Ranking de Produtos")
    print("" * 72)
    print(f" {'#':<3} {'Atual':>8} {'Ideal':>8} {'Margem':>8} {'Δ Lucro 1k':>12} Produto")
    print(" " + "" * 66)

    for i, r in enumerate(records, 1):
        current = r.get("current_price", 0)
    ideal = r.get("final_price", 0)
    margin = r.get("ideal_margin", 0) * 100
    sc = next((s for s in r.get("impact_scenarios", []) if s["users"] == 1000), {})
    delta = sc.get("delta_pct", 0)
    name = r.get("product_name", "?")[:35]
    warn = " " if r.get("pricing_intel", {}).get("warning") else ""
    delta_str = f"+{delta:.0f}%" if delta > 0 else f"{delta:.0f}%"
    print(f" {i:<3} ${current:>7.2f} ${ideal:>7.2f} {margin:>7.1f}% {delta_str:>12} {name}{warn}")
    strategy = r.get("pricing_intel", {}).get("entry_strategy", "")
    if strategy:
        print(f" Estratégia: {strategy[:70]}")

    print("" * 72 + "\n")


# Persistência

def _salvar_local(result: dict) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    slug = result["product_name"].replace(" ", "_")[:28]
    fname = f"{OUTPUTS_DIR}/pricing_{slug}_{result['timestamp']}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return fname


async def _salvar_notion(result: dict):
    try:
        from notion_logger import salvar_tarefa
        p = result.get("pricing_intel", {})
        sc = next((s for s in result.get("impact_scenarios", []) if s["users"] == 1000), {})
        body = (
        f"Preço atual: ${result.get('current_price', 0):.2f} → Margem {result.get('current_margin', 0)*100:.1f}%\n"
        f"Preço ideal: ${result.get('final_price', 0):.2f} → Margem {result.get('ideal_margin', 0)*100:.1f}%\n\n"
        f"Estratégia: {p.get('entry_strategy', '')}\n"
        f"Risco de rejeição: {p.get('rejection_risk', '')}\n\n"
        f"Impacto 1.000 usuários:\n"
        f" Lucro atual: ${sc.get('current_profit', 0):,.0f}\n"
        f" Lucro ideal: ${sc.get('ideal_profit', 0):,.0f} (+{sc.get('delta_pct', 0):.0f}%)\n\n"
        f"Posicionamento: {p.get('positioning', '')}\n"
        f"Tática de lançamento: {p.get('launch_tactic', '')}"
    )
        await salvar_tarefa(
        f"Pricing: {result['product_name'][:50]} → ${result.get('final_price', 0)} "
        f"(margem {result.get('ideal_margin', 0)*100:.0f}%)",
        "pricing_engine",
        body,
    )
    except Exception:
            pass


def _atualizar_dashboard():
    import subprocess
    import sys as _sys
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
    p = result.get("pricing_intel", {})
    sc = result.get("impact_scenarios", [])
    plans = p.get("plans", result.get("plans_calculated", {}))
    calc = result.get("plans_calculated", {})

    RISK_COLOR = {"baixo": "", "médio": "", "alto": ""}
    STRAT_ICON = {"agressivo": "", "valor": "", "premium": ""}

    current_margin = result.get("current_margin", 0) * 100
    ideal_margin = result.get("ideal_margin", 0) * 100

    print("\n" + "" * 62)
    print(f" AI PRICING ENGINE — {result['product_name'][:40]}")
    print("" * 62)

    # Bloco de preços
    print(f"\n {''*58}")
    if result.get("current_price"):
        margin_icon = "" if current_margin >= 60 else "" if current_margin >= 40 else ""
    print(f" {'Preço atual':<22}: ${result['current_price']:>8.2f} {margin_icon} margem {current_margin:.1f}%")
    print(f" {'Preço mínimo seguro':<22}: ${result['min_price']:>8.2f}")
    print(f" {'Preço ideal (sugerido)':<22}: ${result['suggested_price']:>8.2f} margem {ideal_margin:.1f}%")
    print(f" {'Preço premium':<22}: ${result['premium_price']:>8.2f}")
    if p.get("final_price"):
        print(f" {''*58}")
    print(f" {'PREÇO FINAL RECOMENDADO':<22}: ${p['final_price']:>8.2f} ")
    print(f" {''*58}")

    # Alerta
    if p.get("warning"):
        print(f"\n ALERTA: {p['warning']}")

    # Diagnóstico
    if p.get("value_perception"):
        print(f"\n Percepção de valor: {p['value_perception'][:100]}")

    risk = p.get("rejection_risk", "")
    if risk:
        icon = RISK_COLOR.get(risk.split()[0].lower(), "?")
    print(f" Risco de rejeição: {icon} {risk[:100]}")

    strat = p.get("entry_strategy", "")
    if strat:
        icon = STRAT_ICON.get(strat.split()[0].lower(), "→")
    print(f" Estratégia: {icon} {strat[:100]}")

    if p.get("positioning"):
        print(f" Posicionamento: {p['positioning'][:100]}")

    if p.get("launch_tactic"):
        print(f" Tática de lançamento: {p['launch_tactic'][:100]}")

    # Planos
    plans_list = p.get("plans") if isinstance(p.get("plans"), list) else []
    if plans_list:
        print(f"\n Estrutura de Planos ")
    for pl in plans_list:
        feats = " · ".join(pl.get("features", [])[:3])
    print(f" {' '+pl.get('name', ''):<12} ${pl.get('price', 0):>6} {pl.get('limit', '')[:30]}")
    if feats:
        print(f" {feats[:56]}")
    else:
        print(f"\n Planos Calculados ")
    for key, pl in calc.items():
        print(f" {' '+key.upper():<12} ${pl.get('price', 0):>6} {pl.get('limit', '')}")

    if p.get("anchor_price"):
        print(f"\n Preço âncora para marketing: ${p['anchor_price']}")

    # Impacto
    if sc:
        has_base = any(not s.get("no_base") for s in sc)
    print(f"\n Simulação de Impacto ")
    if has_base:
        print(f" {'Usuários':<10} {'Lucro Atual':>14} {'Lucro Ideal':>14} {'Delta':>8}")
    else:
        print(f" {'Usuários':<10} {'Lucro Ideal':>14}")
    print(f" {''*50}")
    for s in sc:
        delta_str = f"+{s['delta_pct']:.0f}%" if s["delta_pct"] > 0 else f"{s['delta_pct']:.0f}%"
    delta_color = "" if s["delta_pct"] > 0 else ""
    if has_base:
        print(f" {str(s['users'])+'u':<10} ${s['current_profit']:>13,.0f} ${s['ideal_profit']:>13,.0f} {delta_color}{delta_str:>7}")
    else:
        print(f" {str(s['users'])+'u':<10} ${s['ideal_profit']:>13,.0f}")

    print(f"\n Custo análise: ~${result.get('total_cost', 0):.4f}")
    print("" * 62 + "\n")

    print(" Response (Node):")
    print(json.dumps(result["response"], ensure_ascii=False, indent=2))
    print()


# Modo interativo

def _interactive_input() -> dict:
    print("\n" + "" * 62)
    print(" AI PRICING ENGINE — Input Interativo")
    print("" * 62)

    name = input(" Produto: ").strip() or "Produto"
    cost = float(input(" Custo/usuário ($): ").strip() or "0")
    current = float(input(" Preço atual ($, 0 se não tiver): ").strip() or "0")
    margin = float(input(" Margem-alvo % [70]: ").strip() or "70") / 100
    market = input(" Mercado [BR/US/LATAM]: ").strip() or "BR"

    print("\n Nível de valor percebido do produto:")
    print(" low / medium / high / ultra")
    value = input(" Nível [medium]: ").strip() or "medium"

    print("\n Preços dos concorrentes (Enter para pular)")
    print(" Ex: 19 29 49 99")
    comp_str = input(" Preços: ").strip()
    comp = [float(x) for x in comp_str.split() if x.replace(".", "").isdigit()] if comp_str else []

    return {
        "product_name": name,
        "cost_per_user": cost,
        "current_price": current,
        "target_margin": margin,
        "market": market,
        "value_level": value,
        "competitor_prices": comp,
    }


# CLI

async def main():
    args = sys.argv[1:]

    if "--ranking" in args:
        show_ranking()
    return

    if "--json" in args:
        idx = args.index("--json")
    raw = json.loads(args[idx + 1])
    await run_pricing(raw)
    return

    raw = _interactive_input()
    await run_pricing(raw)


if __name__ == "__main__":
    asyncio.run(main())
