"""
Smoke tests LESSON-011 — Scheduler + Session.

Cobre 12 casos (minimo exigido >= 8):

 1. submit() devolve run_id imediato e nao-bloqueante
 2. status() transita pending -> running -> done
 3. cancel() em run running -> status cancelled
 4. cancel() em run ja done eh no-op (retorna False)
 5. stream() produz eventos na ordem canonica
 6. Multiplos runs concorrentes nao vazam estado entre si
 7. tenant isolation no status (tenant B nao enxerga run de tenant A)
 8. tenant isolation no stream (idem)
 9. list_runs filtra por tenant + project + status
10. parent_run_id propaga via submit
11. result() bloqueia ate terminar e devolve RunResult
12. close() termina pool limpo, submits posteriores falham
"""
from __future__ import annotations

import time
from uuid import uuid4

import pytest

from orch_core.contracts import (
    RunSpec,
    TenantIsolationViolation,
)
from orch_core.control.registry import Registry
from orch_core.control.scheduler import Scheduler, SchedulerError
from orch_core.control.session import SessionStore
from orch_core.execution import FeatureFlags, Runner
from orch_core.observability.event_bus import InMemoryEventBus
from tests.smoke._fakes import (
    EchoTool,
    FakeAudit,
    FakeGuard,
    ScriptedExecutor,
    SimpleAgent,
)


def _wiring(
    *,
    responses: list | None = None,
    max_workers: int = 4,
    tenant_quotas: dict | None = None,
):
    reg = Registry()
    reg.register_agent(SimpleAgent("t1", "agent-x"))
    reg.register_agent(SimpleAgent("t2", "agent-y"))
    reg.register_tool(EchoTool())

    store = SessionStore()
    bus = InMemoryEventBus()

    runner = Runner(
        registry=reg,
        audit=FakeAudit(),
        guard=FakeGuard(),
        agent_executor=ScriptedExecutor(
            responses or [{"stop_reason": "end_turn", "text": "ok", "tool_calls": []}]
        ),
        events=bus,
        flags=FeatureFlags(),
    )
    scheduler = Scheduler(
        runner=runner,
        store=store,
        event_bus=bus,
        max_workers=max_workers,
        tenant_quotas=tenant_quotas,
    )
    return scheduler, reg, store, bus


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
def test_submit_returns_run_id_immediately() -> None:
    scheduler, *_ = _wiring()
    run_id = scheduler.submit(_spec())
    assert run_id is not None
    # Consumir o resultado pra ThreadPool nao reclamar no teardown
    scheduler.result(run_id, timeout=5)
    scheduler.close()


# 2
def test_status_transitions_to_done() -> None:
    # Resposta com pequeno delay pra capturar "running"
    class DelayedExec:
        def __init__(self) -> None:
            self.calls = 0

        def step(self, *, run, messages, tools):
            time.sleep(0.05)
            return {"stop_reason": "end_turn", "text": "done", "tool_calls": []}

    reg = Registry()
    reg.register_agent(SimpleAgent("t1", "agent-x"))
    reg.register_tool(EchoTool())
    bus = InMemoryEventBus()
    runner = Runner(
        registry=reg,
        audit=FakeAudit(),
        guard=FakeGuard(),
        agent_executor=DelayedExec(),
        events=bus,
    )
    sched = Scheduler(runner=runner, event_bus=bus, max_workers=2)

    run_id = sched.submit(_spec())
    # Logo apos submit, status pode ser pending ou running
    early = sched.status(run_id).status
    assert early in ("pending", "running")
    sched.result(run_id, timeout=5)
    final = sched.status(run_id).status
    assert final == "done"
    sched.close()


# 3
def test_cancel_running_run() -> None:
    # Executor que nunca termina ate ser cancelado
    class SpinExec:
        def step(self, *, run, messages, tools):
            # forca loop tool_use indefinido
            return {
                "stop_reason": "tool_use",
                "text": "loop",
                "tool_calls": [{"id": str(uuid4()), "name": "echo", "args": {}}],
            }

    reg = Registry()
    reg.register_agent(SimpleAgent("t1", "agent-x"))
    reg.register_tool(EchoTool())
    bus = InMemoryEventBus()
    runner = Runner(
        registry=reg,
        audit=FakeAudit(),
        guard=FakeGuard(),
        agent_executor=SpinExec(),
        events=bus,
        flags=FeatureFlags(runner_max_steps=10_000),
    )
    sched = Scheduler(runner=runner, event_bus=bus, max_workers=2)

    run_id = sched.submit(_spec())
    time.sleep(0.05)  # deixa comecar
    signaled = sched.cancel(run_id)
    assert signaled is True
    sched.result(run_id, timeout=5)
    final = sched.status(run_id).status
    assert final == "cancelled"
    sched.close()


# 4
def test_cancel_done_is_noop() -> None:
    scheduler, *_ = _wiring()
    run_id = scheduler.submit(_spec())
    scheduler.result(run_id, timeout=5)
    # Ja terminou
    assert scheduler.status(run_id).status == "done"
    signaled = scheduler.cancel(run_id)
    assert signaled is False
    scheduler.close()


# 5
def test_stream_events_canonical_order() -> None:
    scheduler, *_ = _wiring(
        responses=[
            {"stop_reason": "end_turn", "text": "final", "tool_calls": []}
        ]
    )
    run_id = scheduler.submit(_spec())
    kinds = [ev.kind for ev in scheduler.stream(run_id, timeout=5)]
    assert kinds[0] == "run.created"
    assert "run.started" in kinds
    assert "run.step" in kinds
    assert kinds[-1] == "run.finished"
    scheduler.close()


# 6
def test_concurrent_runs_isolated() -> None:
    scheduler, *_ = _wiring(
        responses=[
            {"stop_reason": "end_turn", "text": "ok", "tool_calls": []}
        ]
        * 50,
        max_workers=8,
    )
    ids = [scheduler.submit(_spec()) for _ in range(10)]
    results = [scheduler.result(rid, timeout=5) for rid in ids]
    # Cada run com run_id unico
    assert len({r.run.run_id for r in results}) == 10
    assert all(r.run.status == "done" for r in results)
    scheduler.close()


# 7
def test_tenant_isolation_on_status() -> None:
    scheduler, *_ = _wiring()
    run_id = scheduler.submit(_spec(tenant_id="t1"))
    scheduler.result(run_id, timeout=5)

    # Mesmo tenant: funciona
    assert scheduler.status(run_id, tenant_id="t1").status == "done"
    # Tenant diferente: bloqueia
    with pytest.raises(TenantIsolationViolation):
        scheduler.status(run_id, tenant_id="t2")
    scheduler.close()


# 8
def test_tenant_isolation_on_stream() -> None:
    scheduler, *_ = _wiring()
    run_id = scheduler.submit(_spec(tenant_id="t1"))
    scheduler.result(run_id, timeout=5)

    # Tenant certo: stream abre
    evs = list(scheduler.stream(run_id, tenant_id="t1", timeout=5))
    assert len(evs) >= 3
    # Tenant errado: bloqueia
    with pytest.raises(TenantIsolationViolation):
        list(scheduler.stream(run_id, tenant_id="t2", timeout=5))
    scheduler.close()


# 9
def test_list_runs_filters() -> None:
    scheduler, *_ = _wiring()
    r1 = scheduler.submit(_spec(tenant_id="t1", project_id="p1"))
    r2 = scheduler.submit(_spec(tenant_id="t1", project_id="p2"))
    r3 = scheduler.submit(_spec(tenant_id="t2", project_id="p1", agent_id="agent-y"))

    for rid in (r1, r2, r3):
        scheduler.result(rid, timeout=5)

    t1_all = scheduler.list_runs("t1")
    assert {r.run_id for r in t1_all} == {r1, r2}

    t1_p1 = scheduler.list_runs("t1", project_id="p1")
    assert {r.run_id for r in t1_p1} == {r1}

    t1_done = scheduler.list_runs("t1", status="done")
    assert {r.run_id for r in t1_done} == {r1, r2}

    scheduler.close()


# 10
def test_parent_run_id_propagates_through_scheduler() -> None:
    scheduler, *_ = _wiring()
    parent = uuid4()
    run_id = scheduler.submit(_spec(parent_run_id=str(parent)))
    scheduler.result(run_id, timeout=5)
    run = scheduler.status(run_id)
    assert run.parent_run_id == parent
    scheduler.close()


# 11
def test_result_blocks_until_done() -> None:
    scheduler, *_ = _wiring(
        responses=[
            {"stop_reason": "end_turn", "text": "blocking test", "tool_calls": []}
        ]
    )
    run_id = scheduler.submit(_spec())
    result = scheduler.result(run_id, timeout=5)
    assert result.run.status == "done"
    assert result.output.get("text") == "blocking test"
    scheduler.close()


# 12
def test_close_blocks_further_submits() -> None:
    scheduler, *_ = _wiring()
    run_id = scheduler.submit(_spec())
    scheduler.result(run_id, timeout=5)
    scheduler.close()
    with pytest.raises(SchedulerError, match="closed"):
        scheduler.submit(_spec())
