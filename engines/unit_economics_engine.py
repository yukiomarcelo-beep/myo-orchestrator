#!/usr/bin/env python3
"""
Unit Economics Engine — Pipeline AI
Responde as 3 perguntas que definem se um produto pode escalar:
1. Quanto custa servir 1 usuário?
2. Quanto ele paga?
3. Qual a margem real?

Fluxo:
Input (produto + custos + receita)
→ Calculate Unit Economics (lógica) — profit, margin, status
→ Claude Analysis (Claude) — diagnóstico, riscos, ações
→ Decision Engine (lógica) — scale / acceptable / optimize / kill
→ Scale Projection (lógica) — projeção 100 / 500 / 1000 usuários
→ Action Generator (Claude) — plano para melhorar margem
→ Save (local) — persiste em unit_economics_*.json
→ Output (terminal + Notion + Dashboard)

Regras de margem:
≥ 70% → SCALE (ideal)
≥ 60% → ACCEPTABLE (saudável)
≥ 40% → OPTIMIZE (melhorar antes de escalar)
< 40% → KILL (não escala)

Uso:
python unit_economics_engine.py # modo interativo
python unit_economics_engine.py --json '{...}' # input manual
python unit_economics_engine.py --ranking # ranking de produtos
python unit_economics_engine.py --title "CFO Digital" # analisa produto específico
"""

import asyncio
import glob
import json
import os
import sys
import time
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"
OUTPUTS_DIR = "outputs"

# Thresholds de margem
MARGIN_SCALE = 0.70  # ≥ 70% → escalar
MARGIN_ACCEPTABLE = 0.60  # ≥ 60% → aceitável
MARGIN_OPTIMIZE = 0.40  # ≥ 40% → otimizar
# < 40% → kill


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
            "model": CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
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
                "cost": round(
                    (u.get("input_tokens", 0) * 3e-6) + (u.get("output_tokens", 0) * 15e-6), 6
                ),
            }


# Prompts


def _p_analysis(data: dict) -> str:
    margin_pct = data.get("margin", 0) * 100
    status = data.get("status", "kill")
    costs = data.get("cost_breakdown", {})

    cost_lines = ""
    if costs:
        for k, v in costs.items():
            cost_lines += f" - {k}: ${v:.2f}\n"

            return f"""Você é um CFO especialista em unit economics de produtos digitais.

Analise a viabilidade financeira deste produto:

Produto : {data.get('product_name', '')}
Preço/mês : ${data.get('revenue_per_user', 0):.2f}
Custo/usuário : ${data.get('cost_per_user', 0):.2f}
Lucro/usuário : ${data.get('profit_per_user', 0):.2f}
Margem : {margin_pct:.1f}%
Status : {status.upper()}

Breakdown de custos:
{cost_lines if cost_lines else " Não informado"}

Retorne análise completa em JSON:

{{
"diagnostic": "",
"main_risk": "",
"cost_killers": [],
"price_suggestion": 0,
"actions_to_improve_margin": [],
"scale_viability": "",
"next_step": ""
}}

- diagnostic: diagnóstico direto em 1-2 frases
- main_risk: principal risco se tentar escalar agora
- cost_killers: os 2-3 itens de custo que mais prejudicam a margem
- price_suggestion: preço sugerido para atingir margem ≥70% (0 se já ok)
- actions_to_improve_margin: 3-5 ações concretas para melhorar margem
- scale_viability: "sim" / "não" / "após ajustes"
- next_step: ação mais importante agora (1 frase)

Responda APENAS em JSON válido."""


def _p_action_plan(data: dict, analysis: dict) -> str:
    status = data.get("status", "kill")
    margin = data.get("margin", 0) * 100

    context = {
        "scale": "Margem excelente. Foque em escalar com eficiência.",
        "acceptable": "Margem ok. Pequenos ajustes antes de escalar.",
        "optimize": "Margem baixa. Otimize custos antes de qualquer escala.",
        "kill": "Margem inviável. Reestruture o produto ou descarte.",
    }.get(status, "")

    return f"""Produto : {data.get('product_name', '')}
Margem : {margin:.1f}% — {status.upper()}
Situação : {context}

Diagnóstico: {analysis.get('diagnostic', '')}
Custo/usuário: ${data.get('cost_per_user', 0):.2f}
Receita/usuário: ${data.get('revenue_per_user', 0):.2f}

Crie um plano de ação de 30 dias para melhorar os unit economics.

Responda APENAS em JSON válido:

{{
"plano_30_dias": [
{{"semana": "Semana 1", "acao": "", "impacto": "", "prioridade": "alta"}}
],
"reducao_custo_possivel": 0,
"aumento_preco_sugerido": 0,
"margem_alvo": 0,
"criterio_de_sucesso": ""
}}

- reducao_custo_possivel: estimativa de redução de custo em $ se ações forem executadas
- aumento_preco_sugerido: aumento de preço sugerido em $
- margem_alvo: margem % esperada após ajustes"""


# Lógica de cálculo


def _calculate(raw: dict) -> dict:
    """Node — Calculate Unit Economics."""
    cost = raw.get("cost_per_user", 0) or 0
    revenue = raw.get("revenue_per_user", 0) or 0

    profit = revenue - cost
    margin = (profit / revenue) if revenue > 0 else 0

    if margin >= MARGIN_SCALE:
        status = "scale"
    elif margin >= MARGIN_ACCEPTABLE:
        status = "acceptable"
    elif margin >= MARGIN_OPTIMIZE:
        status = "optimize"
    else:
        status = "kill"

        return {
            **raw,
            "profit_per_user": round(profit, 2),
            "margin": round(margin, 6),
            "status": status,
        }


def _scale_projection(data: dict) -> dict:
    """Projeta receita, custo e lucro para múltiplos de usuários."""
    cost = data.get("cost_per_user", 0)
    revenue = data.get("revenue_per_user", 0)
    profit = data.get("profit_per_user", 0)

    scenarios = {}
    for n in [100, 500, 1000, 5000]:
        scenarios[str(n)] = {
            "users": n,
            "revenue": round(revenue * n, 2),
            "cost": round(cost * n, 2),
            "profit": round(profit * n, 2),
        }
        return scenarios


# Auto-coleta de dados


def _collect_from_outputs(title_filter: Optional[str] = None) -> list[dict]:
    """Recarrega unit_economics existentes para ranking."""
    records = []
    for path in sorted(glob.glob(f"{OUTPUTS_DIR}/unit_economics_*.json"), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
                if title_filter and title_filter.lower() not in d.get("product_name", "").lower():
                    continue
                    records.append(d)
        except Exception:
            pass
            return records


# Fluxo principal


async def run_unit_economics(raw_input: dict) -> dict:
    name = raw_input.get("product_name", "?")
    print(f"\n Analisando Unit Economics: {name[:55]}")
    print(" " + "" * 56)

    # [1] Calculate
    print(" [1/5] Calculando unit economics...")
    data = _calculate(raw_input)
    margin_pct = data["margin"] * 100
    STATUS_ICON = {"scale": "", "acceptable": "", "optimize": "", "kill": ""}
    print(
        f" Margem {margin_pct:.1f}% → "
        f"{STATUS_ICON.get(data['status'],'')} {data['status'].upper()}"
    )
    print(
        f" Receita ${data['revenue_per_user']:.2f} | "
        f"Custo ${data['cost_per_user']:.2f} | "
        f"Lucro ${data['profit_per_user']:.2f} / usuário"
    )

    # [2] Scale Projection
    print(" [2/5] Calculando projeção de escala...")
    data["timestamp"] = time.strftime("%Y%m%d_%H%M%S")
    projection = _scale_projection(data)
    data["scale_projection"] = projection
    print(
        f" 1.000 usuários → ${projection['1000']['revenue']:,.0f} receita | "
        f"${projection['1000']['profit']:,.0f} lucro"
    )

    # [3] Claude Analysis
    print(" [3/5] Claude Unit Economics Analysis...")
    analysis_raw, m1 = await _claude(_p_analysis(data))
    analysis = analysis_raw if isinstance(analysis_raw, dict) else {}
    print(f" {m1['latency_ms']}ms · ${m1['cost']:.4f}")

    # [4] Action Plan
    print(" [4/5] Gerando plano de ação...")
    plan_raw, m2 = await _claude(_p_action_plan(data, analysis), max_tokens=1200)
    plan = plan_raw if isinstance(plan_raw, dict) else {}
    total_cost = m1["cost"] + m2["cost"]
    print(f" {len(plan.get('plano_30_dias', []))} ações planejadas · ${m2['cost']:.4f}")

    # [5] Save
    print(" [5/5] Salvando resultado...")
    result = {
        "product_name": name,
        "cost_per_user": data["cost_per_user"],
        "revenue_per_user": data["revenue_per_user"],
        "profit_per_user": data["profit_per_user"],
        "margin": data["margin"],
        "status": data["status"],
        "cost_breakdown": data.get("cost_breakdown", {}),
        "scale_projection": projection,
        "analysis": analysis,
        "action_plan": plan,
        "total_cost": total_cost,
        "timestamp": data["timestamp"],
        "response": {
            "status": "success",
            "product_name": name,
            "margin": round(margin_pct, 1),
            "unit_status": data["status"],
            "profit_per_user": data["profit_per_user"],
            "scale_viability": analysis.get("scale_viability", ""),
            "next_step": analysis.get("next_step", ""),
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
    records = _collect_from_outputs()
    if not records:
        print("\n Nenhuma análise de unit economics encontrada.")
        print(" Rode: python unit_economics_engine.py")
        return

        records.sort(key=lambda x: -x.get("margin", 0))

        STATUS_ICON = {"scale": "", "acceptable": "", "optimize": "", "kill": ""}

        print("\n" + "" * 70)
        print(" UNIT ECONOMICS — Ranking de Produtos")
        print("" * 70)
        print(f" {'#':<3} {'Margem':<9} {'Status':<13} {'Receita':<9} {'Custo':<9} Produto")
        print(" " + "" * 64)
        for i, r in enumerate(records, 1):
            status = r.get("status", "kill")
            margin = r.get("margin", 0) * 100
            icon = STATUS_ICON.get(status, "?")
            name = r.get("product_name", "?")[:30]
            print(
                f" {i:<3} {margin:>5.1f}% "
                f"{icon} {status:<11} "
                f"${r.get('revenue_per_user',0):<8.2f} "
                f"${r.get('cost_per_user',0):<8.2f} "
                f"{name}"
            )
            diag = r.get("analysis", {}).get("diagnostic", "")
            if diag:
                print(f" → {diag[:70]}")

                scale = sum(1 for r in records if r.get("status") == "scale")
                acceptable = sum(1 for r in records if r.get("status") == "acceptable")
                optimize = sum(1 for r in records if r.get("status") == "optimize")
                kill = sum(1 for r in records if r.get("status") == "kill")

                print("" * 70)
                print(
                    f"\n Scale: {scale} | Acceptable: {acceptable} | "
                    f" Optimize: {optimize} | Kill: {kill}\n"
                )


# Persistência


def _salvar_local(result: dict) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    slug = result["product_name"].replace(" ", "_")[:28]
    fname = f"{OUTPUTS_DIR}/unit_economics_{slug}_{result['timestamp']}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        return fname


async def _salvar_notion(result: dict):
    try:
        from integrations.notion_logger import salvar_tarefa

        a = result.get("analysis", {})
        p = result.get("action_plan", {})
        proj = result.get("scale_projection", {})
        margin_pct = result.get("margin", 0) * 100
        body = (
            f"Margem: {margin_pct:.1f}% → {result.get('status','').upper()}\n"
            f"Receita: ${result.get('revenue_per_user',0):.2f} | "
            f"Custo: ${result.get('cost_per_user',0):.2f} | "
            f"Lucro: ${result.get('profit_per_user',0):.2f} / usuário\n\n"
            f"Diagnóstico: {a.get('diagnostic','')}\n"
            f"Risco principal: {a.get('main_risk','')}\n\n"
            f"Projeção 1.000 usuários:\n"
            f" Receita: ${proj.get('1000',{}).get('revenue',0):,.0f}\n"
            f" Lucro: ${proj.get('1000',{}).get('profit',0):,.0f}\n\n"
            f"Próximo passo: {a.get('next_step','')}"
        )
        await salvar_tarefa(
            f"Unit Economics: {result['product_name'][:50]} → "
            f"{margin_pct:.0f}% ({result.get('status','').upper()})",
            "unit_economics_engine",
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
    a = result.get("analysis", {})
    p = result.get("action_plan", {})
    proj = result.get("scale_projection", {})
    status = result.get("status", "kill")
    margin = result.get("margin", 0) * 100

    STATUS_BLOCK = {
        "scale": " ESCALAR — Margem excelente",
        "acceptable": " ACEITÁVEL — Margem saudável",
        "optimize": " OTIMIZAR — Margem abaixo do ideal",
        "kill": " MATAR — Margem inviável para escala",
    }

    print("\n" + "" * 62)
    print(f" UNIT ECONOMICS — {result['product_name'][:40]}")
    print("" * 62)

    # Bloco financeiro
    print(f"\n {''*58}")
    print(f" {'Receita/usuário':<22}: ${result['revenue_per_user']:>8.2f}")
    print(f" {'Custo/usuário':<22}: ${result['cost_per_user']:>8.2f}")
    print(f" {'Lucro/usuário':<22}: ${result['profit_per_user']:>8.2f}")
    print(f" {'Margem':<22}: {margin:>7.1f}%")
    print(f" {''*58}")
    print(f" {STATUS_BLOCK.get(status, status.upper())}")
    print(f" {''*58}")

    # Cost breakdown
    breakdown = result.get("cost_breakdown", {})
    if breakdown:
        print("\n Breakdown de Custos ")
        for k, v in breakdown.items():
            print(f" • {k:<28}: ${v:.2f}")

            # Diagnóstico
            if a.get("diagnostic"):
                print(f"\n Diagnóstico: {a['diagnostic']}")
                if a.get("main_risk"):
                    print(f" Risco principal: {a['main_risk'][:100]}")

                    if a.get("cost_killers"):
                        print("\n Itens que mais pesam no custo ")
                        for c in a["cost_killers"]:
                            print(f" {c}")

                            if a.get("actions_to_improve_margin"):
                                print("\n Ações para melhorar margem ")
                                for ac in a["actions_to_improve_margin"]:
                                    print(f" → {ac}")

                                    if a.get("price_suggestion") and a["price_suggestion"] > 0:
                                        print(
                                            f"\n Preço sugerido para margem ≥70%: ${a['price_suggestion']:.2f}"
                                        )

                                        # Projeção de escala
                                        print("\n Projeção de Escala ")
                                        print(
                                            f" {'Usuários':<10} {'Receita':>12} {'Custo':>12} {'Lucro':>12}"
                                        )
                                        print(f" {''*50}")
                                        for n in ["100", "500", "1000", "5000"]:
                                            sc = proj.get(n, {})
                                            print(
                                                f" {n+'u':<10} ${sc.get('revenue',0):>11,.0f} ${sc.get('cost',0):>11,.0f} ${sc.get('profit',0):>11,.0f}"
                                            )

                                            # Plano 30 dias
                                            plano = p.get("plano_30_dias", [])
                                            if plano:
                                                print("\n Plano 30 dias ")
                                                for item in plano:
                                                    pri = item.get("prioridade", "")
                                                    pri_tag = (
                                                        ""
                                                        if pri == "alta"
                                                        else ("" if pri == "media" else "")
                                                    )
                                                    impacto = (
                                                        f" → {item.get('impacto','')[:40]}"
                                                        if item.get("impacto")
                                                        else ""
                                                    )
                                                    print(
                                                        f" {pri_tag} [{item.get('semana',''):<8}] {item.get('acao','')[:48]}{impacto}"
                                                    )

                                                    if p.get("criterio_de_sucesso"):
                                                        print(
                                                            f"\n Critério de sucesso: {p['criterio_de_sucesso'][:80]}"
                                                        )

                                                        if a.get("next_step"):
                                                            print(
                                                                f"\n Próximo passo: {a['next_step'][:100]}"
                                                            )

                                                            print(
                                                                f"\n Custo análise: ~${result.get('total_cost',0):.4f}"
                                                            )
                                                            print("" * 62 + "\n")

                                                            print(" Response (Node):")
                                                            print(
                                                                json.dumps(
                                                                    result["response"],
                                                                    ensure_ascii=False,
                                                                    indent=2,
                                                                )
                                                            )
                                                            print()


# Modo interativo


def _interactive_input() -> dict:
    print("\n" + "" * 62)
    print(" UNIT ECONOMICS — Input Interativo")
    print("" * 62)

    name = input(" Produto: ").strip() or "Produto"
    revenue = float(input(" Receita/usuário por mês ($): ").strip() or "0")

    print("\n Informe os custos por usuário:")
    print(" (Enter para 0 em cada item)")

    costs = {}
    items = [
        ("IA (Claude/GPT/Perplexity)", "ia"),
        ("Vídeo (HeyGen/ElevenLabs)", "video"),
        ("Infra (servidor/banco/n8n)", "infra"),
        ("Suporte/Atendimento", "suporte"),
        ("Outros", "outros"),
    ]
    for label, key in items:
        val = input(f" {label}: $").strip()
        if val:
            costs[label] = float(val)

            total_cost = sum(costs.values())
            print(f"\n Custo total/usuário: ${total_cost:.2f}")
            print(f" Receita/usuário: ${revenue:.2f}")
            margin = ((revenue - total_cost) / revenue * 100) if revenue > 0 else 0
            print(f" Margem estimada: {margin:.1f}%")

            return {
                "product_name": name,
                "revenue_per_user": revenue,
                "cost_per_user": total_cost,
                "cost_breakdown": costs,
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
            await run_unit_economics(raw)
            return

            if "--title" in args:
                idx = args.index("--title")
                title = args[idx + 1] if idx + 1 < len(args) else ""
                records = _collect_from_outputs(title_filter=title)
                if not records:
                    print(f"\n Nenhum dado encontrado para: {title}")
                    return
                    show_ranking()
                    return

                    # modo interativo
                    raw = _interactive_input()
                    await run_unit_economics(raw)


if __name__ == "__main__":
    asyncio.run(main())
