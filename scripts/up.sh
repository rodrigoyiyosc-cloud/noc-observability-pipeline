#!/usr/bin/env bash
# scripts/up.sh: levanta el entorno local (MinIO + clúster noc-tf + Argo CD).
#
# Propósito: gate de la semana 4 (plan v2): todo arriba en menos de 15 min, medido.
#
# Uso:
#   scripts/up.sh            dry-run (por defecto): revisa precondiciones y muestra
#                            qué haría; no cambia nada.
#   scripts/up.sh --apply    pide confirmación y levanta todo (incremento 2).
#
# Idempotente: se puede repetir; lo que ya está arriba no se vuelve a crear.
# Credenciales: solo se leen dentro de subshells desde los .env; nunca se imprimen.
#
# Códigos de salida:
#   0 ok · 1 uso incorrecto · 2 precondición no cumplida · 3 MinIO no responde
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
if [ "$#" -gt 1 ]; then fail 1 "uso: scripts/up.sh [--apply]"; fi
case "${1:-}" in
  "")      ;;
  --apply) MODE="apply" ;;
  *)       fail 1 "uso: scripts/up.sh [--apply]" ;;
esac

# --- Precondiciones (solo lectura) ---
check_preconditions() {
  for cmd in docker terraform curl; do
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

# --- Principal ---
check_preconditions

code="$(minio_http_code)"
if [ "$code" = "200" ]; then
  log "MinIO: ya responde (200)"
else
  log "MinIO: no responde (código $code); con --apply se levantaría"
fi

log "plan con --apply (nada de esto se ejecutó):"
log "  1. docker compose up -d (MinIO) y esperar health/live = 200"
log "  2. comprobar que el bucket tfstate existe (si no, falla: ver el runbook)"
log "  3. terraform init y terraform apply (clúster noc-tf + Argo CD)"
log "  4. esperar a que la aplicación root de Argo CD esté Synced y Healthy"

if [ "$MODE" = "dry-run" ]; then
  log "DRY-RUN: no se cambió nada. Para aplicar: scripts/up.sh --apply"
  exit 0
fi

fail 1 "--apply aún no está implementado (incremento 2)"