# ADR-008: Estado remoto de Terraform en MinIO fuera del clúster

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-11-21 |
| Decide | Rodrigo Codoceo |
| Fecha de revisión | 2027-01-04 |

## Contexto

El estado de Terraform era un archivo local. El proveedor `kind` guarda en él el certificado y la clave del cliente del clúster, y el clúster `noc-tf` se crea y se destruye por código (ADR-003). Un estado que vive dentro de lo que se destruye se pierde con ello. TF 3 del plan pide estado remoto.

MinIO publicó imágenes oficiales hasta 2025. Según Chainguard, el proyecto dejó de publicar la imagen de la edición comunitaria en octubre de 2025, y los mantenedores declinaron parchear CVE-2025-62506 en esa edición. Sin verificar en las fuentes oficiales de MinIO.

## Decisión

1. MinIO corre en Docker, fuera del clúster kind y fuera del stack de la aplicación, en un compose aparte (`infra/minio/docker-compose.yml`) con un volumen con nombre. Un `down -v` del stack no puede borrar el estado.
2. Los puertos se publican solo en `127.0.0.1`.
3. Imágenes de Chainguard fijadas por digest: servidor `sha256:e9cf6b99c226e9539ed0f14b6f00e37b07da153c7ba1f4f8709c807574b471ec` y cliente `sha256:94433f625c8057d18c69675dbaa33da6e4864f084f9c44faf30d3eb8e3754e0b` (digests del índice multi-arquitectura). La versión interna de MinIO y de `mc` es desconocida: el cliente reporta `DEVELOPMENT.GOGET`.
4. Bucket `tfstate` con versionado activado.
5. El usuario `terraform-state` tiene una política mínima (`infra/minio/policy-tfstate.json`): lista `tfstate`, lee y escribe objetos dentro de él, y borra solo archivos `*.tflock`. No puede borrar el archivo de estado. Las credenciales de root se usan solo para administrar MinIO.
6. Las credenciales viven en archivos `.env` ignorados por git; el repo solo tiene `.env.example`. Nunca se imprimen.

## Alternativas consideradas
- Imágenes de terceros en Docker Hub (espejos y compilaciones propias): descartadas, editor desconocido para algo que guarda certificado y clave.
- Otro almacén compatible con S3: diferida. Se revisa al inicio de O3, que también usa MinIO (pgBackRest).
- Dejar el estado local: descartada, no cumple el gate de TF 3 y deja certificado y clave sin versionado en el disco.

## Consecuencias
- Positivas: el estado sobrevive a la destrucción del clúster; el versionado permite volver atrás; el usuario de Terraform no puede crear buckets, ver otros, administrar ni borrar el archivo de estado (probado, ver runbook).
- Negativas: componente sin actualizaciones de seguridad de su origen; el digest no se actualiza solo; sin TLS (http en localhost); las credenciales aún no están en un gestor de claves.
- Riesgo aceptado: usar MinIO comunitario archivado solo en `localhost`. Mitigación: puertos en `127.0.0.1`, revisión el 2027-01-04, escaneo con Trivy pendiente.
- Cambia el plan: O3 (pgBackRest → MinIO) queda sujeto a la revisión de esta decisión.

## Enlaces
- [Runbook de MinIO](../docs/runbook-minio-estado-terraform.md)
- [Compose](../infra/minio/docker-compose.yml)
- [Política mínima](../infra/minio/policy-tfstate.json)
- [ADR-003: clúster nuevo noc-tf](003-terraform-cluster-nuevo-noc-tf.md)
- [ADR-007: cambio de foco](007-cambio-de-foco-observabilidad-e-infraestructura.md)