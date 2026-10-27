#!/usr/bin/env bash
# D2: valida con kubeconform lo que kubectl aplicaría. No usa el clúster.
set -euo pipefail

: "${K8S_VERSION:?definir K8S_VERSION, por ejemplo K8S_VERSION=1.37.0}"
OPTS=(-strict -summary -kubernetes-version "$K8S_VERSION")

echo "== 1/2 Kustomize: render y validación (deploy/apps/grafana)"
kubectl kustomize deploy/apps/grafana | kubeconform "${OPTS[@]}" -

echo "== 2/2 Manifiestos planos"
# Fuera a propósito: kustomization.yaml (no es un recurso), los Secrets
# (solo existen como .example), grafana-provisioning/ (config de Grafana, no
# de Kubernetes) y cluster/ (config de kind).
mapfile -t files < <(find deploy/base deploy/apps/webhook deploy/apps/timescaledb \
  deploy/apps/grafana -maxdepth 1 -name '*.yaml' \
  ! -name 'kustomization.yaml' ! -name '*secret*' | sort)
echo "${#files[@]} archivos"
kubeconform "${OPTS[@]}" "${files[@]}"
