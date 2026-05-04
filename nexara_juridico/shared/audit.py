"""
shared/audit.py — Auditoria de segurança do Nexara

Logging estruturado separado do log de custo do Cost Guard.
Razão da separação: log de custo serve para finanças/CFO; log de segurança
serve para incidente/forense — perfis de acesso e retenção diferentes.

Formato: JSONL append-only com fcntl lock (mesmo padrão do Cost Guard).
Localização: logs/security.jsonl

Uso típico:

    from shared.audit import log_event, log_anomaly, log_tool_call

    log_event(
        agent="pesquisador",
        action="web_fetch",
        url="https://stf.jus.br/...",
        result="ok",
    )

    log_anomaly(
        agent="analisador",
        flags=["OVERRIDE_INSTRUCTION", "ROLE_HIJACK"],
        content_hash="sha256:abc123...",
        source="pdf_cliente",
    )
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Diretório de log relativo à raiz do projeto Nexara
_LOG_DIR = Path(os.environ.get("NEXARA_LOG_DIR", "logs"))
_LOG_FILE = _LOG_DIR / "security.jsonl"


def _ensure_log_dir() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_content(content: str | bytes) -> str:
    """SHA-256 truncado para 16 chars — identifica conteúdo sem armazenar PII."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return "sha256:" + hashlib.sha256(content).hexdigest()[:16]


def _write_event(event: dict[str, Any]) -> None:
    """Append thread-safe ao log de segurança."""
    _ensure_log_dir()
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(_LOG_FILE, "a", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


# ─────────────────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────────────────


def log_event(
    agent: str,
    action: str,
    *,
    session_id: str | None = None,
    result: str = "ok",
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """Evento genérico — chamada de tool, decisão tomada, etc."""
    event = {
        "ts": _ts(),
        "type": "event",
        "agent": agent,
        "action": action,
        "result": result,
        "session_id": session_id,
    }
    if metadata:
        event["metadata"] = metadata
    event.update(kwargs)
    _write_event(event)


def log_tool_call(
    agent: str,
    tool: str,
    *,
    session_id: str | None = None,
    args_summary: dict[str, Any] | None = None,
    result_summary: str | None = None,
    duration_ms: float | None = None,
) -> None:
    """Registra uma chamada de tool com sumário sanitizado dos args."""
    event = {
        "ts": _ts(),
        "type": "tool_call",
        "agent": agent,
        "tool": tool,
        "session_id": session_id,
    }
    if args_summary is not None:
        event["args_summary"] = args_summary
    if result_summary is not None:
        event["result_summary"] = result_summary[:500]
    if duration_ms is not None:
        event["duration_ms"] = round(duration_ms, 2)
    _write_event(event)


def log_url_fetch(
    agent: str,
    url: str,
    *,
    session_id: str | None = None,
    status: str,  # "allowed" | "blocked" | "out_of_whitelist"
    domain: str | None = None,
) -> None:
    """Registra cada tentativa de fetch — independente de ter passado ou não."""
    event = {
        "ts": _ts(),
        "type": "url_fetch",
        "agent": agent,
        "url": url[:300],
        "domain": domain,
        "status": status,
        "session_id": session_id,
    }
    _write_event(event)


def log_anomaly(
    agent: str,
    flags: list[str] | list[Any],  # FlagInjection ou strings
    *,
    session_id: str | None = None,
    content_hash: str | None = None,
    content: str | None = None,
    source: str = "unknown",  # ex: "pdf_cliente", "web_search", "user_input"
    severity: str = "medium",  # low | medium | high | critical
) -> None:
    """
    Registra anomalia detectada (prompt injection suspeito, etc).

    Se content for fornecido (e content_hash não), gera hash automaticamente.
    NÃO armazena o conteúdo cru — apenas hash + flags + tag de fonte.
    """
    if content_hash is None and content is not None:
        content_hash = _hash_content(content)

    # Normalizar flags — aceita FlagInjection ou strings
    flags_norm = []
    for f in flags:
        if hasattr(f, "tag"):
            flags_norm.append(
                {
                    "tag": f.tag,
                    "trecho": f.trecho[:120],
                    "posicao": f.posicao,
                }
            )
        else:
            flags_norm.append({"tag": str(f)})

    event = {
        "ts": _ts(),
        "type": "anomaly",
        "agent": agent,
        "severity": severity,
        "source": source,
        "content_hash": content_hash,
        "flags": flags_norm,
        "session_id": session_id,
    }
    _write_event(event)


def log_decision(
    agent: str,
    decision: str,  # ex: "allow", "deny", "escalate"
    *,
    reason: str,
    session_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Registra decisão de segurança tomada pelo agente ou middleware."""
    event = {
        "ts": _ts(),
        "type": "decision",
        "agent": agent,
        "decision": decision,
        "reason": reason,
        "session_id": session_id,
    }
    if context:
        event["context"] = context
    _write_event(event)
