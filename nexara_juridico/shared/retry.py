"""
Retry com backoff exponencial para chamadas à API Anthropic.
Resolve: rate limits e erros transientes derrubando análises.
"""

import asyncio
import functools
import logging
from typing import Any, Callable

import anthropic

logger = logging.getLogger(__name__)

ERROS_RETRIABLE = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
)
ERROS_FATAIS = (
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.BadRequestError,
)


async def com_retry(
    func: Callable,
    *args,
    max_tentativas: int = 4,
    espera_base: float = 2.0,
    espera_maxima: float = 60.0,
    **kwargs,
) -> Any:
    import random

    ultima = None
    for tentativa in range(1, max_tentativas + 1):
        try:
            return await func(*args, **kwargs)
        except ERROS_FATAIS as e:
            logger.error(f"Erro fatal: {type(e).__name__}: {e}")
            raise
        except ERROS_RETRIABLE as e:
            ultima = e
            if tentativa == max_tentativas:
                raise
            espera = min(espera_base * (2 ** (tentativa - 1)), espera_maxima)
            espera *= random.uniform(0.8, 1.2)
            retry_after = getattr(getattr(e, "response", None), "headers", {}).get("retry-after")
            if retry_after:
                try:
                    espera = max(espera, float(retry_after))
                except (ValueError, TypeError):
                    pass
            logger.warning(
                f"Tentativa {tentativa}/{max_tentativas} falhou: "
                f"{type(e).__name__}. Aguardando {espera:.1f}s..."
            )
            await asyncio.sleep(espera)
        except Exception as e:
            logger.error(f"Erro inesperado: {type(e).__name__}: {e}")
            raise
    raise ultima


def com_retry_decorator(max_tentativas: int = 4, espera_base: float = 2.0):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await com_retry(
                func, *args, max_tentativas=max_tentativas, espera_base=espera_base, **kwargs
            )

        return wrapper

    return decorator
