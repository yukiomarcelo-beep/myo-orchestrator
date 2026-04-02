#!/usr/bin/env python3
"""
Product Engine — Pipeline AI
Pega a oportunidade vencedora do Opportunity Engine e constrói o blueprint completo.

Fluxo:
  Opportunity Winner
  → Product Strategy   (Claude)
  → Offer Design       (Claude)
  → Naming             (GPT)
  → Product Structure  (GPT)
  → Copy Base          (GPT)
  → Save Blueprint     (JSON + Notion + Dashboard)

Uso:
  python product_engine.py                            # pega melhor scoring automaticamente
  python product_engine.py --title "CFO Digital..."  # busca pelo título
  python product_engine.py --json '{"idea_title":...}'
"""
import asyncio, json, os, sys, time, glob
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-6"
GPT_MODEL         = os.getenv("GPT_MODEL", "gpt-4o")
OUTPUTS_DIR       = "outputs"


# ─── Helpers de chamada de API ────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s != -1 and e > s:
            return json.loads(raw[s:e])
        raise ValueError(f"JSON inválido: {raw[:200]}")


async def _claude(prompt: str, max_tokens: int = 1800) -> tuple[dict, dict]:
    if not ANTHROPIC_API_KEY or "sua-chave" in ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY não configurada")
    payload = {
        "model": CLAUDE_MODEL, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    t0 = time.time()
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    raw = data.get("content", [{}])[0].get("text", "")
    usage = data.get("usage", {})
    meta = {
        "latency_ms": int((time.time() - t0) * 1000),
        "tokens_in": usage.get("input_tokens", 0),
        "tokens_out": usage.get("output_tokens", 0),
        "cost": round((usage.get("input_tokens", 0) * 3e-6) + (usage.get("output_tokens", 0) * 15e-6), 6),
    }
    return _parse_json(raw), meta


async def _gpt(prompt: str) -> tuple[dict, dict]:
    if not OPENAI_API_KEY or "sua-chave" in OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY não configurada")
    payload = {"model": GPT_MODEL, "input": prompt}
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    t0 = time.time()
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post("https://api.openai.com/v1/responses", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    items = data.get("output", [])
    raw = "\n".join(i.get("content", [{}])[0].get("text", "")
                    for i in items if i.get("type") == "message")
    usage = data.get("usage", {})
    meta = {
        "latency_ms": int((time.time() - t0) * 1000),
        "tokens_in": usage.get("input_tokens", 0),
        "tokens_out": usage.get("output_tokens", 0),
        "cost": round((usage.get("input_tokens", 0) * 2.5e-6) + (usage.get("output_tokens", 0) * 10e-6), 6),
    }
    return _parse_json(raw), meta


# ─── Prompts ─────────────────────────────────────────────────────────────────

def _prompt_strategy(w: dict) -> str:
    return f"""Você é um estrategista de produto sênior.

Com base nesta oportunidade vencedora:

Título: {w['idea_title']}
Descrição: {w['idea_description']}
Público: {w['target_audience']}
Contexto: {w['market_context']}
Score: {w.get('final_score', 0)}/100 | Prioridade: {w.get('priority', '')}

Defina a estratégia completa do produto:
1. transformação principal prometida ao cliente
2. problema central resolvido
3. mecanismo único do produto (o que o torna diferente e crível)
4. objeções prováveis do público (2-4 objeções reais)
5. melhor formato inicial do produto
6. diferenciais competitivos (2-4 diferenciais concretos)
7. versão MVP recomendada para validar rápido

Responda APENAS em JSON válido, sem markdown:

{{
  "transformation": "",
  "core_problem": "",
  "unique_mechanism": "",
  "main_objections": [],
  "best_initial_format": "",
  "competitive_differentials": [],
  "mvp_recommendation": ""
}}"""


def _prompt_offer(w: dict, strategy: dict) -> str:
    return f"""Você é um especialista em design de oferta.

Oportunidade:
Título: {w['idea_title']}
Descrição: {w['idea_description']}
Público: {w['target_audience']}

Estratégia definida:
{json.dumps(strategy, ensure_ascii=False, indent=2)}

Monte a estrutura completa da oferta:
1. promessa principal (clara, específica, mensurável)
2. entregáveis (lista do que o cliente recebe)
3. formato de entrega
4. duração ideal
5. bônus possíveis (2-3 bônus que aumentam o valor percebido)
6. ângulo de posicionamento (como apresentar no mercado)
7. ticket sugerido de entrada
8. versão low ticket (porta de entrada, menor comprometimento)
9. versão premium (máximo valor, maior ticket)

Responda APENAS em JSON válido, sem markdown:

{{
  "main_promise": "",
  "deliverables": [],
  "delivery_format": "",
  "ideal_duration": "",
  "bonus_options": [],
  "positioning_angle": "",
  "entry_ticket": "",
  "low_ticket_version": "",
  "premium_version": ""
}}"""


def _prompt_naming(w: dict, strategy: dict, offer: dict) -> str:
    return f"""Crie 10 nomes fortes para este produto.

Produto:
Título base: {w['idea_title']}
Transformação: {strategy.get('transformation', '')}
Mecanismo único: {strategy.get('unique_mechanism', '')}
Promessa: {offer.get('main_promise', '')}
Público: {w['target_audience']}
Formato: {offer.get('delivery_format', '')}

Para cada nome, inclua:
- nome (o nome em si)
- justificativa (por que funciona, 1 frase)
- tom: "premium", "direto", "técnico" ou "aspiracional"
- slogan opcional (1 frase de apoio)

Responda APENAS em JSON válido:

{{
  "names": [
    {{"name": "", "justificativa": "", "tom": "", "slogan": ""}},
    {{"name": "", "justificativa": "", "tom": "", "slogan": ""}}
  ],
  "top_pick": "",
  "top_pick_reason": ""
}}"""


def _prompt_structure(strategy: dict, offer: dict) -> str:
    return f"""Monte a estrutura completa do produto.

Estratégia:
{json.dumps(strategy, ensure_ascii=False, indent=2)}

Oferta:
{json.dumps(offer, ensure_ascii=False, indent=2)}

Crie:
1. módulos principais (nome + objetivo de cada módulo)
2. sequência ideal de entrega
3. entregáveis por módulo
4. versão MVP (mínimo para lançar e validar)
5. versão expandida (produto completo)
6. quick wins (o que o cliente conquista nas primeiras 48h)

Responda APENAS em JSON válido:

{{
  "modules": [
    {{"name": "", "objective": "", "deliverables": [], "duration": ""}}
  ],
  "delivery_sequence": [],
  "mvp_version": {{"modules": [], "estimated_time": "", "focus": ""}},
  "expanded_version": {{"modules": [], "estimated_time": "", "focus": ""}},
  "quick_wins": []
}}"""


def _prompt_copy(w: dict, strategy: dict, offer: dict) -> str:
    return f"""Crie a copy base completa para esta oferta.

Contexto:
Título: {w['idea_title']}
Público: {w['target_audience']}
Transformação: {strategy.get('transformation', '')}
Mecanismo único: {strategy.get('unique_mechanism', '')}
Promessa: {offer.get('main_promise', '')}
Ângulo: {offer.get('positioning_angle', '')}
Ticket de entrada: {offer.get('entry_ticket', '')}

Crie:
1. headline principal (impacto máximo, foco na transformação)
2. subheadline (complementa e aprofunda a headline)
3. 5 bullets de valor (benefícios concretos, com especificidade)
4. 3 objeções com resposta (objeção real + resposta persuasiva)
5. CTA principal (ação clara, urgência real)
6. opening hook para conteúdo (gancho para vídeo ou post)

Responda APENAS em JSON válido:

{{
  "headline": "",
  "subheadline": "",
  "value_bullets": [],
  "objections": [
    {{"objection": "", "response": ""}}
  ],
  "cta": "",
  "opening_hook": ""
}}"""


# ─── Fluxo principal ──────────────────────────────────────────────────────────

async def build_product(winner: dict) -> dict:
    title = winner.get("idea_title", "")
    print(f"\n  Construindo produto: {title[:60]}")
    print("  " + "─" * 56)

    total_cost = 0.0
    total_latency = 0

    # Step 1 — Product Strategy (Claude)
    print("  [1/5] Product Strategy via Claude...")
    strategy, m1 = await _claude(_prompt_strategy(winner))
    total_cost += m1["cost"]; total_latency += m1["latency_ms"]
    print(f"        ✓ {m1['latency_ms']}ms · ${m1['cost']:.4f}")

    # Step 2 — Offer Design (Claude)
    print("  [2/5] Offer Design via Claude...")
    offer, m2 = await _claude(_prompt_offer(winner, strategy))
    total_cost += m2["cost"]; total_latency += m2["latency_ms"]
    print(f"        ✓ {m2['latency_ms']}ms · ${m2['cost']:.4f}")

    # Step 3 — Naming (GPT)
    print("  [3/5] Naming via GPT...")
    naming, m3 = await _gpt(_prompt_naming(winner, strategy, offer))
    total_cost += m3["cost"]; total_latency += m3["latency_ms"]
    print(f"        ✓ {m3['latency_ms']}ms · ${m3['cost']:.4f}")

    # Step 4 — Product Structure (GPT)
    print("  [4/5] Product Structure via GPT...")
    structure, m4 = await _gpt(_prompt_structure(strategy, offer))
    total_cost += m4["cost"]; total_latency += m4["latency_ms"]
    print(f"        ✓ {m4['latency_ms']}ms · ${m4['cost']:.4f}")

    # Step 5 — Copy Base (GPT)
    print("  [5/5] Copy Base via GPT...")
    copy_base, m5 = await _gpt(_prompt_copy(winner, strategy, offer))
    total_cost += m5["cost"]; total_latency += m5["latency_ms"]
    print(f"        ✓ {m5['latency_ms']}ms · ${m5['cost']:.4f}")

    blueprint = {
        "idea_title":       title,
        "target_audience":  winner.get("target_audience", ""),
        "market_context":   winner.get("market_context", ""),
        "final_score":      winner.get("final_score", 0),
        "priority":         winner.get("priority", ""),
        "product_strategy": strategy,
        "offer_design":     offer,
        "naming_options":   naming,
        "product_structure": structure,
        "copy_base":        copy_base,
    }

    # Resposta final (equivalente ao Node 11_Response)
    response = {
        "status":               "success",
        "idea_title":           title,
        "best_initial_format":  strategy.get("best_initial_format", ""),
        "main_promise":         offer.get("main_promise", ""),
        "entry_ticket":         offer.get("entry_ticket", ""),
        "top_name":             naming.get("top_pick", ""),
        "mvp":                  strategy.get("mvp_recommendation", ""),
        "headline":             copy_base.get("headline", ""),
        "cta":                  copy_base.get("cta", ""),
    }

    result = {
        "blueprint":      blueprint,
        "response":       response,
        "total_cost":     round(total_cost, 6),
        "total_latency":  total_latency,
        "timestamp":      time.strftime("%Y%m%d_%H%M%S"),
    }

    _salvar_local(result)
    _imprimir(result)

    await _salvar_notion(result)
    _atualizar_dashboard()

    return result


# ─── Persistência ─────────────────────────────────────────────────────────────

def _salvar_local(result: dict) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    slug = result["blueprint"]["idea_title"].replace(" ", "_")[:30]
    fname = f"{OUTPUTS_DIR}/blueprint_{slug}_{result['timestamp']}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  Salvo em: {fname}")
    return fname


async def _salvar_notion(result: dict):
    try:
        from integrations.notion_logger import salvar_tarefa
        bp = result["blueprint"]
        resp = result["response"]
        output_text = json.dumps(result, ensure_ascii=False, indent=2)
        await salvar_tarefa(
            f"Blueprint: {bp['idea_title'][:60]}",
            "blueprint",
            output_text,
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
    bp   = result["blueprint"]
    resp = result["response"]
    s    = bp.get("product_strategy", {})
    o    = bp.get("offer_design", {})
    n    = bp.get("naming_options", {})
    c    = bp.get("copy_base", {})
    st   = bp.get("product_structure", {})

    print("\n" + "═" * 62)
    print(f"  PRODUCT BLUEPRINT — {bp['idea_title'][:38]}")
    print("═" * 62)

    print(f"\n  Formato inicial  : {resp['best_initial_format']}")
    print(f"  Ticket de entrada: {resp['entry_ticket']}")
    print(f"  Nome top pick    : {resp['top_name']}")

    print("\n  ─── Estratégia ─────────────────────────────────────────")
    print(f"  Transformação : {s.get('transformation','')}")
    print(f"  Problema core : {s.get('core_problem','')}")
    print(f"  Mecanismo     : {s.get('unique_mechanism','')}")
    print(f"  MVP           : {s.get('mvp_recommendation','')}")

    print("\n  ─── Oferta ──────────────────────────────────────────────")
    print(f"  Promessa      : {o.get('main_promise','')}")
    print(f"  Posicionamento: {o.get('positioning_angle','')}")
    print(f"  Low ticket    : {o.get('low_ticket_version','')}")
    print(f"  Premium       : {o.get('premium_version','')}")

    deliverables = o.get("deliverables", [])
    if deliverables:
        print("\n  Entregáveis:")
        for d in deliverables:
            print(f"    · {d}")

    print("\n  ─── Nomes ───────────────────────────────────────────────")
    for nm in n.get("names", [])[:5]:
        print(f"  [{nm.get('tom','')[:8]:<8}] {nm.get('name','')} — {nm.get('justificativa','')[:50]}")

    print("\n  ─── Copy ────────────────────────────────────────────────")
    print(f"  Headline  : {c.get('headline','')}")
    print(f"  Sub       : {c.get('subheadline','')}")
    print(f"  Hook      : {c.get('opening_hook','')}")
    print(f"  CTA       : {c.get('cta','')}")

    modules = st.get("modules", [])
    if modules:
        print("\n  ─── Estrutura (módulos) ─────────────────────────────────")
        for m in modules:
            print(f"  · {m.get('name','')} — {m.get('objective','')[:55]}")

    quick = st.get("quick_wins", [])
    if quick:
        print("\n  Quick wins (primeiras 48h):")
        for q in quick:
            print(f"    ✓ {q}")

    print(f"\n  Custo total : ~${result['total_cost']:.4f}")
    print(f"  Tempo total : {result['total_latency']}ms")
    print("═" * 62 + "\n")

    print("  Output final (Node 11_Response):")
    print(json.dumps(resp, ensure_ascii=False, indent=2))
    print()


# ─── Carregar winner automático ───────────────────────────────────────────────

def _load_best_winner() -> Optional[dict]:
    """Carrega a melhor oportunidade dos arquivos de scoring."""
    files = glob.glob(f"{OUTPUTS_DIR}/scoring_*.json")
    best = None
    best_score = -1
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            out = data.get("output", {})
            score = out.get("final_score", 0)
            rec   = out.get("recommendation", "")
            if score > best_score and rec in ("priorizar", "testar"):
                best_score = score
                best = {
                    "idea_title":       out.get("idea_title", ""),
                    "idea_description": data.get("opportunity", {}).get("idea_description", ""),
                    "target_audience":  data.get("opportunity", {}).get("target_audience", ""),
                    "market_context":   data.get("opportunity", {}).get("market_context", ""),
                    "final_score":      score,
                    "priority":         out.get("priority", ""),
                }
        except Exception:
            pass
    return best


def _load_winner_by_title(title: str) -> Optional[dict]:
    for path in glob.glob(f"{OUTPUTS_DIR}/scoring_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if title.lower() in data.get("output", {}).get("idea_title", "").lower():
                out = data.get("output", {})
                opp = data.get("opportunity", {})
                return {
                    "idea_title":       out.get("idea_title", ""),
                    "idea_description": opp.get("idea_description", ""),
                    "target_audience":  opp.get("target_audience", ""),
                    "market_context":   opp.get("market_context", ""),
                    "final_score":      out.get("final_score", 0),
                    "priority":         out.get("priority", ""),
                }
        except Exception:
            pass
    return None


# ─── CLI ─────────────────────────────────────────────────────────────────────

async def main():
    args = sys.argv[1:]
    winner = None

    if "--json" in args:
        idx = args.index("--json")
        winner = json.loads(args[idx + 1])

    elif "--title" in args:
        idx = args.index("--title")
        title = args[idx + 1] if idx + 1 < len(args) else ""
        winner = _load_winner_by_title(title)
        if not winner:
            print(f"  Nenhum scoring encontrado com título contendo: {title}")
            return

    else:
        winner = _load_best_winner()
        if winner:
            print(f"\n  Winner automático: {winner['idea_title']} (score {winner['final_score']})")
        else:
            print("  Nenhum scoring disponível. Rode primeiro o opportunity_scorer.py")
            return

    if not winner.get("idea_title"):
        print("  idea_title obrigatório.")
        return

    await build_product(winner)


if __name__ == "__main__":
    asyncio.run(main())
