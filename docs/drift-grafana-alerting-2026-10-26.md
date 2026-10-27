# Nota de drift: ConfigMap de alertas de Grafana (2026-10-26)

| Campo | Valor |
|---|---|
| Fecha | 2026-10-26 |
| Tipo | Drift de configuración (no es un incidente, sin impacto) |
| Entorno | Clúster kind `noc-local-cluster`, namespace `monitoring` |
| Relacionado | PM-001, acción PM1-A4 (detección de drift con Argo CD) |

## Hallazgo

Al verificar la reorganización de `deploy/`, `kubectl diff -k deploy/apps/grafana` dio código 1: el repo y el clúster no coincidían. El mismo diff sobre el layout original (`git archive HEAD`) también dio 1, así que el drift era previo a la reorganización.

## Causa

El ConfigMap vivo `grafana-provisioning-alerting-c5465d6t84` se aplicó desde archivos con fin de línea CRLF. El repo guarda LF (`git ls-files --eol`: `i/lf w/lf`, `.gitattributes` con `eol=lf`, `core.autocrlf=false`). El contenido es idéntico; solo cambian los bytes. Kustomize calcula el sufijo del nombre con los bytes, así que el repo generaba otro nombre (`k6552kcgm8`).

| Archivo | Bytes repo | Bytes vivo | CR en vivo |
|---|---|---|---|
| contact_points.yml | 1154 | 1154 | 0 |
| notification_policies.yml | 889 | 920 | 31 |
| alert_rules.yml | 6097 | 6261 | 164 |
| mute_timings.yml | 239 | 249 | 10 |

La diferencia de bytes es exactamente la cantidad de CR. El ConfigMap de datasources no tenía diferencias.

## Cambio ejecutado

`kubectl apply -k deploy/apps/grafana` el 2026-10-26, de 20:48:16 a 20:48:29 (13 s, Deployment con estrategia `Recreate`). Se creó el ConfigMap nuevo, datasources quedó sin cambios y el Deployment se actualizó. Plan de retorno: `kubectl rollout undo deployment/grafana -n monitoring`, válido mientras el ConfigMap viejo siguiera en el clúster.

## Verificación

- [x] `kubectl diff -k deploy/apps/grafana` devuelve 0
- [x] Pod `1/1`, 0 reinicios
- [x] Reglas (3), contact points (2), políticas y mute timing visibles en la interfaz
- [x] Logs: un único error, el del plugin de Elasticsearch (conocido, sin efecto)
- [x] Sin tickets duplicados en Jira tras el reinicio
- [x] ConfigMap viejo `c5465d6t84` eliminado

## Lecciones

- Nada avisó de la divergencia: el clúster y el repo estuvieron desalineados sin alertas.
- Comparar el texto con los fines de línea normalizados dice "igual" aunque el hash cambie. Para detectar este tipo de drift hay que comparar bytes (`wc -c`, `tr -cd '\r' | wc -c`).
- En Git Bash, `grep -c $'\r'` no es fiable (contó todas las líneas). Usar `tr`.

## Acciones

| ID | Tipo | Acción y criterio de cierre |
|---|---|---|
| D1 | detect | Cubierta por PM1-A4: Argo CD marca `OutOfSync` este tipo de divergencia. Cierre: demostrarlo en un simulacro y registrar el tiempo |
| D2 | prevent | Paso de CI que renderiza `kubectl kustomize deploy/apps/grafana` y valida con kubeconform. Cierre: el job falla ante un manifiesto o kustomization inválido |
