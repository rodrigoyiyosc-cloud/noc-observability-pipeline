#!/usr/bin/env bash
# test_lab_marks.sh - pruebas de scripts/lab-marks.sh con reloj falso (PM1-A7, issue #29).
#
# Proposito: probar el script sin esperar tiempo real, con marcas falsas y pruebas negativas.
# Usa un directorio temporal y TZ=UTC; no toca ~/.lab-marks.
# Codigos de salida: 0 todo bien | 1 alguna prueba fallo.
# Uso: bash scripts/test_lab_marks.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/lab-marks.sh"
TMP="$(mktemp -d)"
trap '[[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"' EXIT
export TZ=UTC
export LAB_MARKS_HOME="$TMP/estado"
unset LAB_MARKS_NOW LAB_MARKS_FORCE

pass=0
fail=0
check() { # descripcion esperado real
  if [[ "$2" == "$3" ]]; then
    pass=$((pass + 1))
    printf 'ok   %s\n' "$1"
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  esperado: [%s]\n  real:     [%s]\n' "$1" "$2" "$3"
  fi
}

# run NOW args...: ejecuta el script como comando con reloj falso; deja salida en $out y codigo en $rc.
run() {
  local now="$1"
  shift
  out="$(LAB_MARKS_NOW="$now" bash "$SCRIPT" "$@" 2>&1)"
  rc=$?
}

T0=1767225600 # 2026-01-01 00:00:00 UTC

echo "== Escenario con los tiempos de PM-001 (marcas falsas)"
run "$T0" disparo pm001-falso
check "Disparo: codigo 0" "0" "$rc"
check "Disparo: T+0 s" "00:00:00  T+0 s  DISPARO  pm001-falso" "$out"

run $((T0 + 187)) det "CrashLoopBackOff, causa en logs --previous"
check "Det a +187 s" "00:03:07  T+3 min 7 s  DETECTADO  CrashLoopBackOff, causa en logs --previous" "$out"
run $((T0 + 287)) causa "comparar claves repo vs cluster"
check "Causa a +287 s" "00:04:47  T+4 min 47 s  CAUSA  comparar claves repo vs cluster" "$out"
run $((T0 + 316)) accion "restaurar ConfigMap desde el repo"
check "Accion a +316 s" "00:05:16  T+5 min 16 s  ACCION  restaurar ConfigMap desde el repo" "$out"
run $((T0 + 470)) res "pods 1/1 y PG_HOST presente"
check "Res a +470 s" "00:07:50  T+7 min 50 s  RESUELTO  pods 1/1 y PG_HOST presente" "$out"

run $((T0 + 500)) tabla
expected_tabla='| Hora | T+ | Evento |
|---|---|---|
| 00:00:00 | T+0 s | Marca `DISPARO`: pm001-falso |
| 00:03:07 | T+3 min 7 s | Marca `DETECTADO`: CrashLoopBackOff, causa en logs --previous |
| 00:04:47 | T+4 min 47 s | Marca `CAUSA`: comparar claves repo vs cluster |
| 00:05:16 | T+5 min 16 s | Marca `ACCION`: restaurar ConfigMap desde el repo |
| 00:07:50 | T+7 min 50 s | Marca `RESUELTO`: pods 1/1 y PG_HOST presente |'
check "Tabla: filas Markdown" "$expected_tabla" "$out"

run $((T0 + 500)) resumen
expected_resumen='Resumen de pm001-falso
DISPARO: T+0 s
DETECTADO: T+3 min 7 s (+3 min 7 s desde DISPARO)
CAUSA: T+4 min 47 s (+1 min 40 s desde DETECTADO)
ACCION: T+5 min 16 s (+29 s desde CAUSA)
RESUELTO: T+7 min 50 s (+2 min 34 s desde ACCION)'
check "Resumen: tiempos entre marcas" "$expected_resumen" "$out"

run $((T0 + 500)) ver
check "Ver: termina con el T+ de ahora" "ahora: T+8 min 20 s" "$(tail -n 1 <<<"$out")"

run $((T0 + 500)) fin
check "Fin cierra la sesion de PM-001: codigo 0" "0" "$rc"

echo "== Formato de duraciones"
run "$T0" disparo formato
check "Disparo de formato: codigo 0" "0" "$rc"
run $((T0 + 59)) det
check "59 s" "00:00:59  T+59 s  DETECTADO  " "$out"
run $((T0 + 60)) det
check "60 s" "00:01:00  T+1 min 0 s  DETECTADO  " "$out"
run $((T0 + 3723)) det
check "3723 s" "01:02:03  T+1 h 2 min 3 s  DETECTADO  " "$out"
run $((T0 + 3724)) disparo otra
check "Disparo con sesion abierta: codigo 3" "3" "$rc"

echo "== Pruebas negativas"
run $((T0 + 900)) fin
check "Fin: codigo 0" "0" "$rc"
run $((T0 + 901)) det "sin sesion"
check "Det despues de Fin: codigo 4" "4" "$rc"
run $((T0 + 901)) tabla
check "Tabla sin sesion: codigo 4" "4" "$rc"

run "$T0" disparo "../escape"
check "Nombre invalido: codigo 2" "2" "$rc"
run "$T0" disparo "con espacio"
check "Nombre con espacio: codigo 2" "2" "$rc"
run "abc" disparo nombre-ok
check "Reloj no numerico: codigo 2" "2" "$rc"
run "$T0" desconocido
check "Comando desconocido: codigo 2" "2" "$rc"

run $((T0 + 2000)) disparo reloj
run $((T0 + 1990)) det "reloj atrasado"
check "Reloj retrocedio: codigo 6" "6" "$rc"
run $((T0 + 2001)) disparo otra-sesion
check "Segundo Disparo sin forzar: codigo 3" "3" "$rc"
out="$(LAB_MARKS_FORCE=1 LAB_MARKS_NOW=$((T0 + 2002)) bash "$SCRIPT" disparo forzada 2>&1)"
rc=$?
check "Disparo forzado: codigo 0" "0" "$rc"

echo "== Texto con barra vertical y permisos"
run $((T0 + 2010)) det "a|b"
run $((T0 + 2011)) tabla
check "Tabla escapa la barra vertical" '| 00:33:30 | T+8 s | Marca `DETECTADO`: a\|b |' "$(grep 'a' <<<"$out" | tail -n 1)"
case "$(uname -s)" in
  MINGW* | MSYS* | CYGWIN*) echo "skip permisos 700: el sistema de archivos de Windows no los aplica" ;;
  *) check "Directorio de estado con permisos 700" "700" "$(stat -c %a "$LAB_MARKS_HOME")" ;;
esac

echo "== Cargado con source"
out="$(bash -c 'source "$1"; [[ $- != *e* ]] && echo sin-set-e' _ "$SCRIPT")"
check "source no activa set -e" "sin-set-e" "$out"
out="$(LAB_MARKS_NOW=$((T0 + 5000)) bash -c 'source "$1"; Det "desde funcion"' _ "$SCRIPT" 2>&1)"
check "Funcion Det cargada con source usa la sesion abierta" "01:23:20  T+49 min 58 s  DETECTADO  desde funcion" "$out"

echo
echo "pasaron: $pass | fallaron: $fail"
[[ "$fail" -eq 0 ]]