# Operação Choke Point — Semana 1

**Data de conclusão:** 2026-04-27
**Objetivo:** Fechar 6 vulnerabilidades críticas de segurança e custo antes de qualquer nova feature.

---

## Entregas

### Entrega 1 — Rotação de credencial hardcoded
**Status:** ✓ Concluída

- Eliminado `KITCHEN_PG_PASSWORD` hardcoded em `api/myo_server.py`
- Senha rotacionada no Postgres local
- Credencial atualizada no n8n via Playwright
- Variável migrada para `.env` (lida via `os.getenv`)

**Critério de done:** `grep -r "k1FV" .` → zero hits em código de produção.

---

### Entrega 2 — Pre-commit: gitleaks + ruff
**Status:** ✓ Concluída

**Arquivos criados:**
- `.pre-commit-config.yaml` — gitleaks v8.18.4 + ruff v0.4.0
- `ruff.toml` — target py312, line-length 100, select E/F/I/W, ignore E501

**Critério de done:** `echo 'AWS_KEY = "<FAKE_KEY_REDACTED>"' > /tmp/_test_block.py && git add /tmp/_test_block.py && pre-commit run gitleaks` → bloqueou com exit 1.

---

### Entrega 3 — Zero `shell=True` em produção
**Status:** ✓ Concluída

**Arquivos modificados:**
- `core/myo.py` — 10 ocorrências eliminadas
- `core/safe_exec.py` — helper criado com `shell=False` explícito

**Padrões substituídos:**
- `subprocess.run(cmd, shell=True)` → `safe_exec(shlex.split(cmd))`
- `nohup python ... &` → `subprocess.Popen([...], stdout=log_f, stderr=log_f, start_new_session=True)`
- `pkill -f "..."` via shell → `subprocess.run(["pkill", "-f", "..."])`
- `open dash` via shell → `subprocess.run(["open", dash])`

**Critério de done:**
```
grep -r "shell=True" . \
  --include="*.py" \
  --exclude-dir=venv \
  --exclude-dir=.git \
  --exclude-dir=.claude \
  --exclude-dir=tests
```
→ zero hits.

---

### Entrega 4 — LLMGateway: retry + circuit breaker + prompt caching
**Status:** ✓ Concluída

**Arquivo criado:** `core/llm_gateway.py`

**Funcionalidades:**
- Retry exponencial com jitter (HTTP 429/5xx), máx 4 tentativas
- Circuit breaker 3 estados: CLOSED → OPEN → HALF_OPEN → CLOSED
  - Abre após `failure_threshold` falhas consecutivas
  - Cooldown padrão 60s; ao expirar vai para HALF_OPEN (probe único)
  - HALF_OPEN: sucesso → CLOSED, falha → OPEN (reset cooldown)
- Prompt caching via `anthropic-beta: prompt-caching-2024-07-31`
  - `cache_control: {"type": "ephemeral"}` aplicado quando `len(system) >= 4096`
- Log estruturado DEBUG com 4 campos de token: `input=`, `output=`, `cache_write=`, `cache_read=`
- `GatewayResponse` dataclass: `text, cost_usd, latency_ms, cached, input_tokens, output_tokens`

**Testes:** `tests/test_llm_gateway.py` — 10 testes, todos passando.
```
pytest tests/test_llm_gateway.py -v
10 passed in 7.14s
```

---

### Entrega 5 — Feature flag `MYO_USE_LLM_GATEWAY`
**Status:** ✓ Concluída

**Callsites atualizados (dual-path):**

| Arquivo | Função | Padrão |
|---------|--------|--------|
| `agents/llm_router.py` | `_call_claude` | `if os.getenv("MYO_USE_LLM_GATEWAY", "false").lower() == "true"` |
| `core/orch_core.py` | `AnthropicProvider.chat` | idem |
| `core/master_controller.py` | `_claude` (async) | idem + `asyncio.to_thread()` |

**`.env.example` atualizado:**
```
MYO_USE_LLM_GATEWAY=false  # false = httpx legado; true = gateway com caching/retry/CB
```

**Critério de done:** `grep -r "MYO_USE_LLM_GATEWAY" . --include="*.py"` → 4 hits (gateway + 3 callsites).

---

### Entrega 6 — Benchmark de prompt caching
**Status:** ✓ Concluída

**Arquivo criado:** `scripts/benchmark_caching.py`

**Configuração:**
- Modelo: `claude-haiku-4-5-20251001` (mais barato)
- System prompt: 11235 chars / ~2808 tokens (acima do mínimo Haiku de 2048)
- 50 chamadas por rodada (100 total)
- Orçamento máximo: $1.50

#### Tabela de Resultados

```
═══ BENCHMARK DE PROMPT CACHING ═══
Métrica                          | Sem cache  | Com cache  | Δ
---------------------------------|-------------|-------------|----------
Input tokens cobrados            | 209447      | 1947        | -99%
Cache creation tokens            | 0           | 4150        | +4150
Cache read tokens                | 0           | 203350      | +203350
Output tokens                    | 4000        | 4000        | 0%
Custo total (USD)                | $0.1836     | $0.0380     | -79%
Latência média (ms)              | 4488        | 2013        | -55%
Latência p95 (ms)                | 8019        | 2770        | -65%

Custo total das duas rodadas: $0.2215 USD
```

#### Critérios de Done

| Critério | Resultado | Status |
|----------|-----------|--------|
| Redução de custo ≥ 60% | 79.3% | ✓ |
| Cache read tokens > 0 | 203350 | ✓ |
| Custo total < USD 1.50 | $0.2215 | ✓ |

---

## Scorecard Final — Semana 1

| # | Entrega | Risco eliminado | Done |
|---|---------|-----------------|------|
| 1 | Rotação de credencial | Senha exposição no código-fonte | ✓ |
| 2 | Pre-commit gitleaks+ruff | Secrets acidentais em commits futuros | ✓ |
| 3 | Zero `shell=True` | Command injection via input não sanitizado | ✓ |
| 4 | LLMGateway (retry+CB+cache) | Cascata de falhas + custo desnecessário | ✓ |
| 5 | Feature flag MYO_USE_LLM_GATEWAY | Rollout sem downtime, reversível | ✓ |
| 6 | Benchmark caching | Validação quantitativa do ROI do gateway | ✓ |

**Redução de custo comprovada em produção simulada: 79% por chamada com system prompt longo.**

---

## Semana 2 — Próximos Passos Candidatos

1. **Ativar gateway em produção**
   - Setar `MYO_USE_LLM_GATEWAY=true` no `.env` de produção
   - Monitorar `outputs/llm_costs.json` por 48h comparando custo real vs baseline

2. **Cost guard no gateway**
   - Integrar `record_cost()` / `daily_cost_limit` do `master_controller` no `LLMGateway`
   - Emergency stop automático se custo diário > threshold

3. **Audit log de circuit breaker**
   - Eventos OPEN/HALF_OPEN/CLOSED escritos em JSONL para rastreabilidade
   - Alerta via Telegram quando CB abre

4. **Migrar `venv/` para `uv venv`**
   - Conforme pendência no CLAUDE.md

5. **Ativar GitHub real**
   - Substituir stubs `GITHUB_TOKEN` / `GITHUB_REPO` no `.env`
   - Rodar loop completo `myo_cli → execution_engine → github_executor`
