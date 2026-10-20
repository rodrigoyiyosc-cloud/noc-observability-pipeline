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

## 7. ITIL v4 (resumen)

- **Gestión de incidentes**: `debug` es una herramienta de diagnóstico dentro del incidente.
- **Control de accesos**: el permiso se concede por incidente y se retira al cerrarlo.
- **Gestión de problemas**: lo encontrado con `debug` alimenta la causa raíz y el post-mortem.
