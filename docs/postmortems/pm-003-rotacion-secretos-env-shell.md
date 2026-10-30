# PM-003: rotación de secretos con variables heredadas en el shell

| Campo | Valor |
|---|---|
| Fecha | 2026-10-28 (ventana ~18:35) a 2026-10-29 (cierre 11:05), hora Santiago UTC-3 |
| Tipo | Cambio planificado (rotación de secretos) que degradó el laboratorio |
| Entorno | Docker Compose local y clúster kind `noc-local-cluster` (namespaces `dev` y `monitoring`) |
| Servicios afectados | `simulator-*` (3), `webhook_service` (Docker), `jupyter_ml`, `grafana` (Docker) |
| Autor | Rodrigo Codoceo |
| Estado | Cerrado; acciones abiertas (ver sección 10) |
| Formato | SREW cap. 10, sin culpa |
| Marco | ITIL v4: Gestión de la seguridad de la información y Gestión de cambios |

## 1. Resumen

Se rotaron `GROQ_API_KEY`, `JIRA_API_TOKEN`, `NOC_WEBHOOK_TOKEN` y `PG_PASSWORD`, porque se habían pegado en chats anteriores. Tras actualizar el `.env`, los Secrets del clúster y la contraseña en la base, los contenedores de Docker Compose siguieron usando los valores viejos. Los simuladores y el webhook Docker quedaron en reinicio constante contra Postgres, y después el webhook Docker rechazó el token nuevo. La causa fue que las terminales de VS Code abiertas antes de la rotación tenían exportadas las variables viejas, y Compose da prioridad al entorno del shell sobre el `.env`.

## 2. Impacto

- Entorno de laboratorio: sin usuarios externos ni SLA.
- Simuladores (3) y webhook Docker en bucle de reinicio desde 18:43 hasta las 19:02 del 28-oct (`password authentication failed for user "noc_user"`).
- Webhook Docker con 401 al token nuevo desde 19:09 del 28-oct hasta la mañana del 29-oct (verificado a las 10:23).
- Hueco de telemetría en `network_telemetry` mientras los simuladores no escribían: **no medido**. Al 29-oct 10:25 las filas crecían (288.540 a 289.539 en ~4 min).
- Alertas de la Grafana de Docker hacia el webhook durante el 401: **no verificado**.
- Sin pérdida de datos: `timescaledb` no se recreó y su volumen quedó intacto.

## 3. Línea de tiempo (hora local)

| Hora | Evento |
|---|---|
| 28-oct 17:44 | Inicio de P0: inventario de secretos (`PG_PASSWORD` de 6 caracteres en 5 lugares) |
| 18:25 | Respaldo de la base (dump de 1,5 MB) y del `.env` |
| ~18:35 | Ventana: `.env` reescrito, Secrets del clúster, `ALTER USER`, reinicios y `docker compose up -d` |
| 18:43 | **DETECTADO:** simuladores en `Restarting` |
| 18:47 | Log: `password authentication failed for user "noc_user"` |
| 18:52 | `--force-recreate` sin efecto: el `PG_DSN` seguía con contraseña de 6 caracteres |
| 18:56 | **CAUSA** (probada con `docker compose config` y `printenv`): `.env` correcto (32 y 82), pero el shell exportaba `PG_PASSWORD` (6) y `PG_DSN` (56) |
| 19:02 | **RESUELTO (base):** `unset` y recreación; 8 contenedores `Up`, `/ready` 200 |
| 19:09 | Webhook Docker devuelve 401 al token nuevo; el shell también tenía `NOC_WEBHOOK_TOKEN` y otras |
| 29-oct 10:23 | Variables quitadas y servicios recreados: 400 con el token nuevo, Save & test OK en ambas Grafana |
| 10:32 a 10:50 | Hashes de Groq y Jira coinciden en los consumidores; prueba 200 y 200 con las claves nuevas; origen identificado (`python.terminal.useEnvFile`) |
| 10:50 a 11:00 | Revocación de las claves viejas de Groq y Atlassian |
| 11:05 | `useEnvFile` en `false`; terminal nueva sin secretos; Compose resuelve el `.env` |

## 4. Detección

- `docker compose ps`: simuladores en `Restarting (1)` y el webhook con tiempo de vida de segundos.
- `docker logs` de un simulador: error de autenticación de Postgres.
- La detección fue **manual**: ninguna alerta avisó. El 401 del webhook Docker se vio porque se probó con el token nuevo antes de revocar.

## 5. Causa raíz

Las terminales de VS Code abiertas antes de la rotación tenían exportadas `PG_PASSWORD`, `PG_DSN`, `NOC_WEBHOOK_TOKEN`, `GROQ_API_KEY`, `JIRA_API_TOKEN`, `JIRA_USER` y `JIRA_URL` con valores viejos. Docker Compose da prioridad a las variables del shell sobre el `.env`, así que resolvió los valores viejos y `docker compose up -d` no detectó cambios en los simuladores.

El origen de la inyección: la opción `python.terminal.useEnvFile` carga el `.env` en cada terminal al abrirla. Una terminal nueva ya traía los valores correctos, lo que lo confirmó.

Factor contribuyente: el procedimiento no incluía abrir una terminal limpia ni correr `docker compose config` antes de recrear contenedores. Además, los largos de la clave vieja y la nueva coinciden, así que comparar largos no detecta este error.

## 6. Resolución

1. `unset` de las variables heredadas en la terminal.
2. `docker compose config` para ver lo que resuelve Compose (`PG_PASSWORD: 32`, DSN con largos nuevos).
3. `docker compose up -d --force-recreate --no-deps` de los consumidores, sin tocar `timescaledb`.
4. Verificación: `/ready` 200, token nuevo con 400 en ambos webhooks, hashes de 8 caracteres iguales a los esperados y llamada real a Groq y Jira con 200 y 200.
5. Revocación de las claves viejas solo después de esas pruebas.
6. `python.terminal.useEnvFile` en `false` (cierre del origen).

| Métrica | Valor |
|---|---|
| Tiempo hasta detectar (MTTD) | ~8 min (desde ~18:35 hasta 18:43) |
| Detección a causa probada | 13 min (18:43 a 18:56) |
| Detección a servicio de base restaurado | 19 min (18:43 a 19:02) |
| Token del webhook Docker restaurado | Mañana del 29-oct (verificado 10:23) |

## 7. Qué salió bien

- Inventario de todos los consumidores antes de tocar nada.
- Respaldo del `.env` y de la base antes de la ventana, y plan de retorno definido.
- Ningún valor secreto se imprimió: solo largos y hashes de 8 caracteres.
- Las claves viejas no se revocaron hasta probar las nuevas con hash y con una llamada real.
- La causa se probó con un comando (`docker compose config` y `printenv`) antes de actuar.

## 8. Qué salió mal

- No se corrió `docker compose config` antes de recrear contenedores; habría mostrado el problema antes de la ventana.
- Se asumió que `docker compose up -d` aplicaba el `.env` nuevo.
- La primera hipótesis fue errónea (contenedor sin recrear) y los largos esperados del `PG_DSN` estaban mal calculados: costó unos 9 minutos.
- No se registró la hora exacta del `ALTER USER`.
- El webhook Docker siguió con el token viejo hasta el día siguiente porque la recreación quedó pendiente de la primera pasada.

## 9. Dónde hubo suerte

- Las claves viejas seguían activas mientras los consumidores usaban valores desfasados, así que había vía de retorno.
- `timescaledb` no se recreó y su volumen estaba intacto.
- Fue laboratorio: sin usuarios, sin SLA y sin alertas críticas dependiendo del webhook.

## 10. Acciones correctivas

| ID | Acción | Tipo | Prioridad | Responsable | Criterio de cierre | Fecha / estado |
|---|---|---|---|---|---|---|
| PM3-A1 | Desactivar `python.terminal.useEnvFile` | prevent | P1 | Rodrigo | Terminal nueva con 0 secretos | **Cerrada 2026-10-29 11:05** |
| PM3-A2 | Runbook de rotación: terminal limpia, inventario, `docker compose config`, hash antes de revocar, revocar al final | prevent | P1 | Rodrigo | `docs/runbook-rotacion-secretos.md` ejecutado al rotar `dev/timescaledb-secret` | Issue #30. Vence 2026-11-03 |
| PM3-A3 | Script que lista variables del shell que pisan al `.env`, para correr antes de `compose up` | detect | P2 | Rodrigo | Script en `scripts/` probado con una variable falsa | Issue #31. Vence 2026-11-06 |
| PM3-A4 | Rotar `dev/timescaledb-secret` (6 caracteres) y reemplazar la clave de Grafana Docker (8 caracteres) por una larga | mitigate | P1 | Rodrigo | Valores nuevos aplicados y verificados con el runbook de A2 | Issue #27. Vence 2026-11-02 |
| PM3-A5 | Mover Postgres al clúster para reducir copias de la contraseña (hoy 5 lugares) | prevent | P3 | Rodrigo | Un solo Secret como fuente | Issue #32. Backlog. Unificar con PM2-A2 |

Las fechas de vencimiento, el tipo y la prioridad son propuestas: ajústalas si no calzan.

## 11. ITIL v4 (resumen)

- **Gestión de la seguridad de la información:** rotación de credenciales expuestas (secciones 1 y 6).
- **Gestión de cambios:** el cambio no verificó la configuración activa antes de aplicar (secciones 5 y 8).
- **Mejora continua:** runbook, script de detección y limpieza del origen (sección 10).