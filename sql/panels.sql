-- =============================================================================
-- panels.sql — Consultas SQL para los 3 paneles del dashboard NOC base
-- Pegar directamente en el editor SQL de cada panel en Grafana.
-- Datasource: TimescaleDB-NOC (PostgreSQL con extensión timescaledb activa)
-- =============================================================================


-- =============================================================================
-- PANEL 1: Time Series — Latencia y CPU por dispositivo
-- Tipo de panel: Time series
-- Configuración del panel:
--   • Fill opacity: 10  | Line width: 2  | Points: off
--   • Tooltip: All (para ver todos los devices en el mismo hover)
--   • Legend: Bottom, Table, con Max y Last
--   • Overrides: aplicar unit "ms" a latency_ms, "percent (0-100)" a cpu_pct
-- =============================================================================

-- Query A — Latencia promedio por dispositivo en bucket de $__interval
SELECT
    time_bucket('$__interval', ts)  AS "time",
    hostname,
    AVG(latency_ms)                 AS latency_ms
FROM v_telemetry_ts
WHERE
    $__timeFilter(ts)
    AND hostname IN ($hostname)     -- variable de template (multi-value)
GROUP BY 1, 2
ORDER BY 1;

-- Query B — CPU promedio por dispositivo en bucket de $__interval
SELECT
    time_bucket('$__interval', ts)  AS "time",
    hostname,
    AVG(cpu_pct)                    AS cpu_pct
FROM v_telemetry_ts
WHERE
    $__timeFilter(ts)
    AND hostname IN ($hostname)
GROUP BY 1, 2
ORDER BY 1;

-- ─── Nota sobre las macros ───────────────────────────────────────────────────
-- $__timeFilter(ts)  → expande a: ts BETWEEN '<from>' AND '<to>'
--                      usando el rango del time-picker de Grafana.
-- $__interval        → Grafana calcula el bucket óptimo según el ancho de
--                      pantalla del panel (ej: '15s', '1m', '5m').
-- $hostname          → variable de template definida en el dashboard (ver abajo).
-- ─────────────────────────────────────────────────────────────────────────────


-- =============================================================================
-- PANEL 2: Table — Estado actual de cada dispositivo (foto instantánea)
-- Tipo de panel: Table
-- Configuración del panel:
--   • Column alignment: Auto
--   • Overrides:
--       - cpu_pct     → unit: percent (0-100), Thresholds: >70 yellow, >90 red
--       - latency_ms  → unit: milliseconds,    Thresholds: >50 yellow, >200 red
--       - iface_status→ Value mappings: UP→green text, DOWN→red text
--       - severity    → Value mappings: INFO→blue, WARN→yellow, ERROR→orange, CRITICAL→red
--   • Footer: desactivado (es una snapshot, no necesita sumas)
-- =============================================================================

SELECT
    ts                  AS "Last seen",
    hostname            AS "Device",
    severity            AS "Severity",
    cpu_pct             AS "CPU %",
    latency_ms          AS "Latency (ms)",
    packet_loss_pct     AS "Packet loss %",
    iface_status        AS "Last iface state"
FROM v_device_latest
ORDER BY
    -- Pone los CRITICAL arriba automáticamente
    CASE severity
        WHEN 'CRITICAL' THEN 1
        WHEN 'ERROR'    THEN 2
        WHEN 'WARN'     THEN 3
        ELSE                 4
    END,
    hostname;

-- ─── Sin $__timeFilter aquí ──────────────────────────────────────────────────
-- v_device_latest ya devuelve solo la última fila por device (DISTINCT ON).
-- Añadir un filtro de tiempo rompería la vista para devices sin actividad
-- reciente dentro del rango seleccionado.
-- ─────────────────────────────────────────────────────────────────────────────


-- =============================================================================
-- PANEL 3: Stat + Table — Alerta visual: CRITICAL e interfaces DOWN (últimos 15 min)
-- Implementar como DOS sub-paneles en un Row, o un solo panel Table con Stat encima.
--
-- OPCIÓN A (recomendada): Stat panel para el conteo total
-- Tipo de panel: Stat
-- Configuración:
--   • Calculation: Last (no mean)
--   • Color mode: Background
--   • Thresholds: 0→green, 1→red  (cualquier evento critico = rojo inmediato)
--   • No legend
-- =============================================================================

-- Query para el Stat (número total de eventos críticos en los últimos 15 min)
SELECT
    COUNT(*) AS "Critical events (15m)"
FROM network_telemetry
WHERE
    ts >= NOW() - INTERVAL '15 minutes'
    AND (
        severity    = 'CRITICAL'
        OR iface_status = 'DOWN'
    );


-- =============================================================================
-- OPCIÓN B: Table panel con el detalle de los eventos (debajo del Stat)
-- Tipo de panel: Table
-- Configuración:
--   • Sort by: ts DESC (por defecto)
--   • Overrides: severity → value mappings con colores (igual que Panel 2)
--   • Page size: 20
-- =============================================================================

SELECT
    ts                  AS "Time",
    hostname            AS "Device",
    severity            AS "Severity",
    message             AS "Message",
    interface           AS "Interface",
    iface_status        AS "State",
    cpu_pct             AS "CPU %",
    latency_ms          AS "Latency (ms)",
    packet_loss_pct     AS "Loss %"
FROM network_telemetry
WHERE
    ts >= NOW() - INTERVAL '15 minutes'
    AND (
        severity    = 'CRITICAL'
        OR iface_status = 'DOWN'
    )
ORDER BY
    ts DESC,
    severity;            -- CRITICAL sube si hay varios en el mismo segundo


-- =============================================================================
-- VARIABLE DE TEMPLATE: $hostname (multi-value dropdown en el dashboard)
-- Settings → Variables → New variable:
--   • Type:        Query
--   • Name:        hostname
--   • Data source: TimescaleDB-NOC
--   • Query:       (pegar la SELECT de abajo)
--   • Multi-value: ON
--   • Include All: ON  (valor All = todos los devices a la vez)
--   • Refresh:     On time range change
-- =============================================================================

SELECT DISTINCT hostname
FROM devices
ORDER BY hostname;


-- =============================================================================
-- REFRESH AUTOMÁTICO DEL DASHBOARD
-- Dashboard settings → Time options:
--   • Auto-refresh: 5s, 10s, 30s   (añadir opciones)
--   • Default refresh: 10s
--   • Time range default: Last 30 minutes
-- =============================================================================
