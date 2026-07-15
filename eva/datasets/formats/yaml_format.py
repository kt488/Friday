"""YAML dataset format handler."""
import logging
from pathlib import Path
from typing import Any, Dict, List

from eva.core.registry import plugin
from eva.datasets.manager import DatasetFormat

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


@plugin("dataset", "yaml")
class YAMLFormat(DatasetFormat):
    """YAML dataset format handler."""

    def load(self, source: str) -> List[Dict[str, Any]]:
        if yaml is None:
            raise ImportError("PyYAML is required. Install with: pip install pyyaml")
        path = Path(source)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            data = data.get("tests", data.get("data", [data]))
        if not isinstance(data, list):
            raise ValueError(f"YAML root must be a list or dict with 'tests' key, got {type(data)}")
        return data

    def validate(self, data: List[Dict[str, Any]]) -> bool:
        if not isinstance(data, list):
            return False
        for item in data:
            if not isinstance(item, dict):
                return False
        return True

    def save(self, data: List[Dict[str, Any]], destination: str) -> None:
        if yaml is None:
            raise ImportError("PyYAML is required. Install with: pip install pyyaml")
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump({"tests": data, "total": len(data)}, f, default_flow_style=False)
        logger.info("Saved %d tests to %s", len(data), destination)
