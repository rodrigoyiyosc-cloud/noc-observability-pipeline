# Runbook: depurar el webhook con `kubectl debug`

Alcance: `webhook-service` en el namespace `dev` del clúster kind `noc-local-cluster`. Comandos en PowerShell 5.1. Probado en laboratorio el 2026-10-20.

## 1. Cuándo usar cada herramienta

| Situación | Herramienta |
|---|---|
| El pod está vivo y la imagen trae shell | `kubectl exec` |
| El pod está vivo, pero la imagen **no** trae shell ni herramientas | `kubectl debug` con contenedor efímero |
| El pod crashea o hay que conservar la evidencia | `kubectl debug --copy-to` (se depura una copia) |

Siempre antes: `get pods`, `describe pod` (Events) y `logs --previous`. `debug` es el paso siguiente, no el primero.

## 2. Variables

```powershell
$ns="dev"; $sel="app.kubernetes.io/name=webhook-receiver"; $c="webhook-receiver"
$pod = kubectl get pods -n $ns -l $sel -o jsonpath='{.items[0].metadata.name}'
```

## 3. Contenedor efímero en el pod vivo

```powershell
kubectl debug -it $pod -n $ns --image=busybox:1.36 --target=$c --profile=general -- sh
```

Dentro del contenedor (`sh`):

| Qué comprobar | Comando | Resultado sano |
|---|---|---|
| Proceso de la app | `ps` | `uvicorn main:app` como PID 1 |
| Readiness desde dentro | `wget -qO- http://localhost:8000/ready` | `{"status":"ready","postgres":"ok"}` |
| DNS del clúster | `nslookup timescaledb-service.dev.svc.cluster.local` | Resuelve una IP |
| Conectividad a Postgres | `nc -w 3 <PG_HOST> 5432 </dev/null; echo "exit=$?"` | `exit=0` |
| Nombres de variables | `tr '\0' '\n' < /proc/1/environ \| cut -d= -f1 \| sort` | Solo nombres |

Reglas:
- **Nunca imprimir valores** de variables ni de Secrets. Siempre filtrar con `cut -d= -f1`.
- El contenedor efímero **no se puede borrar**: queda en el pod hasta que este se reemplace.

## 4. Depurar una copia del pod

```powershell
kubectl debug $pod -n $ns -it --copy-to=webhook-debug --container=$c -- sh
# ... inspeccionar, y al terminar:
kubectl delete pod webhook-debug -n $ns
```

- La copia usa la misma imagen y configuración, pero con el comando cambiado a `sh`, así que la app no arranca.
- Si la imagen no trae `sh`: añade `--image=busybox:1.36 --share-processes`.
- La copia **no** recibe tráfico del Service (no figura en los endpoints). Verificar con `kubectl get endpoints webhook-service -n $ns`.
- **Siempre borrar la copia** al terminar.

## 5. Evidencia del laboratorio (2026-10-20)

| Comprobación | Postgres arriba | Postgres detenido |
|---|---|---|
| `wget .../ready` desde el contenedor efímero | 200 | 503 Service Unavailable |
| `nc` a `host.docker.internal:5432` | `exit=0` | `exit=1` |

Tiempos: ejercicio 1 en 4 min 10 s y ejercicio 2 en 3 min 6 s.

Interpretación: un `/ready` 503 junto con `nc` fallando apunta a la dependencia (Postgres), no al pod ni a la imagen.

## 6. Permisos y seguridad

`debug` permite ver procesos, variables y red del pod, por lo que es una acción privilegiada.

| Permiso | Resultado con el rol `noc-operator` |
|---|---|
| `update` sobre `pods/ephemeralcontainers` | `no` |
| `create` sobre `pods/exec` | `no` |
| `create` sobre `pods` (necesario para `--copy-to`) | `no` |

Hoy **solo un administrador** puede depurar. Es el diseño deseado.

Decisión pendiente: si el NOC necesita depurar en producción, definir un rol temporal (por ejemplo `noc-debugger`), asignado solo durante el incidente, retirado después y con registro del cambio. Antes de adoptarlo, validar sus permisos con `kubectl auth can-i` y con un `debug` real, porque no se probó en el laboratorio.

## 7. Guía de diagnóstico por síntoma

Los logs son solo una de cuatro pantallas. El estado del pod indica cuál abrir:

```
get pods  ──►  describe pod  ──►  logs  ──►  kubectl debug
(estado)       (Events, lastState,  (solo si    (probar desde
                Image, Environment)  arrancó)    dentro)
```

```
kubectl get pods
├─ 2 pods (el viejo 1/1 y uno nuevo que falla) → alguien cambió el Deployment
│    ├─ ImagePullBackOff ............ falla 1 → describe, Events
│    ├─ CrashLoopBackOff ............ falla 2 o 4 → logs --previous
│    │      ├─ última línea RuntimeError ........ falla 2
│    │      └─ logs vacíos + lastState OOMKilled  falla 4
│    └─ Running 0/1 ................. falla 5 → describe (Environment) + debug
└─ 1 pod, misma edad, 1/1 pasa a 0/1, RESTARTS 0 → dependencia caída: falla 3 (docker ps -a)
```

Comando para leer solo las líneas útiles (toma el pod más nuevo, que es el que falla cuando hay dos):

```powershell
$ns="dev"; $sel="app.kubernetes.io/name=webhook-receiver"
$pod = kubectl get pods -n $ns -l $sel --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}'
kubectl describe pod $pod -n $ns | Select-String -Pattern "Image:","State:","Reason:","Exit Code","Limits","memory:","Environment","PG_HOST","NOC_WEBHOOK","Readiness probe failed"
kubectl get events -n $ns --sort-by=.lastTimestamp | Select-Object -Last 8
```

Estado sano (comparar contra esto): imagen `v1.0.12`, `Environment: <none>`, límites `500m` y `512Mi`, requests `100m` y `256Mi`, un pod `1/1` con `RESTARTS 0`. Cualquier diferencia es la pista.

### Cómo leer los logs

- Solo sirven si el contenedor llegó a arrancar. En `ImagePullBackOff` no hay logs, y en `OOMKilled` salen vacíos.
- Con `CrashLoopBackOff`: `kubectl logs $pod -n $ns --previous --tail=5`.
- En un traceback de Python, leer la **última línea**: es el error. Las líneas anteriores son ruido.

### Las 5 fallas del simulacro

| # | Qué se ve | Dónde está la prueba | Arreglo |
|---|---|---|---|
| 1 Imagen inexistente | 2 pods, el nuevo en `ImagePullBackOff` | `describe` o `get events`: `Failed to pull image ... v9.9.9` | `rollout undo` |
| 2 Token vacío | 2 pods, el nuevo en `CrashLoopBackOff` | `logs --previous --tail=5`: línea `RuntimeError: Faltan variables de entorno obligatorias: NOC_WEBHOOK_TOKEN` | `rollout undo` |
| 3 Postgres detenido | 1 pod que pasa a `0/1`, `RESTARTS 0`, sin pod nuevo | `docker ps -a` (timescaledb `Exited`) y Events: `Readiness probe failed: 503` | `docker start timescaledb` |
| 4 Memoria 20Mi | 2 pods, el nuevo cae enseguida | `lastState` en `describe`: `OOMKilled`, exit 137 (los logs no sirven) | `rollout undo` |
| 5 `PG_HOST` erróneo | 2 pods, el nuevo `Running 0/1` | `describe`, sección `Environment`: `PG_HOST` con un valor raro; Events: readiness 503 | `rollout undo` |

Un pod borrado a mano no es una falla: el Deployment lo repone solo (6 a 7 s en el laboratorio). Se reconoce por un único pod `1/1` con edad de segundos.

### Dónde sirve `kubectl debug`

- **Fallas 1 y 4: no sirve.** En la 1 el contenedor nunca arranca, y en la 4 muere en 1 s. La herramienta es `describe`.
- **Fallas 3 y 5: es lo que las distingue.** Ambas dan `0/1` y `/ready` 503. Desde dentro del pod (sección 3), el discriminador es el `nc` al host correcto de Postgres (`host.docker.internal` en este laboratorio):

| Resultado del `nc` al puerto 5432 | Conclusión |
|---|---|
| `exit=1` | Postgres caído: falla 3 (infraestructura) |
| `exit=0` y `/ready` sigue en 503 | Postgres vive y la app apunta a otro host: falla 5 (configuración) |

Ejemplo laboral: "la base responde, pero el servicio dice que no" casi siempre es configuración. "La base no responde" es infraestructura, y cada caso va a un equipo distinto.

### Marcas de tiempo para simulacros

```powershell
function Mark($m){ "$(Get-Date -Format 'HH:mm:ss')  $m" | Tee-Object -FilePath .\timeline.txt -Append | Out-Null }
function Det($m){ Mark "DETECTADO: $m" }
function Causa($m){ Mark "CAUSA: $m | EVIDENCIA: <comando>" }
function Res($m){ Mark "RESUELTO: $m" }
```

Metas: detectar en menos de 3 min, causa en menos de 7, resuelto en menos de 10. Una marca de causa debe nombrar la **causa** (qué cambió), no el síntoma, y el comando que la prueba.

### Resultados de simulacros ciegos

| Fecha | Falla | Detección | Causa | Resuelto |
|---|---|---|---|---|
| 21-oct | Postgres detenido | 40 s | 2 min 43 s (la primera marca, a 1 min 16 s, era el síntoma) | 3 min 25 s |
| 21-oct | `NOC_WEBHOOK_TOKEN` vacío | 32 s | 2 min 24 s | 3 min 10 s |
| 21-oct | Imagen inexistente | 1 min 51 s | 3 min 45 s | 4 min 10 s |
| 22-oct | `NOC_WEBHOOK_TOKEN` vacío (causa vía `logs`) | 1 min 3 s | 2 min 50 s | 4 min 21 s |
| 22-oct | `OOMKilled` (causa vía `describe`, `Reason`) | 39 s | 1 min 53 s | 3 min 17 s |
| 22-oct | `PG_HOST` erróneo (causa vía `describe`, `Environment`) | 35 s | 2 min 3 s | 3 min 51 s |

Cobertura: las 5 fallas fueron diagnosticadas a ciegas y todas quedaron dentro de las metas (detección en menos de 3 min, causa en menos de 7, resuelto en menos de 10). Los dos simulacros del 21-oct (Postgres y token vacío) se confirmaron con `Revelar`. Para el resto no se registró la salida de `Revelar`, y la causa anotada coincide con las señales esperadas de cada falla en la tabla anterior.

Desde el 22-oct las marcas de causa nombran la causa concreta (variable, valor, motivo) y la herramienta que la probó (`logs` o `describe`). Pendientes: registrar el comando exacto en la marca, y confirmar la falla `PG_HOST` erróneo con `kubectl debug` y `nc` (`exit=0` con `/ready` en 503) como segunda prueba, porque hasta ahora se resolvió solo con `describe`.

## 8. ITIL v4 (resumen)

- **Gestión de incidentes**: `debug` es una herramienta de diagnóstico dentro del incidente.
- **Control de accesos**: el permiso se concede por incidente y se retira al cerrarlo.
- **Gestión de problemas**: lo encontrado con `debug` alimenta la causa raíz y el post-mortem.

## Pod nuevo no arranca: ¿clave faltante o Postgres inalcanzable? (2026-10-27)
El webhook exige Postgres al arrancar: `orchestrator.py` crea el checkpointer al importarse (5 intentos de 10 s) y, si falla, el proceso termina. Con Postgres caído, un pod nuevo entra en CrashLoopBackOff (no solo falla `/ready`). Durante un rollout, el pod viejo sigue sirviendo.

| `logs --previous` dice | Causa |
|---|---|
| `Faltan variables de entorno obligatorias: <NOMBRE>` | Falta una clave en el ConfigMap o Secret (PM-001) |
| `No se pudo inicializar el checkpointer Postgres tras 5 intentos` | Postgres inalcanzable o credenciales incorrectas (PM-002) |
