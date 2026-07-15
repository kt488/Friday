"""SQLite dataset format handler."""
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from eva.core.registry import plugin
from eva.datasets.manager import DatasetFormat

logger = logging.getLogger(__name__)


@plugin("dataset", "sqlite")
class SQLiteFormat(DatasetFormat):
    """SQLite dataset format handler."""

    TABLE_NAME = "eva_tests"

    def load(self, source: str) -> List[Dict[str, Any]]:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Database not found: {source}")
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(f"SELECT * FROM {self.TABLE_NAME}")
            rows = cursor.fetchall()
            data = []
            for row in rows:
                record = dict(row)
                # Deserialize JSON fields
                for k, v in record.items():
                    if isinstance(v, str) and v.startswith(("[", "{")):
                        try:
                            record[k] = json.loads(v)
                        except (json.JSONDecodeError, ValueError):
                            pass
                data.append(record)
            return data
        finally:
            conn.close()

    def validate(self, data: List[Dict[str, Any]]) -> bool:
        if not isinstance(data, list):
            return False
        return all(isinstance(r, dict) for r in data)

    def save(self, data: List[Dict[str, Any]], destination: str) -> None:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        try:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    id TEXT PRIMARY KEY,
                    prompt TEXT,
                    expected TEXT,
                    category TEXT,
                    difficulty TEXT,
                    tags TEXT,
                    metadata TEXT
                )
            """)
            conn.execute(f"DELETE FROM {self.TABLE_NAME}")
            for record in data:
                conn.execute(
                    f"INSERT OR REPLACE INTO {self.TABLE_NAME} "
                    f"(id, prompt, expected, category, difficulty, tags, metadata) "
                    f"VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.get("id", ""),
                        record.get("prompt", ""),
                        record.get("expected", ""),
                        record.get("category", ""),
                        record.get("difficulty", ""),
                        json.dumps(record.get("tags", [])),
                        json.dumps(
                            {k: v for k, v in record.items()
                             if k not in ("id", "prompt", "expected", "category", "difficulty", "tags")},
                            default=str,
                        ),
                    ),
                )
            conn.commit()
            logger.info("Saved %d tests to %s", len(data), destination)
        finally:
            conn.close()
