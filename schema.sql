-- =============================================================================
-- schema.sql — NOC Telemetry: TimescaleDB schema
-- Ejecutar como superuser o con permisos CREATE en la DB target.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Extensiones
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- -----------------------------------------------------------------------------
-- 2. Tipos ENUM  (evitan VARCHAR libre y ahorran ~30% de espacio en hot columns)
-- -----------------------------------------------------------------------------
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
-- 3. Tabla de dimensiones: dispositivos (lookup estático, sin series)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    hostname    TEXT        PRIMARY KEY,
    ip          INET        NOT NULL,
    role        device_role NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO devices (hostname, ip, role) VALUES
    ('core-rtr-01',  '10.0.0.1', 'core-router'),
    ('core-rtr-02',  '10.0.0.2', 'core-router'),
    ('dist-sw-01',   '10.0.1.1', 'distribution-sw'),
    ('dist-sw-02',   '10.0.1.2', 'distribution-sw'),
    ('access-sw-01', '10.0.2.1', 'access-sw')
ON CONFLICT (hostname) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 4. Tabla principal de telemetría (será convertida a hypertable)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS network_telemetry (
    -- Eje temporal (partition key obligatorio para hypertable)
    ts                  TIMESTAMPTZ     NOT NULL,

    -- Dimensiones (FK a devices; hostname incluido inline para query speed)
    hostname            TEXT            NOT NULL REFERENCES devices(hostname),
    ip                  INET            NOT NULL,
    role                device_role     NOT NULL,

    -- Clasificación del evento
    severity            severity_level  NOT NULL,
    message             TEXT,

    -- Métricas numéricas
    cpu_pct             DOUBLE PRECISION CHECK (cpu_pct BETWEEN 0 AND 100),
    latency_ms          DOUBLE PRECISION CHECK (latency_ms >= 0),
    packet_loss_pct     DOUBLE PRECISION CHECK (packet_loss_pct BETWEEN 0 AND 100),

    -- Estado de interfaz
    interface           TEXT,
    iface_status        iface_state,
    peer_ip             INET
);

-- -----------------------------------------------------------------------------
-- 5. Convertir a hypertable particionada por tiempo (chunk = 1 día)
-- -----------------------------------------------------------------------------
SELECT create_hypertable(
    'network_telemetry',
    'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

-- -----------------------------------------------------------------------------
-- 6. Índices optimizados para los patrones de query de Grafana
-- -----------------------------------------------------------------------------

-- (a) Filtro por hostname en ventana temporal → panel por dispositivo
CREATE INDEX IF NOT EXISTS idx_tel_hostname_ts
    ON network_telemetry (hostname, ts DESC);

-- (b) Filtro por severidad → panel de alertas / conteo de eventos
CREATE INDEX IF NOT EXISTS idx_tel_severity_ts
    ON network_telemetry (severity, ts DESC);

-- (c) Filtro combinado severity + hostname → correlación en dashboards
CREATE INDEX IF NOT EXISTS idx_tel_sev_host_ts
    ON network_telemetry (severity, hostname, ts DESC);

-- -----------------------------------------------------------------------------
-- 7. Compresión automática (chunks > 7 días se comprimen en background)
--    Ahorro típico: 85-95% en columnas numéricas de telemetría
-- -----------------------------------------------------------------------------
ALTER TABLE network_telemetry
    SET (
        timescaledb.compress,
        timescaledb.compress_orderby   = 'ts DESC',
        timescaledb.compress_segmentby = 'hostname, severity'
    );

SELECT add_compression_policy(
    'network_telemetry',
    compress_after => INTERVAL '7 days',
    if_not_exists  => TRUE
);

-- -----------------------------------------------------------------------------
-- 8. Retención automática de datos (ajustar según SLA del NOC)
-- -----------------------------------------------------------------------------
SELECT add_retention_policy(
    'network_telemetry',
    drop_after    => INTERVAL '90 days',
    if_not_exists => TRUE
);

-- -----------------------------------------------------------------------------
-- 9. Views para Grafana (datasource directo sin CTEs en cada panel)
-- -----------------------------------------------------------------------------

-- 9a. Vista de series temporales por dispositivo (Time series panel)
CREATE OR REPLACE VIEW v_telemetry_ts AS
SELECT
    ts,
    hostname,
    role::TEXT              AS role,
    severity::TEXT          AS severity,
    cpu_pct,
    latency_ms,
    packet_loss_pct,
    interface,
    iface_status::TEXT      AS iface_status
FROM network_telemetry;

-- 9b. Conteo de eventos por severidad en ventana deslizante (Stat / Bar panel)
CREATE OR REPLACE VIEW v_event_counts AS
SELECT
    time_bucket('5 minutes', ts)    AS bucket,
    hostname,
    severity::TEXT                  AS severity,
    COUNT(*)                        AS event_count
FROM network_telemetry
GROUP BY bucket, hostname, severity;

-- 9c. Últimas métricas por dispositivo (Gauge / Stat panel — "current state")
CREATE OR REPLACE VIEW v_device_latest AS
SELECT DISTINCT ON (hostname)
    ts,
    hostname,
    severity::TEXT      AS severity,
    cpu_pct,
    latency_ms,
    packet_loss_pct,
    iface_status::TEXT  AS iface_status
FROM network_telemetry
ORDER BY hostname, ts DESC;

-- 9d. Anomalías: eventos WARN+ en la última hora (tabla de alertas en Grafana)
CREATE OR REPLACE VIEW v_recent_anomalies AS
SELECT
    ts,
    hostname,
    severity::TEXT      AS severity,
    message,
    cpu_pct,
    latency_ms,
    packet_loss_pct,
    interface,
    iface_status::TEXT  AS iface_status
FROM network_telemetry
WHERE severity IN ('WARN', 'ERROR', 'CRITICAL')
  AND ts >= NOW() - INTERVAL '1 hour'
ORDER BY ts DESC;
