# 📡 NOC Observability Pipeline

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-009639?style=for-the-badge&logo=timescaledb&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=for-the-badge&logo=grafana&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2CA5E0?style=for-the-badge&logo=docker&logoColor=white)
![Jira](https://img.shields.io/badge/Jira-0052CC?style=for-the-badge&logo=jira&logoColor=white)

Pipeline de observabilidad de extremo a extremo — **multi-región** — para simular, ingerir, almacenar, visualizar, alertar, **ticketizar** y analizar telemetría de red en un entorno de Centro de Operaciones de Red (NOC). Arquitectura 100% contenerizada, gobernada por **Infrastructure as Code**: dashboards, reglas de alerta, ventanas de mantenimiento y el motor de recepción/escalado de incidentes viven como código versionado, no como clics en una UI.

---

## 🧭 Acerca del Proyecto

Este repositorio implementa un **loop de alerta cerrado y geográficamente distribuido**. Tres simuladores regionales (`us-east`, `eu-west`, `sa-south`) alimentan una única hypertable en TimescaleDB. Grafana detecta la anomalía, la enruta según severidad, respeta las ventanas de mantenimiento definidas en código, y un microservicio propio en **FastAPI** — ahora autenticado y con cliente Jira nativo — recibe, registra, prioriza y **escala automáticamente cada incidente a un ticket de Jira**, sin intervención humana.

Con la **Fase 4 completada**, el sistema deja de ser un pipeline de un solo sitio para convertirse en una plataforma de observabilidad **multi-región, segura y con inteligencia operativa de postmortem** (MTTR real, conteo de incidentes, historial correlacionado).

Cuatro capas, un solo `docker compose up`.

---

## 🏗️ Arquitectura y Stack

El ecosistema está compuesto por **cuatro capas**, todas orquestadas mediante **Docker Compose** sobre una red bridge compartida (`noc_net`):

### Capa 1 — Ingesta Multi-Región (`python-simulator/`)
Simulador modular, parametrizado por la variable de entorno `REGION`, que genera **métricas de red realistas** para 5 dispositivos por región (core routers, distribution switches, access switches):
- **3 réplicas concurrentes** vía Docker Compose: `simulator-us-east`, `simulator-eu-west`, `simulator-sa-south` — mismo build, distinto `REGION`
- **Latencia (RTT):** baseline por región con jitter gaussiano, picos de degradación controlados
- **Packet Loss:** nominal bajo, picos altos en eventos `CRITICAL`
- **CPU:** baseline por dispositivo, hasta saturación en sobrecarga
- Hostnames prefijados por región (`euw1-*`, `sas1-*`) para evitar colisiones; `us-east` se mantiene sin prefijo por retrocompatibilidad
- Múltiples sinks intercambiables vía `--fmt`: `csv`, `jsonl`, `postgres`
- Incluye `force_alert_test.py`: inyector determinístico de telemetría `CRITICAL` sostenida sobre `core-rtr-01`, pensado para testear alertas sin esperar al azar del simulador general

### Capa 2 — Almacenamiento Multi-Región (TimescaleDB / PostgreSQL 16)
- **Hypertable** `network_telemetry` particionada por tiempo (chunks de 1 día), con columna `region` indexada y como parte del `compress_segmentby`
- Tabla de dimensiones `devices` extendida con `region` (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, idempotente)
- **Compresión automática** a los 7 días (`compress_segmentby: hostname, severity, region`) → 85–95% de ahorro típico
- **Retención automática** de 90 días vía `add_retention_policy`
- **5 vistas** optimizadas para consumo directo desde Grafana, incluyendo la nueva `v_region_health` (comparativa de salud entre regiones)
- **Vistas de postmortem sobre JSONB** (`incident_views.sql`): `v_incident_events` extrae `region`, `hostname`, `severity` y `fingerprint` directamente del payload de Alertmanager vía `payload -> 'alerts' -> 0 -> 'labels' ->> 'region'`; `v_incident_mttr` empareja `firing` → `resolved` por fingerprint y calcula el MTTR real en segundos

### Capa 3 — Visualización e Inteligencia Operativa (Grafana OSS, Unified Alerting)
Dos dashboards y el sistema de alertas **100% aprovisionados vía IaC** (`grafana/provisioning/`), sin configuración manual en la UI:
- **Dashboard `NOC — Network Telemetry`** (`noc_telemetry.json`): eventos críticos (últimos 15 min), time series de latencia/CPU, snapshot de estado por dispositivo — con variable de plantilla **`$region`** (multi-value, Include All) además de `$hostname`
- **🆕 Dashboard `NOC - Postmortem & MTTR`** (`noc-postmortem-dashboard.json`): MTTR general, MTTR por dispositivo (bar gauge), conteo de incidentes por dispositivo (bar chart) e historial de incidentes recientes con estado — todos filtrables por `$region` y `$hostname`
- **3 reglas de alerta** (`alert_rules.yml`) evaluadas cada minuto
- **Contact points** (`contact_points.yml`) apuntando al Webhook Service interno, ahora con **Bearer Token** en cada request
- **Notification policies** (`notification_policies.yml`) con ruteo por severidad
- **Mute timings** (`mute_timings.yml`) — ventanas de mantenimiento que silencian alertas sin desactivar las reglas
- `GF_UNIFIED_ALERTING_ENABLED: "true"` / `GF_ALERTING_ENABLED: "false"` — el motor legacy está explícitamente apagado

### Capa 4 — Webhook Service: Seguridad + Auto-Ticketing (FastAPI + Docker)
El punto de llegada real de cada alerta disparada por Grafana, ahora **asegurado y accionable**:
- Expone `POST /alert` **protegido con Bearer Token** (`NOC_WEBHOOK_TOKEN`, validado con `secrets.compare_digest` para evitar timing attacks) — rechaza con `401 Unauthorized` cualquier request sin token válido
- Recibe el payload JSON estándar de Grafana (`status`, `alerts[]`, `labels`), lo loguea y lo persiste en `incident_logs`
- **🆕 Cliente Jira Cloud integrado**: por cada alerta recibida, construye y envía un ticket vía `POST {JIRA_URL}/rest/api/3/issue`, mapeando la severidad de Grafana a la prioridad de Jira (`critical → Highest`, `warning → Medium`, etc.) y adjuntando el payload completo en la descripción del ticket
- Si Jira no está configurado (variables ausentes) o la creación falla, el servicio **no rompe la ingesta**: responde igualmente `200 OK` con `jira: {"created": false, "reason": "..."}`, garantizando resiliencia zero-touch
- Expone `GET /health` para liveness checks
- Pool de conexiones a PostgreSQL (`psycopg2.pool.SimpleConnectionPool`), inicializado/cerrado en los eventos `startup`/`shutdown` de FastAPI
- Corre en su propio contenedor (`webhook-service`, puerto `8000`), en la misma red `noc_net`, con build propio vía Dockerfile

---

## 📂 Estructura del Proyecto

```
.
├── python-simulator/
│   ├── simulator.py                 # CLI + bucle principal de generación (lee REGION del entorno)
│   ├── config.py                    # Topología de dispositivos por región (_REGION_SEEDS)
│   ├── log_builder.py               # Construcción de registros de eventos
│   ├── metrics.py                   # Generación de métricas con anomalías
│   ├── writer.py                    # Sinks: CSV, JSONL, PostgreSQL (connection pool)
│   ├── force_alert_test.py          # Inyector de CRITICAL sostenido, solo testing
│   ├── simulate_mttr_incidents.py   # 🆕 Chaos Engineering: 3 incidentes concurrentes (firing→resolved) vía HTTP directo al Webhook
│   └── requirements.txt
│
├── webhook_service/
│   ├── main.py                      # FastAPI: POST /alert (Bearer auth), GET /health, cliente Jira
│   ├── requirements.txt             # fastapi, uvicorn[standard], psycopg2-binary, httpx
│   ├── webhook_service.sql          # DDL de incident_logs (tabla + índices GIN)
│   └── Dockerfile
│
├── grafana/provisioning/
│   ├── datasources/
│   │   └── timescaledb.yaml             # Datasource PostgreSQL (uid fijo: timescaledb_noc)
│   ├── dashboards/
│   │   ├── dashboards.yaml              # Proveedor de dashboards (file-based)
│   │   ├── noc_telemetry.json           # Dashboard principal (con $region)
│   │   └── noc-postmortem-dashboard.json # 🆕 Dashboard de Postmortem & MTTR
│   └── alerting/
│       ├── alert_rules.yml              # 3 reglas de alerta
│       ├── contact_points.yml           # Receivers → Webhook Service (Bearer Token)
│       ├── notification_policies.yml    # Ruteo de notificaciones por severidad
│       └── mute_timings.yml             # Ventanas de mantenimiento
│
├── sql/
│   ├── schema.sql                   # DDL: devices, network_telemetry (hypertable) + region
│   ├── panels.sql                   # Queries de referencia — dashboard principal
│   ├── panels_postmortem.sql        # Queries de referencia — dashboard de postmortem
│   └── incident_views.sql           # Vistas JSONB: v_incident_events, v_incident_mttr, v_incident_latest_status
│
├── .env                              # Secretos y configuración (no versionado)
├── .gitignore
├── .gitattributes
├── docker-compose.yml                # Orquestación: timescaledb + grafana + webhook-service + 3 simuladores
└── README.md
```

---

## 🚀 Requisitos

- **Docker** 20.10+
- **Docker Compose** v2 (`docker compose`, sin guion)
- **4 GB RAM** mínimo (recomendado 8 GB — 3 simuladores + TimescaleDB + Grafana + Webhook Service)
- **2 GB** de espacio en disco para volúmenes de datos
- Cuenta de **Jira Cloud** con un API Token válido (opcional, pero requerido para el auto-ticketing de la Fase 4)
- Windows: **PowerShell 5.1+** o **PowerShell 7+** (las instrucciones de este README están validadas para ambos)

---

## 🔐 Variables de Entorno (`.env`)

Crea un archivo `.env` en la raíz del repositorio (ya cubierto por `.gitignore`) con las siguientes claves:

```dotenv
# ── Webhook Service — autenticación ─────────────────────────────────────────
NOC_WEBHOOK_TOKEN=reemplaza-con-un-token-largo-y-aleatorio

# ── Integración Jira Cloud ───────────────────────────────────────────────────
JIRA_URL=https://tu-dominio.atlassian.net
JIRA_USER=tu-email@tudominio.com
JIRA_API_TOKEN=reemplaza-con-tu-api-token-de-atlassian
JIRA_PROJECT_KEY=NOC

# ── PostgreSQL / TimescaleDB (opcional si difiere del default de compose) ──
PG_HOST=timescaledb
PG_PORT=5432
PG_DB=noc
PG_USER=noc_user
PG_PASSWORD=secret
```

| Variable | Requerida | Descripción |
|---|---|---|
| `NOC_WEBHOOK_TOKEN` | ✅ Sí | Token Bearer compartido entre Grafana (`contact_points.yml`) y el Webhook Service. Sin él, el servicio **no arranca** (`RuntimeError`). |
| `JIRA_URL` | Opcional* | URL base de tu instancia Jira Cloud, sin `/` final. |
| `JIRA_USER` | Opcional* | Email de la cuenta de servicio usada para autenticar contra la API REST de Jira. |
| `JIRA_API_TOKEN` | Opcional* | API Token generado desde `id.atlassian.com/manage-profile/security/api-tokens`. |
| `JIRA_PROJECT_KEY` | Opcional* | Clave del proyecto Jira donde se crearán los tickets `Incident`. |
| `PG_*` | Opcional | Sobrescriben los defaults ya definidos en `docker-compose.yml` para el Webhook Service. |
| `WEBHOOK_URL` | Opcional | Usada por `simulate_mttr_incidents.py` para apuntar a un Webhook Service distinto de `http://localhost:8000/alert` (útil si lo corres contra un host remoto o expuesto tras un proxy). |

\* Si cualquiera de las 4 variables de Jira falta, el servicio sigue funcionando con normalidad — simplemente omite la creación del ticket y lo reporta en la respuesta (`jira.created: false`).

> ⚠️ Nunca commitees el `.env` real. Usa `.env.example` (sin valores) como plantilla para el equipo.

---

## ⚙️ Instalación y Despliegue

### 1. Clonar el repositorio

```powershell
git clone <repo-url>
cd noc-observability-pipeline
```

### 2. Configurar el `.env`

Copia la plantilla y completa tus credenciales:

```powershell
Copy-Item .env.example .env
notepad .env
```

### 3. Levantar la infraestructura completa

El Webhook Service se construye desde su propio Dockerfile; conviene forzar el build en el primer despliegue. `docker compose` levanta **6 servicios**: TimescaleDB, Grafana, Webhook Service y los 3 simuladores regionales.

```powershell
docker compose up -d --build
```

Verifica que **los seis** servicios estén corriendo:

```powershell
docker compose ps
```

Esperado:
```
NAME                 IMAGE                              STATUS         PORTS
timescaledb          timescale/timescaledb:latest-pg16  Up            0.0.0.0:5432->5432/tcp
grafana              grafana/grafana-oss:latest         Up            0.0.0.0:3000->3000/tcp
webhook_service      noc-observability-webhook          Up            0.0.0.0:8000->8000/tcp
simulator_us_east    noc-observability-simulator        Up
simulator_eu_west    noc-observability-simulator        Up
simulator_sa_south   noc-observability-simulator        Up
```

### 4. Inicializar el esquema principal (telemetría + regiones)

En PowerShell, usa `Get-Content` para inyectar el SQL vía stdin al contenedor:

```powershell
Get-Content sql/schema.sql | docker exec -i timescaledb psql -U noc_user -d noc
```

Verifica las tablas y vistas creadas:

```powershell
docker exec -i timescaledb psql -U noc_user -d noc `
  -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public';"
```

Deberías ver `devices`, `network_telemetry` y las vistas `v_telemetry_ts`, `v_event_counts`, `v_device_latest`, `v_recent_anomalies`, `v_region_health`.

Confirma que las 15 seeds de dispositivos (5 por región) se cargaron:

```powershell
docker exec -i timescaledb psql -U noc_user -d noc `
  -c "SELECT region, COUNT(*) FROM devices GROUP BY region ORDER BY region;"
```

### 5. Inicializar el esquema del Webhook Service

```powershell
Get-Content webhook_service/webhook_service.sql | docker exec -i timescaledb psql -U noc_user -d noc
```

Confirma la tabla `incident_logs`:

```powershell
docker exec -i timescaledb psql -U noc_user -d noc -c "\d incident_logs"
```

### 6. Inicializar las vistas de postmortem (JSONB → MTTR)

```powershell
Get-Content sql/incident_views.sql | docker exec -i timescaledb psql -U noc_user -d noc
```

Confirma las vistas:

```powershell
docker exec -i timescaledb psql -U noc_user -d noc `
  -c "SELECT viewname FROM pg_views WHERE viewname LIKE 'v_incident%';"
```

### 7. Verificar el Webhook Service (auth incluida)

```powershell
# Sin token → 401 esperado
Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get

# Endpoint /alert requiere Bearer Token — prueba de humo
$headers = @{ Authorization = "Bearer $env:NOC_WEBHOOK_TOKEN" }
Invoke-RestMethod -Uri "http://localhost:8000/health" -Headers $headers -Method Get
```

---

## ▶️ Uso

### Ejecutar un simulador regional de forma manual (fuera de Compose)

> ⚠️ `simulator.py` usa imports planos (`from config import DEVICES`), así que debes ejecutarlo **desde dentro de** `python-simulator/`.

```powershell
cd python-simulator
$env:REGION = "eu-west"
python simulator.py --fmt postgres --interval 2 --batch 3 `
  --pg-dsn "postgresql://noc_user:secret@localhost:5432/noc"
```

Logs esperados:
```
[INFO] [SIM][eu-west] Iniciando simulador [región=eu-west] → PostgreSQL/TimescaleDB [POSTGRES]
[INFO] [SIM][eu-west]    [WARN    ] eu-west  euw1-dist-sw-01      CPU=58.1%   LAT=  41.2ms  LOSS= 0.80%  Gi1/0/2 UP
[INFO] [SIM][eu-west]    [CRITICAL] eu-west  euw1-core-rtr-01     CPU=95.4%   LAT= 298.7ms  LOSS=14.20%  Te0/1/0 UP
```

En producción, los 3 simuladores ya corren automáticamente como servicios de `docker-compose.yml` (`simulator-us-east`, `simulator-eu-west`, `simulator-sa-south`) — no requieren intervención manual.

### Acceder a Grafana

Abre `http://localhost:3000`.

**Credenciales por defecto (solo laboratorio):**
- Usuario: `admin`
- Contraseña: `admin`

Navega a:
- **Dashboards → NOC — Network Telemetry**: telemetría en vivo, filtrable por `$region` y `$hostname`
- **Dashboards → NOC - Postmortem & MTTR**: KPIs operativos (MTTR general, MTTR por dispositivo, conteo de incidentes, historial), también filtrables por región

### Forzar una alerta de punta a punta (incluye ticket Jira)

Para validar el circuito completo (Grafana dispara → Webhook Service autentica, persiste y ticketiza en Jira) sin depender del azar del simulador:

```powershell
cd python-simulator
python force_alert_test.py --minutes 5 `
  --pg-dsn "postgresql://noc_user:secret@localhost:5432/noc"
```

En 2–3 minutos deberías ver la regla pasar a `Firing` en **Alerting → Alert rules**, el incidente persistido en `incident_logs`, y un ticket nuevo en tu proyecto de Jira:

```powershell
docker exec -i timescaledb psql -U noc_user -d noc `
  -c "SELECT received_at, status, alert_name FROM incident_logs ORDER BY received_at DESC LIMIT 5;"

docker logs webhook_service --tail 20 | Select-String "Ticket Jira creado"
```

### 🆕 Simulación de Chaos Engineering para MTTR

A diferencia de `force_alert_test.py` (que inyecta telemetría en TimescaleDB y espera a que Grafana evalúe la regla), `simulate_mttr_incidents.py` **envía payloads HTTP directamente al Webhook Service**, replicando el formato nativo de Grafana Alerting (`status`, `alerts[]`, `labels`, `fingerprint`). Esto permite validar el cálculo de MTTR en el dashboard de Postmortem sin depender de los tiempos de evaluación (`for:`) de las reglas de alerta.

El script dispara **3 incidentes concurrentes fijos, uno por región** (`core-rtr-01` / `us-east`, `euw1-core-rtr-01` / `eu-west`, `sas1-core-rtr-01` / `sa-south`), cada uno en su propio hilo:
1. Envía el estado `firing` cada 15s durante `fire_minutes` (2–3 min según el incidente), simulando latencia, packet loss o CPU degradados según corresponda.
2. Espera un intervalo de recuperación aleatorio (`recovery_minutes_range`).
3. Envía el estado `resolved`, cerrando el fingerprint y dejando el par `firing → resolved` listo para que `v_incident_mttr` calcule el `resolution_seconds` real.

**Dependencias adicionales** (no incluidas en `python-simulator/requirements.txt` actual — instálalas antes de ejecutar):

```powershell
pip install requests python-dotenv
```

**Requiere `NOC_WEBHOOK_TOKEN`** disponible como variable de entorno o en un archivo `.env` en el directorio de ejecución (el script usa `load_dotenv()` y aborta con `sys.exit(1)` si el token no está presente).

```powershell
cd python-simulator
# Asegúrate de que .env (con NOC_WEBHOOK_TOKEN) esté en este directorio, o expórtalo:
$env:NOC_WEBHOOK_TOKEN = "el-mismo-token-que-usa-el-webhook-service"

python simulate_mttr_incidents.py
# O apuntando a un webhook remoto/expuesto en otro host:
python simulate_mttr_incidents.py --webhook-url "http://localhost:8000/alert"
```

Salida esperada (resumida):
```
=== CHAOS ENGINEERING — MTTR MULTI-REGIÓN (WEBHOOK) ===
Webhook: http://localhost:8000/alert
Regiones/dispositivos objetivo: core-rtr-01(us-east), euw1-core-rtr-01(eu-west), sas1-core-rtr-01(sa-south)

[10:32:01] 🔥 FIRING   core-rtr-01          Inyectando falla [latency=230.0ms] Latencia > 150ms durante 2.0 min (for: 3m)
[10:32:01] 🚨 CRITICAL core-rtr-01          latency=230.0ms — esperando evaluación de Grafana...
[10:34:12] 🛠️  RECOVERY core-rtr-01          Resolviendo en 1.3 min (aleatorio) para forzar RESOLVED
[10:35:30] ✅ RESOLVED core-rtr-01          MTTR ≈ 209s
[10:35:30] 🏁 CLOSED   core-rtr-01          Incidente cerrado — Grafana debería marcar RESOLVED y calcular el MTTR
```

Al finalizar los 3 hilos, revisa el dashboard **NOC - Postmortem & MTTR** en Grafana: deberías ver los 3 incidentes reflejados en el historial, con MTTR calculado por región. `Ctrl+C` detiene los incidentes en curso de forma limpia (fuerza el envío del estado `resolved` pendiente antes de salir).

> ⚠️ El único flag soportado es `--webhook-url` (o la variable de entorno `WEBHOOK_URL`). Los 3 incidentes, sus métricas y su duración están hardcodeados en la lista `INCIDENTS` dentro del script — para escenarios distintos, edita esa lista directamente.

---

## 🚨 Sistema de Alertas Provisioned (IaC)

Reglas, contact points, políticas de notificación y ventanas de mantenimiento se aprovisionan **automáticamente** al levantar Grafana — cero configuración manual en la UI. Todo vive en `grafana/provisioning/alerting/`.

### Reglas de alerta (`alert_rules.yml`)

| Regla | Umbral | Duración sostenida | Severidad |
|---|---|---|---|
| Latencia Crítica Sostenida | `AVG(latency_ms) > 150ms` | 3 min | `critical` |
| Packet Loss Elevado | `AVG(packet_loss_pct) > 10%` | 2 min | `critical` |
| CPU Elevado Sostenido | `AVG(cpu_pct) > 85%` | 5 min | `warning` |

Cada regla sigue el mismo patrón de evaluación: `Query (SQL contra TimescaleDB) → Reduce (last) → Threshold → Fire/Resolve`.

### Contact points (`contact_points.yml`)

Ambos contact points (`noc-webhook-default`, `noc-webhook-critical`) apuntan al **Webhook Service interno** (`type: webhook`, `url: http://webhook-service:8000/alert`), autenticados con **Bearer Token** (`${NOC_WEBHOOK_TOKEN}` inyectado vía `secureSettings.authorization`). Esto significa que cada disparo de alerta queda **persistido, auditado y ticketizado en Jira** por defecto, sin depender de un servicio de terceros ni exponer el endpoint sin autenticación.

### Ruteo de notificaciones (`notification_policies.yml`)

| Condición | Receptor | Group Wait | Repeat |
|---|---|---|---|
| `severity = critical` | `noc-webhook-critical` | 10s | 20s |
| `severity = warning` | `noc-webhook-default` | 1m | 6h |
| (default) | `noc-webhook-default` | 30s | 4h |

**Group By:** `alertname, hostname` — agrupa alertas del mismo tipo en el mismo dispositivo.

### Mute Timings — ventanas de mantenimiento

`mute_timings.yml` define una ventana de silencio recurrente que se aplica a **ambas** rutas (`critical` y `warning`) vía `mute_time_intervals`:

```yaml
muteTimes:
  - name: maintenance-window-tuesday
    time_intervals:
      - times:
          - start_time: '14:50'
            end_time:   '15:10'
        weekdays: ['tuesday']
        location: 'America/Santiago'
```

Durante esa franja, las reglas siguen evaluándose y pueden pasar a `Firing`, pero **no se envían notificaciones ni se crean tickets Jira** — ideal para ventanas de mantenimiento programado sin tener que deshabilitar reglas a mano.

### Validar el circuito de alertas

```powershell
# 1. Confirmar que las reglas se aprovisionaron
docker logs grafana | Select-String "provisioned alert rule"

# 2. Ver estado de las reglas vía API
Invoke-RestMethod -Uri "http://localhost:3000/api/v1/provisioning/alert-rules" `
  -Credential (Get-Credential) | ConvertTo-Json -Depth 4

# 3. Probar el contact point manualmente
# UI: Alerting → Contact points → noc-webhook-default → Test
```

---

## 📊 Estructura de Datos

### `network_telemetry` (hypertable, multi-región)

```sql
ts               TIMESTAMPTZ      -- partition key
hostname         TEXT             -- FK → devices
ip               INET
role             device_role      -- core-router | distribution-sw | access-sw
region           TEXT             -- us-east | eu-west | sa-south
severity         severity_level   -- INFO | WARN | ERROR | CRITICAL
message          TEXT
cpu_pct          DOUBLE PRECISION -- 0-100
latency_ms       DOUBLE PRECISION -- ms
packet_loss_pct  DOUBLE PRECISION -- 0-100
interface        TEXT
iface_status     iface_state      -- UP | DOWN
peer_ip          INET
```

### `incident_logs` — tabla del Webhook Service

```sql
id            BIGSERIAL PRIMARY KEY
received_at   TIMESTAMPTZ NOT NULL DEFAULT now()
status        TEXT              -- 'firing' | 'resolved' (según payload de Grafana)
alert_name    TEXT              -- extraído de alerts[0].labels.alertname
payload       JSONB NOT NULL    -- payload completo de Grafana, indexado con GIN
```

### Vistas para Grafana — telemetría

| Vista | Propósito |
|---|---|
| `v_telemetry_ts` | Time series: latencia, CPU, packet loss por dispositivo |
| `v_event_counts` | Conteo de eventos por severidad en buckets de 5m |
| `v_device_latest` | Último estado registrado por dispositivo |
| `v_recent_anomalies` | Eventos `WARN+` en la última hora |
| `v_region_health` | 🆕 Comparativa de salud (CRITICAL count, latencia y CPU promedio) por región en buckets de 5m |

### Vistas para Grafana — postmortem (sobre `incident_logs`, JSONB)

| Vista | Propósito |
|---|---|
| `v_incident_events` | Normaliza cada fila JSONB en columnas planas (`fingerprint`, `hostname`, `region`, `severity`, `starts_at`) |
| `v_incident_mttr` | Empareja `firing` → `resolved` por `fingerprint` y calcula `resolution_seconds` (MTTR real) |
| `v_incident_latest_status` | Último estado conocido por `fingerprint`, usado para marcar incidentes como `FIRING` o `RESOLVED` en la tabla de historial |

---

## 🔍 Troubleshooting

### "AlertRule has no datasource"
**Causa:** la UID en `alert_rules.yml` (`timescaledb_noc`) no coincide con la UID real del datasource.
**Solución:** copia la UID real desde **Administration → Connections → Datasources** y reemplázala en `alert_rules.yml`.

### "Connection refused" entre Grafana y PostgreSQL
```powershell
docker network inspect noc_net
docker exec grafana ping timescaledb
```
Confirma que `timescaledb`, `grafana`, `webhook_service` y los 3 simuladores estén en la misma red `noc_net`.

### El Webhook Service responde `401 Unauthorized`
**Causa:** `NOC_WEBHOOK_TOKEN` no coincide entre `.env` (leído por `docker-compose.yml`) y el valor aprovisionado en `contact_points.yml`.
**Solución:** verifica que ambos usen la misma variable de entorno y reinicia:
```powershell
docker compose up -d --force-recreate grafana webhook-service
```

### El ticket de Jira no se crea (`jira.created: false`)
**Causa 1:** faltan una o más variables `JIRA_URL`, `JIRA_USER`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY` en `.env`.
**Causa 2:** el API Token expiró o el usuario no tiene permisos de creación en el proyecto.
**Solución:**
```powershell
docker logs webhook_service --tail 50 | Select-String "Jira"
```
Revisa el campo `reason` en la respuesta del webhook para el detalle exacto devuelto por la API de Jira.

### Las alertas no disparan pese a haber anomalías
1. Alguno de los simuladores regionales no está corriendo → `docker compose ps` y reinícialo con `docker compose up -d simulator-eu-west`
2. Las métricas no superan el umbral → sube la intensidad con `--interval 0.3 --batch 10`
3. Estás dentro de la ventana de `mute_timings.yml` (martes 14:50–15:10, `America/Santiago`) → las reglas disparan pero no notifican ni ticketizan, es comportamiento esperado

### El Webhook Service responde `persisted: false`
**Causa:** la tabla `incident_logs` no existe o la conexión a PostgreSQL falló.
**Solución:**
```powershell
docker logs webhook_service --tail 50
docker exec -i timescaledb psql -U noc_user -d noc -c "\d incident_logs"
```
Si la tabla no existe, corre el paso 5 de instalación (`webhook_service/webhook_service.sql`).

### El dashboard de Postmortem no muestra datos
**Causa:** `incident_views.sql` no se ejecutó, o no hay pares `firing`/`resolved` en `incident_logs` todavía.
**Solución:** corre el paso 6 de instalación y luego `simulate_mttr_incidents.py` para poblar datos sintéticos de MTTR.

### Quiero volver a usar Slack en vez del Webhook Service
Cambia `type: webhook` por `type: slack` en `contact_points.yml` y reemplaza `url` por tu Incoming Webhook de Slack. **Importante:** para URLs `hooks.slack.com`, el tipo debe ser `slack` — con `type: webhook` genérico, Slack rechaza el payload con `400 invalid_payload` porque el esquema JSON no coincide.

---

## 🔧 Configuración en Producción

### Reintroducir Slack / Teams / PagerDuty como receiver

```yaml
# grafana/provisioning/alerting/contact_points.yml
contactPoints:
  - orgId: 1
    name: noc-webhook-critical
    receivers:
      - uid: noc-webhook-002
        type: slack   # usar "slack", no "webhook", para hooks.slack.com
        settings:
          url: https://hooks.slack.com/services/YOUR/ACTUAL/WEBHOOK_URL
```

Redeploy:
```powershell
docker compose down
docker compose up -d
```

### Habilitar SMTP para alertas por email

Descomenta y completa en `docker-compose.yml` (servicio `grafana`):

```yaml
environment:
  GF_SMTP_ENABLED:      "true"
  GF_SMTP_HOST:         smtp.gmail.com:587
  GF_SMTP_USER:         alerts@tudominio.com
  GF_SMTP_PASSWORD:     tu-app-password
  GF_SMTP_FROM_ADDRESS: alerts@tudominio.com
  GF_SMTP_FROM_NAME:    "NOC Alerts"
```

Luego añade un contact point `type: email` en `contact_points.yml`.

### Escalar el Webhook Service

Al ser un servicio FastAPI stateless (toda la persistencia vive en PostgreSQL), es horizontalmente escalable: súbelo detrás de un balanceador y aumenta `maxconn` en el pool de conexiones según el volumen esperado de alertas. La creación de tickets Jira es asíncrona (`httpx.AsyncClient`), por lo que no bloquea la persistencia del incidente aunque la API de Jira esté lenta.

### Añadir una nueva región

1. Extiende `_REGION_SEEDS` en `python-simulator/config.py` con los dispositivos de la nueva región.
2. Añade un nuevo servicio `simulator-<region>` en `docker-compose.yml`, replicando el patrón de los existentes con `REGION: <region>`.
3. Ejecuta `sql/schema.sql` de nuevo (es idempotente) para insertar los nuevos `devices`.
4. Las variables `$region` en ambos dashboards se refrescan automáticamente (`refresh: 2` — on time range change) sin cambios adicionales.

---

## 🔐 Seguridad

### Credenciales por defecto (solo laboratorio — no usar en producción)

- **PostgreSQL:** usuario `noc_user`, contraseña `secret`
- **Grafana Admin:** usuario `admin`, contraseña `admin`
- **Webhook Service:** hereda las credenciales de PostgreSQL vía variables de entorno (`PG_HOST`, `PG_PORT`, `PG_DB`, `PG_USER`, `PG_PASSWORD`)

### Autenticación implementada (Fase 4)

- El endpoint `POST /alert` **exige** un header `Authorization: Bearer <NOC_WEBHOOK_TOKEN>`; requests sin token o con token inválido reciben `401 Unauthorized`
- La comparación del token usa `secrets.compare_digest` para mitigar ataques de timing
- El token se inyecta en Grafana vía `secureSettings.authorization` en `contact_points.yml` (nunca en texto plano en `jsonData`)
- Las credenciales de Jira (`JIRA_API_TOKEN`) viajan únicamente como variables de entorno del contenedor `webhook-service`, nunca hardcodeadas en el código ni en el repositorio

### En producción

- Usa variables de entorno vía `.env` (ya soportado por `docker compose`) — **nunca** commitees el `.env` real
- Almacena secretos en HashiCorp Vault o AWS/GCP Secrets Manager, inyectándolos como variables de entorno en el orquestador
- Cambia la contraseña de Grafana Admin inmediatamente tras el primer despliegue
- Rota `NOC_WEBHOOK_TOKEN` y `JIRA_API_TOKEN` periódicamente; ambos son reemplazables sin downtime (`docker compose up -d --force-recreate`)
- No publiques el puerto `8000` fuera del host en producción — restringe la exposición del Webhook Service a la red interna (`noc_net`) y ponlo detrás de un reverse proxy con TLS si necesitas acceso externo

---

## 📈 Roadmap

### ✅ Fase 2 — Notificaciones y alertas nativas (completada)
- ✅ Alertas nativas de Grafana aprovisionadas 100% vía IaC
- ✅ Ruteo por severidad con políticas de notificación diferenciadas

### ✅ Fase 3 — Recepción y resiliencia operativa (completada)
- ✅ Microservicio Webhook (FastAPI) para recibir y persistir alertas
- ✅ Mute Timings para ventanas de mantenimiento programado
- ✅ Tabla `incident_logs` como bitácora auditable de incidentes

### ✅ Fase 4 — Escalado Avanzado (completada)
- ✅ Integración del Webhook Service con **JIRA** para auto-tickets zero-touch ante alertas `firing`
- ✅ **Autenticación Bearer Token** (`NOC_WEBHOOK_TOKEN`) en `POST /alert` — ingesta segura, sin tickets falsos
- ✅ **Escalado geográfico multi-región**: 3 simuladores concurrentes (`us-east`, `eu-west`, `sa-south`) sobre una hypertable única
- ✅ Extensión del esquema (`schema.sql`, `devices`, `network_telemetry`) con la dimensión `region`
- ✅ **Dashboards de postmortem** (`noc-postmortem-dashboard.json`) con MTTR general, MTTR por dispositivo, conteo de incidentes e historial
- ✅ Vistas JSONB refactorizadas (`incident_views.sql`) extrayendo `region`, `hostname` y `severity` desde `payload -> 'alerts' -> 0 -> 'labels'`
- ✅ Variable de plantilla `$region` en ambos dashboards para filtrado dinámico multi-sitio

### 🔮 Fase 5 — ML y Anomalía Adaptativa (próxima)
- [ ] Detección de anomalías basada en histórico (Prophet / Isolation Forest)
- [ ] Baselines dinámicos por hora del día / día de la semana / región
- [ ] Deduplicación inteligente de alertas repetidas antes de ticketizar en Jira
- [ ] Cierre automático de tickets Jira al recibir el evento `resolved` correspondiente
- [ ] Exportación de métricas de MTTR a un dashboard ejecutivo (SLA/SLO tracking)

---

## 📚 Referencias

- **Grafana Unified Alerting:** https://grafana.com/docs/grafana/latest/alerting/
- **Grafana Provisioning:** https://grafana.com/docs/grafana/latest/administration/provisioning/
- **Mute Timings:** https://grafana.com/docs/grafana/latest/alerting/configure-notifications/mute-timings/
- **TimescaleDB:** https://docs.timescaledb.com/
- **FastAPI:** https://fastapi.tiangolo.com/
- **Jira Cloud REST API (Issues):** https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/

---

## 📝 Contribuciones

Este proyecto sigue **Infrastructure as Code** como principio rector. Cualquier cambio en alertas, dashboards, datasources, esquema multi-región o en el Webhook Service debe pasar por código y Git.

**Workflow:**
1. Edita el YAML/SQL/código correspondiente
2. Commit descriptivo
3. Abre PR
4. Redeploy: `docker compose down && docker compose up -d --build`
5. Valida el cambio en la UI o vía `Invoke-RestMethod`/API

---

## 📄 Licencia

[Especifica tu licencia aquí — ej. MIT, Apache 2.0]

---

**Mantenido por:** [Tu equipo NOC]
**Última actualización:** Agosto 2026
**Versión:** 4.0 (Multi-Región + Jira Auto-Ticketing + Webhook Seguro + Postmortem)