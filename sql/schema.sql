-- =============================================================================
-- schema.sql — NOC Telemetry: TimescaleDB schema (Fase 4 — multi-región)
-- Ejecutar como superuser o con permisos CREATE en la DB target.
-- Idempotente: seguro re-ejecutar sobre una base ya inicializada.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

DO $$ BEGIN
    CREATE TYPE severity_level AS ENUM ('INFO', 'WARN', 'ERROR', 'CRITICAL');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE device_role AS ENUM ('core-router', 'distribution-sw', 'access-sw');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE iface_state AS ENUM ('UP', 'DOWN');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- -----------------------------------------------------------------------------
-- 3. Tabla de dimensiones: dispositivos (+ región)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    hostname    TEXT        PRIMARY KEY,
    ip          INET        NOT NULL,
    role        device_role NOT NULL,
    region      TEXT        NOT NULL DEFAULT 'us-east',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE devices ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us-east';

-- Dispositivos existentes (us-east, sin cambio de hostname → no rompe dashboards)
INSERT INTO devices (hostname, ip, role, region) VALUES
    ('core-rtr-01',  '10.0.0.1', 'core-router',      'us-east'),
    ('core-rtr-02',  '10.0.0.2', 'core-router',      'us-east'),
    ('dist-sw-01',   '10.0.1.1', 'distribution-sw',  'us-east'),
    ('dist-sw-02',   '10.0.1.2', 'distribution-sw',  'us-east'),
    ('access-sw-01', '10.0.2.1', 'access-sw',        'us-east')
ON CONFLICT (hostname) DO NOTHING;

-- Nuevos dispositivos — eu-west
INSERT INTO devices (hostname, ip, role, region) VALUES
    ('euw1-core-rtr-01',  '10.20.0.1', 'core-router',     'eu-west'),
    ('euw1-core-rtr-02',  '10.20.0.2', 'core-router',     'eu-west'),
    ('euw1-dist-sw-01',   '10.20.1.1', 'distribution-sw', 'eu-west'),
    ('euw1-dist-sw-02',   '10.20.1.2', 'distribution-sw', 'eu-west'),
    ('euw1-access-sw-01', '10.20.2.1', 'access-sw',       'eu-west')
ON CONFLICT (hostname) DO NOTHING;

-- Nuevos dispositivos — sa-south
INSERT INTO devices (hostname, ip, role, region) VALUES
    ('sas1-core-rtr-01',  '10.30.0.1', 'core-router',     'sa-south'),
    ('sas1-core-rtr-02',  '10.30.0.2', 'core-router',     'sa-south'),
    ('sas1-dist-sw-01',   '10.30.1.1', 'distribution-sw', 'sa-south'),
    ('sas1-dist-sw-02',   '10.30.1.2', 'distribution-sw', 'sa-south'),
    ('sas1-access-sw-01', '10.30.2.1', 'access-sw',       'sa-south')
ON CONFLICT (hostname) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 4. Tabla principal de telemetría (+ región)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS network_telemetry (
    ts                  TIMESTAMPTZ     NOT NULL,
    hostname            TEXT            NOT NULL REFERENCES devices(hostname),
    ip                  INET            NOT NULL,
    role                device_role     NOT NULL,
    region              TEXT            NOT NULL DEFAULT 'us-east',
    severity            severity_level  NOT NULL,
    message             TEXT,
    cpu_pct             DOUBLE PRECISION CHECK (cpu_pct BETWEEN 0 AND 100),
    latency_ms          DOUBLE PRECISION CHECK (latency_ms >= 0),
    packet_loss_pct     DOUBLE PRECISION CHECK (packet_loss_pct BETWEEN 0 AND 100),
    interface           TEXT,
    iface_status        iface_state,
    peer_ip             INET
);

ALTER TABLE network_telemetry ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us-east';

SELECT create_hypertable(
    'network_telemetry',
    'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

-- -----------------------------------------------------------------------------
-- 6. Índices (+ región)
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_tel_hostname_ts   ON network_telemetry (hostname, ts DESC);
CREATE INDEX IF NOT EXISTS idx_tel_severity_ts    ON network_telemetry (severity, ts DESC);
CREATE INDEX IF NOT EXISTS idx_tel_sev_host_ts    ON network_telemetry (severity, hostname, ts DESC);
CREATE INDEX IF NOT EXISTS idx_tel_region_ts      ON network_telemetry (region, ts DESC);

-- -----------------------------------------------------------------------------
-- 7. Compresión (segmentby ahora incluye región)
-- -----------------------------------------------------------------------------
ALTER TABLE network_telemetry
    SET (
        timescaledb.compress,
        timescaledb.compress_orderby   = 'ts DESC',
        timescaledb.compress_segmentby = 'hostname, severity, region'
    );

SELECT add_compression_policy(
    'network_telemetry',
    compress_after => INTERVAL '7 days',
    if_not_exists  => TRUE
);

SELECT add_retention_policy(
    'network_telemetry',
    drop_after    => INTERVAL '90 days',
    if_not_exists => TRUE
);

-- -----------------------------------------------------------------------------
-- 9. Views para Grafana (+ región, con filtro/agregación disponible por región)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_telemetry_ts AS
SELECT
    ts, hostname, region,
    role::TEXT              AS role,
    severity::TEXT          AS severity,
    cpu_pct, latency_ms, packet_loss_pct, interface,
    iface_status::TEXT      AS iface_status
FROM network_telemetry;

CREATE OR REPLACE VIEW v_event_counts AS
SELECT
    time_bucket('5 minutes', ts)    AS bucket,
    hostname, region,
    severity::TEXT                  AS severity,
    COUNT(*)                        AS event_count
FROM network_telemetry
GROUP BY bucket, hostname, region, severity;

CREATE OR REPLACE VIEW v_device_latest AS
SELECT DISTINCT ON (hostname)
    ts, hostname, region,
    severity::TEXT      AS severity,
    cpu_pct, latency_ms, packet_loss_pct,
    iface_status::TEXT  AS iface_status
FROM network_telemetry
ORDER BY hostname, ts DESC;

CREATE OR REPLACE VIEW v_recent_anomalies AS
SELECT
    ts, hostname, region,
    severity::TEXT      AS severity,
    message, cpu_pct, latency_ms, packet_loss_pct, interface,
    iface_status::TEXT  AS iface_status
FROM network_telemetry
WHERE severity IN ('WARN', 'ERROR', 'CRITICAL')
  AND ts >= NOW() - INTERVAL '1 hour'
ORDER BY ts DESC;

-- 9e. Nueva vista — comparativa de salud entre regiones
CREATE OR REPLACE VIEW v_region_health AS
SELECT
    region,
    time_bucket('5 minutes', ts)   AS bucket,
    COUNT(*) FILTER (WHERE severity = 'CRITICAL') AS critical_count,
    ROUND(AVG(latency_ms)::numeric, 2)             AS avg_latency_ms,
    ROUND(AVG(cpu_pct)::numeric, 2)                AS avg_cpu_pct
FROM network_telemetry
GROUP BY region, bucket;