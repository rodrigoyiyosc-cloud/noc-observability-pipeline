"""
log_builder.py — Construcción del registro de log completo (dict plano → CSV/JSON).
"""

import random
from datetime import datetime, timezone
from config import NetworkDevice
from metrics import generate_metrics


_MSG_TEMPLATES = {
    "INFO": [
        "Interface {iface} is {status}",
        "SNMP poll successful on {hostname}",
        "Spanning-tree topology change detected on {iface}",
        "BGP neighbor {peer} keepalive received",
    ],
    "WARN": [
        "High CPU utilization {cpu_pct}% on {hostname}",
        "Interface {iface} is {status} - flapping detected",
        "Latency spike to {latency_ms}ms on {hostname}",
        "BGP neighbor {peer} hold-timer expiring",
    ],
    "ERROR": [
        "Interface {iface} went {status} - link failure",
        "CPU threshold exceeded: {cpu_pct}% on {hostname}",
        "Packet loss {packet_loss_pct}% exceeds SLO on {hostname}",
        "OSPF adjacency lost with {peer}",
    ],
    "CRITICAL": [
        "CRITICAL: {hostname} unreachable - RTT {latency_ms}ms",
        "CRITICAL: Interface {iface} {status} - service impact",
        "CRITICAL: CPU at {cpu_pct}% - process crash risk",
        "CRITICAL: Packet loss {packet_loss_pct}% - circuit down",
    ],
}


def _pick_peer() -> str:
    return f"10.{random.randint(0,2)}.{random.randint(0,5)}.{random.randint(1,254)}"


def build_log_record(device: NetworkDevice) -> dict:
    m    = generate_metrics(device)
    peer = _pick_peer()
    sev  = m["severity"]

    template = random.choice(_MSG_TEMPLATES[sev])
    message  = template.format(
        hostname      = device.hostname,
        iface         = m["interface"],
        status        = m["iface_status"],
        cpu_pct       = m["cpu_pct"],
        latency_ms    = m["latency_ms"],
        packet_loss_pct = m["packet_loss_pct"],
        peer          = peer,
    )

    return {
        "timestamp":         datetime.now(timezone.utc).isoformat(),
        "hostname":          device.hostname,
        "ip":                device.ip,
        "role":              device.role,
        "region":            device.region,
        "severity":          sev,
        "message":           message,
        "cpu_pct":           m["cpu_pct"],
        "latency_ms":        m["latency_ms"],
        "packet_loss_pct":   m["packet_loss_pct"],
        "interface":         m["interface"],
        "iface_status":      m["iface_status"],
        "peer_ip":           peer,
    }