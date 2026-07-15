"""JSON dataset format handler."""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from eva.datasets.manager import DatasetFormat

logger = logging.getLogger(__name__)


class JSONFormat(DatasetFormat):
    """JSON dataset format handler."""

    def load(self, source: str) -> List[Dict[str, Any]]:
        path = Path(source)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("tests", data.get("data", [data]))
        if not isinstance(data, list):
            raise ValueError(f"JSON root must be a list or dict with 'tests' key, got {type(data)}")
        return data

    def validate(self, data: List[Dict[str, Any]]) -> bool:
        if not isinstance(data, list):
            return False
        required_keys = {"id", "prompt"}
        for item in data:
            if not isinstance(item, dict):
                return False
            if not required_keys.intersection(item.keys()):
                return False
        return True

    def save(self, data: List[Dict[str, Any]], destination: str) -> None:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"tests": data, "total": len(data)}, f, indent=2, ensure_ascii=False)
        logger.info("Saved %d tests to %s", len(data), destination)
