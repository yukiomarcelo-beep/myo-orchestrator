"""
core.llm_gateway
================

Camada de acesso ao Claude com:
  - Prompt caching via anthropic-beta: prompt-caching-2024-07-31
    (cache_control ephemeral no system prompt quando len >= _MIN_CACHE_CHARS)
  - Retry com backoff exponencial + jitter (até 3 tentativas em 429/5xx)
  - Circuit breaker 3 estados: CLOSED → OPEN → HALF_OPEN → CLOSED

Feature flag: MYO_USE_LLM_GATEWAY (env, default "true")
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MYO_USE_LLM_GATEWAY = os.getenv("MYO_USE_LLM_GATEWAY", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# ~1024 tokens × 4 chars/token — threshold mínimo exigido pela API para caching.
# Prompts mais curtos não recebem cache_control e são enviados como string simples.
_MIN_CACHE_CHARS = 4096


@dataclass
class GatewayResponse:
    text: str
    cost_usd: float
    latency_ms: int
    cached: bool = False  # True quando cache_read_input_tokens > 0
    input_tokens: int = 0
    output_tokens: int = 0


class _CircuitBreaker:
    """
    Circuit breaker 3 estados:

      CLOSED     → operação normal
      OPEN       → bloqueia todas as chamadas
      HALF_OPEN  → permite UMA chamada de sonda após o cooldown;
                   sucesso → CLOSED, falha → OPEN (cooldown reinicia)

    Transição OPEN → HALF_OPEN ocorre dentro de `is_open`, que detecta
    o fim do cooldown e transita automaticamente para HALF_OPEN antes de
    retornar False — permitindo a próxima chamada passar como sonda.
    """

    _CLOSED = "closed"
    _OPEN = "open"
    _HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 5, cooldown_secs: float = 60.0) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_secs
        self._failures = 0
        self._state = self._CLOSED
        self._opened_at: Optional[float] = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_open(self) -> bool:
        """
        Retorna True se chamadas devem ser bloqueadas.

        Efeito colateral intencional: quando o cooldown expira enquanto
        em OPEN, transita para HALF_OPEN e retorna False — liberando
        exatamente uma chamada de sonda sem redefinir os contadores.
        """
        if self._state == self._CLOSED:
            return False
        if self._state == self._HALF_OPEN:
            return False
        # OPEN: verifica se o cooldown expirou
        if time.monotonic() - self._opened_at >= self._cooldown:
            self._state = self._HALF_OPEN
            logger.info("circuit_breaker state=half_open")
            return False
        return True

    def record_success(self) -> None:
        if self._state != self._CLOSED:
            logger.info("circuit_breaker state=closed (success)")
        self._failures = 0
        self._state = self._CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        if self._state == self._HALF_OPEN:
            # sonda falhou → reabre com cooldown reiniciado
            self._state = self._OPEN
            self._opened_at = time.monotonic()
            logger.warning("circuit_breaker state=open (half_open probe failed)")
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._state = self._OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "circuit_breaker state=open failures=%d threshold=%d",
                self._failures,
                self._threshold,
            )


class LLMGateway:
    """
    Gateway síncrono para Claude.

    Uso:
        gw = LLMGateway()
        resp = gw.chat(system="Você é...", prompt="Analise X")
        print(resp.text, resp.cost_usd, resp.cached)

    Raises:
        RuntimeError: circuit breaker aberto ou esgotadas as tentativas.
    """

    _MAX_RETRIES = 3
    _RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 529})
    _BASE_DELAY_SECS = 1.0

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        timeout: float = 90.0,
        failure_threshold: int = 5,
        cooldown_secs: float = 60.0,
    ) -> None:
        self._api_key = api_key or ANTHROPIC_API_KEY
        self._model = model or CLAUDE_MODEL
        self._timeout = timeout
        self._cb = _CircuitBreaker(failure_threshold, cooldown_secs)

    def chat(
        self,
        system: str,
        prompt: str,
        *,
        max_tokens: int = 1500,
        temperature: float = 0.5,
        cache_system: bool = True,
    ) -> GatewayResponse:
        """
        Chama Claude com caching de system prompt (quando >= _MIN_CACHE_CHARS),
        retry exponencial e circuit breaker.

        Args:
            cache_system: quando True E len(system) >= _MIN_CACHE_CHARS,
                          adiciona cache_control ephemeral ao system prompt.
        """
        if self._cb.is_open:
            raise RuntimeError(
                f"LLMGateway: circuit breaker {self._cb.state} — aguardando cooldown"
            )

        # TODO(2026-04-27): verificar se anthropic-beta: prompt-caching-2024-07-31
        # ainda é obrigatório ou se o prompt caching já saiu de beta na API.
        # O header é seguro de manter (no-op se já GA), mas pode ser removido
        # após confirmação em https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "anthropic-beta": "prompt-caching-2024-07-31",
        }

        use_cache = cache_system and system and len(system) >= _MIN_CACHE_CHARS
        system_payload: list | str = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if use_cache
            else (system or "")
        )

        payload: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_payload,
            "messages": [{"role": "user", "content": prompt}],
        }

        last_exc: Exception = RuntimeError("nenhuma tentativa realizada")

        for attempt in range(self._MAX_RETRIES):
            try:
                t0 = time.time()
                with httpx.Client(timeout=self._timeout) as c:
                    resp = c.post(
                        "https://api.anthropic.com/v1/messages",
                        json=payload,
                        headers=headers,
                    )

                if resp.status_code in self._RETRYABLE_STATUS:
                    delay = self._BASE_DELAY_SECS * (2**attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        "llm_gateway retry attempt=%d status=%d delay_secs=%.2f",
                        attempt + 1,
                        resp.status_code,
                        delay,
                    )
                    time.sleep(delay)
                    last_exc = RuntimeError(f"HTTP {resp.status_code} (tentativa {attempt + 1})")
                    continue

                resp.raise_for_status()

                data = resp.json()
                lat = int((time.time() - t0) * 1000)
                u = data.get("usage", {})

                input_tokens = u.get("input_tokens", 0)
                output_tokens = u.get("output_tokens", 0)
                cache_write_tokens = u.get("cache_creation_input_tokens", 0)
                cache_read_tokens = u.get("cache_read_input_tokens", 0)

                logger.debug(
                    "llm_gateway tokens input=%d output=%d cache_write=%d cache_read=%d "
                    "latency_ms=%d",
                    input_tokens,
                    output_tokens,
                    cache_write_tokens,
                    cache_read_tokens,
                    lat,
                )

                # Custo com prompt caching:
                #   input (não-cacheado)  → $3.00/M
                #   cache_write           → $3.75/M (1.25× — escreve no cache)
                #   cache_read            → $0.30/M (0.10× — lê do cache)
                #   output                → $15.00/M
                cost = round(
                    input_tokens * 3e-6
                    + output_tokens * 15e-6
                    + cache_write_tokens * 3.75e-6
                    + cache_read_tokens * 0.3e-6,
                    6,
                )

                self._cb.record_success()
                return GatewayResponse(
                    text=data["content"][0]["text"],
                    cost_usd=cost,
                    latency_ms=lat,
                    cached=cache_read_tokens > 0,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            except httpx.HTTPStatusError as exc:
                self._cb.record_failure()
                raise RuntimeError(f"LLMGateway: erro HTTP {exc.response.status_code}") from exc

            except Exception as exc:
                last_exc = exc
                delay = self._BASE_DELAY_SECS * (2**attempt) + random.uniform(0, 0.5)
                time.sleep(delay)

        self._cb.record_failure()
        raise RuntimeError(
            f"LLMGateway: {self._MAX_RETRIES} tentativas esgotadas — {last_exc}"
        ) from last_exc


_gateway: Optional[LLMGateway] = None


def get_gateway() -> LLMGateway:
    """Instância de processo. Crie instâncias separadas se precisar de CBs independentes."""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
