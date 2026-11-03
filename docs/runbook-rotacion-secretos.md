# Runbook: rotación de secretos

| Campo | Valor |
|---|---|
| Alcance | Contraseñas y claves del laboratorio: Postgres (Docker y clúster), webhook, Grafana, Groq, Atlassian |
| Origen | PM-003, acción PM3-A2 (issue #30) |
| Última ejecución | 2026-11-02: `dev/timescaledb-secret` (procedimiento A, sin incidentes). 2026-10-28: rotación completa con Compose (procedimiento B, con las fallas de PM-003) |
| Regla de oro | Nunca imprimir ni pegar valores. Solo nombres, largos y hashes de 8 caracteres |
| Shell | Git Bash en Windows. Con `MSYS_NO_PATHCONV=1` delante de `docker exec` con rutas de Linux |

## 1. Antes de empezar (siempre)

1. **Terminal nueva.** Una terminal abierta antes de una rotación puede traer los valores viejos exportados (PM-003). Cierra las viejas y abre una nueva.
2. **El shell no debe tener secretos exportados.** Esperado: `0` en todas.
   ```bash
   for v in $(tr -d '\r' < .env | awk -F= '/^[A-Za-z_]/{print $1}'); do
     [ -n "$(printenv $v)" ] && echo "EN CONFLICTO: $v"
   done; echo "revision terminada"
   ```
   Si lista algo, `unset` esa variable antes de seguir. Un script que lo haga solo es la acción PM3-A3.
3. **Contexto correcto.** Esperado: `kind-noc-local-cluster`.
   ```bash
   unset KUBECONFIG; kubectl config current-context
   ```
4. **Inventario de consumidores.** Anota dónde vive cada valor: Secrets del clúster, `.env`, entorno de los contenedores Docker, ConfigMaps y el `docker-compose.yml`. Un consumidor olvidado deja de funcionar al revocar.
5. **Respaldo y plan de retorno.** Respaldo del `.env` fuera del repo y de la base antes de tocar nada. La clave vieja no se revoca hasta el final.
   ```bash
   cp .env "$HOME/env-backup-$(date +%F)" && chmod 600 "$HOME/env-backup-$(date +%F)"
   docker exec timescaledb pg_dump -U noc_user -d noc -Fc > "$HOME/noc-backup-$(date +%F).dump"
   ls -l "$HOME"/noc-backup-*.dump | tail -1
   ```
   Esperado: archivo con tamaño mayor que 0. El aviso de `continuous_agg` de TimescaleDB es normal. La restauración de este dump no está probada: requiere `timescaledb_pre_restore()` y `timescaledb_post_restore()`.

## 2. Generar valores sin imprimirlos

```bash
NEW_VAL=$(openssl rand -hex 16); echo "largo: ${#NEW_VAL}"      # 32
NEW_TOKEN=$(openssl rand -hex 32); echo "largo: ${#NEW_TOKEN}"  # 64
read -rsp "Clave de tercero (sin eco): " NEW_EXT; echo; echo "largo: ${#NEW_EXT}"
```

Usa `hex` para evitar `@ / : #` en contraseñas que van dentro de una DSN. Usa la misma terminal hasta terminar.

## 3. Orden general

1. Cambiar el valor en el origen (la base, la consola del servicio) **sin revocar el viejo**.
2. Actualizar el Secret o el `.env`.
3. Reiniciar los consumidores. Un cambio de ConfigMap o Secret no se activa hasta reiniciar el pod, y `rollout undo` no lo revierte.
4. Verificar con hash y con una prueba real.
5. Revocar el valor viejo.
6. Limpiar variables y respaldos del shell.

## 4. Procedimiento A: Secret del StatefulSet de Postgres del clúster (probado el 2026-11-02)

`POSTGRES_PASSWORD` solo se lee al inicializar un volumen vacío. Cambiar el Secret no cambia la clave de una base existente: hay que hacer `ALTER USER` y después recrear el Secret.

1. Lectura previa, sin cambios: claves y largos del Secret, y tablas existentes.
   ```bash
   kubectl -n dev get secret timescaledb-secret -o go-template='{{range $k,$v := .data}}{{$k}}{{"\t"}}{{len (base64decode $v)}}{{"\n"}}{{end}}'
   kubectl -n dev exec sts/timescaledb -- sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
   ```
2. `ALTER USER` por stdin, para que la clave no aparezca en la lista de procesos. Esperado: `ALTER ROLE`.
   ```bash
   printf "%s" "$NEW_VAL" | kubectl -n dev exec -i sts/timescaledb -- sh -c 'read -r NP; printf "ALTER USER \"%s\" PASSWORD '"'"'%s'"'"';\n" "$POSTGRES_USER" "$NP" | psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
   ```
3. Recrear el Secret conservando usuario y base.
   ```bash
   DB_V=$(kubectl -n dev get secret timescaledb-secret -o go-template='{{.data.POSTGRES_DB | base64decode}}')
   USER_V=$(kubectl -n dev get secret timescaledb-secret -o go-template='{{.data.POSTGRES_USER | base64decode}}')
   kubectl -n dev create secret generic timescaledb-secret \
     --from-literal=POSTGRES_DB="$DB_V" --from-literal=POSTGRES_USER="$USER_V" \
     --from-literal=POSTGRES_PASSWORD="$NEW_VAL" --dry-run=client -o yaml | kubectl apply -f -
   unset DB_V USER_V
   ```
4. Reiniciar el pod. El volumen se conserva.
   ```bash
   kubectl -n dev rollout restart sts/timescaledb && kubectl -n dev rollout status sts/timescaledb
   ```
5. Verificar. Esperado: dos hashes iguales y un `1`. El login va por TCP (`-h 127.0.0.1`), que exige clave.
   ```bash
   printf %s "$NEW_VAL" | sha256sum | cut -c1-8
   kubectl -n dev exec sts/timescaledb -- sh -c 'printf %s "$POSTGRES_PASSWORD" | sha256sum | cut -c1-8'
   kubectl -n dev exec sts/timescaledb -- sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select 1"'
   ```

## 5. Procedimiento B: contraseña de la base Docker, `.env` y consumidores (corregido, pendiente de ejecutar de nuevo)

Se ejecutó el 2026-10-28 y falló por variables heredadas del shell (PM-003). Esta versión añade las comprobaciones que faltaron; aún no se ha repetido completa.

1. Cumplir la sección 1 completa.
2. Reescribir el `.env` sin imprimir valores. Los nombres de variable son los de tu `.env`; ajusta la lista.
   ```bash
   export NEW_VAL
   tr -d '\r' < .env | awk 'BEGIN{FS=OFS="="} $1=="PG_PASSWORD"{$0="PG_PASSWORD=" ENVIRON["NEW_VAL"]} {print}' > .env.new && mv .env.new .env
   tr -d '\r' < .env | awk -F= '$1=="PG_PASSWORD"{print $1, length($0)-length($1)-1}'
   ```
   Si el `PG_DSN` lleva la contraseña dentro, hay que reescribirlo también, por sustitución del valor viejo por el nuevo. Comprueba su largo después.
3. **Antes de recrear nada, mirar lo que Compose resolverá.** Esperado: el largo nuevo en `PG_PASSWORD` y en cada `PG_DSN`.
   ```bash
   docker compose config | awk '/^ *(PG_PASSWORD|PG_DSN):/{v=$0; sub(/^ *[A-Z_]+: */,"",v); gsub(/"/,"",v); print $1, length(v)}'
   ```
   Si los largos son los viejos, el shell tiene variables exportadas que pisan al `.env`: `unset` y repetir.
4. `ALTER USER` en la base Docker por stdin.
   ```bash
   printf "ALTER USER noc_user PASSWORD '%s';\n" "$NEW_VAL" | docker exec -i timescaledb psql -U noc_user -d noc
   ```
5. Parchear los Secrets del clúster que llevan la contraseña (`dev/webhook-secret` y `monitoring/grafana-provisioning-secret`), conservando las demás claves del Secret `webhook-secret`. Verificar los largos con el template de `kubectl` de la sección 4.
6. Recrear los consumidores, sin tocar la base: `docker compose up -d --force-recreate --no-deps <servicios>` y `kubectl rollout restart` de `webhook-service` y `grafana`.
7. Verificar: `docker compose ps` sin `Restarting`, `/ready` 200 en el webhook del clúster y en el de Docker, y Save & test de las dos Grafana.

## 6. Procedimiento C: claves de terceros (Groq, Atlassian) y token del webhook

1. Crear la clave nueva en la consola del servicio, sin revocar la vieja.
2. Cargarla en `.env` y en el Secret del clúster, y recrear los consumidores como en la sección 5.
3. Comparar el hash dentro de cada consumidor con el esperado (8 caracteres).
   ```bash
   printf %s "$NEW_EXT" | sha256sum | cut -c1-8
   docker exec webhook_service sh -c 'printenv NOMBRE_DE_LA_VARIABLE | tr -d "\n" | sha256sum | cut -c1-8'
   kubectl -n dev exec deploy/webhook-service -- sh -c 'printenv NOMBRE_DE_LA_VARIABLE | tr -d "\n" | sha256sum | cut -c1-8'
   ```
4. Hacer una llamada real de solo lectura con la clave nueva (por ejemplo, listar modelos en Groq o consultar `/myself` en Jira) y comprobar el código 200. El largo no sirve: la clave vieja y la nueva miden lo mismo.
5. Solo con el hash coincidente y el 200, revocar la clave vieja.
6. Para el token del webhook: la prueba sin crear tickets es un `POST` con un JSON inválido y el token nuevo. Esperado: `400`. Sin token: `401`.

## 7. Cierre

```bash
unset NEW_VAL NEW_TOKEN NEW_EXT
rm "$HOME/env-backup-$(date +%F)"
```

Cierra las terminales abiertas antes de la rotación. El dump de la base se borra cuando todo esté estable. Anota la hora de cada paso para el post-mortem si algo falló.

## 8. Errores conocidos

| Síntoma | Causa | Qué hacer |
|---|---|---|
| Contenedores en `Restarting` tras recrear, con `password authentication failed` | El shell exporta variables viejas y Compose las prioriza sobre el `.env` | `unset` y `docker compose config` antes de recrear |
| `docker compose up -d` no recrea un servicio | Compose no vio cambios en su configuración | `--force-recreate --no-deps` del servicio, después de verificar con `docker compose config` |
| Un pod sigue con la clave vieja tras cambiar el Secret | Un cambio de Secret o ConfigMap no se aplica hasta reiniciar el pod | `kubectl rollout restart` |
| `rollout undo` no devolvió la clave | Los Secrets y ConfigMaps no forman parte del Deployment | Reaplicar el Secret correcto |
| El Secret de Postgres cambió y la base sigue con la clave vieja | `POSTGRES_PASSWORD` solo se usa al inicializar un volumen vacío | `ALTER USER` dentro de la base |
| El largo de la clave nueva y la vieja coincide y no se distingue | El largo no identifica el valor | Comparar hashes de 8 caracteres y hacer una llamada real |
| Falla la conexión con una DSN | La contraseña lleva `@ / : #` | Generar con `openssl rand -hex` |