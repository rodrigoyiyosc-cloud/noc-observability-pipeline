CREATE OR REPLACE VIEW v_incident_events AS
SELECT
    id,
    received_at,
    status,
    alert_name,
    payload -> 'alerts' -> 0 ->> 'fingerprint'                               AS fingerprint,
    COALESCE(payload -> 'alerts' -> 0 -> 'labels' ->> 'hostname', 'unknown') AS hostname,
    COALESCE(payload -> 'alerts' -> 0 -> 'labels' ->> 'severity', 'unknown') AS severity,
    COALESCE(payload -> 'alerts' -> 0 -> 'labels' ->> 'region', 'us-east')   AS region,
    payload -> 'alerts' -> 0 -> 'annotations' ->> 'summary'                  AS summary,
    (payload -> 'alerts' -> 0 ->> 'startsAt')::timestamptz                   AS starts_at
FROM incident_logs
WHERE payload ? 'alerts';

CREATE OR REPLACE VIEW v_incident_mttr AS
WITH firing AS (
    SELECT
        fingerprint,
        hostname,
        severity,
        alert_name,
        region,
        started_at,
        ROW_NUMBER() OVER (PARTITION BY fingerprint ORDER BY started_at) AS rn
    FROM (
        SELECT DISTINCT
            fingerprint, hostname, severity, alert_name, region, starts_at AS started_at
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
    f.region,
    f.started_at,
    r.resolved_at,
    EXTRACT(EPOCH FROM (r.resolved_at - f.started_at)) AS resolution_seconds
FROM firing f
JOIN resolved r ON r.fingerprint = f.fingerprint AND r.rn = f.rn
WHERE r.resolved_at > f.started_at;

CREATE OR REPLACE VIEW v_incident_latest_status AS
SELECT DISTINCT ON (fingerprint)
    fingerprint,
    status,
    region,
    received_at
FROM v_incident_events
WHERE fingerprint IS NOT NULL
ORDER BY fingerprint, received_at DESC;