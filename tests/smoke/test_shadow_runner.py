"""
Smokes do ShadowRunner (FASE 3 — wave2, LESSON-010).

Casos:
  1. Sem divergencia -> callback nunca chamado
  2. Divergencia de status (done vs failed) -> hard_fail
  3. Divergencia so em text -> soft_fail
  4. Canonico crasha -> canonical_crashed
  5. Caller SEMPRE recebe resultado do legado
  6. Divergencia de tool_names -> hard_fail
  7. policy_denied so no canonico -> hard_fail
"""

from __future__ import annotations

import time
from typing import Any

from orch_core.contracts import RunSpec, new_run
from orch_core.control.registry import Registry
from orch_core.execution.runner import Runner, RunResult
from orch_core.execution.shadow import ShadowRunner
from tests.smoke._fakes import (
    FakeAudit,
    FakeEvents,
    FakeGuard,
    ScriptedExecutor,
    SimpleAgent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SPEC: RunSpec = {
    "tenant_id": "t1",
    "project_id": "p1",
    "agent_id": "agent-x",
    "input": {"content": "oi"},
}


def _make_runner(responses: list[dict]) -> Runner:
    registry = Registry()
    agent = SimpleAgent(tenant_id="t1", agent_id="agent-x")
    registry.register_agent(agent)
    return Runner(
        registry=registry,
        audit=FakeAudit(),
        guard=FakeGuard(),
        agent_executor=ScriptedExecutor(responses),
        events=FakeEvents(),
    )


def _run_result(status: str, text: str = "ok", error: str | None = None) -> RunResult:
    run = new_run(tenant_id="t1", project_id="p1", agent_id="agent-x")
    # transicionar ate o status desejado
    if status in ("running", "done", "failed", "cancelled"):
        run = run.with_status("running")
    if status in ("done", "failed", "cancelled"):
        run = run.with_status(status)
    from uuid import uuid4

    from orch_core.contracts import Step

    steps = []
    if text:
        steps.append(
            Step(
                step_id=uuid4(), run_id=run.run_id, index=0, kind="message", payload={"text": text}
            )
        )
    return RunResult(run=run, steps=steps, output={"text": text}, error=error)


def _make_shadow(
    canonical: Runner | None = None,
    legacy_result: Any = None,
    on_divergence: Any = None,
    canonical_crash: Exception | None = None,
) -> tuple[ShadowRunner, list[dict]]:
    divergences: list[dict] = []

    if on_divergence is None:
        on_divergence = divergences.append

    if canonical is None:
        canonical = _make_runner([{"stop_reason": "end_turn", "text": "ok", "tool_calls": []}])

    if legacy_result is None:
        legacy_result = _run_result("done", "ok")

    def _legacy(_spec: RunSpec) -> Any:
        if canonical_crash is not None:
            # Faz o canonico crashar substituindo execute
            original_execute = canonical.execute

            def crashing_execute(*a, **kw):
                raise canonical_crash

            canonical.execute = crashing_execute
        return legacy_result

    shadow = ShadowRunner(
        canonical=canonical,
        legacy=_legacy,
        on_divergence=on_divergence,
    )
    return shadow, divergences


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------


class TestShadowRunnerNoDivergence:
    def test_no_divergence_callback_never_called(self):
        canonical = _make_runner([{"stop_reason": "end_turn", "text": "ok", "tool_calls": []}])
        divergences: list[dict] = []
        shadow = ShadowRunner(
            canonical=canonical,
            legacy=lambda _spec: _run_result("done", "ok"),
            on_divergence=divergences.append,
        )
        result = shadow.execute(_SPEC)
        time.sleep(0.3)  # deixa a thread shadow terminar
        assert result is not None
        assert divergences == []


class TestShadowRunnerStatusDivergence:
    def test_status_hard_fail(self):
        # legado retorna done, canonico vai retornar failed (sem agent registrado)
        registry = Registry()  # agent-x nao registrado -> OrchError
        canonical = Runner(
            registry=registry,
            audit=FakeAudit(),
            guard=FakeGuard(),
            agent_executor=ScriptedExecutor([]),
        )
        divergences: list[dict] = []
        shadow = ShadowRunner(
            canonical=canonical,
            legacy=lambda _spec: _run_result("done", "ok"),
            on_divergence=divergences.append,
        )
        shadow.execute(_SPEC)
        time.sleep(0.3)
        assert len(divergences) == 1
        assert divergences[0]["kind"] == "hard_fail"
        assert divergences[0]["field"] == "status"
        assert divergences[0]["legacy"] == "done"
        assert divergences[0]["canonical"] == "failed"


class TestShadowRunnerTextDivergence:
    def test_text_soft_fail(self):
        canonical = _make_runner(
            [{"stop_reason": "end_turn", "text": "resultado diferente", "tool_calls": []}]
        )
        divergences: list[dict] = []
        shadow = ShadowRunner(
            canonical=canonical,
            legacy=lambda _spec: _run_result("done", "texto do legado"),
            on_divergence=divergences.append,
        )
        shadow.execute(_SPEC)
        time.sleep(0.3)
        assert len(divergences) == 1
        assert divergences[0]["kind"] == "soft_fail"
        assert divergences[0]["field"] == "text"


class TestShadowRunnerCanonicalCrash:
    def test_canonical_crash_reports_canonical_crashed(self):
        divergences: list[dict] = []

        def _crashing_execute(*a, **kw):
            raise RuntimeError("boom inesperado")

        canonical = _make_runner([{"stop_reason": "end_turn", "text": "ok", "tool_calls": []}])
        canonical.execute = _crashing_execute

        shadow = ShadowRunner(
            canonical=canonical,
            legacy=lambda _spec: _run_result("done", "ok"),
            on_divergence=divergences.append,
        )
        shadow.execute(_SPEC)
        time.sleep(0.3)
        assert len(divergences) == 1
        assert divergences[0]["kind"] == "canonical_crashed"
        assert "RuntimeError" in divergences[0]["error"]


class TestShadowRunnerLegacyAlwaysReturned:
    def test_caller_always_receives_legacy_result(self):
        legacy_result = _run_result("done", "resposta do legado")
        canonical = _make_runner(
            [{"stop_reason": "end_turn", "text": "algo diferente", "tool_calls": []}]
        )
        shadow = ShadowRunner(
            canonical=canonical,
            legacy=lambda _spec: legacy_result,
            on_divergence=lambda _d: None,
        )
        result = shadow.execute(_SPEC)
        assert result is legacy_result

    def test_canonical_crash_does_not_affect_caller(self):
        legacy_result = _run_result("done", "legado ok")

        def _crashing_execute(*a, **kw):
            raise SystemError("crash severo")

        canonical = _make_runner([])
        canonical.execute = _crashing_execute
        shadow = ShadowRunner(
            canonical=canonical,
            legacy=lambda _spec: legacy_result,
            on_divergence=lambda _d: None,
        )
        result = shadow.execute(_SPEC)
        assert result is legacy_result  # crash no canonico nao afeta o caller
