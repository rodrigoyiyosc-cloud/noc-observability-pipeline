"""
tests/conftest.py — Variables de entorno de prueba para los tests unitarios.

pytest lee este archivo antes que los tests. main.py exige 10 variables al
importarse (ver _require_env), y sin esto los tests dependen de la terminal
de quien los corre.

Todos los valores son falsos. Solo se completan las variables que falten o
estén vacías; las que ya existan se respetan (por ejemplo, para los tests de
integración contra una base real).
"""
import os

_FAKE_ENV = {
    "NOC_WEBHOOK_TOKEN": "test-token-ci",
    "PG_HOST": "localhost",
    "PG_PORT": "5432",
    "PG_DB": "noc_test",
    "PG_USER": "test_user",
    "PG_PASSWORD": "test-password-not-real",
    "JIRA_URL": "https://jira.example.invalid",
    "JIRA_USER": "test@example.invalid",
    "JIRA_API_TOKEN": "test-token-not-real",
    "JIRA_PROJECT_KEY": "TST",
    "GROQ_API_KEY": "test-groq-key-not-real",
}

for _name, _value in _FAKE_ENV.items():
    if not os.environ.get(_name, "").strip():
        os.environ[_name] = _value