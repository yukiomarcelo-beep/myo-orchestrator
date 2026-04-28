#!/usr/bin/env python3
"""Gera HTML de pitch pra investidor a partir do PROJECT_TREE.yaml + CLAUDE.md.

Uso:
    python3 build_pitch.py --project forja
    python3 build_pitch.py --project forja --output /tmp/pitch.html

Por default escreve em ~/claude-dashboard/pitch-<project>.html.
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

HOME = Path.home()

PROJECTS = {
    "forja": {
        "dir": HOME / "forja",
        "emoji": "🔥",
        "accent": "#d97706",  # cobre inox
        "accent2": "#fbbf24",  # âmbar claro
        "bg_grad": "#0f0a06",  # grafite quase preto
        "bg_grad2": "#1a0f08",
        "ask": {
            "stage": "Seed Round",
            "amount": "R$ 2M",
            "use": "Contratar 2 devs full-stack, ir a mercado com 15 clientes em 6 meses.",
        },
    },
    "kitchen": {
        "dir": HOME / "kitchen",
        "emoji": "🍳",
        "accent": "#16a34a",
        "accent2": "#4ade80",
        "bg_grad": "#050f08",
        "bg_grad2": "#0a1a10",
        "ask": {
            "stage": "Pre-Seed",
            "amount": "R$ 500k",
            "use": "Onboardar 10 restaurantes-piloto e validar unit economics.",
        },
    },
    "myo": {
        "dir": HOME / "Documents/orchestrator",
        "emoji": "🤖",
        "accent": "#7c3aed",
        "accent2": "#c4b5fd",
        "bg_grad": "#0a0518",
        "bg_grad2": "#150a2e",
        "ask": {
            "stage": "Seed Round",
            "amount": "R$ 3M",
            "use": "Time, GPU/API credits, go-to-market B2B.",
        },
    },
    "sofia": {
        "dir": HOME / "evolution-api",
        "emoji": "📱",
        "accent": "#0891b2",
        "accent2": "#67e8f9",
        "bg_grad": "#04101a",
        "bg_grad2": "#081a28",
        "ask": {
            "stage": "Bootstrapping",
            "amount": "—",
            "use": "Operado como spin-off de serviço interno da Mali Travel.",
        },
    },
}


def h(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{path} não existe")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def extract_claude_section(md_text: str, heading_regex: str) -> str:
    """Extrai o conteúdo de uma seção markdown dado um regex do heading."""
    pattern = re.compile(
        rf"^{heading_regex}.*?$(.+?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(md_text)
    return m.group(1).strip() if m else ""


def count_status(modules: list) -> dict:
    acc = {"done": 0, "building": 0, "planned": 0, "idea": 0, "paused": 0}
    stack = list(modules or [])
    while stack:
        n = stack.pop()
        s = n.get("status", "idea")
        if s in acc:
            acc[s] += 1
        stack.extend(n.get("children") or [])
    return acc


def build_html(project_key: str, yaml_data: dict, claude_md: str) -> str:
    cfg = PROJECTS[project_key]
    name = yaml_data.get("name", project_key.title())
    tagline = yaml_data.get("tagline", "")
    vision = (yaml_data.get("vision") or "").strip()
    version = yaml_data.get("version", "")
    modules = yaml_data.get("modules") or []
    counts = count_status(modules)
    total_modules = sum(counts.values())
    done_pct = int(100 * counts["done"] / total_modules) if total_modules else 0

    # Hero stats
    hero_stats = [
        ("📦", str(total_modules), "módulos mapeados"),
        ("✅", str(counts["done"]), "entregues"),
        ("🔨", str(counts["building"]), "em construção"),
        ("💡", str(counts["idea"]), "ideias"),
    ]

    # Extrai informação do CLAUDE.md se presente
    stack = extract_claude_section(claude_md, r"## (Stack|Tech\s*Stack|Tecnologia)")
    problem = extract_claude_section(claude_md, r"## (Problema|Problem|Anti-padr)")
    differential = extract_claude_section(
        claude_md, r"## (Motor|Differential|Diferencial|Arquitetura)"
    )

    # Fases (roots do YAML com 'fase' no id ou name)
    phases = []
    for m in modules:
        mid = (m.get("id") or "").lower()
        mname = (m.get("name") or "").lower()
        if "fase" in mid or "fase" in mname or "phase" in mid:
            c = count_status([m])
            phases.append(
                {
                    "name": m.get("name"),
                    "status": m.get("status"),
                    "done": c["done"],
                    "total": sum(c.values()),
                    "why_now": m.get("why_now", ""),
                    "notes": m.get("notes", ""),
                }
            )

    # Módulos totais (pitch fala mais alto se for número redondo de módulos principais)
    primary_modules = modules[:12]

    # Ask
    ask = cfg["ask"]

    # Destaque principal (o diferencial técnico marcante)
    # Pro Forja: motor 7 camadas (32% vs 14%)
    HIGHLIGHT = {}
    if project_key == "forja":
        HIGHLIGHT = {
            "big_stat_left": "14%",
            "big_stat_left_label": "margem ilusória",
            "big_stat_left_sub": "cálculo sobre custo, esquece desperdício, erra impostos",
            "big_stat_right": "32%",
            "big_stat_right_label": "margem real",
            "big_stat_right_sub": "Forja aplica motor de 7 camadas",
            "delta": "+18 p.p.",
            "delta_label": "diferença no bottom-line",
        }

    stamp = datetime.now().strftime("%d/%m/%Y")

    # Build HTML
    css = build_css(cfg)
    body = build_body(
        project_key=project_key,
        cfg=cfg,
        name=name,
        tagline=tagline,
        vision=vision,
        version=version,
        hero_stats=hero_stats,
        phases=phases,
        primary_modules=primary_modules,
        counts=counts,
        done_pct=done_pct,
        ask=ask,
        highlight=HIGHLIGHT,
        problem=problem,
        differential=differential,
        stack=stack,
        stamp=stamp,
    )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{h(name)} · Pitch Investidor</title>
<meta name="theme-color" content="{cfg['bg_grad']}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Bebas+Neue&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>{body}</body>
</html>"""


def build_css(cfg: dict) -> str:
    a = cfg["accent"]
    a2 = cfg["accent2"]
    bg = cfg["bg_grad"]
    bg2 = cfg["bg_grad2"]
    return f"""
:root{{--a:{a};--a2:{a2};--bg:{bg};--bg2:{bg2};--text:#f4ecd8;--mute:#9a8a75;--mute2:#c9b998}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
body{{background:radial-gradient(ellipse at 30% 0%,var(--bg2),var(--bg) 60%),var(--bg);color:var(--text);
  font-family:'Inter',system-ui,sans-serif;-webkit-font-smoothing:antialiased;line-height:1.6;min-height:100vh}}
section{{min-height:95vh;padding:64px 32px;display:flex;flex-direction:column;justify-content:center;
  position:relative;border-bottom:1px solid rgba(217,119,6,.1)}}
section.compact{{min-height:auto;padding:48px 32px}}
.container{{max-width:1080px;margin:0 auto;width:100%}}
.eyebrow{{font-size:11px;font-weight:800;color:var(--a2);text-transform:uppercase;letter-spacing:3px;margin-bottom:16px;opacity:.85}}
h1{{font-family:'Bebas Neue',sans-serif;font-size:clamp(60px,12vw,160px);line-height:.92;letter-spacing:-1px;
  background:linear-gradient(135deg,#fff 20%,var(--a2) 50%,var(--a));-webkit-background-clip:text;background-clip:text;color:transparent;margin-bottom:14px}}
h2{{font-family:'Bebas Neue',sans-serif;font-size:clamp(36px,6vw,72px);line-height:1;color:var(--text);margin-bottom:24px;letter-spacing:-.5px}}
h3{{font-size:20px;font-weight:700;color:var(--text);margin-bottom:10px}}
p.tagline{{font-size:clamp(18px,3vw,28px);color:var(--mute2);font-weight:400;margin-bottom:32px;max-width:780px}}
p.lead{{font-size:17px;color:var(--mute2);max-width:720px;margin-bottom:22px}}
p{{color:var(--mute2)}}

.hero-badge{{display:inline-flex;align-items:center;gap:10px;background:rgba(217,119,6,.08);border:1px solid var(--a);
  padding:10px 18px;border-radius:40px;font-size:12px;font-weight:600;color:var(--a2);letter-spacing:1px;margin-bottom:28px}}
.hero-dot{{width:8px;height:8px;border-radius:50%;background:var(--a2);box-shadow:0 0 12px var(--a2);animation:pulse 2s infinite}}
@keyframes pulse{{50%{{opacity:.35}}}}

.hero-stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-top:48px}}
.hero-stat{{padding:18px 20px;background:rgba(244,236,216,.03);border:1px solid rgba(217,119,6,.2);border-radius:10px}}
.hero-stat .n{{font-family:'Bebas Neue';font-size:40px;color:var(--a2);line-height:1}}
.hero-stat .e{{font-size:22px;margin-bottom:4px;opacity:.6}}
.hero-stat .l{{font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:1px;margin-top:4px;font-weight:600}}

.compare{{display:grid;grid-template-columns:1fr auto 1fr;gap:32px;align-items:center;margin-top:32px}}
.compare-box{{padding:40px 28px;border-radius:16px;text-align:center;border:1px solid;transition:transform .3s}}
.compare-box.bad{{background:rgba(239,68,68,.05);border-color:rgba(239,68,68,.3)}}
.compare-box.good{{background:rgba(217,119,6,.08);border-color:var(--a);box-shadow:0 0 60px rgba(217,119,6,.15)}}
.compare-stat{{font-family:'Bebas Neue';font-size:clamp(80px,14vw,140px);line-height:.9;margin-bottom:10px}}
.compare-box.bad .compare-stat{{color:#f87171}}
.compare-box.good .compare-stat{{color:var(--a2)}}
.compare-label{{font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:2px;margin-bottom:12px}}
.compare-box.bad .compare-label{{color:#fca5a5}}
.compare-box.good .compare-label{{color:var(--a2)}}
.compare-sub{{font-size:12px;color:var(--mute);line-height:1.5}}
.compare-arrow{{font-family:'Bebas Neue';font-size:46px;color:var(--a);writing-mode:horizontal-tb}}
.delta{{margin-top:32px;text-align:center;padding:18px;background:linear-gradient(90deg,transparent,rgba(217,119,6,.1),transparent);border-radius:8px}}
.delta-n{{font-family:'Bebas Neue';font-size:52px;color:var(--a2);display:inline-block;margin-right:14px}}
.delta-l{{font-size:13px;color:var(--mute);text-transform:uppercase;letter-spacing:2px}}

.layers{{counter-reset:layer;display:grid;gap:10px;margin-top:28px}}
.layer{{counter-increment:layer;background:rgba(244,236,216,.03);border:1px solid rgba(217,119,6,.18);
  border-radius:10px;padding:18px 22px;display:flex;align-items:center;gap:16px;transition:all .2s}}
.layer:hover{{border-color:var(--a);transform:translateX(8px);box-shadow:-4px 0 0 var(--a)}}
.layer::before{{content:counter(layer,decimal-leading-zero);font-family:'Bebas Neue';font-size:32px;color:var(--a);min-width:50px}}
.layer .text{{flex:1}}
.layer .text b{{color:var(--text);font-weight:700;font-size:15px}}
.layer .text .meta{{font-size:12px;color:var(--mute);margin-top:2px}}
.layer.key{{background:linear-gradient(90deg,rgba(217,119,6,.15),transparent);border-color:var(--a);border-left:4px solid var(--a)}}
.layer.key::before{{color:var(--a2)}}

.modules-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:24px}}
.module-card{{background:rgba(244,236,216,.03);border:1px solid rgba(217,119,6,.15);border-radius:8px;padding:16px}}
.module-card .t{{font-size:14px;font-weight:600;color:var(--text);margin-bottom:6px}}
.module-card .s{{font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:1px}}

.roadmap-timeline{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-top:24px}}
.roadmap-phase{{background:rgba(244,236,216,.03);border:1px solid rgba(217,119,6,.2);border-radius:12px;padding:22px;position:relative}}
.roadmap-phase::before{{content:'';position:absolute;top:-1px;left:0;right:0;height:3px;background:var(--c,var(--a));border-radius:12px 12px 0 0}}
.roadmap-phase.status-done{{--c:#22c55e}}
.roadmap-phase.status-building{{--c:#ffb800}}
.roadmap-phase.status-planned{{--c:#5b9cff}}
.roadmap-phase.status-idea{{--c:#c060ff}}
.roadmap-phase.status-paused{{--c:#ef4444}}
.roadmap-phase h4{{font-size:15px;font-weight:700;margin-bottom:8px;color:var(--text)}}
.roadmap-phase .pct{{font-family:'Bebas Neue';font-size:36px;color:var(--c);line-height:1;margin-bottom:4px}}
.roadmap-phase .meta{{font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:1px}}
.roadmap-phase .note{{font-size:12px;color:var(--mute2);margin-top:10px;padding-top:10px;border-top:1px solid rgba(217,119,6,.15);line-height:1.5}}

.ask-card{{background:linear-gradient(135deg,rgba(217,119,6,.15),rgba(251,191,36,.05));border:1px solid var(--a);
  border-radius:20px;padding:48px 36px;text-align:center;max-width:720px;margin:32px auto 0}}
.ask-stage{{font-size:12px;color:var(--a2);font-weight:800;text-transform:uppercase;letter-spacing:3px;margin-bottom:12px}}
.ask-amount{{font-family:'Bebas Neue';font-size:clamp(64px,11vw,120px);color:var(--text);line-height:1;margin-bottom:16px}}
.ask-use{{font-size:16px;color:var(--mute2);max-width:540px;margin:0 auto}}

.foot{{text-align:center;padding:40px 24px;color:var(--mute);font-size:11px;border-top:1px solid rgba(217,119,6,.15)}}
.foot code{{font-family:'SF Mono',Menlo,monospace;color:var(--a2);background:rgba(217,119,6,.08);padding:2px 7px;border-radius:4px}}

@media(max-width:680px){{
  section{{padding:56px 24px;min-height:auto}}
  .compare{{grid-template-columns:1fr;gap:14px}}
  .compare-arrow{{transform:rotate(90deg);font-size:32px;margin:8px auto}}
  h1{{font-size:64px}}
  p.tagline{{font-size:17px}}
  .ask-card{{padding:32px 22px}}
}}
"""


def build_body(
    project_key,
    cfg,
    name,
    tagline,
    vision,
    version,
    hero_stats,
    phases,
    primary_modules,
    counts,
    done_pct,
    ask,
    highlight,
    problem,
    differential,
    stack,
    stamp,
):
    emoji = cfg["emoji"]

    # HERO
    stats_html = "".join(
        f'<div class="hero-stat"><div class="e">{e}</div><div class="n">{h(n)}</div><div class="l">{h(l)}</div></div>'
        for e, n, l in hero_stats
    )
    hero = f"""
<section id="hero">
  <div class="container">
    <div class="hero-badge"><span class="hero-dot"></span>{h(version) or "Pitch atualizado " + h(stamp)}</div>
    <h1>{h(name)}</h1>
    <p class="tagline">{h(tagline)}</p>
    {f'<p class="lead">{h(vision)}</p>' if vision else ''}
    <div class="hero-stats">{stats_html}</div>
  </div>
</section>"""

    # COMPARE (destaque quando tem highlight configurado — ex Forja)
    compare = ""
    if highlight:
        compare = f"""
<section id="problema">
  <div class="container">
    <div class="eyebrow">O Problema</div>
    <h2>A indústria calcula margem errado</h2>
    <p class="lead">Metalúrgicas de inox achum que lucram 14% quando na verdade estão vendendo no vermelho.
    O motor de precificação que cada oficina usa ignora desperdício real, mistura hora/homem com hora/máquina
    e aplica margem sobre custo em vez de sobre preço. Em 6 meses, a conta não fecha.</p>
    <div class="compare">
      <div class="compare-box bad">
        <div class="compare-stat">{h(highlight["big_stat_left"])}</div>
        <div class="compare-label">{h(highlight["big_stat_left_label"])}</div>
        <div class="compare-sub">{h(highlight["big_stat_left_sub"])}</div>
      </div>
      <div class="compare-arrow">→</div>
      <div class="compare-box good">
        <div class="compare-stat">{h(highlight["big_stat_right"])}</div>
        <div class="compare-label">{h(highlight["big_stat_right_label"])}</div>
        <div class="compare-sub">{h(highlight["big_stat_right_sub"])}</div>
      </div>
    </div>
    <div class="delta">
      <span class="delta-n">{h(highlight["delta"])}</span>
      <span class="delta-l">{h(highlight["delta_label"])}</span>
    </div>
  </div>
</section>"""

    # DIFERENCIAL — motor 7 camadas (Forja específico)
    differential_html = ""
    if project_key == "forja":
        # Extrai motor do YAML
        motor_children = []
        for m in primary_modules:
            for c in m.get("children") or []:
                if "motor" in (c.get("id") or "").lower():
                    motor_children = c.get("children") or []
                    break
            if motor_children:
                break
        if motor_children:
            layers_html = []
            for i, layer in enumerate(motor_children, 1):
                is_key = i == 7
                cls = "layer key" if is_key else "layer"
                nm = layer.get("name", "")
                # Separa "Camada N · Nome" se tiver
                clean = re.sub(r"^Camada\s+\d+\s*[·:\-—]?\s*", "", nm).strip()
                key_label = (
                    ' <span style="background:var(--a);color:#000;padding:2px 8px;border-radius:4px;font-size:10px;margin-left:10px;font-weight:800;letter-spacing:1px">INVIOLÁVEL</span>'
                    if is_key
                    else ""
                )
                layers_html.append(
                    f'<div class="{cls}"><div class="text"><b>{h(clean)}{key_label}</b></div></div>'
                )
            differential_html = f"""
<section id="diferencial">
  <div class="container">
    <div class="eyebrow">O Diferencial Forja</div>
    <h2>Motor de 7 camadas</h2>
    <p class="lead">Nenhum ERP genérico aplica todas essas camadas na ordem certa. A sétima — margem sobre preço,
    nunca sobre custo — é a regra inviolável que destrói a margem de quem erra.</p>
    <div class="layers">{"".join(layers_html)}</div>
  </div>
</section>"""

    # SOLUÇÃO — grade de módulos
    modules_cards = "".join(
        f'<div class="module-card"><div class="t">{h(m.get("name",""))}</div>'
        f'<div class="s">{h(m.get("status",""))}</div></div>'
        for m in primary_modules
    )
    solution = f"""
<section id="solucao" class="compact">
  <div class="container">
    <div class="eyebrow">A Solução</div>
    <h2>ERP integrado do orçamento ao BI</h2>
    <p class="lead">Não é mais uma planilha, nem uma calculadora solta. {h(name)} conecta {len(primary_modules)} módulos
    em pipeline único — orçamento aprovado vira OP, OP consome estoque, estoque dispara compra,
    compra vira financeiro, tudo em um sistema que fala a mesma língua.</p>
    <div class="modules-grid">{modules_cards}</div>
  </div>
</section>"""

    # ROADMAP — fases
    roadmap_html = ""
    if phases:
        cards = []
        for p in phases:
            pct = int(100 * p["done"] / p["total"]) if p["total"] else 0
            status_label = {
                "done": "entregue",
                "building": "em construção",
                "planned": "próximo",
                "idea": "conceito",
                "paused": "aguardando",
            }.get(p["status"], p["status"])
            note = p["why_now"] or p["notes"] or ""
            cards.append(
                f'<div class="roadmap-phase status-{p["status"]}">'
                f'<h4>{h(p["name"])}</h4>'
                f'<div class="pct">{pct}%</div>'
                f'<div class="meta">{p["done"]}/{p["total"]} itens · {status_label}</div>'
                f'{f"<div class=\"note\">{h(note)}</div>" if note else ""}'
                f'</div>'
            )
        roadmap_html = f"""
<section id="roadmap" class="compact">
  <div class="container">
    <div class="eyebrow">Roadmap</div>
    <h2>4 fases em 12 semanas</h2>
    <p class="lead">Plano executável. Cliente pagante já ancorou Fase 1. Cada fase entrega algo vendável por si só.</p>
    <div class="roadmap-timeline">{"".join(cards)}</div>
  </div>
</section>"""

    # TRAÇÃO
    tracao = f"""
<section id="tracao" class="compact">
  <div class="container">
    <div class="eyebrow">Tração</div>
    <h2>Cliente pagante ativo</h2>
    <p class="lead">Não estamos validando hipótese no papel. Contrato assinado, Fase 1 em construção,
    dados operacionais reais sendo coletados. O próximo cliente vem da indicação do primeiro.</p>
    <div class="hero-stats" style="margin-top:32px">
      <div class="hero-stat"><div class="n">{counts["done"]}/{sum(counts.values())}</div><div class="l">módulos prontos</div></div>
      <div class="hero-stat"><div class="n">1</div><div class="l">cliente pagante</div></div>
      <div class="hero-stat"><div class="n">22</div><div class="l">entidades modeladas</div></div>
      <div class="hero-stat"><div class="n">{done_pct}%</div><div class="l">progresso geral</div></div>
    </div>
  </div>
</section>"""

    # ASK
    ask_html = f"""
<section id="ask">
  <div class="container">
    <div class="eyebrow" style="text-align:center">A Proposta</div>
    <h2 style="text-align:center">Estamos buscando</h2>
    <div class="ask-card">
      <div class="ask-stage">{h(ask["stage"])}</div>
      <div class="ask-amount">{h(ask["amount"])}</div>
      <div class="ask-use">{h(ask["use"])}</div>
    </div>
  </div>
</section>"""

    foot = f"""
<footer class="foot">
  {h(emoji)} {h(name)} · pitch gerado em {h(stamp)} ·
  <code>build_pitch.py --project {h(project_key)}</code>
</footer>"""

    return hero + compare + differential_html + solution + roadmap_html + tracao + ask_html + foot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, choices=list(PROJECTS))
    ap.add_argument(
        "--output",
        default=None,
        help="caminho do HTML (default: ~/claude-dashboard/pitch-<project>.html)",
    )
    args = ap.parse_args()

    cfg = PROJECTS[args.project]
    yaml_path = cfg["dir"] / "PROJECT_TREE.yaml"
    claude_md = cfg["dir"] / "CLAUDE.md"

    data = load_yaml(yaml_path)
    md = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""

    html = build_html(args.project, data, md)

    out = Path(args.output) if args.output else HOME / f"claude-dashboard/pitch-{args.project}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    print(f"✓ pitch gerado: {out}")
    print(f"  tamanho: {out.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
