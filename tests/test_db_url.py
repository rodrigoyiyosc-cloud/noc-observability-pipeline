"""
tests/test_db_url.py — Pruebas unitarias de webhook_service/src/db_url.py.

El módulo se carga por ruta de archivo, no con `from src.db_url import ...`:
test_webhook_endpoints.py reemplaza `src` en sys.modules por un stub, y un
import normal podría fallar según el orden de ejecución de los tests.

Todos los valores son falsos. Ninguna prueba abre conexiones.

Uso:
    python -m pytest tests/test_db_url.py -v
"""
import importlib.util
from pathlib import Path

import pytest

_DB_URL_PATH = (
    Path(__file__).resolve().parents[1] / "webhook_service" / "src" / "db_url.py"
)
_spec = importlib.util.spec_from_file_location("db_url_under_test", _DB_URL_PATH)
db_url = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db_url)

_PG_VARS = {
    "PG_HOST": "db.example.invalid",
    "PG_PORT": "5432",
    "PG_DB": "noc_test",
    "PG_USER": "test_user",
    "PG_PASSWORD": "p@ss/word:1",
}


@pytest.fixture
def pg_env(monkeypatch):
    """Entorno controlado: PG_* falsas y sin PG_DSN."""
    monkeypatch.delenv("PG_DSN", raising=False)
    for name, value in _PG_VARS.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def test_builds_url_from_pg_variables(pg_env):
    url = db_url.build_db_url()
    assert url.drivername == "postgresql+psycopg2"
    assert url.host == "db.example.invalid"
    assert url.port == 5432
    assert url.database == "noc_test"
    assert url.username == "test_user"


def test_password_with_special_characters_is_escaped(pg_env):
    url = db_url.build_db_url()
    assert url.password == "p@ss/word:1"
    rendered = url.render_as_string(hide_password=False)
    assert "p%40ss%2Fword%3A1" in rendered


def test_password_is_hidden_in_safe_rendering(pg_env):
    rendered = db_url.build_db_url().render_as_string(hide_password=True)
    assert "***" in rendered
    assert "p@ss" not in rendered


def test_explicit_pg_dsn_takes_priority(pg_env):
    explicit = "postgresql+psycopg2://a:b@explicit.example.invalid:5432/x"
    pg_env.setenv("PG_DSN", explicit)
    assert db_url.build_db_url() == explicit


@pytest.mark.parametrize(
    "missing", ["PG_HOST", "PG_PORT", "PG_DB", "PG_USER", "PG_PASSWORD"]
)
def test_missing_variable_fails_loudly(pg_env, missing):
    pg_env.delenv(missing)
    with pytest.raises(KeyError):
        db_url.build_db_url()
