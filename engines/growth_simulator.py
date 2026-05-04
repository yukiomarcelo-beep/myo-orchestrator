#!/usr/bin/env python3
"""
Growth Simulator — Simulador de Crescimento e Painel de CEO
Uso: python growth_simulator.py [opções]

Exemplos:
  python growth_simulator.py --leads 30 --conversion 0.10 --ticket 200 --cost 5000
  python growth_simulator.py --ads --investment 2000 --cpl 8
  python growth_simulator.py --breakeven
  python growth_simulator.py --history
  python growth_simulator.py            # último simulador salvo
"""

import argparse
import asyncio
import json
import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv()
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OUTPUTS_DIR = "outputs"
SIM_FILE = os.path.join(OUTPUTS_DIR, "simulations.json")

os.makedirs(OUTPUTS_DIR, exist_ok=True)

# ── persistência ──────────────────────────────────────────────────────────────


def _load_all() -> list:
    if os.path.exists(SIM_FILE):
        try:
            with open(SIM_FILE, encoding="utf-8") as f:
                d = json.load(f)
                return d if isinstance(d, list) else []
        except Exception:
            pass
    return []


def _save_all(sims: list):
    with open(SIM_FILE, "w", encoding="utf-8") as f:
        json.dump(sims, f, ensure_ascii=False, indent=2)


# ── Claude ────────────────────────────────────────────────────────────────────


async def _claude(prompt: str) -> str:
    if not ANTHROPIC_KEY:
        return ""
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1200,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


# ── cálculos core ─────────────────────────────────────────────────────────────


def _calc(leads: float, conversion: float, ticket: float, monthly_cost: float) -> dict:
    """Fórmula base: Receita = Leads × Conversão × Ticket."""
    revenue_day = leads * conversion * ticket
    revenue_month = revenue_day * 30
    profit = revenue_month - monthly_cost
    margin = round(profit / revenue_month, 4) if revenue_month > 0 else 0.0
    roi = round(profit / monthly_cost, 4) if monthly_cost > 0 else 0.0
    return {
        "leads_dia": round(leads, 1),
        "conversion": round(conversion, 4),
        "conversion_pct": round(conversion * 100, 2),
        "ticket": round(ticket, 2),
        "revenue_day": round(revenue_day, 2),
        "revenue_month": round(revenue_month, 2),
        "monthly_cost": round(monthly_cost, 2),
        "profit": round(profit, 2),
        "margin": margin,
        "margin_pct": round(margin * 100, 1),
        "roi": roi,
        "roi_pct": round(roi * 100, 1),
    }


def run_scenarios(leads: float, conversion: float, ticket: float, monthly_cost: float) -> dict:
    """Node Scenario_Engine — 4 cenários + variações de alavanca."""
    base = _calc(leads, conversion, ticket, monthly_cost)

    scenarios = {
        "base": _calc(leads, conversion, ticket, monthly_cost),
        "dobrar_leads": _calc(leads * 2, conversion, ticket, monthly_cost),
        "melhorar_conversao": _calc(leads, conversion * 1.5, ticket, monthly_cost),
        "aumentar_preco": _calc(leads, conversion, ticket * 1.3, monthly_cost),
        "combo_leve": _calc(leads * 1.3, conversion * 1.2, ticket * 1.1, monthly_cost),
        "combo_agressivo": _calc(leads * 2, conversion * 1.5, ticket * 1.3, monthly_cost),
    }

    # delta % de lucro vs base
    base_profit = base["profit"]
    for name, sc in scenarios.items():
        if name == "base":
            sc["delta_lucro_pct"] = 0.0
        else:
            if base_profit != 0:
                sc["delta_lucro_pct"] = round(
                    (sc["profit"] - base_profit) / abs(base_profit) * 100, 1
                )
            else:
                sc["delta_lucro_pct"] = round(sc["profit"] * 100, 1)

    # ranking por impacto no lucro
    ranking = sorted(
        [(n, s["delta_lucro_pct"]) for n, s in scenarios.items() if n != "base"],
        key=lambda x: -x[1],
    )

    return {
        "input": {
            "leads": leads,
            "conversion": conversion,
            "ticket": ticket,
            "monthly_cost": monthly_cost,
        },
        "scenarios": scenarios,
        "ranking": ranking,
    }


def calc_ads_impact(
    investment: float, cpl: float, conversion: float, ticket: float, monthly_cost: float
) -> dict:
    """Simulação com Ads: Investimento + CPL → leads extras → impacto."""
    extra_leads = investment / cpl if cpl > 0 else 0
    extra_revenue = extra_leads * conversion * ticket
    extra_profit = extra_revenue - investment
    roas = round(extra_revenue / investment, 2) if investment > 0 else 0.0

    return {
        "investment": round(investment, 2),
        "cpl": round(cpl, 2),
        "extra_leads": round(extra_leads, 1),
        "extra_revenue": round(extra_revenue, 2),
        "extra_profit": round(extra_profit, 2),
        "roas": roas,
        "viable": roas >= 2.0,
    }


def calc_breakeven(conversion: float, ticket: float, monthly_cost: float) -> dict:
    """Quantos leads/dia precisa para não ter prejuízo."""
    if conversion <= 0 or ticket <= 0:
        return {"breakeven_leads_dia": 0, "breakeven_leads_mes": 0}
    leads_mes = monthly_cost / (conversion * ticket)
    leads_dia = leads_mes / 30
    return {
        "breakeven_leads_dia": round(leads_dia, 1),
        "breakeven_leads_mes": round(leads_mes, 1),
        "monthly_cost": round(monthly_cost, 2),
        "conversion": round(conversion, 4),
        "ticket": round(ticket, 2),
    }


# ── decisão automática (regras) ───────────────────────────────────────────────


def _auto_decision(scenarios: dict, ranking: list) -> dict:
    """Baseado no ranking de cenários, define ação prioritária."""
    LABEL = {
        "dobrar_leads": "Dobrar produção de conteúdo e tráfego (leads 2x)",
        "melhorar_conversao": "Melhorar CTA, oferta e copywriting (conversão +50%)",
        "aumentar_preco": "Subir preço do produto em 30%",
        "combo_leve": "Combo leve: +30% leads, +20% conversão, +10% preço",
        "combo_agressivo": "Combo agressivo: dobrar leads + conversão + preço",
    }
    DIFICULDADE = {
        "dobrar_leads": "media",
        "melhorar_conversao": "baixa",
        "aumentar_preco": "baixa",
        "combo_leve": "media",
        "combo_agressivo": "alta",
    }

    if not ranking:
        return {}

    prioridade = ranking[0][0]
    secundaria = ranking[1][0] if len(ranking) > 1 else None
    futura = ranking[2][0] if len(ranking) > 2 else None

    return {
        "acao_prioritaria": {
            "nome": prioridade,
            "descricao": LABEL.get(prioridade, ""),
            "dificuldade": DIFICULDADE.get(prioridade, "media"),
            "impacto_pct": ranking[0][1],
        },
        "acao_secundaria": {
            "nome": secundaria,
            "descricao": LABEL.get(secundaria, ""),
            "dificuldade": DIFICULDADE.get(secundaria, "media"),
            "impacto_pct": ranking[1][1] if len(ranking) > 1 else 0,
        }
        if secundaria
        else {},
        "acao_futura": {
            "nome": futura,
            "descricao": LABEL.get(futura, ""),
            "dificuldade": DIFICULDADE.get(futura, "media"),
            "impacto_pct": ranking[2][1] if len(ranking) > 2 else 0,
        }
        if futura
        else {},
    }


# ── Claude insights ───────────────────────────────────────────────────────────


async def get_insights(sim_result: dict) -> dict:
    if not ANTHROPIC_KEY:
        return {}

    sc = sim_result.get("scenarios", {})
    rank = sim_result.get("ranking", [])
    base = sc.get("base", {})
    inp = sim_result.get("input", {})

    prompt = f"""Você é um estrategista de crescimento para negócios online de alto ticket.

SITUAÇÃO BASE:
- Leads/dia    : {inp.get('leads', 0)}
- Conversão    : {inp.get('conversion', 0)*100:.1f}%
- Ticket       : R${inp.get('ticket', 0):,.2f}
- Receita/mês  : R${base.get('revenue_month', 0):,.2f}
- Custo/mês    : R${inp.get('monthly_cost', 0):,.2f}
- Lucro/mês    : R${base.get('profit', 0):,.2f}
- Margem       : {base.get('margin_pct', 0):.1f}%

CENÁRIOS SIMULADOS (impacto no lucro):
{json.dumps([{"cenario": n, "delta_lucro": f"+{d}%"} for n, d in rank], ensure_ascii=False)}

MELHOR CENÁRIO INDIVIDUAL: {rank[0][0] if rank else "N/A"} ({rank[0][1] if rank else 0}% impacto)

Retorne SOMENTE JSON válido:
{{
  "alavanca_maior_impacto": "nome da alavanca",
  "por_que": "explicação em 1 frase",
  "mais_facil_executar": "nome da alavanca mais fácil",
  "estrategia_agora": "o que fazer nos próximos 7 dias",
  "plano_acao": [
    {{"semana": 1, "acao": "...", "meta": "..."}},
    {{"semana": 2, "acao": "...", "meta": "..."}},
    {{"semana": 3, "acao": "...", "meta": "..."}},
    {{"semana": 4, "acao": "...", "meta": "..."}}
  ],
  "alerta": "um risco ou erro a evitar",
  "projecao_realista_30d": 0,
  "projecao_otimista_90d": 0
}}"""

    try:
        raw = await _claude(prompt)
        s = raw.find("{")
        e = raw.rfind("}") + 1
        if s >= 0 and e > s:
            return json.loads(raw[s:e])
    except Exception as ex:
        return {"estrategia_agora": f"Erro: {ex}"}
    return {}


# ── simulação completa ────────────────────────────────────────────────────────


async def run_simulation(
    leads: float, conversion: float, ticket: float, monthly_cost: float, with_claude: bool = True
) -> dict:
    sim = run_scenarios(leads, conversion, ticket, monthly_cost)
    decision = _auto_decision(sim["scenarios"], sim["ranking"])
    bev = calc_breakeven(conversion, ticket, monthly_cost)
    insights = await get_insights(sim) if with_claude else {}

    result = {
        **sim,
        "breakeven": bev,
        "decision": decision,
        "insights": insights,
        "timestamp": time.strftime("%Y%m%d_%H%M%S"),
    }

    sims = _load_all()
    sims.append(result)
    sims = sims[-50:]  # mantém últimas 50
    _save_all(sims)
    return result


# ── display terminal ──────────────────────────────────────────────────────────


def _bar(val: float, max_val: float, width: int = 20) -> str:
    pct = min(1.0, val / max_val) if max_val > 0 else 0
    filled = round(pct * width)
    return "█" * filled + "░" * (width - filled)


def show_result(r: dict):
    sc = r.get("scenarios", {})
    base = sc.get("base", {})
    bev = r.get("breakeven", {})
    dec = r.get("decision", {})
    ins = r.get("insights", {})
    rank = r.get("ranking", [])

    max_rev = max((s["revenue_month"] for s in sc.values()), default=1)

    print("\n" + "═" * 64)
    print("  🚀  GROWTH SIMULATOR — PAINEL DE CEO")
    print("═" * 64)

    # base
    print("\n  📊  SITUAÇÃO BASE")
    print(f"  Leads/dia    : {base.get('leads_dia', 0)}")
    print(f"  Conversão    : {base.get('conversion_pct', 0):.1f}%")
    print(f"  Ticket       : R${base.get('ticket', 0):,.2f}")
    print("  ──────────────────────────────────")
    print(f"  Receita/dia  : R${base.get('revenue_day', 0):,.2f}")
    print(f"  Receita/mês  : R${base.get('revenue_month', 0):,.2f}")
    print(f"  Custo/mês    : R${base.get('monthly_cost', 0):,.2f}")
    m_icon = (
        "🟢"
        if base.get("margin_pct", 0) >= 70
        else "🟡"
        if base.get("margin_pct", 0) >= 40
        else "🔴"
    )
    print(
        f"  Lucro/mês {m_icon}: R${base.get('profit', 0):,.2f}  ({base.get('margin_pct', 0):.1f}% margem)"
    )

    # breakeven
    print(
        f"\n  📍 BREAK-EVEN: {bev.get('breakeven_leads_dia', 0)} leads/dia necessários para cobrir custos"
    )

    # cenários
    SCNAME = {
        "base": "BASE ATUAL       ",
        "dobrar_leads": "DOBRAR LEADS     ",
        "melhorar_conversao": "MELHORAR CONVERSÃO",
        "aumentar_preco": "AUMENTAR PREÇO   ",
        "combo_leve": "COMBO LEVE       ",
        "combo_agressivo": "COMBO AGRESSIVO  ",
    }
    print("\n  📈  CENÁRIOS\n")
    for name, sc_item in sc.items():
        rev = sc_item.get("revenue_month", 0)
        prf = sc_item.get("profit", 0)
        dlt = sc_item.get("delta_lucro_pct", 0)
        bar = _bar(rev, max_rev)
        sign = "+" if dlt > 0 else ""
        dlt_str = f"  ({sign}{dlt:.0f}% lucro)" if name != "base" else ""
        print(f"  {SCNAME.get(name, name)}: R${rev:>10,.0f}  {bar}  lucro R${prf:>9,.0f}{dlt_str}")

    # ranking
    print("\n  🏆  RANKING DE ALAVANCAS (por impacto no lucro)")
    LABEL_SHORT = {
        "dobrar_leads": "Dobrar leads",
        "melhorar_conversao": "Melhorar conversão",
        "aumentar_preco": "Aumentar preço",
        "combo_leve": "Combo leve",
        "combo_agressivo": "Combo agressivo",
    }
    for i, (name, delta) in enumerate(rank, 1):
        medal = ["🥇", "🥈", "🥉", "  ", "  "][i - 1]
        print(f"  {medal} {LABEL_SHORT.get(name, name):<25}: +{delta:.0f}% lucro")

    # decisão
    if dec.get("acao_prioritaria"):
        print("\n  🤖  DECISÃO AUTOMÁTICA")
        p = dec["acao_prioritaria"]
        print(f"  🔴 PRIORITÁRIA : {p.get('descricao','')}  (+{p.get('impacto_pct',0):.0f}%)")
        s = dec.get("acao_secundaria", {})
        if s:
            print(f"  🟡 SECUNDÁRIA  : {s.get('descricao','')}  (+{s.get('impacto_pct',0):.0f}%)")
        f = dec.get("acao_futura", {})
        if f:
            print(f"  🔵 FUTURA      : {f.get('descricao','')}  (+{f.get('impacto_pct',0):.0f}%)")

    # Claude
    if ins.get("estrategia_agora"):
        print("\n  🧠  CLAUDE — ESTRATÉGIA")
        print(f"  Alavanca #1  : {ins.get('alavanca_maior_impacto','')}")
        print(f"  Por quê      : {ins.get('por_que','')}")
        print(f"  Mais fácil   : {ins.get('mais_facil_executar','')}")
        print(f"  Agora        : {ins.get('estrategia_agora','')}")
        if ins.get("alerta"):
            print(f"  ⚠️  Alerta    : {ins.get('alerta','')}")
        plano = ins.get("plano_acao", [])
        if plano:
            print("\n  📅  PLANO 4 SEMANAS:")
            for w in plano:
                print(f"  Sem {w.get('semana','')}: {w.get('acao','')} → {w.get('meta','')}")

    print("\n" + "═" * 64 + "\n")


def show_history():
    sims = _load_all()
    if not sims:
        print("  Nenhuma simulação salva ainda.")
        return
    print(f"\n  HISTÓRICO DE SIMULAÇÕES ({len(sims)})\n")
    print(
        f"  {'#':<3} {'Data':<17} {'Leads':>6} {'Conv':>6} {'Ticket':>8} {'Receita/mês':>14} {'Lucro/mês':>12} {'Margem':>8}"
    )
    print("  " + "─" * 80)
    for i, s in enumerate(reversed(sims[-10:]), 1):
        base = s.get("scenarios", {}).get("base", {})
        inp = s.get("input", {})
        ts = s.get("timestamp", "")[:15]
        mg = base.get("margin_pct", 0)
        ic = "🟢" if mg >= 70 else "🟡" if mg >= 40 else "🔴"
        print(
            f"  {i:<3} {ts:<17} "
            f"{inp.get('leads',0):>6.0f} "
            f"{inp.get('conversion',0)*100:>5.1f}% "
            f"R${inp.get('ticket',0):>6.0f} "
            f"R${base.get('revenue_month',0):>11,.0f} "
            f"R${base.get('profit',0):>9,.0f} "
            f"{ic}{mg:>6.1f}%"
        )
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse():
    p = argparse.ArgumentParser(description="Growth Simulator")
    p.add_argument("--leads", type=float, default=None, help="Leads por dia")
    p.add_argument("--conversion", type=float, default=None, help="Taxa de conversão (0.10 = 10%%)")
    p.add_argument("--ticket", type=float, default=None, help="Ticket médio em R$")
    p.add_argument("--cost", type=float, default=None, help="Custo mensal em R$")
    p.add_argument("--ads", action="store_true", help="Simular impacto de ads")
    p.add_argument("--investment", type=float, default=2000, help="Investimento em ads (R$)")
    p.add_argument("--cpl", type=float, default=8, help="Custo por lead (R$)")
    p.add_argument("--breakeven", action="store_true", help="Calcular break-even")
    p.add_argument("--history", action="store_true", help="Ver histórico")
    p.add_argument("--no-claude", action="store_true", help="Pular análise Claude")
    return p.parse_args()


async def main_async():
    args = _parse()

    if args.history:
        show_history()
        return

    # carregar defaults da última simulação ou do financial_engine
    fin_file = os.path.join(OUTPUTS_DIR, "financial_data.json")
    defaults = {"leads": 30, "conversion": 0.10, "ticket": 197, "cost": 5000}
    if os.path.exists(fin_file):
        try:
            with open(fin_file, encoding="utf-8") as f:
                fin = json.load(f)
            projs = fin.get("projections", [])
            if projs:
                last = projs[-1]
                defaults["leads"] = last.get("leads", defaults["leads"])
                defaults["conversion"] = last.get("conversion_rate", defaults["conversion"])
                defaults["ticket"] = last.get("ticket", defaults["ticket"])
                defaults["cost"] = last.get("monthly_cost", defaults["cost"])
        except Exception:
            pass

    leads = args.leads if args.leads is not None else defaults["leads"]
    conversion = args.conversion if args.conversion is not None else defaults["conversion"]
    ticket = args.ticket if args.ticket is not None else defaults["ticket"]
    cost = args.cost if args.cost is not None else defaults["cost"]

    if args.breakeven:
        bev = calc_breakeven(conversion, ticket, cost)
        print("\n  📍 BREAK-EVEN")
        print(f"  Conversão    : {conversion*100:.1f}%")
        print(f"  Ticket       : R${ticket:,.2f}")
        print(f"  Custo mensal : R${cost:,.2f}")
        print("  ──────────────────────────────────")
        print(f"  Leads/dia necessários : {bev['breakeven_leads_dia']}")
        print(f"  Leads/mês necessários : {bev['breakeven_leads_mes']}\n")
        return

    if args.ads:
        bev = calc_breakeven(conversion, ticket, cost)
        ads = calc_ads_impact(args.investment, args.cpl, conversion, ticket, cost)
        print("\n  📣  SIMULAÇÃO DE ADS")
        print(f"  Investimento    : R${ads['investment']:,.2f}")
        print(f"  CPL             : R${ads['cpl']:,.2f}")
        print(f"  Leads extras    : {ads['extra_leads']:.0f}")
        print(f"  Receita extra   : R${ads['extra_revenue']:,.2f}")
        print(f"  Lucro extra     : R${ads['extra_profit']:,.2f}")
        print(f"  ROAS            : {ads['roas']:.2f}x")
        print(f"  Viável?         : {'✅ SIM' if ads['viable'] else '❌ NÃO (ROAS < 2x)'}\n")
        return

    print(
        f"\n  Simulando: {leads} leads/dia · {conversion*100:.1f}% conversão · R${ticket:,.2f} ticket · R${cost:,.2f} custo/mês"
    )
    if not args.no_claude and ANTHROPIC_KEY:
        print("  Gerando insights com Claude...")

    r = await run_simulation(leads, conversion, ticket, cost, with_claude=not args.no_claude)
    show_result(r)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
