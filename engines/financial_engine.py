#!/usr/bin/env python3
"""
Financial Engine — Custo, Margem, Projeção e Decisão
Uso: python financial_engine.py [opções]

Exemplos:
  python financial_engine.py --product '{"idea_title":"CFO Digital","creation_cost":50,"acquisition_cost":200,"operational_cost":30,"selling_price":497}'
  python financial_engine.py --monthly-costs '[{"category":"IA","description":"Claude+OpenAI","cost":1200}]'
  python financial_engine.py --projection --leads 30 --conversion 0.10 --ticket 497
  python financial_engine.py --goal 50000
  python financial_engine.py --analyze
  python financial_engine.py --dashboard
  python financial_engine.py --ranking
"""
import asyncio, json, os, sys, time, argparse, uuid
import httpx
from dotenv import load_dotenv
from observability import tracker, tracer

load_dotenv()
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
OUTPUTS_DIR    = "outputs"
FINANCIAL_FILE = os.path.join(OUTPUTS_DIR, "financial_data.json")

os.makedirs(OUTPUTS_DIR, exist_ok=True)

# ── persistência ──────────────────────────────────────────────────────────────

def _load() -> dict:
    if os.path.exists(FINANCIAL_FILE):
        try:
            with open(FINANCIAL_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "product_financials": [],
        "monthly_costs":      [],
        "projections":        [],
        "goal":               {"meta": 0, "atual": 0},
        "last_analysis":      {},
        "updated_at":         "",
    }


def _save(data: dict):
    data["updated_at"] = time.strftime("%Y%m%d_%H%M%S")
    with open(FINANCIAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── helpers ───────────────────────────────────────────────────────────────────

def _monthly_total(data: dict) -> float:
    return sum(c.get("cost", 0) for c in data.get("monthly_costs", []))


def _by_category(data: dict) -> dict:
    cats: dict = {}
    for c in data.get("monthly_costs", []):
        cat = c.get("category", "Outros")
        cats[cat] = cats.get(cat, 0) + c.get("cost", 0)
    return dict(sorted(cats.items(), key=lambda x: -x[1]))


def _latest_proj(data: dict) -> dict:
    projs = data.get("projections", [])
    return projs[-1] if projs else {}


# ── Claude ────────────────────────────────────────────────────────────────────

async def _claude(prompt: str) -> str:
    if not ANTHROPIC_KEY:
        return ""
    model_name = "claude-sonnet-4-6"
    with tracker.track(
        agent="financial_engine",
        model=model_name,
        action="calculate_margins",
        engine_name="financial_engine",
        confidence="observed",
        run_type="internal_ops",
        tenant_mode="internal_portfolio",
    ) as t:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      model_name,
                    "max_tokens": 1500,
                    "messages":   [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            resp = r.json()
            t.set_tokens(
                input=resp.get("usage", {}).get("input_tokens", 0),
                output=resp.get("usage", {}).get("output_tokens", 0),
            )
            return resp["content"][0]["text"]


# ── funções principais ────────────────────────────────────────────────────────

def add_product_cost(raw: dict) -> dict:
    """Node Calculate_Product_Cost — total_cost, profit, margin."""
    run_id = uuid.uuid4().hex[:8]

    try:
        creation    = float(raw.get("creation_cost",    0) or 0)
        acquisition = float(raw.get("acquisition_cost", 0) or 0)
        operational = float(raw.get("operational_cost", 0) or 0)
        price       = float(raw.get("selling_price",    0) or 0)
    except (TypeError, ValueError):
        tracer.step(run_id, agent="financial_engine",
                    action="calculate_margins",
                    status="error",
                    error_silent=True,
                    error_message="input inválido ou histórico ausente")
        raise

    total_cost = creation + acquisition + operational
    profit     = price - total_cost

    if price > 0:
        margin = round(profit / price, 4)
    else:
        tracer.step(run_id, agent="financial_engine",
                    action="calculate_margins",
                    status="error",
                    error_silent=True,
                    error_message="input inválido ou histórico ausente")
        margin = 0.0

    record = {
        "idea_title":        raw.get("idea_title", "Produto"),
        "creation_cost":     round(creation, 2),
        "acquisition_cost":  round(acquisition, 2),
        "operational_cost":  round(operational, 2),
        "total_cost":        round(total_cost, 2),
        "selling_price":     round(price, 2),
        "profit":            round(profit, 2),
        "margin":            margin,
        "margin_pct":        round(margin * 100, 1),
        "timestamp":         time.strftime("%Y%m%d_%H%M%S"),
    }

    data = _load()
    idx = next((i for i, p in enumerate(data["product_financials"])
                if p.get("idea_title") == record["idea_title"]), None)
    if idx is not None:
        data["product_financials"][idx] = record
    else:
        data["product_financials"].append(record)
    _save(data)

    tracer.step(run_id, agent="financial_engine",
                action="calculate_margins",
                input_summary=str(raw)[:100],
                status="success")
    return record


def set_monthly_costs(costs: list) -> dict:
    """Substitui lista de custos mensais [{category, description, cost}]."""
    validated = [
        {
            "category":    c.get("category", "Outros"),
            "description": c.get("description", ""),
            "cost":        float(c.get("cost", 0)),
        }
        for c in costs
    ]
    data = _load()
    data["monthly_costs"] = validated
    _save(data)
    total = sum(c["cost"] for c in validated)
    return {"total_monthly_cost": round(total, 2), "n_items": len(validated), "items": validated}


def run_projection(leads: int, conversion: float, ticket: float) -> dict:
    """Node Financial_Projection — Receita = Leads × Conversão × Ticket."""
    data         = _load()
    monthly_cost = _monthly_total(data)

    daily_revenue   = leads * conversion * ticket
    monthly_revenue = daily_revenue * 30
    monthly_profit  = monthly_revenue - monthly_cost
    margin          = round(monthly_profit / monthly_revenue, 4) if monthly_revenue > 0 else 0.0

    record = {
        "leads":              leads,
        "conversion_rate":    conversion,
        "ticket":             round(ticket, 2),
        "daily_revenue":      round(daily_revenue, 2),
        "monthly_revenue":    round(monthly_revenue, 2),
        "monthly_cost":       round(monthly_cost, 2),
        "monthly_profit":     round(monthly_profit, 2),
        "monthly_margin":     margin,
        "monthly_margin_pct": round(margin * 100, 1),
        "projected_revenue":  round(monthly_revenue, 2),
        "projected_profit":   round(monthly_profit, 2),
        "timestamp":          time.strftime("%Y%m%d_%H%M%S"),
    }

    data["projections"].append(record)
    # atualiza "atual" na meta
    data["goal"]["atual"] = round(monthly_revenue, 2)
    _save(data)
    return record


def set_goal(meta: float) -> dict:
    data = _load()
    projs = data.get("projections", [])
    atual = projs[-1].get("monthly_revenue", 0) if projs else 0
    data["goal"] = {"meta": round(meta, 2), "atual": round(atual, 2)}
    _save(data)
    return data["goal"]


# ── decisões automáticas (regras) ─────────────────────────────────────────────

def _auto_decisions(monthly_revenue: float, monthly_cost: float,
                    monthly_profit: float, monthly_margin: float) -> list:
    decisions = []

    if monthly_revenue == 0:
        decisions.append({
            "trigger":  "receita_zero",
            "action":   "Aumentar conteúdo orgânico e ativar tráfego pago imediatamente",
            "priority": "maxima",
        })
        return decisions

    cost_pct = monthly_cost / monthly_revenue if monthly_revenue > 0 else 0

    if monthly_margin < 0.30:
        decisions.append({
            "trigger":  "margem_baixa",
            "action":   "Aumentar preço do produto principal ou reduzir custo operacional",
            "priority": "alta",
        })
    if cost_pct > 0.50:
        decisions.append({
            "trigger":  "custo_alto",
            "action":   "Cortar ferramentas não essenciais e otimizar prompts para reduzir tokens",
            "priority": "alta",
        })
    if monthly_margin < 0.0:
        decisions.append({
            "trigger":  "prejuizo",
            "action":   "PARAR ADS imediatamente — renegociar custos fixos antes de escalar",
            "priority": "maxima",
        })
    if monthly_margin >= 0.70 and monthly_revenue > 0:
        decisions.append({
            "trigger":  "lucro_alto",
            "action":   "ESCALAR — duplicar budget de ads e lançar segundo produto",
            "priority": "escala",
        })
    if 0.30 <= monthly_margin < 0.50:
        decisions.append({
            "trigger":  "margem_media",
            "action":   "Testar aumento de 20% no ticket e medir impacto na conversão",
            "priority": "media",
        })
    if 0.50 <= monthly_margin < 0.70:
        decisions.append({
            "trigger":  "margem_boa",
            "action":   "Aumentar tráfego pago — margem sustenta escala",
            "priority": "media",
        })
    if not decisions:
        decisions.append({
            "trigger":  "estavel",
            "action":   "Sistema estável — monitorar conversão e testar upsell",
            "priority": "media",
        })
    return decisions


# ── análise Claude ─────────────────────────────────────────────────────────────

async def run_analysis() -> dict:
    data         = _load()
    products     = data.get("product_financials", [])
    projs        = data.get("projections", [])
    goal         = data.get("goal", {})
    monthly_cost = _monthly_total(data)
    by_cat       = _by_category(data)
    latest       = _latest_proj(data)

    monthly_revenue = latest.get("monthly_revenue", 0)
    monthly_profit  = latest.get("monthly_profit", 0)
    monthly_margin  = latest.get("monthly_margin", 0)

    decisions = _auto_decisions(monthly_revenue, monthly_cost, monthly_profit, monthly_margin)

    claude_analysis: dict = {}
    if ANTHROPIC_KEY:
        meta = goal.get("meta", 0)
        faltam = max(0, meta - monthly_revenue)
        prompt = f"""Você é um CFO digital especializado em infoprodutos e negócios online de alto crescimento.

SITUAÇÃO FINANCEIRA ATUAL:
- Receita mensal   : R${monthly_revenue:,.2f}
- Custo mensal     : R${monthly_cost:,.2f}
- Lucro mensal     : R${monthly_profit:,.2f}
- Margem           : {monthly_margin*100:.1f}%
- Meta mensal      : R${meta:,.2f}
- Faltam para meta : R${faltam:,.2f}

CUSTOS POR CATEGORIA:
{json.dumps(by_cat, ensure_ascii=False, indent=2)}

PRODUTOS CADASTRADOS ({len(products)}):
{json.dumps([{"titulo": p.get("idea_title",""), "margem": f"{p.get('margin_pct',0)}%", "preco": p.get("selling_price",0), "custo_total": p.get("total_cost",0)} for p in products[:6]], ensure_ascii=False, indent=2)}

ÚLTIMA PROJEÇÃO:
{json.dumps({"leads_dia": latest.get("leads",0), "conversao": f"{latest.get('conversion_rate',0)*100:.1f}%", "ticket": latest.get("ticket",0)}, ensure_ascii=False)}

Retorne SOMENTE JSON válido (sem markdown):
{{
  "diagnostico": "diagnóstico da saúde financeira em 2 frases diretas",
  "ponto_critico": "o maior problema financeiro neste momento",
  "alavanca_principal": "a ação com maior impacto imediato no lucro",
  "plano_90_dias": [
    {{"mes": 1, "foco": "...", "meta_receita": 0, "acoes": ["...", "..."]}},
    {{"mes": 2, "foco": "...", "meta_receita": 0, "acoes": ["...", "..."]}},
    {{"mes": 3, "foco": "...", "meta_receita": 0, "acoes": ["...", "..."]}}
  ],
  "cortes_recomendados": ["item a cortar 1", "item a cortar 2"],
  "aumentos_recomendados": ["onde investir mais 1", "onde investir mais 2"],
  "projecao_otimista_mensal": 0,
  "projecao_conservadora_mensal": 0,
  "breakeven_leads_dia": 0
}}"""
        try:
            raw = await _claude(prompt)
            s = raw.find("{")
            e = raw.rfind("}") + 1
            if s >= 0 and e > s:
                claude_analysis = json.loads(raw[s:e])
        except Exception as ex:
            claude_analysis = {"diagnostico": f"Erro na análise: {ex}"}

    result = {
        "monthly_revenue":  monthly_revenue,
        "monthly_cost":     monthly_cost,
        "monthly_profit":   monthly_profit,
        "monthly_margin":   monthly_margin,
        "by_category":      by_cat,
        "decisions":        decisions,
        "goal":             goal,
        "claude_analysis":  claude_analysis,
        "timestamp":        time.strftime("%Y%m%d_%H%M%S"),
    }

    data["last_analysis"] = result
    _save(data)
    return result


# ── display terminal ──────────────────────────────────────────────────────────

def show_dashboard():
    data         = _load()
    products     = data.get("product_financials", [])
    goal         = data.get("goal", {})
    monthly_cost = _monthly_total(data)
    by_cat       = _by_category(data)
    latest       = _latest_proj(data)
    analysis     = data.get("last_analysis", {})

    monthly_revenue = latest.get("monthly_revenue", 0)
    monthly_profit  = latest.get("monthly_profit", 0)
    monthly_margin  = latest.get("monthly_margin_pct", 0)
    daily_revenue   = latest.get("daily_revenue", 0)
    meta            = goal.get("meta", 0)
    faltam          = max(0, meta - monthly_revenue)

    print("\n" + "═" * 62)
    print("  💰  FINANCIAL ENGINE — CENTRAL FINANCEIRA")
    print("═" * 62)

    # receita
    print(f"\n  📈  RECEITA")
    print(f"  Receita / dia   : R${daily_revenue:>10,.2f}")
    print(f"  Receita / mês   : R${monthly_revenue:>10,.2f}")

    # custos
    print(f"\n  🧾  CUSTOS MENSAIS — R${monthly_cost:,.2f}")
    for cat, val in by_cat.items():
        pct = round(val / monthly_cost * 100) if monthly_cost > 0 else 0
        bar = "▓" * (pct // 5)
        print(f"  {cat:<20}: R${val:>8,.2f}  {bar} {pct}%")

    # margem
    mg_icon = "🟢" if monthly_margin >= 70 else "🟡" if monthly_margin >= 40 else "🔴"
    print(f"\n  📊  MARGEM {mg_icon}")
    print(f"  Lucro / mês     : R${monthly_profit:>10,.2f}")
    print(f"  Margem          : {monthly_margin:.1f}%")

    # meta
    if meta > 0:
        pct = min(100, round(monthly_revenue / meta * 100))
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"\n  🎯  META vs REAL")
        print(f"  Meta            : R${meta:>10,.2f}")
        print(f"  Atual           : R${monthly_revenue:>10,.2f}")
        print(f"  [{bar}] {pct}%")
        if faltam > 0:
            print(f"  Faltam          : R${faltam:>10,.2f}")

    # projeção
    if latest:
        print(f"\n  🔮  PROJEÇÃO BASE")
        print(f"  Leads / dia     : {latest.get('leads', 0)}")
        print(f"  Conversão       : {latest.get('conversion_rate', 0)*100:.1f}%")
        print(f"  Ticket médio    : R${latest.get('ticket', 0):,.2f}")

        ca = analysis.get("claude_analysis", {})
        if ca.get("projecao_otimista_mensal"):
            print(f"  Projeção otimis.: R${ca['projecao_otimista_mensal']:>10,.2f}")
        if ca.get("projecao_conservadora_mensal"):
            print(f"  Projeção consrv.: R${ca['projecao_conservadora_mensal']:>10,.2f}")

    # produtos
    if products:
        print(f"\n  🏗️   PRODUTOS — ranking por margem")
        for p in sorted(products, key=lambda x: -x.get("margin_pct", 0)):
            mg = p.get("margin_pct", 0)
            ic = "🟢" if mg >= 70 else "🟡" if mg >= 40 else "🔴"
            print(f"  {ic} {p.get('idea_title',''):<30}  margem {mg:5.1f}%  "
                  f"preço R${p.get('selling_price', 0):>6.0f}  "
                  f"custo R${p.get('total_cost', 0):>6.0f}")

    # claude
    ca = analysis.get("claude_analysis", {})
    if ca.get("diagnostico"):
        print(f"\n  🧠  ANÁLISE CLAUDE")
        print(f"  {ca['diagnostico']}")
    if ca.get("alavanca_principal"):
        print(f"  → Alavanca: {ca['alavanca_principal']}")
    if ca.get("ponto_critico"):
        print(f"  ⚠️  Crítico: {ca['ponto_critico']}")

    # decisões automáticas
    decisions = analysis.get("decisions", [])
    if not decisions:
        # gera live sem salvar
        decisions = _auto_decisions(monthly_revenue, monthly_cost, monthly_profit,
                                    latest.get("monthly_margin", 0))
    if decisions:
        ICON = {"maxima": "🚨", "alta": "⚠️ ", "escala": "🚀", "media": "ℹ️ "}
        print(f"\n  🤖  DECISÕES AUTOMÁTICAS")
        for d in decisions:
            print(f"  {ICON.get(d.get('priority','media'),'')} [{d.get('trigger','')}] {d.get('action','')}")

    print("\n" + "═" * 62 + "\n")


def show_ranking():
    data     = _load()
    products = sorted(data.get("product_financials", []), key=lambda x: -x.get("margin_pct", 0))
    if not products:
        print("  Nenhum produto. Use: --product '{...}'")
        return

    print(f"\n  RANKING DE PRODUTOS — por Margem\n")
    print(f"  {'#':<3} {'Produto':<30} {'Preço':>8} {'Custo':>8} {'Lucro':>8} {'Margem':>8}")
    print("  " + "─" * 68)
    for i, p in enumerate(products, 1):
        mg = p.get("margin_pct", 0)
        ic = "🟢" if mg >= 70 else "🟡" if mg >= 40 else "🔴"
        print(f"  {ic}{i:<2} {p.get('idea_title',''):<30} "
              f"R${p.get('selling_price', 0):>6.0f} "
              f"R${p.get('total_cost', 0):>6.0f} "
              f"R${p.get('profit', 0):>6.0f} "
              f"{mg:>7.1f}%")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse():
    p = argparse.ArgumentParser(description="Financial Engine")
    p.add_argument("--product",       type=str, help="JSON com custos do produto")
    p.add_argument("--monthly-costs", type=str, help="JSON array de custos mensais")
    p.add_argument("--projection",    action="store_true", help="Rodar projeção financeira")
    p.add_argument("--leads",         type=int,   default=30,   help="Leads/dia para projeção")
    p.add_argument("--conversion",    type=float, default=0.10, help="Taxa de conversão (0.10 = 10%%)")
    p.add_argument("--ticket",        type=float, default=197,  help="Ticket médio em R$")
    p.add_argument("--goal",          type=float, help="Define meta mensal em R$")
    p.add_argument("--analyze",       action="store_true", help="Análise completa com Claude")
    p.add_argument("--dashboard",     action="store_true", help="Exibe dashboard no terminal")
    p.add_argument("--ranking",       action="store_true", help="Ranking de produtos por margem")
    return p.parse_args()


async def main_async():
    args = _parse()

    if args.product:
        raw = json.loads(args.product)
        r   = add_product_cost(raw)
        print(f"\n  ✅ Produto registrado: {r['idea_title']}")
        print(f"     Preço  : R${r['selling_price']:,.2f}")
        print(f"     Custo  : R${r['total_cost']:,.2f}")
        print(f"     Lucro  : R${r['profit']:,.2f}")
        print(f"     Margem : {r['margin_pct']:.1f}%\n")

    elif args.monthly_costs:
        costs = json.loads(args.monthly_costs)
        r = set_monthly_costs(costs)
        print(f"\n  ✅ Custos mensais atualizados: {r['n_items']} itens")
        print(f"     Total: R${r['total_monthly_cost']:,.2f}/mês\n")
        for item in r["items"]:
            print(f"     {item['category']:<20} R${item['cost']:,.2f}  — {item['description']}")
        print()

    elif args.projection:
        r = run_projection(args.leads, args.conversion, args.ticket)
        print(f"\n  📈 PROJEÇÃO FINANCEIRA")
        print(f"     Leads/dia     : {r['leads']}")
        print(f"     Conversão     : {r['conversion_rate']*100:.1f}%")
        print(f"     Ticket        : R${r['ticket']:,.2f}")
        print(f"     Receita/dia   : R${r['daily_revenue']:,.2f}")
        print(f"     Receita/mês   : R${r['monthly_revenue']:,.2f}")
        print(f"     Custo/mês     : R${r['monthly_cost']:,.2f}")
        print(f"     Lucro/mês     : R${r['monthly_profit']:,.2f}")
        print(f"     Margem        : {r['monthly_margin_pct']:.1f}%\n")

    elif args.goal:
        r = set_goal(args.goal)
        faltam = max(0, r["meta"] - r["atual"])
        print(f"\n  🎯 Meta definida: R${r['meta']:,.2f}")
        print(f"     Atual        : R${r['atual']:,.2f}")
        print(f"     Faltam       : R${faltam:,.2f}\n")

    elif args.analyze:
        print("\n  🔄 Analisando situação financeira com Claude...")
        r = await run_analysis()
        print(f"\n  ✅ ANÁLISE COMPLETA")
        print(f"     Receita/mês  : R${r['monthly_revenue']:,.2f}")
        print(f"     Lucro/mês    : R${r['monthly_profit']:,.2f}")
        print(f"     Margem       : {r['monthly_margin']*100:.1f}%")
        ca = r.get("claude_analysis", {})
        if ca.get("diagnostico"):
            print(f"\n  Diagnóstico    : {ca['diagnostico']}")
        if ca.get("alavanca_principal"):
            print(f"  Alavanca       : {ca['alavanca_principal']}")
        if ca.get("ponto_critico"):
            print(f"  Ponto crítico  : {ca['ponto_critico']}")
        plano = ca.get("plano_90_dias", [])
        if plano:
            print(f"\n  PLANO 90 DIAS:")
            for m in plano:
                print(f"  Mês {m.get('mes','')}: {m.get('foco','')} — meta R${m.get('meta_receita',0):,.0f}")
                for a in m.get("acoes", []):
                    print(f"    → {a}")
        print(f"\n  DECISÕES AUTOMÁTICAS:")
        ICON = {"maxima": "🚨", "alta": "⚠️ ", "escala": "🚀", "media": "ℹ️ "}
        for d in r.get("decisions", []):
            print(f"  {ICON.get(d.get('priority','media'),'')} [{d.get('trigger','')}] {d.get('action','')}")
        print()

    elif args.ranking:
        show_ranking()

    else:
        # default: dashboard
        show_dashboard()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
