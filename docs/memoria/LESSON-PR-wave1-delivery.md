# PR Wave-1 — Delivery Report

**Branch:** `fix/ultrareview-wave-1`
**Data:** 2026-04-19
**Status final:** `STATUS: BLOCKED` (push rejeitado + `gh` ausente)

---

## Sugerido

1. Confirmar working tree limpa.
2. Listar commits da branch vs `main`.
3. Push `fix/ultrareview-wave-1` se necessário.
4. Aguardar CI; se vermelho, parar.
5. Abrir PR via `gh pr create` com título e body especificados.
6. Reportar número/URL/status.

## Feito

1. `git status --short` → **vazio** (working tree limpa). ✓
2. `git log origin/main..fix/ultrareview-wave-1 --oneline` → **22 commits** (não 5 — ver Erro #1).
3. `git push -u origin fix/ultrareview-wave-1` → **rejeitado**. Detalhes abaixo.
4. CI não rodou (push falhou).
5. PR não criado.

## Erros (blockers)

### ❌ BLOCKER 1 — Push rejeitado por escopo `workflow` ausente no token

```
! [remote rejected] fix/ultrareview-wave-1 -> fix/ultrareview-wave-1
  (refusing to allow a Personal Access Token to create or update
   workflow `.github/workflows/smoke.yml` without `workflow` scope)
```

O PAT atual (HTTPS `https://github.com/yukiomarcelo-beep/myo-orchestrator.git`) não tem o escopo `workflow`, exigido pelo GitHub sempre que um push cria/altera arquivos em `.github/workflows/`. O commit `3a891a9` (FASE 3 CI) é justamente a adição do `.github/workflows/smoke.yml`. Enquanto o token estiver sem esse escopo, **nenhum push que inclua esse commit passa**.

### ❌ BLOCKER 2 — `gh` CLI não instalado

```
$ gh auth status
zsh: command not found: gh
```

Sem `gh`, não consigo criar PR via CLI conforme o prompt pediu (`gh pr create`). Mesmo que o push funcionasse, eu não teria como abrir o PR por conta. `brew` está disponível (`/usr/local/bin/brew`), então a instalação é viável.

### ⚠️ Observação — divergência main ↔ branch

`origin/main..fix/ultrareview-wave-1` retorna **22 commits**, não 5. A branch foi criada bem antes desta sessão e inclui toda a linha de trabalho pré-LESSON (baseline nexara, dashboard, react, subprocess drain, etc.). O prompt mencionou "5 commits" mas a realidade do git mostra mais. Por contexto: há uma branch `origin/dev` intermediária — `origin/dev..fix/ultrareview-wave-1` tem 13 commits. Pode ser intencional (PR grande de consolidação) ou pode ser que o target correto seja `dev`, não `main`. **Registrado mas não bloqueante** — assumo `main` como target conforme instrução literal.

Lista dos 22 commits (main até HEAD da wave):

```
649bb23 docs: FASE 2+3 delivery (higiene + CI smoke)            ← sessão atual
3a891a9 ci: smoke tests on every push and PR                    ← sessão atual (BLOQUEIA push)
3c41e60 chore: gitignore .bak files, archive old backups        ← sessão atual
72ad50f docs+tests: legacy pytest adapter + delivery            ← sessão atual
aa0fc16 LESSON-006: consolidate verification_logger             ← sessão atual
2c7fc01 LESSON-005: consolidate policy_adapter                  ← sessão atual
01b6cc4 LESSON-003: runtime guard                               ← sessão anterior
8629c3d LESSON-004: consolidate AuditLog                        ← sessão anterior
ed1a94f LESSON-002: normalize execution_context                 ← sessão anterior
d4a7eb8 fix: drain subprocess stdout/stderr                     ← pré-sessão
fd9672b style: apply black formatter to api/myo_server.py       ← pré-sessão
103d7ef fix: resolve dead code in auth/telegram/pnl handlers    ← pré-sessão
fd2c993 feat: baseline — nexara, observability, security        ← pré-sessão
6160a26 fix: corrige 6 bugs de indentação pré-existentes
f6543a3 feat: integra dashboard-kit — tema roxo profundo
b25f5bd feat: conecta React ao backend real
01f6261 feat: dashboard design upgrade
a0182b1 feat: frontend React — decision engine
8d64253 feat: intelligence panel + KPI insights
2bdbe80 refactor: reorganiza estrutura do projeto MYO
ea2180c feat: adiciona modo OFFLINE
79db2cc fix: corrige erros de sintaxe em 18 engines
```

## Correções — ações que você precisa tomar

Nenhum patch autônomo é possível sem você. Duas coisas dependem de ação sua:

### 1. Conceder escopo `workflow` ao token

No GitHub:
1. **Settings → Developer settings → Personal access tokens** (o token usado por este remote HTTPS).
2. Editar o token e marcar o escopo **`workflow`** (além dos que já tem).
3. Salvar. O token mesmo não muda, só ganha permissão nova.

Alternativas mais envolvidas (não recomendadas a menos que você queira evitar escopo extra):
- **(B)** `git push` via SSH em vez de HTTPS — SSH não passa pelas restrições do PAT. Precisaria trocar o remote: `git remote set-url origin git@github.com:yukiomarcelo-beep/myo-orchestrator.git`.
- **(C)** Separar `3a891a9` em um segundo PR depois. Daria pra push de `fix/ultrareview-wave-1~1` (HEAD sem o CI). Mas isso fragmenta a wave e perde o valor de ter CI rodando no próprio PR.

### 2. Instalar `gh`

```
brew install gh
gh auth login
```

Sem isso, só dá pra abrir o PR pela interface web.

## Plano para retomada (quando desbloquear)

Assim que você aplicar #1 e #2, eu consigo fazer sem perguntar:

```
git push -u origin fix/ultrareview-wave-1        # esperado: OK
# CI dispara em 'fix/ultrareview-wave-1', ubuntu-latest, py 3.11 + 3.12
# Aguardo workflow run terminar. Se vermelho, paro e reporto.
gh pr create \
  --base main \
  --head fix/ultrareview-wave-1 \
  --title "Ultrareview Wave 1: LESSONS 002-006 + higiene + CI smoke" \
  --body "<conforme especificado>"
# Relato: PR number, URL, conclusion do smoke workflow.
```

Se você preferir abrir o PR pela UI do GitHub mesmo depois de push funcionar, também está ok — eu posso só reportar o status do CI.

## Estado atual

- **Commits:** zero novos nesta etapa. Os 5 commits de FASE 1/2/3 permanecem em HEAD local.
- **Working tree:** limpa.
- **Push:** falhou, nada subiu pro remote.
- **PR:** não existe.
- **Tasks:** mantidas; pode reabrir #5 ou criar nova quando desbloquear.
