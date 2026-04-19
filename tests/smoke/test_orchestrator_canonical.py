"""
Smoke tests das rotas canonicas (substituicao do bloco 3746-4268 do
myo_server.py).

Cobre 10 casos via TestClient do FastAPI sobre app construido do zero
na fixture (nao precisa do myo_server.py real).

Pre-req: pip install fastapi httpx (uvicorn nao e necessario pra teste)

Executa:
    pytest tests/smoke/test_orchestrator_canonical.py -v
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.orchestrator_canonical import mount_canonical_orchestrator
from api.orchestrator_dev_bootstrap import dev_scheduler


@pytest.fixture
def app_and_scheduler():
    app = FastAPI()
    scheduler = dev_scheduler()
    mount_canonical_orchestrator(app, scheduler=scheduler)
    yield app, scheduler
    scheduler.close(wait=True)


@pytest.fixture
def client(app_and_scheduler):
    app, _ = app_and_scheduler
    with TestClient(app) as c:
        yield c


# -----------------------------------------------------------------------------
# 1. POST /api/orchestrator/run submete e devolve run_id
# -----------------------------------------------------------------------------
def test_run_submit(client):
    resp = client.post(
        "/api/orchestrator/run",
        json={"project_id": "p1", "agent_id": "echo", "input": {"content": "oi"}},
        headers={"X-Tenant-Id": "marcelo"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body
    # Aliases de compat com cockpit antigo
    assert body["id"] == body["run_id"]
    assert body["state"] == body["status"]


# -----------------------------------------------------------------------------
# 2. Submit sem agent_id falha com 400 claro
# -----------------------------------------------------------------------------
def test_run_submit_missing_agent(client):
    resp = client.post(
        "/api/orchestrator/run",
        json={"project_id": "p1"},  # sem agent_id
        headers={"X-Tenant-Id": "marcelo"},
    )
    assert resp.status_code == 422  # pydantic validation


# -----------------------------------------------------------------------------
# 3. GET /api/orchestrator/status retorna run com aliases
# -----------------------------------------------------------------------------
def test_status_includes_legacy_aliases(client):
    rid = client.post(
        "/api/orchestrator/run",
        json={"project_id": "p1", "agent_id": "echo"},
        headers={"X-Tenant-Id": "marcelo"},
    ).json()["run_id"]

    # Aguarda terminar (echo eh rapido)
    for _ in range(20):
        resp = client.get(
            f"/api/orchestrator/status?run_id={rid}",
            headers={"X-Tenant-Id": "marcelo"},
        )
        if resp.json()["status"] in ("done", "failed"):
            break
        time.sleep(0.05)

    body = resp.json()
    assert body["status"] == "done"
    assert body["state"] == "done"  # alias
    assert body["id"] == body["run_id"]  # alias


# -----------------------------------------------------------------------------
# 4. GET /api/orchestrator/result inclui output no shape legado
# -----------------------------------------------------------------------------
def test_result_shape(client):
    rid = client.post(
        "/api/orchestrator/run",
        json={"project_id": "p1", "agent_id": "echo"},
        headers={"X-Tenant-Id": "marcelo"},
    ).json()["run_id"]

    # Aguarda terminar
    for _ in range(20):
        s = client.get(
            f"/api/orchestrator/status?run_id={rid}",
            headers={"X-Tenant-Id": "marcelo"},
        ).json()
        if s["status"] == "done":
            break
        time.sleep(0.05)

    resp = client.get(
        f"/api/orchestrator/result?run_id={rid}",
        headers={"X-Tenant-Id": "marcelo"},
    )
    body = resp.json()
    assert body["run_id"] == rid
    assert body["status"] == "done"
    # Ambos os nomes (compat legado + canonico)
    assert "result" in body
    assert "output" in body


# -----------------------------------------------------------------------------
# 5. GET /api/orchestrator/opportunity devolve shape esperado
# -----------------------------------------------------------------------------
def test_opportunity_shape(client):
    rid = client.post(
        "/api/orchestrator/run",
        json={"project_id": "p1", "agent_id": "echo"},
        headers={"X-Tenant-Id": "marcelo"},
    ).json()["run_id"]
    for _ in range(20):
        s = client.get(
            f"/api/orchestrator/status?run_id={rid}",
            headers={"X-Tenant-Id": "marcelo"},
        ).json()
        if s["status"] == "done":
            break
        time.sleep(0.05)

    resp = client.get(
        f"/api/orchestrator/opportunity?run_id={rid}",
        headers={"X-Tenant-Id": "marcelo"},
    )
    body = resp.json()
    assert body["run_id"] == rid
    assert "opportunity" in body  # pode ser None
    assert "raw_output" in body


# -----------------------------------------------------------------------------
# 6. Tenant isolation: tenant B nao ve run de tenant A
# -----------------------------------------------------------------------------
def test_tenant_isolation(client, app_and_scheduler):
    app, scheduler = app_and_scheduler
    # Registra agent 'echo' tambem pra tenant "outro"
    from api.orchestrator_dev_bootstrap import _SimpleAgent
    scheduler._runner._registry.register_agent(_SimpleAgent("outro", "echo"))  # type: ignore[attr-defined]

    rid = client.post(
        "/api/orchestrator/run",
        json={"project_id": "p1", "agent_id": "echo"},
        headers={"X-Tenant-Id": "marcelo"},
    ).json()["run_id"]

    # Tenant "marcelo" ve
    r1 = client.get(
        f"/api/orchestrator/status?run_id={rid}",
        headers={"X-Tenant-Id": "marcelo"},
    )
    assert r1.status_code == 200

    # Tenant "outro" nao ve
    r2 = client.get(
        f"/api/orchestrator/status?run_id={rid}",
        headers={"X-Tenant-Id": "outro"},
    )
    assert r2.status_code == 403


# -----------------------------------------------------------------------------
# 7. POST /api/orchestrator/cancel/{id} funciona
# -----------------------------------------------------------------------------
def test_cancel_route(client):
    # Usa agent 'slow' pra dar tempo de cancelar
    rid = client.post(
        "/api/orchestrator/run",
        json={"project_id": "p1", "agent_id": "slow"},
        headers={"X-Tenant-Id": "marcelo"},
    ).json()["run_id"]

    time.sleep(0.05)  # deixa comecar
    resp = client.post(
        f"/api/orchestrator/cancel/{rid}",
        headers={"X-Tenant-Id": "marcelo"},
    )
    assert resp.status_code == 200
    assert "cancel_signaled" in resp.json()


# -----------------------------------------------------------------------------
# 8. GET /api/orchestrator/runs lista e filtra
# -----------------------------------------------------------------------------
def test_list_runs_and_filter(client):
    for pid in ("p1", "p2", "p1"):
        client.post(
            "/api/orchestrator/run",
            json={"project_id": pid, "agent_id": "echo"},
            headers={"X-Tenant-Id": "marcelo"},
        )
    # Dar tempo pra comecar
    time.sleep(0.2)

    all_runs = client.get(
        "/api/orchestrator/runs", headers={"X-Tenant-Id": "marcelo"}
    ).json()
    assert len(all_runs) >= 3

    p1_runs = client.get(
        "/api/orchestrator/runs?project_id=p1",
        headers={"X-Tenant-Id": "marcelo"},
    ).json()
    assert all(r["project_id"] == "p1" for r in p1_runs)


# -----------------------------------------------------------------------------
# 9. GET /api/orchestrator/stream produz chunks SSE validos
# -----------------------------------------------------------------------------
def test_stream_sse_chunks(client):
    rid = client.post(
        "/api/orchestrator/run",
        json={"project_id": "p1", "agent_id": "echo"},
        headers={"X-Tenant-Id": "marcelo"},
    ).json()["run_id"]

    with client.stream(
        "GET",
        f"/api/orchestrator/stream/{rid}",
        headers={"X-Tenant-Id": "marcelo"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        collected = []
        for chunk in resp.iter_lines():
            if chunk:
                collected.append(chunk)
            if len(collected) > 30:
                break
        # Deve ter visto ao menos uma linha event: e uma data:
        assert any(l.startswith("event: ") for l in collected)
        assert any(l.startswith("data: ") for l in collected)


# -----------------------------------------------------------------------------
# 10. GET /orch serve o cockpit HTML
# -----------------------------------------------------------------------------
def test_cockpit_serves_html(client):
    resp = client.get("/orch")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "MYO COCKPIT" in resp.text
    # JS monta a URL do stream via API + '/stream/' + runId
    assert "/api/orchestrator" in resp.text
    assert "'/stream/'" in resp.text or "/stream/" in resp.text
