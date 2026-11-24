#!/usr/bin/env bash
# scripts/down.sh: destruye el clúster noc-tf (y Argo CD con él) y, si se pide,
# detiene MinIO.
#
# Propósito: par de scripts/up.sh; cierra el día sin dejar recursos (plan v2).
#
# Uso:
#   scripts/down.sh                       dry-run (por defecto): no cambia nada.
#   scripts/down.sh --apply               pide confirmación ("si") y destruye.
#   scripts/down.sh --apply --yes         igual, sin preguntar (para medir).
#   scripts/down.sh --apply --stop-minio  además detiene MinIO (docker compose stop).
#
# Idempotente: si noc-tf ya no existe, terraform destroy no encuentra nada que borrar.
# MinIO debe estar arriba: el estado de Terraform vive ahí (ADR-008).
# Nunca borra el volumen minio-data (no usa -v): el estado sobrevive.
# Credenciales: solo se leen dentro de un subshell desde el .env; nunca se imprimen.
#
# Códigos de salida:
#   0 ok · 1 uso incorrecto o cancelado · 2 precondición no cumplida
#   3 MinIO no responde · 4 Terraform falló · 5 el clúster noc-tf sigue existiendo
#
# Retorno: scripts/up.sh --apply
# Registros: ADR-008 (estado en MinIO), ADR-009 (Bash en vez de PowerShell),
# docs/runbook-minio-estado-terraform.md (procedimiento manual).
# Variables solo para pruebas: DOWN_MINIO_ENV y DOWN_TF_ENV.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MINIO_ENV="${DOWN_MINIO_ENV:-$REPO_ROOT/infra/minio/.env}"
TF_ENV="${DOWN_TF_ENV:-$REPO_ROOT/infra/terraform/envs/local/.env}"
TF_DIR="$REPO_ROOT/infra/terraform/envs/local"
MINIO_COMPOSE="$REPO_ROOT/infra/minio/docker-compose.yml"
MINIO_HEALTH_URL="http://127.0.0.1:9000/minio/health/live"
CLUSTER="noc-tf"

log()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { local code="$1"; shift; printf '[%s] ERROR: %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit "$code"; }

# --- Argumentos ---
MODE="dry-run"
ASSUME_YES="no"
STOP_MINIO="no"
for arg in "$@"; do
  case "$arg" in
    --apply)      MODE="apply" ;;
    --yes)        ASSUME_YES="yes" ;;
    --stop-minio) STOP_MINIO="yes" ;;
    *)            fail 1 "uso: scripts/down.sh [--apply [--yes] [--stop-minio]]" ;;
  esac
done
if [ "$MODE" != "apply" ] && { [ "$ASSUME_YES" = "yes" ] || [ "$STOP_MINIO" = "yes" ]; }; then
  fail 1 "--yes y --stop-minio solo se usan junto con --apply"
fi

# --- Funciones ---
check_preconditions() {
  for cmd in docker terraform curl kind; do
    command -v "$cmd" >/dev/null 2>&1 || fail 2 "falta el comando: $cmd"
  done
  [ -f "$TF_ENV" ] || fail 2 "falta infra/terraform/envs/local/.env (runbook, sección 7)"
  if [ "$STOP_MINIO" = "yes" ]; then
    [ -f "$MINIO_ENV" ] || fail 2 "falta infra/minio/.env (runbook, sección 3)"
  fi
  log "precondiciones: OK"
}

minio_http_code() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$MINIO_HEALTH_URL" || true
}

cluster_exists() {
  [ -n "$(kind get clusters 2>/dev/null | grep -x "$CLUSTER" || true)" ]
}

tf() { ( set -a; . "$TF_ENV"; set +a; cd "$TF_DIR" && terraform "$@" ); }

tf_step() {
  local name="$1"; shift
  log "terraform $name..."
  if ! tf "$@" >"$LOG" 2>&1; then
    tail -n 15 "$LOG" >&2
    fail 4 "terraform $name falló (si dice 403 o NoSuchBucket: runbook, sección 14)"
  fi
}

# --- Principal ---
check_preconditions

if cluster_exists; then
  log "clúster $CLUSTER: existe"
else
  log "clúster $CLUSTER: no existe"
fi

code="$(minio_http_code)"
[ "$code" = "200" ] || fail 3 "MinIO no responde (código $code); el estado vive ahí. Levántalo con scripts/up.sh o docker compose"
log "MinIO: responde (200)"

log "plan con --apply:"
log "  1. terraform init y destroy (clúster $CLUSTER + Argo CD)"
log "  2. comprobar que el clúster $CLUSTER ya no existe"
if [ "$STOP_MINIO" = "yes" ]; then
  log "  3. docker compose stop (MinIO; el volumen minio-data se conserva)"
else
  log "  3. MinIO queda arriba (usa --stop-minio para detenerlo)"
fi

if [ "$MODE" = "dry-run" ]; then
  log "DRY-RUN: no se cambió nada. Para aplicar: scripts/down.sh --apply"
  exit 0
fi

if [ "$ASSUME_YES" != "yes" ]; then
  printf 'Esto destruye el clúster %s. Escribe "si" para seguir: ' "$CLUSTER"
  read -r answer || answer=""
  [ "$answer" = "si" ] || fail 1 "cancelado: no se cambió nada"
fi

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT
SECONDS=0

tf_step init init -input=false
tf_step destroy destroy -input=false -auto-approve

if cluster_exists; then
  fail 5 "terraform terminó bien, pero el clúster $CLUSTER sigue existiendo (kind get clusters)"
fi
log "clúster $CLUSTER: destruido"

if [ "$STOP_MINIO" = "yes" ]; then
  docker compose -f "$MINIO_COMPOSE" --env-file "$MINIO_ENV" stop >/dev/null
  log "MinIO: detenido (volumen conservado)"
fi

log "DESTRUIDO en ${SECONDS} s"