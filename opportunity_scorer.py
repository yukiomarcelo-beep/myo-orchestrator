#!/usr/bin/env python3
"""
Opportunity Scorer — Pipeline AI
Motor de avaliação de oportunidades de negócio.

Uso:
    python opportunity_scorer.py "CFO Digital para restaurantes"
    python opportunity_scorer.py --json '{"idea_title": "...", "idea_description": "...", ...}'
    python opportunity_scorer.py  # modo interativo
"""
import asyncio
import json
import os
import sys
import time
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-6"

WEIGHTS = {
    "dor_do_mercado":        20,
    "urgencia":              15,
    "monetizacao":           15,
    "escalabilidade":        15,
    "aquisicao":             10,
    "diferenciacao":         10,
    "execucao":              10,
    "potencial_de_conteudo":  5,
}

PROMPT_TEMPLATE = """Você é um avaliador especialista em oportunidades de negócio digital.

Avalie a seguinte oportunidade com rigor e objetividade:

Título: {idea_title}
Descrição: {idea_description}
Público-alvo: {target_audience}
Contexto de mercado: {market_context}

Dê notas de 1 a 5 para cada critério (1=péssimo, 3=mediano, 5=excelente):
- dor_do_mercado: A dor é real, frequente e custosa?
- urgencia: As pessoas querem resolver isso agora?
- monetizacao: Dá para cobrar bem, com margens saudáveis?
- escalabilidade: Dá para vender em volume sem custo proporcional?
- aquisicao: É fácil encontrar esse público via conteúdo, ads ou prospecção?
- diferenciacao: Dá para entrar com algo diferente e não virar commodity?
- execucao: Dá para lançar com stack Python/API/Claude atual?
- potencial_de_conteudo: Essa oportunidade gera ganchos e autoridade orgânica?

Também forneça:
- justificativa (1 frase) para cada critério
- main_risks: lista de 2 a 3 riscos reais e objetivos (strings curtas)
- recommendation: exatamente "descartar", "testar" ou "priorizar"
- initial_format: "serviço", "produto digital", "consultoria", "assinatura", "conteúdo + oferta" ou outro
- next_step: UMA ação concreta e específica para dar agora (string única, não lista)

Responda APENAS em JSON válido, sem markdown:

{{
  "scores": {{
    "dor_do_mercado":        {{"score": 0, "justificativa": ""}},
    "urgencia":              {{"score": 0, "justificativa": ""}},
    "monetizacao":           {{"score": 0, "justificativa": ""}},
    "escalabilidade":        {{"score": 0, "justificativa": ""}},
    "aquisicao":             {{"score": 0, "justificativa": ""}},
    "diferenciacao":         {{"score": 0, "justificativa": ""}},
    "execucao":              {{"score": 0, "justificativa": ""}},
    "potencial_de_conteudo": {{"score": 0, "justificativa": ""}}
  }},
  "main_risks": [],
  "recommendation": "",
  "initial_format": "",
  "next_step": ""
}}"""


# ─── Chamada Claude ────────────────────────────────────────────────────────────

async def avaliar_com_claude(opportunity: dict) -> dict:
    if not ANTHROPIC_API_KEY or "sua-chave" in ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY não configurada no .env")

    prompt = PROMPT_TEMPLATE.format(
        idea_title       = opportunity.get("idea_title", ""),
        idea_description = opportunity.get("idea_description", ""),
        target_audience  = opportunity.get("target_audience", ""),
        market_context   = opportunity.get("market_context", ""),
    )

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1600,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    t0 = time.time()
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post("https://api.anthropic.com/v1/messages",
                                 json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    raw_text = data.get("content", [{}])[0].get("text", "")
    latency  = int((time.time() - t0) * 1000)
    usage    = data.get("usage", {})
    cost     = round((usage.get("input_tokens", 0) * 3e-6) +
                     (usage.get("output_tokens", 0) * 15e-6), 6)

    # extrair JSON mesmo se vier com texto extra
    try:
        scoring = json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end   = raw_text.rfind("}") + 1
        if start != -1 and end > start:
            scoring = json.loads(raw_text[start:end])
        else:
            raise ValueError(f"Claude não retornou JSON válido:\n{raw_text[:400]}")

    return {"scoring": scoring, "latency_ms": latency, "estimated_cost": cost,
            "tokens_input": usage.get("input_tokens", 0),
            "tokens_output": usage.get("output_tokens", 0)}


# ─── Cálculo do score final ────────────────────────────────────────────────────

def calcular_score(scoring: dict) -> dict:
    scores = scoring.get("scores", {})
    weighted_total = 0.0

    for key, weight in WEIGHTS.items():
        note = scores.get(key, {}).get("score", 0)
        weighted_total += (note / 5) * weight

    final = round(weighted_total)

    if final >= 85:
        priority = "maxima"
    elif final >= 70:
        priority = "alta"
    elif final >= 55:
        priority = "media"
    else:
        priority = "baixa"

    return {"final_score": final, "priority": priority}


# ─── Salvar resultado local ────────────────────────────────────────────────────

def salvar_local(opportunity: dict, output: dict, raw_scoring: dict) -> str:
    os.makedirs("outputs", exist_ok=True)
    ts    = time.strftime("%Y%m%d_%H%M%S")
    title = opportunity.get("idea_title", "oportunidade").replace(" ", "_")[:30]
    fname = f"outputs/scoring_{title}_{ts}.json"

    with open(fname, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp":   ts,
            "output":      output,
            "opportunity": opportunity,
            "raw_scoring": raw_scoring,
        }, f, ensure_ascii=False, indent=2)
    return fname


# ─── Display no terminal ──────────────────────────────────────────────────────

PRIORITY_LABELS = {
    "maxima": "PRIORIDADE MÁXIMA  ★★★★★",
    "alta":   "Vale testar rápido  ★★★★☆",
    "media":  "Testar com cautela  ★★★☆☆",
    "baixa":  "Descartar por agora ★☆☆☆☆",
}

def imprimir_resultado(opportunity: dict, result: dict):
    out    = result["output"]
    raw    = result["raw_scoring"]
    scores = raw.get("scores", {})
    label  = PRIORITY_LABELS.get(out["priority"], out["priority"])

    print("\n" + "═" * 62)
    print(f"  OPPORTUNITY SCORE — {out['idea_title'][:40]}")
    print("═" * 62)

    print(f"\n  Score Final  : {out['final_score']}/100")
    print(f"  Prioridade   : {label}")
    print(f"  Recomendação : {out['recommendation'].upper()}")
    print(f"  Formato      : {out['initial_format']}")

    print("\n  ─── Critérios " + "─" * 46)
    for key, weight in WEIGHTS.items():
        info  = scores.get(key, {})
        nota  = info.get("score", 0)
        just  = info.get("justificativa", "")
        bar   = "█" * nota + "░" * (5 - nota)
        print(f"  {key.replace('_',' ').capitalize():<28} [{bar}] {nota}/5  (peso {weight})")
        if just:
            print(f"    → {just}")

    if out["main_risks"]:
        print("\n  ─── Riscos " + "─" * 49)
        for r in out["main_risks"]:
            print(f"  ⚠  {r}")

    print("\n  ─── Próximo passo " + "─" * 42)
    print(f"  → {out['next_step']}")

    print(f"\n  Custo : ~${result.get('estimated_cost', 0):.4f}  |  Latência: {result.get('latency_ms', 0)}ms")
    print("═" * 62)

    print("\n  Output JSON:")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print()


# ─── Fluxo principal ──────────────────────────────────────────────────────────

async def score_opportunity(opportunity: dict) -> dict:
    """
    Avalia uma oportunidade e retorna o output limpo + metadados internos.

    result["output"] — JSON final pronto para uso no fluxo:
        idea_title, final_score, priority, recommendation,
        initial_format, main_risks, next_step

    result["raw_scoring"] — detalhamento completo por critério (interno)
    """
    print(f"\n  Avaliando: {opportunity.get('idea_title', '')[:60]}")
    print("  Chamando Claude Opportunity Scorer...")

    claude_result = await avaliar_com_claude(opportunity)
    raw           = claude_result["scoring"]
    calc          = calcular_score(raw)

    # output limpo — o que sai do módulo para o fluxo
    output = {
        "idea_title":     opportunity.get("idea_title", ""),
        "final_score":    calc["final_score"],
        "priority":       calc["priority"],
        "recommendation": raw.get("recommendation", "descartar"),
        "initial_format": raw.get("initial_format", ""),
        "main_risks":     raw.get("main_risks", []),
        "next_step":      raw.get("next_step", ""),
    }

    result = {
        "output":           output,
        "raw_scoring":      raw,
        "latency_ms":       claude_result["latency_ms"],
        "estimated_cost":   claude_result["estimated_cost"],
        "tokens_input":     claude_result["tokens_input"],
        "tokens_output":    claude_result["tokens_output"],
    }

    fname = salvar_local(opportunity, output, raw)
    print(f"  Salvo em: {fname}")

    # Notion (se configurado)
    try:
        from notion_logger import salvar_tarefa
        await salvar_tarefa(
            f"Scoring: {output['idea_title'][:60]}",
            "scoring",
            json.dumps(result, ensure_ascii=False, indent=2),
        )
    except Exception:
        pass

    # Atualizar dashboard automaticamente
    _atualizar_dashboard()

    return result


def _atualizar_dashboard():
    import subprocess, sys
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generate_dashboard.py")
    if not os.path.exists(script):
        return
    try:
        subprocess.run([sys.executable, script], check=True, capture_output=True)
        dashboard = os.path.join(os.path.dirname(script), "dashboard.html")
        subprocess.Popen(["open", dashboard])
        print("  Dashboard atualizado e aberto.")
    except Exception as e:
        print(f"  Dashboard: {e}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def construir_opportunity_interativo() -> dict:
    print("\n  ─── Opportunity Scorer — Entrada Manual ───────────────")
    idea_title       = input("  Título da oportunidade: ").strip()
    idea_description = input("  Descrição (o que é, como funciona): ").strip()
    target_audience  = input("  Público-alvo: ").strip()
    market_context   = input("  Contexto de mercado (dores, pressões, sinais): ").strip()
    return {
        "idea_title":       idea_title,
        "idea_description": idea_description,
        "target_audience":  target_audience,
        "market_context":   market_context,
    }


async def main():
    args = sys.argv[1:]

    if "--json" in args:
        idx = args.index("--json")
        raw = args[idx + 1] if idx + 1 < len(args) else "{}"
        opportunity = json.loads(raw)

    elif args:
        # título rápido via CLI
        idea_title = " ".join(args)
        print(f"\n  Título recebido: {idea_title}")
        print("  Complete as informações para uma avaliação precisa:")
        idea_description = input("  Descrição: ").strip() or idea_title
        target_audience  = input("  Público-alvo: ").strip() or "a definir"
        market_context   = input("  Contexto de mercado: ").strip() or "a definir"
        opportunity = {
            "idea_title":       idea_title,
            "idea_description": idea_description,
            "target_audience":  target_audience,
            "market_context":   market_context,
        }

    else:
        opportunity = construir_opportunity_interativo()

    if not opportunity.get("idea_title"):
        print("  Título obrigatório. Saindo.")
        return

    result = await score_opportunity(opportunity)
    imprimir_resultado(opportunity, result)


if __name__ == "__main__":
    asyncio.run(main())
