"""Smoke test: invariantes da API publica de utils/verification_logger.py (LESSON-006).

Cobre:
  - _normalize_context retorna 'unknown' para invalidos sem crashar
  - _normalize_context trata None e '' como 'unknown' silencioso (sem warn ruidoso)
  - _normalize_context normaliza case e whitespace (propagacao canonica)
  - _build_event propaga execution_context no evento emitido
  - _build_event usa 'unknown' quando ctx invalido (nao silencia internamente)
  - _build_event e defensivo quando pack.sources ausente (getattr)
  - VerificationLogger.log grava JSONL auditavel e retorna lista
  - VerificationLogger.log cria diretorio pai automaticamente
  - VerificationLogger.load_events pula linhas JSON invalidas sem crashar
  - VerificationLogger.load_events retorna [] se arquivo inexistente (nao crasha)
  - VALID_CONTEXTS == 5 contextos canonicos (API estavel)
"""
import json
import sys
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import verification_logger as vl


class _FakeEnum(Enum):
    FACT = "fact"


class _FakeMode(Enum):
    ALLOW = "allow"


def _make_pack(claim="retorno foi 20%", topic="finance", ctx_sources=None):
    pack = SimpleNamespace(
        topic=topic,
        criticality="high",
        claim_type=_FakeEnum.FACT,
        claim=claim,
        confidence=0.8,
        verified=True,
        requires_validation=False,
        is_critical_failure=False,
        validation_question=None,
        specific_policy_triggered=None,
    )
    if ctx_sources is not None:
        pack.sources = ctx_sources
    return pack


def _make_result(verified=None, unverified=None):
    return SimpleNamespace(
        source_quality_score=0.75,
        source_count=2,
        execution_mode=_FakeMode.ALLOW,
        safe_to_execute=True,
        verified_claims=verified or [],
        unverified_claims=unverified or [],
        critical_failures=[],
    )


def test_valid_contexts_are_canonical():
    assert vl.VALID_CONTEXTS == {"idea", "research", "mvp", "launch_ready", "scaling"}


def test_normalize_context_accepts_canonical():
    for ctx in ["idea", "research", "mvp", "launch_ready", "scaling"]:
        assert vl._normalize_context(ctx) == ctx


def test_normalize_context_strips_and_lowercases():
    assert vl._normalize_context("  MVP  ") == "mvp"
    assert vl._normalize_context("Launch_Ready") == "launch_ready"


def test_normalize_context_invalid_returns_unknown_with_warning(capsys):
    assert vl._normalize_context("production") == "unknown"
    out = capsys.readouterr().out
    assert "execution_context inválido" in out


def test_normalize_context_empty_and_none_silent():
    """Entrada vazia nao gera warning ruidoso mas retorna unknown."""
    assert vl._normalize_context("") == "unknown"
    assert vl._normalize_context(None) == "unknown"


def test_build_event_propagates_execution_context():
    pack = _make_pack()
    result = _make_result()
    event = vl._build_event(pack, result, origin_engine="test", entity_id="e1",
                            execution_context="launch_ready")
    assert event["execution_context"] == "launch_ready"
    assert event["origin_engine"] == "test"
    assert event["entity_id"] == "e1"
    assert event["topic"] == "finance"


def test_build_event_invalid_context_becomes_unknown():
    pack = _make_pack()
    result = _make_result()
    event = vl._build_event(pack, result, "test", "e1", execution_context="bogus")
    assert event["execution_context"] == "unknown"


def test_build_event_defensive_when_pack_sources_missing():
    """pack sem atributo sources nao pode crashar _build_event."""
    pack = _make_pack()  # sem sources
    result = _make_result()
    event = vl._build_event(pack, result, "test", "e1", execution_context="mvp")
    assert event["sources"] == []


def test_logger_log_writes_jsonl_auditable(tmp_path, capsys):
    events_file = tmp_path / "trust" / "verification_events.jsonl"
    logger = vl.VerificationLogger(events_file=events_file)
    pack = _make_pack()
    result = _make_result(verified=[pack])
    written = logger.log(result, origin_engine="engine_x", entity_id="abc",
                         execution_context="mvp")
    assert len(written) == 1
    assert events_file.exists()
    lines = events_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["execution_context"] == "mvp"
    assert parsed["origin_engine"] == "engine_x"


def test_logger_creates_parent_dir(tmp_path):
    events_file = tmp_path / "nested" / "path" / "events.jsonl"
    vl.VerificationLogger(events_file=events_file)
    assert events_file.parent.exists()


def test_load_events_skips_bad_json_without_crashing(tmp_path):
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps({"event_id": "v_1"}) + "\n"
        + "not-valid-json\n"
        + json.dumps({"event_id": "v_2"}) + "\n",
        encoding="utf-8",
    )
    logger = vl.VerificationLogger(events_file=events_file)
    events = logger.load_events()
    assert [e["event_id"] for e in events] == ["v_1", "v_2"]


def test_load_events_returns_empty_when_file_missing(tmp_path):
    logger = vl.VerificationLogger(events_file=tmp_path / "nope.jsonl")
    assert logger.load_events() == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
