# LESSON-008 — Contratos canonicos do orch_core

## Contexto

Primeira fase construtiva da unificação dos três orquestradores concorrentes
(`master_controller`, `orch_core` antigo, `orchestrator.py`). Estabelece a
fonte única de verdade dos tipos que atravessam o sistema.

Pré-requisito de toda LESSON subsequente (009 Registry, 010 Runner,
011 Scheduler, 012 Adapters, 013 Remoção de shims).

## Sugerido

Fonte única em `orch_core/contracts.py` com:

- `Run` — dataclass frozen, identidade imutável de execução
- `Step` — passo dentro de um Run
- `Event` — evento observável
- `RunStatus` — Literal fechado (`pending|running|done|failed|cancelled`)
- `VALID_TRANSITIONS` — máquina de estados explícita
- `Agent`, `Tool` — Protocols
- `RunSpec` — TypedDict pra Scheduler.submit()
- Exceções canônicas: `OrchError`, `AgentNotFound`, `ToolNotFound`,
  `InvalidTransition`, `TenantIsolationViolation`
- Helpers: `new_run()`, `replace_run()`, `is_valid_transition()`

Invariantes:
- `tenant_id` obrigatório desde o dia um
- `run_id` sempre UUID
- `parent_run_id` existe desde já (sub-runs no futuro)
- Imutabilidade por construção

## Feito

- `orch_core/__init__.py` com API pública explícita
- `orch_core/contracts.py` completo
- 12 smoke tests cobrindo construção, validação de campos obrigatórios,
  tipagem de UUID, máquina de estados, imutabilidade, serialização
  round-trip, factory, rejeição de status inválido
- Todos os 12 smokes passam
- CI configurado em matrix Python 3.11/3.12 via `.github/workflows/smoke.yml`

## Erros

- Compatibilidade com `ExecutionContext` (LESSON-002) e `AuditLog`
  (LESSON-004) ainda não testada — os smokes de integração estão marcados
  como TODO no arquivo de teste. Razão: arquitetura desenhada sem acesso
  ao código canônico dessas lessons anteriores.
- `metadata` do `Run` é `Mapping[str, Any]`, não tipado em profundidade.
  Suficiente pro MVP; pode precisar endurecer depois.

## Correções

1. Primeira ação do Sonnet 4.6 na integração:
   - Adicionar 2 smokes de integração em `test_lesson_008_contracts.py`:
     - `test_run_compatible_with_execution_context` — construir `Run`,
       passar pro `ExecutionContext`, garantir que tenant_id/run_id
       propagam.
     - `test_run_roundtrip_via_audit_log` — persistir via AuditLog,
       ler de volta, comparar.
2. Se `ExecutionContext` da LESSON-002 já tem noção própria de
   `run_id`/`tenant_id`, alinhar nomenclatura. Se conflitar, `contracts.py`
   é a fonte canônica — a LESSON-002 vira re-export/adapter.

## Critério de aceite

- 12/12 smokes novos passando
- 26/26 smokes anteriores (Wave 1) continuam verdes
- CI verde em matrix 3.11/3.12
