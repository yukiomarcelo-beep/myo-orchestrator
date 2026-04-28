#!/usr/bin/env python3
"""
Sofia Monitor Engine — status em tempo real dos produtos Mali Travel.

Coleta em paralelo:
  - Estado das instâncias Evolution (sofia-mali, viviane-mali)
  - Última mensagem recebida (base_mali no evolution-postgres)
  - Clock skew do n8n
  - Status dos containers Docker relevantes
  - Healthcheck n8n

Expõe: /api/products/status
"""

import asyncio
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_URL = os.getenv("EVOLUTION_URL", "http://localhost:8080")
EVOLUTION_APIKEY = os.getenv("EVOLUTION_APIKEY", "sofia2024")
N8N_URL = os.getenv("N8N_URL", "http://localhost:5678")
EVOLUTION_DB_HOST = os.getenv("EVOLUTION_DB_HOST", "localhost")
EVOLUTION_DB_PORT = int(os.getenv("EVOLUTION_DB_PORT", "5432"))
EVOLUTION_DB_USER = os.getenv("EVOLUTION_DB_USER", "evolution")
EVOLUTION_DB_PASS = os.getenv("EVOLUTION_DB_PASS", "evolution123")
EVOLUTION_DB_NAME = os.getenv("EVOLUTION_DB_NAME", "evolution")

INSTANCES = ["sofia-mali", "viviane-mali"]
WATCH_CONTAINERS = [
    "evolution-api",
    "evolution-postgres",
    "evolution-redis",
    "n8n",
    "sofia-search",
    "kitchen-n8n",
]

_OUTPUTS = Path(__file__).parent.parent / "outputs" / "sofia_monitor"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_ago(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds/60)}min"
    if seconds < 86400:
        return f"{seconds/3600:.1f}h"
    return f"{seconds/86400:.1f}d"


# ── checkers ────────────────────────────────────────────────────────────────


async def _check_instance(client: httpx.AsyncClient, name: str) -> dict[str, Any]:
    try:
        t0 = time.monotonic()
        r = await client.get(
            f"{EVOLUTION_URL}/instance/connectionState/{name}",
            headers={"apikey": EVOLUTION_APIKEY},
            timeout=6,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        state = r.json().get("instance", {}).get("state", "unknown")
        return {"state": state, "latency_ms": latency_ms}
    except Exception as exc:
        return {"state": "error", "error": str(exc)[:80]}


def _query_last_msg_sync() -> dict[str, Any]:
    import psycopg2

    conn = psycopg2.connect(
        host=EVOLUTION_DB_HOST,
        port=EVOLUTION_DB_PORT,
        user=EVOLUTION_DB_USER,
        password=EVOLUTION_DB_PASS,
        dbname=EVOLUTION_DB_NAME,
        connect_timeout=5,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT criado_em FROM base_mali ORDER BY criado_em DESC LIMIT 1")
            row = cur.fetchone()
        if row and row[0]:
            ts = row[0]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ago_s = (datetime.now(timezone.utc) - ts).total_seconds()
            return {"last_msg_iso": ts.isoformat(), "ago_s": int(ago_s), "ago_fmt": _fmt_ago(ago_s)}
        return {"last_msg_iso": None, "ago_s": None, "ago_fmt": "nunca"}
    finally:
        conn.close()


async def _last_msg_base_mali() -> dict[str, Any]:
    try:
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, _query_last_msg_sync),
            timeout=8,
        )
    except Exception as exc:
        return {"error": str(exc)[:120], "last_msg_iso": None, "ago_s": None, "ago_fmt": "erro"}


async def _check_n8n(client: httpx.AsyncClient) -> dict[str, Any]:
    try:
        t0 = time.monotonic()
        r = await client.get(f"{N8N_URL}/healthz", timeout=5)
        latency_ms = int((time.monotonic() - t0) * 1000)
        ok = r.status_code == 200
        return {"up": ok, "latency_ms": latency_ms}
    except Exception as exc:
        return {"up": False, "error": str(exc)[:80]}


def _check_clock_skew() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["docker", "logs", "n8n", "--since", "5m"], capture_output=True, text=True, timeout=8
        )
        logs = result.stdout + result.stderr
        skew_lines = [l for l in logs.splitlines() if "clock skew" in l.lower()]
        if skew_lines:
            last = skew_lines[-1]
            import re

            m = re.search(r"(\d+)ms", last)
            ms = int(m.group(1)) if m else None
            return {"detected": True, "skew_ms": ms, "sample": last[-80:]}
        return {"detected": False, "skew_ms": 0}
    except Exception as exc:
        return {"detected": False, "error": str(exc)[:80]}


def _check_docker() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        containers: dict[str, str] = {}
        for line in result.stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                name, status = parts
                if name in WATCH_CONTAINERS:
                    containers[name] = status
        up = sum(1 for s in containers.values() if s.lower().startswith("up"))
        return {"containers": containers, "up": up, "total_watched": len(WATCH_CONTAINERS)}
    except Exception as exc:
        return {"containers": {}, "up": 0, "error": str(exc)[:80]}


# ── overall status ───────────────────────────────────────────────────────────


def _overall(instances: dict, n8n: dict, skew: dict, last_msg: dict) -> str:
    problems = 0
    for inst in instances.values():
        if inst.get("state") != "open":
            problems += 1
    if not n8n.get("up"):
        problems += 1
    if skew.get("detected") and (skew.get("skew_ms") or 0) > 3000:
        problems += 1
    ago = last_msg.get("ago_s")
    if ago and ago > 3600 * 6:
        problems += 1
    if problems == 0:
        return "healthy"
    if problems == 1:
        return "degraded"
    return "critical"


# ── public API ───────────────────────────────────────────────────────────────


async def run() -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        inst_tasks = [_check_instance(client, n) for n in INSTANCES]
        n8n_task = _check_n8n(client)
        db_task = _last_msg_base_mali()

        # IO-bound em paralelo; docker/skew são subprocess (sync mas rápido)
        results = await asyncio.gather(*inst_tasks, n8n_task, db_task, return_exceptions=True)

    instances = {}
    for i, name in enumerate(INSTANCES):
        r = results[i]
        instances[name] = r if isinstance(r, dict) else {"state": "error", "error": str(r)}

    n8n = results[len(INSTANCES)] if isinstance(results[len(INSTANCES)], dict) else {"up": False}
    last_msg = results[len(INSTANCES) + 1] if isinstance(results[len(INSTANCES) + 1], dict) else {}

    skew = _check_clock_skew()
    docker = _check_docker()

    payload = {
        "timestamp": _now_iso(),
        "overall": _overall(instances, n8n, skew, last_msg),
        "instances": instances,
        "n8n": n8n,
        "clock_skew": skew,
        "docker": docker,
        "last_msg": last_msg,
    }

    _OUTPUTS.mkdir(parents=True, exist_ok=True)
    (_OUTPUTS / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


if __name__ == "__main__":
    import sys

    result = asyncio.run(run())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["overall"] in ("healthy", "degraded") else 1)
