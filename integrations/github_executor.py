"""
GitHub Executor — Pipeline AI
Transforma uma ExecutionTask em uma issue real no GitHub.

Requer no .env:
 GITHUB_TOKEN — Personal Access Token com permissão issues:write
 GITHUB_REPO — formato owner/repo (ex: marceloyukio/myo-builds)
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_API = "https://api.github.com"


# Body da issue

def _build_issue_body(task) -> str:
    ctx = task.context or {}

    lines = [
        f"## Objetivo",
        f"{task.description}",
        f"",
        f"## Contexto",
    ]

    for k, v in ctx.items():
        if v is not None:
            lines.append(f"- **{k}**: {v}")

    if task.acceptance_criteria:
        lines += ["", "## Critérios de aceite"]
        for c in task.acceptance_criteria:
            lines.append(f"- [ ] {c}")

    if task.deliverables:
        lines += ["", "## Entregáveis"]
        for d in task.deliverables:
            lines.append(f"- {d}")

    lines += [
        "",
        "## Metadados",
        f"- **task_id**: `{task.task_id}`",
        f"- **origin_engine**: `{task.origin_engine}`",
        f"- **agente sugerido**: `{task.suggested_agent.value if hasattr(task.suggested_agent, 'value') else task.suggested_agent}`",
        f"- **prioridade**: `{task.priority.value if hasattr(task.priority, 'value') else task.priority}`",
        f"- **tipo**: `{task.task_type.value if hasattr(task.task_type, 'value') else task.task_type}`",
        f"- **criado em**: `{task.created_at}`",
    ]

    if task.related_entity_id:
        lines.append(f"- **entidade relacionada**: `{task.related_entity_id}`")

    # Metadados de experimento (presentes quando task vem de retry)
    exp_entries = [
        (k, getattr(task, k, None))
        for k in ("original_failure_type", "retry_mode", "experiment_context")
        if getattr(task, k, None)
    ]
    if exp_entries:
        lines += ["", "## Experimento"]
        for k, v in exp_entries:
            lines.append(f"- **{k}**: `{v}`")

    lines += ["", "---", "*Gerado automaticamente pelo MYO Execution Engine*"]

    return "\n".join(lines)


# Criação da issue

async def create_github_issue(task) -> dict:
    """
    Recebe uma ExecutionTask, cria uma issue no GitHub e retorna:
    { issue_number, issue_url, status }
    """
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN não configurado no .env")
    if not GITHUB_REPO:
        raise ValueError("GITHUB_REPO não configurado no .env (formato: owner/repo)")

    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/issues"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "title": task.title,
        "body": _build_issue_body(task),
        "labels": [t for t in task.tags if t],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    return {
        "issue_number": data["number"],
        "issue_url": data["html_url"],
        "status": "created",
    }
