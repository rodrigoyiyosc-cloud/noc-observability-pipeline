# Cheatsheet de Linux I: procesos, señales, systemd, journald y permisos

Fecha: 2026-11-24. Entorno: Ubuntu 26.04.1 LTS en WSL2 (kernel 6.18.33.2-microsoft-standard-WSL2), systemd como PID 1. Todo lo de las tablas se ejecutó ese día; lo que no, está marcado "sin verificar". Runbook relacionado: `docs/runbook-servicio-caido.md`.

## 0. WSL y terminal

| Comando | Qué hace | Nota |
|---|---|---|
| `wsl -l -v \| tr -d '\0'` (Git Bash) | Lista las distros y su versión | `tr` quita los ceros UTF-16 que imprime `wsl.exe` |
| `wsl -d Ubuntu` | Entra a Ubuntu | La distro predeterminada era `docker-desktop`: `wsl` a secas abre esa, no Ubuntu |
| `wsl -d Ubuntu -u root` | Shell de root | Sirve para `passwd <usuario>` si se olvidó la clave de `sudo` |

Antes de pegar comandos, mirar el prompt: `MINGW64` es Git Bash (Windows) y `usuario@PC` es Linux. El 2026-11-24 un comando de Linux corrido en Git Bash dio `id -u` = 197610 y `systemctl: command not found`.

## 1. Procesos

| Comando | Qué hace | Esperado |
|---|---|---|
| `sleep 600 &` | Lanza un proceso en segundo plano | `[1] <pid>` |
| `P=$!; echo "pid=$P bash=$$"` | `$!` es el PID del último proceso de fondo; `$$` es el del shell | Dos números distintos |
| `ps -o pid,ppid,stat,etime,cmd -p "$P"` | Estado, padre y tiempo de un proceso | `PPID` = PID del shell; `STAT` `S` = durmiendo |
| `ps -p 1 -o comm=` | Qué es el PID 1 | `systemd` |

## 2. Señales

| Comando | Efecto | Esperado |
|---|---|---|
| `kill -STOP "$P"` / `kill -CONT "$P"` | Detiene / reanuda | `STAT` pasa a `T` y vuelve a `S` |
| `kill -TERM "$P"; wait "$P"; echo "exit=$?"` | Pide terminar | `exit=143` (128 + 15) |
| `kill -KILL "$P"; wait "$P"; echo "exit=$?"` | Mata sin aviso; no se puede atrapar | `exit=137` (128 + 9) |
| `kill -0 "$P"; echo "kill0=$?"` | No envía nada: pregunta si el proceso existe | `0` existe; `1` y "No such process" si no |
| `trap "echo recibi-TERM" TERM` | Un proceso puede atrapar `TERM` y seguir vivo | Imprime el mensaje y sigue en `S`; solo `KILL` lo mata |

Regla: un proceso muerto por la señal N deja código 128 + N.

## 3. systemd

| Comando | Qué hace | Esperado |
|---|---|---|
| `systemctl is-system-running; echo "exit=$?"` | Estado global | `running` (`exit=0`); `degraded` da `exit=1` |
| `systemctl is-active <svc>; echo "exit=$?"` | ¿Está activo? | `active` y `0`. No activo da `exit=3` (`inactive` o `activating`) |
| `systemctl status <svc> --no-pager` | Estado, `Main PID` y últimas líneas | `Active: active (running)` |
| `systemctl show <svc> -p ActiveState -p MainPID -p NRestarts --no-pager` | Contadores | `NRestarts` sube con cada reinicio automático |
| `sudo systemctl start\|stop\|restart <svc>` | Controla el servicio | Sin salida si va bien |
| `sudo systemctl daemon-reload` | Relee las unidades | Obligatorio tras cambiar un archivo de unidad |
| `systemd-analyze verify <unidad>; echo "exit=$?"` | Valida la unidad | Sin mensajes y `exit=0` |

Unidad mínima (`/etc/systemd/system/<nombre>.service`):

```ini
[Unit]
Description=<texto>

[Service]
User=<usuario>
ExecStart=<ruta absoluta del ejecutable>
Restart=on-failure
RestartSec=2
```

- `Restart=on-failure`: `kill -KILL` se reinicia solo en unos 2 s; `kill -TERM` no (sale con `Deactivated successfully`).
- Sin `[Install]` la unidad es `static`: no arranca sola.
- `status=203/EXEC` = systemd no pudo ejecutar el binario. El texto distingue la causa: `No such file or directory` (ruta mala) o `Permission denied` (falta `x`). Entre tanto, systemd reinicia en bucle cada 2 s.
- `reset-failed`: limpia un estado `failed`; sin verificar que hiciera falta.

## 4. journald

| Comando | Qué hace | Esperado |
|---|---|---|
| `sudo journalctl -u <svc> -n 5 --no-pager` | Últimas líneas de un servicio | Líneas con hora |
| `sudo journalctl -u <svc> --since "10 min ago" --no-pager \| grep -v "<ruido>"; echo "exit=$?"` | Quita el ruido propio del servicio | `exit=0` con líneas, `1` sin ninguna |
| `sudo journalctl -p err -b --no-pager \| tail -5` | Errores del arranque actual | En WSL salen líneas `dxg ... Ioctl failed`: ruido del adaptador gráfico (lectura propia, sin verificar) |
| `sudo journalctl --disk-usage` | Espacio en uso | `... take up 80M` |
| `ls -d /var/log/journal; echo "exit=$?"` | ¿Guarda en disco? | Existe (`exit=0`): persistente |
| `journalctl --list-boots --no-pager \| tail -3` | Arranques guardados | Hubo tres, dos del 6-oct y uno desde el 24-nov a las 17:05 |

- Reiniciar solo la distro de WSL no cambia el arranque (la VM es la misma) y deja el aviso `corrupted or uncleanly shut down, renaming and replacing`. Causa exacta sin verificar.
- `journalctl -k` mostró líneas de `systemd-journald`; por qué, sin verificar.

## 5. Permisos

| Comando | Qué hace | Esperado |
|---|---|---|
| `stat -c '%A %a %U:%G %n' <ruta>` | Modo simbólico, modo octal, dueño y nombre | `-rwxr-xr-x 755 yiyo_:yiyo_ ...` |
| `umask` | Máscara de los archivos nuevos | `0022`: archivos `644`, carpetas `755` |
| `chmod 644 <f>` / `chmod u+x <f>` | Fija el modo / añade `x` al dueño | `-rw-r--r--` y luego `-rwxr--r-- 744` |
| `./<f>` sin `x`; `echo "exit=$?"` | Ejecutar directo | `Permission denied` y `exit=126` |
| `timeout 3 bash <f>` sin `x` | Un intérprete solo necesita leer | Corre y `timeout` corta con `exit=124` |
| `chmod 600` frente a `chmod 644`, con `sudo -u nobody cat <f>` | Quién lo puede leer | 600: `Permission denied` y `exit=1`. 644: lo lee, `exit=0` |
| `sudo cp ...` | La copia queda del usuario que la crea | `latido.service.orig` quedó `root:root` |

Un `.env` va con `600`. `chmod +x` sobre un `644` da `755` con `umask 0022`.

## 6. Sin verificar o pendiente

- Permisos de carpetas (`x` para entrar), `chown`, grupos, ACL, setuid y sticky bit.
- Memoria y OOM killer, disco e inodos: simulacro del 2026-11-25 13:30.
- Red (`ip`, `ss`, `dig`, `curl`, `tcpdump`), DNS, TLS y método USE: lectura y runbook "host lento (USE)", sin bloque asignado.
- Arranque del servicio al encender, con `[Install]` y `systemctl enable`; límite de reinicios (`StartLimitBurst`).