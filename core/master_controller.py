#!/usr/bin/env python3
"""
Master Controller — AI Business OS
Orquestra todo o sistema em 11 nós: do input ao loop de aprendizado.

Arquitetura em camadas:
  CAMADA 1 — INPUT       : ideia manual, tema, comando estratégico
  CAMADA 2 — CORE ENGINE : Opportunity + Scoring + Decision
  CAMADA 3 — EXECUÇÃO    : Product → Content → Video → Sales
  CAMADA 4 — INTELIGÊNCIA: Performance → Validation → Scaling → Memory
  CAMADA 5 — OUTPUT      : conteúdo, vídeos, leads, insights

11 nós do pipeline:
  01_Input → 02_Context_Load → 03_Objective_Definition → 04_Opportunity_Check
  → 05_Scoring → 06_Decision → 07_Execute_Path → 08_Distribute
  → 09_Collect_Feedback → 10_Learn → 11_Repeat

3 modos de operação:
  --mode auto      → sistema roda sozinho (zero interrupções)
  --mode semi_auto → pausa nas decisões críticas (default)
  --mode manual    → pausa em cada nó

Uso:
  python master_controller.py
  python master_controller.py --objective "criar produto para restaurantes" --market "restaurantes"
  python master_controller.py --mode auto --objective "CFO Digital"
  python master_controller.py --mode manual
  python master_controller.py --resume SESSION_ID
  python master_controller.py --status          # lista sessões anteriores
"""
import asyncio, json, os, sys, time, glob
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-6"
OUTPUTS_DIR       = "outputs"
SESSIONS_DIR      = os.path.join(OUTPUTS_DIR, "sessions")

# ─── Helpers de API ───────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s != -1 and e > s:
            try:
                return json.loads(raw[s:e])
            except Exception:
                pass
        return {"raw": raw}


async def _claude(prompt: str, max_tokens: int = 1000) -> tuple[dict, float]:
    if not ANTHROPIC_API_KEY or "sua-chave" in ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY não configurada")
    payload = {
        "model": CLAUDE_MODEL, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    raw = data.get("content", [{}])[0].get("text", "")
    u   = data.get("usage", {})
    cost = round((u.get("input_tokens", 0) * 3e-6) + (u.get("output_tokens", 0) * 15e-6), 6)
    return _parse_json(raw), cost


# ─── Session ──────────────────────────────────────────────────────────────────

class Session:
    def __init__(self, session_id: str, mode: str, objective: str, market: str):
        self.id         = session_id
        self.mode       = mode          # auto / semi_auto / manual
        self.objective  = objective
        self.market     = market
        self.state: dict = {
            "status":      "running",
            "current_node": "01_Input",
            "nodes_done":  [],
            "total_cost":  0.0,
            "started_at":  time.strftime("%Y-%m-%d %H:%M:%S"),
            "results":     {},
        }

    def checkpoint(self, node: str, data: dict, cost: float = 0.0):
        self.state["current_node"] = node
        self.state["nodes_done"].append(node)
        self.state["total_cost"] = round(self.state["total_cost"] + cost, 6)
        self.state["results"][node] = data
        self._save()

    def _save(self):
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        path = os.path.join(SESSIONS_DIR, f"session_{self.id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "session_id": self.id,
                "mode":       self.mode,
                "objective":  self.objective,
                "market":     self.market,
                **self.state,
            }, f, ensure_ascii=False, indent=2)

    def finish(self, status: str = "completed"):
        self.state["status"]      = status
        self.state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._save()


# ─── UI helpers ───────────────────────────────────────────────────────────────

MODE_COLORS = {"auto": "🤖 AUTO", "semi_auto": "🧑‍💻 SEMI-AUTO", "manual": "👤 MANUAL"}

def _header(session: Session):
    print("\n" + "═" * 66)
    print(f"  AI BUSINESS OS — Master Controller")
    print(f"  Sessão  : {session.id}")
    print(f"  Modo    : {MODE_COLORS.get(session.mode, session.mode)}")
    print(f"  Objetivo: {session.objective[:56]}")
    if session.market:
        print(f"  Mercado : {session.market}")
    print("═" * 66)


def _node(num: str, name: str):
    print(f"\n  ┌─ Nó {num} — {name} {'─'*(46-len(name)-len(num))}")


def _ok(msg: str, cost: float = 0.0):
    suffix = f" · ${cost:.4f}" if cost > 0 else ""
    print(f"  │  ✓ {msg}{suffix}")


def _pause(session: Session, node: str, message: str) -> bool:
    """
    Pausa dependendo do modo.
    manual    → pausa em todo nó
    semi_auto → pausa apenas nos nós críticos (06_Decision, 07_Execute_Path)
    auto      → nunca pausa
    Retorna True para continuar, False para abortar.
    """
    CRITICAL = {"06_Decision", "07_Execute_Path"}
    should_pause = (
        session.mode == "manual" or
        (session.mode == "semi_auto" and node in CRITICAL)
    )
    if not should_pause:
        return True

    print(f"\n  ┌─ PAUSA [{node}] ─────────────────────────────────────────")
    print(f"  │  {message}")
    print(f"  └─ [ENTER] continuar  [s] pular  [q] abortar ──────────────")
    resp = input("  > ").strip().lower()
    if resp == "q":
        return False
    return True


# ─── Prompts ──────────────────────────────────────────────────────────────────

def _p_objective_definition(objective: str, market: str, context: dict) -> str:
    ctx_lines = []
    if context.get("existing_opportunities"):
        ctx_lines.append(f"Oportunidades já avaliadas: {len(context['existing_opportunities'])}")
    if context.get("existing_blueprints"):
        ctx_lines.append(f"Produtos já criados: {', '.join(context['existing_blueprints'][:3])}")
    if context.get("memory_patterns"):
        ctx_lines.append(f"Padrões vencedores em memória: {len(context['memory_patterns'])}")
    if context.get("best_validation"):
        ctx_lines.append(f"Melhor validação anterior: {context['best_validation']}")

    ctx_text = "\n".join(ctx_lines) if ctx_lines else "Nenhum histórico encontrado."

    return f"""Você é o cérebro estratégico de um sistema de negócio com IA.

Objetivo recebido: "{objective}"
Mercado/nicho: "{market}"

Contexto do sistema (outputs existentes):
{ctx_text}

Defina com precisão:
1. Tipo de tarefa (novo_produto / novo_conteudo / validar_existente / escalar_vencedor / pesquisa_mercado)
2. Objetivo real (o que de fato precisa acontecer)
3. Caminho ideal (sequência de engines a executar)
4. Se já existe algo aproveitável no histórico

Responda APENAS em JSON válido:

{{
  "task_type": "",
  "real_objective": "",
  "execution_path": [],
  "reuse_existing": false,
  "reuse_title": "",
  "reasoning": "",
  "estimated_engines": 0
}}

Valores válidos para execution_path: "opportunity", "product", "content", "video", "sales", "validation", "performance", "scaling", "crm"
Valores válidos para task_type: "novo_produto", "novo_conteudo", "validar_existente", "escalar_vencedor", "pesquisa_mercado"
"""


def _p_learn(session: Session, results: dict) -> str:
    summary = []
    if results.get("05_Scoring"):
        s = results["05_Scoring"]
        summary.append(f"Oportunidade avaliada: {s.get('idea_title','')} — score {s.get('final_score',0)}")
    if results.get("07_Execute_Path"):
        ep = results["07_Execute_Path"]
        summary.append(f"Engines executados: {', '.join(ep.get('engines_run', []))}")
    if results.get("09_Collect_Feedback"):
        fb = results["09_Collect_Feedback"]
        summary.append(f"Performance score: {fb.get('performance_score',0)} · Validation: {fb.get('validation_score',0)}")

    return f"""Sessão do AI Business OS concluída.

Objetivo: {session.objective}
Mercado: {session.market}
Modo: {session.mode}

Resultados desta sessão:
{chr(10).join(summary) or 'Sem resultados coletados'}

Gere os aprendizados para atualizar a memória do sistema:

Responda APENAS em JSON válido:

{{
  "session_insight": "",
  "patterns_to_remember": [],
  "what_to_avoid": [],
  "next_session_recommendation": "",
  "memory_tags": []
}}"""


# ─── Context Loader ───────────────────────────────────────────────────────────

def _load_context() -> dict:
    ctx: dict = {}

    # oportunidades existentes
    scoring_files = glob.glob(f"{OUTPUTS_DIR}/scoring_*.json")
    if scoring_files:
        scores = []
        for p in scoring_files:
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                out = d.get("output", {})
                if out.get("idea_title"):
                    scores.append({"title": out["idea_title"], "score": out.get("final_score", 0)})
            except Exception:
                pass
        ctx["existing_opportunities"] = sorted(scores, key=lambda x: -x["score"])

    # blueprints existentes
    bp_files = glob.glob(f"{OUTPUTS_DIR}/blueprint_*.json")
    if bp_files:
        bps = []
        for p in bp_files:
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                bp = d.get("blueprint", {})
                if bp.get("idea_title"):
                    bps.append(bp["idea_title"])
            except Exception:
                pass
        ctx["existing_blueprints"] = bps

    # padrões de memória
    mem_file = os.path.join(OUTPUTS_DIR, "memory_items.json")
    if os.path.exists(mem_file):
        try:
            with open(mem_file, encoding="utf-8") as f:
                mem = json.load(f)
            ctx["memory_patterns"] = mem[:10]
        except Exception:
            pass

    # melhor validação
    val_files = sorted(glob.glob(f"{OUTPUTS_DIR}/validation_*.json"), reverse=True)
    if val_files:
        try:
            with open(val_files[0], encoding="utf-8") as f:
                d = json.load(f)
            s = d.get("signals", {})
            ctx["best_validation"] = (
                f"{d.get('idea_title','')} score {s.get('validation_score',0)} → {d.get('final_action','')}"
            )
        except Exception:
            pass

    return ctx


# ─── Update Memory ────────────────────────────────────────────────────────────

def _update_memory(session_insights: dict, session: Session):
    mem_file = os.path.join(OUTPUTS_DIR, "memory_items.json")
    items = []
    if os.path.exists(mem_file):
        try:
            with open(mem_file, encoding="utf-8") as f:
                items = json.load(f)
        except Exception:
            pass

    entry = {
        "session_id":    session.id,
        "timestamp":     time.strftime("%Y%m%d_%H%M%S"),
        "objective":     session.objective,
        "market":        session.market,
        "insight":       session_insights.get("session_insight", ""),
        "repeat":        session_insights.get("patterns_to_remember", []),
        "avoid":         session_insights.get("what_to_avoid", []),
        "tags":          session_insights.get("memory_tags", []),
        "next_session":  session_insights.get("next_session_recommendation", ""),
        "performance_score": 0,
        "performance_band":  "media",
        "asset_type":    "session",
        "platform":      "master",
        "gancho":        "",
    }
    items.append(entry)
    items = items[-50:]  # mantém os 50 mais recentes

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    with open(mem_file, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print(f"  │  ✓ Memória atualizada: {len(items)} entradas")


# ─── Engine runners ───────────────────────────────────────────────────────────

async def _run_opportunity(session: Session, objective: str, market: str) -> Optional[dict]:
    try:
        from opportunity_scorer import score_opportunity
        opportunity = {
            "idea_title":       objective,
            "idea_description": f"Oportunidade no mercado de {market}",
            "target_market":    market,
            "problem":          f"Dor principal do mercado de {market}",
            "solution":         objective,
        }
        result = await score_opportunity(opportunity)
        out = result.get("output", {})
        _ok(f"Score: {out.get('final_score',0)}/100 · Prioridade: {out.get('priority','')}")
        return out
    except Exception as e:
        print(f"  │  ⚠ Opportunity Engine: {e}")
        return None


async def _run_product(session: Session, winner: dict) -> Optional[dict]:
    try:
        from engines.product_engine import build_product
        result = await build_product(winner)
        _ok(f"Blueprint criado: {result.get('idea_title','')[:40]}", result.get("total_cost", 0))
        return result.get("blueprint", result)
    except Exception as e:
        print(f"  │  ⚠ Product Engine: {e}")
        return None


async def _run_content(session: Session, blueprint: dict) -> Optional[dict]:
    try:
        from engines.content_engine import build_content
        result = await build_content(blueprint)
        s = result.get("summary", {})
        _ok(f"{s.get('angles',0)} ângulos · {s.get('hooks',0)} ganchos · {s.get('posts',0)} posts",
            result.get("total_cost", 0))
        return result
    except Exception as e:
        print(f"  │  ⚠ Content Engine: {e}")
        return None


async def _run_video(session: Session, content: dict) -> Optional[dict]:
    try:
        from engines.video_engine import build_video
        result = await build_video(content, script_only=True)
        _ok(f"Scripts gerados · status: {result.get('response',{}).get('status','?')}",
            result.get("total_cost", 0))
        return result
    except Exception as e:
        print(f"  │  ⚠ Video Engine: {e}")
        return None


async def _run_sales(session: Session, blueprint: dict) -> Optional[dict]:
    try:
        from engines.sales_engine import build_funnel
        result = await build_funnel(blueprint)
        _ok(f"Funil criado · {len(result.get('ctas',[]))} CTAs · {len(result.get('sequence',[]))} msgs",
            result.get("total_cost", 0))
        return result
    except Exception as e:
        print(f"  │  ⚠ Sales Engine: {e}")
        return None


# ─── Nós do pipeline ──────────────────────────────────────────────────────────

async def node_01_input(session: Session) -> dict:
    _node("01", "Input")
    data = {"objective": session.objective, "market": session.market, "mode": session.mode}
    _ok(f"Objetivo: {session.objective[:50]}")
    _ok(f"Mercado: {session.market or 'não especificado'}")
    _ok(f"Modo: {session.mode}")
    session.checkpoint("01_Input", data)
    return data


async def node_02_context_load(session: Session) -> dict:
    _node("02", "Context Load")
    ctx = _load_context()

    n_opp = len(ctx.get("existing_opportunities", []))
    n_bp  = len(ctx.get("existing_blueprints", []))
    n_mem = len(ctx.get("memory_patterns", []))

    _ok(f"{n_opp} oportunidades · {n_bp} blueprints · {n_mem} padrões em memória")

    if ctx.get("existing_opportunities"):
        best = ctx["existing_opportunities"][0]
        _ok(f"Melhor oportunidade anterior: {best['title']} (score {best['score']})")

    session.checkpoint("02_Context_Load", ctx)
    return ctx


async def node_03_objective_definition(session: Session, context: dict) -> dict:
    _node("03", "Objective Definition")
    definition, cost = await _claude(
        _p_objective_definition(session.objective, session.market, context),
        max_tokens=800,
    )
    task_type = definition.get("task_type", "novo_produto")
    path      = definition.get("execution_path", ["opportunity", "product", "content"])
    _ok(f"Tarefa: {task_type}", cost)
    _ok(f"Caminho: {' → '.join(path)}")
    if definition.get("reuse_existing") and definition.get("reuse_title"):
        _ok(f"Reaproveita: {definition['reuse_title']}")
    if definition.get("reasoning"):
        _ok(f"Raciocínio: {definition['reasoning'][:80]}")
    session.checkpoint("03_Objective_Definition", definition, cost)
    return definition


async def node_04_opportunity_check(session: Session, definition: dict, context: dict) -> Optional[dict]:
    _node("04", "Opportunity Check")

    # se tem aproveitável e não precisa criar novo
    if definition.get("reuse_existing") and definition.get("reuse_title"):
        reuse_title = definition["reuse_title"]
        existing = [
            o for o in context.get("existing_opportunities", [])
            if reuse_title.lower() in o.get("title", "").lower()
        ]
        if existing:
            best = existing[0]
            _ok(f"Reutilizando: {best['title']} (score {best['score']}) — pulando avaliação")
            winner = {"idea_title": best["title"], "final_score": best["score"], "priority": "alta"}
            session.checkpoint("04_Opportunity_Check", {"reused": True, "winner": winner})
            return winner

    if "opportunity" not in definition.get("execution_path", []):
        _ok("Pulando (não necessário para este objetivo)")
        session.checkpoint("04_Opportunity_Check", {"skipped": True})
        return None

    _ok("Gerando nova avaliação de oportunidade...")
    winner = await _run_opportunity(session, session.objective, session.market)
    session.checkpoint("04_Opportunity_Check", winner or {})
    return winner


async def node_05_scoring(session: Session, winner: Optional[dict]) -> Optional[dict]:
    _node("05", "Scoring")
    if not winner:
        _ok("Pulando (sem oportunidade para pontuar)")
        session.checkpoint("05_Scoring", {"skipped": True})
        return None

    score    = winner.get("final_score", 0)
    priority = winner.get("priority", "baixa")

    PRIORITY_ICON = {"maxima": "🔥", "alta": "✅", "media": "🟡", "baixa": "🔴"}
    _ok(f"Score final: {score}/100 · Prioridade: {PRIORITY_ICON.get(priority,'')} {priority}")
    _ok(f"Recomendação: {winner.get('recommendation', '')}")

    if winner.get("next_step"):
        _ok(f"Próximo passo: {winner['next_step'][:80]}")

    session.checkpoint("05_Scoring", winner)
    return winner


async def node_06_decision(session: Session, winner: Optional[dict], definition: dict) -> str:
    _node("06", "Decision")

    if not winner:
        # sem scoring, usa a definição de objetivo
        decision = "executar" if definition.get("execution_path") else "ajustar"
        _ok(f"Decisão (sem scoring): {decision.upper()}")
        session.checkpoint("06_Decision", {"decision": decision, "reason": "sem_scoring"})
        return decision

    score    = winner.get("final_score", 0)
    priority = winner.get("priority", "baixa")

    if priority in ("maxima", "alta") or score >= 60:
        decision = "executar"
        reason   = f"Score {score} + prioridade {priority} → seguir"
    elif score >= 40:
        decision = "ajustar"
        reason   = f"Score {score} mediano → ajustar ideia antes de executar"
    else:
        decision = "descartar"
        reason   = f"Score {score} insuficiente → não vale executar agora"

    DECISION_ICON = {"executar": "🚀", "ajustar": "🔧", "descartar": "🛑"}
    _ok(f"{DECISION_ICON.get(decision,'')} {decision.upper()} — {reason}")

    if not _pause(session, "06_Decision",
                  f"Decisão: {decision.upper()} para '{winner.get('idea_title','')}'\n  │  Continuar?"):
        session.finish("aborted")
        sys.exit(0)

    session.checkpoint("06_Decision", {"decision": decision, "reason": reason})
    return decision


async def node_07_execute_path(
    session: Session,
    decision: str,
    winner: Optional[dict],
    definition: dict,
) -> dict:
    _node("07", "Execute Path")

    if decision == "descartar":
        _ok("Descartado. Encerrando pipeline de execução.")
        session.checkpoint("07_Execute_Path", {"skipped": True, "reason": "descartado"})
        return {}

    if not _pause(session, "07_Execute_Path",
                  f"Vai executar: {' → '.join(definition.get('execution_path', []))}"):
        session.finish("aborted")
        sys.exit(0)

    path    = definition.get("execution_path", ["product", "content"])
    results = {"engines_run": []}

    # ── estado carregado/criado pelo engine anterior ──
    blueprint = None
    content   = None

    # usa winner como ponto de entrada
    entry = winner or {"idea_title": session.objective, "final_score": 70, "priority": "alta"}

    if "product" in path:
        print(f"  │")
        print(f"  │  ─ Product Engine ─────────────────────────────────────")
        blueprint = await _run_product(session, entry)
        if blueprint:
            results["engines_run"].append("product")
            results["blueprint"] = {"idea_title": blueprint.get("idea_title", "")}

    if "content" in path and blueprint:
        print(f"  │")
        print(f"  │  ─ Content Engine ─────────────────────────────────────")
        content = await _run_content(session, blueprint)
        if content:
            results["engines_run"].append("content")
            results["content_summary"] = content.get("summary", {})

    if "video" in path and content:
        print(f"  │")
        print(f"  │  ─ Video Engine ───────────────────────────────────────")
        video = await _run_video(session, content)
        if video:
            results["engines_run"].append("video")

    if "sales" in path and blueprint:
        print(f"  │")
        print(f"  │  ─ Sales Engine ───────────────────────────────────────")
        funnel = await _run_sales(session, blueprint)
        if funnel:
            results["engines_run"].append("sales")

    _ok(f"Engines executados: {', '.join(results['engines_run'])}")
    session.checkpoint("07_Execute_Path", results)
    return results


async def node_08_distribute(session: Session, execution: dict) -> dict:
    _node("08", "Distribute")
    engines_run = execution.get("engines_run", [])

    queue: list[dict] = []

    if "content" in engines_run:
        queue.append({"tipo": "posts", "canal": "instagram/linkedin", "status": "pronto"})
    if "video" in engines_run:
        queue.append({"tipo": "reels/videos", "canal": "instagram/youtube", "status": "scripts_prontos"})
    if "sales" in engines_run:
        queue.append({"tipo": "funil", "canal": "whatsapp/email", "status": "ativo"})

    for item in queue:
        _ok(f"{item['tipo']} → {item['canal']} [{item['status']}]")

    if not queue:
        _ok("Nenhum ativo para distribuir nesta sessão")

    session.checkpoint("08_Distribute", {"queue": queue})
    return {"queue": queue}


async def node_09_collect_feedback(session: Session) -> dict:
    _node("09", "Collect Feedback")

    # tenta ler feedbacks existentes dos outputs
    feedback: dict = {}

    perf_files = sorted(glob.glob(f"{OUTPUTS_DIR}/performance_*.json"), reverse=True)
    if perf_files:
        try:
            with open(perf_files[0], encoding="utf-8") as f:
                d = json.load(f)
            m = d.get("metrics", {})
            feedback["performance_score"] = m.get("performance_score", 0)
            feedback["performance_band"]  = m.get("performance_band", "")
            _ok(f"Performance mais recente: score {feedback['performance_score']} ({feedback['performance_band']})")
        except Exception:
            pass

    val_files = sorted(glob.glob(f"{OUTPUTS_DIR}/validation_*.json"), reverse=True)
    if val_files:
        try:
            with open(val_files[0], encoding="utf-8") as f:
                d = json.load(f)
            s = d.get("signals", {})
            feedback["validation_score"]  = s.get("validation_score", 0)
            feedback["validation_action"] = d.get("final_action", "")
            _ok(f"Validação mais recente: score {feedback['validation_score']} → {feedback['validation_action']}")
        except Exception:
            pass

    if not feedback:
        _ok("Sem feedbacks coletados ainda (execute performance/validation engines após publicar)")

    session.checkpoint("09_Collect_Feedback", feedback)
    return feedback


async def node_10_learn(session: Session, feedback: dict) -> dict:
    _node("10", "Learn")
    try:
        insights, cost = await _claude(
            _p_learn(session, session.state.get("results", {})),
            max_tokens=600,
        )
        _ok(f"Insights gerados", cost)

        if isinstance(insights, dict) and insights.get("patterns_to_remember"):
            for p in insights["patterns_to_remember"][:3]:
                _ok(f"Padrão: {p[:70]}")

        _update_memory(insights if isinstance(insights, dict) else {}, session)
        session.checkpoint("10_Learn", insights if isinstance(insights, dict) else {}, cost)
        return insights if isinstance(insights, dict) else {}

    except Exception as e:
        _ok(f"Learn: {e} (continuando)")
        session.checkpoint("10_Learn", {"error": str(e)})
        return {}


async def node_11_repeat(session: Session, insights: dict) -> dict:
    _node("11", "Repeat")

    next_rec = insights.get("next_session_recommendation", "")
    if next_rec:
        print(f"\n  │  Próxima sessão recomendada:")
        print(f"  │  → {next_rec[:100]}")

    custo_total = session.state["total_cost"]
    engines = session.state.get("results", {}).get("07_Execute_Path", {}).get("engines_run", [])
    nodes   = len(session.state["nodes_done"])

    _ok(f"Sessão concluída: {nodes} nós · {len(engines)} engines · ${custo_total:.4f}")
    _ok("Loop disponível — execute novamente para continuar")

    loop_cmd = f'python master_controller.py --mode {session.mode} --objective "{session.objective}"'
    if session.market:
        loop_cmd += f' --market "{session.market}"'

    print(f"\n  │  Comando para próximo loop:")
    print(f"  │  {loop_cmd}")

    result = {"loop_ready": True, "next_recommendation": next_rec, "total_cost": custo_total}
    session.checkpoint("11_Repeat", result)
    session.finish("completed")
    return result


# ─── Orquestrador principal ───────────────────────────────────────────────────

async def run_session(
    objective: str,
    market: str = "",
    mode: str = "semi_auto",
    session_id: Optional[str] = None,
):
    sid = session_id or time.strftime("%Y%m%d_%H%M%S")
    session = Session(sid, mode, objective, market)

    _header(session)

    try:
        # Nó 01 — Input
        await node_01_input(session)

        # Nó 02 — Context Load
        context = await node_02_context_load(session)

        # Nó 03 — Objective Definition
        definition = await node_03_objective_definition(session, context)

        # Nó 04 — Opportunity Check
        winner = await node_04_opportunity_check(session, definition, context)

        # Nó 05 — Scoring
        winner = await node_05_scoring(session, winner)

        # Nó 06 — Decision
        decision = await node_06_decision(session, winner, definition)

        # Nó 07 — Execute Path
        execution = await node_07_execute_path(session, decision, winner, definition)

        # Nó 08 — Distribute
        await node_08_distribute(session, execution)

        # Nó 09 — Collect Feedback
        feedback = await node_09_collect_feedback(session)

        # Nó 10 — Learn
        insights = await node_10_learn(session, feedback)

        # Nó 11 — Repeat
        await node_11_repeat(session, insights)

        # Resumo final
        _print_summary(session)

    except KeyboardInterrupt:
        print("\n\n  Sessão interrompida pelo usuário.")
        session.finish("interrupted")
    except Exception as e:
        print(f"\n  Erro na sessão: {e}")
        session.finish("error")
        raise


def _print_summary(session: Session):
    results = session.state.get("results", {})
    print("\n" + "═" * 66)
    print("  RESUMO DA SESSÃO")
    print("═" * 66)
    print(f"  ID          : {session.id}")
    print(f"  Status      : {session.state['status']}")
    print(f"  Custo total : ~${session.state['total_cost']:.4f}")
    print(f"  Nós ok      : {len(session.state['nodes_done'])}/11")

    if results.get("05_Scoring"):
        s = results["05_Scoring"]
        print(f"\n  Oportunidade : {s.get('idea_title','')} — {s.get('final_score',0)}/100")

    if results.get("06_Decision"):
        d = results["06_Decision"]
        print(f"  Decisão      : {d.get('decision','').upper()}")

    if results.get("07_Execute_Path"):
        ep = results["07_Execute_Path"]
        engines = ep.get("engines_run", [])
        if engines:
            print(f"  Engines run  : {', '.join(engines)}")

    if results.get("11_Repeat"):
        r = results["11_Repeat"]
        if r.get("next_recommendation"):
            print(f"\n  Próxima ação : {r['next_recommendation'][:80]}")

    print("═" * 66 + "\n")

    _atualizar_dashboard()


# ─── Status ───────────────────────────────────────────────────────────────────

def show_status():
    files = sorted(glob.glob(os.path.join(SESSIONS_DIR, "session_*.json")), reverse=True)
    if not files:
        print("  Nenhuma sessão encontrada.")
        return

    STATUS_ICON = {"completed": "✅", "running": "🔄", "aborted": "🛑", "error": "❌", "interrupted": "⏸"}

    print("\n" + "═" * 70)
    print("  AI BUSINESS OS — Sessões")
    print("═" * 70)
    for path in files[:15]:
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            status = d.get("status", "?")
            icon   = STATUS_ICON.get(status, "?")
            nodes  = len(d.get("nodes_done", []))
            cost   = d.get("total_cost", 0)
            print(f"  {icon} [{d.get('session_id','')}] {d.get('mode',''):<10} "
                  f"{nodes}/11 nós · ${cost:.4f}")
            print(f"     → {d.get('objective','')[:60]}")
        except Exception:
            pass
    print()


# ─── Dashboard ────────────────────────────────────────────────────────────────

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


# ─── CLI ──────────────────────────────────────────────────────────────────────

async def main():
    args = sys.argv[1:]

    if "--status" in args:
        show_status()
        return

    def _arg(flag: str, default: str = "") -> str:
        if flag in args:
            i = args.index(flag)
            return args[i + 1] if i + 1 < len(args) else default
        return default

    mode       = _arg("--mode", "semi_auto")
    objective  = _arg("--objective", "")
    market     = _arg("--market", "")
    session_id = _arg("--resume", None) or None

    if mode not in ("auto", "semi_auto", "manual"):
        print(f"  Modo inválido: {mode}. Use: auto, semi_auto, manual")
        return

    if not objective:
        print("\n  ─── AI Business OS — Novo objetivo ─────────────────────")
        objective = input("  Objetivo (ex: 'criar produto para restaurantes'): ").strip()
        if not objective:
            print("  Objetivo obrigatório.")
            return
        market = input("  Mercado/nicho (ex: 'restaurantes'): ").strip()
        mode_input = input("  Modo [auto/semi_auto/manual] (Enter = semi_auto): ").strip()
        if mode_input in ("auto", "semi_auto", "manual"):
            mode = mode_input

    await run_session(objective, market, mode, session_id)


if __name__ == "__main__":
    asyncio.run(main())
