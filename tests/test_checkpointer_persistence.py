"""
tests/test_checkpointer_persistence.py — Test de integración: valida que el
checkpointer Postgres del NOC-MAS persiste el estado del grafo (mensajes,
next_agent, HITL) en TimescaleDB y es recuperable por el mismo thread_id
desde un proceso distinto.

Por qué se reconstruye el grafo dos veces (en vez de invocar dos veces sobre
el mismo objeto `orchestrator`): con MemorySaver, dos invocaciones sobre el
mismo objeto en el mismo proceso también "recordarían" el hilo, aunque el
estado viviera solo en RAM. Eso no probaría nada sobre Postgres. Para
demostrar que la persistencia sobrevive a un reinicio del contenedor
webhook_service, este test arma un pool de conexiones y un PostgresSaver
NUEVOS (simulando un proceso/contenedor distinto) que solo comparten la
base de datos y el thread_id con el primero.

Requiere:
    - TimescaleDB accesible (PG_DSN, o PG_HOST/PG_PORT/PG_DB/PG_USER/PG_PASSWORD)
    - GROQ_API_KEY (opcional): si falla o falta, el Supervisor cae a su
      fallback seguro (human_in_the_loop) sin romper el test — el mensaje
      humano ya quedó persistido en el checkpoint inicial de todos modos.

Uso:
    python tests/test_checkpointer_persistence.py
    pytest tests/test_checkpointer_persistence.py
"""
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

# Permite `from webhook_service.src...` (paquete raíz) Y que ese módulo
# resuelva a su vez sus propios imports absolutos `from src...` (orchestrator.py
# asume que webhook_service/ está en sys.path, como cuando corre con
# cwd=webhook_service dentro del contenedor). Sin el segundo path, importar
# webhook_service.src.orchestrator falla con "No module named 'src'".
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEBHOOK_SERVICE_DIR = os.path.join(_REPO_ROOT, "webhook_service")
for _p in (_REPO_ROOT, _WEBHOOK_SERVICE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from langchain_core.messages import HumanMessage
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver

from webhook_service.src.orchestrator import build_graph, _build_checkpointer_dsn


def _compile_fresh_orchestrator():
    """Grafo + checkpointer + pool propios, apuntando a la misma DB que el servicio real."""
    dsn = _build_checkpointer_dsn()
    pool = ConnectionPool(
        conninfo=dsn, max_size=5, kwargs={"autocommit": True, "prepare_threshold": 0}
    )
    pool.wait(timeout=15)
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    compiled = build_graph().compile(
        checkpointer=checkpointer, interrupt_before=["human_in_the_loop"]
    )
    return compiled, checkpointer, pool


def test_checkpoint_state_persists_across_process_restart():
    thread_id = f"test-persist-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    first_message = "Recuerda este número clave: 7734. No hagas nada más, solo confírmalo."
    second_message = "¿Qué número clave te pedí que recordaras?"

    # "Proceso A": primera invocación, luego se cierra su pool de conexión.
    orchestrator_a, _checkpointer_a, pool_a = _compile_fresh_orchestrator()
    try:
        orchestrator_a.invoke({"messages": [HumanMessage(content=first_message)]}, config=config)
    finally:
        pool_a.close()

    # "Proceso B": grafo, checkpointer y pool nuevos — misma DB, mismo thread_id.
    orchestrator_b, checkpointer_b, pool_b = _compile_fresh_orchestrator()
    try:
        recovered_state = orchestrator_b.get_state(config)
        recovered_messages = recovered_state.values.get("messages", [])

        assert recovered_messages, (
            f"El checkpointer Postgres no devolvió estado previo para thread_id={thread_id}; "
            "la persistencia entre procesos no está funcionando."
        )
        assert any(first_message in getattr(m, "content", "") for m in recovered_messages), (
            "El mensaje de la primera invocación no se recuperó desde Postgres."
        )

        result_b = orchestrator_b.invoke(
            {"messages": [HumanMessage(content=second_message)]}, config=config
        )
        all_messages = result_b.get("messages", [])

        assert len(all_messages) > len(recovered_messages), (
            "El historial no creció tras la segunda invocación; el estado no se está "
            "acumulando sobre la memoria persistida."
        )
        assert any(first_message in getattr(m, "content", "") for m in all_messages), (
            "El mensaje de la primera invocación se perdió tras la segunda invocación."
        )

        print(
            f"OK: thread_id={thread_id} conservó {len(recovered_messages)} mensaje(s) "
            f"tras 'reiniciar' el proceso, y acumuló hasta {len(all_messages)}."
        )
    finally:
        # No dejar basura en la base de datos compartida: cada corrida usa un
        # thread_id nuevo (uuid4), así que sin este cleanup los checkpoints de
        # prueba se acumularían indefinidamente en la DB real.
        checkpointer_b.delete_thread(thread_id)
        pool_b.close()


if __name__ == "__main__":
    test_checkpoint_state_persists_across_process_restart()
    print("PASSED: test_checkpoint_state_persists_across_process_restart")
