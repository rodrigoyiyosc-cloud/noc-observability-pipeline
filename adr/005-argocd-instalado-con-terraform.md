# ADR-005: Argo CD se instala con Terraform (helm_release) en noc-tf, con una excepción temporal de imágenes por tag

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-11-17 |
| Decide | Rodrigo Codoceo |
| Fecha de revisión | 2026-11-19 |

## Contexto

- El plan (M0, semana 4) pide Argo CD con app-of-apps sobre `gitops/`, y la semana 3 pedía los providers `kind` y `helm` sobre el clúster. La acción PM1-A4 (#35) exige `selfHeal`.
- ADR-003 creó `noc-tf` con Terraform y dejó pendiente el provider `helm`.
- Versiones usadas, verificadas en fuentes oficiales el 2026-11-17: provider `hashicorp/helm` 3.3.0, chart `argo/argo-cd` 10.18.0 con Argo CD v3.6.1.
- El chart trae las imágenes por tag, y la regla del repo es identificarlas por digest.
- El recurso `kind_cluster` guarda en el estado el certificado y la clave del cliente (ADR-003). El provider `helm` los usa para conectarse.

## Decisión

1. Argo CD se instala con `helm_release.argocd` en `infra/terraform/envs/local/main.tf`: namespace `argocd`, chart `argo-cd` en la versión 10.18.0, provider `hashicorp/helm` `~> 3.3.0`.
2. El provider `helm` se configura con los atributos de `kind_cluster.noc_tf` (`endpoint`, `cluster_ca_certificate`, `client_certificate`, `client_key`). Así Terraform espera a que el clúster exista antes de conectarse.
3. Terraform solo instala Argo CD (bootstrap). Lo que corre dentro del clúster lo gestiona Argo CD desde `gitops/` con app-of-apps (jueves 2026-11-19). Terraform no gestiona aplicaciones.
4. Las imágenes de Argo CD (argocd, dex y redis) se fijan por digest con values del helm_release (tag: <versión>@sha256:...), verificadas contra el índice del registro. La excepción temporal quedó cerrada el 2026-11-19.
5. El flujo `down` destruye el clúster completo, no solo el release: el chart conserva las CRD de Argo CD al desinstalarse.
6. Argo CD se instala solo en `noc-tf`. `noc-local-cluster` no lo recibe (ADR-003, punto 6).

## Alternativas descartadas

- Instalar Argo CD a mano (`kubectl apply` del manifiesto oficial o `helm install`): es un paso manual que `terraform apply` no repite, y no cabe en `up.sh`.
- Fijar los digests desde hoy: exige identificar las imágenes de todos los componentes (servidor, repo-server, controladores, dex, redis) y probarlas. No cabe en el bloque de hoy, por eso va como excepción con fecha.
- Dejar que Argo CD se gestione a sí mismo desde `gitops/` sin bootstrap: igual necesita un primer arranque, que es lo que hace el `helm_release`. Se podrá evaluar después, no se probó.

## Consecuencias

- Evidencia del 2026-11-17 (PR #76): `fmt=0`, `validate` OK, `tflint=0` y plan de 2 recursos. `helm_release.argocd` se creó en 1 min 13 s. Siete pods `Running` en el namespace `argocd` (dex se reinició 2 veces al inicio; no se investigó la causa). `terraform plan -detailed-exitcode` = 0 después del `apply`. `destroy` en 1 s (release) y 5 s (clúster).
- Negativa: con el provider en uso y sin versión, `tflint` sale con 2 (`terraform_required_providers`); con la versión, sale con 0.
- El estado ya guarda el certificado y la clave del cliente. Al moverlo a MinIO (semana 4) hay que proteger el acceso al bucket.
- Las CRD de Argo CD sobreviven a un `helm uninstall`. Si algún día se destruye solo el release en un clúster que sigue vivo, quedan huérfanas.
- Pendiente: app-of-apps y `selfHeal` (#35, jueves 2026-11-19) y medir el tiempo del `up` completo contra el gate de 15 minutos.
- Actualización 2026-11-19: digests fijados (argocd v3.6.1, dex v2.46.1, redis 8.6.4-alpine), verificados con docker buildx imagetools inspect y con el imageID de los pods tras el apply.