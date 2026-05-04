"""
Smoke de fechamento — LESSON-013 (Wave 2 closure).

Estrutura:
  - Testes "pre-removal": pulados se o modulo legado ainda existe
    (passam apos git rm na FASE 6)
  - Testes "post-removal" (canonicos): rodam AGORA e devem sempre ser verdes

Para executar so os testes de fechamento pos-remocao:
    pytest tests/smoke/test_lesson_013_closure.py -v -m "not pre_removal"

Para executar TUDO (validacao final apos FASE 6):
    pytest tests/smoke/test_lesson_013_closure.py -v
"""

from __future__ import annotations

import importlib

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _module_exists(name: str) -> bool:
    """True se o modulo ainda pode ser importado."""
    try:
        importlib.import_module(name)
        return True
    except (ImportError, ModuleNotFoundError):
        return False


def _skip_if_exists(module: str):
    """Decorator: pula o teste se o modulo ainda existir (LESSON-013 nao executada)."""
    return pytest.mark.skipif(
        _module_exists(module),
        reason=f"Modulo {module!r} ainda existe — execute LESSON-013 (git rm) antes.",
    )


# ---------------------------------------------------------------------------
# Pre-removal: verificar ImportError pos-remocao (LESSON-013 FASE 1 e 2)
# ---------------------------------------------------------------------------


@pytest.mark.pre_removal
@_skip_if_exists("orchestrator")
def test_orchestrator_removed():
    """orchestrator.py removido — importar deve falhar."""
    with pytest.raises((ImportError, ModuleNotFoundError)):
        import orchestrator  # noqa: F401


@pytest.mark.pre_removal
@_skip_if_exists("master_controller")
def test_master_controller_removed():
    """master_controller removido — importar deve falhar."""
    with pytest.raises((ImportError, ModuleNotFoundError)):
        import master_controller  # noqa: F401


@pytest.mark.pre_removal
@_skip_if_exists("orch_core_legacy")
def test_orch_core_legacy_removed():
    """orch_core_legacy removido — importar deve falhar."""
    with pytest.raises((ImportError, ModuleNotFoundError)):
        import orch_core_legacy  # noqa: F401


@pytest.mark.pre_removal
@_skip_if_exists("orch_core.adapters.legacy")
def test_legacy_shim_removed():
    """orch_core/adapters/legacy.py removido — importar deve falhar."""
    with pytest.raises((ImportError, ModuleNotFoundError)):
        from orch_core.adapters import legacy  # noqa: F401


@pytest.mark.pre_removal
@_skip_if_exists("orch_core.adapters.master")
def test_master_shim_removed():
    """orch_core/adapters/master.py removido — importar deve falhar."""
    with pytest.raises((ImportError, ModuleNotFoundError)):
        from orch_core.adapters import master  # noqa: F401


# ---------------------------------------------------------------------------
# Post-removal / canonical: devem ser SEMPRE verdes
# ---------------------------------------------------------------------------


def test_scheduler_importable():
    """Scheduler importavel pelo caminho canonico."""
    from orch_core.control.scheduler import Scheduler

    assert Scheduler is not None


def test_runner_importable():
    """Runner importavel pelo caminho canonico."""
    from orch_core.execution.runner import Runner, RunResult

    assert Runner is not None
    assert RunResult is not None


def test_contracts_importable():
    """Contratos canonicos importaveis."""
    from orch_core.contracts import new_run

    assert new_run is not None
    run = new_run(tenant_id="t1", project_id="p1", agent_id="a1")
    assert run.status == "pending"


def test_shadow_runner_importable():
    """ShadowRunner importavel (dark-launch infra)."""
    from orch_core.execution.shadow import ShadowRunner

    assert ShadowRunner is not None


def test_adapters_importable():
    """Adapters de ports importaveis."""
    from orch_core.observability.adapters import (
        AnthropicAgentExecutor,
        AuditLogAdapter,
        ExecutionContextAdapter,
        RuntimeGuardAdapter,
    )

    assert all(
        [
            AnthropicAgentExecutor,
            AuditLogAdapter,
            ExecutionContextAdapter,
            RuntimeGuardAdapter,
        ]
    )


def test_deprecation_registry_importable():
    """DeprecationRegistry importavel e funcional."""
    from orch_core.adapters.deprecation import (
        default_deprecation_registry,
        reset_deprecation_registry,
    )

    reset_deprecation_registry()
    reg = default_deprecation_registry()
    assert reg.snapshot() == {}


def test_ports_satisfy_protocols():
    """Adapters satisfazem os Protocols declarados em ports.py."""
    import pathlib
    import tempfile
    from uuid import uuid4

    from core.audit_log import AuditLog
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

    with tempfile.TemporaryDirectory() as tmp:
        log = AuditLog(offline=True, offline_path=pathlib.Path(tmp) / "a.jsonl")
        assert isinstance(AuditLogAdapter(audit_log=log), AuditSink)
    assert isinstance(ExecutionContextAdapter(run_id=uuid4(), tenant_id="t1"), ExecutionContext)
    assert isinstance(RuntimeGuardAdapter(execution_context="mvp"), RuntimeGuard)
    assert isinstance(AnthropicAgentExecutor(api_key="test"), AgentExecutor)


def test_no_direct_legacy_imports_in_engines():
    """engines/opportunity_pipeline.py nao importa mais core.orch_core diretamente."""
    import ast
    import pathlib

    src = pathlib.Path("engines/opportunity_pipeline.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert (
                    "core.orch_core" not in node.module
                ), f"Import direto de core.orch_core encontrado na linha {node.lineno}"
