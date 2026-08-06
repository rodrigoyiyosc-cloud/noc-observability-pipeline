"""
metrics.py — Generación de métricas de red con anomalías probabilísticas.
"""

import random
import numpy as np
from config import NetworkDevice, SEVERITY_WEIGHTS


def _weighted_severity() -> str:
    severities = list(SEVERITY_WEIGHTS.keys())
    weights    = list(SEVERITY_WEIGHTS.values())
    return random.choices(severities, weights=weights, k=1)[0]


def _jitter(base: float, pct: float = 0.20) -> float:
    """Aplica jitter gaussiano sobre un valor base (±pct del base)."""
    sigma = base * pct
    return round(max(0.0, np.random.normal(base, sigma)), 2)


def _inject_anomaly(severity: str, base_value: float, ceiling: float) -> float:
    """
    En eventos WARN/ERROR/CRITICAL dispara el valor hacia el techo
    para que las métricas sean coherentes con la severidad.
    """
    if severity == "WARN":
        factor = random.uniform(1.5, 2.0)
    elif severity == "ERROR":
        factor = random.uniform(2.0, 3.0)
    elif severity == "CRITICAL":
        factor = random.uniform(3.0, 4.5)
    else:
        return _jitter(base_value)

    return round(min(ceiling, base_value * factor), 2)


def generate_cpu(device: NetworkDevice, severity: str) -> float:
    """CPU usage en %. Techo: 100 %."""
    return _inject_anomaly(severity, device.cpu_base, ceiling=100.0)


def generate_latency(device: NetworkDevice, severity: str) -> float:
    """Latencia RTT en ms. Techo: 2000 ms."""
    return _inject_anomaly(severity, device.latency_base, ceiling=2000.0)


def generate_packet_loss(severity: str) -> float:
    """Packet loss en %. Solo sube en degradaciones."""
    base = 0.0
    if severity == "WARN":
        base = random.uniform(0.5, 2.0)
    elif severity == "ERROR":
        base = random.uniform(2.0, 10.0)
    elif severity == "CRITICAL":
        base = random.uniform(10.0, 35.0)
    return round(base, 2)


def generate_interface_status(device: NetworkDevice, severity: str) -> dict:
    """
    Devuelve estado de interfaces: UP en condiciones normales,
    con probabilidad de DOWN proporcional a la severidad.
    """
    down_prob = {"INFO": 0.0, "WARN": 0.05, "ERROR": 0.20, "CRITICAL": 0.50}
    prob = down_prob.get(severity, 0.0)

    iface = random.choice(device.interfaces)
    status = "DOWN" if random.random() < prob else "UP"
    return {"interface": iface, "status": status}


def generate_metrics(device: NetworkDevice) -> dict:
    """Punto de entrada único: genera todas las métricas de un evento."""
    severity = _weighted_severity()
    iface    = generate_interface_status(device, severity)

    return {
        "severity":       severity,
        "cpu_pct":        generate_cpu(device, severity),
        "latency_ms":     generate_latency(device, severity),
        "packet_loss_pct": generate_packet_loss(severity),
        "interface":      iface["interface"],
        "iface_status":   iface["status"],
    }
