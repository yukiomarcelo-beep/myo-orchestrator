#!/usr/bin/env python3
"""Gera dashboard HTML standalone com inventário completo do setup Claude Code.

Lê:
- ~/.claude.json (MCPs)
- ~/.claude/agents/*.md
- ~/.claude/commands/*.md
- ~/.claude/hooks/*.{sh,py}
- ~/.claude/settings.json (hooks config + effortLevel)
- ~/.claude/settings.local.json (permissions allowlist)
- ~/.claude/projects/-Users-marceloyukio/memory/**/*.md
- CLAUDE.md dos 3 projetos

Saída: claude_setup.html (~/Documents/orchestrator/).
Abre com: open claude_setup.html
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from extract_roadmap import scan_all as scan_roadmap

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
CLAUDE_CONFIG = HOME / ".claude.json"
MEMORY_DIR = CLAUDE_DIR / "projects/-Users-marceloyukio/memory"

OUT = Path("/Users/marceloyukio/Documents/orchestrator/claude_setup.html")

STRUCTURE_PATHS = [
    ("forja", HOME / "forja/PROJECT_TREE.yaml", "🔥"),
    ("kitchen", HOME / "kitchen/PROJECT_TREE.yaml", "🍳"),
    ("myo", HOME / "Documents/orchestrator/PROJECT_TREE.yaml", "🤖"),
    ("sofia", HOME / "evolution-api/PROJECT_TREE.yaml", "📱"),
]

STATUS_META = {
    "done": {"emoji": "✅", "color": "#39ff14", "label": "pronto"},
    "building": {"emoji": "🔨", "color": "#ffb800", "label": "em construção"},
    "planned": {"emoji": "📋", "color": "#5b9cff", "label": "planejado"},
    "idea": {"emoji": "💡", "color": "#c060ff", "label": "ideia"},
    "paused": {"emoji": "⏸", "color": "#ff4444", "label": "pausado"},
}


def parse_frontmatter(content: str) -> dict:
    m = re.match(r"---\n(.*?)\n---", content, re.DOTALL)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.strip().startswith("#"):
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
    return meta


def scan_mcps() -> list:
    if not CLAUDE_CONFIG.exists():
        return []
    data = json.loads(CLAUDE_CONFIG.read_text())
    mcps = data.get("mcpServers", {}) or {}
    result = []
    # MCP remotos (do claude.ai) — ler via claude mcp list
    remote_mcps = []
    try:
        proc = subprocess.run(["claude", "mcp", "list"], capture_output=True, text=True, timeout=30)
        for line in proc.stdout.splitlines():
            if "claude.ai " in line:
                name_part = line.split("claude.ai ")[1].split(":")[0].strip()
                status = (
                    "connected"
                    if "✓ Connected" in line
                    else ("auth_needed" if "Needs authentication" in line else "failed")
                )
                remote_mcps.append(
                    {
                        "name": name_part,
                        "command": "(remote claude.ai)",
                        "scope": "remote",
                        "status": status,
                    }
                )
    except Exception:
        pass

    for name, conf in mcps.items():
        if isinstance(conf, dict):
            cmd = conf.get("command", "")
            args = conf.get("args", []) or []
            full = (cmd + " " + " ".join(str(a) for a in args)).strip()
        else:
            full = str(conf)
        result.append(
            {
                "name": name,
                "command": full,
                "scope": "local",
                "status": "unknown",
            }
        )

    return remote_mcps + result


def scan_agents() -> list:
    d = CLAUDE_DIR / "agents"
    if not d.exists():
        return []
    result = []
    for f in sorted(d.glob("*.md")):
        meta = parse_frontmatter(f.read_text())
        result.append(
            {
                "name": f.stem,
                "description": meta.get("description", "").strip('"').strip("'")[:240],
                "model": meta.get("model", "inherit"),
                "size_kb": round(f.stat().st_size / 1024, 1),
            }
        )
    return result


def scan_commands() -> list:
    d = CLAUDE_DIR / "commands"
    if not d.exists():
        return []
    result = []
    for f in sorted(d.glob("*.md")):
        meta = parse_frontmatter(f.read_text())
        result.append(
            {
                "name": f"/{f.stem}",
                "description": meta.get("description", "").strip('"').strip("'")[:240],
                "args": meta.get("argument-hint", "").strip('"').strip("'"),
            }
        )
    return result


def scan_hooks() -> dict:
    settings_path = CLAUDE_DIR / "settings.json"
    if not settings_path.exists():
        return {"events": [], "scripts": []}
    settings = json.loads(settings_path.read_text())
    events = []
    for event_name, entries in (settings.get("hooks") or {}).items():
        for entry in entries:
            for h in entry.get("hooks", []):
                events.append(
                    {
                        "event": event_name,
                        "matcher": entry.get("matcher", ""),
                        "command": h.get("command", "")[:200],
                    }
                )
    scripts = []
    hooks_dir = CLAUDE_DIR / "hooks"
    if hooks_dir.exists():
        for f in sorted(hooks_dir.iterdir()):
            if f.is_file():
                scripts.append(
                    {
                        "name": f.name,
                        "size_kb": round(f.stat().st_size / 1024, 1),
                        "executable": os.access(f, os.X_OK),
                    }
                )
    return {
        "events": events,
        "scripts": scripts,
        "statusLine": (settings.get("statusLine") or {}).get("command", "") or None,
        "effortLevel": settings.get("effortLevel", "default"),
    }


def scan_memory() -> dict:
    if not MEMORY_DIR.exists():
        return {"global": [], "projects": {}}
    global_files = []
    gdir = MEMORY_DIR / "global"
    if gdir.exists():
        for f in sorted(gdir.glob("*.md")):
            meta = parse_frontmatter(f.read_text())
            age_days = (datetime.now().timestamp() - f.stat().st_mtime) / 86400
            global_files.append(
                {
                    "name": f.stem,
                    "type": meta.get("type", "?"),
                    "description": meta.get("description", "")[:200],
                    "age_days": int(age_days),
                }
            )
    projects = {}
    pdir = MEMORY_DIR / "projetos"
    if pdir.exists():
        for subdir in sorted(pdir.iterdir()):
            if subdir.is_dir():
                files = []
                for f in sorted(subdir.glob("*.md")):
                    age_days = (datetime.now().timestamp() - f.stat().st_mtime) / 86400
                    files.append(
                        {
                            "name": f.stem,
                            "age_days": int(age_days),
                            "size_kb": round(f.stat().st_size / 1024, 1),
                        }
                    )
                projects[subdir.name] = files
    return {"global": global_files, "projects": projects}


def scan_claude_md() -> list:
    paths = [
        HOME / "kitchen/CLAUDE.md",
        HOME / "Documents/orchestrator/CLAUDE.md",
        HOME / "evolution-api/CLAUDE.md",
        HOME / "forja/CLAUDE.md",
    ]
    result = []
    for p in paths:
        if p.exists():
            age_days = (datetime.now().timestamp() - p.stat().st_mtime) / 86400
            result.append(
                {
                    "project": p.parent.name,
                    "path": str(p),
                    "size_kb": round(p.stat().st_size / 1024, 1),
                    "age_days": int(age_days),
                }
            )
    return result


def scan_structure() -> list:
    """Lê os PROJECT_TREE.yaml dos 4 projetos e devolve lista estruturada."""
    out = []
    for key, path, emoji in STRUCTURE_PATHS:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            data = {"name": key, "_error": str(e)}
        data["_key"] = key
        data["_emoji"] = emoji
        data["_path"] = str(path)
        out.append(data)
    return out


def _count_status(modules: list, acc: dict | None = None) -> dict:
    acc = acc or {k: 0 for k in STATUS_META}
    for m in modules or []:
        s = m.get("status", "idea")
        if s in acc:
            acc[s] += 1
        _count_status(m.get("children") or [], acc)
    return acc


def render_structure_tree(projects: list) -> str:
    """Árvore colapsável (modo A)."""

    def render_node(node: dict, level: int = 0) -> str:
        status = node.get("status", "idea")
        meta = STATUS_META.get(status, STATUS_META["idea"])
        name = h(node.get("name", node.get("id", "?")))
        notes = node.get("notes", "")
        priority = node.get("priority")
        children = node.get("children") or []

        has_children = bool(children)
        caret = (
            '<span class="tv-caret">▸</span>'
            if has_children
            else '<span class="tv-caret-empty"></span>'
        )
        badge_pri = f'<span class="tv-pri">P{priority}</span>' if priority else ""
        notes_html = f'<div class="tv-notes">{h(notes)}</div>' if notes else ""

        head = (
            f'<div class="tv-node tv-status-{status}" data-level="{level}">'
            f'  <div class="tv-row" onclick="this.parentElement.classList.toggle(\'tv-open\')">'
            f'    {caret}'
            f'    <span class="tv-emoji">{meta["emoji"]}</span>'
            f'    <span class="tv-name">{name}</span>'
            f'    {badge_pri}'
            f'    <span class="tv-status-pill" style="background:{meta["color"]}22;color:{meta["color"]};border:1px solid {meta["color"]}55">{meta["label"]}</span>'
            f'  </div>'
            f'  {notes_html}'
        )
        if has_children:
            body = (
                '<div class="tv-children">'
                + "".join(render_node(c, level + 1) for c in children)
                + "</div>"
            )
        else:
            body = ""
        return head + body + "</div>"

    cards = []
    for p in projects:
        if "_error" in p:
            cards.append(
                f'<div class="struct-card"><div class="struct-header"><h3>{h(p.get("_emoji",""))} {h(p.get("name",""))}</h3></div><div class="empty-state">Erro ao ler YAML: {h(p["_error"])}</div></div>'
            )
            continue
        modules = p.get("modules") or []
        counts = _count_status(modules)
        total = sum(counts.values())
        tagline = h(p.get("tagline", ""))
        vision = h((p.get("vision") or "").strip())
        focus = h(p.get("current_focus", ""))
        version = h(p.get("version", ""))
        emoji = h(p.get("_emoji", ""))
        name = h(p.get("name", ""))

        chips = []
        for status, meta in STATUS_META.items():
            n = counts.get(status, 0)
            if n == 0:
                continue
            chips.append(
                f'<span class="struct-chip" style="background:{meta["color"]}18;color:{meta["color"]};border:1px solid {meta["color"]}44">'
                f'{meta["emoji"]} {n} {meta["label"]}</span>'
            )
        chips_html = "".join(chips)

        tree_html = "".join(render_node(m) for m in modules)
        inbox = p.get("inbox") or []
        inbox_html = ""
        if inbox:
            items = "".join(
                f'<div class="tv-inbox-item">💭 {h(str(it))}</div>' for it in inbox[:10]
            )
            inbox_html = f'<div class="tv-inbox-box"><div class="tv-inbox-title">Inbox · {len(inbox)} ideias novas (Telegram)</div>{items}</div>'

        cards.append(
            f'<div class="struct-card">'
            f'  <div class="struct-header">'
            f'    <div><h3>{emoji} {name}</h3><div class="struct-tagline">{tagline}</div></div>'
            f'    <div class="struct-version">{version}</div>'
            f'  </div>'
            f'  {f"<div class=\"struct-vision\">{vision}</div>" if vision else ""}'
            f'  {f"<div class=\"struct-focus\">🎯 foco atual: <b>{focus}</b></div>" if focus else ""}'
            f'  <div class="struct-chips">{chips_html}<span class="struct-chip struct-chip-total">Σ {total}</span></div>'
            f'  <div class="struct-tree">{tree_html}</div>'
            f'  {inbox_html}'
            f'</div>'
        )
    return "\n".join(cards)


def _deep_counts(node: dict) -> dict:
    """Conta status de um nó + todos descendentes."""
    counts = {k: 0 for k in STATUS_META}
    stack = [node]
    while stack:
        n = stack.pop()
        s = n.get("status", "idea")
        if s in counts:
            counts[s] += 1
        stack.extend(n.get("children") or [])
    return counts


def render_structure_executive(projects: list) -> str:
    """Roadmap executivo — cards grandes por fase/módulo, visual pitch-ready."""
    sections = []
    for p in projects:
        if "_error" in p:
            continue
        emoji = h(p.get("_emoji", ""))
        name = h(p.get("name", ""))
        tagline = h(p.get("tagline", ""))
        vision = h((p.get("vision") or "").strip())
        focus = h(p.get("current_focus", ""))
        version = h(p.get("version", ""))
        modules = p.get("modules") or []

        # Overall progress
        proj_counts = {k: 0 for k in STATUS_META}
        for m in modules:
            for k, v in _deep_counts(m).items():
                proj_counts[k] += v
        proj_total = sum(proj_counts.values())
        proj_done = proj_counts["done"]
        proj_pct = int(100 * proj_done / proj_total) if proj_total else 0

        # Phase cards (root modules)
        phase_cards = []
        for mod in modules:
            counts = _deep_counts(mod)
            total = sum(counts.values())
            done = counts["done"]
            pct = int(100 * done / total) if total else 0
            status = mod.get("status", "idea")
            meta = STATUS_META.get(status, STATUS_META["idea"])
            mod_name = h(mod.get("name", ""))
            mod_notes = h(mod.get("notes", ""))
            priority = mod.get("priority")
            pri_html = f'<span class="ex-pri">P{priority}</span>' if priority else ""

            # First-level children as mini-rows
            children = mod.get("children") or []
            child_rows = []
            for c in children[:8]:
                c_status = c.get("status", "idea")
                c_meta = STATUS_META.get(c_status, STATUS_META["idea"])
                c_counts = _deep_counts(c)
                c_total = sum(c_counts.values())
                c_done = c_counts["done"]
                c_pct = int(100 * c_done / c_total) if c_total else 0
                c_has_kids = bool(c.get("children"))
                progress_html = (
                    f'<span class="ex-mini-prog"><span class="ex-mini-bar" style="width:{c_pct}%;background:{c_meta["color"]}"></span></span>'
                    if c_has_kids
                    else ""
                )
                child_rows.append(
                    f'<div class="ex-child" style="border-left-color:{c_meta["color"]}">'
                    f'  <span class="ex-child-dot" style="background:{c_meta["color"]}"></span>'
                    f'  <span class="ex-child-name">{h(c.get("name", ""))}</span>'
                    f'  {progress_html}'
                    f'</div>'
                )
            if len(children) > 8:
                child_rows.append(
                    f'<div class="ex-child ex-child-more">+ {len(children)-8} itens…</div>'
                )

            phase_cards.append(
                f'<div class="ex-phase" style="border-top-color:{meta["color"]}">'
                f'  <div class="ex-phase-head">'
                f'    <div class="ex-phase-title">{mod_name}</div>'
                f'    <div class="ex-phase-tags">{pri_html}<span class="ex-phase-status" style="background:{meta["color"]}22;color:{meta["color"]};border-color:{meta["color"]}55">{meta["emoji"]} {meta["label"]}</span></div>'
                f'  </div>'
                f'  <div class="ex-phase-prog">'
                f'    <div class="ex-phase-bar-wrap"><div class="ex-phase-bar" style="width:{pct}%;background:linear-gradient(90deg,{meta["color"]}aa,{meta["color"]})"></div></div>'
                f'    <div class="ex-phase-pct">{done}/{total} · {pct}%</div>'
                f'  </div>'
                f'  {f"<div class=\"ex-phase-notes\">{mod_notes}</div>" if mod_notes else ""}'
                f'  <div class="ex-children">{"".join(child_rows) if child_rows else "<div class=\"ex-empty\">sem sub-itens</div>"}</div>'
                f'</div>'
            )

        inbox = p.get("inbox") or []
        inbox_html = ""
        if inbox:
            item_html = []
            for it in inbox[:20]:
                if isinstance(it, dict):
                    txt = h(it.get("text", ""))
                    meta = f'<div class="ex-inbox-meta">via {h(it.get("source",""))} · {h(str(it.get("captured_at",""))[:16])}</div>'
                else:
                    txt = h(str(it))
                    meta = ""
                item_html.append(
                    f'<div class="ex-inbox-item"><span class="ex-inbox-dot">💭</span>'
                    f'<div><div class="ex-inbox-text">{txt}</div>{meta}</div></div>'
                )
            inbox_html = (
                f'<div class="ex-inbox">'
                f'  <div class="ex-inbox-title">💡 Ideias capturadas · {len(inbox)} no inbox</div>'
                f'  {"".join(item_html)}'
                f'</div>'
            )

        # Overall badge
        chips = []
        for status, meta in STATUS_META.items():
            n = proj_counts.get(status, 0)
            if n == 0:
                continue
            chips.append(
                f'<span class="ex-chip" style="background:{meta["color"]}18;color:{meta["color"]};border:1px solid {meta["color"]}44">'
                f'{meta["emoji"]} {n}</span>'
            )

        sections.append(
            f'<section class="ex-project">'
            f'  <div class="ex-project-head">'
            f'    <div class="ex-project-title-wrap">'
            f'      <div class="ex-project-emoji">{emoji}</div>'
            f'      <div>'
            f'        <h2 class="ex-project-title">{name}</h2>'
            f'        <div class="ex-project-tagline">{tagline}</div>'
            f'      </div>'
            f'    </div>'
            f'    <div class="ex-project-meta">'
            f'      <div class="ex-project-version">{version}</div>'
            f'      <div class="ex-project-overall">{proj_done}/{proj_total} · {proj_pct}%</div>'
            f'    </div>'
            f'  </div>'
            f'  {f"<div class=\"ex-project-vision\">{vision}</div>" if vision else ""}'
            f'  {f"<div class=\"ex-project-focus\">🎯 Foco atual: <b>{focus}</b></div>" if focus else ""}'
            f'  <div class="ex-project-chips">{"".join(chips)}</div>'
            f'  <div class="ex-phases">{"".join(phase_cards)}</div>'
            f'  {inbox_html}'
            f'</section>'
        )

    return (
        f'<div class="ex-tabs-wrap">'
        f'  <div class="ex-legend">'
        f'    <span class="ex-legend-item"><span class="ex-legend-dot" style="background:#39ff14"></span>pronto</span>'
        f'    <span class="ex-legend-item"><span class="ex-legend-dot" style="background:#ffb800"></span>construindo</span>'
        f'    <span class="ex-legend-item"><span class="ex-legend-dot" style="background:#5b9cff"></span>planejado</span>'
        f'    <span class="ex-legend-item"><span class="ex-legend-dot" style="background:#c060ff"></span>ideia</span>'
        f'    <span class="ex-legend-item"><span class="ex-legend-dot" style="background:#ff4444"></span>pausado</span>'
        f'  </div>'
        f'  {"".join(sections)}'
        f'</div>'
    )


def scan_permissions() -> int:
    p = CLAUDE_DIR / "settings.local.json"
    if not p.exists():
        return 0
    d = json.loads(p.read_text())
    return len((d.get("permissions") or {}).get("allow") or [])


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Claude Code — Setup &amp; Roadmap</title>
<meta name="theme-color" content="#15043a">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root {
  --bg:#15043a; --sb:#0e0228; --c1:#1f0a4e; --c2:#280d60; --c3:#331478;
  --border:#4a2095; --border2:#7040c8;
  --text:#f0e8ff; --muted:#8a6aaa; --muted2:#b89ed8; --muted3:#dcd0f5;
  --cyan:#00e5ff; --pink:#ff4db8; --neon:#39ff14; --amber:#ffb800;
  --purple:#c060ff; --blue:#5b9cff; --red:#ff4444; --teal:#00ffc8;
  --r:12px; --font:'Inter',system-ui,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:radial-gradient(ellipse at 15% 40%,rgba(100,30,220,.25) 0%,var(--bg) 55%),var(--bg);
     color:var(--text);font-family:var(--font);min-height:100vh;font-size:13px;line-height:1.6;
     -webkit-font-smoothing:antialiased;overflow-x:hidden}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:var(--sb)}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}

/* ── LAYOUT ── */
.layout{display:flex;min-height:100vh}

/* ── SIDEBAR ── */
.sidebar{width:220px;flex-shrink:0;background:linear-gradient(180deg,var(--sb),rgba(20,4,60,.95));
         border-right:1px solid var(--border);display:flex;flex-direction:column;
         position:sticky;top:0;height:100vh;overflow-y:auto;box-shadow:4px 0 30px rgba(0,0,0,.4)}
.sb-logo{padding:24px 20px 20px;font-size:14px;font-weight:800;letter-spacing:-.3px;
         color:var(--cyan);display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--border)}
.sb-dot{width:7px;height:7px;border-radius:50%;background:var(--cyan);box-shadow:0 0 8px var(--cyan);
        animation:blink 2s ease-in-out infinite;flex-shrink:0}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}
.sb-sub{font-size:9px;color:var(--muted2);font-weight:400;display:block;margin-top:2px;letter-spacing:0}
.sb-section{font-size:9px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:1.5px;
            padding:18px 20px 6px}
.sb-link{display:flex;align-items:center;gap:10px;padding:9px 20px;font-size:12px;font-weight:500;
         color:var(--muted2);text-decoration:none;transition:all .15s;border-left:2px solid transparent;
         cursor:pointer;background:none;width:100%;text-align:left;font-family:inherit}
.sb-link:hover,.sb-link.active{color:var(--cyan);background:rgba(0,229,255,.05);border-left-color:var(--cyan)}
.sb-link .ico{font-size:14px;width:16px;flex-shrink:0;text-align:center}
.sb-link .count{margin-left:auto;background:var(--c2);padding:2px 7px;border-radius:8px;font-size:10px;
                font-weight:700;color:var(--muted2)}
.sb-link.active .count{background:var(--cyan);color:var(--bg)}
.sb-divider{height:1px;background:var(--border);margin:8px 20px}
.sb-footer{margin-top:auto;padding:16px 20px;font-size:10px;color:var(--muted);border-top:1px solid var(--border)}

/* ── CONTENT ── */
.content{flex:1;min-width:0;display:flex;flex-direction:column}
.topbar{height:52px;background:rgba(21,4,58,.92);backdrop-filter:blur(12px);border-bottom:1px solid var(--border);
        display:flex;align-items:center;padding:0 28px;gap:12px;position:sticky;top:0;z-index:100}
.tb-path{font-size:11px;color:var(--muted2);display:flex;align-items:center;gap:6px}
.tb-path span{color:var(--cyan)}
.tb-spacer{flex:1}
.tb-date{font-size:11px;color:var(--muted2)}
.tb-live{background:linear-gradient(135deg,rgba(0,229,255,.13),rgba(255,77,184,.13));
         border:1px solid rgba(0,229,255,.27);color:var(--cyan);font-size:9px;font-weight:700;
         padding:3px 10px;border-radius:20px;letter-spacing:1px}
.main{padding:24px 28px 60px;flex:1}

/* ── SECTION LABEL ── */
.sec{font-size:9px;font-weight:700;color:var(--muted2);text-transform:uppercase;letter-spacing:2px;
     display:flex;align-items:center;gap:10px;margin:28px 0 14px}
.sec::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--border2),transparent)}
.sec:first-child{margin-top:0}

/* ── KPI CARDS ── */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:12px}
.kpi-card{background:linear-gradient(145deg,var(--c1),var(--c2));border:1px solid var(--border);
          border-radius:var(--r);padding:18px 16px;position:relative;overflow:hidden;
          box-shadow:0 4px 30px rgba(0,0,0,.5),inset 0 1px 0 rgba(180,80,255,.12);
          transition:all .15s}
.kpi-card:hover{border-color:var(--border2);transform:translateY(-2px);
                box-shadow:0 8px 40px rgba(0,0,0,.6),0 0 20px rgba(180,80,255,.15)}
.kpi-card::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;
                  background:linear-gradient(90deg,transparent,var(--accent,var(--cyan)),transparent)}
.kpi-label{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:1.2px;font-weight:700}
.kpi-val{font-size:28px;font-weight:800;line-height:1;margin-top:6px;color:var(--accent,var(--cyan))}
.kpi-sub{font-size:10px;color:var(--muted);margin-top:4px}
.kpi-card.accent-cyan{--accent:var(--cyan)}
.kpi-card.accent-pink{--accent:var(--pink)}
.kpi-card.accent-amber{--accent:var(--amber)}
.kpi-card.accent-neon{--accent:var(--neon)}
.kpi-card.accent-purple{--accent:var(--purple)}

/* ── PANELS ── */
.panel{display:none}
.panel.active{display:block;animation:fadeIn .2s}
@keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}

/* ── ITEMS ── */
.item{background:linear-gradient(145deg,var(--c1),var(--c2));border:1px solid var(--border);
      border-radius:var(--r);padding:14px 18px;margin-bottom:8px;display:grid;
      grid-template-columns:220px 1fr auto;gap:16px;align-items:center;transition:border-color .15s}
.item:hover{border-color:var(--border2)}
.item .name{font-weight:700;color:var(--cyan);font-family:'SF Mono',Menlo,monospace;font-size:12px}
.item .desc{color:var(--muted3);font-size:12px;line-height:1.5}
.item .badge{padding:4px 10px;border-radius:6px;font-size:10px;font-weight:700;
             text-transform:uppercase;letter-spacing:.5px}
.badge.opus{background:rgba(192,96,255,.18);color:var(--purple);border:1px solid rgba(192,96,255,.4)}
.badge.sonnet{background:rgba(255,77,184,.15);color:var(--pink);border:1px solid rgba(255,77,184,.35)}
.badge.haiku{background:rgba(57,255,20,.12);color:var(--neon);border:1px solid rgba(57,255,20,.3)}
.badge.inherit{background:var(--c3);color:var(--muted2);border:1px solid var(--border)}
.badge.connected{background:rgba(57,255,20,.12);color:var(--neon);border:1px solid rgba(57,255,20,.3)}
.badge.auth_needed{background:rgba(255,184,0,.15);color:var(--amber);border:1px solid rgba(255,184,0,.35)}
.badge.failed{background:rgba(255,68,68,.15);color:var(--red);border:1px solid rgba(255,68,68,.35)}
.badge.local{background:rgba(0,229,255,.12);color:var(--cyan);border:1px solid rgba(0,229,255,.3)}
.badge.remote{background:rgba(192,96,255,.18);color:var(--purple);border:1px solid rgba(192,96,255,.4)}

.item-compact{display:flex;justify-content:space-between;align-items:center;
              background:var(--c1);border:1px solid var(--border);border-radius:8px;
              padding:10px 14px;margin-bottom:6px;font-size:12px}
.item-compact:hover{border-color:var(--border2)}
.item-compact .k{color:var(--cyan);font-family:'SF Mono',Menlo,monospace;font-weight:600}
.item-compact .v{color:var(--muted2)}

/* ── SEARCH ── */
.search{width:100%;padding:11px 14px;background:var(--c1);border:1px solid var(--border);
        border-radius:8px;color:var(--text);font-size:13px;margin-bottom:12px;font-family:inherit}
.search:focus{outline:none;border-color:var(--cyan)}
.search::placeholder{color:var(--muted)}

/* ── ROADMAP ── */
.roadmap-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:16px}
.proj-card{background:linear-gradient(145deg,var(--c1),var(--c2));border:1px solid var(--border);
           border-radius:var(--r);padding:20px;box-shadow:0 4px 30px rgba(0,0,0,.5)}
.proj-card:hover{border-color:var(--border2)}
.proj-header{display:flex;justify-content:space-between;align-items:flex-start;
             margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid var(--border)}
.proj-title{font-size:16px;font-weight:700;color:var(--text)}
.proj-version{font-size:10px;color:var(--cyan);font-family:'SF Mono',Menlo,monospace;
              background:rgba(0,229,255,.08);border:1px solid rgba(0,229,255,.3);
              padding:4px 10px;border-radius:6px;font-weight:600}
.proj-meta{font-size:11px;color:var(--muted);margin-top:4px}
.urgency-group{margin-top:16px}
.urgency-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;
               margin-bottom:8px;display:flex;align-items:center;gap:6px}
.urgency-high{color:var(--red)}
.urgency-medium{color:var(--amber)}
.urgency-low{color:var(--muted2)}
.task{background:var(--bg);border-left:3px solid var(--border2);padding:10px 14px;margin-bottom:6px;
      border-radius:0 8px 8px 0;font-size:12px;line-height:1.55}
.task.high{border-left-color:var(--red);background:rgba(255,68,68,.05)}
.task.medium{border-left-color:var(--amber);background:rgba(255,184,0,.05)}
.task.low{border-left-color:var(--muted2)}
.task .txt{color:var(--muted3)}
.task .src{display:block;margin-top:6px;font-size:10px;color:var(--muted);
           font-family:'SF Mono',Menlo,monospace}
.task .src::before{content:"↳ ";color:var(--border2)}
.empty-state{color:var(--muted);font-size:12px;font-style:italic;padding:12px;text-align:center}

/* ── HELPER ── */
.stale{color:var(--amber)}
.fresh{color:var(--neon)}

/* ── STRUCTURE PANEL (mind map + tree) ── */
.struct-toggle{display:inline-flex;gap:2px;background:var(--sb);border:1px solid var(--border);border-radius:8px;padding:3px;margin-bottom:16px}
.struct-toggle button{background:transparent;border:none;color:var(--muted2);font-family:inherit;font-size:12px;font-weight:600;padding:7px 14px;border-radius:6px;cursor:pointer;transition:all .15s}
.struct-toggle button.active{background:linear-gradient(135deg,var(--cyan),var(--pink));color:var(--bg)}
.struct-toggle button:hover:not(.active){color:var(--cyan);background:rgba(0,229,255,.08)}

.struct-mode{display:none}
.struct-mode.active{display:block}

.struct-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:18px}
.struct-card{background:linear-gradient(145deg,var(--c1),var(--c2));border:1px solid var(--border);border-radius:var(--r);padding:20px;box-shadow:0 4px 30px rgba(0,0,0,.5)}
.struct-card:hover{border-color:var(--border2)}
.struct-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;padding-bottom:12px;border-bottom:1px solid var(--border)}
.struct-header h3{font-size:17px;font-weight:800;color:var(--text)}
.struct-tagline{font-size:11px;color:var(--muted2);margin-top:4px}
.struct-version{font-size:10px;color:var(--cyan);font-family:'SF Mono',Menlo,monospace;background:rgba(0,229,255,.08);border:1px solid rgba(0,229,255,.3);padding:4px 10px;border-radius:6px;font-weight:600;white-space:nowrap}
.struct-vision{font-size:11px;color:var(--muted3);font-style:italic;margin-bottom:10px;line-height:1.55;padding:8px 10px;background:rgba(100,30,220,.1);border-left:2px solid var(--border2);border-radius:0 6px 6px 0}
.struct-focus{font-size:12px;color:var(--neon);margin-bottom:10px}
.struct-focus b{color:var(--neon)}
.struct-chips{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:12px}
.struct-chip{font-size:10px;font-weight:700;padding:3px 9px;border-radius:10px;letter-spacing:.3px}
.struct-chip-total{background:var(--c3);color:var(--muted2);border:1px solid var(--border)}

.struct-tree{font-family:'SF Mono',Menlo,monospace}
.tv-node{padding-left:0}
.tv-children{display:none;margin-left:22px;border-left:1px dashed var(--border);padding-left:8px;margin-top:2px}
.tv-open > .tv-children{display:block}
.tv-row{display:flex;align-items:center;gap:6px;padding:5px 6px;border-radius:5px;cursor:pointer;transition:background .12s;font-size:12px}
.tv-row:hover{background:rgba(0,229,255,.07)}
.tv-caret{display:inline-block;width:12px;color:var(--muted2);transition:transform .15s;flex-shrink:0}
.tv-caret-empty{display:inline-block;width:12px;flex-shrink:0}
.tv-open > .tv-row > .tv-caret{transform:rotate(90deg)}
.tv-emoji{font-size:13px;flex-shrink:0}
.tv-name{color:var(--text);font-weight:500;flex:1;min-width:0}
.tv-pri{font-size:9px;font-weight:800;color:var(--amber);background:rgba(255,184,0,.12);border:1px solid rgba(255,184,0,.35);padding:2px 6px;border-radius:4px}
.tv-status-pill{font-size:9px;font-weight:700;padding:2px 7px;border-radius:4px;letter-spacing:.3px;flex-shrink:0}
.tv-notes{font-size:10px;color:var(--muted2);font-style:italic;padding:2px 0 4px 30px;line-height:1.45}
.tv-inbox-box{margin-top:12px;padding:10px;background:rgba(192,96,255,.08);border:1px dashed rgba(192,96,255,.35);border-radius:6px}
.tv-inbox-title{font-size:10px;font-weight:700;color:var(--purple);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}
.tv-inbox-item{font-size:11px;color:var(--muted3);padding:4px 0;border-top:1px solid rgba(192,96,255,.15)}
.tv-inbox-item:first-of-type{border-top:none}

/* EXECUTIVE ROADMAP */
.ex-legend{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px;padding:10px 14px;background:rgba(255,255,255,.02);border:1px solid var(--border);border-radius:8px;font-size:12px;color:var(--muted2)}
.ex-legend-item{display:inline-flex;align-items:center;gap:6px}
.ex-legend-dot{width:9px;height:9px;border-radius:50%;display:inline-block;box-shadow:0 0 6px currentColor}

.ex-project{background:linear-gradient(145deg,var(--c1),var(--c2));border:1px solid var(--border);border-radius:14px;padding:24px 26px;margin-bottom:22px;box-shadow:0 6px 40px rgba(0,0,0,.55)}
.ex-project-head{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;padding-bottom:16px;border-bottom:1px solid var(--border)}
.ex-project-title-wrap{display:flex;gap:14px;align-items:center}
.ex-project-emoji{font-size:36px;line-height:1;flex-shrink:0}
.ex-project-title{font-size:22px;font-weight:800;color:var(--text);letter-spacing:-.3px;margin:0}
.ex-project-tagline{font-size:13px;color:var(--muted2);margin-top:4px;font-weight:500}
.ex-project-meta{display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex-shrink:0}
.ex-project-version{font-size:11px;color:var(--cyan);background:rgba(0,229,255,.08);border:1px solid rgba(0,229,255,.3);padding:5px 11px;border-radius:7px;font-weight:600;font-family:'SF Mono',Menlo,monospace}
.ex-project-overall{font-size:15px;color:var(--neon);font-weight:700}
.ex-project-vision{font-size:13px;color:var(--muted3);line-height:1.65;margin:14px 0 10px;padding:12px 16px;background:rgba(100,30,220,.12);border-left:3px solid var(--border2);border-radius:0 8px 8px 0}
.ex-project-focus{font-size:13px;color:var(--neon);margin:10px 0;font-weight:500}
.ex-project-focus b{color:var(--neon);font-weight:700}
.ex-project-chips{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 18px}
.ex-chip{font-size:12px;font-weight:700;padding:5px 12px;border-radius:12px;letter-spacing:.2px}

.ex-phases{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.ex-phase{background:linear-gradient(160deg,#1a0f3a,#2a1550);border:1px solid var(--border);border-top:3px solid var(--cyan);border-radius:10px;padding:16px 18px;transition:transform .2s,box-shadow .2s}
.ex-phase:hover{transform:translateY(-3px);box-shadow:0 8px 30px rgba(0,0,0,.5),0 0 20px rgba(180,80,255,.15)}
.ex-phase-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:10px}
.ex-phase-title{font-size:15px;font-weight:700;color:var(--text);line-height:1.3;flex:1;min-width:0}
.ex-phase-tags{display:flex;gap:5px;flex-shrink:0}
.ex-pri{font-size:10px;font-weight:800;color:var(--amber);background:rgba(255,184,0,.15);border:1px solid rgba(255,184,0,.4);padding:3px 8px;border-radius:5px;letter-spacing:.3px}
.ex-phase-status{font-size:10px;font-weight:700;padding:3px 9px;border-radius:5px;letter-spacing:.3px;border:1px solid;white-space:nowrap}

.ex-phase-prog{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.ex-phase-bar-wrap{flex:1;height:8px;background:rgba(255,255,255,.06);border-radius:4px;overflow:hidden}
.ex-phase-bar{height:100%;border-radius:4px;transition:width .5s ease;box-shadow:0 0 10px currentColor}
.ex-phase-pct{font-size:11px;color:var(--muted2);font-family:'SF Mono',Menlo,monospace;white-space:nowrap;font-weight:600}

.ex-phase-notes{font-size:11px;color:var(--amber);font-style:italic;padding:7px 10px;background:rgba(255,184,0,.06);border-left:2px solid var(--amber);border-radius:0 5px 5px 0;margin:8px 0}

.ex-children{display:flex;flex-direction:column;gap:5px;margin-top:10px}
.ex-child{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:6px;border-left:3px solid;background:rgba(255,255,255,.025);font-size:12px;color:var(--text);transition:background .12s}
.ex-child:hover{background:rgba(255,255,255,.06)}
.ex-child-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;box-shadow:0 0 6px currentColor}
.ex-child-name{flex:1;min-width:0;line-height:1.4}
.ex-mini-prog{width:40px;height:4px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden;flex-shrink:0}
.ex-mini-bar{display:block;height:100%;border-radius:2px}
.ex-child-more{color:var(--muted2);font-style:italic;border-left-color:var(--border);font-size:11px}
.ex-empty{color:var(--muted);font-size:11px;font-style:italic;padding:4px 10px}

.ex-inbox{margin-top:18px;padding:14px 18px;background:rgba(192,96,255,.09);border:1px dashed rgba(192,96,255,.45);border-radius:10px}
.ex-inbox-title{font-size:12px;font-weight:700;color:var(--purple);text-transform:uppercase;letter-spacing:1.2px;margin-bottom:10px}
.ex-inbox-item{display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-top:1px solid rgba(192,96,255,.15)}
.ex-inbox-item:first-of-type{border-top:none;padding-top:2px}
.ex-inbox-dot{flex-shrink:0;font-size:15px}
.ex-inbox-text{font-size:13px;color:var(--text);line-height:1.45}
.ex-inbox-meta{font-size:10px;color:var(--muted);margin-top:3px;font-family:'SF Mono',Menlo,monospace}

/* ── RESPONSIVE ── */
@media(max-width:900px){
  .sidebar{position:fixed;left:-240px;transition:left .3s;z-index:200}
  .sidebar.open{left:0}
  .main{padding:16px}
  .item{grid-template-columns:1fr;gap:8px}
  .struct-grid{grid-template-columns:1fr}
  .ex-phases{grid-template-columns:1fr}
  .ex-project{padding:18px}
  .ex-project-head{flex-direction:column;align-items:flex-start}
  .ex-project-meta{align-items:flex-start;flex-direction:row;gap:10px}
  .ex-project-title{font-size:18px}
  .ex-project-emoji{font-size:28px}
}
</style>
</head>
<body>
<div class="layout">

  <!-- ── SIDEBAR ───────────────────────────────────────── -->
  <aside class="sidebar">
    <div class="sb-logo">
      <span class="sb-dot"></span>
      <div>
        Claude Code
        <span class="sb-sub">Setup &amp; Roadmap</span>
      </div>
    </div>

    <div class="sb-section">Planejamento</div>
    <a class="sb-link active" data-panel="structure"><span class="ico">🗺️</span> Estrutura <span class="count">__STRUCTURE_COUNT__</span></a>
    <a class="sb-link" data-panel="roadmap"><span class="ico">🎯</span> Roadmap <span class="count">__ROADMAP_COUNT__</span></a>

    <div class="sb-divider"></div>
    <div class="sb-section">Ferramentas</div>
    <a class="sb-link" data-panel="mcps"><span class="ico">🔌</span> MCPs <span class="count">__MCP_COUNT__</span></a>
    <a class="sb-link" data-panel="agents"><span class="ico">🤖</span> Subagentes <span class="count">__AGENTS_COUNT__</span></a>
    <a class="sb-link" data-panel="commands"><span class="ico">⚡</span> Commands <span class="count">__COMMANDS_COUNT__</span></a>

    <div class="sb-divider"></div>
    <div class="sb-section">Infra</div>
    <a class="sb-link" data-panel="hooks"><span class="ico">🪝</span> Hooks <span class="count">__HOOKS_COUNT__</span></a>
    <a class="sb-link" data-panel="claudemd"><span class="ico">📄</span> CLAUDE.md <span class="count">__CLAUDEMD_COUNT__</span></a>
    <a class="sb-link" data-panel="memory"><span class="ico">🧠</span> Memória <span class="count">__MEMORY_COUNT__</span></a>

    <div class="sb-footer">
      __GENERATED__<br>
      __EFFORT_INLINE__
    </div>
  </aside>

  <!-- ── CONTENT ──────────────────────────────────────── -->
  <div class="content">
    <div class="topbar">
      <div class="tb-path">Claude Code <span>/ Setup &amp; Roadmap</span></div>
      <div class="tb-spacer"></div>
      <div class="tb-date">__GENERATED__</div>
      <div class="tb-live">● LIVE</div>
    </div>

    <div class="main">

      <!-- KPI CARDS -->
      <div class="sec">Visão Geral</div>
      <div class="kpi-grid">
        <div class="kpi-card accent-cyan">
          <div class="kpi-label">MCP Servers</div>
          <div class="kpi-val">__MCP_COUNT__</div>
          <div class="kpi-sub">tools conectados</div>
        </div>
        <div class="kpi-card accent-pink">
          <div class="kpi-label">Subagentes</div>
          <div class="kpi-val">__AGENTS_COUNT__</div>
          <div class="kpi-sub">especialistas Sonnet</div>
        </div>
        <div class="kpi-card accent-amber">
          <div class="kpi-label">Slash Commands</div>
          <div class="kpi-val">__COMMANDS_COUNT__</div>
          <div class="kpi-sub">atalhos customizados</div>
        </div>
        <div class="kpi-card accent-neon">
          <div class="kpi-label">Próximas etapas</div>
          <div class="kpi-val">__ROADMAP_COUNT__</div>
          <div class="kpi-sub">cross-projetos</div>
        </div>
        <div class="kpi-card accent-purple">
          <div class="kpi-label">Hooks</div>
          <div class="kpi-val">__HOOKS_COUNT__</div>
          <div class="kpi-sub">eventos automáticos</div>
        </div>
        <div class="kpi-card accent-cyan">
          <div class="kpi-label">CLAUDE.md</div>
          <div class="kpi-val">__CLAUDEMD_COUNT__</div>
          <div class="kpi-sub">contextos carregados</div>
        </div>
        <div class="kpi-card accent-pink">
          <div class="kpi-label">Memórias</div>
          <div class="kpi-val">__MEMORY_COUNT__</div>
          <div class="kpi-sub">globais + projetos</div>
        </div>
        <div class="kpi-card accent-amber">
          <div class="kpi-label">Permissões</div>
          <div class="kpi-val">__PERMS_COUNT__</div>
          <div class="kpi-sub">auto-allowlist</div>
        </div>
      </div>

      <!-- PANELS -->
      <div class="panel active" id="panel-structure">
        <div class="sec">Estrutura · visão executiva dos projetos</div>
        <div class="struct-toggle">
          <button class="active" data-mode="exec">📊 Roadmap</button>
          <button data-mode="tree">🌳 Árvore detalhada</button>
        </div>
        <div class="struct-mode active" id="struct-exec">__STRUCTURE_EXEC__</div>
        <div class="struct-mode" id="struct-tree"><div class="struct-grid">__STRUCTURE_TREE__</div></div>
      </div>

      <div class="panel" id="panel-roadmap">
        <div class="sec">Roadmap · próximas etapas detectadas</div>
        <div class="roadmap-grid">__ROADMAP__</div>
      </div>

      <div class="panel" id="panel-mcps">
        <div class="sec">MCP Servers · __MCP_COUNT__ conectados</div>
        <input class="search" placeholder="filtrar MCPs..." data-target="mcps-list">
        <div id="mcps-list">__MCPS__</div>
      </div>

      <div class="panel" id="panel-agents">
        <div class="sec">Subagentes · __AGENTS_COUNT__ especializados</div>
        <input class="search" placeholder="filtrar agentes..." data-target="agents-list">
        <div id="agents-list">__AGENTS__</div>
      </div>

      <div class="panel" id="panel-commands">
        <div class="sec">Slash Commands · __COMMANDS_COUNT__ customizados</div>
        <input class="search" placeholder="filtrar commands..." data-target="commands-list">
        <div id="commands-list">__COMMANDS__</div>
      </div>

      <div class="panel" id="panel-hooks">
        <div class="sec">Eventos registrados</div>
        <div>__HOOKS_EVENTS__</div>
        <div class="sec">Scripts em ~/.claude/hooks/</div>
        <div>__HOOKS_SCRIPTS__</div>
      </div>

      <div class="panel" id="panel-claudemd">
        <div class="sec">CLAUDE.md por projeto</div>
        <div>__CLAUDEMD__</div>
      </div>

      <div class="panel" id="panel-memory">
        <div class="sec">Memórias globais</div>
        <div>__MEMORY_GLOBAL__</div>
        <div class="sec">Memórias por projeto</div>
        <div>__MEMORY_PROJECTS__</div>
      </div>

    </div>
  </div>
</div>

<script>
// Tabs (sidebar-driven)
document.querySelectorAll('.sb-link[data-panel]').forEach(t => {
  t.addEventListener('click', (e) => {
    e.preventDefault();
    document.querySelectorAll('.sb-link').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById('panel-' + t.dataset.panel).classList.add('active');
    window.scrollTo(0, 0);
  });
});

// Structure mode toggle (exec roadmap <-> árvore detalhada)
document.querySelectorAll('.struct-toggle button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.struct-toggle button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.struct-mode').forEach(m => m.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('struct-' + btn.dataset.mode).classList.add('active');
  });
});
// Deep-link via hash (#panel-mcps etc.)
const initHash = window.location.hash;
if (initHash && initHash.startsWith('#panel-')) {
  const target = document.querySelector(`.sb-link[data-panel="${initHash.replace('#panel-','')}"]`);
  if (target) target.click();
}
// Search
document.querySelectorAll('.search').forEach(inp => {
  inp.addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    const target = document.getElementById(e.target.dataset.target);
    target.querySelectorAll('.item').forEach(it => {
      it.style.display = it.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  });
});
</script>
</body>
</html>
"""


def h(s: str) -> str:
    """HTML escape minimal."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_mcps(mcps: list) -> str:
    out = []
    for m in mcps:
        status = m.get("status", "unknown")
        scope = m.get("scope", "")
        status_badge = (
            f'<span class="badge {status}">{status}</span>' if status != "unknown" else ""
        )
        out.append(
            f'<div class="item"><div class="name">{h(m["name"])}</div>'
            f'<div class="desc">{h(m.get("command", "")[:120])}</div>'
            f'<div style="display:flex;gap:6px"><span class="badge {scope}">{scope}</span>{status_badge}</div></div>'
        )
    return "\n".join(out) if out else '<p style="color:#64748b">nenhum MCP</p>'


def render_agents(agents: list) -> str:
    out = []
    for a in agents:
        model = a.get("model", "inherit")
        badge_class = model if model in ("opus", "sonnet", "haiku") else "inherit"
        out.append(
            f'<div class="item"><div class="name">{h(a["name"])}</div>'
            f'<div class="desc">{h(a["description"])}</div>'
            f'<span class="badge {badge_class}">{h(model)}</span></div>'
        )
    return "\n".join(out) if out else '<p style="color:#64748b">sem agentes</p>'


def render_commands(commands: list) -> str:
    out = []
    for c in commands:
        args = f'<small style="color:#64748b">{h(c["args"])}</small>' if c.get("args") else ""
        out.append(
            f'<div class="item"><div class="name">{h(c["name"])}</div>'
            f'<div class="desc">{h(c["description"])} {args}</div>'
            f'<span class="badge local">cmd</span></div>'
        )
    return "\n".join(out) if out else '<p style="color:#64748b">sem commands</p>'


def render_hooks_events(events: list) -> str:
    out = []
    for e in events:
        matcher = f' · matcher: <code>{h(e["matcher"])}</code>' if e["matcher"] else ""
        out.append(
            f'<div class="item-compact"><span class="k">{h(e["event"])}{matcher}</span>'
            f'<span class="v">{h(e["command"][:120])}</span></div>'
        )
    return "\n".join(out) if out else '<p style="color:#64748b">sem hooks</p>'


def render_hooks_scripts(scripts: list) -> str:
    out = []
    for s in scripts:
        exe = "✓" if s["executable"] else "✗ não executável"
        out.append(
            f'<div class="item-compact"><span class="k">{h(s["name"])}</span>'
            f'<span class="v">{s["size_kb"]} KB · {exe}</span></div>'
        )
    return "\n".join(out) if out else ""


def render_claudemd(items: list) -> str:
    out = []
    for c in items:
        age_cls = "fresh" if c["age_days"] <= 7 else ("stale" if c["age_days"] > 30 else "")
        out.append(
            f'<div class="item"><div class="name">{h(c["project"])}</div>'
            f'<div class="desc">{h(c["path"])} · {c["size_kb"]} KB · '
            f'<span class="{age_cls}">{c["age_days"]}d atrás</span></div>'
            f'<span class="badge local">md</span></div>'
        )
    return "\n".join(out) if out else '<p style="color:#64748b">sem CLAUDE.md</p>'


def render_memory_global(items: list) -> str:
    out = []
    for m in items:
        age_cls = "fresh" if m["age_days"] <= 7 else ("stale" if m["age_days"] > 30 else "")
        out.append(
            f'<div class="item"><div class="name">{h(m["name"])}</div>'
            f'<div class="desc">{h(m["description"])} · '
            f'<span class="{age_cls}">{m["age_days"]}d</span></div>'
            f'<span class="badge inherit">{h(m["type"])}</span></div>'
        )
    return "\n".join(out) if out else ""


def render_roadmap(roadmap: dict) -> str:
    """Renderiza cards por projeto com tarefas agrupadas por urgência."""
    cards = []
    for key, p in roadmap.items():
        # Agrupa por urgência
        groups = {"high": [], "medium": [], "low": []}
        for it in p["items"]:
            groups.setdefault(it["urgency"], []).append(it)

        # Header
        version = p.get("version") or "—"
        age = p.get("latest_source_age_days")
        age_str = f"{age}d" if age is not None else "?"
        freshness_cls = (
            "fresh"
            if (age is not None and age <= 7)
            else ("stale" if (age is not None and age > 30) else "")
        )

        header = (
            f'<div class="proj-header">'
            f'<div><div class="proj-title">{h(p["emoji"])} {h(p["name"])}</div>'
            f'<div class="proj-meta">{len(p["items"])} próximas etapas · '
            f'fonte mais nova: <span class="{freshness_cls}">{age_str}</span></div></div>'
            f'<div class="proj-version">{h(version)}</div>'
            f'</div>'
        )

        body = []
        urgency_labels = [
            ("high", "🔴 Crítico / decisão pendente"),
            ("medium", "🟡 Importante"),
            ("low", "🟢 Quando possível"),
        ]
        has_any = False
        for urg_key, label in urgency_labels:
            items = groups.get(urg_key) or []
            if not items:
                continue
            has_any = True
            body.append(
                f'<div class="urgency-group">'
                f'<div class="urgency-label urgency-{urg_key}">{label}</div>'
            )
            for it in items[:6]:  # limite 6 por urgência pra não inflar
                body.append(
                    f'<div class="task {urg_key}">'
                    f'<span class="txt">{h(it["text"])}</span>'
                    f'<span class="src">{h(it["source_file"])} · '
                    f'{h(it["source_section"])}</span>'
                    f'</div>'
                )
            body.append("</div>")

        if not has_any:
            body.append(
                '<div class="empty-state">Sem próximas etapas detectadas — tudo em dia ou checkpoint desatualizado</div>'
            )

        cards.append(f'<div class="proj-card">{header}{"".join(body)}</div>')
    return "\n".join(cards)


def render_memory_projects(projects: dict) -> str:
    out = []
    for project, files in projects.items():
        out.append(f'<div style="margin-top:12px;color:#60a5fa;font-weight:600">{h(project)}</div>')
        for f in files:
            age_cls = "fresh" if f["age_days"] <= 7 else ("stale" if f["age_days"] > 30 else "")
            out.append(
                f'<div class="item-compact"><span class="k">{h(f["name"])}</span>'
                f'<span class="v">{f["size_kb"]} KB · '
                f'<span class="{age_cls}">{f["age_days"]}d</span></span></div>'
            )
    return "\n".join(out) if out else ""


def main() -> None:
    data = {
        "mcps": scan_mcps(),
        "agents": scan_agents(),
        "commands": scan_commands(),
        "hooks": scan_hooks(),
        "memory": scan_memory(),
        "claudemd": scan_claude_md(),
        "perms": scan_permissions(),
        "roadmap": scan_roadmap(),
        "structure": scan_structure(),
    }

    html = HTML_TEMPLATE
    html = html.replace("__GENERATED__", datetime.now().strftime("%d/%m/%Y %H:%M"))
    html = html.replace("__EFFORT_INLINE__", f'effortLevel: {data["hooks"]["effortLevel"]}')
    html = html.replace("__MCP_COUNT__", str(len(data["mcps"])))
    html = html.replace("__AGENTS_COUNT__", str(len(data["agents"])))
    html = html.replace("__COMMANDS_COUNT__", str(len(data["commands"])))
    html = html.replace("__HOOKS_COUNT__", str(len(data["hooks"]["events"])))
    html = html.replace("__CLAUDEMD_COUNT__", str(len(data["claudemd"])))
    mem_total = len(data["memory"]["global"]) + sum(
        len(v) for v in data["memory"]["projects"].values()
    )
    html = html.replace("__MEMORY_COUNT__", str(mem_total))
    html = html.replace("__PERMS_COUNT__", str(data["perms"]))
    html = html.replace("__EFFORT__", data["hooks"]["effortLevel"])
    html = html.replace("__MCPS__", render_mcps(data["mcps"]))
    html = html.replace("__AGENTS__", render_agents(data["agents"]))
    html = html.replace("__COMMANDS__", render_commands(data["commands"]))
    html = html.replace("__HOOKS_EVENTS__", render_hooks_events(data["hooks"]["events"]))
    html = html.replace("__HOOKS_SCRIPTS__", render_hooks_scripts(data["hooks"]["scripts"]))
    html = html.replace("__CLAUDEMD__", render_claudemd(data["claudemd"]))
    html = html.replace("__MEMORY_GLOBAL__", render_memory_global(data["memory"]["global"]))
    html = html.replace("__MEMORY_PROJECTS__", render_memory_projects(data["memory"]["projects"]))

    # Roadmap
    roadmap_total = sum(len(p["items"]) for p in data["roadmap"].values())
    html = html.replace("__ROADMAP_COUNT__", str(roadmap_total))
    html = html.replace("__ROADMAP__", render_roadmap(data["roadmap"]))

    # Structure
    structure_total = sum(
        sum(_count_status(p.get("modules") or []).values())
        for p in data["structure"]
        if "_error" not in p
    )
    html = html.replace("__STRUCTURE_COUNT__", str(structure_total))
    html = html.replace("__STRUCTURE_TREE__", render_structure_tree(data["structure"]))
    html = html.replace("__STRUCTURE_EXEC__", render_structure_executive(data["structure"]))

    OUT.write_text(html)

    # Gera também summary JSON consumido pelo dashboard.html do MYO
    summary = {
        "generated_at": datetime.now().isoformat(),
        "mcps": len(data["mcps"]),
        "agents": len(data["agents"]),
        "commands": len(data["commands"]),
        "hooks": len(data["hooks"]["events"]),
        "claudemd": len(data["claudemd"]),
        "memory": mem_total,
        "perms": data["perms"],
        "effort_level": data["hooks"]["effortLevel"],
        "roadmap_total": sum(len(p["items"]) for p in data["roadmap"].values()),
        "roadmap_high": sum(
            len([it for it in p["items"] if it["urgency"] == "high"])
            for p in data["roadmap"].values()
        ),
        "roadmap_medium": sum(
            len([it for it in p["items"] if it["urgency"] == "medium"])
            for p in data["roadmap"].values()
        ),
        "projects": {
            key: {
                "name": p["name"],
                "emoji": p["emoji"],
                "version": p["version"],
                "total": len(p["items"]),
                "urgency_high": len([it for it in p["items"] if it["urgency"] == "high"]),
                "urgency_medium": len([it for it in p["items"] if it["urgency"] == "medium"]),
                "urgency_low": len([it for it in p["items"] if it["urgency"] == "low"]),
            }
            for key, p in data["roadmap"].items()
        },
    }
    summary_path = OUT.parent / "claude_setup_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    print(f"✓ Dashboard gerado: {OUT}")
    print(f"✓ Summary JSON:     {summary_path}")
    print(f"  Abrir no browser: open {OUT}")
    print(
        f"  Tamanho HTML: {OUT.stat().st_size / 1024:.1f} KB · JSON: {summary_path.stat().st_size} B"
    )


if __name__ == "__main__":
    main()
