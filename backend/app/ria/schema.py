"""Create the RIA tables on first use. The SQL is idempotent (IF NOT EXISTS everywhere)."""

import threading
from pathlib import Path

from sqlalchemy import text

from app.db import get_engine

_SQL = Path(__file__).with_name("schema.sql")
_lock = threading.Lock()
_ready = False


def ensure_schema() -> None:
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        with get_engine().begin() as conn:
            # Serialise concurrent API workers creating the same tables.
            conn.execute(text("SELECT pg_advisory_xact_lock(724001)"))
            conn.exec_driver_sql(_SQL.read_text())
        _ready = True
