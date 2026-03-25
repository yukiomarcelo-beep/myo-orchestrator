# MYO — Status do Sistema
Última atualização: 25/03/2026 (atualizado)

---

## ✅ CONCLUÍDO HOJE

### 1. Dashboard Mobile
- Hamburger menu + sidebar drawer para celular
- Cloudflare Tunnel instalado em `~/bin/cloudflared`
- Menu MYO → opção 12 → 2 sobe servidor + tunnel automaticamente
- URL pública salva em `outputs/tunnel_url.txt`

### 2. Notion — Estrutura Completa
Página raiz: **MYO — Pipeline de Negócio**
(dentro de AI Operating System → AI COMPANY OS)

| Database | ID | Relações |
|---|---|---|
| Central de Comando | `11ded56a9d9a4032bfffc04741db607b` | — |
| Banco de Ideias | `e9d9a79c3868415b8c01d443addd2d3d` | ← Conteúdo |
| Conteúdo | `e35930fe71b043c0a8199b9dca3fbcea` | → Ideias / ← Produtos |
| Produtos | `68085ac404854c1eb2705e991aa0e432` | → Conteúdo |
| Insights e Aprendizado | `5373e8dfb46f401cb06613e812079c4e` | — |
| Logs de Execução | `5c339186b8894899841dde17714d8238` | — |

### 3. Notion — Views da Central de Comando
- **Kanban — Status** (board agrupado por status) ✅
- **Top Score** (tabela ordenada por score_ia) ✅
- **Fila — Novos** (lista filtrada status=novo) ✅
- **Prioridade × Score** (tabela duplo sort: prioridade + score_ia desc) ✅

### 4. notion_engine.py — Conexão Validada
- Integração `agenteorquestradorn8n` adicionada à Central de Comando ✅
- Dry-run OK: 3 itens detectados, roteamento correto por modo_execucao ✅
- Pronto para rodar com `python3 notion_engine.py` após crédito OpenAI

### 5. n8n Workflows (prontos para importar)
| Arquivo | Função |
|---|---|
| `myo_n8n_workflow.json` | Principal v2: trigger → switch → IA → merge → score → Notion |
| `myo_n8n_error_workflow.json` | Error Handler: captura falhas → loga em Logs de Execução |
| `myo_n8n_scheduled_workflow.json` | Agendado: seg–sex 08h → tema aleatório → IA → Central de Comando |

### 4. Python — notion_engine.py
- Alternativa ao n8n, roda pelo menu MYO → opção 13
- Busca itens com `status = novo` na Central de Comando
- Roteia por `modo_execucao` → OpenAI → atualiza Notion + salva em `outputs/`

### 5. .env atualizado
```
NOTION_TOKEN=ntn_573309338754...
NOTION_DATABASE_ID=11ded56a9d9a4032bfffc04741db607b
```

### 6. Itens de teste criados no Notion
| Título | Modo | Status |
|---|---|---|
| restaurante fatura bem mas não lucra | research_auto | novo |
| erro invisível no CMV | dan_koe | novo |
| dashboard financeiro para restaurantes | produto | novo |

---

## ⏳ PENDENTE — RETOMAR AMANHÃ

### 🔴 CRÍTICO (sem isso o n8n não processa)
- [ ] **Adicionar crédito na OpenAI** (mín. $5 → platform.openai.com → Billing)
  - Free tier = 3 req/min → fluxo trava
  - Com crédito: 500 req/min, sem espera

### 🟡 N8N — Implementação em fases
- [ ] **Fase 1** — Importar `myo_n8n_workflow.json`, conectar credenciais, testar só ramo `research_auto`
- [ ] **Fase 2** — Testar ramo `dan_koe`
- [ ] **Fase 3** — Testar ramo `produto`
- [ ] **Fase 4** — Verificar Merge + Score funcionando (campo `score_ia` no Notion)
- [ ] **Fase 5** — Importar `myo_n8n_error_workflow.json` → ativar → copiar ID → colar em Settings → Error Workflow do principal
- [ ] **Fase 6** — Importar `myo_n8n_scheduled_workflow.json` → ativar

### 🟡 NOTION — Ajustes pós-teste
- [x] Confirmar que a integração n8n tem acesso à **Central de Comando** (Connections) ✅
- [ ] Adicionar integração `agenteorquestradorn8n` ao **Logs de Execução** (mesmo processo: `...` → Connections)
- [ ] Verificar se campo `score_ia` está sendo gravado corretamente (aguarda OpenAI)

### 🟢 MELHORIAS OPCIONAIS
- [ ] Adicionar webhook no n8n para também disparar em `page updated` (não só `page added`)
- [x] Criar view no Notion por `prioridade` e `score_ia` — **Prioridade × Score** criada ✅
- [ ] Conectar `notion_engine.py` ao watch mode em background (menu 13 → opção 2)
- [ ] Testar dashboard mobile via URL do Cloudflare Tunnel

---

## 🏗️ ARQUITETURA ATUAL

```
CELULAR / BROWSER
      ↓
Cloudflare Tunnel → servidor local (porta 8080) → dashboard.html

NOTION (Central de Comando)
  → status = novo
      ↓
  n8n Trigger
      ↓
  Switch (modo_execucao)
  ├── research_auto → OpenAI → parse → merge
  ├── dan_koe       → OpenAI → parse → merge
  └── produto       → OpenAI → parse → merge
                                          ↓
                                    Score Automático
                                          ↓
                                    Notion Update
                                    (status, saida_json, score_ia)

AGENDADOR (seg–sex 08h)
  → gera tema aleatório → OpenAI → cria item na Central de Comando

ERROR HANDLER
  → qualquer falha → Logs de Execução no Notion
```

---

## 📁 ARQUIVOS PRINCIPAIS

```
/Documents/orchestrator/
├── myo.py                         ← menu principal (opções 1-13)
├── notion_engine.py               ← alternativa Python ao n8n
├── server.py                      ← servidor do dashboard
├── generate_dashboard.py          ← gera dashboard.html
├── myo_n8n_workflow.json          ← workflow principal v2
├── myo_n8n_error_workflow.json    ← workflow error handler
├── myo_n8n_scheduled_workflow.json← workflow agendado
├── .env                           ← chaves de API
└── outputs/                       ← resultados de cada engine
```
