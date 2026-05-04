# LESSON-009 — Registry unificado

## Contexto

Segunda fase. Consolida em fonte única os lookups de agent e tool que hoje
estão duplicados nos três orquestradores (`master_controller`, `orch_core`
antigo, `orchestrator.py`). Dependência direta: LESSON-008 (contratos).

## Sugerido

- `orch_core/control/registry.py` com classe `Registry` thread-safe
- Escopo de agent sempre por `(tenant_id, agent_id)` — isolation por
  construção, não por cuidado do caller
- Tools por enquanto globais (`name` único); pode virar per-tenant em
  fase futura sem quebrar API
- `default_registry()` como singleton preguiçoso de conveniência,
  **não obrigatório** — caller pode instanciar próprio `Registry()`
- Duplicação rejeitada (falha alto e cedo, não sobrescreve silenciosamente)
- Miss explícito via `AgentNotFound` / `ToolNotFound` (contratos LESSON-008)

## Feito

- `orch_core/control/__init__.py` expondo `Registry`, `default_registry`,
  `reset_default_registry`
- `orch_core/control/registry.py` completo com lock `RLock` interno
- 10 smoke tests cobrindo:
  1. register + get
  2. miss → AgentNotFound
  3. isolation por tenant (mesmo agent_id em tenants diferentes)
  4. duplicação rejeitada
  5. tool lookup
  6. tool miss → ToolNotFound
  7. list_agents escopado por tenant
  8. thread-safety com 50 threads concorrentes
  9. unregister idempotente (bool)
  10. default_registry singleton
- Todos os 10 smokes passam

## Erros

- Tools são globais (não per-tenant). Se algum dos três orquestradores
  atuais tem tool sensível a tenant, a LESSON-007 (pré-diagnóstico) vai
  pegar e aí esta decisão precisa ser revisitada — provavelmente virando
  `register_tool(tool, *, tenant_id: str | None = None)`.
- Thread-safety é garantido por `RLock` simples. Para altíssima
  concorrência de leitura, um `RWLock` seria melhor, mas é otimização
  prematura neste estágio.
- Ainda não integra com shims deprecated dos três orquestradores antigos
  (isso é LESSON-012).

## Correções

1. Na LESSON-012, ao mover os callers dos três orquestradores pro Registry:
   - Cada lookup antigo vira chamada ao `default_registry().get_agent(...)`
   - Emitir `DeprecationWarning` no shim + log estruturado (agent_id,
     caller module) pra mapear quem ainda chama o caminho antigo
2. Se LESSON-007 revelar que algum orquestrador atual permite agent_id
   global sem tenant: adicionar modo de compatibilidade com tenant
   implícito `__legacy__` só pro shim, removido na LESSON-013.

## Critério de aceite

- 10/10 smokes novos passando
- 12/12 smokes da LESSON-008 continuam verdes
- 26/26 smokes Wave 1 continuam verdes (total 48)
- CI verde em matrix 3.11/3.12
