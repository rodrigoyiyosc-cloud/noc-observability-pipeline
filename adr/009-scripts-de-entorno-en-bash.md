# ADR-009: Scripts de entorno up/down en Bash, en scripts/

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-11-24 |
| Decide | Rodrigo Codoceo |
| Fecha de revisión | 2027-01-04 |

## Contexto

El plan maestro (semana 4) pide `up.ps1` y `down.ps1`: levantar clúster, Argo CD y estado remoto en menos de 15 minutos, y destruirlos. Todo el trabajo diario corre en Git Bash y WSL2, y los scripts que ya existen en `scripts/` son Bash (`check_env_shadow.sh`, `deploy_dev.sh`).

## Decisión

1. Los scripts de entorno son `scripts/up.sh` y `scripts/down.sh`, en Bash, y no `up.ps1` y `down.ps1`. Es una excepción al plan, decidida por Rodrigo.
2. Viven en `scripts/`, junto a los demás.
3. Ambos hacen dry-run por defecto, piden confirmación con `--apply`, no imprimen credenciales y usan los códigos de salida de su cabecera.

## Alternativas consideradas

- PowerShell, como pide el plan: obliga a mantener un segundo lenguaje para el mismo flujo, que ya corre en Bash.
- Makefile o Taskfile: agregan una herramienta más sin necesidad hoy.

## Consecuencias

- Gate de la semana 4 medido el 2026-11-24: `up` en 274 s y 140 s (dos muestras; el `apply` tardó 131–133 s y la espera de Argo CD varió entre 140 s y 6 s, causa sin verificar) y `down` en 9 s y 8 s. Imágenes en caché de Docker en ambas.
- No probado: el código de salida 5 de los scripts y un arranque con la caché de Docker vacía.
- `up.sh` y `down.sh` repiten las funciones `log`, `fail`, `minio_http_code` y `tf`. A la tercera repetición se extraen a una biblioteca (registro en `docs/toil.md`).
- Revisar esta decisión al abrir la pista de nube, si algún paso solo existe en PowerShell.

## Enlaces
- [Runbook de up y down](../docs/runbook-up-down.md)
- [Script up](../scripts/up.sh)
- [Script down](../scripts/down.sh)
- [ADR-005: Argo CD instalado con Terraform](005-argocd-instalado-con-terraform.md)
- [ADR-006: app-of-apps con selfHeal](006-argocd-app-of-apps-con-selfheal.md)
- [ADR-008: estado remoto en MinIO](008-minio-estado-remoto-fuera-del-cluster.md)
