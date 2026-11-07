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

### SEC-002: cierre 2026-11-02
- Clave de la Grafana Docker reemplazada por una de 24 caracteres (antes 8), cambiada por la interfaz web, y registrada en GF_ADMIN_PASSWORD de .env.
- Verificado: login con la clave nueva, 401 con admin:admin, Save & test del datasource OK y largo del .env igual al que resuelve docker compose config.
- No verificado: que la clave sobreviva a recrear el contenedor sin el volumen (el volumen de Grafana persiste, no se probó).

## SEC-003: un workflow puede aprobar PR (2026-11-04, revisión 2026-12-04)
- Se activó "Allow GitHub Actions to create and approve pull requests" para la promoción por PR (ADR-002).
- Hoy no pesa, porque el ruleset de `main` exige 0 aprobaciones. Si se sube a 1 o más, un workflow con `pull-requests: write` podría aprobar su propio PR.
- Mitigación: permisos mínimos por job, ningún workflow llama a `gh pr review --approve`, y revisar esta excepción antes de subir las aprobaciones requeridas.

### SEC-001: cierre 2026-11-06
- Pila actualizada: langchain-core 1.7.6, langgraph 1.2.20, langgraph-checkpoint 4.3.1, langgraph-sdk 0.4.14, langsmith 0.14.17, starlette 1.10.0 (FastAPI 0.162.0), langchain-groq 1.1.3 y langgraph-checkpoint-postgres 3.2.0.
- Cambio de código: `reasoning_format="hidden"` pasa a ser un parámetro explícito de ChatGroq (4 archivos), porque la versión nueva rechaza que vaya dentro de `model_kwargs`.
- Verificado: 12 tests unitarios, Trivy sin excepciones, arranque de la imagen, chat del NOC-MAS con memoria (también tras reiniciar) y simulador de incidentes de punta a punta.
- `.trivyignore.yaml` queda sin entradas.
- Deuda: las dependencias transitivas no están fijadas (pip resuelve la última al construir); evaluar un archivo de restricciones.
- También se actualizó `zlib1g` de la base Debian (2 HIGH que Trivy empezó a reportar el 2026-11-07).
- Deuda: los CVE de la base Debian aparecen cuando Trivy actualiza su base y pueden bloquear PR sin relación. Evaluar `apt-get upgrade` completo o una reconstrucción programada de la imagen.