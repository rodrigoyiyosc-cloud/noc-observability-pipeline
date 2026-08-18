"""
simulate_mttr_incidents.py — Chaos Engineering: dispara alertas concurrentes
(firing -> resolved) directamente contra el Webhook FastAPI, emulando el
payload nativo de Grafana Alerting, para validar el cálculo de MTTR en el
Dashboard de Postmortem multi-región.

Fase 4 — Escalado Multi-región y Autenticación de Webhook:
    - Auth: Bearer token (NOC_WEBHOOK_TOKEN) cargado desde .env.
    - Payload: incluye "region" dentro de "labels" por cada alerta.
    - Dispositivos: pool global (us-east, eu-west, sa-south).
    - Estructura: payload estándar de Grafana ({"status", "alerts": [...]}).

Uso:
    python simulate_mttr_incidents.py
    python simulate_mttr_incidents.py --webhook-url "http://localhost:8000/alert"
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

# Habilita el procesamiento de secuencias ANSI en consolas Windows (cmd/PowerShell 5.1+).
if os.name == "nt":
    os.system("")

load_dotenv()  # carga .env (NOC_WEBHOOK_TOKEN, WEBHOOK_URL, etc.)


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
        print(f"{C.GRAY}[{ts}]{C.RESET} {color}{tag} {C.BOLD}{hostname:20s}{C.RESET}{color} {msg}{C.RESET}")


# ── Configuración del Webhook ──────────────────────────────────────────────
DEFAULT_WEBHOOK_URL = "http://localhost:8000/alert"
NOC_WEBHOOK_TOKEN = os.environ.get("NOC_WEBHOOK_TOKEN")

if not NOC_WEBHOOK_TOKEN:
    print(f"{C.RED}Falta NOC_WEBHOOK_TOKEN. Defínelo en tu archivo .env.{C.RESET}")
    sys.exit(1)

_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {NOC_WEBHOOK_TOKEN}",
}

_stop_event = threading.Event()  # permite corte limpio con Ctrl+C


# ── Definición del incidente (multi-región) ──────────────────────────────────
@dataclass
class ChaosIncident:
    hostname: str
    ip: str
    role: str                  # core-router | distribution-sw | access-sw
    region: str                 # us-east | eu-west | sa-south
    interface: str
    metric: str                 # "latency" | "packet_loss" | "cpu"
    bad_value: float
    threshold_label: str
    for_clause: str
    fire_minutes: float         # duración inyectando estado "firing"
    recovery_minutes_range: tuple[float, float]  # rango para recovery aleatorio
    start_delay_s: float = 0.0  # stagger para que los incidentes se crucen en el tiempo


INCIDENTS: list[ChaosIncident] = [
    ChaosIncident(
        hostname="core-rtr-01", ip="10.0.0.1", role="core-router", region="us-east",
        interface="Gi0/0/0", metric="latency", bad_value=230.0,
        threshold_label="Latencia > 150ms", for_clause="for: 3m",
        fire_minutes=2.0, recovery_minutes_range=(0.5, 2.0),
        start_delay_s=0,
    ),
    ChaosIncident(
        hostname="euw1-core-rtr-01", ip="10.20.0.1", role="core-router", region="eu-west",
        interface="Gi0/0/0", metric="packet_loss", bad_value=22.0,
        threshold_label="Packet Loss > 10%", for_clause="for: 2m",
        fire_minutes=3.0, recovery_minutes_range=(1.0, 3.0),
        start_delay_s=20,
    ),
    ChaosIncident(
        hostname="sas1-core-rtr-01", ip="10.30.0.1", role="core-router", region="sa-south",
        interface="Gi0/0/0", metric="cpu", bad_value=94.0,
        threshold_label="CPU > 85%", for_clause="for: 5m",
        fire_minutes=2.5, recovery_minutes_range=(0.5, 2.5),
        start_delay_s=40,
    ),
]

INSERT_INTERVAL_S = 15  # cadencia de reenvío del estado "firing" mientras persiste


def _fingerprint(inc: ChaosIncident) -> str:
    raw = f"{inc.hostname}:{inc.metric}:{inc.region}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _metric_value_label(inc: ChaosIncident) -> str:
    units = {"latency": "ms", "packet_loss": "%", "cpu": "%"}
    return f"{inc.bad_value:.1f}{units[inc.metric]}"


def _build_payload(inc: ChaosIncident, alert_status: str, starts_at: str, ends_at: str) -> dict:
    """Construye el payload en formato estándar de Grafana Alerting."""
    alertname = f"{inc.metric.replace('_', ' ').title()}Critical"
    summary = f"{inc.threshold_label} en {inc.hostname} ({inc.region})"
    description = (
        f"El dispositivo {inc.hostname} ({inc.ip}, {inc.role}) en la región {inc.region} "
        f"reporta {inc.metric}={_metric_value_label(inc)} en la interfaz {inc.interface}. {inc.for_clause}."
        if alert_status == "firing"
        else f"El dispositivo {inc.hostname} ({inc.region}) volvió a valores baseline. Alerta resuelta."
    )

    alert = {
        "status": alert_status,
        "labels": {
            "alertname": alertname,
            "severity": "critical",
            "region": inc.region,
            "hostname": inc.hostname,
            "instance": inc.ip,
            "role": inc.role,
            "interface": inc.interface,
            "metric": inc.metric,
        },
        "annotations": {
            "summary": summary,
            "description": description,
        },
        "startsAt": starts_at,
        "endsAt": ends_at,
        "fingerprint": _fingerprint(inc),
    }

    return {
        "receiver": "noc-webhook-service",
        "status": alert_status,
        "alerts": [alert],
        "groupLabels": {"alertname": alertname, "region": inc.region},
        "commonLabels": alert["labels"],
        "commonAnnotations": alert["annotations"],
        "title": summary,
        "ruleName": alertname,
    }


# ── Envío HTTP al webhook ─────────────────────────────────────────────────────
def _send_alert(payload: dict, retries: int = 2, timeout: float = 5.0) -> None:
    for attempt in range(retries + 1):
        try:
            resp = requests.post(DEFAULT_WEBHOOK_URL if not _webhook_url_override else _webhook_url_override,
                                  json=payload, headers=_HEADERS, timeout=timeout)
            if resp.status_code == 401:
                raise PermissionError(f"401 Unauthorized — revisa NOC_WEBHOOK_TOKEN ({resp.text})")
            resp.raise_for_status()
            return
        except PermissionError:
            raise
        except requests.RequestException:
            if attempt == retries:
                raise
            time.sleep(0.5)


_webhook_url_override: str | None = None


# ── Ciclo de vida completo de un incidente ───────────────────────────────────
def run_incident(inc: ChaosIncident) -> None:
    if inc.start_delay_s:
        time.sleep(inc.start_delay_s)

    starts_at = datetime.now(timezone.utc).isoformat()

    clog(C.RED, "🔥 FIRING  ", f"{inc.hostname} [{inc.region}]",
         f"Inyectando falla [{inc.metric}={_metric_value_label(inc)}] {inc.threshold_label} "
         f"durante {inc.fire_minutes:.1f} min ({inc.for_clause})")

    fire_deadline = time.time() + inc.fire_minutes * 60
    while time.time() < fire_deadline and not _stop_event.is_set():
        try:
            payload = _build_payload(inc, "firing", starts_at, "0001-01-01T00:00:00Z")
            _send_alert(payload)
        except Exception as exc:
            clog(C.RED, "⚠️  ERROR  ", f"{inc.hostname} [{inc.region}]", f"Fallo enviando alerta firing: {exc}")
        clog(C.YELLOW, "🚨 CRITICAL", f"{inc.hostname} [{inc.region}]",
             f"{inc.metric}={_metric_value_label(inc)} — esperando evaluación de Grafana...")
        time.sleep(INSERT_INTERVAL_S)

    recovery_minutes = random.uniform(*inc.recovery_minutes_range)
    clog(C.CYAN, "🛠️  RECOVERY", f"{inc.hostname} [{inc.region}]",
         f"Resolviendo en {recovery_minutes:.1f} min (aleatorio) para forzar RESOLVED")

    if not _stop_event.is_set():
        _stop_event.wait(recovery_minutes * 60)

    ends_at = datetime.now(timezone.utc).isoformat()
    try:
        payload = _build_payload(inc, "resolved", starts_at, ends_at)
        _send_alert(payload)
    except Exception as exc:
        clog(C.RED, "⚠️  ERROR  ", f"{inc.hostname} [{inc.region}]", f"Fallo enviando alerta resolved: {exc}")

    clog(C.GREEN, "✅ RESOLVED", f"{inc.hostname} [{inc.region}]",
         f"MTTR ≈ {(datetime.fromisoformat(ends_at) - datetime.fromisoformat(starts_at)).total_seconds():.0f}s")

    clog(C.MAGENTA, "🏁 CLOSED  ", f"{inc.hostname} [{inc.region}]",
         "Incidente cerrado — Grafana debería marcar RESOLVED y calcular el MTTR")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chaos Engineering — simulación de alertas multi-región vía Webhook")
    p.add_argument("--webhook-url", dest="webhook_url", default=None,
                    help=f'URL del webhook FastAPI (default: env WEBHOOK_URL o "{DEFAULT_WEBHOOK_URL}")')
    return p.parse_args()


def main() -> None:
    global _webhook_url_override

    args = parse_args()
    _webhook_url_override = args.webhook_url or os.environ.get("WEBHOOK_URL") or DEFAULT_WEBHOOK_URL

    print(f"{C.BOLD}{C.MAGENTA}=== CHAOS ENGINEERING — MTTR MULTI-REGIÓN (WEBHOOK) ==={C.RESET}")
    print(f"{C.GRAY}Webhook: {_webhook_url_override}{C.RESET}")
    print(f"{C.GRAY}Regiones/dispositivos objetivo: "
          f"{', '.join(f'{i.hostname}({i.region})' for i in INCIDENTS)}{C.RESET}\n")

    # Verificación rápida de salud/auth antes de disparar incidentes
    try:
        health_url = _webhook_url_override.rsplit("/alert", 1)[0] + "/health"
        r = requests.get(health_url, timeout=5)
        r.raise_for_status()
        clog(C.CYAN, "❤️  HEALTH ", "webhook", f"OK — {health_url}")
    except Exception as exc:
        clog(C.YELLOW, "⚠️  WARN   ", "webhook", f"No se pudo verificar /health ({exc}), continuando de todos modos")

    incident_threads = [threading.Thread(target=run_incident, args=(inc,), name=f"{inc.hostname}-{inc.region}")
                         for inc in INCIDENTS]

    try:
        for t in incident_threads:
            t.start()
        for t in incident_threads:
            t.join()

        print(f"\n{C.BOLD}{C.GREEN}✅ Escenario de caos multi-región completado. "
              f"Revisa el Dashboard de Postmortem en Grafana.{C.RESET}")
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}Ctrl+C recibido — deteniendo incidentes en curso...{C.RESET}")
    finally:
        _stop_event.set()
        for t in incident_threads:
            t.join(timeout=5)


if __name__ == "__main__":
    main()