# Excepciones de seguridad

| ID | Fecha | Qué | Motivo | Vence | Cierre |
|---|---|---|---|---|---|
| SEC-001 | 2026-10-27 | 11 hallazgos HIGH/CRITICAL de Trivy en dependencias Python de `webhook_service` (langchain-core 0.3.15, langgraph-checkpoint 2.1.2, langgraph-sdk 0.1.74, langsmith 0.1.147, starlette 0.37.2) | Corregirlos exige pasar la pila LangChain/LangGraph a 1.x y subir FastAPI. Es un cambio mayor que requiere prueba de punta a punta con el simulador | 2026-11-13 | PR de actualización de dependencias; el job `image-scan` pasa sin `.trivyignore.yaml` |

Alcance (pendiente de analizar): para cada CVE, ¿se usa la función afectada? Ejemplos para empezar: deserialización en el `PostgresSaver` (langgraph-checkpoint), carga de formularios multipart (starlette).

## SEC-002: credencial por defecto de Grafana (Docker) expuesta en repo público
- Detectado: 2026-10-30, gitleaks (regla curl-auth-user, README.md, 3 commits de agosto).
- Hecho: la clave `admin` del README era la real de la Grafana de Docker. Puerto 3000 publicado en todas las interfaces.
- Causa (lo que cambió): la clave inicial nunca se cambió y estaba escrita directo en docker-compose.yml.
- Resuelto 2026-10-30: clave rotada, movida a .env (GF_ADMIN_PASSWORD) y README con placeholder.
- No verificado: accesos anteriores al 28-oct (el log se perdió al recrear el contenedor) y si el puerto era alcanzable fuera de la red local.
- Pendiente: acotar 3000, 5432 y 8000 a 127.0.0.1; clave de 8 caracteres a reemplazar por una larga.
- El valor viejo sigue en el historial git, pero ya no es válido. No se reescribe el historial.

### SEC-002: actualización 2026-10-30 (puertos)
- Cerrado: puertos de Compose (3000, 5432, 8000, 8501, 8888) publicados solo en 127.0.0.1.
- Verificado: `docker compose config` con 5 host_ip 127.0.0.1; el clúster sigue llegando a Postgres (host.docker.internal:5432); por la IP de red los puertos no responden.
- No verificado: si antes eran alcanzables desde fuera de la red local (depende de firewall y router, no revisados).
- Pendiente: reemplazar la clave de Grafana de 8 caracteres por una larga.
