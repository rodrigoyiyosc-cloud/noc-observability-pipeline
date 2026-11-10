# ADR-003: Terraform crea un clúster nuevo (noc-tf) y no reemplaza a noc-local-cluster todavía

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-11-09 |
| Decide | Rodrigo Codoceo |
| Fecha de revisión | 2026-11-20 |

## Contexto

- El plan (M0, semana 3) pide un clúster kind de 1 control-plane y 2 workers, reproducible con Terraform (providers `kind` y `helm`).
- `noc-local-cluster` (creado con `deploy/cluster/kind-3nodes.yaml`) tiene dev corriendo con el digest `d05534095c17…` y TimescaleDB con un PVC de 2Gi.
- Docker tiene 7,6 GiB de memoria. Medido el 2026-11-09 en reposo: el clúster viejo y los servicios de Compose usan cerca de 3,1 GB, y `noc-tf` suma cerca de 1,25 GB.
- El recurso `kind_cluster` guarda en el estado de Terraform el certificado y la clave del cliente.

## Decisión

1. Terraform crea `noc-tf` (1 control-plane + 2 workers) en `infra/terraform/envs/local/`. No adopta ni modifica `noc-local-cluster`.
2. `noc-tf` usa la misma imagen de nodo que el clúster actual, fijada por digest: `kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5`.
3. El kubeconfig se escribe en un archivo propio (`kubeconfig_path`), ignorado por git, para no cambiar el contexto actual de `kubectl`.
4. Versiones: Terraform `~> 1.17` (probado con 1.17.0), provider `tehcyx/kind` `~> 0.13.0`. El archivo `.terraform.lock.hcl` se versiona con hashes para `linux_amd64` y `windows_amd64`.
5. El estado es local y está ignorado por git (`*.tfstate`) hasta que exista el estado remoto en MinIO (semana 4).
6. Si `noc-tf` reemplaza a `noc-local-cluster` se decide al cerrar el gate de la semana 4 (levantar y destruir todo en menos de 15 minutos).

## Alternativas descartadas

- Reemplazar `noc-local-cluster` desde ya: cada ciclo de `destroy` y `apply` del laboratorio borraría dev y los datos de TimescaleDB.
- Importar el clúster existente a Terraform: no se probó si el provider lo permite (sin verificar).
- Un clúster de un solo nodo para el laboratorio: no cumple el gate "clúster de 1+2 nodos".

## Consecuencias

- Evidencia del 2026-11-09: `validate` y `plan` sin errores (1 recurso por crear); `apply` en 38 s; `destroy` y `apply` otra vez, con 32 s la segunda vez; 3 nodos `Ready` en v1.37.0; el contexto `kind-noc-local-cluster` no cambió. PR #60.
- Con dos clústeres encendidos la memoria queda justa. Si el uso pasa de unos 6,5 GB, se apagan los nodos del clúster viejo con `docker stop` (reversible).
- Si se pierde el archivo de estado, `noc-tf` queda sin dueño: se borra con `kind delete cluster --name noc-tf` y se recrea con `terraform apply`.
- Pendiente: `terraform fmt`, `validate` y `tflint` en CI, y el provider `helm` sobre `noc-tf`.