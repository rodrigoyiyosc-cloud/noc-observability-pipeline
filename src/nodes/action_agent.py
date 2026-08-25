# src/nodes/action_agent.py
import os
import re
import json
import logging
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import AIMessage

from src.state import NOCState

logger = logging.getLogger("noc_mas.action_agent")


# --- Esquema de salida estructurada ---
class ActionResponse(BaseModel):
    """Acción operativa estructurada generada por el Action_Agent."""

    action_type: str = Field(
        description=(
            "Tipo de acción a ejecutar. Valores esperados: 'CREATE_TICKET', "
            "'SEND_ALERT', 'ACK_ALERT', 'ESCALATE'."
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
    """Elimina bloques de razonamiento <think>...</think> antes del parseo Pydantic."""
    return re.sub(r"<think>.*?</think>", "", ai_message.content, flags=re.DOTALL).strip()


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
    model=os.getenv("NOC_ACTION_AGENT_MODEL", "qwen/qwen3.6-27b"),
    temperature=0,
)

action_agent_chain = (
    action_agent_prompt | action_llm | RunnableLambda(clean_think_tags) | parser
)


def _execute_action(action_type: str, action_payload: str) -> dict:
    """
    Simula la ejecución de la acción operativa.
    Reemplazar por integración real (Jira API, webhook Slack, etc.) en fases
    posteriores. Por ahora registra en log/stdout.
    """
    try:
        payload_dict = json.loads(action_payload)
    except (json.JSONDecodeError, TypeError) as exc:
        return {
            "success": False,
            "error": f"action_payload no es JSON válido: {exc}",
            "executed_at": None,
        }

    timestamp = datetime.now(timezone.utc).isoformat()
    log_line = f"[ACTION_EXECUTED] type={action_type} payload={payload_dict} ts={timestamp}"

    logger.info(log_line)
    print(log_line)

    return {"success": True, "error": None, "executed_at": timestamp}


def action_agent_node(state: NOCState) -> dict:
    """Nodo Action_Agent: genera acción vía PydanticOutputParser blindado y la ejecuta."""
    action_type = None
    action_payload = None

    try:
        parsed: ActionResponse = action_agent_chain.invoke({"messages": state["messages"]})
        action_type = parsed.action_type
        action_payload = parsed.action_payload
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

    return {
        "messages": [summary_message],
        "context": {
            **state.get("context", {}),
            "last_action_type": action_type,
            "last_action_payload": action_payload,
            "last_action_success": exec_result["success"],
        },
        "next_agent": None,
    }