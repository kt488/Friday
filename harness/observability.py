"""Friday AI Runtime Harness — Observability & Metrics.

Provides logging, tracing, metrics collection, cost tracking, and
observer-based event emission for monitoring and debugging.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .models import Observation, Severity


class ObservabilityManager:
    """Central observability hub — logging, metrics, tracing, cost tracking."""

    def __init__(self, log_level: str = "INFO", enable_tracing: bool = True):
        self._log_level = self._parse_level(log_level)
        self._enable_tracing = enable_tracing
        self._observations: List[Observation] = []
        self._metrics: Dict[str, List[float]] = defaultdict(list)
        self._counters: Dict[str, int] = defaultdict(int)
        self._traces: Dict[str, Dict[str, Any]] = {}
        self._costs: List[float] = []
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._current_trace_id: Optional[str] = None

    # ── Logging ──────────────────────────────────────────────────────────────

    def log(
        self,
        level: Severity,
        event: str,
        message: str,
        component: str = "harness",
        data: Optional[Dict[str, Any]] = None,
    ) -> Observation:
        """Create and record an observation."""
        if level.value not in ["debug", "info", "warn", "error", "critical"]:
            level = Severity.INFO

        # Filter by log level
        if self._parse_level(level.value) < self._log_level:
            pass  # Still track, just don't surface

        obs = Observation(
            id=uuid.uuid4().hex[:12],
            event=event,
            level=level,
            component=component,
            message=message,
            data=data or {},
            trace_id=self._current_trace_id,
        )
        self._observations.append(obs)

        # Notify handlers
        for handler in self._handlers.get(level.value, []):
            try:
                handler(obs)
            except Exception:
                pass

        return obs

    def debug(self, event: str, message: str, **data) -> Observation:
        return self.log(Severity.DEBUG, event, message, data=data)

    def info(self, event: str, message: str, **data) -> Observation:
        return self.log(Severity.INFO, event, message, data=data)

    def warn(self, event: str, message: str, **data) -> Observation:
        return self.log(Severity.WARN, event, message, data=data)

    def error(self, event: str, message: str, **data) -> Observation:
        return self.log(Severity.ERROR, event, message, data=data)

    def critical(self, event: str, message: str, **data) -> Observation:
        return self.log(Severity.CRITICAL, event, message, data=data)

    # ── Metrics ──────────────────────────────────────────────────────────────

    def record_metric(self, name: str, value: float) -> None:
        """Record a numeric metric value."""
        self._metrics[name].append(value)

    def increment(self, counter: str, amount: int = 1) -> None:
        """Increment a counter."""
        self._counters[counter] += amount

    def timing(self, name: str) -> _Timer:
        """Context manager for timing a block of code."""
        return _Timer(self, name)

    def get_metrics(self) -> Dict[str, Any]:
        """Get aggregated metrics."""
        result = {}
        for name, values in self._metrics.items():
            if values:
                result[name] = {
                    "count": len(values),
                    "sum": round(sum(values), 4),
                    "avg": round(sum(values) / len(values), 4),
                    "min": round(min(values), 4),
                    "max": round(max(values), 4),
                    "last": round(values[-1], 4),
                }
        for name, count in self._counters.items():
            if name in result:
                result[name]["total_count"] = count
            else:
                result[name] = {"total_count": count}
        return result

    # ── Tracing ──────────────────────────────────────────────────────────────

    def start_trace(self, name: str) -> str:
        """Start a new trace span."""
        trace_id = uuid.uuid4().hex[:16]
        self._traces[trace_id] = {
            "name": name,
            "started_at": datetime.utcnow(),
            "spans": [],
            "status": "running",
        }
        self._current_trace_id = trace_id
        return trace_id

    def end_trace(self, trace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """End a trace span and return summary."""
        trace_id = trace_id or self._current_trace_id
        trace = self._traces.get(trace_id)
        if not trace:
            return None

        trace["status"] = "completed"
        trace["duration_ms"] = round(
            (datetime.utcnow() - trace["started_at"]).total_seconds() * 1000, 2
        )
        if self._current_trace_id == trace_id:
            self._current_trace_id = None
        return trace

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        return self._traces.get(trace_id)

    # ── Cost Tracking ────────────────────────────────────────────────────────

    def track_cost(self, tokens: int, cost: float) -> None:
        """Track token usage and cost."""
        self._costs.append(cost)
        self.increment("total_tokens", tokens)
        self.increment("total_cost_cents", int(cost * 100))

    def get_total_cost(self) -> float:
        return round(sum(self._costs), 6)

    # ── Event Handlers ───────────────────────────────────────────────────────

    def on(self, level: str, handler: Callable) -> None:
        """Register a handler for a specific log level."""
        self._handlers[level].append(handler)

    # ── Query ────────────────────────────────────────────────────────────────

    def get_logs(
        self,
        level: Optional[str] = None,
        component: Optional[str] = None,
        limit: int = 100,
    ) -> List[Observation]:
        """Get logs with optional filtering."""
        filtered = self._observations
        if level:
            filtered = [o for o in filtered if o.level == Severity(level)]
        if component:
            filtered = [o for o in filtered if o.component == component]
        return filtered[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get observability statistics."""
        return {
            "total_observations": len(self._observations),
            "log_level": self._log_level.name,
            "tracing_enabled": self._enable_tracing,
            "active_traces": sum(1 for t in self._traces.values() if t["status"] == "running"),
            "metrics_tracked": len(self._metrics),
            "counters": dict(self._counters),
            "total_cost": self.get_total_cost(),
        }

    def clear(self) -> None:
        """Clear all observations, metrics, and traces."""
        self._observations.clear()
        self._metrics.clear()
        self._counters.clear()
        self._traces.clear()
        self._costs.clear()

    @staticmethod
    def _parse_level(level: str) -> int:
        levels = {"debug": 0, "info": 1, "warn": 2, "error": 3, "critical": 4}
        return levels.get(level.lower(), 1)


class _Timer:
    """Context manager for timing code blocks."""

    def __init__(self, mgr: ObservabilityManager, name: str):
        self._mgr = mgr
        self._name = name
        self._start: float = 0.0

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, *args):
        duration = (time.time() - self._start) * 1000
        self._mgr.record_metric(f"timing.{self._name}", duration)
