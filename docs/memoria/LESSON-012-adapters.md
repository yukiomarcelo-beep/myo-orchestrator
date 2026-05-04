# LESSON-012 — Adapters legados

## Contexto

Última LESSON que escreve código novo na Wave 2. Cria shims que
redirecionam os três orquestradores antigos pro `Scheduler` canônico
com `DeprecationWarning` + log estruturado — essa instrumentação é o
que destrava a LESSON-013 (remoção segura).

Dependências diretas: LESSON-008/009/010/011 completas.

## Sugerido

### Princípio dos shims

1. **Interface antiga preservada ao máximo.** Caller não percebe a
   troca, só vê warning.
2. **Nenhuma lógica de negócio nos shims.** Apenas tradução de shape +
   delegação pro Scheduler.
3. **Todo shim emite `DeprecationWarning` + log estruturado.** Sem
   exceção.
4. **`ORCH_DEPRECATION_SILENT=1` silencia apenas o warning**, não o log.
   Flag existe pra operação em produção durante janela de observação;
   NÃO usar em dev.

### Arquivos

- `orch_core/adapters/deprecation.py` — infra comum:
  `emit_deprecation()`, `DeprecationRegistry` (contador de callers),
  `deprecated_shim` decorator, `CallerTrace`
- `orch_core/adapters/legacy.py` — `LegacyOrchestratorShim` (ex-`orchestrator.py`)
  com `run_agent()`, `execute()`
- `orch_core/adapters/master.py` — `MasterControllerShim` (ex-`master_controller`)
  com `start_session()`, `end_session()`, `get_session_status()`.
  `send_message()` levanta `NotImplementedError` explícito — vide
  "Migração de sessões multi-turno" abaixo
- `orch_core/adapters/war_room.py` — `WarRoomAdapter` com
  `handle_submit`, `handle_status`, `handle_cancel`, `handle_list`,
  `stream_sse` + helper `format_sse_event`
- `orch_core/adapters/asyncio_adapter.py` — `async_stream`,
  `async_stream_sse` pra FastAPI sem acoplar o core

### Contrato operacional

O operador consulta em produção:

```python
from orch_core.adapters import default_deprecation_registry
reg = default_deprecation_registry()
for (shim, caller_module), count in sorted(
    reg.snapshot().items(), key=lambda x: -x[1]
):
    print(f"{count:>5}  {shim}  <-  {caller_module}")
```

Saída típica durante transição:

```
  1820  orchestrator.py.run_agent  <-  war_room.handlers
   340  master_controller.start_session  <-  analytics.worker
    12  orchestrator.py.execute  <-  scripts.adhoc.scrape
```

Isso alimenta o roadmap de migração dos callers pelo próprio repo.

### Migração de sessões multi-turno

`master_controller.send_message` não tem equivalente 1:1 no Scheduler
stateless. **Decisão arquitetural:** quebrar explicitamente com
`NotImplementedError` e forçar migração pro padrão canônico (submeter
novo Run com histórico no `input`).

Se LESSON-007 revelar uso alto de `send_message`, há duas saídas:

1. **Aceitar o break** (caso uso seja <20%) e migrar os callers pra
   padrão canônico manualmente.
2. **LESSON-014 (nova):** sessão conversacional persistente como
   primitiva separada (`ConversationStore`). Independente do Scheduler
   — caller monta histórico e submete Run a cada turno.

Recomendação: opção 1, a menos que o volume força opção 2.

## Feito

- 5 módulos novos (~500 linhas produção)
- 14 smoke tests cobrindo:
  1. `DeprecationWarning` emitido
  2. `DeprecationRegistry` conta callers corretamente
  3. `ORCH_DEPRECATION_SILENT` silencia warning mas não log
  4. `LegacyOrchestratorShim.run_agent` delega e retorna shape legado
  5. `LegacyOrchestratorShim.execute` extrai última mensagem user
  6. `MasterControllerShim.start_session` retorna session_id string
  7. `MasterControllerShim.send_message` levanta `NotImplementedError`
  8. `MasterControllerShim.end_session` cancela via Scheduler
  9. `MasterControllerShim.get_session_status` funciona
  10. `WarRoomAdapter.handle_submit` valida campos obrigatórios
  11. `WarRoomAdapter.handle_status` respeita tenant isolation
  12. `WarRoomAdapter.stream_sse` formata chunks SSE válidos
  13. `format_sse_event` produz chunk parseável
  14. `async_stream` entrega eventos em AsyncIterator
- **63/63 smokes passam** (12+10+15+12+14), zero warnings

## Erros

- **Assinaturas dos shims são assumidas.** `run_agent`, `execute`,
  `start_session` etc. refletem o que é *típico* em código desses três
  orquestradores, não o código real do repo MYO. LESSON-007 + ajuste
  cirúrgico dos shims pelo Sonnet antes de habilitar em produção.
- **Shape de resposta legado pode divergir.** `_result_to_legacy_shape`
  retorna `{run_id, status, output, error, tenant_id, agent_id}`. Se o
  `orchestrator.py` original retornava chaves diferentes (ex.: `id`,
  `result`, `agent`), callers quebram. Testar contra callers reais
  antes do cutover.
- **`WarRoomAdapter` não trata autenticação.** Tenant isolation funciona
  se o caller passar `tenant_id` corretamente. Extrair tenant de JWT /
  header HTTP é responsabilidade do framework HTTP, não do adapter.
- **`async_stream` usa `run_in_executor` default.** Se o Scheduler
  tiver muitos streams abertos, o pool default do asyncio pode esgotar.
  Produção deve passar executor dedicado.

## Correções (pro Sonnet 4.6 no repo)

1. **Validar assinaturas reais** na LESSON-007 e ajustar shims antes
   de mergear. Procurar especificamente por:
   - `orchestrator.run_agent` vs `orchestrator.execute_agent` vs outros
   - `master_controller.start_session` vs `.create_conversation` etc.
   - Shape de retorno (chaves específicas)
2. **Lint rule no CI** proibir import direto de:
   - `orchestrator` (módulo antigo)
   - `master_controller` (módulo antigo)

   Callers precisam passar pelos shims em `orch_core.adapters`. Dois
   warnings no review do PR aposentam a regra antiga.

3. **Exportar snapshot periódico** do `DeprecationRegistry` pro AuditLog
   (LESSON-004) — cria trilha persistente pra LESSON-013.

4. **Adicionar smoke de integração com FastAPI real:** se o War Room
   usa FastAPI, testar endpoint real com StreamingResponse consumindo
   `async_stream_sse`. Ficou fora daqui por não termos o framework
   instalado no sandbox.

5. **Se LESSON-007 revelar autenticação acoplada** em algum dos três
   orquestradores (JWT parsing, sessão de usuário etc.), extrair pra
   middleware separado. Adapters não lidam com auth.

## Critério de aceite

- 14/14 smokes novos passando
- 49/49 smokes anteriores continuam verdes (total 63)
- 26/26 smokes Wave 1 continuam verdes (total 89 no repo)
- CI verde em matrix 3.11/3.12
- Lint rule proibindo imports legados ativa
- `default_deprecation_registry()` sendo consultado periodicamente em
  produção (cron/script de observabilidade)
