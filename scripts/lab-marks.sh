#!/usr/bin/env bash
# lab-marks.sh - marcas de tiempo T+ para simulacros e incidentes (PM1-A7, issue #29).
#
# Proposito: reemplazar el calculo manual de T+ (docs/toil.md, linea del 2026-11-17).
# Fija un disparo (T0) y cada marca guarda su hora y su T+ sola.
#
# Comandos:
#   Disparo [nombre]   abre la sesion y fija T0 (la inyeccion o el aviso)
#   Det     [texto]    marca DETECTADO
#   Causa   [texto]    marca CAUSA (poner el comando que la prueba)
#   Accion  [texto]    marca ACCION (el cambio aplicado)
#   Res     [texto]    marca RESUELTO (la confirmacion: la verificacion posterior a la accion)
#   Ver                muestra las marcas y el T+ de ahora
#   Tabla              imprime las marcas como filas de tabla Markdown (para el post-mortem)
#   Resumen            tiempos entre marcas (detectar, causa, accion, resolver)
#   Fin                muestra el resumen y cierra la sesion
#
# Uso recomendado (las funciones quedan en tu terminal y sirven en todas las que abras):
#   source scripts/lab-marks.sh
#   Disparo "disco-lleno"; Det "df muestra 100%"; Causa "du -ah: app.log ocupa todo"
# Uso como comando (cada llamada es un proceso aparte; el estado vive en un archivo):
#   scripts/lab-marks.sh disparo disco-lleno
#   scripts/lab-marks.sh det "df muestra 100%"
#
# Estado: ${LAB_MARKS_HOME:-$HOME/.lab-marks} (permisos 700; fuera del repo).
# NO escribir secretos en los textos de las marcas.
#
# Por que no tiene modo dry-run: su unico efecto es agregar lineas a su propio archivo
# de marcas; no toca nada externo. Ver y Tabla solo leen. Excepcion registrada en docs/toil.md.
# Idempotencia: repetir Det, Causa, Accion o Res agrega otra marca (no sobrescribe).
# Disparo con una sesion abierta falla (codigo 3) salvo LAB_MARKS_FORCE=1.
#
# Codigos de salida:
#   0 ok | 2 uso o argumento invalido | 3 ya hay una sesion abierta
#   4 no hay sesion abierta | 5 error de lectura o escritura | 6 el reloj retrocedio
#
# Pruebas: scripts/test_lab_marks.sh (reloj falso con LAB_MARKS_NOW=<epoch>).
# Requiere bash 4 o mayor y date de GNU (WSL2 y Git Bash los traen).
# Esta pensado para cargarse con "source": no activa set -e en tu terminal.

if [ -z "${BASH_VERSION:-}" ] || [ "${BASH_VERSINFO[0]:-0}" -lt 4 ]; then
  echo "lab-marks: requiere bash 4 o mayor" >&2
  return 2 2>/dev/null || exit 2
fi

LAB_MARKS_VERSION=1

lab__dir() { printf '%s' "${LAB_MARKS_HOME:-$HOME/.lab-marks}"; }

# Hora actual en segundos epoch. LAB_MARKS_NOW permite un reloj falso (solo para pruebas).
lab__now() {
  local n="${LAB_MARKS_NOW:-}"
  if [[ -z "$n" ]]; then
    date +%s
    return 0
  fi
  if [[ ! "$n" =~ ^[0-9]+$ ]]; then
    echo "lab-marks: LAB_MARKS_NOW debe ser un entero (segundos epoch)" >&2
    return 2
  fi
  printf '%s\n' "$n"
}

lab__hms() { date -d "@$1" +%T; }

# Segundos -> "7 s", "3 min 7 s" o "1 h 2 min 3 s".
lab__fmt() {
  local s="$1" h m
  h=$((s / 3600))
  m=$(((s % 3600) / 60))
  s=$((s % 60))
  if ((h > 0)); then
    printf '%d h %d min %d s' "$h" "$m" "$s"
  elif ((m > 0)); then
    printf '%d min %d s' "$m" "$s"
  else
    printf '%d s' "$s"
  fi
}

# Ruta del archivo de la sesion abierta (falla si no hay).
lab__current() {
  local d f
  d="$(lab__dir)"
  [[ -r "$d/current" ]] || return 1
  f="$(<"$d/current")"
  [[ -n "$f" && -r "$f" ]] || return 1
  printf '%s\n' "$f"
}

lab__t0() {
  local t
  t="$(sed -n 's/^# t0: //p' "$1" | head -n 1)"
  [[ "$t" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$t"
}

lab__nombre() { sed -n 's/^# nombre: //p' "$1" | head -n 1; }

lab__sin_sesion() { echo "lab-marks: no hay sesion abierta; ejecuta Disparo primero" >&2; }

# lab__mark ETIQUETA [texto...]: escribe "epoch|hora|T+...|ETIQUETA|texto" y lo muestra.
lab__mark() {
  local label="$1"
  shift
  local text="$*" cur t0 now delta
  cur="$(lab__current)" || { lab__sin_sesion; return 4; }
  t0="$(lab__t0 "$cur")" || { echo "lab-marks: archivo de sesion danado (sin t0): $cur" >&2; return 5; }
  now="$(lab__now)" || return $?
  delta=$((now - t0))
  if ((delta < 0)); then
    echo "lab-marks: el reloj retrocedio respecto de T0; no se escribe la marca" >&2
    return 6
  fi
  text="${text//$'\n'/ }"
  printf '%s|%s|T+%s|%s|%s\n' "$now" "$(lab__hms "$now")" "$(lab__fmt "$delta")" "$label" "$text" >>"$cur" ||
    { echo "lab-marks: no se pudo escribir en $cur" >&2; return 5; }
  printf '%s  T+%s  %s  %s\n' "$(lab__hms "$now")" "$(lab__fmt "$delta")" "$label" "$text"
}

Disparo() {
  local name="${1:-simulacro}" now d f
  if [[ ! "$name" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "lab-marks: nombre invalido (solo letras, numeros, punto, guion y guion bajo)" >&2
    return 2
  fi
  if lab__current >/dev/null 2>&1 && [[ "${LAB_MARKS_FORCE:-0}" != "1" ]]; then
    echo "lab-marks: ya hay una sesion abierta ($(lab__current)); usa Fin o LAB_MARKS_FORCE=1" >&2
    return 3
  fi
  now="$(lab__now)" || return $?
  d="$(lab__dir)"
  (umask 077 && mkdir -p "$d") || { echo "lab-marks: no se pudo crear $d" >&2; return 5; }
  f="$d/$(date -d "@$now" +%Y%m%d-%H%M%S)-$name.txt"
  if [[ -e "$f" ]]; then
    echo "lab-marks: ya existe $f (mismo nombre en el mismo segundo)" >&2
    return 3
  fi
  (umask 077 && printf '# lab-marks v%s\n# nombre: %s\n# t0: %s\n' "$LAB_MARKS_VERSION" "$name" "$now" >"$f" &&
    printf '%s\n' "$f" >"$d/current") || { echo "lab-marks: no se pudo escribir la sesion en $d" >&2; return 5; }
  lab__mark DISPARO "$name"
}

Det() { lab__mark DETECTADO "$@"; }
Causa() { lab__mark CAUSA "$@"; }
Accion() { lab__mark ACCION "$@"; }
Res() { lab__mark RESUELTO "$@"; }

Ver() {
  local cur t0 now
  cur="$(lab__current)" || { lab__sin_sesion; return 4; }
  t0="$(lab__t0 "$cur")" || { echo "lab-marks: archivo de sesion danado (sin t0): $cur" >&2; return 5; }
  now="$(lab__now)" || return $?
  echo "Sesion: $(lab__nombre "$cur")"
  grep -v '^#' "$cur" | while IFS='|' read -r _e hms tp label text; do
    printf '%s  %s  %s  %s\n' "$hms" "$tp" "$label" "$text"
  done
  if ((now < t0)); then
    echo "ahora: el reloj retrocedio respecto de T0" >&2
    return 6
  fi
  printf 'ahora: T+%s\n' "$(lab__fmt $((now - t0)))"
}

Tabla() {
  local cur
  cur="$(lab__current)" || { lab__sin_sesion; return 4; }
  printf '| Hora | T+ | Evento |\n|---|---|---|\n'
  grep -v '^#' "$cur" | while IFS='|' read -r _e hms tp label text; do
    text="${text//|/\\|}"
    if [[ -n "$text" ]]; then
      printf '| %s | %s | Marca `%s`: %s |\n' "$hms" "$tp" "$label" "$text"
    else
      printf '| %s | %s | Marca `%s` |\n' "$hms" "$tp" "$label"
    fi
  done
}

Resumen() {
  local cur t0 prev_label="" prev_t=0 rel gap epoch label
  local -A seen=()
  cur="$(lab__current)" || { lab__sin_sesion; return 4; }
  t0="$(lab__t0 "$cur")" || { echo "lab-marks: archivo de sesion danado (sin t0): $cur" >&2; return 5; }
  echo "Resumen de $(lab__nombre "$cur")"
  while IFS='|' read -r epoch _hms _tp label _text; do
    [[ -n "${seen[$label]:-}" ]] && continue
    seen[$label]=1
    rel=$((epoch - t0))
    if [[ -z "$prev_label" ]]; then
      printf '%s: T+%s\n' "$label" "$(lab__fmt "$rel")"
    else
      gap=$((epoch - prev_t))
      if ((gap < 0)); then
        printf '%s: T+%s (orden inconsistente respecto de %s)\n' "$label" "$(lab__fmt "$rel")" "$prev_label"
      else
        printf '%s: T+%s (+%s desde %s)\n' "$label" "$(lab__fmt "$rel")" "$(lab__fmt "$gap")" "$prev_label"
      fi
    fi
    prev_label="$label"
    prev_t="$epoch"
  done < <(grep -v '^#' "$cur")
}

Fin() {
  local r
  Resumen
  r=$?
  ((r == 0)) || return "$r"
  : >"$(lab__dir)/current" || { echo "lab-marks: no se pudo cerrar la sesion" >&2; return 5; }
}

lab__help() {
  sed -n '2,/^# Pruebas:/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

lab__main() {
  local cmd="${1:-help}"
  (($#)) && shift
  case "${cmd,,}" in
    disparo) Disparo "$@" ;;
    det) Det "$@" ;;
    causa) Causa "$@" ;;
    accion) Accion "$@" ;;
    res) Res "$@" ;;
    ver) Ver ;;
    tabla) Tabla ;;
    resumen) Resumen ;;
    fin) Fin ;;
    help | -h | --help) lab__help ;;
    *)
      echo "lab-marks: comando desconocido: $cmd" >&2
      lab__help >&2
      return 2
      ;;
  esac
}

# Si se ejecuta (no se carga con source), despacha el comando.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  lab__main "$@"
  exit $?
fi