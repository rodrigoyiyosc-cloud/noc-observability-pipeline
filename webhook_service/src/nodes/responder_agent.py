# src/nodes/responder.py
import os
import re

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import AIMessage

from src.state import NOCState


def strip_think_tags(ai_message) -> str:
    """
    Elimina bloques <think>...</think>. Si el tag quedó abierto (truncado
    por max_tokens), NUNCA expone el razonamiento crudo al usuario: retorna
    un mensaje de fallback controlado en su lugar.
    """
    content = ai_message.content

    has_open = "<think>" in content
    has_close = "</think>" in content

    if has_open and has_close:
        cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        return cleaned if cleaned else (
            "El modelo no generó una respuesta final tras su razonamiento interno."
        )

    if has_open and not has_close:
        return (
            "⚠️ No se pudo completar la respuesta: el modelo excedió el límite de "
            "tokens durante su razonamiento interno antes de formular la respuesta final. "
            "Aumenta NOC_RESPONDER_MODEL_MAX_TOKENS o reintenta la consulta."
        )

    return content.strip()


RESPONDER_SYSTEM_PROMPT = """
PERSONA:
Eres el Responder_Agent del NOC-MAS. Tu única función es traducir resultados
técnicos (filas SQL, resultados de acciones) en una respuesta clara y breve
para un operador humano, en español.

TAREA:
Usa el contexto disponible para responder la última pregunta del usuario.
- Si 'last_sql_rows' contiene datos, extrae el valor relevante y respóndelo
  directamente (ej. "La latencia máxima fue de 42.3 ms").
- Si 'last_sql_success' es False, informa el error de forma breve.
- Si no hay contexto suficiente, dilo explícitamente sin inventar datos.
- Si 'last_action_info_data' contiene datos (ticket Jira), resume el estado/summary del ticket.

CONTEXTO SQL DISPONIBLE:
last_sql_query: {last_sql_query}
last_sql_success: {last_sql_success}
last_sql_rows: {last_sql_rows}

CONTEXTO DE ACCIÓN/JIRA DISPONIBLE:
last_action_type: {last_action_type}
last_action_info_data: {last_action_info_data}

FORMATO:
Responde en texto plano, en español, sin JSON, sin markdown de código,
máximo 3 frases.
"""

responder_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", RESPONDER_SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ]
)

responder_llm = ChatGroq(
    model=os.getenv("NOC_RESPONDER_AGENT_MODEL", "openai/gpt-oss-20b"),
    temperature=0,
    max_tokens=1024,
    model_kwargs={"reasoning_format": "hidden"},
)

responder_chain = responder_prompt | responder_llm | RunnableLambda(strip_think_tags)


def responder_agent_node(state: NOCState) -> dict:
    """Nodo Responder_Agent: sintetiza el contexto técnico en una respuesta final para el usuario."""
    context = state.get("context", {})

    try:
        answer_text = responder_chain.invoke(
            {
                "messages": state["messages"],
                "last_sql_query": context.get("last_sql_query", "N/A"),
                "last_sql_success": context.get("last_sql_success", "N/A"),
                "last_sql_rows": context.get("last_sql_rows", []),
                "last_action_type": context.get("last_action_type", "N/A"),
                "last_action_info_data": context.get("last_action_info_data", None),
            }
        )
    except Exception as exc:
        answer_text = f"No pude generar la respuesta final debido a un error: {exc}"

    return {
        "messages": [AIMessage(content=answer_text)],
        "next_agent": "END",
    }