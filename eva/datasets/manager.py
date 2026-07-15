"""
Dataset management for EVA.

Multi-format dataset loading, filtering, sampling, partitioning,
and statistics computation.
"""

import json
import logging
import random
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DatasetError(Exception):
    """Raised on dataset operations errors."""


class DatasetFormat(ABC):
    """Base class for dataset format handlers."""

    @abstractmethod
    def load(self, source: str) -> List[Dict[str, Any]]:
        """Load tests from source.
        Args:
            source: File path, URL, or connection string.
        Returns:
            List of test definitions.
        """

    @abstractmethod
    def validate(self, data: List[Dict[str, Any]]) -> bool:
        """Validate dataset structure.
        Args:
            data: List of test definitions.
        Returns:
            True if valid.
        """

    @abstractmethod
    def save(self, data: List[Dict[str, Any]], destination: str) -> None:
        """Save dataset to destination.
        Args:
            data: List of test definitions.
            destination: Output path.
        """


class DatasetManager:
    """Manages test datasets with multi-format support.

    Thread-safe manager for loading, filtering, sampling, and
    partitioning test datasets across multiple formats.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._formats: Dict[str, DatasetFormat] = {}
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self.logger = logger

    def register_format(self, name: str, format_handler: DatasetFormat) -> None:
        """Register a custom format handler."""
        with self._lock:
            self._formats[name] = format_handler

    def load(self, source: str, fmt: str = "auto") -> List[Dict[str, Any]]:
        """Load dataset from source.

        Args:
            source: File path or connection string.
            fmt: Format hint ('auto' for extension detection).

        Returns:
            List of test definitions.
        """
        cache_key = f"{fmt}:{source}"
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        if fmt == "auto":
            ext = Path(source).suffix.lower()
            format_map = {
                ".json": "json", ".yaml": "yaml", ".yml": "yaml",
                ".csv": "csv", ".db": "sqlite", ".sqlite": "sqlite",
                ".sqlite3": "sqlite",
            }
            fmt = format_map.get(ext, "json")

        if fmt not in self._formats:
            raise DatasetError(
                f"Unsupported format: {fmt}. Registered: {list(self._formats.keys())}"
            )

        try:
            handler = self._formats[fmt]
            data = handler.load(source)
            with self._lock:
                self._cache[cache_key] = data
            self.logger.info("Loaded %d tests from %s (%s)", len(data), source, fmt)
            return data
        except Exception as e:
            raise DatasetError(f"Failed to load dataset from {source}: {e}") from e

    def filter(
        self,
        tests: List[Dict[str, Any]],
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        tags: Optional[List[str]] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Filter tests by criteria."""
        result = list(tests)
        if category:
            result = [t for t in result if t.get("category") == category]
        if difficulty:
            result = [t for t in result if t.get("difficulty") == difficulty]
        if tags:
            result = [
                t for t in result
                if all(tag in t.get("tags", []) for tag in tags)
            ]
        if search:
            sl = search.lower()
            result = [
                t for t in result
                if sl in t.get("prompt", "").lower() or sl in t.get("id", "").lower()
            ]
        return result

    def sample(self, tests: List[Dict[str, Any]], n: int, strategy: str = "random") -> List[Dict[str, Any]]:
        """Sample N tests using specified strategy."""
        if n >= len(tests):
            return list(tests)
        if strategy == "stratified":
            return self._stratified_sample(tests, n)
        elif strategy == "balanced":
            return self._balanced_sample(tests, n)
        return random.sample(tests, n)

    def _stratified_sample(self, tests: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
        cats: Dict[str, List[Dict]] = {}
        for t in tests:
            cats.setdefault(t.get("category", "general"), []).append(t)
        spc = max(1, n // max(len(cats), 1))
        result = []
        for ct in cats.values():
            result.extend(random.sample(ct, min(spc, len(ct))))
        remaining = n - len(result)
        if remaining > 0:
            pool = [t for t in tests if t not in result]
            result.extend(random.sample(pool, min(remaining, len(pool))))
        return result[:n]

    def _balanced_sample(self, tests: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
        diffs: Dict[str, List[Dict]] = {}
        for t in tests:
            diffs.setdefault(t.get("difficulty", "medium"), []).append(t)
        pl = max(1, n // max(len(diffs), 1))
        result = []
        for dt in diffs.values():
            result.extend(random.sample(dt, min(pl, len(dt))))
        remaining = n - len(result)
        if remaining > 0:
            pool = [t for t in tests if t not in result]
            result.extend(random.sample(pool, min(remaining, len(pool))))
        return result[:n]

    def split(self, tests: List[Dict[str, Any]], ratio: float = 0.8) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Split dataset into train/test sets."""
        shuffled = list(tests)
        random.shuffle(shuffled)
        idx = int(len(shuffled) * ratio)
        return shuffled[:idx], shuffled[idx:]

    def stats(self, tests: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute dataset statistics."""
        if not tests:
            return {"total": 0, "categories": {}, "difficulties": {}, "tags": {}}
        cats: Dict[str, int] = {}
        diffs: Dict[str, int] = {}
        tags: Dict[str, int] = {}
        for t in tests:
            cats[t.get("category", "unknown")] = cats.get(t.get("category", "unknown"), 0) + 1
            diffs[t.get("difficulty", "unknown")] = diffs.get(t.get("difficulty", "unknown"), 0) + 1
            for tag in t.get("tags", []):
                tags[tag] = tags.get(tag, 0) + 1
        return {"total": len(tests), "categories": cats, "difficulties": diffs, "tags": dict(sorted(tags.items(), key=lambda x: -x[1]))}

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
