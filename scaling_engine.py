#!/usr/bin/env python3
"""
Scaling Engine — Pipeline AI
Escala o que funciona. Elimina o que não funciona. Fecha o loop.

Fluxo:
  Scaling Input
  → Collect Data        (auto/manual) — lê performance + validation + CRM ou recebe direto
  → Normalize Data      (lógica)      — recalcula conversion_rate real
  → Scaling Score       (lógica)      — 0-100 (scale ≥75 / optimize ≥50 / stop <50)
  → Claude Analysis     (Claude)      — insight, repeat, kill, scale_actions, next_steps
  → Decision Engine     (lógica)      — escalar / otimizar / stop
  → Action Generator    (Claude)      — plano de ação concreto
  → Save Decisions      (local)       — persiste em scaling_*.json
  → Output              (terminal + Notion + Dashboard)

Loop completo:
  descobrir → criar → distribuir → validar → vender → medir → escalar → repetir

Uso:
  python scaling_engine.py                        # auto-coleta de todos os dados existentes
  python scaling_engine.py --title "CFO Digital"  # foca em um produto específico
  python scaling_engine.py --json '{...}'         # input manual direto
  python scaling_engine.py --ranking              # ranking de decisões de escala
"""
import asyncio, json, os, sys, time, glob
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-6"
OUTPUTS_DIR       = "outputs"

SCALING_WEIGHTS = {
    "performance": 0.40,
    "validation":  0.40,
    "conversion":  20.0,   # multiplica a taxa (0-1) para pontuação proporcional
}


# ─── API helper ───────────────────────────────────────────────────────────────

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


# ─── Prompts ──────────────────────────────────────────────────────────────────

def _p_scaling_analysis(data: dict) -> str:
    return f"""Você é um especialista em crescimento de negócios digitais e escala.

Analise este ativo de negócio:

Produto: {data.get('idea_title', '')}

Dados consolidados:
- Performance score : {data.get('performance_score', 0)}/100
- Validation score  : {data.get('validation_score', 0)}/100
- Leads gerados     : {data.get('leads', 0)}
- Vendas fechadas   : {data.get('sales', 0)}
- Taxa de conversão : {data.get('conversion_rate', 0)*100:.1f}%
- Scaling score     : {data.get('scaling_score', 0)}/100 ({data.get('scaling_status', '')})

Contexto adicional:
{_format_context(data)}

Retorne uma análise estratégica completa em JSON:

{{
  "insight": "",
  "why_it_worked": "",
  "repeat": [],
  "kill": [],
  "scale_actions": [],
  "next_steps": ""
}}

- insight: diagnóstico direto em 1-2 frases
- why_it_worked: o que explica o resultado
- repeat: lista de padrões a replicar (ganchos, ângulos, CTAs, formatos)
- kill: lista do que eliminar imediatamente
- scale_actions: ações concretas para escalar (3-5 itens específicos e acionáveis)
- next_steps: próximo passo mais importante agora

Responda APENAS em JSON válido."""


def _p_action_plan(data: dict, analysis: dict, action: str) -> str:
    action_ctx = {
        "escalar": (
            "O ativo é forte. Crie um plano para ESCALAR:\n"
            "- Gerar mais conteúdos no mesmo ângulo vencedor\n"
            "- Aumentar frequência de publicação\n"
            "- Testar variações do gancho original\n"
            "- Iniciar campanha de tráfego pago se aplicável"
        ),
        "otimizar": (
            "O ativo é mediano. Crie um plano para OTIMIZAR:\n"
            "- Ajustar o gancho para aumentar CTR\n"
            "- Refinar a oferta ou o CTA\n"
            "- Testar 2-3 variações antes de desistir\n"
            "- Identificar o que está travando a conversão"
        ),
        "stop": (
            "O ativo é fraco. Crie um plano de ENCERRAMENTO:\n"
            "- Parar produção de conteúdo neste ângulo\n"
            "- Arquivar o que foi produzido\n"
            "- Extrair aprendizados antes de fechar\n"
            "- Redirecionar esforço para o Opportunity Engine"
        ),
    }

    return f"""Produto: {data.get('idea_title', '')}
Decisão: {action.upper()}

{action_ctx.get(action, '')}

Análise do ativo:
- Repeat: {json.dumps(analysis.get('repeat', []), ensure_ascii=False)}
- Kill: {json.dumps(analysis.get('kill', []), ensure_ascii=False)}
- Insight: {analysis.get('insight', '')}

Crie um plano de ação de 7 dias concreto e específico para esta decisão.

Responda APENAS em JSON válido:

{{
  "plano_7_dias": [
    {{"dia": "Dia 1", "acao": "", "responsavel": "sistema", "prioridade": "alta"}}
  ],
  "recursos_necessarios": [],
  "kpis_para_monitorar": [],
  "criterio_de_sucesso": ""
}}"""


def _format_context(data: dict) -> str:
    lines = []
    if data.get("top_hooks"):
        lines.append(f"Ganchos vencedores: {', '.join(data['top_hooks'][:3])}")
    if data.get("top_ctas"):
        lines.append(f"CTAs de maior conversão: {', '.join(data['top_ctas'][:3])}")
    if data.get("best_format"):
        lines.append(f"Formato mais performático: {data['best_format']}")
    if data.get("platform"):
        lines.append(f"Plataforma principal: {data['platform']}")
    if data.get("validation_decision"):
        lines.append(f"Decisão de validação anterior: {data['validation_decision']}")
    return "\n".join(lines) if lines else "Sem contexto adicional disponível."


# ─── Etapas do pipeline ───────────────────────────────────────────────────────

def _normalize(raw: dict) -> dict:
    """Node 03 — recalcula conversion_rate real a partir de leads/sales."""
    leads = raw.get("leads", 0) or 0
    sales = raw.get("sales", 0) or 0
    conversion_rate = (sales / leads) if leads > 0 else raw.get("conversion_rate", 0) or 0
    return {**raw, "conversion_rate": round(conversion_rate, 6)}


def _scaling_score(data: dict) -> dict:
    """Node 04 — computa scaling_score e scaling_status."""
    perf = data.get("performance_score", 0) or 0
    valid = data.get("validation_score", 0) or 0
    conv = data.get("conversion_rate", 0) or 0

    score = (
        perf  * SCALING_WEIGHTS["performance"] +
        valid * SCALING_WEIGHTS["validation"] +
        conv  * SCALING_WEIGHTS["conversion"]
    )
    score = min(round(score), 100)

    if score >= 75:
        status = "scale"
    elif score >= 50:
        status = "optimize"
    else:
        status = "stop"

    return {**data, "scaling_score": score, "scaling_status": status}


def _decision(data: dict) -> str:
    """Node 06 — decisão final."""
    status = data.get("scaling_status", "stop")
    return {"scale": "escalar", "optimize": "otimizar", "stop": "stop"}.get(status, "stop")


# ─── Auto-coleta de dados ─────────────────────────────────────────────────────

def _collect_from_outputs(title_filter: Optional[str] = None) -> list[dict]:
    """
    Coleta dados de performance_*.json, validation_*.json e crm_leads.json
    e consolida por produto (idea_title).
    """
    consolidated: dict[str, dict] = {}

    # Performance
    for path in glob.glob(f"{OUTPUTS_DIR}/performance_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            m = d.get("metrics", {})
            title = m.get("asset_id", "?")
            if title_filter and title_filter.lower() not in title.lower():
                continue
            if title not in consolidated:
                consolidated[title] = {"idea_title": title}
            c = consolidated[title]
            # pega o melhor score de performance
            if m.get("performance_score", 0) > c.get("performance_score", 0):
                c["performance_score"] = m.get("performance_score", 0)
                c["platform"] = m.get("platform", "")
                ins = d.get("insights", {})
                c["top_hooks"] = ins.get("repeat", [])[:3]
        except Exception:
            pass

    # Validation
    for path in glob.glob(f"{OUTPUTS_DIR}/validation_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            title = d.get("idea_title", "?")
            if title_filter and title_filter.lower() not in title.lower():
                continue
            if title not in consolidated:
                consolidated[title] = {"idea_title": title}
            c = consolidated[title]
            s = d.get("signals", {})
            if s.get("validation_score", 0) > c.get("validation_score", 0):
                c["validation_score"]    = s.get("validation_score", 0)
                c["validation_decision"] = d.get("final_action", "")
                c["leads"]               = s.get("leads", 0)
        except Exception:
            pass

    # CRM leads
    crm_file = os.path.join(OUTPUTS_DIR, "crm_leads.json")
    if os.path.exists(crm_file):
        try:
            with open(crm_file, encoding="utf-8") as f:
                leads = json.load(f)
            for lead in leads:
                title = lead.get("product", "?")
                if title_filter and title_filter.lower() not in title.lower():
                    continue
                if title not in consolidated:
                    consolidated[title] = {"idea_title": title}
                c = consolidated[title]
                c["crm_leads"] = c.get("crm_leads", 0) + 1
                if lead.get("pipeline_stage") == "cliente":
                    c["sales"] = c.get("sales", 0) + 1
        except Exception:
            pass

    # normaliza campos ausentes
    result = []
    for title, data in consolidated.items():
        data.setdefault("performance_score", 0)
        data.setdefault("validation_score", 0)
        data.setdefault("leads", data.get("crm_leads", 0))
        data.setdefault("sales", 0)
        data.setdefault("conversion_rate", 0)
        result.append(data)

    return result


# ─── Fluxo principal ──────────────────────────────────────────────────────────

async def run_scaling(raw_input: dict) -> dict:
    title = raw_input.get("idea_title", "?")
    print(f"\n  Analisando escala: {title[:60]}")
    print("  " + "─" * 56)

    # [1] Normalize
    print("  [1/6] Normalizing data...")
    data = _normalize(raw_input)
    print(f"        ✓ conv rate {data['conversion_rate']*100:.1f}% "
          f"({data.get('sales',0)} vendas / {data.get('leads',0)} leads)")

    # [2] Scaling Score
    print("  [2/6] Scaling Score...")
    data = _scaling_score(data)
    STATUS_ICON = {"scale": "🚀", "optimize": "🔧", "stop": "🛑"}
    print(f"        ✓ score {data['scaling_score']}/100 → "
          f"{STATUS_ICON.get(data['scaling_status'],'')} {data['scaling_status'].upper()}")

    # [3] Claude Analysis
    print("  [3/6] Claude Scaling Analysis...")
    data["timestamp"] = time.strftime("%Y%m%d_%H%M%S")
    analysis_raw, m1 = await _claude(_p_scaling_analysis(data))
    analysis = analysis_raw if isinstance(analysis_raw, dict) else {}
    print(f"        ✓ {m1['latency_ms']}ms · ${m1['cost']:.4f}")

    # [4] Decision Engine
    print("  [4/6] Decision Engine...")
    final_action = _decision(data)
    print(f"        ✓ DECISÃO FINAL: {final_action.upper()}")

    # [5] Action Generator
    print("  [5/6] Action Generator...")
    plan_raw, m2 = await _claude(_p_action_plan(data, analysis, final_action), max_tokens=1400)
    plan = plan_raw if isinstance(plan_raw, dict) else {}
    total_cost = m1["cost"] + m2["cost"]
    days = len(plan.get("plano_7_dias", []))
    print(f"        ✓ {days} ações planejadas · ${m2['cost']:.4f}")

    # [6] Save
    print("  [6/6] Saving scaling decision...")
    result = {
        "idea_title":    title,
        "data":          data,
        "analysis":      analysis,
        "action_plan":   plan,
        "final_action":  final_action,
        "total_cost":    total_cost,
        "timestamp":     data["timestamp"],
        "response": {
            "status":         "success",
            "idea_title":     title,
            "scaling_score":  data["scaling_score"],
            "scaling_status": data["scaling_status"],
            "final_action":   final_action,
            "insight":        analysis.get("insight", ""),
            "next_steps":     analysis.get("next_steps", ""),
        },
    }

    fname = _salvar_local(result)
    print(f"        ✓ Salvo em {fname}")

    _imprimir(result)
    await _salvar_notion(result)
    _atualizar_dashboard()

    return result


async def run_all(title_filter: Optional[str] = None):
    """Modo automático: coleta todos os dados existentes e roda scaling em cada produto."""
    items = _collect_from_outputs(title_filter)
    if not items:
        print("\n  Nenhum dado encontrado nos outputs.")
        print("  Execute os engines anteriores primeiro.")
        return

    print(f"\n  Scaling Engine — {len(items)} produto(s) encontrado(s)")
    results = []
    for item in items:
        try:
            r = await run_scaling(item)
            results.append(r)
        except Exception as e:
            print(f"  Erro em {item.get('idea_title','?')}: {e}")

    # Resumo final
    if len(results) > 1:
        print("\n" + "═" * 62)
        print("  RESUMO — Decisões de Escala")
        print("═" * 62)
        for r in sorted(results, key=lambda x: -x["data"]["scaling_score"]):
            icon = {"escalar": "🚀", "otimizar": "🔧", "stop": "🛑"}.get(r["final_action"], "?")
            print(f"  {icon} [{r['data']['scaling_score']:>3}/100] {r['idea_title'][:45]}")
        print()


# ─── Ranking ──────────────────────────────────────────────────────────────────

def show_ranking():
    files = sorted(glob.glob(f"{OUTPUTS_DIR}/scaling_*.json"), reverse=True)
    if not files:
        print("  Nenhuma decisão de escala encontrada.")
        print("  Rode: python scaling_engine.py")
        return

    records = []
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                records.append(json.load(f))
        except Exception:
            pass

    records.sort(key=lambda x: -x.get("data", {}).get("scaling_score", 0))

    ACTION_ICON = {"escalar": "🚀 ESCALAR", "otimizar": "🔧 OTIMIZAR", "stop": "🛑 STOP"}

    print("\n" + "═" * 70)
    print("  SCALING ENGINE — Ranking de Decisões")
    print("═" * 70)
    print(f"  {'#':<3} {'Score':<7} {'Decisão':<14} Produto")
    print("  " + "─" * 64)
    for i, r in enumerate(records, 1):
        d      = r.get("data", {})
        action = r.get("final_action", "stop")
        title  = r.get("idea_title", "?")[:40]
        print(f"  {i:<3} {d.get('scaling_score',0):<7} "
              f"{ACTION_ICON.get(action, action):<14} {title}")
        ins = r.get("analysis", {}).get("insight", "")
        if ins:
            print(f"       → {ins[:70]}")

    escalar  = sum(1 for r in records if r.get("final_action") == "escalar")
    otimizar = sum(1 for r in records if r.get("final_action") == "otimizar")
    stop     = sum(1 for r in records if r.get("final_action") == "stop")

    print("═" * 70)
    print(f"\n  🚀 Escalar: {escalar}  |  🔧 Otimizar: {otimizar}  |  🛑 Stop: {stop}\n")


# ─── Persistência ─────────────────────────────────────────────────────────────

def _salvar_local(result: dict) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    slug  = result["idea_title"].replace(" ", "_")[:28]
    fname = f"{OUTPUTS_DIR}/scaling_{slug}_{result['timestamp']}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return fname


async def _salvar_notion(result: dict):
    try:
        from notion_logger import salvar_tarefa
        d   = result["data"]
        a   = result.get("analysis", {})
        p   = result.get("action_plan", {})
        body = (
            f"Decisão: {result.get('final_action','').upper()}\n"
            f"Score: {d.get('scaling_score',0)}/100 ({d.get('scaling_status','')})\n"
            f"Performance: {d.get('performance_score',0)} | Validation: {d.get('validation_score',0)} | "
            f"Conversão: {d.get('conversion_rate',0)*100:.1f}%\n\n"
            f"Insight: {a.get('insight','')}\n\n"
            f"Repetir:\n" + "\n".join(f"• {r}" for r in a.get("repeat", [])) +
            f"\n\nEliminar:\n" + "\n".join(f"• {k}" for k in a.get("kill", [])) +
            f"\n\nPróximos passos: {a.get('next_steps','')}"
        )
        await salvar_tarefa(
            f"Scaling: {result['idea_title'][:50]} → {result.get('final_action','').upper()} "
            f"({d.get('scaling_score',0)}/100)",
            "scaling_engine",
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
        print("  Dashboard atualizado.")
    except Exception as e:
        print(f"  Dashboard: {e}")


# ─── Display terminal ─────────────────────────────────────────────────────────

def _imprimir(result: dict):
    d    = result["data"]
    a    = result.get("analysis", {})
    p    = result.get("action_plan", {})
    act  = result["final_action"]

    ACTION_BLOCK = {
        "escalar":  ("🚀  ESCALAR", ["Gerar mais conteúdos no ângulo vencedor",
                                     "Aumentar frequência de publicação",
                                     "Testar variações do gancho original"]),
        "otimizar": ("🔧  OTIMIZAR", ["Ajustar gancho para aumentar CTR",
                                      "Refinar oferta ou CTA",
                                      "Testar 2-3 variações antes de desistir"]),
        "stop":     ("🛑  STOP",     ["Parar produção neste ângulo",
                                      "Arquivar conteúdos gerados",
                                      "Voltar para o Opportunity Engine"]),
    }
    label, default_steps = ACTION_BLOCK.get(act, (act.upper(), []))

    print("\n" + "═" * 62)
    print(f"  SCALING ENGINE — {result['idea_title'][:40]}")
    print("═" * 62)

    print(f"\n  Scaling Score   : {d['scaling_score']}/100")
    print(f"  Status          : {d['scaling_status'].upper()}")
    print(f"  Performance     : {d.get('performance_score',0)}/100")
    print(f"  Validation      : {d.get('validation_score',0)}/100")
    print(f"  Conversão       : {d.get('conversion_rate',0)*100:.1f}% "
          f"({d.get('sales',0)} vendas / {d.get('leads',0)} leads)")

    if a.get("insight"):
        print(f"\n  Insight: {a['insight']}")

    if a.get("why_it_worked"):
        print(f"\n  Por que performou: {a['why_it_worked'][:120]}")

    if a.get("repeat"):
        print(f"\n  ─── Repetir ─────────────────────────────────────────────")
        for r in a["repeat"]:
            print(f"  ✓ {r}")

    if a.get("kill"):
        print(f"\n  ─── Eliminar ────────────────────────────────────────────")
        for k in a["kill"]:
            print(f"  ✗ {k}")

    print(f"\n  {'─'*58}")
    print(f"  DECISÃO: {label}")
    print(f"  {'─'*58}")

    plano = p.get("plano_7_dias", [])
    if plano:
        print(f"\n  ─── Plano 7 dias ────────────────────────────────────────")
        for item in plano:
            pri = item.get("prioridade", "")
            pri_tag = "🔴" if pri == "alta" else ("🟡" if pri == "media" else "⚪")
            print(f"  {pri_tag} [{item.get('dia',''):<6}] {item.get('acao','')[:58]}")
    else:
        for step in default_steps:
            print(f"  → {step}")

    if p.get("criterio_de_sucesso"):
        print(f"\n  Critério de sucesso: {p['criterio_de_sucesso'][:80]}")

    if a.get("next_steps"):
        print(f"\n  Próximo passo agora: {a['next_steps'][:100]}")

    print(f"\n  Custo total : ~${result.get('total_cost',0):.4f}")
    print("═" * 62 + "\n")

    print("  Response (Node 09):")
    print(json.dumps(result["response"], ensure_ascii=False, indent=2))
    print()


# ─── CLI ──────────────────────────────────────────────────────────────────────

async def main():
    args = sys.argv[1:]

    if "--ranking" in args:
        show_ranking()
        return

    # --json: input direto
    if "--json" in args:
        idx = args.index("--json")
        raw = json.loads(args[idx + 1])
        await run_scaling(raw)
        return

    # --title: foca em produto específico usando dados existentes
    if "--title" in args:
        idx   = args.index("--title")
        title = args[idx + 1] if idx + 1 < len(args) else ""
        await run_all(title_filter=title)
        return

    # sem argumentos: auto-mode completo
    await run_all()


if __name__ == "__main__":
    asyncio.run(main())
