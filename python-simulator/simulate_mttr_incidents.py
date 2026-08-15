"""
simulate_mttr_incidents.py — Chaos Engineering: dispara incidentes concurrentes
en múltiples dispositivos para validar el cálculo de MTTR (FIRING -> RESOLVED)
en el Dashboard de Postmortem de Grafana.

Reutiliza la lógica de conexión/pool/casts de writer.py (misma usada por simulator.py).

Uso:
    python simulate_mttr_incidents.py --pg-dsn "postgresql://noc_user:secret@localhost:5432/noc"

    # o vía variable de entorno
    $env:PG_DSN = "postgresql://noc_user:secret@localhost:5432/noc"
    python simulate_mttr_incidents.py
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

# Habilita el procesamiento de secuencias ANSI en consolas Windows (cmd/PowerShell 5.1+).
if os.name == "nt":
    os.system("")

from writer import init_pg_pool, close_pg_pool, write_postgres  # noqa: E402
from config import DEVICES  # noqa: E402


# ── Colores / estilo de consola ───────────────────────────────────────────────
class C:
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"
    MAGENTA = "\033[95m"
    GRAY    = "\033[90m"
    BOLD    = "\033[1m"
    RESET   = "\033[0m"


_print_lock = threading.Lock()


def clog(color: str, tag: str, hostname: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    with _print_lock:
        print(f"{C.GRAY}[{ts}]{C.RESET} {color}{tag} {C.BOLD}{hostname:14s}{C.RESET}{color} {msg}{C.RESET}")


# ── Definición del incidente ──────────────────────────────────────────────────
@dataclass
class ChaosIncident:
    hostname: str
    ip: str
    role: str                 # core-router | distribution-sw | access-sw
    interface: str
    metric: str                # "latency" | "packet_loss" | "cpu"
    bad_value: float
    baseline_cpu: float
    baseline_latency: float
    fire_minutes: float        # duración inyectando valores críticos
    recovery_minutes: float    # duración sosteniendo baseline sano
    start_delay_s: float = 0.0 # stagger para que los incidentes se crucen en el tiempo


INCIDENTS: list[ChaosIncident] = [
    ChaosIncident(
        hostname="core-rtr-01", ip="10.0.0.1", role="core-router",
        interface="Gi0/0/0", metric="latency", bad_value=230.0,
        baseline_cpu=45.0, baseline_latency=3.0,
        fire_minutes=4.0, recovery_minutes=3.0,
        start_delay_s=0,
    ),
    ChaosIncident(
        hostname="dist-sw-01", ip="10.0.1.1", role="distribution-sw",
        interface="Gi1/0/1", metric="packet_loss", bad_value=22.0,
        baseline_cpu=25.0, baseline_latency=6.0,
        fire_minutes=6.0, recovery_minutes=3.0,
        start_delay_s=20,
    ),
    ChaosIncident(
        hostname="access-sw-01", ip="10.0.2.1", role="access-sw",
        interface="Fa0/1", metric="cpu", bad_value=94.0,
        baseline_cpu=15.0, baseline_latency=8.0,
        fire_minutes=6.0, recovery_minutes=3.0,
        start_delay_s=40,
    ),
]

# Umbrales de alert_rules.yml — solo para logging informativo
_THRESHOLDS = {
    "latency":     ("Latencia > 150ms",   "for: 3m"),
    "packet_loss": ("Packet Loss > 10%",  "for: 2m"),
    "cpu":          ("CPU > 85%",         "for: 5m"),
}

INSERT_INTERVAL_S   = 15   # cadencia de inserción durante cada fase de incidente
KEEPALIVE_INTERVAL_S = 10  # cadencia del baseline continuo (anti DatasourceNoData)
WARMUP_SECONDS       = 120 # datos sanos previos antes de disparar el primer incidente
_write_lock = threading.Lock()   # SimpleConnectionPool no es thread-safe -> serializa el checkout
_stop_event = threading.Event()  # permite corte limpio con Ctrl+C

# Hosts con un incidente activo (FIRING o RECOVERY) -> el keepalive los ignora
# para no pisar los valores que el incidente está inyectando deliberadamente.
_active_incident_hosts: set[str] = set()
_active_lock = threading.Lock()


# ── Construcción e inserción de registros ────────────────────────────────────
def _build_record(inc: ChaosIncident, severity: str, cpu: float, latency: float,
                   loss: float, iface_status: str, message: str) -> dict:
    return {
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "hostname":        inc.hostname,
        "ip":              inc.ip,
        "role":            inc.role,
        "severity":        severity,
        "message":         message,
        "cpu_pct":         round(cpu, 2),
        "latency_ms":      round(latency, 2),
        "packet_loss_pct": round(loss, 2),
        "interface":       inc.interface,
        "iface_status":    iface_status,
        "peer_ip":         "10.0.0.254",
    }


def _safe_insert(record: dict, retries: int = 2) -> None:
    for attempt in range(retries + 1):
        try:
            with _write_lock:
                write_postgres(record)
            return
        except Exception:
            if attempt == retries:
                raise
            time.sleep(0.5)


def _jitter(base: float, pct: float = 0.1) -> float:
    return max(0.0, base + random.uniform(-base * pct, base * pct))


def _emit_bad(inc: ChaosIncident) -> None:
    cpu, latency, loss = inc.baseline_cpu, inc.baseline_latency, 0.2
    iface_status = "UP"

    if inc.metric == "latency":
        latency = inc.bad_value
        msg = f"CRITICAL: {inc.hostname} unreachable - RTT {latency:.1f}ms"
    elif inc.metric == "packet_loss":
        loss = inc.bad_value
        iface_status = "DOWN" if random.random() < 0.3 else "UP"
        msg = f"CRITICAL: Packet loss {loss:.1f}% - circuit down"
    else:  # cpu
        cpu = inc.bad_value
        msg = f"CRITICAL: CPU at {cpu:.1f}% - process crash risk"

    record = _build_record(inc, "CRITICAL", _jitter(cpu) if inc.metric != "cpu" else cpu,
                            _jitter(latency) if inc.metric != "latency" else latency,
                            loss, iface_status, msg)
    _safe_insert(record)


def _emit_healthy(inc: ChaosIncident) -> None:
    cpu    = _jitter(inc.baseline_cpu)
    latency = _jitter(inc.baseline_latency)
    loss    = round(random.uniform(0.0, 0.3), 2)
    msg     = f"SNMP poll successful on {inc.hostname}"
    record  = _build_record(inc, "INFO", cpu, latency, loss, "UP", msg)
    _safe_insert(record)


# ── Keepalive: telemetría sana continua para TODOS los dispositivos ──────────
# Evita que cualquier host quede sin filas recientes en network_telemetry
# (antes de su incidente, después de resolverlo, o si nunca tiene incidente),
# que es la causa real de las alertas "DatasourceNoData".
def keepalive_loop() -> None:
    clog(C.CYAN, "💓 KEEPALIVE", "ALL", f"Baseline continuo activo cada {KEEPALIVE_INTERVAL_S}s")
    while not _stop_event.is_set():
        with _active_lock:
            busy = set(_active_incident_hosts)

        for device in DEVICES:
            if device.hostname in busy:
                continue  # un incidente ya está escribiendo sus propios valores
            record = {
                "timestamp":       datetime.now(timezone.utc).isoformat(),
                "hostname":        device.hostname,
                "ip":              device.ip,
                "role":            device.role,
                "severity":        "INFO",
                "message":         f"SNMP poll successful on {device.hostname}",
                "cpu_pct":         round(_jitter(device.cpu_base), 2),
                "latency_ms":      round(_jitter(device.latency_base), 2),
                "packet_loss_pct": round(random.uniform(0.0, 0.3), 2),
                "interface":       "Gi0/0/0",
                "iface_status":    "UP",
                "peer_ip":         "10.0.0.254",
            }
            try:
                _safe_insert(record)
            except Exception as exc:
                clog(C.RED, "⚠️  ERROR  ", device.hostname, f"Keepalive falló: {exc}")

        _stop_event.wait(KEEPALIVE_INTERVAL_S)


def warmup(seconds: int) -> None:
    clog(C.CYAN, "🌡️  WARMUP  ", "ALL",
         f"Precalentando {seconds}s de baseline antes de inyectar incidentes (evita NoData inicial)")
    _stop_event.wait(seconds)


# ── Ciclo de vida completo de un incidente ───────────────────────────────────
def run_incident(inc: ChaosIncident) -> None:
    if inc.start_delay_s:
        time.sleep(inc.start_delay_s)

    with _active_lock:
        _active_incident_hosts.add(inc.hostname)

    label, for_clause = _THRESHOLDS[inc.metric]

    # Fase 1 + 2: inyectar y sostener la métrica crítica
    clog(C.RED, "🔥 FIRING  ", inc.hostname,
         f"Inyectando falla [{inc.metric}] {label} durante {inc.fire_minutes:.0f} min ({for_clause})")

    fire_deadline = time.time() + inc.fire_minutes * 60
    while time.time() < fire_deadline and not _stop_event.is_set():
        try:
            _emit_bad(inc)
        except Exception as exc:
            clog(C.RED, "⚠️  ERROR  ", inc.hostname, f"Fallo insertando métrica crítica: {exc}")
        clog(C.YELLOW, "🚨 CRITICAL", inc.hostname,
             f"{inc.metric}={inc.bad_value} — esperando que Grafana evalúe la regla...")
        time.sleep(INSERT_INTERVAL_S)

    # Fase 3: recuperación -> baseline sano
    clog(C.CYAN, "🛠️  RECOVERY", inc.hostname,
         f"Restaurando valores baseline durante {inc.recovery_minutes:.0f} min para forzar RESOLVED")

    recovery_deadline = time.time() + inc.recovery_minutes * 60
    while time.time() < recovery_deadline and not _stop_event.is_set():
        try:
            _emit_healthy(inc)
        except Exception as exc:
            clog(C.RED, "⚠️  ERROR  ", inc.hostname, f"Fallo insertando métrica sana: {exc}")
        clog(C.GREEN, "✅ HEALTHY ", inc.hostname, "Valores dentro de baseline")
        time.sleep(INSERT_INTERVAL_S)

    with _active_lock:
        _active_incident_hosts.discard(inc.hostname)

    clog(C.MAGENTA, "🏁 CLOSED  ", inc.hostname,
         "Incidente cerrado — Grafana debería marcar RESOLVED y calcular el MTTR")


# ── Bootstrap de conexión ─────────────────────────────────────────────────────
def setup_pg(dsn: str | None) -> None:
    resolved = dsn or os.environ.get("PG_DSN")
    if not resolved:
        print(f"{C.RED}Falta DSN. Usa --pg-dsn o define $env:PG_DSN.{C.RESET}")
        sys.exit(1)
    init_pg_pool(dsn=resolved, minconn=1, maxconn=len(INCIDENTS) + 2)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chaos Engineering — simulación de incidentes para MTTR")
    p.add_argument("--pg-dsn", dest="pg_dsn", default=None,
                    help='DSN Postgres, ej: "postgresql://noc_user:secret@localhost:5432/noc"')
    return p.parse_args()


def main() -> None:
    args = parse_args()
    setup_pg(args.pg_dsn)

    print(f"{C.BOLD}{C.MAGENTA}=== CHAOS ENGINEERING — MTTR SCENARIO ==={C.RESET}")
    print(f"{C.GRAY}Dispositivos objetivo: {', '.join(i.hostname for i in INCIDENTS)}{C.RESET}")
    print(f"{C.GRAY}Baseline continuo: {', '.join(d.hostname for d in DEVICES)}{C.RESET}\n")

    keepalive_thread = threading.Thread(target=keepalive_loop, name="keepalive", daemon=True)
    incident_threads = [threading.Thread(target=run_incident, args=(inc,), name=inc.hostname) for inc in INCIDENTS]

    try:
        keepalive_thread.start()
        warmup(WARMUP_SECONDS)

        for t in incident_threads:
            t.start()
        for t in incident_threads:
            t.join()

        print(f"\n{C.BOLD}{C.GREEN}✅ Escenario de caos completado. Revisa el Dashboard de Postmortem en Grafana.{C.RESET}")
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}Ctrl+C recibido — deteniendo incidentes en curso...{C.RESET}")
    finally:
        _stop_event.set()
        for t in incident_threads:
            t.join(timeout=5)
        keepalive_thread.join(timeout=5)
        close_pg_pool()


if __name__ == "__main__":
    main()