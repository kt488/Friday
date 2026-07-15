"""JSON Schema validator evaluator."""
import json
import logging
from typing import Any, Dict

from eva.core.registry import plugin
from eva.evaluators.base import BaseEvaluator

logger = logging.getLogger(__name__)

try:
    import jsonschema
except ImportError:
    jsonschema = None


@plugin("evaluator", "json_schema_validator")
class JSONSchemaEvaluator(BaseEvaluator):
    """Validates JSON output against a JSON Schema."""

    name = "json_schema_validator"

    async def evaluate(self, test: Dict[str, Any], output: str) -> Dict[str, float]:
        schema: Dict = test.get("json_schema", test.get("schema", {}))
        if not schema:
            return {"formatting": 100.0, "overall": 100.0}

        if jsonschema is None:
            logger.warning("jsonschema not installed, attempting basic validation")
            return await self._basic_validate(output, schema)

        try:
            data = json.loads(output) if isinstance(output, str) else output
            jsonschema.validate(data, schema)
            return {"formatting": 100.0, "overall": 100.0}
        except json.JSONDecodeError:
            return {"formatting": 0.0, "overall": 0.0}
        except jsonschema.ValidationError as e:
            logger.debug("JSONSchema: %s failed: %s", test.get("id"), e.message)
            return {"formatting": 30.0, "overall": 30.0}

    async def _basic_validate(self, output: str, schema: Dict) -> Dict[str, float]:
        """Basic JSON structure validation without jsonschema lib."""
        try:
            data = json.loads(output) if isinstance(output, str) else output
        except json.JSONDecodeError:
            return {"formatting": 0.0, "overall": 0.0}

        score = 100.0
        if "required" in schema and isinstance(data, dict):
            missing = [k for k in schema["required"] if k not in data]
            if missing:
                score -= len(missing) * (100.0 / len(schema["required"]))

        return {"formatting": max(0, score), "overall": max(0, score)}
