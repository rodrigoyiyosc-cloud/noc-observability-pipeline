
## Smoke test en kind (2026-10-27)
Solo corre en GitHub Actions (job `image-scan`, antes de publicar). GitLab no lo ejecuta: kind en Docker-in-Docker requiere un runner privilegiado. Revisar si se habilita cuando el pipeline de GitLab publique imágenes.

## Overlays de gitops (2026-11-04)
El smoke test usa los manifiestos base de `deploy/`; el overlay `gitops/` lo valida `scripts/validate_manifests.sh`. El `kustomization.yaml` de `deploy/apps/webhook/` se omite en el bucle del smoke test.

## Publicación y promoción a dev (2026-11-04)
En cada push a main corren test, config-check, manifests e image-scan; después publish (sha-<7>, sin sobrescribir una etiqueta que ya existe) y promote-dev (solo si cambió webhook_service/ o si se lanza a mano). promote-dev abre un PR que cambia la línea digest de gitops/dev, lanza ci.yml con workflow_dispatch sobre la rama del PR para que se reporten los checks obligatorios y activa el auto-merge. Si esos checks no se reportan, la salida es un PAT fine-grained como excepción documentada (ADR-002). Los tags v* no disparan este workflow.

## Releases (2026-11-05)
Un tag vX.Y.Z (anotado, sobre un commit de main) lanza release.yml: validate comprueba el formato, que sea mayor que el último tag, que la imagen de gitops/dev traiga la etiqueta revision y que webhook_service/ no haya cambiado desde ese commit. promote-prod (environment prod, con revisor) agrega la etiqueta vX.Y.Z a esa misma imagen, sin reconstruir, y abre el PR de gitops/prod.

## Release v1.0.14 fallido (2026-11-06)
`docker buildx imagetools create` con un solo origen envuelve la imagen en un índice nuevo (digest distinto). release.yml usa ahora `--prefer-index=false` (copia exacta) y comprueba que el digest de la etiqueta sea el original. La etiqueta v1.0.14 de GHCR apunta a un índice que contiene la imagen correcta; no se usa.