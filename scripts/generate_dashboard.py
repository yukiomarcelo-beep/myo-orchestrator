#!/usr/bin/env python3
"""
Gera dashboard.html a partir dos arquivos em outputs/
Uso: python generate_dashboard.py
"""

import glob
import json
import os
import sys
from datetime import datetime

# Security layer (opcional — degrada graciosamente se indisponível)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from security_layer import (
        AGENT_PERMISSIONS,
        CRITICAL_COST_LIMIT_USD,
        DAILY_COST_LIMIT_USD,
        MAX_TURNS,
    )

    _SECURITY_AVAILABLE = True
except ImportError:
    _SECURITY_AVAILABLE = False

OUTPUTS_DIR = "outputs"
OUTPUT_FILE = "dashboard.html"

WEIGHTS = {
    "dor_do_mercado": 20,
    "urgencia": 15,
    "monetizacao": 15,
    "escalabilidade": 15,
    "aquisicao": 10,
    "diferenciacao": 10,
    "execucao": 10,
    "potencial_de_conteudo": 5,
}
CRITERIA_LABELS = {
    "dor_do_mercado": "Dor do mercado",
    "urgencia": "Urgência",
    "monetizacao": "Monetização",
    "escalabilidade": "Escalabilidade",
    "aquisicao": "Aquisição",
    "diferenciacao": "Diferenciação",
    "execucao": "Execução",
    "potencial_de_conteudo": "Conteúdo",
}
PRIORITY_ORDER = {"maxima": 0, "alta": 1, "media": 2, "baixa": 3}
PRIORITY_LABEL = {
    "maxima": "Prioridade Máxima",
    "alta": "Vale Testar",
    "media": "Com Cautela",
    "baixa": "Descartar",
}
PRIORITY_COLOR = {"maxima": "#10b981", "alta": "#3b82f6", "media": "#f59e0b", "baixa": "#ef4444"}
PRIORITY_BG = {
    "maxima": "#10b98115",
    "alta": "#3b82f615",
    "media": "#f59e0b15",
    "baixa": "#ef444415",
}
REC_COLOR = {"priorizar": "#10b981", "testar": "#3b82f6", "descartar": "#ef4444"}
TYPE_COLOR = {
    "research": "#8b5cf6",
    "strategy": "#3b82f6",
    "execution": "#f59e0b",
    "video": "#ec4899",
}
TYPE_ICON = {"research": "🔍", "strategy": "🧠", "execution": "⚡", "video": "🎬"}


def load_scorings():
    items = []
    for path in sorted(glob.glob(f"{OUTPUTS_DIR}/scoring_*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            out = data.get("output", {})
            if out.get("idea_title"):
                items.append(
                    {
                        "file": os.path.basename(path),
                        "ts": data.get("timestamp", ""),
                        **out,
                        "raw_scoring": data.get("raw_scoring", {}),
                        "opportunity": data.get("opportunity", {}),
                    }
                )
        except Exception:
            pass
    items.sort(
        key=lambda x: (PRIORITY_ORDER.get(x.get("priority", "baixa"), 9), -x.get("final_score", 0))
    )
    return items


def load_videos():
    items = []
    for path in sorted(glob.glob(f"{OUTPUTS_DIR}/video_*.json"), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("idea_title") and data.get("script"):
                sc = data.get("selected", data.get("script", {}))
                aud = data.get("audio", {})
                vid = data.get("video", {})
                var = data.get("variations", {})
                items.append(
                    {
                        "file": os.path.basename(path),
                        "ts": data.get("timestamp", ""),
                        "idea_title": data.get("idea_title", ""),
                        "roteiro_final": data.get("roteiro_final", ""),
                        "caption": data.get("caption", ""),
                        "hook": sc.get("hook", sc.get("gancho", "")),
                        "cta": sc.get("cta", ""),
                        "audio_file": aud.get("audio_file", ""),
                        "audio_ok": bool(aud.get("audio_file")),
                        "video_url": vid.get("video_url", ""),
                        "video_id": vid.get("video_id", ""),
                        "video_status": vid.get("status", ""),
                        "n_agressivas": len(var.get("agressivas", [])),
                        "n_elegantes": len(var.get("elegantes", [])),
                        "queue": data.get("queue", []),
                        "total_cost": data.get("total_cost", 0),
                    }
                )
        except Exception:
            pass
    return items


def load_contents():
    items = []
    for path in sorted(glob.glob(f"{OUTPUTS_DIR}/content_*.json"), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("idea_title"):
                items.append(
                    {
                        "file": os.path.basename(path),
                        "ts": data.get("timestamp", ""),
                        "idea_title": data.get("idea_title", ""),
                        "angles": data.get("angles", []),
                        "hooks": data.get("hooks", []),
                        "content_ideas": data.get("content_ideas", []),
                        "posts": data.get("posts", []),
                        "scripts": data.get("scripts", []),
                        "variations": data.get("script_variations", []),
                        "summary": data.get("summary", {}),
                        "total_cost": data.get("total_cost", 0),
                    }
                )
        except Exception:
            pass
    return items


def load_blueprints():
    items = []
    for path in sorted(glob.glob(f"{OUTPUTS_DIR}/blueprint_*.json"), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            bp = data.get("blueprint", {})
            resp = data.get("response", {})
            if bp.get("idea_title"):
                items.append(
                    {
                        "file": os.path.basename(path),
                        "ts": data.get("timestamp", ""),
                        "idea_title": bp.get("idea_title", ""),
                        "target_audience": bp.get("target_audience", ""),
                        "final_score": bp.get("final_score", 0),
                        "priority": bp.get("priority", ""),
                        "best_initial_format": resp.get("best_initial_format", ""),
                        "main_promise": resp.get("main_promise", ""),
                        "entry_ticket": resp.get("entry_ticket", ""),
                        "top_name": resp.get("top_name", ""),
                        "headline": resp.get("headline", ""),
                        "cta": resp.get("cta", ""),
                        "total_cost": data.get("total_cost", 0),
                        "product_strategy": bp.get("product_strategy", {}),
                        "offer_design": bp.get("offer_design", {}),
                        "naming_options": bp.get("naming_options", {}),
                        "product_structure": bp.get("product_structure", {}),
                        "copy_base": bp.get("copy_base", {}),
                    }
                )
        except Exception:
            pass
    return items


def load_performances():
    items = []
    for path in sorted(glob.glob(f"{OUTPUTS_DIR}/performance_*.json"), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            m = data.get("metrics", {})
            ins = data.get("insights", {})
            if m.get("asset_type"):
                items.append(
                    {
                        "file": os.path.basename(path),
                        "ts": data.get("timestamp", ""),
                        "asset_type": m.get("asset_type", ""),
                        "asset_id": m.get("asset_id", ""),
                        "platform": m.get("platform", ""),
                        "views": m.get("views", 0),
                        "likes": m.get("likes", 0),
                        "comments": m.get("comments", 0),
                        "saves": m.get("saves", 0),
                        "shares": m.get("shares", 0),
                        "clicks": m.get("clicks", 0),
                        "leads": m.get("leads", 0),
                        "engagement_rate": m.get("engagement_rate", 0),
                        "click_rate": m.get("click_rate", 0),
                        "lead_rate": m.get("lead_rate", 0),
                        "performance_score": m.get("performance_score", 0),
                        "performance_band": m.get("performance_band", "baixa"),
                        "gancho": m.get("gancho", ""),
                        "why_it_performed": ins.get("why_it_performed", ""),
                        "what_worked": ins.get("what_worked", []),
                        "repeat": ins.get("repeat", []),
                        "avoid": ins.get("avoid", []),
                        "next_content": ins.get("next_content_recommendation", ""),
                    }
                )
        except Exception:
            pass
    items.sort(key=lambda x: x.get("performance_score", 0), reverse=True)
    return items


def load_memory_items():
    if not os.path.exists(MEMORY_FILE := os.path.join(OUTPUTS_DIR, "memory_items.json")):
        return []
    try:
        with open(MEMORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def load_validations():
    items = []
    for path in sorted(glob.glob(f"{OUTPUTS_DIR}/validation_*.json"), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            s = data.get("signals", {})
            a = data.get("analysis", {})
            if data.get("idea_title"):
                items.append(
                    {
                        "file": os.path.basename(path),
                        "ts": data.get("timestamp", ""),
                        "idea_title": data.get("idea_title", ""),
                        "platform": data.get("platform", ""),
                        "validation_score": s.get("validation_score", 0),
                        "validation_status": s.get("validation_status", "fraco"),
                        "final_action": data.get("final_action", "descartar"),
                        "real_interest": a.get("real_interest", False),
                        "audience_signal": a.get("audience_signal", ""),
                        "problem_strength": a.get("problem_strength", ""),
                        "next_action": a.get("next_action", ""),
                        "views": s.get("views", 0),
                        "leads": s.get("leads", 0),
                        "dm_requests": s.get("dm_requests", 0),
                        "engagement": s.get("engagement", 0),
                    }
                )
        except Exception:
            pass
    items.sort(key=lambda x: x.get("validation_score", 0), reverse=True)
    return items


def load_crm_leads():
    crm_file = os.path.join(OUTPUTS_DIR, "crm_leads.json")
    if not os.path.exists(crm_file):
        return []
    try:
        with open(crm_file, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def load_scaling_decisions():
    items = []
    for path in sorted(glob.glob(f"{OUTPUTS_DIR}/scaling_*.json"), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            d = data.get("data", {})
            a = data.get("analysis", {})
            p = data.get("action_plan", {})
            if data.get("idea_title"):
                items.append(
                    {
                        "file": os.path.basename(path),
                        "ts": data.get("timestamp", ""),
                        "idea_title": data.get("idea_title", ""),
                        "scaling_score": d.get("scaling_score", 0),
                        "scaling_status": d.get("scaling_status", "stop"),
                        "final_action": data.get("final_action", "stop"),
                        "performance_score": d.get("performance_score", 0),
                        "validation_score": d.get("validation_score", 0),
                        "conversion_rate": d.get("conversion_rate", 0),
                        "leads": d.get("leads", 0),
                        "sales": d.get("sales", 0),
                        "insight": a.get("insight", ""),
                        "repeat": a.get("repeat", []),
                        "kill": a.get("kill", []),
                        "scale_actions": a.get("scale_actions", []),
                        "next_steps": a.get("next_steps", ""),
                        "plano_7_dias": p.get("plano_7_dias", []),
                    }
                )
        except Exception:
            pass
    items.sort(key=lambda x: x.get("scaling_score", 0), reverse=True)
    return items


def load_sessions():
    sessions_dir = os.path.join(OUTPUTS_DIR, "sessions")
    if not os.path.exists(sessions_dir):
        return []
    items = []
    for path in sorted(glob.glob(os.path.join(sessions_dir, "session_*.json")), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            items.append(
                {
                    "session_id": d.get("session_id", ""),
                    "mode": d.get("mode", ""),
                    "objective": d.get("objective", ""),
                    "market": d.get("market", ""),
                    "status": d.get("status", ""),
                    "nodes_done": len(d.get("nodes_done", [])),
                    "total_cost": d.get("total_cost", 0),
                    "started_at": d.get("started_at", ""),
                    "finished_at": d.get("finished_at", ""),
                    "engines_run": d.get("results", {})
                    .get("07_Execute_Path", {})
                    .get("engines_run", []),
                    "decision": d.get("results", {}).get("06_Decision", {}).get("decision", ""),
                    "score": d.get("results", {}).get("05_Scoring", {}).get("final_score", 0),
                    "next_rec": d.get("results", {})
                    .get("11_Repeat", {})
                    .get("next_recommendation", ""),
                }
            )
        except Exception:
            pass
    return items


def load_simulations():
    path = os.path.join(OUTPUTS_DIR, "simulations.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, list) else []
    except Exception:
        return []


def load_financial_data():
    path = os.path.join(OUTPUTS_DIR, "financial_data.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_ads_campaigns():
    path = os.path.join(OUTPUTS_DIR, "ads_campaigns.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            campaigns = json.load(f)
        if not isinstance(campaigns, list):
            return []
        items = []
        for c in campaigns:
            items.append(
                {
                    "campaign_id": c.get("campaign_id", ""),
                    "idea_title": c.get("idea_title", ""),
                    "fase": c.get("fase", "teste"),
                    "plataforma": c.get("plataforma", "meta_ads"),
                    "budget_total": c.get("budget_total", 0),
                    "total_ads": c.get("total_ads", 0),
                    "clicks": c.get("clicks", 0),
                    "leads": c.get("leads", 0),
                    "sales": c.get("sales", 0),
                    "cost": c.get("cost", 0.0),
                    "revenue": c.get("revenue", 0.0),
                    "roas": c.get("roas", 0.0),
                    "cpc": c.get("cpc", 0.0),
                    "cpl": c.get("cpl", 0.0),
                    "cpa": c.get("cpa", 0.0),
                    "optimization_status": c.get("optimization_status", "aguardando_dados"),
                    "optimization_insights": c.get("optimization_insights", {}),
                    "timestamp": c.get("timestamp", ""),
                }
            )
        return items
    except Exception:
        return []


def load_funnels():
    items = []
    for path in sorted(glob.glob(f"{OUTPUTS_DIR}/funnel_*.json"), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("idea_title"):
                o = data.get("offer_refinement", {})
                lc = data.get("lead_capture", {})
                ct = data.get("ctas", [])
                sq = data.get("sequence", [])
                lp = data.get("landing_page", {})
                items.append(
                    {
                        "file": os.path.basename(path),
                        "ts": data.get("timestamp", ""),
                        "idea_title": data.get("idea_title", ""),
                        "target_audience": data.get("target_audience", ""),
                        "refined_headline": o.get("refined_headline", ""),
                        "refined_promise": o.get("refined_promise", ""),
                        "main_sale_angle": o.get("main_sale_angle", ""),
                        "urgency_element": o.get("urgency_element", ""),
                        "risk_reversal": o.get("risk_reversal", ""),
                        "price_anchor": o.get("ideal_price_anchor", ""),
                        "value_stack": o.get("value_stack", []),
                        "lead_capture": lc.get("lead_capture", ""),
                        "lead_link": lc.get("link", ""),
                        "n_ctas": len(ct),
                        "ctas": ct,
                        "n_msgs": len(sq),
                        "sequence": sq,
                        "above_fold": lp.get("above_fold", {}),
                        "lp_sections": [k for k in lp if k != "above_fold"],
                        "total_cost": data.get("total_cost", 0),
                    }
                )
        except Exception:
            pass
    return items


def load_others():
    items = []
    for path in sorted(glob.glob(f"{OUTPUTS_DIR}/*.json"), reverse=True):
        fname = os.path.basename(path)
        if any(
            fname.startswith(p)
            for p in ("scoring_", "blueprint_", "funnel_", "content_", "video_", "queue_")
        ):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            t = data.get("task_type", fname.split("_")[0])
            items.append(
                {
                    "file": fname,
                    "ts": data.get("timestamp", ""),
                    "task_type": t,
                    "input": data.get("input", "")[:100],
                    "output": (data.get("output") or data.get("script") or "")[:280],
                }
            )
        except Exception:
            pass
    return items[:12]


def fmt_ts(ts):
    if len(ts) == 15:
        try:
            return datetime.strptime(ts, "%Y%m%d_%H%M%S").strftime("%d/%m/%Y %H:%M")
        except:
            pass
    return ts


def render_videos(videos):
    if not videos:
        return '<div class="empty">Nenhum vídeo ainda.<br>Rode: <code>python video_engine.py</code></div>'
    html = ""
    for idx, v in enumerate(videos):
        audio_badge = (
            '<span class="sbadge" style="background:#10b98120;color:#10b981;border:1px solid #10b98133">Áudio ✓</span>'
            if v["audio_ok"]
            else '<span class="sbadge grey">Sem áudio</span>'
        )
        video_badge = (
            f'<span class="sbadge" style="background:#3b82f620;color:#3b82f6;border:1px solid #3b82f633">Vídeo {v["video_status"]}</span>'
            if v.get("video_url") or v.get("video_id")
            else '<span class="sbadge grey">Script only</span>'
        )
        queue_items = "".join(
            f'<div class="bp-field"><span>{q["platform"]}</span><p>{q["status"]}</p></div>'
            for q in v.get("queue", [])
        )
        html += f"""
        <div class="bpcard" id="vid-{idx}">
          <div class="bpcard-header" onclick="toggleVid({idx})">
            <div class="bpcard-icon" style="background:#3b82f618;color:#3b82f6">🎬</div>
            <div class="bpcard-info">
              <div class="bpcard-title">{v['idea_title']}</div>
              <div class="bpcard-sub">
                {audio_badge}{video_badge}
                <span class="sbadge grey">{v['n_agressivas']}+{v['n_elegantes']} variações</span>
                {'<span class="sbadge grey">' + fmt_ts(v.get('ts','')) + '</span>' if v.get('ts') else ''}
              </div>
              <div class="bpcard-promise">{v.get('hook','')}</div>
            </div>
            <div class="scard-chev" id="vidchev-{idx}">›</div>
          </div>
          <div class="bpcard-body" id="vidbody-{idx}">
            <div class="bp-grid">
              <div class="bp-col">
                <div class="bp-section">Roteiro</div>
                <div class="bp-field"><span>Hook</span><p style="font-weight:700">{v.get('hook','')}</p></div>
                <div class="bp-field"><span>CTA</span><p style="color:#10b981;font-weight:700">{v.get('cta','')}</p></div>
                {'<div class="bp-field"><span>Roteiro completo</span><p style="font-size:12px;line-height:1.6">' + v.get('roteiro_final','').replace(chr(10),'<br>') + '</p></div>' if v.get('roteiro_final') else ''}
              </div>
              <div class="bp-col">
                <div class="bp-section">Produção</div>
                {'<div class="bp-field"><span>Áudio</span><p>' + v.get('audio_file','') + '</p></div>' if v.get('audio_file') else ''}
                {'<div class="bp-field"><span>Vídeo URL</span><p><a href="' + v.get('video_url','') + '" style="color:var(--blue)">' + v.get('video_url','') + '</a></p></div>' if v.get('video_url') else ''}
                {'<div class="bp-field"><span>HeyGen ID</span><p>' + v.get('video_id','') + '</p></div>' if v.get('video_id') else ''}
                <div class="bp-section">Distribution Queue</div>
                {queue_items}
              </div>
            </div>
            <div class="bp-field" style="margin-top:8px"><span>Caption</span><p>{v.get('caption','')}</p></div>
            <div class="bp-meta">Custo: ~${v.get('total_cost',0):.4f}</div>
          </div>
        </div>"""
    return html


def render_contents(contents):
    if not contents:
        return '<div class="empty">Nenhum conteúdo ainda.<br>Rode: <code>python content_engine.py</code></div>'
    html = ""
    for idx, ct in enumerate(contents):
        s = ct.get("summary", {})
        html += f"""
        <div class="bpcard" id="ct-{idx}">
          <div class="bpcard-header" onclick="toggleCt({idx})">
            <div class="bpcard-icon" style="background:#ec489918;color:#ec4899">🎯</div>
            <div class="bpcard-info">
              <div class="bpcard-title">{ct['idea_title']}</div>
              <div class="bpcard-sub">
                <span class="sbadge grey">{s.get('angles',0)} ângulos</span>
                <span class="sbadge grey">{s.get('hooks',0)} ganchos</span>
                <span class="sbadge grey">{s.get('posts',0)} posts</span>
                <span class="sbadge grey">{s.get('scripts',0)} roteiros</span>
                {'<span class="sbadge grey">' + fmt_ts(ct.get('ts','')) + '</span>' if ct.get('ts') else ''}
              </div>
              <div class="bpcard-promise">Custo: ~${ct.get('total_cost',0):.4f}</div>
            </div>
            <div class="scard-chev" id="ctchev-{idx}">›</div>
          </div>
          <div class="bpcard-body" id="ctbody-{idx}">
            <div class="bp-grid">
              <div class="bp-col">
                <div class="bp-section">Ângulos</div>
                {''.join(f'<div class="bp-field"><span>{a.get("tipo","")}</span><p>{a.get("titulo","")}</p><p style="color:var(--muted2);font-size:11px">{a.get("gancho_sugerido","")}</p></div>' for a in ct.get("angles",[]))}
              </div>
              <div class="bp-col">
                <div class="bp-section">Top Ganchos</div>
                {''.join(f'<div class="bp-field"><p>→ {h}</p></div>' for h in ct.get("hooks",[])[:10])}
              </div>
            </div>
            {'<div class="bp-section">Posts</div>' + ''.join(f"""<div class="bp-field"><span>Gancho</span><p>{p.get("gancho","")}</p><span>Desenvolvimento</span><p style="font-size:12px">{str(p.get("desenvolvimento",""))[:300]}</p><span>CTA</span><p style="color:#10b981;font-weight:700">{p.get("cta","")}</p></div>""" for p in ct.get("posts",[])) if ct.get("posts") else ''}
            {'<div class="bp-section">Roteiros</div>' + ''.join(f'<div class="bp-field"><span>[{sc.get("tom","")}] {sc.get("duracao_estimada","")}</span><p><strong>Gancho:</strong> {sc.get("gancho","")}</p><p><strong>CTA:</strong> {sc.get("cta","")}</p></div>' for sc in ct.get("scripts",[])) if ct.get("scripts") else ''}
          </div>
        </div>"""
    return html


def render_blueprints(blueprints):
    if not blueprints:
        return '<div class="empty">Nenhum blueprint ainda.<br>Rode: <code>python product_engine.py</code></div>'

    html = ""
    for idx, bp in enumerate(blueprints):
        pc = PRIORITY_COLOR.get(bp.get("priority", ""), "#3b82f6")
        s = bp.get("product_strategy", {})
        o = bp.get("offer_design", {})
        n = bp.get("naming_options", {})
        c = bp.get("copy_base", {})
        st = bp.get("product_structure", {})
        names_html = "".join(
            f'<div class="nm-item"><span class="nm-tag">{nm.get("tom","")}</span>'
            f'<strong>{nm.get("name","")}</strong> — {nm.get("justificativa","")[:55]}</div>'
            for nm in n.get("names", [])[:5]
        )
        bullets_html = "".join(f"<li>{b}</li>" for b in c.get("value_bullets", []))
        obj_html = "".join(
            f'<div class="obj-row"><div class="obj-q">"{ob.get("objection","")}"</div>'
            f'<div class="obj-a">→ {ob.get("response","")}</div></div>'
            for ob in c.get("objections", [])
        )
        modules_html = "".join(
            f'<div class="mod-item"><div class="mod-name">{m.get("name","")}</div>'
            f'<div class="mod-obj">{m.get("objective","")}</div></div>'
            for m in st.get("modules", [])
        )
        deliverables_html = "".join(f"<li>{d}</li>" for d in o.get("deliverables", []))
        diffs_html = "".join(f"<li>{d}</li>" for d in s.get("competitive_differentials", []))

        html += f"""
        <div class="bpcard" id="bp-{idx}">
          <div class="bpcard-header" onclick="toggleBp({idx})">
            <div class="bpcard-icon" style="background:{pc}18;color:{pc}">🏗️</div>
            <div class="bpcard-info">
              <div class="bpcard-title">{bp.get('idea_title','')}</div>
              <div class="bpcard-sub">
                <span class="sbadge grey">{bp.get('best_initial_format','')}</span>
                <span class="sbadge grey">{bp.get('entry_ticket','')}</span>
                <span class="sbadge" style="background:{pc}18;color:{pc};border:1px solid {pc}33">{bp.get('top_name','')}</span>
                {'<span class="sbadge grey">' + fmt_ts(bp.get('ts','')) + '</span>' if bp.get('ts') else ''}
              </div>
              <div class="bpcard-promise">{bp.get('main_promise','')}</div>
            </div>
            <div class="scard-chev" id="bpchev-{idx}">›</div>
          </div>

          <div class="bpcard-body" id="bpbody-{idx}">
            <div class="bp-grid">

              <div class="bp-col">
                <div class="bp-section">Estratégia</div>
                <div class="bp-field"><span>Transformação</span><p>{s.get('transformation','')}</p></div>
                <div class="bp-field"><span>Mecanismo único</span><p>{s.get('unique_mechanism','')}</p></div>
                <div class="bp-field"><span>MVP</span><p>{s.get('mvp_recommendation','')}</p></div>
                {'<div class="bp-field"><span>Diferenciais</span><ul>' + diffs_html + '</ul></div>' if diffs_html else ''}

                <div class="bp-section">Oferta</div>
                <div class="bp-field"><span>Ângulo</span><p>{o.get('positioning_angle','')}</p></div>
                <div class="bp-field"><span>Low ticket</span><p>{o.get('low_ticket_version','')}</p></div>
                <div class="bp-field"><span>Premium</span><p>{o.get('premium_version','')}</p></div>
                {'<div class="bp-field"><span>Entregáveis</span><ul>' + deliverables_html + '</ul></div>' if deliverables_html else ''}
              </div>

              <div class="bp-col">
                <div class="bp-section">Copy</div>
                <div class="bp-field headline-field"><p>{c.get('headline','')}</p></div>
                <div class="bp-field"><span>Sub</span><p>{c.get('subheadline','')}</p></div>
                <div class="bp-field"><span>Hook</span><p>{c.get('opening_hook','')}</p></div>
                <div class="bp-field"><span>CTA</span><p style="color:#10b981;font-weight:700">{c.get('cta','')}</p></div>
                {'<div class="bp-field"><span>Bullets de valor</span><ul>' + bullets_html + '</ul></div>' if bullets_html else ''}
                {'<div class="bp-section">Objeções</div>' + obj_html if obj_html else ''}
              </div>

            </div>

            {'<div class="bp-section">Nomes</div><div class="names-grid">' + names_html + '</div>' if names_html else ''}
            {'<div class="bp-section">Módulos do produto</div><div class="modules-grid">' + modules_html + '</div>' if modules_html else ''}

            <div class="bp-meta">
              Custo total: ~${bp.get('total_cost', 0):.4f}
            </div>
          </div>
        </div>"""
    return html


def render_funnels(funnels):
    if not funnels:
        return '<div class="empty">Nenhum funil ainda.<br>Rode: <code>python sales_engine.py</code></div>'
    html = ""
    for idx, fn in enumerate(funnels):
        ctas_html = "".join(
            f'<div class="bp-field"><span style="color:#a855f7">[{c.get("tom","")}]</span>'
            f'<p style="font-weight:700">{c.get("button_text","")}</p>'
            f'<p style="font-size:11px;color:var(--muted2)">{c.get("context","")}</p></div>'
            for c in fn.get("ctas", [])
        )
        seq_html = "".join(
            f'<div class="bp-field">'
            f'<span>[{m.get("timing","")}] Msg {m.get("numero","")}: {m.get("nome","")}</span>'
            f'<p style="font-size:11px">{m.get("assunto","")}</p>'
            f'<p style="color:#10b981;font-size:11px">→ {m.get("cta","")}</p></div>'
            for m in fn.get("sequence", [])
        )
        stack_html = "".join(f"<li>{v}</li>" for v in fn.get("value_stack", []))
        lp_sections = ", ".join(fn.get("lp_sections", []))
        af = fn.get("above_fold", {})

        html += f"""
        <div class="bpcard" id="fn-{idx}">
          <div class="bpcard-header" onclick="toggleFn({idx})">
            <div class="bpcard-icon" style="background:#a855f718;color:#a855f7">💰</div>
            <div class="bpcard-info">
              <div class="bpcard-title">{fn['idea_title']}</div>
              <div class="bpcard-sub">
                <span class="sbadge" style="background:#a855f720;color:#a855f7;border:1px solid #a855f733">{fn['lead_capture']} capture</span>
                <span class="sbadge grey">{fn['n_ctas']} CTAs</span>
                <span class="sbadge grey">{fn['n_msgs']} msgs sequência</span>
                {'<span class="sbadge grey">' + fmt_ts(fn.get('ts','')) + '</span>' if fn.get('ts') else ''}
              </div>
              <div class="bpcard-promise">{fn.get('refined_headline','')}</div>
            </div>
            <div class="scard-chev" id="fnchev-{idx}">›</div>
          </div>
          <div class="bpcard-body" id="fnbody-{idx}">
            <div class="bp-grid">
              <div class="bp-col">
                <div class="bp-section">Oferta Refinada</div>
                <div class="bp-field"><span>Promessa</span><p style="font-weight:700">{fn.get('refined_promise','')}</p></div>
                <div class="bp-field"><span>Ângulo de venda</span><p>{fn.get('main_sale_angle','')}</p></div>
                <div class="bp-field"><span>Urgência</span><p style="color:#f59e0b">{fn.get('urgency_element','')}</p></div>
                <div class="bp-field"><span>Garantia</span><p style="color:#10b981">{fn.get('risk_reversal','')}</p></div>
                <div class="bp-field"><span>Preço âncora</span><p style="color:#a855f7;font-weight:700">{fn.get('price_anchor','')}</p></div>
                {'<div class="bp-field"><span>Value Stack</span><ul>' + stack_html + '</ul></div>' if stack_html else ''}
                {'<div class="bp-section">Landing Page (above fold)</div>' + '<div class="bp-field"><span>Headline</span><p style="font-weight:700">' + af.get('headline','') + '</p></div><div class="bp-field"><span>Sub</span><p>' + af.get('subheadline','') + '</p></div><div class="bp-field"><span>Botão</span><p style="color:#10b981;font-weight:700">' + af.get('cta_button','') + '</p></div>' if af else ''}
                <div class="bp-field"><span>Seções LP</span><p style="font-size:11px;color:var(--muted2)">{lp_sections}</p></div>
              </div>
              <div class="bp-col">
                <div class="bp-section">CTAs de alto impacto</div>
                {ctas_html if ctas_html else '<div class="bp-field"><p style="color:var(--muted)">Nenhum CTA gerado</p></div>'}
                <div class="bp-section">Sequência de Conversão ({fn['n_msgs']} msgs)</div>
                {seq_html if seq_html else '<div class="bp-field"><p style="color:var(--muted)">Nenhuma sequência gerada</p></div>'}
                <div class="bp-section">Lead Capture</div>
                <div class="bp-field"><span>Canal</span><p style="font-weight:700">{fn.get('lead_capture','')}</p></div>
                <div class="bp-field"><span>Link</span><p style="font-size:11px;word-break:break-all"><a href="{fn.get('lead_link','')}" style="color:#a855f7">{fn.get('lead_link','')}</a></p></div>
              </div>
            </div>
            <div class="bp-meta">Custo: ~${fn.get('total_cost',0):.4f}</div>
          </div>
        </div>"""
    return html


def render_sessions_section(sessions):
    if not sessions:
        return ""

    STATUS_COLOR = {
        "completed": "#10b981",
        "running": "#3b82f6",
        "aborted": "#ef4444",
        "error": "#ef4444",
        "interrupted": "#f59e0b",
    }
    STATUS_ICON = {
        "completed": "✅",
        "running": "🔄",
        "aborted": "🛑",
        "error": "❌",
        "interrupted": "⏸",
    }
    MODE_ICON = {"auto": "🤖", "semi_auto": "🧑‍💻", "manual": "👤"}
    DECISION_COLOR = {"executar": "#10b981", "ajustar": "#f59e0b", "descartar": "#ef4444"}

    rows = ""
    for s in sessions[:15]:
        status = s.get("status", "?")
        scolor = STATUS_COLOR.get(status, "#888")
        sicon = STATUS_ICON.get(status, "?")
        micon = MODE_ICON.get(s.get("mode", ""), "?")
        decision = s.get("decision", "")
        dcolor = DECISION_COLOR.get(decision, "#7a90a8")
        engines = ", ".join(s.get("engines_run", [])) or "—"
        rows += f"""
        <div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr 80px;gap:12px;
                    padding:12px 16px;border-bottom:1px solid #1e2d45;font-size:0.83rem;align-items:center">
          <div>
            <div style="font-weight:600">{s.get('objective','')[:52]}</div>
            <div style="color:#7a90a8;margin-top:2px">{s.get('market','')} · {s.get('started_at','')[:16]}</div>
            {f'<div style="color:#7a90a8;font-size:0.76rem;margin-top:2px">→ {s.get("next_rec","")[:60]}</div>' if s.get("next_rec") else ''}
          </div>
          <div>
            <div style="color:#7a90a8;font-size:0.75rem">Engines</div>
            <div>{engines[:30]}</div>
          </div>
          <div>
            <div style="color:#7a90a8;font-size:0.75rem">Decisão</div>
            <div style="color:{dcolor};font-weight:600">{decision.upper() if decision else '—'}</div>
          </div>
          <div>
            <span style="color:#7a90a8">{micon} {s.get('mode','')}</span><br>
            <span style="font-size:0.75rem;color:#7a90a8">{s.get('nodes_done',0)}/11 nós · ${s.get('total_cost',0):.4f}</span>
          </div>
          <div style="text-align:center">
            <span style="background:{scolor}20;color:{scolor};border:1px solid {scolor}33;
                         border-radius:20px;padding:3px 10px;font-size:0.78rem">
              {sicon} {status}
            </span>
          </div>
        </div>"""

    return f"""
<!-- MASTER CONTROLLER SESSIONS -->
<div class="sec-title" style="margin-top:32px">MYO — Sessões do Master Controller</div>
<div style="background:#0a1628;border-radius:12px;border:1px solid #1e2d45;overflow:hidden;margin-top:12px">
  <div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr 80px;gap:12px;
              padding:10px 16px;background:#1e2d45;font-size:0.75rem;color:#7a90a8;
              text-transform:uppercase;letter-spacing:.5px">
    <div>Objetivo</div><div>Engines</div><div>Decisão</div><div>Modo</div><div>Status</div>
  </div>
  {rows}
</div>"""


def render_scaling_section(scaling):
    if not scaling:
        return ""

    ACTION_COLOR = {"escalar": "#10b981", "otimizar": "#f59e0b", "stop": "#ef4444"}
    ACTION_ICON = {"escalar": "🚀", "otimizar": "🔧", "stop": "🛑"}
    STATUS_COLOR = {"scale": "#10b981", "optimize": "#f59e0b", "stop": "#ef4444"}

    n_escalar = sum(1 for s in scaling if s.get("final_action") == "escalar")
    n_otimizar = sum(1 for s in scaling if s.get("final_action") == "otimizar")
    n_stop = sum(1 for s in scaling if s.get("final_action") == "stop")

    cards = ""
    for s in scaling[:12]:
        action = s.get("final_action", "stop")
        status = s.get("scaling_status", "stop")
        acolor = ACTION_COLOR.get(action, "#888")
        score = s.get("scaling_score", 0)

        repeat_html = "".join(f"<li>✓ {r[:70]}</li>" for r in s.get("repeat", [])[:3])
        kill_html = "".join(f"<li>✗ {k[:70]}</li>" for k in s.get("kill", [])[:2])
        plan_html = "".join(
            f'<div style="font-size:0.78rem;color:#a0aec0;margin:2px 0">'
            f'{"🔴" if p.get("prioridade")=="alta" else "🟡"} '
            f'[{p.get("dia","")}] {p.get("acao","")[:60]}</div>'
            for p in s.get("plano_7_dias", [])[:3]
        )

        cards += f"""
        <div class="bp-card" style="border-left:4px solid {acolor}">
          <div class="bp-header">
            <span class="sbadge" style="background:{acolor}20;color:{acolor};border:1px solid {acolor}33">
              {ACTION_ICON.get(action,'')} {action.upper()}
            </span>
            <span style="margin-left:auto;font-size:1.4rem;font-weight:700;color:{acolor}">{score}/100</span>
          </div>
          <div class="bp-title">{s.get('idea_title','')[:55]}</div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0;font-size:0.78rem">
            <div style="text-align:center"><div style="color:#7a90a8">Perf</div><div style="font-weight:600">{s.get('performance_score',0)}</div></div>
            <div style="text-align:center"><div style="color:#7a90a8">Valid</div><div style="font-weight:600">{s.get('validation_score',0)}</div></div>
            <div style="text-align:center"><div style="color:#7a90a8">Conv</div><div style="font-weight:600">{s.get('conversion_rate',0)*100:.1f}%</div></div>
          </div>
          {f'<div style="font-size:0.82rem;margin-bottom:6px;color:#e2e8f0"><em>{s.get("insight","")[:100]}</em></div>' if s.get("insight") else ""}
          {f'<div style="font-size:0.8rem;margin-bottom:4px"><strong>Repetir:</strong><ul style="margin:4px 0 0 16px;padding:0">{repeat_html}</ul></div>' if repeat_html else ""}
          {f'<div style="font-size:0.8rem;margin-bottom:4px"><strong>Eliminar:</strong><ul style="margin:4px 0 0 16px;padding:0">{kill_html}</ul></div>' if kill_html else ""}
          {f'<div style="font-size:0.8rem;margin-top:8px"><strong>Plano 7 dias:</strong>{plan_html}</div>' if plan_html else ""}
          {f'<div style="font-size:0.82rem;color:#10b981;margin-top:6px"><strong>→</strong> {s.get("next_steps","")[:100]}</div>' if s.get("next_steps") else ""}
          <div class="bp-meta">{s.get('ts','')}</div>
        </div>"""

    return f"""
<!-- SCALING ENGINE -->
<div class="sec-title" style="margin-top:32px">Scaling Engine — Decisões Estratégicas</div>
<div style="display:flex;gap:12px;margin:12px 0;flex-wrap:wrap">
  <div style="background:#10b98115;border:1px solid #10b98133;border-radius:8px;padding:10px 20px;text-align:center">
    <div style="font-size:1.5rem;font-weight:700;color:#10b981">{n_escalar}</div>
    <div style="font-size:0.78rem;color:#7a90a8">🚀 Escalando</div>
  </div>
  <div style="background:#f59e0b15;border:1px solid #f59e0b33;border-radius:8px;padding:10px 20px;text-align:center">
    <div style="font-size:1.5rem;font-weight:700;color:#f59e0b">{n_otimizar}</div>
    <div style="font-size:0.78rem;color:#7a90a8">🔧 Otimizando</div>
  </div>
  <div style="background:#ef444415;border:1px solid #ef444433;border-radius:8px;padding:10px 20px;text-align:center">
    <div style="font-size:1.5rem;font-weight:700;color:#ef4444">{n_stop}</div>
    <div style="font-size:0.78rem;color:#7a90a8">🛑 Parado</div>
  </div>
</div>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-top:8px">
  {cards}
</div>"""


def render_crm_section(crm_leads):
    if not crm_leads:
        return ""

    TEMP_COLOR = {"quente": "#ef4444", "morno": "#f59e0b", "frio": "#3b82f6"}
    TEMP_ICON = {"quente": "🔥", "morno": "🟡", "frio": "❄️"}
    PIPELINE_STAGES = ["entrada", "interessado", "qualificado", "proposta", "fechamento", "cliente"]

    n_total = len(crm_leads)
    n_quentes = sum(1 for l in crm_leads if l.get("temperature") == "quente")
    n_cli = sum(1 for l in crm_leads if l.get("pipeline_stage") == "cliente")
    conv_rate = round(n_cli / n_total * 100, 1) if n_total else 0

    # mini kanban por estágio
    kanban = ""
    for stage in PIPELINE_STAGES:
        stage_leads = [l for l in crm_leads if l.get("pipeline_stage") == stage]
        if not stage_leads:
            continue
        cards_html = ""
        for l in sorted(stage_leads, key=lambda x: -x.get("lead_score", 0))[:6]:
            temp = l.get("temperature", "frio")
            tcolor = TEMP_COLOR.get(temp, "#888")
            cards_html += f"""
            <div style="background:#0d1b2a;border-radius:6px;padding:10px;border-left:3px solid {tcolor};margin-bottom:8px">
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
                <span>{TEMP_ICON.get(temp,'')}</span>
                <span style="font-weight:600;font-size:0.88rem">{l.get('name','?')}</span>
                <span style="margin-left:auto;font-size:0.78rem;color:#7a90a8">{l.get('lead_score',0)}/100</span>
              </div>
              <div style="font-size:0.75rem;color:#7a90a8">{l.get('source','?')} · {l.get('product','?')[:28]}</div>
              {f'<div style="font-size:0.75rem;color:#a0aec0;margin-top:3px">"{l.get("message","")[:50]}"</div>' if l.get("message") else ''}
            </div>"""
        kanban += f"""
        <div style="background:#0a1628;border-radius:10px;padding:14px;min-width:180px;flex:1">
          <div style="font-weight:600;font-size:0.82rem;color:#7a90a8;text-transform:uppercase;margin-bottom:10px;letter-spacing:.5px">
            {stage} <span style="color:#3b82f6">({len(stage_leads)})</span>
          </div>
          {cards_html}
        </div>"""

    return f"""
<!-- CRM ENGINE -->
<div class="sec-title" style="margin-top:32px">CRM Engine — Pipeline de Leads</div>
<div style="display:flex;gap:12px;margin:12px 0;flex-wrap:wrap">
  <div style="background:#ef444415;border:1px solid #ef444433;border-radius:8px;padding:10px 18px;text-align:center">
    <div style="font-size:1.4rem;font-weight:700;color:#ef4444">{n_quentes}</div>
    <div style="font-size:0.78rem;color:#7a90a8">🔥 Leads quentes</div>
  </div>
  <div style="background:#10b98115;border:1px solid #10b98133;border-radius:8px;padding:10px 18px;text-align:center">
    <div style="font-size:1.4rem;font-weight:700;color:#10b981">{n_cli}</div>
    <div style="font-size:0.78rem;color:#7a90a8">✅ Clientes</div>
  </div>
  <div style="background:#3b82f615;border:1px solid #3b82f633;border-radius:8px;padding:10px 18px;text-align:center">
    <div style="font-size:1.4rem;font-weight:700;color:#3b82f6">{conv_rate}%</div>
    <div style="font-size:0.78rem;color:#7a90a8">Taxa de conversão</div>
  </div>
  <div style="background:#1e2d45;border-radius:8px;padding:10px 18px;text-align:center">
    <div style="font-size:1.4rem;font-weight:700;color:#e2e8f0">{n_total}</div>
    <div style="font-size:0.78rem;color:#7a90a8">Total de leads</div>
  </div>
</div>
<div style="display:flex;gap:12px;overflow-x:auto;padding-bottom:8px">
  {kanban}
</div>"""


def render_validation_section(validations):
    if not validations:
        return ""

    ACTION_COLOR = {"escalar": "#10b981", "ajustar": "#f59e0b", "descartar": "#ef4444"}
    ACTION_ICON = {"escalar": "🚀", "ajustar": "🔧", "descartar": "🗑"}
    STATUS_COLOR = {"forte": "#10b981", "medio": "#f59e0b", "fraco": "#ef4444"}

    cards = ""
    for v in validations[:20]:
        action = v.get("final_action", "descartar")
        status = v.get("validation_status", "fraco")
        acolor = ACTION_COLOR.get(action, "#888")
        scolor = STATUS_COLOR.get(status, "#888")
        score = v.get("validation_score", 0)
        cards += f"""
        <div class="bp-card" style="border-left:4px solid {acolor}">
          <div class="bp-header">
            <span class="sbadge" style="background:{acolor}20;color:{acolor};border:1px solid {acolor}33">
              {ACTION_ICON.get(action,'')} {action.upper()}
            </span>
            <span class="sbadge" style="background:{scolor}20;color:{scolor};border:1px solid {scolor}33">
              {status}
            </span>
            <span class="sbadge" style="background:#1e2d45;color:#7a90a8">{v.get('platform','?')}</span>
            <span style="margin-left:auto;font-size:1.4rem;font-weight:700;color:{acolor}">{score}/100</span>
          </div>
          <div class="bp-title">{v.get('idea_title','')[:60]}</div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0;font-size:0.78rem">
            <div style="text-align:center"><div style="color:#7a90a8">Views</div><div style="font-weight:600">{v.get('views',0):,}</div></div>
            <div style="text-align:center"><div style="color:#7a90a8">DMs</div><div style="font-weight:600">{v.get('dm_requests',0):,}</div></div>
            <div style="text-align:center"><div style="color:#7a90a8">Leads</div><div style="font-weight:600">{v.get('leads',0):,}</div></div>
          </div>
          {'<div style="font-size:0.8rem;margin-bottom:4px"><strong>Sinal:</strong> ' + v.get('audience_signal','')[:100] + '</div>' if v.get('audience_signal') else ''}
          {'<div style="font-size:0.82rem;color:#10b981"><strong>Próxima ação:</strong> ' + v.get('next_action','')[:120] + '</div>' if v.get('next_action') else ''}
          <div class="bp-meta">{v.get('ts','')}</div>
        </div>"""

    n_escalar = sum(1 for v in validations if v.get("final_action") == "escalar")
    n_ajustar = sum(1 for v in validations if v.get("final_action") == "ajustar")
    n_descartar = sum(1 for v in validations if v.get("final_action") == "descartar")

    summary = f"""
<div style="display:flex;gap:16px;margin:12px 0;flex-wrap:wrap">
  <div style="background:#10b98115;border:1px solid #10b98133;border-radius:8px;padding:12px 20px;text-align:center">
    <div style="font-size:1.6rem;font-weight:700;color:#10b981">{n_escalar}</div>
    <div style="font-size:0.8rem;color:#7a90a8">🚀 Escalar</div>
  </div>
  <div style="background:#f59e0b15;border:1px solid #f59e0b33;border-radius:8px;padding:12px 20px;text-align:center">
    <div style="font-size:1.6rem;font-weight:700;color:#f59e0b">{n_ajustar}</div>
    <div style="font-size:0.8rem;color:#7a90a8">🔧 Ajustar</div>
  </div>
  <div style="background:#ef444415;border:1px solid #ef444433;border-radius:8px;padding:12px 20px;text-align:center">
    <div style="font-size:1.6rem;font-weight:700;color:#ef4444">{n_descartar}</div>
    <div style="font-size:0.8rem;color:#7a90a8">🗑 Descartar</div>
  </div>
</div>"""

    return f"""
<!-- VALIDATION ENGINE -->
<div class="sec-title" style="margin-top:32px">Validation Engine — Decisões de Mercado</div>
{summary}
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-top:8px">
  {cards}
</div>"""


def render_performance_section(performances, memory_items):
    if not performances and not memory_items:
        return ""

    BAND_COLOR = {"alta": "#10b981", "media": "#f59e0b", "baixa": "#ef4444"}
    BAND_LABEL = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}

    cards = ""
    for p in performances[:20]:
        band = p.get("performance_band", "baixa")
        color = BAND_COLOR.get(band, "#888")
        label = BAND_LABEL.get(band, band)
        score = p.get("performance_score", 0)
        worked = "".join(f"<li>{w}</li>" for w in p.get("what_worked", [])[:3])
        repeat = "".join(f"<li>→ {r}</li>" for r in p.get("repeat", [])[:2])
        next_c = p.get("next_content", "")
        gancho = p.get("gancho", "")
        cards += f"""
        <div class="bp-card" style="border-left:4px solid {color}">
          <div class="bp-header">
            <span class="sbadge" style="background:{color}20;color:{color};border:1px solid {color}33">{label}</span>
            <span class="sbadge" style="background:#1e2d45;color:#7a90a8">{p.get('asset_type','?')} · {p.get('platform','?')}</span>
            <span style="margin-left:auto;font-size:1.4rem;font-weight:700;color:{color}">{score}/100</span>
          </div>
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0;font-size:0.78rem">
            <div style="text-align:center"><div style="color:#7a90a8">Views</div><div style="font-weight:600">{p.get('views',0):,}</div></div>
            <div style="text-align:center"><div style="color:#7a90a8">Eng%</div><div style="font-weight:600">{p.get('engagement_rate',0)*100:.1f}%</div></div>
            <div style="text-align:center"><div style="color:#7a90a8">CTR</div><div style="font-weight:600">{p.get('click_rate',0)*100:.1f}%</div></div>
            <div style="text-align:center"><div style="color:#7a90a8">Leads</div><div style="font-weight:600">{p.get('leads',0):,}</div></div>
          </div>
          {f'<div style="font-size:0.8rem;color:#a0aec0;margin-bottom:8px">Gancho: <em>{gancho}</em></div>' if gancho else ""}
          {f'<div style="font-size:0.82rem;margin-bottom:6px"><strong>O que funcionou:</strong><ul style="margin:4px 0 0 16px;padding:0">{worked}</ul></div>' if worked else ""}
          {f'<div style="font-size:0.82rem;margin-bottom:6px"><strong>Repetir:</strong><ul style="margin:4px 0 0 16px;padding:0">{repeat}</ul></div>' if repeat else ""}
          {f'<div style="font-size:0.82rem;color:#10b981"><strong>Próximo conteúdo:</strong> {next_c[:120]}</div>' if next_c else ""}
          <div class="bp-meta">{p.get('ts','')}</div>
        </div>"""

    mem_html = ""
    if memory_items:
        top = memory_items[:6]
        mem_items_html = "".join(
            f"""
        <div style="background:#0d1b2a;border-radius:8px;padding:12px;border:1px solid #1e2d45">
          <div style="font-size:0.78rem;color:#7a90a8">{m.get('asset_type','?')} · {m.get('platform','?')} · score {m.get('performance_score',0)}</div>
          {f'<div style="font-size:0.85rem;margin:4px 0"><em>"{m.get("gancho","")}"</em></div>' if m.get('gancho') else ''}
          {''.join(f'<div style="font-size:0.8rem;color:#10b981">→ {r}</div>' for r in m.get('repeat',[])[:2])}
        </div>"""
            for m in top
        )
        mem_html = f"""
<div class="sec-title" style="margin-top:24px">Memória de Padrões Vencedores</div>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin-top:12px">
  {mem_items_html}
</div>"""

    return f"""
<!-- PERFORMANCE ENGINE -->
<div class="sec-title" style="margin-top:32px">Performance Engine — Análise de Ativos</div>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-top:12px">
  {cards if cards else '<div style="color:#7a90a8;padding:16px">Nenhum registro ainda. Rode: python performance_engine.py --json \'{{...}}\'</div>'}
</div>
{mem_html}"""


def _sim_claude_block(ins: dict) -> str:
    if not ins.get("estrategia_agora"):
        return ""
    alerta_html = ""
    if ins.get("alerta"):
        alerta_html = (
            '<div style="grid-column:1/-1">'
            '<span style="color:#f59e0b">⚠️ Alerta:</span> '
            f'<span style="color:#a0aec0">{ins["alerta"]}</span>'
            '</div>'
        )
    return (
        '<div style="margin-top:16px;padding:14px 18px;background:#1a2535;'
        'border:1px solid #2d3f55;border-radius:8px">'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;font-size:0.82rem">'
        '<div><span style="color:#7a90a8">Alavanca #1:</span> '
        f'<span style="color:#e2e8f0">{ins.get("alavanca_maior_impacto","")}</span></div>'
        '<div><span style="color:#7a90a8">Mais fácil:</span> '
        f'<span style="color:#e2e8f0">{ins.get("mais_facil_executar","")}</span></div>'
        '<div style="grid-column:1/-1"><span style="color:#7a90a8">Estratégia agora:</span> '
        f'<span style="color:#10b981;font-weight:600">{ins.get("estrategia_agora","")}</span></div>'
        f'{alerta_html}'
        '</div></div>'
    )


def render_simulator_section(simulations):
    if not simulations:
        return ""

    latest = simulations[-1]
    sc = latest.get("scenarios", {})
    base = sc.get("base", {})
    bev = latest.get("breakeven", {})
    dec = latest.get("decision", {})
    ins = latest.get("insights", {})
    rank = latest.get("ranking", [])
    inp = latest.get("input", {})

    SCENARIO_LABEL = {
        "base": "Base Atual",
        "dobrar_leads": "Dobrar Leads",
        "melhorar_conversao": "Melhorar Conversão",
        "aumentar_preco": "Aumentar Preço",
        "combo_leve": "Combo Leve",
        "combo_agressivo": "Combo Agressivo",
    }
    SC_COLOR = {
        "base": "#6366f1",
        "dobrar_leads": "#10b981",
        "melhorar_conversao": "#3b82f6",
        "aumentar_preco": "#f59e0b",
        "combo_leve": "#ec4899",
        "combo_agressivo": "#ef4444",
    }

    max_rev = max((s.get("revenue_month", 0) for s in sc.values()), default=1)

    # scenario bars
    bars_html = ""
    for name, sc_item in sc.items():
        rev = sc_item.get("revenue_month", 0)
        prf = sc_item.get("profit", 0)
        dlt = sc_item.get("delta_lucro_pct", 0)
        pct = round(rev / max_rev * 100) if max_rev > 0 else 0
        color = SC_COLOR.get(name, "#888")
        mg = sc_item.get("margin_pct", 0)
        mc = "#10b981" if mg >= 70 else "#f59e0b" if mg >= 40 else "#ef4444"
        dlt_badge = (
            f'<span style="font-size:0.75rem;color:#10b981;margin-left:8px">+{dlt:.0f}%</span>'
            if dlt > 0
            else ""
        )
        bars_html += f"""
        <div style="margin:10px 0">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <span style="font-size:0.82rem;color:#e2e8f0;font-weight:600">{SCENARIO_LABEL.get(name,name)}</span>
            <span style="font-size:0.82rem;color:#a0aec0">R${rev:,.0f}/mês · lucro <span style="color:{mc};font-weight:700">R${prf:,.0f}</span>{dlt_badge}</span>
          </div>
          <div style="background:#1e2a3a;border-radius:4px;height:10px">
            <div style="width:{pct}%;background:{color};border-radius:4px;height:10px"></div>
          </div>
        </div>"""

    # ranking medalhas
    RANK_LABEL = {
        "dobrar_leads": "Dobrar leads",
        "melhorar_conversao": "Melhorar conversão",
        "aumentar_preco": "Aumentar preço",
        "combo_leve": "Combo leve",
        "combo_agressivo": "Combo agressivo",
    }
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    rank_html = ""
    for i, (name, delta) in enumerate(rank[:5]):
        rank_html += f"""
        <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 14px;background:#1a2535;border-radius:6px;margin:4px 0">
          <span style="font-size:1rem">{medals[i]}</span>
          <span style="font-size:0.85rem;color:#e2e8f0;flex:1;margin-left:10px">{RANK_LABEL.get(name,name)}</span>
          <span style="font-size:0.85rem;font-weight:700;color:#10b981">+{delta:.0f}% lucro</span>
        </div>"""

    # decisões
    DICON = {"maxima": "🚨", "alta": "⚠️", "media": "ℹ️", "escala": "🚀"}
    DCOLOR = {"acao_prioritaria": "#ef4444", "acao_secundaria": "#f59e0b", "acao_futura": "#6366f1"}
    DLABEL = {
        "acao_prioritaria": "🔴 PRIORITÁRIA",
        "acao_secundaria": "🟡 SECUNDÁRIA",
        "acao_futura": "🔵 FUTURA",
    }
    dec_html = ""
    for key in ["acao_prioritaria", "acao_secundaria", "acao_futura"]:
        d = dec.get(key, {})
        if d and d.get("descricao"):
            c = DCOLOR[key]
            dec_html += f"""
            <div style="padding:10px 16px;background:{c}10;border:1px solid {c}33;border-radius:8px;margin:6px 0">
              <div style="font-size:0.75rem;color:#7a90a8;margin-bottom:3px">{DLABEL[key]} · +{d.get('impacto_pct',0):.0f}% lucro</div>
              <div style="font-size:0.88rem;color:#e2e8f0;font-weight:600">{d.get('descricao','')}</div>
            </div>"""

    # plano 4 semanas
    plano_html = ""
    for w in ins.get("plano_acao", [])[:4]:
        plano_html += f"""
        <div style="background:#1a2535;border:1px solid #2d3f55;border-radius:8px;padding:12px 16px">
          <div style="font-size:0.75rem;color:#7a90a8;margin-bottom:4px">SEMANA {w.get('semana','')}</div>
          <div style="font-size:0.85rem;color:#e2e8f0;margin-bottom:4px">{w.get('acao','')[:60]}</div>
          <div style="font-size:0.78rem;color:#10b981">→ {w.get('meta','')[:60]}</div>
        </div>"""

    mg_color = (
        "#10b981"
        if base.get("margin_pct", 0) >= 70
        else "#f59e0b"
        if base.get("margin_pct", 0) >= 40
        else "#ef4444"
    )

    return f"""
<!-- GROWTH SIMULATOR -->
<div class="sec-title" style="margin-top:32px">Growth Simulator — Painel de CEO</div>

<!-- base KPIs -->
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px;margin:16px 0">
  <div style="background:#6366f115;border:1px solid #6366f133;border-radius:10px;padding:14px 18px">
    <div style="font-size:0.75rem;color:#7a90a8;text-transform:uppercase;margin-bottom:5px">Leads/dia</div>
    <div style="font-size:1.5rem;font-weight:800;color:#6366f1">{inp.get('leads',0):.0f}</div>
  </div>
  <div style="background:#3b82f615;border:1px solid #3b82f633;border-radius:10px;padding:14px 18px">
    <div style="font-size:0.75rem;color:#7a90a8;text-transform:uppercase;margin-bottom:5px">Conversão</div>
    <div style="font-size:1.5rem;font-weight:800;color:#3b82f6">{inp.get('conversion',0)*100:.1f}%</div>
  </div>
  <div style="background:#f59e0b15;border:1px solid #f59e0b33;border-radius:10px;padding:14px 18px">
    <div style="font-size:0.75rem;color:#7a90a8;text-transform:uppercase;margin-bottom:5px">Ticket</div>
    <div style="font-size:1.5rem;font-weight:800;color:#f59e0b">R${inp.get('ticket',0):,.0f}</div>
  </div>
  <div style="background:#10b98115;border:1px solid #10b98133;border-radius:10px;padding:14px 18px">
    <div style="font-size:0.75rem;color:#7a90a8;text-transform:uppercase;margin-bottom:5px">Receita/mês</div>
    <div style="font-size:1.5rem;font-weight:800;color:#10b981">R${base.get('revenue_month',0):,.0f}</div>
  </div>
  <div style="background:{mg_color}15;border:1px solid {mg_color}33;border-radius:10px;padding:14px 18px">
    <div style="font-size:0.75rem;color:#7a90a8;text-transform:uppercase;margin-bottom:5px">Lucro/mês</div>
    <div style="font-size:1.5rem;font-weight:800;color:{mg_color}">R${base.get('profit',0):,.0f}</div>
    <div style="font-size:0.75rem;color:#7a90a8;margin-top:3px">{base.get('margin_pct',0):.1f}% margem</div>
  </div>
  <div style="background:#ec489915;border:1px solid #ec489933;border-radius:10px;padding:14px 18px">
    <div style="font-size:0.75rem;color:#7a90a8;text-transform:uppercase;margin-bottom:5px">Break-even</div>
    <div style="font-size:1.5rem;font-weight:800;color:#ec4899">{bev.get('breakeven_leads_dia',0):.0f}</div>
    <div style="font-size:0.75rem;color:#7a90a8;margin-top:3px">leads/dia mínimos</div>
  </div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:16px">

  <!-- cenários -->
  <div style="background:#131e2e;border:1px solid #1e2d45;border-radius:10px;padding:20px">
    <div style="font-size:0.85rem;font-weight:600;color:#e2e8f0;margin-bottom:12px">📈 Cenários Simulados</div>
    {bars_html}
  </div>

  <!-- ranking + decisões -->
  <div>
    <div style="background:#131e2e;border:1px solid #1e2d45;border-radius:10px;padding:20px;margin-bottom:16px">
      <div style="font-size:0.85rem;font-weight:600;color:#e2e8f0;margin-bottom:10px">🏆 Ranking de Alavancas</div>
      {rank_html}
    </div>
    <div style="background:#131e2e;border:1px solid #1e2d45;border-radius:10px;padding:20px">
      <div style="font-size:0.85rem;font-weight:600;color:#e2e8f0;margin-bottom:10px">🤖 Decisão Automática</div>
      {dec_html if dec_html else '<div style="color:#7a90a8;font-size:0.82rem">Rode o simulador para gerar decisões</div>'}
    </div>
  </div>

</div>

{f'<div style="margin-top:20px"><div style="font-size:0.85rem;font-weight:600;color:#e2e8f0;margin-bottom:12px">📅 Plano de Ação — 4 Semanas</div><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px">{plano_html}</div></div>' if plano_html else ""}

{_sim_claude_block(ins)}

<div style="margin-top:12px;font-size:0.75rem;color:#4a5568;text-align:right">{len(simulations)} simulações salvas · última: {latest.get('timestamp','')[:15]}</div>"""


def render_financial_section(fin):
    if not fin:
        return ""

    products = fin.get("product_financials", [])
    monthly_costs = fin.get("monthly_costs", [])
    projs = fin.get("projections", [])
    goal = fin.get("goal", {})
    analysis = fin.get("last_analysis", {})
    latest = projs[-1] if projs else {}

    monthly_revenue = latest.get("monthly_revenue", 0)
    monthly_cost = sum(c.get("cost", 0) for c in monthly_costs)
    monthly_profit = latest.get("monthly_profit", 0)
    monthly_margin = latest.get("monthly_margin_pct", 0)
    daily_revenue = latest.get("daily_revenue", 0)
    meta = goal.get("meta", 0)
    faltam = max(0, meta - monthly_revenue)
    meta_pct = min(100, round(monthly_revenue / meta * 100)) if meta > 0 else 0

    mg_color = (
        "#10b981" if monthly_margin >= 70 else "#f59e0b" if monthly_margin >= 40 else "#ef4444"
    )

    # custos por categoria
    cats: dict = {}
    for c in monthly_costs:
        cat = c.get("category", "Outros")
        cats[cat] = cats.get(cat, 0) + c.get("cost", 0)
    cats = dict(sorted(cats.items(), key=lambda x: -x[1]))
    cat_bars = ""
    for cat, val in cats.items():
        pct = round(val / monthly_cost * 100) if monthly_cost > 0 else 0
        cat_bars += f"""
        <div style="display:flex;align-items:center;gap:8px;margin:4px 0;font-size:0.82rem">
          <div style="width:110px;color:#a0aec0;flex-shrink:0">{cat}</div>
          <div style="flex:1;background:#1e2a3a;border-radius:4px;height:8px">
            <div style="width:{pct}%;background:#3b82f6;border-radius:4px;height:8px"></div>
          </div>
          <div style="width:80px;text-align:right;color:#e2e8f0">R${val:,.0f}</div>
          <div style="width:36px;text-align:right;color:#7a90a8">{pct}%</div>
        </div>"""

    # produtos ranking
    products_sorted = sorted(products, key=lambda x: -x.get("margin_pct", 0))
    prod_rows = ""
    for p in products_sorted[:6]:
        mg = p.get("margin_pct", 0)
        pc = "#10b981" if mg >= 70 else "#f59e0b" if mg >= 40 else "#ef4444"
        prod_rows += f"""
        <tr>
          <td style="padding:8px 12px;color:#e2e8f0">{p.get('idea_title','')[:35]}</td>
          <td style="padding:8px 12px;text-align:right;color:#7a90a8">R${p.get('selling_price',0):,.0f}</td>
          <td style="padding:8px 12px;text-align:right;color:#7a90a8">R${p.get('total_cost',0):,.0f}</td>
          <td style="padding:8px 12px;text-align:right;color:#e2e8f0">R${p.get('profit',0):,.0f}</td>
          <td style="padding:8px 12px;text-align:right;font-weight:700;color:{pc}">{mg:.1f}%</td>
        </tr>"""

    # meta progress bar
    meta_html = ""
    if meta > 0:
        meta_html = f"""
        <div style="margin-top:8px">
          <div style="display:flex;justify-content:space-between;font-size:0.8rem;color:#a0aec0;margin-bottom:4px">
            <span>R${monthly_revenue:,.0f} atual</span>
            <span>meta R${meta:,.0f}</span>
          </div>
          <div style="background:#1e2a3a;border-radius:6px;height:12px">
            <div style="width:{meta_pct}%;background:{mg_color};border-radius:6px;height:12px;transition:width .3s"></div>
          </div>
          <div style="display:flex;justify-content:space-between;font-size:0.78rem;margin-top:4px">
            <span style="color:{mg_color};font-weight:600">{meta_pct}% da meta</span>
            {f'<span style="color:#7a90a8">faltam R${faltam:,.0f}</span>' if faltam > 0 else '<span style="color:#10b981">✅ Meta atingida!</span>'}
          </div>
        </div>"""

    # plano 90 dias
    ca = analysis.get("claude_analysis", {})
    plano_html = ""
    for m in ca.get("plano_90_dias", [])[:3]:
        plano_html += f"""
        <div style="background:#1a2535;border:1px solid #2d3f55;border-radius:8px;padding:12px 16px">
          <div style="font-size:0.85rem;font-weight:600;color:#e2e8f0;margin-bottom:4px">
            Mês {m.get('mes','')} — {m.get('foco','')[:40]}
            <span style="float:right;color:#10b981">R${m.get('meta_receita',0):,.0f}</span>
          </div>
          {''.join(f"<div style='font-size:0.78rem;color:#a0aec0;margin:2px 0'>→ {a[:70]}</div>" for a in m.get('acoes',[])[:3])}
        </div>"""

    # decisões automáticas
    decisions = analysis.get("decisions", [])
    DCOLOR = {"maxima": "#ef4444", "alta": "#f59e0b", "escala": "#10b981", "media": "#6366f1"}
    DICON = {"maxima": "🚨", "alta": "⚠️", "escala": "🚀", "media": "ℹ️"}
    dec_html = ""
    for d in decisions:
        dc = DCOLOR.get(d.get("priority", "media"), "#888")
        dec_html += f"""
        <div style="display:flex;align-items:flex-start;gap:10px;padding:10px 14px;background:{dc}10;border:1px solid {dc}33;border-radius:8px;margin:6px 0">
          <span style="font-size:1.1rem">{DICON.get(d.get('priority','media'),'')}</span>
          <div>
            <div style="font-size:0.78rem;color:#7a90a8;margin-bottom:2px">[{d.get('trigger','')}]</div>
            <div style="font-size:0.85rem;color:#e2e8f0">{d.get('action','')}</div>
          </div>
        </div>"""

    return f"""
<!-- FINANCIAL ENGINE -->
<div class="sec-title" style="margin-top:32px">Financial Engine — Receita · Custos · Margem · Projeção</div>

<!-- KPI row financeiro -->
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin:16px 0">
  <div style="background:#10b98115;border:1px solid #10b98133;border-radius:10px;padding:16px 20px">
    <div style="font-size:0.75rem;color:#7a90a8;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Receita / Dia</div>
    <div style="font-size:1.6rem;font-weight:800;color:#10b981">R${daily_revenue:,.0f}</div>
    <div style="font-size:0.75rem;color:#7a90a8;margin-top:4px">R${monthly_revenue:,.0f}/mês</div>
  </div>
  <div style="background:#3b82f615;border:1px solid #3b82f633;border-radius:10px;padding:16px 20px">
    <div style="font-size:0.75rem;color:#7a90a8;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Custo Mensal</div>
    <div style="font-size:1.6rem;font-weight:800;color:#3b82f6">R${monthly_cost:,.0f}</div>
    <div style="font-size:0.75rem;color:#7a90a8;margin-top:4px">{len(monthly_costs)} itens de custo</div>
  </div>
  <div style="background:{mg_color}15;border:1px solid {mg_color}33;border-radius:10px;padding:16px 20px">
    <div style="font-size:0.75rem;color:#7a90a8;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Margem</div>
    <div style="font-size:1.6rem;font-weight:800;color:{mg_color}">{monthly_margin:.1f}%</div>
    <div style="font-size:0.75rem;color:#7a90a8;margin-top:4px">R${monthly_profit:,.0f} lucro/mês</div>
  </div>
  <div style="background:#8b5cf615;border:1px solid #8b5cf633;border-radius:10px;padding:16px 20px">
    <div style="font-size:0.75rem;color:#7a90a8;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Projeção</div>
    <div style="font-size:1.6rem;font-weight:800;color:#8b5cf6">R${ca.get('projecao_otimista_mensal', monthly_revenue):,.0f}</div>
    <div style="font-size:0.75rem;color:#7a90a8;margin-top:4px">otimista/mês</div>
  </div>
</div>

{meta_html}

<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:20px">

  <!-- custos por categoria -->
  <div style="background:#131e2e;border:1px solid #1e2d45;border-radius:10px;padding:20px">
    <div style="font-size:0.85rem;font-weight:600;color:#e2e8f0;margin-bottom:12px">🧾 Custos por Categoria — R${monthly_cost:,.0f}/mês</div>
    {cat_bars if cat_bars else '<div style="color:#7a90a8;font-size:0.82rem">Use --monthly-costs para registrar custos</div>'}
  </div>

  <!-- produtos por margem -->
  <div style="background:#131e2e;border:1px solid #1e2d45;border-radius:10px;padding:20px;overflow:auto">
    <div style="font-size:0.85rem;font-weight:600;color:#e2e8f0;margin-bottom:12px">🏗️ Produtos — ranking por Margem</div>
    {f'<table style="width:100%;border-collapse:collapse;font-size:0.82rem"><thead><tr style="border-bottom:1px solid #1e2d45"><th style="padding:6px 12px;text-align:left;color:#7a90a8">Produto</th><th style="padding:6px 12px;text-align:right;color:#7a90a8">Preço</th><th style="padding:6px 12px;text-align:right;color:#7a90a8">Custo</th><th style="padding:6px 12px;text-align:right;color:#7a90a8">Lucro</th><th style="padding:6px 12px;text-align:right;color:#7a90a8">Margem</th></tr></thead><tbody>{prod_rows}</tbody></table>' if prod_rows else '<div style="color:#7a90a8;font-size:0.82rem">Use --product para cadastrar produtos</div>'}
  </div>

</div>

{f'<div style="margin-top:20px"><div style="font-size:0.85rem;font-weight:600;color:#e2e8f0;margin-bottom:12px">🤖 Decisões Automáticas</div>{dec_html}</div>' if dec_html else ""}

{f'<div style="margin-top:20px"><div style="font-size:0.85rem;font-weight:600;color:#e2e8f0;margin-bottom:12px">📅 Plano 90 Dias</div><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px">{plano_html}</div></div>' if plano_html else ""}

{f'<div style="margin-top:16px;padding:14px 18px;background:#1a2535;border:1px solid #2d3f55;border-radius:8px;font-size:0.85rem"><strong style="color:#e2e8f0">🧠 Diagnóstico Claude:</strong> <span style="color:#a0aec0">{ca.get("diagnostico","")}</span></div>' if ca.get("diagnostico") else ""}
"""


def render_ads_section(ads):
    if not ads:
        return ""

    STATUS_COLOR = {
        "escalar": "#10b981",
        "otimizar": "#f59e0b",
        "pausar": "#ef4444",
        "aguardando_dados": "#6366f1",
    }
    STATUS_ICON = {
        "escalar": "🚀",
        "otimizar": "🔧",
        "pausar": "⏸️",
        "aguardando_dados": "⏳",
    }
    FASE_LABEL = {"teste": "Teste", "escala": "Escala", "agressivo": "Agressivo"}

    with_data = [c for c in ads if c.get("cost", 0) > 0]
    waiting = [c for c in ads if c.get("cost", 0) == 0]
    n_escalar = sum(1 for c in with_data if c.get("optimization_status") == "escalar")
    n_otimizar = sum(1 for c in with_data if c.get("optimization_status") == "otimizar")
    n_pausar = sum(1 for c in with_data if c.get("optimization_status") == "pausar")
    total_spend = sum(c.get("cost", 0) for c in with_data)
    total_revenue = sum(c.get("revenue", 0) for c in with_data)
    global_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0.0
    roas_color = "#10b981" if global_roas >= 2 else "#f59e0b" if global_roas >= 1 else "#ef4444"

    cards = ""
    for c in ads[:12]:
        status = c.get("optimization_status", "aguardando_dados")
        scolor = STATUS_COLOR.get(status, "#888")
        roas = c.get("roas", 0.0)
        rc = (
            "#10b981"
            if roas >= 2
            else "#f59e0b"
            if roas >= 1
            else ("#ef4444" if roas > 0 else "#6366f1")
        )
        ins = c.get("optimization_insights", {})
        insight_html = ""
        if ins.get("insight"):
            insight_html = f'<div style="font-size:0.82rem;color:#e2e8f0;margin:6px 0"><em>{ins["insight"][:100]}</em></div>'
        actions_html = ""
        for a in ins.get("acoes_imediatas", [])[:3]:
            actions_html += (
                f'<div style="font-size:0.78rem;color:#a0aec0;margin:2px 0">→ {str(a)[:70]}</div>'
            )

        cards += f"""
        <div class="bp-card" style="border-left:4px solid {scolor}">
          <div class="bp-header">
            <span class="sbadge" style="background:{scolor}20;color:{scolor};border:1px solid {scolor}33">
              {STATUS_ICON.get(status,'')} {status.replace('_',' ').upper()}
            </span>
            <span style="margin-left:8px;font-size:0.78rem;color:#7a90a8">{c.get('campaign_id','')}</span>
            <span style="margin-left:auto;font-size:0.82rem;color:#7a90a8">{FASE_LABEL.get(c.get('fase','teste'),c.get('fase',''))}</span>
          </div>
          <div class="bp-title">{c.get('idea_title','')[:55]}</div>
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:10px 0;font-size:0.78rem">
            <div style="text-align:center"><div style="color:#7a90a8">ROAS</div><div style="font-weight:700;color:{rc}">{roas:.2f}x</div></div>
            <div style="text-align:center"><div style="color:#7a90a8">Clicks</div><div style="font-weight:600">{c.get('clicks',0)}</div></div>
            <div style="text-align:center"><div style="color:#7a90a8">Leads</div><div style="font-weight:600">{c.get('leads',0)}</div></div>
            <div style="text-align:center"><div style="color:#7a90a8">Spend</div><div style="font-weight:600">R${c.get('cost',0):.0f}</div></div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:8px;font-size:0.78rem">
            <div style="text-align:center"><div style="color:#7a90a8">CPC</div><div>R${c.get('cpc',0):.2f}</div></div>
            <div style="text-align:center"><div style="color:#7a90a8">CPL</div><div>R${c.get('cpl',0):.2f}</div></div>
            <div style="text-align:center"><div style="color:#7a90a8">Anúncios</div><div>{c.get('total_ads',0)}</div></div>
          </div>
          {insight_html}
          {f'<div style="font-size:0.8rem;margin-top:4px">{actions_html}</div>' if actions_html else ""}
          <div class="bp-meta">{c.get('timestamp','')[:15]}</div>
        </div>"""

    waiting_html = ""
    for c in waiting[:6]:
        waiting_html += f"""
        <div style="background:#1e2a3a;border:1px dashed #2d3f55;border-radius:8px;padding:12px 16px;font-size:0.82rem">
          <span style="color:#6366f1">⏳</span>
          <strong style="color:#e2e8f0;margin-left:8px">{c.get('campaign_id','')}</strong>
          <span style="color:#7a90a8;margin-left:8px">{c.get('idea_title','')[:45]}</span>
          <span style="color:#7a90a8;margin-left:auto;float:right">{c.get('total_ads',0)} anúncios · aguardando dados</span>
        </div>"""

    return f"""
<!-- ADS ENGINE -->
<div class="sec-title" style="margin-top:32px">Ads Engine — Tráfego Pago</div>
<div style="display:flex;gap:12px;margin:12px 0;flex-wrap:wrap">
  <div style="background:#10b98115;border:1px solid #10b98133;border-radius:8px;padding:10px 20px;text-align:center">
    <div style="font-size:1.5rem;font-weight:700;color:#10b981">{n_escalar}</div>
    <div style="font-size:0.78rem;color:#7a90a8">🚀 Escalando</div>
  </div>
  <div style="background:#f59e0b15;border:1px solid #f59e0b33;border-radius:8px;padding:10px 20px;text-align:center">
    <div style="font-size:1.5rem;font-weight:700;color:#f59e0b">{n_otimizar}</div>
    <div style="font-size:0.78rem;color:#7a90a8">🔧 Otimizando</div>
  </div>
  <div style="background:#ef444415;border:1px solid #ef444433;border-radius:8px;padding:10px 20px;text-align:center">
    <div style="font-size:1.5rem;font-weight:700;color:#ef4444">{n_pausar}</div>
    <div style="font-size:0.78rem;color:#7a90a8">⏸️ Pausado</div>
  </div>
  <div style="background:#6366f115;border:1px solid #6366f133;border-radius:8px;padding:10px 20px;text-align:center">
    <div style="font-size:1.5rem;font-weight:700;color:#6366f1">{len(waiting)}</div>
    <div style="font-size:0.78rem;color:#7a90a8">⏳ Aguardando</div>
  </div>
  <div style="background:{roas_color}15;border:1px solid {roas_color}33;border-radius:8px;padding:10px 20px;text-align:center;margin-left:auto">
    <div style="font-size:1.5rem;font-weight:700;color:{roas_color}">{global_roas:.2f}x</div>
    <div style="font-size:0.78rem;color:#7a90a8">ROAS Global · R${total_spend:,.0f} spend</div>
  </div>
</div>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-top:8px">
  {cards if cards else '<div style="color:#7a90a8;padding:16px">Nenhuma campanha com dados ainda. Rode: python ads_engine.py --json \'{{...}}\'</div>'}
</div>
{f'<div style="margin-top:12px;display:grid;gap:8px">{waiting_html}</div>' if waiting_html else ""}"""


def load_security_data() -> dict:
    """Coleta dados da Security Layer sem precisar de banco."""
    data = {
        "available": _SECURITY_AVAILABLE,
        "agents": {},
        "limits": {},
        "recent_blocks": [],
    }
    if not _SECURITY_AVAILABLE:
        return data

    data["limits"] = {
        "max_turns": MAX_TURNS,
        "daily_cost_usd": DAILY_COST_LIMIT_USD,
        "critical_cost_usd": CRITICAL_COST_LIMIT_USD,
    }

    for agent, cfg in AGENT_PERMISSIONS.items():
        data["agents"][agent] = {
            "actions": cfg.get("actions", []),
            "blocked_actions": cfg.get("blocked_actions", []),
            "limits": cfg.get("limits", {}),
        }

    # Lê bloqueios recentes de outputs/security_events.jsonl (se existir)
    events_path = os.path.join(OUTPUTS_DIR, "security_events.jsonl")
    if os.path.exists(events_path):
        with open(events_path, encoding="utf-8") as f:
            lines = f.readlines()[-20:]  # últimas 20
        for line in reversed(lines):
            try:
                data["recent_blocks"].append(json.loads(line.strip()))
            except Exception:
                pass

    return data


def render_security_section(sec: dict) -> str:
    if not sec.get("available"):
        return """
<div class="sec">Execution Control</div>
<div style="color:var(--muted);font-size:12px;padding:16px 0">
  Security layer não carregada — instale <code>psycopg2-binary</code> e verifique o <code>security_layer.py</code>.
</div>"""

    limits = sec.get("limits", {})
    agents = sec.get("agents", {})
    blocks = sec.get("recent_blocks", [])

    # ── KPI cards ────────────────────────────────────────────
    kpis = f"""
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px">
  <div style="background:var(--c1);border:1px solid var(--border);border-radius:var(--r);padding:16px">
    <div style="font-size:9px;color:var(--muted2);text-transform:uppercase;letter-spacing:1px">Agentes ativos</div>
    <div style="font-size:28px;font-weight:800;color:var(--cyan);margin-top:4px">{len(agents)}</div>
    <div style="font-size:10px;color:var(--muted)">com RBAC configurado</div>
  </div>
  <div style="background:var(--c1);border:1px solid var(--border);border-radius:var(--r);padding:16px">
    <div style="font-size:9px;color:var(--muted2);text-transform:uppercase;letter-spacing:1px">Max turns/sessão</div>
    <div style="font-size:28px;font-weight:800;color:var(--amber);margin-top:4px">{limits.get('max_turns', 5)}</div>
    <div style="font-size:10px;color:var(--muted)">contexto resetado após</div>
  </div>
  <div style="background:var(--c1);border:1px solid var(--border);border-radius:var(--r);padding:16px">
    <div style="font-size:9px;color:var(--muted2);text-transform:uppercase;letter-spacing:1px">Limite diário</div>
    <div style="font-size:28px;font-weight:800;color:var(--neon);margin-top:4px">${limits.get('daily_cost_usd', 10)}</div>
    <div style="font-size:10px;color:var(--muted)">shutdown non-critical</div>
  </div>
  <div style="background:var(--c1);border:1px solid var(--border);border-radius:var(--r);padding:16px">
    <div style="font-size:9px;color:var(--muted2);text-transform:uppercase;letter-spacing:1px">Limite crítico</div>
    <div style="font-size:28px;font-weight:800;color:var(--red);margin-top:4px">${limits.get('critical_cost_usd', 25)}</div>
    <div style="font-size:10px;color:var(--muted)">emergency stop</div>
  </div>
</div>"""

    # ── RBAC table ────────────────────────────────────────────
    rows = ""
    for agent, cfg in agents.items():
        actions_html = " ".join(
            f'<span style="background:var(--cyan)18;color:var(--cyan);font-size:9px;padding:2px 7px;border-radius:10px">{a}</span>'
            for a in cfg["actions"]
        )
        blocked_html = " ".join(
            f'<span style="background:var(--red)18;color:var(--red);font-size:9px;padding:2px 7px;border-radius:10px">{a}</span>'
            for a in cfg["blocked_actions"]
        )
        limit_str = ", ".join(f"{k}: {v}" for k, v in cfg["limits"].items()) or "—"
        rows += f"""
<tr style="border-bottom:1px solid var(--border)">
  <td style="padding:10px 12px;font-weight:600;color:var(--muted3);white-space:nowrap">{agent}</td>
  <td style="padding:10px 12px">{actions_html}</td>
  <td style="padding:10px 12px">{blocked_html}</td>
  <td style="padding:10px 12px;font-size:10px;color:var(--muted2)">{limit_str}</td>
</tr>"""

    rbac_table = f"""
<div style="background:var(--c1);border:1px solid var(--border);border-radius:var(--r);overflow:hidden;margin-bottom:20px">
  <div style="padding:14px 16px;border-bottom:1px solid var(--border);font-size:11px;font-weight:700;color:var(--muted2);text-transform:uppercase;letter-spacing:1px">
    RBAC — Permissões por Agente
  </div>
  <div style="overflow-x:auto">
  <table style="width:100%;border-collapse:collapse;font-size:11px">
    <tr style="border-bottom:1px solid var(--border);background:var(--sb)">
      <th style="padding:8px 12px;text-align:left;color:var(--muted);font-weight:600">Agente</th>
      <th style="padding:8px 12px;text-align:left;color:var(--muted);font-weight:600">Ações permitidas</th>
      <th style="padding:8px 12px;text-align:left;color:var(--muted);font-weight:600">Bloqueadas</th>
      <th style="padding:8px 12px;text-align:left;color:var(--muted);font-weight:600">Rate limits</th>
    </tr>
    {rows}
  </table>
  </div>
</div>"""

    # ── Blocos de defesa ──────────────────────────────────────
    defenses = [
        ("RBAC", "Permissões por agente verificadas antes de toda execução", "var(--cyan)"),
        ("Gatekeeper", "DLP + prompt injection detectados em input e output", "var(--pink)"),
        (
            "MAX_TURNS",
            f"Contexto isolado por sessão — reset após {limits.get('max_turns',5)} turns",
            "var(--amber)",
        ),
        (
            "Cost Control",
            f"Shutdown em ${limits.get('daily_cost_usd',10)} · Emergency em ${limits.get('critical_cost_usd',25)}/dia",
            "var(--neon)",
        ),
        ("Audit Log", "Hash chain SHA-256 append-only — rastreabilidade LGPD", "var(--purple)"),
    ]
    defense_cards = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:20px">'
    for name, desc, color in defenses:
        defense_cards += f"""
<div style="background:var(--c1);border:1px solid {color}44;border-left:3px solid {color};border-radius:var(--r);padding:14px">
  <div style="font-size:11px;font-weight:700;color:{color};margin-bottom:4px">{name}</div>
  <div style="font-size:10px;color:var(--muted2)">{desc}</div>
</div>"""
    defense_cards += "</div>"

    # ── Eventos recentes (se houver) ──────────────────────────
    events_html = ""
    if blocks:
        ev_rows = ""
        for ev in blocks[:10]:
            decision_color = {
                "BLOCK": "var(--red)",
                "HUMAN": "var(--amber)",
                "ALLOW": "var(--neon)",
            }.get(ev.get("decision", ""), "var(--muted)")
            ev_rows += f"""
<tr style="border-bottom:1px solid var(--border)">
  <td style="padding:8px 12px;font-size:10px;color:var(--muted)">{ev.get('ts','')}</td>
  <td style="padding:8px 12px;font-size:11px;color:var(--muted3)">{ev.get('agent','')}</td>
  <td style="padding:8px 12px;font-size:11px;color:var(--muted3)">{ev.get('action','')}</td>
  <td style="padding:8px 12px"><span style="color:{decision_color};font-weight:700;font-size:10px">{ev.get('decision','')}</span></td>
  <td style="padding:8px 12px;font-size:10px;color:var(--muted2)">{str(ev.get('reason',''))[:60]}</td>
</tr>"""
        events_html = f"""
<div style="background:var(--c1);border:1px solid var(--border);border-radius:var(--r);overflow:hidden">
  <div style="padding:14px 16px;border-bottom:1px solid var(--border);font-size:11px;font-weight:700;color:var(--muted2);text-transform:uppercase;letter-spacing:1px">
    Eventos Recentes do Gatekeeper
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:11px">
    <tr style="background:var(--sb);border-bottom:1px solid var(--border)">
      <th style="padding:8px 12px;text-align:left;color:var(--muted)">Timestamp</th>
      <th style="padding:8px 12px;text-align:left;color:var(--muted)">Agente</th>
      <th style="padding:8px 12px;text-align:left;color:var(--muted)">Ação</th>
      <th style="padding:8px 12px;text-align:left;color:var(--muted)">Decisão</th>
      <th style="padding:8px 12px;text-align:left;color:var(--muted)">Motivo</th>
    </tr>
    {ev_rows}
  </table>
</div>"""
    else:
        events_html = '<div style="font-size:11px;color:var(--muted);padding:12px 0">Nenhum evento registrado — o audit log requer DATABASE_URL configurada.</div>'

    return f"""
<div class="sec">Execution Control</div>
{kpis}
{defense_cards}
{rbac_table}
{events_html}"""


def generate(
    scorings,
    others,
    blueprints=None,
    contents=None,
    videos=None,
    funnels=None,
    performances=None,
    memory_items=None,
    validations=None,
    crm_leads=None,
    scaling=None,
    sessions=None,
    ads=None,
    financial=None,
    simulations=None,
    security=None,
):
    blueprints = blueprints or []
    contents = contents or []
    videos = videos or []
    funnels = funnels or []
    performances = performances or []
    memory_items = memory_items or []
    validations = validations or []
    crm_leads = crm_leads or []
    scaling = scaling or []
    sessions = sessions or []
    ads = ads or []
    financial = financial or {}
    simulations = simulations or []
    security = security or {}
    n_content = len(contents)
    n_videos = len(videos)
    n_funnels = len(funnels)
    n_perf = len(performances)
    n_valid = len(validations)
    n_leads = len(crm_leads)
    n_scaling = len(scaling)
    n_sessions = len(sessions)
    n_quentes = sum(1 for l in crm_leads if l.get("temperature") == "quente")
    n_clientes = sum(1 for l in crm_leads if l.get("pipeline_stage") == "cliente")
    n_escalando = sum(1 for s in scaling if s.get("final_action") == "escalar")
    n_completed = sum(1 for s in sessions if s.get("status") == "completed")
    n_ads = len(ads)
    ads_with_data = [c for c in ads if c.get("cost", 0) > 0]
    ads_spend = sum(c.get("cost", 0) for c in ads_with_data)
    ads_revenue = sum(c.get("revenue", 0) for c in ads_with_data)
    ads_roas = round(ads_revenue / ads_spend, 2) if ads_spend > 0 else 0.0
    ads_roas_color = "#10b981" if ads_roas >= 2 else "#f59e0b" if ads_roas >= 1 else "#ef4444"
    # financial
    fin_projs = financial.get("projections", [])
    fin_latest = fin_projs[-1] if fin_projs else {}
    fin_revenue = fin_latest.get("monthly_revenue", 0)
    fin_profit = fin_latest.get("monthly_profit", 0)
    fin_margin_pct = fin_latest.get("monthly_margin_pct", 0)
    fin_margin_color = (
        "#10b981" if fin_margin_pct >= 70 else "#f59e0b" if fin_margin_pct >= 40 else "#ef4444"
    )
    # simulator
    n_sims = len(simulations)
    sim_latest = simulations[-1] if simulations else {}
    sim_base = sim_latest.get("scenarios", {}).get("base", {})
    sim_best_rev = (
        max(
            (s.get("revenue_month", 0) for s in sim_latest.get("scenarios", {}).values()), default=0
        )
        if sim_latest
        else 0
    )
    sim_best_pct = (
        round(
            (sim_best_rev - sim_base.get("revenue_month", 0))
            / sim_base.get("revenue_month", 1)
            * 100
        )
        if sim_base.get("revenue_month")
        else 0
    )
    total = len(scorings)
    n_max = sum(1 for s in scorings if s.get("priority") == "maxima")
    n_alta = sum(1 for s in scorings if s.get("priority") == "alta")
    n_media = sum(1 for s in scorings if s.get("priority") == "media")
    n_baixa = sum(1 for s in scorings if s.get("priority") == "baixa")
    avg = round(sum(s.get("final_score", 0) for s in scorings) / total) if total else 0
    best = scorings[0] if scorings else None
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    n_bp = len(blueprints)

    # ── chart data ──────────────────────────────────────────────────────────
    bar_labels = json.dumps([s.get("idea_title", "")[:28] for s in scorings])
    bar_scores = json.dumps([s.get("final_score", 0) for s in scorings])
    bar_colors = json.dumps(
        [PRIORITY_COLOR.get(s.get("priority", "baixa"), "#888") for s in scorings]
    )

    donut_data = json.dumps([n_max, n_alta, n_media, n_baixa])
    donut_colors = json.dumps(["#10b981", "#3b82f6", "#f59e0b", "#ef4444"])
    donut_labels = json.dumps(["Máxima", "Alta", "Média", "Baixa"])

    # radar per scoring (first 4)
    radar_datasets = []
    radar_colors_list = ["#10b981", "#3b82f6", "#f59e0b", "#ec4899"]
    for i, s in enumerate(scorings[:4]):
        sc = s.get("raw_scoring", {}).get("scores", {})
        vals = [sc.get(k, {}).get("score", 0) for k in CRITERIA_LABELS]
        color = radar_colors_list[i % len(radar_colors_list)]
        radar_datasets.append(
            {
                "label": s.get("idea_title", "")[:22],
                "data": vals,
                "borderColor": color,
                "backgroundColor": color + "22",
                "borderWidth": 2,
                "pointBackgroundColor": color,
            }
        )
    radar_labels = json.dumps(list(CRITERIA_LABELS.values()))
    radar_datasets_json = json.dumps(radar_datasets)

    # timeline
    ts_sorted = sorted(scorings, key=lambda x: x.get("ts", ""))
    tl_labels = json.dumps([fmt_ts(s.get("ts", "")) for s in ts_sorted])
    tl_scores = json.dumps([s.get("final_score", 0) for s in ts_sorted])

    # criteria averages
    crit_avgs = {}
    for k in CRITERIA_LABELS:
        vals = [
            s.get("raw_scoring", {}).get("scores", {}).get(k, {}).get("score", 0)
            for s in scorings
            if s.get("raw_scoring", {}).get("scores", {}).get(k)
        ]
        crit_avgs[k] = round(sum(vals) / len(vals), 1) if vals else 0

    crit_avg_labels = json.dumps(list(CRITERIA_LABELS.values()))
    crit_avg_values = json.dumps(list(crit_avgs.values()))

    # ── priority queue ───────────────────────────────────────────────────────
    queue_html = ""
    for i, s in enumerate(scorings[:6]):
        pc = PRIORITY_COLOR.get(s.get("priority", "baixa"), "#888")
        pb = PRIORITY_BG.get(s.get("priority", "baixa"), "#88811")
        sc = s.get("final_score", 0)
        queue_html += f"""
        <div class="queue-item" style="border-left:3px solid {pc};background:{pb}">
          <div class="queue-rank">#{i+1}</div>
          <div class="queue-info">
            <div class="queue-title">{s.get("idea_title","")}</div>
            <div class="queue-meta">
              <span style="color:{pc}">{PRIORITY_LABEL.get(s.get("priority",""),"")}</span>
              <span class="dot">·</span>
              <span>{s.get("initial_format","")}</span>
            </div>
            <div class="queue-step">→ {s.get("next_step","")[:80]}</div>
          </div>
          <div class="queue-score" style="color:{pc}">{sc}</div>
        </div>"""

    # ── heatmap table ────────────────────────────────────────────────────────
    heatmap_html = "<tr><th>Oportunidade</th>"
    for lbl in CRITERIA_LABELS.values():
        heatmap_html += f"<th>{lbl}</th>"
    heatmap_html += "<th>Score</th></tr>"

    for s in scorings:
        sc = s.get("raw_scoring", {}).get("scores", {})
        final = s.get("final_score", 0)
        pc = PRIORITY_COLOR.get(s.get("priority", "baixa"), "#888")
        heatmap_html += f"<tr><td class='ht-title'>{s.get('idea_title','')[:28]}</td>"
        for k in CRITERIA_LABELS:
            v = sc.get(k, {}).get("score", 0)
            if v >= 4:
                bg, fg = "#10b98120", "#10b981"
            elif v >= 3:
                bg, fg = "#3b82f620", "#3b82f6"
            elif v >= 2:
                bg, fg = "#f59e0b20", "#f59e0b"
            else:
                bg, fg = "#ef444420", "#ef4444"
            heatmap_html += f"<td style='background:{bg};color:{fg};font-weight:700'>{v}</td>"
        heatmap_html += f"<td style='color:{pc};font-weight:800'>{final}</td></tr>"

    # ── scoring cards ────────────────────────────────────────────────────────
    cards_html = ""
    for idx, s in enumerate(scorings):
        pc = PRIORITY_COLOR.get(s.get("priority", "baixa"), "#888")
        pb = PRIORITY_BG.get(s.get("priority", "baixa"), "#11")
        rc = REC_COLOR.get(s.get("recommendation", ""), "#888")
        sc = s.get("final_score", 0)
        raw = s.get("raw_scoring", {})
        scores_detail = raw.get("scores", {})
        opp = s.get("opportunity", {})
        risks = s.get("main_risks", [])

        # mini bar per criterion
        crit_rows = ""
        for k, lbl in CRITERIA_LABELS.items():
            info = scores_detail.get(k, {})
            v = info.get("score", 0)
            just = info.get("justificativa", "")
            w = WEIGHTS.get(k, 0)
            pct = v / 5 * 100
            if pct >= 80:
                bc = "#10b981"
            elif pct >= 60:
                bc = "#3b82f6"
            elif pct >= 40:
                bc = "#f59e0b"
            else:
                bc = "#ef4444"
            contrib = round((v / 5) * w)
            crit_rows += f"""
              <div class="crit-row">
                <div class="crit-name">{lbl}<span class="crit-w">w{w}</span></div>
                <div class="crit-bar-wrap">
                  <div class="crit-bar" style="width:{pct:.0f}%;background:{bc}"></div>
                </div>
                <div class="crit-score" style="color:{bc}">{v}/5</div>
                <div class="crit-pts">+{contrib}pts</div>
                <div class="crit-just">{just}</div>
              </div>"""

        risks_html = "".join(f'<div class="risk-item">⚠ {r}</div>' for r in risks)

        cards_html += f"""
        <div class="scard" id="scard-{idx}" data-priority="{s.get('priority','baixa')}">
          <div class="scard-header" onclick="toggle({idx})">
            <div class="scard-score-col" style="background:{pb};border-right:1px solid {pc}33">
              <div class="big-score" style="color:{pc}">{sc}</div>
              <div class="big-sub">/ 100</div>
              <div class="scard-prio-badge" style="background:{pc}22;color:{pc}">{PRIORITY_LABEL.get(s.get('priority',''),'')}</div>
            </div>
            <div class="scard-main">
              <div class="scard-title">{s.get('idea_title','')}</div>
              <div class="scard-badges">
                <span class="sbadge" style="background:{rc}22;color:{rc};border:1px solid {rc}44">{s.get('recommendation','').upper()}</span>
                <span class="sbadge grey">{s.get('initial_format','')}</span>
                {'<span class="sbadge grey">' + fmt_ts(s.get('ts','')) + '</span>' if s.get('ts') else ''}
              </div>
              <div class="scard-next">→ {s.get('next_step','')}</div>
            </div>
            <div class="scard-chev" id="chev-{idx}">›</div>
          </div>
          <div class="scard-body" id="sbody-{idx}">
            <div class="scard-grid">
              {''.join([f'<div class="scard-info"><div class="si-label">{l}</div><div class="si-val">{v2}</div></div>' for l, v2 in [("Descrição", opp.get("idea_description","")), ("Público-alvo", opp.get("target_audience","")), ("Contexto", opp.get("market_context",""))] if v2])}
            </div>
            <div class="scard-section">Critérios</div>
            <div class="crit-list">{crit_rows}</div>
            {'<div class="scard-section">Riscos</div><div class="risks-wrap">' + risks_html + '</div>' if risks else ''}
            <div class="next-box" style="border-color:{pc}44;background:{pb}">
              <div class="next-box-label" style="color:{pc}">Próximo passo</div>
              <div class="next-box-text">{s.get('next_step','')}</div>
            </div>
          </div>
        </div>"""

    # ── other outputs ────────────────────────────────────────────────────────
    others_html = ""
    for o in others:
        tc = TYPE_COLOR.get(o.get("task_type", ""), "#64748b")
        ti = TYPE_ICON.get(o.get("task_type", ""), "📋")
        others_html += f"""
        <div class="ocard">
          <div class="ocard-type" style="color:{tc};border-color:{tc}33">
            {ti} {o.get('task_type','').upper()}
          </div>
          <div class="ocard-input">{o.get('input','')}</div>
          <div class="ocard-output">{o.get('output','')}</div>
          {'<div class="ocard-date">' + fmt_ts(o.get('ts','')) + '</div>' if o.get('ts') else ''}
        </div>"""

    # ── extra chart data ─────────────────────────────────────────────────────
    # revenue/cost trend (financial projections)
    fin_projs_all = financial.get("projections", [])
    fin_tl_labels = json.dumps([p.get("timestamp", "")[:8] for p in fin_projs_all[-12:]])
    fin_tl_rev = json.dumps([p.get("monthly_revenue", 0) for p in fin_projs_all[-12:]])
    fin_tl_cost = json.dumps([p.get("monthly_cost", 0) for p in fin_projs_all[-12:]])
    fin_tl_profit = json.dumps([p.get("monthly_profit", 0) for p in fin_projs_all[-12:]])
    # cost breakdown donut
    fin_cats_all = {}
    for c in financial.get("monthly_costs", []):
        fin_cats_all[c.get("category", "Outros")] = fin_cats_all.get(
            c.get("category", "Outros"), 0
        ) + c.get("cost", 0)
    cost_cat_labels = json.dumps(list(fin_cats_all.keys()))
    cost_cat_values = json.dumps(list(fin_cats_all.values()))
    cost_cat_colors = json.dumps(
        ["#4f8ef7", "#00d4aa", "#f5a623", "#a855f7", "#f04040", "#06b6d4", "#ec4899"][
            : len(fin_cats_all)
        ]
    )
    # scenario comparison (latest simulation)
    sim_sc = simulations[-1].get("scenarios", {}) if simulations else {}
    SIM_LABELS_MAP = {
        "base": "Base",
        "dobrar_leads": "2× Leads",
        "melhorar_conversao": "Conv +50%",
        "aumentar_preco": "Preço +30%",
        "combo_leve": "Combo Leve",
        "combo_agressivo": "Combo Agress.",
    }
    sc_labels = json.dumps([SIM_LABELS_MAP.get(k, k) for k in sim_sc])
    sc_rev = json.dumps([v.get("revenue_month", 0) for v in sim_sc.values()])
    sc_profit = json.dumps([v.get("profit", 0) for v in sim_sc.values()])
    sc_colors = json.dumps(
        ["#4f8ef722", "#00d4aa22", "#4f8ef722", "#f5a62322", "#a855f722", "#f0404022"]
    )
    sc_border = json.dumps(["#4f8ef7", "#00d4aa", "#4f8ef7", "#f5a623", "#a855f7", "#f04040"])
    # CRM funnel
    crm_stages_count = {}
    for lead in crm_leads:
        st = lead.get("pipeline_stage", "entrada")
        crm_stages_count[st] = crm_stages_count.get(st, 0) + 1
    crm_funnel_order = [
        "entrada",
        "interessado",
        "qualificado",
        "proposta",
        "fechamento",
        "cliente",
    ]
    crm_funnel_vals = json.dumps([crm_stages_count.get(s, 0) for s in crm_funnel_order])
    crm_funnel_lbls = json.dumps(
        ["Entrada", "Interessado", "Qualificado", "Proposta", "Fechamento", "Cliente"]
    )

    # ── assemble HTML ─────────────────────────────────────────────────────────
    source_counts: dict = {}
    for _lead in crm_leads:
        _src = _lead.get("source", "Direto")
        source_counts[_src] = source_counts.get(_src, 0) + 1
    lead_source_labels = json.dumps(list(source_counts.keys()) or ["Sem dados"])
    lead_source_values = json.dumps(list(source_counts.values()) or [0])
    _temp_q = sum(1 for l in crm_leads if l.get("temperature") == "quente")
    _temp_m = sum(1 for l in crm_leads if l.get("temperature") == "morno")
    _temp_f = sum(1 for l in crm_leads if l.get("temperature") == "frio")
    temp_data = json.dumps([_temp_q, _temp_m, _temp_f])
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>MYO — Dashboard</title>
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#15043a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="MYO">
<link rel="apple-touch-icon" href="/icon-192.png">
<script src="/chart.umd.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:#15043a; --sb:#0e0228; --c1:#1f0a4e; --c2:#280d60; --c3:#331478;
  --border:#4a2095; --border2:#7040c8;
  --text:#f0e8ff; --muted:#8a6aaa; --muted2:#b89ed8; --muted3:#dcd0f5;
  --cyan:#00e5ff; --pink:#ff4db8; --neon:#39ff14; --amber:#ffb800;
  --purple:#c060ff; --blue:#5b9cff; --red:#ff4444; --teal:#00ffc8;
  --r:12px; --font:'Inter',system-ui,sans-serif;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
body{{background:radial-gradient(ellipse at 15% 40%,rgba(100,30,220,.25) 0%,var(--bg) 55%),var(--bg);color:var(--text);font-family:var(--font);min-height:100vh;font-size:13px;line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:hidden}}
::-webkit-scrollbar{{width:4px;height:4px}}
::-webkit-scrollbar-track{{background:var(--sb)}}
::-webkit-scrollbar-thumb{{background:var(--border2);border-radius:2px}}

/* ── LAYOUT ── */
.layout{{display:flex;min-height:100vh}}

/* ── SIDEBAR ── */
.sidebar{{
  width:220px;flex-shrink:0;background:linear-gradient(180deg,var(--sb),rgba(20,4,60,.95));
  border-right:1px solid var(--border);
  display:flex;flex-direction:column;
  position:sticky;top:0;height:100vh;overflow-y:auto;
  box-shadow:4px 0 30px rgba(0,0,0,.4);
}}
.sb-logo{{
  padding:24px 20px 20px;
  font-size:14px;font-weight:800;letter-spacing:-.3px;
  color:var(--cyan);display:flex;align-items:center;gap:8px;
  border-bottom:1px solid var(--border);
}}
.sb-dot{{width:7px;height:7px;border-radius:50%;background:var(--cyan);box-shadow:0 0 8px var(--cyan);animation:blink 2s ease-in-out infinite;flex-shrink:0}}
@keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:.25}}}}
.sb-sub{{font-size:9px;color:var(--muted2);font-weight:400;display:block;margin-top:2px;letter-spacing:0}}
.sb-section{{font-size:9px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:1.5px;padding:18px 20px 6px}}
.sb-link{{
  display:flex;align-items:center;gap:10px;
  padding:9px 20px;font-size:12px;font-weight:500;color:var(--muted2);
  text-decoration:none;transition:all .15s;border-left:2px solid transparent;
}}
.sb-link:hover,.sb-link.active{{color:var(--cyan);background:var(--cyan)08;border-left-color:var(--cyan)}}
.sb-link .ico{{font-size:14px;width:16px;flex-shrink:0;text-align:center}}
.sb-divider{{height:1px;background:var(--border);margin:8px 20px}}
.sb-footer{{margin-top:auto;padding:16px 20px;font-size:10px;color:var(--muted);border-top:1px solid var(--border)}}

/* ── CONTENT AREA ── */
.content{{flex:1;min-width:0;display:flex;flex-direction:column}}

/* ── TOPBAR ── */
.topbar{{
  height:52px;background:rgba(21,4,58,.92);backdrop-filter:blur(12px);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;padding:0 28px;gap:12px;
  position:sticky;top:0;z-index:100;
}}
.tb-path{{font-size:11px;color:var(--muted2);display:flex;align-items:center;gap:6px}}
.tb-path span{{color:var(--cyan)}}
.tb-spacer{{flex:1}}
.tb-date{{font-size:11px;color:var(--muted2)}}
.tb-live{{
  background:linear-gradient(135deg,var(--cyan)22,var(--pink)22);
  border:1px solid var(--cyan)44;color:var(--cyan);
  font-size:9px;font-weight:700;padding:3px 10px;border-radius:20px;letter-spacing:1px;
}}

/* ── MAIN ── */
.main{{padding:24px 28px 60px;flex:1}}

/* ── SECTION LABEL ── */
.sec{{
  font-size:9px;font-weight:700;color:var(--muted2);
  text-transform:uppercase;letter-spacing:2px;
  display:flex;align-items:center;gap:10px;margin:28px 0 14px;
}}
.sec::after{{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--border2),transparent)}}
.sec:first-child{{margin-top:0}}

/* ── KPI RINGS ── */
.rings-row{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:12px}}
.ring-card{{
  background:linear-gradient(145deg,var(--c1),var(--c2));border:1px solid var(--border);border-radius:var(--r);
  padding:20px 14px;display:flex;flex-direction:column;align-items:center;gap:10px;
  transition:border-color .2s,transform .15s,box-shadow .2s;position:relative;overflow:hidden;
  box-shadow:0 4px 30px rgba(0,0,0,.5),inset 0 1px 0 rgba(180,80,255,.12);
}}
.ring-card:hover{{border-color:var(--border2);transform:translateY(-2px);box-shadow:0 8px 40px rgba(0,0,0,.6),0 0 20px rgba(180,80,255,.15),inset 0 1px 0 rgba(180,80,255,.2)}}
.ring-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--accent,var(--cyan)),transparent)}}
.ring-wrap{{position:relative;width:80px;height:80px}}
.ring-svg{{width:80px;height:80px;transform:rotate(-90deg)}}
.ring-track{{fill:none;stroke:var(--c3);stroke-width:6;opacity:.6}}
.ring-fill{{fill:none;stroke-width:7;stroke-linecap:round;transition:stroke-dashoffset .6s ease}}
.ring-inner{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}}
.ring-val{{font-size:16px;font-weight:800;line-height:1}}
.ring-unit{{font-size:9px;color:var(--muted2);margin-top:1px}}
.ring-info{{text-align:center}}
.ring-label{{font-size:10px;font-weight:700;color:var(--muted3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px}}
.ring-sub{{font-size:10px;color:var(--muted);line-height:1.3}}

/* ── FLAT KPI CARDS ── */
.kpi-row{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:10px}}
.kpi{{
  background:linear-gradient(145deg,var(--c1),var(--c2));border:1px solid var(--border);border-radius:var(--r);
  padding:16px 14px;transition:border-color .15s,box-shadow .2s;position:relative;overflow:hidden;
  box-shadow:0 4px 20px rgba(0,0,0,.45),inset 0 1px 0 rgba(180,80,255,.1);
}}
.kpi:hover{{border-color:var(--border2);box-shadow:0 6px 28px rgba(0,0,0,.5),0 0 14px rgba(180,80,255,.12)}}
.kpi-label{{font-size:9px;color:var(--muted2);text-transform:uppercase;letter-spacing:.8px;margin-bottom:7px;font-weight:600}}
.kpi-val{{font-size:22px;font-weight:800;line-height:1;letter-spacing:-.5px}}
.kpi-sub{{font-size:10px;color:var(--muted);margin-top:4px}}
.kpi-glow{{position:absolute;bottom:-20px;right:-20px;width:60px;height:60px;border-radius:50%;filter:blur(20px);opacity:.3}}

/* ── CHART PANELS ── */
.cg-2-1{{display:grid;grid-template-columns:2fr 1fr;gap:12px;margin-bottom:12px}}
.cg-1-1{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}}
.cg-1-1-1{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px}}
.cg-3-2{{display:grid;grid-template-columns:3fr 2fr;gap:12px;margin-bottom:12px}}
.panel{{
  background:linear-gradient(145deg,var(--c1),var(--c2));border:1px solid var(--border);border-radius:var(--r);
  padding:18px 20px;position:relative;overflow:hidden;
  box-shadow:0 4px 24px rgba(0,0,0,.45),inset 0 1px 0 rgba(180,80,255,.1);
}}
.panel::before{{
  content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--accent,var(--cyan))60,transparent);
}}
.p-title{{
  font-size:11px;font-weight:600;color:var(--muted3);margin-bottom:14px;
  display:flex;align-items:center;gap:7px;
}}
.p-title .bar{{width:3px;height:11px;border-radius:1px;display:inline-block}}
canvas{{max-height:200px}}

/* ── BEST CARD ── */
.best{{
  background:linear-gradient(135deg,var(--c2),var(--c3));
  border:1px solid var(--cyan)45;border-radius:var(--r);
  padding:20px 24px;display:flex;align-items:center;gap:20px;margin-bottom:12px;
  position:relative;overflow:hidden;
  box-shadow:0 0 40px rgba(0,229,255,.08),0 4px 24px rgba(0,0,0,.5);
}}
.best::after{{content:'TOP PICK';position:absolute;top:14px;right:20px;font-size:8px;font-weight:800;color:var(--cyan);letter-spacing:2px;opacity:.6}}
.best::before{{content:'';position:absolute;top:-40px;right:-40px;width:120px;height:120px;border-radius:50%;background:var(--cyan);filter:blur(40px);opacity:.1}}
.score-ring{{width:76px;height:76px;flex-shrink:0;border-radius:50%;position:relative;display:flex;align-items:center;justify-content:center}}
.score-ring-svg{{position:absolute;inset:0;width:100%;height:100%;transform:rotate(-90deg)}}
.score-inner{{position:relative;z-index:1;text-align:center}}
.score-num{{font-size:20px;font-weight:900;color:var(--cyan)}}
.score-den{{font-size:9px;color:var(--muted2)}}
.best-info{{flex:1;min-width:0}}
.best-title{{font-size:17px;font-weight:700;margin-bottom:7px}}
.best-badges{{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:7px}}
.badge{{padding:2px 8px;border-radius:20px;font-size:9px;font-weight:700;letter-spacing:.3px;border:1px solid transparent}}
.badge-c{{background:var(--cyan)18;color:var(--cyan);border-color:var(--cyan)35}}
.badge-m{{background:var(--c3);color:var(--muted2);border-color:var(--border)}}
.best-next{{font-size:11px;color:var(--muted2)}}
.best-next strong{{color:var(--cyan)}}

/* ── QUEUE ── */
.queue{{display:flex;flex-direction:column;gap:5px}}
.qi{{display:flex;align-items:center;gap:10px;padding:10px 12px;background:var(--c2);border-radius:8px;border-left:3px solid var(--border2);transition:all .15s}}
.qi:hover{{background:var(--c3);border-left-color:var(--cyan)}}
.qi-rank{{font-size:12px;font-weight:800;color:var(--muted);width:20px;flex-shrink:0;text-align:center}}
.qi-info{{flex:1;min-width:0}}
.qi-title{{font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:2px}}
.qi-meta{{font-size:10px;color:var(--muted2)}}
.qi-step{{font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.qi-score{{font-size:20px;font-weight:900;flex-shrink:0;width:42px;text-align:right}}

/* ── FILTER BAR ── */
.fbar{{display:flex;gap:5px;margin-bottom:12px;flex-wrap:wrap}}
.fbtn{{background:var(--c2);border:1px solid var(--border);color:var(--muted2);padding:4px 12px;border-radius:20px;cursor:pointer;font-size:10px;font-weight:600;font-family:inherit;transition:all .12s;letter-spacing:.3px}}
.fbtn:hover,.fbtn.on{{border-color:var(--cyan);color:var(--cyan);background:var(--cyan)10}}

/* ── SCORING CARDS ── */
.scard{{background:linear-gradient(145deg,var(--c1),var(--c2));border:1px solid var(--border);border-radius:var(--r);margin-bottom:7px;overflow:hidden;transition:border-color .15s,box-shadow .15s;box-shadow:0 2px 12px rgba(0,0,0,.4)}}
.scard:hover{{border-color:var(--border2);box-shadow:0 4px 20px rgba(0,0,0,.5),0 0 12px rgba(112,64,200,.15)}}
.scard-header{{display:flex;align-items:stretch;cursor:pointer;min-height:70px}}
.scard-score-col{{width:80px;flex-shrink:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;padding:10px 6px}}
.big-score{{font-size:26px;font-weight:900;line-height:1}}
.big-sub{{font-size:9px;color:var(--muted)}}
.scard-prio-badge{{font-size:8px;font-weight:700;padding:1px 6px;border-radius:8px;text-align:center}}
.scard-main{{flex:1;padding:12px 14px;display:flex;flex-direction:column;justify-content:center;gap:5px;min-width:0}}
.scard-title{{font-size:13px;font-weight:600}}
.scard-badges{{display:flex;gap:4px;flex-wrap:wrap}}
.sbadge{{padding:2px 7px;border-radius:20px;font-size:9px;font-weight:600;letter-spacing:.3px}}
.sbadge.grey{{background:var(--c3);color:var(--muted2);border:1px solid var(--border)}}
.scard-next{{font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.scard-chev{{width:36px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:16px;color:var(--muted);transition:transform .2s}}
.scard-chev.open{{transform:rotate(90deg)}}
.scard-body{{border-top:1px solid var(--border);padding:18px;display:none}}
.scard-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:7px;margin-bottom:14px}}
.scard-info{{background:var(--c2);border-radius:6px;padding:9px 11px}}
.si-label{{font-size:8px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px;font-weight:700}}
.si-val{{font-size:11px;line-height:1.5}}
.scard-section{{font-size:9px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;margin:12px 0 7px}}
.crit-list{{display:flex;flex-direction:column;gap:4px}}
.crit-row{{display:grid;grid-template-columns:150px 1fr 46px 38px;align-items:center;gap:7px;padding:5px 8px;background:var(--c2);border-radius:6px}}
.crit-name{{font-size:10px;font-weight:500;display:flex;align-items:center;gap:4px}}
.crit-w{{font-size:8px;color:var(--muted);background:var(--c3);padding:1px 4px;border-radius:3px}}
.crit-bar-wrap{{background:var(--c3);border-radius:2px;height:4px;overflow:hidden}}
.crit-bar{{height:100%;border-radius:2px;transition:width .3s}}
.crit-score{{font-size:10px;font-weight:700;text-align:right}}
.crit-pts{{font-size:8px;color:var(--muted);text-align:right}}
.crit-just{{display:none}}
.risks-wrap{{display:flex;flex-direction:column;gap:4px;margin-bottom:10px}}
.risk-item{{font-size:10px;color:#fca5a5;padding:6px 9px;background:#ff444410;border:1px solid #ff444420;border-radius:5px}}
.next-box{{padding:10px 14px;border-radius:8px;border-width:1px;border-style:solid;margin-top:10px}}
.next-box-label{{font-size:8px;font-weight:800;text-transform:uppercase;letter-spacing:.8px;margin-bottom:3px}}
.next-box-text{{font-size:12px;font-weight:500}}
/* ── HEATMAP ── */
.hm-wrap{{background:var(--c1);border:1px solid var(--border);border-radius:var(--r);padding:18px;overflow-x:auto}}
.ht-table{{width:100%;border-collapse:collapse;font-size:10px;min-width:700px}}
.ht-table th{{padding:6px 8px;color:var(--muted2);font-weight:600;text-align:center;border-bottom:1px solid var(--border);font-size:9px}}
.ht-table th:first-child{{text-align:left}}
.ht-table td{{padding:7px 8px;text-align:center;border-bottom:1px solid var(--border)18}}
.ht-title{{text-align:left!important;font-weight:600;white-space:nowrap;color:var(--text)!important;background:transparent!important}}
.ht-table tr:hover td{{background:var(--c2)!important}}
/* ── BP CARDS ── */
.bpcard{{background:var(--c1);border:1px solid var(--border);border-radius:var(--r);margin-bottom:7px;overflow:hidden;transition:border-color .15s}}
.bpcard:hover{{border-color:var(--border2)}}
.bpcard-header{{display:flex;align-items:center;gap:10px;padding:12px 16px;cursor:pointer}}
.bpcard-icon{{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0}}
.bpcard-info{{flex:1;min-width:0}}
.bpcard-title{{font-size:13px;font-weight:600;margin-bottom:4px}}
.bpcard-sub{{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:4px}}
.bpcard-promise{{font-size:10px;color:var(--muted2);font-style:italic;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.bpcard-body{{border-top:1px solid var(--border);padding:18px;display:none}}
.bp-grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:14px}}
.bp-col{{display:flex;flex-direction:column;gap:9px}}
.bp-section{{font-size:9px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.8px}}
.bp-field{{background:var(--c2);border-radius:6px;padding:8px 10px}}
.bp-field span{{font-size:8px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:2px;font-weight:700}}
.bp-field p{{font-size:11px;line-height:1.5;margin:0}}
.bp-field ul{{margin:3px 0 0 12px;font-size:10px;color:var(--muted2)}}
.bp-field ul li{{margin-bottom:2px}}
.headline-field p{{font-size:14px;font-weight:700}}
.obj-row{{background:var(--c2);border-radius:6px;padding:8px 10px;margin-bottom:4px}}
.obj-q{{font-size:10px;color:#fca5a5;margin-bottom:3px;font-style:italic}}
.obj-a{{font-size:10px;color:var(--muted2)}}
.names-grid{{display:flex;flex-direction:column;gap:4px;margin-bottom:12px}}
.nm-item{{display:flex;align-items:center;gap:7px;background:var(--c2);border-radius:6px;padding:6px 10px;font-size:11px}}
.nm-tag{{font-size:8px;color:var(--cyan);background:var(--cyan)15;padding:1px 6px;border-radius:8px;border:1px solid var(--cyan)30;white-space:nowrap;flex-shrink:0}}
.modules-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:6px;margin-bottom:12px}}
.mod-item{{background:var(--c2);border-radius:6px;padding:8px 10px}}
.mod-name{{font-size:11px;font-weight:600;margin-bottom:2px}}
.mod-obj{{font-size:9px;color:var(--muted2)}}
.bp-meta{{font-size:9px;color:var(--muted);text-align:right;margin-top:6px}}
.bp-card{{background:var(--c2);border-radius:var(--r);padding:12px 14px;border:1px solid var(--border);transition:border-color .15s}}
.bp-card:hover{{border-color:var(--border2)}}
.bp-header{{display:flex;align-items:center;gap:7px;margin-bottom:7px}}
.bp-title{{font-size:12px;font-weight:600;margin-bottom:5px}}
/* ── OTHER ── */
.other-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:9px;margin-bottom:24px}}
.ocard{{background:var(--c1);border:1px solid var(--border);border-radius:var(--r);padding:12px;transition:border-color .15s}}
.ocard:hover{{border-color:var(--border2)}}
.ocard-type{{display:inline-block;font-size:8px;font-weight:700;padding:2px 7px;border-radius:20px;border-width:1px;border-style:solid;margin-bottom:7px;letter-spacing:.5px;text-transform:uppercase}}
.ocard-input{{font-size:11px;font-weight:600;margin-bottom:4px}}
.ocard-output{{font-size:10px;color:var(--muted2);line-height:1.5}}
.ocard-date{{font-size:9px;color:var(--muted);margin-top:6px}}
.empty{{text-align:center;color:var(--muted);padding:40px 20px;font-size:12px;line-height:2}}
.empty code{{background:var(--c2);padding:2px 6px;border-radius:4px;font-size:10px}}
/* ── FOOTER ── */
.footer{{text-align:center;color:var(--muted);font-size:10px;padding:20px;border-top:1px solid var(--border);letter-spacing:.3px}}
/* ── HAMBURGER ── */
.hamburger{{
  display:none;flex-direction:column;justify-content:center;gap:5px;
  background:none;border:none;cursor:pointer;padding:8px;margin-right:4px;flex-shrink:0;
}}
.hamburger span{{display:block;width:20px;height:2px;background:var(--muted2);border-radius:2px;transition:all .25s}}
.hamburger.open span:nth-child(1){{transform:translateY(7px) rotate(45deg)}}
.hamburger.open span:nth-child(2){{opacity:0;transform:scaleX(0)}}
.hamburger.open span:nth-child(3){{transform:translateY(-7px) rotate(-45deg)}}
/* ── OVERLAY ── */
.overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:199;backdrop-filter:blur(2px)}}
.overlay.show{{display:block}}
/* ── RESPONSIVE ── */
@media(max-width:1100px){{.rings-row,.kpi-row{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:900px){{
  .hamburger{{display:flex}}
  .sidebar{{
    position:fixed;left:-250px;top:0;height:100vh;z-index:200;
    transition:left .25s cubic-bezier(.4,0,.2,1);width:250px;
    box-shadow:none;
  }}
  .sidebar.open{{left:0;box-shadow:8px 0 40px rgba(0,0,0,.6)}}
  .rings-row,.kpi-row{{grid-template-columns:repeat(2,1fr)}}
  .cg-2-1,.cg-1-1,.cg-1-1-1,.cg-3-2{{grid-template-columns:1fr}}
  .bp-grid{{grid-template-columns:1fr}}
  .crit-row{{grid-template-columns:110px 1fr 40px}}
  .crit-pts{{display:none}}
  .main{{padding:14px 14px 60px}}
  .topbar{{padding:0 14px}}
  .kpi-val{{font-size:18px}}
  .ring-val{{font-size:14px}}
  canvas{{max-height:160px}}
  .bp-grid{{gap:8px}}
  .bpcard,.scard{{margin-bottom:6px}}
  .org-modal{{max-height:90vh}}
  .org-modal-body{{padding:14px 16px 20px}}
  .org-modal-header{{padding:16px 16px 12px}}
  .best{{flex-direction:column;text-align:center;gap:12px}}
  .score-ring{{margin:0 auto}}
}}
@media(max-width:480px){{
  .rings-row,.kpi-row{{grid-template-columns:1fr 1fr}}
  .topbar .tb-path{{display:none}}
  .tb-live{{font-size:8px;padding:2px 8px}}
  .sec{{font-size:8px}}
  .kpi-val{{font-size:16px}}
  .org-node{{width:130px;padding:10px 10px}}
  .org-node-name{{font-size:10px}}
  .org-node-tag{{font-size:7px}}
  .org-root{{padding:14px 20px}}
  .org-root-title{{font-size:15px}}
}}

/* ── ORGANOGRAMA ── */
.org-wrap{{overflow-x:auto;padding:12px 0 32px}}
.org-tree{{display:flex;flex-direction:column;align-items:center;gap:0;min-width:900px}}
.org-root{{
  background:linear-gradient(135deg,var(--cyan)18,var(--purple)18);
  border:1.5px solid var(--cyan)66;border-radius:14px;
  padding:18px 40px;text-align:center;position:relative;
  box-shadow:0 0 32px rgba(0,229,255,.18),0 4px 24px rgba(0,0,0,.5);
}}
.org-root-title{{font-size:18px;font-weight:900;color:var(--cyan);letter-spacing:-.3px}}
.org-root-sub{{font-size:10px;color:var(--muted2);margin-top:3px}}
.org-connector-v{{width:2px;height:32px;background:linear-gradient(180deg,var(--border2),var(--border));margin:0 auto}}
.org-connector-h{{display:flex;align-items:flex-start;position:relative;gap:0}}
.org-connector-h::before{{
  content:'';position:absolute;top:0;left:10%;right:10%;height:2px;
  background:linear-gradient(90deg,transparent,var(--border2) 20%,var(--border2) 80%,transparent);
}}
.org-col{{display:flex;flex-direction:column;align-items:center;flex:1;padding-top:32px}}
.org-col-line{{width:2px;height:24px;background:linear-gradient(180deg,var(--border2),var(--border));margin:0 auto}}
.org-node{{
  background:linear-gradient(145deg,var(--c1),var(--c2));
  border:1px solid var(--border);border-radius:12px;
  padding:14px 16px;width:160px;cursor:pointer;
  transition:all .2s;position:relative;overflow:hidden;
  box-shadow:0 3px 16px rgba(0,0,0,.4);
}}
.org-node::before{{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--node-color,var(--cyan));opacity:.7}}
.org-node:hover{{transform:translateY(-3px);border-color:var(--node-color,var(--cyan));box-shadow:0 8px 28px rgba(0,0,0,.5),0 0 16px var(--node-glow,rgba(0,229,255,.12))}}
.org-node-icon{{font-size:22px;margin-bottom:6px;text-align:center}}
.org-node-name{{font-size:11px;font-weight:700;text-align:center;color:var(--text);line-height:1.3;margin-bottom:4px}}
.org-node-tag{{font-size:8px;font-weight:700;padding:2px 7px;border-radius:8px;text-align:center;background:var(--node-color,var(--cyan))18;color:var(--node-color,var(--cyan));border:1px solid var(--node-color,var(--cyan))30;margin:0 auto;display:table}}
.org-node-expand{{font-size:9px;color:var(--muted);text-align:center;margin-top:6px;opacity:.6}}

/* Modal do nó */
.org-modal-overlay{{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(6px);
  z-index:1000;align-items:center;justify-content:center;padding:20px;
}}
.org-modal-overlay.open{{display:flex}}
.org-modal{{
  background:linear-gradient(145deg,var(--c2),var(--c3));
  border:1px solid var(--border2);border-radius:16px;
  max-width:580px;width:100%;max-height:80vh;overflow-y:auto;
  box-shadow:0 20px 60px rgba(0,0,0,.7),0 0 40px rgba(112,64,200,.2);
  position:relative;
}}
.org-modal-header{{
  padding:24px 28px 16px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:14px;
  position:sticky;top:0;background:linear-gradient(145deg,var(--c2),var(--c3));z-index:1;
}}
.org-modal-icon{{font-size:32px}}
.org-modal-title{{font-size:17px;font-weight:800}}
.org-modal-tag{{font-size:9px;font-weight:700;padding:3px 10px;border-radius:10px;margin-top:4px;display:inline-block}}
.org-modal-close{{margin-left:auto;background:var(--c3);border:1px solid var(--border);color:var(--muted2);width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;transition:all .15s;flex-shrink:0}}
.org-modal-close:hover{{border-color:var(--pink);color:var(--pink)}}
.org-modal-body{{padding:20px 28px 28px}}
.org-modal-desc{{font-size:12px;color:var(--muted3);margin-bottom:20px;line-height:1.7}}
.org-func-title{{font-size:9px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px}}
.org-func-list{{display:flex;flex-direction:column;gap:7px}}
.org-func-item{{
  display:flex;align-items:flex-start;gap:10px;
  background:var(--c1);border-radius:8px;padding:10px 12px;
  border-left:3px solid var(--node-color,var(--cyan));
}}
.org-func-ico{{font-size:14px;flex-shrink:0;margin-top:1px}}
.org-func-text{{font-size:11px;color:var(--muted3);line-height:1.5}}
.org-func-text strong{{color:var(--text);display:block;margin-bottom:2px}}
.org-modal-inputs{{margin-top:16px}}
.org-io-row{{display:flex;gap:10px;margin-top:10px}}
.org-io{{flex:1;background:var(--c1);border-radius:8px;padding:10px 12px}}
.org-io-label{{font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:6px}}
.org-io-items{{font-size:10px;color:var(--muted2);line-height:1.8}}
</style>
</head>
<body>
<div class="layout">

<!-- ── OVERLAY (mobile) ──────────────────────────────── -->
<div class="overlay" id="overlay" onclick="closeSidebar()"></div>

<!-- ── SIDEBAR ─────────────────────────────────────────── -->
<aside class="sidebar" id="sidebar">
  <div class="sb-logo">
    <span class="sb-dot"></span>
    <div>
      MYO
      <span class="sb-sub">Pipeline de Negócio</span>
    </div>
  </div>
  <div class="sb-section">Principal</div>
  <a href="#overview"     class="sb-link active"><span class="ico">◈</span> Visão Geral</a>
  <a href="#financeiro"   class="sb-link"><span class="ico">◈</span> Financeiro</a>
  <a href="#simulator"    class="sb-link"><span class="ico">◈</span> Simulador</a>
  <div class="sb-divider"></div>
  <div class="sb-section">Engines</div>
  <a href="#pipeline"     class="sb-link"><span class="ico">◈</span> Pipeline</a>
  <a href="#crm"          class="sb-link"><span class="ico">◈</span> CRM</a>
  <a href="#leads-origem" class="sb-link"><span class="ico">◈</span> Origem Leads</a>
  <a href="#performance"  class="sb-link"><span class="ico">◈</span> Performance</a>
  <a href="#ads"          class="sb-link"><span class="ico">◈</span> Ads</a>
  <div class="sb-divider"></div>
  <div class="sb-section">Análise</div>
  <a href="#oportunidades" class="sb-link"><span class="ico">◈</span> Oportunidades</a>
  <a href="#producao"      class="sb-link"><span class="ico">◈</span> Produção</a>
  <div class="sb-divider"></div>
  <div class="sb-section">Estrutura</div>
  <a href="#organograma"   class="sb-link"><span class="ico">◈</span> Organograma</a>
  <div class="sb-divider"></div>
  <div class="sb-section">Segurança</div>
  <a href="#security"      class="sb-link"><span class="ico">◈</span> Execution Control</a>
  <div class="sb-footer">
    {now}<br>
    {total} opor · {n_leads} leads · {n_ads} ads
  </div>
</aside>

<!-- ── MAIN CONTENT ─────────────────────────────────────── -->
<div class="content">

<div class="topbar">
  <button class="hamburger" id="hamburger" onclick="toggleSidebar()" aria-label="Menu">
    <span></span><span></span><span></span>
  </button>
  <div class="tb-path">MYO <span>/ Dashboard</span></div>
  <div class="tb-spacer"></div>
  <div class="tb-date">{now}</div>
  <div class="tb-live">● LIVE</div>
</div>

<div class="main">

<!-- ── OVERVIEW ─────────────────────────────────────────── -->
<div id="overview"></div>
<div class="sec">Métricas Executivas</div>

<!-- KPI RINGS -->
<div class="rings-row">
  <div class="ring-card" style="--accent:var(--cyan)">
    <div class="ring-wrap">
      <svg class="ring-svg" viewBox="0 0 80 80">
        <circle class="ring-track" cx="40" cy="40" r="33"/>
        <circle class="ring-fill" cx="40" cy="40" r="33"
          stroke="var(--cyan)"
          stroke-dasharray="{round(min(100,fin_margin_pct)/100*207.3,1)} 207.3"
          stroke-dashoffset="0"/>
      </svg>
      <div class="ring-inner">
        <div class="ring-val" style="color:var(--cyan)">{fin_margin_pct:.0f}%</div>
        <div class="ring-unit">margem</div>
      </div>
    </div>
    <div class="ring-info">
      <div class="ring-label">Margem</div>
      <div class="ring-sub">R${fin_profit:,.0f} lucro</div>
    </div>
  </div>
  <div class="ring-card" style="--accent:var(--pink)">
    <div class="ring-wrap">
      <svg class="ring-svg" viewBox="0 0 80 80">
        <circle class="ring-track" cx="40" cy="40" r="33"/>
        <circle class="ring-fill" cx="40" cy="40" r="33"
          stroke="var(--pink)"
          stroke-dasharray="{round(min(100,ads_roas*25)/100*207.3,1)} 207.3"
          stroke-dashoffset="0"/>
      </svg>
      <div class="ring-inner">
        <div class="ring-val" style="color:var(--pink)">{ads_roas:.1f}x</div>
        <div class="ring-unit">ROAS</div>
      </div>
    </div>
    <div class="ring-info">
      <div class="ring-label">Retorno Ads</div>
      <div class="ring-sub">R${ads_spend:,.0f} spend</div>
    </div>
  </div>
  <div class="ring-card" style="--accent:var(--neon)">
    <div class="ring-wrap">
      <svg class="ring-svg" viewBox="0 0 80 80">
        <circle class="ring-track" cx="40" cy="40" r="33"/>
        <circle class="ring-fill" cx="40" cy="40" r="33"
          stroke="var(--neon)"
          stroke-dasharray="{round(min(100,n_quentes*10)/100*207.3,1)} 207.3"
          stroke-dashoffset="0"/>
      </svg>
      <div class="ring-inner">
        <div class="ring-val" style="color:var(--neon)">{n_quentes}</div>
        <div class="ring-unit">quentes</div>
      </div>
    </div>
    <div class="ring-info">
      <div class="ring-label">Leads Quentes</div>
      <div class="ring-sub">{n_leads} leads total</div>
    </div>
  </div>
  <div class="ring-card" style="--accent:var(--amber)">
    <div class="ring-wrap">
      <svg class="ring-svg" viewBox="0 0 80 80">
        <circle class="ring-track" cx="40" cy="40" r="33"/>
        <circle class="ring-fill" cx="40" cy="40" r="33"
          stroke="var(--amber)"
          stroke-dasharray="{round(min(100,(n_max+n_alta)*10)/100*207.3,1)} 207.3"
          stroke-dashoffset="0"/>
      </svg>
      <div class="ring-inner">
        <div class="ring-val" style="color:var(--amber)">{n_max+n_alta}</div>
        <div class="ring-unit">executar</div>
      </div>
    </div>
    <div class="ring-info">
      <div class="ring-label">Oportunidades</div>
      <div class="ring-sub">{total} avaliadas</div>
    </div>
  </div>
  <div class="ring-card" style="--accent:var(--purple)">
    <div class="ring-wrap">
      <svg class="ring-svg" viewBox="0 0 80 80">
        <circle class="ring-track" cx="40" cy="40" r="33"/>
        <circle class="ring-fill" cx="40" cy="40" r="33"
          stroke="var(--purple)"
          stroke-dasharray="{round(min(100,sim_best_pct)/100*207.3,1)} 207.3"
          stroke-dashoffset="0"/>
      </svg>
      <div class="ring-inner">
        <div class="ring-val" style="color:var(--purple)">+{sim_best_pct}%</div>
        <div class="ring-unit">upside</div>
      </div>
    </div>
    <div class="ring-info">
      <div class="ring-label">Melhor Cenário</div>
      <div class="ring-sub">{n_sims} simulações</div>
    </div>
  </div>
</div>

<!-- KPI FLAT ROW -->
<div class="kpi-row">
  <div class="kpi">
    <div class="kpi-glow" style="background:var(--cyan)"></div>
    <div class="kpi-label">Receita / Dia</div>
    <div class="kpi-val" style="color:var(--cyan)">R${(fin_revenue/30):,.0f}</div>
    <div class="kpi-sub">R${fin_revenue:,.0f}/mês</div>
  </div>
  <div class="kpi">
    <div class="kpi-glow" style="background:var(--pink)"></div>
    <div class="kpi-label">Blueprints</div>
    <div class="kpi-val" style="color:var(--pink)">{n_bp}</div>
    <div class="kpi-sub">produtos construídos</div>
  </div>
  <div class="kpi">
    <div class="kpi-glow" style="background:var(--neon)"></div>
    <div class="kpi-label">Conteúdos</div>
    <div class="kpi-val" style="color:var(--neon)">{n_content}</div>
    <div class="kpi-sub">batches gerados</div>
  </div>
  <div class="kpi">
    <div class="kpi-glow" style="background:var(--amber)"></div>
    <div class="kpi-label">Vídeos</div>
    <div class="kpi-val" style="color:var(--amber)">{n_videos}</div>
    <div class="kpi-sub">{n_funnels} funis ativos</div>
  </div>
  <div class="kpi">
    <div class="kpi-glow" style="background:var(--purple)"></div>
    <div class="kpi-label">Sessões OS</div>
    <div class="kpi-val" style="color:var(--purple)">{n_sessions}</div>
    <div class="kpi-sub">✓ {n_completed} concluídas · {n_scaling} scalings</div>
  </div>
</div>

<!-- ── FINANCIAL ─────────────────────────────────────────── -->
<div id="financeiro"></div>
<div class="sec">Análise Financeira</div>
<div class="cg-2-1">
  <div class="panel" style="--accent:var(--cyan)">
    <div class="p-title"><span class="bar" style="background:var(--cyan)"></span>Receita · Custo · Lucro — Histórico</div>
    <canvas id="revTrendChart"></canvas>
  </div>
  <div class="panel" style="--accent:var(--amber)">
    <div class="p-title"><span class="bar" style="background:var(--amber)"></span>Custos por Categoria</div>
    <canvas id="costDonutChart"></canvas>
  </div>
</div>
{render_financial_section(financial)}

<!-- ── SIMULATOR ─────────────────────────────────────────── -->
<div id="simulator"></div>
<div class="sec">Growth Simulator</div>
<div class="cg-1-1">
  <div class="panel" style="--accent:var(--purple)">
    <div class="p-title"><span class="bar" style="background:var(--purple)"></span>Cenários — Receita vs Lucro Mensal</div>
    <canvas id="scenarioChart"></canvas>
  </div>
  <div class="panel" style="--accent:var(--teal)">
    <div class="p-title"><span class="bar" style="background:var(--teal)"></span>Funil de Vendas CRM</div>
    <canvas id="crmFunnelChart"></canvas>
  </div>
</div>
{render_simulator_section(simulations)}

<!-- ── PIPELINE ──────────────────────────────────────────── -->
<div id="pipeline"></div>
{render_sessions_section(sessions)}
{render_scaling_section(scaling)}
{render_validation_section(validations)}
{render_performance_section(performances, memory_items)}

<!-- ── CRM ───────────────────────────────────────────────── -->
<div id="crm"></div>
{render_crm_section(crm_leads)}

<!-- ── LEAD ORIGIN ───────────────────────────────────────── -->
<div id="leads-origem"></div>
<div class="sec">Origem dos Leads</div>
<div class="cg-1-1">
  <div class="panel" style="--accent:var(--amber)">
    <div class="p-title"><span class="bar" style="background:var(--amber)"></span>Leads por Canal / Fonte</div>
    <canvas id="sourceChart"></canvas>
  </div>
  <div class="panel" style="--accent:var(--pink)">
    <div class="p-title"><span class="bar" style="background:var(--pink)"></span>Temperatura dos Leads</div>
    <canvas id="tempChart"></canvas>
  </div>
</div>

<!-- ── PERFORMANCE ───────────────────────────────────────── -->
<div id="performance"></div>

<!-- ── ADS ───────────────────────────────────────────────── -->
<div id="ads"></div>
{render_ads_section(ads)}

<!-- ── OPPORTUNITIES ─────────────────────────────────────── -->
<div id="oportunidades"></div>
<div class="sec">Análise de Oportunidades</div>

{f"""<div class="best">
  <div class="score-ring">
    <svg class="score-ring-svg" viewBox="0 0 76 76">
      <circle fill="none" cx="38" cy="38" r="32" stroke="var(--c3)" stroke-width="6"/>
      <circle fill="none" cx="38" cy="38" r="32" stroke="var(--cyan)" stroke-width="6"
        stroke-linecap="round"
        stroke-dasharray="{round(best.get('final_score',0)/100*201.1,1)} 201.1"
        stroke-dashoffset="0"/>
    </svg>
    <div class="score-inner">
      <div class="score-num">{best.get('final_score',0)}</div>
      <div class="score-den">/100</div>
    </div>
  </div>
  <div class="best-info">
    <div class="best-title">{best.get('idea_title','')}</div>
    <div class="best-badges">
      <span class="badge badge-c">{PRIORITY_LABEL.get(best.get('priority',''),'')}</span>
      <span class="badge badge-c">{best.get('recommendation','').upper()}</span>
      <span class="badge badge-m">{best.get('initial_format','')}</span>
    </div>
    <div class="best-next">Próximo passo: <strong>{best.get('next_step','')}</strong></div>
  </div>
</div>""" if best else ""}

<div class="cg-2-1">
  <div class="panel" style="--accent:var(--blue)">
    <div class="p-title"><span class="bar" style="background:var(--blue)"></span>Score por Oportunidade</div>
    <canvas id="barChart"></canvas>
  </div>
  <div class="panel" style="--accent:var(--pink)">
    <div class="p-title"><span class="bar" style="background:var(--pink)"></span>Distribuição por Prioridade</div>
    <canvas id="donutChart"></canvas>
  </div>
</div>
<div class="cg-1-1">
  <div class="panel" style="--accent:var(--cyan)">
    <div class="p-title"><span class="bar" style="background:var(--cyan)"></span>Radar — Comparativo de Critérios</div>
    <canvas id="radarChart"></canvas>
  </div>
  <div class="panel" style="--accent:var(--purple)">
    <div class="p-title"><span class="bar" style="background:var(--purple)"></span>Média por Critério</div>
    <canvas id="avgChart"></canvas>
  </div>
</div>

<div class="sec">Fila de Execução</div>
<div class="panel" style="margin-bottom:12px;--accent:var(--cyan)">
  <div class="queue">
    {queue_html if scorings else '<div class="empty">Nenhuma oportunidade ainda.</div>'}
  </div>
</div>

<div class="sec">Heatmap de Critérios</div>
<div class="hm-wrap" style="margin-bottom:12px">
  <table class="ht-table">{heatmap_html}</table>
</div>

<div class="sec">Detalhamento</div>
<div class="fbar">
  <button class="fbtn on" onclick="filt(this,'all')">Todas ({total})</button>
  <button class="fbtn" onclick="filt(this,'maxima')">Máxima ({n_max})</button>
  <button class="fbtn" onclick="filt(this,'alta')">Alta ({n_alta})</button>
  <button class="fbtn" onclick="filt(this,'media')">Média ({n_media})</button>
  <button class="fbtn" onclick="filt(this,'baixa')">Baixa ({n_baixa})</button>
</div>
<div id="cards">
  {cards_html if scorings else '<div class="empty">Nenhuma avaliação ainda.<br>Rode: <code>python opportunity_scorer.py "sua ideia"</code></div>'}
</div>

<!-- ── PRODUCAO ───────────────────────────────────────────── -->
<div id="producao"></div>
<div class="sec" style="margin-top:20px">Product Blueprints</div>
{render_blueprints(blueprints)}
<div class="sec" style="margin-top:20px">Content Engine</div>
{render_contents(contents)}
<div class="sec" style="margin-top:20px">Video Engine</div>
{render_videos(videos)}
<div class="sec" style="margin-top:20px">Sales Engine — Funis</div>
{render_funnels(funnels)}

{f'<div class="sec" style="margin-top:20px">Outros Outputs</div><div class="other-grid">{others_html}</div>' if others else ""}

<!-- ── ORGANOGRAMA ──────────────────────────────────────── -->
<div id="organograma"></div>
<div class="sec" style="margin-top:32px">Organograma MYO — Estrutura do Negócio</div>
<div class="panel" style="padding:28px 20px">
  <div style="font-size:11px;color:var(--muted2);margin-bottom:24px;text-align:center">
    Clique em qualquer engine para ver suas funções, entradas e saídas
  </div>
  <div class="org-wrap">
  <div class="org-tree">

    <!-- ROOT -->
    <div class="org-root">
      <div class="org-root-title">🚀 MYO</div>
      <div class="org-root-sub">Pipeline de Negócio com IA — 12 Engines Integrados</div>
    </div>
    <div class="org-connector-v"></div>

    <!-- MASTER CONTROLLER -->
    <div onclick="openOrg('master')" class="org-node" style="--node-color:#c060ff;--node-glow:rgba(192,96,255,.15);width:200px">
      <div class="org-node-icon">🧠</div>
      <div class="org-node-name">Master Controller</div>
      <div class="org-node-tag">Orquestrador Geral</div>
      <div class="org-node-expand">▼ ver funções</div>
    </div>
    <div class="org-connector-v"></div>

    <!-- LINHA 1: DESCOBERTA -->
    <div style="width:100%;text-align:center;font-size:9px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:2px;margin-bottom:8px">— Fase 1: Descoberta —</div>
    <div class="org-connector-h" style="width:100%;justify-content:center">
      <div class="org-col">
        <div class="org-col-line"></div>
        <div onclick="openOrg('opportunity')" class="org-node" style="--node-color:#00e5ff;--node-glow:rgba(0,229,255,.12)">
          <div class="org-node-icon">🔍</div>
          <div class="org-node-name">Opportunity Engine</div>
          <div class="org-node-tag">Score de Oportunidade</div>
          <div class="org-node-expand">▼ ver funções</div>
        </div>
      </div>
      <div class="org-col">
        <div class="org-col-line"></div>
        <div onclick="openOrg('product')" class="org-node" style="--node-color:#39ff14;--node-glow:rgba(57,255,20,.12)">
          <div class="org-node-icon">📦</div>
          <div class="org-node-name">Product Engine</div>
          <div class="org-node-tag">Blueprint de Produto</div>
          <div class="org-node-expand">▼ ver funções</div>
        </div>
      </div>
      <div class="org-col">
        <div class="org-col-line"></div>
        <div onclick="openOrg('financial')" class="org-node" style="--node-color:#ffb800;--node-glow:rgba(255,184,0,.12)">
          <div class="org-node-icon">💰</div>
          <div class="org-node-name">Financial Engine</div>
          <div class="org-node-tag">Receita & Margem</div>
          <div class="org-node-expand">▼ ver funções</div>
        </div>
      </div>
      <div class="org-col">
        <div class="org-col-line"></div>
        <div onclick="openOrg('growth')" class="org-node" style="--node-color:#5b9cff;--node-glow:rgba(91,156,255,.12)">
          <div class="org-node-icon">📈</div>
          <div class="org-node-name">Growth Simulator</div>
          <div class="org-node-tag">Cenários de Crescimento</div>
          <div class="org-node-expand">▼ ver funções</div>
        </div>
      </div>
    </div>

    <div class="org-connector-v" style="margin-top:20px"></div>

    <!-- LINHA 2: CRIAÇÃO -->
    <div style="width:100%;text-align:center;font-size:9px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:2px;margin-bottom:8px">— Fase 2: Criação & Distribuição —</div>
    <div class="org-connector-h" style="width:100%;justify-content:center">
      <div class="org-col">
        <div class="org-col-line"></div>
        <div onclick="openOrg('content')" class="org-node" style="--node-color:#ff4db8;--node-glow:rgba(255,77,184,.12)">
          <div class="org-node-icon">✍️</div>
          <div class="org-node-name">Content Engine</div>
          <div class="org-node-tag">Conteúdo & Hooks</div>
          <div class="org-node-expand">▼ ver funções</div>
        </div>
      </div>
      <div class="org-col">
        <div class="org-col-line"></div>
        <div onclick="openOrg('video')" class="org-node" style="--node-color:#c060ff;--node-glow:rgba(192,96,255,.12)">
          <div class="org-node-icon">🎬</div>
          <div class="org-node-name">Video Engine</div>
          <div class="org-node-tag">Produção de Vídeo IA</div>
          <div class="org-node-expand">▼ ver funções</div>
        </div>
      </div>
      <div class="org-col">
        <div class="org-col-line"></div>
        <div onclick="openOrg('sales')" class="org-node" style="--node-color:#00ffc8;--node-glow:rgba(0,255,200,.12)">
          <div class="org-node-icon">🛒</div>
          <div class="org-node-name">Sales Engine</div>
          <div class="org-node-tag">Funil de Vendas</div>
          <div class="org-node-expand">▼ ver funções</div>
        </div>
      </div>
      <div class="org-col">
        <div class="org-col-line"></div>
        <div onclick="openOrg('ads')" class="org-node" style="--node-color:#ff4444;--node-glow:rgba(255,68,68,.12)">
          <div class="org-node-icon">📣</div>
          <div class="org-node-name">Ads Engine</div>
          <div class="org-node-tag">Tráfego Pago</div>
          <div class="org-node-expand">▼ ver funções</div>
        </div>
      </div>
    </div>

    <div class="org-connector-v" style="margin-top:20px"></div>

    <!-- LINHA 3: ANÁLISE -->
    <div style="width:100%;text-align:center;font-size:9px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:2px;margin-bottom:8px">— Fase 3: Análise & Escala —</div>
    <div class="org-connector-h" style="width:100%;justify-content:center">
      <div class="org-col">
        <div class="org-col-line"></div>
        <div onclick="openOrg('performance')" class="org-node" style="--node-color:#00e5ff;--node-glow:rgba(0,229,255,.12)">
          <div class="org-node-icon">📊</div>
          <div class="org-node-name">Performance Engine</div>
          <div class="org-node-tag">Score de Ativos</div>
          <div class="org-node-expand">▼ ver funções</div>
        </div>
      </div>
      <div class="org-col">
        <div class="org-col-line"></div>
        <div onclick="openOrg('validation')" class="org-node" style="--node-color:#39ff14;--node-glow:rgba(57,255,20,.12)">
          <div class="org-node-icon">✅</div>
          <div class="org-node-name">Validation Engine</div>
          <div class="org-node-tag">Validação de Mercado</div>
          <div class="org-node-expand">▼ ver funções</div>
        </div>
      </div>
      <div class="org-col">
        <div class="org-col-line"></div>
        <div onclick="openOrg('crm')" class="org-node" style="--node-color:#ffb800;--node-glow:rgba(255,184,0,.12)">
          <div class="org-node-icon">👥</div>
          <div class="org-node-name">CRM Engine</div>
          <div class="org-node-tag">Pipeline de Leads</div>
          <div class="org-node-expand">▼ ver funções</div>
        </div>
      </div>
      <div class="org-col">
        <div class="org-col-line"></div>
        <div onclick="openOrg('scaling')" class="org-node" style="--node-color:#c060ff;--node-glow:rgba(192,96,255,.12)">
          <div class="org-node-icon">🚀</div>
          <div class="org-node-name">Scaling Engine</div>
          <div class="org-node-tag">Decisão de Escala</div>
          <div class="org-node-expand">▼ ver funções</div>
        </div>
      </div>
    </div>

  </div><!-- /org-tree -->
  </div><!-- /org-wrap -->
</div><!-- /panel -->

<!-- MODAL ORGANOGRAMA -->
<div class="org-modal-overlay" id="orgModalOverlay" onclick="closeOrg(event)">
  <div class="org-modal" id="orgModal">
    <div class="org-modal-header">
      <div class="org-modal-icon" id="orgModalIcon"></div>
      <div>
        <div class="org-modal-title" id="orgModalTitle"></div>
        <div class="org-modal-tag" id="orgModalTag"></div>
      </div>
      <button class="org-modal-close" onclick="closeOrgBtn()">✕</button>
    </div>
    <div class="org-modal-body">
      <div class="org-modal-desc" id="orgModalDesc"></div>
      <div class="org-func-title">Funções principais</div>
      <div class="org-func-list" id="orgModalFuncs"></div>
      <div class="org-modal-inputs" id="orgModalIO"></div>
    </div>
  </div>
</div>

<!-- ── SECURITY ──────────────────────────────────────── -->
<div id="security"></div>
{render_security_section(security)}

</div><!-- /main -->
<div class="footer">MYO · {now} · {total} oportunidades · {n_bp} blueprints · {n_funnels} funis · {n_leads} leads · {n_valid} validações · {n_perf} performances · {n_scaling} scalings · {n_ads} ads · R${fin_revenue:,.0f} receita/mês</div>
</div><!-- /content -->
</div><!-- /layout -->

<script>
Chart.defaults.color = '#6b5a8a';
Chart.defaults.borderColor = '#2a1560';
Chart.defaults.font.family = 'Inter, system-ui, sans-serif';
Chart.defaults.font.size = 10;

// Revenue Trend
if ({json.dumps(bool(fin_projs_all))}) {{
  new Chart(document.getElementById('revTrendChart'), {{
    type: 'line',
    data: {{
      labels: {fin_tl_labels},
      datasets: [
        {{ label:'Receita', data:{fin_tl_rev}, borderColor:'#00e5ff', backgroundColor:'#00e5ff12', fill:true, tension:.4, borderWidth:2, pointRadius:3, pointBackgroundColor:'#00e5ff' }},
        {{ label:'Custo',   data:{fin_tl_cost}, borderColor:'#ff4db8', backgroundColor:'rgba(0,0,0,0)', tension:.4, borderWidth:2, pointRadius:3, borderDash:[5,3] }},
        {{ label:'Lucro',   data:{fin_tl_profit}, borderColor:'#39ff14', backgroundColor:'#39ff1410', fill:true, tension:.4, borderWidth:2, pointRadius:3 }}
      ]
    }},
    options: {{
      responsive:true, maintainAspectRatio:true,
      interaction:{{ mode:'index', intersect:false }},
      plugins:{{ legend:{{ position:'bottom', labels:{{ boxWidth:8, padding:12, color:'#9b87b8' }} }} }},
      scales:{{ x:{{ grid:{{ display:false }}, ticks:{{ color:'#6b5a8a', maxTicksLimit:8 }} }}, y:{{ grid:{{ color:'#2a1560' }}, ticks:{{ color:'#6b5a8a', callback: v => 'R$'+v.toLocaleString('pt-BR') }} }} }}
    }}
  }});
}}

// Cost Donut
if ({json.dumps(bool(fin_cats_all))}) {{
  new Chart(document.getElementById('costDonutChart'), {{
    type: 'doughnut',
    data: {{ labels:{cost_cat_labels}, datasets:[{{ data:{cost_cat_values}, backgroundColor:{cost_cat_colors}, borderWidth:0, hoverOffset:6 }}] }},
    options: {{ responsive:true, maintainAspectRatio:true, cutout:'70%', plugins:{{ legend:{{ position:'bottom', labels:{{ boxWidth:8, padding:10, color:'#9b87b8' }} }} }} }}
  }});
}}

// Scenario Chart
if ({json.dumps(bool(sim_sc))}) {{
  new Chart(document.getElementById('scenarioChart'), {{
    type: 'bar',
    data: {{
      labels: {sc_labels},
      datasets: [
        {{ label:'Receita', data:{sc_rev},    backgroundColor:{sc_colors}, borderColor:{sc_border}, borderWidth:1, borderRadius:5, borderSkipped:false }},
        {{ label:'Lucro',   data:{sc_profit}, backgroundColor:'#4f8ef720', borderColor:'#4f8ef7',   borderWidth:1, borderRadius:5, borderSkipped:false }}
      ]
    }},
    options: {{
      responsive:true, maintainAspectRatio:true,
      interaction:{{ mode:'index', intersect:false }},
      plugins:{{ legend:{{ position:'bottom', labels:{{ boxWidth:8, padding:12, color:'#9b87b8' }} }} }},
      scales:{{ x:{{ grid:{{ display:false }}, ticks:{{ color:'#6b5a8a' }} }}, y:{{ grid:{{ color:'#2a1560' }}, ticks:{{ color:'#6b5a8a', callback: v => 'R$'+v.toLocaleString('pt-BR') }} }} }}
    }}
  }});
}}

// CRM Funnel
new Chart(document.getElementById('crmFunnelChart'), {{
  type: 'bar',
  data: {{
    labels: {crm_funnel_lbls},
    datasets: [{{ label:'Leads', data:{crm_funnel_vals}, backgroundColor:['#00e5ff22','#00ffc822','#ffb80022','#b44fff22','#ff4db822','#39ff1440'], borderColor:['#00e5ff','#00ffc8','#ffb800','#b44fff','#ff4db8','#39ff14'], borderWidth:1, borderRadius:5, borderSkipped:false }}]
  }},
  options: {{
    indexAxis:'y', responsive:true, maintainAspectRatio:true,
    plugins:{{ legend:{{ display:false }} }},
    scales:{{ x:{{ grid:{{ color:'#2a1560' }}, ticks:{{ color:'#6b5a8a', stepSize:1 }} }}, y:{{ grid:{{ display:false }}, ticks:{{ color:'#9b87b8' }} }} }}
  }}
}});

// Lead Source
new Chart(document.getElementById('sourceChart'), {{
  type: 'bar',
  data: {{
    labels: {lead_source_labels},
    datasets: [{{ label:'Leads', data:{lead_source_values}, backgroundColor:'#ffb80022', borderColor:'#ffb800', borderWidth:1, borderRadius:5, borderSkipped:false }}]
  }},
  options: {{
    indexAxis:'y', responsive:true, maintainAspectRatio:true,
    plugins:{{ legend:{{ display:false }} }},
    scales:{{ x:{{ grid:{{ color:'#2a1560' }}, ticks:{{ color:'#6b5a8a', stepSize:1 }} }}, y:{{ grid:{{ display:false }}, ticks:{{ color:'#9b87b8' }} }} }}
  }}
}});

// Temperature Donut
new Chart(document.getElementById('tempChart'), {{
  type: 'doughnut',
  data: {{
    labels: ['Quente 🔥','Morno','Frio'],
    datasets: [{{ data:{temp_data}, backgroundColor:['#ff444440','#ffb80040','#4f8ef740'], borderColor:['#ff4444','#ffb800','#4f8ef7'], borderWidth:2, hoverOffset:6 }}]
  }},
  options: {{ responsive:true, maintainAspectRatio:true, cutout:'65%', plugins:{{ legend:{{ position:'bottom', labels:{{ boxWidth:8, padding:10, color:'#9b87b8' }} }} }} }}
}});

// Opportunity Bar
new Chart(document.getElementById('barChart'), {{
  type: 'bar',
  data: {{ labels:{bar_labels}, datasets:[{{ data:{bar_scores}, backgroundColor:{bar_colors}, borderRadius:5, borderSkipped:false }}] }},
  options: {{
    responsive:true, maintainAspectRatio:true,
    plugins:{{ legend:{{ display:false }}, tooltip:{{ callbacks:{{ label: ctx => ' Score: '+ctx.raw+'/100' }} }} }},
    scales:{{ x:{{ ticks:{{ color:'#6b5a8a', font:{{ size:9 }} }}, grid:{{ display:false }} }}, y:{{ min:0, max:100, ticks:{{ stepSize:20, color:'#6b5a8a' }}, grid:{{ color:'#2a1560' }} }} }}
  }}
}});

// Priority Donut
new Chart(document.getElementById('donutChart'), {{
  type: 'doughnut',
  data: {{ labels:{donut_labels}, datasets:[{{ data:{donut_data}, backgroundColor:['#00e5ff40','#4f8ef740','#ffb80040','#ff444440'], borderColor:['#00e5ff','#4f8ef7','#ffb800','#ff4444'], borderWidth:1, hoverOffset:5 }}] }},
  options: {{ responsive:true, maintainAspectRatio:true, cutout:'68%', plugins:{{ legend:{{ position:'bottom', labels:{{ boxWidth:8, padding:10, color:'#9b87b8' }} }} }} }}
}});

// Radar
new Chart(document.getElementById('radarChart'), {{
  type:'radar',
  data:{{ labels:{radar_labels}, datasets:{radar_datasets_json} }},
  options:{{
    responsive:true, maintainAspectRatio:true,
    scales:{{ r:{{ min:0, max:5, ticks:{{ stepSize:1, backdropColor:'transparent', color:'#6b5a8a', font:{{ size:9 }} }}, grid:{{ color:'#2a1560' }}, angleLines:{{ color:'#2a1560' }}, pointLabels:{{ color:'#9b87b8', font:{{ size:9 }} }} }} }},
    plugins:{{ legend:{{ position:'bottom', labels:{{ boxWidth:8, padding:10, color:'#9b87b8' }} }} }}
  }}
}});

// Criteria Avg
new Chart(document.getElementById('avgChart'), {{
  type:'bar',
  data:{{ labels:{crit_avg_labels}, datasets:[{{ label:'Média', data:{crit_avg_values}, backgroundColor:'#b44fff22', borderColor:'#b44fff', borderWidth:1, borderRadius:4, borderSkipped:false }}] }},
  options:{{
    indexAxis:'y', responsive:true, maintainAspectRatio:true,
    plugins:{{ legend:{{ display:false }} }},
    scales:{{ x:{{ min:0, max:5, ticks:{{ stepSize:1, color:'#6b5a8a' }}, grid:{{ color:'#2a1560' }} }}, y:{{ grid:{{ display:false }}, ticks:{{ color:'#9b87b8', font:{{ size:9 }} }} }} }}
  }}
}});

// Toggle functions
function toggle(i)    {{ const b=document.getElementById('sbody-'+i),c=document.getElementById('chev-'+i),o=b.style.display==='block'; b.style.display=o?'none':'block'; c.classList.toggle('open',!o); }}
function toggleVid(i) {{ const b=document.getElementById('vidbody-'+i),c=document.getElementById('vidchev-'+i),o=b.style.display==='block'; b.style.display=o?'none':'block'; c.classList.toggle('open',!o); }}
function toggleCt(i)  {{ const b=document.getElementById('ctbody-'+i),c=document.getElementById('ctchev-'+i),o=b.style.display==='block'; b.style.display=o?'none':'block'; c.classList.toggle('open',!o); }}
function toggleBp(i)  {{ const b=document.getElementById('bpbody-'+i),c=document.getElementById('bpchev-'+i),o=b.style.display==='block'; b.style.display=o?'none':'block'; c.classList.toggle('open',!o); }}
function toggleFn(i)  {{ const b=document.getElementById('fnbody-'+i),c=document.getElementById('fnchev-'+i),o=b.style.display==='block'; b.style.display=o?'none':'block'; c.classList.toggle('open',!o); }}
function filt(btn,p)  {{
  document.querySelectorAll('.fbtn').forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
  document.querySelectorAll('.scard').forEach(c => {{
    c.style.display=(p==='all'||c.dataset.priority===p)?'block':'none';
  }});
}}

// Active nav link on scroll
const sections = document.querySelectorAll('[id]');
const links = document.querySelectorAll('.sb-link');
window.addEventListener('scroll', () => {{
  let cur='';
  sections.forEach(s => {{ if(window.scrollY >= s.offsetTop - 80) cur = s.id; }});
  links.forEach(l => {{ l.classList.toggle('active', l.getAttribute('href')==='#'+cur); }});
}}, {{passive:true}});

// ── ORGANOGRAMA DATA ──────────────────────────────────────
const ORG_DATA = {{
  master: {{
    icon:'🧠', name:'Master Controller', tag:'Orquestrador Geral', color:'#c060ff',
    desc:'O cérebro central do MYO. Recebe um objetivo e coordena automaticamente todos os 12 engines na sequência correta, gerenciando 11 nós de decisão e 3 modos de operação.',
    funcs:[
      {{ico:'🎯', title:'Definição de Objetivo', desc:'Recebe objetivo em linguagem natural e define task_type + execution_path ideal'}},
      {{ico:'🔄', title:'Orquestração de Engines', desc:'Chama opportunity, product, content, video, sales, performance, validation, crm, scaling e ads na sequência correta'}},
      {{ico:'📋', title:'Sessões Persistidas', desc:'Salva estado de cada sessão com todos os resultados intermediários para retomada'}},
      {{ico:'⚡', title:'3 Modos', desc:'Modo completo (todos os engines), modo rápido (opportunity + decision) ou modo personalizado'}},
      {{ico:'🔁', title:'Loop de Melhoria', desc:'Nó 11 analisa resultados e gera recomendação para o próximo ciclo'}}
    ],
    inputs:['Objetivo em texto livre','Nicho/mercado','Modo de operação'],
    outputs:['Sessão salva em outputs/sessions/','Recomendação próximo ciclo','Relatório consolidado']
  }},
  opportunity: {{
    icon:'🔍', name:'Opportunity Engine', tag:'Score de Oportunidade', color:'#00e5ff',
    desc:'Avalia e pontua oportunidades de mercado com 8 critérios ponderados. Usa Claude para análise profunda e gera um score 0-100 com prioridade de execução.',
    funcs:[
      {{ico:'📊', title:'Score 8 Critérios', desc:'Dor do mercado (20%), Urgência (15%), Monetização (15%), Escalabilidade (15%), Aquisição (10%), Diferenciação (10%), Execução (10%), Conteúdo (5%)'}},
      {{ico:'🤖', title:'Análise Claude', desc:'Claude avalia cada critério com contexto de mercado e justifica o score'}},
      {{ico:'🏆', title:'Prioridade Automática', desc:'Máxima (≥75) / Alta (≥55) / Média (≥35) / Baixa (<35)'}},
      {{ico:'💾', title:'Histórico', desc:'Salva em outputs/scoring_*.json para comparar oportunidades ao longo do tempo'}}
    ],
    inputs:['Título da ideia','Público-alvo','Nicho/mercado'],
    outputs:['Score 0-100','Prioridade','Recomendação','Breakdown por critério']
  }},
  product: {{
    icon:'📦', name:'Product Engine', tag:'Blueprint de Produto', color:'#39ff14',
    desc:'Transforma uma oportunidade validada em um produto digital completo com posicionamento, estrutura, precificação e copy base.',
    funcs:[
      {{ico:'🏗️', title:'Blueprint Completo', desc:'Define produto principal, oferta de entrada, estrutura de módulos e bônus'}},
      {{ico:'💲', title:'Estratégia de Preço', desc:'Calcula âncora de preço ideal e estrutura de value stack com percepção de valor'}},
      {{ico:'📝', title:'Copy Base', desc:'Gera headline principal, subheadline e CTA para landing page e ads'}},
      {{ico:'🎯', title:'Naming Options', desc:'3-5 opções de nome com posicionamento e diferenciação de mercado'}}
    ],
    inputs:['scoring_*.json','Público-alvo','Nicho'],
    outputs:['blueprint_*.json','Nome do produto','Estrutura de módulos','Headline + CTA']
  }},
  content: {{
    icon:'✍️', name:'Content Engine', tag:'Conteúdo & Hooks', color:'#ff4db8',
    desc:'Gera todo o arsenal de conteúdo orgânico: ângulos de dor, hooks testados, roteiros, posts e variações por plataforma.',
    funcs:[
      {{ico:'🎣', title:'Geração de Hooks', desc:'Cria 5-10 ganchos por ângulo (dor_direta, erro, oportunidade, autoridade, urgência)'}},
      {{ico:'📱', title:'Multi-plataforma', desc:'Posts adaptados para Instagram (carrossel, reels, stories), YouTube Shorts e LinkedIn'}},
      {{ico:'📖', title:'Roteiros Completos', desc:'Scripts com gancho, desenvolvimento, virada e CTA para cada formato'}},
      {{ico:'🧠', title:'Memória de Padrões', desc:'Acumula hooks e CTAs que funcionaram em memory_items.json para reutilização'}}
    ],
    inputs:['blueprint_*.json','performance_*.json (padrões vencedores)'],
    outputs:['content_*.json','Hooks','Posts prontos','Roteiros por formato']
  }},
  video: {{
    icon:'🎬', name:'Video Engine', tag:'Produção de Vídeo IA', color:'#c060ff',
    desc:'Produz vídeos completos com IA: roteiro → áudio TTS (ElevenLabs) → vídeo avatar (HeyGen) + variações de formato.',
    funcs:[
      {{ico:'🎙️', title:'TTS com ElevenLabs', desc:'Converte roteiro em áudio com voz clonada ou selecionada da biblioteca'}},
      {{ico:'🤖', title:'Avatar com HeyGen', desc:'Gera vídeo com avatar digital sincronizado com o áudio produzido'}},
      {{ico:'🎞️', title:'Variações Automáticas', desc:'Cria versão agressiva e versão elegante de cada vídeo com ângulos diferentes'}},
      {{ico:'📦', title:'Fila de Produção', desc:'Gerencia fila de vídeos pendentes e rastreia status de cada produção'}}
    ],
    inputs:['content_*.json','Roteiro final','Configuração de voz'],
    outputs:['video_*.json','Arquivo de áudio (.mp3)','URL do vídeo HeyGen','Legenda/caption']
  }},
  sales: {{
    icon:'🛒', name:'Sales Engine', tag:'Funil de Vendas', color:'#00ffc8',
    desc:'Constrói o funil de vendas completo: página de captura, sequência de e-mails, CTAs e landing page com copy persuasiva.',
    funcs:[
      {{ico:'🧲', title:'Lead Magnet', desc:'Define oferta gratuita irresistível para captura de leads qualificados'}},
      {{ico:'📧', title:'Sequência de E-mails', desc:'Cria série de 5-7 e-mails de nutrição com história, prova e oferta'}},
      {{ico:'🖥️', title:'Landing Page', desc:'Estrutura acima da dobra com headline, subheadline, bullets e CTA'}},
      {{ico:'⚡', title:'Value Stack', desc:'Monta stack de valor com precificação âncora para justificar preço do produto'}}
    ],
    inputs:['blueprint_*.json','Produto definido','Público-alvo'],
    outputs:['funnel_*.json','CTAs prontos','Sequência de e-mails','Estrutura de LP']
  }},
  ads: {{
    icon:'📣', name:'Ads Engine', tag:'Tráfego Pago', color:'#ff4444',
    desc:'Cria e otimiza campanhas de tráfego pago no Meta Ads e Google Ads, gerando criativos por ângulo e monitorando ROAS.',
    funcs:[
      {{ico:'🎯', title:'Seleção de Criativos', desc:'Filtra conteúdos com performance_score ≥ 70 para usar como base de anúncio'}},
      {{ico:'📐', title:'5 Ângulos de Anúncio', desc:'Gera copies para: dor_direta, erro_comum, oportunidade, autoridade, urgência'}},
      {{ico:'💹', title:'Monitoramento ROAS', desc:'Calcula ROAS, CPC, CPL, CPA e status automático: escalando/otimizando/pausado'}},
      {{ico:'🔧', title:'Otimização Contínua', desc:'Claude analisa performance e sugere: pausar, dobrar orçamento ou testar novo ângulo'}}
    ],
    inputs:['performance_*.json','content_*.json','Orçamento definido'],
    outputs:['ads_campaigns.json','Criativos por ângulo','Insights de otimização','Status de campanha']
  }},
  performance: {{
    icon:'📊', name:'Performance Engine', tag:'Score de Ativos', color:'#00e5ff',
    desc:'Analisa a performance de cada ativo publicado (vídeos, posts, carrosséis) com score 0-100 e extrai padrões vencedores para reutilização.',
    funcs:[
      {{ico:'📐', title:'Normalização de Métricas', desc:'Calcula engagement_rate, click_rate, lead_rate a partir dos dados brutos da plataforma'}},
      {{ico:'🏅', title:'Score 0-100', desc:'Pesos: engajamento (40%) + cliques (30%) + leads (30%). Banda: alta ≥70 / média ≥40 / baixa <40'}},
      {{ico:'🤖', title:'Análise Claude', desc:'Explica por que performou, o que repetir, o que evitar e sugere próximo conteúdo'}},
      {{ico:'🧠', title:'Memória de Padrões', desc:'Acumula hooks, CTAs e ângulos vencedores em memory_items.json para alimentar o Content Engine'}}
    ],
    inputs:['Views, likes, comments, saves, shares','Clicks e leads','Asset type + plataforma'],
    outputs:['performance_*.json','Score 0-100','Insights de melhoria','memory_items.json atualizado']
  }},
  validation: {{
    icon:'✅', name:'Validation Engine', tag:'Validação de Mercado', color:'#39ff14',
    desc:'Valida o interesse real do mercado antes de escalar. Analisa sinais de engajamento profundo como salvamentos, DMs e cliques para decidir entre escalar, ajustar ou descartar.',
    funcs:[
      {{ico:'📡', title:'Sinais de Interesse Real', desc:'Mede engagement + clicks + DMs + leads com pesos por tipo de sinal (DM = sinal mais forte)'}},
      {{ico:'🎯', title:'Validation Score 0-100', desc:'Eng (40%) + Click (25%) + DM (20%) + Lead (15%) → forte/moderado/fraco'}},
      {{ico:'🤖', title:'Análise Claude', desc:'Determina se há interesse real, analisa força da dor e define próxima ação específica'}},
      {{ico:'⚡', title:'Decisão Automática', desc:'Escalar (≥70) / Ajustar (≥40) / Descartar (<40) com plano de ação detalhado'}}
    ],
    inputs:['Métricas do conteúdo publicado','Views, DMs, leads','Plataforma'],
    outputs:['validation_*.json','Score de validação','Decisão escalar/ajustar/descartar','Próximo passo']
  }},
  crm: {{
    icon:'👥', name:'CRM Engine', tag:'Pipeline de Leads', color:'#ffb800',
    desc:'Gerencia o pipeline completo de leads: qualifica, classifica por temperatura, atribui estágio do pipeline e gera sequência de follow-up personalizada.',
    funcs:[
      {{ico:'🌡️', title:'Lead Scoring', desc:'Analisa mensagem/comportamento e atribui score + temperatura: quente/morno/frio'}},
      {{ico:'🗂️', title:'Pipeline Automático', desc:'Quente → Qualificado | Morno → Interessado | Frio → Entrada'}},
      {{ico:'💬', title:'Follow-up Personalizado', desc:'GPT gera 3 mensagens personalizadas (dia 0, 1, 3) baseadas na mensagem original do lead'}},
      {{ico:'💾', title:'CRM Persistente', desc:'Mantém histórico completo em crm_leads.json com todos os contatos e interações'}}
    ],
    inputs:['Nome e mensagem do lead','Fonte (Instagram, stories, etc.)','Produto de interesse'],
    outputs:['crm_leads.json atualizado','Score + temperatura','Sequência de follow-up','Estágio do pipeline']
  }},
  scaling: {{
    icon:'🚀', name:'Scaling Engine', tag:'Decisão de Escala', color:'#c060ff',
    desc:'Decide quando e como escalar um produto com base em dados reais de performance, validação e conversão. Gera plano de 7 dias com ações concretas.',
    funcs:[
      {{ico:'📊', title:'Scaling Score', desc:'Combina performance_score (40%) + validation_score (40%) + conversion_rate (20%) → 0-100'}},
      {{ico:'⚡', title:'Decisão Automática', desc:'Scale (≥75) → escalar agora | Optimize (≥50) → otimizar primeiro | Stop (<50) → pausar'}},
      {{ico:'🤖', title:'Análise Claude', desc:'Identifica o que repetir, o que matar e quais ações específicas de escala executar'}},
      {{ico:'📅', title:'Plano 7 Dias', desc:'Gera plano de ação diário concreto com prioridades e KPIs esperados'}}
    ],
    inputs:['performance_*.json','validation_*.json','Dados de conversão/vendas'],
    outputs:['scaling_*.json','Score de escala','Decisão scale/optimize/stop','Plano 7 dias']
  }},
  financial: {{
    icon:'💰', name:'Financial Engine', tag:'Receita & Margem', color:'#ffb800',
    desc:'Analisa a saúde financeira do negócio: calcula margem por produto, projeta receita futura e monitora custos mensais com decisões automáticas.',
    funcs:[
      {{ico:'💲', title:'Margem por Produto', desc:'Custo de criação + aquisição + operacional vs. receita → margem % + decisão'}},
      {{ico:'📊', title:'Custos Mensais', desc:'Categoriza e monitora gastos mensais (IA, Ads, Plataforma, Infra, Ferramentas)'}},
      {{ico:'📈', title:'Projeção de Receita', desc:'Leads × Conversão × Ticket médio → projeção mensal com meta vs. real'}},
      {{ico:'⚡', title:'Decisões Automáticas', desc:'Margem baixa → reduzir custo | Custo alto → otimizar ads | Alta margem → ESCALAR'}}
    ],
    inputs:['Custos de criação/aquisição/operação','Preço de venda','Leads e conversão'],
    outputs:['financial_data.json','Margem %','Projeção mensal','Recomendação financeira']
  }},
  growth: {{
    icon:'📈', name:'Growth Simulator', tag:'Cenários de Crescimento', color:'#5b9cff',
    desc:'Simula 6 cenários de crescimento alterando alavancas (leads, conversão, ticket) para identificar o caminho de maior impacto no lucro.',
    funcs:[
      {{ico:'🎲', title:'6 Cenários Automáticos', desc:'Base, Dobrar Leads, Melhorar Conversão, Aumentar Ticket, Combo Leve, Combo Agressivo'}},
      {{ico:'🏆', title:'Ranking por Impacto', desc:'Ordena cenários por lucro gerado e identifica a alavanca de maior retorno'}},
      {{ico:'📊', title:'Break-even Analysis', desc:'Calcula ponto de equilíbrio e meses para atingir meta financeira em cada cenário'}},
      {{ico:'🤖', title:'Recomendação Claude', desc:'Analisa o melhor cenário e gera plano de ação para atingir as metas projetadas'}}
    ],
    inputs:['Leads atuais','Taxa de conversão','Ticket médio','Custo mensal'],
    outputs:['simulations.json','Ranking de cenários','Melhor alavanca','Plano de ação']
  }}
}};

function openOrg(key) {{
  const d = ORG_DATA[key];
  if(!d) return;
  document.getElementById('orgModalIcon').textContent = d.icon;
  document.getElementById('orgModalTitle').textContent = d.name;
  const tag = document.getElementById('orgModalTag');
  tag.textContent = d.tag;
  tag.style.cssText = 'background:'+d.color+'22;color:'+d.color+';border:1px solid '+d.color+'44;font-size:9px;font-weight:700;padding:3px 10px;border-radius:10px;margin-top:4px;display:inline-block';
  document.getElementById('orgModalDesc').textContent = d.desc;
  const fl = document.getElementById('orgModalFuncs');
  fl.innerHTML = d.funcs.map(f =>
    '<div class="org-func-item" style="--node-color:'+d.color+'">'+
    '<div class="org-func-ico">'+f.ico+'</div>'+
    '<div class="org-func-text"><strong>'+f.title+'</strong>'+f.desc+'</div>'+
    '</div>'
  ).join('');
  const io = document.getElementById('orgModalIO');
  io.innerHTML = '<div class="org-io-row">'+
    '<div class="org-io"><div class="org-io-label">📥 Entradas</div><div class="org-io-items">'+d.inputs.map(i=>'• '+i).join('<br>')+'</div></div>'+
    '<div class="org-io"><div class="org-io-label">📤 Saídas</div><div class="org-io-items">'+d.outputs.map(o=>'• '+o).join('<br>')+'</div></div>'+
    '</div>';
  document.getElementById('orgModalOverlay').classList.add('open');
  document.body.style.overflow='hidden';
}}
function closeOrg(e) {{ if(e.target===document.getElementById('orgModalOverlay')) closeOrgBtn(); }}
function closeOrgBtn() {{
  document.getElementById('orgModalOverlay').classList.remove('open');
  document.body.style.overflow='';
}}
document.addEventListener('keydown', e => {{ if(e.key==='Escape') closeOrgBtn(); }});

// Active nav link on scroll
const sections = document.querySelectorAll('[id]');
const links = document.querySelectorAll('.sb-link');
window.addEventListener('scroll', () => {{
  let cur='';
  sections.forEach(s => {{ if(window.scrollY >= s.offsetTop - 80) cur = s.id; }});
  links.forEach(l => {{ l.classList.toggle('active', l.getAttribute('href')==='#'+cur); }});
}}, {{passive:true}});

// ── MOBILE DRAWER ─────────────────────────────────────────
function toggleSidebar() {{
  const sb = document.getElementById('sidebar');
  const hb = document.getElementById('hamburger');
  const ov = document.getElementById('overlay');
  const open = sb.classList.toggle('open');
  hb.classList.toggle('open', open);
  ov.classList.toggle('show', open);
  document.body.style.overflow = open ? 'hidden' : '';
}}
function closeSidebar() {{
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('hamburger').classList.remove('open');
  document.getElementById('overlay').classList.remove('show');
  document.body.style.overflow = '';
}}
document.querySelectorAll('.sb-link').forEach(l => {{
  l.addEventListener('click', () => {{ if(window.innerWidth <= 900) closeSidebar(); }});
}});
</script>
</body>
</html>"""


def main():
    s = load_scorings()
    o = load_others()
    bp = load_blueprints()
    ct = load_contents()
    vd = load_videos()
    fn = load_funnels()
    pf = load_performances()
    mem = load_memory_items()
    vl = load_validations()
    crm = load_crm_leads()
    sc = load_scaling_decisions()
    ss = load_sessions()
    ads = load_ads_campaigns()
    fin = load_financial_data()
    sims = load_simulations()
    sec = load_security_data()
    html = generate(s, o, bp, ct, vd, fn, pf, mem, vl, crm, sc, ss, ads, fin, sims, sec)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  Dashboard gerado: {OUTPUT_FILE}")
    print(f"  Oportunidades : {len(s)}")
    print(f"  Blueprints    : {len(bp)}")
    print(f"  Conteúdos     : {len(ct)}")
    print(f"  Vídeos        : {len(vd)}")
    print(f"  Funis         : {len(fn)}")
    print(f"  Leads CRM     : {len(crm)}")
    print(f"  Scalings      : {len(sc)}")
    print(f"  Sessões OS    : {len(ss)}")
    print(f"  Validações    : {len(vl)}")
    print(f"  Performances  : {len(pf)}")
    print(f"  Memória       : {len(mem)} padrões")
    print(f"  Campanhas Ads : {len(ads)}")
    fin_rev = (fin.get("projections") or [{}])[-1].get("monthly_revenue", 0)
    print(f"  Receita/mês   : R${fin_rev:,.2f}")
    print(f"  Simulações    : {len(sims)}")
    print(f"  Outros outputs: {len(o)}")
    print(f"\n  open {os.path.abspath(OUTPUT_FILE)}\n")


if __name__ == "__main__":
    main()
