# Runbook: levantar y destruir el entorno local con up.sh y down.sh

Fecha: 2026-11-24 · Responsable: Rodrigo Codoceo · Revisión: 2027-01-04
Registros: ADR-009 (Bash en scripts/), ADR-008 (estado en MinIO), ADR-006 (app-of-apps).

## 1. Propósito

Levantar MinIO, el clúster `noc-tf` y Argo CD en menos de 15 minutos, y destruirlos al terminar el día. Es el gate de la semana 4 del plan. Los dos scripts hacen dry-run por defecto: no cambian nada sin `--apply`.

## 2. Requisitos

1. Git Bash (o WSL2) en la raíz del repo, con Docker corriendo.
2. Comandos: `docker`, `terraform`, `curl`, `kubectl` y `kind`.
3. `infra/minio/.env` e `infra/terraform/envs/local/.env` creados (runbook de MinIO, secciones 3 y 7). Nunca se imprimen.
4. Bucket `tfstate` y usuario `terraform-state` creados (runbook de MinIO, secciones 6 y 7).
5. Sin variables `MINIO_` en el shell: pisarían al `.env` (PM-003). El script lo comprueba.

## 3. Levantar

1. `scripts/up.sh`
   - Esperado: precondiciones OK, el plan de 5 pasos, `DRY-RUN: no se cambió nada` y `exit=0`.
2. `scripts/up.sh --apply`
   - Esperado: pide escribir `si`; luego MinIO, `terraform init` y `apply`, `kubectl apply` de `root` y la espera de Argo CD.
   - Termina con `LEVANTADO en N s` y `gate: CUMPLE` (N de 900 s o menos). Con `--yes` no pregunta.
3. Estado real:
   `kubectl --kubeconfig infra/terraform/envs/local/noc-tf.kubeconfig -n argocd get applications`
   - Esperado: `root` Synced/Healthy y `webhook-dev` Synced. `webhook-dev` puede estar Progressing o Degraded (limitación conocida; se investiga el 2026-12-05).

Criterio de "levantado": MinIO responde 200, `terraform apply` termina bien, `root` queda Synced y Healthy, y `webhook-dev` queda Synced.

## 4. Destruir

1. `scripts/down.sh`
   - Esperado: dry-run con el plan de 3 pasos y `exit=0`. Exige que MinIO responda: el estado vive ahí.
2. `scripts/down.sh --apply`
   - Esperado: pide `si`, ejecuta `terraform destroy` y comprueba con `kind get clusters` que `noc-tf` ya no existe. Termina con `DESTRUIDO en N s`.
3. `scripts/down.sh --apply --stop-minio` además detiene MinIO con `docker compose stop`. Nunca borra el volumen `minio-data`.

## 5. Códigos de salida

| Código | up.sh | down.sh | Qué hacer |
|---|---|---|---|
| 0 | Levantado | Destruido | Nada |
| 1 | Uso incorrecto o cancelado | Igual | Revisar los argumentos |
| 2 | Falta un comando, un `.env` o hay variables `MINIO_` | Falta un comando o el `.env` | Leer el mensaje |
| 3 | MinIO no responde 200 en 60 s | MinIO no responde | `docker compose` y logs de MinIO, filtrando secretos |
| 4 | Falló `terraform init` o `apply` | Falló `init` o `destroy` | Ver abajo |
| 5 | Argo CD no llegó al estado esperado en 300 s | `noc-tf` sigue existiendo tras el `destroy` | Diagnóstico con `kubectl` o `kind` |

Código 4, según el mensaje:
- `403 InvalidAccessKeyId`: el usuario o la clave del `.env` no coinciden con MinIO (runbook de MinIO, sección 7).
- `NoSuchBucket`: falta el bucket `tfstate` (sección 6).
- `412 PreconditionFailed` al bloquear el estado: hay otro `terraform` en curso (sección 14).

## 6. Pruebas del control (negativas)

Cada una se ejecutó el 2026-11-24 y salió como se esperaba:

| Prueba | Script | Resultado |
|---|---|---|
| `--yes` sin `--apply` | up y down | `exit=1`, sin cambios |
| Responder `no` a la confirmación | up y down | `exit=1`, sin cambios |
| Credenciales falsas en un `.env` de prueba | up y down | `403 InvalidAccessKeyId`, `exit=4`, sin cambios |
| MinIO detenido | down | `exit=3` |

## 7. Plan de retorno

- Deshacer `up`: `scripts/down.sh --apply`. Deshacer `down`: `scripts/up.sh --apply`. El estado de Terraform vive en el volumen de MinIO y sobrevive a ambos.
- Camino manual (si un script falla): runbook de MinIO, secciones 4 y 14, y `kubectl --kubeconfig infra/terraform/envs/local/noc-tf.kubeconfig apply -f gitops/bootstrap/root.yaml` para `root` (ADR-006).
- Quitar los scripts: revertir el PR. El camino manual sigue documentado.

## 8. Registro de ejecuciones

| Fecha y hora | Comando | Resultado | Tiempo |
|---|---|---|---|
| 2026-11-24 13:39 | `up.sh --apply --yes` desde cero | Levantado, `gate: CUMPLE` | 274 s (`apply` 132 s, Argo CD 140 s) |
| 2026-11-24 13:50 | `up.sh --apply --yes` repetido | Levantado, sin recrear | 7 s |
| 2026-11-24 13:50 | `down.sh --apply --yes` | Destruido | 9 s |
| 2026-11-24 13:58 | `down.sh --apply --yes --stop-minio` (sin clúster) | MinIO detenido | 2 s |
| 2026-11-24 13:58 | `down.sh` con MinIO parado | `exit=3` | 2 s |
| 2026-11-24 13:59 | `up.sh --apply --yes` con MinIO parado | Levantado, `gate: CUMPLE` | 140 s (`apply` 131 s, Argo CD 6 s) |
| 2026-11-24 14:03 | `down.sh --apply --yes` | Destruido | 8 s |

Las medidas son muestras sueltas, con las imágenes en la caché de Docker. La espera de Argo CD varió de 140 s a 6 s; la causa no está verificada.

## 9. Pendiente

- Código 5 de ambos scripts: sin probar.
- Arranque con la caché de Docker vacía: sin medir.
- Que el objeto de estado sobreviva al `stop` de MinIO: solo se comprobó que `terraform init` funciona tras reiniciarlo.
- `webhook-dev` Degraded en `noc-tf`: investigar el 2026-12-05.
- Endurecer el criterio de "levantado" (`webhook-dev` Healthy) después de esa investigación.