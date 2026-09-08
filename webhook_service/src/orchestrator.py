# src/orchestrator.py
import logging
import os
import time
from typing import Literal

import re
from langchain_core.runnables import RunnableLambda

from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.exceptions import OutputParserException
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

from src.state import NOCState
from src.nodes.data_agent import data_agent_node
from src.nodes.action_agent import action_agent_node
from src.nodes.responder_agent import responder_agent_node

logger = logging.getLogger("noc_mas.orchestrator")


# --- Esquema de enrutamiento estructurado ---
class RouteResponse(BaseModel):
    """Decisión de enrutamiento del supervisor NOC-MAS."""

    next_agent: Literal["Data_Agent", "Action_Agent", "Responder_Agent", "human_in_the_loop", "END"] = Field(
        description="Siguiente nodo del grafo a ejecutar."
    )
    reasoning: str = Field(
        description="Justificación técnica breve de la decisión de enrutamiento."
    )
    requires_human_approval: str = Field(
        description=(
            "Indica si la acción requiere aprobación humana. "
            "Responde EXCLUSIVAMENTE con el string 'true' o el string 'false'."
        )
    )


parser = PydanticOutputParser(pydantic_object=RouteResponse)

# --- Prompt del sistema (estándar PTCF) ---
SUPERVISOR_SYSTEM_PROMPT = """
PERSONA:
Eres el Agente Supervisor de un sistema NOC-MAS (Network Operations Center - Multi-Agent System) en Fase 5 de producción. Actúas como un Ingeniero de Operaciones Senior con autoridad para enrutar decisiones técnicas entre agentes especialistas.

TAREA:
Analiza el historial de mensajes y el contexto de la alerta/incidente. Determina cuál es el siguiente paso lógico en el flujo de resolución, seleccionando exactamente uno de los siguientes destinos:
- "Data_Agent": cuando se requiera consultar o analizar telemetría en TimescaleDB (SQL) para diagnosticar una anomalía.
- "Action_Agent": cuando exista suficiente diagnóstico y se deba operar sobre Jira/Grafana o sugerir una remediación concreta.
- "Responder_Agent": cuando ya exista suficiente información (ej. resultado de una consulta SQL del Data_Agent) para responder directamente la pregunta del usuario en lenguaje natural, sin que se requiera crear tickets, alertas ni intervención humana.
- "human_in_the_loop": cuando la severidad sea crítica (P1), la acción sea irreversible, o exista ambigüedad que exceda tu autoridad de decisión automática.
- "END": cuando la alerta/incidente esté resuelto o la consulta del usuario haya sido respondida completamente.

CONTEXTO:
Operas dentro de un pipeline de observabilidad que integra TimescaleDB (telemetría), Grafana (visualización) y FastAPI (deduplicación de alertas hacia Jira). Cada decisión de enrutamiento debe minimizar el MTTR (Mean Time To Resolution) sin comprometer la seguridad operativa.

FORMATO:
{format_instructions}
No incluyas texto fuera del JSON. No uses markdown, ni bloques de código, ni explicaciones adicionales.
Si el último mensaje es de Action_Agent con tipo INFO_QUERY y éxito=True, enruta siempre a "Responder_Agent" para sintetizar la respuesta al usuario.
"""

supervisor_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SUPERVISOR_SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ]
).partial(format_instructions=parser.get_format_instructions())

llm = ChatGroq(
    model=os.getenv("NOC_SUPERVISOR_MODEL", "openai/gpt-oss-20b"),
    temperature=0,
    model_kwargs={"reasoning_format": "hidden"},
)

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

supervisor_chain = supervisor_prompt | llm | RunnableLambda(clean_think_tags) | parser

def _fallback_route(reason: str, state: NOCState) -> dict:
    """Fallback seguro: enruta obligatoriamente a human_in_the_loop ante fallo de parseo."""
    return {
        "next_agent": "human_in_the_loop",
        "requires_human_approval": True,
        "context": {
            **state.get("context", {}),
            "last_routing_reasoning": f"[FALLBACK] Fallo de parseo del supervisor: {reason}",
        },
    }


def supervisor_node(state: NOCState) -> dict:
    """Nodo supervisor: invoca el LLM y parsea la salida vía PydanticOutputParser."""
    try:
        response: RouteResponse = supervisor_chain.invoke({"messages": state["messages"]})
    except OutputParserException as exc:
        return _fallback_route(str(exc), state)
    except Exception as exc:  # red de seguridad ante errores de red/API no contemplados
        return _fallback_route(f"Error inesperado: {exc}", state)

    requires_approval = str(response.requires_human_approval).strip().lower() == "true"

    return {
        "next_agent": response.next_agent,
        "requires_human_approval": requires_approval,
        "context": {
            **state.get("context", {}),
            "last_routing_reasoning": response.reasoning,
        },
    }


def human_in_the_loop_node(state: NOCState) -> dict:
    """Válvula de seguridad HITL. Punto de interrupción para aprobación manual."""
    return {
        "human_decision": "pending",
    }


def route_from_supervisor(state: NOCState) -> str:
    if state.get("requires_human_approval"):
        return "human_in_the_loop"
    next_agent = state.get("next_agent")
    return next_agent if next_agent and next_agent != "END" else END


def build_graph() -> StateGraph:
    graph = StateGraph(NOCState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("human_in_the_loop", human_in_the_loop_node)
    graph.add_node("Data_Agent", data_agent_node)
    graph.add_node("Action_Agent", action_agent_node)
    graph.add_node("Responder_Agent", responder_agent_node)   # nuevo

    graph.set_entry_point("supervisor")

    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "Data_Agent": "Data_Agent",
            "Action_Agent": "Action_Agent",
            "Responder_Agent": "Responder_Agent",   # nuevo
            "human_in_the_loop": "human_in_the_loop",
            END: END,
        },
    )

    graph.add_edge("human_in_the_loop", END)
    graph.add_edge("Data_Agent", "supervisor")
    graph.add_edge("Action_Agent", "supervisor")
    graph.add_edge("Responder_Agent", END)   # nuevo: termina el grafo, no vuelve al supervisor

    return graph


def _build_checkpointer_dsn() -> str:
    """
    Construye el DSN de Postgres para el checkpointer (psycopg 3, driver
    "postgresql://" plano) leyendo directamente PG_USER, PG_PASSWORD,
    PG_HOST, PG_PORT y PG_DB del entorno. Sin PG_DSN ni defaults estáticos:
    estas variables ya vienen inyectadas (env/secretKeyRef en el Deployment
    de AKS), así que su ausencia debe fallar alto y explícito en vez de
    caer silenciosamente a un host/credencial equivocados.
    """
    user = os.environ["PG_USER"]
    password = os.environ["PG_PASSWORD"]
    host = os.environ["PG_HOST"]
    port = os.environ["PG_PORT"]
    db = os.environ["PG_DB"]
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _init_checkpointer(
    dsn: str, max_attempts: int = 5, retry_seconds: float = 3.0
) -> tuple[PostgresSaver, ConnectionPool]:
    """
    Abre el pool de conexiones hacia TimescaleDB y crea (si no existen) las
    tablas de LangGraph (checkpoints, checkpoint_writes, checkpoint_blobs).
    Reintenta con backoff fijo porque webhook_service puede arrancar antes
    de que timescaledb esté listo para aceptar conexiones (el `depends_on`
    de Compose no espera un healthcheck).
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        pool: ConnectionPool | None = None
        try:
            pool = ConnectionPool(
                conninfo=dsn,
                max_size=10,
                kwargs={"autocommit": True, "prepare_threshold": 0},
            )
            pool.wait(timeout=10)
            checkpointer = PostgresSaver(pool)
            checkpointer.setup()
            logger.info("Checkpointer Postgres listo (pool + tablas verificadas/creadas).")
            return checkpointer, pool
        except Exception as exc:
            last_exc = exc
            if pool is not None:
                pool.close()
            logger.warning(
                "Fallo al inicializar el checkpointer Postgres (intento %s/%s): %s",
                attempt, max_attempts, exc,
            )
            if attempt < max_attempts:
                time.sleep(retry_seconds)

    raise RuntimeError(
        f"No se pudo inicializar el checkpointer Postgres tras {max_attempts} intentos: {last_exc}"
    )


_CHECKPOINTER_DSN = _build_checkpointer_dsn()
checkpointer, checkpointer_pool = _init_checkpointer(_CHECKPOINTER_DSN)


def compile_orchestrator():
    graph = build_graph()
    return graph.compile(checkpointer=checkpointer, interrupt_before=["human_in_the_loop"])


orchestrator = compile_orchestrator()