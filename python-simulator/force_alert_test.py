"""
force_alert_test.py — Inyecta telemetría degradada de forma sostenida
para disparar las 3 reglas de alerta de Grafana. Solo para testing.

Uso:
    python force_alert_test.py --minutes 5 --pg-dsn "postgresql://noc_user:secret@localhost:5432/noc"
"""

import argparse
import time
from datetime import datetime, timezone

import psycopg2

INSERT_SQL = """
INSERT INTO network_telemetry
    (ts, hostname, ip, role, severity, message, cpu_pct, latency_ms, packet_loss_pct, interface, iface_status, peer_ip)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

TARGET = ("core-rtr-01", "10.0.0.1", "core-router")


def run(minutes: int, dsn: str) -> None:
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()

    end_time = time.time() + (minutes * 60)
    print(f"Inyectando fallas en {TARGET[0]} por {minutes} minutos...")

    while time.time() < end_time:
        now = datetime.now(timezone.utc)
        cur.execute(
            INSERT_SQL,
            (
                now,
                TARGET[0], TARGET[1], TARGET[2],
                "CRITICAL",
                f"CRITICAL: {TARGET[0]} degradado - test forzado",
                96.5,      # cpu_pct > 85
                210.0,     # latency_ms > 150
                18.5,      # packet_loss_pct > 10
                "Gi0/0/0",
                "UP",
                "10.0.0.254",
            ),
        )
        print(f"[{now.strftime('%H:%M:%S')}] Registro CRITICAL insertado")
        time.sleep(10)

    cur.close()
    conn.close()
    print("Listo. Revisa Alerting > Alert rules en Grafana (puede tardar 1-2 min en pasar a Firing).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=5)
    parser.add_argument("--pg-dsn", required=True)
    args = parser.parse_args()
    run(args.minutes, args.pg_dsn)