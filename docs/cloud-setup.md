# Cuentas de nube: decisión, calendario y lista de verificación

Estado: **DIFERIDO por decisión del 2026-10-26**. Las cuentas se abren justo antes de su primer uso.

**Actualización 2026-11-20 (ADR-007):** la apertura de la cuenta AWS se pospone a la pista de nube. Los plazos por semana de este documento quedan reemplazados por el calendario del plan maestro v2. Regla vigente: abrir la cuenta justo antes del primer uso, con 2FA y alarma de presupuesto antes de crear recursos.

## Decisión

- Las cuentas de AWS, Azure y GCP se abren cerca de su primer uso práctico, no antes.
- **Motivo:** una cuenta de Azure abierta con antelación perdió sus créditos gratuitos por el paso del tiempo sin usarla.
- Es una excepción a la fila "Abrir cuentas AWS, Azure y GCP" de la Fase 0 del plan maestro (prevista para el 2026-10-23). El resto de la Fase 0 se cierra sin ella.
- Hasta la pista de nube el plan usa kind, GHCR, GitHub Actions y MinIO. Ningún entregable anterior a la pista de nube necesita una cuenta de nube.
- **Riesgo:** retrasos al abrir una cuenta (verificación de identidad o de pago). **Mitigación:** fecha límite de apertura 3 a 4 días antes del primer uso.
- **Reglas que no cambian:** alarma de presupuesto activa antes de crear cualquier recurso, y destrucción de todo recurso al terminar el día.

## Calendario de apertura

Fechas según el plan maestro; si el plan se mueve, se mueven estas.

| Nube | Primer uso práctico | Abrir a más tardar | Para qué se necesita |
|---|---|---|---|
| AWS | Pista de nube (desde 2026-05-24; antes si un proyecto lo pide; ADR-007) | 3 a 4 días antes del primer uso | Módulo `network`, rol OIDC para GitHub Actions, `terraform plan` en cada PR; después EKS y Lambda |
| Azure | Pista de nube (desde 2026-05-24; antes si un proyecto lo pide; ADR-007) | 3 a 4 días antes del primer uso | AKS y ACR por Terraform, credenciales federadas OIDC |
| GCP | Pista de nube (desde 2026-05-24; antes si un proyecto lo pide; ADR-007) | 3 a 4 días antes del primer uso | Un despliegue real (Cloud Run o GKE) con Workload Identity Federation |

El examen Terraform Associate no tiene fecha (ver `docs/terraform-associate-schedule.md`) y no necesita cuenta de nube.

## Lista de verificación por nube (completar al abrir)

Se repite para cada proveedor. No escribir aquí valores, claves ni identificadores de cuenta.

- [ ] Autenticación en dos pasos activada en la cuenta propietaria
- [ ] La cuenta propietaria o raíz no se usa para el trabajo diario
- [ ] Usuario o rol administrador para el trabajo diario, con autenticación en dos pasos
- [ ] Alarma de presupuesto con umbral definido y aviso por correo (verificada con una prueba)
- [ ] Sin claves de acceso de larga duración: el CI usa OIDC (en la pista de nube, ADR-007)
- [ ] Región o ubicación elegida y anotada
- [ ] Etiquetas de costo acordadas (por ejemplo, proyecto y entorno)
- [ ] Procedimiento de cierre del día: `terraform destroy` y revisión manual de que no quedan recursos que cobran por hora (balanceadores, NAT, volúmenes)

## Registro de apertura (completar al abrir)

| Nube | Fecha de apertura | Autenticación en dos pasos | Alarma de presupuesto (umbral y fecha) | Administrador no raíz | Observaciones |
|---|---|---|---|---|---|
| AWS | | | | | |
| Azure | | | | | |
| GCP | | | | | |

## A verificar en los sitios oficiales (no asumir)

Estos datos cambian y no están registrados aquí a propósito.

- Créditos o nivel gratuito de cada proveedor: monto, duración, desde cuándo cuenta el plazo y qué pasa al vencer.
- Medio de pago y verificación de identidad que exige cada uno, y cuánto puede tardar.
- Si un presupuesto o alarma solo avisa o también corta el gasto.
- Azure: la cuenta existente ya perdió los créditos. Confirmar qué opciones ofrece hoy el proveedor antes de contar con ellos.
- Precios por hora de EKS, NAT Gateway y balanceadores antes de la pista de nube.
