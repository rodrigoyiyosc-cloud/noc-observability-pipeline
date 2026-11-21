# ADR-007: Cambio de foco del plan hacia observabilidad e infraestructura

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-11-20 |
| Decide | Rodrigo Codoceo |
| Fecha de revisión | 2027-01-04 |

## Contexto

Cambia mi situación laboral y mi disponibilidad pasa de 8 h/día a 10–12 h/semana. El plan v1 priorizaba nube, CI/CD y certificaciones. El foco pasa a observabilidad e infraestructura.

## Decisión

1. Se adopta el plan maestro v2: Linux, observabilidad, SLO, incidentes, DR y retención primero; IA después; nube al final.
2. Las certificaciones (CKA, Terraform Associate, AWS SAA, PCA, OTCA) quedan en pausa hasta que el empleador defina cuáles pide o financia. El contenido ya ejecutado se mantiene en el repo.
3. Las cuentas de nube se abren justo antes de la pista de nube.
4. Se elimina el bloque diario de postulaciones. Las publicaciones pasan a una cada 2 semanas.
5. Nada del empleador ni de sus clientes entra al repo ni a las publicaciones.

## Alternativas consideradas

- Mantener el plan v1 con menos horas: descartada, retrasaría la observabilidad, que pasa a ser la prioridad.
- Mantener las certificaciones con fecha: descartada, sin presupuesto ni requisito del empleador.

## Consecuencias

- Positivas: el repo se alinea con el nuevo foco; menos deuda de certificaciones sin uso.
- Negativas: la nube y el CI/CD multi-nube se retrasan hasta mayo de 2027; CKA y Terraform Associate pierden ritmo.
- Riesgo: perder el hábito de práctica cronometrada. Mitigación: runbooks y simulacros dentro de los módulos.

## Enlaces

- [Excepción CKA](../docs/cka-schedule.md)
- [Excepción Terraform Associate](../docs/terraform-associate-schedule.md)
- [Cuentas de nube](../docs/cloud-setup.md)