"""Base evaluator class for EVA."""
from abc import ABC, abstractmethod
from typing import Any, Dict

from eva.core.registry import PluginRegistry


class BaseEvaluator(ABC):
    """Abstract base for all evaluators.

    Subclasses must implement ``evaluate()`` and set ``name``.
    """

    name: str = "base"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}

    @abstractmethod
    async def evaluate(self, test: Dict[str, Any], output: str) -> Dict[str, float]:
        """Evaluate test output and return score dict.

        Args:
            test: Test definition with 'expected' and optional fields.
            output: The actual output to evaluate.

        Returns:
            Dict of score names to float values (0-100).
        """
