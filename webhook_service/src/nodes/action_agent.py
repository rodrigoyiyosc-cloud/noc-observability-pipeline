# src/nodes/action_agent.py
import os
import re
import json
import logging
from datetime import datetime, timezone
import httpx

from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import AIMessage

from src.state import NOCState

logger = logging.getLogger("noc_mas.action_agent")

JIRA_BASE_URL = os.getenv("JIRA_URL")   # ej. https://rodrigoyiyo.atlassian.net
JIRA_EMAIL = os.getenv("JIRA_USER")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "NOC")


# --- Esquema de salida estructurada ---
class ActionResponse(BaseModel):
    """Acción operativa estructurada generada por el Action_Agent."""

    action_type: str = Field(
        description=(
            "Tipo de acción a ejecutar. Valores esperados: 'CREATE_TICKET', "
            "'SEND_ALERT', 'ACK_ALERT', 'ESCALATE', 'INFO_QUERY'. "
        )
    )
    action_payload: str = Field(
        description=(
            "Payload de la acción en formato JSON (string). Debe incluir los "
            "campos relevantes según action_type, ej. title, description, "
            "severity, hostname, assignee."
        )
    )


parser = PydanticOutputParser(pydantic_object=ActionResponse)


def clean_think_tags(ai_message) -> str:
    """
    Elimina bloques de razonamiento <think>...</think> antes del parseo Pydantic.
    Si el tag <think> quedó sin cerrar (truncado por max_tokens), descarta todo
    lo anterior a la última '{' para intentar rescatar el JSON final igualmente.
    """
    content = ai_message.content
    cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    if cleaned:
        return cleaned

    # Fallback: <think> sin cerrar. Busca el último bloque JSON plausible.
    last_brace = content.rfind("{")
    if last_brace != -1:
        return content[last_brace:].strip()

    return content.strip()


# --- Prompt del sistema ---
ACTION_AGENT_SYSTEM_PROMPT = """
PERSONA:
Eres el Action_Agent del NOC-MAS. Ejecutas remediaciones y acciones operativas
(Jira, alertas) a partir del diagnóstico ya generado por el Data_Agent.

TAREA:
Analiza el historial de mensajes y el contexto (incluye 'last_sql_query',
'last_sql_success' y 'last_sql_rows' del Data_Agent) y decide la acción
operativa concreta a estructurar.

CONTEXTO:
- CREATE_TICKET: cuando se detecte una anomalía que requiera seguimiento
  formal en Jira. El payload debe incluir: title, description, severity,
  hostname (si aplica).
- SEND_ALERT: cuando se deba notificar a un canal (ej. Slack/Grafana) sin
  crear ticket formal. El payload debe incluir: channel, message, severity.
- ACK_ALERT: cuando la alerta ya fue reconocida/resuelta. El payload debe
  incluir: alert_id o hostname, note.
- ESCALATE: cuando la severidad exceda tu autoridad operativa habitual.
- INFO_QUERY: cuando el usuario solo pregunta por el estado de algo (ticket, alerta,
  incidente) sin requerir una acción operativa. El payload debe incluir: query, note.

REGLAS:
- action_payload SIEMPRE debe ser un JSON válido serializado como string.
- No inventes datos que no estén en el historial o contexto; si falta un
  campo, indícalo como null dentro del JSON.

FORMATO:
{format_instructions}
No incluyas texto fuera del JSON. No uses markdown, ni bloques de código, ni explicaciones adicionales.
"""

action_agent_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", ACTION_AGENT_SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ]
).partial(format_instructions=parser.get_format_instructions())

action_llm = ChatGroq(
    model=os.getenv("NOC_ACTION_AGENT_MODEL", "openai/gpt-oss-20b"),
    temperature=0,
    max_tokens=1024,
    model_kwargs={"reasoning_format": "hidden"},
)

action_agent_chain = (
    action_agent_prompt | action_llm | RunnableLambda(clean_think_tags) | parser
)


def _fetch_jira_ticket(ticket_id: str) -> dict:
    """Consulta real a Jira: trae summary, status y descripción del ticket."""
    if not (JIRA_BASE_URL and JIRA_EMAIL and JIRA_API_TOKEN):
        return {"success": False, "error": "Credenciales de Jira no configuradas.", "data": None}

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket_id}"
    try:
        resp = httpx.get(
            url,
            auth=(JIRA_EMAIL, JIRA_API_TOKEN),
            headers={"Accept": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        issue = resp.json()
        fields = issue.get("fields", {})
        return {
            "success": True,
            "error": None,
            "data": {
                "key": issue.get("key"),
                "summary": fields.get("summary"),
                "status": fields.get("status", {}).get("name"),
                "priority": (fields.get("priority") or {}).get("name"),
            },
        }
    except httpx.HTTPStatusError as exc:
        return {"success": False, "error": f"Jira respondió {exc.response.status_code}", "data": None}
    except Exception as exc:
        return {"success": False, "error": str(exc), "data": None}


def _create_jira_ticket(payload_dict: dict) -> dict:
    """Crea un ticket real en Jira y devuelve su key (ej. NOC-643)."""
    if not (JIRA_BASE_URL and JIRA_EMAIL and JIRA_API_TOKEN):
        return {"success": False, "error": "Credenciales de Jira no configuradas.", "key": None}

    url = f"{JIRA_BASE_URL}/rest/api/3/issue"
    body = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": payload_dict.get("title") or "Incidente NOC",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": payload_dict.get("description") or ""}]
                }]
            },
            "issuetype": {"name": "Task"},
        }
    }
    try:
        resp = httpx.post(
            url,
            auth=(JIRA_EMAIL, JIRA_API_TOKEN),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        issue = resp.json()
        return {"success": True, "error": None, "key": issue.get("key")}
    except httpx.HTTPStatusError as exc:
        return {"success": False, "error": f"Jira respondió {exc.response.status_code}: {exc.response.text}", "key": None}
    except Exception as exc:
        return {"success": False, "error": str(exc), "key": None}


def _execute_action(action_type: str, action_payload: str) -> dict:
    """Ejecuta la acción operativa. CREATE_TICKET e INFO_QUERY llaman a Jira real."""
    try:
        payload_dict = json.loads(action_payload)
    except (json.JSONDecodeError, TypeError) as exc:
        return {
            "success": False,
            "error": f"action_payload no es JSON válido: {exc}",
            "executed_at": None,
        }

    timestamp = datetime.now(timezone.utc).isoformat()

    # ── INFO_QUERY: consulta real, no solo log ──────────────────────────
    if action_type == "INFO_QUERY":
        ticket_id = payload_dict.get("query", "").strip()
        jira_result = _fetch_jira_ticket(ticket_id)
        log_line = f"[ACTION_EXECUTED] type=INFO_QUERY ticket={ticket_id} result={jira_result} ts={timestamp}"
        logger.info(log_line)
        print(log_line)
        return {
            "success": jira_result["success"],
            "error": jira_result["error"],
            "executed_at": timestamp,
            "info_data": jira_result["data"],
            "ticket_key": None,
        }

    # ── CREATE_TICKET: creación real en Jira ─────────────────────────────
    if action_type == "CREATE_TICKET":
        jira_result = _create_jira_ticket(payload_dict)
        log_line = f"[ACTION_EXECUTED] type=CREATE_TICKET result={jira_result} ts={timestamp}"
        logger.info(log_line)
        print(log_line)
        return {
            "success": jira_result["success"],
            "error": jira_result["error"],
            "executed_at": timestamp,
            "ticket_key": jira_result["key"],
            "info_data": None,
        }

    # ── Resto de acciones (SEND_ALERT, ACK_ALERT, ESCALATE): stub ────────
    log_line = f"[ACTION_EXECUTED] type={action_type} payload={payload_dict} ts={timestamp}"
    logger.info(log_line)
    print(log_line)
    return {"success": True, "error": None, "executed_at": timestamp, "info_data": None, "ticket_key": None}


def action_agent_node(state: NOCState) -> dict:
    """Nodo Action_Agent: genera acción vía PydanticOutputParser blindado y la ejecuta."""
    action_type = None
    action_payload = None

    try:
        parsed: ActionResponse = action_agent_chain.invoke({"messages": state["messages"]})
        action_type = parsed.action_type
        action_payload = parsed.action_payload

        # Si es INFO_QUERY y el "query" no parece una key válida de Jira
        # (ej. el usuario preguntó "cuál es el número del ticket" sin dar
        # la key), usar el último ticket creado en este hilo.
        if action_type == "INFO_QUERY":
            payload_dict = json.loads(action_payload)
            query = (payload_dict.get("query") or "").strip()
            if not re.match(r"^[A-Z][A-Z0-9]+-\d+$", query):
                last_key = state.get("context", {}).get("last_ticket_key")
                if last_key:
                    payload_dict["query"] = last_key
                    action_payload = json.dumps(payload_dict)

        exec_result = _execute_action(action_type, action_payload)
    except OutputParserException as exc:
        exec_result = {"success": False, "error": f"Fallo de parseo de acción: {exc}", "executed_at": None}
    except Exception as exc:
        exec_result = {"success": False, "error": f"Error inesperado: {exc}", "executed_at": None}

    summary_message = AIMessage(
        content=(
            f"[Action_Agent] Tipo: {action_type} | Payload: {action_payload}\n"
            f"Éxito: {exec_result['success']}"
            + (f" | Error: {exec_result['error']}" if not exec_result["success"] else "")
        )
    )

    new_ticket_key = exec_result.get("ticket_key")
    persisted_ticket_key = new_ticket_key or state.get("context", {}).get("last_ticket_key")

    return {
        "messages": [summary_message],
        "context": {
            **state.get("context", {}),
            "last_action_type": action_type,
            "last_action_payload": action_payload,
            "last_action_success": exec_result["success"],
            "last_action_info_data": exec_result.get("info_data"),
            "last_ticket_key": persisted_ticket_key,
        },
        "next_agent": None,
    }