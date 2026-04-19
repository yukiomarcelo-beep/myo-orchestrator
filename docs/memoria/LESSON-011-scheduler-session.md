# LESSON-011 — Scheduler + Session

## Contexto

Amarra o Runner canônico num ponto único de entrada. Habilita
paralelismo real, tenant quotas, cancelamento cooperativo, e streaming
de eventos por run_id. Pré-requisito pra cockpit unificado e pra
adapter do War Room (LESSON-012).

Dependências diretas: LESSON-008 (contratos), LESSON-009 (Registry),
LESSON-010 (Runner).

## Sugerido

### Arquitetura

- **Scheduler é choke point único.** Nenhum caller externo instancia
  `Runner` direto — lint rule no CI (a adicionar na LESSON-012).
- **Session store** guarda estado in-flight + histórico, thread-safe.
  Hoje em memória; adapter PostgreSQL é LESSON-011.1 se precisar
  sobreviver a restart.
- **EventBus in-memory** com fan-out por `run_id` e backlog (subscriber
  que chega tarde não perde `run.created`).
- **Concorrência:** `ThreadPoolExecutor` single-process + semáforo por
  tenant via `tenant_quotas`. API pública não muda quando trocarmos
  pra pool distribuído (Redis/dramatiq).
- **Dedup de eventos via `event_id`.** Backlog vs live não duplica.

### Refatoração no Runner (mudança importante)

A API primária do Runner agora é `execute_run(run, input_payload, is_cancelled)`.
O `execute(spec)` ficou como conveniência. Motivo: o Scheduler precisa
preservar o `run_id` que ele gerou no `submit()` — delegar pro Runner
gerar outro forçava reconciliação feia no store. Com `execute_run`, o
Scheduler passa o `Run` já materializado.

Isso também clarifica a divisão: **quem gera run_id é quem submete**,
não quem executa.

### API pública do Scheduler

```python
submit(spec: RunSpec) -> UUID                    # não-bloqueante
status(run_id, *, tenant_id=None) -> Run         # snapshot
cancel(run_id, *, tenant_id=None) -> bool        # cooperativo
stream(run_id, *, tenant_id=None, timeout=None)  # Iterator[Event]
result(run_id, *, tenant_id=None, timeout=None)  # RunResult (bloqueia)
list_runs(tenant_id, *, project_id=None, status=None) -> list[Run]
close(*, wait=True) -> None
```

### Arquivos

- `orch_core/control/session.py` — `SessionStore`, `SessionEntry`, `RunNotFound`
- `orch_core/control/scheduler.py` — `Scheduler`, `SchedulerError`
- `orch_core/observability/event_bus.py` — `InMemoryEventBus` (implementa `EventSink`)
- `orch_core/execution/runner.py` — **modificado:** nova API `execute_run`
- `orch_core/control/__init__.py` e `orch_core/observability/__init__.py` — atualizados

## Feito

- 3 módulos novos (~400 linhas produção)
- Refatoração cirúrgica no Runner: `execute_run` como API primária,
  `execute(spec)` como wrapper fino que delega. Os 15 smokes da
  LESSON-010 continuam verdes sem modificação.
- 12 smoke tests cobrindo:
  1. submit não-bloqueante
  2. transições de status
  3. cancel em running
  4. cancel em done é no-op
  5. stream em ordem canônica
  6. 10 runs concorrentes isolados
  7. tenant isolation no status
  8. tenant isolation no stream
  9. list_runs com filtros
  10. parent_run_id propaga via submit
  11. result bloqueia até done
  12. close fecha pool e bloqueia submits
- **49/49 smokes passam** (12+10+15+12)

## Erros

- **Session store em memória.** Restart de processo perde histórico de
  runs finalizados. Pra produção: adapter sobre `AuditLog` (LESSON-004)
  como fonte de verdade persistente.
- **Quota por tenant é semáforo simples.** Não há noção de prioridade
  (runs críticos vs batch). Se precisar, adicionar `PriorityQueue` no
  lugar do `ThreadPoolExecutor` default.
- **Cancelamento é cooperativo.** Se uma tool bloquear I/O síncrono
  dentro do Runner, o cancel só surte efeito depois que a tool volta.
  Não dá pra interromper tool sem timeout próprio.
- **`close(wait=True)` pode travar indefinidamente** se houver run
  travado. Produção deve usar `wait=False` + monitoring externo.
- **Stream bloqueante.** `Iterator[Event]` síncrono não combina com
  HTTP async (FastAPI, etc). LESSON-012 precisa expor `async_stream`
  via adapter.

## Correções (pro Sonnet 4.6)

1. **Lint rule no CI (obrigatória):** proibir `from orch_core.execution.runner import Runner` fora de:
   - `orch_core/control/scheduler.py`
   - `orch_core/adapters/*`
   - `tests/`

   Qualquer outro import de `Runner` é code smell — deve usar `Scheduler`.

2. **Adapter async pro stream:** em `orch_core/adapters/asyncio.py`:
   ```python
   async def async_stream(scheduler, run_id, **kwargs):
       loop = asyncio.get_event_loop()
       it = scheduler.stream(run_id, **kwargs)
       while True:
           ev = await loop.run_in_executor(None, next, it, None)
           if ev is None:
               return
           yield ev
   ```

3. **Adapter PostgreSQL pro SessionStore** (se LESSON-007 mostrar que
   o `master_controller` persiste sessão em PG — provavelmente sim).
   Implementar em `orch_core/control/session_postgres.py` como drop-in
   replacement de `SessionStore`.

4. **Validação de `tenant_quotas` no `__init__`:** quota <= 0 deve
   levantar `SchedulerError`. Hoje aceita silenciosamente.

5. **Smoke de integração:** submit 100 runs com `tenant_quotas={"t1": 2}`,
   verificar que nunca há mais que 2 runs de t1 em `running` ao mesmo tempo.
   Não foi adicionado neste pacote porque exige timing sensível que é
   flaky em CI gratuito — melhor rodar no Claude Code com observabilidade.

## Critério de aceite

- 12/12 smokes novos passando
- 37/37 smokes anteriores continuam verdes (total 49)
- 26/26 smokes Wave 1 continuam verdes (total 75)
- CI verde em matrix 3.11/3.12
- Lint rule de choke point ativa e verificada
