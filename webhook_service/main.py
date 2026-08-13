import json
import logging
import os
from datetime import datetime, timezone

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from fastapi import FastAPI, Request

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


@app.post("/alert")
async def receive_alert(request: Request):
    payload = await request.json()

    logger.info(
        "ALERT RECEIVED at %s\n%s",
        datetime.now(timezone.utc).isoformat(),
        json.dumps(payload, indent=2, ensure_ascii=False),
    )

    status, alert_name = extract_alert_fields(payload)

    try:
        insert_incident(status, alert_name, payload)
    except Exception as exc:
        logger.error("Fallo al insertar en PostgreSQL: %s", exc)
        return {"status": "received", "persisted": False}

    return {"status": "received", "persisted": True}


@app.get("/health")
async def health():
    return {"status": "ok"}