"""
orch_core.execution.runner
===========================

Runner canonico (LESSON-010). Substitui os 3 loops de tool_use duplicados.

Design:
- STATELESS. Estado vive em ExecutionContext in-flight + AuditSink
  persistido. Multiplas instancias podem rodar em paralelo sem conflito.
- Loop unico de tool_use com limite configuravel (feature flag).
- Integra ports (AuditSink, RuntimeGuard, AgentExecutor, EventSink)
  sem acoplar a implementacoes concretas.
- Emite eventos canonicos (LESSON-008): run.created, run.started,
  run.step, run.finished, run.failed, run.cancelled.
- Cancelamento cooperativo via callable is_cancelled().
- Idempotencia de retry: cada step tem step_id unico; retry re-executa
  o step, audit registra ambos.

NAO faz:
- Scheduling (isso e LESSON-011).
- Persistencia de sessao (LESSON-011).
- HTTP/SSE (LESSON-012 adapters.war_room).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4

from orch_core.contracts import (
    Event,
    OrchError,
    Run,
    RunSpec,
    Step,
    new_run,
)
from orch_core.control.registry import Registry
from orch_core.execution.context_builder import (
    build_messages,
    build_tools,
    resolve_agent,
)
from orch_core.execution.feature_flags import DEFAULT_MAX_STEPS, FeatureFlags
from orch_core.execution.policy import (
    PolicyDenied,
    enforce_tool_call,
)
from orch_core.observability.ports import (
    AgentExecutor,
    AuditSink,
    EventSink,
    RuntimeGuard,
)


class RunCancelled(OrchError):
    pass


class MaxStepsExceeded(OrchError):
    pass


@dataclass(frozen=True, slots=True)
class RunResult:
    run: Run
    steps: list[Step] = field(default_factory=list)
    output: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None


class Runner:
    """Runner stateless. Uma instancia pode executar N runs em paralelo
    (desde que os ports injetados sejam thread-safe)."""

    def __init__(
        self,
        *,
        registry: Registry,
        audit: AuditSink,
        guard: RuntimeGuard,
        agent_executor: AgentExecutor,
        events: EventSink | None = None,
        flags: FeatureFlags | None = None,
    ) -> None:
        self._registry = registry
        self._audit = audit
        self._guard = guard
        self._executor = agent_executor
        self._events = events
        self._flags = flags or FeatureFlags()

    # -- API publica ----------------------------------------------------------

    def execute(
        self,
        spec: RunSpec,
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> RunResult:
        """Conveniencia: materializa Run a partir de RunSpec e delega
        pra execute_run. Scheduler nao usa este caminho (cria o Run
        ele mesmo pra controlar run_id antes de submeter)."""
        run = _run_from_spec(spec)
        input_payload = dict(spec.get("input", {}))
        return self.execute_run(
            run, input_payload=input_payload, is_cancelled=is_cancelled
        )

    def execute_run(
        self,
        run: Run,
        *,
        input_payload: Mapping[str, Any] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> RunResult:
        """Executa um Run ja materializado. API primaria usada pelo
        Scheduler — preserva o run_id gerado pelo caller."""
        input_payload = dict(input_payload or {})
        self._emit(
            Event(
                event_id=uuid4(),
                run_id=run.run_id,
                kind="run.created",
                payload={"agent_id": run.agent_id, "tenant_id": run.tenant_id},
            )
        )
        self._audit.append(
            run_id=run.run_id,
            tenant_id=run.tenant_id,
            kind="run.created",
            payload=run.to_dict(),
        )

        # -- 2) Transiciona pra running -------------------------------------
        run = run.with_status("running")
        self._emit(
            Event(
                event_id=uuid4(),
                run_id=run.run_id,
                kind="run.started",
                payload={},
            )
        )

        steps: list[Step] = []
        try:
            agent = resolve_agent(run=run, registry=self._registry)
            tools = build_tools(run=run, registry=self._registry)
            messages: list[Mapping[str, Any]] = build_messages(
                run=run, input_payload=input_payload
            )
            output = self._loop(
                run=run,
                agent=agent,
                messages=messages,
                tools=tools,
                steps=steps,
                is_cancelled=is_cancelled,
            )
        except RunCancelled as e:
            run = run.with_status("cancelled")
            self._emit_terminal(run, "run.cancelled", reason=str(e))
            return RunResult(run=run, steps=steps, error=str(e))
        except MaxStepsExceeded as e:
            run = run.with_status("failed")
            self._emit_terminal(run, "run.failed", reason=str(e))
            return RunResult(run=run, steps=steps, error=str(e))
        except PolicyDenied as e:
            run = run.with_status("failed")
            self._emit_terminal(run, "run.failed", reason=str(e))
            return RunResult(run=run, steps=steps, error=str(e))
        except OrchError as e:
            run = run.with_status("failed")
            self._emit_terminal(run, "run.failed", reason=str(e))
            return RunResult(run=run, steps=steps, error=str(e))

        # -- 3) Sucesso -----------------------------------------------------
        run = run.with_status("done")
        self._emit_terminal(run, "run.finished", payload=dict(output))
        return RunResult(run=run, steps=steps, output=output)

    # -- internos -------------------------------------------------------------

    def _loop(
        self,
        *,
        run: Run,
        agent: Any,
        messages: list[Mapping[str, Any]],
        tools: list[Mapping[str, Any]],
        steps: list[Step],
        is_cancelled: Callable[[], bool] | None,
    ) -> Mapping[str, Any]:
        max_steps = self._flags.runner_max_steps or DEFAULT_MAX_STEPS

        for step_idx in range(max_steps):
            if is_cancelled is not None and is_cancelled():
                raise RunCancelled(f"run {run.run_id} cancelled by caller")

            response = self._executor.step(
                run=run, messages=messages, tools=tools
            )

            stop_reason = response.get("stop_reason")
            text = response.get("text")
            tool_calls = list(response.get("tool_calls") or [])

            # -- Registra step do agente ------------------------------------
            agent_step = Step(
                step_id=uuid4(),
                run_id=run.run_id,
                index=step_idx,
                kind="message",
                payload={
                    "stop_reason": stop_reason,
                    "text": text,
                    "tool_calls_count": len(tool_calls),
                },
            )
            steps.append(agent_step)
            self._audit.append(
                run_id=run.run_id,
                tenant_id=run.tenant_id,
                kind="run.step",
                payload={
                    "step_id": str(agent_step.step_id),
                    "kind": "message",
                    "stop_reason": stop_reason,
                    "text": text,
                },
            )
            self._emit(
                Event(
                    event_id=uuid4(),
                    run_id=run.run_id,
                    kind="run.step",
                    payload={
                        "step_id": str(agent_step.step_id),
                        "stop_reason": stop_reason,
                    },
                )
            )

            # Condicao de saida: agente terminou sem pedir tool
            if stop_reason in ("end_turn", "stop", None) and not tool_calls:
                return {"text": text, "stop_reason": stop_reason}

            if stop_reason == "error":
                raise OrchError(
                    response.get("error") or "agent returned error"
                )

            # Adiciona resposta do agente no historico
            messages = [
                *messages,
                {
                    "role": "assistant",
                    "content": response.get("content") or text or "",
                },
            ]

            # -- Processa cada tool_call ------------------------------------
            for call in tool_calls:
                if is_cancelled is not None and is_cancelled():
                    raise RunCancelled(
                        f"run {run.run_id} cancelled mid-tool"
                    )
                tool_name = call["name"]
                args = call.get("args") or {}
                decision = enforce_tool_call(
                    guard=self._guard,
                    run=run,
                    tool_name=tool_name,
                    args=args,
                )
                if not decision.allowed:
                    self._audit.append(
                        run_id=run.run_id,
                        tenant_id=run.tenant_id,
                        kind="run.policy_denied",
                        payload={
                            "tool_name": tool_name,
                            "reason": decision.reason,
                        },
                    )
                    raise PolicyDenied(
                        decision.reason or "denied",
                        tool_name=tool_name,
                        run_id=str(run.run_id),
                    )

                try:
                    tool = self._registry.get_tool(tool_name)
                    tool_result = _invoke_tool(tool, args)
                    tool_status = "ok"
                    tool_error: str | None = None
                except Exception as e:  # noqa: BLE001
                    tool_result = None
                    tool_status = "error"
                    tool_error = str(e)

                tool_step = Step(
                    step_id=uuid4(),
                    run_id=run.run_id,
                    index=step_idx,
                    kind="tool_result",
                    payload={
                        "tool_name": tool_name,
                        "status": tool_status,
                        "error": tool_error,
                    },
                )
                steps.append(tool_step)
                self._audit.append(
                    run_id=run.run_id,
                    tenant_id=run.tenant_id,
                    kind="run.tool_result",
                    payload={
                        "step_id": str(tool_step.step_id),
                        "tool_name": tool_name,
                        "status": tool_status,
                        "error": tool_error,
                    },
                )
                messages = [
                    *messages,
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": (
                            tool_result
                            if tool_status == "ok"
                            else f"ERROR: {tool_error}"
                        ),
                    },
                ]

        raise MaxStepsExceeded(
            f"run {run.run_id} exceeded {max_steps} steps"
        )

    def _emit(self, event: Event) -> None:
        if self._events is not None:
            self._events.emit(event)

    def _emit_terminal(
        self,
        run: Run,
        kind: str,
        *,
        reason: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        full_payload: dict[str, Any] = {"status": run.status}
        if reason is not None:
            full_payload["reason"] = reason
        if payload:
            full_payload.update(payload)
        self._emit(
            Event(
                event_id=uuid4(),
                run_id=run.run_id,
                kind=kind,  # type: ignore[arg-type]
                payload=full_payload,
            )
        )
        self._audit.append(
            run_id=run.run_id,
            tenant_id=run.tenant_id,
            kind=kind,
            payload=full_payload,
        )


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _run_from_spec(spec: RunSpec) -> Run:
    tenant_id = spec.get("tenant_id")
    project_id = spec.get("project_id")
    agent_id = spec.get("agent_id")
    if not (tenant_id and project_id and agent_id):
        raise OrchError(
            "RunSpec must include tenant_id, project_id, agent_id"
        )
    parent = spec.get("parent_run_id")
    parent_uuid = UUID(parent) if isinstance(parent, str) else parent
    return new_run(
        tenant_id=tenant_id,
        project_id=project_id,
        agent_id=agent_id,
        parent_run_id=parent_uuid,
        metadata=spec.get("metadata") or {},
    )


def _invoke_tool(tool: Any, args: Mapping[str, Any]) -> Any:
    """Chama a tool de forma uniforme.

    Contrato minimo: se o objeto tem __call__, usa; senao, .run(**args).
    Implementacoes concretas podem usar qualquer dos dois padroes.
    """
    if callable(tool):
        return tool(**dict(args))
    if hasattr(tool, "run"):
        return tool.run(**dict(args))
    raise OrchError(f"tool {getattr(tool, 'name', '?')} is not callable")


__all__ = [
    "MaxStepsExceeded",
    "RunCancelled",
    "RunResult",
    "Runner",
]
