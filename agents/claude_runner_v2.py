"""
agents/claude_runner_v2.py — Agent SDK Integration

SUBSTITUI o claude_runner.py atual (baseado em `claude -p` subprocess).

Diferenças fundamentais:
- ANTES: claude -p → texto → humano executa manualmente → volta. One-shot.
- AGORA: Agent SDK → Claude executa (Read, Write, Edit, Bash, Git). Loop completo.

Integração com MYO (trust pipeline, observability, policy):
- `tracker` (observability.py) → mede latência e custo
- `policy_adapter` + `context_policy.json` → hook PreToolUse bloqueia por contexto
- `verification_logger` → hook PostToolUse grava cada tool use como evento
- result_ingestor continua consumindo o JSON salvo em outputs/claude_results/

Modos (compatível com claude_runner.py atual):
    python3 claude_runner_v2.py               → todas as issues abertas
    python3 claude_runner_v2.py --issue 7     → issue específica
    python3 claude_runner_v2.py --no-close    → não fecha issue (teste)
    python3 claude_runner_v2.py --local --prompt "fix X"  → modo local sem GitHub

Requer:
    pip install claude-agent-sdk
    .env: ANTHROPIC_API_KEY, GITHUB_TOKEN, GITHUB_REPO
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookContext,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    query,
)
from dotenv import load_dotenv

load_dotenv()

# ─── Integrações com MYO ──────────────────────────────────────────────
try:
    from observability import tracker

    _HAS_TRACKER = True
except ImportError:
    _HAS_TRACKER = False
    print("[runner_v2] AVISO: observability.tracker não disponível")

try:
    from policies import claim_policy

    _HAS_POLICY = True
except ImportError:
    _HAS_POLICY = False
    print("[runner_v2] AVISO: policies.claim_policy não disponível — hooks de policy desativados")

try:
    from policies.runtime_guard import RuntimeGuard, build_hook_response

    _HAS_RUNTIME_GUARD = True
except ImportError:
    _HAS_RUNTIME_GUARD = False
    print("[runner_v2] AVISO: policies.runtime_guard não disponível — contextual policy desativada")
# ─────────────────────────────────────────────────────────────────────


# =========================================================================
# CONFIG
# =========================================================================

DEFAULT_MODEL = "claude-opus-4-7"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_API = "https://api.github.com"
RESULTS_DIR = Path("outputs/claude_results")
EXECUTION_CONTEXT = os.getenv(
    "MYO_EXECUTION_CONTEXT", "mvp"
)  # idea|research|mvp|launch_ready|scaling

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


# =========================================================================
# RESULTADO ESTRUTURADO
# =========================================================================


@dataclass
class RunResult:
    issue_number: int
    status: str = "failed"  # "success" | "partial" | "failed"
    final_text: str = ""
    tool_uses: list[dict] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    bash_commands: list[str] = field(default_factory=list)
    duration_ms: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    session_id: Optional[str] = None
    error: Optional[str] = None
    blocked_by_policy: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "issue_number": self.issue_number,
            "status": self.status,
            "final_text": self.final_text,
            "tool_uses": self.tool_uses,
            "files_modified": self.files_modified,
            "bash_commands": self.bash_commands,
            "duration_ms": self.duration_ms,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "session_id": self.session_id,
            "error": self.error,
            "blocked_by_policy": self.blocked_by_policy,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }


# =========================================================================
# HOOKS — integração com trust pipeline e policy
# =========================================================================

# Lista de padrões DEFINITIVAMENTE perigosos (bloqueio hard, sem política)
HARD_DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "dd if=",
    "mkfs",
    ":(){ :|:& };:",  # fork bomb
    "> /dev/sda",
    "chmod -R 777 /",
]

# Shared state pro post-hook conseguir ler o que o pre-hook coletou
_HOOK_STATE: dict = {"blocked": [], "tool_uses_raw": []}

# RuntimeGuard global — instanciado por run (set_runtime_guard)
_GUARD: "RuntimeGuard | None" = None


def set_runtime_guard(execution_context: str):
    """Inicializa o RuntimeGuard para o contexto atual. Chamado antes de cada run."""
    global _GUARD
    if not _HAS_RUNTIME_GUARD:
        _GUARD = None
        return
    try:
        _GUARD = RuntimeGuard(execution_context=execution_context)
        print(
            f"[runner_v2] RuntimeGuard ativo: context={execution_context}, has_policy={_GUARD.has_policy}"
        )
    except ValueError as e:
        print(f"[runner_v2] AVISO: execution_context invalido ({e}); guard desativado")
        _GUARD = None


async def pre_tool_use_hook(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext,
) -> dict[str, Any]:
    """Hook PreToolUse: bloqueia ferramentas perigosas antes de executar."""
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # 1. Bloqueio hard por padrão destrutivo (Bash)
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        for danger in HARD_DANGEROUS_PATTERNS:
            if danger in command:
                _HOOK_STATE["blocked"].append(
                    {
                        "tool": tool_name,
                        "reason": f"hard_block: '{danger}'",
                        "command": command[:200],
                    }
                )
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": f"hard block: padrão destrutivo detectado ({danger})",
                    }
                }

    # 2. Policy contextual via RuntimeGuard (LESSON-003)
    if _GUARD is not None:
        decision = _GUARD.evaluate_tool_use(tool_name, tool_input)
        if not decision.allowed:
            _HOOK_STATE["blocked"].append(
                {
                    "tool": tool_name,
                    "reason": decision.reason,
                    "rule": decision.rule,
                    "context": decision.context,
                }
            )
            return build_hook_response(decision)
        # severity 'warn' permite execucao mas registra
        if decision.severity == "warn":
            _HOOK_STATE.setdefault("warnings", []).append(
                {
                    "tool": tool_name,
                    "reason": decision.reason,
                    "rule": decision.rule,
                    "context": decision.context,
                }
            )

    return {}


async def post_tool_use_hook(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext,
) -> dict[str, Any]:
    """Hook PostToolUse: registra tool use no trust log."""
    _HOOK_STATE["tool_uses_raw"].append(
        {
            "tool_name": input_data.get("tool_name", ""),
            "tool_input": input_data.get("tool_input", {}),
            "tool_response": input_data.get("tool_response", {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {}


# =========================================================================
# EXECUTOR PRINCIPAL (Agent SDK)
# =========================================================================


async def run_prompt_async(
    prompt: str,
    project_dir: str | Path,
    issue_number: int = 0,
    model: str = DEFAULT_MODEL,
    max_turns: int = 30,
    allowed_tools: Optional[list[str]] = None,
    permission_mode: str = "acceptEdits",
) -> RunResult:
    """
    Executa um prompt com Agent SDK. Claude tem acesso completo a tools.
    Retorna RunResult com histórico completo pra observability e trust.
    """
    # Reset estado dos hooks
    _HOOK_STATE["blocked"] = []
    _HOOK_STATE["tool_uses_raw"] = []

    started = time.time()
    result = RunResult(issue_number=issue_number)

    if allowed_tools is None:
        allowed_tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]

    options = ClaudeAgentOptions(
        model=model,
        allowed_tools=allowed_tools,
        permission_mode=permission_mode,
        cwd=str(project_dir),
        max_turns=max_turns,
        hooks={
            "PreToolUse": [HookMatcher(hooks=[pre_tool_use_hook])],
            "PostToolUse": [HookMatcher(hooks=[post_tool_use_hook])],
        },
    )

    # Wrapper com tracker pra observability
    if _HAS_TRACKER:
        track_ctx = tracker.track(
            agent="claude_runner_v2",
            model=model,
            action="run_prompt",
            engine_name="claude_runner_v2",
            confidence="observed",
        )
    else:
        # dummy context manager
        class _Noop:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def set_tokens(self, **kw):
                pass

        track_ctx = _Noop()

    try:
        with track_ctx as t:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, SystemMessage):
                    if getattr(message, "subtype", None) == "init":
                        data = getattr(message, "data", {}) or {}
                        result.session_id = data.get("session_id")

                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            result.final_text += block.text + "\n"
                        elif isinstance(block, ToolUseBlock):
                            tool_entry = {
                                "tool": block.name,
                                "input": block.input,
                                "id": block.id,
                            }
                            result.tool_uses.append(tool_entry)
                            if block.name in ("Write", "Edit"):
                                fp = block.input.get("file_path")
                                if fp and fp not in result.files_modified:
                                    result.files_modified.append(fp)
                            elif block.name == "Bash":
                                cmd = block.input.get("command", "")
                                result.bash_commands.append(cmd)

                if isinstance(message, ResultMessage):
                    result.status = (
                        "success" if not getattr(message, "is_error", False) else "partial"
                    )
                    usage = getattr(message, "usage", {}) or {}
                    result.tokens_input = usage.get("input_tokens", 0)
                    result.tokens_output = usage.get("output_tokens", 0)

            if _HAS_TRACKER:
                t.set_tokens(input=result.tokens_input, output=result.tokens_output)

    except asyncio.TimeoutError:
        result.status = "failed"
        result.error = "timeout"
    except Exception as e:
        result.status = "failed"
        result.error = f"{type(e).__name__}: {e}"

    # Captura blocks dos hooks
    result.blocked_by_policy = [b["reason"] for b in _HOOK_STATE["blocked"]]

    result.duration_ms = int((time.time() - started) * 1000)
    return result


# =========================================================================
# GITHUB INTEGRATION (preservado do claude_runner original)
# =========================================================================


def _check_github_config():
    missing = []
    if not GITHUB_TOKEN:
        missing.append("GITHUB_TOKEN")
    if not GITHUB_REPO:
        missing.append("GITHUB_REPO")
    if missing:
        print(f"[ERRO] Variáveis não configuradas no .env: {', '.join(missing)}")
        sys.exit(1)


def fetch_open_issues() -> list[dict]:
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/issues"
    params = {"state": "open", "labels": "myo", "per_page": 50, "sort": "created"}
    with httpx.Client(timeout=30) as client:
        res = client.get(url, headers=HEADERS, params=params)
        res.raise_for_status()
        return res.json()


def get_issue(issue_number: int) -> dict:
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/issues/{issue_number}"
    with httpx.Client(timeout=30) as client:
        res = client.get(url, headers=HEADERS)
        res.raise_for_status()
        return res.json()


def post_comment(issue_number: int, body: str):
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/issues/{issue_number}/comments"
    with httpx.Client(timeout=30) as client:
        res = client.post(url, headers=HEADERS, json={"body": body})
        res.raise_for_status()


def close_issue(issue_number: int):
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/issues/{issue_number}"
    with httpx.Client(timeout=30) as client:
        res = client.patch(url, headers=HEADERS, json={"state": "closed"})
        res.raise_for_status()


# =========================================================================
# BUILD PROMPT
# =========================================================================


def build_prompt_from_issue(issue: dict, project_dir: str) -> str:
    title = issue.get("title", "—")
    body = (issue.get("body") or "").strip()
    number = issue.get("number", 0)
    labels = [lb["name"] for lb in issue.get("labels", [])]

    return f"""Você é um executor técnico. Resolva a tarefa abaixo COMPLETAMENTE.

Você tem acesso total ao projeto em `{project_dir}`:
- Read/Glob/Grep pra explorar código
- Write/Edit pra modificar arquivos
- Bash pra rodar testes, git, build

# Issue #{number} — {title}
Labels: {', '.join(labels) if labels else '—'}

{body}

# Entregáveis obrigatórios

Ao final, resuma em texto:
1. **Resultado**: o que foi feito
2. **Entregáveis**: arquivos modificados/criados (o Agent já os criou via Edit/Write)
3. **Lógica**: raciocínio
4. **Próximos**: passos recomendados
"""


# =========================================================================
# PERSISTÊNCIA + COMENTÁRIO
# =========================================================================


def save_result_json(result: RunResult) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"issue_{result.issue_number}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    return path


def build_github_comment(result: RunResult) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    status_icon = {"success": "✓", "partial": "⚠", "failed": "✗"}.get(result.status, "?")

    files_section = ""
    if result.files_modified:
        files_section = "\n\n**Arquivos modificados:**\n" + "\n".join(
            f"- `{f}`" for f in result.files_modified
        )

    bash_section = ""
    if result.bash_commands:
        bash_section = (
            "\n\n**Comandos bash executados:**\n```\n"
            + "\n".join(result.bash_commands[:10])
            + "\n```"
        )
        if len(result.bash_commands) > 10:
            bash_section += f"\n(+ {len(result.bash_commands) - 10} comandos)"

    blocked_section = ""
    if result.blocked_by_policy:
        blocked_section = "\n\n**⚠ Ações bloqueadas por policy:**\n" + "\n".join(
            f"- {b}" for b in result.blocked_by_policy
        )

    return f"""## Resultado MYO · Issue #{result.issue_number}  {status_icon}

{result.final_text.strip() or '_(sem output textual — ver tool_uses no JSON)_'}

{files_section}{bash_section}{blocked_section}

---
Executado via `claude_runner_v2.py` (Agent SDK) em {ts}
Modelo: `{DEFAULT_MODEL}`  ·  Duração: {result.duration_ms}ms  ·  Tool uses: {len(result.tool_uses)}
Tokens: in={result.tokens_input} out={result.tokens_output}
"""


# =========================================================================
# PROCESSAR UMA ISSUE
# =========================================================================


async def run_issue(issue: dict, project_dir: str, auto_close: bool = True):
    number = issue.get("number", 0)
    title = issue.get("title", "—")
    print(f"\n{'=' * 60}\n Issue #{number}: {title}\n{'=' * 60}")

    prompt = build_prompt_from_issue(issue, project_dir)
    result = await run_prompt_async(
        prompt=prompt,
        project_dir=project_dir,
        issue_number=number,
    )

    # Salvar
    saved_path = save_result_json(result)
    print(f"\n  Status: {result.status}")
    print(
        f"  Tool uses: {len(result.tool_uses)}  ·  arquivos: {len(result.files_modified)}  ·  bash: {len(result.bash_commands)}"
    )
    print(
        f"  Tokens: in={result.tokens_input}  out={result.tokens_output}  duração={result.duration_ms}ms"
    )
    if result.blocked_by_policy:
        print(f"  ⚠ Bloqueados: {len(result.blocked_by_policy)}")
    print(f"  Salvo: {saved_path}")

    # Postar comentário
    if number > 0 and GITHUB_TOKEN:
        try:
            post_comment(number, build_github_comment(result))
            print(f"  ✓ comentário postado na issue #{number}")
        except httpx.HTTPStatusError as e:
            print(f"  ✗ falha ao postar comentário: {e}")

    # Fechar issue se sucesso
    if auto_close and result.status == "success" and number > 0 and GITHUB_TOKEN:
        try:
            close_issue(number)
            print(f"  ✓ issue #{number} fechada")
        except httpx.HTTPStatusError as e:
            print(f"  ✗ falha ao fechar: {e}")


async def run_local(prompt: str, project_dir: str):
    """Modo local — sem GitHub, só executa e salva JSON."""
    print(f"\n[modo local] Executando em {project_dir}")
    result = await run_prompt_async(
        prompt=prompt,
        project_dir=project_dir,
        issue_number=0,
    )
    saved_path = save_result_json(result)
    print(f"\n  Status: {result.status}")
    print(f"  Tool uses: {len(result.tool_uses)}  ·  arquivos: {len(result.files_modified)}")
    print(f"  Salvo: {saved_path}")


# =========================================================================
# CLI
# =========================================================================


def main():
    parser = argparse.ArgumentParser(description="Claude Runner v2 (Agent SDK)")
    parser.add_argument("--issue", type=int, help="issue específica")
    parser.add_argument("--no-close", action="store_true", help="não fecha issue")
    parser.add_argument("--local", action="store_true", help="modo local sem GitHub")
    parser.add_argument("--prompt", type=str, help="prompt local (requer --local)")
    parser.add_argument("--project", type=str, default=".", help="diretório do projeto")
    args = parser.parse_args()

    # Modo local
    if args.local:
        if not args.prompt:
            print("[ERRO] --local requer --prompt")
            sys.exit(1)
        asyncio.run(run_local(args.prompt, args.project))
        return

    # Modo GitHub
    _check_github_config()
    auto_close = not args.no_close

    if args.issue:
        issue = get_issue(args.issue)
        if issue.get("state") == "closed":
            print(f"Issue #{args.issue} já fechada.")
            return
        asyncio.run(run_issue(issue, args.project, auto_close=auto_close))
    else:
        issues = fetch_open_issues()
        if not issues:
            print("Nenhuma issue MYO aberta.")
            return

        print(f"\n {len(issues)} issue(s) encontrada(s):")
        for iss in issues:
            print(f"  #{iss['number']:>4}  {iss['title'][:55]}")
        confirm = input("\nProcessar todas? [s/N]: ").strip().lower()
        if confirm != "s":
            print("Cancelado.")
            return
        for issue in issues:
            asyncio.run(run_issue(issue, args.project, auto_close=auto_close))

    print("\n Concluído.\n")


if __name__ == "__main__":
    main()
