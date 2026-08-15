-- =============================================================================
-- panels_postmortem.sql — Consultas de los 4 paneles del dashboard "NOC Postmortem"
-- Datasource: TimescaleDB-NOC (uid: timescaledb_noc)
-- Requiere: incident_views.sql ya ejecutado (v_incident_events, v_incident_mttr)
-- Variable de template: $hostname (multi-value, Include All) → misma definición
--                        que panels.sql: SELECT DISTINCT hostname FROM devices
-- =============================================================================


-- =============================================================================
-- PANEL 1 — Stat: MTTR General
-- Tipo: Stat | Unit: seconds (s) | Calculation: last
-- =============================================================================
SELECT
    AVG(resolution_seconds) AS "MTTR (s)"
FROM v_incident_mttr
WHERE
    $__timeFilter(started_at)
    AND hostname IN ($hostname);


-- =============================================================================
-- PANEL 2 — Bar gauge: MTTR por dispositivo
-- Tipo: Bar gauge (horizontal) | Unit: seconds (s) | Orientation: horizontal
-- =============================================================================
SELECT
    hostname                 AS "Device",
    AVG(resolution_seconds)  AS "MTTR (s)"
FROM v_incident_mttr
WHERE
    $__timeFilter(started_at)
    AND hostname IN ($hostname)
GROUP BY hostname
ORDER BY 2 DESC;


-- =============================================================================
-- PANEL 3 — Bar chart: Conteo de incidentes por dispositivo
-- Tipo: Bar chart | Cuenta fingerprints únicos que dispararon "firing"
-- =============================================================================
SELECT
    hostname                        AS "Device",
    COUNT(DISTINCT fingerprint)     AS "Incident count"
FROM v_incident_events
WHERE
    status = 'firing'
    AND $__timeFilter(starts_at)
    AND hostname IN ($hostname)
GROUP BY hostname
ORDER BY 2 DESC;


-- =============================================================================
-- PANEL 4 — Table: Historial de incidentes recientes y su estado
-- Tipo: Table | Sort: Started DESC | Overrides:
--   • "Current status" → Value mappings: firing→rojo, resolved→verde
--   • "Severity"       → Value mappings: critical→rojo, warning→amarillo
--   • "MTTR (s)"       → Unit: seconds (s); NULL = incidente aún abierto
-- =============================================================================
SELECT
    f.started_at                                        AS "Started",
    f.hostname                                           AS "Device",
    f.severity                                            AS "Severity",
    f.alert_name                                           AS "Alert",
    ls.status                                               AS "Current status",
    r.resolved_at                                            AS "Resolved",
    CASE
        WHEN r.resolved_at IS NOT NULL
        THEN EXTRACT(EPOCH FROM (r.resolved_at - f.started_at))
    END                                                        AS "MTTR (s)"
FROM (
    SELECT fingerprint, hostname, severity, alert_name, MIN(starts_at) AS started_at
    FROM v_incident_events
    WHERE status = 'firing' AND fingerprint IS NOT NULL
    GROUP BY fingerprint, hostname, severity, alert_name
) f
LEFT JOIN (
    SELECT fingerprint, MIN(received_at) AS resolved_at
    FROM v_incident_events
    WHERE status = 'resolved'
    GROUP BY fingerprint
) r ON r.fingerprint = f.fingerprint
LEFT JOIN v_incident_latest_status ls ON ls.fingerprint = f.fingerprint
WHERE
    $__timeFilter(f.started_at)
    AND f.hostname IN ($hostname)
ORDER BY f.started_at DESC
LIMIT 100;

-- ─── Nota ──────────────────────────────────────────────────────────────────
-- Si $hostname está en "All", Grafana expande hostname IN ($hostname) con
-- todos los valores de la variable, no rompe la clausula IN.
-- ─────────────────────────────────────────────────────────────────────────────