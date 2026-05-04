"""
orch_core.execution.shadow
==========================

ShadowRunner — dark-launch do Runner canonico (LESSON-010).

Logica:
- execute() chama o legado de forma sincrona e retorna o resultado imediatamente.
- Em thread daemon separada, executa o canonico com o mesmo RunSpec.
- Compara os dois resultados e chama on_divergence se houver diferenca.

Criterios de comparacao:
- hard_fail  : status diverge, lista de tool_names diverge, policy_denied em um so
- soft_fail  : texto diverge, numero de steps difere por +/-1
- ignore     : run_id, step_id, timestamps, event_id (sempre diferentes)

O caller SEMPRE recebe o resultado do legado. O canonico corre em
background — crash no canonico nunca afeta o caller.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from orch_core.contracts import RunSpec
from orch_core.execution.runner import Runner, RunResult


class ShadowRunner:
    """Executa o legado como primario e o canonico em shadow."""

    def __init__(
        self,
        *,
        canonical: Runner,
        legacy: Callable[[RunSpec], Any],
        on_divergence: Callable[[dict[str, Any]], None],
    ) -> None:
        self._canonical = canonical
        self._legacy = legacy
        self._on_divergence = on_divergence

    def execute(self, spec: RunSpec) -> Any:
        legacy_result = self._legacy(spec)
        t = threading.Thread(
            target=self._shadow,
            args=(spec, legacy_result),
            daemon=True,
        )
        t.start()
        return legacy_result

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    def _shadow(self, spec: RunSpec, legacy_result: Any) -> None:
        try:
            canonical_result = self._canonical.execute(spec)
            diff = self._compare(legacy_result, canonical_result)
            if diff:
                self._on_divergence(diff)
        except BaseException as exc:  # noqa: BLE001
            self._on_divergence(
                {
                    "kind": "canonical_crashed",
                    "error": type(exc).__name__ + ": " + str(exc),
                }
            )

    @staticmethod
    def _compare(legacy: Any, canon: RunResult) -> dict[str, Any] | None:
        """Retorna dict de divergencia ou None se tudo ok."""
        diffs: dict[str, Any] = {}

        # Extrair status do legado — pode ser RunResult ou dict ou qualquer coisa
        legacy_status = _extract_status(legacy)
        canon_status = canon.run.status

        if legacy_status is not None and legacy_status != canon_status:
            diffs["kind"] = "hard_fail"
            diffs["field"] = "status"
            diffs["legacy"] = legacy_status
            diffs["canonical"] = canon_status
            return diffs

        # policy_denied: canonico falhou com erro de policy enquanto legado nao
        legacy_error = _extract_error(legacy)
        canon_error = canon.error
        legacy_policy = legacy_error is not None and "policy" in str(legacy_error).lower()
        canon_policy = canon_error is not None and "policy" in str(canon_error).lower()
        if legacy_policy != canon_policy:
            diffs["kind"] = "hard_fail"
            diffs["field"] = "policy_denied"
            diffs["legacy_policy"] = legacy_policy
            diffs["canonical_policy"] = canon_policy
            return diffs

        # tool_names: lista de tools chamados
        legacy_tools = _extract_tool_names(legacy)
        canon_tools = [
            s.payload.get("tool_name", "") for s in canon.steps if s.kind == "tool_result"
        ]
        if legacy_tools is not None and sorted(legacy_tools) != sorted(canon_tools):
            diffs["kind"] = "hard_fail"
            diffs["field"] = "tool_names"
            diffs["legacy"] = legacy_tools
            diffs["canonical"] = canon_tools
            return diffs

        # soft_fail: texto diverge
        legacy_text = _extract_text(legacy)
        canon_text = _extract_text(canon)
        if legacy_text is not None and canon_text is not None and legacy_text != canon_text:
            diffs["kind"] = "soft_fail"
            diffs["field"] = "text"
            diffs["legacy"] = legacy_text[:200]
            diffs["canonical"] = canon_text[:200]
            return diffs

        # soft_fail: numero de steps difere por mais de 1
        legacy_steps = _extract_step_count(legacy)
        canon_steps = len(canon.steps)
        if legacy_steps is not None and abs(legacy_steps - canon_steps) > 1:
            diffs["kind"] = "soft_fail"
            diffs["field"] = "step_count"
            diffs["legacy"] = legacy_steps
            diffs["canonical"] = canon_steps
            return diffs

        return None


# ---------------------------------------------------------------------------
# Helpers de extracao — o resultado do legado pode ser qualquer shape
# ---------------------------------------------------------------------------


def _extract_status(result: Any) -> str | None:
    if isinstance(result, RunResult):
        return result.run.status
    if isinstance(result, dict):
        return result.get("status")
    return None


def _extract_error(result: Any) -> str | None:
    if isinstance(result, RunResult):
        return result.error
    if isinstance(result, dict):
        return result.get("error")
    return None


def _extract_text(result: Any) -> str | None:
    if isinstance(result, RunResult):
        output = result.output
        return output.get("text") if isinstance(output, dict) else None
    if isinstance(result, dict):
        return result.get("text")
    return None


def _extract_tool_names(result: Any) -> list[str] | None:
    if isinstance(result, RunResult):
        return [s.payload.get("tool_name", "") for s in result.steps if s.kind == "tool_result"]
    if isinstance(result, dict):
        return result.get("tool_names")
    return None


def _extract_step_count(result: Any) -> int | None:
    if isinstance(result, RunResult):
        return len(result.steps)
    if isinstance(result, dict):
        steps = result.get("steps")
        if isinstance(steps, list):
            return len(steps)
        count = result.get("step_count")
        if isinstance(count, int):
            return count
    return None


__all__ = ["ShadowRunner"]
