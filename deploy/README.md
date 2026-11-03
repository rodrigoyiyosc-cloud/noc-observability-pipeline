# deploy/

| Carpeta | Contenido |
|---|---|
| cluster/ | Config de kind y script de creación del clúster |
| base/ | Namespaces y recursos compartidos |
| apps/webhook/ | Manifiestos del webhook (ns dev) |
| apps/timescaledb/ | StatefulSet y Service de TimescaleDB |
| apps/grafana/ | Grafana con provisioning. `kubectl apply -k deploy/apps/grafana` aplica el Deployment y los 2 ConfigMaps. El PVC, Service, ServiceAccount, Ingress y Secret se aplican con `kubectl apply -f` sobre cada archivo (nunca `-f` sobre el Deployment) |
| _archive/ | Intentos descartados (solo referencia) |

Orden: `kubectl apply -f deploy/base/` → `-f deploy/apps/timescaledb/` → `-f deploy/apps/webhook/` → Grafana (primero los `-f` de pvc, serviceaccount, service e ingress, y el Secret; al final `kubectl apply -k deploy/apps/grafana`).

Secretos: copiar cada `*.yaml.example` a su nombre sin `.example` (git lo ignora), completar los valores y aplicarlo. Los valores reales nunca van al repo.