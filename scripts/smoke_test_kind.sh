#!/usr/bin/env bash
# Smoke test: ¿arranca la imagen con los manifiestos reales y una base TimescaleDB?
# Usa su propio clúster (noc-smoke) y kubeconfig: no toca tu contexto actual.
# Todos los valores secretos son falsos y viven solo en el clúster efímero.
set -euo pipefail

IMAGE="${1:?uso: bash scripts/smoke_test_kind.sh <imagen-local>}"
CLUSTER="noc-smoke"
export KUBECONFIG=".smoke-kubeconfig"
TOKEN="smoke-token-not-real"
DBPASS="smoke-db-password-not-real"
PORT=18000
SEL="app.kubernetes.io/name=webhook-receiver"
CFG="deploy/apps/webhook/webhook-config.yaml"
PF_PID=""
FAILED=0

cleanup() {
  if [ -n "$PF_PID" ]; then kill "$PF_PID" 2>/dev/null || true; fi
  kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
  rm -f "$KUBECONFIG"
}
trap cleanup EXIT

check() { # descripcion esperado obtenido
  if [ "$2" = "$3" ]; then echo "OK    $1 -> $3"
  else echo "FALLO $1: esperado $2, obtenido $3"; FAILED=1; fi
}
http() { curl -s --max-time 20 -o /dev/null -w '%{http_code}' "$@" || true; }
cfg() { grep -E "^  $1:" "$CFG" | sed -E 's/^[^:]+: *"?([^"#]*)"?.*/\1/' | tr -d '[:space:]'; }
diagnostico() {
  echo "--- diagnóstico (los logs solo nombran variables, nunca valores)"
  kubectl get pods -n dev || true
  kubectl describe pod -n dev -l "$SEL" | grep -E "State:|Reason:|Exit Code|Restart Count|Warning|Failed" || true
  kubectl logs -n dev -l "$SEL" --tail=5 --previous 2>/dev/null || kubectl logs -n dev -l "$SEL" --tail=5 || true
}

PG_DB="$(cfg PG_DB)"; PG_USER="$(cfg PG_USER)"
[ -n "$PG_DB" ] && [ -n "$PG_USER" ] || { echo "No pude leer PG_DB/PG_USER de $CFG"; exit 1; }

echo "== 1/6 Clúster efímero ($CLUSTER)"
kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
kind create cluster --name "$CLUSTER" --kubeconfig "$KUBECONFIG" --wait 120s
kind load docker-image "$IMAGE" --name "$CLUSTER"

echo "== 2/6 Base y Secrets con valores falsos"
kubectl apply -f deploy/base/
kubectl create secret generic timescaledb-secret -n dev \
  --from-literal=POSTGRES_DB="$PG_DB" --from-literal=POSTGRES_USER="$PG_USER" \
  --from-literal=POSTGRES_PASSWORD="$DBPASS"
args=()
for k in $(grep -oE '^  [A-Z][A-Z0-9_]*:' deploy/apps/webhook/webhook-secret.yaml.example | tr -d ' :'); do
  case "$k" in
    NOC_WEBHOOK_TOKEN) v="$TOKEN" ;;
    PG_PASSWORD)       v="$DBPASS" ;;
    *)                 v="fake-$k" ;;
  esac
  args+=("--from-literal=$k=$v")
done
kubectl create secret generic webhook-secret -n dev "${args[@]}"

echo "== 3/6 TimescaleDB (manifiestos del repo)"
kubectl apply -f deploy/apps/timescaledb/timescaledb-service.yaml
kubectl apply -f deploy/apps/timescaledb/timescaledb-statefulset.yaml
kubectl rollout status statefulset/timescaledb -n dev --timeout=300s

echo "== 4/6 Esquema SQL (dos pasadas: debe ser idempotente)"
for pass in 1 2; do
  for f in sql/schema.sql sql/incident_views.sql webhook_service.sql; do
    if kubectl exec -i -n dev timescaledb-0 -- env PGOPTIONS='--client-min-messages=warning' \
         psql -q -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 < "$f" >/dev/null; then
      echo "OK    pasada $pass: $f"
    else
      echo "FALLO pasada $pass: $f"; FAILED=1
    fi
  done
done

echo "== 5/6 Webhook (PG_HOST apunta al Service del clúster solo en este test)"
sed -E 's#^(  PG_HOST:).*#\1 "timescaledb-service"#' "$CFG" | kubectl apply -f -
for f in deploy/apps/webhook/*.yaml; do
  case "$f" in *secret*|*deployment*|*webhook-config*) continue;; esac
  kubectl apply -f "$f"
done
sed -E "s#(image: )noc-webhook-service:[^[:space:]]+#\1$IMAGE#" deploy/apps/webhook/webhook-deployment.yaml | kubectl apply -f -
check "imagen desplegada" "$IMAGE" "$(kubectl get deploy webhook-service -n dev -o jsonpath='{.spec.template.spec.containers[0].image}')"

started=""; pod=""
for _ in $(seq 1 60); do
  pod=$(kubectl get pod -n dev -l "$SEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [ -n "$pod" ]; then
    started=$(kubectl get pod "$pod" -n dev -o jsonpath='{.status.containerStatuses[0].started}' 2>/dev/null || true)
    if [ "$started" = "true" ]; then break; fi
  fi
  sleep 2
done
check "contenedor iniciado (startupProbe /health)" "true" "$started"
if [ "$started" != "true" ]; then diagnostico; echo "SMOKE FALLO"; exit 1; fi
ready=true
kubectl wait --for=condition=Ready "pod/$pod" -n dev --timeout=90s >/dev/null || ready=false
check "pod Ready (readinessProbe /ready con Postgres)" "true" "$ready"
check "reinicios" "0" "$(kubectl get pod "$pod" -n dev -o jsonpath='{.status.containerStatuses[0].restartCount}')"

echo "== 6/6 Peticiones HTTP"
kubectl port-forward -n dev "pod/$pod" "$PORT:8000" >/dev/null 2>&1 &
PF_PID=$!
base="http://127.0.0.1:$PORT"
for _ in $(seq 1 20); do
  if [ "$(http "$base/health")" = "200" ]; then break; fi
  sleep 1
done
check "GET /health" 200 "$(http "$base/health")"
check "GET /ready con Postgres" 200 "$(http "$base/ready")"
check "POST /alert sin token" 401 "$(http -X POST -d '{}' "$base/alert")"
check "POST /alert token incorrecto" 401 "$(http -X POST -H 'Authorization: Bearer incorrecto' -d '{}' "$base/alert")"
check "POST /alert token correcto, body invalido" 400 "$(http -X POST -H "Authorization: Bearer $TOKEN" -d 'no-es-json' "$base/alert")"

if [ "$FAILED" -ne 0 ]; then diagnostico; echo "SMOKE FALLO"; exit 1; fi
echo "SMOKE OK"
