# LESSON-010 — Runner canônico

## Contexto

Fase mais densa da unificação. Substitui os três loops de `tool_use`
duplicados em `master_controller`, `orch_core` antigo e `orchestrator.py`
por um único Runner stateless. É a primeira LESSON que executa código
real (as 008 e 009 são estruturais).

Dependências diretas: LESSON-008 (contratos), LESSON-009 (Registry).

## Sugerido

### Arquitetura

- **Runner stateless.** Não carrega estado entre runs; estado vive no
  `ExecutionContext` in-flight + `AuditSink` persistido. Permite N runs
  em paralelo na mesma instância sem corrida.
- **Ports-and-adapters.** Runner depende só de Protocols (`AuditSink`,
  `RuntimeGuard`, `AgentExecutor`, `EventSink`, `ExecutionContext`).
  Zero import de concretos das LESSONS 002/003/004 — plugados via
  adaptadores finos no Claude Code.
- **Loop único de tool_use.** Limite configurável via
  `ORCH_RUNNER_MAX_STEPS` (default 25). Tool que explode vira
  `tool_result` com status=error, run continua; `stop_reason=error` do
  agente mata o run com status=failed.
- **Cancelamento cooperativo.** `is_cancelled: Callable[[], bool]`
  consultado no início de cada step e antes de cada tool call.
- **Eventos canônicos:** `run.created`, `run.started`, `run.step`,
  `run.finished`, `run.failed`, `run.cancelled`.
- **Idempotência de steps.** Cada step tem `step_id` único. Retry
  re-executa, audit registra ambos. Reconciliação é do caller/Scheduler.

### Arquivos

- `orch_core/observability/ports.py` — Protocols dos 5 ports
- `orch_core/execution/feature_flags.py` — `FeatureFlags` +
  `ORCH_USE_CANONICAL_RUNNER`, `ORCH_RUNNER_MAX_STEPS`,
  `ORCH_RUNNER_SHADOW_MODE`
- `orch_core/execution/context_builder.py` — `build_messages()`,
  `build_tools()`, `resolve_agent()`
- `orch_core/execution/policy.py` — `enforce_tool_call()`, `PolicyDenied`
- `orch_core/execution/runner.py` — `Runner`, `RunResult`,
  `RunCancelled`, `MaxStepsExceeded`

### Invariantes reforçados

1. Runner NUNCA chama `RuntimeGuard` direto; sempre via `enforce_tool_call()`
2. Runner NUNCA instancia `Run` direto; sempre via `new_run()` (LESSON-008)
3. Runner NUNCA grava em lugar nenhum que não seja o `AuditSink` + `EventSink`
4. Runner NUNCA conhece HTTP, SSE, PostgreSQL. Esses são adapters (LESSON-012)

## Feito

- 5 módulos Python completos (~600 linhas produção)
- 15 smoke tests cobrindo todos os paths críticos:
  1. Run sem tools → done
  2. Run com 1 tool call → done
  3. Múltiplos tool calls em rodadas sucessivas
  4. Max steps excedido → failed
  5. Tool explodiu → tool_result error, run continua
  6. Cancel antes do primeiro step → cancelled
  7. Cancel no meio da chain → cancelled
  8. Audit grava kinds canônicos na ordem correta
  9. Runtime guard bloqueia → PolicyDenied, run failed
  10. tenant_id preservado em todos os audit records
  11. parent_run_id propaga
  12. Stream de eventos em ordem canônica
  13. Runner stateless: 10 execuções concorrentes, zero interferência
  14. `stop_reason=error` → run failed
  15. Agent não registrado → run failed com AgentNotFound
- Fakes reutilizáveis em `tests/smoke/_fakes.py` (FakeAudit, FakeGuard,
  FakeEvents, ScriptedExecutor, SimpleAgent, EchoTool, BoomTool,
  DangerTool)
- **37/37 smokes passam** (12 LESSON-008 + 10 LESSON-009 + 15 LESSON-010)

## Erros

- **Dark-launch ainda não implementado.** Flag `ORCH_RUNNER_SHADOW_MODE`
  existe mas não há infra pra executar canônico em paralelo com legacy
  e comparar. Esse é o item crítico pra Sonnet 4.6 completar antes do
  cutover em produção.
- **Idempotência de retry é do caller.** Runner não reconhece "já vi
  esse step_id antes". Se o Scheduler (LESSON-011) retryar um run, dois
  runs diferentes com run_ids diferentes executam. Correto pro design
  stateless, mas precisa ser explícito na LESSON-011.
- **Tool invocation síncrona.** `_invoke_tool` chama `tool(**args)`
  bloqueante. Tools async precisam wrapper; fica pra LESSON-010.1 se
  LESSON-007 revelar que algum dos três orquestradores já usa tools
  async.
- **Não há timeout por tool call.** Só timeout global via max_steps.
  Tool que trava trava o run inteiro.

## Correções

### Ações do Sonnet 4.6 no repo (ordem obrigatória)

1. **Criar adaptadores pros ports:**
   - `orch_core/observability/adapters/audit_log_adapter.py` — liga
     `AuditSink` ao `AuditLog` canônico da LESSON-004 (hash chain incluso)
   - `orch_core/observability/adapters/runtime_guard_adapter.py` — liga
     `RuntimeGuard` às 4 camadas da LESSON-003
   - `orch_core/observability/adapters/execution_context_adapter.py` —
     liga `ExecutionContext` à LESSON-002
   - `orch_core/observability/adapters/anthropic_agent_executor.py` —
     implementa `AgentExecutor` sobre o Claude SDK

2. **Dark-launch (CRÍTICO antes do cutover):**
   - Criar `orch_core/execution/shadow.py` com `ShadowRunner` que:
     - Recebe spec
     - Executa canônico (`Runner`) em thread separada
     - Executa legacy (shim do orquestrador antigo) no caller
     - Compara `RunResult` dos dois por hash do audit trail
     - Registra divergência em `run.shadow_divergence`
     - Sempre retorna o resultado do **legacy** (canônico não serve
       tráfego ainda)
   - Rodar 7 dias em produção. Critério de promoção: zero divergências
     bloqueantes.
   - Definir "divergência bloqueante":
     - Hard-fail: `status` diferente (um done, outro failed)
     - Hard-fail: divergência em `tool_name` chamada
     - Soft-fail (log, não bloqueia): divergência em `text` final
       (LLM é não-determinístico)
     - Tolerar: timing

3. **Lint rule no CI:** proibir `from orch_core.execution.runner import`
   fora de `orch_core/adapters/` e `tests/`. Scheduler é choke point
   único (LESSON-011).

4. **Tools async:** se LESSON-007 apontar uso de async, adicionar
   `_invoke_tool_async` em `runner.py` e smoke `test_async_tool_call`.

## Critério de aceite

- 15/15 smokes novos passando
- 22/22 smokes LESSON-008/009 continuam verdes
- 26/26 smokes Wave 1 continuam verdes (total 63)
- CI verde em matrix 3.11/3.12
- Adapters das LESSONS 002/003/004 plugados sem modificar `runner.py`
- Flag `ORCH_USE_CANONICAL_RUNNER` testada em dev antes de ligar em prod
