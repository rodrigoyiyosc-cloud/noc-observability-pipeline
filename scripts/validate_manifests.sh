#!/usr/bin/env bash
# D2: valida con kubeconform lo que kubectl aplicaría. No usa el clúster.
set -euo pipefail

: "${K8S_VERSION:?definir K8S_VERSION, por ejemplo K8S_VERSION=1.37.0}"
OPTS=(-strict -summary -kubernetes-version "$K8S_VERSION")

echo "== 1/4 Kustomize: render y validación"
for d in deploy/apps/grafana deploy/apps/webhook deploy/apps/kube-state-metrics deploy/apps/prometheus gitops/dev gitops/prod; do
  echo "-- $d"
  kubectl kustomize "$d" | kubeconform "${OPTS[@]}" -
done

echo "== 2/4 gitops/prod no debe arrastrar valores de dev"
rendered="$(kubectl kustomize gitops/prod)"
if grep -nE 'environment: *"?dev"?|namespace: *dev' <<<"$rendered"; then
  echo "ERROR: gitops/prod contiene valores de dev (líneas arriba)" >&2
  exit 1
fi

echo "== 3/4 gitops/<env>: imagen fijada por digest, sin newTag"
for e in dev prod; do
  f="gitops/$e/kustomization.yaml"
  n=$(grep -cE '^    digest: sha256:[0-9a-f]{64}$' "$f" || true)
  [ "$n" -eq 1 ] || { echo "ERROR: $f debe tener exactamente 1 digest válido (hay $n)" >&2; exit 1; }
  if grep -q 'newTag' "$f"; then echo "ERROR: $f usa newTag" >&2; exit 1; fi
done

echo "== 4/4 Manifiestos planos"
# Fuera a propósito: kustomization.yaml (no es un recurso), los Secrets
# (solo existen como .example), grafana-provisioning/ (config de Grafana, no
# de Kubernetes) y cluster/ (config de kind).
mapfile -t files < <(find deploy/base deploy/apps/webhook deploy/apps/timescaledb \
  deploy/apps/grafana -maxdepth 1 -name '*.yaml' \
  ! -name 'kustomization.yaml' ! -name '*secret*' | sort)
echo "${#files[@]} archivos"
kubeconform "${OPTS[@]}" "${files[@]}"
