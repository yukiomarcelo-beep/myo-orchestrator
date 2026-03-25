#!/usr/bin/env python3
"""
Autonomous_Agent — standalone
Fluxo: Init → Planner → ForEach(Task → Router → Save) → Evaluator → Loop/End

Uso:
    python autonomous_agent.py "Pesquise e crie estratégia de live commerce no Brasil"
    python autonomous_agent.py  # modo interativo
"""
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv
from notion_logger import salvar_agente

load_dotenv()

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
CLAUDE_MODEL       = "claude-sonnet-4-6"
GPT_MODEL          = os.getenv("GPT_MODEL", "gpt-4o")
PERPLEXITY_MODEL   = os.getenv("PERPLEXITY_MODEL", "sonar")
MAX_ITERATIONS     = int(os.getenv("AGENT_MAX_ITERATIONS", "5"))


# ─────────────────────────────────────────────────────────────────────────────
# Estado (02_Init_State)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AgentTask:
    id: str
    type: str           # research | strategy | execution | video
    description: str
    expected_output: str
    result: str = ""
    status: str = "pending"

@dataclass
class AgentState:
    objective: str
    iteration: int = 1
    max_iterations: int = MAX_ITERATIONS
    tasks: list = field(default_factory=list)
    results: list = field(default_factory=list)
    status: str = "running"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def results_summary(self) -> str:
        if not self.results:
            return "Nenhum resultado ainda."
        return "\n".join(
            f"- [{r.get('task_id')}|{r.get('type')}] {r.get('output','')[:300]}"
            for r in self.results
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers HTTP
# ─────────────────────────────────────────────────────────────────────────────

async def _claude(prompt: str, max_tokens: int = 1200) -> str:
    if not ANTHROPIC_API_KEY or "sua-chave" in ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY não configurada")
    payload = {
        "model": CLAUDE_MODEL, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
        r.raise_for_status()
    return r.json().get("content", [{}])[0].get("text", "").strip()

async def _gpt(prompt: str) -> str:
    if not OPENAI_API_KEY or "sua-chave" in OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY não configurada")
    payload = {"model": GPT_MODEL, "input": prompt}
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post("https://api.openai.com/v1/responses", json=payload, headers=headers)
        r.raise_for_status()
    items = r.json().get("output", [])
    return "\n".join(
        i.get("content", [{}])[0].get("text", "")
        for i in items if i.get("type") == "message"
    )

async def _perplexity(prompt: str) -> str:
    if not PERPLEXITY_API_KEY or "sua-chave" in PERPLEXITY_API_KEY:
        raise ValueError("PERPLEXITY_API_KEY não configurada")
    payload = {
        "model": PERPLEXITY_MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
    return r.json().get("choices", [{}])[0].get("message", {}).get("content", "")

def _extract_json(raw: str) -> dict:
    """Remove markdown e parseia JSON."""
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) >= 2 else raw
        raw = raw.lstrip("json").strip()
    return json.loads(raw)


# ─────────────────────────────────────────────────────────────────────────────
# 03_Planner_Claude
# ─────────────────────────────────────────────────────────────────────────────

async def planner(state: AgentState) -> list[AgentTask]:
    context = (f"\n\nResultados anteriores (iteração {state.iteration - 1}):\n{state.results_summary()}"
               if state.results else "")

    prompt = f"""Você é um agente planejador.

Objetivo:
{state.objective}{context}

Crie um plano em JSON com até 5 tarefas acionáveis.
Cada tarefa deve ter:
- id (string, ex: "t1")
- type (research | strategy | execution | video)
- description (instrução completa e autossuficiente)
- expected_output (o que esperar como resultado)

Responda APENAS em JSON válido, sem markdown:
{{
  "tasks": [...]
}}"""

    raw = await _claude(prompt, max_tokens=1200)
    # 04_Parse_Tasks
    try:
        data = _extract_json(raw)
        tasks = [
            AgentTask(
                id=str(t.get("id", f"t{i}")),
                type=t.get("type", "execution"),
                description=t.get("description", ""),
                expected_output=t.get("expected_output", ""),
            )
            for i, t in enumerate(data.get("tasks", []))
        ]
        _print(f"  {len(tasks)} tarefa(s) planejada(s): {[t.type for t in tasks]}")
        return tasks
    except Exception as e:
        _print(f"  ⚠ Erro ao parsear plano: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 06_Task_Router
# ─────────────────────────────────────────────────────────────────────────────

async def task_router(task: AgentTask) -> str:
    _print(f"\n    → [{task.type.upper()}] {task.description[:70]}")
    try:
        if task.type == "research":
            return await _perplexity(
                f"Pesquise profundamente sobre: {task.description}. "
                "Retorne oportunidades, dores, sinais de demanda, concorrência e riscos."
            )
        elif task.type == "strategy":
            return await _claude(
                f"Execute esta tarefa estratégica:\n{task.description}\n\n"
                "Retorne resposta estruturada e objetiva.",
                max_tokens=1800
            )
        elif task.type == "execution":
            return await _gpt(f"Execute: {task.description}")

        elif task.type == "video":
            # roteiro via Claude
            script = await _claude(
                f"Crie um roteiro curto, com até 30 segundos, para: {task.description}. "
                "Estruture em gancho, desenvolvimento e CTA.",
                max_tokens=800
            )
            # variações via GPT
            try:
                variations = await _gpt(
                    f"Com base neste roteiro: {script}, "
                    "crie 3 versões mais agressivas e 3 versões mais elegantes."
                )
                return f"ROTEIRO BASE:\n{script}\n\nVARIAÇÕES:\n{variations}"
            except Exception:
                return f"ROTEIRO BASE:\n{script}"
        else:
            return await _gpt(f"Execute: {task.description}")

    except Exception as e:
        return f"ERRO: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# 08_Evaluator_Claude
# ─────────────────────────────────────────────────────────────────────────────

async def evaluator(state: AgentState) -> dict:
    prompt = f"""Objetivo original:
{state.objective}

Resultados até agora (iteração {state.iteration}):
{state.results_summary()}

Avalie o progresso e retorne APENAS JSON válido, sem markdown:
{{
  "progress": 0,
  "quality": "baixa | média | alta",
  "status": "continue | complete | refine",
  "missing": "o que ainda falta",
  "next_actions": []
}}

Critério:
- "complete" se o objetivo foi totalmente atingido
- "refine" se há resultados mas precisam de melhoria
- "continue" se falta conteúdo essencial"""

    try:
        raw = await _claude(prompt, max_tokens=600)
        ev = _extract_json(raw)
        _print(f"  progress={ev.get('progress')}% | quality={ev.get('quality')} | status={ev.get('status')}")
        if ev.get("missing"):
            _print(f"  faltando: {ev['missing'][:80]}")
        return ev
    except Exception as e:
        _print(f"  ⚠ Evaluator falhou: {e} — forçando complete")
        return {"progress": 100, "quality": "desconhecida", "status": "complete",
                "missing": "", "next_actions": []}


# ─────────────────────────────────────────────────────────────────────────────
# 09_Decision
# ─────────────────────────────────────────────────────────────────────────────

def decision(state: AgentState, evaluation: dict) -> str:
    if state.iteration >= state.max_iterations:
        _print(f"  max_iterations ({state.max_iterations}) atingido → complete")
        return "complete"
    return evaluation.get("status", "complete")


# ─────────────────────────────────────────────────────────────────────────────
# Salvar resultado local
# ─────────────────────────────────────────────────────────────────────────────

def _salvar_local(state: AgentState):
    os.makedirs("outputs", exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = f"outputs/agent_{ts}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "objective": state.objective,
            "iterations": state.iteration,
            "status": state.status,
            "results": state.results,
        }, f, ensure_ascii=False, indent=2)
    _print(f"\n  💾 Salvo em: {fname}")
    return fname


# ─────────────────────────────────────────────────────────────────────────────
# LOOP PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def _print(msg: str):
    print(msg, flush=True)

async def run(objective: str) -> dict:
    print(f"\n{'═'*60}")
    print(f"  AUTONOMOUS AGENT")
    print(f"{'═'*60}")
    print(f"\n  Objetivo : {objective[:80]}")
    print(f"  Max iter : {MAX_ITERATIONS}\n")

    # 02_Init_State
    state = AgentState(objective=objective)

    while state.status == "running":
        print(f"\n{'─'*60}")
        print(f"  ITERAÇÃO {state.iteration}/{state.max_iterations}")
        print(f"{'─'*60}")

        # 03_Planner_Claude + 04_Parse_Tasks
        _print("\n  [1/4] Planejando tarefas...")
        state.tasks = await planner(state)

        if not state.tasks:
            _print("  ⚠ Nenhuma tarefa gerada — encerrando")
            break

        # 05_ForEach_Task → 06_Task_Router → 07_Save_Result
        _print(f"\n  [2/4] Executando {len(state.tasks)} tarefa(s)...")
        for task in state.tasks:
            output = await task_router(task)
            task.result = output
            task.status = "done" if not output.startswith("ERRO") else "error"

            # 07_Save_Result — acumular no estado
            state.results.append({
                "task_id": task.id,
                "type": task.type,
                "description": task.description[:100],
                "output": output,
            })
            preview = output[:120].replace("\n", " ")
            _print(f"    ✓ {preview}")

        # 08_Evaluator_Claude
        _print("\n  [3/4] Avaliando progresso...")
        evaluation = await evaluator(state)

        # 09_Decision + 10_Update_State + 11_Loop_Or_End
        next_status = decision(state, evaluation)
        _print(f"\n  [4/4] Decisão: {next_status.upper()}")

        if next_status == "complete":
            state.status = "complete"
        else:
            # continue ou refine → volta ao Planner com contexto acumulado
            state.iteration += 1

    # 12_Respond
    saved = _salvar_local(state)

    # salvar no Notion
    notion_url = await salvar_agente(
        objective=state.objective,
        iterations=state.iteration,
        results=state.results,
        status=state.status,
    )

    final = {
        "status": state.status,
        "iterations": state.iteration,
        "objective": state.objective,
        "tasks_executed": len(state.results),
        "results": state.results,
        "saved_to": saved,
        "notion_url": notion_url,
    }

    print(f"\n{'═'*60}")
    print(f"  CONCLUÍDO — {state.iteration} iteração(ões) | {len(state.results)} tarefas executadas")
    print(f"{'═'*60}\n")

    return final


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    if len(sys.argv) > 1:
        objective = " ".join(sys.argv[1:])
    else:
        print("\n  AUTONOMOUS AGENT — modo interativo")
        print("  Exemplos:")
        print('    "Pesquise e crie estratégia de live commerce no Brasil"')
        print('    "Crie campanha completa para restaurante premium em SP"')
        print()
        try:
            objective = input("  Objetivo: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Saindo.")
            return

    if not objective:
        print("  Nenhum objetivo fornecido.")
        return

    result = await run(objective)

    print("\nRESUMO FINAL:")
    print(json.dumps({
        "status": result["status"],
        "iterations": result["iterations"],
        "tasks_executed": result["tasks_executed"],
        "saved_to": result["saved_to"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
