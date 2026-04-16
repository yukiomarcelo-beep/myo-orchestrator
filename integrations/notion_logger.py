"""
notion_logger.py — salva resultados no Notion de forma estruturada
Cria uma página por execução com seções por tarefa.

Requer no .env:
    NOTION_API_KEY=ntn_...
    NOTION_DATABASE_ID=id-do-seu-database   (recomendado)
    # ou
    NOTION_PAGE_ID=id-da-pagina-pai         (cria sub-páginas)
"""
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

# ── Security Bridge — DLP antes de enviar para Notion ─────────────────────────
try:
    from core.security_bridge import guard_output as _guard_output
    _SECURITY_ENABLED = True
except ImportError:
    _SECURITY_ENABLED = False
    def _guard_output(data, destination="notion"): return True, "OK"
# ───────────────────────────────────────────────────────────────────────────────

NOTION_API_KEY     = os.getenv("NOTION_API_KEY", "")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "")  # preferido
NOTION_PAGE_ID     = os.getenv("NOTION_PAGE_ID", "")      # fallback

NOTION_VERSION = "2022-06-28"
NOTION_URL     = "https://api.notion.com/v1"

# ícones por tipo de tarefa
ICONS = {
    "research":            "🔍",
    "strategy":            "🧠",
    "execution":           "⚡",
    "video":               "🎬",
    "agent":               "🤖",
    "scoring":             "🎯",
    "opportunity_scoring": "🎯",
    "blueprint":           "🏗️",
    "product_engine":      "🏗️",
    "content":             "🎯",
    "content_engine":      "🎯",
    "video_engine":        "🎬",
    "sales_engine":        "💰",
    "default":             "📋",
}

STATUS_COLORS = {
    "complete": "green",
    "running":  "yellow",
    "error":    "red",
    "refine":   "orange",
}


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _is_configured() -> bool:
    return bool(NOTION_API_KEY and "sua-chave" not in NOTION_API_KEY
                and (NOTION_DATABASE_ID or NOTION_PAGE_ID))


# ─── Blocos de conteúdo ───────────────────────────────────────────────────────

def _heading(text: str, level: int = 2) -> dict:
    tag = f"heading_{level}"
    return {"object": "block", "type": tag,
            tag: {"rich_text": [{"text": {"content": text[:2000]}}]}}

def _paragraph(text: str) -> dict:
    # Notion limita 2000 chars por bloco — dividir se necessário
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": text[:2000]}}]}}

def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}

def _callout(text: str, emoji: str = "💡") -> dict:
    return {
        "object": "block", "type": "callout",
        "callout": {
            "rich_text": [{"text": {"content": text[:2000]}}],
            "icon": {"type": "emoji", "emoji": emoji},
        }
    }

def _bullet(text: str) -> dict:
    return {
        "object": "block", "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"text": {"content": text[:2000]}}]},
    }

def _code_block(text: str) -> dict:
    return {
        "object": "block", "type": "code",
        "code": {
            "rich_text": [{"text": {"content": text[:2000]}}],
            "language": "plain text",
        }
    }

def _split_text_blocks(text: str, max_chars: int = 1800) -> list:
    """Quebra textos longos em múltiplos blocos de parágrafo."""
    blocks = []
    for i in range(0, len(text), max_chars):
        blocks.append(_paragraph(text[i:i + max_chars]))
    return blocks or [_paragraph("(sem conteúdo)")]


# ─── Construir blocos por tipo de resultado ───────────────────────────────────

def _blocks_para_research(output: str) -> list:
    return [
        _heading("Resultado da Pesquisa", 3),
        *_split_text_blocks(output),
    ]

def _blocks_para_strategy(output: str) -> list:
    return [
        _heading("Estratégia Gerada", 3),
        *_split_text_blocks(output),
    ]

def _blocks_para_execution(output: str) -> list:
    return [
        _heading("Output de Execução", 3),
        *_split_text_blocks(output),
    ]

def _blocks_para_video(output: str) -> list:
    blocks = [_heading("Roteiro e Variações", 3)]
    if "VARIAÇÕES:" in output:
        parts = output.split("VARIAÇÕES:", 1)
        blocks += [_heading("Roteiro Base", 3), *_split_text_blocks(parts[0])]
        blocks += [_divider(), _heading("Variações", 3), *_split_text_blocks(parts[1])]
    else:
        blocks += _split_text_blocks(output)
    return blocks

def _blocks_para_scoring(output: str) -> list:
    blocks = [_heading("Opportunity Score", 3)]
    try:
        data = json.loads(output) if isinstance(output, str) else output
        # score_opportunity() retorna {output: {...}, raw_scoring: {...}, ...}
        inner = data.get("output", data)
        raw   = data.get("raw_scoring", {})
        score = inner.get("final_score", "?")
        prio  = inner.get("priority", "?")
        rec   = inner.get("recommendation", "?")
        blocks.append(_callout(
            f"Score: {score}/100  |  Prioridade: {prio}  |  Recomendação: {rec}", "🎯"
        ))
        scores = raw.get("scores", {})
        if scores:
            blocks.append(_heading("Critérios", 3))
            for k, v in scores.items():
                nota = v.get("score", 0) if isinstance(v, dict) else v
                just = v.get("justificativa", "") if isinstance(v, dict) else ""
                blocks.append(_bullet(f"{k.replace('_', ' ').capitalize()}: {nota}/5 — {just}"))
        risks = inner.get("main_risks", [])
        if risks:
            blocks.append(_heading("Riscos", 3))
            for r in risks:
                blocks.append(_bullet(str(r)))
        next_step = inner.get("next_step", "")
        if next_step:
            blocks.append(_heading("Próximo passo", 3))
            blocks.append(_callout(next_step, "→"))
    except Exception:
        blocks += _split_text_blocks(str(output))
    return blocks

def _blocks_para_video_engine(output: str) -> list:
    blocks = [_heading("Video Engine", 3)]
    try:
        data = json.loads(output) if isinstance(output, str) else output
        sc   = data.get("selected", {})
        aud  = data.get("audio", {})
        vid  = data.get("video", {})
        var  = data.get("variations", {})

        n_agr = len(var.get("agressivas", []))
        n_ele = len(var.get("elegantes", []))
        blocks.append(_callout(
            f"Script ✓  |  Variações: {n_agr} agressivas + {n_ele} elegantes  |  "
            f"Áudio: {'✓' if aud.get('audio_file') else aud.get('error','⚠')}  |  "
            f"Vídeo: {vid.get('video_url') or vid.get('video_id') or vid.get('error','pendente')}",
            "🎬"
        ))
        if sc:
            blocks.append(_heading("Script selecionado", 3))
            blocks.append(_bullet(f"Hook: {sc.get('hook', sc.get('gancho',''))}"))
            blocks.append(_bullet(f"CTA: {sc.get('cta','')}"))
            rf = data.get("roteiro_final", "")
            if rf:
                blocks.extend(_split_text_blocks(rf))

        queue = data.get("queue", [])
        if queue:
            blocks.append(_heading("Distribution Queue", 3))
            for q in queue:
                blocks.append(_bullet(f"[{q.get('platform','')}] {q.get('status','')} — {q.get('caption','')[:60]}"))

        caption = data.get("caption", "")
        if caption:
            blocks.append(_callout(caption, "📲"))
    except Exception:
        blocks += _split_text_blocks(str(output))
    return blocks


def _blocks_para_content(output: str) -> list:
    blocks = [_heading("Content Engine", 3)]
    try:
        data = json.loads(output) if isinstance(output, str) else output
        s = data.get("summary", {})
        blocks.append(_callout(
            f"Ângulos: {s.get('angles',0)}  ·  Ganchos: {s.get('hooks',0)}  ·  "
            f"Ideias: {s.get('ideas',0)}  ·  Posts: {s.get('posts',0)}  ·  "
            f"Roteiros: {s.get('scripts',0)}", "🎯"
        ))
        angles = data.get("angles", [])
        if angles:
            blocks.append(_heading("Ângulos", 3))
            for a in angles:
                blocks.append(_bullet(f"[{a.get('tipo','')}] {a.get('titulo','')} — {a.get('premissa','')}"))
        hooks = data.get("hooks", [])
        if hooks:
            blocks.append(_heading("Top Ganchos", 3))
            for h in hooks[:10]:
                blocks.append(_bullet(str(h)))
        posts = data.get("posts", [])
        if posts:
            blocks.append(_heading("Posts", 3))
            for p in posts:
                blocks.append(_bullet(p.get("gancho", "")))
                blocks.extend(_split_text_blocks(p.get("desenvolvimento", "")[:400]))
                blocks.append(_bullet(f"CTA: {p.get('cta','')}"))
                blocks.append(_divider())
        scripts = data.get("scripts", [])
        if scripts:
            blocks.append(_heading("Roteiros", 3))
            for sc in scripts:
                blocks.append(_callout(
                    f"[{sc.get('tom','')}] {sc.get('duracao_estimada','')}\n"
                    f"Gancho: {sc.get('gancho','')}\n"
                    f"CTA: {sc.get('cta','')}", "🎬"
                ))
    except Exception:
        blocks += _split_text_blocks(str(output))
    return blocks


def _blocks_para_blueprint(output: str) -> list:
    blocks = [_heading("Product Blueprint", 3)]
    try:
        data = json.loads(output) if isinstance(output, str) else output
        bp   = data.get("blueprint", data)
        resp = data.get("response", {})

        if resp:
            blocks.append(_callout(
                f"Formato: {resp.get('best_initial_format','')}  |  "
                f"Ticket: {resp.get('entry_ticket','')}  |  "
                f"Nome: {resp.get('top_name','')}", "🏗️"
            ))

        s = bp.get("product_strategy", {})
        if s:
            blocks.append(_heading("Estratégia", 3))
            blocks.append(_bullet(f"Transformação: {s.get('transformation','')}"))
            blocks.append(_bullet(f"Mecanismo único: {s.get('unique_mechanism','')}"))
            blocks.append(_bullet(f"MVP: {s.get('mvp_recommendation','')}"))
            for obj in s.get("main_objections", []):
                blocks.append(_bullet(f"Objeção: {obj}"))

        o = bp.get("offer_design", {})
        if o:
            blocks.append(_heading("Oferta", 3))
            blocks.append(_bullet(f"Promessa: {o.get('main_promise','')}"))
            blocks.append(_bullet(f"Ticket entrada: {o.get('entry_ticket','')}"))
            blocks.append(_bullet(f"Low ticket: {o.get('low_ticket_version','')}"))
            blocks.append(_bullet(f"Premium: {o.get('premium_version','')}"))
            for d in o.get("deliverables", []):
                blocks.append(_bullet(f"Entregável: {d}"))

        n = bp.get("naming_options", {})
        if n:
            blocks.append(_heading("Nomes", 3))
            blocks.append(_callout(f"Top pick: {n.get('top_pick','')} — {n.get('top_pick_reason','')}", "✨"))
            for nm in n.get("names", [])[:5]:
                blocks.append(_bullet(f"[{nm.get('tom','')}] {nm.get('name','')} — {nm.get('justificativa','')}"))

        c = bp.get("copy_base", {})
        if c:
            blocks.append(_heading("Copy", 3))
            blocks.append(_bullet(f"Headline: {c.get('headline','')}"))
            blocks.append(_bullet(f"Sub: {c.get('subheadline','')}"))
            blocks.append(_bullet(f"Hook: {c.get('opening_hook','')}"))
            blocks.append(_bullet(f"CTA: {c.get('cta','')}"))
            for b in c.get("value_bullets", []):
                blocks.append(_bullet(str(b)))

        st = bp.get("product_structure", {})
        if st:
            blocks.append(_heading("Estrutura", 3))
            for m in st.get("modules", []):
                blocks.append(_bullet(f"{m.get('name','')} — {m.get('objective','')}"))

    except Exception:
        blocks += _split_text_blocks(str(output))
    return blocks


def _blocks_para_sales(output: str) -> list:
    blocks = [_heading("Sales Engine — Funil de Vendas", 3)]
    try:
        data = json.loads(output) if isinstance(output, str) else output
        o  = data.get("offer_refinement", {})
        lp = data.get("landing_page", {})
        ct = data.get("ctas", [])
        lc = data.get("lead_capture", {})
        sq = data.get("sequence", [])
        af = lp.get("above_fold", {})

        blocks.append(_callout(
            f"Headline: {o.get('refined_headline','')}  |  "
            f"Canal: {lc.get('lead_capture','')}  |  "
            f"CTAs: {len(ct)}  |  Sequência: {len(sq)} msgs", "💰"
        ))

        if o:
            blocks.append(_heading("Oferta Refinada", 3))
            blocks.append(_bullet(f"Promessa: {o.get('refined_promise','')}"))
            blocks.append(_bullet(f"Ângulo: {o.get('main_sale_angle','')}"))
            blocks.append(_bullet(f"Urgência: {o.get('urgency_element','')}"))
            blocks.append(_bullet(f"Garantia: {o.get('risk_reversal','')}"))
            blocks.append(_bullet(f"Preço âncora: {o.get('ideal_price_anchor','')}"))
            for v in o.get("value_stack", []):
                blocks.append(_bullet(f"✓ {v}"))

        if af:
            blocks.append(_heading("Landing Page — Above the Fold", 3))
            blocks.append(_bullet(f"Headline: {af.get('headline','')}"))
            blocks.append(_bullet(f"Sub: {af.get('subheadline','')}"))
            blocks.append(_bullet(f"CTA: {af.get('cta_button','')}"))

        if ct:
            blocks.append(_heading("CTAs", 3))
            for c in ct:
                blocks.append(_bullet(f"[{c.get('tom','')}] {c.get('button_text','')} — {c.get('context','')}"))

        if lc:
            blocks.append(_heading("Lead Capture", 3))
            blocks.append(_bullet(f"Canal: {lc.get('lead_capture','')}"))
            blocks.append(_bullet(f"Link: {lc.get('link','')}"))

        if sq:
            blocks.append(_heading("Sequência de Conversão", 3))
            for m in sq:
                blocks.append(_callout(
                    f"Msg {m.get('numero','')}: {m.get('nome','')} [{m.get('timing','')}]\n"
                    f"Assunto: {m.get('assunto','')}\n"
                    f"CTA: {m.get('cta','')}", "📨"
                ))
    except Exception:
        blocks += _split_text_blocks(str(output))
    return blocks


BLOCK_BUILDERS = {
    "research":            _blocks_para_research,
    "strategy":            _blocks_para_strategy,
    "execution":           _blocks_para_execution,
    "video":               _blocks_para_video,
    "scoring":             _blocks_para_scoring,
    "opportunity_scoring": _blocks_para_scoring,
    "blueprint":           _blocks_para_blueprint,
    "product_engine":      _blocks_para_blueprint,
    "content":             _blocks_para_content,
    "content_engine":      _blocks_para_content,
    "video_engine":        _blocks_para_video_engine,
    "sales_engine":        _blocks_para_sales,
}


# ─── Criar página no Database (estrutura com propriedades) ────────────────────

async def _criar_pagina_database(title: str, task_type: str,
                                  status: str, blocks: list) -> Optional[str]:
    icon = ICONS.get(task_type, ICONS["default"])
    color = STATUS_COLORS.get(status, "default")
    ts = datetime.now(timezone.utc).isoformat()

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "icon": {"type": "emoji", "emoji": icon},
        "properties": {
            "Name": {"title": [{"text": {"content": f"{icon} {title[:90]}"}}]},
            "Tipo": {"select": {"name": task_type.capitalize(), "color": color}},
            "Status": {"select": {"name": status.capitalize(), "color": color}},
            "Data": {"date": {"start": ts}},
        },
        "children": blocks[:100],  # Notion aceita até 100 blocos por request
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{NOTION_URL}/pages", json=payload, headers=_headers())
        resp.raise_for_status()
    return resp.json().get("url")


# ─── Criar sub-página (fallback se não houver database) ──────────────────────

async def _criar_subpagina(title: str, task_type: str, blocks: list) -> Optional[str]:
    icon = ICONS.get(task_type, ICONS["default"])

    payload = {
        "parent": {"page_id": NOTION_PAGE_ID},
        "icon": {"type": "emoji", "emoji": icon},
        "properties": {
            "title": {"title": [{"text": {"content": f"{icon} {title[:90]}"}}]},
        },
        "children": blocks[:100],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{NOTION_URL}/pages", json=payload, headers=_headers())
        resp.raise_for_status()
    return resp.json().get("url")


# ─── Adicionar blocos extras (quando > 100) ───────────────────────────────────

async def _append_blocks(page_id: str, blocks: list):
    """Adiciona blocos em batches de 100."""
    for i in range(0, len(blocks), 100):
        batch = blocks[i:i + 100]
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.patch(
                f"{NOTION_URL}/blocks/{page_id}/children",
                json={"children": batch},
                headers=_headers(),
            )
            resp.raise_for_status()


# ─── API pública ──────────────────────────────────────────────────────────────

async def salvar_tarefa(title: str, task_type: str, output: str,
                         status: str = "complete") -> Optional[str]:
    """
    Salva uma tarefa avulsa no Notion.
    Retorna a URL da página criada, ou None se não configurado.
    """
    if not _is_configured():
        return None

    # DLP scan antes de persistir no Notion
    ok, reason = _guard_output(output, destination="notion")
    if not ok:
        print(f"  [Security] OUTPUT BLOQUEADO → Notion: {reason}")
        output = f"[REDACTED — {reason}]"

    builder = BLOCK_BUILDERS.get(task_type, lambda x: _split_text_blocks(x))
    blocks = [
        _callout(f"Tipo: {task_type.upper()} | Status: {status} | {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                 ICONS.get(task_type, "📋")),
        _divider(),
        *builder(output),
    ]

    try:
        if NOTION_DATABASE_ID:
            url = await _criar_pagina_database(title, task_type, status, blocks)
        else:
            url = await _criar_subpagina(title, task_type, blocks)

        # adicionar blocos restantes se houver
        if url and len(blocks) > 100:
            page_id = url.split("-")[-1]
            await _append_blocks(page_id, blocks[100:])

        print(f"  📝 Notion: {url}")
        return url

    except Exception as e:
        print(f"  ⚠ Notion erro: {e}")
        return None


async def salvar_agente(objective: str, iterations: int, results: list,
                         status: str = "complete") -> Optional[str]:
    """
    Salva o resultado completo de uma execução do agente autônomo.
    Cria uma página com seções por tarefa.
    """
    if not _is_configured():
        return None

    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    blocks = [
        _callout(
            f"Objetivo: {objective[:200]}\n"
            f"Iterações: {iterations} | Tarefas: {len(results)} | Status: {status} | {ts}",
            "🤖"
        ),
        _divider(),
    ]

    for i, r in enumerate(results, 1):
        task_type = r.get("type", "execution")
        icon = ICONS.get(task_type, "📋")
        desc = r.get("description", "")[:100]
        output = r.get("output", "")

        blocks.append(_heading(f"{icon} Tarefa {i}: {desc}", 2))

        builder = BLOCK_BUILDERS.get(task_type, lambda x: _split_text_blocks(x))
        blocks.extend(builder(output))
        blocks.append(_divider())

    title = f"Agente: {objective[:70]}"

    try:
        if NOTION_DATABASE_ID:
            url = await _criar_pagina_database(title, "agent", status, blocks)
        else:
            url = await _criar_subpagina(title, "agent", blocks)

        if url and len(blocks) > 100:
            page_id = url.split("-")[-1]
            await _append_blocks(page_id, blocks[100:])

        print(f"  📝 Notion: {url}")
        return url

    except Exception as e:
        print(f"  ⚠ Notion erro: {e}")
        return None
