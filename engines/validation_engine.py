#!/usr/bin/env python3
"""
Validation Engine — Pipeline AI
Transforma conteúdo publicado em decisão de negócio: escalar, ajustar ou descartar.

Fluxo:
  Validation Input
  → Collect Signals     (input)   — views, likes, comments, saves, shares, clicks, DMs, leads
  → Normalize Signals   (lógica)  — calcula engagement, click_rate, dm_rate, lead_rate
  → Interest Scoring    (lógica)  — validation_score 0-100 + status (forte/medio/fraco)
  → Claude Analysis     (Claude)  — interesse real, sinal de público, força do problema
  → Save Validation     (local)   — persiste JSON
  → Decision Engine     (lógica)  — escalar / ajustar / descartar
  → Output              (terminal + Notion + Dashboard)

Regra mais importante: NÃO ESCALAR SEM VALIDAÇÃO.

Uso:
  python validation_engine.py --json '{"idea_title":"CFO Digital","video_id":12,...}'
  python validation_engine.py --title "CFO Digital" --views 12000 --likes 650 ...
  python validation_engine.py --ranking          # exibe ranking de validações
  python validation_engine.py                    # modo interativo
"""
import asyncio, json, os, sys, time, glob
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-6"
OUTPUTS_DIR       = "outputs"

# Pesos do interest score (somam 100 ao multiplicar pelas taxas em %)
SCORE_WEIGHTS = {
    "engagement": 40,
    "click_rate": 25,
    "dm_rate":    20,
    "lead_rate":  15,
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


async def _claude(prompt: str, max_tokens: int = 1200) -> tuple[dict, dict]:
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

def _p_validation_analysis(signals: dict) -> str:
    return f"""Você é um especialista em validação de mercado e marketing digital.

Analise essa validação de mercado:

Produto: {signals.get('idea_title', '')}
Plataforma: {signals.get('platform', '')}

Dados de engajamento:
- Views         : {signals.get('views', 0):,}
- Likes         : {signals.get('likes', 0):,}
- Comentários   : {signals.get('comments', 0):,}
- Saves         : {signals.get('saves', 0):,}
- Shares        : {signals.get('shares', 0):,}
- Clicks        : {signals.get('clicks', 0):,}
- DMs recebidos : {signals.get('dm_requests', 0):,}
- Leads         : {signals.get('leads', 0):,}

Taxas calculadas:
- Engajamento  : {signals.get('engagement', 0)*100:.2f}%
- Click Rate   : {signals.get('click_rate', 0)*100:.2f}%
- DM Rate      : {signals.get('dm_rate', 0)*100:.2f}%
- Lead Rate    : {signals.get('lead_rate', 0)*100:.2f}%

Validation Score: {signals.get('validation_score', 0)}/100 ({signals.get('validation_status', '')})

Responda analisando:
1. Isso indica interesse real de compra?
2. Qual tipo de público respondeu melhor?
3. O problema parece forte o suficiente para monetizar?
4. Vale escalar (mais conteúdo + oferta direta), ajustar (gancho/narrativa) ou descartar?
5. O que mudar no próximo conteúdo para aumentar conversão?

Responda APENAS em JSON válido:

{{
  "real_interest": true,
  "audience_signal": "",
  "problem_strength": "",
  "decision": "escalar",
  "next_action": "",
  "reasoning": ""
}}

Valores válidos para "decision": "escalar", "ajustar", "descartar"."""


# ─── Etapas do pipeline ───────────────────────────────────────────────────────

def _normalize(raw: dict) -> dict:
    """Node 03 — calcula engagement, click_rate, dm_rate, lead_rate."""
    views       = raw.get("views", 0) or 0
    likes       = raw.get("likes", 0) or 0
    comments    = raw.get("comments", 0) or 0
    saves       = raw.get("saves", 0) or 0
    shares      = raw.get("shares", 0) or 0
    clicks      = raw.get("clicks", 0) or 0
    dm_requests = raw.get("dm_requests", 0) or 0
    leads       = raw.get("leads", 0) or 0

    engagement = ((likes + comments + saves + shares) / views) if views > 0 else 0.0
    click_rate = (clicks / views) if views > 0 else 0.0
    dm_rate    = (dm_requests / views) if views > 0 else 0.0
    lead_rate  = (leads / views) if views > 0 else 0.0

    return {
        **raw,
        "engagement": round(engagement, 6),
        "click_rate": round(click_rate, 6),
        "dm_rate":    round(dm_rate, 6),
        "lead_rate":  round(lead_rate, 6),
    }


def _interest_score(signals: dict) -> dict:
    """Node 04 — calcula validation_score (0-100) e validation_status."""
    score = (
        signals.get("engagement", 0) * SCORE_WEIGHTS["engagement"] +
        signals.get("click_rate", 0) * SCORE_WEIGHTS["click_rate"] +
        signals.get("dm_rate",    0) * SCORE_WEIGHTS["dm_rate"] +
        signals.get("lead_rate",  0) * SCORE_WEIGHTS["lead_rate"]
    ) * 100  # converte taxas (0-1) para pontuação percentual

    score = min(round(score), 100)

    if score >= 70:
        status = "forte"
    elif score >= 40:
        status = "medio"
    else:
        status = "fraco"

    return {**signals, "validation_score": score, "validation_status": status}


def _decision(signals: dict) -> str:
    """Node 07 — decisão final baseada no validation_score."""
    score = signals.get("validation_score", 0)
    if score >= 70:
        return "escalar"
    elif score >= 40:
        return "ajustar"
    return "descartar"


# ─── Fluxo principal ──────────────────────────────────────────────────────────

async def run_validation(raw_input: dict) -> dict:
    title = raw_input.get("idea_title", raw_input.get("title", "?"))
    print(f"\n  Validando: {title[:60]}")
    print(f"  Plataforma: {raw_input.get('platform','?')} · "
          f"video_id={raw_input.get('video_id','?')}")
    print("  " + "─" * 56)

    # [1] Normalize
    print("  [1/5] Collecting & normalizing signals...")
    signals = _normalize(raw_input)
    print(f"        ✓ eng {signals['engagement']*100:.2f}% · "
          f"click {signals['click_rate']*100:.2f}% · "
          f"DM {signals['dm_rate']*100:.2f}% · "
          f"lead {signals['lead_rate']*100:.2f}%")

    # [2] Interest Score
    print("  [2/5] Interest Scoring...")
    signals = _interest_score(signals)
    STATUS_ICON = {"forte": "🟢", "medio": "🟡", "fraco": "🔴"}
    icon = STATUS_ICON.get(signals["validation_status"], "⚪")
    print(f"        ✓ score {signals['validation_score']}/100 → "
          f"{icon} {signals['validation_status'].upper()}")

    # [3] Claude Validation Analysis
    print("  [3/5] Claude Validation Analysis...")
    signals["timestamp"] = time.strftime("%Y%m%d_%H%M%S")
    analysis_raw, meta = await _claude(_p_validation_analysis(signals))
    analysis = analysis_raw if isinstance(analysis_raw, dict) else {}
    print(f"        ✓ decisão: {analysis.get('decision','?')} · "
          f"{meta['latency_ms']}ms · ${meta['cost']:.4f}")

    # [4] Decision Engine
    print("  [4/5] Decision Engine...")
    final_action = _decision(signals)
    # Claude pode ter corrigido a decisão com mais contexto — usa a do Claude se consistente
    claude_decision = analysis.get("decision", "").lower()
    if claude_decision in ("escalar", "ajustar", "descartar"):
        final_action = claude_decision
    print(f"        ✓ AÇÃO FINAL: {final_action.upper()}")

    # [5] Save + Output
    print("  [5/5] Saving validation record...")
    result = {
        "idea_title":       title,
        "video_id":         raw_input.get("video_id", ""),
        "platform":         raw_input.get("platform", ""),
        "signals":          signals,
        "analysis":         analysis,
        "final_action":     final_action,
        "cost":             meta["cost"],
        "timestamp":        signals["timestamp"],
        "response": {
            "status":            "success",
            "idea_title":        title,
            "validation_score":  signals["validation_score"],
            "validation_status": signals["validation_status"],
            "real_interest":     analysis.get("real_interest", False),
            "decision":          final_action,
            "next_action":       analysis.get("next_action", ""),
        },
    }

    fname = _salvar_local(result)
    print(f"        ✓ Salvo em {fname}")

    _imprimir(result)
    await _salvar_notion(result)
    _atualizar_dashboard()

    return result


# ─── Ranking ──────────────────────────────────────────────────────────────────

def show_ranking():
    files = sorted(glob.glob(f"{OUTPUTS_DIR}/validation_*.json"), reverse=True)
    if not files:
        print("  Nenhum registro de validação encontrado.")
        print("  Rode: python validation_engine.py --json '{...}'")
        return

    records = []
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            records.append(data)
        except Exception:
            pass

    records.sort(key=lambda x: x.get("signals", {}).get("validation_score", 0), reverse=True)

    ACTION_ICON = {"escalar": "🚀 ESCALAR", "ajustar": "🔧 AJUSTAR", "descartar": "🗑  DESCARTAR"}
    STATUS_COLOR = {"forte": "🟢", "medio": "🟡", "fraco": "🔴"}

    print("\n" + "═" * 70)
    print("  VALIDATION RANKING — Pipeline AI")
    print("═" * 70)
    print(f"  {'#':<3} {'Score':<7} {'Status':<8} {'Ação':<14} Produto")
    print("  " + "─" * 64)
    for i, r in enumerate(records[:20], 1):
        s      = r.get("signals", {})
        score  = s.get("validation_score", 0)
        status = s.get("validation_status", "fraco")
        action = r.get("final_action", "descartar")
        title  = r.get("idea_title", "?")[:36]
        print(f"  {i:<3} {score:<7} {STATUS_COLOR.get(status,'')} {status:<6} "
              f"{ACTION_ICON.get(action, action):<14} {title}")

    escalares  = sum(1 for r in records if r.get("final_action") == "escalar")
    ajustar    = sum(1 for r in records if r.get("final_action") == "ajustar")
    descartar  = sum(1 for r in records if r.get("final_action") == "descartar")

    print("═" * 70)
    print(f"\n  Total: {len(records)}  |  🚀 Escalar: {escalares}  |  "
          f"🔧 Ajustar: {ajustar}  |  🗑  Descartar: {descartar}\n")


# ─── Persistência ─────────────────────────────────────────────────────────────

def _salvar_local(result: dict) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    slug  = result["idea_title"].replace(" ", "_")[:28]
    fname = f"{OUTPUTS_DIR}/validation_{slug}_{result['timestamp']}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return fname


async def _salvar_notion(result: dict):
    try:
        from integrations.notion_logger import salvar_tarefa
        s   = result.get("signals", {})
        a   = result.get("analysis", {})
        body = (
            f"Score: {s.get('validation_score',0)}/100 ({s.get('validation_status','')})\n"
            f"Decisão: {result.get('final_action','').upper()}\n\n"
            f"Interesse real: {'Sim' if a.get('real_interest') else 'Não'}\n"
            f"Sinal de público: {a.get('audience_signal','')}\n"
            f"Força do problema: {a.get('problem_strength','')}\n\n"
            f"Próxima ação: {a.get('next_action','')}"
        )
        await salvar_tarefa(
            f"Validação: {result['idea_title'][:50]} → {result.get('final_action','').upper()}",
            "validation_engine",
            body,
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
    s   = result["signals"]
    a   = result.get("analysis", {})
    act = result["final_action"]

    ACTION_BLOCK = {
        "escalar":   ("🚀  ESCALAR", "#10b981",
                      ["Aumentar frequência de conteúdo",
                       "Lançar oferta direta",
                       "Iniciar sequência de vendas"]),
        "ajustar":   ("🔧  AJUSTAR", "#f59e0b",
                      ["Mudar gancho do próximo vídeo",
                       "Refinar a narrativa",
                       "Testar nova promessa"]),
        "descartar": ("🗑   DESCARTAR", "#ef4444",
                      ["Não insistir neste ângulo",
                       "Voltar para o Opportunity Engine",
                       "Testar nova ideia"]),
    }

    label, _, steps = ACTION_BLOCK.get(act, (act.upper(), "#888", []))

    print("\n" + "═" * 62)
    print(f"  VALIDATION ENGINE — {result['idea_title'][:38]}")
    print("═" * 62)

    print(f"\n  Score       : {s['validation_score']}/100")
    print(f"  Status      : {s['validation_status'].upper()}")
    print(f"\n  Views       : {s.get('views',0):>8,}")
    print(f"  Likes       : {s.get('likes',0):>8,}  (eng {s['engagement']*100:.2f}%)")
    print(f"  Comments    : {s.get('comments',0):>8,}")
    print(f"  Saves       : {s.get('saves',0):>8,}")
    print(f"  Shares      : {s.get('shares',0):>8,}")
    print(f"  Clicks      : {s.get('clicks',0):>8,}  (CTR {s['click_rate']*100:.2f}%)")
    print(f"  DMs         : {s.get('dm_requests',0):>8,}  (DM  {s['dm_rate']*100:.2f}%)")
    print(f"  Leads       : {s.get('leads',0):>8,}  (conv {s['lead_rate']*100:.2f}%)")

    print(f"\n  Interesse real   : {'SIM' if a.get('real_interest') else 'NÃO'}")
    if a.get("audience_signal"):
        print(f"  Sinal de público : {a['audience_signal']}")
    if a.get("problem_strength"):
        print(f"  Força do problema: {a['problem_strength']}")
    if a.get("reasoning"):
        print(f"\n  Raciocínio: {a['reasoning'][:120]}")

    print(f"\n  {'─'*58}")
    print(f"  DECISÃO FINAL: {label}")
    print(f"  {'─'*58}")
    for step in steps:
        print(f"  → {step}")
    if a.get("next_action"):
        print(f"\n  Próxima ação específica:")
        print(f"  {a['next_action'][:120]}")

    print(f"\n  Custo análise : ~${result.get('cost',0):.4f}")
    print("═" * 62 + "\n")

    print("  Response (Node 08):")
    print(json.dumps(result["response"], ensure_ascii=False, indent=2))
    print()


# ─── Modo interativo ──────────────────────────────────────────────────────────

def _interactive_input() -> dict:
    print("\n  ─── Validation Engine — Entrada de dados ────────────────")
    title    = input("  Produto/ideia          : ").strip()
    platform = input("  Plataforma (instagram) : ").strip() or "instagram"
    video_id = input("  Video ID (ou nome)     : ").strip() or "1"
    views    = int(input("  Views       : ").strip() or 0)
    likes    = int(input("  Likes       : ").strip() or 0)
    comments = int(input("  Comentários : ").strip() or 0)
    saves    = int(input("  Saves       : ").strip() or 0)
    shares   = int(input("  Shares      : ").strip() or 0)
    clicks   = int(input("  Clicks      : ").strip() or 0)
    dms      = int(input("  DMs recebidos: ").strip() or 0)
    leads    = int(input("  Leads       : ").strip() or 0)
    return {
        "idea_title": title, "platform": platform, "video_id": video_id,
        "views": views, "likes": likes, "comments": comments,
        "saves": saves, "shares": shares, "clicks": clicks,
        "dm_requests": dms, "leads": leads,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

async def main():
    args = sys.argv[1:]

    if "--ranking" in args:
        show_ranking()
        return

    raw_input: Optional[dict] = None

    if "--json" in args:
        idx       = args.index("--json")
        raw_input = json.loads(args[idx + 1])

    elif "--title" in args:
        idx   = args.index("--title")
        title = args[idx + 1] if idx + 1 < len(args) else ""

        def _arg(flag: str, default=0):
            if flag in args:
                i = args.index(flag)
                return args[i + 1] if i + 1 < len(args) else default
            return default

        raw_input = {
            "idea_title":   title,
            "video_id":     str(_arg("--video-id", "1")),
            "platform":     str(_arg("--platform", "instagram")),
            "views":        int(_arg("--views", 0)),
            "likes":        int(_arg("--likes", 0)),
            "comments":     int(_arg("--comments", 0)),
            "saves":        int(_arg("--saves", 0)),
            "shares":       int(_arg("--shares", 0)),
            "clicks":       int(_arg("--clicks", 0)),
            "dm_requests":  int(_arg("--dms", 0)),
            "leads":        int(_arg("--leads", 0)),
        }

    else:
        raw_input = _interactive_input()

    if not raw_input or not raw_input.get("idea_title"):
        print("  idea_title obrigatório.")
        return

    await run_validation(raw_input)


if __name__ == "__main__":
    asyncio.run(main())
