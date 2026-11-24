#!/usr/bin/env bash
# scripts/up.sh: levanta el entorno local (MinIO + clúster noc-tf + Argo CD).
#
# Propósito: gate de la semana 4 (plan v2): todo arriba en menos de 15 min, medido.
#
# Uso:
#   scripts/up.sh            dry-run (por defecto): revisa precondiciones y muestra
#                            qué haría; no cambia nada.
#   scripts/up.sh --apply    pide confirmación ("si") y levanta todo.
#   scripts/up.sh --apply --yes   igual, sin preguntar (para medir el gate).
#
# Idempotente: se puede repetir; lo que ya está arriba no se vuelve a crear.
# Credenciales: solo se leen dentro de subshells desde los .env; nunca se imprimen.
#
# Códigos de salida:
#   0 ok · 1 uso incorrecto o cancelado · 2 precondición no cumplida · 3 MinIO no responde
#   4 Terraform falló · 5 Argo CD no llegó al estado esperado a tiempo
#
# Criterio de "levantado": MinIO responde 200; terraform apply termina bien; la
# aplicación `root` de Argo CD queda Synced y Healthy; `webhook-dev` queda Synced.
# Limitación conocida: `webhook-dev` puede quedar Degraded (se investiga el
# 2026-12-05); el criterio se endurecerá después.
#
# Retorno: scripts/down.sh --apply
# Registros: ADR-008 (estado en MinIO), ADR-009 (Bash en vez de PowerShell),
# docs/runbook-minio-estado-terraform.md (procedimiento manual).
# Variables solo para pruebas: UP_MINIO_ENV y UP_TF_ENV (rutas alternativas a los .env).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MINIO_ENV="${UP_MINIO_ENV:-$REPO_ROOT/infra/minio/.env}"
TF_ENV="${UP_TF_ENV:-$REPO_ROOT/infra/terraform/envs/local/.env}"
MINIO_HEALTH_URL="http://127.0.0.1:9000/minio/health/live"

log()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { local code="$1"; shift; printf '[%s] ERROR: %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit "$code"; }

# --- Argumentos ---
MODE="dry-run"
ASSUME_YES="no"
for arg in "$@"; do
  case "$arg" in
    --apply) MODE="apply" ;;
    --yes)   ASSUME_YES="yes" ;;
    *)       fail 1 "uso: scripts/up.sh [--apply [--yes]]" ;;
  esac
done
if [ "$ASSUME_YES" = "yes" ] && [ "$MODE" != "apply" ]; then
  fail 1 "--yes solo se usa junto con --apply"
fi

TF_DIR="$REPO_ROOT/infra/terraform/envs/local"
MINIO_COMPOSE="$REPO_ROOT/infra/minio/docker-compose.yml"
ROOT_APP="$REPO_ROOT/gitops/bootstrap/root.yaml"
GATE_SECONDS=900
ARGO_TIMEOUT=300

# --- Precondiciones (solo lectura) ---
check_preconditions() {
  for cmd in docker terraform curl kubectl; do
    command -v "$cmd" >/dev/null 2>&1 || fail 2 "falta el comando: $cmd"
  done
  docker info >/dev/null 2>&1 || fail 2 "Docker no responde"
  [ -f "$MINIO_ENV" ] || fail 2 "falta infra/minio/.env (runbook, sección 3)"
  [ -f "$TF_ENV" ]    || fail 2 "falta infra/terraform/envs/local/.env (runbook, sección 7)"
  # Una variable MINIO_ en el shell pisaría al .env de Docker Compose (lección de PM-003).
  if [ -n "$(env | grep '^MINIO_' || true)" ]; then
    fail 2 "hay variables MINIO_ en el shell; pisarían al .env (quítalas con unset)"
  fi
  log "precondiciones: OK"
}

# Código HTTP de MinIO; "000" si no hay conexión.
minio_http_code() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$MINIO_HEALTH_URL" || true
}

# Terraform con las credenciales del .env, cargadas solo dentro del subshell.
tf() { ( set -a; . "$TF_ENV"; set +a; cd "$TF_DIR" && terraform "$@" ); }

# kubectl contra el clúster noc-tf (se define KCFG más abajo).
k() { kubectl --kubeconfig "$KCFG" "$@"; }

minio_up() {
  log "MinIO: docker compose up -d"
  docker compose -f "$MINIO_COMPOSE" --env-file "$MINIO_ENV" up -d >/dev/null || return 1
  local i
  for i in $(seq 1 30); do
    [ "$(minio_http_code)" = "200" ] && return 0
    sleep 2
  done
  return 1
}

# Corre un subcomando de terraform; si falla, muestra el final del log y sale con 4.
tf_step() {
  local name="$1"; shift
  log "terraform $name..."
  if ! tf "$@" >"$LOG" 2>&1; then
    tail -n 15 "$LOG" >&2
    fail 4 "terraform $name falló (si dice NoSuchBucket o 403: runbook, sección 14)"
  fi
}

# Estado de una aplicación de Argo CD: $1 = nombre, $2 = sync.status o health.status.
app_status() {
  k -n argocd get application "$1" -o "jsonpath={.status.$2}" 2>/dev/null || true
}

wait_argo() {
  local end=$((SECONDS + ARGO_TIMEOUT)) rs rh ws
  while [ "$SECONDS" -lt "$end" ]; do
    rs="$(app_status root sync.status)"
    rh="$(app_status root health.status)"
    ws="$(app_status webhook-dev sync.status)"
    if [ "$rs" = "Synced" ] && [ "$rh" = "Healthy" ] && [ "$ws" = "Synced" ]; then
      log "Argo CD: root $rs/$rh · webhook-dev $ws"
      return 0
    fi
    sleep 5
  done
  log "Argo CD (último estado): root ${rs:-?}/${rh:-?} · webhook-dev ${ws:-?}" >&2
  return 1
}

# --- Principal ---
check_preconditions

code="$(minio_http_code)"
if [ "$code" = "200" ]; then
  log "MinIO: ya responde (200)"
else
  log "MinIO: no responde (código $code); con --apply se levantaría"
fi

log "plan con --apply:"
log "  1. docker compose up -d (MinIO) y esperar health/live = 200 (máx. 60 s)"
log "  2. terraform init y apply (clúster noc-tf + Argo CD; el bucket tfstate debe existir)"
log "  3. kubectl apply -f gitops/bootstrap/root.yaml (app-of-apps, ADR-006)"
log "  4. esperar (máx. ${ARGO_TIMEOUT} s) root Synced y Healthy, y webhook-dev Synced"
log "  5. medir el tiempo total contra el gate de ${GATE_SECONDS} s"

if [ "$MODE" = "dry-run" ]; then
  log "DRY-RUN: no se cambió nada. Para aplicar: scripts/up.sh --apply"
  exit 0
fi

if [ "$ASSUME_YES" != "yes" ]; then
  printf 'Esto levanta MinIO, el clúster noc-tf y Argo CD. Escribe "si" para seguir: '
  read -r answer || answer=""
  [ "$answer" = "si" ] || fail 1 "cancelado: no se cambió nada"
fi

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT
SECONDS=0

minio_up || fail 3 "MinIO no respondió 200 en 60 s (docker compose -f infra/minio/docker-compose.yml logs, filtrando secretos)"
log "MinIO: responde (200)"

tf_step init init -input=false
tf_step apply apply -input=false -auto-approve

# La ruta viene relativa al directorio de Terraform (./noc-tf.kubeconfig).
KCFG="$(tf output -raw kubeconfig_path)"
KCFG="$TF_DIR/${KCFG#./}"
[ -f "$KCFG" ] || fail 4 "no existe el kubeconfig: $KCFG"

log "Argo CD: aplicando root"
k apply -f "$ROOT_APP" >/dev/null || fail 5 "kubectl apply de root falló"
wait_argo || fail 5 "Argo CD no llegó al estado esperado en ${ARGO_TIMEOUT} s"

total="$SECONDS"
log "LEVANTADO en ${total} s (gate: ${GATE_SECONDS} s)"
if [ "$total" -le "$GATE_SECONDS" ]; then
  log "gate: CUMPLE"
else
  log "gate: NO CUMPLE"
fi