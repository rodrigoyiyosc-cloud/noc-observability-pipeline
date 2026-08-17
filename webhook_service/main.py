import json
import logging
import os
import secrets
from datetime import datetime, timezone

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from fastapi import FastAPI, Request, Security, HTTPException, status
from fastapi.security import APIKeyHeader

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("webhook_service")

app = FastAPI(title="NOC Webhook Service")

# ── Configuración desde variables de entorno ────────────────────────────────
PG_HOST = os.environ.get("PG_HOST", "postgres")
PG_PORT = os.environ.get("PG_PORT", "5432")
PG_DB = os.environ.get("PG_DB", "noc_db")
PG_USER = os.environ.get("PG_USER", "noc_user")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "secret")

pool: SimpleConnectionPool | None = None

# ── Configuración Jira desde variables de entorno ───────────────────────────
JIRA_URL = os.environ.get("JIRA_URL")
JIRA_USER = os.environ.get("JIRA_USER")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY")

# ── Autenticación del webhook (Bearer Token compartido) ─────────────────────
NOC_WEBHOOK_TOKEN = os.environ.get("NOC_WEBHOOK_TOKEN")
if not NOC_WEBHOOK_TOKEN:
    raise RuntimeError("NOC_WEBHOOK_TOKEN no está configurado en el entorno.")

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def verify_token(authorization: str | None = Security(api_key_header)):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el header Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, NOC_WEBHOOK_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True

def extract_jira_fields(payload: dict) -> tuple[str, str, str]:
    """
    Extrae severidad, título y estado del payload de Grafana
    para construir el ticket en Jira.
    """
    status = payload.get("status", "unknown")
    title = payload.get("title") or payload.get("ruleName") or "Alerta NOC sin título"
    severity = "critical"

    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts:
        labels = alerts[0].get("labels", {})
        severity = labels.get("severity", severity)
        if not payload.get("title"):
            title = labels.get("alertname", title)

    return status, title, severity


def map_priority(severity: str) -> str:
    mapping = {
        "critical": "Highest",
        "high": "High",
        "warning": "Medium",
        "info": "Low",
    }
    return mapping.get(severity.lower(), "Medium")

async def create_jira_ticket(status: str, title: str, severity: str, payload: dict) -> dict:
    if not all([JIRA_URL, JIRA_USER, JIRA_API_TOKEN, JIRA_PROJECT_KEY]):
        logger.error("Credenciales de Jira no configuradas; se omite creación de ticket.")
        return {"created": False, "reason": "missing_credentials"}

    url = f"{JIRA_URL}/rest/api/3/issue"

    description_text = (
        f"Estado: {status}\nSeveridad: {severity}\n\n"
        f"Payload:\n{json.dumps(payload, indent=2, ensure_ascii=False)}"
    )

    issue_payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": f"[{severity.upper()}] {title}",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description_text}],
                    }
                ],
            },
            "issuetype": {"name": "Incident"},
            "priority": {"name": map_priority(severity)},
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json=issue_payload,
                auth=(JIRA_USER, JIRA_API_TOKEN),
                headers={"Content-Type": "application/json"},
            )
        response.raise_for_status()
        data = response.json()
        logger.info("Ticket Jira creado: %s", data.get("key"))
        return {"created": True, "key": data.get("key")}
    except httpx.HTTPStatusError as exc:
        logger.error("Error Jira %s: %s", exc.response.status_code, exc.response.text)
        return {"created": False, "reason": exc.response.text}
    except Exception as exc:
        logger.error("Fallo al crear ticket Jira: %s", exc)
        return {"created": False, "reason": str(exc)}

@app.on_event("startup")
def startup():
    global pool
    pool = SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
    )
    logger.info("Pool de conexiones PostgreSQL inicializado (%s:%s/%s)", PG_HOST, PG_PORT, PG_DB)


@app.on_event("shutdown")
def shutdown():
    if pool:
        pool.closeall()


def extract_alert_fields(payload: dict) -> tuple[str | None, str | None]:
    """
    Extrae status y alert_name del payload estándar de Grafana.
    Grafana envía 'status' a nivel raíz y 'alerts' como lista;
    tomamos el nombre de la primera alerta si existe.
    """
    status = payload.get("status")
    alert_name = None

    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts:
        labels = alerts[0].get("labels", {})
        alert_name = labels.get("alertname")

    if alert_name is None:
        alert_name = payload.get("title") or payload.get("ruleName")

    return status, alert_name


def insert_incident(status: str | None, alert_name: str | None, payload: dict):
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO incident_logs (status, alert_name, payload)
                VALUES (%s, %s, %s)
                """,
                (status, alert_name, json.dumps(payload)),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@app.post("/alert", dependencies=[Security(verify_token)])
async def receive_alert(request: Request):
    payload = await request.json()

    logger.info(
        "ALERT RECEIVED at %s\n%s",
        datetime.now(timezone.utc).isoformat(),
        json.dumps(payload, indent=2, ensure_ascii=False),
    )

    status_, alert_name = extract_alert_fields(payload)

    try:
        insert_incident(status_, alert_name, payload)
    except Exception as exc:
        logger.error("Fallo al insertar en PostgreSQL: %s", exc)

    jira_status, jira_title, jira_severity = extract_jira_fields(payload)
    jira_result = await create_jira_ticket(jira_status, jira_title, jira_severity, payload)

    return {"status": "received", "persisted": True, "jira": jira_result}


@app.get("/health")
async def health():
    return {"status": "ok"}