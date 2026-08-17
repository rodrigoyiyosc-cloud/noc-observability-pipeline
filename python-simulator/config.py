"""
config.py — Topología de red por región. La región activa se define vía
la variable de entorno REGION (us-east | eu-west | sa-south).
"""

import os
from dataclasses import dataclass, field
from typing import List

REGION = os.environ.get("REGION", "us-east")

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
    role: str
    region: str = REGION
    interfaces: List[str] = field(default_factory=list)
    cpu_base: float = 30.0
    latency_base: float = 5.0


# Semillas de dispositivos por región. Los hostnames de us-east se mantienen
# SIN prefijo para no romper compatibilidad con datos/dashboards existentes.
_REGION_SEEDS = {
    "us-east": [
        ("core-rtr-01",  "10.0.0.1", "core-router",     ["Gi0/0/0","Gi0/0/1","Gi0/0/2","Te0/1/0"], 45.0, 3.0),
        ("core-rtr-02",  "10.0.0.2", "core-router",     ["Gi0/0/0","Gi0/0/1","Te0/1/0"],            40.0, 3.5),
        ("dist-sw-01",   "10.0.1.1", "distribution-sw", ["Gi1/0/1","Gi1/0/2","Gi1/0/3","Gi1/0/24"], 25.0, 6.0),
        ("dist-sw-02",   "10.0.1.2", "distribution-sw", ["Gi1/0/1","Gi1/0/2","Gi1/0/3"],             22.0, 6.5),
        ("access-sw-01", "10.0.2.1", "access-sw",       ["Fa0/1","Fa0/2","Fa0/3","Fa0/24"],          15.0, 8.0),
    ],
    "eu-west": [
        ("euw1-core-rtr-01",  "10.20.0.1", "core-router",     ["Gi0/0/0","Gi0/0/1","Gi0/0/2","Te0/1/0"], 42.0, 4.0),
        ("euw1-core-rtr-02",  "10.20.0.2", "core-router",     ["Gi0/0/0","Gi0/0/1","Te0/1/0"],            38.0, 4.5),
        ("euw1-dist-sw-01",   "10.20.1.1", "distribution-sw", ["Gi1/0/1","Gi1/0/2","Gi1/0/3","Gi1/0/24"], 24.0, 7.0),
        ("euw1-dist-sw-02",   "10.20.1.2", "distribution-sw", ["Gi1/0/1","Gi1/0/2","Gi1/0/3"],             21.0, 7.5),
        ("euw1-access-sw-01", "10.20.2.1", "access-sw",       ["Fa0/1","Fa0/2","Fa0/3","Fa0/24"],          14.0, 9.0),
    ],
    "sa-south": [
        ("sas1-core-rtr-01",  "10.30.0.1", "core-router",     ["Gi0/0/0","Gi0/0/1","Gi0/0/2","Te0/1/0"], 44.0, 6.0),
        ("sas1-core-rtr-02",  "10.30.0.2", "core-router",     ["Gi0/0/0","Gi0/0/1","Te0/1/0"],            39.0, 6.5),
        ("sas1-dist-sw-01",   "10.30.1.1", "distribution-sw", ["Gi1/0/1","Gi1/0/2","Gi1/0/3","Gi1/0/24"], 26.0, 9.0),
        ("sas1-dist-sw-02",   "10.30.1.2", "distribution-sw", ["Gi1/0/1","Gi1/0/2","Gi1/0/3"],             23.0, 9.5),
        ("sas1-access-sw-01", "10.30.2.1", "access-sw",       ["Fa0/1","Fa0/2","Fa0/3","Fa0/24"],          16.0, 11.0),
    ],
}

if REGION not in _REGION_SEEDS:
    raise ValueError(
        f"REGION '{REGION}' no soportada. Usa una de: {list(_REGION_SEEDS)}"
    )

DEVICES: List[NetworkDevice] = [
    NetworkDevice(
        hostname=h, ip=ip, role=role, region=REGION,
        interfaces=ifaces, cpu_base=cpu_b, latency_base=lat_b,
    )
    for (h, ip, role, ifaces, cpu_b, lat_b) in _REGION_SEEDS[REGION]
]