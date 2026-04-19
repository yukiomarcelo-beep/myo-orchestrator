"""
orch_core.adapters.deprecation
===============================

Infra comum dos shims legados (LESSON-012).

Responsabilidades:
- Emitir DeprecationWarning com contexto (caller module, funcao, stack)
- Contar callers por modulo pra priorizar migracao (grep de producao)
- Permitir silenciar em producao via ORCH_DEPRECATION_SILENT=1 (durante
  janela de observacao do dark-launch; NAO em dev)
- Registrar cada chamada no log estruturado pro operador rastrear quem
  ainda depende dos shims

Criterio de remocao dos shims (LESSON-013):
- Contador de cada caller zerado por 7 dias corridos em producao
- Zero DeprecationWarning capturado no log estruturado
"""
from __future__ import annotations

import functools
import inspect
import logging
import os
import sys
import threading
import warnings
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_logger = logging.getLogger("orch_core.deprecation")


def _silent() -> bool:
    raw = os.environ.get("ORCH_DEPRECATION_SILENT", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class CallerTrace:
    shim: str
    caller_module: str
    caller_function: str
    caller_file: str
    caller_line: int


class DeprecationRegistry:
    """Contador global de chamadas por (shim, caller_module).

    Uso em producao: logar periodicamente
    default_registry().snapshot() pra acompanhar a curva de callers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, str], int] = defaultdict(int)
        self._traces: list[CallerTrace] = []

    def record(self, trace: CallerTrace) -> None:
        with self._lock:
            self._counts[(trace.shim, trace.caller_module)] += 1
            self._traces.append(trace)

    def snapshot(self) -> dict[tuple[str, str], int]:
        with self._lock:
            return dict(self._counts)

    def traces(self) -> list[CallerTrace]:
        with self._lock:
            return list(self._traces)

    def clear(self) -> None:
        """So pra testes."""
        with self._lock:
            self._counts.clear()
            self._traces.clear()


_registry: DeprecationRegistry | None = None
_registry_lock = threading.Lock()


def default_deprecation_registry() -> DeprecationRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = DeprecationRegistry()
    return _registry


def reset_deprecation_registry() -> None:
    """Testes only."""
    global _registry
    with _registry_lock:
        _registry = None


def _identify_caller(skip_frames: int = 3) -> tuple[str, str, str, int]:
    """Retorna (module, function, file, line) do caller externo ao
    proprio arquivo de shim."""
    frame = inspect.currentframe()
    # Pula: _identify_caller -> _emit -> wrapper do @deprecated_shim -> caller real
    for _ in range(skip_frames):
        if frame is None:
            break
        frame = frame.f_back
    if frame is None:
        return ("<unknown>", "<unknown>", "<unknown>", 0)
    module = frame.f_globals.get("__name__", "<unknown>")
    function = frame.f_code.co_name
    file = frame.f_code.co_filename
    line = frame.f_lineno
    return (module, function, file, line)


def emit_deprecation(
    *,
    shim: str,
    replacement: str,
    skip_frames: int = 3,
) -> CallerTrace:
    """Emite DeprecationWarning + registra no log estruturado +
    incrementa contador. Retorna a trace pra quem quiser logar com
    contexto adicional."""
    module, function, file, line = _identify_caller(skip_frames=skip_frames)
    trace = CallerTrace(
        shim=shim,
        caller_module=module,
        caller_function=function,
        caller_file=file,
        caller_line=line,
    )
    default_deprecation_registry().record(trace)

    if not _silent():
        warnings.warn(
            f"{shim} is deprecated; use {replacement} instead "
            f"(caller: {module}.{function} at {file}:{line})",
            DeprecationWarning,
            stacklevel=skip_frames + 1,
        )
    # Log estruturado SEMPRE (mesmo silencioso) — e a fonte pro
    # criterio de remocao da LESSON-013
    _logger.info(
        "deprecation.shim_called",
        extra={
            "shim": shim,
            "replacement": replacement,
            "caller_module": module,
            "caller_function": function,
            "caller_file": file,
            "caller_line": line,
        },
    )
    return trace


def deprecated_shim(
    *, shim: str, replacement: str
) -> Callable[[F], F]:
    """Decorator. Aplica emit_deprecation antes de executar o shim."""

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            emit_deprecation(shim=shim, replacement=replacement)
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


__all__ = [
    "CallerTrace",
    "DeprecationRegistry",
    "default_deprecation_registry",
    "deprecated_shim",
    "emit_deprecation",
    "reset_deprecation_registry",
]
