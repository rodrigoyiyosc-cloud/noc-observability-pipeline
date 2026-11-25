# Runbook: inodos agotados (`No space left on device` con espacio libre)

| Campo | Valor |
|---|---|
| Alcance | Un sistema de archivos sin inodos libres (`df -i` al 100 %) y con bloques de sobra. Probado el 2026-11-25 en Ubuntu 26.04.1 LTS bajo WSL2, con un tmpfs de 32 MB y 1000 inodos (`nr_inodes=1000`) en `/mnt/lab-inodos`. **No probado en ext4**, donde el número de inodos se fija al formatear (sin probar aquí) |
| Origen | Plan v2 §2.1 (Linux II, simulacros del mié 25-nov). Lectura: SYSPER 8 §8.3.11 y §8.3.16. Ninguno de los dos índices (SYSPER, LML) nombra los inodos: la fuente es `man df` |
| Última ejecución | 2026-11-25: una ejecución con marcas de tiempo |
| Shell | Ubuntu en WSL2 (prompt `usuario@PC`). Un comando de Linux en Git Bash (`MINGW64`) da datos de Windows |
| Regla de oro | Primero decidir si faltan bloques o inodos: `docs/runbook-disco-lleno.md`, sección 1 |

## 1. Síntoma

Crear un archivo falla aunque `df -h` muestre espacio libre. En el laboratorio:

```
-bash: /mnt/lab-inodos/sesiones/s998: No space left on device
```

El mensaje es el mismo que en un disco lleno. Lo que los separa es `df -i` frente a `df -h` (tabla de decisión en `docs/runbook-disco-lleno.md`, sección 1).

## 2. Diagnóstico (solo lectura)

```bash
df -h /mnt/lab-inodos
df -i /mnt/lab-inodos
```

Esperado: exit 0 en ambos.

Evidencia (2026-11-25):

| Comando | Salida relevante | Qué dice |
|---|---|---|
| `df -h` | `tmpfs 32M 0 32M 0%` | Bloques libres: no es un disco lleno |
| `df -i` | `1000 inodos, 1000 usados, 0 libres, 100%` | Sin inodos libres |

Observación: `df -i` redondea hacia arriba. Con 3 inodos usados de 1000 mostró `1%`.

## 3. Localizar quién consume inodos

Contar entradas por directorio. Para contar se usa `wc -l`:

```bash
for d in /mnt/lab-inodos/*/; do echo "$(find "$d" | wc -l) $d"; done
```

Esperado: una línea por directorio, exit 0.

| Directorio | Conteo | Qué dice |
|---|---|---|
| `cache/` | 1 | Solo el propio directorio |
| `sesiones/` | 998 | 997 archivos más el propio directorio |

Nota: `find <dir>` lista también el directorio mismo, por eso el conteo es 1 más que los archivos. Cuadre: 3 inodos iniciales (raíz y 2 directorios) + 997 archivos = 1000.

Causa nombrada: `sesiones/` concentra casi todos los archivos (997 vacíos). En un sistema real, la causa es lo que cambió: qué proceso empezó a crear archivos y por qué no se limpian.

En un sistema real, recorrer `/` con este bucle: acotar a un solo sistema de archivos con `find -xdev` (sin probar).

## 4. Resolución

Borrar los archivos del directorio culpable.

```bash
find /mnt/lab-inodos/sesiones -type f -delete; echo "exit=$?"
df -i /mnt/lab-inodos
: > /mnt/lab-inodos/prueba && echo "se puede crear de nuevo"
```

Esperado: `exit=0` (`find` devuelve 0 aunque no encuentre nada), `df -i` con 3 usados y 997 libres, y el mensaje `se puede crear de nuevo`.

**El borrado es irreversible.** En el laboratorio los archivos eran sintéticos. En un sistema real: confirmar con el dueño del directorio y respaldar antes si los archivos importan. No hay plan de retorno posterior al `-delete`.

## 5. Pruebas negativas

| Prueba | Resultado | Qué prueba |
|---|---|---|
| `df -h` durante la falla | `Use%` 0 % | No faltaban bloques |
| Conteo de `cache/` | 1 | No era ese directorio |
| Crear `prueba` después de borrar | Funcionó | La falta de inodos era la causa, no otra cosa |

## 6. Tiempos medidos

| INICIO | INYECTO | DETECTADO | CAUSA | RESUELTO | Desde la inyección |
|---|---|---|---|---|---|
| 16:27:45 | 16:28:34 (+49 s de preparación) | 16:29:29 (55 s) | 16:29:59 (+30 s) | 16:30:21 (+22 s) | 1 min 47 s |

Límites: la detección fue la observación del operador, no una alerta; la causa se conocía de antemano. **No es un MTTD real.**

## 7. Plan de retorno y limpieza del laboratorio

El laboratorio vive solo en memoria (tmpfs) y no toca el repo ni el disco de la distro.

```bash
sudo umount /mnt/lab-inodos; echo "exit=$?"
sudo rmdir /mnt/lab-inodos; echo "exit=$?"
```

Esperado: exit 0 en ambos. Si `umount` falla por estar en uso, salir del directorio (esperable, sin probar).

## 8. Registro de ejecuciones

| # | Fecha | Escenario | Resultado | Notas |
|---|---|---|---|---|
| 1 | 2026-11-25 | tmpfs de 1000 inodos, 997 archivos vacíos en `sesiones/` | Resuelto en 1 min 47 s | Causa conocida de antemano |

## 9. Pendiente

- Probar en ext4, donde los inodos se fijan al crear el sistema de archivos.
- Detección real: no existe una alerta por `IUse%`.
- Borrar un directorio con millones de archivos: velocidad de `find -delete` (sin probar).
- Archivos borrados pero abiertos también retienen su inodo (sin probar; ver `docs/runbook-disco-lleno.md`, caso B).
- Prevención: limpieza periódica de directorios de sesiones y caché (sin evaluar).

ITIL 4: Gestión de incidentes · tecnología