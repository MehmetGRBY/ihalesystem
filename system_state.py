"""Small persistent operational state; never stores search queries or credentials."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class StateStore:
    def __init__(self, database: Path) -> None:
        self.database = database
        with closing(sqlite3.connect(database, timeout=30)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS operation_state (name TEXT PRIMARY KEY, payload TEXT)"
            )

    def get(self, name: str) -> dict[str, Any]:
        with closing(sqlite3.connect(self.database, timeout=30)) as connection:
            row = connection.execute(
                "SELECT payload FROM operation_state WHERE name=?", (name,)
            ).fetchone()
        return json.loads(row[0]) if row else {}

    def put(self, name: str, value: dict[str, Any]) -> None:
        with closing(sqlite3.connect(self.database, timeout=30)) as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO operation_state VALUES (?,?)", (name, json.dumps(value))
            )

    def search_observation(self, name: str, status: str, count: int) -> None:
        now = datetime.now(UTC).isoformat()
        # Read-modify-write is serialized, including independent provider callbacks.
        with closing(sqlite3.connect(self.database, timeout=30)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM operation_state WHERE name='search_health'"
            ).fetchone()
            health = json.loads(row[0]) if row else {}
            previous = health.get(name, {})
            health[name] = {
                **previous,
                "status": status,
                "checked_at": now,
                "result_count": count,
                "last_error_at": now if status == "error" else previous.get("last_error_at"),
                "last_success_at": now if status != "error" else previous.get("last_success_at"),
            }
            connection.execute(
                "INSERT OR REPLACE INTO operation_state VALUES ('search_health',?)",
                (json.dumps(health),),
            )
