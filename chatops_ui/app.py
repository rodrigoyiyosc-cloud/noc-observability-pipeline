"""
ChatOps UI - NOC-MAS Frontend
Interfaz conversacional para el Orquestador LangGraph (futuro backend).
"""

import streamlit as st
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ChatOps UI - NOC-MAS",
    page_icon="🛰️",
    layout="wide",
)

# ──────────────────────────────────────────────────────────────────────────
# STATE
# ──────────────────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "👋 ChatOps NOC-MAS listo. Aún no conectado al Orquestador (modo standalone).",
            "ts": datetime.now().strftime("%H:%M:%S"),
        }
    ]

# ──────────────────────────────────────────────────────────────────────────
# SIDEBAR - Estado del sistema (dummy, reemplazar con API real)
# ──────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🛰️ NOC-MAS Status")
    st.caption("Estado del sistema (datos dummy)")

    st.subheader("Conectividad")
    st.markdown("🟢 **Backend FastAPI:** OK")
    st.markdown("🟢 **PostgreSQL / TimescaleDB:** OK")
    st.markdown("🟡 **Orquestador LangGraph:** No conectado")
    st.markdown("🟢 **Conexión a Jira:** OK")

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
st.caption("Interfaz conversacional NOC-MAS · Fase Frontend")

# Render historial
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        st.caption(msg.get("ts", ""))

# Input del usuario
if prompt := st.chat_input("Escribe un comando o consulta para el NOC..."):
    # Guardar mensaje del usuario
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
        "ts": datetime.now().strftime("%H:%M:%S"),
    })
    with st.chat_message("user"):
        st.markdown(prompt)
        st.caption(datetime.now().strftime("%H:%M:%S"))

    # ── Placeholder de respuesta (aquí irá el call al Orquestador LangGraph) ──
    respuesta_dummy = (
        f"🔧 [Modo standalone] Recibí: *\"{prompt}\"*.\n\n"
        "Aún no hay conexión al Orquestador NOC-MAS. "
        "Esta respuesta será reemplazada por la llamada real a la API."
    )
    st.session_state.messages.append({
        "role": "assistant",
        "content": respuesta_dummy,
        "ts": datetime.now().strftime("%H:%M:%S"),
    })
    with st.chat_message("assistant"):
        st.markdown(respuesta_dummy)
        st.caption(datetime.now().strftime("%H:%M:%S"))