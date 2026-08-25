from dotenv import load_dotenv; load_dotenv()
from langchain_core.messages import HumanMessage
from webhook_service.src.orchestrator import orchestrator

config = {"configurable": {"thread_id": "test-1"}}
query = "Muéstrame el CPU máximo de core-rtr-01 en la última hora"

print(f"Iniciando el NOC-MAS...\nConsultando: '{query}'\n(Esto puede tomar unos segundos...)")

result = orchestrator.invoke(
    {"messages": [HumanMessage(content=query)]},
    config=config,
)

print("\n" + "="*70)
print("📊 HISTORIAL DE MENSAJES Y DATOS OBTENIDOS")
print("="*70)

# Iteramos sobre TODOS los mensajes para ver el SQL y los datos reales
for msg in result.get("messages", []):
    rol = msg.__class__.__name__
    
    if "Human" in rol:
        print(f"👤 USUARIO NOC:\n{msg.content}\n")
    else:
        # Aquí es donde se imprimirá la respuesta cruda del Data_Agent
        print(f"🤖 {rol} (Agente/Base de Datos):\n{msg.content}\n")
    print("-" * 70)

print("\n" + "="*70)
print("🧠 DECISIÓN FINAL DEL ORQUESTADOR")
print("="*70)

# Imprimimos el estado final de enrutamiento
print(f"--> Destino asignado   : {result.get('next_agent')}")
print(f"--> Justificación      : {result.get('context', {}).get('last_routing_reasoning')}")
print(f"--> Requiere HITL      : {result.get('requires_human_approval')}")