"""
writer.py — Sinks de persistencia: CSV append | JSON Lines append | PostgreSQL/TimescaleDB.
Todos los sinks aceptan el mismo dict plano de build_log_record() (incluye 'region').
"""

import csv
import json
from pathlib import Path
from typing import Literal

CSV_FIELDNAMES = [
    "timestamp", "hostname", "ip", "role", "region", "severity", "message",
    "cpu_pct", "latency_ms", "packet_loss_pct",
    "interface", "iface_status", "peer_ip",
]


def write_csv(record: dict, filepath: str | Path) -> None:
    filepath = Path(filepath)
    write_header = not filepath.exists() or filepath.stat().st_size == 0
    with open(filepath, mode="a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(record)


def write_jsonl(record: dict, filepath: str | Path) -> None:
    with open(filepath, mode="a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


try:
    import psycopg2
    from psycopg2 import pool as pg_pool
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False

_connection_pool = None

_INSERT_SQL = """
INSERT INTO network_telemetry (
    ts, hostname, ip, role, region, severity, message,
    cpu_pct, latency_ms, packet_loss_pct,
    interface, iface_status, peer_ip
) VALUES (
    %s, %s, %s::inet, %s::device_role, %s, %s::severity_level, %s,
    %s, %s, %s,
    %s, %s::iface_state, %s::inet
);
"""


def init_pg_pool(dsn: str, minconn: int = 1, maxconn: int = 5) -> None:
    global _connection_pool
    if not _PG_AVAILABLE:
        raise ImportError("psycopg2 no instalado. Ejecuta: pip install psycopg2-binary")
    _connection_pool = pg_pool.SimpleConnectionPool(minconn=minconn, maxconn=maxconn, dsn=dsn)


def close_pg_pool() -> None:
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None


def write_postgres(record: dict, _filepath=None) -> None:
    if _connection_pool is None:
        raise RuntimeError("Pool no inicializado. Llama init_pg_pool() primero.")

    conn = _connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(_INSERT_SQL, (
                record["timestamp"],
                record["hostname"],
                record["ip"],
                record["role"],
                record["region"],
                record["severity"],
                record["message"],
                record["cpu_pct"],
                record["latency_ms"],
                record["packet_loss_pct"],
                record["interface"],
                record["iface_status"],
                record["peer_ip"],
            ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _connection_pool.putconn(conn)


_WRITERS = {
    "csv":      write_csv,
    "jsonl":    write_jsonl,
    "postgres": write_postgres,
}


def get_writer(fmt: Literal["csv", "jsonl", "postgres"]):
    if fmt not in _WRITERS:
        raise ValueError(f"Formato no soportado: '{fmt}'. Opciones: {list(_WRITERS)}")
    return _WRITERS[fmt]