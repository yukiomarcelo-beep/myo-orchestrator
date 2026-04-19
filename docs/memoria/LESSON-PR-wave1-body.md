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
