import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage

# Cargar variables de entorno (asegúrate de tener tu GROQ_API_KEY)
load_dotenv()

# Importamos el nodo que acabas de crear
from webhook_service.src.nodes.action_agent import action_agent_node

def run_test():
    print("🚀 Iniciando prueba unitaria del Action_Agent...\n")

    # 1. Simulamos el NOCState inyectando un diagnóstico del Data_Agent
    mock_state = {
        "messages": [
            HumanMessage(content="¿Por qué falló el core-rtr-01 anoche?"),
            AIMessage(content="El diagnóstico indica que la latencia del core-rtr-01 es de 350ms, superando ampliamente el umbral crítico.")
        ],
        "context": {
            "last_sql_query": "SELECT avg(latency) FROM telemetry WHERE hostname='core-rtr-01' AND time > now() - interval '1 hour';",
            "last_sql_success": True,
            "last_sql_rows": "[{'avg_latency': 350}]"
        }
    }

    # 2. Ejecutamos el nodo de acción directamente
    result = action_agent_node(mock_state)

    print("="*70)
    print("🎯 RESULTADOS DE LA DECISIÓN OPERATIVA")
    print("="*70)

    # 3. Extraemos las variables actualizadas inyectadas al contexto
    context = result.get("context", {})
    messages = result.get("messages", [])

    print(f"--> Tipo de Acción    : {context.get('last_action_type')}")
    print(f"--> Payload Generado  : {context.get('last_action_payload')}")
    print(f"--> Éxito de Ejecución: {context.get('last_action_success')}")
    
    print("\n" + "="*70)
    print("🤖 RESUMEN DEL MENSAJE (Devuelto al Orquestador)")
    print("="*70)
    if messages:
        print(messages[0].content)

if __name__ == "__main__":
    run_test()