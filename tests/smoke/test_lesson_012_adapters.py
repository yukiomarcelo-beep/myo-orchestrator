"""
Smoke tests LESSON-012 — Adapters legados.

Cobre 14 casos:

 1. DeprecationWarning eh emitido pelo shim legacy
 2. DeprecationRegistry conta callers corretamente
 3. ORCH_DEPRECATION_SILENT silencia warning mas NAO o log estruturado
 4. LegacyOrchestratorShim.run_agent delega pro Scheduler e retorna shape legado
 5. LegacyOrchestratorShim.execute extrai ultima mensagem user
 6. MasterControllerShim.start_session retorna session_id string
 7. MasterControllerShim.send_message levanta NotImplementedError claro
 8. MasterControllerShim.end_session cancela via Scheduler
 9. MasterControllerShim.get_session_status funciona
10. WarRoomAdapter.handle_submit valida campos obrigatorios
11. WarRoomAdapter.handle_status respeita tenant isolation
12. WarRoomAdapter.stream_sse formata chunks SSE validos
13. format_sse_event produz chunk parseavel
14. async_stream entrega eventos em AsyncIterator
"""

from __future__ import annotations

import asyncio
import json
import warnings

import pytest

from orch_core.adapters import (
    LegacyOrchestratorShim,
    MasterControllerShim,
    WarRoomAdapter,
    async_stream,
    default_deprecation_registry,
    emit_deprecation,
    format_sse_event,
    reset_deprecation_registry,
)
from orch_core.contracts import TenantIsolationViolation
from orch_core.control.registry import Registry
from orch_core.control.scheduler import Scheduler
from orch_core.execution import FeatureFlags, Runner
from orch_core.observability.event_bus import InMemoryEventBus
from tests.smoke._fakes import (
    EchoTool,
    FakeAudit,
    FakeGuard,
    ScriptedExecutor,
    SimpleAgent,
)


def _wiring(*, responses: list | None = None):
    reg = Registry()
    reg.register_agent(SimpleAgent("t1", "agent-x"))
    reg.register_agent(SimpleAgent("t2", "agent-y"))
    reg.register_tool(EchoTool())
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
    scheduler = Scheduler(runner=runner, event_bus=bus, max_workers=4)
    return scheduler, reg, bus


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_deprecation_registry()
    yield
    reset_deprecation_registry()


@pytest.fixture(autouse=True)
def _reset_silent_env(monkeypatch):
    monkeypatch.delenv("ORCH_DEPRECATION_SILENT", raising=False)
    yield


# 1
def test_deprecation_warning_emitted() -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        emit_deprecation(shim="test.shim", replacement="test.new")
    assert any(issubclass(w.category, DeprecationWarning) for w in captured)
    msgs = [str(w.message) for w in captured]
    assert any("test.shim" in m and "test.new" in m for m in msgs)


# 2
def test_deprecation_registry_counts() -> None:
    reg = default_deprecation_registry()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        emit_deprecation(shim="x", replacement="y")
        emit_deprecation(shim="x", replacement="y")
        emit_deprecation(shim="z", replacement="y")
    snap = reg.snapshot()
    assert sum(v for (s, _), v in snap.items() if s == "x") == 2
    assert sum(v for (s, _), v in snap.items() if s == "z") == 1


# 3
def test_silent_env_suppresses_warning_but_not_log(monkeypatch, caplog) -> None:
    monkeypatch.setenv("ORCH_DEPRECATION_SILENT", "1")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        with caplog.at_level("INFO", logger="orch_core.deprecation"):
            emit_deprecation(shim="silent.shim", replacement="new")
    assert not any(issubclass(w.category, DeprecationWarning) for w in captured)
    # Log estruturado ainda acontece
    assert any(
        "silent.shim" in r.message or (hasattr(r, "shim") and r.shim == "silent.shim")
        for r in caplog.records
    )


# 4
def test_legacy_shim_run_agent_delegates() -> None:
    scheduler, *_ = _wiring(
        responses=[{"stop_reason": "end_turn", "text": "legacy works", "tool_calls": []}]
    )
    shim = LegacyOrchestratorShim(
        scheduler=scheduler,
        default_tenant="t1",
        default_project="p1",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = shim.run_agent("agent-x", {"content": "oi"}, timeout=5)
    assert result["status"] == "done"
    assert result["agent_id"] == "agent-x"
    assert result["tenant_id"] == "t1"
    assert result["output"]["text"] == "legacy works"
    scheduler.close()


# 5
def test_legacy_shim_execute_extracts_last_user_message() -> None:
    scheduler, *_ = _wiring(
        responses=[{"stop_reason": "end_turn", "text": "extracted", "tool_calls": []}]
    )
    shim = LegacyOrchestratorShim(scheduler=scheduler, default_tenant="t1", default_project="p1")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = shim.execute(
            "agent-x",
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "primeiro"},
                {"role": "assistant", "content": "bla"},
                {"role": "user", "content": "ultimo"},
            ],
        )
    assert result["status"] == "done"
    scheduler.close()


# 6
def test_master_shim_start_session_returns_str() -> None:
    scheduler, *_ = _wiring()
    shim = MasterControllerShim(scheduler=scheduler, default_tenant="t1", default_project="p1")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        sid = shim.start_session("agent-x", {"content": "hi"})
    assert isinstance(sid, str)
    # Limpar o run
    scheduler.result(__import__("uuid").UUID(sid), timeout=5)
    scheduler.close()


# 7
def test_master_shim_send_message_raises() -> None:
    scheduler, *_ = _wiring()
    shim = MasterControllerShim(scheduler=scheduler, default_tenant="t1", default_project="p1")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with pytest.raises(NotImplementedError, match="send_message"):
            shim.send_message("any-id", {"text": "oi"})
    scheduler.close()


# 8
def test_master_shim_end_session_cancels() -> None:
    # Loop infinito pra ter algo pra cancelar
    class SpinExec:
        def step(self, *, run, messages, tools):
            return {
                "stop_reason": "tool_use",
                "text": "loop",
                "tool_calls": [{"id": "x", "name": "echo", "args": {}}],
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
        flags=FeatureFlags(runner_max_steps=100000),
    )
    sched = Scheduler(runner=runner, event_bus=bus, max_workers=2)
    shim = MasterControllerShim(scheduler=sched, default_tenant="t1", default_project="p1")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        sid = shim.start_session("agent-x")
        import time

        time.sleep(0.05)
        signaled = shim.end_session(sid)
    assert signaled is True
    sched.close()


# 9
def test_master_shim_status() -> None:
    scheduler, *_ = _wiring()
    shim = MasterControllerShim(scheduler=scheduler, default_tenant="t1", default_project="p1")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        sid = shim.start_session("agent-x")
        # aguarda conclusao
        scheduler.result(__import__("uuid").UUID(sid), timeout=5)
        status = shim.get_session_status(sid)
    assert status == "done"
    scheduler.close()


# 10
def test_war_room_handle_submit_validates() -> None:
    scheduler, *_ = _wiring()
    wr = WarRoomAdapter(scheduler=scheduler)
    with pytest.raises(ValueError, match="agent_id"):
        wr.handle_submit({"tenant_id": "t1", "project_id": "p1"})
    with pytest.raises(ValueError, match="tenant_id"):
        wr.handle_submit({"project_id": "p1", "agent_id": "agent-x"})
    scheduler.close()


# 11
def test_war_room_handle_status_tenant_isolation() -> None:
    scheduler, *_ = _wiring()
    wr = WarRoomAdapter(scheduler=scheduler)
    resp = wr.handle_submit(
        {
            "tenant_id": "t1",
            "project_id": "p1",
            "agent_id": "agent-x",
            "input": {"content": "hi"},
        }
    )
    run_id = resp["run_id"]
    scheduler.result(__import__("uuid").UUID(run_id), timeout=5)

    ok = wr.handle_status(run_id, tenant_id="t1")
    assert ok["status"] == "done"
    with pytest.raises(TenantIsolationViolation):
        wr.handle_status(run_id, tenant_id="t2")
    scheduler.close()


# 12
def test_war_room_stream_sse_valid_chunks() -> None:
    scheduler, *_ = _wiring()
    wr = WarRoomAdapter(scheduler=scheduler)
    resp = wr.handle_submit(
        {
            "tenant_id": "t1",
            "project_id": "p1",
            "agent_id": "agent-x",
            "input": {"content": "hi"},
        }
    )
    chunks = list(wr.stream_sse(resp["run_id"], tenant_id="t1", timeout=5))
    assert len(chunks) >= 3
    for c in chunks:
        assert c.startswith("event: ")
        assert "\ndata: " in c
        assert c.endswith("\n\n")
    # o ultimo chunk eh terminal
    assert (
        "run.finished" in chunks[-1] or "run.failed" in chunks[-1] or "run.cancelled" in chunks[-1]
    )
    scheduler.close()


# 13
def test_format_sse_event_parseable() -> None:
    from uuid import uuid4

    from orch_core.contracts import Event

    ev = Event(
        event_id=uuid4(),
        run_id=uuid4(),
        kind="run.step",
        payload={"x": 1},
    )
    chunk = format_sse_event(ev)
    # Extrai o JSON da linha "data: ..."
    data_line = next(ln for ln in chunk.split("\n") if ln.startswith("data: "))
    parsed = json.loads(data_line[len("data: ") :])
    assert parsed["kind"] == "run.step"
    assert parsed["payload"]["x"] == 1


# 14
def test_async_stream_yields_events() -> None:
    scheduler, *_ = _wiring()
    wr = WarRoomAdapter(scheduler=scheduler)
    resp = wr.handle_submit(
        {
            "tenant_id": "t1",
            "project_id": "p1",
            "agent_id": "agent-x",
            "input": {"content": "hi"},
        }
    )

    async def collect():
        out = []
        async for ev in async_stream(scheduler, resp["run_id"], tenant_id="t1", timeout=5):
            out.append(ev.kind)
        return out

    kinds = asyncio.run(collect())
    assert kinds[0] == "run.created"
    assert kinds[-1] == "run.finished"
    scheduler.close()
