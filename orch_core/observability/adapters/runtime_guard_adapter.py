"""
orch_core.observability.adapters.runtime_guard_adapter
=======================================================

Adapter que conecta o port RuntimeGuard ao RuntimeGuard canonico (LESSON-003).

O guard canonico e inicializado com um execution_context fixo (default: "mvp").
O port RuntimeGuard nao tem conceito de execution_context — ele recebe
tenant_id + agent_id + tool_name + args, que sao ignorados no routing
e passados diretamente para evaluate_tool_use.

Mapeamento:
  RuntimeGuard.allow_tool_call(tenant_id, agent_id, tool_name, args)
    -> CanonicalRuntimeGuard.evaluate_tool_use(tool_name, dict(args))
    -> GuardDecision.allowed

  RuntimeGuard.reason()
    -> ultimo GuardDecision.reason, se nao permitido
"""
from __future__ import annotations

from typing import Any, Mapping

from policies.runtime_guard import RuntimeGuard as CanonicalRuntimeGuard


class RuntimeGuardAdapter:
    """Implementa o port RuntimeGuard usando o guard canonico (LESSON-003)."""

    def __init__(self, execution_context: str = "mvp") -> None:
        self._guard = CanonicalRuntimeGuard(execution_context=execution_context)
        self._last_reason: str | None = None

    def allow_tool_call(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        tool_name: str,
        args: Mapping[str, Any],
    ) -> bool:
        decision = self._guard.evaluate_tool_use(tool_name, dict(args))
        if not decision.allowed:
            self._last_reason = decision.reason
        else:
            self._last_reason = None
        return decision.allowed

    def reason(self) -> str | None:
        return self._last_reason


__all__ = ["RuntimeGuardAdapter"]
