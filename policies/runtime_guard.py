"""
Runtime Guard — LESSON-003
==========================
Aplica context_policy.json em runtime, bloqueando tool uses inseguros
conforme o execution_context (idea/research/mvp/launch_ready/scaling).

Complementa policy_adapter.py (analitico/offline): este modulo faz enforcement
em tempo real durante execucao do claude_runner_v2.

Camadas de decisao (em ordem):
    1. hard_block  -> patroes destrutivos (rm -rf /, fork bomb, etc) — sempre deny
    2. system_path -> escritas em /etc, /usr, /var, /bin, /sbin — sempre deny
    3. contextual  -> rm -rf paths especificos, wget/curl sem auth, etc —
                      deny em launch_ready/scaling, warn em mvp, allow em idea/research
    4. default     -> allow com registro para auditoria
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Reusa fonte unica da verdade do LESSON-002
try:
    from utils.verification_engine import (
        VALID_EXECUTION_CONTEXTS,
        DEFAULT_EXECUTION_CONTEXT,
        normalize_execution_context,
    )
except ImportError:
    # Fallback defensivo: caso verification_engine nao esteja disponivel
    VALID_EXECUTION_CONTEXTS = frozenset({"idea", "research", "mvp", "launch_ready", "scaling"})
    DEFAULT_EXECUTION_CONTEXT = "research"
    def normalize_execution_context(v):
        if not v:
            return DEFAULT_EXECUTION_CONTEXT
        n = str(v).strip().lower()
        if n not in VALID_EXECUTION_CONTEXTS:
            raise ValueError(f"execution_context invalido: {v!r}")
        return n


POLICY_FILE = Path("config/context_policy.json")

# Hard block: padroes destrutivos — sempre deny, independente de contexto
HARD_DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf $HOME",
    "dd if=",
    "mkfs",
    ":(){ :|:& };:",
    "> /dev/sda",
    "chmod -R 777 /",
]

# System paths: escrita aqui e bloqueada em todos contextos
SYSTEM_PATHS = ["/etc/", "/usr/", "/var/", "/bin/", "/sbin/", "/boot/"]

# Contextos com enforcement rigido (bloqueiam operacoes de risco medio)
STRICT_CONTEXTS = {"launch_ready", "scaling"}

# Contextos com enforcement suave (warn em vez de deny para risco medio)
LENIENT_CONTEXTS = {"idea", "research"}


def _hard_block_matches(pattern: str, command: str) -> bool:
    """
    Hard block match: exige que o padrao apareca como token completo,
    nao como prefixo de um path legitimo.

    Exemplos:
      pattern='rm -rf /', command='rm -rf /'            -> True  (destrutivo real)
      pattern='rm -rf /', command='rm -rf /tmp/x'       -> False (path especifico)
      pattern='rm -rf /', command='rm -rf /*'           -> True  (destrutivo)
      pattern='rm -rf ~', command='rm -rf ~'            -> True
      pattern='rm -rf ~', command='rm -rf ~/project'    -> False
      pattern='dd if=', command='dd if=/dev/zero'       -> True  (qualquer dd if=)
      pattern=':(){...', command=':(){ :|:& };:'        -> True  (fork bomb exato)
    """
    # Paths: rm -rf /  ~  $HOME  devem ser o token COMPLETO ou seguidos de wildcard
    if pattern in ("rm -rf /", "rm -rf ~", "rm -rf $HOME"):
        # Permite: 'rm -rf /' exato, 'rm -rf /*', 'rm -rf / ', 'rm -rf /;'
        # Bloqueia: 'rm -rf /tmp/x', 'rm -rf ~/project'
        escaped = re.escape(pattern)
        # (?:$|[\s*;&|]) — fim de string OU whitespace/separador OU asterisco
        regex = escaped + r"(?:$|[\s*;&|])"
        return bool(re.search(regex, command))

    # Demais padroes: substring match mantido (dd if=, mkfs, fork bomb, etc)
    return pattern in command


@dataclass
class GuardDecision:
    allowed: bool
    reason: str = ""
    severity: str = "info"  # info | warn | deny
    rule: str = ""          # qual camada ativou
    context: str = ""

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "severity": self.severity,
            "rule": self.rule,
            "context": self.context,
        }


class RuntimeGuard:
    """Guard runtime que consulta context_policy.json por contexto."""

    def __init__(
        self,
        execution_context: str = DEFAULT_EXECUTION_CONTEXT,
        policy_file: Optional[Path] = None,
    ):
        self.context = normalize_execution_context(execution_context)
        self.policy_file = Path(policy_file) if policy_file else POLICY_FILE
        self._policy = self._load_policy()
        self._ctx_policy = self._policy.get(self.context, {}) if self._policy else {}

    def _load_policy(self) -> dict:
        if not self.policy_file.exists():
            return {}
        try:
            with open(self.policy_file, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    @property
    def has_policy(self) -> bool:
        return bool(self._ctx_policy)

    def evaluate_tool_use(self, tool_name: str, tool_input: dict) -> GuardDecision:
        """Avalia um tool use e retorna GuardDecision."""
        # Camada 1: hard_block
        if tool_name == "Bash":
            command = tool_input.get("command", "") or ""
            for pattern in HARD_DANGEROUS_PATTERNS:
                if _hard_block_matches(pattern, command):
                    return GuardDecision(
                        allowed=False,
                        reason=f"hard_block: padrao destrutivo '{pattern}'",
                        severity="deny",
                        rule="hard_block",
                        context=self.context,
                    )

        # Camada 2: system_path (Write/Edit em paths do sistema)
        if tool_name in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
            path = tool_input.get("file_path", "") or tool_input.get("path", "") or ""
            for sys_path in SYSTEM_PATHS:
                if path.startswith(sys_path):
                    return GuardDecision(
                        allowed=False,
                        reason=f"system_path: escrita em '{sys_path}' proibida",
                        severity="deny",
                        rule="system_path",
                        context=self.context,
                    )

        # Camada 3: contextual (rm -rf com path, rede sem auth, etc)
        contextual = self._evaluate_contextual(tool_name, tool_input)
        if contextual is not None:
            return contextual

        # Camada 4: default allow
        return GuardDecision(
            allowed=True,
            reason="ok",
            severity="info",
            rule="default_allow",
            context=self.context,
        )

    def _evaluate_contextual(self, tool_name: str, tool_input: dict) -> Optional[GuardDecision]:
        """Avalia regras contextuais. Retorna None se nenhuma regra se aplica."""
        if tool_name != "Bash":
            return None

        command = tool_input.get("command", "") or ""

        # rm -rf <path> com path nao-critico
        if re.search(r"\brm\s+-rf?\s+\S+", command):
            if self.context in STRICT_CONTEXTS:
                return GuardDecision(
                    allowed=False,
                    reason=f"rm -rf bloqueado em contexto '{self.context}' (strict)",
                    severity="deny",
                    rule="contextual_destructive",
                    context=self.context,
                )
            elif self.context in LENIENT_CONTEXTS:
                return GuardDecision(
                    allowed=True,
                    reason=f"rm -rf permitido em '{self.context}' com warn",
                    severity="warn",
                    rule="contextual_destructive",
                    context=self.context,
                )
            else:  # mvp
                return GuardDecision(
                    allowed=True,
                    reason=f"rm -rf em 'mvp' — warn",
                    severity="warn",
                    rule="contextual_destructive",
                    context=self.context,
                )

        # api_cost_strict: wget/curl sem autenticacao em contextos que pedem strict
        if self._ctx_policy.get("api_cost_strict") is True:
            net_cmds = ["wget ", "curl "]
            if any(command.strip().startswith(c) for c in net_cmds):
                if "Authorization" not in command and "--user" not in command and "-u " not in command:
                    return GuardDecision(
                        allowed=False,
                        reason=f"api_cost_strict em '{self.context}': rede sem auth bloqueada",
                        severity="deny",
                        rule="contextual_api_strict",
                        context=self.context,
                    )

        return None


def build_hook_response(decision: GuardDecision) -> dict:
    """Converte GuardDecision no formato de resposta esperado pelo claude_agent_sdk."""
    if decision.allowed:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": decision.reason,
        }
    }
