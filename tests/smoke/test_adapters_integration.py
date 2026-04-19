"""
Smoke tests dos adapters de ports (FASE 2 — wave2).

Exercita os 4 adapters contra mocks leves:
  - AuditLogAdapter    -> AuditLog offline (sem PG)
  - RuntimeGuardAdapter -> RuntimeGuard canonico
  - ExecutionContextAdapter -> implementacao direta do port
  - AnthropicAgentExecutor  -> mock de httpx (sem API real)
"""
from __future__ import annotations

import json
from typing import Any, Mapping
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from orch_core.contracts import Run, new_run
from orch_core.observability.adapters import (
    AnthropicAgentExecutor,
    AuditLogAdapter,
    ExecutionContextAdapter,
    RuntimeGuardAdapter,
)
from orch_core.observability.ports import (
    AgentExecutor,
    AuditSink,
    ExecutionContext,
    RuntimeGuard,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def run() -> Run:
    return new_run(tenant_id="t1", project_id="p1", agent_id="agent-x")


@pytest.fixture()
def offline_audit(tmp_path) -> AuditLogAdapter:
    from core.audit_log import AuditLog
    log = AuditLog(offline=True, offline_path=tmp_path / "audit.jsonl")
    return AuditLogAdapter(audit_log=log)


# ---------------------------------------------------------------------------
# AuditLogAdapter
# ---------------------------------------------------------------------------


class TestAuditLogAdapter:
    def test_satisfies_protocol(self, offline_audit):
        assert isinstance(offline_audit, AuditSink)

    def test_append_and_events_of(self, offline_audit, run):
        offline_audit.append(
            run_id=run.run_id,
            tenant_id=run.tenant_id,
            kind="run.created",
            payload={"agent_id": run.agent_id},
        )
        events = offline_audit.events_of(run.run_id)
        assert len(events) == 1
        assert events[0]["action"] == "run.created"

    def test_multiple_events_ordered(self, offline_audit, run):
        for kind in ("run.created", "run.started", "run.finished"):
            offline_audit.append(
                run_id=run.run_id,
                tenant_id=run.tenant_id,
                kind=kind,
                payload={},
            )
        events = offline_audit.events_of(run.run_id)
        assert [e["action"] for e in events] == [
            "run.created", "run.started", "run.finished"
        ]

    def test_audit_trail_isolated_by_run(self, offline_audit):
        r1 = new_run(tenant_id="t1", project_id="p1", agent_id="a1")
        r2 = new_run(tenant_id="t1", project_id="p1", agent_id="a2")
        offline_audit.append(run_id=r1.run_id, tenant_id="t1", kind="ev1", payload={})
        offline_audit.append(run_id=r2.run_id, tenant_id="t1", kind="ev2", payload={})
        assert len(offline_audit.events_of(r1.run_id)) == 1
        assert len(offline_audit.events_of(r2.run_id)) == 1


# ---------------------------------------------------------------------------
# RuntimeGuardAdapter
# ---------------------------------------------------------------------------


class TestRuntimeGuardAdapter:
    def test_satisfies_protocol(self):
        adapter = RuntimeGuardAdapter(execution_context="mvp")
        assert isinstance(adapter, RuntimeGuard)

    def test_allows_safe_tool(self):
        adapter = RuntimeGuardAdapter(execution_context="research")
        allowed = adapter.allow_tool_call(
            tenant_id="t1", agent_id="a1",
            tool_name="Read", args={"file_path": "/tmp/x.txt"},
        )
        assert allowed is True
        assert adapter.reason() is None

    def test_blocks_hard_dangerous(self):
        adapter = RuntimeGuardAdapter(execution_context="mvp")
        allowed = adapter.allow_tool_call(
            tenant_id="t1", agent_id="a1",
            tool_name="Bash", args={"command": "rm -rf /"},
        )
        assert allowed is False
        assert adapter.reason() is not None
        assert "hard_block" in adapter.reason() or "destrutivo" in adapter.reason()

    def test_blocks_system_path_write(self):
        adapter = RuntimeGuardAdapter(execution_context="mvp")
        allowed = adapter.allow_tool_call(
            tenant_id="t1", agent_id="a1",
            tool_name="Write", args={"file_path": "/etc/passwd"},
        )
        assert allowed is False

    def test_reason_clears_after_allow(self):
        adapter = RuntimeGuardAdapter(execution_context="mvp")
        adapter.allow_tool_call(
            tenant_id="t1", agent_id="a1",
            tool_name="Bash", args={"command": "rm -rf /"},
        )
        assert adapter.reason() is not None
        adapter.allow_tool_call(
            tenant_id="t1", agent_id="a1",
            tool_name="Read", args={"file_path": "/tmp/safe.txt"},
        )
        assert adapter.reason() is None


# ---------------------------------------------------------------------------
# ExecutionContextAdapter
# ---------------------------------------------------------------------------


class TestExecutionContextAdapter:
    def test_satisfies_protocol(self):
        ctx = ExecutionContextAdapter(run_id=uuid4(), tenant_id="t1")
        assert isinstance(ctx, ExecutionContext)

    def test_run_id_and_tenant_id(self):
        rid = uuid4()
        ctx = ExecutionContextAdapter(run_id=rid, tenant_id="tenant-42")
        assert ctx.run_id == rid
        assert ctx.tenant_id == "tenant-42"

    def test_get_missing_key_returns_default(self):
        ctx = ExecutionContextAdapter(run_id=uuid4(), tenant_id="t1")
        assert ctx.get("no_key") is None
        assert ctx.get("no_key", "fallback") == "fallback"

    def test_with_value_returns_new_instance(self):
        ctx = ExecutionContextAdapter(run_id=uuid4(), tenant_id="t1")
        ctx2 = ctx.with_value("env", "prod")
        assert ctx.get("env") is None
        assert ctx2.get("env") == "prod"

    def test_with_value_preserves_existing(self):
        ctx = ExecutionContextAdapter(run_id=uuid4(), tenant_id="t1", _data={"a": 1})
        ctx2 = ctx.with_value("b", 2)
        assert ctx2.get("a") == 1
        assert ctx2.get("b") == 2

    def test_immutability(self):
        rid = uuid4()
        ctx = ExecutionContextAdapter(run_id=rid, tenant_id="t1")
        ctx2 = ctx.with_value("x", 99)
        assert ctx2.run_id == rid
        assert ctx2.tenant_id == "t1"


# ---------------------------------------------------------------------------
# AnthropicAgentExecutor
# ---------------------------------------------------------------------------


def _mock_anthropic_response(
    stop_reason: str = "end_turn",
    text: str = "hello",
    tool_calls: list[dict] | None = None,
) -> MagicMock:
    content: list[dict] = []
    if text:
        content.append({"type": "text", "text": text})
    for tc in (tool_calls or []):
        content.append({
            "type": "tool_use",
            "id": tc.get("id", "toolu_x"),
            "name": tc["name"],
            "input": tc.get("args", {}),
        })
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "stop_reason": stop_reason,
        "content": content,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    return mock_resp


class TestAnthropicAgentExecutor:
    def test_satisfies_protocol(self):
        executor = AnthropicAgentExecutor(api_key="test-key")
        assert isinstance(executor, AgentExecutor)

    def test_end_turn_returns_text(self, run):
        executor = AnthropicAgentExecutor(api_key="test-key")
        mock_resp = _mock_anthropic_response(stop_reason="end_turn", text="Done.")
        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp
            result = executor.step(run=run, messages=[{"role": "user", "content": "hi"}], tools=[])
        assert result["stop_reason"] == "end_turn"
        assert result["text"] == "Done."
        assert result["tool_calls"] == []

    def test_tool_use_extracts_calls(self, run):
        executor = AnthropicAgentExecutor(api_key="test-key")
        mock_resp = _mock_anthropic_response(
            stop_reason="tool_use",
            text="",
            tool_calls=[{"name": "search", "id": "toolu_1", "args": {"q": "python"}}],
        )
        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp
            result = executor.step(run=run, messages=[], tools=[])
        assert result["stop_reason"] == "tool_use"
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["name"] == "search"
        assert result["tool_calls"][0]["args"] == {"q": "python"}
        assert result["tool_calls"][0]["id"] == "toolu_1"

    def test_http_error_returns_error_shape(self, run):
        import httpx as _httpx
        executor = AnthropicAgentExecutor(api_key="bad-key")
        with patch("httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value.raise_for_status.side_effect = _httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock(status_code=401, text="Unauthorized")
            )
            result = executor.step(run=run, messages=[], tools=[])
        assert result["stop_reason"] == "error"
        assert result["tool_calls"] == []

    def test_model_from_run_metadata(self, run):
        from orch_core.contracts import replace_run
        run_with_model = replace_run(run, metadata={"model": "claude-haiku-4-5-20251001"})
        executor = AnthropicAgentExecutor(api_key="test-key")
        captured: list[dict] = []

        def fake_post(url, json=None, headers=None):
            captured.append(json or {})
            return _mock_anthropic_response()

        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.side_effect = fake_post
            executor.step(run=run_with_model, messages=[], tools=[])

        assert captured[0]["model"] == "claude-haiku-4-5-20251001"
