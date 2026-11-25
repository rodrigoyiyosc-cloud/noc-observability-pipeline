# Runbook: servicio caído en Linux (systemd)

Alcance: servicios de systemd en Ubuntu 26.04.1 LTS bajo WSL2 (kernel 6.18.33.2-microsoft-standard-WSL2). Servicio de laboratorio: `latido.service`. Comandos en Bash dentro de Ubuntu. Probado en laboratorio el 2026-11-24. Estado: ejecutado dos veces el 2026-11-24 con fallos distintos (ver sección 10); ambas con la causa conocida de antemano, no a ciegas.

## 1. Cuándo usar cada herramienta

| Situación | Herramienta |
|---|---|
| Un servicio de systemd desapareció o no responde | Este runbook |
| Un pod de Kubernetes falla | Runbook de `kubectl debug` |
| El host entero va lento | Runbook "host lento (USE)" (pendiente) |

Siempre antes: ¿existe el servicio y qué dice `systemctl`? El journal es el paso siguiente, no el primero.

## 2. El servicio de laboratorio

`~/lab-linux1/latido.sh` escribe `latido N pid=...` cada 2 s. Unidad `/etc/systemd/system/latido.service`:

```ini
[Unit]
Description=Laboratorio Linux I - latido

[Service]
User=yiyo_
ExecStart=/home/yiyo_/lab-linux1/latido.sh
Restart=on-failure
RestartSec=2
```

- `Restart=on-failure` reinicia el servicio si muere por una señal de fallo o sale con código distinto de 0.
- La unidad no tiene `[Install]`: `systemctl` la muestra como `static` y no arranca sola.

## 3. Marcas de tiempo

Anotar con `date +%T` en cada paso:

| Marca | Qué es |
|---|---|
| DETECTADO | Hora en que se ve que el servicio no está activo |
| CAUSA | Qué cambió (señal, código de salida, motivo) y el comando que lo prueba. No el síntoma |
| RESUELTO | Hora en que `is-active` vuelve a dar `active` |

## 4. Diagnóstico

Sustituir `<svc>` por el nombre del servicio.

1. ¿Está activo?
   ```bash
   date +%T
   systemctl is-active <svc>; echo "exit=$?"
   ```
   Esperado sano: `active` y `exit=0`. Si no está activo, da `exit=3`, ya sea `inactive` o `activating` (cuando systemd lo reinicia en bucle).
2. Contadores del servicio:
   ```bash
   systemctl show <svc> -p ActiveState -p MainPID -p NRestarts --no-pager
   ```
   Un `MainPID` distinto o un `NRestarts` que subió indican que hubo una caída y reinicios.
3. Historia en journald, quitando el ruido propio del servicio (en el laboratorio, los latidos):
   ```bash
   sudo journalctl -u <svc> --since "10 min ago" --no-pager | grep -v "latido [0-9]"; echo "exit=$?"
   ```
   Esperado: líneas de systemd. `exit=0` si hubo líneas y `exit=1` si el filtro dejó cero.

```
systemctl is-active <svc>
├─ active (exit=0) ........... no está caído: mirar NRestarts y el journal
└─ no activo (exit=3): inactive, o activating si se reinicia en bucle
     ├─ journal: "Deactivated successfully" .......... parada limpia: no se reinicia
     ├─ journal: "Main process exited, code=killed" .. fallo por señal: se reinicia solo
     └─ journal: "status=203/EXEC" ................... no halla el ejecutable: bucle de reinicios
```

### Qué dice el journal

| Línea del journal | Causa | Acción |
|---|---|---|
| `Main process exited, code=killed, status=9/KILL` + `Failed with result 'signal'` | Un `kill -KILL` (verificado). Un OOM killer daría el mismo código (sin verificar: se prueba en el simulacro del 2026-11-25) | `Restart=on-failure` lo levanta solo; buscar quién o qué lo mató |
| `Deactivated successfully` y `is-active` = `inactive` | Salida limpia: `TERM` o `exit 0`. `Restart=on-failure` no la cuenta como fallo | `sudo systemctl start <svc>` |
| `status=203/EXEC` + `Unable to locate executable '<ruta>': No such file or directory` | Ruta de `ExecStart` inexistente (verificado el 2026-11-24) | Corregir la unidad y recuperar (sección 5). Mientras tanto systemd reinicia cada 2 s: `NRestarts` sube y el estado es `activating` |
| `status=203/EXEC` + `Unable to locate executable '<ruta>': Permission denied` | El script existe pero perdió el permiso `x` (verificado el 2026-11-24) | `chmod +x <ruta>` y `sudo systemctl restart <svc>` |

## 5. Recuperar

Si el problema era la unidad, corregirla primero y recargar:

```bash
sudo systemctl daemon-reload
```

Luego:

```bash
sudo systemctl reset-failed <svc>; sudo systemctl start <svc>; sleep 3
date +%T
systemctl is-active <svc>; echo "exit=$?"
```

Esperado: `active` y `exit=0`. Esa hora es RESUELTO. `reset-failed` limpia un estado `failed`; en la ejecución 2 se usó por precaución y no se verificó que hiciera falta.

## 6. Códigos de salida

| Comando | Código | Significa |
|---|---|---|
| `systemctl is-active` | 0 / 3 | Activo / no activo (`inactive` o `activating`) |
| `wait` tras `kill -TERM` | 143 | 128 + 15: murió por `TERM` |
| `wait` tras `kill -KILL` | 137 | 128 + 9: murió por `KILL`, que no se puede atrapar |
| `kill -0 <pid>` | 0 / 1 | El proceso existe / "No such process" |
| `timeout 5 <cmd>` | 124 | `timeout` cortó el comando por tiempo |
| `grep -v` (o `grep`) | 0 / 1 | Hubo líneas / ninguna línea |
| `systemd-analyze verify <unidad>` | 0 | Sin mensajes: la unidad es válida |
| Estado del servicio `status=203/EXEC` | 203 | systemd no pudo ejecutar el binario (ruta o permisos) |

## 7. Pruebas del control (negativas)

El control es la política `Restart=on-failure`. Se probó que reinicia ante un fallo, que NO reinicia ante una parada limpia y qué hace ante un fallo permanente.

| Prueba | Resultado (2026-11-24) |
|---|---|
| `kill -KILL` al `MainPID` 634 | 18:37:31 muere (`status=9/KILL`). 18:37:33 `Started`. `MainPID` pasa a 2805 y `NRestarts` de 0 a 1. Recuperación en unos 2 s |
| `kill -TERM` al `MainPID` 2805 | 18:39:44 `Deactivated successfully`. Sin reinicio en 4 s. `is-active` = `inactive`, `exit=3` |
| `systemctl start` a mano | 18:40:07 `Started`. `is-active` = `active`, `exit=0` |
| `ExecStart` apuntando a un archivo inexistente | 21:28:13 cambio y `restart`. 21:28:25: estado `activating`, `exit=3`, `NRestarts=5`, `status=203/EXEC` |
| Unidad restaurada desde la copia | 21:28:40 `active`, `exit=0` |

Interpretación: la caída por señal se recupera sola, la parada limpia no, y un fallo permanente entra en un bucle de reinicios cada 2 s que no se corrige solo. Del 18:39:44 al 18:40:07 pasaron 23 s sin servicio, tiempo tomado de journald que incluye la reacción humana, así que no mide al sistema.

## 8. Plan de retorno

El laboratorio no toca datos. Antes de modificar la unidad se guardó una copia: `~/lab-linux1/latido.service.orig`. Para restaurar:

```bash
sudo cp ~/lab-linux1/latido.service.orig /etc/systemd/system/latido.service
sudo systemctl daemon-reload
```

Para dejar el laboratorio como antes de empezar:

```bash
sudo systemctl stop latido
sudo rm /etc/systemd/system/latido.service
sudo systemctl daemon-reload
```

## 9. Pendiente

- Tras el reinicio de la distro del 2026-11-24 a las 19:49, journald registró "corrupted or uncleanly shut down". `journalctl --list-boots` muestra un solo arranque desde las 17:05:34, así que no se reinició la VM de WSL. `latido` quedó `inactive` (`exit=3`): no vuelve solo, siendo `static`. Que la causa fuera el reinicio de la distro está sin verificar. Probar con `[Install]` y `systemctl enable`.
- Límite de reinicios (`StartLimitBurst`): en la prueba de `203/EXEC` el estado seguía `activating` con `NRestarts=5` a los 12 s. No se observó el paso a `failed`. Sin probar.
- Prevención: si `systemd-analyze verify` detecta una ruta de `ExecStart` inexistente antes de reiniciar. Sin probar.
- OOM killer: simulacro del 2026-11-25 13:30.

## 10. Registro de ejecuciones

| Fecha | Caso | Tiempo | Resultado | Notas |
|---|---|---|---|---|
| 2026-11-24 | `kill -KILL` al `MainPID` | Caída 18:37:31, recuperado 18:37:33 (unos 2 s, automático) | OK: `NRestarts=1`, `MainPID` 634 a 2805 | Laboratorio, no ciego |
| 2026-11-24 | `kill -TERM` al `MainPID` | Caída 18:39:44, inicio a mano 18:40:07 (23 s, incluye reacción humana) | OK: no reinició, `start` manual dejó `active` | Contraste de la política |
| 2026-11-24 | `ExecStart` con ruta inexistente (`203/EXEC`) | Cambio 21:28:13, diagnóstico 21:28:25 (12 s), recuperado 21:28:40 (27 s desde el cambio) | OK: causa en el journal, `active` y `exit=0` tras restaurar la unidad | Laboratorio, no ciego: la causa se conocía de antemano. Los tiempos incluyen la reacción humana |
| 2026-11-24 | Script sin permiso `x` (`203/EXEC`, `Permission denied`) | Diagnóstico 23:18:05; no se anotó la hora del cambio ni la de RESUELTO | OK: `active`, `exit=0`, modo 755 tras `chmod +x` | Laboratorio, no ciego. Sin tiempos de recuperación por no haber marcado la hora |

## 11. ITIL 4

- **Gestión de incidentes**: detectar, diagnosticar con el journal y recuperar el servicio.
- **Gestión de problemas**: la causa nombrada (señal, parada limpia o ruta inexistente) alimenta el post-mortem si el fallo se repite.
- **Gestión de la configuración de servicios**: la política `Restart=` queda escrita en la unidad, no en la memoria de quien opera.