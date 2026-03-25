#!/usr/bin/env python3
"""
Orchestrator — Pipeline AI
Uso:
    python orchestrator.py                          # modo interativo
    python orchestrator.py "sua tarefa aqui"        # modo direto
    python orchestrator.py "tarefa" --tipo video    # forçar rota
"""
import asyncio
import hashlib
import json
import os
import sys
import time
from typing import Optional

import httpx
from dotenv import load_dotenv
from notion_logger import salvar_tarefa

load_dotenv()

# ─── Chaves de API ────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
NOTION_API_KEY     = os.getenv("NOTION_API_KEY", "")
NOTION_PAGE_ID     = os.getenv("NOTION_PAGE_ID", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
HEYGEN_API_KEY     = os.getenv("HEYGEN_API_KEY", "")

PERPLEXITY_MODEL = os.getenv("PERPLEXITY_MODEL", "sonar")
CLAUDE_MODEL     = "claude-sonnet-4-6"
GPT_MODEL        = os.getenv("GPT_MODEL", "gpt-4o")


# ─── Utilitários ──────────────────────────────────────────────────────────────

def print_header():
    print("\n" + "═" * 60)
    print("  ORCHESTRATOR — Pipeline AI")
    print("═" * 60)

def print_step(step: str, icon: str = "►"):
    print(f"\n{icon}  {step}")

def print_result(label: str, content: str, max_chars: int = 800):
    print(f"\n{'─' * 50}")
    print(f"  {label}")
    print(f"{'─' * 50}")
    if len(content) > max_chars:
        print(content[:max_chars] + f"\n  ... (+{len(content) - max_chars} chars)")
    else:
        print(content)

def detectar_tipo(input_text: str) -> str:
    t = input_text.lower()
    if any(w in t for w in ["vídeo", "video", "roteiro", "narração", "avatar"]):
        return "video"
    if any(w in t for w in ["score", "scoring", "avaliar oportunidade", "pontuar", "oportunidade vale"]):
        return "scoring"
    if any(w in t for w in ["blueprint", "produto engine", "product engine", "construir produto", "montar produto", "criar produto"]):
        return "product"
    if any(w in t for w in ["content engine", "conteúdo", "conteudo", "post", "gancho", "roteiro de conteúdo", "ideias de conteúdo"]):
        return "content"
    if any(w in t for w in ["video engine", "gerar vídeo", "produzir vídeo", "reels", "tiktok", "tts", "heygen", "elevenlabs"]):
        return "video_engine"
    if any(w in t for w in ["sales engine", "funil", "funnel", "landing page", "vendas", "conversão", "sequência de vendas", "cta"]):
        return "sales_engine"
    if any(w in t for w in ["pesquise", "pesquisa", "tendência", "mercado", "análise de mercado"]):
        return "research"
    if any(w in t for w in ["estratégia", "estrategia", "produto", "oferta", "ideia"]):
        return "strategy"
    return "execution"


# ─── ROTA 1: Pesquisa (Perplexity) ────────────────────────────────────────────

async def rota_research(input_text: str) -> dict:
    print_step("Rota 1 — Pesquisa via Perplexity", "🔍")
    if not PERPLEXITY_API_KEY or "sua-chave" in PERPLEXITY_API_KEY:
        return {"error": "PERPLEXITY_API_KEY não configurada", "output": ""}

    payload = {
        "model": PERPLEXITY_MODEL,
        "messages": [{
            "role": "user",
            "content": (
                f"Pesquise profundamente sobre: {input_text}. "
                "Retorne oportunidades, dores, sinais de demanda, concorrência e riscos."
            )
        }]
    }
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }

    t0 = time.time()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post("https://api.perplexity.ai/chat/completions",
                                 json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    output = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    latency = int((time.time() - t0) * 1000)
    tokens = data.get("usage", {}).get("total_tokens", 0)

    print(f"  ✓ {tokens} tokens · {latency}ms")
    return {"output": output, "tokens": tokens, "latency_ms": latency}


# ─── ROTA 2: Estratégia (Claude) ──────────────────────────────────────────────

async def rota_strategy(input_text: str) -> dict:
    print_step("Rota 2 — Estratégia via Claude", "🧠")
    if not ANTHROPIC_API_KEY or "sua-chave" in ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY não configurada", "output": ""}

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1800,
        "messages": [{
            "role": "user",
            "content": (
                f"Com base neste pedido: {input_text}. "
                "Crie 3 ideias de produto, público-alvo, proposta de valor, "
                "mecanismo único, diferenciação e qual ideia testar primeiro."
            )
        }]
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

    output = data.get("content", [{}])[0].get("text", "")
    usage = data.get("usage", {})
    latency = int((time.time() - t0) * 1000)
    cost = round((usage.get("input_tokens", 0) * 3e-6) + (usage.get("output_tokens", 0) * 15e-6), 6)

    print(f"  ✓ {usage.get('output_tokens', 0)} tokens output · {latency}ms · ~${cost:.4f}")
    return {"output": output, "usage": usage, "latency_ms": latency, "estimated_cost": cost}


# ─── ROTA 3: Execução (GPT) ───────────────────────────────────────────────────

async def rota_execution(input_text: str) -> dict:
    print_step("Rota 3 — Execução via GPT", "⚡")
    if not OPENAI_API_KEY or "sua-chave" in OPENAI_API_KEY:
        return {"error": "OPENAI_API_KEY não configurada", "output": ""}

    payload = {
        "model": GPT_MODEL,
        "input": f"Execute esta tarefa com clareza e objetividade: {input_text}",
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    t0 = time.time()
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post("https://api.openai.com/v1/responses",
                                 json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    output_items = data.get("output", [])
    output = "\n".join(
        item.get("content", [{}])[0].get("text", "")
        for item in output_items if item.get("type") == "message"
    )
    usage = data.get("usage", {})
    latency = int((time.time() - t0) * 1000)

    print(f"  ✓ {usage.get('output_tokens', 0)} tokens output · {latency}ms")
    return {"output": output, "usage": usage, "latency_ms": latency}


# ─── ROTA 5: Opportunity Scoring (Claude) ─────────────────────────────────────

async def rota_scoring(input_text: str) -> dict:
    print_step("Rota 5 — Opportunity Scoring via Claude", "🎯")
    from opportunity_scorer import score_opportunity, imprimir_resultado, construir_opportunity_interativo

    # tenta extrair título do input; pede complemento
    opportunity = {
        "idea_title":       input_text,
        "idea_description": "",
        "target_audience":  "",
        "market_context":   "",
    }

    print("  Complete para uma avaliação precisa (Enter para pular):")
    desc = input("  Descrição da oportunidade: ").strip()
    pub  = input("  Público-alvo: ").strip()
    ctx  = input("  Contexto de mercado: ").strip()

    if desc: opportunity["idea_description"] = desc
    if pub:  opportunity["target_audience"]  = pub
    if ctx:  opportunity["market_context"]   = ctx
    if not opportunity["idea_description"]:
        opportunity["idea_description"] = input_text

    result = await score_opportunity(opportunity)
    imprimir_resultado(opportunity, result)

    out = result.get("output", {})
    return {
        "output": (
            f"Score: {out.get('final_score', '?')}/100 | "
            f"Prioridade: {out.get('priority', '?')} | "
            f"Recomendação: {out.get('recommendation', '')}"
        ),
        "final_score":    out.get("final_score", 0),
        "priority":       out.get("priority", ""),
        "recommendation": out.get("recommendation", ""),
        "raw_scoring":    result.get("raw_scoring", {}),
        "latency_ms":     result.get("latency_ms", 0),
        "estimated_cost": result.get("estimated_cost", 0),
    }


# ─── ROTA 4: Vídeo (Claude + GPT) ─────────────────────────────────────────────

async def rota_video(input_text: str) -> dict:
    print_step("Rota 4 — Vídeo (roteiro + variações)", "🎬")

    # 4a — Roteiro via Claude
    print("  → 12_Claude_Video_Script...")
    script = ""
    if ANTHROPIC_API_KEY and "sua-chave" not in ANTHROPIC_API_KEY:
        payload = {
            "model": CLAUDE_MODEL,
            "max_tokens": 1200,
            "messages": [{
                "role": "user",
                "content": (
                    f"Crie um roteiro curto, com até 30 segundos, para: {input_text}. "
                    "Estruture em gancho, desenvolvimento e CTA."
                )
            }]
        }
        headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post("https://api.anthropic.com/v1/messages",
                                     json=payload, headers=headers)
            resp.raise_for_status()
            script = resp.json().get("content", [{}])[0].get("text", "")
        print(f"  ✓ Roteiro gerado ({len(script)} chars)")
    else:
        print("  ⚠ ANTHROPIC_API_KEY não configurada — pulando roteiro")

    # 4b — Variações via GPT
    variations = ""
    print("  → 13_GPT_Video_Variations...")
    if script and OPENAI_API_KEY and "sua-chave" not in OPENAI_API_KEY:
        payload = {
            "model": GPT_MODEL,
            "input": (f"Com base neste roteiro: {script}, "
                      "crie 3 versões mais agressivas e 3 versões mais elegantes."),
        }
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post("https://api.openai.com/v1/responses",
                                     json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        output_items = data.get("output", [])
        variations = "\n".join(
            item.get("content", [{}])[0].get("text", "")
            for item in output_items if item.get("type") == "message"
        )
        print(f"  ✓ Variações geradas ({len(variations)} chars)")
    else:
        print("  ⚠ Variações puladas (sem chave OpenAI ou sem roteiro base)")

    return {
        "script": script,
        "variations": variations,
        "output": script,
        "note": "TTS (ElevenLabs) e vídeo (HeyGen) disponíveis via pipeline/api (requer chaves configuradas)"
    }


# ─── ROTA 6: Product Engine ───────────────────────────────────────────────────

async def rota_product(input_text: str) -> dict:
    print_step("Rota 6 — Product Engine (Strategy → Offer → Naming → Structure → Copy)", "🏗️")
    from product_engine import build_product, _load_best_winner, _load_winner_by_title

    winner = _load_winner_by_title(input_text) or _load_best_winner()
    if not winner:
        return {"error": "Nenhuma oportunidade encontrada. Rode o opportunity_scorer primeiro.", "output": ""}

    print(f"  Winner: {winner['idea_title']} (score {winner.get('final_score',0)})")
    result = await build_product(winner)
    resp = result.get("response", {})
    return {
        "output": (
            f"Blueprint: {resp.get('idea_title','')} | "
            f"Formato: {resp.get('best_initial_format','')} | "
            f"Nome: {resp.get('top_name','')} | "
            f"Ticket: {resp.get('entry_ticket','')}"
        ),
        **result,
    }


# ─── ROTA 8: Video Engine ─────────────────────────────────────────────────────

async def rota_video_engine(input_text: str) -> dict:
    print_step("Rota 8 — Video Engine (Script → Variations → TTS → HeyGen → Queue)", "🎬")
    from video_engine import build_video, _load_best_content, _load_content_by_title

    content = _load_content_by_title(input_text) or _load_best_content()
    if not content:
        return {"error": "Nenhum conteúdo encontrado. Rode content_engine.py primeiro.", "output": ""}

    print(f"  Conteúdo: {content.get('idea_title','')} ({content.get('timestamp','')})")
    result = await build_video(content)
    vid = result.get("video", {})
    return {
        "output": (
            f"Vídeo: {result['idea_title']} | "
            f"Script ✓ | Variações ✓ | "
            f"Áudio: {'✓' if result.get('audio',{}).get('audio_file') else '⚠'} | "
            f"Vídeo: {'✓ ' + (vid.get('video_url') or vid.get('video_id','')) if not vid.get('error') else '⚠'}"
        ),
        **result,
    }


# ─── ROTA 9: Sales Engine ─────────────────────────────────────────────────────

async def rota_sales_engine(input_text: str) -> dict:
    print_step("Rota 9 — Sales Engine (Offer → Landing Page → CTAs → Lead Capture → Sequence)", "💰")
    from sales_engine import build_funnel, _load_best_blueprint, _load_blueprint_by_title

    bp = _load_blueprint_by_title(input_text) or _load_best_blueprint()
    if not bp:
        return {"error": "Nenhum blueprint encontrado. Rode product_engine.py primeiro.", "output": ""}

    print(f"  Blueprint: {bp.get('idea_title','')} (score {bp.get('final_score',0)})")
    result = await build_funnel(bp)
    r = result.get("response", {})
    return {
        "output": (
            f"Funil: {r.get('product','')} | "
            f"Canal: {r.get('lead_capture','')} | "
            f"CTA: {r.get('main_cta','')} | "
            f"Custo: ~${result.get('total_cost',0):.4f}"
        ),
        **result,
    }


# ─── ROTA 7: Content Engine ───────────────────────────────────────────────────

async def rota_content(input_text: str) -> dict:
    print_step("Rota 7 — Content Engine (Angles → Hooks → Ideas → Posts → Scripts)", "🎯")
    from content_engine import build_content, _load_best_blueprint, _load_blueprint_by_title

    bp = _load_blueprint_by_title(input_text) or _load_best_blueprint()
    if not bp:
        return {"error": "Nenhum blueprint encontrado. Rode product_engine.py primeiro.", "output": ""}

    print(f"  Blueprint: {bp.get('idea_title','')} (score {bp.get('final_score',0)})")
    result = await build_content(bp)
    s = result.get("summary", {})
    return {
        "output": (
            f"Content: {result['idea_title']} | "
            f"{s.get('angles',0)} ângulos · {s.get('hooks',0)} ganchos · "
            f"{s.get('posts',0)} posts · {s.get('scripts',0)} roteiros"
        ),
        **result,
    }


# Notion via notion_logger.py


# ─── Salvar resultado local ───────────────────────────────────────────────────

def salvar_local(input_text: str, task_type: str, output: str):
    os.makedirs("outputs", exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = f"outputs/{task_type}_{ts}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "task_type": task_type,
            "input": input_text,
            "output": output,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 Salvo em: {fname}")


# ─── Orquestrador principal ───────────────────────────────────────────────────

async def orquestrar(input_text: str, task_type: Optional[str] = None) -> dict:
    print_header()
    print(f"\n  Input : {input_text[:80]}")

    tipo = task_type or detectar_tipo(input_text)
    print(f"  Rota  : {tipo.upper()}")

    try:
        if tipo == "research":
            result = await rota_research(input_text)
        elif tipo == "strategy":
            result = await rota_strategy(input_text)
        elif tipo == "execution":
            result = await rota_execution(input_text)
        elif tipo == "video":
            result = await rota_video(input_text)
        elif tipo == "scoring":
            result = await rota_scoring(input_text)
        elif tipo == "product":
            result = await rota_product(input_text)
        elif tipo == "content":
            result = await rota_content(input_text)
        elif tipo == "video_engine":
            result = await rota_video_engine(input_text)
        elif tipo == "sales_engine":
            result = await rota_sales_engine(input_text)
        else:
            result = {"error": f"tipo '{tipo}' desconhecido", "output": ""}
    except httpx.HTTPStatusError as e:
        result = {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}", "output": ""}
    except Exception as e:
        result = {"error": str(e), "output": ""}

    if "error" in result and result["error"]:
        print(f"\n  ✗ Erro: {result['error']}")
    else:
        output_text = result.get("output", "")
        print_result(f"Output — {tipo.upper()}", output_text)

        # salvar local
        salvar_local(input_text, tipo, output_text)

        # salvar Notion (se configurado)
        notion_url = await salvar_tarefa(input_text, tipo, output_text)
        if not notion_url:
            pass  # silencioso se não configurado

    print("\n" + "═" * 60 + "\n")
    return result


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    args = sys.argv[1:]
    task_type = None
    input_text = ""

    if "--tipo" in args:
        idx = args.index("--tipo")
        task_type = args[idx + 1] if idx + 1 < len(args) else None
        args = [a for i, a in enumerate(args) if i != idx and i != idx + 1]

    if args:
        input_text = " ".join(args)

    return input_text, task_type


async def main():
    input_text, task_type = parse_args()

    if not input_text:
        print_header()
        print("\n  Nenhum input detectado. Modo interativo.\n")
        print("  Exemplos:")
        print('    python orchestrator.py "Pesquise tendências de live commerce no Brasil"')
        print('    python orchestrator.py "Crie estratégia para produto digital de restaurante"')
        print('    python orchestrator.py "Gere copy de email de boas-vindas"')
        print('    python orchestrator.py "Crie vídeo de 30s para vender curso online" --tipo video')
        print('    python orchestrator.py "CFO Digital para restaurantes" --tipo scoring')
        print()
        try:
            input_text = input("  Digite a tarefa: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Saindo.")
            return

    if not input_text:
        print("  Nada a fazer.")
        return

    await orquestrar(input_text, task_type)


if __name__ == "__main__":
    asyncio.run(main())
