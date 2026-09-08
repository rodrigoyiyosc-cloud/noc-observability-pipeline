"""
tests/test_webhook_endpoints.py — Pruebas unitarias del microservicio FastAPI
(webhook_service/main.py) usando TestClient.

Cubre:
    - GET /health responde 200 OK.
    - POST /alert sin header Authorization responde 401 Unauthorized.

Aislamiento de infraestructura: `main.py` hace, a nivel de módulo,
`from src.orchestrator import orchestrator, checkpointer_pool`, y
`src/orchestrator.py` abre una conexión real a TimescaleDB (PostgresSaver)
en el momento de importarse. Para que estas pruebas sean pruebas UNITARIAS
de verdad — rápidas, deterministas, sin depender de que haya una base de
datos ni credenciales de Groq/Jira disponibles — se reemplaza
`src.orchestrator` en `sys.modules` por un stub ANTES de importar `main`,
igual que se haría con cualquier dependencia externa pesada en un test
unitario. Las pruebas de integración reales contra TimescaleDB viven en
`tests/test_checkpointer_persistence.py`.

Uso:
    python -m pytest tests/test_webhook_endpoints.py -v
"""
import os
import sys
import types

# ── 1. Variables de entorno mínimas requeridas por main.py ──────────────────
# main.py levanta un RuntimeError al importarse si NOC_WEBHOOK_TOKEN no está
# seteado. En CI se inyecta como token de prueba temporal (ver ci.yml); en
# local, si ya hay uno en el entorno/.env, se respeta con setdefault.
os.environ.setdefault("NOC_WEBHOOK_TOKEN", "test-token-ci")

# ── 2. sys.path dinámico: permite importar `main` tanto si este archivo
# corre desde la raíz del repo (main.py vive bajo webhook_service/) como
# desde dentro del contenedor (WORKDIR /app, main.py es top-level). ─────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEBHOOK_SERVICE_DIR = os.path.join(_REPO_ROOT, "webhook_service")
for _p in (_WEBHOOK_SERVICE_DIR, _REPO_ROOT):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

# ── 3. Stub de src.orchestrator: evita que importar `main` dispare una
# conexión real a Postgres (PostgresSaver.setup()) o instancie ChatGroq. ────
if "src.orchestrator" not in sys.modules:
    _fake_orchestrator = types.ModuleType("src.orchestrator")
    _fake_orchestrator.orchestrator = None
    _fake_orchestrator.checkpointer_pool = types.SimpleNamespace(close=lambda: None)

    _fake_src_pkg = sys.modules.get("src") or types.ModuleType("src")
    _fake_src_pkg.orchestrator = _fake_orchestrator

    sys.modules["src"] = _fake_src_pkg
    sys.modules["src.orchestrator"] = _fake_orchestrator

from fastapi.testclient import TestClient

import main  # noqa: E402  (import tardío intencional, después de preparar sys.path/sys.modules)

# Ojo: NO se usa `with TestClient(app) as client:` a propósito. Ese context
# manager dispara el evento `startup` de FastAPI, que abre un
# SimpleConnectionPool de psycopg2 real contra Postgres — otra dependencia
# de infraestructura que estas pruebas de endpoint no necesitan.
client = TestClient(main.app)


def test_health_endpoint_returns_200_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_alert_endpoint_rejects_unauthenticated_requests():
    response = client.post("/alert", json={"status": "firing", "alerts": []})
    assert response.status_code == 401


def test_alert_endpoint_rejects_malformed_bearer_token():
    response = client.post(
        "/alert",
        json={"status": "firing", "alerts": []},
        headers={"Authorization": "Bearer token-incorrecto"},
    )
    assert response.status_code == 401


if __name__ == "__main__":
    test_health_endpoint_returns_200_ok()
    test_alert_endpoint_rejects_unauthenticated_requests()
    test_alert_endpoint_rejects_malformed_bearer_token()
    print("PASSED: test_webhook_endpoints.py")
