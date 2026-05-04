#!/usr/bin/env python3
"""
Performance Engine — Pipeline AI
Analisa resultados dos ativos publicados e alimenta o sistema com aprendizado.

Fluxo:
  Performance Input
  → Collect Metrics    (input)   — recebe dados de engajamento
  → Normalize Metrics  (lógica)  — calcula taxas de engajamento, clique e lead
  → Performance Score  (lógica)  — pontuação 0-100 + banda (alta/media/baixa)
  → Claude Insights    (Claude)  — por que performou, o que repetir, o que evitar
  → Save Performance   (local)   — persiste JSON + atualiza ranking
  → Update Memory      (lógica)  — salva ganchos/CTAs vencedores em memory_items.json
  → Send Recommendations         — exibe próximos conteúdos recomendados + Notion

Uso:
  python performance_engine.py --json '{"asset_type":"video","asset_id":12,...}'
  python performance_engine.py --title "CFO Digital" --views 8200 --likes 410 ...
  python performance_engine.py --ranking          # exibe ranking de todos os ativos
  python performance_engine.py                    # modo interativo
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
MEMORY_FILE = os.path.join(OUTPUTS_DIR, "memory_items.json")

# Pesos do performance score (somam 100)
SCORE_WEIGHTS = {
    "engagement_rate": 0.40,
    "click_rate": 0.30,
    "lead_rate": 0.30,
}


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
        "cost": round((u.get("input_tokens", 0) * 3e-6) + (u.get("output_tokens", 0) * 15e-6), 6),
    }


# ─── Prompts ──────────────────────────────────────────────────────────────────


def _p_insights(metrics: dict) -> str:
    asset_context = ""
    if metrics.get("gancho"):
        asset_context += f"\nGancho usado: {metrics['gancho']}"
    if metrics.get("angulo"):
        asset_context += f"\nÂngulo: {metrics['angulo']}"
    if metrics.get("cta"):
        asset_context += f"\nCTA: {metrics['cta']}"
    if metrics.get("formato"):
        asset_context += f"\nFormato: {metrics['formato']}"

    return f"""Você é um especialista em performance de marketing digital.

Analise a performance deste ativo:

Tipo: {metrics.get('asset_type', '')}
Plataforma: {metrics.get('platform', '')}
Views: {metrics.get('views', 0):,}
Likes: {metrics.get('likes', 0):,}
Comentários: {metrics.get('comments', 0):,}
Saves: {metrics.get('saves', 0):,}
Shares: {metrics.get('shares', 0):,}
Clicks: {metrics.get('clicks', 0):,}
Leads: {metrics.get('leads', 0):,}

Taxas calculadas:
Engajamento: {metrics.get('engagement_rate', 0)*100:.2f}%
Clique: {metrics.get('click_rate', 0)*100:.2f}%
Lead: {metrics.get('lead_rate', 0)*100:.2f}%

Performance score: {metrics.get('performance_score', 0)}/100 ({metrics.get('performance_band', '')})
{asset_context}

Com base nesses dados, responda:
1. Por que esse ativo performou assim (fatores que explicam o resultado)
2. O que parece ter funcionado (elementos que contribuíram positivamente)
3. O que deve ser repetido (padrões a replicar nos próximos conteúdos)
4. O que deve ser evitado (o que provavelmente prejudicou ou não adicionou)
5. Qual próximo conteúdo produzir (recomendação específica e acionável)

Responda APENAS em JSON válido:

{{
  "why_it_performed": "",
  "what_worked": [],
  "repeat": [],
  "avoid": [],
  "next_content_recommendation": "",
  "memory_worthy": true,
  "memory_tags": []
}}"""


# ─── Etapas do pipeline ───────────────────────────────────────────────────────


def _normalize(raw: dict) -> dict:
    """Node 03 — calcula engagement_rate, click_rate, lead_rate."""
    views = raw.get("views", 0) or 0
    likes = raw.get("likes", 0) or 0
    comments = raw.get("comments", 0) or 0
    saves = raw.get("saves", 0) or 0
    shares = raw.get("shares", 0) or 0
    clicks = raw.get("clicks", 0) or 0
    leads = raw.get("leads", 0) or 0

    engagement_rate = ((likes + comments + saves + shares) / views) if views > 0 else 0.0
    click_rate = (clicks / views) if views > 0 else 0.0
    lead_rate = (leads / views) if views > 0 else 0.0

    return {
        **raw,
        "engagement_rate": round(engagement_rate, 6),
        "click_rate": round(click_rate, 6),
        "lead_rate": round(lead_rate, 6),
    }


def _score(metrics: dict) -> dict:
    """Node 04 — calcula performance_score (0-100) e performance_band."""
    engagement = metrics.get("engagement_rate", 0) * 100
    click_rate = metrics.get("click_rate", 0) * 100
    lead_rate = metrics.get("lead_rate", 0) * 100

    score = (
        engagement * SCORE_WEIGHTS["engagement_rate"]
        + click_rate * SCORE_WEIGHTS["click_rate"]
        + lead_rate * SCORE_WEIGHTS["lead_rate"]
    )
    score = round(score)

    if score >= 70:
        band = "alta"
    elif score >= 40:
        band = "media"
    else:
        band = "baixa"

    return {
        **metrics,
        "performance_score": score,
        "performance_band": band,
    }


def _update_memory(metrics: dict, insights: dict):
    """Node 07 — salva padrões vencedores em memory_items.json."""
    if not insights.get("memory_worthy", False):
        return

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    items = []
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, encoding="utf-8") as f:
                items = json.load(f)
        except Exception:
            items = []

    entry = {
        "timestamp": metrics.get("timestamp", time.strftime("%Y%m%d_%H%M%S")),
        "asset_type": metrics.get("asset_type", ""),
        "platform": metrics.get("platform", ""),
        "performance_score": metrics.get("performance_score", 0),
        "performance_band": metrics.get("performance_band", ""),
        "gancho": metrics.get("gancho", ""),
        "angulo": metrics.get("angulo", ""),
        "cta": metrics.get("cta", ""),
        "formato": metrics.get("formato", ""),
        "what_worked": insights.get("what_worked", []),
        "repeat": insights.get("repeat", []),
        "avoid": insights.get("avoid", []),
        "tags": insights.get("memory_tags", []),
    }

    # remove duplicata por gancho + platform
    items = [
        i
        for i in items
        if not (i.get("gancho") == entry["gancho"] and i.get("platform") == entry["platform"])
    ]

    items.append(entry)
    # mantém apenas os 50 mais recentes com banda alta/media
    items_sorted = sorted(
        [i for i in items if i.get("performance_band") in ("alta", "media")],
        key=lambda x: x.get("performance_score", 0),
        reverse=True,
    )[:50]

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(items_sorted, f, ensure_ascii=False, indent=2)

    print(f"  Memória atualizada: {len(items_sorted)} itens em memory_items.json")


# ─── Fluxo principal ──────────────────────────────────────────────────────────


async def analyze_performance(raw_input: dict) -> dict:
    print(
        f"\n  Analisando: [{raw_input.get('asset_type','?')}] "
        f"id={raw_input.get('asset_id','?')} · {raw_input.get('platform','?')}"
    )
    print("  " + "─" * 56)

    # [1] Normalize
    print("  [1/5] Normalizing metrics...")
    metrics = _normalize(raw_input)
    print(
        f"        ✓ engagement {metrics['engagement_rate']*100:.2f}% · "
        f"click {metrics['click_rate']*100:.2f}% · "
        f"lead {metrics['lead_rate']*100:.2f}%"
    )

    # [2] Score
    print("  [2/5] Performance Scoring...")
    metrics = _score(metrics)
    print(
        f"        ✓ score {metrics['performance_score']}/100 → banda {metrics['performance_band'].upper()}"
    )

    # [3] Claude Insights
    print("  [3/5] Claude Insights...")
    metrics["timestamp"] = time.strftime("%Y%m%d_%H%M%S")
    insights_raw, meta = await _claude(_p_insights(metrics))
    insights = insights_raw if isinstance(insights_raw, dict) else {}
    print(f"        ✓ {meta['latency_ms']}ms · ${meta['cost']:.4f}")

    # [4] Save Performance
    print("  [4/5] Saving performance record...")
    result = {
        "metrics": metrics,
        "insights": insights,
        "cost": meta["cost"],
        "timestamp": metrics["timestamp"],
        "response": {
            "status": "success",
            "asset_type": metrics.get("asset_type", ""),
            "asset_id": metrics.get("asset_id", ""),
            "platform": metrics.get("platform", ""),
            "performance_score": metrics["performance_score"],
            "performance_band": metrics["performance_band"],
            "next_content": insights.get("next_content_recommendation", ""),
        },
    }
    fname = _salvar_local(result)
    print(f"        ✓ Salvo em {fname}")

    # [5] Update Memory + Recommendations
    print("  [5/5] Updating memory & sending recommendations...")
    _update_memory(metrics, insights)

    _imprimir(result)
    await _salvar_notion(result)
    _atualizar_dashboard()

    return result


# ─── Ranking ──────────────────────────────────────────────────────────────────


def show_ranking():
    files = sorted(glob.glob(f"{OUTPUTS_DIR}/performance_*.json"), reverse=True)
    if not files:
        print("  Nenhum registro de performance encontrado.")
        print("  Rode: python performance_engine.py --json '{...}'")
        return

    records = []
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            m = data.get("metrics", {})
            records.append(m)
        except Exception:
            pass

    records.sort(key=lambda x: x.get("performance_score", 0), reverse=True)

    BAND_COLOR = {"alta": "★★★", "media": "★★☆", "baixa": "★☆☆"}

    print("\n" + "═" * 66)
    print("  PERFORMANCE RANKING — Pipeline AI")
    print("═" * 66)
    print(f"  {'#':<3} {'Tipo':<10} {'Plataforma':<13} {'Score':<7} {'Banda':<8} {'Views':>7}")
    print("  " + "─" * 60)
    for i, m in enumerate(records[:20], 1):
        band = m.get("performance_band", "baixa")
        stars = BAND_COLOR.get(band, "☆☆☆")
        gancho = m.get("gancho", "")[:30]
        print(
            f"  {i:<3} {m.get('asset_type','?'):<10} "
            f"{m.get('platform','?'):<13} "
            f"{m.get('performance_score',0):<7} "
            f"{stars:<8} "
            f"{m.get('views',0):>7,}"
        )
        if gancho:
            print(f"      Gancho: {gancho}")
    print("═" * 66)
    print(f"\n  Total de registros: {len(records)}")

    # Mostra memória acumulada
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, encoding="utf-8") as f:
            mem = json.load(f)
        print(f"  Padrões vencedores em memória: {len(mem)}")
        if mem:
            print("\n  ─── Top padrões (o que repetir) ─────────────────────────")
            for item in mem[:5]:
                print(
                    f"  [{item.get('performance_score',0):>3}/100] "
                    f"{item.get('asset_type','?')} · {item.get('platform','?')}"
                )
                for r in item.get("repeat", [])[:2]:
                    print(f"         → {r}")
    print()


# ─── Persistência ─────────────────────────────────────────────────────────────


def _salvar_local(result: dict) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    m = result["metrics"]
    slug = f"{m.get('asset_type','asset')}_{m.get('platform','?')}_{m.get('asset_id','0')}"
    fname = f"{OUTPUTS_DIR}/performance_{slug}_{result['timestamp']}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return fname


async def _salvar_notion(result: dict):
    try:
        from integrations.notion_logger import salvar_tarefa

        m = result["metrics"]
        ins = result.get("insights", {})
        body = (
            f"Score: {m.get('performance_score',0)}/100 ({m.get('performance_band','')})\n"
            f"Views: {m.get('views',0):,} · Likes: {m.get('likes',0):,} · "
            f"Comments: {m.get('comments',0):,} · Leads: {m.get('leads',0):,}\n\n"
            f"O que funcionou:\n"
            + "\n".join(f"• {w}" for w in ins.get("what_worked", []))
            + f"\n\nPróximo conteúdo:\n{ins.get('next_content_recommendation', '')}"
        )
        await salvar_tarefa(
            f"Performance: {m.get('asset_type','')} · {m.get('platform','')} · score {m.get('performance_score',0)}",
            "performance_engine",
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
        print("  Dashboard atualizado.")
    except Exception as e:
        print(f"  Dashboard: {e}")


# ─── Display terminal ─────────────────────────────────────────────────────────


def _imprimir(result: dict):
    m = result["metrics"]
    ins = result.get("insights", {})

    BAND_LABEL = {"alta": "ALTA  ★★★", "media": "MÉDIA ★★☆", "baixa": "BAIXA ★☆☆"}

    print("\n" + "═" * 62)
    print(f"  PERFORMANCE ENGINE — {m.get('asset_type','?').upper()} · {m.get('platform','?')}")
    print("═" * 62)

    print(f"\n  Score       : {m['performance_score']}/100")
    print(f"  Banda       : {BAND_LABEL.get(m['performance_band'], m['performance_band'])}")
    print(f"\n  Views       : {m.get('views',0):>8,}")
    print(f"  Likes       : {m.get('likes',0):>8,}  ({m.get('engagement_rate',0)*100:.2f}% eng)")
    print(f"  Comments    : {m.get('comments',0):>8,}")
    print(f"  Saves       : {m.get('saves',0):>8,}")
    print(f"  Shares      : {m.get('shares',0):>8,}")
    print(f"  Clicks      : {m.get('clicks',0):>8,}  ({m.get('click_rate',0)*100:.2f}% CTR)")
    print(f"  Leads       : {m.get('leads',0):>8,}  ({m.get('lead_rate',0)*100:.2f}% conv)")

    if ins.get("why_it_performed"):
        print("\n  ─── Por que performou assim ─────────────────────────────")
        text = ins["why_it_performed"]
        for line in _wrap(text, 56):
            print(f"  {line}")

    if ins.get("what_worked"):
        print("\n  ─── O que funcionou ─────────────────────────────────────")
        for w in ins["what_worked"]:
            print(f"  ✓ {w}")

    if ins.get("repeat"):
        print("\n  ─── Repetir nos próximos conteúdos ──────────────────────")
        for r in ins["repeat"]:
            print(f"  → {r}")

    if ins.get("avoid"):
        print("\n  ─── Evitar ──────────────────────────────────────────────")
        for a in ins["avoid"]:
            print(f"  ✗ {a}")

    if ins.get("next_content_recommendation"):
        print("\n  ─── Próximo conteúdo recomendado ────────────────────────")
        for line in _wrap(ins["next_content_recommendation"], 56):
            print(f"  {line}")

    print(f"\n  Custo análise : ~${result.get('cost', 0):.4f}")
    print("═" * 62 + "\n")

    print("  Response (Node 08):")
    print(json.dumps(result["response"], ensure_ascii=False, indent=2))
    print()


def _wrap(text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            if line:
                lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        lines.append(line)
    return lines or [""]


# ─── Modo interativo ──────────────────────────────────────────────────────────


def _interactive_input() -> dict:
    print("\n  ─── Performance Engine — Entrada de dados ───────────────")
    asset_type = input("  Tipo de ativo (video/post/reel/story/email): ").strip() or "video"
    platform = input("  Plataforma (instagram/youtube/linkedin/email): ").strip() or "instagram"
    asset_id = input("  ID do ativo (número ou nome): ").strip() or "1"
    views = int(input("  Views      : ").strip() or 0)
    likes = int(input("  Likes      : ").strip() or 0)
    comments = int(input("  Comentários: ").strip() or 0)
    saves = int(input("  Saves      : ").strip() or 0)
    shares = int(input("  Shares     : ").strip() or 0)
    clicks = int(input("  Clicks     : ").strip() or 0)
    leads = int(input("  Leads      : ").strip() or 0)
    gancho = input("  Gancho usado (opcional): ").strip()
    angulo = input("  Ângulo (opcional)       : ").strip()
    cta = input("  CTA usado (opcional)    : ").strip()
    formato = input("  Formato (carrossel/reel/post/stories): ").strip()

    data = {
        "asset_type": asset_type,
        "asset_id": asset_id,
        "platform": platform,
        "views": views,
        "likes": likes,
        "comments": comments,
        "saves": saves,
        "shares": shares,
        "clicks": clicks,
        "leads": leads,
    }
    if gancho:
        data["gancho"] = gancho
    if angulo:
        data["angulo"] = angulo
    if cta:
        data["cta"] = cta
    if formato:
        data["formato"] = formato
    return data


# ─── CLI ──────────────────────────────────────────────────────────────────────


async def main():
    args = sys.argv[1:]

    # --ranking: exibe ranking e sai
    if "--ranking" in args:
        show_ranking()
        return

    raw_input: Optional[dict] = None

    # --json: input direto
    if "--json" in args:
        idx = args.index("--json")
        raw_input = json.loads(args[idx + 1])

    # --title + flags individuais
    elif "--title" in args:
        idx = args.index("--title")
        title = args[idx + 1] if idx + 1 < len(args) else ""

        def _arg(flag: str, default=0):
            if flag in args:
                i = args.index(flag)
                return args[i + 1] if i + 1 < len(args) else default
            return default

        raw_input = {
            "asset_type": str(_arg("--type", "video")),
            "asset_id": title,
            "platform": str(_arg("--platform", "instagram")),
            "views": int(_arg("--views", 0)),
            "likes": int(_arg("--likes", 0)),
            "comments": int(_arg("--comments", 0)),
            "saves": int(_arg("--saves", 0)),
            "shares": int(_arg("--shares", 0)),
            "clicks": int(_arg("--clicks", 0)),
            "leads": int(_arg("--leads", 0)),
        }

    # sem argumentos: modo interativo
    else:
        raw_input = _interactive_input()

    if not raw_input:
        print("  Nenhum dado de entrada. Use --json, --title ou modo interativo.")
        return

    await analyze_performance(raw_input)


if __name__ == "__main__":
    asyncio.run(main())
