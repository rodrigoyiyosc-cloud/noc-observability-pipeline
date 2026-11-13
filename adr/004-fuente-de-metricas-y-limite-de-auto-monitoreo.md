# ADR-004: kube-state-metrics y Prometheus como fuente de alertas del clúster, y el límite de auto-monitoreo del webhook

| Campo | Valor |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-11-13 |
| Decide | Rodrigo Codoceo |
| Fecha de revisión | 2026-12-04 |

## Contexto

- PM-001 (PM1-A5) y PM-002 (PM2-A1) pedían una alerta de pod no listo que avisara sin depender de que alguien mirara `kubectl get pods`.
- El 2026-11-10 dev estuvo en 0/1 porque el contenedor `timescaledb` de Docker estaba detenido, y solo se notó al revisar a mano.
- En el clúster no había fuente de métricas de estado de pods. El único datasource de Grafana era TimescaleDB.
- El webhook es a la vez el destino de las alertas y uno de los pods vigilados. Según `webhook_service/main.py`, `/ready` falla (503) si Postgres cae, y `/alert` necesita Postgres para guardar la alerta y deduplicar.

## Decisión

1. Se instalan en `monitoring`, por `kubectl apply -k`, **kube-state-metrics v2.20.0** y **Prometheus v3.13.5** (LTS), ambos con la imagen fijada por digest.
2. Prometheus raspa kube-state-metrics cada 30 s, guarda 24 h en un `emptyDir` de 1Gi y no tiene autenticación dentro del clúster.
3. Grafana lee Prometheus con el datasource `Prometheus-NOC` (no predeterminado, no editable). La regla "Pod No Listo (dev)" va en el grupo `k8s-state-alerts`, con `for: 2m` y `severity: critical`, y usa `max by (namespace, pod)` para que el webhook deduplique por nombre de pod.
4. Se mantiene el camino existente Grafana → webhook → Jira. No se agrega Alertmanager.
5. `noDataState: NoData`: si kube-state-metrics deja de reportar, la regla debe avisar y no fallar en silencio (diseñado, aún sin probar).
6. **Límite aceptado:** una alerta sobre el propio webhook no puede llegar por el webhook. El simulacro de #36 usó un pod de prueba en `dev`.

## Alternativas descartadas

- PVC para Prometheus: no se necesita historial para alertar sobre el estado actual. Si el pod se reinicia, se pierde hasta 24 h de series.
- Alertmanager propio: ya existe el camino Grafana → webhook → Jira, con deduplicación por huella.
- Alertar sobre `/ready` con una sonda externa: agrega un componente más; las métricas de estado cubren pods no listos de cualquier causa.

## Consecuencias

- Simulacro del 2026-11-13: pod de prueba en `CrashLoopBackOff` creado a las 01:36:55; Pending a +35 s; Firing a +2 min 35 s; llegada al webhook a +2 min 45 s con el token vigente; ticket NOC-865 creado, deduplicado (comentarios cada 2 min mientras persiste) y cerrado al resolverse.
- El criterio original de PM2-A1 (alerta disparada con Postgres detenido y recibida en el webhook) no se puede cumplir con este diseño. Se cerró con el pod de prueba; el cambio de criterio queda registrado aquí.
- Si cae el único pod del webhook, nadie recibe aviso por este camino. Mitigación posible (sin decidir): un segundo punto de contacto que no dependa del webhook.
- Cada notificación de un problema persistente agrega un comentario al ticket (cada ~2 min con la configuración actual de la ruta crítica).
- Sin cubrir: reinicios por `OOMKilled` (PM2-A7, incremento B3) y la prueba de `NoData` con kube-state-metrics detenido.
- Retorno: `kubectl delete -k deploy/apps/prometheus` y `kubectl delete -k deploy/apps/kube-state-metrics`, y quitar el datasource y la regla de `deploy/apps/grafana`.