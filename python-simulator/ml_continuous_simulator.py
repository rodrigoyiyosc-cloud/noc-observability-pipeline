"""
ml_continuous_simulator.py — Fase 5 (Machine Learning): generador continuo
multi-región de telemetría sintética hacia TimescaleDB + disparo SÍNCRONO del
Webhook FastAPI (firing/resolved), saltando el motor de evaluación de Grafana,
para garantizar Dataset perfecto (telemetría alineada 1:1 con incidentes en
Jira/Postmortem).

Fusiona:
    - ml_continuous_simulator.py  → loop infinito, 3 regiones embebidas,
      inserción batch en network_telemetry, CRITICAL sostenido 6-8 min.
    - simulate_mttr_incidents.py  → payload nativo de Grafana Alerting,
      Bearer NOC_WEBHOOK_TOKEN, POST directo a FastAPI /alert.

Reglas de disparo:
    DEGRADING -> CRITICAL   : POST status="firing"  (una vez, al entrar)
    CRITICAL  -> RECOVERING : POST status="resolved" (una vez, al salir)

Resiliencia: los envíos al Webhook corren en un ThreadPoolExecutor con sus
propios reintentos/timeout — un fallo de red hacia FastAPI/Jira NUNCA detiene
ni retrasa el loop de inserción en TimescaleDB.

Uso:
    python ml_continuous_simulator.py
    python ml_continuous_simulator.py --pg-dsn "postgresql://user:pass@host:5432/noc" --interval 15
    python ml_continuous_simulator.py --webhook-url "http://localhost:8000/alert" --hours 12
    python ml_continuous_simulator.py --no-webhook   # sólo telemetría, sin disparar incidentes
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import math
import os
import random
import signal
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import requests
from dotenv import load_dotenv

try:
    import psycopg2
    from psycopg2 import pool as pg_pool
    from psycopg2.extras import execute_values
except ImportError:
    print("Falta psycopg2. Ejecuta: pip install psycopg2-binary")
    sys.exit(1)

load_dotenv()

if os.name == "nt":
    os.system("")


# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ML-SIM][multi-region] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Señales / apagado limpio ─────────────────────────────────────────────────
_running = True


def _handle_shutdown(sig, frame):
    global _running
    log.info("Señal de apagado recibida — terminando el tick actual y cerrando limpio...")
    _running = False


signal.signal(signal.SIGINT, _handle_shutdown)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, _handle_shutdown)


# ── Topología: 3 regiones embebidas, SIN depender de la env REGION ─────────
@dataclass
class NetworkDevice:
    hostname: str
    ip: str
    role: str
    region: str
    interfaces: list[str]
    cpu_base: float
    latency_base: float


REGIONS: list[str] = ["us-east", "eu-west", "sa-south"]

_REGION_SEEDS = {
    "us-east": [
        ("core-rtr-01",  "10.0.0.1", "core-router",     ["Gi0/0/0", "Gi0/0/1", "Gi0/0/2", "Te0/1/0"], 45.0, 3.0),
        ("core-rtr-02",  "10.0.0.2", "core-router",     ["Gi0/0/0", "Gi0/0/1", "Te0/1/0"],             40.0, 3.5),
        ("dist-sw-01",   "10.0.1.1", "distribution-sw", ["Gi1/0/1", "Gi1/0/2", "Gi1/0/3", "Gi1/0/24"], 25.0, 6.0),
        ("dist-sw-02",   "10.0.1.2", "distribution-sw", ["Gi1/0/1", "Gi1/0/2", "Gi1/0/3"],              22.0, 6.5),
        ("access-sw-01", "10.0.2.1", "access-sw",       ["Fa0/1", "Fa0/2", "Fa0/3", "Fa0/24"],          15.0, 8.0),
    ],
    "eu-west": [
        ("euw1-core-rtr-01",  "10.20.0.1", "core-router",     ["Gi0/0/0", "Gi0/0/1", "Gi0/0/2", "Te0/1/0"], 42.0, 4.0),
        ("euw1-core-rtr-02",  "10.20.0.2", "core-router",     ["Gi0/0/0", "Gi0/0/1", "Te0/1/0"],             38.0, 4.5),
        ("euw1-dist-sw-01",   "10.20.1.1", "distribution-sw", ["Gi1/0/1", "Gi1/0/2", "Gi1/0/3", "Gi1/0/24"], 24.0, 7.0),
        ("euw1-dist-sw-02",   "10.20.1.2", "distribution-sw", ["Gi1/0/1", "Gi1/0/2", "Gi1/0/3"],              21.0, 7.5),
        ("euw1-access-sw-01", "10.20.2.1", "access-sw",       ["Fa0/1", "Fa0/2", "Fa0/3", "Fa0/24"],          14.0, 9.0),
    ],
    "sa-south": [
        ("sas1-core-rtr-01",  "10.30.0.1", "core-router",     ["Gi0/0/0", "Gi0/0/1", "Gi0/0/2", "Te0/1/0"], 44.0, 6.0),
        ("sas1-core-rtr-02",  "10.30.0.2", "core-router",     ["Gi0/0/0", "Gi0/0/1", "Te0/1/0"],             39.0, 6.5),
        ("sas1-dist-sw-01",   "10.30.1.1", "distribution-sw", ["Gi1/0/1", "Gi1/0/2", "Gi1/0/3", "Gi1/0/24"], 26.0, 9.0),
        ("sas1-dist-sw-02",   "10.30.1.2", "distribution-sw", ["Gi1/0/1", "Gi1/0/2", "Gi1/0/3"],              23.0, 9.5),
        ("sas1-access-sw-01", "10.30.2.1", "access-sw",       ["Fa0/1", "Fa0/2", "Fa0/3", "Fa0/24"],          16.0, 11.0),
    ],
}

ALL_DEVICES: list[NetworkDevice] = [
    NetworkDevice(hostname=h, ip=ip, role=role, region=region, interfaces=ifaces,
                   cpu_base=cpu_b, latency_base=lat_b)
    for region in REGIONS
    for (h, ip, role, ifaces, cpu_b, lat_b) in _REGION_SEEDS[region]
]


# ── SQL: misma tabla/columnas que writer.py ─────────────────────────────────
_INSERT_SQL = """
INSERT INTO network_telemetry (
    ts, hostname, ip, role, region, severity, message,
    cpu_pct, latency_ms, packet_loss_pct,
    interface, iface_status, peer_ip
) VALUES %s
"""

_INSERT_TEMPLATE = (
    "(%s, %s, %s::inet, %s::device_role, %s, %s::severity_level, %s, "
    "%s, %s, %s, %s, %s::iface_state, %s::inet)"
)


# ── Webhook FastAPI (payload nativo Grafana Alerting) ───────────────────────
NOC_WEBHOOK_TOKEN = os.environ.get("NOC_WEBHOOK_TOKEN")
DEFAULT_WEBHOOK_URL = "http://localhost:8000/alert"

_WEBHOOK_HEADERS: dict | None = None
if NOC_WEBHOOK_TOKEN:
    _WEBHOOK_HEADERS = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NOC_WEBHOOK_TOKEN}",
    }
else:
    log.warning("NOC_WEBHOOK_TOKEN no definido — el webhook quedará deshabilitado "
                "(sólo se insertará telemetría en TimescaleDB).")

_webhook_url: str = DEFAULT_WEBHOOK_URL
_webhook_enabled: bool = True
_webhook_executor: Optional[ThreadPoolExecutor] = None

_METRIC_UNITS = {"latency": "ms", "packet_loss": "%", "cpu": "%"}
_METRIC_THRESHOLD_LABEL = {
    "latency": "Latencia > umbral crítico",
    "packet_loss": "Packet Loss > umbral crítico",
    "cpu": "CPU > umbral crítico",
}


def _fingerprint(hostname: str, metric: str, region: str) -> str:
    raw = f"{hostname}:{metric}:{region}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _build_alert_payload(device: "NetworkDevice", metric: str, bad_value: float,
                          iface: str, alert_status: str, starts_at: str, ends_at: str,
                          fingerprint: str) -> dict:
    """Construye el payload en formato estándar de Grafana Alerting (idéntico a
    simulate_mttr_incidents.py) para POSTear directo al Webhook FastAPI."""
    alertname = f"{metric.replace('_', ' ').title()}Critical"
    unit = _METRIC_UNITS[metric]
    value_label = f"{bad_value:.1f}{unit}"
    threshold_label = _METRIC_THRESHOLD_LABEL[metric]
    summary = f"{threshold_label} en {device.hostname} ({device.region})"
    description = (
        f"El dispositivo {device.hostname} ({device.ip}, {device.role}) en la región "
        f"{device.region} reporta {metric}={value_label} en la interfaz {iface}. for: 6m."
        if alert_status == "firing"
        else f"El dispositivo {device.hostname} ({device.region}) volvió a valores baseline. Alerta resuelta."
    )

    alert = {
        "status": alert_status,
        "labels": {
            "alertname": alertname,
            "severity": "critical",
            "region": device.region,
            "hostname": device.hostname,
            "instance": device.ip,
            "role": device.role,
            "interface": iface,
            "metric": metric,
        },
        "annotations": {"summary": summary, "description": description},
        "startsAt": starts_at,
        "endsAt": ends_at,
        "fingerprint": fingerprint,
    }

    return {
        "receiver": "noc-webhook-service",
        "status": alert_status,
        "alerts": [alert],
        "groupLabels": {"alertname": alertname, "region": device.region},
        "commonLabels": alert["labels"],
        "commonAnnotations": alert["annotations"],
        "title": summary,
        "ruleName": alertname,
    }


def _post_webhook_safe(payload: dict, tag: str, retries: int = 2, timeout: float = 5.0) -> None:
    """Se ejecuta en un worker del ThreadPoolExecutor. Nunca propaga excepciones
    hacia el loop principal — sólo loguea éxito/fallo."""
    if not _webhook_enabled or _WEBHOOK_HEADERS is None:
        return

    for attempt in range(retries + 1):
        try:
            resp = requests.post(_webhook_url, json=payload, headers=_WEBHOOK_HEADERS, timeout=timeout)
            if resp.status_code == 401:
                log.error(f"Webhook 401 Unauthorized ({tag}) — revisa NOC_WEBHOOK_TOKEN")
                return
            resp.raise_for_status()
            log.info(f"📡 Webhook OK [{tag}] → {resp.status_code}")
            return
        except requests.RequestException as exc:
            if attempt == retries:
                log.error(f"Webhook falló definitivamente [{tag}] tras {retries + 1} intentos: {exc}")
                return
            time.sleep(0.5 * (2 ** attempt))
        except Exception as exc:  # blindaje total: cualquier error nunca debe tumbar el hilo
            log.error(f"Error inesperado enviando webhook [{tag}]: {exc}")
            return


def dispatch_webhook(device: "NetworkDevice", metric: str, bad_value: float, iface: str,
                      alert_status: str, starts_at: datetime, ends_at: Optional[datetime],
                      fingerprint: str, tag: str) -> None:
    if not _webhook_enabled or _webhook_executor is None:
        return
    starts_at_s = starts_at.isoformat()
    ends_at_s = ends_at.isoformat() if ends_at else "0001-01-01T00:00:00Z"
    payload = _build_alert_payload(device, metric, bad_value, iface, alert_status,
                                    starts_at_s, ends_at_s, fingerprint)
    try:
        _webhook_executor.submit(_post_webhook_safe, payload, tag)
    except Exception as exc:  # pool caído/saturado: jamás afecta al loop de DB
        log.error(f"No se pudo encolar el webhook [{tag}]: {exc}")


# ── Máquina de estados por dispositivo ──────────────────────────────────────
PHASES = ("BASELINE", "DEGRADING", "CRITICAL", "RECOVERING")

_METRIC_BY_ROLE = {
    "core-router":     ["latency", "packet_loss", "cpu"],
    "distribution-sw": ["packet_loss", "cpu", "latency"],
    "access-sw":       ["cpu", "packet_loss", "latency"],
}

_CEILINGS = {"cpu": 100.0, "latency": 2000.0, "packet_loss": 100.0}

# Mínimo/máximo tiempo REAL sostenido en CRITICAL, para cumplir el "for: 5m" de Grafana
# (aunque ahora el webhook se dispara directo, se conserva la duración realista).
CRITICAL_MIN_SECONDS = 6 * 60
CRITICAL_MAX_SECONDS = 8 * 60

# Se fija en run()/main() según --interval y se usa para calcular ticks de CRITICAL.
_INTERVAL_S: float = 10.0


@dataclass
class DeviceState:
    device: NetworkDevice
    phase: str = "BASELINE"
    metric: Optional[str] = None
    abrupt: bool = False
    ticks_total: int = 0
    ticks_done: int = 0
    incident_id: Optional[str] = None
    fingerprint: Optional[str] = None
    starts_at: Optional[datetime] = None
    last_bad_value: float = 0.0
    last_iface: str = ""
    peer_ip: str = field(default_factory=lambda: f"10.{random.randint(0,2)}.{random.randint(0,5)}.{random.randint(1,254)}")


def _jitter(base: float, pct: float = 0.15) -> float:
    sigma = max(base * pct, 0.01)
    return max(0.0, float(np.random.normal(base, sigma)))


def _base_value(device: NetworkDevice, metric: str) -> float:
    if metric == "cpu":
        return device.cpu_base
    if metric == "latency":
        return device.latency_base
    return 0.3  # packet_loss baseline casi nulo


def _critical_value(metric: str) -> float:
    return {
        "cpu": random.uniform(90.0, 99.0),
        "latency": random.uniform(250.0, 900.0),
        "packet_loss": random.uniform(15.0, 40.0),
    }[metric]


def _interp(start: float, end: float, frac: float) -> float:
    frac = min(1.0, max(0.0, frac))
    return start + (end - start) * frac


def _severity_for(phase: str, frac: float) -> str:
    if phase == "BASELINE":
        return random.choices(["INFO", "WARN"], weights=[0.93, 0.07])[0]
    if phase == "DEGRADING":
        return "WARN" if frac < 0.6 else "ERROR"
    if phase == "CRITICAL":
        return "CRITICAL"
    if phase == "RECOVERING":
        return "ERROR" if frac < 0.4 else ("WARN" if frac < 0.85 else "INFO")
    return "INFO"


def _critical_ticks(interval_s: float) -> int:
    """Ticks necesarios para sostener CRITICAL entre 6 y 8 minutos reales."""
    seconds = random.uniform(CRITICAL_MIN_SECONDS, CRITICAL_MAX_SECONDS)
    return max(1, math.ceil(seconds / max(interval_s, 0.001)))


def _start_incident(st: DeviceState) -> None:
    st.metric = random.choice(_METRIC_BY_ROLE.get(st.device.role, ["cpu"]))
    st.abrupt = random.random() < 0.30  # 30% abrupto, 70% degradación progresiva
    st.incident_id = uuid.uuid4().hex[:12]
    st.phase = "DEGRADING"
    st.ticks_total = 1 if st.abrupt else random.randint(4, 10)
    st.ticks_done = 0
    tag = "ABRUPTA" if st.abrupt else "PROGRESIVA"
    log.warning(f"🔥 Nuevo incidente [{tag}] métrica={st.metric} host={st.device.hostname} "
                f"región={st.device.region} id={st.incident_id}")


def _advance(st: DeviceState) -> dict:
    """Avanza un tick la máquina de estados y devuelve las métricas resultantes."""
    device = st.device

    if st.phase == "BASELINE":
        cpu = _jitter(device.cpu_base)
        lat = _jitter(device.latency_base)
        loss = _jitter(0.2, pct=0.5)
        severity = _severity_for("BASELINE", 0.0)
        return {"severity": severity, "cpu_pct": cpu, "latency_ms": lat, "packet_loss_pct": loss}

    frac = (st.ticks_done + 1) / max(st.ticks_total, 1)
    base = _base_value(device, st.metric)
    peak = _critical_value(st.metric)

    if st.phase in ("DEGRADING", "CRITICAL"):
        target_frac = 1.0 if st.phase == "CRITICAL" else frac
        bad_val = _jitter(_interp(base, peak, target_frac), pct=0.10)
    else:  # RECOVERING
        bad_val = _jitter(_interp(peak, base, frac), pct=0.10)

    severity = _severity_for(st.phase, frac)

    metrics = {
        "severity": severity,
        "cpu_pct": _jitter(device.cpu_base),
        "latency_ms": _jitter(device.latency_base),
        "packet_loss_pct": _jitter(0.2, pct=0.5),
    }
    key = {"cpu": "cpu_pct", "latency": "latency_ms", "packet_loss": "packet_loss_pct"}[st.metric]
    bad_val = round(min(_CEILINGS[st.metric], bad_val), 2)
    metrics[key] = bad_val
    st.last_bad_value = bad_val
    for k in ("cpu_pct", "latency_ms", "packet_loss_pct"):
        metrics[k] = round(metrics[k], 2)

    st.ticks_done += 1
    if st.ticks_done >= st.ticks_total:
        _transition(st)

    return metrics


def _transition(st: DeviceState) -> None:
    device = st.device

    if st.phase == "DEGRADING":
        st.phase = "CRITICAL"
        st.ticks_total = _critical_ticks(_INTERVAL_S)  # sostenido 6-8 min reales
        st.ticks_done = 0
        st.starts_at = datetime.now(timezone.utc)
        st.fingerprint = _fingerprint(device.hostname, st.metric, device.region)
        eta_min = (st.ticks_total * _INTERVAL_S) / 60.0
        log.error(f"🚨 CRITICAL sostenido host={device.hostname} región={device.region} "
                  f"métrica={st.metric} id={st.incident_id} duración≈{eta_min:.1f}min "
                  f"({st.ticks_total} ticks)")

        dispatch_webhook(
            device=device, metric=st.metric, bad_value=st.last_bad_value or _critical_value(st.metric),
            iface=st.last_iface or random.choice(device.interfaces), alert_status="firing",
            starts_at=st.starts_at, ends_at=None, fingerprint=st.fingerprint,
            tag=f"FIRING {device.hostname}/{st.metric}",
        )

    elif st.phase == "CRITICAL":
        ends_at = datetime.now(timezone.utc)
        mttr_s = (ends_at - st.starts_at).total_seconds() if st.starts_at else 0.0

        dispatch_webhook(
            device=device, metric=st.metric, bad_value=st.last_bad_value,
            iface=st.last_iface or random.choice(device.interfaces), alert_status="resolved",
            starts_at=st.starts_at or ends_at, ends_at=ends_at, fingerprint=st.fingerprint or "",
            tag=f"RESOLVED {device.hostname}/{st.metric}",
        )

        st.phase = "RECOVERING"
        st.ticks_total = random.randint(2, 6)
        st.ticks_done = 0
        log.info(f"🛠️  Recuperando host={device.hostname} región={device.region} "
                 f"métrica={st.metric} id={st.incident_id} MTTR≈{mttr_s:.0f}s")

    elif st.phase == "RECOVERING":
        log.info(f"✅ CERRADO host={device.hostname} región={device.region} "
                 f"métrica={st.metric} id={st.incident_id}")
        st.phase = "BASELINE"
        st.metric = None
        st.incident_id = None
        st.fingerprint = None
        st.starts_at = None
        st.ticks_total = 0
        st.ticks_done = 0


def _iface_status_for(severity: str, device: NetworkDevice) -> tuple[str, str]:
    down_prob = {"INFO": 0.0, "WARN": 0.04, "ERROR": 0.15, "CRITICAL": 0.45}
    iface = random.choice(device.interfaces)
    status = "DOWN" if random.random() < down_prob.get(severity, 0.0) else "UP"
    return iface, status


def _message_for(st: DeviceState, m: dict) -> str:
    device = st.device
    if st.phase == "BASELINE":
        return f"Telemetría nominal en {device.hostname} ({device.region})"
    fase_es = {"DEGRADING": "degradándose", "CRITICAL": "en estado crítico",
               "RECOVERING": "recuperándose"}[st.phase]
    return (f"[{st.incident_id}] {device.hostname} ({device.region}) {fase_es} — "
            f"{st.metric}: CPU={m['cpu_pct']}% LAT={m['latency_ms']}ms LOSS={m['packet_loss_pct']}%")


def build_record(st: DeviceState, incident_prob: float) -> dict:
    if st.phase == "BASELINE" and random.random() < incident_prob:
        _start_incident(st)

    m = _advance(st)
    iface, iface_status = _iface_status_for(m["severity"], st.device)
    st.last_iface = iface
    device = st.device

    return {
        "ts": datetime.now(timezone.utc),
        "hostname": device.hostname,
        "ip": device.ip,
        "role": device.role,
        "region": device.region,
        "severity": m["severity"],
        "message": _message_for(st, m),
        "cpu_pct": m["cpu_pct"],
        "latency_ms": m["latency_ms"],
        "packet_loss_pct": m["packet_loss_pct"],
        "interface": iface,
        "iface_status": iface_status,
        "peer_ip": st.peer_ip,
    }


# ── Persistencia: pool acotado + batch insert ───────────────────────────────
_pool: "pg_pool.SimpleConnectionPool | None" = None


def init_pool(dsn: str, minconn: int = 1, maxconn: int = 3) -> None:
    global _pool
    _pool = pg_pool.SimpleConnectionPool(minconn=minconn, maxconn=maxconn, dsn=dsn)


def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None


def insert_batch(records: list[dict], retries: int = 3) -> int:
    """Inserta un batch de registros. Devuelve cantidad insertada. Reintenta con backoff.
    Cualquier fallo queda contenido aquí — nunca debe tumbar el loop principal."""
    if not records:
        return 0

    rows = [
        (
            r["ts"], r["hostname"], r["ip"], r["role"], r["region"], r["severity"], r["message"],
            r["cpu_pct"], r["latency_ms"], r["packet_loss_pct"],
            r["interface"], r["iface_status"], r["peer_ip"],
        )
        for r in records
    ]

    for attempt in range(retries + 1):
        conn = None
        try:
            conn = _pool.getconn()
            with conn.cursor() as cur:
                execute_values(cur, _INSERT_SQL, rows, template=_INSERT_TEMPLATE, page_size=200)
            conn.commit()
            return len(rows)
        except Exception as exc:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if attempt == retries:
                log.error(f"Fallo insertando batch tras {retries} reintentos: {exc}")
                return 0
            wait = 0.5 * (2 ** attempt)
            log.warning(f"Error insertando batch (intento {attempt + 1}/{retries}): {exc} — reintentando en {wait:.1f}s")
            time.sleep(wait)
        finally:
            if conn is not None:
                _pool.putconn(conn)
    return 0


# ── Loop principal ───────────────────────────────────────────────────────────
def run(interval: float, incident_prob: float, hours: Optional[float], log_every: int) -> None:
    global _INTERVAL_S
    _INTERVAL_S = interval

    states = [DeviceState(device=d) for d in ALL_DEVICES]
    by_region = {r: sum(1 for d in ALL_DEVICES if d.region == r) for r in REGIONS}
    log.info(f"Dispositivos activos (total={len(ALL_DEVICES)}): "
             + ", ".join(f"{r}={n}" for r, n in by_region.items()))
    log.info(f"Intervalo={interval}s | incident_prob/tick/nodo={incident_prob} | "
             f"CRITICAL sostenido={CRITICAL_MIN_SECONDS/60:.0f}-{CRITICAL_MAX_SECONDS/60:.0f}min | "
             f"webhook={'ON → ' + _webhook_url if _webhook_enabled else 'OFF'} | "
             f"límite={f'{hours}h' if hours else 'infinito'}")

    deadline = (datetime.now(timezone.utc) + timedelta(hours=hours)) if hours else None
    tick = 0
    total_inserted = 0
    start_time = time.time()

    while _running:
        if deadline and datetime.now(timezone.utc) >= deadline:
            log.info("Límite de horas alcanzado. Finalizando.")
            break

        try:
            batch = [build_record(st, incident_prob) for st in states]
        except Exception as exc:
            # Blindaje: un error generando métricas/disparando webhook nunca debe
            # matar el proceso ni saltarse el tick de inserción.
            log.error(f"Error generando batch del tick {tick}: {exc}")
            batch = []

        inserted = insert_batch(batch)
        total_inserted += inserted
        tick += 1

        if tick % log_every == 0:
            uptime_h = (time.time() - start_time) / 3600
            log.info(f"Tick {tick} | registros insertados acumulados={total_inserted} | "
                     f"uptime={uptime_h:.2f}h")

        # dormir en pasos cortos para responder rápido a Ctrl+C
        slept = 0.0
        while slept < interval and _running:
            step = min(0.5, interval - slept)
            time.sleep(step)
            slept += step

    log.info(f"Loop finalizado. Ticks={tick} | registros insertados={total_inserted}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generador continuo multi-región de telemetría "
                                             "+ disparo directo de Webhook (Fase 5 - ML)")
    p.add_argument("--pg-dsn", dest="pg_dsn", default=None,
                    help="DSN de PostgreSQL/TimescaleDB (default: env PG_DSN)")
    p.add_argument("--interval", type=float, default=10.0, help="segundos entre ticks (default: 10)")
    p.add_argument("--incident-prob", type=float, default=0.015,
                    help="probabilidad por tick/nodo de iniciar un incidente en BASELINE (default: 0.015)")
    p.add_argument("--hours", type=float, default=None,
                    help="horas de ejecución antes de detenerse (default: infinito)")
    p.add_argument("--log-every", type=int, default=30, help="ticks entre líneas de resumen (default: 30)")
    p.add_argument("--minconn", type=int, default=1)
    p.add_argument("--maxconn", type=int, default=3)
    p.add_argument("--webhook-url", dest="webhook_url", default=None,
                    help=f'URL del webhook FastAPI (default: env WEBHOOK_URL o "{DEFAULT_WEBHOOK_URL}")')
    p.add_argument("--webhook-workers", type=int, default=4,
                    help="hilos concurrentes para envíos al webhook (default: 4)")
    p.add_argument("--no-webhook", dest="no_webhook", action="store_true",
                    help="deshabilita el disparo de incidentes al webhook (sólo telemetría)")
    return p.parse_args()


def main() -> None:
    global _webhook_url, _webhook_enabled, _webhook_executor

    args = parse_args()
    dsn = args.pg_dsn or os.environ.get("PG_DSN")
    if not dsn:
        log.error("Falta PG_DSN. Pásalo con --pg-dsn o defínelo en tu .env / variable de entorno.")
        sys.exit(1)

    _webhook_url = args.webhook_url or os.environ.get("WEBHOOK_URL") or DEFAULT_WEBHOOK_URL
    _webhook_enabled = (not args.no_webhook) and (_WEBHOOK_HEADERS is not None)
    if args.no_webhook:
        log.info("Webhook deshabilitado explícitamente (--no-webhook).")

    if _webhook_enabled:
        _webhook_executor = ThreadPoolExecutor(max_workers=max(1, args.webhook_workers),
                                                thread_name_prefix="webhook")

    log.info("Conectando a TimescaleDB...")
    init_pool(dsn, minconn=args.minconn, maxconn=args.maxconn)
    log.info("Pool de conexiones inicializado.")

    try:
        run(
            interval=args.interval,
            incident_prob=args.incident_prob,
            hours=args.hours,
            log_every=max(1, args.log_every),
        )
    finally:
        close_pool()
        log.info("Pool de PostgreSQL cerrado.")
        if _webhook_executor is not None:
            _webhook_executor.shutdown(wait=True)
            log.info("Executor de webhooks cerrado (pendientes drenados).")
        log.info("Proceso terminado.")


if __name__ == "__main__":
    main()