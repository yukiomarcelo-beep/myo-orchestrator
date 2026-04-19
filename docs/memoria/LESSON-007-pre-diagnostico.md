# LESSON-007 — Pré-diagnóstico dos três orquestradores

> **STATUS:** STUB. Preencher no Claude Code (Sonnet 4.6) como
> **primeira ação** antes de tocar em LESSON-010 em diante.
> LESSON-008 e 009 já estão mergeadas e não dependem deste pré-diagnóstico.

## Objetivo

Substituir as hipóteses inferenciais do blueprint pelo mapeamento real das
responsabilidades dos três orquestradores concorrentes. Alimenta as
decisões concretas de LESSON-010 (Runner), 011 (Scheduler), 012 (Adapters).

## Entregáveis obrigatórios

### 1. Tabela de responsabilidades reais

Para cada um dos três (`master_controller`, `orch_core` antigo,
`orchestrator.py`), listar:

| Orquestrador | Responsabilidades ÚNICAS | Responsabilidades SOBREPOSTAS | Integrações externas |
|--------------|-------------------------|-------------------------------|---------------------|
| master_controller | ... | ... | ... |
| orch_core (antigo) | ... | ... | ... |
| orchestrator.py | ... | ... | ... |

### 2. Matriz de sobreposição

Para cada capacidade listada abaixo, marcar qual(is) dos três implementa:

- [ ] Resolução de agent por id/role
- [ ] Resolução de tool por nome
- [ ] Loop de `while tool_use`
- [ ] Montagem de `messages[]` / contexto
- [ ] Retry de tool call
- [ ] Timeout
- [ ] Cancelamento
- [ ] Logging / telemetria (e ONDE grava — alinhado com AuditLog LESSON-004?)
- [ ] Gestão de `run_id` / `session_id`
- [ ] Persistência de estado (PostgreSQL direto?)
- [ ] Streaming / SSE
- [ ] HTTP endpoints do War Room
- [ ] Rate limit / throttling
- [ ] Error classification

### 3. Grafo de dependências

```
# Rodar no repo:
grep -r "from master_controller" --include="*.py" | sort -u
grep -r "from orch_core" --include="*.py" | sort -u
grep -r "from orchestrator" --include="*.py" | sort -u
grep -r "import orchestrator" --include="*.py" | sort -u
```

Documentar:
- Lista completa de callers de cada orquestrador
- Existe dependência circular entre os três? (crítico pra ordenação das
  próximas LESSONS)
- Qual o orquestrador com mais callers? (prioridade do shim na LESSON-012)

### 4. Integração com LESSONS anteriores

- Os três usam `ExecutionContext` (LESSON-002)? Se não, quais montam
  contexto próprio?
- Os três escrevem no `AuditLog` canônico (LESSON-004)? Se não, onde
  escrevem?
- Os três respeitam `runtime_guard` (LESSON-003)? Se não, qual bypassa?
- Os três usam `policy_adapter` (LESSON-006)?

### 5. Decisões concretas que destravam LESSON-010+

- [ ] Qual dos três tem o loop de `tool_use` mais completo? (base do
      Runner canônico)
- [ ] Qual gerencia streaming/SSE? (alvo do adapter `war_room.py`)
- [ ] Qual tem persistência em PostgreSQL? (alvo do adapter `master.py`)
- [ ] Existe tool sensível a tenant hoje? (decide se Registry precisa de
      tools per-tenant)
- [ ] Existe feature flag no repo (infra de env vars ou similar) ou
      precisa introduzir?

## Critério de conclusão

Documento preenchido + commit `docs: LESSON-007 pre-diagnostico`.
**Não mexer em código de produção nesta LESSON.** Só leitura e documentação.

## Após completar

Revisar premissas de LESSON-010/011/012 neste repo e ajustar se alguma
hipótese do blueprint original caiu.
