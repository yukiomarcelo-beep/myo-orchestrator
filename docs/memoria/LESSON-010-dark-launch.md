# Dark-launch protocol — Runner canônico (LESSON-010)

> **STATUS:** TEMPLATE. Implementar antes do cutover em produção.

## Por que existe

O Runner canônico substitui 3 loops de `tool_use` que hoje rodam em
produção. Ligar direto é suicídio: qualquer divergência de semântica
quebra War Room, BellaFlow, LuxAI, etc.

Dark-launch = executar o canônico **em paralelo** com o legacy, comparar
os dois, **servir só o legacy** até o canônico provar equivalência por N
dias.

## Arquitetura proposta

```
caller
   │
   ▼
LegacyShim  ───► legacy orchestrator ──► result_legacy ─► caller recebe
   │
   └── (fire-and-forget) ──► ShadowRunner ──► canonical Runner
                                 │
                                 └─► compara hashes
                                     registra em run.shadow_divergence
```

Pontos-chave:
- Canônico roda em **thread/worker separado**, não bloqueia o caller
- Caller SEMPRE recebe `result_legacy`
- Se canônico levantar excepção: **não propaga**, só loga
- Se canônico demorar mais que 2× o legacy: cancela com timeout

## Critérios de divergência

### Hard-fail (bloqueia promoção)

- `status` final diferente (ex.: legacy `done`, canônico `failed`)
- Lista de `tool_name` chamadas difere em ordem ou conteúdo
- `policy_denied` em um mas não no outro
- `tenant_id` ou `project_id` no audit diferem

### Soft-fail (log, não bloqueia)

- `text` final difere (LLM é não-determinístico; isso é esperado)
- Número de steps difere em até ±1 (um pode encurtar rota)
- Timing difere em até 3×

### Ignorar completamente

- `run_id`, `step_id`, timestamps, event_id — obviamente diferentes
- Ordem de eventos entre `run.started` e `run.step` (race condition
  benigna)

## Gate de promoção

Promove pra produção quando, por **7 dias corridos**:

1. Zero hard-fails
2. Soft-fail rate <1% dos runs
3. p95 latência do canônico ≤ p95 latência do legacy × 1.2
4. Zero excepções não-tratadas no canônico
5. CI verde em todos os commits

## Implementação (esqueleto)

```python
# orch_core/execution/shadow.py
import hashlib
import json
import threading
from typing import Any, Callable

from orch_core.contracts import RunSpec
from orch_core.execution.runner import Runner, RunResult


class ShadowRunner:
    def __init__(
        self,
        *,
        canonical: Runner,
        legacy: Callable[[RunSpec], Any],
        on_divergence: Callable[[dict], None],
    ) -> None:
        self._canonical = canonical
        self._legacy = legacy
        self._on_divergence = on_divergence

    def execute(self, spec: RunSpec) -> Any:
        legacy_result = self._legacy(spec)
        # Dispara canônico em background
        threading.Thread(
            target=self._shadow,
            args=(spec, legacy_result),
            daemon=True,
        ).start()
        return legacy_result

    def _shadow(self, spec: RunSpec, legacy_result: Any) -> None:
        try:
            canonical_result = self._canonical.execute(spec)
            diff = self._compare(legacy_result, canonical_result)
            if diff:
                self._on_divergence(diff)
        except BaseException as e:
            self._on_divergence({"kind": "canonical_crashed", "error": str(e)})

    @staticmethod
    def _compare(legacy: Any, canon: RunResult) -> dict | None:
        # Hash estruturado ignorando campos voláteis
        # Implementar segundo os critérios de divergência acima
        ...
```

## Rollback

Se hard-fail detectado em produção:

```bash
# .env (sem deploy)
ORCH_USE_CANONICAL_RUNNER=false
ORCH_RUNNER_SHADOW_MODE=false
```

Reinicia processos. Tudo volta pro legacy. Zero deploy.

## Pós-promoção

Quando os 7 dias fecharem verde:

1. `ORCH_USE_CANONICAL_RUNNER=true` em prod
2. `ORCH_RUNNER_SHADOW_MODE=false` (não precisa mais shadow)
3. Legacy vira shim com `DeprecationWarning` (isso é a LESSON-012)
4. LESSON-013 remove o shim quando os warnings zerarem por 7 dias
