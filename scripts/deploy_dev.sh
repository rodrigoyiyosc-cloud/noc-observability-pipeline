#!/usr/bin/env bash
# Despliega gitops/dev al kind local. Consumidor manual hasta Argo CD (#35).
# Solo corre desde main sincronizada con origin/main.
set -euo pipefail
CTX="kind-noc-local-cluster"
cd "$(git rev-parse --show-toplevel)"

[ "$(kubectl config current-context)" = "$CTX" ] || { echo "ERROR: el contexto no es $CTX" >&2; exit 1; }
[ "$(git branch --show-current)" = "main" ] || { echo "ERROR: no estás en main" >&2; exit 1; }
[ -z "$(git status --porcelain -- gitops deploy)" ] || { echo "ERROR: cambios sin commit en gitops/ o deploy/" >&2; exit 1; }
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "ERROR: HEAD distinto de origin/main (haz git pull)" >&2; exit 1; }

want="$(sed -n 's/^ *digest: *//p' gitops/dev/kustomization.yaml | tr -d '\r')"
[[ "$want" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "ERROR: digest inválido en gitops/dev" >&2; exit 1; }

rc=0
kubectl --context "$CTX" diff -k gitops/dev || rc=$?
case "$rc" in
  0) echo "Sin diferencias: nada que aplicar."; exit 0 ;;
  1) read -r -p "Hay diferencias (arriba). ¿Aplicar? [s/N] " ans
     [ "$ans" = "s" ] || { echo "Cancelado."; exit 0; } ;;
  *) echo "ERROR: kubectl diff falló (código $rc)" >&2; exit "$rc" ;;
esac

kubectl --context "$CTX" apply -k gitops/dev
kubectl --context "$CTX" -n dev rollout status deployment/webhook-service --timeout=180s
got="$(kubectl --context "$CTX" -n dev get pods -l app.kubernetes.io/name=webhook-receiver \
  -o jsonpath='{.items[*].status.containerStatuses[*].imageID}')"
echo "imageID del pod: $got"
echo "digest esperado: $want"
case "$got" in
  *"$want"*) echo "OK: dev corre el digest esperado" ;;
  *) echo "ADVERTENCIA: imageID no contiene el digest (puede ser el del índice OCI). Verifícalo a mano." ;;
esac
