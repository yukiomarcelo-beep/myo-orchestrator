# LESSON-005/006 + CI — Delivery Report

**Branch:** `fix/ultrareview-wave-1`
**Data:** 2026-04-19
**Status final:** `DONE` (FASE 1 fechada; FASE 2 e FASE 3 não iniciadas, conforme instruído)

---

## Sugerido (ordem executada)

1. **FASE 1 — LESSON-005 (`policies/policy_adapter.py`)**: consolidar fonte canônica, criar smoke test cobrindo invariantes (≥8), commit isolado.
2. **FASE 1 — LESSON-006 (`utils/verification_logger.py`)**: idem, commit separado.
3. **Suite completa**: `pytest tests/ -q` verde (34 atuais + novos).
4. Atualizar este delivery (Feito/Erros/Correções, remover seção A/B/C).
5. Commit final do delivery.

FASE 2 (higiene) e FASE 3 (CI) **não iniciadas**, conforme "PARAR após passo 5".

## Feito

### Commits criados (nesta branch, nesta sessão)

| SHA | Mensagem |
|---|---|
| `2c7fc01` | `LESSON-005: consolidate policy_adapter canonical source` |
| `aa0fc16` | `LESSON-006: consolidate verification_logger canonical source` |
| _(próximo)_ | `docs+tests: legacy pytest adapter + delivery update` |

### Arquivos tocados

**LESSON-005 (`2c7fc01`):**
- `policies/policy_adapter.py` (412 linhas, 9 funções públicas) — reformatação consistente (indent 4sp, banners `# ===`, alinhamento de comentários), rename de variável local `f` → `f_count` em `compute_topic_failure_by_context()`. API pública inalterada.
- `tests/test_policy_adapter_smoke.py` (new) — **11 casos** pytest.

**LESSON-006 (`aa0fc16`):**
- `utils/verification_logger.py` (162 linhas, 2 funções + 1 classe) — removidas **1.983 linhas de `pass`** consecutivas (corrupção de ferramenta de edição anterior). `getattr(pack, "sources", [])` defensivo.
- `tests/test_verification_logger_smoke.py` (new) — **12 casos** pytest.

**Delivery + adapter (próximo commit):**
- `tests/test_legacy_smokes.py` (new) — adapter pytest que invoca os 3 smokes LESSON-002/003/004 via subprocess. Mantém scripts standalone originais intactos. **3 test nodes** em pytest, 34 assertions internas.
- `docs/memoria/LESSON-005-006-CI-delivery.md` — este arquivo.

### Contagem final de testes

```
$ venv/bin/pytest tests/ -q
...
26 passed, 4 warnings in 0.75s
```

| Suite | Nodes pytest | Assertions |
|---|---|---|
| `test_policy_adapter_smoke.py` | 11 | 11 |
| `test_verification_logger_smoke.py` | 12 | 12 |
| `test_legacy_smokes.py` (adapter) | 3 | 34 (13+9+12 via subprocess) |
| **Total** | **26 nodes** | **57 assertions** |

Todos os 3 smokes legacy continuam executáveis standalone (`python3 tests/test_*.py`) para compatibilidade com o padrão LESSON-002/003/004.

## Erros (no caminho)

1. **`pytest` ausente.** Não estava instalado nem no venv, nem no `requirements.txt`. Tentei instalar global: bloqueado por PEP 668 (externally-managed-environment). Resolvido com `venv/bin/pip install pytest --quiet` (pytest 9.0.3). Nota: não adicionei ao `requirements.txt` por estar fora do escopo da FASE 1.

2. **Pre-commit hook sem config.** `git commit` falhou em ambos os commits com `No .pre-commit-config.yaml file was found`. O próprio pre-commit sugere `PRE_COMMIT_ALLOW_NO_CONFIG=1` como solução oficial (não é bypass, é reconhecimento explícito de "sem hooks configurados"). Usei a variável inline. Se o repositório deveria ter `.pre-commit-config.yaml`, é item de higiene separado.

3. **Tests legacy não descobertos por pytest.** `pytest tests/ -q` sem o adapter retornava `no tests ran in 0.09s` porque os smokes LESSON-002/003/004 são scripts standalone com `run()`, sem funções `test_*`. Resolvido com `tests/test_legacy_smokes.py` — 3 wrappers que rodam os scripts como subprocess e `assert returncode == 0`. Zero churn nos arquivos originais.

4. **DeprecationWarning silencioso em `verification_logger.py`.** 4 warnings emitidos pelo uso de `datetime.utcnow()` (deprecated a partir do Python 3.12). Código ainda funciona, testes passam, mas é dívida técnica. **Fora do escopo da FASE 1** — registrado aqui para um LESSON futuro (fix trivial: `datetime.now(timezone.utc)` como já feito em `policy_adapter._snapshot_policy`).

## Correções / Patches aplicados

- **`policy_adapter.compute_topic_failure_by_context`**: shadow de file handle `f` resolvido via rename para `f_count`. Commit `2c7fc01`.
- **`verification_logger._build_event`**: acesso defensivo a `pack.sources` via `getattr(pack, "sources", []) or []` — tolera `EvidencePack` de versões antigas do `verification_engine`. Commit `aa0fc16`.
- **`verification_logger.py` — deleção em massa.** As 1.983 linhas de `pass` consecutivas no HEAD anterior eram artefato de corrupção de ferramenta de edição. Foram removidas na working tree e incluídas no commit `aa0fc16`. O arquivo de referência corrompido permanece em `utils/verification_logger.py.broken.bak` (untracked, será tratado na FASE 2 de higiene).

## Observações para FASE 2 / FASE 3 (não executadas)

Registrado aqui para continuidade da wave:

- **FASE 2 — Higiene:** pendente. 8 arquivos `.bak` continuam untracked. `.gitignore` atual não cobre `*.bak`. `docs/memoria/` agora tem este delivery + `LESSONS.md` já existente.
- **FASE 3 — CI:** `.github/workflows/smoke.yml` não criado. Comando sugerido para o workflow: `venv/bin/pytest tests/ -q` (26 nodes) — já valida a suite inteira via adapter legacy.
- **Dívida técnica identificada:** (a) `datetime.utcnow()` em `verification_logger.py:59`; (b) `pytest` deveria entrar em `requirements.txt` (ou `requirements-dev.txt`); (c) considerar migrar os 3 legacy smokes para funções `test_*` nativas pytest, eliminando o adapter.

## Estado final

- Working tree: limpa exceto pelos `.bak` intocados e `docs/memoria/LESSON-005-006-CI-delivery.md` + `tests/test_legacy_smokes.py` no próximo commit.
- Suite: `pytest tests/ -q` → **26 passed, 4 warnings, 0.75s**.
- Branch: `fix/ultrareview-wave-1`, 2 commits à frente (`2c7fc01`, `aa0fc16`) + 1 próximo.
