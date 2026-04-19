# LESSON-013 — Remoção dos três orquestradores legados

> **STATUS:** PLAYBOOK, não código. A remoção é operacional — depende
> de dados reais de produção (contador de callers do
> `DeprecationRegistry`), não de implementação nova.

## Contexto

Última LESSON da Wave 2. Fecha a unificação. A partir daqui, o repo tem
**um só orquestrador**: `orch_core`, acessado exclusivamente via
`Scheduler`.

## Pré-requisitos (todos obrigatórios)

1. LESSONs 008–012 mergeadas em `main`
2. Dark-launch do Runner (LESSON-010) completado com promoção
3. Todos os callers de `orchestrator.py`, `master_controller` e
   `orch_core` antigo passando pelos shims
4. Lint rule CI proibindo imports legados ativa e verde
5. Exportação periódica do `DeprecationRegistry` pra AuditLog rodando
   em produção

## Critério de início da remoção

**`DeprecationRegistry.snapshot()` retornando contador zero por 7 dias
corridos em produção, para cada um dos três shims.**

Consulta de validação:

```python
from orch_core.adapters import default_deprecation_registry

reg = default_deprecation_registry()
snap = reg.snapshot()

for shim in (
    "orchestrator.py (legacy).run_agent",
    "orchestrator.py (legacy).execute",
    "master_controller (legacy).start_session",
    "master_controller (legacy).send_message",
    "master_controller (legacy).end_session",
    "master_controller (legacy).get_session_status",
):
    total = sum(v for (s, _), v in snap.items() if s == shim)
    print(f"{shim}: {total}")
```

Se qualquer linha for não-zero: **não remover**. Investigar quem ainda
chama via `reg.traces()` e migrar o caller antes.

## Sequência da remoção

### Fase 1 — Remover os arquivos originais

```bash
git checkout -b chore/lesson-013-remove-legacy-orchestrators

# Os três arquivos/módulos originais
git rm orchestrator.py
git rm -r master_controller/
git rm -r orch_core_legacy/  # o antigo, renomeado na integração LESSON-008
```

### Fase 2 — Remover os shims

```bash
git rm orch_core/adapters/legacy.py
git rm orch_core/adapters/master.py
```

Mantém `war_room.py` (não é shim, é adapter canônico), `asyncio_adapter.py`,
`deprecation.py` (pode ser útil no futuro pra outras migrações).

### Fase 3 — Remover testes dos shims

```bash
# Deletar smokes específicos dos shims; manter smokes do WarRoomAdapter
# (adapter canônico) e do async_stream
```

Ajustar `test_lesson_012_adapters.py` pra manter só os testes de:
- `WarRoomAdapter` (6 casos ainda relevantes)
- `async_stream` / `async_stream_sse` (1 caso)
- `deprecation` infra (se for mantida pra outras migrações)

### Fase 4 — Atualizar lint rules

Remover as regras que proibiam imports legados (agora os módulos nem
existem mais). Adicionar regra permanente:

> **Runner só pode ser importado por:** `orch_core.control.scheduler`,
> `orch_core.adapters.*`, `tests/`. Todo outro caller passa pelo
> Scheduler.

### Fase 5 — Atualizar docs

1. Em `docs/memoria/LESSON-013-fechamento-unificacao.md` (este arquivo,
   renomeado): substituir "STATUS: PLAYBOOK" por "STATUS: EXECUTADO em
   YYYY-MM-DD"
2. Listar contadores finais do `DeprecationRegistry` no momento da
   remoção (deve ser tudo zero)
3. Atualizar README principal do MYO: a arquitetura oficial é
   `orch_core` via `Scheduler`

## Smoke de fechamento (≥8 casos)

Os smokes abaixo devem ser adicionados em `tests/smoke/test_lesson_013_closure.py`
e rodar no CI final:

1. `from orchestrator import *` levanta `ImportError` (módulo removido)
2. `from master_controller import *` levanta `ImportError`
3. `from orch_core_legacy import *` levanta `ImportError`
4. `from orch_core.adapters.legacy import *` levanta `ImportError`
5. `from orch_core.adapters.master import *` levanta `ImportError`
6. `Scheduler` importável via `orch_core.control.scheduler`
7. 63 smokes anteriores continuam verdes (exceto os shims removidos)
8. CI matrix 3.11/3.12 verde

## Rollback

Se algo quebrar após a remoção:

```bash
git revert <sha-da-remoção>
git push origin main
```

Os módulos voltam. Os shims voltam. O `DeprecationRegistry` volta a
coletar dados. Investiga-se quem quebrou e corrige.

Por isso a Fase 1 é `git rm` em commits separados por módulo — facilita
revert cirúrgico.

## Critério de aceite

- Três arquivos/módulos legados removidos do repo
- Dois shims removidos
- Smokes de fechamento (≥8) passando
- CI verde em matrix 3.11/3.12
- `grep -r "from orchestrator\|import orchestrator\|from master_controller\|import master_controller" --include="*.py"` retorna vazio
- README principal do MYO atualizado com a arquitetura canônica final
- PR mergeado em `main` com label `closes: orch-unificacao`

## Pós-LESSON-013

A Wave 2 fecha aqui. Próximos passos lógicos (**fora do escopo da
unificação**):

- **Wave 3:** persistência de `SessionStore` em PostgreSQL
- **Wave 3:** EventBus distribuído (Redis Pub/Sub) substituindo
  InMemoryEventBus sem mudar API
- **Wave 3:** cockpit unificado consumindo `Scheduler.stream()` via
  WebSocket
- **Wave 3:** LESSON-014 de sessões conversacionais persistentes, se
  necessário

Tudo isso se conecta ao `Scheduler` sem tocar em nenhuma LESSON da
Wave 2 — é o resultado do contrato ter sido desenhado certo desde a
LESSON-008.
