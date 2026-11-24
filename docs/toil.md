# Registro de toil

Toil es trabajo manual, repetitivo, automatizable y sin valor duradero. Una línea por evento repetido. Se revisa cada viernes.
A la tercera repetición se decide: automatizar o registrar por qué no.

| Fecha | Tarea | Minutos por vez | Veces | Decisión |
|---|---|---|---|---|
| 2026-11-16 | `git push gitlab main` tras cada merge (espejo manual) | [completar] | [completar] | Pendiente: decidir en la revisión del vie 20-nov |
| 2026-11-16 | `terraform apply` y `destroy` de noc-tf a mano | 0,6 (apply de 32 a 38 s) | [completar] | Automatizar con `up.sh` y `down.sh` (gate de la semana 4) |
| 2026-11-16 | `kubectl diff -k gitops/dev` tras cada merge para detectar deriva | 0,2 (10 s) | [completar] | No automatizar: Argo CD (#35, jue 19-nov) lo reemplaza. Revisar después de medir el tiempo de detección |
| 2026-11-17 | Definir `mark` y calcular a mano los T+ de las marcas (ejecuciones del runbook y simulacro) | [completar] | 4 | Automatizar con #29 (PM1-A7, vence 27-nov), en Bash. Medir antes |
| 2026-11-24 | Levantar y destruir `noc-tf` con `up.sh` y `down.sh` (antes: `terraform apply` y `destroy` a mano) | 2,3 a 4,6 (up, 140 a 274 s) y 0,15 (down, 8 a 9 s) | [completar] | Automatizado (ADR-009). Gate de la semana 4 cumplido. Runbook: docs/runbook-up-down.md |
| 2026-11-24 | Redefinir `mcx`, `mctf` y `tfx` en cada terminal nueva | [completar] | [completar] | Registrar; a la tercera vez, proponer un script de solo lectura |
| 2026-11-24 | `log`, `fail`, `minio_http_code` y `tf` repetidos en `up.sh` y `down.sh` | 0 | 2 | A la tercera repetición, extraer a una biblioteca (ADR-009) |