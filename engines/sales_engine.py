#!/usr/bin/env python3
"""
Sales Engine — Pipeline AI
Transforma produto em funil de vendas completo.

Fluxo:
  Product Blueprint
  → Offer Refinement   (Claude) — oferta afiada para conversão
  → Landing Page       (GPT)   — estrutura completa da página
  → CTA Generator      (GPT)   — 5 CTAs de alto impacto
  → Lead Capture       (lógica) — canal de captura
  → Sequence Generator (GPT)   — 5 mensagens de conversão
  → Save + Notion + Dashboard

Uso:
  python sales_engine.py                       # pega melhor blueprint automaticamente
  python sales_engine.py --title "CFO Digital"
  python sales_engine.py --json '{...}'
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

WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "")  # ex: 5511999999999


# ─── API helpers ──────────────────────────────────────────────────────────────

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


async def _claude(prompt: str, max_tokens: int = 1800) -> tuple[dict, dict]:
    if not ANTHROPIC_API_KEY or "sua-chave" in ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY não configurada")
    payload = {"model": CLAUDE_MODEL, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
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


async def _gpt(prompt: str) -> tuple[dict, dict]:
    if not OPENAI_API_KEY or "sua-chave" in OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY não configurada")
    payload = {"model": GPT_MODEL, "input": prompt}
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    t0 = time.time()
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post("https://api.openai.com/v1/responses", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    raw = "\n".join(i.get("content", [{}])[0].get("text", "")
                    for i in data.get("output", []) if i.get("type") == "message")
    u = data.get("usage", {})
    return _parse_json(raw), {
        "latency_ms": int((time.time() - t0) * 1000),
        "cost": round((u.get("input_tokens", 0) * 2.5e-6) + (u.get("output_tokens", 0) * 10e-6), 6),
    }


# ─── Prompts ──────────────────────────────────────────────────────────────────

def _p_offer_refinement(bp: dict) -> str:
    o = bp.get("offer_design", {})
    s = bp.get("product_strategy", {})
    c = bp.get("copy_base", {})
    return f"""Você é um especialista em copywriting e vendas de alta conversão.

Produto: {bp['idea_title']}
Público: {bp.get('target_audience', '')}

Oferta atual:
{json.dumps(o, ensure_ascii=False, indent=2)}

Estratégia:
Transformação: {s.get('transformation', '')}
Mecanismo único: {s.get('unique_mechanism', '')}
Headline atual: {c.get('headline', '')}

Refine esta oferta para maximizar conversão:
- Torne a promessa irresistível e específica
- Injete urgência real (não artificial)
- Eleve a percepção de valor
- Elimine fricção e dúvidas
- Posicione contra alternativas

Retorne APENAS em JSON válido:

{{
  "refined_promise": "",
  "irresistible_offer": "",
  "main_sale_angle": "",
  "urgency_element": "",
  "value_stack": [],
  "risk_reversal": "",
  "ideal_price_anchor": "",
  "refined_headline": "",
  "refined_subheadline": ""
}}"""


def _p_landing_page(bp: dict, offer: dict) -> str:
    return f"""Você é um copywriter especialista em landing pages de alta conversão.

Produto: {bp['idea_title']}
Público: {bp.get('target_audience', '')}
Promessa refinada: {offer.get('refined_promise', '')}
Ângulo de venda: {offer.get('main_sale_angle', '')}
Urgência: {offer.get('urgency_element', '')}
Garantia/Reversão de risco: {offer.get('risk_reversal', '')}

Crie uma landing page de alta conversão com todas as seções:

1. Above the fold: headline + subheadline + CTA principal
2. Seção de dor: 3 dores reais do público
3. Seção de solução: como o produto resolve
4. Seção de prova: tipos de prova social recomendados
5. Seção de benefícios: 5 bullets de transformação
6. Seção de oferta: o que está incluso + preço
7. Garantia: reversão de risco
8. FAQ: 3 perguntas frequentes com resposta
9. CTA final: urgência + ação

Escreva o copy completo de cada seção, pronto para usar.

Responda APENAS em JSON válido:

{{
  "above_fold": {{
    "headline": "",
    "subheadline": "",
    "cta_button": ""
  }},
  "pain_section": {{
    "title": "",
    "pains": []
  }},
  "solution_section": {{
    "title": "",
    "body": ""
  }},
  "proof_section": {{
    "title": "",
    "proof_types": []
  }},
  "benefits_section": {{
    "title": "",
    "bullets": []
  }},
  "offer_section": {{
    "title": "",
    "what_included": [],
    "price_anchor": "",
    "real_price": "",
    "cta_button": ""
  }},
  "guarantee": {{
    "title": "",
    "body": ""
  }},
  "faq": [
    {{"question": "", "answer": ""}}
  ],
  "final_cta": {{
    "urgency": "",
    "button": "",
    "reassurance": ""
  }}
}}"""


def _p_ctas(bp: dict, offer: dict) -> str:
    return f"""Crie 5 CTAs (calls-to-action) de alto impacto para:

Produto: {bp['idea_title']}
Público: {bp.get('target_audience', '')}
Promessa: {offer.get('refined_promise', '')}
Urgência: {offer.get('urgency_element', '')}

Cada CTA deve ter:
- texto do botão (curto, ação clara, até 8 palavras)
- contexto de uso (onde usar: hero, meio de página, final, popup, etc)
- tom (urgente / aspiracional / direto / benefício / curiosidade)

Responda APENAS em JSON válido:

{{
  "ctas": [
    {{"button_text": "", "context": "", "tom": ""}}
  ]
}}"""


def _p_sequence(bp: dict, offer: dict, lead_capture: str) -> str:
    canal = "WhatsApp" if lead_capture == "whatsapp" else "e-mail"
    return f"""Crie uma sequência de 5 mensagens de conversão para {canal}.

Produto: {bp['idea_title']}
Público: {bp.get('target_audience', '')}
Oferta irresistível: {offer.get('irresistible_offer', '')}
Preço âncora: {offer.get('ideal_price_anchor', '')}

Sequência:
- Mensagem 1 — Conexão: quebrar o gelo, mostrar que entende a dor
- Mensagem 2 — Dor: amplificar o problema, custo de não resolver
- Mensagem 3 — Valor: mostrar a transformação possível com o produto
- Mensagem 4 — Prova: resultado de quem já usou / depoimento hipotético
- Mensagem 5 — CTA: oferta clara, urgência real, fricção zero

Para cada mensagem:
- assunto (para email) ou primeira linha (para WhatsApp)
- corpo completo
- cta (próximo passo)
- timing (quando enviar: imediato / 1 dia / 2 dias / 3 dias / 5 dias)

Responda APENAS em JSON válido:

{{
  "sequence": [
    {{
      "numero": 1,
      "nome": "Conexão",
      "assunto": "",
      "corpo": "",
      "cta": "",
      "timing": ""
    }}
  ]
}}"""


# ─── Lead Capture ─────────────────────────────────────────────────────────────

def _setup_lead_capture(bp: dict) -> dict:
    canal = "whatsapp"
    link  = f"https://wa.me/{WHATSAPP_NUMBER}?text=Quero+saber+mais+sobre+{bp['idea_title'].replace(' ', '+')}" \
            if WHATSAPP_NUMBER else "wa.me/SEU_NUMERO"
    return {
        "lead_capture": canal,
        "link":         link,
        "alternatives": ["formulário simples", "link direto", "checkout"],
        "note":         "Configure WHATSAPP_NUMBER no .env para link personalizado",
    }


# ─── Fluxo principal ──────────────────────────────────────────────────────────

async def build_funnel(bp: dict) -> dict:
    title = bp.get("idea_title", "")
    print(f"\n  Construindo funil: {title[:60]}")
    print("  " + "─" * 56)

    total_cost = 0.0

    # [1] Offer Refinement — Claude
    print("  [1/5] Offer Refinement via Claude...")
    offer_raw, m1 = await _claude(_p_offer_refinement(bp))
    offer = offer_raw if isinstance(offer_raw, dict) else {}
    total_cost += m1["cost"]
    print(f"        ✓ {m1['latency_ms']}ms · ${m1['cost']:.4f}")

    # [2] Landing Page — GPT
    print("  [2/5] Landing Page via GPT...")
    lp_raw, m2 = await _gpt(_p_landing_page(bp, offer))
    landing_page = lp_raw if isinstance(lp_raw, dict) else {}
    total_cost += m2["cost"]
    print(f"        ✓ {m2['latency_ms']}ms · ${m2['cost']:.4f}")

    # [3] CTAs — GPT
    print("  [3/5] CTAs via GPT...")
    ctas_raw, m3 = await _gpt(_p_ctas(bp, offer))
    ctas = ctas_raw.get("ctas", []) if isinstance(ctas_raw, dict) else []
    total_cost += m3["cost"]
    print(f"        ✓ {len(ctas)} CTAs · {m3['latency_ms']}ms · ${m3['cost']:.4f}")

    # [4] Lead Capture — lógica local
    print("  [4/5] Lead Capture Setup...")
    lead_capture = _setup_lead_capture(bp)
    print(f"        ✓ Canal: {lead_capture['lead_capture']} → {lead_capture['link'][:60]}")

    # [5] Sequence — GPT
    print("  [5/5] Sequence Generator via GPT...")
    seq_raw, m4 = await _gpt(_p_sequence(bp, offer, lead_capture["lead_capture"]))
    sequence = seq_raw.get("sequence", []) if isinstance(seq_raw, dict) else []
    total_cost += m4["cost"]
    print(f"        ✓ {len(sequence)} mensagens · {m4['latency_ms']}ms · ${m4['cost']:.4f}")

    result = {
        "idea_title":       title,
        "target_audience":  bp.get("target_audience", ""),
        "offer_refinement": offer,
        "landing_page":     landing_page,
        "ctas":             ctas,
        "lead_capture":     lead_capture,
        "sequence":         sequence,
        "total_cost":       round(total_cost, 6),
        "timestamp":        time.strftime("%Y%m%d_%H%M%S"),
        "response": {
            "status":         "success",
            "funnel_created": True,
            "product":        title,
            "lead_capture":   lead_capture["lead_capture"],
            "link":           lead_capture["link"],
            "headline":       offer.get("refined_headline", ""),
            "main_cta":       ctas[0].get("button_text", "") if ctas else "",
        },
    }

    _salvar_local(result)
    _imprimir(result)
    await _salvar_notion(result)
    _atualizar_dashboard()

    return result


# ─── Persistência ─────────────────────────────────────────────────────────────

def _salvar_local(result: dict) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    slug  = result["idea_title"].replace(" ", "_")[:28]
    fname = f"{OUTPUTS_DIR}/funnel_{slug}_{result['timestamp']}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  Salvo em: {fname}")
    return fname


async def _salvar_notion(result: dict):
    try:
        from integrations.notion_logger import salvar_tarefa
        await salvar_tarefa(
            f"Funil: {result['idea_title'][:60]}",
            "sales_engine",
            json.dumps(result, ensure_ascii=False, indent=2),
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
    o  = result.get("offer_refinement", {})
    lp = result.get("landing_page", {})
    ct = result.get("ctas", [])
    lc = result.get("lead_capture", {})
    sq = result.get("sequence", [])
    af = lp.get("above_fold", {})

    print("\n" + "═" * 62)
    print(f"  SALES ENGINE — {result['idea_title'][:40]}")
    print("═" * 62)

    print(f"\n  ─── Oferta refinada ─────────────────────────────────────")
    print(f"  Headline     : {o.get('refined_headline','')}")
    print(f"  Promessa     : {o.get('refined_promise','')}")
    print(f"  Ângulo       : {o.get('main_sale_angle','')}")
    print(f"  Urgência     : {o.get('urgency_element','')}")
    print(f"  Garantia     : {o.get('risk_reversal','')}")
    print(f"  Preço âncora : {o.get('ideal_price_anchor','')}")

    if af:
        print(f"\n  ─── Landing Page (above the fold) ───────────────────────")
        print(f"  Headline : {af.get('headline','')}")
        print(f"  Sub      : {af.get('subheadline','')}")
        print(f"  Botão    : {af.get('cta_button','')}")

    lp_sections = [k for k in lp if k != "above_fold"]
    print(f"\n  Seções geradas: {', '.join(lp_sections)}")

    if ct:
        print(f"\n  ─── CTAs ────────────────────────────────────────────────")
        for c in ct:
            print(f"  [{c.get('tom',''):<12}] {c.get('button_text','')} ({c.get('context','')})")

    print(f"\n  ─── Lead Capture ────────────────────────────────────────")
    print(f"  Canal : {lc.get('lead_capture','')}")
    print(f"  Link  : {lc.get('link','')}")

    if sq:
        print(f"\n  ─── Sequência ({len(sq)} mensagens) ──────────────────────────")
        for m in sq:
            print(f"  [{m.get('timing',''):<10}] Msg {m.get('numero','')}: {m.get('nome','')} — {m.get('assunto','')[:45]}")

    print(f"\n  Custo total : ~${result['total_cost']:.4f}")
    print("═" * 62 + "\n")

    print("  Response (Node 08):")
    print(json.dumps(result["response"], ensure_ascii=False, indent=2))
    print()


# ─── Carregar blueprint ───────────────────────────────────────────────────────

def _load_best_blueprint() -> Optional[dict]:
    files = glob.glob(f"{OUTPUTS_DIR}/blueprint_*.json")
    best, best_score = None, -1
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            bp = data.get("blueprint", {})
            if bp.get("final_score", 0) > best_score:
                best_score = bp["final_score"]
                best = bp
        except Exception:
            pass
    return best


def _load_blueprint_by_title(title: str) -> Optional[dict]:
    for path in glob.glob(f"{OUTPUTS_DIR}/blueprint_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            bp = data.get("blueprint", {})
            if title.lower() in bp.get("idea_title", "").lower():
                return bp
        except Exception:
            pass
    return None


# ─── CLI ──────────────────────────────────────────────────────────────────────

async def main():
    args = sys.argv[1:]
    bp   = None

    if "--json" in args:
        idx = args.index("--json")
        bp  = json.loads(args[idx + 1])
    elif "--title" in args:
        idx = args.index("--title")
        title = args[idx + 1] if idx + 1 < len(args) else ""
        bp = _load_blueprint_by_title(title)
        if not bp:
            print(f"  Blueprint não encontrado para: {title}")
            return
    else:
        bp = _load_best_blueprint()
        if bp:
            print(f"\n  Blueprint carregado: {bp.get('idea_title','')} (score {bp.get('final_score',0)})")
        else:
            print("  Nenhum blueprint encontrado. Rode product_engine.py primeiro.")
            return

    if not bp.get("idea_title"):
        print("  idea_title obrigatório.")
        return

    await build_funnel(bp)


if __name__ == "__main__":
    asyncio.run(main())
