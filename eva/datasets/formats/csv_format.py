"""CSV dataset format handler."""
import csv
import io
import logging
from pathlib import Path
from typing import Any, Dict, List

from eva.datasets.manager import DatasetFormat

logger = logging.getLogger(__name__)


class CSVFormat(DatasetFormat):
    """CSV dataset format handler."""

    def load(self, source: str) -> List[Dict[str, Any]]:
        path = Path(source)
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            data = list(reader)
        # Convert numeric strings
        for row in data:
            for k, v in row.items():
                if v is None:
                    continue
                v = v.strip()
                try:
                    if "." in v:
                        row[k] = float(v)
                    else:
                        row[k] = int(v)
                except (ValueError, TypeError):
                    row[k] = v
        return data

    def validate(self, data: List[Dict[str, Any]]) -> bool:
        if not isinstance(data, list):
            return False
        if not data:
            return True
        keys = set(data[0].keys())
        return all(isinstance(r, dict) and set(r.keys()) == keys for r in data)

    def save(self, data: List[Dict[str, Any]], destination: str) -> None:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not data:
            raise ValueError("No data to save")
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            writer.writeheader()
            writer.writerows(data)
        logger.info("Saved %d tests to %s", len(data), destination)
