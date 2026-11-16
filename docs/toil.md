# Registro de toil

Toil es trabajo manual, repetitivo, automatizable y sin valor duradero. Una línea por evento repetido. Se revisa cada viernes.
A la tercera repetición se decide: automatizar o registrar por qué no.

| Fecha | Tarea | Minutos por vez | Veces | Decisión |
|---|---|---|---|---|
| 2026-11-16 | `git push gitlab main` tras cada merge (espejo manual) | [completar] | [completar] | Pendiente: decidir en la revisión del vie 20-nov |
| 2026-11-16 | `terraform apply` y `destroy` de noc-tf a mano | 0,6 (apply de 32 a 38 s) | [completar] | Automatizar con `up.sh` y `down.sh` (gate de la semana 4) |
| 2026-11-16 | `kubectl diff -k gitops/dev` tras cada merge para detectar deriva | 0,2 (10 s) | [completar] | No automatizar: Argo CD (#35, jue 19-nov) lo reemplaza. Revisar después de medir el tiempo de detección |