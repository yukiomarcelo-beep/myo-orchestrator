# LESSON-007 — Pré-diagnóstico dos três orquestradores

> **STATUS:** COMPLETO — preenchido em 2026-04-19 (Sonnet 4.6, wave2 FASE 1)

## Objetivo

Substituir as hipóteses inferenciais do blueprint pelo mapeamento real das
responsabilidades dos três orquestradores concorrentes. Alimenta as
decisões concretas de LESSON-010 (Runner), 011 (Scheduler), 012 (Adapters).

---

## 1. Tabela de responsabilidades reais

| Orquestrador | Responsabilidades ÚNICAS | Responsabilidades SOBREPOSTAS | Integrações externas |
|---|---|---|---|
| `core/master_controller.py` | Pipeline 11-nós (01→11), 3 modos (auto/semi_auto/manual), memória de sessão (outputs/memory_items.json), checkpoint por nó, context-load de outputs anteriores, node_10_learn (geração de insights via Claude) | Chamada ao Claude (httpx direto), persistência JSON, orquestração de engines (product/content/video/sales) | `core/security_bridge.py` (guard_input, record_cost), `engines/*.py` (product, content, video, sales), `opportunity_scorer` |
| `core/orch_core.py` (antigo) | Debate GPT×Claude multi-round (propose→critique→refine), scoring ponderado 8 dimensões, regras de rejeição automáticas, confiança baseada em verdicts, **SYNC** (não async) | Chamada ao Claude e GPT (via llm_router), scoring, persistência JSON | `agents/llm_router.py`, `observability.py` (tracker/tracer) |
| `core/orchestrator.py` | Detecção de rota (ROUTE_MAP 9 rotas), gate check via SecureOrchestrator, integração Notion (salvar_tarefa) | Chamada ao Claude/GPT/Perplexity (httpx direto), persistência JSON local | `security_layer.SecureOrchestrator`, `integrations/notion_logger.py`, `engines/*.py` |

---

## 2. Matriz de sobreposição

| Capacidade | master_controller | orch_core (antigo) | orchestrator.py |
|---|:---:|:---:|:---:|
| Resolução de agent por id/role | ❌ engines por nome hardcoded | ❌ providers (GPT/Claude) fixos | ❌ ROUTE_MAP hardcoded |
| Resolução de tool por nome | ❌ | ❌ | ❌ |
| Loop de `tool_use` | ❌ loop de nós (01→11), não tool_use | ✅ loop debate rounds | ❌ single-shot por rota |
| Montagem de `messages[]` | ✅ via `_claude(prompt)` | ✅ via providers | ✅ via httpx direto |
| Retry de tool call | ❌ | ❌ | ❌ |
| Timeout | ✅ httpx timeout=90 | ✅ httpx timeout indireto via llm_router | ✅ httpx timeout 60-90 |
| Cancelamento | ❌ só via KeyboardInterrupt | ❌ | ❌ |
| Logging / telemetria | ✅ JSON por sessão em outputs/sessions/ | ✅ tracker/tracer (observability.py) | ✅ AuditLog via SecureOrchestrator |
| Gestão de run_id / session_id | ✅ session_id = timestamp | ✅ run_id = uuid4().hex[:8] | ✅ session via SecureOrchestrator |
| Persistência de estado (PG) | ❌ JSON local | ❌ JSON local | ❌ JSON local |
| Streaming / SSE | ❌ | ❌ | ❌ |
| HTTP endpoints / War Room | ❌ CLI only | ❌ CLI only (importável) | ❌ CLI only |
| Rate limit / throttling | ✅ via security_bridge.record_cost (emergency_stop) | ❌ | ❌ |
| Error classification | ❌ except genérico | ❌ | ❌ parcial (HTTPStatusError) |

**Nota crítica:** Nenhum dos três tem SSE, HTTP endpoints ou tool_use no sentido do Runner canônico. SSE está em `api/myo_server.py` (FastAPI), fora dos orquestradores.

---

## 3. Grafo de dependências

### Callers Python reais (grep no repo, excluindo venv e worktrees)

| Orquestrador | Callers Python | Tipo de uso |
|---|---|---|
| `core/orchestrator.py` | **0 callers** (somente CLI própria) | CLI standalone |
| `core/master_controller.py` | **0 callers** (somente CLI própria) | CLI standalone |
| `core/orch_core.py` | **1 caller**: `engines/opportunity_pipeline.py` | Importado como módulo |

```
engines/opportunity_pipeline.py:43:
    from core.orch_core import (Orchestrator, TrendSignal, OpportunityDecision, ...)
    # usa: Orchestrator().process_signal(signal, debate_rounds=N) — SYNC
```

**Dependência circular:** NÃO existe.

**Prioridade de shim:** `orch_core` (antigo) é o único com caller Python real. Os outros dois são CLIs sem importadores.

---

## 4. Integração com LESSONs anteriores

| LESSON | orchestrator.py | master_controller.py | orch_core.py (antigo) |
|---|---|---|---|
| LESSON-002 (ExecutionContext) | ❌ contexto ad-hoc no `orquestrar()` | ❌ contexto via `Session.state` dict próprio | ❌ sem contexto formal |
| LESSON-003 (runtime_guard) | ✅ parcial via `SecureOrchestrator._gate_check()` (não usa runtime_guard canônico) | ✅ parcial via `security_bridge.guard_input()` | ❌ sem guarda |
| LESSON-004 (AuditLog) | ✅ parcial via `SecureOrchestrator.audit.record()` (não AuditLog canônico diretamente) | ❌ sem audit | ❌ sem audit (só tracker/tracer) |
| LESSON-005 (policy_adapter) | ❌ | ❌ | ❌ |
| LESSON-006 (verification_logger) | ❌ | ❌ | ❌ |

**Conclusão:** Nenhum dos três está integrado com os canônicos das LESSONs 002-006. Todos têm implementações proprietárias de runtime guard e audit. A FASE 2 (adapters de ports) vai criar a ponte — mas por agora não há nada a "migrar" em termos de código dos orquestradores; a integração será feita nos adapters do orch_core canônico.

---

## 5. Decisões concretas que destravam LESSON-010+

| Questão | Resposta | Impacto |
|---|---|---|
| Qual tem o loop de tool_use mais completo? | **orch_core.py** — loop de debate rounds com propose→critique→refine. Não é tool_use no sentido do Runner, mas é o loop iterativo mais sofisticado. | Base conceitual do Runner canônico (LESSON-010) |
| Qual gerencia SSE / streaming? | **Nenhum** — SSE está em `api/myo_server.py` (FastAPI), não nos orquestradores. | war_room adapter (LESSON-012) precisa ir buscar em myo_server.py, não em nenhum dos 3 |
| Qual tem persistência em PostgreSQL? | **Nenhum** — todos usam JSON local. | Adapters de persistência PG pertencem a Wave 3, não Wave 2 |
| Existe tool sensível a tenant? | **Não** — nenhum dos 3 tem conceito de tenant. O tenant é um conceito novo introduzido pelo orch_core canônico. | Registry não precisa tools per-tenant hoje; introduzir na Wave 3 se necessário |
| Existe feature flag infrastructure? | **Não** no legado — apenas env vars ad-hoc. O novo `orch_core/execution/feature_flags.py` (do ZIP) introduz a infra. | Usar `feature_flags.py` do pacote canônico; não retroagir no legado |

---

## 6. Análise dos shims vs realidade

### LegacyOrchestratorShim (`orch_core/adapters/legacy.py`)

**API assumida pelo shim:** `run_agent(agent_id, input)`, `execute(agent_name, messages)`

**API real do `core/orchestrator.py`:** `orquestrar(input_text, task_type, confidence)` — função async, sem run_agent nem execute.

**Veredicto:** As assinaturas assumidas **não existem** no legado. Porém, como há **0 callers Python** que importam `core/orchestrator.py`, **não há assinaturas a reconciliar**. O shim está correto como contrato hipotético de migração futura. **Sem ajuste necessário.**

### MasterControllerShim (`orch_core/adapters/master.py`)

**API assumida:** `start_session`, `send_message`, `end_session`, `get_session_status`

**API real do `core/master_controller.py`:** `run_session(objective, market, mode, session_id)` — pipeline 11-nós, sem API conversacional.

**Veredicto:** O master_controller real não expõe sessão conversacional (start/send/end). Há **0 callers Python** que o importam. O shim modela uma API hipotética de sessão que o legado nunca teve. `send_message` levanta `NotImplementedError` (correto — o canônico é stateless). **Sem ajuste necessário.**

**Nota arquitetural preservada:** Se o `send_message` for necessário no futuro, requer LESSON-014 (sessões conversacionais persistentes com PG SessionStore), conforme anotado no cabeçalho do shim.

---

## 7. Descobertas que contradizem o blueprint original

1. **Os 3 orquestradores são CLIs standalone** — nenhum tem API pública de importação exceto `orch_core.py` (antigo). A "migração de callers" da FASE 4 tem apenas 1 alvo real: `engines/opportunity_pipeline.py`.

2. **Nenhum usa PG** — o blueprint assumia que `master_controller` persistia em PostgreSQL. Persistência é toda em JSON local. Wave 3 é necessária para introduzir isso.

3. **SSE não é nos orquestradores** — está em `api/myo_server.py`. O `WarRoomAdapter` da LESSON-012 vai apontar para lá, não para os orquestradores.

4. **0 callers precisam de migração urgente** — a FASE 4 (migração de callers) é muito menor do que o blueprint previa: apenas 1 arquivo (`opportunity_pipeline.py`).

---

## Critério de conclusão

✅ Documento preenchido. Commit: `docs(wave2): LESSON-007 pre-diagnostico`.

## Impacto nas próximas LESSONS

- **LESSON-010 (Runner):** usar orch_core.py antigo como referência do loop iterativo (debate rounds → tool_use rounds)
- **LESSON-011 (Scheduler):** nenhum legado tem Scheduler; introdução limpa
- **LESSON-012 (Adapters):** shims corretos como estão; ajustar apenas `_result_to_legacy_shape` se `opportunity_pipeline.py` esperar shape diferente
- **FASE 2 (ports adapters):** AuditSink → bridge para `core/audit_log.py` (LESSON-004); RuntimeGuard → `policies/runtime_guard.py` (LESSON-003)
