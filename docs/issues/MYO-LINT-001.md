# MYO-LINT-001 — 185 violações ruff em 30 arquivos legados

**Status:** ABERTO
**Aberto em:** 2026-04-28
**Bloqueador de:** FASE 6 (closure do wave2 / remoção de shims legados)
**Prioridade:** F701/F704/F706 primeiro — suspeita de bug real de produção

---

## Contexto

Ao ativar o ruff lint como pre-commit hook (commit A da Choke Point),
os 30 arquivos abaixo acumularam violations pré-existentes que não
foram fixadas antes da configuração do hook.

O `ruff.toml` está limpo (sem `per-file-ignores`). O pre-commit exclui
esses 30 arquivos temporariamente via `.pre-commit-config.yaml` com
pointer explícito a este issue — isso é sinal de débito visível,
não silenciamento global.

---

## Tabela de violações por arquivo

| Violações | Arquivo | Regras |
|----------:|---------|--------|
| 80 | `utils/trust_aggregator.py` | F701, F706, F821, F841 |
| 22 | `scripts/generate_dashboard.py` | E722, E741, F841 |
| 11 | `engines/crm_engine.py` | E741, F841 |
| 9 | `engines/self_healing_engine.py` | F706, F821, F841 |
| 8 | `engines/pricing_engine.py` | F821, F841 |
| 6 | `engines/dashboard_engine.py` | E741, F841 |
| 6 | `observability.py` | E722 |
| 5 | `engines/kaizen_engine.py` | E402 |
| 5 | `engines/opportunity_pipeline.py` | E402 |
| 3 | `core/execution_control.py` | E402 |
| 3 | `core/myo_cli.py` | F701, F704 |
| 3 | `main.py` | E402 |
| 3 | `security_layer.py` | E402 |
| 2 | `engines/ads_engine.py` | F841 |
| 2 | `engines/content_engine.py` | E722 |
| 2 | `tests/smoke/test_orchestrator_canonical.py` | E741 |
| 2 | `utils/trust_feedback_engine.py` | F821, F841 |
| 1 | `agents/claude_runner.py` | E402 |
| 1 | `agents/claude_runner_v2.py` | F401 |
| 1 | `api/telegram_command_router.py` | F841 |
| 1 | `engines/financial_engine.py` | F841 |
| 1 | `engines/product_engine.py` | F841 |
| 1 | `engines/scaling_engine.py` | F841 |
| 1 | `engines/sofia_monitor_engine.py` | E741 |
| 1 | `engines/unit_economics_engine.py` | F841 |
| 1 | `integrations/telegram_bot.py` | F841 |
| 1 | `nexara_juridico/orquestrador.py` | E741 |
| 1 | `scripts/build_pitch.py` | E741 |
| 1 | `tests/smoke/test_shadow_runner.py` | F841 |
| 1 | `utils/result_ingestor.py` | E402 |

**Total: 185 violações em 30 arquivos**

---

## Categorias e esforço estimado

### F701 / F704 / F706 — Sintaxe estrutural quebrada (91 ocorrências)
**PRIORIDADE ALTA — possível bug de produção**

Arquivos afetados:
- `utils/trust_aggregator.py` (80 violações — F701, F706)
- `utils/trust_feedback_engine.py` (F821 — provável decorrência)
- `core/myo_cli.py` (3 — F701, F704)
- `engines/self_healing_engine.py` (9 — F706, F821)

Suspeita: padrão de indentação 1-espaço causando `break`/`return`/`continue`
fora de loop/função — igual ao bug do `result_ingestor.py` identificado
na LESSON-002 do wave2.

**Próximo passo:** investigar `utils/trust_aggregator.py` (head -50 + grep
por F706/F701 com contexto de indentação). NÃO reescrever sem confirmação
do owner.

Esforço estimado: **investigação 2-4h** (pode ser rewrite parcial se
confirmar bug estrutural)

---

### F841 — Variável local atribuída mas nunca usada (37 ocorrências)

Arquivos: crm_engine, dashboard_engine, generate_dashboard, pricing_engine,
self_healing_engine, ads_engine, financial_engine, product_engine,
scaling_engine, unit_economics_engine, telegram_bot, trust_aggregator,
trust_feedback_engine, api/telegram_command_router, test_shadow_runner.

Ruff não auto-fixa F841 sem `--unsafe-fixes` (risco de deletar atribuição
com side-effect). Fix manual: avaliar cada variável, deletar atribuição
ou usar a variável.

Esforço estimado: **2-3h** (inspeção + delete/use)

---

### F821 — Nome não definido (18 ocorrências)

Concentrado em `utils/trust_aggregator.py` (provável decorrência do bug
F706 — código fora de função referencia variáveis locais que não existem
no escopo).

Esforço estimado: **resolvido junto com F706**

---

### E402 — Import fora do topo do arquivo (13 ocorrências)

Arquivos: agents/claude_runner, core/execution_control,
engines/kaizen_engine, engines/opportunity_pipeline, main, security_layer,
utils/result_ingestor, agents/claude_runner_v2 (F401).

Causa típica: import após `load_dotenv()` ou `sys.path.insert()`.
Fix: adicionar `# noqa: E402` inline quando o import late é intencional
(ex: depende de env vars), ou reordenar para o topo quando não há
dependência real.

Esforço estimado: **1h** (8 arquivos, inspeção caso a caso)

---

### E741 — Nome de variável ambíguo: l, I, O (9 ocorrências)

Arquivos: crm_engine, dashboard_engine, generate_dashboard,
test_orchestrator_canonical, sofia_monitor_engine, nexara/orquestrador,
build_pitch.

Fix: rename `l` → `lead` / `line` / `item` conforme contexto.
Esforço estimado: **30 min** (trivial)

---

### E722 — Bare `except:` sem tipo (3 ocorrências)

Arquivos: observability.py, content_engine, generate_dashboard.
Fix: `except:` → `except Exception:`.
Esforço estimado: **15 min** (trivial)

---

### F401 — Import não usado (1 ocorrência)

`agents/claude_runner_v2.py` — 1 import residual.
Esforço estimado: **5 min**

---

## Ordem de ataque recomendada

1. **Investigar F701/F706 em `utils/trust_aggregator.py`** — prioridade por
   risco de bug real. Head + contexto de indentação.
2. **E741** — rename trivial, desbloqueia outros fixes
3. **E722** — 3 linhas, 15 min
4. **E402** — noqa inline ou reorder por arquivo
5. **F841** — inspecionar e deletar variáveis mortas
6. **F401** — 1 import, 5 min
7. **F821** — resolvido em cascata com F706

---

## Progresso

| Data | Ação | Resultado |
|------|------|-----------|
| 2026-04-28 | ruff --fix F401,F841,F811 | 1 fix: telegram_ideas_poll.py |
| 2026-04-28 | ruff.toml limpo (sem per-file-ignores) | Baseline estabelecido |

---

## Referências

- Commit A (lint infra): `87fee12`
- Commit D (wave2 refactor): `fabf649`
- LESSON-002 (bug indentação result_ingestor): `docs/memoria/LESSON-007-pre-diagnostico.md`
- Pre-commit exclude temporário: `.pre-commit-config.yaml` (seção `exclude`)
