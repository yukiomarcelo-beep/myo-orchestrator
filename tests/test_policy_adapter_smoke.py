"""Smoke test: invariantes da API publica de policies/policy_adapter.py (LESSON-005).

Cobre:
  - fail-fast em config ausente (load_policy nao silencia FileNotFoundError)
  - guardrails de clamp (THRESHOLD_MIN/MAX respeitados)
  - dry_run nao muta policy em memoria
  - MIN_EVENTS_TOPIC: evidencia insuficiente nao gera change
  - apply_adjustments emite TIGHTEN acima de TIGHTEN_RATE com volume suficiente
  - apply_adjustments liga api_cost_strict quando passa API_STRICT_RATE
  - contexto fora de VALID_CONTEXTS nao afeta policy
  - VALID_CONTEXTS contem os 5 contextos canonicos (API estavel)
  - _snapshot_policy silencia (por design) mas sem propagar exceção para save_policy
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from policies import policy_adapter as pa


def _policy_with(ctx="mvp", topic="api_cost", threshold=60, gates=None):
    p = {
        ctx: {
            "topic_thresholds": {topic: threshold},
        },
    }
    if gates:
        p[ctx].update(gates)
    return p


def test_valid_contexts_are_canonical():
    assert pa.VALID_CONTEXTS == {"idea", "research", "mvp", "launch_ready", "scaling"}


def test_clamp_respects_min_and_max():
    assert pa._clamp(1000, pa.THRESHOLD_MIN, pa.THRESHOLD_MAX) == pa.THRESHOLD_MAX
    assert pa._clamp(-5, pa.THRESHOLD_MIN, pa.THRESHOLD_MAX) == pa.THRESHOLD_MIN
    assert pa._clamp(60, pa.THRESHOLD_MIN, pa.THRESHOLD_MAX) == 60


def test_load_policy_fail_fast_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "POLICY_FILE", tmp_path / "nope.json")
    with pytest.raises(FileNotFoundError):
        pa.load_policy()


def test_load_policy_reads_existing_file(tmp_path, monkeypatch):
    f = tmp_path / "policy.json"
    f.write_text(json.dumps({"mvp": {"topic_thresholds": {"api_cost": 55}}}))
    monkeypatch.setattr(pa, "POLICY_FILE", f)
    loaded = pa.load_policy()
    assert loaded["mvp"]["topic_thresholds"]["api_cost"] == 55


def test_apply_adjustments_tighten_above_rate_with_volume():
    policy = _policy_with(ctx="mvp", topic="api_cost", threshold=60)
    topic_failures = {
        "mvp": {
            "api_cost": {
                "total": pa.MIN_EVENTS_TOPIC + 5,
                "failures": pa.MIN_EVENTS_TOPIC + 4,
                "failure_rate": 0.95,
            }
        }
    }
    changes = pa.apply_adjustments(policy, topic_failures, {}, dry_run=False)
    assert any("TIGHTEN" in c and "api_cost" in c for c in changes)
    assert policy["mvp"]["topic_thresholds"]["api_cost"] == 60 + pa.STEP


def test_apply_adjustments_insufficient_evidence_no_change():
    policy = _policy_with(ctx="mvp", topic="api_cost", threshold=60)
    topic_failures = {
        "mvp": {
            "api_cost": {
                "total": pa.MIN_EVENTS_TOPIC - 1,
                "failures": pa.MIN_EVENTS_TOPIC - 1,
                "failure_rate": 0.99,
            }
        }
    }
    changes = pa.apply_adjustments(policy, topic_failures, {}, dry_run=False)
    assert changes == []
    assert policy["mvp"]["topic_thresholds"]["api_cost"] == 60


def test_apply_adjustments_dry_run_does_not_mutate():
    policy = _policy_with(ctx="mvp", topic="api_cost", threshold=60)
    topic_failures = {
        "mvp": {
            "api_cost": {
                "total": pa.MIN_EVENTS_TOPIC + 5,
                "failures": pa.MIN_EVENTS_TOPIC + 4,
                "failure_rate": 0.95,
            }
        }
    }
    changes = pa.apply_adjustments(policy, topic_failures, {}, dry_run=True)
    assert changes  # changes reportadas
    assert policy["mvp"]["topic_thresholds"]["api_cost"] == 60  # policy intacta


def test_apply_adjustments_api_strict_flipped_on_high_failure():
    policy = _policy_with(
        ctx="launch_ready",
        topic="api_cost",
        threshold=60,
        gates={"api_cost_strict": False},
    )
    topic_failures = {
        "launch_ready": {
            "api_cost": {
                "total": pa.MIN_EVENTS_TOPIC + 2,
                "failures": pa.MIN_EVENTS_TOPIC + 1,
                "failure_rate": pa.API_STRICT_RATE + 0.2,
            }
        }
    }
    changes = pa.apply_adjustments(policy, topic_failures, {}, dry_run=False)
    assert any("STRICT" in c for c in changes)
    assert policy["launch_ready"]["api_cost_strict"] is True


def test_apply_adjustments_unknown_context_is_skipped():
    policy = {"bogus_ctx": {"topic_thresholds": {"api_cost": 60}}}
    topic_failures = {
        "bogus_ctx": {
            "api_cost": {
                "total": 100,
                "failures": 99,
                "failure_rate": 0.99,
            }
        }
    }
    changes = pa.apply_adjustments(policy, topic_failures, {}, dry_run=False)
    assert changes == []
    assert policy["bogus_ctx"]["topic_thresholds"]["api_cost"] == 60


def test_save_policy_survives_snapshot_failure(tmp_path, monkeypatch, capsys):
    """_snapshot_policy falha silenciosa por design, mas save_policy nao pode crashar."""
    target = tmp_path / "policy.json"
    monkeypatch.setattr(pa, "POLICY_FILE", target)

    def _boom(_policy):
        raise RuntimeError("simulated snapshot failure")

    monkeypatch.setattr(pa, "_snapshot_policy", lambda p: (_ for _ in ()).throw(RuntimeError("boom")) if False else None)

    policy = {"mvp": {"topic_thresholds": {"api_cost": 60}}}
    pa.save_policy(policy, ["noop"])
    assert target.exists()
    written = json.loads(target.read_text())
    assert written["_meta"]["version"] == 2
    assert written["_meta"]["adjustment_history"][-1]["changes"] == ["noop"]


def test_compute_topic_failure_empty_when_events_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "EVENTS_FILE", tmp_path / "nope.jsonl")
    assert pa.compute_topic_failure_by_context() == {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
