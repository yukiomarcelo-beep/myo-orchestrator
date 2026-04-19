# PR Wave-1 — Branch Investigation

**Branch:** `fix/ultrareview-wave-1`
**Data:** 2026-04-19
**Status:** investigação concluída, recomendação pronta (push/PR não executados)

---

## Cenário detectado

**(a) Target correto é `dev`** — os 9 commits que apareciam "sobrando" contra `origin/main` já estão em `origin/dev`. PR contra `dev` dá um diff legítimo da wave + 4 fixes pré-LESSON.

Corolários:
- PR contra `main` seria gigante e misturaria a wave com trabalho anterior de frontend/dashboard (9 commits) que provavelmente já tem um fluxo próprio dev→main.
- Não é caso de rebase: `fix/ultrareview-wave-1` saiu de uma base coerente e a sequência de commits está limpa.

## Evidências

### Contagens agregadas

| Comparação | Commits |
|---|---|
| `origin/main..fix/ultrareview-wave-1` | **23** |
| `origin/dev..fix/ultrareview-wave-1` | **14** |
| `origin/main..origin/dev` (já mergeado em dev, não em main) | **9** |

A diferença 23 − 14 = **9 commits** que estão em `origin/dev` (e por isso somem do diff contra `dev`). São todos de trabalho de frontend/dashboard/refactor pré-wave.

### Tabela completa (23 commits `origin/main..branch`)

Classificação: presença em `origin/main` e `origin/dev`, e natureza.

| SHA | main | dev | Natureza | Mensagem |
|---|---|---|---|---|
| `d92ee48` | no | no | doc sessão | docs: PR wave-1 delivery (BLOCKED) |
| `649bb23` | no | no | doc sessão | docs: FASE 2+3 delivery |
| `3a891a9` | no | no | CI sessão | ci: smoke tests on every push and PR |
| `3c41e60` | no | no | chore sessão | chore: gitignore .bak, archive backups |
| `72ad50f` | no | no | doc sessão | docs+tests: legacy pytest adapter + delivery |
| `aa0fc16` | no | no | **LESSON-006** | consolidate verification_logger canonical source |
| `2c7fc01` | no | no | **LESSON-005** | consolidate policy_adapter canonical source |
| `01b6cc4` | no | no | **LESSON-003** | runtime guard with context-aware policy enforcement |
| `8629c3d` | no | no | **LESSON-004** | consolidate AuditLog in core/audit_log.py |
| `ed1a94f` | no | no | **LESSON-002** | normalize execution_context + fix indentation bug |
| `d4a7eb8` | no | no | pré-LESSON fix | fix: drain subprocess stdout/stderr |
| `fd9672b` | no | no | pré-LESSON style | style: apply black formatter to api/myo_server.py |
| `103d7ef` | no | no | pré-LESSON fix | fix: resolve dead code in auth/telegram/pnl handlers |
| `fd2c993` | no | no | pré-LESSON baseline | feat: baseline — nexara, observability, security, execution control |
| `6160a26` | no | **yes** | em dev | fix: corrige 6 bugs de indentação em myo_server.py |
| `f6543a3` | no | **yes** | em dev | feat: integra dashboard-kit (tema roxo profundo) |
| `b25f5bd` | no | **yes** | em dev | feat: conecta React ao backend real |
| `01f6261` | no | **yes** | em dev | feat: dashboard design upgrade |
| `a0182b1` | no | **yes** | em dev | feat: frontend React — decision engine |
| `8d64253` | no | **yes** | em dev | feat: intelligence panel + KPI insights |
| `2bdbe80` | no | **yes** | em dev | refactor: reorganiza estrutura MYO em módulos |
| `ea2180c` | no | **yes** | em dev | feat: modo OFFLINE |
| `79db2cc` | no | **yes** | em dev | fix: corrige erros de sintaxe em 18 engines |

### Leitura rápida

- **14 commits** desaparecem do diff quando a base é `origin/dev` em vez de `origin/main`. Destes, os 9 últimos da tabela (`main=no, dev=yes`) são trabalho de frontend já mergeado em dev.
- **4 commits pré-LESSON** (`d4a7eb8`, `fd9672b`, `103d7ef`, `fd2c993`) não estão em nenhuma branch remota. São trabalho local (fixes + baseline nexara) feitos antes da wave de LESSONs começar. Legítimos, mas **não são wave-1 stricto sensu**.
- **5 LESSONS** (002-006) + **5 commits de suporte** (CI/chore/deliveries) = o núcleo da wave propriamente dita.

## Recomendação

### Ação primária — PR contra `dev`

Uma vez que você conceda escopo `workflow` ao PAT (ou troque o remote pra SSH) e instale `gh`:

```bash
git push -u origin fix/ultrareview-wave-1
# aguarda smoke.yml rodar em fix/ultrareview-wave-1 (ubuntu, py 3.11+3.12)
gh pr create \
  --base dev \
  --head fix/ultrareview-wave-1 \
  --title "Ultrareview Wave 1: LESSONS 002-006 + higiene + CI smoke" \
  --body "$(cat <<'EOF'
## Sumário
5 lessons consolidadas + 4 fixes pré-wave + higiene de repo + CI smoke tests.

## Commits (14 contra dev)
### LESSONs (5)
- ed1a94f LESSON-002: normalize execution_context + fix SyntaxError
- 8629c3d LESSON-004: AuditLog canônico em core/audit_log.py
- 01b6cc4 LESSON-003: runtime guard context-aware
- 2c7fc01 LESSON-005: policy_adapter canônico
- aa0fc16 LESSON-006: verification_logger canônico (remove 1983 linhas pass)

### Wave — suporte (5)
- 72ad50f docs+tests: legacy pytest adapter + LESSON-005/006 delivery
- 3c41e60 chore: gitignore .bak, archive old backups, track docs/memoria
- 3a891a9 ci: smoke tests on every push and PR
- 649bb23 docs: FASE 2+3 delivery
- d92ee48 docs: PR wave-1 investigation + BLOCKED note

### Pré-wave (4)
- fd2c993 feat: baseline nexara/observability/security/execution control
- 103d7ef fix: resolve dead code in auth/telegram/pnl handlers
- fd9672b style: apply black formatter to api/myo_server.py
- d4a7eb8 fix: drain subprocess stdout/stderr (pipe buffer deadlock)

## Testes
26/26 smokes verdes (57 assertions) — local py 3.14, CI py 3.11 + 3.12.

## Padrão estabelecido
Fonte única → re-export deprecated → smoke test ≥8 casos → delivery em docs/memoria.

## Risco
Baixo. Refactors isolados, cobertos por smoke suite. CI roda em todo push/PR.
EOF
)"
```

**Por que dev e não main:** `origin/main` está 9 commits atrás de `origin/dev` (trabalho de frontend/dashboard). Abrir PR contra `main` misturaria a wave com esse trabalho anterior, criando um diff de 23 commits que o reviewer teria que separar mentalmente. Contra `dev`, o PR foca em 14 commits coerentes com a wave.

### Ação secundária (opcional) — separar os 4 pré-LESSON

Se você quiser um PR ainda mais enxuto (só wave), dá pra rebase interativo e mover `d4a7eb8`, `fd9672b`, `103d7ef`, `fd2c993` para um PR separado:

```bash
# cria branch só com os 4 pré-LESSON
git checkout -b pre-wave-fixes origin/dev
git cherry-pick fd2c993 103d7ef fd9672b d4a7eb8
git push -u origin pre-wave-fixes
gh pr create --base dev --head pre-wave-fixes --title "Pre-wave: baseline fixes"

# rebase da wave pra remover esses 4
git checkout fix/ultrareview-wave-1
git rebase --onto origin/dev <ultimo-pre-LESSON-sha> fix/ultrareview-wave-1
# (equivalente: git rebase -i origin/dev e dropar os 4)
```

**Não recomendo** a menos que você tenha política estrita de "um PR = uma temática". Os 4 fixes pré-LESSON são pequenos e contextualmente próximos da wave (hygiene + fixes), a revisão deles junto é leve.

### Ação terciária (não fazer) — PR contra main

Se fosse obrigatório `main`, precisaria:
1. Primeiro mergear `dev` → `main` via PR (9 commits de frontend).
2. Depois o PR da wave contra `main` (mesmos 14 commits finais).

Isto abre espaço pra conflito entre as duas abordagens (quem vai primeiro?) e duplica trabalho de review. Desnecessário dado que o target correto é `dev`.

## Não executado

- `git push`: **não rodado** (continua bloqueado por escopo `workflow` do PAT — ver `LESSON-PR-wave1-delivery.md`).
- `gh pr create`: **não rodado** (gh CLI segue não instalado no ambiente local).
- Nenhum commit revertido ou alterado.

## Próximos passos para você

1. Conceder escopo `workflow` ao PAT (ou `git remote set-url origin git@github.com:yukiomarcelo-beep/myo-orchestrator.git` para SSH).
2. `brew install gh && gh auth login`.
3. Decidir: PR contra `dev` (recomendação primária) ou separar pré-LESSON (secundária).
4. Me pedir pra executar — eu sigo o comando da recomendação e relato PR number, URL, status do CI.
