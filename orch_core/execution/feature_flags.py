"""
orch_core.execution.feature_flags
==================================

Feature flags por fase. Rollout gradual + rollback instantaneo.

Precedencia: env var > default.

Flags:
- ORCH_USE_CANONICAL_RUNNER: quando False, chamadas devem cair nos
  shims dos orquestradores antigos. Default: True (flag existe pra
  permitir desligar em incidente).
- ORCH_RUNNER_MAX_STEPS: limite de rodadas do loop tool_use.
  Default: 25.
- ORCH_RUNNER_SHADOW_MODE: quando True, executa canonico em shadow
  e retorna resultado do legacy (usado na fase de dark-launch).
  Default: False.
"""
from __future__ import annotations

import os
from typing import Final


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class FeatureFlags:
    """Namespace de flags. Nao e singleton; re-instanciar a cada run
    permite testes injetarem overrides sem mexer em env global."""

    def __init__(
        self,
        *,
        use_canonical_runner: bool | None = None,
        runner_max_steps: int | None = None,
        shadow_mode: bool | None = None,
    ) -> None:
        self.use_canonical_runner = (
            use_canonical_runner
            if use_canonical_runner is not None
            else _bool("ORCH_USE_CANONICAL_RUNNER", True)
        )
        self.runner_max_steps = (
            runner_max_steps
            if runner_max_steps is not None
            else _int("ORCH_RUNNER_MAX_STEPS", 25)
        )
        self.shadow_mode = (
            shadow_mode
            if shadow_mode is not None
            else _bool("ORCH_RUNNER_SHADOW_MODE", False)
        )


DEFAULT_MAX_STEPS: Final[int] = 25

__all__ = ["DEFAULT_MAX_STEPS", "FeatureFlags"]
