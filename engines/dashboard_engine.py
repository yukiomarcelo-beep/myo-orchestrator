#!/usr/bin/env python3
"""
Dashboard Engine — AI Business OS
Central de comando executiva. Consolida métricas de todos os engines.

5 blocos:
  1. Aquisição   — views, alcance, vídeos publicados
  2. Engajamento — likes, comentários, saves, shares, engagement rate
  3. Validação   — cliques, DMs, leads, lead rate
  4. Conversão   — leads → vendas, taxa, faturamento
  5. Escala      — decisões, ROI, top produto, top conteúdo

Regras de decisão automáticas:
  alto eng + baixa conv  → problema na oferta
  baixo eng + alto prod  → problema no conteúdo
  alto lead + baixa venda → problema no fechamento
  tudo alto               → ESCALAR IMEDIATO

Uso:
  python dashboard_engine.py              # gera + abre executive_dashboard.html
  python dashboard_engine.py --ticket 497 # define ticket médio (padrão R$497)
  python dashboard_engine.py --print      # exibe resumo no terminal sem abrir browser
"""

import glob
import json
import os
import subprocess
import sys
from datetime import date, datetime

OUTPUTS_DIR = "outputs"
DASH_FILE = "executive_dashboard.html"
METRICS_FILE = os.path.join(OUTPUTS_DIR, "dashboard_metrics.json")

DEFAULT_TICKET = 497.0  # R$ — ajuste conforme seu produto


# ─── Coleta de dados ──────────────────────────────────────────────────────────


def collect_metrics(ticket: float = DEFAULT_TICKET) -> dict:
    """Consolida todos os outputs em métricas executivas."""

    # ── Performance ──────────────────────────────────────────────────────────
    perf_records = []
    for path in glob.glob(f"{OUTPUTS_DIR}/performance_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            m = d.get("metrics", {})
            if m.get("views"):
                perf_records.append(m)
        except Exception:
            pass

    total_views = sum(r.get("views", 0) for r in perf_records)
    total_likes = sum(r.get("likes", 0) for r in perf_records)
    total_comments = sum(r.get("comments", 0) for r in perf_records)
    total_saves = sum(r.get("saves", 0) for r in perf_records)
    total_shares = sum(r.get("shares", 0) for r in perf_records)
    total_clicks = sum(r.get("clicks", 0) for r in perf_records)
    total_leads_p = sum(r.get("leads", 0) for r in perf_records)
    avg_eng = (
        sum(r.get("engagement_rate", 0) for r in perf_records) / len(perf_records)
        if perf_records
        else 0
    )

    top_perf = max(perf_records, key=lambda x: x.get("performance_score", 0), default={})

    # ── Validation ──────────────────────────────────────────────────────────
    val_records = []
    for path in glob.glob(f"{OUTPUTS_DIR}/validation_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            s = d.get("signals", {})
            val_records.append(
                {
                    "title": d.get("idea_title", ""),
                    "score": s.get("validation_score", 0),
                    "action": d.get("final_action", ""),
                    "dms": s.get("dm_requests", 0),
                    "leads": s.get("leads", 0),
                    "views": s.get("views", 0),
                    "dm_rate": s.get("dm_rate", 0),
                    "lead_rate": s.get("lead_rate", 0),
                }
            )
        except Exception:
            pass

    total_dms = sum(r.get("dms", 0) for r in val_records)
    total_leads_v = sum(r.get("leads", 0) for r in val_records)
    n_escalar = sum(1 for r in val_records if r.get("action") == "escalar")
    n_ajustar = sum(1 for r in val_records if r.get("action") == "ajustar")
    n_descartar = sum(1 for r in val_records if r.get("action") == "descartar")
    best_val = max(val_records, key=lambda x: x.get("score", 0), default={})
    avg_lead_rate = (
        sum(r.get("lead_rate", 0) for r in val_records) / len(val_records) if val_records else 0
    )

    # ── CRM (conversão) ──────────────────────────────────────────────────────
    crm_leads = []
    crm_file = os.path.join(OUTPUTS_DIR, "crm_leads.json")
    if os.path.exists(crm_file):
        try:
            with open(crm_file, encoding="utf-8") as f:
                crm_leads = json.load(f)
        except Exception:
            pass

    total_leads_crm = len(crm_leads)
    total_sales = sum(1 for l in crm_leads if l.get("pipeline_stage") == "cliente")
    total_quentes = sum(1 for l in crm_leads if l.get("temperature") == "quente")
    conv_rate = (total_sales / total_leads_crm) if total_leads_crm > 0 else 0.0
    revenue = total_sales * ticket

    # produto mais leads
    from collections import Counter

    product_counts = Counter(l.get("product", "?") for l in crm_leads)
    top_product = product_counts.most_common(1)[0][0] if product_counts else "—"

    # ── Scaling ──────────────────────────────────────────────────────────────
    scaling_records = []
    for path in glob.glob(f"{OUTPUTS_DIR}/scaling_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            scaling_records.append(d)
        except Exception:
            pass

    n_escalando = sum(1 for r in scaling_records if r.get("final_action") == "escalar")
    n_otimizando = sum(1 for r in scaling_records if r.get("final_action") == "otimizar")
    n_parado = sum(1 for r in scaling_records if r.get("final_action") == "stop")
    best_scaling = max(
        [r for r in scaling_records if r.get("final_action") == "escalar"],
        key=lambda x: x.get("data", {}).get("scaling_score", 0),
        default={},
    )

    # ── Leads consolidados ───────────────────────────────────────────────────
    total_leads = max(total_leads_p, total_leads_v, total_leads_crm)

    # ── ROI ──────────────────────────────────────────────────────────────────
    # custo estimado baseado nos registros de sessão
    session_files = glob.glob(os.path.join(OUTPUTS_DIR, "sessions", "session_*.json"))
    total_api_cost = 0.0
    for p in session_files:
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            total_api_cost += d.get("total_cost", 0)
        except Exception:
            pass

    roi = ((revenue - total_api_cost) / total_api_cost * 100) if total_api_cost > 0 else 0.0

    # ── Decisão automática ───────────────────────────────────────────────────
    decision = _auto_decision(avg_eng, avg_lead_rate, conv_rate, n_escalando)

    return {
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "ticket": ticket,
        # Bloco 1 — Aquisição
        "acquisition": {
            "total_views": total_views,
            "n_videos": len(perf_records),
            "avg_views": round(total_views / len(perf_records)) if perf_records else 0,
            "top_video_hook": top_perf.get("gancho", "—"),
            "top_video_score": top_perf.get("performance_score", 0),
            "top_video_views": top_perf.get("views", 0),
            "top_video_platform": top_perf.get("platform", "—"),
        },
        # Bloco 2 — Engajamento
        "engagement": {
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_saves": total_saves,
            "total_shares": total_shares,
            "engagement_rate": round(avg_eng * 100, 2),
            "total_clicks": total_clicks,
        },
        # Bloco 3 — Validação
        "validation": {
            "total_dms": total_dms,
            "total_leads": total_leads,
            "lead_rate": round(avg_lead_rate * 100, 2),
            "n_escalar": n_escalar,
            "n_ajustar": n_ajustar,
            "n_descartar": n_descartar,
            "best_product": best_val.get("title", "—"),
            "best_val_score": best_val.get("score", 0),
        },
        # Bloco 4 — Conversão
        "conversion": {
            "total_leads": total_leads_crm,
            "total_sales": total_sales,
            "total_quentes": total_quentes,
            "conv_rate": round(conv_rate * 100, 1),
            "revenue": round(revenue, 2),
            "ticket": ticket,
            "top_product": top_product,
        },
        # Bloco 5 — Escala
        "scaling": {
            "n_escalando": n_escalando,
            "n_otimizando": n_otimizando,
            "n_parado": n_parado,
            "total_records": len(scaling_records),
            "best_title": best_scaling.get("idea_title", "—"),
            "best_score": best_scaling.get("data", {}).get("scaling_score", 0),
            "roi": round(roi, 1),
            "api_cost": round(total_api_cost, 4),
        },
        # Diagnóstico
        "decision": decision,
        "raw": {
            "perf_records": len(perf_records),
            "val_records": len(val_records),
            "crm_leads": total_leads_crm,
            "scaling_records": len(scaling_records),
        },
    }


def _auto_decision(eng_rate: float, lead_rate: float, conv_rate: float, n_escalando: int) -> dict:
    """Regras de decisão automáticas do dashboard."""
    eng_high = eng_rate > 0.04  # >4%
    lead_high = lead_rate > 0.01  # >1%
    conv_high = conv_rate > 0.15  # >15%

    if eng_high and lead_high and conv_high:
        return {
            "action": "ESCALAR IMEDIATO",
            "color": "#10b981",
            "icon": "🚀",
            "reason": "Engajamento + leads + conversão altos. Sistema funcionando. Aumentar volume agora.",
            "priority": "maxima",
        }
    elif eng_high and not conv_high:
        return {
            "action": "REVISAR OFERTA",
            "color": "#f59e0b",
            "icon": "💰",
            "reason": "Alto engajamento mas baixa conversão. O problema está na oferta, não no conteúdo.",
            "priority": "alta",
        }
    elif not eng_high and lead_high:
        return {
            "action": "REVISAR CONTEÚDO",
            "color": "#f59e0b",
            "icon": "🎯",
            "reason": "Leads chegando mas engajamento baixo. Ajustar gancho e formato do conteúdo.",
            "priority": "alta",
        }
    elif lead_high and not conv_high:
        return {
            "action": "REVISAR FECHAMENTO",
            "color": "#f97316",
            "icon": "🤝",
            "reason": "Leads chegando mas vendas baixas. O problema está no processo de fechamento/CRM.",
            "priority": "alta",
        }
    elif n_escalando > 0:
        return {
            "action": "EXECUTAR ESCALA",
            "color": "#3b82f6",
            "icon": "📈",
            "reason": f"{n_escalando} produto(s) marcados para escala. Execute scaling_engine.py.",
            "priority": "media",
        }
    else:
        return {
            "action": "GERAR CONTEÚDO",
            "color": "#8b5cf6",
            "icon": "🎬",
            "reason": "Volume insuficiente para análise. Publique mais conteúdo e colete métricas.",
            "priority": "media",
        }


# ─── Persistência de métricas ─────────────────────────────────────────────────


def save_metrics_snapshot(metrics: dict):
    """Salva snapshot diário das métricas consolidadas."""
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    history = []
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass

    today = date.today().isoformat()
    history = [h for h in history if h.get("date") != today]  # remove entrada do dia
    history.append(
        {
            "date": today,
            "views": metrics["acquisition"]["total_views"],
            "engagement_rate": metrics["engagement"]["engagement_rate"],
            "clicks": metrics["engagement"]["total_clicks"],
            "leads": metrics["validation"]["total_leads"],
            "sales": metrics["conversion"]["total_sales"],
            "revenue": metrics["conversion"]["revenue"],
            "conversion_rate": metrics["conversion"]["conv_rate"],
            "decision": metrics["decision"]["action"],
        }
    )
    history = history[-90:]  # mantém 90 dias

    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ─── Geração do HTML ──────────────────────────────────────────────────────────


def generate_html(m: dict, history: list) -> str:
    acq = m["acquisition"]
    eng = m["engagement"]
    val = m["validation"]
    conv = m["conversion"]
    sc = m["scaling"]
    dec = m["decision"]

    # sparkline data (últimos 14 dias)
    hist14 = history[-14:]
    views_data = json.dumps([h.get("views", 0) for h in hist14])
    leads_data = json.dumps([h.get("leads", 0) for h in hist14])
    sales_data = json.dumps([h.get("sales", 0) for h in hist14])
    rev_data = json.dumps([h.get("revenue", 0) for h in hist14])
    dates_data = json.dumps([h.get("date", "")[-5:] for h in hist14])  # MM-DD

    # gauge de conversão (arco SVG simples)
    conv_pct = min(conv["conv_rate"], 100)
    eng_pct = min(eng["engagement_rate"] * 10, 100)  # escala: 10% eng = 100%

    def fmt_brl(v: float) -> str:
        return f"R$ {v:,.0f}".replace(",", ".")

    def fmt_num(v: int) -> str:
        if v >= 1_000_000:
            return f"{v/1_000_000:.1f}M"
        if v >= 1_000:
            return f"{v/1_000:.1f}K"
        return str(v)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Business OS — Dashboard Executivo</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0 }}
  :root {{
    --bg:     #060d17;
    --surface:#0a1628;
    --card:   #0d1f35;
    --border: #1a2d45;
    --text:   #e2e8f0;
    --muted:  #5a7a9a;
    --green:  #10b981;
    --blue:   #3b82f6;
    --yellow: #f59e0b;
    --red:    #ef4444;
    --purple: #8b5cf6;
    --orange: #f97316;
  }}
  body {{
    background:var(--bg); color:var(--text);
    font-family:'Inter','Segoe UI',system-ui,sans-serif;
    font-size:14px; min-height:100vh;
  }}

  /* ── Header ── */
  .header {{
    background:linear-gradient(135deg,#0a1628 0%,#0d2140 100%);
    border-bottom:1px solid var(--border);
    padding:20px 32px; display:flex; align-items:center; gap:16px;
  }}
  .header-logo {{ font-size:1.6rem; font-weight:800; color:var(--text);
    letter-spacing:-.5px }}
  .header-sub  {{ font-size:.85rem; color:var(--muted); margin-top:2px }}
  .header-time {{ margin-left:auto; text-align:right; font-size:.8rem; color:var(--muted) }}

  /* ── Decision Banner ── */
  .decision-banner {{
    margin:24px 32px 0;
    border-radius:14px; padding:20px 28px;
    display:flex; align-items:center; gap:16px;
    border:1px solid;
  }}
  .decision-icon  {{ font-size:2.4rem }}
  .decision-title {{ font-size:1.25rem; font-weight:700 }}
  .decision-reason {{ font-size:.88rem; color:#a0b8cc; margin-top:4px }}

  /* ── Grid ── */
  .grid-5 {{
    display:grid;
    grid-template-columns:repeat(5,1fr);
    gap:16px; padding:24px 32px 0;
  }}
  @media(max-width:1200px) {{ .grid-5 {{ grid-template-columns:repeat(3,1fr) }} }}
  @media(max-width:800px)  {{ .grid-5 {{ grid-template-columns:1fr 1fr }} }}

  /* ── Block Card ── */
  .block {{
    background:var(--card); border:1px solid var(--border);
    border-radius:14px; padding:20px; position:relative;
    overflow:hidden;
  }}
  .block::before {{
    content:''; position:absolute; top:0; left:0; right:0; height:3px;
  }}
  .block-acq::before   {{ background:var(--blue) }}
  .block-eng::before   {{ background:var(--purple) }}
  .block-val::before   {{ background:var(--yellow) }}
  .block-conv::before  {{ background:var(--green) }}
  .block-scale::before {{ background:var(--orange) }}

  .block-label {{ font-size:.7rem; text-transform:uppercase; letter-spacing:1px;
    color:var(--muted); margin-bottom:12px; font-weight:600 }}
  .kpi-big  {{ font-size:2.2rem; font-weight:800; line-height:1 }}
  .kpi-sub  {{ font-size:.78rem; color:var(--muted); margin-top:4px }}
  .metric-row {{
    display:flex; justify-content:space-between; align-items:center;
    padding:7px 0; border-bottom:1px solid var(--border); font-size:.82rem;
  }}
  .metric-row:last-child {{ border-bottom:none }}
  .metric-val {{ font-weight:600 }}
  .badge {{
    font-size:.72rem; padding:2px 8px; border-radius:20px; font-weight:600;
  }}

  /* ── Charts row ── */
  .charts-row {{
    display:grid; grid-template-columns:1fr 1fr;
    gap:16px; padding:16px 32px;
  }}
  @media(max-width:900px) {{ .charts-row {{ grid-template-columns:1fr }} }}
  .chart-card {{
    background:var(--card); border:1px solid var(--border);
    border-radius:14px; padding:20px;
  }}
  .chart-title {{ font-size:.82rem; color:var(--muted);
    text-transform:uppercase; letter-spacing:.5px; margin-bottom:16px }}
  .chart-wrap  {{ position:relative; height:140px }}

  /* ── Rules ── */
  .rules-grid {{
    display:grid; grid-template-columns:repeat(4,1fr);
    gap:12px; padding:0 32px 16px;
  }}
  @media(max-width:900px) {{ .rules-grid {{ grid-template-columns:1fr 1fr }} }}
  .rule-card {{
    background:var(--surface); border:1px solid var(--border);
    border-radius:10px; padding:14px; font-size:.8rem;
  }}
  .rule-if   {{ color:var(--muted); margin-bottom:6px }}
  .rule-then {{ font-weight:600; margin-top:4px }}

  /* ── Ticker ── */
  .ticker-row {{
    display:flex; gap:12px; padding:16px 32px; overflow-x:auto; flex-wrap:wrap;
  }}
  .ticker {{
    background:var(--surface); border:1px solid var(--border);
    border-radius:10px; padding:12px 18px; white-space:nowrap;
  }}
  .ticker-label {{ font-size:.7rem; color:var(--muted); text-transform:uppercase }}
  .ticker-val   {{ font-size:1.2rem; font-weight:700; margin-top:2px }}

  /* ── Footer ── */
  .footer {{
    text-align:center; font-size:.72rem; color:var(--muted);
    padding:20px 0 32px; border-top:1px solid var(--border); margin-top:24px;
  }}
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <div>
    <div class="header-logo">AI Business OS</div>
    <div class="header-sub">Dashboard Executivo — Central de Comando</div>
  </div>
  <div class="header-time">
    Atualizado: {m["generated_at"]}<br>
    Ticket médio: {fmt_brl(conv["ticket"])}
  </div>
</div>

<!-- DECISION BANNER -->
<div class="decision-banner" style="background:{dec['color']}12;border-color:{dec['color']}40;">
  <div class="decision-icon">{dec['icon']}</div>
  <div>
    <div class="decision-title" style="color:{dec['color']}">{dec['action']}</div>
    <div class="decision-reason">{dec['reason']}</div>
  </div>
  <div style="margin-left:auto;text-align:right">
    <div style="font-size:.75rem;color:var(--muted)">Prioridade</div>
    <div style="font-weight:700;color:{dec['color']};font-size:1rem;text-transform:uppercase">
      {dec['priority']}
    </div>
  </div>
</div>

<!-- TICKER ROW (KPIs rápidos) -->
<div class="ticker-row">
  <div class="ticker">
    <div class="ticker-label">Views Totais</div>
    <div class="ticker-val" style="color:var(--blue)">{fmt_num(acq['total_views'])}</div>
  </div>
  <div class="ticker">
    <div class="ticker-label">Engajamento</div>
    <div class="ticker-val" style="color:var(--purple)">{eng['engagement_rate']}%</div>
  </div>
  <div class="ticker">
    <div class="ticker-label">Leads</div>
    <div class="ticker-val" style="color:var(--yellow)">{fmt_num(val['total_leads'])}</div>
  </div>
  <div class="ticker">
    <div class="ticker-label">Vendas</div>
    <div class="ticker-val" style="color:var(--green)">{conv['total_sales']}</div>
  </div>
  <div class="ticker">
    <div class="ticker-label">Faturamento</div>
    <div class="ticker-val" style="color:var(--green)">{fmt_brl(conv['revenue'])}</div>
  </div>
  <div class="ticker">
    <div class="ticker-label">Conversão</div>
    <div class="ticker-val" style="color:{'var(--green)' if conv['conv_rate']>15 else 'var(--yellow)' if conv['conv_rate']>5 else 'var(--red)'}">{conv['conv_rate']}%</div>
  </div>
  <div class="ticker">
    <div class="ticker-label">ROI API</div>
    <div class="ticker-val" style="color:{'var(--green)' if sc['roi']>0 else 'var(--red)'}">{sc['roi']}%</div>
  </div>
  <div class="ticker">
    <div class="ticker-label">Top Produto</div>
    <div class="ticker-val" style="color:var(--orange);font-size:.95rem">{conv['top_product'][:22]}</div>
  </div>
</div>

<!-- 5 BLOCOS -->
<div class="grid-5">

  <!-- Bloco 1 — Aquisição -->
  <div class="block block-acq">
    <div class="block-label">📡 Aquisição</div>
    <div class="kpi-big" style="color:var(--blue)">{fmt_num(acq['total_views'])}</div>
    <div class="kpi-sub">views totais</div>
    <div style="margin-top:14px">
      <div class="metric-row">
        <span>Vídeos publicados</span>
        <span class="metric-val">{acq['n_videos']}</span>
      </div>
      <div class="metric-row">
        <span>Média por vídeo</span>
        <span class="metric-val">{fmt_num(acq['avg_views'])}</span>
      </div>
      <div class="metric-row">
        <span>Clicks totais</span>
        <span class="metric-val">{fmt_num(eng['total_clicks'])}</span>
      </div>
    </div>
    {f'<div style="margin-top:12px;font-size:.75rem;color:var(--muted)">Top: <em>{acq["top_video_hook"][:40]}</em></div>' if acq.get("top_video_hook") and acq["top_video_hook"] != "—" else ""}
  </div>

  <!-- Bloco 2 — Engajamento -->
  <div class="block block-eng">
    <div class="block-label">💜 Engajamento</div>
    <div class="kpi-big" style="color:var(--purple)">{eng['engagement_rate']}%</div>
    <div class="kpi-sub">engagement rate</div>
    <div style="margin-top:14px">
      <div class="metric-row">
        <span>Likes</span>
        <span class="metric-val">{fmt_num(eng['total_likes'])}</span>
      </div>
      <div class="metric-row">
        <span>Comentários</span>
        <span class="metric-val">{fmt_num(eng['total_comments'])}</span>
      </div>
      <div class="metric-row">
        <span>Saves</span>
        <span class="metric-val">{fmt_num(eng['total_saves'])}</span>
      </div>
      <div class="metric-row">
        <span>Shares</span>
        <span class="metric-val">{fmt_num(eng['total_shares'])}</span>
      </div>
    </div>
  </div>

  <!-- Bloco 3 — Validação -->
  <div class="block block-val">
    <div class="block-label">✅ Validação</div>
    <div class="kpi-big" style="color:var(--yellow)">{fmt_num(val['total_leads'])}</div>
    <div class="kpi-sub">leads gerados</div>
    <div style="margin-top:14px">
      <div class="metric-row">
        <span>DMs recebidos</span>
        <span class="metric-val">{fmt_num(val['total_dms'])}</span>
      </div>
      <div class="metric-row">
        <span>Lead rate</span>
        <span class="metric-val">{val['lead_rate']}%</span>
      </div>
      <div class="metric-row">
        <span>🚀 Escalar</span>
        <span class="metric-val" style="color:var(--green)">{val['n_escalar']}</span>
      </div>
      <div class="metric-row">
        <span>🔧 Ajustar</span>
        <span class="metric-val" style="color:var(--yellow)">{val['n_ajustar']}</span>
      </div>
      <div class="metric-row">
        <span>🗑 Descartar</span>
        <span class="metric-val" style="color:var(--red)">{val['n_descartar']}</span>
      </div>
    </div>
  </div>

  <!-- Bloco 4 — Conversão -->
  <div class="block block-conv">
    <div class="block-label">💰 Conversão</div>
    <div class="kpi-big" style="color:var(--green)">{fmt_brl(conv['revenue'])}</div>
    <div class="kpi-sub">faturamento estimado</div>
    <div style="margin-top:14px">
      <div class="metric-row">
        <span>Leads no CRM</span>
        <span class="metric-val">{conv['total_leads']}</span>
      </div>
      <div class="metric-row">
        <span>Leads quentes</span>
        <span class="metric-val" style="color:var(--red)">🔥 {conv['total_quentes']}</span>
      </div>
      <div class="metric-row">
        <span>Vendas</span>
        <span class="metric-val" style="color:var(--green)">{conv['total_sales']}</span>
      </div>
      <div class="metric-row">
        <span>Taxa de conv.</span>
        <span class="metric-val" style="color:{'var(--green)' if conv['conv_rate']>15 else 'var(--yellow)'}">{conv['conv_rate']}%</span>
      </div>
      <div class="metric-row">
        <span>Ticket médio</span>
        <span class="metric-val">{fmt_brl(conv['ticket'])}</span>
      </div>
    </div>
  </div>

  <!-- Bloco 5 — Escala -->
  <div class="block block-scale">
    <div class="block-label">📈 Escala</div>
    <div class="kpi-big" style="color:var(--orange)">{sc['n_escalando']}</div>
    <div class="kpi-sub">produtos escalando</div>
    <div style="margin-top:14px">
      <div class="metric-row">
        <span>🔧 Otimizando</span>
        <span class="metric-val">{sc['n_otimizando']}</span>
      </div>
      <div class="metric-row">
        <span>🛑 Parado</span>
        <span class="metric-val" style="color:var(--red)">{sc['n_parado']}</span>
      </div>
      <div class="metric-row">
        <span>ROI (api)</span>
        <span class="metric-val" style="color:{'var(--green)' if sc['roi']>0 else 'var(--red)'}">{sc['roi']}%</span>
      </div>
      <div class="metric-row">
        <span>Custo API</span>
        <span class="metric-val">${sc['api_cost']:.4f}</span>
      </div>
    </div>
    {f'<div style="margin-top:10px;font-size:.75rem;color:var(--muted)">Top: <strong style=\'color:var(--orange)\'>{sc["best_title"][:30]}</strong> ({sc["best_score"]}/100)</div>' if sc.get("best_title") and sc["best_title"] != "—" else ""}
  </div>

</div>

<!-- CHARTS -->
<div class="charts-row">

  <div class="chart-card">
    <div class="chart-title">Views ao longo do tempo</div>
    <div class="chart-wrap"><canvas id="viewsChart"></canvas></div>
  </div>

  <div class="chart-card">
    <div class="chart-title">Leads & Vendas ao longo do tempo</div>
    <div class="chart-wrap"><canvas id="convChart"></canvas></div>
  </div>

</div>

<!-- REGRAS DE DECISÃO -->
<div style="padding:0 32px 8px;margin-top:4px">
  <div style="font-size:.75rem;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:10px">
    Regras de Decisão Automáticas
  </div>
</div>
<div class="rules-grid">
  <div class="rule-card" style="border-color:#ef444430">
    <div class="rule-if">SE alto eng + baixa conv</div>
    <div class="rule-then" style="color:var(--red)">💰 Problema na oferta</div>
    <div style="font-size:.74rem;color:var(--muted);margin-top:6px">
      O conteúdo atrai mas a oferta não converte. Revise preço, promessa e CTA.
    </div>
  </div>
  <div class="rule-card" style="border-color:#8b5cf630">
    <div class="rule-if">SE baixo eng + alto produto</div>
    <div class="rule-then" style="color:var(--purple)">🎯 Problema no conteúdo</div>
    <div style="font-size:.74rem;color:var(--muted);margin-top:6px">
      O produto existe mas o conteúdo não gera atenção. Mudar gancho e formato.
    </div>
  </div>
  <div class="rule-card" style="border-color:#f9731630">
    <div class="rule-if">SE alto lead + baixa venda</div>
    <div class="rule-then" style="color:var(--orange)">🤝 Problema no fechamento</div>
    <div style="font-size:.74rem;color:var(--muted);margin-top:6px">
      Leads chegando mas não fecham. Revisar follow-up, sequência e CRM.
    </div>
  </div>
  <div class="rule-card" style="border-color:#10b98130">
    <div class="rule-if">SE tudo alto</div>
    <div class="rule-then" style="color:var(--green)">🚀 Escalar imediato</div>
    <div style="font-size:.74rem;color:var(--muted);margin-top:6px">
      Sistema funcionando. Aumentar frequência, verba e volume agora.
    </div>
  </div>
</div>

<!-- FOOTER -->
<div class="footer">
  AI Business OS &mdash; Dashboard Executivo &mdash; {m["generated_at"]} &mdash;
  {m["raw"]["perf_records"]} ativos · {m["raw"]["val_records"]} validações ·
  {m["raw"]["crm_leads"]} leads · {m["raw"]["scaling_records"]} scalings
  &mdash; gerado por dashboard_engine.py
</div>

<script>
Chart.defaults.color = '#5a7a9a';
Chart.defaults.borderColor = '#1a2d45';
Chart.defaults.font.family = 'Inter, system-ui, sans-serif';

const dates  = {dates_data};
const views  = {views_data};
const leads  = {leads_data};
const sales  = {sales_data};

// Views chart
new Chart(document.getElementById('viewsChart'), {{
  type: 'line',
  data: {{
    labels: dates.length ? dates : ['—'],
    datasets: [{{
      label: 'Views',
      data: views.length ? views : [0],
      borderColor: '#3b82f6',
      backgroundColor: '#3b82f615',
      fill: true, tension: 0.4,
      pointRadius: 3,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      y: {{ beginAtZero: true, grid: {{ color: '#1a2d45' }} }},
      x: {{ grid: {{ color: '#1a2d45' }} }}
    }}
  }}
}});

// Conv chart
new Chart(document.getElementById('convChart'), {{
  type: 'bar',
  data: {{
    labels: dates.length ? dates : ['—'],
    datasets: [
      {{ label: 'Leads', data: leads.length ? leads : [0],
         backgroundColor: '#f59e0b80', borderColor: '#f59e0b', borderWidth:1 }},
      {{ label: 'Vendas', data: sales.length ? sales : [0],
         backgroundColor: '#10b98180', borderColor: '#10b981', borderWidth:1 }},
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ position: 'top', labels: {{ boxWidth: 10 }} }} }},
    scales: {{
      y: {{ beginAtZero: true, grid: {{ color: '#1a2d45' }} }},
      x: {{ grid: {{ color: '#1a2d45' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main():
    args = sys.argv[1:]
    ticket = DEFAULT_TICKET
    silent = "--print" in args

    if "--ticket" in args:
        idx = args.index("--ticket")
        try:
            ticket = float(args[idx + 1])
        except (IndexError, ValueError):
            pass

    print("\n  Dashboard Engine — consolidando métricas...")

    metrics = collect_metrics(ticket)
    save_metrics_snapshot(metrics)

    # carrega histórico para charts
    history = []
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass

    html = generate_html(metrics, history)
    with open(DASH_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    dec = metrics["decision"]
    acq = metrics["acquisition"]
    eng = metrics["engagement"]
    val = metrics["validation"]
    conv = metrics["conversion"]
    sc = metrics["scaling"]

    print(f"\n  {'═'*56}")
    print("  AI BUSINESS OS — RESUMO EXECUTIVO")
    print(f"  {'═'*56}")
    print(f"  {dec['icon']}  AÇÃO: {dec['action']}")
    print(f"      {dec['reason'][:70]}")
    print(f"\n  Views      : {acq['total_views']:>10,}  ({acq['n_videos']} ativos)")
    print(f"  Engajamento: {eng['engagement_rate']:>9}%")
    print(f"  Leads      : {val['total_leads']:>10,}  (lead rate {val['lead_rate']}%)")
    print(f"  Vendas     : {conv['total_sales']:>10,}  (conv {conv['conv_rate']}%)")
    print(f"  Faturamento: R$ {conv['revenue']:>9,.0f}")
    print(f"  ROI API    : {sc['roi']:>9}%  (custo ${sc['api_cost']:.4f})")
    print(f"  Escalando  : {sc['n_escalando']:>10}")
    print(f"\n  Dashboard  : {os.path.abspath(DASH_FILE)}")
    print(f"  Métricas   : {os.path.abspath(METRICS_FILE)}")
    print(f"  {'═'*56}\n")

    if not silent:
        try:
            subprocess.Popen(["open", DASH_FILE])
        except Exception:
            pass


if __name__ == "__main__":
    main()
