-- SETUP DO AUDIT LOG — rodar uma vez no PostgreSQL
-- Compatible com: PostgreSQL 13+
-- Uso: psql $DATABASE_URL -f scripts/setup_audit_log.sql

-- Extensão para gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Tabela principal
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    entry_id    UUID NOT NULL DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL,
    agent       TEXT NOT NULL,
    action      TEXT NOT NULL,
    decision    TEXT NOT NULL CHECK (decision IN ('ALLOW','BLOCK','HUMAN')),
    input_hash  TEXT NOT NULL,
    output_hash TEXT,
    reason      TEXT,
    confidence  FLOAT,
    cost_usd    FLOAT DEFAULT 0,
    prev_hash   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Imutabilidade via RULES
CREATE OR REPLACE RULE audit_log_no_update AS
    ON UPDATE TO audit_log DO INSTEAD NOTHING;

CREATE OR REPLACE RULE audit_log_no_delete AS
    ON DELETE TO audit_log DO INSTEAD NOTHING;

-- Índices
CREATE INDEX IF NOT EXISTS idx_audit_session  ON audit_log (session_id);
CREATE INDEX IF NOT EXISTS idx_audit_agent    ON audit_log (agent);
CREATE INDEX IF NOT EXISTS idx_audit_decision ON audit_log (decision);
CREATE INDEX IF NOT EXISTS idx_audit_created  ON audit_log (created_at DESC);

-- View para auditoria LGPD — "quem acessou o quê e quando"
CREATE OR REPLACE VIEW lgpd_audit AS
SELECT
    entry_id,
    session_id,
    agent,
    action,
    decision,
    reason,
    confidence,
    cost_usd,
    created_at
FROM audit_log
ORDER BY created_at DESC;

-- View de custo diário
CREATE OR REPLACE VIEW daily_costs AS
SELECT
    DATE(created_at)       AS day,
    agent,
    COUNT(*)               AS total_calls,
    SUM(cost_usd)          AS total_cost_usd,
    AVG(confidence)        AS avg_confidence,
    SUM(CASE WHEN decision = 'BLOCK' THEN 1 ELSE 0 END) AS blocks,
    SUM(CASE WHEN decision = 'HUMAN' THEN 1 ELSE 0 END) AS escalations
FROM audit_log
GROUP BY DATE(created_at), agent
ORDER BY day DESC, total_cost_usd DESC;

-- Verifica se imutabilidade está funcionando (deve retornar 0 após tentativa)
-- UPDATE audit_log SET reason = 'teste' WHERE id = 1;
-- SELECT * FROM audit_log WHERE id = 1; -- reason não muda
