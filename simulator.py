"""
simulator.py — Bucle principal del generador de logs de red.

Uso:
    # Flat-file sinks
    python simulator.py --fmt csv
    python simulator.py --fmt jsonl --interval 0.5

    # PostgreSQL/TimescaleDB sink
    python simulator.py --fmt postgres --pg-dsn "postgresql://noc_user:secret@localhost:5432/noc"

    # Variables de entorno (alternativa al DSN en CLI)
    export PG_DSN="postgresql://noc_user:secret@localhost:5432/noc"
    python simulator.py --fmt postgres

    # Opciones comunes
    python simulator.py --fmt postgres --interval 2 --batch 3 --count 100
"""

import argparse
import logging
import os
import random
import signal
import sys
import time
from pathlib import Path

from config import DEVICES
from log_builder import build_log_record
from writer import get_writer, init_pg_pool, close_pg_pool

# ── Logger de la aplicación ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SIM] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Salida limpia con Ctrl+C ──────────────────────────────────────────────────
_running = True

def _handle_sigint(sig, frame):
    global _running
    log.info("SIGINT recibido — cerrando el simulador.")
    _running = False

signal.signal(signal.SIGINT, _handle_sigint)


# ── Generación de un batch de N eventos ──────────────────────────────────────
def generate_batch(n: int = 1) -> list[dict]:
    return [build_log_record(random.choice(DEVICES)) for _ in range(n)]


# ── Bucle principal ───────────────────────────────────────────────────────────
def run_loop(
    output_path: Path | None,
    fmt: str,
    interval: float,
    count: int | None,
    batch_size: int,
) -> None:
    writer    = get_writer(fmt)
    generated = 0

    sink_label = str(output_path) if output_path else "PostgreSQL/TimescaleDB"
    log.info(f"Iniciando simulador → {sink_label} [{fmt.upper()}]")
    log.info(f"Intervalo: {interval}s | Batch: {batch_size} | Límite: {count or '∞'}")

    while _running:
        records = generate_batch(batch_size)

        for record in records:
            try:
                # Los sinks de archivo usan output_path; postgres lo ignora.
                writer(record, output_path)
                generated += 1

                log.info(
                    f"[{record['severity']:8s}] {record['hostname']:15s} "
                    f"CPU={record['cpu_pct']:5.1f}%  "
                    f"LAT={record['latency_ms']:7.1f}ms  "
                    f"LOSS={record['packet_loss_pct']:5.2f}%  "
                    f"{record['interface']} {record['iface_status']}"
                )
            except Exception as exc:
                # Log del error pero no se aborta el bucle → resiliencia
                log.error(f"Error escribiendo registro: {exc}")

        if count and generated >= count:
            log.info(f"Límite de {count} registros alcanzado. Fin.")
            break

        if interval > 0:
            time.sleep(interval)


# ── Bootstrap de conexión Postgres ────────────────────────────────────────────
def _setup_postgres(dsn: str | None) -> None:
    """Resuelve DSN (arg > env var) e inicializa el pool."""
    resolved_dsn = dsn or os.environ.get("PG_DSN")
    if not resolved_dsn:
        log.error(
            "Sink 'postgres' requiere DSN. Pásalo con --pg-dsn "
            "o define la variable de entorno PG_DSN."
        )
        sys.exit(1)

    log.info("Conectando a PostgreSQL...")
    init_pg_pool(dsn=resolved_dsn, minconn=1, maxconn=3)
    log.info("Pool de conexiones inicializado.")


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="NOC Network Log Simulator")
    p.add_argument(
        "--output", default="network_logs",
        help="Nombre base del archivo de salida sin extensión (solo para csv/jsonl)"
    )
    p.add_argument(
        "--fmt", default="csv", choices=["csv", "jsonl", "postgres"],
        help="Sink de salida"
    )
    p.add_argument(
        "--pg-dsn", dest="pg_dsn", default=None,
        help='DSN de conexión Postgres, ej: "postgresql://user:pass@host:5432/db". '
             'Alternativa: variable de entorno PG_DSN.'
    )
    p.add_argument("--interval", type=float, default=1.0,  help="Segundos entre batches")
    p.add_argument("--count",    type=int,   default=None, help="Límite de registros (None = infinito)")
    p.add_argument("--batch",    type=int,   default=1,    help="Registros por batch")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # Configuración condicional del sink
    if args.fmt == "postgres":
        _setup_postgres(args.pg_dsn)
        output_path = None          # el sink postgres no usa path
    else:
        output_path = Path(f"{args.output}.{args.fmt}")

    try:
        run_loop(
            output_path = output_path,
            fmt         = args.fmt,
            interval    = args.interval,
            count       = args.count,
            batch_size  = args.batch,
        )
    finally:
        if args.fmt == "postgres":
            close_pg_pool()
            log.info("Pool cerrado.")