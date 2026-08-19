import json
import logging
import os
import re
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

# Nombre de la transición de Jira usada para cerrar el ticket cuando Grafana
# envía status=resolved. Ajusta este valor al nombre exacto de tu workflow
# (ej. "Done", "Resuelto", "Close Issue"). Si no existe, solo se comenta.
JIRA_RESOLVE_TRANSITION_NAME = os.environ.get("JIRA_RESOLVE_TRANSITION_NAME", "Done")

# Tipo de issue a crear en Jira (ya lo tenías en .env pero antes estaba
# hardcodeado en el código; ahora se respeta lo configurado).
JIRA_ISSUE_TYPE = os.environ.get("JIRA_ISSUE_TYPE", "Incident")

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


# ── Extracción de campos del payload de Grafana ─────────────────────────────

def extract_alert_fields(payload: dict) -> tuple[str | None, str | None]:
    """
    Extrae status y alert_name del payload estándar de Grafana.
    Grafana envía 'status' a nivel raíz y 'alerts' como lista;
    tomamos el nombre de la primera alerta si existe.
    """
    status_ = payload.get("status")
    alert_name = None

    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts:
        labels = alerts[0].get("labels", {})
        alert_name = labels.get("alertname")

    if alert_name is None:
        alert_name = payload.get("title") or payload.get("ruleName")

    return status_, alert_name


def extract_device_name(payload: dict) -> str:
    """
    Extrae el nombre del dispositivo/nodo/host afectado por la alerta,
    revisando las claves más comunes que Grafana suele incluir en los
    labels de la primera alerta, y con fallback a nivel raíz del payload.
    """
    candidate_keys = ("device", "host", "hostname", "instance", "node", "pod", "service")

    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts:
        labels = alerts[0].get("labels", {}) or {}
        for key in candidate_keys:
            if labels.get(key):
                return str(labels[key])

    for key in candidate_keys:
        if payload.get(key):
            return str(payload[key])

    return "desconocido"


def extract_jira_fields(payload: dict) -> tuple[str, str]:
    """
    Extrae título y severidad del payload de Grafana para construir el ticket.
    """
    title = payload.get("title") or payload.get("ruleName") or "Alerta NOC sin título"
    severity = "critical"

    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts:
        labels = alerts[0].get("labels", {})
        severity = labels.get("severity", severity)
        if not payload.get("title"):
            title = labels.get("alertname", title)

    return title, severity


def map_priority(severity: str) -> str:
    mapping = {
        "critical": "Highest",
        "high": "High",
        "warning": "Medium",
        "info": "Low",
    }
    return mapping.get(severity.lower(), "Medium")


def slugify(value: str, prefix: str) -> str:
    """
    Convierte un nombre de alerta/dispositivo en un label válido de Jira
    (sin espacios ni comas). Se usa como huella (fingerprint) determinística
    para poder buscar el mismo par alerta+dispositivo vía JQL.
    """
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    if not normalized:
        normalized = "unknown"
    return f"{prefix}-{normalized}"[:100]


# ── Integración con Jira: búsqueda JQL, comentarios, creación y resolución ──

async def find_open_jira_ticket(alert_label: str, device_label: str) -> str | None:
    """
    Busca vía JQL si ya existe un ticket ABIERTO para la misma combinación
    alerta+dispositivo, usando los labels como huella de deduplicación.

    NOTA (Jira Cloud, CHANGE-2046): el endpoint clásico GET/POST
    /rest/api/3/search fue RETIRADO por Atlassian y ahora responde 410 Gone.
    El reemplazo soportado es POST /rest/api/3/search/jql, que además cambia
    el modelo de paginación (nextPageToken/isLast en vez de startAt/total;
    no afecta este caso porque solo pedimos 1 resultado).

    Se usa 'resolution = Unresolved' en lugar de 'statusCategory != Done'
    porque statusCategory puede venir traducido/renombrado según el idioma
    o el esquema de workflow del proyecto, mientras que 'resolution' es un
    campo de sistema estable independiente del idioma de la instancia.
    """
    jql = (
        f'project = "{JIRA_PROJECT_KEY}" '
        f'AND resolution = Unresolved '
        f'AND labels = "{alert_label}" '
        f'AND labels = "{device_label}" '
        f'ORDER BY created DESC'
    )
    url = f"{JIRA_URL}/rest/api/3/search/jql"
    body = {
        "jql": jql,
        "maxResults": 1,
        "fields": ["key", "status", "resolution"],
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json=body,
                auth=(JIRA_USER, JIRA_API_TOKEN),
                headers={"Content-Type": "application/json"},
            )
        response.raise_for_status()
        issues = response.json().get("issues", [])
        if issues:
            key = issues[0]["key"]
            logger.info("Ticket abierto existente encontrado: %s", key)
            return key
        return None
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Error Jira %s en búsqueda JQL: %s", exc.response.status_code, exc.response.text
        )
        return None
    except Exception as exc:
        logger.error("Fallo en búsqueda JQL de Jira: %s", exc)
        return None


async def add_jira_comment(issue_key: str, text: str) -> bool:
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}/comment"
    comment_payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json=comment_payload,
                auth=(JIRA_USER, JIRA_API_TOKEN),
                headers={"Content-Type": "application/json"},
            )
        response.raise_for_status()
        logger.info("Comentario agregado en %s", issue_key)
        return True
    except Exception as exc:
        logger.error("Fallo al comentar en %s: %s", issue_key, exc)
        return False


async def try_resolve_jira_ticket(issue_key: str) -> bool:
    """
    [Bonus Tier 1] Intenta transicionar el ticket a la transición configurada
    en JIRA_RESOLVE_TRANSITION_NAME (ej. "Done"). Si no existe esa transición
    en el workflow del ticket, se registra y se continúa sin fallar.
    """
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}/transitions"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, auth=(JIRA_USER, JIRA_API_TOKEN))
        response.raise_for_status()
        transitions = response.json().get("transitions", [])
        match = next(
            (t for t in transitions if t.get("name", "").lower() == JIRA_RESOLVE_TRANSITION_NAME.lower()),
            None,
        )
        if not match:
            logger.warning(
                "Transición '%s' no disponible para %s; se deja solo el comentario.",
                JIRA_RESOLVE_TRANSITION_NAME,
                issue_key,
            )
            return False

        async with httpx.AsyncClient(timeout=10) as client:
            response2 = await client.post(
                url,
                json={"transition": {"id": match["id"]}},
                auth=(JIRA_USER, JIRA_API_TOKEN),
                headers={"Content-Type": "application/json"},
            )
        response2.raise_for_status()
        logger.info("Ticket %s transicionado a '%s'", issue_key, JIRA_RESOLVE_TRANSITION_NAME)
        return True
    except Exception as exc:
        logger.error("Fallo al transicionar %s: %s", issue_key, exc)
        return False


async def create_jira_ticket(title: str, severity: str, payload: dict, labels: list[str]) -> dict:
    url = f"{JIRA_URL}/rest/api/3/issue"

    description_text = (
        f"Severidad: {severity}\n\n"
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
            "issuetype": {"name": JIRA_ISSUE_TYPE},
            "priority": {"name": map_priority(severity)},
            "labels": labels,
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


async def handle_jira_dedup(
    status_: str | None,
    alert_name: str | None,
    device_name: str,
    payload: dict,
) -> dict:
    """
    Orquesta la lógica de Deduplicación Inteligente:
    1. Busca por JQL un ticket abierto para el par (alerta, dispositivo).
    2. Si status == "resolved": comenta y trata de cerrar el ticket existente.
    3. Si existe ticket abierto: comenta "la anomalía persiste" (sin crear).
    4. Si no existe ticket abierto: crea uno nuevo con los labels de huella.
    """
    if not all([JIRA_URL, JIRA_USER, JIRA_API_TOKEN, JIRA_PROJECT_KEY]):
        logger.error("Credenciales de Jira no configuradas; se omite la integración.")
        return {"action": "skipped", "reason": "missing_credentials"}

    alert_label = slugify(alert_name or "sin-alerta", "al")
    device_label = slugify(device_name or "sin-dispositivo", "dev")

    existing_key = await find_open_jira_ticket(alert_label, device_label)
    now_iso = datetime.now(timezone.utc).isoformat()

    if status_ == "resolved":
        if not existing_key:
            return {"action": "resolved_no_open_ticket"}

        resolved_text = (
            f"✅ Alerta RESUELTA ({now_iso}).\n"
            f"Dispositivo: {device_name}\nAlerta: {alert_name}\n\n"
            f"Payload:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        commented = await add_jira_comment(existing_key, resolved_text)
        transitioned = await try_resolve_jira_ticket(existing_key)
        return {
            "action": "resolved",
            "key": existing_key,
            "commented": commented,
            "transitioned": transitioned,
        }

    # status "firing" (o cualquier otro distinto de "resolved")
    if existing_key:
        persist_text = (
            f"⚠️ La anomalía PERSISTE ({now_iso}).\n"
            f"Dispositivo: {device_name}\nAlerta: {alert_name}\n\n"
            f"Payload actual:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        commented = await add_jira_comment(existing_key, persist_text)
        return {"action": "comment_added", "key": existing_key, "commented": commented, "created": False}

    title, severity = extract_jira_fields(payload)
    result = await create_jira_ticket(title, severity, payload, [alert_label, device_label])
    result["action"] = "ticket_created"
    return result


# ── PostgreSQL ───────────────────────────────────────────────────────────────

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


def insert_incident(status_: str | None, alert_name: str | None, payload: dict):
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO incident_logs (status, alert_name, payload)
                VALUES (%s, %s, %s)
                """,
                (status_, alert_name, json.dumps(payload)),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/alert", dependencies=[Security(verify_token)])
async def receive_alert(request: Request):
    payload = await request.json()

    logger.info(
        "ALERT RECEIVED at %s\n%s",
        datetime.now(timezone.utc).isoformat(),
        json.dumps(payload, indent=2, ensure_ascii=False),
    )

    status_, alert_name = extract_alert_fields(payload)
    device_name = extract_device_name(payload)

    try:
        insert_incident(status_, alert_name, payload)
    except Exception as exc:
        logger.error("Fallo al insertar en PostgreSQL: %s", exc)

    jira_result = await handle_jira_dedup(status_, alert_name, device_name, payload)

    return {"status": "received", "persisted": True, "jira": jira_result}


@app.get("/health")
async def health():
    return {"status": "ok"}