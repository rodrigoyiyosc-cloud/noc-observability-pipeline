#!/usr/bin/env bash
#
# timescaledb_backup.sh — Backup, restauración y prueba de restauración de TimescaleDB
#
# Uso:
#   ./timescaledb_backup.sh backup            # pg_dump (formato custom) + checksum + manifiesto
#   ./timescaledb_backup.sh verify [archivo]  # restaura en una BD temporal y compara conteos
#   ./timescaledb_backup.sh restore <archivo> [bd_destino]   # restaura en una BD NUEVA
#   ./timescaledb_backup.sh prune             # elimina backups más antiguos que RETENTION_DAYS
#   ./timescaledb_backup.sh all               # backup + verify + prune (para cron)
#
# Modos de ejecución (variable MODE):
#   docker (default)  -> docker exec en el contenedor "timescaledb" (docker-compose)
#   k8s               -> kubectl exec en deploy/timescaledb (manifiestos de k8s/)
#
# Variables (todas opcionales salvo PG_PASSWORD; se leen de .env si existe):
#   PG_USER=noc_user  PG_DB=noc  PG_PASSWORD=<requerida>
#   CONTAINER=timescaledb   K8S_NAMESPACE=default   K8S_TARGET=deploy/timescaledb
#   BACKUP_DIR=./backups    RETENTION_DAYS=7
#
# Por qué no basta un pg_restore simple: en TimescaleDB hay que envolver la
# restauración con timescaledb_pre_restore() / timescaledb_post_restore(), en una
# BD vacía que ya tenga la extensión creada.

set -Eeuo pipefail

# ── Configuración ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/../.env" ]]; then
  set -a; source "${SCRIPT_DIR}/../.env"; set +a   # carga PG_* si existen
fi

MODE="${MODE:-docker}"
PG_USER="${PG_USER:-noc_user}"
PG_DB="${PG_DB:-noc}"
PG_PASSWORD="${PG_PASSWORD:?Define PG_PASSWORD (en .env o en el entorno)}"
CONTAINER="${CONTAINER:-timescaledb}"
K8S_NAMESPACE="${K8S_NAMESPACE:-default}"
K8S_TARGET="${K8S_TARGET:-deploy/timescaledb}"
BACKUP_DIR="${BACKUP_DIR:-${SCRIPT_DIR}/../backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

# Tablas a comparar entre origen y copia restaurada: "tabla:columna_de_tiempo"
CHECK_TABLES=("network_telemetry:ts" "incident_logs:received_at" "devices:")

TEMP_DB=""   # BD temporal de verify (se limpia en trap)

# ── Utilidades ───────────────────────────────────────────────────────────────
log()  { printf '%s [%s] %s\n' "$(date '+%F %T')" "$1" "${*:2}" >&2; }
die()  { log ERROR "$*"; exit 1; }

# Ejecuta un comando dentro del contenedor/pod con PGPASSWORD (stdin pasa tal cual)
pg_run() {
  case "$MODE" in
    docker) docker exec -i -e PGPASSWORD="$PG_PASSWORD" "$CONTAINER" "$@" ;;
    k8s)    kubectl exec -i -n "$K8S_NAMESPACE" "$K8S_TARGET" -- env PGPASSWORD="$PG_PASSWORD" "$@" ;;
    *)      die "MODE inválido: $MODE (usa docker|k8s)" ;;
  esac
}

psql_db() {  # psql_db <bd> <sql>  -> salida sin formato
  local db="$1" sql="$2"
  pg_run psql -U "$PG_USER" -d "$db" -v ON_ERROR_STOP=1 -X -At -c "$sql"
}

check_prereqs() {
  case "$MODE" in
    docker) command -v docker >/dev/null || die "docker no está instalado"
            docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true \
              || die "El contenedor '$CONTAINER' no está corriendo" ;;
    k8s)    command -v kubectl >/dev/null || die "kubectl no está instalado" ;;
  esac
  command -v sha256sum >/dev/null || die "sha256sum no disponible"
  mkdir -p "$BACKUP_DIR"
}

# Conteos estables: solo filas anteriores al corte (el simulador sigue insertando)
snapshot_counts() {  # snapshot_counts <bd> <cutoff_iso>  -> líneas "tabla=conteo"
  local db="$1" cutoff="$2" spec table col where
  for spec in "${CHECK_TABLES[@]}"; do
    table="${spec%%:*}"; col="${spec##*:}"
    where=""
    [[ -n "$col" ]] && where="WHERE ${col} < '${cutoff}'::timestamptz"
    printf '%s=%s\n' "$table" "$(psql_db "$db" "SELECT count(*) FROM ${table} ${where};")"
  done
}

# ── backup ───────────────────────────────────────────────────────────────────
do_backup() {
  check_prereqs
  local ts file cutoff
  ts="$(date '+%Y%m%d_%H%M%S')"
  file="${BACKUP_DIR}/${PG_DB}_${ts}.dump"
  # Corte 1 min en el pasado: filas ya consolidadas, comparables tras restaurar
  cutoff="$(psql_db "$PG_DB" "SELECT to_char(now() - interval '1 minute', 'YYYY-MM-DD\"T\"HH24:MI:SSOF');")"

  log INFO "Iniciando backup de '${PG_DB}' (modo ${MODE}) -> ${file}"
  # -Fc: formato custom (comprimido, restaurable con pg_restore)
  if ! pg_run pg_dump -U "$PG_USER" -d "$PG_DB" -Fc --no-owner > "${file}.partial"; then
    rm -f "${file}.partial"; die "pg_dump falló"
  fi
  [[ -s "${file}.partial" ]] || { rm -f "${file}.partial"; die "El dump quedó vacío"; }
  mv "${file}.partial" "$file"

  # Integridad: checksum + el archivo debe ser legible por pg_restore --list
  ( cd "$BACKUP_DIR" && sha256sum "$(basename "$file")" > "$(basename "$file").sha256" )
  pg_run pg_restore --list < "$file" > /dev/null || die "El dump no es legible por pg_restore"

  # Manifiesto con conteos al momento del backup (referencia para verify)
  {
    echo "cutoff=${cutoff}"
    snapshot_counts "$PG_DB" "$cutoff"
  } > "${file}.manifest"

  log INFO "Backup OK: $(du -h "$file" | cut -f1) | checksum y manifiesto generados"
  echo "$file"
}

# ── restore (en BD nueva) ────────────────────────────────────────────────────
do_restore_into() {  # do_restore_into <archivo> <bd_destino>
  local file="$1" target="$2"
  [[ -f "$file" ]] || die "No existe el archivo: $file"

  # Verifica checksum si existe
  if [[ -f "${file}.sha256" ]]; then
    ( cd "$(dirname "$file")" && sha256sum -c "$(basename "$file").sha256" --quiet ) \
      || die "Checksum inválido: el backup está corrupto"
    log INFO "Checksum verificado"
  fi

  # Nunca pisa una BD existente
  local exists
  exists="$(psql_db postgres "SELECT 1 FROM pg_database WHERE datname='${target}';")"
  [[ -z "$exists" ]] || die "La BD destino '${target}' ya existe; elige otro nombre"

  log INFO "Creando BD '${target}' con extensión timescaledb"
  psql_db postgres "CREATE DATABASE \"${target}\";" >/dev/null
  psql_db "$target" "CREATE EXTENSION IF NOT EXISTS timescaledb;" >/dev/null

  log INFO "Restaurando (pre_restore -> pg_restore -> post_restore)"
  psql_db "$target" "SELECT timescaledb_pre_restore();" >/dev/null
  # Algunos avisos de pg_restore (extensión ya creada) son esperables: no abortamos por ellos
  pg_run pg_restore -U "$PG_USER" -d "$target" --no-owner --exit-on-error=false < "$file" \
    2> >(grep -v -E 'already exists|extension "timescaledb"' >&2) || \
    log WARN "pg_restore terminó con avisos; la verificación de conteos decide si es válido"
  psql_db "$target" "SELECT timescaledb_post_restore();" >/dev/null
  log INFO "Restauración completada en '${target}'"
}

do_restore() {
  check_prereqs
  local file="${1:-}" target="${2:-${PG_DB}_restored_$(date '+%Y%m%d_%H%M%S')}"
  [[ -n "$file" ]] || die "Uso: $0 restore <archivo.dump> [bd_destino]"
  do_restore_into "$file" "$target"
  log INFO "Para usarla: revisa '${target}' y, si es correcta, apunta la app a ella. No se sobrescribió '${PG_DB}'."
}

# ── verify: prueba de restauración ──────────────────────────────────────────
cleanup_temp_db() {
  if [[ -n "$TEMP_DB" ]]; then
    psql_db postgres "DROP DATABASE IF EXISTS \"${TEMP_DB}\" WITH (FORCE);" >/dev/null 2>&1 || true
    log INFO "BD temporal '${TEMP_DB}' eliminada"
  fi
}

do_verify() {
  check_prereqs
  local file="${1:-}"
  [[ -n "$file" ]] || file="$(ls -1t "${BACKUP_DIR}"/${PG_DB}_*.dump 2>/dev/null | head -n1 || true)"
  [[ -n "$file" && -f "$file" ]] || die "No hay backups que verificar en ${BACKUP_DIR}"
  [[ -f "${file}.manifest" ]] || die "Falta el manifiesto: ${file}.manifest"

  TEMP_DB="restore_test_$(date '+%Y%m%d_%H%M%S')"
  trap cleanup_temp_db EXIT
  log INFO "Prueba de restauración de $(basename "$file") en '${TEMP_DB}'"

  do_restore_into "$file" "$TEMP_DB"

  local cutoff failed=0 table expected actual
  cutoff="$(grep '^cutoff=' "${file}.manifest" | cut -d= -f2-)"

  # Compara conteos restaurados (hasta el corte) contra los del manifiesto
  while IFS='=' read -r table expected; do
    [[ "$table" == "cutoff" || -z "$table" ]] && continue
    actual="$(snapshot_counts "$TEMP_DB" "$cutoff" | grep "^${table}=" | cut -d= -f2)"
    if [[ "$actual" == "$expected" ]]; then
      log INFO "OK    ${table}: ${actual} filas (esperadas ${expected})"
    else
      log ERROR "FALLA ${table}: restauradas ${actual}, esperadas ${expected}"
      failed=1
    fi
  done < "${file}.manifest"

  # La hypertable debe seguir siendo hypertable tras restaurar
  local hts
  hts="$(psql_db "$TEMP_DB" "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name='network_telemetry';")"
  if [[ "$hts" == "1" ]]; then
    log INFO "OK    network_telemetry sigue siendo hypertable"
  else
    log ERROR "FALLA network_telemetry no quedó como hypertable"; failed=1
  fi

  [[ "$failed" -eq 0 ]] || die "Prueba de restauración FALLIDA para $(basename "$file")"
  log INFO "Prueba de restauración EXITOSA para $(basename "$file")"
}

# ── prune ────────────────────────────────────────────────────────────────────
do_prune() {
  mkdir -p "$BACKUP_DIR"
  log INFO "Eliminando backups con más de ${RETENTION_DAYS} días en ${BACKUP_DIR}"
  find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name "${PG_DB}_*.dump" -o -name "${PG_DB}_*.dump.sha256" -o -name "${PG_DB}_*.dump.manifest" \) \
    -mtime "+${RETENTION_DAYS}" -print -delete >&2
}

# ── main ─────────────────────────────────────────────────────────────────────
case "${1:-}" in
  backup)  do_backup ;;
  verify)  do_verify "${2:-}" ;;
  restore) do_restore "${2:-}" "${3:-}" ;;
  prune)   do_prune ;;
  all)     f="$(do_backup)"; do_verify "$f"; do_prune ;;
  *)       sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac