# ORCH — Pain to Product Engine

Pipeline completo de descoberta de oportunidades:
reclamações de mercado → dor prioritária → concorrência → debate GPT × Claude → produto priorizado.

---

## Estrutura

```
orchestrator/
  main.py                          ← ponto de entrada
  orch_core.py                     ← motor de debate GPT × Claude + scoring
  pain_radar_adapter.py            ← clusteriza dores e gera produto inicial
  competitor_research_adapter.py   ← mapeia gaps e vetores de ataque
  opportunity_pipeline.py          ← encadeia os 3 estágios + sinal para o Orch
  complaint_collector.py           ← coleta reclamações (Reddit, RSS, JSON)
  competitor_collector.py          ← pesquisa concorrentes (Perplexity + scraping)
  telegram_command_router.py       ← bot Telegram com comandos /criar_produto etc.
  outputs/                         ← JSONs gerados em cada execução
  requirements.txt
  .env.example
```

---

## Instalação

```bash
cd orchestrator
pip install -r requirements.txt
cp .env.example .env
# edite .env com suas chaves
```

---

## Variáveis de ambiente (`.env`)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Claude — critic, scorer, pain radar |
| `OPENAI_API_KEY` | ✅ | GPT — proposer, refiner, competitor research |
| `PERPLEXITY_API_KEY` | Recomendada | Busca de concorrentes na web |
| `TELEGRAM_BOT_TOKEN` | Opcional | Bot Telegram |
| `TELEGRAM_CHAT_ID` | Opcional | Chat para alertas |
| `GPT_MODEL` | Opcional | Padrão: `gpt-4o` |
| `MYO_PASSWORD` | Opcional | Protege painel MYO (vazio = sem auth) |
| `STRIPE_SECRET_KEY` | Opcional | Receita ao vivo no painel MYO |

---

## Modos de execução

### 1. Demo (dados simulados — testa sem APIs de coleta)

```bash
python main.py
```

### 2. Auto (coleta ao vivo Reddit + Perplexity)

```bash
python main.py --mode auto \
  --niche "restaurant" \
  --problem "profit margin pricing cash flow" \
  --subreddits "restaurantowners,smallbusiness,entrepreneur"
```

Parâmetros opcionais:
```
--reddit-limit 15   # posts por query (padrão: 10)
--rounds 5          # rodadas de debate GPT×Claude (padrão: 3)
--output-dir outputs/meu_run
--quiet             # menos logs
```

### 3. JSON (com arquivos já coletados)

```bash
python main.py --mode json \
  --complaints-file  outputs/complaints_reddit.json \
  --competitors-file outputs/competitors_auto.json
```

---

## Fluxo completo

```
Reclamações (Reddit / RSS / JSON)
  └─► ComplaintCollector      → complaint_record[]
        └─► PainRadarAdapter  → clusters de dor + produto inicial (Claude)
              └─► CompetitorResearchAdapter → gaps + vetores de ataque (GPT)
                    └─► signal_builder → TrendSignal enriquecido
                          └─► Orchestrator
                                ├─ Round 1..N: GPT propõe → Claude critica → GPT refina
                                ├─ Score final (Claude): 0–100 em 8 dimensões
                                ├─ Filtros de rejeição automática
                                └─► OpportunityDecision
                                      └─► outputs/main_result.json
```

---

## Saídas geradas (`outputs/<run>/`)

| Arquivo | Conteúdo |
|---|---|
| `complaints_auto.json` | Reclamações coletadas e pontuadas |
| `competitors_auto.json` | Concorrentes perfilizados |
| `01_pain_radar.json` | Clusters de dor, scores, produto inicial |
| `02_competitor_intel.json` | Gaps, vetores de ataque, posicionamento |
| `03_decision.json` | Decisão final do Orchestrator |
| `main_result.json` | Saída consolidada (entrada para o Executor) |

---

## Bot Telegram

### Iniciar polling

```bash
python telegram_command_router.py --poll
```

### Comandos

```
/scan_dores <nicho>|<problema>|<sub1,sub2>
/scan_concorrencia <nicho>|<problema>
/criar_produto <nicho>|<problema>|<sub1,sub2>
/top_oportunidades
/ajuda
```

**Exemplo completo:**
```
/criar_produto restaurant|profit margin pricing cash flow|restaurantowners,smallbusiness,entrepreneur
```

O bot responde imediatamente e envia o resultado no chat quando o pipeline terminar (~2 min).

---

## Módulos individuais

Cada arquivo pode ser rodado diretamente:

```bash
python complaint_collector.py  --queries "restaurant profit,small business margin" --subreddits "smallbusiness"
python competitor_collector.py --niche "restaurant" --problem "margin pricing"
python pain_radar_adapter.py
python opportunity_pipeline.py
python orch_core.py --rounds 5
```

---

## Acoplamento com o MYO Server

O pipeline já salva `03_decision.json` em `outputs/`. Para conectar ao MYO:

```python
from opportunity_pipeline import OpportunityPipeline

pipeline = OpportunityPipeline()
result   = pipeline.run(complaints_payload, competitors_payload)

if result["status"] == "aprovado":
    # envia para o executor MYO
    requests.post("http://localhost:8000/api/run-pipeline",
                  json={"produto": result["idea_name"]})
```
