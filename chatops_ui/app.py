"""
ChatOps UI - NOC-MAS Frontend
Interfaz conversacional conectada al Orquestador LangGraph vía FastAPI.
"""

import uuid
from datetime import datetime

import requests
import streamlit as st

# ──────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ChatOps UI - NOC-MAS",
    page_icon="🛰️",
    layout="wide",
)

# Nombre del servicio FastAPI dentro de la red interna de Docker (noc_net).
# Debe coincidir con el "service name" del docker-compose.yml, NO con localhost.
BACKEND_URL = "http://webhook-service:8000/api/chat"
BACKEND_TIMEOUT = 30  # segundos; el grafo LangGraph puede tardar por el LLM

# ──────────────────────────────────────────────────────────────────────────
# STATE
# ──────────────────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "👋 ChatOps NOC-MAS listo. Conectado al Orquestador vía FastAPI.",
            "ts": datetime.now().strftime("%H:%M:%S"),
        }
    ]

if "thread_id" not in st.session_state:
    # thread_id estable por sesión de navegador -> mantiene memoria del grafo (MemorySaver)
    st.session_state.thread_id = str(uuid.uuid4())

# ──────────────────────────────────────────────────────────────────────────
# SIDEBAR - Estado del sistema
# ──────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🛰️ NOC-MAS Status")
    st.caption("Estado del sistema")

    st.subheader("Conectividad")
    st.markdown("🟢 **Backend FastAPI:** OK")
    st.markdown("🟢 **PostgreSQL / TimescaleDB:** OK")
    st.markdown("🟢 **Orquestador LangGraph:** Conectado")
    st.markdown("🟢 **Conexión a Jira:** OK")

    st.divider()

    st.subheader("Sesión")
    st.code(st.session_state.thread_id, language=None)
    if st.button("🔄 Nueva sesión (reset thread_id)", use_container_width=True):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()

    st.divider()

    st.subheader("Métricas rápidas")
    col1, col2 = st.columns(2)
    col1.metric("Incidentes abiertos", "3", "-1")
    col2.metric("MTTR promedio", "14m", "2m")
    col1.metric("Agentes activos", "2/4")
    col2.metric("Uptime NOC", "99.2%")

    st.divider()

    if st.button("🧹 Limpiar historial de chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# ──────────────────────────────────────────────────────────────────────────
# MAIN - Vista de chat
# ──────────────────────────────────────────────────────────────────────────
st.title("💬 ChatOps UI")
st.caption("Interfaz conversacional NOC-MAS · Conectado al Orquestador")

# Render historial
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        st.caption(msg.get("ts", ""))


def call_orchestrator(user_message: str) -> dict:
    """Llama al endpoint /api/chat del backend FastAPI."""
    payload = {
        "message": user_message,
        "thread_id": st.session_state.thread_id,
    }
    response = requests.post(BACKEND_URL, json=payload, timeout=BACKEND_TIMEOUT)
    response.raise_for_status()
    return response.json()


# Input del usuario
if prompt := st.chat_input("Escribe un comando o consulta para el NOC..."):
    # Guardar y renderizar mensaje del usuario
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
        "ts": datetime.now().strftime("%H:%M:%S"),
    })
    with st.chat_message("user"):
        st.markdown(prompt)
        st.caption(datetime.now().strftime("%H:%M:%S"))

    # Llamada al Orquestador NOC-MAS vía FastAPI
    with st.chat_message("assistant"):
        with st.spinner("Consultando al Orquestador NOC-MAS..."):
            try:
                data = call_orchestrator(prompt)
                reply_text = data.get("reply", "⚠️ Respuesta vacía del orquestador.")

                if data.get("requires_human_approval"):
                    reply_text += "\n\n🔶 **Requiere aprobación humana (HITL).**"
                if data.get("next_agent"):
                    reply_text += f"\n\n_Próximo agente sugerido: `{data['next_agent']}`_"

            except requests.exceptions.ConnectionError:
                reply_text = (
                    "❌ No se pudo conectar al backend FastAPI "
                    f"(`{BACKEND_URL}`). Verifica que el contenedor esté "
                    "en la misma red Docker (`noc_net`) y corriendo."
                )
            except requests.exceptions.Timeout:
                reply_text = "⏱️ Timeout esperando respuesta del Orquestador."
            except requests.exceptions.HTTPError as exc:
                reply_text = f"❌ Error del backend ({exc.response.status_code}): {exc.response.text}"
            except Exception as exc:
                reply_text = f"❌ Error inesperado: {exc}"

        st.markdown(reply_text)
        ts_now = datetime.now().strftime("%H:%M:%S")
        st.caption(ts_now)

    st.session_state.messages.append({
        "role": "assistant",
        "content": reply_text,
        "ts": ts_now,
    })