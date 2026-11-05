
## Smoke test en kind (2026-10-27)
Solo corre en GitHub Actions (job `image-scan`, antes de publicar). GitLab no lo ejecuta: kind en Docker-in-Docker requiere un runner privilegiado. Revisar si se habilita cuando el pipeline de GitLab publique imágenes.

## Overlays de gitops (2026-11-04)
El smoke test usa los manifiestos base de `deploy/`; el overlay `gitops/` lo valida `scripts/validate_manifests.sh`. El `kustomization.yaml` de `deploy/apps/webhook/` se omite en el bucle del smoke test.
