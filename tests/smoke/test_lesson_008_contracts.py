"""
Smoke tests LESSON-008 — contratos canonicos.

Cobre 12 casos (minimo >= 8 do padrao da Wave 1):
1. Construcao de Run valido
2. tenant_id obrigatorio
3. run_id precisa ser UUID
4. parent_run_id opcional
5. Enum de status validado
6. Imutabilidade (frozen dataclass)
7. Transicao valida pending -> running
8. Transicao invalida done -> running bloqueada
9. Serializacao to_dict / from_dict (roundtrip)
10. Factory new_run preenche run_id automaticamente
11. project_id obrigatorio
12. agent_id obrigatorio

TODO (Sonnet 4.6, quando tiver o repo em maos):
- Adicionar teste de compatibilidade com ExecutionContext (LESSON-002)
- Adicionar teste de round-trip Run -> AuditLog -> Run (LESSON-004)
"""
from __future__ import annotations

import dataclasses
from uuid import UUID, uuid4

import pytest

from orch_core.contracts import (
    Run,
    is_valid_transition,
    new_run,
    replace_run,
)


def _valid_run_kwargs() -> dict:
    return dict(
        run_id=uuid4(),
        tenant_id="tenant-a",
        project_id="proj-1",
        agent_id="agent-x",
    )


# 1
def test_construct_valid_run() -> None:
    run = Run(**_valid_run_kwargs())
    assert isinstance(run.run_id, UUID)
    assert run.status == "pending"
    assert run.started_at is None
    assert run.finished_at is None


# 2
def test_tenant_id_required() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        Run(**{**_valid_run_kwargs(), "tenant_id": ""})
    with pytest.raises(ValueError, match="tenant_id"):
        Run(**{**_valid_run_kwargs(), "tenant_id": "   "})


# 3
def test_run_id_must_be_uuid() -> None:
    with pytest.raises(TypeError, match="run_id must be UUID"):
        Run(**{**_valid_run_kwargs(), "run_id": "not-a-uuid"})  # type: ignore[arg-type]


# 4
def test_parent_run_id_optional_and_typed() -> None:
    parent = uuid4()
    run = Run(**{**_valid_run_kwargs(), "parent_run_id": parent})
    assert run.parent_run_id == parent

    run2 = Run(**_valid_run_kwargs())
    assert run2.parent_run_id is None

    with pytest.raises(TypeError, match="parent_run_id"):
        Run(**{**_valid_run_kwargs(), "parent_run_id": "nope"})  # type: ignore[arg-type]


# 5
def test_invalid_status_rejected() -> None:
    with pytest.raises(ValueError, match="invalid status"):
        Run(**{**_valid_run_kwargs(), "status": "bogus"})  # type: ignore[arg-type]


# 6
def test_immutability() -> None:
    run = Run(**_valid_run_kwargs())
    with pytest.raises(dataclasses.FrozenInstanceError):
        run.status = "running"  # type: ignore[misc]


# 7
def test_valid_transition_pending_to_running() -> None:
    assert is_valid_transition("pending", "running")
    run = Run(**_valid_run_kwargs())
    moved = run.with_status("running")
    assert moved.status == "running"
    assert moved.started_at is not None
    assert moved.run_id == run.run_id  # identidade preservada


# 8
def test_invalid_transition_done_to_running_blocked() -> None:
    assert not is_valid_transition("done", "running")
    run = replace_run(Run(**_valid_run_kwargs()), status="done")
    with pytest.raises(ValueError, match="invalid transition"):
        run.with_status("running")


# 9
def test_serialization_roundtrip() -> None:
    original = Run(**_valid_run_kwargs()).with_status("running")
    data = original.to_dict()
    restored = Run.from_dict(data)
    assert restored.run_id == original.run_id
    assert restored.tenant_id == original.tenant_id
    assert restored.status == original.status
    assert restored.started_at == original.started_at


# 10
def test_new_run_factory_generates_uuid() -> None:
    run = new_run(
        tenant_id="t", project_id="p", agent_id="a", metadata={"k": "v"}
    )
    assert isinstance(run.run_id, UUID)
    assert run.metadata == {"k": "v"}


# 11
def test_project_id_required() -> None:
    with pytest.raises(ValueError, match="project_id"):
        Run(**{**_valid_run_kwargs(), "project_id": ""})


# 12
def test_agent_id_required() -> None:
    with pytest.raises(ValueError, match="agent_id"):
        Run(**{**_valid_run_kwargs(), "agent_id": ""})
