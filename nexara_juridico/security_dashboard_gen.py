"""
security_dashboard_gen.py — Gerador de dashboard de segurança Nexara

Lê logs/security.jsonl (gerado por shared/audit.py) e produz dashboard.html
estático com Chart.js. Sem servidor, sem polling, sem dependências externas
além do Python stdlib.

Padrão visual alinhado com o Nexara design system (Inter/Poppins/JetBrains Mono,
tokens --nx-*, sidebar, glassmorphism).

Uso:
    python security_dashboard_gen.py              # gera HTML
    python security_dashboard_gen.py --open       # gera e abre no browser
    python security_dashboard_gen.py --janela 7   # últimos 7 dias (default: 30)

CLI:
    --output PATH    Caminho do HTML (default: logs/security_dashboard.html)
    --log PATH       Caminho do JSONL (default: logs/security.jsonl)
    --janela N       Janela em dias para análise (default: 30)
    --open           Abre o HTML no browser ao final
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Leitura e parsing do log
# ─────────────────────────────────────────────────────────────────────────────


def carregar_eventos(caminho_log: Path, janela_dias: int) -> list[dict[str, Any]]:
    """Lê security.jsonl e retorna eventos dentro da janela."""
    if not caminho_log.exists():
        return []

    limite = datetime.now(timezone.utc) - timedelta(days=janela_dias)
    eventos: list[dict[str, Any]] = []

    with open(caminho_log, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                ev = json.loads(linha)
            except json.JSONDecodeError:
                continue

            ts = ev.get("ts")
            if not ts:
                continue
            try:
                ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if ts_dt < limite:
                    continue
                ev["_ts_dt"] = ts_dt
            except (ValueError, TypeError):
                continue

            eventos.append(ev)

    return eventos


# ─────────────────────────────────────────────────────────────────────────────
# Agregação para os gráficos
# ─────────────────────────────────────────────────────────────────────────────


def agregar(eventos: list[dict[str, Any]], janela_dias: int) -> dict[str, Any]:
    """Produz dicts prontos para alimentar Chart.js."""
    agora = datetime.now(timezone.utc)
    inicio = agora - timedelta(days=janela_dias)

    dias = []
    cursor = inicio.date()
    while cursor <= agora.date():
        dias.append(cursor.isoformat())
        cursor += timedelta(days=1)

    anomalias_por_dia = Counter({d: 0 for d in dias})
    eventos_por_dia = Counter({d: 0 for d in dias})

    por_severity = Counter()
    por_agente = Counter()
    por_tag = Counter()
    por_source = Counter()
    por_url_status = Counter()

    ultimas_anomalias: list[dict[str, Any]] = []
    ultimas_decisoes: list[dict[str, Any]] = []

    total_eventos = 0
    total_anomalias = 0
    total_tool_calls = 0
    total_url_fetches = 0
    total_url_blocked = 0

    for ev in eventos:
        total_eventos += 1
        dia = ev["_ts_dt"].date().isoformat()
        eventos_por_dia[dia] += 1

        tipo = ev.get("type")
        agente = ev.get("agent", "?")
        por_agente[agente] += 1

        if tipo == "anomaly":
            total_anomalias += 1
            anomalias_por_dia[dia] += 1
            sev = ev.get("severity", "medium")
            por_severity[sev] += 1
            por_source[ev.get("source", "unknown")] += 1
            for flag in ev.get("flags", []):
                tag = flag.get("tag") if isinstance(flag, dict) else str(flag)
                por_tag[tag] += 1
            ultimas_anomalias.append(
                {
                    "ts": ev["_ts_dt"].strftime("%Y-%m-%d %H:%M"),
                    "agent": agente,
                    "severity": sev,
                    "source": ev.get("source", "unknown"),
                    "tags": [
                        f.get("tag") if isinstance(f, dict) else str(f) for f in ev.get("flags", [])
                    ][:5],
                    "content_hash": (ev.get("content_hash") or "")[:23],
                }
            )

        elif tipo == "tool_call":
            total_tool_calls += 1

        elif tipo == "url_fetch":
            total_url_fetches += 1
            status = ev.get("status", "?")
            por_url_status[status] += 1
            if status in ("blocked", "out_of_whitelist"):
                total_url_blocked += 1

        elif tipo == "decision":
            ultimas_decisoes.append(
                {
                    "ts": ev["_ts_dt"].strftime("%Y-%m-%d %H:%M"),
                    "agent": agente,
                    "decision": ev.get("decision", "?"),
                    "reason": (ev.get("reason") or "")[:120],
                }
            )

    ultimas_anomalias.sort(key=lambda x: x["ts"], reverse=True)
    ultimas_anomalias = ultimas_anomalias[:20]
    ultimas_decisoes.sort(key=lambda x: x["ts"], reverse=True)
    ultimas_decisoes = ultimas_decisoes[:20]

    severity_ordem = ["low", "medium", "high", "critical"]
    severity_data = {s: por_severity.get(s, 0) for s in severity_ordem}

    return {
        "janela_dias": janela_dias,
        "gerado_em": agora.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "totais": {
            "eventos": total_eventos,
            "anomalias": total_anomalias,
            "tool_calls": total_tool_calls,
            "url_fetches": total_url_fetches,
            "url_blocked": total_url_blocked,
        },
        "dias": dias,
        "anomalias_por_dia": [anomalias_por_dia[d] for d in dias],
        "eventos_por_dia": [eventos_por_dia[d] for d in dias],
        "severity_labels": severity_ordem,
        "severity_data": list(severity_data.values()),
        "agentes_labels": list(por_agente.keys()),
        "agentes_data": list(por_agente.values()),
        "tags_labels": [t for t, _ in por_tag.most_common(10)],
        "tags_data": [c for _, c in por_tag.most_common(10)],
        "source_labels": list(por_source.keys()),
        "source_data": list(por_source.values()),
        "url_status_labels": list(por_url_status.keys()),
        "url_status_data": list(por_url_status.values()),
        "ultimas_anomalias": ultimas_anomalias,
        "ultimas_decisoes": ultimas_decisoes,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Template HTML — Nexara design system
# ─────────────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nexara — Security Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Poppins:wght@600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  /* ── Nexara design tokens ── */
  :root {
    --nx-brand:           #009dde;
    --nx-brand-300:       #4bbdf1;
    --nx-brand-600:       #0078a8;
    --nx-success:         #10b981;
    --nx-warning:         #f59e0b;
    --nx-danger:          #ef4444;
    --nx-info:            #0891b2;

    --nx-bg-page:         #000;
    --nx-sidebar-bg:      #0a0a0c;
    --nx-chrome-border:   rgba(255,255,255,.06);
    --nx-text:            #ffffff;
    --nx-text-85:         rgba(235,235,245,.85);
    --nx-text-secondary:  rgba(235,235,245,.6);
    --nx-text-tertiary:   rgba(235,235,245,.4);
    --nx-text-dim:        rgba(235,235,245,.2);
    --nx-surface-1:       rgba(255,255,255,.03);
    --nx-surface-2:       rgba(255,255,255,.06);
    --nx-surface-3:       rgba(255,255,255,.09);
    --nx-surface-4:       rgba(255,255,255,.13);
    --nx-nav-active-bg:   rgba(0,166,234,.14);
    --nx-nav-icon-bg:     rgba(255,255,255,.04);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--nx-bg-page);
    color: var(--nx-text-85);
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 13px;
    line-height: 1.5;
    display: flex;
    min-height: 100vh;
  }

  /* ── Sidebar ── */
  .sidebar {
    width: 240px;
    background: var(--nx-sidebar-bg);
    border-right: 0.5px solid var(--nx-chrome-border);
    display: flex;
    flex-direction: column;
    padding: 20px 12px;
    position: sticky;
    top: 0;
    height: 100vh;
    flex-shrink: 0;
  }

  .logo {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 8px;
    margin-bottom: 28px;
  }
  .logo-icon {
    width: 28px; height: 28px;
    border-radius: 8px;
    background: linear-gradient(135deg, #009dde, #4bbdf1);
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    font-size: 15px;
  }
  .logo-name {
    font-family: 'Poppins', sans-serif;
    font-weight: 700;
    font-size: 15px;
    color: var(--nx-text);
    line-height: 1.2;
  }
  .logo-sub {
    font-size: 10px;
    font-weight: 400;
    color: var(--nx-text-tertiary);
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .nav-label {
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--nx-text-tertiary);
    padding: 0 10px;
    margin: 16px 0 4px;
  }

  nav { display: flex; flex-direction: column; gap: 1px; }

  nav a {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 7px 10px;
    border-radius: 10px;
    text-decoration: none;
    color: var(--nx-text-secondary);
    font-size: 13px;
    font-weight: 500;
    position: relative;
    transition: background 0.15s, color 0.15s;
  }
  nav a:hover {
    background: var(--nx-surface-2);
    color: var(--nx-text-85);
  }
  nav a.active {
    background: var(--nx-nav-active-bg);
    color: var(--nx-brand-300);
  }
  nav a.active::before {
    content: '';
    position: absolute;
    left: 0; top: 20%; bottom: 20%;
    width: 3px;
    border-radius: 0 3px 3px 0;
    background: var(--nx-brand);
  }

  .nav-icon {
    width: 22px; height: 22px;
    background: var(--nx-nav-icon-bg);
    border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    font-size: 13px;
    flex-shrink: 0;
  }
  nav a.active .nav-icon {
    background: rgba(0,157,222,.18);
  }

  .sidebar-footer {
    margin-top: auto;
    padding: 14px 10px 0;
    border-top: 0.5px solid var(--nx-chrome-border);
    font-size: 11px;
    color: var(--nx-text-tertiary);
    line-height: 1.7;
  }
  .sidebar-footer code {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    background: var(--nx-surface-2);
    padding: 1px 5px;
    border-radius: 4px;
    color: var(--nx-text-secondary);
  }

  /* ── Main ── */
  .main {
    flex: 1;
    padding: 32px 36px;
    overflow-x: hidden;
  }

  .page-header { margin-bottom: 28px; }
  .page-title {
    font-family: 'Poppins', sans-serif;
    font-weight: 700;
    font-size: 22px;
    color: var(--nx-text);
    margin-bottom: 4px;
  }
  .page-sub {
    font-size: 12px;
    color: var(--nx-text-tertiary);
  }

  /* ── Grid ── */
  .grid { display: grid; gap: 12px; margin-bottom: 16px; }
  .grid-4 { grid-template-columns: repeat(4, 1fr); }
  .grid-2 { grid-template-columns: repeat(2, 1fr); }
  .grid-3 { grid-template-columns: repeat(3, 1fr); }

  @media (max-width: 1100px) {
    .grid-4 { grid-template-columns: repeat(2, 1fr); }
    .grid-2, .grid-3 { grid-template-columns: 1fr; }
    .sidebar { display: none; }
    .main { padding: 20px 16px; }
  }

  /* ── Cards ── */
  .card {
    background: var(--nx-surface-2);
    border: 0.5px solid var(--nx-chrome-border);
    border-radius: 12px;
    padding: 20px;
  }

  .section-title {
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--nx-text-tertiary);
    margin-bottom: 16px;
  }

  /* ── KPI ── */
  .kpi-label {
    font-size: 12px;
    font-weight: 500;
    color: var(--nx-text-secondary);
    margin-bottom: 10px;
  }
  .kpi-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 32px;
    font-weight: 600;
    color: var(--nx-text);
    line-height: 1;
    letter-spacing: -0.02em;
  }
  .kpi-value.ok     { color: var(--nx-success); }
  .kpi-value.warn   { color: var(--nx-warning); }
  .kpi-value.danger { color: var(--nx-danger); }
  .kpi-sub {
    font-size: 11px;
    color: var(--nx-text-tertiary);
    margin-top: 8px;
  }

  /* ── Charts ── */
  .chart-container { position: relative; height: 220px; }

  /* ── Tables ── */
  table { width: 100%; border-collapse: collapse; }
  th {
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--nx-text-tertiary);
    padding: 0 10px 10px;
    text-align: left;
    border-bottom: 0.5px solid var(--nx-chrome-border);
  }
  td {
    padding: 10px;
    border-bottom: 0.5px solid var(--nx-chrome-border);
    color: var(--nx-text-85);
    font-size: 13px;
    vertical-align: middle;
  }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: var(--nx-surface-1); }
  .mono {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 400;
    color: var(--nx-text-tertiary);
  }

  /* ── Badges ── */
  .badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 8px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .badge.low      { background: rgba(16,185,129,.12);  color: #10b981; }
  .badge.medium   { background: rgba(245,158,11,.12);  color: #f59e0b; }
  .badge.high     { background: rgba(249,115,22,.12);  color: #f97316; }
  .badge.critical { background: rgba(239,68,68,.18);   color: #ef4444; }

  /* ── Tags ── */
  .tag {
    display: inline-flex;
    padding: 2px 6px;
    margin-right: 3px;
    background: rgba(8,145,178,.12);
    color: var(--nx-info);
    border-radius: 6px;
    font-size: 10px;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.02em;
  }

  .empty {
    text-align: center;
    color: var(--nx-text-tertiary);
    padding: 40px 0;
    font-style: italic;
  }
</style>
</head>
<body>

<!-- Sidebar -->
<aside class="sidebar">
  <div class="logo">
    <div class="logo-icon">🛡</div>
    <div>
      <div class="logo-name">Nexara</div>
      <div class="logo-sub">Security</div>
    </div>
  </div>

  <div class="nav-label">Visão Geral</div>
  <nav>
    <a href="#kpis" class="active">
      <span class="nav-icon">📊</span>KPIs
    </a>
    <a href="#timeline">
      <span class="nav-icon">📈</span>Linha do tempo
    </a>
    <a href="#distribuicoes">
      <span class="nav-icon">🔍</span>Distribuições
    </a>
  </nav>

  <div class="nav-label">Eventos</div>
  <nav>
    <a href="#anomalias">
      <span class="nav-icon">⚠️</span>Anomalias
    </a>
    <a href="#decisoes">
      <span class="nav-icon">✅</span>Decisões
    </a>
  </nav>

  <div class="sidebar-footer">
    Fonte: <code>logs/security.jsonl</code><br>
    Janela: {JANELA} dias<br>
    Atualizado: {GERADO}
  </div>
</aside>

<!-- Main -->
<main class="main">
  <div class="page-header">
    <h1 class="page-title">Security Dashboard</h1>
    <div class="page-sub">Últimos {JANELA} dias · Gerado em {GERADO}</div>
  </div>

  <!-- KPIs -->
  <div id="kpis" class="grid grid-4">
    <div class="card">
      <div class="kpi-label">Eventos totais</div>
      <div class="kpi-value">{TOT_EVENTOS}</div>
      <div class="kpi-sub">na janela</div>
    </div>
    <div class="card">
      <div class="kpi-label">Anomalias detectadas</div>
      <div class="kpi-value {ANOMALIAS_CLASS}">{TOT_ANOMALIAS}</div>
      <div class="kpi-sub">injection suspeita</div>
    </div>
    <div class="card">
      <div class="kpi-label">Chamadas LLM</div>
      <div class="kpi-value">{TOT_TOOL}</div>
      <div class="kpi-sub">tool calls auditadas</div>
    </div>
    <div class="card">
      <div class="kpi-label">URLs bloqueadas</div>
      <div class="kpi-value {URL_CLASS}">{TOT_BLOCKED} / {TOT_FETCH}</div>
      <div class="kpi-sub">fora da whitelist</div>
    </div>
  </div>

  <!-- Timeline -->
  <div id="timeline" class="grid grid-2">
    <div class="card">
      <div class="section-title">Anomalias por dia</div>
      <div class="chart-container"><canvas id="chart_anomalias"></canvas></div>
    </div>
    <div class="card">
      <div class="section-title">Eventos por dia</div>
      <div class="chart-container"><canvas id="chart_eventos"></canvas></div>
    </div>
  </div>

  <!-- Distribuições -->
  <div id="distribuicoes" class="grid grid-3">
    <div class="card">
      <div class="section-title">Severidade</div>
      <div class="chart-container"><canvas id="chart_severity"></canvas></div>
    </div>
    <div class="card">
      <div class="section-title">Top tags injection</div>
      <div class="chart-container"><canvas id="chart_tags"></canvas></div>
    </div>
    <div class="card">
      <div class="section-title">Por agente</div>
      <div class="chart-container"><canvas id="chart_agentes"></canvas></div>
    </div>
  </div>

  <!-- Anomalias -->
  <div id="anomalias" class="card" style="margin-bottom: 12px;">
    <div class="section-title">Últimas 20 anomalias</div>
    {TABELA_ANOMALIAS}
  </div>

  <!-- Decisões -->
  <div id="decisoes" class="card">
    <div class="section-title">Últimas 20 decisões</div>
    {TABELA_DECISOES}
  </div>
</main>

<script>
Chart.defaults.color = 'rgba(235,235,245,.4)';
Chart.defaults.borderColor = 'rgba(255,255,255,.06)';
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.font.size = 12;

const brand      = '#009dde';
const brandGlass = 'rgba(0,157,222,.15)';
const danger     = '#ef4444';
const dangerGlass= 'rgba(239,68,68,.15)';

new Chart(document.getElementById('chart_anomalias'), {
  type: 'line',
  data: {
    labels: {DIAS_JSON},
    datasets: [{
      data: {ANOMALIAS_POR_DIA_JSON},
      borderColor: danger,
      backgroundColor: dangerGlass,
      fill: true, tension: 0.4,
      pointRadius: 3, pointBackgroundColor: danger,
    }]
  },
  options: {
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { maxTicksLimit: 7 } },
      y: { beginAtZero: true, ticks: { precision: 0 } }
    }
  }
});

new Chart(document.getElementById('chart_eventos'), {
  type: 'line',
  data: {
    labels: {DIAS_JSON},
    datasets: [{
      data: {EVENTOS_POR_DIA_JSON},
      borderColor: brand,
      backgroundColor: brandGlass,
      fill: true, tension: 0.4,
      pointRadius: 3, pointBackgroundColor: brand,
    }]
  },
  options: {
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { maxTicksLimit: 7 } },
      y: { beginAtZero: true, ticks: { precision: 0 } }
    }
  }
});

const sevColors = { low:'#10b981', medium:'#f59e0b', high:'#f97316', critical:'#ef4444' };
new Chart(document.getElementById('chart_severity'), {
  type: 'doughnut',
  data: {
    labels: {SEVERITY_LABELS_JSON},
    datasets: [{
      data: {SEVERITY_DATA_JSON},
      backgroundColor: {SEVERITY_LABELS_JSON}.map(s => sevColors[s] || '#6b7280'),
      borderWidth: 0,
    }]
  },
  options: {
    cutout: '65%',
    plugins: { legend: { position: 'bottom', labels: { padding: 14, boxWidth: 10 } } }
  }
});

new Chart(document.getElementById('chart_tags'), {
  type: 'bar',
  data: {
    labels: {TAGS_LABELS_JSON},
    datasets: [{ data: {TAGS_DATA_JSON}, backgroundColor: danger, borderRadius: 4 }]
  },
  options: {
    indexAxis: 'y',
    plugins: { legend: { display: false } },
    scales: { x: { beginAtZero: true, ticks: { precision: 0 } } }
  }
});

new Chart(document.getElementById('chart_agentes'), {
  type: 'bar',
  data: {
    labels: {AGENTES_LABELS_JSON},
    datasets: [{ data: {AGENTES_DATA_JSON}, backgroundColor: brand, borderRadius: 4 }]
  },
  options: {
    indexAxis: 'y',
    plugins: { legend: { display: false } },
    scales: { x: { beginAtZero: true, ticks: { precision: 0 } } }
  }
});

// Ativa nav item ativo ao scroll
const sections = ['kpis','timeline','distribuicoes','anomalias','decisoes'];
const navLinks  = document.querySelectorAll('nav a');
window.addEventListener('scroll', () => {
  let current = '#kpis';
  sections.forEach(id => {
    const el = document.getElementById(id);
    if (el && window.scrollY >= el.offsetTop - 100) current = '#' + id;
  });
  navLinks.forEach(a => {
    a.classList.toggle('active', a.getAttribute('href') === current);
  });
}, { passive: true });
</script>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Renderização de tabelas
# ─────────────────────────────────────────────────────────────────────────────


def _render_tabela_anomalias(anomalias: list[dict[str, Any]]) -> str:
    if not anomalias:
        return '<div class="empty">Nenhuma anomalia detectada na janela.</div>'
    linhas = []
    for a in anomalias:
        tags_html = "".join(f'<span class="tag">{t}</span>' for t in a["tags"])
        linhas.append(
            f'<tr>'
            f'<td class="mono">{a["ts"]}</td>'
            f'<td>{a["agent"]}</td>'
            f'<td><span class="badge {a["severity"]}">{a["severity"]}</span></td>'
            f'<td style="color:var(--nx-text-secondary)">{a["source"]}</td>'
            f'<td>{tags_html}</td>'
            f'<td class="mono">{a["content_hash"]}</td>'
            f'</tr>'
        )
    return (
        '<table>'
        '<thead><tr>'
        '<th>Quando</th><th>Agente</th><th>Severidade</th>'
        '<th>Fonte</th><th>Tags</th><th>Hash</th>'
        '</tr></thead>'
        f'<tbody>{"".join(linhas)}</tbody>'
        '</table>'
    )


def _render_tabela_decisoes(decisoes: list[dict[str, Any]]) -> str:
    if not decisoes:
        return '<div class="empty">Nenhuma decisão registrada na janela.</div>'
    linhas = [
        f'<tr>'
        f'<td class="mono">{d["ts"]}</td>'
        f'<td>{d["agent"]}</td>'
        f'<td style="color:var(--nx-brand-300)">{d["decision"]}</td>'
        f'<td style="color:var(--nx-text-secondary)">{d["reason"]}</td>'
        f'</tr>'
        for d in decisoes
    ]
    return (
        '<table>'
        '<thead><tr><th>Quando</th><th>Agente</th><th>Decisão</th><th>Motivo</th></tr></thead>'
        f'<tbody>{"".join(linhas)}</tbody>'
        '</table>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Renderização HTML
# ─────────────────────────────────────────────────────────────────────────────


def renderizar_html(dados: dict[str, Any]) -> str:
    t = dados["totais"]

    def _classe_anomalia(n: int) -> str:
        if n == 0:
            return "ok"
        if n < 5:
            return ""
        if n < 20:
            return "warn"
        return "danger"

    def _classe_url(blocked: int, total: int) -> str:
        if total == 0 or blocked == 0:
            return "ok"
        if blocked / total < 0.05:
            return ""
        return "warn"

    return (
        HTML_TEMPLATE.replace("{JANELA}", str(dados["janela_dias"]))
        .replace("{GERADO}", dados["gerado_em"])
        .replace("{TOT_EVENTOS}", f"{t['eventos']:,}".replace(",", "."))
        .replace("{TOT_ANOMALIAS}", str(t["anomalias"]))
        .replace("{ANOMALIAS_CLASS}", _classe_anomalia(t["anomalias"]))
        .replace("{TOT_TOOL}", f"{t['tool_calls']:,}".replace(",", "."))
        .replace("{TOT_FETCH}", str(t["url_fetches"]))
        .replace("{TOT_BLOCKED}", str(t["url_blocked"]))
        .replace("{URL_CLASS}", _classe_url(t["url_blocked"], t["url_fetches"]))
        .replace("{TABELA_ANOMALIAS}", _render_tabela_anomalias(dados["ultimas_anomalias"]))
        .replace("{TABELA_DECISOES}", _render_tabela_decisoes(dados["ultimas_decisoes"]))
        .replace("{DIAS_JSON}", json.dumps(dados["dias"]))
        .replace("{ANOMALIAS_POR_DIA_JSON}", json.dumps(dados["anomalias_por_dia"]))
        .replace("{EVENTOS_POR_DIA_JSON}", json.dumps(dados["eventos_por_dia"]))
        .replace("{SEVERITY_LABELS_JSON}", json.dumps(dados["severity_labels"]))
        .replace("{SEVERITY_DATA_JSON}", json.dumps(dados["severity_data"]))
        .replace("{TAGS_LABELS_JSON}", json.dumps(dados["tags_labels"]))
        .replace("{TAGS_DATA_JSON}", json.dumps(dados["tags_data"]))
        .replace("{AGENTES_LABELS_JSON}", json.dumps(dados["agentes_labels"]))
        .replace("{AGENTES_DATA_JSON}", json.dumps(dados["agentes_data"]))
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Gerador de dashboard de segurança Nexara")
    parser.add_argument(
        "--log",
        default="logs/security.jsonl",
        help="Caminho do JSONL (default: logs/security.jsonl)",
    )
    parser.add_argument(
        "--output",
        default="logs/security_dashboard.html",
        help="Caminho do HTML (default: logs/security_dashboard.html)",
    )
    parser.add_argument("--janela", type=int, default=30, help="Janela em dias (default: 30)")
    parser.add_argument("--open", action="store_true", help="Abre o HTML no browser ao final")
    args = parser.parse_args()

    log_path = Path(args.log)
    out_path = Path(args.output)

    print(f"[security_dashboard] Lendo {log_path}...")
    eventos = carregar_eventos(log_path, args.janela)
    print(f"[security_dashboard] {len(eventos)} eventos na janela de {args.janela} dias")

    dados = agregar(eventos, args.janela)
    html = renderizar_html(dados)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"[security_dashboard] HTML gerado: {out_path.resolve()}")
    print(f"[security_dashboard] Anomalias na janela: {dados['totais']['anomalias']}")

    if args.open:
        webbrowser.open(f"file://{out_path.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
