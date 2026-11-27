# Runbook: host lento (método USE)

| Campo | Valor |
|---|---|
| Alcance | Un host Linux que "va lento": decidir qué recurso (CPU, memoria, disco, red) está usado, saturado o con errores. Probado el 2026-11-26 en Ubuntu 26.04.1 LTS bajo WSL2 (kernel 6.18.33.2, 24 CPU, 7807 MB de RAM, 2048 MB de swap), con el clúster kind y 2 contenedores más levantados. **No probado en un servidor físico ni en la nube** |
| Origen | Plan v2 §2.1 (Linux III, jueves 26-nov). Lectura hecha: SYSPER 2 §2.5.9–2.5.10, SYSPER A, SYSPER 1 §1.10.1, SYSPER 10 §10.5.2 y §10.6.1–10.6.2 |
| Última ejecución | 2026-11-26: CPU (U y S), memoria (U, S y OOM de cgroup), disco (U), red por loopback (U, S y E). **`eth0` sin carga** |
| Shell | Ubuntu en WSL2 (prompt `usuario@PC`). Un comando de Linux en Git Bash (`MINGW64`) da datos de Windows |
| Regla de oro | Mirar U, S y E de **cada** recurso. Un recurso saturado puede dejar la CPU ociosa (memoria con swap, sección 4) |
| Herramientas | `sysstat` (`mpstat`, `iostat`, `pidstat`, `sar`), instalado con `apt` el 2026-11-26 |

## 1. El método: tres preguntas por recurso

- **U** (utilización): ¿qué porcentaje del tiempo está ocupado?
- **S** (saturación): ¿hay trabajo esperando turno?
- **E** (errores): ¿el kernel o el dispositivo reportan fallas?

| Recurso | U | S | E |
|---|---|---|---|
| CPU | `mpstat 1 5` (`%usr`+`%nice`+`%sys`, `%idle`) | `vmstat 1 5` (`r` mayor que `nproc`), `/proc/pressure/cpu`, `pidstat` (`%wait`) | `journalctl -k \| grep -i -E 'mce\|thermal\|lockup\|hung'` |
| Memoria | `free -m` (`available`), `sar -r`, `pidstat -r` | `vmstat` (`si`/`so`), `pidstat -r` (`majflt/s`), `/proc/pressure/memory` | `journalctl -k \| grep -i -E 'out of memory\|oom\|killed process'` |
| Disco | `iostat -x -d <dev> 1 5` (`%util`) | `aqu-sz`, `w_await`/`r_await`, `/proc/pressure/io` | `journalctl -k \| grep -i -E 'i/o error\|blk_update_request\|ext4.*error'` |
| Red | `sar -n DEV 1 5` | `nstat -az TcpExtListenOverflows TcpExtListenDrops TcpRetransSegs` (diferencia antes/después), `ss -ltn` (`Send-Q` = cola de escucha) | `ip -s link` (`errors`, `dropped`), `journalctl -k \| grep -i -E 'nf_conntrack: table full\|link is down\|tx timeout'` |

Esperado: todos los comandos de lectura devuelven `exit=0`, salvo `grep` (`1` = sin coincidencias, que aquí es lo bueno). `diff` devuelve `1` cuando hay diferencias (aquí es lo que se busca en `nstat`). La fila de red se probó solo por loopback (sección 6).

## 2. Línea base (host en reposo)

| Dato | Valor | Cuándo |
|---|---|---|
| Núcleos | 24 (`nproc`) | 12:16 |
| Memoria | 7807 MB total; `available` 5052 MB (sin clúster) y 4796 MB (con clúster) | 12:16 y 18:02 |
| CPU en reposo | `%idle` 98.53 con 5 contenedores arriba | 14:07 |
| PSI | cpu, memoria e io en 0 o casi 0 | 12:16 y 18:02 |
| Red `eth0` | `errors` y `dropped` en 0 (contadores desde el arranque); `speed` 10000 (NIC virtual) | 12:40 y antes del ejercicio 7 |
| Contadores TCP | `TcpRetransSegs`, `TcpExtListenOverflows` y `TcpExtListenDrops` en 0 | antes del ejercicio 7 |

Notas para leer una alerta sin falsos positivos:

- `free` bajo (84 MB) es normal: el resto es caché que el kernel libera. Mirar `available`.
- `/mnt/wsl/docker-desktop/cli-tools` sale al 100 % en `df`: es una imagen de solo lectura. Excluirla de alertas de disco lleno.
- La carga de 1 min fue 5.45 con 7 min de arranque y no era saturación. Comparar siempre con `nproc` y con `r`.

## 3. CPU

Evidencia (2026-11-26):

| Ejercicio | Comando | Salida relevante | Qué dice |
|---|---|---|---|
| 1: 4 procesos (`nice 19`) | `mpstat 1 5` | `%nice` 16.13, `%usr` 0.27, `%idle` 81.40 | U de 4 núcleos de 24 (4/24 = 16.67 %) |
| 1 | `pidstat 1 3` | 4 `sha256sum` a ~100 % `%CPU`, `%wait` 0.00 | Cada uno corre sin esperar: U sin S |
| 2: 48 procesos | `vmstat 1 5` | `r` 47-48, `us` 95-96, `sy` 4-5, `id` 0 | `r` es el doble de núcleos: S |
| 2 | `cat /proc/pressure/cpu` | `some avg10=42.70`, `full` 0.00 | Hay espera de CPU |
| 2 | `uptime` | carga 8.26 2.30 1.25 | La carga llega tarde frente a `r` (48) |
| 2 | `pidstat -C sha256sum 1 3` | `%wait` 27.72–49.83 en 4 de 48 procesos | `%usr`+`%system`+`%wait` suma ~99.5 %: o corre o espera |
| 2 | `journalctl -k \| grep ...` | `grep=1` | Sin errores de CPU en la ventana de 1 hora |

Cosas que confunden:

- La carga con `nice` cuenta en `%nice`, no en `%usr`. `vmstat` no tiene columna `nice` y la suma en `us`.
- `%guest` y `%gnice` no aplican en WSL2 (son para VM invitadas de este kernel). `%steal` sí vale mirarlo: hoy 0.00.
- El PSI global de CPU sube con 48 procesos, pero `full` se queda en 0.00.
- `%soft` pasó de 0.32 (reposo) a 1.60 con la carga. **Causa sin explicar.**

Resolución del caso de laboratorio: los procesos terminan solos por `timeout`. En un caso real: nombrar con `pidstat` quién consume, y recién entonces decidir (limitar, reiniciar, escalar).

## 4. Memoria

Evidencia (2026-11-26):

| Ejercicio | Comando | Salida relevante | Qué dice |
|---|---|---|---|
| 3: 1500 MB, modo `hold` | `sar -r 1 3` | `kbavail` 4357156 → 4007924 kB en 2 s | `available` baja mientras el proceso toca páginas |
| 3 | `pidstat -r -C python3 1 2` | `RSS` 1056344 → 1238936 kB, `majflt/s` 0.00, `minflt/s` ~45000 | Páginas nuevas, nada leído desde swap |
| 3 | `vmstat 1 3` | `free` ~84 MB fijo, `cache` 3423840 → 3148672 kB | El kernel da RAM sacándola de la caché |
| 3 | `/proc/pressure/memory` | `some avg10=1.01`, `full avg10=1.01` | Presión leve (yo esperaba 0) |
| 4: 600 MB con `MemoryHigh=300M`, modo `churn` | `vmstat 1 6` | `si` 151536–160300 y `so` 151136–160096 kB/s, `b`=1, `us` 0–1, `id` 93–94, `wa` 3 | S: ~150 MB/s de swap con la CPU ociosa |
| 4 | `pidstat -r -C python3 1 3` | `majflt/s` 7737–9891 (promedio 8488), `RSS` ~309 MB, `VSZ` 630468 kB | Cada falta mayor es una lectura de swap. `RSS` queda en el tope, no en lo pedido |
| 4 | `/proc/pressure/memory` y `/proc/meminfo` | `some avg10=0.81`; `SwapFree` 2096096 → 1564260 kB | El PSI global sube poco para ese thrash |
| 5: 600 MB con `MemoryMax=300M`, sin swap | `systemctl --user status lab-oom` | `failed (Result: oom-kill)`, `Mem peak: 300M`, `exit=3` | El control mató solo a la unidad |
| 5 | `journalctl -k \| grep ...` | `oom-kill:constraint=CONSTRAINT_MEMCG`, `Memory cgroup out of memory: Killed process ... (python3)`, `grep=0` | E: el OOM es de cgroup, no global |
| 5 | `docker ps` y `free -m` | 5 contenedores `Up 4 hours`, `available` 4751 MB | Daño acotado |

Cosas que confunden:

- **Overcommit:** `vm.overcommit_memory` es 1 (siempre aceptar). `Committed_AS` 13.07 GB supera el `CommitLimit` de 6.09 GB sin consecuencias. Aquí la falta de RAM no da errores de asignación: da OOM kills.
- **PID:** `systemd` mostró el PID 2858 y el log del kernel el 24566. Hipótesis, sin verificar: WSL2 corre la distro en otro espacio de PIDs. Buscar por nombre de unidad (`lab-oom.service`), no por PID.
- **Swap usado:** 532 MB, más que los ~300 MB esperados. **Sin explicar.**
- El PSI global puede subestimar la saturación de un solo servicio en un host con muchos núcleos ociosos (hipótesis, sin verificar). El PSI del cgroup no se midió.

Resolución del caso de laboratorio: `systemctl --user reset-failed lab-oom.service`. En un caso real: leer el log del kernel por nombre de unidad, decidir si el límite era demasiado bajo o si hay una fuga.

## 5. Disco (rendimiento)

El caso de disco **lleno** está en `docs/runbook-disco-lleno.md` y el de inodos en `docs/runbook-inodos-agotados.md`. Aquí solo rendimiento.

Evidencia (2026-11-26, `sdf` = `/`): escritura directa de 512 MB en bucle sobre el mismo archivo, 30 s.

| Comando | Salida relevante | Qué dice |
|---|---|---|
| `iostat -x -d sdf 1 5` | `w/s` 6356–8308, `wkB/s` 4.59–5.20 millones, `w_await` 0.12–0.13 ms, `aqu-sz` 0.76–1.06, `%util` 50.8–62.4 | U moderada; **sin saturación** (cola de ~1, latencia mínima) |
| `/proc/pressure/io` | `some avg10=2.86` | Espera de I/O baja |
| `pidstat -d 1 3` | `sh` 4.2–4.7 millones de kB/s; cada `dd` con un PID nuevo y cifras parciales | Los `dd` duran ~0.1 s, menos que el intervalo; la causa se lee en el `sh` que los lanza |
| `journalctl -k \| grep ...` | `grep=1` | Sin errores de disco |

Cosas que confunden:

- 4.6–5.2 GB/s no es la velocidad de un SSD. Hipótesis, sin verificar: el disco virtual de WSL2 está respaldado por la caché de Windows. Las cifras de `iostat` sirven para comparar entre sí, no como capacidad del disco.
- La primera tabla de `iostat` es el promedio desde el arranque, no la medición en vivo.
- **La saturación de disco no se reprodujo.** Para verla haría falta más de un escritor en paralelo (sección 9).

## 6. Red

Evidencia (2026-11-26), solo por **loopback**: servidor `python3 -m http.server 8000 --bind 127.0.0.1` y clientes `curl`. `eth0` no recibió carga (0.00 en todas las muestras de `sar`).

| Ejercicio | Comando | Salida relevante | Qué dice |
|---|---|---|---|
| 7: descarga limitada a 50 MB/s (`curl --limit-rate 50M`), 15 s | `sar -n DEV 1 5` | `lo` `rxkB/s` = `txkB/s`, promedio 52600.77 (muestras 47685–58257); objetivo 51200 | La herramienta mide lo inyectado (+2.7 %). `%ifutil` 0.00 porque `lo` no tiene velocidad |
| 8: 300 conexiones a la vez contra una cola de escucha de 5 | `nstat -az ...` antes y después (`diff=1`) | `TcpExtListenOverflows` 0 → 154, `TcpExtListenDrops` 0 → 154, `TcpRetransSegs` 33 → 171 | S: la cola de escucha se desbordó y el kernel descartó conexiones |
| 8 | `curl -w '%{time_total}'`, los 5 peores | 2.0495–2.0601 s, agrupados | Esperas del orden de 2 s |
| 8 | `ss -ltn 'sport = :8000'` | `LISTEN 0 5 127.0.0.1:8000` | CAUSA: `Send-Q` 5 es el tamaño de la cola de escucha |
| 9: errores | `ip -s link show lo` y `eth0` | `errors` y `dropped` en 0 en ambos | Los 154 descartes no aparecen en la interfaz |
| 9 | `journalctl -k \| grep -i -E 'nf_conntrack: table full\|link is down\|tx timeout'` | `grep=1` | Sin errores de red en el kernel (ventana de 30 min) |

Cosas que confunden:

- Los descartes de la cola de escucha **no se ven en `ip -s link`** (queda en 0): son un contador TCP. Para saturación de un servicio mirar `nstat` y `ss -ltn`.
- `nstat` es global del host. `TcpRetransSegs` ya marcaba 33 antes del ejercicio 8 (era 0 en la línea base), de otro tráfico sin identificar. El delta de 138 es el número a citar, con cautela.
- Mi estimación de ~1 s para el peor tiempo era corta: salió ~2.05 s. Causa sin verificar (hipótesis: reintentos con el temporizador de 1 s).
- `tail -n 5` muestra solo los 5 peores: no se sabe cuántas de las 300 esperaron. Tampoco se capturaron los códigos de salida de `curl`, así que no se sabe si alguna falló.
- Esto prueba la pila TCP del kernel, no la capacidad de una tarjeta de red.

Resolución del caso de laboratorio: no se cambió el servidor. En un caso real: leer `Send-Q`, subir la cola (`listen backlog`) en la aplicación o poner un proxy delante. Sin probar.

## 7. Pruebas negativas y controles

| Prueba | Resultado | Qué prueba |
|---|---|---|
| `python3 memhog.py` sin argumentos | mensaje `uso: ...` y `exit=1` | El script valida sus argumentos |
| Límite de cgroup antes del OOM: leer `memory.max` dentro de `systemd-run --user --scope -p MemoryMax=300M` | `314572800` | El límite se aplica de verdad |
| OOM con `MemoryMax=300M` y sin swap | solo murió `lab-oom.service`; 5 contenedores `Up 4 hours` | El control acota el daño |
| `pgrep -c sha256sum` al terminar la carga | `0` con `exit=1` | Sin procesos residuales (`1` = sin coincidencias) |
| `timeout 30 sh -c '...'` | `exit=124` | `timeout` cortó por tiempo, como se quería |
| `journalctl -k \| grep errores` | `grep=1` | Sin errores en las ventanas medidas (CPU: solo la del ejercicio 2) |
| `timeout 15 sh -c '...curl...'` | `Exit 124` | `timeout` cortó la descarga a los 15 s, como se quería |
| `curl` al puerto 8000 con el servidor detenido | `exit=7` | El cliente detecta un servidor ausente (7 = no pudo conectar) |
| `ss -ltn \| grep ':8000'` antes de levantar el servidor | `grep=1` | El puerto estaba libre |

## 8. Tiempos medidos

| Ejercicio | INYECTADO | DETECTADO | CAUSA | RESUELTO |
|---|---|---|---|---|
| 1 (CPU, U) | 14:10:00 | 14:10:18 (18 s) | 14:10:21 (+3 s) | 14:10:40 (calculado) |
| 2 (CPU, S) | 17:47:38 | 17:47:47 (9 s) | 17:47:50 (+3 s) | 17:48:18 (calculado) |
| 3 (memoria, U) | 18:07:20 | 18:07:29 (9 s) | no marcada | 18:08:00 (calculado) |
| 4 (memoria, S) | 18:09:48 | 18:09:54 (6 s) | 18:09:57 (+3 s) | 18:10:28 (calculado) |
| 5 (OOM cgroup) | 18:28:44 | 18:28:55 (11 s) | 18:28:55 (+0 s) | `reset-failed` antes de las 18:31; marca de registro 18:36:40 |
| 6 (disco, U) | 18:39:23 | 18:39:32 (9 s) | 18:39:35 (+3 s) | ~18:39:53 (calculado: `timeout` de 30 s) |
| 7 (red, U) | 18:58:55 | 18:59:00 (5 s) | no marcada | ~18:59:10 (calculado: `timeout` de 15 s; `Exit 124` y `pgrep` en 0 lo confirmaron) |
| 8 (red, S) | 18:59:59 | 19:00:01 (2 s) | 19:00:01 (+0 s) | termina solo al acabar `xargs` (~19:00:01, sin marca propia) |

En los ejercicios 7 y 8, los 5 s y los 2 s de DETECTADO son sobre todo la duración del propio comando (`sar 1 5` y la ráfaga de conexiones), no un tiempo de detección.

La marca de CAUSA del ejercicio 6 dice "pidstat -d nombra a dd", pero `pidstat` mostró casi todo en el `sh` que lanza los `dd` (sección 5). Se deja el texto original de `timeline.txt` y se corrige aquí.

Límites de estas cifras: la marca `mk` se escribe al terminar cada comando, no cuando el operador ve el dato. La causa se conocía de antemano y nada de esto es una alerta. **No son un MTTD real.** Las horas "calculadas" son INYECTADO + la duración programada, no una observación.

## 9. Plan de retorno y limpieza

Todo termina solo (`timeout`, `memhog.py` con duración). Si algo queda:

```bash
pkill sha256sum; echo "exit=$?"
pkill -f memhog.py; echo "exit=$?"
systemctl --user reset-failed lab-oom.service; echo "exit=$?"
rm ~/lab-use/io.tmp; echo "exit=$?"
pkill -f 'http.server 8000'; echo "exit=$?"
rm -r ~/lab-use/red; echo "exit=$?"
```

Esperado: `pkill` `0` = mató alguno, `1` = no había (ambos aceptables); los demás `0`. Daño posible no revertido: el disco virtual de Windows pudo crecer hasta 512 MB por la prueba de disco y no se encoge solo (sin verificar).

## 10. Registro de ejecuciones

| # | Fecha | Caso | Resultado | Notas |
|---|---|---|---|---|
| 1 | 2026-11-26 | CPU U (4 procesos) | U sin S | `%nice`, no `%usr` |
| 2 | 2026-11-26 | CPU S (48 procesos) | S confirmada | `r` 48 sobre 24 núcleos |
| 3 | 2026-11-26 | Memoria U (1500 MB) | U sin S | Captura durante la subida, meseta sin verificar |
| 4 | 2026-11-26 | Memoria S (swap) | S confirmada | ~150 MB/s de swap con CPU ociosa |
| 5 | 2026-11-26 | OOM de cgroup | Controlado | Evidencia en `systemctl` y en el log del kernel |
| 6 | 2026-11-26 | Disco U | U moderada, sin S | Cifras de caché del host |
| 7 | 2026-11-26 | Red U (loopback, 50 MB/s) | Medido 52.6 MB/s | `eth0` sin carga |
| 8 | 2026-11-26 | Red S y E (300 conexiones, cola de 5) | S confirmada: 154 descartes | Invisible en `ip -s link` |

## 11. Pendiente

- Red: probar `eth0` con tráfico real (no hay carga externa medida) y contar cuántas de las 300 conexiones fallaron o esperaron.
- Red: identificar de dónde vinieron las 33 retransmisiones previas al ejercicio 8.
- Disco: reproducir saturación (varios escritores en paralelo) y comparar `aqu-sz`.
- Medir el PSI del cgroup durante el ejercicio 4 y comparar con el global.
- Capturar la meseta de memoria del ejercicio 3 (medir 5 s después de iniciar).
- Explicar: swap de 532 MB, `%soft` 0.32 → 1.60, por qué `overcommit_memory` es 1.
- OOM global del host: no probado a propósito (riesgo para Docker y la sesión).
- Alertas: no existe ninguna sobre CPU, memoria ni disco; hoy la detección fue el operador.
- `memhog.py` vive solo en `~/lab-use`: decidir si va al repo (con cabecera y prueba) o se registra por qué no.
- Probar en un host que no sea WSL2.

ITIL 4: Gestión de incidentes · tecnología