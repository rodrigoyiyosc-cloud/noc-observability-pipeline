# src/orchestrator.py
import os
from typing import Literal

import re
from langchain_core.runnables import RunnableLambda

from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.exceptions import OutputParserException
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.state import NOCState
from src.nodes.data_agent import data_agent_node
from src.nodes.action_agent import action_agent_node


# --- Esquema de enrutamiento estructurado ---
class RouteResponse(BaseModel):
    """Decisión de enrutamiento del supervisor NOC-MAS."""

    next_agent: Literal["Data_Agent", "Action_Agent", "human_in_the_loop", "END"] = Field(
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
- "human_in_the_loop": cuando la severidad sea crítica (P1), la acción sea irreversible, o exista ambigüedad que exceda tu autoridad de decisión automática.
- "END": cuando la alerta/incidente esté resuelto o la consulta del usuario haya sido respondida completamente.

CONTEXTO:
Operas dentro de un pipeline de observabilidad que integra TimescaleDB (telemetría), Grafana (visualización) y FastAPI (deduplicación de alertas hacia Jira). Cada decisión de enrutamiento debe minimizar el MTTR (Mean Time To Resolution) sin comprometer la seguridad operativa.

FORMATO:
{format_instructions}
No incluyas texto fuera del JSON. No uses markdown, ni bloques de código, ni explicaciones adicionales.
"""

supervisor_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SUPERVISOR_SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ]
).partial(format_instructions=parser.get_format_instructions())

llm = ChatGroq(
    model=os.getenv("NOC_SUPERVISOR_MODEL", "llama3-8b-8192"),
    temperature=0,
)

def clean_think_tags(ai_message) -> str:
    """Elimina bloques de razonamiento <think>...</think> antes del parseo Pydantic."""
    return re.sub(r"<think>.*?</think>", "", ai_message.content, flags=re.DOTALL).strip()

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

    graph.set_entry_point("supervisor")

    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "Data_Agent": "Data_Agent",
            "Action_Agent": "Action_Agent",   # <- antes: END
            "human_in_the_loop": "human_in_the_loop",
            END: END,
        },
    )

    graph.add_edge("human_in_the_loop", END)
    graph.add_edge("Data_Agent", "supervisor")
    graph.add_edge("Action_Agent", "supervisor")

    return graph


def compile_orchestrator():
    graph = build_graph()
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer, interrupt_before=["human_in_the_loop"])


orchestrator = compile_orchestrator()