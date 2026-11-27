# Registro de toil

Toil es trabajo manual, repetitivo, automatizable y sin valor duradero. Una línea por evento repetido. Se revisa cada viernes.
A la tercera repetición se decide: automatizar o registrar por qué no.

| Fecha | Tarea | Minutos por vez | Veces | Decisión |
|---|---|---|---|---|
| 2026-11-16 | `git push gitlab main` tras cada merge (espejo manual) | sin medir | 8 o más desde 2026-11-24 (PR #87, #88, #89, #90, #91, #93, #96, #97) | Automatizar con scripts/post_merge.sh (dry-run por defecto), sábado 2026-12-05 en la holgura. Medir los minutos antes |
| 2026-11-16 | `terraform apply` y `destroy` de noc-tf a mano | 0,6 (apply de 32 a 38 s) | sin medir | Automatizar con `up.sh` y `down.sh` (gate de la semana 4) |
| 2026-11-16 | `kubectl diff -k gitops/dev` tras cada merge para detectar deriva | 0,2 (10 s) | sin medir | No automatizar: Argo CD (#35, jue 19-nov) lo reemplaza. Revisar después de medir el tiempo de detección |
| 2026-11-17 | Definir `mark` y calcular a mano los T+ de las marcas (ejecuciones del runbook y simulacro) | sin medir | 4 | Automatizado con scripts/lab-marks.sh (#29, PR #97). Antes: sin medir. Después: medir en el próximo simulacro |
| 2026-11-24 | Levantar y destruir `noc-tf` con `up.sh` y `down.sh` (antes: `terraform apply` y `destroy` a mano) | 2,3 a 4,6 (up, 140 a 274 s) y 0,15 (down, 8 a 9 s) | sin medir | Automatizado (ADR-009). Gate de la semana 4 cumplido. Runbook: docs/runbook-up-down.md |
| 2026-11-24 | Redefinir `mcx`, `mctf` y `tfx` en cada terminal nueva | sin medir | sin medir | Registrar; a la tercera vez, proponer un script de solo lectura |
| 2026-11-24 | `log`, `fail`, `minio_http_code` y `tf` repetidos en `up.sh` y `down.sh` | 0 | 2 | A la tercera repetición, extraer a una biblioteca (ADR-009) |
| 2026-11-27 | CVE de la imagen base Debian bloquea el CI (3 casos: zlib1g 2026-11-07; apt/libapt-pkg7.0 2026-11-05; libzstd1 2026-11-25) | Sin medir | 3 | No automatizar. Reducir superficie con una imagen menor en #86 (2026-12-05) y medir hallazgos de la base antes y después.|

Excepción 2026-11-27: `scripts/lab-marks.sh` se valida con `scripts/test_lab_marks.sh` (29 pruebas) y con uso real en simulacros. Revisión de lectura del código: 2026-12-12.