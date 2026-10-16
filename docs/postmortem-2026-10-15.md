# Post-mortem: Postgres inalcanzable, webhook `0/1` (falla simulada)

| Campo | Valor |
|---|---|
| Fecha | 2026-10-15 (hora Santiago, UTC-3) |
| Tipo | Simulacro de laboratorio (no es un incidente real) |
| Entorno | Clúster kind `noc-local-cluster`, namespace `dev` |
| Servicio afectado | `webhook-service` (imagen `noc-webhook-service:v1.0.12`, 1 réplica) |
| Autor | Rodrigo Codoceo |
| Marco | ITIL v4: Gestión de incidentes y Gestión de problemas |

## 1. Resumen

Se detuvo el contenedor Docker `timescaledb` para simular la caída de la base de datos. El webhook siguió con el proceso vivo, pero su `/ready` pasó a responder 503 y el pod quedó `Running 0/1` sin reiniciarse. El Service `webhook-service` quedó sin endpoints. El servicio se recuperó solo al volver a iniciar Postgres, sin rollout. Duración total: **4 min 4 s**.

## 2. Impacto

- Durante la caída, `webhook-service` no tuvo ningún pod listo. Un POST a `/alert` desde Grafana habría fallado y Grafana habría reintentado (comportamiento fail-closed diseñado).
- **No se envió tráfico de prueba durante la caída**, así que el impacto real en alertas y tickets Jira no se midió.
- Pendiente de verificar: que la tabla `jira_dedup` quedó intacta y que no hubo tickets duplicados tras la recuperación.
- Sin pérdida de configuración: no hubo cambios en el Deployment, solo se detuvo una dependencia.

## 3. Línea de tiempo (hora local)

| Hora | Evento |
|---|---|
| 20:41:35 | Se inyecta la falla: `docker stop timescaledb` |
| 20:43:39 | Se detecta: pod `0/1`, readiness fallando (2 min 4 s después) |
| 20:45:39 | Se registra la resolución: `docker start timescaledb`, pod `1/1` |

Nota: el archivo `timeline.txt` tiene una sola marca para la resolución, que mezcla la acción y la confirmación. Para el MTTR se toma 20:45:39 como momento de servicio restaurado. En próximos simulacros, registrar dos marcas separadas (acción y confirmación).

## 4. Detección

- `kubectl get pods -w`: el pod pasó de `1/1` a `0/1`, con `RESTARTS 0`.
- `kubectl get endpoints`: `webhook-service` sin ENDPOINTS.
- `kubectl describe pod`, sección Events: `Readiness probe failed: HTTP probe failed with statuscode: 503` (x10 en 82 s).
- Hoy la detección fue **manual**. Ninguna alerta de Grafana avisa de un pod `0/1`.

## 5. Causa raíz

El endpoint `/ready` consulta Postgres. Al estar detenido el contenedor `timescaledb`, `/ready` devolvió 503 y Kubernetes retiró el pod del Service. En la simulación la causa fue provocada. En un caso real, la dependencia queda **fuera del clúster** (Docker, `PG_HOST=host.docker.internal`), por lo que Kubernetes no la gestiona ni la vigila.

Hallazgo adicional: el `timescaledb-service` del clúster seguía con endpoint (`10.244.1.4:5432`) pero no sirvió de respaldo, porque el webhook no apunta a él y su esquema no está cargado.

## 6. Resolución

1. Diagnóstico con `get pods`, `get endpoints` y `describe pod` (Events).
2. `docker start timescaledb`.
3. El pod volvió a `1/1` solo, sin `rollout undo` ni reinicio.
4. Comprobación posterior: `/ready` responde `200 {"status":"ready","postgres":"ok"}` (capturado a las 20:52:20).

| Métrica | Valor |
|---|---|
| Tiempo hasta detectar (MTTD) | 2 min 4 s |
| Tiempo de detección a resolución | 2 min 0 s |
| Tiempo total de indisponibilidad (MTTR) | 4 min 4 s |

Limitación: el código 503 de `/ready` durante la falla no se capturó directamente con port-forward. La evidencia del 503 es el evento del kubelet. El 200 de la tabla es de después de la recuperación.

## 7. Qué funcionó

- La readiness probe retiró el pod del tráfico sin reiniciarlo, que es lo correcto: reiniciar no arregla una base caída.
- La liveness (`/health`) no depende de Postgres, así que no hubo reinicios en cascada (`RESTARTS 0`).
- Recuperación automática al volver la dependencia, sin intervención sobre el Deployment.
- Los Events del pod dieron la causa visible en una sola lectura.

## 8. Qué no funcionó

- Sin alerta automática: la caída se detectó porque se estaba mirando.
- Dependencia crítica fuera del clúster, sin vigilancia desde Kubernetes.
- Una sola réplica: no hay redundancia, pero tampoco ayudaría, porque todas las réplicas dependen de la misma base.
- Una sola marca de resolución en el registro de tiempos.

## 9. Acciones correctivas

Responsable y fechas son una propuesta, ajusta según tu calendario.

| # | Acción | Responsable | Fecha |
|---|---|---|---|
| 1 | Crear alerta en Grafana sobre pod no listo (`kube_pod_status_ready{condition="false"}`) o sobre `/ready` | Rodrigo | 2026-10-22 |
| 2 | Repuntar `PG_HOST` a `timescaledb-service` del clúster y cargar el esquema (fase posterior) | Rodrigo | 2026-10-29 |
| 3 | Añadir al runbook: ante `Running 0/1`, revisar Postgres antes de reiniciar el pod | Rodrigo | 2026-10-18 |
| 4 | Verificar `jira_dedup` e historial de tickets tras la recuperación | Rodrigo | 2026-10-16 |
| 5 | Registrar dos marcas (acción y confirmación) en los próximos simulacros | Rodrigo | 2026-10-16 |

## 10. Otros simulacros del día (resumen)

| Falla | Síntoma | Causa visible | Duración | Resolución |
|---|---|---|---|---|
| 1. Tag inexistente `v9.9.9` | `ImagePullBackOff` | `pull access denied` en Events (mensaje engañoso: el tag no estaba cargado en kind) | 19:08:12 a 19:51:45 (ver nota) | `rollout undo` |
| 2. `NOC_WEBHOOK_TOKEN` vacío | `CrashLoopBackOff` | `RuntimeError: Faltan variables de entorno obligatorias: NOC_WEBHOOK_TOKEN` | 20:25:44 a 20:29:34 (3 min 50 s) | `rollout undo` |

Nota falla 1: no hay marca de detección, y los Events muestran el scale-down del ReplicaSet unos minutos antes de la marca de resolución, por lo que la duración de 43 min incluye tiempo de diagnóstico y registro tardío. No usar como MTTR fiable.

Con rolling update, el pod anterior (`v1.0.12`) siguió `Ready` en las fallas 1 y 2, por lo que el impacto fue bajo.

Mejora posible (falla 2): el traceback de 40 líneas para un error de configuración podría ser un `sys.exit()` con un mensaje de una línea.

## 11. ITIL v4 (resumen)

- **Gestión de incidentes**: restaurar el servicio rápido (secciones 4 a 6).
- **Gestión de problemas**: causa raíz y acciones correctivas (secciones 5 y 9).
- **Mejora continua**: alerta, runbook y repunte de la base al clúster.
