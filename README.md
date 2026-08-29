
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

### 8. 🆕 Poblar datos de entrenamiento y validar el modelo ML

```powershell
cd python-simulator
python simulate_mttr_incidents.py --webhook-url "http://localhost:8000/alert"
cd ..
```

Abre `http://localhost:8888` (token = `JUPYTER_TOKEN`) y ejecuta `notebooks/anomaly_detection.ipynb` de punta a punta para entrenar y validar el `IsolationForest`.

### 9. 🆕 Verificar el NOC-MAS y la ChatOps UI

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

### 🆕 Interactuar con el NOC-MAS desde la ChatOps UI

Abre `http://localhost:8501`. El sidebar muestra el estado de conectividad y métricas rápidas (incidentes abiertos, MTTR promedio, agentes activos, uptime). Escribe consultas o instrucciones en lenguaje natural en el campo de chat; el Supervisor decide si el flujo debe pasar por `Data_Agent`, `Action_Agent` o detenerse en la compuerta `human_in_the_loop`.

### 🆕 Ejecutar el NOC-MAS directamente (fuera de la UI)

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

### 🆕 `NOCState` — estado compartido del NOC-MAS (`src/state.py`)

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

### 🆕 La búsqueda JQL de deduplicación falla o responde `410 Gone`
**Causa:** se está usando el endpoint clásico `GET/POST /rest/api/3/search`, retirado por Atlassian (CHANGE-2046). **Solución:** confirma que el código apunte a `POST /rest/api/3/search/jql`; revisa logs:
```powershell
docker logs webhook_service --tail 50 | Select-String "búsqueda JQL"
```

### 🆕 El Supervisor cae siempre en `human_in_the_loop` (fallback)
**Causa:** el LLM no está devolviendo JSON parseable por `PydanticOutputParser` (típico en modelos que emiten bloques `<think>` sin cerrarse, o `GROQ_API_KEY` inválida/rate-limited).
```powershell
docker logs webhook_service --tail 100 | Select-String "Fallo de parseo|FALLBACK"
```
Verifica `GROQ_API_KEY` y considera bajar `temperature` o cambiar `NOC_SUPERVISOR_MODEL`.

### 🆕 El Data_Agent rechaza toda consulta con "operaciones no permitidas"
**Causa esperada:** el validador (`_validate_query`) bloquea cualquier sentencia que no sea `SELECT` puro sobre `network_telemetry`, o que contenga `INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/GRANT/REVOKE/CREATE` — es una medida de seguridad, no un bug. Reformula la pregunta en lenguaje natural para que derive en un `SELECT` válido.

### 🆕 El notebook de Jupyter no conecta a TimescaleDB
```powershell
docker exec jupyter_ml python -c "import os; print(os.environ['PG_DSN'])"
docker network inspect noc_net
```
Confirma que `jupyter_ml` esté en `noc_net` y que `PG_DSN` apunte a `timescaledb:5432`.

### 🆕 La ChatOps UI no refleja respuestas reales del NOC-MAS
**Causa esperada (temporal):** `chatops-ui/app.py` opera en **modo standalone** — la llamada a `orchestrator.invoke()` aún no está cableada al backend HTTP; ver Roadmap Fase 5 pendiente.

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
- **🆕 Text-to-SQL blindado**: el Data_Agent solo ejecuta `SELECT` validados por regex y forzados a `network_telemetry`, con `LIMIT 200` — el LLM nunca tiene acceso a credenciales de escritura ni a otras tablas
- **🆕 Compuerta HITL obligatoria**: cualquier severidad `P1`, acción irreversible o fallo de parseo del Supervisor enruta forzosamente a `human_in_the_loop`, deteniendo el grafo (`interrupt_before`) hasta aprobación explícita
- **🆕 Sanitización de salida de modelos Open Source**: `clean_think_tags()` elimina bloques `<think>` antes de cualquier parseo, evitando inyección de contenido no estructurado en el pipeline de decisión

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