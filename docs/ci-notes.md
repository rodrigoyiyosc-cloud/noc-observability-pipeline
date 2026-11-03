
## Smoke test en kind (2026-10-27)
Solo corre en GitHub Actions (job `image-scan`, antes de publicar). GitLab no lo ejecuta: kind en Docker-in-Docker requiere un runner privilegiado. Revisar si se habilita cuando el pipeline de GitLab publique imágenes.
