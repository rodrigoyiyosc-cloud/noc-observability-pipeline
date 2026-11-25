# Runbook: disco lleno (`No space left on device` por bloques)

| Campo | Valor |
|---|---|
| Alcance | Un sistema de archivos sin bloques libres (`df -h` al 100 %). Probado el 2026-11-25 en Ubuntu 26.04.1 LTS bajo WSL2, con un tmpfs de 32 MB montado en `/mnt/lab-disco`. **No probado en ext4** |
| Origen | Plan v2 §2.1 (Linux II, simulacros del mié 25-nov). Lectura: SYSPER 8 §8.3.16, SYSPER 9 §9.5.2 |
| Última ejecución | 2026-11-25: caso A (archivo grande) y caso B (archivo borrado pero abierto), ambos con marcas de tiempo |
| Shell | Ubuntu en WSL2 (prompt `usuario@PC`). Un comando de Linux en Git Bash (`MINGW64`) da datos de Windows |
| Regla de oro | Primero decidir si faltan bloques o inodos (sección 1). Si un proceso puede tener el archivo abierto, `rm` no libera espacio (sección 4) |

## 1. Primera pregunta: ¿bloques o inodos?

El mensaje `No space left on device` es el mismo para ambos casos. En este laboratorio fue `dd: IO error: No space left on device` con `exit=1`. El texto exacto puede variar según la versión de `dd`.

```bash
df -h /mnt/lab-disco
df -i /mnt/lab-disco
```

Esperado: exit 0 en ambos (`df` devuelve 0 si pudo leer el punto de montaje).

| `df -h` (Use%) | `df -i` (IUse%) | Conclusión | Dónde seguir |
|---|---|---|---|
| 100 % | bajo | Faltan bloques | Esta página, sección 2 |
| bajo | 100 % | Faltan inodos | `docs/runbook-inodos-agotados.md` |
| 100 % | 100 % | Ambos | Sin probar |

Observación: `df -i` redondea hacia arriba. Con 3 inodos usados de 1000 mostró `1%`.

## 2. Diagnóstico (solo lectura)

```bash
df -h /mnt/lab-disco
du -ah /mnt/lab-disco
```

Esperado: exit 0 en ambos.

Evidencia del caso A (2026-11-25):

| Comando | Salida relevante | Qué dice |
|---|---|---|
| `df -h` | `tmpfs 32M 32M 0 100%` | Sin bloques libres |
| `df -i` | `999380 inodos, 2 usados, 1%` | Inodos de sobra: no es un problema de inodos |
| `du -ah` | `32M app.log` | Un archivo visible ocupa todo el espacio |

La pregunta que separa los casos: ¿`df` y `du` cuentan lo mismo?

| `df` usado frente a `du` | Significa |
|---|---|
| Coinciden | Hay archivos visibles que ocupan el espacio: caso A |
| `df` mucho mayor que `du` | Archivo borrado pero abierto: caso B (otras causas de diferencia: sin probar) |

## 3. Caso A: un archivo grande ocupa el espacio

Causa nombrada: `app.log` ocupa los 32 MB del sistema de archivos (lo prueba `du`, con `df -i` descartando inodos).

Resolución: truncar el archivo, no borrarlo.

```bash
: > /mnt/lab-disco/app.log; echo "exit=$?"
df -h /mnt/lab-disco
```

Esperado: `exit=0` y 0 usado.

Por qué truncar y no `rm`: ver el caso B. Que truncar libere los bloques aunque un proceso tenga el archivo abierto es lo esperable, pero **no se probó**. En el caso A ningún proceso lo mantenía abierto.

## 4. Caso B: archivo borrado pero abierto

Síntoma: se borró un archivo grande y el espacio no se liberó. Evidencia de la ejecución 2:

| Momento | `df -h` | `du -ah` | Qué dice |
|---|---|---|---|
| Después del `rm` | `20M` usados (63 %) | `0 /mnt/lab-disco` | `df` y `du` no coinciden |

Prueba de la causa (con el PID del proceso sospechoso):

```bash
ls -l /proc/<PID>/fd
```

Esperado: exit 0 y una línea como `0 -> '/mnt/lab-disco/app.log (deleted)'`. Ese `(deleted)` es la evidencia: el proceso mantiene abierto un archivo que ya no tiene nombre.

Para encontrar el PID sin conocerlo existe `lsof +L1`. **Sin probar:** no se verificó si está instalado.

Resolución (la probada): detener el proceso que mantiene el archivo.

```bash
kill <PID>; echo "exit=$?"
sleep 1; df -h /mnt/lab-disco
```

Esperado: `exit=0` (solo significa que la señal se envió; la prueba es `df`) y 0 usado. Puede aparecer un aviso `Terminated`: es normal.

En un servicio real, detener el proceso es un reinicio con su costo. Reiniciar con `systemctl restart <unidad>` y truncar el archivo vía `/proc/<PID>/fd/<N>` sin matar el proceso: **sin probar**.

## 5. Pruebas negativas

| Prueba | Resultado | Qué prueba |
|---|---|---|
| `df -i` durante el caso A | `IUse%` 1 % | No eran inodos |
| `rm` del archivo con un proceso que lo mantenía abierto | `df` siguió en 20M y `du` en 0 | Borrar el nombre no libera el espacio mientras exista un descriptor abierto |

## 6. Tiempos medidos

| Ejecución | INYECTO | DETECTADO | CAUSA | RESUELTO | Desde la inyección |
|---|---|---|---|---|---|
| 1 (caso A) | 16:08:07 | 16:08:26 (19 s) | 16:09:51 (+1 min 25 s) | 16:10:17 (+26 s) | 2 min 10 s |
| 2 (caso B) | 16:17:26 | 16:17:43 (17 s) | 16:18:45 (+1 min 2 s) | 16:19:10 (+25 s) | 1 min 44 s |

Límites de estas cifras: la detección fue el error del propio `dd` o la observación del operador, no una alerta; la causa se conocía de antemano. **No son un MTTD real.**

## 7. Plan de retorno y limpieza del laboratorio

El laboratorio vive solo en memoria (tmpfs) y no toca el repo ni el disco de la distro.

```bash
jobs
sudo umount /mnt/lab-disco; echo "exit=$?"
sudo rmdir /mnt/lab-disco; echo "exit=$?"
```

Esperado: `jobs` vacío y exit 0 en ambos. Si `umount` falla por estar en uso, salir del directorio (esperable, sin probar). Al reiniciar la distro el tmpfs desaparece (esperable, sin probar).

## 8. Registro de ejecuciones

| # | Fecha | Caso | Resultado | Notas |
|---|---|---|---|---|
| 1 | 2026-11-25 | A: archivo grande, tmpfs 32 MB | Resuelto en 2 min 10 s | Causa conocida de antemano |
| 2 | 2026-11-25 | B: archivo borrado pero abierto | Resuelto en 1 min 44 s | Resolución: matar el proceso |

## 9. Pendiente

- Probar en ext4: espacio reservado para root y diferencias entre `df` y `du`.
- Detección real: no existe una alerta por uso de disco.
- Verificar si `lsof +L1` está instalado.
- Truncar un archivo borrado vía `/proc/<PID>/fd/<N>` sin detener el proceso.
- Reiniciar un servicio real con systemd en el caso B (ver `docs/runbook-servicio-caido.md`).
- `du` sobre un sistema de archivos grande: acotar con `-x` y `--max-depth` (sin probar).
- Prevención: rotación de logs y límites de tamaño (sin evaluar).
- En un caso real, nombrar qué cambió: quién escribió y por qué creció (aquí fue `dd`).

ITIL 4: Gestión de incidentes · tecnología