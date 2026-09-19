"""SQLite connection management.

Connections are short-lived and always used through :class:`DatabaseConnection`
(context manager) so they can never leak. All SQL in this project is
parameterised; no query is ever built by string concatenation with record data.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from utils.exceptions import DatabaseError
from utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseConnection:
    """Thin owner of the SQLite database file path."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        """Open a new connection with sane pragmas applied."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as exc:
            raise DatabaseError(f"Cannot open database {self.db_path}: {exc}") from exc

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection; commits on success, rolls back on error."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if isinstance(exc, sqlite3.Error):
                raise DatabaseError(f"Database operation failed: {exc}") from exc
            raise
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Alias of :meth:`session` - explicit transaction semantics."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if isinstance(exc, sqlite3.Error):
                raise DatabaseError(f"Database operation failed: {exc}") from exc
            raise
        finally:
            conn.close()
