-- =============================================================================
-- incident_views_fix.sql — FIX: MTTR negativo por reuso de fingerprint
--
-- BUG: fingerprint es estable por (rule + labels), no por ciclo de incidente.
-- Si una misma alerta (mismo hostname+rule) hace firing->resolved->firing de
-- nuevo, MIN(starts_at) / MIN(received_at) agrupados solo por fingerprint
-- mezclan ciclos distintos: toma el started_at del ciclo N y el resolved_at
-- del ciclo N-1 (o cualquier otro), dando resolved_at < started_at.
--
-- FIX: emparejar cada evento 'firing' con el evento 'resolved' del MISMO
-- fingerprint que ocupa la misma posición cronológica (ROW_NUMBER por
-- fingerprint, ordenado por tiempo), asumiendo alternancia firing/resolved
-- estricta por rule instance -- que es como Alertmanager/Grafana la emite.
--
-- Ejecutar contra la DB "noc" DESPUÉS de incident_views.sql (reemplaza la
-- vista v_incident_mttr con CREATE OR REPLACE).
-- =============================================================================

CREATE OR REPLACE VIEW v_incident_mttr AS
WITH firing AS (
    SELECT
        fingerprint,
        hostname,
        severity,
        alert_name,
        started_at,
        ROW_NUMBER() OVER (PARTITION BY fingerprint ORDER BY started_at) AS rn
    FROM (
        SELECT DISTINCT
            fingerprint, hostname, severity, alert_name, starts_at AS started_at
        FROM v_incident_events
        WHERE status = 'firing' AND fingerprint IS NOT NULL
    ) d
),
resolved AS (
    SELECT
        fingerprint,
        resolved_at,
        ROW_NUMBER() OVER (PARTITION BY fingerprint ORDER BY resolved_at) AS rn
    FROM (
        SELECT DISTINCT
            fingerprint, received_at AS resolved_at
        FROM v_incident_events
        WHERE status = 'resolved' AND fingerprint IS NOT NULL
    ) d
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
JOIN resolved r ON r.fingerprint = f.fingerprint AND r.rn = f.rn
WHERE r.resolved_at > f.started_at;


-- =============================================================================
-- FIX del panel "Historial de Incidentes Recientes" (mismo bug, query inline
-- duplicada en panels_postmortem.sql y en el dashboard JSON id=4/panel "Historial").
-- Usa LEFT JOIN (no INNER) para seguir mostrando incidentes aún en FIRING
-- (resolved_at NULL -> MTTR NULL, no se filtran).
-- =============================================================================

-- Pega este rawSql en el panel "Historial de Incidentes Recientes"
-- (reemplaza el bloque SELECT actual del panel id=4 en noc-postmortem-dashboard.json):
--
-- SELECT
--     f.started_at   AS "Started",
--     f.hostname     AS "Device",
--     f.severity     AS "Severity",
--     f.alert_name   AS "Alert",
--     ls.status      AS "Current status",
--     r.resolved_at  AS "Resolved",
--     CASE WHEN r.resolved_at IS NOT NULL
--          THEN EXTRACT(EPOCH FROM (r.resolved_at - f.started_at))
--     END AS "MTTR (s)"
-- FROM (
--     SELECT fingerprint, hostname, severity, alert_name, starts_at AS started_at,
--            ROW_NUMBER() OVER (PARTITION BY fingerprint ORDER BY starts_at) AS rn
--     FROM (
--         SELECT DISTINCT fingerprint, hostname, severity, alert_name, starts_at
--         FROM v_incident_events
--         WHERE status = 'firing' AND fingerprint IS NOT NULL
--     ) d
-- ) f
-- LEFT JOIN (
--     SELECT fingerprint, received_at AS resolved_at,
--            ROW_NUMBER() OVER (PARTITION BY fingerprint ORDER BY received_at) AS rn
--     FROM (
--         SELECT DISTINCT fingerprint, received_at
--         FROM v_incident_events
--         WHERE status = 'resolved' AND fingerprint IS NOT NULL
--     ) d
-- ) r ON r.fingerprint = f.fingerprint AND r.rn = f.rn
-- LEFT JOIN v_incident_latest_status ls ON ls.fingerprint = f.fingerprint
-- WHERE
--     $__timeFilter(f.started_at)
--     AND f.hostname IN ($hostname)
-- ORDER BY f.started_at DESC
-- LIMIT 100;