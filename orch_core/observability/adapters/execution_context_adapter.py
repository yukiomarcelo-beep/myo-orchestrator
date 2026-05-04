"""
orch_core.observability.adapters.execution_context_adapter
===========================================================

Implementacao concreta do port ExecutionContext (LESSON-002).

O ExecutionContext do port carrega run_id + tenant_id + metadata imutavel
durante um Run. Nao existe um objeto canonico identico no repo legado —
o mais proximo e AgentContext de core/execution_control.py, mas tem
semantica diferente (sessao por agente, nao por run).

Esta implementacao satisfaz o Protocol diretamente, sendo imutavel via
with_value() (retorna nova instancia). Thread-safe por imutabilidade.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID


class ExecutionContextAdapter:
    """Implementacao imutavel do port ExecutionContext."""

    def __init__(
        self,
        run_id: UUID,
        tenant_id: str,
        _data: dict[str, Any] | None = None,
    ) -> None:
        self._run_id = run_id
        self._tenant_id = tenant_id
        self._data: dict[str, Any] = dict(_data or {})

    @property
    def run_id(self) -> UUID:
        return self._run_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def with_value(self, key: str, value: Any) -> "ExecutionContextAdapter":
        new_data = {**self._data, key: value}
        return ExecutionContextAdapter(self._run_id, self._tenant_id, new_data)

    def __repr__(self) -> str:
        return (
            f"ExecutionContextAdapter(run_id={self._run_id}, "
            f"tenant_id={self._tenant_id!r}, keys={list(self._data)})"
        )


__all__ = ["ExecutionContextAdapter"]
