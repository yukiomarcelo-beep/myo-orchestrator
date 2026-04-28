#!/usr/bin/env python3
"""
Ads Engine — AI Business OS
Transforma conteúdo orgânico validado em campanhas de tráfego pago otimizadas.

Fluxo:
  Ads Input
  → Select Winning Content  (lógica)  — só entra se performance ≥70
  → Ad Angle Generator      (Claude)  — 5 ângulos: dor, erro, oportunidade, autoridade, urgência
  → Ad Copy Generator       (GPT)     — 5 copies por ângulo, formato direto e agressivo
  → Creative Generator      (lógica)  — combinações de vídeo + hook + texto
  → Campaign Setup          (lógica)  — estrutura Campanha > Conjunto > Anúncios
  → Testing Engine          (lógica)  — 3 criativos × 3 copies × 2 públicos = 18 combinações
  → Performance Tracking    (local)   — ROAS, CPC, CPL, CPA
  → Optimization Engine     (lógica)  — ROAS >2 escala / 1-2 otimiza / <1 pausa
  → Scaling                 (Claude)  — plano de escala/otimização/encerramento

Regra fundamental: validar orgânico ANTES de escalar com ads.

Uso:
  python ads_engine.py                               # auto-carrega melhor conteúdo validado
  python ads_engine.py --title "CFO Digital"         # foca em produto específico
  python ads_engine.py --json '{"idea_title":"...", "performance_score":85, ...}'
  python ads_engine.py --track --campaign C001 --clicks 340 --leads 28 --cost 180 --sales 6
  python ads_engine.py --optimize                    # roda otimização em todas as campanhas
  python ads_engine.py --ranking                     # ranking de campanhas
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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"
GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4o")
OUTPUTS_DIR = "outputs"
ADS_FILE = os.path.join(OUTPUTS_DIR, "ads_campaigns.json")

PERFORMANCE_THRESHOLD = 70  # score mínimo para rodar ads

AD_ANGLES = ["dor_direta", "erro", "oportunidade", "autoridade", "urgencia"]

AUDIENCES = [
    {"tipo": "interesse", "desc": "Interesse direto no nicho"},
    {"tipo": "lookalike", "desc": "Lookalike de seguidores/clientes"},
]

BUDGETS = {
    "teste": {"diario": 30, "desc": "Fase de testes (mín. 3 dias)"},
    "escala": {"diario": 150, "desc": "Escala conservadora"},
    "agressivo": {"diario": 500, "desc": "Escala agressiva (ROAS >3 confirmado)"},
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
    raw = "\n".join(
        i.get("content", [{}])[0].get("text", "")
        for i in data.get("output", [])
        if i.get("type") == "message"
    )
    u = data.get("usage", {})
    return _parse_json(raw), {
        "latency_ms": int((time.time() - t0) * 1000),
        "cost": round((u.get("input_tokens", 0) * 2.5e-6) + (u.get("output_tokens", 0) * 10e-6), 6),
    }


# ─── Prompts ──────────────────────────────────────────────────────────────────


def _p_angles(content: dict) -> str:
    return f"""Você é um especialista em performance marketing e tráfego pago.

Conteúdo orgânico validado:
Produto: {content.get('idea_title', '')}
Performance score: {content.get('performance_score', 0)}/100
Validation score:  {content.get('validation_score', 0)}/100
Gancho original:   {content.get('top_hook', '')}
Plataforma:        {content.get('platform', 'instagram')}

Crie 5 ângulos de anúncio de alta conversão — um de cada tipo:

1. dor_direta   — ataca diretamente a dor mais forte do público
2. erro         — aponta um erro que o público comete sem perceber
3. oportunidade — mostra o que o público está perdendo agora
4. autoridade   — prova social, resultado, credibilidade
5. urgencia     — escassez real ou janela de oportunidade limitada

Para cada ângulo:
- tipo (um dos 5 acima)
- titulo_anuncio (headline do ad, máximo 8 palavras, impactante)
- gancho_video (primeira linha/cena do criativo, máximo 2 segundos)
- promessa (o que o anúncio promete, específico e mensurável)
- cta (call-to-action direto)
- tom (agressivo / provocador / aspiracional / direto / urgente)

Responda APENAS em JSON válido:

{{
  "angles": [
    {{
      "tipo": "",
      "titulo_anuncio": "",
      "gancho_video": "",
      "promessa": "",
      "cta": "",
      "tom": ""
    }}
  ]
}}"""


def _p_copies(content: dict, angles: list) -> str:
    top_angles = json.dumps(
        [
            {"tipo": a["tipo"], "titulo": a["titulo_anuncio"], "promessa": a["promessa"]}
            for a in angles[:5]
        ],
        ensure_ascii=False,
    )
    return f"""Crie 5 copies de anúncio de alta conversão para o produto "{content.get('idea_title','')}".

Ângulos disponíveis:
{top_angles}

Regras para os copies:
- Formato curto e direto (máximo 4 linhas)
- Tom agressivo e sem enrolação
- Começa com o problema ou resultado, nunca com "Você"
- Cada copy usa um ângulo diferente
- Termina com CTA claro e sem atrito

Para cada copy:
- angulo_usado (tipo do ângulo)
- texto_completo (copy pronto para usar no ad)
- plataformas (onde usar: feed, stories, reels, youtube)
- variante (A, B, C, D ou E)

Responda APENAS em JSON válido:

{{
  "copies": [
    {{
      "variante": "A",
      "angulo_usado": "",
      "texto_completo": "",
      "plataformas": []
    }}
  ]
}}"""


def _p_optimization(campaign: dict) -> str:
    roas = campaign.get("roas", 0)
    cpl = campaign.get("cpl", 0)
    cpa = campaign.get("cpa", 0)
    status = campaign.get("optimization_status", "")
    return f"""Você é um especialista em media buying e performance marketing.

Campanha: {campaign.get('idea_title', '')}
ID: {campaign.get('campaign_id', '')}

Métricas atuais:
- Clicks   : {campaign.get('clicks', 0):,}
- Leads    : {campaign.get('leads', 0):,}
- Vendas   : {campaign.get('sales', 0):,}
- Custo    : R$ {campaign.get('cost', 0):,.2f}
- Receita  : R$ {campaign.get('revenue', 0):,.2f}
- ROAS     : {roas:.2f}x
- CPC      : R$ {campaign.get('cpc', 0):.2f}
- CPL      : R$ {cpl:.2f}
- CPA      : R$ {cpa:.2f}
- Status   : {status.upper()}

Analise e forneça:
1. Diagnóstico do que está acontecendo
2. Causa raiz do problema (ou do sucesso)
3. Ação imediata (hoje)
4. Ajuste para amanhã
5. Meta para os próximos 7 dias

Responda APENAS em JSON válido:

{{
  "diagnostico": "",
  "causa_raiz": "",
  "acao_imediata": "",
  "ajuste_amanhã": "",
  "meta_7_dias": "",
  "recomendacao_budget": "",
  "criativo_vencedor": "",
  "copy_vencedor": ""
}}"""


# ─── Nós do pipeline ──────────────────────────────────────────────────────────


def _select_winning_content(raw: dict) -> Optional[dict]:
    """Node 02 — filtro de qualidade: só entra conteúdo com score ≥ 70."""
    score = raw.get("performance_score", 0)
    if score >= PERFORMANCE_THRESHOLD:
        return raw
    return None


def _build_creatives(content: dict, angles: list, copies: list) -> list:
    """Node 05 — combinações de criativo (vídeo/imagem + hook + texto)."""
    top_angles = angles[:3]
    top_copies = copies[:3]
    creatives = []

    for i, angle in enumerate(top_angles, 1):
        copy = top_copies[i - 1] if i - 1 < len(top_copies) else top_copies[0] if top_copies else {}
        creatives.append(
            {
                "id": f"CRV-{i:02d}",
                "tipo": "video" if content.get("top_video_url") else "imagem_estatica",
                "angulo": angle.get("tipo", ""),
                "gancho": angle.get("gancho_video", ""),
                "titulo": angle.get("titulo_anuncio", ""),
                "copy": copy.get("texto_completo", ""),
                "cta": angle.get("cta", ""),
                "plataformas": copy.get("plataformas", ["feed", "stories"]),
                "status": "pronto_para_subir",
            }
        )

    return creatives


def _setup_campaign(content: dict, creatives: list, copies: list) -> dict:
    """Node 06 — estrutura da campanha."""
    ts = time.strftime("%Y%m%d%H%M%S")
    campaign_id = f"C{ts[-6:]}"
    title = content.get("idea_title", "").replace(" ", "_")[:20]

    ad_sets = []
    for audience in AUDIENCES:
        ads = []
        for criativo in creatives[:3]:
            for copy in copies[:3]:
                ads.append(
                    {
                        "ad_id": f"{campaign_id}-{audience['tipo'][:3].upper()}-{criativo['id']}-V{copy.get('variante','A')}",
                        "criativo": criativo["id"],
                        "copy": copy.get("variante", "A"),
                        "titulo": criativo["titulo"],
                        "texto": copy.get("texto_completo", "")[:100],
                        "cta": criativo["cta"],
                        "status": "aguardando_subida",
                    }
                )
        ad_sets.append(
            {
                "adset_id": f"{campaign_id}-AS-{audience['tipo'].upper()}",
                "publico": audience["tipo"],
                "descricao": audience["desc"],
                "budget_dia": BUDGETS["teste"]["diario"],
                "ads": ads,
            }
        )

    total_ads = sum(len(a["ads"]) for a in ad_sets)

    return {
        "campaign_id": campaign_id,
        "idea_title": content.get("idea_title", ""),
        "objetivo": "conversao",
        "fase": "teste",
        "budget_total": BUDGETS["teste"]["diario"] * len(AUDIENCES),
        "duracao_dias": 3,
        "plataforma": "meta_ads",
        "ad_sets": ad_sets,
        "total_ads": total_ads,
        "timestamp": time.strftime("%Y%m%d_%H%M%S"),
        # métricas (preenchidas depois via --track)
        "clicks": 0,
        "leads": 0,
        "sales": 0,
        "cost": 0.0,
        "revenue": 0.0,
        "roas": 0.0,
        "cpc": 0.0,
        "cpl": 0.0,
        "cpa": 0.0,
        "optimization_status": "aguardando_dados",
        "optimization_insights": {},
    }


def _optimization_status(roas: float) -> tuple[str, str, str]:
    """Node 09 — ROAS >2 escala / 1-2 otimiza / <1 pausa."""
    if roas >= 2.0:
        return "escalar", "🚀", "#10b981"
    elif roas >= 1.0:
        return "otimizar", "🔧", "#f59e0b"
    else:
        return "pausar", "🛑", "#ef4444"


def _compute_kpis(campaign: dict) -> dict:
    """Recalcula KPIs a partir dos dados brutos."""
    clicks = campaign.get("clicks", 0) or 0
    leads = campaign.get("leads", 0) or 0
    sales = campaign.get("sales", 0) or 0
    cost = campaign.get("cost", 0.0) or 0.0
    revenue = campaign.get("revenue", 0.0) or 0.0

    return {
        **campaign,
        "roas": round(revenue / cost, 2) if cost > 0 else 0.0,
        "cpc": round(cost / clicks, 2) if clicks > 0 else 0.0,
        "cpl": round(cost / leads, 2) if leads > 0 else 0.0,
        "cpa": round(cost / sales, 2) if sales > 0 else 0.0,
    }


# ─── CRM store de campanhas ───────────────────────────────────────────────────


def _load_campaigns() -> list:
    if not os.path.exists(ADS_FILE):
        return []
    try:
        with open(ADS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_campaigns(campaigns: list):
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    with open(ADS_FILE, "w", encoding="utf-8") as f:
        json.dump(campaigns, f, ensure_ascii=False, indent=2)


# ─── Fluxo principal ──────────────────────────────────────────────────────────


async def create_campaign(raw_input: dict) -> dict:
    title = raw_input.get("idea_title", "?")
    print(f"\n  Ads Engine: {title[:60]}")
    print(
        f"  Performance: {raw_input.get('performance_score',0)} · "
        f"Validation: {raw_input.get('validation_score',0)}"
    )
    print("  " + "─" * 56)

    # [1] Select Winning Content
    print("  [1/8] Selecting winning content...")
    content = _select_winning_content(raw_input)
    if not content:
        score = raw_input.get("performance_score", 0)
        print(f"  │  ✗ Score {score} < {PERFORMANCE_THRESHOLD} — conteúdo não apto para ads")
        print("  │    Valide organicamente primeiro. Rode performance_engine.py.")
        return {
            "skipped": True,
            "reason": f"score {score} abaixo do mínimo {PERFORMANCE_THRESHOLD}",
        }
    print(f"  │  ✓ Conteúdo aprovado (score {content.get('performance_score',0)})")

    total_cost = 0.0

    # [2] Ad Angle Generator — Claude
    print("  [2/8] Ad Angle Generator via Claude...")
    angles_raw, m1 = await _claude(_p_angles(content))
    angles = angles_raw.get("angles", []) if isinstance(angles_raw, dict) else []
    total_cost += m1["cost"]
    print(f"  │  ✓ {len(angles)} ângulos · {m1['latency_ms']}ms · ${m1['cost']:.4f}")

    # [3] Ad Copy Generator — GPT
    print("  [3/8] Ad Copy Generator via GPT...")
    copies_raw, m2 = await _gpt(_p_copies(content, angles))
    copies = copies_raw.get("copies", []) if isinstance(copies_raw, dict) else []
    total_cost += m2["cost"]
    print(f"  │  ✓ {len(copies)} copies · {m2['latency_ms']}ms · ${m2['cost']:.4f}")

    # [4] Creative Generator
    print("  [4/8] Creative Generator...")
    creatives = _build_creatives(content, angles, copies)
    print(f"  │  ✓ {len(creatives)} criativos gerados")

    # [5] Campaign Setup
    print("  [5/8] Campaign Setup...")
    campaign = _setup_campaign(content, creatives, copies)
    print(
        f"  │  ✓ Campanha {campaign['campaign_id']} · {campaign['total_ads']} anúncios · "
        f"R${campaign['budget_total']}/dia"
    )

    # [6] Testing Engine
    print("  [6/8] Testing Engine (3 criativos × 3 copies × 2 públicos)...")
    n_combos = len(creatives[:3]) * len(copies[:3]) * len(AUDIENCES)
    print(f"  │  ✓ {n_combos} combinações de teste prontas")

    # [7] Save
    print("  [7/8] Saving campaign...")
    campaign["angles"] = angles
    campaign["copies"] = copies
    campaign["creatives"] = creatives
    campaign["ad_cost"] = total_cost

    campaigns = _load_campaigns()
    # remove campanha anterior com mesmo título (mantém a mais recente)
    campaigns = [c for c in campaigns if c.get("idea_title") != title]
    campaigns.append(campaign)
    _save_campaigns(campaigns)

    # [8] Individual JSON
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    slug = title.replace(" ", "_")[:25]
    fname = f"{OUTPUTS_DIR}/ads_{slug}_{campaign['timestamp']}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(campaign, f, ensure_ascii=False, indent=2)
    print(f"  │  ✓ Salvo em {fname}")

    print("  [8/8] Finalizing...")
    result = {**campaign, "total_cost": total_cost}
    _imprimir(result)
    await _salvar_notion(result)
    _atualizar_dashboard()

    return result


# ─── Track de performance ─────────────────────────────────────────────────────


def track_performance(
    campaign_id: str,
    clicks: int,
    leads: int,
    sales: int,
    cost: float,
    revenue: float,
):
    campaigns = _load_campaigns()
    target = next((c for c in campaigns if c.get("campaign_id") == campaign_id), None)
    if not target:
        print(f"  Campanha {campaign_id} não encontrada. IDs disponíveis:")
        for c in campaigns:
            print(f"    {c.get('campaign_id','')} — {c.get('idea_title','')}")
        return

    target.update(
        {
            "clicks": (target.get("clicks", 0) or 0) + clicks,
            "leads": (target.get("leads", 0) or 0) + leads,
            "sales": (target.get("sales", 0) or 0) + sales,
            "cost": round((target.get("cost", 0) or 0) + cost, 2),
            "revenue": round((target.get("revenue", 0) or 0) + revenue, 2),
        }
    )
    target = _compute_kpis(target)
    status, icon, _ = _optimization_status(target["roas"])
    target["optimization_status"] = status

    idx = next(i for i, c in enumerate(campaigns) if c.get("campaign_id") == campaign_id)
    campaigns[idx] = target
    _save_campaigns(campaigns)

    print(f"\n  Campanha {campaign_id} ({target['idea_title']}) atualizada:")
    print(
        f"  ROAS: {target['roas']:.2f}x · CPC: R${target['cpc']:.2f} · "
        f"CPL: R${target['cpl']:.2f} · CPA: R${target['cpa']:.2f}"
    )
    print(f"  {icon} Status: {status.upper()}")
    _atualizar_dashboard()


# ─── Optimization run ─────────────────────────────────────────────────────────


async def run_optimization():
    campaigns = _load_campaigns()
    active = [c for c in campaigns if c.get("clicks", 0) > 0]

    if not active:
        print("  Nenhuma campanha com dados. Use --track para adicionar métricas.")
        return

    print(f"\n  Optimization Engine — {len(active)} campanha(s) com dados")
    print("  " + "─" * 56)

    total_cost = 0.0
    for campaign in active:
        campaign = _compute_kpis(campaign)
        status, icon, _ = _optimization_status(campaign["roas"])
        print(f"\n  {icon} [{campaign['campaign_id']}] {campaign['idea_title'][:40]}")
        print(f"     ROAS {campaign['roas']:.2f}x · {status.upper()}")

        insights_raw, meta = await _claude(_p_optimization(campaign))
        insights = insights_raw if isinstance(insights_raw, dict) else {}
        total_cost += meta["cost"]

        campaign["optimization_status"] = status
        campaign["optimization_insights"] = insights

        if insights.get("acao_imediata"):
            print(f"     Ação imediata: {insights['acao_imediata'][:70]}")
        if insights.get("recomendacao_budget"):
            print(f"     Budget: {insights['recomendacao_budget'][:70]}")

        idx = next(
            (i for i, c in enumerate(campaigns) if c.get("campaign_id") == campaign["campaign_id"]),
            None,
        )
        if idx is not None:
            campaigns[idx] = campaign

    _save_campaigns(campaigns)
    print(f"\n  Otimização concluída · custo: ${total_cost:.4f}")
    _atualizar_dashboard()


# ─── Ranking ──────────────────────────────────────────────────────────────────


def show_ranking():
    campaigns = _load_campaigns()
    if not campaigns:
        print("  Nenhuma campanha encontrada.")
        print("  Rode: python ads_engine.py")
        return

    with_data = [_compute_kpis(c) for c in campaigns if c.get("clicks", 0) > 0]
    without_data = [c for c in campaigns if not c.get("clicks", 0)]

    STATUS_ICON = {"escalar": "🚀", "otimizar": "🔧", "pausar": "🛑", "aguardando_dados": "⏳"}

    print("\n" + "═" * 74)
    print("  ADS ENGINE — Ranking de Campanhas")
    print("═" * 74)

    if with_data:
        with_data.sort(key=lambda x: -x.get("roas", 0))
        print(f"\n  {'ID':<12} {'ROAS':>5} {'CPC':>7} {'CPL':>7} {'CPA':>7} {'Status':<12} Produto")
        print("  " + "─" * 70)
        for c in with_data:
            status = c.get("optimization_status", "aguardando_dados")
            icon = STATUS_ICON.get(status, "?")
            print(
                f"  {c.get('campaign_id','?'):<12} "
                f"{c.get('roas',0):>5.2f}x "
                f"R${c.get('cpc',0):>5.2f} "
                f"R${c.get('cpl',0):>5.2f} "
                f"R${c.get('cpa',0):>5.2f} "
                f"{icon} {status:<10} "
                f"{c.get('idea_title','?')[:25]}"
            )

    if without_data:
        print(f"\n  Aguardando dados ({len(without_data)}):")
        for c in without_data:
            print(
                f"  ⏳ {c.get('campaign_id','?'):<12} {c.get('idea_title','?')[:40]} "
                f"· {c.get('total_ads',0)} ads"
            )

    n_scale = sum(1 for c in with_data if c.get("optimization_status") == "escalar")
    n_opt = sum(1 for c in with_data if c.get("optimization_status") == "otimizar")
    n_pause = sum(1 for c in with_data if c.get("optimization_status") == "pausar")

    total_spend = sum(c.get("cost", 0) for c in campaigns)
    total_revenue = sum(c.get("revenue", 0) for c in campaigns)
    total_leads = sum(c.get("leads", 0) for c in campaigns)
    total_sales = sum(c.get("sales", 0) for c in campaigns)
    global_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0.0

    print("\n" + "═" * 74)
    print(
        f"  ROAS global: {global_roas:.2f}x  |  Spend: R${total_spend:,.2f}  |  "
        f"Revenue: R${total_revenue:,.2f}"
    )
    print(
        f"  Leads: {total_leads}  |  Vendas: {total_sales}  |  "
        f"🚀 Escalar: {n_scale}  |  🔧 Otimizar: {n_opt}  |  🛑 Pausar: {n_pause}\n"
    )


# ─── Auto-carrega melhor conteúdo ─────────────────────────────────────────────


def _load_best_content(title_filter: Optional[str] = None) -> Optional[dict]:
    """Carrega o melhor conteúdo validado dos outputs existentes."""
    candidates = []

    # de performance_*.json
    for path in glob.glob(f"{OUTPUTS_DIR}/performance_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            m = d.get("metrics", {})
            ins = d.get("insights", {})
            if m.get("performance_score", 0) >= PERFORMANCE_THRESHOLD:
                title = m.get("asset_id", "")
                if title_filter and title_filter.lower() not in title.lower():
                    continue
                candidates.append(
                    {
                        "idea_title": title,
                        "performance_score": m.get("performance_score", 0),
                        "validation_score": 0,
                        "platform": m.get("platform", "instagram"),
                        "top_hook": m.get("gancho", ""),
                    }
                )
        except Exception:
            pass

    # enriquece com validation scores
    for path in glob.glob(f"{OUTPUTS_DIR}/validation_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            title = d.get("idea_title", "")
            for c in candidates:
                if title.lower() in c["idea_title"].lower():
                    c["validation_score"] = d.get("signals", {}).get("validation_score", 0)
        except Exception:
            pass

    if not candidates:
        return None

    return max(
        candidates, key=lambda x: x.get("performance_score", 0) + x.get("validation_score", 0)
    )


# ─── Persistência secundária ──────────────────────────────────────────────────


async def _salvar_notion(result: dict):
    try:
        from integrations.notion_logger import salvar_tarefa

        body = (
            f"Campanha: {result.get('campaign_id','')}\n"
            f"Produto: {result.get('idea_title','')}\n"
            f"Total de anúncios: {result.get('total_ads',0)}\n"
            f"Budget/dia: R${result.get('budget_total',0)}\n\n"
            f"Ângulos:\n"
            + "\n".join(
                f"• [{a.get('tipo','')}] {a.get('titulo_anuncio','')}"
                for a in result.get("angles", [])
            )
        )
        await salvar_tarefa(
            f"Ads: {result.get('idea_title','')[:50]} — {result.get('total_ads',0)} ads",
            "ads_engine",
            body,
        )
    except Exception:
        pass


def _atualizar_dashboard():
    import subprocess
    import sys as _sys

    for script_name in ["generate_dashboard.py", "dashboard_engine.py"]:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), script_name)
        if not os.path.exists(script):
            continue
        try:
            subprocess.run(
                [_sys.executable, script, "--print" if "dashboard_engine" in script else ""],
                check=True,
                capture_output=True,
            )
        except Exception as e:
            print(f"  Dashboard ({script_name}): {e}")


# ─── Display terminal ─────────────────────────────────────────────────────────


def _imprimir(result: dict):
    angles = result.get("angles", [])
    copies = result.get("copies", [])
    creatives = result.get("creatives", [])
    ad_sets = result.get("ad_sets", [])

    print("\n" + "═" * 64)
    print(f"  ADS ENGINE — {result.get('idea_title','')[:40]}")
    print("═" * 64)
    print(f"\n  Campanha     : {result.get('campaign_id','')}")
    print(f"  Fase         : {result.get('fase','').upper()}")
    print(f"  Total ads    : {result.get('total_ads',0)}")
    print(f"  Budget/dia   : R${result.get('budget_total',0)}")
    print(f"  Duração teste: {result.get('duracao_dias',3)} dias")

    if angles:
        print(f"\n  ─── Ângulos ({len(angles)}) ──────────────────────────────────────")
        for a in angles:
            print(f"  [{a.get('tipo',''):<14}] {a.get('titulo_anuncio','')}")
            print(f"    Gancho: {a.get('gancho_video','')[:60]}")

    if copies:
        print(f"\n  ─── Copies ({len(copies)}) ───────────────────────────────────────")
        for c in copies:
            print(
                f"  [Var {c.get('variante','')}] {c.get('angulo_usado',''):<14} "
                f"→ {c.get('texto_completo','')[:55]}..."
            )

    if creatives:
        print("\n  ─── Criativos prontos ───────────────────────────────────")
        for cr in creatives:
            print(f"  {cr.get('id','')} [{cr.get('angulo',''):<14}] {cr.get('gancho','')[:45]}")
            print(
                f"    CTA: {cr.get('cta','')} | Plataformas: {', '.join(cr.get('plataformas',[]))}"
            )

    print("\n  ─── Conjuntos de anúncio ────────────────────────────────")
    for ads in ad_sets:
        print(
            f"  [{ads.get('publico','').upper():<12}] {len(ads.get('ads',[]))} ads · "
            f"R${ads.get('budget_dia',0)}/dia"
        )

    print(f"\n  Custo geração: ~${result.get('total_cost', result.get('ad_cost',0)):.4f}")
    print("\n  ─── Próximos passos ─────────────────────────────────────")
    print(f"  1. Subir os {result.get('total_ads',0)} anúncios no Meta Ads Manager")
    print("  2. Aguardar 3 dias de dados")
    print(f"  3. Rodar: python ads_engine.py --track --campaign {result.get('campaign_id','')} \\")
    print("            --clicks X --leads X --cost X --sales X")
    print("  4. Rodar: python ads_engine.py --optimize")
    print("═" * 64 + "\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────


async def main():
    args = sys.argv[1:]

    # --ranking
    if "--ranking" in args:
        show_ranking()
        return

    # --optimize
    if "--optimize" in args:
        await run_optimization()
        return

    # --track
    if "--track" in args:

        def _arg(flag, default=None):
            if flag in args:
                i = args.index(flag)
                return args[i + 1] if i + 1 < len(args) else default
            return default

        campaign_id = _arg("--campaign")
        if not campaign_id:
            print("  --campaign ID obrigatório com --track")
            return

        track_performance(
            campaign_id=campaign_id,
            clicks=int(_arg("--clicks", 0)),
            leads=int(_arg("--leads", 0)),
            sales=int(_arg("--sales", 0)),
            cost=float(_arg("--cost", 0)),
            revenue=float(_arg("--revenue", 0)),
        )
        return

    # --json
    if "--json" in args:
        idx = args.index("--json")
        raw = json.loads(args[idx + 1])
        await create_campaign(raw)
        return

    # --title
    if "--title" in args:
        idx = args.index("--title")
        title = args[idx + 1] if idx + 1 < len(args) else ""
        content = _load_best_content(title_filter=title)
        if not content:
            print(f"  Conteúdo com score ≥{PERFORMANCE_THRESHOLD} não encontrado para '{title}'.")
            print("  Execute performance_engine.py primeiro.")
            return
        print(f"  Carregado: {content['idea_title']} (score {content['performance_score']})")
        await create_campaign(content)
        return

    # sem argumentos — auto-carrega melhor conteúdo
    content = _load_best_content()
    if content:
        print(
            f"\n  Melhor conteúdo encontrado: {content['idea_title']} "
            f"(score {content['performance_score']})"
        )
        await create_campaign(content)
    else:
        print(f"\n  Nenhum conteúdo com score ≥{PERFORMANCE_THRESHOLD} encontrado.")
        print("  Execute performance_engine.py para registrar métricas primeiro.")
        print("\n  Ou passe manualmente:")
        print(
            '  python ads_engine.py --json \'{"idea_title":"CFO Digital",'
            '"performance_score":85,"validation_score":78}\''
        )


if __name__ == "__main__":
    asyncio.run(main())
