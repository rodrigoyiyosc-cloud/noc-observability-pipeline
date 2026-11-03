# ADR-001: una sola rama principal (`main`) protegida

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-11-03 |
| Decide | Rodrigo Codoceo |
| Fecha de revisión | 2026-12-04 |

## Contexto

- Hasta hoy el repo usaba una rama de trabajo (`kubernetes`) y `main` como rama por defecto, con promociones por PR.
- La rama por defecto llegó a quedar 78 commits atrás y con el CI en rojo (workflow antiguo), y era justo lo que ve primero quien revisa el repo.
- Cada promoción con merge commit deja a `main` con un commit que la rama de trabajo no tiene, y obliga a un fast-forward manual para igualarlas.
- `kubernetes` es el nombre de una fase terminada, y el plan sigue con CI/CD, Terraform y nubes.
- Hay un solo mantenedor.

## Decisión

`main` es la única rama de larga vida y está protegida: los cambios entran solo por PR desde ramas cortas (`docs/...`, `ci/...`, `security/...`), con los checks de CI obligatorios y sin force-push ni borrado. La rama `kubernetes` se retira cuando esté contenida en `main`.

## Consecuencias

- Desaparecen la rutina de promoción y el fast-forward de alineación.
- Cada merge a `main` publica una imagen en GHCR, porque el paso corre en cada `push`. El versionado semántico de CI/CD II decidirá cuándo y con qué etiqueta se publica.
- Un cambio roto en `main` queda visible de inmediato. Se mitiga con checks obligatorios y `git revert`.
- GitLab sigue siendo un espejo manual: `git push gitlab main` después de cada merge.
- Excepción al flujo del plan, que decía "PR hacia `kubernetes`": desde hoy es "PR hacia `main`".

## Alternativas descartadas

- Mantener dos ramas con promociones periódicas: más pasos y más oportunidades de desalineación para un solo mantenedor.
- Una sola rama sin protección: un push directo roto llegaría a la rama visible sin pasar por el CI.
