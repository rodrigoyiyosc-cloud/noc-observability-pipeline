# 📡 NOC Observability Pipeline

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-009639?style=for-the-badge&logo=timescaledb&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=for-the-badge&logo=grafana&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2CA5E0?style=for-the-badge&logo=docker&logoColor=white)

Pipeline de observabilidad de extremo a extremo para simular, ingerir, almacenar, visualizar, alertar **y reaccionar** ante telemetría de red en un entorno de Centro de Operaciones de Red (NOC). Arquitectura 100% contenerizada, gobernada por **Infrastructure as Code**: dashboards, reglas de alerta, ventanas de mantenimiento y el propio motor de recepción de incidentes viven como código versionado, no como clics en una UI.

---

## 🧭 Acerca del Proyecto

Este repositorio deja de ser solo un simulador con dashboard: ahora es un **loop de alerta cerrado**. Grafana detecta la anomalía, la enruta según severidad, respeta las ventanas de mantenimiento definidas en código, y un microservicio propio en **FastAPI** recibe, registra y persiste cada incidente en PostgreSQL — listo para auditoría, correlación o integración con un sistema de tickets.

Cuatro capas, un solo `docker-compose up`.

---

## 🏗️ Arquitectura y Stack

El ecosistema está compuesto por **cuatro capas**, todas orquestadas mediante **Docker Compose** sobre una red bridge compartida (`noc_net`):

### Capa 1 — Ingesta (`python-simulator/`)
Simulador modular que genera **métricas de red realistas** para 5 dispositivos (core routers, distribution switches, access switches):
- **Latencia (RTT):** 3–8 ms baseline con jitter gaussiano, picos de degradación controlados
- **Packet Loss:** nominal bajo, picos altos en eventos `CRITICAL`
- **CPU:** baseline por dispositivo (22–45%), hasta saturación en sobrecarga
- Múltiples sinks intercambiables vía `--fmt`: `csv`, `jsonl`, `postgres`
- Incluye `force_alert_test.py`: inyector determinístico de telemetría `CRITICAL` sostenida sobre `core-rtr-01`, pensado para testear alertas sin esperar al azar del simulador general

### Capa 2 — Almacenamiento (TimescaleDB / PostgreSQL 16)
- **Hypertable** `network_telemetry` particionada por tiempo (chunks de 1 día)
- **Compresión automática** a los 7 días (`compress_segmentby: hostname, severity`) → 85–95% de ahorro típico
- **Retención automática** de 90 días vía `add_retention_policy`
- **4 vistas** optimizadas para consumo directo desde Grafana (sin CTEs en cada panel)
- **Tabla adicional `incident_logs`**: bitácora JSONB de todo lo que el Webhook Service recibe desde Grafana (ver Capa 4)

### Capa 3 — Visualización y Alertas Nativas (Grafana OSS, Unified Alerting)
Dashboard y sistema de alertas **100% aprovisionados vía IaC** (`grafana/provisioning/`), sin configuración manual en la UI:
- **Dashboard `NOC — Network Telemetry`**, 3 paneles: eventos críticos (últimos 15 min), time series de latencia/CPU, snapshot de estado por dispositivo
- **3 reglas de alerta** (`alert_rules.yml`) evaluadas cada minuto
- **Contact points** (`contact_points.yml`) apuntando al Webhook Service interno
- **Notification policies** (`notification_policies.yml`) con ruteo por severidad
- **Mute timings** (`mute_timings.yml`) — ✅ **Fase 3**: ventanas de mantenimiento que silencian alertas sin desactivar las reglas
- `GF_UNIFIED_ALERTING_ENABLED: "true"` / `GF_ALERTING_ENABLED: "false"` — el motor legacy está explícitamente apagado

### Capa 4 — Webhook Service (FastAPI + Docker) — 🆕 Nuevo microservicio
El punto de llegada real de cada alerta disparada por Grafana:
- Expone `POST /alert`: recibe el payload JSON estándar de Grafana (`status`, `alerts[]`, `labels`), lo loguea y lo persiste en `incident_logs`
- Expone `GET /health` para liveness checks
- Pool de conexiones a PostgreSQL (`psycopg2.pool.SimpleConnectionPool`), inicializado/cerrado en los eventos `startup`/`shutdown` de FastAPI
- Corre en su propio contenedor (`webhook-service`, puerto `8000`), en la misma red `noc_net`, con build propio vía Dockerfile
- Si la escritura en PostgreSQL falla, el servicio **no rompe la recepción**: responde `{"status": "received", "persisted": false}` en vez de un 500

---

## 📂 Estructura del Proyecto
.
├── python-simulator/
│ ├── simulator.py # CLI + bucle principal de generación
│ ├── config.py # Topología de dispositivos (DEVICES)
│ ├── log_builder.py # Construcción de registros de eventos
│ ├── metrics.py # Generación de métricas con anomalías
│ ├── writer.py # Sinks: CSV, JSONL, PostgreSQL (connection pool)
│ └── force_alert_test.py # Inyector de CRITICAL sostenido, solo testing
│
├── webhook-service/ # 🆕 Microservicio receptor de alertas
│ ├── main.py # FastAPI: POST /alert, GET /health
│ ├── requirements.txt # fastapi, uvicorn[standard], psycopg2-binary
│ ├── webhook_service.sql # DDL de incident_logs (tabla + índices)
│ └── Dockerfile
│
├── grafana/provisioning/
│ ├── datasources/
│ │ └── timescaledb.yaml # Datasource PostgreSQL (uid fijo: timescaledb_noc)
│ ├── dashboards/
│ │ ├── dashboards.yaml # Proveedor de dashboards (file-based)
│ │ └── noc_telemetry.json # Dashboard principal (3 paneles)
│ └── alerting/
│ ├── alert_rules.yml # 3 reglas de alerta
│ ├── contact_points.yml # Receivers → Webhook Service
│ ├── notification_policies.yml # Ruteo de notificaciones por severidad
│ └── mute_timings.yml # 🆕 Ventanas de mantenimiento (Fase 3)
│
├── sql/
│ ├── schema.sql # DDL: devices, network_telemetry (hypertable), vistas
│ └── panels.sql # Queries de referencia para los paneles
│
├── docker-compose.yml # Orquestación: timescaledb + grafana + webhook-service
└── README.md
---

## 🚀 Requisitos

- **Docker** 20.10+
- **Docker Compose** 2.0+
- **4 GB RAM** mínimo (recomendado 8 GB)
- **2 GB** de espacio en disco para volúmenes de datos

---

## ⚙️ Instalación

### 1. Clonar el repositorio

```bash
git clone <repo-url>
cd noc-observability-pipeline
```

### 2. Levantar la infraestructura

El Webhook Service se construye desde su propio Dockerfile, así que la primera vez conviene forzar el build:

```bash
docker-compose up -d --build
```

Verifica que los **tres** servicios estén corriendo:

```bash
docker-compose ps
```

Esperado:
NAME IMAGE STATUS PORTS
timescaledb timescale/timescaledb:latest-pg16 Up 0.0.0.0:5432->5432/tcp
grafana grafana/grafana-oss:latest Up 0.0.0.0:3000->3000/tcp
webhook_service noc-observability-webhook Up 0.0.0.0:8000->8000/tcp

### 3. Inicializar el esquema principal (telemetría)

```bash
docker exec -i timescaledb psql -U noc_user -d noc < sql/schema.sql
```

Verifica las tablas y vistas creadas:

```bash
docker exec -i timescaledb psql -U noc_user -d noc \
  -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public';"
```

Deberías ver `devices`, `network_telemetry` y las vistas `v_telemetry_ts`, `v_event_counts`, `v_device_latest`, `v_recent_anomalies`.

### 4. Inicializar el esquema del Webhook Service

Este paso es **nuevo** y no se puede omitir: sin esta tabla, el Webhook Service recibirá las alertas pero fallará al persistirlas.

```bash
docker exec -i timescaledb psql -U noc_user -d noc < webhook-service/webhook_service.sql
```

Confirma la tabla `incident_logs`:

```bash
docker exec -i timescaledb psql -U noc_user -d noc \
  -c "\d incident_logs"
```

### 5. Verificar el Webhook Service

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

---

## ▶️ Uso

### Ejecutar el simulador de telemetría

> ⚠️ `simulator.py` usa imports planos (`from config import DEVICES`), así que debes ejecutarlo **desde dentro de** `python-simulator/`. Correrlo desde la raíz del proyecto falla con `ModuleNotFoundError: No module named 'config'`.

```bash
cd python-simulator
python simulator.py --fmt postgres --interval 2 --batch 3 \
  --pg-dsn "postgresql://noc_user:secret@localhost:5432/noc"
```

Logs esperados:
[INFO] [SIM] Iniciando simulador → PostgreSQL/TimescaleDB [POSTGRES]
[INFO] [SIM] [WARN ] dist-sw-01 CPU=62.5% LAT= 45.3ms LOSS= 0.50% eth0 UP
[INFO] [SIM] [CRITICAL] core-rtr-01 CPU=94.2% LAT= 312.1ms LOSS=12.50% eth1 UP

### Acceder a Grafana

Abre `http://localhost:3000`.

**Credenciales por defecto (solo laboratorio):**
- Usuario: `admin`
- Contraseña: `admin`

Ve a **Dashboards → NOC — Network Telemetry** para ver los 3 paneles en vivo.

### Forzar una alerta de punta a punta

Para validar el circuito completo (Grafana dispara → Webhook Service persiste) sin depender del azar del simulador:

```bash
cd python-simulator
python force_alert_test.py --minutes 5 \
  --pg-dsn "postgresql://noc_user:secret@localhost:5432/noc"
```

En 2–3 minutos deberías ver la regla pasar a `Firing` en **Alerting → Alert rules**, y el incidente aparecer en `incident_logs`:

```bash
docker exec -i timescaledb psql -U noc_user -d noc \
  -c "SELECT received_at, status, alert_name FROM incident_logs ORDER BY received_at DESC LIMIT 5;"
```

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

**Cambio de diseño relevante:** ambos contact points (`noc-webhook-default`, `noc-webhook-critical`) apuntan hoy al **Webhook Service interno** (`type: webhook`, `url: http://webhook-service:8000/alert`) en lugar de a un canal de Slack externo. Esto significa que cada disparo de alerta queda **persistido y auditable en `incident_logs`** por defecto, sin depender de un servicio de terceros.

Integrar Slack, Teams o PagerDuty sigue siendo posible y se documenta en la sección [🔧 Configuración en Producción](#-configuración-en-producción).

### Ruteo de notificaciones (`notification_policies.yml`)

| Condición | Receptor | Group Wait | Repeat |
|---|---|---|---|
| `severity = critical` | `noc-webhook-critical` | 10s | 20s |
| `severity = warning` | `noc-webhook-default` | 1m | 6h |
| (default) | `noc-webhook-default` | 30s | 4h |

**Group By:** `alertname, hostname` — agrupa alertas del mismo tipo en el mismo dispositivo.

### 🆕 Mute Timings — ventanas de mantenimiento (Fase 3)

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

Durante esa franja, las reglas siguen evaluándose y pueden pasar a `Firing`, pero **no se envían notificaciones** — ideal para ventanas de mantenimiento programado sin tener que deshabilitar reglas a mano.

### Validar el circuito de alertas

```bash
# 1. Confirmar que las reglas se aprovisionaron
docker logs grafana | grep -i "provisioned alert rule"

# 2. Ver estado de las reglas vía API
curl -u admin:admin http://localhost:3000/api/v1/provisioning/alert-rules | jq '.[] | {uid, title, state}'

# 3. Probar el contact point manualmente
# UI: Alerting → Contact points → noc-webhook-default → Test
```

---

## 📊 Estructura de Datos

### `network_telemetry` (hypertable)

```sql
ts               TIMESTAMPTZ      -- partition key
hostname         TEXT             -- FK → devices
ip               INET
role             device_role      -- core-router | distribution-sw | access-sw
severity         severity_level   -- INFO | WARN | ERROR | CRITICAL
message          TEXT
cpu_pct          DOUBLE PRECISION -- 0-100
latency_ms       DOUBLE PRECISION -- ms
packet_loss_pct  DOUBLE PRECISION -- 0-100
interface        TEXT
iface_status     iface_state      -- UP | DOWN
peer_ip          INET
```

### `incident_logs` — 🆕 tabla del Webhook Service

```sql
id            BIGSERIAL PRIMARY KEY
received_at   TIMESTAMPTZ NOT NULL DEFAULT now()
status        TEXT              -- 'firing' | 'resolved' (según payload de Grafana)
alert_name    TEXT              -- extraído de alerts[0].labels.alertname
payload       JSONB NOT NULL    -- payload completo de Grafana, indexado con GIN
```

### Vistas para Grafana

| Vista | Propósito |
|---|---|
| `v_telemetry_ts` | Time series: latencia, CPU, packet loss por dispositivo |
| `v_event_counts` | Conteo de eventos por severidad en buckets de 5m |
| `v_device_latest` | Último estado registrado por dispositivo |
| `v_recent_anomalies` | Eventos `WARN+` en la última hora |

---

## 🔍 Troubleshooting

### "AlertRule has no datasource"
**Causa:** la UID en `alert_rules.yml` (`timescaledb_noc`) no coincide con la UID real del datasource.
**Solución:** copia la UID real desde **Administration → Connections → Datasources** y reemplázala en `alert_rules.yml`.

### "Connection refused" entre Grafana y PostgreSQL
```bash
docker network inspect noc_net
docker exec grafana ping timescaledb
```
Confirma que `timescaledb`, `grafana` y `webhook_service` estén en la misma red `noc_net`.

### Las alertas no disparan pese a haber anomalías
1. El simulador no está corriendo → reinícialo con `--interval 2` y espera al menos 3 min
2. Las métricas no superan el umbral → sube la intensidad con `--interval 0.3 --batch 10`
3. Estás dentro de la ventana de `mute_timings.yml` (martes 14:50–15:10) → las reglas disparan pero no notifican, es comportamiento esperado

### El Webhook Service responde `persisted: false`
**Causa:** la tabla `incident_logs` no existe o la conexión a PostgreSQL falló.
**Solución:**
```bash
docker logs webhook_service --tail 50
docker exec -i timescaledb psql -U noc_user -d noc -c "\d incident_logs"
```
Si la tabla no existe, corre el paso 4 de instalación (`webhook-service/webhook_service.sql`).

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
```bash
docker-compose down
docker-compose up -d
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

Al ser un servicio FastAPI stateless (toda la persistencia vive en PostgreSQL), es horizontalmente escalable: súbelo detrás de un balanceador y aumenta `maxconn` en el pool de conexiones según el volumen esperado de alertas.

---

## 🔐 Seguridad

### Credenciales por defecto (solo laboratorio — no usar en producción)

- **PostgreSQL:** usuario `noc_user`, contraseña `secret`
- **Grafana Admin:** usuario `admin`, contraseña `admin`
- **Webhook Service:** hereda las credenciales de PostgreSQL vía variables de entorno (`PG_HOST`, `PG_PORT`, `PG_DB`, `PG_USER`, `PG_PASSWORD`)

### En producción

- Usa variables de entorno vía `.env` (ya soportado por `docker-compose`)
- Almacena secretos en HashiCorp Vault o AWS/GCP Secrets Manager
- Cambia la contraseña de Grafana Admin inmediatamente tras el primer despliegue
- El endpoint `POST /alert` del Webhook Service no tiene autenticación — restringe su exposición a la red interna (`noc_net`) y no publiques el puerto `8000` fuera del host en producción

---

## 📈 Roadmap

### ✅ Fase 2 — Notificaciones y alertas nativas (completada)
- ✅ Alertas nativas de Grafana aprovisionadas 100% vía IaC
- ✅ Ruteo por severidad con políticas de notificación diferenciadas

### ✅ Fase 3 — Recepción y resiliencia operativa (completada)
- ✅ Microservicio Webhook (FastAPI) para recibir y persistir alertas
- ✅ Mute Timings para ventanas de mantenimiento programado
- ✅ Tabla `incident_logs` como bitácora auditable de incidentes

### 🔜 Fase 4 — Escalado avanzado
- [ ] Integración del Webhook Service con JIRA/ServiceNow para auto-tickets
- [ ] Dashboards de postmortem sobre `incident_logs`
- [ ] Autenticación en `POST /alert` (token compartido o mTLS interno)
- [ ] Escalado a múltiples regiones geográficas

### 🔮 Fase 5 — ML y anomalía adaptativa
- [ ] Detección de anomalías basada en histórico (Prophet / Isolation Forest)
- [ ] Baselines dinámicos por hora del día / día de la semana
- [ ] Deduplicación inteligente de alertas repetidas

---

## 📚 Referencias

- **Grafana Unified Alerting:** https://grafana.com/docs/grafana/latest/alerting/
- **Grafana Provisioning:** https://grafana.com/docs/grafana/latest/administration/provisioning/
- **Mute Timings:** https://grafana.com/docs/grafana/latest/alerting/configure-notifications/mute-timings/
- **TimescaleDB:** https://docs.timescaledb.com/
- **FastAPI:** https://fastapi.tiangolo.com/

---

## 📝 Contribuciones

Este proyecto sigue **Infrastructure as Code** como principio rector. Cualquier cambio en alertas, dashboards, datasources o en el Webhook Service debe pasar por código y Git.

**Workflow:**
1. Edita el YAML/código correspondiente
2. Commit descriptivo
3. Abre PR
4. Redeploy: `docker-compose down && docker-compose up -d --build`
5. Valida el cambio en la UI o vía `curl`/API

---

## 📄 Licencia

[Especifica tu licencia aquí — ej. MIT, Apache 2.0]

---

**Mantenido por:** [Tu equipo NOC]
**Última actualización:** Agosto 2026
**Versión:** 3.0 (Webhook Service + Mute Timings)