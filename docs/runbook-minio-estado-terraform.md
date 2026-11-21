# Runbook: MinIO como almacén del estado remoto de Terraform

| Campo | Valor |
|---|---|
| Fecha | 2026-11-21 |
| Dueño | Rodrigo Codoceo |
| Estado | Ejecutado una vez (2026-11-21) |
| Decisión | [ADR-008](../adr/008-minio-estado-remoto-fuera-del-cluster.md) |

## 1. Propósito

Levantar, comprobar y apagar el MinIO local que guarda el estado de Terraform fuera del clúster. Incluye bucket, versionado, un usuario de mínimo privilegio y las pruebas del control.

## 2. Requisitos

- Docker en marcha y Git Bash, desde la raíz del repo.
- `infra/minio/.env` con `MINIO_ROOT_USER` y `MINIO_ROOT_PASSWORD` (plantilla: `infra/minio/.env.example`). No está en el repo.
- Ningún `MINIO_` en el shell. Esperado: `0` (el código 1 de `grep -c` es lo esperado).
```bash
  env | grep -c '^MINIO_'
```

## 3. Crear las credenciales de root sin mostrarlas

Esperado: sin salida; luego `MINIO_ROOT_USER 13` y `MINIO_ROOT_PASSWORD 48`, y `0` saltos de línea de Windows.

```bash
printf 'MINIO_ROOT_USER=%s\nMINIO_ROOT_PASSWORD=%s\n' "tfstate-admin" "$(openssl rand -hex 24)" > infra/minio/.env
awk -F= '{print $1, length($2)}' infra/minio/.env
grep -c $'\r' infra/minio/.env
```

## 4. Levantar y comprobar

Esperado: `Up`, puertos en `127.0.0.1:9000-9001`, salud `200`. No pegar los logs completos: el banner de MinIO puede imprimir credenciales (sin verificar).

```bash
docker compose -f infra/minio/docker-compose.yml config --quiet; echo "exit=$?"
docker compose -f infra/minio/docker-compose.yml up -d
docker compose -f infra/minio/docker-compose.yml ps
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9000/minio/health/live
docker compose -f infra/minio/docker-compose.yml logs --tail 40 2>&1 | grep -i -E 'permission|denied|error|fatal|API:|WebUI:'
```

No ejecutar `docker compose config` sin `--quiet` ni `docker inspect` del contenedor: imprimen las variables.

## 5. Cliente mc: funciones `mcx` (root) y `mctf` (Terraform)

Cada comando corre un contenedor `mc` efímero en la red `noc-state_default`. El `.env` se carga dentro de un subshell, así las variables no quedan en el shell. Las funciones viven solo en la terminal donde se definen.

```bash
mcx() (
  export MSYS_NO_PATHCONV=1
  set -a; . infra/minio/.env; set +a
  export MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000"
  docker run --rm --network noc-state_default -e MC_HOST_local \
    -v "$PWD/infra/minio/policy-tfstate.json:/work/policy-tfstate.json:ro" \
    cgr.dev/chainguard/minio-client@sha256:94433f625c8057d18c69675dbaa33da6e4864f084f9c44faf30d3eb8e3754e0b "$@"
)

mctf() (
  export MSYS_NO_PATHCONV=1
  set -a; . infra/terraform/envs/local/.env; set +a
  export MC_HOST_tf="http://${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}@minio:9000"
  docker run --rm --network noc-state_default -e MC_HOST_tf \
    cgr.dev/chainguard/minio-client@sha256:94433f625c8057d18c69675dbaa33da6e4864f084f9c44faf30d3eb8e3754e0b "$@"
)
```

Prueba de conexión. Esperado: versión y `exit=0`.

```bash
mcx --version
mcx ls local; echo "exit=$?"
```

## 6. Bucket y versionado

Esperado: `Bucket created successfully` y `versioning is enabled` (dos veces).

```bash
mcx mb local/tfstate
mcx version enable local/tfstate
mcx version info local/tfstate
```

## 7. Usuario de Terraform con permiso mínimo

Política en `infra/minio/policy-tfstate.json`. Las credenciales se generan sin mostrarlas y quedan en `infra/terraform/envs/local/.env` (ignorado). `mc admin user add` recibe la clave como argumento: queda unos segundos en la línea de comandos del contenedor; aceptable en un equipo local de un solo usuario.

La política permite listar `tfstate`; leer y escribir objetos del bucket; y borrar solo archivos `*.tflock`. Terraform no puede borrar el archivo de estado (ajuste del 2026-11-21, PR 2). Para cambiarla, editar el JSON y repetir `mcx admin policy create local tfstate-rw /work/policy-tfstate.json`: sobrescribe la política (verificado el 2026-11-21: cambió `UpdateDate`). Para ver la que tiene el servidor: `mcx admin policy info local tfstate-rw`.

Esperado: `Created policy tfstate-rw successfully`; `AWS_ACCESS_KEY_ID 15` y `AWS_SECRET_ACCESS_KEY 48`; `Added user terraform-state successfully`; `Attached Policies: [tfstate-rw]`.

```bash
git check-ignore -v infra/terraform/envs/local/.env
mcx admin policy create local tfstate-rw /work/policy-tfstate.json
( s="$(openssl rand -hex 24)"
  printf 'AWS_ACCESS_KEY_ID=%s\nAWS_SECRET_ACCESS_KEY=%s\n' "terraform-state" "$s" > infra/terraform/envs/local/.env )
awk -F= '{print $1, length($2)}' infra/terraform/envs/local/.env
( set -a; . infra/terraform/envs/local/.env; set +a
  mcx admin user add local "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" )
mcx admin policy attach local tfstate-rw --user terraform-state
```

## 8. Pruebas del control (negativas)

Lo permitido pasa y lo prohibido falla. Esperado: `ls tf/tfstate` con `exit=0`; `mb tf/otro-bucket` con `Access Denied` y `exit=1`; con un bucket de control creado por root, `ls tf` muestra solo `tfstate/`, y `ls tf/control-privado` y `admin user list tf` fallan con `Access Denied` y `exit=1`.

```bash
mctf ls tf/tfstate; echo "exit=$?"
mctf mb tf/otro-bucket; echo "exit=$?"
mcx mb local/control-privado
mctf ls tf; echo "exit=$?"
mctf ls tf/control-privado; echo "exit=$?"
mctf admin user list tf; echo "exit=$?"
mcx rb --force local/control-privado
mcx ls local
```

Nota: `mctf ls tf` no da `Access Denied`: MinIO lista solo los buckets visibles al usuario (hipótesis, confirmada por el bucket de control). Con un solo bucket en el servidor esa prueba no distingue nada; por eso se usa `control-privado`.

## 9. Prueba de persistencia

Esperado: tras `down` y `up`, el objeto sigue y la salud da `200`. **Sin `-v`.**

```bash
mcx mb local/prueba-persistencia
mcx cp /work/policy-tfstate.json local/prueba-persistencia/policy.json
mcx ls local/prueba-persistencia
docker compose -f infra/minio/docker-compose.yml down
docker compose -f infra/minio/docker-compose.yml up -d
sleep 5
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9000/minio/health/live
mcx ls local/prueba-persistencia
mcx rb --force local/prueba-persistencia
mcx ls local
```

## 10. Apagar

```bash
docker compose -f infra/minio/docker-compose.yml down
```

Nunca `down -v`: borra el volumen y con él el estado remoto.

## 11. Plan de retorno

- Si el contenedor no arranca: `ps` y los logs filtrados del paso 4. Un `permission denied` apunta al usuario `65532` sobre el volumen (no ocurrió el 2026-11-21).
- Si se pierde `infra/minio/.env`: las credenciales de root se reasignan cambiando el `.env` y reiniciando (sin verificar en la documentación de esta versión).
- Si se borra el volumen: el estado remoto se pierde. Aún no hay respaldo del bucket (pendiente).
- Para volver al estado local: quitar el bloque `backend` y ejecutar `terraform init -migrate-state` (se prueba en el PR 2).

## 12. Registro de ejecuciones

| Fecha | Qué | Resultado |
|---|---|---|
| 2026-11-21 | Secciones 3 a 9 completas | Todo según lo esperado. Hallazgo: `ls tf` no da `Access Denied`; prueba corregida con bucket de control |
| 2026-11-21 | Sección 14 completa (backend, bloqueo, escritura, mínimo privilegio) | Todo según lo esperado. `apply` 1m43,7s; `destroy` 7,9 s; estado de 17 KiB en el bucket |

## 13. Pendiente

- Guardar las credenciales en un gestor de claves (hoy el `.env` es la única copia).
- Escanear las dos imágenes con Trivy.
- Probar la restauración de una versión anterior del estado (el bucket tiene versionado; no se ha probado restaurar).
- Respaldo del bucket `tfstate`.
- Mover `infra/terraform/envs/local/terraform.tfstate.backup` (estado viejo con certificado y clave) fuera del repo.
- Pasar `mcx`, `mctf` y `tfx` a un script si el procedimiento se repite una tercera vez (escalera de toil).

## 14. Uso con Terraform

El bloque `backend "s3"` está en `infra/terraform/envs/local/versions.tf`: bucket `tfstate`, clave `envs/local/terraform.tfstate`, endpoint `http://127.0.0.1:9000`, `use_path_style`, `use_lockfile` y los `skip_*` (MinIO no tiene STS, IAM ni metadata de EC2). Las credenciales no van en el bloque: Terraform lee `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY` del entorno, desde `infra/terraform/envs/local/.env` (ignorado).

Función para correr Terraform con esas credenciales sin dejarlas en el shell (vive solo en la terminal donde se define):

```bash
tfx() ( set -a; . infra/terraform/envs/local/.env; set +a; terraform -chdir=infra/terraform/envs/local "$@" )
```

**Migración y pruebas (2026-11-21).** Esperado en cada paso:

1. Credenciales falsas deben fallar. Esperado: `403 InvalidAccessKeyId` y `exit=1`.
```bash
   ( export AWS_ACCESS_KEY_ID=falso AWS_SECRET_ACCESS_KEY=falso12345678
     terraform -chdir=infra/terraform/envs/local init -migrate-state; echo "exit=$?" )
```
2. Migración real. Esperado: `Successfully configured the backend "s3"!`.
```bash
   tfx init -migrate-state
```
3. Las credenciales no quedan en `.terraform`. Esperado: `2` y `2` (los argumentos `access_key` y `secret_key` aparecen con valor `null`).
```bash
   grep -c -i -E 'access_key|secret_key' infra/terraform/envs/local/.terraform/terraform.tfstate
   grep -c -E '"(access_key|secret_key)": *null' infra/terraform/envs/local/.terraform/terraform.tfstate
```
4. Con el estado local vacío, `init` no escribe nada en el bucket. Esperado: `No state file was found!` y `0`; el bucket vacío.
```bash
   tfx state list | wc -l
   mctf ls --recursive tf/tfstate
```
5. Bloqueo, con dos terminales. En la A, `tfx apply` (sin `-auto-approve`) y esperar en `Enter a value:`. En la B, el comando de abajo. Esperado en B: `Error acquiring the state lock` (`412 PreconditionFailed`) y `exit=1`. En la A, responder `no`.
```bash
   ( set -a; . infra/terraform/envs/local/.env; set +a
     terraform -chdir=infra/terraform/envs/local plan -lock-timeout=0s ); echo "exit=$?"
```
6. Escritura real. Esperado: `Apply complete! Resources: 2 added` (1m43,7s), el objeto `envs/local/terraform.tfstate` de unos 17 KiB sin `.tflock`, y `2` recursos.
```bash
   time tfx apply -auto-approve
   mctf ls --recursive tf/tfstate
   tfx state list | wc -l
```
7. Destrucción. Esperado: `Destroy complete! Resources: 2 destroyed.` (7,9 s) y `0` recursos.
```bash
   time tfx destroy -auto-approve
   tfx state list | wc -l
```
8. Mínimo privilegio. Esperado: el `plan` funciona (crea y borra el `.tflock`) y deja solo el objeto de estado; el `rm` del estado falla con `Access Denied` y `exit=1`, y el objeto sigue ahí.
```bash
   tfx plan -no-color | grep -E '^(Plan:|No changes|Error)'
   mctf ls --recursive tf/tfstate
   mctf rm tf/tfstate/envs/local/terraform.tfstate; echo "exit=$?"
   mctf ls --recursive tf/tfstate
```

**Plan de retorno del backend:** quitar el bloque `backend` de `versions.tf` y ejecutar `terraform init -migrate-state` (sin probar). El estado remoto queda en el bucket.

**Medidas del 2026-11-21 (una sola muestra):** `apply` de clúster y Argo CD, 1m43,7s; `destroy`, 7,9 s. No son la medida del gate de `up.sh`/`down.sh`.