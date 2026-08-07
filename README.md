# 📡 NOC Observability Pipeline

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=for-the-badge&logo=grafana&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2CA5E0?style=for-the-badge&logo=docker&logoColor=white)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-009639?style=for-the-badge&logo=timescaledb&logoColor=white)

Un pipeline de observabilidad de extremo a extremo diseñado para simular, ingerir, almacenar y visualizar telemetría de red en un entorno de Centro de Operaciones de Red (NOC). Implementa una arquitectura basada en contenedores con **Infrastructure as Code (IaC)** completa, incluyendo alertas automatizadas nativas de Grafana.

## 🏗️ Arquitectura del Sistema

El ecosistema está compuesto por **tres capas principales**, todas orquestadas mediante **Docker Compose**:

### Capa 1: Ingesta (Python Simulator)
Un simulador modular que genera **métricas de red realistas**:
- **Latencia (RTT):** 10-50ms con jitter gaussiano, picos hasta 2000ms en degradaciones
- **Packet Loss:** 0-0.5% nominal, hasta 35% en eventos CRITICAL
- **CPU Usage:** 15-45% nominal, hasta 100% en sobrecarga
- Fluctuaciones estadísticas aplicadas vía `Gaussian jitter` para emular comportamiento real
- Soporte para múltiples dispositivos (core routers, distribution switches, access switches)

### Capa 2: Almacenamiento (TimescaleDB/PostgreSQL)
Base de datos optimizada para **series de tiempo de alto volumen**:
- **Hyper-tables particionadas por tiempo** (chunks de 1 día) → compresión automática a los 7 días
- **Vistas materializadas** para queries rápidas de Grafana
- **Índices multi-columna** (`hostname_ts`, `severity_ts`, `severity_hostname_ts`)
- **Retención automática** de 90 días
- ~85-95% compresión en telemetría histórica

### Capa 3: Visualización y Alertas (Grafana OSS)
Dashboard interactivo aprovisionado íntegramente vía **Infrastructure as Code**:
- **3 paneles principales:** Time series (latencia/CPU), Heatmap (packet loss), Stat (eventos críticos)
- **Unified Alerting:** 3 reglas de alerta provisionadas automáticamente
- **Políticas de ruteo** por severidad (CRITICAL → canal dedicado, WARNING → general)
- **Contact points** preparados para webhooks de Slack/Teams/PagerDuty

---

## 📂 Estructura del Proyecto

```
.
├── python-simulator/
│   ├── main.py              # Punto de entrada (CLI con args)
│   ├── simulator.py         # Bucle principal de generación
│   ├── config.py            # Dispositivos, base de datos, severidades
│   ├── log_builder.py       # Construcción de registros de eventos
│   ├── metrics.py           # Generación de métricas con anomalías
│   ├── writer.py            # Sinks: CSV, JSONL, PostgreSQL
│   └── database.py          # Connection pool de PostgreSQL
│
├── grafana/provisioning/
│   ├── datasources/
│   │   └── timescaledb.yaml     # Datasource PostgreSQL preconfigurado
│   ├── dashboards/
│   │   ├── dashboards.yaml      # Proveedor de dashboards
│   │   └── noc_telemetry.json   # Dashboard principal (3 paneles)
│   └── alerting/                # ← NUEVO: Alertas provisioned
│       ├── alert_rules.yaml          # 3 reglas de alerta
│       ├── contact_points.yaml       # Configuración de webhooks
│       └── notification_policies.yaml # Ruteo de notificaciones
│
├── sql/
│   ├── schema.sql           # DDL: tables, hypertables, índices
│   └── panels.sql           # Queries para los 3 paneles
│
├── docker-compose.yml       # Orquestación de servicios
└── README.md                # Este archivo
```

---

## 🚀 Inicio Rápido

### Requisitos
- **Docker** 20.10+
- **Docker Compose** 2.0+
- **4 GB RAM** mínimo (recomendado 8 GB)
- **2 GB espacio en disco** para volúmenes de datos

### 1. Clonar y preparar

```bash
git clone <repo-url>
cd noc-observability-pipeline
```

### 2. Levantar infraestructura

```bash
docker-compose up -d
```

Verifica que todos los servicios estén corriendo:

```bash
docker-compose ps
```

Esperado:
```
NAME           IMAGE                           STATUS
timescaledb    timescale/timescaledb:latest    Up 2 minutes
grafana        grafana/grafana-oss:latest      Up 2 minutes
```

### 3. Inicializar base de datos

Copia el schema a la BD:

```bash
docker exec -i timescaledb psql -U noc_user -d noc < sql/schema.sql
```

Verifica que las tablas se crearon:

```bash
docker exec -i timescaledb psql -U noc_user -d noc \
  -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public';"
```

Deberías ver: `network_telemetry`, `devices`, y varias vistas (`v_telemetry_ts`, `v_event_counts`, etc.).

### 4. Ejecutar simulador

```bash
cd python-simulator
python simulator.py --fmt postgres --interval 2 --batch 3 \
  --pg-dsn "postgresql://noc_user:secret@localhost:5432/noc"
```

Verás logs como:
```
[INFO] [SIM] Iniciando simulador → PostgreSQL/TimescaleDB [POSTGRES]
[INFO] [SIM]    [WARN    ] dist-sw-01       CPU=62.5%   LAT=  45.3ms  LOSS= 0.50%  eth0 UP
[INFO] [SIM]    [CRITICAL] core-rtr-01      CPU=94.2%   LAT= 312.1ms  LOSS=12.50%  eth1 UP
```

### 5. Acceder a Grafana

Abre `http://localhost:3000` en tu navegador.

**Credenciales por defecto:**
- Usuario: `admin`
- Contraseña: `admin`

Dirígete a **Dashboards** → **NOC Network Telemetry** para ver los 3 paneles en vivo.

---

## 🚨 Sistema de Alertas Provisioned (Nuevo)

### Visión General

Las **alertas se aprovisionan automáticamente** al levantar el contenedor de Grafana. No requiere configuración manual en la UI. Las reglas, contact points y políticas viven en YAML dentro de `grafana/provisioning/alerting/`.

#### Filosofía IaC
- **Versionable en Git:** Todos los cambios de alertas pasan por code review
- **Reproducible:** Redeploys crean la misma configuración
- **Idempotente:** Correr `docker-compose up -d` múltiples veces no causa duplicados ni conflictos

### Archivos de Configuración

#### 1. `alert_rules.yaml`

Define **3 reglas de alerta** que evalúan telemetría en tiempo real:

**Regla 1: Latencia Crítica Sostenida**
- **Umbral:** Latencia promedio > 150 ms
- **Duración:** Sostenido 3 minutos
- **Severidad:** `critical`
- **Trigger:** Degradación de enlace, congestión
- **Query:** `AVG(latency_ms) por hostname en buckets de 1m`

**Regla 2: Packet Loss Elevado**
- **Umbral:** Packet loss > 10%
- **Duración:** Sostenido 2 minutos
- **Severidad:** `critical`
- **Trigger:** Pérdida de paquetes, QoS degradado
- **Query:** `AVG(packet_loss_pct) por hostname en buckets de 1m`

**Regla 3: CPU Sostenido (Bonus)**
- **Umbral:** CPU > 85%
- **Duración:** Sostenido 5 minutos
- **Severidad:** `warning`
- **Trigger:** Riesgo de degradación en plano de control
- **Query:** `AVG(cpu_pct) por hostname en buckets de 1m`

**Patrón de evaluación:**
```
Query A (PostgreSQL)
    ↓
Reduce B (último valor por serie)
    ↓
Threshold C (comparar contra límite)
    ↓
Fire/Resolve (si supera umbrales por tiempo mínimo)
```

#### 2. `contact_points.yaml`

Define **2 puntos de contacto** (webhooks) para notificaciones:

| Nombre | URL | Propósito |
|--------|-----|----------|
| `noc-webhook-default` | `https://hooks.slack.com/services/PLACEHOLDER/...` | Notificaciones normales (WARNING) |
| `noc-webhook-critical` | `https://hooks.slack.com/services/PLACEHOLDER_CRITICAL/...` | Alertas críticas (CRITICAL) → canal dedicado |

**⚠️ Placeholders:** Las URLs aún no son válidas. Reemplázalas en **Fase 2** con URLs reales de Slack Incoming Webhooks o Teams Connectors.

#### 3. `notification_policies.yaml`

Configura **ruteo inteligente** de alertas por severidad:

| Condición | Receptor | Group Wait | Repeat |
|-----------|----------|-----------|--------|
| `severity = critical` | `noc-webhook-critical` | 10s | 1h |
| `severity = warning` | `noc-webhook-default` | 1m | 6h |
| (otros) | `noc-webhook-default` | 30s | 4h |

**Group By:** `alertname, hostname` → agrupa alertas del mismo tipo en el mismo dispositivo.

---

## ✅ Validar Alertas (Testing)

### Test 1: Verificar carga en UI

```bash
docker logs grafana | grep -i alert
```

Busca líneas como:
```
lvl=info msg="Provisioned alert rule" uid=latency-critical-001 title="Latencia Crítica Sostenida"
lvl=info msg="Provisioned alert rule" uid=packetloss-critical-002 title="Packet Loss Elevado"
```

### Test 2: Confirmar reglas en Grafana

1. Abre `http://localhost:3000`
2. Ve a **Alerting → Alert rules**
3. Deberías ver el folder **NOC Alerts** con 3 reglas en estado `Normal` (verde)

### Test 3: Forzar anomalía real

Corre el simulador con `--count` bajo para inyectar eventos rápidamente:

```bash
cd python-simulator
python simulator.py --fmt postgres --interval 0.3 --batch 10 --count 500 \
  --pg-dsn "postgresql://noc_user:secret@localhost:5432/noc"
```

Esto genera **latencia y packet loss altos** para forzar disparo de alertas en ~1-3 minutos.

### Test 4: Observar transición de estado

En **Alerting → Alert rules**, vigila que el estado pase de `Normal` → `Pending` → `Firing` (rojo).

Alternativamente, usa la API:

```bash
curl -u admin:admin http://localhost:3000/api/v1/provisioning/alert-rules | jq '.[] | {uid, title, state}'
```

### Test 5: Probar contact point (sin URL real)

Ve a **Alerting → Contact points** → selecciona `noc-webhook-default` → **Test**.

Verás un error HTTP (porque es un placeholder), pero confirma que el routing de notificaciones funciona correctamente. Cuando tengas la URL real de Slack/Teams, el mensaje llegará al canal.

---

## 🔧 Configuración en Producción

### Habilitar SMTP (para alertas por email)

Descomenta y completa en `docker-compose.yml`:

```yaml
grafana:
  environment:
    GF_SMTP_ENABLED:      "true"
    GF_SMTP_HOST:         smtp.gmail.com:587
    GF_SMTP_USER:         alerts@tudominio.com
    GF_SMTP_PASSWORD:     tu-app-password
    GF_SMTP_FROM_ADDRESS: alerts@tudominio.com
    GF_SMTP_FROM_NAME:    "NOC Alerts"
```

Luego añade un contact point de tipo `email` en `contact_points.yaml`.

### Integrar con Slack

Crea un **Incoming Webhook** en Slack:

1. Ve a tu workspace de Slack → **Settings → Apps & integrations → Manage → Custom Integrations → Incoming Webhooks**
2. Haz clic en **Add New Webhook to Workspace**
3. Selecciona el canal (ej. `#noc-alerts`, `#noc-critical`)
4. Copia la URL generada
5. Reemplaza los placeholders en `grafana/provisioning/alerting/contact_points.yaml`:

```yaml
contactPoints:
  - orgId: 1
    name: noc-webhook-critical
    receivers:
      - uid: noc-webhook-002
        type: webhook
        settings:
          url: https://hooks.slack.com/services/YOUR/ACTUAL/WEBHOOK_URL_HERE
```

6. Redeploy:

```bash
docker-compose down
docker-compose up -d
```

### Integrar con PagerDuty

Similar a Slack, pero usando el **Integration Key** de PagerDuty y tipo `pagerduty` en contact points.

---

## 📊 Estructura de Datos

### Tabla `network_telemetry` (hypertable)

```sql
ts          TIMESTAMPTZ      -- timestamp (partition key)
hostname    TEXT             -- nombre del dispositivo
ip          INET             -- dirección IP
role        device_role      -- core-router, distribution-sw, access-sw
severity    severity_level   -- INFO, WARN, ERROR, CRITICAL
message     TEXT             -- descripción del evento
cpu_pct     DOUBLE PRECISION -- 0-100%
latency_ms  DOUBLE PRECISION -- RTT en milisegundos
packet_loss_pct DOUBLE PRECISION -- 0-100%
interface   TEXT             -- nombre de interfaz (eth0, ge-0/0/0)
iface_status iface_state     -- UP, DOWN
peer_ip     INET             -- IP del peer remoto
```

### Vistas para Grafana

| Vista | Propósito |
|-------|-----------|
| `v_telemetry_ts` | Time series: latencia, CPU, packet loss por dispositivo |
| `v_event_counts` | Conteo de eventos por severidad en ventanas de 5m |
| `v_device_latest` | Estado actual de cada dispositivo (último registro) |
| `v_recent_anomalies` | Eventos WARN+ en la última hora (tabla de alertas) |

---

## 🔍 Troubleshooting

### "AlertRule has no datasource"

**Causa:** La UID del datasource en `alert_rules.yaml` no coincide con la UID real de TimescaleDB.

**Solución:**
1. Abre Grafana → **Administration → Connections → Datasources**
2. Copia la UID del datasource PostgreSQL
3. Reemplaza `timescaledb_noc` en `alert_rules.yaml` con la UID correcta

### "Connection refused" desde Grafana a PostgreSQL

**Causa:** El contenedor de Grafana no puede alcanzar TimescaleDB.

**Solución:**
```bash
docker network ls
docker network inspect noc_net
docker exec grafana ping timescaledb
```

Verifica que ambos contenedores estén en la red `noc_net`.

### Alertas no disparan aunque hay anomalías

**Causas comunes:**
1. El simulador no está corriendo → reinicia con `--interval 2` y espera 3+ minutos
2. Las métricas están dentro del umbral normal → incrementa `--interval 1` y `--batch 20`
3. Datasource desconectado → ve a **Alerting → Alert rules**, haz clic en una regla, busca errores en logs

**Debug:**
```bash
docker logs grafana | grep -i "alert\|error\|datasource" | tail -30
```

---

## 📈 Roadmap Futuro

### Fase 2: Notificaciones Reales
- ✅ Estructura IaC presente
- [ ] Reemplazar placeholders con URLs reales de Slack/Teams
- [ ] Testear flujo end-to-end de notificaciones

### Fase 3: Escalado Avanzado
- [ ] Silenciadores de alertas (mantenimiento programado)
- [ ] Dashboards de postmortem (registrar incidentes)
- [ ] Integración con JIRA/ServiceNow para auto-tickets
- [ ] Escalado a múltiples regiones geográficas

### Fase 4: ML y Anomalía Adaptativa
- [ ] Detección de anomalías basada en histórico (Prophet/Isolationfor Forest)
- [ ] Baselines dinámicos por hora del día / día de la semana
- [ ] Deduplicación inteligente de alertas

---

## 📚 Referencias

- **Grafana Unified Alerting:** https://grafana.com/docs/grafana/latest/alerting/
- **Provisioning:** https://grafana.com/docs/grafana/latest/administration/provisioning/
- **TimescaleDB:** https://docs.timescaledb.com/
- **PostgreSQL en Docker:** https://hub.docker.com/_/postgres

---

## 📝 Contribuciones

Este proyecto sigue **Infrastructure as Code** como principio. Cualquier cambio en alertas, dashboards o datasources debe hacerse vía YAML/JSON y commitearse a Git.

**Workflow para cambios:**
1. Edita el archivo YAML correspondiente en `grafana/provisioning/`
2. Haz commit con mensaje descriptivo
3. Abre PR con descripción de cambios
4. Redeploy con `docker-compose down && docker-compose up -d`
5. Valida en UI que los cambios se reflejen

---

## 🔐 Seguridad

### Credenciales por Defecto (No usar en Producción)

- **PostgreSQL:** usuario `noc_user`, contraseña `secret`
- **Grafana Admin:** usuario `admin`, contraseña `admin`

**En producción:**
- Usa variables de entorno (`docker-compose` las soporte via `.env`)
- Almacena credenciales en HashiCorp Vault o AWS Secrets Manager
- Cambia contraseña de Grafana Admin inmediatamente

### Webhooks de Alertas

Las URLs de webhooks en `contact_points.yaml` son **públicas por naturaleza** (Slack/Teams los requieren). Usa canales privados/restringidos en Slack/Teams para limitar visibilidad.

---

## 📄 Licencia

[Especifica tu licencia aquí — ej. MIT, Apache 2.0]

---

**Mantenido por:** [Tu equipo NOC]  
**Última actualización:** Agosto 2026  
**Versión:** 2.0 (con Unified Alerting)
