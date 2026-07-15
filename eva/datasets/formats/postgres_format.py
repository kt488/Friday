"""PostgreSQL dataset format handler."""
import json
import logging
from typing import Any, Dict, List, Optional

from eva.core.registry import plugin
from eva.datasets.manager import DatasetFormat

logger = logging.getLogger(__name__)

try:
    import asyncpg
except ImportError:
    asyncpg = None


@plugin("dataset", "postgresql")
class PostgreSQLFormat(DatasetFormat):
    """PostgreSQL dataset format handler.

    Uses a connection string: postgresql://user:pass@host:port/db
    Tests are read from a configurable table (default: eva_tests).
    """

    TABLE_NAME = "eva_tests"

    def __init__(self, table: Optional[str] = None):
        if asyncpg is None:
            raise ImportError("asyncpg is required. Install with: pip install asyncpg")
        self._table = table or self.TABLE_NAME

    def load(self, source: str) -> List[Dict[str, Any]]:
        """Load from PostgreSQL connection string."""
        import asyncio
        return asyncio.run(self._load_async(source))

    async def _load_async(self, source: str) -> List[Dict[str, Any]]:
        conn = await asyncpg.connect(source)
        try:
            rows = await conn.fetch(f"SELECT * FROM {self._table}")
            data = []
            for row in rows:
                record = dict(row)
                for k, v in record.items():
                    if isinstance(v, str) and v.startswith(("[", "{")):
                        try:
                            record[k] = json.loads(v)
                        except (json.JSONDecodeError, ValueError):
                            pass
                data.append(record)
            return data
        finally:
            await conn.close()

    def validate(self, data: List[Dict[str, Any]]) -> bool:
        if not isinstance(data, list):
            return False
        return all(isinstance(r, dict) for r in data)

    def save(self, data: List[Dict[str, Any]], destination: str) -> None:
        """Save to PostgreSQL - executes INSERT statements."""
        import asyncio
        asyncio.run(self._save_async(data, destination))

    async def _save_async(self, data: List[Dict[str, Any]], destination: str) -> None:
        conn = await asyncpg.connect(destination)
        try:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    id TEXT PRIMARY KEY,
                    prompt TEXT,
                    expected TEXT,
                    category TEXT,
                    difficulty TEXT,
                    tags JSONB DEFAULT '[]',
                    metadata JSONB DEFAULT '{{}}'
                )
            """)
            for record in data:
                await conn.execute(
                    f"INSERT INTO {self._table} (id, prompt, expected, category, difficulty, tags, metadata) "
                    f"VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb) "
                    f"ON CONFLICT (id) DO UPDATE SET prompt=$2, expected=$3, category=$4, difficulty=$5, tags=$6::jsonb, metadata=$7::jsonb",
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
                )
            logger.info("Saved %d tests to PostgreSQL %s", len(data), destination)
        finally:
            await conn.close()
