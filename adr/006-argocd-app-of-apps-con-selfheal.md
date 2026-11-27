# ADR-006: app-of-apps de Argo CD con selfHeal y prune sobre gitops/ en noc-tf

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-11-19 |
| Decide | Rodrigo Codoceo |
| Fecha de revisión | 2026-12-04 |

## Contexto

- La acción PM1-A4 (#35) pide Argo CD con `selfHeal`: un `kubectl patch` manual a un ConfigMap debe revertirse o quedar `OutOfSync`, y el tiempo debe medirse.
- ADR-005 instaló Argo CD en `noc-tf` con Terraform. El repositorio es público, así que Argo CD lo lee sin credenciales.
- `gitops/` tenía solo `gitops/dev/kustomization.yaml` y `gitops/prod/kustomization.yaml`. No existía ninguna `Application`.
- `gitops/dev` toma `deploy/apps/webhook`, cuyo `configMapGenerator` fija `namespace: dev`.
- En `noc-tf` no existe el Secret `webhook-secret`, ni hay acceso garantizado a Postgres ni controlador de Ingress.

## Decisión

1. Una `Application` raíz (`root`, en `gitops/bootstrap/root.yaml`) lee `gitops/apps/` en `main`. Su hija `webhook-dev` (en `gitops/apps/webhook-dev.yaml`) sincroniza `gitops/dev` en el namespace `dev` de `noc-tf`, con `CreateNamespace=true`.
2. Las dos Applications usan sincronización automática con `prune` y `selfHeal`.
3. `root` se aplica a mano una sola vez tras el `terraform apply` (`kubectl apply -f gitops/bootstrap/root.yaml`). Más adelante lo hará `up.sh`.
4. El repositorio es público: no hay credenciales ni token. Si pasa a privado, se abre un registro de seguridad antes de dar acceso a Argo CD.
5. Límite aceptado: en `noc-tf` el webhook queda `Degraded` (sin Secret, Postgres ni controlador de Ingress). No se crean Secrets reales en `noc-tf`. Eso no impide que Argo CD sincronice y revierta el ConfigMap, que es lo que mide #35.
6. `gitops/prod` no se sincroniza: no existe clúster de producción.
7. El dev local (`noc-local-cluster`) sigue desplegándose con `scripts/deploy_dev.sh` (ADR-005, punto 6).

## Alternativas descartadas

- Sincronizar `noc-local-cluster`: contradice ADR-003 y ADR-005.
- Una sola `Application` sin `root`: no cumple la app-of-apps que pide el plan.
- Sincronización manual: no cumple `selfHeal` ni el criterio de #35.

## Consecuencias

- Evidencia del 2026-11-19. Bootstrap a las 13:30:35: `root` `Synced/Healthy` y `webhook-dev` `Synced/Progressing`, que luego pasó a `Degraded`. El pod quedó en `CreateContainerConfigError`, como se esperaba.
- Medición de `selfHeal`: al quitar `JIRA_ISSUE_TYPE` del ConfigMap vivo, la clave volvió en unos 2 s (13:48:35 a 13:48:37).
- Prueba negativa: con `selfHeal` desactivado en `root` y `webhook-dev`, la clave seguía ausente a los 34 s (14:06:52 a 14:07:26) y `webhook-dev` quedó `OutOfSync`. `root` también quedó `OutOfSync` porque detectó la deriva de su hija. Al reactivar `selfHeal` en `root`, la clave volvió en unos 2 s y ambas apps quedaron `Synced`, con `selfHeal: true` restaurado en `webhook-dev`.
- Resolución de las medidas: ±1 s. La espera sin `selfHeal` fue de 30 s, no se midió cuánto tarda en aparecer `OutOfSync`.
- Los manifiestos de `gitops/apps/` y `gitops/bootstrap/` no pasan por `kubeconform` en CI (no conoce el tipo `Application`; el script revisa una lista fija). Hoy los valida solo un `--dry-run=server` local.
- Pendiente: validar las Applications en CI, medir el `prune` de los ConfigMap viejos del generator (sin probar), fijar las imágenes de Argo CD por digest (revisión de ADR-005) y el Secret del webhook (Sealed Secrets, M9).
- Revisión 2026-11-27: se mantiene la decisión, sin cambios en los puntos 1 a 7. En el repositorio, `gitops/apps/webhook-dev.yaml` y `gitops/bootstrap/root.yaml` no cambiaron desde su creación (`6d50da0`) y siguen con `prune` y `selfHeal` activos.
  - Punto 3: `scripts/up.sh` aplica `root` (`k apply -f "$ROOT_APP"`), con el camino manual en `docs/runbook-up-down.md`. Se verificó leyendo el script. No se ejecutó `up.sh --apply` en esta revisión porque `noc-tf` no está levantado.
  - Punto 4: el repositorio sigue `PUBLIC`. La decisión depende de eso y de la revisión de la política de Accenture, aún pendiente.
  - Resuelto: imágenes de Argo CD por digest (ADR-005, actualización del 2026-11-19).
  - Sigue abierto: validar las `Application` en CI (#94), medir el `prune` de los ConfigMap viejos y su orden frente al rollout (#95), y el Secret del webhook (Sealed Secrets, M9).
  - ADR-007 no menciona Argo CD ni GitOps: no cambia esta decisión.