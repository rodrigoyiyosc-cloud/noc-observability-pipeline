# ADR-007: Cambio de foco del plan hacia observabilidad e infraestructura

- Fecha: 2026-11-20
- Estado: aceptado
- Revisión: 2027-01-04

## Contexto
Desde el 2026-12-02 Cambia mi situación laboral y mi disponibilidad pasa de 8 h/día a 10–12 h/semana. El plan v1 priorizaba nube, CI/CD y certificaciones.

## Decisión
1. Se adopta el plan maestro v2: Linux, observabilidad, SLO, incidentes, DR y retención primero; IA después; nube al final.
2. Las certificaciones (CKA, Terraform Associate, AWS SAA, PCA, OTCA) quedan en pausa hasta que el empleador defina cuáles pide o financia. El contenido ya ejecutado se mantiene en el repo.
3. La cuenta AWS se abre justo antes de la pista de nube.
4. Se elimina el bloque diario de postulaciones. Las publicaciones pasan a una cada 2 semanas.
5. Nada del empleador ni de sus clientes entra al repo, a las publicaciones ni al chat.

## Alternativas consideradas
- Mantener el plan v1 con menos horas: descartada, retrasaría la observabilidad, que es lo que pide el puesto.
- Mantener las certificaciones con fecha: descartada, sin presupuesto ni requisito del empleador.

## Consecuencias
- Positivas: el repo muestra lo que el puesto exige; menos deuda de certificaciones sin uso.
- Negativas: la nube y CI/CD multi-nube se retrasan hasta mayo-2027; CKA y Terraform Associate pierden ritmo.
- Riesgo: perder el hábito de práctica cronometrada. Mitigación: runbooks y simulacros dentro de los módulos.

## Enlaces
- docs/cka-schedule.md · docs/terraform-associate-schedule.md · docs/cloud-setup.md