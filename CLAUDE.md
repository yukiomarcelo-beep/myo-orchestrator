# CLAUDE.md — MYO OS (orchestrator)

Contexto permanente do repositório. Lido toda vez que `claude` abre aqui.

## O que é

Pipeline AI autônomo de criação/operação de negócios online. Não é um app de uma funcionalidade só — é um **sistema de orquestração** com engines independentes + camada de execução via GitHub + trust pipeline que aprende.

Repo público com `protect-main`. PRs obrigatórios.

## Stack

- **Python 3.14** (não 3.11/3.12 — checar `python3 --version` antes de instalar deps)
- **uv** para gerência de pacotes (preferir sobre pip). `uv pip install -r requirements.txt` é 100x mais rápido.
- **FastAPI** (`main.py`), **httpx** (async), **psycopg2** (audit), **Pydantic v2**
- APIs: **Anthropic Claude** (obrigatória), OpenAI, Perplexity, Notion (opcionais)

## Arquitetura (11 engines + execução)

**Business engines** (`opportunity_scorer.py`, `product_engine.py`, `content_engine.py`, `video_engine.py`, `sales_engine.py`, `performance_engine.py`, `validation_engine.py`, `crm_engine.py`, `scaling_engine.py`, `dashboard_engine.py`, `master_controller.py`).

**Execution layer:**
```
myo_cli.py → execution_engine → executor_router → github_executor
  → GitHub issue → claude_runner.py → result_ingestor.py
  → trust_aggregator → trust_feedback_engine → policy_adapter → context_policy.json
```

**Trust pipeline:** `verification_engine.py` (semântica via Claude) → `verification_logger.py` (JSONL) → `trust_aggregator.py` (métricas topic × context × engine) → `claim_policy.py` (thresholds) → `policy_adapter.py` (ajuste automático).

**Contextos:** `idea` → `research` → `mvp` → `launch_ready` → `scaling`.

**Regras de ajuste automático (não mexa à mão — use policy_adapter):**
- topic failure_rate > 60% → endurece threshold +5
- policy_rigidity experiment success_rate > 60% → relaxa gate -5
- api_cost failure_rate > 50% → liga `api_cost_strict`

## Convenções

- **Async primeiro.** Use `async/await` + httpx.AsyncClient. Se adicionar código sync em engine existente, justifique.
- **Toda chamada externa** tem timeout explícito + fallback estruturado. Nada de `try: ... except: pass`.
- **API keys** só via `os.getenv` após `load_dotenv()`. Nunca hardcoded. Nunca em logs.
- **Campos experiment** (`original_failure_type`, `retry_mode`, `experiment_context`, `experiment_result`, `original_hint`) são obrigatórios em retries via execution layer.
- **Formato JSONL** do `outputs/trust/` é crítico — mudanças exigem migration ou são backwards-compatible.
- **Não adicionar** comentários óbvios. Só `# Why:` quando o motivo não estiver no código.
- **Preferir deletar** código não usado sobre manter atrás de feature flag.

## Comandos frequentes

```bash
# Ativar env
source venv/bin/activate  # (ou uv venv + source .venv/bin/activate se migrar)

# Loop de aprendizado
python3 result_ingestor.py              # verifica semanticamente + roda trust
python3 policy_adapter.py               # ajusta thresholds (aplica)
python3 policy_adapter.py --dry-run     # preview sem salvar

# Servidor/dashboard
python3 main.py                          # FastAPI

# Testes
pytest                                   # conftest.py na raiz
```

## Slash commands disponíveis

- `/myo-health` — git state + último trust event + policy + dry-run adapter
- `/checkpoint myo` — resumo dos checkpoints

## Subagente recomendado

Para review de código deste repo: invoque o agent `myo-reviewer` (conhece convenções e trust pipeline).

## Pendências (vindas dos checkpoints)

- Ativar GitHub real: substituir stubs em `.env` (`GITHUB_TOKEN`, `GITHUB_REPO`) e rodar loop completo
- Migrar de `venv/` pra `uv venv` (agora que uv está instalado)

## Referências

- `STATUS.md` — estado macro versionado
- `MYO_ANALISE_SISTEMA.md` — arquitetura detalhada
- Memória: `~/.claude/projects/-Users-marceloyukio/memory/projetos/myo-os/`

## Formato de handoff do chat (Opus) pra este Code (Sonnet)

Quando receber uma mensagem começando com `### HANDOFF`, trate como spec executável vinda da sessão de arquitetura. Formato:

### HANDOFF <nome-curto>
**Contexto decidido no chat:** <1-3 linhas>
**Arquivos a criar/editar:** <lista>
**Regras invioláveis aplicáveis:** <quais regras do CLAUDE.md este trabalho obedece>
**Critério de aceite:** <como saber que terminou>
**Fora do escopo:** <o que NÃO fazer nesta execução>

Regras ao receber handoff:
1. Não pergunte "você tem certeza?" — a decisão já foi tomada no chat. Execute.
2. Se descobrir durante execução que a spec quebra regra inviolável do CLAUDE.md → pare, aponte o conflito, peça confirmação.
3. Ao terminar, responda APENAS com: arquivos criados/editados + resultado dos testes + próximo handoff sugerido.
4. Zero análise, zero "opções A/B/C", zero runbook em markdown.
