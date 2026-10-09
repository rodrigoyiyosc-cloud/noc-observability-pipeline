import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from fastapi import FastAPI, Request, Security, HTTPException, status
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool

import httpx

from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage

def _require_env(*names: str) -> dict[str, str]:
    """Falla al arrancar si falta una variable o está vacía. Solo muestra los NOMBRES."""
    values = {n: os.environ.get(n) for n in names}
    missing = [n for n, v in values.items() if not v or not v.strip()]
    if missing:
        raise RuntimeError("Faltan variables de entorno obligatorias: " + ", ".join(missing))
    return values


# Se valida ANTES de importar src.orchestrator, que también lee PG_* al cargarse.
_cfg = _require_env(
    "PG_HOST", "PG_PORT", "PG_DB", "PG_USER", "PG_PASSWORD",
    "JIRA_URL", "JIRA_USER", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY",
    "NOC_WEBHOOK_TOKEN",
)

from src.orchestrator import orchestrator, checkpointer_pool  # noqa: E402  (checkpointer=PostgresSaver)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("webhook_service")

app = FastAPI(title="NOC Webhook Service")

# ── Configuración desde variables de entorno ────────────────────────────────

PG_HOST = _cfg["PG_HOST"]
PG_PORT = _cfg["PG_PORT"]
PG_DB = _cfg["PG_DB"]
PG_USER = _cfg["PG_USER"]
PG_PASSWORD = _cfg["PG_PASSWORD"]

pool: ThreadedConnectionPool | None = None

# ── Configuración Jira desde variables de entorno ───────────────────────────
JIRA_URL = _cfg["JIRA_URL"]
JIRA_USER = _cfg["JIRA_USER"]
JIRA_API_TOKEN = _cfg["JIRA_API_TOKEN"]
JIRA_PROJECT_KEY = _cfg["JIRA_PROJECT_KEY"]

# Nombre de la transición de Jira usada para cerrar el ticket cuando Grafana
# envía status=resolved. Ajusta este valor al nombre exacto de tu workflow
# (ej. "Done", "Resuelto", "Close Issue"). Si no existe, solo se comenta.
JIRA_RESOLVE_TRANSITION_NAME = os.environ.get("JIRA_RESOLVE_TRANSITION_NAME", "Done")

# Tipo de issue a crear en Jira (ya lo tenías en .env pero antes estaba
# hardcodeado en el código; ahora se respeta lo configurado).
JIRA_ISSUE_TYPE = os.environ.get("JIRA_ISSUE_TYPE", "Incident")

# ── Autenticación del webhook (Bearer Token compartido) ─────────────────────
NOC_WEBHOOK_TOKEN = _cfg["NOC_WEBHOOK_TOKEN"]

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

# ── Esquemas Pydantic ────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default-session"  # Streamlit debe enviar un id estable por usuario/sesión


class ChatResponse(BaseModel):
    thread_id: str
    reply: str
    next_agent: str | None = None
    requires_human_approval: bool = False

async def verify_token(authorization: str | None = Security(api_key_header)):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el header Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token.encode("utf-8"), NOC_WEBHOOK_TOKEN.encode("utf-8")):
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
    Título del ticket, siempre con el mismo criterio:
    1. annotations.summary de la alerta (texto definido en la regla de Grafana)
    2. "<alertname> en <equipo>"
    El 'title' del payload NO se usa: Grafana lo genera con [FIRING:n] y
    las etiquetas, y cambia según el número de alertas en el POST.
    """
    severity = "critical"
    summary = None
    alertname = None

    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts and isinstance(alerts[0], dict):
        alert = alerts[0]
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        severity = labels.get("severity", severity)
        summary = (annotations.get("summary") or "").strip() or None
        alertname = labels.get("alertname")
        if alertname == "DatasourceNoData":
            return f"Sin datos de telemetría: {rule_identity(payload)}", severity

    if summary:
        title = summary
    elif alertname:
        device = extract_device_name(payload)
        title = alertname if device == "desconocido" else f"{alertname} en {device}"
    else:
        title = payload.get("ruleName") or "Alerta NOC sin título"

    return title, severity

def split_alerts(payload: dict) -> list[dict]:
    """
    Convierte un POST de Grafana con N alertas en N payloads de 1 alerta,
    cada uno con el status de ESA alerta.
    El 'title' del payload se descarta siempre (ver extract_jira_fields).
    """
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not alerts:
        return [payload]  # formato antiguo o sin lista: se procesa tal cual

    views = []
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        view = {k: v for k, v in payload.items() if k not in ("alerts", "title")}
        view["alerts"] = [alert]
        view["status"] = alert.get("status") or payload.get("status")
        views.append(view)

    return views or [payload]

def jira_failed(result: dict) -> bool:
    action = result.get("action")
    if action in ("jira_unavailable", "skipped", "jira_create_failed", "dedup_store_unavailable"):
        return True
    if action == "ticket_created":
        return not result.get("created")
    if action in ("comment_added", "resolved"):
        return not result.get("commented")
    return False

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
class JiraLookupError(Exception):
    """Jira no pudo responder la búsqueda: NO sabemos si existe un ticket."""

def rule_identity(payload: dict) -> str:
    """
    Identidad de la regla de origen para alertas sin equipo (DatasourceNoData).
    Usa la etiqueta 'rulename', que Grafana sí envía en esas alertas.
    """
    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts and isinstance(alerts[0], dict):
        labels = alerts[0].get("labels") or {}
        if labels.get("rulename"):
            return str(labels["rulename"])

        match = re.search(r"/alerting/grafana/([^/?]+)/view", alerts[0].get("generatorURL") or "")
        if match:
            return match.group(1)

        if alerts[0].get("fingerprint"):
            return str(alerts[0]["fingerprint"])

    return "sin-regla"

async def find_open_jira_ticket(alert_label: str, device_label: str) -> str | None:
    """
    Devuelve la key del ticket abierto, o None si de verdad NO existe.
    Si Jira falla (timeout, 401, 500...) lanza JiraLookupError: devolver None
    ahí haría creer que no hay ticket y crearía duplicados.
    """
    await verify_jira_auth()

    jql = (
        f'project = "{JIRA_PROJECT_KEY}" '
        f'AND resolution = Unresolved '
        f'AND labels = "{alert_label}" '
        f'AND labels = "{device_label}" '
        f'ORDER BY created DESC'
    )
    url = f"{JIRA_URL}/rest/api/3/search/jql"
    body = {"jql": jql, "maxResults": 1, "fields": ["key", "status", "resolution"]}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json=body,
                auth=(JIRA_USER, JIRA_API_TOKEN),
                headers={"Content-Type": "application/json"},
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("Error Jira %s en búsqueda JQL: %s", exc.response.status_code, exc.response.text)
        raise JiraLookupError(f"HTTP {exc.response.status_code}") from exc
    except Exception as exc:
        logger.error("Fallo en búsqueda JQL de Jira: %s", exc)
        raise JiraLookupError(str(exc)) from exc

    issues = response.json().get("issues", [])
    if issues:
        key = issues[0]["key"]
        logger.info("Ticket abierto existente encontrado: %s", key)
        return key
    return None

async def verify_jira_auth() -> None:
    """Lanza JiraLookupError si las credenciales no son válidas para Jira."""
    url = f"{JIRA_URL}/rest/api/3/myself"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, auth=(JIRA_USER, JIRA_API_TOKEN))
        response.raise_for_status()
        if not response.json().get("accountId"):
            raise JiraLookupError("Jira respondió sin identidad: credenciales no válidas")
    except JiraLookupError:
        raise
    except Exception as exc:
        logger.error("Fallo de autenticación con Jira: %s", exc)
        raise JiraLookupError(f"autenticación: {exc}") from exc


async def jira_issue_closed(issue_key: str) -> bool:
    """
    Consulta directa por key: es consistente, a diferencia de la búsqueda JQL,
    que depende del índice de Jira y puede no ver un ticket recién creado.
    """
    await verify_jira_auth()
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}?fields=status"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, auth=(JIRA_USER, JIRA_API_TOKEN))
        if response.status_code == 404:
            return True  # credenciales ya verificadas: 404 = ticket eliminado
        response.raise_for_status()
        category = response.json()["fields"]["status"]["statusCategory"]["key"]
        return category == "done"
    except Exception as exc:
        logger.error("Fallo al consultar %s: %s", issue_key, exc)
        raise JiraLookupError(f"consulta {issue_key}: {exc}") from exc


async def resolve_open_key(fp: str, alert_label: str, device_label: str) -> str | None:
    """
    Ticket abierto para la huella. Primero Postgres (consistente e inmediato);
    si no hay registro, respaldo JQL para adoptar tickets creados antes de
    que existiera la tabla jira_dedup.
    Todo ticket candidato se verifica por key (statusCategory), porque la JQL
    usa 'resolution', que el workflow puede no rellenar al cerrar, y además
    depende del índice de Jira.
    """
    key = await adb(db_get_open_key, fp)
    if key:
        if not await jira_issue_closed(key):
            return key
        await adb(db_mark_closed, fp)  # alguien lo cerró a mano en Jira
        return None

    key = await find_open_jira_ticket(alert_label, device_label)
    if key and not await jira_issue_closed(key):
        await adb(db_set_open, fp, key)
        return key
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
    1. Busca el ticket abierto de la huella (alerta, dispositivo) en Postgres,
       con respaldo JQL.
    2. Si status == "resolved": comenta, trata de cerrar y marca la huella cerrada.
    3. Si existe ticket abierto: comenta "la anomalía persiste" (sin crear).
    4. Si no existe: reserva la huella de forma atómica (UNIQUE) y solo el
       proceso que la obtiene crea el ticket. Evita duplicados en paralelo.
    """
    if not all([JIRA_URL, JIRA_USER, JIRA_API_TOKEN, JIRA_PROJECT_KEY]):
        logger.error("Credenciales de Jira no configuradas; se omite la integración.")
        return {"action": "skipped", "reason": "missing_credentials"}

    # Sin equipo (DatasourceNoData), la regla de origen es la identidad.
    # Sin esto, todas las reglas sin datos comparten la misma huella y un solo ticket.
    identity = device_name
    if device_name == "desconocido":
        identity = rule_identity(payload)

    origen = device_name if device_name != "desconocido" else f"sin equipo (regla: {identity})"
    alert_label = slugify(alert_name or "sin-alerta", "al")
    device_label = slugify(identity or "sin-dispositivo", "dev")
    fp = f"{alert_label}|{device_label}"

    existing_key = await resolve_open_key(fp, alert_label, device_label)
    now_iso = datetime.now(timezone.utc).isoformat()

    if status_ == "resolved":
        if not existing_key:
            return {"action": "resolved_no_open_ticket"}

        resolved_text = (
            f"✅ Alerta RESUELTA ({now_iso}).\n"
            f"Dispositivo: {origen}\nAlerta: {alert_name}\n\n"
            f"Payload:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        commented = await add_jira_comment(existing_key, resolved_text)
        transitioned = await try_resolve_jira_ticket(existing_key)
        if transitioned:
            await adb(db_mark_closed, fp)
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
            f"Dispositivo: {origen}\nAlerta: {alert_name}\n\n"
            f"Payload actual:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        commented = await add_jira_comment(existing_key, persist_text)
        return {"action": "comment_added", "key": existing_key, "commented": commented, "created": False}

    if not await adb(db_claim, fp):
        logger.info("Creación en curso para %s por otra petición; se omite duplicado", fp)
        return {"action": "dedup_in_progress"}

    title, severity = extract_jira_fields(payload)
    result = await create_jira_ticket(title, severity, payload, [alert_label, device_label])
    if result.get("created"):
        await adb(db_set_open, fp, result["key"])
        result["action"] = "ticket_created"
    else:
        await adb(db_release, fp)  # libera la reserva para que el reintento pueda crear
        result["action"] = "jira_create_failed"
    return result


# ── PostgreSQL ───────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    global pool
    pool = ThreadedConnectionPool(
        minconn=1,
        maxconn=20,
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
    )
    logger.info("Pool de conexiones PostgreSQL inicializado (%s:%s/%s)", PG_HOST, PG_PORT, PG_DB)
    ensure_schema()


@app.on_event("shutdown")
def shutdown():
    if pool:
        pool.closeall()
    checkpointer_pool.close()


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


class DedupStoreError(Exception):
    """Postgres no respondió: no sabemos si la huella ya tiene ticket."""

async def adb(func, *args):
    """Ejecuta una función bloqueante de Postgres en un hilo, sin congelar el event loop."""
    return await run_in_threadpool(func, *args)

def db_exec(sql: str, params: tuple = (), fetch: bool = False):
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone() if fetch else None
        conn.commit()
        return row
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise DedupStoreError(str(exc)) from exc
    finally:
        if conn is not None:
            pool.putconn(conn)


def ensure_schema():
    # PRIMARY KEY = UNIQUE: dos procesos no pueden registrar la misma huella.
    db_exec("""
        CREATE TABLE IF NOT EXISTS jira_dedup (
            fingerprint TEXT PRIMARY KEY,
            issue_key   TEXT,
            state       TEXT NOT NULL CHECK (state IN ('creating', 'open', 'closed')),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    logger.info("Tabla jira_dedup verificada")


def db_get_open_key(fp: str) -> str | None:
    row = db_exec(
        "SELECT issue_key FROM jira_dedup WHERE fingerprint = %s AND state = 'open'",
        (fp,), fetch=True,
    )
    return row[0] if row else None


def db_set_open(fp: str, key: str):
    db_exec("""
        INSERT INTO jira_dedup (fingerprint, issue_key, state, updated_at)
        VALUES (%s, %s, 'open', now())
        ON CONFLICT (fingerprint) DO UPDATE
        SET issue_key = EXCLUDED.issue_key, state = 'open', updated_at = now()
    """, (fp, key))


def db_mark_closed(fp: str):
    db_exec(
        "UPDATE jira_dedup SET state = 'closed', updated_at = now() WHERE fingerprint = %s",
        (fp,),
    )


def db_claim(fp: str) -> bool:
    """
    Reserva atómica de la creación. Solo UN proceso obtiene True.
    Se puede reclamar si no existe, si estaba cerrada, o si una reserva
    quedó colgada más de 2 minutos (proceso caído a mitad de creación).
    """
    row = db_exec("""
        INSERT INTO jira_dedup (fingerprint, state) VALUES (%s, 'creating')
        ON CONFLICT (fingerprint) DO UPDATE
        SET state = 'creating', issue_key = NULL, updated_at = now()
        WHERE jira_dedup.state = 'closed'
           OR (jira_dedup.state = 'creating' AND jira_dedup.updated_at < now() - interval '2 minutes')
        RETURNING fingerprint
    """, (fp,), fetch=True)
    return row is not None


def db_release(fp: str):
    db_exec("DELETE FROM jira_dedup WHERE fingerprint = %s AND state = 'creating'", (fp,))


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/alert", dependencies=[Security(verify_token)])
async def receive_alert(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body inválido: se espera JSON UTF-8")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body inválido: se espera un objeto JSON")

    logger.info(
        "ALERT RECEIVED at %s\n%s",
        datetime.now(timezone.utc).isoformat(),
        json.dumps(payload, indent=2, ensure_ascii=False),
    )

    results = []
    all_ok = True

    for view in split_alerts(payload):
        status_, alert_name = extract_alert_fields(view)
        device_name = extract_device_name(view)

        persisted = True
        try:
            await adb(insert_incident, status_, alert_name, view)
        except Exception as exc:
            persisted = False
            logger.error("Fallo al insertar en PostgreSQL (%s): %s", alert_name, exc)

        try:
            jira_result = await handle_jira_dedup(status_, alert_name, device_name, view)
        except JiraLookupError as exc:
            logger.error("Jira no disponible para %s / %s: %s", alert_name, device_name, exc)
            jira_result = {"action": "jira_unavailable"}
        except DedupStoreError as exc:
            logger.error("Postgres no disponible para deduplicar %s / %s: %s", alert_name, device_name, exc)
            jira_result = {"action": "dedup_store_unavailable"}

        if not persisted or jira_failed(jira_result):
            all_ok = False

        results.append({
            "alert": alert_name,
            "device": device_name,
            "persisted": persisted,
            "jira": jira_result,
        })

    body = {"status": "received" if all_ok else "partial_failure",
            "total": len(results), "results": results}

    # 503 -> Grafana reintenta. Los tickets ya creados no se duplican en el reintento.
    return JSONResponse(content=body, status_code=200 if all_ok else 503)

# ── Endpoint /api/chat ───────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse, dependencies=[Security(verify_token)])
def chat(req: ChatRequest):
    """
    Invoca el grafo NOC-MAS (LangGraph) manteniendo el estado por thread_id
    vía el checkpointer (MemorySaver). El grafo puede detenerse en
    'human_in_the_loop' (interrupt_before); en ese caso se informa igual.
    """
    config = {"configurable": {"thread_id": req.thread_id}}

    try:
        result = orchestrator.invoke(
            {"messages": [HumanMessage(content=req.message)]},
            config=config,
        )
    except Exception as exc:
        logger.error("Fallo al invocar el orquestador NOC-MAS: %s", exc)
        raise HTTPException(status_code=500, detail=f"Error del orquestador: {exc}")

    # Último mensaje del historial (respuesta del agente/supervisor)
    messages = result.get("messages", [])
    last_ai_msg = next(
        (m for m in reversed(messages) if isinstance(m, AIMessage)),
        None,
    )

    if last_ai_msg is not None:
        reply_text = last_ai_msg.content
    elif result.get("requires_human_approval"):
        reasoning = result.get("context", {}).get("last_routing_reasoning", "Sin detalle.")
        reply_text = f"⏸️ Requiere aprobación humana (HITL). Motivo: {reasoning}"
    else:
        reply_text = "⚠️ El orquestador no devolvió un mensaje de respuesta."

    return ChatResponse(
        thread_id=req.thread_id,
        reply=reply_text,
        next_agent=result.get("next_agent"),
        requires_human_approval=result.get("requires_human_approval", False),
    )

@app.get("/health")
async def health():
    """Liveness: el proceso responde."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """
    Readiness: ¿puede este proceso atender alertas? Solo verifica Postgres.
    Jira NO se verifica: si Jira cae y todos los pods quedan "no listos",
    tampoco se podrían guardar las alertas en incident_logs.
    """
    try:
        db_exec("SELECT 1", fetch=True)
    except Exception as exc:
        logger.error("Readiness fallida: %s", exc)
        return JSONResponse({"status": "not_ready", "postgres": "down"}, status_code=503)
    return {"status": "ready", "postgres": "ok"}