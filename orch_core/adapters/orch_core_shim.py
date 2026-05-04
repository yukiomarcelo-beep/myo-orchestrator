"""
orch_core.adapters.orch_core_shim
==================================

Shim para `core/orch_core.py` (Orchestrator de debate GPT×Claude, LESSON-007).

O caller real no repo e `engines/opportunity_pipeline.py` que usa:
  - Orchestrator().process_signal(signal, debate_rounds)
  - OpportunityDecision, TrendSignal, trend_signal_from_dict, save_decision_json

Este shim:
1. Re-exporta os tipos de suporte sem mudanca de API
2. Wraps Orchestrator com DeprecationRegistry (contador de callers)
3. Facilita LESSON-013: quando contadores zerados por 7 dias, remove

Destino final (LESSON-013): callers migram para Scheduler.submit() com
um AgentExecutor de debate. Por enquanto o wrapper mantem a implementacao
existente.
"""

from __future__ import annotations

from typing import Any

# Re-exporta tipos sem mudanca — callers usam as mesmas classes
from core.orch_core import (
    OpportunityDecision,
    TrendSignal,
    save_decision_json,
    trend_signal_from_dict,
)
from core.orch_core import Orchestrator as _OriginalOrchestrator
from orch_core.adapters.deprecation import emit_deprecation


class OrcCoreShim:
    """Wrapper de Orchestrator (core/orch_core.py) com rastreio de deprecacao.

    Uso de migracao:
        # antes:
        from core.orch_core import Orchestrator, OpportunityDecision, ...
        orch = Orchestrator(verbose=True)
        decision = orch.process_signal(signal, debate_rounds=3)

        # depois (via shim):
        from orch_core.adapters.orch_core_shim import OrcCoreShim, OpportunityDecision, ...
        orch = OrcCoreShim(verbose=True)
        decision = orch.process_signal(signal, debate_rounds=3)
    """

    SHIM_NAME = "core.orch_core.Orchestrator (legacy debate loop)"
    REPLACEMENT = "orch_core.control.scheduler.Scheduler + debate AgentExecutor"

    def __init__(self, verbose: bool = True, **kwargs: Any) -> None:
        self._inner = _OriginalOrchestrator(verbose=verbose, **kwargs)

    def process_signal(
        self,
        signal: Any,
        debate_rounds: int = 3,
    ) -> OpportunityDecision:
        emit_deprecation(
            shim=f"{self.SHIM_NAME}.process_signal",
            replacement=self.REPLACEMENT,
        )
        return self._inner.process_signal(signal, debate_rounds=debate_rounds)


__all__ = [
    "OrcCoreShim",
    "OpportunityDecision",
    "TrendSignal",
    "trend_signal_from_dict",
    "save_decision_json",
]
