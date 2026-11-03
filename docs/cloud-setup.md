# Cuentas de nube: decisión, calendario y lista de verificación

Estado: **DIFERIDO por decisión del 2026-10-26**. Las cuentas se abren justo antes de su primer uso.

## Decisión

- Las cuentas de AWS, Azure y GCP se abren cerca de su primer uso práctico, no antes.
- **Motivo:** una cuenta de Azure abierta con antelación perdió sus créditos gratuitos por el paso del tiempo sin usarla.
- Es una excepción a la fila "Abrir cuentas AWS, Azure y GCP" de la Fase 0 del plan maestro (prevista para el 2026-10-23). El resto de la Fase 0 se cierra sin ella.
- Hasta la semana 5 el plan usa kind, GHCR, GitHub Actions y MinIO. Ningún entregable de las semanas 1 a 4 necesita una cuenta de nube.
- **Riesgo:** retrasos al abrir una cuenta (verificación de identidad o de pago). **Mitigación:** fecha límite de apertura 3 a 4 días antes del primer uso.
- **Reglas que no cambian:** alarma de presupuesto activa antes de crear cualquier recurso, y destrucción de todo recurso al terminar el día.

## Calendario de apertura

Fechas según el plan maestro; si el plan se mueve, se mueven estas.

| Nube | Primer uso práctico | Abrir a más tardar | Para qué se necesita |
|---|---|---|---|
| AWS | Semana 5 (23-nov a 12-dic) | Vie 20-nov | Módulo `network`, rol OIDC para GitHub Actions, `terraform plan` en cada PR; después EKS y Lambda |
| Azure | Semana 8 (desde 14-dic) | Vie 11-dic | AKS y ACR por Terraform, credenciales federadas OIDC |
| GCP | Semana 9 (desde 21-dic) | Vie 18-dic | Un despliegue real (Cloud Run o GKE) con Workload Identity Federation |

El examen Terraform Associate (lunes 23-nov) no necesita cuenta de nube.

## Lista de verificación por nube (completar al abrir)

Se repite para cada proveedor. No escribir aquí valores, claves ni identificadores de cuenta.

- [ ] Autenticación en dos pasos activada en la cuenta propietaria
- [ ] La cuenta propietaria o raíz no se usa para el trabajo diario
- [ ] Usuario o rol administrador para el trabajo diario, con autenticación en dos pasos
- [ ] Alarma de presupuesto con umbral definido y aviso por correo (verificada con una prueba)
- [ ] Sin claves de acceso de larga duración: el CI usa OIDC (AWS en la semana 5, Azure en la 8, GCP en la 9)
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
- Precios por hora de EKS, NAT Gateway y balanceadores antes de la semana 6.
