# src/nodes/data_agent.py
import os
import re

from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from src.state import NOCState

PG_DSN = os.getenv("PG_DSN", "postgresql+psycopg2://user:pass@localhost:5432/noc")
_engine = create_engine(PG_DSN, pool_pre_ping=True)

ALLOWED_TABLE = "network_telemetry"
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CREATE)\b",
    re.IGNORECASE,
)


# --- Esquema de salida estructurada ---
class SQLQuery(BaseModel):
    """Consulta SQL generada por el Data_Agent sobre network_telemetry."""

    sql_query: str = Field(
        description="Sentencia SQL SELECT completa y válida sobre la tabla network_telemetry."
    )


parser = PydanticOutputParser(pydantic_object=SQLQuery)


def clean_think_tags(ai_message) -> str:
    """Elimina bloques de razonamiento <think>...</think> antes del parseo Pydantic."""
    return re.sub(r"<think>.*?</think>", "", ai_message.content, flags=re.DOTALL).strip()


# --- Prompt del sistema ---
DATA_AGENT_SYSTEM_PROMPT = """
Eres el Data_Agent del NOC-MAS. Traduces peticiones en lenguaje natural a SQL
de solo lectura sobre la tabla 'network_telemetry' (TimescaleDB).

Columnas disponibles: ts, hostname, ip, role, region, severity, message,
cpu_pct, latency_ms, packet_loss_pct, interface, iface_status, peer_ip.

Reglas:
- Solo SELECT. Nunca DML/DDL.
- Usa siempre filtros de tiempo razonables (ej. últimas 1-24 horas) salvo
  que el usuario indique lo contrario.
- Limita resultados con LIMIT cuando no se pida agregación.

FORMATO:
{format_instructions}
No incluyas texto fuera del JSON. No uses markdown, ni bloques de código, ni explicaciones adicionales.
"""

data_agent_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", DATA_AGENT_SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ]
).partial(format_instructions=parser.get_format_instructions())

data_llm = ChatGroq(
    model=os.getenv("NOC_DATA_AGENT_MODEL", "llama3-8b-8192"),
    temperature=0,
)

data_agent_chain = data_agent_prompt | data_llm | RunnableLambda(clean_think_tags) | parser


def _validate_query(sql: str) -> str | None:
    """Retorna mensaje de error si la query es insegura o inválida. None si es válida."""
    normalized = sql.strip().rstrip(";")
    if not normalized.upper().startswith("SELECT"):
        return "Solo se permiten sentencias SELECT."
    if _FORBIDDEN.search(normalized):
        return "Sentencia contiene operaciones no permitidas (DML/DDL)."
    if ALLOWED_TABLE not in normalized.lower():
        return f"La query debe referenciar la tabla '{ALLOWED_TABLE}'."
    return None


def _execute_sql(sql: str) -> dict:
    """Ejecuta SQL de solo lectura sobre network_telemetry. Retorna filas o error."""
    error = _validate_query(sql)
    if error:
        return {"success": False, "error": error, "rows": []}

    try:
        with _engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = [dict(r._mapping) for r in result.fetchmany(200)]
        return {"success": True, "error": None, "rows": rows}
    except SQLAlchemyError as exc:
        return {"success": False, "error": str(exc), "rows": []}


def data_agent_node(state: NOCState) -> dict:
    """Nodo Data_Agent: genera SQL vía PydanticOutputParser blindado y lo ejecuta."""
    sql_generated = None

    try:
        parsed: SQLQuery = data_agent_chain.invoke({"messages": state["messages"]})
        sql_generated = parsed.sql_query
        db_result = _execute_sql(sql_generated)
    except OutputParserException as exc:
        db_result = {"success": False, "error": f"Fallo de parseo SQL: {exc}", "rows": []}
    except Exception as exc:
        db_result = {"success": False, "error": f"Error inesperado: {exc}", "rows": []}

    summary_message = AIMessage(
        content=(
            f"[Data_Agent] Query: {sql_generated}\n"
            f"Éxito: {db_result['success']} | Filas: {len(db_result['rows'])}"
            + (f" | Error: {db_result['error']}" if not db_result["success"] else "")
        )
    )

    return {
        "messages": [summary_message],
        "context": {
            **state.get("context", {}),
            "last_sql_query": sql_generated,
            "last_sql_success": db_result["success"],
            "last_sql_rows": db_result["rows"],
        },
        "next_agent": None,
    }