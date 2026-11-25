# Runbook: servicio caído en Linux (systemd)

Alcance: servicios de systemd en Ubuntu 26.04.1 LTS bajo WSL2 (kernel 6.18.33.2-microsoft-standard-WSL2). Servicio de laboratorio: `latido.service`. Comandos en Bash dentro de Ubuntu. Probado en laboratorio el 2026-11-24. Estado: ejecutado una vez como laboratorio; falta ejecutarlo siguiendo este documento ante un fallo distinto (sección 9).

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
- La unidad no tiene `[Install]`: `systemctl` la muestra como `static` y no arranca sola al encender WSL.

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
   Esperado sano: `active` y `exit=0`. `inactive` da `exit=3`.
2. Contadores del servicio:
   ```bash
   systemctl show <svc> -p ActiveState -p MainPID -p NRestarts --no-pager
   ```
   Un `MainPID` distinto o un `NRestarts` que subió indican que hubo una caída y una recuperación.
3. Historia en journald, quitando el ruido propio del servicio (en el laboratorio, los latidos):
   ```bash
   sudo journalctl -u <svc> --since "10 min ago" --no-pager | grep -v "latido [0-9]"; echo "exit=$?"
   ```
   Esperado: líneas de systemd. `exit=0` si hubo líneas y `exit=1` si el filtro dejó cero.

```
systemctl is-active <svc>
├─ active (exit=0) ........... no está caído: mirar NRestarts y el journal
└─ inactive (exit=3)
     ├─ journal: "Deactivated successfully" .......... parada limpia: no se reinicia
     └─ journal: "Main process exited, code=killed" .. fallo por señal: debería reiniciarse
```

### Qué dice el journal

| Línea del journal | Causa | Acción |
|---|---|---|
| `Main process exited, code=killed, status=9/KILL` + `Failed with result 'signal'` | Un `kill -KILL` (verificado). Un OOM killer daría el mismo código (sin verificar: se prueba en el simulacro del 2026-11-25) | `Restart=on-failure` lo levanta solo; buscar quién o qué lo mató |
| `Deactivated successfully` y `is-active` = `inactive` | Salida limpia: `TERM` o `exit 0`. `Restart=on-failure` no la cuenta como fallo | `sudo systemctl start <svc>` |
| `status=203/EXEC` | Ruta de `ExecStart` inexistente (sin verificar: se prueba en la ejecución 2) | Corregir la unidad y `daemon-reload` |

## 5. Recuperar

```bash
sudo systemctl start <svc>; sleep 3
date +%T
systemctl is-active <svc>; echo "exit=$?"
```

Esperado: `active` y `exit=0`. Esa hora es RESUELTO.

## 6. Códigos de salida

| Comando | Código | Significa |
|---|---|---|
| `systemctl is-active` | 0 / 3 | Activo / no activo (`inactive`) |
| `wait` tras `kill -TERM` | 143 | 128 + 15: murió por `TERM` |
| `wait` tras `kill -KILL` | 137 | 128 + 9: murió por `KILL`, que no se puede atrapar |
| `kill -0 <pid>` | 0 / 1 | El proceso existe / "No such process" |
| `timeout 5 <cmd>` | 124 | `timeout` cortó el comando por tiempo |
| `grep -v` (o `grep`) | 0 / 1 | Hubo líneas / ninguna línea |
| `systemd-analyze verify <unidad>` | 0 | Sin mensajes: la unidad es válida |

## 7. Pruebas del control (negativas)

El control es la política `Restart=on-failure`. Se probó que reinicia ante un fallo y que NO reinicia ante una parada limpia.

| Prueba | Resultado (2026-11-24) |
|---|---|
| `kill -KILL` al `MainPID` 634 | 18:37:31 muere (`status=9/KILL`). 18:37:33 `Started`. `MainPID` pasa a 2805 y `NRestarts` de 0 a 1. Recuperación en unos 2 s |
| `kill -TERM` al `MainPID` 2805 | 18:39:44 `Deactivated successfully`. Sin reinicio en 4 s. `is-active` = `inactive`, `exit=3` |
| `systemctl start` a mano | 18:40:07 `Started`. `is-active` = `active`, `exit=0` |

Interpretación: la caída por señal se recupera sola; la parada limpia no. Del 18:39:44 al 18:40:07 pasaron 23 s sin servicio, tiempo tomado de journald que incluye la reacción humana, así que no mide al sistema.

## 8. Plan de retorno

El laboratorio no toca datos. Para dejarlo como antes:

```bash
sudo systemctl stop latido
sudo rm /etc/systemd/system/latido.service
sudo systemctl daemon-reload
```

## 9. Pendiente

- Ejecución 2 siguiendo este documento ante un fallo distinto (ruta de `ExecStart` errónea, `203/EXEC`), para cerrar la regla "runbook ejecutado" con un caso que no fue el de escritura.
- Tras reiniciar WSL: el 2026-11-24 a las 19:49 journald registró que sus archivos estaban "corrupted or uncleanly shut down" y los reemplazó. Que `latido` no vuelva solo (es `static`) está sin verificar. Probar con `[Install]` y `systemctl enable`.
- Fallos repetidos seguidos y límite de reinicios (`StartLimitBurst`): sin probar.
- OOM killer: simulacro del 2026-11-25 13:30.

## 10. Registro de ejecuciones

| Fecha | Caso | Tiempo | Resultado | Notas |
|---|---|---|---|---|
| 2026-11-24 | `kill -KILL` al `MainPID` | Caída 18:37:31, recuperado 18:37:33 (unos 2 s, automático) | OK: `NRestarts=1`, `MainPID` 634 a 2805 | Laboratorio, no ciego |
| 2026-11-24 | `kill -TERM` al `MainPID` | Caída 18:39:44, inicio a mano 18:40:07 (23 s, incluye reacción humana) | OK: no reinició, `start` manual dejó `active` | Contraste de la política |

## 11. ITIL 4

- **Gestión de incidentes**: detectar, diagnosticar con el journal y recuperar el servicio.
- **Gestión de problemas**: la causa nombrada (señal o parada limpia) alimenta el post-mortem si el fallo se repite.
- **Gestión de la configuración de servicios**: la política `Restart=` queda escrita en la unidad, no en la memoria de quien opera.