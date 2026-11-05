# ADR-002: promoción por PR con GITHUB_TOKEN, digest en vez de tag, prod promueve lo que dev probó

| Campo | Valor |
|---|---|
| Estado | Aceptada (el mecanismo A queda sujeto a la prueba única del PR 2) |
| Fecha | 2026-11-04 |
| Decide | Rodrigo Codoceo |
| Fecha de revisión | 2026-12-04 |

## Contexto

- `main` está protegida (ADR-001): el pipeline no puede hacer push directo.
- Hasta Argo CD (#35) no hay consumidor automático de `gitops/`.
- Los builds de la imagen no son reproducibles: construir dos veces el mismo commit da digests distintos. Se comprobó con `sha-5bb54a1`, cuyo tag apuntaba a un digest distinto del que registró el primer log de CI.

## Decisión

1. `gitops/dev` y `gitops/prod` viven en este repo. La imagen se fija por digest, nunca solo por tag.
2. El digest que se promueve sale del job que publica, y publicar no sobrescribe un `sha-<7>` que ya existe.
3. El pipeline abre un PR hacia `main` con GITHUB_TOKEN que cambia solo la línea `digest:`. Los checks se lanzan con `workflow_dispatch` sobre la rama del PR y el PR se fusiona con auto-merge.
4. Un tag `vX.Y.Z` (anotado, creado a mano) no reconstruye: agrega la etiqueta a la imagen ya publicada.
5. Prod promueve el digest que figura en `gitops/dev` en el commit del tag, y solo si `webhook_service/` no cambió entre el commit de origen de esa imagen y el tag.
6. Mientras no exista Argo CD, el consumidor de `gitops/dev` es `scripts/deploy_dev.sh`, solo desde `main` sincronizada.

## Alternativas descartadas

- Bypass del ruleset para Actions: la lista de bypass no ofrece GitHub Actions, solo roles, apps y deploy keys. Implicaría una llave privada con escritura sin PR ni checks.
- Repo separado `noc-gitops`: contradice la regla de un solo repo y el Argo CD de la semana 4. Solo como excepción documentada con fecha de revisión.
- PAT fine-grained: excepción documentada solo si falla la prueba única de A.

## Consecuencias

- `gitops/prod` queda "sin desplegar, validado solo con kubeconform".
- Activar "Allow GitHub Actions to create and approve pull requests" tiene un riesgo (ver SEC-003 en `docs/security-exceptions.md`).
- Revertir exige `kubectl rollout undo` y después `git revert` del commit de promoción.
