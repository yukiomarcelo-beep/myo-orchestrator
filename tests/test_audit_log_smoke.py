"""Smoke test AuditLog (LESSON-004). 9 casos."""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def run():
    root = Path(__file__).parent.parent
    sys.path.insert(0, str(root))
    from core.audit_log import AuditLog, GatekeeperDecision

    failures = []
    tmpdir = tempfile.mkdtemp(prefix="audit_smoke_")
    jsonl = Path(tmpdir) / "audit.jsonl"

    saved_db = os.environ.pop("DATABASE_URL", None)
    saved_off = os.environ.pop("OFFLINE", None)

    try:
        # 1. auto-detect -> offline
        try:
            audit = AuditLog(offline_path=jsonl)
            assert audit.mode == "offline"
            print(f"  OK   auto-detect -> {audit.mode}")
        except Exception as e:
            failures.append(("auto_detect", repr(e)))

        # 2. offline=False sem DATABASE_URL -> RuntimeError
        try:
            AuditLog(offline=False, offline_path=jsonl)
            failures.append(("fail_fast", "nao levantou RuntimeError"))
        except RuntimeError as e:
            assert "DATABASE_URL" in str(e)
            print("  OK   fail-fast sem DATABASE_URL")

        # 3. offline=True forcado
        try:
            audit = AuditLog(offline=True, offline_path=jsonl)
            assert audit.mode == "offline"
            print(f"  OK   offline=True -> {audit.mode}")
        except Exception as e:
            failures.append(("offline_forced", repr(e)))

        # 4. record() grava jsonl
        try:
            if jsonl.exists():
                jsonl.unlink()
            audit = AuditLog(offline=True, offline_path=jsonl)
            entry_id = audit.record(
                session_id="s1",
                agent="t",
                action="a",
                decision=GatekeeperDecision.APPROVED,
                input_data="in",
                output_data="out",
                reason="smoke",
                confidence=0.9,
                cost_usd=0.01,
            )
            assert entry_id.startswith("off_")
            with open(jsonl) as f:
                lines = [ln for ln in f if ln.strip()]
            assert len(lines) == 1
            e = json.loads(lines[0])
            assert e["decision"] == "APPROVED"
            assert e["prev_hash"] is None
            assert "entry_hash" in e
            print("  OK   record() grava jsonl")
        except Exception as e:
            failures.append(("record", repr(e)))

        # 5. hash chain
        try:
            audit = AuditLog(offline=True, offline_path=jsonl)
            audit.record(
                session_id="s1",
                agent="t",
                action="a2",
                decision=GatekeeperDecision.BLOCKED,
                input_data="2",
            )
            with open(jsonl) as f:
                lines = [json.loads(ln) for ln in f if ln.strip()]
            assert lines[1]["prev_hash"] == lines[0]["entry_hash"]
            print("  OK   hash chain")
        except Exception as e:
            failures.append(("chain", repr(e)))

        # 6. verify_chain valida
        try:
            audit = AuditLog(offline=True, offline_path=jsonl)
            r = audit.verify_chain()
            assert r["valid"] is True and r["total"] == 2
            print(f"  OK   verify_chain: valida ({r['total']})")
        except Exception as e:
            failures.append(("verify_valid", repr(e)))

        # 7. tampering detection
        try:
            with open(jsonl) as f:
                lines = [json.loads(ln) for ln in f if ln.strip()]
            lines[0]["reason"] = "TAMPERED"
            with open(jsonl, "w") as f:
                for e in lines:
                    f.write(json.dumps(e) + "\n")
            audit = AuditLog(offline=True, offline_path=jsonl)
            r = audit.verify_chain()
            assert r["valid"] is False
            print("  OK   tampering detectado")
        except Exception as e:
            failures.append(("tamper", repr(e)))

        # 8. queries
        try:
            if jsonl.exists():
                jsonl.unlink()
            audit = AuditLog(offline=True, offline_path=jsonl)
            audit.record(
                session_id="A",
                agent="x",
                action="1",
                decision=GatekeeperDecision.APPROVED,
                input_data="1",
            )
            audit.record(
                session_id="B",
                agent="x",
                action="2",
                decision=GatekeeperDecision.BLOCKED,
                input_data="2",
            )
            audit.record(
                session_id="A",
                agent="x",
                action="3",
                decision=GatekeeperDecision.APPROVED,
                input_data="3",
            )
            assert len(audit.query_session("A")) == 2
            assert len(audit.query_recent(limit=2)) == 2
            print("  OK   queries")
        except Exception as e:
            failures.append(("queries", repr(e)))

        # 9. chain persistida entre instances
        try:
            audit2 = AuditLog(offline=True, offline_path=jsonl)
            assert audit2._last_hash is not None
            audit2.record(
                session_id="A",
                agent="x",
                action="4",
                decision=GatekeeperDecision.APPROVED,
                input_data="4",
            )
            with open(jsonl) as f:
                lines = [json.loads(ln) for ln in f if ln.strip()]
            assert lines[-1]["prev_hash"] == lines[-2]["entry_hash"]
            print("  OK   chain persistida entre instances")
        except Exception as e:
            failures.append(("persist", repr(e)))

    finally:
        if saved_db is not None:
            os.environ["DATABASE_URL"] = saved_db
        if saved_off is not None:
            os.environ["OFFLINE"] = saved_off
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("\n" + "=" * 60)
    if failures:
        print(f"SMOKE TEST FALHOU: {len(failures)}")
        for name, err in failures:
            print(f"  [{name}] {err}")
        return 1
    print("SMOKE TEST PASSOU (9/9)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
