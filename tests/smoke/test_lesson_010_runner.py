"""
Smoke tests LESSON-010 — Runner canonico.

Cobre 15 casos (minimo exigido >= 15 por ser fase densa):

 1. Run sem tools termina em end_turn e status done
 2. Run com 1 tool call simples completa com sucesso
 3. Run com multiplos tool calls encadeados em rodadas sucessivas
 4. Timeout via max_steps levanta MaxStepsExceeded e status failed
 5. Tool que explode vira tool_result com status error (run nao morre)
 6. Cancelamento cooperativo antes do primeiro step -> status cancelled
 7. Cancelamento no meio da cadeia de tools -> status cancelled
 8. Audit_log grava run.created, run.started, run.step, run.finished
 9. Runtime_guard bloqueia tool danger -> PolicyDenied, run failed
10. ExecutionContext/tenant_id preservado em todos os audit records
11. parent_run_id propaga pro Run e pros audit records
12. Streaming de eventos preserva ordem canonica
13. Idempotencia: runner eh stateless, 2 instancias concorrentes
    nao compartilham estado
14. Failure no meio da chain (stop_reason=error) -> run failed
15. Registry miss (agent nao registrado) -> run failed com AgentNotFound

TODO (Sonnet 4.6 no repo):
- Substituir FakeAudit pelo AuditLog canonico (LESSON-004) via adapter
- Substituir FakeGuard pelo runtime_guard canonico (LESSON-003) via adapter
- Acrescentar smokes de integracao com ExecutionContext (LESSON-002)
"""

from __future__ import annotations

import threading
from uuid import uuid4

from orch_core.contracts import RunSpec
from orch_core.control.registry import Registry
from orch_core.execution import (
    FeatureFlags,
    Runner,
)
from tests.smoke._fakes import (
    BoomTool,
    DangerTool,
    EchoTool,
    FakeAudit,
    FakeEvents,
    FakeGuard,
    ScriptedExecutor,
    SimpleAgent,
)


def _wiring(
    *,
    responses: list | None = None,
    deny_tools: set[str] | None = None,
    flags: FeatureFlags | None = None,
    register_agent: bool = True,
    extra_tools: list | None = None,
):
    reg = Registry()
    agent = SimpleAgent("t1", "agent-x")
    if register_agent:
        reg.register_agent(agent)
    reg.register_tool(EchoTool())
    reg.register_tool(BoomTool())
    reg.register_tool(DangerTool())
    for t in extra_tools or []:
        reg.register_tool(t)

    audit = FakeAudit()
    guard = FakeGuard(deny_tools=deny_tools or set())
    events = FakeEvents()
    executor = ScriptedExecutor(responses or [{"stop_reason": "end_turn", "text": "done"}])

    runner = Runner(
        registry=reg,
        audit=audit,
        guard=guard,
        agent_executor=executor,
        events=events,
        flags=flags or FeatureFlags(shadow_mode=False),
    )
    return runner, reg, audit, guard, events, executor


def _spec(**overrides) -> RunSpec:
    base: RunSpec = {
        "tenant_id": "t1",
        "project_id": "p1",
        "agent_id": "agent-x",
        "input": {"content": "hi"},
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


# 1
def test_run_without_tools_finishes_done() -> None:
    runner, *_ = _wiring(responses=[{"stop_reason": "end_turn", "text": "hello", "tool_calls": []}])
    result = runner.execute(_spec())
    assert result.run.status == "done"
    assert result.error is None
    assert result.output.get("text") == "hello"


# 2
def test_run_with_single_tool_call_completes() -> None:
    runner, *_ = _wiring(
        responses=[
            {
                "stop_reason": "tool_use",
                "text": "calling echo",
                "tool_calls": [{"id": "c1", "name": "echo", "args": {"msg": "oi"}}],
            },
            {"stop_reason": "end_turn", "text": "done", "tool_calls": []},
        ]
    )
    result = runner.execute(_spec())
    assert result.run.status == "done"
    assert len(result.steps) == 3  # 1 message + 1 tool_result + 1 final message
    tool_steps = [s for s in result.steps if s.kind == "tool_result"]
    assert len(tool_steps) == 1
    assert tool_steps[0].payload["status"] == "ok"


# 3
def test_multiple_tool_calls_chained_across_rounds() -> None:
    runner, *_ = _wiring(
        responses=[
            {
                "stop_reason": "tool_use",
                "text": "t1",
                "tool_calls": [{"id": "a", "name": "echo", "args": {"x": 1}}],
            },
            {
                "stop_reason": "tool_use",
                "text": "t2",
                "tool_calls": [{"id": "b", "name": "echo", "args": {"x": 2}}],
            },
            {"stop_reason": "end_turn", "text": "final", "tool_calls": []},
        ]
    )
    result = runner.execute(_spec())
    assert result.run.status == "done"
    tool_steps = [s for s in result.steps if s.kind == "tool_result"]
    assert len(tool_steps) == 2


# 4
def test_max_steps_exceeded_fails_run() -> None:
    # Cria 50 respostas todas com tool_use (forca loop infinito); limite 3
    responses = [
        {
            "stop_reason": "tool_use",
            "text": "loop",
            "tool_calls": [{"id": f"x{i}", "name": "echo", "args": {}}],
        }
        for i in range(50)
    ]
    runner, *_ = _wiring(
        responses=responses,
        flags=FeatureFlags(runner_max_steps=3),
    )
    result = runner.execute(_spec())
    assert result.run.status == "failed"
    assert "exceeded" in (result.error or "").lower()


# 5
def test_tool_error_does_not_kill_run() -> None:
    runner, *_ = _wiring(
        responses=[
            {
                "stop_reason": "tool_use",
                "text": "boom time",
                "tool_calls": [{"id": "b1", "name": "boom", "args": {}}],
            },
            {"stop_reason": "end_turn", "text": "recovered", "tool_calls": []},
        ]
    )
    result = runner.execute(_spec())
    assert result.run.status == "done"
    tool_steps = [s for s in result.steps if s.kind == "tool_result"]
    assert tool_steps[0].payload["status"] == "error"
    assert "boom" in (tool_steps[0].payload["error"] or "")


# 6
def test_cancel_before_first_step() -> None:
    runner, *_ = _wiring(responses=[{"stop_reason": "end_turn", "text": "ok", "tool_calls": []}])
    result = runner.execute(_spec(), is_cancelled=lambda: True)
    assert result.run.status == "cancelled"
    assert "cancelled" in (result.error or "")


# 7
def test_cancel_mid_tool_chain() -> None:
    calls = {"n": 0}

    def cancel_after_first() -> bool:
        calls["n"] += 1
        return calls["n"] > 2  # deixa passar pelos 2 primeiros checks

    runner, *_ = _wiring(
        responses=[
            {
                "stop_reason": "tool_use",
                "text": "t1",
                "tool_calls": [
                    {"id": "c1", "name": "echo", "args": {}},
                    {"id": "c2", "name": "echo", "args": {}},
                ],
            },
            {"stop_reason": "end_turn", "text": "unused", "tool_calls": []},
        ]
    )
    result = runner.execute(_spec(), is_cancelled=cancel_after_first)
    assert result.run.status == "cancelled"


# 8
def test_audit_records_canonical_kinds() -> None:
    runner, _, audit, *_ = _wiring(
        responses=[{"stop_reason": "end_turn", "text": "done", "tool_calls": []}]
    )
    result = runner.execute(_spec())
    kinds = audit.kinds_of(result.run.run_id)
    assert "run.created" in kinds
    assert "run.step" in kinds
    assert "run.finished" in kinds
    # ordem: created antes de step antes de finished
    assert kinds.index("run.created") < kinds.index("run.step")
    assert kinds.index("run.step") < kinds.index("run.finished")


# 9
def test_runtime_guard_blocks_danger_tool() -> None:
    runner, *_ = _wiring(
        responses=[
            {
                "stop_reason": "tool_use",
                "text": "try danger",
                "tool_calls": [{"id": "d1", "name": "danger", "args": {}}],
            }
        ],
        deny_tools={"danger"},
    )
    result = runner.execute(_spec())
    assert result.run.status == "failed"
    assert "danger" in (result.error or "")
    assert "blocked" in (result.error or "").lower()


# 10
def test_tenant_id_preserved_in_audit() -> None:
    runner, _, audit, *_ = _wiring(
        responses=[{"stop_reason": "end_turn", "text": "ok", "tool_calls": []}]
    )
    result = runner.execute(_spec(tenant_id="t1"))
    records = audit.events_of(result.run.run_id)
    assert all(r["tenant_id"] == "t1" for r in records)
    assert len(records) >= 3


# 11
def test_parent_run_id_propagates() -> None:
    parent = uuid4()
    runner, _, audit, *_ = _wiring(
        responses=[{"stop_reason": "end_turn", "text": "ok", "tool_calls": []}]
    )
    result = runner.execute(_spec(parent_run_id=str(parent)))
    assert result.run.parent_run_id == parent
    created = [r for r in audit.events_of(result.run.run_id) if r["kind"] == "run.created"]
    assert created and created[0]["payload"]["parent_run_id"] == str(parent)


# 12
def test_event_stream_canonical_order() -> None:
    runner, _, _, _, events, _ = _wiring(
        responses=[
            {
                "stop_reason": "tool_use",
                "text": "t1",
                "tool_calls": [{"id": "c1", "name": "echo", "args": {}}],
            },
            {"stop_reason": "end_turn", "text": "final", "tool_calls": []},
        ]
    )
    runner.execute(_spec())
    kinds = events.kinds()
    assert kinds[0] == "run.created"
    assert kinds[1] == "run.started"
    assert "run.step" in kinds
    assert kinds[-1] == "run.finished"


# 13
def test_runner_stateless_parallel_runs() -> None:
    # Duas execucoes concorrentes no mesmo Runner nao compartilham estado
    runner, *_ = _wiring(
        responses=[{"stop_reason": "end_turn", "text": "x", "tool_calls": []}] * 20
    )
    results: list = []
    errors: list = []

    def work() -> None:
        try:
            r = runner.execute(_spec())
            results.append(r)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(results) == 10
    # todos os run_ids sao diferentes
    ids = {r.run.run_id for r in results}
    assert len(ids) == 10
    assert all(r.run.status == "done" for r in results)


# 14
def test_agent_returned_error_fails_run() -> None:
    runner, *_ = _wiring(
        responses=[
            {
                "stop_reason": "error",
                "text": None,
                "tool_calls": [],
                "error": "upstream LLM blew up",
            }
        ]
    )
    result = runner.execute(_spec())
    assert result.run.status == "failed"
    assert "upstream" in (result.error or "")


# 15
def test_agent_not_registered_fails_run() -> None:
    runner, *_ = _wiring(
        responses=[{"stop_reason": "end_turn", "text": "x", "tool_calls": []}],
        register_agent=False,
    )
    result = runner.execute(_spec())
    assert result.run.status == "failed"
    assert "agent not found" in (result.error or "").lower()
