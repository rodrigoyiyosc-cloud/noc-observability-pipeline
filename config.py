"""
config.py — Definición de topología de red ficticia y constantes del simulador.
"""

from dataclasses import dataclass, field
from typing import List

SEVERITY_WEIGHTS = {
    "INFO":     0.60,
    "WARN":     0.25,
    "ERROR":    0.10,
    "CRITICAL": 0.05,
}

@dataclass
class NetworkDevice:
    hostname: str
    ip: str
    role: str                       # core-router | distribution-sw | access-sw
    interfaces: List[str] = field(default_factory=list)
    # Baseline de métricas "normales" para este equipo
    cpu_base: float = 30.0          # % CPU idle baseline
    latency_base: float = 5.0       # ms baseline


DEVICES: List[NetworkDevice] = [
    NetworkDevice(
        hostname="core-rtr-01",
        ip="10.0.0.1",
        role="core-router",
        interfaces=["Gi0/0/0", "Gi0/0/1", "Gi0/0/2", "Te0/1/0"],
        cpu_base=45.0,
        latency_base=3.0,
    ),
    NetworkDevice(
        hostname="core-rtr-02",
        ip="10.0.0.2",
        role="core-router",
        interfaces=["Gi0/0/0", "Gi0/0/1", "Te0/1/0"],
        cpu_base=40.0,
        latency_base=3.5,
    ),
    NetworkDevice(
        hostname="dist-sw-01",
        ip="10.0.1.1",
        role="distribution-sw",
        interfaces=["Gi1/0/1", "Gi1/0/2", "Gi1/0/3", "Gi1/0/24"],
        cpu_base=25.0,
        latency_base=6.0,
    ),
    NetworkDevice(
        hostname="dist-sw-02",
        ip="10.0.1.2",
        role="distribution-sw",
        interfaces=["Gi1/0/1", "Gi1/0/2", "Gi1/0/3"],
        cpu_base=22.0,
        latency_base=6.5,
    ),
    NetworkDevice(
        hostname="access-sw-01",
        ip="10.0.2.1",
        role="access-sw",
        interfaces=["Fa0/1", "Fa0/2", "Fa0/3", "Fa0/24"],
        cpu_base=15.0,
        latency_base=8.0,
    ),
]
