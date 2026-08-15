-- =============================================================================
-- incident_views.sql — Vistas de postmortem sobre incident_logs (JSONB)
-- Ejecutar UNA VEZ contra la DB "noc" en TimescaleDB.
-- Depende de: incident_logs (webhook_service.sql)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Normaliza cada fila JSONB en columnas planas (1 fila = 1 evento recibido:
--    firing o resolved). Usa el fingerprint de Grafana como ID de incidente.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_incident_events AS
SELECT
    id,
    received_at,
    status,
    alert_name,
    payload -> 'alerts' -> 0 ->> 'fingerprint'                               AS fingerprint,
    COALESCE(payload -> 'alerts' -> 0 -> 'labels' ->> 'hostname', 'unknown') AS hostname,
    COALESCE(payload -> 'alerts' -> 0 -> 'labels' ->> 'severity', 'unknown') AS severity,
    payload -> 'alerts' -> 0 -> 'annotations' ->> 'summary'                  AS summary,
    (payload -> 'alerts' -> 0 ->> 'startsAt')::timestamptz                   AS starts_at
FROM incident_logs
WHERE payload ? 'alerts';

-- -----------------------------------------------------------------------------
-- 2. Empareja firing -> resolved por fingerprint y calcula MTTR real.
--    resolved_at usa received_at del evento "resolved" (más confiable que
--    endsAt del payload, que en Alertmanager viaja en '0001-01-01T00:00:00Z'
--    mientras la alerta sigue activa).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_incident_mttr AS
WITH firing AS (
    SELECT
        fingerprint,
        hostname,
        severity,
        alert_name,
        MIN(starts_at) AS started_at
    FROM v_incident_events
    WHERE status = 'firing' AND fingerprint IS NOT NULL
    GROUP BY fingerprint, hostname, severity, alert_name
),
resolved AS (
    SELECT
        fingerprint,
        MIN(received_at) AS resolved_at
    FROM v_incident_events
    WHERE status = 'resolved' AND fingerprint IS NOT NULL
    GROUP BY fingerprint
)
SELECT
    f.fingerprint,
    f.hostname,
    f.severity,
    f.alert_name,
    f.started_at,
    r.resolved_at,
    EXTRACT(EPOCH FROM (r.resolved_at - f.started_at)) AS resolution_seconds
FROM firing f
JOIN resolved r USING (fingerprint)
WHERE r.resolved_at > f.started_at;

-- -----------------------------------------------------------------------------
-- 3. Estado actual (último evento) por fingerprint → para la tabla de
--    historial ("Firing" en rojo si aún no ha llegado el resolved).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_incident_latest_status AS
SELECT DISTINCT ON (fingerprint)
    fingerprint,
    status,
    received_at
FROM v_incident_events
WHERE fingerprint IS NOT NULL
ORDER BY fingerprint, received_at DESC;