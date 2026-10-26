# 📡 NOC Observability Pipeline

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-009639?style=for-the-badge&logo=timescaledb&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=for-the-badge&logo=grafana&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2CA5E0?style=for-the-badge&logo=docker&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white)
![Jira](https://img.shields.io/badge/Jira-0052CC?style=for-the-badge&logo=jira&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)
![Scikit--Learn](https://img.shields.io/badge/scikit--learn-F7931E?style=for-the-badge&logo=scikitlearn&logoColor=white)
![Jupyter](https://img.shields.io/badge/Jupyter-F37626?style=for-the-badge&logo=jupyter&logoColor=white)

Pipeline de observabilidad de extremo a extremo — **multi-región**, **auto-inteligente** y ahora **cloud-native** — para simular, ingerir, almacenar, visualizar, alertar, **ticketizar**, **analizar con ML** y **operar conversacionalmente** telemetría de red en un entorno de Centro de Operaciones de Red (NOC). Arquitectura contenerizada, gobernada por **Infrastructure as Code**: dashboards, reglas de alerta, ventanas de mantenimiento, el motor de recepción/escalado de incidentes, el sistema multiagente de decisión y, desde la Fase 7, los **manifiestos de Kubernetes** (con RBAC de mínimo privilegio) viven como código versionado, no como clics en una UI.

---

## 🧭 Acerca del Proyecto

Este repositorio implementa un **loop de alerta cerrado, geográficamente distribuido y con criterio propio**. Tres simuladores regionales (`us-east`, `eu-west`, `sa-south`) alimentan una única hypertable en TimescaleDB. Grafana detecta la anomalía, la enruta según severidad, respeta las ventanas de mantenimiento definidas en código, y un microservicio propio en **FastAPI** — autenticado, con cliente Jira nativo y **deduplicación atómica compartida en PostgreSQL** — recibe, registra, prioriza y **escala automáticamente cada incidente a un ticket de Jira**, sin intervención humana y sin generar *ticket storms*, incluso con varias réplicas corriendo en paralelo.

Con la **Fase 5** el pipeline dejó de ser puramente reactivo: un modelo `IsolationForest` detecta anomalías dinámicas que los umbrales estáticos no capturan, y un **sistema multiagente (NOC-MAS)** orquestado con **LangGraph** (Supervisor, Data Agent con Text-to-SQL seguro, Action Agent y Responder Agent, bajo una compuerta **Human-in-the-Loop**) diagnostica y propone acciones, todo accesible desde una **ChatOps UI en Streamlit**.

Con la **Fase 6** el estado del NOC-MAS persiste en PostgreSQL (`PostgresSaver`) y el proyecto suma pruebas unitarias y CI.

La **Fase 7**, en curso, lleva el Webhook Service desde Docker Compose hacia Kubernetes: una prueba de concepto en Azure (AKS + ACR) y un clúster local multinodo con `kind`. En el clúster local el servicio ya corre **endurecido** (probes, límites, NetworkPolicy, Secrets, ServiceAccount sin token y rol de operador de mínimo privilegio) y su comportamiento (alertas, resolución, rollback y deduplicación entre réplicas) está **validado**.

---

## 🏗️ Arquitectura y Stack

El ecosistema está compuesto por **cinco capas**. En Docker Compose se orquestan sobre una red bridge compartida (`noc_net`); el Webhook Service además tiene una ruta de despliegue en Kubernetes (ver sección dedicada).

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
│  jira_dedup (estado de deduplicación compartido entre réplicas)            │
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
│  POST /alert → dedup atómico (Postgres) → insert incident_logs → Jira      │
│  Supervisor ──▶ Data_Agent (Text-to-SQL) ──▶ Action_Agent (Pydantic)       │
│              └─▶ human_in_the_loop (HITL gate) ─▶ END                     │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │ REST (issue / comment / transition)
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ CAPA 5 · ESCALADO Y OPERACIÓN — Jira Cloud + ChatOps UI (Streamlit)        │
│  tickets deduplicados por huella alerta+equipo │ chat operativo NL         │
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
- 🆕 **Tabla `jira_dedup`**: estado de deduplicación compartido por todas las réplicas del Webhook Service; la crea automáticamente `main.py` al arrancar

### Capa 3 — Visualización e Inteligencia Operativa (Grafana OSS, Unified Alerting)
Dos dashboards y el sistema de alertas **100% aprovisionados vía IaC** (`grafana/provisioning/`):
- **Dashboard `NOC — Network Telemetry`**: eventos críticos, time series de latencia/CPU, snapshot por dispositivo — filtrable por `$region`/`$hostname`
- **Dashboard `NOC - Postmortem & MTTR`**: MTTR general, MTTR por dispositivo, conteo de incidentes, historial
- **3 reglas de alerta** (`alert_rules.yml`) evaluadas cada minuto
- **Contact points** hacia el Webhook Service con `authorization_credentials` (Bearer Token)
- **Notification policies** con ruteo por severidad
- **Mute timings** — ventanas de mantenimiento

### Capa 3.5 — ML Analytics Hub (`jupyter/`)
Contenedor **Jupyter** desplegado dentro de `noc_net`, conectado directamente a TimescaleDB, dedicado a analítica avanzada fuera del ciclo de vida operativo de Grafana:
- **Entrenamiento y validación de `IsolationForest`** (scikit-learn) sobre series históricas de `cpu_pct` y `latency_ms` para detectar picos inusuales que un umbral estático no captura
- Complementa (no reemplaza) las reglas de alerta de Grafana: banco de pruebas para calibrar umbrales dinámicos y fuente de *features* para el Data_Agent
- Acceso vía `http://localhost:8888` protegido con `JUPYTER_TOKEN`
- Notebooks persistidos en `./jupyter/notebooks` (bind mount)

### Capa 4 — Decisión: Webhook Service + NOC-MAS (FastAPI + LangGraph)

#### Recepción de alertas (`POST /alert`)
- **Autenticación Bearer** con `secrets.compare_digest` (mitiga timing attacks); sin token o con token inválido responde `401`
- **Varias alertas por payload**: `split_alerts()` descompone un POST de Grafana con N alertas en N vistas de 1 alerta, cada una con **su propio** `status`; cada una se registra y se deduplica por separado
- **Títulos de ticket estables**: se toman de `annotations.summary` (o `alertname` + equipo); el `title` del payload de Grafana (`[FIRING:n] ...`) se descarta porque cambia según cuántas alertas lleguen juntas. Las alertas `DatasourceNoData` usan la identidad de la regla de origen
- **Fail-closed con Jira**: antes de buscar o crear, `verify_jira_auth()` comprueba las credenciales. Si Jira o Postgres no responden, la alerta devuelve **HTTP 503** (`partial_failure`) y **Grafana reintenta**; los tickets ya creados no se duplican en el reintento
- Respuesta `200` con `status: received` cuando todo fue bien, y un detalle por alerta (`alert`, `device`, `persisted`, `jira.action`, `jira.key`)

#### Deduplicación atómica (anti Ticket Storm, multi-réplica)
La huella es `al-<alertname>|dev-<equipo>` (`slugify` de cada parte). El equipo se toma del primer label disponible entre `device`, `host`, `hostname`, `instance`, `node`, `pod`, `service`.

| Estado | Qué ocurre |
|---|---|
| `firing`, sin ticket abierto | `db_claim()` reserva la huella de forma **atómica** (`PRIMARY KEY` + `ON CONFLICT`); solo la réplica que gana crea el ticket (`ticket_created`). Las demás responden `dedup_in_progress` o `comment_added` |
| `firing`, con ticket abierto | Se agrega un comentario "⚠️ La anomalía PERSISTE" (`comment_added`), sin crear ticket nuevo |
| `resolved`, con ticket abierto | Comenta el cierre, ejecuta la transición `JIRA_RESOLVE_TRANSITION_NAME` y marca la huella `closed` (`resolved`) |
| `resolved`, sin ticket abierto | No hace nada (`resolved_no_open_ticket`) |

Detalles de diseño:
- **Postgres primero** (`jira_dedup`: consistente e inmediato); si no hay registro, **respaldo JQL** (`POST /rest/api/3/search/jql`, el endpoint clásico `/search` fue retirado por Atlassian y responde `410 Gone`) para adoptar tickets creados antes de que existiera la tabla
- Todo ticket candidato se **verifica por key** (`statusCategory`), porque la JQL depende del índice de Jira y puede no ver un ticket recién creado, y porque el workflow puede no rellenar `resolution` al cerrar
- Una reserva `creating` colgada más de 2 minutos (proceso caído a mitad de creación) puede reclamarse de nuevo
- Si la creación en Jira falla, `db_release()` libera la reserva para que el reintento de Grafana pueda crear

#### Salud, robustez y rendimiento
- `GET /health` → **liveness** (el proceso responde)
- `GET /ready` → **readiness** (solo verifica Postgres; Jira no se verifica a propósito: si Jira cae y todos los pods quedaran "no listos", tampoco se podrían guardar las alertas en `incident_logs`)
- **Validación de variables de entorno al arrancar** (`_require_env`): si falta alguna, el servicio no inicia y el error muestra solo los **nombres**, nunca los valores
- Acceso a Postgres con `ThreadedConnectionPool` (`maxconn=20`) y llamadas bloqueantes ejecutadas con `run_in_threadpool` para no congelar el event loop

#### NOC-MAS — Sistema Multiagente (`webhook_service/src/`, Clean Architecture)
Orquestación con **LangGraph** bajo un `StateGraph` jerárquico con enrutamiento determinista:
- `src/state.py` — `NOCState` (`TypedDict`): estado compartido, con `messages: Annotated[Sequence[BaseMessage], operator.add]` para acumular historial, más `incident_id`, `severity`, `next_agent`, `requires_human_approval`, `human_decision` y `context`
- `src/orchestrator.py` — nodo **Supervisor**: LLM (`ChatGroq`) con prompt PTCF que enruta a `Data_Agent`, `Action_Agent`, `Responder_Agent`, `human_in_the_loop` o `END`, con salida forzada a JSON vía `PydanticOutputParser` (`RouteResponse`)
- `src/nodes/data_agent.py` — **Data Agent**: Text-to-SQL **seguro** sobre TimescaleDB — solo `SELECT`, bloqueo por regex de `INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/GRANT/REVOKE/CREATE`, forzado a referenciar `network_telemetry`, `LIMIT 200`
- `src/nodes/action_agent.py` — **Action Agent**: acciones estructuradas (`CREATE_TICKET`, `SEND_ALERT`, `ACK_ALERT`, `ESCALATE`, `INFO_QUERY`) con `action_payload` validado vía Pydantic; para `CREATE_TICKET`/`INFO_QUERY` ejecuta la llamada real a Jira
- `src/nodes/responder_agent.py` — **Responder Agent**: nodo de cierre que sintetiza los resultados crudos (filas SQL o datos de Jira) en una respuesta breve en lenguaje natural; termina el grafo (`END`)
- **Compuerta HITL**: el grafo se compila con `interrupt_before=["human_in_the_loop"]` — severidad `P1`, acción irreversible o ambigüedad detienen el flujo hasta aprobación humana
- **Checkpointer persistente**: `PostgresSaver` (`langgraph-checkpoint-postgres`) sobre el mismo contenedor `timescaledb` — el historial, `next_agent` y la decisión HITL sobreviven a un reinicio del Webhook Service
- **Sanitización para modelos Open Source**: `clean_think_tags()`/`strip_think_tags()` limpian bloques `<think>...</think>` antes del parseo Pydantic, con *fallback* seguro a `human_in_the_loop`
- Ciclo del grafo: `supervisor → {Data_Agent | Action_Agent} → supervisor → ... → {Responder_Agent | human_in_the_loop | END}`

### Capa 5 — ChatOps UI (Streamlit) + Jira
- Servicio web interactivo en `http://localhost:8501` para interactuar en lenguaje natural con el ecosistema NOC
- Sidebar con estado de conectividad y métricas rápidas — estos widgets son valores de demostración fijos, no están cableados a métricas en vivo
- ✅ Conexión real de punta a punta: `chatops_ui/app.py` llama por HTTP a `POST /api/chat` (autenticado con el mismo token) con un `thread_id` estable por sesión de navegador, que mantiene la memoria conversacional gracias al checkpointer persistente
- Los tickets creados/comentados por la deduplicación y por el Action Agent llegan al mismo proyecto Jira, cerrando el loop: **detección → diagnóstico → decisión → registro**

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
│   ├── main.py                      # FastAPI: /alert (Bearer), /api/chat, /health, /ready, dedup atómico + Jira
│   ├── src/
│   │   ├── state.py                 # NOCState (TypedDict) — estado compartido del NOC-MAS
│   │   ├── orchestrator.py          # StateGraph LangGraph + Supervisor + checkpointer PostgresSaver
│   │   └── nodes/
│   │       ├── data_agent.py        # Text-to-SQL seguro (solo SELECT) sobre network_telemetry
│   │       ├── action_agent.py      # Acciones estructuradas (Pydantic) y llamadas a Jira
│   │       └── responder_agent.py   # Síntesis en lenguaje natural para el operador (nodo final)
│   ├── requirements.txt
│   └── Dockerfile
│
├── chatops_ui/
│   ├── app.py                       # Streamlit — chat NL conectado a POST /api/chat, sidebar de estado
│   ├── requirements.txt
│   └── Dockerfile
│
├── jupyter/
│   ├── notebooks/
│   │   ├── IsolationForest.ipynb    # Entrenamiento/validación IsolationForest (CPU/latencia)
│   │   └── RandomForest2.ipynb
│   ├── requirements.txt
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
├── tests/
│   ├── test_webhook_endpoints.py    # Unit tests (TestClient) — GET /health, auth de POST /alert; corren en CI
│   ├── test_checkpointer_persistence.py # Integración: persistencia del checkpointer PostgresSaver
│   ├── test_supervisor.py           # Script manual (no pytest) — requiere GROQ_API_KEY
│   └── test_action_agent.py         # Script manual (no pytest) — idem, sobre el Action Agent
│
├── webhook_service.sql              # DDL de incident_logs (tabla + índices GIN); idempotente, incluido en sql/schema.sql
│
├── .github/workflows/
│   └── ci.yml                       # pytest sobre tests/test_webhook_endpoints.py + build de la imagen Docker
├── .gitlab-ci.yml                   # Mismo pipeline en GitLab CI: stages test (pytest) y build (docker build vía dind)
│
├── k8s/                             # PoC de despliegue en Azure AKS (ver sección Kubernetes)
│   ├── webhook-deployment.yaml
│   ├── webhook-service.yaml         # type: LoadBalancer
│   ├── webhook-secret.yaml          # plantilla con placeholders — sin valores reales
│   ├── timescaledb-deployment.yaml  # PVC 10Gi + PGDATA en subdirectorio (workaround Azure Disk)
│   └── timescaledb-service.yaml
│
├── deploy/                          # Manifiestos: cluster/, base/, apps/ (ver deploy/README.md)
│   ├── kind-3nodes.yaml             # 1 control-plane + 2 workers
│   ├── setup-local-cluster.ps1
│   ├── namespaces.yaml              # namespaces dev y monitoring con labels estándar
│   ├── dev/                         # namespace dev
│   │   ├── webhook-deployment.yaml  # imagen v1.0.12, probes, límites, anti-affinity, SA propia
│   │   ├── webhook-serviceaccount.yaml # 🆕 webhook-sa (sin token montado)
│   │   ├── noc-operator-rbac.yaml   # 🆕 SA + Role + RoleBinding del operador NOC (mínimo privilegio)
│   │   ├── webhook-config.yaml      # ConfigMap (PG_HOST, PG_PORT, PG_DB, PG_USER, JIRA_URL, ...)
│   │   ├── webhook-secret.yaml.example # plantilla — el real está gitignored
│   │   ├── webhook-service.yaml     # ClusterIP
│   │   ├── webhook-ingress.yaml     # NGINX Ingress, host webhook.local (solo /alert y /health)
│   │   ├── network-policy.yaml      # default-deny + allow ingress-nginx/monitoring + allow webhook→timescaledb
│   │   ├── timescaledb-statefulset.yaml # StatefulSet + volumeClaimTemplate RWO 2Gi
│   │   ├── timescaledb-service.yaml
│   │   ├── timescaledb-secret.yaml.example # 🆕 plantilla — el real está gitignored
│   │   └── timescaledb-secret.yaml  # gitignored
│   └── monitoring/                  # namespace monitoring
│       ├── grafana-deployment.yaml  # grafana-oss:13.0.2, fsGroup 472, admin desde Secret, probes /api/health
│       ├── grafana-admin-secret.yaml.example # 🆕 plantilla — el real está gitignored
│       ├── grafana-pvc.yaml
│       ├── grafana-service.yaml
│       └── grafana-ingress.yaml     # NGINX Ingress, host grafana.local
│
├── deploy-azure-infra.ps1           # az login / group create / acr create / aks create / attach-acr
│
├── .env                              # Secretos y configuración (no versionado)
├── .env.example                      # Plantilla sin valores
├── .gitignore
├── .dockerignore
├── .gitattributes
├── docker-compose.yml                # Orquestación: 9 servicios (ver tabla abajo)
└── README.md
```

---

## 🚀 Requisitos

- **Docker** 20.10+
- **Docker Compose** v2 (`docker compose`, sin guion)
- **8 GB RAM** mínimo (recomendado 12 GB — 3 simuladores + TimescaleDB + Grafana + Webhook Service/NOC-MAS + Jupyter + ChatOps UI; más si además corres el clúster `kind`)
- **3 GB** de espacio en disco para volúmenes de datos
- Cuenta de **Jira Cloud** con un API Token válido (auto-ticketing + deduplicación)
- Cuenta de **Groq** con API Key válida (Supervisor, Data Agent y Action Agent del NOC-MAS)
- Para Kubernetes local: **kind**, **kubectl** y el Ingress Controller NGINX
- Windows: **PowerShell 5.1+** o **PowerShell 7+** (los comandos de este README están validados para PowerShell 5.1)

---

## 🔐 Variables de Entorno (`.env`)

Crea un archivo `.env` en la raíz del repositorio (ya cubierto por `.gitignore` y `.dockerignore`) con las siguientes claves. **El `docker-compose.yml` ya no trae credenciales por defecto**: si falta una variable obligatoria, el servicio no arranca.

```dotenv
# ── Webhook Service — autenticación ─────────────────────────────────────────
NOC_WEBHOOK_TOKEN=reemplaza-con-un-token-largo-y-aleatorio

# ── Integración Jira Cloud ───────────────────────────────────────────────────
JIRA_URL=https://tu-dominio.atlassian.net
JIRA_USER=tu-email@tudominio.com
JIRA_API_TOKEN=reemplaza-con-tu-api-token-de-atlassian
JIRA_PROJECT_KEY=NOC
JIRA_RESOLVE_TRANSITION_NAME="Finalizar"
JIRA_ISSUE_TYPE="Incident"

# ── PostgreSQL / TimescaleDB ────────────────────────────────────────────────
PG_HOST=timescaledb
PG_PORT=5432
PG_DB=noc
PG_USER=noc_user
PG_PASSWORD=reemplaza-con-una-contrasena-fuerte
PG_DSN=postgresql+psycopg2://noc_user:<PG_PASSWORD>@timescaledb:5432/noc

# ── NOC-MAS (LangGraph + Groq) ───────────────────────────────────────────────
GROQ_API_KEY=reemplaza-con-tu-api-key-de-groq
NOC_SUPERVISOR_MODEL=llama3-8b-8192
NOC_DATA_AGENT_MODEL=llama3-8b-8192
NOC_ACTION_AGENT_MODEL=qwen/qwen3.6-27b

# ── Grafana ──────────────────────────────────────────────────────────────────
GF_SECURITY_ADMIN_PASSWORD=reemplaza-con-una-contrasena-fuerte

# ── ML Analytics Hub (Jupyter) ───────────────────────────────────────────────
JUPYTER_TOKEN=reemplaza-con-un-token-de-acceso

# ── Chaos Engineering / simuladores ──────────────────────────────────────────
WEBHOOK_URL=http://localhost:8000/alert
```

| Variable | Requerida | Descripción |
|---|---|---|
| `NOC_WEBHOOK_TOKEN` | ✅ Sí | Token Bearer compartido entre Grafana (`contact_points.yml`), la ChatOps UI y el Webhook Service. Sin él, el servicio **no arranca**. |
| `PG_HOST` / `PG_PORT` / `PG_DB` / `PG_USER` / `PG_PASSWORD` | ✅ Sí | Conexión a PostgreSQL. Se validan al arrancar. |
| `JIRA_URL` / `JIRA_USER` / `JIRA_API_TOKEN` / `JIRA_PROJECT_KEY` | ✅ Sí | Credenciales de Jira Cloud. El servicio valida que existan al arrancar y verifica la autenticación (`fail-closed`) antes de cada operación. |
| `JIRA_RESOLVE_TRANSITION_NAME` | Recomendada | Nombre **exacto** de la transición de workflow usada para cerrar el ticket al recibir `resolved`. Si no se define, el código usa `Done`; en este proyecto el workflow usa **`Finalizar`**. |
| `JIRA_ISSUE_TYPE` | Opcional | Tipo de issue a crear. Default `Incident`. |
| `GROQ_API_KEY` | ✅ Sí (para NOC-MAS) | Autentica las llamadas `ChatGroq`. |
| `NOC_*_MODEL` | Opcional | Override del modelo Groq por nodo del grafo. |
| `PG_DSN` | ✅ Sí (Data Agent / Jupyter) | DSN SQLAlchemy usado por `data_agent.py` y los notebooks. |
| `JUPYTER_TOKEN` | Opcional | Token de acceso a `jupyter-ml` (`http://localhost:8888`). |
| `WEBHOOK_URL` | Opcional | Usada por `simulate_mttr_incidents.py` para apuntar a otro Webhook Service. |

> ⚠️ Nunca commitees el `.env` real ni imprimas valores de secretos en logs o capturas: al verificar, muestra solo **nombres y largos**. Usa `.env.example` como plantilla.

---

## ⚙️ Instalación y Despliegue (Docker Compose)

### 1. Clonar el repositorio

```powershell
git clone <repo-url>
cd noc-observability-pipeline-cloud-native
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
docker compose ps
```

### 4. Inicializar el esquema principal (telemetría + regiones)

```powershell
Get-Content sql/schema.sql | docker exec -i timescaledb psql -U noc_user -d noc
docker exec -i timescaledb psql -U noc_user -d noc `
  -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public';"
```

Deberías ver `devices`, `network_telemetry` y las vistas `v_telemetry_ts`, `v_event_counts`, `v_device_latest`, `v_recent_anomalies`, `v_region_health`.

### 5. Inicializar el esquema del Webhook Service

```powershell
Get-Content webhook_service.sql | docker exec -i timescaledb psql -U noc_user -d noc
docker exec -i timescaledb psql -U noc_user -d noc -c "\d incident_logs"
```

La tabla `jira_dedup` **no requiere paso manual**: el Webhook Service la crea al arrancar.

### 6. Inicializar las vistas de postmortem (JSONB → MTTR)

```powershell
Get-Content sql/incident_views.sql | docker exec -i timescaledb psql -U noc_user -d noc
docker exec -i timescaledb psql -U noc_user -d noc `
  -c "SELECT viewname FROM pg_views WHERE viewname LIKE 'v_incident%';"
```

### 7. Verificar el Webhook Service

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get   # liveness
Invoke-RestMethod -Uri "http://localhost:8000/ready"  -Method Get   # readiness (Postgres)
```

`/health` y `/ready` no requieren token; `/alert` y `/api/chat` sí (`Authorization: Bearer <NOC_WEBHOOK_TOKEN>`).

### 8. Poblar datos de entrenamiento y validar el modelo ML

```powershell
cd python-simulator
python simulate_mttr_incidents.py --webhook-url "http://localhost:8000/alert"
cd ..
```

Abre `http://localhost:8888` (token = `JUPYTER_TOKEN`) y ejecuta `notebooks/IsolationForest.ipynb` de punta a punta para entrenar y validar el `IsolationForest`.

### 9. Verificar el NOC-MAS y la ChatOps UI

```powershell
Start-Process "http://localhost:8501"
```

Escribe una consulta (ej. *"muéstrame los dispositivos con CPU > 90% en la última hora"*) para validar el circuito Supervisor → Data_Agent → Supervisor.

---

## ▶️ Uso

### Ejecutar un simulador regional de forma manual (fuera de Compose)

> ⚠️ `simulator.py` usa imports planos (`from config import DEVICES`), así que debes ejecutarlo **desde dentro de** `python-simulator/`.

```powershell
cd python-simulator
$env:REGION = "eu-west"
python simulator.py --fmt postgres --interval 2 --batch 3 `
  --pg-dsn "postgresql://noc_user:<PG_PASSWORD>@localhost:5432/noc"
```

### Acceder a Grafana

Abre `http://localhost:3000` con el usuario `admin` y la contraseña definida en tu `.env`. Navega a:
- **Dashboards → NOC — Network Telemetry**
- **Dashboards → NOC - Postmortem & MTTR**

### Forzar una alerta de punta a punta (ticket Jira deduplicado)

```powershell
cd python-simulator
python force_alert_test.py --minutes 5 `
  --pg-dsn "postgresql://noc_user:<PG_PASSWORD>@localhost:5432/noc"
```

Si la misma alerta (mismo `alertname` + equipo) llega dos veces, la segunda **comenta** el ticket existente en vez de crear uno nuevo (`jira.action == "comment_added"`).

### Enviar una alerta manual al Webhook (PowerShell)

> ⚠️ Esto crea un ticket real en Jira. Usa un `alertname` de prueba (ej. `PRUEBA-...`) y ciérralo después con un `resolved`.

```powershell
$token = $env:NOC_WEBHOOK_TOKEN   # no lo imprimas
$ahora = (Get-Date).ToUniversalTime().ToString("o")
$cuerpo = @{
  receiver = "noc-webhook"; status = "firing"; version = "1"
  alerts = @(@{
    status      = "firing"
    labels      = @{ alertname = "PRUEBA-MANUAL"; severity = "warning"; instance = "prueba-host" }
    annotations = @{ summary = "Prueba manual" }
    startsAt    = $ahora
    endsAt      = "0001-01-01T00:00:00Z"
  })
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Uri "http://localhost:8000/alert" -Method Post `
  -ContentType "application/json" -Headers @{ Authorization = "Bearer $token" } `
  -Body ([Text.Encoding]::UTF8.GetBytes($cuerpo))
```

### Interactuar con el NOC-MAS desde la ChatOps UI

Abre `http://localhost:8501`. Escribe consultas en lenguaje natural; el Supervisor decide si el flujo pasa por `Data_Agent`, `Action_Agent` o se detiene en la compuerta `human_in_the_loop`.

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

Ambos contact points apuntan al **Webhook Service**, autenticados con **Bearer Token** (`authorization_credentials`). Cada disparo queda persistido, deduplicado y ticketizado en Jira. Si el webhook responde `503`, Grafana **reintenta**.

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

### `incident_logs` — bitácora del Webhook Service

```sql
id              BIGSERIAL PRIMARY KEY
received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
status          TEXT              -- 'firing' | 'resolved'
alert_name      TEXT
payload         JSONB NOT NULL    -- payload de Grafana (1 alerta por fila), indexado con GIN
```
Índices: `received_at DESC`, `status`, `alert_name`, GIN sobre `payload`. Cada alerta de un POST agrupado se guarda en su propia fila.

### `jira_dedup` — estado de deduplicación compartido

```sql
fingerprint  TEXT PRIMARY KEY                     -- 'al-<alertname>|dev-<equipo>'
issue_key    TEXT                                  -- key del ticket en Jira
state        TEXT NOT NULL                         -- 'creating' | 'open' | 'closed'
updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
```
La `PRIMARY KEY` junto con `INSERT ... ON CONFLICT` actúa como **lock distribuido**: solo una réplica obtiene la reserva de creación para una huella.

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

## ☸️ Despliegue Cloud-Native (Kubernetes) — Fase 7, en curso

El `webhook-service` tiene dos rutas paralelas de migración a Kubernetes. En ambas, **TimescaleDB** sigue pudiendo vivir en Docker Compose (red híbrida) salvo donde se indica.

### Prueba de concepto en Azure (AKS + ACR) — `k8s/`

- `webhook-deployment.yaml`: imagen `nocacr.azurecr.io/noc-webhook-service:latest`, variables no sensibles inline y el resto vía `envFrom: secretRef`; sondas sobre `/health`
- `webhook-service.yaml`: `type: LoadBalancer` (IP pública directa; sin Ingress/TLS todavía)
- `webhook-secret.yaml`: plantilla con placeholders `REEMPLAZAR_*` — **nunca** commitear con valores reales
- `timescaledb-deployment.yaml`: `PersistentVolumeClaim` (10Gi, `ReadWriteOnce`) + `Deployment` (`strategy: Recreate`); `PGDATA` en subdirectorio para sortear el `lost+found` de Azure Disk
- `deploy-azure-infra.ps1`: aprovisiona Resource Group + ACR + AKS y adjunta el ACR al clúster
- El job `docker-build` de `ci.yml` corre en cada push/PR (build sin push). Los pasos de login a ACR, push y despliegue a AKS están escritos pero **pausados** mientras se valida Kubernetes en local

### Clúster local con `kind` — `deploy/`

Clúster `noc-local-cluster`: 1 control-plane + 2 workers (`kind-3nodes.yaml` + `setup-local-cluster.ps1`). Namespaces `dev` (webhook-service + TimescaleDB) y `monitoring` (Grafana), con labels estándar `app.kubernetes.io/*` y `environment`.

#### Webhook Service endurecido (`dev/webhook-deployment.yaml`)

| Aspecto | Configuración |
|---|---|
| Imagen | `noc-webhook-service:v1.0.12` (cargada al clúster con `kind load docker-image`) |
| Probes | `startupProbe` y `livenessProbe` en `/health`; `readinessProbe` en `/ready` (Postgres) |
| Recursos | límite de memoria 512Mi (a ajustar tras medir con `docker stats`) |
| Historial | `revisionHistoryLimit: 5` |
| Apagado | `terminationGracePeriodSeconds: 30` |
| Estrategia | `RollingUpdate` (`maxSurge: 1`, `maxUnavailable: 0`) |
| Identidad | `serviceAccountName: webhook-sa`, `automountServiceAccountToken: false` |
| Reparto | `podAntiAffinity` **preferred** por `kubernetes.io/hostname`: separa réplicas entre workers sin bloquear el despliegue si no hay nodos suficientes |

#### Exposición y red

- `webhook-service` es un `Service` ClusterIP publicado por **NGINX Ingress** (`webhook-ingress.yaml`, host `webhook.local`) que expone **solo** `/alert` y `/health` (rutas `Exact`); `/ready` y `/api/chat` no se publican. Grafana se expone en `grafana.local`
- **`NetworkPolicy`** (`dev/network-policy.yaml`): *default-deny* en `dev`; permite ingreso al webhook (puerto 8000) solo desde `ingress-nginx` y el namespace `monitoring`; y `allow-webhook-to-timescaledb` permite al webhook llegar a TimescaleDB (5432)
- En `kind`, el Ingress no es alcanzable desde Windows sin `extraPortMappings`; para pruebas se usa `kubectl port-forward`

#### Secrets (sin valores en el repositorio)

| Secret | Namespace | Contenido |
|---|---|---|
| `webhook-secret` | `dev` | 5 claves: `GROQ_API_KEY`, `NOC_WEBHOOK_TOKEN`, `PG_PASSWORD`, `JIRA_API_TOKEN`, `JIRA_USER` |
| `grafana-admin-secret` | `monitoring` | contraseña de admin de Grafana |
| `timescaledb-secret` | `dev` | credenciales de TimescaleDB |

Las plantillas `*.yaml.example` están versionadas y los secretos reales están en `.gitignore`. Al verificarlos, compara solo **nombres y largos** contra el `.env`.

> Nota: Grafana solo aplica la contraseña de admin al **crear su base**. Si el PVC ya existía, restablécela con `grafana cli admin reset-admin-password`.

#### Scheduling y RBAC de mínimo privilegio

Principio: partir de cero permisos y agregar solo lo que se puede justificar.

- **`webhook-sa`** (`webhook-serviceaccount.yaml`): identidad propia del webhook, **sin Role asociado y sin token montado**. El webhook no habla con la API de Kubernetes; si alguien explotara el contenedor, no tendría credencial para pivotar al clúster. Se verifica que `/var/run/secrets/kubernetes.io/serviceaccount` no exista dentro del pod
- **Grafana**: mismo patrón (`grafana-sa`, `automountServiceAccountToken: false`)
- **`noc-operator`** (`noc-operator-rbac.yaml`): rol de un operador NOC de guardia, limitado al namespace `dev`:

| Recurso | Verbos |
|---|---|
| `pods`, `pods/log`, `services`, `endpoints`, `events` | `get`, `list`, `watch` |
| `deployments`, `replicasets` (apps) | `get`, `list`, `watch` |
| `deployments` (apps) | `patch` (permite `rollout restart` y `rollout undo`) |

Exclusiones deliberadas: **`secrets`** (el operador no lee credenciales), **`pods/exec`** (no entra a los contenedores), **`delete`** (no borra recursos) y cualquier acceso a otros namespaces o recursos de clúster.

- **Taints, tolerations y affinity** (práctica de laboratorio): un taint repele pods de un nodo; la toleration solo *permite* entrar (no obliga); para dirigir el pod al nodo dedicado se combina con `nodeSelector`/`nodeAffinity`. `podAntiAffinity` `required` con más réplicas que nodos deja pods en `Pending`, por eso el proyecto usa `preferred`

Verificación del rol (matriz de pruebas, todas deben dar el resultado esperado):

```powershell
$sa = "system:serviceaccount:dev:noc-operator"
kubectl auth can-i get    pods              -n dev --as=$sa   # yes
kubectl auth can-i get    pods/log          -n dev --as=$sa   # yes
kubectl auth can-i patch  deployments.apps  -n dev --as=$sa   # yes
kubectl auth can-i delete pods              -n dev --as=$sa   # no
kubectl auth can-i get    secrets           -n dev --as=$sa   # no
kubectl auth can-i create pods/exec         -n dev --as=$sa   # no
kubectl auth can-i get    pods              -n monitoring --as=$sa   # no
kubectl auth can-i get    nodes             --as=$sa          # no
```

#### TimescaleDB en Kubernetes (`dev/timescaledb-statefulset.yaml`)

`StatefulSet` de 1 réplica (`timescale/timescaledb:2.17.2-pg16`) con `volumeClaimTemplate` RWO de 2Gi (`storageClassName: standard`). El clúster no trae el esquema (`incident_logs`, `network_telemetry`, `devices`); `main.py` solo crea `jira_dedup`. Para usarlo hay que cargar `sql/schema.sql`, `webhook_service.sql` e `sql/incident_views.sql`.

#### Red híbrida Docker ↔ Kubernetes

Hoy el webhook usa `PG_HOST=host.docker.internal` (TimescaleDB de Compose). Queda pendiente repuntarlo a `timescaledb-service` del clúster.

### Grafana en Kubernetes (provisioning)
Datasource, contact points, políticas, mute timings y reglas viven en `deploy/apps/grafana/grafana-provisioning/` y se montan como ConfigMaps con Kustomize.

- Aplicar: `kubectl apply -k deploy/apps/grafana`. Nunca `kubectl apply -f` sobre el Deployment (los ConfigMaps llevan hash en el nombre).
- Secret: `grafana-provisioning-secret` (PG_PASSWORD y NOC_WEBHOOK_TOKEN), copiado desde `webhook-secret`. Al rotar credenciales, recrearlo y ejecutar `kubectl rollout restart deployment/grafana -n monitoring`.
- Mientras Postgres siga en Docker, el datasource apunta a `host.docker.internal:5432`.
- No arrancar a la vez el Grafana de Docker y el de Kubernetes: cada alerta llegaría dos veces.

### Despliegue y validación en `kind` (paso a paso)

```powershell
# 1) Construir la imagen y cargarla al clúster
docker build -t noc-webhook-service:v1.0.12 .\webhook_service
kind load docker-image noc-webhook-service:v1.0.12 --name noc-local-cluster

# 2) Aplicar los manifiestos y esperar el rollout
kubectl apply -R -f .\deploy\local\dev\
kubectl rollout status deployment/webhook-deployment -n dev

# 3) Acceso local para pruebas
kubectl port-forward -n dev svc/webhook-service 8000:8000
```

> Un `port-forward` a un `Service` se pega a **un solo pod** y se cae cuando ese pod se reemplaza (por ejemplo en un `rollout undo`): hay que relanzarlo. Para probar varias réplicas se usa un `port-forward` por pod.

#### Resultados de la validación (Fase 3)

| Prueba | Resultado |
|---|---|
| `/health` y `/ready` | 200 en ambos (readiness comprueba el alcance a Postgres) |
| `/alert` sin token | 401 |
| `firing` → repetido → `resolved` | `ticket_created` → `comment_added` → `resolved` (ticket finalizado con la transición `Finalizar`) |
| `resolved` repetido | `resolved_no_open_ticket`, sin ruido en Jira |
| Grupo de 2 alertas en un payload | 2 tickets distintos, un `status` por alerta |
| `rollout restart` + `rollout undo` | `successfully rolled out` y `/ready` 200 tras revertir |
| 2 réplicas, mismo `alertname` + equipo, secuencial | un `ticket_created` y un `comment_added` con la misma key |
| 2 réplicas, peticiones simultáneas | un solo `ticket_created` (reserva atómica en `jira_dedup`) |
| Filas en Postgres | una fila de `jira_dedup` por alerta; todos los POST en `incident_logs` |

### Pendientes de la Fase 7

- Repuntar `PG_HOST` al `timescaledb-service` del clúster y cargar el esquema allí
- Inyectar `PG_DSN` en los manifiestos (el Data Agent no funciona en Kubernetes sin esa variable; confirmar si `data_agent.py` la exige)
- Confirmar que el CNI de `kind` (kindnet) aplica las `NetworkPolicy`
- Agregar `extraPortMappings` a `kind-3nodes.yaml` para alcanzar el Ingress desde Windows
- Medir la memoria real del webhook (`docker stats`) y ajustar el límite de 512Mi
- Verificar que `webhook_service/.env` no entra a la imagen (`.dockerignore`)
- `JIRA_URL` en el ConfigMap revela el nombre del sitio Atlassian: revisar antes de publicar el repositorio
- Provisionar `grafana/provisioning/` (datasource, contact point con `NOC_WEBHOOK_TOKEN`, reglas) en el Grafana del clúster
- Kustomize con overlays (réplicas: 1 en `dev`, 2 en producción)
- `NetworkPolicy` de egress
- CHANGELOG, runbook (incluido el rol `noc-operator`) y checklist de rotación de secretos
- Reactivar el push a ACR + despliegue a AKS en `ci.yml`

---

## 🔍 Troubleshooting

### "AlertRule has no datasource"
**Causa:** la UID en `alert_rules.yml` no coincide con la del datasource. **Solución:** cópiala desde **Administration → Connections → Datasources**.

### "Connection refused" entre Grafana y PostgreSQL
```powershell
docker network inspect noc_net
docker exec grafana ping timescaledb
```

### El Webhook Service responde `401 Unauthorized`
**Causa:** `NOC_WEBHOOK_TOKEN` no coincide entre `.env`/Secret y `contact_points.yml`. **Solución (Compose):**
```powershell
docker compose up -d --force-recreate grafana webhook-service
```

### El Webhook Service no arranca: "Faltan variables de entorno obligatorias"
**Causa:** `main.py` valida `PG_*`, `JIRA_*` y `NOC_WEBHOOK_TOKEN` al iniciar y muestra solo los **nombres** faltantes. **Solución:** revisa el `.env` (Compose) o el Secret/ConfigMap (Kubernetes).

### `/alert` responde `503` (`partial_failure`)
**Causa:** Jira o Postgres no respondieron (diseño *fail-closed*): el servicio prefiere fallar a crear duplicados. Grafana reintenta solo. **Revisa:**
```powershell
docker logs webhook_service --tail 50 | Select-String "Jira|Postgres"
# Kubernetes:
kubectl logs -n dev deploy/webhook-deployment --tail=50
```

### `/ready` responde `503`
**Causa:** el pod no alcanza Postgres. En el clúster `kind` con la red híbrida, comprueba `host.docker.internal:5432` y la `NetworkPolicy` hacia TimescaleDB.

### El ticket se crea pero el `resolved` no lo cierra
**Causa:** `JIRA_RESOLVE_TRANSITION_NAME` no coincide con el nombre exacto de la transición del workflow (el default del código es `Done`; este proyecto usa `Finalizar`). El comentario sí se agrega (`transitioned: false`). **Solución:** define la variable en `.env`/ConfigMap y reinicia el servicio.

### El ticket de Jira no se crea (`jira.created: false`)
**Causa 1:** faltan variables Jira. **Causa 2:** API Token expirado o sin permisos.
```powershell
docker logs webhook_service --tail 50 | Select-String "Jira"
```

### La búsqueda JQL falla o responde `410 Gone`
**Causa:** se usa el endpoint clásico `/rest/api/3/search`, retirado por Atlassian. **Solución:** el código debe apuntar a `POST /rest/api/3/search/jql`.

### Se duplican tickets con varias réplicas
**Causa:** las réplicas no comparten el mismo Postgres, o `jira_dedup` no existe. **Verifica:**
```powershell
docker exec -i timescaledb psql -U noc_user -d noc -c "SELECT fingerprint, issue_key, state FROM jira_dedup ORDER BY updated_at DESC LIMIT 10;"
```

### El pod sigue montando el token de ServiceAccount
**Causa:** el deployment no tiene `serviceAccountName`/`automountServiceAccountToken: false`. **Verifica:**
```powershell
kubectl get pods -n dev -o custom-columns="POD:.metadata.name,SA:.spec.serviceAccountName,AUTOMOUNT:.spec.automountServiceAccountToken"
```
Si muestra `default`, aplica de nuevo `deploy/base/` y `deploy/apps/`.

### `kubectl auth can-i ... --as=...` devuelve un resultado inesperado
**Causa:** el Role o el RoleBinding no se aplicaron, o el `RoleBinding` apunta a otro namespace/SA. **Verifica:** `kubectl get sa,role,rolebinding -n dev`.

### Grafana en Kubernetes no acepta la contraseña del Secret
**Causa:** Grafana solo aplica la contraseña al crear su base y el PVC ya existía. **Solución:** `grafana cli admin reset-admin-password` dentro del pod.

### El Supervisor cae siempre en `human_in_the_loop` (fallback)
**Causa:** el LLM no devuelve JSON parseable (bloques `<think>` sin cerrar, o `GROQ_API_KEY` inválida/rate-limited).
```powershell
docker logs webhook_service --tail 100 | Select-String "Fallo de parseo|FALLBACK"
```

### El Data_Agent rechaza toda consulta con "operaciones no permitidas"
**Causa esperada:** el validador bloquea cualquier sentencia que no sea `SELECT` puro sobre `network_telemetry` — es una medida de seguridad, no un bug.

### El notebook de Jupyter no conecta a TimescaleDB
```powershell
docker exec jupyter_ml python -c "import os; print('PG_DSN definido:', bool(os.environ.get('PG_DSN')))"
docker network inspect noc_net
```

### El dashboard de Postmortem no muestra datos
**Causa:** `incident_views.sql` no se ejecutó, o aún no hay pares `firing`/`resolved`. **Solución:** paso 6 de instalación y `simulate_mttr_incidents.py`.

### Quiero volver a usar Slack en vez del Webhook Service
Cambia `type: webhook` por `type: slack` en `contact_points.yml`.

---

## 🔐 Seguridad

### Credenciales y laboratorio

- **Compose sin credenciales por defecto**: todas las contraseñas y tokens salen del `.env`; el servicio no inicia sin ellas
- `.gitignore` y `.dockerignore` excluyen `.env`, Secrets reales y archivos temporales; solo se versionan plantillas `*.example`
- En Kubernetes, las credenciales viven en `Secret` y la config no sensible en `ConfigMap`; ningún valor real se versiona

### Controles implementados

- `POST /alert` y `POST /api/chat` **exigen** `Authorization: Bearer <NOC_WEBHOOK_TOKEN>`, con `secrets.compare_digest`
- **Fail-closed**: si Jira o Postgres no responden, el servicio devuelve `503` en vez de arriesgar duplicados; Grafana reintenta
- **Deduplicación atómica** en Postgres: mismo ticket aunque varias réplicas reciban la misma alerta a la vez
- **Validación de entorno al arrancar**, mostrando solo nombres de variables, nunca valores
- **Text-to-SQL blindado**: el Data_Agent solo ejecuta `SELECT` validados y forzados a `network_telemetry`, con `LIMIT 200`
- **Compuerta HITL obligatoria** para severidad `P1`, acciones irreversibles o fallos de parseo del Supervisor
- **Sanitización de salida** de modelos Open Source (bloques `<think>`) antes de cualquier parseo
- **Checkpointer persistente** en Postgres: el estado del NOC-MAS sobrevive a reinicios y permite escalar a varias réplicas
- **Kubernetes**: NetworkPolicy *default-deny*, Ingress mínimo (`/alert` y `/health`), ServiceAccount sin token montado, rol `noc-operator` sin acceso a `secrets`, `exec` ni `delete`, y límites de recursos

### En producción

- Usa un secret manager (Vault, AWS/GCP Secrets Manager, Azure Key Vault) o un CSI driver de secretos en el clúster
- Rota `NOC_WEBHOOK_TOKEN`, `JIRA_API_TOKEN`, `GROQ_API_KEY` y `PG_PASSWORD` periódicamente, y **de inmediato** si alguno se pegó en un chat, ticket o log
- Cambia la contraseña de Grafana Admin y el token de Jupyter tras el despliegue
- No publiques los puertos `8000` y `8888` fuera del host; usa reverse proxy con TLS
- Recuerda que `JIRA_URL` revela el nombre del sitio Atlassian si el repositorio es público

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
- ✅ Integración con **JIRA** para auto-tickets zero-touch
- ✅ **Autenticación Bearer Token** en `POST /alert`
- ✅ **Escalado geográfico multi-región**: 3 simuladores sobre una hypertable única
- ✅ Extensión del esquema con la dimensión `region`
- ✅ **Dashboards de postmortem** con MTTR, conteo de incidentes e historial
- ✅ Vistas JSONB refactorizadas (`incident_views.sql`) y variable `$region` en ambos dashboards

### ✅ Fase 5 — ML, Multiagencia y ChatOps (completada)
- ✅ Deduplicación en Jira y cierre automático de tickets al recibir `resolved`
- ✅ **ML Analytics Hub** (Jupyter) y detección dinámica de anomalías con `IsolationForest`
- ✅ **NOC-MAS** en LangGraph: `NOCState`, `StateGraph` jerárquico, Supervisor, Data Agent (Text-to-SQL seguro), Action Agent (Pydantic)
- ✅ **Compuerta HITL** con `interrupt_before`
- ✅ Sanitización de bloques `<think>` con validación `PydanticOutputParser` y *fallback* seguro
- ✅ **ChatOps UI en Streamlit** con sidebar de estado

### ✅ Fase 6 — Cierre del loop conversacional, persistencia y CI (completada)
- ✅ ChatOps UI cableada de punta a punta con `POST /api/chat` y `thread_id` estable por sesión
- ✅ `Responder_Agent` para respuestas ejecutivas en lenguaje natural
- ✅ Checkpointer `PostgresSaver`
- ✅ Pruebas unitarias + CI (`ci.yml`, `.gitlab-ci.yml`)
- [ ] Exponer los hallazgos del `IsolationForest` como feature del Data_Agent
- [ ] Endpoint dedicado `POST /noc-mas/invoke`, desacoplado de `/alert`
- [ ] Dashboard ejecutivo de MTTR y decisiones del NOC-MAS (SLA/SLO)
- [ ] Autenticación de la ChatOps UI (hoy sin login en `8501`)

### ✅ Hardening del Webhook Service — v1.0.12 (completado en Docker)
- ✅ Autenticación por token en el webhook y en el chat; Grafana → webhook con `authorization_credentials`
- ✅ Varias alertas por payload (`split_alerts`) y títulos de ticket estables
- ✅ **Fail-closed con Jira** (`verify_jira_auth` → `503` para que Grafana reintente)
- ✅ **Deduplicación atómica** con tabla `jira_dedup` (`PRIMARY KEY` + `ON CONFLICT`), válida entre réplicas
- ✅ Cierre de tickets con la transición `Finalizar`
- ✅ `/health` (liveness) y `/ready` (readiness, solo Postgres)
- ✅ Validación de variables de entorno, `run_in_threadpool` y pool de conexiones (`maxconn=20`)
- ✅ Compose sin credenciales por defecto; reglas de `.gitignore` y `.dockerignore`

### 🚧 Fase 7 — Cloud-Native / Kubernetes (en curso)
- ✅ Manifiestos para AKS (`k8s/`) y script de aprovisionamiento Azure (`deploy-azure-infra.ps1`)
- ✅ Clúster local multinodo con `kind` y namespaces `dev`/`monitoring`
- ✅ Webhook en `v1.0.12` con probes (`startup`, `liveness`, `readiness`), límite de memoria, `revisionHistoryLimit` y `terminationGracePeriodSeconds`
- ✅ `NetworkPolicy` *default-deny* + reglas hacia el webhook y hacia TimescaleDB
- ✅ Ingress mínimo (`/alert` y `/health`) para el webhook y Ingress para Grafana
- ✅ Grafana `13.0.2` con contraseña desde Secret, `fsGroup` y probes
- ✅ Secrets reales fuera del repositorio y plantillas `*.yaml.example`
- ✅ **RBAC de mínimo privilegio**: `webhook-sa` sin token, rol `noc-operator` y `podAntiAffinity` preferred
- ✅ **Validación funcional** en Kubernetes: alertas `firing`/`resolved`/grupo, `rollout undo` y deduplicación entre 2 réplicas
- ✅ TimescaleDB como `StatefulSet` con volumen RWO
- ✅ Pipeline equivalente en GitLab CI
- ⏸️ Push a ACR y despliegue a AKS escritos en `ci.yml`, pausados
- [ ] Repuntar `PG_HOST` al `timescaledb-service` y cargar el esquema en el clúster
- [ ] Inyectar `PG_DSN` en los manifiestos
- [ ] Provisioning de Grafana en Kubernetes (datasource, contact point, reglas, `NOC_WEBHOOK_TOKEN`)
- [ ] Kustomize con overlays, `NetworkPolicy` de egress
- [ ] CHANGELOG, runbook y README operativo

### 🧱 Deuda técnica registrada
- Timeout de Streamlit de 30 s frente a respuestas del chat de 22 a 111 s
- Indicadores fijos del sidebar de la ChatOps UI
- *Mojibake* (codificación) en `alert_rules.yml`
- `execErrState` en `Error` en las reglas de alerta
- `/api/chat`: tipo de `reply`, fuga de mensajes de error al cliente, `thread_id` por defecto y endpoint HITL
- La verificación de memoria del webhook y los límites de recursos están pendientes de medición

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
- **Kubernetes (RBAC):** https://kubernetes.io/docs/reference/access-authn-authz/rbac/
- **Kubernetes (taints, tolerations y affinity):** https://kubernetes.io/docs/concepts/scheduling-eviction/
- **kind:** https://kind.sigs.k8s.io/

---

## 📝 Contribuciones

Este proyecto sigue **Infrastructure as Code** como principio rector. Cualquier cambio en alertas, dashboards, datasources, esquema, Webhook Service, grafo del NOC-MAS o manifiestos de Kubernetes debe pasar por código y Git.

**Workflow:**
1. Crea una rama de trabajo (`git switch -c chore/<tema>`) desde `kubernetes` o `main`
2. Edita el YAML/SQL/código correspondiente
3. Commit descriptivo (un tema por commit)
4. Abre PR / merge y haz push a `origin` y `gitlab`
5. Redeploy: `docker compose up -d --build` (Compose) o `kubectl apply -R -f .\deploy\local\dev\` (Kubernetes)
6. Valida el cambio en la UI, con `Invoke-RestMethod` o con la matriz de pruebas de la sección Kubernetes

---

**Mantenido por:** Rodrigo Codoceo.
**Última actualización:** Octubre 2026
**Versión:** 7.0 (Webhook v1.0.12 · dedup atómico multi-réplica · Kubernetes local endurecido con RBAC de mínimo privilegio)