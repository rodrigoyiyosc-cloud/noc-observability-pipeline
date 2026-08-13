CREATE TABLE IF NOT EXISTS incident_logs (
    id              BIGSERIAL PRIMARY KEY,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT,
    alert_name      TEXT,
    payload         JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incident_logs_received_at ON incident_logs (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_incident_logs_status       ON incident_logs (status);
CREATE INDEX IF NOT EXISTS idx_incident_logs_alert_name   ON incident_logs (alert_name);
CREATE INDEX IF NOT EXISTS idx_incident_logs_payload_gin  ON incident_logs USING GIN (payload);