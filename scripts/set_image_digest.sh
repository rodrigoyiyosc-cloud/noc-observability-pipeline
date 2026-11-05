#!/usr/bin/env bash
# Cambia SOLO la línea digest: de gitops/<env>/kustomization.yaml.
set -euo pipefail
env="${1:?uso: set_image_digest.sh <dev|prod> <sha256:...>}"
digest="${2:?falta el digest}"
[[ "$env" =~ ^(dev|prod)$ ]] || { echo "ERROR: env debe ser dev o prod" >&2; exit 1; }
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "ERROR: digest inválido" >&2; exit 1; }
f="gitops/$env/kustomization.yaml"
n=$(grep -cE '^    digest: sha256:[0-9a-f]{64}$' "$f" || true)
[ "$n" -eq 1 ] || { echo "ERROR: $f debe tener exactamente 1 línea digest (hay $n)" >&2; exit 1; }
sed -i -E "s#^(    digest: )sha256:[0-9a-f]{64}\$#\1${digest}#" "$f"
git diff --numstat -- "$f"   # esperado: 1  1  <archivo>
