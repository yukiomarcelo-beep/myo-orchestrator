"""
Testes de core.llm_gateway

Cenários cobertos:
  1. caching aplicado quando system prompt >= _MIN_CACHE_CHARS
  2. caching NÃO aplicado quando system prompt < _MIN_CACHE_CHARS
  3. retry em 429 — mock chamado mais de uma vez
  4. circuit breaker abre após 5 falhas consecutivas
  5. circuit breaker transita OPEN → HALF_OPEN → CLOSED após cooldown + sucesso
  6. logging estruturado emite os 4 campos de tokens (input, output, cache_write, cache_read)
"""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock, patch

import pytest

from core.llm_gateway import (
    _MIN_CACHE_CHARS,
    LLMGateway,
    _CircuitBreaker,
)

# ── helpers ───────────────────────────────────────────────────────────────────


def _ok_response(
    text: str = "ok",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_write: int = 0,
    cache_read: int = 0,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "content": [{"text": text}],
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_write,
            "cache_read_input_tokens": cache_read,
        },
    }
    return resp


def _status_response(status: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    return resp


def _make_gw(**kwargs) -> LLMGateway:
    return LLMGateway(api_key="test-key", **kwargs)


# ── cenário 1: caching aplicado quando system >= _MIN_CACHE_CHARS ─────────────


def test_cache_applied_for_long_system_prompt():
    system = "x" * _MIN_CACHE_CHARS  # exatamente no limite
    gw = _make_gw()

    with patch("httpx.Client") as MockClient, patch("time.sleep"):
        mock_post = MockClient.return_value.__enter__.return_value.post
        mock_post.return_value = _ok_response(cache_read=80)

        resp = gw.chat(system, "prompt")

    payload = mock_post.call_args.kwargs["json"]
    assert isinstance(payload["system"], list), "system deve ser lista quando cacheado"
    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert resp.cached is True


# ── cenário 2: caching NÃO aplicado quando system < _MIN_CACHE_CHARS ─────────


def test_cache_not_applied_for_short_system_prompt():
    system = "x" * (_MIN_CACHE_CHARS - 1)  # um char abaixo do limite
    gw = _make_gw()

    with patch("httpx.Client") as MockClient, patch("time.sleep"):
        mock_post = MockClient.return_value.__enter__.return_value.post
        mock_post.return_value = _ok_response()

        resp = gw.chat(system, "prompt")

    payload = mock_post.call_args.kwargs["json"]
    assert isinstance(payload["system"], str), "system deve ser string quando não cacheado"
    assert resp.cached is False


def test_cache_not_applied_when_cache_system_false():
    system = "x" * (_MIN_CACHE_CHARS + 100)  # longo mas cache_system=False
    gw = _make_gw()

    with patch("httpx.Client") as MockClient, patch("time.sleep"):
        mock_post = MockClient.return_value.__enter__.return_value.post
        mock_post.return_value = _ok_response()

        gw.chat(system, "prompt", cache_system=False)

    payload = mock_post.call_args.kwargs["json"]
    assert isinstance(payload["system"], str)


# ── cenário 3: retry em 429 com mock chamado mais de uma vez ──────────────────


def test_retry_on_429_calls_post_multiple_times():
    gw = _make_gw()

    with patch("httpx.Client") as MockClient, patch("time.sleep") as mock_sleep:
        mock_post = MockClient.return_value.__enter__.return_value.post
        mock_post.side_effect = [
            _status_response(429),
            _status_response(429),
            _ok_response(text="terceira tentativa"),
        ]

        resp = gw.chat("sys", "prompt")

    assert mock_post.call_count == 3, "deve tentar 3 vezes (2×429 + 1×200)"
    assert resp.text == "terceira tentativa"
    assert mock_sleep.call_count == 2  # sleep após cada 429


def test_retry_exhausted_raises_after_max_retries():
    gw = _make_gw()

    with patch("httpx.Client") as MockClient, patch("time.sleep"):
        mock_post = MockClient.return_value.__enter__.return_value.post
        mock_post.return_value = _status_response(429)

        with pytest.raises(RuntimeError, match="tentativas esgotadas"):
            gw.chat("sys", "prompt")

    assert mock_post.call_count == 3


# ── cenário 4: circuit breaker abre após 5 falhas consecutivas ───────────────


def test_circuit_breaker_opens_after_5_failures():
    cb = _CircuitBreaker(failure_threshold=5, cooldown_secs=60.0)
    assert cb.state == "closed"

    for i in range(4):
        cb.record_failure()
        assert cb.state == "closed", f"não deve abrir com {i+1} falhas"
        assert not cb.is_open

    cb.record_failure()  # 5ª falha
    assert cb.state == "open"
    assert cb.is_open


def test_circuit_breaker_blocks_calls_when_open():
    gw = _make_gw(failure_threshold=1, cooldown_secs=60.0)
    gw._cb.record_failure()
    assert gw._cb.is_open

    with pytest.raises(RuntimeError, match="circuit breaker"):
        gw.chat("sys", "prompt")


# ── cenário 5: OPEN → HALF_OPEN → CLOSED após cooldown + sucesso ─────────────


def test_circuit_breaker_transitions_open_half_open_closed():
    cb = _CircuitBreaker(failure_threshold=1, cooldown_secs=0.05)

    # Abre o circuito
    cb.record_failure()
    assert cb.state == "open"
    assert cb.is_open

    # Aguarda cooldown expirar
    time.sleep(0.1)

    # Próxima chamada a is_open deve transitar para HALF_OPEN
    assert not cb.is_open, "cooldown expirado: deve permitir sonda"
    assert cb.state == "half_open"

    # Sucesso na sonda → CLOSED
    cb.record_success()
    assert cb.state == "closed"
    assert not cb.is_open


def test_circuit_breaker_half_open_failure_reopens():
    cb = _CircuitBreaker(failure_threshold=1, cooldown_secs=0.05)

    cb.record_failure()
    time.sleep(0.1)
    assert not cb.is_open  # transita para half_open
    assert cb.state == "half_open"

    # Falha na sonda → re-abre
    cb.record_failure()
    assert cb.state == "open"
    assert cb.is_open


# ── cenário 6: logging estruturado com 4 campos de tokens ────────────────────


def test_structured_logging_emits_four_token_fields(caplog):
    gw = _make_gw()

    with caplog.at_level(logging.DEBUG, logger="core.llm_gateway"):
        with patch("httpx.Client") as MockClient, patch("time.sleep"):
            mock_post = MockClient.return_value.__enter__.return_value.post
            mock_post.return_value = _ok_response(
                input_tokens=300,
                output_tokens=120,
                cache_write=200,
                cache_read=80,
            )
            gw.chat("sys", "prompt")

    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert debug_records, "nenhum log DEBUG emitido"

    log_msg = debug_records[0].getMessage()
    assert "input=300" in log_msg
    assert "output=120" in log_msg
    assert "cache_write=200" in log_msg
    assert "cache_read=80" in log_msg
