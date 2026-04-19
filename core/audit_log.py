"""AuditLog canonico (LESSON-004)."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Optional


class GatekeeperDecision(str, Enum):
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    EXPERIMENT = "EXPERIMENT"


AUDIT_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    entry_id      BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id    TEXT NOT NULL,
    agent         TEXT NOT NULL,
    action        TEXT NOT NULL,
    decision      TEXT NOT NULL,
    input_hash    TEXT NOT NULL,
    output_hash   TEXT,
    reason        TEXT,
    confidence    REAL,
    cost_usd      REAL,
    prev_hash     TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log (session_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log (created_at DESC);
"""

DEFAULT_OFFLINE_PATH = Path("outputs/audit/audit_log_offline.jsonl")


class AuditLog:
    """Log imutavel com hash chain. Auto-detecta Postgres vs offline."""

    def __init__(self, db_url=None, offline=None, offline_path=None):
        env_db_url = (os.getenv("DATABASE_URL", "") or "").strip() or None
        env_offline = (os.getenv("OFFLINE", "") or "").strip().lower() in {"1", "true", "yes"}

        self._db_url = db_url if db_url else env_db_url
        self._offline_path = Path(offline_path) if offline_path else DEFAULT_OFFLINE_PATH

        if offline is True:
            self._offline = True
        elif offline is False:
            self._offline = False
            if not self._db_url:
                raise RuntimeError(
                    "AuditLog: offline=False mas DATABASE_URL nao esta definido. "
                    "Defina DATABASE_URL no ambiente ou use offline=True."
                )
        else:
            self._offline = env_offline or not self._db_url

        self._last_hash = None
        self._conn = None
        self._lock = Lock()

        if self._offline:
            self._offline_path.parent.mkdir(parents=True, exist_ok=True)
            self._last_hash = self._recover_last_hash()
        else:
            try:
                import psycopg2  # noqa: F401
            except ImportError as e:
                raise RuntimeError(
                    "AuditLog: modo Postgres requer psycopg2. "
                    "Use pip install psycopg2-binary ou offline=True."
                ) from e

    @property
    def mode(self):
        return "offline" if self._offline else "postgres"

    @staticmethod
    def _hash(data):
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def _recover_last_hash(self):
        if not self._offline_path.exists():
            return None
        try:
            with open(self._offline_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                if size == 0:
                    return None
                chunk = min(8192, size)
                f.seek(-chunk, os.SEEK_END)
                tail = f.read().decode("utf-8", errors="replace")
                lines = [ln for ln in tail.splitlines() if ln.strip()]
                if not lines:
                    return None
                return json.loads(lines[-1]).get("entry_hash")
        except (json.JSONDecodeError, OSError):
            return None

    def _connect(self):
        import psycopg2
        if self._conn is None or getattr(self._conn, "closed", 1):
            try:
                self._conn = psycopg2.connect(self._db_url)
            except psycopg2.Error as e:
                raise RuntimeError(
                    f"AuditLog: falha conectando Postgres. Erro: {e}"
                ) from e
        return self._conn

    def setup(self):
        if self._offline:
            return
        sql_path = Path(__file__).resolve().parent.parent / "scripts" / "setup_audit_log.sql"
        sql = sql_path.read_text(encoding="utf-8") if sql_path.exists() else AUDIT_LOG_SCHEMA
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()

    def record(self, session_id, agent, action, decision, input_data,
               output_data=None, reason="", confidence=1.0, cost_usd=0.0):
        input_hash = self._hash(input_data)
        output_hash = self._hash(output_data) if output_data else None
        decision_value = decision.value if isinstance(decision, GatekeeperDecision) else str(decision)

        with self._lock:
            prev_hash = self._last_hash

            if self._offline:
                entry_id = f"off_{uuid.uuid4().hex[:16]}"
                entry = {
                    "entry_id": entry_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "session_id": session_id,
                    "agent": agent,
                    "action": action,
                    "decision": decision_value,
                    "input_hash": input_hash,
                    "output_hash": output_hash,
                    "reason": reason,
                    "confidence": confidence,
                    "cost_usd": cost_usd,
                    "prev_hash": prev_hash,
                }
                entry_hash = self._hash(json.dumps(entry, sort_keys=True, ensure_ascii=False))
                entry["entry_hash"] = entry_hash
                with open(self._offline_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                self._last_hash = entry_hash
                return entry_id

            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log "
                    "(session_id, agent, action, decision, input_hash, output_hash, "
                    "reason, confidence, cost_usd, prev_hash) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING entry_id",
                    (session_id, agent, action, decision_value,
                     input_hash, output_hash, reason,
                     confidence, cost_usd, prev_hash),
                )
                entry_id_int = cur.fetchone()[0]
            conn.commit()
            self._last_hash = self._hash(f"{entry_id_int}{input_hash}{decision_value}")
            return str(entry_id_int)

    def query_session(self, session_id):
        if self._offline:
            return self._query_offline(lambda e: e.get("session_id") == session_id)
        import psycopg2.extras
        conn = self._connect()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM audit_log WHERE session_id=%s ORDER BY created_at",
                (session_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def query_recent(self, limit=100):
        if self._offline:
            return list(reversed(self._query_offline(lambda e: True)))[:limit]
        import psycopg2.extras
        conn = self._connect()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT %s", (limit,))
            return [dict(r) for r in cur.fetchall()]

    def _query_offline(self, predicate):
        if not self._offline_path.exists():
            return []
        out = []
        with open(self._offline_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if predicate(entry):
                        out.append(entry)
                except json.JSONDecodeError:
                    continue
        return out

    def verify_chain(self):
        if not self._offline:
            return {"valid": True, "total": 0, "broken_at": None,
                    "note": "only offline mode"}
        if not self._offline_path.exists():
            return {"valid": True, "total": 0, "broken_at": None}

        prev_hash = None
        total = 0
        with open(self._offline_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    return {"valid": False, "total": total, "broken_at": "json"}
                total += 1
                if entry.get("prev_hash") != prev_hash:
                    return {"valid": False, "total": total,
                            "broken_at": entry.get("entry_id")}
                expected = {k: v for k, v in entry.items() if k != "entry_hash"}
                exp_hash = self._hash(json.dumps(expected, sort_keys=True, ensure_ascii=False))
                if exp_hash != entry.get("entry_hash"):
                    return {"valid": False, "total": total,
                            "broken_at": entry.get("entry_id"),
                            "reason": "entry_hash_mismatch"}
                prev_hash = entry["entry_hash"]

        return {"valid": True, "total": total, "broken_at": None}
