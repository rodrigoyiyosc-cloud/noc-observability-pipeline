# 📡 NOC Observability Pipeline

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-009639?style=for-the-badge&logo=timescaledb&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=for-the-badge&logo=grafana&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2CA5E0?style=for-the-badge&logo=docker&logoColor=white)
![Jira](https://img.shields.io/badge/Jira-0052CC?style=for-the-badge&logo=jira&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)
![Scikit--Learn](https://img.shields.io/badge/scikit--learn-F7931E?style=for-the-badge&logo=scikitlearn&logoColor=white)
![Jupyter](https://img.shields.io/badge/Jupyter-F37626?style=for-the-badge&logo=jupyter&logoColor=white)

Pipeline de observabilidad de extremo a extremo — **multi-región** y ahora **auto-inteligente** — para simular, ingerir, almacenar, visualizar, alertar, **ticketizar**, **analizar con ML** y **operar conversacionalmente** telemetría de red en un entorno de Centro de Operaciones de Red (NOC). Arquitectura 100% contenerizada, gobernada por **Infrastructure as Code**: dashboards, reglas de alerta, ventanas de mantenimiento, el motor de recepción/escalado de incidentes y ahora el propio **sistema multiagente de decisión** viven como código versionado, no como clics en una UI.

---

## 🧭 Acerca del Proyecto

Este repositorio implementa un **loop de alerta cerrado, geográficamente distribuido y con criterio propio**. Tres simuladores regionales (`us-east`, `eu-west`, `sa-south`) alimentan una única hypertable en TimescaleDB. Grafana detecta la anomalía, la enruta según severidad, respeta las ventanas de mantenimiento definidas en código, y un microservicio propio en **FastAPI** — autenticado, con cliente Jira nativo y ahora con **deduplicación inteligente vía JQL** — recibe, registra, prioriza y **escala automáticamente cada incidente a un ticket de Jira**, sin intervención humana y sin generar *ticket storms*.

Con la **Fase 5 completada**, el pipeline deja de ser puramente reactivo (umbral → alerta → ticket) para incorporar una capa de **inteligencia operativa activa**: un modelo `IsolationForest` entrenado sobre la telemetría histórica detecta anomalías dinámicas que los umbrales estáticos no capturan, y un **sistema multiagente (NOC-MAS)** orquestado con **LangGraph** — con un Supervisor, un Data Agent (Text-to-SQL seguro) y un Action Agent (ejecución de remediaciones vía payloads Pydantic), todos bajo una compuerta de seguridad **Human-in-the-Loop** — es capaz de diagnosticar y proponer acciones sobre el propio incidente. Todo esto es accesible en lenguaje natural desde una **ChatOps UI en Streamlit**.

Cinco capas, un solo `docker compose up`.

---

## 🏗️ Arquitectura y Stack

El ecosistema está compuesto por **cinco capas**, todas orquestadas mediante **Docker Compose** sobre una red bridge compartida (`noc_net`):

```
┌───────────────────────────────────────────────────────────────────────────┐
│ CAPA 1 · SIMULACIÓN                                                        │
│  simulator-us-east │ simulator-eu-west │ simulator-sa-south                │
│  (CPU, latencia, packet loss, iface state — 5 dispositivos c/u)            │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │ INSERT (psycopg2 / SQL sink)
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ CAPA 2 · ALMACENAMIENTO                                                    │
│  TimescaleDB (PG16) — hypertable network_telemetry                         │
│  compresión 7d · retención 90d · vistas telemetría + postmortem            │
└───────────────┬─────────────────────────────────────────┬─────────────────┘
                │ SELECT (datasource)                      │ SELECT (Jupyter/psycopg2)
                ▼                                           ▼
┌───────────────────────────────────┐   ┌───────────────────────────────────┐
│ CAPA 3 · VISUALIZACIÓN             │   │ CAPA 3.5 · ML ANALYTICS HUB        │
│  Grafana OSS (Unified Alerting)    │   │  Jupyter (noc_net) + IsolationForest│
│  dashboards + alert rules (IaC)    │   │  detección de anomalías dinámicas   │
└───────────────────┬───────────────┘   └───────────────────┬───────────────┘
                     │ webhook (Bearer Token)                 │ hallazgos / features
                     ▼                                        │
┌───────────────────────────────────────────────────────────◄┘
│ CAPA 4 · DECISIÓN — FastAPI + NOC-MAS (LangGraph)                          │
│  POST /alert → dedupe JQL → insert incident_logs                           │
│  Supervisor ──▶ Data_Agent (Text-to-SQL) ──▶ Action_Agent (Pydantic)       │
│              └─▶ human_in_the_loop (HITL gate) ─▶ END                     │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │ REST (issue / comment / transition)
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ CAPA 5 · ESCALADO Y OPERACIÓN — Jira Cloud + ChatOps UI (Streamlit)        │
│  tickets deduplicados por labels (fingerprint) │ chat operativo NL         │
└───────────────────────────────────────────────────────────────────────────┘
```

### Capa 1 — Ingesta Multi-Región (`python-simulator/`)
Simulador modular, parametrizado por la variable de entorno `REGION`, que genera **métricas de red realistas** para 5 dispositivos por región (core routers, distribution switches, access switches):
- **3 réplicas concurrentes** vía Docker Compose: `simulator-us-east`, `simulator-eu-west`, `simulator-sa-south` — mismo build, distinto `REGION`
- **Latencia (RTT):** baseline por región con jitter gaussiano, picos de degradación controlados
- **Packet Loss:** nominal bajo, picos altos en eventos `CRITICAL`
- **CPU:** baseline por dispositivo, hasta saturación en sobrecarga
- Hostnames prefijados por región (`euw1-*`, `sas1-*`) para evitar colisiones; `us-east` se mantiene sin prefijo por retrocompatibilidad
- Múltiples sinks intercambiables vía `--fmt`: `csv`, `jsonl`, `postgres`
- Incluye `force_alert_test.py`: inyector determinístico de telemetría `CRITICAL` sostenida sobre `core-rtr-01`
- Incluye `simulate_mttr_incidents.py`: Chaos Engineering — 3 incidentes concurrentes (`firing`→`resolved`) vía HTTP directo al Webhook, usado también para poblar el dataset de entrenamiento del modelo `IsolationForest`

### Capa 2 — Almacenamiento Multi-Región (TimescaleDB / PostgreSQL 16)
- **Hypertable** `network_telemetry` particionada por tiempo (chunks de 1 día), con columna `region` indexada y como parte del `compress_segmentby`
- Tabla de dimensiones `devices` extendida con `region`
- **Compresión automática** a los 7 días → 85–95% de ahorro típico
- **Retención automática** de 90 días vía `add_retention_policy`
- **5 vistas** para Grafana, incluyendo `v_region_health`
- **Vistas de postmortem sobre JSONB** (`incident_views.sql`): `v_incident_events`, `v_incident_mttr`, `v_incident_latest_status`

### Capa 3 — Visualización e Inteligencia Operativa (Grafana OSS, Unified Alerting)
Dos dashboards y el sistema de alertas **100% aprovisionados vía IaC** (`grafana/provisioning/`):
- **Dashboard `NOC — Network Telemetry`**: eventos críticos, time series de latencia/CPU, snapshot por dispositivo — filtrable por `$region`/`$hostname`
- **Dashboard `NOC - Postmortem & MTTR`**: MTTR general, MTTR por dispositivo, conteo de incidentes, historial
- **3 reglas de alerta** (`alert_rules.yml`) evaluadas cada minuto
- **Contact points** con Bearer Token hacia el Webhook Service
- **Notification policies** con ruteo por severidad
- **Mute timings** — ventanas de mantenimiento

### 🆕 Capa 3.5 — ML Analytics Hub (`jupyter/`)
Contenedor **Jupyter** desplegado dentro de `noc_net`, conectado directamente a TimescaleDB, dedicado a analítica avanzada fuera del ciclo de vida operativo de Grafana:
- **Entrenamiento y validación de `IsolationForest`** (scikit-learn) sobre series históricas de `cpu_pct` y `latency_ms` para detectar picos inusuales que un umbral estático no captura — el modelo se adapta a la dinámica propia de cada dispositivo/región en vez de usar un corte fijo
- Complementa (no reemplaza) las reglas de alerta de Grafana: sirve como banco de pruebas para calibrar futuros umbrales dinámicos y como fuente de *features* para el Data_Agent del NOC-MAS
- Acceso vía `http://localhost:8888` protegido con `JUPYTER_TOKEN`
- Notebooks persistidos en `./jupyter/notebooks` (bind mount)

### 🆕 Capa 4 — Decisión: Webhook Service + NOC-MAS (FastAPI + LangGraph)
El punto de llegada de cada alerta, ahora con **deduplicación inteligente** y capacidad de **razonamiento multiagente**:

**Deduplicación JQL (anti Ticket Storm)**
- Antes de crear un ticket, `handle_jira_dedup()` construye una huella determinística (`slugify` de `alertname` + `hostname`) y ejecuta una búsqueda **JQL** contra `POST /rest/api/3/search/jql` (endpoint vigente — el clásico `GET/POST /rest/api/3/search` fue retirado por Atlassian y responde `410 Gone`) filtrando por `resolution = Unresolved` y ambos `labels`
- Si ya existe un ticket abierto para ese par alerta+dispositivo: se agrega un **comentario** ("⚠️ La anomalía PERSISTE") con las métricas actuales — **no se crea un ticket nuevo**
- Si el `status` entrante es `resolved`: comenta el cierre y **intenta transicionar** el ticket a `JIRA_RESOLVE_TRANSITION_NAME` (ej. `Done`/`Resolved`)
- Si no hay ticket abierto y la alerta está `firing`: crea el ticket con los labels de huella (`al-<alertname>`, `dev-<hostname>`) para que la siguiente búsqueda lo encuentre

**NOC-MAS — Sistema Multiagente (`src/`, Clean Architecture)**
Orquestación con **LangGraph** bajo un `StateGraph` jerárquico con enrutamiento determinista:
- `src/state.py` — `NOCState` (`TypedDict`): repositorio de estado compartido, con `messages: Annotated[Sequence[BaseMessage], operator.add]` para acumulación de historial entre nodos, más `incident_id`, `severity`, `next_agent`, `requires_human_approval`, `human_decision` y `context`
- `src/orchestrator.py` — nodo **Supervisor**: LLM (`ChatGroq`) con prompt PTCF que enruta a `Data_Agent`, `Action_Agent`, `human_in_the_loop` o `END`, con salida forzada a JSON vía `PydanticOutputParser` (`RouteResponse`)
- `src/nodes/data_agent.py` — **Data Agent**: Text-to-SQL **seguro** sobre TimescaleDB — solo `SELECT`, bloqueo por regex de `INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/GRANT/REVOKE/CREATE`, forzado a referenciar `network_telemetry`, `LIMIT 200` en la ejecución
- `src/nodes/action_agent.py` — **Action Agent**: genera acciones estructuradas (`CREATE_TICKET`, `SEND_ALERT`, `ACK_ALERT`, `ESCALATE`) con `action_payload` validado como JSON vía Pydantic
- **Compuerta HITL**: el grafo se compila con `interrupt_before=["human_in_the_loop"]` y `MemorySaver` como checkpointer — cualquier severidad `P1`, acción irreversible o ambigüedad detectada por el Supervisor detiene el flujo hasta aprobación humana
- **Sanitización para modelos Open Source**: `clean_think_tags()` limpia bloques `<think>...</think>` (típicos de modelos razonadores servidos vía Groq) antes de intentar el parseo Pydantic — con *fallback* seguro a `human_in_the_loop` si el parseo falla
- Ciclo del grafo: `supervisor → {Data_Agent | Action_Agent} → supervisor → ... → END`, con reentrada al Supervisor tras cada nodo especialista

### 🆕 Capa 5 — ChatOps UI (Streamlit) + Jira
- Servicio web interactivo en `http://localhost:8501` para interactuar en lenguaje natural con el ecosistema NOC
- Sidebar con estado de conectividad (Backend FastAPI, TimescaleDB, Orquestador LangGraph, Jira) y métricas rápidas (incidentes abiertos, MTTR promedio, agentes activos, uptime)
- Historial de chat en `st.session_state`, listo para conmutar del modo *standalone* actual a la invocación real de `orchestrator.invoke()` del NOC-MAS
- Los tickets creados/comentados por la deduplicación JQL y por el Action Agent llegan al mismo proyecto Jira, cerrando el loop: **detección → diagnóstico → decisión → registro**

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
│   ├── simulate_mttr_incidents.py   # Chaos Engineering: 3 incidentes concurrentes (firing→resolved)
│   └── requirements.txt
│
├── webhook_service/
│   ├── src/
│   │   ├── main.py                  # FastAPI: POST /alert (Bearer auth), GET /health, dedupe JQL + Jira
│   │   ├── state.py                 # 🆕 NOCState (TypedDict) — estado compartido del NOC-MAS
│   │   ├── orchestrator.py          # 🆕 StateGraph LangGraph + nodo Supervisor (PydanticOutputParser)
│   │   └── nodes/
│   │       ├── data_agent.py        # 🆕 Text-to-SQL seguro (solo SELECT) sobre network_telemetry
│   │       └── action_agent.py      # 🆕 Generación y ejecución de acciones estructuradas (Pydantic)
│   ├── requirements.txt             # fastapi, uvicorn[standard], psycopg2-binary, httpx, langgraph,
│   │                                 # langchain-groq, sqlalchemy, pydantic
│   ├── webhook_service.sql          # DDL de incident_logs (tabla + índices GIN)
│   └── Dockerfile
│
├── chatops-ui/
│   ├── app.py                       # 🆕 Streamlit — chat NL, sidebar de estado, métricas rápidas
│   ├── requirements.txt             # streamlit
│   └── Dockerfile
│
├── jupyter/
│   ├── notebooks/
│   │   └── anomaly_detection.ipynb  # 🆕 Entrenamiento/validación IsolationForest (CPU/latencia)
│   ├── requirements.txt             # scikit-learn, pandas, sqlalchemy, psycopg2-binary, matplotlib
│   └── Dockerfile
│
├── grafana/provisioning/
│   ├── datasources/
│   │   └── timescaledb.yaml             # Datasource PostgreSQL (uid fijo: timescaledb_noc)
│   ├── dashboards/
│   │   ├── dashboards.yaml              # Proveedor de dashboards (file-based)
│   │   ├── noc_telemetry.json           # Dashboard principal (con $region)
│   │   └── noc-postmortem-dashboard.json # Dashboard de Postmortem & MTTR
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
├── .env.example                      # Plantilla sin valores
├── .gitignore
├── .gitattributes
├── docker-compose.yml                # Orquestación: 9 servicios (ver tabla abajo)
└── README.md
```

---

## 🚀 Requisitos

- **Docker** 20.10+
- **Docker Compose** v2 (`docker compose`, sin guion)
- **8 GB RAM** mínimo (recomendado 12 GB — 3 simuladores + TimescaleDB + Grafana + Webhook Service/NOC-MAS + Jupyter + ChatOps UI)
- **3 GB** de espacio en disco para volúmenes de datos
- Cuenta de **Jira Cloud** con un API Token válido (requerido para auto-ticketing + deduplicación JQL)
- Cuenta de **Groq** con API Key válida (requerida para el Supervisor, Data Agent y Action Agent del NOC-MAS)
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
JIRA_RESOLVE_TRANSITION_NAME="Done"
JIRA_ISSUE_TYPE="Incident"

# ── PostgreSQL / TimescaleDB (opcional si difiere del default de compose) ──
PG_HOST=timescaledb
PG_PORT=5432
PG_DB=noc
PG_USER=noc_user
PG_PASSWORD=secret
PG_DSN=postgresql+psycopg2://noc_user:secret@timescaledb:5432/noc

# ── NOC-MAS (LangGraph + Groq) ───────────────────────────────────────────────
GROQ_API_KEY=reemplaza-con-tu-api-key-de-groq
NOC_SUPERVISOR_MODEL=llama3-8b-8192
NOC_DATA_AGENT_MODEL=llama3-8b-8192
NOC_ACTION_AGENT_MODEL=qwen/qwen3.6-27b

# ── ML Analytics Hub (Jupyter) ───────────────────────────────────────────────
JUPYTER_TOKEN=reemplaza-con-un-token-de-acceso

# ── Chaos Engineering / simuladores ──────────────────────────────────────────
WEBHOOK_URL=http://localhost:8000/alert
```

| Variable | Requerida | Descripción |
|---|---|---|
| `NOC_WEBHOOK_TOKEN` | ✅ Sí | Token Bearer compartido entre Grafana (`contact_points.yml`) y el Webhook Service. Sin él, el servicio **no arranca** (`RuntimeError`). |
| `JIRA_URL` / `JIRA_USER` / `JIRA_API_TOKEN` / `JIRA_PROJECT_KEY` | Opcional* | Credenciales de Jira Cloud. Sin ellas, `handle_jira_dedup()` responde `{"action": "skipped", "reason": "missing_credentials"}` sin romper la ingesta. |
| `JIRA_RESOLVE_TRANSITION_NAME` | Opcional | Nombre exacto de la transición de workflow usada para cerrar el ticket al recibir `status=resolved`. Default `Done`. |
| `JIRA_ISSUE_TYPE` | Opcional | Tipo de issue a crear en Jira. Default `Incident`. |
| `GROQ_API_KEY` | ✅ Sí (para NOC-MAS) | Autentica las llamadas `ChatGroq` del Supervisor, Data Agent y Action Agent. |
| `NOC_SUPERVISOR_MODEL` / `NOC_DATA_AGENT_MODEL` / `NOC_ACTION_AGENT_MODEL` | Opcional | Override del modelo Groq por nodo del grafo. |
| `PG_DSN` | ✅ Sí (para Data Agent / Jupyter) | DSN SQLAlchemy de solo lectura usado por `data_agent.py` y los notebooks. |
| `JUPYTER_TOKEN` | Opcional | Token de acceso al contenedor `jupyter-ml` (`http://localhost:8888`). |
| `PG_*` | Opcional | Sobrescriben los defaults ya definidos en `docker-compose.yml`. |
| `WEBHOOK_URL` | Opcional | Usada por `simulate_mttr_incidents.py` para apuntar a un Webhook Service distinto de `http://localhost:8000/alert`. |

\* Si cualquiera de las 4 variables de Jira falta, el servicio sigue funcionando con normalidad.

> ⚠️ Nunca commitees el `.env` real. Usa `.env.example` (sin valores) como plantilla para el equipo.

---

## ⚙️ Instalación y Despliegue

### 1. Clonar el repositorio

```powershell
git clone <repo-url>
cd noc-observability-pipeline
```

### 2. Configurar el `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

### 3. Levantar la infraestructura completa

`docker compose` levanta **9 servicios**: TimescaleDB, Grafana, Webhook Service (con NOC-MAS embebido), 3 simuladores regionales, Jupyter (ML Analytics Hub) y ChatOps UI (Streamlit).

```powershell
docker compose up -d --build
```

Verifica que **los nueve** servicios estén corriendo:

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
jupyter_ml           noc-observability-jupyter          Up            0.0.0.0:8888->8888/tcp
chatops_ui           noc-observability-chatops           Up            0.0.0.0:8501->8501/tcp
```

### 4. Inicializar el esquema principal (telemetría + regiones)

```powershell
Get-Content sql/schema.sql | docker exec -i timescaledb psql -U noc_user -d noc
```

```powershell
docker exec -i timescaledb psql -U noc_user -d noc `
  -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public';"
```

Deberías ver `devices`, `network_telemetry` y las vistas `v_telemetry_ts`, `v_event_counts`, `v_device_latest`, `v_recent_anomalies`, `v_region_health`.

```powershell
docker exec -i timescaledb psql -U noc_user -d noc `
  -c "SELECT region, COUNT(*) FROM devices GROUP BY region ORDER BY region;"
```

### 5. Inicializar el esquema del Webhook Service

```powershell
Get-Content webhook_service/webhook_service.sql | docker exec -i timescaledb psql -U noc_user -d noc
```

```powershell
docker exec -i timescaledb psql -U noc_user -d noc -c "\d incident_logs"
```

### 6. Inicializar las vistas de postmortem (JSONB → MTTR)

```powershell
Get-Content sql/incident_views.sql | docker exec -i timescaledb psql -U noc_user -d noc
```

```powershell
docker exec -i timescaledb psql -U noc_user -d noc `
  -c "SELECT viewname FROM pg_views WHERE viewname LIKE 'v_incident%';"
```

### 7. Verificar el Webhook Service (auth incluida)

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get

$headers = @{ Authorization = "Bearer $env:NOC_WEBHOOK_TOKEN" }
Invoke-RestMethod -Uri "http://localhost:8000/health" -Headers $headers -Method Get
```

### 8. Poblar datos de entrenamiento y validar el modelo ML

```powershell
cd python-simulator
python simulate_mttr_incidents.py --webhook-url "http://localhost:8000/alert"
cd ..
```

Abre `http://localhost:8888` (token = `JUPYTER_TOKEN`) y ejecuta `notebooks/anomaly_detection.ipynb` de punta a punta para entrenar y validar el `IsolationForest`.

### 9. Verificar el NOC-MAS y la ChatOps UI

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health" -Headers $headers -Method Get
Start-Process "http://localhost:8501"
```

Escribe una consulta en el chat (ej. *"muéstrame los dispositivos con CPU > 90% en la última hora"*) para validar el circuito Supervisor → Data_Agent → Supervisor.

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

En producción, los 3 simuladores ya corren automáticamente como servicios de `docker-compose.yml` — no requieren intervención manual.

### Acceder a Grafana

Abre `http://localhost:3000` (`admin` / `admin` en laboratorio). Navega a:
- **Dashboards → NOC — Network Telemetry**
- **Dashboards → NOC - Postmortem & MTTR**

### Forzar una alerta de punta a punta (incluye ticket Jira deduplicado)

```powershell
cd python-simulator
python force_alert_test.py --minutes 5 `
  --pg-dsn "postgresql://noc_user:secret@localhost:5432/noc"
```

Dispara el mismo `alertname`+`hostname` dos veces seguidas para confirmar que la segunda vez el Webhook Service **comenta** en vez de crear un ticket duplicado (`jira.action == "comment_added"`).

### Interactuar con el NOC-MAS desde la ChatOps UI

Abre `http://localhost:8501`. El sidebar muestra el estado de conectividad y métricas rápidas (incidentes abiertos, MTTR promedio, agentes activos, uptime). Escribe consultas o instrucciones en lenguaje natural en el campo de chat; el Supervisor decide si el flujo debe pasar por `Data_Agent`, `Action_Agent` o detenerse en la compuerta `human_in_the_loop`.

### Ejecutar el NOC-MAS directamente (fuera de la UI)

```powershell
docker exec -it webhook_service python -c "
from src.orchestrator import orchestrator
from langchain_core.messages import HumanMessage
config = {'configurable': {'thread_id': 'demo-1'}}
result = orchestrator.invoke(
    {'messages': [HumanMessage(content='¿Qué dispositivos tuvieron CPU > 90% en la última hora?')]},
    config,
)
print(result['messages'][-1].content)
"
```

---

## 🚨 Sistema de Alertas Provisioned (IaC)

Reglas, contact points, políticas de notificación y ventanas de mantenimiento se aprovisionan **automáticamente** al levantar Grafana. Todo vive en `grafana/provisioning/alerting/`.

### Reglas de alerta (`alert_rules.yml`)

| Regla | Umbral | Duración sostenida | Severidad |
|---|---|---|---|
| Latencia Crítica Sostenida | `AVG(latency_ms) > 150ms` | 3 min | `critical` |
| Packet Loss Elevado | `AVG(packet_loss_pct) > 10%` | 2 min | `critical` |
| CPU Elevado Sostenido | `AVG(cpu_pct) > 85%` | 5 min | `warning` |

### Contact points (`contact_points.yml`)

Ambos contact points apuntan al **Webhook Service interno**, autenticados con **Bearer Token**. Cada disparo queda persistido, deduplicado por JQL y ticketizado en Jira por defecto.

### Ruteo de notificaciones (`notification_policies.yml`)

| Condición | Receptor | Group Wait | Repeat |
|---|---|---|---|
| `severity = critical` | `noc-webhook-critical` | 10s | 20s |
| `severity = warning` | `noc-webhook-default` | 1m | 6h |
| (default) | `noc-webhook-default` | 30s | 4h |

**Group By:** `alertname, hostname`.

### Mute Timings — ventanas de mantenimiento

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
id              BIGSERIAL PRIMARY KEY
received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
status          TEXT              -- 'firing' | 'resolved'
alert_name      TEXT
payload         JSONB NOT NULL    -- payload completo de Grafana, indexado con GIN
```
Índices: `received_at DESC`, `status`, `alert_name`, GIN sobre `payload`.

### `NOCState` — estado compartido del NOC-MAS (`src/state.py`)

```python
messages: Annotated[Sequence[BaseMessage], operator.add]  # historial acumulativo
incident_id: Optional[str]
severity: Optional[Literal["P1", "P2", "P3", "P4"]]
source_alert: Optional[dict]
next_agent: Optional[str]
requires_human_approval: bool
human_decision: Optional[Literal["approved", "rejected", "pending"]]
context: dict                                              # last_sql_query, last_action_type, ...
```

### Vistas para Grafana — telemetría

| Vista | Propósito |
|---|---|
| `v_telemetry_ts` | Time series: latencia, CPU, packet loss por dispositivo |
| `v_event_counts` | Conteo de eventos por severidad en buckets de 5m |
| `v_device_latest` | Último estado registrado por dispositivo |
| `v_recent_anomalies` | Eventos `WARN+` en la última hora |
| `v_region_health` | Comparativa de salud por región en buckets de 5m |

### Vistas para Grafana — postmortem (sobre `incident_logs`, JSONB)

| Vista | Propósito |
|---|---|
| `v_incident_events` | Normaliza cada fila JSONB en columnas planas |
| `v_incident_mttr` | Empareja `firing` → `resolved` por `fingerprint`, calcula `resolution_seconds` |
| `v_incident_latest_status` | Último estado conocido por `fingerprint` |

---

## 🔍 Troubleshooting

### "AlertRule has no datasource"
**Causa:** la UID en `alert_rules.yml` no coincide con la UID real del datasource. **Solución:** cópiala desde **Administration → Connections → Datasources**.

### "Connection refused" entre Grafana y PostgreSQL
```powershell
docker network inspect noc_net
docker exec grafana ping timescaledb
```

### El Webhook Service responde `401 Unauthorized`
**Causa:** `NOC_WEBHOOK_TOKEN` no coincide entre `.env` y `contact_points.yml`. **Solución:**
```powershell
docker compose up -d --force-recreate grafana webhook-service
```

### El ticket de Jira no se crea (`jira.created: false`)
**Causa 1:** faltan variables Jira en `.env`. **Causa 2:** API Token expirado o sin permisos.
```powershell
docker logs webhook_service --tail 50 | Select-String "Jira"
```

### La búsqueda JQL de deduplicación falla o responde `410 Gone`
**Causa:** se está usando el endpoint clásico `GET/POST /rest/api/3/search`, retirado por Atlassian (CHANGE-2046). **Solución:** confirma que el código apunte a `POST /rest/api/3/search/jql`; revisa logs:
```powershell
docker logs webhook_service --tail 50 | Select-String "búsqueda JQL"
```

### El Supervisor cae siempre en `human_in_the_loop` (fallback)
**Causa:** el LLM no está devolviendo JSON parseable por `PydanticOutputParser` (típico en modelos que emiten bloques `<think>` sin cerrarse, o `GROQ_API_KEY` inválida/rate-limited).
```powershell
docker logs webhook_service --tail 100 | Select-String "Fallo de parseo|FALLBACK"
```
Verifica `GROQ_API_KEY` y considera bajar `temperature` o cambiar `NOC_SUPERVISOR_MODEL`.

### El Data_Agent rechaza toda consulta con "operaciones no permitidas"
**Causa esperada:** el validador (`_validate_query`) bloquea cualquier sentencia que no sea `SELECT` puro sobre `network_telemetry`, o que contenga `INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/GRANT/REVOKE/CREATE` — es una medida de seguridad, no un bug. Reformula la pregunta en lenguaje natural para que derive en un `SELECT` válido.

### El notebook de Jupyter no conecta a TimescaleDB
```powershell
docker exec jupyter_ml python -c "import os; print(os.environ['PG_DSN'])"
docker network inspect noc_net
```
Confirma que `jupyter_ml` esté en `noc_net` y que `PG_DSN` apunte a `timescaledb:5432`.

### La ChatOps UI no refleja respuestas reales del NOC-MAS
**Causa esperada (temporal):** `chatops-ui/app.py` opera en **modo standalone** — la llamada a `orchestrator.invoke()` aún no está cableada al backend HTTP; ver Roadmap Fase 6.

### El dashboard de Postmortem no muestra datos
**Causa:** `incident_views.sql` no se ejecutó, o no hay pares `firing`/`resolved` todavía. **Solución:** corre el paso 6 de instalación y `simulate_mttr_incidents.py`.

### Quiero volver a usar Slack en vez del Webhook Service
Cambia `type: webhook` por `type: slack` en `contact_points.yml`.

---

## 🔐 Seguridad

### Credenciales por defecto (solo laboratorio — no usar en producción)

- **PostgreSQL:** usuario `noc_user`, contraseña `secret`
- **Grafana Admin:** usuario `admin`, contraseña `admin`
- **Jupyter:** token definido en `JUPYTER_TOKEN`
- **Webhook Service:** hereda credenciales de PostgreSQL vía variables de entorno

### Autenticación y controles implementados

- `POST /alert` **exige** `Authorization: Bearer <NOC_WEBHOOK_TOKEN>`; comparación con `secrets.compare_digest` (mitiga timing attacks)
- `JIRA_API_TOKEN` y `GROQ_API_KEY` viajan únicamente como variables de entorno del contenedor, nunca hardcodeadas
- **Text-to-SQL blindado**: el Data_Agent solo ejecuta `SELECT` validados por regex y forzados a `network_telemetry`, con `LIMIT 200` — el LLM nunca tiene acceso a credenciales de escritura ni a otras tablas
- **Compuerta HITL obligatoria**: cualquier severidad `P1`, acción irreversible o fallo de parseo del Supervisor enruta forzosamente a `human_in_the_loop`, deteniendo el grafo (`interrupt_before`) hasta aprobación explícita
- **Sanitización de salida de modelos Open Source**: `clean_think_tags()` elimina bloques `<think>` antes de cualquier parseo, evitando inyección de contenido no estructurado en el pipeline de decisión

### En producción

- Usa `.env` (nunca lo commitees) o un secret manager (Vault, AWS/GCP Secrets Manager)
- Cambia la contraseña de Grafana Admin y el token de Jupyter inmediatamente tras el despliegue
- Rota `NOC_WEBHOOK_TOKEN`, `JIRA_API_TOKEN` y `GROQ_API_KEY` periódicamente
- No publiques los puertos `8000`, `8888` fuera del host — restringe a `noc_net` y usa reverse proxy con TLS para exposición externa
- Considera fijar el checkpointer del NOC-MAS a un backend persistente (Postgres/Redis) en vez de `MemorySaver` antes de escalar a múltiples réplicas del Webhook Service

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
- ✅ Integración del Webhook Service con **JIRA** para auto-tickets zero-touch
- ✅ **Autenticación Bearer Token** en `POST /alert`
- ✅ **Escalado geográfico multi-región**: 3 simuladores concurrentes sobre una hypertable única
- ✅ Extensión del esquema con la dimensión `region`
- ✅ **Dashboards de postmortem** con MTTR general, MTTR por dispositivo, conteo de incidentes e historial
- ✅ Vistas JSONB refactorizadas (`incident_views.sql`)
- ✅ Variable de plantilla `$region` en ambos dashboards

### ✅ Fase 5 — ML, Multiagencia y ChatOps (completada)
- ✅ **Deduplicación Inteligente en Jira (JQL)**: búsqueda `POST /rest/api/3/search/jql` por labels antes de ticketizar; comentario de "falla persistente" en vez de ticket duplicado
- ✅ **Cierre automático de tickets Jira** al recibir `status=resolved` (transición configurable vía `JIRA_RESOLVE_TRANSITION_NAME`)
- ✅ **ML Analytics Hub**: contenedor Jupyter en `noc_net`, conectado a TimescaleDB
- ✅ **Detección Dinámica de Anomalías** con `IsolationForest` sobre CPU/latencia, complementando los umbrales estáticos de Grafana
- ✅ **Sistema Multiagente NOC-MAS** en LangGraph: `NOCState` compartido, `StateGraph` jerárquico, Supervisor con enrutamiento determinista, Data Agent (Text-to-SQL seguro), Action Agent (payloads Pydantic)
- ✅ **Compuerta de seguridad Human-in-the-Loop (HITL)** con `interrupt_before` y checkpointer `MemorySaver`
- ✅ **Sanitización Regex** de bloques `<think>` para modelos Open Source servidos vía Groq, con validación `PydanticOutputParser` y *fallback* seguro
- ✅ **ChatOps UI en Streamlit** (`http://localhost:8501`) con sidebar de estado y métricas rápidas
- ✅ Nuevo árbol de infraestructura: `webhook_service/src/`, `jupyter/`, servicios `chatops-ui` y `jupyter-ml` en `docker-compose.yml`

### 🔮 Fase 6 — Cierre del loop conversacional y checkpointer persistente (próxima)
- [ ] Cablear `chatops-ui/app.py` a `orchestrator.invoke()` vía llamada HTTP real al Webhook Service (hoy en modo standalone)
- [ ] Reemplazar `MemorySaver` por un checkpointer persistente (Postgres/Redis) para sobrevivir reinicios del contenedor
- [ ] Exponer los hallazgos del `IsolationForest` como feature adicional del Data_Agent (contexto enriquecido para el Supervisor)
- [ ] Endpoint dedicado `POST /noc-mas/invoke` en el Webhook Service, desacoplado de `/alert`
- [ ] Exportación de métricas de MTTR + decisiones del NOC-MAS a un dashboard ejecutivo (SLA/SLO tracking)
- [ ] Autenticación de la ChatOps UI (hoy expuesta sin login en `8501`)

---

## 📚 Referencias

- **Grafana Unified Alerting:** https://grafana.com/docs/grafana/latest/alerting/
- **Grafana Provisioning:** https://grafana.com/docs/grafana/latest/administration/provisioning/
- **Mute Timings:** https://grafana.com/docs/grafana/latest/alerting/configure-notifications/mute-timings/
- **TimescaleDB:** https://docs.timescaledb.com/
- **FastAPI:** https://fastapi.tiangolo.com/
- **Jira Cloud REST API (Issues):** https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/
- **Jira Cloud REST API (`/search/jql`):** https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/
- **LangGraph:** https://langchain-ai.github.io/langgraph/
- **Groq API:** https://console.groq.com/docs
- **scikit-learn — IsolationForest:** https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html
- **Streamlit:** https://docs.streamlit.io/

---

## 📝 Contribuciones

Este proyecto sigue **Infrastructure as Code** como principio rector. Cualquier cambio en alertas, dashboards, datasources, esquema multi-región, Webhook Service o en el grafo del NOC-MAS debe pasar por código y Git.

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
**Versión:** 5.0 (ML Analytics + NOC-MAS LangGraph + Deduplicación JQL + ChatOps Streamlit)