import os
from sqlalchemy.engine import URL


def build_db_url():
    """URL de conexión del Data_Agent desde las variables PG_* que main.py ya valida.
    PG_DSN, si está definida, tiene prioridad (compatibilidad con Docker Compose).
    Sin valor por defecto: si falta algo, falla al arrancar."""
    explicit = os.getenv("PG_DSN")
    if explicit:
        return explicit
    return URL.create(
        "postgresql+psycopg2",
        username=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"],
        host=os.environ["PG_HOST"],
        port=int(os.environ["PG_PORT"]),
        database=os.environ["PG_DB"],
    )