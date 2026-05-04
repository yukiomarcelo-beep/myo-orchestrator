"""
orch_core.execution.policy
===========================

Adaptador fino sobre RuntimeGuard (LESSON-003) e policy_adapter
(LESSON-006). Ponto unico onde o Runner consulta "posso fazer isso?".

Invariante:
- Runner NUNCA chama RuntimeGuard direto. Passa sempre por enforce().
- Se bloqueado, levanta PolicyDenied com razao estruturada.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from orch_core.contracts import OrchError, Run
from orch_core.observability.ports import RuntimeGuard


class PolicyDenied(OrchError):
    """Levantada quando runtime_guard bloqueia uma tool call."""

    def __init__(self, reason: str, *, tool_name: str, run_id: str) -> None:
        super().__init__(
            f"policy denied tool '{tool_name}' on run {run_id}: {reason}"
        )
        self.reason = reason
        self.tool_name = tool_name
        self.run_id = run_id


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str | None = None


def enforce_tool_call(
    *,
    guard: RuntimeGuard,
    run: Run,
    tool_name: str,
    args: Mapping[str, Any],
) -> PolicyDecision:
    """Consulta o guard. Retorna decisao estruturada.

    Runner decide se abre excecao ou apenas registra no audit_log.
    """
    allowed = guard.allow_tool_call(
        tenant_id=run.tenant_id,
        agent_id=run.agent_id,
        tool_name=tool_name,
        args=args,
    )
    if allowed:
        return PolicyDecision(allowed=True)
    return PolicyDecision(
        allowed=False, reason=guard.reason() or "denied by runtime_guard"
    )


__all__ = ["PolicyDecision", "PolicyDenied", "enforce_tool_call"]
