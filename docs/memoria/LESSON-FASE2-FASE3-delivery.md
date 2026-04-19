# FASE 2 + FASE 3 — Delivery Report

**Branch:** `fix/ultrareview-wave-1`
**Data:** 2026-04-19
**Status final:** `DONE`

---

## Sugerido (ordem executada)

1. **FASE 2 — Higiene:** `.gitignore` para `.bak`, mover 8 backups para `.archive/bak_2026-04-19/`, trackear `docs/memoria/`, commit chore.
2. **FASE 3 — CI smoke:** criar `.github/workflows/smoke.yml` com pytest em push+PR, matrix Python 3.11/3.12, commit CI.
3. Este delivery + commit final.

## Feito

### Commits criados

| SHA | Mensagem |
|---|---|
| `3c41e60` | `chore: gitignore .bak files, archive old backups, track docs/memoria` |
| `3a891a9` | `ci: smoke tests on every push and PR` |
| _(próximo)_ | `docs: FASE 2+3 delivery` |

### FASE 2 — arquivos tocados

**`.gitignore`** — adicionado bloco ao final (preserva entradas existentes):
```
# Backups locais (archives curados ficam em .archive/ e sao versionados)
*.bak
*.bak_*
*.broken.bak
!.archive/
!.archive/**
```
Whitelist `!.archive/**` permite arquivar backups versionados em `.archive/` sem colidir com regra geral `*.bak`. Validado com `git check-ignore -v`.

**`.archive/bak_2026-04-19/`** (novo) — recebeu os 8 backups que estavam soltos:

| Origem → Destino |
|---|
| `agents/claude_runner.py.v1.bak` |
| `agents/claude_runner_v2.py.bak_lesson003` |
| `core/execution_control.py.bak_lesson004` |
| `policies/policy_adapter.py.broken.bak` |
| `security_layer.py.bak_lesson004` |
| `utils/result_ingestor.py.bak_lesson002` |
| `utils/verification_engine.py.broken.bak` |
| `utils/verification_logger.py.broken.bak` |

Todos movidos com `mv` (eram untracked, git não tinha histórico a preservar) e depois `git add .archive/`. Working tree limpa de `.bak` fora de `.archive/`.

**`docs/memoria/LESSONS.md`** — único arquivo untracked em `docs/memoria/` (o `LESSON-005-006-CI-delivery.md` já havia sido commitado em `72ad50f`). Agora trackeado.

### FASE 3 — arquivos tocados

**`.github/workflows/smoke.yml`** (novo):

```yaml
name: smoke
on:
  push:
    branches: ["**"]
  pull_request:
    branches: ["**"]
jobs:
  pytest:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
      - run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest
      - run: pytest tests/ -q
```

Comportamento:
- **Triggers:** push e pull_request em qualquer branch (`["**"]`).
- **Matrix:** Python 3.11 e 3.12 em paralelo, `fail-fast: false` (cada versão reporta independentemente).
- **Install:** `requirements.txt` + `pytest`. `pytest` não consta em `requirements.txt` localmente, então o workflow instala explicitamente — dívida técnica registrada (idealmente mover para `requirements-dev.txt`).
- **Comando final:** `pytest tests/ -q` cobre 26 nodes (11 policy_adapter + 12 verification_logger + 3 legacy adapters → 57 assertions totais).

### Contagem final de testes

```
$ venv/bin/pytest tests/ -q
...
26 passed, 4 warnings in 1.48s
```

Baseline preservado do delivery anterior — nem FASE 2 nem FASE 3 modificaram código de produção ou de teste, apenas estrutura de repo e CI.

## Erros (no caminho)

1. **Nenhum arquivo `.bak` faltou.** Os 8 identificados estavam todos presentes. `mv` não gerou erro.

2. **Whitelist de `.gitignore` exigiu atenção.** A regra `*.bak` ignoraria também arquivos dentro de `.archive/`. Adicionadas duas linhas `!.archive/` e `!.archive/**` — a segunda é necessária porque a primeira sozinha só libera o diretório, não o conteúdo. Validado com `git check-ignore -v .archive/bak_2026-04-19/claude_runner.py.v1.bak` → confirma whitelist ativa.

3. **Projeto sem `pyproject.toml`/`setup.py`.** Sem declaração formal de versão Python suportada. O venv local roda 3.14; o `requirements.txt` comenta "Python 3.8+" informal. Escolhi matrix 3.11/3.12 como range conservador — evita 3.14 (ainda não comum em runners do GH) e cobre duas versões LTS modernas. Se o projeto for adotar um `pyproject.toml` formal no futuro, matrix pode ser atualizada.

4. **`pytest` fora do `requirements.txt`.** Registrado como dívida técnica no delivery anterior; workflow instala explicitamente para destravar FASE 3. Fix correto seria criar `requirements-dev.txt` com `pytest`, mas está fora do escopo desta wave.

5. **Pre-commit hook sem config (recorrente).** Usei `PRE_COMMIT_ALLOW_NO_CONFIG=1` em ambos os commits da FASE 2 e FASE 3. Solução oficial do próprio pre-commit; não é bypass de hooks.

## Correções / Patches aplicados

- **`.gitignore` whitelist dupla** (`!.archive/` + `!.archive/**`): necessária para o git aplicar exclusão antes de entrar no diretório e depois permitir o conteúdo.
- **CI sem dependência declarada de pytest**: workaround instalando `pytest` explicitamente no step de install, até `requirements-dev.txt` ser criado em wave futura.

## Observações para waves futuras

- **`requirements-dev.txt`:** separar deps de teste (`pytest`). Hoje o workflow instala pytest "por fora" do requirements.txt.
- **Branch protection:** `.github/workflows/smoke.yml` só _reporta_ status; bloqueio de merge depende de configuração manual em **Settings → Branches → Protection rules** no GitHub (selecionar o check `pytest` como required). Fora do escopo de código.
- **DeprecationWarning `datetime.utcnow()`** em `utils/verification_logger.py:59` continua visível como 4 warnings no pytest — fix trivial (`datetime.now(timezone.utc)`), deixado para um LESSON dedicado.
- **Unificar smokes legacy:** hoje passam via `tests/test_legacy_smokes.py` (subprocess adapter). Refatorar LESSON-002/003/004 para funções `test_*` nativas elimina o adapter.
- **Considerar pinar actions com SHA:** `actions/checkout@v4` e `actions/setup-python@v5` estão em tags móveis. Pinar com SHA aumenta supply-chain safety, mas custa manutenção — decisão do time.

## Estado final

- Working tree: limpa. `git status` sem surpresas.
- Suite local: `pytest tests/ -q` → **26 passed, 4 warnings**.
- CI: workflow criado, será disparado no próximo push/PR.
- Branch: `fix/ultrareview-wave-1`, **5 commits** à frente do ponto de partida desta sessão:
  - `2c7fc01` LESSON-005
  - `aa0fc16` LESSON-006
  - `72ad50f` docs+tests adapter
  - `3c41e60` chore higiene
  - `3a891a9` ci smoke
