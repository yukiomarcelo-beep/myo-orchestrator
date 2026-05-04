"""
Claude Runner — Pipeline AI
Puxa issues MYO do GitHub, executa automaticamente via Claude Code CLI
e posta resultado validado de volta no GitHub.

Uso:
 python3 claude_runner.py → automático: todas as issues abertas
 python3 claude_runner.py --issue 7 → automático: issue específica
 python3 claude_runner.py --manual → semi-manual: você cola a resposta
 python3 claude_runner.py --no-close → não fecha issue (útil para testar)

Requer no .env:
 GITHUB_TOKEN — Personal Access Token com permissão issues:write
 GITHUB_REPO — formato owner/repo (ex: marceloyukio/myo-builds)
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()
from observability import tracker

CLAUDE_CLI_MODEL = "claude-sonnet-4-6"  # flag --model sonnet

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_API = "https://api.github.com"
RESULTS_DIR = Path("outputs/claude_results")

# Seções obrigatórias no output do Claude
REQUIRED_SECTIONS = ["## Resultado", "## Entregáveis", "## Lógica", "## Próximos"]
MIN_RESULT_LENGTH = 200  # chars — abaixo disso é superficial

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


# Config


def _check_config():
    missing = []
    if not GITHUB_TOKEN:
        missing.append("GITHUB_TOKEN")
    if not GITHUB_REPO:
        missing.append("GITHUB_REPO")
    if missing:
        print(f"[ERRO] Variáveis não configuradas no .env: {', '.join(missing)}")
        sys.exit(1)


# GitHub API


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


# Prompt


def build_prompt(issue: dict) -> str:
    title = issue.get("title", "—")
    body = issue.get("body", "").strip()
    number = issue.get("number", "—")
    labels = [lb["name"] for lb in issue.get("labels", [])]
    label_str = ", ".join(labels) if labels else "—"

    return f"""Você é um executor técnico especialista.

Resolva completamente a tarefa abaixo. Não seja superficial.
Se alguma informação estiver faltando, assuma o mais razoável e explique.


Issue #{number} — {title}
Labels: {label_str}


{body}


Formato obrigatório de resposta:

## Resultado
(descrição clara e objetiva do que foi feito)

## Entregáveis
(código, estrutura, arquivos ou plano — completo)

## Lógica utilizada
(decisões tomadas e por quê)

## Próximos passos
(o que fazer depois disto)
"""


# Execução automática (Claude Code CLI)


def run_claude_automatic(prompt: str) -> tuple[str, str]:
    """
    Executa o prompt via `claude -p` (não-interativo).
    Retorna (stdout, stderr).
    """
    with tracker.track(
        agent="claude_runner",
        model=CLAUDE_CLI_MODEL,
        action="run_claude_automatic",
        engine_name="claude_runner",
        confidence="observed",
    ) as t:
        proc = subprocess.run(
            ["claude", "-p", "--model", "sonnet"],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=120,
        )
        t.set_tokens(input=0, output=0)  # CLI não expõe usage; apenas latência é rastreada
    return proc.stdout.strip(), proc.stderr.strip()


# Execução manual (fallback)


def run_claude_manual(prompt: str) -> str:
    """Mostra prompt e aguarda o usuário colar a resposta."""
    print("\n PROMPT PARA CLAUDE CODE ")
    print(prompt)
    print("")
    print()
    print(" Cole a resposta do Claude Code abaixo.")
    print(" (quando terminar, digite uma linha só com: END)")
    print()

    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines).strip()


# Validação de qualidade


def validate_result(result: str) -> str:
    """
    Classifica a qualidade do resultado.
    Retorna: 'valid' | 'weak' | 'risky'

    valid → completo, tem todas as seções, tamanho adequado
    weak → faltam seções ou texto curto (pode ser aceito, mas avisa)
    risky → vazio, erro ou muito curto (NÃO fechar issue)
    """
    if not result or len(result) < 50:
        return "risky"

    if len(result) < MIN_RESULT_LENGTH:
        return "risky"

    sections_found = sum(1 for s in REQUIRED_SECTIONS if s in result)

    if sections_found >= 3:
        return "valid"
    if sections_found >= 1:
        return "weak"
    return "risky"


# Persistência local


def _save_result(issue_number: int, result: str, quality: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc)
    payload = {
        "issue_number": issue_number,
        "repo": GITHUB_REPO,
        "executed_at": ts.isoformat(),
        "experiment_quality": quality,
        "result": result,
    }
    path = RESULTS_DIR / f"issue_{issue_number}_{ts.strftime('%Y%m%d_%H%M%S')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


# Comentário no GitHub

QUALITY_LABEL = {
    "valid": " válido",
    "weak": " fraco",
    "risky": " incompleto",
}


def _build_comment(result: str, issue_number: int, quality: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    badge = QUALITY_LABEL.get(quality, quality)
    return f"""## Resultado MYO — Issue #{issue_number}

{result}

---
 Executado automaticamente via `claude_runner.py` em {ts}
 Qualidade: {badge}
 Salvo em `outputs/claude_results/`"""


# Processamento de uma issue


def run_issue(issue: dict, manual: bool = False, auto_close: bool = True):
    number = issue["number"]
    title = issue.get("title", "—")

    print(f"\n{'='*60}")
    print(f" Issue #{number}: {title}")
    print(f"{'='*60}")

    prompt = build_prompt(issue)

    # Execução
    if manual:
        result = run_claude_manual(prompt)
        stderr = ""
    else:
        print(" Executando via Claude Code CLI...")
        try:
            result, stderr = run_claude_automatic(prompt)
        except subprocess.TimeoutExpired:
            print(" Timeout (120s). Tente --manual ou verifique a issue.")
            return
        except FileNotFoundError:
            print(" Claude CLI não encontrado. Use --manual ou verifique a instalação.")
            return

    if stderr and not result:
        print(f" Claude retornou erro:\n{stderr}")
        return

    if stderr:
        print(f" ℹ stderr: {stderr[:120]}")

    if not result:
        print(f" Resposta vazia. Issue #{number} ignorada.")
        return

    # Validação
    quality = validate_result(result)
    quality_label = QUALITY_LABEL.get(quality, quality)
    print(f" Qualidade do resultado: {quality_label}")

    if quality == "risky":
        print(f" Resultado classificado como RISKY — issue #{number} NÃO será fechada.")
        print(" Motivo: resposta vazia, muito curta ou sem seções obrigatórias.")

    # Salvar local
    saved_path = _save_result(number, result, quality)
    print(f" Salvo em: {saved_path}")

    # Postar comentário
    comment_body = _build_comment(result, number, quality)
    try:
        post_comment(number, comment_body)
        print(f" Comentário postado na issue #{number}")
    except httpx.HTTPStatusError as e:
        print(f" Falha ao postar comentário: {e}")

    # Fechar issue (só se qualidade >= weak e auto_close=True)
    if auto_close and quality != "risky":
        try:
            close_issue(number)
            print(f" Issue #{number} fechada")
        except httpx.HTTPStatusError as e:
            print(f" Falha ao fechar issue: {e}")
    elif quality == "risky":
        print(f" ↩ Issue #{number} mantida aberta para revisão/retry.")


# Main


def main():
    _check_config()

    parser = argparse.ArgumentParser(
        description="Claude Runner — executa issues MYO via Claude Code"
    )
    parser.add_argument(
        "--issue", type=int, help="Número da issue específica (default: todas abertas)"
    )
    parser.add_argument(
        "--manual", action="store_true", help="Modo semi-manual: você cola a resposta"
    )
    parser.add_argument("--no-close", action="store_true", help="Não fecha a issue após executar")
    args = parser.parse_args()

    auto_close = not args.no_close

    if args.issue:
        print(f"\n Buscando issue #{args.issue}...")
        issue = get_issue(args.issue)
        if issue.get("state") == "closed":
            print(f" Issue #{args.issue} já está fechada.")
            return
        run_issue(issue, manual=args.manual, auto_close=auto_close)
    else:
        print("\n Buscando issues MYO abertas...")
        issues = fetch_open_issues()

        if not issues:
            print(" Nenhuma issue MYO aberta encontrada.")
            return

        print(f" {len(issues)} issue(s) encontrada(s):\n")
        for iss in issues:
            labels = [lb["name"] for lb in iss.get("labels", [])]
            print(f" #{iss['number']:>4} {iss['title'][:55]} [{', '.join(labels)}]")

        print()
        mode_str = "manual" if args.manual else "automático"
        confirm = input(f" Processar todas no modo {mode_str}? [s/N]: ").strip().lower()
        if confirm != "s":
            print(" Cancelado.")
            return

        for issue in issues:
            run_issue(issue, manual=args.manual, auto_close=auto_close)

    print("\n Concluído.\n")


if __name__ == "__main__":
    main()
