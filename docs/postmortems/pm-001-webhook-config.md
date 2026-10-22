# PM-001 · Post-mortem: clave `PG_HOST` eliminada del ConfigMap del webhook

| Campo | Valor |
|---|---|
| Owner | Rodrigo Codoceo (colaboradores: ninguno) |
| Compartido con | Repositorio `noc-observability-pipeline`, carpeta `docs/postmortems/` |
| Estado | Final (acciones correctivas abiertas) |
| Fecha del incidente | 2026-10-22, 14:57:25 a 15:07:38 (hora Santiago, UTC-3) |
| Publicado | 2026-10-22 |
| Tipo | Simulacro de laboratorio, no es un incidente real |
| Entorno | Clúster kind `noc-local-cluster`, namespace `dev` |
| Relacionado | PM-002 (Postgres caído), `runbook-kubectl-debug.md` |

## Resumen ejecutivo

| | |
|---|---|
| **Impacto** | Sin interrupción del servicio. Un pod nuevo quedó en `CrashLoopBackOff` durante 7 min 50 s y se descubrió un cambio de configuración latente que nada detectaba |
| **Causa raíz** | Un cambio manual quitó la clave `PG_HOST` del ConfigMap `webhook-config` fuera del repositorio. El estado vivo divergió del repo, y no hay mecanismo que detecte esa divergencia ni valide las claves requeridas antes del despliegue |

## Resumen del problema

| Campo | Valor |
|---|---|
| Duración | 7 min 50 s (disparo a resolución). 10 min 13 s desde la inyección |
| Producto afectado | `webhook-service` (`noc-webhook-service:v1.0.12`, 1 réplica) |
| % del producto afectado | 0 % del tráfico servido. El 100 % de los pods creados por el rollout fallido (1 de 1) no arrancó |
| Impacto en usuarios | No medido: no se envió tráfico de prueba. No se esperaba pérdida, porque el pod anterior siguió `Ready` |
| Impacto económico | No aplica (laboratorio) |
| Detección | Manual: dos pods en `kubectl get pods`, y causa en `kubectl logs --previous`. Ninguna alerta avisó |
| Resolución | `kubectl apply` del ConfigMap desde el repo y `rollout restart` |

## Contexto

El webhook recibe las alertas de Grafana y crea tickets en Jira. Lee su configuración de dos fuentes con `envFrom`: el ConfigMap `webhook-config` y el Secret `webhook-secret`. Al arrancar, `_require_env` (en `main.py`) comprueba que existan las variables obligatorias y, si falta alguna, el proceso termina con un error que nombra solo la variable. El glosario al final explica los términos de Kubernetes usados aquí.

## Impacto

**Usuarios.** No medido. El pod anterior, creado antes de la inyección, siguió `Ready` y conservó el endpoint durante todo el rollout fallido.

**Riesgo latente.** Cualquier reinicio del pod sano (desalojo, caída del nodo, nuevo despliegue) habría dejado el servicio sin backend. En producción, el tiempo entre el cambio y el disparo no tiene límite: aquí fueron 2 min 23 s por ser un simulacro.

**Alertas y tickets.** No se midió el efecto sobre Grafana, Jira ni `jira_dedup`.

**Equipo.** Una persona, 10 min 13 s de intervención, sin escalamiento.

**Documento de incidente.** Marcas de tiempo originales en `docs/postmortems/evidence/pm-001-timeline.txt`.

## Causa raíz y disparador

| Elemento | Descripción |
|---|---|
| Causa raíz | El estado vivo del ConfigMap divergió del repo (clave eliminada con un cambio manual fuera del flujo de cambios). Nada lo detecta: no hay GitOps, ni alerta de drift, ni validación de claves requeridas en CI |
| Disparador | `rollout restart`, que creó un pod que lee el ConfigMap alterado |
| Qué lo ocultó | `envFrom` se resuelve al crear el contenedor, así que el pod ya en ejecución conserva los valores antiguos |

**Mecanismo, paso a paso:**

1. `kubectl patch` elimina `PG_HOST` del ConfigMap vivo. El pod en ejecución no cambia, porque ya leyó sus variables.
2. `rollout restart` crea un pod nuevo. Al arrancar, `_require_env` no encuentra `PG_HOST` y el proceso termina antes de abrir el puerto 8000.
3. Kubernetes reinicia el contenedor con esperas crecientes (`CrashLoopBackOff`). El rolling update no retira el pod anterior hasta que el nuevo esté `Ready`, así que el servicio sigue atendido.
4. `rollout undo` devuelve el Deployment a su revisión anterior, pero el ConfigMap no forma parte del Deployment: sigue sin `PG_HOST`. Los pods se ven sanos y la causa persiste.

Esto es lo que mantuvo el problema escondido: la ausencia de error visible no significaba que la configuración fuera correcta.

## Línea de tiempo y recuperación (T0 = disparo)

| Hora | T | Evento |
|---|---|---|
| 14:56:54 | T−2 min 54 s | Base verificada: 1 pod `1/1`, `PG_HOST` presente |
| 14:57:25 | T−2 min 23 s | **Inyección:** `PG_HOST` eliminado del ConfigMap |
| 14:59:37 | T−11 s | Observación: el pod sigue `1/1` (cambio latente) |
| 14:59:48 | **T0** | **Disparo:** `rollout restart` |
| ~15:01:10 | T+1 min 22 s | Primera observación según los eventos capturados (inferido, ver nota) |
| 15:02:55 | T+3 min 7 s | Marca `DETECTADO`: `CrashLoopBackOff`, causa en `logs --previous` |
| 15:04:35 | T+4 min 47 s | Causa probada: `Compare-Object` de claves repo vs clúster |
| 15:05:04 | T+5 min 16 s | Intento: `rollout undo` |
| 15:05:46 | T+5 min 58 s | Comprobado: pods `1/1` pero `PG_HOST` sigue ausente |
| 15:07:38 | T+7 min 50 s | **Resuelto:** ConfigMap restaurado desde el repo y reinicio |

Nota sobre la detección: la marca `DETECTADO` parece registrada después de la primera observación. Los eventos capturados mostraban al pod con 80 s de vida (alrededor de las 15:01:10). El valor registrado (3 min 7 s) es una cota superior, y el real estaría cerca de 1 min 20 s.

**Recuperación.**
- *Intento incorrecto (15:05:04):* `rollout undo`. El pod que quedó sirviendo era el original, con 9 min 3 s de vida, es decir, arrancó antes de la inyección. El listado se tomó unos 2 s después del undo y aún mostraba el pod fallido (`0/1 Error`, 5 reinicios): no se verificó cuándo desapareció.
- *Corrección (15:07:38):* `kubectl apply -f deploy/local/dev/webhook-config.yaml` y `rollout restart`. Pod nuevo `1/1`, según la marca (no se adjuntó la salida).

## Métricas

| Métrica | Valor |
|---|---|
| Ventana latente (inyección a disparo) | 2 min 23 s (simulada; en la práctica no tiene límite) |
| Detección (disparo a `DETECTADO`) | 3 min 7 s registrado; cerca de 1 min 20 s estimado |
| Detección a causa probada | 1 min 40 s |
| Causa probada a resolución | 3 min 3 s (incluye 42 s del `rollout undo` fallido) |
| **MTTR (disparo a resolución)** | **7 min 50 s** |
| Inyección a resolución | 10 min 13 s |

## Lecciones aprendidas

**Qué salió bien**
- La validación al arrancar falló rápido, con un mensaje de una línea al final del traceback y sin imprimir valores.
- `logs --previous --tail=5` dio la causa a la primera.
- `Compare-Object` probó la causa comparando solo nombres de claves, sin exponer valores.
- La corrección desde el repo restauró el estado esperado.

**Qué salió mal**

*La falla*
- Nada detectó el cambio manual: el clúster y el repo divergieron sin aviso.
- El cambio manual saltó la regla del plan de que todo cambio entra por PR.
- No hay validación previa al despliegue de que el ConfigMap contenga las claves que exige la aplicación.

*La recuperación*
- Nada alertó del pod fallido; la detección fue manual.
- `describe` no ayuda con `envFrom`: lista el nombre del ConfigMap, no sus claves.
- `rollout undo` dio la falsa sensación de que el problema estaba resuelto cuando la causa seguía en el ConfigMap.

**Dónde tuvimos suerte**
- El rolling update mantuvo vivo al pod anterior, por lo que el fallo no se convirtió en una caída. Con un pod sin respaldo, o tras un reinicio del nodo, el servicio habría quedado sin backend.
- El simulacro dura minutos. En la práctica, un cambio así puede pasar días sin ser notado.

## Acciones correctivas

Prioridades: **P0** previene un impacto directo a usuarios; **P1** evita este fallo o reduce su detección; **P2** mejora el proceso. Tipos: prevent, detect, mitigate. Responsable y fechas son una propuesta alineada con el plan maestro. Cada acción tiene un criterio de cierre verificable.

| ID | Tipo | Prioridad | Acción y criterio de cierre | Responsable | Fecha | Seguimiento |
|---|---|---|---|---|---|---|
| PM1-A1 | prevent | P1 | Paso de CI que compara las claves de `webhook-config.yaml` con las que exige `_require_env`. Cierre: un PR de prueba sin `PG_HOST` falla el job, y uno completo lo pasa | Rodrigo | 2026-10-30 | Issue por crear |
| PM1-A2 | prevent | P2 | Revisar quién puede hacer `patch` de ConfigMaps en `dev`. Cierre: resultado de `kubectl auth can-i patch configmaps -n dev --as=...` de cada rol operativo documentado en el runbook, y los permisos sobrantes retirados | Rodrigo | 2026-10-30 | Issue por crear |
| PM1-A3 | prevent | P2 | Generar el ConfigMap con Kustomize (`configMapGenerator`, que añade un hash al nombre). Cierre: cambiar un valor en el repo crea un ConfigMap con nombre nuevo y un rollout visible en `kubectl rollout history` | Rodrigo | 2026-11-13 | Issue por crear |
| PM1-A4 | prevent | P1 | Argo CD con `selfHeal` (Fase 2, semanas 3 y 4). Cierre: un `kubectl patch` manual a un ConfigMap se revierte o queda `OutOfSync`, y el tiempo hasta que ocurre se mide y se registra | Rodrigo | 2026-11-20 | Issue por crear |
| PM1-A5 | detect | P1 | Alerta en Grafana por pod no listo o `CrashLoopBackOff` (misma línea que PM-002). Cierre: la alerta dispara en un simulacro y su tiempo de disparo queda registrado | Rodrigo | 2026-10-30 | Issue por crear |
| PM1-A6 | mitigate | P2 | Sección "Cambios de ConfigMap" en el runbook: no usar `rollout undo`, comparar claves vivas con el repo sin imprimir valores. Cierre: sección publicada y seguida en un simulacro nuevo | Rodrigo | 2026-10-23 | Issue por crear |
| PM1-A7 | prevent | P2 | Script de apoyo `lab-marks.ps1` con las funciones `Det`, `Causa` y `Res` que calculan solas el tiempo T+ desde el disparo. Cierre: usado en el siguiente simulacro, con marcas que traen su T+ | Rodrigo | 2026-10-23 | Issue por crear |

Mientras no existan los issues, el seguimiento queda sin trazabilidad externa: crearlos y reemplazar "Issue por crear" por su número es el paso siguiente para cerrar este documento.

## Glosario

| Término | Significado |
|---|---|
| ConfigMap | Objeto de Kubernetes con configuración no secreta (aquí, `webhook-config`) |
| `envFrom` | Forma de inyectar todas las claves de un ConfigMap o Secret como variables de entorno. Se resuelve al crear el contenedor, no después |
| Rolling update | Reemplazo gradual de pods: el nuevo debe estar `Ready` antes de retirar el anterior |
| `CrashLoopBackOff` | El contenedor falla al arrancar una y otra vez, y Kubernetes espera cada vez más entre reinicios |
| `rollout undo` | Devuelve el Deployment a su revisión anterior. No afecta a ConfigMaps ni Secrets |
| `_require_env` | Función de `main.py` que valida las variables obligatorias al arrancar |
| Drift | Diferencia entre el estado vivo del clúster y lo que declara el repo |
| `selfHeal` (Argo CD) | Opción que revierte automáticamente los cambios manuales sobre recursos gestionados desde Git |
| `configMapGenerator` (Kustomize) | Genera el ConfigMap con un hash en el nombre, de modo que un cambio de contenido provoca un rollout |

## Apéndice A: evidencia (sin valores de variables)

```text
kubectl logs <pod> -n dev --previous --tail=5
  RuntimeError: Faltan variables de entorno obligatorias: PG_HOST

kubectl describe pod <pod> -n dev   (líneas relevantes)
  State: Waiting / Reason: CrashLoopBackOff
  Last State: Terminated / Reason: Error
  Ready: False

kubectl get events -n dev   (resumen)
  Startup probe failed: ... connection refused
  Back-off restarting failed container

Pods justo después del rollout undo:
  webhook-service-5d9474fdd9-...   1/1   Running   0   9m3s
  webhook-service-9495f9b9c-...    0/1   Error     5   5m16s

Claves vivas del ConfigMap tras el undo (solo nombres; PG_HOST ausente):
  JIRA_ISSUE_TYPE, JIRA_PROJECT_KEY, JIRA_RESOLVE_TRANSITION_NAME,
  JIRA_URL, PG_DB, PG_PORT, PG_USER
```

Registro completo de marcas: `docs/postmortems/evidence/pm-001-timeline.txt`.

## Apéndice B: resumen para entrevista (30 s)

"Un cambio manual quitó una variable de un ConfigMap y el servicio siguió sano porque el pod anterior ya la tenía en memoria. Al siguiente despliegue, el pod nuevo falló con `CrashLoopBackOff`. Lo diagnostiqué con `logs --previous` y comparando las claves del ConfigMap con el repo. Un `rollout undo` parecía arreglarlo, pero no toca el ConfigMap. Lo resolví reaplicando desde Git. La acción preventiva es validar las claves en CI y reconciliar con GitOps para que un cambio manual no pueda quedar latente."

## Apéndice C: lista de verificación del post-mortem

- [x] Impacto evaluado, con las salvedades de lo no medido
- [x] Causa raíz y disparador analizados con su mecanismo
- [x] Lenguaje sin culpa, orientado a fallas del sistema
- [x] Acciones con tipo, prioridad, responsable, fecha y criterio de cierre
- [x] Publicado el mismo día del incidente
- [ ] Acciones con issue de seguimiento creado
- [ ] Acciones revisadas por una segunda persona (opcional en un proyecto individual)
- [ ] Compartido en el repositorio mediante PR

## Apéndice D: ITIL 4 (resumen)

- **Gestión de incidentes:** diagnóstico y restauración (línea de tiempo y recuperación).
- **Gestión de problemas:** causa raíz y acciones correctivas.
- **Habilitación del cambio:** un cambio manual sin pipeline creó el incidente diferido (PM1-A1 a PM1-A4).
