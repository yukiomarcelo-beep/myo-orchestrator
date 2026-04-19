"""
orch_core — pacote canonico unificado.

Ver docs/memoria/LESSON-008 em diante.
"""
from orch_core.contracts import (
    Agent,
    AgentNotFound,
    Event,
    InvalidTransition,
    OrchError,
    Run,
    RunSpec,
    RunStatus,
    Step,
    TenantIsolationViolation,
    Tool,
    ToolNotFound,
    is_valid_transition,
    new_run,
    replace_run,
)

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "AgentNotFound",
    "Event",
    "InvalidTransition",
    "OrchError",
    "Run",
    "RunSpec",
    "RunStatus",
    "Step",
    "TenantIsolationViolation",
    "Tool",
    "ToolNotFound",
    "__version__",
    "is_valid_transition",
    "new_run",
    "replace_run",
]
