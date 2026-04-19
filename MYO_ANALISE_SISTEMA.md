# MYO OS — Análise Completa do Sistema
> Gerado em: 2026-04-02 | Para uso com Claude (análise de próximos passos)

---

## 1. VISÃO GERAL

**MYO OS** é um sistema de negócio digital automatizado construído em Python + FastAPI.
O objetivo é transformar dores de mercado em produtos digitais vendidos online, com o mínimo de intervenção humana.

**Stack principal:**
- Backend: Python 3.14 + FastAPI + Jinja2 (porta 8000)
- Frontend alternativo: React + Vite (porta 5173, em desenvolvimento)
- APIs de IA: Anthropic Claude, OpenAI GPT, Perplexity
- Automações: ElevenLabs (voz), HeyGen (vídeo), Telegram (bot)
- Integrações: Notion, Stripe (webhook), n8n (workflows)
- Dados: JSON files em `outputs/` (sem banco de dados ainda)

---

## 2. ARQUITETURA DE ENGINES (23 componentes)

### Nível 0 — Core Infraestrutura
| Engine | Arquivo | Status | Função |
|---|---|---|---|
| Master Controller | `core/master_controller.py` | ✅ existe | Orquestra todas as engines, gerencia fluxo |
| MYO Server | `api/myo_server.py` | ✅ rodando | FastAPI — 60+ endpoints, serve plataforma web |

### Nível 1 — Inteligência Base
| Engine | Arquivo | Status | Função |
|---|---|---|---|
| Strategic Memory | `agents/strategic_memory.py` | ✅ existe | Aprende padrões, alimenta decisões futuras |
| Execution Engine | `engines/execution_engine.py` | ✅ existe | Executa tarefas async, gerencia filas |
| Dashboard Engine | `engines/dashboard_engine.py` | ✅ existe | Agrega métricas para o painel |

### Nível 2 — Oportunidade
| Engine | Arquivo | Status | Função |
|---|---|---|---|
| Opportunity Pipeline | `engines/opportunity_pipeline.py` | ✅ existe | Escaneia nichos, avalia demanda, score de oportunidade |
| Opportunity Scorer | `engines/opportunity_scorer.py` | ✅ existe | Pontuação detalhada das oportunidades |
| Validation Engine | `engines/validation_engine.py` | ✅ existe | Valida hipóteses antes de avançar |

### Nível 3 — Produto
| Engine | Arquivo | Status | Função |
|---|---|---|---|
| Product Engine | `engines/product_engine.py` | ✅ existe | Define produto, posicionamento, avatar |
| Pricing Engine | `engines/pricing_engine.py` | ✅ existe | Estratégia de preço com benchmarks |

### Nível 4 — Conteúdo
| Engine | Arquivo | Status | Função |
|---|---|---|---|
| Content Engine | `engines/content_engine.py` | ✅ existe | Gera copies, posts, e-mails |
| Video Engine | `engines/video_engine.py` | ✅ existe | Roteiros e vídeos (HeyGen + ElevenLabs) |

### Nível 5 — Vendas
| Engine | Arquivo | Status | Função |
|---|---|---|---|
| Sales Engine | `engines/sales_engine.py` | ✅ existe | Funil de vendas, landing page, checkout |
| Ads Engine | `engines/ads_engine.py` | ✅ existe | Campanhas pagas Meta/Google/TikTok |
| CRM Engine | `engines/crm_engine.py` | ✅ existe | Leads, qualificação, follow-ups |

### Nível 6 — Performance & Financeiro
| Engine | Arquivo | Status | Função |
|---|---|---|---|
| Performance Engine | `engines/performance_engine.py` | ✅ existe | Métricas, aprende padrões |
| Financial Engine | `engines/financial_engine.py` | ✅ existe | Receita, custos, margem, fluxo de caixa |
| SaaS Metrics | `engines/saas_metrics_engine.py` | ✅ existe | MRR, ARR, churn, NPS |
| Unit Economics | `engines/unit_economics_engine.py` | ✅ existe | CAC, LTV, payback period |

### Nível 7 — Otimização & Crescimento
| Engine | Arquivo | Status | Função |
|---|---|---|---|
| Kaizen Engine | `engines/kaizen_engine.py` | ✅ existe | Melhoria contínua automatizada |
| Scaling Engine | `engines/scaling_engine.py` | ✅ existe | Quando e como escalar |
| Growth Simulator | `engines/growth_simulator.py` | ✅ existe | Simula cenários com Monte Carlo |
| Self-Healing Engine | `engines/self_healing_engine.py` | ✅ existe | Detecta e corrige erros |

### Nível 8 — Integrações
| Engine | Arquivo | Status | Função |
|---|---|---|---|
| Notion Engine | `integrations/notion_engine.py` | ✅ existe | Sincroniza decisões com Notion |

### Engines de Suporte
| Arquivo | Função |
|---|---|
| `core/orch_core.py` | Debate GPT × Claude, scoring, rejeição automática |
| `agents/llm_router.py` | Roteamento entre modelos de IA |
| `agents/claude_runner.py` | Wrapper para Claude API |
| `adapters/pain_radar_adapter.py` | Clusteriza dores do mercado |
| `adapters/competitor_research_adapter.py` | Pesquisa concorrentes |
| `adapters/complaint_collector.py` | Coleta reclamações (Reddit, RSS) |
| `utils/audit_engine.py` | Auditoria de decisões |
| `utils/trust_feedback_engine.py` | Feedback de confiança |
| `utils/verification_engine.py` | Verificação de outputs |

---

## 3. DADOS ATUAIS DO NEGÓCIO

### Produto Ativo: CFO Digital
```
Receita atual:  R$ 891,00
Lucro atual:    R$ 506,00
Margem:         56.8%
Custo op./mês:  R$ 350,00
  - IA (Claude + GPT):  R$ 47
  - Plataforma:         R$ 0
  - Infra:              R$ 28
  - Ferramentas:        R$ 55
  - Ads (Meta teste):   R$ 220
Decisão IA:     escalar_com_cautela
```

### Pipeline CRM
```
Total de leads: 5
  - Quentes: 2
  - Mornos:  2
  - Frios:   1
```

### Negócios Cadastrados
```
1. CFO Digital     → fase: performance  [ativo]
2. Produto X       → fase: opportunity  [idle]
3. Agência MYO     → fase: opportunity  [idle]
```

### Aprovações
```
Total:     7
Aprovadas: 7
Pendentes: 0
```

### Estado do Pipeline (system_state.json)
```
opportunity → rodando (progresso 27%)
CFO Digital → idle / error
Produto-Demo → done
ORCH Engine → idle / error
Kaizen Engine → done
```

### Outputs Gerados
```
blueprint_cfo_digital_001.json   → Blueprint do produto
content_cfo_digital_001.json     → Conteúdo gerado
funnel_cfo_digital_001.json      → Funil de vendas
performance_cfo_001/002.json     → Análises de performance
scaling_cfo_001.json             → Plano de escala
validation_cfo_001.json          → Validação de hipótese
video_cfo_digital_001.json       → Roteiro de vídeo
scoring_CFO_Digital_*.json       → Score de oportunidade
ads_campaigns.json               → Campanhas configuradas
simulations.json                 → Simulações de crescimento
pnl_history.json                 → Histórico P&L (6 meses)
```

---

## 4. PLATAFORMA WEB — PÁGINAS

| Rota | Template | Função |
|---|---|---|
| `/` | home (inline) | Dashboard executivo com métricas |
| `/dashboard` | `dashboard.html` | Operacional — KPIs, pipeline, log ao vivo |
| `/novo-dashboard` | React frontend | Dashboard React (em desenvolvimento) |
| `/organograma` | `organograma.html` | Grafo interativo com 23 engines |
| `/operacao` | `operacao.html` | Aprovações pendentes, ações manuais |
| `/crm` | `crm.html` | Gestão de leads |
| `/vendas` | `vendas.html` | Pipeline de vendas |
| `/produtos` | `produtos.html` | Gestão de produtos |
| `/portfolio` | `portfolio.html` | Portfolio exportável em PDF |
| `/relatorios` | `relatorios.html` | Relatórios financeiro/marketing/custos |
| `/roi` | `roi.html` | Dashboard ROI de aprovações |
| `/orch` | inline | ORCH Engine — análise de oportunidades com IA |
| `/kit-demo` | `kit-demo.html` | Demo do dashboard-kit visual |
| `/login` | `login.html` | Auth por cookie |

---

## 5. APIs REST — ENDPOINTS

### Estado e Monitoramento
```
GET  /api/state          → Estado completo do pipeline (produtos, fases, status)
GET  /api/status         → Saúde do sistema (ok, problemas, auto_level)
GET  /api/log            → Log de eventos em tempo real
GET  /api/system-health  → Health check detalhado
GET  /api/home-data      → Dados para home executiva
```

### KPIs e Financeiro
```
GET  /api/kpis           → Receita, lucro, conversão, leads, margem
GET  /api/pnl            → P&L por negócio
GET  /api/pnl-history    → Histórico 6 meses {historico[], insights[]}
GET  /api/custos         → Custos operacionais {costs[], total}
GET  /api/roi-history    → Histórico de aprovações com ROI
GET  /api/stripe-revenue → Receita real via Stripe API
```

### Pipeline e Engines
```
POST /api/pipeline/start        → Inicia pipeline para um produto
GET  /api/pipeline/status       → Status do pipeline ativo
GET  /api/pipeline              → Pipeline atual {fase, progresso, status}
POST /api/run-pipeline          → Executa pipeline completo
POST /api/regenerar             → Regenera output de uma fase
POST /api/orchestrator/run      → Executa ORCH (análise de oportunidade com debate IA)
GET  /api/orchestrator/status   → Status do ORCH
GET  /api/orchestrator/result   → Resultado do último ORCH
GET  /api/orchestrator/opportunity → Oportunidade gerada pelo ORCH
```

### Negócios
```
GET  /api/businesses     → Lista de negócios ativos
POST /api/businesses     → Cria novo negócio
```

### Aprovações Humanas
```
GET  /api/pending            → Aprovações pendentes
POST /api/request-approval   → Solicita aprovação para uma ação
POST /api/approve/{id}       → Aprova uma ação (com auto-trigger opcional)
POST /api/reject/{id}        → Rejeita uma ação
```

### CRM e Leads
```
GET  /api/crm            → Lista de leads com temperatura e score
POST /api/add-lead       → Adiciona novo lead
GET  /api/mapa           → Pontos geográficos dos leads (para mapa Leaflet)
```

### IA e Automação
```
POST /api/sugerir        → Gera sugestões com IA
POST /api/estrategia     → Gera estratégia para produto
POST /api/new-idea       → Avalia nova ideia de produto
POST /api/simulate       → Simula crescimento (cenários)
GET  /api/suggest-actions → Sugere próximas ações com IA
POST /api/log-performance → Registra evento de performance
```

### Autônomo
```
GET  /api/autonomous     → Nível atual (0=manual, 1=sugerido, 2=auto)
POST /api/autonomous     → Define nível de autonomia
GET  /api/kaizen         → Análise Kaizen atual
POST /api/run-kaizen     → Executa ciclo Kaizen
```

### Webhooks e Integrações
```
POST /webhook/stripe     → Recebe eventos do Stripe
POST /api/login          → Autenticação com cookie
POST /api/logout         → Logout
```

### Governance (router externo)
```
/api/governance/*        → Endpoints de governança (governance_router.py)
```

---

## 6. ESTADO TÉCNICO — O QUE ESTÁ FUNCIONANDO

### ✅ Funcionando
- Servidor FastAPI rodando em localhost:8000
- Todos os endpoints principais retornando dados reais
- Templates Jinja2 com dados ao vivo
- Organograma com 23 engines visualizado (vis-network)
- Dashboard com KPIs reais (R$891 receita, 56.8% margem)
- CRM com 5 leads segmentados por temperatura
- P&L histórico 6 meses com chart Chart.js
- Custos operacionais (R$350/mês)
- Aprovações com fluxo completo (request → approve → auto-trigger)
- Modo autônomo (0/1/2)
- Mapa interativo (Leaflet.js)
- Auth com cookie (MYO_PASSWORD)
- Telegram bot (polling)
- Symlinks: api/outputs → outputs, api/static → static, api/templates → templates

### ⚠️ Problemas Conhecidos
- `system_state.json` mostra "ORCH Engine → error" e "opportunity → rodando 27%" (estado travado)
- `idea_analyzer.py` referenciado no organograma antigo mas não existe como arquivo independente
- Frontend React (porta 5173) existe mas não está integrado à produção
- Stripe: webhook configurado mas `STRIPE_SECRET_KEY` pode não estar no .env
- n8n workflows existem (3 JSONs) mas não estão ativos
- `pnl_history.json` tem poucos dados históricos reais (maioria estimado)
- Indentação 1-espaço no myo_server.py causou múltiplos bugs latentes (6 já corrigidos)

### ❌ Não implementado ainda
- Banco de dados (tudo em JSON files — sem persistência robusta)
- API de pagamento ativa (Stripe integrado mas sem receita real)
- Pipeline executando de ponta a ponta de forma autônoma
- Conteúdo publicado em plataforma real
- Produto CFO Digital com página de vendas ativa
- Integração n8n ativa
- Autenticação multi-usuário
- Deploy em produção (tudo local)

---

## 7. FLUXO ORCH (Pain to Product)

```
Reclamações (Reddit/RSS/arquivo)
  → ComplaintCollector        → complaint_record[]
  → PainRadarAdapter          → clusters + produto inicial  (Claude)
  → CompetitorResearch        → gaps + vetores de ataque    (GPT)
  → signal_builder            → TrendSignal enriquecido
  → Orchestrator (orch_core)  → debate N rodadas GPT × Claude
  → OpportunityDecision       → score + rejeição + ações
  → /api/request-approval     → fila de aprovação humana
  → POST /api/approve/{id}    → auto-trigger master_controller
  → Pipeline completo         → blueprint → content → video → sales
```

**Produtos avaliados pelo ORCH:**
- CFO Digital — score 60/100 — aprovado e em produção
- App Dieta — avaliado
- Mentoria Precificação — avaliado

---

## 8. TECNOLOGIAS DE IA INTEGRADAS

| API | Uso | Chave necessária |
|---|---|---|
| Anthropic Claude | Pain radar, critic, scorer, conteúdo | `ANTHROPIC_API_KEY` |
| OpenAI GPT | Proposer, competitor research, estratégia | `OPENAI_API_KEY` |
| Perplexity | Pesquisa de concorrentes | `PERPLEXITY_API_KEY` |
| ElevenLabs | Voz para vídeos | `ELEVENLABS_API_KEY` |
| HeyGen | Produção de vídeo com avatar | `HEYGEN_API_KEY` |
| Telegram Bot | Comandos e alertas | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |
| Stripe | Pagamentos e receita real | `STRIPE_SECRET_KEY` |
| Notion | Persistência de decisões | `NOTION_TOKEN` + `NOTION_DATABASE_ID` |

---

## 9. MÉTRICAS DO CÓDIGO

```
myo_server.py:          ~4.000 linhas
engines/ (19 arquivos): ~15.000 linhas total
core/ (5 arquivos):     ~3.100 linhas total
Templates HTML:         14 páginas
API endpoints:          60+ rotas
Output files:           24 arquivos JSON
```

---

## 10. ESTRUTURA DE PASTAS

```
orchestrator/
├── api/
│   ├── myo_server.py          # Servidor principal (~4k linhas)
│   ├── run_server.py          # Wrapper de inicialização
│   ├── governance_router.py   # Router de governança
│   ├── executor_router.py     # Router de execução
│   └── telegram_command_router.py
├── agents/
│   ├── strategic_memory.py
│   ├── llm_router.py
│   ├── claude_runner.py
│   └── autonomous_agent.py
├── core/
│   ├── master_controller.py
│   ├── orch_core.py           # Debate GPT × Claude
│   ├── orchestrator.py
│   ├── myo.py
│   └── myo_cli.py
├── engines/ (19 engines)
│   ├── opportunity_pipeline.py
│   ├── product_engine.py
│   ├── pricing_engine.py
│   ├── content_engine.py
│   ├── video_engine.py
│   ├── sales_engine.py
│   ├── ads_engine.py
│   ├── crm_engine.py
│   ├── performance_engine.py
│   ├── financial_engine.py
│   ├── saas_metrics_engine.py
│   ├── unit_economics_engine.py
│   ├── kaizen_engine.py
│   ├── scaling_engine.py
│   ├── growth_simulator.py
│   ├── self_healing_engine.py
│   ├── validation_engine.py
│   ├── dashboard_engine.py
│   └── execution_engine.py
├── adapters/
│   ├── pain_radar_adapter.py
│   ├── competitor_research_adapter.py
│   └── complaint_collector.py
├── integrations/
│   ├── notion_engine.py
│   ├── notion_logger.py
│   ├── telegram_bot.py
│   └── github_executor.py
├── utils/
│   ├── audit_engine.py
│   ├── trust_feedback_engine.py
│   └── verification_engine.py
├── templates/ (14 páginas HTML)
├── static/ (CSS, JS, Chart.js)
├── frontend/ (React + Vite — em desenvolvimento)
├── outputs/ (24 arquivos JSON — estado persistido)
├── config/
│   ├── system_map.json
│   └── context_policy.json
└── main.py
```

---

## 11. PERGUNTAS PARA O CLAUDE DEFINIR PRÓXIMOS PASSOS

1. **Receita real**: CFO Digital tem R$891 em vendas simuladas. Como transformar isso em receita real? (página de vendas, checkout Hotmart/Kiwify, ads ativos)

2. **Pipeline end-to-end**: O fluxo ORCH → aprovação → pipeline existe no código mas não executa de ponta a ponta de forma confiável. Como estabilizar?

3. **Persistência**: Tudo em JSON files. Quando escalar para PostgreSQL? Como migrar sem quebrar os 60+ endpoints?

4. **Multi-negócio**: "Produto X" e "Agência MYO" estão em `opportunity` idle. Como ativar o pipeline para um segundo produto simultaneamente?

5. **Monetização imediata**: Com a margem de 56.8% e 2 leads quentes, qual a próxima ação de maior ROI?

6. **Deploy**: Sistema rodando 100% local. Como fazer deploy (Railway, VPS, Render) mantendo os JSON files e o servidor?

7. **React vs Jinja2**: Existe frontend React em desenvolvimento mas o Jinja2 está funcionando. Vale migrar completamente? Ou manter os dois?

8. **Dados reais**: pnl_history tem poucos dados reais. Como conectar Stripe para popular automaticamente?

9. **Self-healing**: O engine existe mas o estado mostra erros não resolvidos. Como ativar o ciclo de auto-recuperação?

10. **Escalabilidade do myo_server.py**: 4.000 linhas em um único arquivo com bugs de indentação históricos. Quando e como refatorar em módulos menores?
